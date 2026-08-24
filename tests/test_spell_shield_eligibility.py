"""P2 Slice 2 spell-shield acceptance matrix — Sivir E + Annul items.

This file is the RLM-2 acceptance-matrix suite for the spell-shield
eligibility/use lifecycle added to ``src/calculator/delivery_eligibility.py``
(P2 Slice 2; consumers: Sivir E timed 1.5s window + one on-block heal,
Banshee's Veil / Edge of Night / Verdant Barrier Annul — ready at fight
start, block one hostile ability, and rearm once their sourced 40/40/60s
cooldown has fully elapsed from the later of the consumption instant and
the last champion damage the holder took).  It follows the styles of
``test_delivery_interaction_eligibility.py``
and ``test_interaction_atoms.py``: kernel unit tests with minimal
_Action/_Attacker classes for pure kernel cases, and ``src.app`` ->
``POST /api/calculate`` consumer tests for end-to-end cases.

Row status conventions (same as the P2 Slice 1 matrix):
- "CURRENT" rows assert behavior the tree already satisfies today.
- "NEW-CONTRACT" rows assert the kernel API the owner commits to
  (``de.SpellShieldAcceptance``, ``de.SpellShieldEligibility``,
  ``de.SpellShieldDecision``, ``de.resolve_cast_identity``,
  ``de.UseBudget(consume='per_cast')``, ``de.TriggeredHealRule``,
  ``de.SpellShieldComposition``).  They fail today with
  AttributeError/ValueError and are reported as "pending kernel" until the
  kernel lands; the assertion is the intended signal for the owner.

Matrix rows covered (row id | dimension | level):
R1  | Sivir E eligible block + exactly one triggered heal          | app
R2  | Annul items block one ability; second ability passes        | app
R3  | basic attack first does NOT consume; ability then blocks    | app+timeline
R4  | multi-part cast (same cast): all packets blocked, one use,
     one heal                                                     | app
R5  | control-only cast consumes and blocks                       | timeline
R6  | two casts at one timestamp: total order decides; same-slot
     collision splits across attackers (attacker-qualified grouping
     key; sourced distinct vs derived fallback)                   | app+kernel
R7  | window boundaries (start inclusive, end exclusive) + accept
     reasons                                                      | kernel
R8  | walk order: stasis -> projectile defense -> spell shield    | app
R9  | unknown/missing cast identity fails closed, no consumption  | kernel
R10 | survival-row receipt vs blocked events parity              | app
R11 | score-path fail-closed receipts (Annul items, Sivir heal
     template)                                                    | unit
R12 | kernel contract: receipt shapes, budget modes, decision
     reasons, cast-identity kinds                                 | kernel
R13 | sourced rearm clock end to end on Banshee's 40s: endpoint
     pins, a rearm inside the window, a cooldown that outlasts the
     window, and the unsourced shield that never rearms          | walk
"""

from types import SimpleNamespace

import pytest

from src.app import app
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator import delivery_eligibility as de
from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import get_champion
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.interaction_effects import resolve_spell_shield
from src.calculator.item_effects import (
    annul_spell_shield_cooldown_atom,
    annul_spell_shield_timer_restarts,
    spell_shield_cooldown_seconds,
)
from src.calculator.participant_timeline import Combatant
from src.calculator.stats import calculate_total_stats
from src.calculator.interpreters import uncompilable_item_receipt
from src.calculator.survival import unrepresentable_template_receipt
from tests.survival_probe import simulate_survival
from tests.survival_probe import survival_of

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _calculate(payload: dict) -> dict:
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _events(combat: dict, *, target: str, source: str | None = None) -> list[dict]:
    return [
        event
        for event in combat["events"]
        if event.get("target") == target
        and (source is None or event.get("source") == source)
    ]


def _spell_shield_blocked(combat: dict, target: str) -> list[dict]:
    return [
        event
        for event in combat["events"]
        if event.get("target") == target
        and event.get("skipped_reason") == "spell_shield"
    ]


def _sivir() -> dict:
    return {
        "champion": "Sivir",
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": 3.0,
        "include_auto_attacks": False,
        "cast_order": ["E", "Q", "R", "W"],
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
    }


def _ezreal_q_only(duration: float = 9.0) -> dict:
    return {
        "champion": "Ezreal",
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": False,
        "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
    }


def _sivir_expected_heal() -> float:
    data = get_champion("Sivir")
    stats = calculate_total_stats(data, 18, [])
    entry = parse_champion_abilities(
        data,
        18,
        float(stats.get("ability_power", 0.0)),
        {"E": 5},
        champion_stats=stats,
    )["E"]
    [shield_state] = entry["self_state_events"]
    assert shield_state["kind"] == "spell_shield"
    return float(shield_state["on_block_heal_amount"])


# ---------------------------------------------------------------------------
# Minimal kernel actors (pure kernel cases)
# ---------------------------------------------------------------------------


class _Action:
    """One incoming packet with the typed fields the kernel reads."""

    def __init__(
        self,
        *,
        time: float = 0.5,
        source_key: str = "Q",
        is_ability: bool = True,
        basic_attack: bool = False,
        damage_over_time: bool = False,
        skillshot: bool = False,
        area_damage: bool = False,
        ability_instance: str | None = None,
        cc_kind: str = "",
        sequence: int = 0,
        event_id: str = "packet",
    ) -> None:
        self.time = time
        self.source_key = source_key
        self.is_ability = is_ability
        self.basic_attack = basic_attack
        self.damage_over_time = damage_over_time
        self.skillshot = skillshot
        self.area_damage = area_damage
        self.ability_instance = ability_instance
        self.cc_kind = cc_kind
        self.sequence = sequence
        self.event_id = event_id


class _Attacker:
    def __init__(self, name: str = "Enemy") -> None:
        self.champion_data = {"name": name}


def _dummy_combatant(
    participant_id: str,
    team: str,
    health: float = 100.0,
) -> Combatant:
    """Minimal combatant for timeline-level (participant-timeline style)
    tests, mirroring the pinned suite's helper."""
    defenses = StartingDefenses(
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
        healing_received_multiplier=1.0,
    )
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=1,
        items=(),
        stats={"health": health},
        defenses=defenses,
    )


def _eligibility(start: float = 0.0, until: float = 1.5) -> de.SpellShieldEligibility:
    return de.SpellShieldEligibility(
        name="spell_shield",
        window=de.DefenseWindow(start=start, until=until),
        acceptance=de.SpellShieldAcceptance(),
        block_rule="all",
        source=None,
    )


