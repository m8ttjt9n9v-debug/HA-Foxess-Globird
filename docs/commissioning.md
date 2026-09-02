# Commissioning (0.2 observer release)

The controller starts and remains in **observe** mode. Its status entity reports `observer_only` when the required battery input is valid, or a reason such as `missing_battery_soc` when it is not.

Confirm these values over at least seven complete tariff cycles before considering a future actuation release:

- battery energy and the energy remaining after the configured floor and reserve;
- grid import/export direction against the inverter or retailer view;
- configured EV maximum power, if an EV current ceiling has been supplied; and
- the learned house-energy budget, sample count, and warm-up status when a
  whole-house sensor is mapped; and
- diagnostics that show expected availability without personal entity IDs.

Do not disable the existing YAML controller, modify actuator ownership, or rely on this release for physical control. Actuation will be introduced only in a later separately commissioned release.
