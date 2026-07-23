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
from collections.abc import Mapping
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
from calculator.item_effects import refresh_item_effects
from calculator.champions import champion_options_meta_map, registered_champion_names
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
    """Return the optimizer-eligible legendaries (name + icon), sorted.

    Delegates eligibility to the optimizer so the manual item picker and
    the optimizer's candidate set can never diverge.
    """
    result = sorted(
        [
            {"name": item["name"], "icon": _https_icon(item.get("icon", ""))}
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
            {"name": item["name"], "icon": _https_icon(item.get("icon", ""))}
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
    local_dev = _local_dev_request()
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
            "dev_mode": local_dev,
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
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        champion_data = _load_public_champion(champion_name)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    try:
        _validate_champion_options(champion_data["name"], data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Resolve items
    items = []
    try:
        if boots_name:
            items.append(_resolve_named_item(boots_name, kind="Boots"))
        items.extend(_resolve_named_item(item_name) for item_name in item_names)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404

    rate_limit_response = _spend_rate_limit("calculate")
    if rate_limit_response is not None:
        return rate_limit_response

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
            # Count label for the detail cell ("procs" vs default "hits")
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
            "damage_by_type": {
                dtype: round(amount, 1)
                for dtype, amount in result["damage_by_type"].items()
            },
            "breakdown": api_breakdown,
            "effective_mr": round(result.get("effective_mr", 0.0), 1),
            "effective_armor": round(result.get("effective_armor", 0.0), 1),
        }
    )


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
        fight_params = FightParams.from_request(data, deterministic=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        champion_data = _load_public_champion(champion_name)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422

    try:
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

    try:
        for item_name in locked_items:
            _resolve_named_item(item_name)
        if locked_boots:
            _resolve_named_item(locked_boots, kind="Boots")
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404

    rate_limit_response = _spend_rate_limit("optimize")
    if rate_limit_response is not None:
        return rate_limit_response

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
