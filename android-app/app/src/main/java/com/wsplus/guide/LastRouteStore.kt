package com.wsplus.guide

import android.content.Context

/**
 * 记住上一次的导航配置，供首页"继续上次路线"一键恢复。
 *
 * 保存内容：地图 ID、目标节点、云服务地址、会话 ID、时间戳。
 * 与 TopologyMapsScreen 中的 KEY_MAP_ID / KEY_NODE_NAME 共享同一份 SharedPreferences
 * （topology_selection），因此在地图页选择后会自动同步到这里。
 */
object LastRouteStore {
    private const val PREFS = "topology_selection"
    private const val CLOUD_PREFS = "cloud_service"

    private const val KEY_MAP_ID = "map_id"
    private const val KEY_NODE_NAME = "node_name"
    private const val KEY_LAST_USED_AT = "last_used_at"
    private const val KEY_SERVICE_URL = "service_url"
    private const val KEY_SESSION_ID = "navigation_session_id"

    data class LastRoute(
        val mapId: String,
        val nodeName: String,
        val serviceUrl: String,
        val sessionId: String,
        val lastUsedAt: Long,
    ) {
        val isValid: Boolean
            get() = mapId.isNotBlank() && nodeName.isNotBlank() && serviceUrl.isNotBlank()

        /** 用于首页展示，例如 "208-2 · 31.jpg"。 */
        val displayName: String
            get() = "${mapId.trimEnd('/')} · $nodeName"
    }

    fun load(context: Context): LastRoute? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val cloud = context.getSharedPreferences(CLOUD_PREFS, Context.MODE_PRIVATE)
        val mapId = prefs.getString(KEY_MAP_ID, "").orEmpty()
        val node = prefs.getString(KEY_NODE_NAME, "").orEmpty()
        val url = cloud.getString(KEY_SERVICE_URL, "").orEmpty()
        val session = cloud.getString(KEY_SESSION_ID, "").orEmpty()
        var at = prefs.getLong(KEY_LAST_USED_AT, 0L)
        val route = LastRoute(mapId, node, url, session, at)
        if (!route.isValid) return null
        // 兼容旧版本：选择已存在但未记录时间戳时，补写当前时间，
        // 避免首页显示"上次使用："后面为空。
        if (at <= 0L) {
            at = System.currentTimeMillis()
            markUsed(context)
        }
        return route.copy(lastUsedAt = at)
    }

    /** 记录一次成功开始导航的时间，用于"继续上次路线"。 */
    fun markUsed(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putLong(KEY_LAST_USED_AT, System.currentTimeMillis())
            .apply()
    }

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_LAST_USED_AT)
            .apply()
    }

    /** 把毫秒时间戳格式化成"x 分钟前 / x 小时前 / x 天前"。 */
    fun relativeTime(at: Long): String {
        if (at <= 0L) return ""
        val diff = System.currentTimeMillis() - at
        val minute = 60_000L
        val hour = 60 * minute
        val day = 24 * hour
        return when {
            diff < minute -> "刚刚"
            diff < hour -> "${diff / minute} 分钟前"
            diff < day -> "${diff / hour} 小时前"
            else -> "${diff / day} 天前"
        }
    }
}
