"""Fail-closed coverage labels for item mechanics used by BIS search.

Raw item stats are always sourced by :mod:`stats`.  This module answers the
separate question the optimiser needs: is every outgoing-damage mechanic on
this item represented by the current fight model?
"""

from typing import Any, Literal

from .item_effects import ITEM_EFFECTS, ITEM_INPUT_OPTIONS

ItemCoverageStatus = Literal[
    "modeled_effect",
    "modeled_state",
    "stats_only",
    "blocked",
    "review_pending",
]


# These mechanics can change TDD, casts, resources, or target durability.  The
# optimiser withholds them until the named mechanic has an explicit model.
_BLOCKED_REASONS: dict[str, str] = {
    "Axiom Arc": "Flux takedown cooldown refunds are not modelled.",
    "Ardent Censer": "Sanctify's conditional self buff and on-hit damage are not modelled.",
    "Endless Hunger": "Famine's bonus-AD-scaled ability haste is not modelled.",
    "Fimbulwinter": "Awe's mana scaling and Everlasting shield state are not modelled.",
    "Hubris": "Eminence takedown stacks and temporary attack damage are not modelled.",
    "Immortal Path": "Now and Forever's health-state damage amplification is not modelled.",
    "Imperial Mandate": (
        "Control's ability haste and Command's damage amplification are not modelled."
    ),
    "Manamune": "Awe's mana scaling and Manaflow stack state are not modelled.",
    "Redemption": "Intervention's target-max-health true damage is not modelled.",
    "Rod of Ages": "Timeless minute stacks and level gain are not modelled.",
    "Runaan's Hurricane": "Wind's Fury multi-target bolts and copied on-hits are not modelled.",
    "Serpent's Fang": "Shield Reaver's active and future shield reduction is not modelled.",
    "Swiftmarch": "Noxian Fervor's movement-speed-scaled adaptive force is not modelled.",
    "Thornmail": (
        "Thorns' reactive magic damage requires incoming attack events that are not modelled."
    ),
    "Umbral Glaive": "Nightstalker's first-attack true damage is not modelled.",
    "Warmog's Armor": "Warmog's Vitality bonus item-health multiplier is not modelled.",
    "Whispering Circlet": "Manaflow stacks and the Diadem transformation state are not modelled.",
    "Winter's Approach": "Awe's mana scaling and Manaflow transformation state are not modelled.",
    "Zeke's Convergence": "Ultimate haste and Frostfire Tempest damage are not modelled.",
}


# Each entry was reviewed against the cached Wiki passive/active description.
# The effect does not add outgoing TDD in the calculator's current attacker
# event model; the item's ordinary stats still flow through stats.py.
_REVIEWED_STATS_ONLY: dict[str, str] = {
    "Banshee's Veil": "Annul is defensive spell protection.",
    "Armored Advance": "Plating and Noxian Endurance are defensive effects.",
    "Bloodthirster": "Ichorshield is a defensive shield.",
    "Celestial Opposition": "Blessing of the Mountain is defensive mitigation.",
    "Chempunk Chainsword": "Hackshorn applies anti-heal, not direct damage.",
    "Cosmic Drive": "Spelldance grants movement speed, not direct damage.",
    "Cryptbloom": "Life From Death is a post-takedown heal.",
    "Death's Dance": "Ignore Pain and Defy change incoming damage and healing.",
    "Diadem of Songs": "Harmony and Consonance change healing, not outgoing damage.",
    "Dream Maker": "Dream Maker affects an ally, not the item holder's TDD.",
    "Echoes of Helia": "Soul Siphon stores damage only to heal an ally.",
    "Edge of Night": "Annul is defensive spell protection.",
    "Force of Nature": "Steadfast grants defensive stats and movement speed.",
    "Frozen Heart": "Winter's Caress reduces enemy attack speed.",
    "Guardian Angel": "Rebirth is a defensive revive.",
    "Gluttonous Greaves": "Slay grants omnivamp, not outgoing damage.",
    "Immortal Shieldbow": "Lifeline is a defensive shield.",
    "Jak'Sho, The Protean": "Voidborn Resilience changes defensive resistances.",
    "Kaenic Rookern": "Magebane is a defensive magic shield.",
    "Chainlaced Crushers": "Noxian Persistence is a defensive magic shield.",
    "Knight's Vow": "Sacrifice and Pledge redirect damage and heal the holder.",
    "Locket of the Iron Solari": "Devotion shields allies.",
    "Maw of Malmortius": "Lifeline is a defensive shield.",
    "Mercurial Scimitar": "Quicksilver cleanses crowd control and grants movement speed.",
    "Mikael's Blessing": "Purify cleanses and heals an ally.",
    "Moonstone Renewer": "Starlit Grace chains healing or shielding.",
    "Morellonomicon": "Grievous Wounds applies anti-heal, not direct damage.",
    "Mortal Reminder": "Grievous Wounds applies anti-heal, not direct damage.",
    "Phantom Dancer": "Spectral Waltz grants ghosting.",
    "Plated Steelcaps": "Plating reduces incoming basic damage.",
    "Protoplasm Harness": "Lifeline is an incoming-damage defensive trigger.",
    "Randuin's Omen": "Resilience and Humility reduce incoming damage.",
    "Rylai's Crystal Scepter": "Rimefrost slows without adding direct damage.",
    "Crimson Lucidity": "Its passives grant summoner haste and movement speed.",
    "Serylda's Grudge": "Bitter Cold slows without adding direct damage.",
    "Shurelya's Battlesong": "Inspiring Speech grants movement speed.",
    "Solstice Sleigh": "Going Sledding heals and grants movement speed.",
    "Spirit Visage": "Boundless Vitality increases healing and shielding received.",
    "Boots of Swiftness": "Fleetfooted grants slow resistance.",
    "Ionian Boots of Lucidity": "Ionian Insight grants summoner spell haste.",
    "Youmuu's Ghostblade": "Haunt and Wraith Step grant movement speed.",
    "Zhonya's Hourglass": "Time Stop is defensive stasis.",
}


