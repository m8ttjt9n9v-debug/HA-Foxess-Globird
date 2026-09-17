# Work item: EV disconnected cleanup characterization

## Purpose

Freeze the retained disconnected-EV cleanup before extracting it from the Home
Assistant controller.

## Frozen trace

- Any Charge-to-Full timer is cleared and its existing config-entry cleanup is
  requested separately.
- Daily-backfill session, stop obligation and retry state are cleared.
- Pre-free state and both outside-control flags are cleared.
- Solar-spill diagnostics report `vehicle_not_eligible` when enabled.
- The eligibility reason remains authoritative unless the separately retained
  smart-socket cleanup issues an action or diagnostic reason.

No production code changes in this work item.

## Completion evidence

- Focused direct and smart-socket disconnected traces: `2 passed`.
- Full pytest suite: `818 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
