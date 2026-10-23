# EV backfill timing and daily ready-by allocation

HEO retains the Working Single Phase Pilot Site's proven latest-start EV
backfill as the no-solar path of the explicit **Conservative** choice.
**Ready by** is the default timing and uses currently available battery surplus
before departure through the
existing daily ready-by planner and session, then retains the original late
pre-free opportunity. It works with no fixed daily EV
allocation. Both timing choices require the pre-free backfill policy to be
enabled and Local Modbus ownership.

The additional **Use spare energy when plugged in** timing admits that same
protected charging promptly after export, rather than waiting for a latest
start. It is opt-in; the existing Ready-by default is unchanged.

The fixed daily ready-by allocation remains a separate operator choice. Its
existing energy protection, proportional surplus calculation, and FoxCloud
compatibility are retained when Conservative timing is selected. Ready by is a
configuration extension, not a claim that the pilot already had this behavior.

## Proven source retained

| Decision | Pilot source | HEO implementation |
| --- | --- | --- |
| Work in AC wall energy | `configuration_v1.4.24.yaml:4037-4057` | Battery energy above floor and configured reserve is converted with configured discharge efficiency before comparison with wall demand. |
| Protect remaining house demand once | `configuration_v1.4.24.yaml:3780-3915` | The occupancy-aware remaining house budget is subtracted once. |
| Cap by vehicle room | `configuration_v1.4.24.yaml:4119-4188` | Planned wall energy cannot exceed room to the configured EV soft limit. |
| Calculate duration and latest start | `configuration_v1.4.24.yaml:4250-4308` | Discrete power determines duration; scheduling works backwards from the configured ready time. |
| Freeze an active phase across restart | `configuration_v1.4.24.yaml:686-692,4273-4295` | Cycle, delivered energy, session target and frozen start are stored in Home Assistant storage. |

## Configuration

In **EV Charging policies**, select **Backfill timing**:

- **Conservative — finish before free power** retains the original late
  pre-free session without a measured morning-solar opportunity. Enabling both
  morning solar and pre-free also permits the combined opportunity described
  below; the daily allocation's Conservative arithmetic is unchanged.
- **Ready by — use available surplus before departure** schedules currently
  discretionary battery energy toward the existing daily ready-by time.
  Charging may start overnight after midnight. It does not need a fixed daily
  kWh allocation and adds no new protection to the previous evening's export.
  After that deadline, remaining safe surplus can still use the original
  latest-start backfill before free power; it is an additional opportunity.
  This is the default for new entries and existing entries without a saved
  timing choice.
- **Use spare energy when plugged in** starts promptly after the configured
  effective export finish whenever a home-connected direct-EVSE vehicle has
  current protected surplus and room to its normal target. It does not wait for
  a latest start. It reuses this daily session before the canonical ready time
  and the existing pre-free successor after it. No new deadline, reservation or
  inverter/EV writer is introduced. Qualified price export may request physical
  handoff; all existing EV-minimum/reserve and electrical gates still apply.
  See [prompt timing and lifecycle](ev-post-export-design.md).

Native `select.home_energy_ev_backfill_timing` exposes the same saved choice on
a dashboard. The new mode's **Spare-energy restart margin** is adjustable in
setup and `number.home_energy_ev_surplus_rearm_energy` (0–5 kWh, default 0.1).
It prevents small budget fluctuations from repeatedly restarting the charger;
active funded charging is not stopped early solely because it is below that
restart margin. Zero deliberately removes the extra admission band.

Upgrade preserves an explicitly saved Conservative choice. It changes only
the missing timing selection: neither Automatic EV Control nor the pre-free
backfill enable switch is turned on if it was off. An already enabled
pre-free policy without a saved timing choice adopts Ready by.

Enable **Use spare home-battery energy for EV before free power** to use either
choice. Ready by requires a ready time strictly after midnight and before the
configured free-power start, a positive commissioned inverter output/discharge
limit, and a positive maximum outside-window inverter percentage. The deadline
is not silently moved to the next day to make an invalid configuration fit.
An old invalid ready time or missing power limit holds Ready by inactive;
runtime does not fall back to conservative charging or spend an unproven
budget. Reconfiguration rejects the invalid enabled Ready by setting until the
operator corrects it or explicitly selects Conservative.

The optional fixed daily wall-energy allocation uses the same ready-by time,
inverter percentage, and planning buffer. Setting its kWh value to zero
disables only the fixed allocation; Ready by surplus charging can still run.

