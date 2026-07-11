"""Flask web application for the LoL Damage Calculator."""

import json
import sys
from pathlib import Path

# Ensure the src directory is on the path so calculator imports work
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, Response, jsonify, render_template, request

from calculator.data_fetcher import (
    fetch_champion_data,
    fetch_item_data,
    get_champion,
    get_item_by_name,
)
from calculator.data_updater import update_data
from calculator.item_effects import refresh_item_effects
from calculator.stats import calculate_total_stats
from calculator.champions import champion_options_meta_map, parse_abilities
from calculator.damage import (
    DEFAULT_TARGET,
    calculate_fight_damage,
    split_auto_vs_ability,
)
from calculator.optimizer import exclusivity_groups, optimize_build, ITEM_BLOCKLIST

app = Flask(
    __name__,
    template_folder=str(Path(__file__).resolve().parent.parent / "templates"),
    static_folder=str(Path(__file__).resolve().parent.parent / "static"),
)
app.json.sort_keys = False

# ITEM_BLOCKLIST is imported from calculator.optimizer


@app.route("/")
def index():
    """Serve the main calculator page."""
    return render_template("index.html")


@app.route("/api/champions")
def api_champions():
    """Return a sorted list of champion names with icons."""
    champions = fetch_champion_data()
    result = sorted(
        [
            {"name": champ_data["name"], "icon": champ_data.get("icon", "")}
            for champ_data in champions.values()
        ],
        key=lambda c: c["name"],
    )
    return jsonify(result)


@app.route("/api/items")
def api_items():
    """Return a sorted list of Summoner's Rift item names with icons (no boots)."""
    items = fetch_item_data()
    result = sorted(
        [
            {"name": item_data["name"], "icon": item_data.get("icon", "")}
            for item_data in items.values()
            if "LEGENDARY" in item_data.get("rank", [])
            and item_data.get("name")
            and "BOOTS" not in item_data.get("rank", [])
            and item_data.get("name") not in ITEM_BLOCKLIST
        ],
        key=lambda i: i["name"],
    )
    return jsonify(result)


@app.route("/api/boots")
def api_boots():
    """Return a sorted list of boots with icons (tier 2+)."""
    items = fetch_item_data()
    result = sorted(
        [
            {"name": item_data["name"], "icon": item_data.get("icon", "")}
            for item_data in items.values()
            if "BOOTS" in item_data.get("rank", [])
            and item_data.get("tier", 0) >= 2
            and item_data.get("name")
            and item_data.get("name") not in ITEM_BLOCKLIST
        ],
        key=lambda i: i["name"],
    )
    return jsonify(result)


@app.route("/api/config")
def api_config():
    """Serve calculator config the frontend must share with the backend.

    Single source of truth for domain facts that would otherwise be
    hand-copied into app.js: item exclusivity groups (optimizer.py),
    default target stats (damage.py), and champion option/assumption
    metadata (each champion module's OPTIONS/ASSUMPTIONS declarations).
    Champion options ride the existing one-shot bootstrap fetch rather
    than a per-champion endpoint so app.js can keep reading the map
    synchronously on champion select.
    """
    return jsonify(
        {
            "exclusivity_groups": exclusivity_groups(),
            "default_target": DEFAULT_TARGET,
            "champion_options": champion_options_meta_map(),
        }
    )


@app.route("/api/abilities/<champion_name>")
def api_abilities(champion_name: str):
    """Return ability names and icons for a champion keyed by Q, W, E, R."""
    try:
        champion_data = get_champion(champion_name)
    except KeyError:
        return jsonify({"error": f"Champion '{champion_name}' not found"}), 404

    abilities = champion_data.get("abilities", {})
    result = {}
    for key in ("P", "Q", "W", "E", "R"):
        ability_list = abilities.get(key, [])
        if ability_list and isinstance(ability_list[0], dict):
            result[key] = {
                "name": ability_list[0].get("name", key),
                "icon": ability_list[0].get("icon", ""),
            }
        elif ability_list and isinstance(ability_list[0], str):
            result[key] = {"name": ability_list[0], "icon": ""}
        else:
            result[key] = {"name": key, "icon": ""}
    return jsonify(result)


