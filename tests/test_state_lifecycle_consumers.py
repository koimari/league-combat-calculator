"""P1 kernel consumers: Eclipse, Fimbulwinter, Conqueror, Force of Nature,
Ashe Focus, and Rengar Ferocity routed through state_lifecycle.

Each consumer's damage/shield/heal formula stays where it was; these tests
pin that the trigger/stack/cooldown timing is kernel-owned and that the
existing breakdown/event/packet shapes are preserved.
"""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("authorized_fimbulwinter_mana_gate")

from src.calculator import item_effects
from src.calculator import state_lifecycle as sl
from src.calculator.ability_spec import DamagePart
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.ashe import ASHE_FOCUS_STACK_RULE
from src.calculator.champions.rengar import RENGAR_FEROCITY_STACK_RULE
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.interpreters import cast_proc
from src.calculator.item_support_effects import derive_item_support_effects

# ---------------------------------------------------------------------------
# Eclipse: kernel-owned pair gate + per-target cooldown
# ---------------------------------------------------------------------------


def _stats() -> dict:
    return {
        "ability_haste": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_attack_damage": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "health": 0.0,
        "lethality": 0.0,
        "max_mana": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "resource_regen_per_second": 0.0,
        "ultimate_haste": 0.0,
        "attack_damage": 100,
        "ability_power": 0,
        "base_attack_damage": 100,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "magic_penetration_flat": 0,
        "magic_penetration_percent": 0,
        "armor_penetration_percent": 0,
        "flat_armor_penetration": 0,
        "critical_strike_chance": 0,
        "is_melee": False,
        "level": 18,
    }


def _ability(name: str, cooldown: float = 5.0) -> dict:
    return {
        "name": name,
        "rank": 1,
        "cooldown": cooldown,
        "physical_damage": 100,
        "parts": (DamagePart("physical", 100),),
        "total_raw": 100,
        "damage_type": "physical",
    }


def _eclipse_fight(abilities: dict, *, duration: float, **kwargs) -> dict:
    kwargs.setdefault("auto_attack_uptime", 0.0)
    return calculate_fight_damage(
        _stats(),
        abilities,
        [{"name": "Eclipse"}],
        FightConfig(
            target_health=2000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=duration,
            **kwargs,
        ),
    )


