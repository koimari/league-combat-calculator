"""P3 Package 3M — Doran's Helm Helping Hand minion-only damage certification.

This file is the focused acceptance-matrix owner for Doran's Helm's
Helping Hand passive.  It pins the OBSERVABLES of the P3-3M completion.

P3-3M HAS LANDED.  Before it, the fight model was champion-only: no minion
target was representable, so every minion-context assertion below was a
documented-boundary test asserting a fail-closed denial (the
``_MinionTargetUnavailable`` helper exception, since removed) not a number.  The
kernel now carries a target-class gate (``FightConfig.target_class``), so
each of those boundary pins has been CONVERTED to the live sourced
arithmetic it was always standing in for — a strictly stronger assertion,
never a weaker one.  The champion-class path is unchanged and still pinned
bit-identical (see ``test_champion_targets_receive_zero_helping_hand_damage``).

Contract under test (typed source-backed values):

* SOURCED FLAT: the cached Wiki branch and the full-entry audit both state
  "Basic attacks deal {{as|5 '''bonus''' physical damage}} [[on-hit]]
  against [[minions]]."  The typed value is 5.0 bonus PHYSICAL damage per
  qualifying basic attack against a minion (docs/wiki-full-entry-audit.json
  revision 4034679, page 1726898).  The source revision must ride the
  item's typed registry (``ITEM_EFFECTS`` / ``ITEM_INPUT_OPTIONS`` /
  ``item_state_receipts``) so a parser refresh cannot overwrite it.
* TYPED ACCESSOR: ``required_effect_value("Doran's Helm", ...)`` is the
  value home (AGENTS.md rule 5: no silent stale fallbacks); a missing key
  raises ``KeyError`` naming Doran's Helm AND the key.
* BASIC ATTACKS vs MINIONS: IF a classified minion target can exist, one
  qualifying basic attack receives exactly the sourced 5 bonus physical
  damage ONCE, and every repeated qualifying attack receives it again
  (N attacks -> N x 5, no double application with the auto's own damage).
* CHAMPION EXCLUSION: basic attacks against CHAMPION targets receive NO
  Helping Hand damage — the bonus never applies to champions (champion-TDD
  effect is zero).
* ABILITY / NON-BASIC EXCLUSION: abilities, item procs, and non-basic
  packets receive no Helping Hand damage even against minions.
* FAIL CLOSED: missing/unknown/malformed target classification receives no
  invented damage.
* RESISTANCE: the bonus is PHYSICAL — it rides the normal armor-mitigated
  physical path (5 at armor 0, 5 x 100/(100+armor) above 0), never true
  damage.
* SCORE/RECEIPT PARITY: the score path (fight breakdown contribution) and
  the receipt path (``item_state_receipts`` row) agree where the target
  model supports the branch; unsupported target contexts fail closed on
  BOTH paths (no row and no receipt in the champion-only model).
* THE BOUNDARY (post-P3-3M): the target-class label gates class-restricted
  EFFECTS only.  The target's stats stay caller-supplied — no sourced
  minion base-stat block is cached, so a "minion" fight is a champion-shaped
  target wearing a minion label, and its health/armor/MR are whatever the
  caller passed.  Champion ABILITY class clauses (Nasus Q, Cho'Gath Feast,
  Ezreal R's minion row) are NOT adjudicated.  Any build item whose sourced
  text carries an unadjudicated target-class clause makes a minion-class
  fight fail closed with the item and clause named, rather than pricing it
  with the champion-class reading.  ``item_coverage`` still classifies the
  Helm ``stats_only`` because the CHAMPION-class contribution is zero.

Sibling owners: the Tear of the Goddess Helping Hand precedent (same 5.0
flat, same minion-only boundary) is pinned in ``tests/test_cp20_items.py``
and ``tests/test_resource_ledger.py``; the P3-3X matrix conventions follow
``tests/test_muramana_packet.py``.  This file is disjoint and pins only the
Doran's Helm acceptance observables.
"""

