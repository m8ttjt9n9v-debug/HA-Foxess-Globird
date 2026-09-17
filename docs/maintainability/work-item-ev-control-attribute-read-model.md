# Work item — EV control attribute read model

## Problem

EV Control Status attributes were assembled directly in `sensor.py`, while
the corresponding entity states and Fleet values already came from the
canonical EV read model. That duplicated controller traversal, rolling-average
evaluation and missing-controller behavior across presentation surfaces.

## Change and preserved behavior

`EvReadModel.control_attributes()` now owns the complete existing public
attribute mapping. The read-model builder captures the required controller
facts once. Entity identity, state, attribute names, values, timestamps and
control behavior are unchanged. A missing EV controller still exposes exactly
`{"gate": "unavailable"}`.

The frozen attribute-contract extractor now follows the canonical EV method;
its checked contract remains unchanged.

## Verification

- Exact-value characterization covers every EV Control Status attribute.
- Missing-controller characterization freezes the one-key fallback.
- Focused read-model, entity-contract, setup and lifecycle suite: 97 passed.
- Full repository suite: 634 passed.
- Ruff and the frozen entity, attribute, configuration and persistence
  contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.
