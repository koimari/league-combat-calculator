"""Patch-pinned Summoner's Rift role-quest combat rules.

Source: League of Legends Wiki, ``Role Quests``, revision 4026385
(2026-06-09), retrieved by the local Scryglass Wiki warehouse.
https://wiki.leagueoflegends.com/en-us/Role_Quests
"""

from typing import Final

ROLES: Final[frozenset[str]] = frozenset({"top", "jungle", "mid", "bottom", "support"})

# Support quest progression is represented as an explicit inventory contract.
# The cache has no reliable source-item links for these seasonal items, so
# keep the sourced names and progression stages together here rather than
# letting a frontend picker infer an upgrade from an item id.
SUPPORT_QUEST_ITEM_STAGES: Final[dict[str, str]] = {
    "World Atlas": "starter",
    "Runic Compass": "intermediate",
    "Celestial Opposition": "upgraded",
    "Dream Maker": "upgraded",
    "Zaz'Zak's Realmspike": "upgraded",
    "Solstice Sleigh": "upgraded",
    "Bloodsong": "upgraded",
}
SUPPORT_QUEST_STARTER_STAGES: Final[frozenset[str]] = frozenset(
    {"starter", "intermediate"}
)
SUPPORT_QUEST_UPGRADED_STAGE: Final[str] = "upgraded"

# Names are the stable public values used by the cached item source.  Item
# ids are deliberately absent so patch data can refresh without a second,
# frontend-only numeric mapping.
BOOT_UPGRADES: Final[dict[str, str]] = {
    "Berserker's Greaves": "Gunmetal Greaves",
    "Boots of Swiftness": "Swiftmarch",
    "Gluttonous Greaves": "Immortal Path",
    "Ionian Boots of Lucidity": "Crimson Lucidity",
    "Mercury's Treads": "Chainlaced Crushers",
    "Plated Steelcaps": "Armored Advance",
    "Sorcerer's Shoes": "Spellslinger's Shoes",
}
# Mid quest: "Gain 8% bonus AD and 8% AP" (V26.11).
MID_QUEST_BONUS_AD_PERCENT: Final[float] = 8.0
MID_QUEST_AP_PERCENT: Final[float] = 8.0

# Top-lane reward from the Season 2026 Role Quests: the completion packet
# grants one upfront level's worth of sourced experience and increases later
# experience gains; the calculator exposes the resulting level cap while the
# actual level remains an explicit user input.
TOP_QUEST_BONUS_XP: Final[int] = 600
TOP_QUEST_FUTURE_XP_PERCENT: Final[float] = 12.5
BASE_LEVEL_CAP: Final[int] = 18
TOP_QUEST_LEVEL_CAP: Final[int] = 20
TOP_LEVEL_CAP: Final[int] = TOP_QUEST_LEVEL_CAP


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
        "top": (
            f"+{TOP_QUEST_BONUS_XP} XP, +{TOP_QUEST_FUTURE_XP_PERCENT:g}% future XP, "
            f"and level cap {TOP_LEVEL_CAP}"
        ),
        "jungle": "Movement reward is positional and not used for damage scoring",
        "mid": "8% bonus AD, 8% AP, and tier-3 boots",
        "bottom": "Boots move to the quest slot, allowing six ordinary items",
        "support": (
            "Support quest complete: one upgraded support item is legal; "
            "the item remains part of the six combat inventory slots"
        ),
    }
    return {"role": role, "complete": True, "effect": effects[role]}


def max_champion_level(role: str, complete: bool) -> int:
    """Return the sourced level cap for the selected role-quest state."""
    # Direct engine/unit-test callers supply level 20 without a role object;
    # that internal contract holds.  Public loadouts use
    # ``require_level_within_cap`` above and therefore still require the
    # completed top quest explicitly.
    if not role:
        return TOP_LEVEL_CAP
    return level_cap(role, complete)


def support_quest_item_stage(item_name: object) -> str | None:
    """Return the authored support-quest stage for one cached item name."""
    if not isinstance(item_name, str):
        return None
    return SUPPORT_QUEST_ITEM_STAGES.get(item_name)


def support_quest_item_contract() -> dict[str, object]:
    """Expose the support quest item gate to API clients and the picker."""
    return {
        "role": "support",
        "complete_field": "role_quest_complete",
        "stages": {
            "starter": sorted(
                name
                for name, stage in SUPPORT_QUEST_ITEM_STAGES.items()
                if stage == "starter"
            ),
            "intermediate": sorted(
                name
                for name, stage in SUPPORT_QUEST_ITEM_STAGES.items()
                if stage == "intermediate"
            ),
            "upgraded": sorted(
                name
                for name, stage in SUPPORT_QUEST_ITEM_STAGES.items()
                if stage == SUPPORT_QUEST_UPGRADED_STAGE
            ),
        },
        "incomplete_allowed_stages": sorted(SUPPORT_QUEST_STARTER_STAGES),
        "complete_allowed_stages": [SUPPORT_QUEST_UPGRADED_STAGE],
        "note": (
            "A completed support role quest is required before an upgraded "
            "support item can be equipped."
        ),
    }


def boot_upgrade_contract() -> dict[str, dict[str, str]]:
    """Return the sourced base/quest boot relationship for API clients."""
    return {
        base: {"base": base, "upgraded": upgraded}
        for base, upgraded in BOOT_UPGRADES.items()
    }


def role_quest_domain_contract() -> dict[str, object]:
    """Return the role-dependent limits used by every public client.

    The browser needs these values to shape controls.  Keep the calculation
    functions as the owners and publish only their JSON-safe result here.
    """
    from .loadout_rules import inventory_capacity, required_boots_tier

    states = (("incomplete", False), ("complete", True))
    return {
        "roles": sorted(ROLES),
        "level_cap": {
            "default": level_cap("", False),
            "by_role": {
                role: {
                    state_name: level_cap(role, complete)
                    for state_name, complete in states
                }
                for role in sorted(ROLES)
            },
        },
        "inventory_capacity": {
            "default": inventory_capacity("", False),
            "by_role": {
                role: {
                    state_name: inventory_capacity(role, complete)
                    for state_name, complete in states
                }
                for role in sorted(ROLES)
            },
        },
        "boots_tier": {
            "default": required_boots_tier("", False),
            "by_role": {
                role: {
                    state_name: required_boots_tier(role, complete)
                    for state_name, complete in states
                }
                for role in sorted(ROLES)
            },
        },
    }
