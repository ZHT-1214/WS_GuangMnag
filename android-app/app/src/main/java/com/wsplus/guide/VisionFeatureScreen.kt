package com.wsplus.guide

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.speech.tts.TextToSpeech
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.Image
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.wsplus.guide.ai.AiApiClient
import com.wsplus.guide.ai.AiApiConfig
import com.wsplus.guide.cloud.CloudApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

internal enum class VisionFeature { OBSTACLE, FIND_OBJECT, DESCRIBE }

@Composable
internal fun VisionFeatureScreen(
    feature: VisionFeature,
    initialItemName: String = "",
    aiConfig: AiApiConfig = AiApiConfig(),
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val preferences = remember { context.getSharedPreferences("cloud_service", Context.MODE_PRIVATE) }
    val serviceUrl = remember { preferences.getString("service_url", "").orEmpty() }
    val apiToken = remember { preferences.getString("api_token", "").orEmpty() }
    val api = remember(serviceUrl, apiToken) { runCatching { CloudApi(serviceUrl, apiToken) }.getOrNull() }
    val requesting = remember { AtomicBoolean(false) }
    var cameraGranted by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    var latestFrame by remember { mutableStateOf<ByteArray?>(null) }
    var submittedFrame by remember { mutableStateOf<ByteArray?>(null) }
    var active by rememberSaveable { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var itemName by rememberSaveable { mutableStateOf(initialItemName) }
    var status by remember { mutableStateOf(initialStatus(feature, serviceUrl, aiConfig)) }
    var resultText by remember { mutableStateOf("") }
    var tts by remember { mutableStateOf<TextToSpeech?>(null) }

    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        cameraGranted = it
        if (!it) status = "未获得相机权限，无法采集画面"
    }

    DisposableEffect(context) {
        val engine = TextToSpeech(context) { result ->
            if (result == TextToSpeech.SUCCESS) tts?.language = Locale.SIMPLIFIED_CHINESE
        }
        tts = engine
        onDispose {
            engine.stop()
            engine.shutdown()
            tts = null
        }
    }

    androidx.compose.runtime.LaunchedEffect(resultText) {
        if (resultText.isNotBlank()) {
            tts?.speak(resultText, TextToSpeech.QUEUE_FLUSH, null, "vision-result")
        }
    }

    fun submit(frame: ByteArray, request: (CloudApi, ByteArray) -> String) {
        val cloudApi = api
        if (cloudApi == null) {
            status = "请先在拓扑地图页配置云服务地址"
            return
        }
        if (!requesting.compareAndSet(false, true)) return
        submittedFrame = frame.copyOf()
        busy = true
        scope.launch {
            val response = withContext(Dispatchers.IO) {
                runCatching { request(cloudApi, frame) }
            }
            response.onSuccess {
                status = "识别完成"
                resultText = it
            }.onFailure {
                status = it.message ?: "云端识别失败"
            }
            busy = false
            requesting.set(false)
        }
    }

    fun submitDescription(frame: ByteArray) {
        if (api == null && !aiConfig.isConfigured) {
            status = "请配置云服务地址或 AI API"
            return
        }
        if (!requesting.compareAndSet(false, true)) return
        submittedFrame = frame.copyOf()
        busy = true
        status = if (api != null) "正在把当前图片发送给云服务" else "正在把当前图片发送给 AI 分析"
        scope.launch {
            val response = withContext(Dispatchers.IO) {
                runCatching {
                    val cloudResult = api?.let { cloud ->
                        runCatching { cloud.describeEnvironment(frame).message }
                    }
                    if (cloudResult?.isSuccess == true) {
                        "云服务已分析本次显示的图片" to cloudResult.getOrThrow()
                    } else {
                        if (!aiConfig.isConfigured) {
                            throw (cloudResult?.exceptionOrNull() ?: IllegalStateException("请配置 AI API"))
                        }
                        val source = if (api != null) "云服务不可用，已由 AI 分析本次图片" else "AI 已分析本次显示的图片"
                        source to AiApiClient(aiConfig).describeImage(frame)
                    }
                }
            }
            response.onSuccess {
                status = it.first
                resultText = it.second
            }.onFailure {
                status = it.message ?: "图片描述失败，请检查云服务或 AI API"
            }
            busy = false
            requesting.set(false)
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            OutlinedButton(onClick = onBack, modifier = Modifier.sizeIn(minWidth = 96.dp, minHeight = 52.dp)) {
                Text("返回", fontSize = 20.sp)
            }
        }
        item { Text(featureTitle(feature), fontSize = 28.sp, fontWeight = FontWeight.Bold) }
        item {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(status, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
                    if (resultText.isNotBlank()) Text(resultText, modifier = Modifier.padding(top = 10.dp), fontSize = 22.sp)
                }
            }
        }
        submittedFrame?.let { frame ->
            item {
                val bitmap = remember(frame) {
                    BitmapFactory.decodeByteArray(frame, 0, frame.size)?.asImageBitmap()
                }
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text("本次发送给识别服务的画面", fontSize = 19.sp, fontWeight = FontWeight.SemiBold)
                        if (bitmap != null) {
                            Image(
                                bitmap = bitmap,
                                contentDescription = "本次上传到环境识别服务的相机画面",
                                contentScale = ContentScale.Fit,
                                modifier = Modifier.fillMaxWidth().height(260.dp).padding(top = 8.dp),
                            )
                        } else {
                            Text("上传画面解码失败", modifier = Modifier.padding(top = 8.dp), fontSize = 19.sp)
                        }
                    }
                }
            }
        }
        item {
            if (cameraGranted) {
                CloudCameraPreview(
                    modifier = Modifier.fillMaxWidth().height(420.dp),
                    onFrame = { latestFrame = it },
                )
            } else {
                Button(
                    onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                    modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 56.dp),
                ) { Text("允许使用相机", fontSize = 20.sp) }
            }
        }
        when (feature) {
            VisionFeature.OBSTACLE -> {
                item {
                    Text("语义识别只能作为辅助提示，不能测距或替代盲杖。遇到楼梯、画面异常或不确定提示时，请停下确认。", fontSize = 19.sp)
                    Button(
                        onClick = {
                            active = !active
                            status = if (active) "正在上传画面进行辅助判断" else "已暂停视觉避障"
                            if (!active) resultText = ""
                        },
                        enabled = cameraGranted && api != null,
                        modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 56.dp),
                    ) { Text(if (active) "暂停检测" else "开始检测", fontSize = 20.sp) }
                }
            }
            VisionFeature.FIND_OBJECT -> {
                item {
                    OutlinedTextField(
                        value = itemName,
                        onValueChange = { itemName = it },
                        label = { Text("要寻找的物品") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Button(
                        onClick = {
                            latestFrame?.let { frame ->
                                submit(frame) { cloud, image -> cloud.findObject(image, itemName.trim()).message }
                            }
                        },
                        enabled = cameraGranted && !busy && latestFrame != null && itemName.isNotBlank() && api != null,
                        modifier = Modifier.fillMaxWidth().padding(top = 10.dp).sizeIn(minHeight = 56.dp),
                    ) { Text(if (busy) "正在识别" else "寻找物品", fontSize = 20.sp) }
                }
            }
            VisionFeature.DESCRIBE -> {
                item {
                    Text("优先调用云服务描述当前画面；云服务不可用时，使用支持图片输入的 AI API。", fontSize = 19.sp)
                    Button(
                        onClick = {
                            latestFrame?.let { frame ->
                                submitDescription(frame)
                            }
                        },
                        enabled = cameraGranted && !busy && latestFrame != null && (api != null || aiConfig.isConfigured),
                        modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 56.dp),
                    ) { Text(if (busy) "正在分析图片" else "描述当前环境", fontSize = 20.sp) }
                }
            }
        }
    }

    androidx.compose.runtime.LaunchedEffect(latestFrame, active, feature) {
        val frame = latestFrame ?: return@LaunchedEffect
        if (feature != VisionFeature.OBSTACLE || !active || api == null || busy) return@LaunchedEffect
        submit(frame) { cloud, image -> cloud.detectObstacle(image).message }
    }
}

private fun featureTitle(feature: VisionFeature) = when (feature) {
    VisionFeature.OBSTACLE -> "视觉避障"
    VisionFeature.FIND_OBJECT -> "寻找物品"
    VisionFeature.DESCRIBE -> "环境描述"
}

private fun initialStatus(feature: VisionFeature, serviceUrl: String, aiConfig: AiApiConfig) = when {
    feature == VisionFeature.DESCRIBE && serviceUrl.isBlank() && !aiConfig.isConfigured -> "请配置云服务地址或 AI API"
    feature == VisionFeature.DESCRIBE -> "点击按钮描述当前画面，优先使用云服务"
    serviceUrl.isBlank() -> "请先在拓扑地图页配置云服务地址"
    feature == VisionFeature.OBSTACLE -> "辅助避障待启动"
    feature == VisionFeature.FIND_OBJECT -> "输入物品名称后识别当前画面"
    else -> "等待拍摄画面"
}
