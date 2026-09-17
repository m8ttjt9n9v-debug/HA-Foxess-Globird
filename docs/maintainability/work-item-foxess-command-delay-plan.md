# Work item: FoxESS command-delay plan

## Change

Move the adapter-neutral five-second force-mode settle transformation from the
active controller into the FoxESS command planner.

## Invariants

- Only a charge/discharge power command immediately followed by `select_mode`
  receives the five-second wait.
- Earlier power commands, mode commands and restore-mode delays are unchanged.
- Command order, values, reason, adapter execution and persistence are
  unchanged.

## Verification

- A pure fixture freezes the exact three-command wait sequence.
- Existing active charge/export command-order tests remain authoritative.
- Focused FoxESS planner and lifecycle suite: `77 passed`.
- Full suite: `835 passed`.
- Repository Ruff check passed.
- All ten architecture contracts passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to restore the identical list transformation in the active
controller.
