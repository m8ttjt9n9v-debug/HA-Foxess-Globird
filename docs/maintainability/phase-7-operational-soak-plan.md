# Phase 7 operational soak and rollback plan

This plan begins only after independent review accepts correction candidate
`67a5ab71744e5ed670b88faf278f86d3d4d5a490`. It does not authorize a push,
release, deployment, configuration change or live hardware test.

## Entry requirements

- Independent review record says **Accepted**, with no unresolved P0/P1.
- Candidate tests, contracts, boundaries, Ruff and previous-release rehearsal
  remain green at the exact reviewed commit.
- A versioned release candidate and previous known-good package are available.
- Configuration, entity-registry and private Store backups are recoverable.
- The operator has identified an immediate stop path and can restore the
  previous package without changing hardware commissioning.

## Gate 1 — clean staging instance

Install the release candidate without prior HEO state, complete configuration,
restart Home Assistant, reload the entry and then perform a one-version upgrade
and rollback rehearsal.

Pass requires:

- no duplicate or renamed entities and no reclaimed user-owned entity IDs;
- all 107 contracted entities and 125 wizard fields retain their contract;
- no service call while Safety Lock/rehearsal mode is active;
- config and all 13 Store families restore without repair or silent reset;
- downgrade and subsequent re-upgrade retain unfinished obligations without a
  hardware command during setup; and
- diagnostics contain no credentials, tokens, hostnames or site-identifying
  evidence.

Any contract, restoration or unexpected-command failure stops progression.

## Gate 2 — pilot site

Observe one complete relevant operating cycle containing:

- ZEROCHARGE start, active charging and exact end restoration;
- ZEROHERO qualification and its hourly/no-import evidence;
- planned automatic export start, completion and Self Use restoration;
- EV connect/disconnect, target reconciliation and any active outside-window
  stage configured at that site;
- one Home Assistant entry reload during an idle period; and
- the next completed house-learning cycle.

Record timestamps, public HEO states, controller reasons, requested/actual
settings, persistent phase before/after reload and any service-call trace
available through normal diagnostics. Do not add experimental live commands to
manufacture coverage.

Pass requires no paid import attributable to HEO outside configured policy, no
stuck forced mode, no lost restoration obligation, no command flapping, no
entity unavailability beyond mapped-source availability and no unexplained
learning/accounting reset.

## Gate 3 — one remote topology

Repeat the applicable pilot observations on one remote installation with its
existing hardware/configuration differences. The candidate must require no
site-specific code, hidden default or manual Store edit. A remote-only failure
stops progression even when the pilot passes.

## Gate 4 — remaining sites

Roll out one site at a time. Require one complete applicable tariff/control
cycle before proceeding to the next site. Record explicit pass/fail and the
release version for each installation; do not infer success from an online
status alone.

## Immediate rollback triggers

Rollback the affected site to the previous known-good package when any of the
following occurs:

- unintended hardware command or paid import caused by HEO;
- forced charge/discharge mode remains owned after its restoration boundary;
- Safety Lock, ownership or sign gate permits a command;
- persistent obligation disappears or is duplicated after reload/restart;
- EV current repeatedly alternates between incompatible targets;
- entity/configuration/Store compatibility breaks; or
- evidence is insufficient to distinguish safe operation from a stale state.

Before rollback, engage Safety Lock and confirm no command sequence is active.
Preserve sanitized diagnostics and Store backups. Rollback must not delete the
config entry, registry, Recorder history or private storage.

## Soak record

Copy the table for the completed rollout record.

| Gate/site role | Candidate version | Start/end | Required cycles observed | Reload/restart result | Commands/restoration result | Accounting/learning result | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Clean staging | `0.12.29rc2` (local only) | 2026-09-21 | Synthetic observer configuration; no production inputs, EV, actuator mapping or credentials | Core restart, config-entry reload, and recoverable `rc2 → rc1 → rc2` rehearsal retained 107 HEO entities and locked observer settings | Diagnostic actions were refused before adapter access; the expected refusal is now shown as a readable Home Assistant service error | Diagnostics redaction passed. The fresh observer has no non-empty controller Stores; their restoration remains covered by the 974-case deterministic corpus, not this clean-instance observation | **Partial — do not progress to Gate 2 without owner approval** |
| Pilot | | | | | | | Pending |
| Remote topology | | | | | | | Pending |
| Remaining site | | | | | | | Pending |

Final rollout acceptance requires every applicable row to pass and all
exceptions to be resolved or explicitly rejected. Operational acceptance does
not itself authorize Phase 8 scheduling changes; that remains a separate
project-owner safety decision.
