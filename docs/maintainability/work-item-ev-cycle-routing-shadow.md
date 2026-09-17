# Work item: EV cycle routing shadow

## Problem

The active EV controller mixes two different routing decisions around the
Charge-to-Full lifecycle update: connection/feedback eligibility first, then
free-window, outside-policy or general-limit routing. Combining them prematurely
would change when a completed Charge-to-Full request is cleared.

## Change

Extract two pure route selectors and run both in shadow:

1. eligibility route: blocked, disconnected smart-socket cleanup, or eligible;
2. policy route: free-window, outside-window policy, or general-limit only.

The retained controller branches remain authoritative. Splitting the decision
at the existing lifecycle boundary preserves evaluation timing exactly.

## Invariants

- Disconnected smart-socket cleanup still requires mapped actuator feedback and
  active home-control scope.
- Missing actuator feedback blocks a connected vehicle.
- The free window wins over any retained outside-control state.
- Outside stop/recovery ownership wins over general-limit-only handling.
- No lifecycle, target, persistence, command or public-contract changes.

## Verification

- Pure collision tables cover disconnected cleanup, missing feedback, free plus
  outside activity, outside stop ownership and general-limit fallback.
- Existing live free-window, general-limit, solar-spill and disconnected socket
  scenarios assert the shadow route.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this shadow-only routing commit; retained branches remain untouched.

## Completion evidence

- Focused cycle-routing, EV and lifecycle suite: `174 passed`.
- Full pytest suite: `805 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
