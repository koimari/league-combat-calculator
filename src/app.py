"""Flask web application for the LoL Damage Calculator."""

import hmac
import base64
import binascii
import functools
import hashlib
import ipaddress
import json
import math
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Single import namespace (issue #164): the repository is imported as
# ``src.calculator`` everywhere (tests, scripts, gunicorn ``src.app:app``).
# Put the repository root on the path so ``src.calculator.*`` and the
# ``scripts.*`` scorecard import resolve; never insert ``src/`` itself,
# which would create a second ``calculator`` package tree in sys.modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import (
    Flask,
    Response,
    after_this_request,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from src.calculator.calculate import calculate_payload
from src.calculator.application_errors import ApplicationError

# The sys.path bootstrap above forces every first-party import below it;
# this one line carries the disable rather than the whole block, because
# widening it is another lane's file to change.
from src.calculator.trigger_stream import (  # pylint: disable=wrong-import-position
    StarvedSignal,
)
from src.calculator.certainty import (
    CERTAINTY_BOUNDARY as _CERTAINTY_BOUNDARY,
    classify_assumption as _classify_assumption,
    derive_certainty,
)
from src.calculator.data_fetcher import (
    fetch_champion_data,
    get_champion,
)
from src.calculator.item_effects import (
    item_input_options_meta,
    refresh_item_effects,
    stat_conversion_metadata,
)
from src.calculator.rune_effects import keystone_catalog, refresh_rune_effects
from src.calculator.item_coverage import (
    ATTACKER_LANES,
    item_model_coverage,
    target_item_model_coverage,
)
from src.calculator.loadout_rules import (
    exclusivity_groups,
    inventory_capacity,
    required_boots_tier,
    validate_resolved_loadout,
)
from src.calculator.champions import (
    champion_options_meta_map,
    engine_registration_kind,
    get_champion_module_meta,
    get_supported_fight_modes,
    get_unsupported_fight_mode_reason,
)
from src.calculator.champion_coverage import attacker_availability
from src.calculator.capabilities import public_capability_contract
from src.calculator.optimizer import (
    get_eligible_boots,
    get_selectable_items,
    optimize_build,
    optimize_purchase,
)
from src.calculator.stats import MAX_LEVEL
from src.calculator.stats import get_item_stats
from src.calculator.bis import bis_objective_contract, bis_payload
from src.calculator.public_response import (
    ICON_HOSTS as _ICON_HOSTS,
    https_icon as _https_icon,
    public_loadout_summary,
)
from src.calculator.scenario import (
    ENGINE_CHAMPIONS as _ENGINE_CHAMPIONS,
    VERIFIED_CHAMPIONS as _VERIFIED_CHAMPIONS,
    ChampionLoadout,
    load_public_champion as _load_public_champion,
    parse_scenario_request,
    resolve_named_item as _resolve_named_item,
    resolve_scenario,
)
from src.calculator.role_quests import (
    boot_upgrade_contract,
    role_quest_domain_contract,
    support_quest_item_contract,
    support_quest_item_stage,
)
from src.calculator.pipeline import (
    DEFAULT_AUTO_ATTACK_UPTIME,
    DEFAULT_AUTO_ATTACK_UPTIME_MODE,
    DEFAULT_FIGHT_DURATION,
    DEFAULT_FIGHT_MODE,
    DEFAULT_TARGET,
    ONE_ROTATION_DURATION,
    MAX_ROTATIONS,
    PUBLIC_INPUT_LIMITS,
    rank_allocation_contract,
)
from src.calculator.request_parsing import (
    request_int as _request_int,
    request_string as _request_string,
    request_string_list as _request_string_list,
)
from src.calculator.validation_receipts import (
    VALIDATION_SOURCES as _VALIDATION_SOURCES,
    evaluate_validation_receipt,
)
from src.rate_limit import TokenBucketStore
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from src.db import (
    CacheUnavailable,
    add_feedback,
    cache_backend,
    cache_delete_all,
    cache_get,
    cache_set,
    cache_stats,
    create_share_link,
    get_build,
    get_share_link,
    is_configured,
    is_postgres,
    list_feedback,
    record_metric_event,
    redis_configured,
    save_build,
    session,
    stable_cache_key,
    validation_summary,
)

app = Flask(
    __name__,
    template_folder=str(Path(__file__).resolve().parent.parent / "templates"),
    static_folder=str(Path(__file__).resolve().parent.parent / "static"),
)
app.json.sort_keys = False
app.config.update(
    MAX_CONTENT_LENGTH=32 * 1024,
    RATE_LIMIT_ENABLED=True,
    # The benchmark harness's seam into the optimizer (campaign runbook
    # R-24): ``{"work_counters": <sink>, "use_compiled_walk": <bool>}``.
    # ``scripts/bench_coupled_optimizer.py`` installs it before posting, so
    # the counters CI reads come out of the shipped request path instead of
    # a patched copy of it.  Empty in production, where it costs one dict
    # lookup per optimize request.
    OPTIMIZER_INSTRUMENTATION={},
)
# The test client hammers /api/calculate across the per-champion suites;
# the shared token bucket would 429 long runs. Rate limiting is a
# production-deployment concern, not a test-mode one.
if app.config.get("TESTING"):
    app.config["RATE_LIMIT_ENABLED"] = False

# --- Sentry error tracking ---------------------------------------------------
# The sentry-sdk package is imported lazily: without ``SENTRY_DSN`` this module
# never touches the dependency, so local installs and the test suite run
# without it. Initialisation happens once at import time; the captured module
# reference is what the error handlers consult. Rate-limit 429 rejections are
# expected traffic and are deliberately kept out of capture.
_sentry = None


def _configure_sentry() -> None:
    """Initialise Sentry from ``SENTRY_DSN``; a missing DSN is a no-op."""
    global _sentry
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        _sentry = None
        return
    try:
        # pylint: disable-next=import-outside-toplevel  # deliberate lazy import
        import sentry_sdk
    except ImportError:
        app.logger.warning(
            "SENTRY_DSN is set but the sentry-sdk package is not installed"
        )
        _sentry = None
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=0.0,  # error capture only on the closed-beta floor
        send_default_pii=False,
    )
    _sentry = sentry_sdk


