"""P3 Package 3M — Doran's Helm Helping Hand minion-only damage certification.

This file is the focused acceptance-matrix owner for Doran's Helm's
Helping Hand passive.  It pins the OBSERVABLES the coordinator's P3-3M
completion must satisfy, and each test runs against today's source: every
behavior that already exists passes now; every assertion that targets a
mechanic the 1v1 champion-only fight model cannot express is a named
documented-boundary test asserting the current fail-closed denial (the
``_MinionTargetUnavailable`` exception) rather than an ``xfail`` — the 1v1
champion-only model is the acceptance's most likely final state (see THE
BOUNDARY below), so no coordinator completion is pending.

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
* THE BOUNDARY: the 1v1 fight model is CHAMPION-ONLY.  Today no minion
  target is representable (``FightConfig`` exposes no target-kind field),
  so no Helping Hand damage can fire; ``item_coverage`` names the
  minion-only boundary and the champion-TDD effect is zero.  These pins
  are the acceptance's most likely final state; the documented-boundary
  tests below assert the fail-closed denial and would need rewriting only
  if a coordinator later adds a classified minion target.

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
from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.item_coverage import item_model_coverage
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    dorans_helm_helping_hand_minion_damage,
    item_state_receipts,
    required_effect_value,
)
from src.calculator.stats import calculate_total_stats

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


class _MinionTargetUnavailable(Exception):
    """The 1v1 champion-only model cannot express a minion target yet."""


# Spelling contract for a future minion-kind gate: the acceptance requires
# a classified minion target; the field name is pinned to one of these
# three spellings on FightConfig so the score path could author a
# minion-targeted fight.  Absent the gate, the acceptance tests assert the
# named boundary exception instead of guessing an API.
_MINION_TARGET_FIELD_NAMES = ("target_kind", "target_class", "target_type")


def _minion_target_kwargs(target_kind: str = "minion") -> dict:
    """Return the FightConfig kwarg that classifies the target as a minion."""
    field_names = {field.name for field in dataclasses.fields(FightConfig)}
    for name in _MINION_TARGET_FIELD_NAMES:
        if name in field_names:
            return {name: target_kind}
    raise _MinionTargetUnavailable(
        "the 1v1 champion-only model has no minion target kind"
    )


def _minion_fight(
    stats, abilities=None, *, items=(), target_kind="minion", **overrides
):
    """One fight whose target is classified as *target_kind*.

    Raises ``_MinionTargetUnavailable`` when the minion-kind gate is absent
    (the acceptance's most likely final state); the documented-boundary
    tests below assert this exception directly."""
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


def test_no_minion_target_is_representable_in_the_1v1_model():
    """THE BOUNDARY (most likely final state): the 1v1 fight model is
    champion-only — FightConfig exposes no target-kind field, so no minion
    target exists and no Helping Hand damage can fire.  If the coordinator
    adds a minion-kind gate, this pin changes by design."""
    field_names = {field.name for field in dataclasses.fields(FightConfig)}
    assert not (field_names & set(_MINION_TARGET_FIELD_NAMES)), (
        "the 1v1 champion-only model must not expose a target-kind gate "
        "until P3-3M lands it with the named minion boundary"
    )


def test_one_qualifying_minion_auto_deals_exactly_5_bonus_physical_once(attacker_stats):
    """THE BOUNDARY: the full P3-3M contract (one qualifying minion auto
    adds exactly the sourced 5 bonus physical damage once) cannot be
    exercised today — FightConfig has no minion-kind field, so no
    minion-targeted fight can even be constructed.  Attempting to author
    one fails closed with the named boundary exception rather than
    inventing a target."""
    stats = attacker_stats()
    with pytest.raises(_MinionTargetUnavailable):
        _minion_fight(
            stats,
            items=(_helm(),),
            target_kind="minion",
            fight_duration_seconds=1.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            target_armor=0.0,
        )


def test_repeated_qualifying_minion_autos_each_add_the_bonus_once(attacker_stats):
    """THE BOUNDARY: the N-autos-times-5.0 contract cannot be exercised
    today for the same reason — no minion-kind field exists on
    FightConfig, so authoring the fight fails closed."""
    stats = attacker_stats()
    with pytest.raises(_MinionTargetUnavailable):
        _minion_fight(
            stats,
            items=(_helm(),),
            target_kind="minion",
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            target_armor=0.0,
        )


def test_helping_hand_is_physical_damage_not_true(attacker_stats):
    """THE BOUNDARY: the armor-mitigation contract (5 x 100/(100+armor))
    cannot be exercised today for the same reason — no minion target is
    representable, so no per-armor contribution can be computed; every
    attempt fails closed instead of inventing a value."""
    stats = attacker_stats()
    for armor in (0.0, 100.0):
        with pytest.raises(_MinionTargetUnavailable):
            _helm_contribution(
                stats,
                target_kind="minion",
                fight_duration_seconds=1.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
                target_armor=armor,
            )


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
    with pytest.raises(_MinionTargetUnavailable):
        _helm_contribution(
            stats,
            target_kind="minion",
            abilities=abilities,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            one_rotation=True,
            cast_order=["Q"],
        )
    with pytest.raises(_MinionTargetUnavailable):
        _minion_fight(
            stats,
            items=(_helm(),),
            target_kind="minion",
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            target_armor=0.0,
        )
    with pytest.raises(_MinionTargetUnavailable):
        _helm_contribution(
            stats,
            target_kind="minion",
            items=({"name": "Statikk Shiv"},),
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            target_armor=0.0,
        )


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
    """THE BOUNDARY: unknown/malformed target kinds receive NO invented
    Helping Hand damage — today EVERY target kind (valid "minion" spelling
    included) fails closed the same way, because no minion-kind field
    exists on FightConfig at all.  The boundary exception is raised
    uniformly regardless of the requested kind."""
    stats = attacker_stats()
    for bad_kind in ("monster", "structure", "MINION", "minions", ""):
        with pytest.raises(_MinionTargetUnavailable):
            _minion_fight(
                stats,
                items=(_helm(),),
                target_kind=bad_kind,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            )


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
    """THE BOUNDARY: the score-vs-receipt parity contract needs a live
    minion score contribution to compare against the typed receipt —
    unreachable today, since no minion-targeted fight can be authored.
    The receipt path alone stays live (pinned in
    ``test_receipt_row_pins_the_typed_minion_only_boundary``); the score
    side fails closed instead of inventing a comparison value."""
    stats = attacker_stats()
    receipts = item_state_receipts(
        [_helm()], {}, fight_duration_seconds=5.0, is_melee=True
    )
    row = next(row for row in receipts if row["item"] == HELM)
    assert row[HELPING_HAND_KEY] == pytest.approx(5.0)
    with pytest.raises(_MinionTargetUnavailable):
        _minion_fight(
            stats,
            items=(_helm(),),
            target_kind="minion",
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            target_armor=0.0,
        )


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
    item stays optimizer-eligible as stats_only with zero champion TDD."""
    coverage = item_model_coverage(_helm())
    assert coverage["status"] == "stats_only"
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert "minion" in coverage["reason"]
    assert "5 bonus physical damage" in coverage["reason"]


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
    previous_testing = app_module.app.config.get("TESTING")
    previous_rate = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["TESTING"] = True
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    try:
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
    finally:
        app_module.app.config["TESTING"] = previous_testing
        app_module.app.config["RATE_LIMIT_ENABLED"] = previous_rate
