# Proposed EV charging during the evening export opportunity

Status: design only; not implemented, enabled, released or deployed. This is a
separately configured, default-off extension for review after the requested
settling period. The current EV-before-export policy remains the default.
Neither this document nor an eventual code installation authorises a live
configuration change, device command, monitoring job or another-site rollout.

## Intended result and scope

When an eligible home-connected EV arrives below the configured EV-before-export
threshold during the configured evening export window, protect the energy still
needed by that EV before allowing any sale. If enough discretionary battery
energy and electrical headroom remain, charge the EV while the existing export
controller runs Force Discharge. This can preserve an export opportunity that
would end before a sequential EV-then-export handoff could use it.

The extension changes arbitration between the existing controllers. It does not
introduce a wrapper, automation, poller, actuator writer, tariff optimiser or
replacement charging algorithm. It reuses the saved EV threshold, evening window,
efficiencies, current limits, outside-window inverter percentage, protected
baseline, house/battery reserves, paid-export cap and existing control cadence.
The only proposed new operator choice is an explicit opt-in to overlap; its
configuration representation needs review before implementation. Do not infer
that opt-in from the existing EV-priority switch or create extra rate, reserve,
margin or timing settings for this design.

Initial scope is the commissioned direct-Tessie EV path and an HEO-owned export
session within the configured evening window. The smart-socket path has no new
authority. Existing away/disconnected policy is unchanged: a low-SoC absent EV
does not gain charging authority or an exemption from the current export gate.
Price admission may use this arbitration only inside that same evening window,
with its independent permission, original actuators and absolute deadline intact.

## Existing authority and proposed seams

The canonical provenance remains the reference implementation recorded in
[the export policy](zerohero-export-policy.md): protected house energy, mandatory
connected-EV energy, Sellable, bounded fixed discharge, latest start and durable
Self Use recovery. Concurrent discretionary EV charging/export is an extension,
not a ported reference behavior. The current software record in
[source of truth](source-of-truth.md) takes precedence over older descriptions of
the first-stage EV gate.

| Existing authority | Preserved decision | Proposed extension seam |
| --- | --- | --- |
| `planner/ev_before_export.py` | Below-threshold hold, inclusive target crossing, existing three-minute energy/current calculation | Pure shared allocation result with separately named EV reservation, net export allowance and infeasibility reason |
| `planner/export.py`, `planner/foxess_export_policy.py` | Available energy, efficiencies, protected ledger, paid cap, configured bounds and ordinary latest start | Clip the overlap candidate using energy remaining after EV protection and physically achievable **net** export in the remaining window |
| `ev_active.py` | One selected EV stage, existing current/limit reconciliation, fresh per-command budget check, baseline/stop and retry duties | Accept only a matching qualified HEO-owned Force Discharge cohort instead of requiring idle export/Self Use for this opted-in decision |
| `active.py`, `planner/export_session.py` | One inverter owner, persist-before-write, fixed bounded gross discharge, retry/cleanup and price authority | Replace the EV-baseline-only admission guard with the same shared decision while overlap qualifies; retain the physical baseline handoff elsewhere |
| `planner/foxess_ownership.py`, existing journals | External modes are not adopted; unfinished HEO ownership and cleanup survive restart | Bind overlap to existing session/actuator ownership; no independent owner or restoration mechanism |
| Existing capacity resolver, load composition and paid-export ledger | Explicit capacity provenance, EV subtraction once, measured cap union | Consume those same qualified inputs; add no guessed capacity, house meter, EV quota or cap counter |

Before implementation, freeze characterization of these current seams, including
their existing exclusivity. Extend the pure policy inputs/results and existing
facades only after those tests pass. Ordinary opt-out decisions must remain
identical.

## Energy and power accounting

Use one coherent, current feedback cohort and one explicit AC energy basis:

- `A` is battery energy above the existing floor/additional reserve, converted to
  deliverable AC energy using discharge efficiency **once**.
- `H` is the existing remaining protected house requirement.
- `R` is the existing protected EV ledger, including mandatory connected baseline
  and applicable daily-ready protection, each counted once.
- `S = max(A - H - R, 0)` is protected Sellable **before** export-cap or window
  clipping. The hidden or zero planned-export value is not the EV energy pool.
- `Q` is the full still-undelivered wall energy needed to reach the configured
  EV threshold. Use the existing selected capacity/SoC calculation and charging
  efficiency **once**. A pack-energy shortfall is not already wall energy.
- `Q_add` is the part of `Q` not already reserved for that exact delivery
  obligation inside `R`. Export may use at most `max(S - Q_add, 0)`; strict
  positive excess is required for overlap. Equal energy protects the EV only.

