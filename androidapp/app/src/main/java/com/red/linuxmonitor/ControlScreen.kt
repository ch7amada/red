package com.red.linuxmonitor

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material.icons.outlined.PowerSettingsNew
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.SystemUpdateAlt
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

@Composable
internal fun ControlScreen(
    state: MonitorState,
    onRefreshRole: () -> Unit,
    onCheckUpdates: () -> Unit,
    onApplyUpdates: (Boolean) -> Unit,
    onSchedulePower: (String, Int, String) -> Unit,
    onCancelPower: (String) -> Unit,
    onDisconnect: () -> Unit,
) {
    var confirmApply by rememberSaveable { mutableStateOf(false) }
    var showApplyDialog by remember { mutableStateOf(false) }

    var powerAction by rememberSaveable { mutableStateOf("reboot") }
    var powerDelay by rememberSaveable { mutableStateOf("60") }
    var powerConfirmation by rememberSaveable { mutableStateOf("") }

    val delayValue = powerDelay.toIntOrNull()
    val delayValid = delayValue != null && delayValue in 10..3600
    val confirmationValid = powerConfirmation == powerAction

    val snapshot = state.snapshot
    val hostName = snapshot?.optString("hostname")?.takeIf { it.isNotBlank() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp),
    ) {
        Spacer(modifier = Modifier.height(28.dp))

        ConnectedScreenHeader(
            title = stringResource(R.string.control_title),
            onDisconnect = onDisconnect,
        )

        if (hostName != null) {
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = hostName,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Spacer(modifier = Modifier.height(16.dp))

        // Role feedback near the header
        if (state.roleLoading) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(
                    modifier = Modifier
                        .size(18.dp)
                        .semantics { liveRegion = LiveRegionMode.Polite },
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = stringResource(R.string.control_role_loading),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(modifier = Modifier.height(12.dp))
        } else if (state.roleError != null) {
            Text(
                text = state.roleError ?: stringResource(R.string.control_role_error),
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
            )
            Spacer(modifier = Modifier.height(8.dp))
            OutlinedButton(onClick = onRefreshRole) {
                Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(modifier = Modifier.width(4.dp))
                Text(stringResource(R.string.control_role_retry))
            }
            Spacer(modifier = Modifier.height(12.dp))
        } else {
            when (state.role) {
                MonitorRole.READER -> {
                    Surface(
                        shape = RoundedCornerShape(16.dp),
                        color = MaterialTheme.colorScheme.surfaceVariant,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text(
                                text = stringResource(R.string.control_role_reader_title),
                                style = MaterialTheme.typography.titleSmall,
                                modifier = Modifier.semantics { heading() },
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = stringResource(R.string.control_role_reader_message),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(12.dp))
                }
                MonitorRole.UNKNOWN -> {
                    Surface(
                        shape = RoundedCornerShape(16.dp),
                        color = MaterialTheme.colorScheme.errorContainer,
                        contentColor = MaterialTheme.colorScheme.onErrorContainer,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text(
                                text = stringResource(R.string.control_role_unknown_title),
                                style = MaterialTheme.typography.titleSmall,
                                modifier = Modifier.semantics { heading() },
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = stringResource(R.string.control_role_unknown_message),
                                style = MaterialTheme.typography.bodySmall,
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            OutlinedButton(onClick = onRefreshRole) {
                                Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text(stringResource(R.string.control_role_retry))
                            }
                        }
                    }
                    Spacer(modifier = Modifier.height(12.dp))
                }
                else -> Unit
            }
        }

        // Dominant updates card
        Surface(
            shape = RoundedCornerShape(32.dp),
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
                        imageVector = Icons.Outlined.SystemUpdateAlt,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Text(
                        text = stringResource(R.string.control_updates_title),
                        style = MaterialTheme.typography.headlineSmall,
                        modifier = Modifier.semantics { heading() },
                    )
                }

                Spacer(modifier = Modifier.height(16.dp))

                JobStatusBlock(job = state.job, jobError = state.jobError, jobBusy = state.jobBusy)

                if (state.role == MonitorRole.ADMIN) {
                    Spacer(modifier = Modifier.height(16.dp))

                    Button(
                        onClick = onCheckUpdates,
                        enabled = !state.jobBusy && !state.powerBusy,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = MaterialTheme.colorScheme.onPrimary,
                            contentColor = MaterialTheme.colorScheme.primary,
                        ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 2.dp),
                    ) {
                        if (state.jobBusy) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                color = MaterialTheme.colorScheme.primary,
                                strokeWidth = 2.dp,
                            )
                        } else {
                            Text(text = stringResource(R.string.control_updates_button_check))
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    Button(
                        onClick = {
                            confirmApply = false
                            showApplyDialog = true
                        },
                        enabled = !state.jobBusy && !state.powerBusy,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = MaterialTheme.colorScheme.onPrimary,
                            contentColor = MaterialTheme.colorScheme.primary,
                        ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 2.dp),
                    ) {
                        Text(text = stringResource(R.string.control_updates_button_install))
                    }
                }
            }
        }

        if (showApplyDialog) {
            AlertDialog(
                onDismissRequest = {
                    showApplyDialog = false
                    confirmApply = false
                },
                title = { Text(stringResource(R.string.control_confirm_update_title)) },
                text = {
                    Column {
                        Text(
                            text = stringResource(
                                R.string.control_confirm_update_message,
                                hostName ?: "this server",
                            ),
                        )
                        Spacer(modifier = Modifier.height(12.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(
                                checked = confirmApply,
                                onCheckedChange = { confirmApply = it },
                                enabled = !state.jobBusy,
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(
                                text = stringResource(R.string.control_updates_checkbox_confirm),
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                },
                dismissButton = {
                    TextButton(onClick = {
                        showApplyDialog = false
                        confirmApply = false
                    }) {
                        Text(stringResource(R.string.control_dialog_cancel))
                    }
                },
                confirmButton = {
                    Button(
                        onClick = {
                            onApplyUpdates(confirmApply)
                            showApplyDialog = false
                            confirmApply = false
                        },
                        enabled = confirmApply && !state.jobBusy && !state.powerBusy,
                    ) {
                        Text(text = stringResource(R.string.control_updates_button_install))
                    }
                },
            )
        }

        Spacer(modifier = Modifier.height(24.dp))

        // Quieter power card
        Surface(
            shape = RoundedCornerShape(24.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
            contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Icon(
                        imageVector = Icons.Outlined.PowerSettingsNew,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Text(
                        text = stringResource(R.string.control_power_title),
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.semantics { heading() },
                    )
                }

                Spacer(modifier = Modifier.height(12.dp))

                PowerStatusBlock(
                    power = state.power,
                    powerError = state.powerError,
                    powerBusy = state.powerBusy,
                    isAdmin = state.role == MonitorRole.ADMIN,
                    onCancelPower = onCancelPower,
                )

                if (state.role == MonitorRole.ADMIN) {
                    Spacer(modifier = Modifier.height(12.dp))

                    Text(
                        text = stringResource(R.string.control_power_action_label),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(modifier = Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(
                            selected = powerAction == "reboot",
                            onClick = { powerAction = "reboot"; powerConfirmation = "" },
                            label = { Text(stringResource(R.string.control_power_action_reboot)) },
                        )
                        FilterChip(
                            selected = powerAction == "shutdown",
                            onClick = { powerAction = "shutdown"; powerConfirmation = "" },
                            label = { Text(stringResource(R.string.control_power_action_shutdown)) },
                        )
                    }

                    Spacer(modifier = Modifier.height(12.dp))

                    OutlinedTextField(
                        value = powerDelay,
                        onValueChange = { powerDelay = it },
                        label = { Text(stringResource(R.string.control_power_delay_label)) },
                        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                            keyboardType = KeyboardType.Number,
                        ),
                        isError = !delayValid && powerDelay.isNotEmpty(),
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )

                    Spacer(modifier = Modifier.height(8.dp))

                    OutlinedTextField(
                        value = powerConfirmation,
                        onValueChange = { powerConfirmation = it },
                        label = { Text(stringResource(R.string.control_power_confirm_label)) },
                        supportingText = {
                            Text(stringResource(R.string.control_power_confirm_support, powerAction))
                        },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        isError = powerConfirmation.isNotEmpty() && !confirmationValid,
                    )

                    Spacer(modifier = Modifier.height(12.dp))

                    Button(
                        onClick = {
                            val delay = delayValue
                            if (delay != null && delayValid && confirmationValid) {
                                onSchedulePower(powerAction, delay, powerConfirmation)
                                powerConfirmation = ""
                            }
                        },
                        enabled = delayValid && confirmationValid && !state.powerBusy && !state.jobBusy,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        if (state.powerBusy) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp,
                            )
                        } else {
                            Text(text = stringResource(R.string.control_power_schedule))
                        }
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(32.dp))
    }
}

@Composable
private fun JobStatusBlock(job: JSONObject?, jobError: String?, jobBusy: Boolean) {
    if (jobBusy) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(
                modifier = Modifier.size(16.dp),
                color = MaterialTheme.colorScheme.onPrimary,
                strokeWidth = 2.dp,
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = stringResource(R.string.control_loading),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onPrimary,
            )
        }
        Spacer(modifier = Modifier.height(8.dp))
    }
    if (jobError != null) {
        Text(
            text = jobError,
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        )
        Spacer(modifier = Modifier.height(8.dp))
    }
    if (job == null) {
        Text(
            text = stringResource(R.string.control_updates_no_job),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.85f),
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        )
        return
    }

    val status = job.optString("status", "")
    val kind = job.optString("kind")
    val result = job.optJSONObject("result")
    val statusText = when {
        status == "succeeded" && kind == "update_check" -> {
            val count = result?.optInt("count", -1) ?: -1
            if (count >= 0) {
                pluralStringResource(R.plurals.control_updates_count, count, count)
            } else {
                stringResource(R.string.control_updates_check_success)
            }
        }
        status == "succeeded" && kind == "update_apply" ->
            stringResource(R.string.control_updates_successful)
        else ->
            "${stringResource(R.string.control_updates_status_label)}: $status"
    }
    Text(
        text = statusText,
        style = MaterialTheme.typography.bodyMedium,
        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
    )
    val errorCode = if (job.isNull("error_code")) "" else job.optString("error_code")
    val errorMessage = if (job.isNull("error_message")) "" else job.optString("error_message")
    if (errorCode.isNotEmpty() || errorMessage.isNotEmpty()) {
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = listOf(errorCode, errorMessage).filter { it.isNotEmpty() }.joinToString(" "),
            color = MaterialTheme.colorScheme.errorContainer,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        )
    }
}

