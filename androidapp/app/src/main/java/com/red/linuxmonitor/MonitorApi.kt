package com.red.linuxmonitor

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.util.UUID
import java.util.regex.Pattern

internal class MonitorApiException(
    val status: Int?,
    val code: String?,
    message: String,
) : Exception(message)

internal class MonitorApi(serverUrl: String, token: String) {

    private val baseUrl: String
    private val bearerToken: String

    init {
        val uri = try {
            URI(serverUrl)
        } catch (e: Exception) {
            throw IllegalArgumentException("serverUrl must be a valid http(s) URL", e)
        }
        val scheme = uri.scheme?.lowercase() ?: ""
        if (scheme != "http" && scheme != "https") {
            throw IllegalArgumentException("serverUrl scheme must be http or https")
        }
        val host = uri.host
        if (host.isNullOrBlank()) {
            throw IllegalArgumentException("serverUrl must include a host")
        }
        if (uri.userInfo != null) {
            throw IllegalArgumentException("serverUrl must not include userinfo")
        }
        if (uri.query != null) {
            throw IllegalArgumentException("serverUrl must not include a query")
        }
        if (uri.fragment != null) {
            throw IllegalArgumentException("serverUrl must not include a fragment")
        }
        val port = uri.port
        if (port != -1 && (port < 1 || port > 65535)) {
            throw IllegalArgumentException("serverUrl port must be between 1 and 65535")
        }
        val rawAuthority = uri.rawAuthority
        if (rawAuthority != null && rawAuthority.endsWith(":") && port == -1) {
            throw IllegalArgumentException("serverUrl must not include an empty port")
        }
        val path = uri.rawPath.orEmpty()
        val normalizedPath = path.trimEnd('/')
        val authority = if (port == -1) host else "$host:$port"
        baseUrl = "$scheme://$authority$normalizedPath"

        val trimmedToken = token.trim()
        if (trimmedToken.isEmpty() || !trimmedToken.all { it in '\u0021'..'\u007E' }) {
            throw IllegalArgumentException("token must be non-empty visible ASCII")
        }
        bearerToken = trimmedToken
    }

    private fun validateUuid(value: String, field: String) {
        if (!UUID_PATTERN.matcher(value).matches()) {
            throw MonitorApiException(null, "validation_error", "$field must be a valid UUID")
        }
    }

    private fun validatePower(action: String, delaySeconds: Int, confirmation: String) {
        if (action != "reboot" && action != "shutdown") {
            throw MonitorApiException(null, "validation_error", "action must be reboot or shutdown")
        }
        if (delaySeconds < 10 || delaySeconds > 3600) {
            throw MonitorApiException(null, "validation_error", "delaySeconds must be between 10 and 3600")
        }
        if (confirmation != action) {
            throw MonitorApiException(null, "validation_error", "confirmation must exactly equal action")
        }
    }

    suspend fun snapshot(includeContext: Boolean = false): JSONObject {
        val path = if (includeContext) {
            "/api/v1/system?include_llama_context=true"
        } else {
            "/api/v1/system"
        }
        return request("GET", path, READ_TIMEOUT_MS)
    }

    suspend fun probeAdmin(): Boolean {
        val zero = "00000000-0000-0000-0000-000000000000"
        val (status, body) = rawRequest("GET", "/api/v1/jobs/$zero", READ_TIMEOUT_MS)
        if (status == 403) return false
        val (code, message) = parseError(body)
        if (status == 404 && code == "job_not_found") return true
        throw MonitorApiException(status, code ?: "unknown", message ?: "HTTP $status")
    }

    suspend fun checkUpdates(): JSONObject =
        request("POST", "/api/v1/updates/check", READ_TIMEOUT_MS)

    suspend fun applyUpdates(): JSONObject =
        request("POST", "/api/v1/updates/apply", READ_TIMEOUT_MS)

    suspend fun job(id: String): JSONObject {
        validateUuid(id, "id")
        return request("GET", "/api/v1/jobs/$id", READ_TIMEOUT_MS)
    }

