"""Tests for Syndra champion ability parsing and damage calculation.

Reference damage (raw, pre-mitigation, hand-computed from the wiki).
Anchors use splinters=60 so W's true damage is on but the 120-stack
+15% AP multiplier does not distort the AP the formulas see.
At level 18, rank 5/5/5/3, 600 total AP:
- Q rank 5: 230 + 70% AP = 650 magic; 7s static CD (Q-only R haste folded)
- W rank 5: 190 + 65% AP = 580 magic, plus at 60+ splinters bonus TRUE
  damage = (12% + 2% per 100 AP) x 580 = 0.24 x 580 = 139.2
- E rank 5: 200 + 60% AP = 560 magic, CD 15
- R rank 3: 80/120/160 + 20% AP PER SPHERE = 280 x sphere count
  (840 at the 3 base spheres, 1960 at the 7-sphere cap)
- P at 120 splinters: +15% TOTAL AP applied before all damage parses
  (at 100 AP pre-buff: Q rank 5 = 230 + 0.70 x 115 = 310.5)
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _golden_snapshot():
    """The capture instrument, imported from ``scripts/`` on first use."""
    if str(_REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    return importlib.import_module("golden_snapshot")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_MAXED = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _parse(syndra_data, level=18, ap=600.0, options=None, ranks=None, stats=None):
    """Parse Syndra at a level with explicit AP and champion options."""
    champion_stats = {
        "attack_damage": 100.0,
        "bonus_attack_damage": 0.0,
        "ability_power": ap,
    }
    if stats:
        champion_stats.update(stats)
    return parse_abilities(
        syndra_data,
        level,
        ap,
        ability_ranks=ranks if ranks is not None else dict(ALL_MAXED),
        champion_stats=champion_stats,
        champion_options=options if options is not None else {"splinters": 60},
    )


def _fight(stats, abilities, **overrides):
    """Unmitigated deterministic fight (0 resistances) for exact numbers."""
    config = {
        "target_health": 10000.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 8.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": False,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(stats, abilities, [], FightConfig(**config))


# ---------------------------------------------------------------------------
# Slot coverage and damage types
# ---------------------------------------------------------------------------


class TestSlotMap:
    """Emitted slots track the splinter thresholds."""

    def test_full_splinters_slots(self, syndra_data) -> None:
        """At 120 splinters: passive AP buff row, Q + 2nd charge, W, E, R."""
        abilities = _parse(syndra_data, options={"splinters": 120})
        assert set(abilities) == {"passive", "Q", "Q2", "W", "E", "R"}

    def test_zero_splinters_slots(self, syndra_data) -> None:
        """Below every threshold only the four base casts exist."""
        abilities = _parse(syndra_data, options={"splinters": 0})
        assert set(abilities) == {"Q", "W", "E", "R"}

    @pytest.mark.parametrize("slot", ["Q", "Q2", "E", "R"])
    def test_magic_damage_types(self, syndra_data, slot) -> None:
        abilities = _parse(syndra_data, options={"splinters": 120})
        assert abilities[slot]["damage_type"] == "magic"

    def test_w_is_mixed_at_60_splinters(self, syndra_data) -> None:
        abilities = _parse(syndra_data, options={"splinters": 60})
        assert abilities["W"]["damage_type"] == "mixed"

    def test_w_is_magic_below_60_splinters(self, syndra_data) -> None:
        abilities = _parse(syndra_data, options={"splinters": 59})
        assert abilities["W"]["damage_type"] == "magic"

    def test_cooldowns(self, syndra_data) -> None:
        """W 8s / E 15s / R 80s at max rank; Q's is haste-folded (below)."""
        abilities = _parse(syndra_data)
        assert abilities["W"]["cooldown"] == 8.0
        assert abilities["E"]["cooldown"] == 15.0
        assert abilities["R"]["cooldown"] == 80.0


# ---------------------------------------------------------------------------
# Hand-validated ability damage (wiki anchors, splinters=60, 600 AP)
# ---------------------------------------------------------------------------


