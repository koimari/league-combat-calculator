"""Revision-backed tests for Soraka's offensive slot map."""

import pytest

from src.calculator.champions import soraka
from tests import cc_review
from tests.ability_math import parts_raw_total


def _parse(soraka_data, parse_at, second_hit):
    return parse_at(
        soraka_data,
        18,
        ap=200,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_options={"e_second_hit": second_hit},
    )


def test_soraka_e_counts_initial_hit_and_eruption(soraka_data, parse_at):
    _, abilities = _parse(soraka_data, parse_at, True)

    # W (Astral Infusion) and R (Wish) are declared as zero-damage support
    # casts so the ally-support scanner can emit their sourced heals.
    assert set(abilities) == {"Q", "W", "E", "R"}
    for slot in ("W", "R"):
        assert abilities[slot]["total_raw"] == 0.0
        assert abilities[slot]["parts"] == ()
    assert parts_raw_total(abilities["Q"]["parts"], "magic") == pytest.approx(295.0)
    assert parts_raw_total(abilities["E"]["parts"], "magic") == pytest.approx(500.0)
    assert abilities["E"]["dot_duration"] == 1.5
    assert abilities["E"]["detail"] == "Initial hit + eruption"


def test_soraka_e_can_exclude_eruption(soraka_data, parse_at):
    _, abilities = _parse(soraka_data, parse_at, False)

    assert parts_raw_total(abilities["E"]["parts"], "magic") == pytest.approx(250.0)
    assert "dot_duration" not in abilities["E"]
    assert abilities["E"]["detail"] == "Initial hit only"


def test_soraka_rotation_spends_only_offensive_spell_costs(
    soraka_data, parse_at, fight
):
    stats, abilities = _parse(soraka_data, parse_at, True)
    result = fight(stats, abilities, target_magic_resistance=100)

    assert result["total_damage"] == pytest.approx(397.5)
    # W (Astral Infusion) and R (Wish) join the rotation as zero-damage
    # support casts; neither spends mana the offensive budget counts.
    assert [event["slot"] for event in result["cast_timeline"]] == ["Q", "W", "E", "R"]
    assert abilities["Q"]["resource_cost"] + abilities["E"]["resource_cost"] == 155.0
    assert stats["max_mana"] >= 155.0


class TestReviewedCrowdControl:
    """Soraka's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Soraka")
        assert soraka.MODULE_CC == {"Q": "slow", "E": "root"}
        assert "slowing them by 30% for 1.5 seconds" in cc_review.slot_text(data, "Q")
        # Equinox silences while the zone stands and roots when it erupts;
        # the root is the immobilizing half its two hits apply.
        assert "silences enemies within" in cc_review.slot_text(data, "E")
        assert "root them for a duration" in cc_review.slot_text(data, "E")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Soraka") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Soraka")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestSalvationIsNoDamageNotAnOpenReceipt:
    """P: movement only, gated on a condition this surface cannot establish.

    The slot's prior receipt claimed the movement-speed axis "has no
    ``stat_buff`` key at all".  That was false — ``move_speed_percent`` is a
    live key that Sivir R, Teemo W, Udyr E and Sona E all publish through —
    so these tests pin the REAL blocker (the condition) and the real reason
    the label is ``no_damage`` rather than an Olaf-R open (an ability
    movement buff cannot reach a damage row).
    """

    def test_the_map_reports_the_slot_as_no_damage(self):
        from src.calculator.champions import get_champion_module_contract

        assert get_champion_module_contract("Soraka").coverage == {
            "P": "no_damage",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "modeled",
        }

    def test_p_has_no_damage_clause_anywhere_in_the_cache(self):
        """The verdict is re-derived from the cache, not trusted from prose."""
        import json
        from pathlib import Path

        entries = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))[
            "Soraka"
        ]["abilities"]["P"]

        assert len(entries) == 1
        entry = entries[0]
        assert entry["name"] == "Salvation"
        assert entry["damageType"] is None
        assert entry["affects"] == "Self"
        assert [effect["leveling"] for effect in entry["effects"]] == [[]]

    def test_the_blocker_is_the_condition_not_the_channel(self):
        """Both gates are cached prose, and neither is establishable here."""
        import json
        from pathlib import Path

        text = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))[
            "Soraka"
        ]["abilities"]["P"][0]["effects"][0]["description"]

        assert "90% bonus movement speed" in text
        assert "nearby allied champions" in text
        assert "below 40% of their maximum health" in text
        # The channel the retired receipt said did not exist.
        from src.calculator.champions import sivir

        assert "move_speed_percent" in str(sivir.ASSUMPTIONS)

    def test_the_grant_is_not_published_as_a_stat_buff(self, soraka_data, parse_at):
        _, abilities = _parse(soraka_data, parse_at, True)

        assert "P" not in abilities
        assert not [
            row
            for row in abilities.values()
            if "move_speed_percent" in str(row.get("stat_buff", {}))
        ]

    def test_an_ability_move_speed_buff_cannot_reach_a_damage_row(self):
        """Why no_damage, not an Olaf-R open — the Sivir-P finding, live.

        Swiftmarch is the one item that turns movement speed into damage, and
        it resolves ``adaptive_force_per_total_move_speed`` inside
        ``calculate_total_stats`` from the BUILD's move speed, before any cast.
        An ability ``stat_buff`` rewrites ``stats['move_speed']`` afterwards,
        so it moves ``champion_stats`` and nothing else.  Teemo is the probe
        because it actually publishes such a buff; Soraka's would behave the
        same if its condition were ever establishable.
        """
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.pipeline import FightParams, run_fight

        def fight(w_rank):
            return run_fight(
                get_champion("Teemo"),
                18,
                [get_item_by_name("Swiftmarch")],
                FightParams(
                    target_health=2000.0,
                    target_armor=100.0,
                    target_magic_resistance=50.0,
                    fight_duration_seconds=10.0,
                    ability_ranks={"Q": 5, "W": w_rank, "E": 5, "R": 3},
                    deterministic=True,
                ),
            )

        buffed, unbuffed = fight(5), fight(0)

        assert (
            buffed["champion_stats"]["move_speed"]
            > unbuffed["champion_stats"]["move_speed"]
        )
        for stat in ("attack_damage", "ability_power"):
            assert buffed["champion_stats"][stat] == unbuffed["champion_stats"][stat]
        assert buffed["total_damage"] == pytest.approx(unbuffed["total_damage"])
