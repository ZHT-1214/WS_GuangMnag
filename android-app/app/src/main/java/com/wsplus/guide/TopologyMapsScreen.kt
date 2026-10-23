package com.wsplus.guide

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.wsplus.guide.cloud.CloudApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import java.util.zip.ZipInputStream

private data class TopologyMap(
    val id: String,
    val name: String,
    val directory: File,
    val nodes: List<File>,
)

@Composable
internal fun TopologyMapsScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val maps = remember { mutableStateListOf<TopologyMap>() }
    var selectedMapId by rememberSaveable { mutableStateOf("") }
    var selectedNodeName by rememberSaveable { mutableStateOf("") }
    var selectedMap by remember { mutableStateOf<TopologyMap?>(null) }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("导入由拓扑图工具生成的 ZIP 文件") }
    var pendingDelete by remember { mutableStateOf<TopologyMap?>(null) }
    var showRecordDialog by remember { mutableStateOf(false) }
    var newMapName by rememberSaveable { mutableStateOf("") }
    var recordingDirectory by remember { mutableStateOf<File?>(null) }
    val cloudPrefs = remember { context.getSharedPreferences(CLOUD_PREFS_NAME, Context.MODE_PRIVATE) }
    var serviceUrl by rememberSaveable { mutableStateOf(cloudPrefs.getString(KEY_SERVICE_URL, "").orEmpty()) }
    var apiToken by rememberSaveable { mutableStateOf(cloudPrefs.getString(KEY_API_TOKEN, "").orEmpty()) }
    var cloudConnected by remember { mutableStateOf(false) }
    var inferenceReady by remember { mutableStateOf(false) }
    var obstacleReady by remember { mutableStateOf(false) }
    var cloudStatus by remember { mutableStateOf("尚未测试云服务") }
    var activeSessionId by rememberSaveable { mutableStateOf("") }

    val importLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri != null) {
            scope.launch {
                busy = true
                message = "正在导入拓扑图…"
                val result = withContext(Dispatchers.IO) { importTopologyZip(context, uri) }
                if (result.isSuccess) {
                    maps.clear()
                    maps.addAll(withContext(Dispatchers.IO) { loadTopologyMaps(context) })
                    val imported = result.getOrThrow()
                    selectedMapId = imported.id
                    selectedMap = imported
                    selectedNodeName = imported.nodes.lastOrNull()?.name.orEmpty()
                    saveSelection(context, imported.id, selectedNodeName)
                    message = "已导入 ${imported.name}，共 ${imported.nodes.size} 个节点"
                } else {
                    message = result.exceptionOrNull()?.message ?: "导入失败，请检查 ZIP 文件"
                }
                busy = false
            }
        }
    }

    LaunchedEffect(Unit) {
        maps.addAll(withContext(Dispatchers.IO) { loadTopologyMaps(context) })
        selectedMapId = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_MAP_ID, "").orEmpty()
        selectedNodeName = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_NODE_NAME, "").orEmpty()
    }

    LaunchedEffect(maps.size, selectedMapId) {
        selectedMap = maps.firstOrNull { it.id == selectedMapId }
        selectedMap?.let { map ->
            if (map.nodes.none { it.name == selectedNodeName }) {
                selectedNodeName = map.nodes.lastOrNull()?.name.orEmpty()
            }
        }
    }

    recordingDirectory?.let { directory ->
        TopologyMapRecordingScreen(
            mapDirectory = directory,
            onSaved = {
                scope.launch {
                    val refreshed = withContext(Dispatchers.IO) { loadTopologyMaps(context) }
                    maps.clear()
                    maps.addAll(refreshed)
                    val recorded = refreshed.firstOrNull { it.directory.canonicalFile == directory.canonicalFile }
                    if (recorded != null) {
                        selectedMapId = recorded.id
                        selectedNodeName = recorded.nodes.lastOrNull()?.name.orEmpty()
                        saveSelection(context, recorded.id, selectedNodeName)
                        message = "已录制 ${recorded.name}，共 ${recorded.nodes.size} 个节点"
                    }
                    recordingDirectory = null
                }
            },
            onDiscard = {
                scope.launch {
                    withContext(Dispatchers.IO) { directory.deleteRecursively() }
                    recordingDirectory = null
                    message = "已放弃本次录制"
                }
            },
        )
        return
    }

    if (showRecordDialog) {
        AlertDialog(
            onDismissRequest = { showRecordDialog = false },
            title = { Text("录制陌生环境") },
            text = {
                Column {
                    OutlinedTextField(
                        value = newMapName,
                        onValueChange = { newMapName = it },
                        label = { Text("地图名称") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Text(
                        "录制时不会提供导航，请由熟悉环境的陪同者带领，沿可通行路线行走。",
                        modifier = Modifier.padding(top = 12.dp),
                        fontSize = 17.sp,
                    )
                }
            },
            confirmButton = {
                TextButton(
                    enabled = newMapName.isNotBlank(),
                    onClick = {
                        val name = newMapName.trim()
                        scope.launch {
                            val directory = withContext(Dispatchers.IO) { createRecordingDirectory(context, name) }
                            if (directory != null) {
                                recordingDirectory = directory
                                showRecordDialog = false
                                newMapName = ""
                            } else {
                                message = "无法创建地图，请更换名称后重试"
                                showRecordDialog = false
                            }
                        }
                    },
                ) { Text("继续") }
            },
            dismissButton = {
                TextButton(onClick = { showRecordDialog = false }) { Text("取消") }
            },
        )
    }

    if (activeSessionId.isNotBlank()) {
        CloudTopologyNavigationScreen(
            serviceUrl = serviceUrl,
            apiToken = apiToken,
            sessionId = activeSessionId,
            routeNodeNames = selectedMap?.nodes?.map { it.name }.orEmpty(),
            destinationNodeName = selectedNodeName,
            onBack = { activeSessionId = "" },
        )
        return
    }

    pendingDelete?.let { map ->
        AlertDialog(
            onDismissRequest = { if (!busy) pendingDelete = null },
            title = { Text("删除拓扑图？") },
            text = { Text("将删除 ${map.name} 及其 ${map.nodes.size} 个节点图像。") },
            confirmButton = {
                TextButton(
                    onClick = {
                        scope.launch {
                            busy = true
                            withContext(Dispatchers.IO) { deleteTopologyMap(context, map) }
                            maps.clear()
                            maps.addAll(withContext(Dispatchers.IO) { loadTopologyMaps(context) })
                            if (selectedMapId == map.id) {
                                selectedMapId = ""
                                selectedNodeName = ""
                                selectedMap = null
                                saveSelection(context, "", "")
                            }
                            message = "已删除 ${map.name}"
                            busy = false
                            pendingDelete = null
                        }
                    },
                    enabled = !busy,
                ) { Text("确认删除") }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = null }, enabled = !busy) { Text("取消") }
            },
        )
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            OutlinedButton(onClick = onBack, modifier = Modifier.height(52.dp)) {
                Text("返回", fontSize = 20.sp)
            }
        }
        item { Text("拓扑图管理", fontSize = 28.sp, fontWeight = FontWeight.Bold) }
        item {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("云端视觉导航", fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
                    OutlinedTextField(
                        value = serviceUrl,
                        onValueChange = {
                            serviceUrl = it
                            cloudConnected = false
                            inferenceReady = false
                            obstacleReady = false
                        },
                        label = { Text("服务地址") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                    )
                    OutlinedTextField(
                        value = apiToken,
                        onValueChange = { apiToken = it },
                        label = { Text("访问令牌（可留空）") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    )
                    OutlinedButton(
                        onClick = {
                            scope.launch {
                                busy = true
                                cloudStatus = "正在连接…"
                                val result = withContext(Dispatchers.IO) {
                                    runCatching { CloudApi(serviceUrl, apiToken).health() }
                                }
                                result.onSuccess { health ->
                                    cloudConnected = health.status == "ok"
                                    inferenceReady = health.inferenceReady
                                    obstacleReady = health.yosoVisionReady
                                    cloudPrefs.edit()
                                        .putString(KEY_SERVICE_URL, serviceUrl.trim().trimEnd('/'))
                                        .putString(KEY_API_TOKEN, apiToken)
                                        .apply()
                                    cloudStatus = when {
                                        health.inferenceReady && health.yosoVisionReady && health.voiceAsrReady -> "服务正常，导航、视觉辅助和语音识别已就绪"
                                        health.inferenceReady && health.yosoVisionReady -> "导航与视觉辅助已就绪，云端语音识别未配置"
                                        health.inferenceReady && health.voiceAsrReady -> "导航与语音识别已就绪，但视觉避障模型未就绪"
                                        health.inferenceReady -> "导航模型已就绪，但视觉避障模型未就绪"
                                        health.yosoVisionReady && health.voiceAsrReady -> "视觉辅助与语音识别已就绪，导航模型未就绪"
                                        health.inferenceReady -> "拓扑导航已就绪，视觉辅助或语音识别尚未就绪"
                                        health.yosoVisionReady -> "视觉辅助已就绪，导航或语音识别尚未就绪"
                                        health.voiceAsrReady -> "语音识别已就绪，导航或视觉辅助尚未就绪"
                                        else -> "服务正常，导航、视觉辅助和语音识别均未就绪"
                                    }
                                }.onFailure { error ->
                                    cloudConnected = false
                                    inferenceReady = false
                                    obstacleReady = false
                                    cloudStatus = error.message ?: "连接失败"
                                }
                                busy = false
                            }
                        },
                        enabled = !busy && serviceUrl.isNotBlank(),
                        modifier = Modifier.fillMaxWidth().padding(top = 10.dp).height(52.dp),
                    ) {
                        Text("测试连接", fontSize = 19.sp)
                    }
                    Text(cloudStatus, modifier = Modifier.padding(top = 8.dp), fontSize = 19.sp)
                }
            }
        }
        item {
            Button(
                onClick = { importLauncher.launch(arrayOf("application/zip", "application/octet-stream", "*/*")) },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth().height(56.dp),
            ) {
                Text(if (busy) "正在导入…" else "导入拓扑图 ZIP", fontSize = 20.sp)
            }
        }
        item {
            OutlinedButton(
                onClick = { showRecordDialog = true },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth().height(56.dp),
            ) {
                Text("录制陌生环境", fontSize = 20.sp)
            }
        }
        item { Text(message, fontSize = 19.sp) }
        if (maps.isEmpty()) {
            item { Text("还没有导入地图", fontSize = 19.sp) }
        } else {
            item { Text("已导入地图", fontSize = 22.sp, fontWeight = FontWeight.SemiBold) }
            items(maps, key = { it.id }) { map ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(
                            selected = selectedMapId == map.id,
                            onClick = {
                                selectedMapId = map.id
                                selectedNodeName = map.nodes.lastOrNull()?.name.orEmpty()
                                saveSelection(context, map.id, selectedNodeName)
                            },
                        )
                        Column(modifier = Modifier.weight(1f)) {
                            Text(map.name, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
                            Text("${map.nodes.size} 个节点", fontSize = 17.sp)
                        }
                        OutlinedButton(onClick = { pendingDelete = map }, enabled = !busy) {
                            Text("删除")
                        }
                    }
                }
            }
            selectedMap?.let { map ->
                item {
                    Text("选择目标节点", fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
                    Text("${map.name} · ${map.nodes.size} 个节点", fontSize = 17.sp)
                }
                items(map.nodes, key = { "${map.id}/${it.name}" }) { node ->
                    NodeRow(
                        node = node,
                        selected = selectedNodeName == node.name,
                        onSelect = {
                            selectedNodeName = node.name
                            saveSelection(context, map.id, node.name)
                        },
                    )
                }
            }
            item {
                Button(
                    onClick = {
                        val map = selectedMap ?: return@Button
                        scope.launch {
                            busy = true
                            message = "正在同步拓扑图…"
                            val result = withContext(Dispatchers.IO) {
                                runCatching {
                                    val api = CloudApi(serviceUrl, apiToken)
                                    val key = cloudMapKey(map.id, serviceUrl)
                                    val existingMapId = cloudPrefs.getString(key, null)
                                    val cloudMapId = existingMapId ?: api.uploadMap(context, map.directory).also {
                                        require(it.nodeCount == map.nodes.size) { "云端节点数量与本地不一致" }
                                        cloudPrefs.edit().putString(key, it.id).apply()
                                    }.id
                                    api.createNavigationSession(cloudMapId, selectedNodeName)
                                }
                            }
                            result.onSuccess { session ->
                                cloudPrefs.edit().putString(KEY_SESSION_ID, session.id).apply()
                                inferenceReady = session.inferenceReady
                                message = if (session.inferenceReady) {
                                    "导航会话已创建，编号 ${session.id.take(8)}"
                                } else {
                                    "地图已同步；视觉模型尚未就绪，未开始方向引导"
                                }
                                if (session.inferenceReady) activeSessionId = session.id
                            }.onFailure { error ->
                                message = error.message ?: "创建导航会话失败"
                            }
                            busy = false
                        }
                    },
                    enabled = !busy && cloudConnected && inferenceReady && obstacleReady &&
                        selectedMap != null && selectedNodeName.isNotBlank(),
                    modifier = Modifier.fillMaxWidth().height(56.dp),
                ) {
                    Text(
                        if (inferenceReady && obstacleReady) "同步地图并开始导航避障"
                        else "等待导航与避障模型就绪",
                        fontSize = 19.sp,
                    )
                }
            }
        }
    }
}

