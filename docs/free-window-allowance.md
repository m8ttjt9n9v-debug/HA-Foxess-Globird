# Measured free-window allowance (unreleased)

Automatic free charging uses the configured clock window while today's
free-window import is below the configured daily allowance. With EV priority,
the retained current planner requests the configured maximum up to the normal
charge limit. House-battery deficit, future EV needs and remaining window
duration no longer create an EV pacing ceiling or reserve a future allocation.
A late-arriving vehicle receives only the allowance still available.

When allowance protection is enabled and the counter reaches the allowance,
EV control takes the existing outside-window route immediately, including
during an unfinished ramp or before the normal decision cadence. Ordinary
solar spill/soak, backfill, protected baseline/stop and charge limits retain
their existing selection and qualification. Exhaustion does not grant paid
grid charging. The explicit Charge to Full override remains independently
available, with its existing time, current, source and charging protections.

The independently commissioned battery charging extension already ends Force
Charge at exhaustion and restores Self Use through its existing persisted
session. No new FoxESS writer, EV allocation controller, forecast or delay is
introduced. FoxCloud ownership still prohibits HEO from changing inverter mode;
an unrelated cloud schedule cannot be stopped by this EV setting.

## Provenance and changed extension

| Source input/decision | Retained implementation or explicit correction |
| --- | --- |
| Canonical v1.4.24 free-window current target, EV-priority branch | Retain maximum-current request and the preceding service-limit correction in `plan_free_window_current`. |
| Canonical configured time, priority, charge ceiling and physical current bounds | Retain configured values, half-open clock window, normal ceiling, matched feedback and one EV writer. |
| Later HEO forecast allowance extension | Replace battery-first deficit/EV-need pacing with measured remaining allowance eligibility. This is an explicitly requested correction to that extension, not a replacement for the canonical current algorithm. |
| Existing `WindowImportAccumulator` and version-one private Store | Retain the counter, local accounting-day reset, bounded integration gaps and payload. Save the first allowance crossing even below the ordinary checkpoint increment. |
| Existing outside-window route and solar-soak journal | Reuse them after exhaustion; preserve limits, source clocks, reserves, cadence, pending intent and cleanup. |
| Existing explicit Charge to Full | Keep its independent paid override; it does not reset or replenish metered allowance. |
| Existing Local Modbus battery charge session | Retain its exhaustion finish, Self Use sequence, persistence and exclusive owner. |

The actual tariff clock and daily import accounting stay active after free
charging eligibility ends. Further imports, including explicit paid overrides
and household use, remain counted. House learning still excludes the real
clock window; this change does not redefine learning cycles or future windows.

## Stability, lifecycle and safety

The daily counter integrates only non-negative import and does not subtract
export. It cannot oscillate around the cutoff as SoC or power jitters; a
single exact energy boundary therefore suffices. No arbitrary hysteresis,
time delay or future-energy buffer is added. Same-day restored exhaustion
remains exhausted. The next accounting day resets the existing counter;
an explicit allowance increase or protection opt-out is a new user setting,
not an automatic rearm. Unknown, non-finite, future or wrong-day counter
evidence cannot grant free EV charging.

An old free-EV plan rechecks allowance after awaited command/checkpoint
boundaries. It cannot start or retry a positive free target after exhaustion.
Outside-policy reductions and the explicit Full override retain their existing
authority. Safety Lock, commissioning, source/current qualification, service
and inverter limits, normal charge ceiling, reserve calculations, export
handoff and ownership checks are unchanged.

This is a charging cutoff based on HEO's observed grid-power integral, not a
guarantee about a retailer's settlement meter. Sampling/command delay, a
configured protected baseline and uncontrolled household or external charging
can still produce overage. Self Use does not guarantee zero grid import when
house demand exceeds available solar and battery output.

## Settings and compatibility

The existing `ev_allowance_guard_enabled` key, default and explicit opt-out are
preserved. Setup labels now describe ending free charging at the used daily
allowance. The obsolete forecast-only margin is removed from setup; its saved
key/value remains supported for round-trip and rollback, without affecting the
new measured cutoff. Frozen configuration contracts remain unchanged; exact
reviewed field retirement, label and boundary-access amendments characterize
the current surface. No installed dashboard, settings or registered identity
is rewritten by this repository work.

Regression coverage includes below/at/above configurable allowances, missing
projection inputs, delayed ramps, command-boundary expiry, solar soak and its
reserve stop, explicit Full/cancellation, unknown counters, restart/solar
jitter/daily reset, physical-current gates and Safety Lock. The retained battery
session tests verify exhaustion restores Self Use. All tests use local synthetic
states; no live installation, wake, provider request or release is involved.
