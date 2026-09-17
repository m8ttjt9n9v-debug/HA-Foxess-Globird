# Clean-install usability audit — v0.12.26 baseline

This generated report identifies remaining presentation gaps and records
the owner-approved display-name changes. Category and dashboard decisions
remain separate.

## Summary

| Measure | Result |
|---|---:|
| Catalogue entities | 107 |
| Portable dashboard references | 98 |
| Entity translation keys | 0 |
| Proposed relabels awaiting owner review | 0 |
| Owner-approved relabels | 9 |

## Dashboard coverage by reviewed audience

| Audience | Total | Referenced | Not referenced |
|---|---:|---:|---:|
| primary | 46 | 44 | 2 |
| advanced | 34 | 29 | 5 |
| diagnostic | 27 | 25 | 2 |

Dashboard absence is audit evidence, not automatically a defect: Fleet,
site overlays and deliberately advanced entities may be consumed elsewhere.
The two primary omissions require a presentation decision before change.

### Primary entities not referenced by the portable dashboard

| Entity ID | Current name |
|---|---|
| `sensor.home_energy_measured_net_cost` | Measured Net Cost Today |
| `sensor.home_energy_globird_yesterday_actual_cost` | Actual Cost for Latest GloBird Day |

## Category evidence

Current categories: `{'none': 98, 'config': 8, 'diagnostic': 1}`.

The semantic review marks the following entities as diagnostic audience,
but Home Assistant does not currently classify them as Diagnostic. This is
a review list, not approval to change upgraded installations.

| Entity ID | Current name | Current category |
|---|---|---|
| `sensor.home_energy_ev_grid_current_average` | EV Controller Grid Current Average | none |
| `sensor.home_energy_ev_actual_current_average` | EV Actual Current Average | none |
| `sensor.home_energy_ev_reconciliation_attempts` | EV Reconciliation Attempts | none |
| `sensor.home_energy_ev_smart_socket_recovery_status` | EV Smart Socket Recovery Status | none |
| `sensor.home_energy_ev_solar_spill_surplus` | EV Reconstructed Solar Spill | none |
| `sensor.home_energy_ev_driving_learning_samples` | EV Driving Learning Samples | none |
| `sensor.home_energy_forecast_export_realisation` | Forecast Export Realisation | none |
| `sensor.home_energy_forecast_scorecard_status` | Forecast Scorecard Status | none |
| `sensor.home_energy_free_charge_completion` | Free-Window Battery Charge Status | none |
| `sensor.home_energy_bonus_zero_import_allowed` | ZEROHERO Local Telemetry Qualified | none |
| `sensor.home_energy_tariff_status` | Tariff Guard Status | none |
| `sensor.home_energy_learning_samples` | House Learning Samples | none |
| `sensor.home_energy_learning_status` | House Learning Status | none |
| `sensor.home_energy_heater_learning_samples` | Heater Learning Samples | none |
| `sensor.home_energy_test_charge_estimated_cost` | Test Charge Estimated Cost | none |
| `sensor.home_energy_test_charge_import_rate` | Test Charge Import Rate | none |
| `sensor.home_energy_test_discharge_estimated_earning` | Test Discharge Estimated Earning | none |
| `sensor.home_energy_test_discharge_export_rate` | Test Discharge Export Rate | none |
| `sensor.home_energy_test_status` | Test Status | none |
| `sensor.home_energy_test_remaining_minutes` | Test Remaining | none |
| `button.home_energy_test_force_charge` | Start Charge Diagnostic | none |
| `button.home_energy_test_force_discharge` | Start Discharge Diagnostic | none |
| `button.home_energy_test_stop` | Stop Diagnostic and Restore Self Use | none |
| `number.home_energy_test_charge_power` | Test Charge Power | none |
| `number.home_energy_test_discharge_power` | Test Discharge Power | none |
| `number.home_energy_test_duration` | Test Duration | none |

## Remaining Phase 2 decisions

- The nine display-name changes in `terminology-review-v0.12.26.md`
  are owner-approved and implemented in the catalogue.
- Decide whether the two missing primary entities belong on the portable
  dashboard or should be reclassified.
- Review diagnostic-category candidates before registry presentation changes.
- Translation adoption can now begin from the approved English labels.
