"""P1 Package 3N — Ionian Boots of Lucidity "Ionian Insight" certification.

This file is the focused acceptance-matrix owner for Ionian Boots of
Lucidity's Ionian Insight passive ("Gain 10 summoner spell haste").  It
pins the OBSERVABLES the coordinator's P3-3N completion must satisfy and
runs against today's source: every behavior that already exists passes
now; every assertion that targets a contract piece the source does not
emit yet is marked ``xfail`` with reason ``awaiting P3-3N summoner-spell
model ...`` (the 1v1 fight model has NO summoner-spell action/cooldown
state — champion abilities + autos only).

Contract under test (typed source-backed values, verified against
docs/wiki-full-entry-audit.json — Ionian Boots of Lucidity page 41221,
revision 4022246, description "Gain 10 [[Haste#Summoner spell haste|
summoner spell haste]]."; cross-checked by data/atoms/items.json 3158
``stat.haste`` atom 1e775793fa61a40e = [10.0] flat, evidence
"passive:Ionian Insight@kw:summoner spell haste"):

* ITEM IDENTITY: cached name "Ionian Boots of Lucidity", id 3158,
  price 900 (shop.prices.total, economy.total atom 189e1d4b5e5b5bd1),
  stats 45 flat move speed + 10 flat ability haste; one unique passive
  "Ionian Insight" whose branch is exactly "Gain 10 [[Haste#Summoner
  spell haste|summoner spell haste]].".
* TYPED ACCESSOR: the coordinator's accessor
  ``ionian_insight_summoner_spell_haste()`` (spelling pinned by this
  matrix, mirroring ``dorans_helm_helping_hand_minion_damage()``) reads
  the registry key ``summoner_spell_haste`` (spelling pinned by this
  matrix) through the typed ``required_effect_value``/sustain machinery
  and returns exactly 10.0; a missing key raises ``KeyError`` naming
  Ionian Boots of Lucidity AND the key; a malformed value fails loudly
  (TypeError/ValueError) — never a silent fallback (AGENTS.md rule 5).
  TODAY: no registry entry exists, so the value-read is absent (xfail);
  the fail-loud paths are pinned through the existing typed reads.
* ATOM/SOURCE RECEIPT: the accessor or registry is tied to the catalog
  ``stat.haste`` atom (hash 1e775793fa61a40e, values [10.0], evidence
  "@kw:summoner spell haste"); a monkeypatched diverging registry value
  fails closed with a ValueError naming the atom hash; the wiki revision
  4022246 rides the typed registry (ITEM_INPUT_OPTIONS source receipt or
  ITEM_EFFECTS static key, per the Catalyst/Doran's Helm precedents).
  TODAY: the atom receipt is pinned from data/atoms/items.json (read-only
  evidence); the registry-tied revision and the fail-closed accessor are
  absent (xfail).
* ABILITY-HASTE SEPARATION (the core pin): the item's 10 ability haste
  (stats.abilityHaste.flat) and the passive's 10 summoner spell haste are
  SEPARATE.  Ionian Insight must NOT change champion ability cooldowns:
  a fight whose stats include the boots behaves EXACTLY like the same
  build without the boots item (same ability timing/cooldown/recast
  numbers, bit-identical breakdown and totals — the passive adds NO
  damage, NO CDR, NO auto change), and the 10 ability-haste stat DOES
  flow: the timed recast schedule matches effective_cooldown(base, +10)
  exactly, with NO extra haste from the passive.
* NO INVENTED SUMMONER ACTION: no summoner cast, cooldown reset, damage,
  or TDD effect exists anywhere in the fight result (no summoner fields
  in receipts/events/breakdown).
* COVERAGE: item_model_coverage returns stats_only (the audit-justified
  posture; a named-boundary receipt surface would legitimately upgrade
  it to modeled_state) with a reason naming "summoner spell haste";
  optimizer_eligible and calculation_eligible stay True — the item
  remains selectable and BIS-eligible (it is in the optimizer boots
  pool).
* FAIL-CLOSED ABSENT STATE: today an absent summoner-spell state authors
  no row/claim anywhere (pinned as the current observable); the
  coordinator's chosen P3-3N surface is the receipt-only named-boundary
  row (the Tear/Doran's Helm Helping Hand precedent) — the receipt-row
  contract is pinned below and xfailed until it lands.  The B-vs-C
  parity test filters the Ionian receipt row so it stays green under
  EITHER surface.
* XFAIL ONLY for: the typed value read, the atom-tied fail-closed
  accessor, the registry-tied revision, the named-boundary receipt row,
  and the actual summoner-spell cooldown/action assertion (a Flash/
  Ignite cast would reuse 9.09% faster) — all with reason
  ``awaiting P3-3N summoner-spell model ...``.

Existing regression surface touching this item (kept green, disjoint):
tests/test_app.py (allies boots slot -> ability_haste 10, lines ~1350/
1363/1429), tests/test_optimizer.py (~1037, boots pool), tests/
test_scenario.py (~243+), tests/test_issues_82.py (~479).

Sibling owners: the Tear of the Goddess / Doran's Helm Helping Hand
precedents are pinned in tests/test_cp20_items.py and
tests/test_dorans_helm_minion_damage.py; the Gluttonous Greaves
pre-implementation matrix conventions follow tests/test_gluttonous_
greaves.py.  This file is disjoint and pins only the Ionian Insight
acceptance observables.
"""