class _CastBudget:
    """Mirror of the pinned walk consumption rule, for kernel-level tests.

    The walk keeps ``spell_shield_used`` + ``spell_shield_blocked_cast``:
    one spend per cast identity; every later packet of the SAME cast
    reuses the decision without spending again; a different cast after
    the budget is spent passes.  ``decide`` itself stays pure (it has no
    budget state), so these kernel tests drive the decision through this
    tiny tracker and the app-level rows prove the real walk does the same.
    """

    def __init__(self, uses: int = 1) -> None:
        self.remaining = uses
        self.blocked_cast: str | None = None

    def blocks(self, decision: de.SpellShieldDecision) -> tuple[bool, str]:
        if not decision.eligible:
            return False, decision.reason
        if (
            self.blocked_cast is not None
            and self.blocked_cast != decision.cast_identity
        ):
            return False, "budget_spent"
        if self.blocked_cast is None:
            if self.remaining <= 0:
                return False, "budget_spent"
            self.remaining -= 1
            self.blocked_cast = decision.cast_identity
        return True, ""


# ---------------------------------------------------------------------------
# R1 — Sivir E: eligible block + exactly one triggered heal
# ---------------------------------------------------------------------------


def test_r1_sivir_e_blocks_one_effect_and_triggers_exactly_one_heal():
    """Sivir E blocks the first hostile ability in its 1.5s window and
    schedules exactly one sourced heal at blocked_time + 0.25 (amount from
    the cached Heal row, source 'Spell Shield · Heal')."""
    combat = _calculate(
        {
            **_sivir(),
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                }
            ],
        }
    )

    blocked = _spell_shield_blocked(combat, "main")
    assert len(blocked) == 1
    (block_event,) = blocked
    assert block_event["damage"] == pytest.approx(0.0)
    assert block_event["skipped_reason"] == "spell_shield"
    assert block_event["spell_shield_source"] == "Spell Shield"

    heals = [
        event
        for event in combat["healing_events"]
        if event.get("source") == "Spell Shield · Heal"
    ]
    assert len(heals) == 1
    (heal,) = heals
    assert heal["attacker"] == "main"
    assert heal["time"] == pytest.approx(block_event["time"] + 0.25)
    assert heal["amount"] == pytest.approx(_sivir_expected_heal())
    assert heal["applied_amount"] > 0.0

    survival = survival_of(combat, "main")
    assert survival["spell_shield_used"] is True
    assert survival["spell_shield_until"] == pytest.approx(1.5)
    assert survival["spell_shield_source"] == "Spell Shield"
    assert survival["spell_shield_heal_triggered"] is True


# ---------------------------------------------------------------------------
# R2 — Annul items: block one ability; second ability passes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "item,source",
    [
        ("Banshee's Veil", "Banshee's Veil — Annul"),
        ("Edge of Night", "Edge of Night — Annul"),
        ("Verdant Barrier", "Verdant Barrier — Annul"),
    ],
)
def test_r2_annul_items_block_one_ability_then_second_passes(item, source):
    """Each Annul item is ready at fight start, blocks exactly one hostile
    ability (infinite window until consumed), and the next ability lands."""
    combat = _calculate(
        {
            **_ezreal_q_only(),
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [item],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                }
            ],
        }
    )

    blocked = _spell_shield_blocked(combat, "enemy:Ahri")
    assert len(blocked) == 1
    assert blocked[0]["spell_shield_source"] == source

    survival = survival_of(combat, "enemy:Ahri")
    assert survival["spell_shield_used"] is True
    assert survival["spell_shield_source"] == source
    assert survival["spell_shield_until"] is None  # infinite until consumed

    # The next ability after the blocked one lands with full damage.
    # (The public serializer drops is_ability; ability slots are Q/W/E/R.)
    later = [
        event
        for event in _events(combat, target="enemy:Ahri")
        if event.get("source") in {"Q", "W", "E", "R"}
        and event.get("skipped_reason") is None
        and event.get("time") > blocked[0]["time"]
    ]
    assert later, "expected a post-block ability to land"
    assert later[0]["damage"] > 0.0


# ---------------------------------------------------------------------------
# R3 — basic attacks do NOT consume; ability then consumes and blocks
# ---------------------------------------------------------------------------


def test_r3_basic_attack_first_does_not_consume_then_ability_blocks():
    """Timeline-level (pinned test style): an auto attack before the first
    ability passes untouched and does not spend the shield; the ability is
    then blocked."""
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = _dummy_combatant("target", "main", health=100.0)
    result = simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 0.5,
                    "damage": 20.0,
                    "damage_type": "physical",
                    "attacker": "source",
                    "target": "target",
                    "source_key": "auto_attacks",
                    "basic_attack": True,
                    "sequence": 0,
                    "_event_id": "auto",
                },
                {
                    "time": 1.0,
                    "damage": 40.0,
                    "damage_type": "magic",
                    "attacker": "source",
                    "target": "target",
                    "is_ability": True,
                    "sequence": 1,
                    "_event_id": "spell",
                },
            ]
        },
        {},
        {
            "target": [
                {
                    "time": 0.0,
                    "kind": "spell_shield",
                    "duration": 2.0,
                    "attacker": "target",
                    "source": "Annul",
                }
            ]
        },
        10.0,
    )
    assert result["target"]["damage_taken"] == 20.0  # auto only, spell blocked
    assert result["target"]["spell_shield_used"] is True
    assert result["target"]["spell_shield_source"] == "Annul"
    assert result["target"]["spell_shield_until"] == 2.0


def test_r3_auto_attack_packets_never_carry_spell_shield_annotations():
    """App-level: in a fight with autos, no basic-attack packet is ever
    spell-shield-skipped or annotated, and the shield is spent only by an
    ability packet."""
    combat = _calculate(
        {
            **_ezreal_q_only(),
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": ["Banshee's Veil"],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                }
            ],
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        }
    )
    autos = [
        event
        for event in _events(combat, target="enemy:Ahri")
        if event.get("source") == "auto_attacks"
    ]
    assert autos
    for event in autos:
        assert event.get("skipped_reason") != "spell_shield"
        assert "spell_shield_source" not in event
    assert all(
        event.get("skipped_reason") == "spell_shield"
        and event.get("spell_shield_source") == "Banshee's Veil — Annul"
        for event in _spell_shield_blocked(combat, "enemy:Ahri")
    )


# ---------------------------------------------------------------------------
# R4 — multi-part cast from ONE cast: all packets blocked, one use, one heal
# ---------------------------------------------------------------------------


