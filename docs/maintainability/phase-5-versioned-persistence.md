# Phase 5 — versioned persistence repositories

## Purpose

Phase 5 introduces shared, typed load, fallback and save mechanics around the
existing Home Assistant `Store` objects. Stores remain separate and retain
their v0.12.26 keys, Store version, privacy flag and payload shape.

## Compatibility contract

- Existing Store constructors and storage keys remain unchanged.
- Repository code adds no payload envelope and performs no migration.
- Domain models continue to own payload parsing and semantic validation.
- Missing or invalid outer payloads restore the domain's safe empty state.
- Checkpoint thresholds and save timing remain with their existing owner until
  a separately characterized seam moves them.
- One state family is migrated and verified at a time.

## Current evidence

The first seam adds `TypedStoreRepository` and migrates the daily-import
accumulator. Its Store remains version 1 at the same private key, its serialized
dictionary is byte-for-byte equivalent as structured data, and existing
positive-flow-to-zero checkpoint timing is unchanged.

The second seam completes the tariff-meter family: daily export, peak-rate
export, free-window import, peak-window import, ZEROHERO hourly import and
ZEROHERO export now use the same mechanics while retaining their original Store
objects and independent checkpoint rules.

The third seam adds the value-returning repository variant and migrates
forecast calibration. Its existing decoder, daily rollover and write-coalescing
signature remain authoritative.

The fourth seam adds a typed composite state for house learning. It preserves
the two histories and two optional in-progress sampler payloads while leaving
sampler freshness validation with the configured runtime samplers.

The fifth seam moves charge and export session codecs into their pure session
models and routes all active-controller persistence through separate typed
repositories. Missing and malformed evidence retain their ownership-safety
distinction.

The sixth seam moves the manual-diagnostic restoration obligation into a typed
state codec and repository while preserving its valid/missing/malformed safety
status and bounded cleanup lifecycle.

Work-item evidence:

- [daily-import typed repository](work-item-daily-import-repository.md)
- [tariff-meter typed repositories](work-item-tariff-meter-repositories.md)
- [forecast-feedback typed repository](work-item-forecast-repository.md)
- [house-learning typed repository](work-item-learning-repository.md)
- [inverter-session typed repositories](work-item-inverter-session-repositories.md)
- [manual-diagnostic typed repository](work-item-manual-test-repository.md)

## Exit gate

Old payload fixtures restore identically; corrupt data fails safely; restart at
every phase retains unfinished ownership and recovery work; rollback boundaries
are documented and tested; all thirteen frozen Store contracts remain intact.

## Status

In progress. Every state family except the composite EV controller Store is
behind a typed repository boundary.
