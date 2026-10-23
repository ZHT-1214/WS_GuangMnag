package com.wsplus.guide

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.TextButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.amap.api.maps.CameraUpdateFactory
import com.amap.api.maps.MapView
import com.amap.api.maps.model.LatLng
import com.amap.api.maps.model.MyLocationStyle
import com.amap.api.maps.model.Marker
import com.amap.api.maps.model.MarkerOptions
import com.wsplus.guide.amap.AmapPrivacy
import com.wsplus.guide.ai.AiApiClient
import com.wsplus.guide.ai.AiApiConfig
import com.wsplus.guide.ai.AiApiPreferences
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.foundation.background
import androidx.compose.ui.graphics.Color

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AmapPrivacy.applySavedConsent(this)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    WSPlusApp()
                }
            }
        }
    }
}

private enum class AppScreen {
    HOME,
    WALKING_NAVIGATION,
    TOPOLOGY_NAVIGATION,
    OBSTACLE_AVOIDANCE,
    FIND_OBJECT,
    DESCRIBE_ENVIRONMENT,
    AI_SETTINGS,
}

private data class HomeAction(
    val screen: AppScreen,
    val title: String,
    val description: String,
)

/**
 * Keep voice matching aligned with the original Wukong plugins. In particular,
 * the camera plugin only handles the explicit scene question, rather than any
 * sentence containing "environment" or "describe".
 */
private fun matchVoiceCommand(command: String): AppScreen? {
    val text = command.trim()
    return when {
        "避障" in text -> AppScreen.OBSTACLE_AVOIDANCE
        "拓扑" in text -> AppScreen.TOPOLOGY_NAVIGATION
        text.contains("面前有什么") || text.contains("我面前有什N") ->
            AppScreen.DESCRIBE_ENVIRONMENT
        listOf("帮我寻找", "帮我找一下", "帮我找", "寻找", "查找", "找一下")
            .any { text.contains(it) } -> AppScreen.FIND_OBJECT
        "步行" in text || "导航" in text -> AppScreen.WALKING_NAVIGATION
        else -> null
    }
}

@Composable
private fun WSPlusApp() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var privacyAgreed by rememberSaveable { mutableStateOf(AmapPrivacy.hasAgreed(context)) }
    var currentScreen by rememberSaveable { mutableStateOf(AppScreen.HOME) }
    var voiceFeedback by rememberSaveable { mutableStateOf("说出 App 功能，或提出一般问题") }
    var pendingItemName by rememberSaveable { mutableStateOf("") }
    var aiConfig by remember { mutableStateOf(AiApiPreferences.load(context)) }
    var tts by remember { mutableStateOf<TextToSpeech?>(null) }
    // 用于在"清除上次路线"后强制刷新首页的"继续上次路线"卡片
    var homeRefreshKey by remember { mutableIntStateOf(0) }

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

    if (!privacyAgreed) {
        AmapPrivacyScreen(
            onAgree = {
                AmapPrivacy.agree(context)
                privacyAgreed = true
            },
            onExit = { (context as? Activity)?.finish() },
        )
        return
    }

    if (currentScreen != AppScreen.HOME) {
        BackHandler { currentScreen = AppScreen.HOME }
    }

    when (currentScreen) {
        AppScreen.HOME -> HomeScreen(
            aiConfig = aiConfig,
            voiceFeedback = voiceFeedback,
            onVoiceStatus = { voiceFeedback = it },
            onOpen = { currentScreen = it },
            onResumeLastRoute = {
                LastRouteStore.markUsed(context)
                currentScreen = AppScreen.TOPOLOGY_NAVIGATION
            },
            onClearLastRoute = {
                LastRouteStore.clear(context)
                homeRefreshKey += 1
            },
            refreshKey = homeRefreshKey,
            onVoiceCommand = { command ->
                val normalized = command.trim()
                val target = matchVoiceCommand(normalized)
                if (target == null) {
                    if (!aiConfig.isConfigured) {
                        voiceFeedback = "未匹配到 App 功能。请先完成 AI API 设置。"
                    } else {
                        voiceFeedback = "未匹配到 App 功能，正在请求 AI"
                        scope.launch {
                            val result = withContext(Dispatchers.IO) {
                                runCatching { AiApiClient(aiConfig).chat(normalized) }
                            }
                            result.onSuccess { answer ->
                                voiceFeedback = answer.take(240)
                                tts?.speak(answer, TextToSpeech.QUEUE_FLUSH, null, "ai-fallback-answer")
                            }.onFailure { error ->
                                voiceFeedback = error.message?.let { "AI 问答失败：$it" } ?: "AI 问答失败，请检查网络和 API 设置"
                            }
                        }
                    }
                } else {
                    voiceFeedback = "已识别：$normalized"
                    if (target == AppScreen.FIND_OBJECT) pendingItemName = extractObjectName(normalized)
                    currentScreen = target
                }
            },
        )
        AppScreen.AI_SETTINGS -> AiApiSettingsScreen(
            config = aiConfig,
            onBack = { currentScreen = AppScreen.HOME },
            onSave = { updated ->
                runCatching { AiApiPreferences.save(context, updated) }
                    .onSuccess {
                        aiConfig = updated
                        voiceFeedback = "AI API 设置已保存"
                    }
                    .onFailure { error -> voiceFeedback = error.message ?: "AI API 设置保存失败" }
            },
        )
        AppScreen.WALKING_NAVIGATION -> AmapWalkingScreen(
            onBack = { currentScreen = AppScreen.HOME },
        )
        AppScreen.TOPOLOGY_NAVIGATION -> TopologyMapsScreen(
            onBack = { currentScreen = AppScreen.HOME },
        )
        AppScreen.OBSTACLE_AVOIDANCE -> VisionFeatureScreen(
            feature = VisionFeature.OBSTACLE,
            onBack = { currentScreen = AppScreen.HOME },
        )
        AppScreen.FIND_OBJECT -> VisionFeatureScreen(
            feature = VisionFeature.FIND_OBJECT,
            initialItemName = pendingItemName,
            onBack = { currentScreen = AppScreen.HOME },
        )
        AppScreen.DESCRIBE_ENVIRONMENT -> VisionFeatureScreen(
            feature = VisionFeature.DESCRIBE,
            aiConfig = aiConfig,
            onBack = { currentScreen = AppScreen.HOME },
        )
    }
}

