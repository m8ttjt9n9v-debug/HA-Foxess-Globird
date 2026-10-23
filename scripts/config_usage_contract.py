"""Inventory direct persisted-configuration access in integration source."""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any

from custom_components.home_energy_orchestrator import const
from scripts.config_contract import (
    ADDITIVE_CONFIG_KEYS,
    AMBER_CONFIG_KEYS,
    EV_CAPACITY_CONFIG_KEYS,
    EV_EXPORT_BUFFER_CONFIG_KEYS,
    EV_IMPORT_CONFIG_KEYS,
    EV_LOCAL_CONNECTION_CONFIG_KEYS,
    EV_SURPLUS_REARM_CONFIG_KEYS,
    LOAD_CONFIG_KEYS,
    SOLAR_SOAK_CONFIG_KEYS,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "custom_components" / "home_energy_orchestrator"
BASELINE_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "maintainability"
    / "config-usage-contract-v0.12.26.json"
)
ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-usage-additions-price-export-v1.json"
)
RELOCATIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-usage-relocations-trip-charge-v1.json"
)
CAPACITY_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-usage-additions-ev-capacity-v1.json"
)
AMBER_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-usage-additions-amber-price-v1.json"
)
LOAD_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-usage-additions-load-power-v1.json"
)
SOLAR_SOAK_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-usage-additions-solar-soak-v1.json"
)
EV_EXPORT_BUFFER_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs/maintainability/config-usage-additions-ev-export-buffer-v1.json"
)
EV_LOCAL_CONNECTION_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs/maintainability/config-usage-additions-ev-local-connection-v1.json"
)
EV_IMPORT_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs/maintainability/config-usage-additions-ev-import-v1.json"
)
EV_BACKFILL_TIMING_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs/maintainability/config-usage-additions-ev-backfill-timing-v1.json"
)
EV_SURPLUS_REARM_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs/maintainability/config-usage-additions-ev-surplus-rearm-v1.json"
)
RECONFIGURE_TRANSITION_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-usage-transition-reconfigure-v1.json"
)
_CONFIG_ACCESS_METHODS = {
    "get",
    "pop",
    "setdefault",
    "update_config_value",
    "update_persisted_config_value",
}
_BOUNDARY_FILES = {
    "__init__.py",
    "config_flow.py",
    "configuration.py",
    "aemo_monitor_controls.py",
}
_RUNTIME_CONFIG_RECEIVERS = {"self.config", "self.coordinator.config"}


class _UsageVisitor(ast.NodeVisitor):
    def __init__(self, source: Path, constants: dict[str, str]) -> None:
        self.source = source
        self.constants = constants
        self.constants_by_value = {
            value: name for name, value in sorted(constants.items())
        }
        self.scope: list[str] = []
        self.records: list[dict[str, Any]] = []

    def _is_runtime_config_receiver(self, receiver_text: str) -> bool:
        if receiver_text in _RUNTIME_CONFIG_RECEIVERS:
            return True
        return (
            receiver_text == "config"
            and self.source.name == "coordinator.py"
            and ".".join(self.scope) == "EnergyCoordinator.__init__"
        )

    def _record(
        self,
        constant_node: ast.expr,
        receiver: ast.expr,
        access: str,
    ) -> None:
        receiver_text = ast.unparse(receiver)
        constant: str | None = None
        key: str | None = None
        if isinstance(constant_node, ast.Name) and constant_node.id in self.constants:
            constant = constant_node.id
            key = self.constants[constant]
        elif (
            isinstance(constant_node, ast.Constant)
            and isinstance(constant_node.value, str)
            and self._is_runtime_config_receiver(receiver_text)
        ):
            key = constant_node.value
            constant = self.constants_by_value.get(key)
        elif not self._is_runtime_config_receiver(receiver_text):
            return
        relative = self.source.relative_to(REPOSITORY_ROOT).as_posix()
        scope = ".".join(self.scope) or "<module>"
        mutation_boundary = (
            self.source.name == "coordinator.py"
            and scope == "EnergyCoordinator.update_config_value"
            and receiver_text == "self.config"
            and access in {"pop", "subscript_store"}
        )
        kind = (
            "mutation_boundary"
            if mutation_boundary
            else (
                "managed_mutation"
                if access in {"update_config_value", "update_persisted_config_value"}
                else "raw_mapping"
            )
        )
        self.records.append(
            {
                "constant": constant,
                "key": key,
                "source": relative,
                "scope": scope,
                "receiver": receiver_text,
                "access": access,
                "kind": kind,
                "layer": (
                    "boundary"
                    if self.source.name in _BOUNDARY_FILES or mutation_boundary
                    else "runtime"
                ),
                **(
                    {"key_expression": ast.unparse(constant_node)}
                    if key is None
                    else {}
                ),
            }
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _CONFIG_ACCESS_METHODS
            and node.args
        ):
            key_index = 1 if node.func.attr == "update_persisted_config_value" else 0
            if len(node.args) > key_index:
                self._record(node.args[key_index], node.func.value, node.func.attr)
            if node.func.attr in {
                "update_config_value",
                "update_persisted_config_value",
            }:
                for keyword in node.keywords:
                    if keyword.arg == "remove_key":
                        self._record(
                            keyword.value,
                            node.func.value,
                            node.func.attr,
                        )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:  # noqa: N802
        context = type(node.ctx).__name__.lower()
        self._record(node.slice, node.value, f"subscript_{context}")
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:  # noqa: N802
        left = node.left
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            if isinstance(operator, (ast.In, ast.NotIn)):
                access = "not_in" if isinstance(operator, ast.NotIn) else "in"
                self._record(left, comparator, access)
            left = comparator
        self.generic_visit(node)


