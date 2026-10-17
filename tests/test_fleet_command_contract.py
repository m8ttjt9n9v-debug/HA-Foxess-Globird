"""Exercise Fleet scripts with native HA service responses and REST transport."""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.api import APIDomainServicesView
from homeassistant.components.http import KEY_HASS
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from scripts.fleet_command_contract import (
    ACK,
    DISPATCH,
    OPERATIONS,
    REQUEST,
    RESULTS,
    SITES,
    build_controls_section,
    build_dashboard,
    build_package,
    render_assets,
)


def _response(data, command, **changes):
    result = {
        "accepted": True,
        "command_confirmed": True,
        "target": OPERATIONS[command],
        "status": "native_feedback_confirmed",
        "hold": command != "manual_resume_automatic",
        "power_kw": 4.0 if command == "manual_export_max" else 0.0,
        "generation": 1,
        "request_id": data["request_id"],
    }
    return result | changes


async def _setup(hass, *, local_error=False, remote_error=None, custom_remote=None, package=None):
    package = package or build_package()
    for domain in ("input_boolean", "input_text"):
        assert await async_setup_component(hass, domain, {domain: package[domain]})
    calls = []

    async def local(call):
        calls.append(("local", call.service, dict(call.data)))
        if local_error:
            raise HomeAssistantError("Test node declined the request")
        return _response(call.data, call.service)

    async def remote(call):
        site = call.service.removeprefix("heo_fleet_")
        calls.append((site, call.data["operation"], dict(call.data)))
        if site == remote_error:
            raise HomeAssistantError("Test API timeout; outcome unknown")
        return {
            "status": 200,
            "content": {
                "changed_states": [],
                "service_response": _response(call.data, call.data["operation"]),
            },
        }

    for command in OPERATIONS:
        hass.services.async_register(
            "home_energy_orchestrator", command, local, supports_response=SupportsResponse.OPTIONAL
        )
    for site in ("bravo", "charlie"):
        hass.services.async_register(
            "rest_command",
            f"heo_fleet_{site}",
            custom_remote or remote,
            supports_response=SupportsResponse.OPTIONAL,
        )
    assert await async_setup_component(hass, "script", {"script": package["script"]})
    await hass.async_block_till_done()
    return package, calls


async def _ack(hass):
    await hass.services.async_call("input_boolean", "turn_on", {"entity_id": ACK}, blocking=True)


async def _command(hass, command):
    await hass.services.async_call(
        "script", DISPATCH.split(".", 1)[1], {"command": command}, blocking=True
    )
    await hass.async_block_till_done()


def _messages(hass):
    return {site: hass.states.get(RESULTS[site]).state for site in SITES}


def test_examples_are_sanitized_and_preserve_three_site_columns():
    for path, text in render_assets().items():
        assert path.read_text() == text
        assert "Bearer ey" not in text
        assert "100." not in text
        assert "192.168." not in text
        assert "taile" not in text
    package = build_package()
    assert set(package) == {"input_boolean", "input_text", "script", "rest_command"}
    assert package["script"][DISPATCH.split(".")[1]]["mode"] == "restart"
    assert len(package["script"][DISPATCH.split(".")[1]]["sequence"][-1]["parallel"]) == 3
    view = build_dashboard()["views"][0]
    assert view["max_columns"] == 3
    assert len(view["sections"]) == 4
    controls = build_controls_section()
    assert controls["column_span"] == 3
    buttons = controls["cards"][0]["cards"]
    assert [b["tap_action"]["data"]["variables"]["command"] for b in buttons] == [
        "manual_export_max",
        "manual_self_use",
    ]
    assert all("confirmation" not in b["tap_action"] for b in buttons)
    assert controls["cards"][-1]["tap_action"]["confirmation"]["text"]
    assert (
        "manual_resume_automatic"
        == (controls["cards"][-1]["tap_action"]["data"]["variables"]["command"])
    )
    assert all(len(section["cards"]) == 1 for section in view["sections"][1:])


