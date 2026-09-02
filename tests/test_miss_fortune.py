"""Miss Fortune — Love Tap's ladder, Strut's steroid, and the reviewed CC.

The MODULE_CC declaration is not decoration: a control-armed holder
shield (Fimbulwinter's Everlasting) reads a control marker off ability
damage events, and one unreviewed ability packet makes the whole timed
fight fall back to coarse ordering.  These tests hold the declaration to
the cached text it was read from, and prove it reaches the event ledger.

P (Love Tap) is priced off the game-binary total-AD ladder
(``_LOVE_TAP_LEVEL1_AD_RATIO`` 0.5 + 0.1 per breakpoint at levels
4/7/9/11/13/20/25/30), cross-checked against the cached wiki "Per-Level
Scaling" row at parse time.  The ladder is verified at its endpoints —
level 1 (0.5), 4 (0.6), 11 (0.9), 18 (1.0) and 20 (1.1, the binary-only
tier past the 6-entry cached row, and the highest MAX_LEVEL reaches) —
standalone and through the parsed row.

W (Strut) carries no damage instance; its row is the sourced Bonus
Attack Speed active through ``stat_buff``, so it must publish a named
zero-damage row and never contribute a point to a fight total.
"""

import json

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import (
    get_champion_module_contract,
    get_champion_options_meta,
    miss_fortune,
)
from src.calculator.champions.engine import SlotCtx
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from tests import cc_review, rider_probe, row_review

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {"E": "slowing them by 40%"}

# No reviewed-absent slot's cached text carries a control word at all.
UNCONTROLLED_MENTIONS: dict[str, list[str]] = {}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Miss Fortune")


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert miss_fortune.MODULE_CC == {
            "Q": "none",
            "E": "slow",
            "R": "none",
            "P": "none",
            "W": "none",
        }
        for slot, phrase in QUOTED.items():
            assert phrase in cc_review.slot_text(cached, slot), slot

    def test_reviewed_absences_read_the_whole_slot(self, cached):
        """A "none" is a slot that was read, not a slot that was skipped."""
        for slot, kind in miss_fortune.MODULE_CC.items():
            if kind != "none":
                continue
            hits = cc_review.any_control_hits(cached, slot)
            assert hits == UNCONTROLLED_MENTIONS.get(slot, []), slot

    def test_every_ability_event_carries_the_review(self, cached):
        """A declared kind lands on every part of the slot's row that can
        carry it; the roster census counts the slots with no such part."""
        parsed = miss_fortune.parse_abilities(cached, 18, 100.0)
        for slot, kind in miss_fortune.MODULE_CC.items():
            parts = cc_review.declared_parts(parsed, slot)
            assert {part.cc_kind for part in parts} <= {kind}, slot

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        """The campaign's control-token probe, through the public entry."""
        coverage = calculate_payload(
            {
                "champion": "Miss Fortune",
                "level": 18,
                "items": ["Fimbulwinter"],
                "fight_mode": "timed",
                "include_auto_attacks": True,
            }
        )["timeline_coverage"]

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
        assert coverage["coarse_sources"] == []


class TestLoveTap:
    """P: the AD-scaled bonus on an attack that tags a NEW enemy."""

    def test_the_ratio_is_the_cached_six_band_row(self, cached):
        """The champion row is 50 : 100; the minion half-row is not read."""
        champion_band, minion_band = [
            leveling["modifiers"][0]["values"]
            for effect in cached["abilities"]["P"][0]["effects"]
            for leveling in effect["leveling"]
        ]
        assert champion_band == [50, 60, 70, 80, 90, 100]
        assert minion_band == [25, 30, 35, 40, 45, 50]
        # Level 18 is past the last breakpoint (13), so the ratio is 100%
        # of the 200 total AD row_review fixes.
        on_hit = row_review.entry("Miss Fortune", "passive")["on_hit"]
        assert on_hit["damage_type"] == "physical"
        assert on_hit["damage_per_hit"] == pytest.approx(200.0)
        assert on_hit["max_procs"] == 1

    def test_one_tap_reaches_the_fight_total_by_default(self):
        result = rider_probe.fight("Miss Fortune")
        row = result["breakdown"][rider_probe.RIDER_ROW]
        assert row["name"] == "Love Tap (on-hit)"
        assert row["count"] == 1
        # Eight swings, not ten: the shared probe's legacy window is 8s at
        # 0.8 uptime (6.4 effective seconds) and Strut's +100% puts Miss
        # Fortune's fight attack speed at 1.319.  The tap itself is what
        # this row is about, and it is unchanged.
        assert result["breakdown"]["auto_attacks"]["count"] == 8
        assert row["total_damage"] == pytest.approx(48.0, abs=0.05)

    def test_tagging_more_targets_prices_more_taps(self):
        result = rider_probe.fight("Miss Fortune", champion_options={"p_procs": 3})
        row = result["breakdown"][rider_probe.RIDER_ROW]
        assert row["count"] == 3
        assert row["total_damage"] == pytest.approx(144.0, abs=0.05)

    def test_no_tap_prices_nothing(self):
        result = rider_probe.fight("Miss Fortune", champion_options={"p_procs": 0})
        assert rider_probe.RIDER_ROW not in result["breakdown"]


