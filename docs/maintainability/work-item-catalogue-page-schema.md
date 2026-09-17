# Work item — catalogue-driven page schemas

## Problem and evidence

The immutable field catalogue controls page membership and ordering, but the
human configuration pages still reconstruct markers and selectors indirectly
through the legacy full-payload schema. The site page separately duplicates
three field definitions.

## Existing contract

The frozen v0.12.26 field contract records all 124 page fields, including
required/optional status, displayed default, selector type and selector config.

## Invariants

- Page names, order, fields, required status, defaults and selectors do not
  change.
- Numeric float/int coercion and optional-field default behavior do not change.
- Setup/reconfigure validation, draft retention and serialization do not
  change.

## Non-goals

- Do not change the legacy full-payload import/automation compatibility schema.
- Do not move cross-field or physical-limit validation into field metadata.
- Do not rename any key, label, step or translation.

## Deliverables

- One catalogue-driven page-schema builder.
- Frozen-contract and dynamic-default characterization tests.
- `ConfigFlow._page_schema` delegates only to that builder.

## Compatibility and rollback

No persisted data, entity, service, dashboard or migration changes. Reverting
this seam restores the former indirect builder without rewriting configuration.

## Acceptance evidence

The focused config-flow/catalogue tests, full suite, Ruff, all frozen contracts
and the v0.12.26 previous-release rehearsal must pass.

## Outcome

- Human setup and reconfigure pages now build markers and selectors directly
  from the immutable catalogue.
- The legacy full-payload schema remains unchanged for import and automation
  compatibility.
- Frozen-contract coverage proves all 124 fields retain exact required status,
  defaults, selector kind/config and order; focused coverage also proves dynamic
  optional defaults and float/int coercion.
- Focused schema/catalogue/config-flow tests: 55 passed.
- Complete regression suite: 585 passed.
- Ruff, all generated/frozen contracts and the v0.12.26 previous-release
  rehearsal passed.