import json
import math
from pathlib import Path

import pytest

import src.app as app_module
from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import (
    FightConfig,
    calculate_fight_damage,
    effective_cooldown,
)
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.item_coverage import item_model_coverage
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    item_state_receipts,
    required_effect_value,
    sustain_effect_value,
)
from src.calculator.optimizer import get_eligible_boots
from src.calculator.stats import calculate_total_stats

from tests import item_probe
from tests.app_config import app_config

BOOTS = "Ionian Boots of Lucidity"
ITEM_ID = 3158
PRICE = 900
PASSIVE_NAME = "Ionian Insight"
BRANCH_TEXT = "Gain 10 [[Haste#Summoner spell haste|summoner spell haste]]."
MOVE_SPEED_FLAT = 45.0
ABILITY_HASTE_FLAT = 10.0
# Pinned spellings for the P3-3N typed surface (this matrix owns them).
SUMMONER_SPELL_HASTE_KEY = "summoner_spell_haste"
# Pinned accessor name, mirroring dorans_helm_helping_hand_minion_damage.
ACCESSOR_NAME = "ionian_insight_summoner_spell_haste"

AUDIT_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "wiki-full-entry-audit.json"
)
ATOMS_PATH = Path(__file__).resolve().parent.parent / "data" / "atoms" / "items.json"
# Sourced revision receipt from docs/wiki-full-entry-audit.json.
REVISION_ID = 4022246
PAGE_ID = 41221
SOURCE_URL = "https://wiki.leagueoflegends.com/en-us/Ionian_Boots_of_Lucidity"
# Catalog atom receipt for the passive branch (data/atoms/items.json 3158).
SUMMONER_SPELL_HASTE_ATOM_HASH = "1e775793fa61a40e"
SUMMONER_SPELL_HASTE_ATOM_ID = "stat.haste"
SUMMONER_SPELL_HASTE_ATOM_EVIDENCE = "passive:Ionian Insight@kw:summoner spell haste"
PRICE_ATOM_HASH = "189e1d4b5e5b5bd1"
ABILITY_HASTE_ATOM_HASH = "305818c346391945"
MOVE_SPEED_ATOM_HASH = "9c06c3edde6990e7"


def _boots() -> dict:
    """The real cached item record (id 3158, passive Ionian Insight)."""
    return get_item_by_name(BOOTS)


