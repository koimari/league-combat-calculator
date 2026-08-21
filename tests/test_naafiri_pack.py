"""Naafiri W (The Call of the Pack) + P (We Are More), and Mordekaiser's
``no_damage`` receipts.

The roadmap slot session closes Naafiri's last two ``out_of_scope`` rows.
They close for different reasons and both are pinned here, together with
the one defect the closure introduced and the sourcing trap that makes
this champion unusually easy to get wrong.

**The slot labels in the game binary are SWAPPED.**  Naafiri's binary
names her two upper spell slots the opposite way round from the live
kit, the wiki and ``data/champions.json``: the record called
``NaafiriR`` IS wiki W, and the record called ``NaafiriW`` IS wiki R.
Every constant this module pins is read off one of those two records, so
a silent re-bind would swap a 20% AD steroid with an ultimate's damage
row.  ``TestSlotLabelsAreSwapped`` re-derives the binding from cooldowns
alone — the only two-channel signal that survives the swap — rather than
trusting the record names or the module's comment.

**W was a real steroid, not a gap.**  The hunt grants bonus attack
damage equal to 20% of TOTAL AD.  The number lives in wiki prose (no
leveling row), corroborated by the binary's ``NaafiriADPercentBoost``.
It is a BUFF-phase ``stat_buff``, so Q/E/R and the Packmate row below
all price off the buffed bonus AD and the fight engine applies it to
autos.

**P was the pack's damage coupling.**  The innate summon deals nothing
itself; what the Packmates contribute on Hounds' Pursuit is R's own
"Physical Damage per Packmate" row times the sourced pack size.  The
wiki R notes publish the resulting per-level totals as a table, and
``TestPackmateTotalsMatchTheWikiTable`` reproduces all six bands
exactly — that table is the arithmetic product of the two independently
sourced rows, so matching it end-to-end is a genuine three-way check.

**The 7x regression pin.**  The first cut of P carried the pack size in
BOTH ``DamagePart.count`` AND ``proc_count``.  ``damage.py``'s
``_add_precomputed_proc_damage`` prices
``sum(part.amount * part.count) * proc_count``, so a 7-Packmate pack was
priced as 49 hits — 1434.72 instead of 204.96, an exact 7x overstatement
that also told ``_apply_basic_amp`` about 49 damage instances.
``TestProcCountSemantics`` pins the fixed contract (one hit per part,
pack size as the proc count) and, at zero resistances, that the fight
row equals ``total_raw`` rather than a multiple of it.
"""

import copy
import json
from pathlib import Path

import pytest

