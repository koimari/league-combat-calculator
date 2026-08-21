"""Issues #45 (grouped sustain stats + item healing) and #43 (on-hit,
Spellblade, Energized, Hydra families).

Every item sibling the issues call out is verified twice here:

* **Parse-level sourced pins** — the typed registry value and the wiki
  revision it was sourced from (``sustain_stat_receipt`` /
  ``required_effect_value`` / family accessors).  Missing keys raise,
  naming the item and key; there are no literal fallbacks.
* **``/api/calculate`` fights** — the sourced value reaches the public
  fight result (loadout stats, breakdown rows, self-healing events, and
  the participant timeline's sustain receipts such as ``healing_received``).
"""

import pytest

import src.app as app_module
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_effects import (
    ENERGIZED_SOURCE_RECEIPT,
    ITEM_EFFECTS,
    energized_proc_indices,
    energized_schedule_receipt,
    essence_reaver_mana_restore_per_proc,
    grouped_sustain_stat_percent,
    hydra_cleave_secondary_ad_damage,
    hydra_secondary_target_damage,
    required_effect_value,
    sustain_effect_value,
    sustain_stat_receipt,
)
from src.calculator.interpreters import charged_strike
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats


@pytest.fixture(autouse=True)
def _disable_rate_limits_between_route_tests():
    """Only dedicated tests spend the production abuse-control budget."""
    previous = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    yield
    app_module.app.config["RATE_LIMIT_ENABLED"] = previous


def _calculate(items, *, champion="Ahri", enemies=(), duration=6, **extra):
    """POST one /api/calculate fight with explicit auto-attack uptime."""
    payload = {
        "champion": champion,
        "level": 18,
        "items": list(items),
        "enemies": list(enemies),
        "fight_mode": "timed",
        "fight_duration": duration,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 3},
        "target_armor": 0,
        "target_mr": 0,
        "target_health": 5000,
    }
    payload.update(extra)
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _items(*names):
    return [get_item_by_name(name) for name in names]


# ---------------------------------------------------------------------------
# Issue #45 — grouped sustain stats and item healing
# ---------------------------------------------------------------------------


# Wiki Module:ItemData/data lifesteal percent + item-page revision each typed
# entry was sourced from.  The cached data/items.json carries the same values
# (it is parsed from the same wiki module); the registry pins them so a
# parser break cannot silently change sustain.
LIFESTEAL_PINS = {
    "Vampiric Scepter": (7.0, 4030549),
    "Mercurial Scimitar": (10.0, 3984461),
    "Bloodthirster": (15.0, 4025103),
    "Blade of the Ruined King": (10.0, 4044693),
    "Ravenous Hydra": (12.0, 4047314),
    "Gunmetal Greaves": (5.0, 4013706),
}


@pytest.mark.parametrize(
    ("item_name", "percent", "revision"),
    sorted((name, *pin) for name, pin in LIFESTEAL_PINS.items()),
)
def test_lifesteal_typed_receipts_pin_wiki_values(item_name, percent, revision):
    """Every lifesteal item has a typed registry entry with its source."""
    receipt = sustain_stat_receipt(item_name, "lifesteal_percent")
    assert receipt["value"] == pytest.approx(percent)
    assert receipt["source_revision_id"] == revision
    assert receipt["source_url"] == (
        "https://wiki.leagueoflegends.com/en-us/" + item_name.replace(" ", "_")
    )
    # The typed value agrees with the cached item JSON (same wiki source).
    assert get_item_by_name(item_name)["stats"]["lifesteal"][
        "percent"
    ] == pytest.approx(percent)


def test_missing_lifesteal_key_raises_naming_item_and_key(monkeypatch):
    """A missing typed key fails loudly instead of borrowing a literal."""
    monkeypatch.setitem(ITEM_EFFECTS, "Vampiric Scepter", {"type": "sustain"})
    with pytest.raises(KeyError, match="Vampiric Scepter.*lifesteal_percent"):
        sustain_stat_receipt("Vampiric Scepter", "lifesteal_percent")
    with pytest.raises(KeyError, match="Vampiric Scepter.*lifesteal_percent"):
        grouped_sustain_stat_percent(_items("Vampiric Scepter"), "lifesteal_percent")


def test_missing_lifesteal_source_raises_naming_item_and_key(monkeypatch):
    """A receipt without its wiki revision is not synthesized; it raises."""
    monkeypatch.setitem(
        ITEM_EFFECTS, "Vampiric Scepter", {"type": "sustain", "lifesteal_percent": 7.0}
    )
    with pytest.raises(KeyError, match="Vampiric Scepter.*source_url"):
        sustain_stat_receipt("Vampiric Scepter", "lifesteal_percent")


