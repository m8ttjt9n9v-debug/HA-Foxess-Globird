# FoxESS Globird Energy Observer

A Home Assistant custom integration for a site-configured energy ledger,
conservative demand learning, bounded FoxESS diagnostics, the verified
Working Single Phase Pilot Site ZEROHERO export policy, and a faithful direct-EVSE free-window port.

Version 0.4.0 deliberately removes the automatic battery and Tessie controllers
that were not faithful ports of the proven Working Single Phase Pilot Site. Automatic FoxESS
free charging remains absent. A separately gated direct-EVSE free-window Tessie
path has now returned through port-first characterization and bounded feedback
reconciliation. Remaining behaviors are tracked in the [roadmap](ROADMAP.md).

## Installation

Install this public repository in HACS as a custom **Integration** repository:

`https://github.com/m8ttjt9n9v-debug/HA-Foxess-Globird`

Restart Home Assistant and add **FoxESS Globird Energy Observer** under
**Settings → Devices & services**. No `configuration.yaml` edit is required.
The setup flow explicitly maps telemetry and FoxESS actuators and asks for the
commissioned limits for that site.

Read the [system requirements](docs/system-requirements.md),
[installation guide](docs/installation.md), and
[commissioning checklist](docs/commissioning.md) before enabling writes. HACS
installs the integration, not dashboards; `examples/dashboard.yaml` is a
generic Lovelace view for manual import.

## Current capabilities

- Normalized battery SoC/energy, signed grid import/export, solar, house-load,
  and optional EV observation sensors.
- Persisted daily import, free-window import, and hourly ZEROHERO evidence.
- Configurable tariff estimates, electrical limits, tariff windows, allowance,
  battery reserve, and export policy; control logic contains no personal entity
  IDs.
- Mapped protected-house demand learning outside the free window. In-progress cycles and
  retained samples survive Home Assistant restarts; an over-gap cycle is
  rejected instead of fabricating demand.
- Explicit FoxESS ownership: Observer only, Local Modbus, or FoxCloud Mode
  Scheduler. Cloud ownership blocks every HEO Modbus write for the entire day.
- The proven Working Single Phase Pilot Site ZEROHERO export policy behind independent default-off
  gates. It protects learned house energy and a configured mandatory connected-
  EV baseline, computes the latest fixed-power start, persists its session,
  bounds retries, observes the export cap, and deliberately restores Self Use
  at the configured finish. See the
  [export policy](docs/zerohero-export-policy.md).
- The Working Single Phase Pilot Site direct-EVSE free-window current policy behind its own
  default-off intent, explicit commissioning, complete Tessie mappings, and the
  shared Safety Lock. It preserves matched three-minute service feedback,
  charge-limit/current/start ordering, the separate anti-pause limit, and the
  configured whole-site allowance as an outer ceiling. An unchanged target is
  limited to three feedback-confirmed command attempts. See the
  [EV charging policy](docs/ev-charging-policy.md).
- Preview-first, explicitly submitted FoxESS force-charge and force-discharge
  diagnostics. Tests require Local Modbus ownership, the FoxESS gate, complete
  actuator mapping, Safety Lock off, and confirmation. They are time-bounded
  and restore Self Use; force-charge diagnostics are restricted to the
  configured free window.

The integration exposes `switch.home_energy_safety_lock`: ON means no hardware
writes. Turning it OFF does not enable automation. Automatic export additionally
requires Local Modbus ownership, the FoxESS automatic gate, and
`switch.home_energy_automatic_export`.
Direct-EVSE control instead requires `switch.home_energy_automatic_ev_control`,
explicit EV commissioning, and complete mappings. It writes no FoxESS entity,
so FoxCloud may remain the inverter owner; Safety Lock still blocks both paths.

## Not currently implemented

- Automatic FoxESS free-window charging or post-charge reconciliation.
- Tessie smart-socket recovery, learned driving targets, pre-free backfill, and
  solar-spill charging.
- Mixed FoxCloud schedule and local Modbus control.

These are intentionally absent rather than represented by simplified rewrite
code. The [project source of truth](docs/source-of-truth.md) records the public
engineering evidence; the [port-first guide](docs/port-first-development.md)
defines the proof required before behavior returns.

## Safety boundary

Home Assistant is supervisory software, not electrical protection. Keep one
inverter owner, validate grid sign and direct Modbus feedback, and retain a
rollback path. Do not enable Local Modbus automation while FoxCloud Mode
Scheduler or another inverter writer is active. Review the
[safety boundary](docs/safety.md).

Run the automated checks with:

```console
python -m pytest
ruff check custom_components tests
```

Report reproducible issues in the
[issue tracker](https://github.com/m8ttjt9n9v-debug/HA-Foxess-Globird/issues)
without credentials, precise location data, or production sensor history.
