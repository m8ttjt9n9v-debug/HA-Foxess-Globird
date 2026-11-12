# Dynamic EV reservation — local candidate

This optional configuration extension changes energy accounting, not the
inverter or EV writer. Learning remains advisory: no weekday prediction,
remaining-trip estimate or learned charge percentage changes the chosen target.

## One protected pool

Select **Dynamic SoC shortfall** in EV Charging policies or native
`select.home_energy_ev_reservation_mode`. Existing installations default to
**Fixed daily energy**. The existing **Prioritise EV before export** switch
enables Dynamic protection and minimum-recovery charging; switching it off
releases Dynamic without reviving an old fixed allocation.

For Dynamic, the wall-energy reservation is:

`capacity × max(min(minimum + buffer, normal target) − current SoC, 0) / efficiency`

Percent quantities use the same percentage units; e.g. capacity60kWh, target42%,
current35%, efficiency95% reserves approximately4.42kWh. The configured normal
non-override target still clips recovery. An invalid or stale SoC, unavailable
capacity or invalid setting cannot be replaced by zero protection.

Dynamic reservation planning can retain a healthy, exactly vehicle-bound
native Tessie SoC under two configurable limits:

- **EV reservation SoC maximum age** applies when the provider explicitly reports
  asleep. It defaults to 24 hours and accepts 0.025–48 hours.
- **Unplugged EV reservation SoC maximum age** applies when the provider reports
  online and its charge-state frame and the mapped native cable and charging
  entities agree that the vehicle is unplugged. It applies both at home and
  away, defaults to 90 minutes, and accepts 0–1,440 whole minutes. Zero disables
  the extension. The live limit still applies to plugged vehicles and to
  generic sources.

Both settings are available in setup and as native numbers
(`number.home_energy_ev_reservation_soc_max_age_hours` and
`number.home_energy_ev_reservation_unplugged_soc_max_age_minutes`). The
original vehicle measurement time governs age. HA reports, repeated reads,
restart and unrelated updates cannot renew it. Provider failure, offline status,
unloading, identity/value mismatch, future time and expiry make protection
unavailable. Loss of unplugged evidence or a shorter setting takes effect on
the next evaluation.

The age bounds apply only to energy accounting. Current, physical handoff
and EV commands retain their original checks. Expiry is an evidence validity
boundary, so there is no grace period or hysteresis when evidence expires.

Battery floor/reserve and discharge efficiency are applied first. Protect the
remaining house demand and mandatory keepalive exactly once. Reserve the
selected fixed OR dynamic EV amount from that pool; export gets the non-negative
balance. The EV can consume its own reserved share as well as an independently
eligible discretionary share, not only the amount left after its own deduction.
Underfunding can leave no export energy while the available reserved energy
remains usable by its intended EV. A reservation never creates extra energy.
Fixed allocation is spendable by its accounting policy: late pre-free charging
does not borrow tomorrow's allocation without crediting that ready-cycle ledger.
Cached withholding proof and the current protected pool are both ceilings;
changing a setting alone cannot invent energy previously withheld from export.

Away/unplugged vehicles retain Dynamic protection. Ordinary automatic presence
or a manual house-energy Away choice does not release it. If the car is
unreachable for an extended absence, missing qualified SoC can withhold
automatic export with Dynamic priority enabled. Other house modes retain
their own controls. A separate, explicitly selected Extended Away policy
and journey prediction remain deferred.

## Timing, hysteresis and ownership

While away below the minimum, the unreserved balance can export. When the
vehicle returns home and connects below its minimum, the existing export writer
reduces to Self Use and confirms physical handoff before the existing EV writer
uses its reservation. Once that recovery completes, the remaining balance may
export if its window/price and all other conditions still qualify. Simultaneous
forced export and surplus EV charging is not introduced.

The existing persistent recovery starts below the minimum and releases at the
configured buffered target. Its journal survives disconnect/restart; the mode
does not introduce a second latch or delay. Reservation arithmetic itself is
continuous across the minimum and contains no switching threshold. Emergency,
stale-source, reserve, current, ownership and disabled-control reductions remain
immediate. Existing timing choices, normal targets, house reserves, total
outside-window inverter percentage and electrical limits remain binding.

## Provenance and corrections

| Retained source or extension | Implementation |
| --- | --- |
| Pilot house budget, floor/reserve and AC conversion (`configuration_v1.4.24.yaml:3780–4060`) | Existing ledger and house learning remain authoritative; `planner/ev_reservation.py` splits their one AC pool. |
| Pilot vehicle room and wall-energy conversion (`configuration_v1.4.24.yaml:4119–4188`) | Existing capacity/efficiency and normal SoC ceiling; new Dynamic amount is a separately selected extension. |
| Fixed ready-cycle allocation | Keep configured allocation minus confirmed policy delivery. Do not stack it with Dynamic or strand it behind its own export deduction. |
| Existing before-export recovery/handoff | Retain the same bound recovery journal and physical stop/baseline proof. Dynamic replaces only the blanket away-vehicle SoC block. |
| Native numeric current versus fresh local power | Shared measurement qualification uses the native vehicle measurement clock and identity, not request amps, HTTP/report publication or unrelated Modbus freshness. |

The telemetry correction distinguishes fresh numeric ramp lag from an expired
measurement. Native actual current and charging state must agree with their
loaded, healthy, same-vehicle source. All mapped native policy anchors retain
that identity even when their values are unavailable. Explicit fully generic
publisher contracts are retained; a mixed native/generic physical pair cannot
borrow HA report freshness to hide a missing native provider. No new poller or
synthetic current estimate is added.

Regression coverage includes budget conservation, own-reservation availability,
both export pathways, connection/return handoff, buffered boundaries and jitter,
reload/reconnect, changed settings, native expiry/provider failure across awaits,
and delayed-but-fresh current beside independently fresh Modbus readings.
Sleeping-car lifecycle cases also cover above/below-minimum reservations,
ordinary and price export, strict connected-EV rejection, exact planning expiry,
wake/offline/failure and setting edits during export/checkpoint boundaries.

Installation does not select Dynamic or change any deployed dashboard. A local
candidate requires a recorded exact commit, version and file hashes, recoverable
backup and separately authorised activation after verification. It is not an
official HACS release or proof of future retailer payment.
