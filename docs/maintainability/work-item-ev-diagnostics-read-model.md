# Work item — EV support diagnostics read model

## Problem

Support diagnostics independently traversed the EV controller for the same
status, targets, reconciliation, recovery, solar-spill and pre-free facts used
by EV entities. That left two presentation paths capable of drifting.

## Change and preserved behavior

`EvReadModel.actuator_diagnostics()` now projects the existing EV portion of
the redacted actuator diagnostics. The diagnostics entry point still derives
the fallback EV gate from runtime configuration when no controller exists, so
disabled, uncommissioned and safety-gated sites retain their established
explanations. No control decisions, commands or diagnostic keys changed.

## Verification

- Exact-value characterization covers the active-controller diagnostic map.
- Missing-controller characterization covers the configuration-derived gate
  and unavailable defaults.
- Focused read-model and diagnostics setup suite: 51 passed.
- Full repository suite: 635 passed.
- Ruff and the frozen entity, attribute, configuration and persistence
  contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.