import dataclasses
import json
from pathlib import Path

import pytest

import src.app as app_module
import src.calculator.item_effects as item_effects_module
from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.item_coverage import ATTACKER_LANES, item_model_coverage
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    dorans_helm_helping_hand_minion_damage,
    item_state_receipts,
    required_effect_value,
)
from src.calculator.stats import calculate_total_stats
from tests.app_config import app_config

HELM = "Doran's Helm"
HELPING_HAND_KEY = "helping_hand_minion_damage"
AUDIT_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "wiki-full-entry-audit.json"
)
# Sourced revision receipt from docs/wiki-full-entry-audit.json (read-only docs pin).
HELM_REVISION_ID = 4034679
HELM_PAGE_ID = 1726898
BRANCH_TEXT = (
    "Basic attacks deal {{as|5 '''bonus''' physical damage}} [[on-hit]] "
    "against [[minions]]."
)


def _helm() -> dict:
    """The real cached item record (id 1120, passive Helping Hand)."""
    return get_item_by_name(HELM)


def _audit_helm_entry() -> dict:
    """The Doran's Helm row of docs/wiki-full-entry-audit.json."""
    with AUDIT_PATH.open(encoding="utf-8") as handle:
        audit = json.load(handle)
    matches = [row for row in audit["entries"] if row.get("name") == HELM]
    assert matches, "full-entry audit must contain Doran's Helm"
    return matches[0]


def _champion_fight(stats, abilities=None, *, items=(), **overrides):
    """One champion-target fight through the public engine (the only target
    the 1v1 model can express today)."""
    config = {
        "target_health": 1000.0,
        "target_armor": 100.0,
        "target_magic_resistance": 100.0,
        "fight_duration_seconds": 5.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": True,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(
        stats, abilities or {}, list(items), FightConfig(**config)
    )


# Spelling contract for the minion-kind gate.  P3-3M landed exactly ONE of
# these three candidate spellings on FightConfig; the others must stay
# absent so there is a single unambiguous target-class home.
_MINION_TARGET_FIELD_NAMES = ("target_kind", "target_class", "target_type")
_LANDED_TARGET_FIELD = "target_class"


def _minion_target_kwargs(target_kind: str = "minion") -> dict:
    """Return the FightConfig kwarg that classifies the target as a minion."""
    return {_LANDED_TARGET_FIELD: target_kind}


def _minion_fight(
    stats, abilities=None, *, items=(), target_kind="minion", **overrides
):
    """One fight whose target is classified as *target_kind*.

    A bad *target_kind* spelling raises ``ValueError`` from
    ``FightConfig.__post_init__``; an unadjudicated build item raises
    ``ValueError`` from the engine's build-scoped class gate."""
    config = {
        "target_health": 1000.0,
        "target_armor": 100.0,
        "target_magic_resistance": 100.0,
        "fight_duration_seconds": 5.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": True,
        "deterministic": True,
    }
    config.update(overrides)
    config.update(_minion_target_kwargs(target_kind))
    return calculate_fight_damage(
        stats, abilities or {}, list(items), FightConfig(**config)
    )


def _helm_contribution(
    stats, *, target_kind, abilities=None, items=(), **overrides
) -> float:
    """The Doran's Helm-sourced total-damage contribution in one target context.

    Doran's Helm carries no offensive stats (150 HP / 8 armor / 8 MR only),
    so ``total_damage(helm build) - total_damage(bare build)`` isolates the
    Helping Hand branch mechanism-free: any row naming the coordinator
    chooses is covered without coupling this matrix to a breakdown key."""
    with_helm = _minion_fight(
        stats, abilities, items=(_helm(), *items), target_kind=target_kind, **overrides
    )
    without = _minion_fight(
        stats, abilities, items=items, target_kind=target_kind, **overrides
    )
    return with_helm["total_damage"] - without["total_damage"]


