# FoxESS Globird Energy Observer

An Australia-scoped Home Assistant custom integration for an auditable,
site-configured home-energy ledger. Version 0.2.23 is deliberately
observer-only: it reads the entities selected during setup, normalises their
units and signs, persists local tariff meters and demand-learning evidence,
and makes no service calls or hardware changes.

## Installation

Install this repository in HACS as a custom **Integration** repository:

`https://github.com/m8ttjt9n9v-debug/HA-Foxess-Globird`

Then restart Home Assistant and add **FoxESS Globird Energy Observer** under
**Settings → Devices & services**. The setup flow asks for the entity IDs and
commissioned electrical limits for that site; no `configuration.yaml` edits
are required. See the [installation guide](docs/installation.md) and
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

The ZEROHERO guard checks each hourly bucket independently against the
configured 0.03 kWh/hour threshold. A three-hour total below 0.09 kWh does not
qualify if any individual hourly bucket exceeds 0.03 kWh/hour.

## Safety boundary

This integration is supervisory software, not electrical protection. It does
not control FoxESS equipment, EVs, EVSEs, sockets, or tariff settings. Any
future actuator release must be separately commissioned with explicit entity
mapping, response tests, and rollback evidence. Review the [safety
boundary](docs/safety.md) before use.

Please report reproducible issues in the [issue tracker](https://github.com/m8ttjt9n9v-debug/HA-Foxess-Globird/issues) without including credentials, detailed home-location data, or production sensor history.

Run the automated checks with:

```console
python -m pytest
ruff check custom_components tests
```
