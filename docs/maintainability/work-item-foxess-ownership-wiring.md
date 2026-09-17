# OM-704B — Wire pure FoxESS retained-ownership evaluation

## Problem and evidence

OM-704A froze forced-mode ownership decisions and their explicit reset,
checkpoint and publication obligations. The active controller still mixed that
decision tree with repository and manual-controller effects.

## Existing contract

Matching retained sessions continue. Self Use with a retained obligation does
not erase it even when unrelated evidence is degraded. Self Use without an
owner safely resets degraded automatic sessions, persists both idle payloads,
marks both stores valid and checkpoints manual diagnostics before publication.
Unowned forced modes remain held as unknown or external according to evidence.

## Invariants

- Decision inputs are captured once before any ownership mutation.
- Reset persistence and manual checkpoint ordering remain unchanged.
- No external forced mode is adopted.
- Status, reason, action clearing and hold behavior remain exact.
- Charge/export policy and command execution remain untouched.

## Non-goals

- Do not alter Store codecs or degraded-status classification.
- Do not combine ownership with session-transition planning.
- Do not change manual diagnostic restore behavior.
- Do not extract EV control in this seam.

## Deliverables

- The controller invokes one immutable ownership evaluator.
- The controller executes only the returned persistence/checkpoint obligations.
- The duplicate inline ownership decision tree is removed.

## Compatibility

No entity, attribute, configuration field, Store payload, service payload,
reason, timer or retry contract changes. Existing missing/malformed-store,
external-mode, restart and safe-checkpoint fixtures exercise the wired path.

## Test plan

- Matching automatic/manual retained ownership.
- Self Use plus unrelated degraded evidence.
- Safe reset/checkpoint ordering and persisted idle payloads.
- Unknown and verified external forced modes across reload.
- Full lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert this wiring commit. The pure OM-704A evaluator may remain unused. No
stored data or state conversion is involved.

## Acceptance evidence

- 125 focused ownership, persistence, diagnostics and lifecycle tests passed.
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
