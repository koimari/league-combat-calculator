"""Tests for the build optimizer."""

import pytest

from src.calculator import economy
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.loadout_rules import (
    ITEM_EXCLUSIVITY_GROUPS,
    exclusivity_groups,
    role_scoped_shop_items,
)
from src.calculator.optimizer import (
    _evaluate_build,
    _hill_climb,
    get_eligible_boots,
    get_eligible_legendaries,
    get_purchase_items,
    get_selectable_items,
    item_gold,
    optimize_purchase,
    optimizer_supported_items,
)
from src.calculator.optimizer import (
    optimize_build as _optimize_build,
)
from src.calculator.pipeline import FightParams

_FIGHT_PARAM_KEYS = {
    "target_health",
    "target_bonus_health",
    "target_armor",
    "target_mr",
    "fight_mode",
    "fight_duration",
    "include_auto_attacks",
    "auto_attack_uptime",
    "auto_attacks_only",
    "ability_ranks",
    "include_actives",
    "cast_order",
    "champion_options",
    "role",
    "role_quest_complete",
}


def optimize_build(_champion_name, champion_data, level, **kwargs):
    """Keep scenarios readable while exercising the public FightParams seam."""
    request_values = {
        key: kwargs.pop(key) for key in tuple(kwargs) if key in _FIGHT_PARAM_KEYS
    }
    fight_params = FightParams.from_request(request_values, deterministic=True)
    return _optimize_build(
        champion_data,
        level,
        fight_params=fight_params,
        **kwargs,
    )


class TestItemPools:
    """Tests for item pool loading."""

    def test_eligible_legendaries_not_empty(self):
        items = get_eligible_legendaries()
        assert len(items) > 100

    def test_eligible_legendaries_excludes_boots(self):
        items = get_eligible_legendaries()
        for item in items:
            assert "BOOTS" not in item.get("rank", [])

    def test_eligible_boots_not_empty(self):
        boots = get_eligible_boots()
        assert len(boots) >= 5

    def test_eligible_boots_are_tier_2_plus(self):
        boots = get_eligible_boots()
        for boot in boots:
            assert boot.get("tier") == 2

    def test_mid_quest_boot_pool_is_tier_3(self):
        boots = get_eligible_boots(tier=3)
        assert boots
        assert all(boot.get("tier") == 3 for boot in boots)

    def test_manual_pool_includes_components_and_starters(self):
        names = {item["name"] for item in get_selectable_items()}

        assert "Ruby Crystal" in names
        assert "Dark Seal" in names
        assert "Doran's Ring" in names
        assert "Boots of Swiftness" not in names

    @pytest.mark.parametrize(
        "name",
        [
            "Guardian's Amulet",
            "Guardian's Blade",
            "Guardian's Dirk",
            "Guardian's Hammer",
            "Guardian's Horn",
            "Guardian's Orb",
            "Guardian's Shroud",
            "Lifeline",
        ],
    )
    def test_pool_excludes_items_absent_from_summoners_rift(self, name):
        """ARAM starters and the Arena-only Soul Anchor item are not SR builds."""
        assert name not in {item["name"] for item in get_selectable_items()}

    def test_pool_excludes_champion_granted_items(self):
        """Black Spear is handed to Kalista and Sylas, never bought."""
        assert "Black Spear" not in {item["name"] for item in get_selectable_items()}

    def test_pool_excludes_quest_transforms_that_are_never_sold(self):
        """Bounty of Worlds only exists once the support quest transforms it."""
        pools = (
            get_selectable_items()
            + get_eligible_legendaries()
            + get_eligible_boots(None)
        )
        assert "Bounty of Worlds" not in {item["name"] for item in pools}

    def test_every_pool_item_is_available_on_summoners_rift(self):
        pools = (
            get_selectable_items()
            + get_eligible_legendaries()
            + get_eligible_boots(None)
        )
        off_rift = [
            item["name"] for item in pools if not item["modes"].get("classic sr 5v5")
        ]
        assert off_rift == []

    def test_main_optimizer_uses_the_sourced_role_shop_scope(self):
        candidates = get_eligible_legendaries()
        top = {item["name"] for item in role_scoped_shop_items(candidates, "top")}
        support = {
            item["name"] for item in role_scoped_shop_items(candidates, "support")
        }

        assert "Shurelya's Battlesong" not in top
        assert "Shurelya's Battlesong" in support
        assert "Warmog's Armor" in top
        assert "Warmog's Armor" not in support

    def test_top_search_never_evaluates_a_support_only_candidate(self, monkeypatch):
        def fake_evaluate(_champion, _level, items, **_kwargs):
            assert "Shurelya's Battlesong" not in {item["name"] for item in items}
            return 1.0

        monkeypatch.setattr("src.calculator.optimizer._evaluate_build", fake_evaluate)
        params = FightParams.from_request({"role": "top"}, deterministic=True)
        result = _optimize_build(
            get_champion("Aatrox"),
            6,
            fight_params=params,
            max_legendary_slots=1,
            include_boots=False,
        )

        assert "Shurelya's Battlesong" not in result["items"]


def test_evaluate_build_sums_objective_across_target_roster(monkeypatch):
    """One candidate build is scored into every selected enemy."""

    def fake_run_fight(_champion, _level, _items, params):
        damage = params.target_health / 10
        return {
            "total_damage": damage,
            "breakdown": {
                "spell": {
                    "damage_type": "magic",
                    "total_damage": damage,
                }
            },
        }

    monkeypatch.setattr("src.calculator.optimizer.run_fight", fake_run_fight)
    first = FightParams.from_request({"target_health": 1000}, deterministic=True)
    second = FightParams.from_request({"target_health": 2500}, deterministic=True)

    score = _evaluate_build({}, 1, [], (first, second), objective="magic_damage")

    assert score == 350


def test_hill_climb_reuses_greedy_score_without_duplicate_evaluation(monkeypatch):
    monkeypatch.setattr(
        "src.calculator.optimizer._evaluate_build",
        lambda *_args, **_kwargs: pytest.fail("duplicate initial evaluation"),
    )
    item = {"name": "Rabadon's Deathcap"}
    legendaries, boots, score, evals = _hill_climb(
        {},
        18,
        [item],
        None,
        locked_legendary_names=set(),
        locked_boots=True,
        pool=[],
        boots_pool=[],
        eval_kwargs={
            "fight_params": FightParams.from_request({}, deterministic=True),
            "objective": "total_damage",
        },
        max_iterations=0,
        initial_score=42.0,
    )

    assert legendaries == [item]
    assert boots is None
    assert score == 42.0
    assert evals == 0


