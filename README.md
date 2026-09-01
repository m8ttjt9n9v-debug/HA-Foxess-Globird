# FoxESS Globird Energy Observer

An Australia-scoped Home Assistant custom integration for an auditable,
site-configured home-energy ledger. Version 0.1.1 is deliberately
**observer-only**: it reads the Home Assistant entities selected during setup
and makes no service calls or hardware changes.

## What it does

- guides setup through Home Assistant's UI; no `configuration.yaml` edits;
- normalises battery, signed grid, household-load, and EV limit values;
- exposes observer status, available battery energy, grid import/export, and
  configured EV-power sensors;
- keeps source entity mappings in the config entry and offers reconfiguration;
- produces redacted diagnostics; and
- installs independently of inverter, EV, EVSE, smart-socket, and tariff
  providers.

## Installation

This integration requires Home Assistant 2025.1.4 or newer. Once the GitHub
repository has been published, install it in HACS as a custom **Integration**
repository using:

`https://github.com/m8ttjt9n9v-debug/HA-Foxess-Globird`

Then restart Home Assistant and add **FoxESS Globird Energy Observer** from
**Settings → Devices & services**. The setup flow asks for the local entity
IDs and electrical limits for that home. See the [installation guide](docs/installation.md)
and the [clean-instance pilot](docs/clean-instance-pilot.md).

## Safety and release scope

This integration is supervisory software, not electrical protection. Every
installation must independently validate its entity mappings, measurement
units, sign conventions, and electrical limits.

It does not currently control FoxESS equipment, EVs, EVSEs, sockets, or tariff
settings. Adding actuator control requires a separately commissioned and
tested release.

## Support and development

Please report reproducible issues in the [issue tracker](https://github.com/m8ttjt9n9v-debug/HA-Foxess-Globird/issues), without including credentials, detailed home location data, or production sensor history.

Run the automated checks with:

```console
python -m pytest
ruff check .
ruff format --check .
```

The [HACS publication checklist](docs/hacs-publishing.md) records the
remaining external release checks.
