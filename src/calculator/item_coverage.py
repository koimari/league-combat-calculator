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
from dataclasses import dataclass
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
from .data_fetcher import get_item_by_name
from .interpreters import INTERPRETERS, lanes_for
from .item_behavior import (
    BehaviorRule,
    DefenseExclusivity,
    DefenseMechanic,
    EngineLane,
    PacketKind,
    RuleFamily,
    SustainStatRule,
    UtilityDimension,
)
from .item_behavior_catalog import (
    EVENT_CERTIFIED_MECHANICS,
    behavior_rules,
    registry_entries,
)
from .item_effects import ALLY_ITEM_EFFECTS, ITEM_EFFECTS, ITEM_INPUT_OPTIONS

ItemCoverageStatus = Literal[
    "modeled_effect",
    "modeled_state",
    "stats_only",
    "withheld",
    "review_pending",
]

# The two answers that are refusals rather than classifications.  ``withheld``
# is the campaign's spelling for "coverage refused to model it — a named
# receipt and no number" (D-23); ``review_pending`` is the same refusal for a
# record that is not a shop item at all.  Neither is optimizer- or
# calculation-eligible, and no third status is a refusal.
_REFUSAL_STATUSES: frozenset[str] = frozenset({"withheld", "review_pending"})

# Families whose whole subject is the holder surviving rather than the holder
# dealing damage.  An item declaring nothing but these changes durability, and
# saying so on the attacker lane is the honest answer rather than a modelled
# claim about outgoing TDD.
_DEFENCE_FAMILIES: frozenset[RuleFamily] = frozenset(
    {
        RuleFamily.OPENING_DEFENSE,
        RuleFamily.THRESHOLD_DEFENSE,
        RuleFamily.COMBAT_STATE,
        RuleFamily.REACTIVE,
    }
)

# Families whose numbers come out of a progression or cross-participant state
# the shared ledger schedules rather than out of the pair engine's own
# rotation — which is exactly what ``modeled_state`` has always meant.
_STATE_FAMILIES: frozenset[RuleFamily] = frozenset(
    {RuleFamily.ALLY_PACKET, RuleFamily.STAT_DERIVATION}
)

# The lanes each public question needs answered.  ``needed`` is a real
# argument and not decoration: a family with no interpreter on a lane a caller
# depends on is the whole of ``withheld``, and a caller that never runs the
# compiled score walk must not be told its items are withheld because that
# lane has no interpreter yet.
#
# The three constants are three different questions, and they are meant to be:
#
# * ``ATTACKER_LANES`` — "can the pair engine price this item's outgoing
#   damage?"  It is what the shop and boots payloads publish, because the
#   browser asks what an item *is*, not what one search would do with it.
# * ``SCORING_LANES`` — "can BIS rank a build holding it?"  Ranking runs the
#   defence resolver too, so eligibility is the stricter question and the
#   refusals it produces are the ones that exclude a candidate.
# * ``TARGET_LANES`` — "can the passive-target model price what this item does
#   to the actor wearing it?"  That is the defence resolver's lane alone: a
#   target neither attacks nor casts in this model.
#
# The consequence is stated rather than left to be discovered: the day a
# family loses its defence-resolver interpreter, an item reads ``modeled_*``
# in the shop payload and is ``withheld`` from the optimizer in the same
# request.  That is the honest pair of answers to two different questions —
# the shop is not claiming the optimizer will score it — and it is latent
# today because ``unserved_lanes`` is empty for every cached item on every
# lane (asserted, not assumed).
ATTACKER_LANES: frozenset[EngineLane] = frozenset({EngineLane.PAIR_ENGINE})
SCORING_LANES: frozenset[EngineLane] = ATTACKER_LANES | frozenset(
    {EngineLane.DEFENSE_RESOLVER}
)
TARGET_LANES: frozenset[EngineLane] = frozenset({EngineLane.DEFENSE_RESOLVER})


@dataclass(frozen=True, slots=True)
class ItemCoverage:
    """One item's coverage answer, and the lanes it was answered for.

    A record rather than a dict because ``needed`` is part of the answer: the
    same item is modelled for a caller that prices only the pair engine and
    withheld for one that also needs a lane no interpreter serves, and a
    payload that did not carry the question could not be read back.

    ``as_payload`` is the only producer of the public shape, so the two
    serializing call sites in ``app.py`` cannot drift from the one the
    optimizer and the classification receipt read.
    """

    name: str
    status: ItemCoverageStatus
    reason: str
    outcome_dimensions: tuple[UtilityDimension, ...]
    review_issue_refs: tuple[int, ...]
    needed: frozenset[EngineLane]

    @property
    def optimizer_eligible(self) -> bool:
        """Whether BIS search may generate candidates holding this item."""
        return self.status not in _REFUSAL_STATUSES

    @property
    def calculation_eligible(self) -> bool:
        """Whether an explicit request naming this item may be calculated."""
        return self.status not in _REFUSAL_STATUSES

    def as_payload(self) -> dict[str, Any]:
        """The public coverage dict — one producer, read by every consumer."""
        return {
            "name": self.name,
            "status": self.status,
            "optimizer_eligible": self.optimizer_eligible,
            "calculation_eligible": self.calculation_eligible,
            "outcome_dimensions": [
                dimension.value for dimension in self.outcome_dimensions
            ],
            "review_issue_refs": list(self.review_issue_refs),
            "reason": self.reason,
        }