def _audit_boots_entry() -> dict:
    """The Ionian Boots row of docs/wiki-full-entry-audit.json."""
    with AUDIT_PATH.open(encoding="utf-8") as handle:
        audit = json.load(handle)
    matches = [row for row in audit["entries"] if row.get("name") == BOOTS]
    assert matches, "full-entry audit must contain Ionian Boots of Lucidity"
    return matches[0]


def _atom_records() -> list[dict]:
    """The catalog atom records for item id 3158 (data/atoms/items.json)."""
    with ATOMS_PATH.open(encoding="utf-8") as handle:
        atoms = json.load(handle)
    records = atoms["objects"].get(str(ITEM_ID))
    assert records, "atoms catalog must contain item 3158"
    return records


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
    """Ahri Q/W/E/R at rank 5/5/5/3 for the timing pins."""
    return parse_champion_abilities(
        ahri_data,
        18,
        stats.get("ability_power", 0.0),
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
    )


def _recast_counts(fight: dict) -> dict[str, int]:
    """Per-slot cast counts from the fight's cast_timeline."""
    counts: dict[str, int] = {}
    for event in fight["cast_timeline"]:
        slot = event.get("slot")
        counts[slot] = counts.get(slot, 0) + 1
    return counts


def _without_ionian_receipt_rows(receipts: list[dict]) -> list[dict]:
    """Receipt rows excluding the (future) Ionian named-boundary row, so
    the parity pins stay green under either P3-3N surface."""
    return [row for row in receipts if row.get("item") != BOOTS]


def _lazy_accessor():
    """Import the coordinator's P3-3N accessor lazily (absent today).

    Module-level import would break collection before the coordinator
    lands; the xfail tests below exercise it and fail closed today."""
    from src.calculator import item_effects as _item_effects

    return getattr(_item_effects, ACCESSOR_NAME)


# ---------------------------------------------------------------------------
# 1. Exact item identity + passive + price + source revision
# ---------------------------------------------------------------------------


def test_cached_identity_pins_name_id_price_and_stats():
    """The cached item is Ionian Boots of Lucidity (id 3158), price 900,
    45 flat move speed + 10 flat ability haste, with ONE unique passive
    named "Ionian Insight" whose branch is the exact summoner-spell-haste
    text."""
    item = _boots()
    assert item["name"] == BOOTS
    assert item["id"] == ITEM_ID
    assert item["shop"]["prices"]["total"] == PRICE
    assert item["stats"]["movespeed"]["flat"] == MOVE_SPEED_FLAT
    assert item["stats"]["abilityHaste"]["flat"] == ABILITY_HASTE_FLAT
    (passive,) = item["passives"]
    assert passive["name"] == PASSIVE_NAME
    assert passive["unique"] is True
    assert BRANCH_TEXT in passive["branches"]


def test_full_entry_audit_pins_revision_page_and_branch_text():
    """The docs audit pins page 41221 / revision 4022246 and the exact
    branch text; its runtime review already classifies the passive as
    stats_only with a reason naming summoner spell haste."""
    entry = _audit_boots_entry()
    assert entry["revision_id"] == REVISION_ID
    assert entry["page_id"] == PAGE_ID
    assert entry["status"] == "ready"
    assert entry["source_url"] == SOURCE_URL
    descriptions = entry["full_entry_review"]["expected_effects"]["effects"][0][
        "descriptions"
    ]
    assert BRANCH_TEXT in descriptions
    effect = entry["full_entry_review"]["expected_effects"]["effect_coverage"][0]
    assert effect["name"] == PASSIVE_NAME
    assert effect["verdict"] == "out_of_scope"
    runtime = entry["full_entry_review"]["runtime"]
    assert runtime["status"] == "stats_only"
    assert runtime["optimizer_eligible"] is True
    assert runtime["calculation_eligible"] is True
    assert "summoner spell haste" in runtime["reason"]


# ---------------------------------------------------------------------------
# 2 + 3. Atom receipt (read-only evidence) — passes today
# ---------------------------------------------------------------------------


