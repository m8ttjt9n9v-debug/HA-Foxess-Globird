# Installation

## Current pilot installation

The first release should be installed manually on a clean test instance. Follow
the [clean-instance pilot guide](clean-instance-pilot.md). It has no hardware
control capability.

## HACS custom repository (after publishing)

1. In HACS, open **Integrations** and add this repository as a custom repository with category **Integration**.
2. Download **FoxESS Globird Energy Observer** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and select **FoxESS Globird Energy Observer**.
4. Complete the entity-mapping form. No edits to `configuration.yaml` are needed.

HACS installation requires a public GitHub repository. A GitHub release is
preferred for a custom repository; it becomes mandatory only when applying
for inclusion in HACS's default catalogue. This repository does not yet have
that published distribution channel.

The current 0.2.14 release is observer-only: it makes no service calls and cannot change inverter, EV, charger, socket, or tariff settings. Its planner and adapters are tested separately but remain disabled until commissioning gates are complete.

## Before setup

- Keep your existing controller enabled; this release is designed to run beside it.
- Identify a battery-SOC sensor and a signed grid-power sensor with a power unit of W, kW, or MW.
- If available, select the battery potential-capacity sensor (for example, FoxESS Modbus
  `sensor.bms_kwh_remaining_1`). The observer treats this as 100%-SoC potential capacity and
  calculates current energy as potential capacity × SoC. The numeric capacity remains the
  explicit fallback when no measured capacity sensor is selected.
- Confirm the grid sensor's sign convention using a known load. The setup form asks whether positive means import.
- Record usable battery capacity, battery floor, and any reserve required for the site.
- If you select a whole-house load sensor, set the free-charge window and the
  explicit learning fallback in the setup form. The observer then records
  non-free-window demand cycles locally; it does not control the inverter.

If a sensor is unavailable or has an unsupported unit, the integration displays unavailable calculations rather than guessing.
