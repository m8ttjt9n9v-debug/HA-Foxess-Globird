# Phase 7.9 — extract learned EV charge-limit composition

## Problem and evidence

`ActiveEvController._learned_general_limit` still composes three pure domain
steps inside the Home Assistant facade: usable vehicle capacity from live
stored energy, maximum ZEROCHARGE-window SoC gain, and the retained fallback or
P85 general charge limit.

## Existing contract

- Live stored vehicle energy plus vehicle SoC determine usable capacity.
- Configured maximum EV current, voltage, phase count, exact ZEROCHARGE window
  duration and charging efficiency determine maximum free-window SoC gain.
- The 28-sample driving history and configured maturity threshold select the
  fallback or learned-P85 branch with retained floor/ceil actuator rounding.
- Stored-energy or actuator metadata absence returns no learned decision.
- Invalid energy, SoC, topology, efficiency, history or actuator evidence is
  caught at the facade boundary and clears the published learned decision.
- This calculation has no current-control or hardware-write authority by
  itself.

## Invariants

- Preserve limit, mode, sample count, P85, usable capacity and free-window gain.
- Preserve exact configured time-window duration and phase conversion.
- Preserve fail-closed missing and invalid evidence behavior.
- No command, reconciliation, timing, persistence or priority change.
- No Home Assistant import or side effect enters the pure evaluator.

## Non-goals

- Do not change the learning percentile, maturity threshold or history window.
- Do not change EV charge-limit policy, solar/pre-free behaviour or retry rules.
- Do not add forecast inputs or infer vehicle capacity from a fixed model.

## Deliverables

- Facade characterization of the exact fallback composition and invalid inputs.
- Immutable primitive evidence type and one pure composition function.
- Thin controller adapter retaining observation and publication only.
- Focused, lifecycle, frozen-contract, previous-release and full-suite gates.

## Compatibility and rollback

No public or stored contract changes. Reverting the extraction commit restores
the same composition to the facade without data or hardware-state migration.

## Acceptance evidence

- Pre-extraction fallback/P85, live-capacity, metadata, invalid-evidence and
  lifecycle characterization: 11 passed.
- Implementation and complete compatibility gates remain outstanding.

## Completion record

- [x] Existing behaviour characterised
- [ ] Implementation complete
- [ ] Compatibility checks passed
- [ ] Documentation and roadmap updated
- [ ] Independent review complete
- [ ] Rollback demonstrated
- [ ] Operational soak complete where required
