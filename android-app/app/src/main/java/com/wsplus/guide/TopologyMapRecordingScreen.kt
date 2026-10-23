package com.wsplus.guide

import android.Manifest
import android.content.pm.PackageManager
import android.speech.tts.TextToSpeech
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.wsplus.guide.sensor.ImuRecorder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/**
 * 录制页：按屏幕方向自适应布局。
 *
 * 竖屏（上图下栏）：
 *   ┌───────────────┐
 *   │ 状态栏         │
 *   ├───────────────┤
 *   │ 相机预览       │ ← weight(1f)
 *   ├───────────────┤
 *   │ 控制区         │
 *   └───────────────┘
 *
 * 横屏（左图右栏）：
 *   ┌──────────────────┬──────────┐
 *   │                  │ 状态     │
 *   │   相机预览        │ 控制按钮 │ ← 右侧固定宽度
 *   │                  │ IMU 读数 │
 *   └──────────────────┴──────────┘
 *
 * 横屏时右侧栏独立滚动，保证所有信息与按钮都可达，图像始终完整可见。
 */
@Composable
internal fun TopologyMapRecordingScreen(
    mapDirectory: File,
    onSaved: () -> Unit,
    onDiscard: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val configuration = LocalConfiguration.current
    val isLandscape = configuration.screenWidthDp > configuration.screenHeightDp

    val isRecording = remember { AtomicBoolean(false) }
    val isSavingFrame = remember { AtomicBoolean(false) }
    val lastFrameAt = remember { AtomicLong(0L) }
    val nextNode = remember { AtomicInteger(0) }
    var recording by remember { mutableStateOf(false) }
    var cameraGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    var nodeCount by remember { mutableStateOf(0) }
    var status by remember { mutableStateOf("准备录制 ${mapDirectory.name}") }
    var tts by remember { mutableStateOf<TextToSpeech?>(null) }

    val imuRecorder = remember { ImuRecorder(context, mapDirectory) }
    var imuAvailable by remember { mutableStateOf(imuRecorder.isAvailable) }
    var imuSamples by remember { mutableStateOf(0) }
    var imuHeadingChange by remember { mutableStateOf(0f) }
    var imuRotation by remember { mutableStateOf(0f) }
    var imuStats by remember { mutableStateOf<ImuRecorder.ImuStats?>(null) }
    var imuCalibrated by remember { mutableStateOf(false) }
    var qualityHint by remember { mutableStateOf("") }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { cameraGranted = it }

    DisposableEffect(context) {
        val engine = TextToSpeech(context) { result ->
            if (result == TextToSpeech.SUCCESS) tts?.language = Locale.SIMPLIFIED_CHINESE
        }
        tts = engine
        onDispose {
            isRecording.set(false)
            imuRecorder.stop()
            engine.stop()
            engine.shutdown()
            tts = null
        }
    }

    DisposableEffect(recording) {
        if (!recording) return@DisposableEffect onDispose { }
        val job = scope.launch {
            while (recording) {
                delay(500)
                imuSamples = imuRecorder.sampleCount
                imuHeadingChange = imuRecorder.cumulativeHeadingChange
                imuRotation = imuRecorder.cumulativeRotationDeg
                imuCalibrated = imuRecorder.isCalibrated
            }
        }
        onDispose { job.cancel() }
    }

    val onStart: () -> Unit = {
        isRecording.set(true)
        recording = true
        lastFrameAt.set(0L)
        val imuStarted = imuRecorder.start()
        imuAvailable = imuRecorder.isAvailable
        status = if (imuStarted) {
            "正在校准陀螺仪，请保持静止约 1 秒…"
        } else {
            "录制中（仅相机），请缓慢沿路线行走"
        }
        tts?.speak("开始录制，请缓慢沿路线行走", TextToSpeech.QUEUE_FLUSH, null, "topology-recording")
    }
    val onStop: () -> Unit = {
        isRecording.set(false)
        recording = false
        val stats = imuRecorder.stop()
        imuStats = stats
        qualityHint = buildQualityHint(stats, nodeCount)
        status = "录制已停止，可以保存地图"
        tts?.speak("录制已停止", TextToSpeech.QUEUE_FLUSH, null, "topology-recording")
    }

    if (isLandscape) {
        // ========== 横屏：左图 + 右栏 ==========
        Row(modifier = Modifier.fillMaxSize()) {
            // 左：相机预览，占满剩余宽度与全高
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .background(Color.Black),
                contentAlignment = Alignment.Center,
            ) {
                CameraArea(
                    cameraGranted = cameraGranted,
                    onRequestPermission = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                    isRecording = isRecording,
                    isSavingFrame = isSavingFrame,
                    lastFrameAt = lastFrameAt,
                    nextNode = nextNode,
                    mapDirectory = mapDirectory,
                    scope = scope,
                    onNodeSaved = { nodeCount = nextNode.get(); status = "正在录制，请缓慢沿路线行走" },
                    onSaveFailed = {
                        nextNode.decrementAndGet()
                        status = "保存节点失败，请检查存储空间"
                        isRecording.set(false); recording = false; imuRecorder.stop()
                    },
                )
            }
            // 右：信息与控制，固定宽度，可滚动
            Column(
                modifier = Modifier
                    .width(300.dp)
                    .fillMaxHeight()
                    .background(MaterialTheme.colorScheme.surface)
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                StatusBlock(
                    mapName = mapDirectory.name,
                    nodeCount = nodeCount,
                    status = status,
                    recording = recording,
                    imuAvailable = imuAvailable,
                    imuSamples = imuSamples,
                    imuRotation = imuRotation,
                    imuHeadingChange = imuHeadingChange,
                    imuCalibrated = imuCalibrated,
                    compact = true,
                )
                ControlBlock(
                    recording = recording,
                    canSave = !recording && !isSavingFrame.get() && nodeCount >= 2,
                    canDiscard = !recording && !isSavingFrame.get(),
                    onStart = onStart,
                    onStop = onStop,
                    onSaved = onSaved,
                    onDiscard = onDiscard,
                    compact = true,
                )
                if (qualityHint.isNotBlank() && !recording) {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Text(
                            qualityHint,
                            fontSize = 15.sp,
                            modifier = Modifier.padding(8.dp),
                        )
                    }
                }
            }
        }
    } else {
        // ========== 竖屏：上图 + 下栏 ==========
        Column(modifier = Modifier.fillMaxSize()) {
            StatusBlock(
                mapName = mapDirectory.name,
                nodeCount = nodeCount,
                status = status,
                recording = recording,
                imuAvailable = imuAvailable,
                imuSamples = imuSamples,
                imuRotation = imuRotation,
                imuHeadingChange = imuHeadingChange,
                imuCalibrated = imuCalibrated,
                compact = false,
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .background(Color.Black),
                contentAlignment = Alignment.Center,
            ) {
                CameraArea(
                    cameraGranted = cameraGranted,
                    onRequestPermission = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                    isRecording = isRecording,
                    isSavingFrame = isSavingFrame,
                    lastFrameAt = lastFrameAt,
                    nextNode = nextNode,
                    mapDirectory = mapDirectory,
                    scope = scope,
                    onNodeSaved = { nodeCount = nextNode.get(); status = "正在录制，请缓慢沿路线行走" },
                    onSaveFailed = {
                        nextNode.decrementAndGet()
                        status = "保存节点失败，请检查存储空间"
                        isRecording.set(false); recording = false; imuRecorder.stop()
                    },
                )
            }
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(MaterialTheme.colorScheme.surface)
                    .padding(horizontal = 14.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                ControlBlock(
                    recording = recording,
                    canSave = !recording && !isSavingFrame.get() && nodeCount >= 2,
                    canDiscard = !recording && !isSavingFrame.get(),
                    onStart = onStart,
                    onStop = onStop,
                    onSaved = onSaved,
                    onDiscard = onDiscard,
                    compact = false,
                )
                if (qualityHint.isNotBlank() && !recording) {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(90.dp)
                                .verticalScroll(rememberScrollState())
                                .padding(10.dp),
                        ) {
                            Text(qualityHint, fontSize = 15.sp)
                        }
                    }
                }
                if (!recording && nodeCount < 2) {
                    Text(
                        "提示：至少需录制 2 个节点才能保存；建议 30 个以上。",
                        fontSize = 15.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

/** 相机预览区域（含权限引导）。 */
@Composable
private fun CameraArea(
    cameraGranted: Boolean,
    onRequestPermission: () -> Unit,
    isRecording: AtomicBoolean,
    isSavingFrame: AtomicBoolean,
    lastFrameAt: AtomicLong,
    nextNode: AtomicInteger,
    mapDirectory: File,
    scope: kotlinx.coroutines.CoroutineScope,
    onNodeSaved: () -> Unit,
    onSaveFailed: () -> Unit,
) {
    if (!cameraGranted) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text("录制需要相机权限", fontSize = 19.sp, color = Color.White)
            Button(onClick = onRequestPermission, modifier = Modifier.padding(top = 12.dp)) {
                Text("允许使用相机", fontSize = 19.sp)
            }
        }
        return
    }
    CloudCameraPreview(
        modifier = Modifier.fillMaxSize(),
        onFrame = { jpeg ->
            val now = System.currentTimeMillis()
            if (isRecording.get() && now - lastFrameAt.get() >= NODE_INTERVAL_MS &&
                isSavingFrame.compareAndSet(false, true)
            ) {
                lastFrameAt.set(now)
                val index = nextNode.getAndIncrement()
                scope.launch(Dispatchers.IO) {
                    val saved = runCatching {
                        FileOutputStream(File(mapDirectory, "$index.jpg")).use { it.write(jpeg) }
                    }.isSuccess
                    withContext(Dispatchers.Main) {
                        if (saved) onNodeSaved() else onSaveFailed()
                        isSavingFrame.set(false)
                    }
                }
            }
        },
    )
}

/** 状态信息块。compact=true 用于横屏右栏（字号略小、更紧凑）。 */
@Composable
private fun StatusBlock(
    mapName: String,
    nodeCount: Int,
    status: String,
    recording: Boolean,
    imuAvailable: Boolean,
    imuSamples: Int,
    imuRotation: Float,
    imuHeadingChange: Float,
    imuCalibrated: Boolean,
    compact: Boolean,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(horizontal = if (compact) 10.dp else 14.dp, vertical = 8.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                mapName,
                fontSize = if (compact) 15.sp else 18.sp,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f),
            )
            Text(
                "$nodeCount 节点",
                fontSize = if (compact) 15.sp else 18.sp,
                fontWeight = FontWeight.Bold,
                color = if (nodeCount >= 20) Color(0xFF2E7D32) else Color(0xFFB26A00),
            )
        }
        Text(status, fontSize = if (compact) 12.sp else 14.sp, modifier = Modifier.padding(top = 2.dp))
        if (recording || imuSamples > 0) {
            if (imuAvailable && !imuCalibrated && recording) {
                Text(
                    "⏳ 陀螺仪校准中，请保持静止…",
                    fontSize = if (compact) 12.sp else 13.sp,
                    color = Color(0xFFB26A00),
                    modifier = Modifier.padding(top = 2.dp),
                )
            } else if (imuAvailable) {
                Text(
                    "IMU 采样 $imuSamples",
                    fontSize = if (compact) 12.sp else 13.sp,
                    modifier = Modifier.padding(top = 1.dp),
                )
                Text(
                    "累计转角 ${String.format(Locale.US, "%.0f", imuRotation)}°",
                    fontSize = if (compact) 12.sp else 13.sp,
                    fontWeight = FontWeight.SemiBold,
                )

            } else {
                Text(
                    "IMU 不可用（本机无传感器）",
                    fontSize = if (compact) 12.sp else 13.sp,
                    modifier = Modifier.padding(top = 1.dp),
                )
            }
        }
    }
}

