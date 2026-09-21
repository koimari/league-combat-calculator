"""Public response serializers for engine fight results.

One home for the stable wire shape: ``serialize_fight_result`` renders a
single engine result and ``aggregate_public_results`` combines several
per-target results into the roster response.  The aggregate is driven by
``_PUBLIC_FIELD_POLICIES``, the same schema table that defines the
single-target key set, so a future key added to one serializer cannot
silently disappear from the other (see tests/test_endpoint_parity.py).
"""

import math
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from .capabilities import FIGHT_EFFECTIVE_STATS
from .champion_loadout import ChampionLoadout
from .champions import engine_registration_kind
from .timeline_coverage import (
    aggregate_timeline_coverage,
)

ICON_HOSTS = frozenset(
    {
        "cdn.communitydragon.org",
        "ddragon.leagueoflegends.com",
        "raw.communitydragon.org",
    }
)


def https_icon(url: object) -> str:
    """Return one allow-listed HTTPS icon URL or an empty public value.

    ``url`` is a cached icon field, so anything but a string is unsourced.
    """
    if not isinstance(url, str):
        return ""
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ICON_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        return ""
    return url


def public_engine_mode(champion_name: str) -> str:
    """Expose the public certification mode for one registered engine."""
    registration = engine_registration_kind(champion_name)
    if registration == "reviewed_module":
        return "reviewed_event_order"
    return "unregistered"


def public_loadout_summary(loadout: ChampionLoadout) -> dict[str, Any]:
    """Sanitize one resolved loadout for the stable browser response."""
    summary = loadout.public_summary()
    summary["icon"] = https_icon(summary["icon"])
    summary["item_icons"] = [https_icon(icon) for icon in summary["item_icons"]]
    summary["engine_registration"] = engine_registration_kind(summary["champion"])
    return summary


def _public_event_time(event: Mapping[str, object]) -> float | None:
    """Return a finite event timestamp, withholding malformed public rows."""
    if "time" not in event:
        return None
    value = event["time"]
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return round(parsed, 3)


def _target_effective_health(result: Mapping[str, object]) -> float:
    """Estimate one target's effective health from a per-target result.

    Max health, shields and healing received sum to the combat ledger's
    effective-health definition, so overkill compares across both shapes.
    """
    return (
        float(result.get("target_effective_max_health", 0.0))
        + float(result.get("shield_absorbed", 0.0))
        + float(result.get("target_healing_received", 0.0))
    )


def _legacy_overkill(result: Mapping[str, object]) -> float:
    """Raw total damage beyond the target's effective health, which the
    per-target engine can exceed because it keeps swinging after defeat."""
    return max(
        0.0, float(result.get("total_damage", 0.0)) - _target_effective_health(result)
    )


def _public_damage_event(event: Mapping[str, object]) -> dict[str, object]:
    """Keep typed interaction fields on the public damage ledger."""
    # These four ARE on every internal damage row the engine builds
    # (docs/receipts/internal-row-census.json, 3,960 rows over 173
    # champions), and they still keep their defaults. This serializer's
    # contract is to TOLERATE a malformed row and withhold it, which
    # tests/test_public_response.py pins by handing it partial events on
    # purpose. Indexing here turns graceful withholding into a crash at the
    # API boundary, so the census licenses the read and the contract forbids
    # it (clause 5).
    row: dict[str, object] = {
        "time": _public_event_time(event),
        "source": str(event.get("source_key", "")),
        "damage_type": str(event.get("damage_type", "")),
        "damage": round(float(event.get("damage", 0.0)), 1),
        "phase": str(event.get("phase", "")),
    }
    for key in (
        "amplified",
        "basic_attack",
        "cc_kind",
        "cc_duration",
        "control_source_atoms",
        "damage_over_time",
        "deathfire_category",
        "event_precision",
        "skillshot",
        "trigger_source",
    ):
        if key not in event:
            continue
        value = event[key]
        if key in {"cc_duration", "time"} and value is not None:
            value = round(float(value), 3)
        row[key] = value
    if "trigger_time" in event:
        row["trigger_time"] = _public_event_time({"time": event.get("trigger_time")})
    return row


