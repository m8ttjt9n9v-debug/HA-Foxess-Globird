# Work item — typed automatic-control gates

## Scope

Migrate only the automatic FoxESS controller's existing ownership, master,
Safety Lock, sign-verification, actuator-mapping and independent request reads
to the immutable runtime configuration snapshot.

## Source provenance

| Existing serialized input | Typed field | Preserved behavior |
|---|---|---|
| `foxess_control_owner` | `automation.control_owner` | FoxCloud and observer outcomes retain first precedence. |
| `automatic_control_enabled` | `automation.master_enabled` | False remains an absolute no-write gate. |
| `rehearsal_mode` | `automation.safety_lock` | True remains an absolute no-write gate. |
| `sign_conventions_verified` | `electrical.verified` | False remains an absolute no-write gate. |
| Three FoxESS actuator mappings | `inverter.*_entity` and `actuator_mapping_complete` | Any falsey mapping remains blocked. |
| `automatic_charge_enabled` | `automation.battery_charge_enabled` | Existing default and boolean coercion are unchanged. |
| `free_charge_schedule_confirmed` | `automation.free_charge_schedule_confirmed` | Confirmation remains mandatory for a new charge. |
| `automatic_export_enabled` | `automation.battery_export_enabled` | Existing default and boolean coercion are unchanged. |
| `ev_before_export_enabled` | `ev_preferences.before_export_enabled` | Existing default and boolean coercion are unchanged. |
| `ev_before_export_soc_target` | `ev_preferences.before_export_soc_target` | Existing numeric fallback is unchanged. |

## Invariants

- Preserve gate order, status strings, reason strings and zero-write outcomes.
- Preserve charge-before-export reconciliation and session ownership order.
- Preserve every command, delay, time window, energy calculation and stored
  payload.
- Do not migrate time-window, telemetry, EV electrical or energy-policy inputs
  in this work item.
- Do not change serialized keys, config-entry versions, entities or services.

Parameterized legacy-versus-typed configuration tests and controller no-write
gate tests are the pre-change characterization. The full lifecycle suite,
configuration contracts and previous-release rehearsal remain release gates.

## Outcome

The controller's direct configuration reads fell from 25 to 5 and total
runtime raw reads fell from 106 to 86. The five remaining controller reads are
time-window, energy-policy and EV electrical inputs deliberately outside this
seam.

Validation completed with 511 tests, repository-wide Ruff, the configuration
usage/configuration/persistence contract checks and the unmodified v0.12.26
previous-release rehearsal.
