"""Issue #82 — role-quest boot upgrades + support-item progression acceptance.

The acceptance criteria pin four contracts:

1. Completing the mid role quest swaps the selected tier-2 boot for its
   sourced tier-3 pair and that boot REMAINS present through role, level,
   quest, copy, and rerender operations.  The frontend owns the swap
   (``normalizeRosterBootForRole`` / ``roleQuestBootUpgradeName``); the
   API owns the tier legality contract that makes the swap enforceable.
2. The upgraded boot's typed stats actually move the calculation
   (TDD via flat magic penetration, eHP via lifesteal healing).
3. Support-quest progression stages are legal per quest state across the
   API, the frontend picker, the optimizer candidate pool, and the BIS
   sweep — the five upgraded support items certify only with the quest
   complete.
4. The browser flow is exercised headlessly (see /tmp/pw-qa/qa-quest-boots.js);
   these tests pin the API contract transitions and the JS wiring those
   flows depend on.
"""

import re
from pathlib import Path

import pytest

import src.app as app_module
from src.calculator.data_fetcher import get_champion
from src.calculator.loadout_rules import role_quest_legal_items
from src.calculator.optimizer import (
    get_eligible_legendaries,
    optimize_build as _optimize_build,
    optimizer_supported_items,
    role_scoped_shop_items,
)
from src.calculator.pipeline import FightParams
from src.calculator.role_quests import (
    BOOT_UPGRADES,
    SUPPORT_QUEST_ITEM_STAGES,
    support_quest_item_stage,
)
from tests.app_config import app_config

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "js" / "app.js"

SUPPORT_UPGRADES = sorted(
    name for name, stage in SUPPORT_QUEST_ITEM_STAGES.items() if stage == "upgraded"
)
SUPPORT_STARTERS = sorted(
    name for name, stage in SUPPORT_QUEST_ITEM_STAGES.items() if stage != "upgraded"
)
UPGRADED_BY_BASE = {upgraded: base for base, upgraded in BOOT_UPGRADES.items()}


@pytest.fixture(autouse=True)
def _isolate_app_config():
    """Keep these route tests off the shared rate-limit budget."""
    with app_config(TESTING=True, RATE_LIMIT_ENABLED=False):
        yield


def _client():
    return app_module.app.test_client()


def _calculate(payload):
    response = _client().post("/api/calculate", json=payload)
    return response.status_code, response.get_json() or {}


def _main_survival(body):
    return next(
        row["survival"]
        for row in body["combat"]["participants"]
        if row["participant_id"] == "main"
    )


# --------------------------------------------------------------------------
# Criterion 1 — mid quest boot tier contract (API + frontend wiring)
# --------------------------------------------------------------------------


