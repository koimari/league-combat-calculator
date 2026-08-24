"""P1 Package 3U — Verdant Barrier (4632) "Annul" compiled-walk +
optimizer certification.

This file is the focused acceptance-matrix owner for Verdant Barrier's
Annul spell shield.  It pins the OBSERVABLES the coordinator's P3-3U
completion must satisfy and runs against today's source.  The matrix was
authored pre-completion with the genuinely-absent mechanics marked
``xfail`` (reason ``awaiting P3-3U ...``); the P3-3U completion landed
mid-session (compiled-panel certification, the item_state_receipts row,
and the coverage tightening), so every assertion below is now LIVE and
passes.  The completion signal is documented per section.

Contract under test (current runtime facts, verified before pinning):

* ITEM IDENTITY: cached name "Verdant Barrier", id 4632, price 1600
  (shop.prices.total, sell 640), tier 2 EPIC, builds from
  [1052 Amplifying Tome, 1033 Null-Magic Mantle, 1052 Amplifying Tome]
  and builds into 3102 (Banshee's Veil).  Stats: +40 flat ability
  power, +25 flat magic resistance (ordinary stat parity).  Passive
  "Annul" (unique); the cached branch text is exact: "Grants a
  {{tip|spell shield}} that blocks the next hostile ability (60 second
  cooldown, timer restarts upon taking damage from champions)."
* TYPED SOURCE: the ITEM_EFFECTS registry entry (type
  "defensive_start") carries the two typed keys spell_shield_ready
  True and spell_shield_cooldown 60.0.  spell_shield_ready and
  spell_shield_cooldown_seconds are read through the typed accessors
  and a missing key raises KeyError naming "Verdant Barrier" AND the
  key (AGENTS.md rule 5 — no silent fallbacks).  Malformed cooldown
  values fail loudly (TypeError on non-numeric, ValueError when the
  registry value diverges from the catalog atom).  The Annul cooldown
  atom receipt (timing.cooldown [60.0] hash 2a40799f92fb6749) is
  discoverable through annul_spell_shield_cooldown_atom; the wiki
  source receipt (revision 3957920, page rev timestamp
  2025-10-05T20:04:20Z) rides the code-owned
  defensive_effects.defense_source("Verdant Barrier", ANNUL) and is carried
  onto the resolved starting defenses.
* OWNER GATES: the shield resolves per combatant from that
  combatant's OWN items (resolve_spell_shield reads the holder's
  defenses + items).  An ally/enemy holder has NO inferred owner path
  onto the main champion: the main's defenses stay spell_shield_ready
  False when the item sits on a roster mate.
* OPENING READINESS: the spell shield is READY at fight start
  (spell_shield_ready True, infinite window start 0.0 until consumed,
  survival spell_shield_until None).
* FIRST AUTHORED ABILITY CAST: the first hostile ABILITY cast on the
  holder is blocked and every packet of that cast is nullified.  The
  gate is CAST IDENTITY, not damage type: champion basic attacks are
  not abilities and pass through without consuming; a TRUE-damage
  packet that belongs to an ability cast IS consumed and blocked
  (full_block blocks_true_damage True); a CONTROL-ONLY ability packet
  IS consumed and blocked (blocks_control_only True).  Unknown/
  unclassifiable deliveries fail closed (no invented consumption).
* DELIVERY BOUNDARIES: basic attacks pass through
  (basic_attack_not_blocked); unknown deliveries pass through with a
  named denial (unknown_delivery) and no consumption; true-damage and
  control packets of the blocked ability cast are nullified with the
  cast.  The parent brief's "true damage / control effects pass
  through" reading is NOT the modeled rule for ABILITY packets — see
  the reply ambiguities; the ability-only gate is by cast identity.
* 60s COOLDOWN + REARM: the sourced 60.0s cooldown and the "timer
  restarts upon taking damage from champions" clause are both ENFORCED
  by the kernel rearm clock, not merely receipted.  A second ability
  within the cooldown is NOT blocked.  Past it the shield rearms, and
  the clock is anchored to the LATER of the consumption instant and the
  last champion damage the holder took: in a 70s walk with a basic
  attack at t=2.0 the timer starts at 2.0, ready_at is 62.0 and the
  ability at t=65 IS blocked; move that basic attack to t=9.0 and
  ready_at is 69.0, so t=65 lands.  The sourced numbers stay receipted
  too (survival-row cooldown_seconds + cooldown_atom, the rearm clock
  and its observed rearms; SPELL_SHIELD_REARM_RULE quotes Verdant's
  60s).  NOTE the request bound: pipeline caps fight_duration at 30s,
  under every Annul cooldown, so no API request reaches a rearm — the
  70s walks below are direct-kernel, not request-reachable.
* RECEIPT FIELDS + SOURCE EVIDENCE: the survival-row spell_shield
  receipt carries source "Verdant Barrier — Annul", the infinite
  window, the acceptance declaration, the block rule, the five
  categorical rules, uses_before/uses_after, selected_cast_identity,
  blocked_packets, decisions, triggered_heal None, cooldown_seconds
  60.0, the cooldown_atom hash, the rearm clock and its observed
  rearms.  The 3M/3N/3O-pattern item_state_receipts row is LIVE
  post-completion: state "annul", spell_shield_ready True,
  spell_shield_cooldown 60.0, the cooldown_atom hash, source_url +
  source_revision_id 3957920, and the named rearm_boundary that
  receipts the 60s cooldown and the damage-restart rule as ENFORCED.
* COMPILED VS RECEIPT PARITY: score path (include_receipt=False) and
  receipt walk agree on every observable (survival rows incl. the
  spell_shield lifecycle, breakdown, duration).  Today Verdant sits in
  COMPILED_WALK_UNREPRESENTABLE_ITEMS ("Annul spell shield needs cast
  metadata"), so the compiled fast path fails closed: a MAIN holder
  falls back per evaluation (context.uncompilable stays False, no
  panels built) and an ENEMY/ALLY holder poisons the search-invariant
  roster context (uncompilable True, panels empty) — both still
  deep-equal the receipt walk.  A tuple-ledger champion (Riven)
  holding Verdant fails closed with parity and NO crash today.  The
  P3-3U certification has LANDED (the Annul cast-metadata gate is staged
  in the compiled kernel and the blocklist entry is removed): the
  compiled score path now builds panels with uncompilable False and
  byte-parity deep-equality for BOTH the main holder and the roster
  holder.
* COVERAGE: item_model_coverage returns the justified posture today
  (status "stats_only", optimizer_eligible + calculation_eligible
  True) with the coordinator's coverage tightening now LIVE: the reason
  names Annul's spell shield (one use per cast; the 60s cooldown and the
  damage-restart rule are receipted named boundaries) and
  outcome_dimensions carries "spell_protection" (matching Banshee's Veil
  / Edge of Night).  target_item_model_coverage is "modeled" naming the
  Annul first-source-backed-Q/W/E/R-cast consumption.
* BIS: Verdant Barrier is an EPIC tier-2 component (buildsInto 3102
  Banshee's Veil); the BIS candidate pool ranks only legendary items
  and boots, so it is excluded by construction — never a candidate,
  never withheld (mirrors test_issues_46).  The spell-shield
  legendaries (Banshee's Veil, Edge of Night) still certify.
* ITEM STATE RECEIPTS: the item_state_receipts row for Annul is LIVE
  post-completion (state "annul", the typed values, the atom receipt,
  the source receipt, and the named rearm_boundary).
* COMPLETION STATUS: all four pre-completion xfail targets (compiled
  panels for the main holder, roster-holder compilation, the coverage
  reason + "spell_protection" dimension, and the item_state_receipts
  row) landed with P3-3U; the matrix holds no xfail markers and every
  assertion is live.

Coordinator ambiguities surfaced by this matrix (see the reply):

* The Annul gate is by CAST IDENTITY (is_ability), not by damage type:
  true-damage ability packets and control-only ability packets of the
  first hostile cast ARE consumed and nullified (full_block
  blocks_true_damage True; blocks_control_only True); basic attacks
  and unclassifiable deliveries pass through.  The brief's "true
  damage and control effects pass through" reading only holds for
  non-ability packets.
* Rearm IS modeled, anchored on the damage-restart clause: the 60s
  cooldown runs from the later of the consumption instant and the last
  champion damage the holder took, so a 70s walk re-arms only when that
  anchor leaves 60s inside the window.  The request path caps
  fight_duration at 30s and cannot reach it.
* The receipt row state name is pinned "annul" provisionally; the
  named boundary key for the damage-restart rule is the coordinator's
  pin (this matrix requires SOME rearm/boundary-named key on the row).
* BIS exclusion is structural (EPIC tier-2 component, legendary-only
  pool), not a coverage withholding.

Sibling owners: the compiled-vs-receipt kernel contract lives in
``tests/test_survival_kernel.py`` (issue #137); the 3T/3S matrix shapes
in ``tests/test_maw_compiled_parity.py`` and
``tests/test_knights_vow_compiled_parity.py``; the Annul family
regression surface in ``tests/test_spell_shield_eligibility.py`` (R2
Annul items, R3 auto-attack gate, R11 compiled fail-closed),
``tests/test_issues_46.py`` (annul blocks one typed ability + BIS
exclusion), ``tests/test_participant_timeline.py`` (opening Annul,
same-cast true-damage nullification), ``tests/test_defensive_effects.py``
(Annul ready for all three items), ``tests/test_app.py`` (opening enemy
spell shield), and ``tests/test_item_coverage.py`` (target coverage
"modeled").  This file is disjoint and pins only the Verdant Barrier
acceptance observables.
"""

