# Work item — configuration usage metric

## Scope

Separate centralized `update_config_value(...)` calls from raw mapping access
in the machine-readable configuration inventory. Retain both records so the
mutation surface remains auditable while Phase 3 measures the raw runtime
access it is intended to remove.

## Invariants

- Preserve every existing access record and its source location.
- Classify only the existing coordinator mutation API as managed mutation.
- Treat all direct `get`, `pop`, `setdefault` and subscript operations as raw.
- Do not change integration runtime behavior or public contracts.

The reviewed generated baseline and contract tests provide the gate.

## Audit correction

The original v2 visitor recorded only named `CONF_*` arguments. Variable-key
helpers and one literal legacy-key access were therefore omitted. The v3
contract records those known coordinator-config receivers explicitly; raw
runtime access is not boundary-only until the newly visible helpers are
migrated.