async def test_monitoring_cards_preserve_zero_and_show_missing_optional_data(hass):
    hass.states.async_set(
        "sensor.fleet_site_alpha_summary",
        "ready",
        {"battery_soc": 0, "battery_power_kw": 0, "grid_power_kw": 0, "solar_power_kw": 0},
    )
    hass.states.async_set("sensor.fleet_site_alpha_globird_balance", "0")
    card = build_dashboard()["views"][0]["sections"][1]["cards"][0]
    content = Template(card["content"], hass).async_render(parse_result=False)
    assert "| Grid / Solar | 0 / 0 kW |" in content
    assert "| GloBird balance | **$0.00** |" in content
    assert "| GloBird expected monthly cost | **—** |" in content
    assert "| EV plug / location | — · — |" in content
    assert "| Installed HEO | **—** |" in content


@pytest.mark.parametrize("site", ["alpha", "bravo", "charlie"])
@pytest.mark.parametrize("installed_version", ["v0.12.38", "0.12.29rc17"])
async def test_monitoring_cards_show_each_sites_installed_version(hass, site, installed_version):
    """The displayed value is each site's installed-version sensor, not an update flag."""
    hass.states.async_set(f"sensor.fleet_site_{site}_summary", "ready")
    hass.states.async_set(f"sensor.fleet_site_{site}_heo_version", installed_version)
    # Neither another site's version nor the latest available release is authoritative.
    hass.states.async_set("sensor.fleet_site_other_heo_version", "v9.0.0")
    hass.states.async_set(
        "update.home_energy_orchestrator_update", "on", {"latest_version": "v9.0.0"}
    )
    sections = build_dashboard()["views"][0]["sections"]
    card = sections[1 + ("alpha", "bravo", "charlie").index(site)]["cards"][0]
    content = Template(card["content"], hass).async_render(parse_result=False)
    assert f"| Installed HEO | **{installed_version}** |" in content
    assert "v9.0.0" not in content


@pytest.mark.parametrize("version_state", ["unknown", "unavailable", "none"])
async def test_monitoring_card_does_not_present_unavailable_version_as_installed(
    hass, version_state,
):
    hass.states.async_set("sensor.fleet_site_alpha_summary", "ready")
    hass.states.async_set("sensor.fleet_site_alpha_heo_version", version_state)
    card = build_dashboard()["views"][0]["sections"][1]["cards"][0]
    content = Template(card["content"], hass).async_render(parse_result=False)
    assert "| Installed HEO | **—** |" in content


@pytest.mark.parametrize("command", ["manual_export_max", "manual_resume_automatic"])
async def test_export_and_resume_need_explicit_hub_acknowledgement(hass, command):
    _, calls = await _setup(hass)
    await _command(hass, command)
    assert calls == []
    assert all(message.startswith("Rejected:") for message in _messages(hass).values())


async def test_stop_dispatches_without_ack_using_one_correlated_aware_ticket(hass):
    _, calls = await _setup(hass)
    await _command(hass, "manual_self_use")
    assert {site for site, _, _ in calls} == set(SITES)
    assert len(calls) == 3
    assert {command for _, command, _ in calls} == {"manual_self_use"}
    assert {data["request_id"] for _, _, data in calls} == {hass.states.get(REQUEST).state}
    times = {data["issued_at"] for _, _, data in calls}
    assert len(times) == 1
    assert datetime.fromisoformat(times.pop()).tzinfo is not None
    assert all(data["local_control_confirmed"] is False for _, _, data in calls)
    assert all(message.startswith("Command confirmed:") for message in _messages(hass).values())


@pytest.mark.parametrize("local_error,remote_error", [(True, None), (False, "bravo")])
async def test_one_failed_api_does_not_abort_or_retry_other_sites(hass, local_error, remote_error):
    _, calls = await _setup(hass, local_error=local_error, remote_error=remote_error)
    await _ack(hass)
    await _command(hass, "manual_export_max")
    assert len(calls) == 3
    failed = "local" if local_error else remote_error
    assert _messages(hass)[failed].startswith("Unknown:")
    assert all(
        _messages(hass)[site].startswith("Command confirmed:") for site in SITES if site != failed
    )
    await hass.async_block_till_done()
    assert len(calls) == 3


