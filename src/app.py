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
from calculator.champions import champion_options_meta_map
from calculator.optimizer import (
    exclusivity_groups,
    get_eligible_boots,
    get_eligible_legendaries,
    optimize_build,
)
from calculator.stats import MAX_LEVEL
from calculator.pipeline import (
    DEFAULT_AUTO_ATTACK_UPTIME,
    DEFAULT_FIGHT_DURATION,
    DEFAULT_FIGHT_MODE,
    DEFAULT_TARGET,
    ONE_ROTATION_DURATION,
    FightParams,
    run_fight,
)

app = Flask(
    __name__,
    template_folder=str(Path(__file__).resolve().parent.parent / "templates"),
    static_folder=str(Path(__file__).resolve().parent.parent / "static"),
)
app.json.sort_keys = False


@app.route("/")
def index():
    """Serve the main calculator page."""
    return render_template(
        "index.html",
        default_target=DEFAULT_TARGET,
        default_fight_duration=DEFAULT_FIGHT_DURATION,
        default_auto_attack_uptime=DEFAULT_AUTO_ATTACK_UPTIME,
        max_level=MAX_LEVEL,
    )


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
    """Return the optimizer-eligible legendaries (name + icon), sorted.

    Delegates eligibility to the optimizer so the manual item picker and
    the optimizer's candidate set can never diverge.
    """
    result = sorted(
        [
            {"name": item["name"], "icon": item.get("icon", "")}
            for item in get_eligible_legendaries()
        ],
        key=lambda i: i["name"],
    )
    return jsonify(result)


@app.route("/api/boots")
def api_boots():
    """Return the optimizer-eligible tier-2+ boots (name + icon), sorted."""
    result = sorted(
        [
            {"name": item["name"], "icon": item.get("icon", "")}
            for item in get_eligible_boots()
        ],
        key=lambda i: i["name"],
    )
    return jsonify(result)


@app.route("/api/config")
def api_config():
    """Serve calculator config the frontend must share with the backend.

    Single source of truth for domain facts that would otherwise be
    hand-copied into app.js: item exclusivity groups (optimizer.py),
    fight/target defaults (pipeline.py), and champion option/assumption
    metadata (each champion module's OPTIONS/ASSUMPTIONS declarations).
    Champion options ride the existing one-shot bootstrap fetch rather
    than a per-champion endpoint so app.js can keep reading the map
    synchronously on champion select.
    """
    return jsonify(
        {
            "exclusivity_groups": exclusivity_groups(),
            "default_target": DEFAULT_TARGET,
            "fight_defaults": {
                "mode": DEFAULT_FIGHT_MODE,
                "duration_seconds": DEFAULT_FIGHT_DURATION,
                "auto_attack_uptime": DEFAULT_AUTO_ATTACK_UPTIME,
                "one_rotation_duration_seconds": ONE_ROTATION_DURATION,
            },
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
    try:
        fight_params = FightParams.from_request(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Validate
    if not champion_name:
        return jsonify({"error": "No champion selected"}), 400
    if level < 1 or level > MAX_LEVEL:
        return jsonify({"error": f"Level must be between 1 and {MAX_LEVEL}"}), 400

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

    result = run_fight(champion_data, level, items, fight_params)

    breakdown = result.get("breakdown", {})
    auto_attack_damage = result["auto_attack_damage"]
    ability_damage = result["ability_damage"]
    total_damage = result.get("total_damage", 0.0)

    # Build breakdown dict for JSON response
    api_breakdown = {}
    for key, entry in breakdown.items():
        # Include damaging rows plus display-only rows carrying text
        has_damage = entry.get("total_damage", 0.0) > 0
        if not (has_damage or "detail" in entry):
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
        # Display extras are minted by the engine and passed through
        # untouched — adding a new one never requires editing this route.
        for display_key in ("detail", "damage_display"):
            if display_key in entry:
                row[display_key] = entry[display_key]
        api_breakdown[key] = row

    return jsonify(
        {
            "champion_stats": result["champion_stats"],
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
    if level < 1 or level > MAX_LEVEL:
        return jsonify({"error": f"Level must be between 1 and {MAX_LEVEL}"}), 400

    try:
        champion_data = get_champion(champion_name)
    except KeyError:
        return jsonify({"error": f"Champion '{champion_name}' not found"}), 404

    try:
        fight_params = FightParams.from_request(data, deterministic=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Optimizer-specific parameters
    objective = data.get("objective", "total_damage")
    locked_items = data.get("locked_items", [])
    locked_boots = data.get("locked_boots", "")
    max_legendary_slots = int(data.get("max_legendary_slots", 5))

    if objective not in ("total_damage", "physical_damage", "magic_damage"):
        return jsonify({"error": "Invalid objective"}), 400
    if not 1 <= max_legendary_slots <= 6:
        return jsonify({"error": "max_legendary_slots must be between 1 and 6"}), 400
    if len(locked_items) > max_legendary_slots:
        return (
            jsonify(
                {
                    "error": (
                        f"{len(locked_items)} locked items don't fit in "
                        f"{max_legendary_slots} legendary slots"
                    )
                }
            ),
            400,
        )

    result = optimize_build(
        champion_data=champion_data,
        level=level,
        fight_params=fight_params,
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
