# Work item — catalogue-driven page composition

## Scope

Replace the hand-maintained 124-key configuration page map with page ordering
derived from the immutable `FieldSpec` catalogue.

## Existing contract

- Page names, order, field membership and within-page order remain byte-for-byte
  equivalent to the frozen v0.12.26 field contract.
- Setup and reconfigure continue to share the existing canonical validators and
  defaults; only page composition changes source.
- Capability routing and draft retention remain unchanged.

## Invariants and non-goals

- Do not change field schemas, selectors, defaults, labels or validation.
- Do not change flow step IDs, page routing or config-entry serialization.
- Do not yet generate validator objects from `FieldSpec`.

Field catalogue/contract tests, config-flow tests, the full suite and the
previous-release rehearsal are acceptance gates. Rollback requires no migration.

## Outcome

- `ConfigFlow._PAGE_FIELDS` now uses the immutable catalogue's generated
  `FIELD_KEYS_BY_PAGE` projection; the duplicate 124-key page map was removed.
- Exact page names, ordering, membership and within-page field ordering are
  checked against the frozen v0.12.26 field contract.
- Focused catalogue/configuration tests: 52 passed.
- Complete regression suite: 582 passed.
- Ruff, all frozen configuration/persistence contracts, generated-catalogue
  consistency and the v0.12.26 previous-release rehearsal passed.
