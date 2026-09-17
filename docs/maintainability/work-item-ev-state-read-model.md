# Work item — EV entity-state read model

## Problem

Thirty-three EV entity states and the Fleet EV summary independently traversed
the active EV controller, its nested plans, timed averages, reconciliation,
recovery and learning state. The projections agreed only by convention.

## Canonical projection

`EvReadModel` now captures EV SoC/power, requested and measured current,
charge-limit feedback, timed averages, recovery and solar-spill state, pre-free
and daily-backfill plans, delivered/remaining energy and learned driving
outputs. Individual EV entities and Fleet Summary project this frozen model.

## Preserved behavior

- No EV policy, current target, plan, reconciliation, recovery, persistence or
  service call changed.
- A missing controller retains live snapshot SoC and ledger maximum power while
  exposing the existing `None`, zero, `disabled` and `unavailable` defaults.
- Active daily backfill continues to expose its frozen start instead of a newly
  calculated plan start.
- Candidate averages use one timestamp for both grid and EV windows within a
  model snapshot.
- EV Control attributes, Status attributes and support diagnostics remain on
  their existing path for the next separately reviewed seam.

## Verification

- Characterization covers every EV entity-state key.
- Explicit cases cover missing-controller defaults and active daily-backfill
  frozen-start precedence.
- Frozen sensor key extraction includes every nested read-model projection.
- Focused read-model, presentation, contract, setup, lifecycle and EV-control
  suite: 151 passed.
- Full repository suite: 633 passed.
- Ruff, frozen entity/attribute/configuration/persistence contracts and the
  v0.12.26 previous-release upgrade rehearsal passed.
- `README.md` was not changed.