class TestEclipseConsumer:
    def test_kernel_gate_rule_matches_sourced_values(self):
        # MERGE: the proc families left ``BuildDamageEffects`` for their
        # own interpreter (a projection field defaulting to an empty tuple
        # would price a whole family at zero with nothing saying so).
        proc = next(
            p
            for p in cast_proc.resolve_slots(
                ("Eclipse",),
                level=11,
                fight_duration_seconds=5.0,
                target_bonus_health=0.0,
                holder_is_melee=True,
            ).cooldown_procs
            if p.source.item_name == "Eclipse"
        )
        gate = item_effects.eclipse_trigger_gate(proc)
        rule = gate.public_receipt()["rule"]
        assert rule["stacks_required"] == 2
        assert rule["window_seconds"] == 2.0
        assert rule["cooldown_seconds"] == 6.0
        assert rule["per_target"] is True
        assert rule["source"]["url"].endswith("/Eclipse")

    def test_proc_row_and_kernel_transition_receipt(self):
        fight = _eclipse_fight(
            {"Q": _ability("Q"), "W": _ability("W")}, duration=1.0, one_rotation=True
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert row["count"] == 1
        # The event now carries the ``AuthoredDeclaration`` the walk prices it
        # from: the rule that authored the packet, its pre-mitigation
        # magnitude and the attack class that decides which of the holder's
        # amplifiers it earns.  The last three positions are the resistance,
        # swing and routing umbrellas, all absent on a proc that reached its
        # subject directly through no basic-attack swing.
        assert row["damage_events"] == [
            {
                "time": 0.0,
                "damage": 100.0,
                "damage_type": "physical",
                "event_precision": "exact",
                "target_id": "target:0",
                "declared": ("eclipse.proc", 100.0, "other", None, None, None),
            }
        ]
        receipt = row["state_transitions"]
        assert receipt["rule"]["stacks_required"] == 2
        kinds = [t["kind"] for t in receipt["transitions"]]
        assert kinds == ["gain", "proc", "cooldown_start"]
        assert receipt["transitions"][1]["detail"]["reset"] is True
        assert receipt["transitions"][2]["detail"]["cooldown_until"] == pytest.approx(
            6.0
        )

    def test_kernel_proc_times_equal_damage_event_times(self):
        fight = _eclipse_fight(
            {"Q": _ability("Q", cooldown=1.0), "W": _ability("W", cooldown=5.0)},
            duration=7.0,
            one_rotation=False,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        event_times = [event["time"] for event in row["damage_events"]]
        proc_times = [p["time"] for p in row["state_transitions"]["procs"]]
        assert event_times == proc_times == [0.0, 7.0]

    def test_window_lapse_does_not_pair(self):
        fight = _eclipse_fight(
            {"Q": _ability("Q", cooldown=3.0)},
            duration=3.0,
            one_rotation=False,
        )
        # Casts land at 0 and 3: 3 > 0 + 2, so the first stack expires and
        # no pair ever completes.  The engine preserves its contract: a
        # passive that never fired authors no proc row (and no aggregate
        # substitute).  The kernel gate itself records the window-lapse
        # expiry and is covered by the kernel tests.
        assert "proc_Eclipse" not in fight["breakdown"]

    def test_receipts_are_deterministic_across_runs(self):
        abilities = {
            "Q": _ability("Q", cooldown=1.0),
            "W": _ability("W", cooldown=5.0),
        }
        first = _eclipse_fight(abilities, duration=7.0, one_rotation=False)
        second = _eclipse_fight(abilities, duration=7.0, one_rotation=False)
        assert (
            first["breakdown"]["proc_Eclipse"]["state_transitions"]
            == second["breakdown"]["proc_Eclipse"]["state_transitions"]
        )

    def test_self_shield_shape_is_preserved(self):
        fight = _eclipse_fight(
            {"Q": _ability("Q"), "W": _ability("W")}, duration=1.0, one_rotation=True
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert row["self_shield_events"] == [
            {
                "amount": 75.0,
                "duration": 2.0,
                "source": "Eclipse (Ever Rising Moon)",
                # P3-3C: the shield receipt carries the pair event's time
                # and precision.
                "time": 0.0,
                "event_precision": "exact",
            }
        ]


# ---------------------------------------------------------------------------
# Conqueror: kernel-owned stack timing (expiry, refresh, 4s interval gate)
# ---------------------------------------------------------------------------


def _conqueror_fight(
    abilities: dict,
    *,
    duration: float,
    starting_stacks: int = 0,
    one_rotation: bool = False,
) -> dict:
    return calculate_fight_damage(
        _stats(),
        abilities,
        [],
        FightConfig(
            target_health=2000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=duration,
            one_rotation=one_rotation,
            auto_attack_uptime=0.0,
            keystone="Conqueror",
            keystone_options={"starting_stacks": starting_stacks},
        ),
    )


class TestConquerorConsumer:
    def test_stack_rule_declaration_uses_sourced_values(self):
        from src.calculator import rune_effects

        rule = rune_effects.conqueror_stack_state(
            rune_effects.resolve_keystone("Conqueror")
        ).rule
        receipt = rule.public_receipt()
        assert receipt["max_stacks"] == 12
        assert receipt["gain_per_application"] == 2
        assert receipt["duration_seconds"] == 5.0
        assert receipt["interval_seconds"] == 4.0
        assert receipt["interval_key"] == "source_key"
        assert receipt["interval_gate_packets"] == ["ability_cast"]
        assert receipt["refresh"] == "refresh"
        assert receipt["source"]["url"].endswith("/Conqueror")

    def test_repeat_casts_within_4s_are_gated(self):
        # One ability on a 1s cooldown: casts at 0,1,2,3 are denied by the
        # interval gate (first grant at 0 gates the slot for 4s), so only
        # the t=0, 4, and 8 grants land in a 10s fight.
        fight = _conqueror_fight({"Q": _ability("Q", cooldown=1.0)}, duration=10.0)
        row = fight["breakdown"]["keystone_Conqueror"]
        assert row["cast_instance_interval_seconds"] == 4.0
        grants = [event for event in row["stack_events"] if not event.get("denied")]
        assert [event["time"] for event in grants] == [0.0, 4.0, 8.0]
        denied = [event for event in row["stack_events"] if event.get("denied")]
        # 11 casts (0..10) minus the 3 grants = 8 interval denials.
        assert len(denied) == 8
        assert all(event["denied"] == "interval_gate" for event in denied)
        # The kernel receipt exposes the same denials.
        denied_transitions = [
            t for t in row["state_transitions"] if t["kind"] == "gain_denied"
        ]
        assert len(denied_transitions) == 8

    def test_5s_expiry_resets_before_the_next_gain(self):
        # A 6s-cooldown ability casts at 0 and 6: the 5s stack window lapses,
        # so the second cast starts from zero again.
        fight = _conqueror_fight({"Q": _ability("Q", cooldown=6.0)}, duration=7.0)
        row = fight["breakdown"]["keystone_Conqueror"]
        events = row["stack_events"]
        assert [event["time"] for event in events] == [0.0, 6.0]
        assert events[1]["stacks_before"] == 0
        assert events[1]["stacks_after"] == 2
        kinds = [t["kind"] for t in row["state_transitions"]]
        assert "expire" in kinds

    def test_max_stack_heal_still_fires(self):
        fight = _conqueror_fight(
            {"Q": _ability("Q", cooldown=1.0)},
            duration=10.0,
            starting_stacks=10,
        )
        heal = fight["breakdown"].get("heal_Conqueror")
        assert heal is not None
        assert heal["total_amount"] > 0
        # Starting at 10, the first grant reaches 12 and heals.
        stack_events = fight["breakdown"]["keystone_Conqueror"]["stack_events"]
        assert any(event["stacks_after"] == 12 for event in stack_events)

    def test_keystone_state_events_aggregation_preserved(self):
        from src.app import _load_public_champion
        from src.calculator.pipeline import FightParams, run_fight

        params = FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 10,
                "rotations": 2,
                "include_auto_attacks": False,
                "auto_attack_uptime": 0,
                "auto_attack_uptime_mode": "calculated",
                "ability_ranks": {"Q": 5},
                "role": "mid",
                "role_quest_complete": True,
                "keystone": "Conqueror",
                "keystone_options": {"starting_stacks": 0},
            },
            deterministic=True,
        )
        result = run_fight(_load_public_champion("Ahri"), 18, [], params)
        state_events = result["keystone_state_events"]
        assert any(event["source"] == "Conqueror · stack" for event in state_events)


# ---------------------------------------------------------------------------
# Fimbulwinter: kernel CC-trigger predicate, instance cadence, cooldown
# ---------------------------------------------------------------------------


def _actor(
    participant_id: str,
    team: str,
    item_names: tuple[str, ...],
    *,
    is_melee: bool = False,
    max_mana: float = 1000.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in item_names),
        stats={
            "mana": max_mana,
            "max_mana": max_mana,
            "is_melee": is_melee,
        },
        request=SimpleNamespace(item_options={}, ally_effects_enabled=True),
    )


