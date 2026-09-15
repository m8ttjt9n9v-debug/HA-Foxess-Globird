# Tariff meters and source integrations

The setup wizard accepts telemetry that is safe to obtain from the other Home
Assistant integrations, but it does not silently guess electrical limits.

## What can be mapped

From **FoxESS Modbus**, map the inverter's battery SoC, battery
potential/remaining-capacity sensor, signed grid power, and (when available)
house-load or PV power. The observer calculates current battery energy as:

`potential capacity × SoC ÷ 100`

From **Tessie**, the optional vehicle SoC sensor may be mapped for observation.
EV phase count, voltage, and current bounds are explicit commissioned values;
they are never inferred from a transient charger reading. HEO does not
currently write Tessie entities.

## Daily import on a new site

A new site does not need to have created a cumulative daily-import helper in
advance. If the user maps a trustworthy native cumulative import sensor, that
sensor is used. If the field is left blank, the integration creates a persisted
local-calendar-day accumulator from the signed grid-power sensor and exposes it
as **Grid Import Today**. It starts at zero when first commissioned, so it must
be allowed to run for the current day before it can represent a complete bill
day; it does not reconstruct historical imports.

The free allowance is a separate accumulator. **Free Window Import** counts
only imports observed between the configured off-peak start and end, so a
large shoulder or peak import cannot silently consume the 50 kWh allowance.

The default rate profile is configurable during setup:

| Period | Default local window | Default rate |
| --- | --- | ---: |
| Peak | 16:00–23:00 | $0.594/kWh |
| Off-peak within allowance | 12:01–14:59 | $0.00/kWh |
| Off-peak above allowance | 12:01–14:59 | $0.308/kWh |
| Shoulder | all remaining time | $0.528/kWh |
| Daily supply charge | every day | $2.035/day |

The integration exposes separate estimated financial values:

- import energy cost, excluding the daily supply charge;
- daily supply charge;
- gross cost, which is the preceding two values added together;
- grid export today and estimated export revenue; and
- the ZEROHERO daily credit and its qualification status; and
- net cost, which is gross cost minus export revenue and any earned credit.

The daily export meter integrates canonical positive export from local
midnight. A separate persisted meter counts export inside the configurable
Peak Solar/GenerationFeedin window. Its complement is Off-peak
Solar/GenerationFeedin; no additional time pair is required. Each period has
its own base rate. Within the independently configured Super Export window,
eligible export also receives the additional top-up for no more than the daily
top-up allowance. For example, if all 20 kWh is exported inside a 2 c/kWh base
window and the first 15 kWh also receives an 8 c/kWh top-up, earnings are
`20 × $0.02 + 15 × $0.08 = $1.60`.

The automatic controller has a separate daily export cap. A 20 kWh automatic
cap and 15 kWh boosted allowance lets HEO plan a fixed-power session for no
more than 20 kWh while applying the boost only to the eligible first 15 kWh.
The plan remains latched until its calculated finish so transient telemetry
cannot cause unsafe command flapping. Existing installations initially
migrate their old shared allowance into the new controller cap, so an upgrade
does not silently increase exported energy. The meter is persisted across
reloads and restarts, but starts at zero when this feature is first installed
and cannot reconstruct export from earlier that day. These values are estimates
until a complete local day has been observed; they are not copies of the
retailer's final bill.

After upgrading, verify both Peak and Off-peak base feed-in rates, the Peak
feed-in start/end times, and that Super Export contains only the additional
top-up, not the combined rate.

The ZEROHERO daily credit defaults to $1.00 and is configurable. HEO applies it
once per day only after the complete configured bonus window has been observed,
the expected number of clock-hour buckets is present, and every bucket is at or
below the configured import-energy threshold. Before then its status is
`pending_window_completion`; missing hour evidence and an exceeded threshold
remain explicit and receive no estimated credit.

## ZEROHERO versus the engineering guard

The supplied GloBird wording says that a ZEROHERO day is assessed in the local
6–9 pm window and gives a threshold of **0.03 kWh/hour**. In the setup flow,
the threshold defaults to 0.03 kWh/hour. The observer keeps independent local
hour buckets for 18:00–19:00, 19:00–20:00, and 20:00–21:00 and checks each
bucket against that threshold. It does **not** add the three buckets together:
for example, 0.01 + 0.02 + 0.04 kWh is a failure because the third hourly
bucket exceeds 0.03, even though the three-hour total is below 0.09 kWh.
The sustained-time field is explicitly only a local telemetry debounce; it is
not a second retailer condition. The observer therefore reports evidence and a
fail-closed guard, while retaining a clear distinction between live telemetry
and the provider's final billing calculation. The **ZEROHERO Import This
Window** sensor shows the accumulated import observed so far and exposes the
individual hourly buckets in its attributes, so each 18:00–19:00,
19:00–20:00, and 20:00–21:00 result can be checked directly.

Super Export is a separate rule: only the first **15 kWh exported during the
6–9 pm window per day** receives the boosted top-up. It requires its own
windowed export counter and is not interchangeable with the ZEROHERO import
guard.