def test_grouped_sustain_stat_sums_lifesteal_across_a_build():
    """The grouped receipt adds every typed lifesteal stat in the build."""
    assert grouped_sustain_stat_percent(
        _items("Blade of the Ruined King", "Bloodthirster"), "lifesteal_percent"
    ) == pytest.approx(25.0)
    assert grouped_sustain_stat_percent(
        _items("Vampiric Scepter", "Mercurial Scimitar"), "lifesteal_percent"
    ) == pytest.approx(17.0)
    assert grouped_sustain_stat_percent(
        _items("Ravenous Hydra"), "lifesteal_percent"
    ) == pytest.approx(12.0)


def test_grouped_sustain_aggregates_into_loadout_stats(ahri_data):
    """stats.py folds the typed lifesteal into the loadout stats."""
    stats = calculate_total_stats(
        ahri_data,
        18,
        _items("Blade of the Ruined King", "Bloodthirster"),
    )
    assert stats["lifesteal_percent"] == pytest.approx(25.0)
    stats = calculate_total_stats(
        ahri_data, 18, _items("Vampiric Scepter", "Mercurial Scimitar")
    )
    assert stats["lifesteal_percent"] == pytest.approx(17.0)


def test_dorans_blade_typed_override_zeroes_stale_omnivamp(ahri_data):
    """Life Draining replaced the old omnivamp stat; the override wins."""
    assert grouped_sustain_stat_percent(
        _items("Doran's Blade"), "omnivamp_percent"
    ) == pytest.approx(0.0)
    stats = calculate_total_stats(ahri_data, 18, _items("Doran's Blade"))
    assert stats["omnivamp_percent"] == pytest.approx(0.0)


def test_heal_shield_power_aggregates_into_loadout_stats(ahri_data):
    """Heal-and-shield power remains a sourced loadout stat."""
    stats = calculate_total_stats(ahri_data, 18, _items("Ardent Censer"))
    assert stats["heal_and_shield_power_percent"] == pytest.approx(10.0)


def test_cull_three_health_on_hit_is_typed_and_heals_per_auto():
    """Reap's 3 health on-hit is the typed term, not a parsed guess."""
    assert sustain_effect_value("Cull", "health_per_on_hit") == pytest.approx(3.0)
    params = FightParams.from_request(
        {
            "fight_mode": "timed",
            "fight_duration": 4,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "target_armor": 0,
            "target_mr": 0,
            "target_health": 5000,
        }
    )
    result = run_fight(get_champion("Ahri"), 18, _items("Cull"), params)
    reap = [
        event
        for event in result["self_healing_events"]
        if event["source"] == "Cull (Reap)"
    ]
    assert reap
    assert [event["amount"] for event in reap] == pytest.approx(
        [3.0] * result["breakdown"]["auto_attacks"]["count"]
    )


def test_calculate_botrk_bloodthirster_heals_sourced_lifesteal_per_auto():
    """A BotRK+Bloodthirster build heals 25% of post-mitigation auto damage."""
    data = _calculate(["Blade of the Ruined King", "Bloodthirster"], duration=5)
    assert data["champion_stats"]["lifesteal_percent"] == pytest.approx(25.0)
    vamp_events = [
        event
        for event in data["self_healing_events"]
        if "Life steal" in event["source"]
    ]
    assert vamp_events
    auto_damage = data["breakdown"]["auto_attacks"]["total_damage"]
    bork_damage = data["breakdown"]["on_hit_Blade of the Ruined King"]["total_damage"]
    assert data["breakdown"]["heal_lifesteal"]["total_amount"] == pytest.approx(
        0.25 * (auto_damage + bork_damage), abs=0.5
    )


def test_calculate_participant_timeline_sustain_receipts_include_lifesteal():
    """The roster timeline's healing_received counts the item lifesteal."""
    data = _calculate(
        ["Blade of the Ruined King", "Bloodthirster"],
        enemies=[{"champion": "Aatrox", "level": 18}],
        duration=5,
    )
    main = next(
        row for row in data["combat"]["participants"] if row["participant_id"] == "main"
    )
    vamp = [
        event
        for event in data["combat"]["healing_events"]
        if event["attacker"] == "main" and "Life steal" in event.get("source", "")
    ]
    assert vamp
    vamp_total = sum(event["amount"] for event in vamp)
    assert main["survival"]["healing_received"] >= vamp_total
    assert vamp_total > 0


# ---------------------------------------------------------------------------
# Issue #43 — Guinsoo's Rageblade Seething Strike (0-32% attack speed)
# ---------------------------------------------------------------------------


