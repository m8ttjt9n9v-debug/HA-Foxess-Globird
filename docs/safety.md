# Safety and support boundary

Home Assistant is supervisory software; it is not a substitute for compliant electrical design, equipment protections, breaker ratings, EVSE protections, or installer verification.

Version 0.4.0 is observer-by-default. Its only automatic write path is ZEROHERO
selling, enabled only by Local Modbus ownership, the FoxESS automatic setting,
the separate automatic-export toggle, Safety Lock being OFF, complete FoxESS
actuator mapping, valid telemetry, and commissioned limits. Automatic FoxESS
free charging and Tessie writes are not implemented. The repository does not
claim hardware compatibility merely because an entity can be selected.

Before enabling actuation at any site, retain a backup, identify all existing
writers (including FoxCloud schedules and Tessie automations), verify live
signs and units, test outage/restart behaviour, and rehearse rollback on the
designated test instance. Never enable the Local Modbus owner while FoxCloud
Mode Scheduler is enabled. Do not enable a controller on a live site while an
unresolved writer remains.

The Diagnostics view is an explicit commissioning surface, not an automatic
schedule. It refuses charge tests outside the free window, requires Rehearsal
mode (Safety Lock) off and complete FoxESS mapping, bounds each run to 120 minutes, and
attempts to clear both force-power targets before restoring Self Use when a
run ends. Confirm inverter feedback after every test.

The integration exposes `switch.home_energy_safety_lock` so the state is
unambiguous in a dashboard: ON means locked and no hardware writes are
allowed; OFF is required before an explicitly submitted commissioning test.