def _champion_contribution(stats, *, abilities=None, items=(), **overrides) -> float:
    """Champion-target total-damage delta (champion-only model)."""
    with_helm = _champion_fight(stats, abilities, items=(_helm(), *items), **overrides)
    without = _champion_fight(stats, abilities, items=items, **overrides)
    return with_helm["total_damage"] - without["total_damage"]


# ---------------------------------------------------------------------------
# 1. Sourced data + typed accessor (parent pin 1)
# ---------------------------------------------------------------------------


def test_cached_entry_and_full_entry_audit_pin_the_sourced_flat_and_revision():
    """The cached item and the docs audit agree: 5 bonus PHYSICAL damage
    on-hit vs minions, at wiki revision 4034679 (page 1726898)."""
    item = _helm()
    (passive,) = item["passives"]
    assert passive["name"] == "Helping Hand"
    assert BRANCH_TEXT in passive["branches"]

    entry = _audit_helm_entry()
    assert entry["revision_id"] == HELM_REVISION_ID
    assert entry["page_id"] == HELM_PAGE_ID
    assert entry["status"] == "ready"
    assert entry["source_url"] == "https://wiki.leagueoflegends.com/en-us/Doran's_Helm"
    descriptions = entry["full_entry_review"]["expected_effects"]["effects"][0][
        "descriptions"
    ]
    assert BRANCH_TEXT in descriptions
    runtime = entry["full_entry_review"]["runtime"]
    assert runtime["status"] == "stats_only"
    assert "minion" in runtime["reason"]
    assert "5 bonus physical damage" in runtime["reason"]


def test_missing_accessor_key_fails_loud_naming_item_and_key():
    """AGENTS.md rule 5: a missing key raises KeyError naming Doran's Helm
    AND the key — no silent stale fallback (passes today AND after the
    P3-3M typed entry lands; the key is deliberately never a real key)."""
    with pytest.raises(KeyError) as excinfo:
        required_effect_value(HELM, "not_a_typed_helm_key")
    # KeyError.args[0] is the raw message; str() adds repr escaping.
    message = excinfo.value.args[0]
    assert HELM in message
    assert "not_a_typed_helm_key" in message


def test_typed_accessor_exposes_the_sourced_5_bonus_physical():
    """P3-3M contract: ``required_effect_value`` is the value home and the
    sourced flat is exactly 5.0 (matches the audit branch's number)."""
    value = required_effect_value(HELM, HELPING_HAND_KEY)
    assert value == pytest.approx(5.0)
    assert not isinstance(value, bool)


def test_source_revision_is_discoverable_through_the_typed_registry():
    """P3-3M contract: the audit revision 4034679 rides the item's typed
    registry (ITEM_EFFECTS static keys or the ITEM_INPUT_OPTIONS source
    receipt, per the Catalyst/Tear precedents) so a parser refresh cannot
    overwrite it."""
    revision = ITEM_INPUT_OPTIONS.get(HELM, {}).get(
        "source_revision_id"
    ) or ITEM_EFFECTS.get(HELM, {}).get("source_revision_id")
    assert revision == HELM_REVISION_ID
    source_url = ITEM_INPUT_OPTIONS.get(HELM, {}).get(
        "source_url", ITEM_EFFECTS.get(HELM, {}).get("source_url")
    )
    assert source_url == "https://wiki.leagueoflegends.com/en-us/Doran's_Helm"


# ---------------------------------------------------------------------------
# 2 + 8. Basic attacks vs minions / THE BOUNDARY
# ---------------------------------------------------------------------------


def test_the_model_exposes_exactly_one_target_class_gate():
    """CONVERTED from the pre-P3-3M champion-only pin.  The kernel now has a
    minion gate, and it must be exactly ONE field so there is a single
    unambiguous home for the target class (a second spelling would let two
    callers disagree about which one the engine reads)."""
    field_names = {field.name for field in dataclasses.fields(FightConfig)}
    landed = field_names & set(_MINION_TARGET_FIELD_NAMES)
    assert landed == {_LANDED_TARGET_FIELD}, (
        "P3-3M must expose exactly one target-class gate on FightConfig; "
        f"found {sorted(landed)}"
    )
    # It defaults to the historical champion model, so every pre-P3-3M
    # caller keeps its exact behavior without passing anything.
    assert FightConfig.target_class == "champion"
    assert item_effects_module.TARGET_CLASSES == ("champion", "minion")


