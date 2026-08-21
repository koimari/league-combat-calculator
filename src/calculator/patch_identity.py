"""Map Riot public patch labels to client and source-version labels."""

from __future__ import annotations

import re
from dataclasses import dataclass


class PatchIdentityError(ValueError):
    """Raised when a patch label cannot be mapped without guessing."""


_PATCH_RE = re.compile(r"^v?(?P<major>\d{2})\.(?P<minor>\d{1,2})(?:\.\d+)?$")


@dataclass(frozen=True)
class PatchIdentity:
    public_patch: str
    client_patch: str


def canonical_patch(value: object) -> PatchIdentity:
    text = str(value or "").strip()
    match = _PATCH_RE.fullmatch(text)
    if match is None:
        raise PatchIdentityError(f"malformed patch label: {value!r}")
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    if major not in {15, 16, 25, 26}:
        raise PatchIdentityError(
            f"unsupported patch season {major}; expected 25/26 or 15/16"
        )
    public_major = major if major in {25, 26} else major + 10
    client_major = major if major in {15, 16} else major - 10
    client_minor = str(minor) if minor < 10 else f"{minor:02d}"
    return PatchIdentity(
        public_patch=f"{public_major}.{minor:02d}",
        client_patch=f"{client_major}.{client_minor}",
    )


def public_patch(value: object) -> str:
    return canonical_patch(value).public_patch


def client_patch(value: object) -> str:
    return canonical_patch(value).client_patch


__all__ = [
    "PatchIdentity",
    "PatchIdentityError",
    "canonical_patch",
    "client_patch",
    "public_patch",
]
