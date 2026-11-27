package com.red.linuxmonitor

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Memory
import androidx.compose.material.icons.outlined.Speed
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import java.text.DateFormat
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

private fun JSONObject.stringOrNull(key: String): String? =
    if (has(key) && !isNull(key)) optString(key).takeIf { it.isNotBlank() } else null

private fun JSONObject.doubleOrNull(key: String): Double? {
    if (!has(key) || isNull(key)) return null
    return when (val value = opt(key)) {
        is Number -> value.toDouble()
        is String -> value.toDoubleOrNull()
        else -> value.toString().toDoubleOrNull()
    }
}

private fun JSONObject.longOrNull(key: String): Long? {
    if (!has(key) || isNull(key)) return null
    return when (val value = opt(key)) {
        is Number -> value.toLong()
        is String -> value.toLongOrNull()
        else -> value.toString().toLongOrNull()
    }
}

private fun JSONObject.intOrNull(key: String): Int? {
    if (!has(key) || isNull(key)) return null
    return when (val value = opt(key)) {
        is Number -> value.toInt()
        is String -> value.toIntOrNull()
        else -> value.toString().toIntOrNull()
    }
}

private fun formatBytes(value: Long?): String {
    if (value == null) return "—"
    var number = value.toDouble()
    if (number < 0) number = 0.0
    val units = listOf("B", "KiB", "MiB", "GiB", "TiB")
    var index = 0
    while (number >= 1024.0 && index < units.size - 1) {
        number /= 1024.0
        index++
    }
    return if (index == 0) "${number.toLong()} ${units[index]}" else "%.1f ${units[index]}".format(number)
}

private fun formatPct(value: Double?): String =
    value?.let { "%.1f%%".format(it) } ?: "—"

private fun formatUptime(seconds: Double?): String {
    if (seconds == null) return "—"
    val total = seconds.toLong().coerceAtLeast(0)
    val days = total / 86400
    val hours = (total % 86400) / 3600
    val minutes = (total % 3600) / 60
    val secs = total % 60
    val parts = mutableListOf<String>()
    if (days > 0) parts.add("${days}d")
    if (hours > 0 || days > 0) parts.add("${hours}h")
    parts.add("${minutes}m")
    if (days == 0L && hours == 0L) parts.add("${secs}s")
    return parts.joinToString(" ")
}

private fun formatCollectedAt(snapshot: JSONObject): String? {
    val raw = snapshot.stringOrNull("collected_at") ?: return null
    return try {
        val normalized = raw.replace(Regex("\\.\\d+"), "")
        val utc = TimeZone.getTimeZone("UTC")
        val date = listOf(
            SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.getDefault()).apply { timeZone = utc },
            SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault()).apply { timeZone = utc },
        ).firstNotNullOfOrNull { parser ->
            try { parser.parse(normalized) } catch (_: Exception) { null }
        } ?: return raw
        DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.MEDIUM, Locale.getDefault()).format(date)
    } catch (_: Exception) {
        raw
    }
}

