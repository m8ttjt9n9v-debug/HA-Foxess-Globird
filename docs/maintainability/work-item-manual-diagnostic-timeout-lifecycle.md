# Work item: manual diagnostic timeout lifecycle trace

## Problem and evidence

Manual diagnostic restoration had focused controller coverage and a lifecycle
restart fixture, but no system case retained the complete successful
start → timer expiry → Self Use → zero target → confirmed idle sequence. The
incident catalogue therefore classified wrong-mode restoration as focused
only.

## Frozen contract

- A discharge diagnostic starts by setting discharge power, then selecting
  Force Discharge.
- Timer expiry selects Self Use, then clears the discharge target.
- Restoration remains persistently `stopping` until external feedback confirms
  Self Use and a zero target.
- Confirmation clears the obligation without another hardware call.
- Service payloads, order, delay, retry limit, Store payload and public status
  are unchanged.

## Implementation

One Home Assistant lifecycle fixture now sets up a real config entry, starts a
manual discharge through the runtime controller, invokes the timer callback,
supplies confirmed actuator feedback and inspects ordered service calls plus
the private Store after each phase.

No production code changes.

## Compatibility and rollback

This is characterization only. Revert the test, catalogue row and this record
to restore the preceding suite without changing runtime behaviour or data.

## Acceptance evidence

- Exact two-call start and two-call timeout restoration traces pass.
- Running, stopping and idle Store checkpoints pass.
- Final confirmation emits zero service calls.
- Full suite, frozen contracts, previous-release round trip and Ruff pass.

## Completion record

- [x] Existing behaviour characterized
- [x] System lifecycle fixture complete
- [x] Incident catalogue updated
- [ ] Independent review complete
