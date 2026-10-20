# Automatic export during high wholesale prices

HEO can use a high wholesale electricity price as another reason to export
energy. It uses the existing **Sellable Energy** calculation and battery
controller: it does not sell the energy already protected for the house, the
EV, or the battery reserve. Price monitoring and automatic price-triggered
export are both off by default.

This is a price rule, not confirmation of a retailer critical event. A price
at or above your threshold does not prove that your retailer will pay a particular
amount. Check your plan and participation conditions before enabling it.

## Choose the price rule

In **Reconfigure → AEMO prices and export**, enable **AEMO price monitoring**,
select your NEM region, and set the export threshold in Australian dollars per
kWh. NSW, including the Illawarra, uses `NSW1`. The starting threshold is
`$3.00/kWh`; this is a configurable operating choice, not an official GloBird
event definition. A price of exactly $3.00 qualifies when the threshold is
$3.00; anything below it does not. This comparison uses the source price,
not a rounded dashboard display.

First leave **Automatic price-triggered export** off and observe the price,
source status, and expiry. Enable it only after commissioning exclusive Local
Modbus control. Disable competing VPP, cloud-scheduler, and other inverter
writers; HEO cannot verify their absence from a price reading.

The reusable dashboard example includes these controls and the current price
evidence. HACS installs the entities, not an updated dashboard. Monitoring can
remain on without granting any hardware control. Its optional import threshold
is observation only; there is no price-triggered buying in this implementation.

### Optional Amber source (v0.12.46)

If Home Assistant already has the Amber Electric integration, HEO can use its
confirmed five-minute wholesale price first and keep the existing direct AEMO
feed as a fallback. This reuses the installed Amber integration: HEO does not
ask for its API key, store another copy, or start another Amber polling loop.

Map **Amber price sensor (optional)** (`amber_price_entity`) and confirm the
**Amber account's NEM region** (`amber_price_region`). The region must
match HEO's selected NEM region. HEO does not guess the region from an entity's
name. Leave both fields empty to keep the existing AEMO-only path. Adding a
mapping does not enable monitoring or automatic selling.

The Amber sensor's main value is its feed-in or import tariff, not necessarily
the wholesale price. HEO reads its separate `spot_per_kwh` attribute. In the
supported native integration this attribute is already dollars per kWh and
includes GST; HEO removes GST once, using decimal arithmetic, to compare it with
the same wholesale threshold used for AEMO. Do not divide that native attribute
by 100 as though it were the raw Amber API's cents value. A confirmed five-minute
reading is usable; a 30-minute, forecast, estimated, expired or otherwise invalid
reading is not.

Installing this release does not select an Amber source or enable selling.
Configure the two source fields explicitly, then verify the source evidence.
Publication alone is not a claim that an installed site uses Amber for selling.

## What HEO does

When a valid current price reaches or exceeds the threshold, HEO checks the same energy
protections used for ordinary export. It also checks fresh battery, grid,
house-load and SoC evidence, the remaining daily automatic-export budget, and
the EV-before-export policy. Missing or uncertain evidence prevents a start.

If enough safe energy remains, HEO requests the smaller of the commissioned
inverter discharge maximum and its native actuator maximum. The inverter still
enforces its installed electrical limits. A small execution margin and minimum
start horizon prevent a maximum-power start for a tiny remaining energy amount.
The first release requires force-power number entities measured in kW.

Price export does not take over the free-power window or an explicit paid EV
Charge to Full request. Manual Export, Stop, and the diagnostic handoff retain
their existing priority. Local ownership, automatic-control commissioning,
the master control switch, and Safety Lock still apply. Price export has its
own request switch; turning ordinary ZEROHERO export off does not turn this
separate request off.

The daily automatic-export cap is shared and counts qualifying paid net export,
not zero-rate solar overflow. Positive configured base tariffs, eligible bonus
energy and actually owned bounded price-export opportunities count once even
when they overlap. Solar or manual export during a paid tariff counts too; the
source of the exported energy is not the distinction. A new price block,
reload or switch toggle does not grant another allowance. The first upgrade
conservatively retains that day's old total, because earlier price events cannot
be reconstructed; clean paid-only counting begins next local midnight. This
controller estimate is separate from retailer reward eligibility or payment.

## When export ends

HEO keeps the last confirmed price usable for up to **150 seconds after its
five-minute interval ends**. This bridges the delay before the next AEMO report
arrives. It is not a claim that the old price is still the current price: the
current-price sensor can show unavailable while this brief permission remains.
Failed downloads, estimated prices and repeated old reports do not restart the
clock. If no new confirmed price arrives, HEO starts restoring Self Use at the
deadline and clears both forced targets. Communication and Home Assistant must
be working for those commands to reach the inverter.

