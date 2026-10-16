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

The daily automatic-export cap is shared. Measured export earlier in the day,
including solar export and manual export, reduces its remaining budget. A new
price block, reload, or switch toggle does not grant another daily allowance.
This controller limit is separate from any retailer reward allowance.

## When export ends

An owned price session has a fixed deadline based on the current five-minute
price block and the safe energy available. That deadline may be shortened but
never extended. HEO begins restoration slightly before it expires. It also
restores Self Use and clears both forced targets when the price falls, the
feed expires or fails, safe Sellable runs out, or the price-export request is
turned off.

A price falling to exactly the threshold still qualifies. Falling below it
withdraws price permission; there is no extra price deadband or rounded-price
comparison. The same inclusive rule applies after restart and report correction.

Consecutive high-price blocks do not silently renew the old session. HEO first
confirms Self Use and cleared targets, then rechecks current evidence before
starting another session. This deliberately leaves a short gap rather than
allowing stale price permission to keep exporting.

An ordinary ZEROHERO session keeps its existing fixed-power latch and finish
rules. Price changes do not stop an already-owned ZEROHERO session, and a
price-owned session cannot inherit that latch to continue after its permission
expires.

## Data and failure handling

HEO reads AEMO's public [DispatchIS reports](https://nemweb.com.au/Reports/Current/DispatchIS_Reports/).
It accepts only the exact current interval for the selected region, with a
firm price, no intervention, and no administered-pricing or market-suspension
flag. The public price is converted from dollars per MWh to dollars per kWh by
dividing by 1,000. Market timestamps use fixed AEST and mark the interval end;
HEO converts them to aware timestamps so daylight saving does not shift the
rule. Cached summary pages and forecasts cannot grant export permission.

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