def serialize_fight_result(result: Mapping[str, object]) -> dict[str, Any]:
    """Translate one engine result into the stable public response shape."""
    breakdown = result.get("breakdown", {})
    api_breakdown = {}
    for key, entry in breakdown.items():
        has_damage = entry.get("total_damage", 0.0) > 0
        total_amount = entry.get("total_amount", 0.0)
        has_amount = isinstance(total_amount, (int, float)) and total_amount > 0
        if not (has_damage or has_amount or "detail" in entry):
            continue
        row = {
            "name": entry.get("name", key),
            "total_damage": round(entry.get("total_damage", 0.0), 1),
            "total_amount": round(total_amount, 1) if has_amount else None,
            "casts": entry.get("casts", None),
            "count": entry.get("count", None),
            "unit": entry.get("unit", None),
            "damage_per_hit": (
                round(entry["damage_per_hit"], 1) if "damage_per_hit" in entry else None
            ),
            "num_crits": entry.get("num_crits", None),
            "num_non_crits": entry.get("num_non_crits", None),
            "crit_damage_per_hit": (
                round(entry["crit_damage_per_hit"], 1)
                if entry.get("crit_damage_per_hit") is not None
                else None
            ),
            "non_crit_damage_per_hit": (
                round(entry["non_crit_damage_per_hit"], 1)
                if entry.get("non_crit_damage_per_hit") is not None
                else None
            ),
        }
        if has_amount:
            row["amount_per_proc"] = (
                round(entry["amount_per_proc"], 1)
                if entry.get("amount_per_proc") is not None
                else None
            )
            row["proc_times"] = list(entry.get("proc_times", []))
            row["output_type"] = "mana" if entry.get("unit") == "mana" else "health"
        for display_key in ("detail", "damage_display"):
            if display_key in entry:
                row[display_key] = entry[display_key]
        temporary_lethality = entry.get("temporary_lethality")
        if isinstance(temporary_lethality, Mapping):
            # Preserve the engine's sourced state receipt so the frontend can
            # explain a temporary penetration window instead of collapsing it
            # into an unexplained aggregate damage number.
            row["temporary_lethality"] = dict(temporary_lethality)
        if "targeting" in entry:
            row["targeting"] = dict(entry["targeting"])
        for receipt_key in (
            "amp_delay_seconds",
            "amp_ratio",
            "amplified_tick_count",
            "duration_by_category",
            "pet_damage_category_modeled",
            "tick_interval_seconds",
            "trigger_events",
        ):
            if receipt_key not in entry:
                continue
            value = entry[receipt_key]
            if isinstance(value, Mapping):
                row[receipt_key] = dict(value)
            elif isinstance(value, list):
                row[receipt_key] = [
                    dict(item) if isinstance(item, Mapping) else item for item in value
                ]
            else:
                row[receipt_key] = value
        api_breakdown[key] = row

    return {
        "champion_stats": result["champion_stats"],
        "champion_stats_state": FIGHT_EFFECTIVE_STATS,
        "total_damage": round(result.get("total_damage", 0.0), 1),
        "health_damage": round(result.get("health_damage", 0.0), 1),
        "shield_absorbed": round(result.get("shield_absorbed", 0.0), 1),
        "magic_shield_absorbed": round(result.get("magic_shield_absorbed", 0.0), 1),
        "physical_shield_absorbed": round(
            result.get("physical_shield_absorbed", 0.0), 1
        ),
        "general_shield_absorbed": round(result.get("general_shield_absorbed", 0.0), 1),
        "threshold_shield_absorbed": round(
            result.get("threshold_shield_absorbed", 0.0), 1
        ),
        "threshold_health_triggered": bool(
            result.get("threshold_health_triggered", False)
        ),
        "threshold_health_bonus_gained": round(
            result.get("threshold_health_bonus_gained", 0.0), 1
        ),
        "target_healing_received": round(result.get("target_healing_received", 0.0), 1),
        "target_ending_health": round(result.get("target_ending_health", 0.0), 1),
        "target_effective_max_health": round(
            result.get("target_effective_max_health", 0.0), 1
        ),
        "target_effective_health": round(_target_effective_health(result), 1),
        "overkill": round(_legacy_overkill(result), 1),
        "ability_damage": round(result["ability_damage"], 1),
        "auto_attack_damage": round(result["auto_attack_damage"], 1),
        "damage_by_type": {
            dtype: round(amount, 1)
            for dtype, amount in result["damage_by_type"].items()
        },
        "breakdown": api_breakdown,
        "effective_mr": round(result.get("effective_mr", 0.0), 1),
        "effective_armor": round(result.get("effective_armor", 0.0), 1),
        "notes": list(result.get("notes", [])),
        "cast_timeline": list(result.get("cast_timeline", [])),
        "rotation": dict(result.get("rotation") or {}),
        "resource_spent": round(result.get("resource_spent", 0.0), 1),
        "resource_remaining": round(result.get("resource_remaining", 0.0), 1),
        "resource_ledger": dict(result.get("resource_ledger") or {}),
        "timeline_coverage": dict(result.get("timeline_coverage", {})),
        "auto_attack_policy": dict(result.get("auto_attack_policy", {})),
        "auto_attack_schedule": dict(result.get("auto_attack_schedule", {})),
        "damage_events": [
            _public_damage_event(event)
            for event in result.get("damage_events", [])
            if isinstance(event, Mapping) and _public_event_time(event) is not None
        ],
        "self_healing": round(float(result.get("self_healing", 0.0)), 1),
        "self_healing_events": [
            {
                "time": _public_event_time(event),
                "source": str(event.get("source", "")),
                "kind": str(event.get("kind", "")),
                "amount": round(float(event.get("amount", 0.0)), 1),
            }
            for event in result.get("self_healing_events", [])
            if isinstance(event, Mapping) and _public_event_time(event) is not None
        ],
    }


def _primary(key: str, results: list[dict[str, Any]]) -> object:
    """Copy the primary target's value defensively (mapping/list containers)."""
    value = results[0][key]
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value


