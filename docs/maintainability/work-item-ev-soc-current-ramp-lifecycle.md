# Work item: EV SoC/current-ramp lifecycle trace

## Problem and evidence

The EV decision-cadence boundary had focused coverage for an SoC update that
arrives while requested and actual charging current are still converging. It
did not have a full Home Assistant lifecycle case proving that the temporary
hold cannot conceal a real site service-limit breach.

## Frozen contract

- During ZEROCHARGE, an SoC-only event below the selected charge limit retains
  the existing target while requested and actual current are converging.
- The hold applies only to the allowance recalculation race; it does not relax
  the commissioned electrical service limit.
- Fresh measured site current above that limit bypasses the hold immediately
  and requests a lower charging current.
- Safety Lock/rehearsal execution emits no hardware service call.
- Target, reason, cadence, configuration and persistence contracts are
  unchanged.

## Implementation

One deterministic lifecycle fixture now sets up a real config entry, builds
the three-minute averaging evidence, publishes a house-load and vehicle-SoC
event during a 3 A → 16 A current ramp, and then publishes an 81 A site-current
measurement against an 80 A commissioned limit. It verifies the retained
16 A transition hold followed by immediate curtailment planning, public target
projection and an empty hardware-call trace.

No production code changes.

## Compatibility and rollback

This is characterization only. Revert the fixture, catalogue row and this
record to restore the preceding suite without changing runtime behaviour or
stored data.

## Acceptance evidence

- SoC-only current-ramp transition hold passes at system level.
- Fresh service-limit overrun bypasses that hold and lowers the target.
- Rehearsal execution records the intended current/limit actions while making
  zero Home Assistant service calls.
- Full suite, frozen contracts, previous-release round trip and Ruff pass.

## Completion record

- [x] Existing behaviour characterized
- [x] System lifecycle fixture complete
- [x] Incident catalogue updated
- [ ] Independent review complete
