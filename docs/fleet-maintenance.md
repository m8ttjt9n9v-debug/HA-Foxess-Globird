# Update and restart a Fleet site

The optional Fleet maintenance controls let an administrator choose a published
HEO release and request **Update & restart**, or request **Restart** without a
new download. Each action affects **one site only**. HACS remains the installer;
HEO does not add another updater or change the battery and EV charging policies.

The site waits for a safe opportunity, creates a verified recoverable backup,
installs the selected release when requested, checks configuration, and asks
Home Assistant to restart. The default wait for a safe opportunity is 60 minutes.
It does not stop an active charge or export to make the update possible.

Available in v0.12.40. Publishing the release does not install, configure or
activate maintenance on a site; controlled installation and live acceptance are
separate steps.

v0.12.41 introduced cold-start release-list loading but misses a HACS 2.0.5
startup case: that version saves release tags without restoring them into memory,
so both tags and release details may be empty. The v0.12.42 correction allows
the verified installed repository to initialise both lists through HACS's own
metadata path, without downloading code or issuing controls. Versions still
require full published, non-draft, non-prerelease evidence after that read.
A failed attempt is reported, not retried on every status update; check HACS's
connection and refresh its repository information before retrying deliberately.

Once admitted, maintenance temporarily prevents **new** HEO actuator commands
while the backup and installation run. A large backup can delay a newly due
charging/export action. Choose a maintenance gap well away from charging and
departure deadlines; the idle check is not a prediction of the next safe gap.

## First installation

Every target needs a maintenance-capable HEO release before it can accept these
requests. Install that first release through the site's ordinary HACS interface,
using the usual backup and controlled restart process. A site showing **First
update needed** cannot be bootstrapped by these buttons. There is no fallback to
unrestricted remote Home Assistant, FoxESS or EV commands.

The monitoring hub also needs that release, plus the optional backend
configuration below. HACS installs the integration code, **not** personal
dashboards or this YAML configuration. Adding the backend configuration requires
a configuration check and a separately approved safe-time hub restart.

Merge this into the hub's existing configuration; do not duplicate its top-level
`home_energy_orchestrator` key:

```yaml
home_energy_orchestrator:
  fleet_maintenance:
    # With several HEO entries on the hub, specify the entry that owns these
    # Fleet entities. Omit this for a hub with exactly one HEO entry.
    # entry_id: HUB_HEO_CONFIG_ENTRY_ID
    sites:
      - key: alpha
        name: Local site
        local: true
      - key: bravo
        name: Remote site 1
        origin: "http://SITE_B_PRIVATE_HOST:8123"
        token: !secret site_b_maintenance_token
      - key: charlie
        name: Remote site 2
        origin: "http://SITE_C_PRIVATE_HOST:8123"
        token: !secret site_c_maintenance_token
```

Use each site's verified origin, including its actual port exactly once. An
origin contains no path, query, username or password. Use HTTPS or an
appropriately secured private network. Site keys are stable lowercase identifiers;
changing one creates a different entity identity. The local target, if present,
calls its own node directly and needs no network token. Only one local target
is allowed. Each remote request is restricted to the fixed maintenance services
at its configured origin, never a URL supplied by a dashboard action.

Keep remote tokens in the hub's `secrets.yaml`, for example:

```yaml
site_b_maintenance_token: "REPLACE_WITH_PRIVATE_ADMINISTRATOR_TOKEN"
site_c_maintenance_token: "REPLACE_WITH_PRIVATE_ADMINISTRATOR_TOKEN"
```

A complete `Bearer …` value is also accepted. Use deliberately created
administrator credentials: Home Assistant tokens inherit their user's
permissions, and these are privileged credentials. Do **not** silently reuse or
elevate a non-administrator Fleet monitoring account. Protect the hub and its
backups accordingly; never put tokens in Lovelace, browser code, public examples
or debug output. Maintenance buttons and release selection require the current
active administrator on the hub. Remote nodes independently authorise the
configured token's administrator. Anonymous automations cannot bypass this by
calling the buttons or services directly.

## Dashboard controls

The [reusable Fleet dashboard](../examples/fleet-dashboard.yaml) puts a small
single-line maintenance row beneath each site's existing monitoring card. It retains the
separate manual Export/Stop controls at the top. Maintenance does not use that
export dispatcher and has no **Update all** or **Restart all** action.

The row uses small native text controls, without a heading or large buttons:
**Release · Update · Restart · Check releases**. Release opens the site's release picker.
Update still means update **and restart**, and both privileged actions retain their confirmation prompts and
server-side administrator/safety checks. Controls do not bypass an unavailable
site or missing initial installation. The detailed status Markdown template is
retained for an optional diagnostic view, not displayed in the default row.
Detailed progress is also available in the site's maintenance entity more-info
dialog through Home Assistant's entity search; it does not occupy this row.

For the example `alpha` target, the maintenance entities are:

