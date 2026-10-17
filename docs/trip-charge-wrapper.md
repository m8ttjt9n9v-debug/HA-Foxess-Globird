# One-off trip charging to a selected SoC

## Built into HACS

HACS installs Trip Charge together with HEO. You do not need a separate helper
package on a new installation. Import the **Trip Charge** view from
`examples/dashboard.yaml` or add these entities to your existing dashboard:

| Control or information | Entity |
| --- | --- |
| Departure date and time | `datetime.home_energy_trip_ready_by` |
| Desired car charge, 1–100% | `select.home_energy_trip_target_soc` |
| Schedule this trip | `switch.home_energy_trip_charge_scheduled` |
| Trip status | `sensor.home_energy_trip_charge_status` |
| Calculated start | `sensor.home_energy_trip_charge_planned_start` |
| Estimated charging hours | `sensor.home_energy_trip_charge_duration` |
| Optional extra minutes | `number.home_energy_trip_extra_minutes` |

Set the departure and target, then enable **Schedule this trip**. Scheduling
starts **off**. HEO's commissioned home/cable mappings, usable capacity,
maximum power, efficiency and Full timeout are used directly. Automatic EV
control must remain on and Safety Lock off; the first version supports the
direct-EVSE path. No new Tesla or inverter writer is added.

The scheduler requests the existing paid **Charge to Full** policy at the
calculated time, then withdraws only its own request when the selected reported
SoC is reached. That policy can use paid grid power and bypass the normal
house-battery EV reserve; electrical and hardware protections still apply.
Normal policies resume afterwards, so this is **not a permanent charge ceiling**.
Taper, faults and reporting delays mean an exact finish time or percentage is
not guaranteed. The normal policies can charge before the trip's calculated
start; their SoC changes update the calculation.

A private persistent journal binds each trip to its own Full request. Manual
Full changes invalidate that lease; old trip cleanup cannot stop a later manual
request. Positive intent requires a successful checkpoint. Missing data blocks
a start, invalid SoC interrupts an owned request, and restart cleanup retains
its ownership obligation. An unstarted past departure expires rather than
starting unexpectedly. An already-active late trip continues only within the
original absolute Full timeout. It does not repeatedly restart a cancelled,
replaced, timed-out or invalid-data request.

Cancel to withdraw an owned request. Editing departure or target while charging
cancels that trip; deliberately enable the edited schedule again. Edits while
waiting replan. An already-at-target waiting schedule stays armed until departure
in case the SoC falls, but a completed trip is consumed. Weekly repetition is
not implemented.

### Unplugging and reconnecting

From v0.12.36, restarting Home Assistant also waits for the car's initial
information to arrive. Different integrations may load at different times;
"not received yet" does not mean "unplugged". An already-active trip keeps its
original timeout during this wait, and no new EV commands are authorised until
the required information is trustworthy. A confirmed unplug still pauses the
trip. The pause-aware legacy dispatcher must be updated to the matching version
to share this startup handling. An upgrade does not automatically re-arm an
already-cancelled request.

From v0.12.35, a confirmed temporary unplug or departure from home **pauses** an
outstanding trip rather than cancelling it. HEO withdraws only that trip's
charging override and keeps the original target and departure. It sends no
charging commands while the car is away or disconnected. A qualified return
before departure lets HEO reassess the current SoC and remaining energy, then
resume through the existing charging policy when needed. A trip that had
already started does not wait for a newly calculated later start time.

The original timeout keeps running during the pause: reconnecting does not
grant another full timeout. Cancel still cancels, and a manual Full replacement,
invalid data without a confirmed disconnect, timeout or completed trip is not
automatically revived. A missing SoC during a confirmed disconnect can pause
the request, but cannot authorise a restart until valid data returns. Returning
after departure cannot silently start a new paid charge. If the remaining time
is insufficient, the original deadline is not moved or presented as achievable.
Normal free-window charging remains independent of the trip request and may
continue above the selected trip target after that trip has completed.

If the scheduled override **has not started**, the armed schedule can wait for
the car and re-evaluate on reconnect before departure. A passed departure
expires instead of starting a late unexpected paid charge. A very brief physical
unplug that never reaches Home Assistant telemetry is not a detected interruption.

Tariff-aware rates and ZEROHERO credit trade-offs remain deferred design work
in the [roadmap](../ROADMAP.md); this correction does not change charging rates.

For DD/MM/YYYY, choose **Profile → General → Date format → day/month/year**.
The stored instant follows Home Assistant's timezone rather than a fixed UTC
offset, including daylight-saving transitions.

### Estimated trip impact

