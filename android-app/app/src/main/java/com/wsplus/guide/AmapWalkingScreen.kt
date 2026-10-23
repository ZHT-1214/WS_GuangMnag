package com.wsplus.guide

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.media.AudioAttributes
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.amap.api.maps.AMap
import com.amap.api.maps.CameraUpdateFactory
import com.amap.api.maps.CoordinateConverter
import com.amap.api.maps.MapView
import com.amap.api.maps.model.LatLng
import com.amap.api.maps.model.Marker
import com.amap.api.maps.model.MarkerOptions
import com.amap.api.maps.model.MyLocationStyle
import com.amap.api.maps.model.Polyline
import com.amap.api.maps.model.PolylineOptions
import com.amap.api.navi.AMapNavi
import com.amap.api.navi.SimpleNaviListener
import com.amap.api.navi.enums.NaviType
import com.amap.api.navi.model.NaviLatLng
import com.amap.api.services.core.LatLonPoint
import com.amap.api.services.core.PoiItem
import com.amap.api.services.poisearch.PoiResult
import com.amap.api.services.poisearch.PoiSearch
import java.util.Locale

private data class Destination(
    val id: String,
    val name: String,
    val address: String,
    val point: LatLng,
    val distanceMeters: Int,
)

@Composable
internal fun AmapWalkingScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    var locationGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED ||
                ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions(),
    ) { result ->
        locationGranted = result[Manifest.permission.ACCESS_FINE_LOCATION] == true ||
            result[Manifest.permission.ACCESS_COARSE_LOCATION] == true
    }

    var locationStatus by rememberSaveable { mutableStateOf("正在请求系统定位") }
    var location by remember { mutableStateOf<Location?>(null) }
    var retryToken by rememberSaveable { mutableStateOf(0) }
    var map by remember { mutableStateOf<AMap?>(null) }
    var query by rememberSaveable { mutableStateOf("") }
    var searchStatus by rememberSaveable { mutableStateOf("") }
    var searching by remember { mutableStateOf(false) }
    var destinations by remember { mutableStateOf(emptyList<Destination>()) }
    var destination by remember { mutableStateOf<Destination?>(null) }
    var routePoints by remember { mutableStateOf<List<LatLng>>(emptyList()) }
    var routeStatus by rememberSaveable { mutableStateOf("") }
    var guidance by rememberSaveable { mutableStateOf("") }
    var navigationActive by remember { mutableStateOf(false) }
    var routeSummary by rememberSaveable { mutableStateOf("") }
    var navi by remember { mutableStateOf<AMapNavi?>(null) }
    var naviReady by remember { mutableStateOf(false) }
    var ttsReady by remember { mutableStateOf(false) }
    var ttsInitStatus by remember { mutableStateOf<Int?>(null) }
    var ttsStatus by rememberSaveable { mutableStateOf("正在初始化系统语音") }
    val mainHandler = remember { Handler(Looper.getMainLooper()) }
    val tts = remember(context) {
        TextToSpeech(context.applicationContext) { status ->
            ttsInitStatus = status
        }
    }

    LaunchedEffect(tts, ttsInitStatus) {
        val status = ttsInitStatus ?: return@LaunchedEffect
        if (status != TextToSpeech.SUCCESS) {
            ttsReady = false
            ttsStatus = "系统语音引擎初始化失败（状态 $status）"
            return@LaunchedEffect
        }
        tts.setAudioAttributes(
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build(),
        )
        val languageResult = tts.setLanguage(Locale.CHINA)
        ttsReady = languageResult != TextToSpeech.LANG_MISSING_DATA &&
            languageResult != TextToSpeech.LANG_NOT_SUPPORTED
        ttsStatus = if (ttsReady) {
            "中文语音已就绪"
        } else {
            "当前系统语音引擎缺少中文语音包"
        }
    }

    DisposableEffect(tts) {
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {
                mainHandler.post { ttsStatus = "正在播报语音" }
            }

            override fun onDone(utteranceId: String?) {
                mainHandler.post { ttsStatus = "语音播报完成" }
            }

            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) {
                mainHandler.post { ttsStatus = "系统语音播报失败" }
            }

            override fun onError(utteranceId: String?, errorCode: Int) {
                mainHandler.post { ttsStatus = "系统语音播报失败（错误码 $errorCode）" }
            }
        })
        onDispose {
            ttsReady = false
            tts.stop()
            tts.shutdown()
        }
    }

    fun speakGuidance(text: String, utteranceId: String) {
        if (!ttsReady) {
            ttsStatus = "语音尚未就绪，无法播报"
            return
        }
        val result = tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, utteranceId)
        if (result == TextToSpeech.ERROR) {
            ttsStatus = "语音请求提交失败"
        }
    }

    DisposableEffect(context) {
        var instance: AMapNavi? = null
        var listener: SimpleNaviListener? = null
        try {
            instance = AMapNavi.getInstance(context.applicationContext)
            listener = object : SimpleNaviListener() {
                override fun onInitNaviSuccess() {
                    mainHandler.post {
                        naviReady = true
                        routeStatus = "导航服务已就绪"
                    }
                }

                override fun onCalculateRouteSuccess(routeIds: IntArray) {
                    val path = instance?.naviPath
                    if (path == null || path.coordList.isNullOrEmpty()) {
                        mainHandler.post { routeStatus = "路线计算完成，但路线坐标为空，请重试。" }
                        return
                    }
                    val points = path.coordList.map { LatLng(it.latitude, it.longitude) }
                    val distanceKm = path.allLength / 1000.0
                    val minutes = (path.allTime / 60).coerceAtLeast(1)
                    mainHandler.post {
                        routePoints = points
                        routeSummary = "${"%.1f".format(Locale.US, distanceKm)} 公里，约 $minutes 分钟"
                        routeStatus = "路线已生成"
                    }
                }

                override fun onCalculateRouteFailure(errorCode: Int) {
                    mainHandler.post { routeStatus = "步行路线计算失败（错误码 $errorCode），请检查网络后重试。" }
                }

                override fun onGetNavigationText(text: String) {
                    if (text.isBlank()) return
                    mainHandler.post {
                        guidance = text
                        if (navigationActive && ttsReady) {
                            speakGuidance(text, "walk-guidance")
                        }
                    }
                }

                override fun onNaviInfoUpdate(info: com.amap.api.navi.model.NaviInfo) {
                    val next = info.getNextRoadName().orEmpty()
                    val distance = info.curStepRetainDistance
                    mainHandler.post {
                        if (navigationActive && next.isNotBlank()) {
                            guidance = "前方 $distance 米，沿${next}继续"
                        }
                    }
                }

                override fun onArriveDestination() {
                    mainHandler.post {
                        navigationActive = false
                        guidance = "已到达目的地"
                        routeStatus = "已到达目的地"
                        if (ttsReady) {
                            speakGuidance("已到达目的地", "walk-arrival")
                        }
                    }
                }
            }
            instance.addAMapNaviListener(listener)
            navi = instance
        } catch (error: Exception) {
            routeStatus = "高德步行导航初始化失败：${error.message ?: "请检查 Key 配置"}"
        }

        onDispose {
            navigationActive = false
            runCatching { instance?.stopNavi() }
            if (instance != null && listener != null) {
                runCatching { instance.removeAMapNaviListener(listener) }
            }
            runCatching { AMapNavi.destroy() }
            navi = null
        }
    }

    val polyline = remember { mutableStateOf<Polyline?>(null) }
    val destinationMarker = remember { mutableStateOf<Marker?>(null) }
    LaunchedEffect(map, destination, routePoints) {
        val currentMap = map ?: return@LaunchedEffect
        polyline.value?.remove()
        destinationMarker.value?.remove()
        destination?.let { selected ->
            destinationMarker.value = currentMap.addMarker(
                MarkerOptions().position(selected.point).title(selected.name).snippet(selected.address),
            )
        }
        if (routePoints.size > 1) {
            polyline.value = currentMap.addPolyline(
                PolylineOptions()
                    .addAll(routePoints)
                    .color(android.graphics.Color.rgb(0, 125, 110))
                    .width(12f),
            )
            destination?.let { currentMap.animateCamera(CameraUpdateFactory.newLatLngZoom(it.point, 16f)) }
        }
    }

    fun searchDestination() {
        val keyword = query.trim()
        val currentLocation = location
        if (keyword.isEmpty()) {
            searchStatus = "请输入目的地名称或地址。"
            return
        }
        if (currentLocation == null) {
            searchStatus = "还没有当前位置；请先完成定位。"
            return
        }

        searching = true
        searchStatus = "正在搜索附近地点"
        destinations = emptyList()
        val centerPoint = toAmapLatLng(context, currentLocation)
        val center = LatLonPoint(centerPoint.latitude, centerPoint.longitude)
        try {
            val poiQuery = PoiSearch.Query(keyword, "", "").apply {
                pageSize = 8
                pageNum = 0
                cityLimit = false
                setLocation(center)
                setDistanceSort(true)
            }
            val poiSearch = PoiSearch(context, poiQuery)
            poiSearch.bound = PoiSearch.SearchBound(center, 50_000, true)
            poiSearch.setOnPoiSearchListener(object : PoiSearch.OnPoiSearchListener {
                override fun onPoiSearched(result: PoiResult?, errorCode: Int) {
                    searching = false
                    if (errorCode != 1000 || result == null) {
                        searchStatus = poiSearchErrorMessage(errorCode)
                    } else {
                        val results = result.pois.orEmpty().mapNotNull { poi ->
                            val point = poi.latLonPoint ?: return@mapNotNull null
                            poi.toDestination(point)
                        }
                        destinations = results
                        searchStatus = if (results.isEmpty()) "附近没有找到相关地点，请换个关键词。" else "找到 ${results.size} 个地点"
                    }
                }

                override fun onPoiItemSearched(item: PoiItem?, errorCode: Int) = Unit
            })
            poiSearch.searchPOIAsyn()
        } catch (error: Exception) {
            searching = false
            searchStatus = "地点搜索暂不可用：${error.message ?: "请稍后重试"}"
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                OutlinedButton(onClick = onBack, modifier = Modifier.sizeIn(minWidth = 96.dp, minHeight = 52.dp)) {
                    Text("返回", fontSize = 18.sp)
                }
            }
            item { Text("步行导航", fontSize = 30.sp, fontWeight = FontWeight.Bold) }
            item {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = if (locationGranted) locationStatus else "需要定位权限才能规划步行路线",
                        modifier = Modifier.padding(16.dp),
                        fontSize = 18.sp,
                    )
                }
            }
            if (!locationGranted) {
                item {
                    Button(
                        onClick = {
                            permissionLauncher.launch(
                                arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION),
                            )
                        },
                        modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 56.dp),
                    ) { Text("允许使用定位", fontSize = 18.sp) }
                }
            } else {
                item {
                    OutlinedButton(
                        onClick = {
                            locationStatus = "正在重新请求系统定位"
                            retryToken++
                        },
                        modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 52.dp),
                    ) { Text("重新定位", fontSize = 18.sp) }
                }
                item {
                    AmapLocationMap(
                        retryToken = retryToken,
                        onLocationStatus = { locationStatus = it },
                        onLocation = { location = it },
                        onMapReady = { map = it },
                        modifier = Modifier.fillMaxWidth().height(380.dp),
                    )
                }
                item {
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("目的地") },
                        placeholder = { Text("输入地点、道路或地址") },
                        singleLine = true,
                    )
                }
                item {
                    Button(
                        onClick = ::searchDestination,
                        enabled = !searching,
                        modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 56.dp),
                    ) { Text(if (searching) "正在搜索" else "搜索目的地", fontSize = 18.sp) }
                }
                if (searchStatus.isNotBlank()) {
                    item { Text(searchStatus, fontSize = 16.sp) }
                }
                item {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            Text("语音状态：$ttsStatus", fontSize = 17.sp)
                            Button(
                                onClick = { speakGuidance("语音测试正常，步行导航已准备就绪。", "tts-test") },
                                enabled = ttsReady,
                                modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 52.dp),
                            ) {
                                Text("测试语音", fontSize = 18.sp)
                            }
                        }
                    }
                }
                if (destination == null) {
                    items(destinations, key = { it.id }) { candidate ->
                        DestinationCard(
                            destination = candidate,
                            selected = false,
                            onClick = {
                                destination = candidate
                                routePoints = emptyList()
                                routeSummary = ""
                                routeStatus = "已选择目的地"
                            },
                        )
                    }
                }
                destination?.let { selected ->
                    item {
                        DestinationCard(
                            destination = selected,
                            selected = true,
                            onClick = {
                                destination = null
                                routePoints = emptyList()
                                routeSummary = ""
                                routeStatus = "请重新选择候选地点"
                            },
                        )
                    }
                    item {
                        Text("目的地：${selected.name}", fontSize = 19.sp, fontWeight = FontWeight.SemiBold)
                    }
                    item {
                        Button(
                            onClick = {
                                val start = location
                                if (!naviReady || start == null) {
                                    routeStatus = "导航服务或当前位置尚未就绪，请稍后重试。"
                                } else {
                                    routeStatus = "正在计算步行路线"
                                    routePoints = emptyList()
                                    val accepted = navi?.calculateWalkRoute(
                                        toAmapLatLng(context, start).let { NaviLatLng(it.latitude, it.longitude) },
                                        NaviLatLng(selected.point.latitude, selected.point.longitude),
                                    ) == true
                                    if (!accepted) routeStatus = "路线请求未能启动，请检查网络后重试。"
                                }
                            },
                            enabled = naviReady && location != null && !navigationActive,
                            modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 56.dp),
                        ) { Text("规划步行路线", fontSize = 18.sp) }
                    }
                }
                if (routeStatus.isNotBlank()) {
                    item {
                        Card(modifier = Modifier.fillMaxWidth()) {
                            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text(routeStatus, fontSize = 18.sp)
                                if (routeSummary.isNotBlank()) Text(routeSummary, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                            }
                        }
                    }
                }
                if (routePoints.isNotEmpty() && !navigationActive) {
                    item {
                        Button(
                            onClick = {
                                val started = navi?.startNavi(NaviType.GPS) == true
                                if (started) {
                                    navigationActive = true
                                    guidance = "正在开始步行引导"
                                    if (ttsReady) {
                                        speakGuidance("开始步行引导。$routeSummary", "walk-start")
                                    }
                                } else {
                                    routeStatus = "未能启动实时引导，请确认定位和路线仍有效。"
                                }
                            },
                            modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 60.dp),
                        ) { Text("开始步行引导", fontSize = 19.sp) }
                    }
                }
                if (navigationActive) {
                    item {
                        Card(modifier = Modifier.fillMaxWidth()) {
                            Text(
                                text = guidance.ifBlank { "正在进行步行引导" },
                                modifier = Modifier.padding(16.dp),
                                fontSize = 21.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                    }
                    item {
                        OutlinedButton(
                            onClick = {
                                navi?.stopNavi()
                                navigationActive = false
                                guidance = "导航已停止"
                                routeStatus = "导航已停止"
                            },
                            modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 56.dp),
                        ) { Text("停止导航", fontSize = 18.sp) }
                    }
                }
            }
        }
    }
}