Reservation composition must be auditable by obligation and delivery interval.
Do not subtract a baseline kWh from Sellable and then reserve that same kWh
again inside the threshold top-up. Equally, do not subtract all of `R` from `Q`
or use `max(R, Q)` without proving that those obligations overlap. Baseline after
threshold completion and independent daily-ready duties still need protection.
If existing records cannot prove the overlap, withhold concurrent export until
the reservation can be represented unambiguously; retain the current exclusive
policy. This is not authority to change daily-ready accounting: this top-up
remains excluded from daily-ready delivery, and cannot erase its reservation.

Reserve the **full** remaining requirement when the existing top-up is allowed
to continue after the export finish. A window-clipped EV delivery estimate is
useful for timing, but is not the EV reserve. Never release the undelivered
balance merely because it cannot be charged before export ends. A target above
the ordinary permitted EV SoC ceiling is infeasible under normal policy; retain
the below-threshold export hold and show that reason rather than silently lower
the export preference or invoke Full. A lower rate also changes time feasibility,
not the protected energy requirement.

On one common AC power boundary, the physical balance is:

`net export = gross inverter discharge + measured solar - house-only load - EV load`

For a hypothetical 15 kW gross inverter discharge, 7 kW EV load and 1 kW house
load with no solar, net export is **7 kW**, not 15 kW. The same inverter output
serves all three flows. This balance must use the commissioned topology and
existing AC/DC conversion semantics; an actuator target alone does not prove
that physical output is present. No conversion loss is applied a second time to
an already AC value. House-only load removes EV once only where the configured
meter includes it. Requested EV current is not measured EV consumption.

Use the commissioned inverter/native actuator limits for the existing gross
Force Discharge request. Preserve its fixed-power session semantics; do not add
EV kW to that request or introduce continuous inverter modulation. Estimate the
concurrent net export headroom from qualified house/EV flows, configured grid
export limit and the remaining window. No future solar is guaranteed; measured
solar is usable only with its existing freshness/provenance. For the overlap
candidate, planned net export is bounded by all of:

`energy after full EV protection`, `remaining shared paid cap`, and
`achievable net export over the remaining authorised window`.

The last term must reflect the EV charging period and, if feasible, its later
baseline/off period. Do not project an hour of charging into a half-hour window
or use the full configured window after a late arrival. Reuse latest-start
arithmetic with this bounded overlap candidate; a newly due opportunity may
start now within the existing window. This extension must not change ordinary
opt-out latest-start arithmetic or extend a finish/deadline.

The cap is consumed by qualified **measured net grid export**, using the existing
paid-cap union exactly once. EV and house consumption reduce the battery energy
pool but do not consume exported kWh. Do not deduct a projected export from the
measured cap, count gross battery discharge as export, or decrement a persistent
EV shortfall from commanded current. Recalculate undelivered threshold energy
from qualified vehicle evidence; account for confirmed wall consumption through
the existing flow/energy paths without also subtracting it from a second pool.

## Priority, ownership and lifecycle

House energy, battery floor/reserve and protected EV obligations remain ahead of
discretionary export. The EV receives its existing safe current allocation;
export uses the residual energy and physical output. Its current still obeys
connector minimum/maximum/step, actual service/phase headroom, total outside-window
inverter percentage, battery reserve and normal SoC ceiling. The feature cannot
raise those limits to meet a threshold sooner. Full/Trip/free-window and already
active daily-ready priority remain unchanged.

One shared immutable allocation decision must authorise both controllers for a
specific coherent input/configuration generation and existing session owner.
`ActiveEvController` remains the sole EV writer and `ActiveFoxessController`
remains the sole normal inverter writer. Their independent locks alone do not
establish a cross-controller transaction: add a narrow shared arbitration/fence
at the existing boundary, with a documented lock order, rather than acquiring
each other's locks or creating another task that writes. Check that decision
and live gates before each positive command and after every awaited checkpoint
or settlement delay. A new cohort invalidates the old decision; a command-only
cache mutation is not a new measurement.

Admit overlap only from known idle/clean sessions or a matching already-owned
export session with valid journals, original actuator bindings and fresh
physical feedback. Qualified Force Discharge is not a blanket alternative to
Self Use: foreign/manual/diagnostic/charge ownership, unknown journals or a
different session must fail closed. Persist the existing export latch before
positive inverter intent and preserve EV reconciliation checkpoints. If a
durable association is needed, extend the existing journal compatibly with the
minimum provenance; do not claim an in-memory flag survives restart or add an
independent overlap Store/timer.

The overlap path requires a live residual-energy check even for an ordinary
latched evening session: if reserves shrink, house demand rises, net export
headroom disappears or the protected EV requirement grows, withdraw overlap
through existing export cleanup while protecting the EV first. This is a
separately tested exception for the opted-in path; ordinary fixed sessions keep
their existing semantics. Material grid import or service overrun still invokes
the existing immediate EV safety response as well. Clouds are real power loss,
not missing evidence; neither permits spending protected energy. Aggregate net
export does not prove safe phase loading, so unbalanced/missing per-phase
evidence cannot authorise an EV increase.

