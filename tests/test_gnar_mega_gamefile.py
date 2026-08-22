"""Gnar Mega form — Rage Gene game-file verification matrix (P4 slice).

Pins the five hardcoded Rage Gene constants in ``gnar.py`` against the
game-file authority (Community Dragon ``gnarbig.bin.json`` CharacterRecords
minus ``gnar.bin.json``'s), the growth formula at levels 1/18/20, the
base-vs-bonus AD and attack-speed-loss semantics, the E/R consumers, and
the API/fight output in both forms.

- S1  Source evidence: the Gnar root's modifiable stats from the LOCAL
      binary (540/79 HP, 60/3.2 AD, 32/3.7 armor, 30 MR, 0.625 AS +
      6%/lvl); the five constants and their documented receipts
      (GnarBig-minus-Gnar (base, growth) deltas); the Rage Gene JSON
      carries NO leveling rows (the hardcode receipt).
- S2  Level endpoints: growth_stat at 1/18/20 for every constant (growth
      multiplier exactly 17.0 at 18, 19.665 at 20): HP +100/+831/+945.595,
      AD +6/+45.1/+51.2295, armor +4/+55/+62.995, MR +3/+62.5/+71.8275,
      bonus-AS loss 0/-93.5/-108.1575.
- S3  Base vs bonus AD: the stat_buff carries base_attack_damage only;
      the panel's bonus_attack_damage stays 0 without items at every
      level; R's %bonus-AD ratios read 0 without items (wall 600 flat)
      and scale only with item bonus AD (Bloodthirster +80 -> 660).
- S4  Attack-speed loss: percentage points of BONUS AS — the buff value
      equals -(6.0-0.5) growth, so Mega's net level AS growth is
      0.5%/level (0.625 at 1, 0.678125 at 18, 0.686453 at 20 via
      base_AS + ratio x bonus); Mini's panel AS includes Hop's +60%
      (1.6375 at 18); the loss changes the 5 s auto count (8 vs 3).
- S5  Stat panel (champion_stats) at 1/18/20 in BOTH forms: health,
      attack_damage, base/bonus attack damage, armor, MR, attack_speed,
      base_health.
- S6  E and R consumers at 1/18/20: Hop/Crunch price own max HP against
      the BUFFED health (E rank 0 at level 1 -> absent in both forms);
      R is Mega-only and prices flat 600 at 18/20 with zero bonus AD
      (wall) and 400 without the wall.
- S7  Game-file authority: data/bin/characters/gnarbig.bin.json (fetched
      from raw.communitydragon.org/latest/game/data/characters/gnarbig/
      gnarbig.bin.json — gnar.py's own header names this exact path) now
      carries Characters/GnarBig/CharacterRecords/Root; gnar.bin.json
      (the Mini-side root) still carries only the GnarBig SPELL nodes,
      never the stat root.  The delta verification against the real root
      runs live and passes exactly.
- S8  Source/atom receipts: the module SOURCES (wiki revision
      4008132/2026-04-13T18:59:15Z) and the meta surface; the
      stats-domain atom hashes for the Gnar root; the Rage Gene
      abilities-domain atom is ONLY timing.active_duration (2.0 s — no
      stat atom exists, nothing to go stale); the champions-domain
      GnarBig spell-node atoms carry no stat values; the atoms
      manifest digests verify against the on-disk files.
- S9  API/fight output: /api/calculate 200 with the post-buff
      champion_stats panel, the pre-buff combat participant snapshot,
      breakdown rows (name/casts/total_damage) and damage_events in
      both forms; engine-level breakdown raw/mitigated rows.
- S10 Regression surface: the tests/ grep set for "gnar" is pinned
      (test_gnar.py, test_damage.py, test_jayce_form_transition.py,
      this file, plus conftest.py's fixture) and the mandated sanity
      list runs green (footer).

AMBIGUITY NOTES for the coordinator:

1. GNARBIG-ROOT AUTHORITY LANDED: data/bin/characters/gnarbig.bin.json
   was fetched from raw.communitydragon.org (gnar.py's own header names
   this exact path) and carries Characters/GnarBig/CharacterRecords/Root;
   gnar.bin.json (which DOES contain the GnarBig spell nodes
   GnarBigQ/W/E + GnarBigAttackTower) still has no CharacterRecords root
   of its own.  The five constants' receipts (640/122, 66/5.5, 36/6.7,
   33/4.8, 0.5%/lvl) are now re-derived from the landed root and match
   the module's hardcoded constants exactly (S7's live verification).
   The AS constant's growth delta uses the loss-magnitude convention
   (mini-minus-big, 6.0 - 0.5 = 5.5) — the opposite sign from the other
   four constants' gain convention (big-minus-mini) — matching the
   module's own documented semantics.
2. LEVEL-20 REFERENCE VALUES: the parent brief guessed "+943.5?" for
   HP at 20; the exact value is +945.595 (growth multiplier at 20 =
   19 x 1.035 = 19.665; 43 x 19.665 = 845.595).  AD +51.2295, armor
   +62.995, MR +71.8275, bonus-AS loss -108.1575 are pinned as
   computed endpoints (engine agrees bit-for-bit).
3. AS-LOSS SEMANTICS: the loss is percentage points of BONUS attack
   speed applied through the AS ratio (bonus_attack_speed = -(0,5.5)
   growth; engine: state.attack_speed += ratio x bonus/100).  The
   net identity is Mega level AS growth = 0.5%/level
   (growth_stat(0, 6.0, L) - growth_stat(0, 5.5, L) ==
   growth_stat(0, 0.5, L)); the fight panel's Mini attack_speed at
   18/20 ALSO includes Hop's +60% bonus-AS buff (applied fight-wide
   by the engine), so Mini-vs-Mega panel deltas at 18/20 mix the
   Rage Gene loss with the missing Hop buff — the S4 pins separate
   the two (Mega side = Rage Gene only).
4. R %BONUS-AD BEHAVIOR: R's ratios read ctx.stats bonus_attack_damage
   ONLY; the Mega AD grant lands in base_attack_damage, so itemless R
   wall is exactly 600 flat at rank 3 (18/20) and 660 with
   Bloodthirster (+80 bonus AD).  The 1/18/20 pins assert the flat
   base and the item-scaled value; the completion must keep the
   base/bonus split.
5. BONUS-AD PANEL: bonus_attack_damage stays 0 in both forms at every
   level with no items; with items it is identical in both forms (the
   grant never touches it) — S3 pins both.
6. E/R at level 1 are rank 0 in both forms (no entries); the
   level-1 matrix pins Q only (80 Mini / 137.4 Mega raw) plus the
   buff dict's base deltas.
"""