@Composable
private fun NodeRow(node: File, selected: Boolean, onSelect: () -> Unit) {
    val thumbnail by produceState<Bitmap?>(initialValue = null, node.absolutePath, node.lastModified()) {
        value = withContext(Dispatchers.IO) { decodeThumbnail(node) }
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth().clickable(onClick = onSelect).padding(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            thumbnail?.let { bitmap ->
                Image(
                    bitmap = bitmap.asImageBitmap(),
                    contentDescription = "节点 ${node.name} 图像",
                    modifier = Modifier.size(width = 104.dp, height = 76.dp),
                )
            } ?: run {
                Surface(modifier = Modifier.size(width = 104.dp, height = 76.dp), color = MaterialTheme.colorScheme.surfaceVariant) { }
            }
            Column(modifier = Modifier.weight(1f).padding(horizontal = 10.dp)) {
                Text("节点 ${node.nameWithoutExtension}", fontSize = 19.sp, fontWeight = FontWeight.Medium)
                Text(if (selected) "已选为目标" else "点击设为目标", fontSize = 17.sp)
            }
            RadioButton(selected = selected, onClick = onSelect)
        }
    }
}

private fun saveSelection(context: Context, mapId: String, nodeName: String) {
    context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
        .putString(KEY_MAP_ID, mapId)
        .putString(KEY_NODE_NAME, nodeName)
        .apply()
    // 同步记录使用时间，供首页"继续上次路线"展示
    LastRouteStore.markUsed(context)
}

