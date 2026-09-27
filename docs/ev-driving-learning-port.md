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

## Learning warm-up

P85 is intentionally not calculated from the first few days of driving. HEO
records one valid daily-driving sample when it can compare Tessie's cumulative
lifetime-energy reading at a free-window boundary with the reading from the
same boundary on the preceding day. A missed boundary, an unavailable reading,
or a cumulative meter that decreases does not create a sample.

The **EV driving samples required for P85 learning** setting controls when the
model becomes mature. Its default is **14 valid daily samples**, so a new
installation normally needs at least 14 completed daily boundary-to-boundary
cycles. Until that threshold is reached, **EV Driving P85** is shown as
unavailable. When the current vehicle SoC, stored energy, and charge-limit
metadata are valid, the controller uses its conservative full-window fallback
until the P85 model is mature. The displayed **EV Driving Learning Samples**
value is the authoritative progress counter. The retained history is limited
to the newest 28 valid samples and samples older than 35 days are discarded.

**EV Driving Learning Status** is a separate live-input diagnostic. Its
`unavailable` value does not mean that more samples are required; it means HEO
cannot currently form either the fallback or learned limit because required
live evidence or a configured learning input is unavailable or invalid. Check
the mapped Tessie vehicle SoC, stored-energy, and charge-limit entities first.
P85 can still be
unavailable solely because the configured sample threshold has not yet been
reached.