internal @Composable
fun SystemInfoScreen(state: MonitorState, onRefresh: () -> Unit) {
    val snapshot = state.snapshot
    val loading = state.snapshotLoading
    val error = state.snapshotError

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp),
    ) {
        Spacer(modifier = Modifier.height(28.dp))

        Text(
            text = stringResource(R.string.screen_title),
            style = MaterialTheme.typography.displayMedium,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.semantics { heading() },
        )

        Spacer(modifier = Modifier.height(8.dp))

        val retained = error != null && snapshot != null
        val collectedText = snapshot?.let { formatCollectedAt(it) }
        val fontScale = LocalDensity.current.fontScale
        BoxWithConstraints(modifier = Modifier.fillMaxWidth()) {
            val isNarrow = maxWidth < 320.dp
            val stacked = fontScale > 1.3f || isNarrow
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (stacked) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Surface(
                            shape = RoundedCornerShape(999.dp),
                            color = if (retained) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.primaryContainer,
                            contentColor = if (retained) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onPrimaryContainer,
                        ) {
                            Text(
                                text = stringResource(if (retained) R.string.dashboard_retained else R.string.dashboard_live),
                                style = MaterialTheme.typography.labelMedium,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                            )
                        }
                        Button(onClick = onRefresh, enabled = !loading) {
                            if (loading && snapshot != null) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(18.dp),
                                    strokeWidth = 2.dp,
                                )
                            } else {
                                Text(text = stringResource(R.string.dashboard_refresh))
                            }
                        }
                    }
                } else {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Surface(
                            shape = RoundedCornerShape(999.dp),
                            color = if (retained) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.primaryContainer,
                            contentColor = if (retained) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onPrimaryContainer,
                        ) {
                            Text(
                                text = stringResource(if (retained) R.string.dashboard_retained else R.string.dashboard_live),
                                style = MaterialTheme.typography.labelMedium,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                            )
                        }
                        Button(onClick = onRefresh, enabled = !loading) {
                            if (loading && snapshot != null) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(18.dp),
                                    strokeWidth = 2.dp,
                                )
                            } else {
                                Text(text = stringResource(R.string.dashboard_refresh))
                            }
                        }
                    }
                }
                if (collectedText != null) {
                    Text(
                        text = stringResource(R.string.dashboard_snapshot, collectedText),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        if (loading && snapshot != null) {
            Text(
                text = stringResource(R.string.dashboard_loading),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
            )
            Spacer(modifier = Modifier.height(8.dp))
        }

        if (error != null) {
            Text(
                text = error,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
            )
            Spacer(modifier = Modifier.height(8.dp))
            Button(onClick = onRefresh) {
                Text(text = stringResource(R.string.dashboard_retry))
            }
            Spacer(modifier = Modifier.height(12.dp))
        }

        if (snapshot == null) {
            if (!loading && error == null) {
                Box(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = stringResource(R.string.dashboard_snapshot_unavailable),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (loading) {
                Box(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator()
                }
            }
        } else {
            HostHeader(snapshot)
            Spacer(modifier = Modifier.height(24.dp))
            CpuCard(snapshot)
            Spacer(modifier = Modifier.height(16.dp))
            MemoryCard(snapshot)
            Spacer(modifier = Modifier.height(16.dp))
            SwapCard(snapshot)
            Spacer(modifier = Modifier.height(24.dp))
            GpuSection(snapshot)
            Spacer(modifier = Modifier.height(24.dp))
            NetworkSection(snapshot)
            Spacer(modifier = Modifier.height(24.dp))
            FilesystemSection(snapshot)
            Spacer(modifier = Modifier.height(32.dp))
        }
    }
}

@Composable
private fun HostHeader(snapshot: JSONObject) {
    val host = snapshot.stringOrNull("hostname") ?: "—"
    val os = snapshot.optJSONObject("os")
    val osLine = if (os != null) {
        buildString {
            os.stringOrNull("name")?.let { append(it) }
            os.stringOrNull("version")?.let { append(" ").append(it) }
            os.stringOrNull("kernel")?.let { append(" · kernel ").append(it) }
            os.stringOrNull("architecture")?.let { append(" · ").append(it) }
        }.trim().ifBlank { null }
    } else null
    val uptimeSeconds = snapshot.doubleOrNull("uptime_seconds")
    val uptimeStatus = snapshot.optJSONObject("uptime_status")
    val uptimeOk = uptimeStatus?.stringOrNull("status") ?: "ok"

    Text(
        text = host,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    if (osLine != null) {
        Text(
            text = osLine,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
    Spacer(modifier = Modifier.height(4.dp))
    if (uptimeOk != "ok") {
        Text(
            text = uptimeStatus?.stringOrNull("error") ?: stringResource(R.string.dashboard_uptime_unavailable),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.error,
        )
    } else {
        Text(
            text = formatUptime(uptimeSeconds),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
fun CpuCard(snapshot: JSONObject? = null) {
    val cpu = snapshot?.optJSONObject("cpu")
    val statusOk = cpu?.stringOrNull("status") ?: "ok"
    val util = cpu?.doubleOrNull("utilization_pct")
    val load1 = cpu?.doubleOrNull("load_1m")
    val load5 = cpu?.doubleOrNull("load_5m")
    val load15 = cpu?.doubleOrNull("load_15m")

    val utilText = formatPct(util)
    val progress = util?.let { it / 100.0 }
    val load1Text = load1?.toString() ?: "—"
    val load5Text = load5?.toString() ?: "—"
    val load15Text = load15?.toString() ?: "—"

    androidx.compose.foundation.layout.BoxWithConstraints {
        val isNarrow = maxWidth < 330.dp

        Surface(
            shape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp, bottomStart = 12.dp, bottomEnd = 32.dp),
            color = MaterialTheme.colorScheme.primary,
            contentColor = MaterialTheme.colorScheme.onPrimary,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(20.dp)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Icon(
                        imageVector = Icons.Outlined.Speed,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Text(
                        text = stringResource(R.string.cpu_title),
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.semantics { heading() },
                    )
                }

                Spacer(modifier = Modifier.height(16.dp))

                if (statusOk != "ok") {
                    Text(
                        text = cpu?.stringOrNull("error") ?: stringResource(R.string.dashboard_cpu_collection_failed),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error,
                    )
                } else {
                    if (isNarrow) {
                        Text(
                            text = utilText,
                            style = MaterialTheme.typography.displayLarge,
                            fontWeight = FontWeight.Bold,
                        )
                        if (progress != null) {
                            Spacer(modifier = Modifier.height(12.dp))
                            Row(horizontalArrangement = Arrangement.Center) {
                                CircularProgressIndicator(
                                    progress = { progress.toFloat() },
                                    color = MaterialTheme.colorScheme.onPrimary,
                                    trackColor = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.22f),
                                    strokeWidth = 8.dp,
                                    modifier = Modifier.size(90.dp).clearAndSetSemantics { },
                                )
                            }
                        }
                    } else {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(
                                text = utilText,
                                style = MaterialTheme.typography.displayLarge,
                                fontWeight = FontWeight.Bold,
                            )
                            if (progress != null) {
                                Spacer(modifier = Modifier.weight(1f))
                                CircularProgressIndicator(
                                    progress = { progress.toFloat() },
                                    color = MaterialTheme.colorScheme.onPrimary,
                                    trackColor = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.22f),
                                    strokeWidth = 8.dp,
                                    modifier = Modifier.size(90.dp).clearAndSetSemantics { },
                                )
                            }
                        }
                    }

                    Spacer(modifier = Modifier.height(20.dp))
                    HorizontalDivider(color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.2f))
                    Spacer(modifier = Modifier.height(16.dp))

                    Text(
                        text = stringResource(R.string.load_average_label),
                        style = MaterialTheme.typography.labelMedium,
                    )
                    Spacer(modifier = Modifier.height(8.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceEvenly,
                    ) {
                        LoadCell(value = load1Text, label = stringResource(R.string.load_1m_label))
                        LoadCell(value = load5Text, label = stringResource(R.string.load_5m_label))
                        LoadCell(value = load15Text, label = stringResource(R.string.load_15m_label))
                    }
                }
            }
        }
    }
}

@Composable
private fun LoadCell(value: String, label: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(text = value, style = MaterialTheme.typography.headlineSmall)
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.8f),
        )
    }
}