def test_r4_multipart_cast_blocks_all_packets_with_one_use_and_one_heal():
    """Ahri's Q is two packets of one cast (same slot, same timestamp):
    both are blocked, the shield spends exactly once, and Sivir heals once."""
    combat = _calculate(
        {
            **_sivir(),
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [],
                    "cast_order": ["Q", "E", "W", "R"],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                }
            ],
        }
    )

    blocked = _spell_shield_blocked(combat, "main")
    assert len(blocked) == 2
    assert {event["source"] for event in blocked} == {"Q"}
    assert {event["time"] for event in blocked} == {0.0}
    assert all(event["spell_shield_source"] == "Spell Shield" for event in blocked)

    heals = [
        event
        for event in combat["healing_events"]
        if event.get("source") == "Spell Shield · Heal"
    ]
    assert len(heals) == 1
    assert heals[0]["time"] == pytest.approx(0.0 + 0.25)

    survival = survival_of(combat, "main")
    assert survival["spell_shield_used"] is True
    assert survival["spell_shield_heal_triggered"] is True
    # A later cast from the same attacker passes.
    later = _events(combat, target="main", source="E")
    assert later and later[0].get("skipped_reason") is None
    assert later[0]["damage"] > 0.0


# ---------------------------------------------------------------------------
# R5 — control-only cast (is_ability, no damage/amount, cc_kind)
# ---------------------------------------------------------------------------


def test_r5_control_only_cast_consumes_the_shield_and_is_blocked():
    """A control-only ability packet (no damage amount, cc_kind only)
    consumes the spell shield and is blocked; the CC is never applied."""
    source = _dummy_combatant("source", "enemy", health=100.0)
    target = _dummy_combatant("target", "main", health=100.0)
    result = simulate_survival(
        [source, target],
        {
            "target": [
                {
                    "time": 0.5,
                    "damage": 0.0,
                    "damage_type": "magic",
                    "attacker": "source",
                    "target": "target",
                    "is_ability": True,
                    "kind": "crowd_control",
                    "cc_kind": "stun",
                    "cc_duration": 2.5,
                    "skillshot": True,
                    "sequence": 0,
                    "_event_id": "stun-only",
                }
            ]
        },
        {},
        {
            "target": [
                {
                    "time": 0.0,
                    "kind": "spell_shield",
                    "duration": 1.5,
                    "attacker": "target",
                    "source": "Spell Shield",
                }
            ]
        },
        10.0,
    )
    assert result["target"]["spell_shield_used"] is True
    assert result["target"]["spell_shield_source"] == "Spell Shield"
    # The stun was blocked: no action downtime, no damage.
    assert result["target"]["damage_taken"] == 0.0
    assert result["target"]["action_downtime"] == 0.0


def test_r5_acceptance_blocks_control_only_packets():
    """Kernel acceptance: control-only ability packets are accepted by the
    spell-shield acceptance rule."""
    acceptance = de.SpellShieldAcceptance()
    action = _Action(
        time=0.5,
        source_key="E",
        is_ability=True,
        cc_kind="stun",
        skillshot=True,
    )
    accepted, reason = acceptance.accepts(action, de.classify_delivery(action))
    assert accepted is True
    assert reason == ""


# ---------------------------------------------------------------------------
# R6 — two different casts at one timestamp; collision grouping
# ---------------------------------------------------------------------------


def test_r6_two_casts_same_timestamp_total_order_decides():
    """App-level: Ahri E and Lux Q both arrive at t=0.0.  The total order
    gives Ahri E the first slot: it is blocked and spends the shield; Lux Q
    passes with damage."""
    combat = _calculate(
        {
            **_sivir(),
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [],
                    "cast_order": ["E", "Q", "W", "R"],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                },
                {
                    "champion": "Lux",
                    "level": 18,
                    "items": [],
                    "cast_order": ["Q", "E", "W", "R"],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                },
            ],
        }
    )

    # (Lux E at 0.25 is the same-slot 'E:1' collision case covered by the
    # dedicated test below; here only the t=0.0 decision matters.)
    blocked = [
        event for event in _spell_shield_blocked(combat, "main") if event["time"] == 0.0
    ]
    assert len(blocked) == 1
    assert blocked[0]["attacker"] == "enemy:Ahri"
    assert blocked[0]["source"] == "E"

    lux_q = next(
        event
        for event in _events(combat, target="main", source="Q")
        if event.get("attacker") == "enemy:Lux" and event.get("time") == 0.0
    )
    assert lux_q.get("skipped_reason") is None
    assert lux_q["damage"] > 0.0
    assert survival_of(combat, "main")["spell_shield_used"] is True


def test_r6_same_slot_collision_groups_as_one_cast_one_use():
    """App-level same-slot collision case, corrected by the kernel: the
    pipeline authors ability_instance as ``slot:ordinal`` without the
    attacker (Ahri E at t=0.0 and Lux E at t=0.25 both resolve to 'E:1'),
    but the kernel's grouping key is attacker-qualified
    (``spell_shield_group_key`` = (attacker, cast_identity)).  One shield
    use blocks ONE hostile ability instance, so the two E casts now SPLIT:
    Ahri E (t=0.0) is blocked (use spent, one heal) and Lux E (t=0.25)
    lands with full damage.  The public identity string stays 'E:1' — the
    attacker lives in the grouping key, not in the identity string."""
    combat = _calculate(
        {
            **_sivir(),
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [],
                    "cast_order": ["E", "Q", "W", "R"],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                },
                {
                    "champion": "Lux",
                    "level": 18,
                    "items": [],
                    "cast_order": ["Q", "E", "W", "R"],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                },
            ],
        }
    )

    blocked = _spell_shield_blocked(combat, "main")
    assert len(blocked) == 1
    (block_event,) = blocked
    assert block_event["attacker"] == "enemy:Ahri"
    assert block_event["source"] == "E"
    assert block_event["time"] == 0.0
    assert block_event["spell_shield_source"] == "Spell Shield"

    # The same-slot Lux E (same 'E:1' identity, different attacker) lands.
    lux_e = next(
        event
        for event in _events(combat, target="main", source="E")
        if event.get("attacker") == "enemy:Lux" and event.get("time") == 0.25
    )
    assert lux_e.get("skipped_reason") is None
    assert lux_e["damage"] > 0.0

    heals = [
        event
        for event in combat["healing_events"]
        if event.get("source") == "Spell Shield · Heal"
    ]
    assert len(heals) == 1
    assert heals[0]["time"] == pytest.approx(0.25)

    survival = survival_of(combat, "main")
    assert survival["spell_shield_used"] is True
    receipt = survival["spell_shield"]
    assert receipt["selected_cast_identity"] == "E:1"
    assert receipt["uses_before"] == 1
    assert receipt["uses_after"] == 0
    assert len(receipt["blocked_packets"]) == 1


