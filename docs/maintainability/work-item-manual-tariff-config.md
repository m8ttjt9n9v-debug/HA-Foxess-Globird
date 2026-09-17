# Work item — typed manual-diagnostic tariffs

## Problem and evidence

Manual charge/discharge previews and current-rate display used a generic helper
that read tariff values directly from the mutable configuration mapping.

## Existing contract

- Valid non-negative configured rates are used.
- Missing or invalid import rates fall back to zero in manual diagnostics.
- Invalid or negative export rates fall back to their established defaults.
- Standard and ZEROHERO windows remain independent; the top-up is added only
  while the ZEROHERO window is active.

## Invariants and non-goals

- Preserve preview energy, cost/earning direction and rounding.
- Preserve all tariff-window decisions and malformed-value fallbacks.
- Do not change accounting, automation policy or hardware commands.
- Do not rewrite persisted entries or rename serialized keys.

## Deliverables

- Extend immutable tariff settings with manual-diagnostic import rates.
- Read all manual preview/current rates from the immutable snapshot.
- Remove the manual controller's raw mapping helper.

## Compatibility and rollback

No serialized key or config-entry version changes. Rollback restores the raw
helper against the same persisted values.

## Outcome

- Manual diagnostics now consume only immutable tariff settings.
- Configured, missing, invalid and negative rate behavior is characterized.
- Focused configuration/manual-diagnostic tests: 94 passed.
- Raw runtime configuration operations fell from six to five.
- Complete regression suite: 611 passed.
- Ruff, all generated/frozen contracts and the v0.12.26 previous-release
  rehearsal passed.