def test_coupled_total_damage_does_not_add_effective_health_twice(monkeypatch):
    """Survival-coupled output is already truncated at the main actor's death."""
    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline",
        lambda *args, **kwargs: {
            "breakdown": [{"participant_id": "main", "total_damage": 125.0}],
            "participants": [
                {"participant_id": "main", "survival": {"effective_health": 4000.0}}
            ],
            "events": [],
            "timeline_coverage": {
                "complete": True,
                "exact_sources": [],
                "coarse_sources": [],
            },
        },
    )
    params = FightParams.from_request({}, deterministic=True)

    score = _evaluate_build(
        get_champion("Aatrox"),
        18,
        [],
        params,
        objective="total_damage",
        combat_context={"enemies": [object()], "allies": []},
    )

    assert score == 125.0


def test_coupled_equal_damage_uses_event_health_only_as_tie_break(monkeypatch):
    def fake_timeline(*_args, **kwargs):
        items = kwargs.get("items") or _args[2]
        health = (
            2_000.0
            if any(item["name"] == "Warmog's Armor" for item in items)
            else 1_000.0
        )
        return {
            "breakdown": [{"participant_id": "main", "total_damage": 500.0}],
            "participants": [
                {"participant_id": "main", "survival": {"effective_health": health}}
            ],
            "events": [],
            "timeline_coverage": {
                "complete": True,
                "exact_sources": [],
                "coarse_sources": [],
            },
        }

    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline", fake_timeline
    )
    result = optimize_build(
        "Aatrox",
        get_champion("Aatrox"),
        level=6,
        role="top",
        max_legendary_slots=1,
        include_boots=False,
        enemy_loadouts=[object()],
        require_complete_timeline=True,
    )

    assert result["total_damage"] == 500.0
    assert "Warmog's Armor" in result["items"]


def test_coupled_optimizer_rejects_partial_candidates_before_ranking(monkeypatch):
    """A partial item event cannot win the main champion's coupled search."""

    def fake_timeline(*_args, **kwargs):
        items = kwargs.get("items") or _args[2]
        partial = any(item.get("name") == "Unending Despair" for item in items)
        return {
            "breakdown": [{"participant_id": "main", "total_damage": 900.0}],
            "participants": [],
            "events": [],
            "timeline_coverage": {
                "complete": not partial,
                "exact_sources": [],
                "coarse_sources": ["periodic_Unending Despair"] if partial else [],
            },
        }

    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline", fake_timeline
    )
    result = optimize_build(
        "Aatrox",
        get_champion("Aatrox"),
        level=6,
        max_legendary_slots=1,
        locked_boots="Sorcerer's Shoes",
        enemy_loadouts=[object()],
        require_complete_timeline=True,
    )

    assert result["is_certified_best"] is True
    assert result["selection_certification"] == "event_ordered_local_search"
    assert "Unending Despair" not in result["items"]
    withheld = result["timeline_withheld_candidates"]
    assert any("Unending Despair" in row["items"] for row in withheld)
    assert all(
        row["timeline_coverage"]["complete"] is False
        for row in withheld
        if "Unending Despair" in row["items"]
    )
    assert all(
        row["reason"] == "candidate_withheld_partial_event_order"
        for row in withheld
        if "Unending Despair" in row["items"]
    )


def test_coupled_optimizer_excludes_audited_item_timing_before_ranking(monkeypatch):
    """Audited item timing gaps are receipts, not search-wide partials."""

    def fake_timeline(*_args, **kwargs):
        items = kwargs.get("items") or _args[2]
        excluded = any(item.get("name") == "Eclipse" for item in items)
        return {
            "breakdown": [{"participant_id": "main", "total_damage": 900.0}],
            "participants": [],
            "events": [],
            "timeline_coverage": {
                "complete": not excluded,
                "exact_sources": [] if excluded else ["Q"],
                "coarse_sources": ["proc_Eclipse"] if excluded else [],
            },
        }

    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline", fake_timeline
    )
    result = optimize_build(
        "Aatrox",
        get_champion("Aatrox"),
        level=6,
        max_legendary_slots=1,
        locked_boots="Sorcerer's Shoes",
        enemy_loadouts=[object()],
        require_complete_timeline=True,
    )

    coverage = result["search_timeline_coverage"]
    assert result["is_certified_best"] is True
    assert coverage["complete"] is True
    assert coverage["coarse_sources"] == []
    assert coverage["excluded_sources"] == ["proc_Eclipse"]
    assert coverage["excluded_evaluations"] > 0
    assert result["timeline_withheld_evaluations"] == 0
    assert result["timeline_excluded_evaluations"] > 0
    excluded = [
        row
        for row in result["timeline_withheld_candidates"]
        if "Eclipse" in row["items"]
    ]
    assert excluded
    assert all(
        row["reason"] == "candidate_excluded_unresolved_timing"
        and row["exclusion_type"] == "applicability"
        for row in excluded
    )


def test_uncoupled_optimizer_drops_partial_candidates_with_disclosed_rows(monkeypatch):
    """A pair-fight candidate dropped for a partial timeline names the drop."""

    def fake_run_fight(_champion_data, _level, items, _params):
        partial = any(item.get("name") == "Unending Despair" for item in items)
        return {
            "total_damage": 500.0,
            "breakdown": {},
            "timeline_coverage": {
                "complete": not partial,
                "exact_sources": [] if partial else ["Q"],
                "coarse_sources": ["periodic_Unending Despair"] if partial else [],
            },
        }

    monkeypatch.setattr("src.calculator.optimizer.run_fight", fake_run_fight)
    result = optimize_build(
        "Aatrox",
        get_champion("Aatrox"),
        level=6,
        max_legendary_slots=1,
        locked_boots="Sorcerer's Shoes",
        require_complete_timeline=True,
    )

    assert "Unending Despair" not in result["items"]
    withheld = [
        row
        for row in result["timeline_withheld_candidates"]
        if "Unending Despair" in row["items"]
    ]
    assert withheld
    assert all(
        row["reason"] == "candidate_withheld_partial_event_order"
        and row["timeline_coverage"]["complete"] is False
        for row in withheld
    )


def test_coupled_ranked_build_uses_its_participant_timeline_receipt(monkeypatch):
    """Ranked coupled rows must not fall back to raw pair-fight coverage."""

    def coupled_timeline(*_args, **_kwargs):
        return {
            "breakdown": [{"participant_id": "main", "total_damage": 900.0}],
            "participants": [
                {"participant_id": "main", "survival": {"effective_health": 1.0}}
            ],
            "events": [],
            "timeline_coverage": {
                "complete": True,
                "certification": "event_order_certified",
                "exact_sources": ["coupled_receipt"],
                "coarse_sources": [],
            },
        }

    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline", coupled_timeline
    )
    monkeypatch.setattr(
        "src.calculator.optimizer.run_fight",
        lambda *_args, **_kwargs: {
            "timeline_coverage": {
                "complete": False,
                "certification": "partial_event_order",
                "exact_sources": [],
                "coarse_sources": ["raw_pair_fallback"],
            }
        },
    )

    result = _optimize_build(
        get_champion("Aatrox"),
        level=6,
        max_legendary_slots=1,
        include_boots=False,
        enemy_loadouts=[object()],
        require_complete_timeline=True,
    )

    assert result["ranked_builds"]
    assert result["ranked_builds"][0]["timeline_coverage"] == {
        "complete": True,
        "certification": "event_order_certified",
        "exact_sources": ["coupled_receipt"],
        "coarse_sources": [],
    }