def test_r6_kernel_two_casts_same_timestamp_distinct_instances():
    """Kernel-level: with distinct ability_instance values at one timestamp,
    the total order decides — the first cast blocks and spends, the second
    cast (different identity) passes."""
    eligibility = _eligibility()
    budget = _CastBudget(uses=1)
    attacker = _Attacker("Enemy")

    first = _Action(time=0.5, source_key="E", ability_instance="cast-a")
    second = _Action(time=0.5, source_key="Q", ability_instance="cast-b")

    decision_a = eligibility.decide(first, attacker)
    assert decision_a.eligible is True
    assert decision_a.cast_identity == "cast-a"
    assert decision_a.cast_identity_kind == "sourced"
    blocked, reason = budget.blocks(decision_a)
    assert blocked is True and reason == ""

    decision_b = eligibility.decide(second, attacker)
    assert decision_b.eligible is True
    assert decision_b.cast_identity == "cast-b"
    blocked, reason = budget.blocks(decision_b)
    assert blocked is False and reason == "budget_spent"


def test_r6_kernel_derived_fallback_groups_identically_to_current():
    """Kernel-level: without ability_instance, the derived identity
    ``source_key:time`` groups every packet of one cast — the first packet
    spends, later packets of the same cast reuse the decision without
    spending again (identical grouping to today's walk)."""
    eligibility = _eligibility()
    budget = _CastBudget(uses=1)
    attacker = _Attacker("Enemy")

    packet_one = _Action(time=0.5, source_key="Q", sequence=0)
    packet_two = _Action(time=0.5, source_key="Q", sequence=1)

    d1 = eligibility.decide(packet_one, attacker)
    assert d1.cast_identity == "Q:0.5"
    assert d1.cast_identity_kind == "derived"
    blocked, reason = budget.blocks(d1)
    assert blocked is True and reason == ""
    assert budget.remaining == 0

    d2 = eligibility.decide(packet_two, attacker)
    assert d2.cast_identity == "Q:0.5"
    assert d2.cast_identity_kind == "derived"
    # Same cast: reuses the decision, does NOT spend again.
    blocked, reason = budget.blocks(d2)
    assert blocked is True and reason == ""
    assert budget.remaining == 0


# ---------------------------------------------------------------------------
# R7 — window boundaries (start inclusive, end exclusive)
# ---------------------------------------------------------------------------


def test_r7_window_boundaries_start_inclusive_end_exclusive():
    """An event before start is outside, at start is inside, just before
    end is inside, at end is outside."""
    eligibility = _eligibility(start=1.0, until=2.5)
    attacker = _Attacker()

    before = eligibility.decide(_Action(time=0.9999999), attacker)
    assert before.eligible is False
    assert before.reason == "outside_window"

    at_start = eligibility.decide(_Action(time=1.0), attacker)
    assert at_start.eligible is True
    assert at_start.reason == ""

    just_before_end = eligibility.decide(_Action(time=2.4999999), attacker)
    assert just_before_end.eligible is True
    assert just_before_end.reason == ""

    at_end = eligibility.decide(_Action(time=2.5), attacker)
    assert at_end.eligible is False
    assert at_end.reason == "outside_window"


def test_r7_acceptance_reasons_not_an_ability_basic_attack_unknown():
    """SpellShieldAcceptance fails closed with the named reasons:
    'basic_attack_not_blocked' for basic attacks, 'not_an_ability' for
    non-ability declared packets, 'unknown_delivery' for unclassifiable
    packets."""
    acceptance = de.SpellShieldAcceptance()

    basic = _Action(is_ability=False, basic_attack=True, source_key="auto_attacks")
    accepted, reason = acceptance.accepts(basic, de.classify_delivery(basic))
    assert accepted is False
    assert reason == "basic_attack_not_blocked"

    dot_tick = _Action(is_ability=False, damage_over_time=True, source_key="burn")
    accepted, reason = acceptance.accepts(dot_tick, de.classify_delivery(dot_tick))
    assert accepted is False
    assert reason == "not_an_ability"

    unknown = _Action(is_ability=False, source_key="item_proc")
    accepted, reason = acceptance.accepts(unknown, de.classify_delivery(unknown))
    assert accepted is False
    assert reason == "unknown_delivery"

    # The decide() path surfaces the same reasons.
    eligibility = _eligibility()
    attacker = _Attacker()
    assert eligibility.decide(basic, attacker).reason == "basic_attack_not_blocked"
    assert eligibility.decide(unknown, attacker).reason == "unknown_delivery"


# ---------------------------------------------------------------------------
# R8 — walk order: stasis -> projectile defense -> spell shield
# ---------------------------------------------------------------------------


def test_r8_stasis_blocked_packets_do_not_spend_the_shield():
    """App-level: packets blocked by target stasis ('target_state_blocked')
    never touch the spell shield; the first post-stasis ability is blocked
    by the shield and spends it."""
    combat = _calculate(
        {
            **_ezreal_q_only(),
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": ["Zhonya's Hourglass", "Banshee's Veil"],
                    "item_options": {
                        "Zhonya's Hourglass": {"stasis_active_seconds": 2.5}
                    },
                    "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
                }
            ],
        }
    )

    q_events = sorted(
        _events(combat, target="enemy:Ahri", source="Q"),
        key=lambda event: event["time"],
    )
    assert [event["time"] for event in q_events] == [0.0, 3.25, 6.5]

    stasis_blocked, shield_blocked, passed = q_events
    assert stasis_blocked["skipped_reason"] == "target_state_blocked"
    assert "spell_shield_source" not in stasis_blocked

    assert shield_blocked["skipped_reason"] == "spell_shield"
    assert shield_blocked["spell_shield_source"] == "Banshee's Veil — Annul"

    assert passed.get("skipped_reason") is None
    assert passed["damage"] > 0.0
    assert survival_of(combat, "enemy:Ahri")["spell_shield_used"] is True


