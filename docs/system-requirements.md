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
  protection. At Mangerton this is the non-heater base-house power; another
  site may map whole-house load only when that is the intended protected demand.
- Home Assistant history/storage plus its built-in template, statistics, and
  integration-style behavior used by the source model and HEO persistence.

The FoxESS work-mode and force-power entities must be explicitly mapped. Entity
availability alone does not prove safe hardware compatibility.

## Required for future faithful Tessie automation

Tessie is not required for the current automatic feature set. Restoring the
Mangerton EV policy will require explicitly mapped capabilities equivalent to:

- vehicle SoC and stored energy;
- lifetime driving energy for demand learning;
- location/at-home state and user override;
- cable connection, charging state, and actual current;
- writable charge current and its min/max/step metadata;
- charge-limit state/control where the source policy requires it; and
- an explicit charge start/stop path when the controller owns the session.

Mangerton uses Tessie entities for these roles. Portable code must map roles,
not embed that vehicle's `jns_x` entity IDs.

## Optional equipment and integrations

- Mangerton supports a switchable 10 A smart-socket charging path in addition
  to direct EVSE charging. Its current switch is provided by eWeLink, but a
  future port must depend on the explicitly mapped switch capability, not the
  vendor name.
- Weather forecast data supports Mangerton's weather-conditioned heater-energy
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
from the generated entities. HACS does not install Lovelace views. Personal
backgrounds, room devices, heaters, and unrelated Mangerton dashboard cards
are intentionally outside the portable integration.
