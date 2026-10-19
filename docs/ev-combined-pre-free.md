# Combined solar and battery EV charging before free power

Before the next free-power window, an eligible car can use both measured spare
solar and home-battery energy that HEO does not need to protect for the house.
This avoids leaving usable energy in the home battery simply because solar-only
charging is keeping its charge level steady.

This is a correction around the existing pre-free planner, not a second EV
controller. It requires **both Morning Solar EV Charging and pre-free backfill
to be enabled**. Installing an update does not turn either policy on.

## When it starts

The existing daily Ready-by opportunity keeps its priority. Before its deadline,
its own planner and energy accounting remain authoritative. After its deadline,
the pre-free planner becomes eligible using the current protected budget, not a
copy of energy offered earlier. Invalid Ready-by timing or evidence still blocks
the handoff; it cannot grant a less-protected fallback.

During the eligible pre-free period, a fresh positive measured solar surplus and
a positive protected battery budget can start the combined opportunity before
the old latest-start time. The combined current must be representable by the
charger. Solar alone need not reach the charger's minimum: battery support may
make the combined current usable.

Without this solar opportunity, the existing latest-start plan is retained. If
either policy is disabled, its existing independent behaviour is retained.
Once a combined session has started, passing clouds can reduce solar to zero
while the remaining safe battery budget continues to be available for charging.
Zero measured solar is different from missing or stale electrical evidence.
Positive measured surplus is the admission test, not proof of daylight; there
is no additional universal wattage threshold or fixed sunrise time.

## One calculation, one current request

HEO works in wall-side AC energy and power:

```
EV power = protected keepalive power
         + current protected discretionary battery energy / spending horizon
         + current measured net solar surplus
```

From v0.12.45, HEO offers that spare energy sooner instead of assuming the car
will stay plugged in until free power. The spending horizon normally ends at
the next ten-minute current adjustment. Between updates it remains anchored to
the accepted target's clock, so normal energy consumption does not continually
restart a rolling ten-minute calculation. The free-power boundary shortens the
horizon, but it is never shorter than the existing thirty-second control
recheck. HEO does not knowingly spend a small budget faster than it can recheck.

The time to free power is physical elapsed time between UTC instants, including
daylight-saving changes. The boundary is the site's exact configured free-power
start, not a rounded hour or a guessed retailer schedule. No future sunshine is
assumed.

The battery contribution uses the existing protected discretionary/export plan,
capped by the car's remaining wall-energy room. That plan already accounts for
the battery floor, configured reserve, discharge efficiency, remaining house
demand, protected EV keepalive, fixed daily EV allocation and applicable export
cap. These are not subtracted a second time. Keepalive is added separately
because it was protected separately in that ledger.

Measured net solar uses the existing coherent equation:

```
net solar available to the EV = max(EV power + grid export + signed battery charge, 0)
```

Grid import is negative export; battery discharge is negative battery charge.
This removes the existing battery/grid contribution rather than allowing a high
EV request to justify itself as solar. The raw power is combined before rounding;
HEO does not round solar and battery independently and lose their smaller parts.

HEO converts the total power with the configured EV voltage and phase count,
rounds down once to a supported current step, and caps the **total EV current**
at the existing outside-window inverter percentage, connector rating and current
service headroom. The percentage remains a limit on total EV power, not a newly
redefined limit on the battery component alone. It does not increase because
solar is available.

For example, with 0.9 kWh of safe battery energy and ten minutes until the next
adjustment, the battery contribution may be up to 5.4 kW before current limits.
A 15 A single-phase charger would still receive no more than its roughly
3.45 kW physical maximum at 230 V. A three-phase charger still respects the
saved percentage of inverter output across all phases. This offers the same
energy earlier; it does not reserve or manufacture another 0.9 kWh at each tick.
Once the spare budget is exhausted, an eligible solar-only successor keeps the
same total inverter-percentage ceiling while both policies remain enabled.

## Protection and smooth adjustments