class TestFimbulwinterConsumer:
    def test_cc_trigger_predicate_is_kernel_owned(self):
        holder = _actor("main:Ahri", "main", ("Fimbulwinter",))
        enemy = _actor("enemy:Aatrox", "enemy", ())
        packets = derive_item_support_effects(
            holder,
            {
                "damage_events": [
                    {
                        "time": 1.0,
                        "target": enemy.participant_id,
                        "ability_instance": "E:1",
                        "cc_kind": "stun",
                    }
                ]
            },
            [holder, enemy],
        )
        shield = next(
            p
            for p in packets
            if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "shield"
        )
        assert shield["trigger_kind"] == "immobilize"
        assert shield["trigger_rule"]["name"].startswith("Fimbulwinter")
        assert "stun" in shield["trigger_rule"]["immobilize_kinds"]
        assert shield["trigger_rule"]["slow_melee_only"] is True

    def test_cooldown_gate_and_instance_dedup_are_kernel_owned(self):
        holder = _actor("main:Ahri", "main", ("Fimbulwinter",), is_melee=True)
        enemy_one = _actor("enemy:Aatrox", "enemy", ())
        enemy_two = _actor("enemy:Galio", "enemy", ())
        packets = derive_item_support_effects(
            holder,
            {
                "cast_timeline": [{"time": 1.0, "resource_after": 900.0}],
                "damage_events": [
                    {
                        "time": 1.0,
                        "target": enemy_one.participant_id,
                        "source_key": "E",
                        "ability_instance": "E:1",
                        "cc_kind": "slow",
                    },
                    # Same cast instance: must not fire a second shield.
                    {
                        "time": 1.2,
                        "target": enemy_one.participant_id,
                        "source_key": "E",
                        "ability_instance": "E:1",
                        "cc_kind": "slow",
                    },
                    {
                        "time": 5.0,
                        "target": enemy_one.participant_id,
                        "source_key": "E",
                        "ability_instance": "E:2",
                        "cc_kind": "slow",
                    },
                    {
                        "time": 9.0,
                        "target": enemy_one.participant_id,
                        "source_key": "E",
                        "ability_instance": "E:3",
                        "cc_kind": "slow",
                    },
                ],
            },
            [holder, enemy_one, enemy_two],
        )
        shields = [
            p
            for p in packets
            if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "shield"
        ]
        assert [p["time"] for p in shields] == [pytest.approx(1.0), pytest.approx(9.0)]
        assert shields[0]["cooldown_until"] == pytest.approx(9.0)
        assert shields[0]["trigger_kind"] == "slow"
        # The two denials are now NAMED receipts (P3-3B): the same-instance
        # 1.2s event and the in-flight 5.0s cast.
        denials = [
            p
            for p in packets
            if p["source"] == "Fimbulwinter — Everlasting"
            and p["kind"] == "item_denial"
        ]
        assert sorted((round(p["time"], 3), p["reason"]) for p in denials) == [
            (1.0, "nearby_enemy_spatial_input_unavailable"),
            (1.2, "duplicate_instance"),
            (5.0, "cooldown"),
            (9.0, "nearby_enemy_spatial_input_unavailable"),
        ]

    def test_melee_slow_and_ranged_rejection(self):
        enemy = _actor("enemy:Aatrox", "enemy", ())
        ranged = _actor("main:Ahri", "main", ("Fimbulwinter",), is_melee=False)
        packets = derive_item_support_effects(
            ranged,
            {
                "damage_events": [
                    {
                        "time": 1.0,
                        "target": enemy.participant_id,
                        "ability_instance": "E:1",
                        "cc_kind": "slow",
                    }
                ]
            },
            [ranged, enemy],
        )
        assert not [
            p
            for p in packets
            if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "shield"
        ]
        # The ranged-slow rejection is a NAMED receipt (P3-3B).
        denials = [
            p
            for p in packets
            if p["source"] == "Fimbulwinter — Everlasting"
            and p["kind"] == "item_denial"
        ]
        assert [(p["reason"], p["time"]) for p in denials] == [
            ("ranged_slow", pytest.approx(1.0))
        ]
        melee = _actor("main:Ahri", "main", ("Fimbulwinter",), is_melee=True)
        packets = derive_item_support_effects(
            melee,
            {
                "damage_events": [
                    {
                        "time": 1.0,
                        "target": enemy.participant_id,
                        "ability_instance": "E:1",
                        "cc_kind": "slow",
                    }
                ]
            },
            [melee, enemy],
        )
        shield = next(
            p
            for p in packets
            if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "shield"
        )
        assert shield["trigger_kind"] == "slow"

    def test_mana_gate_is_unchanged(self):
        holder = _actor(
            "main:Ahri", "main", ("Fimbulwinter",), is_melee=True, max_mana=1000.0
        )
        enemy = _actor("enemy:Aatrox", "enemy", ())
        packets = derive_item_support_effects(
            holder,
            {
                "cast_timeline": [{"time": 1.0, "resource_after": 100.0}],
                "damage_events": [
                    {
                        "time": 1.0,
                        "target": enemy.participant_id,
                        "ability_instance": "Q:1",
                        "cc_kind": "immobilize",
                    }
                ],
            },
            [holder, enemy],
        )
        assert not [
            p
            for p in packets
            if p["source"] == "Fimbulwinter — Everlasting" and p["kind"] == "shield"
        ]
        # The mana-gate rejection is a NAMED receipt (P3-3B).
        denials = [
            p
            for p in packets
            if p["source"] == "Fimbulwinter — Everlasting"
            and p["kind"] == "item_denial"
        ]
        assert [(p["reason"], p["time"]) for p in denials] == [
            ("mana_gate", pytest.approx(1.0))
        ]


