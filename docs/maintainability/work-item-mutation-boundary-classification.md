# Work item — classify the central mutation boundary

## Problem and evidence

The configuration-usage inventory reported the coordinator's two deliberate
`pop`/store operations as uncontrolled runtime raw access. Those operations are
the implementation of the single mutation boundary: it updates the live mirror
and immediately rebuilds the immutable snapshot.

## Invariants and non-goals

- Keep both writes visible and frozen in the usage contract.
- Keep every caller classified as a managed mutation.
- Do not change persistence, snapshot rebuild order or runtime behavior.
- Do not exempt any other raw write from the runtime metric.

## Deliverables

- Usage-contract schema v4 with an explicit `mutation_boundary` kind.
- Classify only the two exact operations in
  `EnergyCoordinator.update_config_value` as boundary operations.
- Assert that no uncontrolled runtime raw write remains.

## Outcome

- Both central implementation writes remain inventoried as boundary operations.
- All 11 callers remain inventoried as managed runtime mutations.
- Raw runtime mapping operations fell from five to three without a production
  code change; the remaining three are read helpers requiring typed migration.
- Focused usage/configuration tests: 81 passed.
- Complete regression suite: 611 passed.
- Ruff, all generated/frozen contracts and the v0.12.26 previous-release
  rehearsal passed.