class TestAbilityDamage:
    """Raw values match the wiki at rank 5/5/5/3 with 600 AP."""

    def test_q_rank5(self, syndra_data) -> None:
        """Q rank 5: 230 + 70% AP = 650."""
        abilities = _parse(syndra_data)
        assert abilities["Q"]["total_raw"] == pytest.approx(650.0)

    def test_w_rank5_magic_plus_true(self, syndra_data) -> None:
        """W rank 5: 580 magic + (0.12 + 0.0002 x 600) x 580 = 139.2 true."""
        entry = _parse(syndra_data)["W"]
        assert entry["total_raw"] == pytest.approx(580.0 + 139.2)
        magic_part, true_part = entry["parts"]
        assert magic_part.damage_type == "magic"  # Horizon Focus trigger first
        assert magic_part.amount == pytest.approx(580.0)
        assert true_part.damage_type == "true"
        assert true_part.amount == pytest.approx(139.2)

    def test_w_below_threshold_is_base_magic_only(self, syndra_data) -> None:
        entry = _parse(syndra_data, options={"splinters": 0})["W"]
        assert entry["total_raw"] == pytest.approx(580.0)
        assert len(entry["parts"]) == 1

    def test_w_true_damage_is_quadratic_in_ap(self, syndra_data) -> None:
        """At 1000 AP: magic 840; true = (0.12 + 0.20) x 840 = 268.8 —
        the module formula, NOT the JSON's garbled effect[3] rows."""
        entry = _parse(syndra_data, ap=1000.0)["W"]
        assert entry["parts"][1].amount == pytest.approx(268.8)

    def test_e_rank5(self, syndra_data) -> None:
        """E rank 5: 200 + 60% AP = 560."""
        abilities = _parse(syndra_data)
        assert abilities["E"]["total_raw"] == pytest.approx(560.0)

    def test_r_rank3_default_spheres(self, syndra_data) -> None:
        """R rank 3 at 3 spheres: 3 x (160 + 20% AP) = 840."""
        entry = _parse(syndra_data)["R"]
        assert entry["total_raw"] == pytest.approx(840.0)
        (part,) = entry["parts"]
        assert part.amount == pytest.approx(280.0)
        assert part.count == 3


# ---------------------------------------------------------------------------
# Passive: 120-splinter +15% total AP (BUFF phase)
# ---------------------------------------------------------------------------


class TestTranscendentApBuff:
    """The 15% multiplier applies to total AP before all damage parses."""

    def test_buff_row_shape(self, syndra_data) -> None:
        entry = _parse(syndra_data, ap=100.0, options={"splinters": 120})["passive"]
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert entry["stat_buff"] == {"ability_power": pytest.approx(15.0)}

    def test_damage_slots_see_multiplied_ap(self, syndra_data) -> None:
        """At 100 AP pre-buff, Q parses against 115 AP: 230 + 80.5."""
        abilities = _parse(syndra_data, ap=100.0, options={"splinters": 120})
        assert abilities["Q"]["total_raw"] == pytest.approx(310.5)
        assert abilities["E"]["total_raw"] == pytest.approx(260.0 + 9.0)

    def test_w_true_damage_uses_multiplied_ap(self, syndra_data) -> None:
        """Pre-buff 521.7391 AP -> 600 total: W = 580 magic + 139.2 true."""
        entry = _parse(syndra_data, ap=600.0 / 1.15, options={"splinters": 120})["W"]
        assert entry["parts"][0].amount == pytest.approx(580.0)
        assert entry["parts"][1].amount == pytest.approx(139.2)

    def test_no_buff_below_120(self, syndra_data) -> None:
        abilities = _parse(syndra_data, ap=100.0, options={"splinters": 119})
        assert "passive" not in abilities
        assert abilities["Q"]["total_raw"] == pytest.approx(300.0)

    def test_default_options_are_fully_stacked(self, syndra_data) -> None:
        """No options supplied -> splinters defaults to 120 (buff on)."""
        abilities = _parse(syndra_data, ap=100.0, options={})
        assert "passive" in abilities
        assert abilities["Q"]["total_raw"] == pytest.approx(310.5)


# ---------------------------------------------------------------------------
# Q: second charge (40+ splinters) and R's Q-only ability haste
# ---------------------------------------------------------------------------


