# Work item: FoxESS EV-presence read boundary

## Problem

The FoxESS export controller retained one direct Home Assistant state read for
the connected-EV keepalive reservation. This bypassed the EV observation
adapter used by the EV controller and left state extraction duplicated across
two runtime controllers.

## Preserved contract

- A commissioned non-zero EV baseline still fails closed when mapped home or
  cable evidence is missing, `unknown`, or `unavailable`.
- Explicit home/on plus cable-on evidence protects the same calculated energy.
- Away or disconnected evidence protects zero energy.
- The legacy comparison remains case-sensitive; this boundary extraction does
  not silently broaden accepted states.
- Battery-only installations remain independent of retained EV fields.

## Change

The final FoxESS-side EV presence read now uses the read-only EV entity adapter.
Policy and energy calculation remain in the FoxESS controller. No controller in
the integration now reads EV entities directly from `hass.states`.

## Verification

- Existing connected, missing-evidence and battery-only tests remain
  authoritative.
- Added characterization freezes lowercase unavailable and legacy
  case-sensitive behavior.
- Focused controller tests, full pytest, Ruff, repository contracts and the
  previous-release rehearsal must pass before local commit.

## Rollback

Revert this commit; no persistence or configuration schema changed.

## Completion evidence

- Focused FoxESS, EV-boundary and lifecycle suite: `99 passed`.
- Full pytest suite: `777 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