    suspend fun schedulePower(action: String, delaySeconds: Int, confirmation: String): JSONObject {
        validatePower(action, delaySeconds, confirmation)
        val body = JSONObject()
            .put("action", action)
            .put("delay_seconds", delaySeconds)
            .put("confirmation", confirmation)
            .toString()
        return request("POST", "/api/v1/power-actions", POWER_READ_TIMEOUT_MS, body)
    }

    suspend fun power(id: String): JSONObject {
        validateUuid(id, "id")
        return request("GET", "/api/v1/power-actions/$id", READ_TIMEOUT_MS)
    }

    suspend fun cancelPower(id: String): JSONObject {
        validateUuid(id, "id")
        return request("DELETE", "/api/v1/power-actions/$id", POWER_READ_TIMEOUT_MS)
    }

    private data class ApiError(val code: String?, val message: String?)

    private fun parseError(body: String): ApiError {
        return try {
            val obj = JSONObject(body)
            val err = obj.optJSONObject("error")
            val codeRaw = err?.optString("code").orEmpty().ifBlank { obj.optString("code") }
            val messageRaw = err?.optString("message").orEmpty().ifBlank { obj.optString("message") }
            ApiError(codeRaw.ifBlank { null }, messageRaw.ifBlank { null })
        } catch (e: JSONException) {
            ApiError(null, null)
        }
    }

    private suspend fun request(
        method: String,
        path: String,
        readTimeoutMs: Int,
        body: String? = null,
    ): JSONObject {
        val (status, text) = rawRequest(method, path, readTimeoutMs, body)
        if (status in 200..299) {
            val json = try {
                JSONObject(text)
            } catch (e: JSONException) {
                throw MonitorApiException(status, null, "Invalid response from server")
            }
            if (path.startsWith("/api/v1/system")) {
                validateSnapshot(json, status)
            }
            return json
        }
        val (code, message) = parseError(text)
        throw MonitorApiException(status, code, message ?: "HTTP $status")
    }

    private fun validateSnapshot(json: JSONObject, status: Int) {
        if (json.isNull("hostname") || !json.has("hostname") || json.optString("hostname").isBlank()) {
            throw MonitorApiException(status, null, "Invalid response from server")
        }
        if (json.isNull("collected_at") || !json.has("collected_at") || json.optString("collected_at").isBlank()) {
            throw MonitorApiException(status, null, "Invalid response from server")
        }
    }

    private suspend fun rawRequest(
        method: String,
        path: String,
        readTimeoutMs: Int,
        body: String? = null,
    ): Pair<Int, String> {
        return withContext(Dispatchers.IO) {
            var connection: HttpURLConnection? = null
            try {
                val url = URL("$baseUrl$path")
                connection = url.openConnection() as HttpURLConnection
                connection.requestMethod = method
                connection.instanceFollowRedirects = false
                connection.connectTimeout = CONNECT_TIMEOUT_MS
                connection.readTimeout = readTimeoutMs
                connection.setRequestProperty("Authorization", "Bearer $bearerToken")
                connection.setRequestProperty("Accept", "application/json")
                val isPost = method.equals("POST", ignoreCase = true)
                if (isPost) {
                    val bytes = body?.toByteArray(Charsets.UTF_8) ?: byteArrayOf()
                    connection.doOutput = true
                    connection.setFixedLengthStreamingMode(bytes.size)
                    connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    connection.outputStream.use { stream ->
                        stream.write(bytes)
                    }
                } else if (body != null) {
                    val bytes = body.toByteArray(Charsets.UTF_8)
                    connection.doOutput = true
                    connection.setFixedLengthStreamingMode(bytes.size)
                    connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    connection.outputStream.use { stream ->
                        stream.write(bytes)
                    }
                }
                val status = connection.responseCode
                val stream = if (status in 200..299) connection.inputStream else connection.errorStream
                val text = stream?.use { it.readBytes().toString(Charsets.UTF_8) }.orEmpty()
                status to text
            } catch (e: IOException) {
                throw MonitorApiException(null, "unknown", "Monitoring server unavailable.")
            } finally {
                connection?.disconnect()
            }
        }
    }

    companion object {
        private const val CONNECT_TIMEOUT_MS = 10_000
        private const val READ_TIMEOUT_MS = 10_000
        private const val POWER_READ_TIMEOUT_MS = 120_000
        private val UUID_PATTERN: Pattern =
            Pattern.compile("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    }
}