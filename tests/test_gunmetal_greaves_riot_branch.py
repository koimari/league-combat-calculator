"""P1 Package 3O — Gunmetal Greaves (3172) "Noxian Gait" Riot-only branch
certification.

This file is the focused acceptance-matrix owner for Gunmetal Greaves'
Noxian Gait passive.  It pins the OBSERVABLES the coordinator's P3-3O
completion must satisfy and runs against today's source: every behavior
that already exists passes now; every assertion that targets a contract
piece the source does not emit yet is marked ``xfail`` with reason
``awaiting P3-3O ...``.

Contract under test (current runtime facts, verified before pinning):

* ITEM IDENTITY: cached name "Gunmetal Greaves", id 3172, price 1100
  (shop.prices.total), tier 3 BOOTS, classic SR 5v5 mode only
  (aram/nb/ar = false), midlane-quest acquisition.  Stats: 40 flat
  attack speed, 45 flat move speed, 5% life steal.  NOTE: the cache
  stats block carries ``lifesteal.flat = 0`` — the effective 5.0 is the
  typed sustain entry (``ITEM_EFFECTS``), and this matrix pins the
  effective 5.0 through the typed accessor/stat path.
* PASSIVE: the parsed wiki branch carries NO magnitude — the cached item
  has ``passives == []`` and the only branch text is Riot's description:
  "Attacks against Champions grant Move Speed On-Hit decaying over
  2 seconds." (passive name "Noxian Gait").  The docs full-entry audit
  (page 1675881, revision 4013706, status ready) records ZERO effect
  branches for the item.
* TYPED LIFESTEAL: ``required_effect_value("Gunmetal Greaves",
  "lifesteal_percent") == 5.0``; a missing key raises ``KeyError``
  naming Gunmetal Greaves AND the key; the source receipt
  (``source_revision_id`` 4013706 + ``source_url``) is discoverable
  through the typed registry (ITEM_EFFECTS static keys /
  ``sustain_stat_receipt``) — AGENTS.md rule 5, no silent fallbacks.
* ORDINARY STATS PARITY: equipping the boots yields exactly +40% attack
  speed, +45 move speed, +5% lifesteal vs the bare build; NO change to
  ability haste, damage, or any other stat.  Fights are bit-identical
  (total_damage / breakdown / cast_timeline / damage_events) against a
  synthetic build that already has exactly those stats.
* NO DIRECT DAMAGE: Noxian Gait adds no damage/AS/LS/AH/TDD packet:
  with-vs-without boots fights show zero direct contribution beyond the
  ordinary stats; no "Noxian"/movement breakdown row; no
  movement-speed field in fight results; ``resolve_damage_effects``
  ``per_hits`` stays empty (no on-hit movement compiled).
* THE RIOT-ONLY BOUNDARY: no Riot mode/map admission exists — the
  passive is not compiled into any packet; the movement magnitude is
  UNSOURCED (no numeric magnitude exists in the cached wiki branch or
  riotDescription — the typed registry must NOT invent one).  The
  decay duration 2.0s IS sourced (riotDescription "decaying over 2
  seconds", binary-confirmed by ``data/bin/items.bin.json``
  16.15.8024387 ``Items/3172`` mDataValues ``Duration = 2.0``).  The
  binary-only magnitude (``MeleeMS`` 0.15 / ``RangedMSMultiplier``
  0.667) stays OUT of the registry: the wiki cache is authoritative
  (docs/item-source-reconciliation.md section 1, wiki rev 4013706) and
  records no branch.
* TYPED BOUNDARY RECEIPT (P3-3O surface, absent today → xfail): the
  coordinator's completion adds ONE ``item_state_receipts`` row
  ``state == "noxian_gait_boundary"`` carrying
  ``noxian_gait_decay_seconds 2.0``,
  ``noxian_gait_champions_only True``,
  ``noxian_gait_magnitude_unsourced True`` (or the coordinator's named
  field), a boundary string naming "Riot-only" + the missing magnitude +
  the absent movement model, and ``source_revision_id 4013706``.
* FAIL-CLOSED ABSENT STATE: no authored Noxian Gait input exists (no
  ITEM_INPUT_OPTIONS option); the absent state authors NO claim about
  movement speed/spacing/magnitude; fabricated input options are
  rejected ("Unknown item option target" / "Unknown option").
* COVERAGE: ``item_model_coverage`` returns the justified posture
  (modeled_effect or stats_only) with a reason naming "Noxian Gait"
  AND the boundary ("Riot-only" / "out of scope"); optimizer_eligible
  + calculation_eligible stay True; the boots stay in the eligible
  boots pool; outcome_dimensions ("movement",) unchanged.
* XFAIL ONLY for: the named-boundary receipt row and the actual
  movement-state assertion (a champion-targeted auto would grant the
  sourced move speed decaying over 2s) — both ``awaiting P3-3O
  movement-state model ...``.

Sibling owners: the Ionian Insight precedent is pinned in
``tests/test_ionian_boots_summoner_haste.py`` (same receipt-only
named-boundary shape); the Doran's Helm Helping Hand precedent is
pinned in ``tests/test_dorans_helm_minion_damage.py``; the typed
lifesteal receipt is pinned in ``tests/test_issues_45_43.py``
(LIFESTEAL_PINS "Gunmetal Greaves": (5.0, 4013706)).  Existing
regression surface touching this item (kept green, disjoint):
``tests/test_app.py`` (boots slot ~2046), ``tests/test_issues_82.py``
(~100+ tier contract), ``tests/test_item_coverage.py`` (~202), and
``tests/test_issues_45_43.py`` (~87).  This file is disjoint and pins
only the Gunmetal Greaves acceptance observables.
"""

