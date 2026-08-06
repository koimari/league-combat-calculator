"""E8d — revive events (Anivia, Zac, Zilean) + ally-support heals/shields.

Revives: each champion module sources its revive contract from the cached
passive/ultimate prose and leveling rows (``starting_revive_defense``), and
the fight assertion wires those sourced values through the existing
``StartingDefenses.revive_*`` interface (the same fields Guardian Angel's
Rebirth uses) so the engine's revive state transition restores the sourced
HP after a lethal packet.

Ally support: each champion declares its support slot in SLOTS so the fight
rotation casts it; the engine's ally-support scanner (support_effects.py)
then emits the shield/heal packet with amounts sourced from the cached
leveling rows.  The assertions use the roster path (/api/calculate with an
ally) and check the ally's survival ledger.

Documented missing engine hooks (not emitted by the current shared
interfaces — see the E8d reply for file+function+why):
- Taric Q per-charge heal (cached leveling has only "Maximum Charges"; the
  heal formula is prose "25 (+ 15% AP) (+ 1% of his maximum health) per
  charge") and Taric R invulnerability (state, no heal/shield amount).
- Bard W "Minimum Heal"/"Maximum Heal" rows are not in the support scanner's
  heal-attribute lookup set ({"Total Heal", "Heal", "Heal Per Tick"}).
- Rakan P (Fancy Footwork) is a passive self-shield; the scanner reads only
  Q/W/E/R slots.
- Yuumi E scope: the cached "grants herself a shield" prose yields
  target_scope "self"; the attached-bonus anchor target is not expressed.
- Seraphine W heal is "% of target's missing health" (dynamic) — the scanner
  emits the sourced shield but cannot price the heal.
"""

from dataclasses import replace

import pytest

from src import app as app_module
from src.calculator.data_fetcher import get_champion
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.participant_timeline import build_participant_timeline
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _roster_combat(champion: str, *, level: int = 18, ap: int = 0, ally: str = "Jinx"):
    """Run /api/calculate with *champion* as main and one ally in the roster."""
    app_module.app.config["TESTING"] = True
    payload = {
        "champion": champion,
        "level": level,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 6,
        "include_auto_attacks": False,
        "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        "allies": [
            {
                "champion": ally,
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            }
        ],
    }
    if ap:
        payload["allies"][0]["items"] = ["Rabadon's Deathcap"]
        payload["items"] = ["Rabadon's Deathcap"]
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    combat = response.get_json()["combat"]
    ally_row = next(
        row for row in combat["participants"] if row["participant_id"] == f"ally:{ally}"
    )
    return combat, ally_row


def _support_events(combat, source_prefix: str):
    attacker = "main"
    return [
        event
        for event in combat["support_events"]
        if event["attacker"] == attacker
        and event["source"].startswith(source_prefix)
        and event["kind"] in {"heal", "shield"}
    ]


# ---------------------------------------------------------------------------
# REVIVES
# ---------------------------------------------------------------------------


