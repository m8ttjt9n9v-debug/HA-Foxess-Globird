# Phase 7 correction independent re-review record

This is a new review record for the corrected Phase 7 implementation
candidate. It does not edit or replace the rejected review recorded in
`phase-7-independent-review-record-4a73017.md`.

## Candidate identity and independence

- Original rejected candidate: `4a73017f90bd11813570ffda6b8c465851697f89`
- Correction candidate: `67a5ab71744e5ed670b88faf278f86d3d4d5a490`
- Reviewer: Codex, independent fresh-context reviewer
- Reviewer independence statement: The reviewer did not implement or modify
  any commit in the reviewed range. Review was performed from a new local clone
  detached at the exact correction candidate. The existing working checkout
  and the original rejected record were not modified during verification.
- Review date: 2026-09-21 (Australia/Sydney)
- Environment: Darwin 25.5.0 arm64; Python 3.14.7; pytest 9.0.3; Home Assistant
  2026.8.3; Ruff 0.16.5.

The required repository instructions, rejected review record and correction
packet were read in the specified order. The public source-of-truth,
port-first, system-requirements and programme-rules documents were also
reviewed. Private operational evidence was consulted locally only; no private
hostname, address, credential or incident chronology is reproduced here.

## Mechanical verification

All commands were run from the detached clone at the exact candidate. The
checkout was clean both before and after verification.

| Gate | Result | Evidence |
| --- | --- | --- |
| Candidate hash and clean detached checkout | Pass | `git rev-parse HEAD` was exactly `67a5ab71744e5ed670b88faf278f86d3d4d5a490`; `git status --porcelain` was empty. |
| Full repository suite | Pass | `pytest -q`: `972 passed in 58.66s`. An earlier equivalent invocation through the same virtual-environment interpreter also passed all 972 tests. |
| Frozen compatibility contracts | Pass | `pytest -q tests/test_*contract*.py`: `24 passed in 2.80s`. |
| Current -> `v0.12.26` -> current round trip | Pass | `python -m scripts.previous_release_rehearsal --tag v0.12.26`: two isolated cases, each `1 passed`. |
| Controller boundary contract | Pass | `python scripts/controller_boundary_contract.py --check`: exit 0. |
| Persistence boundary contract | Pass | `python scripts/persistence_boundary_contract.py --check`: exit 0. |
| Ruff | Pass | `ruff check custom_components tests scripts`: `All checks passed!`. |
| Correction range diff check | Pass | `git diff --check 4a73017..67a5ab7`: exit 0. |

These results were treated as assertion evidence only. The production paths,
the two relevant historical commits and their surrounding lifecycle code were
inspected independently.

## Finding-by-finding re-review

