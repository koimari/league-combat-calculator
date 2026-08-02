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

# Top-lane reward from the Season 2026 Role Quests: the completion packet
# grants one upfront level's worth of sourced experience and increases later
# experience gains; the calculator exposes the resulting level cap while the
# actual level remains an explicit user input.
TOP_QUEST_BONUS_XP: Final[int] = 600
TOP_QUEST_FUTURE_XP_PERCENT: Final[float] = 12.5
TOP_LEVEL_CAP: Final[int] = 20


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
        "top": (
            f"+{TOP_QUEST_BONUS_XP} XP, +{TOP_QUEST_FUTURE_XP_PERCENT:g}% future XP, "
            f"and level cap {TOP_LEVEL_CAP}"
        ),
        "jungle": "Movement reward is positional and not used for damage scoring",
        "mid": "8% bonus AD, 8% AP, and tier-3 boots",
        "bottom": "Boots move to the quest slot, allowing six ordinary items",
        "support": "Ward and support-item rewards do not add an ordinary damage slot",
    }
    return {"role": role, "complete": True, "effect": effects[role]}


def max_champion_level(role: str, complete: bool) -> int:
    """Return the sourced level cap for the selected role-quest state."""
    # A blank role is the legacy API contract: callers that already provide a
    # concrete level are not silently assigned a quest state.  Once a role is
    # selected, level 19/20 is reserved for a completed top quest.
    if not role:
        return TOP_LEVEL_CAP
    return TOP_LEVEL_CAP if role == "top" and complete else 18
