# Clean Home Assistant pilot

This is the first installation test for the **observer-only** 0.2.1 release.
It verifies that the application installs, calculates values, reacts to state
changes, can be reconfigured, and can be removed. It must not be connected to
an inverter, EV, EVSE, smart socket, or production credentials.

## Supported pilot environment

- Home Assistant Core **2026.8.3** is the supported pilot baseline and is
  exercised by the automated test suite.
- A fresh Home Assistant OS, Container, or Core installation is suitable.
- HACS is not needed for this first manual pilot.

## Install the application

1. Transfer the release archive for `home_energy_orchestrator-0.2.1` to the new Home
   Assistant host and extract it in the Home Assistant configuration directory.
   It creates `custom_components/home_energy_orchestrator` in the correct
   location. Alternatively, create `<Home Assistant config>/custom_components`
   and copy the repository's complete `custom_components/home_energy_orchestrator`
   directory into it.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and choose
   **FoxESS Globird Energy Observer**.

Home Assistant will label it as an untested custom integration. That warning
is expected until the integration has a published release and broader testing
evidence.

## Create safe test inputs

In **Developer Tools → States**, create these temporary states. State changes
made here do not control hardware and disappear after a Home Assistant restart.

| Entity ID | State | Attributes |
| --- | ---: | --- |
| `sensor.test_battery_soc` | `60` | `{ "unit_of_measurement": "%" }` |
| `sensor.test_grid_power` | `1200` | `{ "unit_of_measurement": "W" }` |
| `sensor.test_house_load` | `800` | `{ "unit_of_measurement": "W" }` |

Complete setup with these values:

| Setup field | Value |
| --- | --- |
| Site name | `Pilot Site` |
| Battery SOC | `sensor.test_battery_soc` |
| Battery potential capacity | leave blank for this synthetic pilot |
| Usable battery capacity | `20` kWh |
| Minimum battery SOC | `10` % |
| Additional reserve | `2` kWh |
| Signed grid power | `sensor.test_grid_power` |
| Positive grid means import | enabled |
| Whole-house load | `sensor.test_house_load` |
| EV minimum / maximum current | `6` A / `32` A |
| Charging voltage | `230` V |

## Expected results

The created device should expose these values within 30 seconds (normally it
updates immediately):

| Entity name | Expected state |
| --- | ---: |
| Status | `observer_only` |
| Available Battery Energy | `8` kWh |
| Grid Import | `1.2` kW |
| Grid Export | `0` kW |
| EV Maximum Configured Power | `7.36` kW |

Change `sensor.test_grid_power` to `-2000` W. **Grid Export** must update to
`2` kW without restarting Home Assistant. Then use **Reconfigure** on the
integration to change usable capacity to `25` kWh; Home Assistant must reload
the integration and retain the updated value.

Finally, remove the integration. Its entities will become unavailable; this is
normal Home Assistant entity-registry behaviour and confirms the runtime has
unloaded.

For the learning path, keep `sensor.test_house_load` mapped, use the configured
12:01–14:59 free-charge window, and inspect the read-only learning sample and
budget entities after recording complete cycles. No actuator is enabled by
this pilot.

## Record the pilot

Record the Home Assistant version, installation method, test results, and any
log entries. Do not include access tokens, external URLs, home coordinates, or
production entity history in an issue or diagnostic.

## After this pilot

Once this installation passes, the next stage is to map read-only telemetry on
the new site and compare the observer output over seven tariff cycles. Offering
the project through HACS as a custom repository comes after a public GitHub
repository and successful HACS/Hassfest checks; a GitHub release is preferred.
HACS default-catalogue inclusion is a separate step that requires a full
GitHub release after those checks pass.
