# Phase 7.9 — extract EV solar-spill telemetry evaluation

## Problem and evidence

`ActiveEvController._solar_spill_decision` currently contains source-provenance
selection, timestamp age/skew coherence, EV power conversion and signed power
reconstruction alongside Home Assistant facade wiring. These are domain rules,
not lifecycle or command-execution responsibilities, and they make the active
controller harder to review before the planned solar-spill cadence work.

## Existing contract

- Grid and battery power must both have canonical numeric values.
- State-qualified actual EV current must be valid; the mapped current entity
  and battery-SoC entity must be present.
- Grid and battery are fast telemetry. Every effective source timestamp must be
  present, not in the future, no older than the configured maximum age, and no
  farther apart than the configured maximum skew.
- For `signed_fallback_pair_stale`, only the accepted signed fallback source
  timestamp underpins the normalized battery value; rejected stale magnitude
  sources remain diagnostic provenance and do not invalidate it.
- Stable Tessie current state and battery SoC are value/presence evidence, not
  fast-clock members.
- Reconstructed surplus is EV power plus grid export plus signed battery charge,
  with battery discharge reducing the result in the existing current planner.

## Invariants

- Preserve every phase, current target and reconstructed-surplus value.
- Preserve exact inclusive maximum-age and maximum-skew boundaries.
- Preserve future-timestamp rejection and fallback-source selection.
- No timer, cadence, hysteresis, retry, command, priority or persistence change.
- No Home Assistant import or side effect enters the pure planner.

## Non-goals

- Do not implement the planned 15-minute solar-spill hold.
- Do not add morning measured-solar charging or alter pre-free precedence.
- Do not change telemetry normalization, source signs or configuration.
- Do not improve impossible malformed normalized samples in this seam.

## Deliverables

- Characterization of fresh, stale, skewed, future and signed-fallback evidence.
- Immutable primitive telemetry-evidence and evaluation result types.
- A pure evaluation function for coherence and power reconstruction.
- A thin controller adapter that invokes the existing current planner with the
  extracted result.

## Compatibility

There are no entity, unique-ID, state-value, attribute, configuration-key,
storage, dashboard, Fleet or Recorder changes. The refactor retains the same
planner and command adapter.

## Test plan

- Freeze current controller outcomes before extraction.
- Add pure tests for every coherence term and reconstructed power component.
- Retain runtime measured-surplus and signed-fallback tests.
- Run the EV/outside-window, lifecycle, contract, rollback and full-suite gates.

## Rollback

Revert the extraction commit to restore the same calculation to the controller.
No stored state, command ownership or hardware restoration is involved.

## Acceptance evidence

- Pre-extraction runtime, fallback, age, skew, future and pure current-planner
  characterization: 25 passed.
- Implementation and complete compatibility gates remain outstanding.

## Completion record

- [x] Existing behaviour characterised
- [ ] Implementation complete
- [ ] Compatibility checks passed
- [ ] Documentation and roadmap updated
- [ ] Independent review complete
- [ ] Rollback demonstrated
- [ ] Operational soak complete where required