@Composable
private fun PowerStatusBlock(
    power: JSONObject?,
    powerError: String?,
    powerBusy: Boolean,
    isAdmin: Boolean,
    onCancelPower: (String) -> Unit,
) {
    if (powerBusy) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(
                modifier = Modifier.size(16.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                strokeWidth = 2.dp,
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = stringResource(R.string.control_loading),
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Spacer(modifier = Modifier.height(8.dp))
    }
    if (powerError != null) {
        Text(
            text = powerError,
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        )
        Spacer(modifier = Modifier.height(8.dp))
    }
    if (power == null) {
        Text(
            text = stringResource(R.string.control_power_no_action),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        )
        return
    }

    val action = power.optString("action", "")
    val status = power.optString("status", "")
    Text(
        text = "${stringResource(R.string.control_power_action_label)}: $action",
        style = MaterialTheme.typography.bodyMedium,
    )
    Text(
        text = "${stringResource(R.string.control_power_status_label)}: $status",
        style = MaterialTheme.typography.bodyMedium,
        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
    )

    val scheduledFor = if (power.isNull("scheduled_for")) "" else power.optString("scheduled_for")
    if (scheduledFor.isNotEmpty()) {
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = "${stringResource(R.string.control_power_scheduled_for)}: ${formatScheduledFor(scheduledFor)}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }

    val cancellable = power.optBoolean("cancellable", false)
    val terminal = status in setOf("cancelled", "failed", "completed", "unknown")
    if (!cancellable && !terminal) {
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = stringResource(R.string.control_power_cancelled_window_closed),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }

    val errorCode = if (power.isNull("error_code")) "" else power.optString("error_code")
    val errorMessage = if (power.isNull("error_message")) "" else power.optString("error_message")
    if (errorCode.isNotEmpty() || errorMessage.isNotEmpty()) {
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = listOf(errorCode, errorMessage).filter { it.isNotEmpty() }.joinToString(" "),
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        )
    }

    if (cancellable && isAdmin) {
        Spacer(modifier = Modifier.height(8.dp))
        OutlinedButton(
            onClick = { onCancelPower(power.optString("id")) },
            enabled = !powerBusy,
        ) {
            Text(stringResource(R.string.control_power_cancel))
        }
    }
}

private fun formatScheduledFor(raw: String): String {
    if (raw.isBlank()) return raw
    val normalized = raw.trim()
        .replace(Regex("\\.\\d+"), "")
        .replace("Z", "+00:00")
    val patterns = listOf(
        "yyyy-MM-dd'T'HH:mm:ssXXX",
        "yyyy-MM-dd'T'HH:mm:ssX",
        "yyyy-MM-dd'T'HH:mm:ss",
    )
    for (pattern in patterns) {
        try {
            val parser = SimpleDateFormat(pattern, Locale.getDefault())
            parser.timeZone = TimeZone.getTimeZone("UTC")
            val date = parser.parse(normalized)
            if (date != null) {
                val formatter = SimpleDateFormat("MMM d, yyyy HH:mm", Locale.getDefault())
                return formatter.format(date)
            }
        } catch (_: Exception) {
        }
    }
    return raw
}