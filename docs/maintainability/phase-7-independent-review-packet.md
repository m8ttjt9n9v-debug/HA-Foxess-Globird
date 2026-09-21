# Phase 7 independent review packet

## Purpose

This packet lets an engineer with no implementation context review the Phase 7
controller decomposition without reconstructing the programme history. It is a
review aid, not evidence that independent review occurred.

Record the completed review in a copy of the
[candidate-bound review record template](phase-7-independent-review-record-template.md).
The template is deliberately separate from this packet so evidence and the
reviewer's decision are not mixed with implementation-authored instructions.

Review range: pre-Phase-7 commit `4838e51` through implementation candidate
`4a73017`. Review that exact commit, not a later moving `HEAD`. Documentation-
only handoff commits after `4a73017` are outside the implementation range.

Authoritative documents, in order:

1. `AGENTS.md`;
2. `docs/source-of-truth.md`;
3. `docs/port-first-development.md`;
4. `docs/maintainability/programme-rules.md`;
5. `docs/maintainability/phase-7-controller-decomposition.md`; and
6. `docs/maintainability/phase-7-exit-audit.md`.

Private site evidence is intentionally absent. A reviewer must not request or
copy hostnames, LAN addresses, credentials or identifiable incident chronology
into the public repository.

## Frozen review question

Did the extraction preserve every controller decision, reason, command,
ordering constraint, retry/delay, persistence obligation and public contract
while moving policy and transition logic behind immutable boundaries?

The review must not propose new policy, retry behaviour, scheduling,
configuration or naming. Those are separate changes requiring their own
characterization and approval.

## Mandatory invariants

- Safety Lock produces no hardware call and consumes no retry.
- Non-Local-Modbus ownership produces no FoxESS command.
- Ambiguous, stale, unavailable or contradictory evidence fails closed.
- No controller adopts an unowned forced mode.
- Charge, export, manual-test and EV obligations survive reload/restart.
- EV priority, exact-boundary takeover, current feedback and battery-floor
  behaviour remain unchanged.
- Store keys, versions, privacy and payloads remain unchanged.
- Entities, attributes, configuration fields and Fleet schema remain
  unchanged.
- Adapters remain the only hardware-service boundary.
- Phase 8 serialized scheduling is absent from the candidate.

## Review map

| Concern | Production boundary | Primary evidence |
|---|---|---|
| FoxESS observation and actuation | `foxess_observation_adapter.py`, `foxess_adapter.py` | FoxESS observation, gate, ownership, charge/export and recovery tests |
| Inverter lifecycle facade | `active.py` | `test_zerohero_active.py`, lifecycle harness charge/export/recovery fixtures |
| EV observation and actuation | `ev_observation_adapter.py`, `ev_adapter.py` | observation snapshot, mapped feedback and adapter tests |
| EV policy and priority | `planner/ev*.py` | candidate collisions, free/outside-window and reconciliation tests |
| EV lifecycle facade | `ev_active.py` | exact-boundary, battery-floor, plug-in, learning and recovery fixtures |
| Persistence | `persistence.py`, typed codecs | persistence contracts, malformed-state lifecycle cases, release round trip |
| Public projection | `read_model.py` | entity, attribute, presentation and Fleet contracts |

## Required commands

Run from a clean checkout of the candidate:

```bash
git checkout --detach 4a73017
test "$(git rev-parse HEAD)" = "4a73017f90bd11813570ffda6b8c465851697f89"
test -z "$(git status --porcelain)"
pytest -q
pytest -q tests/test_*contract*.py
python -m scripts.previous_release_rehearsal --tag v0.12.26
python scripts/controller_boundary_contract.py --check
python scripts/persistence_boundary_contract.py --check
ruff check custom_components tests scripts
git diff --check 4838e51..4a73017
```

Expected repository evidence at this candidate is 956 full-suite tests, 24
frozen contract tests and two passing release-roundtrip system cases. Test
counts are descriptive; review the assertions and command traces rather than
treating the count as proof.

The implementation candidate was also exported with `git archive 4a73017`
into a tree with no working-copy files. That exported tree separately ran
the 956-test suite, 24 frozen contracts, both static boundary checks and Ruff.
The retained-state current → `v0.12.26` → current rehearsal passed from the
clean repository immediately before the candidate commit. This reproducibility
check prepares the review input; it is not independent review approval.

## Manual review checklist

- [ ] Trace every controller exit branch to a documented gate, lifecycle or
  immutable planner result.
- [ ] Confirm planners cannot import Home Assistant or issue service calls.
- [ ] Confirm controllers cannot read `hass.states`, call `hass.services` or
  load/save raw Stores directly.
- [ ] Compare charge/export/manual/EV stored payloads with the frozen contract.
- [ ] Inspect every command executor for service domain, payload, order, delay
  and exception behaviour.
- [ ] Inspect reload/restart handling for each non-idle phase and malformed
  ownership evidence.
- [ ] Confirm EV stage priority and simultaneous-candidate collision cases.
- [ ] Confirm no public entity, attribute, config key or Fleet field changed.
- [ ] Confirm no Phase 8 lock, coalescing scheduler or cadence change entered
  the range.
- [ ] Record every finding with file/line, violated invariant, severity and a
  deterministic regression that would demonstrate it.

## Acceptance rule

Independent review is complete only when every checklist item is signed by a
reviewer who did not implement the range, all P0/P1 findings are resolved and
re-reviewed, and unresolved lower-severity findings are explicitly recorded.
Passing tests alone cannot sign this gate.

After independent approval, the next gate is a clean-instance release
candidate followed by pilot and remote-topology soak. Review approval alone
does not authorize a push, release, deployment or Phase 8 implementation.
