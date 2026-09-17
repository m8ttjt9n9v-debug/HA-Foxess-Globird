# Phase 6 — accounting and coordinator extraction

## Purpose

Reduce `EnergyCoordinator` to a Home Assistant lifecycle and scheduling facade
without changing update cadence, persisted state, service-call order, public
entities, or controller decisions. Each extraction is independently reversible
and is proved against the frozen contracts before the next seam starts.

## Current responsibility map

| Responsibility | Current owner | Target boundary |
|---|---|---|
| Home Assistant lifecycle, timers and listener notification | coordinator | coordinator facade |
| Home Assistant state lookup and unit conversion | coordinator | telemetry adapter |
| telemetry normalization and freshness | coordinator | immutable telemetry acquisition result |
| daily/window meter advancement | coordinator plus planner accumulators | accounting service |
| tariff guard, credit and daily financial projection | coordinator plus pure tariff helpers | accounting service |
| optimistic forecast assembly and scorecard matching | coordinator plus pure forecast helpers | forecast service |
| occupancy, base-load and heater-cycle sampling | coordinator plus pure learning helpers | learning service |
| Store construction and serialization | typed repositories | unchanged repository boundary |
| inverter and EV controller scheduling | setup/controller modules | explicitly unchanged in Phase 6 |

## Extraction order

1. **Forecast calculation.** Move forecast financial assembly behind an
   immutable input object. The coordinator gathers current observations and
   configuration, then consumes the pure result.
2. **Tariff/accounting projection.** Introduce immutable accounting inputs and
   outputs around tariff guard, ZEROHERO credit and daily financials. Preserve
   every reason string and unavailable fallback.
3. **Meter advancement.** Move daily/window accumulator orchestration behind a
   single accounting-cycle operation while retaining the thirteen Store
   identities and existing save coalescing.
4. **House learning.** Extract sampling eligibility and learned-budget
   composition behind immutable observations and results.
5. **Telemetry acquisition.** Keep Home Assistant state reads in one adapter;
   feed normalization with captured source observations instead of allowing
   domain code to reach `hass.states`.
6. **Facade audit.** Prove the coordinator owns only lifecycle, scheduling,
   adapter invocation, repository invocation and publication.

This order starts with the narrowest read-only calculation and leaves the
Home Assistant boundary until its consumers have explicit input contracts.

## Compatibility and rollback rules

- No scheduling or controller changes belong in this phase.
- No entity, attribute, configuration key, Store key or Store version changes.
- No additional persistence or hardware writes.
- Preserve unavailable and invalid-configuration behavior exactly.
- Keep one extraction per commit so rollback is a commit revert, not a data
  migration.
- Characterize coordinator output before replacing each seam, then add direct
  tests for the extracted immutable boundary.

## Required validation per seam

- focused unit and coordinator-characterization tests;
- lifecycle, persistence and recorded-day replay tests;
- full test suite and Ruff;
- entity, field, configuration, presentation and persistence contracts;
- previous-release rehearsal against the current known-good tag; and
- `git diff --check` with `README.md` unchanged.

## Exit evidence

Phase 6 is complete only when:

- the coordinator contains no tariff, forecasting or learning algorithm;
- raw Home Assistant state access for energy telemetry is isolated to the
  telemetry adapter;
- all Store access remains repository-owned;
- recorded-day ledger, forecast and learning traces match the pre-extraction
  fixtures; and
- persistence-write and hardware-call counts do not increase.

## Completion evidence

The technical Phase 6 exit gate was satisfied on 2026-09-18. The extracted
seams were committed separately so each remains independently reversible:

- `5752bf4` — tariffed forecast calculation;
- `a3be8f7` — daily accounting projection;
- `b5b9ee0` — accounting meter cycle;
- `177d8b9` — house learning cycle;
- `35b1c77` — telemetry acquisition boundary;
- `77b3b06` — retailer scorecard matching;
- `8e92d36` — coordinator state-read isolation; and
- `102d3eb` — accounting window state.

The [Phase 6 exit audit](phase-6-exit-audit.md) records the recorded-day replay,
frozen write counts, zero hardware calls, boundary contracts and release
compatibility evidence.