class TestMidQuestBootTierContract:
    """The tier-3 pair is legal exactly for mid + quest complete."""

    @pytest.mark.parametrize(
        ("boots", "role", "complete", "expected"),
        [
            # tier-2 legal without the completed mid quest
            ("Berserker's Greaves", "mid", False, 200),
            # tier-3 requires the completed mid quest
            ("Gunmetal Greaves", "mid", False, 400),
            ("Gunmetal Greaves", "mid", True, 200),
            # tier-2 is illegal once the mid quest is complete
            ("Berserker's Greaves", "mid", True, 400),
            # tier-3 boots are a mid-only quest reward
            ("Gunmetal Greaves", "top", True, 400),
            ("Gunmetal Greaves", "bottom", True, 400),
            ("Gunmetal Greaves", "support", True, 400),
            # no role means no quest state, so tier-3 is illegal
            ("Gunmetal Greaves", "", False, 400),
        ],
    )
    def test_boot_tier_legal_exactly_for_mid_quest_state(
        self, boots, role, complete, expected
    ):
        payload = {
            "champion": "Jinx",
            "level": 12,
            "boots": boots,
            "items": [],
        }
        if role:
            payload["role"] = role
        if complete:
            payload["role_quest_complete"] = True
        status, body = _calculate(payload)
        assert status == expected, (boots, role, complete, body)
        if expected == 400:
            assert "tier" in body["error"]

    def test_level_change_keeps_the_quest_boot_legal(self):
        """The tier-3 boot stays legal across levels (18 is the pre-top cap)."""
        for level in (1, 12, 18):
            status, _ = _calculate(
                {
                    "champion": "Jinx",
                    "level": level,
                    "role": "mid",
                    "role_quest_complete": True,
                    "boots": "Gunmetal Greaves",
                    "items": [],
                }
            )
            assert status == 200

    def test_boot_api_exposes_every_sourced_tier_three_pair(self):
        boots = _client().get("/api/boots").get_json()
        by_name = {boot["name"]: boot for boot in boots}
        assert set(by_name) == set(BOOT_UPGRADES) | set(BOOT_UPGRADES.values())

        for base, upgraded in BOOT_UPGRADES.items():
            assert by_name[base]["tier"] == 2
            assert by_name[base]["upgrade_to"] == upgraded
            assert by_name[upgraded]["tier"] == 3
            assert by_name[upgraded]["upgrade_from"] == base

    def test_frontend_wiring_swaps_boots_and_keeps_them_across_transitions(self):
        """Every UI transition the issue lists is wired to state that
        preserves the selected pair: role change, quest toggle, copy A->B,
        and rerender all leave the quest boot in place; the level handler
        never touches it."""
        source = APP_JS.read_text(encoding="utf-8")

        # The swap helpers exist and are the only boot-rewrite entry points.
        assert "function roleQuestBootUpgradeName(item, complete)" in source
        assert "function normalizeRosterBootForRole(loadout)" in source
        assert "function normalizeAttackerBootsForRole()" in source

        # Quest toggle (both the prototype #questToggle and the analyst
        # [data-role-quest] handler) normalizes the attacker boot.
        assert (
            "state.attacker.roleQuestComplete = !state.attacker.roleQuestComplete;\n"
            "    normalizeAttackerBootsForRole();"
        ) in source

        # Role change normalizes the attacker boot.
        assert (
            "state.attacker.role = roleButton.dataset.role;\n"
            "    normalizeAttackerBootsForRole();"
        ) in source
        assert (
            "state.attacker.role = roleSelect.value || null;\n"
            "    if (!state.attacker.role) state.attacker.roleQuestComplete = false;\n"
            "    normalizeAttackerBootsForRole();"
        ) in source

        # Roster role select and roster quest toggle normalize through the
        # same helper (boots stay in the dedicated field).
        assert "normalizeRosterRoleState(loadout);" in source

        # Copy A->B carries the upgraded boot into the other build column.
        assert (
            "state.attacker[`questBoot${to}`] = state.attacker[`questBoot${from}`];"
        ) in source

        # Rerender reads the quest boot straight from state on the duel
        # canvas — its own slot row, keyed by side; nothing resets it.
        assert "state.attacker[`questBoot${side}`]" in source
        assert (
            "rows.push(duelRowHtml(state.attacker[`questBoot${side}`], "
            "questBootPath(side)));"
        ) in source

        # The picker only offers the tier the current quest state allows.
        assert "return bootIdsForTier(" in source
        assert "roleBootsTier(state.attacker.role" in source

        # The level handler clamps against the role cap but never rewrites
        # the quest boot (level changes must keep the selected pair).
        level_block = re.search(
            r"const levelButton = event\.target\.closest\(\"[^\"]*data-level-delta[^\"]*\"\);.*?\n  \}",
            source,
            re.S,
        )
        assert level_block is not None
        assert "normalizeAttackerBootsForRole" not in level_block.group(0)
        assert "normalizeRosterRoleState" not in level_block.group(0)


# --------------------------------------------------------------------------
# Criterion 2 — the upgraded boot's typed stats move the calculation
# --------------------------------------------------------------------------


