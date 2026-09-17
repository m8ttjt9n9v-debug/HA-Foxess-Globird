# Phase 4 — canonical read model and presentation

## Purpose

Phase 4 creates one immutable `SiteReadModel` from coordinator-owned
telemetry, accounting, planner and controller state. Individual entities,
diagnostics and Fleet Summary will project that model rather than independently
recalculating the same public concepts.

## Compatibility contract

- Entity IDs, unique IDs, state values, attributes, units and availability do
  not change.
- Fleet Summary schema version 1 and its rounding remain stable.
- Candidate sellable energy remains visible even when EV priority withholds
  the effective export plan; planned export remains hidden in that state.
- Presentation receives no control, scheduling, persistence or hardware-write
  authority.
- Read-model extraction is incremental; each consumer seam remains separately
  revertible and characterization-tested.

## Current evidence

The first seam introduces a frozen `SiteReadModel` for the core site summary.
It is now the single projection source for Fleet Summary and 20 corresponding
individual sensor states covering operating status, normalized site power,
forecast/measured cost, prior-day scorecard, ZEROHERO export visibility and EV
status. Existing Fleet-specific rounding and individual-state precision remain
deliberately distinct projections of the same raw model values.

The second seam adds frozen cost and scorecard submodels. Estimated Net Cost
attributes, all four prior-day scorecard entities and redacted forecast
diagnostics now share the same facts already used by Fleet Summary; accounting,
forecast and feedback calculations remain with their existing producers.

The third seam adds a frozen learning/occupancy submodel shared by learning
entities, occupancy and Status attributes, Fleet sample counts and redacted
diagnostics. Sampling, learning selection and occupancy policy remain unchanged.

The fourth seam adds a frozen EV state submodel for all EV entity states and
Fleet EV summary values. It preserves missing-controller defaults and active
session start precedence without moving EV control or command behavior.

The fifth seam completes cost entity-state projection through the existing
cost submodel, retaining all established state rounding.

Work-item evidence:

- [core SiteReadModel projection](work-item-core-read-model.md)
- [accounting and scorecard read model](work-item-accounting-read-model.md)
- [house learning and occupancy read model](work-item-learning-read-model.md)
- [EV entity-state read model](work-item-ev-state-read-model.md)
- [cost entity-state read model](work-item-cost-state-read-model.md)

## Work packages

1. Inventory every presentation calculation and map its authoritative producer
   and consumers.
2. Move core site, plan, cost and Fleet values into the immutable read model.
3. Move accounting and scorecard attributes without duplicating tariff
   arithmetic.
4. Move EV, learning and controller diagnostics as typed nested projections.
5. Project redacted support diagnostics from the same model while retaining
   redaction and support-only evidence.
6. Add parity contracts proving entities, attributes, diagnostics and Fleet
   cannot disagree about a shared concept in one model snapshot.

## Exit gate

Individual entities, diagnostics and Fleet Summary project one immutable read
model; presentation code contains no business calculation; every shared concept
has one producer; and frozen entity, attribute, Fleet, lifecycle and
previous-release contracts remain unchanged.

## Rollback

Each projection seam is a behavior-preserving internal refactor with no
serialized-data change. Reverting a seam restores its former direct projection
without migration or persistence rollback.
