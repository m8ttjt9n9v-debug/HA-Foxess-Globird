"""Generate the immutable v0.12.26 configuration-surface baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from custom_components.home_energy_orchestrator import const
from custom_components.home_energy_orchestrator.config_flow import ConfigFlow

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPOSITORY_ROOT / "docs" / "maintainability" / "config-contract-v0.12.26.json"
# The read-only monitor is a reviewed additive extension after this baseline.
# Exclude only its exact keys from the historical comparison; current-surface
# tests request the full contract so unrelated additions remain visible.
AEMO_CONFIG_KEYS = frozenset(
    {
        const.CONF_AEMO_MONITOR_ENABLED,
        const.CONF_AEMO_REGION,
        const.CONF_AEMO_EXPORT_THRESHOLD,
        const.CONF_AEMO_IMPORT_THRESHOLD,
    }
)
PRICE_EXPORT_CONFIG_KEYS = frozenset({const.CONF_CRITICAL_EVENT_SELL_ENABLED})
EV_CAPACITY_CONFIG_KEYS = frozenset({
    const.CONF_EV_CAPACITY_SOURCE, const.CONF_EV_CAPACITY_ENTITY,
    const.CONF_EV_CAPACITY_FALLBACK_KWH,
})
AMBER_CONFIG_KEYS = frozenset({const.CONF_AMBER_PRICE_ENTITY, const.CONF_AMBER_PRICE_REGION})
LOAD_CONFIG_KEYS = frozenset({const.CONF_HOUSE_LOAD_SOURCE})
SOLAR_SOAK_CONFIG_KEYS = frozenset({
    const.CONF_EV_SOLAR_SOAK_BATTERY_SOC,
    const.CONF_EV_SOLAR_SOAK_AVERAGE_MINUTES,
    const.CONF_EV_SOLAR_SOAK_ADJUSTMENT_MINUTES,
})
EV_EXPORT_BUFFER_CONFIG_KEYS = frozenset({const.CONF_EV_BEFORE_EXPORT_SOC_BUFFER})
EV_LOCAL_CONNECTION_CONFIG_KEYS = frozenset({const.CONF_EV_LOCAL_CONNECTION})
ADDITIVE_CONFIG_KEYS = (
    AEMO_CONFIG_KEYS | PRICE_EXPORT_CONFIG_KEYS | EV_CAPACITY_CONFIG_KEYS | AMBER_CONFIG_KEYS
    | LOAD_CONFIG_KEYS | SOLAR_SOAK_CONFIG_KEYS | EV_EXPORT_BUFFER_CONFIG_KEYS
    | EV_LOCAL_CONNECTION_CONFIG_KEYS
)
CAPACITY_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-additions-ev-capacity-v1.json"
)
AMBER_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-additions-amber-price-v1.json"
)
LOAD_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-additions-load-power-v1.json"
)
SOLAR_SOAK_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-additions-solar-soak-v1.json"
)
EV_EXPORT_BUFFER_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs/maintainability/config-additions-ev-export-buffer-v1.json"
)
EV_LOCAL_CONNECTION_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs/maintainability/config-additions-ev-local-connection-v1.json"
)


def build_config_contract(*, include_extensions: bool = False) -> dict[str, object]:
    """Return page order plus declared persisted-key vocabulary."""
    for path, keys in (
        (CAPACITY_ADDITIONS_PATH, EV_CAPACITY_CONFIG_KEYS),
        (AMBER_ADDITIONS_PATH, AMBER_CONFIG_KEYS),
        (LOAD_ADDITIONS_PATH, LOAD_CONFIG_KEYS),
        (SOLAR_SOAK_ADDITIONS_PATH, SOLAR_SOAK_CONFIG_KEYS),
        (EV_EXPORT_BUFFER_ADDITIONS_PATH, EV_EXPORT_BUFFER_CONFIG_KEYS),
        (EV_LOCAL_CONNECTION_ADDITIONS_PATH, EV_LOCAL_CONNECTION_CONFIG_KEYS),
    ):
        addition = json.loads(path.read_text(encoding="utf-8"))
        if (
            addition["config_entry_version"] != ConfigFlow.VERSION
            or set(addition["additional_config_keys"]) != keys
        ):
            raise ValueError(f"reviewed configuration identities changed: {path.name}")
    pages = {
        page: [key for key in fields if include_extensions or key not in ADDITIVE_CONFIG_KEYS]
        for page, fields in ConfigFlow._PAGE_FIELDS.items()
    }
    pages = {page: fields for page, fields in pages.items() if fields}
    page_keys = [key for fields in pages.values() for key in fields]
    declared_keys = sorted(
        {
            value
            for name, value in vars(const).items()
            if name.startswith("CONF_")
            and isinstance(value, str)
            and (include_extensions or value not in ADDITIVE_CONFIG_KEYS)
        }
    )
    return {
        "schema_version": 1,
        "release_baseline": "0.12.26",
        "config_entry_version": ConfigFlow.VERSION,
        "page_field_count": len(page_keys),
        "unique_page_field_count": len(set(page_keys)),
        "pages": pages,
        "declared_config_keys": declared_keys,
        "declared_keys_not_on_pages": sorted(set(declared_keys) - set(page_keys)),
    }


def rendered_contract() -> str:
    return json.dumps(build_config_contract(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_contract()
    if args.write:
        parser.error("The release baseline is frozen; review additive configuration separately")
    if args.check:
        if not BASELINE_PATH.is_file() or BASELINE_PATH.read_text(encoding="utf-8") != rendered:
            raise SystemExit(
                "Configuration contract changed; review migration and compatibility impact"
            )
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