import json
import re
from pathlib import Path

import pytest

import src.app as app_module
from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_coverage import item_model_coverage
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    grouped_sustain_stat_percent,
    item_input_options_meta,
    item_state_receipts,
    required_effect_value,
    resolve_damage_effects,
    sustain_effect_value,
    sustain_stat_receipt,
    validate_item_input_options,
)
from src.calculator.item_source import (
    ACKNOWLEDGED_SOURCE_CONFLICTS,
    item_source_audit,
    riot_declared_effects,
)
from src.calculator.optimizer import get_eligible_boots
from src.calculator.stats import calculate_total_stats

BOOTS = "Gunmetal Greaves"
ITEM_ID = 3172
PRICE = 1100
PASSIVE_NAME = "Noxian Gait"
# Normalized (tag-stripped) branch text; the cached wiki carries no branch,
# so the only branch text is Riot's description — with NO numeric magnitude.
BRANCH_TEXT = (
    "Attacks against Champions grant Move Speed On-Hit decaying over 2 seconds."
)
ATTACK_SPEED_FLAT = 40.0
MOVE_SPEED_FLAT = 45.0
LIFESTEAL_PERCENT = 5.0
NOXIAN_GAIT_DECAY_SECONDS = 2.0
# Sourced revision receipt (docs/wiki-full-entry-audit.json AND the typed
# sustain entry share the same wiki revision 4013706).
REVISION_ID = 4013706
PAGE_ID = 1675881
SOURCE_URL = "https://wiki.leagueoflegends.com/en-us/Gunmetal_Greaves"

AUDIT_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "wiki-full-entry-audit.json"
)
BINARY_ITEMS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "bin" / "items.bin.json"
)


def _boots() -> dict:
    """The real cached item record (id 3172)."""
    return get_item_by_name(BOOTS)


def _audit_entry() -> dict:
    """The Gunmetal Greaves row of docs/wiki-full-entry-audit.json."""
    with AUDIT_PATH.open(encoding="utf-8") as handle:
        audit = json.load(handle)
    matches = [row for row in audit["entries"] if row.get("name") == BOOTS]
    assert matches, "full-entry audit must contain Gunmetal Greaves"
    return matches[0]


def _binary_item() -> dict:
    """The parsed game-file record Items/3172 (16.15.8024387)."""
    with BINARY_ITEMS_PATH.open(encoding="utf-8") as handle:
        binary = json.load(handle)
    record = binary.get("Items/3172")
    assert record, "data/bin/items.bin.json must contain Items/3172"
    return record


def _normalized_branch_text(riot_description: str) -> str:
    """Strip Riot's markup from the Noxian Gait branch sentence."""
    branch = riot_description.split("<passive>Noxian Gait</passive>", 1)[1]
    branch = branch.split("</mainText>", 1)[0]
    branch = re.sub(r"<[^>]+>", "", branch)
    return " ".join(branch.split())


def _champion_fight(stats, abilities=None, *, items=(), **overrides) -> dict:
    """One champion-target fight through the public engine."""
    config = {
        "target_health": 5000.0,
        "target_armor": 50.0,
        "target_magic_resistance": 50.0,
        "fight_duration_seconds": 30.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": False,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(
        stats, abilities or {}, list(items), FightConfig(**config)
    )