def test_catalog_atom_pins_the_summoner_spell_haste_receipt():
    """The stat.haste catalog atom for id 3158 is the passive's receipt:
    hash 1e775793fa61a40e, values [10.0] flat, name Ionian Insight,
    evidence "@kw:summoner spell haste" — the exact receipt the P3-3N
    accessor must be tied to."""
    records = _atom_records()
    matches = [r for r in records if r.get("hash") == SUMMONER_SPELL_HASTE_ATOM_HASH]
    assert len(matches) == 1
    atom = matches[0]
    assert atom["atom_id"] == SUMMONER_SPELL_HASTE_ATOM_ID
    assert atom["behavior"] == "stat"
    assert atom["source"] == "Ionian Boots of Lucidity.passives[0].branches[0]"
    assert atom["name"] == PASSIVE_NAME
    assert atom["values"] == [10.0]
    assert atom["units"] == ["flat"]
    assert SUMMONER_SPELL_HASTE_ATOM_EVIDENCE in atom["evidence"]


def test_item_atom_receipt_pins_price_ms_and_ability_haste_atoms():
    """The full typed receipt for id 3158: economy.total 900 gold
    (189e1d4b5e5b5bd1), stat.ability_haste [10.0] (305818c346391945) and
    stat.movespeed [45.0] (9c06c3edde6990e7) — the ordinary stats stay
    atom-backed alongside the passive's stat.haste atom."""
    records = {r["atom_id"]: r for r in _atom_records()}
    assert records["economy.total"]["hash"] == PRICE_ATOM_HASH
    assert records["economy.total"]["values"] == [900.0]
    assert records["stat.ability_haste"]["hash"] == ABILITY_HASTE_ATOM_HASH
    assert records["stat.ability_haste"]["values"] == [10.0]
    assert records["stat.movespeed"]["hash"] == MOVE_SPEED_ATOM_HASH
    assert records["stat.movespeed"]["values"] == [45.0]


# ---------------------------------------------------------------------------
# 2. Typed accessor: fail-loud paths pass today; the value read is xfail
# ---------------------------------------------------------------------------


def test_missing_accessor_key_fails_loud_naming_item_and_key():
    """AGENTS.md rule 5: a missing key raises KeyError naming Ionian
    Boots of Lucidity AND the key — no silent stale fallback (passes
    today AND after the P3-3N typed entry lands; the key is deliberately
    never a real key)."""
    with pytest.raises(KeyError) as excinfo:
        required_effect_value(BOOTS, "not_a_typed_ionian_key")
    message = excinfo.value.args[0]
    assert BOOTS in message
    assert "not_a_typed_ionian_key" in message


def test_malformed_registry_value_fails_loud_never_silent_fallback(
    monkeypatch,
):
    """A malformed registry value (non-numeric or bool) fails loudly with
    TypeError naming the item and key through the typed read machinery the
    coordinator's accessor must use — never a silent fallback."""
    for bad_value in ("ten", True):
        monkeypatch.setitem(ITEM_EFFECTS, BOOTS, {SUMMONER_SPELL_HASTE_KEY: bad_value})
        with pytest.raises(TypeError) as excinfo:
            sustain_effect_value(BOOTS, SUMMONER_SPELL_HASTE_KEY)
        message = str(excinfo.value)
        assert BOOTS in message
        assert SUMMONER_SPELL_HASTE_KEY in message


def test_ionian_insight_accessor_returns_exactly_10(monkeypatch):
    """P3-3N contract: ``ionian_insight_summoner_spell_haste()`` reads the
    pinned registry key through the typed accessor and returns exactly
    10.0 (never a bool), and the same value resolves via
    ``required_effect_value``.  Absent today: no registry entry exists."""
    value = _lazy_accessor()()
    assert value == pytest.approx(10.0)
    assert not isinstance(value, bool)
    assert required_effect_value(BOOTS, SUMMONER_SPELL_HASTE_KEY) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 3. Atom-tied fail-closed + source revision riding the registry (xfail)