The reusable Trip Charge view includes a read-only **Estimated trip impact**
card. Its cost is **extra paid electricity before the next free-power window**,
not the whole trip price. It never changes the start, target, charge rate,
reserve, control switches or charging owner.

It shows charging energy including losses, the part scheduled before free
power, the house battery available after expected house use, and the remaining
paid-energy shortfall. It uses the selected scheduler's actual plan, the
shared EV capacity/efficiency and HEO's existing remaining house-energy budget.
The Full override can spend normal additional reserves, so the estimate starts
with battery energy above the configured minimum floor, converts it to AC
energy using discharge efficiency, and deducts expected house use exactly once.
Using the house battery for the car can move later house consumption onto the
grid; that displaced demand is included rather than calling battery energy
unconditionally free. Timing margin moves the start but is not extra energy.

Cost uses the site's saved paid import tariffs. If multiple rates may apply
before free power, it displays a range instead of pretending to know the exact
time that a house-versus-car shortfall will occur. Daily supply charges, lost
export revenue and ZEROHERO credits are excluded. Future solar and export,
inverter headroom, BMS restrictions, taper and unusual house demand can change
the result. This is a planning estimate, not a bill quote or electrical guarantee.

Energy scheduled during and after the free window is listed separately. The
current battery balance is not carried unchanged through that recharge window
to invent a later cost. When the trip starts after the next free window, or
free power is already underway, the card explicitly says that this pre-free
cost estimate does not apply. Missing inputs are unavailable, not $0.

HACS supplies the read-only `energy_impact` attribute on the existing Trip
status entity; no new setting, storage journal or actuator is added. For an
existing standard helper wrapper, it validates that helper plan against its
current target/departure and shared EV inputs, and labels the source **legacy**.
It does not adopt that wrapper's Full ownership, enable native scheduling,
or hide the intentional native `legacy_conflict`. Custom/renamed or stale
helper plans are not guessed. Existing dashboards require an explicit card
import; an older HEO version without the attribute shows an unavailable message.
Failed ledger refreshes or invalid/stale canonical grid, battery or house-power
evidence withhold the cost. Stable SoC retains the source controller's value
semantics rather than receiving a new fast-poll clock. The calculation timestamp
is not a claim that every unchanged source value was newly measured. Expired,
unowned requests cannot be presented as a new future charge.
Paused trips withhold this estimate until they resume, rather than presenting
the old start time as a new charging prediction.

| Existing input | Estimate use |
| --- | --- |
| Native Trip plan, or validated published helper plan | Current target, capacity, efficiency and start; neither planner is replaced |
| Canonical ledger above the configured battery floor | DC energy converted once using existing discharge efficiency |
| Remaining learned/fallback house budget | Existing non-free-cycle house protection, deducted once |
| Configured free/peak windows and import tariffs | Before/during/after split and paid pre-free cost bounds |

Automated tests cover energy versus timing margin, house protection, conversion
losses, tariff boundaries, midnight/DST, free-window crossover, invalid inputs,
helper-plan mismatch, read-only native integration and card rendering. They
do not prove a future physical charging result. Release and controlled site
installation remain separate from local implementation.

### Existing helper installations

HACS does not delete, migrate or reset the older helpers. A detected enabled or
unreadable legacy dispatcher, armed helper or ownership helper blocks built-in
arming. Retire the legacy dispatcher explicitly only when its schedule and
ownership are off and Full is inactive. Keep a backup; the old helper values
may remain for reference. Do not run both schedulers together.

The original generated package and its tests remain for compatibility. The
following section documents that **legacy installation**, not the HACS-owned
scheduler above.

## Legacy native-HA helper package

This optional native Home Assistant helper package schedules HEO's existing
Charge to Full switch. It is a reusable wrapper, not another EV controller.
The current pause/startup-aware dispatcher requires HEO v0.12.36 or later so it
can share startup evidence and verify why the previous charging override stopped.
It ends its own Full request at your
chosen reported SoC without changing HEO's Full implementation. HACS does not
install it automatically.

## Using the panel

1. Set the departure date and time.
2. Choose the desired car SoC, from **1% to 100%** in whole-percent steps.
   The default remains 100%; a target below the current SoC does not discharge
   the car or start a charge.
3. Enable **Schedule this trip**. The calculated start updates as the car's
   charge changes. Leave HEO's normal EV control on.
4. At the calculated time, the wrapper enables HEO's paid Charge to Full
   override. That existing policy may use grid power and bypass the normal
   house-battery EV reserve; its electrical and hardware protections remain.
5. On a valid reported SoC reaching the selected target, the wrapper ends only
   its own Full override and consumes the one-off schedule.

