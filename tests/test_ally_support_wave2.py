"""Wave-2 ally-support coverage (HANDOVER 8.5) for the coordinator's
support champions: Nami W return bounce, Yuumi R Best Friend bonus and
overheal-to-shield conversion, and Renata E all-teammate shield spread.

Every packet amount is priced from the cached leveling rows through the
typed atom catalog; the tests pin the atom hashes so a data drift fails
closed at the assertion instead of silently changing a formula.

Existing packets (Sona W aura shield/heal, Janna E, Milio W, Ivern E,
Karma E, Seraphine W, Taric W/R/Q, Rakan Q/E/P, Yuumi E) are asserted as
regression pins only where this wave adds packets beside them; their
full coverage lives in tests/test_e8_support.py and
tests/test_support_effects.py.
"""

import pytest

from src import app as app_module
from src.calculator.data_fetcher import get_champion
from src.calculator.support_effects import derive_ally_effects

# ---------------------------------------------------------------------------
# Unit-level packet derivation
# ---------------------------------------------------------------------------


def _effects(champion, *, level=18, ap=0.0, casts=None, ranks=None):
    data = get_champion(champion)
    stats = {
        "ability_power": ap,
        "bonus_attack_damage": 0.0,
        "health": 2000.0,
    }
    return derive_ally_effects(
        data,
        level,
        stats,
        casts or [{"slot": "W", "time": 1.0}],
        ability_ranks=ranks,
    )


def _nami_effects(*, ap=0.0, casts=None):
    return _effects("Nami", ap=ap, casts=casts)


def test_nami_w_emits_base_heal_and_sourced_return_bounce():
    effects = _nami_effects()

    heals = [e for e in effects if e["kind"] == "heal"]
    assert len(heals) == 2
    base, bounce = heals
    assert base["source"] == "Ebb and Flow · Heal"
    assert base["amount"] == pytest.approx(155.0)
    assert base["target_selection_key"] == "heal:W:0"
    # The second bounce keeps 60% of the original at 0 AP — exactly the
    # sourced Minimum Heal row (93 = 0.6 x 155 at rank 5).
    assert bounce["source"] == "Ebb and Flow · Return Bounce"
    assert bounce["amount"] == pytest.approx(93.0)
    assert bounce["target_scope"] == "one_teammate"
    assert bounce["target_selection_key"] == "heal:W:0:bounce"
    assert [atom["atom_id"] for atom in bounce["source_atoms"]] == [
        "ability.heal.modifier_0",
        "ability.minimum _heal.modifier_0",
    ]
    assert bounce["source_atoms"][0]["hash"] == "8e0ea6f54dbba943"
    assert bounce["source_atoms"][1]["hash"] == "d8d151fc238186ff"


def test_nami_return_bounce_scales_with_ap_and_floors_at_minimum():
    # 100 AP: heal = 195, minimum = 117, second-bounce factor =
    # 0.60 + 0.30 x 100/100 = 0.90 -> 175.5.
    effects = _nami_effects(ap=100.0)
    bounce = next(e for e in effects if e["kind"] == "heal" and "Bounce" in e["source"])
    assert bounce["amount"] == pytest.approx(175.5)
    # 400 AP: heal = 315, factor = 0.60 + 0.30 x 4 = 1.80 -> 567 (no
    # upper clamp; the same linear extension the E1 first-bounce rule
    # uses).
    effects = _nami_effects(ap=400.0)
    bounce = next(e for e in effects if e["kind"] == "heal" and "Bounce" in e["source"])
    assert bounce["amount"] == pytest.approx(567.0)


def test_nami_repeated_casts_get_distinct_bounce_selection_keys():
    effects = _nami_effects(
        casts=[
            {"slot": "W", "time": 0.0},
            {"slot": "W", "time": 5.0},
        ]
    )
    keys = {
        e["target_selection_key"]
        for e in effects
        if e["kind"] == "heal" and "Bounce" in e["source"]
    }
    assert keys == {"heal:W:0:bounce", "heal:W:1:bounce"}