def test_one_qualifying_minion_auto_deals_exactly_5_bonus_physical_once(attacker_stats):
    """CONVERTED to live arithmetic: ONE qualifying basic attack against a
    minion-class target adds exactly the sourced 5.0 bonus physical damage,
    exactly once.

    Sourced arithmetic: 1 auto x 5.0 flat = 5.0 at target_armor 0 (no
    mitigation), and the Helm carries no offensive stats (150 HP / 8 armor
    / 8 MR), so the with-minus-without delta IS the Helping Hand branch."""
    stats = attacker_stats()
    with_helm = _minion_fight(
        stats,
        items=(_helm(),),
        fight_duration_seconds=1.0,
        auto_attack_uptime=1.0,
        one_rotation=False,
        target_armor=0.0,
    )
    without = _minion_fight(
        stats,
        fight_duration_seconds=1.0,
        auto_attack_uptime=1.0,
        one_rotation=False,
        target_armor=0.0,
    )
    assert with_helm["breakdown"]["auto_attacks"]["count"] == 1
    delta = with_helm["total_damage"] - without["total_damage"]
    assert delta == pytest.approx(5.0)
    # Applied ONCE, not folded twice into the auto's own packet.
    assert with_helm["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
        without["breakdown"]["auto_attacks"]["damage_per_hit"]
    )


def test_repeated_qualifying_minion_autos_each_add_the_bonus_once(attacker_stats):
    """CONVERTED to live arithmetic: N qualifying minion autos add N x 5.0.

    Sourced arithmetic at target_armor 0: the 5s fight lands 5 autos, so
    the delta is 5 x 5.0 = 25.0 — one application per swing, no double
    counting and no per-fight cap."""
    stats = attacker_stats()
    with_helm = _minion_fight(
        stats,
        items=(_helm(),),
        fight_duration_seconds=5.0,
        auto_attack_uptime=1.0,
        one_rotation=False,
        target_armor=0.0,
    )
    without = _minion_fight(
        stats,
        fight_duration_seconds=5.0,
        auto_attack_uptime=1.0,
        one_rotation=False,
        target_armor=0.0,
    )
    auto_count = with_helm["breakdown"]["auto_attacks"]["count"]
    assert auto_count == 5
    delta = with_helm["total_damage"] - without["total_damage"]
    assert delta == pytest.approx(auto_count * 5.0)
    assert delta == pytest.approx(25.0)


def test_helping_hand_is_physical_damage_not_true(attacker_stats):
    """CONVERTED to live arithmetic: the bonus rides the ordinary
    armor-mitigated PHYSICAL path, never true damage.

    Sourced arithmetic per auto (5 autos in a 5s fight):
      armor   0 -> 5.0 x 100/(100+0)   = 5.0  -> 5 x 5.0 = 25.0
      armor 100 -> 5.0 x 100/(100+100) = 2.5  -> 5 x 2.5 = 12.5
    True damage would have produced 25.0 at BOTH armors, so the strict
    inequality below is what rules true damage out."""
    stats = attacker_stats()
    deltas = {}
    for armor in (0.0, 100.0):
        deltas[armor] = _helm_contribution(
            stats,
            target_kind="minion",
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            target_armor=armor,
        )
    assert deltas[0.0] == pytest.approx(5 * 5.0 * 100.0 / 100.0)
    assert deltas[100.0] == pytest.approx(5 * 5.0 * 100.0 / 200.0)
    assert deltas[0.0] == pytest.approx(25.0)
    assert deltas[100.0] == pytest.approx(12.5)
    # Not true damage: armor demonstrably reduced it.
    assert deltas[100.0] < deltas[0.0]


