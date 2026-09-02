"""Sylas's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import get_champion_module_contract, sylas
from tests import cc_review, rider_probe, row_review


class TestReviewedCrowdControl:
    """Sylas' whole kit is reviewed once Q's lump declares its own time."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Sylas")
        assert sylas.MODULE_CC == {
            "W": "none",
            "E": "immobilize",
            "Q": "slow",
            "P": "none",
            "R": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "slowing them for 1.5 seconds" in cc_review.slot_text(data, "Q")
        # Abduct stuns on the chain hit and knocks up on arrival - two
        # immobilize kinds, so the reviewed kind is the un-narrowed one.
        assert "stun them for 0.5 seconds" in cc_review.slot_text(data, "E")
        assert "knocks them up for 0.5 seconds" in cc_review.slot_text(data, "E")

    def test_chain_lash_declares_its_lumped_row_at_the_cast(self):
        """The packet prices the lash and the 0.6s-delayed explosion in one
        part, so the row states when the ledger sees it instead of being
        split into the two cached rows - which re-prices the fight."""
        from src.calculator.champions import parse_champion_abilities
        from src.calculator.stats import calculate_total_stats

        data = cc_review.kit("Sylas")
        parsed = parse_champion_abilities(
            data, 18, 100.0, champion_stats=calculate_total_stats(data, 18, [])
        )
        assert [part.time_offset for part in parsed["Q"]["parts"]] == [0.0]
        assert sylas.SLOTS.packet_spec["slots"]["Q"]["base"] == [
            100.0,
            175.0,
            250.0,
            325.0,
            400.0,
        ]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Sylas") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Sylas")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestPetriciteBurst:
    """P: the Unshackled empowered attack, once per stocked stack."""

    def test_the_cached_entry_carries_no_number_at_all(self):
        """Why both ratios are module constants rather than cached reads."""
        assert [
            leveling
            for effect in cc_review.kit("Sylas")["abilities"]["P"][0]["effects"]
            for leveling in effect.get("leveling") or []
        ] == []
        text = cc_review.slot_text(cc_review.kit("Sylas"), "P")
        assert "130% ad (+ 30% ap) magic damage to the primary target" in text
        assert "stacking up to 3 times" in text

    def test_the_empowered_swing_is_a_conversion_not_a_bonus_row(self):
        """130% AD + 30% AP REPLACES the swing; the module owns the remainder.

        Batch K's evidence: the ratio is 130% of a whole auto, and the
        cached note "Spellblade damage does not get converted to magic
        damage" only parses if the attack's own damage IS converted.
        Pricing it as an added magic row would invent roughly one whole
        auto per stack AND mitigate the real swing against armor instead
        of magic resistance, so P rides ``auto_attack_conversion`` (the
        Galio Colossal Smash channel) and supplies only
        ``1.30 x AD + 0.30 x AP - AD``.
        """
        entry = row_review.entry("Sylas", "passive", passive_procs=3)
        assert "on_hit" not in entry
        assert entry["parts"] == ()
        conversion = entry["auto_attack_conversion"]
        assert conversion["damage_type"] == "magic"
        assert conversion["count"] == 3
        assert conversion["bonus_raw"] == pytest.approx(1.30 * 200 + 0.30 * 200 - 200)

    def test_three_stocked_attacks_reach_the_fight_total(self):
        result = rider_probe.fight("Sylas", champion_options={"passive_procs": 3})
        plain = rider_probe.fight("Sylas", champion_options={"passive_procs": 0})
        # The converted swings raise the AUTO stream, not the ability ledger.
        assert result["ability_damage"] == pytest.approx(plain["ability_damage"])
        assert result["auto_attack_damage"] > plain["auto_attack_damage"]
        assert result["total_damage"] > plain["total_damage"]

    def test_spending_no_stack_prices_nothing(self):
        """The default: Unshackled stacks are caster state, so 0 by default."""
        default = rider_probe.fight("Sylas")
        explicit = rider_probe.fight("Sylas", champion_options={"passive_procs": 0})
        assert default["total_damage"] == pytest.approx(explicit["total_damage"])
        entry = row_review.entry("Sylas", "passive")
        assert entry["auto_attack_conversion"]["count"] == 0
        assert entry["auto_attack_conversion"]["bonus_raw"] > 0.0


class TestTheSlotThatStaysOutOfScope:
    """R (Hijack) casts a copy of another champion's ultimate."""

    def test_the_module_names_the_missing_axis(self):
        assert get_champion_module_contract("Sylas").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "out_of_scope",
        }
        assert "another champion's ultimate" in sylas.__doc__
        assert "cross-champion ultimate-import kernel" in sylas.__doc__