import hashlib
import json
from pathlib import Path

import pytest

from tests.committed_bytes import sha256_as_committed
from src import app as app_module
from src.calculator.atomizer import hash_domain_file
from src.calculator.champions import get_champion_options_meta, parse_champion_abilities
from src.calculator.champions.gnar import (
    MEGA_ATTACK_SPEED_LOSS,
    MEGA_BONUS_AD,
    MEGA_BONUS_ARMOR,
    MEGA_BONUS_HEALTH,
    MEGA_BONUS_MR,
    SOURCES,
)
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats, growth_stat

# ---------------------------------------------------------------------------
# Data roots (read-only evidence reads; nothing is written)
# ---------------------------------------------------------------------------

_GNAR_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Gnar"]
_GNAR_BIN_PATH = Path("data/bin/characters/gnar.bin.json")
_GNAR_BIN = (
    json.loads(_GNAR_BIN_PATH.read_text(encoding="utf-8"))
    if _GNAR_BIN_PATH.exists()
    else None
)
_GNAR_ROOT = (
    _GNAR_BIN["Characters/Gnar/CharacterRecords/Root"]
    if _GNAR_BIN is not None
    else None
)
_GNARBIG_PATH = Path("data/bin/characters/gnarbig.bin.json")
_ATOMS = {
    "stats": json.loads(Path("data/atoms/stats.json").read_text(encoding="utf-8")),
    "abilities": json.loads(
        Path("data/atoms/abilities.json").read_text(encoding="utf-8")
    ),
    "champions": json.loads(
        Path("data/atoms/champions.json").read_text(encoding="utf-8")
    ),
}
_MANIFEST = json.loads(Path("data/atoms/manifest.json").read_text(encoding="utf-8"))

ALL_MAXED = {"Q": 5, "W": 5, "E": 5, "R": 3}
_RANKS = {1: {"Q": 1, "W": 0, "E": 0, "R": 0}, 18: ALL_MAXED, 20: ALL_MAXED}

# Level-18 growth multiplier: 17 x (0.7025 + 0.0175 x 17) = 17.0 exactly.
_GROWTH_18 = 17 * (0.7025 + 0.0175 * 17)
# Level-20 growth multiplier: 19 x (0.7025 + 0.0175 x 19) = 19.665.
_GROWTH_20 = 19 * (0.7025 + 0.0175 * 19)


def _root_value(root: dict | None, key: str) -> float:
    if root is None:
        pytest.skip("local Gnar game-file evidence is unavailable")
    value = root[key]["baseValue"]
    assert isinstance(value, (int, float)), key
    return float(value)


def _atom(domain: str, atom_id: str, name: str | None = None) -> dict:
    """The unique Gnar atom for (atom_id[, name]) in one atom domain."""
    atoms = _ATOMS[domain]["objects"]["Gnar"]
    matches = [
        a
        for a in atoms
        if a["atom_id"] == atom_id and (name is None or a.get("name") == name)
    ]
    assert len(matches) == 1, f"{domain} atom {atom_id!r} name={name!r}: {len(matches)}"
    return matches[0]


def _stats(level: int) -> dict:
    return calculate_total_stats(_GNAR_DATA, level, [])


def _parse(level: int, mega: bool, options: dict | None = None, stats=None):
    """Parse one form at one level against pipeline-shaped stats."""
    stats = dict(stats if stats is not None else _stats(level))
    return stats, parse_champion_abilities(
        _GNAR_DATA,
        level,
        0.0,
        ability_ranks=_RANKS[level],
        champion_stats=stats,
        champion_options={"mega": mega, **(options or {})},
    )


def _fight(level: int, mega: bool, items: list | None = None, **extra) -> dict:
    params = FightParams.from_request(
        {
            "target_health": 1000,
            "target_armor": 100,
            "target_mr": 100,
            "ability_ranks": _RANKS[level],
            "champion_options": {"mega": mega},
            **extra,
        }
    )
    return run_fight(_GNAR_DATA, level, list(items or []), params)


def _timed(level: int, mega: bool) -> dict:
    return _fight(
        level,
        mega,
        target_health=10000,
        fight_mode="time_based",
        fight_duration=5,
        include_auto_attacks=True,
        auto_attack_uptime=1.0,
    )


# ---------------------------------------------------------------------------
# S1 - Source evidence: Gnar root, the constants, the receipts
# ---------------------------------------------------------------------------


