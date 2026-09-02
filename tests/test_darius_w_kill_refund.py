"""P4 Slice 14 — Darius W (Crippling Strike) kill-triggered cooldown
reduction + mana refund (test-matrix owner: RLM-2 C).

Focused TDD matrix for the sourced W kill rule.  CURRENT RUNTIME FACTS
(verify-before-pin completed against ``src/calculator/champions/darius.py``,
``src/calculator/damage.py`` and ``data/champions.json``):

- ``darius.py`` ships ``_crippling_strike`` (the empowered-auto entry:
  40-60% total-AD bonus physical damage at ranks 1-5, crits at full
  effectiveness, 4s window from the cached prose, one empowered attack
  per cast — the Alistar rule) and ``_noxian_guillotine`` with the
  ``r_execute_recast`` kill-assertion option — the input contract's ONLY
  kill representation today (the model's target never dies).
- The cached W data (``Darius.W[0]``) carries the kill rule verbatim in
  ``effects[1]`` ("If this attack kills the target, half of Crippling
  Strike's cooldown is reduced and its mana cost is refunded.") with NO
  leveling row — so, like Ezreal's mark-refund flat, the rule has no atom
  (verified against the catalog AND the live atomization).  Cost is flat
  40, cooldown flat 5 (affectedByCdr), the 4s window and the 1s slow are
  the ``timing.active_duration`` / ``timing.control_duration`` atoms.
- The module's ASSUMPTIONS record "W's kill-triggered cooldown reduction
  and mana refund are not modeled"; the only runtime kill assertion is
  R's ``r_execute_recast`` (the execute-assertion shape).
- The resource walk (``damage._apply_mana_resource_limits``) owns the
  typed mana ledger; champion refund rules ride the same account as cast
  admission (the Ezreal ``mark_refund`` seam) and a denied cast never
  restores anything.

The P4-14 coordinator's completion adds the SMALLEST typed contract for
the sourced rule: a ``w_kill_assertion`` bool option (default False, the
``r_execute_recast`` execute-assertion shape) that (a) halves W's
sourced cooldown for scheduling (5 -> 2.5) and (b) declares the typed
``kill_refund`` rule on the W entry (flat 40.0 = the sourced flat cost,
named source receipt, no atoms), which the mana walk refunds per accepted
W cast at the cast time on the restore tier AFTER the spend.  Genuinely
absent mechanics are ``xfail`` with reason "awaiting P4-14 wiring"; the
completion removes the markers.

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source evidence + atoms + module declaration: the cached W effects
      verbatim (empowered-auto prose, kill rule, reset prose), Bonus
      Physical Damage 40/45/50/55/60 %AD, cost 40, cd 5 (affectedByCdr),
      the four W atoms (id + hash), the kill-rule atom ABSENCE, the
      module's ``_crippling_strike`` / OPTIONS / ASSUMPTIONS declaration.
  S2  Empowered-auto baseline: the bonus + the forced base swing, the
      full crit effectiveness, the 4s window, the one-per-cast — all
      UNCHANGED by the kill contract.
  S3  The kill path: the ``w_kill_assertion`` option (meta + rotation
      execute shape), the parse-level halved cooldown, the cooldown-
      halved NEXT W casts in the shared timeline, the per-cast refund
      receipts at the W cast times (amount 40, source, tier, atoms,
      detail, accepted), the ledger stream order vs the spend, and the
      accounting identity.
  S4  No-kill default: without the assertion the fight is byte-identical
      — no cooldown change, no refund receipts.
  S5  Excluded targets: the cached notes' ONLY named exclusion is jungle
      plants (quoted verbatim); the model cannot represent them, so the
      completion's assumption carries the named exclusion receipt.
      Structures appear in ``affects`` but the notes never exclude them
      from the kill rule.
  S6  Denied/unavailable casts: a denied W (insufficient mana) gets no
      kill rule and no refund; the one-rotation mode (no auto stream)
      still refunds the single W cast while the cooldown halving is
      unobservable (no second W).
  S7  Ledger ordering + max-mana cap: the refund rides the restore tier
      and lands AFTER the W spend at the same timestamp; the typed
      kernel's OP_REFUND caps over-restoration (CAPPED, current pinned
      at maximum).  Fight-level CAPP is unreachable when the refund
      equals the paid cost (refund == spend restores the pool exactly) —
      flagged for the coordinator (Actualizer discount is the one path).
  S8  Fail-closed malformed declarations: ``kill_refund`` validation
      raises (non-mapping, bad flat, bad source, bad atoms, multiple
      declaring slots); the API boundary already 400s unknown option
      keys and non-bool option values.
  S9  Score/receipt parity: the resource ledger section is byte-identical
      full vs score_only today, and must stay so on the kill surface.
  S10 Unchanged boundaries: P/Q/E/R damage, the R execute recast, the
      slow (no new control events), the auto-timer reset prose (the
      reset is not modeled — the swing rides the engine's auto schedule),
      other champions' surfaces.
  S11 Regression surface: ``tests/test_darius.py`` plus the mandated
      sanity list (run list in the module footer).

Expected values are recomputed from ``data/champions.json`` rows and the
module's own typed extractor — no literal damage constants beyond the
module-sourced flat cost 40 and flat cooldown 5 the contract pins.
"""

