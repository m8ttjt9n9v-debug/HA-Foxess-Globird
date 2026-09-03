# Changelog

## 0.2.32 — portable dashboard references

- Correct the starter dashboard entity references to the stable integration
  keys introduced in 0.2.31, removing the remaining `Entity not found` cards.

## 0.2.31 — stable portable entity IDs

- Use stable `sensor.home_energy_*` IDs for the dashboard regardless of the
  config-entry display name.
- Migrate an existing entity to its stable ID only when that ID is unused;
  otherwise preserve the existing entity and fail safely.

## 0.2.30 — portable two-column dashboard

- Add mapped battery SOC, solar, house-load, and EV SOC sensors so a dashboard
  can use stable integration entity IDs rather than site-specific source IDs.
- Replace the minimal starter view with generic Overview, EV, and
  Commissioning views using a two-column layout and no personal imagery.
- Keep the dashboard read-only and retain observer-by-default control gates.

## 0.2.29 — visible ZEROHERO hourly import evidence

- Expose a read-only **ZEROHERO Import This Window** sensor.
- Include each local hourly import bucket, accumulator date, last sample, and
  configured hourly threshold as sensor attributes for direct evening review.
- Add the sensor to the importable Lovelace starter and document where to find
  the evidence. No control boundary changes.

## 0.2.28 — guarded EV session commands and dashboard starter

- Start a mapped Tessie/Tessy charge session only when the vehicle is confirmed
  at home, connected, below its mapped charge-limit target, and the planner has
  an active free-window, solar-spill, or pre-window intent.
- Stop only sessions started by this controller when the mapped target is
  reached or the managed window ends; manually/cloud-started sessions are not
  stopped by the integration.
- Keep away, unknown, disconnected, and unavailable states fail-closed.
- Expand the importable Lovelace starter view with tariff, planning, and house-
  learning sensors. HACS still does not install dashboards automatically.
- Add mocked coverage for EV session start/stop and retain the full regression
  suite (135 public-package tests pass).

## 0.2.27 — Tessie solar spill, away bypass, and pre-window backfill

- Add an opt-in Tessie/Tessy current planner for three explicit behaviours:
  free-window allowance charging, post-window solar-spill charging after the
  battery is full, and a modest reserve-aware backfill before the free window.
- Confirm a Tessie/Tessy vehicle tracker is `home` before writing. An away,
  supercharging, unknown, disconnected, or ambiguous vehicle fails closed;
  away vehicles receive no current-limit write.
- Apply the configurable 20%/30% inverter-capacity ceilings only to slower
  load-following sessions. Free-window charging remains governed by the
  import allowance and commissioned electrical ceiling.
- Keep the active boundary narrow: only the explicitly mapped EV current
  number may be written. Tessie charge start/stop, SoC-limit, and FoxESS
  export writers remain outside this release.
- Add regression coverage for away bypass, solar-spill conversion, pre-window
  backfill, unknown presence, and free-window cap semantics (133 tests pass).

## 0.2.26 — gated Tessie current control

- Connect the tested EV current planner and service adapter to the active
  coordinator behind the existing automatic-control and Rehearsal gates.
- Adjust only the explicitly mapped Tessie/Tessy current setpoint during the
  configured free window when local cable and charger-current feedback exists.
- Do not start or stop charging or change the vehicle SoC limit in this
  milestone; unavailable or ambiguous feedback fails closed.

## 0.2.25 — conservative Tessie entity suggestions

- Suggest common Tessie/Tessy EV entities during setup when the installed
  entities produce one clear match (or an exact known ID).
- Leave ambiguous, unavailable, or non-Tessie entities blank so setup never
  silently controls the wrong vehicle.

## 0.2.24 — opt-in FoxESS free-window controller

- Add an explicit automatic-control opt-in and Rehearsal mode interlock to the
  config and reconfigure forms; defaults remain no-write.
- Wire the tested FoxESS free-window charge/restore planner into a 30-second
  coordinator loop only when all three FoxESS actuator mappings are present
  and the interlocks permit control.
- Keep the first active capability narrow: allowance-paced Force Charge and
  reviewed `Backup`/`Self Use` restoration. Tessie/EV and export writers are
  not enabled by this release.
- Expose control-gate state, last control reason/actions, and write count in
  the status sensor attributes for commissioning evidence.
- Add mocked Home Assistant tests covering disabled, rehearsal, and active
  FoxESS paths.

## 0.2.23 — explicit free-window completion modes

- Add a configurable full-battery import threshold (49 kWh by default) to the
  setup and reconfigure forms.
- Add a pure completion policy for the three reviewed outcomes: continue while
  below full, restore `Backup` when full before the threshold, and restore
  `Self Use` at the threshold or once the 50 kWh allowance is exhausted.
- Extend the adapter-neutral FoxESS planner and runtime composition to support
  `Backup` restoration, while retaining the no-write observer boundary.
- Expose the completion recommendation as a read-only sensor and test the
  exact-threshold boundary explicitly.
- Document the evidence and commissioning rule for FoxCloud schedule versus
  local Modbus ownership; no mixed-control behaviour is assumed.

## 0.2.22 — read-only free-window charge target

- Add an optional AC-coupled solar-power mapping to the setup and reconfigure
  forms.
- Expose a read-only **Free-Window Charge Power Target** sensor that combines
  the persisted free-window import allowance, remaining local window time,
  measured house load, measured AC-coupled PV, and the commissioned inverter
  charge limit.