# ---------------------------------------------------------------------------
# Force of Nature: kernel-typed Steadfast declaration
# ---------------------------------------------------------------------------


class TestForceOfNatureConsumer:
    def test_steadfast_source_revision_is_the_reviewed_receipt(self):
        from src.calculator.defensive_effects import defense_source
        from src.calculator.item_behavior import DefenseMechanic

        source = defense_source("Force of Nature", DefenseMechanic.STEADFAST)
        assert source.revision_id == 4016272

    def test_starting_defenses_still_resolve_the_same_fields(self):
        stats = {
            "health": 5000.0,
            "armor": 30.0,
            "magic_resistance": 40.0,
            "bonus_armor": 0.0,
            "bonus_magic_resistance": 0.0,
            "is_melee": False,
        }
        defenses = resolve_starting_defenses(
            "Ahri", 18, stats, [{"name": "Force of Nature"}]
        )
        assert defenses.force_max_stacks == 8
        assert defenses.force_stack_duration == pytest.approx(7.0)
        assert defenses.force_stack_interval == pytest.approx(1.0)
        assert defenses.force_immobilize_stacks == 2
        assert defenses.force_bonus_magic_resistance == pytest.approx(70.0)
        assert defenses.force_bonus_move_speed_percent == pytest.approx(6.0)
        assert any("Force of Nature Steadfast" in text for text in defenses.assumptions)


