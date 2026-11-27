package com.red.linuxmonitor

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Apps
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.material.icons.outlined.DeveloperBoard
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalConfiguration

import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.ViewModelProvider

class MainActivity : ComponentActivity() {
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
        val viewModel = ViewModelProvider(this@MainActivity)[MonitorViewModel::class.java]
        val state = viewModel.state

        val isConnected = state.isConnected

        var destination by rememberSaveable { mutableStateOf(Destination.SYSTEM) }
        var session by rememberSaveable { mutableStateOf(0) }
        var llamaContextRequested by rememberSaveable { mutableStateOf(false) }
        val stateHolder = rememberSaveableStateHolder()

        LaunchedEffect(isConnected) {
            if (!isConnected) {
                destination = Destination.SYSTEM
                session += 1
                llamaContextRequested = false
            }
        }

        LaunchedEffect(viewModel, isConnected) {
            if (!isConnected) return@LaunchedEffect
            this@MainActivity.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.pollWhileForeground()
            }
        }

        LaunchedEffect(destination) {
            if (isConnected && destination == Destination.CONTROL) {
                viewModel.refreshRole()
            }
        }

        LaunchedEffect(destination, llamaContextRequested, isConnected) {
            if (isConnected && destination == Destination.LLAMA && !llamaContextRequested) {
                llamaContextRequested = true
                viewModel.refreshContext()
            }
        }

        BackHandler(enabled = isConnected && destination != Destination.SYSTEM) {
            destination = Destination.SYSTEM
        }

        if (!isConnected) {
            ConnectScreen(
                state = state,
                onConnect = { url, token -> viewModel.connect(url, token) },
            )
            return
        }

        val useRail = LocalConfiguration.current.screenWidthDp >= 600

        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.surface,
        ) {
            Box(
                modifier = Modifier.fillMaxSize().safeDrawingPadding(),
                contentAlignment = Alignment.TopCenter,
            ) {
                Column(
                    modifier = Modifier.widthIn(max = 640.dp).fillMaxSize(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    val disconnect = { viewModel.disconnect() }
                    val railWidth = if (LocalConfiguration.current.fontScale > 1.3f) 120.dp else 88.dp

                    if (useRail) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 8.dp),
                            horizontalArrangement = Arrangement.End,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            TextButton(onClick = disconnect) {
                                Text(stringResource(R.string.connection_disconnect))
                            }
                        }
                    }
                    if (useRail) {
                        Row(modifier = Modifier.weight(1f).fillMaxWidth()) {
                            Column(
                                modifier = Modifier.width(railWidth),
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                Spacer(modifier = Modifier.height(12.dp))
                                NavigationRail(
                                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                                    contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                                ) {
                                    Destination.entries.forEach { item ->
                                        NavigationRailItem(
                                            selected = destination == item,
                                            onClick = { destination = item },
                                            icon = {
                                                Icon(
                                                    imageVector = iconFor(item),
                                                    contentDescription = null,
                                                )
                                            },
                                            label = { Text(stringResource(item.labelRes)) },
                                        )
                                    }
                                }
                                Spacer(modifier = Modifier.weight(1f))
                            }
                            Box(modifier = Modifier.weight(1f).fillMaxSize()) {
                                stateHolder.SaveableStateProvider("$session:${destination.name}") {
                                    when (destination) {
                                        Destination.SYSTEM -> SystemInfoScreen(
                                            state = state,
                                            onRefresh = { viewModel.refreshSnapshot() },
                                        )
                                        Destination.DOCKER -> DockerScreen(
                                            state = state,
                                            onRefresh = { viewModel.refreshSnapshot() },
                                        )
                                        Destination.LLAMA -> LlamaScreen(
                                            state = state,
                                            onRefresh = { viewModel.refreshSnapshot() },
                                            onRefreshContext = { viewModel.refreshContext() },
                                        )
                                        Destination.CONTROL -> ControlScreen(
                                            state = state,
                                            onRefreshRole = { viewModel.refreshRole() },
                                            onCheckUpdates = { viewModel.checkUpdates() },
                                            onApplyUpdates = { viewModel.applyUpdates(it) },
                                            onSchedulePower = { a, d, c -> viewModel.schedulePower(a, d, c) },
                                            onCancelPower = { viewModel.cancelPower(it) },
                                        )
                                    }
                                }
                            }
                        }
                    } else {
                        Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
                            stateHolder.SaveableStateProvider("$session:${destination.name}") {
                                when (destination) {
                                    Destination.SYSTEM -> SystemInfoScreen(
                                        state = state,
                                        onRefresh = { viewModel.refreshSnapshot() },
                                    )
                                    Destination.DOCKER -> DockerScreen(
                                        state = state,
                                        onRefresh = { viewModel.refreshSnapshot() },
                                    )
                                    Destination.LLAMA -> LlamaScreen(
                                        state = state,
                                        onRefresh = { viewModel.refreshSnapshot() },
                                        onRefreshContext = { viewModel.refreshContext() },
                                    )
                                    Destination.CONTROL -> ControlScreen(
                                        state = state,
                                        onRefreshRole = { viewModel.refreshRole() },
                                        onCheckUpdates = { viewModel.checkUpdates() },
                                        onApplyUpdates = { viewModel.applyUpdates(it) },
                                        onSchedulePower = { a, d, c -> viewModel.schedulePower(a, d, c) },
                                        onCancelPower = { viewModel.cancelPower(it) },
                                    )
                                }
                            }
                        }
                    }
                    if (!useRail) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 8.dp),
                            horizontalArrangement = Arrangement.End,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            TextButton(onClick = disconnect) {
                                Text(stringResource(R.string.connection_disconnect))
                            }
                        }
                        DestinationBar(
                            selected = destination,
                            onNavigate = { destination = it },
                            modifier = Modifier
                                .widthIn(max = 420.dp)
                                .padding(horizontal = 20.dp)
                                .padding(top = 8.dp, bottom = 12.dp),
                        )
                    }
                }
            }
        }
    }

    private enum class Destination(val labelRes: Int) {
        SYSTEM(R.string.nav_system),
        DOCKER(R.string.nav_docker),
        LLAMA(R.string.nav_llama),
        CONTROL(R.string.nav_control),
    }

    @Composable
    private fun iconFor(item: Destination) = when (item) {
        Destination.SYSTEM -> Icons.Outlined.Dashboard
        Destination.DOCKER -> Icons.Outlined.Apps
        Destination.LLAMA -> Icons.Outlined.DeveloperBoard
        Destination.CONTROL -> Icons.Outlined.Tune
    }

    @Composable
    private fun DestinationBar(
        selected: Destination,
        onNavigate: (Destination) -> Unit,
        modifier: Modifier,
    ) {
        val scheme = MaterialTheme.colorScheme
        val iconPosition = NavigationItemIconPosition.Top

        ShortNavigationBar(
            modifier = modifier.clip(RoundedCornerShape(36.dp)),
            containerColor = scheme.surfaceVariant,
            contentColor = scheme.onSurfaceVariant,
            arrangement = ShortNavigationBarArrangement.EqualWeight,
            windowInsets = WindowInsets(0, 0, 0, 0),
        ) {
            val itemColors = ShortNavigationBarItemDefaults.colors(
                selectedIconColor = scheme.onPrimary,
                selectedTextColorTopIconPosition = scheme.onSurface,
                selectedTextColorStartIconPosition = scheme.onPrimary,
                selectedIndicatorColor = scheme.primary,
                unselectedIconColor = scheme.onSurfaceVariant,
                unselectedTextColor = scheme.onSurfaceVariant,
            )

            Destination.entries.forEach { item ->
                ShortNavigationBarItem(
                    selected = selected == item,
                    onClick = { onNavigate(item) },
                    icon = {
                        Icon(
                            imageVector = iconFor(item),
                            contentDescription = null,
                        )
                    },
                    label = {
                        Text(stringResource(item.labelRes))
                    },
                    iconPosition = iconPosition,
                    colors = itemColors,
                )
            }
        }
    }
}