class TestDarkSphereCharges:
    """40+ splinters adds ONE extra Q cast available at fight open."""

    def test_q2_matches_q_damage(self, syndra_data) -> None:
        abilities = _parse(syndra_data, options={"splinters": 40})
        assert abilities["Q2"]["total_raw"] == pytest.approx(
            abilities["Q"]["total_raw"]
        )
        assert abilities["Q2"]["damage_type"] == "magic"

    def test_q2_is_single_cast(self, syndra_data) -> None:
        """Cooldown 0 = the engine's cast-exactly-once idiom."""
        abilities = _parse(syndra_data, options={"splinters": 40})
        assert abilities["Q2"]["cooldown"] == 0.0

    def test_q2_absent_below_40(self, syndra_data) -> None:
        abilities = _parse(syndra_data, options={"splinters": 39})
        assert "Q2" not in abilities

    def test_the_charge_pays_dark_spheres_own_mana(self, syndra_data) -> None:
        """A stocked charge is a whole cast and is priced like one.

        The wiki grants the charge and says nothing about price: "Collecting
        40 Splinters of Wrath causes Syndra to periodically stock a Dark
        Sphere charge, up to a maximum of 2."  So the charge spends what Q
        spends at Q's rank, read from Q's own cached cost row rather than
        typed here.
        """
        abilities = _parse(syndra_data, options={"splinters": 40})
        q_cost = (syndra_data["abilities"]["Q"][0]["cost"]["modifiers"][0]["values"])[4]
        assert abilities["Q2"]["resource_cost"] == pytest.approx(float(q_cost))
        assert abilities["Q2"]["resource_cost"] == abilities["Q"]["resource_cost"]
        assert abilities["Q2"]["resource_type"] == "MANA"

    @pytest.mark.parametrize("rank, expected", [(1, 40.0), (3, 50.0), (5, 60.0)])
    def test_the_charge_is_priced_at_its_parents_rank(
        self, syndra_data, rank, expected
    ) -> None:
        """Not a fixed number: the charge follows Q's rank down its cost row."""
        abilities = _parse(
            syndra_data,
            options={"splinters": 40},
            ranks={"Q": rank, "W": 5, "E": 5, "R": 3},
        )
        assert abilities["Q2"]["resource_cost"] == pytest.approx(expected)

    def test_the_charge_is_priced_on_the_fights_cast_ledger(
        self, syndra_data, attacker_stats
    ) -> None:
        """The stamp is not decoration — the executed timeline carries it.

        Two Q casts and one charge in an 8 s window, and the ledger prices
        all three at Dark Sphere's cost rather than two of them.
        """
        stats = attacker_stats()
        abilities = parse_abilities(
            syndra_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
            champion_stats=stats,
            champion_options={"splinters": 40},
        )
        timeline = _fight(stats, abilities)["cast_timeline"]
        assert [cast["slot"] for cast in timeline] == ["Q", "Q2", "Q"]
        assert [cast["resource_cost"] for cast in timeline] == [
            abilities["Q"]["resource_cost"]
        ] * 3

    def test_timed_fight_gets_exactly_one_extra_q(
        self, syndra_data, attacker_stats
    ) -> None:
        """8s fight, Q only (7s CD, R unranked): 2 Q casts + 1 Q2 cast."""
        stats = attacker_stats()
        options = {"splinters": 40}
        ranks = {"Q": 5, "W": 0, "E": 0, "R": 0}
        abilities = parse_abilities(
            syndra_data,
            18,
            0.0,
            ability_ranks=ranks,
            champion_stats=stats,
            champion_options=options,
        )
        result = _fight(stats, abilities)
        assert result["breakdown"]["Q"]["casts"] == 2
        assert result["breakdown"]["Q2"]["casts"] == 1
        assert result["breakdown"]["Q2"]["total_damage"] == pytest.approx(230.0)


