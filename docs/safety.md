# Safety and support boundary

Home Assistant is supervisory software; it is not a substitute for compliant electrical design, equipment protections, breaker ratings, EVSE protections, or installer verification.

Version 0.12.0 is observer-by-default. ZEROHERO selling requires Local Modbus
ownership, the FoxESS automatic setting, the separate automatic-export toggle,
Safety Lock being OFF, complete FoxESS actuator mapping, valid telemetry, and
commissioned limits. The independent direct-EVSE/smart-socket free-window path
requires its own intent, commissioning and complete Tessie mappings. Automatic
FoxESS free charging is a separate default-off Local Modbus extension with a
persistent fixed-power session and bounded Self Use restoration. The repository
does not claim hardware compatibility merely because an entity can be selected.

Automatic FoxESS and EV writes also require explicit sign commissioning. Any
upgrade from the ambiguous legacy booleans, or any later change to a normalized
source or direction, clears that confirmation and closes both automatic gates.
This verification gate is additional to Safety Lock, not a replacement for it.

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

The battery-charge controller likewise stops after three unconfirmed command
attempts. Its SoC target qualifies session start only; once HEO owns the
session, it remains latched until the configured end to prevent threshold
flapping. Turn off the independent charge switch and confirm Self Use before
engaging Safety Lock or unloading an active controller, because Safety Lock
also forbids recovery writes.

The Diagnostics view is an explicit commissioning surface, not an automatic
schedule. It refuses charge tests outside the free window, requires Rehearsal
mode (Safety Lock) off and complete FoxESS mapping, bounds each run to 120 minutes, and
attempts to clear both force-power targets before restoring Self Use when a
run ends. Confirm inverter feedback after every test.

The integration exposes `switch.home_energy_safety_lock` so the state is
unambiguous in a dashboard: ON means locked and no hardware writes are
allowed; OFF is required before an explicitly submitted commissioning test.
