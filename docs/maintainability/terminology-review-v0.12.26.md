# Entity terminology review — v0.12.26 baseline

This is the only product-owner decision required to finish the Phase 1 entity
contract. It proposes display-name improvements only. Unique IDs, entity IDs,
state values, attributes, configuration keys, history and controller behaviour
remain unchanged. No name changes are implemented by this document.

The governing distinction is:

- **ZEROHERO** names are retained for values that directly measure or qualify
  that retailer window or credit.
- Generic automatic battery export is not itself ZEROHERO. It may run under
  those tariff conditions, but its plan, status and sellable-energy concepts
  remain valid independently of the brand name.

| Stable key | Current display name | Proposed display name | Reason |
|---|---|---|---|
| `automatic_export` | Automatic ZEROHERO Export | Automatic Battery Export | The switch requests the generic automatic export controller, not the ZEROHERO credit itself. |
| `bonus_zero_import_allowed` | ZEROHERO Telemetry Guard Qualified | ZEROHERO Local Telemetry Qualified | Makes clear that this is provisional local evidence, not the retailer's completed result. |
| `free_charge_allowed` | Free Charge Allowance Remaining | Battery Free-Charge Energy Allowed | Distinguishes the controller's currently allowed battery energy from the whole-site allowance remaining. |
| `zerohero_export_status` | ZEROHERO Export Status | Automatic Battery Export Status | Reports generic export-controller withholding/session state. |
| `zerohero_planned_duration` | ZEROHERO Planned Duration | Automatic Export Planned Duration | The plan belongs to automatic battery export, not to the ZEROHERO credit. |
| `zerohero_planned_export_energy` | ZEROHERO Planned Export Energy | Automatic Export Planned Energy | Separates planned automatic export from boost-eligible or credit-qualified energy. |
| `zerohero_planned_start` | ZEROHERO Planned Start | Automatic Export Planned Start | Identifies the automatic export scheduler rather than a retailer event. |
| `zerohero_sellable_energy` | ZEROHERO Sellable Energy | Sellable Battery Energy | This is available battery energy before the automatic daily cap, not a ZEROHERO measurement. |
| `status` | Status | Orchestrator Status | Removes ambiguity on dashboards containing inverter, EV and retailer status entities. |

All other 98 display names are proposed to remain unchanged in this phase.
Later translation-key work may improve localization while preserving these
approved English semantics and every stable identity contract.

## Approval outcomes

- **Approve as proposed:** mark the nine records `owner_approved`; implement a
  naming-only compatibility release in Phase 2.
- **Approve with edits:** update only the proposed display-name text, then mark
  the reviewed records approved.
- **Retain current names:** change each rejected proposal to `retain`; no runtime
  or registry change is needed.

The naming-only release must preserve existing entity IDs and unique IDs and
must pass clean-install, upgrade, reload, user-renamed registry and dashboard
compatibility fixtures before release.
