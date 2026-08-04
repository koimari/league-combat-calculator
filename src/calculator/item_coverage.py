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
    "Endless Hunger": (
        "Feast's takedown-triggered 15% omnivamp for 8 seconds is not modelled."
    ),
    "Fimbulwinter": "Awe's mana scaling and Everlasting shield state are not modelled.",
    "Hubris": "Eminence takedown stacks and temporary attack damage are not modelled.",
    "Immortal Path": "Now and Forever's health-state damage amplification is not modelled.",
    "Imperial Mandate": (
        "Control's ability haste and Command's damage amplification are not modelled."
    ),
    "Manamune": "Awe's mana scaling and Manaflow stack state are not modelled.",
    "Redemption": "Intervention's target-max-health true damage is not modelled.",
    "Rod of Ages": "Timeless minute stacks and level gain are not modelled.",
    "Swiftmarch": "Noxian Fervor's movement-speed-scaled adaptive force is not modelled.",
    "Umbral Glaive": "Nightstalker's first-attack true damage is not modelled.",
    "Whispering Circlet": "Manaflow stacks and the Diadem transformation state are not modelled.",
    "Winter's Approach": "Awe's mana scaling and Manaflow transformation state are not modelled.",
    "Zeke's Convergence": "Ultimate haste and Frostfire Tempest damage are not modelled.",
    "Cull": (
        "Reap's 100-minion progression and 350 gold completion payout are not "
        "modelled."
    ),
    "World Atlas": (
        "Support Quest's 400 gold Shared Riches upgrade and Runic Compass/Ward "
        "transition are not modelled."
    ),
    "Doran's Helm": (
        "Helping Hand's 5 bonus physical damage is restricted to minions; the "
        "item's combat regeneration state is not modelled."
    ),
    "Doran's Ring": (
        "Helping Hand's 5 bonus physical damage is restricted to minions; Drain's "
        "combat resource/heal state is not modelled."
    ),
    "Doran's Shield": (
        "Helping Hand's 5 bonus physical damage is restricted to minions; "
        "Enduring Focus's missing-health regeneration state is not modelled."
    ),
    "Phage": "Rage's conditional movement-speed state is not modelled.",
    "Tear of the Goddess": "Manaflow stack progression is not modelled.",
    "Catalyst of Aeons": (
        "Eternity's damage-based mana restoration and per-cast healing are not "
        "modelled."
    ),
    "Gunmetal Greaves": (
        "Riot's cached description declares Noxian Gait (attacks grant decaying "
        "movement speed for 2 seconds), but the item passive is absent from the "
        "cached Wiki branches and its magnitude cannot be sourced safely."
    ),
    "Runic Compass": (
        "Support Quest's 800 gold upgrade, Shared Riches charges, and Ward active "
        "are not modelled."
    ),
}

# A calculation may expose a fully sourced combat sub-effect even while the
# optimiser must withhold the item because a separate progression/economy
# state is not simulated.  Keep this list narrow and explicit: the API should
# never silently turn an incomplete combat mechanic into a partial result.
_CALCULATION_ALLOWED_BLOCKED = frozenset({"Cull"})