def _ahri_abilities(ahri_data, stats):
    """Ahri Q/W/E/R at rank 5/5/5/3 for the timed parity pins."""
    return parse_champion_abilities(
        ahri_data,
        18,
        stats.get("ability_power", 0.0),
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
    )


def _stat_deltas(base: dict, equipped: dict) -> dict[str, float]:
    """Every stat that changed between two total-stat bundles."""
    return {
        key: equipped[key] - base[key] for key in equipped if equipped[key] != base[key]
    }


def _recursive_keys(obj, path=""):
    """Yield every nested key path of a fight result."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield f"{path}.{key}"
            yield from _recursive_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from _recursive_keys(value, f"{path}[{index}]")


def _movement_keys(fight: dict) -> list[str]:
    """Key paths mentioning movement / Noxian Gait in one fight result,
    excluding the named-boundary receipt row (its field names are the
    boundary contract, not a movement mechanism)."""
    needles = ("movement", "move_speed", "noxian", "gait")
    return [
        key
        for key in _recursive_keys(fight)
        if any(needle in key.lower() for needle in needles)
        and not key.startswith(".item_state_receipts")
    ]


def _gunmetal_receipt_rows(receipts: list[dict]) -> list[dict]:
    """The Gunmetal Greaves rows of an item-state receipt ledger."""
    return [row for row in receipts if row.get("item") == BOOTS]


# ---------------------------------------------------------------------------
# 1. Exact item identity / stats / passive (no magnitude anywhere)
# ---------------------------------------------------------------------------


def test_cached_identity_pins_name_id_price_stats_and_passive():
    """The cached item is Gunmetal Greaves (id 3172), price 1100, 40 flat
    attack speed + 45 flat move speed, classic-SR mode only, tier 3 boots.
    The cache stats block carries lifesteal.flat = 0 (the effective 5.0 is
    the typed sustain entry), the parsed wiki branch list is EMPTY, and the
    ONLY branch text is Riot's Noxian Gait description with no magnitude."""
    item = _boots()
    assert item["name"] == BOOTS
    assert item["id"] == ITEM_ID
    assert item["shop"]["prices"]["total"] == PRICE
    assert item["tier"] == 3
    assert "BOOTS" in item["rank"]
    assert item["stats"]["attackSpeed"]["flat"] == ATTACK_SPEED_FLAT
    assert item["stats"]["movespeed"]["flat"] == MOVE_SPEED_FLAT
    assert item["stats"]["lifesteal"]["flat"] == 0.0  # cache-block note
    assert item["stats"]["lifesteal"]["percent"] == LIFESTEAL_PERCENT
    assert item["stats"]["abilityHaste"]["flat"] == 0.0
    assert item["modes"]["classic sr 5v5"] is True
    assert item["modes"]["aram"] is False
    # No parsed wiki branch exists at all — no magnitude can ride the cache.
    assert item["passives"] == []
    description = item["riotDescription"]
    assert f"<passive>{PASSIVE_NAME}</passive>" in description
    assert _normalized_branch_text(description) == BRANCH_TEXT
    # The branch sentence carries NO numeric magnitude (no % token, and no
    # number directly preceding "Move Speed"); "2 seconds" is the decay
    # duration, pinned separately as the sourced 2.0s.
    branch = _normalized_branch_text(description)
    assert not re.search(r"\d+(?:\.\d+)?\s*%", branch)
    assert not re.search(r"\d+\s+Move Speed", branch)


def test_full_entry_audit_pins_revision_page_and_zero_branch_receipt():
    """The docs audit pins page 1675881 / revision 4013706 (status ready),
    records ZERO effect branches for the item, and classifies the runtime
    posture as modeled_effect with the Noxian Gait boundary named."""
    entry = _audit_entry()
    assert entry["revision_id"] == REVISION_ID
    assert entry["page_id"] == PAGE_ID
    assert entry["status"] == "ready"
    assert entry["source_url"] == SOURCE_URL
    review = entry["full_entry_review"]
    assert review["expected_effects"]["effect_count"] == 0
    assert review["expected_effects"]["effects"] == []
    runtime = review["runtime"]
    assert runtime["status"] == "modeled_effect"
    assert runtime["optimizer_eligible"] is True
    assert runtime["calculation_eligible"] is True
    assert runtime["outcome_dimensions"] == ["movement"]
    assert runtime["registry_effect_type"] == "sustain"
    assert "Noxian Gait" in runtime["reason"]
    assert "Riot-only" in runtime["reason"]