def _any_true(key: str, results: list[dict[str, Any]]) -> object:
    """OR one published boolean across targets."""
    return any(result.get(key, False) for result in results)


def _concat(key: str, results: list[dict[str, Any]]) -> object:
    """Concatenate one ordered per-target stream."""
    return [event for result in results for event in result.get(key, [])]


def _concat_stamped(key: str, results: list[dict[str, Any]]) -> object:
    """Flatten per-target damage events, each stamped with ``target_index``.

    The roster response also keeps the per-target table
    (``targets[i].result``); a single-target response carries no stamp.
    """
    return [
        dict(event, target_index=target_index)
        for target_index, result in enumerate(results)
        for event in result.get(key, [])
    ]


def _summed(key: str, results: list[dict[str, Any]]) -> object:
    """Total one published number across targets."""
    return round(sum(float(result.get(key, 0.0)) for result in results), 1)


def _summed_measure(
    measure: Callable[[Mapping[str, object]], float],
) -> Callable[[str, list[dict[str, Any]]], object]:
    """Total one derived per-target measure, which has no public key to read."""
    return lambda _key, results: round(sum(measure(result) for result in results), 1)


def _summed_by_damage_type(key: str, results: list[dict[str, Any]]) -> object:
    """Add the per-damage-type totals, publishing the three classes always."""
    damage_types = {"physical": 0.0, "magic": 0.0, "true": 0.0}
    for result in results:
        for damage_type, amount in result[key].items():
            damage_types[damage_type] = damage_types.get(damage_type, 0.0) + amount
    return {
        damage_type: round(amount, 1) for damage_type, amount in damage_types.items()
    }


def _combined_timeline_coverage(_key: str, results: list[dict[str, Any]]) -> object:
    """Merge the per-target ordering receipts without overstating precision."""
    return aggregate_timeline_coverage(results)


def _summed_breakdown(key: str, results: list[dict[str, Any]]) -> object:
    """Merge per-target breakdown rows with the existing receipt shape."""
    target_count = len(results)
    breakdown = {}
    for result in results:
        for row_key, entry in result[key].items():
            aggregate = breakdown.setdefault(
                row_key,
                {
                    "name": entry["name"],
                    "total_damage": 0.0,
                    "casts": entry.get("casts"),
                    "count": entry.get("count"),
                    "unit": entry.get("unit"),
                    "damage_per_hit": None,
                    "num_crits": None,
                    "num_non_crits": None,
                    "crit_damage_per_hit": None,
                    "non_crit_damage_per_hit": None,
                    "total_amount": 0.0,
                    "amount_per_proc": None,
                    "proc_times": [],
                    "output_type": entry.get("output_type"),
                },
            )
            aggregate["total_damage"] += entry["total_damage"]
            aggregate["total_amount"] += float(entry.get("total_amount") or 0.0)
            if entry.get("amount_per_proc") is not None:
                aggregate["amount_per_proc"] = entry["amount_per_proc"]
            aggregate["proc_times"].extend(entry.get("proc_times") or [])

    for entry in breakdown.values():
        entry["total_damage"] = round(entry["total_damage"], 1)
        target_label = "target" if target_count == 1 else "targets"
        entry["detail"] = f"Across {target_count} selected {target_label}"
    return breakdown


# One combine policy per public key, shared by both serializers: the single
# target serializer's key set is this table's keys, so a key added to one
# cannot silently disappear from the other.
_PUBLIC_FIELD_POLICIES: dict[str, Callable[[str, list[dict[str, Any]]], object]] = {
    "champion_stats": _primary,
    "champion_stats_state": _primary,
    "total_damage": _summed,
    "health_damage": _summed,
    "shield_absorbed": _summed,
    "magic_shield_absorbed": _summed,
    "physical_shield_absorbed": _summed,
    "general_shield_absorbed": _summed,
    "threshold_shield_absorbed": _summed,
    "threshold_health_triggered": _any_true,
    "threshold_health_bonus_gained": _summed,
    "target_healing_received": _summed,
    "target_ending_health": _summed,
    "target_effective_max_health": _summed,
    "target_effective_health": _summed_measure(_target_effective_health),
    "overkill": _summed_measure(_legacy_overkill),
    "ability_damage": _summed,
    "auto_attack_damage": _summed,
    "damage_by_type": _summed_by_damage_type,
    "breakdown": _summed_breakdown,
    "self_healing": _summed,
    "self_healing_events": _concat,
    "effective_mr": _primary,
    "effective_armor": _primary,
    "cast_timeline": _primary,
    "rotation": _primary,
    "resource_spent": _primary,
    "resource_remaining": _primary,
    "resource_ledger": _primary,
    "notes": _primary,
    "timeline_coverage": _combined_timeline_coverage,
    "auto_attack_policy": _primary,
    "auto_attack_schedule": _primary,
    "damage_events": _concat_stamped,
}


def aggregate_public_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold the same selected damage package across every hit target."""
    return {
        key: combine(key, results) for key, combine in _PUBLIC_FIELD_POLICIES.items()
    }