# Items can have a registered damage packet while still carrying an
# unrepresented sibling passive or state transition.  Keep those items
# fail-closed until every fight-relevant child effect is covered; a name in
# ``ITEM_EFFECTS`` is not proof that the whole item is modelled.
_PARTIAL_BLOCKED_REASONS: dict[str, str] = {
    "Fimbulwinter": (
        "Awe's bonus-mana-to-health conversion is modeled, but Everlasting's "
        "conditional shield and cooldown state are not scheduled."
    ),
    "Bandlepipes": (
        "Fanfare's conditional movement speed and nearby-ally attack-speed buff "
        "are not modelled; only the holder's sourced attack-speed packet is "
        "represented."
    ),
    "Thornmail": (
        "Thornmail's Thorns is a reactive target-side packet; it is modeled "
        "for enemy inventories but is not an outgoing attacker effect."
    ),
    "Actualizer": (
        "Mana Made Real's active duration, doubled mana costs, basic-cooldown "
        "progress, and heal/shield amplification are not modelled."
    ),
    "Archangel's Staff": (
        "Awe's bonus-mana-to-ability-power conversion is modeled, but Manaflow's "
        "charge/bonus-mana progression and the Seraph's Embrace transformation "
        "state are not scheduled."
    ),
    "Winter's Approach": (
        "Awe's bonus-mana-to-health conversion is modeled, but Manaflow's "
        "charge/transform state is not scheduled."
    ),
    "Endless Hunger": (
        "Famine's bonus-AD ability haste is modeled, but Feast's takedown-triggered "
        "15% omnivamp for 8 seconds is not scheduled."
    ),
    "Hubris": (
        "Eminence's takedown trigger, 90-second duration, and permanent stack "
        "state are not scheduled in the participant ledger."
    ),
    "Axiom Arc": (
        "Flux's takedown trigger, three-second damage window, and ultimate "
        "cooldown refund are not scheduled in the participant ledger."
    ),
    "Rapid Firecannon": (
        "Energized generation and recharge timing are not modeled; only the "
        "opening proc packet is priced."
    ),
    "Statikk Shiv": (
        "Energized recharge and level-scaled chain target allocation are modeled, "
        "and fixed-source copied on-hit packets are replayed; current-health and "
        "stack-gated copied effects remain unavailable."
    ),
    "Stormrazor": (
        "Energized generation/recharge and Bolt movement-speed state are not "
        "modeled; only the opening proc packet is priced."
    ),
    "Stridebreaker": (
        "Breaking Shockwave's movement-speed/slow sibling is not modeled; its "
        "active secondary damage packet is represented."
    ),
    "Voltaic Cyclosword": (
        "Energized generation/recharge remains unavailable beyond the authored "
        "opening proc; the sourced temporary lethality window is applied to "
        "later timestamped physical events."
    ),
}


# Each entry was reviewed against the cached Wiki passive/active description.
# The effect does not add outgoing TDD in the calculator's current attacker
# event model; the item's ordinary stats still flow through stats.py.
_REVIEWED_STATS_ONLY: dict[str, str] = {
    "Banshee's Veil": "Annul is defensive spell protection.",
    "Scorchclaw Pup": "The jungle companion and evolved Smite buff affect monsters, not the champion target model.",
    "Gustwalker Hatchling": "The jungle companion and evolved Smite buff affect monsters, not the champion target model.",
    "Mosstomper Seedling": "The jungle companion and evolved Smite buff affect monsters, not the champion target model.",
    "Refillable Potion": "Potion charges restore the holder's health; they add no outgoing target damage.",
    "Seeker's Armguard": "Time Stop is defensive stasis.",
    "Executioner's Calling": "Grievous Wounds reduces recipient healing; it adds no direct damage.",
    "Oblivion Orb": "Grievous Wounds reduces recipient healing; it adds no direct damage.",
    "Quicksilver Sash": "Quicksilver is defensive cleanse.",
    "Lost Chapter": "Enlighten restores mana on level-up; it adds no direct damage.",
    "Verdant Barrier": "Annul is defensive spell protection.",
    "Armored Advance": "Plating and Noxian Endurance are defensive effects.",
    "Bloodthirster": "Ichorshield is a defensive shield.",
    "Celestial Opposition": "Blessing of the Mountain is defensive mitigation.",
    "Chempunk Chainsword": (
        "Hackshorn applies sourced three-second Grievous Wounds in the coupled "
        "timeline; it does not add direct damage."
    ),
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
    "Morellonomicon": (
        "Grievous Wounds reduces recipient healing in the coupled timeline; it "
        "does not add direct damage."
    ),
    "Mortal Reminder": (
        "Grievous Wounds reduces recipient healing in the coupled timeline; it "
        "does not add direct damage."
    ),
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
    "Banshee's Veil": (
        "Annul is ready at the opening and consumes every packet belonging to "
        "the first source-backed Q/W/E/R cast; auto attacks and later casts land."
    ),
    "Edge of Night": (
        "Annul is ready at the opening and consumes every packet belonging to "
        "the first source-backed Q/W/E/R cast; auto attacks and later casts land."
    ),
    "Verdant Barrier": (
        "Annul is ready at the opening and consumes every packet belonging to "
        "the first source-backed Q/W/E/R cast; auto attacks and later casts land."
    ),
    "Bramble Vest": (
        "Thorns' reactive damage and Grievous Wounds are scheduled from the "
        "attacker's modeled basic-attack events in the coupled timeline."
    ),
    "Thornmail": (
        "Thornmail's 20 magic damage plus 10% wearer bonus-armor Thorns and "
        "Grievous Wounds are scheduled from modeled basic-attack events."
    ),
    "Kaenic Rookern": "Magebane's ready maximum-health magic shield is modelled.",
    "Spirit Visage": (
        "Boundless Vitality amplifies modeled healing, shields, and regeneration "
        "received in the participant ledger."
    ),
    "Warmog's Armor": (
        "Warmog's Vitality modifies item health; combat regeneration stays "
        "inactive while the target is taking damage."
    ),
    "Unending Despair": (
        "Anguish's every-four-second magic pulse and 250% post-mitigation "
        "self-heal are scheduled on the certified participant ledger."
    ),
    "Sundered Sky": (
        "Lightshield Strike's base-AD plus missing-health heal is replayed on "
        "the first attack; excess healing becomes sourced 8-second temporary "
        "health in the participant ledger."
    ),
    "Dusk and Dawn": (
        "Spellblade's self-heal is replayed from each certified empowered attack "
        "in the target actor's own participant timeline."
    ),
    "Cull": (
        "Reap's 3-health champion on-hit heal is replayed for the target actor; "
        "its minion progression and gold payout remain optimizer-only gaps."
    ),
    "Plated Steelcaps": "Plating's 10% non-true basic-damage reduction is modelled.",
    "Warden's Mail": (
        "Rock Solid's post-mitigation 15 reduction, capped at 20%, is modelled."
    ),
    "Randuin's Omen": (
        "Resilience's 30% incoming critical-strike damage reduction is modelled."
    ),
    "Frozen Heart": (
        "Winter's Caress applies its sourced 20% total attack-speed cripple to "
        "the opposing participant's authored swing schedule."
    ),
    "Guardian Angel": (
        "Rebirth restores 50% base health four seconds after the first lethal "
        "packet; the coupled survival ledger applies it once when the event "
        "falls inside the selected window."
    ),
}