At threshold completion, re-plan the remaining normal export opportunity and
hand EV current to its configured baseline/off or authorised successor. Use
fresh actual feedback while that handoff settles; a remembered lower target is
not proof. At export finish/cap exhaustion/price withdrawal, use existing Self
Use/zero-target cleanup; the EV may continue only under its independently valid
existing top-up authority and remaining full protection. Never lengthen a price
deadline, bridge beyond its existing expiry rules, revive an expired session
through the evening latch, raise latched power, or relabel an opportunity as a
retailer payment.

Disconnect, stale/invalid capacity/SoC, failed telemetry or ambiguous home/cable
evidence withdraws overlap and retains pending duties. Do not enlarge away
policy, treat unknown as unplugged, or command the EV while away. A qualified
reconnect recomputes the current requirement, budget and time; it neither
restores an old allocation nor grants a new Full/Trip timeout. On restart,
reconcile retained ownership/cleanup first and wait for the existing startup
readiness and qualified physical evidence. Old price permission and a restored
allocation are not new admission. Failed checkpoints block new/increased
intent and preserve cleanup obligations.

All existing master/owner/commissioning/sign/mapping gates remain. Safety Lock
blocks **every** hardware write, including cleanup; retain duties for a later
authorised reconciliation. A manual hold, diagnostic, external owner or higher
EV policy withdraws overlap through the existing handoff. Keep current retry
spacing, attempt bounds, Full/Trip absolute timeouts and source expiry. Disabling
the proposed option returns to exclusive EV-before-export arbitration, with
confirmed cleanup/physical handoff before any later start. A software gate
cannot establish that unrelated automations or cloud writers are disabled.

## Twelve concrete acceptance scenarios

All times, powers and energies below are synthetic test inputs, not site facts
or runtime defaults. Energy figures are AC/wall values after the existing
efficiency conversions. Unless stated otherwise, threshold energy is additional
to the base EV reservation, telemetry/gates are qualified, other owners are idle,
the daily cap is ample, and charging has no taper. Real delivery can be lower.

| # | Concrete scenario | Expected consequence |
| --- | --- | --- |
| 1 | Overlap opt-in is off; connected EV is below the saved threshold with 12 kWh Sellable. | Existing exclusive top-up/export hold and physical baseline handoff are unchanged, including after reload. No overlap decision grants a command. |
| 2 | Opt-in is on, one hour remains, Sellable is 20 kWh, threshold shortfall is 7 kWh **wall** energy, gross discharge is 15 kW, EV is 7 kW and house is 1 kW, with no solar. | Protect all 7 kWh for the EV. Concurrent net export is at most 7 kW/7 kWh in that hour, while EV receives at most 7 kWh wall energy. Never plan 15 kWh export plus 7 kWh EV. |
| 3 | Synthetic window ends at 21:00; arrival is 20:30, Sellable is 12 kWh and EV needs 7 kWh **wall** energy at 7 kW; gross/house powers are 15/1 kW. | EV needs one hour even without house demand, so only 3.5 kWh wall energy can arrive before finish. Reserve the full 7 kWh, permit at most 3.5 kWh net export in the remaining half-hour, stop export at 21:00, and protect the remaining 3.5 kWh for any still-authorised post-window top-up. Do not claim the EV reaches threshold by 21:00; a 7 kWh pack-energy deficit would take longer when charging efficiency is below 100%. |
| 4 | Sellable is 6 kWh while the additional threshold requirement is 7 kWh. | No discretionary export; existing top-up may use only its safely available budget. Report a 1 kWh funding shortfall, without consuming protected house/battery energy or importing to fill it. |
| 5 | Sellable is 12 kWh, EV needs 7 kWh, and paid-export allowance remaining is 1 kWh despite a much larger raw export candidate. | Reserve EV energy from Sellable before cap clipping; at most 1 kWh measured net export consumes the remaining cap. Its exhaustion ends Force Discharge through existing cleanup, while the cap does not incorrectly limit EV charging to 1 kWh. |
| 6 | EV needs 7 kWh wall energy but the saved outside-window/connector rate cap permits only 3.5 kW; one hour remains, gross discharge is 15 kW and house is 1 kW with no solar. | Plan at least two hours to threshold and only 3.5 kWh maximum pre-finish EV delivery; retain the full reserve. Net export headroom is now at most 10.5 kW, still bounded by residual energy/cap. Never raise current or bypass the normal SoC ceiling; a ceiling below the configured threshold withholds overlap as infeasible. |
| 7 | An admitted 15 kW gross/7 kW EV overlap loses measured solar, then a house burst leaves no positive net export headroom or reduces residual energy below its reservation. | Recompute the single balance immediately; withdraw overlap and clean up export rather than export the EV/house reserve. Apply the existing EV import/overrun curtailment when required; no held target or cadence delay preserves unsafe power. |
| 8 | Aggregate grid power shows export, but one commissioned service phase is overloaded or its current/voltage evidence becomes unavailable. | Do not infer balance from the aggregate. Apply existing phase/service limits, block EV increases and retain the applicable baseline/stop duty; no overlap permission bypasses missing phase evidence. |
| 9 | A dedicated capacity source is invalid/stale and has no valid explicit fallback while EV SoC remains below threshold; alternatively the native vehicle frame expires between staged commands. | No guessed pack capacity, ratio fallback after explicit opt-in, fetch-time freshness or command acknowledgement grants overlap. Block new/increased commands, withdraw overlap safely and preserve existing cleanup; only a new qualified cohort can reconsider it. |
| 10 | EV disconnects during overlap below threshold, then reconnects with fresh evidence before the original evening finish. | Withdraw the shared allocation and reconcile owned export cleanup; keep existing absent-EV export policy and stop duties. Reconnect recomputes actual shortfall, reserves, cap and remaining time without an old allocation, duplicated delivery credit or timeout reset. |
| 11 | Home Assistant restarts after the export latch is saved but before Force Discharge confirmation, or while its cleanup is unconfirmed. | Existing journals retain ownership/duties; no new positive intent precedes startup readiness, fresh physical feedback and durable reconciliation. External Force Discharge is not adopted, and restored/expired price permission cannot restart overlap. |
| 12 | A higher-priority Trip/Full/free/manual request arrives during overlap; Safety Lock closes before cleanup, and any price permission expires while locked. | Higher priority removes overlap; the lock causes zero hardware writes and retains pending cleanup. On unlock, finish eligible cleanup before fresh admission, preserve original Trip/Full timeouts, and never revive the expired price session or add competing writers. |

