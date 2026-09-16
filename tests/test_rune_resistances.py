"""The rune stat channel reaches the holder's resistances, and what that buys.

``RuneStat`` is a closed set: a grant into a channel the engine does not read
is a withheld effect, not a stat. Armor and magic resistance were outside it,
so Conditioning compiled to a refusal reading "the pair engine prices the
holder's outgoing damage".

Half of that reason is still true and this pins BOTH halves, because the
honest receipt is the pair:

* what the resistances DO buy: a champion scaling off bonus armor or bonus
  magic resistance prices more damage for them, which is how the grant
  reaches the fight;
* what they do NOT buy: the holder's own damage taken. ``program/walk``'s
  effective health is health, shields and healing with no resistance term, so
  a pure-armor item changes no number there either. That is the engine's
  shape, not the rune's, and the rune discloses it rather than implying a
  durability it does not have.

The numbers are the cache's. Conditioning's description carries them in prose
and its ``effects`` parsed to ``{}`` until the rune parser learned the
``'''bonus''' armor`` shape, so the first class here is the source.
"""

import json
from pathlib import Path

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.rune_effects import RuneStat, resolve_rune
from src.calculator.rune_parser import parse_rune_effects

_RUNES = json.loads(Path("data/runes.json").read_text(encoding="utf-8"))
_PAGE = {
    "keystone": "Grasp of the Undying",
    "minor_runes": ["Conditioning"],
    "stat_shards": [],
}


def _fight(champion: str, minute: float) -> dict:
    return calculate_payload(
        {
            "champion": champion,
            "level": 18,
            "role": "top",
            "items": [],
            "boots": "",
            "enemies": [
                {"kind": "champion", "champion": "Darius", "level": 18, "role": "top"}
            ],
            "fight_duration": 10,
            "fight_mode": "time_based",
            "deterministic": True,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            **_PAGE,
            "rune_options": {"Conditioning": {"game_minute": minute}},
        }
    )


class TestTheNumbersComeFromTheCache:
    """Sourced, not pinned: the parser reads them out of the description."""

    def test_the_cached_description_states_both_halves(self):
        text = _RUNES["Conditioning"]["description"]
        assert "After 12 minutes" in text
        assert "8 '''bonus''' armor" in text
        assert "8 '''bonus''' magic resistance" in text
        assert "are increased by 3%" in text

    def test_the_parser_reads_them_into_the_cached_effects(self):
        effects, _ = parse_rune_effects(
            "Conditioning", _RUNES["Conditioning"]["description"]
        )
        assert effects == {
            "flat_bonus_armor": 8.0,
            "flat_bonus_magic_resistance": 8.0,
            "total_resist_percent": 0.03,
        }

    def test_the_committed_cache_already_holds_that_parse(self):
        """The reparse landed, so the compiler reads structure not prose."""
        assert _RUNES["Conditioning"]["effects"]["flat_bonus_armor"] == 8.0

    def test_the_rule_matches_only_the_two_runes_that_grant_resistances(self):
        """A parser rule that fires elsewhere would rewrite unrelated runes."""
        granting = {
            name
            for name, entry in _RUNES.items()
            if isinstance(entry, dict)
            and entry.get("description")
            and "flat_bonus_armor" in parse_rune_effects(name, entry["description"])[0]
        }
        assert granting == {"Conditioning", "Unflinching"}


class TestTheChannelReachesTheHolder:
    def test_conditioning_compiles_into_the_resistance_channel(self):
        effect = resolve_rune("Conditioning")
        assert effect.stats == (RuneStat.ARMOR, RuneStat.MAGIC_RESIST)

    def test_the_clock_gates_it_and_the_default_grants_nothing(self):
        before = _fight("Malphite", 0)["champion_stats"]
        armed = _fight("Malphite", 12)["champion_stats"]
        assert before["bonus_armor"] == 0
        assert armed["bonus_armor"] == 8
        assert armed["bonus_magic_resistance"] == 8
        assert armed["armor"] - before["armor"] == 8
        assert armed["magic_resistance"] - before["magic_resistance"] == 8

    def test_total_and_bonus_resists_move_together(self):
        """A grant that moved one and not the other would make the stat card
        disagree with the scaling units that read the bonus half."""
        armed = _fight("Malphite", 12)["champion_stats"]
        base = _fight("Malphite", 0)["champion_stats"]
        assert armed["armor"] - base["armor"] == (
            armed["bonus_armor"] - base["bonus_armor"]
        )


class TestWhatTheResistancesBuyAndWhatTheyDoNot:
    """Both halves, because only the pair is an honest receipt."""

    @pytest.mark.parametrize(
        ("champion", "expected"),
        [("Malphite", 11.4), ("Rammus", 9.6), ("K'Sante", 6.5)],
    )
    def test_an_armor_scaling_kit_prices_more_damage(self, champion, expected):
        before = _fight(champion, 0)["total_damage"]
        armed = _fight(champion, 12)["total_damage"]
        assert armed - before == pytest.approx(expected, abs=0.05)

    def test_a_kit_that_reads_bonus_armor_for_a_shield_prices_no_damage(self):
        """Braum's 36% of bonus armor is a shield, so his damage is flat."""
        assert _fight("Braum", 12)["total_damage"] == pytest.approx(
            _fight("Braum", 0)["total_damage"]
        )

    def test_the_holders_own_damage_taken_carries_no_resistance_term(self):
        """The half the rune still discloses, measured on a pure-armor item.

        Chain Vest is 40 armor and no health, so if the survival side read
        resistances this would move. It does not, which is why the grant is
        disclosed as reaching the scaling door and not a durability one.
        """
        request = {
            "champion": "Garen",
            "level": 18,
            "role": "top",
            "boots": "",
            "enemies": [
                {"kind": "champion", "champion": "Darius", "level": 18, "role": "top"}
            ],
            "fight_duration": 10,
            "fight_mode": "time_based",
            "deterministic": True,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "enemies_attack": True,
        }
        bare = calculate_payload({**request, "items": []})
        armored = calculate_payload({**request, "items": ["Chain Vest"]})
        assert (
            armored["champion_stats"]["armor"] - bare["champion_stats"]["armor"] == 40
        )
        bare_row = bare["combat"]["breakdown"][0]
        armored_row = armored["combat"]["breakdown"][0]
        assert armored_row["health_damage"] == pytest.approx(bare_row["health_damage"])
        assert armored_row["effective_health"] == pytest.approx(
            bare_row["effective_health"]
        )

    def test_the_rune_discloses_the_half_it_does_not_price(self):
        disclosures = " ".join(resolve_rune("Conditioning").disclosures)
        assert "3% increase to TOTAL armor" in disclosures
        assert "percent-of-total resist channel" in disclosures
        assert "does not reach" in disclosures or "does not" in disclosures
