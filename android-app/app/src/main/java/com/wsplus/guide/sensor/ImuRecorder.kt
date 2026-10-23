package com.wsplus.guide.sensor

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.SystemClock
import java.io.File
import java.io.FileWriter
import java.util.Locale

/**
 * IMU 录制器：在拓扑图录制时同步记录陀螺仪 + 加速度计 + 旋转矢量。
 *
 * 用途（论文 E2 实验）：
 *  1. 采集质量监控：录制完立即计算航向变化，判断数据是否合格
 *  2. 方向真值：陀螺仪积分得到真实航向变化，用于验证 NoMaD 的方向判断
 *  3. 步态检测：加速度计峰值检测可估算行走距离
 *
 * 输出格式（CSV，与地图同目录）：
 *   timestamp_ms,gyro_x,gyro_y,gyro_z,acc_x,acc_y,acc_z,rot_x,rot_y,rot_z,rot_w,heading_deg
 *
 * heading_deg 由旋转矢量（ROTATION_VECTOR）解算，是手机朝向的绝对角度（0-360）。
 *
 * 使用方式：
 *   val recorder = ImuRecorder(context, mapDirectory)
 *   recorder.start()   // 开始录制时
 *   recorder.stop()    // 停止录制时（自动 flush 并关闭文件）
 */
