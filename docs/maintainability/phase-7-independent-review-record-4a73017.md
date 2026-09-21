# Phase 7 independent review record

This record is a copy of `phase-7-independent-review-record-template.md` for
the exact Phase 7 candidate. The reviewer did not implement any commit in the
reviewed range.

## Candidate identity

- Baseline commit: `4838e518e308fa452a2de46b0b1a969298b31120`
- Candidate commit: `4a73017f90bd11813570ffda6b8c465851697f89`
- Reviewer: Codex, independent fresh-context reviewer
- Reviewer independence statement: The review used a detached clean clone and
  an immutable `git archive` of the candidate. No commit in the reviewed range
  was implemented or modified by the reviewer. No push, release or deployment
  was performed.
- Review start and completion dates: 2026-09-21 to 2026-09-21 (Australia/Sydney)
- Host and Python/Home Assistant test environment: Darwin 25.5.0 arm64;
  Python 3.14.7; pytest 9.0.3; Home Assistant 2026.8.3; Ruff 0.16.5.

The candidate checkout was detached at the exact hash and had no uncommitted
files. The review also inspected the candidate's actual controller, planner,
adapter, typed-persistence and lifecycle code rather than treating passing
tests as proof of equivalence.

## Mechanical verification

| Gate | Result | Evidence or output reference |
| --- | --- | --- |
| Candidate hash and clean checkout | Pass | `test "$(git rev-parse HEAD)" = "4a73017f90bd11813570ffda6b8c465851697f89"`; `test -z "$(git status --porcelain)"`; both passed. |
| Full repository suite (expected 956) | Pass | `pytest -q` from the clean detached candidate: `956 passed in 57.61s`. The immutable archive independently also passed 956 tests. |
| Frozen compatibility contracts (expected 24) | Pass | `pytest -q tests/test_*contract*.py`: `24 passed in 2.87s`. |
| Current → `v0.12.26` → current round trip | Pass | `python -m scripts.previous_release_rehearsal --tag v0.12.26`: two isolated cases, each `1 passed`. |
| Controller boundary contract | Pass | `python scripts/controller_boundary_contract.py --check`: exit 0. |
| Persistence boundary contract | Pass | `python scripts/persistence_boundary_contract.py --check`: exit 0. |
| Ruff | Pass | `ruff check custom_components tests scripts`: `All checks passed!` (Ruff 0.16.5). |
| Range diff check | Pass | `git diff --check 4838e518e308fa452a2de46b0b1a969298b31120..4a73017f90bd11813570ffda6b8c465851697f89`: exit 0. |

## Manual invariant review