| Finding | Result | Implementation evidence and reasoning |
| --- | --- | --- |
| P1-001: outside-window EV battery reserve classification and extraction | Pass | `07153bd` is a separately recorded critical bug correction, not an accidental Phase 7 extraction. The confirmed failure class is unintended paid import, which is a Critical bug exception under `programme-rules.md`. The public changelog, updated configuration contract, config validation, work-item history and regression/lifecycle cases all identify the new `ev_outside_battery_reserve_percent` key, its 20% default, the inclusive reserve boundary, the `ev_battery_reserve_reached` reason and the paid Charge-to-Full exception. The later extraction `2c86327` replaces only the inline predicate with `OutsideBatteryReserveEvidence` and `outside_battery_reserve_reached` (`planner/ev_outside_state.py:75-92`), while the facade still invokes the same unchanged abort transition (`ev_active.py:1442-1472`; `planner/ev_outside_state.py:245-287`). Direct comparison with the pre-extraction expression and an independent truth-table probe confirmed identical results for missing SoC, non-finite SoC, below/equal/above-reserve SoC and both paid-override states. The configuration key/default, reason, session cleanup, stop intent, target, persistence transition and Charge-to-Full exception are unchanged by the extraction. |
| P1-002: malformed FoxESS force-power feedback | Pass | `_power_state_kw` now accepts only finite, non-negative converted power (`foxess_observation_adapter.py:106-116`). Both charge and discharge values use that boundary, so `-1`, `nan`, `inf` and `-inf` become `None`. Neither the automatic observation (`:58-75`) nor manual observation (`:31-45`) can then be constructed. `ActiveFoxessController.async_reconcile` detects the absent observation before ownership or policy planning, moves retained charge/export obligations through the existing source-unavailable recovery transition, persists required changes and returns with reason `foxess_feedback_unavailable` (`active.py:197-205,476-487`). No adapter is constructed or executed on this path, attempts are not consumed and no service call is made. Manual test start also rejects the absent manual observation before obtaining/executing its adapter. The planner's defensive validation remains in place. |
| P2-001: non-finite EV-current feedback | Pass | `_current_a` now checks the converted value with `isfinite` and returns `None` for `nan`, `inf` and `-inf` (`ev_observation_adapter.py:248-258`). The state-qualified charging path consequently returns `(0.0, False)` rather than `(nan, True)` (`:98-109`). The established non-charging semantic remains a valid zero-current observation because current feedback is not authoritative when the charging state is not `charging`. |
| P2-002: empty solar-spill timestamp provenance | Pass | `evaluate_solar_spill_telemetry` retains grid and battery provenance separately and requires each effective source tuple to be non-empty before timestamp arithmetic (`planner/ev_outside_window.py:304-333`). Empty grid, empty battery and both-empty cases therefore deterministically return `telemetry_valid=False`; short-circuit evaluation prevents `max()` or `min()` from running on an empty tuple. The retained reconstructed diagnostic power values are still returned, with no actuator authority. |
| P2-003: FoxESS partial-command diagnostics | Pass | `FoxessServiceAdapter` resets `last_executed` at the start of an authorized non-empty plan and updates it only after each command, including that command's existing delay, completes (`foxess_adapter.py:49-64,66-94`). If a later service call raises, the prior successful action remains available. Charge and export controller paths copy that trace into `last_actions`, increment `writes_performed` by exactly the successful prefix, then use a bare `raise` to preserve the original exception (`active.py:292-310,455-473`). Command construction, clear-opposite/power/mode order, five-second delays, persisted attempt state and retry timing are untouched. The added bookkeeping contains no await or command and cannot reorder the plan. |

## Scope and compatibility audit

The production diff from `4a73017..67a5ab7` changes only:

- `active.py` for partial FoxESS execution diagnostics;
- `foxess_adapter.py` for the successful-command prefix;
- `foxess_observation_adapter.py` for finite/non-negative power feedback;
- `ev_observation_adapter.py` for finite current feedback; and
- `planner/ev_outside_window.py` for non-empty provenance checks.

The commits between the rejected candidate and the correction commit otherwise
contain review/soak documentation and tests. Inspection found no change to
configuration keys/defaults/validation, entity IDs or attributes, Fleet
schema, Store keys/versions/privacy/payloads, controller cadence, Phase 8
scheduling, policy priority, command payloads, command order, delays, retry
state or exception propagation. The accurate partial-write values exposed
through the existing `last_actions` and `writes_performed` diagnostics are the
intended P2-003 correction, not a schema expansion.

The P1-001 configuration change predates the rejected candidate and is the
explicitly approved critical-bug exception described above. Its extraction is
outside the correction diff and remains behaviorally equivalent.

## Findings

No new P0, P1, P2 or P3 finding was identified. All five rejected-review
findings are resolved or, for P1-001, correctly reclassified and verified.

## Residual risks

- No clean-instance install/upgrade, operational rollback, pilot soak,
  remote-topology soak or remaining-site rollout was performed. Those remain
  later programme gates.
- No release, deployment or live hardware command was performed. Deterministic
  evidence cannot substitute for the separately required operational soak.

## Decision

- [x] **Accepted** — every correction and scope disposition passes independent
  re-review, no P0/P1 remains, and residual risks are recorded.
- [ ] **Rejected** — one or more invariant, evidence or independence gate
  failed.
- [ ] **Incomplete** — review stopped before a valid decision.

Decision rationale: The candidate fixes the four malformed-evidence and
partial-diagnostic defects without introducing an unrelated controller or
public-contract change. P1-001 is supported as a separately approved critical
bug exception, and its later pure extraction preserves the established reserve
behavior exactly. Phase 7 is accepted for the next programme gate only.

Reviewer name and date: Codex — 2026-09-21

Project-owner acknowledgement and date:

Acceptance does not authorize a push, tag, release, deployment, Phase 8 change
or live-site command.
