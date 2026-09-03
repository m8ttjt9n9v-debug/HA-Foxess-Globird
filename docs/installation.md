# Installation

## Current pilot installation

Install the release on a backed-up test instance first. Follow the
[clean-instance pilot guide](clean-instance-pilot.md). The default setup is
still non-writing; the optional FoxESS controller is a separate commissioning
step.

## HACS custom repository (after publishing)

1. In HACS, open **Integrations** and add this repository as a custom repository with category **Integration**.
2. Download **FoxESS Globird Energy Observer** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and select **FoxESS Globird Energy Observer**.
4. Complete the entity-mapping form. No edits to `configuration.yaml` are needed.

HACS installation requires a public GitHub repository. This project publishes
versioned GitHub releases for the custom-repository channel; inclusion in
HACS's default catalogue is a separate review process.

Version 0.2.30 is observer-by-default. It makes no writes unless automatic
control is enabled, Rehearsal mode is disabled, and the required FoxESS and EV
entities are explicitly mapped. The commissioned path writes only the mapped
EV current number. It confirms the Tessie/Tessy vehicle is at home before any
write; away or unknown presence is fail-closed. Free-window current follows
the persisted import allowance, while post-window solar spill and reserve-aware
pre-window backfill are bounded by the configured EV and inverter limits. EV
start/stop, vehicle charge-limit, and export writes remain disabled.

Version 0.2.28 adds guarded EV session start/stop. A session can start only
when the mapped Tessie/Tessy vehicle is home, connected, below its mapped
charge-limit target, and the planner has a managed charging intent. The
controller stops only sessions it started itself. Manually or cloud-started
sessions are not stopped. Import [`examples/dashboard.yaml`](../examples/dashboard.yaml)
as a Lovelace starter view; HACS does not install dashboards automatically.
Version 0.2.29 also exposes the read-only ZEROHERO window accumulator and its
hourly buckets as sensor attributes. Version 0.2.30 adds mapped battery SOC,
solar, house-load, and EV SOC entities for the portable dashboard template.

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