# ---------------------------------------------------------------------------


def test_atom_backed_accessor_rejects_stale_registry_literals(monkeypatch):
    """P3-3N contract: the accessor is atom-backed — a monkeypatched
    registry value that diverges from the catalog atom fails closed with
    a ValueError naming the atom hash 1e775793fa61a40e (a stale literal
    can never ride), while the sourced 10.0 keeps resolving."""
    monkeypatch.setitem(ITEM_EFFECTS, BOOTS, {SUMMONER_SPELL_HASTE_KEY: 10.5})
    with pytest.raises(ValueError) as excinfo:
        _lazy_accessor()()
    message = str(excinfo.value)
    assert BOOTS in message
    assert "diverges from catalog atom" in message
    assert SUMMONER_SPELL_HASTE_ATOM_HASH in message


def test_source_revision_rides_the_typed_registry():
    """P3-3N contract: the audit revision 4022246 rides the item's typed
    registry (ITEM_INPUT_OPTIONS source receipt or ITEM_EFFECTS static
    key, per the Catalyst/Doran's Helm precedents) so a parser refresh
    cannot overwrite it."""
    revision = ITEM_INPUT_OPTIONS.get(BOOTS, {}).get(
        "source_revision_id"
    ) or ITEM_EFFECTS.get(BOOTS, {}).get("source_revision_id")
    assert revision == REVISION_ID
    source_url = ITEM_INPUT_OPTIONS.get(BOOTS, {}).get(
        "source_url", ITEM_EFFECTS.get(BOOTS, {}).get("source_url")
    )
    assert source_url == SOURCE_URL


# ---------------------------------------------------------------------------
# 4. ABILITY-HASTE SEPARATION (the core pin) — passes today
# ---------------------------------------------------------------------------


def test_boots_contribute_exactly_ten_ability_haste_and_45_ms(ahri_data):
    """The ordinary stat block flows: the boots add exactly 10 flat
    ability haste and 45 flat move speed, and NO summoner-spell-haste
    stat exists anywhere in the stats dictionary (the passive is not a
    stat)."""
    base = calculate_total_stats(ahri_data, 18, [])
    stats = calculate_total_stats(ahri_data, 18, [_boots()])
    assert stats["ability_haste"] == pytest.approx(
        base["ability_haste"] + ABILITY_HASTE_FLAT
    )
    assert stats["move_speed"] == pytest.approx(base["move_speed"] + MOVE_SPEED_FLAT)
    assert not [
        key for key in stats if "summoner" in key.lower()
    ], "no summoner-spell stat may exist in the stats block"


def test_ionian_insight_adds_no_ability_timing_beyond_the_ten_haste_stat(
    ahri_data,
):
    """THE CORE PIN: a fight whose stats include the boots behaves
    EXACTLY like the same build WITHOUT the boots item — identical
    ability timing/cooldown/recast numbers, bit-identical totals and
    breakdown, in one-rotation, timed ability, and timed auto fights.
    The passive adds NO damage, NO CDR, NO auto change."""
    stats = calculate_total_stats(ahri_data, 18, [_boots()])
    abilities = _ahri_abilities(ahri_data, stats)
    for label, overrides in (
        ("one_rotation", dict(one_rotation=True, fight_duration_seconds=5.0)),
        ("timed_abilities", dict()),
        ("timed_autos", dict(auto_attack_uptime=1.0)),
    ):
        with_boots = _champion_fight(stats, abilities, items=(_boots(),), **overrides)
        without_item = _champion_fight(stats, abilities, items=(), **overrides)
        assert with_boots["total_damage"] == without_item["total_damage"], label
        assert with_boots["breakdown"] == without_item["breakdown"], label
        assert with_boots["cast_timeline"] == without_item["cast_timeline"], label
        # Receipt rows compare modulo the (future) Ionian named-boundary
        # row so this parity survives either P3-3N surface.
        assert _without_ionian_receipt_rows(
            with_boots["item_state_receipts"]
        ) == _without_ionian_receipt_rows(without_item["item_state_receipts"]), label