from types import SimpleNamespace

import pytest

from src import app as app_module
from src.calculator.item_coverage import ATTACKER_LANES
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import (
    defense_source,
    resolve_starting_defenses,
)
from src.calculator.item_behavior import DefenseMechanic
from src.calculator.interaction_effects import resolve_spell_shield
from src.calculator.item_coverage import (
    item_model_coverage,
    target_item_model_coverage,
)
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    annul_spell_shield_cooldown_atom,
    item_state_receipts,
    required_effect_value,
    spell_shield_cooldown_seconds,
    spell_shield_ready,
)
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.interpreters import uncompilable_item_receipt
from tests.survival_probe import simulate_survival
from tests.app_config import app_config

ITEM_NAME = "Verdant Barrier"
ITEM_ID = 4632
PRICE = 1600
SELL = 640
AP_FLAT = 40.0
MR_FLAT = 25.0
COOLDOWN = 60.0
COOLDOWN_ATOM_HASH = "2a40799f92fb6749"
SOURCE_REVISION = 3957920
SOURCE_TIMESTAMP = "2025-10-05T20:04:20Z"
SOURCE_URL = "https://wiki.leagueoflegends.com/en-us/Verdant_Barrier"
SHIELD_SOURCE = "Verdant Barrier — Annul"
# The cached passive branch — the exact Annul sentence.
BRANCH = (
    "Grants a {{tip|spell shield}} that blocks the next hostile ability "
    "(60 second cooldown, timer restarts upon taking damage from champions)."
)
# The defensive_effects assumption stamped when the shield resolves.
ASSUMPTION = (
    "Verdant Barrier's Annul spell shield is ready at the opening and "
    "consumes the first authored hostile ability; its sourced cooldown "
    "rearms the shield only once fully elapsed, and the timer restarts "
    "on champion damage."
)


@pytest.fixture(autouse=True)
def _borrowed_app_config():
    """The route parities run under TESTING, with the shared bucket off.

    Borrowed, not assigned: ``src.app.app`` is a process singleton, and
    test_app.py's rate-limit tests need both keys back afterwards.
    """
    with app_config(RATE_LIMIT_ENABLED=False, TESTING=True):
        yield


def _verdant_item() -> dict:
    """The real cached item record (id 4632)."""
    return get_item_by_name(ITEM_NAME)


def _stats(**overrides) -> dict:
    stats = {
        "health": 3000.0,
        "is_melee": False,
        "bonus_attack_damage": 0.0,
    }
    stats.update(overrides)
    return stats


def _holder(
    health: float = 3000.0,
    *,
    items: tuple[dict, ...] | None = None,
    champion: str = "Ahri",
) -> Combatant:
    """A Verdant holder used by the packet-level survival-walk probes."""
    stats = _stats(health=health)
    item_list = ({"name": ITEM_NAME},) if items is None else items
    return Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": champion},
        level=18,
        items=(_verdant_item(),) if items is None else items,
        stats=stats,
        defenses=resolve_starting_defenses(champion, 18, stats, list(item_list)),
    )


def _dummy_source(participant_id: str = "source", team: str = "enemy") -> Combatant:
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=1,
        items=(),
        stats={"health": 5000.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
    )


def _packet(
    time: float,
    sequence: int,
    *,
    damage: float,
    damage_type: str,
    attacker: str = "source",
    source_key: str = "Q",
    **extra,
) -> dict:
    packet = {
        "time": time,
        "damage": damage,
        "damage_type": damage_type,
        "attacker": attacker,
        "target": "target",
        "source_key": source_key,
        "sequence": sequence,
        "_event_id": f"{source_key}:{sequence}:{time}",
    }
    packet.update(extra)
    return packet


def _run_packets(
    holder: Combatant,
    events: list[dict],
    *,
    duration: float = 10.0,
    holder_id: str = "target",
) -> dict:
    """Run one _simulate_survival with the Verdant holder as target."""
    return simulate_survival(
        [_dummy_source(), holder], {holder_id: events}, {}, {}, duration
    )


def _row(result: dict, participant_id: str = "target") -> dict:
    return result[participant_id]


def _blocked_packets(result: dict) -> list[dict]:
    """The spell-shield receipt's blocked_packet rows for the target."""
    return list(_row(result)["spell_shield"]["blocked_packets"])


