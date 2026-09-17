# Phase 1 — entity and configuration contract

## Problem and evidence

HEO exposes 107 entities plus custom attributes from 16 sensors. Identity is
frozen, but semantic role, producer, availability and terminology are still
distributed across platform code, dashboards and documentation. A small
presentation change can therefore have an unnecessarily large compatibility
blast radius.

## Existing contract

- Unique IDs, default entity IDs, names, units and classifications are frozen
  in `entity-contract-v0.12.26.json`.
- Custom attributes are public API for dashboards, automations and Fleet REST
  consumers even when Home Assistant does not register them separately.
- User-renamed IDs, names, areas, labels, visibility and enabled state remain
  user-owned.
- State values, serialized configuration keys and persisted payloads are not
  renamed by this phase.

## Invariants

- Runtime states, attributes, service calls, schedules and persistence do not
  change while contracts are inventoried.
- Existing unique IDs and default entity IDs remain stable.
- Fleet Summary schema version 1 remains readable.
- A contract check reports public-surface drift; it does not silently approve
  or rewrite that drift.

## Non-goals

- No entity relabel, translation migration, alias or deprecation yet.
- No controller, accounting, scheduling or persistence refactor.
- No attempt to infer project-owner terminology approval from source code.

## Deliverables

1. Immutable v0.12.26 identity and custom-attribute baselines.
2. Immutable wizard-field page/order, required/default, input-kind, selector
   configuration and setup/reconfigure label baseline.
3. Mechanical drift checks run by the ordinary test suite.
4. A semantic worksheet covering every entity and attribute: definition,
   producer, role, unit/sign/time basis, availability, vocabulary, audience,
   equivalents, consumers and retain/relabel/deprecate decision.
5. A terminology review table for project-owner approval before display names
   change.

The semantic worksheet is deliberately completed in reviewed domain slices.
Six domain slices define all 107 electrical, accounting, learning,
operator-control, controller, EV and aggregate diagnostic entities plus every
custom public attribute profile. The nine proposed relabel records were
approved together by the project owner on 2026-09-17. All other records retain
their reviewed engineering status and existing names.

The consolidated nine-name approval is recorded in the
[v0.12.26 entity terminology review](terminology-review-v0.12.26.md).

## Compatibility

The attribute baseline is generated from literal mappings in `sensor.py` and
joined to the frozen entity identity contract. It records only HEO-defined
custom attributes, not standard Home Assistant attributes such as
`friendly_name` or `unit_of_measurement`. A changed key fails CI until its
dashboard, automation, Fleet, documentation and rollback consequences have
been reviewed.

System-level registry fixtures also prove that setup and reload retain a
user-owned entity ID, display name, area, label, visibility and disabled
state. A version-1 entry retains those customizations through migration and
setup, while a foreign integration that already owns an HEO preferred entity
ID keeps it and HEO receives one stable suffixed ID across reload. A true
previous-release downgrade fixture remains deliberately unclaimed.

## Test plan

- Regenerate both contracts from a clean checkout and compare byte-for-byte.
- Require every attribute-bearing entity to exist in the identity contract.
- Reject non-literal attribute keys because they cannot be reliably reviewed.
- Require unique entity and attribute keys.
- Preserve setup/reload registry and lifecycle tests from Phase 0.

## Rollback

This work adds documentation and checks only. Reverting its commit removes the
new contract without changing runtime data, registry state or hardware mode.

## Acceptance evidence

- `PYTHONPATH=. python -m scripts.entity_attribute_contract --check`
- `PYTHONPATH=. python -m scripts.config_field_contract --check`
- `pytest -q -p no:cacheprovider tests/test_entity_attribute_contract.py`
- `pytest -q -p no:cacheprovider tests/test_setup.py::test_setup_preserves_user_owned_entity_ids_and_names tests/test_setup.py::test_upgrade_preserves_user_owned_registry_customizations tests/test_setup.py::test_default_entity_id_collision_preserves_both_registry_owners`
- full test suite and Ruff

## Completion record

- [x] Existing entity identity characterised
- [x] Custom public attributes characterised
- [x] Existing wizard field mechanics characterised
- [x] Semantic worksheet complete (107 of 107 entities drafted)
- [x] Project-owner terminology review complete (nine names approved)
- [ ] Compatibility checks passed for the naming-only release
- [ ] Independent review complete
