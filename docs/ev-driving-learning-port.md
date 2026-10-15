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

The topology extension is configured EV phase count in the electrical
conversion. A one-phase configuration reproduces the source equation; a
three-phase installation multiplies the modeled window energy by three. No
service rating, entity ID, time, capacity, current, voltage, or energy allowance
is embedded in control logic.

## Optional dedicated planning capacity

The retained ratio above is a compatibility path, not a direct measurement of
usable battery capacity. Remaining kWh and displayed SoC can include different
BMS/buffer assumptions. Dividing them can substantially overestimate capacity
at low SoC, moving a latest-start trip too early. The dedicated-capacity option
changes this input only; it does not introduce another charging controller.

Under **Reconfigure → Car**, select **EV planning capacity source**:

- **Legacy remaining-energy/SoC estimate** preserves existing installations
  exactly, including their original stored-energy requirement. Selecting another
  source is explicit; an upgrade does not silently switch any site.
- **Tessie nominal full-pack capacity** reads the existing loaded Tessie cache
  for the exact car identified by the commissioned SoC mapping. HEO makes no
  additional HTTP request, stores no Tessie credential and adds no timer. The
  optional upstream field requires a supporting Tessie/Tesla version; a missing
  field or unsupported provider shape is unavailable, not a guessed vehicle.
- **Mapped capacity sensor** accepts an explicitly selected sensor in Wh or
  kWh, independently of provider. Never map remaining energy as full capacity.
- **Configured capacity only** uses a reviewed numeric planning capacity.

Set **EV planning capacity fallback (kWh)** if a reviewed fixed fallback is
desired. Zero or blank means no fallback. Dedicated-source failures use only
this explicit fallback or expose unavailable; they never resume the ratio
behind the operator's back. A fallback does not claim fresh provider evidence.
No vehicle model, capacity or site value is hardcoded.

Tessie supplies **nominal full-pack** capacity, not a promise of exact usable
energy. Its battery-health capacity is another estimate, suitable for reviewing
a fallback, not an automatically assumed interchangeable definition. The stable
entity ID `sensor.home_energy_ev_usable_capacity` is retained for compatibility;
its default display name is now **EV Planning Capacity**. Attributes identify
the source, basis, observation time and fallback reason. Capacity must be finite
and positive, at most 1,000 kWh for the new sources. Provider observations are
accepted for at most 24 hours, with invalid/future timestamps, failed or unloaded
providers, restored mapped states and ambiguous car bindings rejected. This
slow-capacity age limit does not relax any fast SoC/grid/power safety gate.

| Existing consumer | Dedicated-input extension; retained behaviour |
| --- | --- |
| General learned limit and free-window SoC gain | Replace only the capacity input; preserve P85 history, rounding and policy ordering |
| HACS Trip and older helper Trip | Use the same projected capacity and existing deficit/efficiency/max-power formula; preserve target, departure, ownership and cancellation |
| Free-energy allowance | Use capacity times remaining SoC deficit; preserve house/battery projection and allowance guard |
| Pre-free and ready-by backfill | Use the same vehicle energy-room input; preserve protected house/export budgets, timing, fixed-current latch and session journal |

With an explicit valid capacity, remaining-energy telemetry is no longer needed
solely to infer that capacity; all other commissioned mappings and guards still
apply. SoC exactly zero can be planned without division. Invalid SoC remains
invalid. The existing charging-efficiency setting is unchanged: neither a
capacity correction nor an all-charger average silently recalibrates it.

Validation includes synthetic low-SoC offset cases, selected source versus
legacy parity, both trip wrappers, invalid values/units/time, multiple vehicles,
provider startup/unload/reload and explicit fallback. Live acceptance remains
separate from simulated tests. Keep individual vehicle readings and operational
evidence out of the public repository.

Primary references: [Tessie's nominal capacity field](https://www.tessie.com/announcements/whats-new-in-16-1),
[battery health](https://developer.tessie.com/reference/get-battery-health) and
[battery metric definitions](https://help.tessie.com/article/162-understanding-battery-metrics).

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
