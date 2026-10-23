package com.wsplus.guide.ai

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.security.KeyStore
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class AiApiConfig(
    val baseUrl: String = "https://api.openai.com/v1",
    val apiKey: String = "",
    val chatModel: String = "gpt-4o-mini",
    val transcriptionModel: String = "whisper-1",
    val answerPrompt: String = "你是一个盲人辅助助手小光，请用两百字回答：",
) {
    val isConfigured: Boolean
        get() = baseUrl.startsWith("https://") && apiKey.isNotBlank() &&
            chatModel.isNotBlank() && transcriptionModel.isNotBlank()
}

object AiApiPreferences {
    private const val PREFS = "ai_api_settings"
    private const val KEY_BASE_URL = "base_url"
    private const val KEY_API_KEY = "encrypted_api_key"
    private const val KEY_CHAT_MODEL = "chat_model"
    private const val KEY_TRANSCRIPTION_MODEL = "transcription_model"
    private const val KEY_ANSWER_PROMPT = "answer_prompt"
    private const val KEYSTORE_ALIAS = "wsplus_ai_api_key"

    fun load(context: Context): AiApiConfig {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return AiApiConfig(
            baseUrl = prefs.getString(KEY_BASE_URL, null) ?: AiApiConfig().baseUrl,
            apiKey = prefs.getString(KEY_API_KEY, null)?.let(::decrypt).orEmpty(),
            chatModel = prefs.getString(KEY_CHAT_MODEL, null) ?: AiApiConfig().chatModel,
            transcriptionModel = prefs.getString(KEY_TRANSCRIPTION_MODEL, null)
                ?: AiApiConfig().transcriptionModel,
            answerPrompt = prefs.getString(KEY_ANSWER_PROMPT, null) ?: AiApiConfig().answerPrompt,
        )
    }

    fun save(context: Context, config: AiApiConfig) {
        require(config.baseUrl.startsWith("https://")) { "AI API 地址必须使用 HTTPS" }
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        prefs.edit()
            .putString(KEY_BASE_URL, config.baseUrl.trim().trimEnd('/'))
            .putString(KEY_API_KEY, config.apiKey.takeIf(String::isNotBlank)?.let(::encrypt))
            .putString(KEY_CHAT_MODEL, config.chatModel.trim())
            .putString(KEY_TRANSCRIPTION_MODEL, config.transcriptionModel.trim())
            .putString(KEY_ANSWER_PROMPT, config.answerPrompt.trim())
            .apply()
    }

    private fun encrypt(value: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(
            ByteBuffer.allocate(cipher.iv.size + encrypted.size).put(cipher.iv).put(encrypted).array(),
            Base64.NO_WRAP,
        )
    }

    private fun decrypt(value: String): String? = runCatching {
        val payload = Base64.decode(value, Base64.NO_WRAP)
        val buffer = ByteBuffer.wrap(payload)
        val iv = ByteArray(12).also(buffer::get)
        val encrypted = ByteArray(buffer.remaining()).also(buffer::get)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(128, iv))
        String(cipher.doFinal(encrypted), Charsets.UTF_8)
    }.getOrNull()

    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(KEYSTORE_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(
                KeyGenParameterSpec.Builder(
                    KEYSTORE_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build(),
            )
            generateKey()
        }
    }
}

class AiApiClient(config: AiApiConfig) {
    private val config = config.copy(baseUrl = config.baseUrl.trim().trimEnd('/'))
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(75, TimeUnit.SECONDS)
        .writeTimeout(45, TimeUnit.SECONDS)
        .callTimeout(90, TimeUnit.SECONDS)
        .build()

    fun transcribeWav(wav: ByteArray): String {
        checkConfigured()
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                "command.wav",
                wav.toRequestBody("audio/wav".toMediaType()),
            )
            .addFormDataPart("model", config.transcriptionModel)
            .build()
        val json = execute(
            Request.Builder()
                .url(endpoint("audio/transcriptions"))
                .header("Authorization", "Bearer ${config.apiKey}")
                .post(body)
                .build(),
        )
        return json.optString("text").trim().ifEmpty { error("语音识别没有返回文字") }
    }

    fun chat(text: String): String {
        checkConfigured()
        val payload = JSONObject()
            .put("model", config.chatModel)
            .put(
                "messages",
                JSONArray().put(
                    JSONObject()
                        .put("role", "system")
                        .put("content", config.answerPrompt.trim()),
                ).put(
                    JSONObject()
                        .put("role", "user")
                        .put("content", text),
                ),
            )
            .put("stream", false)
            .put("max_tokens", 400)
        val json = execute(
            Request.Builder()
                .url(endpoint("chat/completions"))
                .header("Authorization", "Bearer ${config.apiKey}")
                .post(payload.toString().toRequestBody("application/json".toMediaType()))
                .build(),
        )
        return json.optJSONArray("choices")
            ?.optJSONObject(0)
            ?.optJSONObject("message")
            ?.optString("content")
            ?.trim()
            ?.ifEmpty { null }
            ?: error("AI 服务没有返回答案")
    }

    fun describeImage(jpeg: ByteArray): String {
        checkConfigured()
        val image = "data:image/jpeg;base64," + Base64.encodeToString(jpeg, Base64.NO_WRAP)
        val content = JSONArray()
            .put(
                JSONObject()
                    .put("type", "text")
                    .put(
                        "text",
                        "请描述这张照片里实际可见的环境和主要物体。只说有把握的内容；看不清或不能确定时明确说明不确定，不要猜测位置、距离或安全性。用简短、适合语音播报的中文回答。",
                    ),
            )
            .put(
                JSONObject()
                    .put("type", "image_url")
                    .put(
                        "image_url",
                        JSONObject().put("url", image).put("detail", "high"),
                    ),
            )
        val payload = JSONObject()
            .put("model", config.chatModel)
            .put(
                "messages",
                JSONArray().put(JSONObject().put("role", "user").put("content", content)),
            )
            .put("stream", false)
            .put("max_tokens", 400)
        val json = execute(
            Request.Builder()
                .url(endpoint("chat/completions"))
                .header("Authorization", "Bearer ${config.apiKey}")
                .post(payload.toString().toRequestBody("application/json".toMediaType()))
                .build(),
        )
        return json.optJSONArray("choices")
            ?.optJSONObject(0)
            ?.optJSONObject("message")
            ?.optString("content")
            ?.trim()
            ?.ifEmpty { null }
            ?: error("AI 服务没有返回图片描述")
    }

    private fun endpoint(path: String): String = "$configBase/$path"

    private val configBase: String
        get() = config.baseUrl

    private fun checkConfigured() {
        check(config.isConfigured) { "请先完成 AI API 设置" }
    }

    private fun execute(request: Request): JSONObject {
        client.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching { JSONObject(body).optString("error") }.getOrNull()
                error(detail?.takeIf(String::isNotBlank) ?: "AI 服务请求失败：HTTP ${response.code}")
            }
            return JSONObject(body)
        }
    }
}
