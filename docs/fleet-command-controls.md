# Fleet manual export and Self Use controls

The optional [command package](../examples/fleet-command-package.yaml) adds one
hub dispatcher for a local HEO installation and two explicitly configured
remote installations. The [Fleet dashboard](../examples/fleet-dashboard.yaml)
places **Export all at maximum** and **Stop all · Self Use** above three site
cards. Both primary buttons dispatch with a single click and have no per-tap
confirmation popup; the separate Resume utility retains confirmation. HACS
installs neither this package nor this dashboard automatically.

Export requests the smaller of each site's commissioned inverter discharge
maximum and the mapped native actuator maximum, rounded down to its supported
step. It continues until Stop, subject to the inverter's own protections; it
does not reserve the normal house/EV energy budget. Stop clears both forced
power targets and requests Self Use. Both actions leave HEO inverter automation
under a persistent manual hold. **Resume automatic control** is a separate
utility which releases that hold and lets existing enabled policies resume.
These controls use HEO's manual services, never raw FoxESS or EV service calls.

New or reasserted positive export commands require valid SoC above the
configured battery floor and fresh canonical battery-power evidence. Those are
command-admission gates, not a new software cutoff for an already accepted
indefinite export. The inverter/BMS remains responsible for its own physical
floor and protections. Do not expect the normal automatic-export reserve to
limit this deliberate manual action.

Disable VPP/cloud scheduling and every other competing inverter writer on each
target before confirming **Competing inverter writers disabled on every Fleet
site**. This default-off hub acknowledgement resets on hub startup and gates
Export and Resume. Stop still dispatches without that acknowledgement; each
node continues to enforce its own owner/master/Safety-Lock and storage gates.
The acknowledgement records an operator assertion, not a discovery of external
writers or a command that disables the VPP. HEO can suppress only its own
inverter controllers. EV control remains subject to its ordinary policy.

## Transport and installation

Install a tested HEO build exposing `manual_export_max`, `manual_self_use`, and
`manual_resume_automatic` with optional service responses on every target
before installing the hub controls. All targets must be commissioned for
exclusive Local Modbus ownership. The hub's local branch calls HEO directly;
the two remote branches use Home Assistant's standard authenticated service
API with `?return_response`.

Copy the package into the hub's existing packages configuration. Replace its
two fixed `.invalid` origins with the trusted origins already used by that
hub's Fleet monitoring, and point each `!secret` at its existing corresponding
Authorization secret. Each secret value is the complete `Bearer …` header.
Keep origins, secret values, account details and any site-specific config-entry
IDs in the private hub configuration. Never add bearer tokens to a Lovelace
card or browser JavaScript. Do not publish REST debug logs containing headers.
The transport allows only these three HEO service names at its fixed origins.

For a target with one HEO entry, leave its entry mapping empty. With multiple
entries, supply that site's explicit config-entry ID: `entry_ids` in
`build_package()` sets the local/remote payload mappings without guessing an
entry. `remote_origins` and `authorization_secrets` likewise let a private
installer reuse already verified Fleet endpoints and secret references. The
default generated examples contain only reusable placeholders.

A first installation of `rest_command` ordinarily needs a controlled hub
restart; a missing `rest_command.reload` cannot load that new domain. If it is
already loaded, use its normal reload together with the affected helper/script
reloads. Native storage-dashboard edits need no HEO reload. Back up the affected
package/dashboard and verify the configuration before an approved restart or
reload. End existing manual exports and confirm the task-specific safe state
before restarting the hub. Installing or reloading the package sends no device
command, and there are no startup/time-triggered Export requests.

For an existing sections dashboard, prepend the object returned by
`build_controls_section()` to its existing `sections` array. Its three-column
span makes the two primary buttons appear above the three site cards. Preserve
the site's existing cards and mappings. The generated dashboard shows this
sanitised structure with generic monitoring entities.

## Requests and results

Each button starts the same dispatcher in `restart` mode. It creates one
unique `request_id` and one aware ISO-8601 `issued_at` shared by all three
parallel branches. A new Stop cancels the preceding hub script, but an HTTP
request already accepted by a remote Home Assistant can keep running after
the connection closes. Each node's persisted request ordering and generation
checks therefore make a newer Stop supersede an older in-flight Export at the
device command boundaries. Cancellation at the hub alone is not a device stop.

Every branch sends at most one request. A timeout or HTTP error is recorded
locally without retrying Export or aborting the other sites. A Stop should be
sent deliberately if needed; check any unknown/offline target individually.
The dispatcher does not queue a start for a disconnected site or replay a
command at startup. Older responses cannot overwrite a newer dispatch's
result helpers. Fleet Summary polling remains an independent monitoring path.

The REST API returns a `service_response` inside its response envelope; an
HTTP 200 or changed-state list alone does not prove a command succeeded.
The dispatcher checks the response shape, matching `request_id` and requested
target, then displays one result for each site:

| Result | Meaning |
|---|---|
| Command confirmed | The node accepted this request and reports matching native mode/power feedback. |
| Pending/blocked | The node accepted it but has not confirmed the requested native feedback. |
| Rejected | The node rejected this request, such as a stale request or a closed gate. |
| Unknown | No usable correlated response arrived, including timeout, HTTP error or incompatible service response. |

Only compact status, power and generation information enters the helpers.
Raw response bodies, headers, endpoint URLs and tokens are never shown there.
Native forced-mode/power values can be cached or virtual; **command confirmed
does not guarantee physical export**, its magnitude, or a retailer payment.
Use measured battery/grid flow and the site's normal operational evidence to
assess physical behaviour. At hub restart the result helpers describe no
command in that session; they do not clear a remote node's persistent hold.

## Local verification

### Downgrading safely

Older HEO versions do not understand this manual-hold journal. Do not downgrade
while a hold or manual export is active: old automatic control could immediately
resume. First Stop, verify native Self Use and both targets zero, and explicitly
Resume while confirming saved automatic policies are suitable. Alternatively,
retain the Safety Lock and verify its no-write state before a controlled
downgrade. Back up the journal and affected configuration; do not delete it to
silence a blocked/untrusted state. A damaged journal requires deliberate,
acknowledged Self Use recovery before normal control is resumed.

### Test coverage

`python scripts/fleet_command_contract.py --check` verifies that both reusable
examples match the generator. Focused native-HA tests exercise helper/script
setup, real REST error/timeout handling, response correlation, acknowledgement
gates, shared aware request timestamps, parallel failure isolation and late
response cancellation. The HEO manual-control tests separately prove node
ownership, persistent holds, generation ordering and device sequencing. These
local checks do not claim live-site deployment or measured physical export.
