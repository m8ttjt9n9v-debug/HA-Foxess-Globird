# Direct-EVSE retry episodes

This is a local, unreleased reliability refinement. It does not change energy
allocation, inverter limits, normal charging targets or physical export handoff.
It does not identify which external component caused a current mismatch.

## Provenance and scope

| Retained source behavior | HEO implementation / refinement |
| --- | --- |
| Direct charging stages a charge limit, then current, then start | Existing `plan_direct_evse_commands` and ordered service adapter retain that order. Across cycles, an unstaged prerequisite still blocks an increase/start. |
| Requested-current mismatch uses native writable steps | Existing effective targets and step comparisons are retained. A sub-step discrepancy does not invent a writable command. |
| Nonzero protected baseline is not a pause | Existing baseline/stop selection is unchanged. The explicit-zero stop retains its separate persistent journal. |
| Current feedback may arrive after an optimistic command echo | Only qualified, source-bound native measurements after a completed current action can establish a settled current episode. A service receipt is not vehicle acknowledgement. |
| Existing progressive retries survive restart | Current, percentage-limit and start retain independent clocks in the existing composite EV journal. Percentage edits no longer reset the current clock. |
| Safety and energy authority can expire during awaited work | Existing controller lock, checkpoints, per-command gates and reducing cleanup remain authoritative. Retry state grants no charging/export authority. |
| Automatic export requires physical EV handoff | The export controller is unchanged. Requested baseline with actual current above baseline continues to withhold forced export, irrespective of retry success or an earned repair token. |

The source policy remains the retained pilot's direct-EVSE staging and protected
baseline. Action-specific timing and measured one-shot recovery are a separately
tested reconciliation refinement, not a replacement energy algorithm or a new
writer. No tariff, SoC, energy buffer or site-specific current is added.

## State transitions and noise

Each action retains the established progressive intervals: 30 seconds, then
1, 2, 4, 8, 16 and at most 30 minutes. A different effective current target
starts its own current episode; a percentage-only edit does not. The current
episode uses the bounded target and native minimum/step, not unrelated raw
configuration values. Safety curtailment and new policy targets are not held
behind an old episode's cooldown.

An already issued current can earn one prompt corrective retry after advancing
native requested/actual measurements agree with the target for at least the
existing 30-second feedback-settling interval. The original provider timestamp,
same source binding, current-action completion time and existing configured EV
telemetry age limit are required. Repeated reports of one old frame, optimistic
number echoes, limit edits, service success and missing evidence cannot earn it.
Actual current must be at or below target; the existing writable step governs
whether a later mismatch merits another command.

A genuinely newer over-target frame can consume that earned recovery once.
Unresolved repeated mismatches then return to progressive backoff; they do not
continuously reset it. This separates settling from release without adding an
arbitrary charging hold, extra energy margin or relaxed physical-current gate.
The settling interval qualifies evidence only: no emergency or authority
withdrawal waits for it.

## Persistence, startup and reconnect

The existing version-1 EV Store gains optional `reconciliation.retry_channels`
fields. Legacy aggregate timing remains present for conservative downgrade.
Legacy/ambiguous journals retain their cooldown but do not acquire a physical
acknowledgement. Invalid optional proof loses eligibility without clearing
unrelated stop, energy-session or recovery duties. Provider clocks and earned
span chronology are validated on restore; reload does not renew them.

Planned intent is checkpointed before dispatch. Only an actually completed
current action receives a completion receipt, timestamped after its awaited
service. The post-command checkpoint uses a sufficiently recent real clock.
Timeouts and interrupted delivery cannot manufacture successful completion.
After a known ordered-prefix outcome, actions proven never invoked regain
their prior action-specific clock; an earlier failed limit cannot penalise an
unsent current/start. An invoked timeout keeps its cooldown. A crash before
that outcome checkpoint conservatively retains all planned attempts; the
ephemeral refund evidence is not restored from storage.
Supervisor repair takes the existing owner lock and re-evaluates without
resetting a pending retry episode.

A positively qualified disconnect clears current acknowledgement eligibility;
ordinary startup uncertainty is not treated as a clean disconnect. Existing
owner/stop guards still decide whether the entire obsolete episode can retire.
Connected-off/start handling remains separate from current and percentage
attempts. A qualified connected stop retains only the prior same-source current
receipt, discarding earned running proof; advancing post-start measurements
must establish a new full dwell. No start action is misrepresented as a
completed current action.

## Verification boundaries

Pure planner/codec, adapter and Home Assistant lifecycle tests cover independent
clocks, noisy/sub-step current, advancing/frozen source clocks, percentage edits,
partial dispatch, service failure, restart, start/reconnect and supervisor races.
Joint native EV/export tests retain the negative requested-baseline/actual-above-
baseline case through reload and both controller orderings, plus a genuinely
qualified positive handoff. These are local regressions, not proof that a remote
vehicle will accept a command, nor evidence that historical export would have
occurred. Deployment and release require separate approval.