class TestTierThreeBootStatsAffectCalculation:
    def test_magic_penetration_boots_change_total_damage(self):
        base = {
            "champion": "Ziggs",
            "level": 12,
            "items": [],
            "target_health": 2_000,
            "target_armor": 100,
            "target_mr": 100,
            "auto_attack_uptime": 1.0,
            "auto_attack_uptime_mode": "explicit",
            "fight_duration": 10,
        }
        _, tier_two = _calculate(
            {
                **base,
                "role": "mid",
                "role_quest_complete": False,
                "boots": "Sorcerer's Shoes",
            }
        )
        _, tier_three = _calculate(
            {
                **base,
                "role": "mid",
                "role_quest_complete": True,
                "boots": "Spellslinger's Shoes",
            }
        )

        assert tier_two["champion_stats"]["magic_penetration_flat"] == 12.0
        assert tier_three["champion_stats"]["magic_penetration_flat"] == 20.0
        assert tier_three["total_damage"] > tier_two["total_damage"]

    def test_lifesteal_boots_change_effective_health(self):
        base = {
            "champion": "Jinx",
            "level": 12,
            "items": [],
            "target_health": 2_000,
            "target_armor": 100,
            "target_mr": 100,
            "auto_attack_uptime": 1.0,
            "auto_attack_uptime_mode": "explicit",
            "fight_duration": 10,
            "enemies": [{"champion": "Galio", "level": 12, "role": "mid"}],
        }
        _, tier_two = _calculate(
            {
                **base,
                "role": "mid",
                "role_quest_complete": False,
                "boots": "Berserker's Greaves",
            }
        )
        _, tier_three = _calculate(
            {
                **base,
                "role": "mid",
                "role_quest_complete": True,
                "boots": "Gunmetal Greaves",
            }
        )

        two_ehp = _main_survival(tier_two)["effective_health"]
        three_ehp = _main_survival(tier_three)["effective_health"]
        assert tier_three["champion_stats"]["lifesteal_percent"] == 5.0
        assert _main_survival(tier_three)["healing_received"] > 0
        assert three_ehp > two_ehp


# --------------------------------------------------------------------------
# Criterion 3 — support-item progression is legal per quest state
# --------------------------------------------------------------------------


class TestSupportQuestStageContract:
    """API: basic/upgraded stages are legal exactly for their quest state."""

    @pytest.mark.parametrize("item", SUPPORT_UPGRADES)
    def test_upgraded_support_item_requires_completed_quest(self, item):
        payload = {
            "champion": "Nami",
            "level": 12,
            "role": "support",
            "items": [item],
        }
        status, body = _calculate(payload)
        assert status == 400
        assert "not legal for this support quest state" in body["error"]

        status, _ = _calculate({**payload, "role_quest_complete": True})
        assert status == 200

    @pytest.mark.parametrize("item", SUPPORT_STARTERS)
    def test_starter_and_intermediate_stages_are_incomplete_quest_only(self, item):
        payload = {
            "champion": "Nami",
            "level": 12,
            "role": "support",
            "items": [item],
        }
        status, body = _calculate({**payload, "role_quest_complete": True})
        assert status == 400
        assert "not legal for this support quest state" in body["error"]

        status, _ = _calculate(payload)
        assert status == 200

    @pytest.mark.parametrize("role", ["top", "jungle", "mid", "bottom"])
    def test_support_quest_items_require_the_support_role(self, role):
        status, body = _calculate(
            {
                "champion": "Nami",
                "level": 12,
                "role": role,
                "items": ["Bloodsong"],
            }
        )
        assert status == 400
        assert "require the support role" in body["error"]

    def test_roster_participants_follow_the_same_stage_gate(self):
        for root in ("enemies", "allies"):
            legal = _client().post(
                "/api/calculate",
                json={
                    "champion": "Ziggs",
                    "level": 12,
                    root: [
                        {
                            "champion": "Nami",
                            "level": 12,
                            "role": "support",
                            "role_quest_complete": True,
                            "items": ["Bloodsong"],
                        }
                    ],
                },
            )
            assert legal.status_code == 200

            illegal = _client().post(
                "/api/calculate",
                json={
                    "champion": "Ziggs",
                    "level": 12,
                    root: [
                        {
                            "champion": "Nami",
                            "level": 12,
                            "role": "support",
                            "role_quest_complete": False,
                            "items": ["Bloodsong"],
                        }
                    ],
                },
            )
            assert illegal.status_code == 400
            assert (
                "not legal for this support quest state" in illegal.get_json()["error"]
            )


