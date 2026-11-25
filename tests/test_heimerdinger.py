"""Reviewed crowd control for Heimerdinger (MODULE_CC).

Both grenades slow every enemy they damage; turrets and rockets do not.
"""

from tests import cc_review

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC)
# ---------------------------------------------------------------------------

_CC_CHAMPION = "Heimerdinger"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CC = cc_review.ChampionReview(_CC_CHAMPION, _CC_RANKS)


class TestReviewedCrowdControl:
    """Both grenades slow every enemy they damage; turrets and rockets do not.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import heimerdinger

        assert heimerdinger.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": "slow",
            "P": "none",
            "R": "none",
        }

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["E", "slow"]]:
            assert word in _CC.slot_text(slot), slot

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["Q", []], ["W", []]]:
            assert _CC.control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _CC.kinds() == {"Q": ["none"], "W": ["none"], "E": ["slow"]}

    def test_reviewed_kinds_follow_the_other_branch(self):
        """The UPGRADE!!! grenade slows by the same 35%."""
        assert _CC.kinds(e_upgrade=1) == {
            "Q": ["none"],
            "W": ["none"],
            "E": ["slow"],
        }


def test_the_turret_packet_carries_pet_damage_and_its_cadence():
    """Q is two rows — the turret's attacks and its beam — on one schedule."""
    from tests import row_review

    turret = row_review.entry(
        "Heimerdinger", "Q", q_turrets=3, q_turret_attacks=3, q_beams=1
    )
    assert turret["total_raw"] > 0
    assert turret["event_order_certified"]
    assert len(turret["parts"]) == 2


def test_the_turret_shot_follows_q_rank_not_champion_level():
    """The binary HeimerdingerQ BaseDamage row is per Q rank (7/11/15/19/23).

    At level 11 Q is already rank 5, so a shot with no AP is 23. Reading the
    row as a 7-to-23 ramp over champion level priced it at 16.4 there.
    """
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.champions.skill_orders import get_ability_rank
    from src.calculator.data_fetcher import get_champion
    from src.calculator.stats import calculate_total_stats

    data = get_champion("Heimerdinger")
    stats = calculate_total_stats(data, 11, [])
    assert get_ability_rank("Q", 11, "Heimerdinger") == 5
    parsed = parse_champion_abilities(
        data,
        11,
        0.0,
        champion_stats=dict(stats, ability_power=0.0),
        champion_options={"q_turrets": 1, "q_turret_attacks": 1, "q_beams": 1},
    )
    shot, beam = parsed["Q"]["parts"]
    assert shot.amount == 23.0
    assert beam.amount == 120.0