def build_config_usage_contract(*, include_extensions: bool = False) -> dict[str, Any]:
    """Return a deterministic AST inventory of direct config-key access."""
    constants = {
        name: value
        for name, value in vars(const).items()
        if name.startswith("CONF_") and isinstance(value, str)
    }
    records: list[dict[str, Any]] = []
    for source in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        visitor = _UsageVisitor(source, constants)
        visitor.visit(tree)
        records.extend(visitor.records)
    if not include_extensions:
        rearm = json.loads(EV_SURPLUS_REARM_ADDITIONS_PATH.read_text(encoding="utf-8"))
        accesses = [item for item in records if item["key"] in EV_SURPLUS_REARM_CONFIG_KEYS]
        if rearm["access_count"] != len(rearm["accesses"]) or sorted(
            json.dumps(item, sort_keys=True) for item in accesses
        ) != sorted(json.dumps(item, sort_keys=True) for item in rearm["accesses"]):
            raise ValueError("Reviewed EV surplus rearm configuration usage changed")
        for reviewed in rearm["accesses"]:
            records.remove(reviewed)
        timing = json.loads(EV_BACKFILL_TIMING_ADDITIONS_PATH.read_text(encoding="utf-8"))
        if timing["schema_version"] != 1 or timing["access_count"] != len(timing["accesses"]):
            raise ValueError("Invalid backfill timing configuration usage addition")
        for reviewed in timing["accesses"]:
            if reviewed not in records:
                raise ValueError("Reviewed backfill timing configuration usage changed")
            records.remove(reviewed)
        imported = json.loads(EV_IMPORT_ADDITIONS_PATH.read_text(encoding="utf-8"))
        accesses = [item for item in records if item["key"] in EV_IMPORT_CONFIG_KEYS]
        if imported["access_count"] != len(imported["accesses"]) or sorted(
            json.dumps(item, sort_keys=True) for item in accesses
        ) != sorted(json.dumps(item, sort_keys=True) for item in imported["accesses"]):
            raise ValueError("reviewed EV import configuration usage changed")
        for reviewed in imported["accesses"]:
            records.remove(reviewed)
        local = json.loads(EV_LOCAL_CONNECTION_ADDITIONS_PATH.read_text(encoding="utf-8"))
        accesses = [item for item in records if item['key'] in EV_LOCAL_CONNECTION_CONFIG_KEYS]
        if local.get("access_count") != len(local["accesses"]) or sorted(
            json.dumps(item, sort_keys=True) for item in accesses
        ) != sorted(json.dumps(item, sort_keys=True) for item in local["accesses"]):
            raise ValueError("reviewed local EV connection configuration usage changed")
        for reviewed in local["accesses"]:
            records.remove(reviewed)
        buffer = json.loads(EV_EXPORT_BUFFER_ADDITIONS_PATH.read_text(encoding="utf-8"))
        accesses = [item for item in records if item['key'] in EV_EXPORT_BUFFER_CONFIG_KEYS]
        if buffer.get('access_count') != len(buffer['accesses']) or sorted(
            json.dumps(item, sort_keys=True) for item in accesses
        ) != sorted(json.dumps(item, sort_keys=True) for item in buffer['accesses']):
            raise ValueError('reviewed EV export buffer configuration usage changed')
        for reviewed in buffer['accesses']:
            records.remove(reviewed)
        solar_soak = json.loads(SOLAR_SOAK_ADDITIONS_PATH.read_text(encoding="utf-8"))
        soak_accesses = [item for item in records if item["key"] in SOLAR_SOAK_CONFIG_KEYS]
        if solar_soak.get("access_count") != len(solar_soak["accesses"]) or sorted(
            json.dumps(item, sort_keys=True) for item in soak_accesses
        ) != sorted(json.dumps(item, sort_keys=True) for item in solar_soak["accesses"]):
            raise ValueError("reviewed solar-soak configuration usage changed")
        for reviewed in solar_soak["accesses"]:
            records.remove(reviewed)
        load = json.loads(LOAD_ADDITIONS_PATH.read_text(encoding="utf-8"))
        load_accesses = [item for item in records if item["key"] in LOAD_CONFIG_KEYS]
        if load.get("access_count") != len(load["accesses"]) or sorted(
            json.dumps(item, sort_keys=True) for item in load_accesses
        ) != sorted(json.dumps(item, sort_keys=True) for item in load["accesses"]):
            raise ValueError("reviewed load-power configuration usage changed")
        for reviewed in load["accesses"]:
            records.remove(reviewed)
        capacity = json.loads(CAPACITY_ADDITIONS_PATH.read_text(encoding="utf-8"))
        capacity_accesses = [
            item
            for item in records
            if item["key"] in EV_CAPACITY_CONFIG_KEYS
            or item["scope"].startswith("EvCapacitySettings.")
        ]
        if capacity.get("access_count") != len(capacity["accesses"]) or sorted(
            json.dumps(item, sort_keys=True) for item in capacity_accesses
        ) != sorted(json.dumps(item, sort_keys=True) for item in capacity["accesses"]):
            raise ValueError("reviewed EV capacity configuration usage changed")
        for reviewed in capacity["accesses"]:
            records.remove(reviewed)
        amber = json.loads(AMBER_ADDITIONS_PATH.read_text(encoding="utf-8"))
        amber_accesses = [item for item in records if item["key"] in AMBER_CONFIG_KEYS]
        if amber.get("access_count") != len(amber["accesses"]) or sorted(
            json.dumps(item, sort_keys=True) for item in amber_accesses
        ) != sorted(json.dumps(item, sort_keys=True) for item in amber["accesses"]):
            raise ValueError("reviewed Amber price configuration usage changed")
        for reviewed in amber["accesses"]:
            records.remove(reviewed)
        # Preserve the fixed baseline while auditing the exact monitor extension
        # separately. No unknown or unrelated key is exempt from comparison.
        records = [item for item in records if item["key"] not in ADDITIVE_CONFIG_KEYS]
        extension = json.loads(ADDITIONS_PATH.read_text(encoding="utf-8"))
        if extension.get("access_count") != len(extension["accesses"]):
            raise ValueError("configuration usage addition count does not match its records")
        for reviewed in extension["accesses"]:
            if reviewed not in records:
                raise ValueError("reviewed configuration usage addition is missing")
            records.remove(reviewed)
        relocations = json.loads(RELOCATIONS_PATH.read_text(encoding="utf-8"))
        if relocations.get("relocation_count") != len(relocations["relocations"]):
            raise ValueError("configuration relocation count does not match its records")
        # Compare the frozen inventory after validating each exact moved write.
        # No new key, receiver, access kind or unrelated method is exempted.
        for relocation in relocations["relocations"]:
            before, after = relocation["before"], relocation["after"]
            if after not in records or before in records:
                raise ValueError("reviewed configuration mutation relocation changed")
            if {k: v for k, v in before.items() if k != "scope"} != {
                k: v for k, v in after.items() if k != "scope"
            }:
                raise ValueError("configuration relocation must preserve the mutation boundary")
            records.remove(after)
            records.append(before)
        transition = json.loads(RECONFIGURE_TRANSITION_PATH.read_text(encoding="utf-8"))
        # Exact boundary-only reads/writes moved to current-value review. Do not
        # exempt a whole file, configuration key, or any runtime access.
        for item in (*transition["before"], *transition["after"]):
            if item["source"] != "custom_components/home_energy_orchestrator/config_flow.py" or (
                item["layer"] != "boundary" or item["kind"] != "raw_mapping"
            ):
                raise ValueError("reconfigure transition must remain at the flow boundary")
        for item in transition["after"]:
            if item not in records:
                raise ValueError("reviewed reconfigure access is missing")
            records.remove(item)
        for item in transition["before"]:
            if item in records:
                raise ValueError("obsolete reconfigure access returned")
            records.append(item)
    records.sort(
        key=lambda item: (
            item["source"],
            item["scope"],
            item["constant"] or "",
            item["access"],
            item["receiver"],
        )
    )
    by_layer = Counter(item["layer"] for item in records)
    by_kind = Counter(item["kind"] for item in records)
    raw_by_layer = Counter(
        item["layer"] for item in records if item["kind"] == "raw_mapping"
    )
    by_source = Counter(item["source"] for item in records)
    return {
        "schema_version": 4,
        "release_baseline": "0.12.26",
        "access_count": len(records),
        "key_count": len(
            {item["key"] for item in records if item["key"] is not None}
        ),
        "dynamic_access_count": sum(item["key"] is None for item in records),
        "accesses_by_layer": dict(sorted(by_layer.items())),
        "accesses_by_kind": dict(sorted(by_kind.items())),
        "raw_accesses_by_layer": dict(sorted(raw_by_layer.items())),
        "accesses_by_source": dict(sorted(by_source.items())),
        "accesses": records,
    }


def rendered_contract() -> str:
    return json.dumps(build_config_usage_contract(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_contract()
    if args.write:
        BASELINE_PATH.write_text(rendered, encoding="utf-8")
    if args.check and (
        not BASELINE_PATH.is_file() or BASELINE_PATH.read_text(encoding="utf-8") != rendered
    ):
        raise SystemExit("Configuration usage contract changed; review and regenerate")
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