private fun loadTopologyMaps(context: Context): List<TopologyMap> {
    val root = File(context.filesDir, MAPS_DIRECTORY)
    if (!root.exists()) return emptyList()
    return root.listFiles()?.filter { it.isDirectory }?.flatMap { imported ->
        val folders = imported.walkTopDown().filter { it.isDirectory }.toList()
        folders.mapNotNull { directory ->
            val nodes = directory.listFiles()?.filter(::isNodeImage)?.sortedBy { it.nameWithoutExtension.toLongOrNull() } ?: emptyList()
            if (nodes.isEmpty()) null else {
                val relative = directory.relativeTo(imported).path
                // 显示名优先用地图根目录名（即用户录制时输入的名称），
                // 若存在子目录则拼接子目录名，避免全部显示为“预录地图”。
                val name = if (relative == ".") {
                    imported.name
                } else {
                    imported.name + "/" + relative.replace(File.separatorChar, '/')
                }
                TopologyMap("${imported.name}/${relative}", name, directory, nodes)
            }
        }
    }?.sortedBy { it.name } ?: emptyList()
}

private fun createRecordingDirectory(context: Context, name: String): File? = runCatching {
    val root = File(context.filesDir, MAPS_DIRECTORY).apply { mkdirs() }
    val safeName = name.trim()
        .replace(Regex("[^\\p{L}\\p{N} _-]"), "_")
        .replace(Regex("\\s+"), "-")
        .trim('-', '_')
        .take(48)
        .ifBlank { "新地图" }
    var candidate = File(root, safeName)
    var suffix = 2
    while (candidate.exists()) candidate = File(root, "$safeName-$suffix").also { suffix += 1 }
    candidate.takeIf { it.mkdirs() }
}.getOrNull()