class TestQOnlyHaste:
    """R's 10/20/30 ability haste applies to Q's cooldown only."""

    def test_q_cd_without_r(self, syndra_data) -> None:
        abilities = _parse(syndra_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 0})
        assert abilities["Q"]["cooldown"] == pytest.approx(7.0)

    def test_q_cd_with_r_rank3_no_item_haste(self, syndra_data) -> None:
        """7 x 100 / (100 + 30) = 5.3846."""
        abilities = _parse(syndra_data)
        assert abilities["Q"]["cooldown"] == pytest.approx(7.0 * 100.0 / 130.0)

    def test_q_cd_folds_against_global_haste(self, syndra_data) -> None:
        """With 70 global AH the emitted base must be 7 x 170/200, so the
        fight engine's own 100/(100+70) lands on 7 x 100/200 = 3.5."""
        abilities = _parse(syndra_data, stats={"ability_haste": 70.0})
        emitted = abilities["Q"]["cooldown"]
        assert emitted == pytest.approx(7.0 * 170.0 / 200.0)
        assert emitted * 100.0 / 170.0 == pytest.approx(3.5)

    def test_other_slots_unaffected_by_r_haste(self, syndra_data) -> None:
        """W/E keep their base cooldowns — the haste is Q-only."""
        abilities = _parse(syndra_data)
        assert abilities["W"]["cooldown"] == 8.0
        assert abilities["E"]["cooldown"] == 15.0


# ---------------------------------------------------------------------------
# R: sphere count option
# ---------------------------------------------------------------------------


class TestUnleashedPowerSpheres:
    """r_spheres multiplies the per-sphere damage, clamped to 3-7."""

    def test_seven_spheres(self, syndra_data) -> None:
        entry = _parse(syndra_data, options={"splinters": 60, "r_spheres": 7})["R"]
        assert entry["total_raw"] == pytest.approx(1960.0)
        assert entry["parts"][0].count == 7

    def test_sphere_count_clamped(self, syndra_data) -> None:
        low = _parse(syndra_data, options={"splinters": 60, "r_spheres": 1})["R"]
        high = _parse(syndra_data, options={"splinters": 60, "r_spheres": 12})["R"]
        assert low["parts"][0].count == 3
        assert high["parts"][0].count == 7

    def test_r_rank1(self, syndra_data) -> None:
        """Rank 1: 3 x (80 + 20% of 600 AP) = 600."""
        entry = _parse(
            syndra_data,
            ranks={"Q": 5, "W": 5, "E": 5, "R": 1},
            options={"splinters": 60},
        )["R"]
        assert entry["total_raw"] == pytest.approx(600.0)


# ---------------------------------------------------------------------------
# Rotation: Q must precede E (the stun consumes a sphere)
# ---------------------------------------------------------------------------


class TestRotationOrder:
    """E's stun exists only by scattering a Dark Sphere, so Q is E's setup —
    the reverse of the generic cc-setup-first ordering.  The hand seed in
    CAST_ORDER_OVERRIDES pinned that order until the module declared it;
    the order is now DERIVED from ``CAST_DEPENDENCIES`` (D-89) and cites
    the wiki revision the declaration was read from, which is the whole
    point of retiring a seed rather than deleting one."""

    def test_cast_order_is_qe_combo(self, syndra_data) -> None:
        from src.calculator.rotation_resolver import (
            CAST_ORDER_OVERRIDES,
            resolve_cast_order,
        )

        abilities = _parse(syndra_data)
        order, rule = resolve_cast_order("Syndra", abilities, champion_data=syndra_data)
        assert order == ["Q", "Q2", "E", "W", "R"]
        assert rule is not None and rule.derived is True
        assert "Syndra" not in CAST_ORDER_OVERRIDES
        assert "sphere" in rule.rationale.lower()
        assert "cc_enabler" in rule.rationale
        assert "wiki.leagueoflegends.com/en-us/Syndra@" in rule.rationale


# ---------------------------------------------------------------------------
# The two cast-order pins — Phase 5 criteria 6 and 11
#
# There is no bespoke Syndra pin fixture.  The parameter set lives once, in
# the ``syndra_derived_order`` / ``syndra_custom_order`` coupled scenarios,
# and the binding totals live once, in the committed
# ``scripts/golden_coupled_baseline.json``.  These classes run the named
# scenarios live and read that file; no number below is typed by hand.
# ---------------------------------------------------------------------------


def _coupled_baseline():
    """The committed coupled baseline — the binding home of the totals."""
    path = _REPO_ROOT / "scripts" / "golden_coupled_baseline.json"
    return json.loads(path.read_text(encoding="utf-8"))["coupled_scenarios"]