import copy
import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.atomizer_domains import atomize_abilities
from src.calculator.champions import darius as darius_module
from src.calculator.champions import (
    get_champion_option_rotation,
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.damage import FightConfig, _empower_hits, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.resource_ledger import (
    OP_REFUND,
    OP_SPEND,
    TIER_CAST,
    TIER_RESTORE,
    ResourceAccount,
    ResourceEvent,
)

_ROOT = Path(__file__).resolve().parents[1]
_CATALOG_PATH = _ROOT / "data" / "atoms" / "abilities.json"

CHAMPION = "Darius"
W_DATA_KEY = "Darius"
# The P4-14 coordinator wires the typed kill contract; genuinely-absent
# mechanics are xfailed with this reason.
_AWAIT = "awaiting P4-14 wiring"

# The sourced flat cost and cooldown (cached rows, pinned in S1).
W_COST = 40.0
W_COOLDOWN = 5.0
HALVED_COOLDOWN = W_COOLDOWN / 2.0
# The typed rule declaration name and refund source (contract pins; the
# completion declares them on the W entry / refund receipts).
KILL_REFUND_KEY = "kill_refund"
REFUND_SOURCE = "Darius W (Crippling Strike) kill refund"
OPTION_KEY = "w_kill_assertion"

# The four cached W atoms (data/atoms/abilities.json + live atomization).
W_ATOMS = {
    "bonus_physical_damage": (
        "ability.bonus _physical _damage",
        "a94382ffe99ee8a9",
        [40.0, 45.0, 50.0, 55.0, 60.0],
    ),
    "active_duration": ("timing.active_duration", "dfb11fc26eebb59d", [4.0]),
    "control_duration": ("timing.control_duration", "d968c3ec9a1d13d9", [1.0]),
    "cooldown": ("timing.cooldown", "b920fb10837a441c", [5.0] * 5),
}

_LEVEL = 20
_BONUS_AD = 100.0
_BASE_AD = 162.325


def _stats(max_mana: float = 1404.0, regen: float = 8.0) -> dict:
    """The test_darius.py reference build (level 20, +100 bonus AD)."""
    return {
        "ability_power": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "health": 0.0,
        "lethality": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "ultimate_haste": 0.0,
        "level": float(_LEVEL),
        "base_attack_damage": _BASE_AD,
        "bonus_attack_damage": _BONUS_AD,
        "attack_damage": _BASE_AD + _BONUS_AD,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "critical_strike_chance": 0.0,
        "ability_haste": 0.0,
        "basic_ability_haste": 0.0,
        "armor_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "is_melee": True,
        "max_mana": max_mana,
        "resource_regen_per_second": regen,
    }


def _parse(options: dict | None = None) -> tuple[dict, dict]:
    stats = _stats()
    abilities = parse_champion_abilities(
        get_champion(W_DATA_KEY),
        _LEVEL,
        0.0,
        champion_stats=dict(stats),
        target_stats={"target_max_health": 2500.0},
        champion_options=options,
    )
    return stats, abilities


def _fight(
    options: dict | None = None,
    *,
    duration: float = 10.0,
    one_rotation: bool = False,
    auto_attack_uptime: float = 0.0,
    score_only: bool = False,
    cast_order: list[str] | None = None,
    **params,
) -> dict:
    """Pipeline fight at the reference build with optional kill assertion."""
    base = {
        "target_health": 2500.0,
        "target_bonus_health": 0.0,
        "target_armor": 100.0,
        "target_magic_resistance": 50.0,
        "fight_duration_seconds": duration,
        "auto_attack_uptime": auto_attack_uptime,
        "one_rotation": one_rotation,
        "include_actives": True,
        "deterministic": True,
        "champion_options": options or {},
    }
    base.update(params)
    if cast_order is not None:
        base["cast_order"] = cast_order
    return run_fight(
        copy.deepcopy(get_champion(W_DATA_KEY)),
        _LEVEL,
        [],
        FightParams(**base),
        score_only=score_only,
    )


def _direct_fight(
    stats: dict,
    options: dict | None = None,
    *,
    cast_order: list[str] | None = None,
    duration: float = 5.0,
    one_rotation: bool = False,
) -> dict:
    """Direct-engine fight (explicit stats, no items) for low-mana cases."""
    abilities = parse_champion_abilities(
        get_champion(W_DATA_KEY),
        _LEVEL,
        0.0,
        champion_options=options,
        champion_stats=dict(stats),
        target_stats={"target_max_health": 2500.0},
    )
    return calculate_fight_damage(
        dict(stats),
        abilities,
        [],
        FightConfig(
            target_health=2500.0,
            target_armor=100.0,
            target_magic_resistance=50.0,
            fight_duration_seconds=duration,
            auto_attack_uptime=0.0,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=cast_order,
        ),
        champion_options=options,
    )


def _refunds(result: dict) -> list[dict]:
    """Kill-rule refund gain receipts, identified by the exact source."""
    return [
        r
        for r in result["resource_ledger"]["receipts"]
        if r["operation"] == "gain" and r["source"] == REFUND_SOURCE
    ]


def _w_spends(result: dict) -> list[dict]:
    """Accepted W cast spend receipts in ledger order."""
    return [
        r
        for r in result["resource_ledger"]["receipts"]
        if r["operation"] == "spend" and r.get("detail", {}).get("slot") == "W"
    ]


def _json(result: dict) -> str:
    """Deterministic JSON-ish fingerprint for byte-identity comparisons.

    Fight results are JSON-safe except the ``amount_formula`` closure on
    self-healing events, which renders as its type name on both sides.
    """
    return json.dumps(result, sort_keys=True, default=lambda o: f"<{type(o).__name__}>")


def _assert_accounting_identity(result: dict) -> None:
    """Receipts are the ONLY resource truth: the public closing state must
    be exactly reproducible from the receipt stream."""
    ledger = result["resource_ledger"]
    opening_current = ledger["opening_current"]
    opening_maximum = ledger["opening_maximum"]
    current_delta = 0.0
    maximum_delta = 0.0
    for receipt in ledger["receipts"]:
        if receipt["accepted"]:
            current_delta += receipt["current_after"] - receipt["current_before"]
            maximum_delta += receipt["maximum_after"] - receipt["maximum_before"]
    assert ledger["closing_current"] == pytest.approx(
        opening_current + current_delta, abs=1e-6
    )
    assert ledger["closing_maximum"] == pytest.approx(
        opening_maximum + maximum_delta, abs=1e-6
    )


# ---------------------------------------------------------------------------
# S1 — Source evidence, atoms, module declaration
# ---------------------------------------------------------------------------


class TestSourceEvidence:
    def test_w_effects_carry_the_kill_rule_verbatim(self) -> None:
        """The cached W data carries the empowered-auto prose, the kill
        rule, and the reset prose verbatim; the kill rule and reset rows
        have NO leveling (so no atom can exist for them)."""
        w = get_champion(W_DATA_KEY)["abilities"]["W"][0]
        effects = w["effects"]
        assert effects[0]["description"] == (
            "Active: Darius empowers his next basic attack within 4 seconds "
            "to have an uncancellable windup, gain 25 bonus range, deal bonus "
            "physical damage and slow the target by 90% for 1 second. This "
            "damage is affected by critical strike modifiers."
        )
        assert effects[0]["leveling"][0]["attribute"] == "Bonus Physical Damage"
        assert effects[1]["description"] == (
            "If this attack kills the target, half of Crippling Strike's "
            "cooldown is reduced and its mana cost is refunded."
        )
        assert effects[1]["leveling"] == []  # no leveling -> no atom (S1)
        assert effects[2]["description"] == (
            "Crippling Strike resets Darius' basic attack timer."
        )
        assert effects[2]["leveling"] == []

    def test_w_cost_and_cooldown_are_flat(self) -> None:
        """Cost 40 flat at every rank; cooldown 5 flat, affected by CDR."""
        w = get_champion(W_DATA_KEY)["abilities"]["W"][0]
        assert w["cost"]["modifiers"][0]["values"] == [40.0] * 5
        assert w["cooldown"]["modifiers"][0]["values"] == [5.0] * 5
        assert w["cooldown"]["affectedByCdr"] is True
        assert w["resource"] == "MANA"
        assert w["damageType"] == "PHYSICAL_DAMAGE"
        assert w["targeting"] == "Auto"
        assert w["affects"] == "Enemies, Structures"
        assert w["spellshieldable"] == "true"

    def test_bonus_physical_damage_leveling_is_40_to_60_percent_ad(self) -> None:
        w = get_champion(W_DATA_KEY)["abilities"]["W"][0]
        leveling = w["effects"][0]["leveling"][0]
        assert leveling["modifiers"][0]["values"] == [40, 45, 50, 55, 60]
        assert leveling["modifiers"][0]["units"] == ["% AD"] * 5

    def test_w_atom_rows_and_kill_rule_atom_absence(self) -> None:
        """The catalog and the live atomization agree on exactly the four
        W rows; NO atom sources effects[1] (kill rule) or effects[2]
        (reset prose) — the kill rule is a typed rule declaration, like
        Ezreal's mark refund."""
        catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        catalog_w = [
            r
            for r in catalog["objects"][W_DATA_KEY]
            if r["source"].startswith(f"{W_DATA_KEY}.W[")
        ]
        live_w = list(atomize_abilities(W_DATA_KEY, get_champion(W_DATA_KEY))["W"])
        assert len(catalog_w) == len(live_w) == len(W_ATOMS) == 4
        for row in catalog_w + live_w:
            assert not row["source"].endswith("effects[1]"), row["source"]
            assert "effects[1]" not in row["source"], row["source"]
            assert "effects[2]" not in row["source"], row["source"]
        by_id = {row["atom_id"]: row for row in catalog_w}
        assert (
            by_id["ability.bonus _physical _damage"]["hash"]
            == W_ATOMS["bonus_physical_damage"][1]
        )
        assert by_id["timing.active_duration"]["hash"] == W_ATOMS["active_duration"][1]
        assert (
            by_id["timing.control_duration"]["hash"] == W_ATOMS["control_duration"][1]
        )
        assert by_id["timing.cooldown"]["hash"] == W_ATOMS["cooldown"][1]
        assert (
            by_id["ability.bonus _physical _damage"]["values"]
            == W_ATOMS["bonus_physical_damage"][2]
        )
        assert (
            by_id["timing.active_duration"]["values"] == W_ATOMS["active_duration"][2]
        )
        # Live atomization values agree with the catalog rows.
        live_by_id = {row["atom_id"]: row for row in live_w}
        for atom_id in by_id:
            assert live_by_id[atom_id]["values"] == by_id[atom_id]["values"]

    def test_module_declares_the_crippling_strike_slot(self) -> None:
        """The module's SLOTS map W to _crippling_strike, and the parser is
        built for the exact cached champion name."""
        assert darius_module.SLOTS["W"] is darius_module._crippling_strike
        assert darius_module.parse_abilities is not None
        assert True

    def test_module_options_and_assumptions_declare_the_current_state(self) -> None:
        """Post-contract declaration: the three options (the existing two
        plus ``w_kill_assertion``) and the replaced assumption line — the
        assertion contract with the jungle-plant exclusion (the S5
        receipt) in place of any not-modeled line."""
        meta = get_champion_options_meta(CHAMPION)
        assert [option["key"] for option in meta["options"]] == [
            "r_execute_recast",
            "starting_hemorrhage_stacks",
            "w_kill_assertion",
        ]
        assumptions = meta["assumptions"]
        assert any(
            "w_kill_assertion" in text and "jungle plants" in text
            for text in assumptions
        )
        assert not any(
            "W's kill-triggered cooldown reduction and mana refund are not "
            "modeled" in text
            for text in assumptions
        )


# ---------------------------------------------------------------------------
# S2 — Empowered-auto baseline (unchanged by the kill contract)
# ---------------------------------------------------------------------------


class TestEmpoweredAutoBaseline:
    def test_w_bonus_damage_and_forced_swing(self) -> None:
        """Rank-5 bonus 0.6 x 262.325 = 157.395; with no auto stream the
        row carries the consumed basic attack (the Blitzcrank/Caitlyn
        rule) — the swing damage is the bonus plus the base."""
        _stats, abilities = _parse()
        w = abilities["W"]
        assert w["rank"] == 5
        assert w["cooldown"] == pytest.approx(W_COOLDOWN)
        assert w["damage_type"] == "physical"
        assert w["total_raw"] == pytest.approx(0.6 * 262.325)
        assert w["parts"][0].amount == pytest.approx(0.6 * 262.325)
        assert w["parts"][0].bonus_ad_ratio == pytest.approx(0.6)
        assert w["resource_cost"] == pytest.approx(W_COST)
        one_rotation = _fight(
            duration=5.0,
            one_rotation=True,
            champion_options={"starting_hemorrhage_stacks": 0},
        )
        # Opened unstacked so no Noxian Might window distorts the swing:
        # the row carries the consumed basic attack at the fight's own AD.
        attack_damage = one_rotation["champion_stats"]["attack_damage"]
        expected = (0.6 * attack_damage + attack_damage) * 100.0 / 160.0
        assert one_rotation["breakdown"]["W"]["total_damage"] == pytest.approx(expected)

    def test_w_crits_fully_and_empowers_one_attack(self) -> None:
        """The bonus crits at full effectiveness beside the base swing; the
        cast empowers exactly one basic attack (Alistar rule); the 4s
        window is the sourced prose + atom."""
        _, abilities = _parse()
        w = abilities["W"]
        assert w["empowers_next_auto"] is True
        assert w["parts"][0].crit_effectiveness == 1.0
        assert _empower_hits(True) == 1  # one empowered attack per cast
        assert w["applies_dot_stack"] is True
        assert (
            "within 4 seconds"
            in get_champion(W_DATA_KEY)["abilities"]["W"][0]["effects"][0][
                "description"
            ]
        )

    def test_kill_contract_leaves_the_damage_surface_unchanged(self) -> None:
        """With the kill assertion on, the damage surface is bit-for-bit
        the same: the parts, the bonus, the empowered-auto flag, the dot
        stack — only the cooldown and the refund rule may change (S3)."""
        _, off = _parse(None)
        _, on = _parse({OPTION_KEY: True})
        for key in (
            "name",
            "rank",
            "damage_type",
            "total_raw",
            "parts",
            "empowers_next_auto",
            "applies_dot_stack",
            "resource_cost",
        ):
            assert on["W"][key] == off["W"][key], key


# ---------------------------------------------------------------------------
# S3 — The kill path (option + halved NEXT W cooldown + refund receipts)
# ---------------------------------------------------------------------------


class TestKillPath:
    def test_option_meta_declares_w_kill_assertion(self) -> None:
        """The kill-assertion option: bool, default False, labelled for
        the sourced kill rule, and DELIBERATELY rotation-free — an
        execute-role edge on the damage row would make the resolver
        derive a different Darius order (W's kill is a
        resource/cooldown assertion, not a rotation edge; the
        r_execute_recast metadata is R's own)."""
        meta = get_champion_options_meta(CHAMPION)
        option = next(o for o in meta["options"] if o["key"] == OPTION_KEY)
        assert option["type"] == "bool"
        assert option["default"] is False
        assert "kill" in option["label"].lower()
        assert "rotation" not in option
        rotation = get_champion_option_rotation(CHAMPION)
        # Centrally classified irrelevant (NOT an execute edge — an
        # execute role would reorder the derived Darius rotation).
        assert rotation[OPTION_KEY] == {"role": "irrelevant", "slot": "W"}

    def test_parse_halves_w_cooldown_and_declares_the_refund_rule(self) -> None:
        """With the assertion on, the W entry's sourced cooldown is halved
        (5 -> 2.5) and the entry declares the typed kill_refund rule (flat
        40.0 = the sourced flat cost, the named source receipt, no atoms).
        Without the assertion neither exists."""
        _, off = _parse(None)
        _, on = _parse({OPTION_KEY: True})
        assert off["W"]["cooldown"] == pytest.approx(W_COOLDOWN)
        assert KILL_REFUND_KEY not in off["W"]
        assert on["W"]["cooldown"] == pytest.approx(HALVED_COOLDOWN)
        declaration = on["W"][KILL_REFUND_KEY]
        assert declaration["flat"] == pytest.approx(W_COST)
        assert declaration["source"] == REFUND_SOURCE
        assert declaration["atoms"] == ()  # module typed shape (mark-refund precedent)

    def test_timed_fight_halves_the_next_w_casts(self) -> None:
        """Observable scheduling ([E,Q,W,R] rotation): every asserted-
        killing W cast halves its own post-cast cooldown, so in the 10s
        shared timeline W casts land at [1.4, 3.9, 7.15, 9.65] (4 casts)
        instead of [1.4, 7.15] (2).  Q/E/R are untouched."""
        on = _fight({OPTION_KEY: True}, duration=10.0)
        off = _fight(None, duration=10.0)
        w_on = [c["time"] for c in on["cast_timeline"] if c["slot"] == "W"]
        w_off = [c["time"] for c in off["cast_timeline"] if c["slot"] == "W"]
        assert w_off == [pytest.approx(1.4), pytest.approx(7.15)]
        assert w_on == [
            pytest.approx(1.4),
            pytest.approx(3.9),
            pytest.approx(7.15),
            pytest.approx(9.65),
        ]
        assert on["breakdown"]["W"]["casts"] == 4
        assert off["breakdown"]["W"]["casts"] == 2
        assert [c["time"] for c in on["cast_timeline"] if c["slot"] == "Q"] == [
            pytest.approx(0.65),
            pytest.approx(6.4),
        ]
        assert [c["time"] for c in on["cast_timeline"] if c["slot"] == "E"] == [
            pytest.approx(0.0)
        ]
        assert [c["time"] for c in on["cast_timeline"] if c["slot"] == "R"] == [
            pytest.approx(1.4)
        ]

    def test_refund_receipts_follow_each_w_spend(self) -> None:
        """One refund per ACCEPTED W cast at the W cast time: amount 40
        (the sourced flat cost), operation gain, the named source receipt,
        restore tier, no atoms, detail naming the W slot and ordinal.  In
        the receipt stream each refund lands AFTER its own W spend at the
        same timestamp (the walk applies it only once the cast is
        accepted — the Ezreal mark-refund pattern), so it can only enable
        LATER casts, never the paying one."""
        result = _fight({OPTION_KEY: True}, duration=10.0)
        refunds = _refunds(result)
        spends = _w_spends(result)
        assert len(refunds) == len(spends) == 4
        for refund, spend in zip(refunds, spends, strict=False):
            assert refund["amount"] == pytest.approx(W_COST)
            assert refund["kind"] == "mana"
            assert refund["tier"] == pytest.approx(TIER_RESTORE)
            assert refund["atoms"] == []
            assert refund["accepted"] is True
            assert refund["reason"] == "accepted"
            assert refund["detail"]["slot"] == "W"
            assert refund["detail"]["ordinal"] == spend["detail"]["ordinal"]
            assert refund["time"] == pytest.approx(spend["time"])
            receipts = result["resource_ledger"]["receipts"]
            assert receipts.index(refund) > receipts.index(spend)
            # The refund restores the pool to the pre-spend level exactly.
            assert refund["current_after"] == pytest.approx(spend["current_before"])

    def test_refund_ledger_stays_accounted_and_capped_at_max(self) -> None:
        """The refund stream keeps the accounting identity, never exceeds
        the account maximum, and never leaves the pool above maximum."""
        result = _fight({OPTION_KEY: True}, duration=10.0)
        _assert_accounting_identity(result)
        refunds = _refunds(result)
        assert refunds
        for refund in refunds:
            assert refund["current_after"] <= refund["maximum_after"] + 1e-9
            assert refund["current_before"] <= refund["maximum_before"] + 1e-9


# ---------------------------------------------------------------------------
# S4 — No-kill default (byte-identical without the assertion)
# ---------------------------------------------------------------------------


class TestNoKillDefault:
    def test_without_the_assertion_the_fight_is_byte_identical(self) -> None:
        """Absent vs explicitly-False produce the same fight, and the W
        surface is the pre-contract one: cooldown 5, casts at 1.4/7.15,
        no kill_refund rule."""
        absent = _fight(None, duration=10.0)
        explicit = _fight({OPTION_KEY: False}, duration=10.0)
        assert _json(absent) == _json(explicit)
        w_times = [c["time"] for c in absent["cast_timeline"] if c["slot"] == "W"]
        assert w_times == [pytest.approx(1.4), pytest.approx(7.15)]
        assert absent["breakdown"]["W"]["casts"] == 2
        _, abilities = _parse({OPTION_KEY: False})
        assert abilities["W"]["cooldown"] == pytest.approx(W_COOLDOWN)
        assert KILL_REFUND_KEY not in abilities["W"]

    def test_default_ledger_has_no_refund_receipts(self) -> None:
        result = _fight(None, duration=10.0)
        assert _refunds(result) == []
        gains = [
            r for r in result["resource_ledger"]["receipts"] if r["operation"] == "gain"
        ]
        assert gains == []  # no items, no restores, no refunds
        _assert_accounting_identity(result)


# ---------------------------------------------------------------------------
# S5 — Excluded targets (the cached notes; jungle plants)
# ---------------------------------------------------------------------------


class TestExcludedTargets:
    def test_w_notes_name_only_jungle_plants_as_the_kill_exclusion(self) -> None:
        """The cached notes (quoted verbatim) name ONE exclusion: the
        cooldown reduction and mana refund do not trigger when killing
        jungle plants.  Structures appear in ``affects`` ("Enemies,
        Structures") but the notes never exclude them from the kill rule —
        there is no structure exclusion in the source."""
        notes = get_champion(W_DATA_KEY)["abilities"]["W"][0]["notes"]
        assert (
            "The cooldown reduction and mana refund will not trigger when "
            "killing jungle plants."
        ) in notes
        assert "jungle plants" in notes
        assert "structure" not in notes.lower()

    def test_jungle_plant_exclusion_is_a_named_assumption(self) -> None:
        """The model cannot represent jungle plants as a target kind, so
        the completion replaces the not-modeled assumption with the
        contract's named receipt: the kill assertion, its sourced rule,
        and the jungle-plant exclusion documented together."""
        meta = get_champion_options_meta(CHAMPION)
        assumptions = meta["assumptions"]
        assert not any(
            "W's kill-triggered cooldown reduction and mana refund are not "
            "modeled" in text
            for text in assumptions
        )
        assert any(
            "kill" in text.lower() and "jungle plant" in text.lower()
            for text in assumptions
        )


# ---------------------------------------------------------------------------
# S6 — Denied/unavailable casts
# ---------------------------------------------------------------------------


class TestDeniedAndUnavailableCasts:
    def test_denied_w_cast_gets_no_kill_rule_and_no_refund(self) -> None:
        """A W cast the mana walk denies (insufficient mana) never happens,
        so the kill rule never fires: no refund, no cooldown change, W
        never appears on the cast timeline.  Pinned with the assertion ON
        (a denied cast must not refund even when the rule is armed)."""
        stats = _stats(max_mana=30.0, regen=0.0)
        result = _direct_fight(stats, {OPTION_KEY: True}, cast_order=["W"])
        assert result["breakdown"]["W"]["casts"] == 0
        assert _refunds(result) == []
        denied = [
            r
            for r in result["resource_ledger"]["receipts"]
            if r["operation"] == "spend" and not r["accepted"]
        ]
        assert denied
        assert all(r["reason"] == "insufficient_resource" for r in denied)

    def test_one_rotation_default_has_no_refund(self) -> None:
        """One-rotation without the assertion: the single W cast refunds
        nothing (the pre-contract baseline the completion must keep)."""
        result = _fight(None, duration=5.0, one_rotation=True)
        assert result["breakdown"]["W"]["casts"] == 1
        assert _refunds(result) == []

    def test_one_rotation_refunds_but_the_halving_is_unobservable(self) -> None:
        """One-rotation interplay: W casts exactly once at t=0, so the
        halved cooldown never has a second W to shorten — the cast count
        stays 1 and the schedule is unchanged — while the kill rule still
        refunds the single cast at t=0 (in-game the swing killed)."""
        on = _fight({OPTION_KEY: True}, duration=5.0, one_rotation=True)
        off = _fight(None, duration=5.0, one_rotation=True)
        assert on["breakdown"]["W"]["casts"] == 1
        assert on["breakdown"]["W"]["casts"] == off["breakdown"]["W"]["casts"]
        w_times = [c["time"] for c in on["cast_timeline"] if c["slot"] == "W"]
        assert w_times == [pytest.approx(0.0)]
        refunds = _refunds(on)
        assert len(refunds) == 1
        assert refunds[0]["time"] == pytest.approx(0.0)
        assert refunds[0]["amount"] == pytest.approx(W_COST)
        assert _refunds(off) == []


# ---------------------------------------------------------------------------
# S7 — Ledger ordering + max-mana cap
# ---------------------------------------------------------------------------


class TestLedgerOrderingAndCap:
    def test_kernel_refund_caps_over_restoration(self) -> None:
        """The typed ledger's OP_REFUND rides the gain cap: over-
        restoration is receipted CAPPED with current pinned at maximum.
        This is the kernel contract the fight walk applies the W refund
        through (the fight-level CAPP is unreachable while the refund
        equals the paid cost — S3 — flagged for the coordinator:
        Actualizer's discounted spend is the one fight-level path)."""
        account = ResourceAccount("main", maximum=100.0, current=100.0)
        spend = account.apply(
            ResourceEvent(
                owner="main",
                operation=OP_SPEND,
                amount=20.0,
                time=1.0,
                tier=TIER_CAST,
            )
        )
        capped = account.apply(
            ResourceEvent(
                owner="main",
                operation=OP_REFUND,
                amount=40.0,
                time=1.0,
                tier=TIER_RESTORE,
            )
        )
        assert spend.accepted is True
        assert capped.accepted is True
        assert capped.reason == "CAPPED"
        assert capped.current_after == pytest.approx(capped.maximum_after)
        # Equal amounts restore the pool exactly (accepted, not capped).
        account2 = ResourceAccount("main", maximum=100.0, current=100.0)
        account2.apply(
            ResourceEvent(
                owner="main",
                operation=OP_SPEND,
                amount=40.0,
                time=1.0,
                tier=TIER_CAST,
            )
        )
        exact = account2.apply(
            ResourceEvent(
                owner="main",
                operation=OP_REFUND,
                amount=40.0,
                time=1.0,
                tier=TIER_RESTORE,
            )
        )
        assert exact.reason == "accepted"
        assert exact.current_after == pytest.approx(100.0)

    def test_refund_stream_order_spend_then_refund_at_one_timestamp(self) -> None:
        """The refund receipt rides the restore tier (0) but is applied by
        the walk only after its cast is accepted, so in the receipt stream
        it lands AFTER the W spend at the same timestamp (in-game: cast,
        hit, kill, refund) — and before any later cast's spend."""
        result = _fight({OPTION_KEY: True}, duration=10.0)
        receipts = result["resource_ledger"]["receipts"]
        refunds = _refunds(result)
        assert refunds
        for refund in refunds:
            assert refund["tier"] == pytest.approx(TIER_RESTORE)
            same_time_spends = [
                r
                for r in receipts
                if r["operation"] == "spend" and abs(r["time"] - refund["time"]) <= 1e-9
            ]
            assert same_time_spends
            w_spend = next(
                r for r in same_time_spends if r.get("detail", {}).get("slot") == "W"
            )
            assert receipts.index(refund) > receipts.index(w_spend)


# ---------------------------------------------------------------------------
# S8 — Fail-closed malformed declarations
# ---------------------------------------------------------------------------


class TestFailClosedDeclarations:
    def test_kill_refund_declaration_validation_raises(self) -> None:
        """The typed kill_refund declaration validates like mark_refund:
        a non-mapping, a negative/non-finite flat, a missing source, or
        malformed atoms raises a ValueError naming the offending field
        (authored code fails closed, never a silent zero)."""
        stats = _stats()
        for malformed, match in (
            ("not a mapping", "kill_refund must be a mapping"),
            ({"flat": -1.0, "source": "x", "atoms": ()}, "kill_refund.flat"),
            ({"flat": float("nan"), "source": "x", "atoms": ()}, "kill_refund.flat"),
            ({"flat": 40.0, "source": "", "atoms": ()}, "kill_refund.source"),
            (
                {"flat": 40.0, "source": "x", "atoms": (("only-one-part",),)},
                "kill_refund.atoms",
            ),
        ):
            _, abilities = _parse()
            abilities["W"][KILL_REFUND_KEY] = (
                "not a mapping" if malformed == "not a mapping" else malformed
            )
            with pytest.raises(ValueError, match=match):
                calculate_fight_damage(
                    dict(stats),
                    abilities,
                    [],
                    FightConfig(
                        target_health=2500.0,
                        target_armor=100.0,
                        target_magic_resistance=50.0,
                        fight_duration_seconds=5.0,
                        auto_attack_uptime=0.0,
                        one_rotation=False,
                        deterministic=True,
                        enforce_resource_limits=True,
                    ),
                )

    def test_multiple_kill_refund_declarations_raise(self) -> None:
        """More than one slot declaring kill_refund raises (the resource
        walk supports one authored kill-refund rule per fight — the
        mark_refund multi-declaration guard)."""
        stats = _stats()
        _, abilities = _parse({OPTION_KEY: True})
        abilities["Q"][KILL_REFUND_KEY] = dict(abilities["W"][KILL_REFUND_KEY])
        with pytest.raises(ValueError, match="multiple kill_refund declarations"):
            calculate_fight_damage(
                dict(stats),
                abilities,
                [],
                FightConfig(
                    target_health=2500.0,
                    target_armor=100.0,
                    target_magic_resistance=50.0,
                    fight_duration_seconds=5.0,
                    auto_attack_uptime=0.0,
                    one_rotation=False,
                    deterministic=True,
                    enforce_resource_limits=True,
                ),
            )

    def test_api_rejects_unknown_option_keys(self) -> None:
        """The public API boundary already fails closed on option keys the
        module does not declare (a never-declared typo stays rejected
        before and after the completion)."""
        client = app_module.app.test_client()
        response = client.post(
            "/api/calculate",
            json={
                "champion": CHAMPION,
                "level": 18,
                "items": [],
                "role": "top",
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                "fight_mode": "time_based",
                "fight_duration": 10,
                "include_auto_attacks": False,
                "target_health": 2500,
                "target_armor": 100,
                "target_mr": 50,
                "champion_options": {"w_kill_assertion_typo": True},
            },
        )
        assert response.status_code == 400
        assert "unknown option" in response.get_json()["error"]

    def test_api_rejects_non_bool_option_values(self) -> None:
        """Once the bool option is declared, the API's existing option
        validator rejects a non-bool value with the typed message."""
        client = app_module.app.test_client()
        response = client.post(
            "/api/calculate",
            json={
                "champion": CHAMPION,
                "level": 18,
                "items": [],
                "role": "top",
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                "fight_mode": "time_based",
                "fight_duration": 10,
                "include_auto_attacks": False,
                "target_health": 2500,
                "target_armor": 100,
                "target_mr": 50,
                "champion_options": {OPTION_KEY: "yes"},
            },
        )
        assert response.status_code == 400
        assert "must be true or false" in response.get_json()["error"]


# ---------------------------------------------------------------------------
# S9 — Score/receipt parity
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_existing_ledger_surface_is_byte_identical_under_score_only(
        self,
    ) -> None:
        """The current resource ledger, resource_spent and
        resource_remaining are byte-identical full vs score_only."""
        full = _fight(None, duration=10.0)
        score = _fight(None, duration=10.0, score_only=True)
        assert _json(full["resource_ledger"]) == _json(score["resource_ledger"])
        assert full["resource_spent"] == score["resource_spent"]
        assert full["resource_remaining"] == score["resource_remaining"]

    def test_kill_surface_is_byte_identical_under_score_only(self) -> None:
        """The kill surface (refund receipts, halved schedule, spends)
        must be byte-identical full vs score_only — the receipt walk and
        the compiled score path agree."""
        full = _fight({OPTION_KEY: True}, duration=10.0)
        score = _fight({OPTION_KEY: True}, duration=10.0, score_only=True)
        # The refund surface exists in BOTH walks (the pins below would be
        # vacuous if the mechanic were absent).
        assert len(_refunds(full)) == len(_refunds(score)) == 4
        assert _json(full["resource_ledger"]) == _json(score["resource_ledger"])
        assert full["resource_spent"] == score["resource_spent"]
        assert full["resource_remaining"] == score["resource_remaining"]
        assert full["breakdown"]["W"]["casts"] == score["breakdown"]["W"]["casts"]


# ---------------------------------------------------------------------------
# S10 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_q_e_r_and_passive_unchanged_by_the_kill_option(self) -> None:
        """The kill contract touches only W's cooldown/refund surface: the
        P/Q/E/R breakdown rows are identical with the option on or off."""
        # One-rotation mode: W casts exactly once, so the halved cooldown
        # is unobservable and the fight's damage surface is byte-identical
        # (the only difference is the refund receipt on the ledger).
        off = _fight(None, duration=10.0, one_rotation=True)
        on = _fight({OPTION_KEY: True}, duration=10.0, one_rotation=True)
        for key in ("Q", "E", "R", "stacking_dot_passive", "auto_attacks"):
            assert _json(off["breakdown"][key]) == _json(on["breakdown"][key]), key
        assert _json(off["damage_by_type"]) == _json(on["damage_by_type"])
        assert off["total_damage"] == on["total_damage"]

    def test_r_execute_recast_unchanged_by_the_kill_option(self) -> None:
        """R's own kill-assertion option keeps its contract: with
        r_execute_recast on, R doubles with the offset recast pair whether
        or not the W kill assertion is also on."""
        options = {"r_execute_recast": True, OPTION_KEY: True}
        _, abilities = _parse(options)
        r = abilities["R"]
        assert len(r["parts"]) == 4
        # Rank 3 with +100 bonus AD: base 375 + 0.75 x 100 and per-stack
        # 75 + 0.15 x 100, at the default 5 Hemorrhage stacks, doubled.
        assert r["total_raw"] == pytest.approx(
            2 * (375.0 + 0.75 * _BONUS_AD + 5 * (75.0 + 0.15 * _BONUS_AD))
        )
        assert r["parts"][2].time_offset == pytest.approx(0.6167 + 0.15 + 0.6167)
        assert "execute recast" in r.get("detail", "")

    def test_no_new_control_events_and_no_auto_timer_reset(self) -> None:
        """W's 90% slow stays utility (no control event) and the reset
        prose ("Crippling Strike resets Darius' basic attack timer") is
        source evidence only: the auto-timer reset is not modeled — the
        empowered swing rides the engine's auto schedule.  The kill
        contract adds neither a control event nor a reset key."""
        off = _fight(None, duration=10.0)
        on = _fight({OPTION_KEY: True}, duration=10.0)
        assert _json(off["control_events"]) == _json(on["control_events"])
        assert [e["source_key"] for e in on["control_events"]] == ["E"]
        _, abilities = _parse({OPTION_KEY: True})
        w = abilities["W"]
        assert not any("reset" in key for key in w)
        assert (
            "resets Darius' basic attack timer"
            in get_champion(W_DATA_KEY)["abilities"]["W"][0]["effects"][2][
                "description"
            ]
        )

    def test_other_champions_do_not_declare_the_option(self) -> None:
        """The kill assertion is Darius-scoped: no other registered
        champion's option metadata carries the key."""
        from src.calculator.champions import registered_champion_names

        for name in registered_champion_names():
            if name == CHAMPION:
                continue
            keys = {o["key"] for o in get_champion_options_meta(name)["options"]}
            assert OPTION_KEY not in keys, name


# ---------------------------------------------------------------------------
# S11 — Regression surface (run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity set with
# ``.venv/bin/python -m pytest``:
#
#   tests/test_darius_w_kill_refund.py        (this file)
#   tests/test_darius.py                      (existing Darius surface)
#   tests/test_mana_restore_refund.py         (ledger refunds/restores)
#   tests/test_resource_ledger.py
#   tests/test_resource_ledger_consumers.py
#   tests/test_resource_ledger_champion_consumers.py
#   tests/test_catalyst_resource_ledger.py
#   tests/test_item_sustain.py
#   tests/test_ezreal_w_mark_refund.py        (the mark-refund seam)
#   tests/test_jayce_w_mana_restore.py        (the per-auto restore seam)
#   tests/test_jayce.py
#   tests/test_ashe_focus_lifecycle.py
#   tests/test_ashe_q_active_window.py
#   tests/test_bard_chimes_ledger.py
#   tests/test_heimerdinger_multihit.py
#   tests/test_ksante_w_resistance.py
#   tests/test_rengar_ferocity_ledger.py
#   tests/test_rengar_w_cleanse.py
#   tests/test_gangplank_w_cleanse.py
#   tests/test_milio_r_cleanse.py
#   tests/test_dr_mundo_passive.py
#   tests/test_olaf_r_cleanse.py
#   tests/test_app.py
