"""Fimbulwinter Everlasting crowd-control review-status certification.

This packet covers the explicit module-level reviewed-no-CC declaration and
the precise review stamps needed by mixed damage/control abilities.  Missing
metadata stays unreviewed.  The focused matrix checks full and score paths.
"""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("authorized_fimbulwinter_mana_gate")

from src.calculator.champions import ezreal, karma, morgana, parse_champion_abilities
from src.calculator.damage import (
    FightConfig,
    _control_armed_event_coverage,
    calculate_fight_damage,
)
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_support_effects import derive_item_support_effects
from src.calculator.stats import calculate_total_stats

FIMBULWINTER = "Fimbulwinter"
EVERLASTING = "Fimbulwinter — Everlasting"


def _fight(
    champion_name: str,
    slot: str,
    *,
    ability_ranks: dict[str, int],
    champion_options: dict | None = None,
    score_only: bool = False,
) -> dict:
    """Run one selected ability through the Fimbulwinter coverage gate."""
    champion = get_champion(champion_name)
    item = get_item_by_name(FIMBULWINTER)
    stats = calculate_total_stats(champion, 18, [item])
    abilities = parse_champion_abilities(
        champion,
        18,
        stats["ability_power"],
        ability_ranks=ability_ranks,
        champion_stats=stats,
        target_stats={
            "target_max_health": 5_000.0,
            "target_current_health": 5_000.0,
            "target_missing_health": 0.0,
        },
        champion_options=champion_options or {},
    )
    return calculate_fight_damage(
        stats,
        {slot: abilities[slot]},
        [item],
        FightConfig(
            target_health=5_000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            one_rotation=True,
            cast_order=[slot],
        ),
        score_only=score_only,
    )


def _ability_events(result: dict, slot: str) -> list[dict]:
    return [
        event
        for event in result["damage_events"]
        if isinstance(event, dict) and event.get("source_key") == slot
    ]


def _actor(
    participant_id: str,
    team: str,
    items: tuple[str, ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in items),
        stats={"mana": 1_000.0, "max_mana": 1_000.0, "is_melee": False},
        request=SimpleNamespace(item_options={}, ally_effects_enabled=True),
    )


class TestModuleReviewDeclaration:
    """A module can opt in only after every ability entry is reviewed.

    The declaration is ``MODULE_CC``: one kind per slot, with ``"none"``
    meaning "reviewed, and this slot applies no control".  There is no
    separate module-level review flag to fall out of step with it.
    """

    def test_mixed_modules_do_not_claim_blanket_no_cc_review(self):
        assert set(morgana.MODULE_CC.values()) != {"none"}
        assert set(karma.MODULE_CC.values()) != {"none"}
        assert not hasattr(morgana, "CC_REVIEW_STATUS")
        assert not hasattr(karma, "CC_REVIEW_STATUS")

    def test_ezreal_has_local_source_authority_for_no_cc_review(self):
        assert ezreal.SOURCES == [
            {
                "label": "Local League Wiki cache",
                "url": "https://wiki.leagueoflegends.com/en-us/Ezreal",
                "revision_id": 4041697,
                "revision_timestamp": "2026-07-10T18:11:03Z",
            }
        ]

    def test_ezreal_explicitly_opts_in_as_reviewed_no_cc(self):
        assert ezreal.MODULE_CC
        assert set(ezreal.MODULE_CC.values()) == {"none"}

    def test_ezreal_no_cc_event_is_reviewed_and_certified(self):
        result = _fight(
            "Ezreal",
            "Q",
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
        )
        events = _ability_events(result, "Q")
        assert events
        assert all(event.get("cc_reviewed") is True for event in events)
        # ``"none"`` is the reviewed-no-control marker: it certifies the row
        # and is never a live control kind.
        assert all(event.get("cc_kind") == "none" for event in events)
        assert result["timeline_coverage"]["complete"] is True
        assert (
            "fimbulwinter_everlasting"
            not in result["timeline_coverage"]["coarse_sources"]
        )