@Composable
private fun AmapPrivacyScreen(onAgree: () -> Unit, onExit: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("定位服务说明", fontSize = 30.sp, fontWeight = FontWeight.Bold)
        Text(
            text = "步行导航将使用高德地图 SDK 获取精确位置、路线和网络状态。只有同意后才会初始化高德 SDK。相机与麦克风权限将在使用对应功能时单独申请。",
            modifier = Modifier.padding(top = 20.dp),
            fontSize = 19.sp,
            lineHeight = 30.sp,
        )
        Button(
            onClick = onAgree,
            modifier = Modifier.fillMaxWidth().padding(top = 28.dp).sizeIn(minHeight = 60.dp),
        ) {
            Text("同意并继续", fontSize = 19.sp)
        }
        OutlinedButton(
            onClick = onExit,
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp).sizeIn(minHeight = 56.dp),
        ) {
            Text("暂不同意，退出", fontSize = 18.sp)
        }
    }
}

@Composable
private fun HomeScreen(
    aiConfig: AiApiConfig,
    voiceFeedback: String,
    onVoiceStatus: (String) -> Unit,
    onOpen: (AppScreen) -> Unit,
    onVoiceCommand: (String) -> Unit,
    onResumeLastRoute: () -> Unit,
    onClearLastRoute: () -> Unit,
    refreshKey: Int,
) {
    val context = LocalContext.current
    var typedCommand by rememberSaveable { mutableStateOf("") }
    val keyboardController = LocalSoftwareKeyboardController.current
    val lastRoute = remember(refreshKey) { LastRouteStore.load(context) }

    // 功能网格：2 行 × 3 列，最后一格为"AI 设置"
    val gridItems = listOf(
        GridItem(AppScreen.WALKING_NAVIGATION, "步行导航", "🧭"),
        GridItem(AppScreen.TOPOLOGY_NAVIGATION, "拓扑导航", "🗺"),
        GridItem(AppScreen.OBSTACLE_AVOIDANCE, "视觉避障", "👁"),
        GridItem(AppScreen.FIND_OBJECT, "寻找物品", "🔍"),
        GridItem(AppScreen.DESCRIBE_ENVIRONMENT, "环境描述", "💬"),
        GridItem(AppScreen.AI_SETTINGS, "AI 设置", "⚙"),
    )

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // ===== 标题栏（固定 48dp）=====
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "随行导航",
                fontSize = 26.sp,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f),
            )
            Text(
                if (aiConfig.isConfigured) "AI 已配置" else "AI 未配置",
                fontSize = 13.sp,
                color = if (aiConfig.isConfigured) Color(0xFF2E7D32)
                else MaterialTheme.colorScheme.error,
            )
        }

        // ===== 继续上次路线（紧凑条，仅在有记录时显示）=====
        if (lastRoute != null) {
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(onClick = onResumeLastRoute),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer,
                ),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            "继续上次路线",
                            fontSize = 17.sp,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                        Text(
                            "${lastRoute.displayName} · ${LastRouteStore.relativeTime(lastRoute.lastUsedAt)}",
                            fontSize = 13.sp,
                            color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.8f),
                        )
                    }
                    Text(
                        "开始 ›",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                }
            }
        }

        // ===== 功能网格（2 行 × 3 列，弹性填充）=====
        Column(
            modifier = Modifier.fillMaxWidth().weight(1f),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            gridItems.chunked(3).forEach { rowItems ->
                Row(
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    rowItems.forEach { item ->
                        GridCard(
                            item = item,
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                            onClick = { onOpen(item.screen) },
                        )
                    }
                    // 补齐空位（保持 3 列对齐）
                    repeat(3 - rowItems.size) {
                        Spacer(modifier = Modifier.weight(1f))
                    }
                }
            }
        }

        // ===== 语音反馈（单行，最多 2 行）=====
        if (voiceFeedback.isNotBlank()) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                ),
            ) {
                Text(
                    voiceFeedback,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                    fontSize = 14.sp,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }

        // ===== 底部输入栏（固定）=====
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = typedCommand,
                onValueChange = { typedCommand = it },
                modifier = Modifier.weight(1f),
                singleLine = true,
                textStyle = MaterialTheme.typography.bodyMedium,
                placeholder = { Text("输入命令，如：讲个笑话", fontSize = 14.sp) },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(
                    onSend = {
                        val message = typedCommand.trim()
                        if (message.isNotEmpty()) {
                            typedCommand = ""
                            keyboardController?.hide()
                            onVoiceCommand(message)
                        }
                    },
                ),
            )
            Button(
                enabled = typedCommand.isNotBlank(),
                onClick = {
                    val message = typedCommand.trim()
                    if (message.isNotEmpty()) {
                        typedCommand = ""
                        keyboardController?.hide()
                        onVoiceCommand(message)
                    }
                },
                modifier = Modifier.sizeIn(minWidth = 72.dp, minHeight = 56.dp),
            ) { Text("发送", fontSize = 15.sp) }
        }
    }
}

