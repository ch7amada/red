package com.red.linuxmonitor

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.UUID

enum class MonitorRole { UNKNOWN, READER, ADMIN }

data class MonitorState(
    val isConnected: Boolean = false,
    val connecting: Boolean = false,
    val connectionError: String? = null,
    val snapshot: JSONObject? = null,
    val snapshotLoading: Boolean = false,
    val snapshotError: String? = null,
    val context: JSONObject? = null,
    val contextLoading: Boolean = false,
    val contextError: String? = null,
    val role: MonitorRole = MonitorRole.UNKNOWN,
    val roleLoading: Boolean = false,
    val roleError: String? = null,
    val job: JSONObject? = null,
    val jobBusy: Boolean = false,
    val jobError: String? = null,
    val power: JSONObject? = null,
    val powerBusy: Boolean = false,
    val powerError: String? = null,
)

class MonitorViewModel : ViewModel() {

    private val _state = mutableStateOf(MonitorState())
    var state: MonitorState by _state
        private set

    private data class Session(
        val api: MonitorApi,
        val scope: CoroutineScope,
        var jobRevision: Long = 0,
        var powerRevision: Long = 0,
    )

    private var currentSession: Session? = null
    private var requestCounter: Long = 0
    private var snapshotReq: Long = 0
    private var contextReq: Long = 0
    private var roleReq: Long = 0
    private var jobReq: Long = 0
    private var powerReq: Long = 0

    private val jobTerminals = setOf("succeeded", "failed", "interrupted")
    private val powerTerminals = setOf("cancelled", "failed", "unknown", "completed")

    fun connect(serverUrl: String, token: String) {
        if (state.isConnected || state.connecting) return
        val url = serverUrl.trim()
        val tok = token.trim()
        if (url.isBlank() || tok.isBlank()) {
            state = MonitorState(connectionError = "Server URL and token are required.")
            return
        }
        val api = try {
            MonitorApi(url, tok)
        } catch (e: IllegalArgumentException) {
            state = MonitorState(connectionError = e.message ?: "Invalid server URL or token.")
            return
        }
        disconnect()
        val scope = CoroutineScope(SupervisorJob(viewModelScope.coroutineContext[Job]) + Dispatchers.Main.immediate)
        val session = Session(api, scope)
        currentSession = session
        state = MonitorState(connecting = true)
        session.scope.launch {
            try {
                val snap = session.api.snapshot(false)
                if (!isActiveSession(session)) return@launch
                state = state.copy(
                    isConnected = true,
                    connecting = false,
                    snapshot = snap,
                    snapshotError = null,
                    connectionError = null,
                )
                fetchRole(session)
            } catch (e: CancellationException) {
                throw e
            } catch (e: MonitorApiException) {
                if (!isActiveSession(session)) return@launch
                val msg = e.message ?: "Monitoring server unavailable."
                if (e.status == 401 || e.status == 403) {
                    disconnectSession(session, auth = true, message = msg)
                } else if (currentSession === session) {
                    currentSession = null
                    session.scope.cancel()
                    state = MonitorState(connecting = false, connectionError = msg)
                }
            } catch (e: Exception) {
                if (!isActiveSession(session)) return@launch
                val msg = e.message ?: "Monitoring server unavailable."
                if (currentSession === session) {
                    currentSession = null
                    session.scope.cancel()
                    state = MonitorState(connecting = false, connectionError = msg)
                }
            }
        }
    }

    fun disconnect() {
        val session = currentSession
        currentSession = null
        session?.scope?.cancel()
        state = MonitorState()
    }

    fun refreshSnapshot() {
        val session = currentSession ?: return
        if (!state.isConnected || state.snapshotLoading) return
        session.scope.launch { fetchSnapshot(session, false) }
    }

    fun refreshContext() {
        val session = currentSession ?: return
        if (!state.isConnected || state.contextLoading) return
        session.scope.launch { fetchSnapshot(session, true) }
    }

    fun refreshRole() {
        val session = currentSession ?: return
        if (!state.isConnected || state.roleLoading) return
        session.scope.launch { fetchRole(session) }
    }

