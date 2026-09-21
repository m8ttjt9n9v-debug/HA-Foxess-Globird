# Work item: Phase 7 one-version rollback rehearsal

## Problem and evidence

The previous-release rehearsal proved only that `v0.12.26` could set up its
own version-6 fixture. It did not prove that current configuration data and
currently serialized controller obligations could be read after a one-version
downgrade.

## Frozen contract

- Configuration entry version 6 remains readable by `v0.12.26`.
- Charge, export and EV Store keys, versions, privacy and payload semantics do
  not change.
- Restoring retained state in observer/Safety-Lock conditions issues no
  hardware service call.
- The rehearsal runs only in an isolated extracted release tree and never
  touches a live Home Assistant installation.

## Implementation

The current checkout now creates a deterministic rollback bundle using the
production typed codecs. The rehearsal extracts `v0.12.26`, seeds that bundle
under a fixed config-entry ID, sets up the previous release and verifies exact
restoration of representative charge, export, direct-EVSE, pre-free,
daily-backfill, driving, Charge-to-Full and smart-recovery state.

The representative sessions are deliberately non-idle, but the unchanged
observer and Safety Lock configuration must produce an empty hardware-service
trace. This tests backward readability without granting either release control
authority.

## Compatibility and rollback

Production code, public entities, configuration, Store schemas and runtime
behaviour are unchanged. Revert this test/script/documentation commit to
restore the narrower setup-only rehearsal.

## Acceptance evidence

- Enhanced previous-release rehearsal against `v0.12.26` passes.
- Full current repository suite, frozen contracts and Ruff pass.
- No live site, release, tag or remote branch is changed.

## Completion record

- [x] Existing rehearsal gap characterized
- [x] Current codecs generate the downgrade fixture
- [x] Previous release restores retained obligations
- [x] Empty hardware-command trace verified
- [ ] Independent review complete
- [ ] Live operational rollback complete
