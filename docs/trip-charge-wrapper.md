# One-off trip charging to a selected SoC

This optional native Home Assistant helper package schedules HEO's existing
Charge to Full switch. It is a reusable wrapper, not another EV controller,
and does not require an HEO upgrade. It ends its own Full request at your
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
and reports Interrupted rather than allowing an unchecked run toward 100%.
An unavailable Full entity during startup retains the ownership obligation
until its state is readable; it is not mistaken for a deliberate manual OFF.
A confirmed Full OFF event consumes ownership even if a human immediately
turns it back ON, so a new manual Full request is not stopped at the old target.
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

### Updating the earlier 100%-only wrapper

Update only with no armed or owned trip and no active Full override. Back up
the existing helpers, templates, automation and dashboard first. Add the
internal started-target number and Full-generation text helper, expand the
existing target/status dropdown
options, and update all three templates, the automation and the card from
the same generated package. Keep the user's existing helper values and entity
IDs. Do not install another dispatcher, reset the departure, or adopt an active
manual Full request. Mixed v1/v2 plan data cannot start a new override.

Future HACS bundling should use HEO's own runtime settings directly and retain
this single-writer handoff; it does not require rewriting Full for selected
trip targets. Weekly repetition remains future work.

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
live delivery or an exact finishing time. Percentage support remains local
until the updated wrapper has been separately approved and deployed.