/** 网格入口数据。 */
private data class GridItem(
    val screen: AppScreen,
    val title: String,
    val icon: String,
)

/** 单个网格卡片：图标 + 标题，整格可点击。 */
@Composable
private fun GridCard(
    item: GridItem,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Card(
        modifier = modifier
            .clickable(onClick = onClick)
            .semantics {
                role = Role.Button
                contentDescription = item.title
            },
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(
            modifier = Modifier.fillMaxSize().padding(8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(item.icon, fontSize = 30.sp)
            Text(
                item.title,
                modifier = Modifier.padding(top = 4.dp),
                fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}


/**
 * 「继续上次路线」卡片：一键回到上次的拓扑导航会话。
 *
 * 这是调试与演示时最常用的入口——省去"进拓扑导航 → 选地图 → 选节点 → 建会话"四步。
 */
@Composable
private fun ContinueLastRouteCard(
    route: LastRouteStore.LastRoute,
    onClick: () -> Unit,
    onClear: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer,
        ),
    ) {
        Column(modifier = Modifier.padding(18.dp)) {
            Text(
                "继续上次路线",
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            Text(
                text = route.displayName,
                modifier = Modifier.padding(top = 8.dp),
                fontSize = 19.sp,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            Text(
                text = "上次使用：${LastRouteStore.relativeTime(route.lastUsedAt)}",
                modifier = Modifier.padding(top = 4.dp),
                fontSize = 15.sp,
                color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.75f),
            )
            Button(
                onClick = onClick,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 14.dp)
                    .sizeIn(minHeight = 64.dp),
            ) {
                Text("一键开始导航", fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
            }
            TextButton(
                onClick = onClear,
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
            ) {
                Text("清除记录", fontSize = 15.sp)
            }
        }
    }
}

private fun extractObjectName(command: String): String {
    val prefixes = listOf("帮我寻找", "帮我找一下", "帮我找", "寻找", "查找", "找一下", "找")
    val remainder = prefixes.firstNotNullOfOrNull { prefix ->
        if (prefix in command) command.substringAfter(prefix) else null
    }.orEmpty()
    return remainder
        .trim()
        .removePrefix("一下")
        .removePrefix("我的")
        .removePrefix("一个")
        .removePrefix("那个")
        .trim(' ', '。', '，', '？', '?')
}

@Composable
private fun ActionCard(action: HomeAction, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .semantics {
                role = Role.Button
                contentDescription = "${action.title}，${action.description}"
            },
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(18.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(action.title, fontSize = 24.sp, fontWeight = FontWeight.Bold)
                Text(
                    text = action.description,
                    modifier = Modifier.padding(top = 6.dp),
                    fontSize = 16.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                "›",
                fontSize = 34.sp,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(start = 12.dp),
            )
        }
    }
}

@Composable
private fun PendingFeatureScreen(
    title: String,
    status: String,
    primaryAction: String,
    onBack: () -> Unit,
) {
    FeaturePage(title = title, status = status, onBack = onBack) {
        Button(
            onClick = { },
            enabled = false,
            modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 56.dp),
        ) {
            Text(primaryAction, fontSize = 18.sp)
        }
    }
}

@Composable
private fun CameraFeatureScreen(title: String, status: String, onBack: () -> Unit) {
    val context = LocalContext.current
    var cameraGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
        onResult = { cameraGranted = it },
    )

    FeaturePage(title = title, status = status, onBack = onBack) {
        if (cameraGranted) {
            CameraPreview(modifier = Modifier.fillMaxWidth().height(420.dp))
            Text(
                text = "相机预览正常",
                modifier = Modifier.padding(top = 12.dp),
                fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold,
            )
        } else {
            Text("需要相机权限才能采集环境画面。", fontSize = 18.sp)
            Button(
                onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                modifier = Modifier.fillMaxWidth().padding(top = 16.dp).sizeIn(minHeight = 56.dp),
            ) {
                Text("允许使用相机", fontSize = 18.sp)
            }
        }
    }
}

