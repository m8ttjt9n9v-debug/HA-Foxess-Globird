# ZEROHERO surplus export policy

This is the durable specification for the selling automation ported from the
successful Mangerton Home Assistant configuration. HEO does not reinterpret
the policy as a continuously modulated export controller.

## Ownership and authorization

Automatic export requires all four conditions:

1. FoxESS owner is **Local Modbus**.
2. HEO automatic FoxESS control is enabled.
3. Automatic ZEROHERO Export is enabled.
4. Safety Lock is off.

Observer and FoxCloud ownership block every HEO Modbus export write for the
whole day. The export toggle cannot bypass ownership or Safety Lock. A mapped
work-mode selector must advertise both `Force Discharge` and `Self Use`, and
the mapped power entities must have valid local feedback. Cloud telemetry never
authorizes this controller.

## Mangerton-equivalent energy plan

The calculation is:

`AC battery after floor/reserve × discharge efficiency`

minus:

- the learned or fallback house-energy requirement until the next free window;
- only a configured, physically unavoidable EV baseline while the car is
  confirmed home and connected.

It deliberately does not reserve an optional EV charge-limit gap. The planned
sale is the minimum of that sellable energy, the remaining daily boosted-export
allowance, and what the fixed discharge power can deliver between the export
window start and configured Force Discharge finish.

Power is fixed for the session. Energy changes duration, and the latest start
is `finish - duration`, bounded no earlier than the export-window start. The
defaults are 18:00, 10 kW, 15 kWh, 95% efficiency, and a 21:01 finish. The
21:01 boundary is deliberate: restoration occurs after the 18:00–21:00 tariff
assessment window.

## Session and recovery behavior

The start remains fluid until it becomes due. HEO then persists a latch and:

1. sets the bounded Force Discharge power;
2. waits five seconds;
3. selects `Force Discharge` if local ownership and feedback remain valid.

Ordinary SoC, reserve, forecast, or allowance changes do not cancel or resize a
latched session. At disable or finish, HEO selects `Self Use`, waits five
seconds, and clears the discharge target. If Modbus disappears, the latch is
retained and restoration or continuation is reconciled only after local
feedback returns.

Command retries are finite. After three failed attempts the controller holds
without further writes, preventing a second writer from producing indefinite
mode flapping. Late matching feedback is still accepted. A genuine Modbus
loss/return re-enters the persisted recovery path.

The daily boosted-window export accumulator and session latch are stored in
Home Assistant storage. A restart therefore cannot erase used allowance or a
pending Self Use restoration.
