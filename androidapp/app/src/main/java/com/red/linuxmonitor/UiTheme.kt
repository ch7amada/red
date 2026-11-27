package com.red.linuxmonitor

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val LightColors = lightColorScheme(
    primary = Color(0xFFAD1C33),
    onPrimary = Color(0xFFFFF6F5),
    primaryContainer = Color(0xFFFFDAD8),
    onPrimaryContainer = Color(0xFF40121B),
    surface = Color(0xFFFFF6F3),
    onSurface = Color(0xFF321B20),
    surfaceVariant = Color(0xFFF7E8E5),
    onSurfaceVariant = Color(0xFF754A50),
    secondaryContainer = Color(0xFFC2E8CE),
    onSecondaryContainer = Color(0xFF1B3D28),
    background = Color(0xFFFFF6F3),
    onBackground = Color(0xFF321B20),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFF8758B),
    onPrimary = Color(0xFF2C0912),
    primaryContainer = Color(0xFF5E1725),
    onPrimaryContainer = Color(0xFFFFDAD8),
    surface = Color(0xFF211315),
    onSurface = Color(0xFFF9E8E7),
    surfaceVariant = Color(0xFF352225),
    onSurfaceVariant = Color(0xFFDDB9BC),
    secondaryContainer = Color(0xFF274937),
    onSecondaryContainer = Color(0xFFD7F6E1),
    background = Color(0xFF211315),
    onBackground = Color(0xFFF9E8E7),
)

@Composable
fun LinuxMonitorTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    MaterialTheme(
        colorScheme = if (dark) DarkColors else LightColors,
        content = content,
    )
}