    fun checkUpdates() {
        val session = currentSession ?: return
        if (!(state.isConnected && state.role == MonitorRole.ADMIN)) return
        if (state.jobBusy) return
        launchJobMutation(session) { it.checkUpdates() }
    }

    fun applyUpdates(confirmed: Boolean) {
        if (!confirmed) {
            state = state.copy(jobError = "Confirmation required: check the box to install updates.")
            return
        }
        val session = currentSession ?: return
        if (!(state.isConnected && state.role == MonitorRole.ADMIN)) return
        if (state.jobBusy) return
        launchJobMutation(session) { it.applyUpdates() }
    }

    fun schedulePower(action: String, delaySeconds: Int, confirmation: String) {
        val act = action.trim().lowercase()
        if (act !in setOf("reboot", "shutdown")) {
            state = state.copy(powerError = "Invalid power action.")
            return
        }
        if (delaySeconds < 10 || delaySeconds > 3600) {
            state = state.copy(powerError = "Delay must be between 10 and 3600 seconds.")
            return
        }
        if (confirmation.trim() != act) {
            state = state.copy(powerError = "Confirmation must exactly match the action.")
            return
        }
        val session = currentSession ?: return
        if (!(state.isConnected && state.role == MonitorRole.ADMIN)) return
        if (state.powerBusy) return
        val current = state.power
        if (current != null && !isTerminalPower(current)) {
            state = state.copy(powerError = "A power action is already pending.")
            return
        }
        session.powerRevision++
        val revision = session.powerRevision
        state = state.copy(powerBusy = true, powerError = null)
        session.scope.launch {
            try {
                val result = session.api.schedulePower(act, delaySeconds, confirmation.trim())
                if (!isActiveSession(session)) return@launch
                if (revision != session.powerRevision) return@launch
                if (!validPowerResult(result)) {
                    state = state.copy(powerBusy = false, powerError = "Invalid response from server.")
                    return@launch
                }
                state = state.copy(power = result, powerBusy = false, powerError = null)
            } catch (e: CancellationException) {
                throw e
            } catch (e: MonitorApiException) {
                if (!isActiveSession(session)) return@launch
                if (revision != session.powerRevision) return@launch
                handleControlFailure(session, e) { msg ->
                    state = state.copy(powerBusy = false, powerError = msg)
                }
            } catch (e: Exception) {
                if (!isActiveSession(session)) return@launch
                if (revision != session.powerRevision) return@launch
                state = state.copy(powerBusy = false, powerError = e.message ?: "Power action failed.")
            }
        }
    }

    fun cancelPower(id: String) {
        if (!isValidUuid(id)) {
            state = state.copy(powerError = "Invalid power action id.")
            return
        }
        val session = currentSession ?: return
        if (!(state.isConnected && state.role == MonitorRole.ADMIN)) return
        if (state.powerBusy) return
        val current = state.power
        if (current == null || current.optString("id") != id) {
            state = state.copy(powerError = "Not the tracked power action.")
            return
        }
        if (!current.optBoolean("cancellable", false)) {
            state = state.copy(powerError = "Action is no longer cancellable.")
            return
        }
        if (isTerminalPower(current)) {
            state = state.copy(powerError = "Power action already finished.")
            return
        }
        session.powerRevision++
        val revision = session.powerRevision
        state = state.copy(powerBusy = true, powerError = null)
        session.scope.launch {
            try {
                val result = session.api.cancelPower(id)
                if (!isActiveSession(session)) return@launch
                if (revision != session.powerRevision) return@launch
                if (!validPowerResult(result, id)) {
                    state = state.copy(powerBusy = false, powerError = "Invalid response from server.")
                    return@launch
                }
                state = state.copy(power = result, powerBusy = false, powerError = null)
            } catch (e: CancellationException) {
                throw e
            } catch (e: MonitorApiException) {
                if (!isActiveSession(session)) return@launch
                if (revision != session.powerRevision) return@launch
                when (e.status) {
                    401 -> disconnectSession(session, auth = true, message = e.message ?: "Unauthorized.")
                    403 -> {
                        demoteToReader(session)
                        state = state.copy(
                            powerBusy = false,
                            powerError = e.message ?: "Admin token required.",
                        )
                    }
                    404 -> {
                        if (state.power?.optString("id") == id) {
                            state = state.copy(power = null, powerBusy = false, powerError = e.message ?: "Power action not found.")
                        } else {
                            state = state.copy(powerBusy = false, powerError = e.message ?: "Power action not found.")
                        }
                    }
                    else -> state = state.copy(powerBusy = false, powerError = e.message ?: "Cancel failed.")
                }
            } catch (e: Exception) {
                if (!isActiveSession(session)) return@launch
                if (revision != session.powerRevision) return@launch
                state = state.copy(powerBusy = false, powerError = e.message ?: "Cancel failed.")
            }
        }
    }

