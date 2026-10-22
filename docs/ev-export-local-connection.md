# Local charger evidence at EV/export handover

The EV-before-export minimum remains the original value-based policy. A
sleeping vehicle can retain old GPS/charge measurements; a new cache fetch is
not proof that those measurements are current. The protected export handover
must not confuse that situation with an EV still consuming surplus locally.

## Authority and provenance

| Existing behavior | Retained | Correction |
| --- | --- | --- |
| Reference minimum gate in ZEROHERO EV-before-export | Opt-in, configured minimum, invalid SoC rejection | Local unplug proof does not change the minimum |
| Persisted buffered recovery | Only measured vehicle completion clears the pending target | Local proof never completes, erases or rebinds it |
| EV/export physical handover | No overlapping HEO surplus writers; pending stops retained | Independently commissioned local unplug evidence may prove no local EV draw |
| Native vehicle source clocks | Exact vehicle/field/value and actual measurement age | Use the same qualified cohort for physical handover and contradictions |
| Existing export state machine | One writer, fixed power and reducing cleanup | Authority withdrawal precedes acceptance of a starting export |

This optional source extension is not claimed as reference-algorithm parity.
It adds no energy allocation, active writer, API reader, polling timer or store.

## Commissioning and freshness

Select `ev_local_connection_entity` in **EV charger**, only for the explicitly
identified direct local charger. Leave it blank for another supply/path. An
ordinary binary sensor must publish its own non-restored, valid report within
the existing telemetry freshness bound. `off` means no vehicle connected.

For the supported native Tesla Wall Connector integration, a lifecycle-owned
read-only subscriber captures the exact selected device's new vitals payload.
Vehicle-connected and contactor-closed must both be boolean false. The native
entry, serial, device, unique field and existing provider must agree. Another
sensor changing cannot freshen the payload; repeated callback/cache identity
cannot renew it. The observer never becomes the first polling listener.
Expired, malformed, failed, unloaded, changed or conflicting evidence discards
the proof. Current positive native connection/contactor evidence vetoes an old
unplugged entity. After startup or rebinding, wait for a new genuine publication.

Unavailable local proof falls back to existing qualified vehicle feedback.
An unplugged charger is not proof of EV SoC, nor is it an acknowledgement that
an earlier charge-stop command succeeded. Pending stops/recovery remain pending.
Retained valid non-future SoC still must satisfy the original minimum. Actual
buffer completion continues to need the original qualified vehicle measurement.
Stop acknowledgement uses the four measured physical fields, independently of
SoC, GPS, requested amps or charge-limit availability. An optimistic switch
acknowledgement, old native frame or live charging contradiction cannot clear it.

Reconfiguration applies only explicitly changed keys to the saved entry. This
keeps sparse/legacy configurations and unrelated option values intact instead
of materialising normalized policy defaults when commissioning this mapping.

## Lifecycle and stability

The regression suite runs real HEO setup/reload, stores and both controllers:
charge below minimum, cross the minimum, reach the buffer, confirm stop, unplug,
leave, sleep, then ordinary or price-triggered export with vehicle clocks still
old and only local electrical/charger evidence advancing. It also covers pending
recovery across restart, return/reconnect in either callback order, conflicting
and out-of-order readings, source changes/failure, Safety Lock, paid cap,
price expiry and command-boundary loss of authority.

No extra delay or hysteresis is added to a physical connection. Positive
connection/conflict must withdraw the unplug shortcut immediately at evaluation;
the existing configurable SoC buffer remains the sole top-up hysteresis.
Fallback does not carry local permission through an outage. No deployed layout,
saved policy or charger mapping is changed automatically by HACS installation.
Rollback ignores the optional mapping and restores the previous strict handover;
retain a deployment backup. Repository and startup checks are not physical
critical-event export or retailer-payment proof.

## Connected stopped-car correction — v0.12.61

The disconnected-only fallback did not cover a car that remains plugged in and
sleeps after its measured stop. The native observer now independently qualifies
**connected and contactor open** from the same newly published vitals frame.
This uses the existing telemetry age bound, not a new delay or grace period.
Raw off-state charger current is not a reliable substitute for contactor state.
Generic binary sensors cannot supply this stronger proof.

The handover also requires the exact mapped vehicle's loaded native publisher
and a valid, coherent retained charge-state frame: connected, stopped/complete/
no-power, charge switch off, actual current zero, matching SoC/current/limit
fields, valid units and a non-future measurement timestamp. Online or asleep is
allowed only for this retained stopped-frame check. It is explicitly NOT a fresh
vehicle cohort and is never used by EV command or stop-acknowledgement checks.
An observed disconnect/reconnect requires a vehicle frame from the new connection;
the old stopped frame cannot follow a car through a trip. Restart/rebinding
discards all local proof and awaits a genuine new local publication; restored
vehicle placeholders still cannot qualify. No persistent schema is added.

The existing minimum remains value-based. Pending buffered recovery, unconfirmed
stop and corrupt recovery remain blocking; this independent physical proof cannot
complete them. Source failure, expiry, affirmative charging/closed-contactor
evidence or changed authority immediately withdraws the shortcut, including
between staged export commands. Existing qualified live vehicle feedback remains
the fallback. No SoC hysteresis boundary or top-up policy changes here.

Joint lifecycle regressions cover both controller orders and one/three phases,
top-up through the buffer, measured stop, continued connection/sleep, repeated
publications/export, real unload/setup, reconnect and command-boundary authority
loss. The preceding disconnected/away, stop-duty and price-expiry suites remain.
No site settings, dashboard layout, charger mapping or minimum changes are implied.
