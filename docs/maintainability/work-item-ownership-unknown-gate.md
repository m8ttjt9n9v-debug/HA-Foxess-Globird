# Work item — fail-closed forced-mode ownership gate

## Decision

Approved by the project owner on 2026-09-17. If the inverter is in Force
Charge or Force Discharge and HEO cannot prove ownership from retained session
state, HEO must expose `ownership_unknown` and perform no hardware write until
Self Use or a verified external owner establishes a safe boundary.

## Compatibility boundary

- Keep all three private Home Assistant storage keys at version 1.
- Continue reading every valid v0.12.26 payload without migration.
- Do not change entity keys, unique IDs, default entity IDs, units or classes.
- Add only the approved `ownership_unknown` state to Orchestrator Status and
  Fleet Summary.
- Do not infer ownership from the inverter work mode.

## Implementation

- Charge, export and manual-test loaders classify valid, missing and malformed
  evidence.
- Malformed evidence is not overwritten while a forced mode is observed.
- Complete valid idle evidence classifies an unowned forced mode as external.
- Matching valid active evidence retains the existing bounded restoration
  obligation even if an unrelated store is missing.
- Self Use checkpoints compatible idle payloads and resumes normal evaluation
  from that observed safe state.

## Acceptance evidence

- `test_missing_session_evidence_holds_forced_mode_until_self_use`
- `test_malformed_session_evidence_is_not_overwritten_while_forced`
- `test_valid_idle_evidence_treats_unowned_forced_mode_as_external`
- `test_active_export_rejects_external_force_charge_across_reload`
- existing charge/export restart and recovery lifecycle fixtures

The previous-valid-snapshot envelope described in
`malformed-session-storage.md` is not included. It remains blocked on a
rollback-compatible persistence design and is not required for this fail-closed
safety gate.
