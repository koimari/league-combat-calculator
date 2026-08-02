"""Flask web application for the LoL Damage Calculator."""

import hmac
import ipaddress
import json
import math
import os
import secrets
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

# Ensure the src directory is on the path so calculator imports work
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, Response, jsonify, render_template, request

from calculator.data_fetcher import (
    fetch_champion_data,
    get_champion,
    get_item_by_name,
)
from calculator.item_effects import item_input_options_meta, refresh_item_effects
from calculator.ally_effects import combine_ally_stat_effects, resolve_ally_stat_effects
from calculator.loadout_rules import validate_resolved_loadout
from calculator.champions import champion_options_meta_map, registered_champion_names
from calculator.optimizer import (
    exclusivity_groups,
    get_eligible_boots,
    get_selectable_items,
    optimize_build,
)
from calculator.stats import MAX_LEVEL
from calculator.scenario import MAX_ALLIES, MAX_ENEMIES, ChampionLoadout, parse_roster
from calculator.role_quests import role_quest_meta
from calculator.pipeline import (
    DEFAULT_AUTO_ATTACK_UPTIME,
    DEFAULT_FIGHT_DURATION,
    DEFAULT_FIGHT_MODE,
    DEFAULT_TARGET,
    ONE_ROTATION_DURATION,
    PUBLIC_INPUT_LIMITS,
    FightParams,
    run_fight,
)
from rate_limit import TokenBucketStore

app = Flask(
    __name__,
    template_folder=str(Path(__file__).resolve().parent.parent / "templates"),
    static_folder=str(Path(__file__).resolve().parent.parent / "static"),
)
app.json.sort_keys = False
app.config.update(
    MAX_CONTENT_LENGTH=32 * 1024,
    RATE_LIMIT_ENABLED=True,
)

_RATE_LIMIT_POLICIES = {
    "calculate": (40, 20.0),
    # Worst max-valid optimizer request measured at 1.81 CPU seconds locally.
    # One token per 10 seconds caps sustained abuse near 20% of one core while
    # the independent calculate budget keeps the ordinary UI responsive.
    "optimize": (2, 0.1),
}
_VERIFIED_CHAMPIONS = frozenset(registered_champion_names())
_ICON_HOSTS = frozenset(
    {
        "cdn.communitydragon.org",
        "ddragon.leagueoflegends.com",
        "raw.communitydragon.org",
    }
)
_DEV_UPDATE_COOKIE = "lol_calc_dev_update"
_DEV_UPDATE_TOKEN = secrets.token_urlsafe(32)
_ICON_SOURCES = " ".join(f"https://{host}" for host in sorted(_ICON_HOSTS))
_SECURITY_HEADERS = {
    "Content-Security-Policy": "; ".join(
        (
            "default-src 'self'",
            "base-uri 'none'",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            f"img-src 'self' {_ICON_SOURCES}",
            "connect-src 'self'",
            "form-action 'self'",
            "upgrade-insecure-requests",
        )
    ),
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}
_rate_limiter = TokenBucketStore(
    Path(tempfile.gettempdir()) / "lol-calculator-rate-limits.sqlite3"
)


def _spend_rate_limit(scope: str):
    """Protect expensive work globally across all Gunicorn workers."""
    if not app.config["RATE_LIMIT_ENABLED"]:
        return None
    capacity, refill_per_second = _RATE_LIMIT_POLICIES[scope]
    try:
        allowed, retry_after = _rate_limiter.consume(
            scope,
            capacity=capacity,
            refill_per_second=refill_per_second,
        )
    except sqlite3.Error:
        app.logger.exception("Shared rate-limit store is unavailable")
        response = jsonify({"error": "Rate-limit service unavailable"})
        response.status_code = 503
        response.headers["Retry-After"] = "1"
        return response

    if allowed:
        return None

    label = "Optimizer" if scope == "optimize" else "Calculator"
    response = jsonify({"error": f"{label} is busy; retry shortly"})
    response.status_code = 429
    response.headers["Retry-After"] = str(max(1, math.ceil(retry_after)))
    return response