def test_r8_yasuo_destroyed_packets_do_not_spend_the_shield():
    """App-level: projectiles destroyed by Yasuo W ('yasuo_wind_wall') are
    skipped before the spell shield gate, so the shield survives them and
    blocks the first non-destroyed ability."""
    combat = _calculate(
        {
            **_ezreal_q_only(),
            "enemies": [
                {
                    "champion": "Yasuo",
                    "level": 18,
                    "items": ["Banshee's Veil"],
                    "ability_ranks": {"Q": 0, "W": 5, "E": 0, "R": 0},
                    "champion_options": {
                        "w_active": True,
                        "w_active_seconds": 4.0,
                        "w_blocked_skillshots": ["Q"],
                    },
                }
            ],
        }
    )

    q_events = sorted(
        _events(combat, target="enemy:Yasuo", source="Q"),
        key=lambda event: event["time"],
    )
    destroyed = [
        event for event in q_events if event.get("skipped_reason") == "yasuo_wind_wall"
    ]
    assert len(destroyed) == 2
    for event in destroyed:
        assert "spell_shield_source" not in event

    shield_blocked = next(
        event for event in q_events if event.get("skipped_reason") == "spell_shield"
    )
    assert shield_blocked["time"] == 6.5
    assert shield_blocked["spell_shield_source"] == "Banshee's Veil — Annul"
    assert survival_of(combat, "enemy:Yasuo")["spell_shield_used"] is True


def test_r8_braum_full_blocked_packet_does_not_spend_the_shield():
    """App-level (NEW-CONTRACT): with Braum E active AND a spell shield, the
    walk order is stasis -> projectile defense -> spell shield.  The first
    projectile is FULLY blocked by Braum E (first-hit) and must NOT spend
    the shield; the second projectile is reduced by Braum E AND fully
    blocked by the spell shield (one use spent).

    Today's walk annotates the full block but still falls through to the
    spell shield gate, so this assertion fails until the kernel lands — the
    intended signal."""
    combat = _calculate(
        {
            **_ezreal_q_only(),
            "enemies": [
                {
                    "champion": "Braum",
                    "level": 18,
                    "items": ["Banshee's Veil"],
                    "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                    "champion_options": {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    },
                }
            ],
        }
    )

    q_events = sorted(
        _events(combat, target="enemy:Braum", source="Q"),
        key=lambda event: event["time"],
    )
    first, second, third = q_events

    # First projectile: fully blocked by Braum E only; shield untouched.
    assert first["projectile_defense"]["mode"] == "full_block"
    assert first["skipped_reason"] == "braum_unbreakable"
    assert "spell_shield_source" not in first

    # Second projectile: Braum E reduces it AND the shield fully blocks it.
    assert second["projectile_defense"]["mode"] == "reduced"
    assert second["skipped_reason"] == "spell_shield"
    assert second["spell_shield_source"] == "Banshee's Veil — Annul"
    assert second["damage"] == pytest.approx(0.0)

    # Third projectile: both defenses spent, full damage.
    assert third.get("skipped_reason") is None
    assert third["damage"] > 0.0
    assert survival_of(combat, "enemy:Braum")["spell_shield_used"] is True


# ---------------------------------------------------------------------------
# R9 — unknown/missing cast identity fails closed, no consumption
# ---------------------------------------------------------------------------


def test_r9_unknown_cast_identity_fails_closed_no_consumption():
    """An ability packet with no ability_instance, no source_key, and no
    finite time resolves to ('', 'unknown'); decide() denies it with
    'unknown_cast_identity' and the budget is never spent."""
    eligibility = _eligibility()
    attacker = _Attacker()
    action = _Action(time=None, source_key=None, ability_instance=None)

    identity, kind = de.resolve_cast_identity(action)
    assert identity == ""
    assert kind == "unknown"

    decision = eligibility.decide(action, attacker)
    assert decision.eligible is False
    assert decision.reason == "unknown_cast_identity"
    assert decision.cast_identity == ""
    assert decision.cast_identity_kind == "unknown"

    budget = _CastBudget(uses=1)
    blocked, reason = budget.blocks(decision)
    assert blocked is False
    assert budget.remaining == 1  # never spent


# ---------------------------------------------------------------------------
# R10 — receipt-versus-result parity
# ---------------------------------------------------------------------------


def test_r10_survival_row_matches_blocked_events():
    """App-level (CURRENT surface): every event blocked with
    skipped_reason='spell_shield' carries the survival row's shield source,
    and the row records exactly one use."""
    combat = _calculate(
        {
            **_sivir(),
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                }
            ],
        }
    )
    survival = survival_of(combat, "main")
    blocked = _spell_shield_blocked(combat, "main")
    assert blocked
    assert all(
        event["spell_shield_source"] == survival["spell_shield_source"]
        for event in blocked
    )
    assert survival["spell_shield_used"] is True


def test_r10_spell_shield_receipt_parity():
    """App-level (NEW-CONTRACT): the survival row's spell_shield receipt —
    source, window, selected cast identity, eligibility decision, blocked
    packets, use before/after, triggered heal — matches the events actually
    blocked (skipped_reason='spell_shield')."""
    combat = _calculate(
        {
            **_sivir(),
            "enemies": [
                {
                    "champion": "Ahri",
                    "level": 18,
                    "items": [],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                }
            ],
        }
    )
    survival = survival_of(combat, "main")
    receipt = survival["spell_shield"]
    blocked = _spell_shield_blocked(combat, "main")

    assert receipt["source"] == "Spell Shield"
    assert receipt["window"]["start"] == pytest.approx(0.0)
    assert receipt["window"]["until"] == pytest.approx(1.5)
    assert receipt["uses_before"] == 1
    assert receipt["uses_after"] == 0
    # Every blocked packet is receipted (event_key uses the stable
    # source_key:time:sequence identity) and matches the events actually
    # blocked by (time, source) — the public serializer drops source_key,
    # so the parity check keys on the observable fields.
    assert receipt["blocked_packets"]
    assert all(entry.get("event_key") for entry in receipt["blocked_packets"])
    assert {
        (entry["time"], entry["source"]) for entry in receipt["blocked_packets"]
    } == {(event["time"], event["source"]) for event in blocked}
    assert receipt["selected_cast_identity"]
    assert receipt["triggered_heal"]["time"] == pytest.approx(blocked[0]["time"] + 0.25)
    assert receipt["triggered_heal"]["source"] == "Spell Shield · Heal"


# ---------------------------------------------------------------------------
# R11 — score-path fail-closed receipts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "item",
    ["Banshee's Veil", "Edge of Night", "Verdant Barrier"],
)
def test_r11_annul_items_fail_closed_in_compiled_score_walk(item):
    """P3-3U: the Annul spell-shield eligibility rides the stamped
    is_ability/basic_attack delivery flags, so every Annul item leaves
    the compiled blocklist — the capability scan is clean.  (A
    representable item stays untouched.)"""
    assert uncompilable_item_receipt([{"name": item}]) is None
    # A representable item is untouched.
    assert uncompilable_item_receipt([{"name": "Infinity Edge"}]) is None


