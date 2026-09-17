# Work item — configuration corpus and draft retention

## Problem and evidence

Phase 3 requires proof that existing configuration shapes retain equivalent
meaning and that one invalid page cannot erase the rest of a multi-page draft.
Earlier tests covered individual defaults and one invalid battery field, not a
representative topology corpus or every independently validated page.

## Existing contract

Configuration keys and fields are frozen at v0.12.26. `_apply_defaults` is the
compatibility normalization boundary; `RuntimeConfiguration` is the immutable
runtime meaning consumed after that boundary.

## Invariants

- Current battery-only, direct three-phase EV, smart-socket EV, FoxCloud and
  legacy configurations normalize idempotently and retain equivalent runtime
  meaning.
- Unknown retained extension keys survive normalization and serialization.
- Invalid submissions redisplay every submitted field without erasing earlier
  valid pages; correcting the error produces the intended complete entry.
- No control policy, hardware command, persisted key or migration changes.

## Deliverables

- A sanitized five-shape configuration corpus exercised through the real Home
  Assistant setup serialization path.
- Data-driven invalid/correct/resume coverage for all ten pages with an
  integration-level invalid input. Solar, car and verification values are
  carried as sentinels through those failures and verified in the final entry;
  their invalid primitive inputs are enforced earlier by Home Assistant's
  selector layer.

## Compatibility and rollback

This is test and evidence only. It publishes no private site values and changes
no production path. Rollback removes only the additional tests and evidence.

## Acceptance evidence

Focused corpus/config-flow tests, the full suite, Ruff, all frozen contracts and
the v0.12.26 previous-release rehearsal must pass.

## Outcome

- Five sanitized topology shapes pass through the real setup serialization
  boundary, normalize idempotently, preserve unknown compatibility data and
  produce the same immutable runtime meaning.
- Ten domain-invalid page cases are corrected and resumed through all pages;
  final entries retain the site, battery, solar, car and verification sentinel
  values submitted before each failure.
- Focused configuration/corpus tests: 131 passed.
- Complete regression suite: 600 passed.
- Ruff, all generated/frozen contracts and the v0.12.26 previous-release
  rehearsal passed.
