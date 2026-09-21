# Phase 7.9 — extract EV daily-protection remainder

## Problem and contract

`ActiveEvController.daily_backfill_protection_kwh` still calculates the battery
energy that automatic export must reserve for the next ready cycle. The
formula is small but safety-relevant: configured allocation minus energy
delivered in the same ready cycle, clamped at zero and rounded to 0.001 kWh.

If the retained delivered-energy counter belongs to another ready cycle, none
of it reduces the next cycle's reservation. A disabled zero allocation returns
zero without creating protection. Ready-cycle selection remains in the facade;
the remainder arithmetic belongs in the pure daily-backfill policy.

## Invariants and non-goals

- Preserve same-cycle/new-cycle selection, zero clamp and rounding.
- Preserve the configured value and persisted delivered counter unchanged.
- Do not change export eligibility, planning, persistence or EV charging.
- Do not combine EV keepalive and daily-backfill reservations.

## Test and rollback

Characterize same-cycle delivery, prior-cycle delivery, over-delivery and the
disabled path. Run daily-backfill/export lifecycle, frozen-contract,
previous-release, full-suite and Ruff gates. Reverting the extraction requires
no data or hardware-state migration.

## Acceptance evidence

- Focused daily-backfill, export and keepalive selection: 40 passed.
- Full repository suite: 902 passed in 36.86 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
- `README.md`, public entities, configuration keys, persistence payloads and
  command behavior are unchanged.
- Independent review and the complete Phase 7 exit/rollout gates remain
  separate obligations; this extraction is not authorized for deployment.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [x] Operational soak not required for this side-effect-free extraction