def test_r11_sivir_on_block_heal_template_fails_closed():
    """Sivir's spell_shield template carries on_block_heal_amount, which the
    compiled kernel cannot stage: unrepresentable_template_receipt names
    'support_spell_shield_on_block_heal'.  A plain timed spell shield is
    representable."""
    template = {
        "kind": "spell_shield",
        "duration": 1.5,
        "on_block_heal_amount": _sivir_expected_heal(),
        "on_block_heal_delay": 0.25,
        "on_block_heal_source": "Spell Shield · Heal",
    }
    assert (
        unrepresentable_template_receipt(template)
        == "support_spell_shield_on_block_heal"
    )
    assert (
        unrepresentable_template_receipt({"kind": "spell_shield", "duration": 1.5})
        is None
    )


# ---------------------------------------------------------------------------
# R12 — kernel contract: receipts, budget modes, reasons, identities
# ---------------------------------------------------------------------------


def test_r12_spell_shield_eligibility_receipt_shape():
    eligibility = _eligibility()
    receipt = eligibility.public_receipt()
    assert set(receipt) == {"name", "window", "acceptance", "block_rule", "source"}
    assert receipt["name"] == "spell_shield"
    assert receipt["block_rule"] == "all"
    assert set(receipt["window"]) == {"start", "until", "source_atoms"}
    assert set(receipt["acceptance"]) == {
        "requires_ability",
        "blocks_basic_attacks",
        "blocks_control_only",
        "accepts_unknown",
    }
    assert receipt["acceptance"]["requires_ability"] is True
    assert receipt["acceptance"]["blocks_basic_attacks"] is False
    assert receipt["acceptance"]["blocks_control_only"] is True
    assert receipt["acceptance"]["accepts_unknown"] is False


def test_r12_spell_shield_composition_receipt_shape():
    composition = de.SpellShieldComposition(
        full_block=de.FullBlockRule(mode="all", blocks_true_damage=True),
        uses=de.UseBudget(action_mode="spell_shield", uses=1, consume="per_cast"),
        triggered_heal=de.TriggeredHealRule(
            amount=81.6,
            delay=0.25,
            source="Spell Shield · Heal",
            source_atoms=({"source": "Sivir.E[2].effects[0]"},),
        ),
    )
    receipt = composition.public_receipt()
    assert set(receipt) == {"full_block", "uses", "triggered_heal"}
    assert receipt["full_block"]["mode"] == "all"
    assert receipt["full_block"]["blocks_true_damage"] is True
    assert receipt["uses"]["action_mode"] == "spell_shield"
    assert receipt["uses"]["uses"] == 1
    assert receipt["uses"]["consume"] == "per_cast"
    assert receipt["triggered_heal"]["amount"] == pytest.approx(81.6)
    assert receipt["triggered_heal"]["delay"] == pytest.approx(0.25)
    assert receipt["triggered_heal"]["source"] == "Spell Shield · Heal"
    assert receipt["triggered_heal"]["source_atoms"] == [
        {"source": "Sivir.E[2].effects[0]"}
    ]


def test_r12_use_budget_consume_modes():
    """'per_cast' is the new spell-shield consume mode; the existing
    'first_eligible'/'each_eligible' modes are unchanged."""
    for consume in ("per_cast", "first_eligible", "each_eligible"):
        budget = de.UseBudget(action_mode="spell_shield", uses=1, consume=consume)
        assert budget.public_receipt()["consume"] == consume
    # The spell-shield declaration shape from the contract.
    budget = de.UseBudget(action_mode="spell_shield", uses=1, consume="per_cast")
    assert budget.initial_remaining() == 1
    with pytest.raises(ValueError):
        de.UseBudget(action_mode="spell_shield", uses=0, consume="per_cast")
    with pytest.raises(ValueError):
        de.UseBudget(action_mode="spell_shield", uses=1, consume="not_a_mode")


def test_r12_decision_reasons_enumeration():
    """SpellShieldDecision.reason carries exactly the named set: '' plus the
    five fail-closed reasons."""
    eligibility = _eligibility(start=0.0, until=1.5)
    attacker = _Attacker()

    reasons = {}

    outside = eligibility.decide(_Action(time=2.0), attacker)
    reasons[outside.reason] = outside

    not_ability = eligibility.decide(
        _Action(is_ability=False, damage_over_time=True), attacker
    )
    reasons[not_ability.reason] = not_ability

    basic = eligibility.decide(_Action(is_ability=False, basic_attack=True), attacker)
    reasons[basic.reason] = basic

    unknown_delivery = eligibility.decide(
        _Action(is_ability=False, source_key="item_proc"), attacker
    )
    reasons[unknown_delivery.reason] = unknown_delivery

    unknown_identity = eligibility.decide(
        _Action(time=None, source_key=None, ability_instance=None), attacker
    )
    reasons[unknown_identity.reason] = unknown_identity

    eligible = eligibility.decide(_Action(time=0.5), attacker)
    reasons[eligible.reason] = eligible

    assert set(reasons) == {
        "",
        "outside_window",
        "not_an_ability",
        "basic_attack_not_blocked",
        "unknown_delivery",
        "unknown_cast_identity",
    }
    assert reasons[""].eligible is True
    assert all(not reasons[reason].eligible for reason in reasons if reason)

    # The public receipt carries the decision fields.
    decision_receipt = eligible.public_receipt()
    assert set(decision_receipt) == {
        "eligible",
        "reason",
        "delivery",
        "cast_identity",
        "cast_identity_kind",
        "event_key",
    }


def test_r12_resolve_cast_identity_three_kinds():
    """resolve_cast_identity: sourced (ability_instance), derived
    (source_key:time fallback — including when source_key is absent but the
    time is finite), unknown (neither nor a finite time)."""
    sourced = _Action(time=0.5, source_key="Q", ability_instance="Q:3")
    assert de.resolve_cast_identity(sourced) == ("Q:3", "sourced")

    derived = _Action(time=0.5, source_key="Q", ability_instance=None)
    assert de.resolve_cast_identity(derived) == ("Q:0.5", "derived")

    # Pinned: derived even without a source_key when the time is finite.
    derived_no_key = _Action(time=0.5, source_key=None, ability_instance=None)
    identity, kind = de.resolve_cast_identity(derived_no_key)
    assert kind == "derived"
    assert identity == ":0.5"

    unknown = _Action(time=None, source_key=None, ability_instance=None)
    assert de.resolve_cast_identity(unknown) == ("", "unknown")