def test_guinsoo_seething_strike_stacks_typed_and_fight_accelerates():
    """8% per stack, 4 stacks = 32%; the authored fight schedule uses it."""
    assert required_effect_value(
        "Guinsoo's Rageblade", "seething_attack_speed_per_stack"
    ) == pytest.approx(0.08)
    assert required_effect_value("Guinsoo's Rageblade", "seething_max_stacks") == 4
    assert required_effect_value(
        "Guinsoo's Rageblade", "seething_duration"
    ) == pytest.approx(3.0)
    ramp = charged_strike.resolve_slots(
        ["Guinsoo's Rageblade"],
        level=18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    ).swing_schedule.ramp
    assert ramp.bonus_percent(0) == 0.0
    assert ramp.bonus_percent(4) == pytest.approx(32.0)

    baseline = _calculate([])
    guinsoo = _calculate(["Guinsoo's Rageblade"])
    # Seething's rising AS pulls more autos into the same timed window, and
    # the phantom hit applies the 30 magic on-hit one extra time (N autos ->
    # N + 1 on-hit applications).
    assert (
        guinsoo["auto_attack_schedule"]["expected_autos_total"]
        > baseline["auto_attack_schedule"]["expected_autos_total"]
    )
    row = guinsoo["breakdown"]["on_hit_Guinsoo's Rageblade"]
    assert row["count"] == guinsoo["auto_attack_schedule"]["expected_autos_total"] + 1
    assert row["damage_per_hit"] == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Issue #43 — Lich Bane empowered-attack bonus attack speed
# ---------------------------------------------------------------------------


def test_lich_bane_empowered_attack_bonus_as_typed_and_priced():
    """Spellblade's 50% bonus AS is a typed sibling and reaches the fight."""
    entry = ITEM_EFFECTS["Lich Bane"]
    assert entry["type"] == "spellblade"
    assert entry["bonus_attack_speed_percent"] == pytest.approx(50.0)
    assert entry["ap_ratio"] == pytest.approx(0.45)

    data = _calculate(["Lich Bane"])
    stats = data["champion_stats"]
    row = data["breakdown"]["spellblade_Lich Bane"]
    assert row["count"] >= 1
    assert row["damage_per_hit"] == pytest.approx(
        0.75 * stats["base_attack_damage"] + 0.45 * stats["ability_power"]
    )


# ---------------------------------------------------------------------------
# Issue #43 — Essence Reaver Spellblade mana restoration
# ---------------------------------------------------------------------------


def test_essence_reaver_spellblade_mana_restore_typed_and_wired():
    """Manaflow's 62.5% base AD + crit share restores mana in the fight."""
    assert required_effect_value(
        "Essence Reaver", "mana_restore_base_ad_ratio"
    ) == pytest.approx(0.625)
    assert required_effect_value(
        "Essence Reaver", "mana_restore_crit_ratio"
    ) == pytest.approx(25.0)
    # 0.625 x 100 base AD + 25 x (50% crit / 100) = 75.0
    assert essence_reaver_mana_restore_per_proc(
        base_attack_damage=100, critical_strike_chance=50
    ) == pytest.approx(75.0)

    data = _calculate(["Essence Reaver"])
    stats = data["champion_stats"]
    row = data["breakdown"]["mana_Essence Reaver"]
    assert row["unit"] == "mana"
    assert row["amount_per_proc"] == pytest.approx(
        essence_reaver_mana_restore_per_proc(
            base_attack_damage=stats["base_attack_damage"],
            critical_strike_chance=stats["critical_strike_chance"],
        ),
        abs=0.1,  # the API rounds the mana receipt to one decimal
    )
    assert row["count"] == data["breakdown"]["spellblade_Essence Reaver"]["count"]


# ---------------------------------------------------------------------------
# Issue #43 — Dusk and Dawn (Spellblade + second on-hit application)
# ---------------------------------------------------------------------------


def test_dusk_and_dawn_spellblade_typed_and_double_on_hit_wired():
    """The second on-hit application hits the same target (wiki: 'again')."""
    entry = ITEM_EFFECTS["Dusk and Dawn"]
    assert entry["type"] == "spellblade"
    assert entry["double_on_hit"] is True
    assert entry["self_heal_ap_ratio"] == pytest.approx(0.10)
    assert entry["self_heal_bonus_health_ratio"] == pytest.approx(0.03)

    data = _calculate(["Dusk and Dawn", "Nashor's Tooth"])
    spellblade = data["breakdown"]["spellblade_Dusk and Dawn"]
    doubled = data["breakdown"]["double_on_hit_Dusk and Dawn"]
    # Every spellblade proc applies the on-hit set one additional time to
    # the same target (the wiki's 0.2s-delayed 'again' application); this is
    # not a multi-target split, so the breakdown stays on the selected target.
    assert doubled["count"] == spellblade["count"]
    heal = data["breakdown"]["heal_Dusk and Dawn"]
    assert heal["amount_per_proc"] == pytest.approx(
        0.10 * data["champion_stats"]["ability_power"]
        + 0.03 * data["champion_stats"]["bonus_health"]
    )


