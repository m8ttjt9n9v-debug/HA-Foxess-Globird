# Work item — non-sensor entity catalogue

## Problem and evidence

The 15 button, switch, number, select and binary-sensor descriptions are spread
across five platform modules, while their public identity is separately
inventoried by the contract tooling. That duplication makes a presentation
change touch several sources of truth.

## Observable contract

- Six switches, four numbers, three buttons, one select and one binary sensor.
- Existing keys, names, icons, units, ranges, categories, enabled defaults,
  unique IDs, default entity IDs and setup order.
- Existing implementation classes continue to own state projection and actions.

## Invariants and non-goals

- No display-name, translation, identity, state, action or availability change.
- No sensor-platform move in this work item.
- No generic entity factory and no controller/configuration refactor.
- User registry customisations remain user-owned.

## Compatibility and persistence

This is a source-only relocation of immutable descriptions. It does not change
config-entry data, storage, state vocabulary, services or hardware commands.
The frozen v0.12.26 entity contract must remain byte-for-byte equal.

## Tests

- Frozen entity-contract comparison.
- Platform setup and action tests in the full suite.
- Registry setup/reload/migration/collision fixtures.
- Ruff, Hassfest and HACS validation.

## Rollback

Revert the work-item commit. No migration or persisted data rollback is needed.

## Acceptance evidence

- `PYTHONPATH=. python -m scripts.entity_contract --check`
- `pytest -q -p no:cacheprovider tests/test_entity_contract.py tests/test_setup.py`
- full test suite and Ruff