class TestMixedAbilityReviewStamps:
    """Typed control and reviewed-no-control entries share one ability."""

    def test_morgana_r_stamps_initial_hit_and_keeps_tether_stun(self):
        result = _fight(
            "Morgana",
            "R",
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 3},
        )
        events = _ability_events(result, "R")
        assert len(events) == 2
        assert events[0].get("cc_reviewed") is True
        assert events[0].get("cc_kind") == "slow"
        assert events[1].get("cc_reviewed") is True
        assert events[1].get("cc_kind") == "stun"
        assert result["timeline_coverage"]["complete"] is True

    @pytest.mark.parametrize(
        ("champion", "slot", "kind"),
        [
            ("Teemo", "Q", "blind"),
            ("Malphite", "E", "cripple"),
            ("Malzahar", "Q", "silence"),
        ],
    )
    def test_a_soft_control_row_is_certified_like_any_other(self, champion, slot, kind):
        """The certification asks whether a module reviewed the row, so it
        is decided by vocabulary membership and not by whether the kind
        happens to block actions or slow."""
        result = _fight(
            champion,
            slot,
            ability_ranks={key: 5 if key == slot else 0 for key in "QWER"},
        )
        events = _ability_events(result, slot)
        assert events
        assert all(event.get("cc_kind") == kind for event in events)
        assert all(event.get("cc_reviewed") is True for event in events)

    def test_karma_w_stamps_initial_hit_and_keeps_tether_root(self):
        result = _fight(
            "Karma",
            "W",
            ability_ranks={"Q": 0, "W": 5, "E": 0, "R": 0},
            champion_options={
                "q_mantra": False,
                "w_renewal": False,
                "w_tether_holds": True,
            },
        )
        events = _ability_events(result, "W")
        assert len(events) == 2
        assert events[0].get("cc_reviewed") is True
        assert events[0].get("cc_kind") == "none"
        assert events[1].get("cc_reviewed") is True
        assert events[1].get("cc_kind") == "root"
        assert result["timeline_coverage"]["complete"] is True

    def test_karma_broken_tether_is_precisely_reviewed_no_cc(self):
        result = _fight(
            "Karma",
            "W",
            ability_ranks={"Q": 0, "W": 5, "E": 0, "R": 0},
            champion_options={
                "q_mantra": False,
                "w_renewal": False,
                "w_tether_holds": False,
            },
        )
        events = _ability_events(result, "W")
        assert len(events) == 1
        assert events[0].get("cc_reviewed") is True
        assert events[0].get("cc_kind") == "none"
        assert result["timeline_coverage"]["complete"] is True


class TestFailClosedReviewState:
    """Missing, false, and unknown metadata never gain review authority."""

    @pytest.mark.parametrize(
        "event",
        [
            {"is_ability": True, "source_key": "Q", "time": 0.0},
            {
                "is_ability": True,
                "source_key": "Q",
                "time": 0.0,
                "cc_reviewed": False,
            },
        ],
    )
    def test_unknown_or_degraded_ability_event_stays_coarse(self, event):
        complete, source, note = _control_armed_event_coverage(
            [get_item_by_name(FIMBULWINTER)],
            [event],
        )
        assert complete is False
        assert source == "fimbulwinter_everlasting"
        assert "Fimbulwinter" in note
        assert "Everlasting" in note

    def test_unknown_cc_kind_is_refused_and_never_shields(self):
        """An unspellable kind is refused outright, not read as no control.

        Main published a ``"unclassified_control"`` marker and answered it
        with an ``unknown_cc_kind`` denial row.  The merged vocabulary is
        closed (``trigger_stream.CC_KIND_VOCABULARY``) and the classifier
        raises on anything outside it, which is the same refusal one step
        earlier: a misspelled kind can never reach a shield decision at all.
        """
        holder = _actor("main:Ezreal", "main", (FIMBULWINTER,))
        enemy = _actor("enemy:Aatrox", "enemy")
        with pytest.raises(ValueError, match="CC_KIND_VOCABULARY"):
            derive_item_support_effects(
                holder,
                {
                    "damage_events": [
                        {
                            "time": 1.0,
                            "source_key": "Q",
                            "target": enemy.participant_id,
                            "ability_instance": "Q:1",
                            "cc_kind": "unclassified_control",
                        }
                    ],
                    "cast_timeline": [{"time": 1.0, "resource_after": 900.0}],
                },
                [holder, enemy],
            )

    def test_an_unmarked_ability_hit_never_shields(self):
        """The case main's denial row really guarded: no marker at all."""
        holder = _actor("main:Ezreal", "main", (FIMBULWINTER,))
        enemy = _actor("enemy:Aatrox", "enemy")
        packets = derive_item_support_effects(
            holder,
            {
                "damage_events": [
                    {
                        "time": 1.0,
                        "source_key": "Q",
                        "target": enemy.participant_id,
                        "ability_instance": "Q:1",
                        "damage": 100.0,
                        "is_ability": True,
                    }
                ],
                "cast_timeline": [{"time": 1.0, "resource_after": 900.0}],
            },
            [holder, enemy],
        )
        shields = [
            packet
            for packet in packets
            if packet.get("source") == EVERLASTING and packet.get("kind") == "shield"
        ]
        assert shields == []