def _scenario(name):
    """One named coupled scenario; its request is the one parameter set."""
    for scenario in _golden_snapshot().COUPLED_SCENARIOS:
        if scenario.name == name:
            return scenario
    raise AssertionError(f"coupled scenario {name!r} is missing")


def _capture(name):
    """Run a named scenario live, rounded exactly as the baseline is."""
    snapshot = _golden_snapshot()
    return snapshot._rounded(  # pylint: disable=protected-access
        snapshot.coupled_entry(_scenario(name))
    )


def _casts(entry):
    """One captured fight's cast timeline as ``(time, slot)`` pairs."""
    fight = entry["fights"]["manual_target"]
    return [(cast["time"], cast["slot"]) for cast in fight["cast_timeline"]]


def _without_coverage_prose(value):
    """The same tree with every ``item_coverage`` block removed.

    The utility-outcomes payload carries one coverage record per item — a
    status and a reason, both prose about *why* the model does or does not
    price a mechanic, and neither a number.  Phase 3's 3.8 flip regenerated
    all of them, and the leaves are enumerated in
    ``docs/receipts/expected-golden-diff-3.8-coverage-flip.json``, which is
    where they are pinned.  Dropping them here is the same split ``rotation``
    already gets: this assertion is about what the engine computed.
    """
    if isinstance(value, dict):
        return {
            key: _without_coverage_prose(child)
            for key, child in value.items()
            if key != "item_coverage"
        }
    if isinstance(value, list):
        return [_without_coverage_prose(child) for child in value]
    return value


def _priced(entry):
    """Everything the scenario prices — the entry minus its receipts' prose.

    ``rotation`` is the receipt that says *why* the order is what it is, and
    ``item_coverage`` is the receipt that says why a mechanic is or is not
    priced; every other leaf is what the engine computed.  The prose moves
    when a hand seed retires against a declaration, or when a coverage
    classifier stops reading a hand registry, and no number may: splitting
    them here is what lets one assertion mean "the change moved nothing"
    instead of "the wording is unchanged".  ``cast_order`` and ``order`` live
    inside ``rotation`` and are pinned separately below by the cast timeline,
    which is the executed fact.
    """
    fights = {
        key: {name: value for name, value in fight.items() if name != "rotation"}
        for key, fight in entry["fights"].items()
    }
    # ``dispositions`` is Phase 4 S9's parallel map: one entry per published
    # leaf, saying whether a rule produced that number.  It is a receipt
    # *about* the numbers rather than one of them, and it did not exist when
    # this baseline was captured, so it joins the prose this comparison
    # excludes.  Its own coverage is asserted in
    # ``tests/test_payload_dispositions.py``, two-way, against a live run.
    combat = {
        name: value
        for name, value in entry.get("combat", {}).items()
        if name != "dispositions"
    }
    trimmed = {**entry, "fights": fights}
    if "combat" in entry:
        trimmed["combat"] = combat
    return _without_coverage_prose(trimmed)


_PIN_SPLINTERS = (39, 60, 120)


def _allowlisted_moves():
    """Every coupled leaf a committed R-17 allowlist claims, with its new value.

    R-17 lands a semantic slice against the *old* baseline plus a committed
    allowlist and re-captures at the boundary, so between the two a pin that
    demands byte-equality with the committed entry forbids every correction
    this campaign exists to make.  What must hold in between is the weaker
    pair the allowlist itself states: a leaf outside it did not move, and a
    leaf inside it holds the value its receipt declared.  Once the boundary
    lands the difference set is empty and both clauses hold trivially.
    """
    claimed: set[str] = set()
    declared: dict[str, object] = {}
    receipts = (_REPO_ROOT / "docs" / "receipts").glob("expected-golden-diff-*.json")
    for receipt in sorted(receipts):
        block = json.loads(receipt.read_text(encoding="utf-8"))
        paths = block.get("expected_diff_paths", {})
        for key in ("coupled_golden", "coupled_golden_shape_counters"):
            claimed.update(paths.get(key, ()))
        for path, move in (block.get("moved_values") or {}).items():
            claimed.add(path)
            declared[path] = move.get("new")
    return claimed, declared