def test_coupled_evaluate_withholds_partial_timeline(monkeypatch):
    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline",
        lambda *_args, **_kwargs: {
            "breakdown": [{"participant_id": "main", "total_damage": 125.0}],
            "participants": [],
            "events": [],
            "timeline_coverage": {
                "complete": False,
                "exact_sources": [],
                "coarse_sources": ["periodic_item"],
            },
        },
    )
    params = FightParams.from_request({}, deterministic=True)
    score = _evaluate_build(
        get_champion("Aatrox"),
        18,
        [],
        params,
        objective="total_damage",
        require_complete_timeline=True,
        combat_context={"enemies": [object()], "allies": []},
    )

    assert score == float("-inf")


def test_audit_less_memo_entry_cannot_mute_a_dropped_candidate(monkeypatch):
    """The purchase baseline's memo entry must not silence the candidate audit.

    ``optimize_purchase`` scores the current loadout first, deliberately
    outside the candidate audit (``timeline_audit=None``).  When the search
    later proposes keeping that exact loadout, the audited evaluation must
    still disclose the require_complete_timeline drop instead of replaying
    the audit-less memo entry as a silent ``-inf``.
    """
    monkeypatch.setattr(
        "src.calculator.optimizer.build_participant_timeline",
        lambda *_args, **_kwargs: {
            "breakdown": [{"participant_id": "main", "total_damage": 125.0}],
            "participants": [],
            "events": [],
            "timeline_coverage": {
                "complete": False,
                "exact_sources": [],
                "coarse_sources": ["periodic_Unending Despair"],
            },
        },
    )
    params = FightParams.from_request({}, deterministic=True)
    combat_context = {
        "enemies": [object()],
        "allies": [],
        "pair_result_cache": {},
        "score_memo": {},
    }
    owned = [get_item_by_name("Unending Despair")]
    baseline = _evaluate_build(
        get_champion("Aatrox"),
        18,
        owned,
        params,
        objective="total_damage",
        timeline_audit=None,
        require_complete_timeline=True,
        combat_context=combat_context,
    )
    assert baseline == float("-inf")

    audit = {
        "evaluations": 0,
        "partial_evaluations": 0,
        "excluded_evaluations": 0,
        "exact_sources": set(),
        "coarse_sources": set(),
        "excluded_sources": set(),
        "build_coverages": {},
        "withheld_builds": {},
    }
    score = _evaluate_build(
        get_champion("Aatrox"),
        18,
        owned,
        params,
        objective="total_damage",
        timeline_audit=audit,
        require_complete_timeline=True,
        combat_context=combat_context,
    )

    assert score == float("-inf")
    assert audit["evaluations"] == 1
    assert audit["partial_evaluations"] == 1
    (row,) = audit["withheld_builds"].values()
    assert row["reason"] == "candidate_withheld_partial_event_order"


def test_optimizer_respects_gold_budget():
    result = optimize_build(
        "Ahri",
        get_champion("Ahri"),
        level=18,
        max_legendary_slots=2,
        gold_budget=7_000,
    )

    assert result["ranked_builds"]
    assert all(build["gold"] <= 7_000 for build in result["ranked_builds"])


def test_one_open_slot_is_exhaustive_for_modeled_items_and_has_runner_up():
    result = optimize_build(
        "Ahri",
        get_champion("Ahri"),
        level=18,
        max_legendary_slots=2,
        locked_items=["Rabadon's Deathcap"],
        locked_boots="Sorcerer's Shoes",
    )

    # Both halves of the conjunction hold: every legal candidate is
    # modelled, and every slot of Ahri's kit states its reviewed control,
    # so no candidate evaluates coarsely.
    assert result["is_certified_best"] is True
    assert result["search_guarantee"] == "exhaustive_legal_candidates"
    assert result["candidate_coverage"]["withheld_count"] == 0
    assert len(result["ranked_builds"]) == 2
    assert result["ranked_builds"][0]["items"] != result["ranked_builds"][1]["items"]


def test_candidate_coverage_alone_does_not_certify_a_coarse_search(
    monkeypatch,
):
    """Certification is a conjunction, and this is the half that fails.

    Candidate coverage is complete here by construction, but one candidate
    — Fimbulwinter — evaluates coarsely: Everlasting arms on an authored
    immobilize or slow, and Anivia's Q and R name themselves ``per_part``
    with no part answering, so their rows reach the ledger with no
    reviewed crowd-control state.  The search is exhaustive over a
    complete candidate set and still not certified, which is exactly the
    distinction the two coverage fields exist to keep apart.  The
    both-axes-true case is the test below, which makes the timelines exact
    as well.
    """
    monkeypatch.setattr(
        "src.calculator.optimizer.optimizer_candidate_coverage",
        lambda items: {
            "eligible_candidates": len(items),
            "scored_candidates": len(items),
            "withheld_count": 0,
            "complete": True,
            "excluded": [],
            "note": "Every available candidate is fully modelled.",
        },
    )

    result = optimize_build(
        "Anivia",
        get_champion("Anivia"),
        level=18,
        max_legendary_slots=2,
        locked_items=["Rabadon's Deathcap"],
        locked_boots="Sorcerer's Shoes",
    )

    assert result["candidate_coverage"]["complete"] is True
    assert result["candidate_coverage"]["withheld_count"] == 0
    assert result["search_guarantee"] == "exhaustive_legal_candidates"
    assert result["is_certified_best"] is False
    coverage = result["search_timeline_coverage"]
    assert coverage["complete"] is False
    assert coverage["excluded_evaluations"] == 0
    assert coverage["partial_evaluations"] == 1
    assert coverage["coarse_sources"] == ["fimbulwinter_everlasting"]


