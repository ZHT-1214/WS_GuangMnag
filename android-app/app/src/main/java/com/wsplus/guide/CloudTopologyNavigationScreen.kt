package com.wsplus.guide

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Matrix
import android.speech.tts.TextToSpeech
import android.util.Size
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.wsplus.guide.cloud.CloudApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalConfiguration

@Composable
internal fun CloudTopologyNavigationScreen(
    serviceUrl: String,
    apiToken: String,
    sessionId: String,
    routeNodeNames: List<String>,
    destinationNodeName: String,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val api = remember(serviceUrl, apiToken) { CloudApi(serviceUrl, apiToken) }
    val sending = remember { AtomicBoolean(false) }
    val obstacleSending = remember { AtomicBoolean(false) }
    val lastObstacleRequestAt = remember { AtomicLong(0L) }
    val lastObstacleAlertAt = remember { AtomicLong(0L) }
    val guidanceHoldUntil = remember { AtomicLong(0L) }
    val safeObstacleFrames = remember { AtomicInteger(0) }
    var lastObstacleAlert by remember { mutableStateOf("") }
    var lastAnnouncedDirection by remember { mutableStateOf<String?>(null) }
    var candidateNavDirection by remember { mutableStateOf<String?>(null) }
    var candidateNavStreak by remember { mutableStateOf(0) }
    var candidateObstacleState by remember { mutableStateOf("") }
    var candidateObstacleStreak by remember { mutableStateOf(0) }
    var cameraGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    var status by remember { mutableStateOf("正在收集定位所需的连续画面") }
    var obstacleStatus by remember { mutableStateOf("正在启动视觉避障") }
    var direction by remember { mutableStateOf<String?>(null) }
    var currentNodeName by remember { mutableStateOf<String?>(null) }
    var trajectory by remember { mutableStateOf(emptyList<Pair<Float, Float>>()) }
    var nodeStatus by remember { mutableStateOf("") }
    var tts by remember { mutableStateOf<TextToSpeech?>(null) }
    // 仲裁实验事件记录器（用于审稿问题 2：规则 2/3/4 的验证）
    val arbLog = remember(sessionId) { ArbitrationLogger(context, sessionId) }
    var markCount by remember { mutableStateOf(0) }
    var lastMarkLabel by remember { mutableStateOf("") }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { cameraGranted = it }

    DisposableEffect(arbLog) {
        onDispose { arbLog.close() }
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

    fun announceDirection(nextDirection: String?) {
        if (nextDirection == lastAnnouncedDirection) return
        val speech = tts ?: run {
            arbLog.log("TTS_NO_ENGINE", "tts=null")
            return
        }
        val text = when (nextDirection) {
            "left" -> "向左转"
            "right" -> "向右转"
            "forward" -> "向前"
            "back" -> "向后转"
            "arrived" -> "已到达目标位置"
            else -> null
        }
        if (text != null) {
            // 说明：原实现在 speech.isSpeaking 时直接 return，若 TTS 引擎卡在
            // "正在播报"状态，会导致后续所有导航播报被永久丢弃（实测现象：
            // 只有第一句有声音）。改为始终投递，用 QUEUE_FLUSH 保证及时性，
            // 并记录实际投递结果用于诊断。
            val rc = speech.speak(text, TextToSpeech.QUEUE_FLUSH, null, "topology-direction")
            arbLog.log("TTS_NAV", "$nextDirection|$text|rc=$rc|speaking=${speech.isSpeaking}")
            lastAnnouncedDirection = nextDirection
        }
    }

    fun announceObstacleStop(message: String) {
        val now = System.currentTimeMillis()
        guidanceHoldUntil.set(now + GUIDANCE_HOLD_MS)
        safeObstacleFrames.set(0)
        obstacleStatus = message
        if (lastObstacleAlertAt.get() == 0L || now - lastObstacleAlertAt.get() >= OBSTACLE_ALERT_REPEAT_MS) {
            tts?.speak(message, TextToSpeech.QUEUE_FLUSH, null, "topology-obstacle-alert")
            arbLog.log("TTS_STOP", message)
            lastObstacleAlert = message
            lastObstacleAlertAt.set(now)
            lastAnnouncedDirection = null
        }
    }

    fun announceLocalAvoidance(direction: String?) {
        val now = System.currentTimeMillis()
        guidanceHoldUntil.set(now + GUIDANCE_HOLD_MS)
        safeObstacleFrames.set(0)
        val message = "导航方向受阻，${obstacleDirectionText(direction)}，请结合盲杖确认"
        obstacleStatus = message
        if (lastObstacleAlertAt.get() == 0L || now - lastObstacleAlertAt.get() >= OBSTACLE_ALERT_REPEAT_MS) {
            tts?.speak(message, TextToSpeech.QUEUE_FLUSH, null, "topology-obstacle-guidance")
            arbLog.log("TTS_OVERRIDE", "$direction|$message")
            lastObstacleAlert = message
            lastObstacleAlertAt.set(now)
            lastAnnouncedDirection = null
        }
    }

    // 导航页锁定横屏：左图 + 右控制栏，视野更宽、操作更集中。
    // 进入时请求 Activity 横屏，退出时恢复，避免影响其他页面。
    DisposableEffect(Unit) {
        val activity = context.findActivity()
        val original = activity?.requestedOrientation
        activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        onDispose {
            activity?.requestedOrientation =
                original ?: ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
        }
    }

    val configuration = LocalConfiguration.current
    val isLandscape = configuration.orientation == Configuration.ORIENTATION_LANDSCAPE

    // ===== 左：相机画面（固定不动）=====
    @Composable
    fun CameraPane(modifier: Modifier) {
        Box(
            modifier = modifier.background(Color.Black),
            contentAlignment = Alignment.Center,
        ) {
            if (cameraGranted) {
                CloudCameraPreview(
                    modifier = Modifier.fillMaxSize(),
                    onFrame = { jpeg ->
                        if (sending.compareAndSet(false, true)) {
                            scope.launch {
                                val result = withContext(Dispatchers.IO) {
                                    runCatching { api.submitFrame(sessionId, jpeg) }
                                }
                                result.onSuccess { guidance ->
                                    if (guidance.status == "warming_up") {
                                        arbLog.log("NAV_WARMUP", "${guidance.framesReceived}/${guidance.framesRequired}")
                                        status = "正在建立视觉上下文 ${guidance.framesReceived}/${guidance.framesRequired}"
                                    } else {
                                        status = if (guidance.status == "arrived") "已到达目标" else "视觉引导进行中"
                                        arbLog.log(
                                            "NAV_FRAME",
                                            "status=${guidance.status}|node=${guidance.currentNode}|" +
                                                "dir=${guidance.direction}|streak=$candidateNavStreak|" +
                                                "hold=${guidanceHoldUntil.get() - System.currentTimeMillis()}"
                                        )
                                        currentNodeName = guidance.currentNode
                                        trajectory = guidance.trajectory
                                        nodeStatus = listOfNotNull(guidance.currentNode, guidance.destinationNode)
                                            .joinToString(" → ")
                                        if (guidance.direction == candidateNavDirection) {
                                            candidateNavStreak += 1
                                        } else {
                                            candidateNavDirection = guidance.direction
                                            candidateNavStreak = 1
                                        }
                                        if (candidateNavStreak >= NAV_DIRECTION_CONFIRMATIONS) {
                                            direction = guidance.direction
                                            if (System.currentTimeMillis() >= guidanceHoldUntil.get()) {
                                                announceDirection(guidance.direction)
                                            }
                                        }
                                    }
                                }.onFailure { error ->
                                    status = error.message ?: "画面上传失败"
                                }
                                sending.set(false)
                            }
                        }
                        val now = System.currentTimeMillis()
                        if (now - lastObstacleRequestAt.get() >= OBSTACLE_REQUEST_INTERVAL_MS &&
                            obstacleSending.compareAndSet(false, true)
                        ) {
                            lastObstacleRequestAt.set(now)
                            scope.launch {
                                launch {
                                    delay(OBSTACLE_RESPONSE_DEADLINE_MS)
                                    if (obstacleSending.get() && lastObstacleRequestAt.get() == now) {
                                        announceObstacleStop("避障响应延迟，请停下确认")
                                    }
                                }
                                val result = withContext(Dispatchers.IO) {
                                    runCatching { api.detectObstacle(jpeg) }
                                }
                                result.onSuccess { vision ->
                                    val routeDirection = direction
                                    val conflictingDirections = routeDirection in CARDINAL_DIRECTIONS &&
                                        vision.direction in CARDINAL_DIRECTIONS &&
                                        routeDirection != vision.direction
                                    when {
                                        vision.stairs -> {
                                            candidateObstacleState = ""
                                            candidateObstacleStreak = 0
                                            announceObstacleStop("检测到楼梯区域，请停下确认")
                                        }
                                        vision.direction == "unknown" || vision.direction == "none" -> {
                                            candidateObstacleStreak = if (candidateObstacleState == "unknown") {
                                                candidateObstacleStreak + 1
                                            } else {
                                                1
                                            }
                                            candidateObstacleState = "unknown"
                                            if (candidateObstacleStreak >= OBSTACLE_STATE_CONFIRMATIONS) {
                                                announceObstacleStop("避障无法判断通行方向，请停下确认")
                                            } else {
                                                guidanceHoldUntil.set(System.currentTimeMillis() + OBSTACLE_RECHECK_HOLD_MS)
                                                obstacleStatus = "避障方向不稳定，正在复核"
                                            }
                                        }
                                        conflictingDirections -> {
                                            val conflictKey = "${routeDirection}_${vision.direction}"
                                            candidateObstacleStreak = if (candidateObstacleState == conflictKey) {
                                                candidateObstacleStreak + 1
                                            } else {
                                                1
                                            }
                                            candidateObstacleState = conflictKey
                                            if (candidateObstacleStreak >= OBSTACLE_STATE_CONFIRMATIONS) {
                                                announceLocalAvoidance(vision.direction)
                                            } else {
                                                guidanceHoldUntil.set(System.currentTimeMillis() + OBSTACLE_RECHECK_HOLD_MS)
                                                obstacleStatus = "导航与避障建议不同，正在复核"
                                            }
                                        }
                                        else -> {
                                            candidateObstacleState = ""
                                            candidateObstacleStreak = 0
                                            obstacleStatus = "视觉避障已运行：${obstacleDirectionText(vision.direction)}"
                                            if (safeObstacleFrames.incrementAndGet() >= SAFE_FRAMES_TO_RESUME &&
                                                guidanceHoldUntil.get() != 0L &&
                                                System.currentTimeMillis() >= guidanceHoldUntil.get()
                                            ) {
                                                guidanceHoldUntil.set(0L)
                                                lastObstacleAlert = ""
                                                announceDirection(direction)
                                            }
                                        }
                                    }
                                }.onFailure {
                                    announceObstacleStop("视觉避障服务中断，请停下确认")
                                }
                                obstacleSending.set(false)
                            }
                        }
                    }
                )
            } else {
                Column(
                    modifier = Modifier.padding(16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("需要相机权限才能进行视觉定位。", fontSize = 18.sp, color = Color.White)
                    Button(
                        onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                        modifier = Modifier.padding(top = 12.dp).sizeIn(minHeight = 56.dp),
                    ) {
                        Text("允许使用相机", fontSize = 18.sp)
                    }
                }
            }
        }
    }

    // ===== 右：状态与控制（可滚动）=====
    @Composable
    fun ControlPane(modifier: Modifier) {
        Column(
            modifier = modifier
                .background(MaterialTheme.colorScheme.surface)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            OutlinedButton(
                onClick = onBack,
                modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 50.dp),
            ) { Text("结束导航", fontSize = 18.sp) }

            Text("拓扑视觉导航", fontSize = 24.sp, fontWeight = FontWeight.Bold)

            // 目标节点提示
            val isStartAsGoal = routeNodeNames.isNotEmpty() &&
                destinationNodeName == routeNodeNames.firstOrNull()
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = if (isStartAsGoal) Color(0xFFFFE0B2)
                    else MaterialTheme.colorScheme.surfaceVariant,
                ),
            ) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text(
                        "目标：${destinationNodeName}（共 ${routeNodeNames.size} 节点）",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                    if (isStartAsGoal) {
                        Text(
                            "⚠ 目标是起点节点，会立即判定到达。请返回选择终点。",
                            fontSize = 15.sp,
                            modifier = Modifier.padding(top = 6.dp),
                        )
                    }
                }
            }

            // 实时状态
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(status, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                    if (nodeStatus.isNotBlank()) {
                        Text(nodeStatus, modifier = Modifier.padding(top = 6.dp), fontSize = 17.sp)
                    }
                    direction?.let {
                        Text(
                            directionText(it),
                            modifier = Modifier.padding(top = 10.dp),
                            fontSize = 30.sp,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                    Text(
                        obstacleStatus,
                        modifier = Modifier.padding(top = 10.dp),
                        fontSize = 17.sp,
                        fontWeight = FontWeight.Medium,
                    )
                    Text(
                        "避障为视觉辅助，不能测距或替代盲杖；提示冲突或不确定时请停下确认。",
                        modifier = Modifier.padding(top = 6.dp),
                        fontSize = 15.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            NavigationRouteVisualization(
                routeNodeNames = routeNodeNames,
                currentNodeName = currentNodeName,
                destinationNodeName = destinationNodeName,
                trajectory = trajectory,
            )

            // 实验标记面板
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(
                        "实验标记（点击记录时间点）",
                        fontSize = 17.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        OutlinedButton(
                            onClick = { arbLog.mark("STOP_AT_OBSTACLE"); markCount++; lastMarkLabel = "停在障碍前" },
                            modifier = Modifier.weight(1f).height(46.dp),
                        ) { Text("停在障碍前", fontSize = 14.sp) }
                        OutlinedButton(
                            onClick = { arbLog.mark("PASS_OBSTACLE"); markCount++; lastMarkLabel = "绕过障碍" },
                            modifier = Modifier.weight(1f).height(46.dp),
                        ) { Text("绕过障碍", fontSize = 14.sp) }
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        OutlinedButton(
                            onClick = { arbLog.mark("HEARD_OBSTACLE_ALERT"); markCount++; lastMarkLabel = "听到避障告警" },
                            modifier = Modifier.weight(1f).height(46.dp),
                        ) { Text("听到避障告警", fontSize = 14.sp) }
                        OutlinedButton(
                            onClick = { arbLog.mark("NO_NAV_SHOULD_BE_SILENT"); markCount++; lastMarkLabel = "导航应静默" },
                            modifier = Modifier.weight(1f).height(46.dp),
                        ) { Text("导航应静默", fontSize = 14.sp) }
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        OutlinedButton(
                            onClick = { arbLog.mark("NETWORK_CUT"); markCount++; lastMarkLabel = "断网" },
                            modifier = Modifier.weight(1f).height(46.dp),
                        ) { Text("断网", fontSize = 14.sp) }
                        OutlinedButton(
                            onClick = { arbLog.mark("NETWORK_RESTORED"); markCount++; lastMarkLabel = "恢复网络" },
                            modifier = Modifier.weight(1f).height(46.dp),
                        ) { Text("恢复网络", fontSize = 14.sp) }
                    }
                    Button(
                        onClick = { arbLog.mark("FREE_MARK"); markCount++; lastMarkLabel = "自由标记" },
                        modifier = Modifier.fillMaxWidth().padding(top = 6.dp).height(48.dp),
                    ) { Text("＋ 自由标记", fontSize = 16.sp) }
                    if (lastMarkLabel.isNotBlank()) {
                        Text(
                            "最近标记：$lastMarkLabel（共 $markCount 次）",
                            fontSize = 14.sp,
                            modifier = Modifier.padding(top = 6.dp),
                        )
                    }
                    Text(
                        "日志：${arbLog.path().substringAfterLast('/')}",
                        fontSize = 13.sp,
                        modifier = Modifier.padding(top = 4.dp),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }

    if (isLandscape) {
        // 横屏：左图占满剩余宽度 + 右侧 320dp 控制栏
        Row(modifier = Modifier.fillMaxSize()) {
            CameraPane(modifier = Modifier.weight(1f).fillMaxHeight())
            ControlPane(modifier = Modifier.width(320.dp).fillMaxHeight())
        }
    } else {
        // 竖屏：上图（固定比例）+ 下方控制栏
        Column(modifier = Modifier.fillMaxSize()) {
            CameraPane(modifier = Modifier.fillMaxWidth().weight(1f))
            ControlPane(modifier = Modifier.fillMaxWidth().weight(1.1f))
        }
    }
}


private fun directionText(direction: String): String = when (direction) {
    "left" -> "向左"
    "right" -> "向右"
    "forward" -> "向前"
    "back" -> "向后"
    "arrived" -> "已到达"
    else -> "等待指令"
}

private fun obstacleDirectionText(direction: String?): String = when (direction) {
    "left" -> "建议左侧通行"
    "right" -> "建议右侧通行"
    "forward", "ahead" -> "建议前方通行"
    else -> "方向待确认"
}

@Composable
internal fun CloudCameraPreview(
    modifier: Modifier,
    onFrame: (ByteArray) -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember {
        PreviewView(context).apply {
            scaleType = PreviewView.ScaleType.FILL_CENTER
            contentDescription = "拓扑导航相机画面"
        }
    }

    DisposableEffect(lifecycleOwner, previewView) {
        val cameraExecutor = Executors.newSingleThreadExecutor()
        val lastFrameAt = AtomicLong(0L)
        val providerFuture = ProcessCameraProvider.getInstance(context)
        providerFuture.addListener(
            {
                runCatching {
                    val cameraProvider = providerFuture.get()
                    val preview = Preview.Builder().build().also {
                        it.surfaceProvider = previewView.surfaceProvider
                    }
                    val analysis = ImageAnalysis.Builder()
                        .setTargetResolution(Size(640, 480))
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .build()
                    analysis.setAnalyzer(cameraExecutor) { image ->
                        val now = System.currentTimeMillis()
                        if (now - lastFrameAt.get() >= FRAME_INTERVAL_MS) {
                            lastFrameAt.set(now)
                            image.toJpeg()?.let(onFrame)
                        }
                        image.close()
                    }
                    cameraProvider.unbindAll()
                    cameraProvider.bindToLifecycle(
                        lifecycleOwner,
                        CameraSelector.DEFAULT_BACK_CAMERA,
                        preview,
                        analysis,
                    )
                }
            },
            ContextCompat.getMainExecutor(context),
        )
        onDispose {
            if (providerFuture.isDone) runCatching { providerFuture.get().unbindAll() }
            cameraExecutor.shutdown()
        }
    }
    AndroidView(factory = { previewView }, modifier = modifier)
}

private fun ImageProxy.toJpeg(): ByteArray? = runCatching {
    val source = toBitmap()
    val rotation = imageInfo.rotationDegrees
    val rotated = if (rotation == 0) source else {
        Bitmap.createBitmap(
            source,
            0,
            0,
            source.width,
            source.height,
            Matrix().apply { postRotate(rotation.toFloat()) },
            true,
        ).also { source.recycle() }
    }
    val scaled = if (rotated.width > 640) {
        val height = (rotated.height * (640f / rotated.width)).toInt()
        Bitmap.createScaledBitmap(rotated, 640, height, true).also { rotated.recycle() }
    } else {
        rotated
    }
    ByteArrayOutputStream().use { output ->
        scaled.compress(Bitmap.CompressFormat.JPEG, 78, output)
        scaled.recycle()
        output.toByteArray()
    }
}.getOrNull()

private const val FRAME_INTERVAL_MS = 700L
private const val OBSTACLE_REQUEST_INTERVAL_MS = 1_000L
private const val OBSTACLE_RESPONSE_DEADLINE_MS = 7_000L
private const val GUIDANCE_HOLD_MS = 5_000L
private const val OBSTACLE_ALERT_REPEAT_MS = 5_000L
private const val OBSTACLE_RECHECK_HOLD_MS = 1_500L
private const val OBSTACLE_STATE_CONFIRMATIONS = 2
private const val NAV_DIRECTION_CONFIRMATIONS = 2
private const val SAFE_FRAMES_TO_RESUME = 2
private val CARDINAL_DIRECTIONS = setOf("left", "right", "forward")

/** 从 Compose 的 Context 中取出宿主 Activity，用于请求屏幕方向。 */
private fun Context.findActivity(): Activity? {
    var ctx = this
    while (ctx is ContextWrapper) {
        if (ctx is Activity) return ctx
        ctx = ctx.baseContext
    }
    return null
}
