# Maintainability programme rules

These rules govern the optimisation and maintainability programme. They apply
until the project owner explicitly ends the functionality freeze.

## Functionality freeze

- Do not add features or expand controller authority.
- Record enhancement ideas without implementation.
- Correct confirmed bugs only after a regression reproduces the failure.
- Do not combine a bug fix, behavioural change and structural refactor.
- Solar-forecast planning remains specification-only during the freeze.

## Change discipline

- Preserve the source-of-truth and port-first rules.
- Characterise observable behaviour before moving or restructuring it.
- Change one architectural seam per work item and release.
- Keep `main` releasable and use a dedicated maintenance branch.
- Treat entity IDs, unique IDs, state values, public attributes, configuration
  keys and stored payloads as compatibility contracts.
- Do not delete apparent dead code until callers, persisted state, dashboards,
  automations, migrations and downgrade requirements have been checked.
- Do not optimise for line count or CPU use. Optimise for one source of truth,
  bounded responsibility and small change blast radius.

## Work-item requirements

Every implementation item must identify:

1. the concrete problem and evidence;
2. the current observable contract;
3. invariants and explicit non-goals;
4. compatibility and persistence consequences;
5. characterisation and lifecycle tests;
6. rollback method; and
7. acceptance evidence.

No production change starts while these are unknown.

## Review rules

- Green tests prove only their assertions.
- Controller and persistence changes require an independent, fresh-context
  review of invariants, transitions, restart behaviour and command traces.
- Mechanical inventories and formatting use local scripts rather than model
  reasoning where possible.
- Product terminology, safety policy, compatibility promises and removal of
  historical behaviour require project-owner approval.

## Release rules

- No maintenance release is published merely because a refactor compiles.
- Verify clean install, upgrade, reload, restart and one-version rollback.
- Compare state, attribute, persistence and ordered service-call snapshots.
- Validate on a clean instance, then the pilot site across a complete relevant
  operating cycle, then one remote topology, then remaining sites.
- Retain the previous known-good release and document its storage compatibility.

## Bug exceptions

- **Critical:** unsafe hardware command, unintended paid import, stuck forced
  mode or lost restoration obligation. Fix immediately with a lifecycle
  regression.
- **Important:** incorrect accounting, unavailable contract entity or broken
  learning. Characterise and fix in a narrow release.
- **Cosmetic or enhancement:** record and defer until the freeze ends.