def _capture_exception(error: BaseException) -> None:
    """Report an exception to Sentry when configured; otherwise no-op."""
    if _sentry is not None:
        _sentry.capture_exception(error)


_configure_sentry()

_AUTH_COOKIE = "scryglass_session"
_AUTH_TTL_SECONDS = 7 * 24 * 60 * 60

_RATE_LIMIT_POLICIES = {
    "calculate": (40, 20.0),
    # Worst max-valid optimizer request measured at 1.81 CPU seconds locally.
    # One token per 10 seconds caps sustained abuse near 20% of one core while
    # the independent calculate budget keeps the ordinary UI responsive.
    "optimize": (2, 0.1),
    # Anonymous funnel events are tiny and fire at most a few times per
    # session; a generous burst budget still bounds scripted spam to one
    # write every five seconds sustained.
    "metrics_event": (60, 0.2),
}
_SCOPE_LABELS = {
    "calculate": "Calculator",
    "optimize": "Optimizer",
    "metrics_event": "Metrics",
}
# One table for the per-operation cache/rate-limit policy (issue #138).
# ``rate_limit_scope`` names the token bucket; ``cache_namespace`` names the
# deterministic result cache.  BIS deliberately shares the calculator budget
# (it is invoked from the same UI surface), and optimize is cached like the
# other two because it is deterministic and the most expensive endpoint.
_OPERATION_POLICY = {
    "calculate": {"rate_limit_scope": "calculate", "cache_namespace": "calculate"},
    "bis": {"rate_limit_scope": "calculate", "cache_namespace": "bis"},
    "optimize": {"rate_limit_scope": "optimize", "cache_namespace": "optimize"},
}


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


# Anonymous beta-metrics session (P1b). The id is a random cookie value that
# never encodes account material, so activation/retention are measurable
# without a user table and without PII (see docs/beta-metrics.md).
_ANON_SESSION_COOKIE = "scryglass_anon"
_ANON_SESSION_MAX_AGE = 90 * 24 * 60 * 60


def _anon_session_id() -> str:
    """Return the anonymous session id, minting and persisting it when absent.

    The cookie is first-party, HttpOnly and scoped to the whole site; it
    carries no username, email, or invite code.  ``after_this_request``
    persists a freshly minted id on the current response.
    """
    existing = request.cookies.get(_ANON_SESSION_COOKIE, "")
    if existing and len(existing) <= 100 and re.fullmatch(r"[A-Za-z0-9_-]+", existing):
        return existing

    session_id = secrets.token_urlsafe(24)

    @after_this_request
    def _persist_anon_cookie(response):  # pylint: disable=unused-variable
        response.set_cookie(
            _ANON_SESSION_COOKIE,
            session_id,
            max_age=_ANON_SESSION_MAX_AGE,
            httponly=True,
            secure=request.is_secure or os.environ.get("VERCEL") == "1",
            samesite="Lax",
            path="/",
        )
        return response

    return session_id


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


def _invite_codes() -> tuple[str, ...]:
    """Return the configured invite codes (comma-separated env), deduplicated.

    Codes are matched exactly (after trimming surrounding whitespace), so
    ``BETA-2026`` and ``beta-2026`` are distinct.  An unset or empty
    ``SCRYGLASS_INVITE_CODES`` keeps the deployment in password-only mode.
    """
    raw = os.environ.get("SCRYGLASS_INVITE_CODES", "")
    return tuple(dict.fromkeys(code.strip() for code in raw.split(",") if code.strip()))


def _invite_mode() -> bool:
    """Invite gating is active only when the auth gate is on AND codes exist."""
    return _auth_enabled() and bool(_invite_codes())


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
    """Render the invite-gated closed-beta landing page.

    Served pre-auth, so it deliberately carries no dependency on protected
    assets: the template embeds its own CSS and the form posts back to
    ``/auth/login``.  The invite-code field appears only when
    ``SCRYGLASS_INVITE_CODES`` is configured on top of the auth gate.
    """
    return (
        render_template(
            "beta_landing.html",
            message=message,
            next_path=next_path,
            invite_required=_invite_mode(),
        ),
        status,
    )


@app.before_request
def _enforce_authentication():
    """Gate the UI, assets, and APIs when the deployment enables auth.

    The pre-auth surface stays reachable without a session: the health
    probe, the auth endpoints (login/logout/status), the invite-code
    validation API, and the public legal pages (privacy, terms, Riot
    disclaimer).
    """
    if not _auth_enabled():
        return None
    if (
        request.path == "/healthz"
        or request.path.startswith("/api/health/")
        or request.path == "/privacy"
        or request.path == "/terms"
        or request.path == "/riot-disclaimer"
        or request.path == "/api/auth/invite"
        # Anonymous funnel events fire before/without any approved session;
        # the scorecard endpoint (GET /api/metrics) stays behind the gate.
        or request.path == "/api/metrics/event"
        or request.path.startswith("/auth/")
    ):
        return None
    if _current_session():
        return None
    next_path = request.full_path.rstrip("?") if request.full_path else "/"
    return redirect(url_for("auth_login", next=next_path))


def _result_cache_enabled() -> bool:
    """Result caching is an explicit-backend feature, bypassed in tests.

    /api/calculate and /api/bis consult the result cache only when the
    operator configured a database (``DATABASE_URL``) or Redis
    (``REDIS_URL``); the local SQLite fallback and the test suite keep
    computing fresh results so a misconfigured cache can never hide a bug.
    """
    return not app.config.get("TESTING") and (is_configured() or redis_configured())


