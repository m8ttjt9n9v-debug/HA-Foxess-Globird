# Work item — house learning and occupancy read model

## Problem

Individual learning sensors, House Occupancy State attributes, Status
attributes, Fleet Summary and redacted diagnostics independently read the
house-budget, base/heater learning, retained histories and occupancy result.
Those paths could report different evidence if one projection changed alone.

## Canonical projection

`LearningReadModel` now owns the selected house budget and model, base and
heater components, remaining budget, retained/sample counts, occupancy evidence
and the optional heater model. `SiteReadModel` projects it to all existing
public and support surfaces.

## Preserved behavior

- No sampling, P80 selection, occupancy classification, persistence or export
  reservation logic changed.
- The budget-selected occupancy remains distinct from the separately exposed
  current occupancy evidence.
- An unmapped heater retains a `None` entity value and `not_mapped` diagnostic
  model.
- Entity states, attribute names, Fleet schema and diagnostic keys are
  unchanged.
- Learning history limits and sampler-enabled evidence remain owned by the
  Status projection because they are configuration/runtime metadata, not model
  results.

## Verification

- Characterization covers all learning sensor states, occupancy attributes and
  redacted learning diagnostics.
- Frozen sensor/attribute extraction follows both canonical learning mappings
  and remaining sensor-local mappings.
- Focused read-model, presentation, entity-contract, setup/diagnostics and
  lifecycle suite: 98 passed.
- Full repository suite: 631 passed.
- Ruff, frozen entity/attribute/configuration/persistence contracts and the
  v0.12.26 previous-release upgrade rehearsal passed.
- `README.md` was not changed.