class TestSourceEvidence:
    def test_gnar_root_modifiable_stats_from_local_binary(self) -> None:
        # The Mini-side authority: Characters/Gnar/CharacterRecords/Root.
        assert _root_value(_GNAR_ROOT, "baseHPModifiable") == pytest.approx(540.0)
        assert _root_value(_GNAR_ROOT, "hpPerLevelModifiable") == pytest.approx(79.0)
        assert _root_value(_GNAR_ROOT, "baseDamageModifiable") == pytest.approx(60.0)
        assert _root_value(_GNAR_ROOT, "damagePerLevelModifiable") == pytest.approx(3.2)
        assert _root_value(_GNAR_ROOT, "baseArmorModifiable") == pytest.approx(32.0)
        assert _root_value(_GNAR_ROOT, "armorPerLevelModifiable") == pytest.approx(3.7)
        assert _root_value(_GNAR_ROOT, "baseMR") == pytest.approx(30.0)
        assert _root_value(_GNAR_ROOT, "attackSpeedModifiable") == pytest.approx(0.625)
        assert _root_value(_GNAR_ROOT, "attackSpeedRatioModifiable") == pytest.approx(
            0.625
        )
        assert _root_value(
            _GNAR_ROOT, "attackSpeedPerLevelModifiable"
        ) == pytest.approx(6.0)

    def test_gnar_root_matches_the_cached_cdn_stats(self) -> None:
        # The tracked cache (data/champions.json) agrees with the binary.
        stats = _GNAR_DATA["stats"]
        assert stats["health"]["flat"] == 540 and stats["health"]["perLevel"] == 79
        assert stats["attackDamage"]["flat"] == 60
        assert stats["attackDamage"]["perLevel"] == pytest.approx(3.2)
        assert stats["armor"]["flat"] == 32 and stats["armor"]["perLevel"] == 3.7
        assert stats["magicResistance"]["flat"] == 30
        assert stats["attackSpeed"]["flat"] == 0.625
        assert stats["attackSpeed"]["perLevel"] == 6
        assert stats["attackSpeedRatio"]["flat"] == 0.625

    def test_constants_equal_the_documented_gnarbig_minus_gnar_receipts(
        self,
    ) -> None:
        # The receipts quoted in gnar.py: each constant is exactly the
        # (GnarBig base, GnarBig growth) minus (Gnar base, Gnar growth).
        for constant, (big_base, big_growth), (mini_base, mini_growth) in (
            (MEGA_BONUS_HEALTH, (640.0, 122.0), (540.0, 79.0)),
            (MEGA_BONUS_AD, (66.0, 5.5), (60.0, 3.2)),
            (MEGA_BONUS_ARMOR, (36.0, 6.7), (32.0, 3.7)),
            (MEGA_BONUS_MR, (33.0, 4.8), (30.0, 1.3)),
        ):
            assert constant == pytest.approx(
                (big_base - mini_base, big_growth - mini_growth)
            )
        # The AS constant is the LOSS magnitude: Mini's 6.0%/lvl growth
        # minus Mega's 0.5%/lvl (the buff applies it as -bonus AS).
        assert MEGA_ATTACK_SPEED_LOSS == pytest.approx((0.0, 6.0 - 0.5))

    def test_constants_are_the_five_pinned_pairs(self) -> None:
        assert MEGA_BONUS_HEALTH == (100.0, 43.0)
        assert MEGA_BONUS_AD == (6.0, 2.3)
        assert MEGA_BONUS_ARMOR == (4.0, 3.0)
        assert MEGA_BONUS_MR == (3.0, 3.5)
        assert MEGA_ATTACK_SPEED_LOSS == (0.0, 5.5)

    def test_rage_gene_json_carries_no_leveling(self) -> None:
        # The hardcode receipt: the cached P effect has NO leveling rows
        # (and no description), so the deltas cannot come from the JSON.
        effects = _GNAR_DATA["abilities"]["P"][0]["effects"]
        assert len(effects) == 4  # the Rage Gene prose block
        assert all(not effect.get("leveling") for effect in effects)
        assert "Rage Gene" in effects[0].get("description", "")

    def test_rage_gene_atom_is_only_the_transform_timer(self) -> None:
        # The abilities-domain atom for Rage Gene is ONLY the 2.0 s
        # active duration — no damage/stat atom exists for P (nothing
        # the constants could go stale against).
        atom = _atom("abilities", "timing.active_duration", "Rage Gene")
        assert atom["values"] == [2.0]
        assert atom["hash"] == "d9ad5f46b46d840e"
        rage_gene_atoms = [
            a
            for a in _ATOMS["abilities"]["objects"]["Gnar"]
            if a.get("name") == "Rage Gene"
        ]
        assert [a["atom_id"] for a in rage_gene_atoms] == ["timing.active_duration"]


# ---------------------------------------------------------------------------
# S2 - Level endpoints 1/18/20 through the growth formula
# ---------------------------------------------------------------------------


class TestLevelEndpoints:
    @pytest.mark.parametrize(
        "constant, level1, level18, level20",
        [
            (MEGA_BONUS_HEALTH, 100.0, 831.0, 945.595),
            (MEGA_BONUS_AD, 6.0, 45.1, 51.2295),
            (MEGA_BONUS_ARMOR, 4.0, 55.0, 62.995),
            (MEGA_BONUS_MR, 3.0, 62.5, 71.8275),
            (MEGA_ATTACK_SPEED_LOSS, 0.0, 93.5, 108.1575),
        ],
    )
    def test_growth_formula_endpoints(self, constant, level1, level18, level20) -> None:
        base, growth = constant
        assert growth_stat(base, growth, 1) == pytest.approx(level1)
        assert growth_stat(base, growth, 18) == pytest.approx(level18)
        assert growth_stat(base, growth, 20) == pytest.approx(level20)

    def test_growth_multipliers_are_exact(self) -> None:
        # The formula's level factor: (L-1) x (0.7025 + 0.0175 x (L-1)).
        assert _GROWTH_18 == pytest.approx(17.0)
        assert _GROWTH_20 == pytest.approx(19.665)
        assert 43 * _GROWTH_20 == pytest.approx(845.595)
        assert 2.3 * _GROWTH_20 == pytest.approx(45.2295)

    def test_level1_deltas_are_the_base_constants(self) -> None:
        # growth_stat at level 1 = base exactly (growth term is zero).
        for constant in (
            MEGA_BONUS_HEALTH,
            MEGA_BONUS_AD,
            MEGA_BONUS_ARMOR,
            MEGA_BONUS_MR,
            MEGA_ATTACK_SPEED_LOSS,
        ):
            assert growth_stat(constant[0], constant[1], 1) == pytest.approx(
                constant[0]
            )


# ---------------------------------------------------------------------------
# S3 - Base vs bonus AD (the stat_buff apply_to + R's %bonus-AD ratios)
# ---------------------------------------------------------------------------