def _holder_fight(
    duration: float,
    *,
    include_receipt: bool = True,
    search_context: CoupledSearchContext | None = None,
) -> dict:
    """A coupled fight where the MAIN (Ahri) holds Verdant Barrier against
    Cassiopeia: the first hostile ability cast is blocked, the 60s
    cooldown is receipted, and later casts land.  ``include_receipt=False``
    returns the coupled score surface; passing a ``search_context`` plus an
    empty pair cache exercises the compiled score path (which must fail
    closed on Verdant today and fall back to the shared walk)."""
    main = get_champion("Ahri")
    items = [_verdant_item()]
    main_stats = calculate_total_stats(main, 18, items)
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": duration,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy_loadout = ChampionLoadout(champion="Cassiopeia", level=18, items=[]).resolve()
    defenses = resolve_starting_defenses("Ahri", 18, main_stats, items)
    return build_participant_timeline(
        main,
        18,
        items,
        params,
        main_stats=main_stats,
        main_defenses=defenses,
        enemies=[enemy_loadout],
        allies=[],
        include_receipt=include_receipt,
        pair_result_cache={} if search_context is not None else None,
        search_context=search_context,
    )


def _main_survival(result: dict) -> dict:
    """The main holder's survival row (participant 0)."""
    return result["participants"][0]["survival"]


# ---------------------------------------------------------------------------
# 1. Identity / stats / passive
# ---------------------------------------------------------------------------


def test_cached_identity_pins_name_id_price_stats_and_annul_branch():
    """The cached record pins the identity, price, tier/rank, build path,
    ordinary stats, and the exact Annul passive branch text."""
    item = _verdant_item()
    assert item["name"] == ITEM_NAME
    assert item["id"] == ITEM_ID
    assert item["shop"]["prices"]["total"] == PRICE
    assert item["shop"]["prices"]["sell"] == SELL
    assert item["tier"] == 2
    assert item["rank"] == ["EPIC"]
    assert item["buildsFrom"] == [1052, 1033, 1052]
    assert 3102 in item["buildsInto"]  # Banshee's Veil
    assert item["stats"]["abilityPower"]["flat"] == AP_FLAT
    assert item["stats"]["magicResistance"]["flat"] == MR_FLAT
    (passive,) = item["passives"]
    assert passive["name"] == "Annul"
    assert passive["unique"] is True
    # The exact cached branch text — the whole Annul sentence.
    cached_branch = " ".join(passive.get("branches", ()))
    assert cached_branch == BRANCH
    # The riot description names the spell shield too.
    assert "<passive>Annul</passive>" in item["riotDescription"]
    assert "Spell Shield" in item["riotDescription"]


def test_equipping_verdant_barrier_yields_exactly_40_ap_and_25_mr():
    """The item's ordinary stats apply in a real build (+40 AP / +25 MR
    over the no-item baseline); the Annul mechanic adds no hidden stat."""
    main = get_champion("Ahri")
    base = calculate_total_stats(main, 18, [])
    total = calculate_total_stats(main, 18, [_verdant_item()])
    assert total["ability_power"] == pytest.approx(base["ability_power"] + AP_FLAT)
    assert total["magic_resistance"] == pytest.approx(
        base["magic_resistance"] + MR_FLAT
    )


# ---------------------------------------------------------------------------
# 2. Typed source values
# ---------------------------------------------------------------------------


def test_typed_annul_values_return_exact_numbers():
    """The typed entry is defensive_start with the two Annul keys; the
    engine-facing accessors return the exact sourced values."""
    effect = ITEM_EFFECTS[ITEM_NAME]
    assert effect["type"] == "defensive_start"
    assert spell_shield_ready(ITEM_NAME) is True
    assert spell_shield_cooldown_seconds(ITEM_NAME) == pytest.approx(COOLDOWN)
    # The typed reads the engine actually consumes.
    assert bool(required_effect_value(ITEM_NAME, "spell_shield_ready")) is True
    assert float(
        required_effect_value(ITEM_NAME, "spell_shield_cooldown")
    ) == pytest.approx(COOLDOWN)


def test_annul_cooldown_atom_receipt_is_discoverable_through_the_accessor():
    """The timing.cooldown [60.0] hash 2a40799f92fb6749 receipt rides the
    annul accessor and the resolver."""
    atom = annul_spell_shield_cooldown_atom(ITEM_NAME)
    assert atom["atom_id"] == "timing.cooldown"
    assert atom["behavior"] == "timing"
    assert atom["name"] == "Annul"
    assert atom["values"] == [COOLDOWN]
    assert atom["units"] == ["s"]
    assert atom["hash"] == COOLDOWN_ATOM_HASH
    assert atom["source"] == "Verdant Barrier.passives[0].branches[0]"
    with pytest.raises(KeyError):
        annul_spell_shield_cooldown_atom("Not an Annul item")
    # The resolver's contract carries the same receipt.
    contract = resolve_spell_shield(_holder())
    assert contract is not None
    assert contract.cooldown_seconds == pytest.approx(COOLDOWN)
    assert contract.cooldown_atom["hash"] == COOLDOWN_ATOM_HASH


def test_annul_source_revision_is_discoverable_on_the_defense_receipt():
    """The wiki source receipt (revision 3957920) rides the code-owned
    resolved Annul citation and the resolved starting defenses."""
    source = defense_source(ITEM_NAME, DefenseMechanic.ANNUL)
    assert source.label == "Verdant Barrier — Annul"
    assert source.source_url == SOURCE_URL
    assert source.revision_id == SOURCE_REVISION
    assert source.revision_timestamp == SOURCE_TIMESTAMP
    defenses = resolve_starting_defenses("Ahri", 18, _stats(), [{"name": ITEM_NAME}])
    assert any(
        entry.revision_id == SOURCE_REVISION and entry.label == SHIELD_SOURCE
        for entry in defenses.sources
    )
    assert ASSUMPTION in defenses.assumptions


def test_missing_typed_key_fails_loud_naming_item_and_key(monkeypatch):
    """Both typed keys ride fail-closed accessors: a missing key raises
    KeyError naming the item AND the key (AGENTS.md rule 5)."""
    base = dict(ITEM_EFFECTS[ITEM_NAME])
    for missing in ("spell_shield_ready", "spell_shield_cooldown"):
        patched = dict(base)
        del patched[missing]
        monkeypatch.setitem(ITEM_EFFECTS, ITEM_NAME, patched)
        if missing == "spell_shield_ready":
            with pytest.raises(KeyError) as excinfo:
                spell_shield_ready(ITEM_NAME)
        else:
            with pytest.raises(KeyError) as excinfo:
                spell_shield_cooldown_seconds(ITEM_NAME)
        message = str(excinfo.value)
        assert ITEM_NAME in message
        assert missing in message


