"""Phase 4 canonical presentation-boundary tests."""

from __future__ import annotations

import pytest

from scripts import presentation_contract
from scripts.presentation_contract import SENSOR_SOURCE, validate_presentation_contract


def test_presentation_consumers_use_only_the_canonical_read_model() -> None:
    validate_presentation_contract()


@pytest.mark.parametrize(
    "bypass",
    [
        "read_model.ev.unreviewed_capacity_attributes()",
        "self.coordinator.hass.states.get('sensor.capacity')",
        "dict(source=self.coordinator.ev_controller.capacity_observation.source)",
    ],
)
def test_capacity_attributes_allow_only_the_explicit_canonical_route(monkeypatch, tmp_path, bypass):
    source = SENSOR_SOURCE.read_text(encoding="utf-8")
    assert source.count("read_model.ev.capacity_attributes()") == 1
    source = source.replace("read_model.ev.capacity_attributes()", bypass)
    path = tmp_path / "sensor.py"
    path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(presentation_contract, "SENSOR_SOURCE", path)
    with pytest.raises(ValueError, match="non-canonical calls"):
        validate_presentation_contract()


def test_capacity_attribute_route_still_prohibits_presentation_math(monkeypatch, tmp_path):
    source = SENSOR_SOURCE.read_text(encoding="utf-8").replace(
        "read_model.ev.capacity_attributes()", "read_model.ev.capacity_attributes() + 1"
    )
    path = tmp_path / "sensor.py"
    path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(presentation_contract, "SENSOR_SOURCE", path)
    with pytest.raises(ValueError, match="route projections, not calculate"):
        validate_presentation_contract()
