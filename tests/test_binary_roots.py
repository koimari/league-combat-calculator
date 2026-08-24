"""The shared character-binary runtime seam (``src/calculator/binary_roots``).

Phase 1 of binary-rooting every champion's values: the dumps are tracked,
every cache name resolves to one, and lookups fail closed.
"""

import json
from pathlib import Path

import pytest

from src.calculator.binary_roots import (
    _BIN_DIR,
    calculation_breakpoints,
    champion_key,
    character_bin,
    character_record_root,
    data_value,
    record_value,
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


class TestBatch3RootedConstants:
    """Batch 3: Varus, Udyr, Seraphine, Senna, Ezreal and Darius constants
    resolve from their binaries; each test re-reads the root so a patch
    moving either side trips."""

    def test_varus(self):
        import src.calculator.champions.varus as varus

        w = spell_object("Varus", "VarusW")
        p = spell_object("Varus", "VarusPassive")
        assert data_value(w, "MaxStacks") == varus._BLIGHT_MAX_STACKS
        assert data_value(p, "PassiveAS") * 100.0 == pytest.approx(
            varus._P_TAKEDOWN_ATTACK_SPEED
        )
        assert data_value(p, "AStoADChampion") / 100.0 == pytest.approx(
            varus._P_TAKEDOWN_DERIVED_RATIO
        )

    def test_udyr(self):
        import src.calculator.champions.udyr as udyr

        assert data_value(spell_object("Udyr", "UdyrQ"), "Bounces") == (
            udyr._Q_LIGHTNING_STRIKES_PER_ATTACK
        )
        assert data_value(spell_object("Udyr", "UdyrE"), "MoveSpeedDuration") == (
            pytest.approx(udyr._E_MOVE_SPEED_SECONDS)
        )
        # The strike interval stays prose-rooted (no binary home).
        assert udyr._Q_LIGHTNING_HIT_INTERVAL == pytest.approx(0.2)

    def test_seraphine(self):
        import src.calculator.champions.seraphine as seraphine

        q = spell_object("Seraphine", "SeraphineQ")
        w = spell_object("Seraphine", "SeraphineW")
        assert data_value(q, "DamageAmp") / 100.0 == pytest.approx(
            seraphine._Q_MISSING_HEALTH_MAX_BONUS
        )
        assert data_value(w, "WMSBonus") * 100.0 == pytest.approx(
            seraphine._W_MOVE_SPEED_PERCENT
        )
        assert data_value(w, "WMSBonusAPRatio") * 10000.0 == pytest.approx(
            seraphine._W_MOVE_SPEED_PER_100_AP
        )

    def test_senna(self):
        import src.calculator.champions.senna as senna

        p = spell_object("Senna", "SennaPassive")
        r = spell_object("Senna", "SennaR")
        assert data_value(p, "ADPerStack") == pytest.approx(senna._MIST_AD_PER_STACK)
        assert data_value(p, "StacksForBonus") == senna._MIST_STACKS_PER_THRESHOLD
        assert data_value(p, "BonusRange") == pytest.approx(
            senna._MIST_RANGE_PER_THRESHOLD
        )
        assert data_value(r, "ShieldDuration") == pytest.approx(
            senna._DAWNING_SHADOW_SHIELD_DURATION_SECONDS
        )

    def test_ezreal(self):
        import src.calculator.champions.ezreal as ezreal

        p = spell_object("Ezreal", "EzrealPassive")
        w = spell_object("Ezreal", "EzrealW")
        assert data_value(p, "AttackSpeedPerStack") * 100.0 == pytest.approx(
            ezreal.PASSIVE_AS_PER_STACK
        )
        assert data_value(p, "MaxStacks") == ezreal.PASSIVE_MAX_STACKS
        assert data_value(spell_object("Ezreal", "EzrealQ"), "CDRefund") == (
            pytest.approx(ezreal.Q_REFUND_SECONDS)
        )
        assert data_value(w, "ManaReturn") == pytest.approx(ezreal.W_MARK_REFUND_FLAT)
        assert data_value(w, "DetonationTimeout") == pytest.approx(
            ezreal.W_MARK_WINDOW_SECONDS
        )

    def test_darius(self):
        import src.calculator.champions.darius as darius

        hemo = spell_object("Darius", "DariusHemoMarker")
        assert data_value(hemo, "BleedDuration") == pytest.approx(
            darius.P_BLEED_DURATION
        )
        assert data_value(hemo, "MaxStacks") == darius.P_BLEED_MAX_STACKS
        # DOCUMENTED DRIFT: the binary cadence reads 1.26; the module prices
        # the wiki's 4-ticks-over-5s shape (1.25).  Pinned here so a patch
        # that settles it flips this test deliberately.
        assert data_value(hemo, "SecondsPerTick") != pytest.approx(
            darius.P_BLEED_TICK_INTERVAL
        )


class TestBatch4MundoAndJayce:
    """Batch 4: Dr. Mundo's W/E/R surfaces and Jayce's Hyper Charge read
    their roots from the binary."""

    def test_dr_mundo(self):
        import src.calculator.champions.dr_mundo as mundo

        w = spell_object("Dr. Mundo", "DrMundoW")
        e = spell_object("Dr. Mundo", "DrMundoE")
        r = spell_object("Dr. Mundo", "DrMundoR")
        assert data_value(w, "Duration") == pytest.approx(mundo.W_DURATION)
        assert data_value(w, "Duration") == pytest.approx(mundo.W_DETONATION_TIME)
        assert data_value(e, "MaxMissingHealthThreshold") * 100.0 == pytest.approx(
            mundo.E_MAX_AMP_MISSING_HEALTH_PERCENT
        )
        assert data_value(r, "BonusPerNearbyChampion") == pytest.approx(
            mundo.R_NEARBY_CHAMPION_BONUS
        )

    def test_jayce_hyper_charge(self):
        import src.calculator.champions.jayce as jayce

        hc = spell_object("Jayce", "JayceHyperCharge")
        assert data_value(hc, "PercentIncreasedAS") * 100.0 == pytest.approx(
            jayce.HYPER_CHARGE_BONUS_ATTACK_SPEED
        )
        assert data_value(hc, "NumAttacks") == jayce.HYPER_CHARGE_ATTACKS


def test_data_value_snaps_float32_storage_noise():
    """The dumps are float32: an authored 0.7 arrives as
    0.69999998807...  The read restores the authored decimal (six
    significant digits) so downstream math divides by exactly what the
    game authors — and the golden gate stays byte-exact."""
    e = spell_object("Dr. Mundo", "DrMundoE")
    assert repr(data_value(e, "MaxMissingHealthThreshold")) == "0.7"
    q = spell_object("Aurelion Sol", "AurelionSolQ")
    assert repr(data_value(q, "QMaxHealthTrueDamagePerStack")) == "0.00031"
    assert repr(data_value(q, "APPerSecond")) == "0.55"


class TestBatch5RootedConstants:
    """Batch 5: Naafiri, Rammus, Shaco and Syndra constants resolve from
    their binaries."""

    def test_naafiri(self):
        import src.calculator.champions.naafiri as naafiri

        q = spell_object("Naafiri", "NaafiriQ")
        r = spell_object("Naafiri", "NaafiriR")
        assert data_value(q, "BleedInterval") == pytest.approx(
            naafiri._BLEED_TICK_INTERVAL
        )
        assert data_value(q, "BleedDuration") == pytest.approx(naafiri._BLEED_DURATION)
        assert naafiri._BLEED_TICKS == 10
        assert data_value(r, "NaafiriADPercentBoost") * 100.0 == pytest.approx(
            naafiri._HUNT_AD_PERCENT
        )
        assert data_value(r, "Duration") == pytest.approx(naafiri._HUNT_DURATION)

    def test_rammus(self):
        import src.calculator.champions.rammus as rammus

        w = spell_object("Rammus", "DefensiveBallCurl")
        p = spell_object("Rammus", "RammusP")
        assert data_value(w, "DamageArmorRatio") == pytest.approx(
            rammus._THORNS_ARMOR_RATIO
        )
        assert data_value(w, "DamageMRRatio") == pytest.approx(
            rammus._THORNS_MAGIC_RESISTANCE_RATIO
        )
        assert data_value(p, "ArmorRatio") == pytest.approx(
            rammus._SPIKED_SHELL_ARMOR_RATIO
        )
        assert data_value(p, "MagicResistRatio") == pytest.approx(
            rammus._SPIKED_SHELL_MAGIC_RESISTANCE_RATIO
        )
        # DOCUMENTED DIVERGENCE: the binary BaseDamage reads 10; the module
        # prices the wiki prose's 15.
        assert data_value(p, "BaseDamage") != pytest.approx(rammus._THORNS_BASE)

    def test_shaco(self):
        import src.calculator.champions.shaco as shaco

        p = spell_object("Shaco", "ShacoPassive")
        assert data_value(p, "AttackBonusADRatio") == pytest.approx(
            shaco._BACKSTAB_BONUS_AD_RATIO
        )
        # DOCUMENTED CONFLICT: the binary clone ratio reads 0.60; the wiki
        # Pets prose (and the module) price 0.75.
        full = spell_object("Shaco", "HallucinateFull")
        assert data_value(full, "CloneAADamagePercent") != pytest.approx(
            shaco._CLONE_ATTACK_AD_RATIO
        )

    def test_syndra(self):
        import src.calculator.champions.syndra as syndra

        p = spell_object("Syndra", "SyndraPassive")
        assert data_value(p, "CapstoneAPPerc") == pytest.approx(
            syndra.TRANSCENDENT_AP_MULTIPLIER
        )
        assert data_value(p, "MaxStackAmount") == syndra.SPLINTERS_FULL


class TestBatch6RootedConstants:
    """Batch 6: Olaf's W shield shape and Yi's Highlander window resolve
    from their binaries; conflicts stay pinned."""

    def test_olaf(self):
        import src.calculator.champions.olaf as olaf

        w = spell_object("Olaf", "OlafFrenziedStrikes")
        assert data_value(w, "ShieldDuration") == pytest.approx(
            olaf.TOUGH_IT_OUT_SHIELD_DURATION_SECONDS
        )
        assert data_value(w, "ShieldPercMissingHP") == pytest.approx(
            olaf.TOUGH_IT_OUT_MISSING_HEALTH_RATIO
        )

    def test_master_yi(self):
        import src.calculator.champions.master_yi as yi

        assert data_value(spell_object("Master Yi", "Highlander"), "RDuration") == (
            pytest.approx(yi._R_DURATION_SECONDS)
        )
        # DOCUMENTED CONFLICT: the binary AttackCount reads 4; the wiki
        # prose (and the module) price a 3-hit cadence.
        assert data_value(
            spell_object("Master Yi", "MasterYiPassive"), "AttackCount"
        ) != (yi._DOUBLE_STRIKE_STACKS)


class TestBatch7RootedConstants:
    """Batch 7: Teemo, Twitch, Vel'Koz and Vex windows/shapes resolve from
    their binaries."""

    def test_teemo(self):
        import src.calculator.champions.teemo as teemo

        assert data_value(
            spell_object("Teemo", "TeemoW"), "ActiveMoveSpeedBuffDuration"
        ) == pytest.approx(teemo._W_ACTIVE_SECONDS)

    def test_twitch(self):
        import src.calculator.champions.twitch as twitch

        assert data_value(
            spell_object("Twitch", "TwitchHideInShadows"), "AttackSpeedDuration"
        ) == pytest.approx(twitch._Q_ATTACK_SPEED_WINDOW)
        assert (
            data_value(spell_object("Twitch", "TwitchDeadlyVenomMarker"), "MaxStacks")
            == twitch._POISON_MAX_STACKS
        )

    def test_velkoz(self):
        import src.calculator.champions.velkoz as velkoz

        assert data_value(spell_object("Vel'Koz", "VelkozPassive"), "MaxStacks") == (
            velkoz._PROC_STACKS
        )

    def test_vex(self):
        import src.calculator.champions.vex as vex

        assert data_value(spell_object("Vex", "VexW"), "ShieldDuration") == (
            pytest.approx(vex._PERSONAL_SPACE_SHIELD_DURATION_SECONDS)
        )


class TestBatch8RootedConstants:
    """Batch 8: Annie, Brand, Warwick and Tristana constants resolve from
    their binaries."""

    def test_annie(self):
        import src.calculator.champions.annie as annie

        r = spell_object("Annie", "AnnieR")
        assert data_value(r, "TibbersAttackAPRatio") == pytest.approx(
            annie._TIBBERS_AUTO_AP_RATIO
        )
        assert data_value(r, "EnrageDuration") == pytest.approx(
            annie._TIBBERS_ENRAGE_SECONDS
        )

    def test_brand(self):
        import src.calculator.champions.brand as brand

        assert data_value(
            spell_object("Brand", "BrandPassive"), "PercentHealthDamage"
        ) / 100.0 == pytest.approx(brand._ABLAZE_DOT_PCT_MAX_HP)

    def test_warwick(self):
        import src.calculator.champions.warwick as warwick

        p = spell_object("Warwick", "WarwickP")
        assert data_value(p, "HealingThreshold") * 100.0 == pytest.approx(
            warwick._HUNGER_HEAL_HEALTH_PERCENT
        )
        assert data_value(p, "HealingRatio") == pytest.approx(
            warwick._HUNGER_HEAL_SHARE
        )
        assert data_value(p, "EmpoweredHealingThreshold") * 100.0 == pytest.approx(
            warwick._HUNGER_RAGE_HEALTH_PERCENT
        )
        assert data_value(p, "EmpoweredHealingRatio") == pytest.approx(
            warwick._HUNGER_RAGE_SHARE
        )

    def test_tristana(self):
        import src.calculator.champions.tristana as tristana

        assert data_value(spell_object("Tristana", "TristanaE"), "ActiveMaxStacks") == (
            tristana._E_MAX_STACKS
        )


class TestBatch9RootedConstants:
    """Batch 9: Yorick's Maiden AD ratio resolves from the binary."""

    def test_yorick(self):
        import src.calculator.champions.yorick as yorick

        assert data_value(spell_object("Yorick", "YorickR"), "MaidenADRatio") == (
            pytest.approx(yorick._MAIDEN_AD_RATIO)
        )


class TestBatch10GnarCrossFile:
    """Batch 10: Gnar's Mega deltas are computed from the two tracked
    binaries (GnarBig root minus Mini root) at import."""

    def test_gnar_deltas_come_from_both_roots(self):
        from src.calculator.champions.gnar import (
            MEGA_ATTACK_SPEED_LOSS,
            MEGA_BONUS_AD,
            MEGA_BONUS_ARMOR,
            MEGA_BONUS_HEALTH,
            MEGA_BONUS_MR,
        )

        mini = character_record_root("Gnar")
        mega = character_record_root("GnarBig")
        assert (
            record_value(mega, "baseHPModifiable")
            - record_value(mini, "baseHPModifiable")
        ) == MEGA_BONUS_HEALTH[0]
        assert (
            record_value(mega, "hpPerLevelModifiable")
            - record_value(mini, "hpPerLevelModifiable")
        ) == MEGA_BONUS_HEALTH[1]
        assert (6.0, 2.3) == MEGA_BONUS_AD
        assert (4.0, 3.0) == MEGA_BONUS_ARMOR
        assert (3.0, 3.5) == MEGA_BONUS_MR
        assert (0.0, 5.5) == MEGA_ATTACK_SPEED_LOSS

    def test_character_record_root_fail_closed(self):
        with pytest.raises(RuntimeError):
            character_record_root("Nobody")


class TestBatch11JayceStance:
    """Batch 11: Jayce's transform-stance tuples come from the binary's
    mSpellCalculations breakpoint nodes."""

    def test_jayce_stance_breakpoints(self):
        from src.calculator.champions.jayce import (
            CANNON_SHRED_PERCENT,
            HAMMER_BONUS_RESISTS,
            HAMMER_EMPOWERED_AUTO_DAMAGE,
        )

        stance = spell_object("Jayce", "JayceStanceHtG")
        assert calculation_breakpoints(stance, "Resists") == HAMMER_BONUS_RESISTS
        assert calculation_breakpoints(stance, "Damage") == (
            HAMMER_EMPOWERED_AUTO_DAMAGE
        )
        assert (
            tuple(
                value * 100.0
                for value in calculation_breakpoints(stance, "RangedFormShred")
            )
            == CANNON_SHRED_PERCENT
        )


class TestBatch12RootedConstants:
    """Batch 12: Braum's passive shape, Volibear's E shield trio, Sett's
    Haymaker window and Shen's Ki Barrier duration resolve from binaries."""

    def test_braum(self):
        import src.calculator.champions.braum as braum

        p = spell_object("Braum", "BraumPassive")
        assert data_value(p, "StackCap") == braum._STACKS_TO_PROC
        assert data_value(p, "StackDuration") == pytest.approx(braum._STACK_DURATION)

    def test_volibear(self):
        import src.calculator.champions.volibear as volibear

        e = spell_object("Volibear", "VolibearE")
        assert data_value(e, "ShieldAmount") == pytest.approx(
            volibear._SKY_SPLITTER_SHIELD_MAX_HP_RATIO
        )
        assert data_value(e, "ShieldAPRatio") == pytest.approx(
            volibear._SKY_SPLITTER_SHIELD_AP_RATIO
        )
        assert data_value(e, "ShieldDuration") == pytest.approx(
            volibear._SKY_SPLITTER_SHIELD_DURATION_SECONDS
        )

    def test_sett(self):
        import src.calculator.champions.sett as sett

        assert data_value(spell_object("Sett", "SettW"), "ShieldMaxDuration") == (
            pytest.approx(sett._W_SHIELD_DURATION_SECONDS)
        )

    def test_shen(self):
        import src.calculator.champions.shen as shen

        assert data_value(spell_object("Shen", "ShenPassive"), "ShieldDuration") == (
            pytest.approx(shen._P_SHIELD_DURATION_SECONDS)
        )


class TestBatch13RootedConstants:
    """Batch 13: Nasus, Urgot and Bel'Veth constants resolve from binaries."""

    def test_nasus(self):
        import src.calculator.champions.nasus as nasus

        assert data_value(spell_object("Nasus", "NasusR"), "QCDR") == pytest.approx(
            nasus._R_Q_COOLDOWN_MULTIPLIER
        )
        assert data_value(spell_object("Nasus", "NasusE"), "Duration") == pytest.approx(
            nasus._E_DOT_DURATION
        )

    def test_urgot(self):
        import src.calculator.champions.urgot as urgot

        w = spell_object("Urgot", "UrgotW")
        assert data_value(w, "Duration") == pytest.approx(urgot._W_DURATION)
        assert data_value(w, "WAttacksPerSecond") * urgot._W_TICK_INTERVAL == (
            pytest.approx(1.0)
        )
        assert urgot._W_SHOTS == int(urgot._W_DURATION * urgot._W_ATTACKS_PER_SECOND)

    def test_belveth(self):
        import src.calculator.champions.belveth as belveth

        p = spell_object("Bel'Veth", "BelvethPassive")
        assert data_value(p, "AttackADRatio") == pytest.approx(
            belveth.PASSIVE_BASIC_ATTACK_RATIO
        )
        assert data_value(p, "OnHitRatio") == pytest.approx(
            belveth.PASSIVE_ON_HIT_RATIO
        )
        assert data_value(spell_object("Bel'Veth", "BelvethE"), "NumberOfStrikes") == (
            belveth.E_BASE_SLASHES
        )


class TestBatch14RootedConstants:
    """Batch 14: Akshan, Camille, Kai'Sa and Lulu constants resolve from
    their binaries."""

    def test_akshan(self):
        import src.calculator.champions.akshan as akshan

        assert data_value(spell_object("Akshan", "AkshanR"), "CritDamageMod") == (
            pytest.approx(akshan._R_CRIT_EFFECTIVENESS)
        )
        assert data_value(
            spell_object("Akshan", "AkshanPassive"), "ShieldDuration"
        ) == pytest.approx(akshan._DIRTY_FIGHTING_SHIELD_DURATION_SECONDS)

    def test_camille(self):
        import src.calculator.champions.camille as camille

        assert data_value(
            spell_object("Camille", "CamillePassive"), "ShieldDuration"
        ) == pytest.approx(camille.ADAPTIVE_DEFENSES_DURATION_SECONDS)

    def test_kaisa(self):
        import src.calculator.champions.kaisa as kaisa

        assert data_value(spell_object("Kai'Sa", "KaisaPassive"), "PDuration") == (
            pytest.approx(kaisa._PLASMA_STACK_DURATION)
        )

    def test_lulu(self):
        import src.calculator.champions.lulu as lulu

        p = spell_object("Lulu", "LuluPassive")
        assert data_value(p, "NumberOfBolts") == lulu._PIX_BOLTS_DEFAULT
        assert data_value(p, "APRatioPerHit") == pytest.approx(lulu._PIX_BOLT_AP_RATIO)


class TestBatch15RootedConstants:
    """Batch 15: Kindred, Nocturne, Riven, Viktor and Viego constants
    resolve from their binaries."""

    def test_kindred(self):
        import src.calculator.champions.kindred as kindred

        assert data_value(
            spell_object("Kindred", "KindredEWrapper"), "CritMod"
        ) == pytest.approx(kindred._E_POUNCE_CRIT_EFFECTIVENESS)

    def test_nocturne(self):
        import src.calculator.champions.nocturne as nocturne

        assert data_value(
            spell_object("Nocturne", "NocturneShroudofDarkness"),
            "DoubleASDuration",
        ) == pytest.approx(nocturne._W_ENHANCED_SECONDS)

    def test_riven(self):
        import src.calculator.champions.riven as riven

        r = spell_object("Riven", "RivenFengShuiEngine")
        assert data_value(r, "PercentBonusAD") == pytest.approx(riven._R_BONUS_AD_RATIO)
        assert data_value(r, "Duration") == pytest.approx(riven._R_BUFF_DURATION)

    def test_viktor(self):
        import src.calculator.champions.viktor as viktor

        assert data_value(spell_object("Viktor", "ViktorQ"), "BuffDuration") == (
            pytest.approx(viktor._Q_SHIELD_DURATION_SECONDS)
        )

    def test_viego(self):
        import src.calculator.champions.viego as viego

        assert data_value(spell_object("Viego", "ViegoQ"), "SecondAttackAPRatio") == (
            pytest.approx(viego._Q_SECOND_STRIKE_AP_RATIO)
        )
        assert data_value(spell_object("Viego", "ViegoR"), "ADRatio") == pytest.approx(
            viego._R_BASE_AD_RATIO
        )


class TestBatch16RootedConstants:
    """Batch 16: Hecarim's W heal shape and Corki's Valkyrie cadence
    resolve from their binaries."""

    def test_hecarim(self):
        import src.calculator.champions.hecarim as hecarim

        w = spell_object("Hecarim", "HecarimW")
        assert data_value(w, "DamageLeechPerc") / 100.0 == pytest.approx(
            hecarim._SPIRIT_OF_DREAD_SHARE
        )
        assert data_value(w, "BuffDuration") == pytest.approx(
            hecarim._SPIRIT_OF_DREAD_WINDOW_SECONDS
        )

    def test_corki(self):
        import src.calculator.champions.corki as corki

        w = spell_object("Corki", "CarpetBomb")
        assert data_value(w, "MaximumTicks") == corki._W_TICKS
        assert corki._W_DURATION == pytest.approx(2.5)
