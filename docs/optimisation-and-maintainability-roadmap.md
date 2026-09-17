# Optimisation and maintainability roadmap

HEO is already operating successfully across multiple sites. This programme
exists to make that working product safe to maintain and scale without
replacing proven behaviour or treating a lower line count as success.

The central problem is duplicated sources of truth. Configuration facts,
runtime state, persistence, controller decisions, entity presentation,
diagnostics, Fleet Summary and documentation can currently describe the same
concept independently. The programme therefore optimises for smaller change
blast radius, explicit contracts and reproducible lifecycle behaviour.

This roadmap is subordinate to the project source of truth and port-first
rules. Control behaviour remains governed by the proven implementation and its
characterisation tests. Refactoring does not authorise a new control algorithm.

## Outcomes

The completed architecture has:

- one reviewed vocabulary and contract for every exposed entity and public
  attribute;
- typed configuration parsed once at the Home Assistant boundary;
- one canonical read model for entities, diagnostics, dashboards and Fleet
  Summary;
- Home Assistant state access isolated to telemetry and actuator adapters;
- versioned typed repositories around separate, blast-radius-limited stores;
- one explicit policy-priority decision for each actuator owner;
- one serialized, coalescing reconciliation cycle per config entry;
- every confirmed incident retained as a deterministic lifecycle replay; and
- tested upgrade, rollback and registry compatibility.

Success is measured by fewer sources of truth, fewer unsafe change paths and
clearer public contracts. Production line-count reduction is a possible
consequence, not a target.

## Baseline and immediate risks

The v0.12.26 surface contains 107 Home Assistant entities: 92 sensors, six
switches, four numbers, three buttons, one binary sensor and one select. The
public surface mixes physical measurements, normalised measurements,
accumulators, forecasts, plans, command targets, actuator settings, session
states, learning outputs and retailer results without one enforced vocabulary.

The largest implementation concentrations are the EV runtime, configuration
flow, coordinator and sensor presentation. Configuration is repeatedly read as
an untyped mapping; the coordinator combines acquisition, accumulation,
accounting, learning, persistence and scheduling; the EV controller combines
policy selection, lifecycle state and command execution; and sensor
presentation recalculates concepts that should come from one canonical read
model.

Before naming work, stop platform setup from forcing a user-renamed entity ID
back to HEO's preferred object ID. Entity IDs become user-owned after
registration and must not be silently reclaimed on reload.

## Non-negotiable compatibility contract

- Preserve current unique IDs unless an explicit, tested migration is approved.
- Treat existing entity IDs, public attributes and machine state values as APIs.
- Preserve user names, user-renamed entity IDs, areas, labels, visibility and
  enabled state.
- Preserve serialized configuration keys unless a versioned semantic migration
  is required; do not rename persisted keys merely for style.
- Never rewrite user dashboards, templates or automations automatically.
- Version Fleet Summary independently and retain compatibility readers when its
  public attribute schema changes.
- Do not replace cumulative-energy entities without deciding how Recorder
  statistics and long-term history will be preserved.
- Keep justified legacy aliases through at least two minor releases and 90 days;
  low-cost aliases used by existing installations should preferably remain
  through 1.0 or indefinitely.
- Keep charge, export, manual-diagnostic and EV state machines distinct where
  their safety and restoration obligations differ.
- Keep stores separate. Shared repository infrastructure must not create one
  omnibus state payload.

## Approved terminology

Entity and configuration names use:

> scope + quantity or action + period or window + provenance or stage

The words below have precise meanings:

- **ZEROCHARGE**: GloBird's free off-peak import allowance and window.
- **ZEROHERO**: GloBird's daily credit for avoiding grid import during its
  qualifying window.
- **Solar/Generation Feed-in**: the applicable base export payment.
- **Super Export top-up**: an additional export payment applied to eligible
  energy.
- **Measured**: a physical observation, not an HEO tariff calculation.
- **Calculated** or **estimated so far**: HEO accounting from measured energy
  and configured rates.
- **Forecast**: a value containing assumptions about future outcomes.
- **Target**: the policy result selected by HEO.
- **Setting**: the value reported by or sent to an actuator.
- **Actual**: a settled external result or a physical observation, identified
  explicitly by context.

Branded terminology is used only where the value directly represents that
tariff or retailer concept. Generic electrical and controller concepts remain
provider-neutral. In particular, automatic battery export is not itself named
ZEROHERO export.

## Delivery programme

### Phase 0 — lifecycle and contract baseline

Estimated effort: 6–10 engineer-days. This is the prerequisite for structural
controller work.

