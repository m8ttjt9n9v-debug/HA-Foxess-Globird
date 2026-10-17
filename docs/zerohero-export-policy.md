# ZEROHERO surplus export policy

This is the durable specification for the selling automation ported from the
successful Working Single Phase Pilot Site Home Assistant configuration. HEO does not reinterpret
the policy as a continuously modulated export controller.

## Provenance map

The canonical source is the Working Single Phase Pilot Site `configuration_v1.4.24.yaml` at commit
`5806b4a5313331fbc421108e9e0c98e661ca20fe`.

| Working Single Phase Pilot Site source | Preserved HEO behavior |
| --- | --- |
| Lines 1008–1079 | enable/latch, allowance, fixed power, efficiency, export window, and finish inputs |
| Lines 3654–3705 | protected house-energy forecast until the next free window |
| Lines 3910–4250 | connected-EV mandatory baseline and energy protection |
| Lines 4431–4648 | sellable energy, bounded plan, duration, and latest start |
| Lines 7139–7375 | fluid pre-start plan, latched session, ordered Force Discharge command, finish, and Self Use recovery |

HEO's pure equivalents are `planner/export.py` and
`planner/export_session.py`; `active.py` supplies explicit entity mappings,
ownership gates, persisted state, and bounded service calls. Site topology and
limits enter through configuration rather than changing the policy equations.

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

An independent, default-off **Prioritise EV Before Export** gate may further
withhold that permission. It does not change the saved automatic-export switch.
When enabled, EV SoC below the configured target prevents a new export and is
an explicit finish request for a latched HEO-owned export; reaching the target
returns control to the unchanged export policy. Missing or invalid EV SoC
fails closed. This is a separately identified extension, not canonical pilot
parity.

## Pilot-site-equivalent energy plan

The calculation is:

`AC battery after floor/reserve × discharge efficiency`

minus:

- the learned or fallback house-energy requirement until the next free window;
- only a configured, physically unavoidable EV baseline while the car is
  confirmed home and connected.

It deliberately does not reserve an optional EV charge-limit gap. The planned
sale is the minimum of that sellable energy and the remaining independent daily
automatic-export allowance.

HEO requests the lesser of the commissioned inverter discharge maximum and the
mapped actuator's advertised maximum. Energy changes duration, and the latest
start is `finish - duration`, bounded no earlier than the export-window start.
The finish is derived from the ZEROHERO window end plus a configurable offset,
defaulting to one minute. The inverter's own regulated grid-export limit remains
the hardware authority and deliberately does not reduce this battery-side
request: preserving maximum discharge headroom helps cover simultaneous house
load without importing during the ZEROHERO assessment window.

## Session and recovery behavior

The start remains fluid until it becomes due. HEO then persists a latch and:

1. sets the bounded Force Discharge power;
2. waits five seconds;
3. selects `Force Discharge` if local ownership and feedback remain valid.

Ordinary battery SoC, reserve, forecast, or allowance changes do not cancel or
resize a latched session. The opt-in EV-before-export gate is the sole added
telemetry-driven finish condition. At disable, EV-priority withholding, or
finish, HEO selects `Self Use`, waits five seconds, and clears the discharge
target. If Modbus disappears, the latch is retained and restoration or
continuation is reconciled only after local feedback returns.

Command retries are finite. After three failed attempts the controller holds
without further writes, preventing a second writer from producing indefinite
mode flapping. Late matching feedback is still accepted. A genuine Modbus
loss/return re-enters the persisted recovery path.

The daily boosted-window export accumulator and session latch are stored in
Home Assistant storage. A restart therefore cannot erase used allowance or a
pending Self Use restoration.

### Feed-in First fallback recovery

FoxESS Modbus exposes Force Discharge as a remote-control overlay. Its
underlying base-mode fallback is Feed-in First; after integration or Home
Assistant restart the overlay may be absent even though HEO has retained its
unfinished export request. Treating that fallback as an unrelated forced owner
would prevent the session's existing recovery logic from ever running.

HEO therefore recognises Feed-in First only when the export journal is valid,
its phase is unfinished (`starting`, `active`, `stopping`, or `recovering`),
there is no conflicting unfinished charge session, and no diagnostic is active.
An idle, missing or invalid export journal grants no ownership of that mode.
An unrelated Force Charge remains external; this exception is not permission
to override arbitrary modes or to adopt a VPP/cloud event.

The existing owner/master/Safety-Lock/sign/mapping/manual gates still run first.
The same export state machine then maintains the retained bounded power while
permitted, or selects Self Use and clears the target when disabled or finished.
Retry spacing and persistence remain unchanged. Ordinary ZEROHERO retains its
fixed-session policy; price-owned export still requires current protected
energy, its original actuator bindings and non-extendable price deadline. No
new grace timer, polling loop, journal field or recovery writer is added.

| Source decision | Preserved implementation |
| --- | --- |
| Canonical `zerohero_surplus_export_controller_v1` startup trigger and latched maintenance branch | An unfinished export can reassert Force Discharge after local feedback returns, retaining its fixed-power request |
| Canonical disabled/outside-window branch and retained latch | Existing Self Use/zero-target cleanup, including recovery after the window has ended |
| FoxESS Modbus remote-control fallback | Narrow ownership classification in `planner/foxess_ownership.py`, not a second controller or native register implementation |
| Existing external-owner boundary | No Feed-in First adoption without a valid unfinished export journal; charge/diagnostic conflicts and write gates remain blocking |

Regression coverage uses pure ownership cases plus actual Home Assistant setup,
storage reconstruction, repeated reload, unavailable mode feedback and periodic
reconciliation with a fake physical actuator. It covers single-/three-phase
configuration, fixed-power retention, window-end/disable/EV-priority cleanup,
manual Stop, missing ownership and absolute gates. Separate price regressions
retain deadline/mapping authority and only clean up when permission is lost.
Repository tests are not live physical-export or competing-writer verification.

## EV-before-export first-stage provenance

This requested policy does not exist in the canonical configuration and is
therefore recorded as an extension around, rather than a rewrite of, ZEROHERO.

| Input or decision | HEO equivalent |
| --- | --- |
| Operator opt-in | `switch.home_energy_ev_before_export` |
| User target | `number.home_energy_ev_before_export_soc_target` |
| Current mapped EV SoC | canonical `sensor.home_energy_ev_soc` snapshot |
| `EV SoC < target` | pure `planner/ev_before_export.py` decision |
| New export | effective enable is false; the session remains idle |
| Active HEO export | existing bounded stop path restores Self Use |
| Target reached | original export eligibility and session policy resume |
| Missing/invalid SoC | export is withheld while the opt-in remains enabled |

The gate sends no Tessie command and allocates no energy itself. More advanced
home/connected qualification, charging activation, source selection, energy
accounting, and hysteresis remain separate future work.