def test_one_open_slot_is_certified_when_candidates_and_timelines_are_complete(
    monkeypatch,
):
    monkeypatch.setattr(
        "src.calculator.optimizer.optimizer_candidate_coverage",
        lambda items: {
            "eligible_candidates": len(items),
            "scored_candidates": len(items),
            "withheld_count": 0,
            "complete": True,
            "excluded": [],
            "note": "Every available candidate is fully modelled.",
        },
    )

    def exact_fight(_champion, _level, items, _params):
        damage = float(len(items) * 100)
        return {
            "total_damage": damage,
            "breakdown": {},
            "timeline_coverage": {
                "complete": True,
                "certification": "event_order_certified",
                "exact_sources": [],
                "coarse_sources": [],
                "note": "Every active damage source is event-ordered.",
            },
        }

    monkeypatch.setattr("src.calculator.optimizer.run_fight", exact_fight)
    result = optimize_build(
        "Ahri",
        get_champion("Ahri"),
        level=18,
        max_legendary_slots=2,
        locked_items=["Rabadon's Deathcap"],
        locked_boots="Sorcerer's Shoes",
    )

    assert result["is_certified_best"] is True
    assert result["search_timeline_coverage"]["complete"] is True
    assert result["timeline_coverage"]["complete"] is True
    assert all(
        build["timeline_coverage"]["complete"] for build in result["ranked_builds"]
    )


def test_optimizer_is_champion_specific_for_orianna_auto_uptime():
    """High AA uptime must not collapse Orianna and Aatrox to one AD build."""
    shared = {
        "level": 18,
        "target_health": 2500,
        "target_armor": 100,
        "target_mr": 55,
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.8,
        "max_legendary_slots": 5,
    }
    orianna = optimize_build("Orianna", get_champion("Orianna"), **shared)
    aatrox = optimize_build("Aatrox", get_champion("Aatrox"), **shared)

    orianna_items = [get_item_by_name(name) for name in orianna["items"]]
    ap_items = sum(
        item.get("stats", {}).get("abilityPower", {}).get("flat", 0) > 0
        for item in orianna_items
    )

    assert ap_items >= 3
    assert orianna["items"] != aatrox["items"]


class TestOptimizerBasic:
    """Basic optimizer functionality tests."""

    def test_optimizer_returns_correct_keys(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=5,
        )

        assert len(result["ranked_builds"]) == 2
        assert (
            result["ranked_builds"][0]["items"] != result["ranked_builds"][1]["items"]
        )
        assert (
            result["ranked_builds"][0]["total_damage"]
            >= result["ranked_builds"][1]["total_damage"]
        )
        assert result["ranked_builds"][0]["dps"] > 0
        assert result["is_certified_best"] is False
        assert "items" in result
        assert "boots" in result
        assert "total_damage" in result
        assert "objective" in result
        assert "optimization_time_ms" in result
        assert "evaluations" in result

    @pytest.mark.parametrize("slot_count", [1, 2, 3, 4, 5, 6])
    def test_optimizer_fills_correct_slot_count(self, slot_count):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=slot_count,
        )
        assert len(result["items"]) == slot_count
        assert result["boots"] is not None

    def test_optimizer_no_duplicate_items(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox",
            champ_data,
            level=18,
            target_health=3000,
            target_armor=100,
            target_mr=60,
            fight_mode="timed",
            fight_duration=10,
            include_auto_attacks=True,
            auto_attack_uptime=0.7,
            max_legendary_slots=6,
        )
        names = result["items"]
        assert len(names) == len(set(names)), f"Duplicate items found: {names}"

    def test_optimizer_positive_damage(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=5,
        )
        assert result["total_damage"] > 0

    def test_optimizer_completes_under_15_seconds(self):
        """A smoke cap on the exhaustive-opening search, not a perf gate.

        The campaign's perf gates are the bench fingerprints (wall is a
        ratchet, R-28) and the allocation budget.  Measured best-of-5 on
        the 16-core dev box: 2,616 ms at the surface-dedup merge (2,677 ms
        on its base — the merge did not slow the search).  The CI runner's
        ``-n auto`` multiplier over the dev box was ~2.2x when the old 8 s
        cap was set and measures ~3.4x now (8.2 s and 8.7 s on two green
        trees), so the cap is recalibrated to 15 s: still an instant fail
        on a runaway search (observed at >30 s) without repinning the
        runner pool's scheduling noise as a formula change.
        """
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=5,
        )
        assert result["optimization_time_ms"] < 15000


class TestLockedItems:
    """Tests for locked item slot support."""

    def test_locked_legendary_preserved(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            locked_items=["Luden's Echo"],
            max_legendary_slots=5,
        )
        assert "Luden's Echo" in result["items"]
        assert len(result["items"]) == 5

    def test_locked_boots_preserved(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            locked_boots="Sorcerer's Shoes",
            max_legendary_slots=5,
        )
        assert result["boots"] == "Sorcerer's Shoes"

    def test_locked_multiple_items(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            locked_items=["Luden's Echo", "Rabadon's Deathcap"],
            max_legendary_slots=5,
        )
        assert "Luden's Echo" in result["items"]
        assert "Rabadon's Deathcap" in result["items"]
        assert len(result["items"]) == 5

    def test_locked_items_filling_every_slot_returns_exactly_those_items(self):
        """Seeding must not push the build past max_legendary_slots."""
        champ_data = get_champion("Ahri")
        locked = ["Luden's Echo", "Rabadon's Deathcap"]
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            locked_items=locked,
            max_legendary_slots=2,
        )
        assert sorted(result["items"]) == sorted(locked)

    def test_all_slots_locked_returns_quickly(self):
        """When all slots are locked, optimizer should evaluate only that build."""
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            locked_items=[
                "Luden's Echo",
                "Rabadon's Deathcap",
                "Shadowflame",
                "Void Staff",
                "Stormsurge",
            ],
            locked_boots="Sorcerer's Shoes",
            max_legendary_slots=5,
        )
        assert result["total_damage"] > 0
        assert result["optimization_time_ms"] < 500


class TestExclusivityGroupsAccessor:
    """Tests for the JSON-safe exclusivity_groups() accessor (served to the UI)."""

    def test_all_groups_present(self):
        groups = exclusivity_groups()
        assert set(groups) == {
            "Glory",
            "Spellblade",
            "Hydra",
            "Blight",
            "Fatality",
            "Immolate",
        }

    def test_glory_group_members(self):
        groups = exclusivity_groups()
        assert groups["Glory"] == ["Dark Seal", "Mejai's Soulstealer"]

    def test_spellblade_group_members(self):
        # Spellblade was missing from the old hand-copied app.js table;
        # the served table must include it.
        groups = exclusivity_groups()
        assert "Sheen" in groups["Spellblade"]
        assert "Trinity Force" in groups["Spellblade"]
        assert "Lich Bane" in groups["Spellblade"]

    def test_values_are_json_safe_sorted_lists(self):
        groups = exclusivity_groups()
        for members in groups.values():
            assert isinstance(members, list)
            assert members == sorted(members)
            assert all(isinstance(name, str) for name in members)