**This is a trip-charge target, not a permanent car charge ceiling.** Normal
HEO policies resume afterward, including a configured keepalive. Normal solar,
backfill or free-window charging may subsequently raise the SoC beyond the trip
target. No direct Tesla charge-limit, current or stop command is added here.
Reporting and HEO reconciliation delays can produce some overshoot; an exact
physical percentage cannot be guaranteed.

Cancelling from the panel withdraws only an override started by this schedule.
The normal HEO policy, including a configured keepalive, resumes. A manually
started Full override is not adopted or stopped by a waiting schedule.
For a deliberate manual handoff during a trip, cancel the trip first, wait
until its ownership/active status clears, then enable Full manually. Do not
configure a second automation to manage the same Full switch. The wrapper
guards observed ON cycles and user contexts, but native helper/service steps
are not an atomic transaction with every possible outside caller.
Completion consumes the one-off request. Changing the departure or target
after charging has started cancels that request; enable the updated schedule
deliberately. Editing either while still waiting simply replans the start.
An interrupted, manually stopped or timed-out override is not repeatedly
restarted. Correct the problem and re-arm if appropriate.

With the updated v0.12.35 helper dispatcher, an explicitly identified temporary
disconnect instead reports **Paused — car disconnected** and retains the dated
request. Its restorable resume checkpoint binds the original timeout and Full
generation. Only a matching disconnected stop can resume; an arbitrary Full OFF
is not treated as permission to retry. Existing installations need this updated
dispatcher and its additional checkpoint helper, not just the new HACS runtime.
Upgrade an idle installation with a fresh backup. An approved active-charge
upgrade must additionally prove the existing wrapper owns that exact Full
generation and recover the original start and timeout; never seed a fresh
timeout or adopt a manual Full request. Preserve the target, departure and
existing helper IDs. A new HACS installation uses the native scheduler above
and does not need this compatibility helper.

If the car is already at or above the target before departure, the schedule
waits without enabling Full. A later SoC drop can still require charging before
that departure; after a completed trip, it never starts again on its own.

### Australian date display

The native date picker follows the viewing user's Home Assistant profile.
Choose **Profile → General → Date format → day/month/year** for DD/MM/YYYY.
This changes display, not the stored departure or the system timezone.

## What the calculation means

The estimate uses the selected target, HEO's usable EV capacity, current EV SoC
and maximum
configured charging power, with the same energy-deficit/efficiency arithmetic
as the retained latest-start planner. It does not treat a current 1 A keepalive
as the vehicle's maximum, or guess a battery size from a car model name.
The energy deficit is `max(target − current SoC, 0) × usable capacity / 100`;
the existing charging-efficiency and maximum-power calculation is unchanged.

It aims to finish near departure, **not at a guaranteed exact minute**. Battery
taper, temperature, service-headroom reductions, cloud delay and charger faults
can change the real duration. The extra-minutes setting is an optional timing
allowance; zero adds no intentional early-finishing buffer.

The normal charging policies remain active before the scheduled start. Their
SoC changes feed back into the calculation. This is not a promise that all
normal charging will be postponed until the trip start time.

## Installation and commissioning

Use [the native package](../examples/trip-charge-package.yaml) and
[the dashboard card](../examples/trip-charge-card.yaml). They are generated
from `scripts/trip_charge_wrapper.py`; check them with
`python -m scripts.trip_charge_wrapper --check`.

The same definitions can be installed as GUI helpers, template-helper config
entries and a GUI automation through Home Assistant's native APIs, without a
full Home Assistant restart. Do not install both representations on one site.

Commission the following before enabling the schedule:

- Explicit home-location and connected-cable mappings. Replace the placeholder
  tracker and cable IDs; do not infer presence from charging power.
- HEO's matching **EV charging efficiency** and **Charge to Full timeout**.
  The external helper copies must be kept aligned if those HEO options change.
  Both default to uncommissioned zero in this package, blocking activation.
- Correct HEO SoC, usable-capacity and configured-maximum-power entities. Update
  references if registered entities have been renamed. Power is kW and capacity
  is kWh. Missing/invalid values do not authorize a guessed start.
- Automatic EV control on, Safety Lock off, and the normal HEO gate ready.

No helper changes these safety switches, disables normal policies, controls a
smart socket, or sends Tessie/inverter commands directly. This first wrapper
has been scoped to the commissioned direct-EVSE path; do not assume its displayed
maximum-power entity accounts for a separately lower smart-socket rating.

## Recovery and limits

