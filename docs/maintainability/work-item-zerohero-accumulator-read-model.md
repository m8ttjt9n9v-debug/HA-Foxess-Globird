# Work item — ZEROHERO accumulator presentation

## Problem

ZEROHERO Import Window was the final sensor attribute path reading coordinator
state and runtime configuration directly. It separately rounded hourly
buckets and formatted accumulator dates/timestamps outside the canonical
model.

## Change and preserved behavior

The operational read model now captures an immutable tuple of hourly import
buckets, accumulator date, last sample and configured threshold. Its attribute
projection preserves six-decimal bucket rounding, ISO formatting, insertion
order and missing-value behavior.

With this change, every public sensor state and custom attribute mapping is
owned by the canonical read model. The frozen attribute-contract generator no
longer parses `sensor.py`; it derives all mappings from canonical methods and
continues to match the unchanged baseline.

The accumulator also now owns its total through `imported_kwh`. Persistence,
coordinator checkpointing and presentation therefore consume the same
authoritative aggregate instead of independently summing hourly buckets.

## Verification

- Exact characterization covers hourly values, date, timestamp and threshold.
- Focused read-model, setup and daily-meter suite: 63 passed.
- Full repository suite: 644 passed.
- Ruff and the frozen entity, attribute, configuration and persistence
  contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.