# Lifeline defenses trigger mid-fight, so pricing them consumes the ordered
# damage ledger.  They are computed for one rotation and for timed fights whose
# every damage event carries a certified timestamp; an uncertified timed fight
# is withheld after computation instead of reporting a mis-timed trigger.
_TARGET_EVENT_CERTIFIED_REASONS: dict[str, str] = {
    "Protoplasm Harness": (
        "Lifeline's level-scaled temporary health and resist-scaled healing "
        "are modeled when every damage event is event-certified. The "
        "calculation fails closed if damage reaches the unsourced "
        "temporary-health expiry boundary."
    ),
    "Hexdrinker": (
        "Lifeline's level-scaled 30%-health magic shield is modeled when "
        "every damage event is event-certified; uncertified timed fights are "
        "withheld."
    ),
    "Immortal Shieldbow": (
        "Lifeline's level-scaled 30%-health shield is modeled when every "
        "damage event is event-certified; uncertified timed fights are "
        "withheld."
    ),
    "Maw of Malmortius": (
        "Lifeline's bonus-AD-scaled 30%-health magic shield is modeled when "
        "every damage event is event-certified; uncertified timed fights are "
        "withheld."
    ),
    "Seraph's Embrace": (
        "Lifeline's maximum-mana-scaled 30%-health shield is modeled when "
        "every damage event is event-certified; uncertified timed fights are "
        "withheld."
    ),
    "Sterak's Gage": (
        "Lifeline's bonus-health-scaled 30%-health shield is modeled when "
        "every damage event is event-certified; uncertified timed fights are "
        "withheld."
    ),
}

_TARGET_BLOCKED_REASONS: dict[str, str] = {
    "Armored Advance": (
        "Noxian Endurance's physical-damage shield trigger is not modelled; "
        "the item's separately sourced Plating reduction is not enough to "
        "price the complete target loadout."
    ),
    "Bloodthirster": "Ichorshield's accumulated starting shield is not modelled.",
    "Celestial Opposition": (
        "Blessing of the Mountain's opening damage reduction is not modelled."
    ),
    "Chainlaced Crushers": "Noxian Persistence's magic shield is not modelled.",
    "Death's Dance": "Ignore Pain's damage deferral is not modelled.",
    "Doran's Shield": "Endure's combat health regeneration is not modelled.",
    "Eclipse": "Ever Rising Moon's target-side shield trigger is not modelled.",
    "Fimbulwinter": "Awe bonus health and Everlasting shields are not modelled.",
    "Force of Nature": (
        "Steadfast's target-side stack timing is not modelled: champion magic "
        "damage grants at most one stack per incoming cast instance per second "
        "(two on immobilize), stacks expire after 7s, and only 8 stacks grant "
        "+70 bonus magic resistance."
    ),
    "Guardian's Horn": "Legendary's flat incoming-damage reduction is not modelled.",
    "Jak'Sho, The Protean": "Voidborn Resilience's combat resist stacks are not modelled.",
    "Knight's Vow": "Pledge damage redirection and healing are not modelled.",
    "Locket of the Iron Solari": "Devotion's activated shield is not modelled.",
    "Mikael's Blessing": "Purify's activated heal is not modelled.",
    "Redemption": "Intervention's activated target healing is not modelled.",
    "Seeker's Armguard": "Time Stop's stasis is not modelled.",
    "Spectre's Cowl": "Incorporeal's post-damage regeneration is not modelled.",
    "Whispering Circlet": "Manaflow health state is not exposed for target modelling.",
    "Winter's Approach": "Awe and Manaflow health state are not modelled.",
    "Zhonya's Hourglass": "Time Stop's stasis is not modelled.",
}

