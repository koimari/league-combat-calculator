"""P2 Slice 3 crowd-control immunity acceptance matrix — Morgana E Black Shield.

This file is the RLM-2 acceptance-matrix suite for the planned orthogonal
typed control-eligibility contract (``src/calculator/crowd_control_eligibility.py``,
NEW leaf) plus the minimal Morgana E wiring that replaces the bespoke
handling in ``survival/transitions.py`` (``_apply_crowd_control`` /
``_crowd_control_immunity_active`` / the immunity branch of ``_apply_shield``).
It follows the styles of ``test_delivery_interaction_eligibility.py``
(P2 Slice 1) and ``test_spell_shield_eligibility.py`` (P2 Slice 2): kernel
unit tests with minimal ``_CcAction`` actors, timeline tests through
``participant_timeline._simulate_survival`` (the same style the spell-shield
matrix uses), and ``src.app`` -> ``POST /api/calculate`` consumer tests for
end-to-end cases.

The walk reuses ``delivery_eligibility.DefenseWindow`` +
``state_lifecycle.SourceReceipt`` (Slices 1/2 kernel) and the
``shield_ledger`` pools; the shield ledger entry is the ONLY immunity holder.

CONTRACT API THIS MATRIX COMMITS THE OWNER TO (six separation concerns):

1. CONTROL CLASSIFICATION
   - ``CONTROL_BLOCKING_KINDS``: the sourced hard set, mirroring
     ``ability_spec.ACTION_BLOCKING_CC_KINDS`` (airborne, charm, fear,
     immobilize, knockback, knockup, polymorph, root, sleep, stun,
     suppression, taunt).
   - ``CONTROL_SOFT_KINDS``: declared non-blocking kinds (blind, disarm,
     ground, silence, slow) — known, never eligible.  Silence is authored
     by champion modules but excluded from ACTION_BLOCKING_CC_KINDS, so the
     contract classifies it as known-and-non-blocking, never unknown.
   - ``classify_control(action) -> ControlProfile(kind, blocking, unknown,
     unknown_markers)``; ``kind == ""`` for a packet with no control
     markers (a plain damage packet — R14).
   - ``required_control_class(action) -> str``: strict API; raises
     ``UnknownControlError`` (named reason "unknown_control") for kinds
     outside the known set.
2. IMMUNITY ELIGIBILITY
   - ``CrowdControlEligibility(name="crowd_control_immunity", window,
     holder_source, source)`` with ``decide(action, attacker=None, *,
     holder=None) -> CrowdControlDecision``.  Named denial reasons:
     "outside_window" / "control_not_blocking" / "unknown_control" /
     "shield_not_held" (no holder entry at decision time) /
     "missing_same_hit_rule" (ordering unverified — fail closed).
3. SHIELD OWNERSHIP
   - ``immunity_holder(pools, holder_source, event_time=0.0)``: the exact
     ``shield_ledger.TimedShield`` entry whose ``source`` equals
     ``holder_source``, ``amount > 1e-9``, and ``expires_at > event_time``;
     None otherwise.  That exact entry is the only immunity holder — a
     general shield granted by another source never holds it (R8, R18).
4. SHIELD LIFETIME
   - ``DefenseWindow`` (start inclusive, end exclusive) from
     ``delivery_eligibility``; ``active_until(entry) -> entry.expires_at``.
5. PACKET ORDERING
   - ``delivery_eligibility.stable_event_key`` ("source_key:time:sequence")
     is the decision identity; same-time packets resolve in the walk's
     total order (``action_key``) — deterministic decisions (R9).
6. RECEIPT WRITING
   - ``CrowdControlDecision.public_receipt()``: {eligible, reason, control,
     shield_source, shield_amount_before, active_until, event_key}.
   - The per-event ``crowd_control_blocked`` receipt EXTENDS today's
     {source, until} with ``decision`` and ``shield_amount_after``.
   - The survival-row receipt ``crowd_control_immunity`` (recipient rows
     only): {recipient, shield_source, source_atoms, window, active_until,
     reason_immunity_ended ("expired" | "drained" | "fight_end" | None),
     eligibility, blocked, decisions} (R12).
7. SAME-HIT ORDERING (RLM-2 A dependency)
   - ``same_hit_ordering() -> (rule_text, SourceReceipt)``; raises
     ``MissingSameHitRuleError`` with ``reason == "missing_same_hit_rule"``
     while RLM-2 A has not verified the in-game ordering (R19).
   - ``compiled_support_receipt(template) -> str | None``: contract-owned
     mirror of ``survival.compile.unrepresentable_template_receipt`` for
     the score path (R13).

Row status conventions (same as the P2 Slice 1/2 matrices):
- "CURRENT" rows assert behavior the tree already satisfies today.  The
  behavior assertions pass against today's walk; the contract-API
  assertions in the same row (marked ``_require_contract()``) fail until
  the kernel lands — the intended signal that the row must be recomposed
  onto the contract without changing the outcome.
- "NEW-CONTRACT" rows assert the kernel API the owner commits to.  They
  fail today (PENDING KERNEL marker) and are reported as pending.
- Rows R6a / R6a-alt / R19 depend on the same-hit ordering evidence
  (RLM-2 A audit).  Exactly ONE of R6a / R6a-alt is pinned once the
  evidence lands; while unverified, the contract must fail closed with the
  named "missing_same_hit_rule" reason instead of guessing.

Matrix rows (row id | dimension | level | status | depends on RLM-2 A):

R1  | Shield ownership / target selection: selected ally only        | app        | CURRENT (behavior) / NEW-CONTRACT (receipt) | no
R2  | Damage-attached charm while the shield remains                 | app        | CURRENT | no
R3  | Control-only packet while the shield remains (same gate)       | app+timeline | CURRENT | no
R4  | Physical damage before control: no magic-pool consumption      | app+timeline | CURRENT | no
R5  | Magic below shield strength before control: drain + persist    | app+timeline | CURRENT | no
R6a | Same-packet damage+CC breaks the shield — variant BLOCKED      | timeline   | CURRENT (gate before absorb) | YES — exactly one of R6a/R6a-alt pinned
R6a-alt | Same-packet damage+CC breaks the shield — variant LANDS never occurs (documented boundary) | timeline | CURRENT (deterministic non-occurrence) | YES — RLM-2 A still owns which wiki rule is cited, not what the walk does today
R6b | Depletion before a later control packet -> CC lands            | timeline+app | CURRENT | no
R7  | Shield lifetime: start inclusive, end exclusive                | kernel+timeline | CURRENT (behavior) / NEW-CONTRACT (decide API) | no
R8  | Shield ownership: another shield never keeps immunity          | timeline+kernel | CURRENT | no
R9  | Packet ordering: two same-time controls, stable total order    | timeline+kernel | CURRENT (order) / NEW-CONTRACT (decide API) | no
R10 | Unknown control kind fails closed (contract level)             | kernel      | NEW-CONTRACT (today silently ignored) | no
R11 | Walk order: stasis -> projectile -> spell shield -> CC -> damage (a-e sub-cases) | app+timeline | CURRENT | no
R12 | Receipt-versus-result parity (survival row / events / downtime) | app        | CURRENT (parity) / NEW-CONTRACT (receipt fields) | no
R13 | Score-path fail-closed (representable today; contract-owned gate) | unit      | CURRENT (representable) / NEW-CONTRACT (gate) | no
R14 | Non-control damage never reports a control block               | app+timeline | CURRENT | no
R15 | Physical damage never consumes the magic pool (ledger)         | unit (ledger) | CURRENT | no
R16 | One contract for damage-attached and control-only packets      | kernel      | NEW-CONTRACT (single contract identity) | no
R17 | Kernel fail-closed: reason enumeration + soft control          | kernel      | NEW-CONTRACT | no
R18 | Kernel fail-closed: immunity tied to the exact ledger entry    | kernel      | NEW-CONTRACT (API; behavior CURRENT) | no
R19 | Kernel fail-closed: same-hit rule unverified -> missing_same_hit_rule | kernel | NEW-CONTRACT | YES
R20 | Kernel contract: receipt shapes (six separation concerns)      | kernel      | NEW-CONTRACT | no
"""

from types import SimpleNamespace
from typing import Any

import pytest

from src.app import app
from src.calculator.program.build import roster_program as _roster_program
from src.calculator.program.views.survival import survival as _survival_view
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.roster_composition import ActorRequest
from src.calculator import shield_ledger
from src.calculator.delivery_eligibility import DefenseWindow, stable_event_key
from src.calculator.participant_timeline import (
    Combatant,
    _WalkCompiler,
    _simulate_survival as _simulate_survival_walk,
)
from src.calculator.state_lifecycle import SourceReceipt
from src.calculator.survival.actions import ActionKind
from src.calculator.survival.compile import unrepresentable_template_receipt


# MERGE: ``_simulate_survival`` returns the frozen ``WalkResult`` now -- one
# walk handed to five views -- so a caller that wants the published rows
# projects it through the survival view, exactly as the composition does.
def _simulate_survival(combatants, *args, **kwargs):
    combatant_list = list(combatants)
    return _survival_view(
        _roster_program(combatant_list),
        _simulate_survival_walk(combatant_list, *args, **kwargs),
    )