Normal combined-current changes use a restart-safe ten-minute adjustment cadence:
at each permitted update, HEO adopts the latest safe combined target. Unlike
standalone measured-solar capture, it does not require that candidate to remain
unchanged for ten minutes. The battery-energy/time contribution moves as the
deadline approaches; resetting a stability timer on every changed current could
leave usable energy stranded. Standalone solar retains its existing ten-minute
stable-target hysteresis. Neither rule permits an unsafe old target. A reduced
protected battery budget/component, verified
grid import or reduced service headroom can curtail immediately. Lost energy
authority, invalid/stale electrical evidence, a house-battery cutoff, EV target,
disconnect, closed control gate or Safety Lock cannot be hidden by the hold.
In addition, a held TOTAL request must remain affordable from current solar and
the remaining approved battery budget through its next adjustment. A lost solar
contribution can be absorbed only while that budget supports it. If a decrease
is required, HEO recalculates it for a fresh normal interval before resetting
the clock; it must not save a target that needs another immediate decrease just
because its horizon reset. Ordinary increases still wait for the existing cadence.

The existing morning battery threshold and global outside-window EV battery
cutoff remain distinct and binding. The existing normal EV charge-limit policy,
including the direct-EVSE 90% hard cap without Charge to Full, is unchanged.
When both policies are enabled, the morning threshold also binds the joint
pre-free battery path on its no-solar latest-start branch, even if the separate
global outside-window cutoff is lower.
A nonzero configured keepalive remains the existing deliberate anti-fault
baseline; only a zero baseline authorises the normal stop path.

The existing pre-free session still owns one EV current request. Its phase and
start survive restart; its energy authority stays live. The measured-solar
journal retains the existing `morning_solar` category with optional accepted
battery-current context for safe curtailment after restart. No new storage
version, device writer, polling dependency or forecast service is introduced.

At the free-power boundary, the independent free-window policy takes over,
including its configured priority and settling behaviour. Paid Charge to Full
and Trip ownership retain their existing precedence. Late pre-free energy does
not count as delivery toward tomorrow's fixed Ready-by allocation.

## What this does not promise

The goal is to use safely spare energy before free power, not to force the home
battery to an exact charge percentage. The power cap, charger steps, remaining
time, car target, house protection and applicable export-budget cap can leave
energy unused. Sudden house demand, imperfect forecasts and device response
times also prevent a guarantee of zero transient grid import. No reserve is
weakened merely to empty the battery before the window.

## Provenance and verification

| Existing behaviour | Retained boundary or approved correction |
| --- | --- |
| Canonical pilot selected the larger of pre-free and measured-solar targets. | Combining their power is a separately identified correction, not a claim of pilot parity. |
| Earlier HACS pre-free selected its target exclusively. | Both enabled policies can now contribute to one pre-free request. |
| v0.12.43/44 spread discretionary energy until free power. | v0.12.45 separately corrects pacing to use the same budget sooner while connected; the no-solar latest-start branch remains characterised and unchanged. |
| Protected export ledger and vehicle-room calculation. | Reused without a second reserve subtraction or invented energy budget. |
| Ready-by planner, session and delivery ledger. | Priority, admission, invalid-evidence holds and after-deadline handoff retained. |
| Measured-solar reconstruction and persistence. | Same signed, coherent evidence and journal; standalone solar keeps stable-target hysteresis, while combined pre-free adopts the latest safe target on the ten-minute cadence. Reduced battery authority adds an immediate downward bound. |
| EV reconciliation and free-window/Full ownership. | Same sole writer, safety gates, retry obligations and independent takeover. |

Regression coverage must include one/three-phase conversions, keepalive/zero
baseline, solar below the charger minimum, no-solar latest-start behaviour,
changing solar and house demand, capped and disappearing budgets, EV room and
limits, Ready-by priority/invalid holds, unplug/replug, restart, stale or missing
sources, service/import curtailment, exact window boundaries and DST elapsed
time. Time-sequenced energy replay must also verify that a moving deadline or
cloud/house-load changes cannot continually reset an update timer and strand
the battery budget. Repository tests do not establish live-site acceptance: publication and
controlled pilot installation remain separately verified stages.
