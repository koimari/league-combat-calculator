"""Briar E — sourced charge-window damage reduction + terrain-collision control.

Hand-validated against the cached Briar E descriptions:

- ``effects[0]``: "charging for up to 1 second ... gains 35% damage reduction"
- ``effects[3]``: "become knocked up for 0.5 seconds and stunned for 1.5
  seconds" (terrain collision, behind ``e_wall_collision``)

The E packet authors one timed self damage-modifier (multiplier 1 - 35/100
derived from the ``ability.damage_reduction`` atom, window = min of the
``e_charge_seconds`` option and the ``timing.active_duration`` atom) plus,
with the wall option, two control-only events priced from the
``timing.control_duration_sequence`` atom.  The modifier template declares
``AURA_ARM`` so it sorts before same-timestamp damage in the survival
walk: an amplification in force at its own timestamp prices the hit that
lands there, which a triggered debuff's rank would not.
"""

import copy

import pytest

from src.app import app
from src.calculator.ability_atoms import (
    _ABILITY_ATOMS_MEMO,
    AbilityAtomQuery,
    required_ability_atom,
)
from src.calculator.ability_spec import AttackClass, DamageClass
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.briar import OPTIONS
from src.calculator.data_fetcher import get_champion
from src.calculator.defensive_effects import (
    StartingDefenses,
    resolve_starting_defenses,
)
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    UncompilableActionError,
    _WalkCompiler,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.program.build import roster_program
from src.calculator.program.compile import action_from_event
from src.calculator.program.views.survival import survival
from src.calculator.program.walk import walk as run_one_walk
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.survival import (
    ReceiptLedger,
    SurvivalAction,
    TransitionContext,
    build_states,
)
from src.calculator.survival.actions import (
    EVENT_SLOTS,
    SUPPORT_RANK_KEY,
    ActionKind,
    TransitionRank,
)
from tests.survival_probe import survival_of

# Rank pins for hand-math tests (independent of level/skill order).
MAX_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 2}

_REDUCTION_SOURCE = "Briar.E[0].effects[0].description"
_DURATION_SOURCE = "Briar.E[0].effects[0].description"
_CONTROL_SOURCE = "Briar.E[0].effects[3].description"


def _parse(briar_data, level=18, *, options=None, ranks=MAX_RANKS, **stat_overrides):
    """Parse Briar with crafted stats (deterministic hand-math inputs)."""
    champion_stats = {
        "ability_haste": 0.0,
        "ability_power": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "critical_strike_chance": 0.0,
        "flat_armor_penetration": 0.0,
        "is_melee": True,
        "lethality": 0.0,
        "level": 1,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "max_mana": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "resource_regen_per_second": 0.0,
        "ultimate_haste": 0.0,
        "attack_damage": 200.0,
        "base_attack_damage": 100.0,
        "bonus_attack_damage": 100.0,
        "health": 2000.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.644,
    }
    champion_stats.update(stat_overrides)
    ap = champion_stats.pop("ability_power", 0.0)
    return parse_champion_abilities(
        briar_data,
        level,
        ap,
        ability_ranks=ranks,
        champion_stats=champion_stats,
        champion_options=options,
        target_stats={
            "target_max_health": 3000.0,
            "target_current_health": 3000.0,
            "target_missing_health": 0.0,
        },
    )


def _fight_params(**overrides):
    """FightParams for a default one-rotation fight, field-overridable."""
    config = {
        "target_health": 1000.0,
        "target_bonus_health": 0.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 5.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": True,
        "include_actives": True,
        "cast_order": None,
        "auto_attacks_only": False,
        "ability_ranks": None,
        "champion_options": None,
        "deterministic": True,
    }
    config.update(overrides)
    return FightParams(**config)


def _calculate(payload: dict) -> dict:
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _events(combat: dict, *, attacker: str, target: str, source: str) -> list[dict]:
    return [
        event
        for event in combat["events"]
        if event.get("attacker") == attacker
        and event.get("target") == target
        and event.get("source") == source
    ]


def _briar_against_corki(*, champion_options: dict | None, duration: float = 5.0):
    """Corki (physical autos + 20% true rider + magic Q) into Briar.

    Corki's Hextech Munitions rider makes one timed fight cover all three
    damage types; Briar's E charge starts at t=0, so t=0 packets land
    exactly at charge start and t>=1 packets land after the sourced window.
    """
    return _calculate(
        {
            "champion": "Corki",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": duration,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
            "enemies": [
                {
                    "champion": "Briar",
                    "level": 18,
                    "items": [],
                    "champion_options": champion_options,
                }
            ],
        }
    )