A price falling to exactly the threshold still qualifies. Falling below it
withdraws price permission; there is no extra price deadband or rounded-price
comparison. The same inclusive rule applies after restart and report correction.

Consecutive confirmed high-price blocks renew a still-live export session
without stopping and restarting. Every renewal still checks current Sellable,
house/EV protection, the shared daily export budget and electrical evidence.
A shorter safe-energy deadline can still stop export before the price deadline.
A repeat of the same block cannot extend that shorter deadline. A fresh price
below the threshold or an affirmative market restriction stops price permission
immediately; HEO does not wait out the grace period. An expired or stopping
session must finish cleanup before another session can start.

An ordinary ZEROHERO session keeps its existing fixed-power latch and finish
rules. Price changes do not stop an already-owned ZEROHERO session, and a
price-owned session cannot inherit that latch to continue after its permission
expires.

## Data and failure handling

The default source is AEMO's public [DispatchIS reports](https://nemweb.com.au/Reports/Current/DispatchIS_Reports/).
The optional Amber source above takes priority only when its native sensor,
confirmed status, five-minute interval, region binding and freshness are valid.
A valid low Amber price takes priority over a high fallback price too: this is
not a rule that chooses whichever source would allow selling.

For the direct AEMO source, HEO accepts only the exact current interval for the
selected region, with a firm price, no intervention, and no administered-pricing or market-suspension
flag. The public price is converted from dollars per MWh to dollars per kWh by
dividing by 1,000. Market timestamps use fixed AEST and mark the interval end;
HEO converts them to aware timestamps so daylight saving does not shift the
rule. Cached summary pages and forecasts cannot grant export permission.

Amber must explicitly report `estimate: false`, a current five-minute NEM block
and a finite wholesale price. HEO accepts both an exact five-minute start/end
pair and Amber's supported convention of starting one second after the block
boundary; it uses the same five-minute block in either case. Restored
placeholders and stale or future readings cannot grant permission. Amber does
not expose every AEMO market flag; missing flags remain unknown, not relabelled
`FIRM` or normal. If current AEMO evidence identifies intervention, administered
pricing or market suspension,
that evidence blocks Amber permission as well. A failed download does not clear
a known restriction for that block; a newer valid official correction is needed.

If Amber is unavailable or unqualified, a qualifying current AEMO reading can
take over without creating another export controller. A delayed or contradictory
fallback cannot resurrect permission that a newer confirmed Amber price has
withdrawn in the same interval. If HEO cannot establish which conflicting
evidence is newer, it withholds permission. Both sources cease being current at
the exact interval end. The separately bounded last-confirmed permission above
can bridge publication gaps; changing provider within the same block never
extends its expiry. Source changes and failures remain visible in price evidence.

The existing export-session journal records price ownership, its deadline,
and its original actuator mappings before a positive command. After restart,
HEO restores an old price session before admitting fresh price evidence.
Missing numeric command feedback does not permit another export start. With
valid original actuator metadata, an already-owned session may still issue
only reducing Self Use and zero-target commands. Unconfirmed cleanup is
retained and retried at progressively longer intervals up to five minutes.
Changed actuator mappings block those writes until the mismatch is resolved.
An unreadable or malformed journal cannot establish ownership; inspect the
native inverter state and use an explicit operator Stop rather than assuming
that blocked automatic control means the inverter has stopped.

Home Assistant must be running and able to reach the inverter to stop it.
Safety Lock blocks cleanup writes as well as starts. A confirmed mode setting
alone is not proof of physical export, delivery of a stop, or retailer payment.
The existing conformance supervisor remains the source of sustained control
issue notifications. This feature adds no critical-event reward estimate to
the daily cost forecast or scorecard.

## Safe disabling and downgrade

To stop only this policy, turn **Automatic price-triggered export** off while
HEO retains write authority. Verify Self Use, both forced targets at zero, and
an idle export session. For an immediate operator hold, use the existing
**Stop/Self Use** service or Fleet Stop control; automatic battery control
remains held until explicit Resume.

Before installing an older HEO version, disable this policy and confirm its
session has fully stopped. Older releases do not understand price ownership
and must not read an active price session as an ordinary latched export.
Do not downgrade an active or unconfirmed session. Retain the normal backup
and controlled pilot acceptance procedure.
