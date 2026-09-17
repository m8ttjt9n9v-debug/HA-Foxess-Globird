# Work item — Status control read model

## Problem

The Status entity independently assembled battery-control, EV-control,
learning and runtime-configuration facts. This duplicated values already used
by Fleet, EV entities and diagnostics, and left the largest public attribute
surface outside the canonical read model.

## Change and preserved behavior

The immutable `ControlReadModel` now captures battery/EV gate, session,
automation and learning-runtime facts. `SiteReadModel.status_attributes()`
combines those facts with its existing EV and learning submodels. All 47
attribute names and values are preserved, including both legacy automatic
export remaining-energy aliases. No control, scheduling or hardware-write
logic moved.

The frozen attribute-contract extractor now follows the canonical Status
method; its checked contract remains unchanged.

## Verification

- Exact-value characterization covers all 47 active Status attributes.
- No-controller characterization freezes FoxESS and EV fallback semantics.
- Focused read-model, presentation, entity-contract, setup and lifecycle
  suite: 102 passed.
- Full repository suite: 637 passed.
- Ruff and the frozen entity, attribute, configuration and persistence
  contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.