# ---------------------------------------------------------------------------
# 2. Typed lifesteal: value, fail-loud, source receipt (all pass today)
# ---------------------------------------------------------------------------


def test_typed_lifesteal_reads_exactly_5_and_aggregates_into_stats():
    """The effective 5.0 lifesteal is the typed sustain entry: the typed
    accessors return exactly 5.0 (never a bool), the grouped sustain path
    sums it, and stats.py folds it into the loadout lifesteal_percent."""
    assert required_effect_value(BOOTS, "lifesteal_percent") == pytest.approx(5.0)
    value = sustain_effect_value(BOOTS, "lifesteal_percent")
    assert value == pytest.approx(5.0)
    assert not isinstance(value, bool)
    assert grouped_sustain_stat_percent(
        [_boots()], "lifesteal_percent"
    ) == pytest.approx(5.0)
    stats = calculate_total_stats(get_champion("Ahri"), 18, [_boots()])
    assert stats["lifesteal_percent"] == pytest.approx(5.0)


def test_missing_lifesteal_key_fails_loud_naming_item_and_key():
    """AGENTS.md rule 5: a missing key raises KeyError naming Gunmetal
    Greaves AND the key — no silent stale fallback.  The key is
    deliberately never a real key, so this passes today AND after P3-3O."""
    with pytest.raises(KeyError) as excinfo:
        required_effect_value(BOOTS, "not_a_typed_gunmetal_key")
    message = excinfo.value.args[0]
    assert BOOTS in message
    assert "not_a_typed_gunmetal_key" in message


def test_lifesteal_source_receipt_rides_the_typed_registry():
    """The typed registry owns the lifesteal receipt: ITEM_EFFECTS static
    keys carry source_revision_id 4013706 + source_url, and
    sustain_stat_receipt exposes them — a parser refresh cannot overwrite
    them (the registry entry is code-owned)."""
    effect = ITEM_EFFECTS[BOOTS]
    assert effect["lifesteal_percent"] == pytest.approx(5.0)
    assert effect["source_revision_id"] == REVISION_ID
    assert effect["source_url"] == SOURCE_URL
    receipt = sustain_stat_receipt(BOOTS, "lifesteal_percent")
    assert receipt["value"] == pytest.approx(5.0)
    assert receipt["source_revision_id"] == REVISION_ID
    assert receipt["source_url"] == SOURCE_URL


# ---------------------------------------------------------------------------
# 3. Ordinary stats parity (pass today)
# ---------------------------------------------------------------------------


def test_equipping_the_boots_yields_exactly_the_three_sourced_stats(ahri_data):
    """Equipping Gunmetal Greaves changes EXACTLY four numeric stats:
    bonus_attack_speed +40, attack_speed +0.25 (= AS ratio 0.625 x 40%),
    move_speed +45, lifesteal_percent +5 — and NOTHING else (no ability
    haste, no damage stat, no resist, no mana...)."""
    base = calculate_total_stats(ahri_data, 18, [])
    stats = calculate_total_stats(ahri_data, 18, [_boots()])
    deltas = _stat_deltas(base, stats)
    assert deltas == {
        "attack_speed": 0.25,
        "bonus_attack_speed": 40.0,
        "lifesteal_percent": 5.0,
        "move_speed": 45.0,
    }
    assert stats["attack_speed"] - base["attack_speed"] == pytest.approx(
        base["attack_speed_ratio"] * ATTACK_SPEED_FLAT / 100.0
    )
    assert stats["ability_haste"] == base["ability_haste"]


