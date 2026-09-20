"""The cached Wiki effect text of every certified ``stats_only`` item.

A golden fixture, not a rule: ``tests/test_stats_only_items.py`` diffs each
certified item's live cached text against the pin so a Wiki refresh that
appends an outgoing-damage clause to a named passive fails loudly instead of
sailing through the name-matched classification forever.
"""

from typing import Any

from src.calculator.item_source import effect_entries, effect_text

# ``stats_only`` means `item_coverage` found no OUTGOING-damage mechanic on
# the item's OWN HOLDER to model, not that the cached entry is textually
# numberless.  Half the SR-admitted stats_only items have no passive or active
# in the cache at all (potions, wards, components, most boots); the 41 pinned
# below carry a real, numeric one, and are still correctly ``stats_only``
# because none of that text adds outgoing TDD from the item's own holder in
# this 1v1 attacker fight model.
#
# Every one of the 41 is matched by NAME ONLY, in `item_coverage`'s
# ``_REVIEWED_STATS_ONLY`` or its defensive-``effect_type`` branch, and the
# classification never re-reads the text.  The pin is the exact cached branch
# text captured at certification (2026-08-20).  A text difference does not by
# itself prove a new mechanic appeared: it means a human re-reads the branch
# and either re-pins the fingerprint or reclassifies the item.
#
# Six items are outside this registry because the declaration-driven
# classifier reaches them: Diadem of Songs, Dream Maker, Echoes of Helia,
# Moonstone Renewer and Solstice Sleigh declare ally_packet mechanics the
# support ledger schedules (``modeled_state``), and Spirit Visage declares a
# sustain multiplier (``modeled_effect``).  None is ``stats_only``, so the
# drift guard has nothing to pin for them.
CERTIFIED_EFFECT_TEXT: dict[str, tuple[tuple[str, str, str], ...]] = {
    "Bramble Vest": (
        (
            "passive",
            "Thorns",
            "When struck by a basic attack [[on-hit]], deal {{as|10 magic "
            "damage}} to the attacker and, if they are a champion, inflict "
            "them with {{tip|Grievous Wounds}} for 3 seconds.",
        ),
    ),
    "Force of Nature": (
        (
            "passive",
            "Steadfast",
            "Taking {{as|magic damage}} from champions generates a stack of "
            "''Steadfast'' for 7 seconds, stacking up to 8 times with the "
            "duration refreshing on subsequent {{as|magic damage}} from "
            "them and whenever dealing damage to them. Becoming "
            "{{tip|immobilize|immobilized}} by an enemy champion generates "
            "2 stacks and also refreshes the duration. Once per {{tip|cast "
            "instance}}, each incoming basic attack, ability, or item "
            "effect can only generate 1 stack of ''Steadfast'' from their "
            "damage every 1 second. At '''maximum''' stacks, gain {{as|70 "
            "'''bonus''' magic resistance}} and {{as|6% '''bonus''' "
            "movement speed}}.",
        ),
    ),
    "Jak'Sho, The Protean": (
        (
            "passive",
            "Voidborn Resilience",
            "Gain a stack for each second [[Combat status|in combat]] with "
            "enemy champions, stacking up to 5 times. At '''maximum''' "
            "stacks, increase your {{as|'''bonus''' armor}} and "
            "{{as|'''bonus''' magic resistance}} by 30% until the end of "
            "combat.",
        ),
    ),
    "Thornmail": (
        (
            "passive",
            "Thorns",
            "When struck by a basic attack [[on-hit]], deal {{as|20 {{as|(+ "
            "10% '''bonus''' armor)}} magic damage|magic damage}} to the "
            "attacker and, if they are a champion, inflict them with "
            "{{tip|Grievous Wounds}} for 3 seconds.",
        ),
    ),
    "Armored Advance": (
        (
            "passive",
            "Plating",
            "Reduces all incoming {{tip|basic damage}} by 10% (''excluding "
            "from [[turret]] attacks'').",
        ),
        (
            "passive",
            "Noxian Endurance",
            "Taking {{as|physical damage}} from champions grants you a "
            "{{tip|shield}} that absorbs {{pp|100 to 200|color=pd}} "
            "{{as|(+ 8% '''bonus''' health)}} {{as|physical damage}} for 5 "
            "seconds.",
        ),
    ),
    "Banshee's Veil": (
        (
            "passive",
            "Annul",
            "Grants a {{tip|spell shield}} that blocks the next hostile "
            "ability (40 second cooldown, timer restarts upon taking damage "
            "from champions).",
        ),
    ),
    "Bloodthirster": (
        (
            "passive",
            "Ichorshield",
            "Convert the {{tip|healing}} received from {{sti|life steal}} in "
            "excess of {{as|'''maximum''' health}} into a {{tip|shield}} for "
            "up to {{pp|165 + (315-165)/10*(x-1)|1;9 to 20 by "
            "1|formula=165 base, then +15 per level starting from level "
            "9.}}, which lasts until destroyed.",
        ),
    ),
    "Boots of Swiftness": (("passive", "Fleetfooted", "Gain 25% [[slow resist]]."),),
    "Celestial Opposition": (
        (
            "passive",
            "Blessing of the Mountain",
            "Become ''Blessed'' to reduce incoming champion damage by "
            "{{rd|35%|25%}}, lingering for 2 seconds after taking damage "
            "from a champion. After the linger ends, you lose ''Blessed'' "
            "to unleash a shockwave around you that {{tip|slow|slows}} "
            "enemies within 500 units by 50% for {{fd|1.5}} seconds (18 "
            "second cooldown, timer restarts upon taking damage from "
            "champions).",
        ),
        (
            "active",
            "Ward",
            "Consumes a charge to place a {{tip|Stealth Ward}} at the "
            "target location, which grants {{tip|sight}} of the "
            "surrounding area. Charges refill upon visiting the shop.",
        ),
    ),
    "Chainlaced Crushers": (
        (
            "passive",
            "Noxian Persistence",
            "Taking {{as|magic damage}} from champions grants you a "
            "{{tip|shield}} that absorbs {{pp|100 to 200|color=md}} "
            "{{as|(+ 8% '''bonus''' health)}} {{as|magic damage}} for 5 "
            "seconds.",
        ),
    ),
    "Chempunk Chainsword": (
        (
            "passive",
            "Hackshorn",
            "Dealing {{as|physical damage}} to enemy champions inflicts "
            "them with {{tip|Grievous Wounds}} for 3 seconds.",
        ),
    ),
    "Cosmic Drive": (
        (
            "passive",
            "Spelldance",
            "Dealing {{as|magic|magic damage}} or {{as|true|true damage}} "
            "damage to an enemy champion grants you {{as|20 '''bonus''' "
            "movement speed|ms}} for 4 seconds.",
        ),
    ),
    "Crimson Lucidity": (
        (
            "passive",
            "Ionian Lucidity",
            "Gain 20 [[Haste#Summoner spell haste|summoner spell haste]].",
        ),
        (
            "passive",
            "Noxian Haste",
            "{{tip|heal|Healing}}, {{tip|shield|shielding}} or buffing an "
            "ally, damaging abilities against champions, and using "
            "[[summoner spell]]s grants you {{as|{{rd|10%|8%}} '''bonus''' "
            "movement speed}} for 4 seconds. This can be triggered from the "
            "same {{tip|cast instance}} only once every 4 seconds.",
        ),
    ),
    "Doran's Helm": (
        (
            "passive",
            "Helping Hand",
            "Basic attacks deal {{as|5 '''bonus''' physical damage}} "
            "[[on-hit]] against [[minions]].",
        ),
    ),
    "Edge of Night": (
        (
            "passive",
            "Annul",
            "Grants a {{tip|spell shield}} that blocks the next hostile "
            "ability (40 second cooldown, timer restarts upon taking damage "
            "from champions).",
        ),
    ),
    "Executioner's Calling": (
        (
            "passive",
            "Grievous Wounds",
            "Dealing {{as|physical damage}} to enemy champions inflicts "
            "them with {{tip|Grievous Wounds}} for 3 seconds.",
        ),
    ),
    "Guardian Angel": (
        (
            "passive",
            "Rebirth",
            "Upon taking [[death|lethal damage]], enter "
            "{{tip|resurrection}} for 4 seconds, during which you are "
            "{{tip|invulnerable}}, {{tip|untargetable}}, and unable to act, "
            "and afterwards {{tip|heal}} for {{as|50% of '''base''' "
            "health}} and restore {{as|100% of '''maximum''' mana}} (300 "
            "second cooldown, starts after resurrection ends).",
        ),
    ),
    "Gustwalker Hatchling": (
        (
            "passive",
            "Jungle Companions",
            "Summon a ''Gustwalker Hatchling'' companion to assist you in "
            "combat against monsters.",
        ),
        (
            "passive",
            "Gustwalker's Gait",
            "Feed your companion enough treats to evolve it and upgrade "
            "your {{si|Smite}}. Upon the companion reaching its final "
            "evolution, this item is consumed, granting you the "
            "{{bi|Gustwalker's Gait}} buff.",
        ),
    ),
    "Hexdrinker": (
        (
            "passive",
            "Lifeline",
            "If you would take {{as|magic damage}} that would reduce you "
            "below {{as|30% of your '''maximum''' health}}, you first gain "
            "a {{tip|shield}} that absorbs {{as|{{rd|110 to 280|82.5 to "
            "210|pp=true}} magic damage}} for {{fd|2.5}} seconds.",
        ),
    ),
    "Immortal Shieldbow": (
        (
            "passive",
            "Lifeline",
            "If you would take damage that would reduce you below "
            "{{as|30% of your '''maximum''' health}}, you first gain a "
            "{{tip|shield}} that absorbs {{rd|400 to 700 for 11|400*0.8 to "
            "700*0.8 for 11|levels=1;9 to 18|pp=true}} damage for 3 "
            "seconds.",
        ),
    ),
    "Ionian Boots of Lucidity": (
        (
            "passive",
            "Ionian Insight",
            "Gain 10 [[Haste#Summoner spell haste|summoner spell haste]].",
        ),
    ),
    "Kaenic Rookern": (
        (
            "passive",
            "Magebane",
            "After not taking {{as|magic damage}} for 15 seconds, gain a "
            "{{tip|shield}} that absorbs {{as|magic damage}} equal to "
            "{{as|15% of '''maximum''' health}} until destroyed.",
        ),
    ),
    "Morellonomicon": (
        (
            "passive",
            "Grievous Wounds",
            "Dealing {{as|magic damage}} to enemy champions inflicts them "
            "with {{tip|Grievous Wounds}} for 3 seconds.",
        ),
    ),
    "Mortal Reminder": (
        (
            "passive",
            "Grievous Wounds",
            "Dealing {{as|physical damage}} to enemy champions inflicts "
            "them with {{tip|Grievous Wounds}} for 3 seconds.",
        ),
    ),
    "Mosstomper Seedling": (
        (
            "passive",
            "Jungle Companions",
            "Summon a ''Mosstomper Seedling'' companion to assist you in "
            "combat against monsters.",
        ),
        (
            "passive",
            "Mosstomper's Courage",
            "Feed your companion enough treats to evolve it and upgrade "
            "your {{si|Smite}}. Upon the companion reaching its final "
            "evolution, this item is consumed, granting you the "
            "{{bi|Mosstomper's Courage}} buff.",
        ),
    ),
    "Oblivion Orb": (
        (
            "passive",
            "Grievous Wounds",
            "Dealing {{as|magic damage}} to enemy champions inflicts them "
            "with {{tip|Grievous Wounds}} for 3 seconds.",
        ),
    ),
    "Phantom Dancer": (
        ("passive", "Spectral Waltz", "Become permanently {{tip|ghosted}}."),
    ),
    "Plated Steelcaps": (
        (
            "passive",
            "Plating",
            "Reduces all incoming {{tip|basic damage}} by 10% (''excluding "
            "from [[turret]] attacks'').",
        ),
    ),
    "Protoplasm Harness": (
        (
            "passive",
            "Lifeline",
            "If you would take damage that would reduce you below "
            "{{as|30% of your '''maximum''' health}}, you first gain "
            "{{as|{{pp|100 to 300|tooltipSize=20}} '''bonus''' health}} for "
            "5 seconds and {{tip|heal}} yourself for {{pp|100 to 400|"
            "tooltipSize=20|color=heal}} {{as|(+ 175% '''bonus''' armor)}} "
            "{{as|(+ 175% '''bonus''' magic resistance)}} over the same "
            "duration, during which you also gain 15% increased [[size]], "
            "{{as|10% '''bonus''' movement speed}}, and 25% "
            "{{tip|tenacity}}.",
        ),
    ),
    "Randuin's Omen": (
        (
            "passive",
            "Resilience",
            "Reduces incoming damage from {{tip|critical strike|critical "
            "strikes}} by 30%.",
        ),
        (
            "active",
            "Humility",
            "Unleash a shockwave around you that {{tip|slow|slows}} "
            "nearby enemies by 70% for 2 seconds.",
        ),
    ),
    "Refillable Potion": (
        (
            "passive",
            None,
            "Holds charges that refill upon visiting the [[shop]].",
        ),
    ),
    "Rylai's Crystal Scepter": (
        (
            "passive",
            "Rimefrost",
            "Dealing {{tip|ability damage}} {{tip|slow|slows}} affected "
            "[[unit]]s by 30% for 1 second.",
        ),
    ),
    "Scorchclaw Pup": (
        (
            "passive",
            "Jungle Companions",
            "Summon a ''Scorchclaw Pup'' companion to assist you in "
            "combat against monsters.",
        ),
        (
            "passive",
            "Scorchclaw's Slash",
            "Feed your companion enough treats to evolve it and upgrade "
            "your {{si|Smite}}. Upon the companion reaching its final "
            "evolution, this item is consumed, granting you the "
            "{{bi|Scorchclaw's Slash}} buff.",
        ),
    ),
    "Seeker's Armguard": (
        (
            "active",
            "Time Stop",
            "Put yourself in {{tip|stasis (buff)|stasis}} for {{fd|2.5}} "
            "seconds, rendering you {{tip|untargetable}} and "
            "{{tip|invulnerable}} for the duration but also unable to "
            "move, declare [[basic attack]]s, cast [[champion "
            "ability|abilities]], use [[summoner spell]]s, or [[active "
            "ability items|activate items]].",
        ),
    ),
    "Serylda's Grudge": (
        (
            "passive",
            "Bitter Cold",
            "Dealing [[ability damage]] to an enemy that is at or below "
            "{{as|50% of their '''maximum''' health}} {{tip|slow|slows}} "
            "them by 30% for 1 second.",
        ),
    ),
    "Verdant Barrier": (
        (
            "passive",
            "Annul",
            "Grants a {{tip|spell shield}} that blocks the next hostile "
            "ability (60 second cooldown, timer restarts upon taking damage "
            "from champions).",
        ),
    ),
    "Warden's Mail": (
        (
            "passive",
            "Rock Solid",
            "Every first incoming instance of {{tt|post-mitigation|Damage "
            "calculated after modifiers}} {{tip|basic damage}} per "
            "{{tip|cast instance}} is [[Damage modifier|reduced]] by 15, "
            "with a '''maximum''' of 20% reduction each.",
        ),
    ),
    "Youmuu's Ghostblade": (
        (
            "passive",
            "Haunt",
            "Gain {{as|{{rd|20|10}} '''bonus''' movement speed}} while "
            "out-of-combat with enemy champions for 3 seconds.",
        ),
        (
            "active",
            "Wraith Step",
            "Gain {{as|{{rd|20%|15%}} '''bonus''' movement speed}} and "
            "{{tip|ghosted|ghosting}} for {{rd|6|4}} seconds.",
        ),
    ),
    "Zhonya's Hourglass": (
        (
            "active",
            "Time Stop",
            "Put yourself in {{tip|stasis (buff)|stasis}} for {{fd|2.5}} "
            "seconds, rendering you {{tip|untargetable}} and "
            "{{tip|invulnerable}} for the duration but also unable to "
            "move, declare [[basic attack]]s, cast [[champion "
            "ability|abilities]], use [[summoner spell]]s, or [[active "
            "ability items|activate items]].",
        ),
    ),
}


def effect_fingerprint(
    item: dict[str, Any],
) -> tuple[tuple[str, str | None, str], ...]:
    """One item's current ``(kind, effect_name, full_text)`` triples.

    The certification suite diffs a cached item's live passive and active text
    against :data:`CERTIFIED_EFFECT_TEXT`.  An empty result means the cached
    item has no described passive or active.
    """
    fingerprint = []
    for kind, entry in effect_entries(item):
        raw_name = entry.get("name")
        name = str(raw_name) if raw_name is not None else None
        fingerprint.append((kind, name, effect_text(entry)))
    return tuple(fingerprint)