def _revive_fight(champion: str, level: int, stats_override=None):
    """Build a roster fight where *champion* takes lethal damage and revives.

    The champion module sources the revive contract; those sourced values are
    wired through the existing StartingDefenses.revive_* fields (the same
    interface Guardian Angel's Rebirth uses) so the engine's revive state
    transition can consume them.
    """
    main = get_champion(champion)
    main_stats = calculate_total_stats(main, level, [])
    if stats_override:
        main_stats = dict(main_stats)
        main_stats.update(stats_override)
    module = __import__(
        f"src.calculator.champions.{champion.lower()}",
        fromlist=["starting_revive_defense"],
    )
    revive = module.starting_revive_defense(level, main_stats)
    defenses = replace(
        resolve_starting_defenses(champion, level, main_stats, []), **revive
    )
    params = FightParams.from_request(
        {
            "fight_mode": "auto_only",
            "fight_duration": float(revive["revive_delay"]) + 0.2,
            "auto_attacks_only": True,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(champion="Aatrox", level=18, items=()).resolve()
    result = build_participant_timeline(
        main,
        level,
        [],
        params,
        main_stats=main_stats,
        main_defenses=defenses,
        enemies=[enemy],
        allies=[],
    )
    return result, revive


def test_anivia_rebirth_revives_with_sourced_full_health():
    """Anivia P Rebirth restores all of her health after a 6s resurrection.

    Source: cached passive prose "restores all of her health"; the engine's
    revive transition consumes the sourced amount.
    """
    result, revive = _revive_fight(
        "Anivia",
        18,
        {
            "health": 150.0,
            "base_health": 300.0,
            "bonus_health": 0.0,
            "armor": 0.0,
            "magic_resistance": 0.0,
        },
    )
    survival = result["participants"][0]["survival"]
    assert revive["revive_health_amount"] == pytest.approx(150.0)
    assert revive["revive_delay"] == pytest.approx(6.0)
    assert revive["revive_cooldown"] == pytest.approx(240.0)
    assert survival["first_death_time"] is not None
    assert survival["revived"] is True
    assert survival["revive_health_restored"] == pytest.approx(150.0)
    assert survival["revive_time"] == pytest.approx(
        survival["first_death_time"] + 6.0, abs=1e-3
    )


def test_zac_cell_division_revives_with_sourced_fifty_percent():
    """Zac P Cell Division revives with 50% max health (all bloblets survive).

    Source: cached passive prose "instantly restoring 50% of his maximum
    health" / "After the duration, Zac is revived with 10 : 50% maximum
    health"; the deterministic model assumes all four bloblets survive.
    """
    result, revive = _revive_fight(
        "Zac",
        18,
        {
            "health": 200.0,
            "base_health": 400.0,
            "bonus_health": 0.0,
            "armor": 0.0,
            "magic_resistance": 0.0,
        },
    )
    survival = result["participants"][0]["survival"]
    assert revive["revive_health_amount"] == pytest.approx(100.0)
    assert revive["revive_delay"] == pytest.approx(4.0)  # level 18 bracket
    assert revive["revive_cooldown"] == pytest.approx(300.0)
    assert survival["revived"] is True
    assert survival["revive_health_restored"] == pytest.approx(100.0)


def test_zilean_chronoshift_revives_with_sourced_flat_ap_heal():
    """Zilean R Chronoshift revives with 600/850/1100 + 200% AP by rank.

    Source: cached R leveling Heal row (values 600/850/1100, "% AP" 200/200/200).
    """
    result, revive = _revive_fight(
        "Zilean",
        18,
        {
            "health": 200.0,
            "base_health": 400.0,
            "bonus_health": 0.0,
            "armor": 0.0,
            "magic_resistance": 0.0,
            "ability_power": 100.0,
        },
    )
    survival = result["participants"][0]["survival"]
    # rank 3 at level 18: 1100 + 200% AP * 100 = 1300.  The revive restores
    # the sourced amount, capped at maximum health (200 here).
    assert revive["revive_health_amount"] == pytest.approx(1300.0)
    assert revive["revive_delay"] == pytest.approx(3.0)
    assert revive["revive_cooldown"] == pytest.approx(60.0)
    assert survival["revived"] is True
    assert survival["revive_health_restored"] == pytest.approx(200.0, abs=1e-3)


# ---------------------------------------------------------------------------
# ALLY-SUPPORT heals/shields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("champion", "source", "kind", "amount"),
    [
        ("Sona", "Aria of Perseverance", "shield", 105.0),
        ("Sona", "Aria of Perseverance", "heal", 90.0),
        ("Nami", "Ebb and Flow", "heal", 155.0),
        ("Milio", "Cozy Campfire", "heal", 150.0),
        ("Milio", "Breath of Life", "heal", 350.0),
        ("Rakan", "Gleaming Quill", "heal", 80.0),
        ("Kayle", "Celestial Blessing", "heal", 155.0),
        ("Seraphine", "Surround Sound", "shield", 140.0),
        ("Janna", "Eye of the Storm", "shield", 240.0),
        ("Janna", "Monsoon", "heal", 600.0),
        ("Yuumi", "Final Chapter", "heal", 350.0),
        ("Soraka", "Astral Infusion", "heal", 170.0),
    ],
)
def test_ally_ledger_receives_sourced_support(champion, source, kind, amount):
    """The ally's survival ledger receives the champion's sourced heal/shield."""
    combat, ally_row = _roster_combat(champion)
    events = _support_events(combat, source)
    matching = [e for e in events if e["kind"] == kind]
    assert matching, f"no {source} {kind} event for {champion}"
    # the packet amount is sourced from cached leveling
    assert matching[0]["amount"] == pytest.approx(amount)
    assert matching[0]["target"] == "ally:Jinx"
    if kind == "shield":
        assert ally_row["survival"]["support_shield_received"] >= amount
    else:
        # F2 order note: the enemy now plays its optimal rotation
        # (Aatrox opens with the zero-damage World Ender), so the first
        # hit on the ally lands at t=0.25 — after the t=0 heal.  A heal
        # that lands on a full-health ally overheals (applied 0); the
        # sourced amount is still fully accounted in the ledger as
        # healing_received + overhealing.
        assert (
            ally_row["survival"]["healing_received"]
            + ally_row["survival"]["overhealing"]
            >= amount
        )


def test_yuumi_zoomies_emits_sourced_self_shield_ally_target_is_missing_hook():
    """Yuumi E (Zoomies) emits the sourced shield; its target is the anchor.

    The cached E prose ("Yuumi grants herself a shield") makes the engine's
    support scanner resolve target_scope "self".  The attached-bonus anchor
    transfer ("Zoomies affects the Anchor instead of Yuumi") is expressed
    by the E8d follow-up scope override: the deterministic roster model
    targets one selected teammate (the anchor).
    """
    combat, _ally_row = _roster_combat("Yuumi")
    events = _support_events(combat, "Zoomies")
    assert events, "Zoomies shield event missing"
    shield = events[0]
    assert shield["kind"] == "shield"
    assert shield["amount"] == pytest.approx(165.0)
    assert shield["target_scope"] == "one_teammate"
    # The anchor is the roster ally (Yuumi attached to Jinx), not the caster.
    assert shield["target"] == "ally:Jinx"


# ---------------------------------------------------------------------------
# Sourced-amount pins: the emitted packet amount must equal the cached
# leveling value at the fight's rank (level 18 skill order), not a literal.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("champion", "slot", "attribute", "expected"),
    [
        ("Sona", "W", "Heal", 90.0),
        ("Sona", "W", "Shield Strength", 105.0),
        ("Nami", "W", "Heal", 155.0),
        ("Milio", "W", "Total Heal", 150.0),
        ("Milio", "R", "Heal", 350.0),
        ("Rakan", "Q", "Heal", 80.0),
        ("Kayle", "W", "Heal", 155.0),
        ("Seraphine", "W", "Shield Strength", 140.0),
        ("Janna", "E", "Shield Strength", 240.0),
        ("Janna", "R", "Total Heal", 600.0),
        ("Yuumi", "E", "Shield", 165.0),
        ("Yuumi", "R", "Total Heal", 350.0),
        ("Soraka", "W", "Heal", 170.0),
    ],
)
def test_support_amount_is_sourced_from_cached_leveling(
    champion, slot, attribute, expected
):
    """The support packet amount equals the cached leveling row at rank 5."""
    from src.calculator.champions.slotlib import extract_named
    from src.calculator.champions.skill_orders import get_ability_rank

    data = get_champion(champion)
    rank = get_ability_rank(slot, 18, champion)
    ability = data["abilities"][slot][0]
    assert extract_named(ability, attribute, rank, {"ability_power": 0.0}, {}) == (
        pytest.approx(expected)
    )


