"""Schedule and end the existing Full override at a selected trip SoC.

This does not contain an EV actuator or a second charging controller. Generated
automations may write only their own helpers and HEO's existing override switch.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from scripts.trip_impact_card import build_trip_impact_card

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "examples/trip-charge-package.yaml"
CARD_PATH = ROOT / "examples/trip-charge-card.yaml"

PLAN = "sensor.heo_trip_charge_plan"
READY = "input_datetime.heo_trip_ready_by"
TICKET = "input_datetime.heo_trip_started_for"
STARTED_TARGET = "input_number.heo_trip_started_target"
GENERATION = "input_text.heo_trip_full_generation"
RESUME = "input_text.heo_trip_resume_state"
NATIVE_STATUS = "sensor.home_energy_trip_charge_status"
ARMED = "input_boolean.heo_trip_charge_scheduled"
OWNED = "input_boolean.heo_trip_charge_started"
TARGET = "input_select.heo_trip_target_soc"
STATUS = "input_select.heo_trip_charge_status"
EFFICIENCY = "input_number.heo_trip_charge_efficiency"
MARGIN = "input_number.heo_trip_extra_minutes"
TIMEOUT = "input_number.heo_trip_override_timeout"
SOC = "sensor.home_energy_ev_soc"
CAPACITY = "sensor.home_energy_ev_usable_capacity"
POWER = "sensor.home_energy_ev_max_power"
OVERRIDE = "switch.home_energy_ev_charge_to_full"
CONTROL = "switch.home_energy_automatic_ev_control"
LOCK = "switch.home_energy_safety_lock"
TARGET_OPTIONS = [f"{value}%" for value in range(100, 0, -1)]

STATUSES = [
    "Not scheduled",
    "Waiting for start",
    "Already at target",
    "Waiting for car",
    "Waiting for data",
    "HEO control unavailable",
    "External override",
    "Override active",
    "Completed",
    "Cancelled",
    "Interrupted",
    "Expired",
    "Charging late",
    "Paused — car disconnected",
]

# Same energy-deficit / efficiency / power arithmetic as HEO's retained latest-
# start planner. Capacity and maximum power come from HEO, never from a guessed
# car model or Tessie's transient writable-current maximum.
PLAN_TEMPLATE = """\
{% set soc = states('sensor.home_energy_ev_soc') | float(none) %}
{% set cap = states('sensor.home_energy_ev_usable_capacity') | float(none) %}
{% set kw = states('sensor.home_energy_ev_max_power') | float(none) %}
{% set eff = states('input_number.heo_trip_charge_efficiency') | float(none) %}
{% set extra = states('input_number.heo_trip_extra_minutes') | float(0) %}
{% set maximum = states('input_number.heo_trip_override_timeout') | float(0) %}
{% set target_label = states('input_select.heo_trip_target_soc') %}
{% set target = target_label | replace('%', '') | float(none) %}
{% set due = state_attr('input_datetime.heo_trip_ready_by', 'timestamp') %}
{% if soc is not none and 0 <= soc <= 100 and cap is not none and 0 < cap <= 1000
      and kw is not none and 0 < kw <= 100 and eff is not none and 0 < eff <= 100
      and due is number and due > 0 and 0 <= extra <= 120 and 0 < maximum <= 48
      and target is not none and 1 <= target <= 100
      and target_label == (target | int | string) ~ '%'
      and state_attr('sensor.home_energy_ev_usable_capacity', 'unit_of_measurement') == 'kWh'
      and state_attr('sensor.home_energy_ev_max_power', 'unit_of_measurement') == 'kW' %}
  {% set hours = ([target - soc, 0] | max * cap / 100) / (kw * eff / 100) + extra / 60 %}
  {% if hours <= maximum %}
    {{ {'v': 2, 'due': due, 'target': target, 'soc': soc, 'cap': cap, 'kw': kw, 'eff': eff,
        'extra': extra, 'maximum': maximum, 'hours': hours | round(6),
        'start': due - hours * 3600} | to_json }}
  {% else %}
    {{ {'v': 0, 'reason': 'Charge duration exceeds override timeout'} | to_json }}
  {% endif %}
{% else %}{{ {'v': 0, 'reason': 'Missing or invalid commissioned inputs'} | to_json }}{% endif %}
"""


def _action(action: str, entity: str, **data) -> dict:
    item = {"action": action, "target": {"entity_id": entity}}
    if data:
        item["data"] = data
    return item


def _status(label: str) -> dict:
    return _action("input_select.select_option", STATUS, option=label)


def _condition(expression: str) -> dict:
    return {"condition": "template", "value_template": "{{ " + expression + " }}"}


def _branch(expression: str, sequence: list[dict]) -> dict:
    return {"conditions": [_condition(expression)], "sequence": sequence}


def _owns_current_full() -> str:
    """An observed ON cycle, or our still-settling service context, not any ON."""
    record = f"(states('{RESUME}') | from_json({{}}))"
    checkpoint_matches = (
        f"(states('{RESUME}') in ['', 'unknown', 'unavailable'] or "
        f"({record} is mapping and {record}.get('generation') is integer and "
        f"{record}.get('generation') == state_attr('{NATIVE_STATUS}', 'full_generation')))"
    )
    return (
        f"is_state('{OWNED}', 'on') and is_state('{OVERRIDE}', 'on') "
        f"and {checkpoint_matches} "
        f"and states['{OVERRIDE}'].context.user_id is none and ("
        f"states('{GENERATION}').startswith('on:' ~ "
        f"states['{OVERRIDE}'].last_changed.isoformat() ~ ':') or "
        f"states('{GENERATION}') == 'pending:' ~ states['{OVERRIDE}'].context.id)"
    )


def _full_generation() -> str:
    return (
        f"{{{{ 'on:' ~ states['{OVERRIDE}'].last_changed.isoformat() "
        f"~ ':' ~ states['{OVERRIDE}'].context.id }}}}"
    )


def _finish(label: str, *, clear_override=False) -> list[dict]:
    result = []
    if clear_override:
        result.append(
            {
                "if": [_condition(_owns_current_full())],
                "then": [_action("switch.turn_off", OVERRIDE)],
            }
        )
    result.extend(
        [
            _action("input_boolean.turn_off", ARMED),
            _action("input_boolean.turn_off", OWNED),
            _action("input_text.set_value", RESUME, value=""),
            _status(label),
        ]
    )
    return result


def _checkpoint_resume(*, paused: bool, starting=False) -> dict:
    """Keep dated intent and its original timeout separate from a Full lease."""
    if starting:
        value = (
            "{% set generation = state_attr('" + NATIVE_STATUS + "', 'full_generation') %}"
            "{{ {'v': 1, 'first': resume_record.get('first') if resuming else now_ts, "
            "'expires': resume_record.get('expires') if resuming "
            "else now_ts + plan.get('maximum') * 3600, "
            "'generation': generation + 1 if generation is integer and generation >= 0 "
            "else none, 'paused': false} | to_json }}"
        )
    else:
        value = (
            "{{ {'v': 1, 'first': resume_record.get('first'), "
            "'expires': resume_record.get('expires'), "
            "'generation': resume_record.get('generation'), "
            f"'paused': {str(paused).lower()}" + "} | to_json }}"
        )
    return _action("input_text.set_value", RESUME, value=value)


def build_package(
    *, location_entity="device_tracker.your_ev", cable_entity="binary_sensor.your_ev_cable"
) -> dict:
    """Return native HA definitions; defaults contain no private site data."""
    for entity in (location_entity, cable_entity):
        if not entity or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_." for c in entity):
            raise ValueError("Use an explicit Home Assistant entity ID")
    plan_matches = f"""\
{{{{ plan.get('v') == 2 and plan.get('due') == due
    and target_valid and plan.get('target') == target
    and plan.get('soc') == states('{SOC}') | float(-1)
    and plan.get('cap') == states('{CAPACITY}') | float(-1)
    and plan.get('kw') == states('{POWER}') | float(-1)
    and plan.get('eff') == states('{EFFICIENCY}') | float(-1)
    and plan.get('extra') == states('{MARGIN}') | float(-1)
    and plan.get('maximum') == states('{TIMEOUT}') | float(-1) }}}}
