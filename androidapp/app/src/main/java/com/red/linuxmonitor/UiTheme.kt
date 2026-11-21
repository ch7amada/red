package com.red.linuxmonitor

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val LightColors = lightColorScheme(
    primary = Color(0xFFDCC6FF),
    onPrimary = Color(0xFF231635),
    primaryContainer = Color(0xFFF2E9FF),
    onPrimaryContainer = Color(0xFF231635),
    surface = Color(0xFFF7F4FC),
    onSurface = Color(0xFF231635),
    surfaceVariant = Color(0xFFF0EBF7),
    onSurfaceVariant = Color(0xFF665777),
    secondaryContainer = Color(0xFFC2E8CE),
    onSecondaryContainer = Color(0xFF1B3D28),
    background = Color(0xFFF7F4FC),
    onBackground = Color(0xFF231635),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF533580),
    onPrimary = Color(0xFFF3E8FF),
    primaryContainer = Color(0xFF4A2A6E),
    onPrimaryContainer = Color(0xFFF2E9FF),
    surface = Color(0xFF1A0E26),
    onSurface = Color(0xFFF2E9FF),
    surfaceVariant = Color(0xFF2A1A3E),
    onSurfaceVariant = Color(0xFFBDA8D4),
    secondaryContainer = Color(0xFF274937),
    onSecondaryContainer = Color(0xFFD7F6E1),
    background = Color(0xFF1A0E26),
    onBackground = Color(0xFFF2E9FF),
)

@Composable
fun LinuxMonitorTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    MaterialTheme(
        colorScheme = if (dark) DarkColors else LightColors,
        content = content,
    )
}
