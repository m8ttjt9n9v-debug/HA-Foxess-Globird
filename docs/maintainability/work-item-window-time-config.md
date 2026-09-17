# Work item — typed runtime window times

## Problem and evidence

Coordinator, EV, tariff, learning and manual-diagnostic paths shared a generic
time parser that still read the mutable configuration mapping on every call.
The window vocabulary was therefore parsed both at the configuration boundary
and again throughout runtime behavior.

## Existing contract

- Valid ISO local times are returned unchanged.
- Missing or invalid values fall back to the default supplied by the caller.
- Existing callers may request free-charge, ZEROHERO, peak, standard export,
  EV ready-by and legacy force-discharge finish times.

## Invariants and non-goals

- Preserve every configured/default time and overnight-window calculation.
- Preserve invalid-value fallback and unknown-key compatibility.
- Do not change scheduling, tariff accounting, learning or controller policy.
- Do not rewrite persisted entries or rename serialized keys.

## Deliverables

- Parse the complete runtime window vocabulary into `WindowSettings` once.
- Bridge existing callers to that immutable snapshot without a broad rewrite.
- Characterize valid, invalid, missing and unknown-key fallback behavior.

## Compatibility and rollback

No serialized key or config-entry version changes. Rollback restores the raw
runtime parser against the same persisted values.

## Outcome

- All runtime time lookups now use the immutable window snapshot.
- Focused coordinator, EV, tariff, learning, lifecycle, manual-diagnostic and
  FoxESS tests: 397 passed.
- Raw runtime configuration operations fell from seven to six.
- Complete regression suite: 610 passed.
- Ruff, all generated/frozen contracts and the v0.12.26 previous-release
  rehearsal passed.