# Product-facing outcome dimensions for utility and non-TDD effects.  These
# labels are deliberately descriptive: they do not claim a combat formula is
# implemented.  A dimension with ``blocked`` coverage remains withheld rather
# than being silently presented as a stat-only item.
_UTILITY_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "Bandlepipes": ("ally_support", "stat_buff"),
    "Cull": ("economy", "progression", "on_hit"),
    "Heartsteel": ("progression", "health_state"),
    "Hubris": ("progression", "stat_conversion"),
    "Axiom Arc": ("progression", "resource"),
    "Mejai's Soulstealer": ("progression", "stat_conversion"),
    "Rod of Ages": ("progression", "health_state", "resource"),
    "Solstice Sleigh": ("ally_support", "movement", "sustain"),
    "Swiftmarch": ("movement", "stat_conversion"),
    "World Atlas": ("economy", "quest", "ally_support"),
    "Banshee's Veil": ("spell_protection",),
    "Edge of Night": ("spell_protection",),
    "Zhonya's Hourglass": ("stasis",),
    "Guardian Angel": ("revive",),
    "Mercurial Scimitar": ("cleanse", "movement"),
    "Boots of Swiftness": ("slow_resistance", "movement"),
    "Cosmic Drive": ("movement",),
    "Force of Nature": ("movement", "defense"),
    "Phantom Dancer": ("movement",),
    "Shurelya's Battlesong": ("movement", "ally_support"),
    "Youmuu's Ghostblade": ("movement",),
    "Rylai's Crystal Scepter": ("slow",),
    "Serylda's Grudge": ("slow",),
    "Frozen Heart": ("attack_speed_reduction",),
    "Randuin's Omen": ("slow", "critical_mitigation"),
    "Runaan's Hurricane": ("multi_target", "copied_on_hit"),
    "Titanic Hydra": ("multi_target",),
    "Profane Hydra": ("multi_target",),
    "Ravenous Hydra": ("multi_target", "sustain"),
    "Stridebreaker": ("multi_target", "slow", "movement"),
    "Statikk Shiv": ("multi_target", "energized"),
    "Stormrazor": ("energized", "movement"),
    "Rapid Firecannon": ("energized", "range"),
    "Umbral Glaive": ("vision",),
    "Horizon Focus": ("vision", "damage_amplification"),
    "Locket of the Iron Solari": ("ally_support", "shield"),
    "Mikael's Blessing": ("ally_support", "cleanse", "sustain"),
    "Redemption": ("ally_support", "sustain"),
    "The Collector": ("execute", "takedown_state"),
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
        "target_threshold_health",
        "target_threshold_shield",
    }:
        status: ItemCoverageStatus = "stats_only"
        reason = (
            "Guardian Angel's Rebirth is modeled in the target survival ledger; "
            "it changes defense, not outgoing TDD."
            if name == "Guardian Angel"
            else "The represented mechanic changes defense, not outgoing TDD."
        )
    elif name in _PARTIAL_BLOCKED_REASONS:
        status = "blocked"
        reason = _PARTIAL_BLOCKED_REASONS[name]
    elif name == "Heartsteel" and name in ITEM_INPUT_OPTIONS:
        status = "modeled_state"
        reason = (
            "Colossal Consumption's permanent bonus-health state is supplied "
            "through the explicit bounded scenario control."
        )
    elif name == "Rod of Ages" and name in ITEM_INPUT_OPTIONS:
        status = "modeled_state"
        reason = (
            "Timeless stacks and their sourced health, mana, and ability-power "
            "conversions are supplied through the explicit bounded scenario control."
        )
    elif name == "Overlord's Bloodmail" and name in ITEM_INPUT_OPTIONS:
        status = "modeled_state"
        reason = (
            "Tyranny is modeled and Retribution uses the explicit bounded "
            "starting missing-health scenario control."
        )
    elif name in _BLOCKED_REASONS:
        status = "blocked"
        reason = _BLOCKED_REASONS[name]
    elif name in ITEM_EFFECTS:
        status: ItemCoverageStatus = "modeled_effect"
        reason = "Damage-relevant effects are represented by the fight model."
    elif name in ITEM_INPUT_OPTIONS:
        status = "modeled_state"
        reason = "The item exposes its damage-relevant state as a scenario control."
    elif not _has_described_effect(item):
        status = "stats_only"
        reason = "The item has no separate passive or active in the cached Wiki data."
    elif name in _REVIEWED_STATS_ONLY:
        status = "stats_only"
        reason = _REVIEWED_STATS_ONLY[name]
    elif item.get("id") is not None or item.get("icon"):
        # A cached source item is a real selectable record, even when its
        # passive/active has not been reviewed yet.  Keep the public contract
        # fail-closed and explicit: ``review_pending`` is reserved for
        # synthetic/unknown fixtures that do not belong to the cached shop.
        status = "blocked"
        reason = (
            "This cached passive or active has not been reviewed for outgoing "
            "damage or state effects; calculation is withheld."
        )
    else:
        status = "review_pending"
        reason = "This passive or active has not yet been reviewed for outgoing TDD."

    return {
        "name": name,
        "status": status,
        "optimizer_eligible": status
        in {"modeled_effect", "modeled_state", "stats_only"},
        "calculation_eligible": (
            status != "review_pending"
            and (status != "blocked" or name in _CALCULATION_ALLOWED_BLOCKED)
        ),
        "outcome_dimensions": list(_UTILITY_DIMENSIONS.get(name, ())),
        "reason": reason,
    }