def test_r12_stable_event_key_reused_for_blocked_bookkeeping():
    """Blocked-packet bookkeeping reuses stable_event_key
    (source_key:time:sequence)."""
    action = _Action(time=0.5, source_key="Q", sequence=3)
    assert de.stable_event_key(action) == "Q:0.5:3"
    decision = _eligibility().decide(action, _Attacker())
    assert decision.event_key == de.stable_event_key(action)


# ---------------------------------------------------------------------------
# R13 — the sourced rearm clock, end to end on Banshee's Veil
# ---------------------------------------------------------------------------
#
# Verdant Barrier's 60s clock is pinned packet-by-packet in
# ``test_verdant_barrier_compiled_parity.py``; this row is the OTHER sourced
# cooldown (40s, shared with Edge of Night) plus the two cases that file
# cannot host: a cooldown that outlasts the whole fight window, and a shield
# whose cooldown is not sourced at all.

BANSHEES = "Banshee's Veil"
#: Pinned literals, cross-checked against the typed accessors in the first
#: test below — the pin is what would catch a silent cache drift, and the
#: cross-check is what keeps the pin honest.
BANSHEES_COOLDOWN = 40.0
BANSHEES_ATOM_HASH = "c020562aebacbe01"
#: ``pipeline._REQUEST_BOUNDS["fight_duration"]`` upper bound.  Every Annul
#: cooldown is longer, so no API request can reach a rearm; the walks below
#: that do reach one run the kernel directly.
REQUEST_MAX_FIGHT_SECONDS = 30.0


def _annul_stats() -> dict:
    return {"health": 3000.0, "is_melee": False, "bonus_attack_damage": 0.0}


def _annul_holder(champion: str = "Ahri") -> Combatant:
    """A Banshee's Veil holder for the packet-level survival walk."""
    stats = _annul_stats()
    return Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": champion},
        level=18,
        items=(get_item_by_name(BANSHEES),),
        stats=stats,
        defenses=resolve_starting_defenses(champion, 18, stats, [{"name": BANSHEES}]),
    )


def _unsourced_shield_holder(champion: str = "Ahri") -> Combatant:
    """A holder whose shield is ready but whose items name no Annul item.

    This is ``resolve_spell_shield``'s fail-closed branch: with no item to
    read a cooldown from it builds the default clock, which never rearms.
    """
    return Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": champion},
        level=18,
        items=(),
        stats=_annul_stats(),
        defenses=StartingDefenses(
            spell_shield_ready=True,
            spell_shield_source="Annul",
            healing_received_multiplier=1.0,
        ),
    )


def _annul_attacker() -> Combatant:
    return Combatant(
        participant_id="source",
        team="main",
        champion_data={"name": "source"},
        level=18,
        items=(),
        stats={"health": 5000.0},
        defenses=StartingDefenses(healing_received_multiplier=1.0),
    )


def _annul_packet(
    time: float,
    sequence: int,
    *,
    damage: float,
    damage_type: str = "magic",
    source_key: str = "Q",
    **extra,
) -> dict:
    packet = {
        "time": time,
        "damage": damage,
        "damage_type": damage_type,
        "attacker": "source",
        "target": "target",
        "source_key": source_key,
        "sequence": sequence,
        "_event_id": f"{source_key}:{sequence}:{time}",
    }
    packet.update(extra)
    return packet


def _ability_at(time: float, sequence: int, damage: float = 100.0) -> dict:
    return _annul_packet(time, sequence, damage=damage, is_ability=True)


def _auto_at(time: float, sequence: int, damage: float = 20.0) -> dict:
    return _annul_packet(
        time,
        sequence,
        damage=damage,
        damage_type="physical",
        source_key="auto_attacks",
        basic_attack=True,
    )


def _annul_walk(holder: Combatant, events: list[dict], duration: float) -> dict:
    """One survival walk with *holder* as the packet target."""
    return simulate_survival(
        [_annul_attacker(), holder], {"target": events}, {}, {}, duration
    )["target"]


def _late_decision(row: dict, cast_identity: str) -> dict:
    """The one eligibility decision recorded for *cast_identity*.

    The decisions receipt records the ELIGIBILITY reason, never the block
    reason, so "was this cast declined on the cooldown or never considered
    at all?" is only answerable through it.
    """
    matches = [
        entry
        for entry in row["spell_shield"]["decisions"]
        if entry["cast_identity"] == cast_identity
    ]
    assert len(matches) == 1
    return matches[0]


def test_r13_banshees_cooldown_and_restart_clause_are_sourced():
    """Every number the clock reads comes from the cache, not this file.

    The pinned 40.0s and the atom hash are cross-checked against the typed
    accessors, and the resolved contract carries the same atom — so a cache
    drift fails here rather than silently moving a rearm instant.
    """
    assert spell_shield_cooldown_seconds(BANSHEES) == pytest.approx(BANSHEES_COOLDOWN)
    atom = annul_spell_shield_cooldown_atom(BANSHEES)
    assert atom["hash"] == BANSHEES_ATOM_HASH
    assert atom["values"] == [BANSHEES_COOLDOWN]
    assert annul_spell_shield_timer_restarts(BANSHEES) is True

    clock = resolve_spell_shield(_annul_holder()).rearm
    assert clock.sourced() is True
    assert clock.cooldown == pytest.approx(BANSHEES_COOLDOWN)
    assert clock.restarts_on_champion_damage is True
    assert clock.source_atom["hash"] == BANSHEES_ATOM_HASH


def test_r13_a_rearm_inside_the_window_is_receipted_with_its_arithmetic():
    """A rearm that lands inside the fight window, arithmetic and all.

    60s walk.  The ability at t=1.0 is blocked and spends the use, so
    consumed_at = 1.0.  Nothing damages the holder afterwards, so the timer
    is never restarted and runs from 1.0: ready_at = 1.0 + 40.0 = 41.0.
    The second ability at t=41.0 finds the shield back and is blocked too,
    so the holder takes nothing at all across the whole walk.
    """
    row = _annul_walk(
        _annul_holder(), [_ability_at(1.0, 0), _ability_at(41.0, 1)], 60.0
    )
    assert row["damage_taken"] == pytest.approx(0.0)
    assert len(row["spell_shield"]["blocked_packets"]) == 2
    rearms = row["spell_shield"]["rearms"]
    assert len(rearms) == 1
    assert rearms[0]["time"] == pytest.approx(41.0)
    assert rearms[0]["consumed_at"] == pytest.approx(1.0)
    assert rearms[0]["cooldown"] == pytest.approx(BANSHEES_COOLDOWN)
    assert rearms[0]["timer_started_at"] == pytest.approx(1.0)
    assert rearms[0]["ready_at"] == pytest.approx(41.0)
    assert rearms[0]["restarts_on_champion_damage"] is True
    assert rearms[0]["spent_cast"] == "Q:1.0"
    # The rearm re-spends immediately on the cast that observed it, so the
    # published budget still reads one use spent, not two available.
    assert row["spell_shield_used"] is True
    assert row["spell_shield"]["uses_after"] == 0