private fun importTopologyZip(context: Context, uri: Uri): Result<TopologyMap> = runCatching {
    val displayName = context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
        val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (cursor.moveToFirst() && index >= 0) cursor.getString(index) else null
    }.orEmpty()
    require(displayName.endsWith(".zip", ignoreCase = true)) { "请选择 ZIP 格式的拓扑图" }

    val root = File(context.filesDir, MAPS_DIRECTORY).apply { mkdirs() }
    val staging = File(root, "import-${UUID.randomUUID()}").apply { mkdirs() }
    var totalBytes = 0L
    var entryCount = 0
    try {
        val input = context.contentResolver.openInputStream(uri) ?: error("无法读取所选文件")
        input.use { source ->
            ZipInputStream(source).use { zip ->
                var entry = zip.nextEntry
                while (entry != null) {
                    entryCount += 1
                    require(entryCount <= MAX_ZIP_ENTRIES) { "ZIP 文件包含过多条目" }
                    val target = File(staging, entry.name).canonicalFile
                    require(target.toPath().startsWith(staging.canonicalFile.toPath())) { "ZIP 中包含不安全路径" }
                    if (entry.isDirectory) {
                        target.mkdirs()
                    } else {
                        target.parentFile?.mkdirs()
                        FileOutputStream(target).use { output ->
                            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                            while (true) {
                                val count = zip.read(buffer)
                                if (count < 0) break
                                totalBytes += count
                                require(totalBytes <= MAX_UNCOMPRESSED_BYTES) { "解压内容超过 1 GB 限制" }
                                output.write(buffer, 0, count)
                            }
                        }
                    }
                    zip.closeEntry()
                    entry = zip.nextEntry
                }
            }
        }
        val importedMaps = loadMapsFromDirectory(staging)
        require(importedMaps.isNotEmpty()) { "没有找到编号为 0、1、2… 的 JPG/PNG 节点图" }
        importedMaps.first()
    } catch (error: Throwable) {
        staging.deleteRecursively()
        throw error
    }
}

