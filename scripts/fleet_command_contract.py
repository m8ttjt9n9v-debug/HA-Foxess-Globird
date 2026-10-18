"""Build and check optional HA-native Fleet controls; HEO remains the device writer."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "examples/fleet-command-package.yaml"
DASHBOARD_PATH = ROOT / "examples/fleet-dashboard.yaml"
DISPATCH = "script.heo_fleet_command"
ACK = "input_boolean.heo_fleet_local_control_confirmed"
REQUEST = "input_text.heo_fleet_request_id"
SITES = ("local", "bravo", "charlie")
RESULTS = {site: f"input_text.heo_fleet_{site}_result" for site in SITES}
OPERATIONS = {
    "manual_export_max": "export_max",
    "manual_self_use": "self_use",
    "manual_resume_automatic": "automatic",
}
LABELS = {"local": "Local site", "bravo": "Remote site 1", "charlie": "Remote site 2"}

MONITOR_CARD_TEMPLATE = """\
{% set p = 'sensor.fleet_site___SITE___' %}
{% set e = p ~ 'summary' %}
{% set online = states(e) not in ['unknown', 'unavailable', 'none'] %}
{% macro a(name) -%}
  {%- set v = state_attr(e, name) -%}
  {{- v if v is not none else '—' -}}
{%- endmacro %}
{% macro r(name, unit='') -%}
  {%- set v = states(p ~ name) -%}
  {{- v ~ unit if v not in ['unknown', 'unavailable', 'none'] else '—' -}}
{%- endmacro %}
{% macro m(name) -%}
  {%- set v = states(p ~ name) | float(none) -%}
  {{- ('$%.2f' | format(v)) if v is not none else '—' -}}
{%- endmacro %}
{% set cable = states(p ~ 'ev_cable') %}
{% set location = states(p ~ 'ev_location') %}
{% set plug = 'Plugged in' if cable in ['on', 'connected', 'plugged_in'] else
              'Unplugged' if cable in ['off', 'disconnected', 'unplugged'] else '—' %}
{% set place = 'Home' if location in ['home', 'on'] else
               'Away' if location in ['away', 'not_home', 'off'] else '—' %}
## {{ '🟢 Online' if online else '🔴 Unavailable' }} · {{ states(e) }}

| | |
|---|---:|
| Installed HEO | **{{ r('heo_version') }}** |
| Battery | **{{ a('battery_soc') }}%** · {{ a('battery_power_kw') }} kW |
| Grid / Solar | {{ a('grid_power_kw') }} / {{ a('solar_power_kw') }} kW |
| House / EV load | {{ r('house_load', ' kW') }} / {{ r('ev_load', ' kW') }} |
| Free import today | **{{ r('free_import_today', ' kWh') }}** |
| Solar today | **{{ r('solar_today', ' kWh') }}** |
| EV battery | **{{ r('ev_soc', '%') }}** |
| EV plug / location | {{ plug }} · {{ place }} |
| GloBird billing period cost | **{{ m('globird_billing_period_cost') }}** |
| GloBird expected monthly cost | **{{ m('globird_expected_monthly_cost') }}** |
| GloBird balance | **{{ m('globird_balance') }}** |
| Charge / Export | {{ a('charging_status') }} / {{ a('export_status') }} |
| Forecast / measured | {{ a('forecast_cost') }} / {{ a('measured_cost') }} |