    suspend fun pollWhileForeground() {
        coroutineScope {
            launch { snapshotPollLoop() }
            launch { jobPollLoop() }
            launch { powerPollLoop() }
        }
    }

    private suspend fun snapshotPollLoop() {
        while (currentCoroutineContext().isActive) {
            delay(5000)
            if (!currentCoroutineContext().isActive) break
            val session = currentSession ?: continue
            if (!state.isConnected) continue
            if (state.snapshotLoading) continue
            fetchSnapshot(session, false)
        }
    }

    private suspend fun jobPollLoop() {
        while (currentCoroutineContext().isActive) {
            delay(2000)
            if (!currentCoroutineContext().isActive) break
            val session = currentSession ?: continue
            if (!state.isConnected || state.role != MonitorRole.ADMIN) continue
            val current = state.job ?: continue
            val id = current.optString("id")
            if (!isValidUuid(id)) continue
            if (isTerminalJob(current)) continue
            if (state.jobBusy) continue
            val revision = session.jobRevision
            fetchJob(session, id, revision)
        }
    }

    private suspend fun powerPollLoop() {
        while (currentCoroutineContext().isActive) {
            delay(2000)
            if (!currentCoroutineContext().isActive) break
            val session = currentSession ?: continue
            if (!state.isConnected || state.role != MonitorRole.ADMIN) continue
            val current = state.power ?: continue
            val id = current.optString("id")
            if (!isValidUuid(id)) continue
            if (isTerminalPower(current)) continue
            if (state.powerBusy) continue
            val revision = session.powerRevision
            fetchPower(session, id, revision)
        }
    }