The departure, selected target, arm state and captured departure/target tickets
use HA's restorable helpers. An internal text helper binds the observed Full
ON cycle to that trip instead of treating any later ON as its own. The target
is captured before enabling Full;
a later edit cannot silently extend an owned charge.
The timestamp trigger is supplemented by startup and minute checks: a restart
inside the due period can still start, provided the deadline has not passed.
Queued or obsolete time events must match the latest plan and inputs again
before activating the Full switch. A passed, unstarted deadline expires instead
of starting an unexpected later charge.

SoC and target changes trigger immediate wrapper checks, in addition to the
minute fallback. A missing or invalid SoC during an owned charge withdraws Full
and reports Interrupted rather than allowing an unchecked run toward 100%,
unless a verified disconnect has already safely paused the dated request.
An unavailable Full entity during startup retains the ownership obligation
until its state is readable; it is not mistaken for a deliberate manual OFF.
A confirmed manual or otherwise unqualified Full OFF event consumes ownership
even if a human immediately turns it back ON, so a new manual Full request is
not stopped at the old target. The only resumable OFF is generation-matched
disconnect provenance from HEO; its dated request remains armed while paused.
After startup or unavailability, rebinding a non-user Full ON assumes it is the
restored HEO request. This is why competing Full automations are unsupported;
a non-user ON alone cannot prove which automation requested it. If native Full
ends before the read-model SoC reaches the target, the wrapper conservatively
reports Interrupted rather than guessing successful completion, and does not
restart it.

Once started, HEO remains responsible for feedback, current control, physical
charging and its timeout. If the target is late, the panel alerts while the
original override continues toward the captured target within those existing
bounds. The wrapper's
"Override active" status means the intent is active, not proof of maximum
physical power; inspect HEO's actual-current and reconciliation sensors.

Before downgrading to a version or dispatcher without pause support, cancel
any outstanding trip and verify its owned override has ended. Older code does
not understand a paused trip; do not downgrade an active or paused request.

### Updating the earlier 100%-only wrapper

Update only with no armed or owned trip and no active Full override. Back up
the existing helpers, templates, automation and dashboard first. Add the
internal started-target number and Full-generation text helper, expand the
existing target/status dropdown
options, and update all three templates, the automation and the card from
the same generated package. Keep the user's existing helper values and entity
IDs. Do not install another dispatcher, reset the departure, or adopt an active
manual Full request. Mixed v1/v2 plan data cannot start a new override.

The built-in HACS implementation above uses HEO runtime settings directly.
This older package is retained for existing installations; weekly repetition
remains future work.

## Provenance and validation

| Decision | Preserved source or separate extension |
| --- | --- |
| Energy deficit, efficiency and latest start | Existing HEO capacity/power projections and retained pre-free arithmetic; target is now the selected percentage |
| Paid charging, electrical limits, location/cable gates, reserve exception and keepalive | Existing HEO Full policy and sole EV actuator; unchanged |
| Start/end at a selected one-off departure/SoC | Separate native HA wrapper; never writes Tesla or inverter commands |
| Cancellation and restart | Restorable departure plus captured target; pending data cannot authorize a guessed start |

Native Home Assistant helper, template and automation tests cover 1/80/90/100%
targets, zero deficit, prompt completion, invalid/unknown readings, cancellation
and awaited-start races, actual helper restoration and HA startup, manual
Full OFF/ON replacement and ordinary Full completion. These tests do not prove
live delivery or an exact finishing time. Built-in scheduler tests additionally
cover its typed journal and generation-bound manual/Trip handoff.

The v0.12.35 regressions also exercise the native Home Assistant services,
automation reload and integration reload, not just the planning calculation:

| Sequence | Required result |
| --- | --- |
| Restart with vehicle sensors arriving in different orders | Keep restored intent and its original timeout; issue no new EV commands before trusted feedback |
| Active trip → unplug/away → return before departure | Retain the dated request; resume only with valid home, cable, SoC and control evidence |
| Unplug and SoC disappears together | Pause safely; missing data cannot restart charging |
| Reconnect during free power → free power ends | Keep the outstanding trip; normal free charging is not cancelled at its selected target |
| Repeated pauses or restart while paused | Keep the original absolute timeout; never grant another full budget |
| Cancel, replace Full, complete, or exceed timeout | Do not revive the consumed request |
| Another automation reasserts Full while already on | Do not adopt or stop its newer Full generation |
| Reconfigure opened → dashboard setting changes → Apply | Preserve newer untouched settings; reject conflicting edits without saving |
| Electrical mapping or schedule changes during confirmation | Reject stale confirmation rather than applying old evidence |

These are software regression results. A pilot upgrade still needs fresh
backups, exact release-file verification, preserved settings and read-only
post-restart checks. Do not manufacture a live unplug or device command merely
to label a release tested.
