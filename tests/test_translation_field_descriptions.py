"""Keep every translated field description paired with its sibling label."""

import json
from pathlib import Path

import pytest

TRANSLATIONS = (
    Path(__file__).resolve().parents[1]
    / "custom_components/home_energy_orchestrator/translations"
)


def _description_pages(value, path=()):
    if isinstance(value, dict):
        if "data_description" in value:
            yield path, value
        for key, child in value.items():
            yield from _description_pages(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _description_pages(child, (*path, str(index)))


@pytest.mark.parametrize("translation", sorted(TRANSLATIONS.glob("*.json")), ids=lambda p: p.name)
def test_every_field_description_has_a_sibling_data_label(translation):
    document = json.loads(translation.read_text(encoding="utf-8"))
    for path, page in _description_pages(document):
        descriptions = page["data_description"]
        labels = page.get("data", {})
        assert isinstance(descriptions, dict) and isinstance(labels, dict), ".".join(path)
        missing = set(descriptions) - set(labels)
        assert not missing, (
            f"{translation.name}:{'.'.join(path)} has descriptions without sibling data labels: "
            f"{sorted(missing)}"
        )
