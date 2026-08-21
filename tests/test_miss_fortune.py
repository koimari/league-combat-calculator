"""Miss Fortune P (Love Tap) + W (Strut) closure — roadmap slot session.

Pins the two decisions recorded in the session's deepfix edit (see
``git log`` on ``src/calculator/champions/miss_fortune.py`` and the saved
decision log the edit cites): P (Love Tap) moves from ``out_of_scope`` to
a ONE-application on-hit priced off the game-binary total-AD ladder
(cross-checked against the cached wiki "Per-Level Scaling" row at parse
time), and W (Strut) moves from the stock generic-parser message to a
named ``no_damage`` receipt.

P's ratio ladder (``_LOVE_TAP_LEVEL1_AD_RATIO`` 0.5 + 0.1 per breakpoint
at levels 4/7/9/11/13/20/25/30) is verified here at its cited endpoints —
level 1 (0.5), level 11 (0.9), level 18 (1.0) and level 20 (1.1, the
binary-only tier past the 6-entry cached row) — both as the standalone
tier/ratio function and end-to-end through a fight (single proc, capped
by ``max_procs=1`` regardless of auto count; zero autos price zero).

W is pinned as a named zero-damage row: it must appear in a cast fight
with ``total_damage == 0`` and a detail string naming the atoms receipt,
never silently absent.
"""

import json

import pytest

from src.calculator.champions import get_champion_options_meta, parse_champion_abilities
from src.calculator.champions.engine import SlotCtx
from src.calculator.champions.miss_fortune import (
    MODULE_COVERAGE,
    _LOVE_TAP_BREAKPOINT_LEVELS,
    _LOVE_TAP_BREAKPOINT_STEP,
    _LOVE_TAP_LEVEL1_AD_RATIO,
    _love_tap_ad_ratio,
    _love_tap_tier,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats

_MF_DATA = get_champion("Miss Fortune")
_P_ABILITY = _MF_DATA["abilities"]["P"][0]
# The cached wiki "Per-Level Scaling" row the ladder is cross-checked
# against at parse time (first of two occurrences — the second is the
# halved anti-minion row and is not read here).
_WIKI_PER_LEVEL_SCALING_PERCENT = [50, 60, 70, 80, 90, 100]
# Endpoints the session's decisions log calls out as verified: level ->
# expected total-AD ratio.  1/4/7/9/11/13 land on the cached row; 20 is
# the binary-only 7th tier past the row's end (MAX_LEVEL is 20, so this
# is the highest tier the calculator can ever reach).
_RATIO_ENDPOINTS = {
    1: 0.5,
    4: 0.6,
    11: 0.9,
    18: 1.0,
    20: 1.1,
}
_NO_ACTIVE_RANKS = {"Q": 0, "W": 0, "E": 0, "R": 0}
_TARGET = {"target_max_health": 2000.0, "target_current_health": 2000.0}
# 0 armor/MR so mitigated physical damage equals raw for the standalone
# ratio checks; a second set of assertions below uses 50 armor (the
# golden-snapshot regression target) to confirm mitigation composes.
_ZERO_RESIST_CONFIG = {"target_armor": 0.0, "target_magic_resistance": 0.0}
_FIFTY_ARMOR_CONFIG = {"target_armor": 50.0, "target_magic_resistance": 40.0}


def _stats(level: int) -> dict:
    return calculate_total_stats(_MF_DATA, level, [])


def _parse(level: int, ranks: dict | None = None):
    stats = _stats(level)
    abilities = parse_champion_abilities(
        _MF_DATA,
        level,
        stats.get("ability_power", 0.0),
        ability_ranks=ranks if ranks is not None else _NO_ACTIVE_RANKS,
        champion_stats=stats,
        target_stats=_TARGET,
    )
    return stats, abilities


def _fight(
    level: int,
    *,
    auto_attack_uptime: float = 1.0,
    duration: float = 6.0,
    one_rotation: bool = False,
    cast_order: list | None = None,
    resist: dict | None = None,
) -> dict:
    stats, abilities = _parse(level)
    resist = resist or _ZERO_RESIST_CONFIG
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=_TARGET["target_max_health"],
            target_armor=resist["target_armor"],
            target_magic_resistance=resist["target_magic_resistance"],
            fight_duration_seconds=duration,
            auto_attack_uptime=auto_attack_uptime,
            one_rotation=one_rotation,
            deterministic=True,
            cast_order=cast_order if cast_order is not None else ["W"],
        ),
        champion_options={},
    )


# ---------------------------------------------------------------------------
# P (Love Tap) — standalone ratio/tier ladder
# ---------------------------------------------------------------------------


