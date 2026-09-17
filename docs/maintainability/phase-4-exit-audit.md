# Phase 4 exit audit — canonical read model and presentation

## Decision

Phase 4 is complete. Public entities, Fleet Summary and calculated support
diagnostics project one immutable `SiteReadModel`. Presentation code selects
and formats canonical facts; it does not own control, tariff, planning or
accumulator calculations.

## Exit-gate evidence

| Requirement | Evidence |
| --- | --- |
| Individual sensor states use one model | `EnergySensor.native_value` is a keyed lookup of `SiteReadModel.sensor_values()`. |
| Custom attributes use one model | Every attribute mapping is produced by a typed read-model projection; the frozen v0.12.26 attribute contract remains unchanged. |
| Fleet Summary uses the same facts | Fleet schema version 1 is projected by `SiteReadModel.fleet_attributes()` and retains its frozen shape and rounding. |
| Diagnostics use the same facts | Normalized telemetry, ledger, forecast, learning and actuator values are read-model projections; only entry metadata and mapped-actuator count remain wrapper metadata. |
| Shared calculations have one producer | Tariff revenue components come from the tariff engine; ZEROHERO total import comes from `HourlyWindowImportAccumulator.imported_kwh`; presentation only formats them. |
| Boundary cannot silently regress | `scripts/presentation_contract.py` statically rejects direct calculation or non-canonical calls in entity presentation and verifies the calculated diagnostic sections. |
| Compatibility remains frozen | Entity, attribute, configuration, field-usage, persistence, lifecycle and previous-release rehearsal gates all pass against v0.12.26. |

## Validation

- Full repository suite: 644 passed.
- Ruff passed for production, tests and scripts.
- Frozen entity, attribute, configuration and persistence contracts passed.
- The v0.12.26 previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.

## Scope boundary

This phase changed internal ownership and projection only. It did not change
entity IDs, unique IDs, state values, attributes, Fleet schema, configuration,
persistence, scheduling, control decisions or hardware writes.