# ---------------------------------------------------------------------------
# Sourced-amount pins (module-level)
# ---------------------------------------------------------------------------


def test_support_caster_in_allies_list_targets_main_ledger():
    """A support champion in the roster's ALLIES list heals/shields the main.

    The roster path supports enemies + allies lists; the ally side emits its
    sourced support packets toward the main when ally_effects_enabled.
    """
    app_module.app.config["TESTING"] = True
    payload = {
        "champion": "Ahri",
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 6,
        "include_auto_attacks": False,
        "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        "allies": [
            {
                "champion": "Sona",
                "level": 18,
                "items": [],
                "role": "support",
                "ally_effects_enabled": True,
            }
        ],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    combat = response.get_json()["combat"]
    support = [
        e
        for e in combat["support_events"]
        if e["attacker"] == "ally:Sona"
        and e["source"].startswith("Aria of Perseverance")
        and e["kind"] in {"heal", "shield"}
    ]
    assert support
    main_row = next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )
    assert main_row["survival"]["support_shield_received"] >= 105.0
    # The t=0 heal lands while the main is still at full health (the
    # enemy's optimal rotation delays its first hit to t=0.25), so the
    # sourced 90 heals as overheal — still fully accounted.
    assert (
        main_row["survival"]["healing_received"] + main_row["survival"]["overhealing"]
        >= 90.0
    )


def test_soraka_astral_infusion_sourced_amount_and_health_cost_documented():
    """Soraka W heal is sourced (90-170 + 50% AP) and the health cost is doc-only."""
    from src.calculator.champions import soraka

    assert "W" in soraka.SLOTS
    combat, ally_row = _roster_combat("Soraka")
    events = _support_events(combat, "Astral Infusion")
    assert events, "Astral Infusion heal missing from the roster fight"
    assert all(e["kind"] == "heal" for e in events)
    assert ally_row["survival"]["healing_received"] >= 170.0


def test_revive_module_sourcing_matches_cached_rows():
    """The revive trio sources its contract from the cached data, not literals."""
    from src.calculator.champions.anivia import starting_revive_defense as ar
    from src.calculator.champions.zac import starting_revive_defense as zr
    from src.calculator.champions.zilean import starting_revive_defense as zilr

    # Anivia: full health, 6s, 240s cd
    assert ar(18, {"health": 1000.0}) == {
        "revive_health_amount": 1000.0,
        "revive_delay": 6.0,
        "revive_cooldown": 240.0,
    }
    # Zac: 50% max health, level-bracketed delay, 300s cd
    assert zr(1, {"health": 1000.0})["revive_delay"] == 8.0
    assert zr(18, {"health": 1000.0})["revive_delay"] == 4.0
    assert zr(18, {"health": 1000.0})["revive_health_amount"] == 500.0
    assert zr(18, {"health": 1000.0})["revive_cooldown"] == 300.0
    # Zilean: rank-based flat + 200% AP
    assert zilr(18, {"ability_power": 0.0})["revive_health_amount"] == 1100.0
    assert zilr(18, {"ability_power": 100.0})["revive_health_amount"] == 1300.0
    assert zilr(18, {"ability_power": 0.0})["revive_cooldown"] == 60.0
