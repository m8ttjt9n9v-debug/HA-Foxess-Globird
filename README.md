# FoxESS Globird Energy Observer

An Australia-scoped Home Assistant custom integration for an auditable,
site-configured home-energy ledger. Version 0.2.26 is observer-by-default:
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

## What it provides

- battery SoC, potential/current/available energy, and signed grid import and
  export sensors;
- persisted daily and free-window import meters for new installations;
- configurable GloBird tariff estimates and an hourly 6–9 pm ZEROHERO guard;
- whole-house demand-learning evidence; and
- explicit single-phase 10/15/32 A and three-phase 16 A EV profile calculations;
- an optional, read-only free-window charge target paced from allowance,
  house-load, AC-coupled PV, and inverter-limit telemetry;
- a read-only completion-mode recommendation for the reviewed `Backup` /
  `Self Use` outcomes at full battery.
- an opt-in FoxESS free-window controller that runs every 30 seconds only when
  the automatic-control gate is enabled and all three FoxESS actuator entities
  are mapped; and
- an opt-in Tessie/Tessy current-setpoint controller that adjusts only the
  mapped current number during the free window when local cable and charger
  current feedback is available. It does not start/stop charging or change
  the vehicle SoC limit.

The ZEROHERO guard checks each hourly bucket independently against the
configured 0.03 kWh/hour threshold. A three-hour total below 0.09 kWh does not
qualify if any individual hourly bucket exceeds 0.03 kWh/hour.

## Safety boundary

This integration is supervisory software, not electrical protection. The
default is still no hardware writes. The optional FoxESS path is a pilot
controller, not a substitute for electrical protection or installer
commissioning; it requires explicit entity mapping, response tests, and
rollback evidence. EV start/stop, vehicle limit, and export control remain
outside this milestone. Review the [safety boundary](docs/safety.md) before use.

Please report reproducible issues in the [issue tracker](https://github.com/m8ttjt9n9v-debug/HA-Foxess-Globird/issues) without including credentials, detailed home-location data, or production sensor history.

Run the automated checks with:

```console
python -m pytest
ruff check custom_components tests
```
