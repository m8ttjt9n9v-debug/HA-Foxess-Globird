# Work item: bind cloud solar to its selected native publication

## Evidence and contract

The native Solis 4.0.x API reuses one `_data` cache while fetching each inverter
on an account. Its `InverterService` publishes each complete `GinlongData`
synchronously before moving to the next fetch. Reading the shared cache later
can correctly reject the serial but lose the selected inverter's valid data.
The old serial rejection is necessary; removing it would accept another system.

## Source mapping

| Existing native fact | HEO boundary |
| --- | --- |
| Explicit AC-power entity, native entry/device/serial | Same existing binding checks |
| Complete selected-inverter serial publication | One lifecycle-owned read-only subscriber |
| Current postprocessed native frame during that dispatch | Immutable copy of the five required fields only |
| Actual provider measurement timestamp | Existing independent age/coherence checks |
| Native account cache subsequently overwritten | Cannot alter or renew the selected observation |

The existing binding checks are shared mechanically between observer setup and
capture, not replaced by discovery. The capture caller must supply its bound
frame explicitly: there is no implicit account-cache fallback. Default mapped
sensor/balance modes do not create an observer. There is no provider request,
poller, timer, actuator, new entity, setting or stored payload.

## Invariants and lifecycle

Another inverter cannot replace or freshen this frame. An invalid/partial
selected publication withdraws the old frame. A failed fetch without any new
publication leaves only the original observation until its existing deadline;
the poll clock, other frames and HA attributes cannot renew it. Offline display
zero cannot replace retained nonzero measured power. Invalid/future timestamps,
units, values or provider identity fail closed. Canonical EV solar and local
grid/battery retain fast bounds; only the explicit house profile has 600 seconds.

Observer setup is idempotent. Reconfiguration, provider/API replacement and
unload remove only that observer and discard the old frame. Old callbacks cannot
poison a replacement. Unsupported publishers cannot seed a guessed frame.
Startup may wait for the next actual selected publication. There is no new
controller policy, persistence schema or reserve/energy-budget change.

## Verification and rollback

Synthetic regressions cover shared-cache replacement, missing/malformed fields,
zero/clipped output, unchanged measurement age, immutability, offline display,
multiple owners, source disable/unload, provider replacement and partial setup
failure. A private offline rehearsal executes the installed native data/publisher
methods unchanged to verify dispatch order, selected frame retention and offline
zero behaviour; private identities/source evidence remain outside this repo.
Full versioned tests/rehearsals and controlled published-asset acceptance remain
required. Reverting to v49 reads unchanged storage but may again reject the
multi-inverter source; no unsafe fallback or positive control is implied.
