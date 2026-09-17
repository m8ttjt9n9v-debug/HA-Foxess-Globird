# OM-703A — Pure FoxESS absolute-gate boundary

## Problem and evidence

`ActiveFoxessController.async_reconcile` currently interleaves absolute safety
and ownership gates with controller mutation. Before inverter policy can be
extracted, the exact gate precedence and its existing publication side effects
need an immutable, side-effect-free contract.

## Existing contract

The precedence is manual diagnostic, FoxCloud owner, observer owner, master
disabled, Safety Lock, unverified electrical directions, incomplete actuator
mapping, then unavailable coordinator telemetry. The first three outcomes
clear `last_actions`; later outcomes retain the preceding value. Incomplete
mapping emits the controller warning. Passing every gate permits observation
capture but does not itself authorize a command.

## Invariants

- The evaluator cannot read Home Assistant state, storage or services.
- Gate order, reason strings and action-clearing behavior remain exact.
- No retained session, persistence obligation or controller field is changed.
- No evaluator result can execute a hardware command.

## Non-goals

- Do not wire the evaluator into production in this seam.
- Do not combine source-feedback or retained-ownership evaluation with gates.
- Do not normalize the intentionally different action-clearing behavior.
- Do not change `gate_status`, entity state or attributes.

## Deliverables

- Immutable primitive `FoxessGateContext`.
- Immutable `FoxessGateResult` carrying reason and legacy side-effect metadata.
- Exhaustive precedence, outcome and immutability characterization.

## Compatibility

This boundary is unwired and adds no entity, attribute, configuration field,
Store payload, service payload, timer, retry or runtime behavior.

## Test plan

- Every individual gate and allowed outcome.
- All gates blocked simultaneously, released one at a time in precedence order.
- Exact reason, clear-actions and mapping-warning metadata.
- Frozen dataclass enforcement.
- Full lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert this commit. Because the evaluator is unwired and side-effect-free,
rollback has no runtime or storage consequence.

## Acceptance evidence

- 90 focused pure-gate, retained-controller and lifecycle tests passed.
- Full repository suite and Ruff passed.
- All nine frozen compatibility contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` unchanged.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [x] Operational soak complete where required — not required while unwired
