# Project source of truth

The public product name is **FoxESS GloBird Tesla Energy Orchestrator**. The
existing `home_energy_orchestrator` integration domain, entity IDs, and `HEO`
short form remain stable for upgrade compatibility.

Registered entity IDs become user-owned after first creation. Setup and reload
must preserve a user's entity ID, custom name, area, labels, visibility and
enabled state. HEO may improve default display translations, but must not
silently reclaim a registered object ID or treat presentation changes as
permission to change unique IDs, machine states or public attributes.

This is the public, durable design record for the project. Git records what
changed; this file records the authority order, supported behavior, and rules
future work must preserve. Site addresses, credentials, incident chronology,
and private operational evidence belong only in the local private record.

## Qualified load readings

Fleet house/EV power has one read-only composition in `load_power.py`, exposed
through the shared read model and native sensors. EV power is an **estimate**
using state-qualified actual current, commissioned voltage and commissioned
phases, not requested current or maximum charge rate. A fresh explicit stopped
state means zero; unknown/stale/restored feedback is not zero. House-only power
subtracts EV exactly once only if its source includes EV. Existing `house_load`
and `house_load_kw` retain their configured meter-topology meanings.

The default `house_load_source=sensor` preserves the existing mapped source
and saved includes-EV flag for valid non-negative power. Negative consumption
is invalid canonical evidence, not a positive value or a learned zero. For a
commissioned external AC-solar topology, explicit `power_balance` calculates
import-positive grid + generation-positive AC solar - charge-positive battery.
All dependencies must qualify independently. A whole-site balance necessarily
includes EV; it uses that topology without rewriting the saved sensor flag.

The separately selected `power_balance_cloud_solar` profile permits a bounded
solar estimate from the explicitly mapped native SolisCloud AC power entity:
at most 600 seconds since the provider's actual measurement timestamp. HEO
reads power, units, serial and timestamp from one already-fetched matching
frame, bound to the loaded native entry/device. An equal power value may remain
valid when that frame's measurement time advances; a cached or attributes-only
HA report cannot renew it. Partial/unsupported/mismatched frames fail closed;
there is no new API request, companion-timestamp guess or HA-clock fallback.
From v0.12.50 the frame is captured during the selected inverter's native
publication, because the account-wide API cache is reused for other inverters.
A lifecycle-owned read-only subscriber retains only that complete immutable
frame. Other inverter publications cannot replace it or renew its clock. A
malformed selected publication invalidates it; no new publication leaves only
the original bounded measurement, not a renewed lease. Source/provider changes
and unload remove only HEO's observer and discard its frame. Startup may wait
for a genuine selected-inverter publication. No polling or stored schema is added.
Grid/battery/current retain their normal
fast limits, as does canonical solar used by EV tracking. The oldest accepted
balance clock remains visible. Price-export rechecks that explicit house bound
and retains its existing conservative age-energy margin and reducing cleanup;
it never relaxes grid, battery or SoC checks. DC battery-side power makes the
balance approximate because conversion losses are not separately metered.

No source is selected automatically. Verify units, signs and whole-site AC
topology before re-confirming direction verification. A broken CT is not fixed
by this software estimate. See `docs/fleet-monitoring.md` for commissioning,
quality limits, dashboard preservation and downgrade precautions.

The diagnostics download includes an on-demand, redacted `solar_provider`
report only for the explicitly selected cloud-solar profile. It runs the same
capture checks and records the rejected boundary, known cache-field types and
presence, and finite power/measurement evidence when available. No arbitrary
cache content, identity, credential or extra API call is exposed. Capture shape
acceptance is not freshness or control permission; all existing bounds remain.

## Optional Fleet maintenance extension

The separately configured Fleet maintenance wrapper uses HACS as its sole
installer and native Home Assistant backup, configuration validation and restart.
It is an operational extension, not a charging/export algorithm port, and
changes no normal policy. Per-site actions require a current active administrator
at the hub and node. Origins and remote administrator credentials remain in
private backend config; arbitrary URLs/repositories/services are unsupported.
Publishing v0.12.40 installs, configures and activates nothing on a site;
installing its code alone starts no maintenance operation. Controlled initial
HACS installation and live acceptance remain separately approved steps.

v0.12.41 introduced one shared native HACS metadata-refresh attempt per
process/repository for an empty release-detail cache. Its initial nonempty-tag
prerequisite does not cover HACS 2.0.5, which saves published tags but does not
restore them into memory. The v0.12.42 correction permits a valid empty tag
list after exact installed repository/entity verification. Refreshed release
models and matching published tags remain required before offering a version.
This is cold-start dependency initialisation, not installation or a second
GitHub poller. Populated caches stay read-only; failed initialisation is reported
rather than retried each status cycle. After the await, the exact binding is
checked again. Stable tag syntax never replaces the published non-draft/
non-prerelease metadata checks.

From v0.12.44, an explicit administrator-only per-site **Check releases** action
can refresh a populated catalogue through that exact site's existing HACS
provider. Normal status polling remains cache-only. One shared repository lock,
bounded native refresh and 30-second attempt cooldown prevent overlapping or
repeated GitHub calls. Refresh state/error/last-success time are additive fields,
not maintenance audit phases or permission to install. Failure preserves only
validated choices under an unchanged trustworthy binding; it never authorises
a download from stale data. Both hub and node support are required; old nodes
report unsupported rather than receiving a generic remote service or fallback
updater. This metadata-only action needs no battery/EV idle admission and does
not acquire an actuator fence, change settings, install or restart anything.

Every HEO entry on the target host must have trusted idle runtime/session and
fresh physical evidence. Existing locks are drained and a short process-local
write fence covers the backup/install/restart boundary; no stored control switch
or Safety Lock is changed. Locks are released before shutdown to avoid an
unload deadlock. A completed verified local HA+database backup precedes file
replacement. Changed settings or physical activity abort the next disruptive
step rather than being overridden. A safe-time request expires after its bounded
wait, defaulting to 60 minutes, without becoming a recurring schedule.

Admission distinguishes roles: measured grid/battery power, inverter mode and
EV feedback need their own fresh native report clocks. Stable battery SoC and
saved force-power settings retain their existing value semantics, not an
invented polling deadline. They must be available, valid and not restored
placeholders; force targets must be zero. This does not make old electrical
measurements fresh or change control permission.

Remembered positive EV current targets count as inactive for maintenance only
when fresh mapped feedback positively proves unplugged, non-charging, charge switch off
and state-qualified actual current zero. A valid retained positive raw current
is not charging evidence under that complete disconnected-idle proof; connected
or contradictory feedback retains the existing conservative activity checks.
This does not excuse connected keepalive, pending
sessions/reconciliation/recovery, invalid targets or missing/stale evidence.
No existing freshness threshold or charging policy changes.

