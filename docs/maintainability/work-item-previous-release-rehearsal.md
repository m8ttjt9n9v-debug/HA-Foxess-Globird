# Work item — previous-release execution rehearsal

## Scope

Extract the immutable v0.12.26 tag and execute a current compatibility case
against that release using the installed Home Assistant test runtime. Confirm
that version-6 configuration can set up, expose its status entity and unload.

## Evidence and discovered limit

The configuration lifecycle case passes against the unmodified tag. A second
deliberate experiment with a user-renamed registry entity failed: v0.12.26
reclaimed the default entity ID. That failing experiment is recorded here and
in Phase 2, not converted into a permissive assertion or represented as a
successful full downgrade.

The safe release sequence is therefore:

1. keep presentation identity unchanged;
2. establish a compatibility-baseline release containing the registry fixes;
3. make no migration-bearing release until rollback to that baseline passes;
4. add the user-registry downgrade case to CI before any approved naming
   change ships.

## Invariants

- The extracted tag is not patched before execution.
- The rehearsal performs no network access and uses a temporary directory.
- Current integration runtime behavior and public contracts are unchanged.
- Full registry-safe rollback remains a hard gate, not an implied result.
