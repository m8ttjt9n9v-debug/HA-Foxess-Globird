"""Validate the reviewed-in-slices v0.12.26 entity semantic worksheet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.entity_attribute_contract import build_entity_attribute_contract
from scripts.entity_contract import build_entity_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "maintainability"
    / "entity-semantics-v0.12.26.json"
)
MANUAL_EXTENSIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-semantics-manual-inverter-v1.json"
)
AEMO_EXTENSIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-semantics-aemo-monitor-v1.json"
)
PRICE_EXTENSIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-semantics-price-export-v1.json"
)
TRIP_EXTENSIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-semantics-trip-charge-v1.json"
)
EV_CAPACITY_EXTENSIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-semantics-ev-capacity-v1.json"
)

_REQUIRED_FIELDS = {
    "key",
    "definition",
    "producer",
    "role",
    "unit_and_sign",
    "time_basis",
    "availability",
    "state_vocabulary",
    "audience",
    "equivalents",
    "consumers",
    "decision",
    "review_status",
}
_ROLES = {
    "accumulator",
    "actuator_setting",
    "calculation",
    "canonical_measurement",
    "configuration",
    "external_result",
    "forecast",
    "learning_output",
    "operator_action",
    "plan",
    "session_state",
    "target",
}
_AUDIENCES = {"primary", "advanced", "diagnostic"}
_DECISIONS = {"retain", "relabel", "replace", "deprecate"}
_REVIEW_STATES = {"engineering_draft", "owner_approved"}
_EQUIVALENT_KEYS = {"foxess", "globird", "tessie"}


def load_semantic_contract() -> dict[str, Any]:
    """Merge explicit additions while preserving every reviewed baseline record."""
    baseline = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
    records = list(baseline["entities"])
    merged_profiles = dict(baseline["attribute_profiles"])
    known_keys = {record["key"] for record in records}
    for path in (
        MANUAL_EXTENSIONS_PATH, AEMO_EXTENSIONS_PATH, PRICE_EXTENSIONS_PATH,
        TRIP_EXTENSIONS_PATH, EV_CAPACITY_EXTENSIONS_PATH,
    ):
        extension = json.loads(path.read_text(encoding="utf-8"))
        if extension.get("schema_version") != baseline.get("schema_version"):
            raise ValueError("semantic extension schema does not match the baseline")
        entities = extension.get("entities")
        profiles = extension.get("attribute_profiles")
        if not isinstance(entities, list) or not isinstance(profiles, dict):
            raise ValueError("semantic extension needs entities and attribute_profiles")
        if extension.get("entity_count") != len(entities):
            raise ValueError("semantic extension entity_count does not match its records")
        if any(record["key"] in known_keys for record in entities):
            raise ValueError("semantic extensions cannot replace reviewed baseline records")
        if merged_profiles.keys() & profiles.keys():
            raise ValueError("semantic extensions cannot replace reviewed attribute profiles")
        records.extend(entities)
        known_keys.update(record["key"] for record in entities)
        merged_profiles.update(profiles)
        profile_additions = extension.get("attribute_profile_additions", {})
        if not isinstance(profile_additions, dict):
            raise ValueError("semantic attribute profile additions must be an object")
        for name, attributes in profile_additions.items():
            if name not in merged_profiles or not isinstance(attributes, dict) or not attributes:
                raise ValueError("semantic additions need a retained profile and new attributes")
            retained = merged_profiles[name]
            if retained["attributes"].keys() & attributes.keys():
                raise ValueError("semantic additions cannot replace reviewed public keys")
            merged_profiles[name] = {
                **retained,
                "attributes": {**retained["attributes"], **attributes},
            }
        revisions = extension.get("entity_revisions", [])
        if extension.get("entity_revision_count", 0) != len(revisions):
            raise ValueError("semantic revision count does not match its records")
        if revisions:
            if path != EV_CAPACITY_EXTENSIONS_PATH or len(revisions) != 1:
                raise ValueError("semantic revisions require the reviewed capacity extension")
            revision = revisions[0]
            if revision.get("key") != "ev_usable_capacity":
                raise ValueError("capacity semantic revision must retain its entity identity")
            retained = next(record for record in records if record["key"] == revision["key"])
            if retained["definition"] != revision.get("previous_definition"):
                raise ValueError(
                    "capacity semantic revision does not match its reviewed predecessor"
                )
            fields = revision.get("fields")
            allowed = (_REQUIRED_FIELDS - {"key"}) | {"attribute_profile", "proposed_display_name"}
            if not isinstance(fields, dict) or not fields or fields.keys() - allowed:
                raise ValueError("capacity semantic revision contains unreviewed fields")
            records = [
                {**record, **fields} if record["key"] == revision["key"] else record
                for record in records
            ]
    added_count = len(records) - len(baseline["entities"])
    return {
        **baseline,
        "entities": records,
        "attribute_profiles": merged_profiles,
        "reviewed_entity_count": baseline["reviewed_entity_count"] + added_count,
        "total_entity_count": baseline["total_entity_count"] + added_count,
    }


def entities_awaiting_review(contract: dict[str, Any] | None = None) -> list[str]:
    """Derive, rather than persist, the remaining identity-contract keys."""
    contract = load_semantic_contract() if contract is None else contract
    reviewed = {record["key"] for record in contract.get("entities", [])}
    identities = {item["key"] for item in build_entity_contract()["entities"]}
    return sorted(identities - reviewed)


def validate_semantic_contract(contract: dict[str, Any] | None = None) -> None:
    """Reject incomplete, stale or structurally ambiguous semantic records."""
    contract = load_semantic_contract() if contract is None else contract
    identity = build_entity_contract()
    identities = {item["key"]: item for item in identity["entities"]}
    attribute_entities = {
        item["entity_key"]: frozenset(item["custom_attributes"])
        for item in build_entity_attribute_contract()["entities"]
    }
    profiles = contract.get("attribute_profiles")
    if not isinstance(profiles, dict):
        raise ValueError("attribute_profiles must be an object")
    for profile_name, profile in profiles.items():
        attributes = profile.get("attributes") if isinstance(profile, dict) else None
        if (
            not isinstance(profile_name, str)
            or not isinstance(attributes, dict)
            or not attributes
        ):
            raise ValueError("every attribute profile needs a non-empty attributes object")
        if any(
            not isinstance(key, str) or not str(value).strip()
            for key, value in attributes.items()
        ):
            raise ValueError(f"attribute profile {profile_name!r} contains an empty definition")

    records = contract.get("entities")
    if not isinstance(records, list):
        raise ValueError("entities must be a list")
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("entity semantic records must be objects")
        missing = _REQUIRED_FIELDS - record.keys()
        if missing:
            raise ValueError(f"semantic record is missing {sorted(missing)}")
        key = record["key"]
        if key not in identities:
            raise ValueError(f"semantic record references unknown entity key {key!r}")
        if key in seen:
            raise ValueError(f"duplicate semantic record for {key!r}")
        seen.add(key)
        if record["role"] not in _ROLES:
            raise ValueError(f"invalid semantic role for {key!r}")
        if record["audience"] not in _AUDIENCES:
            raise ValueError(f"invalid audience for {key!r}")
        if record["decision"] not in _DECISIONS:
            raise ValueError(f"invalid decision for {key!r}")
        proposed_name = record.get("proposed_display_name")
        if record["decision"] == "relabel":
            if not isinstance(proposed_name, str) or not proposed_name.strip():
                raise ValueError(f"relabel decision lacks proposed_display_name for {key!r}")
        elif proposed_name is not None:
            raise ValueError(f"non-relabel record has proposed_display_name for {key!r}")
        if record["review_status"] not in _REVIEW_STATES:
            raise ValueError(f"invalid review status for {key!r}")
        if set(record["equivalents"]) != _EQUIVALENT_KEYS:
            raise ValueError(f"equivalents are incomplete for {key!r}")
        for field in (
            "definition",
            "producer",
            "unit_and_sign",
            "time_basis",
            "availability",
            "state_vocabulary",
        ):
            if not isinstance(record[field], str) or not record[field].strip():
                raise ValueError(f"{field} is empty for {key!r}")
        consumers = record["consumers"]
        if not isinstance(consumers, list) or not consumers or any(
            not isinstance(item, str) or not item.strip() for item in consumers
        ):
            raise ValueError(f"consumers are incomplete for {key!r}")

        expected_attributes = attribute_entities.get(key)
        profile_name = record.get("attribute_profile")
        if expected_attributes is None and profile_name is not None:
            raise ValueError(f"{key!r} declares an attribute profile but has no custom attributes")
        if expected_attributes is not None:
            if profile_name not in profiles:
                raise ValueError(f"{key!r} requires a known attribute profile")
            actual_attributes = frozenset(profiles[profile_name]["attributes"])
            if actual_attributes != expected_attributes:
                raise ValueError(f"attribute profile does not match public keys for {key!r}")

    if contract.get("reviewed_entity_count") != len(records):
        raise ValueError("reviewed_entity_count does not match the worksheet")
    if contract.get("total_entity_count") != identity["entity_count"]:
        raise ValueError("total_entity_count does not match the identity contract")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    contract = load_semantic_contract()
    validate_semantic_contract(contract)
    if not args.check:
        print(json.dumps(contract, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
