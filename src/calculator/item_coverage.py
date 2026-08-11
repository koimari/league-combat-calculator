"""Fail-closed coverage labels for item mechanics used by BIS search.

Raw item stats are always sourced by :mod:`stats`.  This module answers the
separate question the optimiser needs: is every outgoing-damage mechanic on
this item represented by the current fight model?

Three declarations sit beside the classifiers and nothing in ``src`` reads
them: ``COVERAGE_EVIDENCE``, the typed claim behind every answer this module
gives; ``PRECEDENCE``, the classifier chain mirrored as data; and
``FRONTIER``, the claims that are not backed yet and the issues that track
them.  They live here rather than in a module of their own because a claim is
*about* the container two hundred lines above it, and a reader checking
whether the two agree should not have to hold two files open — pylint's line
ceiling is a proxy for "more than one responsibility", and this is one.
"""

# pylint: disable=too-many-lines

from collections.abc import Mapping
from typing import Any, Literal

from .coverage_evidence import (
    Absence,
    Claim,
    ClaimLane,
    ClaimStatus,
    EffectKey,
    Evidence,
    OptionSchema,
    PacketSource,
    PairedSides,
    PrecedenceRule,
    SourceRef,
    SubjectKind,
    Symbol,
    SymbolRole,
    TestRef,
    validate_claim_table,
    validate_precedence,
)
from .item_effects import ALLY_ITEM_EFFECTS, ITEM_EFFECTS, ITEM_INPUT_OPTIONS

ItemCoverageStatus = Literal[
    "modeled_effect",
    "modeled_state",
    "stats_only",
    "blocked",
    "review_pending",
]


# These mechanics can change TDD, casts, resources, or target durability.  The
# optimiser withholds them until the named mechanic has an explicit model.
_BLOCKED_REASONS: dict[str, str] = {}

# A calculation may expose a fully sourced combat sub-effect even while the
# optimiser must withhold the item because a separate progression/economy
# state is not simulated.  Keep this list narrow and explicit: the API should
# never silently turn an incomplete combat mechanic into a partial result.
_CALCULATION_ALLOWED_BLOCKED = frozenset()

# Items can have a registered damage packet while still carrying an
# unrepresented sibling passive or state transition.  Keep those items
# fail-closed until every fight-relevant child effect is covered; a name in
# ``ITEM_EFFECTS`` is not proof that the whole item is modelled.
_PARTIAL_BLOCKED_REASONS: dict[str, str] = {}

# These items have explicit scenario state and a single shared receipt ledger
# for their timed/progression branches.  They remain separate from ordinary
# ``ITEM_EFFECTS`` so an item cannot become optimizer-eligible merely because
# one static stat conversion was parsed.
_STATEFUL_MODELED_ITEMS: dict[str, str] = {
    "Ardent Censer": (
        "Sanctify is represented by the shared participant support ledger: an "
        "explicit heal or shield trigger schedules the sourced holder/ally "
        "attack-speed and on-hit-magic packets."
    ),
    "Bandlepipes": (
        "Fanfare is represented by the shared participant support ledger: an "
        "authored immobilize or slow schedules the sourced movement and "
        "holder/ally attack-speed packets."
    ),
    "Imperial Mandate": (
        "Command is represented on both sides of one authored immobilize "
        "event (a slow is not enough): the holder's pair engine prices its "
        "own post-immobilize amplifier, and the shared participant support "
        "ledger schedules the all-source amplifier for every other "
        "participant."
    ),
    "Actualizer": "Mana Made Real is represented by its bounded active window, resource multiplier, and cooldown-progress receipt.",
    "Archangel's Staff": "Awe and Manaflow state are represented by the bounded bonus-mana control and transformation receipt.",
    "Manamune": "Awe and Manaflow state are represented by the bounded bonus-mana control and transformation receipt.",
    "Whispering Circlet": "Harmony, Manaflow, and Diadem state are represented by the bounded bonus-mana control and transformation receipt.",
    "Winter's Approach": "Awe, Manaflow, and Fimbulwinter transformation state are represented by the bounded bonus-mana control and transformation receipt.",
    "Hubris": "Eminence's bounded starting stacks and timed window are represented by a sourced state receipt.",
    "Axiom Arc": "Flux's sourced takedown refund fraction and trigger window are represented by a terminal-state receipt.",
    "Endless Hunger": "Famine's conversion and Feast's bounded omnivamp window are represented by a sourced state receipt.",
    "Immortal Path": "Slay stacks, above-half damage amplification, and the bounded health-state receipt are represented; below-half recovery is applied by the ordered ledger.",
    "Catalyst of Aeons": "Eternity's pre-mitigation champion-damage mana restoration and capped per-cast healing are represented by the ordered resource and participant ledgers.",
    "Fimbulwinter": (
        "Awe's bonus-mana-to-health conversion and Everlasting's sourced "
        "post-control shield are represented by the ordered participant ledger; "
        "unreviewed crowd-control packets remain fail-closed."
    ),
    "Cull": (
        "Reap's authored minion-kill progression, completion payout, and on-hit "
        "health receipt share one explicit state/economy ledger."
    ),
    "Phage": (
        "Rage is emitted once per authored basic attack with the sourced melee or "
        "ranged movement-speed window."
    ),
    "Runic Compass": (
        "Support Quest, Shared Riches, and Ward charges are explicit state/economy "
        "and vision receipts."
    ),
    "Tear of the Goddess": (
        "Manaflow's bounded bonus-mana progression and minion-only Helping Hand "
        "boundary are explicit state receipts."
    ),
    "Umbral Glaive": (
        "Nightstalker's unseen-ready state gates a typed first-auto true-damage "
        "packet; Blackout remains a separate vision dimension."
    ),
    "World Atlas": (
        "Support Quest, Shared Riches, and Ward charges are explicit state/economy "
        "and vision receipts."
    ),
}


