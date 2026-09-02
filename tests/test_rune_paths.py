"""The rune-path vocabulary: how a path registers what it compiles.

``rune_effects`` is the public surface; the compilers live one module per
path under ``rune_paths``, plus ``shards`` for the three stat-shard rows.
This file pins the registration contract every path module answers to, and
the four exemplars that prove the three shapes a minor rune can take: a stat
grant, a conditional damage amplifier, a proc, and a compiled refusal.
"""

import dataclasses

import pytest

from src.calculator import item_behavior_catalog, rune_effects, rune_paths
from src.calculator.item_behavior import (
    AmpChainSlot,
    Comparison,
    Probe,
    chain_rank,
)
from src.calculator.item_behavior_catalog import BehaviorCatalogError, behavior_rules
from src.calculator.rune_paths import (
    domination,
    inspiration,
    precision,
    resolve,
    shards,
    sorcery,
)
from src.calculator.value_ref import resolve as resolve_ref

PATH_MODULES = (precision, domination, sorcery, resolve, inspiration)


class TestTheRegistrationContract:
    def test_every_path_module_declares_compilers_and_options(self):
        for module in PATH_MODULES:
            assert isinstance(module.COMPILERS, dict), module.__name__
            assert isinstance(module.OPTIONS, dict), module.__name__

    def test_the_five_paths_are_the_roster_s_five(self):
        cached = {entry["path"] for entry in rune_effects.RUNE_EFFECTS.values()}
        declared = {module.__name__.rsplit(".", 1)[-1] for module in PATH_MODULES}
        assert declared == {name.lower() for name in cached}

    def test_every_declared_rune_is_a_minor_rune_of_its_own_path(self):
        for module in PATH_MODULES:
            path = module.__name__.rsplit(".", 1)[-1]
            for name in module.COMPILERS:
                entry = rune_effects.RUNE_EFFECTS[name]
                assert entry["path"].lower() == path, name
                assert entry["row"] > 0, name

    def test_every_option_belongs_to_a_rune_that_module_compiles(self):
        for module in PATH_MODULES:
            assert set(module.OPTIONS) <= set(module.COMPILERS), module.__name__

    def test_the_merged_vocabulary_is_the_keystones_plus_the_paths(self):
        merged = set(rune_effects._compilers())
        paths = set(rune_paths.path_compilers())
        assert merged == set(rune_paths.keystone_compilers()) | paths
        # Every compiled name is a roster rune; the roster's completeness is
        # the catalog's ``implemented`` flag, pinned by the rune-page tests.
        assert merged <= set(rune_effects.RUNE_EFFECTS)

    def test_two_paths_claiming_one_rune_fails_loud(self, monkeypatch):
        """A rune belongs to one path; two compilers is a declaration bug."""
        monkeypatch.setitem(domination.COMPILERS, "Scorch", sorcery.COMPILERS["Scorch"])
        with pytest.raises(ValueError, match="compiled by both"):
            rune_paths.path_compilers()

    def test_a_shard_registers_under_its_row_and_name(self):
        """Nine options over three rows; the row is half of the key."""
        assert rune_paths.shard_compilers() == dict(shards.COMPILERS)
        assert sorted(shards.COMPILERS) == [
            (1, "Adaptive Force"),
            (1, "Attack Speed"),
            (1, "Cooldown Reduction"),
            (2, "Adaptive Force"),
            (2, "Health Scaling"),
            (2, "Movement Speed"),
            (3, "Health"),
            (3, "Health Scaling"),
            (3, "Tenacity and Slow Resist"),
        ]


class TestCoupDeGrace:
    """Precision row 3: the marker for an amp the chain declares.

    Its gate and its ratio live in the ``TARGET_HEALTH_GATE`` chain slot, so
    what the path compiles is the rune's identity — which is what tells the
    engine a page slot is asking for a chain slot.
    """

    def test_it_compiles_to_the_marker_the_chain_slot_is_keyed_by(self):
        effect = rune_effects.resolve_rune("Coup de Grace")
        assert isinstance(effect, rune_effects.RuneConditionalAmpEffect)
        assert effect.breakdown_key == "rune_Coup de Grace"
        assert effect.display_name == "Coup de Grace (rune)"

    def test_its_numbers_are_the_chain_declarations_and_not_the_effects(self):
        (rule,) = behavior_rules("Coup de Grace")
        assert rule.payload.lane_chain_rank == chain_rank(
            AmpChainSlot.TARGET_HEALTH_GATE
        )
        assert rule.payload.activation.probe is Probe.TARGET_HEALTH_FRACTION
        assert rule.payload.activation.cmp is Comparison.LT
        assert resolve_ref(rule.payload.activation.threshold) == pytest.approx(0.40)
        assert resolve_ref(rule.payload.magnitude.value) == pytest.approx(0.08)
        assert not [
            field
            for field in dataclasses.fields(rune_effects.RuneConditionalAmpEffect)
            if "ratio" in field.name or field.name == "condition"
        ], "the gate and the ratio have one home, and it is the declaration"

    def test_a_reordered_description_fails_closed(self, monkeypatch):
        """An unknown gate spelling is refused, never priced as one we know."""
        monkeypatch.setitem(
            rune_effects.RUNE_EFFECTS["Coup de Grace"]["effects"],
            "damage_amp_health_gate",
            "target_sideways",
        )
        with pytest.raises(BehaviorCatalogError, match="not one of"):
            item_behavior_catalog._target_health_gate_rule(
                "Coup de Grace", "RUNE_EFFECTS"
            )

    def test_a_description_naming_the_other_side_fails_closed(self, monkeypatch):
        """The two sources are checked against each other, neither one wins."""
        monkeypatch.setitem(
            rune_effects.RUNE_EFFECTS["Coup de Grace"]["effects"],
            "damage_amp_health_gate",
            "target_above",
        )
        with pytest.raises(BehaviorCatalogError, match="description reordered"):
            item_behavior_catalog._target_health_gate_rule(
                "Coup de Grace", "RUNE_EFFECTS"
            )