# ---------------------------------------------------------------------------
# Ashe Focus and Rengar Ferocity: typed kernel state with public receipts
# ---------------------------------------------------------------------------


class TestAsheFocusConsumer:
    def test_focus_rule_is_typed_with_source_receipt(self):
        receipt = ASHE_FOCUS_STACK_RULE.public_receipt()
        assert receipt["max_stacks"] == 4
        assert receipt["gain_per_application"] == 1
        assert receipt["duration_seconds"] == 4.0
        assert receipt["refresh"] == "refresh"
        assert receipt["expiry"] == "step_down"
        assert receipt["expiry_step_seconds"] == 1.0
        assert receipt["cap_behavior"] == "noop"
        assert receipt["source"]["revision_id"] == 4015971

    def test_q_gate_uses_the_typed_state(self):
        data = get_champion("Ashe")
        stats = _stats()
        full = parse_champion_abilities(
            data,
            9,
            0.0,
            ability_ranks={"Q": 5, "W": 1, "E": 0, "R": 0},
            champion_stats=stats,
            champion_options={"q_focus_stacks": 4},
        )
        assert "Q" in full
        partial = parse_champion_abilities(
            data,
            9,
            0.0,
            ability_ranks={"Q": 5, "W": 1, "E": 0, "R": 0},
            champion_stats=stats,
            champion_options={"q_focus_stacks": 3},
        )
        assert "Q" not in partial
        assert "auto_attack_override" in partial["passive"]

    def test_option_carries_the_public_state_receipt(self):
        from src.calculator.champions import get_champion_options_meta

        meta = get_champion_options_meta("Ashe")
        focus_option = next(o for o in meta["options"] if o["key"] == "q_focus_stacks")
        state = focus_option["state"]
        assert state["max_stacks"] == 4
        assert state["source"]["url"].endswith("/Ashe")
        assert any("typed kernel stack state" in text for text in meta["assumptions"])

    def test_kernel_state_drains_after_the_window(self):
        state = sl.TimedStackState(ASHE_FOCUS_STACK_RULE, starting_stacks=4)
        assert state.stacks == 4
        state._materialize_expiries(4.0, sequence=0)
        assert state.stacks == 3
        state._materialize_expiries(5.0, sequence=0)
        assert state.stacks == 2
        state._materialize_expiries(6.0, sequence=0)
        assert state.stacks == 1
        state._materialize_expiries(7.0, sequence=0)
        assert state.stacks == 0


class TestRengarFerocityConsumer:
    def test_ferocity_rule_is_typed_with_source_receipt(self):
        receipt = RENGAR_FEROCITY_STACK_RULE.public_receipt()
        assert receipt["max_stacks"] == 4
        assert receipt["gain_per_application"] == 1
        assert receipt["duration_seconds"] == 1.0
        assert receipt["refresh"] == "none"
        assert receipt["combat_extension_seconds"] == 10.0
        assert receipt["source"]["revision_id"] == 2864152
        assert receipt["source"]["url"].endswith("Data_Rengar/I")

    def test_empowered_gate_uses_the_typed_state(self):
        data = get_champion("Rengar")
        empowered = parse_champion_abilities(
            data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            champion_options={"p_ferocity": 4},
        )
        base = parse_champion_abilities(
            data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            champion_options={"p_ferocity": 0},
        )
        assert "Ferocity-empowered" in empowered["Q"]["detail"]
        assert "Ferocity-empowered" not in base["Q"]["detail"]
        assert empowered["Q"]["total_raw"] > base["Q"]["total_raw"]

    def test_option_carries_the_public_state_receipt(self):
        from src.calculator.champions import get_champion_options_meta

        meta = get_champion_options_meta("Rengar")
        ferocity_option = next(o for o in meta["options"] if o["key"] == "p_ferocity")
        state = ferocity_option["state"]
        assert state["max_stacks"] == 4
        assert state["refresh"] == "none"
        assert any("typed kernel stack state" in text for text in meta["assumptions"])

    def test_kernel_state_consume_empowers(self):
        state = sl.TimedStackState(RENGAR_FEROCITY_STACK_RULE, starting_stacks=4)
        consumed = state.consume(0.0, sequence=0)
        assert consumed is not None
        assert consumed.detail["empowered"] is True
        assert state.stacks == 0
