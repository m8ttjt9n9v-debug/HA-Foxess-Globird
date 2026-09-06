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
bounded Diagnostics tests. Automatic charging and ZEROHERO selling remain
separate default-off behaviors; enable them one at a time only after their
feedback and rollback paths are recorded. The
[ZEROHERO export policy](zerohero-export-policy.md) defines the ported selling
algorithm and its persisted recovery behavior.