_Last update: {{ a('last_update') }}_
"""

MAINTENANCE_CARD_TEMPLATE = """\
{% set e = 'sensor.home_energy_fleet___SITE___maintenance' %}
{% set phase = states(e) %}
{% set phases = {
  'idle': 'Ready', 'waiting': 'Waiting for a safe time', 'backing_up': 'Creating backup',
  'installing': 'Downloading HEO', 'checking': 'Checking configuration',
  'restart_requested': 'Restarting / reconnecting', 'restart_pending': 'Restart needs checking',
  'verified': 'Running verified', 'blocked': 'Waiting for a safety check',
  'failed': 'Needs attention', 'interrupted': 'Interrupted — check the site',
  'unknown': 'Outcome unknown — check the site', 'submitting': 'Sending request',
  'initial_update_required': 'First update needed'
} %}
{% set reasons = {
  'home_assistant_not_running': 'Home Assistant is not ready',
  'heo_runtime_unavailable': 'HEO is not ready',
  'heo_storage_untrusted': 'Saved control state needs checking',
  'maintenance_storage_unavailable': 'Maintenance history is unavailable',
  'battery_charge_session_active': 'Battery charging is active',
  'battery_export_session_active': 'Battery export is active',
  'battery_diagnostic_active': 'A battery test is active',
  'battery_manual_control_active': 'Manual battery control is active',
  'trip_charge_active': 'A trip charge is active',
  'ev_full_charge_active': 'Charge to Full is active',
  'battery_telemetry_unavailable': 'Battery readings are unavailable',
  'battery_mode_feedback_unavailable': 'Battery mode cannot be confirmed',
  'battery_not_self_use': 'Battery is not in Self Use',
  'battery_force_target_not_clear': 'Forced battery targets are not clear',
  'ev_session_active': 'EV charging is active',
  'ev_reconciliation_pending': 'An EV command is awaiting confirmation',
  'ev_recovery_pending': 'EV recovery is pending',
  'ev_charging_target_active': 'An EV charging target is active',
  'ev_feedback_unavailable': 'EV readings are unavailable',
  'ev_physically_charging': 'The car is charging',
  'ev_charge_switch_on': 'The car charge switch is on',
  'ev_full_feedback_unavailable': 'Charge to Full state is unavailable',
  'hacs_unavailable': 'HACS is not ready',
  'hacs_capability_unavailable': 'HEO releases could not be loaded; check HACS',
  'backup_not_verified': 'Backup could not be verified',
  'backup_failed': 'Backup failed',
  'configuration_invalid': 'Configuration needs correcting',
  'maintenance_settings_changed': 'Settings changed during maintenance',
  'maintenance_expired': 'Safe-time wait expired',
  'maintenance_busy': 'Maintenance is already in progress',
  'maintenance_verification_required': 'The previous restart needs checking',
  'verification_failed': 'The restarted site did not pass verification',
  'restart_not_observed': 'A completed restart was not observed',
  'status_unavailable': 'Maintenance status is unavailable',
  'initial_update_required': 'Install a maintenance-capable release first'
} %}
{% macro version(name) -%}
  {%- set value = state_attr(e, name) -%}
  {{- value if value is string and value else '—' -}}
{%- endmacro %}
{% set error = state_attr(e, 'error') %}
{% set blockers = state_attr(e, 'blockers') %}
{% set backup = state_attr(e, 'backup_verified') %}
**{{ phases.get(phase, 'Maintenance unavailable') }}**

| | |
|---|---|
| Running HEO | {{ version('running_version') }} |
| Downloaded HEO | {{ version('installed_version') }} |
| Backup | {{ 'Verified' if backup is sameas true else
               'Not yet verified' if backup is sameas false else '—' }} |
| Issue | {{ reasons.get(error, 'Needs a site check') if error else '—' }} |
| Waiting for | {% if blockers is iterable and blockers is not string and blockers %}
  {%- for reason in blockers -%}{{ reasons.get(reason, 'An additional safety check') }}
  {{- '; ' if not loop.last else '' }}{%- endfor -%}{% else %}—{% endif %} |