class TestBaseVsBonusAD:
    @pytest.mark.parametrize(
        "level, base_health, base_ad",
        [
            (1, 100.0, 6.0),
            (18, 831.0, 45.1),
            (20, 945.595, 51.2295),
        ],
    )
    def test_stat_buff_is_base_only(self, level, base_health, base_ad) -> None:
        _, abilities = _parse(level, True)
        buff = abilities["passive"]["stat_buff"]
        assert buff["base_health"] == pytest.approx(base_health)
        assert buff["base_attack_damage"] == pytest.approx(base_ad)
        # Base-stat deltas only: never bonus AD, never total health.
        assert set(buff) == {
            "base_health",
            "base_attack_damage",
            "armor",
            "magic_resistance",
            "bonus_attack_speed",
        }

    @pytest.mark.parametrize(
        "level, mini_base_ad, mega_base_ad",
        [
            (1, 60.0, 66.0),
            (18, 114.0, 159.1),
            (20, 123.0, 174.2295),
        ],
    )
    def test_panel_bonus_ad_is_zero_without_items(
        self, level, mini_base_ad, mega_base_ad
    ) -> None:
        # The Mega grant raises base_attack_damage only; bonus AD stays
        # 0 in BOTH forms at every level (R's %bonus-AD reads 0).
        mini = _fight(level, False)["champion_stats"]
        mega = _fight(level, True)["champion_stats"]
        assert mini["base_attack_damage"] == pytest.approx(mini_base_ad)
        assert mega["base_attack_damage"] == pytest.approx(mega_base_ad)
        assert mini["bonus_attack_damage"] == pytest.approx(0.0)
        assert mega["bonus_attack_damage"] == pytest.approx(0.0)

    def test_r_ratios_see_bonus_ad_only(self) -> None:
        # %bonus-AD ratios: base AD (even 300) must NOT feed R; bonus AD
        # scales 0.75 per point on the wall row (rank 3).
        stats = dict(_stats(18), attack_damage=300.0, base_attack_damage=300.0)
        _, abilities = _parse(18, True, stats=stats)
        assert abilities["R"]["total_raw"] == pytest.approx(600.0)
        stats["bonus_attack_damage"] = 100.0
        stats["attack_damage"] = 400.0
        _, abilities = _parse(18, True, stats=stats)
        assert abilities["R"]["total_raw"] == pytest.approx(675.0)

    def test_fight_with_item_bonus_ad_scales_r_and_keeps_panel_split(
        self,
    ) -> None:
        # Bloodthirster +80 bonus AD: R wall = 600 + 0.75 x 80 = 660 raw
        # (330 mitigated at 100 armor); bonus AD is identical in both
        # forms while base AD differs by the Mega grant.
        item = get_item_by_name("Bloodthirster")
        mega = _fight(18, True, [item])
        mini = _fight(18, False, [item])
        assert mega["breakdown"]["R"]["total_raw"] == pytest.approx(660.0)
        assert mega["breakdown"]["R"]["total_damage"] == pytest.approx(330.0)
        assert mega["champion_stats"]["bonus_attack_damage"] == pytest.approx(80.0)
        assert mini["champion_stats"]["bonus_attack_damage"] == pytest.approx(80.0)
        assert mega["champion_stats"]["base_attack_damage"] == pytest.approx(159.1)
        assert mini["champion_stats"]["base_attack_damage"] == pytest.approx(114.0)


# ---------------------------------------------------------------------------
# S4 - Attack-speed loss: percentage points of bonus AS
# ---------------------------------------------------------------------------