try:  # P2 Slice 3 planned kernel — not landed yet; rows fail with the marker.
    from src.calculator import crowd_control_eligibility as cce
except ImportError:  # pragma: no cover - expected until the kernel lands
    cce = None


def _require_contract():
    """Return the planned crowd-control eligibility kernel.

    The module does not exist until the RLM-1 owner lands P2 Slice 3;
    every contract-API assertion calls this so the suite collects and each
    row fails with the named pending-kernel marker instead of one
    collection error (the intended signal, reported to the owner)."""
    if cce is None:
        pytest.fail(
            "PENDING KERNEL: src/calculator/crowd_control_eligibility.py "
            "has not landed yet; this assertion targets the P2 Slice 3 "
            "contract API and is expected to fail until the owner lands it"
        )
    return cce


# -- app-level helpers -------------------------------------------------------


def _calculate(payload: dict) -> dict:
    app.config["TESTING"] = True
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


def _survival(combat: dict, participant_id: str) -> dict:
    return next(
        row["survival"]
        for row in combat["participants"]
        if row["participant_id"] == participant_id
    )


def _cc_blocked(combat: dict, target: str) -> list[dict]:
    """Events whose control was blocked by Black Shield immunity."""
    return [
        event
        for event in combat["events"]
        if event.get("target") == target and event.get("crowd_control_blocked")
    ]


def _cc_applied(combat: dict, target: str) -> list[dict]:
    """Events whose control landed (action downtime added)."""
    return [
        event
        for event in combat["events"]
        if event.get("target") == target and event.get("crowd_control")
    ]


def _morgana(*, shield_target: int = 1, duration: float = 6.0) -> dict:
    """Morgana as the support: E rank 5 Black Shield, nothing else."""
    return {
        "champion": "Morgana",
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": False,
        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
        "support_target_selections": {"shield:E:0": shield_target},
    }


def _ally(
    champion: str,
    *,
    items: list[str] | None = None,
    item_options: dict | None = None,
    options: dict | None = None,
    ranks: dict | None = None,
) -> dict:
    ally: dict = {
        "champion": champion,
        "level": 18,
        "items": items or [],
        "ally_effects_enabled": True,
    }
    if ranks is not None:
        ally["ability_ranks"] = ranks
    if options is not None:
        ally["champion_options"] = options
    if item_options is not None:
        ally["item_options"] = item_options
    return ally


def _enemy(
    champion: str, *, ranks: dict | None = None, cast: list[str] | None = None
) -> dict:
    enemy: dict = {"champion": champion, "level": 18, "items": []}
    enemy["ability_ranks"] = ranks or {"Q": 0, "W": 0, "E": 5, "R": 0}
    if champion == "Lulu":
        # Whimsy is one cast with two exclusive branches (cached effects[1]
        # enemy polymorph vs effects[2] self/ally attack speed); these
        # fixtures are about the control, so they cast it on the enemy.
        enemy["champion_options"] = {"lulu_whimsy_target": "enemy"}
    if cast is not None:
        enemy["cast_order"] = cast
    return enemy


def _ahri_e() -> dict:
    """Ahri Charm only: one damage+CC skillshot packet per cast."""
    return _enemy("Ahri", ranks={"Q": 0, "W": 0, "E": 5, "R": 0})


def _lulu_qw() -> dict:
    """Lulu Glitterlance (magic) + Whimsy polymorph (control-only)."""
    return _enemy("Lulu", ranks={"Q": 5, "W": 5, "E": 0, "R": 0})


def _two_allies() -> list[dict]:
    return [
        {"champion": "Jinx", "level": 18, "items": [], "ally_effects_enabled": True},
        {"champion": "Lux", "level": 18, "items": [], "ally_effects_enabled": True},
    ]


# -- timeline-level helpers --------------------------------------------------


def _dummy_combatant(
    participant_id: str,
    team: str,
    health: float = 3000.0,
) -> Combatant:
    """Minimal combatant for timeline tests, mirroring the pinned suite."""
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