def _run_modifier_window_walk():
    """Walk the survival kernel with Briar's authored damage-modifier
    action (armed at t=0, 0.65x, all sources, sourced 1s window) plus one
    physical/magic/true hit at the window start, a hit just inside and a
    hit exactly at / just after the window end.

    Returns ``(actions, survival_row)``; every damage action carries an
    ``event`` dict the receipt ledger annotates in place, so the tests pin
    the per-packet ``support_damage_multiplier`` receipt as well as the
    aggregated ``damage_taken``.
    """
    combatant = Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 10000.0, "is_melee": True},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
    )

    def hit(time: float, amount: float, damage_type: str, aidx: int, event_id: str):
        return SurvivalAction(
            sort_key=(
                time,
                TransitionRank.DAMAGE,
                0,
                0,
                0,
                "target",
                "hit",
                event_id,
            ),
            time=time,
            phase=TransitionRank.DAMAGE,
            kind=ActionKind.PLAIN_DAMAGE,
            subject=0,
            attacker=0,
            aidx=aidx,
            amount=amount,
            damage_type=damage_type,
            source_key="auto_attacks",
            source="auto_attacks",
            event_slot=EVENT_SLOTS.slot(event_id),
            sequence=0,
            event={},
        )

    modifier = SurvivalAction(
        # ``-1.0`` on a damage modifier is C4's rank: an amplification in
        # force at its own timestamp prices the damage at that timestamp.
        sort_key=(0.0, TransitionRank.AURA_ARM, 0, 0, 0, "target", "mod", "mod"),
        time=0.0,
        phase=TransitionRank.AURA_ARM,
        kind=ActionKind.DAMAGE_MODIFIER,
        subject=0,
        attacker=0,
        aidx=0,
        duration=1.0,
        multiplier=0.65,
        all_sources=True,
        source="Chilling Scream · damage reduction",
        source_key="E",
        event_slot=EVENT_SLOTS.slot("mod"),
        sequence=0,
        # D-04: an armed modifier declares the classes it prices, and
        # empty-means-all is banned.  ``all_sources`` is Briar's own
        # "from all sources", so every class is declared.
        damage_classes=frozenset(DamageClass),
        attack_classes=frozenset(AttackClass),
        event={},
    )
    actions = [
        modifier,
        hit(0.0, 100.0, "physical", 1, "h0"),
        hit(0.0, 200.0, "magic", 2, "h1"),
        hit(0.0, 300.0, "true", 3, "h2"),
        hit(0.5, 400.0, "physical", 4, "h3"),
        hit(0.999, 500.0, "magic", 5, "h4"),
        hit(1.0, 600.0, "true", 6, "h5"),
        hit(1.001, 700.0, "physical", 7, "h6"),
        hit(1.5, 800.0, "magic", 8, "h7"),
    ]
    states = build_states([combatant], (0.0,))
    ledger = ReceiptLedger(
        actions=actions,
        index_of={"target": 0},
        compile_event=action_from_event,
        annotating=True,
    )
    ctx = TransitionContext(
        duration=5.0,
        states=states,
        combatants=[combatant],
        index_of={"target": 0},
        ledger=ledger,
        regeneration_windows=(None,),
    )
    result = run_one_walk(actions, ctx)
    row = survival(roster_program([combatant]), result)["target"]
    return actions, row


class TestAtoms:
    """The exact atoms resolve through the typed accessor with documented
    sources; a wrong query raises naming the source (no literal fallback)."""

    @pytest.fixture(autouse=True)
    def _fresh_atom_memo(self):
        """Atomization is memoized on ``(data_version, champion_name)``.

        The key does not include the ability data, so a case that hands in
        a *tampered* copy would otherwise be answered from rows atomized
        out of the intact cache — the corruption would never reach the
        parser and the raise it should provoke would silently not happen.
        """
        _ABILITY_ATOMS_MEMO.clear()
        yield
        _ABILITY_ATOMS_MEMO.clear()

    def test_damage_reduction_and_active_duration_atoms_resolve(self, briar_data):
        champion_data = {"name": "Briar", "abilities": briar_data["abilities"]}
        reduction = required_ability_atom(
            "Briar",
            champion_data,
            "E",
            query=AbilityAtomQuery(
                source=_REDUCTION_SOURCE,
                behavior="ability",
                evidence_prefix="damage reduction@",
            ),
        )
        assert reduction["values"] == [35.0]
        assert reduction["units"] == ["%"]
        # The acceptance contract names the exact atom ids and evidence
        # prefixes, so the accessor must return them verbatim.
        assert reduction["atom_id"] == "ability.damage_reduction"
        assert reduction["evidence"] == ["damage reduction@effects[0].description"]
        assert reduction["hash"]

        duration = required_ability_atom(
            "Briar",
            champion_data,
            "E",
            query=AbilityAtomQuery(
                source=_DURATION_SOURCE,
                behavior="timing",
                evidence_prefix="active duration@",
            ),
        )
        assert duration["values"] == [1.0]
        assert duration["units"] == ["s"]
        assert duration["atom_id"] == "timing.active_duration"
        assert duration["evidence"] == ["active duration@effects[0].description"]
        assert duration["hash"]

        control = required_ability_atom(
            "Briar",
            champion_data,
            "E",
            query=AbilityAtomQuery(
                source=_CONTROL_SOURCE,
                behavior="timing",
                evidence_prefix="control duration sequence@",
            ),
        )
        assert control["values"] == [0.5, 1.5]
        assert control["units"] == ["s", "s"]
        assert control["atom_id"] == "timing.control_duration_sequence"
        assert control["evidence"] == [
            "control duration sequence@effects[3].description"
        ]
        assert control["hash"]

    def test_missing_atom_raises_naming_the_source(self, briar_data):
        champion_data = {"name": "Briar", "abilities": briar_data["abilities"]}
        with pytest.raises(KeyError) as exc:
            required_ability_atom(
                "Briar",
                champion_data,
                "E",
                query=AbilityAtomQuery(
                    source=_REDUCTION_SOURCE,
                    behavior="timing",
                    evidence_prefix="shield duration@",
                ),
            )
        assert _REDUCTION_SOURCE in str(exc.value)

    def test_missing_duration_atom_fails_closed_through_the_module(self, briar_data):
        """Remove every seconds phrase from the sourced description so the
        ``timing.active_duration`` atom disappears; the E packet must raise
        naming the source path instead of substituting a literal window."""
        tampered = copy.deepcopy(briar_data)
        description = tampered["abilities"]["E"][0]["effects"][0]["description"]
        tampered["abilities"]["E"][0]["effects"][0]["description"] = (
            description.replace("1 second", "one second").replace(
                "0.25 seconds", "quarter second"
            )
        )
        with pytest.raises(KeyError) as exc:
            _parse(tampered, 18)
        assert _DURATION_SOURCE in str(exc.value)
        assert "active duration@" in str(exc.value)

    def test_malformed_control_sequence_fails_closed_naming_the_source(
        self, briar_data
    ):
        """A control sequence missing the stun resolves no sequence atom;
        the wall packet raises naming the source path (opt-in, so only the
        wall path sees it)."""
        tampered = copy.deepcopy(briar_data)
        description = tampered["abilities"]["E"][0]["effects"][3]["description"]
        tampered["abilities"]["E"][0]["effects"][3]["description"] = (
            description.replace(" and stunned for 1.5 seconds", "")
        )
        with pytest.raises(KeyError) as exc:
            _parse(tampered, 18, options={"e_wall_collision": True})
        assert _CONTROL_SOURCE in str(exc.value)
        assert "control duration sequence@" in str(exc.value)