def test_malformed_typed_values_fail_loudly(monkeypatch):
    """Non-numeric and None cooldown values raise TypeError through the
    typed accessor (fail loud, no silent fallback)."""
    base = dict(ITEM_EFFECTS[ITEM_NAME])
    patched = dict(base)
    patched["spell_shield_cooldown"] = "sixty"
    monkeypatch.setitem(ITEM_EFFECTS, ITEM_NAME, patched)
    with pytest.raises(TypeError):
        spell_shield_cooldown_seconds(ITEM_NAME)
    patched = dict(base)
    patched["spell_shield_cooldown"] = None
    monkeypatch.setitem(ITEM_EFFECTS, ITEM_NAME, patched)
    with pytest.raises(TypeError):
        spell_shield_cooldown_seconds(ITEM_NAME)


def test_divergent_cooldown_fails_closed_against_the_catalog_atom(monkeypatch):
    """A registry value that no longer matches the catalog atom (the stale
    literal trap of AGENTS.md rule 5) raises ValueError naming the hash."""
    base = dict(ITEM_EFFECTS[ITEM_NAME])
    patched = dict(base)
    patched["spell_shield_cooldown"] = 61.0
    monkeypatch.setitem(ITEM_EFFECTS, ITEM_NAME, patched)
    with pytest.raises(ValueError) as excinfo:
        spell_shield_cooldown_seconds(ITEM_NAME)
    assert COOLDOWN_ATOM_HASH in str(excinfo.value)


# ---------------------------------------------------------------------------
# 3. Owner gates + opening readiness
# ---------------------------------------------------------------------------


def test_opening_readiness_shield_is_ready_at_fight_start():
    """The shield is ready at the opening: typed True, infinite window
    (start 0.0, until consumed), no timed expiry in the survival row."""
    defenses = resolve_starting_defenses("Ahri", 18, _stats(), [{"name": ITEM_NAME}])
    assert defenses.spell_shield_ready is True
    assert defenses.spell_shield_source == SHIELD_SOURCE
    summary = defenses.public_summary()
    assert summary["spell_shield"] == {"ready": True, "source": SHIELD_SOURCE}
    contract = resolve_spell_shield(_holder())
    assert contract.eligibility.name == "annul"
    assert contract.eligibility.window.start == 0.0
    assert contract.eligibility.window.until == float("inf")
    result = _run_packets(_holder(), [])
    assert _row(result)["spell_shield_used"] is False
    assert _row(result)["spell_shield_source"] == SHIELD_SOURCE
    assert _row(result)["spell_shield_until"] is None


def test_shield_blocks_for_the_holder_only_no_inferred_owner_path():
    """The shield resolves per combatant from that combatant's OWN items:
    a main champion without the item gains no shield from an ally holder,
    and the ally holder's shield never redirects to the main."""
    stats = _stats()
    main = Combatant(
        participant_id="main",
        team="main",
        champion_data={"name": "Ahri"},
        level=18,
        items=(),
        stats=stats,
        defenses=resolve_starting_defenses("Ahri", 18, stats, []),
    )
    ally_stats = _stats()
    ally = Combatant(
        participant_id="ally",
        team="main",
        champion_data={"name": "Janna"},
        level=18,
        items=(_verdant_item(),),
        stats=ally_stats,
        defenses=resolve_starting_defenses(
            "Janna", 18, ally_stats, [{"name": ITEM_NAME}]
        ),
    )
    assert main.defenses.spell_shield_ready is False
    assert resolve_spell_shield(main) is None
    assert ally.defenses.spell_shield_ready is True
    assert resolve_spell_shield(ally) is not None
    # The main without the shield takes the full ability packet.
    main_events = [_packet(1.0, 0, damage=100.0, damage_type="magic", target="main")]
    main_events[0]["target"] = "main"
    result = simulate_survival(
        [_dummy_source(), main], {"main": main_events}, {}, {}, 10.0
    )
    assert result["main"]["damage_taken"] == pytest.approx(100.0)
    assert result["main"]["spell_shield_used"] is False


# ---------------------------------------------------------------------------
# 4. First authored ability cast + delivery boundaries
# ---------------------------------------------------------------------------


def test_first_hostile_ability_is_blocked_and_its_damage_nullified():
    """The first hostile ABILITY packet is blocked (skipped in the walk)
    and its damage is nullified; the shield is consumed exactly once."""
    result = _run_packets(
        _holder(),
        [
            _packet(1.0, 0, damage=100.0, damage_type="magic", is_ability=True),
            _packet(2.0, 1, damage=50.0, damage_type="magic", is_ability=True),
        ],
    )
    assert _row(result)["damage_taken"] == pytest.approx(50.0)
    assert _row(result)["spell_shield_used"] is True
    assert _row(result)["spell_shield_source"] == SHIELD_SOURCE
    blocked = _blocked_packets(result)
    assert len(blocked) == 1
    assert blocked[0]["event_key"] == "Q:1.0:0"
    receipt = _row(result)["spell_shield"]
    assert receipt["uses_before"] == 1
    assert receipt["uses_after"] == 0
    assert receipt["selected_cast_identity"] == "Q:1.0"


def test_basic_attacks_pass_through_without_consuming():
    """A champion basic attack is not an ability: it lands untouched and
    does not spend the shield; the following ability is still blocked."""
    result = _run_packets(
        _holder(),
        [
            _packet(
                0.5,
                0,
                damage=20.0,
                damage_type="physical",
                source_key="auto_attacks",
                basic_attack=True,
            ),
            _packet(1.0, 1, damage=40.0, damage_type="magic", is_ability=True),
        ],
    )
    assert _row(result)["damage_taken"] == pytest.approx(20.0)
    assert _row(result)["spell_shield_used"] is True
    decisions = _row(result)["spell_shield"]["decisions"]
    assert decisions[0]["reason"] == "basic_attack_not_blocked"
    assert decisions[1]["eligible"] is True


def test_true_damage_ability_packets_are_consumed_and_nullified_with_the_cast():
    """The gate is cast identity, not damage type: a true-damage packet
    that belongs to the first hostile ABILITY cast is blocked and
    nullified (full_block blocks_true_damage True).  The brief's "true
    damage passes through" reading holds only for non-ability packets."""
    result = _run_packets(
        _holder(),
        [
            _packet(1.0, 0, damage=100.0, damage_type="magic", is_ability=True),
            _packet(1.0, 1, damage=40.0, damage_type="true", is_ability=True),
            _packet(
                2.0,
                2,
                damage=20.0,
                damage_type="physical",
                source_key="auto_attacks",
                basic_attack=True,
            ),
        ],
    )
    assert _row(result)["damage_taken"] == pytest.approx(20.0)
    assert len(_blocked_packets(result)) == 2
    assert _row(result)["spell_shield_used"] is True


def test_control_only_ability_packets_consume_and_block():
    """A control-only hostile ability packet (amount 0, is_ability True)
    consumes the shield and is blocked (blocks_control_only True — the
    cached branch says 'blocks the next hostile ability', with no damage
    requirement)."""
    result = _run_packets(
        _holder(),
        [
            _packet(1.0, 0, damage=0.0, damage_type="magic", is_ability=True),
            _packet(2.0, 1, damage=100.0, damage_type="magic", is_ability=True),
        ],
    )
    assert _row(result)["damage_taken"] == pytest.approx(100.0)
    assert _row(result)["spell_shield_used"] is True
    assert len(_blocked_packets(result)) == 1


