"""One-request build comparison boundary.

The browser needs two complete results for a build comparison.  Keeping the
two calculations behind one application boundary removes the client-side
request fan-out and gives the server one cache and rate-limit decision.
"""

from collections.abc import Mapping

from .calculate import calculate_payload


def compare_payload(data: Mapping[str, object]) -> dict[str, object]:
    """Calculate exactly two complete builds from one request body."""
    raw_builds = data.get("builds")
    if not isinstance(raw_builds, list) or len(raw_builds) != 2:
        raise ValueError("builds must contain exactly 2 calculation objects")

    results: list[dict] = []
    for index, build in enumerate(raw_builds):
        if not isinstance(build, Mapping):
            raise ValueError(f"builds[{index}] must be an object")
        results.append(calculate_payload(build, deterministic=True))

    return {
        "results": results,
        "build_count": len(results),
        "request_count": 1,
        "mode": "deterministic",
    }