def _pin_diffs(name):
    """The live run against the committed entry, through R-15's own instrument."""
    snapshot = _golden_snapshot()
    live = {"coupled_scenarios": {name: _priced(_capture(name))}}
    committed = {"coupled_scenarios": {name: _priced(_coupled_baseline()[name])}}
    return snapshot.leaf_report(committed, live)


def _assert_pinned(name):
    """The scenario reproduces its committed entry, allowlist included."""
    claimed, declared = _allowlisted_moves()
    for diff in _pin_diffs(name):
        assert (
            diff.path in claimed
        ), f"{name} moved {diff.path}, which no receipt claims"
        if diff.path in declared:
            assert diff.new == declared[diff.path], (
                f"{name} moved {diff.path} to {diff.new!r}, where the receipt claiming "
                f"it declares {declared[diff.path]!r}"
            )


class TestTheDerivedOrderPinScenario:
    """Criterion 6 — the 5.0 s Q recast, pinned by the coupled baseline.

    The splinter count is load-bearing: Q's second charge arrives at 40
    stacks and W's bonus true damage at 60, so the same run totals three
    different numbers across the variants and a pin without that axis is
    ambiguous.  Every expectation here is read from the committed
    baseline; the suite retypes nothing.
    """

    @pytest.mark.parametrize("splinters", _PIN_SPLINTERS)
    def test_the_live_run_reproduces_the_committed_entry(self, splinters) -> None:
        _assert_pinned(f"syndra_derived_order_{splinters}")

    @pytest.mark.parametrize("splinters", _PIN_SPLINTERS)
    def test_q_recasts_at_five_seconds(self, splinters) -> None:
        """10 ability haste puts the recast at 5.0 s exactly."""
        casts = _casts(_capture(f"syndra_derived_order_{splinters}"))
        assert (5.0, "Q") in casts

    @pytest.mark.parametrize("splinters", _PIN_SPLINTERS)
    def test_the_second_charge_rides_its_parents_cast_times(self, splinters) -> None:
        """C6's fold: Q2 never occupies a cast slot of its own."""
        casts = _casts(_capture(f"syndra_derived_order_{splinters}"))
        q_times = {time for time, slot in casts if slot == "Q"}
        q2_times = [time for time, slot in casts if slot == "Q2"]
        assert q2_times == ([0.0] if splinters >= 40 else [])
        assert set(q2_times) <= q_times

    @pytest.mark.parametrize("splinters", _PIN_SPLINTERS)
    def test_the_derived_timeline_is_not_the_requested_one(self, splinters) -> None:
        """A pin the fix and a fall-through both satisfy is not a pin."""
        derived = _casts(_capture(f"syndra_derived_order_{splinters}"))
        requested = _casts(_capture(f"syndra_custom_order_{splinters}"))
        assert derived != requested


class TestTheSeedRetirementAllowlistIsCommitted:
    """R-17: the retirement lands against the committed baseline plus a list.

    The seed deletion moves receipt prose and no number, and the list of
    exactly which leaves may move is committed beside the code rather than
    absorbed by re-capturing a baseline inside a semantic commit.
    """

    _PATH = (
        _REPO_ROOT / "docs" / "receipts" / "expected-golden-diff-P5-seed-syndra.json"
    )

    @staticmethod
    def _receipt():
        return json.loads(
            TestTheSeedRetirementAllowlistIsCommitted._PATH.read_text(encoding="utf-8")
        )

    def test_the_pair_baseline_half_is_empty(self) -> None:
        """The retirement's own gate: the pair engine sees no change."""
        receipt = self._receipt()
        assert receipt["slice"] == "P5-seed-syndra"
        assert receipt["decisions"] == ["D-89", "P5-e"]
        assert receipt["expected_diff_paths"]["golden"] == []

    def test_every_allowed_path_is_inside_the_declared_population(self) -> None:
        """An occurrence outside the enumerated population stops the slice."""
        receipt = self._receipt()
        prefixes = tuple(
            receipt["qualifying_population"]["coupled_golden"]["bounded_by_prefix"]
        )
        assert len(prefixes) == 3
        allowed = receipt["expected_diff_paths"]["coupled_golden"]
        assert allowed, "an empty allowlist would make this check vacuous"
        outside = [path for path in allowed if not path.startswith(prefixes)]
        assert outside == []

    def test_the_population_was_enumerated_before_the_first_src_edit(self) -> None:
        population = self._receipt()["qualifying_population"]
        assert population["enumerated_before_first_src_edit"] is True
        assert population["pair_golden"]["measured_qualifying_leaves"] == 0
        assert population["coupled_golden"]["occurrences_outside_the_population"] == 0

    def test_the_positive_control_is_recorded_in_the_fingerprints_receipt(self) -> None:
        """Zero diffs means nothing unless the gate can be made to fail."""
        fingerprints = json.loads(
            (_REPO_ROOT / "docs" / "receipts" / "campaign-fingerprints.json").read_text(
                encoding="utf-8"
            )
        )
        control = fingerprints["demonstrated_red"]["P5_syndra_seed_positive_control"]
        assert control["pair_golden_diff_count"] >= 1
        assert len(control["sha"]) == 40
        assert len(control["output_sha256"]) == 64