# ---------------------------------------------------------------------------
# Issue #43 — Hydra cleave secondary-target damage (documented boundary)
# ---------------------------------------------------------------------------


def test_hydra_cleave_secondary_cone_typed_and_boundary_documented():
    """Cleave's cone packet is typed; the single-target model documents it."""
    # Sourced cone numbers: melee 40% AD / ranged 20% AD to OTHER enemies in
    # a 350-radius cone centered on the attack target (Tiamat/Ravenous).
    assert hydra_cleave_secondary_ad_damage(
        total_attack_damage=250, is_melee=True, item_name="Tiamat"
    ) == pytest.approx(100.0)
    assert hydra_cleave_secondary_ad_damage(
        total_attack_damage=250, is_melee=False, item_name="Tiamat"
    ) == pytest.approx(50.0)
    # Titanic's Cleave is max-health based: 3% melee / 1.5% ranged of max HP
    # to secondary targets.
    assert hydra_secondary_target_damage(
        max_health=3000, is_melee=True
    ) == pytest.approx(90.0)
    assert hydra_secondary_target_damage(
        max_health=3000, is_melee=False
    ) == pytest.approx(45.0)
    # The selected target never receives the splash (wiki: 'other enemies').
    # Tiamat carries the explicit boundary note; the single-target fight
    # prices only the primary target, so no guessed cone damage enters the
    # ledger.
    assert "unmodeled_splash_note" in ITEM_EFFECTS["Tiamat"]

    data = _calculate(["Titanic Hydra"])
    assert (
        data["breakdown"]["on_hit_Titanic Hydra"]["count"]
        == data["auto_attack_schedule"]["expected_autos_total"]
    )
    assert data["breakdown"]["active_Titanic Hydra"]["count"] == 1


# ---------------------------------------------------------------------------
# Issue #43 — Energized cadence (Statikk / RFC / Stormrazor / Voltaic)
# ---------------------------------------------------------------------------


def test_energized_source_receipt_pins_e9_bis_cadence():
    """Every Energized item's own typed cadence cites the E9-BIS Tip data."""
    assert ENERGIZED_SOURCE_RECEIPT["source_revision_id"] == 4013385
    for item_name in (
        "Statikk Shiv",
        "Rapid Firecannon",
        "Stormrazor",
        "Voltaic Cyclosword",
    ):
        effect = ITEM_EFFECTS[item_name]
        assert effect["energized_max_stacks"] == 100
        assert effect["energized_distance_units_per_stack"] == 24.0
        receipt = energized_schedule_receipt(item_name)
        assert receipt["source_revision_id"] == 4013385
        assert receipt["max_stacks"] == 100
        assert receipt["distance_units_per_stack"] == 24.0


def test_energized_attack_cadence_is_typed_per_item():
    """Statikk adds 9 bonus stacks per attack (6 base + 9 = 15 total)."""
    statikk = ITEM_EFFECTS["Statikk Shiv"]
    assert statikk["energized_attack_stacks"] == 15
    assert statikk["energized_max_stacks"] == 100
    # 100 / 15 per attack -> the 7th attack procs from an empty charge.
    assert energized_proc_indices("Statikk Shiv", 20, initial_stacks=0) == (7, 14)
    assert energized_proc_indices("Statikk Shiv", 3, initial_stacks=100) == (0,)


def test_energized_statikk_fight_asserts_proc_and_chain_receipts():
    """The API fight procs Electrospark once and stamps the chain packet."""
    data = _calculate(["Statikk Shiv"])
    row = data["breakdown"]["on_hit_once_Statikk Shiv"]
    assert row["count"] == 1
    assert row["damage_per_hit"] == pytest.approx(60.0)
    assert row["targeting"]["kind"] == "chain_lightning"
    assert row["targeting"]["chain_target_count"] > 1
    # The engine assumes the walk-in starts fully charged (100 stacks), so
    # the first auto procs; the cadence itself is pinned by the E9 receipt
    # and energized_proc_indices above.
    assert row["targeting"]["allocated_target_index"] == 0
