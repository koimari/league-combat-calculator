"""Taric P (Bravado) and the cast-armed proc-window dedup primitive.

Roadmap session 2 closes Taric P (out_of_scope -> modeled).  Session 1
left it open on a named engine dependency: ``empowers_next_auto``
multiplies flatly by cast count, so Taric's four-cast rotation would
have booked EIGHT empowered attacks against a sourced maximum of two.
``damage.py``'s ``_empower_window_procs`` is that missing dedup — it
walks the accepted cast timeline against the fight's consuming actions
and returns one timestamp per charge ACTUALLY SPENT.

Three layers are pinned here:

1. The primitive's window semantics in isolation (one proc per charge,
   not per hit; re-arming refreshes rather than stacks; expiry; the
   documented simultaneous-event tie-break; fail-closed declarations).
2. Taric's sourced numbers, recomputed from ``data/champions.json``:
   the "Per-Level Scaling" row (25 : 101 across levels 1-20) and the
   "+ 15% bonus armor" ratio / "next two basic attacks within 5
   seconds" window shape, both regex-read from the cached description.
3. The end-to-end fight, where the dedup is visible as a proc count
   that tracks ARMING CASTS rather than swings.
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.taric import (
    MODULE_COVERAGE,
    _bravado_window_terms,
)
from src.calculator.damage import (
    FightConfig,
    _empower_window_procs,
    calculate_fight_damage,
)
from src.calculator.stats import calculate_total_stats

_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_TARIC = _DATA["Taric"]
_TARIC_P = _TARIC["abilities"]["P"][0]
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

# Taric's own window, so the primitive tests exercise the shape the
# module actually ships rather than an invented one.
_BRAVADO_WINDOW = {
    "armed_by": ("Q", "W", "E", "R"),
    "duration": 5.0,
    "charges_per_arm": 2,
    "max_charges": 2,
    "consumed_by": ("auto",),
    "refresh_on_consume": True,
}


def _autos(*times: float) -> list[tuple[float, str]]:
    return [(time, "auto") for time in times]


def _parse(level: int, *, bonus_armor: float | None = None) -> dict:
    """parse_champion_abilities for Taric at a level, with real stats."""
    stats = calculate_total_stats(_TARIC, level, [])
    if bonus_armor is not None:
        stats["bonus_armor"] = bonus_armor
    return parse_champion_abilities(
        _TARIC,
        level,
        stats["ability_power"],
        ability_ranks=_FULL_RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": 2000.0, "target_current_health": 2000.0},
    )


def _fight(*, mode: str, duration: float) -> dict:
    """One /api/calculate fight into a 0-resist target (raw == mitigated)."""
    payload = {
        "champion": "Taric",
        "level": 18,
        "items": [],
        "role": "mid",
        "fight_mode": mode,
        "fight_duration": duration,
        "include_auto_attacks": True,
        "champion_options": {},
        "ability_ranks": _FULL_RANKS,
        "target_health": 10000,
        "target_armor": 0,
        "target_mr": 0,
    }
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _engine_fight(duration: float) -> dict:
    """A fight straight off ``calculate_fight_damage``.

    The API serializer whitelists breakdown fields, so the authored
    per-proc event ledger and damage type are only observable here.
    """
    stats = calculate_total_stats(_TARIC, 18, [])
    abilities = parse_champion_abilities(
        _TARIC,
        18,
        stats["ability_power"],
        ability_ranks=_FULL_RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": 10000.0, "target_current_health": 10000.0},
    )
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=10000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=duration,
            auto_attack_uptime=1.0,
            one_rotation=False,
            deterministic=True,
        ),
    )


# ---------------------------------------------------------------------------
# 1. The dedup primitive
# ---------------------------------------------------------------------------


class TestEmpowerWindowProcs:
    """``_empower_window_procs`` window semantics in isolation."""

    def test_one_proc_per_charge_not_per_hit(self) -> None:
        """THE dedup property: a live window caps at its charge count.

        Eight swings inside one 5s window spend two charges, not eight —
        the exact overcount ``empowers_next_auto`` would have produced.
        """
        procs = _empower_window_procs(
            _BRAVADO_WINDOW,
            arm_times=[0.0],
            consumer_times=_autos(0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0),
        )
        assert procs == [0.5, 1.0]

    def test_re_arming_refreshes_rather_than_stacks(self) -> None:
        """Four casts inside one window still grant two attacks.

        Taric's cached note: "Bravado may only grant up to two empowered
        attacks."  With ``charges_per_arm == max_charges`` an arm tops
        the window back up instead of adding to it.
        """
        procs = _empower_window_procs(
            _BRAVADO_WINDOW,
            arm_times=[0.0, 0.25, 0.5, 0.5],
            consumer_times=_autos(1.0, 1.5, 2.0, 2.5, 3.0),
        )
        assert procs == [1.0, 1.5]

    def test_partial_spend_is_topped_back_up_by_a_later_cast(self) -> None:
        """ "...grant another empowered attack if Taric has one remaining"."""
        procs = _empower_window_procs(
            _BRAVADO_WINDOW,
            arm_times=[0.0, 2.0],
            consumer_times=_autos(1.0, 3.0, 4.0, 5.0),
        )
        # One charge spent at 1.0; the 2.0 cast restores it to two, so the
        # three later swings spend both.
        assert procs == [1.0, 3.0, 4.0]

    def test_a_lapsed_window_grants_nothing(self) -> None:
        procs = _empower_window_procs(
            _BRAVADO_WINDOW, arm_times=[0.0], consumer_times=_autos(5.001, 9.0)
        )
        assert procs == []

    def test_a_fresh_cast_after_expiry_arms_a_fresh_window(self) -> None:
        procs = _empower_window_procs(
            _BRAVADO_WINDOW,
            arm_times=[0.0, 20.0],
            consumer_times=_autos(1.0, 2.0, 3.0, 21.0, 22.0, 23.0),
        )
        assert procs == [1.0, 2.0, 21.0, 22.0]

    def test_a_consumer_at_the_arming_instant_does_not_proc(self) -> None:
        """The documented conservative tie-break.

        One-rotation mode collapses every cast to t=0; arming first there
        would let a simultaneous action spend a buff that did not exist
        when it landed — the direction that INVENTS damage.
        """
        procs = _empower_window_procs(
            _BRAVADO_WINDOW, arm_times=[0.0], consumer_times=_autos(0.0, 1.0, 2.0)
        )
        assert procs == [1.0, 2.0]

    def test_consumed_by_filters_non_matching_actions(self) -> None:
        """Bravado empowers BASIC ATTACKS, so ability hits spend nothing."""
        procs = _empower_window_procs(
            _BRAVADO_WINDOW,
            arm_times=[0.0],
            consumer_times=[(1.0, "ability_hit"), (2.0, "ability_hit")],
        )
        assert procs == []

    def test_refresh_on_consume_extends_the_window(self) -> None:
        """ "The first attack refreshes Bravado's duration"."""
        procs = _empower_window_procs(
            _BRAVADO_WINDOW, arm_times=[0.0], consumer_times=_autos(4.9, 9.5)
        )
        assert procs == [4.9, 9.5]

    def test_without_refresh_on_consume_the_window_runs_from_the_arm(self) -> None:
        window = dict(_BRAVADO_WINDOW)
        window.pop("refresh_on_consume")
        procs = _empower_window_procs(
            window, arm_times=[0.0], consumer_times=_autos(4.9, 9.5)
        )
        assert procs == [4.9]

    def test_charges_accumulate_when_an_arm_grants_fewer_than_the_cap(self) -> None:
        window = dict(_BRAVADO_WINDOW, charges_per_arm=1, max_charges=3)
        procs = _empower_window_procs(
            window,
            arm_times=[0.0, 0.5, 1.0, 1.5],
            consumer_times=_autos(2.0, 2.5, 3.0, 3.5, 4.0),
        )
        # Four arms, capped at three held charges.
        assert procs == [2.0, 2.5, 3.0]

    def test_no_arming_cast_means_no_procs(self) -> None:
        procs = _empower_window_procs(
            _BRAVADO_WINDOW, arm_times=[], consumer_times=_autos(1.0, 2.0)
        )
        assert procs == []

    @pytest.mark.parametrize(
        "override",
        [
            {"duration": 0.0},
            {"duration": -1.0},
            {"charges_per_arm": 0},
            {"max_charges": 0},
        ],
    )
    def test_a_degenerate_window_fails_closed(self, override: dict) -> None:
        window = dict(_BRAVADO_WINDOW, **override)
        with pytest.raises(ValueError):
            _empower_window_procs(window, [0.0], _autos(1.0))

    @pytest.mark.parametrize("missing", ["duration", "charges_per_arm", "consumed_by"])
    def test_a_window_missing_a_required_term_fails_closed(self, missing: str) -> None:
        window = dict(_BRAVADO_WINDOW)
        window.pop(missing)
        with pytest.raises(KeyError):
            _empower_window_procs(window, [0.0], _autos(1.0))


# ---------------------------------------------------------------------------
# 2. Taric's sourced numbers
# ---------------------------------------------------------------------------


class TestBravadoSources:
    """Every Bravado number traces to ``data/champions.json``."""

    def test_the_cached_per_level_row_is_the_25_to_101_ramp(self) -> None:
        levelings = [
            leveling
            for effect in _TARIC_P["effects"]
            for leveling in effect.get("leveling", [])
            if leveling["attribute"] == "Per-Level Scaling"
        ]
        assert len(levelings) == 1
        values = levelings[0]["modifiers"][0]["values"]
        # The level cap is 20, and the row is a flat +4 per level.
        assert len(values) == 20
        assert values[0] == 25
        assert values[17] == 93
        assert values[-1] == 101
        assert all(
            values[i + 1] - values[i] == 4 for i in range(len(values) - 1)
        ), values

    def test_the_cached_description_declares_the_window_shape(self) -> None:
        description = _TARIC_P["effects"][0]["description"]
        assert "empowers his next two basic attacks within 5 seconds" in description
        assert "(+ 15% bonus armor)" in description
        assert "bonus magic damage on-attack" in description

    def test_the_cached_notes_declare_refresh_not_stack(self) -> None:
        notes = _TARIC_P["notes"]
        assert "The first attack refreshes Bravado's duration." in notes
        assert "Bravado may only grant up to two empowered attacks." in notes

    def test_window_terms_are_read_from_the_cache(self) -> None:
        assert _bravado_window_terms(_TARIC_P) == (2, 5.0, 0.15)

    def test_a_description_without_the_window_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="no cached description"):
            _bravado_window_terms({"effects": [{"description": "Innate: nothing."}]})

    def test_a_window_without_the_bonus_armor_ratio_fails_closed(self) -> None:
        broken = {
            "effects": [
                {
                    "description": (
                        "Innate: After casting an ability, Taric empowers his "
                        "next two basic attacks within 5 seconds to each deal "
                        "25 : 101 (based on level) bonus magic damage."
                    )
                }
            ]
        }
        with pytest.raises(ValueError, match="bonus armor"):
            _bravado_window_terms(broken)

    def test_an_unknown_attack_count_word_fails_closed(self) -> None:
        broken = {
            "effects": [
                {
                    "description": (
                        "Taric empowers his next seventeen basic attacks "
                        "within 5 seconds (+ 15% bonus armor)."
                    )
                }
            ]
        }
        with pytest.raises(ValueError, match="not a known count"):
            _bravado_window_terms(broken)


# ---------------------------------------------------------------------------
# 3. The parsed P entry, at pinned rank endpoints
# ---------------------------------------------------------------------------


class TestBravadoEntry:
    def test_p_is_closed_as_modeled(self) -> None:
        assert MODULE_COVERAGE == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "modeled",
        }

    @pytest.mark.parametrize(
        ("level", "expected"),
        [(1, 25.0), (6, 45.0), (11, 65.0), (18, 93.0), (20, 101.0)],
    )
    def test_per_hit_damage_at_the_level_endpoints(
        self, level: int, expected: float
    ) -> None:
        """25 + 4 x (level - 1), the cached row read at the champion level.

        A no-item Taric holds no BONUS armor (his 113 armor at 18 is all
        base growth), so the "+ 15% bonus armor" term is exactly 0 here.
        """
        on_hit = _parse(level)["passive"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(expected)
        assert on_hit["damage_type"] == "magic"

    def test_bonus_armor_scales_the_packet(self) -> None:
        """93 (level 18) + 0.15 x 100 bonus armor = 108."""
        on_hit = _parse(18, bonus_armor=100.0)["passive"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(108.0)

    def test_base_armor_alone_does_not_scale_the_packet(self) -> None:
        """The ratio is BONUS armor; Taric's base growth must not count."""
        stats = calculate_total_stats(_TARIC, 18, [])
        assert stats["armor"] > 100.0
        assert stats["bonus_armor"] == 0.0
        assert _parse(18)["passive"]["on_hit"]["damage_per_hit"] == pytest.approx(93.0)

    def test_the_entry_declares_the_sourced_window(self) -> None:
        entry = _parse(18)["passive"]
        assert entry["on_hit"]["empower_window"] == {
            "armed_by": ("Q", "W", "E", "R"),
            "duration": 5.0,
            "charges_per_arm": 2,
            "max_charges": 2,
            "consumed_by": ("auto",),
            "refresh_on_consume": True,
        }
        # The passive deals no damage at the cast itself.
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()

    def test_the_entry_does_not_use_the_flat_empowers_next_auto_path(self) -> None:
        """The whole point of the window: the flat mechanism overcounts."""
        assert "empowers_next_auto" not in _parse(18)["passive"]


