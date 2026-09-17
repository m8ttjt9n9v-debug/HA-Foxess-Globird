# OM-703D — Wire pure FoxESS charge-policy evaluation

## Problem and evidence

OM-703C froze free-window charge eligibility as immutable input and output.
`ActiveFoxessController` still duplicated those calculations inline before
calling the retained charge-session transition.

## Existing contract

Policy derives the bounded charge maximum, source capability, allowance, SoC
eligibility, public precondition reason, tick ownership and finish intent. The
existing `advance_charge_session` remains responsible for starting, active,
stopping and recovery transitions and for producing the ordered command plan.

## Invariants

- Public precondition reasons and charge target publication remain exact.
- Retained sessions reconcile even after enable, window or allowance changes.
- The session transition receives the same values in the same order.
- Persistence occurs only after a session transition changes retained state.
- Adapter construction, delays, service order and write counts remain exact.

## Non-goals

- Do not alter `advance_charge_session` or command planning.
- Do not extract export policy or retained ownership verification.
- Do not change allowance accounting, timing, limits or target SoC.
- Do not simplify the missing-capability/session responsibility boundary.

## Deliverables

- `_async_reconcile_charge` constructs one immutable policy context.
- The pure result becomes authoritative for pre-session derivation.
- The controller retains only transition persistence and command execution.

## Compatibility

No entity, attribute, configuration field, Store payload, service payload,
reason, timer or retry contract changes. Existing start, active, finish,
recovery and restart fixtures exercise the wired path.

## Test plan

- Eligible, disabled, target-met and outside-window idle paths.
- Missing, exhausted and negative allowance reasons.
- Wrong-mode and unconfirmed-schedule precedence.
- Active, stopping and recovering sessions across reload/restart.
- Exact service order, power values, delays and persistence traces.
- Full lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert this wiring commit. The pure OM-703C evaluator may remain unused. No
stored data or state conversion is involved.

## Acceptance evidence

- 111 focused charge, session, command and lifecycle tests passed.
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
