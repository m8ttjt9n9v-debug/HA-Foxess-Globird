# Work item — typed power telemetry configuration

## Problem and evidence

The corrected v3 inventory exposed dynamic raw reads in power-source and sign
helpers plus the coordinator constructor's listener registration. These paths
read the same mappings independently of the immutable runtime snapshot.

## Existing contract

- Grid, battery, solar and house mappings identify the source states.
- New direction fields take precedence; missing/falsy direction values retain
  the legacy/default fallback.
- Listener registration covers the same valid configured sources.
- Missing/invalid mappings remain unavailable rather than inferred.

## Invariants and non-goals

- Preserve source IDs, sign multipliers, freshness, provenance and availability.
- Preserve paired battery fallback and explicit no-solar behavior.
- Preserve the legacy `grid_import_positive` fallback.
- Do not change telemetry timing, normalization policy or controller behavior.

## Deliverables

- Immutable typed power-source mappings and effective direction projections.
- Telemetry assembly and listener registration consume only that snapshot.
- Characterization covers source coercion and legacy/falsy direction fallback.

## Compatibility and rollback

No serialized key or migration changes. Rollback restores raw reads against the
same config entry without data conversion.

## Acceptance evidence

Focused configuration/telemetry/setup tests, full suite, Ruff, all frozen
contracts and the v0.12.26 previous-release rehearsal must pass.

## Outcome

- Grid, signed-battery, solar and house power mappings now live in one immutable
  `PowerSourceSettings` snapshot.
- Telemetry normalization and state-listener registration consume the snapshot;
  effective direction properties retain explicit, default and legacy boolean
  behavior.
- Raw runtime configuration operations fell from 12 to 8; dynamic operations
  fell from 11 to 8. The additional reads are now at the parser boundary.
- Focused configuration/telemetry/setup/usage tests: 132 passed.
- Complete regression suite: 604 passed.
- Ruff, all generated/frozen contracts and the v0.12.26 previous-release
  rehearsal passed.
