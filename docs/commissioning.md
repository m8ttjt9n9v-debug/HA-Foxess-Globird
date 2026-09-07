# Commissioning

The integration starts with Observer ownership, automatic controls off, and
Safety Lock on. Its status entity reports the configured owner, each control
gate, and the most recent guarded action.

Confirm these values over at least seven complete tariff cycles before considering a future actuation release:

- battery energy and the energy remaining after the configured floor and reserve;
- grid import/export direction against the inverter or retailer view;
- configured EV maximum power, if an EV current ceiling has been supplied; and
- diagnostics that show expected availability without personal entity IDs.

Before commissioning FoxESS actuation, choose one owner for the entire day.
Local Modbus requires FoxCloud Mode Scheduler and all legacy inverter writers
to be disabled. Validate mapped mode and power feedback, then use only the
bounded Diagnostics tests. Automatic battery charging is not implemented.
ZEROHERO selling remains default-off; enable it only after its feedback and
rollback paths are recorded. The
[ZEROHERO export policy](zerohero-export-policy.md) defines the ported selling
algorithm and its persisted recovery behavior.

Direct-EVSE commissioning is independent of FoxESS ownership. First leave
Automatic EV Control off and Safety Lock on, then verify mapped SoC, stored
energy, at-home evidence, cable state, charging state, actual current, writable
current range, writable charge-limit range, and charge switch. Confirm the
configured physical connector rating and service limit. A multiphase site also
requires a signed most-loaded-phase current sensor in amperes; aggregate site
power is not accepted. After rehearsal, disable competing Tesla writers before
unlocking and enabling this path. A latched maximum-attempt fault is evidence
to investigate, not permission to toggle the gate repeatedly.