{% if phase == 'initial_update_required' %}
Install a maintenance-capable HEO release through HACS at this site first.
{% elif phase in ['unknown', 'unavailable', 'none'] %}
Check the site before retrying. No update or restart is automatically replayed.
{% endif %}
Downloaded does not mean running. A restart is verified separately.
"""


class Secret(str):
    """A secret reference, never a credential value."""


class PackageDumper(yaml.SafeDumper):
    """Keep HA secret references and readable multiline templates."""


def _string(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


PackageDumper.add_representer(str, _string)
PackageDumper.add_representer(
    Secret, lambda dumper, value: dumper.represent_scalar("!secret", str(value))
)


def _condition(expression: str) -> dict:
    return {"condition": "template", "value_template": "{{ " + expression + " }}"}


def _result(site: str, message: str) -> dict:
    return {
        "action": "input_text.set_value",
        "target": {"entity_id": RESULTS[site]},
        "data": {"value": message},
        "continue_on_error": True,
    }


def _current_request() -> dict:
    return _condition(f"states('{REQUEST}') == request_id")


def _response_message(site: str) -> str:
    """A transport acknowledgement is not a claim of measured physical export."""
    reply = "reply" if site == "local" else "reply.get('content', {}).get('service_response')"
    transport_check = (
        ""
        if site == "local"
        else """\
{% if reply is not mapping or reply.get('status') != 200 %}
  {{ 'Unknown: HTTP ' ~ reply.get('status') ~ '; check site before retrying Export'
     if reply is mapping and reply.get('status') else
     'Unknown: no API response; check site before retrying Export' }}
{% elif reply.get('content') is not mapping %}
  Unknown: invalid API response; check site before retrying Export
{% else %}
"""
    )
    return (
        transport_check
        + """\
{% set response = """
        + reply
        + """ %}
{% if response is not mapping or response.get('accepted') is not boolean
      or response.get('command_confirmed') is not boolean
      or response.get('hold') is not boolean or response.get('generation') is not integer
      or response.get('status') is not string or response.get('target') is not string
      or 'power_kw' not in response
      or (response.get('power_kw') is not none and response.get('power_kw') is not number) %}
  Unknown: no valid HEO response; check site before retrying Export
{% elif response.get('request_id') != request_id %}
  Unknown: response request mismatch; check site before retrying Export
{% elif not response.get('accepted') %}
  Rejected: {{ response.get('status') }}
{% elif response.get('target') != expected_target %}
  Unknown: response target mismatch; check site before retrying Export
{% elif response.get('command_confirmed') %}
  Command confirmed: {{ response.get('status') }}{% if response.get('power_kw') is not none %}
  · {{ response.get('power_kw') }} kW{% endif %} · generation {{ response.get('generation') }}
{% else %}
  Pending/blocked: {{ response.get('status') }} · generation {{ response.get('generation') }}
{% endif %}
"""
        + ("{% endif %}\n" if site != "local" else "")
    )


def _site_branch(site: str, entry_id: str) -> dict:
    data = {
        "local_control_confirmed": "{{ local_control_confirmed }}",
        "request_id": "{{ request_id }}",
        "issued_at": "{{ issued_at }}",
    }
    if site == "local":
        action = "home_energy_orchestrator.{{ command }}"
        if entry_id:
            data["entry_id"] = entry_id
    else:
        action = f"rest_command.heo_fleet_{site}"
        data.update({"operation": "{{ command }}", "entry_id": entry_id})
    send = [
        _current_request(),
        _result(site, "{{ 'Sending: ' ~ expected_target }}"),
        {
            "action": action,
            "data": data,
            "response_variable": "reply",
            "continue_on_error": True,
        },
        {"variables": {"message": _response_message(site)}},
        _current_request(),
        _result(site, "{{ (message | trim | replace('\n', ' '))[:255] }}"),
    ]
    return {
        "sequence": [
            # A branch owns its response variable; peers cannot overwrite it.
            {"variables": {"reply": {}}},
            {
                "if": [_condition("command == 'manual_self_use' or local_control_confirmed")],
                "then": send,
                "else": [
                    _current_request(),
                    _result(site, "Rejected: confirm competing inverter writers are disabled"),
                ],
            },
        ]
    }


def build_package(*, remote_origins=None, authorization_secrets=None, entry_ids=None) -> dict:
    """Custom values belong only in the installing hub's private package."""
    origins = {
        "bravo": "http://site-bravo.invalid:8123",
        "charlie": "http://site-charlie.invalid:8123",
        **(remote_origins or {}),
    }
    secrets = {
        "bravo": "fleet_site_bravo_authorization",
        "charlie": "fleet_site_charlie_authorization",
        **(authorization_secrets or {}),
    }
    entries = {site: "" for site in SITES} | (entry_ids or {})
    if set(origins) != {"bravo", "charlie"} or set(secrets) != {"bravo", "charlie"}:
        raise ValueError("Configure exactly the two explicitly named remote targets")
    if set(entries) != set(SITES):
        raise ValueError("Unknown site entry mapping")
    for site in ("bravo", "charlie"):
        parsed = urlsplit(origins[site])
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or not re.fullmatch(r"[^\s{}]+", origins[site])
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Remote origin must be a fixed HTTP(S) origin without credentials")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", secrets[site]):
            raise ValueError("Use an existing secrets.yaml key, not a credential")
    for entry in entries.values():
        if not isinstance(entry, str) or not re.fullmatch(r"[A-Za-z0-9_-]{0,64}", entry):
            raise ValueError("Use a config-entry ID or an empty single-entry mapping")

    allowed = repr(list(OPERATIONS))
    payload = """\
{% set payload = {'local_control_confirmed': local_control_confirmed,
                  'request_id': request_id, 'issued_at': issued_at} %}
{% if entry_id %}{% set payload = dict(payload, entry_id=entry_id) %}{% endif %}
{{ payload | to_json }}
"""
    return {
        "input_boolean": {
            ACK.split(".", 1)[1]: {
                "name": "Competing inverter writers disabled on every Fleet site",
                "icon": "mdi:shield-check",
                "initial": False,
            }
        },
        "input_text": {
            REQUEST.split(".", 1)[1]: {"name": "Fleet current request", "max": 100, "initial": ""},
            **{
                RESULTS[site].split(".", 1)[1]: {
                    "name": f"{LABELS[site]} command result",
                    "max": 255,
                    "initial": "No command in this hub session",
                }
                for site in SITES
            },
        },
        "rest_command": {
            f"heo_fleet_{site}": {
                "url": origins[site]
                + "/api/services/home_energy_orchestrator/"
                + "{{ operation if operation in "
                + allowed
                + " else 'unsupported_command' }}"
                + "?return_response",
                "method": "post",
                "headers": {"Authorization": Secret(secrets[site])},
                "content_type": "application/json",
                "payload": payload,
                "timeout": 15,
            }
            for site in ("bravo", "charlie")
        },
        "script": {
            DISPATCH.split(".", 1)[1]: {
                "alias": "HEO Fleet command",
                "description": "One request per site; Stop supersedes the previous hub dispatch.",
                "mode": "restart",
                "fields": {
                    "command": {
                        "name": "Command",
                        "required": True,
                        "selector": {"select": {"options": list(OPERATIONS)}},
                    }
                },
                "sequence": [
                    _condition("command in " + allowed),
                    {
                        "variables": {
                            "issued_at": "{{ now().isoformat() }}",
                            "request_id": "{{ issued_at ~ '-' ~ context.id }}",
                            "expected_target": "{{ " + repr(OPERATIONS) + "[command] }}",
                            "local_control_confirmed": f"{{{{ is_state('{ACK}', 'on') }}}}",
                        }
                    },
                    {
                        "action": "input_text.set_value",
                        "target": {"entity_id": REQUEST},
                        "data": {"value": "{{ request_id }}"},
                    },
                    {"parallel": [_site_branch(site, entries[site]) for site in SITES]},
                ],
            }
        },
    }


