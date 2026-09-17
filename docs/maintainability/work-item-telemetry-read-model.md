# Work item — canonical telemetry presentation

## Problem

Five telemetry entities and support diagnostics independently formatted the
same normalized samples. Entity attributes exposed source evidence while
diagnostics exposed a redacted count, but both traversed coordinator telemetry
directly and could drift.

## Change and preserved behavior

Immutable telemetry source and sample read models now project both surfaces
from one snapshot. Entity source IDs, raw values, units and ISO timestamps are
unchanged. Diagnostics remain redacted to `source_count`; raw entity IDs are
not added. Missing normalized telemetry still yields no telemetry attributes
and an empty diagnostic mapping.

The frozen attribute-contract extractor now follows the canonical telemetry
method; its checked contract remains unchanged.

## Verification

- Exact characterization covers entity source evidence and redacted
  diagnostics from the same sample.
- Missing-telemetry characterization freezes empty payload behavior.
- Focused read-model, setup/diagnostics and entity-contract suite: 61 passed.
- Full repository suite: 640 passed.
- Ruff and the frozen entity, attribute, configuration and persistence
  contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.