An ended backfill session may retain a stop latch while the configured direct
path intentionally keeps charging at a positive protected baseline. Completing
that handoff requires fresh, non-restored cable/charging/switch/current and
actuator feedback, the same confirmed runtime target, and no active surplus,
Full/Trip or recovery owner. The existing representable baseline and actuator
planner are authoritative, not an assumption that every site uses 1 A. Once
proved, only the daily stop fields are retired and immediately checkpointed;
keepalive ownership and energy accounting remain. Save failure restores the
pending duty. A zero baseline still needs switch-off confirmation, and a
connected keepalive remains active for ordinary maintenance admission.

An obsolete, unowned direct-EVSE command episode is retired to the existing
`idle` state only after that same immutable, fresh disconnected-idle observation.
Retirement is not acknowledgement that its former target was applied. It clears
the old active targets and decision cadence and checkpoints immediately, including
while automatic EV control is disabled or service-current feedback is missing.
A failed checkpoint retains the pending episode. Full/Trip intent, active
sessions, unconfirmed stop duties and smart-socket staging/recovery prevent this
retirement. Fresh disconnected-and-switch-off proof may first complete the
existing stop-feedback transition; unplug alone cannot clear that duty.
Reconnection makes a fresh
policy decision. No command, new permission, storage schema or maintenance-audit
change is introduced. See [the bounded correction](maintainability/work-item-ev-disconnected-ack.md).

Downloaded files do not establish loaded version. A private version-one host
audit tracks identity, phase, intended version, original rollback backup,
settings digest and prior process boot identity. Startup only verifies this
record: it never repeats installation/restart or restores the transient write
fence. Integration reload is not reboot. Verification covers loaded HEO,
runtime/source/journal readiness and settings, not measured energy delivery or
absence of external writers. Unknown outcomes require read-only reassessment.

The optional native selectors/buttons and reusable dashboard cards require
explicit hub configuration and dashboard import. Initial old-node bootstrapping
must use an ordinary approved HACS update. Pilot qualification and individual
remote rollout remain separate live acceptance; no automatic fleet-wide rollout
is implemented. See [Fleet maintenance](fleet-maintenance.md).

## Restored EV intent while startup feedback loads

From v0.12.36, an already-enabled restored Full request waits while its initial
vehicle/actuator feedback is still loading. One shared EV startup-evidence
classification is used by EV control, native Trip and the published legacy
dispatcher. Missing startup evidence is not a confirmed unplug and cannot
authorise new EV commands. The original timeout continues counting. Confirmed
absence, deliberate cancellation/replacement, completion, expiry and established
invalid-data safeguards remain authoritative. A consumed request is not
automatically re-armed by an upgrade.

From v0.12.37 this same hold also covers Home Assistant's startup jobs, even
when all vehicle feedback loads early. Readiness requires completed HA startup;
an intermediate status publication cannot consume restored helper ownership
before its startup trigger has rebound the restored Full entity context.

From v0.12.38, the legacy dispatcher consumes the paired
`observed_soc_percent` and `startup_feedback_pending` attributes from one
EV-status update. These are sampled from the same commissioned vehicle feedback;
it must not combine that readiness with a canonical SoC entity which may publish
later. Missing producer capability is a wait, not an invalid-SoC cancellation
or permission to start. Present invalid feedback after startup remains terminal.
This is a publication-coherence correction, not a charging-policy replacement.

## Authority order

1. Direct inverter registers and measured electrical behavior.
2. The proven Working Single Phase Pilot Site v1.4.24 implementation and observed behavior.
3. Home Assistant recorder and service-call evidence.
4. HEO characterization tests and implementation.
5. UI labels and cloud-app displays, which may be stale.

The reference implementation is Working Single Phase Pilot Site v1.4.24 at source commit
`5806b4a5313331fbc421108e9e0c98e661ca20fe`. Public contributors may not have
that private source snapshot, so every port must capture its behavior in a
provenance table and golden characterization tests before implementation.

Different service ratings, phase counts, inverter sizes, solar arrays, and EV
charging capacities are configuration differences. They justify extension
layers around the proven algorithm, not replacement algorithms.

## Current software truth

### v0.12.58 EV-before-export hysteresis correction

The configurable EV top-up buffer defaults to one percentage point; zero
retains the former single-threshold behavior. A bound recovery begun below the
saved export minimum retains that minimum but continues to the buffered target
before handing back to export. Once complete, a reading at the minimum does not
re-arm it. The existing EV journal checkpoints the small recovery record before
positive intent, retains it across restart/disconnect and rolls back failed
transitions. Corruption cannot release export in the uncertain recovery band.
The EV and export policies share this read-only recovery target; their existing
writers, ownership, normal SoC/current/energy limits and physical handoff remain.
The wizard and native buffer number share one configuration-entry value. No
deployed dashboard is automatically rewritten. This correction does not add
simultaneous EV/export or imply live rollout. See [the buffer record](ev-before-export-buffer.md).

### EV discretionary-energy evidence during awaited checkpoints

A genuinely confirmed zero-baseline stop ends its obsolete positive retry
episode. Otherwise a later legitimate request for the same amps/limit can
inherit an old failed-start backoff. Retirement requires a pending stop, fresh
native-qualified stopped/off evidence and no active Full/Trip, daily/pre-free,
surplus or recovery owner. Stop completion and retry/cadence retirement share
one checkpoint; save failure restores both. Positive keepalive and unconfirmed
stop obligations are unchanged. This is not a migration that clears arbitrary
old episodes or treats optimistic switch updates as physical acknowledgement.

Before-export and buffered-soak selection, fallback and energy rechecks sample
complete live feedback synchronously at their actual check time. Earlier captured
feedback and scheduling time must not be combined with a later Tessie frame or
later electrical publication after an awaited checkpoint. That combination can
incorrectly mark an ordinary new reading as future or contradictory and create
a false stop obligation. The local recheck restores the enclosing cycle's
feedback afterward; actuator reconciliation also refreshes its observation so
an already-matching older request cannot hide a new higher current or a lower
actuator maximum. Target/reserve crossings still curtail an existing charge,
even when no new positive service would otherwise be necessary. Every positive
command still makes a new protected check.

This is a coherence correction, not a new charging policy. Native vehicle
identity, measurement age, provider health and value agreement remain required.
Optimistic command acknowledgements are not measurements; actual future/stale
or mismatched evidence remains blocked. The existing instantaneous grid-import
guard, energy reserve, EV targets, electrical caps and exclusive EV/export
ownership are unchanged. Concurrent EV charging and forced export is not enabled
by this correction. Repository regressions do not establish live acceptance.

