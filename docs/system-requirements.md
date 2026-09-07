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
- A trustworthy mapped protected-house load sensor for learned house-energy
  protection. At the Working Single Phase Pilot Site this is the non-heater base-house power; another
  site may map whole-house load only when that is the intended protected demand.
- Home Assistant history/storage plus its built-in template, statistics, and
  integration-style behavior used by the source model and HEO persistence.

The FoxESS work-mode and force-power entities must be explicitly mapped. Entity
availability alone does not prove safe hardware compatibility.

## Required for Tessie EV automation

Tessie is optional when EV control is not commissioned. The ported EV
free-window policy requires explicitly mapped capabilities equivalent to:

- vehicle SoC and stored energy;
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

The direct path never issues a stop or pause. The smart-socket path additionally
requires a mapped on/off outlet, its commissioned physical current ceiling,
and selected recovery/settling timings. It does not depend on a particular
outlet vendor.

Solar-spill control additionally
requires an explicitly mapped signed battery-power sensor, its charge-positive
sign convention, battery SoC threshold, and coherent grid/battery/Tessie
timestamps. Latest-start pre-free backfill additionally requires the Local
Modbus ZEROHERO export ledger. Both outside-window stages are independently
default-off and are rejected unless Local Modbus is selected as FoxESS owner.

Learned driving demand remains a future, last-priority port pending review of
Tessie's native capabilities. Lifetime driving-energy data is therefore not a
current installation requirement.

The Working Single Phase Pilot Site uses Tessie entities for these roles. Portable code must map roles,
not embed that vehicle's `jns_x` entity IDs.

## Optional equipment and integrations

- The Working Single Phase Pilot Site uses an eWeLink-provided switch for its
  smart-socket charging path, but HEO depends only on the explicitly mapped
  on/off switch capability, not the vendor name.
- Weather forecast data supports the Working Single Phase Pilot Site's weather-conditioned heater-energy
  model. It is optional unless that policy is ported.
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

## Dashboard installation

Import `examples/dashboard.yaml` manually or build a site-specific dashboard
from the generated entities. HACS does not install Lovelace views. The example
preserves the seven-view operational structure while using only HEO-owned
entity IDs. Personal backgrounds, vehicle-native Tessie cards, weather, room
devices, heaters, and unrelated site cards are intentionally local overlays.
