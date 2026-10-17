# System requirements and integration map

## Optional Fleet maintenance

Fleet maintenance requires HACS update support for the verified HEO repository,
an available standard local Home Assistant/Supervisor backup destination, native
configuration validation and restart support. A backup must include HA config
and database, finish without partial failures and be read back successfully.
Unsupported capabilities block maintenance, not ordinary HEO setup/control.
A local backup is not an off-device or restore-tested guarantee.

From v0.12.41, cold-start release details are initialised once through the exact
verified HACS repository's native metadata refresh. Concurrent readers share
that attempt, failures do not create a new repeating network poller, and normal
populated catalogue reads make no new request. Published-tag membership and
explicit stable-release metadata remain mandatory.

HACS 2.0.5 can restore both published tags and release models as empty lists.
The v0.12.42 compatibility correction permits that valid cold state to reach
the native metadata read after exact installed-repository verification; malformed
lists still fail closed. Persisted tag strings are not required to authorise a
metadata read and are never sufficient to authorise installation.

Remote targets require explicitly configured private origins and administrator
credentials stored only on the hub. Monitoring accounts are not automatically
elevated. Both the initiating hub user and node token must be current active
administrators; direct service/button calls cannot bypass that check. No generic
service forwarding, arbitrary download ref, redirect or retry is permitted.

Admission is host-wide and fail-closed for active battery/EV/Trip/diagnostic or
manual export, recovery/reconciliation, invalid storage and missing/stale
physical feedback. There is no implicit exemption for idle keepalive charging.
A remembered positive EV target can be disregarded only when fresh feedback
positively confirms unplugged, not charging, charge switch off and actual zero
current. Connected keepalive and pending work still block; missing/stale readings
are not an exemption and existing freshness limits remain unchanged.
Freshness applies to measured power, mode and EV feedback using native report
clocks, not cached REST serialization. Stable SoC and saved force-power targets
are checked for valid available values, not time since their last change;
restored placeholders and nonzero targets block. No old measurement is promoted
to fresh by an unrelated source.
Do not stop a session to obtain an update opportunity. Stored policies remain
unchanged; HEO temporarily fences its own actuator writes only during admitted
maintenance. External controllers remain outside that fence.

Old nodes require a separately approved first HACS installation. Dashboards and
backend target config are explicit imports, never silently installed. Running
version verification requires a real HA process restart, healthy HEO runtime and
preserved settings, not just a changed HACS version or successful HTTP response.
Unknown/restart-pending outcomes require deliberate operator review. See
[maintenance installation and recovery](fleet-maintenance.md).
Publication of v0.12.40 does not install, configure or activate this capability
on any site and is not live-site acceptance.

## Existing integration requirements

HACS installs HEO code only. It does not install device integrations, create a
dashboard, commission electrical limits, or migrate personal entity mappings.

The optional [Fleet command package](fleet-command-controls.md) needs a tested
manual-control HEO version on every target, commissioned exclusive Local
Modbus ownership, and a native-HA hub with backend Authorization secrets for
its fixed remote origins. It sends no commands during installation. Existing
VPP/cloud or other inverter writers must be disabled before operator use;
acknowledgement cannot verify or disable them. Home Assistant restarts for code
installation require the deployment-specific safe-session checks.

Optional [price-triggered export](price-triggered-export.md) needs outbound
HTTPS access to AEMO's current DispatchIS report index and ZIP reports, an
explicit NEM region, fresh commissioned electrical/house/SoC telemetry, and
native force-power number entities in kW. It needs no third-party price
integration. Observation and automatic export are separate default-off
requests. Exclusive Local Modbus ownership and the existing control gates
remain mandatory; a price reading cannot prove a VPP is disabled or that a
retailer payment applies. The configurable sell threshold is inclusive:
the current source price must be at or above it (default $3/kWh). Automatic
price-triggered buying is not included.

## Required for the retained feature set

- A supported Home Assistant installation and HACS custom-repository access.
- The FoxESS Modbus integration for local inverter telemetry and actuation.
- A compatible FoxESS inverter exposing battery SoC, signed grid power, work
  mode, force-charge power, and force-discharge power entities for any Local
  Modbus control or diagnostic use.
