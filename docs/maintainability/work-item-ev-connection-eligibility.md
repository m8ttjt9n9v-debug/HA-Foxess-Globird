# Work item: EV connection eligibility

## Change

Move Home / Auto / Away scope and cable/vehicle connection eligibility into
pure EV candidate decisions. The active controller retains ordered acquisition
of only the evidence required by the selected mode and preceding gates.

## Invariants

- Away mode rejects without reading presence, cable or charging evidence.
- Home mode does not require tracker evidence.
- Auto mode accepts only exact `home` or `on` tracker states.
- Cable rejection remains earlier than vehicle charging-state rejection.
- Missing or disconnected vehicle state retains the unavailable reason.
- Public reason strings, cleanup routing, commands and persistence are
  unchanged.

## Verification

- Pure tests cover all location modes and cable-before-vehicle gate order.
- Existing controller mapping, unavailable-state and route tests remain
  authoritative.
- Focused candidate and active-controller suite: `82 passed`.
- Full suite: `842 passed`.
- Repository Ruff check passed.
- All ten architecture contracts passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to restore the identical eligibility branches in the active
controller.