def test_fights_are_bit_identical_against_a_synthetic_build_with_those_stats(
    ahri_data,
):
    """THE CORE PIN: a fight whose stats come from the real boots is
    BIT-IDENTICAL (total_damage, breakdown, cast_timeline, damage_events,
    receipts) to a fight whose stats were built by adding exactly the
    three sourced stat deltas to the bare bundle with NO item equipped —
    in one-rotation, timed-ability, and timed-auto fights.  The boots item
    itself contributes nothing beyond its ordinary stats."""
    base = calculate_total_stats(ahri_data, 18, [])
    with_boots = calculate_total_stats(ahri_data, 18, [_boots()])
    synthetic = dict(base)
    for key, delta in (
        ("attack_speed", 0.25),
        ("bonus_attack_speed", 40.0),
        ("lifesteal_percent", 5.0),
        ("move_speed", 45.0),
    ):
        synthetic[key] = synthetic[key] + delta
    assert synthetic == with_boots  # the synthetic bundle IS the boot bundle
    abilities = _ahri_abilities(ahri_data, with_boots)
    for label, overrides in (
        ("one_rotation", dict(one_rotation=True, fight_duration_seconds=5.0)),
        ("timed_abilities", dict()),
        ("timed_autos", dict(auto_attack_uptime=1.0)),
    ):
        with_item = _champion_fight(
            with_boots, abilities, items=(_boots(),), **overrides
        )
        without_item = _champion_fight(synthetic, abilities, items=(), **overrides)
        assert with_item["total_damage"] == without_item["total_damage"], label
        assert with_item["breakdown"] == without_item["breakdown"], label
        assert with_item["cast_timeline"] == without_item["cast_timeline"], label
        assert with_item["damage_events"] == without_item["damage_events"], label
        # The ONLY receipt delta is the Gunmetal noxian_gait_boundary row.
        without_receipts = [
            row
            for row in without_item["item_state_receipts"]
            if row.get("item") != BOOTS
        ]
        with_receipts = [
            row for row in with_item["item_state_receipts"] if row.get("item") != BOOTS
        ]
        assert with_receipts == without_receipts, label
        gait_rows = [
            row for row in with_item["item_state_receipts"] if row.get("item") == BOOTS
        ]
        assert len(gait_rows) == 1
        assert gait_rows[0]["state"] == "noxian_gait_boundary"
        assert gait_rows[0]["noxian_gait_magnitude_unsourced"] is True


# ---------------------------------------------------------------------------
# 4. Noxian Gait adds NO damage / breakdown row / movement field
# ---------------------------------------------------------------------------


def test_noxian_gait_adds_no_direct_damage_beyond_the_ordinary_stats(ahri_data):
    """With-vs-without the boots item at equal stats: zero direct-damage
    contribution.  No "Noxian"/movement breakdown row exists, the
    breakdown is identical, and no movement-speed field appears anywhere
    in the fight result (one-rotation AND timed)."""
    base = calculate_total_stats(ahri_data, 18, [])
    with_boots = calculate_total_stats(ahri_data, 18, [_boots()])
    abilities = _ahri_abilities(ahri_data, with_boots)
    fights = [
        _champion_fight(
            with_boots,
            abilities,
            items=(_boots(),),
            one_rotation=True,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
        ),
        _champion_fight(
            with_boots,
            abilities,
            items=(_boots(),),
            auto_attack_uptime=1.0,
        ),
    ]
    for fight in fights:
        assert not [
            key
            for key in fight["breakdown"]
            if "Noxian" in key or "Gait" in key or "movement" in key.lower()
        ]
        # The receipt row carries the boundary field names; everything
        # else (breakdown, events, timeline) stays movement-clean.
        assert _movement_keys(fight) == [], _movement_keys(fight)
        # The only sustain surface is the typed lifesteal row (healing,
        # not damage) — the boots add no damage packet.
        assert (
            fight["breakdown"].get("heal_lifesteal", {}).get("total_amount", 0.0) > 0.0
        )


# ---------------------------------------------------------------------------
# 5. The Riot-only / map boundary: no admission, no packet, no magnitude
# ---------------------------------------------------------------------------


def test_the_passive_is_not_compiled_into_any_damage_packet():
    """resolve_damage_effects compiles the sustain-type entry to NOTHING:
    per_hits (and every other effect family) stays empty — no on-hit
    movement, no damage, no spellblade, no burn, no active."""
    resolved = resolve_damage_effects([_boots()])
    assert resolved.per_hits == ()
    assert resolved.spellblade is None
    assert resolved.burns == ()
    assert resolved.actives == ()
    assert resolved.first_autos == ()
    assert resolved.damage_amplifiers == ()
    assert resolved.execute is None
    assert resolved.conditional_notes == ()


def test_no_riot_map_or_mode_admission_exists_for_the_branch():
    """The branch is Riot-only: Riot's description declares Noxian Gait,
    the cached wiki carries NO branch to admit, and the source audit keeps
    the divergence as an acknowledged conflict naming "Riot-only" and the
    missing magnitude — there is no mode/map gate that admits the passive
    into any packet."""
    item = _boots()
    assert riot_declared_effects(item) == (PASSIVE_NAME,)
    assert item["passives"] == []
    audit = item_source_audit(item)
    conflicts = [c for c in audit["conflicts"] if c["effect"] == PASSIVE_NAME]
    assert len(conflicts) == 1
    assert conflicts[0]["status"] == "explained"
    assert conflicts[0]["acknowledged"] is True
    note = ACKNOWLEDGED_SOURCE_CONFLICTS[BOOTS][PASSIVE_NAME]
    assert "Riot-only" in note
    assert "magnitude" in note


