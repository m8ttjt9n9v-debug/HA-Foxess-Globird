# OM-703B — Wire pure FoxESS absolute-gate evaluation

## Problem and evidence

OM-703A froze the exact automatic-control gate precedence and publication
metadata in a pure, unwired evaluator. `ActiveFoxessController` still retained
the duplicate inline branch chain.

## Existing contract

Manual diagnostic ownership blocks first, followed by FoxCloud owner, observer
owner, disabled master, Safety Lock, unverified electrical directions,
incomplete actuator mapping and unavailable coordinator telemetry. The first
three outcomes clear prior `last_actions`; later outcomes retain it. Incomplete
mapping logs the existing warning. Hardware observation begins only after the
gate allows reconciliation.

## Invariants

- Gate order, reasons, warnings and action publication remain exact.
- Gate evaluation occurs before Home Assistant actuator feedback is read.
- Blocked gates cannot mutate sessions, access repositories or execute calls.
- No policy ordering, timing, persistence or adapter behavior changes.

## Non-goals

- Do not extract ownership verification, charge policy or export policy.
- Do not normalize historical `last_actions` behavior.
- Do not change `gate_status`, public entities or configuration semantics.
- Do not combine this seam with EV observation work.

## Deliverables

- `async_reconcile` constructs one immutable primitive gate context.
- The pure evaluator becomes authoritative for the absolute early-return chain.
- The duplicate inline gate branches are removed.

## Compatibility

No entity, attribute, configuration field, Store payload, service payload,
reason, timer or retry contract changes. Existing controller and lifecycle
fixtures compare the wired path against the frozen outcomes.

## Test plan

- Every blocked gate, allowed path and precedence case.
- Exact `last_reason`, retained/cleared actions and zero service calls.
- Reload/reconfiguration with retained charge and export obligations.
- Full lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert this wiring commit. The pure OM-703A evaluator may remain unused. No
stored data or state conversion is involved.

## Acceptance evidence

- 112 focused gate, automatic-control, diagnostic and lifecycle tests passed.
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
- [x] Operational soak complete where required — no policy change
