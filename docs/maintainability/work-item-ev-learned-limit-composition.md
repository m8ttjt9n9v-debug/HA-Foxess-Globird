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
- Post-extraction focused pure/facade/lifecycle selection: 13 passed.
- Full repository suite: 894 passed in 36.43 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
- `README.md`, public entities, configuration keys, persistence payloads and
  command behavior are unchanged.
- Independent review and the complete Phase 7 exit/rollout gates remain
  separate obligations; this extraction is not authorized for deployment.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [x] Operational soak not required for this side-effect-free extraction
