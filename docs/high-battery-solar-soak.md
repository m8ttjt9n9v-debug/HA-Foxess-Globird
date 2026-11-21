# Maximum-rate solar soak (unreleased)

This optional extension lets a nearly full house battery buffer changing solar
while the EV uses the existing outside-window maximum current. It runs inside
the existing direct-EVSE controller and journal; it adds no automation, device
writer, polling loop or independent energy budget.

Enable Solar Spill and **Maximum EV Solar Soak** to select it for the existing
post-free afternoon opportunity. The new switch defaults off, preserving the
averaged solar policy for existing installations. The separate start and stop
controls are available in EV Charging policies and as native dashboard numbers:

| Control | Default | Behaviour |
| --- | --- | --- |
| Maximum Solar Soak Start SoC | 95% | Start only strictly above this house-battery reading, with qualified positive gross solar. |
| Maximum Solar Soak Stop SoC | 90% | Withdraw at or below this reading, or any higher existing outside-window reserve. |

The stop must be below the start. Both accept 0.1 percentage-point steps.
Invalid saved bands cannot enable maximum charging or make a selected maximum
mode fall through to averaged soak.
The legacy averaging window, cadence and buffer floor keep their own values;
they are not repurposed as the new thresholds.

Once started, ordinary solar fluctuations, including a fresh zero-PV reading,
do not replan the request from a moving surplus average. The house battery may
bridge those fluctuations down to the stop threshold. After stopping, the
policy waits until the battery is above the start threshold again. Averaged
soak does not run inside that recovery band while maximum mode is selected;
otherwise it could consume the solar needed to replenish the battery. Other
independently enabled policies keep their existing priority and qualification.

## Provenance and limits

| Retained source or existing policy | Implementation and explicit extension |
| --- | --- |
| Canonical v1.4.24 Tesla Solar Spill Current Target | Preserve its measured reconstruction and legacy planner. Maximum mode is an explicitly selected afternoon extension, not a replacement for pilot arithmetic. |
| Existing post-free direct-EVSE solar-spill ownership | Retain Local Modbus/master authority, Self Use, idle battery sessions, connected/home EV, normal target and higher-policy handoff. |
| Existing outside-window current envelope | Use the commissioned outside-inverter percentage, service headroom, connector maximum, voltage/phases and supported current steps. The extension can only reduce that ceiling. |
| Protected house/EV energy ledger | Keep the reserve formula unchanged. Bound the next existing control interval by both the qualified discretionary pool and battery energy above the stop floor, after discharge efficiency. These are alternative ceilings on the same energy, not two deductions. Future solar does not fund the request. |
| Existing EV persistence and reconciliation | Add an optional bound episode to the same version-one journal, using the existing writer and reducing cleanup. |

No extra site-independent power cap is introduced. Close to the stop floor or
with a small protected pool, the existing next-interval funding bound can reduce
current below the configured maximum. Safety and source qualification take
precedence over holding a stable request.

## Stability and lifecycle

Separate start and stop thresholds are deliberate: jitter around 95% cannot
repeatedly start and cancel a funded request, and recovery through 90–95% does
not repeatedly rearm it. There is no new minimum-duration timer. Reaching the
stop floor, losing valid/coherent native evidence, losing authority or
connection, reaching the EV target, or a higher-priority policy immediately
withdraws this candidate through existing reconciliation. Emergency, disabled
and electrical checks do not wait for the band.

The current import-confirmation setting can retain an already-issued matching
target during a short economic import transient. It cannot start charging,
increase current, retry that positive target, hide a changed vehicle limit or
extend the original deadline. Sustained import withdraws the request. Strict
source, reserve and electrical checks remain separate and immediate.

Recent restart intent is retained only for the same configured sources and
policy, within the existing telemetry age limit, followed by fresh runtime
qualification. Restore never renews the saved observation clock. Expired,
corrupt, rebound or withdrawn episodes require a new start crossing; settings
and source changes invalidate the old episode. Withdrawal is saved even when
the controller exits early, preventing restart from resurrecting old intent.

## Local regression coverage

The planner and actual-controller tests cover below/at/above both thresholds,
jitter, slow drift, cloud dips, delayed EV current, energy near the floor,
configured thresholds and inverter percentages, service/connector limits,
normal charge limits, Full/free-window/before-export handoff, invalid native
timestamps despite fresh HA reports, command-boundary evidence loss, bounded
restart/rebind, persisted withdrawal and import-confirmation expiry/overrides.
Configuration tests exercise both setup and native controls, invalid bands,
legacy option preservation and the reusable dashboard example. Fixtures are
synthetic and remain separate from private operational evidence.

Local tests do not establish live performance or guarantee zero grid import:
physical feedback, sampling and device response remain delayed. This change
does not install, activate or release anything on a site.
