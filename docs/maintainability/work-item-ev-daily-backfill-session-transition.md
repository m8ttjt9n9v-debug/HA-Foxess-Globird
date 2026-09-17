# Work item: EV daily-backfill session transition

## Problem

Daily ready-by policy directly mutates session start, live energy authority,
completion and stop-latch fields inside the Home Assistant controller.

## Change

Move the established session start, target shrink and completion rules into one
pure immutable transition over the shared daily-backfill cycle state. The
controller still calculates the existing plan, selects stage priority and
executes commands.

## Invariants

- A session starts only for a positive `charge_now` plan.
- Start freezes the plan time and delivered-energy origin exactly once.
- Live authority can shrink but never expand during an active session.
- Delivered target or retained terminal plan phases end the session and create
  the same fresh stop obligation.
- Energy sampling, retry timing, persistence schema, command order and public
  contracts remain unchanged.

## Verification

- Pure tests cover start, live shrink and terminal completion.
- Existing active-session, sellable-energy and stop lifecycle tests remain
  authoritative.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this commit to restore the identical session mutations in the controller.

## Completion evidence

- Focused session, lifecycle and persistence suite: `78 passed`.
- Full pytest suite: `816 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
