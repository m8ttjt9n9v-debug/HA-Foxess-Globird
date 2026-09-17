"""Generate the immutable v0.12.26 configuration-surface baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from custom_components.home_energy_orchestrator import const
from custom_components.home_energy_orchestrator.config_flow import ConfigFlow

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPOSITORY_ROOT / "docs" / "maintainability" / "config-contract-v0.12.26.json"


def build_config_contract() -> dict[str, object]:
    """Return page order plus declared persisted-key vocabulary."""
    pages = {page: list(fields) for page, fields in ConfigFlow._PAGE_FIELDS.items()}
    page_keys = [key for fields in pages.values() for key in fields]
    declared_keys = sorted(
        {
            value
            for name, value in vars(const).items()
            if name.startswith("CONF_") and isinstance(value, str)
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
        BASELINE_PATH.write_text(rendered, encoding="utf-8")
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