def test_yuumi_r_emits_base_heal_best_friend_bonus_and_conversions():
    effects = _effects(
        "Yuumi",
        casts=[{"slot": "R", "time": 1.0}],
        ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
    )

    heals = [e for e in effects if e["kind"] == "heal"]
    assert len(heals) == 2
    base, bonus = heals
    assert base["source"] == "Final Chapter · Total Heal"
    assert base["amount"] == pytest.approx(350.0)
    assert base["target_selection_key"] == "heal:R:0"
    # Level 18 -> the per-level row's last bracket: 60% of 350.
    assert bonus["source"] == "Final Chapter · Best Friend Bonus"
    assert bonus["amount"] == pytest.approx(210.0)
    assert bonus["target_selection_key"] == "heal:R:0:best_friend"
    assert [atom["atom_id"] for atom in bonus["source_atoms"]] == [
        "ability.total _heal.modifier_0",
        "ability.per-_level _scaling",
    ]
    assert bonus["source_atoms"][0]["hash"] == "bc2763eff82ff86e"
    assert bonus["source_atoms"][1]["hash"] == "95f12244ccd7928f"

    shields = [e for e in effects if e["kind"] == "shield"]
    assert len(shields) == 2
    for shield in shields:
        assert shield["source"] == "Final Chapter · Overheal Conversion"
        assert shield["amount"] == 0.0
        assert shield["duration"] == pytest.approx(5.0)  # 1.5 + 3.5 channel
        assert shield["duration_atom"]["hash"] == "fa7f501d3d399129"
        assert [a["hash"] for a in shield["source_atoms"]] == [
            "fa7f501d3d399129",
            "df97a8de9596e829",
        ]
    base_shield, bonus_shield = shields
    # The conversion rides its parent heal's selection key (it lands on
    # whoever was healed), so the two shields pair with the two heals.
    assert base_shield["target_selection_key"] == "heal:R:0"
    assert bonus_shield["target_selection_key"] == "heal:R:0:best_friend"
    # Live excess formula: full-health target converts the whole heal;
    # a target missing 100 health converts heal - 100.
    assert base_shield["amount_formula"](2000.0, 2000.0) == pytest.approx(350.0)
    assert base_shield["amount_formula"](1900.0, 2000.0) == pytest.approx(250.0)
    assert bonus_shield["amount_formula"](2000.0, 2000.0) == pytest.approx(210.0)
    assert bonus_shield["amount_formula"](1000.0, 2000.0) == pytest.approx(0.0)


def test_yuumi_best_friend_bonus_reads_the_per_level_row_at_level_one():
    effects = _effects(
        "Yuumi",
        level=1,
        casts=[{"slot": "R", "time": 1.0}],
        ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
    )
    bonus = next(
        e for e in effects if e["kind"] == "heal" and "Best Friend" in e["source"]
    )
    # Level 1 -> first bracket: 30% of 350.
    assert bonus["amount"] == pytest.approx(105.0)


def test_renata_e_ally_packets_scope_all_selected_teammates():
    effects = _effects("Renata Glasc", casts=[{"slot": "E", "time": 1.0}])

    ally_shields = [e for e in effects if e["kind"] == "shield"]
    assert len(ally_shields) == 1
    shield = ally_shields[0]
    assert shield["source"] == "Loyalty Program · Shield Strength"
    assert shield["target_scope"] == "all_teammates"
    assert shield["target_self"] is False
    assert shield["amount"] == pytest.approx(110.0)
    assert shield["duration"] == pytest.approx(3.0)
    assert shield["target_selection_key"] == "shield:E:0"


# ---------------------------------------------------------------------------
# Roster-level ledger behavior
# ---------------------------------------------------------------------------


def _roster_combat(champion, *, allies=None, selections=None, duration=6.0):
    """Run /api/calculate with *champion* as main and allies in the roster."""
    return _roster_combat_impl(champion, allies, selections, duration)


def _roster_combat_impl(champion, allies, selections, duration):
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": False,
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        "allies": allies
        or [
            {
                "champion": "Jinx",
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            }
        ],
        "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
    }
    if selections:
        payload["support_target_selections"] = selections
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    return response.get_json()["combat"]


def _support(combat, source_prefix):
    return [
        e
        for e in combat["support_events"]
        if e.get("attacker") == "main"
        and str(e.get("source", "")).startswith(source_prefix)
    ]


