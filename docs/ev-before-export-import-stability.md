# EV-before-export import stability

This corrects a separately approved extension, not the canonical current
planner. A single small grid-import reading previously withdrew a funded top-up
immediately. Its ordinary stop acknowledgement then allowed another start when
the reading cleared. Delayed EV feedback and inverter response could therefore
turn short disturbances into repeated stop/start commands.

The fix adds temporal hysteresis only to this economic import veto. An existing
owned top-up with a matching current request and charge switch on may retain at
most its previous current for the configured import-confirmation period. The
default is 60 seconds, editable from EV Charging policies and
`number.home_energy_ev_before_export_import_confirm_seconds`; 0 restores the
former immediate behaviour. The threshold remains the configured ZEROHERO
import threshold; the tariff accounting timer and credit qualification do not
change. Separate start/stop amplitudes are unnecessary: starting/increasing is
strict, while continuation requires bounded continuous-import confirmation.

No positive command is authorised during the import hold, including retries.
Every electrical, freshness, same-vehicle, ownership, battery reserve, Sellable,
normal SoC, physical current and outside-inverter-percentage limit remains live.
Loss of one is not debounced. Continuous import withdraws at the original
deadline, evaluated on the next normal control cycle. A clear reading rearms;
settings/source rebinding during import cannot restart the deadline. Repeated
unchanged samples do not renew it. Corrupt persisted state grants no hold.

The optional timestamp/binding is stored in the existing EV journal, never a new
writer or timer job. Cold restart requires strict start evidence; restoring an
import timestamp cannot manufacture previous-cycle ownership or extend time.
Previous releases ignore the additive field. Free/Trip/Full, pre-free charging,
ordinary solar soak and physical export handover keep their existing rules.

## Provenance and regressions

| Source or retained behaviour | Correction / evidence |
|---|---|
| Canonical configuration v1.4.24 matched three-minute supervisory control | Unchanged; no replacement EV algorithm |
| Protected top-up's fresh energy and owner budget | All checks retained, shared solar path remains strict |
| Outside-current planner and service/inverter ceilings | Unchanged; a hold can only retain or reduce the old target |
| Direct command reconciliation and stop journal | Reused; positive-command guard remains strict |
| Instantaneous top-up import veto | Existing-current confirmation, explicitly configurable |
| EV Store / restart codec | Optional bound original timestamp; no deadline renewal |

Regression cases cover start-up/current lag and native publisher frames,
isolated/repeated spikes, exact threshold and expiry boundaries, sustained
import, per-command races, configuration edits, restart, malformed state,
reserve/energy/source/owner/service withdrawal and zero-confirmation parity.
Release tests and startup acceptance do not prove physical grid-event delivery
or retailer payment. Deployed dashboards are not rewritten by this correction.
