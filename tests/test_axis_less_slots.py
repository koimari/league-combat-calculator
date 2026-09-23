"""The five slots the engine has no axis for, each with a live tripwire.

``docs/coverage-status.md`` reports how many champion slots carry no engine
axis at all, and every one of them is blocked for a reason a module states in
prose. Prose is not a gate: the day a patch states Wukong's clone attack rate
or a Viktor augment's magnitude, nothing here would fail and the block would
quietly outlive its reason.

So each slot's blocker is measured instead, in BOTH places the answer could
arrive: the cached wiki entry and the tracked game binary. They are phrased as
"still absent", the way ``test_blocked_on_absent_data.py`` phrases the two
blocked champion options. A failure here is GOOD news: the data landed and a
slot can be closed.

The set is derived, never hand-listed. ``test_the_watch_covers_exactly_the
_axis_less_slots`` reads ``coverage_status``'s own out_of_scope list, so a
sixth slot cannot appear unwatched and a slot that closes must leave the
watch in the same commit. Sivir R closing is what proved that guard: it left
the list, and this file has no row for it.
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

CHAMPIONS = json.loads(
    (REPO_ROOT / "data" / "champions.json").read_text(encoding="utf-8")
)
BINS = REPO_ROOT / "data" / "bin" / "characters"

#: ``(module name in coverage_status, slot)`` -> the cache key it is stored
#: under. They differ where Riot's internal name does: Wukong is MonkeyKing.
WATCHED = {
    ("Sylas", "R"): "Sylas",
    ("Teemo", "P"): "Teemo",
    ("Udyr", "P"): "Udyr",
    ("Viktor", "P"): "Viktor",
    ("Wukong", "W"): "MonkeyKing",
}


def _prose(cache_key: str, slot: str) -> str:
    """Every cached description on one slot, joined."""
    return " ".join(
        str(effect.get("description", ""))
        for ability in CHAMPIONS[cache_key]["abilities"].get(slot, ())
        for effect in ability.get("effects", ())
    )


def _bin(stem: str) -> dict:
    path = BINS / f"{stem}.bin.json"
    if not path.exists():
        pytest.skip(f"local game-file evidence is unavailable: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _data_values(payload: dict, suffix: str) -> dict[str, list]:
    """Every named DataValue on one spell record, by object-path suffix."""
    for key, value in payload.items():
        if not key.endswith(suffix) or not isinstance(value, dict):
            continue
        spell = value.get("mSpell")
        if not isinstance(spell, dict):
            continue
        return {row["name"]: row["values"] for row in spell.get("DataValues", ())}
    raise AssertionError(f"the probe lost its record: {suffix}")


# ---------------------------------------------------------------------------
# The watch is bound to the measurement, not to a list someone maintains
# ---------------------------------------------------------------------------


def test_the_watch_covers_exactly_the_axis_less_slots():
    """A sixth slot cannot appear unwatched, and a closed one must leave.

    Read from ``coverage_status``'s own scan of the registered modules, which
    is what writes the published page, so this and the page cannot disagree.
    """
    import coverage_status

    _, _, out_of_scope = coverage_status._champion_slots()
    assert set(out_of_scope) == set(WATCHED), sorted(set(out_of_scope) ^ set(WATCHED))


def test_the_watch_would_notice_a_slot_arriving_or_leaving():
    """Why the equality above is a gate and not a coincidence.

    A set comparison that never fails looks the same as one that cannot. This
    drives the same comparison over a scan with one slot added and one
    removed, and requires both to be caught. Sivir R leaving the real list is
    what this stands in for: it closed, and this file has no row for it.
    """
    import coverage_status

    _, _, out_of_scope = coverage_status._champion_slots()
    live = set(out_of_scope)
    assert live == set(WATCHED)

    arrived = live | {("Ashe", "R")}
    assert arrived != set(WATCHED), "an unwatched new slot would pass"

    departed = live - {("Udyr", "P")}
    assert departed != set(WATCHED), "a closed slot left in the watch would pass"


def test_every_watched_slot_still_declares_itself_out_of_scope():
    """The module's own claim, checked against the watch it justifies."""
    from src.calculator.champions import (
        get_champion_module_contract,
    )

    for module, slot in WATCHED:
        coverage = get_champion_module_contract(module).coverage
        assert coverage[slot] == "out_of_scope", (module, slot, coverage[slot])