def test_nami_bounce_reaches_the_ally_ledger_and_respects_selection():
    combat = _roster_combat("Nami")
    events = _support(combat, "Ebb and Flow")
    assert [e["kind"] for e in events] == ["heal", "heal"]
    assert events[0]["amount"] == pytest.approx(155.0)  # E8d pin preserved
    assert events[1]["amount"] == pytest.approx(93.0)
    assert events[1]["target_selection_key"] == "heal:W:0:bounce"
    assert {e["target"] for e in events} == {"ally:Jinx"}

    ally_row = next(
        row for row in combat["participants"] if row["participant_id"] == "ally:Jinx"
    )
    assert ally_row["survival"]["healing_received"] == pytest.approx(248.0)

    # The return bounce is independently selectable: send it to Ashe.
    combat = _roster_combat(
        "Nami",
        allies=[
            {
                "champion": "Jinx",
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            },
            {
                "champion": "Ashe",
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            },
        ],
        selections={"heal:W:0:bounce": 1},
    )
    events = _support(combat, "Ebb and Flow")
    by_key = {e["target_selection_key"]: e["target"] for e in events}
    assert by_key["heal:W:0"] == "ally:Jinx"
    assert by_key["heal:W:0:bounce"] == "ally:Ashe"
    assert (
        next(e for e in events if e["target_selection_key"] == "heal:W:0:bounce")[
            "target_policy"
        ]
        == "selected_teammate"
    )


def test_yuumi_r_best_friend_and_conversion_flow_into_the_ledger():
    combat = _roster_combat("Yuumi", duration=4.0)
    heals = [e for e in _support(combat, "Final Chapter") if e["kind"] == "heal"]
    assert heals[0]["amount"] == pytest.approx(350.0)  # E8d pin preserved
    assert heals[1]["amount"] == pytest.approx(210.0)
    conversions = [
        e for e in _support(combat, "Final Chapter") if e["kind"] == "shield"
    ]
    assert len(conversions) == 2
    # The ally is at full health when R lands, so the whole heal converts.
    assert all(e["applied_amount"] > 0.0 for e in conversions)
    assert sum(e["applied_amount"] for e in conversions) == pytest.approx(560.0)
    assert all(e["duration"] == pytest.approx(5.0) for e in conversions)

    ally_row = next(
        row for row in combat["participants"] if row["participant_id"] == "ally:Jinx"
    )
    assert ally_row["survival"]["support_shield_received"] >= 560.0

    # The bonus packet is independently selectable: send it to Ashe.
    combat = _roster_combat(
        "Yuumi",
        duration=4.0,
        allies=[
            {
                "champion": "Jinx",
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            },
            {
                "champion": "Ashe",
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            },
        ],
        selections={"heal:R:0:best_friend": 1},
    )
    events = _support(combat, "Final Chapter")
    base_events = [e for e in events if e["target_selection_key"] == "heal:R:0"]
    bonus_events = [
        e for e in events if e["target_selection_key"] == "heal:R:0:best_friend"
    ]
    assert {e["target"] for e in base_events} == {"ally:Jinx"}
    # The bonus heal and its conversion follow the same selection: Ashe.
    assert {e["target"] for e in bonus_events} == {"ally:Ashe"}
    assert any(e["kind"] == "shield" for e in bonus_events)


def test_renata_e_shields_every_selected_teammate_and_self_once():
    combat = _roster_combat(
        "Renata Glasc",
        allies=[
            {
                "champion": "Jinx",
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            },
            {
                "champion": "Ashe",
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            },
        ],
    )
    shields = _support(combat, "Loyalty Program")
    assert {e["target"] for e in shields} == {"main", "ally:Jinx", "ally:Ashe"}
    ally_shields = [e for e in shields if e["target"].startswith("ally:")]
    assert len(ally_shields) == 2
    assert all(e["target_policy"] == "all_selected_teammates" for e in ally_shields)
    assert all(e["amount"] == pytest.approx(110.0) for e in ally_shields)
    self_shields = [e for e in shields if e["target"] == "main"]
    assert len(self_shields) == 1  # module-authored self half, no double grant
    assert self_shields[0]["target_policy"] == "self"


def test_wave2_packets_compile_in_score_mode():
    """The score adapter compiles the same templates (shared kernel)."""
    from src.calculator.data_fetcher import get_champion
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.participant_timeline import build_participant_timeline
    from src.calculator.pipeline import FightParams
    from src.calculator.scenario import ChampionLoadout
    from src.calculator.stats import calculate_total_stats

    for champion in ("Nami", "Yuumi", "Renata Glasc"):
        main = get_champion(champion)
        stats = calculate_total_stats(main, 18, [])
        params = FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 4.0,
                "include_auto_attacks": False,
            },
            deterministic=True,
        )
        enemy = ChampionLoadout(champion="Aatrox", level=18, items=()).resolve()
        ally = ChampionLoadout(champion="Jinx", level=18, items=()).resolve()
        defenses = resolve_starting_defenses(champion, 18, stats, [])
        result = build_participant_timeline(
            main,
            18,
            [],
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=[enemy],
            allies=[ally],
            include_receipt=False,
        )
        assert result["timeline_coverage"]["complete"] is True
