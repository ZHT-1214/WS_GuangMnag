package com.wsplus.guide.domain

import kotlinx.coroutines.flow.Flow

data class GeoPoint(val latitude: Double, val longitude: Double)

data class TopologyMapSummary(
    val id: String,
    val name: String,
    val version: Int,
)

sealed interface GuidanceEvent {
    data class Speak(val text: String, val priority: Int = 0) : GuidanceEvent
    data class Turn(val direction: Direction, val distanceMeters: Int?) : GuidanceEvent
    data class Obstacle(val direction: Direction, val severity: Severity) : GuidanceEvent
    data object Arrived : GuidanceEvent
    data class Degraded(val reason: String) : GuidanceEvent
}

enum class Direction { LEFT, FORWARD, RIGHT, BACK }
enum class Severity { INFO, WARNING, DANGER }

interface WalkingNavigationService {
    val events: Flow<GuidanceEvent>
    suspend fun start(destination: GeoPoint)
    suspend fun stop()
}

interface TopologyNavigationService {
    val availableMaps: Flow<List<TopologyMapSummary>>
    val events: Flow<GuidanceEvent>
    suspend fun start(mapId: String, destinationNodeId: String)
    suspend fun stop()
}

interface VisionCloudService {
    val events: Flow<GuidanceEvent>
    suspend fun startObstacleDetection()
    suspend fun stopObstacleDetection()
    suspend fun findObject(name: String)
    suspend fun describeEnvironment(): String
}

interface VoiceCommandService {
    suspend fun listenOnce(): String
}

interface HapticFeedbackController {
    suspend fun emit(event: GuidanceEvent)
}

class NoOpHapticFeedbackController : HapticFeedbackController {
    override suspend fun emit(event: GuidanceEvent) = Unit
}