class TestPacket:
    """The E entry authors the sourced damage-modifier packet."""

    def test_e_entry_authors_sourced_damage_modifier(self, briar_data):
        e = _parse(briar_data, 18)["E"]
        events = e["self_state_events"]
        assert len(events) == 1
        packet = events[0]
        assert packet["kind"] == "damage_modifier"
        # The multiplier is derived from the atom (1 - 35/100); the test
        # re-derives it from the receipt instead of pinning a literal.
        reduction = packet["source_atoms"][0]["values"][0]
        assert reduction == 35.0
        assert packet["multiplier"] == pytest.approx(1.0 - reduction / 100.0)
        assert packet["duration"] == pytest.approx(1.0)
        assert packet["source"] == "Chilling Scream · damage reduction"
        assert packet["all_sources"] is True
        assert packet[SUPPORT_RANK_KEY] is TransitionRank.AURA_ARM
        assert [atom["source"] for atom in packet["source_atoms"]] == [
            _REDUCTION_SOURCE,
            _DURATION_SOURCE,
        ]
        assert packet["source_atoms"][0]["hash"]
        assert packet["source_atoms"][1]["values"] == [1.0]

    def test_charge_seconds_capped_at_sourced_duration(self, briar_data):
        """Requesting more than the sourced 1s active duration behaves as
        1s; a zero option removes the window entirely."""
        short = _parse(briar_data, 18, options={"e_charge_seconds": 0.5})["E"]
        assert short["self_state_events"][0]["duration"] == pytest.approx(0.5)
        capped = _parse(briar_data, 18, options={"e_charge_seconds": 5.0})["E"]
        assert capped["self_state_events"][0]["duration"] == pytest.approx(1.0)
        off = _parse(briar_data, 18, options={"e_charge_seconds": 0.0})["E"]
        assert "self_state_events" not in off

    def test_e_damage_and_charge_heal_preserved(self, briar_data):
        """The Maximum Magic Damage read (and wall addend) and the
        healing.py-owned charge heal are untouched by the new packet."""
        e = _parse(briar_data, 18)["E"]
        assert e["total_raw"] == pytest.approx(320.0)
        wall = _parse(briar_data, 18, options={"e_wall_collision": True})["E"]
        assert wall["total_raw"] == pytest.approx(1000.0)
        # The pipeline result still carries the damage-modifier state event
        # and the fight engine still prices the E damage row.
        result = run_fight(briar_data, 18, [], _fight_params())
        assert result["breakdown"]["E"]["total_damage"] > 0.0
        assert [e["kind"] for e in result["self_state_events"]] == ["damage_modifier"]

    def test_charge_heal_still_lands_in_the_coupled_ledger(self):
        """healing.py owns the charge heal; the new packet does not
        duplicate or remove it (4 sourced ticks)."""
        combat = _calculate(
            {
                "champion": "Ezreal",
                "level": 18,
                "items": [],
                "fight_mode": "time_based",
                "fight_duration": 5.0,
                "include_auto_attacks": False,
                "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
                "enemies": [{"champion": "Briar", "level": 18, "items": []}],
            }
        )
        scream_heals = [
            heal
            for heal in combat["healing_events"]
            if heal.get("source") == "Chilling Scream"
        ]
        assert [round(float(heal["time"]), 3) for heal in scream_heals] == [
            0.25,
            0.5,
            0.75,
            1.0,
        ]
        assert all(float(heal["amount"]) > 0.0 for heal in scream_heals)