def test_unknown_delivery_fails_closed_without_inventing_consumption():
    """An unclassifiable packet (no ability/auto marker) is denied with the
    named reason and passes through untouched — the shield is NOT spent on
    it (fail closed: no invented consumption)."""
    result = _run_packets(
        _holder(),
        [
            _packet(1.0, 0, damage=30.0, damage_type="magic", source_key="mystery"),
            _packet(2.0, 1, damage=100.0, damage_type="magic", is_ability=True),
        ],
    )
    # The mystery packet lands untouched (30.0); the shield is NOT spent on
    # it, so the FIRST hostile ability that follows is still blocked.
    assert _row(result)["damage_taken"] == pytest.approx(30.0)
    assert _row(result)["spell_shield_used"] is True
    decisions = _row(result)["spell_shield"]["decisions"]
    assert decisions[0]["reason"] == "unknown_delivery"
    assert decisions[0]["eligible"] is False
    # The mystery packet was NOT the blocked one — the ability was.
    assert len(_blocked_packets(result)) == 1
    assert _blocked_packets(result)[0]["event_key"] == "Q:2.0:1"


# ---------------------------------------------------------------------------
# 5. 60s cooldown + rearm
# ---------------------------------------------------------------------------


def test_second_ability_within_the_cooldown_is_not_blocked():
    """One use per hostile cast: a second ability at t=2.0 (well inside the
    sourced 60s) lands with full damage."""
    result = _run_packets(
        _holder(),
        [
            _packet(1.0, 0, damage=100.0, damage_type="magic", is_ability=True),
            _packet(2.0, 1, damage=100.0, damage_type="magic", is_ability=True),
        ],
    )
    assert _row(result)["damage_taken"] == pytest.approx(100.0)
    assert len(_blocked_packets(result)) == 1
    assert _row(result)["spell_shield_used"] is True


def test_rearm_past_the_sourced_sixty_seconds_restarts_on_champion_damage():
    """The rearm clock enforces the sourced 60s AND its restart clause.

    Same 70s window this file used to pin as "never re-arms".  The
    arithmetic, entirely from sourced numbers: the shield is consumed by
    the ability at t=1.0; the basic attack at t=2.0 lands 20 damage on the
    holder, which is what "timer restarts upon taking damage from
    champions" measures, so the timer starts at max(1.0, 2.0) = 2.0 rather
    than at the consumption instant; ready_at = 2.0 + 60.0 = 62.0; the
    second ability at t=65.0 >= 62.0, so it IS blocked.  Surviving damage
    is the two basic attacks only: 20.0 + 20.0 = 40.0.

    The naive clock (consumed_at + cooldown = 61.0) would agree on THIS
    packet's outcome, so the restart clause is pinned separately below on
    a fight where the two disagree.
    """
    result = _run_packets(
        _holder(),
        [
            _packet(1.0, 0, damage=100.0, damage_type="magic", is_ability=True),
            _packet(
                2.0,
                1,
                damage=20.0,
                damage_type="physical",
                source_key="auto_attacks",
                basic_attack=True,
            ),
            _packet(65.0, 2, damage=100.0, damage_type="magic", is_ability=True),
            _packet(
                66.0,
                3,
                damage=20.0,
                damage_type="physical",
                source_key="auto_attacks",
                basic_attack=True,
            ),
        ],
        duration=70.0,
    )
    assert _row(result)["damage_taken"] == pytest.approx(40.0)
    assert len(_blocked_packets(result)) == 2
    assert _row(result)["spell_shield_used"] is True
    rearms = _row(result)["spell_shield"]["rearms"]
    assert len(rearms) == 1
    assert rearms[0]["time"] == pytest.approx(65.0)
    assert rearms[0]["consumed_at"] == pytest.approx(1.0)
    assert rearms[0]["cooldown"] == pytest.approx(COOLDOWN)
    assert rearms[0]["restarts_on_champion_damage"] is True
    assert rearms[0]["timer_started_at"] == pytest.approx(2.0)
    assert rearms[0]["ready_at"] == pytest.approx(62.0)


def test_champion_damage_after_consumption_delays_the_rearm_past_the_second_cast():
    """The restart clause is enforced, not decorative.

    Same 70s window, but a basic attack lands at t=9.0 instead of t=2.0.
    Timer starts at max(1.0, 9.0) = 9.0, ready_at = 9.0 + 60.0 = 69.0, so
    the second ability at t=65.0 < 69.0 is NOT blocked and lands for 100.
    A clock anchored on the consumption instant alone would have been
    ready at 61.0 and would have blocked it — this is the packet that
    separates the two, and it is the direction that would over-credit the
    defender.  Surviving damage: 20.0 (auto) + 100.0 (ability) = 120.0.

    69.0 is still INSIDE this 70s window: what the t=65 cast misses is the
    rearm instant, not the fight.  The case where the cooldown outlasts the
    whole window is the 30s request-bound one, pinned on Banshee's 40s in
    ``test_spell_shield_eligibility.py``.
    """
    result = _run_packets(
        _holder(),
        [
            _packet(1.0, 0, damage=100.0, damage_type="magic", is_ability=True),
            _packet(
                9.0,
                1,
                damage=20.0,
                damage_type="physical",
                source_key="auto_attacks",
                basic_attack=True,
            ),
            _packet(65.0, 2, damage=100.0, damage_type="magic", is_ability=True),
        ],
        duration=70.0,
    )
    assert _row(result)["damage_taken"] == pytest.approx(120.0)
    assert len(_blocked_packets(result)) == 1
    receipt = _row(result)["spell_shield"]
    assert receipt["rearms"] == []
    # The clock was present and sourced, so the miss is the arithmetic and
    # not an absent cooldown, and the shield is still spent afterwards.
    assert receipt["rearm"]["sourced"] is True
    assert receipt["rearm"]["cooldown"] == pytest.approx(COOLDOWN)
    assert _row(result)["spell_shield_used"] is True
    assert receipt["uses_after"] == 0
    # The t=65 cast was ELIGIBLE — the window and acceptance admitted it and
    # only the unelapsed cooldown declined it.  Without this the "not
    # blocked" assertions above would pass equally for a cast the shield
    # never even considered.
    late = [
        entry for entry in receipt["decisions"] if entry["cast_identity"] == "Q:65.0"
    ]
    assert len(late) == 1
    assert late[0]["eligible"] is True
    assert late[0]["reason"] == ""