class TestTheCustomOrderPinReadsTheBaseline:
    """Criterion 11 — the requested order is whole, and the total is pinned.

    ``tests/test_custom_cast_order.py`` asserts C6's behaviour structurally
    (the recast survives, once).  This class binds the same scenario to the
    committed number, so a change that keeps the shape and moves the damage
    cannot pass both.
    """

    @pytest.mark.parametrize("splinters", _PIN_SPLINTERS)
    def test_the_live_run_reproduces_the_committed_entry(self, splinters) -> None:
        _assert_pinned(f"syndra_custom_order_{splinters}")

    def test_the_requested_order_keeps_the_second_charge(self) -> None:
        entry = _capture("syndra_custom_order_120")
        fight = entry["fights"]["manual_target"]
        assert fight["breakdown"]["Q2"]["casts"] == 1
        committed = _coupled_baseline()["syndra_custom_order_120"]
        assert (
            fight["total_damage"]
            == committed["fights"]["manual_target"]["total_damage"]
        )


# ---------------------------------------------------------------------------
# E: Scatter the Weak's authored stun marker
# ---------------------------------------------------------------------------


class TestScatterTheWeakStun:
    """E carries the authored stun so CC-triggered item passives (Imperial
    Mandate's Command, Bandlepipes' Fanfare) can see it in the event ledger."""

    def test_e_part_carries_stun_marker(self, syndra_data) -> None:
        (part,) = _parse(syndra_data)["E"]["parts"]
        assert part.cc_kind == "stun"

    def test_e_fight_event_carries_stun_marker(
        self, syndra_data, attacker_stats
    ) -> None:
        """The marker must survive the fight engine into damage_events —
        that ledger is what item_support_effects scans for CC triggers."""
        stats = attacker_stats(ability_power=600.0)
        abilities = parse_abilities(
            syndra_data,
            18,
            600.0,
            ability_ranks={"Q": 0, "W": 0, "E": 5, "R": 0},
            champion_stats=stats,
            champion_options={"splinters": 60},
        )
        result = _fight(stats, abilities, one_rotation=True)
        e_events = [
            event
            for event in result["damage_events"]
            if event.get("source") == "E" or event.get("source_key") == "E"
        ]
        assert e_events
        assert all(event.get("cc_kind") == "stun" for event in e_events)

    def test_imperial_mandate_command_amps_post_stun_damage(
        self, syndra_data, attacker_stats
    ) -> None:
        """E stuns at t=0, R lands at t=0.25 inside Command's 4s window:
        7% of R's 840 = 58.8 bonus. E itself (the trigger) is not amped."""
        from src.calculator.data_fetcher import get_item_by_name

        items = [get_item_by_name("Imperial Mandate")]
        stats = attacker_stats(ability_power=600.0)
        abilities = parse_abilities(
            syndra_data,
            18,
            600.0,
            ability_ranks={"Q": 0, "W": 0, "E": 5, "R": 3},
            champion_stats=stats,
            champion_options={"splinters": 60},
        )
        result = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=10000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=8.0,
                auto_attack_uptime=0.0,
                one_rotation=False,
                deterministic=True,
            ),
        )
        row = result["breakdown"]["damage_amp_Imperial Mandate"]
        assert row["multiplier"] == pytest.approx(1.07)
        assert row["total_damage"] == pytest.approx(0.07 * 840.0)
        assert result["total_damage"] == pytest.approx(560.0 + 840.0 * 1.07)