def test_r13_the_rearm_instant_is_an_endpoint_start_inclusive():
    """41.0 exactly rearms; one millisecond earlier does not.

    Same 60s walk and the same consumed_at = 1.0, so ready_at = 41.0 in
    both runs — only the second ability's instant moves.  Start-inclusive
    is the walk's convention everywhere (``DefenseWindow.active_at``), and
    pinning both sides is what keeps a future comparison from drifting to
    strictly-greater or to a rounded second.
    """
    on_the_instant = _annul_walk(
        _annul_holder(), [_ability_at(1.0, 0), _ability_at(41.0, 1)], 60.0
    )
    assert on_the_instant["damage_taken"] == pytest.approx(0.0)
    assert len(on_the_instant["spell_shield"]["rearms"]) == 1

    one_ms_early = _annul_walk(
        _annul_holder(), [_ability_at(1.0, 0), _ability_at(40.999, 1)], 60.0
    )
    assert one_ms_early["damage_taken"] == pytest.approx(100.0)
    assert one_ms_early["spell_shield"]["rearms"] == []
    assert len(one_ms_early["spell_shield"]["blocked_packets"]) == 1
    # Declined on the cooldown, not on eligibility.
    assert _late_decision(one_ms_early, "Q:40.999")["eligible"] is True


def test_r13_a_cooldown_that_outlasts_the_fight_never_rearms():
    """The production case: 40s of cooldown, 30s of fight.

    ``pipeline`` bounds a requested fight_duration to 30.0s and the
    shortest Annul cooldown is 40.0s, so ready_at = 1.0 + 40.0 = 41.0 sits
    past the end of every window a request can ask for.  The second ability
    at t=29.0 lands for its full 100, exactly as it did before the rearm
    clock existed — which is why no API response moved.
    """
    assert BANSHEES_COOLDOWN > REQUEST_MAX_FIGHT_SECONDS
    row = _annul_walk(
        _annul_holder(),
        [_ability_at(1.0, 0), _ability_at(29.0, 1)],
        REQUEST_MAX_FIGHT_SECONDS,
    )
    assert row["damage_taken"] == pytest.approx(100.0)
    assert len(row["spell_shield"]["blocked_packets"]) == 1
    assert row["spell_shield"]["rearms"] == []
    assert row["spell_shield"]["rearm"]["sourced"] is True
    assert row["spell_shield_used"] is True
    assert _late_decision(row, "Q:29.0")["eligible"] is True
    # The kernel agrees with the walk about why: the rearm is outside the
    # window rather than merely unreached by a packet.
    clock = resolve_spell_shield(_annul_holder()).rearm
    assert clock.ready_at(1.0) == pytest.approx(41.0)
    assert clock.rearms_within(REQUEST_MAX_FIGHT_SECONDS, 1.0) is False


def test_r13_every_champion_hit_restarts_the_timer_including_one_that_got_through():
    """ "Timer restarts upon taking damage from champions" means EVERY hit.

    90s walk, four packets, and the clock is re-anchored twice:

    * t=1.0 ability blocked; consumed_at = 1.0, ready_at = 41.0;
    * t=9.0 basic attack lands 20 (a basic attack never spends the shield),
      restarting the timer at 9.0 -> ready_at = 49.0;
    * t=41.0 ability: 41.0 < 49.0, so it is NOT blocked and lands 100 —
      and that landed damage restarts the timer again at 41.0, so
      ready_at becomes 41.0 + 40.0 = 81.0;
    * t=81.0 ability: 81.0 >= 81.0, so the shield is back and blocks it.

    Surviving damage is the two hits that got through: 20.0 + 100.0 = 120.0.
    The hit that got through is the load-bearing one — an implementation
    that only re-anchored on basic attacks would have rearmed at 49.0 and
    blocked the t=41 ability, taking 20.0 instead.
    """
    row = _annul_walk(
        _annul_holder(),
        [
            _ability_at(1.0, 0),
            _auto_at(9.0, 1),
            _ability_at(41.0, 2),
            _ability_at(81.0, 3),
        ],
        90.0,
    )
    assert row["damage_taken"] == pytest.approx(120.0)
    blocked = row["spell_shield"]["blocked_packets"]
    assert [entry["time"] for entry in blocked] == [1.0, 81.0]
    rearms = row["spell_shield"]["rearms"]
    assert len(rearms) == 1
    assert rearms[0]["time"] == pytest.approx(81.0)
    assert rearms[0]["consumed_at"] == pytest.approx(1.0)
    assert rearms[0]["timer_started_at"] == pytest.approx(41.0)
    assert rearms[0]["ready_at"] == pytest.approx(81.0)
    # The t=41 ability was eligible and declined only by the restarted clock.
    assert _late_decision(row, "Q:41.0")["eligible"] is True


def test_r13_an_unsourced_shield_never_rearms():
    """Fail-closed: no sourced cooldown, no rearm, at any elapsed time.

    The holder's shield is ready with no Annul item to read a cooldown
    from, so ``resolve_spell_shield`` builds the default clock: cooldown
    0.0, ``sourced`` False, ready_at +inf.  In a 100s walk — longer than
    every Annul cooldown put together — the second ability at t=99.0 still
    lands for 100.  A clock that treated the unsourced 0.0 as a real
    cooldown would have rearmed the shield at t=1.0 and blocked it.
    """
    holder = _unsourced_shield_holder()
    clock = resolve_spell_shield(holder).rearm
    assert clock.sourced() is False
    assert clock.cooldown == pytest.approx(0.0)
    assert clock.ready_at(1.0) == float("inf")
    assert clock.rearms_within(100.0, 1.0) is False

    row = _annul_walk(holder, [_ability_at(1.0, 0), _ability_at(99.0, 1)], 100.0)
    assert row["damage_taken"] == pytest.approx(100.0)
    assert len(row["spell_shield"]["blocked_packets"]) == 1
    assert row["spell_shield"]["rearms"] == []
    assert row["spell_shield"]["rearm"]["sourced"] is False
    assert row["spell_shield"]["rearm"]["source_atom"] is None
    assert row["spell_shield_used"] is True
    assert _late_decision(row, "Q:99.0")["eligible"] is True