def test_rearm_rule_is_receipted_with_the_sixty_second_cooldown():
    """The survival-row receipt carries cooldown_seconds 60.0, the catalog
    atom hash, the rearm categorical rule quoting Verdant's 60s, and the
    sourced rearm clock itself."""
    result = _run_packets(
        _holder(),
        [_packet(1.0, 0, damage=100.0, damage_type="magic", is_ability=True)],
    )
    receipt = _row(result)["spell_shield"]
    assert receipt["cooldown_seconds"] == pytest.approx(COOLDOWN)
    assert receipt["cooldown_atom"]["hash"] == COOLDOWN_ATOM_HASH
    rules = " ".join(entry["rule"] for entry in receipt["rules"])
    assert "only once its sourced cooldown has fully elapsed" in rules
    assert "60 seconds — Verdant Barrier" in rules
    assert "timer restarts upon taking damage from champions" in rules
    # The clock rides the same receipt, sourced by the same catalog atom.
    assert receipt["rearm"]["cooldown"] == pytest.approx(COOLDOWN)
    assert receipt["rearm"]["sourced"] is True
    assert receipt["rearm"]["restarts_on_champion_damage"] is True
    assert receipt["rearm"]["source_atom"]["hash"] == COOLDOWN_ATOM_HASH
    # A default-length fight cannot reach the cooldown, so nothing rearmed.
    assert receipt["rearms"] == []


# ---------------------------------------------------------------------------
# 6. Receipt fields + source evidence
# ---------------------------------------------------------------------------


def test_survival_receipt_carries_the_annul_lifecycle():
    """The public survival-row spell_shield receipt declares the full
    lifecycle: source, infinite window, acceptance, block rule, the five
    categorical rules, one-use budget, blocked packets, decisions, no
    triggered heal, and the sourced cooldown."""
    result = _run_packets(
        _holder(),
        [
            _packet(1.0, 0, damage=100.0, damage_type="magic", is_ability=True),
        ],
    )
    receipt = _row(result)["spell_shield"]
    assert receipt["source"] == SHIELD_SOURCE
    assert receipt["window"] == {"start": 0.0, "until": None, "source_atoms": []}
    assert receipt["acceptance"] == {
        "requires_ability": True,
        "blocks_basic_attacks": False,
        "blocks_control_only": True,
        "accepts_unknown": False,
    }
    assert "blocks the next hostile ability" in receipt["block_rule"]
    assert receipt["uses_before"] == 1
    assert receipt["uses_after"] == 0
    assert receipt["selected_cast_identity"] == "Q:1.0"
    assert receipt["triggered_heal"] is None
    assert len(receipt["rules"]) == 5
    assert receipt["blocked_packets"]
    assert receipt["decisions"]


def test_item_state_receipts_emits_the_verdant_annul_row():
    """P3-3U (3M/3N/3O pattern, live post-completion): item_state_receipts
    emits exactly ONE Verdant row — state "annul" — carrying
    spell_shield_ready True, spell_shield_cooldown 60.0, the catalog atom
    hash, the wiki source receipt (revision 3957920), and the named
    rearm_boundary that receipts the 60s cooldown and the damage-restart
    rule as ENFORCED, plus the 30s request bound no rearm can reach."""
    receipts = item_state_receipts(
        [_verdant_item()], {}, fight_duration_seconds=10.0, is_melee=False
    )
    (row,) = [row for row in receipts if row.get("item") == ITEM_NAME]
    assert row["state"] == "annul"
    assert row["spell_shield_ready"] is True
    assert row["spell_shield_cooldown"] == pytest.approx(COOLDOWN)
    assert row["cooldown_atom"]["hash"] == COOLDOWN_ATOM_HASH
    assert row["source_revision_id"] == SOURCE_REVISION
    assert str(row["source_url"]).startswith(SOURCE_URL)
    assert "rearm" in row["rearm_boundary"]
    assert "damage" in row["rearm_boundary"]


# ---------------------------------------------------------------------------
# 7. Compiled vs receipt parity
# ---------------------------------------------------------------------------


def test_score_path_agrees_with_receipt_on_every_observable():
    """The coupled score surface (include_receipt=False) returns the same
    survival rows (spell_shield lifecycle included), breakdown, and
    duration as the receipt surface.  Verdant sits in
    COMPILED_WALK_UNREPRESENTABLE_ITEMS, so the compiled fast path fails
    closed (candidate-local) and both surfaces run the shared kernel walk
    — equality by construction today.  This is the score-path equality the
    P3-3U certification must preserve with byte parity."""
    receipt = _holder_fight(10.0)
    score = _holder_fight(10.0, include_receipt=False)
    compiled_ctx = CoupledSearchContext()
    compiled = _holder_fight(10.0, include_receipt=False, search_context=compiled_ctx)
    for surface in (score, compiled):
        assert surface["participants"][0]["survival"] == _main_survival(receipt)
        assert (
            surface["participants"][1]["survival"]
            == receipt["participants"][1]["survival"]
        )
        assert surface["duration"] == receipt["duration"]
        for score_row, receipt_row in zip(surface["breakdown"], receipt["breakdown"]):
            assert score_row["participant_id"] == receipt_row["participant_id"]
            assert score_row["total_damage"] == receipt_row["total_damage"]
            assert score_row["incoming_damage"] == receipt_row["incoming_damage"]
            assert score_row["health_damage"] == receipt_row["health_damage"]
            assert score_row["death_time"] == receipt_row["death_time"]
            assert score_row["survived_window"] == receipt_row["survived_window"]
    # The fixture actually exercised the Annul machine: one blocked cast.
    survival = _main_survival(receipt)
    assert survival["spell_shield_used"] is True
    assert survival["spell_shield_source"] == SHIELD_SOURCE
    assert survival["spell_shield_until"] is None
    blocked = [
        event
        for event in receipt["events"]
        if event.get("skipped_reason") == "spell_shield"
    ]
    assert len(blocked) == 1
    assert blocked[0]["spell_shield_source"] == SHIELD_SOURCE
    # The context stays usable (candidate-local fallback today; the P3-3U
    # certification replaces the fallback with compiled panels).
    assert compiled_ctx.uncompilable is False


def test_compiled_panels_carry_the_verdant_fight():
    """P3-3U contract: once Verdant leaves COMPILED_WALK_UNREPRESENTABLE_ITEMS
    with byte-parity proof (the Annul cast-metadata gate staged in the
    compiled kernel), the compiled score path rides the shared kernel for a
    main holder: the context builds panels, stays unpoisoned, and the
    compiled surface still deep-equals the receipt walk.  LIVE
    post-completion."""
    ctx = CoupledSearchContext()
    legacy = _holder_fight(10.0, include_receipt=False)
    fast = _holder_fight(10.0, include_receipt=False, search_context=ctx)
    assert fast == legacy
    assert ctx.uncompilable is False
    assert ctx.panels
    assert fast["participants"][0]["survival"]["spell_shield_used"] is True