# ---------------------------------------------------------------------------
# 3. Champion target exclusion + 4. ability/non-basic exclusion
# ---------------------------------------------------------------------------


def test_champion_targets_receive_zero_helping_hand_damage(attacker_stats, fight):
    """Basic attacks against CHAMPION targets receive NO Helping Hand
    damage: the champion fight is bit-identical with and without the Helm
    (no breakdown row, identical auto per-hit, empty receipt row, zero
    total-damage delta) — on both the score and receipt paths."""
    stats = attacker_stats()
    with_helm = fight(
        stats,
        {},
        items=[_helm()],
        fight_duration_seconds=5.0,
        auto_attack_uptime=1.0,
        one_rotation=False,
    )
    without = fight(
        stats,
        {},
        items=[],
        fight_duration_seconds=5.0,
        auto_attack_uptime=1.0,
        one_rotation=False,
    )
    assert with_helm["total_damage"] == pytest.approx(without["total_damage"])
    assert with_helm["breakdown"]["auto_attacks"]["damage_per_hit"] == pytest.approx(
        without["breakdown"]["auto_attacks"]["damage_per_hit"]
    )
    assert (
        with_helm["breakdown"]["auto_attacks"]["count"]
        == without["breakdown"]["auto_attacks"]["count"]
    )
    assert not [
        key for key in with_helm["breakdown"] if "Helping Hand" in key or "Doran" in key
    ]
    # The named-boundary receipt IS the 3M change: it carries the typed
    # minion-only contract, and it contributes zero champion damage.
    helm_receipts = [
        row
        for row in with_helm["item_state_receipts"]
        if row.get("item") == "Doran's Helm"
    ]
    assert len(helm_receipts) == 1
    row = helm_receipts[0]
    assert row["state"] == "helping_hand_minion_only"
    assert row["helping_hand_minion_only"] is True
    assert row["helping_hand_minion_damage"] == pytest.approx(5.0)
    assert "minions only" in row["helping_hand_boundary"]
    assert row["source_revision_id"] == 4034679


def test_abilities_and_item_procs_add_no_helping_hand_damage(attacker_stats, ahri_data):
    """THE BOUNDARY: the ability/non-basic exclusion contract cannot be
    exercised today — every attempt to author a minion-targeted fight
    (pure ability rotation or auto+proc mix) fails closed with the named
    boundary exception rather than inventing a minion-context result."""
    stats = attacker_stats()
    abilities = parse_champion_abilities(ahri_data, 18, 0.0, ability_ranks={"Q": 5})
    # A pure ability rotation against a minion lands ZERO basic attacks, so
    # Helping Hand contributes exactly 0.0 — the branch is on-hit-on-basic,
    # never an ability packet.
    assert _helm_contribution(
        stats,
        target_kind="minion",
        abilities=abilities,
        fight_duration_seconds=5.0,
        auto_attack_uptime=0.0,
        one_rotation=True,
        cast_order=["Q"],
    ) == pytest.approx(0.0)
    # Statikk Shiv's Electrospark carries its OWN unadjudicated class clause
    # ("increased to 90 against non-champions"), so a minion-class fight
    # holding it fails closed naming the item and clause rather than
    # pricing that proc with the champion-class reading.
    with pytest.raises(ValueError) as excinfo:
        _helm_contribution(
            stats,
            target_kind="minion",
            items=({"name": "Statikk Shiv"},),
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            target_armor=0.0,
        )
    message = str(excinfo.value)
    assert "Statikk Shiv" in message
    assert "non-champion" in message


# ---------------------------------------------------------------------------
# 5. Missing / malformed target classification fails closed
# ---------------------------------------------------------------------------