class TestSupportQuestStageOptimizer:
    """Optimizer: the candidate pool never contains an illegal stage."""

    def _pool(self, role_quest_complete):
        candidates = get_eligible_legendaries()
        supported = optimizer_supported_items(candidates)
        scoped = role_scoped_shop_items(supported, "support")
        return role_quest_legal_items(
            scoped, role="support", role_quest_complete=role_quest_complete
        )

    def test_pool_keeps_upgraded_stages_only_with_completed_quest(self):
        incomplete = {
            item["name"]
            for item in self._pool(False)
            if support_quest_item_stage(item["name"]) is not None
        }
        complete = {
            item["name"]
            for item in self._pool(True)
            if support_quest_item_stage(item["name"]) is not None
        }

        assert incomplete == set()
        assert complete == set(SUPPORT_UPGRADES)

    def test_optimizer_never_scores_an_illegal_upgraded_stage(self, monkeypatch):
        evaluated = []

        def recording_evaluate(_champion, _level, items, **_kwargs):
            evaluated.extend(item["name"] for item in items)
            return 1.0

        monkeypatch.setattr(
            "src.calculator.optimizer._evaluate_build", recording_evaluate
        )
        params = FightParams.from_request(
            {"role": "support", "role_quest_complete": False},
            deterministic=True,
        )
        _optimize_build(
            get_champion("Nami"),
            18,
            fight_params=params,
            max_legendary_slots=1,
            include_boots=False,
        )

        assert evaluated
        for name in evaluated:
            if support_quest_item_stage(name) is not None:
                assert support_quest_item_stage(name) != "upgraded"

    def test_optimizer_reaches_all_five_upgrades_with_completed_quest(
        self, monkeypatch
    ):
        evaluated = []

        def recording_evaluate(_champion, _level, items, **_kwargs):
            evaluated.extend(item["name"] for item in items)
            return 1.0

        monkeypatch.setattr(
            "src.calculator.optimizer._evaluate_build", recording_evaluate
        )
        params = FightParams.from_request(
            {"role": "support", "role_quest_complete": True},
            deterministic=True,
        )
        _optimize_build(
            get_champion("Nami"),
            18,
            fight_params=params,
            max_legendary_slots=1,
            include_boots=False,
        )

        assert set(SUPPORT_UPGRADES) <= set(evaluated)


class TestBisSupportSweep:
    """BIS: the five support upgrades certify with the quest complete and
    are excluded from the sweep without it."""

    def _bis_payload(self, role_quest_complete):
        return {
            "champion": "Nami",
            "level": 12,
            "role": "support",
            "role_quest_complete": role_quest_complete,
            "items": [],
            "boots": "Ionian Boots of Lucidity",
            "slot_index": 0,
            "slot_kind": "item",
            "objective": "overall",
            "target_health": 2_000,
            "target_armor": 100,
            "target_mr": 100,
            "enemies": [
                {"champion": "Jhin", "level": 12, "role": "bottom", "items": []}
            ],
        }

    def test_all_five_upgrades_certify_with_completed_quest(self):
        response = _client().post("/api/bis", json=self._bis_payload(True))
        assert response.status_code == 200
        body = response.get_json()

        certified = {candidate["name"] for candidate in body["candidates"]}
        withheld = {candidate["name"] for candidate in body["withheld_candidates"]}
        assert set(SUPPORT_UPGRADES) <= certified
        assert not (set(SUPPORT_UPGRADES) & withheld)
        assert all(
            candidate["timeline_coverage"]["complete"]
            for candidate in body["candidates"]
        )

    def test_upgrades_are_excluded_without_completed_quest(self):
        response = _client().post("/api/bis", json=self._bis_payload(False))
        assert response.status_code == 200
        body = response.get_json()

        certified = {candidate["name"] for candidate in body["candidates"]}
        partial = {candidate["name"] for candidate in body["partial_candidates"]}
        withheld = {candidate["name"] for candidate in body["withheld_candidates"]}
        assert not (set(SUPPORT_UPGRADES) & certified)
        assert not (set(SUPPORT_UPGRADES) & partial)
        assert not (set(SUPPORT_UPGRADES) & withheld)
        assert body["withheld_candidate_count"] == 0


class TestFrontendSupportStageWiring:
    """Frontend: illegal stages are cleared on role/quest transitions."""

    def test_attacker_and_roster_normalizers_clear_illegal_stages(self):
        source = APP_JS.read_text(encoding="utf-8")

        assert "function normalizeAttackerSupportItemsForRole()" in source
        assert "function normalizeRosterSupportItemsForRole(loadout)" in source
        assert (
            'state.attacker.role === "support"\n'
            '        && (state.attacker.roleQuestComplete ? stage === "upgraded" : stage !== "upgraded")'
        ) in source
        assert (
            'loadout.role === "support"\n'
            '      && (loadout.roleQuestComplete ? stage === "upgraded" : stage !== "upgraded")'
        ) in source

    def test_shared_build_restore_normalizes_the_quest_contract(self):
        source = APP_JS.read_text(encoding="utf-8")
        assert (
            "normalizeAttackerBootsForRole();\n"
            "  normalizeAttackerSupportItemsForRole();\n"
            "  render();"
        ) in source
