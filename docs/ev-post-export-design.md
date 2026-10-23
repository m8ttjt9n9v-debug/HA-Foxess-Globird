# Post export EV charging design

The `when_connected` extension reuses the existing backfill timing policy. After normal export
finishes, a home-connected EV can use currently discretionary battery energy
promptly instead of waiting for a calculated morning start. Reuse the protected
energy calculations, backfill sessions and Tessie writer; do not add another
scheduler or multiple ready-by deadlines. Installing its code does not activate
control or select this choice.

## Operator choice

**Use spare energy when plugged in** is the third **Backfill timing** selection,
alongside **Conservative** and **Ready by**. Setup and the native dashboard select
share that same persisted option. Upgrade preserves saved settings and the
current default; selecting the new timing does not enable the EV master or
pre-free policy switches.

Keep the existing ready-by time, outside-window inverter percentage, normal EV
target, battery reserve and electrical limits. There is no new evening clock,
fixed energy allocation, vehicle SoC target or paid-grid override. A fixed daily
allocation of zero must still allow discretionary charging.

The new choice requires the existing Local Modbus ownership and commissioning
conditions and initially supports the direct-EVSE path only. Reject or visibly
hold the choice for a smart-socket path rather than silently bypass its separate
outlet staging/recovery contract. It inherits the valid ready-before-free
deadline requirement rather than silently moving an invalid time. Extended Away
and predicted return-home energy remain separate deferred work; household
Auto/Away is not a substitute.

## Reuse rather than extra deadlines

| Existing component | Retained role | Narrow extension |
| --- | --- | --- |
| `planner/control_windows.py` | Configured export-finish to next-free interval, including evening and midnight | Use this existing interval for prompt admission; validate ambiguous or overlapping bounds |
| `planner/ev_daily_backfill.py` | Protected energy, vehicle room, shrinking session target and ready-cycle delivery ledger | Open the daily planning interval at the preceding export finish and permit explicit immediate admission before ready |
| `planner/ev_outside_window.py` | Pre-free session, supported current steps, normal target and live total current envelope | Permit the existing successor to start promptly after ready, using the same live budget |
| `ev_active.py` protected-budget guard | Raw Sellable plus fresh battery, house, EV and ownership evidence | Extract a shared guard without changing existing callers' policy semantics |
| `planner/ev_before_export.py` funded current conversion | Representable current funded over the existing short decision horizon | Reuse the arithmetic, not the minimum-SoC recovery obligation |
| Existing EV reconciliation and storage | Single writer, confirmed delivery, restart and bounded cleanup | One additive optional owner flag in the existing version-one journal retains cleanup after mode edits; no second dispatcher or synthetic Full lease |

The pilot provenance remains the protected wall-energy/vehicle-room calculation,
latched pre-free phase and live bounded current documented in
[EV backfill timing](ev-daily-ready-backfill.md). Immediate admission is a
separately configured extension, not a claim of original pilot parity.

Merely widening the current daily planning window still produces
`waiting_latest_start`: its planner always works backwards from the deadline.
Extra ready deadlines are more disruptive. `roll_daily_backfill_cycle()` resets
delivered energy, closes an active session and renews the next fixed allocation
when the deadline changes. Do not manufacture a rolling deadline or reset that
ledger to make charging start sooner.

## Timing and accounting

Use the existing chronological export-finish to next-free interval. Exclude an
active normal paid window as the current Ready-by policy does; an early force
finish must not quietly introduce concurrent evening export and EV charging.
The clock opening alone is not permission: positive commands also require
completed export cleanup and fresh Self Use/zero force-target feedback.

| Interval | Existing session used by this mode | Accounting |
| --- | --- | --- |
| Export finish to the canonical ready deadline | Daily backfill | Confirmed delivery reduces the existing upcoming ready-cycle allocation once |
| At and after ready, before next free start | Existing pre-free successor | Preserve next cycle's fixed allocation; late delivery must not count toward tomorrow |
| At free start | Existing free-window controller | End discretionary ownership immediately and apply the saved free-window priority and settlement policy |

Midnight is not a new ready cycle. At the ready deadline, reuse the existing
authorised-successor handoff rather than issue a hardware stop/start solely
because the accounting category changed. Keep any genuinely outstanding cleanup
duty; the successor cannot erase it when authority is absent.

Unplugging prevents further commands but does not turn off the saved timing
policy. Reconnection triggers fresh eligibility and current-energy checks, not
renewal of an old energy allowance. Restart restores the same journal and counts
confirmed endpoint samples using the existing maximum-age rule; longer or
invalid gaps are not estimated.

Do not redefine existing EV-before-export top-up delivery as daily delivery as
a side effect. Its current recovery/accounting contract remains distinct. Tests
must cover transition from that recovery into prompt daily/pre-free ownership.

## Energy and current

Use **Sellable**, not **Planned export**. The latter is clipped by paid-export
allowance and time-window capacity: it can be zero while discretionary energy
remains. The EV must not be limited by a retailer's export cap, and this feature
must not change that cap or its counter.

Reuse the current guarded budget:

1. Bound available AC energy by both cached and freshly recomputed battery
   evidence, after the existing floor/reserve and discharge efficiency.
2. Protect remaining learned house demand and existing EV reservations once.
3. Cap discretionary energy by raw Sellable and wall-energy room to the normal
   automatic target. Keep actuator anti-pause headroom out of that target.
4. Derive funded current with the existing short-horizon energy-to-current
   conversion, then cap TOTAL EV current by the outside-window inverter
   percentage, service headroom, connector rating and supported steps.

Do not subtract delivered energy a second time from the live battery balance:
it already reflects that consumption. The daily ledger only reduces an
applicable fixed reservation. A positive but tiny budget must not authorise
full capped current. The configured normal automatic target and existing
non-override ceiling remain binding; this mode is not Charge to Full.