class TestAbsoluteFocus:
    """Sorcery row 2: a leveled adaptive stat grant behind a health gate."""

    def test_it_grants_the_level_table_the_cache_states(self):
        effect = rune_effects.resolve_rune("Absolute Focus")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is rune_effects.RuneStat.ADAPTIVE_FORCE
        assert effect.amount(_context(level=18)) == pytest.approx(30.0)
        assert effect.amount(_context(level=1)) == pytest.approx(3.0)

    def test_the_gate_is_an_option_with_a_disclosed_default(self):
        effect = rune_effects.resolve_rune("Absolute Focus")
        off = _context(
            level=18, options={"Absolute Focus": {"above_health_threshold": 0}}
        )
        assert effect.amount(off) == 0.0
        assert "70% of maximum health" in effect.disclosures[0]
        assert "above_health_threshold" in effect.disclosures[0]

    def test_the_declared_option_is_bounded(self):
        option = sorcery.OPTIONS["Absolute Focus"][0]
        assert option.key == "above_health_threshold"
        assert option.default == 1.0
        assert option.bounds == (0.0, 1.0)
        with pytest.raises(ValueError, match="between 0 and 1"):
            option.validated(2)
        with pytest.raises(ValueError, match="must be a number"):
            option.validated("yes")

    def test_adaptive_force_takes_the_larger_bonus_and_ties_take_attack_damage(self):
        """30 force is 18 bonus AD (0.6 each) or 30 AP, per Template:Adaptive."""
        assert rune_effects.adaptive_force_attack_damage_ratio() == pytest.approx(0.6)
        effect = rune_effects.resolve_rune("Absolute Focus")
        ap_build = _context(level=18, ability_power=200.0, bonus_attack_damage=10.0)
        assert rune_effects.resolve_stat_grants([effect], ap_build).ability_power == (
            pytest.approx(30.0)
        )
        ad_build = _context(level=18, ability_power=10.0, bonus_attack_damage=200.0)
        grants = rune_effects.resolve_stat_grants([effect], ad_build)
        assert grants.bonus_attack_damage == pytest.approx(18.0)
        assert grants.ability_power == 0.0
        tie = _context(level=18)
        assert rune_effects.resolve_stat_grants([effect], tie).bonus_attack_damage == (
            pytest.approx(18.0)
        )


class TestScorch:
    """Sorcery row 3: an ability-triggered proc on a flat cooldown."""

    def test_it_compiles_to_the_cache_s_table_cooldown_and_delay(self):
        effect = rune_effects.resolve_rune("Scorch")
        assert isinstance(effect, rune_effects.RuneProcEffect)
        assert effect.trigger is rune_effects.RuneTrigger.DAMAGING_CASTS
        assert effect.cooldown_seconds == pytest.approx(10.0)
        assert effect.proc_delay_seconds == pytest.approx(1.0)
        assert effect.stacks_required == 1
        assert effect.damage_type({}) == "magic"
        assert effect.raw_damage(_inputs(level=18)) == pytest.approx(40.0)
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(20.0)


class TestCosmicInsight:
    """Inspiration row 3: compiled, selectable, and refused with a reason."""

    def test_its_haste_is_withheld_because_the_engine_reads_neither_kind(self):
        effect = rune_effects.resolve_rune("Cosmic Insight")
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert effect.zero_policy.disposition.name == "WITHHELD"
        assert "summoner-spell haste and item haste" in effect.zero_policy.reason
        assert "summoner spells are outside the damage model" in (
            effect.zero_policy.reason
        )
        assert any("no ability haste" in receipt for receipt in effect.receipts)


def _context(*, level, ability_power=0.0, bonus_attack_damage=0.0, options=None):
    return rune_effects.RuneStatContext(
        level=level,
        is_melee=False,
        bonus_attack_damage=bonus_attack_damage,
        ability_power=ability_power,
        options=options or {},
    )


def _inputs(*, level):
    from src.calculator.item_effects import DamageInputs

    return DamageInputs(
        champion_stats={"bonus_attack_damage": 0.0, "ability_power": 0.0},
        level=level,
        is_melee=False,
        target_max_health=1000.0,
        target_current_health=1000.0,
    )