@Composable
fun MemoryCard(snapshot: JSONObject? = null) {
    val mem = snapshot?.optJSONObject("memory")
    val statusOk = mem?.stringOrNull("status") ?: "ok"
    val usedPercent = mem?.doubleOrNull("used_percent")
    val usedBytes = mem?.longOrNull("used_bytes")
    val totalBytes = mem?.longOrNull("total_bytes")
    val availBytes = mem?.longOrNull("available_bytes")

    val percentText = formatPct(usedPercent)
    val progress = usedPercent?.let { (it / 100.0).toFloat() }
    val usedTotalText = "${formatBytes(usedBytes)} of ${formatBytes(totalBytes)}"
    val availText = if (availBytes != null) {
        stringResource(R.string.dashboard_available, formatBytes(availBytes))
    } else {
        "—"
    }

    androidx.compose.foundation.layout.BoxWithConstraints {
        val isNarrow = maxWidth < 360.dp

        Surface(
            shape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp, bottomStart = 32.dp, bottomEnd = 12.dp),
            color = MaterialTheme.colorScheme.secondaryContainer,
            contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(20.dp)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Icon(
                        imageVector = Icons.Outlined.Memory,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Text(
                        text = stringResource(R.string.memory_title),
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.semantics { heading() },
                    )
                }

                Spacer(modifier = Modifier.height(16.dp))

                if (statusOk != "ok") {
                    Text(
                        text = mem?.stringOrNull("error") ?: stringResource(R.string.dashboard_memory_collection_failed),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error,
                    )
                } else {
                    Text(
                        text = percentText,
                        style = MaterialTheme.typography.headlineLarge,
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    if (progress != null) {
                        LinearProgressIndicator(
                            progress = { progress },
                            color = MaterialTheme.colorScheme.onSecondaryContainer,
                            trackColor = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.22f),
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(10.dp)
                                .clearAndSetSemantics { },
                        )
                        Spacer(modifier = Modifier.height(12.dp))
                    } else {
                        Spacer(modifier = Modifier.height(12.dp))
                    }

                    if (isNarrow) {
                        Text(text = usedTotalText, style = MaterialTheme.typography.bodyMedium)
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = availText,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.8f),
                        )
                    } else {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(text = usedTotalText, style = MaterialTheme.typography.bodyMedium)
                            Text(
                                text = availText,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.8f),
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun SwapCard(snapshot: JSONObject? = null) {
    val swap = snapshot?.optJSONObject("swap")
    val statusOk = swap?.stringOrNull("status") ?: "ok"
    val usedPercent = swap?.doubleOrNull("used_percent")
    val usedBytes = swap?.longOrNull("used_bytes")
    val totalBytes = swap?.longOrNull("total_bytes")
    val freeBytes = swap?.longOrNull("free_bytes")

    Surface(
        shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp, bottomStart = 12.dp, bottomEnd = 24.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = stringResource(R.string.dashboard_swap_title),
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.semantics { heading() },
            )
            Spacer(modifier = Modifier.height(12.dp))

            if (statusOk != "ok") {
                Text(
                    text = swap?.stringOrNull("error") ?: stringResource(R.string.dashboard_swap_collection_failed),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
            } else if (totalBytes == null || totalBytes == 0L) {
                Text(
                    text = stringResource(R.string.dashboard_swap_no_swap),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                val percentText = usedPercent?.let { formatPct(it) } ?: "—"
                val progress = ((usedPercent ?: 0.0) / 100.0).toFloat()
                Text(
                    text = percentText,
                    style = MaterialTheme.typography.headlineSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(modifier = Modifier.height(8.dp))
                LinearProgressIndicator(
                    progress = { progress },
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    trackColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.22f),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(8.dp)
                        .clearAndSetSemantics { },
                )
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "${formatBytes(usedBytes)} of ${formatBytes(totalBytes)}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = if (freeBytes != null) {
                        stringResource(R.string.dashboard_swap_free, formatBytes(freeBytes))
                    } else {
                        "—"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f),
                )
            }
        }
    }
}