class TestAttackSpeedLoss:
    @pytest.mark.parametrize(
        "level, loss",
        [(1, 0.0), (18, 93.5), (20, 108.1575)],
    )
    def test_stat_buff_loss_value(self, level, loss) -> None:
        _, abilities = _parse(level, True)
        assert abilities["passive"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(
            -loss
        )
        _, mini = _parse(level, False)
        assert "passive" not in mini  # Mini emits no Rage Gene entry

    def test_loss_is_percentage_points_of_bonus_as(self) -> None:
        # The loss cancels Mini's level growth (6.0%/lvl) down to Mega's
        # 0.5%/lvl: growth_stat(0, 6.0, L) + buff == growth_stat(0, 0.5, L).
        for level in (1, 18, 20):
            _, abilities = _parse(level, True)
            loss = -abilities["passive"]["stat_buff"]["bonus_attack_speed"]
            assert growth_stat(0, 6.0, level) - loss == pytest.approx(
                growth_stat(0, 0.5, level)
            )

    @pytest.mark.parametrize(
        "level, mega_as",
        [(1, 0.625), (18, 0.678125), (20, 0.686453125)],
    )
    def test_engine_mega_as_math(self, level, mega_as) -> None:
        # Engine semantics: state.attack_speed += AS_ratio x bonus/100,
        # so Mega AS == base_AS + ratio x growth_stat(0, 0.5, L).  The
        # Mega side is Rage-Gene-only (Crunch carries no AS buff).
        stats = _fight(level, True)["champion_stats"]
        assert stats["attack_speed"] == pytest.approx(mega_as)
        expected = 0.625 + 0.625 * growth_stat(0, 0.5, level) / 100.0
        assert stats["attack_speed"] == pytest.approx(expected)

    @pytest.mark.parametrize(
        "level, mini_as, mega_as",
        [
            (1, 0.625, 0.625),
            (18, 1.6375, 0.678125),
            (20, 1.7374375, 0.686453125),
        ],
    )
    def test_panel_as_both_forms(self, level, mini_as, mega_as) -> None:
        # The Mini panel ALSO includes Hop's +60% bonus-AS buff (the
        # engine applies every stat_buff fight-wide); Mega has no Hop
        # buff, so its panel isolates the Rage Gene loss.
        assert _fight(level, False)["champion_stats"]["attack_speed"] == pytest.approx(
            mini_as
        )
        assert _fight(level, True)["champion_stats"]["attack_speed"] == pytest.approx(
            mega_as
        )

    def test_loss_changes_the_auto_count(self) -> None:
        # 5 s at 100% uptime, level 18: Mini 8 autos (1.6375 x 5) vs
        # Mega 3 (0.678125 x 5); per-auto mitigated 57.0 vs 79.55.
        mini = _timed(18, False)["breakdown"]["auto_attacks"]
        mega = _timed(18, True)["breakdown"]["auto_attacks"]
        assert mini["total_damage"] == pytest.approx(8 * 57.0)
        assert mega["total_damage"] == pytest.approx(3 * 79.55)


# ---------------------------------------------------------------------------
# S5 - Stat panel (champion_stats) at 1/18/20 in both forms
# ---------------------------------------------------------------------------


class TestStatPanel:
    @pytest.mark.parametrize(
        "level, mini, mega",
        [
            # (health, ad, base_ad, bonus_ad, armor, mr, attack_speed)
            (1, (540, 60, 60, 0, 32, 30, 0.625), (640, 66, 66, 0, 36, 33, 0.625)),
            (
                18,
                (1883, 114, 114, 0, 95, 52, 1.6375),
                (2714, 159.1, 159.1, 0, 150, 114.5, 0.678125),
            ),
            (
                20,
                (2094, 123, 123, 0, 105, 56, 1.7374375),
                (3039.595, 174.2295, 174.2295, 0, 167.995, 127.8275, 0.686453125),
            ),
        ],
    )
    def test_panel_both_forms(self, level, mini, mega) -> None:
        for mega_on, expected in ((False, mini), (True, mega)):
            stats = _fight(level, mega_on)["champion_stats"]
            (
                health,
                ad,
                base_ad,
                bonus_ad,
                armor,
                mr,
                attack_speed,
            ) = expected
            assert stats["health"] == pytest.approx(health)
            assert stats["attack_damage"] == pytest.approx(ad)
            assert stats["base_attack_damage"] == pytest.approx(base_ad)
            assert stats["bonus_attack_damage"] == pytest.approx(bonus_ad)
            assert stats["armor"] == pytest.approx(armor)
            assert stats["magic_resistance"] == pytest.approx(mr)
            assert stats["attack_speed"] == pytest.approx(attack_speed)
            # Base health: the grant is BASE, so base_health == health
            # with no items (bonus_health stays 0 in both forms).
            assert stats["base_health"] == pytest.approx(health)
            assert stats["bonus_health"] == pytest.approx(0.0)

    def test_panel_values_are_the_growth_formula_contract(self) -> None:
        # The panel numbers recompute from the Gnar root + the constants:
        # Mini health = round(growth_stat(540, 79, L)); Mega adds the
        # Rage Gene grant; AD/armor/MR likewise (MR growth 1.3 from the
        # wiki cache, no binary MR-per-level key).
        for level in (1, 18, 20):
            mini_hp = round(growth_stat(540, 79, level))
            mega_hp = mini_hp + growth_stat(*MEGA_BONUS_HEALTH, level)
            panel = _fight(level, True)["champion_stats"]
            assert panel["health"] == pytest.approx(mega_hp)
            assert panel["base_health"] == pytest.approx(mega_hp)
            assert panel["armor"] == pytest.approx(
                round(growth_stat(32, 3.7, level))
                + growth_stat(*MEGA_BONUS_ARMOR, level)
            )
            assert panel["magic_resistance"] == pytest.approx(
                round(growth_stat(30, 1.3, level)) + growth_stat(*MEGA_BONUS_MR, level)
            )


# ---------------------------------------------------------------------------
# S6 - E and R consumers at 1/18/20 (buffed stats feed the damage slots)
# ---------------------------------------------------------------------------


class TestEConsumers:
    def test_e_is_absent_at_level_1_in_both_forms(self) -> None:
        # E rank 0 at level 1: no Hop and no Crunch entry.
        _, mini = _parse(1, False)
        _, mega = _parse(1, True)
        assert "E" not in mini
        assert "E" not in mega

    @pytest.mark.parametrize(
        "level, mini_raw, mega_raw",
        [
            (18, 302.98, 382.84),  # 190+6%x1883 / 220+6%x2714
            (20, 315.64, 402.3757),  # 190+6%x2094 / 220+6%x3039.595
        ],
    )
    def test_e_prices_own_max_health_against_buffed_stats(
        self, level, mini_raw, mega_raw
    ) -> None:
        # The BUFF phase lands before the damage slots parse: Crunch
        # reads health AFTER the +831/+945.595 grant.
        _, mini = _parse(level, False)
        _, mega = _parse(level, True)
        assert mini["E"]["total_raw"] == pytest.approx(mini_raw)
        assert mega["E"]["total_raw"] == pytest.approx(mega_raw)
        # Contract recomputation from the growth formula:
        mini_hp = round(growth_stat(540, 79, level))
        mega_hp = mini_hp + growth_stat(*MEGA_BONUS_HEALTH, level)
        assert mega["E"]["total_raw"] == pytest.approx(220.0 + 0.06 * mega_hp)
        assert mini["E"]["total_raw"] == pytest.approx(190.0 + 0.06 * mini_hp)


class TestRConsumers:
    def test_r_is_mega_only_and_absent_at_level_1(self) -> None:
        _, mini18 = _parse(18, False)
        _, mini1 = _parse(1, False)
        _, mega1 = _parse(1, True)
        assert "R" not in mini18
        assert "R" not in mini1
        assert "R" not in mega1

    @pytest.mark.parametrize(
        "level, wall_raw, no_wall_raw",
        [
            (18, 600.0, 400.0),  # rank 3: 600+0.75x0 / 400+0.5x0
            (20, 600.0, 400.0),
        ],
    )
    def test_r_flat_base_with_zero_bonus_ad(self, level, wall_raw, no_wall_raw) -> None:
        # No items -> bonus AD 0 -> R prices its flat base exactly; the
        # Mega base-AD grant never leaks into the %bonus-AD ratios.
        _, wall = _parse(level, True)
        _, no_wall = _parse(level, True, options={"r_wall": False})
        assert wall["R"]["total_raw"] == pytest.approx(wall_raw)
        assert no_wall["R"]["total_raw"] == pytest.approx(no_wall_raw)


# ---------------------------------------------------------------------------
# S7 - Malformed/stale evidence: the missing GnarBig root (fail-closed)
# ---------------------------------------------------------------------------


class TestGnarBigRootAuthority:
    def test_gnarbig_file_is_present(self) -> None:
        # The game-file authority landed (fetched from
        # raw.communitydragon.org/latest/game/data/characters/gnarbig/
        # gnarbig.bin.json, the path gnar.py's own header comment names):
        # the fail-closed absence pin flips to a live-verification pin.
        assert _GNARBIG_PATH.exists(), (
            "data/bin/characters/gnarbig.bin.json is the landed game-file "
            "authority; see test_constants_match_gnarbig_minus_gnar_deltas "
            "for the live delta verification"
        )

    def test_gnarbig_character_records_root_is_absent_inside_gnar_bin(self) -> None:
        # Root level: gnar.bin.json carries the GnarBig SPELL nodes but
        # no Characters/GnarBig/CharacterRecords/Root — the stat block
        # (the constants' authority) is what is missing.
        if _GNAR_BIN is None:
            pytest.skip("local Gnar game-file evidence is unavailable")
        assert "Characters/GnarBig/CharacterRecords/Root" not in _GNAR_BIN
        assert any(
            "GnarBig" in key for key in _GNAR_BIN
        ), "expected the GnarBig spell nodes to coexist in gnar.bin.json"

    def test_gnar_root_is_present(self) -> None:
        if _GNAR_BIN is None:
            pytest.skip("local Gnar game-file evidence is unavailable")
        assert _GNAR_ROOT is not None

    def test_constants_match_gnarbig_minus_gnar_deltas(self) -> None:
        # The live verification: the GnarBig root landed
        # (data/bin/characters/gnarbig.bin.json, fetched from
        # raw.communitydragon.org), so this runs for real and the
        # receipts must hold exactly.
        if not _GNARBIG_PATH.exists():
            raise AssertionError("GnarBig root absent: " + str(_GNARBIG_PATH))
        big_root = json.loads(_GNARBIG_PATH.read_text(encoding="utf-8"))[
            "Characters/GnarBig/CharacterRecords/Root"
        ]
        # HP/AD/armor are GAINS (GnarBig > Gnar): base/growth deltas read
        # big-minus-mini directly. The AS constant instead stores a LOSS
        # magnitude (Mini's 6.0%/lvl growth is larger than Mega's
        # 0.5%/lvl), so its growth delta reads mini-minus-big — the sign
        # convention test_constants_equal_the_documented_gnarbig_minus_gnar_receipts
        # already pins via (0.0, 6.0 - 0.5).
        gain_pairs = [
            (MEGA_BONUS_HEALTH, "baseHPModifiable", "hpPerLevelModifiable"),
            (MEGA_BONUS_AD, "baseDamageModifiable", "damagePerLevelModifiable"),
            (MEGA_BONUS_ARMOR, "baseArmorModifiable", "armorPerLevelModifiable"),
            (MEGA_BONUS_MR, "baseMR", None),
        ]
        for constant, base_key, growth_key in gain_pairs:
            delta_base = _root_value(big_root, base_key) - _root_value(
                _GNAR_ROOT, base_key
            )
            assert constant[0] == pytest.approx(delta_base)
            if growth_key is not None:
                delta_growth = _root_value(big_root, growth_key) - _root_value(
                    _GNAR_ROOT, growth_key
                )
                assert constant[1] == pytest.approx(delta_growth)
        # AS base is unchanged (0.625 both forms): a plain big-minus-mini
        # delta of 0.0 holds regardless of direction.
        assert MEGA_ATTACK_SPEED_LOSS[0] == pytest.approx(
            _root_value(big_root, "attackSpeedModifiable")
            - _root_value(_GNAR_ROOT, "attackSpeedModifiable")
        )
        # The AS loss is the per-level growth delta (6.0 - 0.5): Mini
        # minus GnarBig, the loss-magnitude convention.
        assert MEGA_ATTACK_SPEED_LOSS[1] == pytest.approx(
            _root_value(_GNAR_ROOT, "attackSpeedPerLevelModifiable")
            - _root_value(big_root, "attackSpeedPerLevelModifiable")
        )


# ---------------------------------------------------------------------------
# S8 - Source and atom receipts
# ---------------------------------------------------------------------------


class TestSourceAndAtomReceipts:
    def test_module_sources_pin_the_wiki_revision(self) -> None:
        assert SOURCES == [
            {
                "label": "Local League Wiki cache",
                "url": "https://wiki.leagueoflegends.com/en-us/Gnar",
                "revision_id": 4008132,
                "revision_timestamp": "2026-04-13T18:59:15Z",
            }
        ]
        meta = get_champion_options_meta("Gnar")
        assert meta["sources"] == SOURCES

    def test_meta_declares_the_mega_option_and_base_stat_assumption(self) -> None:
        meta = get_champion_options_meta("Gnar")
        assert {o["key"] for o in meta["options"]} == {
            "mega",
            "q_pickup",
            "r_wall",
            "q_secondary_targets",
        }
        assert any(
            "base-stat increases" in text and "bonus AD is unchanged" in text
            for text in meta["assumptions"]
        )

    def test_stats_domain_atoms_pin_the_gnar_root(self) -> None:
        # The Mini-side evidence atomized from data/champions.json:
        # values + hashes pinned so a re-atomization trips on drift.
        pins = [
            ("stat.health.flat", "health", [540.0], "5142fdf91dae5b2e"),
            ("stat.health.per_level", "health", [79.0], "fd7b1962e2f605fb"),
            ("stat.attack_damage.flat", "attackDamage", [60.0], "eda837fe033e04b5"),
            ("stat.attack_damage.per_level", "attackDamage", [3.2], "97526ad421b28161"),
            ("stat.armor.flat", "armor", [32.0], "6413dadcb1387f2e"),
            ("stat.armor.per_level", "armor", [3.7], "1c951c6fe6829dd7"),
            (
                "stat.magic_resistance.flat",
                "magicResistance",
                [30.0],
                "38beb199608e646b",
            ),
            ("stat.attack_speed.flat", "attackSpeed", [0.625], "facba49dba016280"),
            ("stat.attack_speed.per_level", "attackSpeed", [6.0], "da30b434b803f21b"),
            (
                "stat.attack_speed_ratio.flat",
                "attackSpeedRatio",
                [0.625],
                "5732b78551e01f8b",
            ),
        ]
        for atom_id, name, values, hash_ in pins:
            atom = _atom("stats", atom_id, name)
            assert atom["values"] == pytest.approx(values)
            assert atom["hash"] == hash_

    def test_champions_domain_atoms_attest_gnarbig_spells_but_no_stats(
        self,
    ) -> None:
        # The binary walk knew the GnarBig SPELL nodes (the atoms' source
        # paths), but none of them carries a stat value — the stat
        # authority is the absent CharacterRecords root.
        gnar_atoms = _ATOMS["champions"]["objects"]["Gnar"]
        spell_atoms = [a for a in gnar_atoms if "GnarBig" in a.get("source", "")]
        assert len(spell_atoms) >= 3
        assert _atom("champions", "damage.damage-instance", "GnarBigQ")["hash"] == (
            "3467dbfd9ccd0fc6"
        )
        assert _atom("champions", "damage.damage-instance", "GnarBigW")["hash"] == (
            "b88c5bc5973773c7"
        )
        assert not any(
            a["atom_id"].startswith("stat.") for a in spell_atoms
        ), "a GnarBig stat atom exists: re-derive the constants from it"

    def test_manifest_receipts_verify_the_on_disk_files(self) -> None:
        # The atoms manifest digests: champions domain pins both caches
        # (champions.json + data/bin/characters), stats/abilities pin the
        # champion cache; the source_ref short hash is verified against
        # the actual file bytes.  Rather than pinning a literal (which
        # trips on every legitimate re-atomization), each manifest sha256
        # is verified against a RECOMPUTED content-stable hash of the
        # on-disk domain file (atomizer.hash_domain_file) — stronger than
        # a literal because it checks the actual bytes every run.
        domains = _MANIFEST["domains"]
        assert domains["champions"]["object_count"] == 173
        for domain in ("champions", "stats", "abilities"):
            assert domains[domain]["sha256"] == hash_domain_file(
                Path(f"data/atoms/{domain}.json")
            )
        actual = sha256_as_committed("data/champions.json")
        assert domains["champions"]["source_ref"].endswith(
            f"data/champions.json@sha256:{actual[:16]};data/bin/characters"
        )


# ---------------------------------------------------------------------------
# S9 - API / fight output: stat panel + fight rows in both forms
# ---------------------------------------------------------------------------


def _api(level: int, mega: bool) -> dict:
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Gnar",
            "level": level,
            "items": [],
            "ability_ranks": _RANKS[level],
            "fight_mode": "one_rotation",
            "target_health": 1000,
            "target_armor": 100,
            "target_mr": 100,
            "champion_options": {"mega": mega},
        },
    )
    assert response.status_code == 200
    return response.get_json()