# Target loadouts are currently passive recipients of the selected attacker
# package.  Any equipped mechanic that changes their incoming damage, health,
# shields, or combat healing must either be represented here or stop the run.
_TARGET_MODELED_REASONS: dict[str, str] = {
    "Kaenic Rookern": "Magebane's ready maximum-health magic shield is modelled.",
    "Spirit Visage": "Boundless Vitality amplifies modelled starting shields.",
    "Warmog's Armor": (
        "Warmog's Vitality modifies item health; combat regeneration stays "
        "inactive while the target is taking damage."
    ),
    "Plated Steelcaps": "Plating's 10% non-true basic-damage reduction is modelled.",
    "Warden's Mail": (
        "Rock Solid's post-mitigation 15 reduction, capped at 20%, is modelled."
    ),
    "Randuin's Omen": (
        "Resilience's 30% incoming critical-strike damage reduction is modelled."
    ),
}

_TARGET_BLOCKED_REASONS: dict[str, str] = {
    "Armored Advance": "Plating's incoming physical-damage reduction is not modelled.",
    "Banshee's Veil": "Annul's first-hostile-ability spell shield is not modelled.",
    "Bloodthirster": "Ichorshield's accumulated starting shield is not modelled.",
    "Celestial Opposition": (
        "Blessing of the Mountain's opening damage reduction is not modelled."
    ),
    "Chainlaced Crushers": "Noxian Persistence's magic shield is not modelled.",
    "Death's Dance": "Ignore Pain's damage deferral is not modelled.",
    "Doran's Shield": "Endure's combat health regeneration is not modelled.",
    "Eclipse": "Ever Rising Moon's target-side shield trigger is not modelled.",
    "Edge of Night": "Annul's first-hostile-ability spell shield is not modelled.",
    "Fimbulwinter": "Awe bonus health and Everlasting shields are not modelled.",
    "Force of Nature": "Steadfast's combat magic-resistance stacks are not modelled.",
    "Frozen Heart": "Winter's Caress attack-speed reduction is not modelled.",
    "Guardian Angel": "Rebirth is not modelled in target health damage.",
    "Guardian's Horn": "Legendary's flat incoming-damage reduction is not modelled.",
    "Heartsteel": "Permanent Colossal Consumption health stacks are not modelled.",
    "Hexdrinker": "Lifeline's low-health magic shield is not modelled.",
    "Immortal Shieldbow": "Lifeline's low-health shield is not modelled.",
    "Jak'Sho, The Protean": "Voidborn Resilience's combat resist stacks are not modelled.",
    "Knight's Vow": "Pledge damage redirection and healing are not modelled.",
    "Locket of the Iron Solari": "Devotion's activated shield is not modelled.",
    "Maw of Malmortius": "Lifeline's low-health magic shield is not modelled.",
    "Mikael's Blessing": "Purify's activated heal is not modelled.",
    "Protoplasm Harness": "Lifeline's low-health shield is not modelled.",
    "Redemption": "Intervention's activated target healing is not modelled.",
    "Rod of Ages": "Timeless health stacks are not exposed as target state.",
    "Seeker's Armguard": "Time Stop's stasis is not modelled.",
    "Seraph's Embrace": "Lifeline's low-health mana shield is not modelled.",
    "Spectre's Cowl": "Incorporeal's post-damage regeneration is not modelled.",
    "Sterak's Gage": "Lifeline's low-health shield is not modelled.",
    "Sundered Sky": "Lightshield Strike's target-side healing is not modelled.",
    "Thornmail": "Thorns' reactive damage and attacker survival are not modelled.",
    "Unending Despair": "Anguish's periodic combat healing is not modelled.",
    "Verdant Barrier": "Annul's spell shield is not modelled.",
    "Whispering Circlet": "Manaflow health state is not exposed for target modelling.",
    "Winter's Approach": "Awe and Manaflow health state are not modelled.",
    "Zhonya's Hourglass": "Time Stop's stasis is not modelled.",
}


