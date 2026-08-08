"""Public response serializers for engine fight results.

One home for the stable wire shape: ``serialize_fight_result`` renders a
single engine result and ``aggregate_public_results`` combines several
per-target results into the roster response.  The aggregate is driven by
``_PUBLIC_FIELD_POLICIES``, the same schema table that defines the
single-target key set, so a future key added to one serializer cannot
silently disappear from the other (see tests/test_endpoint_parity.py).
"""

import math
from collections.abc import Mapping
from urllib.parse import urlsplit

from .champions import engine_registration_kind

from .timeline_coverage import combine_timeline_coverages

ICON_HOSTS = frozenset(
    {
        "cdn.communitydragon.org",
        "ddragon.leagueoflegends.com",
        "raw.communitydragon.org",
    }
)


def https_icon(url: str) -> str:
    """Return one allow-listed HTTPS icon URL or an empty public value."""
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


def public_loadout_summary(loadout, verified_champions: frozenset[str]) -> dict:
    """Sanitize one resolved loadout for the stable browser response."""
    summary = loadout.public_summary()
    summary["icon"] = https_icon(summary["icon"])
    summary["item_icons"] = [https_icon(icon) for icon in summary["item_icons"]]
    summary["verified_attacker"] = summary["champion"] in verified_champions
    registration = engine_registration_kind(summary["champion"])
    summary["engine_registered"] = registration is not None
    summary["engine_registration"] = registration
    return summary


# One combine policy per public key, shared by both serializers.
# ``primary`` keeps the first target's value (the primary target), ``sum``
# totals across targets, ``any`` ORs a boolean, ``sum_by_key`` adds
# per-damage-type totals, ``sum_breakdown`` merges the per-ability rows,
# ``concat`` concatenates ordered per-target streams, and
# ``combine_timeline_coverages`` merges ordering receipts without
# overstating precision.
_PUBLIC_FIELD_POLICIES: dict[str, str] = {
    "champion_stats": "primary",
    "total_damage": "sum",
    "health_damage": "sum",
    "shield_absorbed": "sum",
    "magic_shield_absorbed": "sum",
    "physical_shield_absorbed": "sum",
    "general_shield_absorbed": "sum",
    "threshold_shield_absorbed": "sum",
    "threshold_health_triggered": "any",
    "threshold_health_bonus_gained": "sum",
    "target_healing_received": "sum",
    "target_ending_health": "sum",
    "target_effective_max_health": "sum",
    "target_effective_health": "sum",
    "overkill": "sum",
    "ability_damage": "sum",
    "auto_attack_damage": "sum",
    "damage_by_type": "sum_by_key",
    "breakdown": "sum_breakdown",
    "self_healing": "sum",
    "self_healing_events": "concat",
    "effective_mr": "primary",
    "effective_armor": "primary",
    "cast_timeline": "primary",
    "rotation": "primary",
    "resource_spent": "primary",
    "resource_remaining": "primary",
    "notes": "primary",
    "timeline_coverage": "combine_timeline_coverages",
    "auto_attack_policy": "primary",
    "auto_attack_schedule": "primary",
    "damage_events": "concat",
}


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
    """Estimate one target's effective health from a legacy engine result.

    The event-ordered combat ledger reports the exact effective health per
    participant; the standalone per-target engine only carries max health,
    shield absorption, and healing received.  Summing those three reproduces
    the ledger's effective-health definition (max health + shields +
    healing) for the common case so the overkill receipt stays comparable
    across both response shapes.
    """
    return (
        float(result.get("target_effective_max_health", 0.0))
        + float(result.get("shield_absorbed", 0.0))
        + float(result.get("target_healing_received", 0.0))
    )


def _legacy_overkill(result: Mapping[str, object]) -> float:
    """Return raw total damage beyond the target's effective health.

    The standalone engine keeps applying damage after defeat, so total
    damage can exceed every amount the target could absorb.  Overkill is
    that excess; the coupled combat ledger carries the exact per-event
    value in each participant's survival receipt instead.
    """
    return max(
        0.0, float(result.get("total_damage", 0.0)) - _target_effective_health(result)
    )