def test_missing_target_kind_invents_no_helping_hand_damage(attacker_stats):
    """A fight that expresses NO target classification (the only expressible
    context today) invents no Helping Hand damage: the default champion
    path contributes exactly 0 and authors no receipt row."""
    stats = attacker_stats()
    assert _champion_contribution(
        stats,
        fight_duration_seconds=5.0,
        auto_attack_uptime=1.0,
        one_rotation=False,
    ) == pytest.approx(0.0)
    receipts = item_state_receipts(
        [_helm()], {}, fight_duration_seconds=5.0, is_melee=True
    )
    helm_rows = [r for r in receipts if r.get("item") == "Doran's Helm"]
    assert len(helm_rows) == 1
    assert helm_rows[0]["state"] == "helping_hand_minion_only"
    assert helm_rows[0]["helping_hand_minion_only"] is True
    assert helm_rows[0]["helping_hand_minion_damage"] == pytest.approx(5.0)


def test_unknown_or_malformed_target_kind_fails_closed(attacker_stats):
    """CONVERTED: unknown/malformed target classes invent NO Helping Hand
    damage — they raise ValueError from ``FightConfig.__post_init__``
    naming the accepted spellings.  Case variants ("MINION") and plurals
    ("minions") are rejected too: the kernel has ONE spelling contract and
    does not silently normalize a caller's guess into a live minion fight.
    "monster"/"structure" are real LoL target classes the model does not
    adjudicate, so they fail closed rather than aliasing onto "minion"."""
    stats = attacker_stats()
    for bad_kind in ("monster", "structure", "MINION", "minions", ""):
        with pytest.raises(ValueError) as excinfo:
            _minion_fight(
                stats,
                items=(_helm(),),
                target_kind=bad_kind,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            )
        message = str(excinfo.value)
        assert "target_class" in message
        assert repr(bad_kind) in message


# ---------------------------------------------------------------------------
# 7. Receipt-vs-score parity
# ---------------------------------------------------------------------------


def test_receipt_row_pins_the_typed_minion_only_boundary():
    """P3-3M contract (receipt path): the Doran's Helm state receipt names
    the minion-only boundary with the typed 5.0 and the sourced revision —
    the Tear of the Goddess Helping Hand precedent, mirrored for the Helm."""
    receipts = item_state_receipts(
        [_helm()], {}, fight_duration_seconds=5.0, is_melee=True
    )
    row = next(row for row in receipts if row["item"] == HELM)
    assert row[HELPING_HAND_KEY] == pytest.approx(5.0)
    assert row["helping_hand_minion_only"] is True
    boundary = row["helping_hand_boundary"]
    assert "minion" in boundary
    assert "champion" in boundary
    assert row["source_revision_id"] == HELM_REVISION_ID


def test_minion_score_and_receipt_paths_agree(attacker_stats):
    """CONVERTED to a live two-path comparison: the typed receipt value and
    the live minion SCORE contribution are the same sourced number.

    Sourced arithmetic: the receipt states 5.0 per qualifying basic attack;
    the score path at target_armor 0 yields delta/auto_count = 25.0/5 = 5.0.
    A drift on either side (a stale receipt literal, or an engine that
    applied the branch twice) breaks this equality."""
    stats = attacker_stats()
    receipts = item_state_receipts(
        [_helm()], {}, fight_duration_seconds=5.0, is_melee=True
    )
    row = next(row for row in receipts if row["item"] == HELM)
    receipt_value = row[HELPING_HAND_KEY]
    assert receipt_value == pytest.approx(5.0)

    with_helm = _minion_fight(
        stats,
        items=(_helm(),),
        fight_duration_seconds=5.0,
        auto_attack_uptime=1.0,
        one_rotation=False,
        target_armor=0.0,
    )
    without = _minion_fight(
        stats,
        fight_duration_seconds=5.0,
        auto_attack_uptime=1.0,
        one_rotation=False,
        target_armor=0.0,
    )
    auto_count = with_helm["breakdown"]["auto_attacks"]["count"]
    per_auto = (with_helm["total_damage"] - without["total_damage"]) / auto_count
    assert per_auto == pytest.approx(receipt_value)
    # The score path also authors its own named breakdown row.
    assert f"on_hit_minion_{HELM}" in with_helm["breakdown"]


