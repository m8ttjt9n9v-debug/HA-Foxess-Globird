# FoxESS Globird Energy Observer

An Australia-scoped Home Assistant custom integration for an auditable,
site-configured home-energy ledger. Version 0.3.6 is observer-by-default:
it reads the entities selected during setup, normalises their units and signs,
persists local tariff meters and demand-learning evidence, and only permits
FoxESS writes after an explicit control opt-in, complete actuator mapping, and
Rehearsal mode being disabled.

## Installation

Install this repository in HACS as a custom **Integration** repository:

`https://github.com/m8ttjt9n9v-debug/HA-Foxess-Globird`

Then restart Home Assistant and add **FoxESS Globird Energy Observer** under
**Settings → Devices & services**. The setup flow asks for the entity IDs and
commissioned electrical limits for that site; no `configuration.yaml` edits
are required. When Tessie/Tessy is installed, common EV entities are suggested
only when the local match is unambiguous; ambiguous matches are left blank.
See the [installation guide](docs/installation.md) and
[commissioning checklist](docs/commissioning.md).

An importable, generic two-column Lovelace starter dashboard is provided at
[`examples/dashboard.yaml`](examples/dashboard.yaml). HACS installs the
integration, not Lovelace dashboards; import the view and select the generated
entities if your config-entry name differs from the example. The dashboard has
Overview, EV, Commissioning, and Diagnostics views and intentionally contains no site
background image or personal entity IDs. Version 0.2.31 gives the generated
entities stable `sensor.home_energy_*` IDs regardless of the entry name.

## What it provides

- battery SoC, potential/current/available energy, and signed grid import and
  export sensors;
- persisted daily and free-window import meters for new installations;
- configurable GloBird tariff estimates and an hourly 6–9 pm ZEROHERO guard;
- whole-house demand-learning evidence; and
- explicit single-phase 10/15/32 A and three-phase 16 A EV profile calculations;
- an optional, read-only free-window charge target at the commissioned inverter
  limit while the configured import cutoff remains; house-load and AC-coupled
  PV telemetry are retained for grid-import estimation;
- a read-only completion-mode recommendation for the reviewed `Backup` /
  `Self Use` outcomes at the configured import cutoff, regardless of battery SoC.
- a read-only ZEROHERO import accumulator with the three hourly buckets exposed
  in its attributes for evening review.
- an opt-in FoxESS free-window controller that runs every 30 seconds only when
  the automatic-control gate is enabled and all three FoxESS actuator entities
  are mapped; and
- an opt-in Tessie/Tessy current-setpoint controller that adjusts only the
  mapped current number when a connected vehicle is confirmed at home and
  local cable/current feedback is available. During the free window it paces
  total measured site import below the configured daily kWh cutoff, dynamically
  sharing the allowance with FoxESS and house load. It soaks measurable
  post-window solar surplus once the battery is full,
  and can perform a small reserve-aware pre-window backfill. It never applies
  charging limits to an away vehicle. A guarded session may use the mapped
  charge switch to start or stop only a session it owns; it does not change
  the vehicle SoC limit.
- independent automatic-control gates for FoxESS and Tessie/Tessy. Enabling
  battery control never authorizes EV current or charge-switch writes, and EV
  control can be commissioned without enabling automatic FoxESS writes. The
  shared Safety Lock remains an absolute no-write interlock for both paths.
- a preview-first Diagnostics view for short, explicit FoxESS force-charge and
  force-discharge commissioning checks. Each test has editable power and
  duration, a cost/earning preview, live feedback, a 120-minute maximum, and
  automatic Self Use restoration. Force-charge tests are blocked outside the
  free-charge window. Hardware tests require Rehearsal mode to be disabled,
  complete actuator mapping, and an explicit confirmation; they do not enable
  the automatic scheduler. Discharge previews use the configured standard or
  ZEROHERO-window export rate automatically.

The integration also exposes `switch.home_energy_safety_lock`. It is ON when
the no-write interlock is engaged; turning it OFF only opens the explicit
commissioning gate and does not enable automatic control.

The ZEROHERO guard checks each hourly bucket independently against the
configured 0.03 kWh/hour threshold. A three-hour total below 0.09 kWh does not
qualify if any individual hourly bucket exceeds 0.03 kWh/hour.

## Safety boundary

This integration is supervisory software, not electrical protection. The
default is still no hardware writes. The optional FoxESS path is a pilot
controller, not a substitute for electrical protection or installer
commissioning; it requires explicit entity mapping, response tests, and
rollback evidence. Vehicle charge-limit and FoxESS export control remain
outside this milestone. Review the [safety boundary](docs/safety.md) before use.

Please report reproducible issues in the [issue tracker](https://github.com/m8ttjt9n9v-debug/HA-Foxess-Globird/issues) without including credentials, detailed home-location data, or production sensor history.

Run the automated checks with:

```console
python -m pytest
ruff check custom_components tests
```
