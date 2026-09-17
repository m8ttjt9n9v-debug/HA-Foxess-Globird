# Work item — typed active battery/export configuration

## Problem and evidence

The corrected configuration-usage inventory exposed direct mutable-mapping
reads in the active FoxESS controller. They covered the free-window battery
target, automatic export limit, discharge efficiency and the legacy
force-discharge finish/offset selection.

## Existing contract

- Numeric values use their established defaults when absent or invalid and are
  clamped to zero when negative.
- When the offset key is present, export finishes at the ZEROHERO window end
  plus the configured non-negative offset.
- When the offset key is absent, pre-v5 entries retain the separately stored
  force-discharge finish time.
- Missing or invalid window times retain the established runtime defaults.

## Invariants and non-goals

- Preserve all serialized keys, defaults, validation and migration behavior.
- Preserve export energy, reserve, efficiency and time calculations exactly.
- Do not change controller scheduling, latching or hardware commands.
- Do not rewrite persisted entries.

## Deliverables

- Add immutable battery/export projections and effective window fallbacks.
- Make the active FoxESS controller consume only those projections.
- Characterize missing, valid, invalid and negative values plus the legacy key
  presence rule.

## Compatibility and rollback

No serialized key or config-entry version changes. Rollback restores the raw
reads against the same stored configuration without data conversion.

## Acceptance evidence

- Focused configuration and active-controller tests: 113 passed.
- Direct raw runtime configuration operations fell from nine to seven.
- Full suite, Ruff, all frozen contracts and the v0.12.26 previous-release
  rehearsal must pass before commit.

## Outcome

- The active controller now consumes immutable battery/export/window values;
  no direct configuration mapping read remains in `active.py`.
- Missing, valid, invalid and negative values retain the established behavior,
  including the pre-v5 finish-time fallback when the offset key is absent.
- Focused configuration and active-controller tests: 113 passed.
- Complete regression suite: 609 passed.
- Ruff, all generated/frozen contracts and the v0.12.26 previous-release
  rehearsal passed.
