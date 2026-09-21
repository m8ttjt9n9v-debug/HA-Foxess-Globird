# Phase 7.9 — extract EV daily-backfill input composition

## Problem and evidence

`ActiveEvController._calculate_daily_backfill_plan` still performs domain
composition inside the Home Assistant facade: it converts live battery energy
through discharge efficiency, infers vehicle wall-energy room, normalizes
protected/sellable energy and assembles the pure daily planner input.

## Existing contract

- Available battery energy after reserve, protected house energy, a live export
  plan, vehicle stored energy and vehicle SoC are all required.
- Missing evidence returns `daily_backfill_energy_inputs_unavailable` before the
  ready-cycle rollover is evaluated.
- Battery energy is clamped at zero and converted to available AC energy using
  the configured discharge efficiency.
- Protected house and sellable energy are independently clamped at zero.
- Vehicle wall room is derived from live stored energy, current/target SoC and
  configured charging efficiency; it is not a fixed vehicle capacity.
- Ready-cycle rollover remains a lifecycle responsibility of the facade.
- The existing pure daily planner retains all allocation, timing, current-cap,
  phase and exception semantics.

## Invariants

- Preserve every plan field, phase and missing-input reason.
- Preserve the ordering of missing-evidence rejection and cycle rollover.
- Preserve all configuration-driven phase, voltage, efficiency and current
  limits without site assumptions.
- No command, priority, persistence, retry, timer or state-machine change.
- No Home Assistant import or side effect enters the pure evaluator.

## Non-goals

- Do not alter the daily allocation or ZEROHERO export-protection algorithm.
- Do not change pre-free, solar-spill or free-window priority.
- Do not change entity mappings, configuration or persistence.
- Do not accept malformed inputs previously rejected by the planner.

## Deliverables

- Facade characterization for efficiency conversion and missing evidence.
- Immutable primitive evidence type and pure composition/evaluation function.
- Thin facade mapping with lifecycle rollover retained in the controller.
- Focused, lifecycle, frozen-contract, previous-release and full-suite gates.

## Compatibility and rollback

No public or stored contract changes. Reverting the extraction commit restores
the same composition to the facade without data or hardware-state migration.

## Acceptance evidence

- Pre-extraction facade composition, missing-evidence and pure daily-planner
  characterization: 20 passed.
- Implementation and complete compatibility gates remain outstanding.

## Completion record

- [x] Existing behaviour characterised
- [ ] Implementation complete
- [ ] Compatibility checks passed
- [ ] Documentation and roadmap updated
- [ ] Independent review complete
- [ ] Rollback demonstrated
- [ ] Operational soak complete where required
