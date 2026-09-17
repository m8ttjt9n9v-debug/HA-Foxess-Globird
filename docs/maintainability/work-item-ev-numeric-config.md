# Work item — immutable EV numeric configuration

## Problem

The active EV controller's generic numeric helper was the final runtime path
that read the mutable persisted-configuration mapping directly. It served 39
reviewed numeric fields spanning EV policy, learning, telemetry, recovery,
battery reserve and site electrical limits.

## Preserved contract

- A missing field uses its existing `DEFAULT_*` constant.
- A value accepted by `float()` keeps the same numeric meaning.
- Invalid and non-finite values fall back to the existing default.
- Negative values remain negative; this seam does not introduce validation or
  clamping.
- An unknown helper key still uses the caller-supplied compatibility default.
- The serialized keys, setup/reconfigure flow and hardware behavior do not
  change.

## Change

`RuntimeConfiguration` now contains an immutable `EvNumericSettings` snapshot.
Its reviewed key/default table is derived from the existing `CONF_*` and
`DEFAULT_*` constants, and `ActiveEvController._float()` reads that snapshot
instead of the mutable config-entry mapping.

## Verification

- Exact coverage and default-value tests for all 39 fields.
- Mapping immutability and unknown-key compatibility tests.
- Invalid, non-finite and negative-value behavior tests.
- EV controller, backfill, learning and outside-window regression tests.
- Repository configuration-usage contract now enforces zero raw runtime
  mapping accesses. The 11 remaining runtime accesses are managed mutations;
  the two dynamic accesses are classified coordinator mutation boundaries.

## Outcome

- Focused configuration and EV regressions: 183 passed.
- Full repository suite: 628 passed.
- Ruff and the field-catalogue, configuration-usage, configuration,
  configuration-field and persistence contract checks passed.
- The v0.12.26 previous-release upgrade rehearsal passed.
- `README.md` was not changed.