@pytest.mark.parametrize(("module", "slot"), sorted(WATCHED))
def test_every_watched_slot_states_its_blocker_in_its_own_module(module, slot):
    """A slot with no axis says why, in the module, where a reader will look.

    The verdict has to be written where the next reader of that champion is,
    not only in a published page they may never open.
    """
    from src.calculator.champions import (
        get_champion_module_contract,
    )

    stated = " ".join(get_champion_module_contract(module).assumptions)
    # Either spelling: the contract token, or the English of it. Viktor's row
    # writes the phrase, the other four write the token.
    assert re.search(r"out[ _]of[ _]scope", stated), (module, slot)


# ---------------------------------------------------------------------------
# One measurement per slot, in both sources
# ---------------------------------------------------------------------------


class TestWukongsCloneHasNoAttackRate:
    """W's blocker is the clone's SWING COUNT, not its per-hit output."""

    @pytest.mark.needs_game_files
    def test_the_binary_carries_the_output_ratio_and_the_duration(self):
        """What IS sourced, so the absence below is specific rather than vague."""
        values = _data_values(
            _bin("monkeyking"), "MonkeyKingDecoyAbility/MonkeyKingDecoy"
        )
        assert values["CloneDuration"][0] == pytest.approx(4.0)
        # Ranks 1-5 of the game's 7-wide axis are the cache's 40/45/50/55/60%.
        assert [round(v, 2) for v in values["CloneDamageMod"][1:6]] == [
            0.4,
            0.45,
            0.5,
            0.55,
            0.6,
        ]

    @pytest.mark.needs_game_files
    def test_the_binary_states_no_clone_attack_rate(self):
        values = _data_values(
            _bin("monkeyking"), "MonkeyKingDecoyAbility/MonkeyKingDecoy"
        )
        assert not [name for name in values if "attack" in name.lower()]

    def test_no_tracked_binary_holds_a_clone_character_record(self):
        names = sorted(path.name for path in BINS.glob("*.bin.json"))
        assert "monkeyking.bin.json" in names, "the probe lost its corpus"
        assert not [name for name in names if "clone" in name.lower()]

    def test_the_cached_slot_states_no_rate_either(self):
        prose = _prose("MonkeyKing", "W")
        assert "basic attack" in prose.lower(), "the probe lost its sentence"
        assert not re.search(
            r"attacks? (once )?every [\d.]+ second|attacks? per second", prose, re.I
        )


class TestViktorsAugmentsHaveNoCachedMagnitude:
    """P's blocker is that no augment's effect size exists in either source."""

    @pytest.mark.needs_game_files
    def test_the_binary_carries_only_the_fragment_economy(self):
        values = _data_values(_bin("viktor"), "ViktorPassive")
        assert values["MinionStacks"][0] == pytest.approx(1.0)
        assert values["CannonStacks"][0] == pytest.approx(10.0)
        assert values["ChampionStacks"][0] == pytest.approx(20.0)
        assert values["EvolutionStackBreakpoint"][0] == pytest.approx(100.0)

    @pytest.mark.needs_game_files
    def test_the_binary_states_no_augment_effect(self):
        """Every DataValue on the record is an accrual rate or a breakpoint."""
        values = _data_values(_bin("viktor"), "ViktorPassive")
        assert all(
            re.search(r"stacks|breakpoint|cadence", name, re.I) for name in values
        ), sorted(values)

    def test_the_cached_entry_carries_no_leveling_row_at_all(self):
        for ability in CHAMPIONS["Viktor"]["abilities"]["P"]:
            for effect in ability.get("effects", ()):
                assert effect.get("leveling") in (None, [], ())

    def test_the_cost_is_a_whole_game_accrual_a_fight_cannot_reach(self):
        """100 fragments at 1 per minion is the reason, stated by the cache."""
        prose = _prose("Viktor", "P")
        assert "100 Hex Fragments" in prose
        assert "Minions and monsters generate 1 Hex Fragment" in prose


