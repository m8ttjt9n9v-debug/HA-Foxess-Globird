# System requirements and integration map

HACS installs HEO code only. It does not install device integrations, create a
dashboard, commission electrical limits, or migrate personal entity mappings.

## Required for the retained feature set

- A supported Home Assistant installation and HACS custom-repository access.
- The FoxESS Modbus integration for local inverter telemetry and actuation.
- A compatible FoxESS inverter exposing battery SoC, signed grid power, work
  mode, force-charge power, and force-discharge power entities for any Local
  Modbus control or diagnostic use.
- Commissioned battery capacity/floor/reserve, inverter charge/discharge limits,
  site phase count, service import limit, export limit, tariff windows/rates,
  free-energy allowance, and ZEROHERO export settings.
- A trustworthy mapped protected-house load sensor. Map whole-house power when
  that is the intended complete protected demand. At the Working Single Phase
  Pilot Site the mapped source is non-heater base-house power and the heater is
  supplied through the optional separate power mapping, preventing double
  counting. If the mapped value includes EV charging, enable **Mapped
  house-load sensor includes EV charging** so the allowance projection removes
  live EV power exactly once. Leave it disabled for an already EV-exclusive
  house sensor. This correction requires valid actual EV current plus the
  commissioned EV voltage and phase count; missing evidence fails closed.
  HEO holds the existing target across a vehicle-SoC-only early recalculation
  while requested and actual current are converging, but never defers a measured
  service-limit overrun, a target-SoC crossing, or the normal three-minute
  decision boundary. This hold applies only while allowance protection is
  enabled.
- Home Assistant history/storage plus its built-in template, statistics, and
  integration-style behavior used by the source model and HEO persistence.
- Home Assistant `person` entities are optional. Auto occupancy conservatively
  assumes Home when none exist or any presence state is uncertain. Home and
  Away can also be selected explicitly on the dashboard.

The FoxESS work-mode and force-power entities must be explicitly mapped. Entity
availability alone does not prove safe hardware compatibility.