@pytest.mark.parametrize(
    "reply,expected",
    [
        ({"status": 401, "content": {"message": "Unauthorized"}}, "Unknown: HTTP 401"),
        ({"status": 400, "content": {"message": "Service unavailable"}}, "Unknown: HTTP 400"),
        ({"status": 500, "content": "Internal server error"}, "Unknown: HTTP 500"),
        ({"status": 200, "content": []}, "Unknown: invalid API response"),
        ({"status": 200, "content": {"changed_states": []}}, "Unknown: no valid HEO response"),
    ],
)
async def test_real_rest_errors_are_not_reported_as_success(hass, aioclient_mock, reply, expected):
    package, calls = await _setup(hass)
    for site in ("bravo", "charlie"):
        hass.services.async_remove("rest_command", f"heo_fleet_{site}")
        package["rest_command"][f"heo_fleet_{site}"]["headers"]["Authorization"] = "Bearer test"
    assert await async_setup_component(
        hass, "rest_command", {"rest_command": package["rest_command"]}
    )
    for site in ("bravo", "charlie"):
        url = f"http://site-{site}.invalid:8123/api/services/home_energy_orchestrator/"
        aioclient_mock.post(
            url + "manual_self_use?return_response",
            status=reply["status"],
            json=reply["content"],
            headers={"Content-Type": "application/json"},
        )
    await _command(hass, "manual_self_use")
    assert len(calls) == 1
    assert aioclient_mock.call_count == 2
    assert _messages(hass)["local"].startswith("Command confirmed:")
    for site in ("bravo", "charlie"):
        assert _messages(hass)[site].startswith(expected)
    for _, _, request_data, headers in aioclient_mock.mock_calls:
        payload = json.loads(request_data)
        assert payload["request_id"] == hass.states.get(REQUEST).state
        assert payload["local_control_confirmed"] is False
        assert "entry_id" not in payload
        assert headers["Authorization"] == "Bearer test"


async def test_real_rest_timeout_is_unknown_and_never_retried(hass, aioclient_mock):
    package, _ = await _setup(hass)
    for site in ("bravo", "charlie"):
        hass.services.async_remove("rest_command", f"heo_fleet_{site}")
        package["rest_command"][f"heo_fleet_{site}"]["headers"]["Authorization"] = "Bearer test"
    assert await async_setup_component(
        hass, "rest_command", {"rest_command": package["rest_command"]}
    )
    for site in ("bravo", "charlie"):
        url = f"http://site-{site}.invalid:8123/api/services/home_energy_orchestrator/"
        aioclient_mock.post(url + "manual_export_max?return_response", exc=TimeoutError)
    await _ack(hass)
    await _command(hass, "manual_export_max")
    assert aioclient_mock.call_count == 2
    assert all(_messages(hass)[site].startswith("Unknown:") for site in ("bravo", "charlie"))
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 2