| Invariant | Result | Evidence and reasoning |
| --- | --- | --- |
| Safety Lock causes no hardware call or retry consumption | Pass | `active.py:117-186`, `ev_active.py:442-676`, and `manual_test.py:433-485` gate writes before adapters and preserve retry state. Lifecycle cases `test_safety_lock_blocks_all_commands_across_reload`, `test_safety_lock_blocks_persisted_manual_restore_on_setup_and_unload`, and the EV safety-lock/recovery cases assert zero service calls. |
| Ownership and sign gates fail closed | Pass | `planner/foxess_gate.py`, `planner/foxess_ownership.py`, `ev_adapter.py:125-150`, and controller gate paths were traced. `test_owner_and_sign_gate_reconfiguration_is_atomic`, cloud-owner EV cases, and external-force lifecycle cases assert no unauthorized FoxESS command. |
| Stale, missing, contradictory and malformed evidence fail safely | Fail | Missing/unavailable and contradictory ownership cases are handled by `foxess_observation_adapter.py`, `ev_observation_adapter.py`, and the lifecycle harness. However, FoxESS numeric state conversion accepts negative and nonfinite values (`foxess_observation_adapter.py:105-125`), creates an observation at `:68-73`, and the active controller passes it into `charge_session.py:297-302` / `export_session.py:226-231`; `planner/foxess.py:164-170` then raises instead of returning a fail-closed unavailable/recovery result. The empty timestamp case in `planner/ev_outside_window.py:315-327` also raises on malformed evidence. Findings P1-002 and P2-002 record these gaps. |
| Charge, export, manual-test and EV obligations survive reload | Pass | Typed repositories and lifecycle transitions were traced through `active.py`, `ev_active.py`, `manual_test.py`, `planner/charge_session.py`, `planner/export_session.py`, `planner/ev_persistence.py`, and their save-before-execute paths. The lifecycle harness covers active/starting/stopping reloads, manual restoration, EV backfill/recovery, and malformed seeds; the previous-release round trip also restores retained obligations with zero hardware calls. |
| External forced modes are never silently adopted | Pass | `planner/foxess_ownership.py` distinguishes verified ownership from external force; `active.py:502-542` holds degraded ownership until safe feedback. `test_active_export_rejects_external_force_charge_across_reload`, `test_completed_charge_does_not_adopt_external_forced_mode_across_reload`, and malformed/missing ownership fixtures pass. |
| EV priorities, boundaries, feedback and battery floor are preserved | Fail | EV collision selectors, exact-boundary takeover, current-ramp feedback and reserve transitions are covered by `ev_candidates.py`, `ev_active.py`, and the lifecycle harness. The candidate nevertheless adds a new configurable outside-window battery reserve and new stop behavior (`ev_active.py:1438-1465`) relative to the frozen baseline. This violates the no-new-policy/configuration and unchanged battery-floor contract; see P1-001. |
| Service payload, order, delay and retry behaviour are preserved | Pass | `foxess_adapter.py:50-92` and `ev_adapter.py:57-132` were inspected for domains, payloads, blocking calls, ordering, locks, delay and exceptions. FoxESS plans preserve clear-opposite → power → mode order and the five-second restore/force-mode delay; EV plans preserve limit → current → switch and partial execution state. Lifecycle traces assert the concrete ordered calls and bounded retries. The FoxESS partial-exception diagnostic gap is recorded separately as P2-003. |
| Store keys, versions, privacy and payloads are unchanged | Pass | `docs/maintainability/persistence-contract-v0.12.26.json`, `persistence.py`, typed codecs, and all controller save/load paths were compared. The 13-store contract remains private/version 1, EV payload round trips are exact in `tests/test_ev_persistence.py`, and the release rehearsal passes. |
| Entity, attribute, config and Fleet contracts are unchanged | Fail | Entity/read-model/Fleet contract tests pass and no entity/read-model production files changed in the range. The configuration contract does not remain unchanged: the candidate changes the declared field set from 124 to 125 by adding `ev_outside_battery_reserve_percent`, with schema/default/validation and runtime use in `config_flow.py`, `field_catalogue.py`, and `ev_active.py`. The baseline-to-candidate key diff deterministically shows that added key. See P1-001. |
| Only adapters can issue hardware service calls | Pass | Planner modules contain no Home Assistant imports/service calls; controller boundary and persistence boundary scripts pass. Hardware service calls are confined to `foxess_adapter.py`, `ev_adapter.py`, and the existing service-registration layer. |
| No Phase 8 scheduling or cadence change entered the candidate | Pass | `active.py` and `ev_active.py` retain independent 30-second schedules; no cross-controller serialized/coalescing scheduler was added. The existing EV per-controller lock remains local to reconciliation and is not a Phase 8 cycle-request scheduler. |

## Findings