class TestLoveTapRatioLadder:
    def test_tier_breakpoints_pinned(self) -> None:
        # The tier function counts breakpoints reached at-or-before the
        # level; every cited endpoint lands on the expected tier index.
        assert _LOVE_TAP_BREAKPOINT_LEVELS == (4, 7, 9, 11, 13, 20, 25, 30)
        assert _love_tap_tier(1) == 0
        assert _love_tap_tier(3) == 0
        assert _love_tap_tier(4) == 1
        assert _love_tap_tier(11) == 4
        assert _love_tap_tier(13) == 5
        assert _love_tap_tier(18) == 5  # the 20-breakpoint tier not yet reached
        assert _love_tap_tier(20) == 6

    @pytest.mark.parametrize("level,expected_ratio", sorted(_RATIO_ENDPOINTS.items()))
    def test_ratio_at_verified_endpoints(
        self, level: int, expected_ratio: float
    ) -> None:
        # Recompute independently of the module's own tier arithmetic:
        # level1 + step * tier, using the module's public constants.
        tier = _love_tap_tier(level)
        recomputed = _LOVE_TAP_LEVEL1_AD_RATIO + _LOVE_TAP_BREAKPOINT_STEP * tier
        assert recomputed == pytest.approx(expected_ratio)

        ctx = SlotCtx(slot="P", champion_name="Miss Fortune", level=level)
        assert _love_tap_ad_ratio(ctx, _P_ABILITY) == pytest.approx(expected_ratio)

    def test_ratio_cross_checked_against_cached_wiki_row(self) -> None:
        # The module asserts its game-binary ladder against the cached
        # "Per-Level Scaling" row at parse time; this test pins that the
        # cache actually carries the row the module depends on, so a
        # patch pull that drops or reorders it fails this test instead of
        # silently disabling the module's own cross-check.
        leveling = [
            row
            for effect in _P_ABILITY["effects"]
            for row in effect.get("leveling", [])
            if row.get("attribute") == "Per-Level Scaling"
        ]
        assert leveling, "Love Tap lost its cached Per-Level Scaling row"
        assert leveling[0]["modifiers"][0]["values"] == _WIKI_PER_LEVEL_SCALING_PERCENT
        for level, expected_ratio in _RATIO_ENDPOINTS.items():
            tier = _love_tap_tier(level)
            if tier < len(_WIKI_PER_LEVEL_SCALING_PERCENT):
                cached_ratio = _WIKI_PER_LEVEL_SCALING_PERCENT[tier] / 100.0
                assert cached_ratio == pytest.approx(expected_ratio)

    def test_drifted_cache_row_fails_loud(self) -> None:
        # A patch that moves the cached row out from under the binary
        # ladder must raise, naming the ability — never silently keep
        # pricing the stale (or now-mismatched) coefficient.
        ability = json.loads(json.dumps(_P_ABILITY))  # deep copy
        for effect in ability["effects"]:
            for row in effect.get("leveling", []):
                if row.get("attribute") == "Per-Level Scaling":
                    row["modifiers"][0]["values"] = [1, 1, 1, 1, 1, 1]
                    break
            else:
                continue
            break
        ctx = SlotCtx(slot="P", champion_name="Miss Fortune", level=11)
        with pytest.raises(ValueError) as excinfo:
            _love_tap_ad_ratio(ctx, ability)
        assert "Love Tap" in str(excinfo.value)
        assert "drifted" in str(excinfo.value)

    def test_missing_cache_row_fails_loud(self) -> None:
        ability = {"name": "Love Tap", "effects": [{"leveling": []}]}
        ctx = SlotCtx(slot="P", champion_name="Miss Fortune", level=11)
        with pytest.raises(ValueError) as excinfo:
            _love_tap_ad_ratio(ctx, ability)
        assert "Love Tap" in str(excinfo.value)
        assert "missing" in str(excinfo.value)


# ---------------------------------------------------------------------------
# P (Love Tap) — end-to-end fight pricing (single proc, capped by max_procs)
# ---------------------------------------------------------------------------


