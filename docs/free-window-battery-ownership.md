# Free-window battery ownership boundary

## Canonical-source finding

The Working Single Phase Pilot Site v1.4.24 configuration is the port authority.
It contains the local-Modbus ZEROHERO `Force Discharge` writer and the complete
Tessie free-window controller, but it contains no local `Force Charge` writer or
automatic battery free-charge state machine.

The Tessie planner's initial settling branch assumes FoxESS battery charging has
already been established and allocates the EV around measured whole-site
current. That is an input condition, not authority for HEO to create a new
inverter controller.

The separate legacy HEO package did contain an automatic Modbus free-charge
automation. It was created after the canonical source snapshot and is not a
source port. Version 0.4.0 removed it because its tests did not demonstrate
pilot-site provenance or safe post-charge reconciliation.

## Supported operating model

- **FoxCloud Scheduler ownership:** FoxCloud owns battery work mode for the
  whole day. The independently gated HEO EV controller may still allocate
  Tessie current during the free window because it writes no FoxESS entity.
- **Local Modbus ownership:** HEO may run its verified ZEROHERO export, the
  separately identified default-off free-window battery-charge extension, and
  explicitly submitted diagnostic paths. Solar-spill and pre-free EV stages
  may use their local-Modbus evidence.
- **Observer ownership:** HEO writes neither FoxESS nor Tessie unless the
  independent EV controller is separately commissioned and enabled.

HEO never treats an uncovered cloud schedule period as permission for local
Modbus writes. Ownership is transport-wide, not merely active-window-wide.

## Implemented extension boundary

The explicitly requested local-Modbus automatic battery-charge controller is
new functionality, not completion of the source port. It is configuration-
driven, default-off, mutually exclusive with FoxCloud ownership, and reuses the
mapped FoxESS Modbus entities rather than model-specific register code. Its
bounded behavior and provenance are documented in
[`local-modbus-free-charge.md`](local-modbus-free-charge.md).

It cannot identify or suppress unrelated Home Assistant or cloud writers.
Durable service-call and direct-register tracing remains required before any
site with unresolved competing-writer evidence is commissioned for active use.