    private suspend fun fetchSnapshot(session: Session, forContext: Boolean) {
        if (!isActiveSession(session)) return
        if (forContext) {
            if (state.contextLoading) return
            state = state.copy(contextLoading = true, contextError = null)
        } else {
            if (state.snapshotLoading) return
            state = state.copy(snapshotLoading = true, snapshotError = null)
        }
        val reqId = ++requestCounter
        if (forContext) contextReq = reqId else snapshotReq = reqId
        try {
            val result = session.api.snapshot(forContext)
            if (!isActiveSession(session)) return
            val latest = if (forContext) contextReq else snapshotReq
            if (reqId != latest) return
            if (forContext) {
                state = state.copy(context = result, contextError = null)
            } else {
                state = state.copy(snapshot = result, snapshotError = null, isConnected = true)
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: MonitorApiException) {
            if (!isActiveSession(session)) return
            val latest = if (forContext) contextReq else snapshotReq
            if (reqId != latest) return
            if (e.status == 401 || e.status == 403) {
                disconnectSession(session, auth = true, message = e.message ?: "Unauthorized.")
            } else {
                val msg = e.message ?: "Monitoring server unavailable."
                if (forContext) {
                    state = state.copy(contextError = msg)
                } else {
                    state = state.copy(snapshotError = msg)
                }
            }
        } catch (e: Exception) {
            if (!isActiveSession(session)) return
            val latest = if (forContext) contextReq else snapshotReq
            if (reqId != latest) return
            val msg = e.message ?: "Monitoring server unavailable."
            if (forContext) {
                state = state.copy(contextError = msg)
            } else {
                state = state.copy(snapshotError = msg)
            }
        } finally {
            if (isActiveSession(session)) {
                val latest = if (forContext) contextReq else snapshotReq
                if (reqId == latest) {
                    if (forContext) {
                        state = state.copy(contextLoading = false)
                    } else {
                        state = state.copy(snapshotLoading = false)
                    }
                }
            }
        }
    }

    private suspend fun fetchRole(session: Session) {
        if (!isActiveSession(session)) return
        val reqId = ++requestCounter
        roleReq = reqId
        state = state.copy(roleLoading = true)
        try {
            val isAdmin = session.api.probeAdmin()
            if (!isActiveSession(session) || reqId != roleReq) return
            if (isAdmin) {
                state = state.copy(role = MonitorRole.ADMIN, roleError = null)
            } else {
                demoteToReader(session)
                state = state.copy(roleError = null)
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: MonitorApiException) {
            if (!isActiveSession(session) || reqId != roleReq) return
            when (e.status) {
                401 -> disconnectSession(session, auth = true, message = e.message ?: "Unauthorized.")
                403 -> {
                    demoteToReader(session)
                    state = state.copy(roleError = null)
                }
                else -> state = state.copy(roleError = e.message ?: "Role unavailable.")
            }
        } catch (e: Exception) {
            if (!isActiveSession(session) || reqId != roleReq) return
            state = state.copy(roleError = e.message ?: "Role unavailable.")
        } finally {
            if (isActiveSession(session) && reqId == roleReq) {
                state = state.copy(roleLoading = false)
            }
        }
    }

    private suspend fun fetchJob(session: Session, id: String, revision: Long) {
        if (!isActiveSession(session)) return
        if (!isValidUuid(id)) return
        val reqId = ++requestCounter
        jobReq = reqId
        try {
            val result = session.api.job(id)
            if (!isActiveSession(session)) return
            if (reqId != jobReq) return
            if (revision != session.jobRevision) return
            if (id != state.job?.optString("id")) return
            if (state.jobBusy) return
            if (!validJobResult(result, id)) {
                state = state.copy(jobError = "Invalid response from server.")
                return
            }
            state = state.copy(job = result, jobError = null)
        } catch (e: CancellationException) {
            throw e
        } catch (e: MonitorApiException) {
            if (!isActiveSession(session)) return
            if (reqId != jobReq) return
            if (revision != session.jobRevision) return
            if (id != state.job?.optString("id")) return
            when (e.status) {
                401 -> disconnectSession(session, auth = true, message = e.message ?: "Unauthorized.")
                403 -> {
                    demoteToReader(session)
                    state = state.copy(jobError = null, powerError = null)
                }
                404 -> {
                    if (state.job?.optString("id") == id) {
                        state = state.copy(job = null, jobError = e.message ?: "Operation not found.")
                    } else {
                        state = state.copy(jobError = e.message ?: "Operation not found.")
                    }
                }
                else -> state = state.copy(jobError = e.message ?: "Operation unavailable.")
            }
        } catch (e: Exception) {
            if (!isActiveSession(session)) return
            if (reqId != jobReq) return
            if (revision != session.jobRevision) return
            if (id != state.job?.optString("id")) return
            state = state.copy(jobError = e.message ?: "Operation unavailable.")
        }
    }

    private suspend fun fetchPower(session: Session, id: String, revision: Long) {
        if (!isActiveSession(session)) return
        if (!isValidUuid(id)) return
        val reqId = ++requestCounter
        powerReq = reqId
        try {
            val result = session.api.power(id)
            if (!isActiveSession(session)) return
            if (reqId != powerReq) return
            if (revision != session.powerRevision) return
            if (id != state.power?.optString("id")) return
            if (state.powerBusy) return
            if (!validPowerResult(result, id)) {
                state = state.copy(powerError = "Invalid response from server.")
                return
            }
            state = state.copy(power = result, powerError = null)
        } catch (e: CancellationException) {
            throw e
        } catch (e: MonitorApiException) {
            if (!isActiveSession(session)) return
            if (reqId != powerReq) return
            if (revision != session.powerRevision) return
            if (id != state.power?.optString("id")) return
            when (e.status) {
                401 -> disconnectSession(session, auth = true, message = e.message ?: "Unauthorized.")
                403 -> {
                    demoteToReader(session)
                    state = state.copy(jobError = null, powerError = null)
                }
                404 -> {
                    if (state.power?.optString("id") == id) {
                        state = state.copy(power = null, powerError = e.message ?: "Power action not found.")
                    } else {
                        state = state.copy(powerError = e.message ?: "Power action not found.")
                    }
                }
                else -> state = state.copy(powerError = e.message ?: "Power action unavailable.")
            }
        } catch (e: Exception) {
            if (!isActiveSession(session)) return
            if (reqId != powerReq) return
            if (revision != session.powerRevision) return
            if (id != state.power?.optString("id")) return
            state = state.copy(powerError = e.message ?: "Power action unavailable.")
        }
    }

    private fun launchJobMutation(session: Session, call: suspend (MonitorApi) -> JSONObject) {
        session.jobRevision++
        val revision = session.jobRevision
        state = state.copy(jobBusy = true, jobError = null)
        session.scope.launch {
            try {
                val result = call(session.api)
                if (!isActiveSession(session)) return@launch
                if (revision != session.jobRevision) return@launch
                if (!validJobResult(result)) {
                    state = state.copy(jobBusy = false, jobError = "Invalid response from server.")
                    return@launch
                }
                state = state.copy(job = result, jobBusy = false, jobError = null)
            } catch (e: CancellationException) {
                throw e
            } catch (e: MonitorApiException) {
                if (!isActiveSession(session)) return@launch
                if (revision != session.jobRevision) return@launch
                if (e.status == 401) {
                    disconnectSession(session, auth = true, message = e.message ?: "Unauthorized.")
                } else if (e.status == 403) {
                    demoteToReader(session)
                    state = state.copy(
                        jobBusy = false,
                        powerBusy = false,
                        jobError = e.message ?: "Admin token required.",
                        powerError = null,
                    )
                } else {
                    state = state.copy(jobBusy = false, jobError = e.message ?: "Request failed.")
                }
            } catch (e: Exception) {
                if (!isActiveSession(session)) return@launch
                if (revision != session.jobRevision) return@launch
                state = state.copy(jobBusy = false, jobError = e.message ?: "Request failed.")
            }
        }
    }

    private fun handleControlFailure(session: Session, e: MonitorApiException, update: (String) -> Unit) {
        if (!isActiveSession(session)) return
        when (e.status) {
            401 -> disconnectSession(session, auth = true, message = e.message ?: "Unauthorized.")
            403 -> {
                demoteToReader(session)
                update(e.message ?: "Admin token required.")
            }
            else -> update(e.message ?: "Request failed.")
        }
    }

    private fun demoteToReader(session: Session) {
        if (currentSession !== session) return
        session.jobRevision++
        session.powerRevision++
        roleReq = ++requestCounter
        state = state.copy(
            role = MonitorRole.READER,
            roleLoading = false,
            roleError = null,
            job = null,
            power = null,
            jobBusy = false,
            powerBusy = false,
            jobError = null,
            powerError = null,
        )
    }

    private fun disconnectSession(session: Session, auth: Boolean, message: String?) {
        if (currentSession !== session) return
        currentSession = null
        session.scope.cancel()
        state = if (auth) {
            MonitorState(connectionError = message ?: "Unauthorized.")
        } else {
            MonitorState()
        }
    }

    private fun isActiveSession(session: Session): Boolean {
        return currentSession === session && session.scope.isActive
    }

    private fun validJobResult(result: JSONObject, expectedId: String? = null): Boolean =
        validOperationResult(result, expectedId)

    private fun validPowerResult(result: JSONObject, expectedId: String? = null): Boolean =
        validOperationResult(result, expectedId)

    private fun validOperationResult(result: JSONObject, expectedId: String? = null): Boolean {
        val id = result.optString("id")
        return isValidUuid(id) && result.optString("status").isNotBlank() && (expectedId == null || id == expectedId)
    }

    private fun isTerminalJob(j: JSONObject): Boolean {
        return j.optString("status") in jobTerminals
    }

    private fun isTerminalPower(p: JSONObject): Boolean {
        return p.optString("status") in powerTerminals
    }

    private fun isValidUuid(value: String): Boolean {
        return value.matches(Regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"))
    }
}