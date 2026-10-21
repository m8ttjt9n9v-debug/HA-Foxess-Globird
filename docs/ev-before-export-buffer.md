# EV-before-export top-up buffer

Version: v0.12.58 correction; no live installation or policy activation is implied
by this document. Concurrent EV charging and forced export remains a separate,
unimplemented design.

The saved EV-before-export minimum remains the level below which export is
withheld. A top-up that begins below that minimum now continues to the minimum
plus a configurable buffer before handing back to export. For example, a 40%
minimum and a one-percentage-point buffer recover to 41%; a later 40% reading
still permits export, but below 40% starts a new recovery. A car initially at
40% does not acquire a new 41% requirement without a preceding below-minimum
top-up. Simply increasing the minimum would move, rather than remove, the edge.

## Existing authority and small extension

| Existing source/behavior | Retained authority | Correction |
| --- | --- | --- |
| Reference ZEROHERO EV gate, as recorded in `zerohero-export-policy.md` | Explicit opt-in, saved minimum, invalid-SoC rejection | Default remains the same gate outside a pending recovery |
| Existing Sellable-funded EV-before-export stage | Same energy ledger, current planner, reserve, power cap and EV writer | Use the buffered target only for a recovery begun below the minimum |
| Existing export policy and physical baseline handoff | Same inverter owner, cleanup, windows, daily cap and net metering | Keep export withheld in the recovery band; do not overlap writers |
| Existing EV controller journal and typed codec | Same Store/version, accounting, retries and stop duties | Add one optional bound recovery record, checkpointed before positive intent |
| Existing native configuration controls | Saved configuration-entry values and registered entity identities | Add one number; wizard and dashboard edit that same saved setting |

The buffer is configuration-driven extension behavior, not claimed reference
parity. Zero exactly preserves the former single-threshold gate. The default is
one percentage point, configurable from 0 to 100 whole percentage points in EV
Charging policies and `number.home_energy_ev_before_export_soc_buffer`.
Installing a new entity does not edit an existing deployed Lovelace dashboard.
The reusable dashboard example includes the control beside the minimum.

Normal EV SoC limits cap the additional buffer. A minimum above the normal EV
ceiling still cannot invoke Full or be lowered silently; its existing export
hold remains. Lack of Sellable, reserve/current limits, source loss or another
owner can stop charging early. A pending recovery does not create energy or
permission to buy paid power. Free-window, Trip/Full and smart-socket behavior
keep their prior authority. Smart sockets do not gain this direct-EVSE top-up.

## Lifecycle

- Fresh, qualified vehicle evidence below the minimum arms a recovery only
  while the vehicle is home and connected. It is saved before positive EV
  commands. No recovery is inferred from optimistic command acknowledgements.
- Pending intent survives restart, disconnection, a temporary energy hold and
  free/Full pre-emption. Reconnection resumes only under the ordinary gates.
- Current buffer edits adjust the pending release boundary; setting zero
  restores the original behavior. Minimum or mapped-vehicle/actuator changes
  invalidate the old binding and require a new current decision.
- A fresh reading at the release boundary completes the recovery. The existing
  physical stop/baseline handoff still precedes an export start. Completion is
  not visible as export permission while its checkpoint is still in progress;
  cancellation retains the prior pending recovery.
- A failed checkpoint restores the previous record and blocks export release
  and positive top-up writes until a successful retry. A corrupt recovery
  record cannot silently grant authority in the band. A qualified new reading
  below the minimum can establish a new recovery; reaching the release boundary
  or explicit policy disable/zero buffer can resolve the uncertainty.

`ev_buffer_topup` explains an export hold inside the band. The saved minimum
does not change, no second controller/poller/helper is added, and repository
tests do not establish live-site acceptance or retailer payment.

Previous releases ignore the optional buffer setting and recovery field while
retaining their existing accounting and stop duties. Rollback therefore restores
the former single-threshold policy, not buffering; a deployment backup remains
necessary. Ordinary same-version restart retains pending recovery.