class TestChargeWindowBounds:
    """The ``e_charge_seconds`` option schema (min 0 / max 1 / default 1)
    and the module's clamp ``min(max(option, 0), sourced_duration)``: out-
    of-range requests are clamped to the sourced window, never rejected."""

    def test_option_schema_min_max_default(self):
        charge = next(
            option for option in OPTIONS if option["key"] == "e_charge_seconds"
        )
        assert charge["type"] == "float"
        assert charge["default"] == 1.0
        assert charge["min"] == 0.0
        assert charge["max"] == 1.0
        assert charge["rotation"] == {"role": "self_state", "slot": "E"}
        wall = next(option for option in OPTIONS if option["key"] == "e_wall_collision")
        assert wall["type"] == "bool"
        assert wall["default"] is False

    def test_negative_charge_clamped_to_zero_removes_the_window(self, briar_data):
        e = _parse(briar_data, 18, options={"e_charge_seconds": -1.0})["E"]
        assert "self_state_events" not in e

    def test_values_above_one_clamp_to_the_sourced_duration(self, briar_data):
        # 1.5 and 2.0 are above the schema max (1.0); the module clamps to
        # the sourced 1s active-duration atom instead of rejecting the
        # request, so the authored window is exactly the sourced window.
        for value in (1.5, 2.0):
            e = _parse(briar_data, 18, options={"e_charge_seconds": value})["E"]
            assert e["self_state_events"][0]["duration"] == pytest.approx(1.0)

    def test_one_is_the_full_sourced_window(self, briar_data):
        e = _parse(briar_data, 18, options={"e_charge_seconds": 1.0})["E"]
        assert e["self_state_events"][0]["duration"] == pytest.approx(1.0)

    def test_option_max_ties_the_sourced_active_duration_atom(self, briar_data):
        """P3-3I: the option schema max (1.0) equals the sourced
        timing.active_duration atom value — a schema change without a
        source change would fail this tie."""
        charge = next(
            option for option in OPTIONS if option["key"] == "e_charge_seconds"
        )
        champion_data = {"name": "Briar", "abilities": briar_data.get("abilities")}
        duration_atom = required_ability_atom(
            "Briar",
            champion_data,
            "E",
            query=AbilityAtomQuery(
                source="Briar.E[0].effects[0].description",
                behavior="timing",
                evidence_prefix="active duration@",
            ),
        )
        sourced = float(duration_atom["values"][0])
        assert charge["max"] == pytest.approx(sourced)


class TestReductionWindow:
    """35% less damage on every damage type during the window; nothing
    after the sourced window expires."""

    def test_35_percent_reduction_covers_physical_magic_and_true(self):
        with_window = _briar_against_corki(champion_options={"e_charge_seconds": 1.0})
        baseline = _briar_against_corki(champion_options={"e_charge_seconds": 0.0})
        in_window = {
            event["source"]: event
            for event in with_window["events"]
            if event.get("target") == "enemy:Briar" and event.get("time") == 0.0
        }
        base = {
            event["source"]: event
            for event in baseline["events"]
            if event.get("target") == "enemy:Briar" and event.get("time") == 0.0
        }
        # Physical (auto), magic (Corki Q), and true (Hextech Munitions
        # rider) all land at charge start and all carry the receipt.
        assert {"auto_attacks", "Q", "auto_attacks_true_damage"} <= set(in_window)
        for source in ("auto_attacks", "Q", "auto_attacks_true_damage"):
            event = in_window[source]
            assert event["support_damage_multiplier"] == {
                "source": "Chilling Scream · damage reduction",
                "multiplier": pytest.approx(0.65),
            }
            # Public event damage is rounded to one decimal; allow it.
            assert event["damage"] == pytest.approx(
                base[source]["damage"] * 0.65, abs=0.1
            )

    def test_no_reduction_after_the_window_expires(self):
        with_window = _briar_against_corki(champion_options={"e_charge_seconds": 1.0})
        baseline = _briar_against_corki(champion_options={"e_charge_seconds": 0.0})
        after = [
            event
            for event in with_window["events"]
            if event.get("target") == "enemy:Briar" and event.get("time") >= 1.0
        ]
        assert after
        for event in after:
            assert "support_damage_multiplier" not in event
        base_after = {
            event["source"]: event
            for event in baseline["events"]
            if event.get("target") == "enemy:Briar" and event.get("time") >= 1.0
        }
        for event in after:
            assert event["damage"] == pytest.approx(
                base_after[event["source"]]["damage"]
            )
        # The window's total saving is exactly the in-window 35%: the
        # reduced fight takes 0.65x of the in-window baseline packets and
        # the full amount of every post-window packet.
        on_taken = survival_of(with_window, "enemy:Briar")["damage_taken"]
        off_taken = survival_of(baseline, "enemy:Briar")["damage_taken"]
        # damage_taken is rounded to one decimal; the recomputed saving is
        # exact, so allow the display rounding.
        assert on_taken == pytest.approx(
            off_taken
            - 0.35
            * sum(
                float(event["damage"])
                for event in baseline["events"]
                if event.get("target") == "enemy:Briar" and event.get("time") < 1.0
            ),
            abs=0.11,
        )

    def test_support_receipt_exposes_the_window_and_source(self):
        combat = _briar_against_corki(champion_options={"e_charge_seconds": 0.75})
        modifier = next(
            event
            for event in combat["support_events"]
            if event.get("kind") == "damage_modifier"
        )
        assert modifier["target"] == "enemy:Briar"
        assert modifier["source"] == "Chilling Scream · damage reduction"
        assert modifier["multiplier"] == pytest.approx(0.65)
        assert modifier["all_sources"] is True
        assert modifier["duration"] == pytest.approx(0.75)
        assert modifier["expires_at"] == pytest.approx(0.75)
        # The hit at t=0 is reduced; the t>=1 autos are not.
        events = [
            event for event in combat["events"] if event.get("target") == "enemy:Briar"
        ]
        assert events[0]["support_damage_multiplier"]["multiplier"] == pytest.approx(
            0.65
        )
        assert all(
            "support_damage_multiplier" not in event
            for event in events
            if event["time"] >= 1.0
        )


