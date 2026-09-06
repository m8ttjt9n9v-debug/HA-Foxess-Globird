# EV charging policy provenance

This document records the canonical source and extension boundary for the EV
controller. Mangerton is both the proven reference and a required future HACS
deployment target.

## Scope and status

The pure planning and direct-EVSE command layers are ported and characterized.
The independent EV intent, commissioning flag, Safety Lock, and complete
explicit mapping set are separate gates. Restart-serializable matched-average
buffers are implemented, but runtime sampling and reconciliation are not yet
connected. Therefore EV writes remain impossible in this milestone.

## Canonical mapping

| Portable decision | Mangerton source | Port rule |
|---|---|---|
| Three-minute grid/current feedback | `grid_signed_current_avg_3m`, `tesla_actual_charging_current_avg_3m` | Preserve source-validity and grid coverage semantics. |
| Physical current ceiling | `tesla_charge_path_maximum_current`, `tesla_effective_charge_current_ceiling` | Explicit commissioned rating is authoritative; live Tessie maximum only bounds an immediate API write. |
| Free-window current | `tesla_free_window_current_target_v1` | Preserve the exact branch order and 0.5 A deadband. |
| Presence | `tesla_home_current_control_active`, `tesla_connected_for_energy_planning` | Auto/Home/Away must be explicit; unknown or contradictory evidence fails closed. |
| Economic SoC target | `tesla_charge_policy_limit_v1` | Free-window and override targets stay separate from actuator protection. |
| Tessie limit target | `tesla_charge_limit_target` | Retain the existing limit away; when a powered baseline is required, round live SoC plus configured headroom upward. |
| Current command | `tesla_charge_current_target`, `tesla_charge_current_command` | Free-window result is bounded by connector and entity constraints; outside-window behaviours are separate later stages. |
| Direct-path actuation | `tesla_automatic_connector_controller_v3` | Set a changed current within the live writable range, then start charging if required; never operate a smart socket. |
| Smart-socket actuation and recovery | `tesla_automatic_connector_controller_v3`, `tesla_10a_socket_fault_recovery_v2` | Required for Mangerton compatibility, but not part of the first direct-path commissioning stage. |

The canonical private deployment file and revision are recorded in the
maintainer source-of-truth document. Public code contains no personal entity
IDs or site addresses.

## Base branch order

The free-window planner evaluates these branches in order:

1. inactive, disconnected, or no physical ceiling: protected baseline;
2. service-limit overrun: aligned correction when EV feedback is valid,
   otherwise protected baseline;
3. charge-to-full or EV priority: physical ceiling;
4. FoxESS settling interval: configured effective minimum;
5. invalid grid feedback or invalid service limit: effective minimum;
6. invalid EV feedback: retain the bounded requested current;
7. within the 0.5 A service deadband: retain the bounded request;
8. otherwise: aligned, step-rounded, physically bounded correction.

No phase count, inverter size, tariff allowance, or site identity changes this
branch order.

## FoxESS SoC and usable energy

The canonical control model retains the inverter's raw SoC and its configured
minimum SoC as separate inputs. Usable battery energy is:

`effective_capacity_kwh × max(raw_soc − minimum_soc, 0) / 100`

A user-facing relative percentage may instead display
`(raw_soc − minimum_soc) / (100 − minimum_soc) × 100`. That display value must
not be substituted for raw SoC in the energy equation, because doing so would
apply the minimum twice. A battery-capacity mapping must contain kWh capacity,
not either form of SoC percentage.

## Daily allowance extension

The whole-site allowance is an outer ceiling, not a replacement charging
algorithm. It receives the already calculated base current plus explicit,
configured projections for remaining non-EV import and EV energy need.

- First calculate the physical site envelope from configured per-phase service
  current, site voltage, phase count, and remaining window duration. If even
  sustained service-limit import cannot reach the remaining allowance, the
  allowance controller is provably unnecessary and leaves Mangerton unchanged.
- If imported energy plus projected house, battery, EV, and safety margin fits
  under the configured kWh allowance, the base current passes through unchanged.
- Only a projected overrun activates pacing. The remaining EV budget is
  converted to current using configured voltage, phase count, current step, and
  remaining window duration.
- A missing live allowance meter fails to the protected baseline.
- A direct or powered connector may require a non-zero protected baseline. The
  controller must expose that it cannot guarantee the tariff boundary when
  uncontrollable house/FoxESS import plus this safety baseline exceeds it.
- FoxCloud ownership of the inverter does not by itself block the independent
  EV gate: the EV controller writes only explicitly mapped Tessie actuators.
  The shared Safety Lock remains an absolute write interlock.

Service capacity limits instantaneous import; it does not allocate energy.
Conversely, the kWh allowance limits total energy; it does not prove an
instantaneous current is electrically safe. Both constraints must pass.

The extension must never hard-code an allowance, service current, voltage,
phase count, connector rating, efficiency, time, or entity ID.

## Remaining implementation stages

1. Connect the ported matched three-minute samples to mapped runtime state.
2. Connect the now-characterized direct-path adapter with response
   confirmation, bounded retries, service-call tracing, and rehearsal tests.
3. Commission the higher-capacity direct path in observer/rehearsal mode before
   enabling writes.
4. Port the smart-socket sequence and one-attempt fault recovery for Mangerton.
5. Port learned driving demand, pre-free backfill, and solar spill as separate
   provenance-tested behaviours.
