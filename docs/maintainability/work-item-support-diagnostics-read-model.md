# Work item — complete support diagnostics model

## Problem

Support diagnostics still assembled non-EV actuator and ledger facts directly
from runtime configuration, controllers and the ledger. All other diagnostic
sections used the canonical model, leaving one final presentation bypass.

## Change and preserved behavior

The control model now includes EV-before-export policy facts and
`SiteReadModel.actuator_diagnostics()` projects the complete established
actuator payload. The operational model projects the existing five-key ledger
payload. Diagnostics retain their entry version, fixed observe-mode marker and
mapped actuator count; all calculated values now come from one immutable model.
No raw entity IDs or additional private evidence are exposed.

## Verification

- Exact characterization covers the complete actuator and ledger projections.
- Focused read-model, diagnostics setup and lifecycle suite: 100 passed.
- Full repository suite: 642 passed.
- Ruff and the frozen entity, attribute, configuration and persistence
  contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.
