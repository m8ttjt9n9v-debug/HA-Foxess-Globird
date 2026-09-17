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
  Lock, actuator mapping, independent request values and automatic-export EV
  protection inputs and legacy-compatible charge-to-full intent. Direct
  EV Home/Auto/Away mode, home/cable mappings, actuator mappings, telemetry
  mappings, policy modes and the active controller's remaining site inputs are
  also consumed through immutable snapshots. The active EV controller now has
  no non-mutating direct configuration reads. Direct AST-visible runtime raw
  access is now 35, and the EV authorization adapter has no raw configuration
  reads. Shared coordinator site, battery and EV mappings are now typed as well,
  reducing direct AST-visible runtime raw access to 26. Occupancy, house-learning
  fallbacks, heater mapping and explicitly configured free-window sampler times
  are now typed, reducing direct AST-visible runtime raw access to 13. Nine of
  those are remaining coordinator reads; four are explicit charge-to-full
  compatibility mutations rather than policy reads. Telemetry freshness,
  legacy battery sign fallback and split battery mappings are now typed as
  well, reducing runtime raw access to nine and coordinator raw access to five.
  Daily-import accounting, retailer scorecard mappings and the ZEROHERO active
  window are now typed, reducing direct AST-visible runtime raw access to four
  and coordinator raw access to zero. The four remaining raw accesses are
  explicit charge-to-full compatibility mutations. Those compatibility writes
  now use the same coordinator-owned persistence/snapshot boundary as every
  other operator mutation. Direct raw mapping access is therefore confined to
  setup/configuration boundaries; the 11 runtime accesses are all inventoried
  managed mutations. Every frozen v0.12.26 wizard field now has one generated,
  immutable `FieldSpec` covering serialized key, semantic type, default,
  selector, page/order, applicability, redaction and translation key. Exact
  parity with the 124-field UI contract is enforced. Configuration page
  composition now comes from the catalogue's immutable page projection, so the
  former duplicate 124-key page map has been removed without changing page or
  field order. Human setup and reconfigure page markers, displayed defaults and
  selectors are now constructed directly from those same immutable field
  definitions, with exact frozen-contract and numeric-coercion coverage. The
  separate legacy full-payload compatibility schema remains unchanged, and
  named cross-field validators remain outside catalogue metadata. A sanitized
  five-topology corpus now proves idempotent serialization and equivalent typed
  runtime meaning, while ten domain-invalid page scenarios prove the complete
  multi-page draft survives correction and final commit. The completion audit
  also identified dynamic-key raw configuration helpers that the v2 AST usage
  inventory did not count. Contract schema v3 now exposes 13 raw runtime
  mapping operations (eleven variable-key, one literal legacy fallback and one
  constant-key membership test), in
  addition to 11 managed mutation calls. Phase 3 therefore remains open until
  those raw runtime reads are migrated and the central mutation implementation
  is explicitly classified as the boundary it provides. The first corrected
  seam moved power-source mappings, listener registration and effective grid,
  solar and service-current directions into the immutable snapshot, reducing
  raw runtime mapping operations from 13 to nine without changing telemetry.
  The next seam moved the active battery free-window target, automatic export
  limit, discharge efficiency and legacy-compatible finish/offset selection
  into the immutable snapshot. Raw runtime mapping operations are now seven;
  the remaining reads are coordinator, EV-controller and manual-test helpers
  plus the centralized mutation implementation.

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
