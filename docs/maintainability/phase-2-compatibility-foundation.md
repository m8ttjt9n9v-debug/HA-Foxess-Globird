# Phase 2 — compatibility foundation and naming-only release

## Purpose

Phase 2 centralises entity presentation without changing controller behaviour,
entity identity, machine-readable states, public attributes, configuration or
persistence. Runtime catalogue adoption and any display-name change remain
separate reviewable work items.

## Frozen compatibility surface

- Existing unique IDs and default entity IDs remain unchanged.
- User-owned entity IDs, names, areas, labels, visibility and enabled state are
  retained through setup, reload and migration.
- A foreign registry owner keeps an occupied preferred entity ID; HEO receives
  and retains one stable suffixed ID.
- Existing state values, public attributes, services, configuration keys,
  stored payloads and controller decisions remain unchanged.
- Shipped dashboard references must resolve to the frozen entity and attribute
  contracts.
- No entity that is enabled on an upgraded installation is silently disabled.

## Work packages

1. **Registry compatibility evidence**
   - clean setup and reload;
   - user-renamed ID and display customisations;
   - versioned config-entry migration;
   - preferred-ID collision with a foreign owner; and
   - previous-known-good release rollback/downgrade rehearsal.
2. **Dashboard contract**
   - reject duplicate YAML mapping keys;
   - reject unknown portable HEO entity references; and
   - reject undocumented HEO attribute references.
3. **Declarative entity catalogue**
   - one `EntitySpec` per frozen entity key;
   - identity, translation, classification, unit, availability/value projection
     and deprecation metadata; and
   - generation/validation against the frozen identity and semantic contracts.
4. **Translation adoption**
   - preserve identity while moving hard-coded English defaults to translation
     keys;
   - apply only project-owner-approved display labels; and
   - retain a byte-for-byte compatibility report for every other public field.
5. **Naming-only release rehearsal**
   - clean install and upgrade registry snapshots;
   - old shipped dashboard and automation references;
   - HACS, Hassfest, full tests and rollback rehearsal; and
   - no hardware or policy delta in lifecycle traces.

## Current evidence

- Registry setup/reload, migration and collision fixtures pass.
- The portable dashboard is strictly parsed and every HEO entity and attribute
  reference is checked against the frozen v0.12.26 contracts.
- The true previous-release rollback/downgrade rehearsal is still open.
- Runtime `EntitySpec` adoption and translations have not started.
- Nine display-label proposals await project-owner approval; no label is
  inferred as approved from engineering analysis.

## Exit gate

Phase 2 is complete only when the catalogue covers all 107 entities, registry
snapshots show no duplicate or reclaimed entities, the old dashboard still
works, approved labels render on clean installs, upgraded user customisations
remain untouched, and the previous known-good release can read the unchanged
runtime/configuration/persistence surface used by this naming-only release.

## Rollback

Before a naming release, work remains additive and can be reverted without
runtime effect. The release must retain the previous known-good tag and must
not introduce a configuration or storage migration, so rollback restores the
old default presentation without changing operating mode or ownership state.
