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
| Learned general limit and direct baseline headroom | Keep their existing separate policy/anti-pause calculations |
| Direct-current writer's live charge-limit min/max/step | Qualify and use one minimum-origin increment for both target and supported upper value |
| Former `NON_OVERRIDE_CHARGE_LIMIT_MAX_PERCENT=90` | Remove; use only the physical percentage-domain bound where a bound is needed |
| Before-export minimum plus recovery buffer | Clip to the existing configured normal target, not a hidden90 cap |
| Dynamic wall-energy shortfall and backfill vehicle room | Use the same corrected normal target, without a second reservation |
| Full/Trip intent | Preserve its independent paid-grid-capable authority and lifecycle |
| Energy, reserve, source, ownership and electrical gates | Preserve at selection, continuation and every positive write |

The normal target determines discretionary charging eligibility. The effective
charge-limit setpoint sent to a connected protected-baseline vehicle may still
include its configured anti-pause headroom. That was already a separate actuator
contract; this correction does not turn off keepalive or invent a stricter cap.
Selecting a normal100% target does not turn on Full, remove house protection or
authorise paid grid energy outside the existing policy.

At the direct write boundary, round the target upward on the actuator's
minimum-origin increment, then cap it to the greatest supported increment no
higher than the live maximum or100%. This corrects inconsistent zero-/minimum-
origin rounding; Full is not an exception. With min50/max100/step7, target95
becomes99, not98; with max96 it becomes92. The native Tessie50–100/step1 case
is unchanged. Command construction and feedback confirmation use the same
calculation, so a valid accepted step cannot create a false retry loop.
This rounding correction is scoped to direct-current reconciliation; the
separate learned/general limit-only writer retains its existing calculation.
The supported native Tessie1% actuator behaves identically in both paths.

## Stability and persistence

No new hysteresis threshold, timer or owner is added. Existing buffered minimum
recovery, solar/budget continuation, stop boundaries and persistent handoff state
remain authoritative. A target edit is read through existing runtime configuration;
restart/reconnect must still requalify sources and current energy authority.
Headroom and a valid target never delay a safety stop or revive an expired intent.

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
