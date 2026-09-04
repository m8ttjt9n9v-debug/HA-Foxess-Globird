# FoxESS cloud schedules versus local Modbus control

This project must have one clearly identified owner for the inverter's work
mode during any automated window. Do not assume that a local Modbus write will
override a FoxCloud schedule or that FoxCloud will reliably restart a charge
after a local write changes it.

What the available evidence says:

- The [FoxESS Modbus integration](https://github.com/nathanmarlor/foxess_modbus)
  talks directly to supported H3 and KH inverters and can expose work-mode and
  charge-power controls without FoxCloud.
- Its [force-charge documentation](https://github-wiki-see.page/m/nathanmarlor/foxess_modbus/wiki/Force-Charge-and-Discharge)
  says Force Charge requires Home Assistant to keep controlling the inverter;
  if Home Assistant stops, the inverter falls back to Back-up.
- The official [FoxCloud 2.0 manual](https://au.fox-ess.com/Public/Uploads/uploadfile/files/20260611/FoxCloudApp2.0UserManual.pdf)
  describes Mode Scheduler as time periods with a selected work mode, with
  uncovered time using the Remaining Time Work Mode.
- The FoxESS Modbus community reports that the inverter manager's scheduler
  can win over local active-power writes, causing the two controllers to fight
  or the local force-charge period to be cancelled. This is community evidence,
  not a FoxESS guarantee, so it must be verified on the exact inverter and
  firmware before relying on it.

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

The HACS release therefore exposes the target and completion recommendation as
read-only state. It does not fight a cloud schedule or issue local writes until
the exact H3 firmware, schedule ownership, and response/recovery behaviour have
been commissioned.