# ---------------------------------------------------------------------------
# Fight-engine integration
# ---------------------------------------------------------------------------


class TestFightIntegration:
    """Mitigation semantics: W's bonus is TRUE damage, the base is magic."""

    def test_w_true_part_ignores_mr(self, syndra_data, attacker_stats) -> None:
        """100 MR halves W's magic 580 but not the 139.2 true bonus."""
        stats = attacker_stats(ability_power=600.0)
        abilities = parse_abilities(
            syndra_data,
            18,
            600.0,
            ability_ranks={"Q": 0, "W": 5, "E": 0, "R": 0},
            champion_stats=stats,
            champion_options={"splinters": 60},
        )
        result = _fight(
            stats,
            abilities,
            target_magic_resistance=100.0,
            one_rotation=True,
            fight_duration_seconds=5.0,
        )
        row = result["breakdown"]["W"]
        assert row["total_damage"] == pytest.approx(580.0 / 2.0 + 139.2)
        assert row["damage_by_type"]["magic"] == pytest.approx(290.0)
        assert row["damage_by_type"]["true"] == pytest.approx(139.2)

    def test_r_spheres_mitigated_per_hit(self, syndra_data, attacker_stats) -> None:
        """7 spheres into 100 MR: 1960 / 2 (flat magic per sphere)."""
        stats = attacker_stats(ability_power=600.0)
        abilities = parse_abilities(
            syndra_data,
            18,
            600.0,
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 3},
            champion_stats=stats,
            champion_options={"splinters": 60, "r_spheres": 7},
        )
        result = _fight(
            stats,
            abilities,
            target_magic_resistance=100.0,
            one_rotation=True,
            fight_duration_seconds=5.0,
        )
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(980.0)


# ---------------------------------------------------------------------------
# Command window arithmetic (the declared TriggerWindow)
# ---------------------------------------------------------------------------


def _command_slot():
    """Command's declared chain slot, resolved for a Mandate holder.

    The window arithmetic used to be two module helpers in ``damage.py``
    taking a duration nobody sourced at the call site; Phase 3 moved both
    into the rule's ``TriggerWindow(IMMOBILIZE, merge=EXTEND,
    boundary=OPEN_CLOSED)`` and its interpreter.  These tests follow, so
    they keep pinning the behaviour rather than a deleted spelling.
    """
    from src.calculator.interpreters import delta_amp
    from src.calculator.item_behavior import AmpChainSlot

    slot = delta_amp.resolve_slot(
        ["Imperial Mandate"],
        AmpChainSlot.POST_IMMOBILIZE,
        level=18,
        fight_duration_seconds=10.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    assert slot is not None
    return slot


class TestCommandWindows:
    """The two pieces of _apply_command_amp most exposed to refactor drift:
    window merging (extend, not stack) and the strictly-after boundary."""

    def test_overlapping_immobilizes_extend_one_window(self) -> None:
        from src.calculator.interpreters import delta_amp

        slot = _command_slot()
        duration = slot.value(delta_amp.WINDOW_DURATION_FIELD)
        assert slot.trigger_windows([0.0, duration / 2.0]) == (
            (0.0, duration / 2.0 + duration),
        )

    def test_separated_immobilizes_open_separate_windows(self) -> None:
        from src.calculator.interpreters import delta_amp

        slot = _command_slot()
        duration = slot.value(delta_amp.WINDOW_DURATION_FIELD)
        far = duration * 2.5
        assert slot.trigger_windows([0.0, far]) == (
            (0.0, duration),
            (far, far + duration),
        )

    def test_boundary_is_strictly_after_start_inclusive_end(self) -> None:
        from src.calculator.interpreters import delta_amp

        slot = _command_slot()
        duration = slot.value(delta_amp.WINDOW_DURATION_FIELD)
        windows = slot.trigger_windows([1.0])
        assert not slot.window_holds(windows, 1.0)  # the trigger itself
        assert slot.window_holds(windows, 1.001)
        assert slot.window_holds(windows, 1.0 + duration)  # inclusive end
        assert not slot.window_holds(windows, 1.0 + duration + 0.001)
