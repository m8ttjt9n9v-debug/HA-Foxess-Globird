# Work item: EV free-window ownership cleanup

## Change

Move free-window entry cleanup of the retained pre-free session and outside
ownership flags into one immutable transition.

## Invariants

- Cleanup occurs only inside the free window while a pre-free session is active.
- Cleanup clears the pre-free session and both outside ownership flags.
- Outside the window, all three retained values are unchanged.
- An inactive pre-free session does not clear unrelated outside ownership.
- The transition adds no save, command, reason or public-state change.

## Verification

- Pure tests cover cleanup, outside-window retention and inactive-session
  retention.
- Existing controller lifecycle and persistence tests remain authoritative.
- Focused outside-state and active-controller suite: `65 passed`.
- Full suite: `825 passed`.
- Repository Ruff check passed.
- All nine architecture contracts passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to restore the identical three assignments in the active
controller.