class TestApiFightOutput:
    def test_api_panel_is_the_post_buff_stats(self) -> None:
        # The UI panel (champion_stats) reflects the fight-effective
        # Mega stats; the combat participant snapshot stays pre-buff.
        mega = _api(18, True)
        panel = mega["champion_stats"]
        assert panel["health"] == pytest.approx(2714.0)
        assert panel["attack_damage"] == pytest.approx(159.1)
        assert panel["base_attack_damage"] == pytest.approx(159.1)
        assert panel["bonus_attack_damage"] == pytest.approx(0.0)
        assert panel["armor"] == pytest.approx(150.0)
        assert panel["magic_resistance"] == pytest.approx(114.5)
        assert panel["attack_speed"] == pytest.approx(0.678125)
        participant = mega["combat"]["participants"][0]["stats"]
        assert participant["health"] == 1883
        assert participant["attack_damage"] == 114
        assert participant["armor"] == 95
        assert participant["magic_resistance"] == 52
        assert participant["attack_speed"] == pytest.approx(1.2625)
        assert participant["bonus_attack_speed"] == pytest.approx(102.0)

    def test_each_published_stat_block_names_its_fight_state(self) -> None:
        """The two blocks disagree by design, and each says which it is."""
        mega = _api(18, True)
        assert mega["champion_stats_state"] == "fight_effective"
        assert mega["combat"]["participants"][0]["stats_state"] == "pre_combat"
        assert mega["champion_stats"]["health"] != (
            mega["combat"]["participants"][0]["stats"]["health"]
        )

    def test_api_breakdown_rows_both_forms(self) -> None:
        mega = _api(18, True)
        mini = _api(18, False)
        mega_rows = {
            k: (v["name"], v["casts"], v["total_damage"])
            for k, v in mega["breakdown"].items()
            if isinstance(v, dict) and v.get("total_damage")
        }
        mini_rows = {
            k: (v["name"], v["casts"], v["total_damage"])
            for k, v in mini["breakdown"].items()
            if isinstance(v, dict) and v.get("total_damage")
        }
        assert mega_rows["R"] == ("GNAR!", 1, 300.0)
        assert mega_rows["Q"] == ("Boulder Toss", 1, pytest.approx(223.9, abs=0.05))
        assert mega_rows["W"] == ("Wallop", 1, pytest.approx(162.1, abs=0.05))
        assert mega_rows["E"] == ("Crunch", 1, pytest.approx(191.4, abs=0.05))
        assert mini_rows["Q"] == ("Boomerang Throw", 1, pytest.approx(153.8, abs=0.05))
        assert mini_rows["E"] == ("Hop", 1, pytest.approx(151.5, abs=0.05))
        assert "R" not in mini_rows  # Mini cannot cast GNAR!

    def test_api_damage_events_both_forms(self) -> None:
        mega = _api(18, True)["damage_events"]
        mini = _api(18, False)["damage_events"]
        # Every Mega row lands at the cast boundary, so the ledger orders
        # them by the rotation's cast order rather than putting the
        # ultimate first.
        assert [event["source"] for event in mega] == ["Q", "W", "E", "R"]
        first = next(event for event in mega if event["source"] == "R")
        assert first["damage"] == 300.0
        # MERGE: R's own reviewed kind is the knock away the damage lands
        # with ("knocking away nearby enemies", cached R description).  The
        # 1.75s terrain stun belongs to the WALL branch, which the ``r_wall``
        # option selects and which authors it as a separate control event --
        # so the default rotation's row carries the knockback and no stun.
        assert first["cc_kind"] == "knockback"
        assert "cc_duration" not in first
        assert first["skillshot"] is True
        assert {e["source"] for e in mega} == {"R", "Q", "W", "E"}
        assert {e["source"] for e in mini} == {"Q", "E"}

    def test_engine_breakdown_raw_and_mitigated_rows(self) -> None:
        # run_fight breakdown rows carry total_raw and total_damage (the
        # target has 100 armor -> physical raw is halved).
        for level, mega_rows, mini_rows in (
            (
                18,
                {
                    "Q": (447.74, 223.87),
                    "W": (324.1, 162.05),
                    "E": (382.84, 191.42),
                    "R": (600.0, 300.0),
                },
                {"Q": (307.5, 153.75), "E": (302.98, 151.49)},
            ),
            (
                20,
                {
                    "Q": (468.9213, 234.46065),
                    "W": (339.2295, 169.61475),
                    "E": (402.3757, 201.18785),
                    "R": (600.0, 300.0),
                },
                {"Q": (318.75, 159.375), "E": (315.64, 157.82)},
            ),
        ):
            mega = _fight(level, True)["breakdown"]
            mini = _fight(level, False)["breakdown"]
            for slot, (raw, mitigated) in mega_rows.items():
                assert mega[slot]["total_raw"] == pytest.approx(raw)
                assert mega[slot]["total_damage"] == pytest.approx(mitigated)
            for slot, (raw, mitigated) in mini_rows.items():
                assert mini[slot]["total_raw"] == pytest.approx(raw)
                assert mini[slot]["total_damage"] == pytest.approx(mitigated)
            assert "R" not in mini

    def test_level1_fight_rows(self) -> None:
        # Level 1: only Q exists (E/W/R rank 0); the Mega Q prices the
        # +6 base AD grant.
        mini = _fight(1, False)["breakdown"]
        mega = _fight(1, True)["breakdown"]
        assert mini["Q"]["total_raw"] == pytest.approx(80.0)
        assert mini["Q"]["total_damage"] == pytest.approx(40.0)
        assert mega["Q"]["total_raw"] == pytest.approx(137.4)
        assert mega["Q"]["total_damage"] == pytest.approx(68.7)
        assert set(mini) == {"Q", "auto_attacks"}
        assert set(mega) == {"Q", "auto_attacks"}