class TestExclusivityGroups:
    """Tests for item exclusivity group enforcement."""

    def test_no_two_spellblades(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox",
            champ_data,
            level=18,
            target_health=3000,
            target_armor=100,
            target_mr=60,
            fight_mode="timed",
            fight_duration=10,
            include_auto_attacks=True,
            auto_attack_uptime=0.7,
            max_legendary_slots=6,
        )
        spellblades_in_build = [
            name
            for name in result["items"]
            if name in ITEM_EXCLUSIVITY_GROUPS["Spellblade"]
        ]
        assert (
            len(spellblades_in_build) <= 1
        ), f"Multiple spellblades: {spellblades_in_build}"

    def test_no_two_hydra_items(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox",
            champ_data,
            level=18,
            target_health=3000,
            target_armor=100,
            target_mr=60,
            fight_mode="timed",
            fight_duration=10,
            include_auto_attacks=True,
            auto_attack_uptime=0.7,
            max_legendary_slots=6,
        )
        hydra_group = {
            "Tiamat",
            "Profane Hydra",
            "Ravenous Hydra",
            "Stridebreaker",
            "Titanic Hydra",
        }
        hydras = [n for n in result["items"] if n in hydra_group]
        assert len(hydras) <= 1, f"Multiple Hydra items: {hydras}"

    def test_no_two_blight_items(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=6,
        )
        blight_group = {
            "Blighting Jewel",
            "Bloodletter's Curse",
            "Cryptbloom",
            "Terminus",
            "Void Staff",
        }
        blights = [n for n in result["items"] if n in blight_group]
        assert len(blights) <= 1, f"Multiple Blight items: {blights}"

    def test_no_two_fatality_items(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox",
            champ_data,
            level=18,
            target_health=3000,
            target_armor=200,
            target_mr=60,
            fight_mode="timed",
            fight_duration=10,
            include_auto_attacks=True,
            auto_attack_uptime=0.7,
            objective="physical_damage",
            max_legendary_slots=6,
        )
        fatality_group = {
            "Last Whisper",
            "Black Cleaver",
            "Lord Dominik's Regards",
            "Mortal Reminder",
            "Serylda's Grudge",
            "Terminus",
        }
        fatalities = [n for n in result["items"] if n in fatality_group]
        assert len(fatalities) <= 1, f"Multiple Fatality items: {fatalities}"


class TestObjectives:
    """Tests for different optimization objectives."""

    def test_ap_champion_magic_objective(self):
        champ_data = get_champion("Ahri")
        result = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            objective="magic_damage",
            max_legendary_slots=5,
        )
        assert result["objective"] == "magic_damage"
        assert result["total_damage"] > 0

    def test_ad_champion_physical_objective(self):
        champ_data = get_champion("Aatrox")
        result = optimize_build(
            "Aatrox",
            champ_data,
            level=18,
            target_health=3000,
            target_armor=100,
            target_mr=60,
            fight_mode="timed",
            fight_duration=10,
            include_auto_attacks=True,
            auto_attack_uptime=0.7,
            objective="physical_damage",
            max_legendary_slots=5,
        )
        assert result["objective"] == "physical_damage"
        assert result["total_damage"] > 0


class TestSixVsFiveSlots:
    """Tests for 5 vs 6 legendary slots."""

    def test_six_slots_at_least_as_good_as_five(self):
        champ_data = get_champion("Ahri")
        result_5 = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=5,
        )
        result_6 = optimize_build(
            "Ahri",
            champ_data,
            level=18,
            target_health=2000,
            target_armor=50,
            target_mr=40,
            max_legendary_slots=6,
        )
        assert result_6["total_damage"] >= result_5["total_damage"]


def test_coupled_optimizer_caches_do_not_change_results(monkeypatch):
    """The score memo and pair caches are pure speed: force-disabling both
    must reproduce the identical coupled search result and receipts."""
    from src.calculator import optimizer
    from src.calculator.scenario import ChampionLoadout

    real_supported = optimizer.optimizer_supported_items
    keep = {
        "Rabadon's Deathcap",
        "Void Staff",
        "Rylai's Crystal Scepter",
        "Stormsurge",
        "Sorcerer's Shoes",
        "Ionian Boots of Lucidity",
    }

    def small_pool(items):
        supported = real_supported(items)
        narrowed = [item for item in supported if item["name"] in keep]
        return narrowed or supported

    monkeypatch.setattr(optimizer, "optimizer_supported_items", small_pool)

    enemies = [
        ChampionLoadout(
            champion="Alistar",
            level=13,
            role="support",
            boots="Plated Steelcaps",
            items=("Randuin's Omen", "Bramble Vest"),
        ).resolve(),
    ]
    common = {
        "champion_data": get_champion("Cassiopeia"),
        "level": 13,
        "fight_params": FightParams.from_request(
            {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
        ),
        "max_legendary_slots": 2,
        "require_complete_timeline": True,
        "enemy_loadouts": enemies,
    }
    baseline = _optimize_build(**common)

    monkeypatch.setattr(
        optimizer, "_evaluate_build", optimizer._evaluate_build_uncached
    )
    real_timeline = optimizer.build_participant_timeline

    def no_cache_timeline(*args, **kwargs):
        kwargs["pair_result_cache"] = None
        kwargs["search_context"] = None
        return real_timeline(*args, **kwargs)

    monkeypatch.setattr(optimizer, "build_participant_timeline", no_cache_timeline)
    uncached = _optimize_build(**common)

    baseline.pop("optimization_time_ms")
    uncached.pop("optimization_time_ms")
    assert baseline == uncached


_PURCHASE_IDS = {
    "Large Rod": 90101,
    "Blasting Wand": 90102,
    "Amplifying Tome": 90103,
    "Ruby Crystal": 90104,
    "Aether Wisp": 90105,
    "Doran's Ring": 90106,
}


def _patch_purchase_prices(monkeypatch, pool):
    """Give a synthetic pool the sourced rows ``item_total`` prices from.

    ``economy.item_total`` reads the atomized economics table and
    nothing else, so a fabricated item needs a fabricated row; a test
    world that skipped this would be pricing off the wiki cache the
    engine does not read.
    """
    real = economy.sourced_total
    rows = {int(item["id"]): int(item["shop"]["prices"]["total"]) for item in pool}
    monkeypatch.setattr(
        economy,
        "sourced_total",
        lambda item: rows.get(int(item.get("id") or 0), real(item)),
    )


def _purchase_item(name, rank, price):
    return {
        "name": name,
        "id": _PURCHASE_IDS[name],
        "rank": [rank],
        "shop": {"prices": {"total": price}, "tags": []},
    }


def test_purchase_optimizer_can_prefer_two_components_to_one_completed_item(
    monkeypatch,
):
    completed = _purchase_item("Large Rod", "LEGENDARY", 1000)
    wand = _purchase_item("Blasting Wand", "EPIC", 500)
    tome = _purchase_item("Amplifying Tome", "BASIC", 500)
    _patch_purchase_prices(monkeypatch, [completed, wand, tome])
    monkeypatch.setattr(
        "src.calculator.optimizer.get_purchase_items",
        lambda _role="": [completed, wand, tome],
    )
    monkeypatch.setattr(
        "src.calculator.optimizer.get_eligible_boots", lambda tier=2: []
    )
    monkeypatch.setattr("src.calculator.optimizer.optimizer_supported_items", list)
    monkeypatch.setattr(
        "src.calculator.optimizer.optimizer_candidate_coverage",
        lambda _items: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._public_search_timeline_coverage",
        lambda _audit: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._build_timeline_coverage",
        lambda *_args, **_kwargs: {"complete": True},
    )

    def score(_champion, _level, items, **_kwargs):
        names = {item["name"] for item in items}
        if {"Blasting Wand", "Amplifying Tome"} <= names:
            return 100.0
        if "Large Rod" in names:
            return 90.0
        return 50.0

    monkeypatch.setattr("src.calculator.optimizer._evaluate_build", score)
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=1000,
        include_boots=False,
    )

    assert result["purchase_items"] == ["Blasting Wand", "Amplifying Tome"]
    assert result["recommendation_type"] == "component_set"
    assert result["spent_gold"] == 1000
    assert result["remaining_gold"] == 0
    assert result["is_certified_best"] is True


