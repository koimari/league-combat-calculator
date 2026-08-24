"""The shared character-binary runtime seam (``src/calculator/binary_roots``).

Phase 1 of binary-rooting every champion's values: the dumps are tracked,
every cache name resolves to one, and lookups fail closed.
"""

import json
from pathlib import Path

import pytest

from src.calculator.binary_roots import (
    _BIN_DIR,
    champion_key,
    character_bin,
    data_value,
    spell_object,
)

_CHAMPIONS = json.loads((Path("data/champions.json")).read_text(encoding="utf-8"))


def test_every_cache_champion_resolves_to_a_tracked_binary():
    """182/182 alignment: each champions.json key maps to a dump on disk.

    This is the campaign's completeness gate — a champion without a dump
    fails here, not later as a mysterious runtime error.
    """
    missing = [
        name
        for name in sorted(_CHAMPIONS)
        if not (_BIN_DIR / f"{champion_key(name)}.bin.json").exists()
    ]
    assert missing == []


def test_champion_key_strips_non_alphanumerics():
    assert champion_key("Dr. Mundo") == "drmundo"
    assert champion_key("Nunu & Willump") == "nunuwillump"
    assert champion_key("Kai'Sa") == "kaisa"
    assert champion_key("Aurelion Sol") == "aurelionsol"


def test_character_bin_returns_the_parsed_dump():
    payload = character_bin("Aurelion Sol")
    assert isinstance(payload, dict)
    # The Q spell object is reachable by its script name.
    q = spell_object("Aurelion Sol", "AurelionSolQ")
    assert str(q["mScriptName"]) == "AurelionSolQ"


def test_missing_champion_fails_closed(tmp_path, monkeypatch):
    from src.calculator import binary_roots

    monkeypatch.setattr(binary_roots, "_BIN_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="character binary unavailable"):
        binary_roots.character_bin("Nobody")


def test_spell_object_lookup_is_exact_and_fail_closed():
    assert spell_object("Dr. Mundo", "DrMundoQ") is not None
    with pytest.raises(RuntimeError, match="not found"):
        spell_object("Dr. Mundo", "DrMundoNoSuchSpell")
    # A substring of a real name must NOT match.
    with pytest.raises(RuntimeError, match="not found"):
        spell_object("Aurelion Sol", "AurelionSol")


def test_data_value_reads_the_first_rank_row():
    q = spell_object("Aurelion Sol", "AurelionSolQ")
    assert data_value(q, "QMassStolen") == pytest.approx(2.0)
    e = spell_object("Aurelion Sol", "AurelionSolE")
    assert data_value(e, "BaseExecutionThreshold") == pytest.approx(5.0)


def test_data_value_failures_are_named_not_zero():
    e = spell_object("Aurelion Sol", "AurelionSolE")
    # The E dump carries GravityIncPerBreakpoint with NO values row.
    with pytest.raises(RuntimeError, match="carries no values row"):
        data_value(e, "GravityIncPerBreakpoint")
    with pytest.raises(RuntimeError, match="not found"):
        data_value(e, "NoSuchDataValue")


def test_aurelion_sol_module_constants_come_from_the_binary():
    """The pilot: the module no longer hand-copies its Stardust constants."""
    from src.calculator.champions.aurelion_sol import (
        _E_EXECUTE_BASE_PCT,
        _E_EXECUTE_PCT_PER_100_STARDUST,
        _Q_BURST_MAXHP_PCT_PER_STARDUST,
        _STARDUST_PER_Q_BURST,
    )

    q = spell_object("Aurelion Sol", "AurelionSolQ")
    e = spell_object("Aurelion Sol", "AurelionSolE")
    assert data_value(q, "QMaxHealthTrueDamagePerStack") * 100.0 == pytest.approx(
        _Q_BURST_MAXHP_PCT_PER_STARDUST
    )
    assert data_value(e, "BaseExecutionThreshold") == pytest.approx(_E_EXECUTE_BASE_PCT)
    assert data_value(e, "ExecutionGrowthPerBreakpoint") * 100.0 == pytest.approx(
        _E_EXECUTE_PCT_PER_100_STARDUST
    )
    assert data_value(q, "QMassStolen") == pytest.approx(_STARDUST_PER_Q_BURST)


class TestBatch2VladimirAndYone:
    """Batch 2: Vladimir's timings/amp and Yone's Spirit Form window are
    rooted in their binaries, not hand-copied."""

    def test_vladimir_constants_come_from_the_binary(self):
        import src.calculator.champions.vladimir as vlad

        e = spell_object("Vladimir", "VladimirE")
        r = spell_object("Vladimir", "VladimirHemoplague")
        assert data_value(e, "TimetoRampMaxDamage") == pytest.approx(
            vlad._E_CHARGE_RAMP_SECONDS
        )
        assert data_value(e, "MaxChannelTime") == pytest.approx(vlad._E_CHANNEL_SECONDS)
        assert data_value(r, "Duration") == pytest.approx(vlad._R_INFECTION_SECONDS)
        assert data_value(r, "DamageAmp") / 100.0 == pytest.approx(
            vlad._R_HEMOPLAGUE_INCREASE
        )

    def test_yone_spirit_form_window_comes_from_the_binary(self):
        import src.calculator.champions.yone as yone

        e = spell_object("Yone", "YoneE")
        assert data_value(e, "ReturnTimer") == pytest.approx(
            yone._E_SPIRIT_FORM_SECONDS
        )

    def test_yone_q3_knockup_binary_agrees_with_the_cached_description(self):
        """Two roots, one number: the binary Q3KnockupDuration and the live
        description-branch read must agree — either drifting fails closed."""
        from src.calculator.champions.module_helpers import q3_knockup_duration
        from src.calculator.data_fetcher import get_champion

        q_ability = get_champion("Yone")["abilities"]["Q"][0]
        live = q3_knockup_duration("Yone", q_ability)
        binary = data_value(spell_object("Yone", "YoneQ"), "Q3KnockupDuration")
        assert binary == pytest.approx(live)