@app.errorhandler(413)
def _request_too_large(_error):
    """Return the same JSON error shape as every other API rejection."""
    return jsonify({"error": "Request body exceeds 32 KiB"}), 413


@app.after_request
def _add_security_headers(response):
    """Apply browser protections consistently to pages, APIs, and errors."""
    for name, value in _SECURITY_HEADERS.items():
        if (
            name == "Content-Security-Policy"
            and request.scheme == "http"
            and request.remote_addr
        ):
            try:
                if ipaddress.ip_address(request.remote_addr).is_loopback:
                    # Local development has no TLS terminator. Upgrading
                    # same-origin assets here would turn working http static
                    # URLs into failed https requests in standards-compliant
                    # browsers. Deployed responses retain the directive.
                    value = value.replace("; upgrade-insecure-requests", "")
            except ValueError:
                pass
        response.headers[name] = value
    return response


def _json_object() -> dict:
    """Read a public JSON request while rejecting arrays and invalid JSON."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")
    return data


def _request_string(
    data: Mapping[str, object],
    key: str,
    default: str = "",
    *,
    required: bool = False,
) -> str:
    """Read a short request string without coercing objects into names."""
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{key} is required")
    if len(value) > 100:
        raise ValueError(f"{key} must be at most 100 characters")
    return value


def _request_int(
    data: Mapping[str, object],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Read one bounded integer without accepting booleans or decimals."""
    value = data.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{key} must be an integer") from exc
    else:
        raise ValueError(f"{key} must be an integer")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return parsed


def _request_string_list(
    data: Mapping[str, object],
    key: str,
    *,
    maximum: int,
) -> list[str]:
    """Read a bounded list of unique short names."""
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    if len(value) > maximum:
        raise ValueError(f"{key} may contain at most {maximum} entries")

    names = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(f"{key} entries must be strings")
        name = entry.strip()
        if len(name) > 100:
            raise ValueError(f"{key} entries must be at most 100 characters")
        if name:
            names.append(name)
    if len(set(names)) != len(names):
        raise ValueError(f"{key} must not contain duplicates")
    return names


def _validate_champion_options(champion_name: str, data: Mapping[str, object]) -> None:
    """Enforce each champion module's declared public option contract."""
    supplied = data.get("champion_options")
    if supplied is None:
        return
    if not isinstance(supplied, Mapping):
        raise ValueError("champion_options must be an object")

    declared = {
        option["key"]: option
        for option in champion_options_meta_map()
        .get(champion_name, {})
        .get("options", [])
    }
    unknown = set(supplied) - set(declared)
    if unknown:
        raise ValueError(f"Unknown champion option: {sorted(unknown)[0]}")

    for key, value in supplied.items():
        option = declared[key]
        option_type = option["type"]
        if option_type == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"champion_options.{key} must be true or false")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"champion_options.{key} must be a number")
        if option_type == "int" and not isinstance(value, int):
            raise ValueError(f"champion_options.{key} must be an integer")
        if not math.isfinite(value):
            raise ValueError(f"champion_options.{key} must be finite")
        if not option["min"] <= value <= option["max"]:
            raise ValueError(
                f"champion_options.{key} must be between "
                f"{option['min']} and {option['max']}"
            )


def _resolve_named_item(name: str, *, kind: str = "Item") -> dict:
    """Resolve one item name and translate data misses into a public 404."""
    try:
        return get_item_by_name(name)
    except KeyError as exc:
        raise LookupError(f"{kind} '{name}' not found") from exc


def _load_public_champion(name: str) -> dict:
    """Load one champion that the public UI and engine both support."""
    try:
        champion = get_champion(name)
    except KeyError as exc:
        raise LookupError(f"Champion '{name}' not found") from exc
    if champion["name"] not in _VERIFIED_CHAMPIONS:
        raise ValueError(f"Champion '{champion['name']}' is not verified")
    return champion


