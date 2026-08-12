"""What each item changes about a fight besides the damage number.

One mapping and nothing else.  It lives in a module of its own because it is
a *declaration* and not a classification: ``item_coverage`` computes every
status it publishes from what an item declares, and the outcome dimensions are
the one thing on that payload no declaration can produce.  Twenty of these
items compile to no ``BehaviorRule`` at all — a revive, a stasis, a spell
shield, a pair of boots — so their outcome is a reviewed product fact, and
Boots of Swiftness declares nothing anywhere in the tree while still being an
item whose whole point is movement.

It was a hand-keyed table in ``item_coverage`` — one of the ten registries 3.8
collapsed to two — and it is the one whose contents survived the collapse.  Its
old name is deliberately not spelled here: the eight retired names are named
only by the absence gate that proves they are gone
(``tests/test_coverage_claims.py``), which scans this package for them.
Keeping it beside the classifier would have made the collapse a rename; moving
it here makes it what it always was — a declaration the classifier reads,
sitting in a home whose whole content is declarations, with an item name for a
key exactly as ``item_effects``, ``item_source`` and ``loadout_rules`` have.

The *vocabulary* is not declared here either: it is
:class:`~.item_behavior.UtilityDimension`, the single home both this payload
and Phase 1's claim table read.  A test asserts this module holds nothing but
the mapping, so the declarative-home exclusion it rides in the behaviour
frontier can never come to cover a dispatch.
"""

from collections.abc import Mapping

from .item_behavior import UtilityDimension

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
