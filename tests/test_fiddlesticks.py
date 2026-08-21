"""Reviewed crowd control for Fiddlesticks (MODULE_CC, wave 4B).

Terrify fears, Reap slows; the doubled branch fears nothing, which is why Q's kind rides its part.
"""

# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC, wave 4B)
# ---------------------------------------------------------------------------

# The Wiki's crowd-control vocabulary, as this module's review read it:
# https://wiki.leagueoflegends.com/en-us/Types_of_Crowd_Control
_CC_CONTROL_WORDS = (
    "airborne",
    "charm",
    "fear",
    "flee",
    "immobiliz",
    "knock",
    "pull",
    "root",
    "sleep",
    "slow",
    "snare",
    "stasis",
    "stun",
    "suppress",
    "taunt",
)
_CC_CHAMPION = "Fiddlesticks"
_CC_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _cc_slot_text(slot):
    """Every cached description of one slot, lowercased."""
    from src.calculator.data_fetcher import get_champion

    return " ".join(
        effect.get("description") or ""
        for ability in get_champion(_CC_CHAMPION)["abilities"].get(slot, [])
        for effect in ability.get("effects", [])
    ).lower()


def _cc_control_hits(slot):
    """The control vocabulary one slot's cached text actually uses."""
    text = _cc_slot_text(slot)
    return [word for word in _CC_CONTROL_WORDS if word in text]


def _cc_kinds(**options):
    """Result key -> the reviewed kinds the slot's parts actually carry."""
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.data_fetcher import get_champion

    parsed = parse_champion_abilities(
        get_champion(_CC_CHAMPION),
        18,
        100.0,
        _CC_RANKS,
        champion_options=options or None,
    )
    carried = {
        key: sorted({part.cc_kind for part in entry.get("parts") or () if part.cc_kind})
        for key, entry in parsed.items()
    }
    return {key: kinds for key, kinds in carried.items() if kinds}


def _cc_timeline_coverage():
    """The campaign's control-token probe, through the public entry."""
    from src.calculator.calculate import calculate_payload

    return calculate_payload(
        {
            "champion": _CC_CHAMPION,
            "level": 18,
            "items": ["Fimbulwinter"],
            "fight_mode": "timed",
            "include_auto_attacks": True,
        }
    )["timeline_coverage"]


class TestReviewedCrowdControl:
    """Terrify fears, Reap slows; the doubled branch fears nothing, which is why Q's kind rides its part.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads the
    reviewed ``cc_kind`` off authored damage events; an unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering, so the
    probe below is the reason these declarations exist.
    """

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        from src.calculator.champions import fiddlesticks

        assert fiddlesticks.MODULE_CC == {"W": "none", "E": "slow", "R": "none"}
        assert fiddlesticks.parse_abilities.cc_kinds == fiddlesticks.MODULE_CC

    def test_each_declared_kind_is_the_word_its_slot_text_uses(self):
        for slot, word in [["Q", "fear"], ["E", "slow"]]:
            assert word in _cc_slot_text(slot), slot

    def test_control_free_slots_name_every_word_their_text_contains(self):
        for slot, expected in [["W", []], ["R", []]]:
            assert _cc_control_hits(slot) == list(expected), slot

    def test_every_reviewed_part_carries_its_kind(self):
        assert _cc_kinds() == {
            "Q": ["fear"],
            "W": ["none"],
            "E": ["slow"],
            "R": ["none"],
        }

    def test_reviewed_kinds_follow_the_other_branch(self):
        """A target that 'cannot be affected by it again' is not feared."""
        assert _cc_kinds(**{"q_target_already_feared": True}) == {
            "Q": ["none"],
            "W": ["none"],
            "E": ["slow"],
            "R": ["none"],
        }

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = _cc_timeline_coverage()

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_packet_prices_every_drain_and_crowstorm_tick():
    """Both channels are one row carrying the tick count the option asks for."""
    from tests import row_review

    assert row_review.parts("Fiddlesticks", "W", w_ticks=8)[0].count == 8
    assert row_review.parts("Fiddlesticks", "R", r_ticks=20)[0].count == 20
