# Work item — sensor entity catalogue

## Problem and evidence

The 92 sensor descriptions occupy the first large block of `sensor.py`, while
their identity is consumed independently by contract tooling. Keeping the
declarations beside a 900-line presentation implementation makes both files
harder to review and prevents one catalogue from covering the complete public
surface.

## Observable contract

- All 92 sensor keys, names, icons, units, device/state classes, precision,
  categories and enabled defaults.
- Existing setup order, unique IDs, default entity IDs, states, attributes and
  availability.
- The existing `EnergySensor` projection and attribute implementation remains
  in `sensor.py` unchanged.

## Invariants and non-goals

- Mechanical relocation only; no approved or proposed label is applied.
- No translation key, category, projection, availability or behavior change.
- No sensor factory, read model or controller refactor.
- The complete 107-entity catalogue must reproduce the frozen v0.12.26
  identity contract byte-for-byte.

## Compatibility and persistence

No config-entry, entity-registry, Recorder, dashboard, storage, service or
hardware-command contract changes. Rollback requires no data migration.

## Tests

- Catalogue completeness and uniqueness for all 107 entities.
- Frozen entity and dashboard contract checks.
- Sensor-presentation and setup lifecycle tests.
- Full suite, Ruff, Hassfest and HACS validation.

## Rollback

Revert the work-item commit. Entity identity and persistent data are unchanged.

## Acceptance evidence

- `PYTHONPATH=. python -m scripts.entity_contract --check`
- `pytest -q -p no:cacheprovider tests/test_entity_contract.py tests/test_sensor_presentation.py tests/test_setup.py`
- full test suite and Ruff
