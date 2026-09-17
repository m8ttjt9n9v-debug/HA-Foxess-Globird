# Work item: outside-window EV stage candidates shadow

## Problem

Charge to Full, daily-ready backfill, solar spill, pre-free backfill and the
protected baseline are calculated independently but represented only by
mutable controller fields before the retained branch order selects a current.

## Change

Describe all five stages as immutable `EvStageCandidate` values after the
retained calculations and before retained selection. Each candidate records
its own eligibility, reason, current intent, command intent and any active
persistence obligation. Input rejection and battery-floor stop behavior also
receive explicit shadow results.

The retained `if/elif/select_outside_window_current` branch remains the sole
selector. Candidates cannot affect targets, state machines, saves or commands.

## Invariants

- No solar, reserve, timing, current, service-headroom or baseline formula is
  moved or rewritten.
- Charge to Full retains first priority, then daily-ready, then the retained
  pre-free/solar/baseline selector.
- Daily and pre-free state machines remain authoritative.
- Battery-floor fail-safe and stop-pending behavior remain unchanged.
- Candidate state is cycle-local, unpublished and unpersisted.

## Verification

- Existing live controller scenarios assert shadow parity for all five stages.
- Existing battery-floor, unavailable-input, stop, restart and command-order
  tests remain authoritative.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this shadow-only commit; runtime ownership never moved.

## Completion evidence

- Focused EV outside-window, daily-ready and lifecycle suite: `128 passed`.
- Full pytest suite: `779 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
