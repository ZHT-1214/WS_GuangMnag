package com.wsplus.guide

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.wsplus.guide.ai.AiApiClient
import com.wsplus.guide.ai.AiApiConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
internal fun AiApiSettingsScreen(
    config: AiApiConfig,
    onBack: () -> Unit,
    onSave: (AiApiConfig) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var baseUrl by remember(config) { mutableStateOf(config.baseUrl) }
    var apiKey by remember(config) { mutableStateOf(config.apiKey) }
    var chatModel by remember(config) { mutableStateOf(config.chatModel) }
    var transcriptionModel by remember(config) { mutableStateOf(config.transcriptionModel) }
    var answerPrompt by remember(config) { mutableStateOf(config.answerPrompt) }
    var status by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val edited = AiApiConfig(baseUrl, apiKey, chatModel, transcriptionModel, answerPrompt)

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            OutlinedButton(onClick = onBack, modifier = Modifier.sizeIn(minWidth = 96.dp, minHeight = 52.dp)) {
                Text("返回")
            }
        }
        item { Text("AI API 设置", fontSize = 28.sp, fontWeight = FontWeight.Bold) }
        item {
            Text(
                "只在语音命令未匹配到 App 功能时，把识别出的文字发送给聊天模型。语音片段发送给转写 API。请使用兼容 OpenAI 格式的 HTTPS 服务；相机画面不会发送给这个聊天接口。",
                fontSize = 19.sp,
                lineHeight = 23.sp,
            )
        }
        item {
            OutlinedTextField(
                value = baseUrl,
                onValueChange = { baseUrl = it },
                label = { Text("API 地址") },
                placeholder = { Text("https://api.openai.com/v1") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        item {
            OutlinedTextField(
                value = apiKey,
                onValueChange = { apiKey = it },
                label = { Text("API Key") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        item {
            OutlinedTextField(
                value = chatModel,
                onValueChange = { chatModel = it },
                label = { Text("聊天模型") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        item {
            OutlinedTextField(
                value = transcriptionModel,
                onValueChange = { transcriptionModel = it },
                label = { Text("语音转写模型") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        item {
            OutlinedTextField(
                value = answerPrompt,
                onValueChange = { answerPrompt = it },
                label = { Text("回答提示词") },
                placeholder = { Text("你是一个盲人辅助助手小光，请用两百字回答：") },
                minLines = 3,
                maxLines = 6,
                modifier = Modifier.fillMaxWidth(),
            )
            Text(
                "键盘输入未匹配到 App 功能时，这段文字会作为系统提示词发送给聊天模型。留空也可以。",
                modifier = Modifier.padding(top = 6.dp),
                fontSize = 17.sp,
            )
        }
        item {
            Text("API Key 使用 Android Keystore 加密后保存在本机。语音识别与 AI 问答由你配置的服务商处理。", fontSize = 17.sp)
            if (status.isNotBlank()) Text(status, modifier = Modifier.padding(top = 8.dp), fontSize = 19.sp)
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(
                    enabled = !busy,
                    onClick = {
                        runCatching {
                            require(edited.baseUrl.startsWith("https://")) { "API 地址必须使用 HTTPS" }
                            require(edited.apiKey.isNotBlank()) { "请填写 API Key" }
                            require(edited.chatModel.isNotBlank()) { "请填写聊天模型" }
                            require(edited.transcriptionModel.isNotBlank()) { "请填写语音转写模型" }
                            onSave(edited)
                            status = "设置已保存"
                        }.onFailure { status = it.message ?: "设置无效" }
                    },
                    modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 56.dp),
                ) { Text("保存设置", fontSize = 20.sp) }
                OutlinedButton(
                    enabled = !busy && edited.isConfigured,
                    onClick = {
                        busy = true
                        status = "正在测试聊天 API"
                        scope.launch {
                            val result = withContext(Dispatchers.IO) {
                                runCatching { AiApiClient(edited).chat("请只回答：连接成功") }
                            }
                            status = result.fold(
                                onSuccess = { "连接成功：${it.take(80)}" },
                                onFailure = { it.message ?: "API 请求失败" },
                            )
                            busy = false
                        }
                    },
                    modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 56.dp),
                ) { Text(if (busy) "正在测试" else "测试聊天 API", fontSize = 20.sp) }
            }
        }
    }
}
