"""Patch-pinned Summoner's Rift role-quest combat rules.

Source: League of Legends Wiki, ``Role Quests``, revision 4026385
(2026-06-09), retrieved by the local Scryglass Wiki warehouse.
https://wiki.leagueoflegends.com/en-us/Role_Quests
"""

from typing import Final

ROLES: Final[frozenset[str]] = frozenset({"top", "jungle", "mid", "bottom", "support"})

# Mid quest: "Gain 8% bonus AD and 8% AP" (V26.11).
MID_QUEST_BONUS_AD_PERCENT: Final[float] = 8.0
MID_QUEST_AP_PERCENT: Final[float] = 8.0

# Top quest: raises the champion level cap from 18 to 20.
BASE_LEVEL_CAP: Final[int] = 18
TOP_QUEST_LEVEL_CAP: Final[int] = 20


def level_cap(role: str, quest_complete: bool) -> int:
    """Return the champion level cap this role and quest state allow."""
    if role == "top" and quest_complete:
        return TOP_QUEST_LEVEL_CAP
    return BASE_LEVEL_CAP


def require_level_within_cap(
    level: int, role: str, quest_complete: bool, *, field: str = "level"
) -> None:
    """Reject champion levels above what the role's quest state allows."""
    cap = level_cap(role, quest_complete)
    if level > cap:
        raise ValueError(
            f"{field} above {cap} requires a completed top-lane role quest"
        )


def validate_role(role: object) -> str:
    """Return a normalized public role value or reject it."""
    if role in (None, ""):
        return ""
    if not isinstance(role, str):
        raise ValueError("role must be a string")
    normalized = role.strip().lower()
    if normalized not in ROLES:
        raise ValueError("role must be top, jungle, mid, bottom, or support")
    return normalized


def role_quest_meta(role: str, complete: bool) -> dict[str, object]:
    """Expose the currently modeled combat/inventory consequence."""
    if not complete:
        return {"role": role, "complete": False, "effect": "Not active"}
    effects = {
        "top": "Raises the champion level cap from 18 to 20",
        "jungle": "Movement reward is positional and not used for damage scoring",
        "mid": "8% bonus AD, 8% AP, and tier-3 boots",
        "bottom": "Boots move to the quest slot, allowing six ordinary items",
        "support": "Ward and support-item rewards do not add an ordinary damage slot",
    }
    return {"role": role, "complete": True, "effect": effects[role]}
