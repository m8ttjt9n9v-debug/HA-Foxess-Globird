# Commissioning

The integration starts with Observer ownership, automatic controls off, and
Safety Lock on. Its status entity reports the configured owner, each control
gate, and the most recent guarded action.

Confirm these values over at least seven complete tariff cycles before considering a future actuation release:

- battery energy and the energy remaining after the configured floor and reserve;
- grid import/export direction against the inverter or retailer view;
- configured EV maximum power, if an EV current ceiling has been supplied; and
- diagnostics that show expected availability without personal entity IDs.

Before enabling any automatic path, exercise or observe known import/export,
battery charge/discharge, and daylight generation states. Set each explicit
direction, confirm the canonical signed sensors, and only then select **I have
verified these sign conventions**. A source or direction change clears the
confirmation automatically. See [telemetry normalization](telemetry-normalization.md).

Before commissioning FoxESS actuation, choose one owner for the entire day.
Local Modbus requires FoxCloud Mode Scheduler and all legacy inverter writers
to be disabled. Validate mapped mode and power feedback, then use only the
bounded Diagnostics tests. Automatic battery charging remains default-off;
verify that its target is above current SoC before rehearsal, confirm its
displayed bounded power and 24-hour window, then test one supervised window.
Place the inverter in Self Use first; HEO will not adopt an unlatched forced or
different base mode. Confirm Force Charge feedback after the start and Self Use plus zero force
targets after the end. Diagnostics cannot start while an automatic charge or
export session remains latched. ZEROHERO selling likewise remains default-off; enable it
only after its feedback and rollback paths are recorded. The
[ZEROHERO export policy](zerohero-export-policy.md) defines the ported selling
algorithm and its persisted recovery behavior; the
[Local Modbus charge policy](local-modbus-free-charge.md) defines the separate
charge extension.

In the FoxESS Modbus integration itself, verify **Export Power Limit**, **Force
Charge Power**, **Force Discharge Power**, and **Import Power Limit** against the
commissioned site before testing. Do not interpret a successful work-mode
selection as proof of non-zero power: confirm direct battery and grid telemetry.
HEO may legitimately leave both force-power setpoints at zero after restoring
Self Use, but it does not change the native import/export power-limit entities.

Direct-EVSE commissioning is independent of FoxESS ownership. First leave
Automatic EV Control off and Safety Lock on, then verify mapped SoC, stored
energy, at-home evidence, cable state, charging state, actual current, writable
current range, writable charge-limit range, and charge switch. Confirm the
configured physical connector rating and service limit. A multiphase site also
requires a signed most-loaded-phase current sensor in amperes; aggregate site
power is not accepted. After rehearsal, disable competing Tesla writers before
unlocking and enabling this path. A latched maximum-attempt fault is evidence
to investigate, not permission to toggle the gate repeatedly.

Before selecting EV location policy **Auto**, verify Home Assistant's Home
location under Settings → System → General. The mapped Tessie device tracker is
classified against that Home zone; a default or incorrect Home location will
correctly report the vehicle as `not_home` and block every home-current write.
Use the explicit **Home** override only when the operator intentionally wants to
bypass zone classification for a known home connector. It does not bypass the
cable or charging-state gates.

For daily ready-by backfill, configure wall-side kWh, a ready time before the
free-power window, an outside-window percentage of commissioned inverter
output, and any desired planning buffer. Start with Safety Lock on and verify
the displayed planned energy, whole-amp current, latest start, protected house
energy, allocation shortfall, and service headroom. Zero kWh disables the
policy. FoxCloud ownership is permitted because this path writes Tessie only,
but it cannot guarantee the allocation survived earlier cloud-controlled
export; only Local Modbus ZEROHERO can reserve it prospectively.

Treat Charge to Full as a paid-import override. Confirm its configured timeout
and service/connector limits before use; it may start charging immediately
outside free power and clears when full, disconnected after starting, or timed
out.
