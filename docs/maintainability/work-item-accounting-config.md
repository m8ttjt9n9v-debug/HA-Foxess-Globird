# Work item — typed accounting configuration

## Scope

Migrate the cumulative daily-import mapping, retailer scorecard mappings and
ZEROHERO active-window inputs to immutable runtime settings.

## Existing contract

- A missing mapped daily meter falls back to the restart-persistent internal
  accumulator.
- Scorecard matching requires both mappings, complete same-date retailer data,
  a finite cost and a recognized ZEROHERO result.
- Missing bonus-window values use established defaults; invalid values disable
  the active-window check; equal endpoints mean no active window.
- Overnight windows remain start-inclusive and end-exclusive.

## Invariants and non-goals

- Preserve tariff totals, scorecard status/reasons and forecast feedback.
- Preserve daily-meter fallback, date matching and reload behavior.
- Do not change tariff rates, forecast calibration, active control or storage.
- Do not change serialized fields, entity identities or migration behavior.

Focused tariff/scorecard/lifecycle tests, the full suite and previous-release
rehearsal are the acceptance gates. Rollback requires no data migration.

## Outcome

- Direct AST-visible runtime raw configuration access reduced from nine to
  four; coordinator raw access reduced from five to zero.
- Existing mapped-meter fallback, scorecard matching, invalid-window behavior
  and overnight boundary semantics are characterized and preserved.
- Acceptance passed: 214 focused tests, 579 full-suite tests, Ruff, all tracked
  configuration/persistence contracts and the v0.12.26 upgrade rehearsal.