def _button(name: str, icon: str, command: str, confirmation: str | None) -> dict:
    return {
        "type": "button",
        "name": name,
        "icon": icon,
        "show_state": False,
        "tap_action": {
            "action": "perform-action",
            "perform_action": "script.turn_on",
            "target": {"entity_id": DISPATCH},
            "data": {"variables": {"command": command}},
            **({"confirmation": {"text": confirmation}} if confirmation else {}),
        },
        "hold_action": {"action": "none"},
    }


def build_controls_section() -> dict:
    """Prepend this full-width section; preserve the existing site sections."""
    return {
        "type": "grid",
        "column_span": 3,
        "cards": [
            {
                "type": "horizontal-stack",
                "grid_options": {"columns": "full"},
                "cards": [
                    _button(
                        "Export all at maximum",
                        "mdi:transmission-tower-export",
                        "manual_export_max",
                        None,
                    ),
                    _button(
                        "Stop all · Self Use",
                        "mdi:stop-circle",
                        "manual_self_use",
                        None,
                    ),
                ],
            },
            {
                "type": "entities",
                "title": "Fleet command results",
                "show_header_toggle": False,
                "grid_options": {"columns": "full"},
                "entities": [
                    {"entity": ACK},
                    *[{"entity": RESULTS[site], "name": LABELS[site]} for site in SITES],
                ],
            },
            {
                "type": "markdown",
                "grid_options": {"columns": "full"},
                "content": "Export continues until Stop, subject to each inverter's own "
                "protections. Stop selects Self Use and keeps HEO inverter automation held. "
                "Command confirmation describes native mode/power feedback; check measured "
                "grid flow to confirm physical export. Unknown results need a site check; "
                "the hub does not retry Export.",
            },
            {
                **_button(
                    "Resume automatic control",
                    "mdi:play-circle-outline",
                    "manual_resume_automatic",
                    "Release the manual hold on every site. Existing enabled HEO policies "
                    "may then resume; competing inverter writers must remain disabled.",
                ),
                "grid_options": {"columns": "full", "rows": 1},
            },
        ],
    }


