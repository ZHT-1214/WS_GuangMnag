package com.wsplus.guide.cloud

import android.content.Context
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.ConnectionPool
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.TimeUnit
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

data class CloudHealth(
    val status: String,
    val gpuVisible: Boolean,
    val inferenceReady: Boolean,
    val yosoVisionReady: Boolean,
    val voiceAsrReady: Boolean,
    val inferenceError: String?,
)

data class CloudMap(
    val id: String,
    val nodeCount: Int,
)

data class CloudNavigationSession(
    val id: String,
    val status: String,
    val inferenceReady: Boolean,
    val message: String,
)

data class CloudGuidance(
    val status: String,
    val direction: String?,
    val currentNode: String?,
    val destinationNode: String?,
    val framesReceived: Int?,
    val framesRequired: Int?,
    val trajectory: List<Pair<Float, Float>> = emptyList(),
)

data class VisionResponse(
    val message: String,
    val direction: String? = null,
    val found: Boolean? = null,
    val position: String? = null,
    val description: String? = null,
    val objects: List<String> = emptyList(),
    val stairs: Boolean = false,
)

/**
 * 全局共享的 OkHttpClient 单例。
 *
 * 复用同一个实例可共享连接池与线程池，避免每次进入页面重新建立 TCP 连接、
 * 重复 TLS 握手（公网 HTTPS 下每次握手约 20~50 ms）。对导航这种高频请求
 * （700 ms/次）收益明显，且不改变任何请求语义与响应内容。
 */
internal object SharedHttp {
    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(12, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .writeTimeout(90, TimeUnit.SECONDS)
        .connectionPool(ConnectionPool(maxIdleConnections = 8, keepAliveDuration = 5, TimeUnit.MINUTES))
        .retryOnConnectionFailure(true)
        .build()
}

class CloudApi(
    baseUrl: String,
    private val apiToken: String = "",
) {
    private val baseUrl = baseUrl.trim().trimEnd('/').also {
        require(it.startsWith("https://") || it.startsWith("http://")) {
            "服务地址必须以 http:// 或 https:// 开头"
        }
    }

    // 复用全局单例 OkHttpClient：共享连接池与线程池，避免每次切换页面重建
    // TCP 连接、重复 TLS 握手（公网 HTTPS 下单次握手可达 20~50 ms）。
    private val client: OkHttpClient = SharedHttp.client

    fun health(): CloudHealth {
        val json = executeJson(Request.Builder().url("$baseUrl/health").get())
        val capabilities = json.optJSONObject("capabilities")
        val yoso = json.optJSONObject("yoso")
        return CloudHealth(
            status = json.getString("status"),
            gpuVisible = json.optBoolean("gpu_visible", false),
            inferenceReady = json.optBoolean("inference_ready", false),
            yosoVisionReady = capabilities?.optBoolean("yoso_vision", false)
                ?: yoso?.optBoolean("inference_ready", false)
                ?: false,
            voiceAsrReady = capabilities?.optBoolean("voice_asr", false) ?: false,
            inferenceError = json.optString("inference_error").takeIf { it.isNotBlank() && it != "null" },
        )
    }

    fun uploadMap(context: Context, mapDirectory: File): CloudMap {
        val archive = createMapArchive(context, mapDirectory)
        return try {
            val body = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart(
                    "file",
                    "${mapDirectory.name}.zip",
                    archive.asRequestBody("application/zip".toMediaType()),
                )
                .build()
            val json = executeJson(Request.Builder().url("$baseUrl/v1/maps").post(body))
            CloudMap(id = json.getString("id"), nodeCount = json.getInt("node_count"))
        } finally {
            archive.delete()
        }
    }

    fun createNavigationSession(mapId: String, destinationNode: String): CloudNavigationSession {
        val payload = JSONObject()
            .put("map_id", mapId)
            .put("destination_node", destinationNode)
            .toString()
            .toRequestBody("application/json".toMediaType())
        val json = executeJson(
            Request.Builder().url("$baseUrl/v1/navigation/sessions").post(payload),
        )
        return CloudNavigationSession(
            id = json.getString("session_id"),
            status = json.getString("status"),
            inferenceReady = json.getBoolean("inference_ready"),
            message = json.getString("message"),
        )
    }

    fun submitFrame(sessionId: String, jpeg: ByteArray): CloudGuidance {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                "frame.jpg",
                jpeg.toRequestBody("image/jpeg".toMediaType()),
            )
            .build()
        val envelope = executeJson(
            Request.Builder().url("$baseUrl/v1/navigation/sessions/$sessionId/frames").post(body),
        )
        val result = envelope.getJSONObject("result")
        val trajectoryJson = result.optJSONArray("trajectory")
        val trajectory = buildList {
            if (trajectoryJson != null) {
                for (index in 0 until trajectoryJson.length()) {
                    val point = trajectoryJson.optJSONArray(index) ?: continue
                    if (point.length() >= 2) {
                        add(point.optDouble(0).toFloat() to point.optDouble(1).toFloat())
                    }
                }
            }
        }
        return CloudGuidance(
            status = result.getString("status"),
            direction = result.optString("direction").takeIf { it.isNotBlank() && it != "null" },
            currentNode = result.optString("current_node").takeIf { it.isNotBlank() },
            destinationNode = result.optString("destination_node").takeIf { it.isNotBlank() },
            framesReceived = if (result.has("frames_received")) result.getInt("frames_received") else null,
            framesRequired = if (result.has("frames_required")) result.getInt("frames_required") else null,
            trajectory = trajectory,
        )
    }

