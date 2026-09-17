# Work item — core SiteReadModel projection

## Problem

`sensor.py` independently assembled Fleet Summary and individual entity states
from live coordinator objects. Values currently agreed, but there was no type
or contract preventing one presentation path from changing while the other
continued to expose an older interpretation.

## Provenance

| Concept | Authoritative source | Read-model field | Consumers in this seam |
|---|---|---|---|
| Control surface | typed automation config plus FoxESS gate | `orchestrator_status` | Status, Fleet Summary state/attribute |
| Site energy state | canonical snapshot and normalized telemetry | battery, grid, solar and house fields | Individual power/SoC entities, Fleet Summary |
| Export availability | candidate plan plus effective-plan gate | sellable/planned export fields | ZEROHERO plan entities, Fleet Summary |
| Controller state | FoxESS and EV controllers | gate, charge, export and EV status fields | Individual status entities, Fleet Summary |
| Cost outlook | ledger, optimistic forecast and matched scorecard | forecast, measured, actual and error fields | Cost/scorecard entities, Fleet Summary |
| Learning/status summary | house/EV learning and ledger reasons | sample and status fields | Fleet Summary |

## Preserved behavior

- Individual cost states retain two-decimal rounding; raw prior-day scorecard
  states retain their existing precision.
- Fleet numeric attributes retain their existing two- or three-decimal
  rounding and schema version 1 keys.
- The Fleet `last_update` remains a Home Assistant local-time ISO timestamp.
- Sellable energy uses the candidate plan, while planned energy, duration and
  start require the effective export gate.
- Missing controllers, telemetry, plans, forecast and scorecard records retain
  their previous `None`, zero or `unavailable` values.

## Verification

- A frozen-model characterization test covers every projected sensor and Fleet
  key, precision rule and timestamp.
- A withheld-export test proves candidate sellable energy remains visible while
  the effective plan fields are absent.
- Model immutability is enforced.
- Focused read-model, presentation, setup and lifecycle suite: 91 passed.
- The entity and attribute contract extractors follow both the canonical model
  and the remaining `sensor.py` projections, so moving a key cannot make it
  disappear from compatibility coverage.
- Full repository suite: 631 passed.
- Ruff, frozen entity/attribute/configuration/persistence contracts and the
  v0.12.26 previous-release upgrade rehearsal passed.
- `README.md` was not changed.