| ID | Severity | File/line | Violated invariant | Reproduction or evidence | Resolution commit | Re-review result |
| --- | --- | --- | --- | --- | --- | --- |
| P1-001 | P1 | `custom_components/home_energy_orchestrator/const.py:81,210`; `config_flow.py:677-680,1536-1541,2086-2088,2254`; `field_catalogue.py:72`; `ev_active.py:1442-1465` | Configuration fields and EV battery-floor behaviour remain unchanged; no new policy/configuration enters Phase 7 | The baseline config contract declares 124 fields; the candidate declares 125 and adds `ev_outside_battery_reserve_percent`. `diff -u` of the sorted `declared_config_keys` shows the added key. The candidate also introduces the reserve gate and stop transition. This is a public schema and behaviour change inside the reviewed range, despite the packet freezing both. | None; unresolved in candidate | Not re-reviewed; acceptance blocked |
| P1-002 | P1 | `foxess_observation_adapter.py:105-125`; `active.py:197-205,270-300`; `planner/foxess.py:164-175`; `planner/charge_session.py:297-302`; `planner/export_session.py:226-231` | Ambiguous/malformed feedback fails closed and retained restoration obligations remain live | `_power_state_kw(SimpleNamespace(state="-1", unit="kW"))` returns `-1.0`; a `FoxessObservation("Self Use", -1.0, 0.0)` reaches `plan_foxess_commands` and raises `ValueError("charge_power_kw must be finite and non-negative")`. The same converter accepts `nan`. The active controller has no catch converting this into `foxess_feedback_unavailable`/recovery, so the reconciliation task exits before a safe transition. The existing adapter test only covers textual unavailable/non-numeric states. | None; unresolved in candidate | Not re-reviewed; acceptance blocked |
| P2-001 | P2 | `ev_observation_adapter.py:99-109,248-257` | Ambiguous/nonfinite EV current feedback fails closed | `_current_a(SimpleNamespace(state="nan", unit="A"))` returns `nan`; `EvFeedbackSnapshot.actual_current_result` accepts it because it checks only `None` and `< 0`, returning `(nan, True)`. Some downstream planners validate or fall back, but the immutable feedback boundary is marked valid and diagnostics/other consumers can receive nonfinite current. | None | Not re-reviewed |
| P2-002 | P2 | `planner/ev_outside_window.py:315-327`; `ev_active.py:611-624` | Malformed telemetry evidence fails closed without an exception from the immutable boundary | Calling `evaluate_solar_spill_telemetry` with numeric powers, valid flags and empty `grid_source_updated_at=()` / `battery_source_updated_at=()` raises `ValueError: max() iterable argument is empty` at `max(timestamps)`. The current facade catches `ValueError` in one planning path and returns `ev_planning_inputs_invalid`, so this is bounded rather than an observed write, but the pure boundary is not total for malformed evidence and has no deterministic regression for the empty provenance case. | None | Not re-reviewed |
| P2-003 | P2 | `foxess_adapter.py:50-61`; `active.py:292-302` | Ordered command traces and exception behaviour remain diagnosable after partial execution | `FoxessServiceAdapter.async_execute` appends actions only after each service returns and has no `last_executed` field. If a two-command plan successfully writes the first command and the second service raises, `async_execute` raises without returning the partial trace; `ActiveFoxessController` assigns `last_actions` and increments `writes_performed` only after the whole await returns. EV has an explicit partial-trace test (`tests/test_ev_adapter.py:77-101`), but FoxESS has no equivalent test. | None | Not re-reviewed |

Every P0/P1 finding is unresolved and therefore blocks acceptance under the
packet's acceptance rule. No correction was implemented during this review.

## Residual risks

- No live clean-instance install/upgrade, pilot soak, remote-topology soak or
  deployment was performed; those are later programme gates.
- The deterministic suite and release rehearsal pass, but they do not cover the
  invalid FoxESS negative/nonfinite numeric path or empty solar timestamp
  provenance path identified above.
- The direct public repository has this review record as the only review output;
  no implementation, release, tag, push or deployment was performed.

## Decision

- [ ] **Accepted** — all checklist items pass, no P0/P1 remains, and residual
  risks are explicitly recorded.
- [x] **Rejected** — one or more invariant, evidence or independence gate
  failed.
- [ ] **Incomplete** — review stopped before a valid decision.

Decision rationale: The candidate passes all required mechanical gates and most
of the lifecycle/trace review, but it violates the frozen public configuration
and battery-floor contract and has an unresolved FoxESS malformed-feedback
failure. The P1 findings have no correction or re-review, so Phase 7 cannot be
accepted. This review does not authorize a push, release, deployment or Phase 8
implementation.

Reviewer name and date: Codex — 2026-09-21

Project-owner acknowledgement and date:

Acceptance authorizes only the next programme gate. It does not authorize a
push, release, deployment or live-site command.
