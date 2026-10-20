"""Reusable Fleet rows read the shared qualified split, including true zero."""
from pathlib import Path

import pytest
import yaml
from homeassistant.helpers.template import Template

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("site", ["alpha", "bravo", "charlie"])
async def test_fleet_example_uses_qualified_attributes_not_private_helpers(hass, site):
    config = yaml.safe_load((ROOT / "examples/fleet-dashboard.yaml").read_text())
    index = {"alpha": 1, "bravo": 2, "charlie": 3}[site]
    content = config["views"][0]["sections"][index]["cards"][0]["content"]
    assert "r('house_load'" not in content
    assert "r('ev_load'" not in content
    entity = f"sensor.fleet_site_{site}_summary"
    hass.states.async_set(entity, "observe", {
        "house_load_excluding_ev_kw": 0, "ev_charging_power_kw": 3.45,
        "load_power_reason": "ev_subtracted_once",
    })
    rendered = Template(content, hass).async_render()
    assert "| House / EV (est.) | 0 / 3.45 kW |" in rendered
    hass.states.async_set(entity, "observe", {"ev_charging_power_kw": None})
    rendered = Template(content, hass).async_render()
    assert "| House / EV (est.) | — / — kW |" in rendered