private fun loadMapsFromDirectory(imported: File): List<TopologyMap> {
    return imported.walkTopDown().filter { it.isDirectory }.mapNotNull { directory ->
        val nodes = directory.listFiles()?.filter(::isNodeImage)?.sortedBy { it.nameWithoutExtension.toLongOrNull() } ?: emptyList()
        if (nodes.isEmpty()) null else {
            val relative = directory.relativeTo(imported).path
            val name = if (relative == ".") {
                imported.name
            } else {
                imported.name + "/" + relative.replace(File.separatorChar, '/')
            }
            TopologyMap("${imported.name}/${relative}", name, directory, nodes)
        }
    }.toList()
}

private fun deleteTopologyMap(context: Context, map: TopologyMap) {
    val root = File(context.filesDir, MAPS_DIRECTORY).canonicalFile
    val directory = map.directory.canonicalFile
    require(directory.toPath().startsWith(root.toPath()) && directory != root) { "地图路径无效" }
    directory.deleteRecursively()
    var parent = directory.parentFile
    while (parent != null && parent != root && parent.listFiles().isNullOrEmpty()) {
        val next = parent.parentFile
        parent.delete()
        parent = next
    }
}

private fun isNodeImage(file: File): Boolean = file.isFile &&
    file.name.matches(Regex("\\d+\\.(jpg|jpeg|png)", RegexOption.IGNORE_CASE))

private fun decodeThumbnail(file: File): Bitmap? = runCatching {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(file.absolutePath, bounds)
    val options = BitmapFactory.Options().apply { inSampleSize = calculateSampleSize(bounds, 320, 240) }
    BitmapFactory.decodeFile(file.absolutePath, options)
}.getOrNull()

private fun calculateSampleSize(options: BitmapFactory.Options, targetWidth: Int, targetHeight: Int): Int {
    var sample = 1
    while (options.outWidth / sample > targetWidth * 2 || options.outHeight / sample > targetHeight * 2) sample *= 2
    return sample
}

private const val PREFS_NAME = "topology_selection"
private const val KEY_MAP_ID = "map_id"
private const val KEY_NODE_NAME = "node_name"
private const val MAPS_DIRECTORY = "topology_maps"
private const val MAX_ZIP_ENTRIES = 20_000
private const val MAX_UNCOMPRESSED_BYTES = 1L shl 30
private const val CLOUD_PREFS_NAME = "cloud_service"
private const val KEY_SERVICE_URL = "service_url"
private const val KEY_API_TOKEN = "api_token"
private const val KEY_SESSION_ID = "navigation_session_id"

private fun cloudMapKey(localMapId: String, serviceUrl: String): String =
    "cloud_map_${serviceUrl.trim().trimEnd('/').hashCode()}_${localMapId.hashCode()}"