class TestStrut:
    """W: the sourced attack-speed active, through stat_buff."""

    def test_the_buff_is_the_cached_bonus_attack_speed_row(self, cached):
        rows = {
            leveling["attribute"]: leveling["modifiers"][0]["values"]
            for effect in cached["abilities"]["W"][0]["effects"]
            for leveling in effect.get("leveling") or []
        }
        assert rows["Bonus Attack Speed"] == [40, 55, 70, 85, 100]
        entry = row_review.entry("Miss Fortune", "W")
        assert entry["stat_buff"] == {"bonus_attack_speed": 100.0}
        assert entry["total_raw"] == 0.0

    def test_every_slot_now_prices_something(self):
        assert get_champion_module_contract("Miss Fortune").coverage == dict.fromkeys(
            "PQWER", "modeled"
        )


# ---------------------------------------------------------------------------
# P (Love Tap) — the game-binary ratio ladder
# ---------------------------------------------------------------------------


_P_ABILITY = get_champion("Miss Fortune")["abilities"]["P"][0]
# The cached wiki "Per-Level Scaling" row the ladder is cross-checked
# against at parse time (first of two occurrences — the second is the
# halved anti-minion row and is not read here).
_WIKI_PER_LEVEL_SCALING_PERCENT = [50, 60, 70, 80, 90, 100]
# level -> expected total-AD ratio.  1/4/11/18 land on the cached row; 20
# is the binary-only 7th tier past the row's end.
_RATIO_ENDPOINTS = {1: 0.5, 4: 0.6, 11: 0.9, 18: 1.0, 20: 1.1}


def _ratio_ctx(level):
    return SlotCtx(slot="P", champion_name="Miss Fortune", level=level)


class TestLoveTapRatioLadder:
    def test_tier_breakpoints_pinned(self):
        # The tier function counts breakpoints reached at-or-before the
        # level; every cited endpoint lands on the expected tier index.
        assert miss_fortune._LOVE_TAP_BREAKPOINT_LEVELS == (
            4,
            7,
            9,
            11,
            13,
            20,
            25,
            30,
        )
        assert miss_fortune._love_tap_tier(1) == 0
        assert miss_fortune._love_tap_tier(3) == 0
        assert miss_fortune._love_tap_tier(4) == 1
        assert miss_fortune._love_tap_tier(11) == 4
        assert miss_fortune._love_tap_tier(13) == 5
        assert miss_fortune._love_tap_tier(18) == 5  # 20-breakpoint not reached
        assert miss_fortune._love_tap_tier(20) == 6

    @pytest.mark.parametrize(
        ("level", "expected_ratio"), sorted(_RATIO_ENDPOINTS.items())
    )
    def test_ratio_at_verified_endpoints(self, level, expected_ratio):
        # Recompute independently of the module's own tier arithmetic:
        # level1 + step * tier, using the module's public constants.
        tier = miss_fortune._love_tap_tier(level)
        recomputed = (
            miss_fortune._LOVE_TAP_LEVEL1_AD_RATIO
            + miss_fortune._LOVE_TAP_BREAKPOINT_STEP * tier
        )
        assert recomputed == pytest.approx(expected_ratio)
        assert miss_fortune._love_tap_ad_ratio(
            _ratio_ctx(level), _P_ABILITY
        ) == pytest.approx(expected_ratio)

    def test_ratio_cross_checked_against_cached_wiki_row(self):
        # The module asserts its game-binary ladder against the cached
        # "Per-Level Scaling" row at parse time; this pins that the cache
        # actually carries the row the module depends on, so a patch pull
        # that drops or reorders it fails here instead of silently
        # disabling the module's own cross-check.
        leveling = [
            row
            for effect in _P_ABILITY["effects"]
            for row in effect.get("leveling", [])
            if row.get("attribute") == "Per-Level Scaling"
        ]
        assert leveling, "Love Tap lost its cached Per-Level Scaling row"
        assert leveling[0]["modifiers"][0]["values"] == _WIKI_PER_LEVEL_SCALING_PERCENT
        for level, expected_ratio in _RATIO_ENDPOINTS.items():
            tier = miss_fortune._love_tap_tier(level)
            if tier < len(_WIKI_PER_LEVEL_SCALING_PERCENT):
                assert _WIKI_PER_LEVEL_SCALING_PERCENT[tier] / 100.0 == pytest.approx(
                    expected_ratio
                )

    def test_drifted_cache_row_fails_loud(self):
        # A patch that moves the cached row out from under the binary
        # ladder must raise, naming the ability — never silently keep
        # pricing the stale (or now-mismatched) coefficient.
        ability = json.loads(json.dumps(_P_ABILITY))
        for effect in ability["effects"]:
            for row in effect.get("leveling", []):
                if row.get("attribute") == "Per-Level Scaling":
                    row["modifiers"][0]["values"] = [1, 1, 1, 1, 1, 1]
                    break
            else:
                continue
            break
        with pytest.raises(ValueError) as excinfo:
            miss_fortune._love_tap_ad_ratio(_ratio_ctx(11), ability)
        assert "Love Tap" in str(excinfo.value)
        assert "drifted" in str(excinfo.value)

    def test_missing_cache_row_fails_loud(self):
        ability = {"name": "Love Tap", "effects": [{"leveling": []}]}
        with pytest.raises(ValueError) as excinfo:
            miss_fortune._love_tap_ad_ratio(_ratio_ctx(11), ability)
        assert "Love Tap" in str(excinfo.value)
        assert "missing" in str(excinfo.value)