## Fixed daily allocation retained

The extension adds four site inputs: daily protected EV wall energy, ready-by
time, maximum outside-window EV power as a percentage of commissioned inverter
output, and an optional planning buffer. Zero protected energy disables the
fixed allocation.

The accounting cycle runs from one ready deadline to the next, not midnight.
This matters when HEO owns Local Modbus export: an evening export must retain
energy intended for the following morning. Charging itself is restricted to
midnight through the ready deadline.

With Conservative timing, the fixed-allocation planner retains these decisions:

1. Remaining allocation is configured allocation minus confirmed wall energy
   delivered by this policy in the current ready cycle.
2. Energy available after battery floor and fixed reserve is converted to AC.
3. The remaining occupancy-aware house budget is protected.
4. The remaining EV allocation is protected next.
5. Any energy beyond both protections is discretionary. The policy offers the
   fraction `hours until ready / hours until next free window`, capped at one.
6. The result is capped by current vehicle room and the live ZEROHERO export
   plan. A protected daily allocation reserves energy from earlier export; it
   does not itself create permission to drain the house battery later.
7. Current is capped by the configured inverter percentage, connector rating,
   and current service headroom, then rounded down to the actuator step.
8. Duration determines the latest start. A plan that would have needed to start
   before midnight reports an explicit shortfall/unachievable state.

## Ready by uses the current safe surplus

Ready by reuses that planner with the full currently discretionary energy
budget instead of its proportional share. Battery energy above the floor and
fixed reserve is converted to wall energy, the remaining house-demand budget is
protected once, and the remaining fixed EV allocation is accounted for once.
The resulting total is capped by the live ZEROHERO discretionary/export plan
and the vehicle's room to its normal charge target. Energy withheld from an
earlier export is not automatically spendable and no future surplus is assumed.

If a fixed daily allocation is also configured, its existing export protection
is retained. Ready by adds no second reservation, target, or energy counter:
confirmed ready-by wall energy reduces the same ready-cycle allocation. With
the allocation at zero, only currently safe surplus is offered.

The planning window runs from midnight to that morning's ready deadline.
Current remains bounded by the outside-window inverter percentage, connector
rating, actuator step and service headroom. The configured outside-window
house-battery reserve, which defaults to 20%, and the normal EV charge-limit
policy still apply; direct-EVSE commands remain capped at 90% while Charge to
Full is off. The existing duration and planning-buffer arithmetic determines
the latest start. Ready by uses elapsed time across daylight-saving changes
and displays the resulting start in the configured local time zone.

Ready by requires fresh, coherent grid and effective battery-power evidence,
fresh mapped house-load evidence, valid battery energy and house protection,
and no competing HEO export session or export window. Grid import above the
commissioned ZEROHERO zero-import threshold curtails extra EV charging.
Unavailable or invalid energy inputs, lost reserve, disconnection, vehicle
limit, or a closed control gate end the surplus session through the existing
stop or protected-baseline reconciliation.

## Handoff after the ready time

Ready by is an earlier opportunity, not a replacement for pre-free backfill.
Before the ready deadline, it owns battery-backed backfill. At that deadline
the daily session ends and the original latest-start pre-free planner becomes
eligible again. It calculates against the upcoming free-power start, not
tomorrow's ready time. This does not mean charging starts immediately: with a
small remaining budget it may still wait until nearer free power.

Late backfill uses only the current safe budget. Earlier EV charging and house
use do not leave another copy of the earlier allocation to spend. The existing
live house protection, reserve, export cap and next ready-cycle fixed allocation
remain binding. The Ready by evidence checks also continue after its deadline;
invalid timing or missing/stale inputs cannot grant fallback permission.

Eligible measured morning solar can charge while late backfill is waiting.
With both morning solar and pre-free enabled, a fresh positive raw net-solar
surplus and current protected battery budget can instead start a combined
request before latest start. Battery power is paced over physical elapsed time
until free start and added to measured net solar and the separately protected
keepalive. The total is rounded down once and bounded by the saved outside-window
inverter percentage, connector and service limits. The percentage is not a
battery-only limit. A representable combined request can start even when solar
alone is below the charger's minimum. No-solar latest-start behaviour remains;
once admitted, passing clouds can leave battery pacing active with measured zero
solar, but missing/stale authority cannot do so.