def target_item_model_coverage(item: dict[str, Any]) -> dict[str, Any]:
    """Classify one item for use on a passive enemy target."""
    name = str(item.get("name", ""))
    if name in _TARGET_MODELED_REASONS:
        status = "modeled"
        reason = _TARGET_MODELED_REASONS[name]
    elif name in _TARGET_EVENT_CERTIFIED_REASONS:
        status = "modeled_event_certified"
        reason = _TARGET_EVENT_CERTIFIED_REASONS[name]
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
        "outcome_dimensions": list(_UTILITY_DIMENSIONS.get(name, ())),
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


def require_certified_target_timeline(
    items: list[dict[str, Any]], timeline_coverage: dict[str, Any]
) -> None:
    """Withhold a computed timed fight that cannot price a Lifeline defense.

    Lifeline triggers are priced from the ordered damage ledger, so a coarse
    source would mis-time the trigger.  This runs after the fight so the
    error can name the exact uncertified sources instead of guessing.
    """
    if bool(timeline_coverage.get("complete", False)):
        return
    conditional = next(
        (
            str(item.get("name", ""))
            for item in items
            if str(item.get("name", "")) in _TARGET_EVENT_CERTIFIED_REASONS
        ),
        None,
    )
    if conditional is None:
        return
    coarse = [str(source) for source in timeline_coverage.get("coarse_sources", [])]
    named = ", ".join(coarse) if coarse else "at least one damage source"
    verb = "is" if len(coarse) <= 1 else "are"
    raise ValueError(
        f"Result withheld: enemy item {conditional}'s Lifeline needs a "
        f"certified event timeline, but {named} {verb} not event-certified."
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


def require_calculation_item_coverage(
    items: list[dict[str, Any]], *, participant: str
) -> None:
    """Reject a participant loadout whose outgoing effects are incomplete.

    Manual calculations and coupled roster fights are calculation entry paths,
    not only optimiser requests.  Reusing the same per-item contract here
    prevents an incomplete item from being accepted by ``/api/calculate``
    while remaining selectable in the browser.
    """
    for item in items:
        coverage = item_model_coverage(item)
        if coverage["calculation_eligible"]:
            continue
        raise ValueError(
            f"{participant} item {coverage['name']} cannot be used in a "
            f"calculation yet: {coverage['reason']}"
        )


__all__ = [
    "item_model_coverage",
    "optimizer_candidate_coverage",
    "optimizer_supported_items",
    "require_calculation_item_coverage",
    "require_certified_target_timeline",
    "require_optimizer_item_coverage",
    "require_target_item_coverage",
    "target_build_coverage",
    "target_item_model_coverage",
]