class TestTerrainCollisionControl:
    """e_wall_collision prices the sourced knockup + stun sequence on the
    primary target with action downtime and source atoms on the receipt."""

    def test_wall_collision_control_receipts_and_downtime(self):
        combat = _calculate(
            {
                "champion": "Briar",
                "level": 18,
                "items": [],
                "fight_mode": "one_rotation",
                "include_auto_attacks": False,
                "ability_ranks": MAX_RANKS,
                "champion_options": {"e_wall_collision": True},
                "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
            }
        )
        controls = _events(combat, attacker="main", target="enemy:Aatrox", source="E")
        knockup = next(event for event in controls if event.get("cc_kind") == "knockup")
        stun = next(event for event in controls if event.get("cc_kind") == "stun")
        # The scream lands at the END of the full charge, which is where
        # ``champions/briar.py`` puts both its damage part and its control
        # events (``E_FULL_CHARGE_SECONDS``).  Main pinned these at 0.0,
        # from a module whose damage part carried no offset either; the
        # merged module offsets both together, so the sequence is unchanged
        # and only its anchor moved.
        assert knockup["time"] == pytest.approx(1.0)
        assert knockup["cc_duration"] == pytest.approx(0.5)
        assert stun["time"] == pytest.approx(1.5)
        assert stun["cc_duration"] == pytest.approx(1.5)
        for event in (knockup, stun):
            atoms = event["control_source_atoms"]
            assert atoms[0]["source"] == _CONTROL_SOURCE
            assert atoms[0]["values"] == [0.5, 1.5]
            assert atoms[0]["units"] == ["s", "s"]
            assert atoms[0]["hash"]

        survival = survival_of(combat, "enemy:Aatrox")
        assert survival["action_downtime"] == pytest.approx(2.0)
        assert survival["crowd_control_until"] == pytest.approx(3.0)
        assert [
            (interval["kind"], interval["start"], interval["end"])
            for interval in survival["crowd_control_intervals"]
        ] == [
            ("knockup", 1.0, 1.5),
            ("stun", 1.5, 3.0),
        ]
        # The wall damage bonus still lands with the control packet.
        e_damage = next(
            event
            for event in combat["events"]
            if event.get("source") == "E" and event.get("damage", 0.0) > 0.0
        )
        assert e_damage["damage"] > 0.0

    def test_no_control_without_wall_collision(self):
        combat = _calculate(
            {
                "champion": "Briar",
                "level": 18,
                "items": [],
                "fight_mode": "one_rotation",
                "include_auto_attacks": False,
                "ability_ranks": MAX_RANKS,
                "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
            }
        )
        controls = _events(combat, attacker="main", target="enemy:Aatrox", source="E")
        # The merged module authors the full-charge knockback the wiki names
        # ("enemies hit are also knocked back 575 units") on the damage part
        # itself, so a cc_kind IS present without a wall -- but it carries no
        # authored duration, which is what "no control" measured: the wall
        # sequence is still the only thing that locks the target out.
        assert [event.get("cc_kind") for event in controls] == ["knockback"]
        assert all("cc_duration" not in event for event in controls)
        assert survival_of(combat, "enemy:Aatrox")["action_downtime"] == 0.0

    def test_module_parses_control_events_with_atoms(self, briar_data):
        """Parse-level: the entry carries both ControlEvents and the
        sequence atom receipt."""
        e = _parse(briar_data, 18, options={"e_wall_collision": True})["E"]
        events = e["control_events"]
        assert [
            (event.kind, event.duration, event.time_offset) for event in events
        ] == [
            ("knockup", 0.5, 1.0),
            ("stun", 1.5, 1.5),
        ]
        assert e["control_source_atoms"][0]["source"] == _CONTROL_SOURCE
        assert e["control_source_atoms"][0]["values"] == [0.5, 1.5]

    def test_wall_bonus_adds_the_sourced_bonus_magic_damage(self, briar_data):
        """The wall toggle adds exactly the sourced Bonus Magic Damage read
        (re-derived from the bonus atoms — no literal at the call site or
        in the test): flat + 240% bonus AD + 240% AP, at the parsed rank."""
        champion_data = {"name": "Briar", "abilities": briar_data["abilities"]}
        bonus_atoms = [
            required_ability_atom(
                "Briar",
                champion_data,
                "E",
                query=AbilityAtomQuery(
                    source=f"Briar.E[0].effects[3].leveling[0].modifiers[{index}]",
                    behavior="ability",
                    evidence_prefix="Bonus Magic Damage@",
                ),
            )
            for index in range(3)
        ]
        rank = MAX_RANKS["E"]
        expected_bonus = (
            bonus_atoms[0]["values"][rank - 1]
            + bonus_atoms[1]["values"][rank - 1] * 100.0 / 100.0
            + bonus_atoms[2]["values"][rank - 1] * 0.0 / 100.0
        )
        base = _parse(briar_data, 18)["E"]
        wall = _parse(briar_data, 18, options={"e_wall_collision": True})["E"]
        assert wall["total_raw"] - base["total_raw"] == pytest.approx(expected_bonus)

    def test_wall_bonus_scales_the_combat_e_packet(self):
        """At combat level the toggle raises the E packet from the Maximum
        read to Maximum + Bonus: with no items Briar has zero bonus AD/AP,
        so the mitigated event ratio is exactly the raw flat ratio
        (220 -> 660), proving the option feeds the damage engine, not just
        the parse."""
        wall = _calculate(
            {
                "champion": "Briar",
                "level": 18,
                "items": [],
                "fight_mode": "one_rotation",
                "include_auto_attacks": False,
                "ability_ranks": MAX_RANKS,
                "champion_options": {"e_wall_collision": True},
                "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
            }
        )
        no_wall = _calculate(
            {
                "champion": "Briar",
                "level": 18,
                "items": [],
                "fight_mode": "one_rotation",
                "include_auto_attacks": False,
                "ability_ranks": MAX_RANKS,
                "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
            }
        )
        with_bonus = next(
            event
            for event in wall["events"]
            if event.get("source") == "E" and event.get("damage", 0.0) > 0.0
        )
        without_bonus = next(
            event
            for event in no_wall["events"]
            if event.get("source") == "E" and event.get("damage", 0.0) > 0.0
        )
        assert with_bonus["damage"] > without_bonus["damage"]
        assert with_bonus["damage"] == pytest.approx(
            without_bonus["damage"] * 3.0, abs=0.15
        )