- Commissioned battery capacity/floor/reserve, inverter charge/discharge limits,
  site phase count, service import limit, export limit, tariff windows/rates,
  free-energy allowance, and ZEROHERO export settings.
- A trustworthy mapped protected-house load sensor. Map whole-house power when
  that is the intended complete protected demand. At the Working Single Phase
  Pilot Site the mapped source is non-heater base-house power and the heater is
  supplied through the optional separate power mapping, preventing double
  counting. If the mapped value includes EV charging, enable **Mapped
  house-load sensor includes EV charging** so the allowance projection removes
  live EV power exactly once. Leave it disabled for an already EV-exclusive
  house sensor. This correction requires valid actual EV current plus the
  commissioned EV voltage and phase count; missing evidence fails closed.
  HEO holds the existing target across a vehicle-SoC-only early recalculation
  while requested and actual current are converging, but never defers a measured
  service-limit overrun, a target-SoC crossing, or the normal three-minute
  decision boundary. This hold applies only while allowance protection is
  enabled.
- Home Assistant history/storage plus its built-in template, statistics, and
  integration-style behavior used by the source model and HEO persistence.
- Home Assistant `person` entities are optional. Auto occupancy conservatively
  assumes Home when none exist or any presence state is uncertain. Home and
  Away can also be selected explicitly on the dashboard.

The FoxESS work-mode and force-power entities must be explicitly mapped. Entity
availability alone does not prove safe hardware compatibility.

