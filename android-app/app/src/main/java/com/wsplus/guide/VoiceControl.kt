package com.wsplus.guide

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.wsplus.guide.ai.AiApiClient
import com.wsplus.guide.ai.AiApiConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

@Composable
internal fun VoiceControlCard(
    config: AiApiConfig,
    feedback: String,
    onCommand: (String) -> Unit,
    onStatus: (String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    var microphoneGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }

    fun captureAndTranscribe() {
        if (!config.isConfigured || busy) return
        busy = true
        scope.launch {
            onStatus("正在录音，请在 5 秒内说出指令")
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    AiApiClient(config).transcribeWav(recordFiveSecondWav())
                }
            }
            result.onSuccess { text ->
                if (text.isBlank()) onStatus("没有听清，请再试一次") else onCommand(text)
            }.onFailure { error ->
                onStatus(error.message?.let { "语音识别失败：$it" } ?: "语音识别失败，请检查网络")
            }
            busy = false
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        microphoneGranted = granted
        if (granted) captureAndTranscribe() else onStatus("未获得麦克风权限")
    }

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("语音控制", fontSize = 23.sp, fontWeight = FontWeight.SemiBold)
            Text(feedback, modifier = Modifier.padding(top = 4.dp, bottom = 8.dp), fontSize = 17.sp)
            Text("录音会发送到已配置的语音识别 API", modifier = Modifier.padding(bottom = 12.dp), fontSize = 14.sp)
            Button(
                onClick = {
                    when {
                        !config.isConfigured -> onStatus("请先设置 AI API 地址、密钥和模型")
                        microphoneGranted -> captureAndTranscribe()
                        else -> permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    }
                },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 56.dp),
            ) {
                Text(if (busy) "正在识别" else "点击说话", fontSize = 18.sp)
            }
        }
    }
}

private fun recordFiveSecondWav(): ByteArray {
    val sampleRate = 16_000
    val channelConfig = AudioFormat.CHANNEL_IN_MONO
    val audioFormat = AudioFormat.ENCODING_PCM_16BIT
    val minBuffer = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)
    check(minBuffer > 0) { "设备不支持 16 kHz 音频录制" }
    val buffer = ByteArray(maxOf(minBuffer, 4096))
    val recorder = AudioRecord.Builder()
        .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
        .setAudioFormat(
            AudioFormat.Builder()
                .setSampleRate(sampleRate)
                .setChannelMask(channelConfig)
                .setEncoding(audioFormat)
                .build(),
        )
        .setBufferSizeInBytes(buffer.size * 2)
        .build()
    check(recorder.state == AudioRecord.STATE_INITIALIZED) { "无法启动麦克风" }

    val pcm = ByteArrayOutputStream(sampleRate * 2 * 5)
    try {
        recorder.startRecording()
        val deadline = System.nanoTime() + 5_000_000_000L
        while (System.nanoTime() < deadline) {
            val read = recorder.read(buffer, 0, buffer.size, AudioRecord.READ_BLOCKING)
            check(read >= 0) { "麦克风读取失败" }
            if (read > 0) pcm.write(buffer, 0, read)
        }
    } finally {
        if (recorder.recordingState == AudioRecord.RECORDSTATE_RECORDING) recorder.stop()
        recorder.release()
    }
    val samples = pcm.toByteArray()
    check(samples.isNotEmpty()) { "没有录到语音" }
    val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        .put("RIFF".toByteArray(Charsets.US_ASCII))
        .putInt(samples.size + 36)
        .put("WAVE".toByteArray(Charsets.US_ASCII))
        .put("fmt ".toByteArray(Charsets.US_ASCII))
        .putInt(16)
        .putShort(1)
        .putShort(1)
        .putInt(sampleRate)
        .putInt(sampleRate * 2)
        .putShort(2)
        .putShort(16)
        .put("data".toByteArray(Charsets.US_ASCII))
        .putInt(samples.size)
        .array()
    return ByteArray(header.size + samples.size).also {
        header.copyInto(it)
        samples.copyInto(it, header.size)
    }
}