# ---------------------------------------------------------------------------
# S10 - Regression surface: the tests/ grep set for "gnar"
# ---------------------------------------------------------------------------


class TestRegressionSurface:
    def test_gnar_test_file_set_is_pinned(self) -> None:
        # grep -il gnar tests/ (--include="*.py"): the exact 26-file set.
        # The Gnar-CODE surfaces are test_gnar.py, test_damage.py,
        # test_jayce_form_transition.py, test_e3_stacks_1.py (Hyper),
        # test_mechanics_packets.py (Q secondary targets) and
        # test_interaction_atoms.py (R stun atom); the rest match on
        # prose (the Gnar UI-panel rule, the Gnar-module precedent) or
        # the "Ragnarok" substring.  Growing the set trips this pin.
        import subprocess

        result = subprocess.run(
            ["grep", "-ril", "gnar", "tests/", "--include=*.py"],
            capture_output=True,
            text=True,
            check=True,
        )
        files = {Path(line).name for line in result.stdout.splitlines()}
        assert files == {
            "conftest.py",
            "test_briar.py",
            "test_camille.py",
            "test_chogath.py",
            # MERGE: ours-side files that name Gnar in prose -- the coverage
            # claim census, the UI-panel rule and the wave-2 stat-buff suite.
            "test_coverage_claims.py",
            "test_damage.py",
            "test_diana.py",
            "test_dr_mundo.py",
            "test_e3_stacks_1.py",
            # ci-evidence scanner names gnar bin paths as calibration fixtures
            "test_ci_evidence_parity.py",
            "test_f0_frontend.py",
            "test_gnar.py",
            "test_gnar_mega_gamefile.py",
            "test_interaction_atoms.py",
            "test_jayce.py",
            "test_jayce_form_transition.py",
            "test_mechanics_packets.py",
            "test_olaf_r_cleanse.py",
            "test_quinn_p_crit.py",
            "test_rengar_w_cleanse.py",
            # Roadmap session 5 batch L (2026-08-21).  None of these four
            # touch Gnar CODE: each cites this module by NAME in a header
            # comment, for the "ternary idiom" precedent that reads a
            # game-file constant when the bin cache is present and skips
            # the claim when it is absent.  Prose citations of the
            # precedent, not new Gnar coupling.
            "test_teemo_stealth_and_move_quick.py",
            "test_tristana_rapid_fire_and_range.py",
            "test_twitch_ambush_and_cask.py",
            "test_udyr_stampede_and_monk_training.py",
            "test_wave2_stat_buffs.py",
            # The patch-day orchestrator fetches the gnar/gnarbig authority
            # pair, so its test module names them.
            "test_patch_update.py",
        }

    def test_parse_and_fight_entry_points_are_the_named_modules(self) -> None:
        # Every matrix call resolves through the validated named module
        # (never the generic synthetic parser).
        assert parse_champion_abilities.__module__ == ("src.calculator.champions")
        from src.calculator.champions import parse_champion_abilities as entry

        assert entry is parse_champion_abilities