@Composable
private fun DestinationCard(destination: Destination, selected: Boolean, onClick: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(destination.name, fontSize = 19.sp, fontWeight = FontWeight.SemiBold)
            Text(destination.address.ifBlank { "地址暂无" }, fontSize = 16.sp)
            if (destination.distanceMeters > 0) Text("约 ${destination.distanceMeters} 米", fontSize = 15.sp)
            OutlinedButton(onClick = onClick, modifier = Modifier.fillMaxWidth().sizeIn(minHeight = 50.dp)) {
                Text(if (selected) "重新选择候选" else "选择此地点", fontSize = 17.sp)
            }
        }
    }
}

private fun PoiItem.toDestination(point: LatLonPoint) = Destination(
    id = poiId ?: "${point.latitude},${point.longitude}",
    name = title.orEmpty(),
    address = listOf(cityName, adName, snippet)
        .filterNot { it.isNullOrBlank() }
        .distinct()
        .joinToString(" · "),
    point = LatLng(point.latitude, point.longitude),
    distanceMeters = distance,
)

private fun poiSearchErrorMessage(errorCode: Int) = when (errorCode) {
    1008 -> "高德 Key 安全码校验失败。请在高德控制台为 Android Key 绑定当前应用包名和 SHA1。"
    1009 -> "当前 Key 的平台类型不匹配。地点搜索需要 Android 平台 Key。"
    1802, 1804, 1806 -> "地点搜索网络连接失败（错误码 $errorCode），请检查网络后重试。"
    else -> "地点搜索失败（错误码 $errorCode），请稍后重试。"
}