- Complete the lifecycle and incident regression harness defined in the main
  roadmap.
- Capture current entity ID, unique ID, state, attribute and configuration
  serialization contracts.
- Capture ordered service-call and persistence traces.
- Exercise setup, reload, restart and reconfigure at every persisted session
  phase.
- Convert each sanitized confirmed incident into a permanent named fixture.

**Exit gate:** deterministic lifecycle fixtures reproduce existing behaviour;
Safety Lock produces no hardware calls; identical inputs and persisted state
produce identical plans, states and ordered command traces after restart.

### Phase 1 — entity and configuration contract

Estimated effort: 4–7 engineer-days with product-owner terminology review.

Create a machine-readable contract for every exposed entity, public attribute
and persisted configuration field. Each entity record contains:

- stable internal key, unique ID and current entity ID;
- user-facing translation key and approved label;
- one-sentence semantic definition and exact producer;
- semantic role: source, canonical measurement, accumulator, calculation,
  forecast, plan, target, actuator setting, session state, learning output or
  external result;
- unit, sign convention, time basis, availability rule and state vocabulary;
- primary, advanced or diagnostic audience;
- GloBird, FoxESS or Tessie equivalent where one genuinely exists;
- dashboard, automation, documentation and REST consumers; and
- retain, relabel, replace or deprecate decision.

Create contract tests that fail when a new entity lacks a definition, a power
and energy name/unit disagree, forecast/actual/target/setting terminology is
misused, a branded term is inconsistent, or an unexplained duplicate appears.

**Exit gate:** 100% of the public surface is inventoried and the project owner
has approved the glossary and proposed display-name table.

### Phase 2 — compatibility foundation and naming-only release

Estimated effort: 4–6 engineer-days.

- Add a declarative `EntitySpec` catalogue for translation, units, classes,
  categories, default availability, value projection and deprecation metadata.
- Generate entity reference documentation and validate shipped dashboard entity
  references from the catalogue.
- Move hard-coded English names to Home Assistant translation keys.
- Correct display names while preserving entity IDs, unique IDs, state values,
  attributes and all controller decisions.
- Classify low-level averages, retry counters, reconciliation and recovery
  internals as diagnostics. Never silently disable an entity that an upgraded
  installation already has enabled.

**Exit gate:** registry fixtures preserve user customisation and produce no
duplicate entities; the old dashboard and automations continue to work; a
clean-install usability review can identify every primary entity without
reading source code.

### Phase 3 — typed configuration catalogue

Estimated effort: 8–12 engineer-days.

- Define one `FieldSpec` for each persisted field: stable serialized key, type,
  default, selector, page and order, applicability, redaction rule and
  translation key.
- Keep cross-field domain rules as named validators rather than embedding policy
  expressions in metadata.
- Parse the persisted mapping once into immutable nested configuration objects
  for battery, tariff, inverter, grid, house, EV and integrations.
- Generate page composition, defaults and consistency documentation from the
  catalogue while preserving the established multi-page workflow.

**Exit gate:** every persisted key has one catalogue definition; raw config
mapping reads exist only at the configuration and migration boundary; the
existing configuration corpus round-trips with equivalent meaning and invalid
submissions retain the complete draft.

### Phase 4 — canonical read model and presentation

Estimated effort: 6–9 engineer-days.

- Produce one immutable `SiteReadModel` from canonical telemetry, accounting,
  planners and controller state.
- Project individual entities, diagnostics and Fleet Summary from that model.
- Add first-class accounting entities only where a genuine semantic gap exists;
  do not create duplicate calculations merely to obtain prettier entity IDs.
- Keep presentation limited to naming, formatting and availability.

**Exit gate:** individual entities, diagnostics and Fleet Summary cannot report
different values for the same concept in one cycle; presentation contains no
business calculation; snapshots change only where the approved entity contract
requires it.

### Phase 5 — versioned persistence repositories

Estimated effort: 6–8 engineer-days.

- Introduce shared versioned load, validation, fallback, checkpoint and save
  mechanics around separate typed repositories.
- Migrate one state family per pull request: meters, forecast and learning,
  inverter sessions, EV sessions, then manual diagnostics.
- Retain existing storage keys and explicit restoration obligations.

**Exit gate:** old payload fixtures restore identically; corrupt data fails
safely; restart at every phase retains unfinished ownership and recovery work;
rollback boundaries are documented and tested.

### Phase 6 — accounting and coordinator extraction

Estimated effort: 8–12 engineer-days.

