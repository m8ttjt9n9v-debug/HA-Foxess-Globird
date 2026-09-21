# Phase 7 correction and re-review packet

## Purpose

This packet responds to the rejected independent review recorded in
`phase-7-independent-review-record-4a73017.md`. The rejection remains
authoritative and unchanged. This document does not accept Phase 7; it gives a
fresh-context reviewer the exact correction candidate, finding dispositions,
and corrected review scope.

Implementation correction candidate:
`67a5ab71744e5ed670b88faf278f86d3d4d5a490`.

The documentation commits that add the original review record and this packet
are outside the implementation candidate. No push, release, deployment, or
live-site command is authorized by this packet.

## Scope correction for P1-001

P1-001 was a valid finding against the original packet: that packet described
the entire `4838e51..4a73017` range as behavior- and configuration-preserving,
but the range contained separately approved critical bug fixes.

The `ev_outside_battery_reserve_percent` field and outside-window reserve stop
were introduced by `07153bd` (**Rearm EV current recovery with battery
reserve**). They respond to the confirmed 17–18 September EV-current recovery
incident and the project owner's explicit requirement for a configurable
operating reserve above the inverter hard floor. The public changelog,
configuration contract, work-item history, and regression tests record that
exception. Removing it would reintroduce the confirmed risk of automatic
outside-window EV charging flattening the house battery and causing paid grid
import.

Under `programme-rules.md`, this is a permitted critical-bug exception, not a
Phase 7 refactor. P1-001 therefore requires no production reversion. Re-review
must instead verify both of these propositions:

1. commit `07153bd` is a separately characterized and approved bug correction;
2. the later Phase 7 extraction `2c86327` preserves that already-established
   reserve behavior, configuration key, reason, and paid Charge-to-Full
   exception without further policy change.

The other approved incident corrections inside the broad review range are
`4670469` (unowned retained-current plug-in charging), `8b27c52` (free-window
boundary recalculation), and their maintainability forward ports. They must be
reviewed as named bug exceptions rather than silently treated as refactor
output. All other Phase 7 extraction work remains subject to the original
unchanged-behavior and unchanged-public-contract invariants.

## Correction dispositions

| Finding | Disposition | Regression evidence |
| --- | --- | --- |
| P1-001 | Review-scope defect corrected; no safety behavior removed | Existing reserve configuration, boundary, lifecycle, paid-override, persistence, and extraction tests; re-review required |
| P1-002 | Fixed at the observation boundary: negative and non-finite FoxESS force-power feedback becomes unavailable and drives the existing recovery path without a write | Adapter cases for `-1`, `nan`, `inf`, `-inf`; active-session fail-closed cases for the same values |
| P2-001 | Fixed at the observation boundary: non-finite EV current is invalid rather than `(nan, True)` | EV entity and state-qualified composite snapshot cases |
| P2-002 | Fixed in the pure telemetry boundary: each required timestamp source must be non-empty before coherence can pass; empty provenance returns invalid instead of raising | Grid-empty, battery-empty, and both-empty cases |
| P2-003 | Fixed symmetrically with the EV adapter: FoxESS retains `last_executed` after every successful command, and the active controller records the partial trace and write count before preserving the existing exception behavior | Adapter second-call failure plus active charge-controller partial-write case |

## Verification at the correction candidate

- Full repository suite: `972 passed`.
- Frozen compatibility contracts: `24 passed`.
- Current → `v0.12.26` → current rehearsal: two isolated cases passed.
- Controller boundary contract: passed.
- Persistence boundary contract: passed.
- Ruff over `custom_components`, `tests`, and `scripts`: passed.
- `git diff --check`: passed.

These results prove only their assertions. They do not replace independent
review.

## Required re-review

Use a clean detached checkout at the exact implementation candidate and read
the original rejection before reviewing the corrections:

```bash
git checkout --detach 67a5ab71744e5ed670b88faf278f86d3d4d5a490
test "$(git rev-parse HEAD)" = "67a5ab71744e5ed670b88faf278f86d3d4d5a490"
test -z "$(git status --porcelain)"
pytest -q
pytest -q tests/test_*contract*.py
python -m scripts.previous_release_rehearsal --tag v0.12.26
python scripts/controller_boundary_contract.py --check
python scripts/persistence_boundary_contract.py --check
ruff check custom_components tests scripts
git diff --check 4a73017..67a5ab7
```

The reviewer must inspect the implementation, not only run commands. In
particular, verify that:

- malformed FoxESS power feedback cannot construct an automatic or manual
  observation and an active obligation transitions to existing recovery;
- malformed EV current cannot be marked valid;
- empty solar timestamp provenance is total and fail-closed;
- a later FoxESS service failure retains the exact earlier successful action
  without changing command order, delays, retry state, or exception behavior;
- the P1-001 reserve change is traceable to its approved incident work item and
  the extraction preserves it exactly; and
- no unrelated policy, entity, configuration, persistence, cadence, or Phase 8
  scheduling change entered `4a73017..67a5ab7`.

Record the new decision in a separate re-review record. Do not edit or replace
the original rejected review.
