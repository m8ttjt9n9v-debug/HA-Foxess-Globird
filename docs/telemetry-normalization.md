# Telemetry normalization and sign commissioning

HEO accepts site-native FoxESS and template sensors, but its planners consume
one canonical electrical model. Unit conversion, sign conversion, freshness,
and source provenance happen once at the coordinator boundary. Control code
must not reinterpret a raw sensor independently.

## Canonical conventions

| HEO sensor | Positive means | Negative means |
| --- | --- | --- |
| `sensor.home_energy_grid_power` | grid import | grid export |
| `sensor.home_energy_battery_power` | battery charging | battery discharging |
| `sensor.home_energy_solar_power` | solar generation | not expected for ordinary generation |
| `sensor.home_energy_site_grid_current` | grid import | grid export |

`sensor.home_energy_grid_import` and `sensor.home_energy_grid_export` are the
non-negative magnitudes derived from canonical grid power. All power inputs are
converted from W, kW, or MW to kW; current inputs are converted to amperes.

## Supported battery source shapes

Sites may map either one signed battery-power sensor or a pair of non-negative
charge and discharge magnitude sensors. When the pair is selected, HEO retains
the Working Single Phase Pilot Site equation:

`canonical battery power = charge magnitude - discharge magnitude`

Both paired inputs are required and must be fresh. A negative magnitude is
invalid. The paired mapping takes precedence over a signed mapping so there is
only one battery value inside HEO.

## Commissioning and fail-closed behavior

Setup and reconfiguration ask what positive values mean for grid, battery,
solar, and optional service-current inputs. This is explicit configuration;
HEO does not infer direction from an entity name, a sunny instant, or a
particular inverter model. For example, a CT2 sensor that reports generation
as negative is configured as **generation negative**, while a conventional PV
sensor is configured as **generation positive**.

After checking the normalized values against known physical states, select
**I have verified these sign conventions**. Changing any normalized source or
direction automatically clears that confirmation. Upgrading an older entry
also clears it because migration cannot prove the old selections were checked.
While confirmation is clear, automatic FoxESS and EV paths fail closed even if
their request switches are on. Safety Lock and every other ownership,
commissioning, and telemetry gate still apply independently.

The diagnostic binary sensor
`binary_sensor.home_energy_sign_conventions_verified` exposes the confirmation
and selected directions. The canonical sensors retain source value, unit,
update time, validity, freshness, and failure reason as attributes. Raw entity
IDs remain available in Home Assistant state attributes for local commissioning
but are excluded from downloadable HEO diagnostics.

## Freshness and multiphase behavior

Every normalized source must have a valid timestamp and be no older than the
configured telemetry maximum age. Missing, stale, future-dated, non-finite, or
unsupported-unit readings become unavailable rather than zero. Multi-source EV
decisions additionally retain their existing coherence-window check.

On a single-phase site HEO may derive signed service current from canonical
grid power and configured voltage. Leave the optional current mapping blank to
use this path. The current mapping accepts only a sensor measured in amperes;
an upgraded single-phase entry containing an invalid power-unit mapping also
falls back to the grid-power derivation and exposes that provenance in the
normalized sensor. A multiphase site must map a trustworthy signed current for
the most-loaded service phase; aggregate three-phase power cannot prove
per-phase headroom.

Saving a changed normalized source or direction deliberately clears the
verification interlock and reloads the integration. During that reload the
economic export plan and its sellable-energy sensor can be unavailable because
no automatic control evaluation is permitted. Recheck the canonical signs and
explicitly confirm them again; do not treat an enabled automation-request
switch as proof that its independent commissioning gate is open.

## Upgrade boundary

The version-2 config migration preserves the meaning of the previous grid and
battery sign booleans, adds explicit solar and current directions, and locks
automatic writes pending sign verification. It does not change source entity
mappings, persistent learning histories, tariff ledgers, or ported planning
algorithms.