class TestTeemosStealthTriggerIsUnreachable:
    """P's steroid fires on BREAKING a stealth a fought fight never enters."""

    def test_the_stealth_needs_idle_seconds_a_fight_never_gives(self):
        prose = _prose("Teemo", "P")
        assert "1.5 seconds without moving" in prose
        assert "performing actions that break stealth" in prose

    def test_the_steroid_is_gated_on_breaking_that_stealth(self):
        prose = _prose("Teemo", "P")
        assert "When Teemo breaks the stealth" in prose
        assert "bonus attack speed for 5 seconds" in prose

    def test_the_other_route_in_is_positional(self):
        """The brush clause is the only way to be stealthed while moving, and
        where a champion stands is not an axis this engine has."""
        assert "While in brush" in _prose("Teemo", "P")

    @pytest.mark.needs_game_files
    def test_the_binary_holds_no_passive_spell_record_to_read_instead(self):
        payload = _bin("teemo")
        records = [
            key
            for key, value in payload.items()
            if key.lower().endswith("teemopassive")
            and isinstance(value, dict)
            and isinstance(value.get("mSpell"), dict)
        ]
        assert not records


class TestSylasHijackHasNoDamageOfItsOwn:
    """R's damage is another champion's ultimate, which is not a number."""

    @pytest.mark.needs_game_files
    def test_the_binary_record_computes_only_a_cooldown(self):
        payload = _bin("sylas")
        spell = next(
            value["mSpell"]
            for key, value in payload.items()
            if key.endswith("SylasR") and isinstance(value, dict) and "mSpell" in value
        )
        assert sorted(spell.get("mSpellCalculations", {})) == ["PerTargetCooldown"]

    @pytest.mark.needs_game_files
    def test_every_data_value_on_it_is_about_the_stolen_cooldown(self):
        values = _data_values(_bin("sylas"), "SylasR")
        assert set(values) == {
            "EnemyCooldownPercent",
            "EnemyCooldownTooltip",
            "MinimumEnemyCooldown",
            "UltHoldDuration",
        }

    def test_the_cache_says_the_damage_is_the_other_champions_ultimate(self):
        prose = _prose("Sylas", "R")
        assert "casts his hijacked ultimate ability" in prose
        assert "scaling based on Hijack's rank and his own statistics" in prose

    def test_the_conversion_rule_is_sourced_and_is_not_the_blocker(self):
        """What a later change would already have: the AD-to-AP conversion.

        Pinned so the blocker cannot later be misreported as this rule being
        missing. What is missing is a second champion's ultimate inside one
        request, and which champion is a choice about the enemy team.
        """
        prose = _prose("Sylas", "R")
        assert "0.6% AP per 1% total AD" in prose
        assert "0.4% AP per 1% bonus AD" in prose


class TestUdyrsRefundHasNoBase:
    """P refunds a share of a cooldown neither source states."""

    @pytest.mark.needs_game_files
    def test_the_binary_states_the_share_and_not_the_base(self):
        values = _data_values(_bin("udyr"), "UdyrPassive")
        assert values["UltCDReduction"][0] == pytest.approx(0.05)
        assert values["AttackSpeedDuration"][0] == pytest.approx(4.0)
        assert "Cooldown" not in values

    @pytest.mark.needs_game_files
    def test_the_binary_record_carries_no_cooldown_field(self):
        payload = _bin("udyr")
        spell = next(
            value["mSpell"]
            for key, value in payload.items()
            if key.endswith("UdyrPassive")
            and isinstance(value, dict)
            and "mSpell" in value
        )
        assert "Cooldown" not in spell
        assert "cooldownTime" not in spell

    def test_the_cached_entry_states_no_cooldown_either(self):
        (entry,) = CHAMPIONS["Udyr"]["abilities"]["P"]
        assert entry["cooldown"] is None
        assert entry["rechargeRate"] is None
        for effect in entry.get("effects", ()):
            assert effect.get("leveling") in (None, [], ())

    def test_the_refund_names_a_cooldown_the_engine_does_not_model(self):
        prose = _prose("Udyr", "P")
        assert "refund 5% of Awakened Spirit's total cooldown" in prose
        # Awakened Spirit is an innate system, not a slot in the cast order,
        # so even a sourced base would have nothing here to subtract from.
        assert "Udyr has no ultimate ability" in prose

    def test_the_only_statement_about_that_cooldown_is_that_haste_scales_it(self):
        """Not a magnitude. It lives in the champion's notes, not the slot."""
        notes = json.dumps(CHAMPIONS["Udyr"])
        assert "Awakened Spirit's cooldown is affected by" in notes
        assert "ultimate haste" in notes
        assert not re.search(
            r"Awakened Spirit'?s? (total )?cooldown is [\d.]+ ?(second|s)\b",
            notes,
            re.I,
        )
