package com.red.linuxmonitor

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.material.icons.outlined.Apps
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.TextButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

@Composable
internal fun DockerScreen(state: MonitorState, onRefresh: () -> Unit) {
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

        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = stringResource(R.string.service_docker_title),
                style = MaterialTheme.typography.displayMedium,
                fontWeight = FontWeight.Bold,
                modifier = Modifier
                    .semantics { heading() }
                    .weight(1f, fill = false),
            )
            TextButton(onClick = onRefresh, enabled = !loading) {
                Text(text = stringResource(R.string.service_refresh))
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        if (snapshot != null) {
            val ts = formatSampleTime(snapshot.stringOrNull("collected_at"))
            if (ts != null) {
                Text(
                    text = stringResource(R.string.service_sample, ts),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(modifier = Modifier.height(12.dp))
        }

        when {
            snapshot == null && loading -> {
                Box(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator()
                }
            }
            snapshot == null && error != null -> {
                Text(
                    text = error,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                )
                Spacer(modifier = Modifier.height(12.dp))
                Button(onClick = onRefresh) {
                    Text(text = stringResource(R.string.service_retry))
                }
            }
            snapshot == null -> {
                Box(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator()
                }
            }
            else -> {
                val dockerStatus = snapshot.optJSONObject("docker_status")
                val statusOk = dockerStatus?.stringOrNull("status") ?: "ok"
                val containers = snapshot.optJSONArray("docker_containers") ?: JSONArray()

                Surface(
                    shape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp, bottomStart = 12.dp, bottomEnd = 32.dp),
                    color = MaterialTheme.colorScheme.primary,
                    contentColor = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(22.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Outlined.Apps,
                                contentDescription = null,
                                modifier = Modifier.size(18.dp),
                            )
                            Text(
                                text = stringResource(R.string.service_docker_engine),
                                style = MaterialTheme.typography.headlineSmall,
                                modifier = Modifier.semantics { heading() },
                            )
                        }

                        Spacer(modifier = Modifier.height(16.dp))

                        if (statusOk != "ok") {
                            Text(
                                text = stringResource(R.string.service_docker_unavailable),
                                style = MaterialTheme.typography.titleMedium,
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(
                                text = dockerStatus?.stringOrNull("error")
                                    ?: stringResource(R.string.service_docker_collection_failed),
                                style = MaterialTheme.typography.bodyMedium,
                            )
                        } else {
                            Text(
                                text = stringResource(R.string.service_docker_running),
                                style = MaterialTheme.typography.labelLarge,
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(
                                text = containers.length().toString(),
                                style = MaterialTheme.typography.displayLarge,
                                fontWeight = FontWeight.Bold,
                            )
                            Text(
                                text = stringResource(R.string.service_running_containers),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.85f),
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                if (statusOk == "ok") {
                    if (containers.length() == 0) {
                        Text(
                            text = stringResource(R.string.service_no_running_containers),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        Surface(
                            shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp, bottomStart = 12.dp, bottomEnd = 24.dp),
                            color = MaterialTheme.colorScheme.surfaceVariant,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                for (i in 0 until containers.length()) {
                                    val c = containers.optJSONObject(i) ?: continue
                                    val name = c.stringOrNull("name") ?: "—"
                                    val status = c.stringOrNull("status") ?: "—"
                                    val image = c.stringOrNull("image") ?: "—"
                                    val id = c.stringOrNull("id") ?: "—"

                                    Column(modifier = Modifier.fillMaxWidth()) {
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalArrangement = Arrangement.SpaceBetween,
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Text(
                                                text = name,
                                                style = MaterialTheme.typography.titleSmall,
                                                modifier = Modifier.weight(1f),
                                            )
                                            Text(
                                                text = status,
                                                style = MaterialTheme.typography.bodySmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            )
                                        }
                                        Spacer(modifier = Modifier.height(4.dp))
                                        Text(
                                            text = "${stringResource(R.string.service_image)}: $image",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                        Text(
                                            text = "${stringResource(R.string.service_id)}: $id",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }

                                    if (i < containers.length() - 1) {
                                        Spacer(modifier = Modifier.height(12.dp))
                                        HorizontalDivider(color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.2f))
                                        Spacer(modifier = Modifier.height(12.dp))
                                    }
                                }
                            }
                        }
                    }
                } else {
                    Text(
                        text = dockerStatus?.stringOrNull("error")
                            ?: stringResource(R.string.service_docker_collection_failed),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error,
                    )
                }

                if (error != null) {
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = error,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedButton(onClick = onRefresh) {
                        Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(modifier = Modifier.width(4.dp))
                        Text(stringResource(R.string.service_retry))
                    }
                }

                Spacer(modifier = Modifier.height(32.dp))
            }
        }
    }
}

@Composable
internal fun LlamaScreen(state: MonitorState, onRefresh: () -> Unit, onRefreshContext: () -> Unit) {
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

        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = stringResource(R.string.service_llama_title),
                style = MaterialTheme.typography.displayMedium,
                fontWeight = FontWeight.Bold,
                modifier = Modifier
                    .semantics { heading() }
                    .weight(1f, fill = false),
            )
            TextButton(onClick = onRefresh, enabled = !loading) {
                Text(text = stringResource(R.string.service_refresh))
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        if (snapshot != null) {
            val ts = formatSampleTime(snapshot.stringOrNull("collected_at"))
            if (ts != null) {
                Text(
                    text = stringResource(R.string.service_sample, ts),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(modifier = Modifier.height(12.dp))
        }

        when {
            snapshot == null && loading -> {
                Box(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator()
                }
            }
            snapshot == null && error != null -> {
                Text(
                    text = error,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
                Spacer(modifier = Modifier.height(12.dp))
                Button(onClick = onRefresh) {
                    Text(text = stringResource(R.string.service_retry))
                }
            }
            snapshot == null -> {
                Box(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator()
                }
            }
            else -> {
                val l = snapshot.optJSONObject("llama_cpp")
                val models = l?.optJSONArray("models") ?: JSONArray()
                val loadedCount = (0 until models.length()).count { i ->
                    models.optJSONObject(i)?.stringOrNull("status") == "loaded"
                }
                val totalCount = models.length()
                val status = l?.stringOrNull("status") ?: "unavailable"
                val lError = l?.stringOrNull("error")

                Surface(
                    shape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp, bottomStart = 12.dp, bottomEnd = 32.dp),
                    color = MaterialTheme.colorScheme.primary,
                    contentColor = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(22.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Outlined.Storage,
                                contentDescription = null,
                                modifier = Modifier.size(18.dp),
                            )
                            Text(
                                text = stringResource(R.string.service_llama_server),
                                style = MaterialTheme.typography.headlineSmall,
                                modifier = Modifier.semantics { heading() },
                            )
                        }

                        Spacer(modifier = Modifier.height(12.dp))

                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Text(
                                text = if (status == "running") {
                                    stringResource(R.string.service_running)
                                } else {
                                    status
                                },
                                style = MaterialTheme.typography.labelLarge,
                            )
                        }

                        if (status == "running" && lError == null) {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(
                                text = loadedCount.toString(),
                                style = MaterialTheme.typography.displayLarge,
                                fontWeight = FontWeight.Bold,
                            )
                            Text(
                                text = stringResource(R.string.service_loaded_models),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.85f),
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = stringResource(R.string.service_total_models, totalCount),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.85f),
                            )
                        }

                        if (lError != null) {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(
                                text = lError,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                if (l == null) {
                    Text(
                        text = stringResource(R.string.service_model_inventory_unavailable),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else if (models.length() == 0) {
                    if (status == "running" && lError == null) {
                        Text(
                            text = stringResource(R.string.service_no_models_reported),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else if (status == "loading") {
                        Text(
                            text = stringResource(R.string.service_loading_models),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        Text(
                            text = stringResource(R.string.service_model_inventory_unavailable),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                } else {
                    Surface(
                        shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp, bottomStart = 12.dp, bottomEnd = 24.dp),
                        color = MaterialTheme.colorScheme.surfaceVariant,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            for (i in 0 until models.length()) {
                                val model = models.optJSONObject(i) ?: continue
                                val id = model.stringOrNull("id") ?: "—"
                                val mStatus = model.stringOrNull("status") ?: "—"
                                val contextTokens = model.longOrNull("context_tokens")
                                val trainingTokens = model.longOrNull("training_context_tokens")
                                val totalSlots = model.intOrNull("total_slots")
                                val contextError = model.stringOrNull("context_error")

                                Column(modifier = Modifier.fillMaxWidth()) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Text(
                                            text = id,
                                            style = MaterialTheme.typography.titleSmall,
                                            modifier = Modifier.weight(1f),
                                        )
                                        Text(
                                            text = mStatus,
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                    Spacer(modifier = Modifier.height(4.dp))
                                    if (contextTokens != null) {
                                        Text(
                                            text = "${stringResource(R.string.service_context)}: ${formatNumber(contextTokens)} tokens",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                    if (trainingTokens != null) {
                                        Text(
                                            text = "${stringResource(R.string.service_training_context)}: ${formatNumber(trainingTokens)} tokens",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                    if (totalSlots != null) {
                                        Text(
                                            text = "${stringResource(R.string.service_slots)}: $totalSlots",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                    if (contextError != null) {
                                        Text(
                                            text = contextError,
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.error,
                                        )
                                    }
                                }

                                if (i < models.length() - 1) {
                                    Spacer(modifier = Modifier.height(12.dp))
                                    HorizontalDivider(color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.2f))
                                    Spacer(modifier = Modifier.height(12.dp))
                                }
                            }
                        }
                    }
                }

                if (error != null) {
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = error,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedButton(onClick = onRefresh) {
                        Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(modifier = Modifier.width(4.dp))
                        Text(stringResource(R.string.service_retry))
                    }
                }

                Spacer(modifier = Modifier.height(24.dp))

                Surface(
                    shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp, bottomStart = 12.dp, bottomEnd = 24.dp),
                    color = MaterialTheme.colorScheme.secondaryContainer,
                    contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = stringResource(R.string.service_context_usage),
                                style = MaterialTheme.typography.titleMedium,
                                modifier = Modifier.semantics { heading() },
                            )
                            IconButton(onClick = onRefreshContext) {
                                Icon(Icons.Outlined.Refresh, contentDescription = stringResource(R.string.service_refresh_context_usage))
                            }
                        }

                        Spacer(modifier = Modifier.height(8.dp))

                        val contextSnapshot = state.context
                        val contextLoading = state.contextLoading
                        val contextError = state.contextError

                        if (contextSnapshot != null) {
                            val cts = formatSampleTime(contextSnapshot.stringOrNull("collected_at"))
                            if (cts != null) {
                                Text(
                                    text = stringResource(R.string.service_sample, cts),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.8f),
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                            }
                        }

                        when {
                            contextSnapshot == null && contextLoading -> {
                                Box(
                                    modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    CircularProgressIndicator(
                                        modifier = Modifier.size(24.dp),
                                        color = MaterialTheme.colorScheme.onSecondaryContainer,
                                    )
                                }
                            }
                            contextSnapshot == null && contextError != null -> {
                                Text(
                                    text = contextError,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.error,
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                                OutlinedButton(onClick = onRefreshContext) {
                                    Text(stringResource(R.string.service_retry))
                                }
                            }
                            else -> {
                                val cl = contextSnapshot?.optJSONObject("llama_cpp")
                                val contextStatus = cl?.stringOrNull("status")
                                val contextErr = cl?.stringOrNull("error")

                                if (contextSnapshot == null || cl == null || contextStatus != "running" || contextErr != null) {
                                    Text(
                                        text = stringResource(R.string.service_context_unavailable),
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    if (contextErr != null) {
                                        Spacer(modifier = Modifier.height(4.dp))
                                        Text(
                                            text = contextErr,
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.error,
                                        )
                                    }
                                    if (contextError != null) {
                                        Spacer(modifier = Modifier.height(4.dp))
                                        Text(
                                            text = contextError,
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.error,
                                        )
                                    }
                                } else {
                                    val cModels = cl.optJSONArray("models") ?: JSONArray()
                                    var hasLoaded = false
                                    for (mi in 0 until cModels.length()) {
                                        val model = cModels.optJSONObject(mi) ?: continue
                                        if (model.stringOrNull("status") != "loaded") continue
                                        hasLoaded = true
                                        val modelId = model.stringOrNull("id") ?: "—"
                                        val slotsArray = if (model.has("slots") && !model.isNull("slots")) model.optJSONArray("slots") else null

                                        Surface(
                                            shape = RoundedCornerShape(16.dp),
                                            color = MaterialTheme.colorScheme.surface,
                                            contentColor = MaterialTheme.colorScheme.onSurface,
                                            modifier = Modifier.fillMaxWidth(),
                                        ) {
                                            Column(modifier = Modifier.padding(12.dp)) {
                                                Text(
                                                    text = modelId,
                                                    style = MaterialTheme.typography.titleSmall,
                                                )
                                                Spacer(modifier = Modifier.height(4.dp))

                                                if (slotsArray == null) {
                                                    Text(
                                                        text = stringResource(R.string.service_context_unavailable),
                                                        style = MaterialTheme.typography.bodySmall,
                                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                    )
                                                } else if (slotsArray.length() == 0) {
                                                    Text(
                                                        text = stringResource(R.string.service_no_slots_reported),
                                                        style = MaterialTheme.typography.bodySmall,
                                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                    )
                                                } else {
                                                    for (si in 0 until slotsArray.length()) {
                                                        val slot = slotsArray.optJSONObject(si) ?: continue
                                                        val slotId = if (slot.has("id")) slot.optInt("id") else si
                                                        val usedTokens = slot.longOrNull("used_tokens")
                                                        val remainingTokens = slot.longOrNull("remaining_tokens")
                                                        val capacityTokens = slot.longOrNull("context_tokens")
                                                        val hasProcessing = slot.has("is_processing") && !slot.isNull("is_processing")
                                                        val processing = if (hasProcessing) slot.optBoolean("is_processing") else null
                                                        val busyLabel = when (processing) {
                                                            true -> stringResource(R.string.service_busy)
                                                            false -> stringResource(R.string.service_idle)
                                                            null -> stringResource(R.string.service_unknown)
                                                        }

                                                        Column(modifier = Modifier.fillMaxWidth()) {
                                                            Text(
                                                                text = stringResource(R.string.service_slot, slotId),
                                                                style = MaterialTheme.typography.bodySmall,
                                                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                            )
                                                            Spacer(modifier = Modifier.height(4.dp))
                                                            Row(
                                                                modifier = Modifier.fillMaxWidth(),
                                                                horizontalArrangement = Arrangement.SpaceBetween,
                                                            ) {
                                                                Column {
                                                                    Text(
                                                                        text = stringResource(R.string.service_used),
                                                                        style = MaterialTheme.typography.labelSmall,
                                                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                                    )
                                                                    Text(
                                                                        text = if (usedTokens != null) "${formatNumber(usedTokens)} tokens" else stringResource(R.string.service_unknown),
                                                                        style = MaterialTheme.typography.bodySmall,
                                                                    )
                                                                }
                                                                Column {
                                                                    Text(
                                                                        text = stringResource(R.string.service_remaining),
                                                                        style = MaterialTheme.typography.labelSmall,
                                                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                                    )
                                                                    Text(
                                                                        text = if (remainingTokens != null) "${formatNumber(remainingTokens)} tokens" else stringResource(R.string.service_unknown),
                                                                        style = MaterialTheme.typography.bodySmall,
                                                                    )
                                                                }
                                                                Column {
                                                                    Text(
                                                                        text = stringResource(R.string.service_capacity),
                                                                        style = MaterialTheme.typography.labelSmall,
                                                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                                    )
                                                                    Text(
                                                                        text = if (capacityTokens != null) "${formatNumber(capacityTokens)} tokens" else stringResource(R.string.service_unknown),
                                                                        style = MaterialTheme.typography.bodySmall,
                                                                    )
                                                                }
                                                            }
                                                            Spacer(modifier = Modifier.height(4.dp))
                                                            val progress = if (usedTokens != null && capacityTokens != null && capacityTokens > 0) {
                                                                val raw = usedTokens.toDouble() / capacityTokens.toDouble() * 100.0
                                                                maxOf(0.0, minOf(100.0, raw))
                                                            } else null
                                                            if (progress != null) {
                                                                LinearProgressIndicator(
                                                                    progress = { (progress / 100.0).toFloat() },
                                                                    modifier = Modifier
                                                                        .fillMaxWidth()
                                                                        .height(8.dp),
                                                                )
                                                                Spacer(modifier = Modifier.height(4.dp))
                                                            }
                                                            Text(
                                                                text = busyLabel,
                                                                style = MaterialTheme.typography.bodySmall,
                                                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                            )
                                                        }

                                                        if (si < slotsArray.length() - 1) {
                                                            Spacer(modifier = Modifier.height(8.dp))
                                                            HorizontalDivider(color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.2f))
                                                            Spacer(modifier = Modifier.height(8.dp))
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        Spacer(modifier = Modifier.height(12.dp))
                                    }

                                    if (!hasLoaded) {
                                        Text(
                                            text = stringResource(R.string.service_no_loaded_model),
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }

                                if (contextError != null) {
                                    Spacer(modifier = Modifier.height(8.dp))
                                    Text(
                                        text = contextError,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.error,
                                    )
                                }
                            }
                        }
                    }
                }

                Spacer(modifier = Modifier.height(32.dp))
            }
        }
    }
}

private fun formatSampleTime(raw: String?): String? {
    if (raw.isNullOrBlank()) return null
    val patterns = listOf(
        "yyyy-MM-dd'T'HH:mm:ss.SSSXXX",
        "yyyy-MM-dd'T'HH:mm:ssXXX",
        "yyyy-MM-dd'T'HH:mm:ss",
        "yyyy-MM-dd HH:mm:ss",
    )
    for (p in patterns) {
        try {
            val parser = SimpleDateFormat(p, Locale.getDefault())
            parser.timeZone = TimeZone.getTimeZone("UTC")
            val date = parser.parse(raw)
            if (date != null) {
                return SimpleDateFormat("MMM d, yyyy HH:mm", Locale.getDefault()).format(date)
            }
        } catch (_: Exception) {
        }
    }
    return raw
}

private fun formatNumber(value: Long): String {
    return String.format(Locale.getDefault(), "%,d", value)
}

private fun JSONObject.stringOrNull(key: String): String? =
    if (has(key) && !isNull(key)) optString(key).takeIf { it.isNotBlank() } else null

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