This is one selected pre-free current owner, not two competing writers. It
adopts the latest safe combined target on a ten-minute adjustment cadence,
without requiring a moving energy/time candidate to stay unchanged for ten
minutes. Standalone solar keeps its existing stable-target hysteresis. Immediate curtailment remains for
reduced protected battery authority, import, service headroom, reserve/target or
data/gate loss. It does not weaken Ready-by admission or its after-deadline
evidence checks. Caps, time and vehicle room can leave safe battery energy
unused. See the [combined pre-free contract](ev-combined-pre-free.md).
Free-window charging takes over independently at its configured start. Charge
to Full retains its separate paid override.

Both opportunities use the existing controller and session state. A pending
daily stop cannot interrupt an authorised successor, but remains effective if
extra charging loses authority. Without an eligible successor, the configured
protected baseline applies: a nonzero keep-alive is retained; zero means stop.

## Shared session and restart behavior

Only the start time is frozen. The energy authority remains live and may only
shrink: loss of genuinely sellable energy stops the session immediately. The
active session also stops at its remaining target, the EV soft limit, the
ready deadline, the outside-window house-battery reserve or hard floor, or
disconnect. A configured
0 A protected baseline means stop, not Tessie's minimum current. Only confirmed Tessie
actual current is integrated into delivered wall energy; gaps beyond the
configured telemetry age are not guessed. Both ready-by uses share the same
persisted ready-cycle ledger, session target, delivered energy and bounded
stop-retry obligation across reload and restart. A nonzero protected baseline
is reconciled instead of stopping the connector. Free-window charging and paid
Charge to Full charging do not count as ready-by delivery. Late pre-free
charging also does not consume tomorrow's fixed ready-by allocation ledger.

### Confirmed return to a powered baseline

Ending backfill is not always a request to switch the car off. If a positive
protected baseline is configured, the completed handoff is fresh confirmation
that requested and actual current match that representable baseline, the car
is connected and charging, its switch is on, and its limit/target feedback
agrees with the existing direct-EVSE planner. No active surplus, Full/Trip or
recovery owner may be discarded. Missing, stale, restored or contradictory
feedback leaves the pending obligation intact.

HEO retires only the old daily-stop fields and checkpoints them immediately;
it retains keepalive ownership and delivered-energy accounting. Failed storage
restores the pending fields before the cycle can proceed. The zero-baseline
path remains a real stop requiring switch-off acknowledgement. This lifecycle
repair is not permission to restart during charging or bypass maintenance.

| Existing source | Retained meaning in this correction |
| --- | --- |
| Pilot `configuration_v1.4.24.yaml` current-target fallback | Outside charging returns to its configured protected baseline, not an invented stop/start. |
| `end_daily_backfill_session` and `_async_restore_ready_by_baseline` | Keep the pending duty until the existing direct reconciliation and fresh physical feedback prove handoff. |
| Existing version-one EV store and zero-baseline stop reconciliation | Persist cleanup with rollback on failure; retain true switch-off duties and all energy/session state. |

## Ownership

The fixed daily allocation writes Tessie only, so it can operate with FoxCloud
Scheduler as the inverter owner. It never writes a FoxESS entity. With FoxCloud ownership the
allocation is opportunistic: prior cloud-controlled export may already have
spent it, and the live post-midnight energy ledger decides what remains.

With Local Modbus ownership, HEO's ZEROHERO export calculation additionally
protects the remaining allocation for the next ready deadline. That prospective
guarantee is unavailable when another controller owns inverter discharge.

Ready by surplus timing requires Local Modbus ownership even though its
commands also go only to Tessie. It relies on the existing protected
discretionary/export plan. Selecting it does not grant inverter write authority
or prove the absence of a VPP or another external writer.

Safety Lock, EV commissioning, sign verification, explicit mappings, service
limits and bounded reconciliation remain mandatory.

## Charge to Full exception

`switch.home_energy_ev_charge_to_full` is an explicit paid-grid exception. It
starts charging outside the free window and bypasses the daily energy and
inverter-percentage caps, but never the commissioned connector or service
limits. It clears at 100%, after disconnect once started, or after its configured
maximum duration. The dashboard should make the paid-import possibility clear.
It takes over from a ready-by surplus session, which stops accumulating
ready-cycle delivery until eligible ready-by charging resumes.

## Verification boundary

Implementation and automated regression coverage do not establish live-site
acceptance. The broader generated full-system lifecycle and incident harness
remains outstanding.