from src.calculator.champions import (
    get_champion_module_meta,
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.naafiri import (
    ASSUMPTIONS,
    _HUNT_AD_PERCENT,
    _HUNT_DURATION,
    _PACKMATE_CAP_BY_LEVEL,
    _PACKMATE_DAMAGE_ATTR,
    _R_CHANNEL_TIME,
    _packmate_count,
)
from src.calculator.data_fetcher import fetch_champion_data
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats

_CHAMPIONS = fetch_champion_data()
_BY_NAME = {data.get("name"): data for data in _CHAMPIONS.values()}
_NAAFIRI = _BY_NAME["Naafiri"]
_WIKI = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Naafiri"]
_BIN = json.loads(
    Path("data/bin/characters/naafiri.bin.json").read_text(encoding="utf-8")
)
# The binary records, addressed by their (swapped) internal names.
_BIN_R_RECORD = _BIN["Characters/Naafiri/Spells/NaafiriRAbility/NaafiriR"]["mSpell"]
_BIN_W_RECORD = _BIN["Characters/Naafiri/Spells/NaafiriWAbility/NaafiriW"]["mSpell"]
_BIN_P_RECORD = _BIN["Characters/Naafiri/Spells/NaafiriPAbility/NaafiriP"]["mSpell"]

_TARGET = {
    "target_max_health": 2000.0,
    "target_current_health": 2000.0,
    "target_missing_health": 0.0,
}


def _data_value(record: dict, name: str) -> list[float]:
    """One named ``DataValues`` row out of a binary spell record."""
    for entry in record.get("DataValues", []):
        if entry.get("name") == name:
            return list(entry.get("values") or [])
    raise AssertionError(f"binary record has no DataValues row {name!r}")


def _parse(level: int, *, options: dict | None = None, ranks: dict | None = None):
    """Parse Naafiri at *level* with no items, mirroring the pipeline."""
    data = copy.deepcopy(_NAAFIRI)
    stats = calculate_total_stats(data, level, [])
    abilities = parse_champion_abilities(
        data,
        level,
        stats["ability_power"],
        ability_ranks=ranks,
        champion_stats=stats,
        target_stats=dict(_TARGET),
        champion_options=options,
    )
    return stats, abilities


def _fight(level: int, *, options: dict | None = None, armor: float = 0.0):
    """One deterministic burst fight at *armor* (default: no mitigation)."""
    params = FightParams(
        target_health=2000.0,
        target_bonus_health=0.0,
        target_armor=armor,
        target_magic_resistance=0.0,
        fight_duration_seconds=5.0,
        auto_attack_uptime=0.0,
        one_rotation=True,
        include_actives=True,
        cast_order=None,
        auto_attacks_only=False,
        ability_ranks=None,
        champion_options=options,
        deterministic=True,
    )
    return run_fight(copy.deepcopy(_NAAFIRI), level, [], params)


# ---------------------------------------------------------------------------
# The slot-label swap — re-derived from cooldowns, not from record names
# ---------------------------------------------------------------------------


class TestSlotLabelsAreSwapped:
    """Bind the binary records to live slots by their only sound signal.

    Cooldown is the one quantity both channels publish independently, so
    it is the only way to bind a binary record to a live slot without
    reusing the very names the swap corrupts.  The binary pads its rank
    arrays to 7 slots with the rank-1 value repeated at index 0, so
    ranks 1..N live at indices 1..N.
    """

    def test_binary_R_record_carries_the_wiki_W_cooldowns(self):
        wiki_w = _WIKI["abilities"]["W"][0]["cooldown"]["modifiers"][0]["values"]
        assert wiki_w == [26, 24, 22, 20, 18]
        padded = _BIN_R_RECORD["cooldownTime"]
        assert [round(v) for v in padded[1:6]] == wiki_w

    def test_binary_W_record_carries_the_wiki_R_cooldowns(self):
        wiki_r = _WIKI["abilities"]["R"][0]["cooldown"]["modifiers"][0]["values"]
        assert wiki_r == [110, 95, 80]
        padded = _BIN_W_RECORD["cooldownTime"]
        assert [round(v) for v in padded[1:4]] == wiki_r

    def test_the_two_records_are_not_interchangeable(self):
        """The swap is real: neither record fits the other's cooldowns."""
        wiki_w = _WIKI["abilities"]["W"][0]["cooldown"]["modifiers"][0]["values"]
        assert [round(v) for v in _BIN_W_RECORD["cooldownTime"][1:6]] != wiki_w

    def test_ad_steroid_lives_on_the_record_that_is_really_W(self):
        """NaafiriADPercentBoost sits on the wiki-W record, not wiki R."""
        assert _data_value(_BIN_R_RECORD, "NaafiriADPercentBoost")
        with pytest.raises(AssertionError):
            _data_value(_BIN_W_RECORD, "NaafiriADPercentBoost")

    def test_packmate_damage_modifier_lives_on_the_record_that_is_really_R(self):
        """The 10%-bonus-AD-per-Packmate modifier sits on the wiki-R record."""
        modifier = _data_value(_BIN_W_RECORD, "PackmateModifier")
        assert modifier[0] == pytest.approx(0.10, abs=1e-6)


# ---------------------------------------------------------------------------
# W — the hunt's 20%-of-total-AD steroid
# ---------------------------------------------------------------------------


class TestHuntSteroid:
    def test_module_percent_matches_the_binary(self):
        """20.0 in the module == NaafiriADPercentBoost 0.20 in the game file."""
        binary = _data_value(_BIN_R_RECORD, "NaafiriADPercentBoost")
        assert all(value == pytest.approx(0.20, abs=1e-6) for value in binary)
        assert _HUNT_AD_PERCENT / 100.0 == pytest.approx(binary[0], abs=1e-6)

    def test_hunt_duration_matches_the_binary(self):
        binary = _data_value(_BIN_R_RECORD, "Duration")
        assert _HUNT_DURATION == pytest.approx(binary[0])

    def test_steroid_is_unranked(self):
        """Both channels agree the 20% does not scale with W rank."""
        binary = _data_value(_BIN_R_RECORD, "NaafiriADPercentBoost")
        assert len(set(round(v, 6) for v in binary)) == 1

    def test_w_does_not_exist_at_level_one(self):
        """Level 1 has one skill point and the default ladder spends it on Q.

        W therefore has no natural rank until level 2 and the parser
        emits no W row at all — the levels below start at 2 for that
        reason, not because level 1 is inconvenient.
        """
        _, level_one = _parse(1)
        assert "W" not in level_one
        _, level_two = _parse(2)
        assert level_two["W"]["rank"] == 1

    @pytest.mark.parametrize("level", [2, 6, 11, 18, 20])
    def test_stat_buff_is_twenty_percent_of_total_ad(self, level):
        stats, abilities = _parse(level)
        expected = _HUNT_AD_PERCENT / 100.0 * stats["attack_damage"]
        assert abilities["W"]["stat_buff"] == {
            "bonus_attack_damage": pytest.approx(expected)
        }

    def test_buff_is_granted_as_bonus_ad_off_total_ad(self):
        """'20% AD' means 20% of TOTAL AD granted as BONUS AD.

        At level 18 with no items total AD is 89 and bonus AD is 0, so a
        buff computed off bonus AD would be 0 — this pins the base.
        """
        stats, abilities = _parse(18)
        assert stats["attack_damage"] == pytest.approx(89.0)
        assert stats["bonus_attack_damage"] == pytest.approx(0.0)
        assert abilities["W"]["stat_buff"]["bonus_attack_damage"] == pytest.approx(17.8)

    def test_hunt_off_withholds_the_whole_steroid(self):
        _, abilities = _parse(18, options={"w_hunt": False})
        assert "stat_buff" not in abilities["W"]
        assert "w_hunt off" in abilities["W"]["detail"]

    def test_w_itself_deals_no_damage(self):
        """The steroid is a buff row, not a damage row."""
        _, abilities = _parse(18)
        assert abilities["W"]["total_raw"] == pytest.approx(0.0)

    @pytest.mark.parametrize("slot,ratio", [("Q", 1.4), ("E", 1.2), ("R", 1.0)])
    def test_downstream_slots_consume_the_buffed_bonus_ad(self, slot, ratio):
        """Q/E/R gain exactly (their bonus-AD ratio) x the hunt buff.

        Ratios at max rank: Q = 20% + 10 x 8% bleed + 40% recast minimum
        = 1.4, E = 40% dash + 80% Flurry = 1.2, R = 100%.
        """
        _, off = _parse(18, options={"w_hunt": False})
        _, on = _parse(18, options={"w_hunt": True})
        buff = on["W"]["stat_buff"]["bonus_attack_damage"]
        gain = on[slot]["total_raw"] - off[slot]["total_raw"]
        assert gain == pytest.approx(ratio * buff)


# ---------------------------------------------------------------------------
# P — the Packmate cap and the pack's share of Hounds' Pursuit
# ---------------------------------------------------------------------------


class TestPackmateCap:
    def test_module_table_matches_the_binary_breakpoints(self):
        """Cap starts at 2 and gains +1 at levels 9, 12 and 15."""
        part = _BIN_P_RECORD["mSpellCalculations"]["PackmateCap"]["mFormulaParts"][0]
        assert part["mLevel1Value"] == pytest.approx(2.0)
        breakpoints = {
            bp["mLevel"]: bp["mAdditionalBonusAtThisLevel"]
            for bp in part["mBreakpoints"]
        }
        assert breakpoints == {9: 1.0, 12: 1.0, 15: 1.0}
        # The module's own table, expressed as the same step function.
        assert _PACKMATE_CAP_BY_LEVEL == ((15, 5, 7), (12, 4, 6), (9, 3, 5), (1, 2, 4))

    @pytest.mark.parametrize("level", list(range(1, 21)))
    def test_base_cap_reproduces_the_binary_step_function(self, level):
        expected = 2 + sum(1 for breakpoint in (9, 12, 15) if level >= breakpoint)
        assert _packmate_count(level, hunt=False) == expected

    @pytest.mark.parametrize("level", list(range(1, 21)))
    def test_hunt_raises_the_cap_by_exactly_two(self, level):
        """Wiki W note: the hunt raises the cap to 4/5/6/7 by level."""
        assert (
            _packmate_count(level, hunt=True) - _packmate_count(level, hunt=False) == 2
        )

    def test_cap_fails_closed_below_level_one(self):
        with pytest.raises(ValueError, match="no sourced Packmate cap"):
            _packmate_count(0, hunt=False)


class TestPackmateTotalsMatchTheWikiTable:
    """The wiki R notes' packmate-total table, reproduced end to end.

    Each band is the product of two independently sourced rows — R's
    "Physical Damage per Packmate" and We Are More's cap — so hitting the
    published total exactly is a real three-way agreement, not a restated
    constant.  The second column is the hunt-raised cap and therefore
    also carries the hunt's bonus AD through the row's 10% bonus-AD term.
    """

    @pytest.mark.parametrize(
        "level,hunt_off_total,hunt_on_total",
        [
            (6, 25.0, 55.04),
            (11, 60.0, 107.3),
            (18, 137.5, 204.96),
        ],
    )
    def test_bands(self, level, hunt_off_total, hunt_on_total):
        _, off = _parse(level, options={"w_hunt": False})
        _, on = _parse(level, options={"w_hunt": True})
        assert off["passive"]["total_raw"] == pytest.approx(hunt_off_total)
        assert on["passive"]["total_raw"] == pytest.approx(hunt_on_total)

    def test_hunt_off_bands_are_the_flat_row_times_the_cap(self):
        """With no bonus AD the totals are exactly cap x the flat row."""
        for level, flat, cap in ((6, 12.5, 2), (11, 20.0, 3), (18, 27.5, 5)):
            _, off = _parse(level, options={"w_hunt": False})
            assert off["passive"]["total_raw"] == pytest.approx(flat * cap)

    def test_row_is_sourced_from_R_not_reinvented(self):
        """The attribute the module reads is a real cached R leveling row.

        Leveling rows hang off each *effect* of an ability entry, never
        off the entry itself (``abilities.R[0]`` has no ``leveling``
        key at all), so the search has to descend one level.
        """
        assert _PACKMATE_DAMAGE_ATTR == "Physical Damage per Packmate"
        rows = [
            row
            for entry in _WIKI["abilities"]["R"]
            for effect in entry.get("effects") or []
            for row in effect.get("leveling") or []
        ]
        names = [row.get("attribute") for row in rows]
        assert names, "R publishes no leveling rows at all — sourcing moved"
        assert _PACKMATE_DAMAGE_ATTR in names
        # ...and it is the flat/bonus-AD pair the module prices, not a
        # same-named row that drifted to other values.
        row = next(r for r in rows if r.get("attribute") == _PACKMATE_DAMAGE_ATTR)
        assert [m["values"] for m in row["modifiers"]] == [
            [12.5, 20, 27.5],
            [10, 10, 10],
        ]
        assert row["modifiers"][1]["units"] == ["% bonus AD"] * 3


class TestProcCountSemantics:
    """Regression pin for the 7x Packmate overstatement.

    ``_add_precomputed_proc_damage`` prices
    ``sum(part.amount * part.count) * proc_count``.  Carrying the pack
    size in both fields squared it (7 Packmates -> 49 hits).
    """

    @pytest.mark.parametrize("level", [6, 11, 18])
    @pytest.mark.parametrize("hunt", [True, False])
    def test_one_hit_per_part_and_pack_size_as_proc_count(self, level, hunt):
        _, abilities = _parse(level, options={"w_hunt": hunt})
        passive = abilities["passive"]
        count = _packmate_count(level, hunt=hunt)
        assert len(passive["parts"]) == 1
        assert passive["parts"][0].count == 1
        assert passive["proc_count"] == count
        assert passive["total_raw"] == pytest.approx(passive["parts"][0].amount * count)

    @pytest.mark.parametrize("level", [6, 11, 18])
    @pytest.mark.parametrize("hunt", [True, False])
    def test_fight_row_equals_total_raw_at_zero_resistances(self, level, hunt):
        """The exact assertion the buggy build failed by a factor of N."""
        _, abilities = _parse(level, options={"w_hunt": hunt})
        result = _fight(level, options={"w_hunt": hunt}, armor=0.0)
        assert result["breakdown"]["passive"]["total_damage"] == pytest.approx(
            abilities["passive"]["total_raw"]
        )

    def test_seven_packmate_case_is_not_forty_nine_hits(self):
        """The literal bug: L18 hunt-on was 1434.72 instead of 204.96."""
        _, abilities = _parse(18, options={"w_hunt": True})
        assert _packmate_count(18, hunt=True) == 7
        assert abilities["passive"]["total_raw"] == pytest.approx(204.96)
        assert abilities["passive"]["total_raw"] != pytest.approx(204.96 * 7)

    def test_damage_events_are_one_per_packmate_at_the_channel_end(self):
        _, abilities = _parse(18, options={"w_hunt": True})
        events = abilities["passive"]["damage_events"]
        assert len(events) == 7
        assert all(event["time"] == pytest.approx(_R_CHANNEL_TIME) for event in events)
        assert all(event["damage_type"] == "physical" for event in events)


class TestPackRowFailsClosed:
    def test_row_is_withheld_while_hounds_pursuit_is_unlearned(self):
        """No R rank means no sourced Packmate damage row at all."""
        _, abilities = _parse(11, ranks={"Q": 5, "W": 5, "E": 5, "R": 0})
        passive = abilities["passive"]
        assert passive["total_raw"] == pytest.approx(0.0)
        assert passive["parts"] == ()
        assert "unlearned" in passive["detail"]

    def test_packmate_basic_attacks_are_documented_not_priced(self):
        """The receipt must name the gap rather than invent a number."""
        assert any(
            "Packmate BASIC ATTACKS are documented-not-modeled" in text
            for text in ASSUMPTIONS
        )
        assert any("PackmateTotalDamage" in text for text in ASSUMPTIONS)

    def test_movement_speed_rider_is_documented_not_modeled(self):
        _, abilities = _parse(18)
        assert "move_speed" not in abilities["W"].get("stat_buff", {})
        assert any("bonus movement speed" in text for text in ASSUMPTIONS)


# ---------------------------------------------------------------------------
# Coverage + option surface
# ---------------------------------------------------------------------------


class TestCoverageAndOptions:
    def test_naafiri_has_no_out_of_scope_slots_left(self):
        # Every slot emits a priced row, so the contract DERIVES the
        # coverage from SLOTS and the module declares no MODULE_COVERAGE
        # (restating the derived table is a contract error).
        coverage = get_champion_module_meta("Naafiri")["coverage"]
        assert coverage == {slot: "modeled" for slot in "PQWER"}

    def test_w_hunt_option_is_exposed_and_defaults_on(self):
        meta = get_champion_options_meta("Naafiri")
        hunt = next(o for o in meta["options"] if o["key"] == "w_hunt")
        assert hunt["type"] == "bool"
        assert hunt["default"] is True

    def test_mordekaiser_has_no_out_of_scope_slots_left(self):
        """Morde's W and R are priced, not relabelled zero-damage rows.

        W's Potential Shield recast heal is authored by the E8a
        grey-health primitive and R's soul drain by this branch's
        module-owned self-heal rule, so both slots are ``modeled`` and
        the contract derives the whole table from SLOTS.
        """
        coverage = get_champion_module_meta("Mordekaiser")["coverage"]
        assert coverage == {slot: "modeled" for slot in "PQWER"}
        assert "out_of_scope" not in set(coverage.values())