def _spend_rate_limit(scope: str):
    """Protect expensive work globally across all Gunicorn workers."""
    if not app.config["RATE_LIMIT_ENABLED"] or app.config.get("TESTING"):
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

    label = _SCOPE_LABELS.get(scope, scope.replace("_", " ").title())
    response = jsonify({"error": f"{label} is busy; retry shortly"})
    response.status_code = 429
    response.headers["Retry-After"] = str(max(1, math.ceil(retry_after)))
    return response


@app.errorhandler(413)
def _request_too_large(_error):
    """Return the same JSON error shape as every other API rejection."""
    return jsonify({"error": "Request body exceeds 32 KiB"}), 413


@app.errorhandler(500)
def _internal_error(error):
    """Capture unhandled exceptions and keep the API's JSON error shape.

    Flask wraps non-HTTP exceptions in ``InternalServerError`` before the
    handler runs; Sentry should see the original exception, not the wrapper.
    """
    _capture_exception(getattr(error, "original_exception", error))
    return jsonify({"error": "Internal server error"}), 500


def _within_starvation_boundary(view):
    """Wrap one view in the campaign's single ``StarvedSignal`` catch.

    A ``StarvedSignal`` means a leaf has no value a rule computed and the
    only honest answer is to say so — either because a projection cannot
    answer the question a consumer asked, or because a write-once record
    holds two answers to one question and so can answer neither.  Both are
    programming errors rather than data conditions, both are raised where
    they are discovered, and both are handled in exactly one place: here,
    where they become a 500 carrying the ``STARVED`` receipt (D-25, as the
    umbrella's Amendment G reads its "exactly one catch" — one *place*, not
    one exception type).  Everywhere else they propagate: a named refusal
    that is quietly absorbed is the zero this campaign exists to kill, and
    an absorbed ``OutcomeRewritten`` in particular is the last-write-wins the
    write-once ledger was landed to replace.

    One wrapper over every registered view rather than one ``except`` per
    route, because "exactly one catch" is the rule and repeating it would be
    a second place the rule lives.
    """

    @functools.wraps(view)
    def _guarded(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except StarvedSignal as starved:
            _capture_exception(starved)
            return (
                jsonify(
                    {
                        "error": "Internal server error",
                        "disposition": starved.disposition.value,
                        "starved": {
                            "field": starved.field,
                            "producer": starved.producer,
                            "reason": starved.reason,
                        },
                    }
                ),
                500,
            )

    return _guarded


@app.errorhandler(429)
def _rate_limited(_error):
    """Rate-limit rejections are expected traffic, never Sentry noise.

    The token-bucket guard returns its 429 responses directly from the
    route, so they never pass through this handler; it exists for the
    symmetric ``abort(429)`` path and deliberately skips capture.
    """
    return jsonify({"error": "Rate limit exceeded"}), 429


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


def _public_loadout_summary(loadout) -> dict:
    """Sanitize one resolved loadout for the browser."""
    return public_loadout_summary(loadout, _VERIFIED_CHAMPIONS)


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


def _run_data_update():
    """Import data_updater only when actually updating: its import chain
    pulls in vendor/lolstaticdata, which production images don't ship."""
    # pylint: disable-next=import-outside-toplevel  # deliberate, see docstring
    from src.calculator.data_updater import update_data

    return update_data()


@app.route("/auth/login", methods=["GET", "POST"])
def auth_login():
    """Authenticate one of the explicitly configured private accounts.

    In invite-gated deployments (``SCRYGLASS_INVITE_CODES`` set on top of
    the auth gate) the landing form requires an invite code alongside the
    research-account password; the validated code is recorded in the signed
    session so every later request carries its invite source.
    """
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
    invite = None
    if _invite_mode():
        invite = request.form.get("invite_code", "").strip()
        if not invite or invite not in _invite_codes():
            return _login_page("Enter a valid invite code.", 401, next_path)
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    encoded = users.get(username)
    if not encoded or not _verify_password(password, encoded):
        return _login_page("Username or password was not recognised.", 401, next_path)
    session = _pack_signed(
        {
            "username": username,
            "exp": time.time() + _AUTH_TTL_SECONDS,
            "invite": invite,
        }
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
    """Expose the current local identity and gate configuration."""
    session = _current_session()
    return jsonify(
        {
            "required": _auth_enabled(),
            "authenticated": bool(session),
            "user": session or None,
            "invite_required": _invite_mode(),
        }
    )


@app.route("/api/auth/invite", methods=["GET", "POST"])
def api_auth_invite():
    """Validate one invite code without logging in.

    ``GET`` reports whether the deployment is invite-gated; ``POST`` with a
    JSON ``{"code": ...}`` body returns 200 + the normalized code when it is
    configured and valid, 401 for an unknown code, 400 for a missing code,
    and 503 when no codes are configured.  The route is exempt from the auth
    gate so the pre-login landing page can call it.
    """
    if request.method == "GET":
        return jsonify(
            {
                "invite_required": _invite_mode(),
                "configured": bool(_invite_codes()),
            }
        )
    try:
        data = _json_object()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    code = data.get("code")
    if not isinstance(code, str) or not code.strip():
        return jsonify({"error": "code is required"}), 400
    if not _invite_codes():
        return (
            jsonify({"error": "Invite codes are not configured on this deployment"}),
            503,
        )
    normalized = code.strip()
    if normalized not in _invite_codes():
        return jsonify({"error": "Invalid invite code"}), 401
    return jsonify({"valid": True, "invite": normalized})


@app.route("/privacy")
def privacy():
    """Public privacy summary for the closed beta."""
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    """Public terms of use for the closed beta."""
    return render_template("terms.html")


@app.route("/riot-disclaimer")
def riot_disclaimer():
    """Public Riot Games disclaimer and data-source statement."""
    return render_template("riot_disclaimer.html")


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


@app.route("/healthz")
def health():
    """Cheap liveness probe that avoids loading calculator data."""
    return jsonify({"status": "ok"})


# How old the patch-regression report may be before the golden check is
# considered stale. LoL patches land every two weeks, so 14 days is exactly
# one patch cycle: a report older than that cannot vouch for the current game.
_HEALTH_GOLDEN_STALE_DAYS = 14


def _health_db_check() -> dict:
    """Probe the persistence layer with the cheapest possible round trip."""
    backend = "postgresql" if is_postgres() else "sqlite"
    try:
        with session() as db_session:
            db_session.execute(text("SELECT 1"))
    # pylint: disable-next=broad-exception-caught
    except Exception as exc:
        app.logger.exception("Deep health: database check failed")
        return {
            "status": "error",
            "backend": backend,
            "configured": is_configured(),
            "error": str(exc),
        }
    return {"status": "ok", "backend": backend, "configured": is_configured()}


def _health_cache_check() -> dict:
    """Read the result-cache counters; a backend failure is an error."""
    try:
        stats = cache_stats()
    except (SQLAlchemyError, CacheUnavailable) as exc:
        app.logger.exception("Deep health: cache check failed")
        return {
            "status": "error",
            "enabled": _result_cache_enabled(),
            "backend": cache_backend(),
            "error": str(exc),
        }
    hits = int(stats.get("hits") or 0)
    misses = int(stats.get("misses") or 0)
    total = hits + misses
    return {
        "status": "ok",
        "enabled": _result_cache_enabled(),
        "backend": cache_backend(),
        "hits": hits,
        "misses": misses,
        "hit_ratio": round(hits / total, 4) if total else None,
        "cached_entries": int(stats.get("cached_entries") or 0),
    }


def _health_golden_check() -> dict:
    """Golden (patch-regression) staleness from data/staleness.json.

    The report's ``checked_at`` timestamp is authoritative; when it is
    missing or unparseable the file mtime is the fallback age. A report
    at or beyond ``_HEALTH_GOLDEN_STALE_DAYS`` old is ``stale``.
    """
    report = _read_staleness()
    path = _staleness_path()
    if report is None:
        return {
            "status": "missing",
            "path": str(path),
            "stale_threshold_days": _HEALTH_GOLDEN_STALE_DAYS,
        }
    checked_at = report.get("checked_at")
    age_days = None
    if isinstance(checked_at, str):
        try:
            parsed = datetime.fromisoformat(checked_at)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age_days = max(
                0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400.0
            )
        except ValueError:
            age_days = None
    if age_days is None:
        try:
            age_days = max(0.0, (time.time() - path.stat().st_mtime) / 86400.0)
        except OSError:
            age_days = None
    stale = age_days is None or age_days >= _HEALTH_GOLDEN_STALE_DAYS
    return {
        "status": "stale" if stale else "ok",
        "patch": report.get("patch"),
        "checked_at": checked_at,
        "age_days": round(age_days, 2) if age_days is not None else None,
        "stale_threshold_days": _HEALTH_GOLDEN_STALE_DAYS,
    }


def _health_engine_check() -> dict:
    """Engine registration counts; an empty registry means broken data."""
    return {
        "status": "ok" if _ENGINE_CHAMPIONS else "degraded",
        "registered": len(_ENGINE_CHAMPIONS),
        "reviewed": len(_VERIFIED_CHAMPIONS),
        "module_contract": "champion_module_v1",
    }


@app.route("/api/health/deep")
def api_health_deep():
    """Deep health probe: db, result cache, golden staleness, engine.

    Public (like /healthz) so uptime monitors can reach it without a
    session. Status is ``ok`` when every check is ok, ``degraded`` when a
    check is stale/missing/degraded, and ``error`` when any check failed.
    """
    checks = {
        "db": _health_db_check(),
        "cache": _health_cache_check(),
        "golden": _health_golden_check(),
        "engine": _health_engine_check(),
    }
    statuses = {check["status"] for check in checks.values()}
    if "error" in statuses:
        overall = "error"
    elif statuses - {"ok"}:
        overall = "degraded"
    else:
        overall = "ok"
    return jsonify(
        {
            "status": overall,
            "checks": checks,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


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
        # A module that certifies only a subset of fight modes publishes that
        # restriction (and its sourced reason) so the interface can request a
        # supported mode instead of failing closed at calculation time. None
        # means unrestricted: every public fight mode is certified.
        supported_modes = get_supported_fight_modes(champ_data["name"])
        result.append(
            {
                "name": champ_data["name"],
                "icon": _https_icon(champ_data.get("icon", "")),
                "verified": availability["ready"],
                "engine_registered": champ_data["name"] in _ENGINE_CHAMPIONS,
                "engine_registration": engine_registration_kind(champ_data["name"]),
                "engine_backend_enabled": (champ_data["name"] in _ENGINE_CHAMPIONS),
                "supported_fight_modes": (
                    list(supported_modes) if supported_modes is not None else None
                ),
                "unsupported_fight_mode_reason": get_unsupported_fight_mode_reason(
                    champ_data["name"]
                ),
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
                "model_coverage": item_model_coverage(
                    str(item.get("name", "")), ATTACKER_LANES
                ).as_payload(),
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
                "model_coverage": item_model_coverage(
                    str(item.get("name", "")), ATTACKER_LANES
                ).as_payload(),
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
            "domain_contract": {
                "role_quest": role_quest_domain_contract(),
                "rank_allocation": rank_allocation_contract(),
                "bis_objectives": bis_objective_contract(),
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
                "module_contract": "champion_module_v1",
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
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    cache_key = None
    if _result_cache_enabled():
        cache_key = stable_cache_key(
            _OPERATION_POLICY["calculate"]["cache_namespace"], data
        )
        cached_payload = cache_get(cache_key)
        if cached_payload is not None:
            return jsonify(cached_payload)

    rate_limit_response = _spend_rate_limit(
        _OPERATION_POLICY["calculate"]["rate_limit_scope"]
    )
    if rate_limit_response is not None:
        return rate_limit_response

    try:
        payload = calculate_payload(data)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if cache_key is not None:
        cache_set(cache_key, payload)
    return jsonify(payload)


@app.route("/api/bis", methods=["POST"])
def api_bis():
    """Rank one slot through the pure BIS application boundary."""
    try:
        data = _json_object()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    cache_key = None
    if _result_cache_enabled():
        cache_key = stable_cache_key(_OPERATION_POLICY["bis"]["cache_namespace"], data)
        cached_payload = cache_get(cache_key)
        if cached_payload is not None:
            return jsonify(cached_payload)

    rate_limit_response = _spend_rate_limit(
        _OPERATION_POLICY["bis"]["rate_limit_scope"]
    )
    if rate_limit_response is not None:
        return rate_limit_response

    try:
        payload = bis_payload(data)
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "requested data"
        return jsonify({"error": f"Scenario data '{missing}' not found"}), 404
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if cache_key is not None:
        cache_set(cache_key, payload)
    return jsonify(payload)


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    """Find the optimal item build for a champion.

    Request parsing and validation run through the shared scenario boundary
    (``parse_scenario_request``/``resolve_scenario``), so optimize rejects
    the same malformed payloads and calc-blocked participant items as
    /api/calculate and /api/bis (issue #138).  Optimizer-only fields
    (objective, locked items, budgets) are parsed after the shared call, and
    the deterministic result is cached under the ``optimize`` namespace.
    """
    try:
        data = _json_object()
        request = parse_scenario_request(
            data, deterministic=True, parse_crossover=False
        )
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
        optimization_scope = _request_string(data, "optimization_scope", "build")
        if optimization_scope not in {"build", "purchase"}:
            raise ValueError("optimization_scope must be 'build' or 'purchase'")
        available_gold = (
            _request_int(data, "available_gold", 0, 1, 30_000)
            if data.get("available_gold") not in (None, "")
            else None
        )
        if optimization_scope == "purchase" and available_gold is None:
            raise ValueError("available_gold is required for purchase optimization")
        max_purchase_items = (
            _request_int(data, "max_purchase_items", 0, 1, 7)
            if data.get("max_purchase_items") not in (None, "")
            else None
        )
        allow_sell = data.get("allow_sell", False)
        if not isinstance(allow_sell, bool):
            raise ValueError("allow_sell must be true or false")
        max_sell_items = _request_int(data, "max_sell_items", 1, 0, 1)
        combine_policy = _request_string(data, "combine_policy", "shop_combine")
        if combine_policy not in {"shop_combine", "component_accumulate"}:
            raise ValueError(
                "combine_policy must be 'shop_combine' or 'component_accumulate'"
            )
        include_starters = data.get("include_starters", False)
        if not isinstance(include_starters, bool):
            raise ValueError("include_starters must be true or false")
        time_budget_ms = _request_int(data, "time_budget_ms", 12_000, 100, 60_000)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    cache_key = None
    if _result_cache_enabled():
        # Optimize is deterministic (``deterministic=True``) and the most
        # expensive endpoint (worst case ~1.8 CPU seconds), so it consults
        # and populates the same result cache as calculate/BIS.
        cache_key = stable_cache_key(
            _OPERATION_POLICY["optimize"]["cache_namespace"], data
        )
        cached_payload = cache_get(cache_key)
        if cached_payload is not None:
            return jsonify(cached_payload)

    try:
        resolved = resolve_scenario(request)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    champion_data = resolved.champion_data
    level = request.level
    fight_params = resolved.fight_params
    enemies = list(resolved.enemies)
    allies = list(resolved.allies)
    target_fight_params = resolved.target_fight_params

    # Optimizer-specific parameters
    if objective not in ("total_damage", "physical_damage", "magic_damage"):
        return jsonify({"error": "Invalid objective"}), 400
    if optimization_scope == "build" and len(locked_items) > max_legendary_slots:
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

    allowed_slots = min(
        6,
        inventory_capacity(fight_params.role, fight_params.role_quest_complete)
        - int(include_boots),
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

    rate_limit_response = _spend_rate_limit(
        _OPERATION_POLICY["optimize"]["rate_limit_scope"]
    )
    if rate_limit_response is not None:
        return rate_limit_response

    instrumentation = app.config.get("OPTIMIZER_INSTRUMENTATION") or {}
    try:
        common_optimizer_args = {
            "work_counters": instrumentation.get("work_counters"),
            "use_compiled_walk": instrumentation.get("use_compiled_walk", True),
            "champion_data": champion_data,
            "level": level,
            "fight_params": fight_params,
            "objective": objective,
            "locked_items": locked_items if locked_items else None,
            "locked_boots": locked_boots if locked_boots else None,
            "target_fight_params": target_fight_params or None,
            "boots_tier": required_boots_tier(
                fight_params.role, fight_params.role_quest_complete
            ),
            "require_complete_timeline": True,
            "enemy_loadouts": enemies,
            "ally_loadouts": allies,
            "include_boots": include_boots,
        }
        if optimization_scope == "purchase":
            result = optimize_purchase(
                **common_optimizer_args,
                available_gold=available_gold or 0,
                max_purchase_items=max_purchase_items,
                allow_sell=allow_sell,
                max_sell_items=max_sell_items,
                combine_policy=combine_policy,
                include_starters=include_starters,
                time_budget_ms=time_budget_ms,
            )
        else:
            result = optimize_build(
                **common_optimizer_args,
                max_legendary_slots=max_legendary_slots,
                gold_budget=gold_budget,
            )
    except ApplicationError as exc:
        return jsonify(exc.public_payload()), 400
    except (KeyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    if cache_key is not None:
        cache_set(cache_key, result)
    return jsonify(result)


@app.route("/api/builds", methods=["POST"])
def api_save_build():
    """Persist one build scenario for later reload or sharing.

    The request mirrors the /api/calculate payload.  Dedicated columns take
    champion/level/role/items/item_options/ability_ranks/champion_options/
    enemies/allies; every remaining key (boots, fight_mode, target stats,
    rotations, ...) is preserved losslessly in ``fight_params`` so the saved
    build can be reconstructed into a full calculate request.
    """
    try:
        data = _json_object()
        _request_string(data, "champion", required=True)
        _request_int(data, "level", 1, 1, MAX_LEVEL)
        role = _request_string(data, "role")
        items = data.get("items", [])
        if not isinstance(items, list) or not all(
            isinstance(entry, str) and 0 < len(entry.strip()) <= 100 for entry in items
        ):
            raise ValueError("items must be a list of item names")
        if len(items) > 20:
            raise ValueError("items may contain at most 20 entries")
        for key in ("item_options", "ability_ranks", "champion_options"):
            value = data.get(key, {})
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be a JSON object")
        for key in ("enemies", "allies"):
            value = data.get(key, [])
            if not isinstance(value, list):
                raise ValueError(f"{key} must be a list")
        if role and len(role) > 20:
            raise ValueError("role must be at most 20 characters")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        build_id = save_build(data, session_id=_anon_session_id())
    except SQLAlchemyError as exc:  # surface DB failure to the client
        app.logger.exception("Failed to save build")
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    return jsonify({"build_id": build_id}), 201


@app.route("/api/builds/<int:build_id>")
def api_get_build(build_id: int):
    """Return one saved build payload, or 404."""
    try:
        build = get_build(build_id)
    except SQLAlchemyError as exc:  # surface DB failure to the client
        app.logger.exception("Failed to load build")
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    if build is None:
        return jsonify({"error": f"Build {build_id} not found"}), 404
    return jsonify(build)


@app.route("/api/share", methods=["POST"])
def api_create_share():
    """Create a public share link for a saved build."""
    try:
        data = _json_object()
        build_id = _request_int(data, "build_id", 0, 1, 1_000_000_000)
        slug = _request_string(data, "slug")
        if slug and not all(
            character.isalnum() or character in "-_" for character in slug
        ):
            raise ValueError(
                "slug may contain only letters, digits, dashes, underscores"
            )
        if len(slug) > 50:
            raise ValueError("slug must be at most 50 characters")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        share = create_share_link(
            build_id, slug=slug or None, session_id=_anon_session_id()
        )
    except KeyError:
        return jsonify({"error": f"Build {build_id} not found"}), 404
    except SQLAlchemyError as exc:  # surface DB failure to the client
        app.logger.exception("Failed to create share link")
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    return jsonify(share), 201


@app.route("/api/share/<token>")
def api_get_share(token: str):
    """Resolve a share token to its build payload; counts one view."""
    if not token or len(token) > 100:
        return jsonify({"error": "Invalid share token"}), 404
    try:
        payload = get_share_link(token, increment_views=True)
    except SQLAlchemyError as exc:  # surface DB failure to the client
        app.logger.exception("Failed to resolve share link")
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    if payload is None:
        return jsonify({"error": "Share link not found"}), 404
    return jsonify(payload)


@app.route("/api/feedback", methods=["POST"])
def api_add_feedback():
    """Record one validation observation for the champion-module loop."""
    try:
        data = _json_object()
        champion = _request_string(data, "champion", required=True)
        source = _request_string(data, "source", "manual")
        if source not in {"manual", "combat_log", "practice_tool"}:
            raise ValueError("source must be manual, combat_log, or practice_tool")
        for key in ("loadout", "expected", "actual"):
            value = data.get(key, {})
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be a JSON object")
        matched = data.get("matched", False)
        if not isinstance(matched, bool):
            raise ValueError("matched must be true or false")
        note = data.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise ValueError("note must be a string")
            note = note.strip()
            if len(note) > 2000:
                raise ValueError("note must be at most 2000 characters")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        feedback_id = add_feedback(
            champion=champion,
            loadout=data.get("loadout", {}),
            expected=data.get("expected", {}),
            actual=data.get("actual", {}),
            source=source,
            matched=matched,
            note=note,
            session_id=_anon_session_id(),
        )
    except SQLAlchemyError as exc:  # surface DB failure to the client
        app.logger.exception("Failed to record feedback")
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    return jsonify({"feedback_id": feedback_id}), 201


@app.route("/api/feedback")
def api_list_feedback():
    """Return recent validation feedback for the review loop."""
    champion = request.args.get("champion", "").strip() or None
    source = request.args.get("source", "").strip() or None
    try:
        limit = int(request.args.get("limit", "50"))
        rows = list_feedback(champion=champion, source=source, limit=limit)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except SQLAlchemyError as exc:  # surface DB failure to the client
        app.logger.exception("Failed to list feedback")
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    return jsonify({"feedback": rows, "count": len(rows)})


# ---------------------------------------------------------------------------
# P7 — validation loop: game receipts, systematic errors, trust labels
# ---------------------------------------------------------------------------


@app.route("/api/receipts", methods=["POST"])
# pylint: disable=too-many-branches,too-many-locals,too-many-statements
def api_receipts():
    """Record one game-receipt validation observation.

    Body: ``{"champion", "loadout" (mirror of the /api/calculate payload),
    "observed" ({"tdd", "sources"} | {"off_by_percent", "direction"} | a
    raw combat-log paste string), "source" (manual|combat_log|practice_tool),
    "note" (optional)}``.

    The engine prediction is computed for the same loadout through the same
    pipeline as /api/calculate, so ``predicted`` is exactly the total the UI
    displayed.  ``matched`` compares observed vs predicted with
    ``max(10% relative, absolute 20)`` tolerance; ``delta`` is signed
    observed-minus-predicted.  The ``off_by_percent`` shape (the widget's
    "Off by X% higher/lower" answer) is resolved against the prediction so
    the stored receipt stays numeric.  When ``observed`` is omitted the
    receipt is a positive confirmation (observed := predicted).
    """
    try:
        data = _json_object()
        champion = _request_string(data, "champion", required=True)
        source = _request_string(data, "source", "manual")
        if source not in _VALIDATION_SOURCES:
            raise ValueError("source must be manual, combat_log, or practice_tool")
        loadout = data.get("loadout")
        if loadout is None:
            loadout = {}
        if not isinstance(loadout, Mapping):
            raise ValueError("loadout must be an object")
        note = data.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise ValueError("note must be a string")
            note = note.strip()
            if len(note) > 2000:
                raise ValueError("note must be at most 2000 characters")
        observed_raw = data.get("observed")
        if observed_raw is None or isinstance(observed_raw, str):
            observed_input = observed_raw
        elif isinstance(observed_raw, Mapping):
            observed_input = dict(observed_raw)
        else:
            raise ValueError("observed must be an object, a paste string, or omitted")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    rate_limit_response = _spend_rate_limit("calculate")
    if rate_limit_response is not None:
        return rate_limit_response

    calculate_data = dict(loadout)
    calculate_data["champion"] = champion
    try:
        predicted_payload = calculate_payload(calculate_data)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        evaluation = evaluate_validation_receipt(predicted_payload, observed_input)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        feedback_id = add_feedback(
            champion=champion,
            loadout=dict(loadout),
            expected=evaluation["public"]["predicted"],
            actual=evaluation["public"]["observed"],
            source=source,
            matched=evaluation["public"]["matched"],
            delta=evaluation["raw_delta"],
            note=note,
            session_id=_anon_session_id(),
        )
    except SQLAlchemyError as exc:  # surface DB failure to the client
        app.logger.exception("Failed to record receipt")
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    return (
        jsonify(
            {
                "feedback_id": feedback_id,
                **evaluation["public"],
            }
        ),
        201,
    )


@app.route("/api/validation")
def api_validation():
    """Recent receipts plus the systematic-bias summary.

    ``?champion=`` narrows both halves; ``?limit=`` pages the recent
    feedback list.  ``systematic`` is computed over ALL stored receipts for
    the champion (not just the returned page) so the +-15% / n>=5 flag is
    stable.
    """
    champion = request.args.get("champion", "").strip() or None
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        rows = list_feedback(champion=champion, limit=limit)
        systematic = validation_summary(champion=champion)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except SQLAlchemyError as exc:  # surface DB failure to the client
        app.logger.exception("Failed to read validation summary")
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    return jsonify({"feedback": rows, "count": len(rows), "systematic": systematic})


@app.route("/api/validation/champions")
def api_validation_champions():
    """Champions with feedback counts and bias, for a future dashboard."""
    try:
        summary = validation_summary()
    except SQLAlchemyError as exc:  # surface DB failure to the client
        app.logger.exception("Failed to read validation champions")
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    return jsonify({"champions": summary})


# --- Beta metrics (P1b) ---------------------------------------------------
# Whitelist mirrors db._VALID_METRIC_EVENTS; keep the two in sync.
_METRICS_EVENT_NAMES = frozenset({"quick_complete", "page_view"})
_METRICS_EVENT_MAX_TOOK_MS = 3_600_000


@app.route("/api/metrics/event", methods=["POST"])
def api_metrics_event():
    """Record one anonymous, session-scoped product event (no PII).

    Body: ``{"event": "quick_complete", "took_ms": 1234}`` where
    ``took_ms`` is the wall-clock time the user took to complete
    champion -> role -> Best-next-item (the beta activation funnel).  The
    anonymous session id is a first-party cookie (``scryglass_anon``)
    minted here when missing; it never contains account material.  The
    route is deliberately pre-auth so funnel events can be collected from
    any browser session, and is rate-limited like every other public API.
    """
    try:
        data = _json_object()
        event = _request_string(data, "event", required=True)
        if event not in _METRICS_EVENT_NAMES:
            raise ValueError(f"event must be one of {sorted(_METRICS_EVENT_NAMES)}")
        took_ms = data.get("took_ms")
        if took_ms is not None:
            if not isinstance(took_ms, int) or isinstance(took_ms, bool):
                raise ValueError("took_ms must be an integer")
            if took_ms < 0 or took_ms > _METRICS_EVENT_MAX_TOOK_MS:
                raise ValueError(
                    f"took_ms must be between 0 and {_METRICS_EVENT_MAX_TOOK_MS}"
                )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    rate_limit_response = _spend_rate_limit("metrics_event")
    if rate_limit_response is not None:
        return rate_limit_response

    session_id = _anon_session_id()
    try:
        event_id = record_metric_event(
            event=event, session_id=session_id, took_ms=took_ms
        )
    except SQLAlchemyError as exc:  # surface DB failure to the client
        app.logger.exception("Failed to record metrics event")
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    return jsonify({"event_id": event_id, "event": event}), 201


@app.route("/api/metrics")
def api_metrics():
    """Beta success scorecard with the PASS/FAIL gate (auth-gated).

    The scorecard is computed by src/metrics.compute_scorecard so the
    dashboard endpoint and the ``scripts/beta_metrics.py`` CLI share one
    definition of the gate (see docs/beta-metrics.md).  The module ships
    inside the runtime package (issue #144).

    TODO(cross-group): point docs/beta-metrics.md at src/metrics.py and add
    an authenticated /api/metrics smoke to .github/workflows/tests.yml and
    docs/deploy.md (issue #144 findings §5.5/§5.7; tests/test_deployment_package.py
    already covers the identical deployed file set locally).
    """
    try:
        # pylint: disable-next=import-outside-toplevel  # deliberate lazy import
        from src.metrics import compute_scorecard
    except ImportError:
        app.logger.exception("Failed to import the beta metrics scorecard")
        return jsonify({"error": "Metrics module unavailable"}), 503
    try:
        scorecard = compute_scorecard()
    except SQLAlchemyError as exc:  # surface DB failure to the client
        app.logger.exception("Failed to compute the beta scorecard")
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    return jsonify(scorecard)


@app.route("/api/certainty")
def api_certainty():
    """Trust-label data: per-ability certainty for one champion.

    ``?champion=`` is required.  Certainty levels:

    * ``exact`` — every damaging/heal row is a sourced formula with no
      player-controlled default;
    * ``estimate`` — the module uses a defaulted option (stacks/procs/
      uptime), a documented approximation, or is an unreviewed generated
      packet;
    * ``boundary`` — a documented non-computed mechanic exists (utility-
      only slot, death-only trigger, out-of-scope row).
    """
    champion = request.args.get("champion", "").strip()
    if not champion:
        return jsonify({"error": "champion is required"}), 400
    try:
        champion_data = _load_public_champion(champion)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    try:
        return jsonify(derive_certainty(champion, champion_data))
    except (ImportError, KeyError, ValueError) as exc:
        app.logger.exception("Failed to derive certainty for %s", champion)
        return jsonify({"error": f"Certainty unavailable: {exc}"}), 500


@app.route("/api/not-modeled")
def api_not_modeled():
    """Documented non-computed mechanics for one champion.

    Collects the module's ASSUMPTIONS lines that describe mechanics the
    model deliberately does not price (``not modeled``, ``not priced``,
    ``documented``, ``boundary``, ``out of scope``, ``utility only``,
    ``stays state``).  Computed approximations (ESTIMATE) are deliberately
    excluded — they belong in /api/certainty, not here.
    """
    champion = request.args.get("champion", "").strip()
    if not champion:
        return jsonify({"error": "champion is required"}), 400
    try:
        _champion_data = _load_public_champion(champion)  # existence + mode gate
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    meta = get_champion_module_meta(champion)
    assumptions = meta.get("assumptions") or []
    items = [
        line
        for line in assumptions
        if _classify_assumption(line) == _CERTAINTY_BOUNDARY
    ]
    return jsonify({"champion": champion, "items": items})


@app.route("/api/cache-status")
def api_cache_status():
    """Cache hit/miss counters plus live entry count."""
    try:
        stats = cache_stats()
    except (SQLAlchemyError, CacheUnavailable) as exc:
        # surface backend failure (database or Redis) to the client
        app.logger.exception("Failed to read cache status")
        return jsonify({"error": f"Cache backend unavailable: {exc}"}), 503
    return jsonify(
        {
            "cache_enabled": _result_cache_enabled(),
            "database_configured": is_configured(),
            "database": "postgresql" if is_postgres() else "sqlite",
            "cache_backend": cache_backend(),
            **stats,
        }
    )


def _staleness_path() -> Path:
    """Path of the patch-regression report served by /api/staleness."""
    return Path(__file__).resolve().parent.parent / "data" / "staleness.json"


def _read_staleness():
    """Load data/staleness.json, or None when it is missing/invalid."""
    path = _staleness_path()
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None


@app.route("/api/staleness")
def api_staleness():
    """Serve the patch-regression report (wiki cache vs game files).

    The report is generated by scripts/patch_regression.py on patch day and
    committed with the data cache; this endpoint is the read-only face the
    STALE badge consumes.  Missing report -> 404, never a silent fallback.
    """
    report = _read_staleness()
    if report is None:
        return jsonify({"error": "No staleness report; run patch regression"}), 404
    return jsonify(report)


@app.route("/api/staleness/regenerate", methods=["POST"])
def api_staleness_regenerate():
    """Re-run the patch regression against the game files. Dev-only, guarded
    exactly like /api/update-data (local dev mode + update cookie)."""
    supplied_token = request.cookies.get(_DEV_UPDATE_COOKIE, "")
    if not _local_dev_request() or not hmac.compare_digest(
        supplied_token, _DEV_UPDATE_TOKEN
    ):
        return (
            jsonify({"error": "Staleness regeneration is disabled on this server"}),
            404,
        )

    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "scripts" / "patch_regression.py"
    if not script.exists():
        return jsonify({"error": "patch_regression.py not found"}), 500
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "check",
                "--data-dir",
                str(repo_root / "data"),
                "--cache-dir",
                str(repo_root / "data" / "gamefiles"),
                "--out",
                str(_staleness_path()),
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "patch regression timed out"}), 504
    report = _read_staleness()
    if result.returncode != 0 or report is None:
        return (
            jsonify(
                {
                    "error": "patch regression failed",
                    "exit": result.returncode,
                    "stderr": result.stderr[-2000:],
                }
            ),
            500,
        )
    return jsonify(report)


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
        # Every cached calculation was produced against the previous data
        # snapshot; drop the results so the next request recomputes.
        cache_delete_all()

    return Response(generate(), mimetype="text/event-stream")


# The request boundary, applied once every route above is registered: the
# single ``except StarvedSignal`` in ``src/`` reaches every endpoint from
# here, and a source assertion allowlists it and forbids every other — over
# the class, so a member added later is converted rather than newly anonymous.
for _endpoint, _view in list(app.view_functions.items()):
    app.view_functions[_endpoint] = _within_starvation_boundary(_view)


if __name__ == "__main__":
    app.run(debug=_dev_mode(), port=5000)