def _patch_purchase_world(monkeypatch, pool, score):
    """Point the purchase search at a synthetic pool with a scripted scorer."""
    _patch_purchase_prices(monkeypatch, pool)
    monkeypatch.setattr(
        "src.calculator.optimizer.get_purchase_items", lambda _role="": list(pool)
    )
    monkeypatch.setattr(
        "src.calculator.optimizer.get_eligible_boots", lambda tier=2: []
    )
    monkeypatch.setattr("src.calculator.optimizer.optimizer_supported_items", list)
    monkeypatch.setattr(
        "src.calculator.optimizer.optimizer_candidate_coverage",
        lambda _items: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._public_search_timeline_coverage",
        lambda _audit: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._build_timeline_coverage",
        lambda *_args, **_kwargs: {"complete": True},
    )
    monkeypatch.setattr("src.calculator.optimizer._evaluate_build", score)


def test_purchase_optimizer_fills_more_than_two_slots_when_gold_allows(monkeypatch):
    """11k-gold-style requests must consider 3+ buys, not stop at two."""
    wand = _purchase_item("Blasting Wand", "EPIC", 500)
    tome = _purchase_item("Amplifying Tome", "BASIC", 500)
    ruby = _purchase_item("Ruby Crystal", "BASIC", 500)

    values = {"Blasting Wand": 100.0, "Amplifying Tome": 90.0, "Ruby Crystal": 80.0}

    def score(_champion, _level, items, **_kwargs):
        return sum(values[name] for name in {item["name"] for item in items})

    _patch_purchase_world(monkeypatch, [wand, tome, ruby], score)
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=1500,
        include_boots=False,
    )

    assert sorted(result["purchase_items"]) == [
        "Amplifying Tome",
        "Blasting Wand",
        "Ruby Crystal",
    ]
    assert result["spent_gold"] == 1500
    assert result["remaining_gold"] == 0
    assert result["is_certified_best"] is True
    assert result["winner_event_order_certified"] is True


def test_purchase_optimizer_falls_back_to_local_search_beyond_the_cap(monkeypatch):
    """A plan space above the exhaustive cap returns a best-found plan
    instead of withholding: the value-per-gold start must prefer two
    efficient cheap items ({Wand, Tome} = 100) over the single expensive
    item ({Rod} = 90) that pure damage-greedy locks onto."""
    rod = _purchase_item("Large Rod", "LEGENDARY", 1000)
    wand = _purchase_item("Blasting Wand", "EPIC", 500)
    tome = _purchase_item("Amplifying Tome", "BASIC", 500)

    def score(_champion, _level, items, **_kwargs):
        names = {item["name"] for item in items}
        if "Large Rod" in names:
            return 90.0
        if {"Blasting Wand", "Amplifying Tome"} <= names:
            return 100.0
        if names & {"Blasting Wand", "Amplifying Tome"}:
            return 75.0
        return 0.0

    _patch_purchase_world(monkeypatch, [rod, wand, tome], score)
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=1000,
        include_boots=False,
        candidate_cap=1,
    )

    assert sorted(result["purchase_items"]) == ["Amplifying Tome", "Blasting Wand"]
    assert result["is_certified_best"] is False
    assert result["search_guarantee"] == "purchase_local_search"
    assert result["winner_event_order_certified"] is True
    assert result["spent_gold"] == 1000


def test_purchase_search_returns_best_found_when_time_budget_expires_early(
    monkeypatch,
):
    """Enumeration overrunning the clock must never blank the result: the
    scoring loop always evaluates real purchase plans before it honors the
    deadline, so the user gets a best-found plan instead of an error."""
    import time as time_module

    wand = _purchase_item("Blasting Wand", "EPIC", 500)
    tome = _purchase_item("Amplifying Tome", "BASIC", 500)

    def score(_champion, _level, items, **_kwargs):
        return 1.0 + 10.0 * len(items)

    _patch_purchase_world(monkeypatch, [wand, tome], score)
    from src.calculator import optimizer as optimizer_module

    original_enumerate = optimizer_module._enumerate_affordable_shapes

    def slow_enumerate(*args, **kwargs):
        result = original_enumerate(*args, **kwargs)
        time_module.sleep(0.25)
        return result

    monkeypatch.setattr(
        "src.calculator.optimizer._enumerate_affordable_shapes", slow_enumerate
    )
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=1000,
        include_boots=False,
        time_budget_ms=100,
    )

    assert result["truncated"] is True
    assert result["purchase_items"]
    assert result["is_certified_best"] is False


def test_purchase_search_keeps_plans_affordable_only_through_component_credit(
    monkeypatch,
):
    """Affordability pruning must price with component credit: a legendary
    whose list price exceeds the gold is still buyable when owned components
    cover the difference, and must win, certified."""
    from src.calculator.economy import item_total, recipe_demand

    rabadon = get_item_by_name("Rabadon's Deathcap")
    component_ids = set(recipe_demand(rabadon))
    assert component_ids, "fixture assumes Rabadon's Deathcap has a recipe"
    components = [
        item for item in get_selectable_items() if int(item["id"]) in component_ids
    ]
    assert components, "fixture assumes recipe components are shop items"
    credit = sum(item_total(item) for item in components)
    net_cost = item_total(rabadon) - credit
    assert net_cost < item_total(rabadon)

    monkeypatch.setattr(
        "src.calculator.optimizer.get_purchase_items", lambda _role="": [rabadon]
    )
    monkeypatch.setattr(
        "src.calculator.optimizer.get_eligible_boots", lambda tier=2: []
    )
    monkeypatch.setattr(
        "src.calculator.optimizer.optimizer_candidate_coverage",
        lambda _items: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._public_search_timeline_coverage",
        lambda _audit: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._build_timeline_coverage",
        lambda *_args, **_kwargs: {"complete": True},
    )

    def score(_champion, _level, items, **_kwargs):
        names = {item["name"] for item in items}
        return 100.0 if "Rabadon's Deathcap" in names else 1.0

    monkeypatch.setattr("src.calculator.optimizer._evaluate_build", score)
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=net_cost,
        locked_items=[item["name"] for item in components],
        include_boots=False,
    )

    assert result["purchase_items"] == ["Rabadon's Deathcap"]
    assert result["spent_gold"] == net_cost
    assert result["is_certified_best"] is True