- Optional dedicated EV planning capacity replaces the instantaneous
  remaining-energy/SoC inference only when explicitly selected. One read-only
  resolver supplies the learned limit/free-window gain, both Trip schedulers,
  allowance and vehicle-room projections for backfill. It accepts an explicitly
  mapped Wh/kWh capacity sensor, the exact mapped car's already-loaded Tessie
  nominal-full-pack field, or a configured value. Tessie adds no HTTP reader,
  credentials or polling loop. Invalid, stale, future, ambiguous or unloaded
  sources yield only an explicit numeric fallback or unavailable, never an
  implicit ratio after opt-in. Provider basis/provenance remains visible; nominal
  pack capacity is not relabelled physically verified usable energy. Existing
  entries retain exact legacy behaviour until configured. All charging policies,
  safety gates, persistent sessions and efficiency settings remain unchanged.
  See [capacity provenance](ev-driving-learning-port.md#optional-dedicated-planning-capacity).

- An optional HACS-owned Trip Charge wrapper schedules the existing HEO Charge
  to Full override for one departure date/time and selected integer SoC from
  1% to 100%. It calculates latest start from HEO's capacity, SoC and configured
  maximum power, and retains a private typed departure, target and ownership journal.
  Completion or cancellation withdraws only its owned override; normal HEO
  policy resumes, so the target is not a permanent SoC ceiling. Target edits
  during charging cancel rather than extend the trip, and invalid SoC withdraws
  owned Full. An unreadable Full entity preserves the cleanup obligation.
  Confirmed temporary disconnection pauses an outstanding trip rather than
  consuming its dated request. A qualified reconnect before departure may
  resume only that request, with its original absolute timeout and generation-
  bound ownership. Explicit cancellation, manual replacement, invalid SoC,
  completion and timeout remain terminal; a pause cannot grant another Full
  budget or create a new late paid start after departure.
  The wrapper adds no Tessie or inverter writer and uses commissioned HEO
  runtime mappings, efficiency and Full timeout directly. An EV-controller
  transaction lock and generation-bound lease prevent an old trip cleanup
  from stopping a newer manual Full request. Checkpoints precede positive
  intent; storage failure blocks a start. HACS installs its seven entities;
  Lovelace still requires an explicit dashboard import. The new schedule is
  off by default. A detected live legacy dispatcher blocks native arming;
  retire it deliberately while no trip or Full request is active. Existing
  helper values and automations are not automatically changed.
  Timing and reported target completion are estimates, with live acceptance
  separate from repository tests. See [trip charging](trip-charge-wrapper.md).

- Reconfigure drafts are not authoritative snapshots of later live operator
  intent. Applying an unrelated page preserves newer untouched settings and
  checks for concurrent conflicts, including changes during final schedule
  confirmation. A conflicting same-field edit fails without overwriting the
  live value; reopen the flow and review the current configuration. This does
  not weaken electrical direction or schedule confirmation requirements.

- Trip status also exposes a read-only pre-free energy/cost estimate. It uses
  the current native request or a validated standard helper plan, canonical
  energy above the configured battery floor, discharge efficiency, existing
  remaining house protection once, and saved import tariffs. It does not turn
  timing margin into energy, price every EV kWh as a grid purchase, or carry
  today's battery pool unchanged through free charging. Paid-energy liability
  includes displaced house demand; a cost range reflects possible tariff bands.
  Later/free-window energy is separate, missing costs remain unavailable, and
  no actuator, permission, setting, journal or charging policy is changed.
  This estimate excludes solar/export forecasts, supply charges, export earnings
  and ZEROHERO credit. See [estimate basis](trip-charge-wrapper.md#estimated-trip-impact).

- A separately commissioned, default-off price request adds admission to the
  existing protected export controller, not another inverter writer. A qualified
  current regional wholesale price at or above the configured threshold can
  grant permission. Direct DispatchIS remains the default source. The v0.12.46
  optional Amber adapter reads the installed native integration's confirmed
  five-minute `spot_per_kwh` attribute as primary, with DispatchIS as fallback;
  it adds no API reader, credentials or Amber polling loop. The two explicit
  mappings, `amber_price_entity` and `amber_price_region`, must bind that source
  to HEO's selected NEM region. Unmapped entries keep the existing path, and
  configuring a source never enables monitoring or selling. The native attribute
  is dollars/kWh including GST, not raw API cents; decimal conversion removes
  GST exactly once. The supported native one-second-after-boundary start is
  normalized to its five-minute NEM block; other malformed intervals fail.
  Estimated, non-five-minute, stale, future and restored readings cannot grant
  new permission. From v0.12.47, a previously qualified, actually observed price
  can bridge publication gaps until 150 seconds after its interval ends. This
  volatile last-confirmed evidence is distinct from current-price freshness;
  failed fetches, estimates and repeats never move its absolute expiry.
  Missing Amber market flags remain unknown;
  affirmative current AEMO intervention, administered-pricing or suspension
  evidence vetoes admission and survives a failed fetch until a newer qualified
  official correction or the block's expiry. A valid low primary always outranks
  a high fallback.
  Contradictory same-interval fallback cannot revive withdrawn primary permission
  when the correction order is unproven. Current-price evidence still expires
  at the exact block boundary; provider changes within one block cannot extend
  its bounded export permission or a resource-shortened session deadline.
  This source extension still requires release validation and separately
  approved live acceptance. The operator threshold is not a retailer critical-event
  declaration or payment guarantee. Price admission reuses protected house/EV
  energy, battery floor/reserve, and the shared daily paid-export cap.
  Its existing session journal additionally binds price ownership to a
  bounded deadline and original actuators. A strictly newer confirmed high
  block can renew only a still-live starting/active price session, after current
  protected-energy/cap checks, without stopping or raising latched power.
  The journal adds optional `price_permission_end` to distinguish a new block
  from repeated same-block evidence. Old payloads remain readable and ordinary
  journals unchanged; restart cleanup still precedes fresh admission.
  Lost permission or Sellable
  requests Self Use and cleared targets; reducing cleanup survives missing
  ledger/numeric command feedback when original metadata and write gates are
  valid. Fresh low prices and affirmative restrictions withdraw permission
  immediately. Expired/stopping sessions still finish cleanup before fresh
  admission. Normal ZEROHERO
  latch semantics remain separate. Free charging, paid EV Full, and manual
  holds take priority. No automatic market-price buying, new event journal,
  reward accounting, or forecast credit is added. See the
  [price export policy](price-triggered-export.md), including safe downgrade.

- Explicit manual battery services can take a persistent operator hold from
  HEO's automatic and diagnostic inverter controllers. Export requests the
  smaller commissioned/native discharge maximum until Stop, subject to native
  inverter/BMS protections. It does not reserve the
  ordinary house/EV budget. Stop selects Self Use and clears both forced
  targets, retaining the hold until a separate Resume confirms Self Use and
  releases it. Saved automatic switches and EV control remain unchanged.
  Safety Lock, commissioned Local Modbus ownership, sign verification and
  actuator gates are never bypassed. New/reasserted positive export additionally
  requires current battery-power telemetry and valid SoC above the configured
  floor. This is an admission gate, not a software cutoff for an already
  accepted indefinite export. Reducing cleanup does not
  require a working energy ledger. A private versioned journal, per-command
  generation and shared inverter lock prevent stale starts/restores from
  superseding Stop. An unreadable journal fails closed. The optional native-HA
  Fleet package dispatches these services in parallel using fixed authenticated
  backend origins, with no startup replay. Its default-off operator
  acknowledgement is not proof that an external writer is disabled. Mapped
  command feedback is not a physical-export or payment guarantee. See
  [Fleet command controls](fleet-command-controls.md).

- Persisted energy meters immediately checkpoint a positive-flow-to-zero
  transition. Energy-delta write thresholds may reduce routine storage writes,
  but must never leave a positive import/export anchor behind after the
  canonical flow has stopped; otherwise a reload can manufacture energy from
  the bounded gap integration interval. When a native cumulative daily-import
  sensor is commissioned, both the exposed ledger total and cost estimate use
  it; the local accumulator is only the fallback daily total.
- Daily financial reporting keeps import charges, the supply charge, and export
  earnings separate. Export inside the configured Peak Solar/GenerationFeedin
  window receives its base rate and all remaining export receives the configured
  Off-peak base rate; boosted-window export independently
  receives the configured additional ZEROHERO boost up to the lesser of
  measured window export, measured daily export, and the boosted daily
  allowance. The independently configured automatic-export cap
  limits controller energy without changing tariff eligibility. From v0.12.52
  it consumes one separately persisted union of measured net export during
  positive configured base tariffs, eligible positive bonus energy and owned
  bounded price-export opportunities. Overlap counts once; zero-rate solar
  overflow does not consume it. Total physical export and revenue remain
  unchanged. The missing new Store conservatively seeds the upgrade day's old
  total; paid-only accounting starts at next local midnight. Malformed same-day
  state or an unsaved checkpoint cannot grant allowance, and exhausted/missing
  paid evidence requests existing cleanup even for an ordinary latched session.
  The price classification is an HEO cap estimate, not a retailer event or
  payment guarantee. See [paid-cap accounting](tariff-meters.md).
  Existing
  entries migrate the old shared allowance into that cap to preserve behavior.
  Measured net cost is gross cost minus measured export revenue and any credit
  already qualified by HEO. The separate daily forecast is deliberately
  optimistic: it assumes the configured ZEROHERO credit and initially assumes
  75% of the remaining planned export will be realised. Neither value is the
  retailer's final bill.
- Forecast calibration is read-only and has no control authority. HEO freezes
  one daily forecast, matches it only to complete same-date GloBird results,
  and exposes forecast, actual, error, and ZEROHERO outcome as a scorecard. It
  slowly calibrates forecast export realisation and a bounded cost residual;
  it never changes export, charge, EV, inverter, or Safety Lock decisions.
  Days on which ZEROHERO was not achieved remain visible but do not train the
  residual because they violate the forecast's explicit optimistic assumption.
  Existing entries migrate a complete, unambiguous pair of GloBird scorecard
  entities from one GloBird config entry; explicit or partial mappings remain
  untouched for manual review. The GloBird `missed` result is normalized to
  HEO's retained `not_achieved` value. Incomplete, pending, unknown, and
  mismatched-date results never enter the scorecard.
- ZEROHERO automatic export requests the configured inverter discharge maximum,
  capped only by the mapped actuator maximum. The inverter enforces its own grid
  export limit. A lower legacy user-entered discharge preference is ignored so
  ordinary house load cannot consume artificially withheld discharge headroom.
- A valid unfinished export journal also retains ownership when FoxESS Modbus
  exposes its underlying Feed-in First fallback after the forced-discharge
  overlay is lost. The existing session logic decides continuation versus
  Self Use cleanup; fallback recognition alone grants no new export permission.
  Missing/invalid export ownership, a conflicting unfinished charge session or
  an active diagnostic cannot use this exception. Manual holds and all normal
  write gates still take precedence. This is not cloud/VPP provenance and does
  not establish the absence of another writer. See the
  [export recovery contract](zerohero-export-policy.md#feed-in-first-fallback-recovery).
- The configurable ZEROHERO daily credit defaults to $1.00 and is deducted once
  from estimated net cost only after the full configured window is complete,
  all expected clock-hour buckets were observed, and no bucket exceeds the
  configured per-hour import threshold. It is never multiplied by the number
  of qualifying hours and is not awarded early from the live debounce guard.

- HEO is observer-by-default.
- The verified Working Single Phase Pilot Site ZEROHERO export port is behind Local Modbus ownership,
  the FoxESS automatic gate, the independent export toggle, and the Safety
  Lock.
- A faithful direct-EVSE free-window Tessie path is present behind its own
  default-off intent, explicit commissioning flag, complete mappings, and the
  shared Safety Lock. It has not been enabled on a live site.
- The daily EV ready-by allocation is a separately identified configurable
  extension around the retained latest-start arithmetic. Its Tessie-only path
  may run with FoxCloud ownership from live post-midnight energy, but only
  Local Modbus ownership allows HEO to protect the following ready cycle from
  its own ZEROHERO export. That protection is not independent permission to
  charge: the ready-by path is capped by the live ZEROHERO export plan and
  stops when genuinely sellable energy disappears. The ready-to-ready ledger,
  confirmed wall-energy accumulator, shrinking active-session target and start
  latch survive restart.
- **Backfill timing** now has two configuration choices. **Ready by** is the
  default for new entries and existing entries with no saved timing choice.
  An explicit **Conservative** choice preserves late pre-free charging plus
  the existing fixed daily allocation's proportional-surplus semantics.
  Upgrade changes only the missing timing selection; Automatic EV Control and
  pre-free enable requests retain their saved state. Ready by uses
  the full currently safe discretionary battery budget through the same
  ready-by planner, session and persisted ledger. It works with a zero fixed
  allocation, adds no new previous-evening export reservation, and requires
  Local Modbus ownership. Charging is scheduled backwards from the existing
  ready deadline within midnight-to-ready; the deadline must be after midnight
  and before free power starts. It may therefore begin overnight.
  Invalid legacy deadlines or missing power limits hold the policy inactive
  and cannot silently fall back to conservative pre-free charging.
  House protection, the live discretionary/export cap, vehicle room, the
  outside-window battery reserve and inverter percentage, service limits and
  normal charge-limit policy remain binding. Fresh coherent grid/battery
  evidence and fresh mapped house demand are required; excessive grid import,
  invalid energy inputs or lost reserve curtail through the existing stop or
  protected-baseline reconciliation. The v0.12.30 policy-handoff correction
  makes Ready by an additional earlier opportunity: after its deadline, the
  original pre-free planner is eligible against the upcoming free boundary.
  Its energy is capped by the current protected budget, never the earlier
  allocation. Morning solar can run while it waits; with both policies enabled,
  a measured solar opportunity can start combined pre-free charging earlier.
  The pre-free stage remains the sole selected current owner. Invalid Ready by
  evidence still fails closed, not into a less protected fallback. Pending
  stops cannot overrule an authorised successor.
  Late pre-free, paid Charge to Full and free-window charging do not count as
  next-ready-cycle delivery. Elapsed-time ready-by scheduling handles
  daylight-saving transitions. Automated regression coverage does not establish
  live-site acceptance or a completed generated full-system harness. See
  [`ev-daily-ready-backfill.md`](ev-daily-ready-backfill.md).
- Bounded, explicitly submitted FoxESS diagnostics remain available behind
  their guards. They are not schedules. Test ownership, timing and restoration
  attempts persist across reload/restart. An interrupted test immediately
  enters bounded Self Use restoration on setup and remains visibly active until
  mapped mode plus both force targets confirm completion; an unconfirmed
  restoration cannot silently release automatic inverter control. Safety Lock,
  non-Local-Modbus ownership, or incomplete actuator mappings block restoration
  service calls without consuming the bounded attempt allowance; the persisted
  obligation remains visible and retryable.
- A separately gated, default-off Local Modbus free-window Force Charge
  extension is implemented. It uses the configured 24-hour window, requires
  fresh SoC below target and remaining daily free-import allowance to start,
  freezes bounded power for the session, persists its latch/retry state, and
  deliberately restores Self Use at the end or when the allowance is exhausted.
  After restart, current window, SoC, allowance, and control gates are
  authoritative: transient Self Use or Back-up feedback with an unfinished
  HEO-owned session, and an older persisted completed phase, cannot suppress
  an otherwise eligible current-window charge. A clean Back-up mode with no
  unfinished HEO session remains external and is never adopted. Turning off
  the independent charge request or enabling Safety Lock is the deliberate
  operator override. It does not program native schedule registers.
- Automatic Force Charge additionally requires an explicitly confirmed
  schedule. Setup presents exact 24-hour times, duration, and a visual timeline;
  a crossing-midnight window needs a second acknowledgement. v0.12 entries are
  migrated with charging disabled until this review is completed.
- The canonical pilot source contains no local automatic `Force Charge` writer;
  its EV controller assumes battery charging is externally established. The
  local battery controller is therefore explicitly an extension, not missing
  port code or claimed parity.
- Direct-EVSE free-window Tessie current, charge-limit, and charge-start control
  is implemented. Default-off solar-spill and latest-start pre-free stages are
  also implemented for Local Modbus ownership. All three use the same bounded
  feedback reconciliation. The retained pilot's nonzero protected baseline
  never issues a pause; the separate configured-zero-baseline policy may stop
  a connected, unauthorised charge and requires off feedback. If
  the powered direct-path anti-pause guard is active, it retains its configured
  SoC headroom but is capped at 90% whenever Charge to Full is off, including
  after final actuator-step rounding. If that actuator cannot represent a
  value at or below 90%, the direct path issues no command. Charge to Full is
  the only exception and may use the mapped actuator's live maximum (100%
  where supported). If outside-window charging reaches its battery
  reserve, HEO ends the paid
  session but retains a non-zero configured protected baseline through that
  same reconciliation path; only a configured 0 A baseline may stop the
  charge switch. Entry to the configured free-power window is a separate
  reconciliation epoch, so it cannot inherit a failed pre-free/baseline retry
  episode even when both stages select the same current. A valid direct-EVSE
  target has no terminal attempt-count latch: retry intervals progress from
  30 seconds through 1, 2, 4, 8 and 16 minutes, then remain capped at 30
  minutes; the episode and its timing survive restart.
- Charge-to-full operator intent is an integration-owned, persistent switch;
  it is not a site entity mapping. Existing installations retain the effective
  state of the pilot-style external helper until the HEO switch is first used.
  The switch then becomes the sole persistent owner. It preserves the
  source policy ordering and cannot bypass commissioning, ownership, telemetry,
  service-current, allowance, or Safety Lock gates.
- Solar spill reconstructs only measured surplus from EV power, signed grid
  flow (export positive and import negative), and signed battery flow. This
  prevents a carried-over high EV request from treating grid import as free
  solar. Pre-free battery backfill consumes no more than the local protected
  export plan and the vehicle's wall-energy room. Its no-solar path retains
  the latest-start calculation and persisted active phase/frozen start.
- From v0.12.55, enabled **post-free direct-EVSE** solar spill uses a
  time-weighted mean of that same reconstruction, rounded UP once
  to a supported current step and then capped DOWN by physical, service and
  the saved outside-window inverter percentage. Qualified positive gross solar
  and current protected Sellable are mandatory. Both live and snapshot house
  SoC must be strictly above the configured buffer floor (or a higher outside
  reserve); the battery may
  buffer clouds/rounding instead of remaining at the old full-battery threshold.
  No solar/Sellable, reaching that floor, invalid evidence, normal EV limit or a higher
  owner withdraws extra soak through existing baseline/stop. A tiny budget also
  bounds current to energy affordable through the next30s control check,
  conservatively treating it as entirely battery-funded. Ordinary changes adopt
  the latest mean at the configured interval, without a stable-amp-candidate wait.
  Safety reductions remain immediate. Each positive service rechecks authority.
  Optional source-bound averaging history survives only a recent qualified
  restart; invalid, gapped or rebound history is discarded. First entry uses
  observed partial history, never an invented past. From v0.12.56, the buffer
  floor, averaging period and normal adjustment interval are independently
  configurable in EV Charging policies and through native dashboard number
  entities; defaults are90%,5min,5min. Both surfaces persist the same config
  entry values. Edits re-evaluate immediately and invalidate old mean/cadence
  bindings; safety reductions never wait for the adjustment interval. A100%
  floor disables this additional buffer, not the protected baseline. No new
  poller, writer or storage version. Morning, combined/pre-free,
  smart-socket, Full/Trip, free-window and before-export ownership are unchanged.

  | Proven source / authority | Retained behavior | Explicit extension |
  | --- | --- | --- |
  | Pilot v1.4.24 spill reconstruction | EV + export + signed battery; no EV double count | Configured time weighting and upward current step |
  | Protected Sellable ledger / outside envelope | House/reserve/EV protection and all caps | Existing spare energy may buffer above the configured floor |
  | Measured-solar journal / shared EV writer | Persistent cadence, cleanup and priority | Configured cadence and bounded, policy-bound source history |
- Morning measured-solar EV capture is a separate default-off policy before
  the free-power window. It uses the same coherent measured-surplus equation
  but an independently configured house-battery reserve, rather than the
  post-free solar-spill full-battery threshold. The dashboard exposes its
  switch and reserve number. Existing entries keep the policy off and use their
  commissioned outside-window reserve until the new number is explicitly
  saved. When morning solar and pre-free backfill are both enabled, fresh
  positive raw net solar plus a valid protected battery budget can start one
  combined pre-free request before latest start. It adds protected keepalive,
  the current discretionary AC budget divided by a bounded spending horizon,
  and current measured net solar, then floors once and caps TOTAL EV
  current by the saved outside-window percentage and physical/service limits.
  Ready-by priority and evidence holds remain binding. An admitted session may
  use battery energy through zero-solar clouds; invalid authority is not zero
  solar. This is an explicit correction, not pilot parity: the canonical source
  used the larger target and earlier HACS used exclusive pre-free selection.
  Caps, vehicle room and protection can leave energy unused; reaching an exact
  house-battery reserve by free start is not guaranteed. See
  [combined pre-free charging](ev-combined-pre-free.md).
- Legacy/morning measured-solar EV-current changes are restart-safe and require a
  stable 10-minute target before Tessie is asked to change. Verified grid
  import may curtail immediately. The configured measured-solar SoC threshold
  is a hard cutoff: below it, the held spill target is discarded immediately
  and the EV returns to the protected baseline. Any other failed solar
  eligibility condition, including stale telemetry, reserve loss,
  disconnection, EV limit or Safety Lock, also discards the hold. Combined
  pre-free uses the same journal under its existing morning-solar category with
  optional accepted battery-current context, but adopts the latest safe target
  on a ten-minute adjustment cadence rather than requiring an unchanged
  candidate for ten minutes. Otherwise a moving energy/time deadline can reset
  the timer indefinitely and strand energy. Buffered afternoon direct capture
  follows the configured rule above; other measured-solar hysteresis remains
  unchanged. A reduced protected battery component/budget still
  curtails immediately. No new store version or writer is added. Uncombined
  pre-free, free-window, daily-backfill and charge-to-full stages discard the
  solar hold.
  From v0.12.45, combined morning charging spends already-approved spare energy
  over the next normal ten-minute adjustment opportunity rather than waiting
  until free power. Between changes the UTC horizon is anchored to that accepted
  target's next adjustment, with a floor of the existing thirty-second control
  interval. Expected consumption therefore does not cause a rolling-horizon
  staircase of current reductions. A held TOTAL target must fit current measured
  solar plus the remaining budget through that horizon; a required decrease is
  recalculated for its new full cadence before resetting the clock. No new
  energy reservation or store version is added. Existing house, EV and battery
  protection remain authoritative, and a solar-only successor under both
  enabled policies retains the same total inverter-percentage cap. Independent
  morning solar with pre-free disabled and no-solar latest-start admission are
  unchanged. This is a separately approved pacing correction, not pilot parity.
- Solar-spill coherence applies to the fast electrical grid and effective
  battery sources. Rejected inactive-magnitude provenance cannot invalidate a
  fresh signed-battery fallback. Stable battery SoC and state-qualified Tessie
  current keep the pilot implementation's value semantics rather than being
  treated as fast polling clocks.
  The same canonical source selection serves Ready by and pre-free backfill:
  an older inactive zero outside the configured skew limit may yield to an
  explicitly mapped fresh signed sample, provided current flow evidence does
  not contradict it. The accepted signed clock must still agree with the grid.
- The smart-socket command policy is connected to the independently gated EV
  runtime. It preserves the source ordering: bound/stage current before
  power, accept service-valid staged feedback, settle the configured interval,
  then bound current again and start charging. It cannot write an outlet yet.
- Smart-socket configuration and adapter commands require an explicitly mapped
  outlet and configured physical ceiling. Recovery is a restart-serializable
  state machine with a pre-action latch, current and outlet confirmation,
  configurable dwell/timeout periods, delayed permission rechecks, one physical
  cycle per fault episode, visible status, and sustained-health/path rearming.
- Protected-house demand learning integrates the explicitly mapped base or
  whole-house source outside the free window. When a separate heater-power
  source is mapped, it records an independent daily stream and requires seven
  valid samples in both streams before their P80 values replace the occupied
  fallback. Auto occupancy assumes Home unless every Home Assistant person is
  validly away for the configured confirmation period; persistent Home and
  Away overrides reproduce the source controls. Away always selects its own
  fallback. Exactly one resulting budget enters the ledger, and weather
  forecasts remain diagnostic rather than an additive control term. Histories
  and in-progress samples survive ordinary restarts and reject over-gap cycles.
  Source composition retains the pilot order: state-qualify Tessie current,
  remove EV power exactly once only for a commissioned whole-house topology,
  remove an optional separately metered heater exactly once, clamp base demand
  at zero, and accumulate it with the pilot's left integration method. Invalid
  required subtraction telemetry withholds sampling rather than learning a
  knowingly incorrect load.
- FoxCloud ownership blocks all HEO Modbus writes for the entire day. HEO does
  not mix cloud scheduling and local Modbus automation.
- A FoxESS multi-command plan rechecks live owner, master, Safety Lock, sign
  verification and actuator mapping before each service call, including after
  its deliberate settlement delay. If a gate closes mid-plan, the already
  persisted session retains its recovery obligation; no later command in that
  plan is sent. The same interlock applies to manual diagnostics.
- FoxCloud inverter ownership does not block free-window Tessie control,
  because that path does not write FoxESS. It does block solar-spill and
  pre-free stages: both are explicitly Local-Modbus-only policies. The shared
  Safety Lock blocks every write path.
- Entity roles and physical topology are explicitly configured. HEO does not
  guess actuator mappings or infer electrical limits from transient readings.
- All runtime consumers use one timestamp-aware canonical telemetry boundary:
  grid and service current are import-positive, battery power is charge-positive,
  and solar is generation-positive. Signed battery input or the pilot's paired
  charge-minus-discharge magnitudes are supported. Source/direction changes and
  v1 migration clear an independent sign-verification gate, closing automatic
  FoxESS and EV writes until locally recommissioned.
- Setup is a conditional multi-page commissioning workflow; reconfigure uses
  the same page schemas through a section menu. Values remain in an in-memory
  draft and cannot alter the live entry before explicit Review and Apply.
  Electrical-direction verification is part of the final Review and Apply
  boundary, not a standalone reconfiguration section. Changing an electrical
  source or direction clears the displayed confirmation there, so the operator
  can re-verify it before applying rather than unknowingly saving an observer-only
  configuration. Automatic sign calibration must use
  coherent physical evidence and the persisted diagnostic restoration path;
  it must not infer from entity names or enable an automatic-control request.
- Optional mappings shown during commissioning are UI suggestions, not schema
  defaults: clearing a selector must persist an explicit absent value after
  Review and Apply, and reopening the section must not restore it. The
  three-phase grid page groups each CT power with its matching voltage and
  rejects a CT or voltage entity reused for another phase. A direct signed
  current sensor is an alternative to, not a requirement in addition to, all
  three phase pairs. Both methods share one configured positive direction;
  when both are mapped they must have the same sign convention.
- Paired battery charge/discharge magnitudes remain the canonical pilot source.
  When a steady inactive zero alone becomes stale, a separately mapped fresh
  signed battery-power sensor may recover the canonical value with explicit
  fallback provenance. The v0.12.31 source-selection correction also covers
  an older inactive zero whose individually fresh clock exceeds the existing
  EV coherence limit. The pair remains preferred when coherent; an older
  active magnitude, nonzero flow transition or conflicting signed direction
  cannot use this additional fallback. Diagnostics retain rejected pair
  sources, but freshness checks use only the accepted signed clock. Invalid
  magnitudes, disconnected sources and genuine outages remain blocked.
- An installation with EV control explicitly uncommissioned has no EV energy
  reservation. Retained EV defaults or stale mappings cannot withhold its
  otherwise valid battery export plan.
- A multiphase EV controller must receive explicit signed current for the
  most-loaded service phase. Aggregate power is not treated as proof that phase
  loading is balanced. A separately mapped six-source extension can derive
  this feedback from three grid CT phase powers and their corresponding grid
  voltages, with sign, unit, plausible-voltage and freshness checks. It never
  depends on an EV charger voltage or silently replaces an existing current
  mapping. Missing evidence blocks EV current increases rather than assuming
  balance. For a connected direct-EVSE car outside the free window with a
  configured zero baseline and no explicit Charge to Full request, missing
  multiphase current preserves the existing stop obligation: HEO may issue
  only `stop_charging` while its EV write gates permit it. The stop is
  persisted, requires charge-switch-off feedback, and retries with increasing
  intervals capped at 30 minutes rather than a terminal attempt count. Safety
  Lock and unconfirmed home/cable evidence still prohibit a stop command. A
  sustained charging/current-loss mismatch is an alert, not a healthy state.
  The complete six-source phase mapping is a runtime alternative to a direct
  current entity, matching the configuration contract.
- House-load topology is explicit. The retained pilot mapping already excludes
  EV power and remains the default. A whole-house mapping may opt into removing
  measured EV current converted with the commissioned voltage and EV phase
  count exactly once for the free-window allowance projection. HEO never
  infers this choice from entity names, site phase count, or inverter model;
  invalid actual-current evidence makes the projection unavailable.
- In that whole-house topology, a vehicle-SoC update alone must not recalculate
  the allowance while requested and actual EV current are still converging.
  Hold the existing target only until feedback agrees or the normal
  three-minute decision boundary. A measured service-limit overrun always
  bypasses this transition hold. The hold exists only while allowance
  protection is enabled and both the prior and current EV SoC remain below the
  configured target; reaching the target is evaluated immediately.
- A mapped live FoxESS battery-capacity entity is authoritative over the
  configured numeric fallback. Setup may prefill that fallback from an
  unambiguous live FoxESS Modbus capacity value, but must not manufacture a
  capacity from inverter rating or site identity. When no valid live capacity
  exists, setup requires an explicit commissioned fallback and presents no
  default value.
- The portable dashboard preserves the proven operational view structure:
  Overview, Tesla, House, Solar & Weather, Configuration, Advanced, and Manual.
  Shared views use only HEO-owned entity IDs; vehicle-native, weather, room, and
  other site-specific cards are local overlays rather than shared assumptions.
- Dashboard design is informed by the Working Single Phase Pilot Site, but the
  clean disposable test installation is the staging and acceptance template for
  the distributed dashboard. Only dashboard changes reviewed there and accepted
  by the project owner are promoted into `examples/dashboard.yaml`.
- The dashboard must not expose Home Assistant's entities-card aggregate toggle
  as though it were an HEO master switch. Safety Lock is the global no-write
  interlock (ON means no HEO hardware commands); export and EV switches are
  independent behavior requests whose gates remain separately visible.
- Dashboard delivery remains manual in the current release. A future generated
  dashboard or Lovelace strategy/card layer must be upgrade-safe, versioned, and
  preserve local overlays rather than overwriting user customisation.
- Future manual inverter recovery is a distinct operator-control handoff, not a
  second inverter implementation. HEO will use the mapped FoxESS Modbus work-
  mode select and native force-power entities, mirror only their advertised
  options and bounds, and leave register, profile and remote-watchdog behavior
  to that integration. HEO must first persist a visible manual hold and cancel
  its own export/diagnostic latches without issuing a restoration command that
  overwrites the operator's selection. The hold survives restart and suppresses
  all HEO inverter reconciliation until an explicit resume action. Safety Lock
  and exclusive Local Modbus ownership remain mandatory. The hold cannot stop
  or prove the absence of FoxCloud or unrelated Home Assistant writers.
- Treat an EW11 Modbus TCP bridge as single-client unless its exact hardware and
  firmware are independently proven otherwise. Concurrent polling alone can
  make the observed bridge unresponsive, regardless of which client owns write
  control.

## Working Single Phase Pilot Site behaviors that remain the port target

The reference EV policy includes explicit occupancy/location overrides, cable
and charge-state evidence, two charging supplies, configurable current ceilings,
priority, guaranteed free-window current, a free-window SoC target, matched
three-minute grid/current feedback, a settling phase, restart-safe latches,
solar-spill charging, latest-start pre-free backfill, learned driving demand and
charge targets, and smart-socket recovery. These behaviors are now retained
ports, with the learned policy's detailed mapping in
`docs/ev-driving-learning-port.md`.

The house-demand policy and its source mapping are retained in
`docs/house-learning-port.md`.

The pilot's original free-window **House battery** branch used only signed
grid-current headroom. That is not the distributed product policy: a FoxESS
inverter can keep grid current below the same limit by reducing its own battery
charge first, leaving the EV untouched and reversing the selected priority.
HEO therefore treats this as a characterized correction. Below the configured
**House battery SoC for EV taper handoff**, the EV target accounts
for the difference between commissioned inverter charge power and fresh
canonical battery charge power. The conversion uses configured voltage and
site phase count and remains bounded by the connector minimum/maximum and the
physical service-limit correction. At or above that SoC, HEO releases the
battery-power claim and lets the EV absorb capacity exposed by normal BMS
taper. Missing battery SoC or battery-power evidence fails to the configured
free-window minimum. FoxESS remains authoritative for its hardware import
limit; HEO does not write that limit.

The P85 daily-driving model contributes to the general charge limit outside the
free window; it is not part of active free-window current calculation. HEO
collects the same consecutive-day cumulative-meter deltas, persists the same
28-sample/35-day evidence window, and preserves the source fallback and
actuator-step rounding. Configured phase count extends only the electrical
energy conversion.

Its export policy protects learned house demand and mandatory connected-EV
energy, computes sellable energy and latest start, latches a fixed-power
session, observes the independent automatic-export cap, and deliberately
restores Self Use at the configured finish. The retained HEO ZEROHERO path
represents this policy; its detailed mapping is in
`docs/zerohero-export-policy.md`.

The default-off EV-before-export threshold is a separately identified
extension, not pilot parity. Below the adjustable target it prevents or ends
HEO automatic export while preserving the saved request. From v0.12.51, a
confirmed home/connected direct-Tessie vehicle may use already-Sellable battery
energy through the existing outside-window EV writer; no solar, ready-by or
latest-start condition is required. This uses Sellable before export-cap/window
clipping, not the hidden/zero planned export. Current live floor/reserve,
learned house and protected EV energy remain deducted once. Missing/stale
electrical/house/vehicle evidence or material grid import withdraws the top-up.
The usual total outside-window inverter percentage, service/connector limits,
battery cutoff and normal EV ceiling remain. Tiny budgets are paced using the
retained three-minute energy/current calculation and rechecked each control
tick. A top-up never creates another fixed EV reservation or credits itself to
the daily-ready allocation. An already-active daily-ready session is retained;
Free/Trip/Full preserve their existing priority.

Top-up waits for idle HEO battery sessions, no manual/diagnostic owner and fresh
Self Use/zero force targets. At the target, or when its authority disappears,
it returns to the ordinary baseline/stop/successor path. Export waits for fresh
physical EV baseline/off feedback before starting, including startup before EV
restoration and between positive export commands. The smart-socket path keeps
its previous independent authority; this release does not add top-up authority
to a path without a general direct stop. Unknown is not idle; a
confirmed unplugged/off cohort may qualify retained current exactly as before.
The normal evening plan is then recalculated inside its original window, not
forced to start immediately. Invalid or unavailable EV SoC withholds export
only while the opt-in is enabled. No new stored schema, controller or timer.

From v0.12.54, the top-up distinguishes native publisher measurement clocks
from unchanged HA entity clocks. Existing fresh mapped feedback retains its
original contract. For the unchanged-value alternative, native charge inputs must
belong to the same loaded entry/vehicle, match one existing charge-state frame,
and pass the unchanged EV age limit using `charge_state_timestamp`. Failed,
offline, restored, mismatched and optimistic command-only data cannot grant
authority. Location still needs its own fresh report. A recent HTTP cache fetch
cannot renew an old vehicle measurement. Native FoxESS retained mode and
battery SoC require available non-restored values and the same loaded inverter's
fresh local grid evidence, in addition to all existing fast electrical/house
checks. Generic publishers retain strict report-clock checks for mode/EV data.
This correction is confined to the top-up's budget guard; maintenance admission,
export physical handoff, ordinary solar and other policy freshness are unchanged.

Direct Tessie control also treats the configured connected-EV baseline
as site policy: an otherwise unauthorised plug-in auto-start cannot retain a
vehicle's previous charging current. A zero baseline creates a bounded stop
obligation, while free-window, solar, backfill and explicit Charge to Full
authority remain unchanged.

Crossing into ZEROCHARGE while pre-free charging is active forces an immediate
EV decision. HEO clears outside ownership and applies the configured free-window
settlement policy at that boundary; the previous battery-backed current target
must not persist until the ordinary decision interval.

The configured outside-window inverter percentage limits daily backfill and
pre-free EV charging, including the total combined target rather than just its
battery component. It is a percentage of commissioned inverter output, not a
percentage of the EVSE current setting. Conversion uses configured EV voltage
and phase count and rounds down to a supported step.

Dashboard plan entities describe actions HEO is currently permitted to take,
not merely an internal economic candidate. When EV-before-export or another
effective gate withholds export, planned start, energy and duration are absent
and the export status names the hold. The internal candidate remains available
to the controller for immediate recalculation when the hold clears.

## Delayed control-conformance supervision

The active controllers remain the only normal policy writers and continue to
reconcile every 30 seconds. A separate supervisor observes their declared
targets and actuator feedback. It requires the same mismatch continuously for
five minutes before opening one fresh, bounded reconciliation epoch. It does
not write every cycle, does not bypass Safety Lock or commissioning gates, and
does not replace the underlying controller state machines.

The supervisor covers failures that are unambiguous from commissioned local
evidence: a battery charge or export session not holding its HEO-owned mode, an
unexpected Force Charge or non-forced mode outside an HEO session, and an EV
requested current or charge switch that does not match HEO's current target.
It emits `home_energy_orchestrator_control_issue` when a sustained issue opens
and when it recovers, and mirrors the issue in the Orchestrator Status entity
attributes and a local persistent notification. Notification delivery is a
Home Assistant automation concern, so Telegram, ntfy, mobile-app and other
channels do not become integration dependencies.

An unexpected Force Discharge is not inferred to be a VPP event. FoxESS Modbus
does not provide FoxESS Cloud/VPP event provenance, so HEO reports it as an
unattributed external forced discharge with cloud verification unavailable.
It alerts but does not automatically cancel that mode, because doing so could
fight a legitimate VPP instruction. A future exemption may be labelled
verified VPP only when an explicit cloud event source supplies affirmative,
fresh evidence; timing correlation, absence of an HEO command, or the mode
itself is insufficient.

During Home Assistant startup inside ZEROCHARGE, Tessie feedback may recover
before the signed grid-current average. HEO preserves an already-running EV
request for at most five minutes while the normal average gains coverage. A
measured service-limit overrun still curtails immediately. This prevents a
healthy free-window request being actively reduced to the fallback current
solely because integrations restored in a different order.

## Inverter evidence rules

For supported H3 remote control, work mode register `49203` uses `1` Self Use,
`2` Feed-in First, and `3` Backup. Remote control uses registers `46001` enable,
`46002` timeout, and `46003–46004` active power. Treat direct register state as
authoritative when Home Assistant or a cloud UI is stale.

Timing correlation, a disabled-looking boolean, or the absence of a visible
cloud schedule does not identify a writer. Preserve service-call and register-
transition evidence, distinguish manual intervention, and label hypotheses as
hypotheses. Never change a Home Assistant clock to test a time boundary.

## Decision log protocol

For every future control change, record in this file or a linked policy:

- evidence and its source;
- Working Single Phase Pilot Site source sections and preserved decisions;
- configurable site extensions, separately identified;
- rejected alternatives and why;
- tests proving parity, restart behavior, stale-data handling, and ownership;
- deployment state and rollback condition.

Update the private local operational record separately when site-specific
evidence changes. Confirmed facts and hypotheses must remain visibly separate.

The free-window ownership evidence and extension boundary are recorded in
[`free-window-battery-ownership.md`](free-window-battery-ownership.md).
