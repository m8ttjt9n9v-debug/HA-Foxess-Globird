# Work item: controller and planner boundary contract

## Change

Add a static contract that prevents both active controllers from bypassing
their observation/service adapters and prevents pure planner modules from
acquiring a Home Assistant dependency.

## Invariants

- Controllers may keep lifecycle timers, adapter calls, repository calls and
  publication responsibilities.
- Controllers may not read `hass.states` or call `hass.services` directly.
- Pure planners may not import Home Assistant or access platform state/service
  attributes.
- No runtime behavior, entity, configuration, persistence or command changes.

## Verification

- The new contract is executable directly and through pytest.
- Focused boundary-contract suite: `3 passed`.
- Full suite: `828 passed`.
- Repository Ruff check passed.
- All ten architecture contracts, including this new guard, passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to remove only the static regression guard; production
runtime code is unchanged.