class TestPreDamagePriority:
    """A damage modifier armed at the same timestamp as an incoming hit
    applies before that hit (its template sorts at shield priority)."""

    def test_hit_exactly_at_charge_start_is_reduced(self):
        # In one-rotation mode every cast lands at t=0: Ezreal's Q arrives
        # at exactly the timestamp Briar's E charge starts.
        combat = _calculate(
            {
                "champion": "Ezreal",
                "level": 18,
                "items": [],
                "fight_mode": "one_rotation",
                "include_auto_attacks": False,
                "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
                "enemies": [{"champion": "Briar", "level": 18, "items": []}],
            }
        )
        baseline = _calculate(
            {
                "champion": "Ezreal",
                "level": 18,
                "items": [],
                "fight_mode": "one_rotation",
                "include_auto_attacks": False,
                "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
                "enemies": [
                    {
                        "champion": "Briar",
                        "level": 18,
                        "items": [],
                        "champion_options": {"e_charge_seconds": 0.0},
                    }
                ],
            }
        )
        hit = _events(combat, attacker="main", target="enemy:Briar", source="Q")[0]
        assert hit["time"] == 0.0
        assert hit["support_damage_multiplier"]["multiplier"] == pytest.approx(0.65)
        base_hit = _events(baseline, attacker="main", target="enemy:Briar", source="Q")[
            0
        ]
        assert base_hit["time"] == 0.0
        assert hit["damage"] == pytest.approx(base_hit["damage"] * 0.65, abs=0.1)
        # The window receipt sits at the same timestamp, proving the walk
        # armed it before the hit resolved.
        modifier = next(
            event
            for event in combat["support_events"]
            if event.get("kind") == "damage_modifier"
        )
        assert modifier["time"] == 0.0
        assert modifier["duration"] == pytest.approx(1.0)


class TestExactBoundaryTimes:
    """The reduction window is half-open ``[start, start + duration)``: a
    hit at exactly the start is reduced (the -1.0-priority modifier arms
    before same-timestamp damage), a hit at exactly the end is full damage
    (strict expiry: ``until > action.time``)."""

    def test_hit_exactly_at_window_end_is_not_reduced(self):
        actions, _ = _run_modifier_window_walk()
        end = next(
            action for action in actions if EVENT_SLOTS.text(action.event_slot) == "h5"
        )
        assert end.time == 1.0  # exactly start + sourced duration
        assert "support_damage_multiplier" not in end.event
        assert end.event["damage"] == pytest.approx(600.0)
        just_outside = next(
            action for action in actions if EVENT_SLOTS.text(action.event_slot) == "h6"
        )
        assert "support_damage_multiplier" not in just_outside.event
        assert just_outside.event["damage"] == pytest.approx(700.0)

    def test_hit_just_inside_the_window_end_is_reduced(self):
        actions, _ = _run_modifier_window_walk()
        inside = next(
            action for action in actions if EVENT_SLOTS.text(action.event_slot) == "h4"
        )
        assert inside.time == pytest.approx(0.999)
        assert inside.event["support_damage_multiplier"] == {
            "source": "Chilling Scream · damage reduction",
            "multiplier": 0.65,
        }
        assert inside.event["damage"] == pytest.approx(500.0 * 0.65)

    def test_exact_window_arithmetic_in_the_receipt(self):
        """The receipt carries ``expires_at == start + duration`` and the
        walk applies the 0.65 multiplier to every packet strictly inside
        the window: in-window 100+200+300+400+500, out-of-window 600+700
        +800.  Any inclusive-expiry or off-by-one boundary bug changes this
        exact total."""
        actions, row = _run_modifier_window_walk()
        modifier = actions[0]
        assert modifier.event["expires_at"] == pytest.approx(1.0)
        assert row["damage_taken"] == pytest.approx(
            0.65 * (100.0 + 200.0 + 300.0 + 400.0 + 500.0) + 600.0 + 700.0 + 800.0
        )

    def test_all_sources_reduced_inside_window_and_full_after(self):
        """The all-sources modifier gates physical, magic, AND true damage
        inside the window (each packet carries the 0.65 receipt); every
        packet after the window is full with no receipt."""
        actions, _ = _run_modifier_window_walk()
        for event_id, amount in (("h0", 100.0), ("h1", 200.0), ("h2", 300.0)):
            action = next(
                item
                for item in actions
                if EVENT_SLOTS.text(item.event_slot) == event_id
            )
            assert action.event["support_damage_multiplier"]["multiplier"] == (
                pytest.approx(0.65)
            )
            assert action.event["damage"] == pytest.approx(amount * 0.65)
        for event_id, amount in (("h5", 600.0), ("h6", 700.0), ("h7", 800.0)):
            action = next(
                item
                for item in actions
                if EVENT_SLOTS.text(item.event_slot) == event_id
            )
            assert "support_damage_multiplier" not in action.event
            assert action.event["damage"] == pytest.approx(amount)


