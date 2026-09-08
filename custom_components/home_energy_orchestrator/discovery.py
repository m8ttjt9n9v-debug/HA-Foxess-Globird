"""Conservative entity suggestions for accessible initial configuration."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_DAILY_IMPORT_ENTITY,
    CONF_EV_ACTUAL_CURRENT,
    CONF_EV_AT_HOME,
    CONF_EV_CABLE_CONNECTED,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CHARGING_STATE,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_LIFETIME_ENERGY,
    CONF_EV_SOC,
    CONF_EV_STORED_ENERGY,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_SOLAR_POWER,
)


@dataclass(frozen=True, slots=True)
class DiscoveryEntity:
    """Small registry-independent entity record used by the matcher."""

    entity_id: str
    platform: str
    config_entry_id: str | None
    original_name: str | None = None
    disabled: bool = False


_ROLE_SUFFIXES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    CONF_BATTERY_SOC: ("foxess_modbus", ("sensor",), ("battery_soc",)),
    CONF_BATTERY_POWER: ("foxess_modbus", ("sensor",), ("invbatpower",)),
    CONF_BATTERY_CAPACITY_ENTITY: (
        "foxess_modbus",
        ("sensor",),
        ("bms_kwh_remaining",),
    ),
    CONF_GRID_POWER: ("foxess_modbus", ("sensor",), ("grid_ct",)),
    CONF_DAILY_IMPORT_ENTITY: (
        "foxess_modbus",
        ("sensor",),
        ("grid_consumption_energy_today",),
    ),
    CONF_SOLAR_POWER: (
        "foxess_modbus",
        ("sensor",),
        ("foxess_modbus_pv_power", "pv_power"),
    ),
    CONF_HOUSE_LOAD: ("foxess_modbus", ("sensor",), ("load_power",)),
    CONF_FOXESS_WORK_MODE: ("foxess_modbus", ("select",), ("work_mode",)),
    CONF_FOXESS_FORCE_CHARGE_POWER: (
        "foxess_modbus",
        ("number",),
        ("force_charge_power",),
    ),
    CONF_FOXESS_FORCE_DISCHARGE_POWER: (
        "foxess_modbus",
        ("number",),
        ("force_discharge_power",),
    ),
    CONF_EV_SOC: ("tessie", ("sensor",), ("battery_level",)),
    CONF_EV_AT_HOME: ("tessie", ("device_tracker",), ("location",)),
    CONF_EV_CABLE_CONNECTED: (
        "tessie",
        ("binary_sensor",),
        ("charge_cable",),
    ),
    CONF_EV_CHARGING_STATE: ("tessie", ("sensor",), ("charging",)),
    CONF_EV_ACTUAL_CURRENT: ("tessie", ("sensor",), ("charger_current",)),
    CONF_EV_STORED_ENERGY: ("tessie", ("sensor",), ("energy_remaining",)),
    CONF_EV_LIFETIME_ENERGY: (
        "tessie",
        ("sensor",),
        ("lifetime_energy_used",),
    ),
    CONF_EV_CURRENT_LIMIT: ("tessie", ("number",), ("charge_current",)),
    CONF_EV_CHARGE_LIMIT: ("tessie", ("number",), ("charge_limit",)),
    CONF_EV_CHARGE_SWITCH: ("tessie", ("switch",), ("charge",)),
}


def discover_entity_defaults(entities: list[DiscoveryEntity]) -> dict[str, str]:
    """Return only unambiguous suggestions from one cohort per integration."""
    enabled = [entity for entity in entities if not entity.disabled]
    result: dict[str, str] = {}
    for platform in ("foxess_modbus", "tessie"):
        cohort = _select_cohort(enabled, platform)
        if cohort is None:
            continue
        candidates = [
            entity
            for entity in enabled
            if entity.platform == platform and entity.config_entry_id == cohort
        ]
        for role, (role_platform, domains, suffixes) in _ROLE_SUFFIXES.items():
            if role_platform != platform:
                continue
            match = _unique_best(
                [
                    entity
                    for entity in candidates
                    if entity.entity_id.partition(".")[0] in domains
                ],
                suffixes,
            )
            if match is not None:
                result[role] = match.entity_id
    return result


def _select_cohort(entities: list[DiscoveryEntity], platform: str) -> str | None:
    grouped: dict[str, list[DiscoveryEntity]] = defaultdict(list)
    for entity in entities:
        if entity.platform == platform and entity.config_entry_id:
            grouped[entity.config_entry_id].append(entity)
    scored = [
        (
            sum(
                1
                for role_platform, domains, suffixes in _ROLE_SUFFIXES.values()
                if role_platform == platform
                if _unique_best(
                    [
                        entity
                        for entity in group
                        if entity.entity_id.partition(".")[0] in domains
                    ],
                    suffixes,
                )
                is not None
            ),
            entry_id,
        )
        for entry_id, group in grouped.items()
    ]
    if not scored:
        return None
    best_score = max(score for score, _entry_id in scored)
    winners = [entry_id for score, entry_id in scored if score == best_score]
    return winners[0] if best_score > 0 and len(winners) == 1 else None


def _unique_best(
    entities: list[DiscoveryEntity], suffixes: tuple[str, ...]
) -> DiscoveryEntity | None:
    ranked = sorted(
        ((_match_score(entity, suffixes), entity) for entity in entities),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] <= 0:
        return None
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


def _match_score(entity: DiscoveryEntity, suffixes: tuple[str, ...]) -> int:
    object_id = entity.entity_id.partition(".")[2].casefold()
    original = (entity.original_name or "").casefold().replace(" ", "_")
    for suffix in suffixes:
        if object_id == suffix:
            return 100
        if object_id.endswith(f"_{suffix}"):
            return 90
        if original == suffix:
            return 80
    return 0