def serialize_fight_result(result: Mapping[str, object]) -> dict:
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
        api_breakdown[key] = row

    return {
        "champion_stats": result["champion_stats"],
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
        "timeline_coverage": dict(result.get("timeline_coverage", {})),
        "auto_attack_policy": dict(result.get("auto_attack_policy", {})),
        "auto_attack_schedule": dict(result.get("auto_attack_schedule", {})),
        "damage_events": [
            {
                "time": _public_event_time(event),
                "source": str(event.get("source_key", "")),
                "damage_type": str(event.get("damage_type", "")),
                "damage": round(float(event.get("damage", 0.0)), 1),
                "phase": str(event.get("phase", "")),
            }
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


def _aggregate_timeline_coverage(results: list[dict]) -> dict:
    """Combine per-target ordering receipts without overstating precision."""
    return combine_timeline_coverages(
        (result.get("timeline_coverage", {}) for result in results),
        target_count=len(results),
    )


def _primary_value(result: dict, key: str) -> object:
    """Copy the primary target's value defensively (mapping/list containers)."""
    value = result[key]
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value


def _concat_damage_events(results: list[dict]) -> list[dict]:
    """Flatten per-target damage events with a 1:1 ``target_index`` stamp.

    The roster response keeps the per-target table (``targets[i].result``)
    and additionally exposes the flattened stream so consumers that only
    read the top-level ``damage_events`` key see every target.  Each event
    carries the index of the target it came from; single-target responses
    keep the legacy shape (no ``target_index``) so existing consumers are
    unchanged.
    """
    flattened: list[dict] = []
    for target_index, result in enumerate(results):
        for event in result.get("damage_events", []):
            stamped = dict(event)
            stamped["target_index"] = target_index
            flattened.append(stamped)
    return flattened


def _sum_breakdown(results: list[dict]) -> dict:
    """Merge per-target breakdown rows with the existing receipt shape."""
    target_count = len(results)
    breakdown = {}
    for result in results:
        for key, entry in result["breakdown"].items():
            aggregate = breakdown.setdefault(
                key,
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


def aggregate_public_results(results: list[dict]) -> dict:
    """Sum the same selected damage package across every hit target.

    Driven by ``_PUBLIC_FIELD_POLICIES`` so every key the single-target
    serializer emits also exists here (including ``damage_events``, the
    flattened per-target stream stamped with ``target_index``).
    """
    primary = results[0]
    timeline_coverage = _aggregate_timeline_coverage(results)
    damage_types = {"physical": 0.0, "magic": 0.0, "true": 0.0}
    for result in results:
        for damage_type, amount in result["damage_by_type"].items():
            damage_types[damage_type] = damage_types.get(damage_type, 0.0) + amount

    aggregated: dict[str, object] = {}
    # pylint: disable=too-many-branches  # one branch per combine policy
    for key, policy in _PUBLIC_FIELD_POLICIES.items():
        if policy == "primary":
            aggregated[key] = _primary_value(primary, key)
        elif policy == "any":
            aggregated[key] = any(result.get(key, False) for result in results)
        elif policy == "concat":
            if key == "damage_events":
                aggregated[key] = _concat_damage_events(results)
            else:
                aggregated[key] = [
                    event for result in results for event in result.get(key, [])
                ]
        elif policy == "sum_by_key":
            aggregated[key] = {
                damage_type: round(amount, 1)
                for damage_type, amount in damage_types.items()
            }
        elif policy == "sum_breakdown":
            aggregated[key] = _sum_breakdown(results)
        elif policy == "combine_timeline_coverages":
            aggregated[key] = timeline_coverage
        elif policy == "sum":
            if key == "target_effective_health":
                value = sum(_target_effective_health(result) for result in results)
            elif key == "overkill":
                value = sum(_legacy_overkill(result) for result in results)
            else:
                value = sum(float(result.get(key, 0.0)) for result in results)
            aggregated[key] = round(value, 1)
        else:
            raise AssertionError(f"unknown combine policy {policy!r} for {key}")
    return aggregated