# Three containers stood here — ``_BLOCKED_REASONS``,
# ``_CALCULATION_ALLOWED_BLOCKED`` and ``_PARTIAL_BLOCKED_REASONS``.  All three
# were empty, and the commit before this one asserted that emptiness and pinned
# the two ``PRECEDENCE`` rungs they gated.  An empty container makes ``name in``
# false for every name that exists and every name that could, so those rungs
# decided nothing and the eligibility term added nothing: deleting them moves no
# answer.  A withheld item now has one producer — a cached record whose passive
# is unreviewed — instead of three that could disagree with each other.

# ``_STATEFUL_MODELED_ITEMS`` stood here: twenty-one sentences saying an item's
# state was represented, checked by nothing.  It is gone.  ``modeled_state`` is
# now what the declared families say — an ally packet or a stat derivation is
# state the shared ledger schedules — or what ``ITEM_INPUT_OPTIONS`` says, and
# both are read out of a registry rather than asserted in prose here.


# The one reviewed registry that survives the flip, and the reason it has to:
# "we read the cached page and there is no runtime behaviour" is a fact about
# an *absence*, and no declaration can carry an absence.  Every other container
# in this module asserted the presence of a model, which is what declarations
# now say instead.
#
# It is a ratchet and not an escape hatch (criterion 2).  Its membership is
# committed to ``docs/behavior-frontier.json``, diff-gated by set equality, and
# **non-increasing** from the size measured before the phase — otherwise
# counter 3's target could be reached by reviewing the backlog into silence.
# Each entry was reviewed against the cached Wiki passive/active description at
# the revision ``_SOURCE_REFS`` records for it.
NO_RUNTIME_BEHAVIOR: Mapping[str, str] = {
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

# What each item changes about a fight besides the damage number.  The labels
# are deliberately descriptive: they do not claim a combat formula is
# implemented, and an item whose coverage is withheld stays withheld rather
# than being silently presented as a stat-only one.
#
# The *vocabulary* is not declared here — it is
# :class:`~.item_behavior.UtilityDimension`, the single home both this payload
# and Phase 1's claim table read.  What is declared here is the per-item
# assignment, which no rule can derive: twenty of these items compile to no
# ``BehaviorRule`` at all (a revive, a stasis, a spell shield), so their
# outcome is a reviewed product fact rather than a consequence of a
# declaration.  Typed members instead of open strings is the difference the
# flip makes: a misspelling is now an ``AttributeError`` at import.
UTILITY_OUTCOMES: Mapping[str, tuple[UtilityDimension, ...]] = {
    "Bandlepipes": (UtilityDimension.ALLY_SUPPORT, UtilityDimension.STAT_BUFF),
    "Gunmetal Greaves": (UtilityDimension.MOVEMENT,),
    "Cull": (
        UtilityDimension.ECONOMY,
        UtilityDimension.PROGRESSION,
        UtilityDimension.ON_HIT,
    ),
    "Phage": (UtilityDimension.MOVEMENT,),
    "Heartsteel": (UtilityDimension.PROGRESSION, UtilityDimension.HEALTH_STATE),
    "Hubris": (UtilityDimension.PROGRESSION, UtilityDimension.STAT_CONVERSION),
    "Axiom Arc": (UtilityDimension.PROGRESSION, UtilityDimension.RESOURCE),
    "Mejai's Soulstealer": (
        UtilityDimension.PROGRESSION,
        UtilityDimension.STAT_CONVERSION,
    ),
    "Rod of Ages": (
        UtilityDimension.PROGRESSION,
        UtilityDimension.HEALTH_STATE,
        UtilityDimension.RESOURCE,
    ),
    "Solstice Sleigh": (
        UtilityDimension.ALLY_SUPPORT,
        UtilityDimension.MOVEMENT,
        UtilityDimension.SUSTAIN,
    ),
    "Swiftmarch": (UtilityDimension.MOVEMENT, UtilityDimension.STAT_CONVERSION),
    "World Atlas": (
        UtilityDimension.ECONOMY,
        UtilityDimension.QUEST,
        UtilityDimension.ALLY_SUPPORT,
        UtilityDimension.VISION,
    ),
    "Runic Compass": (
        UtilityDimension.ECONOMY,
        UtilityDimension.QUEST,
        UtilityDimension.ALLY_SUPPORT,
        UtilityDimension.VISION,
    ),
    "Tear of the Goddess": (UtilityDimension.PROGRESSION, UtilityDimension.RESOURCE),
    "Banshee's Veil": (UtilityDimension.SPELL_PROTECTION,),
    "Edge of Night": (UtilityDimension.SPELL_PROTECTION,),
    "Zhonya's Hourglass": (UtilityDimension.STASIS,),
    "Guardian Angel": (UtilityDimension.REVIVE,),
    "Mercurial Scimitar": (UtilityDimension.CLEANSE, UtilityDimension.MOVEMENT),
    "Boots of Swiftness": (UtilityDimension.SLOW_RESISTANCE, UtilityDimension.MOVEMENT),
    "Cosmic Drive": (UtilityDimension.MOVEMENT,),
    "Force of Nature": (UtilityDimension.MOVEMENT, UtilityDimension.DEFENSE),
    "Phantom Dancer": (UtilityDimension.MOVEMENT,),
    "Shurelya's Battlesong": (UtilityDimension.MOVEMENT, UtilityDimension.ALLY_SUPPORT),
    "Youmuu's Ghostblade": (UtilityDimension.MOVEMENT,),
    "Rylai's Crystal Scepter": (UtilityDimension.SLOW,),
    "Serylda's Grudge": (UtilityDimension.SLOW,),
    "Frozen Heart": (UtilityDimension.ATTACK_SPEED_REDUCTION,),
    "Randuin's Omen": (UtilityDimension.SLOW, UtilityDimension.CRITICAL_MITIGATION),
    "Runaan's Hurricane": (
        UtilityDimension.MULTI_TARGET,
        UtilityDimension.COPIED_ON_HIT,
    ),
    "Titanic Hydra": (UtilityDimension.MULTI_TARGET,),
    "Profane Hydra": (UtilityDimension.MULTI_TARGET,),
    "Ravenous Hydra": (UtilityDimension.MULTI_TARGET, UtilityDimension.SUSTAIN),
    "Stridebreaker": (
        UtilityDimension.MULTI_TARGET,
        UtilityDimension.SLOW,
        UtilityDimension.MOVEMENT,
    ),
    "Statikk Shiv": (UtilityDimension.MULTI_TARGET, UtilityDimension.ENERGIZED),
    "Stormrazor": (UtilityDimension.ENERGIZED, UtilityDimension.MOVEMENT),
    "Rapid Firecannon": (UtilityDimension.ENERGIZED, UtilityDimension.RANGE),
    "Umbral Glaive": (UtilityDimension.VISION,),
    "Horizon Focus": (UtilityDimension.VISION, UtilityDimension.DAMAGE_AMPLIFICATION),
    "Locket of the Iron Solari": (
        UtilityDimension.ALLY_SUPPORT,
        UtilityDimension.SHIELD,
    ),
    "Mikael's Blessing": (
        UtilityDimension.ALLY_SUPPORT,
        UtilityDimension.CLEANSE,
        UtilityDimension.SUSTAIN,
    ),
    "Redemption": (UtilityDimension.ALLY_SUPPORT, UtilityDimension.SUSTAIN),
    "The Collector": (UtilityDimension.EXECUTE, UtilityDimension.TAKEDOWN_STATE),
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


def _has_described_effect(item: Mapping[str, Any]) -> bool:
    """Return whether cached Wiki data describes a passive or active."""
    return bool(item.get("passives") or item.get("active") or item.get("actives"))


def _cached_record(name: str) -> Mapping[str, Any]:
    """One cached item record, read through the caching layer (rule 2).

    A name the shop does not hold is a synthetic fixture, not an error: the
    last two rungs exist to tell those apart from real records, so a miss is an
    empty mapping rather than a raise.
    """
    try:
        return get_item_by_name(name)
    except KeyError:
        return {}


def _declared_families(name: str) -> frozenset[RuleFamily]:
    """Every family *name* declares — through a rule, or through its entry.

    Two sources and not one, deliberately.  A compiled ``BehaviorRule`` is the
    declaration proper; a registry entry whose family is not migrated yet
    compiles to no rule but is still an item whose behaviour the engines run.
    Reading only the rules would call every unmigrated item unmodelled, which
    is a refusal invented by the migration rather than by the model.
    """
    families = {family for _, family, _ in registry_entries(name)}
    families.update(rule.family for rule in behavior_rules(name))
    return frozenset(families)


def unserved_lanes(name: str, needed: frozenset[EngineLane]) -> tuple[str, ...]:
    """Every ``(family, lane)`` *name* declares that no interpreter serves.

    This is the whole of ``withheld``: a declared family whose interpreter is
    missing on a lane the caller needs cannot be priced, and the honest answer
    is a named refusal rather than a number the missing interpreter would have
    changed.  Empty tuple is the pass condition, and it is empty for every
    cached item today — which is why the branch is proved on a synthetic
    declaration and on an emptiness assertion rather than by a real build
    (D-26).

    It folds over compiled **rules** and never over registry entries, and the
    difference is the whole correctness of the flip.  A family a registry entry
    names but no rule compiles is *unmigrated*, not uninterpreted: its
    behaviour is still live engine code, and withholding it would be a refusal
    the migration invented.  ``stat_derivation`` is exactly that today, and
    reading entries here would withhold Rabadon's Deathcap from BIS on the
    strength of a declaration nobody has written yet.
    """
    return tuple(
        sorted(
            f"{family.value}/{lane.value}"
            for family in {rule.family for rule in behavior_rules(name)}
            for lane in lanes_for(family) & needed
            if (family, lane) not in INTERPRETERS
        )
    )


def has_unserved_lane(name: str) -> bool:
    """Rung 1: a declared family with no interpreter on an attacker lane."""
    return bool(unserved_lanes(name, ATTACKER_LANES))


def declares_only_defence(name: str) -> bool:
    """Rung 2: everything this item declares is about surviving, not dealing."""
    families = _declared_families(name)
    return bool(families) and families <= _DEFENCE_FAMILIES


def declares_state(name: str) -> bool:
    """Rung 3: declared behaviour whose numbers come out of supplied state."""
    families = _declared_families(name)
    if not families:
        return False
    return bool(name in ITEM_INPUT_OPTIONS or families & _STATE_FAMILIES)


def declares_behaviour(name: str) -> bool:
    """Rung 4: anything declared at all, once the two rungs above have passed."""
    return bool(_declared_families(name))


def gated_state_reason(name: str) -> str | None:
    """Rung 2's own sub-question: is this defence *armed* by a scenario input?

    A defence-only item is ``stats_only`` either way, so this decides only what
    the receipt beside that label says.  When a declared rule describes an
    exclusive state (``exclusivity``) that an explicit bounded option arms
    (``option``), the load-bearing fact is that gate — holding the item is not
    holding the state — and the family census, which says only that nothing
    declared here is offensive, is the weaker sentence.  It is also the false
    one for an item like this: an item whose active suppresses its own holder
    for the duration does touch outgoing damage, so "the mechanic changes
    durability, not outgoing TDD" is a claim the declaration does not support.

    Every part of the sentence is read off the declared rule — the mechanic
    names itself, the exclusivity names the state, and what is left of the
    option key after the state's own prefix names the control — so the rung
    stays a derivation and no item name enters this file.  ``None`` means the
    declaration carries no such gate and the family census stands.
    """
    for rule in behavior_rules(name):
        payload = rule.payload
        exclusivity = getattr(payload, "exclusivity", None)
        option = getattr(payload, "option", None)
        if option is None or exclusivity in (None, DefenseExclusivity.NONE):
            continue
        state = exclusivity.value
        control = option.value.removeprefix(f"{state}_").replace("_", "-")
        mechanic = payload.mechanic.value.replace("_", " ").title()
        return (
            f"{mechanic} is priced only from the explicit bounded {control} "
            f"scenario input; item presence alone never assumes {state}."
        )
    return None


def _state_reason(name: str, families: frozenset[RuleFamily]) -> str:
    """Why a declared item's damage-relevant state is supplied rather than run."""
    if name in ITEM_INPUT_OPTIONS:
        return (
            f"{name}'s damage-relevant state is supplied through an explicit "
            "bounded scenario control, and its declared behaviour reads it."
        )
    return (
        "The declared behaviour carries progression or cross-participant state "
        "that the shared participant ledger schedules: "
        + ", ".join(sorted(family.value for family in families & _STATE_FAMILIES))
        + "."
    )


def _declared_status(
    name: str, families: frozenset[RuleFamily]
) -> tuple[ItemCoverageStatus, str]:
    """The status of an item whose behaviour is declared, from its families.

    The three predicates above are the rungs ``PRECEDENCE`` mirrors, and this
    reads them rather than re-testing the same conditions: the ladder and its
    mirror are the same code, so they cannot drift into disagreeing.
    """
    if declares_only_defence(name):
        gated = gated_state_reason(name)
        if gated is not None:
            return "stats_only", gated
        return (
            "stats_only",
            "Every declared family on this item is a defence: the represented "
            "mechanic changes durability, not outgoing TDD.",
        )
    if declares_state(name):
        return "modeled_state", _state_reason(name, families)
    return (
        "modeled_effect",
        "Damage-relevant effects are declared and every declared family has an "
        "interpreter on the lanes this request needs.",
    )


def item_model_coverage(name: str, needed: frozenset[EngineLane]) -> ItemCoverage:
    """One item's coverage on the lanes a caller needs, computed from declarations.

    The ladder used to branch on the item's name eleven times.  It now asks
    four questions in order, and every one of them is answered by something the
    catalog or the registries say rather than by a sentence in this file:

    1. Does a declared family lack an interpreter on a needed lane?  Then the
       answer is ``withheld`` with the missing pair named — never a number.
    2. Is anything declared at all?  Then the families decide: all-defence is
       ``stats_only``, a state or ally family is ``modeled_state``, and the
       rest is ``modeled_effect``.  An all-defence item whose declaration
       gates an exclusive state behind a bounded option publishes that gate
       as its receipt rather than the family census.
    3. Does the item expose bounded state as a scenario control, or has a
       review found it has no runtime behaviour?  Then ``modeled_state`` and
       ``stats_only`` respectively — the second being the one reviewed registry
       that survives, because "we looked and there is nothing" is a fact no
       declaration can carry.
    4. Otherwise it has a cached passive nothing declares.  A real shop record
       is ``withheld``; anything else is a fixture and is ``review_pending``.
    """
    record = _cached_record(name)
    unserved = unserved_lanes(name, needed)
    if unserved:
        status: ItemCoverageStatus = "withheld"
        reason = (
            f"{name} declares {', '.join(unserved)} and no interpreter serves "
            "it there, so its contribution is withheld rather than priced as "
            "zero."
        )
    else:
        families = _declared_families(name)
        if families:
            status, reason = _declared_status(name, families)
        elif name in ITEM_INPUT_OPTIONS:
            status = "modeled_state"
            reason = "The item exposes its damage-relevant state as a scenario control."
        elif name in NO_RUNTIME_BEHAVIOR:
            status = "stats_only"
            reason = NO_RUNTIME_BEHAVIOR[name]
        elif not _has_described_effect(record):
            status = "stats_only"
            reason = (
                "The item has no separate passive or active in the cached Wiki data."
            )
        elif record.get("id") is not None or record.get("icon"):
            status = "withheld"
            reason = (
                "This cached passive or active is declared by no BehaviorRule "
                "and no registry entry; calculation is withheld."
            )
        else:
            status = "review_pending"
            reason = (
                "This passive or active has not yet been reviewed for outgoing TDD."
            )

    return ItemCoverage(
        name=name,
        status=status,
        reason=reason,
        outcome_dimensions=UTILITY_OUTCOMES.get(name, ()),
        review_issue_refs=(
            tuple(review_issue_refs(name)) if status in _REFUSAL_STATUSES else ()
        ),
        needed=needed,
    )


# ── the target lane, derived ──────────────────────────────────────────────

# A packet whose kind is one of these changes what its recipient survives;
# every other kind is a stat buff, a movement effect, vision or an economy
# payout, and none of those is durability.
_DURABILITY_PACKET_KINDS: frozenset[PacketKind] = frozenset(
    {PacketKind.HEAL, PacketKind.SHIELD, PacketKind.TEMPORARY_HEALTH}
)

# The payload fields a strike declares when its own hit heals or shields the
# holder.  Named fields rather than a substring test on field names: the
# ``self_shield`` on a cast proc and the ``heal`` on a forced crit *are* the
# mechanism, and a test asserts every name here is a field of some declared
# payload class, so a rename fails loudly rather than quietly emptying it.
_HOLDER_SURVIVAL_FIELDS: frozenset[str] = frozenset(
    {
        "heal",
        "self_heal_share",
        "self_heal_ap_ratio",
        "self_heal_bonus_health_ratio",
        "self_shield",
    }
)


def declared_defence(rule: BehaviorRule) -> DefenseMechanic | None:
    """The defence a rule declares, or ``None`` when it declares none.

    Every compiler builds ``mechanic_id`` as ``<owner slug>.<mechanic>``, so
    the suffix is the mechanic's own name; a suffix that names a
    :class:`~.item_behavior.DefenseMechanic` member is a defence the resolver
    builds.  Read off the identifier rather than off ``payload.mechanic``
    because one defence — Fimbulwinter's Everlasting — is declared as the ally
    packet that grants the shield and carries no ``mechanic`` field, and a
    reader that missed it would silently drop the item from the target lane.
    A test pins that the two agree wherever the payload has both.
    """
    try:
        return DefenseMechanic(rule.mechanic_id.rsplit(".", 1)[-1])
    except ValueError:
        return None


def _prices_holder_durability(rule: BehaviorRule) -> bool:
    """Whether *rule* changes what the actor holding it can survive.

    Four shapes, each read off the declaration and none off a name:

    1. it declares a :class:`~.item_behavior.DefenseMechanic` — the defence
       resolver's own closed vocabulary, and the target lane is that lane;
    2. it is a ``sustain`` rule that schedules a heal rather than granting a
       vampirism stat, because a stat is priced by the stat fold and only a
       scheduled heal enters the durability ledger;
    3. its payload declares a holder heal or shield beside its own damage —
       the strike families whose hit pays health back;
    4. it emits a cross-participant packet that heals, shields or grants
       temporary health, or that redirects incoming damage away from its
       recipient.
    """
    if declared_defence(rule) is not None:
        return True
    payload = rule.payload
    if rule.family is RuleFamily.SUSTAIN and not isinstance(payload, SustainStatRule):
        return True
    if any(
        getattr(payload, field, None) is not None for field in _HOLDER_SURVIVAL_FIELDS
    ):
        return True
    if getattr(payload, "redirects_incoming_damage", False):
        return True
    return any(
        spec.kind in _DURABILITY_PACKET_KINDS
        for spec in getattr(payload, "packets", ()) or ()
    )


def target_lane_rules(name: str) -> tuple[BehaviorRule, ...]:
    """Every rule *name* declares that the passive-target model prices."""
    return tuple(
        rule for rule in behavior_rules(name) if _prices_holder_durability(rule)
    )


def certified_target_mechanics(name: str) -> tuple[DefenseMechanic, ...]:
    """The declared defences on *name* that need an exactly-timed ledger.

    The catalog declares the property per mechanic and this reads it, so the
    six Lifelines are one declaration rather than six reviewed sentences and a
    seventh item taking a Lifeline is certified the day it is declared.
    """
    return tuple(
        mechanic
        for rule in behavior_rules(name)
        if (mechanic := declared_defence(rule)) in EVENT_CERTIFIED_MECHANICS
        and mechanic is not None
    )


def _mechanic_list(rules: tuple[BehaviorRule, ...]) -> str:
    """The declared mechanics behind an answer, named as the wiki names them.

    The mechanic's own name and never the item's: the receipt says *what* is
    priced, and the item is already the subject of the sentence around it.
    """
    return ", ".join(
        sorted(
            {
                rule.mechanic_id.rsplit(".", 1)[-1].replace("_", " ").title()
                for rule in rules
            }
        )
    )


def _derived_target_status(name: str) -> tuple[str, str]:
    """The target-lane status of an item whose behaviour is declared."""
    certified = certified_target_mechanics(name)
    priced = target_lane_rules(name)
    if certified:
        return (
            "modeled_event_certified",
            f"{_mechanic_list(priced)} is scheduled from the exactly-timed "
            f"damage ledger — "
            + "; ".join(
                sorted(EVENT_CERTIFIED_MECHANICS[mechanic] for mechanic in certified)
            )
            + " — so an uncertified timed fight is withheld rather than mis-timed.",
        )
    if priced:
        return (
            "modeled",
            f"{_mechanic_list(priced)} changes what this actor survives, and "
            "every rule behind it has an interpreter on the target lane.",
        )
    return (
        "not_target_relevant",
        "Nothing this item declares changes incoming damage, durability or "
        "combat healing in the passive-target model.",
    )


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
        status = "withheld"
        reason = _TARGET_BLOCKED_REASONS[name]
    elif not _cached_record(name) and _has_described_effect(item):
        # A record the shop does not hold, carrying a described passive: a
        # synthetic or unknown fixture.  The attacker ladder answers by name
        # and cannot see a caller-supplied record, so the durability question
        # is asked here of the record itself rather than passed through — the
        # rung fails closed either way, and asking it of the argument is what
        # keeps it reachable at all.
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
        "calculation_eligible": status not in _REFUSAL_STATUSES,
        "outcome_dimensions": [
            dimension.value for dimension in UTILITY_OUTCOMES.get(name, ())
        ],
        "review_issue_refs": (
            review_issue_refs(name) if status in _REFUSAL_STATUSES else []
        ),
        "reason": reason,
    }


def target_build_coverage(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise whether a target inventory is safe to calculate."""
    entries = [target_item_model_coverage(item) for item in items]
    withheld = [entry for entry in entries if not entry["calculation_eligible"]]
    return {
        "complete": not withheld,
        "model": "passive_target",
        "items": entries,
        "withheld": withheld,
        "note": (
            "Every equipped item is supported by the passive-target model."
            if not withheld
            else "Calculation is withheld until the named target mechanic is modelled."
        ),
    }


def require_target_item_coverage(items: list[dict[str, Any]]) -> None:
    """Reject target inventories that would silently omit a defense."""
    coverage = target_build_coverage(items)
    if coverage["withheld"]:
        withheld = coverage["withheld"][0]
        raise ValueError(
            f"Enemy item {withheld['name']} is not supported yet: "
            f"{withheld['reason']}"
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
    """Summarise which legal item candidates can be scored without omission.

    D-23's published half.  A withheld candidate is **excluded from candidate
    generation** by :func:`optimizer_supported_items` and **named here**, and
    the per-request exclusion count is published as ``withheld_count`` so a
    request that quietly lost a legal build says so in its own response rather
    than only in a log.  It is never scored as zero, which is the outcome this
    campaign exists to make unrepresentable.
    """
    classified = [
        item_model_coverage(str(item.get("name", "")), SCORING_LANES) for item in items
    ]
    included = [entry for entry in classified if entry.optimizer_eligible]
    withheld = [entry for entry in classified if not entry.optimizer_eligible]
    return {
        "eligible_candidates": len(classified),
        "scored_candidates": len(included),
        "withheld_count": len(withheld),
        "complete": not withheld,
        "withheld": [entry.as_payload() for entry in withheld],
        "note": (
            "Every legal candidate is fully modelled."
            if not withheld
            else (
                f"{len(withheld)} legal item candidate"
                f"{' is' if len(withheld) == 1 else 's are'} withheld because "
                "a damage-relevant mechanic is not yet modelled."
            )
        ),
    }


def optimizer_supported_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return candidates whose outgoing TDD can be scored without omission.

    The exclusion half of D-23: a withheld item never reaches candidate
    generation, so no build is ranked on a zero standing in for a mechanic
    nobody ran.
    """
    return [
        item
        for item in items
        if item_model_coverage(
            str(item.get("name", "")), SCORING_LANES
        ).optimizer_eligible
    ]


def require_optimizer_item_coverage(item: dict[str, Any]) -> None:
    """Reject a locked item whose damage-relevant mechanics are incomplete."""
    coverage = item_model_coverage(str(item.get("name", "")), SCORING_LANES)
    if not coverage.optimizer_eligible:
        raise ValueError(
            f"{coverage.name} cannot be locked into BIS search yet: "
            f"{coverage.reason}"
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
        coverage = item_model_coverage(str(item.get("name", "")), SCORING_LANES)
        if (
            allow_ally_effects
            and coverage.status == "withheld"
            and coverage.name in ALLY_ITEM_EFFECTS
        ):
            # CP17's cross-participant packet layer is the authoritative
            # calculation path for support items.  They remain withheld from
            # ordinary BIS ranking until every holder-side sibling is
            # modeled, but an explicitly rostered support item is safe to
            # calculate because its item-team effects are timestamped and
            # fail closed when their trigger is absent.
            continue
        if coverage.calculation_eligible:
            continue
        raise ValueError(
            f"{participant} item {coverage.name} cannot be used in a "
            f"calculation yet: {coverage.reason}"
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
_ISSUE_REF_ONLY_ITEMS: tuple[str, ...] = (
    "Catalyst of Aeons",
    "Voltaic Cyclosword",
    "Zeke's Convergence",
)

# Why an earlier rung means no cached item can reach a claim, keyed
# ``<subject>@<lane>``.  Twenty-nine container entries are decided above their
# own container, and four rungs are live code only a synthetic fixture enters;
# ``tests/coverage_resolver.shadow_report`` derives the same set from
# ``PRECEDENCE`` and the cached shop, and the suite asserts the two agree both
# ways.  A claim that is dead prose in a live-looking home is what this field
# exists to make visible, so no entry may be blank.
_SHADOWED_CLAIM_REASONS: Mapping[str, str] = {
    "Armored Advance@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Banshee's Veil@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Bloodthirster@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Celestial Opposition@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Chainlaced Crushers@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Cryptbloom@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Death's Dance@attacker": (
        "Its own declaration answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Diadem of Songs@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Doran's Ring@attacker": (
        "Its own declaration answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Doran's Shield@attacker": (
        "Its own declaration answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Dream Maker@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Echoes of Helia@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Edge of Night@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Force of Nature@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Frozen Heart@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Guardian Angel@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Gunmetal Greaves@attacker": (
        "Its own declaration answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Immortal Shieldbow@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Jak'Sho, The Protean@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Kaenic Rookern@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Knight's Vow@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Locket of the Iron Solari@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Maw of Malmortius@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Mercurial Scimitar@attacker": (
        "Its own declaration answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Mikael's Blessing@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Moonstone Renewer@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Plated Steelcaps@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Protoplasm Harness@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Randuin's Omen@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Seeker's Armguard@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Shurelya's Battlesong@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Solstice Sleigh@attacker": (
        "Its declared state family answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Spirit Visage@attacker": (
        "Its own declaration answers it before the reviewed-nothing "
        "container is reached, so the container never speaks for it and "
        "no request can reach this claim."
    ),
    "Verdant Barrier@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "Zhonya's Hourglass@attacker": (
        "Every family this item declares is a defence, so the defence "
        "rung answers it before the reviewed-nothing container is "
        "reached; the container never speaks for it and no request can "
        "reach this claim."
    ),
    "attacker.unreviewed_fixture@attacker": (
        "review_pending is reserved for synthetic and unknown fixtures: "
        "every cached shop record carries an id or an icon and is "
        "withheld by the rung above, so no cached item reaches this one."
    ),
    "attacker.unserved_declared_lane@attacker": (
        "No cached item declares a family whose interpreter is missing on "
        "the attacker lane, so nothing reaches this rung; the branch is "
        "proved on a synthetic declaration and on the emptiness of the "
        "population itself rather than by any real build."
    ),
    "target.attacker_review_pending_passthrough@target": (
        "The passthrough fires only for an item the attacker lane calls "
        "review_pending, and no cached item is; it exists so a synthetic "
        "fixture cannot be target-relevant while being attacker- "
        "unreviewed."
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
    """One stateful item: the state, and the named home it comes from."""
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
    """One ``NO_RUNTIME_BEHAVIOR`` entry: a review, and the revision it read."""
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
        status="withheld",
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
    """One ``UTILITY_OUTCOMES`` entry and the home of what the model prices.

    A utility claim is about outcome *dimensions*, and the model prices some
    of them and none of others.  ``modeled_effect`` and ``modeled_state`` name
    the home of the dimension it does price; ``stats_only`` is the honest
    answer where it prices none of them, and then the claim cites the review
    that says so rather than pointing at code that is about something else.
    """
    path, home = _UTILITY_HOMES[item]
    dimensions = tuple(dimension.value for dimension in UTILITY_OUTCOMES[item])
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
        "attacker.unserved_declared_lane",
        "attacker",
        "withheld",
        (
            Absence(
                reason=(
                    "A declared family whose interpreter is missing on a lane the "
                    "request needs is withheld with the pair named, never priced "
                    "as zero; no cached item reaches it today, which is why the "
                    "rung is proved on a synthetic declaration and on an "
                    "emptiness assertion."
                ),
                issue_refs=(_UMBRELLA_ISSUE,),
            ),
        ),
    ),
    _rule_claim(
        "attacker.declared_defence_only",
        "attacker",
        "stats_only",
        (
            _source_ref("Guardian Angel"),
            _rung_ref("attacker.declared_defence_only"),
        ),
    ),
    _rule_claim(
        "attacker.declared_state",
        "attacker",
        "modeled_state",
        (
            Symbol(path="item_effects.item_state_receipts", role="value_accessor"),
            OptionSchema(item="Hubris", option="eminence_stacks"),
            _rung_ref("attacker.declared_state"),
        ),
    ),
    _rule_claim(
        "attacker.declared_behaviour",
        "attacker",
        "modeled_effect",
        (
            Symbol(path="item_behavior_catalog.behavior_rules", role="compiler"),
            _rung_ref("attacker.declared_behaviour"),
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
        "attacker.no_runtime_behavior",
        "attacker",
        "stats_only",
        (
            _source_ref("Banshee's Veil"),
            _rung_ref("attacker.no_runtime_behavior"),
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
        "withheld",
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
        "target.withheld_reasons",
        "target",
        "withheld",
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
        *(_attacker_state_claim(item) for item in _ATTACKER_STATE_HOMES),
        *(_stats_only_claim(item) for item in NO_RUNTIME_BEHAVIOR),
        *(_item_effects_claim(item) for item in _ISSUE_REF_ONLY_ITEMS),
        *(_target_modeled_claim(item) for item in _TARGET_MODELED_REASONS),
        *(_target_certified_claim(item) for item in _TARGET_EVENT_CERTIFIED_REASONS),
        *(_target_blocked_claim(item) for item in _TARGET_BLOCKED_REASONS),
        *(_utility_claim(item) for item in UTILITY_OUTCOMES),
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
}

validate_claim_table(COVERAGE_EVIDENCE)

# ── the chain, mirrored as data ───────────────────────────────────────────

# The two classifiers above are ``if``/``elif`` ladders, and the *order* of
# their rungs is part of the public contract: an item in
# ``NO_RUNTIME_BEHAVIOR`` that also carries a defensive effect type never
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
        rule_id="attacker.unserved_declared_lane",
        lane="attacker",
        kind="derivation",
        keys_on=("item_coverage.has_unserved_lane",),
        items=(),
        effect_types=(),
        negated=False,
        status="withheld",
    ),
    PrecedenceRule(
        rule_id="attacker.declared_defence_only",
        lane="attacker",
        kind="derivation",
        keys_on=("item_coverage.declares_only_defence",),
        items=(),
        effect_types=(),
        negated=False,
        status="stats_only",
    ),
    PrecedenceRule(
        rule_id="attacker.declared_state",
        lane="attacker",
        kind="derivation",
        keys_on=("item_coverage.declares_state",),
        items=(),
        effect_types=(),
        negated=False,
        status="modeled_state",
    ),
    PrecedenceRule(
        rule_id="attacker.declared_behaviour",
        lane="attacker",
        kind="derivation",
        keys_on=("item_coverage.declares_behaviour",),
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
        rule_id="attacker.no_runtime_behavior",
        lane="attacker",
        kind="container",
        keys_on=("item_coverage.NO_RUNTIME_BEHAVIOR",),
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
        status="withheld",
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
        rule_id="target.withheld_reasons",
        lane="target",
        kind="container",
        keys_on=("item_coverage._TARGET_BLOCKED_REASONS",),
        items=(),
        effect_types=(),
        negated=False,
        status="withheld",
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
    "ATTACKER_LANES",
    "COVERAGE_EVIDENCE",
    "FRONTIER",
    "ItemCoverage",
    "NO_RUNTIME_BEHAVIOR",
    "SCORING_LANES",
    "PRECEDENCE",
    "UTILITY_OUTCOMES",
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