    fun detectObstacle(jpeg: ByteArray): VisionResponse =
        postVision("/v1/vision/obstacle", jpeg)

    fun findObject(jpeg: ByteArray, item: String): VisionResponse {
        val encodedItem = java.net.URLEncoder.encode(item, Charsets.UTF_8.name())
        return postVision("/v1/vision/find?item=$encodedItem", jpeg)
    }

    fun describeEnvironment(jpeg: ByteArray): VisionResponse =
        postVision("/v1/vision/describe", jpeg)

    fun transcribeVoice(wav: ByteArray): String {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                "command.wav",
                wav.toRequestBody("audio/wav".toMediaType()),
            )
            .build()
        return executeJson(
            Request.Builder().url("$baseUrl/v1/voice/transcribe").post(body),
        ).getString("text")
    }

    private fun postVision(path: String, jpeg: ByteArray): VisionResponse {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                "frame.jpg",
                jpeg.toRequestBody("image/jpeg".toMediaType()),
            )
            .build()
        val json = executeJson(Request.Builder().url("$baseUrl$path").post(body))
        val objectsJson = json.optJSONArray("objects")
        val objects = buildList {
            if (objectsJson != null) {
                for (index in 0 until objectsJson.length()) add(objectsJson.optString(index))
            }
        }
        return VisionResponse(
            message = json.optString("message").ifBlank { json.optString("description") },
            direction = json.optString("direction").takeIf { it.isNotBlank() && it != "null" },
            found = if (json.has("found")) json.optBoolean("found") else null,
            position = json.optString("position").takeIf { it.isNotBlank() && it != "null" },
            description = json.optString("description").takeIf { it.isNotBlank() && it != "null" },
            objects = objects,
            stairs = json.optBoolean("stairs", false),
        )
    }

    private fun executeJson(builder: Request.Builder): JSONObject {
        if (apiToken.isNotBlank()) builder.header("Authorization", "Bearer $apiToken")
        client.newCall(builder.build()).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching { JSONObject(body).opt("detail")?.toString() }.getOrNull()
                error(detail ?: "云服务请求失败：HTTP ${response.code}")
            }
            return JSONObject(body)
        }
    }
}

private fun createMapArchive(context: Context, mapDirectory: File): File {
    val archive = File.createTempFile("topology-", ".zip", context.cacheDir)
    ZipOutputStream(FileOutputStream(archive)).use { zip ->
        mapDirectory.walkTopDown()
            .filter { it.isFile && it.name.matches(Regex("\\d+\\.(jpg|jpeg|png)", RegexOption.IGNORE_CASE)) }
            .forEach { node ->
                val relative = node.relativeTo(mapDirectory).invariantSeparatorsPath
                zip.putNextEntry(ZipEntry(relative))
                node.inputStream().use { it.copyTo(zip) }
                zip.closeEntry()
            }
        // 附带 IMU 记录（若录制时已采集），供服务端/离线分析使用。
        // 服务端 _node_files 仅识别数字命名的图片，因此 imu.csv 不会影响节点计数。
        val imu = File(mapDirectory, "imu.csv")
        if (imu.isFile && imu.length() > 0) {
            zip.putNextEntry(ZipEntry("imu.csv"))
            imu.inputStream().use { it.copyTo(zip) }
            zip.closeEntry()
        }
    }
    return archive
}
