"""Twitch's two remaining slots: Q closes MODELED (gated), W ``no_damage``.

Roadmap session 5 batch L.  The pair is the point of the file.

- Q (Ambush) carries Element of Surprise, a windowed attack-speed steroid
  that sits in the ONE slot the engine can place exactly (the kernel
  resolves the window start by breaking on ``"Q"`` in ``cast_order``).
  Unlike Tristana Q in this same batch, the buff does not fire on the
  cast — it fires on BREAKING the stealth the cast creates — so it is
  published only when the ``q_ambush_break`` option asserts that
  pre-fight state.  Default OFF: an always-on window would be a phantom
  proc.
- W (Venom Cask) is a slow whose only damage-relevant clause (applying
  Deadly Venom) is already priced by ``poison_stacks``, so nothing
  damaging is left unmodeled: ``no_damage``, not a receipted
  ``out_of_scope`` opening (contrast Teemo P / Udyr P in this batch).

Everything is re-derived from ``data/champions.json``, the typed atom
catalog and ``data/gamefiles/characters/twitch.bin.json`` rather than
trusted from the module's prose.
"""

import json
import math
import re
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.ability_atoms import _ability_atoms
from src.calculator.champions import twitch
from src.calculator.champions.slotlib import STEROID_ZERO
from src.calculator.data_fetcher import get_champion

RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

_WIKI = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Twitch"]

# ``data/gamefiles/`` is a gitignored local cdtb cache, so CI has no copy.
# The PRIMARY receipt for every number in this file is the git-tracked
# ``data/champions.json`` and is asserted unconditionally; the binary is a
# SECOND, corroborating source, and the tests that read it skip when the
# cache is absent (the ``test_gnar_mega_gamefile.py`` ternary idiom).
_BIN_PATH = Path("data/gamefiles/characters/twitch.bin.json")
_BIN = json.loads(_BIN_PATH.read_text(encoding="utf-8")) if _BIN_PATH.exists() else None


def _data_values(object_name: str) -> dict[str, list]:
    if _BIN is None:
        pytest.skip(f"{_BIN_PATH} absent (gitignored local game-file cache)")
    for value in _BIN.values():
        if isinstance(value, dict) and value.get("ObjectName") == object_name:
            return {row["name"]: row["values"] for row in value["mSpell"]["DataValues"]}
    raise AssertionError(f"{object_name} missing from the cached binary")


def _q_descriptions() -> list[str]:
    return [
        effect.get("description") or ""
        for effect in _WIKI["abilities"]["Q"][0]["effects"]
    ]


def _parse(options: dict | None = None, **ranks) -> dict:
    return twitch.parse_abilities(
        get_champion("Twitch"),
        18,
        0.0,
        dict(RANKS, **ranks),
        champion_options=options or {},
    )


