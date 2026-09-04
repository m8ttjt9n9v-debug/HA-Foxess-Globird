# Safety and support boundary

Home Assistant is supervisory software; it is not a substitute for compliant electrical design, equipment protections, breaker ratings, EVSE protections, or installer verification.

Version 0.3.1 is observer-by-default. Its optional FoxESS path is a bounded
pilot controller, enabled only by an explicit automatic-control setting,
disabled Rehearsal mode, complete FoxESS actuator mapping, valid telemetry,
and a commissioned inverter limit. The EV path writes only the explicitly
mapped current number and, for a session it started itself, the mapped charge
switch. It never changes the vehicle charge-limit or FoxESS export settings.
Away, unknown, disconnected, or ambiguous vehicle presence fails closed. The
repository does not claim hardware compatibility merely because a sensor can
be selected in the setup form.

Before enabling actuation at any site, retain a backup, identify all existing
writers (including FoxCloud schedules and Tessie automations), verify live
signs and units, test outage/restart behaviour, and rehearse rollback on the
disposable instance. Do not enable the controller on the live H3 site until
those checks have been recorded.

The Diagnostics view is an explicit commissioning surface, not an automatic
schedule. It refuses charge tests outside the free window, requires Rehearsal
mode off and complete FoxESS mapping, bounds each run to 120 minutes, and
attempts to clear both force-power targets before restoring Self Use when a
run ends. Confirm inverter feedback after every test.