"""
    live_start = (
        plan_matches.removesuffix("\n").removesuffix(" }}")
        + f" and is_state('{ARMED}', 'on') and is_state('{OWNED}', 'on')"
        + f" and state_attr('{READY}', 'timestamp') == due"
        + f" and states('{TARGET}') == (target | int | string) ~ '%'"
        + f" and states('{STARTED_TARGET}') | float(-1) == target"
        + f" and is_state('{OVERRIDE}', 'off') and is_state('{CONTROL}', 'on')"
        + f" and is_state('{LOCK}', 'off') and is_state('{location_entity}', 'home')"
        + f" and is_state('{cable_entity}', 'on') and now().timestamp() < due"
        + f" and now().timestamp() < (states('{RESUME}') | from_json({{}})).get('expires', 0)"
        + f" and ((states('{RESUME}') | from_json({{}})).get('generation') is none or "
        + f"(state_attr('{NATIVE_STATUS}', 'full_generation') is integer and "
        + f"(states('{RESUME}') | from_json({{}})).get('generation') == "
        + f"state_attr('{NATIVE_STATUS}', 'full_generation') + 1))"
        + f" and 0 <= states('{SOC}') | float(-1) < target }}"
        + "}"
    )
    disconnected_stop = (
        "resume_valid and armed and target_valid "
        "and target == started_target and due == ticket "
        "and (not soc_valid or soc < started_target) "
        "and now_ts < due and now_ts < resume_record.get('expires') "
        "and override_state == 'off' "
        "and full_stop_reason == 'disconnected' "
        "and full_stop_generation == resume_record.get('generation') "
        "and full_generation == resume_record.get('generation') + 1"
    )
    branches = [
        # A confirmed OFF event ends our intent even if a human has already
        # turned Full back ON before this queued run. Do not stop their new ON.
        _branch(
            "owned and full_off_edge and soc_valid and target_valid "
            "and target == started_target and due == ticket and soc >= started_target",
            _finish("Completed"),
        ),
        _branch(
            "owned and (full_off_edge or not override_on) and " + disconnected_stop,
            [
                _checkpoint_resume(paused=True),
                _action("input_boolean.turn_off", OWNED),
                _status("Paused — car disconnected"),
            ],
        ),
        _branch("owned and full_off_edge", _finish("Interrupted")),
        # Startup can briefly hide Full's state. Keep the owned obligation
        # until it is observable; unknown is not a confirmed manual OFF.
        _branch("owned and override_state not in ['on', 'off']", [_status("Waiting for data")]),
        _branch(
            "owned and override_on and has_resume_record and full_generation is not integer",
            [_status("Waiting for data")],
        ),
        # The durable OFF receipt is published before Full's entity changes.
        # Do not mistake that reducing transition for a same-state foreign ON.
        _branch(
            "owned and override_on and resume_valid "
            "and full_generation == resume_record.get('generation') + 1 "
            "and full_stop_generation == resume_record.get('generation') "
            "and full_stop_reason in ['disconnected', 'completed', 'timeout', "
            "'operator', 'cancelled', 'invalid_data']",
            [_status("Waiting for data")],
        ),
        _branch("owned and override_on and not owns_current_full", _finish("Interrupted")),
        _branch(
            "has_resume_record and not resume_valid",
            _finish("Interrupted", clear_override=True),
        ),
        _branch(
            "owned and (not armed or due != ticket or not target_valid "
            "or target != started_target)",
            _finish("Cancelled", clear_override=True),
        ),
        _branch("owned and not soc_valid", _finish("Interrupted", clear_override=True)),
        _branch("owned and soc >= started_target", _finish("Completed", clear_override=True)),
        _branch(
            "owned and resume_valid and now_ts >= resume_record.get('expires')",
            _finish("Expired", clear_override=True),
        ),
        _branch("owned and not override_on", _finish("Interrupted")),
        _branch(
            "owned and due <= now_ts",
            [
                {
                    "if": [_condition(f"not is_state('{STATUS}', 'Charging late')")],
                    "then": [
                        _status("Charging late"),
                        {
                            "action": "persistent_notification.create",
                            "data": {
                                "notification_id": "heo_trip_charge_late",
                                "title": "Trip charge has missed its ready-by time",
                                "message": "The car has not reached the selected trip SoC. "
                                "The existing HEO override remains "
                                "in charge until that target, cancellation, disconnection "
                                "or its timeout.",
                            },
                        },
                    ],
                },
            ],
        ),
        _branch("owned", [_status("Override active")]),
        _branch(
            "armed and resume_unreadable and due == ticket and target == started_target",
            [_status("Waiting for data")],
        ),
        _branch("pause_requested and not armed", _finish("Cancelled")),
        _branch(
            "pause_requested and (not target_valid or target != started_target or due != ticket)",
            _finish("Cancelled"),
        ),
        _branch("pause_requested and not resume_valid", _finish("Interrupted")),
        _branch(
            "resuming and (now_ts >= resume_record.get('expires') or due <= now_ts)",
            _finish("Expired"),
        ),
        _branch("resuming and soc_valid and soc >= target", _finish("Completed")),
        _branch(
            "resuming and (override_state not in ['on', 'off'] or full_generation is not integer)",
            [_status("Waiting for data")],
        ),
        _branch(
            "resuming and (override_on "
            "or full_generation != resume_record.get('generation') + 1 "
            "or full_stop_reason != 'disconnected' "
            "or full_stop_generation != resume_record.get('generation'))",
            _finish("External override"),
        ),
        _branch(
            "armed and due <= now_ts and target_valid and soc_valid and soc >= target",
            _finish("Completed"),
        ),
        _branch("armed and due <= now_ts", _finish("Expired")),
        _branch(
            "armed and target_valid and soc_valid and soc >= target", [_status("Already at target")]
        ),
        _branch("armed and override_on", _finish("External override")),
        _branch("armed and not plan_valid", [_status("Waiting for data")]),
        _branch(
            "armed and not car_ready",
            [_status("{{ 'Paused — car disconnected' if resuming else 'Waiting for car' }}")],
        ),
        _branch("armed and not control_ready", [_status("HEO control unavailable")]),
        _branch(
            "armed and not resuming and plan.get('start', now_ts + 1) > now_ts",
            [_status("Waiting for start")],
        ),
        _branch(
            "armed and plan_valid and car_ready and control_ready",
            [
                # Save the specific departure ticket before any actuator intent.
                _action("input_datetime.set_datetime", TICKET, timestamp="{{ due }}"),
                _action("input_number.set_value", STARTED_TARGET, value="{{ target }}"),
                _action("input_boolean.turn_on", OWNED),
                _checkpoint_resume(paused=False, starting=True),
                _action(
                    "input_text.set_value",
                    GENERATION,
                    value=f"{{{{ 'pending:' ~ states['{OWNED}'].context.id }}}}",
                ),
                _status("Override active"),
                {
                    "if": [{"condition": "template", "value_template": live_start}],
                    "then": [
                        _action("switch.turn_on", OVERRIDE),
                        {
                            "if": [_condition(_owns_current_full())],
                            "then": [
                                _action(
                                    "input_text.set_value",
                                    GENERATION,
                                    value=_full_generation(),
                                )
                            ],
                        },
                    ],
                    "else": [
                        _action("input_boolean.turn_off", OWNED),
                        {
                            "if": [_condition("resuming")],
                            "then": [_checkpoint_resume(paused=True)],
                            "else": [_action("input_text.set_value", RESUME, value="")],
                        },
                        _action(
                            "input_select.select_option",
                            STATUS,
                            option=f"{{{{ 'Waiting for start' if is_state('{ARMED}', 'on') "
                            "else 'Cancelled' }}",
                        ),
                    ],
                },
            ],
        ),
    ]
    dispatcher = {
        "id": "heo_trip_charge_dispatch",
        "alias": "HEO Trip charge — schedule existing full override",
        "description": "One-off trip target. HEO owns EV commands; this schedules and ends intent.",
        "mode": "queued",
        "max": 10,
        "max_exceeded": "silent",
        "triggers": [
            {"trigger": "time", "at": "sensor.heo_trip_charge_start"},
            {"trigger": "time_pattern", "minutes": "/1"},
            {"trigger": "homeassistant", "event": "start", "id": "startup"},
            {"trigger": "state", "entity_id": [READY, ARMED, TARGET, SOC], "from": None},
            {"trigger": "state", "entity_id": OVERRIDE, "from": None, "id": "full_changed"},
            {"trigger": "state", "entity_id": [location_entity, cable_entity], "from": None},
            {"trigger": "state", "entity_id": NATIVE_STATUS},
        ],
        "conditions": [
            _condition(
                f"is_state('{ARMED}', 'on') or is_state('{OWNED}', 'on') or "
                f"states('{RESUME}') not in ['', 'unknown', 'unavailable']"
            )
        ],
        "actions": [
            # HA recreates entity timestamps on startup. The durable trip
            # ticket permits rebinding its restored logical Full request, not
            # a fresh user-issued request. Unknown Full waits without adoption.
            {
                "if": [
                    _condition(
                        f"is_state('{OWNED}', 'on') and ("
                        "(trigger is defined and trigger.get('id') == 'startup') or "
                        f"states('{OVERRIDE}') not in ['on', 'off'])"
                    )
                ],
                "then": [_action("input_text.set_value", GENERATION, value="restoring")],
            },
            {
                "if": [
                    _condition(
                        f"is_state('{OWNED}', 'on') and is_state('{GENERATION}', 'restoring') "
                        f"and is_state('{OVERRIDE}', 'on') "
                        f"and states['{OVERRIDE}'].context.user_id is none"
                    )
                ],
                "then": [
                    _action(
                        "input_text.set_value",
                        GENERATION,
                        value=_full_generation(),
                    )
                ],
            },
            {
                "variables": {
                    "plan": f"{{{{ states('{PLAN}') | from_json({{}}) }}}}",
                    "due": f"{{{{ state_attr('{READY}', 'timestamp') | float(0) }}}}",
                    "ticket": f"{{{{ state_attr('{TICKET}', 'timestamp') | float(0) }}}}",
                    "now_ts": "{{ now().timestamp() }}",
                    "soc": f"{{{{ states('{SOC}') | float(-1) }}}}",
                    "target": f"{{{{ states('{TARGET}') | replace('%', '') | float(-1) }}}}",
                    "started_target": f"{{{{ states('{STARTED_TARGET}') | float(-1) }}}}",
                    "armed": f"{{{{ is_state('{ARMED}', 'on') }}}}",
                    "owned": f"{{{{ is_state('{OWNED}', 'on') }}}}",
                    "override_on": f"{{{{ is_state('{OVERRIDE}', 'on') }}}}",
                    "override_state": f"{{{{ states('{OVERRIDE}') }}}}",
                    "owns_current_full": "{{ " + _owns_current_full() + " }}",
                    "resume_record": "{% set record = states('"
                    + RESUME
                    + "') | from_json({}) %}{{ record if record is mapping else {} }}",
                    "has_resume_record": "{{ states('"
                    + RESUME
                    + "') not in ['', 'unknown', 'unavailable'] }}",
                    "resume_unreadable": "{{ states('"
                    + RESUME
                    + "') in ['unknown', 'unavailable'] }}",
                    "full_generation": "{{ state_attr('"
                    + NATIVE_STATUS
                    + "', 'full_generation') }}",
                    "full_stop_reason": "{{ state_attr('"
                    + NATIVE_STATUS
                    + "', 'full_stop_reason') }}",
                    "full_stop_generation": "{{ state_attr('"
                    + NATIVE_STATUS
                    + "', 'full_stop_generation') }}",
                    "full_off_edge": "{{ trigger is defined "
                    "and trigger.get('id') == 'full_changed' "
                    "and trigger.get('to_state') is not none "
                    "and trigger.to_state.state == 'off' "
                    "and trigger.get('from_state') is not none "
                    "and trigger.from_state.state == 'on' and ("
                    f"states('{GENERATION}') == 'on:' ~ "
                    "trigger.from_state.last_changed.isoformat() "
                    "~ ':' ~ trigger.from_state.context.id or "
                    f"states('{GENERATION}') == 'pending:' ~ trigger.from_state.context.id) "
                    "}}",
                    "car_ready": f"{{{{ is_state('{location_entity}', 'home') and "
                    f"is_state('{cable_entity}', 'on') }}}}",
                    "control_ready": f"{{{{ is_state('{CONTROL}', 'on') "
                    f"and is_state('{LOCK}', 'off') "
                    f"and state_attr('{NATIVE_STATUS}', 'full_generation') is integer "
                    f"and states['{RESUME}'] is not none "
                    "and state_attr('sensor.home_energy_ev_control_status', 'gate') "
                    "== 'ready' }}",
                }
            },
            {
                "variables": {
                    "soc_valid": "{{ 0 <= soc <= 100 }}",
                    "pause_requested": "{{ resume_record.get('paused') is sameas true }}",
                    "resume_valid": "{{ resume_record.get('v') is integer "
                    "and resume_record.get('v') == 1 "
                    "and resume_record.get('first') is number "
                    "and resume_record.get('first') is not boolean "
                    "and is_number(resume_record.get('first')) "
                    "and resume_record.get('expires') is number "
                    "and resume_record.get('expires') is not boolean "
                    "and is_number(resume_record.get('expires')) "
                    "and 0 < resume_record.get('first') <= now_ts "
                    "and resume_record.get('first') < resume_record.get('expires') "
                    "and resume_record.get('generation') is integer "
                    "and resume_record.get('generation') > 0 "
                    "and resume_record.get('paused') is boolean }}",
                    "target_valid": f"{{{{ 1 <= target <= 100 and states('{TARGET}') "
                    "== (target | int | string) ~ '%' }}",
                }
            },
            {"variables": {"plan_valid": plan_matches}},
            {"variables": {"resuming": "{{ pause_requested and resume_valid }}"}},
            {"choose": branches},
        ],
    }
    return {
        "input_datetime": {
            "heo_trip_ready_by": {"name": "HEO Trip Ready By", "has_date": True, "has_time": True},
            "heo_trip_started_for": {
                "name": "HEO Trip Started For",
                "has_date": True,
                "has_time": True,
            },
        },
        "input_boolean": {
            "heo_trip_charge_scheduled": {
                "name": "HEO Trip Charge Scheduled",
                "icon": "mdi:calendar-clock",
            },
            "heo_trip_charge_started": {"name": "HEO Trip Charge Started", "icon": "mdi:car-clock"},
        },
        "input_select": {
            "heo_trip_target_soc": {"name": "HEO Trip Target SoC", "options": TARGET_OPTIONS},
            "heo_trip_charge_status": {"name": "HEO Trip Charge Status", "options": STATUSES},
        },
        "input_text": {
            "heo_trip_full_generation": {"name": "HEO Trip Full Generation", "max": 120},
            "heo_trip_resume_state": {"name": "HEO Trip Resume State", "max": 255},
        },
        "input_number": {
            "heo_trip_started_target": {
                "name": "HEO Trip Started Target",
                "min": 0,
                "max": 100,
                "step": 1,
                "mode": "box",
                "unit_of_measurement": "%",
            },
            "heo_trip_charge_efficiency": {
                "name": "HEO Trip Charge Efficiency",
                "min": 0,
                "max": 100,
                "step": 1,
                "mode": "box",
                "unit_of_measurement": "%",
            },
            "heo_trip_extra_minutes": {
                "name": "HEO Trip Extra Minutes",
                "min": 0,
                "max": 120,
                "step": 1,
                "mode": "box",
                "unit_of_measurement": "min",
            },
            "heo_trip_override_timeout": {
                "name": "HEO Trip Override Timeout",
                "min": 0,
                "max": 48,
                "step": 0.5,
                "mode": "box",
                "unit_of_measurement": "h",
            },
        },
        "template": [
            {
                "sensor": [
                    {
                        "name": "HEO Trip Charge Plan",
                        "unique_id": "heo_trip_charge_plan",
                        "state": PLAN_TEMPLATE,
                    },
                    {
                        "name": "HEO Trip Charge Duration",
                        "unique_id": "heo_trip_charge_duration",
                        "unit_of_measurement": "h",
                        "device_class": "duration",
                        "availability": "{{ (states('sensor.heo_trip_charge_plan') "
                        "| from_json({})).get('v') == 2 }}",
                        "state": f"{{{{ (states('{PLAN}') | from_json({{}})).get('hours') }}}}",
                    },
                    {
                        "name": "HEO Trip Charge Start",
                        "unique_id": "heo_trip_charge_start",
                        "device_class": "timestamp",
                        "availability": "{{ (states('sensor.heo_trip_charge_plan') "
                        "| from_json({})).get('v') == 2 }}",
                        "state": "{% set plan = states('sensor.heo_trip_charge_plan') "
                        "| from_json({}) %}"
                        "{{ as_datetime(plan.get('start')).isoformat() "
                        "if plan.get('v') == 2 else none }}",
                    },
                ]
            }
        ],
        "automation": [dispatcher],
    }


def build_card() -> dict:
    return {
        "type": "vertical-stack",
        "cards": [
            {
                "type": "entities",
                "title": "Trip charge — ready at your chosen SoC",
                "show_header_toggle": False,
                "entities": [
                    {"entity": READY, "name": "Departure date and time"},
                    {"entity": TARGET, "name": "Desired car SoC"},
                    {"entity": ARMED, "name": "Schedule this trip / cancel"},
                    {"type": "simple-entity", "entity": STATUS, "name": "Schedule status"},
                    {"entity": "sensor.heo_trip_charge_start", "name": "Calculated start"},
                    {"entity": "sensor.heo_trip_charge_duration", "name": "Estimated charge hours"},
                    {"entity": SOC, "name": "Car SoC now"},
                    {
                        "entity": "sensor.home_energy_ev_actual_current",
                        "name": "Actual charging current",
                    },
                ],
            },
            {
                "type": "markdown",
                "content": "Set your departure date/time, then enable the schedule. "
                "Start time updates until charging begins. "
                "This uses HEO's existing paid Charge to Full override: the normal house-battery "
                "reserve does not stop it. At your chosen SoC the trip override ends; "
                "normal HEO policies resume, including keepalive. This is not a permanent "
                "car charge ceiling.\n\n"
                "The estimate uses HEO's capacity and maximum configured power; "
                "it cannot promise the exact finishing minute or predict battery taper. "
                "Cancelling returns control to normal HEO "
                "policy, including its keepalive. Changing the date or target after charging "
                "starts cancels that trip. If charging is interrupted, re-arm deliberately.",
            },
            build_trip_impact_card(),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = {
        PACKAGE_PATH: "# Optional native HA package; HACS does not install this automatically.\n"
        "# Set explicit car location/cable mappings and commissioned helper values first.\n"
        "# Generated by python -m scripts.trip_charge_wrapper --write\n"
        + yaml.safe_dump(build_package(), sort_keys=False, allow_unicode=True),
        CARD_PATH: "# Optional card for the native trip-charge helpers.\n"
        + yaml.safe_dump(build_card(), sort_keys=False, allow_unicode=True),
    }
    for path, content in rendered.items():
        if args.write:
            path.write_text(content, encoding="utf-8")
        elif args.check and (not path.exists() or path.read_text(encoding="utf-8") != content):
            raise SystemExit(f"Regenerate {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
