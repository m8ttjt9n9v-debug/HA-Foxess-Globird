# Work item — immutable FieldSpec catalogue

## Scope

Create one immutable `FieldSpec` for every field in the frozen v0.12.26
configuration UI contract before changing schema construction.

## Existing contract

- All 124 setup/reconfigure fields retain key, type, default presence/value,
  selector configuration, page, order and required status.
- Solar fields apply only when solar is configured; car, charger, EV-policy and
  recovery fields apply only when EV support is configured.
- Entity IDs are omitted from support data, the site name is redacted and other
  values may be retained; diagnostics continue to omit the raw configuration.
- Translation lookup remains keyed by each stable serialized field key.

## Invariants and non-goals

- This seam introduces and verifies metadata only; it does not yet generate the
  Home Assistant schema from the catalogue.
- Do not change labels, selectors, validation, page routing or persisted data.
- Do not change config-entry version, migrations or runtime control behavior.

The generated-source check, field-contract parity, config-flow tests, the full
suite and previous-release rehearsal are acceptance gates. Rollback requires no
data migration.

## Outcome

- All 124 frozen fields have an immutable `FieldSpec` and immutable keyed view.
- Type, defaults, selectors, page/order and required status exactly match the
  existing setup/reconfigure schemas; capability, redaction and translation
  metadata is complete and separately asserted.
- Acceptance passed: 52 focused tests, 582 full-suite tests, Ruff, generated
  catalogue/configuration/persistence contracts and the v0.12.26 rehearsal.
