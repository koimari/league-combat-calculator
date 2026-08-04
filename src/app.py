"""Flask web application for the LoL Damage Calculator."""

import hmac
import base64
import binascii
import hashlib
import html
import ipaddress
import json
import math
import os
import secrets
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Ensure the src directory is on the path so calculator imports work
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from calculator.data_fetcher import (
    fetch_champion_data,
    get_champion,
    get_item_by_name,
)
from calculator.item_effects import (
    item_input_options_meta,
    refresh_item_effects,
    stat_conversion_metadata,
)
from calculator.rune_effects import keystone_catalog, refresh_rune_effects
from calculator.item_coverage import (
    item_model_coverage,
    require_calculation_item_coverage,
    require_certified_target_timeline,
    require_target_item_coverage,
    target_item_model_coverage,
    target_build_coverage,
)
from calculator.ally_effects import combine_ally_stat_effects, resolve_ally_stat_effects
from calculator.loadout_rules import role_scoped_shop_items, validate_resolved_loadout
from calculator.defensive_effects import resolve_starting_defenses
from calculator.participant_timeline import (
    build_participant_timeline,
    require_roster_fight_window_support,
)
from calculator.champions import (
    champion_options_meta_map,
    engine_registration_kind,
    get_comparison_curve_unavailable_reason,
    registered_engine_champion_names,
    registered_champion_names,
)
from calculator.champion_coverage import attacker_availability
from calculator.capabilities import public_capability_contract
from calculator.optimizer import (
    exclusivity_groups,
    get_eligible_boots,
    get_eligible_legendaries,
    get_selectable_items,
    optimize_build,
    optimizer_supported_items,
)
from calculator.stats import MAX_LEVEL
from calculator.stats import calculate_total_stats, get_item_stats
from calculator.timeline_coverage import applicability_exclusion_sources
from calculator.scenario import (
    MAX_ALLIES,
    MAX_ENEMIES,
    MAX_LOADOUT_ITEMS,
    ChampionLoadout,
    parse_roster,
)
from calculator.role_quests import (
    require_level_within_cap,
    boot_upgrade_contract,
    role_quest_meta,
    support_quest_item_contract,
    support_quest_item_stage,
)
from calculator.timeline_coverage import combine_timeline_coverages
from calculator.pipeline import (
    DEFAULT_AUTO_ATTACK_UPTIME,
    DEFAULT_AUTO_ATTACK_UPTIME_MODE,
    DEFAULT_FIGHT_DURATION,
    DEFAULT_FIGHT_MODE,
    DEFAULT_TARGET,
    ONE_ROTATION_DURATION,
    MAX_ROTATIONS,
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

_AUTH_COOKIE = "scryglass_session"
_AUTH_TTL_SECONDS = 7 * 24 * 60 * 60

_RATE_LIMIT_POLICIES = {
    "calculate": (40, 20.0),
    # Worst max-valid optimizer request measured at 1.81 CPU seconds locally.
    # One token per 10 seconds caps sustained abuse near 20% of one core while
    # the independent calculate budget keeps the ordinary UI responsive.
    "optimize": (2, 0.1),
}
_VERIFIED_CHAMPIONS = frozenset(registered_champion_names())
_ENGINE_CHAMPIONS = frozenset(registered_engine_champion_names())
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


def _generic_engine_enabled() -> bool:
    """Compatibility flag retained for old clients; no generic lane exists."""
    return False


def _auth_enabled() -> bool:
    """Return whether the deployment requires an approved X session."""
    return os.environ.get("SCRYGLASS_AUTH_REQUIRED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _auth_secret() -> bytes:
    """Return the cookie-signing secret; production must provide one."""
    secret = os.environ.get("SCRYGLASS_AUTH_SECRET", "").strip()
    if not secret and _auth_enabled():
        raise RuntimeError("SCRYGLASS_AUTH_SECRET is required when auth is enabled")
    return (secret or "local-development-only-secret").encode("utf-8")


def _pack_signed(value: Mapping[str, object]) -> str:
    """Sign a compact JSON cookie without storing OAuth tokens server-side."""
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    signature = hmac.new(
        _auth_secret(), payload.encode("ascii"), hashlib.sha256
    ).digest()
    signed = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{payload}.{signed}"


def _unpack_signed(value: str | None) -> dict | None:
    """Validate one signed cookie and reject malformed or expired payloads."""
    if not value or "." not in value:
        return None
    payload, supplied_signature = value.split(".", 1)
    expected_signature = (
        base64.urlsafe_b64encode(
            hmac.new(_auth_secret(), payload.encode("ascii"), hashlib.sha256).digest()
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    if not hmac.compare_digest(supplied_signature, expected_signature):
        return None
    try:
        padded = payload + "=" * (-len(payload) % 4)
        result = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        return None
    if not isinstance(result, dict) or float(result.get("exp", 0)) < time.time():
        return None
    return result


def _current_session() -> dict | None:
    """Read the stateless approved-user session."""
    try:
        return _unpack_signed(request.cookies.get(_AUTH_COOKIE))
    except RuntimeError:
        return None


def _auth_users() -> dict[str, str]:
    """Load the explicit username -> scrypt password-hash map."""
    raw = os.environ.get("SCRYGLASS_AUTH_USERS", "").strip()
    if not raw:
        raise RuntimeError("SCRYGLASS_AUTH_USERS is required when auth is enabled")
    try:
        users = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("SCRYGLASS_AUTH_USERS must be valid JSON") from exc
    if (
        not isinstance(users, dict)
        or not users
        or any(
            not isinstance(username, str)
            or not username.strip()
            or not isinstance(password_hash, str)
            or not password_hash.startswith("scrypt$")
            for username, password_hash in users.items()
        )
    ):
        raise RuntimeError(
            "SCRYGLASS_AUTH_USERS must map account names to scrypt$ password hashes"
        )
    return {username: password_hash for username, password_hash in users.items()}


def _verify_password(password: str, encoded: str) -> bool:
    """Verify an encoded scrypt password without exposing password material."""
    try:
        _, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$", 5)
        n, r, p = int(n_text), int(r_text), int(p_text)
        salt = base64.urlsafe_b64decode(
            (salt_text + "=" * (-len(salt_text) % 4)).encode("ascii")
        )
        expected = base64.urlsafe_b64decode(
            (digest_text + "=" * (-len(digest_text) % 4)).encode("ascii")
        )
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected)
        )
    except (ValueError, TypeError, binascii.Error):
        return False
    return hmac.compare_digest(actual, expected)


def _safe_next_path(value: str | None) -> str:
    """Accept only local paths after login; reject open redirects."""
    path = value or "/"
    return path if path.startswith("/") and not path.startswith("//") else "/"


def _auth_error(message: str, status: int = 503):
    """Return a concise setup/error response without leaking password data."""
    return jsonify({"error": message}), status


def _login_page(message: str = "", status: int = 200, next_path: str = "/"):
    """Render the tiny access gate without depending on protected assets."""
    notice = (
        f'<p style="color:#c5120b" role="alert">{html.escape(message)}</p>'
        if message
        else ""
    )
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scryglass · Private calculator</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#121212;color:#f1f1f1;font:16px/1.5 Georgia,serif}}main{{width:min(420px,calc(100% - 40px));padding:32px;background:#181818;border:1px solid #2d2d2d;box-shadow:0 16px 50px #00000066}}h1{{margin:0 0 8px;font-size:28px}}p{{margin:8px 0 22px;color:#a4a4a4}}label{{display:grid;gap:6px;margin:14px 0;color:#a4a4a4;font:12px/1.2 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em}}input{{box-sizing:border-box;width:100%;padding:12px;border:1px solid #464646;background:#202020;color:#f1f1f1;font:16px Georgia,serif}}button{{margin-top:8px;width:100%;padding:12px;border:0;background:#c5120b;color:#f1f1f1;font:12px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.1em;cursor:pointer}}</style></head>
<body><main><p style="font:11px ui-monospace,monospace;letter-spacing:.14em;text-transform:uppercase;color:#c5120b">Private calculator</p><h1>Sign in to Scryglass</h1><p>This page is restricted to approved research accounts.</p>{notice}<form method="post" action="/auth/login"><input type="hidden" name="next" value="{html.escape(next_path, quote=True)}"><label>Username<input name="username" autocomplete="username" required autofocus></label><label>Password<input type="password" name="password" autocomplete="current-password" required></label><button type="submit">Enter calculator</button></form></main></body></html>"""
    return Response(page, status=status, mimetype="text/html")


@app.before_request
def _enforce_authentication():
    """Gate the UI, assets, and APIs when the deployment enables X auth."""
    if not _auth_enabled():
        return None
    if request.path == "/healthz" or request.path.startswith("/auth/"):
        return None
    if _current_session():
        return None
    next_path = request.full_path.rstrip("?") if request.full_path else "/"
    return redirect(url_for("auth_login", next=next_path))


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
        if option_type == "select":
            if isinstance(value, bool) and option.get("legacy_bool"):
                continue
            if not isinstance(value, str):
                raise ValueError(f"champion_options.{key} must be a string")
            choices = {choice["value"] for choice in option["choices"]}
            if value not in choices:
                raise ValueError(
                    f"champion_options.{key} must be one of {sorted(choices)}"
                )
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
    if champion["name"] not in _ENGINE_CHAMPIONS:
        availability = attacker_availability(champion, _VERIFIED_CHAMPIONS)
        reason = availability["blockers"][0]["label"]
        raise ValueError(f"Champion '{champion['name']}' is not verified: {reason}")
    return champion


def _public_loadout_summary(loadout) -> dict:
    """Sanitize one resolved loadout for the browser."""
    summary = loadout.public_summary()
    summary["icon"] = _https_icon(summary["icon"])
    summary["item_icons"] = [_https_icon(icon) for icon in summary["item_icons"]]
    summary["verified_attacker"] = summary["champion"] in _VERIFIED_CHAMPIONS
    summary["engine_registered"] = summary["champion"] in _ENGINE_CHAMPIONS
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


def _serialize_fight_result(result: Mapping[str, object]) -> dict:
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


def _aggregate_public_results(results: list[dict]) -> dict:
    """Sum the same selected damage package across every hit target."""
    primary = results[0]
    target_count = len(results)
    timeline_coverage = _aggregate_timeline_coverage(results)
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

    return {
        "champion_stats": primary["champion_stats"],
        "total_damage": round(sum(result["total_damage"] for result in results), 1),
        "health_damage": round(sum(result["health_damage"] for result in results), 1),
        "shield_absorbed": round(
            sum(result["shield_absorbed"] for result in results), 1
        ),
        "magic_shield_absorbed": round(
            sum(result.get("magic_shield_absorbed", 0.0) for result in results), 1
        ),
        "physical_shield_absorbed": round(
            sum(result.get("physical_shield_absorbed", 0.0) for result in results), 1
        ),
        "general_shield_absorbed": round(
            sum(result.get("general_shield_absorbed", 0.0) for result in results), 1
        ),
        "threshold_shield_absorbed": round(
            sum(result.get("threshold_shield_absorbed", 0.0) for result in results), 1
        ),
        "threshold_health_triggered": any(
            result.get("threshold_health_triggered", False) for result in results
        ),
        "threshold_health_bonus_gained": round(
            sum(result.get("threshold_health_bonus_gained", 0.0) for result in results),
            1,
        ),
        "target_healing_received": round(
            sum(result.get("target_healing_received", 0.0) for result in results), 1
        ),
        "target_ending_health": round(
            sum(result.get("target_ending_health", 0.0) for result in results), 1
        ),
        "target_effective_max_health": round(
            sum(result.get("target_effective_max_health", 0.0) for result in results), 1
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
        # Each target runs the same ordered package independently. Preserve
        # the resulting recovery receipts when the public response aggregates
        # those target results, otherwise the frontend would lose standalone
        # self-healing even though every per-target engine result emitted it.
        "self_healing": round(
            sum(float(result.get("self_healing", 0.0)) for result in results), 1
        ),
        "self_healing_events": [
            event
            for result in results
            for event in result.get("self_healing_events", [])
        ],
        # Existing result cards expect scalar effective defenses.  The first
        # selected enemy is the primary target; every target's values are also
        # available in the per-target table.
        "effective_mr": primary["effective_mr"],
        "effective_armor": primary["effective_armor"],
        "cast_timeline": primary.get("cast_timeline", []),
        "resource_spent": primary.get("resource_spent", 0.0),
        "resource_remaining": primary.get("resource_remaining", 0.0),
        "notes": list(primary.get("notes", [])),
        "timeline_coverage": timeline_coverage,
        "auto_attack_policy": dict(primary.get("auto_attack_policy", {})),
        "auto_attack_schedule": dict(primary.get("auto_attack_schedule", {})),
    }


def _comparison_curve(
    champion_data: dict,
    level: int,
    items: list[dict],
    fight_params: FightParams,
    enemies: list,
) -> list[dict]:
    """Score one build through six rotation-length timed windows.

    A point is a continuous fight lasting ``ONE_ROTATION_DURATION`` times its
    index. Cooldowns, resources, regeneration, autos, burns, shields, and
    target-specific mitigation are therefore recomputed rather than multiplied
    from the opening rotation.
    """
    points = []
    for rotation in range(1, 7):
        duration = ONE_ROTATION_DURATION * rotation
        params = replace(
            fight_params,
            fight_duration_seconds=duration,
            one_rotation=False,
        )
        if not enemies:
            result = _serialize_fight_result(
                run_fight(champion_data, level, items, params)
            )
        else:
            target_results = []
            for target_index, enemy in enumerate(enemies):
                target_params = replace(
                    params,
                    roster_target_index=target_index,
                    roster_target_count=len(enemies),
                    target_health=enemy.stats["health"],
                    target_bonus_health=enemy.stats["bonus_health"],
                    target_armor=enemy.stats["armor"],
                    target_magic_resistance=enemy.stats["magic_resistance"],
                    target_magic_shield=enemy.defenses.magic_shield,
                    target_physical_shield=enemy.defenses.physical_shield,
                    target_general_shield=enemy.defenses.general_shield,
                    target_basic_damage_multiplier=(
                        enemy.defenses.basic_damage_multiplier
                    ),
                    target_basic_damage_flat_reduction=(
                        enemy.defenses.basic_damage_flat_reduction
                    ),
                    target_basic_damage_flat_reduction_cap=(
                        enemy.defenses.basic_damage_flat_reduction_cap
                    ),
                    target_critical_strike_damage_multiplier=(
                        enemy.defenses.critical_strike_damage_multiplier
                    ),
                    target_threshold_shield_amount=(
                        enemy.defenses.threshold_shield_amount
                    ),
                    target_threshold_shield_health_ratio=(
                        enemy.defenses.threshold_shield_health_ratio
                    ),
                    target_threshold_shield_duration=(
                        enemy.defenses.threshold_shield_duration
                    ),
                    target_threshold_shield_damage_type=(
                        enemy.defenses.threshold_shield_damage_type
                    ),
                    target_threshold_health_bonus=(
                        enemy.defenses.threshold_health_bonus
                    ),
                    target_threshold_health_heal=(enemy.defenses.threshold_health_heal),
                    target_threshold_health_ratio=(
                        enemy.defenses.threshold_health_ratio
                    ),
                    target_threshold_health_duration=(
                        enemy.defenses.threshold_health_duration
                    ),
                )
                target_result = run_fight(champion_data, level, items, target_params)
                # Every curve point is a timed fight, so it needs the same
                # certified-timeline gate as a timed primary result — even
                # when the request itself was one-rotation.
                require_certified_target_timeline(
                    list(enemy.item_data),
                    target_result.get("timeline_coverage", {}),
                )
                target_results.append(
                    {
                        "target": _public_loadout_summary(enemy),
                        "result": _serialize_fight_result(target_result),
                    }
                )
            result = _aggregate_public_results(
                [target["result"] for target in target_results]
            )
        total = float(result["total_damage"])
        points.append(
            {
                "rotation": rotation,
                "seconds": duration,
                "total_damage": round(total, 1),
                "dps": round(total / duration, 1),
                "ability_damage": round(float(result["ability_damage"]), 1),
                "auto_attack_damage": round(float(result["auto_attack_damage"]), 1),
            }
        )
    return points


def _add_comparison_curve(
    response: dict,
    champion_data: dict,
    level: int,
    items: list[dict],
    fight_params: FightParams,
    enemies: list,
) -> None:
    """Attach crossover windows or an explicit fail-closed receipt."""
    reason = get_comparison_curve_unavailable_reason(champion_data["name"])
    if reason:
        response["comparison_curve"] = []
        response["comparison_curve_status"] = {
            "available": False,
            "reason": reason,
        }
        return
    try:
        response["comparison_curve"] = _comparison_curve(
            champion_data, level, items, fight_params, enemies
        )
    except ValueError as exc:
        # The curve is an optional add-on: withhold it with the gate's own
        # explanation instead of failing a valid primary result.
        response["comparison_curve"] = []
        response["comparison_curve_status"] = {
            "available": False,
            "reason": str(exc),
        }
        return
    response["comparison_curve_status"] = {"available": True}


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


def _prototype_local_request() -> bool:
    """Keep the visual prototype available to loopback browsers only.

    The prototype intentionally uses illustrative client-side data. It is a
    useful design surface for local interaction review, but it must never be
    mistaken for the calculator's production data path or be publicly served.
    """
    if not request.remote_addr:
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


@app.route("/auth/login", methods=["GET", "POST"])
def auth_login():
    """Authenticate one of the explicitly configured private accounts."""
    try:
        _auth_secret()
        users = _auth_users()
    except RuntimeError as exc:
        return _auth_error(str(exc))
    next_path = _safe_next_path(
        request.form.get("next")
        if request.method == "POST"
        else request.args.get("next")
    )
    if request.method == "GET":
        return _login_page(next_path=next_path)
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    encoded = users.get(username)
    if not encoded or not _verify_password(password, encoded):
        return _login_page("Username or password was not recognised.", 401, next_path)
    session = _pack_signed(
        {"username": username, "exp": time.time() + _AUTH_TTL_SECONDS}
    )
    response = redirect(next_path)
    response.set_cookie(
        _AUTH_COOKIE,
        session,
        max_age=_AUTH_TTL_SECONDS,
        httponly=True,
        secure=request.is_secure or os.environ.get("VERCEL") == "1",
        samesite="Lax",
        path="/",
    )
    return response


@app.route("/auth/logout", methods=["GET", "POST"])
def auth_logout():
    """End the local approved-user session."""
    response = redirect("/")
    response.delete_cookie(_AUTH_COOKIE, path="/")
    return response


@app.route("/auth/status")
def auth_status():
    """Expose only the current local identity."""
    session = _current_session()
    return jsonify(
        {
            "required": _auth_enabled(),
            "authenticated": bool(session),
            "user": session or None,
        }
    )


@app.route("/")
def index():
    """Serve the main calculator page."""
    session = _current_session()
    return render_template(
        "index.html",
        default_target=DEFAULT_TARGET,
        default_fight_duration=DEFAULT_FIGHT_DURATION,
        default_auto_attack_uptime=DEFAULT_AUTO_ATTACK_UPTIME,
        max_level=MAX_LEVEL,
        input_limits=PUBLIC_INPUT_LIMITS,
        auth_user=session.get("username") if session else None,
    )


@app.route("/prototype/manrope-blackwhite/")
def manrope_prototype_index():
    """Serve the local-only visual prototype without replacing the calculator."""
    if not _prototype_local_request():
        return Response(status=404)
    root = Path(__file__).resolve().parent.parent / "prototypes" / "manrope-blackwhite"
    return send_from_directory(root, "index.html")


@app.route("/prototype/manrope-blackwhite/<path:asset_path>")
def manrope_prototype_asset(asset_path: str):
    """Serve prototype assets only to a loopback browser session."""
    if not _prototype_local_request():
        return Response(status=404)
    root = Path(__file__).resolve().parent.parent / "prototypes" / "manrope-blackwhite"
    return send_from_directory(root, asset_path)


@app.route("/healthz")
def health():
    """Cheap liveness probe that avoids loading calculator data."""
    return jsonify({"status": "ok"})


def _public_ability_entry(ability_list: object, slot: str) -> dict[str, object]:
    """Return bounded descriptive metadata without exposing raw formula graphs."""
    entries = ability_list if isinstance(ability_list, list) else []
    first = entries[0] if entries and isinstance(entries[0], dict) else {}
    descriptions = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for effect in entry.get("effects", []):
            description = str(effect.get("description", "")).strip()
            if description and description not in descriptions:
                descriptions.append(description)
    return {
        "slot": slot,
        "name": first.get("name", slot),
        "icon": _https_icon(first.get("icon", "")),
        "blurb": first.get("blurb") or "",
        "description": " ".join(descriptions),
        "damage_type": first.get("damageType"),
        "targeting": first.get("targeting"),
        "ingested": bool(first),
    }


@app.route("/api/champions")
def api_champions():
    """Return champion identity and fail-closed attacker readiness.

    ``verified`` and ``engine_registered`` are backed by the complete
    dedicated-module registry. Source receipts and packet assumptions remain
    available through the config metadata.
    """
    champions = fetch_champion_data()
    result = []
    for champ_data in champions.values():
        availability = attacker_availability(champ_data, _VERIFIED_CHAMPIONS)
        ability_slots = {}
        for slot in ("P", "Q", "W", "E", "R"):
            ability = _public_ability_entry(
                champ_data.get("abilities", {}).get(slot, []), slot
            )
            ability_slots[slot] = {
                key: ability[key] for key in ("slot", "name", "icon", "ingested")
            }
        result.append(
            {
                "name": champ_data["name"],
                "icon": _https_icon(champ_data.get("icon", "")),
                "verified": availability["ready"],
                "engine_registered": champ_data["name"] in _ENGINE_CHAMPIONS,
                "engine_registration": engine_registration_kind(champ_data["name"]),
                "engine_backend_enabled": (champ_data["name"] in _ENGINE_CHAMPIONS),
                "availability": availability,
                "patch_last_changed": champ_data.get("patchLastChanged"),
                "abilities": ability_slots,
                "ability_ingestion": {
                    "complete": all(
                        entry["ingested"] for entry in ability_slots.values()
                    ),
                    "slot_count": sum(
                        entry["ingested"] for entry in ability_slots.values()
                    ),
                    "source": "Local Wiki cache",
                },
            }
        )
    result = sorted(
        result,
        key=lambda c: (not c["verified"], c["name"]),
    )
    return jsonify(result)


def _item_picker_stat_fields(item: Mapping[str, Any]) -> dict[str, Any]:
    """Expose the cached sustain/stat families the browser can display."""
    stats = get_item_stats(item)
    return {
        "lifesteal": stats["lifesteal_percent"],
        "omnivamp": stats["omnivamp_percent"],
        "healAndShieldPower": stats["heal_and_shield_power_percent"],
        "healthRegen": stats["health_regen_percent"],
        "tenacity": stats["tenacity_percent"],
        "manaRegen": stats["mana_regen_percent"],
        "goldPer10": stats["gold_per_10"],
        "critDamage": stats["critical_strike_damage_percent"],
        "statConversions": stat_conversion_metadata(str(item.get("name", ""))),
    }


@app.route("/api/items")
def api_items():
    """Return ordinary build items for manual attacker/roster loadouts."""
    result = sorted(
        [
            {
                "id": item["id"],
                "name": item["name"],
                "icon": _https_icon(item.get("icon", "")),
                "ap": item.get("ap", 0),
                "hp": item.get("hp", 0),
                "mana": item.get("mana", 0),
                "ad": item.get("ad", 0),
                "armor": item.get("armor", 0),
                "mr": item.get("mr", 0),
                "haste": item.get("haste", 0),
                "pen": item.get("pen", 0),
                "percentPen": item.get("percentPen", 0),
                "lethality": item.get("lethality", 0),
                "percentArmorPen": item.get("percentArmorPen", 0),
                "attackSpeed": item.get("attackSpeed", 0),
                "crit": item.get("crit", 0),
                **_item_picker_stat_fields(item),
                "price": item.get("price", 0),
                "into": item.get("into") or [],
                "categories": item.get("categories") or [],
                "support_quest_stage": support_quest_item_stage(item.get("name")),
                "model_coverage": item_model_coverage(item),
                "target_model_coverage": target_item_model_coverage(item),
            }
            for item in get_selectable_items()
        ],
        key=lambda i: i["name"],
    )
    return jsonify(result)


@app.route("/api/boots")
def api_boots():
    """Return tier-2 and quest-only tier-3 boots for the role-aware picker."""
    upgrade_pairs = boot_upgrade_contract()
    upgrade_from = {pair["upgraded"]: pair["base"] for pair in upgrade_pairs.values()}
    result = sorted(
        [
            {
                "id": item["id"],
                "name": item["name"],
                "icon": _https_icon(item.get("icon", "")),
                "ap": item.get("ap", 0),
                "hp": item.get("hp", 0),
                "mana": item.get("mana", 0),
                "ad": item.get("ad", 0),
                "armor": item.get("armor", 0),
                "mr": item.get("mr", 0),
                "haste": item.get("haste", 0),
                "pen": item.get("pen", 0),
                "percentPen": item.get("percentPen", 0),
                "lethality": item.get("lethality", 0),
                "percentArmorPen": item.get("percentArmorPen", 0),
                "attackSpeed": item.get("attackSpeed", 0),
                "crit": item.get("crit", 0),
                **_item_picker_stat_fields(item),
                "price": item.get("price", 0),
                "into": item.get("into") or [],
                "categories": item.get("categories") or [],
                "tier": item.get("tier"),
                "upgrade_from": upgrade_from.get(item.get("name")),
                "upgrade_to": next(
                    (
                        pair["upgraded"]
                        for pair in upgrade_pairs.values()
                        if pair["base"] == item.get("name")
                    ),
                    None,
                ),
                "model_coverage": item_model_coverage(item),
                "target_model_coverage": target_item_model_coverage(item),
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
                "auto_attack_uptime_mode": DEFAULT_AUTO_ATTACK_UPTIME_MODE,
                "one_rotation_duration_seconds": ONE_ROTATION_DURATION,
            },
            "input_limits": PUBLIC_INPUT_LIMITS,
            "champion_options": champion_options_meta_map(),
            "item_options": item_input_options_meta(),
            "role_quest": {
                "support_item": support_quest_item_contract(),
                "boot_upgrades": boot_upgrade_contract(),
            },
            "capabilities": public_capability_contract(
                input_limits=PUBLIC_INPUT_LIMITS,
                max_rotations=MAX_ROTATIONS,
                champion_option_count=len(champion_options_meta_map()),
                item_option_count=len(item_input_options_meta()),
            ),
            "champion_engine": {
                "registered_count": len(_ENGINE_CHAMPIONS),
                "reviewed_count": len(_VERIFIED_CHAMPIONS),
                "generic_enabled": _generic_engine_enabled(),
            },
            "keystones": keystone_catalog(),
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
    """Return descriptive metadata for all five ingested ability slots."""
    try:
        champion_data = get_champion(champion_name)
    except KeyError:
        return jsonify({"error": f"Champion '{champion_name}' not found"}), 404

    abilities = champion_data.get("abilities", {})
    result = {}
    for key in ("P", "Q", "W", "E", "R"):
        result[key] = _public_ability_entry(abilities.get(key, []), key)
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
        require_level_within_cap(
            level, fight_params.role, fight_params.role_quest_complete
        )
        include_crossover = data.get("include_crossover", False)
        if not isinstance(include_crossover, bool):
            raise ValueError("include_crossover must be true or false")
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
        require_calculation_item_coverage(
            ([resolved_boots] if resolved_boots else []) + ordinary_items,
            participant="Attacker",
        )
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    items = ([resolved_boots] if resolved_boots else []) + ordinary_items

    try:
        enemies = [loadout.resolve() for loadout in enemy_requests]
        allies = [loadout.resolve() for loadout in ally_requests]
        require_roster_fight_window_support(
            fight_params, enemies=enemies, allies=allies
        )
        for enemy in enemies:
            participant = f"Enemy {enemy.champion_data['name']}"
            require_calculation_item_coverage(
                list(enemy.item_data), participant=participant
            )
            require_target_item_coverage(list(enemy.item_data))
        for ally in allies:
            participant = f"Ally {ally.champion_data['name']}"
            require_calculation_item_coverage(
                list(ally.item_data), participant=participant
            )
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "requested data"
        return jsonify({"error": f"Scenario data '{missing}' not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

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
        if include_crossover:
            _add_comparison_curve(
                response, champion_data, level, items, fight_params, enemies
            )
        response["role_quest"] = (
            role_quest_meta(fight_params.role, fight_params.role_quest_complete)
            if fight_params.role
            else None
        )
        response["engine"] = {
            "registration": engine_registration_kind(champion_data["name"]),
            "certified": champion_data["name"] in _VERIFIED_CHAMPIONS,
            "mode": "reviewed_event_order",
        }
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
        if isinstance(champion_data.get("stats"), Mapping):
            main_stats = calculate_total_stats(
                champion_data,
                level,
                items,
                item_options=fight_params.item_options,
                role=fight_params.role,
                role_quest_complete=fight_params.role_quest_complete,
                external_stat_bonuses=fight_params.ally_stat_bonuses,
            )
            response["combat"] = build_participant_timeline(
                champion_data,
                level,
                items,
                fight_params,
                main_stats=main_stats,
                main_defenses=resolve_starting_defenses(
                    champion_data["name"], level, main_stats, items
                ),
                enemies=[],
                allies=allies,
            )
        return jsonify(response)

    target_results = []
    for target_index, enemy in enumerate(enemies):
        target_params = replace(
            fight_params,
            roster_target_index=target_index,
            roster_target_count=len(enemies),
            target_health=enemy.stats["health"],
            target_bonus_health=enemy.stats["bonus_health"],
            target_armor=enemy.stats["armor"],
            target_magic_resistance=enemy.stats["magic_resistance"],
            target_magic_shield=enemy.defenses.magic_shield,
            target_physical_shield=enemy.defenses.physical_shield,
            target_general_shield=enemy.defenses.general_shield,
            target_basic_damage_multiplier=enemy.defenses.basic_damage_multiplier,
            target_basic_damage_flat_reduction=(
                enemy.defenses.basic_damage_flat_reduction
            ),
            target_basic_damage_flat_reduction_cap=(
                enemy.defenses.basic_damage_flat_reduction_cap
            ),
            target_critical_strike_damage_multiplier=(
                enemy.defenses.critical_strike_damage_multiplier
            ),
            target_threshold_shield_amount=enemy.defenses.threshold_shield_amount,
            target_threshold_shield_health_ratio=(
                enemy.defenses.threshold_shield_health_ratio
            ),
            target_threshold_shield_duration=(enemy.defenses.threshold_shield_duration),
            target_threshold_shield_damage_type=(
                enemy.defenses.threshold_shield_damage_type
            ),
            target_threshold_health_bonus=enemy.defenses.threshold_health_bonus,
            target_threshold_health_heal=enemy.defenses.threshold_health_heal,
            target_threshold_health_ratio=enemy.defenses.threshold_health_ratio,
            target_threshold_health_duration=(enemy.defenses.threshold_health_duration),
        )
        result = run_fight(champion_data, level, items, target_params)
        if not fight_params.one_rotation:
            # Lifeline defenses are priced from the ordered ledger; a timed
            # fight whose event order is not certified is withheld here, after
            # computation, so the error can name the coarse sources.
            try:
                require_certified_target_timeline(
                    list(enemy.item_data), result.get("timeline_coverage", {})
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        target_results.append(
            {
                "target": _public_loadout_summary(enemy),
                "result": _serialize_fight_result(result),
            }
        )

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
    response["engine"] = {
        "registration": engine_registration_kind(champion_data["name"]),
        "certified": champion_data["name"] in _VERIFIED_CHAMPIONS,
        "mode": "reviewed_event_order",
    }
    # The legacy aggregate is retained for compatibility.  ``combat`` is the
    # coupled event-ordered receipt used by the UI/BIS objective: every
    # selected ally and enemy is an active participant with survival/eHP and
    # attributed output.
    if isinstance(champion_data.get("stats"), Mapping):
        main_stats = calculate_total_stats(
            champion_data,
            level,
            items,
            item_options=fight_params.item_options,
            role=fight_params.role,
            role_quest_complete=fight_params.role_quest_complete,
            external_stat_bonuses=fight_params.ally_stat_bonuses,
        )
        main_defenses = resolve_starting_defenses(
            champion_data["name"], level, main_stats, items
        )
        response["combat"] = build_participant_timeline(
            champion_data,
            level,
            items,
            fight_params,
            main_stats=main_stats,
            main_defenses=main_defenses,
            enemies=enemies,
            allies=allies,
        )
    if include_crossover:
        _add_comparison_curve(
            response, champion_data, level, items, fight_params, enemies
        )
    return jsonify(response)


def _bis_main_request(data: Mapping[str, object]) -> ChampionLoadout:
    """Parse the actual main champion used by focused BIS requests."""
    return ChampionLoadout.from_request(
        {
            "champion": data.get("champion", ""),
            "level": data.get("level", 1),
            "items": data.get("items", []),
            "boots": data.get("boots", ""),
            "item_options": data.get("item_options"),
            "role": data.get("role", ""),
            "role_quest_complete": data.get("role_quest_complete", False),
            "ally_effects_enabled": data.get("ally_effects_enabled", True),
            # Focused BIS must use the same authored rank allocation as the
            # ordinary calculate/optimize paths.  Omitting this field makes
            # ChampionLoadout silently fall back to level-derived ranks.
            "ability_ranks": data.get("ability_ranks"),
            "champion_options": data.get("champion_options"),
            "cast_order": data.get("cast_order"),
        },
        field="attacker",
    )


def _bis_replaced_loadout(
    loadout: ChampionLoadout,
    *,
    slot_index: int,
    slot_kind: str,
    candidate_name: str,
) -> ChampionLoadout:
    """Replace one ordinary or boots slot while preserving sourced options."""
    if slot_kind == "boots":
        return replace(loadout, boots=candidate_name)
    items = list(loadout.items)
    if slot_index < 0 or slot_index > MAX_LOADOUT_ITEMS - 1:
        raise ValueError("slot_index must be between 0 and 5")
    if slot_index >= len(items):
        # Empty browser slots are not serialized as placeholder items; the
        # next completed candidate therefore occupies the next legal slot.
        items.append(candidate_name)
    else:
        items[slot_index] = candidate_name
    # The browser represents empty slots as absent request entries.  A
    # candidate is therefore the only item introduced for a previously empty
    # slot; duplicate validation remains owned by ChampionLoadout.resolve.
    return replace(loadout, items=tuple(items))


def _role_scoped_bis_candidates(
    candidates: list[dict],
    *,
    role: str,
) -> list[dict]:
    """Keep roster BIS candidates within the selected role's sourced shop scope.

    The item cache carries Riot's shop tags for each completed item.  A roster
    role is an explicit scenario input, so using those tags here prevents a
    support-only item from being recommended to a top/mid enemy and prevents a
    support ally's BIS from collapsing into raw-health tank items.  This is a
    candidate-legality boundary, not a champion archetype or damage heuristic;
    the surviving candidates are still scored by the coupled event timeline.
    """
    return role_scoped_shop_items(candidates, role)


def _bis_candidate_pool(
    slot_kind: str,
    *,
    boots_tier: int,
    role: str = "",
) -> list[dict]:
    legal = (
        get_eligible_boots(tier=boots_tier)
        if slot_kind == "boots"
        else get_eligible_legendaries()
    )
    supported = optimizer_supported_items(legal)
    scoped = (
        supported
        if slot_kind == "boots"
        else _role_scoped_bis_candidates(supported, role=role)
    )
    return sorted(scoped, key=lambda item: item.get("name", ""))


def _roster_target_coverage(loadouts: list[ChampionLoadout]) -> list[dict[str, object]]:
    """Return unsupported target mechanics for the coupled roster.

    Roster BIS candidates are later used as passive targets by the main
    champion's event timeline. Do not apply a candidate whose target-side
    item effect is outside the sourced target model; that would either fail
    the next main optimization late or silently ignore the mechanic.
    """
    blocked: list[dict[str, object]] = []
    for loadout in loadouts:
        coverage = target_build_coverage(list(loadout.item_data))
        for entry in coverage.get("blocked", []):
            blocked.append(
                {
                    "champion": loadout.champion_data.get(
                        "name", loadout.request.champion
                    ),
                    "name": entry.get("name", ""),
                    "reason": entry.get("reason", ""),
                }
            )
    return blocked


def _enemy_bis_rank_key(
    objective: Mapping[str, object],
    survival: Mapping[str, object],
    *,
    duration: float,
) -> tuple[float, ...]:
    """Order enemy candidates by a survival-gated, event-derived objective.

    A roster enemy must remain a live participant before its outgoing damage
    can be useful, but surviving builds should not all collapse to a health
    race.  The first components are a hard event gate (alive through the
    requested window) and survival time, followed by damage dealt before
    defeat (the timeline's TTD-truncated threat).  Effective health and
    recovery actually applied by the timeline are deterministic tie-breakers.
    This is deliberately champion/event based: it does not infer a role or
    assign a damage/tank archetype from the champion name.
    """
    death_time = survival.get("death_time")
    survival_time = float(duration if death_time is None else death_time)
    threat = float(objective.get("focus_damage_before_death", 0.0))
    effective_health = float(survival.get("effective_health", 0.0))
    healing = float(survival.get("healing_received", 0.0))
    support_shield = float(survival.get("support_shield_received", 0.0))
    shield_absorbed = float(survival.get("shield_absorbed", 0.0))
    # Survival is a gate, not an archetype prior.  Survival time still
    # separates candidates that both die before the window; once candidates
    # live equally long, modeled threat is the first discriminator.  Remaining
    # event-derived durability/recovery fields only break ties.
    survived_window = 1.0 if death_time is None else 0.0
    return (
        survived_window,
        survival_time,
        threat,
        effective_health,
        healing,
        support_shield,
        shield_absorbed,
    )


# Best-in-slot is an objective selector, not a second stat-only optimizer.
# Keep the definitions in one place so the API receipt and the browser filter
# cannot silently disagree about direction or units.
_BIS_OBJECTIVES: dict[str, dict[str, str]] = {
    "overall": {
        "label": "Overall",
        "direction": "higher",
        "metric": "event-ordered team-fight value",
    },
    "kill": {
        "label": "Kill pressure",
        "direction": "lower",
        "metric": "time to first target defeat",
    },
    "survival": {
        "label": "Survival",
        "direction": "higher",
        "metric": "effective health (event-applied)",
    },
    "damage": {
        "label": "Damage",
        "direction": "higher",
        "metric": "damage before focus defeat",
    },
    "utility": {
        "label": "Utility",
        "direction": "higher",
        "metric": "healing, shields, and support value",
    },
}

_BIS_CERTIFIED_DEFENSIVE_EFFECTS: dict[str, str] = {
    "Eclipse": (
        "Ever Rising Moon's two-hit trigger creates a timestamped self shield "
        "with its sourced melee/ranged amount and two-second expiry."
    ),
    "Death's Dance": (
        "Ignore Pain splits post-mitigation physical/magic damage into sourced "
        "true-damage ticks; Defy clears the remaining store and heals on a "
        "qualifying takedown."
    ),
    "Sundered Sky": (
        "Lightshield Strike's first-hit heal is timestamped and included in "
        "the participant survival/eHP ledger; any sourced temporary-health "
        "overheal is applied through the same ordered heal event."
    ),
}

# Retained as an explicit API field for clients that display the audit
# contract.  A non-empty entry means the candidate is withheld; CP6 now
# certifies Eclipse and Death's Dance through the ordered event walk.
_BIS_UNMODELED_DEFENSIVE_EFFECTS: dict[str, str] = {}


def _bis_defensive_effect_receipt(
    item_name: str, survival: Mapping[str, object]
) -> dict[str, object]:
    """Describe why a defensive item did or did not affect candidate eHP."""
    certified_note = _BIS_CERTIFIED_DEFENSIVE_EFFECTS.get(item_name)
    if certified_note is None:
        return {"status": "no_special_defensive_effect", "sources": []}
    return {
        "status": "certified",
        "sources": [item_name],
        "note": certified_note,
        "evidence": {
            "healing_received": round(
                float(survival.get("healing_received", 0.0) or 0.0), 1
            ),
            "temporary_health_received": round(
                float(survival.get("temporary_health_received", 0.0) or 0.0), 1
            ),
            "effective_health": round(
                float(survival.get("effective_health", 0.0) or 0.0), 1
            ),
        },
    }


def _bis_objective_meta(key: str) -> dict[str, str]:
    """Return a defensive copy of the API's objective contract."""
    meta = _BIS_OBJECTIVES.get(key)
    if meta is None:
        raise ValueError(
            "objective must be one of: overall, kill, survival, damage, utility"
        )
    return {"key": key, **meta}


def _bis_time_to_target_defeat(
    combat: Mapping[str, object],
    *,
    subject_team: str,
    focus_id: str,
    duration: float,
) -> float:
    """Return an explicit event-derived kill-time objective in seconds.

    For a main/ally item, kill pressure means the first enemy defeat.  For an
    enemy item, it means how quickly the selected enemy is defeated.  An
    undefeated participant is assigned the requested window, never zero or a
    guessed extrapolation.
    """
    participants = combat.get("participants", [])
    if not isinstance(participants, list):
        participants = []
    if subject_team == "enemy":
        participant_ids = {focus_id}
    else:
        participant_ids = {
            str(row.get("participant_id", ""))
            for row in participants
            if isinstance(row, Mapping) and row.get("team") == "enemy"
        }
    times: list[float] = []
    for row in participants:
        if (
            not isinstance(row, Mapping)
            or str(row.get("participant_id", "")) not in participant_ids
        ):
            continue
        survival = row.get("survival", {})
        if not isinstance(survival, Mapping):
            continue
        death_time = survival.get("death_time")
        if death_time is None:
            continue
        try:
            parsed = float(death_time)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            times.append(max(0.0, min(duration, parsed)))
    return min(times, default=duration)


def _bis_objective_score(
    objective_key: str,
    *,
    subject_team: str,
    focus_id: str,
    combat: Mapping[str, object],
    objective: Mapping[str, object],
    focus: Mapping[str, object],
) -> tuple[float, str, dict[str, float], tuple[float, ...] | None]:
    """Derive one candidate's selected objective from the shared timeline."""
    focus_survival = focus.get("survival", {})
    if not isinstance(focus_survival, Mapping):
        focus_survival = {}
    duration = float(combat.get("duration", 0.0) or 0.0)
    if duration <= 0.0:
        duration = DEFAULT_FIGHT_DURATION
    focus_damage = float(objective.get("focus_damage_before_death", 0.0) or 0.0)
    effective_health = float(focus_survival.get("effective_health", 0.0) or 0.0)
    healing = float(focus_survival.get("healing_received", 0.0) or 0.0)
    support_shield = float(focus_survival.get("support_shield_received", 0.0) or 0.0)
    support_value = float(objective.get("focus_support_value", 0.0) or 0.0)
    if objective_key == "overall":
        if subject_team == "main":
            score = focus_damage
            metric = "main TTD (survival-coupled)"
            components = {
                "damage_before_death": focus_damage,
                "effective_health": effective_health,
                "healing": healing,
                "support_shield_received": support_shield,
            }
            return score, metric, components, None
        if subject_team == "ally":
            team_damage = float(
                objective.get("main_team_damage_before_death", 0.0) or 0.0
            )
            score = team_damage + support_value + effective_health
            metric = "team damage + ally utility + effective health"
            components = {
                "main_team_damage_before_death": team_damage,
                "outgoing_support": support_value,
                "healing": float(objective.get("focus_healing", 0.0) or 0.0),
                "effective_health": effective_health,
            }
            return score, metric, components, None
        survival_time = _bis_time_to_target_defeat(
            combat,
            subject_team=subject_team,
            focus_id=focus_id,
            duration=duration,
        )
        rank_key = _enemy_bis_rank_key(objective, focus_survival, duration=duration)
        score = focus_damage
        metric = "enemy survival gate · threat before defeat"
        components = {
            "survival_time": survival_time,
            "effective_health": effective_health,
            "threat_before_defeat": focus_damage,
            "healing": healing,
            "shield_absorbed": float(focus_survival.get("shield_absorbed", 0.0) or 0.0),
        }
        return score, metric, components, rank_key

    if objective_key == "kill":
        score = _bis_time_to_target_defeat(
            combat,
            subject_team=subject_team,
            focus_id=focus_id,
            duration=duration,
        )
        metric = _BIS_OBJECTIVES[objective_key]["metric"]
        components = {
            "time_to_target_defeat": score,
            "damage_before_death": focus_damage,
        }
        return score, metric, components, None
    if objective_key == "survival":
        score = effective_health
        metric = _BIS_OBJECTIVES[objective_key]["metric"]
        components = {
            "effective_health": effective_health,
            "healing": healing,
            "support_shield_received": support_shield,
        }
        return score, metric, components, None
    if objective_key == "damage":
        if subject_team == "ally":
            score = float(objective.get("main_team_damage_before_death", 0.0) or 0.0)
        else:
            score = focus_damage
        metric = _BIS_OBJECTIVES[objective_key]["metric"]
        components = {
            "damage_before_death": score,
            "effective_health": effective_health,
        }
        return score, metric, components, None
    # Utility is intentionally an additive receipt of values that the event
    # walk actually applied.  It does not infer movement, range, or a value
    # for an unmodelled item tooltip.
    score = support_value + healing + support_shield
    metric = _BIS_OBJECTIVES[objective_key]["metric"]
    components = {
        "support_value": support_value,
        "healing": healing,
        "support_shield_received": support_shield,
    }
    return score, metric, components, None


@app.route("/api/bis", methods=["POST"])
def api_bis():
    """Rank one slot from the same coupled participant event model.

    This endpoint exists so the browser's Best-in-Slot modal cannot use its
    historical stat/archetype estimator.  ``subject_team`` identifies whose
    build is being changed; all other selected champions remain active in the
    timeline and the response exposes the metric components and coverage.
    """
    try:
        data = _json_object()
        subject_team = _request_string(data, "subject_team", "main")
        if subject_team not in {"main", "ally", "enemy"}:
            raise ValueError("subject_team must be main, ally, or enemy")
        slot_index = _request_int(data, "slot_index", 0, 0, MAX_LOADOUT_ITEMS - 1)
        slot_kind = _request_string(data, "slot_kind", "item")
        if slot_kind not in {"item", "boots"}:
            raise ValueError("slot_kind must be item or boots")
        subject_index = _request_int(data, "subject_index", 0, 0, 4)
        objective_key = _request_string(data, "objective", "overall")
        objective_meta = _bis_objective_meta(objective_key)
        fight_params = FightParams.from_request(data, deterministic=True)
        main_request = _bis_main_request(data)
        enemy_requests = parse_roster(data, "enemies", maximum=MAX_ENEMIES)
        ally_requests = parse_roster(data, "allies", maximum=MAX_ALLIES)
        if subject_team == "ally" and subject_index >= len(ally_requests):
            raise ValueError("subject_index is outside the selected ally roster")
        if subject_team == "enemy" and subject_index >= len(enemy_requests):
            raise ValueError("subject_index is outside the selected enemy roster")
        if subject_team != "main" and slot_kind == "boots":
            # Roster cards use the same tier contract as their role; ordinary
            # roster roles default to tier-2 boots unless explicitly mid quest.
            pass
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        main_loadout = main_request.resolve()
        # Validate the focused main request against the same champion-specific
        # rank and option contracts as /api/calculate and /api/optimize.  The
        # FightParams parser checks JSON shape/ranges; this second gate checks
        # level legality and module-declared option keys before any candidate
        # evaluation starts.
        fight_params.validate_for_champion(
            main_loadout.champion_data["name"], main_request.level
        )
        _validate_champion_options(main_loadout.champion_data["name"], data)
        enemies = [loadout.resolve() for loadout in enemy_requests]
        allies = [loadout.resolve() for loadout in ally_requests]
        require_roster_fight_window_support(
            fight_params, enemies=enemies, allies=allies
        )
        subject_base = (
            main_request
            if subject_team == "main"
            else (
                ally_requests[subject_index]
                if subject_team == "ally"
                else enemy_requests[subject_index]
            )
        )
        if subject_team != "main" and not subject_base.role:
            raise ValueError(
                f"{subject_team} role is required before roster BIS can be scored"
            )
        subject_id = (
            "main"
            if subject_team == "main"
            else f"{subject_team}:{subject_base.champion}"
        )
        boots_tier = 2
        role = subject_base.role
        if role == "mid" and subject_base.role_quest_complete:
            boots_tier = 3
        candidates = _bis_candidate_pool(slot_kind, boots_tier=boots_tier, role=role)
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "requested data"
        return jsonify({"error": f"Scenario data '{missing}' not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    rate_limit_response = _spend_rate_limit("calculate")
    if rate_limit_response is not None:
        return rate_limit_response

    ranked: list[dict] = []
    withheld_candidates: list[dict[str, object]] = []
    target_coverage_filtered: list[dict[str, object]] = []
    for candidate in candidates:
        try:
            candidate_request = _bis_replaced_loadout(
                subject_base,
                slot_index=slot_index,
                slot_kind=slot_kind,
                candidate_name=candidate["name"],
            )
            resolved_subject = candidate_request.resolve()
            if (
                subject_team != "enemy"
                and candidate["name"] in _BIS_UNMODELED_DEFENSIVE_EFFECTS
            ):
                reason = _BIS_UNMODELED_DEFENSIVE_EFFECTS[candidate["name"]]
                withheld_candidates.append(
                    {
                        "name": candidate["name"],
                        "icon": _https_icon(candidate.get("icon", "")),
                        "reason": "objective_effect_unavailable",
                        "objective": objective_meta,
                        "detail": reason,
                        "timeline_coverage": {
                            "complete": False,
                            "certification": "objective_effect_unavailable",
                            "exact_sources": [],
                            "coarse_sources": [candidate["name"]],
                            "note": reason,
                        },
                    }
                )
                continue
            candidate_main = (
                resolved_subject if subject_team == "main" else main_loadout
            )
            candidate_enemies = list(enemies)
            candidate_allies = list(allies)
            if subject_team == "enemy":
                candidate_enemies[subject_index] = resolved_subject
            elif subject_team == "ally":
                candidate_allies[subject_index] = resolved_subject
            blocked_targets = _roster_target_coverage(
                [*candidate_enemies, *candidate_allies]
            )
            if blocked_targets:
                target_coverage_filtered.extend(blocked_targets)
                withheld_candidates.append(
                    {
                        "name": candidate["name"],
                        "icon": _https_icon(candidate.get("icon", "")),
                        "reason": "target_coverage_blocked",
                        "target_coverage": blocked_targets,
                        "timeline_coverage": {
                            "complete": False,
                            "certification": "target_coverage_blocked",
                            "exact_sources": [],
                            "coarse_sources": [],
                            "note": (
                                "Candidate was not evaluated because a selected "
                                "roster item is outside the sourced target model."
                            ),
                        },
                    }
                )
                continue
            combat = build_participant_timeline(
                candidate_main.champion_data,
                candidate_main.request.level,
                list(candidate_main.item_data),
                fight_params,
                main_stats=candidate_main.stats,
                main_defenses=candidate_main.defenses,
                enemies=candidate_enemies,
                allies=candidate_allies,
                focus_participant_id=("main" if subject_team == "main" else subject_id),
            )
            candidate_coverage = combat.get("timeline_coverage", {})
            timing_exclusions = applicability_exclusion_sources(candidate_coverage)
            if timing_exclusions:
                names = ", ".join(timing_exclusions)
                withheld_candidates.append(
                    {
                        "name": candidate["name"],
                        "icon": _https_icon(candidate.get("icon", "")),
                        "reason": "candidate_excluded_unresolved_timing",
                        "exclusion_type": "applicability",
                        "excluded_sources": timing_exclusions,
                        "detail": (
                            "Candidate was excluded before BIS ranking because "
                            f"{names} has no sourced hit boundary for this "
                            "rotation."
                        ),
                        "timeline_coverage": candidate_coverage,
                    }
                )
                continue
            objective = combat["objective"]
            focus = next(
                row
                for row in combat["participants"]
                if row["participant_id"]
                == ("main" if subject_team == "main" else subject_id)
            )
            focus_id = "main" if subject_team == "main" else subject_id
            score, metric, components, rank_key = _bis_objective_score(
                objective_key,
                subject_team=subject_team,
                focus_id=focus_id,
                combat=combat,
                objective=objective,
                focus=focus,
            )
            ranked.append(
                {
                    "name": candidate["name"],
                    "icon": _https_icon(candidate.get("icon", "")),
                    "score": round(score, 1),
                    "objective_value": round(score, 3),
                    "metric": metric,
                    "components": components,
                    "stats": candidate.get("stats", {}),
                    "survival": focus["survival"],
                    "defensive_effect_receipt": _bis_defensive_effect_receipt(
                        candidate["name"], focus["survival"]
                    ),
                    "timeline_coverage": combat["timeline_coverage"],
                    "_sort_score": score,
                    **({"_rank_key": rank_key} if rank_key is not None else {}),
                }
            )
        except (KeyError, ValueError) as exc:
            # A candidate without a complete legal sourced loadout is withheld,
            # never assigned a zero or a heuristic replacement score.  Keep a
            # receipt for it: dropping the row used to make candidate_count look
            # exhaustive even when a duplicate, state interaction, or missing
            # source prevented evaluation.
            withheld_candidates.append(
                {
                    "name": candidate["name"],
                    "icon": _https_icon(candidate.get("icon", "")),
                    "reason": "candidate_loadout_unavailable",
                    "detail": str(exc),
                    "timeline_coverage": {
                        "complete": False,
                        "certification": "candidate_not_evaluated",
                        "exact_sources": [],
                        "coarse_sources": [],
                        "note": "Candidate was withheld before timeline evaluation.",
                    },
                }
            )
            continue

    if objective_key == "overall" and subject_team == "enemy":
        ranked.sort(key=lambda row: row["_rank_key"], reverse=True)
    else:
        ranked.sort(
            key=lambda row: row["_sort_score"],
            reverse=objective_meta["direction"] == "higher",
        )
    for row in ranked:
        row.pop("_rank_key", None)
        row.pop("_sort_score", None)
    # A row with coarse or missing event order is useful as an audit receipt,
    # but it is not a defensible BIS recommendation.  Keep those rows separate
    # so the browser cannot silently apply an uncertified build.
    partial_ranked = [
        candidate
        for candidate in ranked
        if not candidate["timeline_coverage"].get("complete", False)
    ]
    certified_ranked = [
        candidate
        for candidate in ranked
        if candidate["timeline_coverage"].get("complete", False)
    ]
    target_coverage_note = ""
    if target_coverage_filtered:
        first = target_coverage_filtered[0]
        target_coverage_note = (
            f"Target-side coverage filtered {len(target_coverage_filtered)} candidate "
            f"receipts; {first['champion']} · {first['name']}: {first['reason']}"
        )
    candidate_count = len(candidates)
    timing_excluded = [
        row
        for row in withheld_candidates
        if row.get("reason") == "candidate_excluded_unresolved_timing"
    ]
    blocking_withheld = [
        row
        for row in withheld_candidates
        if row.get("reason") != "candidate_excluded_unresolved_timing"
    ]
    coverage_complete = (
        bool(certified_ranked) and not partial_ranked and not blocking_withheld
    )
    return jsonify(
        {
            "objective": objective_meta,
            "defensive_effects": {
                "certified": _BIS_CERTIFIED_DEFENSIVE_EFFECTS,
                "withheld": _BIS_UNMODELED_DEFENSIVE_EFFECTS,
            },
            "subject_team": subject_team,
            "subject_index": subject_index,
            "slot_index": slot_index,
            "slot_kind": slot_kind,
            "candidate_scope": (
                f"role-tagged:{role}"
                if role and slot_kind != "boots"
                else "all-supported"
            ),
            # Return every evaluated receipt, not a top-12 preview.  The
            # backend acceptance contract requires per-candidate coverage so
            # omitted coarse builds cannot be mistaken for a complete BIS
            # search.  The client may still choose how many rows to render.
            "candidates": certified_ranked,
            "partial_candidates": partial_ranked,
            "candidate_count": candidate_count,
            "certified_candidate_count": len(certified_ranked),
            "partial_candidate_count": len(partial_ranked),
            "withheld_candidate_count": len(withheld_candidates),
            "withheld_candidates": withheld_candidates,
            "coverage": {
                "complete": coverage_complete,
                "certification": (
                    "bis_event_order_certified_with_exclusions"
                    if coverage_complete and timing_excluded
                    else (
                        "bis_event_order_certified"
                        if coverage_complete
                        else (
                            "bis_certified_subset_not_exhaustive"
                            if certified_ranked
                            else "bis_no_certified_candidates"
                        )
                    )
                ),
                "note": (
                    "Every candidate has complete sourced event order."
                    if coverage_complete
                    else (
                        (
                            "Certified candidates are available, but exhaustive "
                            "BIS is withheld because one or more candidates were "
                            "not fully evaluated or still have partial event order."
                        )
                        if certified_ranked
                        else (
                            "No candidate has complete sourced event order; BIS "
                            "is withheld and only partial or pre-timeline receipts "
                            "are shown."
                        )
                    )
                )
                + (
                    f" {len(timing_excluded)} candidate timing receipt(s) were "
                    "excluded before ranking."
                    if timing_excluded
                    else ""
                )
                + (f" {target_coverage_note}" if target_coverage_note else ""),
            },
            "target_coverage_filtered": len(target_coverage_filtered),
            "target_coverage_note": target_coverage_note,
            "timing_excluded_candidate_count": len(timing_excluded),
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
        include_boots = data.get("include_boots", True)
        if not isinstance(include_boots, bool):
            raise ValueError("include_boots must be true or false")
        max_legendary_slots = _request_int(data, "max_legendary_slots", 5, 1, 6)
        gold_budget = (
            _request_int(data, "gold_budget", 0, 1, 30_000)
            if data.get("gold_budget") not in (None, "")
            else None
        )
        fight_params = FightParams.from_request(data, deterministic=True)
        require_level_within_cap(
            level, fight_params.role, fight_params.role_quest_complete
        )
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
        6
        if not include_boots
        else (
            6
            if fight_params.role == "bottom" and fight_params.role_quest_complete
            else 5
        )
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
        require_roster_fight_window_support(
            fight_params, enemies=enemies, allies=allies
        )
        for enemy in enemies:
            require_target_item_coverage(list(enemy.item_data))
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "requested data"
        return jsonify({"error": f"Scenario data '{missing}' not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

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
            roster_target_index=target_index,
            roster_target_count=len(enemies),
            target_health=enemy.stats["health"],
            target_bonus_health=enemy.stats["bonus_health"],
            target_armor=enemy.stats["armor"],
            target_magic_resistance=enemy.stats["magic_resistance"],
            target_magic_shield=enemy.defenses.magic_shield,
            target_physical_shield=enemy.defenses.physical_shield,
            target_general_shield=enemy.defenses.general_shield,
            target_basic_damage_multiplier=enemy.defenses.basic_damage_multiplier,
            target_basic_damage_flat_reduction=(
                enemy.defenses.basic_damage_flat_reduction
            ),
            target_basic_damage_flat_reduction_cap=(
                enemy.defenses.basic_damage_flat_reduction_cap
            ),
            target_critical_strike_damage_multiplier=(
                enemy.defenses.critical_strike_damage_multiplier
            ),
            target_threshold_shield_amount=enemy.defenses.threshold_shield_amount,
            target_threshold_shield_health_ratio=(
                enemy.defenses.threshold_shield_health_ratio
            ),
            target_threshold_shield_duration=(enemy.defenses.threshold_shield_duration),
            target_threshold_shield_damage_type=(
                enemy.defenses.threshold_shield_damage_type
            ),
            target_threshold_health_bonus=enemy.defenses.threshold_health_bonus,
            target_threshold_health_heal=enemy.defenses.threshold_health_heal,
            target_threshold_health_ratio=enemy.defenses.threshold_health_ratio,
            target_threshold_health_duration=(enemy.defenses.threshold_health_duration),
        )
        for target_index, enemy in enumerate(enemies)
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
            require_complete_timeline=True,
            enemy_loadouts=enemies,
            ally_loadouts=allies,
            include_boots=include_boots,
        )
    except ValueError as exc:
        message = str(exc)
        payload = {"error": message}
        if message.startswith("No complete legal event-ordered build fits"):
            payload.update(
                {
                    "error_code": "no_complete_event_order",
                    "champion": champion_data["name"],
                }
            )
        return jsonify(payload), 400

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
        # Fresh item and rune JSON is now on disk — re-parse the in-memory
        # registries so effects reflect the newly fetched patch data.
        refresh_item_effects()
        refresh_rune_effects()

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=_dev_mode(), port=5000)
