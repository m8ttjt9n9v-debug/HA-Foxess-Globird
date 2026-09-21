# Release sync — forward-port v0.12.27 and v0.12.28

## Problem and evidence

The maintenance branch had diverged structurally after v0.12.26 while `main`
released two confirmed EV fixes:

- v0.12.27 stops an unauthorised retained-current plug-in auto-start when the
  configured outside-window baseline is 0 A; and
- v0.12.28 applies the outside-window inverter-power cap to pre-free charging
  and forces an immediate EV decision when pre-free crosses into ZEROCHARGE.

Leaving those commits outside the maintenance history would make later
refactors validate an obsolete production contract. Copying the old runtime
implementation wholesale would bypass the extracted candidate, ownership,
configuration and persistence boundaries.

## Existing contract

- The v0.12.27 baseline authority and bounded stop behaviour are recorded in
  `work-item-ev-retained-current-autostart.md`.
- Daily backfill already interprets the configured outside-window percentage as
  inverter power, converts it using configured EV voltage and phase count, and
  rounds down to an actuator-supported current step.
- A latched pre-free session owns its outside-window current only until entry
  into the configured free window.
- Free-window settlement policy is recalculated from current evidence and must
  replace the battery-backed pre-free target at the boundary.

## Invariants

- The extracted outside-stage candidate and ownership transitions remain the
  only priority and ownership boundaries.
- Solar spill remains measured-surplus control and is not constrained as
  battery-backed pre-free or daily-backfill power.
- Safety Lock, EV commissioning, location, cable, telemetry and command gates
  remain unchanged.
- Current is rounded down and bounded by both physical charger capability and
  live service headroom.
- No new persisted field, entity, configuration key or controller authority is
  introduced.

## Non-goals

- Do not implement the planned 15-minute solar-spill hold or morning measured-
  solar feature during the functionality freeze.
- Do not redesign pre-free scheduling, free-window priority or Tessie retry
  policy.
- Do not publish, tag or deploy the maintenance branch as part of this sync.

## Deliverables

- Merge the v0.12.27 and v0.12.28 release history into the maintenance branch.
- Retain the maintenance branch's extracted EV boundaries while adding one
  shared pure inverter-backed current constraint used by daily backfill and
  pre-free charging.
- Preserve the exact free-window boundary trigger before clearing pre-free
  ownership.
- Retain focused electrical, controller and system-lifecycle regressions.

## Compatibility

The manifest and package version advance from 0.12.26 to 0.12.28, matching
`main`. Public entities, unique IDs, state values, attributes, configuration
keys and persisted payloads are unchanged. Existing entries therefore require
no migration. The merge retains the released behaviour while routing it through
the maintenance branch's internal boundaries.

## Test plan

- Pure constraint tests cover three-phase conversion, actuator-step rounding,
  physical ceiling, zero percentage and invalid input rejection.
- Daily-backfill tests prove the shared constraint preserves its existing
  calculations.
- Controller tests cover a 30%/15 kW/230 V three-phase pre-free cap and the
  immediate pre-free-to-ZEROCHARGE target replacement.
- A system lifecycle replay sets up the integration, injects an active pre-free
  target at the exact boundary, verifies the public target becomes 1 A, and
  captures exactly one ordered Tessie current command.
- The v0.12.27 focused and system auto-start regressions remain collected once,
  without duplicate test names.

## Rollback

Revert the merge commit as one unit. The change has no schema migration and no
new stored state, so the prior maintenance commit can read all retained stores.
Operational rollback still requires confirming that no EV command is in flight;
the code rollback itself creates no FoxESS ownership or restoration obligation.

## Acceptance evidence

- Focused v0.12.27/v0.12.28 merge set — 38 passed.
- Exact-boundary lifecycle replay — 1 passed.
- Final complete suite — 863 passed in 47.12 seconds.
- Frozen architecture and compatibility contracts — 24 passed.
- Previous-release rehearsal against `v0.12.26` — 1 passed.
- `git diff --check` — clean.
- Offline repository Ruff check — passed.
- CI, independent review and rollout remain separate gates before release.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [ ] Rollback demonstrated
- [ ] Operational soak complete where required