@Composable
fun GpuSection(snapshot: JSONObject? = null) {
    val gpus = snapshot?.optJSONArray("gpus")
    val gpuStatus = snapshot?.optJSONObject("gpu_status")
    val statusOk = gpuStatus?.stringOrNull("status") ?: "ok"

    Surface(
        shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp, bottomStart = 12.dp, bottomEnd = 24.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(
                    imageVector = Icons.Outlined.Dns,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = stringResource(R.string.gpu_title),
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.semantics { heading() },
                )
            }

            Spacer(modifier = Modifier.height(12.dp))

            if (statusOk != "ok") {
                Text(
                    text = gpuStatus?.stringOrNull("error") ?: stringResource(R.string.dashboard_gpu_collection_failed),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
            } else if (gpus == null || gpus.length() == 0) {
                Text(
                    text = stringResource(R.string.dashboard_gpu_none),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                for (i in 0 until gpus.length()) {
                    val gpu = gpus.optJSONObject(i) ?: continue
                    val name = gpu.stringOrNull("name") ?: "—"
                    val vendor = gpu.stringOrNull("vendor")
                    val gpuStatusOne = gpu.stringOrNull("status") ?: "ok"
                    val util = gpu.doubleOrNull("utilization_pct")
                    val temp = gpu.doubleOrNull("temperature_celsius")
                    val vramUsed = gpu.longOrNull("vram_used_bytes")
                    val vramTotal = gpu.longOrNull("vram_total_bytes")
                    val vramPct = gpu.doubleOrNull("vram_used_percent")

                    Text(text = name, style = MaterialTheme.typography.titleSmall)
                    if (vendor != null) {
                        Text(
                            text = vendor,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(modifier = Modifier.height(8.dp))

                    if (gpuStatusOne != "ok") {
                        Text(
                            text = gpu.stringOrNull("error") ?: stringResource(R.string.dashboard_gpu_collection_failed),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.error,
                        )
                    } else {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Column {
                                Text(
                                    text = stringResource(R.string.gpu_utilization_label),
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                                Text(
                                    text = formatPct(util),
                                    style = MaterialTheme.typography.headlineSmall,
                                )
                            }
                            Column {
                                Text(
                                    text = stringResource(R.string.gpu_temperature_label),
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                                Text(
                                    text = temp?.let { "${it} °C" } ?: "—",
                                    style = MaterialTheme.typography.headlineSmall,
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(12.dp))

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = stringResource(R.string.gpu_vram_label),
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Text(
                                text = "${formatBytes(vramUsed)} of ${formatBytes(vramTotal)}",
                                style = MaterialTheme.typography.bodyMedium,
                            )
                        }
                    }

                    if (i < gpus.length() - 1) {
                        Spacer(modifier = Modifier.height(12.dp))
                        HorizontalDivider(color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.2f))
                        Spacer(modifier = Modifier.height(12.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun NetworkSection(snapshot: JSONObject) {
    val network = snapshot.optJSONArray("network")
    val status = snapshot.optJSONObject("network_status")
    val statusOk = status?.stringOrNull("status") ?: "ok"

    Surface(
        shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp, bottomStart = 12.dp, bottomEnd = 24.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(
                    imageVector = Icons.Outlined.Storage,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = stringResource(R.string.dashboard_network_title),
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.semantics { heading() },
                )
            }
            Spacer(modifier = Modifier.height(12.dp))

            if (statusOk != "ok") {
                Text(
                    text = status?.stringOrNull("error") ?: stringResource(R.string.dashboard_network_collection_failed),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
            } else if (network == null || network.length() == 0) {
                Text(
                    text = stringResource(R.string.dashboard_network_none),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                for (i in 0 until network.length()) {
                    val iface = network.optJSONObject(i) ?: continue
                    val name = iface.stringOrNull("name") ?: "—"
                    Text(text = name, style = MaterialTheme.typography.titleSmall)
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "${stringResource(R.string.dashboard_rx)} ${formatBytes(iface.longOrNull("rx_bytes"))} · ${stringResource(R.string.dashboard_tx)} ${formatBytes(iface.longOrNull("tx_bytes"))}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = "${stringResource(R.string.dashboard_packets)} ${iface.longOrNull("rx_packets") ?: "—"} / ${iface.longOrNull("tx_packets") ?: "—"} · ${stringResource(R.string.dashboard_errors)} ${iface.longOrNull("rx_errors") ?: 0L} / ${iface.longOrNull("tx_errors") ?: 0L} · ${stringResource(R.string.dashboard_dropped)} ${iface.longOrNull("rx_dropped") ?: 0L} / ${iface.longOrNull("tx_dropped") ?: 0L}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (i < network.length() - 1) {
                        Spacer(modifier = Modifier.height(8.dp))
                        HorizontalDivider(color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.2f))
                        Spacer(modifier = Modifier.height(8.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun FilesystemSection(snapshot: JSONObject) {
    val filesystems = snapshot.optJSONArray("filesystems")
    val status = snapshot.optJSONObject("filesystems_status")
    val statusOk = status?.stringOrNull("status") ?: "ok"

    Surface(
        shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp, bottomStart = 12.dp, bottomEnd = 24.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(
                    imageVector = Icons.Outlined.Storage,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = stringResource(R.string.dashboard_storage_title),
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.semantics { heading() },
                )
            }
            Spacer(modifier = Modifier.height(12.dp))

            if (statusOk != "ok") {
                Text(
                    text = status?.stringOrNull("error") ?: stringResource(R.string.dashboard_storage_collection_failed),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
            } else if (filesystems == null || filesystems.length() == 0) {
                Text(
                    text = stringResource(R.string.dashboard_storage_none),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                for (i in 0 until filesystems.length()) {
                    val fs = filesystems.optJSONObject(i) ?: continue
                    val mount = fs.stringOrNull("mountpoint") ?: "—"
                    val device = fs.stringOrNull("device")
                    val fstype = fs.stringOrNull("fstype")
                    val used = fs.longOrNull("used_bytes")
                    val total = fs.longOrNull("total_bytes")
                    val avail = fs.longOrNull("available_bytes")
                    val pct = fs.doubleOrNull("used_percent")

                    Text(text = mount, style = MaterialTheme.typography.titleSmall)
                    val sub = buildString {
                        device?.let { append(it) }
                        fstype?.let { if (isNotEmpty()) append(" · "); append(it) }
                    }
                    if (sub.isNotBlank()) {
                        Text(
                            text = sub,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(modifier = Modifier.height(4.dp))
                    LinearProgressIndicator(
                        progress = { ((pct ?: 0.0) / 100.0).toFloat() },
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        trackColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.22f),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(8.dp)
                            .clearAndSetSemantics { },
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "${formatBytes(used)} of ${formatBytes(total)} · ${stringResource(R.string.dashboard_available, formatBytes(avail))}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (i < filesystems.length() - 1) {
                        Spacer(modifier = Modifier.height(8.dp))
                        HorizontalDivider(color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.2f))
                        Spacer(modifier = Modifier.height(8.dp))
                    }
                }
            }
        }
    }
}