class ImuRecorder(
    context: Context,
    private val outputDirectory: File,
    private val sampleIntervalMs: Long = 20L, // 50 Hz
) : SensorEventListener {

    private val sensorManager =
        context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val gyro: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
    private val accel: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val rotation: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)

    private var writer: FileWriter? = null
    private var lastWriteMs = 0L
    private var recording = false

    // 最近一次各传感器读数
    private var gx = 0f; private var gy = 0f; private var gz = 0f
    private var ax = 0f; private var ay = 0f; private var az = 0f
    private var rx = 0f; private var ry = 0f; private var rz = 0f; private var rw = 1f
    private var heading = 0f

    // 基于陀螺仪的累计转角（三轴合成，扣除零偏后）
    // 这是最可靠的"转了多少度"度量，用于采集质量判定。
    private var lastGyroTs = 0L
    var cumulativeRotationDeg: Float = 0f
        private set

    // 零偏校准状态
    private var calibrated = false
    private var calibStartMs = 0L
    private var biasCount = 0
    private var biasSumX = 0f
    private var biasSumY = 0f
    private var biasSumZ = 0f
    var biasX = 0f
        private set
    var biasY = 0f
        private set
    var biasZ = 0f
        private set

    /** 校准是否完成（供 UI 提示）。 */
    val isCalibrated: Boolean
        get() = calibrated

    // 统计（用于录制结束时展示）
    var sampleCount: Int = 0
        private set
    var maxHeadingChangeDeg: Float = 0f
        private set
    private var lastHeading: Float? = null
    private var headingBaseline = 0f
    private var headingCalibrated = false
    var cumulativeHeadingChange: Float = 0f
        private set

    val isAvailable: Boolean
        get() = gyro != null || accel != null || rotation != null

    fun start(): Boolean {
        if (recording) return true
        if (!isAvailable) return false
        val file = File(outputDirectory, IMU_FILENAME)
        file.parentFile?.mkdirs()
        return try {
            writer = FileWriter(file, false).apply {
                write("timestamp_ms,gyro_x,gyro_y,gyro_z,acc_x,acc_y,acc_z," +
                        "rot_x,rot_y,rot_z,rot_w,heading_deg\n")
            }
            recording = true
            sampleCount = 0
            maxHeadingChangeDeg = 0f
            cumulativeHeadingChange = 0f
            cumulativeRotationDeg = 0f
            lastHeading = null
            headingBaseline = 0f
            headingCalibrated = false
            lastGyroTs = 0L
            lastWriteMs = 0L
            // 重置零偏校准
            calibrated = false
            calibStartMs = 0L
            biasCount = 0
            biasSumX = 0f; biasSumY = 0f; biasSumZ = 0f
            biasX = 0f; biasY = 0f; biasZ = 0f
            // SENSOR_DELAY_GAME ≈ 20 ms
            gyro?.let { sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
            accel?.let { sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
            rotation?.let { sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
            true
        } catch (e: Exception) {
            writer?.close()
            writer = null
            recording = false
            false
        }
    }

    fun stop(): ImuStats? {
        if (!recording) return null
        recording = false
        sensorManager.unregisterListener(this)
        try {
            writer?.flush()
            writer?.close()
        } catch (_: Exception) {
        }
        writer = null
        return ImuStats(
            sampleCount = sampleCount,
            durationMs = lastWriteMs,
            maxHeadingChangeDeg = maxHeadingChangeDeg,
            totalHeadingChangeDeg = cumulativeHeadingChange,
            totalRotationDeg = cumulativeRotationDeg,
            biasX = biasX,
            biasY = biasY,
            biasZ = biasZ,
            calibrated = calibrated,
            hasGyro = gyro != null,
            hasAccel = accel != null,
            hasRotation = rotation != null,
        )
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (!recording) return
        when (event.sensor.type) {
            Sensor.TYPE_GYROSCOPE -> {
                gx = event.values[0]; gy = event.values[1]; gz = event.values[2]
                val ts = event.timestamp / 1_000_000L  // ns -> ms

                // ---- 阶段 1：零偏校准（开始录制后的前 CALIBRATION_MS 内静止采样）----
                if (!calibrated) {
                    biasSumX += gx; biasSumY += gy; biasSumZ += gz
                    biasCount++
                    if (biasCount == 1) calibStartMs = ts
                    if (ts - calibStartMs >= CALIBRATION_MS && biasCount >= 10) {
                        biasX = biasSumX / biasCount
                        biasY = biasSumY / biasCount
                        biasZ = biasSumZ / biasCount
                        calibrated = true
                        lastGyroTs = ts   // 校准结束才开始积分
                    }
                    return
                }

                // ---- 阶段 2：扣除零偏后积分 ----
                if (lastGyroTs != 0L) {
                    val dt = (ts - lastGyroTs) / 1000.0
                    if (dt > 0 && dt < 0.5) {  // 过滤异常间隔
                        val cx = gx - biasX
                        val cy = gy - biasY
                        val cz = gz - biasZ
                        var omega = Math.sqrt(
                            (cx.toDouble() * cx + cy.toDouble() * cy + cz.toDouble() * cz)
                        )
                        // 死区：低于阈值视为静止噪声，不计入
                        if (omega < STATIC_DEADBAND_RAD_S) omega = 0.0
                        cumulativeRotationDeg +=
                            Math.toDegrees(omega * dt).toFloat()
                    }
                }
                lastGyroTs = ts
            }
            Sensor.TYPE_ACCELEROMETER -> {
                ax = event.values[0]; ay = event.values[1]; az = event.values[2]
            }
            Sensor.TYPE_ROTATION_VECTOR -> {
                rx = event.values[0]; ry = event.values[1]
                rz = event.values[2]
                rw = if (event.values.size >= 4) event.values[3] else 1f
                heading = computeHeading(rx, ry, rz, rw)

                // 旋转矢量存在慢漂移（实测静止 16s 漂 57°，约 3.6°/s）。
                // 处理：校准期记录航向基线；之后用「基线 + 相对变化」，
                // 并对小于死区的增量直接忽略，避免静止时持续累加。
                if (!headingCalibrated) {
                    if (calibrated) {          // 陀螺仪校准完成后开始记录航向基线
                        headingBaseline = heading
                        headingCalibrated = true
                        lastHeading = heading
                    }
                    return
                }

                // 说明：旋转矢量（Rotation Vector）在设备姿态变化时存在 360° 环绕与
                // 磁力计干扰，实测静止段 heading 漂移可达 0.9–15.6°/s，不适合作为
                // 累计量。因此这里只记录原始 heading 值（写入 CSV 供离线分析），
                // 不再累计到 cumulativeHeadingChange，界面与质量判据只用「累计转角」。
                lastHeading = heading
            }
        }

        // 限频写入（避免文件过大：50 Hz × 3 传感器 = 150 行/秒，限到 50 Hz）
        val now = SystemClock.elapsedRealtime()
        if (now - lastWriteMs < sampleIntervalMs) return
        lastWriteMs = now
        sampleCount++

        try {
            writer?.write(
                String.format(
                    Locale.US,
                    "%d,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.3f\n",
                    now, gx, gy, gz, ax, ay, az, rx, ry, rz, rw, heading
                )
            )
        } catch (_: Exception) {
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    /** 由旋转矢量计算航向角（度，0=正北，顺时针）。
     *
     * 关键：必须把设备的旋转矩阵投影到【世界水平面】，再取朝向。
     * 直接用 R[2][0]/R[2][1] 只适用于手机平放（屏幕朝上）的情况；
     * 手机竖握时主要旋转轴是 Y，该公式会严重失真（实测 270° 只算出 8°）。
     *
     * 正确做法：
     *  1. 由四元数构造旋转矩阵 R（设备坐标 -> 世界坐标）
     *  2. 取设备坐标系的前向轴（-Z，即镜头方向）在世界坐标下的投影
     *  3. 取其水平分量 (x, y) 的 atan2
     */
    private fun computeHeading(x: Float, y: Float, z: Float, w: Float): Float {
        // 旋转矩阵 R 的列向量：设备轴在世界坐标系中的表示
        val r00 = 1.0 - 2.0 * (y.toDouble() * y + z.toDouble() * z)
        val r10 = 2.0 * (x.toDouble() * y + w.toDouble() * z)
        val r20 = 2.0 * (x.toDouble() * z - w.toDouble() * y)

        val r01 = 2.0 * (x.toDouble() * y - w.toDouble() * z)
        val r11 = 1.0 - 2.0 * (x.toDouble() * x + z.toDouble() * z)
        val r21 = 2.0 * (y.toDouble() * z + w.toDouble() * x)

        // 设备"前向"轴（镜头朝向）在设备坐标系下是 -Z。
        // 它在世界坐标系中的方向 = -(R 的第三列) = -(r02, r12, r22)
        // 但更稳健的是用设备 Y 轴（竖握时指向正上方）来算水平朝向。
        //
        // 采用通用做法：取世界坐标系下的"设备前向"水平投影。
        // 设备前向（-Z）在世界坐标 = (-r02, -r12, -r22)
        val r02 = 2.0 * (x.toDouble() * z + w.toDouble() * y)
        val r12 = 2.0 * (y.toDouble() * z - w.toDouble() * x)
        val r22 = 1.0 - 2.0 * (x.toDouble() * x + y.toDouble() * y)

        val fx = -r02
        val fy = -r12
        val fz = -r22

        // 水平分量的长度
        val horiz = Math.hypot(fx, fy)
        var deg: Double = when {
            // 设备接近平放（前向几乎垂直）时，改用设备 Y 轴（顶部朝向）
            horiz < 0.3 -> {
                // 设备顶部（+Y）在世界坐标 = (r01, r11, r21)
                Math.toDegrees(Math.atan2(r01, r11))
            }
            else -> Math.toDegrees(Math.atan2(fx, fy))
        }
        if (deg < 0) deg += 360.0
        return deg.toFloat()
    }

    data class ImuStats(
        val sampleCount: Int,
        val durationMs: Long,
        val maxHeadingChangeDeg: Float,
        val totalHeadingChangeDeg: Float,
        val totalRotationDeg: Float,
        val biasX: Float,
        val biasY: Float,
        val biasZ: Float,
        val calibrated: Boolean,
        val hasGyro: Boolean,
        val hasAccel: Boolean,
        val hasRotation: Boolean,
    )

    companion object {
        const val IMU_FILENAME = "imu.csv"

        /** 零偏校准时长：开始录制后先静止约 1 秒。 */
        const val CALIBRATION_MS = 1_000L

        /** 静止死区：合成角速度低于此值视为噪声（rad/s）。 */
        const val STATIC_DEADBAND_RAD_S = 0.08

        /** 航向死区：单次航向增量低于此值视为漂移（度）。 */
        const val HEADING_DEADBAND_DEG = 0.5f
    }
}