Local Modbus ownership requires a clean inverter schedule state. Delete or
disable every inverter-local Mode Scheduler entry, then clear both legacy
front-panel **Charge time** periods. Where the inverter shows P1/P2, set each
start and end to the same value (the conventional cleared value is
`00:00–00:00`) **and** set its grid-charge state to `Dis`. Do not treat matching
times while the period still displays `En` as commissioned or safely disabled.
FoxESS's [public H3 documentation](https://www.fox-ess.com/download/upfiles/EN-H3AC3-User-Manual-V1.0.4-20250107.pdf)
exposes the Charge time menu but does not define equal-time behaviour across
firmware. The FoxESS Modbus project confirms that these periods are
[stored on the inverter](https://github.com/nathanmarlor/foxess_modbus/wiki/Force-Charge-and-Discharge),
so HEO requires the explicit disabled state as well as a zero-duration period.
FoxCloud ownership is the exception: its intended cloud schedule remains the
sole inverter owner and all HEO Modbus writes stay blocked.

Before commissioning any FoxESS command, open the FoxESS Modbus integration and
ensure **Export Power Limit**, **Force Charge Power**, **Force Discharge Power**,
and **Import Power Limit** are properly set for the commissioned inverter and
site. A zero force-power setpoint can make a manual Force Charge or Force
Discharge mode selection produce no battery power; an incorrect import/export
limit can constrain the inverter independently of HEO. Confirm the live values
and native entity maxima rather than copying another site's ratings.

HEO writes the mapped Force Charge Power and Force Discharge Power entities for
its own bounded sessions. It clears the opposite force target before starting
and clears both targets after restoring Self Use, so finding those two setpoints
at zero after an HEO-controlled session can be expected. HEO does not currently
write the FoxESS Modbus Import Power Limit or Export Power Limit entities.

Automatic Local Modbus battery charging additionally requires the work-mode
entity to advertise `Self Use` and `Force Charge`, a positive commissioned
inverter charge limit, a positive live maximum on the force-charge number, a
fresh battery SoC below the configured target at session start, and non-
overlapping charge/export control windows. It uses the inverter limit as its
fixed requested power for the window and remains default-off after installation.

### Modbus TCP connection ownership

Use one Modbus TCP client for an inverter bridge unless that exact bridge and
firmware have been independently proven to support concurrent clients. During
commissioning, an EW11 bridge was observed to lock up and become unresponsive
when two Home Assistant instances polled it at the same time. HEO therefore
treats the EW11 as a single-client transport: enable FoxESS Modbus on only one
Home Assistant instance at a time. This transport constraint is separate from
HEO's write ownership gates; read-only polling from a second instance can still
break the connection.

## Required for Tessie EV automation

Tessie is optional when EV control is not commissioned. The ported EV
free-window policy requires explicitly mapped capabilities equivalent to:

- vehicle SoC and stored energy;
- cumulative lifetime energy for daily-driving learning (optional; without it,
  the conservative full-window fallback remains active);
- location/at-home state and user override;
- cable connection, charging state, and actual current;
- writable charge current and its min/max/step metadata;
- charge-limit state/control where the source policy requires it; and
- an explicit charge-start switch.

Single-phase sites may derive service current from signed grid power. A
multiphase site must additionally provide signed current in amperes for the
most-loaded service phase, positive for import. This may be a trustworthy
template/helper built from phase sensors. Aggregate power is not a substitute
because the controller must protect each phase's configured service limit.
If that mapped multiphase current is unavailable, EV actuation is blocked.

FoxESS Modbus profiles that expose an unambiguous `BMS kWh Remaining` capacity
entity are suggested automatically, and its current value prefills the setup
fallback. HEO uses the mapped live capacity at runtime. The numeric capacity is
optional when valid live capacity is available. If no live capacity is mapped,
the operator must enter a credible commissioned fallback; HEO does not assume a
default battery size.

The retained pilot direct path never issues a stop or pause. The optional daily
ready-by extension may stop only a session it started when its frozen wall-
energy target, soft SoC limit, ready deadline, or safety condition is reached.
It requires a configured daily allocation, ready time, inverter-output
percentage, inverter discharge/output rating, and current house/available-
energy ledger. It can operate with FoxCloud ownership because it writes Tessie
only; that mode cannot reserve energy against earlier cloud export.

The smart-socket path additionally
requires a mapped on/off outlet, its commissioned physical current ceiling,
and selected recovery/settling timings. It does not depend on a particular
outlet vendor.

Solar-spill control additionally
requires an explicitly mapped signed battery-power sensor, its charge-positive
sign convention, battery SoC threshold, and coherent grid/battery/Tessie
timestamps. Latest-start pre-free backfill additionally requires the Local
Modbus ZEROHERO export ledger. Both outside-window stages are independently
default-off and are rejected unless Local Modbus is selected as FoxESS owner.

The Working Single Phase Pilot Site uses Tessie entities for these roles.
Portable code maps roles and never embeds that vehicle's entity IDs. See the
[daily-driving learning provenance](ev-driving-learning-port.md).

## Optional equipment and integrations

- The Working Single Phase Pilot Site uses an eWeLink-provided switch for its
  smart-socket charging path, but HEO depends only on the explicitly mapped
  on/off switch capability, not the vendor name.
- Weather forecast data may support local diagnostics, but it is not an HEO
  house-protection input. The proven control ledger uses measured heater P80,
  not a second weather-derived energy budget.
- FoxESS cloud telemetry may be used as read-only corroboration. FoxCloud Mode
  Scheduler is an alternative inverter owner, not a fallback transport to mix
  with automatic Modbus writes.
- Tailscale, File Editor, and EMHASS may exist on a site but are not core HEO
  algorithm dependencies.

## Site commissioning values

Every installation must supply its own values. Never copy a reference site's
service rating or a target site's multi-phase rating as a default control fact.
Configure phase count, per-phase or aggregate limits as the model requires,
EV phases/current/voltage, inverter and battery limits,
tariff allowance/windows/rates, export cap/power/finish, reserve, and
efficiency.

Multi-sensor controls must use temporally coherent samples and fail closed when
freshness, units, signs, presence, connection, or ownership cannot be proven.
Configure each raw sign once and consume HEO's canonical sensors everywhere
else; the full conventions and commissioning procedure are documented in
[telemetry normalization](telemetry-normalization.md).

## Dashboard installation

Import `examples/dashboard.yaml` manually or build a site-specific dashboard
from the generated entities. HACS does not install Lovelace views. The example
preserves the seven-view operational structure while using only HEO-owned
entity IDs. Personal backgrounds, vehicle-native Tessie cards, weather, room
devices, heaters, and unrelated site cards are intentionally local overlays.
The example deliberately disables Home Assistant's entities-card header toggle:
it is not an HEO master control and is unsafe to present beside the opposite-
polarity Safety Lock. Safety Lock ON blocks all HEO hardware commands; the
automatic export and EV switches express independent intent and do not bypass
that lock or their respective readiness gates.