def test_purchase_local_search_never_claims_exhaustive_certification(monkeypatch):
    """A local-search run whose best plan buys nothing must not dress up as
    a certified 'no affordable purchase' — that claim needs the exhaustive
    walk to have actually finished."""
    wand = _purchase_item("Blasting Wand", "EPIC", 500)
    tome = _purchase_item("Amplifying Tome", "BASIC", 500)

    def score(_champion, _level, _items, **_kwargs):
        return 42.0

    _patch_purchase_world(monkeypatch, [wand, tome], score)
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=1000,
        include_boots=False,
        candidate_cap=1,
    )

    assert result["recommendation_type"] != "no_affordable_purchase"
    assert result["is_certified_best"] is False
    assert result["search_guarantee"] == "purchase_local_search"
    assert result["purchase_items"] == []


def test_purchase_exhaustive_walk_can_hold_a_component_and_its_legendary(
    monkeypatch,
):
    """Buying Thornmail then Bramble Vest keeps both; component-first buy
    order would force the vest into the Thornmail recipe and make the
    two-item loadout unreachable, silently narrowing the certified claim."""
    from src.calculator.economy import item_total

    vest = get_item_by_name("Bramble Vest")
    thornmail = get_item_by_name("Thornmail")
    gold = item_total(vest) + item_total(thornmail)

    monkeypatch.setattr(
        "src.calculator.optimizer.get_purchase_items",
        lambda _role="": [vest, thornmail],
    )
    monkeypatch.setattr(
        "src.calculator.optimizer.get_eligible_boots", lambda tier=2: []
    )
    monkeypatch.setattr("src.calculator.optimizer.optimizer_supported_items", list)
    monkeypatch.setattr(
        "src.calculator.optimizer.optimizer_candidate_coverage",
        lambda _items: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._public_search_timeline_coverage",
        lambda _audit: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._build_timeline_coverage",
        lambda *_args, **_kwargs: {"complete": True},
    )

    def score(_champion, _level, items, **_kwargs):
        names = {item["name"] for item in items}
        if {"Thornmail", "Bramble Vest"} <= names:
            return 100.0
        if "Thornmail" in names:
            return 50.0
        return 10.0

    monkeypatch.setattr("src.calculator.optimizer._evaluate_build", score)
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=gold,
        include_boots=False,
    )

    assert sorted(result["items"]) == ["Bramble Vest", "Thornmail"]
    assert result["spent_gold"] == gold
    assert result["is_certified_best"] is True


def test_purchase_non_improving_buys_are_reported_as_keep_gold(monkeypatch):
    """Affordable items that don't improve the objective are not 'no
    affordable purchase' — the honest certified answer is keep-your-gold."""
    wand = _purchase_item("Blasting Wand", "EPIC", 500)
    tome = _purchase_item("Amplifying Tome", "BASIC", 500)

    def score(_champion, _level, _items, **_kwargs):
        return 42.0

    _patch_purchase_world(monkeypatch, [wand, tome], score)
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=1000,
        include_boots=False,
    )

    assert result["recommendation_type"] == "keep_gold"
    assert result["purchase_items"] == []
    assert result["is_certified_best"] is True


def test_purchase_below_cheapest_item_is_no_affordable_purchase(monkeypatch):
    """Gold below every price is the one state that may claim
    no_affordable_purchase, and it stays certified."""
    wand = _purchase_item("Blasting Wand", "EPIC", 500)

    def score(_champion, _level, _items, **_kwargs):
        return 42.0

    _patch_purchase_world(monkeypatch, [wand], score)
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=100,
        include_boots=False,
    )

    assert result["recommendation_type"] == "no_affordable_purchase"
    assert result["is_certified_best"] is True


def test_coupled_scorer_prefers_faster_kill_over_bystander_tankiness():
    """When two builds both kill the roster inside the window, damage ties
    at the victim's health.  The scorer must then prefer the faster kill,
    not the tankier buyer — the EHP tie-break alone let a Damage-objective
    search recommend Warmog's Armor on Syndra because every killing build
    tied and tankiness decided the winner."""
    from src.calculator.scenario import parse_scenario_request, resolve_scenario

    payload = {
        "champion": "Syndra",
        "level": 16,
        "role": "mid",
        "ability_ranks": {"Q": 5, "W": 4, "E": 4, "R": 3},
        "enemies": [{"champion": "Jhin", "level": 18}],
        "enemies_attack": False,
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0,
        "auto_attack_uptime_mode": "calculated",
        "include_actives": True,
    }
    request = parse_scenario_request(payload, deterministic=True, parse_crossover=False)
    resolved = resolve_scenario(request)

    def coupled_score(names):
        from src.calculator.participant_timeline import CoupledSearchContext

        items = [get_item_by_name(name) for name in names]
        audit = {
            "evaluations": 0,
            "partial_evaluations": 0,
            "excluded_evaluations": 0,
            "exact_sources": set(),
            "coarse_sources": set(),
            "excluded_sources": set(),
            "build_coverages": {},
            "withheld_builds": {},
        }
        context = {
            "enemies": list(resolved.enemies),
            "allies": [],
            "pair_result_cache": {},
            "score_memo": {},
            "search_context": CoupledSearchContext(),
        }
        return _evaluate_build(
            resolved.champion_data,
            16,
            items,
            fight_params=resolved.fight_params,
            objective="total_damage",
            timeline_audit=audit,
            require_complete_timeline=True,
            combat_context=context,
        )

    fast_kill = coupled_score(
        ["Actualizer", "Rabadon's Deathcap", "Shadowflame", "Stormsurge"]
    )
    tanky_kill = coupled_score(
        ["Actualizer", "Spear of Shojin", "Warmog's Armor", "Winter's Approach"]
    )

    assert int(fast_kill) == int(tanky_kill), "both builds must cap at the kill"
    assert fast_kill > tanky_kill


