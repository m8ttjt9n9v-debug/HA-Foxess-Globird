# Work item: FoxESS EV keepalive reservation

## Change

Move the protected connected-EV baseline eligibility and energy calculation
from the active FoxESS controller into the EV-before-export planner. The
controller remains responsible only for acquiring mapped home/cable evidence
and passing configured values.

## Invariants

- Battery-only and uncommissioned-EV sites reserve zero energy.
- A zero baseline reserves zero energy without requiring presence evidence.
- A non-zero baseline fails closed when home or cable evidence is unavailable.
- Only exact retained home/cable states qualify; case semantics are unchanged.
- Connected energy remains hours × amps × volts × phases, rounded to 0.001 kWh.
- Export eligibility, commands, persistence and public contracts are unchanged.

## Verification

- Pure tests cover connected, unavailable, away, unconfigured and zero-baseline
  cases.
- Existing controller tests retain exact unavailable/case/mapping behavior.
- Focused pure-policy and active-controller suite: `51 passed`.
- Full suite: `834 passed`.
- Repository Ruff check passed.
- All ten architecture contracts passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to restore the identical reservation branches and arithmetic
inside the active controller.
