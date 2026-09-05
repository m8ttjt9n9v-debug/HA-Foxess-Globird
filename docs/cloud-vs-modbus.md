# FoxESS cloud schedules versus local Modbus control

This project must have one clearly identified owner for the inverter's work
mode during any automated window. Do not assume that a local Modbus write will
override a FoxCloud schedule or that FoxCloud will reliably restart a charge
after a local write changes it.

What the available evidence says:

- The [FoxESS Modbus integration](https://github.com/nathanmarlor/foxess_modbus)
  talks directly to supported H3 and KH inverters and can expose work-mode and
  charge-power controls without FoxCloud.
- Its [force-charge documentation](https://github.com/nathanmarlor/foxess_modbus/wiki/Force-Charge-and-Discharge)
  says Force Charge requires Home Assistant to keep controlling the inverter;
  if Home Assistant stops, the inverter falls back to Back-up.
- The official [FoxCloud 2.0 manual](https://www.fox-ess.com/Public/Uploads/uploadfile/files/20260212/ENFoxCloud2.0AppUserManual.pdf)
  describes Mode Scheduler as time periods with a selected work mode, with
  uncovered time using the Remaining Time Work Mode.
- The FoxESS Modbus project's [remote-control investigation](https://github.com/nathanmarlor/foxess_modbus/discussions/513)
  found that Active Power temporarily takes precedence during a scheduled force
  charge, but expiry of the remote timeout returns to base work mode instead of
  resuming the schedule. In that tested case, the local write cancelled the
  remainder of the scheduled force-charge period. This is direct community
  testing, not a FoxESS firmware guarantee, so HEO does not generalise it into
  a safe mixed-control mode.

## Consequence for the 50 kWh window

If Home Assistant owns the window, it can pace the charge target and apply the
three completion outcomes in the integration policy:

1. At the configured import cutoff (49 kWh by default), restore Self Use and
   stop deliberate grid import, regardless of battery SoC.
2. At 100% SoC below the import cutoff, restore Back-up so the
   remaining allowance can serve the house from the grid.
3. While below the cutoff and below 100% SoC, continue Force Charge. Equality
   at the cutoff is deliberately treated as the no-more-import boundary.

If FoxCloud/Mode Scheduler owns the window, a Modbus change made by Home
Assistant may be overwritten or may cancel the remainder of the cloud period.
There is no evidence strong enough to promise that FoxCloud will restart the
charge, nor that it will leave the local target in place. The safe rule is to
choose one owner for the window; if ownership is mixed during testing, remain
observer-only and record the mode, charge-power, SoC, grid-import and schedule
state at one-minute intervals.

This means an enabled Mode Scheduler owns more than its named charge periods:
its Remaining Time Work Mode covers the rest of the day. "The noon slot is not
active" is therefore not evidence that an evening Modbus writer has exclusive
ownership.

The HACS integration requires one explicit owner:

- **Observer only**: no HEO FoxESS writes.
- **Local Modbus**: FoxCloud Mode Scheduler must be disabled. HEO may use the
  commissioned local actuator mappings.
- **FoxCloud Mode Scheduler**: all HEO Modbus automation and diagnostics are
  blocked for the entire day. Tessie retains its independent gate.

Dynamic evening export under FoxCloud ownership requires a cloud-schedule
adapter that reads the complete schedule, preserves the standing free-charge
period, rejects overlaps, and writes a second bounded ForceDischarge period.
HEO does not yet provide that adapter. A Modbus export is not substituted while
FoxCloud owns the schedule.
