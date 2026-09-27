# EV solar-spill and pre-free policy provenance

This policy is a mechanical port of the Working Single Phase Pilot Site
v1.4.24 behavior. It does not use learned driving demand. The pilot's P85
driving-energy model affects a separate general charge-limit target; the 1 A
outside-window behavior is the direct-path protected baseline.

## Solar-spill mapping

| Pilot source | Preserved HEO decision |
| --- | --- |
| `configuration_v1.4.24.yaml:4806` | Reconstruct currently available spill from EV charging power + grid export + signed battery charge; do not forecast future solar. |
| `configuration_v1.4.24.yaml:4858` | Require battery SoC at or above the configured full threshold. |
| `configuration_v1.4.24.yaml:4862` | Require explicit home/cable/charging evidence and vehicle SoC below the soft free-window limit. |
| `configuration_v1.4.24.yaml:4845` | Suppress spill capture during the configured boosted export window. |
| `configuration_v1.4.24.yaml:4913` | Convert measured surplus to current, floor to the actuator step, reject values below its minimum, and cap at the commissioned connector ceiling. |
| `configuration_v1.4.24.yaml:5084` | The pilot coupled active pre-free backfill to live spill. HEO preserves its proven pre-free allocation, but applies the separately documented safety extension: active pre-free has exclusive fixed-current ownership, so variable morning or post-free spill cannot modulate that session. |

The portable runtime requires an explicitly mapped signed battery-power
sensor and sign convention. Grid power already has an explicit sign mapping.
Missing, stale, or incoherent telemetry produces no spill target.

## Morning measured-solar extension

Morning solar capture is a separately identified, default-off extension.  It
reuses the coherent measured-surplus equation above, but is available only in
the interval after the previous ZEROHERO finish and before the next free-power
window.  It deliberately does **not** use the post-free battery-full threshold:
the independent `Morning Solar EV Reserve SoC` protects the house battery while
energy that would otherwise be absorbed before free battery charging can serve
an eligible connected EV.

The two configuration-backed dashboard controls are:

- `switch.home_energy_ev_morning_solar`
- `number.home_energy_ev_morning_solar_reserve_soc`

Existing entries leave the policy off.  Until the reserve number is explicitly
saved, its runtime value is the entry's already commissioned outside-window
house-battery reserve; this avoids silently reducing a site's safety margin.
When a scheduled latest-start pre-free session becomes active, it takes
exclusive control at its fixed current.  Morning solar does not raise, lower,
or otherwise modulate that session.

Both measured-solar stages share a restart-safe adjustment hold.  The first
eligible current is accepted immediately, but any ordinary later change must
remain the same for 15 minutes before it is sent to Tessie.  This filters
whole-amp cloud-edge oscillation instead of repeatedly alternating adjacent
current commands.  Verified grid import may reduce a target immediately.
Lost or stale telemetry, loss of the configured reserve, EV disconnection or
limit, Safety Lock, and all other eligibility failures immediately discard the
hold and return to the protected-baseline path.  The hold is discarded at a
pre-free, free-window, daily-backfill, or charge-to-full takeover.

## Latest-start pre-free mapping

| Pilot source | Preserved HEO decision |
| --- | --- |
| `configuration_v1.4.24.yaml:4037` | Begin with AC-deliverable battery energy after the battery floor and configured reserve. |
| `configuration_v1.4.24.yaml:4427` | Protect the one learned remaining-house budget and unavoidable connected-EV baseline once; do not subtract reserve twice. |
| `configuration_v1.4.24.yaml:4534` | Bound the discretionary amount by sellable energy, remaining export allowance, and configured export-window capacity. |
| `configuration_v1.4.24.yaml:4059` | Make that discretionary amount available only after configured export finish and before the next free window. |
| `configuration_v1.4.24.yaml:4119` | Cap planned energy by wall-side vehicle room to the soft free-window limit, excluding the anti-pause charge-limit guard. |
| `configuration_v1.4.24.yaml:4196` | Calculate maximum *additional* power above the protected baseline, avoiding double counting. |
| `configuration_v1.4.24.yaml:4273` | Schedule backwards from the exact next free-window boundary and freeze the displayed start once active. |
| `configuration_v1.4.24.yaml:4329` | While active, recalculate the safe stepped current directly from live protected energy and remaining time; current may jump down without walking intermediate steps. |
| `configuration_v1.4.24.yaml:6955` | Persist only the active phase/frozen start; clear it outside the interval, when disconnected, during HEO export, at the soft limit, or when allocation disappears. |

## Configurable extension

The pilot is single phase, so its power/current conversions multiply or divide
by one phase. HEO applies the already commissioned EV phase count after the
same source decisions. Golden tests run both the one-phase source vectors and
the three-phase extension. No service rating, voltage, current, energy,
threshold, time, or entity ID is embedded in policy logic.

## Ownership and rollout

These EV stages never write FoxESS. Unlike free-window EV control, both stages
require Local Modbus to be the selected FoxESS owner: solar spill depends on
local signed power telemetry and pre-free backfill depends on the local export
ledger. They do not run while FoxCloud owns the inverter. All Tessie writes
still require the independent EV intent, completed mappings, commissioned
limits, and an open Safety Lock. Each new stage has its own default-off
commissioning option. Disabling a stage prevents new sessions; an already
controlled direct path is returned to its protected baseline rather than
paused.
