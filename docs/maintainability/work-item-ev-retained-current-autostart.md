# Confirmed bug — reject unauthorised retained-current EV auto-start

## Problem and evidence

A direct Tessie-controlled vehicle can retain its previous charging current and
start charging when connected. With Automatic EV Control enabled, a configured
0 A outside-window baseline, and no authorised free-window, solar-spill,
pre-free, daily-backfill or Charge to Full stage, the controller previously
returned before creating a stop obligation unless it had owned an earlier
session. This allowed the external auto-start to bypass the configured site
policy.

The sanitized incident is reproduced by
`test_evening_plugin_cannot_resume_retained_current_above_zero_baseline`.

## Existing contract

- Automatic EV Control and its normal commissioning, location, cable,
  telemetry, Safety Lock and write gates remain authoritative.
- A positive configured connected-EV baseline remains a permitted
  outside-window target.
- A 0 A baseline means no ordinary outside-window charging is authorised.
- Free-window, measured-solar, pre-free, daily-backfill and explicit Charge to
  Full stages retain their existing higher-priority authority.
- A direct-EVSE stop is issued through the existing bounded stop obligation and
  service adapter; the fix does not introduce a new command path.

## Invariants

- Safety Lock and an unready EV command gate produce zero hardware calls.
- Smart-socket behaviour is unchanged.
- An authorised charging stage is never stopped by this fallback.
- A positive baseline continues to own current rather than requesting stop.
- Stop retries, persistence and feedback handling remain bounded by the
  existing daily-backfill stop state.

## Non-goals

- Do not change free-window, solar-spill, pre-free or daily-backfill planning.
- Do not change the configured baseline or infer a baseline from hardware.
- Do not add polling, new entities, configuration fields or persisted fields.
- Do not redesign Tessie reconciliation or its retry schedule.

## Deliverables

- Route an unexpected direct-path charging switch through outside-window
  evaluation even when no optional outside stage is enabled.
- Make 0 A baseline ownership create the existing bounded stop obligation
  without requiring a previous HEO current target.
- Retain focused and full lifecycle regressions plus public policy text.

## Compatibility

There are no entity, unique-ID, state-value, attribute, configuration-key,
storage-schema, dashboard, Fleet or Recorder changes. The only observable
change is the confirmed bug fix: an unauthorised direct-path auto-start is
stopped when the configured outside-window baseline is 0 A.

## Test plan

- Focused ownership transition tests preserve authorised-stage, retained-stop,
  positive-baseline and prior-control behaviour.
- Controller regression starts a connected vehicle at retained 16 A with a
  0 A baseline and requires exactly one `stop_charging` action.
- Lifecycle replay performs setup while disconnected, injects the plug-in
  auto-start, captures the ordered Home Assistant service call, verifies the
  public 0 A target, and confirms the outstanding stop obligation.
- Run the complete test suite and diff validation.

## Rollback

Revert the routing and ownership-transition change together. No migration or
stored-state conversion is required. Rollback restores the previous behaviour
without changing any persisted session representation or leaving an inverter
mode owned by HEO.

## Acceptance evidence

- `.venv/bin/pytest -q tests/test_ev_outside_state.py tests/test_ev_active.py::test_zero_baseline_stops_vehicle_auto_start_after_evening_plugin tests/test_lifecycle_harness.py::test_evening_plugin_cannot_resume_retained_current_above_zero_baseline tests/test_lifecycle_harness.py::test_ev_outside_charge_stops_at_house_battery_floor`
  — 11 passed.
- `.venv/bin/pytest -q` — 852 passed.
- `git diff --check` — clean.
- CI, independent review, rollback rehearsal and operational soak remain release
  gates rather than local completion claims.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [ ] Rollback demonstrated
- [ ] Operational soak complete where required