- Keep the target fail-closed: it is unavailable unless the required evidence
  is mapped and valid, and this release still performs no service calls.

## 0.2.21 — normal-mode restoration at zero charge

- Add a pure FoxESS response-reconciliation policy with a retry interval and
  finite attempt limit. It never calls Home Assistant services; active
  coordinator wiring remains gated behind commissioning.
- Reject partial FoxESS or EV actuator mappings at setup time so an active
  coordinator can never receive an incomplete control surface.
- Add a pure export-session state machine covering bounded start retries,
  feedback acceptance, latching, finish restoration, and source-loss recovery.
- Add an allowance-paced battery-charge planner that converts remaining kWh and
  remaining window time into a grid-import target, then accounts for measured
  house load and AC-coupled PV before applying the inverter limit.
- Feed the optional charge plan through the pure runtime composition boundary,
  so the eventual coordinator and reconciliation layer share one bounded
  target calculation.
- Treat an exhausted allowance, finished window, or zero charge target as a
  request to restore normal inverter mode, rather than issuing Force Charge at
  0 kW; Self Use then remains available to soak up solar.

## 0.2.15 — Dashboard entity-ID correction

- Correct the shipped observer dashboard to use the entity IDs generated by
  the integration (`sensor.home_energy_*`).
- Add a regression check so the example cannot silently ship invalid entity
  references.

## 0.2.14 — Explicit actuator mapping groundwork

- Add optional, domain-constrained FoxESS and Tessie actuator mappings to the
  setup and reconfigure flows for future commissioning.
- Validate and redact mapping presence in diagnostics without enabling writes.

## 0.2.13 — Hassfest translation fix

- Place selector option translations at the Home Assistant-supported
  top-level location so Hassfest validates the integration metadata.

## 0.2.12 — Hourly ZEROHERO guard correction

- Evaluate the GloBird ZEROHERO threshold independently for each hourly bucket
  in the 18:00–21:00 window. A single bucket above 0.03 kWh/hour fails the
  guard even when the three-hour sum is below 0.09 kWh.
- Clarify the setup label and tariff-meter documentation to distinguish the
  retailer's hourly condition from the local telemetry debounce.
- Keep the HACS integration observer-only; no hardware-control service calls
  are enabled.

## Unreleased — GloBird FoxESS automation pilot

- Added opt-in, fail-closed FoxESS Modbus free-window charging automation.
- Added opt-in export automation with protected-energy and sustained-import
  guards.
- Added configurable windows, SOC target and command-power limits.
- Kept Tesla vehicle control disabled until a vehicle-current actuator is
  explicitly installed and mapped.
- Recorded the remote H3 commissioning boundary and rollback procedure.
- Added persistent non-free-window house-demand sampling and read-only learning
  sensors to the HACS core.
- Added an automatic EV policy to the YAML pilot: once armed after
  commissioning, a connected vehicle starts in the battery-funded backfill
  window, hands over to free charging, and stops at its target, disconnect, or
  user-configured ready-by time (06:00 default).
- Added explicit FoxESS profile validation plus adapter-neutral, fail-closed
  command planning and mocked service-layer tests; no live HACS writes are
  enabled.
- Added an explicit EV physical phase-count setting (single- or three-phase)
  and phase-aware configured charging-power calculation. Existing entries remain
  single-phase by default until the site is deliberately configured otherwise.
- Added setup choices for the supported EV profiles (single-phase 10/15/32 A or
  three-phase 16 A), plus configurable 6–9 pm and other-paid-period
  load-following ceilings (20% and 30% defaults) and a load-following-preserving
  override. These are policy inputs only until the HACS actuator adapter is
  commissioned.
- Added explicit, configurable bonus-window boundaries (18:00–21:00 defaults)
  so the zero-import policy is a reviewed site setting rather than a hidden
  clock assumption.
- Added explicit site topology plus commissioned service-import, export, and
  inverter charge/discharge limits. Zero means not commissioned and therefore
  cannot silently become an assumed electrical rating.
- Added a pure tariff guard and read-only allowance sensors. A mapped
  cumulative import meter now caps the remaining daily free-energy budget, and
  the bonus guard requires qualified, sustained zero import before it can be
  considered eligible.
- Added a fail-closed EV service adapter and pure runtime safety-state
  evaluator. They are deliberately not connected to the observer entry yet;
  no EV or inverter write is enabled by this release.
- Added a pure runtime composition seam that evaluates tariff, EV and FoxESS
  decisions together before any adapter can be granted write permission.
- Connected the learned protected-house budget to the runtime export plan, so
  learned demand is subtracted before any sellable-energy calculation.

## 0.2.1 — Learning timezone correction

- Use Home Assistant local time when sampling configured site learning windows,
  so Australian 12:01–14:59 windows are not interpreted as UTC.

## 0.2.2 — Remaining learning budget

- Expose the full-cycle house-learning budget scaled to the time remaining
  before the next configured free-power window, with read-only tests.

## 0.2.0 — Observer parity update

- Synced the HACS release tree with measured battery-potential capacity and
  persistent rolling house-demand learning.
- Included tested, adapter-neutral FoxESS planning and response-verification
  primitives while keeping the HACS integration observer-only.

## 0.1.0 — Observer release

- Initial HACS custom-integration package.
- Guided entity mapping with no YAML edits required.
- Normalised, observer-only energy ledger and diagnostics.
- No actuator services are called by this release.
- Added setup, reconfiguration, live-update, unload, and no-service-call tests
  using the Home Assistant test harness.
