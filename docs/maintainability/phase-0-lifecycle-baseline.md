# Phase 0 — lifecycle and contract baseline

Phase 0 creates evidence strong enough to permit later structural change. It
does not alter policy, timing, controller authority or user-facing semantics.

## Work packages

### OM-001 — Programme controls

- Adopt the functionality freeze and programme rules.
- Add the scorecard and work-item template.
- Keep a dedicated maintenance branch while `main` remains releasable.

**Complete when:** the rules are linked from the roadmap and all subsequent
work items use the template.

### OM-002 — Reproducible baseline

- Record supported runtime versions, dependency locks and local/CI commands.
- Capture the full current test result and duration.
- Generate module size, import dependency and complexity inventories.
- Inventory periodic timers, state listeners, service-call boundaries, stores,
  config-entry versions and migrations.

**Complete when:** another engineer can reproduce the baseline from a clean
clone without site access.

Current artifact: [v0.12.26 baseline](baseline-v0.12.26.md).

### OM-003 — Entity-registry contract

- Snapshot every platform, key, unique ID, default entity ID, display name,
  unit, device class, state class, category and default-enabled state.
- Test untouched, user-renamed, custom-named, disabled, hidden, labelled and
  area-assigned entities, plus entity-ID collisions.
- Characterise and remove any setup behaviour that reclaims a user-owned entity
  ID while preserving clean-install defaults.

**Complete when:** setup, reload and upgrade cause zero unintended registry
churn and every current unique ID remains stable.

Current machine-readable identity snapshot:
[v0.12.26 entity contract](entity-contract-v0.12.26.json).

The corresponding ordered setup/reconfigure surface is frozen in the
[v0.12.26 configuration contract](config-contract-v0.12.26.json). It records
page membership and ordering separately from future semantic `FieldSpec` work.

The retained Home Assistant storage keys, schema versions and privacy flags are
frozen in the
[v0.12.26 persistence contract](persistence-contract-v0.12.26.json). Any change
to that contract requires an explicit migration and compatibility review.
The unresolved ownership boundary for missing or malformed session state is
specified separately in
[malformed session storage safety decision](malformed-session-storage.md).

### OM-004 — Lifecycle harness core

Create reusable test infrastructure for:

- deterministic local time and boundary advancement;
- timestamped Home Assistant state input;
- stale, unavailable, delayed, contradictory and out-of-order updates;
- ordered service-call capture;
- persisted-store snapshot, corruption and restoration;
- config-entry setup, unload, reload, restart-equivalent reconstruction and
  reconfiguration; and
- state, attribute, controller, persistence and service-call trace snapshots.

**Complete when:** one ordinary uninterrupted day and the same day with restart
at each session phase produce equivalent final state and command obligations.

Current deterministic evidence:
`test_ordinary_day_has_restart_equivalent_command_obligations` runs the same
charge → idle → export → idle day uninterrupted and with reloads at every
starting, active and stopping boundary. Both traces must produce the same eight
ordered FoxESS calls and finish with both persisted sessions idle.

Ordered FoxESS traces are captured at the awaited Home Assistant service-call
boundary. `EVENT_CALL_SERVICE` remains useful as evidence that calls occurred,
but its asynchronously scheduled listeners are deliberately not used to infer
command order.

### OM-005 — Incident fixture catalogue

Retain sanitized fixtures for each confirmed class of failure, including:

- force-mode restoration and reassertion after restart;
- reload or reconfigure during and immediately after a session;
- stale positive-flow anchors and unavailable canonical telemetry;
- EV current cycling and mismatched target/setting/actual feedback;
- free-window recovery after Home Assistant restart;
- external inverter-mode changes;
- sign-verification and owner changes;
- accounting changes while importing zero or continuously exporting;
- protected house-battery depletion by EV policy; and
- learning state becoming unavailable despite valid retained samples.

Each fixture records initial states, event sequence, persisted payloads,
expected plans, permitted calls, forbidden calls and final ownership.

**Complete when:** every confirmed incident is named, reproducible and runs in
the deterministic suite without private hostnames, addresses or credentials.

Current coverage and evidence gaps are tracked in the
[incident fixture catalogue](incident-fixture-catalogue.md).

### OM-006 — Continuous enforcement

- Run deterministic lifecycle fixtures on every pull request and release tag.
- Run larger fixed-seed generated sequences on schedule and before release.
- Retain every discovered counterexample as a named deterministic fixture.
- Fail CI on unreviewed public-contract or persisted-schema changes.

**Complete when:** a regression cannot merge merely because isolated planner
tests remain green.

## Phase exit gate

- Existing calculation and integration tests pass.
- Lifecycle traces are deterministic.
- Every current incident class has a fixture or an explicitly documented
  evidence gap.
- Registry and configuration snapshots exist.
- Safety Lock, exclusive owner and bounded restoration invariants are enforced
  at system level.
- No production policy or actuator behaviour changed during the phase.