def _public_loadout_summary(loadout) -> dict:
    """Sanitize one resolved loadout for the browser."""
    summary = loadout.public_summary()
    summary["icon"] = _https_icon(summary["icon"])
    summary["item_icons"] = [_https_icon(icon) for icon in summary["item_icons"]]
    summary["verified_attacker"] = summary["champion"] in _VERIFIED_CHAMPIONS
    return summary


def _serialize_fight_result(result: Mapping[str, object]) -> dict:
    """Translate one engine result into the stable public response shape."""
    breakdown = result.get("breakdown", {})
    api_breakdown = {}
    for key, entry in breakdown.items():
        has_damage = entry.get("total_damage", 0.0) > 0
        if not (has_damage or "detail" in entry):
            continue
        row = {
            "name": entry.get("name", key),
            "total_damage": round(entry.get("total_damage", 0.0), 1),
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
        for display_key in ("detail", "damage_display"):
            if display_key in entry:
                row[display_key] = entry[display_key]
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
        "resource_spent": round(result.get("resource_spent", 0.0), 1),
        "resource_remaining": round(result.get("resource_remaining", 0.0), 1),
    }


def _allocate_target_limited_damage(target_results: list[dict]) -> None:
    """Allocate one shared charged proc across legal roster targets once."""
    if not target_results:
        return
    target_count = len(target_results)
    keys = {
        key
        for target in target_results
        for key, row in target["result"]["breakdown"].items()
        if row.get("targeting", {}).get("kind") == "charged_bounce"
    }
    for key in keys:
        first_row = target_results[0]["result"]["breakdown"].get(key, {})
        targeting = first_row.get("targeting", {})
        charges = int(targeting["charges"])
        repeat = float(targeting["repeat_multiplier"])
        solo_multiplier = float(targeting["single_target_multiplier"])
        unique_targets = min(target_count, charges)
        for index, target in enumerate(target_results):
            result = target["result"]
            row = result["breakdown"].get(key)
            if row is None:
                continue
            desired_multiplier = (
                1.0 + max(0, charges - unique_targets) * repeat
                if index == 0
                else (1.0 if index < unique_targets else 0.0)
            )
            old_damage = row["total_damage"]
            new_damage = old_damage * desired_multiplier / solo_multiplier
            delta = new_damage - old_damage
            row["total_damage"] = round(new_damage, 1)
            result["total_damage"] = round(result["total_damage"] + delta, 1)
            result["ability_damage"] = round(result["ability_damage"] + delta, 1)
            result["damage_by_type"]["magic"] = round(
                result["damage_by_type"].get("magic", 0.0) + delta, 1
            )
            available_shield = float(
                target["target"].get("starting_defenses", {}).get("magic_shield", 0.0)
            )
            magic_absorbed = min(
                available_shield, result["damage_by_type"].get("magic", 0.0)
            )
            result["magic_shield_absorbed"] = round(magic_absorbed, 1)
            result["shield_absorbed"] = round(magic_absorbed, 1)
            result["health_damage"] = round(
                max(0.0, result["total_damage"] - magic_absorbed), 1
            )


