# OM-703F — Wire pure FoxESS export-policy evaluation

## Problem and evidence

OM-703E froze export candidate derivation, including its unusual partial-value
behavior on malformed inputs. The active controller still owned the healthy
planning formula inline.

## Existing contract

EV priority and basic bounds are published before protected-energy gathering.
Allowance is published before EV keepalive/backfill is calculated. A failure
while gathering those controller-owned inputs retains the values reached at
that point and gives a retained session the same stop/recovery opportunity.
Once inputs are gathered, the pure evaluator derives the candidate plan and
session-transition inputs.

## Invariants

- Input acquisition and partial-publication order remain unchanged.
- Latest-start, efficiency, allowance and protection formulas remain exact.
- Retained sessions continue through disabled, withheld and malformed paths.
- Session transition, persistence and command execution remain unchanged.
- No new Home Assistant state read or service call is introduced.

## Non-goals

- Do not move EV presence/cable or daily-backfill acquisition yet.
- Do not alter `advance_export_session` or command planning.
- Do not repair stale publication behavior during extraction.
- Do not change export limits, tariff semantics or EV priority.

## Deliverables

- The controller gathers legacy-ordered inputs and invokes one pure evaluator.
- The evaluator becomes authoritative for healthy export planning and all
  session-transition inputs after successful acquisition.
- The duplicate plan/start/eligibility calculation is removed.

## Compatibility

No entity, attribute, configuration field, Store payload, service payload,
reason, timer or retry contract changes. Existing export, EV-priority,
malformed-input and restart fixtures exercise the wired path.

## Test plan

- Healthy plan, latest start and automatic cap.
- EV-priority idle withholding and active-session stop.
- Battery-only, missing reservation and malformed-input paths.
- Every retained export phase across reload/restart.
- Exact service order, values, delays and persistence traces.
- Full lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert this wiring commit. The pure OM-703E evaluator may remain unused. No
stored data or state conversion is involved.

## Acceptance evidence

- 113 focused export, session, EV-priority and lifecycle tests passed.
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
