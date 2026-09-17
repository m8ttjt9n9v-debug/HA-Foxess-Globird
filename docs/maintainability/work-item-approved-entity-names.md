# Work item — approved entity display names

## Scope

Apply the nine display names approved by the project owner on 2026-09-17.
Retain the immutable v0.12.26 baseline and allow only those explicit name
deltas in the compatibility validator.

## Invariants

- No unique ID, entity ID, state, attribute, unit, category or availability
  change.
- Existing user-assigned entity IDs and names remain user-owned.
- The other 98 catalogue names remain byte-for-byte unchanged.
- No controller, configuration, persistence or hardware behavior changes.

Catalogue, semantic, generated-reference, clean-install, registry, dashboard
and full-suite tests provide the gate. Reverting the commit restores the former
defaults without data migration.