def _aggregate_public_results(results: list[dict]) -> dict:
    """Sum the same selected damage package across every hit target."""
    primary = results[0]
    target_count = len(results)
    damage_types = {"physical": 0.0, "magic": 0.0, "true": 0.0}
    breakdown = {}
    for result in results:
        for damage_type, amount in result["damage_by_type"].items():
            damage_types[damage_type] = damage_types.get(damage_type, 0.0) + amount
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
                },
            )
            aggregate["total_damage"] += entry["total_damage"]

    for entry in breakdown.values():
        entry["total_damage"] = round(entry["total_damage"], 1)
        target_label = "target" if target_count == 1 else "targets"
        entry["detail"] = f"Across {target_count} selected {target_label}"

    return {
        "champion_stats": primary["champion_stats"],
        "total_damage": round(sum(result["total_damage"] for result in results), 1),
        "health_damage": round(sum(result["health_damage"] for result in results), 1),
        "shield_absorbed": round(
            sum(result["shield_absorbed"] for result in results), 1
        ),
        "ability_damage": round(sum(result["ability_damage"] for result in results), 1),
        "auto_attack_damage": round(
            sum(result["auto_attack_damage"] for result in results), 1
        ),
        "damage_by_type": {
            damage_type: round(amount, 1)
            for damage_type, amount in damage_types.items()
        },
        "breakdown": breakdown,
        # Existing result cards expect scalar effective defenses.  The first
        # selected enemy is the primary target; every target's values are also
        # available in the per-target table.
        "effective_mr": primary["effective_mr"],
        "effective_armor": primary["effective_armor"],
        "cast_timeline": primary.get("cast_timeline", []),
        "resource_spent": primary.get("resource_spent", 0.0),
        "resource_remaining": primary.get("resource_remaining", 0.0),
        "notes": list(primary.get("notes", [])),
    }


def _dev_mode() -> bool:
    """True when LOL_CALC_DEV=1 (run_web.bat sets it; deployments don't).

    Gates the wiki re-scrape endpoint: patch-day data updates run locally
    and ship to the deployed site as a git-tracked data/ cache
    (see docs/deploy.md).
    """
    return os.environ.get("LOL_CALC_DEV") == "1" and os.environ.get("RENDER") != "true"


def _local_dev_request() -> bool:
    """Require both local dev mode and a loopback network peer."""
    if not _dev_mode() or not request.remote_addr:
        return False
    try:
        peer_is_loopback = ipaddress.ip_address(request.remote_addr).is_loopback
        host = urlsplit(f"//{request.host}").hostname
        host_is_local = host == "localhost" or (
            host is not None and ipaddress.ip_address(host).is_loopback
        )
        return peer_is_loopback and host_is_local
    except ValueError:
        return False


def _https_icon(url: str) -> str:
    """Force https on icon URLs at the API boundary.

    The wiki cache stores Data Dragon links as http://, which an https
    site can't display without mixed-content warnings. Serving-side fix
    so the cache stays byte-for-byte what the scraper wrote."""
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
        or parsed.hostname not in _ICON_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        return ""
    return url


def _run_data_update():
    """Import data_updater only when actually updating: its import chain
    pulls in vendor/lolstaticdata, which production images don't ship."""
    # pylint: disable-next=import-outside-toplevel  # deliberate, see docstring
    from calculator.data_updater import update_data

    return update_data()


@app.route("/")
def index():
    """Serve the main calculator page."""
    return render_template(
        "index.html",
        default_target=DEFAULT_TARGET,
        default_fight_duration=DEFAULT_FIGHT_DURATION,
        default_auto_attack_uptime=DEFAULT_AUTO_ATTACK_UPTIME,
        max_level=MAX_LEVEL,
        input_limits=PUBLIC_INPUT_LIMITS,
    )


@app.route("/healthz")
def health():
    """Cheap liveness probe that avoids loading calculator data."""
    return jsonify({"status": "ok"})


@app.route("/api/champions")
def api_champions():
    """Return champion names, icons, and verified flags for the picker.

    ``verified`` = has a module in src/calculator/champions/ (the registry
    is the source of truth). The picker greys out unverified champions —
    generic-path numbers are estimates, never citable (CLAUDE.md rule 6).
    Verified champions sort first, then unverified, A-Z within each group.
    """
    champions = fetch_champion_data()
    result = sorted(
        [
            {
                "name": champ_data["name"],
                "icon": _https_icon(champ_data.get("icon", "")),
                "verified": champ_data["name"] in _VERIFIED_CHAMPIONS,
            }
            for champ_data in champions.values()
        ],
        key=lambda c: (not c["verified"], c["name"]),
    )
    return jsonify(result)


