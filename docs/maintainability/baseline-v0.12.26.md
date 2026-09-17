# Reproducible baseline — v0.12.26

This baseline was captured from commit `c83b5ae` before structural maintenance
work. Counts are descriptive evidence, not optimisation targets.

## Repository surface

- Production Python: 16,292 physical lines across the integration package.
- Test Python: 9,205 physical lines.
- Collected tests: 414 after adding the first registry contract test.
- Public entities: 107 total—92 sensors, six switches, four numbers, three
  buttons, one binary sensor and one select.
- Configuration constants: 130 `CONF_*` keys.
- Home Assistant stores: 13 separately constructed stores.

## Reconciliation sources

- `EnergyCoordinator`: 30-second `DataUpdateCoordinator` interval plus mapped
  source state-change events.
- `ActiveFoxessController`: independent 30-second interval.
- `ActiveEvController`: independent 30-second interval plus specific scheduled
  time callbacks.

The overlap is recorded for later lifecycle characterization. It must not be
consolidated until ordered command and persistence traces prove equivalence.

## Large responsibility concentrations

- `ev_active.py`: EV eligibility, priority, planning, feedback reconciliation,
  recovery, persistence and commands.
- `config_flow.py`: page composition, defaults, selectors, validation,
  discovery and reconfiguration.
- `coordinator.py`: state acquisition, canonical telemetry, accumulators,
  accounting, learning, forecasting, stores and refresh scheduling.
- `sensor.py`: 92 sensor descriptions plus value and attribute projection.

These are investigation priorities, not permission for a rewrite.

## Initial contract defect

Platform setup attempted to return already registered sensor and switch entity
IDs to HEO's preferred object IDs whenever those IDs were free. This could undo
a user's entity-ID customization after setup or reload. OM-003 characterizes
and removes that behaviour while retaining clean-install defaults.

## Reproduction commands

```bash
pytest
ruff check custom_components tests
```

The GitHub workflow runs Python 3.14 with
`pytest-homeassistant-custom-component==0.13.357`. Local maintenance work uses
the same test dependency environment. Exact test counts and durations are
updated only at explicit phase gates.
