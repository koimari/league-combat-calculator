"""Reviewed crowd control for K'Sante (MODULE_CC, wave 4B).

Ntofo slows, Path Maker stuns outside All Out, All Out itself stuns.
"""

from functools import partial

import pytest

from tests import cc_review
from tests import champion_closure as closure

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "K'Sante"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Ntofo slows, Path Maker stuns outside All Out, All Out itself stuns.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import ksante
        from src.calculator.champions.slot_cc import CC_PER_PART

        assert ksante.MODULE_CC == {
            "Q": "slow",
            "W": CC_PER_PART,
            "R": "stun",
            "P": "none",
            "E": "none",
        }
        assert ksante.parse_abilities.cc_kinds == ksante.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["Q", "slow"], ["W", "stun"], ["R", "stun"]]:
            assert word in _CC.slot_text(slot), slot

    def test_every_reviewed_part_carries_its_kind(self):
        """E prices no damage part, so its declaration lands nowhere."""
        assert _CC.kinds() == {
            "Q": ["slow"],
            "W": ["stun"],
            "R": ["stun"],
            "passive": ["none"],
        }

    def test_reviewed_kinds_follow_the_other_branch(self):
        """All Out: Path Maker does not apply its knock back and stun, so W is 'none'."""
        assert _CC.kinds(all_out=True) == {
            "Q": ["slow"],
            "W": ["none"],
            "R": ["stun"],
            "passive": ["none"],
        }

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _CC.coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


# Level 18, ranks Q5/W5/E5/R3, no items, six seconds of autos at full uptime
# into a 3000-HP Aatrox whose own resistances mitigate.
_closure_fight = partial(
    closure.combat,
    mode="time_based",
    duration=6.0,
    include_autos=True,
    auto_uptime=1.0,
    target_health=3000.0,
    enemy=closure.AATROX,
)
_closure_parse = partial(closure.parse, target=closure.TARGET_3000)


# ---------------------------------------------------------------------------
# K'Sante — All Out 20% omnivamp
# ---------------------------------------------------------------------------


def _omnivamp_heals(combat):
    return [
        h
        for h in combat.get("healing_events", [])
        if h.get("attacker") == "main" and h.get("source", "").startswith("Omnivamp")
    ]


def test_ksante_all_out_omnivamp_heals_twenty_percent_of_attack_packets():
    combat = _closure_fight("KSante", options={"all_out": True})
    heals = _omnivamp_heals(combat)
    assert heals, "All Out omnivamp heal missing"
    attack_damage = sum(
        e.get("damage", 0.0) for e in closure.main_damage_events(combat, "auto_attacks")
    )
    # Per-packet heals are rounded to 0.1, so the summed heal can differ
    # from the exact 20% by a fraction of a point (autoresearch pass 30
    # changed the R bonus-pen channel, shifting the packet mix).
    assert sum(h["amount"] for h in heals) == pytest.approx(
        0.20 * attack_damage, abs=0.25
    )
    survival = closure.main_survival(combat)
    assert survival["healing_received"] == pytest.approx(0.20 * attack_damage, abs=0.25)


def test_ksante_without_all_out_authors_no_omnivamp():
    combat = _closure_fight("KSante")
    assert not _omnivamp_heals(combat)
    assert closure.main_survival(combat)["healing_received"] == 0.0