@Composable
private fun FeaturePage(
    title: String,
    status: String,
    onBack: () -> Unit,
    content: @Composable () -> Unit,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            OutlinedButton(
                onClick = onBack,
                modifier = Modifier.sizeIn(minWidth = 96.dp, minHeight = 52.dp),
            ) {
                Text("返回", fontSize = 18.sp)
            }
        }
        item { Text(title, fontSize = 30.sp, fontWeight = FontWeight.Bold) }
        item {
            Card(modifier = Modifier.fillMaxWidth()) {
                Text(status, modifier = Modifier.padding(16.dp), fontSize = 18.sp)
            }
        }
        item { content() }
    }
}

@Composable
private fun CameraPreview(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember {
        PreviewView(context).apply {
            scaleType = PreviewView.ScaleType.FILL_CENTER
            contentDescription = "手机后置相机实时预览"
        }
    }

    DisposableEffect(lifecycleOwner, previewView) {
        val providerFuture = ProcessCameraProvider.getInstance(context)
        providerFuture.addListener(
            {
                runCatching {
                    val cameraProvider = providerFuture.get()
                    val preview = Preview.Builder().build().also {
                        it.surfaceProvider = previewView.surfaceProvider
                    }
                    cameraProvider.unbindAll()
                    cameraProvider.bindToLifecycle(
                        lifecycleOwner,
                        CameraSelector.DEFAULT_BACK_CAMERA,
                        preview,
                    )
                }
            },
            ContextCompat.getMainExecutor(context),
        )

        onDispose {
            if (providerFuture.isDone) {
                runCatching { providerFuture.get().unbindAll() }
            }
        }
    }

    AndroidView(factory = { previewView }, modifier = modifier)
}
