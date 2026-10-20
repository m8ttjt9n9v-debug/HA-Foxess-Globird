# Paid-export cap correction

## Authority and scope

Owner-approved correction and scoped functionality-freeze exception. Exclude
unpaid solar overflow, retain the controller's existing daily cap and single
writer, and then enter the requested settling-in period. No new price source,
tariff, setting, controller, timer, entity or reward claim. Native tariff and
total physical meters remain untouched.

## Provenance and invariants

| Existing source | Correction |
| --- | --- |
| Canonical import-positive signed grid, bounded daily trapezoid | Same measured positive net export, not requested inverter power |
| Daily total / standard window / independent bonus meters | Unchanged physical and financial reporting |
| Configured base rates/windows and remaining bonus allowance | Positive paid tariff union, each kWh once |
| Original owned price-session phase and absolute permission end | Bounded cap classification only; no admission or deadline extension |
| Independent automatic cap and latest-start/fixed-power session | Shared paid count for ordinary and price paths |
| Existing Self Use reducer and positive-command guard | Exhausted/missing/unsaved paid evidence withdraws; cleanup remains allowed |

The canonical YAML allowance at lines4525–4545 counted its qualified window
meter, not arbitrary zero-rate all-day overflow. HACS's later shared all-day
cap extended that scope incorrectly. A separate minimal paid counter is needed
because arbitrary overlapping tariff/bonus/price opportunities cannot be
recovered by summing the existing independent counters.

## Persistence and lifecycle

One additive private v1 `.paid_export` Store. Old Stores, export session payloads
and public total-export statistics are unchanged. Missing new Store seeds the
upgrade-day legacy total conservatively and saves before admission. Prior price
history cannot be identified reliably; first-day conservation is explicit.
Malformed same-day state stays blocked until next local midnight, not reseeded.
Price provenance is volatile and never restored as control authority. Invalid
measurements break the integration anchor. Counter save failure fences the cap
even if a previous coordinator ledger remains published. Midnight rolls only
the daily meter; switch toggles, new price blocks and reload do not grant energy.

The new native total-export attributes are additive accounting explanation, not
a replacement sensor, live dashboard edit or Fleet schema change. Downgrade
ignores the additive Store and resumes the former conservative all-export cap;
re-upgrade restores the paid Store. No policy activation is performed by install.

## Validation and acceptance

Characterise tariff boundaries, overlap, bonus exhaustion, price expiry, DST,
midnight, migration, corruption, outage, checkpoint failures and retained meters.
Native setup/reload and real writer replays cover no fallback to the physical
meter, normal/price shared cap, active cleanup and late-command revocation.
Full frozen suite, Ruff, v0.12.51/v0.12.26 upgrade/rollback and independent
review precede publication. Published exact-file qualification and backed-up
idle-time pilot restart remain separate from real critical-event delivery and
retailer payment evidence.

## Local acceptance

- Final frozen suite:3,726 passed, including69 pure paid-meter cases,41 real
  export-writer cases and14 native setup/migration/checkpoint cases.
- Ruff, diff/privacy, presentation/storage/config compatibility and v0.12.51/
  v0.12.26 upgrade/rollback rehearsals passed (two cases per release).
- Independent fresh review reproduced subthreshold checkpoint retry/duplicate
  clock and skipped-hour DST gaps. Corrected code has permanent regressions;
  independent targeted and synthetic reproductions pass with no remaining
  reviewed blocker. No live device or retailer delivery was manufactured.
- Stable publication and controlled pilot acceptance remain separate stages.
