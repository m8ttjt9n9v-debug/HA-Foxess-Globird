# EV free-allowance control policy

This file is the durable design record for the Mangerton Tessie policy and its
portable HACS implementation. Energy is measured in kWh; power is kW; current
is amps per charging phase.

## Objective

Use no more than the configured free-window energy cutoff across the whole
site: FoxESS battery charging, household load, and EV charging combined. The
default tariff allowance is 50 kWh and the default control cutoff is 49 kWh,
leaving a 1 kWh measurement and 30-second reconciliation margin. Both values
are site configuration, not constants in the planner.

The same policy must work at sites with different supplies. Mangerton is a
63 A single-phase service, whose physical maximum over the three-hour window
already limits consumption to roughly 43.5 kWh at 230 V. The H3 site is an
80 A three-phase service where a 15 kW battery charge, 11 kW EV charge, and
house demand can exceed 50 kWh. Service capacity alone is therefore not an
energy-budget control.

## Portable calculation

Every 30 seconds during the configured free window:

1. `remaining_kwh = cutoff_kwh - measured_free_window_import_kwh`.
2. Estimate current EV power from measured charger current, configured voltage,
   and physical phase count.
3. `non_ev_kw = max(measured_grid_import_kw - measured_ev_kw, 0)`.
4. Forecast house energy from the mapped house-load channel. While non-EV
   import indicates that the battery is charging, also reserve its configured
   capacity gap from current SoC to 100%. If house load is unavailable, reserve
   current non-EV import for the rest of the window instead.
5. `ev_budget_kwh = remaining_kwh - reserved_non_ev_kwh` and
   `ev_power_kw = ev_budget_kwh / hours_remaining`.
6. Convert that power to amps and round it down to the Tessie entity step.
7. Apply the lower of that allowance ceiling, the setup-time physical charger
   profile, and Tessie's entity maximum. The configured service-current guard
   remains an independent upper bound.

This calculation uses live SoC and commissioned capacity rather than a fixed
site-specific battery guess. A cloud-scheduled 15 kW battery charge is inferred
from non-EV site import; its shrinking capacity gap is reserved while actual
grid import continuously reduces the remaining allowance. Tessie therefore
runs at the rate that can fit beside the battery and house, then gains current
when capacity becomes available. Energy already imported is never counted
twice.

If the remaining allocation cannot support the configured minimum charger
current, HEO does not start an EV session. If HEO owns a running session, it
stops that session. Missing free-window import, grid power, cable, current, SoC,
or home-presence evidence fails closed for an HEO start.

## Ownership and control gates

FoxESS automatic control and Tessie automatic control have separate, default-off
gates. The shared Safety Lock blocks both. Enabling FoxESS never authorizes an
EV write, and enabling Tessie never authorizes a FoxESS write.

HEO records whether it started the current Tessie session. It may stop only
that owned session at target, window end, or allowance cutoff. Manual, Tessie,
and cloud-started sessions are reported but not seized. Consequently HEO can
guarantee its own contribution to the allowance; an external writer can still
consume beyond it and must be commissioned separately.

The mapped Tesla charge-limit entity remains the daily-use target. This release
does not overwrite that limit. The ported current policy gives EV priority up
to the dynamic allowance and electrical ceilings, while a confirmed service
overrun always reduces current.

## Electrical assumptions

The charger profile selected during setup is the physical authority. A smart
socket remains capped at 10 A; direct/EVSE profiles are explicitly selected.
Tessie may lower the ceiling but cannot raise it.

Aggregate grid power provides a sound average per-phase service guard for a
single-phase site or balanced three-phase EV/site. It cannot prove the loading
of one phase for a single-phase EV on a three-phase site. Such a deployment
must use a conservative charger profile and upstream protection until per-phase
grid-current telemetry is supported.

## H3 FoxESS lessons retained

- The live H3 inverter's direct Modbus registers are authoritative; Home
  Assistant work-mode entities can be stale.
- H3 work mode is register 49203 (`1` Self Use, `2` Feed-in First, `3` Backup).
  Remote control uses 46001 enable, 46002 timeout, and 46003–46004 active power.
- A manual diagnostic completing correctly does not clear the separate question
  of which post-test or scheduled writer changes mode afterward.
- Do not infer that a `12:01` configured daytime boundary explains a `00:01`
  write. Capture the service call or direct register transition before assigning
  causality.
- Keep automatic FoxESS control disabled while that writer is unresolved. The
  independent Tessie gate permits EV commissioning without reopening FoxESS
  writes.