class TestControlOnlyEvents:
    """A typed control-only event stays eligible without invented damage."""

    def test_control_only_root_triggers_everlasting(self):
        holder = _actor("main:Morgana", "main", (FIMBULWINTER,))
        enemy = _actor("enemy:Aatrox", "enemy")
        packets = derive_item_support_effects(
            holder,
            {
                "damage_events": [],
                "control_events": [
                    {
                        "time": 1.0,
                        "source_key": "Q",
                        "source": "Dark Binding",
                        "target": enemy.participant_id,
                        "ability_instance": "Q:1",
                        "cc_kind": "root",
                        "cc_reviewed": True,
                        "damage": 0.0,
                        "is_ability": True,
                    }
                ],
                "cast_timeline": [{"time": 1.0, "resource_after": 900.0}],
            },
            [holder, enemy],
        )
        shields = [
            packet
            for packet in packets
            if packet.get("source") == EVERLASTING and packet.get("kind") == "shield"
        ]
        assert len(shields) == 1
        assert shields[0]["trigger_kind"] == "immobilize"


class TestOptimizerAndReceiptParity:
    """The score path uses the same review decision and damage values."""

    @pytest.mark.parametrize(
        ("champion_name", "slot", "ranks", "options"),
        [
            ("Morgana", "R", {"Q": 0, "W": 0, "E": 0, "R": 3}, {}),
            (
                "Karma",
                "W",
                {"Q": 0, "W": 5, "E": 0, "R": 0},
                {
                    "q_mantra": False,
                    "w_renewal": False,
                    "w_tether_holds": True,
                },
            ),
        ],
    )
    def test_score_and_receipt_paths_match(
        self,
        champion_name,
        slot,
        ranks,
        options,
    ):
        full = _fight(
            champion_name,
            slot,
            ability_ranks=ranks,
            champion_options=options,
        )
        score = _fight(
            champion_name,
            slot,
            ability_ranks=ranks,
            champion_options=options,
            score_only=True,
        )
        assert score["total_damage"] == pytest.approx(full["total_damage"])
        for key in ("complete", "exact_sources", "coarse_sources"):
            assert score["timeline_coverage"][key] == full["timeline_coverage"][key]

    @pytest.mark.parametrize(
        ("champion_name", "slot", "ranks", "options"),
        [
            ("Morgana", "R", {"Q": 0, "W": 0, "E": 0, "R": 3}, {}),
            (
                "Karma",
                "W",
                {"Q": 0, "W": 5, "E": 0, "R": 0},
                {
                    "q_mantra": False,
                    "w_renewal": False,
                    "w_tether_holds": True,
                },
            ),
        ],
    )
    def test_optimizer_path_certifies_reviewed_mixed_ability(
        self,
        champion_name,
        slot,
        ranks,
        options,
    ):
        score = _fight(
            champion_name,
            slot,
            ability_ranks=ranks,
            champion_options=options,
            score_only=True,
        )
        assert score["timeline_coverage"]["complete"] is True
        assert (
            "fimbulwinter_everlasting"
            not in score["timeline_coverage"]["coarse_sources"]
        )