def test_atom_backed_accessor_rejects_stale_registry_literals(monkeypatch):
    """P3-3M contract: the accessor is atom-backed — a monkeypatched
    registry value that diverges from the catalog atom fails closed with
    a ValueError naming the atom hash (a stale literal can never ride),
    while the sourced 5.0 keeps resolving."""
    registry = ITEM_EFFECTS if HELM in ITEM_EFFECTS else {}
    assert HELM in registry
    effect = registry[HELM]
    assert dorans_helm_helping_hand_minion_damage() == pytest.approx(5.0)
    monkeypatch.setitem(registry, HELM, {**effect, HELPING_HAND_KEY: 5.5})
    with pytest.raises(ValueError) as excinfo:
        dorans_helm_helping_hand_minion_damage()
    message = str(excinfo.value)
    assert "Doran's Helm" in message
    assert "diverges from catalog atom" in message
    assert "f991d9ce51cb971b" in message


# ---------------------------------------------------------------------------
# 6 + 9. Coverage wording, flat stats, and existing regressions stay green
# ---------------------------------------------------------------------------


def test_coverage_wording_names_the_minion_only_boundary():
    """The item-coverage classification names the minion-only boundary:
    Helping Hand's 5 bonus physical damage is restricted to minions, so the
    item stays optimizer-eligible as stats_only with zero champion TDD.

    P3-3M does NOT move this classification.  ``item_model_coverage`` scores
    the CHAMPION-class model (what the optimizer builds against), and the
    champion-class contribution is still exactly zero — so the Helm remains
    ``stats_only`` and remains certified in
    ``tests/test_stats_only_items.py``.  Only the reason WORDING changed:
    the old text claimed the model "has no minion targets", which P3-3M
    made false."""
    coverage = item_model_coverage(str(_helm()["name"]), ATTACKER_LANES).as_payload()
    assert coverage["status"] == "stats_only"
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert "minion" in coverage["reason"]
    assert "5 bonus physical damage" in coverage["reason"]
    # The superseded claim must not survive anywhere in the reason.
    assert "no minion targets" not in coverage["reason"]


def test_doran_helm_flat_stats_still_flow_through_the_stats_path(ahri_data):
    """The item's ordinary stats (150 HP / 8 armor / 8 MR) still flow
    through stats.py; the minion-only passive never displaces them."""
    base = calculate_total_stats(ahri_data, 18, [])
    stats = calculate_total_stats(ahri_data, 18, [_helm()])
    assert stats["health"] == pytest.approx(base["health"] + 150.0)
    assert stats["armor"] == pytest.approx(base["armor"] + 8.0)
    assert stats["magic_resistance"] == pytest.approx(base["magic_resistance"] + 8.0)


def test_app_item_picker_and_calculate_stay_green():
    """App regressions: every Doran item (including the Helm) stays
    selectable, a Doran's Blade fight still resolves, and an API fight with
    Doran's Helm deals exactly the champion-only total (zero Helping Hand
    contribution through the app path)."""
    with app_config(RATE_LIMIT_ENABLED=False):
        client = app_module.app.test_client()
        names = {item["name"] for item in client.get("/api/items").get_json()}

        assert {"Doran's Blade", "Doran's Ring", "Doran's Shield", HELM} <= names

        def _total(items):
            response = client.post(
                "/api/calculate",
                json={
                    "champion": "Ahri",
                    "level": 18,
                    "items": items,
                    "fight_mode": "time_based",
                    "fight_duration": 5,
                    "rotations": 1,
                    "include_auto_attacks": True,
                    "auto_attack_uptime": 1.0,
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                },
            )
            assert response.status_code == 200
            return response.get_json()["total_damage"]

        assert _total([HELM]) == pytest.approx(_total([]))
        assert _total(["Doran's Blade"]) > 0.0


# ---------------------------------------------------------------------------
# 10. P3-3M request plumbing: the public API target_class selector
# ---------------------------------------------------------------------------


@pytest.fixture(name="api_client")
def _api_client():
    """A rate-limit-free test client for the public calculate endpoint."""
    with app_config(RATE_LIMIT_ENABLED=False):
        yield app_module.app.test_client()