@app.route("/api/items")
def api_items():
    """Return ordinary build items for manual attacker/roster loadouts."""
    result = sorted(
        [
            {"name": item["name"], "icon": _https_icon(item.get("icon", ""))}
            for item in get_selectable_items()
        ],
        key=lambda i: i["name"],
    )
    return jsonify(result)


@app.route("/api/boots")
def api_boots():
    """Return tier-2 and quest-only tier-3 boots for the role-aware picker."""
    result = sorted(
        [
            {
                "name": item["name"],
                "icon": _https_icon(item.get("icon", "")),
                "tier": item.get("tier"),
            }
            for item in get_eligible_boots(tier=None)
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
    local_dev = _local_dev_request()
    cache_meta_path = (
        Path(__file__).resolve().parent.parent / "data" / ".champions.json.meta"
    )
    try:
        cache_meta = json.loads(cache_meta_path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromtimestamp(
            float(cache_meta["fetched_at"]), tz=timezone.utc
        ).isoformat()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        fetched_at = None
    response = jsonify(
        {
            "exclusivity_groups": exclusivity_groups(),
            "default_target": DEFAULT_TARGET,
            "fight_defaults": {
                "mode": DEFAULT_FIGHT_MODE,
                "duration_seconds": DEFAULT_FIGHT_DURATION,
                "auto_attack_uptime": DEFAULT_AUTO_ATTACK_UPTIME,
                "one_rotation_duration_seconds": ONE_ROTATION_DURATION,
            },
            "input_limits": PUBLIC_INPUT_LIMITS,
            "champion_options": champion_options_meta_map(),
            "item_options": item_input_options_meta(),
            "dev_mode": local_dev,
            "data_snapshot": {
                "source": "League of Legends Wiki cache",
                "fetched_at": fetched_at,
                "champion_count": len(fetch_champion_data()),
            },
        }
    )
    if local_dev:
        response.set_cookie(
            _DEV_UPDATE_COOKIE,
            _DEV_UPDATE_TOKEN,
            max_age=3600,
            httponly=True,
            samesite="Strict",
            path="/api/update-data",
        )
    return response


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
                "icon": _https_icon(ability_list[0].get("icon", "")),
            }
        elif ability_list and isinstance(ability_list[0], str):
            result[key] = {"name": ability_list[0], "icon": ""}
        else:
            result[key] = {"name": key, "icon": ""}
    return jsonify(result)


@app.route("/api/loadout-stats", methods=["POST"])
def api_loadout_stats():
    """Return champion-derived stats for one level and item loadout."""
    try:
        data = _json_object()
        loadout = ChampionLoadout.from_request(data, field="loadout").resolve()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "requested data"
        return jsonify({"error": f"'{missing}' not found"}), 404
    return jsonify(_public_loadout_summary(loadout))


@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    """Run the damage calculation and return results."""
    try:
        data = _json_object()
        champion_name = _request_string(data, "champion", required=True)
        level = _request_int(data, "level", 1, 1, MAX_LEVEL)
        item_names = _request_string_list(data, "items", maximum=6)
        boots_name = _request_string(data, "boots")
        fight_params = FightParams.from_request(data)
        enemy_requests = parse_roster(data, "enemies", maximum=MAX_ENEMIES)
        ally_requests = parse_roster(data, "allies", maximum=MAX_ALLIES)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        champion_data = _load_public_champion(champion_name)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    try:
        fight_params.validate_for_champion(champion_data["name"], level)
        _validate_champion_options(champion_data["name"], data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Resolve and validate the inventory in the same backend contract used by BIS.
    try:
        resolved_boots = (
            _resolve_named_item(boots_name, kind="Boots") if boots_name else None
        )
        ordinary_items = [_resolve_named_item(item_name) for item_name in item_names]
        validate_resolved_loadout(
            ordinary_items,
            boots=resolved_boots,
            role=fight_params.role,
            role_quest_complete=fight_params.role_quest_complete,
        )
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    items = ([resolved_boots] if resolved_boots else []) + ordinary_items

    try:
        enemies = [loadout.resolve() for loadout in enemy_requests]
        allies = [loadout.resolve() for loadout in ally_requests]
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "requested data"
        return jsonify({"error": f"Scenario data '{missing}' not found"}), 404

    rate_limit_response = _spend_rate_limit("calculate")
    if rate_limit_response is not None:
        return rate_limit_response

    ally_effects = tuple(
        effect
        for ally in allies
        if ally.request.ally_effects_enabled
        for effect in resolve_ally_stat_effects(ally.item_data)
    )
    if ally_effects:
        fight_params = replace(
            fight_params,
            ally_stat_bonuses=combine_ally_stat_effects(ally_effects),
        )

    if not enemies:
        result = run_fight(champion_data, level, items, fight_params)
        response = _serialize_fight_result(result)
        response["role_quest"] = (
            role_quest_meta(fight_params.role, fight_params.role_quest_complete)
            if fight_params.role
            else None
        )
        if allies:
            response.update(
                {
                    "allies": [_public_loadout_summary(ally) for ally in allies],
                    "scenario": {
                        "target_count": 1,
                        "aggregation": "Manual target",
                        "primary_target": "Manual target",
                        "ally_effects": {
                            "modeled": [effect.source for effect in ally_effects],
                            "unmodeled": [
                                ally.champion_data["name"] for ally in allies
                            ],
                            "note": (
                                "Allies are included as sourced context; outgoing "
                                "ally buffs are applied only when an explicit tested "
                                "effect exists."
                            ),
                        },
                    },
                }
            )
        return jsonify(response)

    target_results = []
    for enemy in enemies:
        target_params = replace(
            fight_params,
            target_health=enemy.stats["health"],
            target_bonus_health=enemy.stats["bonus_health"],
            target_armor=enemy.stats["armor"],
            target_magic_resistance=enemy.stats["magic_resistance"],
            target_magic_shield=enemy.defenses.magic_shield,
            target_physical_shield=enemy.defenses.physical_shield,
            target_general_shield=enemy.defenses.general_shield,
        )
        serialized = _serialize_fight_result(
            run_fight(champion_data, level, items, target_params)
        )
        target_results.append(
            {"target": _public_loadout_summary(enemy), "result": serialized}
        )

    _allocate_target_limited_damage(target_results)
    response = _aggregate_public_results(
        [target["result"] for target in target_results]
    )
    response.update(
        {
            "targets": target_results,
            "allies": [_public_loadout_summary(ally) for ally in allies],
            "scenario": {
                "target_count": len(target_results),
                "aggregation": "Same selected damage package landed on every target",
                "primary_target": target_results[0]["target"]["champion"],
                "ally_effects": {
                    "modeled": [effect.source for effect in ally_effects],
                    "unmodeled": [ally.champion_data["name"] for ally in allies],
                    "note": (
                        "Allies are included as sourced context; outgoing ally buffs "
                        "are applied only when an explicit tested effect exists."
                    ),
                },
            },
            "role_quest": (
                role_quest_meta(fight_params.role, fight_params.role_quest_complete)
                if fight_params.role
                else None
            ),
        }
    )
    return jsonify(response)


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    """Find the optimal item build for a champion."""
    try:
        data = _json_object()
        champion_name = _request_string(data, "champion", required=True)
        level = _request_int(data, "level", 1, 1, MAX_LEVEL)
        objective = _request_string(data, "objective", "total_damage")
        locked_items = _request_string_list(data, "locked_items", maximum=6)
        locked_boots = _request_string(data, "locked_boots")
        max_legendary_slots = _request_int(data, "max_legendary_slots", 5, 1, 6)
        gold_budget = (
            _request_int(data, "gold_budget", 0, 1, 30_000)
            if data.get("gold_budget") not in (None, "")
            else None
        )
        fight_params = FightParams.from_request(data, deterministic=True)
        enemy_requests = parse_roster(data, "enemies", maximum=MAX_ENEMIES)
        ally_requests = parse_roster(data, "allies", maximum=MAX_ALLIES)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        champion_data = _load_public_champion(champion_name)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422

    try:
        fight_params.validate_for_champion(champion_data["name"], level)
        _validate_champion_options(champion_data["name"], data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Optimizer-specific parameters
    if objective not in ("total_damage", "physical_damage", "magic_damage"):
        return jsonify({"error": "Invalid objective"}), 400
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

    allowed_slots = (
        6 if fight_params.role == "bottom" and fight_params.role_quest_complete else 5
    )
    if max_legendary_slots > allowed_slots:
        return (
            jsonify(
                {"error": ("Six ordinary items require a completed bottom role quest")}
            ),
            400,
        )

    try:
        resolved_locked = [_resolve_named_item(name) for name in locked_items]
        resolved_boots = (
            _resolve_named_item(locked_boots, kind="Boots") if locked_boots else None
        )
        validate_resolved_loadout(
            resolved_locked,
            boots=resolved_boots,
            role=fight_params.role,
            role_quest_complete=fight_params.role_quest_complete,
        )
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        enemies = [loadout.resolve() for loadout in enemy_requests]
        allies = [loadout.resolve() for loadout in ally_requests]
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "requested data"
        return jsonify({"error": f"Scenario data '{missing}' not found"}), 404

    ally_effects = tuple(
        effect
        for ally in allies
        if ally.request.ally_effects_enabled
        for effect in resolve_ally_stat_effects(ally.item_data)
    )
    if ally_effects:
        fight_params = replace(
            fight_params,
            ally_stat_bonuses=combine_ally_stat_effects(ally_effects),
        )

    target_fight_params = tuple(
        replace(
            fight_params,
            target_health=enemy.stats["health"],
            target_bonus_health=enemy.stats["bonus_health"],
            target_armor=enemy.stats["armor"],
            target_magic_resistance=enemy.stats["magic_resistance"],
            target_magic_shield=enemy.defenses.magic_shield,
            target_physical_shield=enemy.defenses.physical_shield,
            target_general_shield=enemy.defenses.general_shield,
        )
        for enemy in enemies
    )

    rate_limit_response = _spend_rate_limit("optimize")
    if rate_limit_response is not None:
        return rate_limit_response

    try:
        result = optimize_build(
            champion_data=champion_data,
            level=level,
            fight_params=fight_params,
            objective=objective,
            locked_items=locked_items if locked_items else None,
            locked_boots=locked_boots if locked_boots else None,
            max_legendary_slots=max_legendary_slots,
            target_fight_params=target_fight_params or None,
            boots_tier=(
                3
                if fight_params.role == "mid" and fight_params.role_quest_complete
                else 2
            ),
            gold_budget=gold_budget,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(result)


@app.route("/api/update-data")
def api_update_data():
    """Stream data update progress via Server-Sent Events. Dev-only:
    404s unless LOL_CALC_DEV=1 (see _dev_mode)."""
    supplied_token = request.cookies.get(_DEV_UPDATE_COOKIE, "")
    if not _local_dev_request() or not hmac.compare_digest(
        supplied_token, _DEV_UPDATE_TOKEN
    ):
        return jsonify({"error": "Data updates are disabled on this server"}), 404

    def generate():
        for event in _run_data_update():
            yield f"data: {json.dumps(event)}\n\n"
        # Fresh item JSON is now on disk — re-parse ITEM_EFFECTS in place
        # so in-memory effects reflect the newly fetched patch data.
        refresh_item_effects()

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=_dev_mode(), port=5000)
