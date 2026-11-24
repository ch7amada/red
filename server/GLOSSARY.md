# Domain Glossary

This glossary defines domain terms only. It is not an implementation specification.

## Monitoring Snapshot

A point-in-time collection of host identity, OS, uptime, CPU, memory, swap, filesystem,
network, and GPU information returned for a reader or administrator.

## Component Status

The health state of one monitored subsystem, expressed as `ok` or `error`, with an
optional error message.

## Update Check

A scan for available package upgrades. It refreshes package metadata but does not
install, remove, or upgrade packages.

## Update Apply

An operation that installs available package upgrades without removing packages and
without rebooting. It may report that a reboot is required.

## Operation Job

A tracked asynchronous execution of an update check or update apply, including status,
timing, output, and result.

## Power Action

A scheduled reboot or shutdown requested through the service. It can be cancelled
before its scheduled execution time.

## Cancellation Window

The period before a power action's scheduled execution time during which it can be
cancelled. Once the scheduled time has passed, cancellation is no longer possible.

## Reader

A role with read-only access to monitoring data. It cannot mutate system state.

## Administrator

A role that includes all reader capabilities and can start update checks, apply
updates, inspect jobs, and manage power actions.

## Audit Record

A persisted record of who performed an operation, when, and whether it succeeded or
failed.

## Reboot Required

A flag indicating that installed updates require a reboot before they are fully active.
It does not trigger a reboot automatically.
