# Work item — forecast-feedback typed repository

## Problem

Forecast feedback uses an immutable-style decoder that returns a replacement
state, so it could not use the mutating accumulator repository without either
changing its proven domain API or duplicating persistence mechanics.

## Change and preserved behavior

`TypedValueStoreRepository` provides the corresponding value-returning load
path. Forecast feedback now loads and saves through it while retaining the
original Store object, private key, version 1 payload, decoder defaults,
rollover behavior, checkpoint signature and save timing. Invalid outer payloads
use the existing `ForecastFeedbackState.restore(None, ...)` fallback.

## Rollback

Restore the former direct `_forecast_store` load/save calls and remove the
repository attribute. No payload migration or stored-data rollback is needed.

## Verification

- Value-repository characterization covers exact forecast round-trip and an
  invalid outer payload.
- Existing malformed forecast, rollover, scorecard and setup tests remain
  unchanged.
- Focused forecast, setup and lifecycle selection: 63 passed.
- Full repository suite: 651 passed.
- Ruff and all frozen compatibility contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- The frozen v0.12.26 persistence contract remains unchanged.
- `README.md` remained unchanged.