# ---------------------------------------------------------------------------
# 4. The end-to-end fight
# ---------------------------------------------------------------------------


class TestBravadoFight:
    def test_one_window_grants_two_procs_against_six_swings(self) -> None:
        """The dedup, visible end to end.

        A 10s fight casts Q/W/E/R at 0.0/0.25/0.5/0.5 and swings six
        times.  ``empowers_next_auto`` would have priced four casts x
        their forced attacks; the window prices TWO charges.
        """
        data = _fight(mode="timed", duration=10.0)
        row = data["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == 2
        assert row["damage_per_hit"] == pytest.approx(93.0)
        assert row["total_damage"] == pytest.approx(186.0)
        assert row["unit"] == "procs"
        assert data["breakdown"]["auto_attacks"]["count"] == 6

    def test_a_second_arming_cast_round_grants_a_second_pair(self) -> None:
        """Procs track ARMING CASTS, not swings: 13 swings, 4 procs."""
        data = _fight(mode="timed", duration=20.0)
        row = data["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == 4
        assert row["total_damage"] == pytest.approx(372.0)
        assert data["breakdown"]["auto_attacks"]["count"] == 13
        # E casts twice over 20s (250 raw per cast) — the second cast is
        # what re-arms the window.
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(500.0)

    def test_procs_are_dated_to_the_swings_that_spent_them(self) -> None:
        """Each charge is spent by ONE dated swing, so the row is exact."""
        row = _engine_fight(10.0)["breakdown"]["on_hit_ability_passive"]
        assert row["damage_type"] == "magic"
        assert row["event_phase"] == "auto"
        events = row["damage_events"]
        assert [event["damage"] for event in events] == pytest.approx([93.0, 93.0])
        times = [event["time"] for event in events]
        assert times == sorted(times)
        # Both charges are spent AFTER the arming casts (the last lands at
        # 0.5) and INSIDE the 5s window those casts opened.
        assert all(0.5 < time <= 5.5 for time in times), times
        # And the ledger reconciles with the aggregate the row reports.
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )

    def test_a_fight_without_swings_grants_nothing(self) -> None:
        """One-rotation prices the cast rotation only: no autos to empower."""
        data = _fight(mode="one_rotation", duration=5.0)
        assert "on_hit_ability_passive" not in data["breakdown"]
        assert "auto_attacks" not in data["breakdown"]

    def test_the_passive_adds_exactly_its_row_to_the_fight_total(self) -> None:
        data = _fight(mode="timed", duration=10.0)
        breakdown = data["breakdown"]
        assert data["total_damage"] == pytest.approx(
            sum(row["total_damage"] for row in breakdown.values())
        )
        assert breakdown["on_hit_ability_passive"]["total_damage"] == pytest.approx(
            186.0
        )
