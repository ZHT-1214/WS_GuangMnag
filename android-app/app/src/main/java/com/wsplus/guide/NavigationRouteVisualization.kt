package com.wsplus.guide

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.min

@Composable
internal fun NavigationRouteVisualization(
    routeNodeNames: List<String>,
    currentNodeName: String?,
    destinationNodeName: String,
    trajectory: List<Pair<Float, Float>>,
) {
    val currentIndex = routeNodeNames.indexOfNode(currentNodeName)
    val destinationIndex = routeNodeNames.indexOfNode(destinationNodeName)
    val listState = rememberLazyListState()

    LaunchedEffect(currentIndex) {
        if (currentIndex >= 0) listState.animateScrollToItem((currentIndex - 1).coerceAtLeast(0))
    }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("路径与进度", fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
        Text(
            if (currentIndex >= 0 && destinationIndex >= 0) {
                "已识别到节点 ${currentIndex + 1}，目标节点 ${destinationIndex + 1} / ${routeNodeNames.size}"
            } else {
                "正在识别当前位置，目标节点 ${destinationIndex + 1} / ${routeNodeNames.size}"
            },
            fontSize = 15.sp,
        )
        if (routeNodeNames.isNotEmpty()) {
            LazyRow(
                state = listState,
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                itemsIndexed(routeNodeNames, key = { index, name -> "$index/$name" }) { index, _ ->
                    val isCurrent = index == currentIndex
                    val isGoal = index == destinationIndex
                    val isPassed = currentIndex >= 0 && index < currentIndex
                    val markerColor = when {
                        isCurrent -> MaterialTheme.colorScheme.primary
                        isGoal -> MaterialTheme.colorScheme.tertiary
                        isPassed -> MaterialTheme.colorScheme.primary.copy(alpha = 0.62f)
                        else -> MaterialTheme.colorScheme.surfaceVariant
                    }
                    val markerTextColor = when {
                        isCurrent -> MaterialTheme.colorScheme.onPrimary
                        isGoal -> MaterialTheme.colorScheme.onTertiary
                        isPassed -> MaterialTheme.colorScheme.onPrimary
                        else -> MaterialTheme.colorScheme.onSurfaceVariant
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Surface(
                            modifier = Modifier.size(34.dp),
                            shape = CircleShape,
                            color = markerColor,
                        ) {
                            Box(contentAlignment = Alignment.Center) {
                                Text(
                                    when {
                                        isCurrent -> "现"
                                        isGoal -> "终"
                                        else -> (index + 1).toString()
                                    },
                                    color = markerTextColor,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                )
                            }
                        }
                        if (index < routeNodeNames.lastIndex) {
                            Box(
                                modifier = Modifier
                                    .width(24.dp)
                                    .height(3.dp)
                                    .background(
                                        if (currentIndex >= 0 && index < currentIndex) {
                                            MaterialTheme.colorScheme.primary.copy(alpha = 0.62f)
                                        } else {
                                            MaterialTheme.colorScheme.outlineVariant
                                        },
                                    ),
                            )
                        }
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Text("起点", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("当前位置", fontSize = 13.sp, color = MaterialTheme.colorScheme.primary)
                Text("目标", fontSize = 13.sp, color = MaterialTheme.colorScheme.tertiary)
            }
        }
        if (trajectory.isNotEmpty()) {
            Text("模型预测的局部路径", fontSize = 16.sp, fontWeight = FontWeight.Medium)
            PredictedPathCanvas(trajectory)
        }
        Text(
            "节点路线按预录顺序显示，不代表室内坐标或实际距离；局部曲线是模型预测，不是已走轨迹。",
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun PredictedPathCanvas(trajectory: List<Pair<Float, Float>>) {
    val primary = MaterialTheme.colorScheme.primary
    val guide = MaterialTheme.colorScheme.outlineVariant
    val startColor = MaterialTheme.colorScheme.tertiary
    Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(190.dp)
            .semantics { contentDescription = "NoMaD 模型预测的局部路径图" },
    ) {
        val pad = 12.dp.toPx()
        val plotWidth = size.width - pad * 2
        val plotHeight = size.height - pad * 2
        val scale = min(plotWidth / LATERAL_RANGE, plotHeight / FORWARD_RANGE)
        val centerX = size.width / 2f
        val originY = pad + MAX_FORWARD * scale
        val origin = Offset(centerX, originY)

        drawLine(guide, Offset(centerX, pad), Offset(centerX, size.height - pad), strokeWidth = 1.dp.toPx())
        drawLine(guide, Offset(pad, originY), Offset(size.width - pad, originY), strokeWidth = 1.dp.toPx())

        val path = Path().apply {
            moveTo(origin.x, origin.y)
            trajectory.forEach { (forward, left) ->
                lineTo(centerX - left * scale, pad + (MAX_FORWARD - forward) * scale)
            }
        }
        clipRect(pad, pad, size.width - pad, size.height - pad) {
            drawPath(path, primary, style = Stroke(width = 4.dp.toPx()))
            drawCircle(startColor, radius = 7.dp.toPx(), center = origin)
            trajectory.lastOrNull()?.let { (forward, left) ->
                drawCircle(primary, radius = 6.dp.toPx(), center = Offset(centerX - left * scale, pad + (MAX_FORWARD - forward) * scale))
            }
        }
    }
}

private fun List<String>.indexOfNode(node: String?): Int {
    if (node.isNullOrBlank()) return -1
    val normalized = node.replace('\\', '/')
    return indexOfFirst { candidate ->
        val candidateNormalized = candidate.replace('\\', '/')
        candidateNormalized == normalized || candidateNormalized.substringAfterLast('/') == normalized.substringAfterLast('/')
    }
}

private const val LATERAL_RANGE = 8f
private const val FORWARD_RANGE = 7.5f
private const val MAX_FORWARD = 5f
