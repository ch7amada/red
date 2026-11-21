package com.red.linuxmonitor

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.ShortNavigationBarArrangement
import androidx.compose.material3.ShortNavigationBarItemDefaults
import androidx.compose.material3.NavigationItemIconPosition
import androidx.compose.ui.res.stringResource
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

class MainActivity : ComponentActivity() {
    private enum class Destination(val label: Int) {
        SYSTEM(R.string.nav_system),
        CONTROL(R.string.nav_control)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            LinuxMonitorTheme {
                MonitorApp()
            }
        }
    }

    @Composable
    private fun MonitorApp() {
        var destination by rememberSaveable { mutableStateOf(Destination.SYSTEM) }
        val stateHolder = rememberSaveableStateHolder()

        BackHandler(enabled = destination == Destination.CONTROL) {
            destination = Destination.SYSTEM
        }

        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.surface
        ) {
            Box(
                modifier = Modifier.fillMaxSize().safeDrawingPadding(),
                contentAlignment = Alignment.TopCenter
            ) {
                Column(
                    modifier = Modifier.widthIn(max = 640.dp).fillMaxSize(),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Box(
                        modifier = Modifier.weight(1f).fillMaxWidth()
                    ) {
                        stateHolder.SaveableStateProvider(destination.name) {
                            when (destination) {
                                Destination.SYSTEM -> SystemInfoScreen()
                                Destination.CONTROL -> ControlScreen()
                            }
                        }
                    }
                    DestinationBar(
                        selected = destination,
                        onNavigate = { destination = it },
                        modifier = Modifier
                            .widthIn(max = 420.dp)
                            .padding(horizontal = 20.dp)
                            .padding(top = 8.dp, bottom = 12.dp)
                    )
                }
            }
        }
    }

    @Composable
    private fun DestinationBar(
        selected: Destination,
        onNavigate: (Destination) -> Unit,
        modifier: Modifier
    ) {
        val scheme = MaterialTheme.colorScheme
        val iconPosition = if (LocalDensity.current.fontScale > 1.3f) {
            NavigationItemIconPosition.Top
        } else {
            NavigationItemIconPosition.Start
        }

        ShortNavigationBar(
            modifier = modifier.clip(RoundedCornerShape(36.dp)),
            containerColor = scheme.surfaceVariant,
            contentColor = scheme.onSurfaceVariant,
            arrangement = ShortNavigationBarArrangement.EqualWeight,
            windowInsets = WindowInsets(0, 0, 0, 0)
        ) {
            val itemColors = ShortNavigationBarItemDefaults.colors(
                selectedIconColor = scheme.onPrimary,
                selectedTextColorTopIconPosition = scheme.onSurface,
                selectedTextColorStartIconPosition = scheme.onPrimary,
                selectedIndicatorColor = scheme.primary,
                unselectedIconColor = scheme.onSurfaceVariant,
                unselectedTextColor = scheme.onSurfaceVariant
            )

            Destination.entries.forEach { item ->
                ShortNavigationBarItem(
                    selected = selected == item,
                    onClick = { onNavigate(item) },
                    icon = {
                        Icon(
                            imageVector = if (item == Destination.SYSTEM) {
                                Icons.Outlined.Dashboard
                            } else {
                                Icons.Outlined.Tune
                            },
                            contentDescription = null
                        )
                    },
                    label = {
                        Text(stringResource(item.label))
                    },
                    iconPosition = iconPosition,
                    colors = itemColors
                )
            }
        }
    }
}
