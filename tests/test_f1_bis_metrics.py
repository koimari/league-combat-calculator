"""F1: BIS + metrics regressions reported by the product owner.

Covers the four reported bugs:

1. The Best-in-Slot trigger renders on every attacker build A/B item slot and
   every enemy/ally roster slot, disabled with an explanatory tooltip when the
   slot lacks champion/role context (frontend wiring assertions).
2. ``/api/bis`` excludes the item currently occupying the ranked slot from
   that slot's candidate pool (the unchanged build is not a "best" pick),
   while the same item remains a candidate for every other slot.
3. The comparison panel shows the real timeline time-to-death (never "0 s")
   and surfaces the surviving enemy's remaining HP when a build does not kill.
4. The main output shows an Overkill figure (TDD - enemy effective HP when
   positive) next to the TDD and surfaces enemy eHP; ``/api/calculate``
   exposes ``overkill`` and ``target_effective_health``.
"""

from pathlib import Path

import pytest

import src.app as app_module
from src.calculator.bis import bis_candidate_pool


@pytest.fixture(autouse=True)
def _disable_rate_limits_between_tests():
    """Only dedicated tests spend the production abuse-control budget."""
    previous = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    yield
    app_module.app.config["RATE_LIMIT_ENABLED"] = previous


def _bis_payload(**overrides):
    """One focused BIS request (Aatrox top vs Ambessa, with Lulu support)."""
    payload = {
        "champion": "Aatrox",
        "level": 18,
        "items": ["Infinity Edge", "Bloodthirster"],
        "boots": "Plated Steelcaps",
        "role": "top",
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
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
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
        "allies": [
            {
                "champion": "Lulu",
                "level": 18,
                "items": [],
                "role": "support",
                "ally_effects_enabled": True,
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
        ],
    }
    payload.update(overrides)
    return payload


def _top_role_candidate_names() -> list[str]:
    """The exact pre-exclusion candidate pool /api/bis would use for slot 0."""
    pool = bis_candidate_pool(
        "item",
        boots_tier=2,
        role="top",
        role_quest_complete=False,
    )
    return [item["name"] for item in pool]


# ---------------------------------------------------------------------------
# Bug 2: BIS must not recommend the item already occupying the ranked slot
# ---------------------------------------------------------------------------


def test_bis_does_not_recommend_the_item_already_in_the_ranked_slot():
    """Malignance sits in slot 1; ranking slot 1 must exclude it entirely."""
    client = app_module.app.test_client()
    body = client.post(
        "/api/bis",
        json=_bis_payload(items=["Infinity Edge", "Malignance"], slot_index=1),
    ).get_json()

    assert body["excluded_equipped_item"] == "Malignance"
    assert body["candidate_count"] > 0
    ranked = [row["name"] for row in body["candidates"]]
    assert ranked
    assert "Malignance" not in ranked
    assert all(row["name"] != "Malignance" for row in body["partial_candidates"])


def test_bis_equipped_exclusion_shrinks_the_candidate_pool_by_one():
    """The exclusion removes exactly the equipped item from this slot's pool."""
    client = app_module.app.test_client()
    body = client.post(
        "/api/bis",
        json=_bis_payload(items=["Malignance", "Bloodthirster"], slot_index=0),
    ).get_json()

    pool_names = _top_role_candidate_names()
    assert "Malignance" in pool_names
    expected = [name for name in pool_names if name != "Malignance"]
    assert body["candidate_count"] == len(expected)
    assert body["excluded_equipped_item"] == "Malignance"


def test_bis_moving_the_item_to_another_slot_makes_it_a_candidate_again():
    """Infinity Edge moved out of slot 0 is eligible for slot 0 again."""
    client = app_module.app.test_client()
    body = client.post(
        "/api/bis",
        json=_bis_payload(
            items=["Malignance", "Bloodthirster", "Infinity Edge"],
            slot_index=0,
        ),
    ).get_json()

    assert body["excluded_equipped_item"] == "Malignance"
    pool = [row["name"] for row in body["candidates"]]
    pool += [row["name"] for row in body["partial_candidates"]]
    pool += [row["name"] for row in body["withheld_candidates"]]
    assert "Infinity Edge" in pool


def test_bis_boots_slot_excludes_the_equipped_boots():
    client = app_module.app.test_client()
    body = client.post(
        "/api/bis",
        json=_bis_payload(slot_kind="boots", slot_index=0),
    ).get_json()

    assert body["excluded_equipped_item"] == "Plated Steelcaps"
    ranked = [row["name"] for row in body["candidates"]]
    assert ranked
    assert "Plated Steelcaps" not in ranked


def test_bis_empty_slot_has_no_equipped_item_to_exclude():
    """A slot with no item keeps the full candidate pool."""
    client = app_module.app.test_client()
    body = client.post(
        "/api/bis",
        json=_bis_payload(items=["Infinity Edge"], slot_index=3),
    ).get_json()

    assert body["excluded_equipped_item"] is None
    assert body["candidate_count"] == len(_top_role_candidate_names())


def test_bis_enemy_slot_excludes_the_enemy_s_equipped_item():
    """Roster BIS applies the same exclusion to enemy subjects."""
    client = app_module.app.test_client()
    body = client.post(
        "/api/bis",
        json=_bis_payload(
            subject_team="enemy",
            subject_index=0,
            slot_index=0,
            enemies=[
                {
                    "champion": "Ambessa",
                    "level": 18,
                    "items": ["Stridebreaker"],
                    "role": "top",
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                }
            ],
        ),
    ).get_json()

    assert body["excluded_equipped_item"] == "Stridebreaker"
    ranked = [row["name"] for row in body["candidates"]]
    assert ranked
    assert "Stridebreaker" not in ranked


# ---------------------------------------------------------------------------
# Bug 4 (backend): overkill + enemy effective health in /api/calculate
# ---------------------------------------------------------------------------


def _burst_payload() -> dict:
    """Ahri burst vs a squishy mid enemy that dies inside the window."""
    return {
        "champion": "Ahri",
        "level": 11,
        "items": ["Luden's Echo", "Liandry's Torment", "Shadowflame", "Void Staff"],
        "boots": "Sorcerer's Shoes",
        "role": "mid",
        "ability_ranks": {"Q": 5, "W": 3, "E": 2, "R": 1},
        "enemies": [
            {
                "champion": "Ziggs",
                "level": 11,
                "items": [],
                "role": "mid",
                "ability_ranks": {"Q": 5, "W": 3, "E": 2, "R": 1},
            }
        ],
        "allies": [],
        "fight_mode": "time_based",
        "fight_duration": 8,
        "include_auto_attacks": True,
        "auto_attack_uptime_mode": "calculated",
    }


def test_calculate_exposes_overkill_and_target_effective_health():
    client = app_module.app.test_client()
    body = client.post("/api/calculate", json=_burst_payload()).get_json()

    expected_ehp = (
        float(body["target_effective_max_health"])
        + float(body["shield_absorbed"])
        + float(body["target_healing_received"])
    )
    assert body["target_effective_health"] == pytest.approx(expected_ehp)
    expected_overkill = max(0.0, float(body["total_damage"]) - expected_ehp)
    assert body["overkill"] == pytest.approx(expected_overkill)
    assert body["overkill"] > 0  # burst exceeds the squishy target's eHP


def test_calculate_combat_ledger_carries_exact_participant_overkill():
    """The coupled combat response already reports overkill per participant."""
    client = app_module.app.test_client()
    body = client.post("/api/calculate", json=_burst_payload()).get_json()

    enemy = next(
        row
        for row in body["combat"]["participants"]
        if row["participant_id"] == "enemy:Ziggs"
    )
    assert "overkill" in enemy["survival"]
    assert enemy["survival"]["overkill"] > 0
    assert enemy["survival"]["effective_health"] > 0


# ---------------------------------------------------------------------------
# Bug 1 (frontend): BIS trigger on every slot + disabled-with-tooltip state
# ---------------------------------------------------------------------------


def _app_source() -> str:
    return Path("static/js/app.js").read_text(encoding="utf-8")


def test_frontend_renders_a_bis_trigger_on_every_slot():
    source = _app_source()
    css = Path("static/css/style.css").read_text(encoding="utf-8")

    assert "function bisTrigger(path, compact = false)" in source
    # Attacker build A/B slots and quest boots carry the trigger on the duel
    # canvas; enemy and ally roster slots carry the same compact trigger.
    assert "${bisTrigger(path, true)}</div>" in source
    assert "${row}${bisTrigger(path, true)}" in source
    assert ".duel-slot > .bis-trigger" in css
    assert 'data-bis-path="${path}"' in source
    assert '"Rank every legal item for this slot"' in source
    assert ".bis-trigger" in css


def test_frontend_bis_trigger_disables_with_context_tooltip():
    source = _app_source()

    assert "Needs a champion and role on this enemy" in source
    assert "Needs a champion and role on this ally" in source
    assert '${ready ? "" : "disabled"}' in source
    assert "const ready = bisReadyForPath(path);" in source


# ---------------------------------------------------------------------------
# Bug 3 (frontend): kill time never "0 s", surviving HP shown
# ---------------------------------------------------------------------------


def test_frontend_kill_time_never_displays_zero_and_shows_surviving_hp():
    source = _app_source()

    assert "function killTimeLabel(value)" in source
    assert 'seconds < 0.05 ? "<1 s" :' in source
    assert "function enemyHealthRemaining(result)" in source
    assert "alive · ${fmt(ending)} HP" in source
    # The delta spine feeds the surviving-HP receipt into the kill-time row
    # for both builds (it replaced prototypeMetricRow in the redesign).
    spine = source.split('$("metricList").innerHTML = SPINE_METRICS')[1].split(
        '.join("")'
    )[0]
    assert 'metric.lower ? aAlive : ""' in spine
    assert 'metric.lower ? bAlive : ""' in spine
    row = source.split("function spineRowHtml(")[1].split("\nfunction ")[0]
    assert "metricValueLabel(metric, aValue, aAlive" in row
    # The receipt is never lost to the 52px column: it rides as the cell's
    # title and in the row's accessible name.
    assert "title=" in row and "aria-label=" in row
    label = source.split("function metricValueLabel(")[1].split("\nfunction ")[0]
    assert "killTimeLabel(value)" in label
    # The old formatting that rendered a defeat as "0 s" is gone: every
    # kill-time label now routes through killTimeLabel().
    assert (
        'return metric.lower ? (killTimeLabel(value) || alive || "—") : fmt(value);'
        in label
    )


# ---------------------------------------------------------------------------
# Bug 4 (frontend): overkill + enemy eHP in the main output
# ---------------------------------------------------------------------------


def test_frontend_main_output_adds_overkill_and_enemy_ehp():
    source = _app_source()

    assert "function enemyOverkill(result, totalDamage)" in source
    assert "function enemyEffectiveHealth(result)" in source
    assert (
        '${fmt(aTotal)} TDD${overkill > 0 ? ` · ${fmt(overkill)} overkill` : ""}'
        in source
    )
    assert '<div class="ledger-line"><span>Enemy effective HP</span>' in source
