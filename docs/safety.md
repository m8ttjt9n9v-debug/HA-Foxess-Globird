# Safety and support boundary

Home Assistant is supervisory software; it is not a substitute for compliant electrical design, equipment protections, breaker ratings, EVSE protections, or installer verification.

Version 0.8.0 is observer-by-default. ZEROHERO selling requires Local Modbus
ownership, the FoxESS automatic setting, the separate automatic-export toggle,
Safety Lock being OFF, complete FoxESS actuator mapping, valid telemetry, and
commissioned limits. The independent direct-EVSE/smart-socket free-window path
requires its own intent, commissioning and complete Tessie mappings. Automatic FoxESS free
charging is not implemented. The repository does not claim hardware
compatibility merely because an entity can be selected.

Before enabling actuation at any site, retain a backup, identify all existing
writers (including FoxCloud schedules and Tessie automations), verify live
signs and units, test outage/restart behaviour, and rehearse rollback on the
designated test instance. Never enable the Local Modbus owner while FoxCloud
Mode Scheduler is enabled. Do not enable a controller on a live site while an
unresolved writer remains.

FoxCloud may own the inverter while the EV path is used because that path writes
only mapped Tessie and, when selected, smart-outlet entities. This does not permit mixed FoxESS
control. Disable every other Tesla current/charge-limit writer before EV
commissioning. The controller confirms feedback and stops retrying an unchanged
target after three command attempts rather than flapping indefinitely.

The Diagnostics view is an explicit commissioning surface, not an automatic
schedule. It refuses charge tests outside the free window, requires Rehearsal
mode (Safety Lock) off and complete FoxESS mapping, bounds each run to 120 minutes, and
attempts to clear both force-power targets before restoring Self Use when a
run ends. Confirm inverter feedback after every test.

The integration exposes `switch.home_energy_safety_lock` so the state is
unambiguous in a dashboard: ON means locked and no hardware writes are
allowed; OFF is required before an explicitly submitted commissioning test.