def test_purchase_greedy_first_slot_is_argmax_even_when_deadline_expired(
    monkeypatch,
):
    """A search whose budget was eaten upstream must still recommend the
    best single buy, not the first pool item that beat the baseline — the
    regression that recommended Overlord's Bloodmail on Syndra."""
    # The weak item sorts first (LEGENDARY before EPIC), so a first-improving
    # shortcut would buy it; only a full argmax scan finds the strong one.
    weak = _purchase_item("Large Rod", "LEGENDARY", 500)
    strong = _purchase_item("Blasting Wand", "EPIC", 500)
    values = {"Large Rod": 10.0, "Blasting Wand": 30.0}

    def score(_champion, _level, items, **_kwargs):
        return sum(values.get(item["name"], 0.0) for item in items) + 1.0

    _patch_purchase_world(monkeypatch, [weak, strong], score)
    monkeypatch.setattr(
        "src.calculator.optimizer._PurchaseSearch.expired", lambda self: True
    )
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=500,
        include_boots=False,
    )

    assert result["purchase_items"] == ["Blasting Wand"]
    assert result["truncated"] is True


def test_purchase_winner_receipt_still_reports_incomplete_combine(monkeypatch):
    """Search pricing may skip the shop-wide combine scan for speed, but the
    winning plan's receipt must still carry an honest incomplete_combine
    flag (buying Ruby Crystal completes the owned Thornmail component set)."""
    from src.calculator.economy import item_total

    ruby = get_item_by_name("Ruby Crystal")
    monkeypatch.setattr(
        "src.calculator.optimizer.get_purchase_items", lambda _role="": [ruby]
    )
    monkeypatch.setattr(
        "src.calculator.optimizer.get_eligible_boots", lambda tier=2: []
    )
    monkeypatch.setattr(
        "src.calculator.optimizer.optimizer_candidate_coverage",
        lambda _items: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._public_search_timeline_coverage",
        lambda _audit: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._build_timeline_coverage",
        lambda *_args, **_kwargs: {"complete": True},
    )

    def score(_champion, _level, items, **_kwargs):
        names = [item["name"] for item in items]
        return 10.0 * names.count("Ruby Crystal") + 1.0

    monkeypatch.setattr("src.calculator.optimizer._evaluate_build", score)
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=item_total(ruby),
        locked_items=["Bramble Vest", "Chain Vest"],
        include_boots=False,
    )

    assert result["purchase_items"] == ["Ruby Crystal"]
    assert result["incomplete_combine"] is True


def test_purchase_never_recommends_duplicate_items(monkeypatch):
    """The economy model reviews some components as stackable, but manual
    builds and /api/calculate reject all duplicates — a recommendation the
    app then refuses to display is broken end to end (the double-Kindlegem
    regression)."""
    kindlegem = get_item_by_name("Kindlegem")
    monkeypatch.setattr(
        "src.calculator.optimizer.get_purchase_items", lambda _role="": [kindlegem]
    )
    monkeypatch.setattr(
        "src.calculator.optimizer.get_eligible_boots", lambda tier=2: []
    )
    monkeypatch.setattr(
        "src.calculator.optimizer.optimizer_candidate_coverage",
        lambda _items: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._public_search_timeline_coverage",
        lambda _audit: {"complete": True},
    )
    monkeypatch.setattr(
        "src.calculator.optimizer._build_timeline_coverage",
        lambda *_args, **_kwargs: {"complete": True},
    )

    def score(_champion, _level, items, **_kwargs):
        return 10.0 * len(items) + 1.0

    monkeypatch.setattr("src.calculator.optimizer._evaluate_build", score)
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=5000,
        include_boots=False,
    )

    assert result["purchase_items"] == ["Kindlegem"]
    assert len(result["items"]) == len(set(result["items"]))


def test_purchase_reserves_the_boots_slot_when_boots_are_enabled(monkeypatch):
    """With boots enabled the UI holds one slot for them, so a purchase
    plan may fill at most five ordinary slots — a six-item no-boots plan
    silently loses its sixth item in the interface."""
    pool = [
        _purchase_item(name, "EPIC", 500)
        for name in (
            "Blasting Wand",
            "Amplifying Tome",
            "Ruby Crystal",
            "Aether Wisp",
            "Large Rod",
            "Doran's Ring",
        )
    ]

    def score(_champion, _level, items, **_kwargs):
        return 10.0 * len(items) + 1.0

    _patch_purchase_world(monkeypatch, pool, score)
    result = optimize_purchase(
        {"name": "Test Champion"},
        18,
        available_gold=3000,
        include_boots=True,
    )

    assert len(result["items"]) <= 5


def test_purchase_price_fails_closed_with_item_and_key():
    with pytest.raises(KeyError, match=r"Broken Item: shop\.prices\.total"):
        item_gold({"name": "Broken Item", "shop": {"prices": {}}})


def test_purchase_pool_includes_components_but_not_starters(monkeypatch):
    items = [
        _purchase_item("Ruby Crystal", "BASIC", 400),
        _purchase_item("Aether Wisp", "EPIC", 900),
        _purchase_item("Doran's Ring", "STARTER", 400),
    ]
    monkeypatch.setattr("src.calculator.optimizer._ordinary_sr_items", lambda: items)
    monkeypatch.setattr("src.calculator.optimizer.optimizer_supported_items", list)

    assert [item["name"] for item in get_purchase_items("top")] == [
        "Ruby Crystal",
        "Aether Wisp",
    ]


def test_optimize_build_rejects_consumable_locked_items():
    with pytest.raises(ValueError, match="not an ordinary non-boots shop item"):
        optimize_build(
            "Ahri",
            get_champion("Ahri"),
            level=13,
            locked_items=["Health Potion"],
        )


def test_role_scope_keeps_multiclass_lane_items_available():
    """A SUPPORT tag does not hide lane-class items (patch 16.15.1 added
    SUPPORT to Whispering Circlet, a MAGE item; Morellonomicon/Frozen Heart
    are TANK/MAGE+SUPPORT and legal for those lanes in the real shop)."""
    from src.calculator.loadout_rules import role_scoped_shop_items

    pool = optimizer_supported_items(get_eligible_legendaries())
    top = {item["name"] for item in role_scoped_shop_items(pool, "top")}
    mid = {item["name"] for item in role_scoped_shop_items(pool, "mid")}
    support = {item["name"] for item in role_scoped_shop_items(pool, "support")}

    assert "Whispering Circlet" in top
    assert "Whispering Circlet" in mid
    assert "Morellonomicon" in top
    assert "Frozen Heart" in top
    assert "Locket of the Iron Solari" in top
    # Pure support items stay support-exclusive.
    assert "Shurelya's Battlesong" not in top
    assert "Ardent Censer" not in top
    assert "Redemption" not in top
    assert "Whispering Circlet" in support
