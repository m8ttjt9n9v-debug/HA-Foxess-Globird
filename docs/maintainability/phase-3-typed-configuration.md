# Phase 3 — typed configuration catalogue

## Purpose

Phase 3 will parse persisted Home Assistant configuration once into immutable,
domain-grouped values. It must preserve all serialized keys, defaults,
selectors, validation, migration behavior and the multi-page draft workflow.

## Existing evidence

- `config-contract-v0.12.26.json` freezes page order and serialized vocabulary.
- `config-field-contract-v0.12.26.json` freezes all 124 wizard fields, labels,
  required/default behavior, input kind and selector configuration.
- `config-usage-contract-v0.12.26.json` inventories direct AST-visible mapping
  reads/writes, separates Home Assistant boundaries from runtime consumers,
  and distinguishes raw mapping access from the centralized managed-mutation
  API.
- Incremental consumer migrations have reduced direct AST-visible runtime raw
  access from the frozen 167-access baseline to 106 without changing the
  serialized configuration surface. Sensor presentation and diagnostics use
  typed projections, operator mutations rebuild the immutable snapshot, and
  manual plus automatic FoxESS control gates now use typed ownership, Safety
  Lock, actuator mapping and independent request values. Direct AST-visible
  runtime raw access is now 86.

## Work packages

1. Review the access inventory and group fields into site, battery, inverter,
   grid, tariff, solar, house, EV, recovery, automation and integration domains.
2. Define one immutable `FieldSpec` for each serialized field while retaining
   the frozen key and UI contract.
3. Add immutable nested runtime configuration objects and a single parser at
   setup/reconfigure boundaries.
4. Migrate one runtime consumer seam at a time; each commit must reduce
   `raw_accesses_by_layer.runtime` without changing a value, default or
   validation outcome. Managed mutations are tracked separately and do not
   count as raw configuration access.
5. Keep named cross-field validators outside metadata and prove draft retention
   after invalid submissions.
6. Remove raw runtime mappings only after the inventory reports boundary-only
   access and lifecycle snapshots remain identical.

## Invariants and non-goals

- No serialized key rename or config-entry version bump merely for style.
- No policy, scheduling, controller, persistence or hardware-command change.
- No all-at-once coordinator or EV-controller rewrite.
- Unknown legacy keys remain preserved unless an explicit migration says
  otherwise.

## Exit gate

Every persisted key has one reviewed field definition; raw mapping access is
confined to migration/platform boundaries; the existing configuration corpus
round-trips with equivalent meaning; and invalid multi-page submissions retain
the complete working draft.

## Rollback

Each consumer migration remains separately revertible. Serialized data is not
rewritten, so rollback uses the same config entry without migration.