def _calculate(client, **extra):
    """POST one Ahri auto-attacking fight, with *extra* merged into the body."""
    body = {
        "champion": "Ahri",
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 5,
        "rotations": 1,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
    }
    body.update(extra)
    return client.post("/api/calculate", json=body)


def test_api_defaults_to_the_champion_class_when_target_class_is_omitted(api_client):
    """Omitting target_class keeps the historical champion fight, so every
    pre-P3-3M request body is byte-identical in its result."""
    omitted = _calculate(api_client)
    explicit = _calculate(api_client, target_class="champion")
    assert omitted.status_code == 200
    assert explicit.status_code == 200
    assert omitted.get_json()["total_damage"] == pytest.approx(
        explicit.get_json()["total_damage"]
    )


def test_api_minion_class_arms_the_sourced_helping_hand_packet(api_client):
    """Request plumbing end to end: an API minion-class fight holding the
    Helm out-damages the same fight without it by exactly the sourced
    5.0-per-auto branch, while the champion-class fight is unchanged.

    Sourced arithmetic: target_armor 0 and 5 autos in the 5s fight give a
    25.0 delta (5 x 5.0); the champion-class delta is exactly 0.0."""
    minion_with = _calculate(
        api_client, target_class="minion", items=[HELM], target_armor=0
    )
    minion_without = _calculate(
        api_client, target_class="minion", items=[], target_armor=0
    )
    assert minion_with.status_code == 200
    assert minion_without.status_code == 200
    payload = minion_with.get_json()
    auto_count = payload["breakdown"]["auto_attacks"]["count"]
    delta = payload["total_damage"] - minion_without.get_json()["total_damage"]
    assert delta == pytest.approx(auto_count * 5.0)
    assert f"on_hit_minion_{HELM}" in payload["breakdown"]

    champion_with = _calculate(
        api_client, target_class="champion", items=[HELM], target_armor=0
    )
    champion_without = _calculate(
        api_client, target_class="champion", items=[], target_armor=0
    )
    assert champion_with.get_json()["total_damage"] == pytest.approx(
        champion_without.get_json()["total_damage"]
    )


@pytest.mark.parametrize(
    "bad_value", ["banana", "MINION", "minions", "monster", "structure", "  "]
)
def test_api_rejects_unknown_target_class_spellings_with_a_named_error(
    api_client, bad_value
):
    """Fail closed at the request boundary: an unknown or non-canonical
    spelling is a 400 naming the field and the accepted values — never a
    silent fallback to the champion default."""
    response = _calculate(api_client, target_class=bad_value)
    assert response.status_code == 400
    error = response.get_json()["error"]
    assert "target_class" in error
    assert "champion" in error
    assert "minion" in error


@pytest.mark.parametrize("bad_value", [5, 1.5, True, None, ["minion"], {"a": 1}])
def test_api_rejects_non_string_target_class_with_a_named_error(api_client, bad_value):
    """A non-string target_class is a 400 naming the field — the request
    layer never coerces a truthy value into a target class."""
    response = _calculate(api_client, target_class=bad_value)
    assert response.status_code == 400
    assert "target_class" in response.get_json()["error"]


def test_api_minion_fight_fails_closed_on_an_unadjudicated_class_item(api_client):
    """An item whose sourced text carries an unadjudicated target-class
    clause makes the whole minion fight a named 400 rather than pricing
    that clause with the champion-class reading (Statikk Shiv's
    Electrospark is 60 magic on a champion and a sourced 90 on a
    non-champion — guessing either way would be invented damage)."""
    response = _calculate(api_client, target_class="minion", items=["Statikk Shiv"])
    assert response.status_code == 400
    error = response.get_json()["error"]
    assert "Statikk Shiv" in error
    assert "minion" in error
    # The SAME build is fine against a champion-class target.
    assert _calculate(api_client, items=["Statikk Shiv"]).status_code == 200
