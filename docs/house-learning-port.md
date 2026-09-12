# Occupancy-aware house-learning provenance

This is a direct behavioral port of the Working Single Phase Pilot Site's
v1.4.24 protected-house energy policy. It selects one house budget for the
energy ledger; it does not introduce a weather optimizer or a second additive
forecast.

## Provenance map

The canonical source is the Working Single Phase Pilot Site
`configuration_v1.4.24.yaml` at commit
`5806b4a5313331fbc421108e9e0c98e661ca20fe`.

| Source behavior | HEO implementation |
| --- | --- |
| Lines 537–590: independent base and heater P80 statistics, seven-sample warm-up, 28 samples over 35 days | `DemandHistory`, `select_protected_cycle_budget`, and retained-history tests |
| Lines 648–672: separate persistent left-method energy integrals | `DemandCycleSampler` and `DailyDemandCycleSampler` with restart state and left-hand integration |
| Lines 874–918: Auto/Home/Away and occupied/away fallback inputs | config flow plus `select.home_energy_house_occupancy_mode` |
| Lines 1639–1767: one heater and one non-free base sample at each free-window boundary | paired coordinator samplers and storage payload |
| Lines 2400–2531: retained Tessie current is qualified by explicit charging state; EV and heater power are removed exactly once; the result is clamped at zero; free-window demand is excluded | `protected_base_house_power_kw`, state-qualified EV power, explicit base/whole-house topology, and optional heater mapping |
| Lines 3295–3400: conservative all-person occupancy classification | `classify_energy_occupancy` golden branch tests |
| Lines 3774–3915: away fallback, occupied fallback, or mature base P80 plus heater P80; one time-scaled result | `select_house_cycle_budget` and `remaining_protected_cycle_budget_kwh` |

## Preserved decisions

- Auto assumes Home if no `person` entities exist.
- Auto assumes Home if any person state or timestamp is uncertain.
- Auto selects Away only when nobody is home and every person has remained
  away for the configured confirmation period. The default is six hours.
- Manual Home and Away are persistent explicit overrides. Manual Away bypasses
  the confirmation delay exactly as the source does.
- The occupied fallback remains active until seven valid base samples exist.
  If a separate heater is mapped, seven valid heater samples are also required.
- Mature occupied learning is base P80 plus heater P80. Away never consumes the
  occupied learned value; it uses the configured away fallback.
- Only one selected full-cycle budget is scaled by remaining non-free time and
  passed to export protection. A weather/heater forecast cannot be added again.
- Energy accumulation uses the source integration sensor's `left` method, not
  an interpolated or newly designed demand model.
- The pilot clamps composed base-house power at zero. A negative raw FoxESS
  load therefore contributes zero; it does not erase all energy already
  accumulated for that cycle.

## Portable extension

The source site has a separately metered heater, so its house mapping excludes
that heater. Other sites may not. HEO therefore makes the heater mapping
optional:

- with a heater mapping, the source's paired-learning rule applies;
- without one, the mapped house sensor is treated as the complete protected
  demand and its mature P80 can replace the occupied fallback by itself.
- when the mapped house source includes EV charging, HEO removes measured EV
  power using the explicitly mapped charging state and actual current together
  with configured voltage and phase count. When it already excludes EV,
  subtraction is disabled so the load is not reduced twice.

This extension changes only source composition. It does not embed an entity ID,
heater size, service limit, tariff, schedule, or occupancy assumption in the
algorithm.