def build_maintenance_card(site: str, label: str) -> dict:
    """One quiet native text row; all privileged actions still use the node."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", site):
        raise ValueError("Use a configured maintenance site key")
    prefix = f"home_energy_fleet_{site}_"

    def button(name: str, icon: str, action: str) -> dict:
        purpose = (
            "install the selected HEO release and restart"
            if action == "update_and_restart"
            else "restart Home Assistant"
        )
        return {
            "entity": f"button.{prefix}{action}",
            "name": name,
            "icon": icon,
            "show_name": True,
            "show_icon": False,
            "tap_action": {
                "action": "perform-action",
                "perform_action": "button.press",
                "target": {"entity_id": f"button.{prefix}{action}"},
                "confirmation": {
                    "text": f"Back up {label}, then {purpose} when safely idle. "
                    "Wait up to 60 minutes; active charging or export will not be stopped. "
                    "New HEO actions pause during maintenance; avoid approaching charge deadlines. "
                    "Only this site is affected.",
                },
            },
            "hold_action": {"action": "none"},
            "double_tap_action": {"action": "none"},
        }

    return {
        "type": "entities",
        "show_header_toggle": False,
        "state_color": False,
        "entities": [
            {
                "type": "buttons",
                "entities": [
                    {
                        "entity": f"select.{prefix}release",
                        "name": "Release",
                        "show_name": True,
                        "show_icon": False,
                        "tap_action": {"action": "more-info"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                    button("Update", "mdi:update", "update_and_restart"),
                    button("Restart", "mdi:restart", "restart"),
                    {
                        "entity": f"button.{prefix}check_releases",
                        "name": "Check releases",
                        "show_name": True,
                        "show_icon": False,
                        "tap_action": {
                            "action": "perform-action",
                            "perform_action": "button.press",
                            "target": {"entity_id": f"button.{prefix}check_releases"},
                        },
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                ],
            },
        ],
    }


def build_dashboard() -> dict:
    sections = [build_controls_section()]
    for site, label in (
        ("alpha", "Local site"),
        ("bravo", "Remote site 1"),
        ("charlie", "Remote site 2"),
    ):
        sections.append(
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "markdown",
                        "title": label,
                        "content": MONITOR_CARD_TEMPLATE.replace("__SITE__", site),
                    },
                    build_maintenance_card(site, label),
                ],
            }
        )
    return {
        "title": "HEO Fleet",
        "views": [
            {
                "title": "Fleet",
                "path": "overview",
                "icon": "mdi:home-group",
                "type": "sections",
                "max_columns": 3,
                "sections": sections,
            }
        ],
    }


PACKAGE_HEADER = """\
# Optional native Home Assistant Fleet command package.
# Requires the HEO manual-control services on every target; HACS does not install this package.
# Replace the two fixed .invalid origins and !secret references privately on the hub.
# Secret values are complete Authorization header values (Bearer plus token).
# See docs/fleet-command-controls.md before installing. No device commands run on startup.
"""
DASHBOARD_HEADER = """\
# Reusable three-site Fleet dashboard; all site data is placeholder monitoring data.
# Install fleet-command-package.yaml separately. Insert the first full-width section into
# an existing sections view without replacing its site cards. Secrets stay on the hub.
# Version sensors read HACS installed_version, never latest_version; see docs/fleet-monitoring.md.
# Optional per-site maintenance needs backend configuration; see docs/fleet-maintenance.md.
# Merge only approved cards into a fresh live dashboard; never replace personal layouts.
"""


def render_assets() -> dict[Path, str]:
    return {
        PACKAGE_PATH: PACKAGE_HEADER
        + yaml.dump(
            build_package(), Dumper=PackageDumper, sort_keys=False, allow_unicode=True, width=100
        ),
        DASHBOARD_PATH: DASHBOARD_HEADER
        + yaml.dump(
            build_dashboard(), Dumper=PackageDumper, sort_keys=False, allow_unicode=True, width=100
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Check the committed reusable examples")
    mode.add_argument("--write", action="store_true", help="Regenerate changed reusable examples")
    args = parser.parse_args()
    if args.check:
        mismatches = [
            str(path.relative_to(ROOT))
            for path, text in render_assets().items()
            if not path.exists() or path.read_text() != text
        ]
        if mismatches:
            raise SystemExit("Fleet examples differ from contract: " + ", ".join(mismatches))
        print("Fleet command package and dashboard match the generated contract")
    elif args.write:
        for path, text in render_assets().items():
            if not path.exists() or path.read_text() != text:
                path.write_text(text)
                print(f"Updated {path.relative_to(ROOT)}")
    else:
        for path, text in render_assets().items():
            print(f"--- {path.relative_to(ROOT)} ---\n{text}")


if __name__ == "__main__":
    main()