class TestScoreAndReceiptAgreement:
    """The compiled optimizer walk applies the same damage-modifier
    semantics as the receipt walk; unsupported forms fail closed with a
    named receipt (issue #137 contract)."""

    @staticmethod
    def _briar_timeline(champion_options, **kwargs):
        champion = get_champion("Briar")
        params = FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 5.0,
                "role": "jungle",
                "champion_options": champion_options,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
                "cast_order": ["Q", "W", "E", "R"],
            },
            deterministic=True,
        )
        enemies = [ChampionLoadout(champion="Corki", level=18, role="mid").resolve()]
        stats = calculate_total_stats(champion, 18, [], role="jungle")
        defenses = resolve_starting_defenses("Briar", 18, stats, [])
        return build_participant_timeline(
            champion,
            18,
            [],
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=[],
            **kwargs,
        )

    def test_compiled_score_walk_matches_receipt_for_damage_modifier(self):
        """Score mode (compiled walk) equals the score-only receipt walk
        and both equal the receipt walk's survival numbers; the reduction
        is active in both (not silently dropped) and the terrain-collision
        control compiles too."""
        options = {"e_charge_seconds": 1.0, "e_wall_collision": True}
        legacy_score = self._briar_timeline(options, include_receipt=False)
        fast = self._briar_timeline(
            options,
            pair_result_cache={},
            include_receipt=False,
            search_context=CoupledSearchContext(),
        )
        assert fast == legacy_score
        # The enemy's sourced knockup+stun downtime rides both walks.
        assert fast["participants"][1]["survival"]["action_downtime"] == pytest.approx(
            2.0
        )
        receipt = self._briar_timeline(options)
        assert (
            fast["participants"][0]["survival"]["damage_taken"]
            == receipt["participants"][0]["survival"]["damage_taken"]
        )
        off = self._briar_timeline({"e_charge_seconds": 0.0})
        assert (
            receipt["participants"][0]["survival"]["damage_taken"]
            < off["participants"][0]["survival"]["damage_taken"]
        )

    def test_compiler_compiles_supported_damage_modifier(self):
        """A representable template compiles to ActionKind.DAMAGE_MODIFIER
        carrying every typed field, sorted at the pre-damage priority."""
        compiler = _WalkCompiler()
        template = {
            "target": "enemy:Briar",
            "kind": "damage_modifier",
            "multiplier": 0.65,
            "duration": 1.0,
            "all_sources": True,
            "persistent": False,
            "next_event_only": False,
            "damage_reduction": False,
            "owner": "",
            "source_participant": "",
            "source": "Chilling Scream · damage reduction",
            "source_key": "E",
            "_event_id": "self_state:E:0:0",
            SUPPORT_RANK_KEY: TransitionRank.AURA_ARM,
            "attacker": "enemy:Briar",
        }
        compiler.add_support_templates([template], 1, {"main": 0, "enemy:Briar": 1})
        action = compiler.actions[0]
        assert action.kind is ActionKind.DAMAGE_MODIFIER
        # A modifier in force at its own timestamp arms at C4's
        # ``AURA_ARM`` -- before the damage there, which is the fact the
        # retired float encoded and the author now names.
        assert action.phase is TransitionRank.AURA_ARM
        assert action.multiplier == pytest.approx(0.65)
        assert action.duration == pytest.approx(1.0)
        assert action.all_sources is True
        assert action.persistent is False
        assert action.next_event_only is False
        # ``owner`` is a participant id the packet declares; the kernel
        # keeps the roster slot it resolves to, and ``-1`` is the integer
        # spelling of the empty owner string.
        assert action.holder == -1
        assert action.source_participant == ""
        assert action.source == "Chilling Scream · damage reduction"
        assert action.source_key == "E"
        assert EVENT_SLOTS.text(action.event_slot) == "self_state:E:0:0"

    def test_compiled_walk_prices_the_control_sequence(self):
        """Current observable for the wall option: the terrain-collision
        control events COMPILE into the score walk (no fail-closed receipt
        is raised) and land the sourced sequence on the enemy's survival
        row exactly as the receipt walk does."""
        options = {"e_charge_seconds": 1.0, "e_wall_collision": True}
        fast = self._briar_timeline(
            options,
            pair_result_cache={},
            include_receipt=False,
            search_context=CoupledSearchContext(),
        )
        survival = fast["participants"][1]["survival"]
        assert survival["action_downtime"] == pytest.approx(2.0)
        # Anchored at the end of the full charge -- see
        # ``test_wall_collision_control_receipts_and_downtime``.
        assert survival["crowd_control_until"] == pytest.approx(3.0)
        assert [
            (interval["kind"], interval["start"], interval["end"])
            for interval in survival["crowd_control_intervals"]
        ] == [
            ("knockup", 1.0, 1.5),
            ("stun", 1.5, 3.0),
        ]

    @pytest.mark.parametrize(
        ("template", "receipt"),
        [
            (
                {
                    "target": "main",
                    "kind": "damage_modifier",
                    "multiplier": 0.65,
                    "duration": 0.0,
                    "source": "synthetic",
                },
                "support_duration=0",
            ),
            (
                {
                    "target": "main",
                    "kind": "damage_modifier",
                    "multiplier": float("nan"),
                    "duration": 1.0,
                    "source": "synthetic",
                },
                "support_damage_modifier_multiplier=nonfinite",
            ),
            (
                {
                    "target": "main",
                    "kind": "damage_modifier",
                    "multiplier": -0.5,
                    "duration": 1.0,
                    "source": "synthetic",
                },
                "support_damage_modifier_multiplier=nonfinite",
            ),
            (
                {
                    "target": "main",
                    "kind": "damage_modifier",
                    "damage_reduction": True,
                    "amount": float("inf"),
                    "duration": 1.0,
                    "source": "synthetic",
                },
                "support_damage_modifier_amount=nonfinite",
            ),
            (
                {
                    "target": "main",
                    "kind": "damage_modifier",
                    "multiplier": 0.65,
                    "duration": 1.0,
                    "armor_reduction_percent": float("nan"),
                    "source": "synthetic",
                },
                "support_damage_modifier_armor_reduction_percent=nonfinite",
            ),
        ],
    )
    def test_compiler_fails_closed_on_invalid_damage_modifier(
        self, template: dict, receipt: str
    ):
        """Forms the score kernel cannot apply raise a named receipt so the
        caller falls back to the authoritative receipt walk (nothing is
        silently dropped or mis-compiled)."""
        compiler = _WalkCompiler()
        with pytest.raises(UncompilableActionError) as exc:
            compiler.add_support_templates([template], 0, {"main": 0})
        assert exc.value.receipt == receipt
        assert exc.value.source == "synthetic"