Leave the Home Assistant `DataUpdateCoordinator` as a thin platform facade.
Extract telemetry acquisition, meter/accounting, forecasting and house learning
behind immutable inputs and outputs. Do not change scheduling in this phase.

**Exit gate:** the coordinator owns neither domain algorithms nor raw stores;
recorded-day replay produces the same ledger, forecast and learning trace with
no increase in persistence or hardware writes.

### Phase 7 — controller decomposition

Estimated effort: 15–22 engineer-days. This is the highest-risk phase.

- Inverter: separate ownership and gating, free charging, automatic export,
  diagnostics and command execution while preserving distinct session state
  machines.
- EV: separate observation/eligibility, stage candidates, explicit priority
  selection, command reconciliation, recovery, persistence and learning.
- Use an immutable evaluation context containing observation time, values and
  source validity.
- Controllers return command plans; adapters alone call Home Assistant
  services.

**Exit gate:** old and new command plans match in shadow comparison for every
lifecycle fixture; service order, delays, retries, restoration and reason states
are unchanged; controllers directly access neither `hass.states` nor storage.

### Phase 8 — serialized reconciliation and operational rollout

Estimated effort: 5–8 engineer-days plus elapsed soak time.

- Replace overlapping periodic controller loops with one lock-protected,
  coalescing cycle-request mechanism per config entry.
- Preserve state-change and timer triggers, urgent operator actions and Home
  Assistant coordinator semantics.
- Process each cycle in the documented order: acquire, account and learn,
  evaluate inverter, evaluate EV, persist, then publish.

**Exit gate:** at most one command sequence is active; trigger storms coalesce;
tariff and ready-by boundaries are not missed; restart/reload equivalence and
Phase 0 command traces remain intact.

Roll out one seam per release. Validate first on the clean staging instance,
then the pilot site across a complete ZEROCHARGE/ZEROHERO/export cycle including
restart and reload, then one remote topology, and finally the remaining sites.
Keep a known-good tag and verified storage-compatible rollback at every stage.

## Team and sequencing

A practical team is:

- a controls/domain engineer responsible for policy parity and command traces;
- a Home Assistant integration engineer responsible for registry,
  configuration, adapters and presentation;
- a test/reliability engineer responsible for lifecycle replay, persistence,
  compatibility and release evidence; and
- the project owner responsible for product vocabulary, operating priorities
  and acceptance of the public surface.

Phases 0 and 1 can run partly in parallel but both gate deeper refactoring.
Typed configuration and the read model can overlap after the contracts are
approved. Persistence, controller extraction and reconciliation scheduling are
serial safety gates.

The full programme is estimated at 58–86 engineer-days, approximately 7–10
calendar weeks for a focused three-engineer team plus live soak time. A solo
engineer should expect approximately three to four months. These are planning
ranges, not release promises.

## Relationship to feature development

- Safety fixes and narrowly bounded incident corrections continue, each with a
  lifecycle regression.
- Do not mix new control behaviour with a structural refactor in one change.
- A substantial new controller feature must use the emerging typed contracts
  and add lifecycle fixtures rather than extending an old monolithic seam.
- Forecast-solar planning remains valid future product work, but it requires a
  separately approved policy: forecast provenance and confidence, gaps and
  staleness, required reserve, morning-to-ZEROCHARGE timing, failure behaviour,
  and proof that a forecast cannot grant unsafe discharge or paid charging.
  Implement it after the lifecycle baseline and against the extracted planning
  boundary rather than adding it directly to the current coordinator or EV
  runtime.

## Programme-level definition of done

- Every public entity, attribute and configuration field has one approved
  contract.
- Existing installations upgrade with no registry churn or broken automation,
  dashboard, Recorder or Fleet consumer.
- No raw configuration access exists outside configuration/migration code.
- No direct Home Assistant state access exists outside telemetry/adapters.
- No direct store construction exists outside repositories.
- Entities, Fleet Summary and diagnostics share one read-model producer.
- Every actuator has one explicit policy-priority function and owner.
- Each config entry has one serialized reconciliation cycle.
- Every historical incident is a permanent replay fixture.
- One-version rollback has been demonstrated at every migration-bearing stage.

## Explicitly rejected shortcuts

- A big-bang rewrite.
- Measuring success principally by deleted lines.
- A metadata catalogue that attempts to encode cross-field policy.
- One generic state machine for unrelated charge, export, EV and diagnostic
  obligations.
- One combined persistence payload.
- Mass entity-ID or configuration-key renaming for neatness.
- Introducing the single cycle runner before lifecycle evidence and controller
  seams exist.
- Removing diagnostic reason states merely to make the public surface smaller.
