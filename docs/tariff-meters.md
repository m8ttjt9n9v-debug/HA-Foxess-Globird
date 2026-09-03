# Tariff meters and source integrations

The setup wizard accepts telemetry that is safe to obtain from the other Home
Assistant integrations, but it does not silently guess electrical limits.

## What can be mapped

From **FoxESS Modbus**, map the inverter's battery SoC, battery
potential/remaining-capacity sensor, signed grid power, and (when available)
house-load or PV power. The observer calculates current battery energy as:

`potential capacity × SoC ÷ 100`

From **Tessie**, map the vehicle SoC sensor. The charger profile is selected
explicitly (single-phase 10/15/32 A or three-phase 16 A), because the profile
is a commissioned physical limit rather than a value that can safely be
inferred from a transient charger reading.

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

The integration exposes an estimated daily import cost from these counters. It
is an estimate until a complete local day has been observed; it is not a copy
of the retailer's bill or a claim about export credit.

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
