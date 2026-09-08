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
- **Local Modbus ownership:** HEO may run only its verified ZEROHERO export and
  explicitly submitted diagnostic paths. Solar-spill and pre-free EV stages
  may use their local-Modbus evidence. Automatic free-window battery charging
  remains absent.
- **Observer ownership:** HEO writes neither FoxESS nor Tessie unless the
  independent EV controller is separately commissioned and enabled.

HEO never treats an uncovered cloud schedule period as permission for local
Modbus writes. Ownership is transport-wide, not merely active-window-wide.

## Future extension rule

A local-Modbus automatic battery-charge controller would be new functionality,
not completion of the source port. It may be designed only as an explicitly
requested, separately named extension after model-specific schedule behavior,
work-mode restoration, direct-register feedback, competing-writer detection,
restart recovery, and service-call tracing are proven. It must remain
configuration-driven, default-off, and mutually exclusive with FoxCloud
ownership.