/** 控制按钮块。 */
@Composable
private fun ControlBlock(
    recording: Boolean,
    canSave: Boolean,
    canDiscard: Boolean,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onSaved: () -> Unit,
    onDiscard: () -> Unit,
    compact: Boolean,
) {
    val h = if (compact) 44.dp else 52.dp
    val fs = if (compact) 14.sp else 16.sp

    if (compact) {
        // 横屏右栏：纵向排列，便于触达
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Button(onClick = onStart, enabled = !recording,
                modifier = Modifier.fillMaxWidth().height(h)) {
                Text("开始录制", fontSize = fs)
            }
            Button(onClick = onStop, enabled = recording,
                modifier = Modifier.fillMaxWidth().height(h)) {
                Text("停止录制", fontSize = fs)
            }
            Button(onClick = onSaved, enabled = canSave,
                modifier = Modifier.fillMaxWidth().height(h)) {
                Text("保存并使用", fontSize = fs)
            }
            OutlinedButton(onClick = onDiscard, enabled = canDiscard,
                modifier = Modifier.fillMaxWidth().height(h)) {
                Text("放弃并删除", fontSize = fs)
            }
        }
    } else {
        // 竖屏底部：两行两列
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Button(onClick = onStart, enabled = !recording,
                    modifier = Modifier.weight(1f).height(h)) {
                    Text("开始录制", fontSize = fs)
                }
                Button(onClick = onStop, enabled = recording,
                    modifier = Modifier.weight(1f).height(h)) {
                    Text("停止录制", fontSize = fs)
                }
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Button(onClick = onSaved, enabled = canSave,
                    modifier = Modifier.weight(1f).height(h)) {
                    Text("保存并使用", fontSize = fs)
                }
                OutlinedButton(onClick = onDiscard, enabled = canDiscard,
                    modifier = Modifier.weight(1f).height(h)) {
                    Text("放弃并删除", fontSize = fs)
                }
            }
        }
    }
}

/**
 * 根据 IMU 统计与节点数给出采集质量提示。
 * 判据来自论文 §5.1.4：遗留数据航向变化 >10° 的帧占比为 0，导致无法评估转弯。
 */
private fun buildQualityHint(stats: ImuRecorder.ImuStats?, nodes: Int): String {
    if (stats == null) return "未记录 IMU 数据"
    val sb = StringBuilder()
    sb.append("采样 ${stats.sampleCount} 点 · 累计转角 ")
    sb.append(String.format(Locale.US, "%.0f", stats.totalRotationDeg)).append("°\n")

    val problems = mutableListOf<String>()
    if (nodes < 20) problems += "节点偏少（$nodes），建议 ≥30"
    if (nodes > 70) problems += "节点偏多（$nodes），可能走得过慢"
    if (stats.totalRotationDeg < 45f) problems += "累计转角过小，路线可能缺转弯"
    if (stats.sampleCount < 100) problems += "IMU 采样过少，录制时间过短"
    if (problems.isEmpty()) {
        sb.append("✓ 采集质量通过")
    } else {
        sb.append("⚠ ").append(problems.joinToString("；"))
    }
    return sb.toString()
}

private const val NODE_INTERVAL_MS = 1_200L
