# Work item — typed house-learning configuration

## Scope

Migrate occupancy, house-learning fallbacks, heater mapping and explicitly
configured free-window sampler times to immutable runtime settings.

## Existing contract

- Demand sampling exists only when both free-window keys are present and valid.
- Heater sampling additionally requires an explicit heater mapping.
- An unparsable occupied or away fallback resets both to their defaults; finite
  negative/non-finite values are subsequently defaulted independently.
- Invalid away-confirmation input forces conservative `home` occupancy with a
  zero-hour confirmation.
- Raw invalid occupancy selections retain the classifier's conservative result.

## Invariants and non-goals

- Preserve sampler boundaries, sample admission, fallback coupling and reasons.
- Preserve freshness-qualified EV/heater subtraction from whole-house power.
- Do not migrate unrelated controller/tariff windows or learning persistence.
- Do not change serialized fields, validation or entity identity.

Focused learning/lifecycle tests, the full suite and previous-release rehearsal
are the acceptance gates. Rollback requires no data migration.

## Outcome

- Runtime raw configuration access reduced from 26 to 13; coordinator access
  reduced to nine.
- Existing malformed-value behavior, coupled fallback behavior and sampler
  admission rules are characterized and preserved.
- Acceptance passed: 131 focused tests, 567 full-suite tests, Ruff, all tracked
  configuration/persistence contracts and the v0.12.26 upgrade rehearsal.
