# Phase 5 exit audit — versioned persistence repositories

## Decision

Phase 5 is complete. All thirteen retained Home Assistant Stores keep their
v0.12.26 keys, version, privacy and payload contracts, while every production
load and save now passes through a typed repository boundary.

## Exit-gate evidence

| Requirement | Evidence |
| --- | --- |
| Old payloads restore identically | Tariff meters, forecast feedback, learning, inverter sessions, manual diagnostics and the composite EV controller retain exact payload-shape characterization and existing restart fixtures. |
| Corrupt data fails safely | Repository envelopes reject non-mappings; domain codecs preserve their established fallback groups; malformed ownership evidence remains visible and fail closed. |
| Unfinished obligations survive restart | Inverter charge/export, manual restoration, EV reconciliation, pre-free, daily backfill and smart recovery retain lifecycle tests across active and recovery phases. |
| Stores remain separate | The frozen v0.12.26 persistence contract still reports thirteen private version-1 Stores at the same keys and owners. |
| One persistence boundary is enforced | `scripts/persistence_boundary_contract.py` rejects direct production `async_load` or `async_save` calls outside repository instances. |
| Rollback is bounded | Every migrated family has a work-item rollback section and required no payload migration. |
| Release compatibility remains frozen | Entity, attribute, configuration, persistence, lifecycle and previous-release rehearsal gates all pass. |

## Validation

- Full repository suite: 662 passed.
- Ruff passed for production, tests and scripts.
- Frozen entity, attribute, configuration and persistence contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.

## Scope boundary

This phase changed persistence ownership and payload codecs only. It did not
change Store keys, Store versions, serialized field names, checkpoint timing,
controller policy, command order, retries, scheduling, entities or hardware
writes.