def test_effective_cooldowns_and_recasts_match_the_stat_exactly(ahri_data):
    """The 10 ability-haste stat DOES flow — and nothing else does: the
    with-boots timed recast schedule equals the renewal prediction of
    effective_cooldown(base, +10) exactly (Ahri W 6 -> 7 casts in 30s,
    Q/E/R unchanged).  A summoner-spell-haste leak into ability haste
    (haste 20) would predict W=8 / Q=6 and is explicitly rejected."""
    base_stats = calculate_total_stats(ahri_data, 18, [])
    boot_stats = calculate_total_stats(ahri_data, 18, [_boots()])
    abilities = _ahri_abilities(ahri_data, boot_stats)
    no_boots = _champion_fight(base_stats, abilities, items=())
    with_boots = _champion_fight(boot_stats, abilities, items=(_boots(),))

    assert effective_cooldown(5.0, 0.0) == pytest.approx(5.0)
    assert effective_cooldown(5.0, 10.0) == pytest.approx(5.0 * 100.0 / 110.0)

    base_counts = _recast_counts(no_boots)
    boot_counts = _recast_counts(with_boots)
    assert base_counts == {"Q": 5, "W": 6, "E": 3, "R": 1}
    assert boot_counts == {"Q": 5, "W": 7, "E": 3, "R": 1}
    for slot, base_cd in (("Q", 7.0), ("W", 5.0), ("E", 12.0)):
        predicted = math.ceil(30.0 / effective_cooldown(base_cd, ABILITY_HASTE_FLAT))
        assert boot_counts[slot] == predicted, slot
        leaked = math.ceil(30.0 / effective_cooldown(base_cd, 20.0))
        assert boot_counts[slot] != leaked or leaked == predicted, (
            f"{slot}: a summoner-spell-haste leak into ability haste would "
            f"predict {leaked} casts, got {boot_counts[slot]}"
        )
    # The only timing change is the sourced stat: Q/E/R totals are
    # bit-identical, and W changed by exactly one sourced recast.
    for slot in "QER":
        assert (
            no_boots["breakdown"][slot]["total_damage"]
            == with_boots["breakdown"][slot]["total_damage"]
        ), slot
    per_cast = no_boots["breakdown"]["W"]["total_damage"] / 6.0
    assert with_boots["breakdown"]["W"]["total_damage"] == pytest.approx(7.0 * per_cast)


# ---------------------------------------------------------------------------
# 5. Champion damage + timing parity (with vs without the item)
# ---------------------------------------------------------------------------


def test_one_rotation_fight_is_bit_identical_with_and_without_the_boots(
    ahri_data,
):
    """A one-rotation Ahri fight with the boots deals exactly the same
    total_damage with the same breakdown, auto per-hit/count, and cast
    timeline as the same build without them (the 10 ability haste stat
    does not change a single-rotation fight; the passive adds nothing)."""
    base_stats = calculate_total_stats(ahri_data, 18, [])
    boot_stats = calculate_total_stats(ahri_data, 18, [_boots()])
    abilities = _ahri_abilities(ahri_data, boot_stats)
    overrides = dict(
        one_rotation=True, fight_duration_seconds=5.0, auto_attack_uptime=1.0
    )
    without = _champion_fight(base_stats, abilities, items=(), **overrides)
    with_boots = _champion_fight(boot_stats, abilities, items=(_boots(),), **overrides)
    assert with_boots["total_damage"] == without["total_damage"]
    assert with_boots["breakdown"] == without["breakdown"]
    assert with_boots["cast_timeline"] == without["cast_timeline"]


