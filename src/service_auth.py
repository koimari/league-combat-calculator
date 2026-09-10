"""Authorize the calculator server proxy for its bounded HTTP surface."""

import hmac

SERVICE_ROUTES = frozenset(
    {
        ("GET", "/api/champions"),
        ("GET", "/api/config"),
        ("GET", "/api/items"),
        ("GET", "/api/boots"),
        ("GET", "/api/certainty"),
        ("GET", "/api/not-modeled"),
        ("GET", "/api/staleness"),
        ("GET", "/static/data.json"),
        ("GET", "/static/ability-catalog.json"),
        ("GET", "/static/bis-profiles.json"),
        ("GET", "/static/effect-catalog.json"),
        ("POST", "/api/loadout-stats"),
        ("POST", "/api/calculate"),
        ("POST", "/api/compare"),
        ("POST", "/api/bis"),
        ("POST", "/api/bis/batch"),
        ("POST", "/api/optimize"),
    }
)


def authorize_service_request(
    authorization: str, *, method: str, path: str, configured_token: str
) -> bool | None:
    """Return a bearer verdict, or None when browser authentication applies."""
    scheme, _, supplied = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    expected = configured_token.strip()
    if len(expected) < 32:
        return False
    matches = hmac.compare_digest(
        supplied.strip().encode("utf-8"), expected.encode("utf-8")
    )
    return matches and (method, path) in SERVICE_ROUTES