Revalidate the same live authority after awaited saves and before every positive
command, including retries and current increases. Include the mode in the
existing continuous-recalculation and current-cohort capture paths; changing
only the planner's displayed start is insufficient.

## Priority and physical handoff

Retain Safety Lock, disabled control, manual/diagnostic ownership and all fresh
safety evidence requirements. Active Trip/Full and free-window charging retain
their existing precedence. A future armed Trip does not grant its paid override
early: ordinary surplus can charge now, reducing the later shortfall naturally.

Qualified critical-event export intent takes precedence over discretionary
charging when this timing is enabled, including a daytime solar predecessor.
The normal
minimum-EV-SoC, reserves, source authority, cap and event-deadline gates still
apply. A high price alone is not permission to bypass the EV minimum or proof
of retailer payment.

Check eligible price-export intent BEFORE its physical handoff check. Otherwise
the EV can continue because the export session is idle while export stays idle
waiting for the EV to stop. The EV yields through the existing baseline/stop
reconciliation, then export requires physical handoff confirmation. Loss of
price authority during cleanup must not leave a permanent hold.

The existing physical handoff helper currently short-circuits when the optional
EV-before-export preference is off. Prompt charging needs the same no-overlap
proof independently of that preference. Do not implement simultaneous forced
export and discretionary EV charging in this change.

## Stability and hysteresis

Reuse the existing latched session and bounded funded-current calculation.
Normal budget consumption must not continually move the session's start or
inflate its target. A completed session can restart only from newly qualified
live energy, never its retained original plan.

An exhaustion regression demonstrates that the latch alone can repeatedly
restart under tiny budget jitter. **Spare-energy restart margin** is therefore
one explicit setting shared by setup and its native number: 0–5 kWh in 0.01
steps, default 0.1. Inactive admission requires enough protected energy for the
minimum representable increment plus this margin. Active, funded continuation
can use the remaining energy below that admission boundary. Zero deliberately
removes the extra band. Ready handoff/restart retain confirmed continuation,
not a renewed start allowance. Mode/source/limit edits re-evaluate immediately.

The existing configurable import confirmation is explicitly reused for an
already-owned matching current in this mode, not applied globally. Hard safety
stops remain immediate; the original timestamp persists, and fresh starts,
increases and positive retries remain strict during import. Policy handoff
cannot renew the import deadline. Existing Conservative, Ready-by and independent
solar import semantics remain unchanged.

## Required lifecycle regressions

| Scenario | Required result |
| --- | --- |
| Before, at and after export finish | No premature start; eligible start after actual cleanup |
| Arrive above the export minimum | Charge without inventing a minimum-SoC recovery duty |
| Arrive below the minimum | Preserve buffered recovery and transfer cleanly to prompt surplus |
| Paid cap used up or planned export zero | Raw protected surplus can still charge the EV |
| Automatic export switched off | No export command; independently enabled prompt EV policy can still use valid discretionary energy |
| Zero and nonzero fixed daily allocation | No duplicate protection or delivered-energy credit |
| Small budget, shrinking budget, larger new budget | Funded supported current; no target inflation or phantom energy |
| Exhaustion, repeated/jittering values and slow drift | Stable stop/rearm with immediate unsafe-authority withdrawal |
| Normal EV target and battery reserve boundaries | Stop at existing limits without using actuator headroom as an energy target |
| Single and multiple phases, small inverter and slow connector | Enforce saved total inverter percentage and all electrical caps |
| Direct EVSE versus smart-socket selection | Only the supported direct path can enter the new timing |
| Load surge and sustained grid import | Apply explicit economic-import contract; hard safety reduction is immediate |
| Midnight and ready deadline | Preserve cycle identity and clean successor handoff without a stale stop |
| Next free boundary | Immediate free-window takeover with saved priority |
| Unplug and later reconnect | Preserve policy intent; re-admit only with fresh authority |
| Sleep, unavailable values and restored states | No fabricated charging evidence or unobserved delivery |
| Restart while starting, charging or stopping | Restore duties and energy once; no renewed allowance |
| Both daylight-saving transitions | Correct elapsed duration and chronological interval |
| Equal, adjacent and overlapping configured windows | Explicit valid interval or fail closed, never accidental full-day authority |
| Overnight price entry, expiry and source loss | No deadlock, simultaneous spend or expired authority |
| EV-before-export off during price handoff | Physical no-overlap proof still required |
| Future Trip, active Trip and manual Full | Existing ownership, original deadlines and override semantics retained |
| Mode, reserve, current or mapping changes | Immediate rebinding; stale session cannot retain permission |
| Safety Lock or master disabled | No positive command or delayed safety withdrawal |

`tests/test_ev_post_export_reuse_contracts.py` characterizes the unchanged
building blocks. `tests/test_ev_when_connected_runtime.py` tests the new mode's
timing, energy, boundaries, journal and restart behavior;
`tests/test_ev_when_connected_price_handoff.py` runs both real writers, native
provider frames and price transitions. Setup/native controls have independent
contract and lifecycle tests. Release qualification and named-site acceptance
are separate from these automated checks.

## Implementation boundary

The behavioral change is timing/admission, shared budget/current reuse and
explicit handoff arbitration. One timing choice and one required restart margin
have native controls, translations and configuration contracts. Existing store
meanings remain; the optional owner flag adds cleanup provenance without a new
store version and is ignored by earlier code. Upgrade/rollback rehearsal remains
required.

Do not include predicted trips, multiple schedules, tariff optimisation,
Extended Away, house-learning changes or simultaneous EV/export. Installation,
activation and a live-dashboard import each require the separately approved
deployment/preservation steps; HACS never rewrites a deployed dashboard.
