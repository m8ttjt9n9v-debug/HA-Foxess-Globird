# EV-before-export protected top-up

## Authority and problem

Explicit owner approval authorises this scoped exception to the functionality
freeze: implement/test/release EV-before-export charging and pilot installation.
The paid-export daily-cap clarification remains deferred. The existing opt-in
only withholds automatic export; it does not transfer withheld energy to the EV.

## Source mapping and invariants

| Existing source | Extension |
| --- | --- |
| EV-before-export switch and inclusive SoC target | Same request/target; below target may request a top-up |
| ExportPlan Sellable energy | Budget before daily cap/window clipping, never hidden planned export |
| Battery floor/reserve, learned house and protected EV deductions | Retained exactly once; recheck current qualified energy |
| Outside EV service/connector/inverter-percent envelope | Same total-power ceiling, minimum and supported step |
| Existing EV writer and outside ownership/stop journal | Same single writer, retry/cleanup and persistence |
| Existing export session and Self Use cleanup | Top-up waits for idle/zero force feedback; export waits for EV baseline |

Free power and Full/Trip retain authority. An already-active daily-ready session
is not stolen; inactive daily-ready cannot acquire/credit a top-up. No solar or
ready-by/latest-start condition is added. Missing/stale energy or physical
evidence, exhausted budget, reserve and target crossings withdraw top-up.
Normal 90% ceiling and configured lower soft limit remain. The existing opt-in
being off preserves prior behaviour. This does not promise retailer payment or
eliminate physical/polling transients. No new device writer or stored schema.

Direct Tessie only: the smart-socket controller's historical no-pause path lacks
the general stop capability this top-up needs. Its independent policies remain
unchanged, with no new top-up authority in this release.

## Lifecycle, compatibility and acceptance

Restart re-evaluates live eligibility and protected energy; old positive intent
is not permission. Existing outside ownership persists stop responsibility.
At target the EV first reduces to baseline/off; independent export callbacks
require fresh physical baseline feedback, including before EV startup restore.
Manual/diagnostic owners and active charge/export cleanup cannot be adopted.
No threshold deficit is added to the protection ledger a second time.

Tests cover enable/disable, 0/1A baseline, no solar, different times/topologies,
cap-exhausted but Sellable-positive cases, minimum/tiny/shrinking energy, stale
sources, source loss, home/cable, reserve/target/90% boundaries, daily and Full/
free collisions, both callback orders, restart and saving/command failures.
Frozen suite, Ruff, previous-release upgrade/rollback and independent review
are required before release. Controlled pilot preserves settings and dashboards,
uses a recoverable backup and one idle-time restart, and does not manufacture
EV/inverter commands or activate policies. No other site is authorised.

Rollback installs the previous released code with unchanged payloads/settings;
the opt-in returns to export-withholding only. Runtime acceptance is distinct
from observing a complete natural top-up/export cycle.

## Local acceptance

- Final frozen suite:3,601 passed, including100 new runtime/handoff cases.
- Repository Ruff/diff checks and v0.12.50/v0.12.26 upgrade/rollback rehearsals
  passed. Clean setup, reload, restart and unchanged storage contracts run in
  the full suite; no new schema migration exists.
- Independent fresh review found live-cutoff, restored/missing actuator and
  unsupported smart-path gaps; corrected code passed195 focused cases plus
  six independent reproductions. The added permanent regressions cover those
  findings and live keepalive protection, including between-service changes.
- Publication, pilot startup and a complete natural top-up/export cycle are
  separate; local tests are not physical acceptance or retailer payment proof.