def _has_described_effect(item: dict[str, Any]) -> bool:
    """Return whether cached Wiki data describes a passive or active."""
    return bool(item.get("passives") or item.get("active") or item.get("actives"))


def item_model_coverage(item: dict[str, Any]) -> dict[str, Any]:
    """Return the optimiser coverage classification for one resolved item."""
    name = str(item.get("name", ""))
    if ITEM_EFFECTS.get(name, {}).get("type") in {
        "defensive_start",
        "target_mitigation",
    }:
        status: ItemCoverageStatus = "stats_only"
        reason = "The represented mechanic changes defense, not outgoing TDD."
    elif name in ITEM_EFFECTS:
        status: ItemCoverageStatus = "modeled_effect"
        reason = "Damage-relevant effects are represented by the fight model."
    elif name in ITEM_INPUT_OPTIONS:
        status = "modeled_state"
        reason = "The item exposes its damage-relevant state as a scenario control."
    elif name in _BLOCKED_REASONS:
        status = "blocked"
        reason = _BLOCKED_REASONS[name]
    elif not _has_described_effect(item):
        status = "stats_only"
        reason = "The item has no separate passive or active in the cached Wiki data."
    elif name in _REVIEWED_STATS_ONLY:
        status = "stats_only"
        reason = _REVIEWED_STATS_ONLY[name]
    else:
        status = "review_pending"
        reason = "This passive or active has not yet been reviewed for outgoing TDD."

    return {
        "name": name,
        "status": status,
        "optimizer_eligible": status
        in {"modeled_effect", "modeled_state", "stats_only"},
        "reason": reason,
    }


def target_item_model_coverage(item: dict[str, Any]) -> dict[str, Any]:
    """Classify one item for use on a passive enemy target."""
    name = str(item.get("name", ""))
    if name in _TARGET_MODELED_REASONS:
        status = "modeled"
        reason = _TARGET_MODELED_REASONS[name]
    elif name in _TARGET_BLOCKED_REASONS:
        status = "blocked"
        reason = _TARGET_BLOCKED_REASONS[name]
    elif item_model_coverage(item)["status"] == "review_pending":
        status = "review_pending"
        reason = "This passive or active has not been reviewed for target durability."
    else:
        status = "not_target_relevant"
        reason = (
            "No reviewed effect on this item changes incoming damage or starting "
            "durability in the passive-target model."
        )
    return {
        "name": name,
        "status": status,
        "calculation_eligible": status not in {"blocked", "review_pending"},
        "reason": reason,
    }


def target_build_coverage(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise whether a target inventory is safe to calculate."""
    entries = [target_item_model_coverage(item) for item in items]
    blocked = [entry for entry in entries if not entry["calculation_eligible"]]
    return {
        "complete": not blocked,
        "model": "passive_target",
        "items": entries,
        "blocked": blocked,
        "note": (
            "Every equipped item is supported by the passive-target model."
            if not blocked
            else "Calculation is withheld until the named target mechanic is modelled."
        ),
    }


def require_target_item_coverage(items: list[dict[str, Any]]) -> None:
    """Reject target inventories that would silently omit a defense."""
    coverage = target_build_coverage(items)
    if coverage["blocked"]:
        blocked = coverage["blocked"][0]
        raise ValueError(
            f"Enemy item {blocked['name']} is not supported yet: {blocked['reason']}"
        )


def optimizer_candidate_coverage(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise which legal item candidates can be scored without omission."""
    classified = [item_model_coverage(item) for item in items]
    included = [entry for entry in classified if entry["optimizer_eligible"]]
    excluded = [entry for entry in classified if not entry["optimizer_eligible"]]
    return {
        "eligible_candidates": len(classified),
        "scored_candidates": len(included),
        "excluded_count": len(excluded),
        "complete": not excluded,
        "excluded": excluded,
        "note": (
            "Every legal candidate is fully modelled."
            if not excluded
            else (
                f"{len(excluded)} legal item candidate"
                f"{' is' if len(excluded) == 1 else 's are'} withheld because "
                "a damage-relevant mechanic is not yet modelled."
            )
        ),
    }


def optimizer_supported_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return candidates whose outgoing TDD can be scored without omission."""
    return [item for item in items if item_model_coverage(item)["optimizer_eligible"]]


def require_optimizer_item_coverage(item: dict[str, Any]) -> None:
    """Reject a locked item whose damage-relevant mechanics are incomplete."""
    coverage = item_model_coverage(item)
    if not coverage["optimizer_eligible"]:
        raise ValueError(
            f"{coverage['name']} cannot be locked into BIS search yet: "
            f"{coverage['reason']}"
        )


__all__ = [
    "item_model_coverage",
    "optimizer_candidate_coverage",
    "optimizer_supported_items",
    "require_optimizer_item_coverage",
    "require_target_item_coverage",
    "target_build_coverage",
    "target_item_model_coverage",
]
