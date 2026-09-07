# EV charging policy provenance

This document records the canonical source and extension boundary for the EV
controller. The Working Single Phase Pilot Site is both the proven reference and a required future HACS
deployment target.

## Scope and status

The free-window planning, solar-spill and latest-start pre-free planning,
direct-EVSE command, matched sampling, bounded runtime reconciliation, and pure
smart-socket command layers are ported and characterized. The independent
EV intent, commissioning flag, Safety Lock, and complete explicit mapping set
are separate gates. The integration remains non-writing by default and has not
been commissioned on a live site.

## Canonical mapping

| Portable decision | Working Single Phase Pilot Site source | Port rule |
|---|---|---|
| Three-minute grid/current feedback | `grid_signed_current_avg_3m`, `tesla_actual_charging_current_avg_3m` | Preserve source-validity and grid coverage semantics. |
| Physical current ceiling | `tesla_charge_path_maximum_current`, `tesla_effective_charge_current_ceiling` | Explicit commissioned rating is authoritative; live Tessie maximum only bounds an immediate API write. |
| Free-window current | `tesla_free_window_current_target_v1` | Preserve the exact branch order and 0.5 A deadband. |
| Presence | `tesla_home_current_control_active`, `tesla_connected_for_energy_planning` | Auto/Home/Away must be explicit; unknown or contradictory evidence fails closed. |
| Economic SoC target | `tesla_charge_policy_limit_v1` | Free-window and override targets stay separate from actuator protection. |
| Tessie limit target | `tesla_charge_limit_target` | Retain the existing limit away; when a powered baseline is required, round live SoC plus configured headroom upward. |
| Current command | `tesla_charge_current_target`, `tesla_charge_current_command` | Free-window result is bounded by connector and entity constraints; outside-window behaviours are separate later stages. |
| Direct-path actuation | `tesla_automatic_connector_controller_v3` | Set a changed current within the live writable range, then start charging if required; never operate a smart socket. |
| Smart-socket actuation and recovery | `tesla_automatic_connector_controller_v3`, `tesla_10a_socket_fault_recovery_v2` | Required for Working Single Phase Pilot Site compatibility, but not part of the first direct-path commissioning stage. |

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
  allowance controller is provably unnecessary and leaves the pilot-site behavior unchanged.
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

## Runtime and anti-flapping boundary

- Samples are retained as restart-safe, time-weighted three-minute windows.
  Grid feedback requires at least 67% age coverage and a currently valid source.
  EV current is counted only while the mapped Tessie state explicitly says
  `charging`; a known non-charging state contributes zero and unavailable input
  is invalid.
- Single-phase sites may derive signed grid current from the mapped signed grid
  power and configured per-phase voltage. Multiphase commissioning requires an
  explicit sensor in amperes representing the signed current on the most-loaded
  service phase, positive for import. Aggregate three-phase power is not assumed
  to be balanced and cannot satisfy this safety mapping. Missing live feedback
  from that mapping blocks multiphase actuation before the pilot-site priority
  branches are evaluated.
- Auto location requires mapped at-home evidence to report `home` or `on`. The
  cable must report `on`, and an unavailable or explicitly disconnected
  charging state blocks all writes. Manual Home is available as a deliberate
  location override but does not bypass cable or charge-state evidence.
- Direct actuation orders a changed charge limit, then current, then charge
  start. Outside the free window it remains inert by default; explicitly
  enabled Local-Modbus-only solar-spill and pre-free stages use the same bounded
  actuator and return to the protected baseline without issuing stop or pause.
- The requested current, charge limit, and switch response are confirmed from
  mapped Tessie feedback. One unchanged target receives at most three attempts,
  no faster than 30 seconds apart. Failure latches
  `fault_maximum_attempts`; only a genuinely changed target re-arms writes.
  This prevents another writer or stale cloud feedback causing indefinite
  current flapping.
- The runtime, target/requested/actual current chain, target/applied charge
  limits, policy phase, allowance phase, feedback coverage, attempts, last
  actions, and write count are exposed through portable sensors, status
  attributes, and redacted diagnostics.
- With Safety Lock on, a fully commissioned direct path continues through
  sampling and planning, exposes ordered `would_*` actions, and performs no
  reconciliation attempts or service calls. The adapter independently requires
  a `ready` gate, so rehearsal visibility cannot authorize a write.
- The mapped house-load source used for allowance projection must exclude EV
  charging, matching the pilot site's `non_tesla_house_load` role.

## Smart-socket extraction boundary

The pure planner now preserves the source controller's observable command
decisions without embedding its 10 A installation value. The physical minimum,
physical ceiling, and outlet settle duration are explicit inputs. When the
outlet is off, current is bounded by both the selected physical ceiling and the
temporarily writable Tessie maximum, with the physical ceiling used when that
maximum disappears while unpowered. Current staging precedes outlet power. The
source's existing wait accepts any already service-valid current no greater
than the staged command; tests retain that exact behavior. Once powered, the
planner waits the configured settle duration, re-bounds the latest target, and
orders current before charge start. Zero-demand outlet removal remains limited
to outside the free window when explicit power switching is enabled or the EV
is no longer connected for planning.

The configuration and adapter boundary now accepts a smart-socket path only
with an explicitly mapped outlet and a physical ceiling at least as high as the
configured EV minimum. Existing installations default to direct EVSE. The
adapter can issue power commands only to that mapped outlet. Runtime still
returns `smart_socket_runtime_not_connected`, so selecting the path cannot
accidentally execute the direct-EVSE writer.

The one-attempt `no_power` recovery is now a pure restart-serializable state
machine. It preserves sustained fault and coherent home/cable evidence, latches
before the first command, confirms current before removing power, confirms the
outlet off and on around configurable dwell times, rechecks permissions after
delays, re-bounds current after power returns, starts charging, and rearms only
after sustained healthy charging or a supply-path change. Timeout and changed-
permission outcomes remain latched. Runtime storage and delayed execution are
not connected yet, so this code cannot power-cycle an outlet.

## Remaining implementation stages

1. Commission the higher-capacity direct path in observer/rehearsal mode before
   enabling writes.
2. Connect the characterized smart-socket sequence and recovery state machine
   with restart storage and gate rechecks between every delayed action.
3. Last priority: assess Tessie's native driving-demand capability, then port
   the pilot site's learned target only if it is still required.

The canonical YAML contains a P85 daily-driving model and uses it for the
general charge limit outside the free window. It does not set the active
free-window current target. This is a genuine compatibility behavior, but it is
deliberately last priority for the H3 hands-off free-window objective.

The completed outside-window stages are specified separately in
[`ev-solar-spill-and-pre-free-policy.md`](ev-solar-spill-and-pre-free-policy.md).