@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    """Run the damage calculation and return results."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    champion_name = data.get("champion", "")
    level = int(data.get("level", 1))
    item_names = data.get("items", [])
    boots_name = data.get("boots", "")
    target_health = float(data.get("target_health", DEFAULT_TARGET["health"]))
    target_bonus_health = float(
        data.get("target_bonus_health", DEFAULT_TARGET["bonus_health"])
    )
    target_armor = float(data.get("target_armor", DEFAULT_TARGET["armor"]))
    target_mr = float(data.get("target_mr", DEFAULT_TARGET["mr"]))
    fight_mode = data.get("fight_mode", "one_rotation")
    fight_duration = float(data.get("fight_duration", 8))
    include_auto_attacks = data.get("include_auto_attacks", False)
    auto_attack_uptime = float(data.get("auto_attack_uptime", 0.8))
    auto_attacks_only = data.get("auto_attacks_only", False)
    ability_ranks = data.get("ability_ranks", None)
    include_actives = data.get("include_actives", True)
    cast_order = data.get("cast_order", None)
    champion_options = data.get("champion_options", None)

    # Validate
    if not champion_name:
        return jsonify({"error": "No champion selected"}), 400
    if level < 1 or level > 20:
        return jsonify({"error": "Level must be between 1 and 20"}), 400

    # Validate cast order if provided
    if cast_order is not None:
        if sorted(cast_order) != ["E", "Q", "R", "W"]:
            return (
                jsonify({"error": "Cast order must be a permutation of Q, W, E, R"}),
                400,
            )

    # Validate ability ranks if provided
    if ability_ranks:
        for key in ("Q", "W", "E"):
            val = ability_ranks.get(key, 0)
            if val < 0 or val > 5:
                return jsonify({"error": f"{key} rank must be 0-5"}), 400
        r_val = ability_ranks.get("R", 0)
        if r_val < 0 or r_val > 3:
            return jsonify({"error": "R rank must be 0-3"}), 400

    try:
        champion_data = get_champion(champion_name)
    except KeyError:
        return jsonify({"error": f"Champion '{champion_name}' not found"}), 404

    # Resolve items
    items = []
    if boots_name:
        try:
            items.append(get_item_by_name(boots_name))
        except KeyError:
            return jsonify({"error": f"Boots '{boots_name}' not found"}), 404
    for item_name in item_names:
        if not item_name:
            continue
        try:
            items.append(get_item_by_name(item_name))
        except KeyError:
            return jsonify({"error": f"Item '{item_name}' not found"}), 404

    # Calculate stats
    champion_stats = calculate_total_stats(champion_data, level, items)
    ability_haste = champion_stats.get("ability_haste", 0.0)

    # Build target stats context for %HP abilities
    target_stats = {
        "target_max_health": target_health,
        "target_current_health": target_health,  # Assume full HP at start
        "target_missing_health": 0.0,
    }

    # Parse abilities via the champion registry
    # Use display name from data (e.g. "Kog'Maw") not the data key ("KogMaw")
    display_name = champion_data.get("name", champion_name)
    ability_damages = parse_abilities(
        display_name,
        champion_data,
        level,
        champion_stats["ability_power"],
        ability_ranks=ability_ranks,
        champion_stats=champion_stats,
        target_stats=target_stats,
        champion_options=champion_options,
    )

    # Determine fight parameters based on mode
    is_one_rotation = fight_mode == "one_rotation"
    if is_one_rotation:
        effective_duration = 5.0  # One rotation takes ~5 seconds in practice
        effective_uptime = 0.0
    else:
        effective_duration = fight_duration
        effective_uptime = auto_attack_uptime if include_auto_attacks else 0.0

    # Run damage calculation
    result = calculate_fight_damage(
        champion_stats=champion_stats,
        ability_damages=ability_damages,
        target_health=target_health,
        target_bonus_health=target_bonus_health,
        target_armor=target_armor,
        target_magic_resistance=target_mr,
        fight_duration_seconds=effective_duration,
        auto_attack_uptime=effective_uptime,
        ability_haste=ability_haste,
        items=items,
        one_rotation=is_one_rotation,
        include_actives=include_actives,
        cast_order=cast_order,
        auto_attacks_only=auto_attacks_only,
    )

    # Separate ability damage from auto-attack damage
    breakdown = result.get("breakdown", {})
    auto_attack_damage, ability_damage = split_auto_vs_ability(breakdown)

    total_damage = result.get("total_damage", 0.0)

    # Build breakdown dict for JSON response
    api_breakdown = {}
    for key, entry in breakdown.items():
        # Include entries with damage > 0, or special display entries
        has_damage = entry.get("total_damage", 0.0) > 0
        has_note = "note" in entry
        has_threshold = "execution_threshold_hp" in entry
        has_ss_note = "sundered_sky_note" in entry
        if not (has_damage or has_note or has_threshold or has_ss_note):
            continue
        row = {
            "name": entry.get("name", key),
            "total_damage": round(entry.get("total_damage", 0.0), 1),
            "casts": entry.get("casts", None),
            "count": entry.get("count", None),
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
        if "note" in entry:
            row["note"] = entry["note"]
        if "execution_threshold_hp" in entry:
            row["execution_threshold_hp"] = round(
                entry["execution_threshold_hp"],
                1,
            )
        if "sundered_sky_note" in entry:
            row["sundered_sky_note"] = entry["sundered_sky_note"]
        api_breakdown[key] = row

    return jsonify(
        {
            "champion_stats": champion_stats,
            "total_damage": round(total_damage, 1),
            "ability_damage": round(ability_damage, 1),
            "auto_attack_damage": round(auto_attack_damage, 1),
            "breakdown": api_breakdown,
            "effective_mr": round(result.get("effective_mr", 0.0), 1),
            "effective_armor": round(result.get("effective_armor", 0.0), 1),
        }
    )


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    """Find the optimal item build for a champion."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    champion_name = data.get("champion", "")
    if not champion_name:
        return jsonify({"error": "No champion selected"}), 400

    level = int(data.get("level", 1))
    if level < 1 or level > 20:
        return jsonify({"error": "Level must be between 1 and 20"}), 400

    try:
        champion_data = get_champion(champion_name)
    except KeyError:
        return jsonify({"error": f"Champion '{champion_name}' not found"}), 404

    # Read all fight parameters (same as /api/calculate)
    target_health = float(data.get("target_health", DEFAULT_TARGET["health"]))
    target_bonus_health = float(
        data.get("target_bonus_health", DEFAULT_TARGET["bonus_health"])
    )
    target_armor = float(data.get("target_armor", DEFAULT_TARGET["armor"]))
    target_mr = float(data.get("target_mr", DEFAULT_TARGET["mr"]))
    fight_mode = data.get("fight_mode", "one_rotation")
    fight_duration = float(data.get("fight_duration", 8))
    include_auto_attacks = data.get("include_auto_attacks", False)
    auto_attack_uptime = float(data.get("auto_attack_uptime", 0.8))
    auto_attacks_only = data.get("auto_attacks_only", False)
    ability_ranks = data.get("ability_ranks", None)
    include_actives = data.get("include_actives", True)
    cast_order = data.get("cast_order", None)
    champion_options = data.get("champion_options", None)

    # Optimizer-specific parameters
    objective = data.get("objective", "total_damage")
    locked_items = data.get("locked_items", [])
    locked_boots = data.get("locked_boots", "")
    max_legendary_slots = int(data.get("max_legendary_slots", 5))

    if objective not in ("total_damage", "physical_damage", "magic_damage"):
        return jsonify({"error": "Invalid objective"}), 400
    if max_legendary_slots not in (5, 6):
        return jsonify({"error": "max_legendary_slots must be 5 or 6"}), 400

    result = optimize_build(
        champion_name=champion_name,
        champion_data=champion_data,
        level=level,
        target_health=target_health,
        target_bonus_health=target_bonus_health,
        target_armor=target_armor,
        target_mr=target_mr,
        fight_mode=fight_mode,
        fight_duration=fight_duration,
        include_auto_attacks=include_auto_attacks,
        auto_attack_uptime=auto_attack_uptime,
        auto_attacks_only=auto_attacks_only,
        ability_ranks=ability_ranks,
        include_actives=include_actives,
        cast_order=cast_order,
        champion_options=champion_options,
        objective=objective,
        locked_items=locked_items if locked_items else None,
        locked_boots=locked_boots if locked_boots else None,
        max_legendary_slots=max_legendary_slots,
    )

    return jsonify(result)


@app.route("/api/update-data")
def api_update_data():
    """Stream data update progress via Server-Sent Events."""

    def generate():
        for event in update_data():
            yield f"data: {json.dumps(event)}\n\n"
        # Fresh item JSON is now on disk — re-parse ITEM_EFFECTS in place
        # so in-memory effects reflect the newly fetched patch data.
        refresh_item_effects()

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