class TestLoveTapFightPricing:
    @pytest.mark.parametrize("level,expected_ratio", sorted(_RATIO_ENDPOINTS.items()))
    def test_single_proc_at_zero_resist(
        self, level: int, expected_ratio: float
    ) -> None:
        # 0 armor/MR: mitigated damage equals the raw ratio x total AD,
        # so the breakdown row is asserted straight against the sourced
        # ratio with no mitigation arithmetic in the test itself.
        stats = _stats(level)
        expected_damage = expected_ratio * float(stats["attack_damage"])
        result = _fight(level, resist=_ZERO_RESIST_CONFIG)
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == 1
        assert row["damage_per_hit"] == pytest.approx(expected_damage, abs=0.05)
        assert row["damage_type"] == "physical"

    def test_single_proc_survives_many_autos(self) -> None:
        # max_procs=1 caps the row at exactly one hit regardless of how
        # many autos land in the fight window — a long sustained fight
        # must not multiply Love Tap's one-time mark.
        short = _fight(18, duration=3.0, auto_attack_uptime=1.0)
        long = _fight(18, duration=15.0, auto_attack_uptime=1.0)
        short_row = short["breakdown"]["on_hit_ability_passive"]
        long_row = long["breakdown"]["on_hit_ability_passive"]
        assert short_row["count"] == 1
        assert long_row["count"] == 1
        assert long_row["damage_per_hit"] == pytest.approx(
            short_row["damage_per_hit"], abs=0.05
        )

    def test_no_autos_prices_zero(self) -> None:
        # No basic attacks -> Love Tap has no swing to ride: the on-hit
        # loop's own auto-count guard skips the ability entirely, so the
        # breakdown carries no passive on-hit row at all (not a
        # zero-valued one) — the module's documented boundary.
        result = _fight(18, auto_attack_uptime=0.0, duration=6.0)
        assert "on_hit_ability_passive" not in result["breakdown"]

    def test_mitigation_composes_with_the_ratio(self) -> None:
        # The golden-snapshot regression target (50 armor): mitigated ==
        # raw x 100 / 150, recomputed independently of the module.
        stats = _stats(11)
        ratio = _RATIO_ENDPOINTS[11]
        raw = ratio * float(stats["attack_damage"])
        expected_mitigated = raw * 100.0 / (100.0 + 50.0)
        result = _fight(11, resist=_FIFTY_ARMOR_CONFIG)
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["damage_per_hit"] == pytest.approx(expected_mitigated, abs=0.05)


# ---------------------------------------------------------------------------
# W (Strut) — named zero-damage row
# ---------------------------------------------------------------------------


class TestStrutZeroDamageRow:
    def test_w_is_a_named_zero_row_when_cast(self) -> None:
        result = _fight(18, cast_order=["W"], one_rotation=True, auto_attack_uptime=0.0)
        row = result["breakdown"]["W"]
        assert row["total_damage"] == pytest.approx(0.0)
        assert row["name"] == "Strut"
        assert "Strut is state, not damage" in row["detail"]
        assert "missfortune.atoms.json" in row["detail"]

    def test_w_never_contributes_to_fight_total(self) -> None:
        # A fight that casts W plus lands autos (Love Tap procs) has a
        # nonzero total, but every point of it traces to the passive on-
        # hit / auto rows — W's own contribution is exactly zero.
        result = _fight(18, cast_order=["W"], one_rotation=True, auto_attack_uptime=1.0)
        row = result["breakdown"]["W"]
        assert row["total_damage"] == pytest.approx(0.0)
        other_total = sum(
            entry.get("total_damage", 0.0)
            for key, entry in result["breakdown"].items()
            if key != "W"
        )
        assert result["total_damage"] == pytest.approx(other_total, abs=0.05)

    def test_w_absent_from_parse_when_never_cast(self) -> None:
        # Parsing always yields a W entry (the state receipt exists
        # independent of whether the fight casts it); a fight that never
        # casts W simply omits it from the breakdown.
        _, abilities = _parse(18)
        assert "W" in abilities
        assert abilities["W"]["total_raw"] == pytest.approx(0.0)
        result = _fight(18, cast_order=[], auto_attack_uptime=0.0)
        assert "W" not in result["breakdown"]


# ---------------------------------------------------------------------------
# Coverage dict + assumptions
# ---------------------------------------------------------------------------


class TestModuleCoverageAndAssumptions:
    def test_coverage_dict_closes_both_slots(self) -> None:
        assert MODULE_COVERAGE == {
            "P": "modeled",
            "Q": "modeled",
            "W": "no_damage",
            "E": "modeled",
            "R": "modeled",
        }

    def test_assumptions_name_both_closed_slots(self) -> None:
        meta = get_champion_options_meta("Miss Fortune")
        assumptions = meta["assumptions"]
        assert any(
            "Love Tap" in row and "ONE-application on-hit" in row for row in assumptions
        )
        assert any(
            "Strut" in row and "zero-damage state row" in row for row in assumptions
        )

    def test_parse_publishes_both_slots(self) -> None:
        _, abilities = _parse(18)
        assert "passive" in abilities
        assert "W" in abilities
        assert abilities["passive"]["on_hit"]["max_procs"] == 1
        assert abilities["passive"]["on_hit"]["damage_type"] == "physical"
