# Work item: EV direct runtime decision

## Change

Make the post-reconciliation outside-ownership and persistence decision
explicit. The pure result retains the established unconditional reconciliation
save and the separate second save when confirmed idle feedback releases
outside-window ownership.

## Invariants

- Reconciliation state and command plan are unchanged.
- Outside ownership releases only outside the free window, with no enabled or
  active outside policy, after confirmed feedback and with no pending command.
- The historical first save remains unconditional.
- The ownership-release save remains a distinct second persistence operation.
- Adapter execution, retry bounds, schema and public contracts are unchanged.

## Verification

- Pure tests cover every release predicate and pending-command exclusion.
- Existing bounded reconciliation and live controller tests remain authoritative.
- Full pytest, Ruff, contracts and previous-release rehearsal must pass before
  local commit.

## Rollback

Revert this commit to restore the identical post-reconciliation conditions in
the controller.

## Completion evidence

- Focused EV planner and live controller suite: `116 passed`.
- Full pytest suite: `822 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
