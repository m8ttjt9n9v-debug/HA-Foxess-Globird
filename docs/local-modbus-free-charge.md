# Local Modbus free-window battery charging

## Classification and provenance

This controller is a separately named, default-off extension requested after
the Working Single Phase Pilot Site port. The canonical v1.4.24 YAML does not
contain a local automatic `Force Charge` writer; battery charging was already
established externally. This feature must therefore never be described as
pilot parity.

The extension reuses the verified ZEROHERO control boundary rather than
introducing a second FoxESS implementation:

| Required behaviour | Existing authority reused by this extension |
| --- | --- |
| Explicit inverter owner | `foxess_control_owner`; only `local_modbus` permits writes |
| Global write intent | `automatic_control_enabled` master gate |
| Independent opt-in | Integration-owned Automatic Battery Free Charge switch, default off |
| Absolute no-write interlock | Safety Lock / `rehearsal_mode` |
| Commissioned actuators | Mapped FoxESS Modbus work-mode and force-power entities |
| Supported capability | Live work-mode options must advertise `Self Use` and `Force Charge` |
| Local schedule | Configured 24-hour free-window start and end, including overnight windows |
| Charge power | Configured inverter charge limit, bounded again by the mapped entity maximum |
| Start qualification | Fresh normalized battery SoC below the configured free-window target |
| Stable session | A persistent latch holds the originally requested power for the window |
| Command order | Clear discharge target, set charge target, wait, then select `Force Charge` |
| Feedback and retry | Direct mapped mode/power feedback, 30-second reconciliation, at most three attempts |
| End behavior | Select `Self Use`, wait, then clear both force-power targets |
| Restart recovery | Persist phase, requested power, attempts, and last-command timestamp |
| Competing control | FoxCloud ownership blocks the controller for the entire day |

The upstream FoxESS Modbus controls must also be commissioned. Verify its
Export Power Limit, Force Charge Power, Force Discharge Power, and Import Power
Limit values before enabling HEO. HEO sets the two force-power targets required
for an HEO-owned session and returns them to zero after Self Use restoration; it
does not configure the inverter's import or export power-limit entities.

## Deliberate schedule semantics

The window is half-open: start is included and end is excluded. Home
Assistant's time selector uses 24-hour values, so `12:01:00` means noon and
`00:01:00` means one minute after midnight.

Battery SoC qualifies only the start of a session. Once HEO has started a
session, it remains latched until the configured end or the operator disables
the independent charge request. This avoids mode flapping around the target
and matches the requested fixed schedule. The inverter/BMS remains responsible
for tapering or refusing battery current at its physical limit.

HEO restores only a session recorded as its own. Discovering an unlatched
forced or different base mode does not authorize HEO to adopt or overwrite
another writer: a new automatic session starts only from observed `Self Use`.
Explicit diagnostics are blocked while an HEO automatic charge or export
session is latched; disable that independent automation and confirm its session
is idle before submitting a diagnostic.
Transient loss of battery SoC does not end an already latched session, but loss
of actuator feedback moves the persisted session into recovery. When feedback
returns, HEO resumes only while the same configured window is still active;
otherwise it deliberately restores `Self Use`.

Automatic battery charging cannot be enabled until setup or Reconfigure shows
the saved start and end in 24-hour notation, its duration, and a 24-hour
timeline and the operator confirms them. A schedule whose end is earlier than
its start is interpreted as crossing midnight and requires a second explicit
acknowledgement. Electricity-provider windows can vary by account signup date;
HEO does not infer a tariff cohort from the provider name.

## Exclusions

- This does not read or write FoxESS native schedule-period registers.
- It does not permit FoxCloud and local Modbus to share different parts of the
  day; FoxCloud's remaining-time mode is still whole-day ownership.
- It does not dynamically pace battery power against the daily free-energy
  allowance. The existing EV allowance planner may allocate the remaining
  headroom, while this controller requests the commissioned fixed battery
  charge power.
- Safety Lock prevents restoration writes as well as start writes. Before
  deliberately locking or unloading an active controller, use the independent
  charge switch to request its bounded Self Use restoration.

## Rollback

Turn off Automatic Battery Free Charge and confirm the session reaches `idle`
with mapped feedback showing `Self Use`. If feedback is unavailable, restore
the inverter with the FoxESS Modbus integration's native controls before
changing ownership or disabling its connection. Leaving the feature off keeps
all pre-extension behavior unchanged.
