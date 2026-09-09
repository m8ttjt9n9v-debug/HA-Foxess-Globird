# Daily EV ready-by backfill

This optional policy extends the Working Single Phase Pilot Site's proven
latest-start EV backfill. It does not replace the original Local-Modbus-only
pre-free policy.

## Proven source retained

| Decision | Pilot source | HEO implementation |
| --- | --- | --- |
| Work in AC wall energy | `configuration_v1.4.24.yaml:4037-4057` | Battery energy above floor and configured reserve is converted with configured discharge efficiency before comparison with wall demand. |
| Protect remaining house demand once | `configuration_v1.4.24.yaml:3780-3915` | The occupancy-aware remaining house budget is subtracted once. |
| Cap by vehicle room | `configuration_v1.4.24.yaml:4119-4188` | Planned wall energy cannot exceed room to the configured EV soft limit. |
| Calculate duration and latest start | `configuration_v1.4.24.yaml:4250-4308` | Discrete power determines duration; scheduling works backwards from the configured ready time. |
| Freeze an active phase across restart | `configuration_v1.4.24.yaml:686-692,4273-4295` | Cycle, delivered energy, session target and frozen start are stored in Home Assistant storage. |

## Separately configured extension

The extension adds four site inputs: daily protected EV wall energy, ready-by
time, maximum outside-window EV power as a percentage of commissioned inverter
output, and an optional planning buffer. Zero protected energy disables it.

The accounting cycle runs from one ready deadline to the next, not midnight.
This matters when HEO owns Local Modbus export: an evening export must retain
energy intended for the following morning. Charging itself is restricted to
midnight through the ready deadline.

At each decision:

1. Remaining allocation is configured allocation minus confirmed wall energy
   delivered by this policy in the current ready cycle.
2. Energy available after battery floor and fixed reserve is converted to AC.
3. The remaining occupancy-aware house budget is protected.
4. The remaining EV allocation is protected next.
5. Any energy beyond both protections is discretionary. The policy offers the
   fraction `hours until ready / hours until next free window`, capped at one.
6. The result is capped by current vehicle room and live available energy.
7. Current is capped by the configured inverter percentage, connector rating,
   and current service headroom, then rounded down to the actuator step.
8. Duration determines the latest start. A plan that would have needed to start
   before midnight reports an explicit shortfall/unachievable state.

The active session stops at its frozen energy target, the EV soft limit, the
ready deadline, loss of safe energy, or disconnect. Only confirmed Tessie
actual current is integrated into delivered wall energy; gaps beyond the
configured telemetry age are not guessed.

## Ownership

This policy writes Tessie only, so it can operate with FoxCloud Scheduler as the
inverter owner. It never writes a FoxESS entity. With FoxCloud ownership the
allocation is opportunistic: prior cloud-controlled export may already have
spent it, and the live post-midnight energy ledger decides what remains.

With Local Modbus ownership, HEO's ZEROHERO export calculation additionally
protects the remaining allocation for the next ready deadline. That prospective
guarantee is unavailable when another controller owns inverter discharge.

Safety Lock, EV commissioning, sign verification, explicit mappings, service
limits and bounded reconciliation remain mandatory.

## Charge to Full exception

`switch.home_energy_ev_charge_to_full` is an explicit paid-grid exception. It
starts charging outside the free window and bypasses the daily energy and
inverter-percentage caps, but never the commissioned connector or service
limits. It clears at 100%, after disconnect once started, or after its configured
maximum duration. The dashboard should make the paid-import possibility clear.
