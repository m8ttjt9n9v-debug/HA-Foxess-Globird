# Work item: outside-window EV selector shadow

## Problem

Phase 7.7 requires explicit priority selection after independent candidates are
available. The retained outside branch gives Charge to Full first priority,
then daily-ready, then combines active pre-free with solar spill, then solar
alone, and finally the protected baseline.

## Change

Add a pure selector over the immutable outside-stage candidates and run it in
shadow beside the retained `if/elif/select_outside_window_current` logic. The
shadow result records selected stage, reason and current. The retained result
still owns controller targets and command execution.

## Invariants

- Charge to Full remains above daily-ready.
- Active pre-free uses the greater of its live current and solar-spill current,
  capped at the existing physical ceiling.
- Solar spill remains above the protected baseline.
- No eligible stage still resolves to the retained zero-current protected
  baseline result.
- No runtime ownership, persistence or public contract changes.

## Verification

- Pure collision tests cover every priority boundary, both pre-free/solar
  current orderings, baseline fallback and zero-current fallback.
- Existing live Charge to Full, daily-ready, pre-free, solar and baseline
  scenarios require shadow reason/current equality with retained selection.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this shadow-only selector; retained selection remains untouched.

## Completion evidence

- Focused selector, EV outside-window and lifecycle suite: `138 passed`.
- Full pytest suite: `789 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