def test_the_movement_magnitude_is_unsourced_and_the_registry_invents_none():
    """No numeric magnitude exists in the cached wiki branch (there is no
    branch) or the riotDescription sentence, and the typed registry MUST
    NOT invent one: the ITEM_EFFECTS entry carries the 3O typed key set
    (type / lifesteal_percent / the three noxian_gait boundary keys /
    source_url / source_revision_id) with NO movement-speed magnitude
    key, and a fabricated magnitude key read fails loud naming
    item+key."""
    item = _boots()
    assert item["passives"] == []
    branch = _normalized_branch_text(item["riotDescription"])
    assert not re.search(r"\d+(?:\.\d+)?\s*%", branch)
    assert not re.search(r"\d+\s+Move Speed", branch)
    effect = ITEM_EFFECTS[BOOTS]
    assert set(effect) <= {
        "type",
        "lifesteal_percent",
        "noxian_gait_decay_seconds",
        "noxian_gait_champions_only",
        "noxian_gait_magnitude_unsourced",
        "source_url",
        "source_revision_id",
    }
    assert not [
        key
        for key in effect
        if any(
            needle in key.lower()
            for needle in ("move_speed", "speed_percent", "bonus_move", "gait_")
        )
        and key
        not in {
            "noxian_gait_decay_seconds",
            "noxian_gait_champions_only",
            "noxian_gait_magnitude_unsourced",
        }
    ]
    with pytest.raises(KeyError) as excinfo:
        required_effect_value(BOOTS, "noxian_gait_move_speed_percent")
    message = excinfo.value.args[0]
    assert BOOTS in message
    assert "noxian_gait_move_speed_percent" in message


def test_decay_duration_is_sourced_and_binary_confirmed():
    """The 2.0s decay IS sourced: riotDescription says "decaying over 2
    seconds" and the parsed game files (data/bin/items.bin.json
    16.15.8024387, Items/3172) confirm Duration = 2.0.  The binary-only
    magnitude (MeleeMS 0.15, RangedMSMultiplier 0.667, MSAmount
    calculation) is NOT wiki-sourced and stays out of the registry."""
    item = _boots()
    branch = _normalized_branch_text(item["riotDescription"])
    assert "decaying over 2 seconds" in branch
    record = _binary_item()
    values = {v["mName"]: v["mValue"] for v in record["mDataValues"]}
    assert values["Duration"] == pytest.approx(NOXIAN_GAIT_DECAY_SECONDS)
    # Recorded as evidence, never sourced: the magnitude exists only in
    # the binary, and the wiki cache (the authoritative source) has none.
    assert values["MeleeMS"] == pytest.approx(0.15)
    assert values["RangedMSMultiplier"] == pytest.approx(0.667)


# ---------------------------------------------------------------------------
# 6. Typed boundary receipt (P3-3O surface — absent today, xfail)
# ---------------------------------------------------------------------------


def test_named_boundary_receipt_row_pins_the_3o_surface():
    """P3-3O contract (receipt path): item_state_receipts emits exactly ONE
    Gunmetal Greaves row, state "noxian_gait_boundary", carrying the
    sourced 2.0s decay, the champions-only restriction, the
    magnitude-unsourced flag, a boundary string naming Riot-only + the
    missing magnitude + the absent movement model, and revision 4013706.
    Absent today: no row exists (the fail-closed pin below stays green
    under either surface)."""
    receipts = item_state_receipts(
        [_boots()], {}, fight_duration_seconds=5.0, is_melee=True
    )
    rows = _gunmetal_receipt_rows(receipts)
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "noxian_gait_boundary"
    assert row["noxian_gait_decay_seconds"] == pytest.approx(NOXIAN_GAIT_DECAY_SECONDS)
    assert row["noxian_gait_champions_only"] is True
    assert row["noxian_gait_magnitude_unsourced"] is True
    boundary = " ".join(str(row.get(key, "")) for key in row)
    assert "Riot-only" in boundary
    assert "magnitude" in boundary
    assert "movement model" in boundary
    assert row["source_revision_id"] == REVISION_ID