def _fight(duration: float = 10.0, **options) -> dict:
    """One no-item level-18 fight, autos included (the window's surface)."""
    payload = {
        "champion": "Twitch",
        "level": 18,
        "items": [],
        "role": "bottom",
        "ability_ranks": dict(RANKS),
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": True,
        "target_health": 10_000.0,
        "target_armor": 0,
        "target_mr": 0,
        "champion_options": options,
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


class TestAmbushIsGatedOffByDefault:
    """No option, no window — the Rammus phantom-proc rule."""

    def test_the_default_row_publishes_nothing_to_the_engine(self):
        row = _parse()["Q"]

        assert row["total_raw"] == 0.0
        assert "stat_buff" not in row
        assert "auto_attack_override" not in row

    def test_the_default_zero_is_declared_rather_than_merely_absent(self):
        """The row is built by ``damage_entry``, so its zero has a
        disposition (D-24).  A bare ``parts == ()`` would say only that no
        damage was published; ``STEROID_ZERO`` says the zero is the ANSWER
        — a steroid slot with no damage attribute — which is the stronger
        statement and the one the zero-policy frontier counts.
        """
        parts = _parse()["Q"]["parts"]

        assert [(part.damage_type, part.amount) for part in parts] == [
            ("physical", 0.0)
        ]
        assert [part.zero_policy for part in parts] == [STEROID_ZERO]

    def test_the_default_row_still_names_the_withheld_mechanic(self):
        detail = _parse()["Q"]["detail"]

        assert "Element of Surprise" in detail
        assert "40/45/50/55/60%" in detail
        assert "NOT applied" in detail

    def test_the_option_defaults_off(self):
        option = next(o for o in twitch.OPTIONS if o["key"] == "q_ambush_break")

        assert option["type"] == "bool"
        assert option["default"] is False

    def test_the_default_fight_is_byte_for_byte_the_unbuffed_one(self):
        gated = _fight()
        assert gated["champion_stats"]["attack_speed"] == pytest.approx(
            _fight(q_ambush_break=False)["champion_stats"]["attack_speed"]
        )
        assert "auto_attack_override" not in _parse()["Q"]


class TestAmbushModelsTheWindowWhenTheStateIsAsserted:
    """Option on: the sourced magnitude and sourced window reach the engine."""

    def test_q_publishes_the_stat_buff_and_the_window(self):
        row = _parse({"q_ambush_break": True})["Q"]

        assert row["name"] == "Ambush"
        assert row["total_raw"] == 0.0
        assert row["stat_buff"] == {"bonus_attack_speed": 60.0}
        assert row["auto_attack_override"] == {"active_duration": 6.0}
        # Arming the window must not put damage on the row: the zero is
        # still the declared STEROID_ZERO answer, not a computed total.
        assert [part.zero_policy for part in row["parts"]] == [STEROID_ZERO]
        assert [part.amount for part in row["parts"]] == [0.0]

    def test_the_override_carries_the_window_and_nothing_else(self):
        """A bare window moves the auto COUNT, never the per-swing formula.

        ``ad_ratio`` defaults to 1.0 and the per-swing
        ``swing_window_ratio`` that consumes it is read only inside
        ``damage.py``'s ``override_crit_as_bonus`` branch (Ashe's
        flurry).  Publishing either key here would silently re-price
        every auto attack.
        """
        override = _parse({"q_ambush_break": True})["Q"]["auto_attack_override"]

        assert set(override) == {"active_duration"}
        for forbidden in ("ad_ratio", "crit_as_bonus", "replace_raw", "damage_ratio"):
            assert forbidden not in override

    def test_q_scales_by_rank(self):
        for rank, expected in enumerate([40.0, 45.0, 50.0, 55.0, 60.0], start=1):
            parsed = _parse({"q_ambush_break": True}, Q=rank)
            assert parsed["Q"]["stat_buff"]["bonus_attack_speed"] == expected

    def test_unlearned_q_publishes_no_buff_even_with_the_option_on(self):
        row = _parse({"q_ambush_break": True}, Q=0)["Q"]

        assert "stat_buff" not in row
        assert "auto_attack_override" not in row

    def test_a_stripped_leveling_row_fails_closed(self):
        """No literal fallback: a degraded cache must raise, not zero out."""
        data = json.loads(json.dumps(get_champion("Twitch")))
        for effect in data["abilities"]["Q"][0]["effects"]:
            effect["leveling"] = []

        with pytest.raises((KeyError, ValueError)):
            twitch.parse_abilities(
                data, 18, 0.0, dict(RANKS), champion_options={"q_ambush_break": True}
            )


class TestBothNumbersAreSourcedTwice:
    """Magnitude rides a typed atom; the window rides prose plus the binary."""

    def test_the_magnitude_is_a_typed_atom(self):
        atoms = {
            atom["atom_id"]: atom
            for atom in _ability_atoms("Twitch", get_champion("Twitch"))["Q"]
        }

        assert atoms["ability.bonus _attack _speed"]["values"] == [
            40.0,
            45.0,
            50.0,
            55.0,
            60.0,
        ]
        # The window has NO atom — that is exactly why it is a constant.
        assert "timing.active_duration" not in atoms

    def test_the_binary_rank_indexing_is_proved_by_the_stealth_duration_row(self):
        """Riot DataValues are rank-0-indexed; the wiki proves it here.

        ``StealthDuration`` indices 1..5 are the wiki's
        ``ability.stealth _duration`` atom exactly, so the same slice of
        ``AttackSpeedMod`` is the rank 1-5 attack speed.
        """
        values = _data_values("TwitchHideInShadows")
        atoms = {
            atom["atom_id"]: atom
            for atom in _ability_atoms("Twitch", get_champion("Twitch"))["Q"]
        }

        assert values["StealthDuration"][1:6] == [10.0, 11.0, 12.0, 13.0, 14.0]
        assert atoms["ability.stealth _duration"]["values"] == [
            10.0,
            11.0,
            12.0,
            13.0,
            14.0,
        ]
        assert [round(v * 100) for v in values["AttackSpeedMod"][1:6]] == [
            40,
            45,
            50,
            55,
            60,
        ]

    def test_the_six_second_window_matches_the_tracked_wiki_prose(self):
        """The constant's PRIMARY receipt — runs everywhere, tracked source."""
        prose = next(d for d in _q_descriptions() if "breaking stealth" in d)
        match = re.search(r"bonus attack speed for (\d+(?:\.\d+)?) seconds", prose)

        assert match is not None, prose
        assert float(match.group(1)) == twitch._Q_ATTACK_SPEED_WINDOW

    def test_the_six_second_window_matches_the_binary(self):
        """The constant's SECOND receipt — skips without the local cache."""
        assert set(_data_values("TwitchHideInShadows")["AttackSpeedDuration"]) == {
            twitch._Q_ATTACK_SPEED_WINDOW
        }

    def test_the_trigger_really_is_a_stealth_break_not_the_cast(self):
        """Why this window is gated and Tristana Q's is not.

        Ambush's own cached prose makes the cast CAMOUFLAGE Twitch after
        a delay; the attack speed arrives only on breaking that stealth.
        """
        descriptions = _q_descriptions()

        assert any(
            "1-second delay" in d and "camouflaged" in d for d in descriptions
        ), descriptions
        assert any("Upon breaking stealth" in d for d in descriptions), descriptions

    def test_the_binary_carries_the_same_one_second_fade(self):
        assert set(_data_values("TwitchHideInShadows")["MaxFadeTime"]) == {1.0}


class TestTheWindowSplitsTheLiveAutoCount:
    """The engine surface: in-window / post-window autos."""

    def test_the_fight_applies_the_buffed_attack_speed(self):
        base_stats = _fight()["champion_stats"]
        buffed = _fight(q_ambush_break=True)["champion_stats"]["attack_speed"]

        assert buffed == pytest.approx(
            base_stats["attack_speed"] + base_stats["attack_speed_ratio"] * 0.60
        )

    def test_the_auto_count_matches_the_windowed_arithmetic(self):
        """floor(in-window) + floor(post-window), not one blended floor."""
        base_fight = _fight()
        base_as = base_fight["champion_stats"]["attack_speed"]
        buffed_as = base_as + base_fight["champion_stats"]["attack_speed_ratio"] * 0.60
        uptime = 0.8  # the engine's default auto-attack uptime
        window, duration = 6.0, 10.0

        expected = math.floor(buffed_as * window * uptime) + math.floor(
            base_as * (duration - window) * uptime
        )

        assert (
            _fight(q_ambush_break=True)["breakdown"]["auto_attacks"]["count"]
            == expected
        )
        assert base_fight["breakdown"]["auto_attacks"]["count"] == math.floor(
            base_as * duration * uptime
        )

    def test_the_window_raises_the_count_without_changing_per_hit_damage(self):
        buffed = _fight(q_ambush_break=True)["breakdown"]["auto_attacks"]
        base = _fight()["breakdown"]["auto_attacks"]

        assert buffed["count"] > base["count"]
        assert buffed["damage_per_hit"] == pytest.approx(base["damage_per_hit"])

    def test_the_ultimate_ad_buff_still_lands_alongside_the_new_one(self):
        """Two stat_buff rows (Q and R) must both apply, not the first only."""
        fight = _fight(q_ambush_break=True)
        base = _fight()

        assert fight["champion_stats"]["attack_damage"] == pytest.approx(
            base["champion_stats"]["attack_damage"]
        )
        assert _parse({"q_ambush_break": True})["R"]["stat_buff"] == {
            "bonus_attack_damage": 60.0
        }


class TestVenomCaskIsASourcedZeroDamageRow:
    """W: slow only, and its stacks are already priced."""

    def test_w_emits_a_visible_zero_row_with_the_sourced_slow(self):
        row = _parse()["W"]

        assert row["name"] == "Venom Cask"
        assert row["total_raw"] == 0.0
        assert row["parts"] == ()
        assert "50%" in row["detail"]
        assert "6% per 100 AP" in row["detail"]

    def test_w_publishes_nothing_to_the_engine(self):
        row = _parse()["W"]

        for key in ("stat_buff", "auto_attack_override", "on_hit", "control_events"):
            assert key not in row

    def test_w_scales_its_named_slow_by_rank(self):
        for rank, expected in enumerate([30, 35, 40, 45, 50], start=1):
            assert f"{expected}%" in _parse(W=rank)["W"]["detail"]

    def test_w_has_no_damage_instance_and_only_slow_atoms(self):
        for entry in _WIKI["abilities"]["W"]:
            assert entry["damageType"] is None

        atoms = _ability_atoms("Twitch", get_champion("Twitch"))["W"]
        assert sorted(atom["atom_id"] for atom in atoms) == [
            "ability.slow.modifier_0",
            "ability.slow.modifier_1",
            "timing.cooldown",
        ]

    def test_the_slow_carries_no_sourced_duration_to_publish(self):
        """Why W names the slow instead of authoring a ControlEvent."""
        attributes = [
            leveling.get("attribute")
            for entry in _WIKI["abilities"]["W"]
            for effect in entry.get("effects", [])
            for leveling in effect.get("leveling", [])
        ]

        assert attributes == ["Slow"]
        assert not any("duration" in str(a).lower() for a in attributes)


class TestModuleCoverageRecordsTheSplitVerdict:
    def test_coverage_map(self):
        assert twitch.MODULE_COVERAGE == {
            "P": "modeled",
            "Q": "modeled",
            "W": "no_damage",
            "E": "modeled",
            "R": "modeled",
        }

    def test_no_priced_ability_row_moved(self):
        parsed = _parse()

        assert parsed["E"]["total_raw"] == pytest.approx(396.0)
        assert parsed["passive"]["total_raw"] == pytest.approx(180.0)
        assert parsed["Q"]["total_raw"] == 0.0
        assert parsed["W"]["total_raw"] == 0.0

    def test_enabling_the_option_prices_no_extra_ability_damage(self):
        gated = _parse()
        asserted = _parse({"q_ambush_break": True})

        for slot in ("passive", "Q", "W", "E", "R"):
            assert asserted[slot]["total_raw"] == pytest.approx(
                gated[slot]["total_raw"]
            )