class TestDeterministicReceipts:
    """Identical fights produce identical self-state and control receipts,
    and the damage-modifier packet is authored exactly once per E cast
    (no duplicate packets)."""

    @staticmethod
    def _wall_fight():
        return _calculate(
            {
                "champion": "Briar",
                "level": 18,
                "items": [],
                "fight_mode": "one_rotation",
                "include_auto_attacks": False,
                "ability_ranks": MAX_RANKS,
                "champion_options": {"e_wall_collision": True},
                "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
            }
        )

    def test_repeated_fights_emit_identical_modifier_receipts(self):
        first = _briar_against_corki(champion_options={"e_charge_seconds": 1.0})
        second = _briar_against_corki(champion_options={"e_charge_seconds": 1.0})

        def modifiers(combat: dict) -> list[dict]:
            return [
                event
                for event in combat["support_events"]
                if event.get("kind") == "damage_modifier"
            ]

        one, two = modifiers(first), modifiers(second)
        assert len(one) == len(two) == 1  # exactly one packet, no duplicate
        assert one == two  # byte-identical receipts across identical fights
        # The published id names its owner.  The champion module authors
        # ``self_state:E:0:0`` out of what Briar knows -- slot, cast
        # ordinal, packet ordinal -- which is the same spelling for every
        # actor holding the mechanic; the roster fold that first knows
        # WHICH actor cast it prefixes the participant id, so a roster
        # holding one champion twice publishes two distinct ids instead of
        # one id twice.  Briar is the enemy here, hence ``enemy:Briar:``.
        assert one[0]["event_id"] == "enemy:Briar:self_state:E:0:0"
        # The ordering float is transport between the author and the walk;
        # the published receipt serializes an explicit key list and never
        # sees it (``survival.actions.SUPPORT_RANK_KEY``).
        assert "priority" not in one[0]
        assert one[0]["duration"] == pytest.approx(1.0)
        assert one[0]["expires_at"] == pytest.approx(1.0)

    def test_repeated_wall_fights_emit_identical_control_receipts(self):
        def controls(combat: dict) -> list[dict]:
            return [
                event
                for event in _events(
                    combat, attacker="main", target="enemy:Aatrox", source="E"
                )
                # The full-charge knockback also carries a ``cc_kind`` now
                # and authors no duration; this row is about the sourced
                # knockup/stun sequence, which is what carries one.
                if "cc_duration" in event
            ]

        first = controls(self._wall_fight())
        second = controls(self._wall_fight())
        assert first == second
        assert [(event["cc_kind"], event["cc_duration"]) for event in first] == [
            ("knockup", 0.5),
            ("stun", 1.5),
        ]

    def test_parse_level_self_state_and_control_events_are_deterministic(
        self, briar_data
    ):
        options = {"e_charge_seconds": 1.0, "e_wall_collision": True}
        first = _parse(briar_data, 18, options=options)["E"]
        second = _parse(briar_data, 18, options=options)["E"]
        assert first["self_state_events"] == second["self_state_events"]
        assert first["control_source_atoms"] == second["control_source_atoms"]
        assert [
            (event.kind, event.duration, event.time_offset)
            for event in first["control_events"]
        ] == [
            (event.kind, event.duration, event.time_offset)
            for event in second["control_events"]
        ]