def _braum_combatant(
    participant_id: str = "target", health: float = 3000.0
) -> Combatant:
    """A Braum defender with e_active armed, for timeline walk-order rows."""
    from src.calculator.data_fetcher import get_champion

    data = get_champion("Braum")
    # ``Combatant`` admits a typed ``ActorRequest`` and nothing else; the
    # level rides the combatant itself, not the request.
    request = ActorRequest(
        champion_options={
            "e_active": True,
            "e_active_seconds": 4.0,
            "e_blocked_skillshots": [],
        },
    )
    return Combatant(
        participant_id=participant_id,
        team="main",
        champion_data=data,
        level=18,
        items=(),
        stats={"health": health, "armor": 0.0, "magic_resistance": 0.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
        request=request,
    )


def _black_shield_template(
    amount: float = 320.0, duration: float = 5.0, time: float = 0.0
) -> dict:
    """The authored Black Shield support template (timeline rows)."""
    return {
        "time": time,
        "kind": "shield",
        "amount": amount,
        "duration": duration,
        "attacker": "caster",
        "source": "Black Shield",
        "shield_pool": "magic",
        "crowd_control_immunity_while_shield": True,
        "crowd_control_immunity_source": "Black Shield",
    }


def _control_packet(
    time: float,
    *,
    kind: str = "stun",
    duration: float = 1.5,
    source: str = "E",
    damage: float = 0.0,
    damage_type: str = "magic",
    sequence: int = 0,
    skillshot: bool = False,
    event_id: str | None = None,
) -> dict:
    """One authored incoming packet for timeline rows.

    ``damage == 0.0`` with a ``cc_kind`` authors a control-only packet
    (kind "crowd_control", the walk's ActionKind.CROWD_CONTROL branch);
    ``damage > 0.0`` with a ``cc_kind`` authors a damage-attached control
    packet.  ``cc_kind == ""`` authors a plain damage packet with no
    control markers (R4/R5/R14 set this on their damage packets so only
    the intended packet carries control)."""
    packet: dict = {
        "time": time,
        "damage": damage,
        "damage_type": damage_type,
        "attacker": "enemy",
        "target": "target",
        "source_key": source,
        "source": source,
        "is_ability": True,
        "kind": "crowd_control" if damage == 0.0 else "damage",
        "sequence": sequence,
        "_event_id": event_id or f"cc-{sequence}",
    }
    if kind:
        packet["cc_kind"] = kind
        packet["cc_duration"] = duration
    if skillshot:
        packet["skillshot"] = True
    return packet


def _simulate(
    packets: list[dict],
    supports: list[dict] | None = None,
    *,
    combatants: list[Combatant] | None = None,
    duration: float = 10.0,
) -> tuple[dict[str, dict[str, Any]], list[dict]]:
    """One timeline run; returns (survival result, annotated packets)."""
    if combatants is None:
        combatants = [
            _dummy_combatant("enemy", "enemy"),
            _dummy_combatant("target", "main"),
        ]
    result = _simulate_survival(
        combatants,
        {"target": packets},
        {},
        {"target": supports or []},
        duration,
    )
    return result, packets


# -- kernel-level helpers ----------------------------------------------------


class _CcAction:
    """One incoming packet with the typed fields the CC contract reads."""

    def __init__(
        self,
        *,
        time: float = 0.5,
        source_key: str = "E",
        sequence: int = 0,
        event_id: str = "packet",
        is_ability: bool = True,
        kind: str = "",
        cc_kind: str = "stun",
        cc_duration: float = 1.5,
        damage: float = 0.0,
        damage_type: str = "magic",
        skillshot: bool = False,
    ) -> None:
        self.time = time
        self.source_key = source_key
        self.sequence = sequence
        self.event_id = event_id
        self.is_ability = is_ability
        self.kind = kind
        self.cc_kind = cc_kind
        self.cc_duration = cc_duration
        self.damage = damage
        self.damage_type = damage_type
        self.skillshot = skillshot


def _holder(
    amount: float = 320.0, expires_at: float = 5.0
) -> shield_ledger.TimedShield:
    """One exact Black Shield ledger entry (the immunity holder)."""
    return shield_ledger.TimedShield(
        amount=amount,
        expires_at=expires_at,
        pool=shield_ledger.MAGIC,
        source="Black Shield",
    )


def _eligibility(
    start: float = 0.0,
    until: float = 5.0,
    holder_source: str = "Black Shield",
):
    """One contract eligibility declaration (kernel rows)."""
    return cce.CrowdControlEligibility(
        name="crowd_control_immunity",
        window=DefenseWindow(start=start, until=until),
        holder_source=holder_source,
        source=SourceReceipt(
            label="Local League Wiki cache — Morgana E Black Shield",
            url="https://wiki.leagueoflegends.com",
        ),
    )


# ---------------------------------------------------------------------------
# R1 — Black Shield protects the selected ally only
# ---------------------------------------------------------------------------


def test_r1_black_shield_protects_the_selected_ally_only():
    """The shield lands on the selected ally only: the recipient's CC is
    blocked with zero added downtime, the unselected ally takes the full
    control, and the contract receipt names the recipient + holder."""
    combat = _calculate(
        {
            **_morgana(),
            "enemies": [_ahri_e()],
            "allies": _two_allies(),
        }
    )

    # CURRENT behavior: ally:Lux (selected) blocked, ally:Jinx takes CC.
    blocked = _cc_blocked(combat, "ally:Lux")
    assert len(blocked) == 1
    (charm,) = blocked
    assert charm["source"] == "E"
    assert charm["crowd_control_blocked"]["source"] == "Black Shield"
    assert charm["crowd_control_blocked"]["until"] == pytest.approx(5.0)
    assert _survival(combat, "ally:Lux")["action_downtime"] == pytest.approx(0.0)
    assert _survival(combat, "ally:Lux")["crowd_control_intervals"] == []

    jinx_cc = _cc_applied(combat, "ally:Jinx")
    assert len(jinx_cc) == 1
    assert jinx_cc[0]["source"] == "E"
    assert jinx_cc[0]["crowd_control"]["duration"] == pytest.approx(1.8)
    assert _survival(combat, "ally:Jinx")["action_downtime"] == pytest.approx(1.8)
    assert _survival(combat, "ally:Jinx")["crowd_control_until"] == pytest.approx(1.8)

    # NEW-CONTRACT: the recipient's survival row carries the immunity
    # receipt (recipient, holder source, window, active-until, ended
    # reason, blocked entries); the unselected ally has none.
    cce = _require_contract()
    receipt = _survival(combat, "ally:Lux")["crowd_control_immunity"]
    assert receipt["recipient"] == "ally:Lux"
    assert receipt["shield_source"] == "Black Shield"
    assert receipt["window"]["start"] == pytest.approx(0.0)
    assert receipt["window"]["until"] == pytest.approx(5.0)
    assert receipt["active_until"] == pytest.approx(5.0)
    assert receipt["reason_immunity_ended"] == "expired"
    assert [entry["control_kind"] for entry in receipt["blocked"]] == ["immobilize"]
    assert "crowd_control_immunity" not in _survival(combat, "ally:Jinx")


# ---------------------------------------------------------------------------
# R2 — damage-attached charm while the shield remains
# ---------------------------------------------------------------------------


def test_r2_damage_attached_cc_blocked_while_shield_remains():
    """Ahri E is damage-attached: the magic damage applies (absorbed by the
    shield), the charm is blocked, and zero action downtime is added."""
    combat = _calculate(
        {
            **_morgana(),
            "enemies": [_ahri_e()],
            "allies": _two_allies(),
        }
    )

    # CURRENT behavior: damage absorbed, CC blocked, zero downtime.
    (charm,) = _cc_blocked(combat, "ally:Lux")
    assert charm["damage"] == pytest.approx(157.9)
    assert charm["cc_kind"] == "immobilize"
    assert charm["cc_duration"] == pytest.approx(1.8)
    assert charm["crowd_control_blocked"]["source"] == "Black Shield"
    lux = _survival(combat, "ally:Lux")
    assert lux["health_damage"] == pytest.approx(0.0)
    assert lux["shield_absorbed"] == pytest.approx(157.9)
    assert lux["action_downtime"] == pytest.approx(0.0)

    # NEW-CONTRACT: the blocked event's receipt carries the decision —
    # control kind, eligibility verdict, holder source, shield amount
    # before the packet's absorption and after it, active-until time.
    cce = _require_contract()
    receipt = charm["crowd_control_blocked"]
    decision = receipt["decision"]
    assert decision["eligible"] is True
    assert decision["reason"] == ""
    assert decision["control"]["kind"] == "immobilize"
    assert decision["control"]["blocking"] is True
    assert decision["control"]["unknown"] is False
    assert decision["shield_source"] == "Black Shield"
    assert decision["shield_amount_before"] == pytest.approx(320.0)
    assert decision["active_until"] == pytest.approx(5.0)
    assert receipt["shield_amount_after"] == pytest.approx(162.1)
    assert receipt["shield_amount_after"] == pytest.approx(
        decision["shield_amount_before"] - charm["damage"]
    )


# ---------------------------------------------------------------------------
# R3 — control-only packet while the shield remains
# ---------------------------------------------------------------------------


def test_r3_control_only_packet_blocked_while_shield_remains():
    """Lulu Whimsy is a control-only ability packet (zero damage): while
    the shield remains it is blocked with zero added downtime — the SAME
    gate the damage-attached packet of R2 rides (R16 pins the single
    contract identity)."""
    combat = _calculate(
        {
            **_morgana(),
            "enemies": [_lulu_qw()],
            "allies": _two_allies(),
        }
    )

    # CURRENT behavior: control-only packet blocked, zero downtime.
    (whimsy,) = _cc_blocked(combat, "ally:Lux")
    assert whimsy["source"] == "W"
    assert whimsy["damage"] == pytest.approx(0.0)
    assert whimsy["cc_kind"] == "polymorph"
    assert whimsy["cc_duration"] == pytest.approx(2.0)
    assert whimsy["crowd_control_blocked"]["source"] == "Black Shield"
    assert _survival(combat, "ally:Lux")["action_downtime"] == pytest.approx(0.0)
    jinx_cc = _cc_applied(combat, "ally:Jinx")
    assert len(jinx_cc) == 1
    assert jinx_cc[0]["crowd_control"]["duration"] == pytest.approx(2.0)
    assert _survival(combat, "ally:Jinx")["action_downtime"] == pytest.approx(2.0)

    # NEW-CONTRACT: identical decision receipt shape to R2 (same fields,
    # polymorph kind; the control-only packet spends no shield amount).
    # NOTE: Lulu Q (131.6 magic) sorts BEFORE the W control-only packet at
    # t=0 (Q damage seq precedes the control packet seq), so the W decision
    # sees the drained holder — 320 - 131.6 == 188.4, exactly the value R5
    # pins for the same payload.
    cce = _require_contract()
    decision = whimsy["crowd_control_blocked"]["decision"]
    assert decision["eligible"] is True
    assert decision["reason"] == ""
    assert decision["control"]["kind"] == "polymorph"
    assert decision["shield_amount_before"] == pytest.approx(188.4)
    assert whimsy["crowd_control_blocked"]["shield_amount_after"] == pytest.approx(
        188.4
    )


def test_r3_control_only_packet_blocked_timeline_level():
    """Timeline level: an authored control-only packet (kind
    'crowd_control', cc fields, zero damage) is blocked while the shield
    holds: zero downtime, zero damage, blocked receipt."""
    result, packets = _simulate(
        [_control_packet(1.0, kind="stun", duration=2.5)],
        [_black_shield_template()],
    )
    target = result["target"]
    assert target["action_downtime"] == pytest.approx(0.0)
    assert target["crowd_control_until"] == pytest.approx(0.0)
    assert target["damage_taken"] == pytest.approx(0.0)
    (packet,) = packets
    assert packet["crowd_control_blocked"]["source"] == "Black Shield"

    # NEW-CONTRACT: the decision gate ran (not silently skipped).
    cce = _require_contract()
    decision = packet["crowd_control_blocked"]["decision"]
    assert decision["eligible"] is True
    assert decision["control"]["kind"] == "stun"


# ---------------------------------------------------------------------------
# R4 — physical damage before control does not consume the magic pool
# ---------------------------------------------------------------------------


def test_r4_physical_before_control_does_not_consume_magic_pool():
    """A physical hit before the control packet does NOT drain the magic
    pool: immunity persists and the later control is blocked."""
    combat = _calculate(
        {
            **_morgana(),
            "enemies": [
                _enemy("Aatrox", ranks={"Q": 5, "W": 0, "E": 0, "R": 0}),
                _enemy("Lulu", ranks={"Q": 0, "W": 5, "E": 0, "R": 0}),
            ],
            "allies": _two_allies(),
        }
    )

    # CURRENT behavior: physical damage lands on health, shield pool
    # untouched, polymorph still blocked.
    (swing,) = [
        event
        for event in _events(combat, target="ally:Lux")
        if event.get("attacker") == "enemy:Aatrox" and event.get("source") == "Q"
    ]
    assert swing["damage_type"] == "physical"
    assert swing["damage"] == pytest.approx(629.6)
    assert "crowd_control_blocked" not in swing
    lux = _survival(combat, "ally:Lux")
    assert lux["shield_absorbed"] == pytest.approx(0.0)
    assert lux["health_damage"] == pytest.approx(629.6)
    (whimsy,) = [
        event
        for event in _events(combat, target="ally:Lux")
        if event.get("attacker") == "enemy:Lulu" and event.get("source") == "W"
    ]
    assert whimsy["crowd_control_blocked"]["source"] == "Black Shield"
    assert lux["action_downtime"] == pytest.approx(0.0)

    # NEW-CONTRACT: the decision sees the FULL holder amount (physical
    # damage never touched the magic pool).
    cce = _require_contract()
    assert whimsy["crowd_control_blocked"]["decision"]["shield_amount_before"] == (
        pytest.approx(320.0)
    )


def test_r4_physical_before_control_timeline_level():
    """Timeline level: physical 200 then control-only: magic pool stays at
    320, immunity persists, control blocked."""
    result, packets = _simulate(
        [
            _control_packet(
                1.0,
                damage=200.0,
                damage_type="physical",
                sequence=0,
                source="A",
                kind="",
            ),
            _control_packet(2.0, sequence=1, source="B"),
        ],
        [_black_shield_template()],
    )
    target = result["target"]
    assert target["health_damage"] == pytest.approx(200.0)
    assert target["shield_absorbed"] == pytest.approx(0.0)
    assert target["action_downtime"] == pytest.approx(0.0)
    blocked = [packet for packet in packets if packet.get("crowd_control_blocked")]
    assert len(blocked) == 1
    assert blocked[0]["time"] == pytest.approx(2.0)

    # NEW-CONTRACT: the decision sees the FULL holder amount (physical
    # damage never touched the magic pool — R15 pins the ledger totals).
    cce = _require_contract()
    decision = blocked[0]["crowd_control_blocked"]["decision"]
    assert decision["shield_amount_before"] == pytest.approx(320.0)


# ---------------------------------------------------------------------------
# R5 — magic damage below shield strength before control
# ---------------------------------------------------------------------------


def test_r5_magic_below_shield_strength_persists_immunity():
    """Magic damage below the shield strength drains the pool but the
    immunity persists: the later control is blocked."""
    combat = _calculate(
        {
            **_morgana(),
            "enemies": [_lulu_qw()],
            "allies": _two_allies(),
        }
    )

    # CURRENT behavior: Q (131.6 magic) drains the pool; W still blocked.
    (q,) = [
        event
        for event in _events(combat, target="ally:Lux")
        if event.get("source") == "Q"
    ]
    assert q["damage"] == pytest.approx(131.6)
    assert "crowd_control_blocked" not in q
    (whimsy,) = _cc_blocked(combat, "ally:Lux")
    assert whimsy["source"] == "W"
    assert whimsy["crowd_control_blocked"]["source"] == "Black Shield"
    lux = _survival(combat, "ally:Lux")
    assert lux["shield_absorbed"] == pytest.approx(131.6)
    assert lux["health_damage"] == pytest.approx(0.0)
    assert lux["action_downtime"] == pytest.approx(0.0)

    # NEW-CONTRACT: the decision sees the drained-but-alive holder
    # (320 - 131.6 == 188.4) and still blocks.
    cce = _require_contract()
    decision = whimsy["crowd_control_blocked"]["decision"]
    assert decision["shield_amount_before"] == pytest.approx(188.4)
    assert decision["eligible"] is True


def test_r5_magic_below_shield_strength_timeline_level():
    """Timeline level: magic 200 < 320 then control-only: pool drains by
    200, immunity persists, control blocked."""
    result, packets = _simulate(
        [
            _control_packet(1.0, damage=200.0, sequence=0, source="A", kind=""),
            _control_packet(2.0, sequence=1, source="B"),
        ],
        [_black_shield_template()],
    )
    target = result["target"]
    assert target["shield_absorbed"] == pytest.approx(200.0)
    assert target["health_damage"] == pytest.approx(0.0)
    assert target["action_downtime"] == pytest.approx(0.0)
    blocked = [packet for packet in packets if packet.get("crowd_control_blocked")]
    assert len(blocked) == 1
    assert blocked[0]["time"] == pytest.approx(2.0)

    cce = _require_contract()
    decision = blocked[0]["crowd_control_blocked"]["decision"]
    assert decision["shield_amount_before"] == pytest.approx(120.0)
    assert decision["eligible"] is True


# ---------------------------------------------------------------------------
# R6 — magic damage that depletes the shield before/on a control packet
# ---------------------------------------------------------------------------
# The same-hit ordering is verified by RLM-2 A (read-only source audit).
# Exactly ONE of R6a / R6a-alt is pinned by that evidence; while
# unverified the contract fails closed with the named missing_same_hit_rule
# reason (R19) instead of guessing.


def test_r6a_same_packet_damage_breaks_shield_variant_blocked():
    """Variant A (today's walk order): the CC gate runs BEFORE the same
    packet's absorption, so a packet whose own magic damage fully depletes
    the shield still has its control blocked (320 absorbed, 80 to health,
    zero downtime).  Pinned ONLY if RLM-2 A verifies the gate-before-absorb
    ordering; otherwise R6a-alt is pinned."""
    result, packets = _simulate(
        [_control_packet(1.0, damage=400.0, sequence=0)],
        [_black_shield_template()],
    )
    target = result["target"]
    assert target["shield_absorbed"] == pytest.approx(320.0)
    assert target["health_damage"] == pytest.approx(80.0)
    assert target["action_downtime"] == pytest.approx(0.0)
    assert target["crowd_control_until"] == pytest.approx(0.0)
    (packet,) = packets
    assert packet["crowd_control_blocked"]["source"] == "Black Shield"

    # NEW-CONTRACT: the walk resolves this ordering through
    # same_hit_ordering() (R19 fails closed while RLM-2 A is unverified);
    # the decision gate itself only sees the holder present, so the
    # blocked receipt carries the full before-amount and a zero after.
    cce = _require_contract()
    decision = packet["crowd_control_blocked"]["decision"]
    assert decision["eligible"] is True
    assert decision["shield_amount_before"] == pytest.approx(320.0)
    assert packet["crowd_control_blocked"]["shield_amount_after"] == pytest.approx(0.0)


def test_r6a_alt_variant_lands_does_not_occur_the_walk_deterministically_blocks():
    """Documented boundary, not an xfail (until the RLM-2 A audit lands):
    Variant B (absorb-before-gate, same-packet control lands with 1.5s
    downtime) is not a live ambiguity in the WALK today — it is a
    deterministic non-occurrence.  Running the exact packet/support
    sequence R6a pins produces the SAME gate-before-absorb result on every
    call: the same-packet control is blocked (zero downtime), never
    landed.  RLM-2 A's same-hit ORDERING RULE remains single-provenance /
    UNCERTAIN, but that uncertainty is about which wiki-sourced rule to
    cite, not about what the walk currently does — the walk has exactly
    one behavior, and this row asserts it directly instead of pretending
    the alternate is reachable."""
    result, packets = _simulate(
        [_control_packet(1.0, damage=400.0, sequence=0)],
        [_black_shield_template()],
    )
    target = result["target"]
    assert target["shield_absorbed"] == pytest.approx(320.0)
    assert target["health_damage"] == pytest.approx(80.0)
    # The alternate "lands" outcome (1.5s downtime, crowd_control_until
    # 2.5) never happens — the walk deterministically blocks instead.
    assert target["action_downtime"] == pytest.approx(0.0)
    assert target["crowd_control_until"] == pytest.approx(0.0)
    (packet,) = packets
    assert packet["crowd_control_blocked"]["source"] == "Black Shield"
    assert packet.get("crowd_control") is None

    # The kernel-level absent-holder denial IS fail-closed and independent
    # of the same-hit ordering question: decide() with no holder present
    # always denies "shield_not_held", regardless of which same-hit
    # variant RLM-2 A eventually certifies.
    cce = _require_contract()
    decision = _eligibility().decide(_CcAction(time=1.0), holder=None)
    assert decision.eligible is False
    assert decision.reason == "shield_not_held"


def test_r6b_depletion_before_later_control_packet_cc_lands():
    """A damage packet depletes the shield; a LATER control packet (after
    depletion) lands: the immunity holder is gone and the control applies
    its full sourced duration."""
    result, packets = _simulate(
        [
            _control_packet(1.0, damage=400.0, sequence=0, source="A"),
            _control_packet(2.0, sequence=1, source="B"),
        ],
        [_black_shield_template()],
    )
    target = result["target"]
    assert target["shield_absorbed"] == pytest.approx(320.0)
    assert target["action_downtime"] == pytest.approx(1.5)
    assert target["crowd_control_until"] == pytest.approx(3.5)
    applied = [packet for packet in packets if packet.get("crowd_control")]
    assert len(applied) == 1
    assert applied[0]["time"] == pytest.approx(2.0)

    # NEW-CONTRACT: the second packet was never blocked — its decision
    # fails closed with the named absent-holder reason.
    cce = _require_contract()
    assert "crowd_control_blocked" not in applied[0]
    decision = _eligibility().decide(_CcAction(time=2.0), holder=None)
    assert decision.eligible is False
    assert decision.reason == "shield_not_held"


def test_r6b_app_depletion_then_stun_lands():
    """App level: enemy Morgana R (t=0, 230.3 magic) + Q (t=0.35, 197.4
    magic + root) drain the 320 shield; the t=3.0 tether-break stun
    lands (2.0s downtime)."""
    combat = _calculate(
        {
            **_morgana(shield_target=0),
            "enemies": [
                _enemy(
                    "Morgana",
                    ranks={"Q": 5, "W": 0, "E": 0, "R": 3},
                    cast=["R", "Q", "W", "E"],
                )
            ],
            "allies": [_ally("Lux")],
        }
    )

    r_events = sorted(
        _events(combat, target="ally:Lux", source="R"), key=lambda event: event["time"]
    )
    first, tether = r_events
    assert first["time"] == pytest.approx(0.0)
    assert first["damage"] == pytest.approx(230.3)
    assert "crowd_control" not in first and "crowd_control_blocked" not in first
    (q,) = _events(combat, target="ally:Lux", source="Q")
    assert q["time"] == pytest.approx(0.35)
    assert q["damage"] == pytest.approx(197.4)
    assert q["crowd_control_blocked"]["source"] == "Black Shield"

    assert tether["time"] == pytest.approx(3.0)
    assert tether["cc_kind"] == "stun"
    assert tether["crowd_control"]["duration"] == pytest.approx(2.0)
    lux = _survival(combat, "ally:Lux")
    assert lux["action_downtime"] == pytest.approx(2.0)
    assert lux["crowd_control_until"] == pytest.approx(5.0)

    # NEW-CONTRACT: the survival-row receipt reports the immunity ended
    # because the holder was DRAINED (not expired).
    cce = _require_contract()
    receipt = lux["crowd_control_immunity"]
    assert receipt["reason_immunity_ended"] == "drained"
    assert receipt["active_until"] == pytest.approx(5.0)
    assert [entry["control_kind"] for entry in receipt["blocked"]] == ["root"]


# ---------------------------------------------------------------------------
# R7 — shield lifetime: start inclusive, end exclusive
# ---------------------------------------------------------------------------


def test_r7_window_boundaries_start_inclusive_end_exclusive():
    """Events before the shield cast land; at the cast time they are
    blocked; just before expiry blocked; at expiry (end exclusive) they
    land again."""
    result, packets = _simulate(
        [
            _control_packet(1.0, source="A", sequence=0),
            _control_packet(2.0, source="B", sequence=1),
            _control_packet(4.999, source="C", sequence=2),
            _control_packet(5.0, source="D", sequence=3),
        ],
        [_black_shield_template(time=2.0, duration=3.0)],
    )
    target = result["target"]
    intervals = target["crowd_control_intervals"]
    assert [(entry["start"], entry["end"], entry["source"]) for entry in intervals] == [
        (1.0, 2.5, "A"),
        (5.0, 6.5, "D"),
    ]
    assert target["action_downtime"] == pytest.approx(3.0)
    blocked = [packet for packet in packets if packet.get("crowd_control_blocked")]
    assert sorted((packet["time"], packet["source"]) for packet in blocked) == [
        (2.0, "B"),
        (4.999, "C"),
    ]

    # NEW-CONTRACT: the kernel decision reproduces the same boundary
    # convention (start inclusive, end exclusive) on the eligibility window.
    cce = _require_contract()
    eligibility = _eligibility(start=2.0, until=5.0)
    holder = _holder()
    before = eligibility.decide(_CcAction(time=1.9999999), holder=holder)
    assert before.eligible is False and before.reason == "outside_window"
    at_start = eligibility.decide(_CcAction(time=2.0), holder=holder)
    assert at_start.eligible is True and at_start.reason == ""
    just_before = eligibility.decide(_CcAction(time=4.9999999), holder=holder)
    assert just_before.eligible is True and just_before.reason == ""
    at_end = eligibility.decide(_CcAction(time=5.0), holder=holder)
    assert at_end.eligible is False and at_end.reason == "outside_window"


# ---------------------------------------------------------------------------
# R8 — shield ownership: another shield never keeps immunity
# ---------------------------------------------------------------------------


def test_r8_another_shield_does_not_keep_immunity():
    """After Black Shield breaks, a general shield granted by another
    source (Lux Prismatic Barrier) does NOT keep immunity: the later
    control lands even though a shield remains on the target."""
    result, packets = _simulate(
        [
            _control_packet(1.0, damage=400.0, sequence=0, source="A"),
            _control_packet(2.0, sequence=1, source="B"),
        ],
        [
            _black_shield_template(),
            {
                "time": 1.5,
                "kind": "shield",
                "amount": 500.0,
                "duration": 3.0,
                "attacker": "ally",
                "source": "Prismatic Barrier",
                "shield_pool": "general",
            },
        ],
    )
    target = result["target"]
    # The Black Shield absorbed 320; the general shield (still present at
    # the control) absorbed the rest — but grants no immunity.
    assert target["shield_absorbed"] == pytest.approx(320.0)
    assert target["action_downtime"] == pytest.approx(1.5)
    assert target["crowd_control_until"] == pytest.approx(3.5)
    assert target["crowd_control_immunity_until"] == pytest.approx(0.0)
    applied = [packet for packet in packets if packet.get("crowd_control")]
    assert len(applied) == 1 and applied[0]["time"] == pytest.approx(2.0)

    # NEW-CONTRACT: the exact Black Shield ledger entry is the only
    # immunity holder — the general entry never matches.
    cce = _require_contract()
    pools = shield_ledger.build_pools(health=2000.0)
    shield_ledger.grant(
        pools, 320.0, pool=shield_ledger.MAGIC, expires_at=5.0, source="Black Shield"
    )
    shield_ledger.grant(
        pools,
        500.0,
        pool=shield_ledger.GENERAL,
        expires_at=4.5,
        source="Prismatic Barrier",
    )
    shield_ledger.absorb(pools, 400.0, "magic", 1.0)  # drains the Black Shield entry
    assert cce.immunity_holder(pools, "Black Shield", event_time=2.0) is None
    assert cce.immunity_holder(pools, "Prismatic Barrier", event_time=2.0) is not None
    decision = _eligibility().decide(_CcAction(time=2.0), holder=None)
    assert decision.reason == "shield_not_held"


# ---------------------------------------------------------------------------
# R9 — packet ordering: two same-time control packets
# ---------------------------------------------------------------------------


def test_r9_two_same_time_controls_are_deterministic():
    """Two control packets at one timestamp resolve through the stable
    total order: both are decided in-window, the walk's outcome is
    identical across repeated runs, and the kernel decisions carry the
    stable event key (source_key:time:sequence)."""
    packets_a = [
        _control_packet(1.0, source="A", sequence=0, kind="stun"),
        _control_packet(1.0, source="B", sequence=1, kind="root"),
    ]

    def run():
        return _simulate(
            [dict(packet) for packet in packets_a], [_black_shield_template()]
        )

    result_one, events_one = run()
    result_two, events_two = run()
    assert result_one == result_two
    assert [event["crowd_control_blocked"]["source"] for event in events_one] == [
        "Black Shield",
        "Black Shield",
    ]
    assert events_one[0]["time"] == events_one[1]["time"] == pytest.approx(1.0)
    assert result_one["target"]["action_downtime"] == pytest.approx(0.0)

    # NEW-CONTRACT: each decision is identified by stable_event_key and the
    # same-time order follows the event keys deterministically.
    cce = _require_contract()
    eligibility = _eligibility()
    holder = _holder()
    first = eligibility.decide(
        _CcAction(time=1.0, source_key="A", sequence=0, cc_kind="stun"),
        holder=holder,
    )
    second = eligibility.decide(
        _CcAction(time=1.0, source_key="B", sequence=1, cc_kind="root"),
        holder=holder,
    )
    assert first.eligible is True and second.eligible is True
    assert first.event_key == stable_event_key(
        _CcAction(time=1.0, source_key="A", sequence=0)
    )
    assert first.event_key == "A:1.0:0"
    assert second.event_key == "B:1.0:1"
    ordered = sorted([second, first], key=lambda decision: decision.event_key)
    assert [decision.event_key for decision in ordered] == ["A:1.0:0", "B:1.0:1"]
    assert ordered[0].control.kind == "stun"
    assert ordered[1].control.kind == "root"


# ---------------------------------------------------------------------------
# R10 — unknown control kind fails closed (contract level)
# ---------------------------------------------------------------------------


def test_r10_unknown_control_kind_fails_closed():
    """A control packet whose kind is not in the known set fails closed:
    classify_control marks it unknown, decide() denies it with the named
    'unknown_control' reason, and the strict API raises
    UnknownControlError.  (Today's walk silently ignores such kinds —
    no receipt, no downtime — which is the gap this row closes.)"""
    cce = _require_contract()
    action = _CcAction(cc_kind="dance", cc_duration=2.0)

    profile = cce.classify_control(action)
    assert profile.kind == "dance"
    assert profile.blocking is False
    assert profile.unknown is True
    assert profile.unknown_markers == ("unknown_control_kind",)

    with pytest.raises(cce.UnknownControlError):
        cce.required_control_class(action)

    decision = _eligibility().decide(action, holder=_holder())
    assert decision.eligible is False
    assert decision.reason == "unknown_control"
    assert decision.control.unknown is True


# ---------------------------------------------------------------------------
# R11 — walk order: stasis -> projectile destroy/full-block -> spell shield
#       -> CC immunity -> damage
# ---------------------------------------------------------------------------


def test_r11a_spell_shield_blocks_the_cast_entirely():
    """Annul (Banshee's Veil) blocks the whole hostile cast before the CC
    gate: the Ahri E outside the wind-wall window is spell-shielded with
    no crowd-control receipt at all — there is no CC left to block."""
    combat = _calculate(
        {
            **_morgana(shield_target=0, duration=14.0),
            "enemies": [_ahri_e()],
            "allies": [
                _ally(
                    "Yasuo",
                    items=["Banshee's Veil"],
                    options={
                        "w_active": True,
                        "w_active_from": 1.0,
                        "w_active_seconds": 4.0,
                        "w_blocked_skillshots": ["E"],
                    },
                )
            ],
        }
    )
    e_events = sorted(
        _events(combat, target="ally:Yasuo", source="E"),
        key=lambda event: event["time"],
    )
    annul_blocked, later = e_events
    assert annul_blocked["time"] == pytest.approx(0.0)
    assert annul_blocked["skipped_reason"] == "spell_shield"
    assert annul_blocked["spell_shield_source"] == "Banshee's Veil — Annul"
    assert "crowd_control_blocked" not in annul_blocked
    assert "crowd_control" not in annul_blocked
    assert _survival(combat, "ally:Yasuo")["spell_shield_used"] is True
    # The post-window cast (shield expired at 5.0) lands normally.
    assert later["time"] == pytest.approx(12.25)
    assert later["crowd_control"]["duration"] == pytest.approx(1.8)
    assert _survival(combat, "ally:Yasuo")["action_downtime"] == pytest.approx(1.8)

    # NEW-CONTRACT: the Annul-blocked cast never reached the immunity
    # gate — the recipient's immunity receipt blocked nothing.
    cce = _require_contract()
    assert _survival(combat, "ally:Yasuo")["crowd_control_immunity"]["blocked"] == []


def test_r11b_projectile_defense_destroys_the_packet():
    """Yasuo W destroys the skillshot packet before any later gate: no
    spell-shield spend, no CC immunity decision, no downtime; the shield
    survives to block the post-window cast with Annul."""
    combat = _calculate(
        {
            **_morgana(shield_target=0, duration=14.0),
            "enemies": [_ahri_e()],
            "allies": [
                _ally(
                    "Yasuo",
                    items=["Banshee's Veil"],
                    options={
                        "w_active": True,
                        "w_active_seconds": 4.0,
                        "w_blocked_skillshots": ["E"],
                    },
                )
            ],
        }
    )
    e_events = sorted(
        _events(combat, target="ally:Yasuo", source="E"),
        key=lambda event: event["time"],
    )
    destroyed, annul_blocked = e_events
    assert destroyed["time"] == pytest.approx(0.0)
    assert destroyed["skipped_reason"] == "yasuo_wind_wall"
    assert destroyed["projectile_defense"]["mode"] == "destroyed"
    assert "crowd_control_blocked" not in destroyed
    assert "spell_shield_source" not in destroyed
    assert annul_blocked["time"] == pytest.approx(12.25)
    assert annul_blocked["skipped_reason"] == "spell_shield"
    assert annul_blocked["spell_shield_source"] == "Banshee's Veil — Annul"
    survival = _survival(combat, "ally:Yasuo")
    assert survival["spell_shield_used"] is True
    assert survival["action_downtime"] == pytest.approx(0.0)

    # NEW-CONTRACT: the destroyed packets never reached the immunity
    # gate — no immunity block was recorded.
    cce = _require_contract()
    assert survival["crowd_control_immunity"]["blocked"] == []


def test_r11c_full_blocked_packet_drops_its_cc_without_receipt():
    """A packet fully blocked by Braum E never reaches the CC gate: its
    control is dropped with NO crowd-control receipt and no downtime; the
    post-window cast lands (shield expired)."""
    combat = _calculate(
        {
            **_morgana(shield_target=0, duration=14.0),
            "enemies": [_ahri_e()],
            "allies": [
                _ally(
                    "Braum",
                    options={
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["E"],
                    },
                )
            ],
        }
    )
    e_events = sorted(
        _events(combat, target="ally:Braum", source="E"),
        key=lambda event: event["time"],
    )
    full_blocked, later = e_events
    assert full_blocked["time"] == pytest.approx(0.0)
    assert full_blocked["projectile_defense"]["mode"] == "full_block"
    assert full_blocked["damage"] == pytest.approx(0.0)
    assert "crowd_control_blocked" not in full_blocked
    assert "crowd_control" not in full_blocked
    assert later["time"] == pytest.approx(12.25)
    assert later["crowd_control"]["duration"] == pytest.approx(1.8)
    survival = _survival(combat, "ally:Braum")
    assert survival["action_downtime"] == pytest.approx(1.8)
    assert survival["crowd_control_until"] == pytest.approx(14.05)

    # NEW-CONTRACT: the full-blocked packet's CC was dropped before the
    # immunity gate — no immunity block was recorded.
    cce = _require_contract()
    assert survival["crowd_control_immunity"]["blocked"] == []


def test_r11d_stasis_blocked_packets_skip_every_later_gate():
    """Packets blocked by target stasis ('target_state_blocked') skip the
    projectile, spell-shield, and CC-immunity gates entirely: no receipts,
    no shield spend; the post-stasis cast lands."""
    combat = _calculate(
        {
            **_morgana(shield_target=0, duration=14.0),
            "enemies": [_ahri_e()],
            "allies": [
                _ally(
                    "Lux",
                    items=["Zhonya's Hourglass"],
                    item_options={"Zhonya's Hourglass": {"stasis_active_seconds": 2.5}},
                )
            ],
        }
    )
    e_events = sorted(
        _events(combat, target="ally:Lux", source="E"), key=lambda event: event["time"]
    )
    stasis_blocked, later = e_events
    assert stasis_blocked["time"] == pytest.approx(0.0)
    assert stasis_blocked["skipped_reason"] == "target_state_blocked"
    assert "crowd_control_blocked" not in stasis_blocked
    assert "crowd_control" not in stasis_blocked
    assert later["time"] == pytest.approx(12.25)
    assert later["crowd_control"]["duration"] == pytest.approx(1.8)
    survival = _survival(combat, "ally:Lux")
    intervals = survival["crowd_control_intervals"]
    assert [(entry["kind"], entry["start"], entry["end"]) for entry in intervals] == [
        ("immobilize", 12.25, 14.05)
    ]
    # 4.3 = 2.5s sourced stasis window + 1.8s landed charm; the stasis
    # packet itself added no CC receipt (it never reached the gate).
    assert survival["action_downtime"] == pytest.approx(4.3)

    # NEW-CONTRACT: nothing was blocked by immunity — the stasis packet
    # never reached the gate, so the blocked list is empty.
    cce = _require_contract()
    assert survival["crowd_control_immunity"]["blocked"] == []


def test_r11e_reduced_but_not_blocked_packet_still_hits_the_cc_gate():
    """Timeline level: after the first skillshot is fully blocked, the
    second is REDUCED by Braum E (0.55) but not destroyed — the packet's
    control still reaches the CC gate and is blocked by Black Shield (the
    reduced 90 magic is absorbed by the shield)."""
    braum = _braum_combatant()
    result, packets = _simulate(
        [
            {
                "time": 1.0,
                "damage": 200.0,
                "damage_type": "magic",
                "attacker": "enemy",
                "target": "target",
                "source_key": "Q",
                "source": "Q",
                "is_ability": True,
                "kind": "damage",
                "skillshot": True,
                "sequence": 0,
                "_event_id": "q1",
            },
            _control_packet(
                2.0,
                damage=200.0,
                sequence=1,
                source="E",
                skillshot=True,
                event_id="e1",
            ),
        ],
        [_black_shield_template()],
        combatants=[_dummy_combatant("enemy", "enemy"), braum],
    )
    first, reduced = packets
    assert first["projectile_defense"]["mode"] == "full_block"
    assert reduced["projectile_defense"]["mode"] == "reduced"
    assert reduced["projectile_defense"]["reduction"] == pytest.approx(0.55)
    assert reduced["damage"] == pytest.approx(90.0)  # 200 x 0.45
    assert reduced["crowd_control_blocked"]["source"] == "Black Shield"
    target = result["target"]
    assert target["shield_absorbed"] == pytest.approx(90.0)
    assert target["action_downtime"] == pytest.approx(0.0)

    # NEW-CONTRACT: the reduced-but-not-blocked packet reached the
    # immunity gate and the decision receipt names the reduced holder
    # amount (320 - 90 == 230 remains after this packet's damage).
    cce = _require_contract()
    decision = reduced["crowd_control_blocked"]["decision"]
    assert decision["eligible"] is True
    assert decision["shield_amount_before"] == pytest.approx(320.0)
    assert reduced["crowd_control_blocked"]["shield_amount_after"] == pytest.approx(
        230.0
    )


# ---------------------------------------------------------------------------
# R12 — receipt-versus-result parity
# ---------------------------------------------------------------------------


def test_r12_receipt_result_parity():
    """The survival rows, the per-event receipts, and the action-downtime
    total agree: every landed control has an interval and sourced
    duration; every blocked control has a blocked receipt and adds ZERO
    downtime; the new contract receipt mirrors the blocked events with
    shield amounts before/after and the immunity-ended reason."""
    combat = _calculate(
        {
            **_morgana(),
            "enemies": [
                _ahri_e(),
                _enemy("Lulu", ranks={"Q": 0, "W": 5, "E": 0, "R": 0}),
            ],
            "allies": _two_allies(),
        }
    )

    # CURRENT parity: Lux blocked both controls (zero downtime); Jinx has
    # both intervals and the merged downtime equals their sourced sum.
    lux_blocked = _cc_blocked(combat, "ally:Lux")
    assert len(lux_blocked) == 2
    assert {(event["time"], event["source"]) for event in lux_blocked} == {
        (0.0, "E"),
        (0.0, "W"),
    }
    lux = _survival(combat, "ally:Lux")
    assert lux["crowd_control_intervals"] == []
    assert lux["action_downtime"] == pytest.approx(0.0)

    jinx_applied = _cc_applied(combat, "ally:Jinx")
    assert len(jinx_applied) == 2
    jinx = _survival(combat, "ally:Jinx")
    intervals = jinx["crowd_control_intervals"]
    assert {(entry["kind"], entry["source"]) for entry in intervals} == {
        ("immobilize", "E"),
        ("polymorph", "Whimsy"),
    }
    assert jinx["action_downtime"] == pytest.approx(2.0)
    assert sum(
        event["crowd_control"]["duration"] for event in jinx_applied
    ) == pytest.approx(3.8)
    # Merged intervals: [0, 1.8] + [0, 2.0] overlap -> 2.0, not 3.8.
    assert jinx["action_downtime"] < sum(
        event["crowd_control"]["duration"] for event in jinx_applied
    )

    # NEW-CONTRACT receipt: recipient, holder source atoms, window,
    # active-until, ended reason, blocked entries, decision receipts.
    cce = _require_contract()
    receipt = lux["crowd_control_immunity"]
    assert receipt["recipient"] == "ally:Lux"
    assert receipt["shield_source"] == "Black Shield"
    assert {atom["hash"] for atom in receipt["source_atoms"]} == {
        "797fffe3046f726e",  # Magic Shield Strength
        "106f001ee676d9f2",  # shield duration
    }
    assert receipt["window"]["start"] == pytest.approx(0.0)
    assert receipt["window"]["until"] == pytest.approx(5.0)
    assert receipt["active_until"] == pytest.approx(5.0)
    assert receipt["reason_immunity_ended"] == "expired"
    # Every per-event blocked receipt is mirrored in the survival row.
    blocked_entries = receipt["blocked"]
    assert {(entry["time"], entry["source"]) for entry in blocked_entries} == {
        (event["time"], event["source"]) for event in lux_blocked
    }
    # The decisions carry the control kinds in walk order (Ahri E first).
    # A control takes effect after everything that landed at its own
    # timestamp (``TransitionRank.DEBUFF_ARM``), so Ahri's Charm resolves
    # with the damage it rides and Lulu's control-only Whimsy follows it.
    assert [entry["control_kind"] for entry in blocked_entries] == [
        "immobilize",
        "polymorph",
    ]
    # Shield amounts before/after per blocked packet.
    assert [entry["shield_amount_before"] for entry in blocked_entries] == [
        pytest.approx(320.0),
        pytest.approx(162.1),
    ]
    assert [entry["shield_amount_after"] for entry in blocked_entries] == [
        pytest.approx(162.1),
        pytest.approx(162.1),
    ]
    # Per-event decision receipts carry the same amounts.
    by_source = {
        event["source"]: event["crowd_control_blocked"] for event in lux_blocked
    }
    assert by_source["E"]["decision"]["shield_amount_before"] == pytest.approx(320.0)
    assert by_source["E"]["shield_amount_after"] == pytest.approx(162.1)
    assert by_source["W"]["decision"]["shield_amount_before"] == pytest.approx(162.1)
    assert by_source["W"]["shield_amount_after"] == pytest.approx(162.1)
    assert by_source["E"]["decision"]["control"]["kind"] == "immobilize"
    assert by_source["W"]["decision"]["control"]["kind"] == "polymorph"


# ---------------------------------------------------------------------------
# R13 — score-path fail-closed
# ---------------------------------------------------------------------------


def test_r13_score_path_represents_the_immunity_template_today():
    """The compiled score walk currently stages the Black Shield immunity
    template (unrepresentable_template_receipt -> None) and the compiler
    carries the immunity fields onto the typed SHIELD action — the
    "reproduces the decision" branch.  The contract owns a mirror gate
    (compiled_support_receipt): if the score path ever cannot reproduce
    the immunity decision, it must fail closed with a named receipt."""
    template = {
        "target": "main",
        "kind": "shield",
        "amount": 320.0,
        "duration": 5.0,
        "shield_pool": "magic",
        "crowd_control_immunity_while_shield": True,
        "crowd_control_immunity_source": "Black Shield",
        "source": "Black Shield",
        "attacker": "caster",
        "time": 0.0,
    }
    assert unrepresentable_template_receipt(template) is None

    compiler = _WalkCompiler()
    compiler.add_support_templates([template], 0, {"main": 0, "caster": 1})
    (action,) = compiler.actions
    assert action.kind is ActionKind.SHIELD
    assert action.crowd_control_immunity_while_shield is True
    assert action.crowd_control_immunity_source == "Black Shield"
    assert action.shield_pool == "magic"

    # NEW-CONTRACT: the contract-owned gate mirrors the representation
    # decision (None = the compiled walk reproduces the decision).
    cce = _require_contract()
    assert cce.compiled_support_receipt(template) is None


# ---------------------------------------------------------------------------
# R14 — non-control damage never reports a control block
# ---------------------------------------------------------------------------


def test_r14_non_control_damage_never_reports_a_control_block():
    """A damage packet with no control kind never produces a
    crowd_control_blocked receipt anywhere in the fight."""
    combat = _calculate(
        {
            **_morgana(),
            "enemies": [_enemy("Aatrox", ranks={"Q": 5, "W": 0, "E": 0, "R": 0})],
            "allies": _two_allies(),
        }
    )
    assert not any(event.get("crowd_control_blocked") for event in combat["events"])
    assert not any(event.get("crowd_control") for event in combat["events"])
    for pid in ("ally:Lux", "ally:Jinx"):
        survival = _survival(combat, pid)
        assert survival["action_downtime"] == pytest.approx(0.0)
        assert survival["crowd_control_intervals"] == []

    # NEW-CONTRACT: the recipient's immunity receipt exists but lists no
    # blocked control, and the contract never classifies the plain
    # damage packet as a control at all.
    cce = _require_contract()
    assert _survival(combat, "ally:Lux")["crowd_control_immunity"]["blocked"] == []
    profile = cce.classify_control(_CcAction(cc_kind="", damage=100.0))
    assert profile.kind == ""
    assert profile.blocking is False
    assert profile.unknown is False


def test_r14_timeline_non_control_damage_packet():
    """Timeline level: a physical damage packet without control markers
    gets no control receipts and adds no downtime."""
    packet = {
        "time": 1.0,
        "damage": 100.0,
        "damage_type": "physical",
        "attacker": "enemy",
        "target": "target",
        "source_key": "Q",
        "source": "Q",
        "is_ability": True,
        "kind": "damage",
        "sequence": 0,
        "_event_id": "q1",
    }
    result, packets = _simulate([packet], [_black_shield_template()])
    target = result["target"]
    assert target["action_downtime"] == pytest.approx(0.0)
    assert target["health_damage"] == pytest.approx(100.0)
    assert "crowd_control_blocked" not in packets[0]
    assert "crowd_control" not in packets[0]

    cce = _require_contract()
    profile = cce.classify_control(_CcAction(cc_kind="", damage=100.0))
    assert profile.kind == "" and profile.unknown is False


# ---------------------------------------------------------------------------
# R15 — physical damage never consumes the magic pool (ledger level)
# ---------------------------------------------------------------------------


def test_r15_physical_damage_never_consumes_the_magic_pool():
    """shield_ledger pool totals: a physical hit leaves the magic pool
    exactly untouched (no magic_absorbed, full pool, full health loss)."""
    pools = shield_ledger.build_pools(health=2000.0, magic_shield=320.0)
    outcome = shield_ledger.absorb(pools, 200.0, "physical", 1.0)
    assert pools.magic_shield == pytest.approx(320.0)
    assert pools.magic_absorbed == pytest.approx(0.0)
    assert pools.physical_absorbed == pytest.approx(0.0)
    assert pools.shield_absorbed == pytest.approx(0.0)
    assert outcome.applied_to_health == pytest.approx(200.0)
    assert pools.health == pytest.approx(1800.0)

    # The magic pool DOES absorb magic: the same pool drains for magic.
    outcome = shield_ledger.absorb(pools, 100.0, "magic", 2.0)
    assert pools.magic_shield == pytest.approx(220.0)
    assert pools.magic_absorbed == pytest.approx(100.0)
    assert outcome.applied_to_health == pytest.approx(0.0)

    # NEW-CONTRACT: the immunity holder reads the same ledger totals — a
    # physical hit leaves the holder's amount untouched, a magic hit
    # drains it.
    cce = _require_contract()
    timed = shield_ledger.build_pools(health=2000.0)
    shield_ledger.grant(
        timed, 320.0, pool=shield_ledger.MAGIC, expires_at=5.0, source="Black Shield"
    )
    shield_ledger.absorb(timed, 200.0, "physical", 1.0)
    holder = cce.immunity_holder(timed, "Black Shield", event_time=1.0)
    assert holder is not None
    assert holder.amount == pytest.approx(320.0)
    shield_ledger.absorb(timed, 100.0, "magic", 2.0)
    holder = cce.immunity_holder(timed, "Black Shield", event_time=2.0)
    assert holder is not None
    assert holder.amount == pytest.approx(220.0)


# ---------------------------------------------------------------------------
# R16 — one contract for damage-attached and control-only packets
# ---------------------------------------------------------------------------


def test_r16_damage_attached_and_control_only_share_one_contract():
    """Both packet kinds route through the SAME eligibility contract and
    produce identical decision receipts (modulo the packet identity)."""
    cce = _require_contract()
    eligibility = _eligibility()
    holder = _holder()

    attached = _CcAction(time=1.0, source_key="E", sequence=0, damage=100.0)
    control_only = _CcAction(
        time=1.0,
        source_key="W",
        sequence=1,
        damage=0.0,
        kind="crowd_control",
        cc_kind="polymorph",
    )

    decision_a = eligibility.decide(attached, holder=holder)
    decision_b = eligibility.decide(control_only, holder=holder)
    assert decision_a.eligible is True and decision_b.eligible is True
    assert decision_a.reason == decision_b.reason == ""
    assert decision_a.control.blocking is True and decision_b.control.blocking is True

    receipt_a = decision_a.public_receipt()
    receipt_b = decision_b.public_receipt()
    assert receipt_a["eligible"] == receipt_b["eligible"] is True
    assert receipt_a["reason"] == receipt_b["reason"] == ""
    assert receipt_a["shield_source"] == receipt_b["shield_source"] == "Black Shield"
    assert (
        receipt_a["shield_amount_before"] == receipt_b["shield_amount_before"] == 320.0
    )
    assert receipt_a["active_until"] == receipt_b["active_until"] == 5.0

    def _without_identity(receipt: dict) -> dict:
        # The packet identity and the authored kind differ by design; the
        # contract path (gate, reasons, holder fields) must be identical.
        normalized = {
            key: value for key, value in receipt.items() if key != "event_key"
        }
        normalized["control"] = {
            key: value for key, value in receipt["control"].items() if key != "kind"
        }
        return normalized

    assert _without_identity(receipt_a) == _without_identity(receipt_b)
    # The control profiles differ only in the authored kind field.
    assert receipt_a["control"]["kind"] == "stun"
    assert receipt_b["control"]["kind"] == "polymorph"


# ---------------------------------------------------------------------------
# R17 — kernel fail-closed: reason enumeration + soft control
# ---------------------------------------------------------------------------


def test_r17_kernel_decision_reasons_and_soft_control():
    """The decision reason set is exactly the named five plus ''; a known
    SOFT control (slow; silence is authored but excluded from the
    blocking set) is denied with 'control_not_blocking', never
    'unknown_control'."""
    cce = _require_contract()
    reasons: dict[str, object] = {}

    outside = _eligibility(start=0.0, until=5.0).decide(
        _CcAction(time=6.0), holder=_holder()
    )
    reasons[outside.reason] = outside

    soft = _eligibility().decide(_CcAction(cc_kind="slow"), holder=_holder())
    reasons[soft.reason] = soft

    silence = _eligibility().decide(_CcAction(cc_kind="silence"), holder=_holder())
    reasons[silence.reason] = silence

    unknown = _eligibility().decide(_CcAction(cc_kind="dance"), holder=_holder())
    reasons[unknown.reason] = unknown

    no_holder = _eligibility().decide(_CcAction(), holder=None)
    reasons[no_holder.reason] = no_holder

    eligible = _eligibility().decide(_CcAction(), holder=_holder())
    reasons[eligible.reason] = eligible

    assert set(reasons) == {
        "",
        "outside_window",
        "control_not_blocking",
        "unknown_control",
        "shield_not_held",
    }
    assert reasons[""].eligible is True
    assert all(not reasons[reason].eligible for reason in reasons if reason)
    # Soft kinds are KNOWN: silence must never fail closed as unknown.
    assert silence.control.unknown is False
    assert silence.control.blocking is False
    assert soft.control.unknown is False


# ---------------------------------------------------------------------------
# R18 — kernel fail-closed: immunity tied to the exact ledger entry
# ---------------------------------------------------------------------------


def test_r18_immunity_tied_to_the_exact_ledger_entry():
    """immunity_holder returns exactly the TimedShield entry whose source
    matches the holder source and whose amount is alive: a drained entry
    is not a holder, a different-source shield is never a holder, and a
    fresh re-grant is a NEW holder."""
    cce = _require_contract()
    pools = shield_ledger.build_pools(health=2000.0)
    shield_ledger.grant(
        pools, 320.0, pool=shield_ledger.MAGIC, expires_at=5.0, source="Black Shield"
    )
    shield_ledger.grant(
        pools,
        500.0,
        pool=shield_ledger.GENERAL,
        expires_at=4.5,
        source="Prismatic Barrier",
    )

    holder = cce.immunity_holder(pools, "Black Shield", event_time=1.0)
    assert holder is not None
    assert holder.source == "Black Shield"
    assert holder.amount == pytest.approx(320.0)
    assert holder.expires_at == pytest.approx(5.0)
    # The exact entry is the ONLY holder: the general entry never matches.
    assert cce.immunity_holder(pools, "Prismatic Barrier", event_time=1.0) is not None
    assert cce.immunity_holder(
        pools, "Black Shield", event_time=1.0
    ) is not cce.immunity_holder(pools, "Prismatic Barrier", event_time=1.0)
    assert cce.immunity_holder(pools, "Some Other Shield", event_time=1.0) is None

    # Drain the Black Shield entry: it stops being a holder even though
    # shields remain on the target.
    shield_ledger.absorb(pools, 400.0, "magic", 1.0)
    assert pools.magic_shield == pytest.approx(0.0)
    assert cce.immunity_holder(pools, "Black Shield", event_time=2.0) is None

    # A fresh grant is a NEW holder with its own identity.
    shield_ledger.grant(
        pools, 100.0, pool=shield_ledger.MAGIC, expires_at=7.0, source="Black Shield"
    )
    new_holder = cce.immunity_holder(pools, "Black Shield", event_time=2.0)
    assert new_holder is not None
    assert new_holder.amount == pytest.approx(100.0)
    assert new_holder.expires_at == pytest.approx(7.0)

    # Lifetime: an entry that has lapsed is not a holder (end exclusive).
    assert cce.immunity_holder(pools, "Black Shield", event_time=7.0) is None


# ---------------------------------------------------------------------------
# R19 — kernel fail-closed: same-hit rule unverified
# ---------------------------------------------------------------------------


def test_r19_same_hit_rule_fails_closed_until_verified():
    """same_hit_ordering() fails closed with the named
    'missing_same_hit_rule' reason while RLM-2 A has not verified the
    in-game same-hit ordering.  Once verified, the owner pins exactly one
    of R6a / R6a-alt and this row flips to assert the returned rule
    receipt instead of the raise."""
    cce = _require_contract()
    with pytest.raises(cce.MissingSameHitRuleError) as exc:
        cce.same_hit_ordering()
    assert exc.value.reason == "missing_same_hit_rule"


# ---------------------------------------------------------------------------
# R20 — kernel contract: receipt shapes
# ---------------------------------------------------------------------------


def test_r20_kernel_receipt_shapes():
    """The public receipts pin the six separation concerns: control
    classification (ControlProfile), eligibility declaration, decision
    receipt, ownership, lifetime, and ordering identity."""
    cce = _require_contract()

    # Classification: plain packet vs blocking vs unknown.
    plain = cce.classify_control(_CcAction(cc_kind=""))
    assert plain.kind == "" and plain.blocking is False and plain.unknown is False
    stun = cce.classify_control(_CcAction(cc_kind="stun"))
    assert stun.kind == "stun" and stun.blocking is True and stun.unknown is False
    assert set(stun.public_receipt()) == {
        "kind",
        "blocking",
        "unknown",
        "unknown_markers",
    }
    assert stun.public_receipt()["kind"] == "stun"

    # Eligibility declaration: name, window, holder source, source.
    eligibility = _eligibility()
    declaration = eligibility.public_receipt()
    assert set(declaration) == {"name", "window", "holder_source", "source"}
    assert declaration["name"] == "crowd_control_immunity"
    assert declaration["holder_source"] == "Black Shield"
    assert set(declaration["window"]) == {"start", "until", "source_atoms"}
    assert (
        declaration["source"]["label"]
        == "Local League Wiki cache — Morgana E Black Shield"
    )

    # Decision receipt shape.
    decision = eligibility.decide(_CcAction(), holder=_holder())
    receipt = decision.public_receipt()
    assert set(receipt) == {
        "eligible",
        "reason",
        "control",
        "shield_source",
        "shield_amount_before",
        "active_until",
        "event_key",
    }
    assert receipt["eligible"] is True
    assert receipt["reason"] == ""
    assert receipt["shield_source"] == "Black Shield"
    assert receipt["shield_amount_before"] == pytest.approx(320.0)
    assert receipt["active_until"] == pytest.approx(5.0)
    assert receipt["event_key"] == stable_event_key(_CcAction())
    assert set(receipt["control"]) == {"kind", "blocking", "unknown", "unknown_markers"}
    assert receipt["control"]["blocking"] is True