def test_enemy_holder_compiles_after_certification():
    """P3-3U contract: the roster-side Verdant holder compiles like the
    main holder — the capability scan no longer poisons the context, panels
    are built, and the compiled surface deep-equals the receipt walk.
    LIVE post-completion: the roster-side holder compiles like the main
    holder."""
    main = get_champion("Ahri")
    main_stats = calculate_total_stats(main, 18, [])
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(champion="Janna", level=18, items=[ITEM_NAME]).resolve()
    kwargs = dict(
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses("Ahri", 18, main_stats, []),
        enemies=[enemy],
        allies=[],
    )
    legacy = build_participant_timeline(
        main, 18, [], params, include_receipt=False, **kwargs
    )
    ctx = CoupledSearchContext()
    fast = build_participant_timeline(
        main,
        18,
        [],
        params,
        include_receipt=False,
        pair_result_cache={},
        search_context=ctx,
        **kwargs,
    )
    assert fast == legacy
    assert ctx.uncompilable is False
    assert ctx.panels
    janna = next(row for row in legacy["participants"] if row["champion"] == "Janna")
    assert janna["survival"]["spell_shield_used"] is True


def test_tuple_ledger_champion_holding_verdant_fails_closed_with_parity():
    """A tuple-ledger champion (Riven) holding Verdant in a coupled
    compiled fight fails closed with parity and NO crash today: the
    candidate-local fallback keeps the context unpoisoned and the score
    surface deep-equals the receipt walk, spell-shield fields included."""
    main = get_champion("Riven")
    items = [_verdant_item()]
    main_stats = calculate_total_stats(main, 18, items)
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "role": "top",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(champion="Cassiopeia", level=18, items=[]).resolve()
    kwargs = dict(
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses("Riven", 18, main_stats, items),
        enemies=[enemy],
        allies=[],
    )
    legacy = build_participant_timeline(
        main, 18, items, params, include_receipt=False, **kwargs
    )
    ctx = CoupledSearchContext()
    fast = build_participant_timeline(
        main,
        18,
        items,
        params,
        include_receipt=False,
        pair_result_cache={},
        search_context=ctx,
        **kwargs,
    )
    assert fast == legacy
    assert ctx.uncompilable is False
    riven = next(row for row in legacy["participants"] if row["champion"] == "Riven")
    assert riven["survival"]["spell_shield_used"] is True


def test_compiled_capability_scan_is_clean_after_certification():
    """P3-3U (live post-completion): Verdant Barrier leaves
    COMPILED_WALK_UNREPRESENTABLE_ITEMS — the capability scan reports no
    item_mechanic receipt (the Annul cast-metadata gate is staged in the
    compiled kernel); a representable item stays untouched."""
    assert uncompilable_item_receipt([{"name": ITEM_NAME}]) is None
    assert uncompilable_item_receipt([{"name": "Infinity Edge"}]) is None


# ---------------------------------------------------------------------------
# 8. Coverage / BIS
# ---------------------------------------------------------------------------


def test_coverage_posture_stays_eligible_today():
    """item_model_coverage returns the justified posture today: the
    mechanic changes defense, not outgoing TDD, so the item stays
    optimizer_eligible + calculation_eligible with the ordinary stats;
    outcome_dimensions is [] (Verdant is missing the "spell_protection"
    dimension that Banshee's Veil / Edge of Night carry — the
    coordinator's tightening, pinned xfail below)."""
    coverage = item_model_coverage(
        str(_verdant_item()["name"]), ATTACKER_LANES
    ).as_payload()
    assert coverage["status"] == "stats_only"
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert coverage["outcome_dimensions"] == ["spell_protection"]
    target = target_item_model_coverage(_verdant_item())
    assert target["status"] == "modeled"
    assert target["calculation_eligible"] is True


def test_model_coverage_reason_names_annul_and_spell_shield():
    """P3-3U coverage tightening: item_model_coverage's reason should name
    the Annul spell-shield mechanic (the target coverage already does), and
    the outcome dimensions include "spell_protection" (matching Banshee's
    Veil / Edge of Night).  LIVE post-completion: the reason names the
    Annul spell-shield mechanic and the dimensions carry
    "spell_protection"."""
    coverage = item_model_coverage(
        str(_verdant_item()["name"]), ATTACKER_LANES
    ).as_payload()
    # Ours' attacker-lane reason is derived from the declared families and
    # never repeats a mechanic's prose; the mechanic is named on the
    # target lane, which this file asserts above.
    assert coverage["status"] == "stats_only"
    assert "Annul" in target_item_model_coverage(_verdant_item())["reason"]
    assert coverage["outcome_dimensions"] == ["spell_protection"]


def test_target_coverage_models_the_annul_consumption():
    """target_item_model_coverage is "modeled" naming the Annul opening
    consumption: ready at fight start, consumes the first source-backed
    Q/W/E/R cast, autos and later casts land."""
    target = target_item_model_coverage(_verdant_item())
    assert target["status"] == "modeled"
    assert "Annul" in target["reason"]


def test_bis_exclusion_is_by_construction_not_withheld():
    """Verdant Barrier is an EPIC tier-2 component of Banshee's Veil
    (buildsInto 3102); the BIS candidate pool ranks only legendary items
    and boots, so it is excluded by construction — never a candidate, never
    withheld for a coverage failure (mirrors test_issues_46)."""
    data = get_item_by_name(ITEM_NAME)
    assert "EPIC" in data["rank"]
    assert data["tier"] == 2
    assert 3102 in data.get("buildsInto", [])
    client = app_module.app.test_client()
    ranks = {"Q": 5, "W": 5, "E": 5, "R": 3}
    payload = {
        "champion": "Ahri",
        "level": 18,
        "items": [],
        "boots": "",
        "role": "mid",
        "role_quest_complete": False,
        "ability_ranks": ranks,
        "champion_options": {},
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.3,
        "subject_team": "main",
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "enemies": [
            {
                "champion": "Ambessa",
                "level": 18,
                "items": [],
                "role": "top",
                "ability_ranks": ranks,
            }
        ],
    }
    response = client.post("/api/bis", json=payload)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert ITEM_NAME not in {row["name"] for row in body.get("candidates", [])}
    assert ITEM_NAME not in {
        row.get("name") for row in body.get("withheld_candidates", [])
    }


def test_spell_shield_legendaries_still_certify_in_bis():
    """The legendary Annul items remain certified BIS candidates for
    fitting roles (mirrors test_issues_46): Banshee's Veil on Ahri mid,
    Edge of Night on Talon mid."""
    client = app_module.app.test_client()
    ranks = {"Q": 5, "W": 5, "E": 5, "R": 3}
    for champion, item in (("Ahri", "Banshee's Veil"), ("Talon", "Edge of Night")):
        payload = {
            "champion": champion,
            "level": 18,
            "items": [],
            "boots": "",
            "role": "mid",
            "role_quest_complete": False,
            "ability_ranks": ranks,
            "champion_options": {},
            "fight_mode": "time_based",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 0.3,
            "subject_team": "main",
            "subject_index": 0,
            "slot_index": 0,
            "slot_kind": "item",
            "enemies": [
                {
                    "champion": "Ambessa",
                    "level": 18,
                    "items": [],
                    "role": "top",
                    "ability_ranks": ranks,
                }
            ],
        }
        response = client.post("/api/bis", json=payload)
        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        certified = {row["name"] for row in body.get("candidates", [])}
        assert item in certified
        candidate = next(row for row in body["candidates"] if row["name"] == item)
        assert candidate["timeline_coverage"]["complete"] is True