# Each entry was reviewed against the cached Wiki passive/active description.
# The effect does not add outgoing TDD in the calculator's current attacker
# event model; the item's ordinary stats still flow through stats.py.
_REVIEWED_STATS_ONLY: dict[str, str] = {
    "Banshee's Veil": "Annul is defensive spell protection.",
    "Doran's Ring": (
        "Drain restores mana first and converts to a sourced health packet only "
        "when the actor cannot gain mana; Helping Hand is minion-only."
    ),
    "Doran's Helm": (
        "Helping Hand's 5 bonus physical damage is restricted to minions; the "
        "full Wiki entry has no champion-facing sustain branch."
    ),
    "Doran's Shield": (
        "Enduring Focus's sourced missing-health regeneration is replayed after "
        "incoming champion damage; Helping Hand is minion-only."
    ),
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
    "Gunmetal Greaves": (
        "Noxian Gait's Riot-only movement branch remains explicitly out of scope "
        "because its magnitude and spacing input are not sourced; the boot's "
        "attack-speed and life-steal stats are still applied."
    ),
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
    "Armored Advance": (
        "Noxian Endurance grants a typed five-second physical shield after an "
        "authored champion physical-damage event; Plating reduces basic damage."
    ),
    "Chainlaced Crushers": (
        "Noxian Persistence grants a typed five-second magic shield after an "
        "authored champion magic-damage event."
    ),
    "Celestial Opposition": (
        "Blessing of the Mountain applies the sourced 35% champion-damage "
        "reduction and its two-second linger in the ordered ledger."
    ),
    "Bloodthirster": (
        "Ichorshield converts certified lifesteal excess into a persistent "
        "general shield capped by the sourced level maximum; an explicit "
        "starting state is accepted when supplied."
    ),
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
    "Doran's Shield": (
        "Enduring Focus's sourced missing-health regeneration is replayed after "
        "incoming champion damage."
    ),
    "Unending Despair": (
        "Anguish's every-four-second magic pulse and 250% post-mitigation "
        "self-heal are scheduled on the certified participant ledger for the "
        "selected enemy targets assumed within its 650-unit area."
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
        "the opposing participant's authored swing schedule when the selected "
        "roster pair is assumed within the enemy-only 700-unit aura."
    ),
    "Knight's Vow": (
        "Pledge redirects 14% of eligible pre-mitigation physical or magic damage "
        "to the explicitly selected Worthy holder, and Sacrifice heals the holder "
        "from post-mitigation Worthy damage while its sourced range and health "
        "gates are active."
    ),
    "Guardian Angel": (
        "Rebirth restores 50% base health four seconds after the first lethal "
        "packet; the coupled survival ledger applies it once when the event "
        "falls inside the selected window."
    ),
    "Seeker's Armguard": (
        "Time Stop is priced only from the explicit bounded active-seconds "
        "scenario input; item presence alone never assumes stasis."
    ),
    "Zhonya's Hourglass": (
        "Time Stop is priced only from the explicit bounded active-seconds "
        "scenario input; item presence alone never assumes stasis."
    ),
    "Locket of the Iron Solari": (
        "Devotion is represented by the shared participant support ledger: an "
        "explicit active_seconds input emits the sourced shield to the holder "
        "and selected teammates. Passive target calculations do not assume the "
        "active and therefore remain safe when no roster target is authored."
    ),
    "Mikael's Blessing": (
        "Purify is represented by the shared participant support ledger: an "
        "explicit active_seconds input emits the sourced cleanse/heal to the "
        "selected teammate. Passive target calculations do not invent a cast."
    ),
    "Redemption": (
        "Intervention is represented by the shared participant support ledger: "
        "an explicit active_seconds input schedules its delayed ally heal and "
        "enemy true-damage area packet for the selected roster. Passive target "
        "calculations do not invent the active."
    ),
    "Spectre's Cowl": (
        "The current full Wiki entry confirms that Incorporeal was removed in "
        "V14.6; the remaining target-relevant behavior is its sourced base "
        "health-regeneration stat, with no post-damage passive to schedule."
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
    "Fimbulwinter": (
        "Everlasting's 100 + 4.5% current-mana shield (1.8x with more than one "
        "nearby enemy) is scheduled after an authored immobilize, or a slow for "
        "a melee holder; the 20%-maximum-mana gate and eight-second cooldown "
        "are enforced, and unreviewed control packets are withheld."
    ),
    "Force of Nature": (
        "Steadfast stacks are scheduled from exact incoming champion magic-damage "
        "events, including expiry and the maximum-stack bonus resistance."
    ),
    "Jak'Sho, The Protean": (
        "Voidborn Resilience's one-stack-per-second combat state is scheduled "
        "from the exact event ledger and multiplies bonus resistances at max."
    ),
}

_TARGET_BLOCKED_REASONS: dict[str, str] = {
    "Guardian's Horn": "Legendary's flat incoming-damage reduction is not modelled.",
}

# Product-facing outcome dimensions for utility and non-TDD effects.  These
# labels are deliberately descriptive: they do not claim a combat formula is
# implemented.  A dimension with ``blocked`` coverage remains withheld rather
# than being silently presented as a stat-only item.
_UTILITY_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "Bandlepipes": ("ally_support", "stat_buff"),
    "Gunmetal Greaves": ("movement",),
    "Cull": ("economy", "progression", "on_hit"),
    "Phage": ("movement",),
    "Heartsteel": ("progression", "health_state"),
    "Hubris": ("progression", "stat_conversion"),
    "Axiom Arc": ("progression", "resource"),
    "Mejai's Soulstealer": ("progression", "stat_conversion"),
    "Rod of Ages": ("progression", "health_state", "resource"),
    "Solstice Sleigh": ("ally_support", "movement", "sustain"),
    "Swiftmarch": ("movement", "stat_conversion"),
    "World Atlas": ("economy", "quest", "ally_support", "vision"),
    "Runic Compass": ("economy", "quest", "ally_support", "vision"),
    "Tear of the Goddess": ("progression", "resource"),
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

# Concrete GitHub owners for source-backed gaps.  The full-entry audit exposes
# these references beside every withheld effect so a page review cannot end
# with an untracked prose note.  The umbrella #40 remains the release gate;
# child issues own the implementation family.
_REVIEW_ISSUE_REFS: dict[str, tuple[int, ...]] = {
    "Stridebreaker": (43,),
    "Voltaic Cyclosword": (43,),
    "Runaan's Hurricane": (43,),
    "Fimbulwinter": (44, 46),
    "Endless Hunger": (44, 45),
    "Whispering Circlet": (44,),
    "Archangel's Staff": (44,),
    "Manamune": (44,),
    "Winter's Approach": (44,),
    "Zeke's Convergence": (44,),
    "Axiom Arc": (44,),
    "Hubris": (44,),
    "Doran's Helm": (45,),
    "Actualizer": (45,),
    "Catalyst of Aeons": (45,),
    "Immortal Path": (45,),
    "Ardent Censer": (48,),
    "Bandlepipes": (48,),
    "Imperial Mandate": (48,),
    "Redemption": (48,),
    "Mikael's Blessing": (48,),
    "Locket of the Iron Solari": (46, 48),
}


def review_issue_refs(item_name: str) -> list[int]:
    """Return concrete child issues for a source-backed coverage gap."""
    return list(_REVIEW_ISSUE_REFS.get(str(item_name), (40,)))


def _has_described_effect(item: dict[str, Any]) -> bool:
    """Return whether cached Wiki data describes a passive or active."""
    return bool(item.get("passives") or item.get("active") or item.get("actives"))


def item_model_coverage(item: dict[str, Any]) -> dict[str, Any]:
    """Return the optimiser coverage classification for one resolved item."""
    name = str(item.get("name", ""))
    effect_type = ITEM_EFFECTS.get(name, {}).get("type")
    if name == "Death's Dance" and effect_type == "defensive_start":
        status: ItemCoverageStatus = "modeled_effect"
        reason = (
            "Ignore Pain's post-mitigation deferral ticks and Defy's takedown "
            "clear/heal are represented in the ordered participant timeline."
        )
    elif effect_type in {
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
            else (
                "Time Stop is priced only from the explicit bounded active-seconds "
                "scenario input; item presence alone never assumes stasis."
                if name in {"Zhonya's Hourglass", "Seeker's Armguard"}
                else "The represented mechanic changes defense, not outgoing TDD."
            )
        )
    elif name in _STATEFUL_MODELED_ITEMS:
        status = "modeled_state"
        reason = _STATEFUL_MODELED_ITEMS[name]
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
    elif name == "Gunmetal Greaves":
        # The boot's life steal is now pinned by the typed sustain receipt,
        # but Noxian Gait's Riot-only movement branch stays out of scope.
        status: ItemCoverageStatus = "modeled_effect"
        reason = (
            "Noxian Gait's Riot-only movement branch remains explicitly out of "
            "scope because its magnitude and spacing input are not sourced; the "
            "boot's attack-speed and life-steal stats are still applied."
        )
    elif name in ITEM_EFFECTS:
        status: ItemCoverageStatus = "modeled_effect"
        reason = "Damage-relevant effects are represented by the fight model."
    elif name in ITEM_INPUT_OPTIONS:
        status = "modeled_state"
        reason = "The item exposes its damage-relevant state as a scenario control."
    elif name in _REVIEWED_STATS_ONLY:
        status = "stats_only"
        reason = _REVIEWED_STATS_ONLY[name]
    elif not _has_described_effect(item):
        status = "stats_only"
        reason = "The item has no separate passive or active in the cached Wiki data."
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
        "review_issue_refs": (
            review_issue_refs(name) if status in {"blocked", "review_pending"} else []
        ),
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
        "review_issue_refs": (
            review_issue_refs(name) if status in {"blocked", "review_pending"} else []
        ),
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
    """Withhold a computed fight that cannot price a conditional defense.

    Conditional defenses are priced from the ordered damage ledger, so a
    coarse source would mis-time the trigger.  This runs after the fight so
    the error can name the exact uncertified sources instead of guessing.
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
        f"Result withheld: enemy item {conditional} needs a "
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
    items: list[dict[str, Any]],
    *,
    participant: str,
    allow_ally_effects: bool = False,
) -> None:
    """Reject a participant loadout whose outgoing effects are incomplete.

    Manual calculations and coupled roster fights are calculation entry paths,
    not only optimiser requests.  Reusing the same per-item contract here
    prevents an incomplete item from being accepted by ``/api/calculate``
    while remaining selectable in the browser.
    """
    for item in items:
        coverage = item_model_coverage(item)
        if (
            allow_ally_effects
            and coverage["status"] == "blocked"
            and coverage["name"] in ALLY_ITEM_EFFECTS
        ):
            # CP17's cross-participant packet layer is the authoritative
            # calculation path for support items.  They remain withheld from
            # ordinary BIS ranking until every holder-side sibling is
            # modeled, but an explicitly rostered support item is safe to
            # calculate because its item-team effects are timestamped and
            # fail closed when their trigger is absent.
            continue
        if coverage["calculation_eligible"]:
            continue
        raise ValueError(
            f"{participant} item {coverage['name']} cannot be used in a "
            f"calculation yet: {coverage['reason']}"
        )


# ── the claim corpus ──────────────────────────────────────────────────────

# Every answer this module gives used to be backed by a sentence.  One of them
# went on describing both halves of Imperial Mandate's Command long after only
# one half existed, and nothing checked the sentence against the code.  These
# are the claims that replace the sentences: one per ``(item, lane)`` for every
# entry in the seven non-empty containers above, one per rung of ``PRECEDENCE``,
# and one per item that emits a walk packet — each carrying typed evidence the
# resolution tier resolves against this tree on every ``pytest`` run.
#
# The *evidence* is authored and the assembly is mechanical, in that order and
# never the other way round.  A table that read its own evidence out of the
# registries it describes would agree with them by construction, which is the
# failure mode this module exists to catch; so every symbol path, packet
# source, option control, registry key, wiki revision and node id below is
# written down, and only the loop that turns them into ``Claim`` records is
# code.  ``Claim.status`` is a **pinned expectation, never an authority**: the
# classifier above stays the only answer to "what is this item's coverage",
# the resolution tier asserts the two agree for every cached item, and no
# ``src`` module reads the corpus at all.

# The umbrella issue every unrouted review gap falls back to.
_UMBRELLA_ISSUE = 40

# The two H4 reasons, written once.  Ten of the thirty-eight declared effect
# tags have no live handler branch, and which four are dead and which six are
# read only by this module's own claim is umbrella decision H4's to settle —
# so they sit on the frontier naming it rather than carrying an ``EffectTag``
# member that would have to name a handler that does not exist.
_H4_DEAD_TAG = (
    "Read nowhere in src/: blocked on umbrella decision H4, which owns whether "
    "the tag is deleted or given a handler. Tracked by #40."
)
_H4_SELF_REFERENTIAL_TAG = (
    "Read only by this module's own coverage claim while the behaviour is "
    "reached by item name: blocked on umbrella decision H4. Tracked by #40."
)

# Two items appear in ``_REVIEW_ISSUE_REFS`` and in no other container.  Their
# refs still need exactly one claim to carry them, so they get the claim their
# rung implies — ``ITEM_EFFECTS`` membership — rather than a home invented for
# the purpose.
_ISSUE_REF_ONLY_ITEMS: tuple[str, ...] = ("Voltaic Cyclosword", "Zeke's Convergence")

# Why an earlier rung means no cached item can reach a claim, keyed
# ``<subject>@<lane>``.  Twenty-nine container entries are decided above their
# own container, and four rungs are live code only a synthetic fixture enters;
# ``tests/coverage_resolver.shadow_report`` derives the same set from
# ``PRECEDENCE`` and the cached shop, and the suite asserts the two agree both
# ways.  A claim that is dead prose in a live-looking home is what this field
# exists to make visible, so no entry may be blank.
_SHADOWED_CLAIM_REASONS: Mapping[str, str] = {
    "Armored Advance@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Banshee's Veil@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Bloodthirster@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Celestial Opposition@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Chainlaced Crushers@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Death's Dance@attacker": (
        "attacker.deaths_dance_defensive_start decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Doran's Ring@attacker": (
        "attacker.item_effects_membership decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Doran's Shield@attacker": (
        "attacker.item_effects_membership decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Edge of Night@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Force of Nature@attacker": (
        "attacker.item_effects_membership decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Frozen Heart@attacker": (
        "attacker.item_effects_membership decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Guardian Angel@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Gunmetal Greaves@attacker": (
        "attacker.gunmetal_greaves_movement_gap decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Immortal Shieldbow@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Jak'Sho, The Protean@attacker": (
        "attacker.item_effects_membership decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Kaenic Rookern@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Knight's Vow@attacker": (
        "attacker.item_input_options_membership decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Locket of the Iron Solari@attacker": (
        "attacker.item_input_options_membership decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Maw of Malmortius@attacker": (
        "attacker.item_effects_membership decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Mercurial Scimitar@attacker": (
        "attacker.item_effects_membership decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Mikael's Blessing@attacker": (
        "attacker.item_input_options_membership decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Plated Steelcaps@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Protoplasm Harness@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Randuin's Omen@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Seeker's Armguard@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Shurelya's Battlesong@attacker": (
        "attacker.item_input_options_membership decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Spirit Visage@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Verdant Barrier@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "Zhonya's Hourglass@attacker": (
        "attacker.defensive_effect_types decides this item before the "
        "container is reached, so the container never speaks for it and no "
        "request can reach this claim."
    ),
    "attacker.blocked_reasons@attacker": (
        "_BLOCKED_REASONS is empty, so no cached item can reach this rung; "
        "the branch is proved on an empty registry and by a synthetic fixture "
        "rather than by any real build."
    ),
    "attacker.partial_blocked_reasons@attacker": (
        "_PARTIAL_BLOCKED_REASONS is empty, so no cached item can reach this "
        "rung; the branch is proved on an empty registry and by a synthetic "
        "fixture rather than by any real build."
    ),
    "attacker.unreviewed_fixture@attacker": (
        "review_pending is reserved for synthetic and unknown fixtures: every "
        "cached shop record carries an id or an icon and is blocked by the "
        "rung above, so no cached item reaches this one."
    ),
    "target.attacker_review_pending_passthrough@target": (
        "The passthrough fires only for an item the attacker lane calls "
        "review_pending, and no cached item is; it exists so a synthetic "
        "fixture cannot be target-relevant while being attacker-unreviewed."
    ),
}
_SOURCE_REFS: Mapping[str, tuple[str, int]] = {
    "Abyssal Mask": ("https://wiki.leagueoflegends.com/en-us/Abyssal_Mask", 3984960),
    "Armored Advance": (
        "https://wiki.leagueoflegends.com/en-us/Armored_Advance",
        4013702,
    ),
    "Banshee's Veil": (
        "https://wiki.leagueoflegends.com/en-us/Banshee's_Veil",
        3957919,
    ),
    "Blasting Wand": ("https://wiki.leagueoflegends.com/en-us/Blasting_Wand", 4022947),
    "Bloodthirster": ("https://wiki.leagueoflegends.com/en-us/Bloodthirster", 4025103),
    "Boots of Swiftness": (
        "https://wiki.leagueoflegends.com/en-us/Boots_of_Swiftness",
        4022244,
    ),
    "Celestial Opposition": (
        "https://wiki.leagueoflegends.com/en-us/Celestial_Opposition",
        4028004,
    ),
    "Chainlaced Crushers": (
        "https://wiki.leagueoflegends.com/en-us/Chainlaced_Crushers",
        4013705,
    ),
    "Chempunk Chainsword": (
        "https://wiki.leagueoflegends.com/en-us/Chempunk_Chainsword",
        4000212,
    ),
    "Cosmic Drive": ("https://wiki.leagueoflegends.com/en-us/Cosmic_Drive", 4005389),
    "Crimson Lucidity": (
        "https://wiki.leagueoflegends.com/en-us/Crimson_Lucidity",
        4030440,
    ),
    "Cryptbloom": ("https://wiki.leagueoflegends.com/en-us/Cryptbloom", 3989109),
    "Death's Dance": ("https://wiki.leagueoflegends.com/en-us/Death's_Dance", 4015383),
    "Diadem of Songs": (
        "https://wiki.leagueoflegends.com/en-us/Diadem_of_Songs",
        3993317,
    ),
    "Doran's Helm": ("https://wiki.leagueoflegends.com/en-us/Doran's_Helm", 4034679),
    "Doran's Ring": ("https://wiki.leagueoflegends.com/en-us/Doran's_Ring", 4026377),
    "Doran's Shield": (
        "https://wiki.leagueoflegends.com/en-us/Doran's_Shield",
        4026378,
    ),
    "Dream Maker": ("https://wiki.leagueoflegends.com/en-us/Dream_Maker", 4030400),
    "Echoes of Helia": (
        "https://wiki.leagueoflegends.com/en-us/Echoes_of_Helia",
        4046489,
    ),
    "Edge of Night": ("https://wiki.leagueoflegends.com/en-us/Edge_of_Night", 4013389),
    "Executioner's Calling": (
        "https://wiki.leagueoflegends.com/en-us/Executioner's_Calling",
        3985491,
    ),
    "Force of Nature": (
        "https://wiki.leagueoflegends.com/en-us/Force_of_Nature",
        4016272,
    ),
    "Frozen Heart": ("https://wiki.leagueoflegends.com/en-us/Frozen_Heart", 4025104),
    "Gluttonous Greaves": (
        "https://wiki.leagueoflegends.com/en-us/Gluttonous_Greaves",
        4030444,
    ),
    "Guardian Angel": (
        "https://wiki.leagueoflegends.com/en-us/Guardian_Angel",
        4001358,
    ),
    "Gunmetal Greaves": (
        "https://wiki.leagueoflegends.com/en-us/Gunmetal_Greaves",
        4013706,
    ),
    "Gustwalker Hatchling": (
        "https://wiki.leagueoflegends.com/en-us/Gustwalker_Hatchling",
        4041864,
    ),
    "Immortal Shieldbow": (
        "https://wiki.leagueoflegends.com/en-us/Immortal_Shieldbow",
        4030401,
    ),
    "Ionian Boots of Lucidity": (
        "https://wiki.leagueoflegends.com/en-us/Ionian_Boots_of_Lucidity",
        4022246,
    ),
    "Jak'Sho, The Protean": (
        "https://wiki.leagueoflegends.com/en-us/Jak'Sho,_The_Protean",
        3984950,
    ),
    "Kaenic Rookern": (
        "https://wiki.leagueoflegends.com/en-us/Kaenic_Rookern",
        3984971,
    ),
    "Knight's Vow": ("https://wiki.leagueoflegends.com/en-us/Knight's_Vow", 4023793),
    "Locket of the Iron Solari": (
        "https://wiki.leagueoflegends.com/en-us/Locket_of_the_Iron_Solari",
        4022957,
    ),
    "Lost Chapter": ("https://wiki.leagueoflegends.com/en-us/Lost_Chapter", 3989340),
    "Maw of Malmortius": (
        "https://wiki.leagueoflegends.com/en-us/Maw_of_Malmortius",
        3984424,
    ),
    "Mercurial Scimitar": (
        "https://wiki.leagueoflegends.com/en-us/Mercurial_Scimitar",
        3984461,
    ),
    "Mikael's Blessing": (
        "https://wiki.leagueoflegends.com/en-us/Mikael's_Blessing",
        3984364,
    ),
    "Moonstone Renewer": (
        "https://wiki.leagueoflegends.com/en-us/Moonstone_Renewer",
        4022988,
    ),
    "Morellonomicon": (
        "https://wiki.leagueoflegends.com/en-us/Morellonomicon",
        3985490,
    ),
    "Mortal Reminder": (
        "https://wiki.leagueoflegends.com/en-us/Mortal_Reminder",
        4023637,
    ),
    "Mosstomper Seedling": (
        "https://wiki.leagueoflegends.com/en-us/Mosstomper_Seedling",
        4041862,
    ),
    "Oblivion Orb": ("https://wiki.leagueoflegends.com/en-us/Oblivion_Orb", 3985489),
    "Phantom Dancer": (
        "https://wiki.leagueoflegends.com/en-us/Phantom_Dancer",
        4047301,
    ),
    "Plated Steelcaps": (
        "https://wiki.leagueoflegends.com/en-us/Plated_Steelcaps",
        4022248,
    ),
    "Protoplasm Harness": (
        "https://wiki.leagueoflegends.com/en-us/Protoplasm_Harness",
        4045616,
    ),
    "Quicksilver Sash": (
        "https://wiki.leagueoflegends.com/en-us/Quicksilver_Sash",
        3729899,
    ),
    "Randuin's Omen": (
        "https://wiki.leagueoflegends.com/en-us/Randuin's_Omen",
        4021798,
    ),
    "Refillable Potion": (
        "https://wiki.leagueoflegends.com/en-us/Refillable_Potion",
        3971312,
    ),
    "Rylai's Crystal Scepter": (
        "https://wiki.leagueoflegends.com/en-us/Rylai's_Crystal_Scepter",
        3984377,
    ),
    "Scorchclaw Pup": (
        "https://wiki.leagueoflegends.com/en-us/Scorchclaw_Pup",
        4041863,
    ),
    "Seeker's Armguard": (
        "https://wiki.leagueoflegends.com/en-us/Seeker's_Armguard",
        3837259,
    ),
    "Serylda's Grudge": (
        "https://wiki.leagueoflegends.com/en-us/Serylda's_Grudge",
        3984392,
    ),
    "Shurelya's Battlesong": (
        "https://wiki.leagueoflegends.com/en-us/Shurelya's_Battlesong",
        3984368,
    ),
    "Solstice Sleigh": (
        "https://wiki.leagueoflegends.com/en-us/Solstice_Sleigh",
        4028003,
    ),
    "Spirit Visage": ("https://wiki.leagueoflegends.com/en-us/Spirit_Visage", 4016166),
    "Umbral Glaive": ("https://wiki.leagueoflegends.com/en-us/Umbral_Glaive", 4013390),
    "Verdant Barrier": (
        "https://wiki.leagueoflegends.com/en-us/Verdant_Barrier",
        3957920,
    ),
    "Youmuu's Ghostblade": (
        "https://wiki.leagueoflegends.com/en-us/Youmuu's_Ghostblade",
        4013388,
    ),
    "Zhonya's Hourglass": (
        "https://wiki.leagueoflegends.com/en-us/Zhonya's_Hourglass",
        3902922,
    ),
}

_ATTACKER_STATE_HOMES: Mapping[str, tuple[str, str]] = {
    "Actualizer": (
        "item_effects.item_state_receipts",
        "option:mana_made_real_active_seconds",
    ),
    "Archangel's Staff": (
        "item_effects.item_state_receipts",
        "option:manaflow_bonus_mana",
    ),
    "Ardent Censer": (
        "item_support_effects.derive_item_support_effects",
        "packet:Ardent Censer — Sanctify",
    ),
    "Axiom Arc": (
        "item_effects.axiom_arc_ultimate_refund_fraction",
        "key:ultimate_refund_base_ratio",
    ),
    "Bandlepipes": (
        "item_support_effects.derive_item_support_effects",
        "packet:Bandlepipes — Fanfare",
    ),
    "Catalyst of Aeons": (
        "item_effects.item_state_receipts",
        "key:mana_spent_heal_ratio",
    ),
    "Cull": ("item_effects.item_state_receipts", "option:reap_minion_kills"),
    "Endless Hunger": (
        "item_effects.item_state_receipts",
        "option:feast_active_seconds",
    ),
    "Fimbulwinter": (
        "item_support_effects.derive_item_support_effects",
        "packet:Fimbulwinter — Everlasting",
    ),
    "Hubris": ("item_effects.item_state_receipts", "option:eminence_stacks"),
    "Immortal Path": ("item_effects.item_state_receipts", "option:slay_stacks"),
    "Imperial Mandate": (
        "item_support_effects.derive_item_support_effects",
        "packet:Imperial Mandate — Command",
    ),
    "Manamune": ("item_effects.item_state_receipts", "option:manaflow_bonus_mana"),
    "Phage": (
        "item_support_effects.derive_item_support_effects",
        "packet:Phage — Rage",
    ),
    "Runic Compass": ("item_effects.item_state_receipts", "option:shared_riches_gold"),
    "Tear of the Goddess": (
        "item_effects.item_state_receipts",
        "option:manaflow_bonus_mana",
    ),
    "Umbral Glaive": ("item_effects.item_state_receipts", "option:nightstalker_ready"),
    "Whispering Circlet": (
        "item_effects.item_state_receipts",
        "option:manaflow_bonus_mana",
    ),
    "Winter's Approach": (
        "item_effects.item_state_receipts",
        "option:manaflow_bonus_mana",
    ),
    "World Atlas": ("item_effects.item_state_receipts", "option:shared_riches_gold"),
}

_TARGET_MODELED_IMPLS: Mapping[str, str] = {
    "Armored Advance": "defensive_effects.resolve_starting_defenses",
    "Banshee's Veil": "defensive_effects.resolve_starting_defenses",
    "Bloodthirster": "defensive_effects.resolve_starting_defenses",
    "Bramble Vest": "interpreters.reactive.thorns_effects",
    "Celestial Opposition": "defensive_effects.resolve_starting_defenses",
    "Chainlaced Crushers": "defensive_effects.resolve_starting_defenses",
    "Cull": "item_support_effects.derive_item_support_effects",
    "Doran's Shield": "survival.transitions.schedule_doran_shield_recovery",
    "Dusk and Dawn": "damage._add_spellblade_damage",
    "Edge of Night": "defensive_effects.resolve_starting_defenses",
    "Frozen Heart": "roster_composition.target_overrides",
    "Guardian Angel": "defensive_effects.resolve_starting_defenses",
    "Kaenic Rookern": "defensive_effects.resolve_starting_defenses",
    "Knight's Vow": "item_support_effects.schedule_knights_vow",
    "Locket of the Iron Solari": "item_support_effects.derive_item_support_effects",
    "Mikael's Blessing": "item_support_effects.derive_item_support_effects",
    "Plated Steelcaps": "defensive_effects.resolve_starting_defenses",
    "Randuin's Omen": "defensive_effects.resolve_starting_defenses",
    "Redemption": "item_support_effects.derive_item_support_effects",
    "Seeker's Armguard": "defensive_effects.resolve_starting_defenses",
    "Spectre's Cowl": "stats.get_item_stats",
    "Spirit Visage": "defensive_effects.resolve_starting_defenses",
    "Sundered Sky": "damage._add_first_auto_healing",
    "Thornmail": "interpreters.reactive.thorns_effects",
    "Unending Despair": "damage._add_burn_damage",
    "Verdant Barrier": "defensive_effects.resolve_starting_defenses",
    "Warden's Mail": "defensive_effects.resolve_starting_defenses",
    "Warmog's Armor": "participant_timeline._warmog_heart_tick_events",
    "Zhonya's Hourglass": "defensive_effects.resolve_starting_defenses",
}

_TARGET_CERTIFIED_IMPLS: Mapping[str, str] = {
    "Fimbulwinter": "item_support_effects.derive_item_support_effects",
    "Force of Nature": "survival.transitions.update_combat_state",
    "Hexdrinker": "interpreters.threshold_defense._lifeline_shield",
    "Immortal Shieldbow": "interpreters.threshold_defense._lifeline_shield",
    "Jak'Sho, The Protean": "survival.transitions.update_combat_state",
    "Maw of Malmortius": "interpreters.threshold_defense._lifeline_shield",
    "Protoplasm Harness": "interpreters.threshold_defense._protoplasm",
    "Seraph's Embrace": "interpreters.threshold_defense._lifeline_shield",
    "Sterak's Gage": "interpreters.threshold_defense._lifeline_shield",
}

_UTILITY_HOMES: Mapping[str, tuple[str, str]] = {
    "Axiom Arc": (
        "item_effects.axiom_arc_ultimate_refund_fraction",
        "key:ultimate_refund_base_ratio",
    ),
    "Bandlepipes": (
        "item_support_effects.derive_item_support_effects",
        "packet:Bandlepipes — Fanfare",
    ),
    "Banshee's Veil": ("defensive_effects.resolve_starting_defenses", "effects"),
    "Boots of Swiftness": ("", "source"),
    "Cosmic Drive": ("", "source"),
    "Cull": ("item_support_effects.derive_item_support_effects", "packet:Cull — Reap"),
    "Edge of Night": ("defensive_effects.resolve_starting_defenses", "effects"),
    "Force of Nature": ("survival.transitions.update_combat_state", "effects"),
    "Frozen Heart": ("roster_composition.target_overrides", "effects"),
    "Guardian Angel": ("defensive_effects.resolve_starting_defenses", "effects"),
    "Gunmetal Greaves": ("", "source"),
    "Heartsteel": ("item_effects.item_state_receipts", "option:bonus_health"),
    "Horizon Focus": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Hubris": ("item_effects.item_state_receipts", "option:eminence_stacks"),
    "Locket of the Iron Solari": (
        "item_support_effects.derive_item_support_effects",
        "packet:Locket of the Iron Solari — Devotion",
    ),
    "Mejai's Soulstealer": ("item_effects.item_state_receipts", "option:glory_stacks"),
    "Mercurial Scimitar": ("", "source"),
    "Mikael's Blessing": (
        "item_support_effects.derive_item_support_effects",
        "packet:Mikael's Blessing — Purify",
    ),
    "Phage": (
        "item_support_effects.derive_item_support_effects",
        "packet:Phage — Rage",
    ),
    "Phantom Dancer": ("", "source"),
    "Profane Hydra": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Randuin's Omen": ("defensive_effects.resolve_starting_defenses", "effects"),
    "Rapid Firecannon": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Ravenous Hydra": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Redemption": (
        "item_support_effects.derive_item_support_effects",
        "packet:Redemption — Intervention",
    ),
    "Rod of Ages": ("item_effects.item_state_receipts", "option:timeless_stacks"),
    "Runaan's Hurricane": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Runic Compass": (
        "item_support_effects.derive_item_support_effects",
        "packet:{} — Shared Riches",
    ),
    "Rylai's Crystal Scepter": ("", "source"),
    "Serylda's Grudge": ("", "source"),
    "Shurelya's Battlesong": (
        "item_support_effects.derive_item_support_effects",
        "packet:Shurelya's Battlesong — Inspiring Speech",
    ),
    "Solstice Sleigh": (
        "item_support_effects.derive_item_support_effects",
        "packet:Solstice Sleigh — Going Sledding",
    ),
    "Statikk Shiv": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Stormrazor": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Stridebreaker": (
        "item_support_effects.derive_item_support_effects",
        "packet:Stridebreaker — Breaking Shockwave",
    ),
    "Swiftmarch": ("item_effects.swiftmarch_adaptive_force", "effects"),
    "Tear of the Goddess": (
        "item_effects.item_state_receipts",
        "option:manaflow_bonus_mana",
    ),
    "The Collector": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Titanic Hydra": ("item_effects._resolve_damage_effects_uncached", "effects"),
    "Umbral Glaive": ("", "source"),
    "World Atlas": (
        "item_support_effects.derive_item_support_effects",
        "packet:{} — Shared Riches",
    ),
    "Youmuu's Ghostblade": ("", "source"),
    "Zhonya's Hourglass": ("defensive_effects.resolve_starting_defenses", "effects"),
}
# Which lane's claim carries an item's tracked review issues.  ``review_issue_refs``
# publishes one list per item and a claim's ``issue_refs`` has to be that list, so
# exactly one claim per item may carry it; this names which.  A negative claim
# carries its refs on its ``Absence`` instead, which is why no lane below is one.
_ISSUE_REF_LANES: Mapping[str, ClaimLane] = {
    "Actualizer": "attacker",
    "Archangel's Staff": "attacker",
    "Ardent Censer": "attacker",
    "Axiom Arc": "attacker",
    "Bandlepipes": "attacker",
    "Catalyst of Aeons": "attacker",
    "Doran's Helm": "attacker",
    "Endless Hunger": "attacker",
    "Fimbulwinter": "attacker",
    "Hubris": "attacker",
    "Immortal Path": "attacker",
    "Imperial Mandate": "attacker",
    "Locket of the Iron Solari": "target",
    "Manamune": "attacker",
    "Mikael's Blessing": "target",
    "Redemption": "target",
    "Runaan's Hurricane": "utility",
    "Stridebreaker": "utility",
    "Voltaic Cyclosword": "attacker",
    "Whispering Circlet": "attacker",
    "Winter's Approach": "attacker",
    "Zeke's Convergence": "attacker",
}

# The walk packets an item emits, the builder that emits them, and one focused
# test that exercises the behaviour.  A packet whose source the builder composes
# with an f-string is written the way the builder renders it -- ``{} — Ward``,
# not ``World Atlas — Ward`` -- because the interpolated part is not in the
# source at all and a member spelling the item name there could never resolve.  Seven more items own a walk packet and have
# no such test; they are on ``FRONTIER`` rather than here, because a claim backed
# by "some test file mentions this string" is the prose this corpus replaces.
_SUPPORT_PACKET_CLAIMS: Mapping[str, tuple[str, tuple[str, ...], str]] = {
    "Abyssal Mask": (
        "item_support_effects.derive_item_support_effects",
        ("Abyssal Mask — Unmake",),
        "tests/test_item_support_effects.py::TestAbyssalMaskOwnerHandshake"
        "::test_unmake_declares_split",
    ),
    "Ardent Censer": (
        "item_support_effects.derive_item_support_effects",
        ("Ardent Censer — Sanctify",),
        "tests/test_item_support_effects.py"
        "::test_ardent_and_moonstone_use_the_authored_heal_or_shield_target",
    ),
    "Bandlepipes": (
        "item_support_effects.derive_item_support_effects",
        ("Bandlepipes — Fanfare",),
        "tests/test_item_support_effects.py"
        "::test_cc_only_packets_require_an_authored_immobilize_marker",
    ),
    "Black Cleaver": (
        "item_support_effects.derive_item_support_effects",
        ("Black Cleaver — Carve",),
        "tests/test_item_support_effects.py"
        "::test_cross_participant_debuffs_are_typed_and_triggered_by_holder_packets",
    ),
    "Bloodletter's Curse": (
        "item_support_effects.derive_item_support_effects",
        ("Bloodletter's Curse — Vile Decay",),
        "tests/test_item_support_effects.py"
        "::test_cross_participant_debuffs_are_typed_and_triggered_by_holder_packets",
    ),
    "Bloodsong": (
        "item_support_effects.derive_item_support_effects",
        ("Bloodsong — Expose Weakness",),
        "tests/test_item_support_effects.py"
        "::test_cross_participant_debuffs_are_typed_and_triggered_by_holder_packets",
    ),
    "Cryptbloom": (
        "item_support_effects.derive_item_support_effects",
        ("Cryptbloom — Life From Death",),
        "tests/test_item_support_effects.py"
        "::test_cryptbloom_requires_an_explicit_takedown_receipt",
    ),
    "Cull": (
        "item_support_effects.derive_item_support_effects",
        ("Cull — Reap",),
        "tests/test_item_support_effects.py"
        "::test_cp20_progression_items_emit_typed_economy_vision_and_movement_receipts",
    ),
    "Dream Maker": (
        "item_support_effects.derive_item_support_effects",
        ("Dream Maker — Blue Dream Bubble",),
        "tests/test_item_support_effects.py::TestCrossParticipantAuthorities"
        "::test_dream_maker_is_a_producer",
    ),
    "Fimbulwinter": (
        "item_support_effects.derive_item_support_effects",
        ("Fimbulwinter — Everlasting",),
        "tests/test_item_support_effects.py"
        "::test_fimbulwinter_everlasting_uses_current_mana_and_nearby_enemy_multiplier",
    ),
    "Imperial Mandate": (
        "item_support_effects.derive_item_support_effects",
        ("Imperial Mandate — Command",),
        "tests/test_item_support_effects.py"
        "::test_command_requires_an_immobilize_not_a_slow",
    ),
    "Knight's Vow": (
        "item_support_effects.schedule_knights_vow",
        ("Knight's Vow — Sacrifice",),
        "tests/test_item_support_effects.py"
        "::test_knights_vow_attaches_typed_redirect_and_holder_heal_receipts",
    ),
    "Moonstone Renewer": (
        "item_support_effects.derive_item_support_effects",
        ("Moonstone Renewer — Starlit Grace",),
        "tests/test_item_support_effects.py"
        "::test_ardent_and_moonstone_use_the_authored_heal_or_shield_target",
    ),
    "Phage": (
        "item_support_effects.derive_item_support_effects",
        ("Phage — Rage",),
        "tests/test_item_support_effects.py"
        "::test_cp20_progression_items_emit_typed_economy_vision_and_movement_receipts",
    ),
    "Redemption": (
        "item_support_effects.derive_item_support_effects",
        ("Redemption — Intervention",),
        "tests/test_participant_timeline.py"
        "::test_redemption_active_emits_sourced_area_true_damage_and_heal_packets",
    ),
    "Solstice Sleigh": (
        "item_support_effects.derive_item_support_effects",
        ("Solstice Sleigh — Going Sledding",),
        "tests/test_item_support_effects.py"
        "::test_sourced_cc_packets_include_holder_movement_and_solstice_both_recipients",
    ),
    "Staff of Flowing Water": (
        "item_support_effects.derive_item_support_effects",
        ("Staff of Flowing Water — Rapids",),
        "tests/test_app.py"
        "::test_enabled_ally_staff_buff_changes_attacker_stats_and_damage",
    ),
    "World Atlas": (
        "item_support_effects.derive_item_support_effects",
        ("{} — Shared Riches", "{} — Ward"),
        "tests/test_item_support_effects.py"
        "::test_cp20_progression_items_emit_typed_economy_vision_and_movement_receipts",
    ),
}

# The five mechanics Phase 2 declares ``SPLIT``, by holder.  The claim names the
# mechanic and the handshake; the registry is what says both halves exist and
# pair back, which is the check the incident's hand list could not perform.
_SPLIT_MECHANICS: Mapping[str, str] = {
    "Abyssal Mask": "abyssal_mask.unmake",
    "Black Cleaver": "black_cleaver.carve",
    "Bloodletter's Curse": "bloodletters_curse.vile_decay",
    "Bloodsong": "bloodsong.expose_weakness",
    "Imperial Mandate": "imperial_mandate.command",
}


def _test_ref(function: str, subject: str) -> TestRef:
    """The parametrized node in the claim suite that exercises *subject*.

    The node id is composed rather than written out once per claim: the
    parametrization id is the subject verbatim, so composing it keeps two
    hundred claims from carrying two hundred near-identical strings, and the
    resolver still has to find the node in what pytest actually collected.
    """
    return TestRef(node_id=f"tests/test_coverage_claims.py::{function}[{subject}]")


def _source_ref(item: str) -> SourceRef:
    """The wiki revision the item's full-entry review was read from."""
    url, revision_id = _SOURCE_REFS[item]
    return SourceRef(url=url, revision_id=revision_id)


def _state_home(item: str, home: str) -> Evidence:
    """The member naming where a ``modeled_state`` claim's state comes from.

    Three spellings, one per route the classifier reaches that status by: an
    ``option:`` control, a ``packet:`` the ledger schedules, or a ``key:`` the
    engine reads out of the registry.
    """
    kind, _, value = home.partition(":")
    if kind == "option":
        return OptionSchema(item=item, option=value)
    if kind == "packet":
        return PacketSource(source=value)
    return EffectKey(registry="ITEM_EFFECTS", item=item, key=value)


def _issue_refs(item: str, lane: ClaimLane) -> tuple[int, ...]:
    """The tracked review issues, on the one lane declared to carry them."""
    if _ISSUE_REF_LANES.get(item) != lane:
        return ()
    return tuple(_REVIEW_ISSUE_REFS[item])


def _unreachable_reason(item: str, lane: ClaimLane) -> str:
    """Why an earlier rung means no cached item reaches this claim."""
    return _SHADOWED_CLAIM_REASONS.get(f"{item}@{lane}", "")


def _attacker_state_claim(item: str) -> Claim:
    """One ``_STATEFUL_MODELED_ITEMS`` entry: state, and where it comes from."""
    path, home = _ATTACKER_STATE_HOMES[item]
    role: SymbolRole = (
        "walk_packet_builder" if home.startswith("packet:") else "value_accessor"
    )
    return Claim(
        subject_kind="item",
        subject=item,
        lane="attacker",
        status="modeled_state",
        evidence=(
            Symbol(path=path, role=role),
            _state_home(item, home),
            _test_ref(
                "test_a_stateful_item_supplies_its_state_from_a_named_home", item
            ),
        ),
        dimensions=(),
        issue_refs=_issue_refs(item, "attacker"),
        unreachable_reason=_unreachable_reason(item, "attacker"),
    )


def _stats_only_claim(item: str) -> Claim:
    """One ``_REVIEWED_STATS_ONLY`` entry: a review, and the revision it read."""
    return Claim(
        subject_kind="item",
        subject=item,
        lane="attacker",
        status="stats_only",
        evidence=(
            _source_ref(item),
            _test_ref("test_a_reviewed_stats_only_item_adds_no_outgoing_damage", item),
        ),
        dimensions=(),
        issue_refs=_issue_refs(item, "attacker"),
        unreachable_reason=_unreachable_reason(item, "attacker"),
    )


def _item_effects_claim(item: str) -> Claim:
    """An ``ITEM_EFFECTS`` member whose refs need a home of their own."""
    return Claim(
        subject_kind="item",
        subject=item,
        lane="attacker",
        status="modeled_effect",
        evidence=(
            Symbol(
                path="item_effects._resolve_damage_effects_uncached", role="tag_handler"
            ),
            _test_ref(
                "test_an_item_effects_member_names_a_dispatched_or_frontiered_tag", item
            ),
        ),
        dimensions=(),
        issue_refs=_issue_refs(item, "attacker"),
        unreachable_reason=_unreachable_reason(item, "attacker"),
    )


def _target_modeled_claim(item: str) -> Claim:
    """One ``_TARGET_MODELED_REASONS`` entry and the code that admits it."""
    return Claim(
        subject_kind="item",
        subject=item,
        lane="target",
        status="modeled",
        evidence=(
            Symbol(path=_TARGET_MODELED_IMPLS[item], role="walk_packet_builder"),
            _test_ref(
                "test_a_target_modeled_item_is_admitted_by_the_target_model", item
            ),
        ),
        dimensions=(),
        issue_refs=_issue_refs(item, "target"),
        unreachable_reason=_unreachable_reason(item, "target"),
    )


def _target_certified_claim(item: str) -> Claim:
    """One conditional defense, plus the guard that withholds an uncertified fight."""
    return Claim(
        subject_kind="item",
        subject=item,
        lane="target",
        status="modeled_event_certified",
        evidence=(
            Symbol(path=_TARGET_CERTIFIED_IMPLS[item], role="walk_packet_builder"),
            Symbol(
                path="item_coverage.require_certified_target_timeline",
                role="certification_guard",
            ),
            _test_ref(
                "test_a_target_event_certified_item_needs_a_certified_timeline", item
            ),
        ),
        dimensions=(),
        issue_refs=_issue_refs(item, "target"),
        unreachable_reason=_unreachable_reason(item, "target"),
    )


def _target_blocked_claim(item: str) -> Claim:
    """The one withheld target mechanic: a reason and the issue tracking it."""
    return Claim(
        subject_kind="item",
        subject=item,
        lane="target",
        status="blocked",
        evidence=(
            Absence(
                reason=_TARGET_BLOCKED_REASONS[item],
                issue_refs=tuple(review_issue_refs(item)),
            ),
        ),
        dimensions=(),
        issue_refs=(),
        unreachable_reason=_unreachable_reason(item, "target"),
    )


def _utility_claim(item: str) -> Claim:
    """One ``_UTILITY_DIMENSIONS`` entry and the home of what the model prices.

    A utility claim is about outcome *dimensions*, and the model prices some
    of them and none of others.  ``modeled_effect`` and ``modeled_state`` name
    the home of the dimension it does price; ``stats_only`` is the honest
    answer where it prices none of them, and then the claim cites the review
    that says so rather than pointing at code that is about something else.
    """
    path, home = _UTILITY_HOMES[item]
    dimensions = tuple(_UTILITY_DIMENSIONS[item])
    node = _test_ref("test_a_utility_item_publishes_its_declared_dimensions", item)
    refs = _issue_refs(item, "utility")
    if home == "source":
        return Claim(
            subject_kind="item",
            subject=item,
            lane="utility",
            status="stats_only",
            evidence=(_source_ref(item), node),
            dimensions=dimensions,
            issue_refs=refs,
            unreachable_reason="",
        )
    if home == "effects":
        return Claim(
            subject_kind="item",
            subject=item,
            lane="utility",
            status="modeled_effect",
            evidence=(Symbol(path=path, role="tag_handler"), node),
            dimensions=dimensions,
            issue_refs=refs,
            unreachable_reason="",
        )
    role: SymbolRole = (
        "walk_packet_builder" if home.startswith("packet:") else "value_accessor"
    )
    return Claim(
        subject_kind="item",
        subject=item,
        lane="utility",
        status="modeled_state",
        evidence=(
            Symbol(path=path, role=role),
            _state_home(item, home),
            node,
        ),
        dimensions=dimensions,
        issue_refs=refs,
        unreachable_reason="",
    )


def _support_packet_claim(item: str) -> Claim:
    """One holder's walk packets, its builder, and its dual-sided handshake."""
    impl, packets, node_id = _SUPPORT_PACKET_CLAIMS[item]
    mechanic = _SPLIT_MECHANICS.get(item)
    sides = (
        (PairedSides(mechanic=mechanic, owner_policy="owner_skips_holder"),)
        if mechanic
        else ()
    )
    return Claim(
        subject_kind="item",
        subject=item,
        lane="support_packet",
        status="modeled_effect",
        evidence=(
            Symbol(path=impl, role="walk_packet_builder"),
            *(PacketSource(source=packet) for packet in packets),
            *sides,
            TestRef(node_id=node_id),
        ),
        dimensions=(),
        issue_refs=(),
        unreachable_reason="",
    )


def _rung_ref(rule_id: str) -> TestRef:
    """The node that runs one rung against the live classifier."""
    return _test_ref("test_a_precedence_rung_yields_its_declared_status", rule_id)


def _rule_claim(
    rule_id: str,
    lane: ClaimLane,
    status: ClaimStatus,
    evidence: tuple[Evidence, ...],
) -> Claim:
    """One claim about one rung of the chain."""
    return Claim(
        subject_kind="rule",
        subject=rule_id,
        lane=lane,
        status=status,
        evidence=evidence,
        dimensions=(),
        issue_refs=(),
        unreachable_reason=_unreachable_reason(rule_id, lane),
    )


def _unreachable_rung_claim(
    rule_id: str, lane: ClaimLane, status: ClaimStatus
) -> Claim:
    """A rung no cached item enters: a refusal, its reason and its issue.

    ``blocked`` and ``review_pending`` take exactly one ``Absence`` and no
    positive evidence, which is why these four carry no ``TestRef`` — the
    rung's own parametrized node still runs, and still asserts that nothing
    reaches it (D-26's emptiness half).
    """
    return _rule_claim(
        rule_id,
        lane,
        status,
        (
            Absence(
                reason=_unreachable_reason(rule_id, lane),
                issue_refs=(_UMBRELLA_ISSUE,),
            ),
        ),
    )


# One claim per rung of ``PRECEDENCE``, in its order.  A rung is where a status
# comes from, so its claim is about the *mechanism* the rung routes to — and the
# five rungs whose membership is recomputed from ``data/`` on every call carry
# their population's backing instead of a per-item claim each, which is the
# whole reason a claim's subject may be a rule.
_RULE_CLAIMS: tuple[Claim, ...] = (
    _rule_claim(
        "attacker.deaths_dance_defensive_start",
        "attacker",
        "modeled_effect",
        (
            Symbol(
                path="survival.transitions.trigger_defy", role="walk_packet_builder"
            ),
            _rung_ref("attacker.deaths_dance_defensive_start"),
        ),
    ),
    _rule_claim(
        "attacker.defensive_effect_types",
        "attacker",
        "stats_only",
        (
            _source_ref("Guardian Angel"),
            _rung_ref("attacker.defensive_effect_types"),
        ),
    ),
    _rule_claim(
        "attacker.stateful_modeled_items",
        "attacker",
        "modeled_state",
        (
            Symbol(path="item_effects.item_state_receipts", role="value_accessor"),
            OptionSchema(item="Hubris", option="eminence_stacks"),
            _rung_ref("attacker.stateful_modeled_items"),
        ),
    ),
    _unreachable_rung_claim("attacker.partial_blocked_reasons", "attacker", "blocked"),
    _rule_claim(
        "attacker.heartsteel_state_option",
        "attacker",
        "modeled_state",
        (
            Symbol(path="item_effects.item_state_receipts", role="value_accessor"),
            OptionSchema(item="Heartsteel", option="bonus_health"),
            _rung_ref("attacker.heartsteel_state_option"),
        ),
    ),
    _rule_claim(
        "attacker.rod_of_ages_state_option",
        "attacker",
        "modeled_state",
        (
            Symbol(path="item_effects.item_state_receipts", role="value_accessor"),
            OptionSchema(item="Rod of Ages", option="timeless_stacks"),
            _rung_ref("attacker.rod_of_ages_state_option"),
        ),
    ),
    _rule_claim(
        "attacker.overlords_bloodmail_state_option",
        "attacker",
        "modeled_state",
        (
            Symbol(path="item_effects.item_state_receipts", role="value_accessor"),
            OptionSchema(item="Overlord's Bloodmail", option="missing_health_percent"),
            _rung_ref("attacker.overlords_bloodmail_state_option"),
        ),
    ),
    _unreachable_rung_claim("attacker.blocked_reasons", "attacker", "blocked"),
    _rule_claim(
        "attacker.gunmetal_greaves_movement_gap",
        "attacker",
        "modeled_effect",
        (
            Symbol(path="stats.get_item_stats", role="value_accessor"),
            _rung_ref("attacker.gunmetal_greaves_movement_gap"),
        ),
    ),
    _rule_claim(
        "attacker.item_effects_membership",
        "attacker",
        "modeled_effect",
        (
            Symbol(
                path="item_effects._resolve_damage_effects_uncached", role="tag_handler"
            ),
            _rung_ref("attacker.item_effects_membership"),
        ),
    ),
    _rule_claim(
        "attacker.item_input_options_membership",
        "attacker",
        "modeled_state",
        (
            Symbol(path="item_effects.item_state_receipts", role="value_accessor"),
            OptionSchema(item="Dark Seal", option="glory_stacks"),
            _rung_ref("attacker.item_input_options_membership"),
        ),
    ),
    _rule_claim(
        "attacker.reviewed_stats_only",
        "attacker",
        "stats_only",
        (
            _source_ref("Banshee's Veil"),
            _rung_ref("attacker.reviewed_stats_only"),
        ),
    ),
    _rule_claim(
        "attacker.no_described_effect",
        "attacker",
        "stats_only",
        (
            _source_ref("Blasting Wand"),
            _rung_ref("attacker.no_described_effect"),
        ),
    ),
    _rule_claim(
        "attacker.cached_shop_record",
        "attacker",
        "blocked",
        (
            Absence(
                reason=(
                    "A cached shop record whose passive or active has not been "
                    "reviewed for outgoing damage is withheld rather than scored; "
                    "the umbrella issue tracks the review queue."
                ),
                issue_refs=(_UMBRELLA_ISSUE,),
            ),
        ),
    ),
    _unreachable_rung_claim(
        "attacker.unreviewed_fixture", "attacker", "review_pending"
    ),
    _rule_claim(
        "target.modeled_reasons",
        "target",
        "modeled",
        (
            Symbol(
                path="defensive_effects.resolve_starting_defenses",
                role="walk_packet_builder",
            ),
            _rung_ref("target.modeled_reasons"),
        ),
    ),
    _rule_claim(
        "target.event_certified_reasons",
        "target",
        "modeled_event_certified",
        (
            Symbol(
                path="interpreters.threshold_defense._lifeline_shield",
                role="walk_packet_builder",
            ),
            Symbol(
                path="item_coverage.require_certified_target_timeline",
                role="certification_guard",
            ),
            _rung_ref("target.event_certified_reasons"),
        ),
    ),
    _rule_claim(
        "target.blocked_reasons",
        "target",
        "blocked",
        (
            Absence(
                reason=(
                    "The one withheld target mechanic stops the run by name; the "
                    "container holds its reason and the umbrella issue tracks it."
                ),
                issue_refs=(_UMBRELLA_ISSUE,),
            ),
        ),
    ),
    _unreachable_rung_claim(
        "target.attacker_review_pending_passthrough", "target", "review_pending"
    ),
    _rule_claim(
        "target.not_target_relevant",
        "target",
        "not_target_relevant",
        (
            _source_ref("Abyssal Mask"),
            _rung_ref("target.not_target_relevant"),
        ),
    ),
)


def _corpus() -> dict[tuple[SubjectKind, str, ClaimLane], Claim]:
    """Every claim, keyed the way the load gate reads it.

    Built once at import from the tables above.  The *evidence* is authored --
    a table that derived its own evidence from the registries it describes
    would agree with them by construction, which is the failure this module
    exists to catch -- and only the assembly is mechanical.
    """
    claims = [
        *(_attacker_state_claim(item) for item in _STATEFUL_MODELED_ITEMS),
        *(_stats_only_claim(item) for item in _REVIEWED_STATS_ONLY),
        *(_item_effects_claim(item) for item in _ISSUE_REF_ONLY_ITEMS),
        *(_target_modeled_claim(item) for item in _TARGET_MODELED_REASONS),
        *(_target_certified_claim(item) for item in _TARGET_EVENT_CERTIFIED_REASONS),
        *(_target_blocked_claim(item) for item in _TARGET_BLOCKED_REASONS),
        *(_utility_claim(item) for item in _UTILITY_DIMENSIONS),
        *(_support_packet_claim(item) for item in _SUPPORT_PACKET_CLAIMS),
        *_RULE_CLAIMS,
    ]
    return {(claim.subject_kind, claim.subject, claim.lane): claim for claim in claims}


COVERAGE_EVIDENCE: Mapping[tuple[SubjectKind, str, ClaimLane], Claim] = _corpus()

# Claim key -> why it is not backed yet.  It shrinks by edit and never grows:
# a new member arrives only with the reason it cannot be a claim, and every
# reason carries the issue that tracks it.
#
# Three key shapes: ``item:<name>@<lane>`` is a claim nobody may file yet,
# ``tag:<name>`` an effect tag with no live handler, and ``packet:<source>``
# one walk packet of an item whose claim exists but does not reach that
# packet.  The third exists because ``PacketSource`` proves only that a
# quoted packet is emitted; the totality check
# (``coverage_resolver.unquoted_packet_sources``) asks the other direction --
# every literal the builder emits is quoted by a claim or withheld here --
# and a per-item key cannot answer it for an item that is already claimed.
#
# No attacker or target key may appear here at all.  The rule is that a
# frontier which can absorb a damage or durability claim is the escape hatch
# this campaign closes, and "no such lane, ever" is the version of that rule a
# test can check without deciding what "prices damage" means.
FRONTIER: Mapping[str, str] = {
    "item:Diadem of Songs@support_packet": (
        "Consonance emits a walk packet no focused test exercises; #48 tracks "
        "the support-item authoring debt."
    ),
    "item:Echoes of Helia@support_packet": (
        "Soul Siphon emits a walk packet no focused test exercises; #48 tracks "
        "the support-item authoring debt."
    ),
    "item:Locket of the Iron Solari@support_packet": (
        "Devotion emits a walk packet no focused test exercises; #46 and #48 "
        "track the shield and the support-item authoring debt."
    ),
    "item:Mikael's Blessing@support_packet": (
        "Purify emits a walk packet no focused test exercises; #48 tracks the "
        "support-item authoring debt."
    ),
    "item:Runic Compass@support_packet": (
        "Shared Riches and Ward emit walk packets no focused test exercises; "
        "#40 tracks the review."
    ),
    "item:Shurelya's Battlesong@support_packet": (
        "Inspiring Speech emits a walk packet no focused test exercises; #40 "
        "tracks the review."
    ),
    "item:Stridebreaker@support_packet": (
        "Breaking Shockwave emits a walk packet no focused test exercises; #43 "
        "tracks the multi-target authoring debt."
    ),
    "packet:Dream Maker — Purple Dream Bubble": (
        "Dream Maker's second walk packet: the item's support_packet claim "
        "quotes Blue Dream Bubble, and the Purple bubble's magic on-hit is "
        "exercised by no focused test; #48 tracks the support-item authoring "
        "debt."
    ),
    "tag:conditional_attack_speed": _H4_DEAD_TAG,
    "tag:target_attack_speed_aura": _H4_DEAD_TAG,
    "tag:stat_conversion": _H4_SELF_REFERENTIAL_TAG,
    "tag:sustain": _H4_SELF_REFERENTIAL_TAG,
}

validate_claim_table(COVERAGE_EVIDENCE)

# ── the chain, mirrored as data ───────────────────────────────────────────

# The two classifiers above are ``if``/``elif`` ladders, and the *order* of
# their rungs is part of the public contract: an item in
# ``_REVIEWED_STATS_ONLY`` that also carries a defensive effect type never
# reaches its own container, so a coverage claim filed against that container
# is a claim no cached item can reach.  Nothing could say that until the
# ladder was something a program could walk.
#
# This is that walk, landed **beside** the chain and never instead of it
# (D-98).  It is read-only in this phase: no function in ``src/`` consumes
# it, ``tests/coverage_resolver.first_matching_rule`` interprets it, and a
# test reproduces the live status for every cached item on both lanes.
# Phase 3's step 3.8 is the one-symbol commit that flips the classifier onto
# it.  Every rung below is in the same order as the branch it mirrors, and
# `keys_on` names the container, registry or predicate that branch reads.
PRECEDENCE: tuple[PrecedenceRule, ...] = (
    PrecedenceRule(
        rule_id="attacker.deaths_dance_defensive_start",
        lane="attacker",
        kind="effect_type",
        keys_on=("item_effects.ITEM_EFFECTS",),
        items=("Death's Dance",),
        effect_types=("defensive_start",),
        negated=False,
        status="modeled_effect",
    ),
    PrecedenceRule(
        rule_id="attacker.defensive_effect_types",
        lane="attacker",
        kind="effect_type",
        keys_on=("item_effects.ITEM_EFFECTS",),
        items=(),
        effect_types=(
            "defensive_start",
            "target_mitigation",
            "target_threshold_health",
            "target_threshold_shield",
        ),
        negated=False,
        status="stats_only",
    ),
    PrecedenceRule(
        rule_id="attacker.stateful_modeled_items",
        lane="attacker",
        kind="container",
        keys_on=("item_coverage._STATEFUL_MODELED_ITEMS",),
        items=(),
        effect_types=(),
        negated=False,
        status="modeled_state",
    ),
    PrecedenceRule(
        rule_id="attacker.partial_blocked_reasons",
        lane="attacker",
        kind="container",
        keys_on=("item_coverage._PARTIAL_BLOCKED_REASONS",),
        items=(),
        effect_types=(),
        negated=False,
        status="blocked",
    ),
    PrecedenceRule(
        rule_id="attacker.heartsteel_state_option",
        lane="attacker",
        kind="option_state",
        keys_on=("item_effects.ITEM_INPUT_OPTIONS",),
        items=("Heartsteel",),
        effect_types=(),
        negated=False,
        status="modeled_state",
    ),
    PrecedenceRule(
        rule_id="attacker.rod_of_ages_state_option",
        lane="attacker",
        kind="option_state",
        keys_on=("item_effects.ITEM_INPUT_OPTIONS",),
        items=("Rod of Ages",),
        effect_types=(),
        negated=False,
        status="modeled_state",
    ),
    PrecedenceRule(
        rule_id="attacker.overlords_bloodmail_state_option",
        lane="attacker",
        kind="option_state",
        keys_on=("item_effects.ITEM_INPUT_OPTIONS",),
        items=("Overlord's Bloodmail",),
        effect_types=(),
        negated=False,
        status="modeled_state",
    ),
    PrecedenceRule(
        rule_id="attacker.blocked_reasons",
        lane="attacker",
        kind="container",
        keys_on=("item_coverage._BLOCKED_REASONS",),
        items=(),
        effect_types=(),
        negated=False,
        status="blocked",
    ),
    PrecedenceRule(
        rule_id="attacker.gunmetal_greaves_movement_gap",
        lane="attacker",
        kind="named_item",
        keys_on=(),
        items=("Gunmetal Greaves",),
        effect_types=(),
        negated=False,
        status="modeled_effect",
    ),
    PrecedenceRule(
        rule_id="attacker.item_effects_membership",
        lane="attacker",
        kind="container",
        keys_on=("item_effects.ITEM_EFFECTS",),
        items=(),
        effect_types=(),
        negated=False,
        status="modeled_effect",
    ),
    PrecedenceRule(
        rule_id="attacker.item_input_options_membership",
        lane="attacker",
        kind="container",
        keys_on=("item_effects.ITEM_INPUT_OPTIONS",),
        items=(),
        effect_types=(),
        negated=False,
        status="modeled_state",
    ),
    PrecedenceRule(
        rule_id="attacker.reviewed_stats_only",
        lane="attacker",
        kind="container",
        keys_on=("item_coverage._REVIEWED_STATS_ONLY",),
        items=(),
        effect_types=(),
        negated=False,
        status="stats_only",
    ),
    PrecedenceRule(
        rule_id="attacker.no_described_effect",
        lane="attacker",
        kind="predicate",
        keys_on=("item_coverage._has_described_effect",),
        items=(),
        effect_types=(),
        negated=True,
        status="stats_only",
    ),
    PrecedenceRule(
        rule_id="attacker.cached_shop_record",
        lane="attacker",
        kind="cached_record",
        keys_on=(),
        items=(),
        effect_types=(),
        negated=False,
        status="blocked",
    ),
    PrecedenceRule(
        rule_id="attacker.unreviewed_fixture",
        lane="attacker",
        kind="terminal",
        keys_on=(),
        items=(),
        effect_types=(),
        negated=False,
        status="review_pending",
    ),
    PrecedenceRule(
        rule_id="target.modeled_reasons",
        lane="target",
        kind="container",
        keys_on=("item_coverage._TARGET_MODELED_REASONS",),
        items=(),
        effect_types=(),
        negated=False,
        status="modeled",
    ),
    PrecedenceRule(
        rule_id="target.event_certified_reasons",
        lane="target",
        kind="container",
        keys_on=("item_coverage._TARGET_EVENT_CERTIFIED_REASONS",),
        items=(),
        effect_types=(),
        negated=False,
        status="modeled_event_certified",
    ),
    PrecedenceRule(
        rule_id="target.blocked_reasons",
        lane="target",
        kind="container",
        keys_on=("item_coverage._TARGET_BLOCKED_REASONS",),
        items=(),
        effect_types=(),
        negated=False,
        status="blocked",
    ),
    PrecedenceRule(
        rule_id="target.attacker_review_pending_passthrough",
        lane="target",
        kind="status_passthrough",
        keys_on=(),
        items=(),
        effect_types=(),
        negated=False,
        status="review_pending",
    ),
    PrecedenceRule(
        rule_id="target.not_target_relevant",
        lane="target",
        kind="terminal",
        keys_on=(),
        items=(),
        effect_types=(),
        negated=False,
        status="not_target_relevant",
    ),
)

validate_precedence(PRECEDENCE)

__all__ = [
    "COVERAGE_EVIDENCE",
    "FRONTIER",
    "PRECEDENCE",
    "item_model_coverage",
    "optimizer_candidate_coverage",
    "optimizer_supported_items",
    "require_calculation_item_coverage",
    "require_certified_target_timeline",
    "require_optimizer_item_coverage",
    "require_target_item_coverage",
    "review_issue_refs",
    "target_build_coverage",
    "target_item_model_coverage",
]
