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

Version 0.4.0 is observer-by-default. Automatic FoxESS free charging is not
present; the earlier simplified controller remains removed. The verified
ZEROHERO export path and the faithful direct-EVSE free-window Tessie path are
separately gated. Bounded FoxESS Diagnostics remain explicitly submitted
actions.

Automatic ZEROHERO export is a third, default-off behavior toggle beneath the
FoxESS gate. It operates only when **Local Modbus** is the selected FoxESS
owner, automatic FoxESS control is enabled, the complete Modbus actuator map
is valid, and Safety Lock is OFF. Do not enable it while FoxCloud Mode
Scheduler is enabled. Configure the boosted window, 21:01 restoration time,
daily export cap, fixed discharge power, efficiency, and any physically
mandatory connected-EV baseline during setup or reconfiguration. The full
ported behavior is recorded in the
[ZEROHERO export policy](zerohero-export-policy.md).

Import [`examples/dashboard.yaml`](../examples/dashboard.yaml) as a Lovelace
starter view; HACS does not install dashboards automatically. Generated
entities use stable `sensor.home_energy_*` IDs where the stable ID is unused.

Direct-EVSE control requires every Tessie telemetry and actuator mapping, a
commissioned physical current ceiling, a positive service limit, the independent
**Automatic EV Control** switch, and Safety Lock OFF. It operates only during
the configured free window and never writes FoxESS. A multiphase site must also
map a signed amperage sensor for the most-loaded service phase, positive for
import; HEO deliberately refuses to infer per-phase safety from aggregate
three-phase power. Commission first with the EV intent off, verify all portable
diagnostic values, and keep any competing Tesla current automation disabled.

Version 0.3.2 adds a separate **Diagnostics** dashboard view and matching
commissioning entities. The editable power and duration fields only prepare a
preview; pressing a start button is the explicit submit action. Force-charge
tests are rejected outside the configured free window, both test types are
limited to 120 minutes, and the controller restores Self Use at the end. The
discharge preview uses the configured standard or ZEROHERO-window export rate
and updates with the current time. Rehearsal mode must be disabled and all
three FoxESS actuator mappings complete; the automatic scheduler itself may
remain disabled.

## Before setup

- HEO may observe beside an existing controller. Before selecting Local Modbus
  or enabling any write path, disable every other inverter writer and record
  its previous state for rollback.
- Identify a battery-SOC sensor and a signed grid-power sensor with a power unit of W, kW, or MW.
- If available, select the battery potential-capacity sensor (for example, FoxESS Modbus
  `sensor.bms_kwh_remaining_1`). The observer treats this as 100%-SoC potential capacity and
  calculates current energy as potential capacity × SoC. The numeric capacity remains the
  explicit fallback when no measured capacity sensor is selected.
- Confirm the grid sensor's sign convention using a known load. The setup form asks whether positive means import.
- Record usable battery capacity, battery floor, and any reserve required for the site.
- If you select a protected house-load sensor, set the free-charge window and
  explicit learning fallback. At Mangerton this source excludes separately
  forecast heaters. The observer records non-free-window cycles locally; the
  learner itself does not control the inverter.

If a sensor is unavailable or has an unsupported unit, the integration displays unavailable calculations rather than guessing.