async def test_real_service_api_round_trip_preserves_entry_ids_and_response_envelope(
    hass, aioclient_mock
):
    package, calls = await _setup(
        hass,
        package=build_package(
            entry_ids={"local": "entry-local", "bravo": "entry-bravo", "charlie": "entry-charlie"}
        ),
    )
    for site in ("bravo", "charlie"):
        hass.services.async_remove("rest_command", f"heo_fleet_{site}")
        package["rest_command"][f"heo_fleet_{site}"]["headers"]["Authorization"] = "Bearer test"
    assert await async_setup_component(
        hass, "rest_command", {"rest_command": package["rest_command"]}
    )

    async def api(method, url, data):
        # Run HA's actual service-API view, including SupportsResponse handling.
        # The two pretend remote nodes share a test HA, never real equipment.
        request = Mock(app={KEY_HASS: hass}, query={"return_response": ""})
        request.text = AsyncMock(return_value=data.decode())
        with patch.object(APIDomainServicesView, "context", return_value=Context()):
            response = await APIDomainServicesView().post(
                request, "home_energy_orchestrator", "manual_export_max"
            )
        return AiohttpClientMockResponse(
            method,
            url,
            status=response.status,
            json=json.loads(response.text),
            headers={"Content-Type": "application/json"},
        )

    for site in ("bravo", "charlie"):
        url = f"http://site-{site}.invalid:8123/api/services/home_energy_orchestrator/"
        aioclient_mock.post(url + "manual_export_max?return_response", side_effect=api)
    await _ack(hass)
    await _command(hass, "manual_export_max")
    assert len(calls) == 3
    assert {data["entry_id"] for _, _, data in calls} == {
        "entry-local",
        "entry-bravo",
        "entry-charlie",
    }
    assert {data["request_id"] for _, _, data in calls} == {hass.states.get(REQUEST).state}
    assert all(data["local_control_confirmed"] is True for _, _, data in calls)
    assert aioclient_mock.call_count == 2
    assert all(message.startswith("Command confirmed:") for message in _messages(hass).values())


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"command_confirmed": False, "status": "waiting_feedback"}, "Pending/blocked:"),
        ({"accepted": False, "status": "stale_request"}, "Rejected:"),
        ({"request_id": "some-other-request"}, "Unknown: response request mismatch"),
        ({"target": "self_use"}, "Unknown: response target mismatch"),
        ({"accepted": "true"}, "Unknown: no valid HEO response"),
    ],
)
async def test_structured_node_acknowledgement_requires_confirmation_and_correlation(
    hass, changes, expected
):
    async def remote(call):
        return {
            "status": 200,
            "content": {
                "service_response": _response(call.data, call.data["operation"], **changes)
            },
        }

    await _setup(hass, custom_remote=remote)
    await _ack(hass)
    await _command(hass, "manual_export_max")
    assert all(_messages(hass)[site].startswith(expected) for site in ("bravo", "charlie"))


async def test_stop_restarts_dispatch_and_late_start_response_cannot_overwrite_results(hass):
    started = asyncio.Event()
    release = asyncio.Event()
    requests = []
    pending = []

    async def finish_export(data):
        await release.wait()
        return {
            "status": 200,
            "content": {"service_response": _response(data, "manual_export_max")},
        }

    async def remote(call):
        requests.append((call.data["operation"], dict(call.data)))
        if call.data["operation"] == "manual_export_max":
            started.set()
            task = asyncio.create_task(finish_export(dict(call.data)))
            pending.append(task)
            return await asyncio.shield(task)
        return {
            "status": 200,
            "content": {"service_response": _response(call.data, call.data["operation"])},
        }

    await _setup(hass, custom_remote=remote)
    await _ack(hass)
    first = asyncio.create_task(
        hass.services.async_call(
            "script", DISPATCH.split(".")[1], {"command": "manual_export_max"}, blocking=True
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    old_request = hass.states.get(REQUEST).state
    await _command(hass, "manual_self_use")
    new_request = hass.states.get(REQUEST).state
    assert new_request != old_request
    stop_results = _messages(hass)
    assert all(message.startswith("Command confirmed:") for message in stop_results.values())
    release.set()
    await asyncio.gather(first, *pending)
    await hass.async_block_till_done()
    assert _messages(hass) == stop_results
    assert len(requests) == 4
    old_times = {data["issued_at"] for command, data in requests if command == "manual_export_max"}
    new_times = {data["issued_at"] for command, data in requests if command == "manual_self_use"}
    assert len(old_times) == len(new_times) == 1
    assert datetime.fromisoformat(new_times.pop()) > datetime.fromisoformat(old_times.pop())


async def test_direct_rest_transport_cannot_choose_another_heo_service(hass):
    command = build_package()["rest_command"]["heo_fleet_bravo"]
    url = Template(command["url"], hass).async_render({"operation": "test_force_charge"})
    assert url.endswith("/unsupported_command?return_response")


@pytest.mark.parametrize(
    "origin",
    [
        "http://user:pass@example.invalid",
        "http://example.invalid/api",
        "http://example.invalid?secret=1",
        "file:///tmp/node",
        "http://example.invalid/#x",
        "http://{{ arbitrary_host }}",
    ],
)
def test_origin_mapping_rejects_credentials_or_non_origin_values(origin):
    with pytest.raises(ValueError):
        build_package(remote_origins={"bravo": origin})
