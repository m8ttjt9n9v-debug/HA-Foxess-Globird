# Entity terminology review — v0.12.26 baseline

The project owner approved all nine display-name improvements on 2026-09-17.
Unique IDs, entity IDs, state values, attributes, configuration keys, history
and controller behaviour remain unchanged.

The governing distinction is:

- **ZEROHERO** names are retained for values that directly measure or qualify
  that retailer window or credit.
- Generic automatic battery export is not itself ZEROHERO. It may run under
  those tariff conditions, but its plan, status and sellable-energy concepts
  remain valid independently of the brand name.

| Stable key | v0.12.26 display name | Approved display name | Reason |
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

## Approval outcome

All nine records are `owner_approved` and implemented as naming-only catalogue
changes. The immutable v0.12.26 contract remains the compatibility baseline;
tests permit exactly these nine name deltas and reject any other public drift.

The naming-only release must preserve existing entity IDs and unique IDs and
must pass clean-install, upgrade, reload, user-renamed registry and dashboard
compatibility fixtures before release.
