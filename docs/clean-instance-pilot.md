# Clean Home Assistant pilot

Use a clean Home Assistant instance to validate installation and observer
calculations without connecting actuators, an EV, production credentials, or a
live inverter.

## Install

1. Copy `custom_components/home_energy_orchestrator` into the clean Home
   Assistant configuration's `custom_components` directory, or install the
   repository through HACS.
2. Restart Home Assistant.
3. Add **FoxESS GloBird Tesla Energy Orchestrator** under **Settings → Devices &
   services**.

## Synthetic inputs

In **Developer Tools → States**, create temporary states:

| Entity ID | State | Attributes |
| --- | ---: | --- |
| `sensor.test_battery_soc` | `60` | `{ "unit_of_measurement": "%" }` |
| `sensor.test_grid_power` | `1200` | `{ "unit_of_measurement": "W" }` |
| `sensor.test_house_load` | `800` | `{ "unit_of_measurement": "W" }` |

Configure a 20 kWh battery, 10% floor, 2 kWh reserve, positive grid meaning
import, and leave every FoxESS actuator blank. Keep ownership **Observer only**,
automatic control off, and Safety Lock on. Site/EV electrical values may be
entered explicitly for calculation tests; do not select an actuator or infer a
charger profile.

Expected values are approximately:

| Entity | State |
| --- | ---: |
| Status | `observer_only` |
| Available battery energy | `8` kWh |
| Grid import | `1.2` kW |
| Grid export | `0` kW |

Change grid power to `-2000` W. Grid export should become `2` kW without a
restart. Reconfigure usable capacity to `25` kWh and verify the entry reloads.
No service-call events should be generated.

## Record and remove

Record the Home Assistant and integration versions, values, reload behavior,
and relevant log entries. Do not publish tokens, external hostnames, precise
location data, or production history. Remove the integration and verify its
entities unload.

Use only a deliberately selected clean instance. Never treat a site as a test
proxy merely because it is reachable from the development network.
