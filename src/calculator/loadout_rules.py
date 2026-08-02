"""Authoritative inventory and item-exclusivity rules.

Every entry point uses this module.  The browser may prevent an illegal
selection for convenience, but the API and optimizer remain the authority.
"""

from collections.abc import Iterable
from typing import Any

from .role_quests import validate_role

ITEM_EXCLUSIVITY_GROUPS: dict[str, frozenset[str]] = {
    "Glory": frozenset({"Dark Seal", "Mejai's Soulstealer"}),
    "Spellblade": frozenset(
        {
            "Trinity Force",
            "Lich Bane",
            "Essence Reaver",
            "Iceborn Gauntlet",
            "Bloodsong",
            "Dusk and Dawn",
        }
    ),
    "Hydra": frozenset(
        {
            "Tiamat",
            "Profane Hydra",
            "Ravenous Hydra",
            "Stridebreaker",
            "Titanic Hydra",
        }
    ),
    "Blight": frozenset(
        {
            "Blighting Jewel",
            "Bloodletter's Curse",
            "Cryptbloom",
            "Terminus",
            "Void Staff",
        }
    ),
    "Fatality": frozenset(
        {
            "Last Whisper",
            "Black Cleaver",
            "Lord Dominik's Regards",
            "Mortal Reminder",
            "Serylda's Grudge",
            "Terminus",
        }
    ),
}

ITEM_TO_EXCLUSIVITY_GROUPS: dict[str, frozenset[str]] = {}
for _group_name, _members in ITEM_EXCLUSIVITY_GROUPS.items():
    for _item_name in _members:
        ITEM_TO_EXCLUSIVITY_GROUPS[_item_name] = frozenset(
            {*ITEM_TO_EXCLUSIVITY_GROUPS.get(_item_name, ()), _group_name}
        )


def exclusivity_groups() -> dict[str, list[str]]:
    """Return stable JSON-safe item groups for the picker."""
    return {
        group: sorted(members) for group, members in ITEM_EXCLUSIVITY_GROUPS.items()
    }


def occupied_groups(item_names: Iterable[str]) -> set[str]:
    """Return every exclusivity group occupied by ``item_names``."""
    occupied: set[str] = set()
    for name in item_names:
        occupied.update(ITEM_TO_EXCLUSIVITY_GROUPS.get(name, ()))
    return occupied


def conflicts_with_groups(item_name: str, groups: set[str]) -> bool:
    """Return whether adding ``item_name`` would violate ``groups``."""
    return bool(ITEM_TO_EXCLUSIVITY_GROUPS.get(item_name, frozenset()) & groups)


def inventory_capacity(role: str, role_quest_complete: bool) -> int:
    """Return combat-item slots for the selected role state."""
    parsed_role = validate_role(role)
    if role_quest_complete and not parsed_role:
        raise ValueError("role is required when role_quest_complete is true")
    return 7 if parsed_role == "bottom" and role_quest_complete else 6


def required_boots_tier(role: str, role_quest_complete: bool) -> int:
    """Return the only boots tier legal for the selected role state."""
    parsed_role = validate_role(role)
    if role_quest_complete and not parsed_role:
        raise ValueError("role is required when role_quest_complete is true")
    return 3 if parsed_role == "mid" and role_quest_complete else 2


def role_scoped_shop_items(
    items: Iterable[dict[str, Any]], role: str
) -> list[dict[str, Any]]:
    """Return completed items in the selected role's sourced shop scope.

    Role tags are an item-shop legality boundary for the optimizer.  They are
    deliberately not a champion archetype or stat heuristic: the remaining
    candidates are still evaluated with the champion-specific event model.
    An omitted role keeps the historical, unrestricted engine contract.
    """
    parsed_role = validate_role(role)
    candidates = list(items)
    if parsed_role == "support":
        return [
            item
            for item in candidates
            if "SUPPORT"
            in {str(tag).upper() for tag in item.get("shop", {}).get("tags", [])}
        ]
    if parsed_role in {"top", "jungle", "mid", "bottom"}:
        return [
            item
            for item in candidates
            if "SUPPORT"
            not in {str(tag).upper() for tag in item.get("shop", {}).get("tags", [])}
        ]
    return candidates


def validate_resolved_loadout(
    ordinary_items: Iterable[dict[str, Any]],
    *,
    boots: dict[str, Any] | None = None,
    role: str = "",
    role_quest_complete: bool = False,
) -> None:
    """Reject an inventory that cannot exist in a live game."""
    ordinary = list(ordinary_items)
    equipped = ([boots] if boots else []) + ordinary
    names = [str(item.get("name", "")) for item in equipped]
    if any(not name for name in names):
        raise ValueError("Every selected item must have a name")
    if len(set(names)) != len(names):
        raise ValueError("A build must not contain duplicate items")
    if len(equipped) > inventory_capacity(role, role_quest_complete):
        raise ValueError("Selected items exceed the available inventory slots")

    boot_items = [item for item in equipped if "BOOTS" in item.get("rank", [])]
    if len(boot_items) > 1:
        raise ValueError("A build may contain at most one pair of boots")
    if boots is not None and boots not in boot_items:
        raise ValueError(f"{boots.get('name', 'Selected boots')} is not a boots item")
    for item in ordinary:
        if "BOOTS" in item.get("rank", []):
            raise ValueError("Boots must use the dedicated boots slot")
    if boots is not None:
        expected_tier = required_boots_tier(role, role_quest_complete)
        actual_tier = int(boots.get("tier", 0))
        if actual_tier != expected_tier:
            raise ValueError(
                f"{boots['name']} is tier {actual_tier}; this role state "
                f"requires tier-{expected_tier} boots"
            )

    seen_groups: dict[str, str] = {}
    for name in names:
        for group in ITEM_TO_EXCLUSIVITY_GROUPS.get(name, ()):
            if group in seen_groups:
                raise ValueError(
                    f"{seen_groups[group]} and {name} cannot be equipped together "
                    f"({group} group)"
                )
            seen_groups[group] = name
