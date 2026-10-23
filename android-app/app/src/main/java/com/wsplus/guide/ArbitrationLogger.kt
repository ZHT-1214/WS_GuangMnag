package com.wsplus.guide

import android.content.Context
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 仲裁实验事件记录器。
 *
 * 目的：为审稿问题 2（规则 2/3/4 未验证）提供精确的时间线数据。
 *
 * 记录两类事件：
 *   1. 系统事件（自动）：每次 TTS 播报、每次仲裁决策、每次方向判定变化
 *   2. 人工标记（按钮）：实验者观察到关键现象时手动打点
 *
 * 输出格式（CSV，便于离线分析）：
 *   t_ms,elapsed_ms,type,detail
 *
 * 设计要点：
 *   - 所有时间戳用 SystemClock.elapsedRealtime()，不受系统时间调整影响
 *   - 写入带缓冲，每 20 条或 2 秒刷盘一次，避免频繁 IO 影响推理时延
 *   - 与地图录制共用目录，便于一起导出
 */
class ArbitrationLogger(
    private val context: Context,
    private val sessionName: String,
) {
    private val startMs = android.os.SystemClock.elapsedRealtime()
    private val fmt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)
    private val file: File by lazy {
        val dir = File(context.getExternalFilesDir(null), "arbitration_logs")
        dir.mkdirs()
        File(dir, "arb_${sanitize(sessionName)}_${System.currentTimeMillis()}.csv")
    }

    private val buffer = StringBuilder()
    private var lastFlush = 0L
    private var count = 0

    init {
        buffer.append("t_ms,elapsed_ms,wall_time,type,detail\n")
        flush()
    }

    /** 系统事件（自动记录）。 */
    fun log(type: String, detail: String = "") {
        val now = android.os.SystemClock.elapsedRealtime()
        val elapsed = now - startMs
        buffer.append(now).append(',')
            .append(elapsed).append(',')
            .append(fmt.format(Date())).append(',')
            .append(escape(type)).append(',')
            .append(escape(detail)).append('\n')
        count++
        if (count % 20 == 0 || now - lastFlush > 2_000) flush()
    }

    /** 人工标记（实验者按钮触发）。 */
    fun mark(label: String) {
        log("MANUAL", label)
        flush()   // 手动标记立即落盘，防止丢失
    }

    fun flush() {
        runCatching {
            file.appendText(buffer.toString())
            buffer.setLength(0)
            lastFlush = android.os.SystemClock.elapsedRealtime()
        }
    }

    fun close() {
        flush()
    }

    fun path(): String = file.absolutePath

    private fun escape(s: String): String =
        if (s.contains(',') || s.contains('"') || s.contains('\n')) {
            "\"" + s.replace("\"", "\"\"") + "\""
        } else s

    private fun sanitize(s: String): String =
        s.replace(Regex("[^\\p{L}\\p{N}_-]"), "_").take(32).ifBlank { "session" }
}
