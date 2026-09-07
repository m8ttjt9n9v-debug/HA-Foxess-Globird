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
| `configuration_v1.4.24.yaml:5084` | During active pre-free backfill select the greater of live backfill and live spill; otherwise spill precedes the protected baseline. |

The portable runtime requires an explicitly mapped signed battery-power
sensor and sign convention. Grid power already has an explicit sign mapping.
Missing, stale, or incoherent telemetry produces no spill target.

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
