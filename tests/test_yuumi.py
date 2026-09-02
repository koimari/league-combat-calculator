"""Reviewed crowd control for Yuumi (MODULE_CC), and Feline Friendship.

Both damaging slots slow: Prowling Projectile by 20%, Final Chapter's
waves by a stacking 10%.
"""

import copy
import inspect
import itertools

import pytest

from src import app as app_module
from src.calculator import healing_reduction
from src.calculator.champions import get_champion_module_contract, yuumi
from src.calculator.data_fetcher import get_champion
from tests import cc_review

# Prowling Projectile has six ranks (You and Me! is free at level 1).
RANKS = {"Q": 6, "W": 5, "E": 5, "R": 3}


def _yuumi_fight(level: int, ranks: dict, items: list | None = None) -> dict:
    """One live Yuumi fight through the public endpoint."""
    enemy_ranks = {"Q": 1, "W": 1, "E": 1, "R": 1} if level >= 6 else {"Q": 1}
    payload = {
        "champion": "Yuumi",
        "level": level,
        "items": items or [],
        "role": "support",
        "fight_mode": "time_based",
        "fight_duration": 25,
        "include_auto_attacks": True,
        "ability_ranks": ranks,
        "enemies": [
            {
                "champion": "Ahri",
                "level": level,
                "items": [],
                "role": "mid",
                "ability_ranks": enemy_ranks,
            }
        ],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _feline_heals(result: dict) -> list[dict]:
    return [
        event
        for event in result["combat"].get("healing_events", [])
        if event.get("attacker") == "main"
        and event.get("source") == "Feline Friendship"
    ]


class TestReviewedCrowdControl:
    """Yuumi's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Yuumi")
        assert yuumi.MODULE_CC == {"Q": "slow", "R": "slow"}
        assert yuumi.parse_abilities.cc_kinds == yuumi.MODULE_CC
        assert "slowed by 20% for 1 second" in cc_review.slot_text(data, "Q")
        assert "slowed by 10% for 1.25 seconds" in cc_review.slot_text(data, "R")

    def test_the_ally_slots_stay_absent(self):
        """W attaches and E shields; neither damages an enemy.

        Coverage is about the row a slot publishes, not about damage: E is
        ``modeled`` on its 165.0 shield to the anchor (test_e8_support.py),
        while W prices nothing an enemy takes and reads ``no_damage``
        (TestYouAndMeIsASourcedZeroDamageRow re-derives that verdict).
        """
        assert "W" not in yuumi.MODULE_CC
        assert "E" not in yuumi.MODULE_CC
        assert get_champion_module_contract("Yuumi").coverage["W"] == "no_damage"
        assert get_champion_module_contract("Yuumi").coverage["E"] == "modeled"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Yuumi") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Yuumi")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestFelineFriendship:
    """P's self-heal: the sourced row, the sourced gate, and what is refused.

    Both numbers are cached rows this module reads live — the per-level
    "Heal" (20 : 120.59 by level + 30% AP) and the innate's own per-level
    cooldown (20 : 8s, ``affectedByCdr`` false).  Nothing here is a literal
    the module could keep after a patch moved the row.
    """

    def test_the_slot_is_modeled_through_the_named_channel(self):
        contract = get_champion_module_contract("Yuumi")
        assert contract.coverage["P"] == "modeled"
        assert yuumi.COVERAGE_CHANNELS == {"P": ("self_healing_rule",)}

    def test_the_first_damaging_hit_pays_the_level_row(self):
        heals = _feline_heals(_yuumi_fight(18, {"Q": 5, "W": 5, "E": 5, "R": 3}))
        assert heals, "Feline Friendship heal missing"
        assert heals[0]["time"] == pytest.approx(0.0)
        # cached Heal[level 18] == 110.0, and the fight carries no AP
        assert heals[0]["amount"] == pytest.approx(110.0, rel=1e-6)

    def test_the_heal_carries_the_thirty_percent_ap_ratio(self):
        result = _yuumi_fight(
            18, {"Q": 5, "W": 5, "E": 5, "R": 3}, items=["Rabadon's Deathcap"]
        )
        ability_power = float(result["champion_stats"]["ability_power"])
        assert ability_power > 0.0
        heals = _feline_heals(result)
        assert heals
        assert heals[0]["amount"] == pytest.approx(
            110.0 + 0.30 * ability_power, rel=1e-6
        )

    @pytest.mark.parametrize(
        ("level", "ranks", "heal", "recharge"),
        [
            (1, {"Q": 1, "W": 0, "E": 0, "R": 0}, 20.0, 20.0),
            (6, {"Q": 3, "W": 1, "E": 1, "R": 1}, 46.47, 16.470588235294116),
            (18, {"Q": 5, "W": 5, "E": 5, "R": 3}, 110.0, 8.0),
        ],
    )
    def test_the_passive_cooldown_row_gates_every_later_payment(
        self, level, ranks, heal, recharge
    ):
        """Each payment re-arms the gate; no hit inside the recharge pays."""
        heals = _feline_heals(_yuumi_fight(level, ranks))
        assert heals
        # the public response rounds a heal amount to one decimal
        assert all(event["amount"] == pytest.approx(round(heal, 1)) for event in heals)
        times = [float(event["time"]) for event in heals]
        assert times[0] == pytest.approx(0.0)
        assert all(
            later - earlier >= recharge - 1e-6
            for earlier, later in itertools.pairwise(times)
        )

    def test_the_recharge_is_the_innates_own_haste_immune_row(self):
        """The cached innate sets ``affectedByCdr`` false, so haste is inert.

        The gate is read straight off that row, which is why the rule never
        divides it by an ability-haste factor.
        """
        passive = cc_review.kit("Yuumi")["abilities"]["P"][0]
        assert passive["cooldown"]["affectedByCdr"] is False
        assert passive["cooldown"]["modifiers"][0]["values"][17] == pytest.approx(8.0)

    def test_a_hit_inside_the_recharge_pays_nothing(self):
        """The gate, exercised directly on a synthetic ledger."""
        data = copy.deepcopy(cc_review.kit("Yuumi"))
        events = [
            {"time": time, "source_key": "auto_attacks", "damage": 50.0}
            for time in (0.0, 3.0, 7.9, 8.0, 12.0, 16.5)
        ]
        heals = yuumi.derive_self_healing(data, {"level": 18}, {}, events, [], 20.0)
        paid = [
            event["time"] for event in heals if event["source"] == "Feline Friendship"
        ]
        # recharge 8.0 at level 18: 0.0 pays, 3.0/7.9 are inside it, 8.0
        # re-arms, 12.0 is inside the second window, 16.5 pays.
        assert paid == [0.0, 8.0, 16.5]

    def test_a_hit_that_dealt_no_damage_never_spends_the_buff(self):
        """A whiff is not a hit; the buff survives it."""
        data = copy.deepcopy(cc_review.kit("Yuumi"))
        events = [
            {"time": 0.0, "source_key": "auto_attacks", "damage": 0.0},
            {"time": 1.0, "source_key": "Q", "damage": 40.0},
        ]
        heals = yuumi.derive_self_healing(data, {"level": 18}, {}, events, [], 20.0)
        paid = [
            event["time"] for event in heals if event["source"] == "Feline Friendship"
        ]
        assert paid == [1.0]

    def test_a_kit_with_no_heal_row_is_refused_not_paid_as_zero(self):
        """P is modeled through this rule alone, so a dropped row must raise."""
        data = copy.deepcopy(cc_review.kit("Yuumi"))
        passive = data["abilities"]["P"][0]
        for effect in passive.get("effects", []):
            effect["leveling"] = [
                row
                for row in effect.get("leveling", [])
                if row.get("attribute") != "Heal"
            ]
        with pytest.raises(ValueError, match="no cached 'Heal' leveling row"):
            yuumi.derive_self_healing(data, {"level": 18}, {}, [], [], 10.0)


class TestYouAndMeIsASourcedZeroDamageRow:
    """W: attachment and the Best Friend Bonus, so ``no_damage``.

    The prior receipt kept the slot ``out_of_scope`` and blamed the CHANNEL:
    the heal-and-shield-power amplifier "has no kernel hook (the kernel
    prices received-healing multipliers, not caster heal power)".  That claim
    is false today and is retired here — the caster hook exists and is read
    live.  What is withheld is withheld on the CONDITION, and the row states
    both cached Best Friend numbers rather than restating them as literals.
    """

    @staticmethod
    def _abilities(ranks: dict) -> dict:
        return yuumi.parse_abilities(get_champion("Yuumi"), 18, 0.0, dict(ranks))

    def test_w_emits_a_visible_zero_row(self):
        row = self._abilities(RANKS)["W"]

        assert row["name"] == "You and Me!"
        assert row["total_raw"] == 0.0
        assert row["parts"] == ()
        assert row["detail"]

    def test_w_has_no_damage_clause_anywhere_in_the_cache(self):
        """The verdict is re-derived from the cache, not trusted from prose."""
        for entry in cc_review.kit("Yuumi")["abilities"]["W"]:
            assert entry["damageType"] is None
            assert entry["affects"] == "Allies"
            for effect in entry.get("effects", []):
                for row in effect.get("leveling", []):
                    assert row["attribute"] in (
                        "Heal and Shield Power",
                        "Healing On-Hit",
                    )

    def test_the_row_reads_both_best_friend_rows_at_this_rank(self):
        """Rank 5: 8% heal and shield power, 7 (+3% AP) healing on-hit."""
        detail = self._abilities(RANKS)["W"]["detail"]

        assert "8% heal and shield power" in detail
        assert "7 (+3% AP) healing on-hit" in detail

    def test_the_rank_one_row_reads_the_rank_one_values(self):
        """The numbers move with the rank, so they are read and not literal."""
        detail = self._abilities({"Q": 1, "W": 1, "E": 1, "R": 1})["W"]["detail"]

        assert "4% heal and shield power" in detail
        assert "3 (+3% AP) healing on-hit" in detail

    def test_neither_half_is_published(self):
        """The Akshan-W rider convention: documented, not emitted.

        A published grant would ride every solo Yuumi fight, where she is
        attached to nobody — W's own active "dashes to the target allied
        champion and attaches to them".
        """
        row = self._abilities(RANKS)["W"]

        assert "stat_buff" not in row
        assert row.get("healing") is None

    def test_the_retired_claim_is_false_the_caster_channel_exists(self):
        """Why the label moved: the hook the old receipt denied is live.

        ``_apply_stat_buff_ultimates`` adds any stat key generically, and
        ``heal_and_shield_power_factor`` reads that key back for the CASTER.
        """
        assert healing_reduction.heal_and_shield_power_factor(
            {"heal_and_shield_power_percent": 8.0}
        ) == pytest.approx(1.08)

        stats = {"heal_and_shield_power_percent": 0.0}
        for stat_key, buff_value in {"heal_and_shield_power_percent": 8.0}.items():
            stats[stat_key] = stats.get(stat_key, 0.0) + buff_value
        assert healing_reduction.heal_and_shield_power_factor(stats) == pytest.approx(
            1.08
        )
        assert "heal_and_shield_power_percent" in inspect.getsource(
            healing_reduction.heal_and_shield_power_factor
        )

    @pytest.mark.parametrize("attribute", ["Heal and Shield Power", "Healing On-Hit"])
    def test_a_kit_missing_either_row_is_refused(self, attribute):
        """Fail-closed: the row cites both, so neither may go stale."""
        data = copy.deepcopy(cc_review.kit("Yuumi"))
        for entry in data["abilities"]["W"]:
            for effect in entry.get("effects", []):
                effect["leveling"] = [
                    row
                    for row in effect.get("leveling", [])
                    if row.get("attribute") != attribute
                ]
        with pytest.raises(ValueError, match=f"no cached '{attribute}' leveling row"):
            yuumi.parse_abilities(data, 18, 0.0, dict(RANKS))