def test_absent_state_authors_no_fight_claim_today(ahri_data):
    """Fail-closed absent state: with no Noxian Gait state in the 1v1
    model, the fight authors NO movement/noxian row or claim anywhere —
    no movement key in the fight result, no movement event in
    damage_events/control_events/cast_timeline.  The ONLY permitted
    Gunmetal surface is the (future) named-boundary receipt row, which
    carries the magnitude-unsourced flag and zero movement mechanics; the
    score path stays byte-identical (verified by the parity pins)."""
    with_boots = calculate_total_stats(ahri_data, 18, [_boots()])
    abilities = _ahri_abilities(ahri_data, with_boots)
    for fight in (
        _champion_fight(
            with_boots,
            abilities,
            items=(_boots(),),
            one_rotation=True,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
        ),
        _champion_fight(with_boots, abilities, items=(_boots(),)),
    ):
        assert _movement_keys(fight) == [], _movement_keys(fight)
        assert not [
            event
            for event in fight.get("control_events", [])
            if "movement" in str(event).lower()
        ]
        rows = _gunmetal_receipt_rows(fight["item_state_receipts"])
        # Either the absent state (no rows) or the named boundary row —
        # never an invented magnitude claim.
        if rows:
            assert len(rows) == 1
            assert rows[0]["state"] == "noxian_gait_boundary"
            assert rows[0]["noxian_gait_magnitude_unsourced"] is True


# ---------------------------------------------------------------------------
# 7. Fail-closed absent input options (pass today)
# ---------------------------------------------------------------------------


def test_no_authored_noxian_gait_input_option_exists():
    """No Noxian Gait scenario control is authored: Gunmetal Greaves'
    ITEM_INPUT_OPTIONS entry is the source-only receipt (no option
    schemas), so the metadata exposes no controls and the absent state
    authors NO claim about movement speed/spacing/magnitude."""
    config = ITEM_INPUT_OPTIONS.get("Gunmetal Greaves", {})
    assert set(config) <= {"source_url", "source_revision_id"}
    assert config.get("source_revision_id") == 4013706
    meta = item_input_options_meta().get("Gunmetal Greaves", {})
    assert meta.get("options") == {}


def test_fabricated_input_options_are_rejected_fail_closed():
    """Unknown item option targets are rejected with "Unknown item option
    target", and an unknown option under a real item is rejected with
    "Unknown option" — the fail-closed behavior for the absent Noxian
    Gait state."""
    with pytest.raises(ValueError) as excinfo:
        validate_item_input_options({"Gunmetal Greaves": {"noxian_gait_seconds": 2.0}})
    assert "Unknown option" in str(excinfo.value)
    assert "Gunmetal Greaves" in str(excinfo.value)
    # Empty options for the source-only item are the absent state: the
    # no-op parse succeeds and authors no control.
    assert validate_item_input_options({"Gunmetal Greaves": {}}) == {
        "Gunmetal Greaves": {}
    }
    with pytest.raises(ValueError) as excinfo:
        validate_item_input_options({"Dark Seal": {"noxian_gait_seconds": 2}})
    assert "Unknown option" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 8. Coverage wording + eligibility (pass today)
# ---------------------------------------------------------------------------


def test_coverage_wording_names_the_boundary_and_keeps_the_boots_eligible():
    """item_model_coverage returns the justified posture (modeled_effect
    or stats_only) with a reason naming "Noxian Gait" AND the boundary
    ("Riot-only" / "out of scope"); both eligibility flags stay True; the
    boots remain in the eligible boots pool (tier 3); outcome_dimensions
    stays ("movement",)."""
    coverage = item_model_coverage(_boots())
    assert coverage["status"] in {"modeled_effect", "stats_only"}
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert coverage["outcome_dimensions"] == ["movement"]
    assert "Noxian Gait" in coverage["reason"]
    assert any(
        token in coverage["reason"]
        for token in ("Riot-only", "out of scope", "no movement model")
    )
    assert any(
        item["name"] == BOOTS for item in get_eligible_boots(tier=None)
    ), "Gunmetal Greaves must stay in the optimizer boots pool"
    assert any(
        item["name"] == BOOTS for item in get_eligible_boots(tier=3)
    ), "Gunmetal Greaves must stay in the tier-3 quest boots pool"