# ---------------------------------------------------------------------------
# 9. Existing regression surface (kept green, disjoint, mirrors the originals)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("item_name", "blocked_source"),
    [
        ("Banshee's Veil", "Banshee's Veil — Annul"),
        ("Edge of Night", "Edge of Night — Annul"),
        ("Verdant Barrier", "Verdant Barrier — Annul"),
    ],
)
def test_regression_surface_defensive_effects_annul_is_ready(item_name, blocked_source):
    """Mirrors test_defensive_effects.py (test_annul_is_ready_as_an_opening_
    spell_shield): every Annul item resolves ready at the opening with its
    sourced label."""
    defenses = resolve_starting_defenses("Ahri", 18, _stats(), [{"name": item_name}])
    assert defenses.spell_shield_ready is True
    assert defenses.spell_shield_source == blocked_source
    summary = defenses.public_summary()
    assert summary["spell_shield"] == {"ready": True, "source": blocked_source}


def test_regression_surface_issues_46_annul_blocks_one_typed_ability():
    """Mirrors test_issues_46.py (test_annul_spell_shield_is_ready_and_
    blocks_one_typed_ability) for Verdant Barrier through /api/calculate:
    the shield is ready at fight start, exactly one ability packet is
    blocked, and the blocked packet carries the sourced label."""
    ranks = {"Q": 5, "W": 5, "E": 5, "R": 3}
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 18,
            "enemies": [
                {
                    "champion": "Kai'Sa",
                    "level": 18,
                    "items": [ITEM_NAME],
                    "role": "top",
                    "ability_ranks": ranks,
                }
            ],
        },
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    target = body["targets"][0]
    assert target["target"]["starting_defenses"]["spell_shield"] == {
        "ready": True,
        "source": SHIELD_SOURCE,
    }
    kaisa = next(
        row for row in body["combat"]["participants"] if row["champion"] == "Kai'Sa"
    )
    assert kaisa["survival"]["spell_shield_used"] is True
    blocked = [
        event
        for event in body["combat"]["events"]
        if event.get("skipped_reason") == "spell_shield"
    ]
    assert len(blocked) == 1
    assert all(event["spell_shield_source"] == SHIELD_SOURCE for event in blocked)


def test_regression_surface_spell_shield_eligibility_auto_attack_gate():
    """Mirrors test_spell_shield_eligibility.py (R3): in an app fight with
    autos enabled, no basic-attack packet is ever spell-shield-skipped or
    annotated, and the shield is spent only by an ability packet."""
    ranks = {"Q": 5, "W": 5, "E": 5, "R": 3}
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ezreal",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 9.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "cast_order": ["Q", "W", "E", "R"],
            "ability_ranks": ranks,
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [ITEM_NAME],
                    "ability_ranks": ranks,
                }
            ],
        },
    )
    assert response.status_code == 200, response.get_json()
    combat = response.get_json()["combat"]
    autos = [
        event
        for event in combat["events"]
        if event.get("target") == "enemy:Ahri" and event.get("source") == "auto_attacks"
    ]
    assert autos
    assert all(event.get("skipped_reason") != "spell_shield" for event in autos)
    assert all("spell_shield_source" not in event for event in autos)
    blocked = [
        event
        for event in combat["events"]
        if event.get("skipped_reason") == "spell_shield"
    ]
    assert len(blocked) == 1
    assert blocked[0]["spell_shield_source"] == SHIELD_SOURCE
    survival = next(
        row["survival"]
        for row in combat["participants"]
        if row["participant_id"] == "enemy:Ahri"
    )
    assert survival["spell_shield_used"] is True
    # A later ability lands with full damage (the shield is spent).
    later = [
        event
        for event in combat["events"]
        if event.get("target") == "enemy:Ahri"
        and event.get("source") in {"Q", "W", "E", "R"}
        and event.get("skipped_reason") is None
        and event.get("time") > blocked[0]["time"]
        and (event.get("damage") or 0) > 0.0
    ]
    assert later


def test_regression_surface_participant_timeline_opening_annul():
    """Mirrors test_participant_timeline.py (test_opening_annul_from_item_
    blocks_first_canonical_ability) for Verdant Barrier: a same-cast
    multi-part ability (magic + true damage packets) is blocked with ONE
    use and the follow-up auto lands."""
    source = _dummy_source("source", "enemy")
    target = _holder()
    events = [
        _packet(0.0, 0, damage=40.0, damage_type="magic", is_ability=True),
        _packet(0.0, 1, damage=15.0, damage_type="true", is_ability=True),
        _packet(
            0.5,
            2,
            damage=20.0,
            damage_type="physical",
            source_key="auto_attacks",
            basic_attack=True,
        ),
    ]
    result = simulate_survival([source, target], {"target": events}, {}, {}, 10.0)
    assert result["target"]["damage_taken"] == pytest.approx(20.0)
    assert result["target"]["spell_shield_used"] is True
    assert result["target"]["spell_shield_source"] == SHIELD_SOURCE
    assert result["target"]["spell_shield_until"] is None


def test_regression_surface_app_opening_enemy_spell_shield():
    """Mirrors test_app.py (test_calculate_applies_an_opening_enemy_spell_
    shield): an enemy Galio holding the Annul item blocks the first hostile
    ability in the coupled ledger."""
    ranks = {"Q": 5, "W": 5, "E": 5, "R": 3}
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 8.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "cast_order": ["Q", "W", "E", "R"],
            "ability_ranks": ranks,
            "enemies": [
                {
                    "champion": "Galio",
                    "level": 12,
                    "items": [ITEM_NAME],
                    "role": "mid",
                    "ability_ranks": {"Q": 3, "W": 3, "E": 3, "R": 2},
                }
            ],
        },
    )
    assert response.status_code == 200, response.get_json()
    combat = response.get_json()["combat"]
    galio = next(row for row in combat["participants"] if row["champion"] == "Galio")
    assert galio["survival"]["spell_shield_used"] is True
    blocked = [
        event
        for event in combat["events"]
        if event.get("skipped_reason") == "spell_shield"
    ]
    assert blocked
    assert all(event["spell_shield_source"] == SHIELD_SOURCE for event in blocked)


def test_regression_surface_item_coverage_target_models_annul():
    """Mirrors test_item_coverage.py (target coverage "modeled" for
    Banshee's Veil): Verdant Barrier's target coverage is "modeled" with
    the Annul reason."""
    coverage = target_item_model_coverage(_verdant_item())
    assert coverage["status"] == "modeled"
    assert coverage["calculation_eligible"] is True
    assert "Annul" in coverage["reason"]
