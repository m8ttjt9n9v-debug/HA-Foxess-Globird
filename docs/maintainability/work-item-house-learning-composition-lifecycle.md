# Work item: persisted house-learning composition lifecycle

## Problem and evidence

The source-composition formula proved that an inclusive whole-house meter
subtracts state-qualified EV power and a separately metered heater exactly
once. It did not prove that repeated sampling, partial-cycle persistence and a
Home Assistant reload preserve that separation over complete learning cycles.

## Frozen contract

- A commissioned inclusive house-load source contributes only base-house
  power to the protected-demand history after EV and heater subtraction.
- The separately metered heater contributes to its own daily history and is
  not duplicated in the base history.
- EV subtraction uses charging-state-qualified current, configured voltage and
  phase count.
- Free-window energy remains excluded from the protected base-house cycle.
- A short reload preserves both completed histories and both in-progress
  sampler accumulators.
- Sampling cadence, source freshness, Store schema and public entities remain
  unchanged.

## Implementation

One deterministic Home Assistant lifecycle fixture now replays two days at
five-minute intervals with different base, EV and heater loads on each day.
It reloads the config entry six hours into the second cycle, verifies the
stored partial accumulators, and then checks the completed runtime histories,
private Store payload and public sample-count entities.

No production code changes.

## Compatibility and rollback

This is characterization only. Revert the fixture, catalogue row and this
record to restore the preceding suite without changing runtime behaviour or
stored data.

## Acceptance evidence

- Two distinct protected base-house totals exclude EV and heater energy once.
- Two distinct heater totals remain in their separate history.
- Completed and partial sampler state survives config-entry reload.
- Runtime history, persisted payload and public sample counts agree.
- Full suite, frozen contracts, previous-release round trip and Ruff pass.

## Completion record

- [x] Existing behaviour characterized
- [x] Multi-cycle lifecycle fixture complete
- [x] Incident catalogue updated
- [ ] Independent review complete