Local Modbus ownership requires a clean inverter schedule state. Delete or
disable every inverter-local Mode Scheduler entry, then clear both legacy
front-panel **Charge time** periods. Where the inverter shows P1/P2, set each
start and end to the same value (the conventional cleared value is
`00:00–00:00`) **and** set its grid-charge state to `Dis`. Do not treat matching
times while the period still displays `En` as commissioned or safely disabled.
FoxESS's [public H3 documentation](https://www.fox-ess.com/download/upfiles/EN-H3AC3-User-Manual-V1.0.4-20250107.pdf)
exposes the Charge time menu but does not define equal-time behaviour across
firmware. The FoxESS Modbus project confirms that these periods are
[stored on the inverter](https://github.com/nathanmarlor/foxess_modbus/wiki/Force-Charge-and-Discharge),
so HEO requires the explicit disabled state as well as a zero-duration period.
FoxCloud ownership is the exception: its intended cloud schedule remains the
sole inverter owner and all HEO Modbus writes stay blocked.

Before commissioning any FoxESS command, open the FoxESS Modbus integration and
ensure **Export Power Limit**, **Force Charge Power**, **Force Discharge Power**,
and **Import Power Limit** are properly set for the commissioned inverter and
site. A zero force-power setpoint can make a manual Force Charge or Force
Discharge mode selection produce no battery power; an incorrect import/export
limit can constrain the inverter independently of HEO. Confirm the live values
and native entity maxima rather than copying another site's ratings.

HEO writes the mapped Force Charge Power and Force Discharge Power entities for
its own bounded sessions. It clears the opposite force target before starting
and clears both targets after restoring Self Use, so finding those two setpoints
at zero after an HEO-controlled session can be expected. HEO does not currently
write the FoxESS Modbus Import Power Limit or Export Power Limit entities.
Safety Lock also blocks recovery writes for a persisted manual diagnostic after
reload or restart. The cleanup obligation remains visible and retryable without
consuming its bounded attempt allowance until Safety Lock is off, Local Modbus
owns control, and all three actuator mappings are complete.

Automatic Local Modbus battery charging additionally requires the work-mode
entity to advertise `Self Use` and `Force Charge`, a positive commissioned
inverter charge limit, a positive live maximum on the force-charge number, a
fresh battery SoC below the configured target, positive remaining daily free-
import allowance, and non-overlapping charge/export control windows. It uses
the inverter limit as its fixed requested power while those current conditions
permit charging and remains default-off after installation. After a Home
Assistant restart it re-evaluates the same conditions; use the independent
Automatic Battery Free Charge switch or Safety Lock to prevent resumption.

An unfinished, valid HEO export journal can reconcile the FoxESS Modbus
Feed-in First fallback after restart, while all normal write gates remain
mandatory. Feed-in First with no valid export ownership remains external;
the mode is not itself an export request or evidence of a cloud/VPP event.
See [fallback recovery](zerohero-export-policy.md#feed-in-first-fallback-recovery).

### Modbus TCP connection ownership

Use one Modbus TCP client for an inverter bridge unless that exact bridge and
firmware have been independently proven to support concurrent clients. During
commissioning, an EW11 bridge was observed to lock up and become unresponsive
when two Home Assistant instances polled it at the same time. HEO therefore
treats the EW11 as a single-client transport: enable FoxESS Modbus on only one
Home Assistant instance at a time. This transport constraint is separate from
HEO's write ownership gates; read-only polling from a second instance can still
break the connection.

## Required for Tessie EV automation

Restored active Full/Trip intent waits for completed Home Assistant startup
and its initial vehicle/actuator feedback before becoming ready. The original
timeout still counts; missing startup data is not a new permission to charge.
Legacy helper installations require the matching startup-aware dispatcher.
From v0.12.38 that dispatcher validates observed SoC and startup readiness
from the same EV-status update, not separate entities with independent update
timing. An older producer missing this capability cannot authorise a new start.

Optional dedicated EV planning capacity can reuse the exact mapped car's loaded
Tessie coordinator, use an explicit Wh/kWh full-capacity sensor, or use a reviewed
numeric fallback. Tessie's nominal-full-pack field requires supporting upstream
software (documented for Tesla firmware 2026.32+). Older or unsupported providers
do not supply a guessed value. This option needs no additional subscription,
credential storage, HTTP client or polling loop in HEO; it does not enable
control. See [capacity configuration and semantics](ev-driving-learning-port.md#optional-dedicated-planning-capacity).

Tessie is optional when EV control is not commissioned. The ported EV
free-window policy requires explicitly mapped capabilities equivalent to:

- vehicle SoC and stored energy;
- cumulative lifetime energy for daily-driving learning (optional; without it,
  the conservative full-window fallback remains active);
- location/at-home state and user override;
- cable connection, charging state, and actual current;
- writable charge current and its min/max/step metadata;
- charge-limit state/control where the source policy requires it; and
- an explicit charge-start switch.

Daily-driving and general charge-limit learning is read-only. When its own SoC,
stored-energy, charge-limit metadata, free-window configuration and retained
history inputs are valid, HEO keeps the learning result available while the
vehicle is away, unplugged or not charging. Location, cable and charging state
continue to gate actuation absolutely; they do not erase valid learning
evidence. Missing or invalid learning inputs still make the result unavailable.

Single-phase sites may derive service current from signed grid power. For
multiphase EV control, map either a trustworthy signed most-loaded-phase grid
current sensor (A), or all three explicitly identified grid CT phase-power
sensors plus their matching grid-voltage sensors (V). The latter calculation
is performed inside HEO; it does not depend on vehicle or charger telemetry.
The phase-power sign must be verified during commissioning. Every phase source
must be fresh and every voltage plausible (180–300 V), or current feedback
remains unavailable and EV current increases are blocked. For a confirmed
home-connected direct-EVSE car outside the free window with a configured
zero-current baseline, HEO can still request a stop of an active charge; it
does not need the missing grid reading to know that charging is unauthorised.
That stop remains pending across restart, retries progressively up to a
30-minute interval until charge-switch-off feedback arrives, and produces an
alert if charging continues. Safety Lock still blocks the command. Aggregate grid power is not
a substitute for per-phase evidence. Existing current-sensor mappings remain
compatible; if both methods are configured, a valid direct sensor takes
precedence and the six phase sources provide a fallback. For the FoxESS
Modbus six-source method, **enable Grid Voltage R, S and T in the FoxESS
Modbus entity list**; these voltage entities are disabled by default on
supported H3 models. Confirm that **Grid CT R, S and T** each report signed
power in W or kW. Match R power with R voltage, S with S, and T with T in
HEO's Grid connection configuration. **Do not use EPS Current R/S/T**: those
sensors describe the inverter's backup/EPS output, not the grid connection.
This FoxESS Modbus configuration is essential only for the six-source
multiphase EV safety method; single-phase sites and sites with a separately
commissioned direct grid-current sensor do not require it.

FoxESS Modbus profiles that expose an unambiguous `BMS kWh Remaining` capacity
entity are suggested automatically, and its current value prefills the setup
fallback. HEO uses the mapped live capacity at runtime. The numeric capacity is
optional when valid live capacity is available. If no live capacity is mapped,
the operator must enter a credible commissioned fallback; HEO does not assume a
default battery size.

The retained pilot direct path never pauses its nonzero protected baseline.
With a configured zero baseline, HEO may stop a connected charge that has no
authorised stage, including one the vehicle started itself. The optional daily
ready-by session may also stop when its wall-energy target, soft SoC limit,
ready deadline, or safety condition is reached. The fixed daily allocation
requires positive configured wall energy, a ready time, inverter-output
percentage, inverter discharge/output rating, and current house/available-
energy ledger. Its existing path can operate with FoxCloud ownership because
it writes Tessie only; that mode cannot reserve energy against earlier cloud
export.

The separate **Backfill timing: Ready by** choice requires enabled pre-free
backfill and Local Modbus ownership. It works with the fixed daily allocation
at zero and adds no new previous-evening export protection. Its ready time must
be strictly after midnight and before the configured free-power start, with a
positive outside-window inverter percentage and commissioned discharge/output
rating. It uses the full current discretionary budget from the existing house-
protected ledger, capped by the live discretionary/export plan and vehicle
room, and may start overnight. Fresh coherent grid/effective-battery power,
fresh mapped house load and valid energy protection are required. Import above
the commissioned ZEROHERO zero-import threshold or lost energy authority
curtails extra charging through the existing stop or protected baseline.
The outside-window house-battery reserve (20% default), electrical limits and
normal charge-limit policy remain in force, including the direct-EVSE 90% cap
unless Charge to Full is on. Ready by shares the existing session and restart
ledger; paid Charge to Full and free-window charging are excluded from its
delivery accounting. With the v0.12.30 handoff correction, Ready by ends at
its deadline and the original pre-free planner becomes eligible again, using
only current protected energy and the upcoming free-window boundary. Morning
solar may run while pre-free waits; active pre-free owns current exclusively.
The same Ready by freshness/authority checks remain required after the deadline,
and late charging does not count toward tomorrow's fixed allocation. Free power
retains independent takeover. **Ready by** is the default for new entries and
old entries missing the timing key, while an explicit saved **Conservative**
choice is preserved.
Neither Automatic EV Control nor pre-free backfill is enabled by this default
change. Invalid old deadlines or missing power limits keep Ready by inactive;
the controller does not silently fall back to conservative charging. See
[EV backfill timing and allocation](ev-daily-ready-backfill.md). Automated
regression coverage does not establish live-site acceptance; the generated
full-system lifecycle and incident harness remains outstanding.

The smart-socket path additionally
requires a mapped on/off outlet, its commissioned physical current ceiling,
and selected recovery/settling timings. It does not depend on a particular
outlet vendor.

Solar-spill control additionally
requires an explicitly mapped signed battery-power sensor, its charge-positive
sign convention, battery SoC threshold, and coherent grid/battery/Tessie
timestamps. The independent, default-off Morning Solar EV Charging policy uses
the same evidence only before the free-power window; it has its own dashboard
editable house-battery reserve SoC and does not use the post-free
battery-full threshold. Latest-start pre-free backfill additionally requires
the Local Modbus ZEROHERO export ledger and, when active, takes exclusive
fixed-current ownership from either measured-solar stage. These
outside-window stages are independently default-off and are rejected unless
Local Modbus is selected as FoxESS owner.

Canonical battery telemetry keeps coherent charge/discharge magnitudes as
its first choice. If an older inactive zero is the only coherence problem,
the existing explicitly mapped signed sensor may supply the value, using its
own fresh timestamp and commissioned sign/unit conversion. Rejected pair
sources remain diagnostic evidence, not accepted clocks. Grid-to-signed
coherence and all age limits still apply. Invalid/missing signed evidence,
opposite flow, or two nonzero magnitudes cannot use this timing fallback.
Ready by, pre-free backfill and measured-solar stages use this same boundary;
none gets a separate relaxed freshness rule.

Measured-solar EV current changes are held until the candidate remains stable
for 10 minutes. This rate limit persists across restart and prevents ordinary
cloud-edge variation from producing repeated adjacent-current Tessie writes.
Verified grid import and any failed eligibility evidence curtail immediately.
The configured measured-solar SoC threshold is a hard cutoff, so the hold
cannot preserve extra EV current below the house-battery boundary.

The Working Single Phase Pilot Site uses Tessie entities for these roles.
Portable code maps roles and never embeds that vehicle's entity IDs. See the
[daily-driving learning provenance](ev-driving-learning-port.md).

## Optional equipment and integrations

- The Working Single Phase Pilot Site uses an eWeLink-provided switch for its
  smart-socket charging path, but HEO depends only on the explicitly mapped
  on/off switch capability, not the vendor name.
- Weather forecast data may support local diagnostics, but it is not an HEO
  house-protection input. The proven control ledger uses measured heater P80,
  not a second weather-derived energy budget.
- FoxESS cloud telemetry may be used as read-only corroboration. FoxCloud Mode
  Scheduler is an alternative inverter owner, not a fallback transport to mix
  with automatic Modbus writes.
- The GloBird Home Assistant integration is optional. Its Latest Daily Cost
  and ZEROHERO Status entities may be mapped to HEO's read-only forecast
  scorecard. Missing, incomplete, mismatched-date, or unrecognised retailer
  results remain explicit and never affect control.
- Tailscale, File Editor, and EMHASS may exist on a site but are not core HEO
  algorithm dependencies.

## Site commissioning values

Every installation must supply its own values. Never copy a reference site's
service rating or a target site's multi-phase rating as a default control fact.
Configure phase count, per-phase or aggregate limits as the model requires,
EV phases/current/voltage, inverter and battery limits, tariff
allowances/windows/rates, automatic export-energy cap, ZEROHERO finish
offset, reserve, and efficiency. HEO derives automatic discharge power from the
commissioned inverter limit and actuator maximum rather than asking for a
separate operator estimate.

Multi-sensor controls must use temporally coherent samples and fail closed when
freshness, units, signs, presence, connection, or ownership cannot be proven.
Configure each raw sign once and consume HEO's canonical sensors everywhere
else; the full conventions and commissioning procedure are documented in
[telemetry normalization](telemetry-normalization.md).

## Dashboard installation

Import `examples/dashboard.yaml` manually or build a site-specific dashboard
from the generated entities. HACS does not install Lovelace views. The example
preserves the eight-view operational structure, including Trip Charge, using only HEO-owned
entity IDs. Personal backgrounds, vehicle-native Tessie cards, weather, room
devices, heaters, and unrelated site cards are intentionally local overlays.
The example deliberately disables Home Assistant's entities-card header toggle:
it is not an HEO master control and is unsafe to present beside the opposite-
polarity Safety Lock. Safety Lock ON blocks all HEO hardware commands; the
automatic export and EV switches express independent intent and do not bypass
that lock or their respective readiness gates.

Trip Charge entities are installed by HACS, with scheduling off by default.
The first implementation requires the commissioned direct-EVSE path, usable
EV capacity, configured maximum charging power, explicit home/cable evidence,
EV control enabled and Safety Lock off. It uses HEO's runtime efficiency and
Full timeout; there are no helper copies to keep in sync. A separate legacy
trip dispatcher must be retired deliberately before arming the built-in one.
Confirmed temporary disconnection pauses an outstanding trip; reconnect before
departure requires fresh commissioned evidence and retains the original Full
timeout. Cancellation, replacement, completion and timeout do not resume.
The legacy helper version additionally needs its published resume-checkpoint
helper and updated dispatcher; a HACS update alone does not replace a separate
existing helper installation. Update that installation explicitly or migrate
only after deliberate ownership handoff.
The departure/SoC estimate does not guarantee exact physical completion.
The optional Trip impact display also needs valid existing house/battery
budgets and saved import tariffs. It estimates extra paid energy only until
the next free window; it adds no forecasting provider or control dependency.

For a single read-only dashboard covering several installations, use the
versioned Fleet Summary entity and Home Assistant's standard REST state API as
described in [fleet monitoring](fleet-monitoring.md). A monitoring hub must
never become a remote site's control dependency.
