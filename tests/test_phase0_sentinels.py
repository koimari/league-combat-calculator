"""Phase 0 sentinels — deferred semantics pinned, with zero ``src/`` change.

A correction with no reachable fixture is a declaration wearing a
correction's clothes, so where Phase 0 declines to change behaviour it says
so in a test instead: the sentinel pins today's answer, names the decision
that deferred it, and goes red on the commit that changes the answer without
re-reading this file.  Each sentinel also pins the size of its own
population, because a sentinel that is green over an empty set proves
nothing (D-26).

This file holds the sentinels as their slices land; C3 lands the first.
"""

from src.calculator.ability_spec import AttackClass, DamageClass
from src.calculator.item_support_effects import cross_participant_authorities
from src.calculator.survival.actions import SurvivalAction, attack_class_of
from src.calculator.survival.transitions import _modifier_applies

from tests.test_item_support_effects import declared_classes_by_producer

# Every producer whose declaration admits AttackClass.OTHER — the packets for
# which the walk's delivery gate is strictly narrower than what they say.
# Pinned, not counted at run time from the same expression the assertions
# use: five of the six producers, all but Blue Dream Bubble.
FROM_ALL_SOURCES_PRODUCERS = 5


class TestIsAttackOrSpellVersusFromAllSources:
    """C3 expresses "from all sources" as ``attack_classes``; the walk's gate
    still prices only attacks and spells (D-04).

    Abyssal Mask's Unmake, Bloodsong's Expose Weakness and Imperial
    Mandate's Command all read "from all sources" on the Wiki, and Carve and
    Vile Decay reduce a resistance without naming a delivery.  All five
    therefore declare every :class:`AttackClass`.  The walk's live gate is
    ``is_ability or basic_attack or source_key == "auto_attacks"``, which is
    Blue Dream Bubble's own restriction — "the next attack or spell they
    receive" — generalised to every modifier before any of them could say
    otherwise, so ``AttackClass.OTHER`` damage (item procs, burns, thorns
    returns) goes unpriced for those five.

    C3 declines to widen the gate: silently widening a gate inside a commit
    labelled "add a typed field" is a second correction riding the first,
    and no committed baseline scenario reaches the branch, so the widening
    would land unfixtured.  When a later slice widens it, this sentinel is
    what turns red.
    """

    def test_the_population_is_five_producers_and_is_not_empty(self):
        """D-26: the sentinel names how much it is green over."""
        admitting_other = {
            source
            for source, declared in declared_classes_by_producer().items()
            if AttackClass.OTHER in declared["attack_classes"]
        }
        assert len(admitting_other) == FROM_ALL_SOURCES_PRODUCERS, (
            "D-04: the sentinel's population moved; a producer changed which "
            "attack classes it declares, and the divergence this pins is "
            f"now over {sorted(admitting_other)}"
        )
        assert admitting_other < set(cross_participant_authorities())

    def test_other_class_damage_is_declared_but_not_priced(self):
        """The divergence itself, at the one predicate that decides it."""
        proc = SurvivalAction(damage_type="magic", source_key="item_burn")
        assert attack_class_of(proc) is AttackClass.OTHER
        unmake = {
            "source": "Abyssal Mask — Unmake",
            "owner": "main",
            "damage_classes": frozenset({DamageClass.MAGIC}),
            "attack_classes": frozenset(AttackClass),
        }
        assert AttackClass.OTHER in unmake["attack_classes"]
        assert not _modifier_applies(unmake, proc, "ally:Lulu"), (
            "D-04: the walk now prices AttackClass.OTHER damage for a "
            "from-all-sources modifier.  That is the correction this "
            "sentinel defers, not a free improvement: re-read Phase 0's "
            "is_attack_or_spell ruling, land it as its own slice with a "
            "declared qualifying population, and delete this sentinel."
        )

    def test_the_one_producer_whose_text_matches_the_gate_is_blue_dream_bubble(self):
        """The gate is not arbitrary — it is one producer's own restriction."""
        declared = declared_classes_by_producer()
        assert declared["Dream Maker — Blue Dream Bubble"]["attack_classes"] == (
            frozenset({AttackClass.BASIC_ATTACK, AttackClass.ABILITY})
        ), "D-04: Blue Dream Bubble is the reading the walk's gate encodes"