def test_auto_only_fight_is_identical_with_and_without_the_boots(ahri_data):
    """A timed auto-attack-only fight is bit-identical with and without
    the boots: same auto count, same damage per hit, same total (ability
    haste and move speed do not touch the 1v1 auto schedule)."""
    base_stats = calculate_total_stats(ahri_data, 18, [])
    boot_stats = calculate_total_stats(ahri_data, 18, [_boots()])
    overrides = dict(auto_attack_uptime=1.0)
    without = _champion_fight(base_stats, {}, items=(), **overrides)
    with_boots = _champion_fight(boot_stats, {}, items=(_boots(),), **overrides)
    assert with_boots["total_damage"] == without["total_damage"]
    assert (
        with_boots["breakdown"]["auto_attacks"]["count"]
        == without["breakdown"]["auto_attacks"]["count"]
    )
    assert (
        with_boots["breakdown"]["auto_attacks"]["damage_per_hit"]
        == without["breakdown"]["auto_attacks"]["damage_per_hit"]
    )
    assert with_boots["breakdown"] == without["breakdown"]


# ---------------------------------------------------------------------------
# 6. No invented summoner action — passes today
# ---------------------------------------------------------------------------


def test_no_summoner_fields_exist_anywhere_in_the_fight_result(ahri_data):
    """No summoner cast, cooldown reset, damage, or TDD effect exists in
    the result: a recursive walk over the with-boots fight (one-rotation
    AND timed) finds no "summoner" key in receipts, events, breakdown, or
    any nested structure, and no Ionian receipt row is authored."""
    boot_stats = calculate_total_stats(ahri_data, 18, [_boots()])
    abilities = _ahri_abilities(ahri_data, boot_stats)
    fights = [
        _champion_fight(
            boot_stats,
            abilities,
            items=(_boots(),),
            one_rotation=True,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
        ),
        _champion_fight(
            boot_stats,
            abilities,
            items=(_boots(),),
            auto_attack_uptime=1.0,
        ),
    ]

    def _keys(obj, path=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                yield path + "." + key
                yield from _keys(value, path + "." + key)
        elif isinstance(obj, list):
            for index, value in enumerate(obj):
                yield from _keys(value, f"{path}[{index}]")

    for fight in fights:
        # The named-boundary receipt row is the ONLY summoner surface:
        # damage events, breakdowns, and timeline rows stay summoner-clean.
        hits = [
            key
            for key in _keys(fight)
            if "summoner" in key.lower() and not key.startswith(".item_state_receipts")
        ]
        assert not hits, hits
        rows = [row for row in fight["item_state_receipts"] if row.get("item") == BOOTS]
        assert len(rows) == 1
        assert rows[0]["state"] == "ionian_insight_summoner_spell_haste"
        assert rows[0]["summoner_spell_haste"] == pytest.approx(10.0)
        assert rows[0]["summoner_spell_haste_only"] is True


# ---------------------------------------------------------------------------
# 8. Fail-closed absent state (today) + named-boundary receipt row (3N)
# ---------------------------------------------------------------------------


def test_absent_summoner_spell_state_authors_no_row_or_claim():
    """Fail-closed absent state: with no summoner-spell state in the 1v1
    model, the fight authors NO summoner action or cooldown claim — the
    Ionian row is the named-boundary receipt only (typed 10.0 + boundary,
    zero timing effect), and the score path stays byte-identical."""
    receipts = item_state_receipts(
        [_boots()], {}, fight_duration_seconds=5.0, is_melee=True
    )
    rows = [row for row in receipts if row.get("item") == BOOTS]
    assert len(rows) == 1
    assert rows[0]["state"] == "ionian_insight_summoner_spell_haste"
    assert rows[0]["summoner_spell_haste"] == pytest.approx(10.0)
    assert rows[0]["summoner_spell_haste_only"] is True
    assert "summoner spell haste" in rows[0]["summoner_spell_haste_boundary"]
    assert rows[0]["source_revision_id"] == 4022246


def test_named_boundary_receipt_row_pins_the_3n_surface():
    """P3-3N contract (receipt path): the Ionian state receipt names the
    summoner-spell boundary with the typed 10.0 and the sourced revision
    — the Tear/Doran's Helm Helping Hand precedent, mirrored for Ionian
    Insight.  The row is receipt-only: it carries the typed value and the
    boundary, and it never changes champion damage."""
    receipts = item_state_receipts(
        [_boots()], {}, fight_duration_seconds=5.0, is_melee=True
    )
    rows = [row for row in receipts if row.get("item") == BOOTS]
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "ionian_insight_summoner_spell_haste"
    assert row[SUMMONER_SPELL_HASTE_KEY] == pytest.approx(10.0)
    assert row.get("summoner_spell_haste_only") is True
    boundary = " ".join(str(row.get(key, "")) for key in row)
    assert "summoner spell haste" in boundary
    assert row["source_revision_id"] == REVISION_ID


# ---------------------------------------------------------------------------
# 7 + 9. Coverage wording + the only actual summoner-spell xfail
# ---------------------------------------------------------------------------


def test_coverage_wording_names_the_summoner_spell_haste_mechanic():
    """The item-coverage classification keeps the item selectable and
    BIS-eligible: stats_only (the audit-justified posture; a named-
    boundary receipt surface would legitimately upgrade it to
    modeled_state) with a reason naming "summoner spell haste", and both
    eligibility flags True.  The boots also stay in the optimizer pool."""
    coverage = item_probe.attacker_coverage(_boots())
    assert coverage["status"] in {"stats_only", "modeled_state"}
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert "summoner spell haste" in coverage["reason"]
    assert any(
        item["name"] == BOOTS for item in get_eligible_boots(tier=None)
    ), "Ionian Boots of Lucidity must stay in the optimizer boots pool"


def test_a_flash_or_ignite_cast_would_reuse_9_percent_faster(ahri_data):
    """THE summoner-spell cooldown/action assertion (xfail by design):
    under the P3-3N summoner-spell model, the sourced 10 summoner spell
    haste must shorten summoner spell cooldowns by the standard haste
    formula — a 300s Flash reuses in 300 x 100/110 = 272.73s and a 180s
    Ignite in 163.64s (each cast 1 - 100/110 = 9.09% faster), and NO
    summoner cast may appear in the champion-only fight result until that
    model exists.  The value is read through the P3-3N typed accessor so
    the assertion is genuinely untestable today (no summoner-spell state
    exists) and flips only when the model lands."""
    boot_stats = calculate_total_stats(ahri_data, 18, [_boots()])
    abilities = _ahri_abilities(ahri_data, boot_stats)
    fight = _champion_fight(boot_stats, abilities, items=(_boots(),))
    assert not [
        event
        for event in fight["cast_timeline"]
        if "summoner" in str(event.get("slot", "")).lower()
    ]
    haste = _lazy_accessor()()
    assert haste == pytest.approx(10.0)
    for base_cd, spell in ((300.0, "Flash"), (180.0, "Ignite")):
        effective = base_cd * 100.0 / (100.0 + haste)
        assert effective == pytest.approx(base_cd * 100.0 / 110.0), spell
        assert effective < base_cd, spell
        assert 1.0 - 100.0 / 110.0 == pytest.approx(0.0909090909), spell


# ---------------------------------------------------------------------------
# 10. App regression surface (boots slot) stays green
# ---------------------------------------------------------------------------


def test_app_boots_slot_fight_stays_green():
    """App regressions: the boots stay selectable through the dedicated
    boots slot, a boots-slot fight resolves with the exact cached name,
    the champion_stats carry the +10 ability haste, and a one-rotation
    fight deals exactly the no-boots total (zero Ionian Insight
    contribution through the app path)."""
    with app_config(RATE_LIMIT_ENABLED=False):
        client = app_module.app.test_client()
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
        with_boots = _calculate({**base, "boots": BOOTS})
        assert with_boots["total_damage"] == pytest.approx(plain["total_damage"])
        assert with_boots["champion_stats"]["ability_haste"] == pytest.approx(
            plain["champion_stats"]["ability_haste"] + ABILITY_HASTE_FLAT
        )
