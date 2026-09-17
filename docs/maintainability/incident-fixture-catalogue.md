# Incident fixture catalogue

This catalogue connects confirmed operational failure classes to permanent,
sanitized regression evidence. A focused unit or controller regression is
valuable, but does not by itself satisfy the Phase 0 system-lifecycle gate.

Status meanings:

- **System:** covered through Home Assistant setup/lifecycle infrastructure.
- **Focused:** covered at planner, controller or component level; system replay
  remains desirable.
- **Gap:** the exact lifecycle sequence is not yet retained.
- **Open bug:** behaviour remains incorrect and must be fixed separately after
  a failing regression is agreed.

| Incident class | Existing evidence | Status | Required Phase 0 work |
|---|---|---|---|
| Safety Lock with requested automation or persisted diagnostic recovery | `test_rehearsal_mode_is_an_absolute_no_write_gate`; `test_safety_lock_blocks_all_commands_across_reload`; `test_safety_lock_blocks_persisted_manual_restore_on_setup_and_unload` | System | Extend to generated transition sequences |
| Free-window Force Charge recovery after restart | `test_persisted_active_charge_restarts_after_ha_restart_feedback_settles`; `test_active_free_charge_restarts_from_self_use_while_still_eligible`; `test_active_free_charge_is_reasserted_then_adopted_after_reload`; `test_active_charge_ownership_survives_unavailable_feedback_and_reload` | System | Extend the system replay to retry exhaustion and corrupted storage |
| ZEROHERO Force Discharge recovery after restart | export-session persistence/controller tests; `test_active_export_is_reasserted_then_adopted_after_reload`; `test_export_exact_end_restores_self_use_and_clears_on_reload`; `test_active_export_ownership_survives_unavailable_feedback_and_reload` | System | Extend the system replay to retry exhaustion and corrupted storage |
| Completed charge incorrectly adopts another forced mode | `test_completed_charge_session_round_trips_through_ha_storage`; `test_completed_charge_does_not_adopt_external_forced_mode_across_reload` | System | Extend to delayed/unavailable feedback sequences |
| Free-window end restores Self Use | `test_latched_free_charge_restores_self_use_after_window`; `test_free_charge_exact_end_restores_self_use_and_clears_on_reload` | System | Extend to unavailable feedback and bounded retry exhaustion |
| Manual diagnostic loses restoration obligation | `test_restart_restores_a_persisted_unfinished_test`; `test_failed_restore_remains_persisted_for_next_startup`; `test_restore_attempts_are_bounded_and_fault_remains_active`; `test_unfinished_manual_discharge_restores_and_clears_across_reload` | System | Extend to service failure, retry exhaustion and malformed-store system traces |
| Malformed session storage loses ownership evidence | [malformed session storage safety decision](malformed-session-storage.md) | Gap | Implement only after the ownership-unknown behavior and rollback representation are approved |
| Diagnostic/test restoration returns wrong work mode | manual-test restoration tests | Focused | Retain exact start → timeout → clear targets → Self Use trace |
| Reload/reconfigure immediately after a forced session | `test_active_charge_survives_applied_reconfiguration_without_duplicate_write`; `test_active_export_survives_safety_lock_reconfiguration` | System | Extend to charge/export starting, stopping and recovering phases |
| External/unowned forced mode must not be adopted | `test_free_charge_does_not_adopt_an_unlatched_forced_mode`; `test_completed_charge_does_not_adopt_external_forced_mode_across_reload`; `test_active_export_rejects_external_force_charge_across_reload` | System | Extend the active replay to an external transition without a restart boundary |
| Import/export meter stale anchor after reload | `test_accumulator_requests_checkpoint_when_import_ends`; `test_import_to_export_transition_is_checkpointed`; `test_export_to_import_transition_is_checkpointed`; `test_import_anchor_stays_zero_when_export_continues_after_reload`; `test_export_anchor_stays_zero_when_import_continues_after_reload` | System | Extend to stale/unavailable transitions and all tariff-window accumulators |
| Estimated cost rises while continuously exporting | tariff and accounting tests in `test_setup.py` and `test_tariff.py`; `test_gross_cost_stays_constant_during_continuous_export_across_reload` | System | Extend the trace across midnight and tariff boundaries |
| Sellable energy unavailable after allowance reconfigure | independent cap/accounting tests; `test_export_cap_reconfiguration_keeps_sellable_energy_available` | System | Extend the 15 → 20 kWh replay into an active export session |
| Canonical battery telemetry disappears while other sources remain healthy | `test_restart_recovers_from_stale_zero_with_fresh_signed_battery`; telemetry normalization tests; `test_battery_telemetry_recovers_after_delay_outage_and_reload` | System | Extend the outage replay across an active automation safety gate |
| EV current cycles between minimum and maximum | `test_allowance_does_not_cycle_when_whole_house_meter_includes_ev`; transition-hold tests; `test_runtime_does_not_flap_forever_when_feedback_never_changes` | Focused | Replay target, setting and actual-current convergence over timed updates |
| EV policy drains protected house battery | `test_battery_floor_stops_automatic_outside_charge`; sellable-energy shrink/stop tests | Focused | Add full battery/EV/grid timeline with forbidden paid import |
| Vehicle update races current convergence | `test_soc_update_does_not_recalculate_whole_house_allowance_during_current_ramp`; safety-boundary tests | Focused | Move into deterministic state-event replay |
| Sign-verification or owner change during reconfiguration | migration and gate tests | Gap | Reconfigure each gate during idle and active sessions; assert atomic apply |
| Battery-only site retains stale EV reservation | `test_battery_only_site_ignores_retained_ev_baseline` | Focused | Add clean setup and upgraded-entry system snapshots |
| Learning becomes unavailable while valid EV samples remain | confirmed roadmap bug; existing learning arithmetic and restart tests | Open bug | First add disconnected setup/unplug/restart failing regressions; connection gates actuation only |
| House learning loses or duplicates EV/heater subtraction | source-composition tests in `test_setup.py` | Focused | Add multi-cycle persisted sampler replay |
| GloBird scorecard mappings disappear on upgrade | v5 migration and scorecard status tests | Focused | Add full config-entry upgrade/setup/Fleet snapshot |
| User entity IDs are reclaimed on setup | `test_setup_preserves_user_owned_entity_ids_and_names` | System | Expand to upgrade, downgrade and collision fixtures |

## Fixture completion rule

An incident becomes **System** only when the fixture records:

1. exact initial Home Assistant states and timestamps;
2. config-entry data and relevant persisted payloads;
3. ordered input events and lifecycle operations;
4. public state and attribute trace;
5. ordered hardware service-call trace;
6. permitted and forbidden actions; and
7. final owner, mode and outstanding restoration obligation.

Private hostnames, addresses, credentials and identifiable site chronology are
never included.
