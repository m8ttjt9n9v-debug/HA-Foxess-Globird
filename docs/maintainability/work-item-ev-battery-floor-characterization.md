# Work item: EV battery-floor characterization

## Purpose

Freeze the retained automatic outside-window battery-floor abort before its
state transition is extracted from the controller.

## Frozen trace

- Paid Charge to Full remains the separately tested exception.
- At or below the configured battery floor, daily backfill and pre-free
  sessions are cleared immediately.
- Current target becomes zero and the public decision remains
  `battery_floor_reached`.
- Charging feedback creates the existing stop obligation and issues one stop
  attempt through the normal bounded stop path.
- Outside-control ownership remains active until stopped feedback is confirmed.

No production code changes in this work item.

## Completion evidence

- Focused unchanged-controller battery-floor trace: `2 passed`.
- Full pytest suite: `816 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