## Proposed implementation and proof plan

First capture current golden outcomes for the pure EV gate, Sellable calculation,
EV priority selection, baseline handoff, ordinary fixed export sessions and
source-clock checks. The document is not permission to relax the recent
awaited-publication correction: every energy recheck must capture its complete
cohort at the actual check time and restore enclosing cycle context.

Then add a pure allocation calculation at the existing policy seam, returning
full threshold requirement, already-covered requirement, additional reserve,
safe EV target, residual energy, estimated net export/time bound and explicit
reason. Reuse existing conversions and rate/target planners. Characterize each
reservation composition before allowing the controllers to consume it. Test
efficiency below 100%, zero/NaN/infinite capacity, exact threshold/equality,
sub-minimum current steps, already-protected keepalive and independent
daily-ready obligations. The same physical kWh must appear once in each ledger
where it belongs and never fund two obligations.

Wire the optional decision into the existing two admission checks under the
shared fence, retaining all reducing paths. Test the twelve scenarios above as
table-driven pure cases and time-sequenced actual-controller replays. Vary
configured windows, phase counts, voltages, inverter/connector ratings, zero and
nonzero baseline, normal EV ceiling and export cap without site literals.
Simulate measured battery/house/EV/net-grid energy minute by minute: confirm
energy conservation, the late-arrival shortfall, cap consumption only from net
export, no invented solar and no incremental rounding energy. A green planner
test alone does not prove command sequencing or physical delivery.

Exercise both callback orders and publication during every await: storage,
current/limit/start services and inverter settlement. Inject source expiry,
out-of-order/future/restored data, wrong native binding, command-cache changes,
clouds, a house burst, phase imbalance, disconnect/reconnect, cap exhaustion,
configuration edits, option disable, higher owners and price deadline expiry.
Assert one selected EV writer, one explicit inverter owner, no positive command
from stale authority and no cleanup from an old decision stopping a newer owner.

Reload/restart at every export phase and EV handoff, including missing/malformed
journals, failed saves, retained positive baseline, pending zero-baseline stop,
Feed-in First fallback, external modes and original-actuator changes. Preserve
existing retry/timeout bounds and absolute Safety Lock behavior. Confirm opt-out
parity and backward-compatible store loading/rollback before release work.

Expose the allocation/reason through existing status/read-model surfaces rather
than a new dashboard or helper source of truth. Display full EV wall-energy
need, deliverable-before-finish estimate, protected remainder, gross discharge
versus estimated/measured net export and infeasibility separately. Plan values
must describe currently authorised actions, with unavailable estimates shown as
unavailable.

Implementation would require independent review, full repository validation and
the normal source-of-truth/roadmap/requirements/changelog updates. Release,
installation, named-site configuration and controlled physical acceptance remain
separate approved operations after the settling period. Acceptance must verify
actual net export, EV energy and protected house reserve; it cannot infer
retailer payment or the absence of another writer from software tests.
