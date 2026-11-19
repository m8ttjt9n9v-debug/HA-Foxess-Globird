# Reliable house-learning collection

This correction changes acquisition of measured house-demand samples. It keeps
the existing left-method energy calculation, seven-sample warm-up, occupied
P80/away fallback, 28 samples over 35 days and remaining-house reserve formula.
Charging, export, source freshness for physical commands and inverter limits
retain their existing authority checks.

## Source mapping and corrected collection

The provenance remains the reference `configuration_v1.4.24.yaml` at commit
`5806b4a5313331fbc421108e9e0c98e661ca20fe`, as mapped in
[house-learning-port.md](house-learning-port.md).

| Reference behaviour | Collection implementation |
| --- | --- |
| Lines 648–672: persistent left-method integrals | Existing demand journal retains qualified partial energy and separately retains raw whole-house progress. Raw energy is diagnostic evidence, never substituted into P80. |
| Lines 1639–1767: separate base/heater boundary samples | Missing base evidence no longer prevents valid heater sampling. Completed cycles are identified by their ending instant to prevent duplicate training. |
| Lines 2400–2531: qualified EV/heater subtraction, zero clamp and free-window exclusion | Keep the subtraction formula; explicitly excluded free hours need no EV or house reading. Unknown protected consumption remains missing, never zero. |
| Lines 537–590: 28 samples over 35 days | Enforce the existing age limit when selecting evidence, including while new collection is stalled. |
| Configured local tariff boundaries | Form boundaries in local time; compare instants and calculate elapsed energy in UTC across clock changes. |

The previous Python collector required an uninterrupted sequence through both
protected and excluded hours. A gap longer than ten minutes during free power
could therefore discard an otherwise complete sample. Excluded intervals now
advance with an unavailable reading, and a restart wholly within those hours
can resume without discarding the protected interval.

The existing ten-minute maximum remains the limit for holding a previous
qualified power reading. Keep its original qualification time separately from
the boundary-processing clock: unavailable reports and restart never renew the
hold. Brief gaps retain the reference left-method behaviour. Split protected
time at the original expiry; later protected consumption is missing. Free hours
do not consume energy or require a future EV reading to close a covered cycle.
Known energy is retained for diagnosis, but an incomplete cycle does not enter
measured history. This is a completeness decision, not a power threshold, so it
introduces no start/stop band, timer or control writer. Held learning evidence
never qualifies live current or an actuator command.

## EV evidence remains separate from physical authority

Fresh positive EV draw continues through the existing native measurement
qualifier. For learning alone, a healthy, bound native frame can establish no
home charging when both the frame and mapped entities explicitly report
disconnected/unplugged, the mapped charge switch is off and no local connection
reports plugged in. A retained numeric current need not settle to zero. The
provider may be online or asleep; its original frame must remain within the
existing configured planning-frame age. SoC is not a learning prerequisite.

Failed, offline, expired, restored, contradictory and rebound evidence remains
unavailable. A connected vehicle with unknown draw is not assigned zero. These
learning-only observations never satisfy a charging or export handoff check.

## Persistence, source changes and diagnostics

The existing version-one demand journal receives additive raw-house progress,
coverage and source-binding fields. Original completed samples and legacy
payloads remain readable. Bind unfinished progress to source identities,
topology, commissioned voltage/phases, sign conventions, time zone and free
window. Changing those inputs starts new progress while preserving completed
history. It cannot splice different sources into one measured cycle.
Compatibility fields prevent an older reader from admitting incomplete
progress or renewing a qualified observation through unavailable reports.

The existing learning-status/sample entities and diagnostics expose the last
completed sample, current raw/base known energy, observed/missing duration and
the last closed cycle's completeness. Partial energy is explicitly separate
from the selected protected budget.

Historical replay can verify collection arithmetic and gap handling. Existing
display-only house/EV history does not establish native provider measurement
time or source health, and is not automatically imported as measured training.
No unqualified cumulative load counter, Tesla lifetime-driving counter or
battery-side charging-session counter is used as home wall energy.

## Qualification

Regression coverage includes complete-data parity, free/protected gaps,
restart/reconnect, incomplete cycles, independent heater data, both daylight
saving transitions, duplicate samples, storage migration/corruption, source
and setting edits, history expiry, retained current while unplugged and
immediate rejection of failed/reconnected sources. Private recorded site
history is replayed locally; public tests use synthetic, sanitised vectors.