class TestLoveTapLadderInTheFight:
    @pytest.mark.parametrize("level", sorted(_RATIO_ENDPOINTS))
    def test_the_parsed_row_carries_the_ladder_ratio(self, level):
        cached = get_champion("Miss Fortune")
        stats = calculate_total_stats(cached, level, [])
        parsed = miss_fortune.parse_abilities(
            cached,
            level,
            stats.get("ability_power", 0.0),
            champion_stats=stats,
        )
        expected = _RATIO_ENDPOINTS[level] * float(stats["attack_damage"])
        assert parsed["passive"]["on_hit"]["damage_per_hit"] == pytest.approx(
            expected, abs=0.05
        )
        assert parsed["passive"]["on_hit"]["damage_type"] == "physical"

    def test_one_tap_is_capped_however_long_the_fight_runs(self):
        # max_procs caps the row at the selected tap count regardless of
        # how many autos land — a sustained fight must not multiply Love
        # Tap's one-time mark.
        short = rider_probe.rider_row("Miss Fortune", fight_duration_seconds=3.0)
        long_fight = rider_probe.rider_row("Miss Fortune", fight_duration_seconds=15.0)
        assert short["count"] == 1
        assert long_fight["count"] == 1
        assert long_fight["total_damage"] == pytest.approx(
            short["total_damage"], abs=0.05
        )

    def test_no_autos_prices_nothing(self):
        # No basic attacks -> Love Tap has no swing to ride, so the
        # breakdown carries no passive on-hit row at all.
        result = rider_probe.fight("Miss Fortune", include_auto_attacks=False)
        assert rider_probe.RIDER_ROW not in result["breakdown"]


class TestStrutRow:
    """W publishes a named zero-damage steroid row, never a silent absence.

    Main's roadmap session left W a ``no_damage`` receipt, arguing that an
    untimed ``stat_buff`` would give a 4s/12s steroid full uptime.  The
    merged module prices the sourced row and answers that with
    ``buff_window_share``, so the assertions on the old receipt text are
    replaced by assertions on the steroid it became.
    """

    def test_the_row_is_named_and_deals_nothing(self):
        entry = row_review.entry("Miss Fortune", "W")
        assert entry["name"] == "Strut"
        assert entry["total_raw"] == pytest.approx(0.0)
        assert "bonus attack speed" in entry["detail"]

    def test_the_window_is_the_cached_four_second_active(self):
        assert miss_fortune._STRUT_ACTIVE_SECONDS == 4.0

    def test_w_never_contributes_to_the_fight_total(self):
        result = rider_probe.fight("Miss Fortune")
        row = result["breakdown"].get("W")
        if row is not None:
            assert row.get("total_damage", 0.0) == pytest.approx(0.0)


class TestAssumptionsNameBothClosedSlots:
    def test_assumptions_name_love_tap_and_strut(self):
        assumptions = get_champion_options_meta("Miss Fortune")["assumptions"]
        assert any(
            "Love Tap" in row and "ByCharLevelBreakpoints" in row for row in assumptions
        )
        assert any(
            "Strut" in row and "Bonus Attack Speed" in row for row in assumptions
        )

    def test_parse_publishes_both_slots(self):
        assert row_review.entry("Miss Fortune", "passive")["on_hit"]["max_procs"] == 1
        assert row_review.entry("Miss Fortune", "W") is not None
