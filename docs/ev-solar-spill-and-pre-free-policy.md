# EV solar-spill and pre-free policy provenance

The underlying solar reconstruction and latest-start battery plan are ports of
the Working Single Phase Pilot Site v1.4.24 behavior. Combined pre-free charging
below is an explicit policy correction, not unchanged pilot parity. These
planners do not use learned driving demand. The pilot's P85
driving-energy model affects a separate general charge-limit target; the 1 A
outside-window behavior is the direct-path protected baseline.

## Solar-spill mapping

| Pilot source | Preserved HEO decision |
| --- | --- |
| `configuration_v1.4.24.yaml:4806` | Reconstruct currently available spill from EV charging power + signed grid flow (export positive, import negative) + signed battery charge; do not forecast future solar. |
| `configuration_v1.4.24.yaml:4858` | Require battery SoC at or above the configured full threshold. |
| `configuration_v1.4.24.yaml:4862` | Require explicit home/cable/charging evidence and vehicle SoC below the soft free-window limit. |
| `configuration_v1.4.24.yaml:4845` | Suppress spill capture during the configured boosted export window. |
| `configuration_v1.4.24.yaml:4913` | Convert measured surplus to current, floor to the actuator step, reject values below its minimum, and cap at the commissioned connector ceiling. |
| `configuration_v1.4.24.yaml:5084` | The pilot selected the larger of active pre-free and solar targets; earlier HACS selected pre-free exclusively. The combined correction now adds permitted measured morning solar and protected battery pacing under one current owner when both policies are enabled. |

The portable runtime requires an explicitly mapped signed battery-power
sensor and sign convention. Grid power already has an explicit sign mapping.
Missing, stale, or incoherent telemetry produces no spill target.

### Canonical battery-source timing correction

Coherent charge/discharge magnitudes remain preferred. An unchanged inactive
zero can report less often while still being individually fresh. If that
older zero exceeds the existing configured EV skew limit, HEO can use the
separately commissioned signed battery-power sample instead, provided it is
valid, fresh and does not contradict the pair's direction. Both idle-zero
readings may also use this independent signed evidence. Two nonzero magnitudes
or an older active magnitude are not covered by this timing fallback.
The original stale-pair fallback remains unchanged.

This is a correction at the shared telemetry boundary, not a new charging
algorithm. Diagnostics retain all sources with
`signed_fallback_pair_incoherent` provenance; only the accepted signed source
supplies the value's clock. The grid and accepted battery clocks must still
pass the same age and skew limits for morning solar, Ready by and pre-free
backfill. No arbitrary old zero is treated as current evidence.

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
When morning solar and pre-free are both enabled, fresh positive raw net solar
plus a live protected battery budget may start one combined pre-free request
before latest start. The request adds separately protected keepalive, current
discretionary AC energy divided by physical UTC hours until free start, and raw
measured net solar. It floors once and caps TOTAL EV current by the saved
outside-window percentage, connector and current service limits. Solar alone
need not reach the charger minimum if the combined current is representable.
No-solar latest-start behaviour remains; an admitted combined session can pace
safe battery energy through measured zero-solar clouds. Invalid or stale
evidence is not equivalent to zero solar and cannot sustain permission.

This deliberately supersedes the earlier exclusive fixed-current handoff, not
the energy protections or single writer. Ready-by priority, its valid
after-deadline handoff and invalid-evidence holds remain binding. Limits, time,
house protection and car room may leave energy unused rather than reaching an
exact house-battery reserve. See [combined pre-free](ev-combined-pre-free.md).

Both measured-solar stages share a restart-safe adjustment hold. The first
eligible current is accepted immediately, but any ordinary later change must
remain the same for 10 minutes before it is sent to Tessie. This filters
whole-amp cloud-edge oscillation instead of repeatedly alternating adjacent
current commands.  Verified grid import may reduce a target immediately.
The configured SoC threshold is a hard cutoff: the instant SoC falls below it,
the held target is discarded and the EV returns to the protected baseline.
Lost or stale telemetry, loss of the configured reserve, EV disconnection or
limit, Safety Lock, and all other eligibility failures do the same. Combined
pre-free retains this journal under the existing `morning_solar` category with
optional accepted battery-current context, but adopts the latest safe target
on a ten-minute cadence without requiring an unchanged candidate for the whole
interval. Its moving battery-energy/time deadline must not starve updates;
standalone solar retains its original stable-target hysteresis. Reduced
protected battery authority or service headroom also curtails immediately.
Uncombined pre-free, free-window,
daily-backfill and charge-to-full takeover discard the solar hold. No new store
version, polling dependency, forecast service or device writer is introduced.

## Latest-start pre-free mapping

With **Ready by** timing, the daily ready-by session is an earlier opportunity.
After its deadline, the retained pre-free planner below becomes eligible again,
using the current protected energy ceiling rather than reusing the earlier
allocation or tomorrow's ready-by schedule. Morning solar may continue while
that planner waits; the combined correction can use both contributions under
one selected pre-free current owner when both policies are enabled. With
explicitly selected **Conservative** timing, the no-solar latest-start and
fixed daily-allocation arithmetic are unchanged. See
[backfill handoff](ev-daily-ready-backfill.md#handoff-after-the-ready-time).

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
