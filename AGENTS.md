# Repository instructions for coding agents

Before changing control behavior, read these files in order:

1. `docs/source-of-truth.md`
2. `ROADMAP.md`
3. `docs/port-first-development.md`
4. `docs/system-requirements.md`

Before inspecting or changing a live Home Assistant site, also read
`docs/agent-operating-manual.md`.

If a private local operational record is named by the workspace's local agent
instructions, read it too. Never copy its hostnames, addresses, credentials,
or incident evidence into this public repository.

These instructions are mandatory for AI-assisted work in this repository.

## Live-site boundary

A designated pilot HACS site is controlled staging and acceptance
infrastructure, not a scratch environment. Do not alter its Home Assistant
configuration, helpers, switches, integration options, installed component,
or runtime merely to explore, debug, or try an idea. Do not issue FoxESS or EV
commands, restart/reload Home Assistant, or disable automation as a shortcut.

Live mutation requires explicit user authorisation for the named site and
action, together with a task-specific deployment or recovery plan. Read-only
inspection is permitted only when the user's request places that site in scope.
For a normal change, prove the repository build first, then use the controlled
deployment sequence in `docs/agent-operating-manual.md`. An unexpected live
state is evidence to collect and diagnose, not permission to fix forward.

- The proven Working Single Phase Pilot Site configuration is the algorithmic source. Port existing
  behavior first; do not invent a replacement controller because the target
  site has different electrical limits.
- Site differences belong in a configurable extension layer after parity has
  been demonstrated. Never encode site times, phases, current, power, energy,
  service limits, entity IDs, or tariff thresholds as control assumptions.
- Do not infer actuator mappings, topology, vehicle presence, connection state,
  or telemetry freshness. Ambiguity must fail closed.
- A feature is not "ported" until its source decisions and persistent state
  have a traceable mapping and characterization tests cover the same outcomes.
- Safety gates do not prove absence of another writer. Maintain one explicit
  FoxESS owner and preserve service-call/Modbus evidence when investigating.
- Update the source-of-truth and roadmap in the same change as any behavioral
  change. Historical changelog entries remain history; do not present removed
  behavior as current capability.
- Do not change a Home Assistant host clock. Treat direct inverter Modbus
  registers as authoritative when Home Assistant entities are stale.
- Current automatic scope is the verified ZEROHERO export port, the separately
  identified default-off Local Modbus free-charge extension, and independently
  gated Tessie direct/smart-socket paths.
