# Work item — accounting and scorecard read model

## Problem

Estimated Net Cost attributes, four prior-day scorecard entities, Fleet Summary
and redacted support diagnostics each assembled forecast and retailer-result
facts directly from the ledger, optimistic forecast and feedback state. This
allowed one presentation surface to drift without changing the accounting
engine itself.

## Canonical projections

- `CostReadModel` owns measured gross/export/credit/net values, optimistic
  forecast inputs and both forecast-time and currently learned calibration
  values.
- `ScorecardReadModel` owns the matched result date, frozen forecast, retailer
  actual, error, ZEROHERO outcome, realised/planned export evidence and feedback
  status.
- `SiteReadModel` projects those values to individual entity states, entity
  attributes, Fleet Summary and redacted forecast diagnostics.

## Preserved behavior

- No tariff, ledger, forecast or feedback calculation moved into presentation.
- Estimated Net Cost state and Fleet cost values retain two-decimal rounding.
- Prior-day entity states retain raw stored precision.
- Entity attribute names and support-diagnostic keys are unchanged.
- Forecast-specific attributes remain `None` when no optimistic forecast
  exists; learned feedback diagnostics remain available as before.
- Missing scorecard records retain `None` values and a false feedback flag.

## Verification

- Characterization covers every cost, scorecard and forecast-diagnostic key.
- Frozen attribute extraction now follows canonical cost and scorecard methods
  as well as remaining sensor-local mappings, retaining full public coverage.
- Focused read-model, presentation, entity-contract, setup/diagnostics and
  lifecycle suite: 98 passed.
- Full repository suite: 631 passed.
- Ruff, frozen entity/attribute/configuration/persistence contracts and the
  v0.12.26 previous-release upgrade rehearsal passed.
- `README.md` was not changed.
