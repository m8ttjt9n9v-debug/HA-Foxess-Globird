# EV daily-driving learning provenance

This is a direct behavioral port of the Working Single Phase Pilot Site's
v1.4.24 Tesla daily-driving and general charge-limit policy. It does not infer
trips, learn departure times, or replace the free-window current allocator.

| Source behavior | HEO implementation |
| --- | --- |
| Snapshot Tessie's cumulative lifetime energy at the configured free-window start | `snapshot_daily_driving_energy` and the exact boundary listener |
| Accept a sample only when the previous snapshot was exactly yesterday and the cumulative meter did not decrease | `DrivingSnapshotState` transition tests |
| Retain the latest 28 valid samples, no older than 35 days | restart-persistent `DemandHistory` |
| Select the 85th percentile after the configured minimum sample count | `plan_learned_general_charge_limit` |
| Estimate usable capacity as stored energy divided by vehicle SoC | `estimate_usable_ev_capacity_kwh` |
| Model the complete free-window SoC gain from current, voltage, duration, efficiency, and capacity | `estimate_free_window_soc_gain_percent` |
| During learning, subtract a complete free window and round down to the Tessie limit step | fallback branch golden test |
| After learning, add configured arrival reserve and P85 driving energy, subtract the free-window gain, and round up | learned branch golden test |
| Use the free-window limit during free charging, solar spill, or pre-free backfill; otherwise use the learned general limit | EV runtime policy selection |
| Retain the existing Tessie limit while away or disconnected | connection gate; no charge-limit write is attempted |
| Apply the anti-pause SoC headroom only while a powered baseline is required | existing charge-limit target planner |

The only topology extension is configured EV phase count in the electrical
conversion. A one-phase configuration reproduces the source equation; a
three-phase installation multiplies the modeled window energy by three. No
service rating, entity ID, time, capacity, current, voltage, or energy allowance
is embedded in control logic.

The lifetime-energy entity is optional so existing installations continue to
load. Without it, no daily samples are collected and the conservative
full-window fallback remains in effect when the other capacity inputs are
available.
