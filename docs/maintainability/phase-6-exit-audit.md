# Phase 6 exit audit — accounting and coordinator extraction

## Decision

Phase 6 is complete. `EnergyCoordinator` is now a Home Assistant lifecycle,
scheduling and publication facade. Telemetry acquisition, meter advancement,
daily accounting, forecasting, retailer scorecard matching and house learning
are owned by explicit immutable service boundaries.

## Exit-gate evidence

| Requirement | Evidence |
| --- | --- |
| Coordinator owns no domain algorithm | Forecasting, accounting projection and window state, meter cycles, learning cycles and scorecard matching are delegated to `planner` services with immutable inputs and results. |
| Raw Home Assistant state access is isolated | `telemetry_adapter.py` owns state lookup, unit conversion, freshness and timestamp capture. `scripts/coordinator_boundary_contract.py` rejects direct `hass.states` access in the coordinator. |
| Store access remains repository-owned | The Phase 5 persistence-boundary contract still rejects direct production loads or saves outside typed repositories. |
| Recorded-day behavior is frozen | `phase6_recorded_day.json` replays a sanitized 24-hour day in five-minute steps across free charging, solar, boosted export, shoulder usage and the local-midnight reset. The identical fixture passes against both pre-extraction commit `0cb1123` and the extracted implementation. |
| Persistence and hardware effects are visible | The replay freezes write counts for all affected repositories and proves zero Home Assistant hardware service calls. It produces one 19.64 kWh learned daily sample. |
| Release compatibility remains frozen | Entity, attribute, field, configuration, presentation and persistence contracts pass, as does the previous-release rehearsal against `v0.12.26`. |

## Extracted seams

The work was kept independently reversible:

1. tariffed optimistic forecast calculation;
2. daily accounting projection and tariff-window state;
3. daily/window meter cycle;
4. house learning cycle;
5. telemetry acquisition and normalization boundary;
6. retailer scorecard matching; and
7. coordinator state-read isolation.

The coordinator is 1,164 lines at this gate, down from the pre-extraction
facade while retaining unchanged lifecycle and compatibility wiring.

## Validation

- Full repository suite: 681 passed.
- The 24-hour recorded-day replay passed in isolation.
- The unchanged replay also passed against pre-extraction commit `0cb1123` in
  a detached temporary worktree.
- Ruff passed for production, tests and scripts.
- Frozen entity, attribute, field, configuration, presentation and persistence
  contracts passed.
- The coordinator and persistence boundary contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.

## Compatibility exception

The thirteen `Store` objects remain constructed in the coordinator. Their
source owner, attributes, keys, versions and privacy flags are part of the
frozen v0.12.26 persistence contract. Moving those constructors would create a
compatibility-surface change without improving runtime safety. All load, save,
validation and serialization behavior is nevertheless repository-owned.

## Scope boundary

This phase changed internal ownership only. It did not change scheduling,
controller policy, entities, attributes, configuration fields, Store keys,
Store versions, payloads, checkpoint cadence, hardware commands or service-call
order. Controller decomposition remains Phase 7 work.