private fun toAmapLatLng(context: Context, location: Location) = CoordinateConverter(context)
    .from(CoordinateConverter.CoordType.GPS)
    .coord(LatLng(location.latitude, location.longitude))
    .convert()

@Composable
private fun AmapLocationMap(
    retryToken: Int,
    onLocationStatus: (String) -> Unit,
    onLocation: (Location) -> Unit,
    onMapReady: (AMap?) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val mapView = remember { MapView(context).apply { onCreate(null) } }

    DisposableEffect(lifecycleOwner, mapView) {
        val map = mapView.map
        onMapReady(map)
        map.uiSettings.isMyLocationButtonEnabled = true
        map.myLocationStyle = MyLocationStyle()
            .myLocationType(MyLocationStyle.LOCATION_TYPE_LOCATION_ROTATE_NO_CENTER)
            .interval(2_000)
        map.isMyLocationEnabled = true

        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> mapView.onResume()
                Lifecycle.Event.ON_PAUSE -> mapView.onPause()
                Lifecycle.Event.ON_DESTROY -> mapView.onDestroy()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            map.isMyLocationEnabled = false
            mapView.onPause()
            mapView.onDestroy()
            onMapReady(null)
        }
    }

    val locationManager = context.getSystemService(LocationManager::class.java)
    LaunchedEffect(lifecycleOwner, mapView, retryToken) {
        val map = mapView.map
        val handler = Handler(Looper.getMainLooper())
        var currentMarker: Marker? = null
        var firstLocation = true
        var deliveredLocation = false
        val timeout = Runnable {
            if (!deliveredLocation) {
                onLocationStatus("暂未取得定位。请到室外或窗边等待 GPS，检查系统定位精度后点“重新定位”。")
            }
        }
        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                if (location.latitude == 0.0 && location.longitude == 0.0) return
                deliveredLocation = true
                handler.removeCallbacks(timeout)
                onLocation(location)
                val point = toAmapLatLng(context, location)
                if (currentMarker == null) {
                    currentMarker = map.addMarker(MarkerOptions().position(point).title("当前位置"))
                } else {
                    currentMarker?.position = point
                }
                onLocationStatus("已定位，精度约 ${location.accuracy.toInt().coerceAtLeast(1)} 米")
                if (firstLocation) {
                    firstLocation = false
                    map.animateCamera(CameraUpdateFactory.newLatLngZoom(point, 18f))
                }
            }
        }

        try {
            val lastKnown = locationManager.getProviders(true)
                .asSequence()
                .mapNotNull { provider -> runCatching { locationManager.getLastKnownLocation(provider) }.getOrNull() }
                .maxByOrNull { it.time }
            if (lastKnown != null) listener.onLocationChanged(lastKnown)
            val providers = locationManager.getProviders(true).filter {
                it == LocationManager.GPS_PROVIDER || it == LocationManager.NETWORK_PROVIDER
            }
            providers.forEach { provider ->
                locationManager.requestLocationUpdates(provider, 1_000L, 0f, listener, Looper.getMainLooper())
            }
            if (providers.isEmpty()) {
                onLocationStatus("系统没有可用的 GPS 或网络定位源，请检查定位设置。")
            } else {
                onLocationStatus("正在使用系统定位；室外 GPS 通常更快")
                handler.postDelayed(timeout, 15_000L)
            }
        } catch (_: SecurityException) {
            onLocationStatus("定位权限已撤销，请重新允许定位。")
        } catch (_: Exception) {
            onLocationStatus("系统定位暂不可用，请稍后点“重新定位”。")
        }

        try {
            kotlinx.coroutines.awaitCancellation()
        } finally {
            handler.removeCallbacks(timeout)
            runCatching { locationManager.removeUpdates(listener) }
            currentMarker?.remove()
        }
    }

    AndroidView(factory = { mapView }, modifier = modifier)
}