| Entity | Purpose |
|---|---|
| `sensor.home_energy_fleet_alpha_maintenance` | Progress, versions and reasons for waiting |
| `select.home_energy_fleet_alpha_release` | Select a release this site's HACS currently offers |
| `button.home_energy_fleet_alpha_update_and_restart` | Back up, update and restart when safely idle |
| `button.home_energy_fleet_alpha_restart` | Back up and restart when safely idle |
| `button.home_energy_fleet_alpha_check_releases` | Ask this site's HACS to check GitHub for releases; no installation or restart |

The other cards use their own configured keys. Confirm the final entity IDs;
registered IDs and personal renames remain user-owned. The release selector is
not a text box for branches, commit IDs or download addresses. The node checks
the current HACS catalogue again before installation; it does not reinterpret
the selection as whatever happens to be “latest” later.

### Check for newly published releases

Click **Check releases** when a new release is missing from the picker. Fleet
asks that site's existing HACS integration to refresh its release information
from GitHub, then updates the choices. This is only a metadata check: it does
not select a version, download integration code, create a backup, restart Home
Assistant, pause automation or issue battery/EV commands. Normal charging and
export do not need to stop for this check.

Both the hub and the target need v0.12.44 or newer for this action. An older
site gives a clear update-first message and retains its existing choices;
there is no alternate privileged remote-command route. Bootstrap through the
site's normal HACS metadata refresh and controlled update once.

Normal Fleet polling still reads status about every minute; it does not check
GitHub every minute. Explicit checks share a short 30-second cooldown for the
same HACS repository, including failed attempts. Connection failures are shown
as failed checks, not successful refreshes. Last-known validated choices can
remain visible while their exact HACS binding remains trustworthy; the installer
independently verifies current published membership before any code download.
The maintenance sensor's `release_refresh_state`, `release_refresh_error` and
`release_last_checked` distinguish the release check from an update/restart.
Checking releases never clears an existing maintenance warning or audit record.

Before changing a deployed dashboard, fetch and back up its **fresh live
configuration** and compare it with any local copy. Start from the live layout,
merge only the approved maintenance cards, stop if that layout changes before
saving, and read back to verify unrelated content is intact. Do not replace a
personal dashboard with this example. Installation or dashboard import sends no
update, restart, inverter or EV command.

## What the card means

- **Running HEO** is the version loaded by Home Assistant.
- **Downloaded HEO** is the code HACS has installed on disk. It can differ from
  the running version until a successful restart.
- **Backup: Verified** means this maintenance request has a checked recoverable
  backup. It is not a claim that a copy exists outside the device; keep your
  normal off-device backup arrangements as well.
- **Waiting for a safe time** names the reasons the site cannot proceed yet.
  This includes active battery or EV work, pending recovery, missing feedback,
  non-Self-Use battery mode or uncleared force targets. There is no special
  keepalive exception: a charge switch still on or unconfirmed EV work blocks
  maintenance even when an app happens to show 0 A.
  A remembered positive current target can be treated as inactive only when fresh
  readings positively confirm the car is unplugged, not charging, its charge
  switch is off and state-qualified actual current is zero. A valid retained raw
  current alone does not imply charging under that complete proof. Missing or stale readings cannot
  qualify; pending sessions, reconciliation and recovery still block maintenance.
  HEO can retire an obsolete unowned direct-command episode after qualified
  unplug, save that retirement and replan after reconnect. This is not command
  confirmation and does not clear an interrupted maintenance audit.
- **Fresh evidence** uses the actual Home Assistant report clock for measured
  power, inverter mode and EV feedback. A stable battery percentage is a level,
  and FoxESS force-power numbers are saved target settings, not continuously
  polled measurements. Their age alone does not block maintenance: they must
  still be available, valid, not restored placeholders, with both targets zero.
  Fresh power and Self Use mode plus trusted idle sessions remain mandatory.
- **Running verified** is shown only after the restarted site confirms the
  requested running version, loaded HEO and preserved integration settings.
- **Needs attention**, **Interrupted**, **Restart needs checking**, or **Outcome
  unknown** requires a site check before another request. A network timeout is
  not proof that the node did nothing.

These are local safety checks, not evidence that a VPP/cloud controller or an
unrelated automation cannot act. Preserve the site's commissioned control
ownership. Maintenance never changes Safety Lock, disables control switches or
issues inverter/EV commands to create an idle state.

## Failure and recovery

The node keeps a private audit record and allows only one maintenance operation
at a time. A received request may continue after the hub loses its connection;
the hub sends it only once. It polls status about every 60 seconds to learn the
result. It does not automatically repeat a failed download, restart an
unresponsive site, or replay a saved operation at startup. An expired safe-time
wait does not turn into a queued update on the following day.

Configuration errors prevent a restart. If code was already downloaded, the
site may therefore be **restart pending** while its old version still runs.
Inspect and correct the actual issue before deliberately requesting Restart.
If the site cannot restart or load HEO, use its normal local recovery/backup
tools; Fleet cannot repair an unavailable Home Assistant server.

Update and verify the pilot first, then the other sites individually. Restarting
the hub temporarily takes Fleet offline, so reconnect to it and verify its
running version before proceeding to another site. The reusable dashboard and
repository tests are not live-site acceptance or permission for unattended
fleet-wide deployment.
