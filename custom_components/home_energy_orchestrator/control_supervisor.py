"""Five-minute conformance supervision for commissioned HEO controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .foxess_adapter import FoxessEntityMap
from .foxess_observation_adapter import capture_foxess_feedback
from .planner.control_supervision import (
    ControlSupervisionDecision,
    ControlSupervisionState,
    evaluate_control_supervision,
)

CONTROL_ISSUE_EVENT = "home_energy_orchestrator_control_issue"
SUPERVISION_INTERVAL = timedelta(seconds=30)
SUPERVISION_GRACE = timedelta(minutes=5)

_OWNED_PHASES = frozenset({"starting", "active", "recovering"})


@dataclass(frozen=True, slots=True)
class SupervisionObservation:
    """One facade-neutral expected/actual comparison."""

    issue_key: str | None
    expected: str
    actual: str
    repair_allowed: bool
    detail: str


class ControlConformanceSupervisor:
    """Observe continuously, then repair once and notify after five minutes."""

    def __init__(self, hass: HomeAssistant, coordinator: Any) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._unsub_interval: CALLBACK_TYPE | None = None
        self._battery_state = ControlSupervisionState()
        self._ev_state = ControlSupervisionState()
        self.status = "starting"
        self.issue_code: str | None = None
        self.issue_first_seen_at: datetime | None = None
        self.expected_state: str | None = None
        self.actual_state: str | None = None
        self.last_action: str | None = None
        self.foxess_cloud_verification = "unavailable"

    async def async_start(self) -> None:
        """Start supervision after the primary controllers are available."""
        if self._unsub_interval is None:
            self._unsub_interval = async_track_time_interval(
                self.hass, self._async_tick, SUPERVISION_INTERVAL
            )
        await self.async_reconcile()

    async def async_stop(self) -> None:
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None

    async def _async_tick(self, _now: datetime) -> None:
        await self.async_reconcile()
        self.coordinator.async_update_listeners()

    async def async_reconcile(self, now: datetime | None = None) -> None:
        """Evaluate both channels without becoming a competing fast controller."""
        now = now or dt_util.now()
        battery = self._battery_observation()
        ev = self._ev_observation()
        battery_decision = evaluate_control_supervision(
            self._battery_state,
            now=now,
            issue_key=battery.issue_key,
            repair_allowed=battery.repair_allowed,
            grace=SUPERVISION_GRACE,
        )
        ev_decision = evaluate_control_supervision(
            self._ev_state,
            now=now,
            issue_key=ev.issue_key,
            repair_allowed=ev.repair_allowed,
            grace=SUPERVISION_GRACE,
        )
        self._battery_state = battery_decision.state
        self._ev_state = ev_decision.state

        await self._async_apply("battery", battery, battery_decision, now)
        await self._async_apply("ev", ev, ev_decision, now)
        self._publish_summary(battery, battery_decision, ev, ev_decision)

    def _battery_observation(self) -> SupervisionObservation:
        controller = getattr(self.coordinator, "active_controller", None)
        manual = getattr(self.coordinator, "manual_test", None)
        if (
            controller is None
            or controller.gate_status != "ready"
            or bool(manual is not None and manual.is_active)
        ):
            return SupervisionObservation(
                None,
                "not_supervised",
                "not_supervised",
                False,
                "Battery supervision is gated",
            )
        runtime = self.coordinator.runtime_config
        mapping = runtime.inverter
        if not mapping.actuator_mapping_complete:
            return SupervisionObservation(
                None,
                "not_supervised",
                "unavailable",
                False,
                "FoxESS actuator mapping is incomplete",
            )
        feedback = capture_foxess_feedback(
            self.hass,
            FoxessEntityMap(
                str(mapping.work_mode_entity),
                str(mapping.force_charge_power_entity),
                str(mapping.force_discharge_power_entity),
            ),
        )
        if feedback.observation is None:
            return SupervisionObservation(
                None,
                "available_feedback",
                "unavailable",
                False,
                "FoxESS feedback is unavailable",
            )
        actual = feedback.observation.mode
        if controller.charge_session.phase in _OWNED_PHASES:
            expected = "Force Charge"
        elif controller.export_session.phase in _OWNED_PHASES:
            expected = "Force Discharge"
        else:
            expected = "Self Use"
        if actual == expected:
            return SupervisionObservation(
                None,
                expected,
                actual,
                False,
                "FoxESS mode matches the HEO-owned state",
            )
        if actual == "Force Discharge" and expected != "Force Discharge":
            # There is deliberately no inference here. The local Modbus
            # integration does not expose FoxESS Cloud/VPP event provenance.
            return SupervisionObservation(
                "battery_unattributed_force_discharge",
                expected,
                actual,
                False,
                "External Force Discharge detected; FoxESS Cloud/VPP origin "
                "is not verifiable",
            )
        issue = (
            "battery_free_charge_not_active"
            if expected == "Force Charge"
            else "battery_export_not_active"
            if expected == "Force Discharge"
            else "battery_unexpected_force_charge"
            if actual == "Force Charge"
            else "battery_not_self_use"
        )
        return SupervisionObservation(
            issue,
            expected,
            actual,
            True,
            "FoxESS mode does not match the HEO-owned state",
        )

    def _ev_observation(self) -> SupervisionObservation:
        controller = getattr(self.coordinator, "ev_controller", None)
        if controller is None:
            return SupervisionObservation(
                None, "not_supervised", "not_supervised", False, "EV controller unavailable"
            )
        if (
            controller.gate_status in {"ready", "safety_locked"}
            and getattr(controller, "multiphase_feedback_unavailable", False)
            and getattr(getattr(controller, "eligibility_route", None), "route", None)
            == "eligible"
            and controller.charge_switch_on is True
        ):
            return SupervisionObservation(
                "ev_current_feedback_unavailable_charging",
                "No charging without commissioned phase-current feedback",
                f"Charge switch on; requested {controller.requested_current_a} A",
                False,
                "EV charging remains on while service-phase current is unavailable",
            )
        if controller.gate_status != "ready":
            return SupervisionObservation(
                None,
                "not_supervised",
                "not_supervised",
                False,
                "EV supervision is gated",
            )
        target = controller.target_current_a
        requested = controller.requested_current_a
        if target is None or requested is None or controller.policy_route is None:
            return SupervisionObservation(
                None,
                "available_feedback",
                "unavailable",
                False,
                "No active EV target is owned by HEO",
            )
        target_on = target > 0
        switch_matches = controller.charge_switch_on is target_on
        current_matches = abs(requested - target) <= 0.25
        expected = f"{target:.1f} A; charge {'on' if target_on else 'off'}"
        actual = (
            f"{requested:.1f} A; charge "
            f"{'on' if controller.charge_switch_on else 'off'}"
        )
        if current_matches and switch_matches:
            return SupervisionObservation(
                None,
                expected,
                actual,
                False,
                "EV request matches the HEO target",
            )
        return SupervisionObservation(
            "ev_target_not_applied",
            expected,
            actual,
            True,
            "The EV current or charge switch does not match HEO's current target",
        )

    async def _async_apply(
        self,
        component: str,
        observation: SupervisionObservation,
        decision: ControlSupervisionDecision,
        now: datetime,
    ) -> None:
        if decision.should_repair:
            if component == "battery":
                await self.coordinator.active_controller.async_supervisory_repair(
                    observation.expected
                )
            else:
                await self.coordinator.ev_controller.async_supervisory_repair(now)
            self.last_action = f"repair_requested:{observation.issue_key}"
        if decision.should_notify:
            self._publish_event(component, observation, "issue")
        if decision.recovered_issue is not None:
            recovered = SupervisionObservation(
                decision.recovered_issue,
                observation.expected,
                observation.actual,
                False,
                "Control feedback has returned to the expected state",
            )
            self._publish_event(component, recovered, "recovered")

    def _publish_event(
        self,
        component: str,
        observation: SupervisionObservation,
        status: str,
    ) -> None:
        issue = observation.issue_key or "control_conformance"
        title = "HEO control issue" if status == "issue" else "HEO control recovered"
        message = (
            f"{component.title()}: expected {observation.expected}; observed "
            f"{observation.actual}. {observation.detail}"
        )
        data = {
            "status": status,
            "component": component,
            "issue": issue,
            "title": title,
            "message": message,
            "expected": observation.expected,
            "actual": observation.actual,
            "foxess_cloud_verification": self.foxess_cloud_verification,
        }
        self.hass.bus.async_fire(CONTROL_ISSUE_EVENT, data)
        notification_id = f"heo_{self.coordinator.entry_id}_control_{component}"
        if status == "issue":
            persistent_notification.async_create(
                self.hass, message, title, notification_id
            )
        else:
            persistent_notification.async_dismiss(self.hass, notification_id)

    def _publish_summary(
        self,
        battery: SupervisionObservation,
        battery_decision: ControlSupervisionDecision,
        ev: SupervisionObservation,
        ev_decision: ControlSupervisionDecision,
    ) -> None:
        ranked = {"healthy": 0, "pending": 1, "issue": 2}
        if ranked[battery_decision.status] >= ranked[ev_decision.status]:
            selected, decision = battery, battery_decision
        else:
            selected, decision = ev, ev_decision
        self.status = decision.status
        self.issue_code = selected.issue_key
        self.issue_first_seen_at = decision.state.first_seen_at
        self.expected_state = selected.expected
        self.actual_state = selected.actual

    def attributes(self) -> dict[str, object]:
        return {
            "issue": self.issue_code,
            "first_seen_at": self.issue_first_seen_at,
            "expected": self.expected_state,
            "actual": self.actual_state,
            "last_action": self.last_action,
            "foxess_cloud_verification": self.foxess_cloud_verification,
            "grace_minutes": SUPERVISION_GRACE.total_seconds() / 60,
        }
