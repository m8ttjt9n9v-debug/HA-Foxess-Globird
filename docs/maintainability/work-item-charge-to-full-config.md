# Work item — typed charge-to-full compatibility configuration

## Scope

Migrate the EV controller and integration-owned dashboard switch to one typed
representation of the charge-to-full request while retaining the legacy mapped
Home Assistant helper as an upgrade fallback.

## Existing contract

- Presence of `ev_charge_to_full_enabled` makes the HEO-owned value
  authoritative, including an explicit false value.
- If that key is absent, a mapped legacy helper requests charge-to-full only
  while its state is exactly `on`.
- The first HEO-owned switch action removes the legacy mapping and persists the
  new boolean key.
- Automatic completion clears both the legacy mapping and HEO-owned request.

## Invariants and non-goals

- Preserve the exact precedence above and the switch's displayed state.
- Preserve update ordering, config-entry persistence and immediate controller
  reconciliation.
- Preserve all paid-grid eligibility, timeout, stop and Safety Lock behavior.
- Do not migrate charge-to-full duration or any broader EV policy in this item.
- Do not change serialized keys, entities, services or config-entry versions.

Existing setup, controller and switch lifecycle tests plus pure parser cases
are the characterization. Rollback is a code revert with no data migration.

## Outcome

The EV controller and dashboard switch now share the typed precedence model.
Direct runtime raw reads fell from 81 to 79, while the legacy mapping remains
preserved until an HEO-owned action deliberately supersedes it.

Validation completed with 523 tests, repository-wide Ruff, configuration and
persistence contracts, and the unmodified v0.12.26 previous-release rehearsal.
