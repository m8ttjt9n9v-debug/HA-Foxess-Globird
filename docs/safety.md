# Safety and support boundary

Home Assistant is supervisory software; it is not a substitute for compliant electrical design, equipment protections, breaker ratings, EVSE protections, or installer verification.

Version 0.2.24 is observer-by-default. Its optional FoxESS path is a bounded
pilot controller, enabled only by an explicit automatic-control setting,
disabled Rehearsal mode, complete FoxESS actuator mapping, valid telemetry,
and a commissioned inverter limit. Tessie/EV and export writes remain disabled.
The repository does not claim hardware compatibility merely because a sensor
can be selected in the setup form.

Before a future actuation release is enabled at any site, retain a backup, identify all existing writers, verify live signs and units, test outage/restart behaviour, and rehearse rollback. See the engineering gates for the complete commissioning requirements.