# ---------------------------------------------------------------------------
# 9. The ONLY actual movement-state xfail
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="awaiting P3-3O movement-state model ...")
def test_a_champion_targeted_auto_would_grant_move_speed_decaying_over_2s(
    ahri_data,
):
    """THE movement-state assertion (xfail by design): under the P3-3O
    movement-state model, each basic attack against a CHAMPION target
    grants the sourced move-speed buff decaying over exactly
    noxian_gait_decay_seconds (2.0s), and NO such event exists in a fight
    today.  The model must source its magnitude from the P3-3O receipt
    (unsourced today), scope the proc to champion targets only, and emit
    one movement event per qualifying auto with the sourced decay."""
    with_boots = calculate_total_stats(ahri_data, 18, [_boots()])
    abilities = _ahri_abilities(ahri_data, with_boots)
    fight = _champion_fight(
        with_boots,
        abilities,
        items=(_boots(),),
        fight_duration_seconds=5.0,
        auto_attack_uptime=1.0,
    )
    movement = [
        event
        for event in fight.get("control_events", [])
        if "movement" in str(event).lower()
    ]
    assert movement, "a champion-targeted auto must grant the sourced move speed"
    assert all(
        event.get("duration", 0.0) == pytest.approx(NOXIAN_GAIT_DECAY_SECONDS)
        for event in movement
    )
    # The magnitude rides the P3-3O receipt; today it is unsourced, so the
    # model cannot exist until the receipt lands.
    receipts = _gunmetal_receipt_rows(fight["item_state_receipts"])
    assert len(receipts) == 1
    assert receipts[0]["noxian_gait_magnitude_unsourced"] is True


# ---------------------------------------------------------------------------
# 10. Existing regression surface stays green (app path)
# ---------------------------------------------------------------------------


def test_app_boots_slot_and_picker_stay_green():
    """App regressions: the boots stay selectable through /api/boots, a
    mid-quest-complete boots-slot fight resolves with exactly the sourced
    stats (+40% AS via attack_speed, +45 MS, +5% lifesteal, no ability
    haste change), and the one-rotation total is identical to the no-boots
    total (zero Noxian Gait contribution).  The combat utility-outcomes
    ledger carries the movement dimension ONLY as a declared-but-never-
    applied block (event_count 0, speed_percent_seconds 0,
    applied_dimensions empty) with the Noxian Gait boundary reason riding
    the item_coverage row — no movement mechanic is applied anywhere."""
    previous_testing = app_module.app.config.get("TESTING")
    previous_rate = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["TESTING"] = True
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    try:
        client = app_module.app.test_client()
        assert BOOTS in {item["name"] for item in client.get("/api/boots").get_json()}
        base = {
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "role": "mid",
            "target_health": 5000,
            "target_armor": 50,
            "target_mr": 50,
            "fight_mode": "one_rotation",
            "fight_duration": 5,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        }

        def _calculate(payload):
            response = client.post("/api/calculate", json=payload)
            assert response.status_code == 200, response.get_json()
            return response.get_json()

        plain = _calculate(base)
        with_boots = _calculate(
            {**base, "role": "mid", "role_quest_complete": True, "boots": BOOTS}
        )
        assert with_boots["champion_stats"]["attack_speed"] == pytest.approx(
            plain["champion_stats"]["attack_speed"] + 0.25
        )
        assert with_boots["champion_stats"]["move_speed"] == pytest.approx(
            plain["champion_stats"]["move_speed"] + MOVE_SPEED_FLAT
        )
        assert with_boots["champion_stats"]["lifesteal_percent"] == pytest.approx(
            plain["champion_stats"]["lifesteal_percent"] + LIFESTEAL_PERCENT
        )
        assert with_boots["champion_stats"]["ability_haste"] == pytest.approx(
            plain["champion_stats"]["ability_haste"]
        )
        assert with_boots["total_damage"] == pytest.approx(plain["total_damage"])
        # The utility-outcomes ledger is the ONLY movement surface in the
        # combat path, and it is a declared-but-unapplied dimension: zero
        # events, zero speed-percent-seconds, empty applied_dimensions, and
        # the item_coverage row carrying the Noxian Gait boundary reason.
        ledger = with_boots["combat"]["utility_outcomes"]["participants"]["main"]
        assert ledger["dimensions"] == ["movement"]
        assert ledger["applied_dimensions"] == []
        assert ledger["movement"] == {"event_count": 0, "speed_percent_seconds": 0}
        row = next(entry for entry in ledger["item_coverage"] if entry["name"] == BOOTS)
        assert "Noxian Gait" in row["reason"]
        assert "Riot-only" in row["reason"]
        # No actual movement mechanic fires in damage events or the score
        # path: the engine result (pinned elsewhere) has zero movement keys,
        # and the combat damage events carry none either.
        assert not [
            event
            for event in with_boots["combat"].get("damage_events", [])
            if "movement" in str(event).lower()
        ]
    finally:
        app_module.app.config["TESTING"] = previous_testing
        app_module.app.config["RATE_LIMIT_ENABLED"] = previous_rate
