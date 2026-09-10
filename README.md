# FoxESS Globird Energy Observer

A Home Assistant custom integration for a site-configured energy ledger,
conservative demand learning, bounded FoxESS diagnostics, the verified
Working Single Phase Pilot Site ZEROHERO export policy, a faithful direct-EVSE free-window port,
and a default-off Local Modbus battery-charge extension.

Version 0.12.1 includes newly requested fixed-window battery charging without
restoring the earlier rewritten controller. It reuses the bounded ZEROHERO
actuator/session pattern, remains separately gated and default-off, and is
documented as an extension because the canonical pilot YAML had no local Force
Charge writer. Separately gated Tessie paths retain their port-first
characterization and restart-safe reconciliation. Remaining behaviors are
tracked in the [roadmap](ROADMAP.md).

When automatic battery charging is requested, setup shows the exact free-power
window in 24-hour notation, its duration, and a 24-hour timeline before saving.
An overnight window requires a separate confirmation. Existing v0.12 entries
fail safe on upgrade: automatic battery charging is disabled until the schedule
has been reviewed through Reconfigure.

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
portable seven-view Lovelace dashboard for manual import. Its Overview, Tesla,
House, Solar & Weather, Configuration, Advanced, and Manual structure preserves
the proven site's operational information architecture while using only
integration-owned entity IDs. Vehicle-native Tessie cards, local weather,
rooms, and other site-specific cards belong in a local overlay.

## Current capabilities

- Assisted FoxESS Modbus and Tessie entity discovery during setup and
  reconfiguration. Only one unambiguous device cohort is suggested; existing
  valid mappings win, and electrical limits, signs, ownership and write gates
  are never inferred.

- Normalized battery SoC/energy, signed grid import/export, solar, house-load,
  and optional EV observation sensors. One timestamp-aware boundary converts
  all supported power units and configured directions into import-positive
  grid/current, charge-positive battery, and generation-positive solar values.
  Automatic writes remain locked until those conventions are explicitly
  verified. See the [normalization contract](docs/telemetry-normalization.md).
- Persisted daily import, free-window import, and hourly ZEROHERO evidence.
- Configurable tariff estimates, electrical limits, tariff windows, allowance,
  battery reserve, and export policy; control logic contains no personal entity
  IDs.
- Occupancy-aware protected-house learning ported from the Working Single Phase
  Pilot Site. Auto conservatively classifies all Home Assistant people, with
  persistent Home/Away overrides and a configurable away-confirmation period.
  Base/whole-house P80 learning runs outside the free window; an optional
  separately metered heater receives its own daily P80 stream. The controller
  selects one away fallback, occupied fallback, or mature measured budget and
  never adds a weather forecast as a second hidden demand term. See the
  [house-learning provenance](docs/house-learning-port.md).
- Explicit FoxESS ownership: Observer only, Local Modbus, or FoxCloud Mode
  Scheduler. Cloud ownership blocks every HEO Modbus write for the entire day.
- Default-off scheduled house-battery Force Charge under exclusive Local
  Modbus ownership. It starts only inside the configured free window with fresh
  SoC below the configured target, latches the bounded configured inverter
  charge power for that window, and deliberately restores Self Use afterward.
  It does not write native FoxESS schedule periods. See the
  [Local Modbus charge policy](docs/local-modbus-free-charge.md).
- The proven Working Single Phase Pilot Site ZEROHERO export policy behind independent default-off
  gates. It protects learned house energy and a configured mandatory connected-
  EV baseline, computes the latest fixed-power start, persists its session,
  bounds retries, observes the export cap, and deliberately restores Self Use
  at the configured finish. See the
  [export policy](docs/zerohero-export-policy.md).
- A default-off EV-before-export threshold can temporarily withhold that
  automatic export while mapped EV SoC is below an integration-owned,
  user-adjustable target. It preserves the saved export request and sends no EV
  charging command; target attainment simply returns eligibility to the normal
  ZEROHERO policy.
- The Working Single Phase Pilot Site direct-EVSE free-window current policy behind its own
  default-off intent, explicit commissioning, complete Tessie mappings, and the
  shared Safety Lock. It preserves matched three-minute service feedback,
  charge-limit/current/start ordering, the separate anti-pause limit, and the
  configured whole-site allowance as an outer ceiling. An unchanged target is
  limited to three feedback-confirmed command attempts. See the
  [EV charging policy](docs/ev-charging-policy.md).
- Default-off Local-Modbus-only solar-spill and latest-start pre-free Tessie
  stages. Solar spill follows measured surplus after the battery threshold;
  pre-free backfill spends only protected post-export energy that the vehicle
  can accept before the next free window. See the
  [outside-window policy](docs/ev-solar-spill-and-pre-free-policy.md).
- Optional daily EV ready-by backfill extends the pilot latest-start arithmetic
  with a configured wall-energy allocation and outside-window inverter
  percentage. It may write Tessie while FoxCloud owns the inverter, using the
  current battery/house ledger; only Local Modbus ownership lets HEO protect the
  next allocation prospectively from its own export. See the
  [daily ready-by policy](docs/ev-daily-ready-backfill.md).
- The explicitly selected smart-socket path stages a service-valid current
  before outlet power, waits the configured connector-settle period, then
  re-bounds current and starts charging. A sustained `no_power` fault receives
  at most one restart-safe, current-first outlet recovery cycle before latching.
- Tessie daily-driving learning from a mapped cumulative energy meter. It keeps
  the source's 28-cycle P85, configured arrival reserve, complete-window
  fallback, actuator-step rounding, and away/disconnected hold behavior. See
  the [learning provenance](docs/ev-driving-learning-port.md).
- Preview-first, explicitly submitted FoxESS force-charge and force-discharge
  diagnostics. Tests require Local Modbus ownership, the FoxESS gate, complete
  actuator mapping, Safety Lock off, and confirmation. They are time-bounded
  and restore Self Use; force-charge diagnostics are restricted to the
  configured free window.

The integration exposes `switch.home_energy_safety_lock`: ON means no hardware
writes. Turning it OFF does not enable automation. Automatic export additionally
requires Local Modbus ownership, the FoxESS automatic gate, and
`switch.home_energy_automatic_export`.
Automatic battery charging uses the same ownership/master/safety gates plus
`switch.home_energy_automatic_charge`; its power is the commissioned inverter
charge limit bounded by the mapped FoxESS entity.
`switch.home_energy_ev_before_export` is a further opt-in arbitration gate;
set its threshold with `number.home_energy_ev_before_export_soc_target`.
Direct-EVSE control instead requires `switch.home_energy_automatic_ev_control`,
explicit EV commissioning, and complete mappings. Free-window EV control may
run with FoxCloud as inverter owner because it writes no FoxESS entity. Solar
spill and pre-free backfill require Local Modbus ownership and remain separately
default-off. Safety Lock blocks every hardware write.

HEO creates `switch.home_energy_ev_charge_to_full` automatically. It replaces
the pilot YAML's external Toggle helper. ON is an explicit paid-grid override:
it may start charging outside the free window at the maximum permitted by the
commissioned connector and service headroom. It bypasses normal daily-energy
and inverter-percentage policy, but not Safety Lock or physical limits, and
automatically clears at full, disconnect after starting, or the configured
timeout.

## Not currently implemented

- FoxESS native schedule-period programming.
- Mixed FoxCloud schedule and local Modbus control.

The canonical pilot source has no local automatic battery `Force Charge`
writer. The new controller is therefore a separately commissioned extension,
not code claimed as a direct port. See the
[battery ownership boundary](docs/free-window-battery-ownership.md).

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
