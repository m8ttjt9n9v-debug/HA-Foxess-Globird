# Work item: EV battery-floor transition

## Change

Replace the characterized outside-window battery-floor mutation block with one
pure immutable transition covering daily and pre-free session cleanup, targets,
ownership, stop intent, candidate diagnostics and the retained public reason.

## Invariants

- Charge to Full eligibility remains outside and before this transition.
- Charging feedback creates a fresh stop obligation; stopped feedback retains
  any pre-existing obligation exactly as before.
- The existing bounded stop reconciler remains the only command path.
- No policy threshold, command order, persistence schema or public contract
  changes.

## Verification

- Pure tests cover charging and already-stopped feedback.
- The pre-extraction end-to-end battery-floor trace remains authoritative.
- Full pytest, Ruff, contracts and previous-release rehearsal must pass before
  local commit.

## Rollback

Revert this commit to restore the identical mutation block in the controller.

## Completion evidence

- Focused pure and end-to-end battery-floor suite: `4 passed`.
- Full pytest suite: `818 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
