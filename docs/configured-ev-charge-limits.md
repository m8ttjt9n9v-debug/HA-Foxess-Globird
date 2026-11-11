# Configured EV charging targets

## Correction, not a new charging policy

The retained reference capped non-Full direct-EVSE targets at90%, even when its
normal charging target was explicitly configured higher. The operator requested
removal of this conflicting policy.90% remains the existing configurable default;
it is no longer an extra ceiling.100% is the physical percentage-domain maximum,
not a new arbitrary target or an instruction to charge every vehicle to full.

This is an intentional exception to reference parity. It does not replace the
charging algorithm, add another writer or activate any setting.

## Source mapping

| Existing input or boundary | Corrected use |
| --- | --- |
| `ev_free_window_charge_limit_percent`, default90 | Retain the configured normal target, including95/100 where supported |
| Learned general limit and direct baseline headroom | Apply their existing calculations within the configured normal ceiling |
| Direct-current writer's live charge-limit min/max/step | Qualify and use one minimum-origin increment for both target and supported upper value |
| Former `NON_OVERRIDE_CHARGE_LIMIT_MAX_PERCENT=90` | Use the site's configured normal ceiling, with the explicit Full/Trip override |
| Before-export minimum plus recovery buffer | Clip to the existing configured normal target, not a hidden90 cap |
| Dynamic wall-energy shortfall and backfill vehicle room | Use the same corrected normal target, without a second reservation |
| Full/Trip intent | Preserve its independent paid-grid-capable authority and lifecycle |
| Energy, reserve, source, ownership and electrical gates | Preserve at selection, continuation and every positive write |

The normal target determines discretionary charging eligibility and caps the
effective charge-limit setpoint, including connected keepalive headroom. The
controller skips ordinary starts at the effective limit. A configured 100%
normal target uses ordinary charging authority. Full and Trip retain their
separate override authority.

At the direct write boundary, round the target upward on the actuator's
minimum-origin increment, then cap it to the greatest supported increment no
higher than the configured ceiling and live actuator maximum. Full and Trip
use the live maximum up to 100%. With a minimum of 50, a step of 7, and a
ceiling of 90, the highest supported value is 85. Direct reconciliation and
the learned/general limit writer share this calculation. The command adapter
rechecks the ceiling before dispatch if settings or override state change.

## Stability and persistence

The charge ceiling is a hard upper bound at every measured SoC. The existing
retry intervals bound repeated requests during unsettled feedback. Restart and
reconnect requalify sources and current energy authority. A lower configured
ceiling also bounds a target retained in the retry journal.

## Regression and compatibility contract

- Exercise configured80/90/95/100 with Full off, and below/at/above each target.
- Cover retained limit, startup, target edits, reload/restart and Full/Trip handoff.
- Cover backfill, morning/afternoon surplus, minimum recovery and Dynamic shortfall
  calculations above90, while respecting lower configured normal targets.
- Check live actuator maxima, awkward steps, missing/non-finite metadata, zero
  budget, reserve/source loss, import limits and Safety Lock without weakening
  their existing expectations.
- Keep all storage schemas, default values and raw saved settings unchanged.
  Previous-release upgrade/rollback rehearsals remain required; no deployed
  dashboard rewrite, provider poll or live test event is part of repository tests.

This work is unreleased. Public publication and any further site deployment are
deliberately held during the owner's settling period and require fresh direction.
