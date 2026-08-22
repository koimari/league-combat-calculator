"""P2 Slice 4 cleanse-eligibility acceptance matrix — Mikael's Blessing / QSS / Mercurial.

This file is the RLM-2 acceptance-matrix suite for the planned orthogonal
typed cleanse contract (``src/calculator/cleanse_eligibility.py``, NEW leaf)
plus the minimal walk integration that consumes it: Mikael's Blessing
(Purify — one explicitly selected ally, incl. heal), Quicksilver Sash
(self), Mercurial Scimitar (self; movement speed = SEPARATE utility effect).
It follows the styles of ``test_crowd_control_immunity.py`` (P2 Slice 3),
``test_spell_shield_eligibility.py`` (P2 Slice 2) and
``test_survival_kernel.py``: kernel unit tests with minimal action actors,
timeline tests through ``participant_timeline._simulate_survival``, and
``src.app`` -> ``POST /api/calculate`` consumer tests.

The kernel reuses the P2 Slice 3 control classification
(``crowd_control_eligibility.classify_control`` / ``CONTROL_BLOCKING_KINDS`` /
``CONTROL_SOFT_KINDS`` / ``KNOWN_CONTROL_KINDS``), the P2 Slice 1/2
``delivery_eligibility.DefenseWindow`` + ``stable_event_key``, the
``state_lifecycle.SourceReceipt`` shape, and the survival walk's
``action_key`` total order.

SOURCED WORDING (verified from ``data/items.json`` — the ONLY source this
matrix reads; no network):

- id 3222 Mikael's Blessing, active Purify: "Remove all crowd control
  debuffs (except Airborne, Blind, Disarm, Nearsight, and Suppression) from
  yourself or the target allied champion and heal the target for 100 to
  250 (target's level)."  Excluded kinds therefore are exactly
  (airborne, blind, disarm, nearsight, suppression).  Cooldown in the
  cache is null (source gap -> ``cooldown_seconds=None``).
- id 3140 Quicksilver Sash, active Quicksilver: "Removes all crowd control
  debuffs (except Airborne) from your champion."  Excluded: (airborne).
  Cooldown null (source gap).
- id 3139 Mercurial Scimitar, active Quicksilver: "Removes all crowd
  control debuffs (except Airborne) from your champion and grants 50%
  bonus total movement speed and ghosting for 2 seconds."  Excluded:
  (airborne).  Movement: amount 50%, duration 2s, SEPARATE utility effect
  with its own atoms.  Cooldown null (source gap).

CONTRACT API THIS MATRIX COMMITS THE OWNER TO:

1. DECLARATIONS — ``cleanse_eligibility.ITEM_CLEANSE_DECLARATIONS``: one
   sourced declaration per item (Mikael's Blessing / Quicksilver Sash /
   Mercurial Scimitar) carrying: item name, active name (Purify /
   Quicksilver / Quicksilver), target scope (explicit_selected_ally /
   self), excluded control kinds (the sourced tuple, e.g. airborne,
   suppression, blind, disarm, nearsight for Mikael's), source receipts +
   source atoms, cooldown_seconds (None = source gap; the cache carries no
   cooldown for any of the three actives), the heal atom + level scaling
   (Mikael's 100-250 by target level), and the movement atom +
   amount/duration (Mercurial 50% / 2s).
2. ELIGIBILITY — ``CleanseEligibility.decide(action) -> CleanseDecision``
   with the committed reason set: "" (eligible — at least one active
   control is removed) / "control_not_active" / "excluded_control_kind" /
   "unknown_control" / "target_not_selected" / "not_armed" / "use_spent" /
   "caster_control_blocks_cleanse" (the castability denial of R7 — a
   QSS/Mercurial self-cast is denied while the CASTER's active controls
   include suppression, per the sourced cleanse atom and the binary
   cannotBeSuppressed flag).  The action carries the recipient's ACTIVE
   control intervals at activation (the walk integration passes them;
   kernel rows author them).  ``decide(action, *, holder=None)`` reads the
   holder's LIVE use state from ``holder`` (a mapping with
   ``uses_remaining`` and ``item_held``; a fresh one-use holder is assumed
   when omitted) — ``use_spent`` is decided ONLY from that live state, a
   historical (non-active) interval set is ``control_not_active``.
3. TRUNCATION — ``truncate_intervals(intervals, activation_time,
   eligible_kinds) -> (kept_intervals, removed_intervals)``: historical
   downtime before activation REMAINS (intervals with end <= activation
   are untouched); an active interval ENDS at activation (end clamped to
   activation); an interval that starts at/after activation is removed
   entirely (same-timestamp controls resolve by total order and are fully
   removed — R11/R17).  Only intervals whose kind is eligible are
   affected; unknown kinds fail closed (R15).
4. WALK INTEGRATION — the walk keeps the existing pinned ordering
   (stasis -> projectile -> spell shield -> CC immunity -> damage); a
   control blocked by a spell shield / CC immunity is NOT present at
   cleanse time (R16); a cleanse consumes one use per activation; use
   state + cooldown receipts are written.  CASTABILITY (sourced by the
   binary audit): QSS/Mercurial self-casts are exempt from the attacker
   crowd-control gate (canCastWhileDisabled=true) while the caster is
   stunned/charmed/etc. (R27) EXCEPT while the caster's active controls
   include suppression — then the cast is DENIED with the named
   caster_control_blocks_cleanse reason and the use is NOT consumed (R7);
   airborne remains an excluded control kind (R8).  Mikael's Purify
   (heal + cleanse) stays GATED while the caster is crowd-controlled —
   R21's attacker_state_blocked receipt is the pinned behavior (R22), and
   the heal fires alongside the truncation when the caster is free
   (R10/R3).
   COMMITTED CONSUMPTION + RECEIPT SEMANTICS:
   - the use is consumed ONLY for the reasons "", "control_not_active" and
     "excluded_control_kind"; "caster_control_blocks_cleanse", "use_spent",
     "not_armed", "target_not_selected" and "unknown_control" do NOT
     consume.
   - the survival-row ``cleanse_denied`` list is written ONLY for
     "use_spent"; the ``cleanse`` survival receipt is written for every
     other processed outcome ("" / control_not_active /
     excluded_control_kind / unknown_control /
     caster_control_blocks_cleanse).
   - ``fired_while_crowd_controlled`` is True when the caster was
     crowd-controlled at activation AND the activation fired (QSS /
     Mercurial self-cast, R27); False when the activation was
     gated/skipped (R22) or the caster was free.
5. RECEIPTS — the decision exposes ``public_receipt()`` (decision
   fields); the survival-row ``cleanse`` and ``cleanse_use`` receipts are
   built by ``survival.transitions`` (``_cleanse_action_view`` /
   ``_cleanse_use_receipt``
   receipt); R20 pins the exact field sets.  Per-event annotations on the
   cleanse packet mirror the removed/rejected lists.

Row status conventions (same as the P2 Slice 1/2/3 matrices):

- "CURRENT" rows assert behavior the tree already satisfies today (e.g. a
  cleanse packet today records utility and truncates nothing; Mikael's
  heals the selected ally only; QSS/Mercurial actives are rejected with a
  named 400).  The behavior assertions pass against today's walk; the
  contract-API assertions in the same row (marked ``_require_contract()``)
  fail until the kernel lands — the intended signal that the row must be
  recomposed onto the contract without changing the outcome.
- "NEW-CONTRACT" rows assert the kernel API the owner commits to.  They
  fail today with the named PENDING KERNEL marker
  (``_require_contract()``) and are reported as pending.

RLM-2 A evidence (binary audit — data/bin/items.bin.json client
16.15.8024387 + data/wiki-atoms/crowd-control-mobility.json):

- Items/Spells/QuicksilverSash.mSpell and ItemMercurial.mSpell carry
  canCastWhileDisabled=true and cannotBeSuppressed=true; Mikael's
  3222Active carries neither.  The cleanse atom states "castable while
  disabled, but not under suppression/stasis".  Sourced castability rule:
  QSS/Mercurial self-casts are exempt from the attacker crowd-control
  gate while the caster is stunned/charmed/etc. (R27) EXCEPT while the
  caster's active controls include suppression — then the cast is denied
  with the named caster_control_blocks_cleanse reason and the use is NOT
  consumed (R7 primary); Mikael's Purify stays GATED while the caster is
  crowd-controlled (R21's attacker_state_blocked is the pinned behavior —
  R22 primary; the exemption alternate is xfailed as contradicted by the
  binary evidence).
- Suppression REMOVAL set: A found no wording-level contradiction — the
  binary/atom facts concern CASTING, not the removal set.  The removal set
  (QSS/Mercurial exclude only airborne, so suppression IS in the removal
  set per their own wording) stays pinned in R4/R5; because the self-only
  cast cannot fire while the caster is suppressed, the walk-level
  observable is the castability denial of R7 (the wording-based removal
  variant is the xfailed alternate).

Matrix rows (row id | dimension | level | status | depends on):

R1  | Mikael's cleanses + heals the SELECTED ally only (other allies and the caster unaffected; enemy control lands on unselected allies) | app | CURRENT (heal + no truncation) / NEW-CONTRACT (cleanse receipt) | no
R2  | Mikael's target-choice public receipt (which ally was selected; heal + decision + use follow the selection; activation after the caster's control ends — app-level truncation is covered by R23-new) | app | CURRENT (heal follows selection) / NEW-CONTRACT (receipt) | no
R3  | Mikael's selected-ally semantics at timeline level (two allies, mid-CC activation, free caster) | timeline | NEW-CONTRACT | no
R4  | ITEM_CLEANSE_DECLARATIONS: one sourced declaration per item (name/active/scope/exclusions/cooldown/heal/movement/atoms) | kernel | NEW-CONTRACT | no
R5  | Mikael's excluded control kinds are row-specific per its wording (airborne, blind, disarm, nearsight, suppression) | kernel | NEW-CONTRACT | no
R6  | Suppression per item: Mikael's own wording excludes it -> NOT cleansed | timeline | NEW-CONTRACT | A-dependent (suppression question)
R7  | Suppression CASTABILITY per item: QSS/Mercurial self-casts are DENIED while the caster is suppressed (decision reason caster_control_blocks_cleanse; rejected control with that reason; interval untouched; use NOT consumed) — the removal SET stays pinned in R4/R5 (excluded == (airborne,)); the wording-based removal variant is the xfailed alternate | timeline | NEW-CONTRACT | no (A resolved)
R8  | Airborne per item: all three exclude airborne -> never cleansed, interval untouched | timeline | NEW-CONTRACT | no
R9  | slow/root/stun/charm/fear per sourced rules (blocking kinds removed; soft slow never creates downtime) | kernel+timeline | CURRENT (soft no-downtime) / NEW-CONTRACT (removal) | no
R10 | No active control at activation (per item: heal still fires / movement still grants / use consumed; receipt names the rule) | kernel+timeline | CURRENT (heal fires) / NEW-CONTRACT (receipts) | no
R11 | Control before / at / after activation (historical remains; active ends at activation; future removed; total order) | timeline | CURRENT (no truncation) / NEW-CONTRACT (truncation) | no
R12 | Two overlapping controls with different eligibility (stun cleansed, suppression not) | timeline | NEW-CONTRACT | no
R13 | Two controls ending at different times (only each cleansed control's own remaining tail removed) | timeline | NEW-CONTRACT | no
R14 | Repeated use and cooldown within one fight (use state; cooldown source gap fails closed) | kernel+timeline | NEW-CONTRACT | no
R15 | Unknown control kind fails closed (named reason; no truncation) | kernel+timeline | CURRENT (walk applies unknown intervals today) / NEW-CONTRACT (decision) | no
R16 | Walk order stays: stasis -> projectile -> spell shield -> CC immunity -> damage; a blocked control is NOT present at cleanse time | app+timeline | CURRENT (order) / NEW-CONTRACT (cleanse receipt) | no
R17 | Cleanse at the same timestamp as a control packet: kernel total order (stable_event_key + action_key) | kernel+timeline | NEW-CONTRACT | no
R18 | Receipt-versus-result parity: action_downtime == merged intervals; removed tails; receipts consistent | app+timeline | CURRENT (parity) / NEW-CONTRACT (cleanse receipts) | no
R19 | Score-path fail-closed: compiled walk with Mikael's/QSS/Mercurial armed | unit | CURRENT (representable today; cleanse/movement kinds rejected) / NEW-CONTRACT (named gate) | A/B-dependent
R20 | Public receipt contents (the owner's required receipt field sets) | kernel | NEW-CONTRACT | no
R21 | Caster crowd-control at activation TODAY (cleanse-kind utility rides the gate; Mikael's heal is blocked) | app+timeline | CURRENT | no
R22 | Caster crowd-control at activation (sourced castability): Mikael's Purify stays GATED (attacker_state_blocked); the caster's use receipt names the rule | timeline | NEW-CONTRACT (gated primary; exemption alternate xfailed — binary evidence) | no (A resolved)
R23 | QSS/Mercurial actives: option validation today (named 400) vs post-contract options | app | CURRENT (named 400) / NEW-CONTRACT (accepted) | no
R24 | Mercurial: self cleanse + SEPARATE movement utility effect (amount 50%, duration 2s, its own atoms) | timeline+app | CURRENT (utility recorded) / NEW-CONTRACT (atoms + grant) | no
R25 | A cleanse packet today: records utility and truncates nothing (canonical CURRENT baseline) | timeline | CURRENT | no
R26 | Support-packet arming-priority baseline: cleanse/movement ride phase 1.0 (total-order baseline) | kernel | CURRENT | no
R27 | QSS/Mercurial castability exemption: self-cast fires while the caster is stunned/charmed (exempt; truncates the caster's own interval; receipt fired_while_crowd_controlled=true) — the suppression denial is R7 (caster_control_blocks_cleanse) and airborne stays excluded_control_kind (R8) | timeline | CURRENT (packet rides the gate) / NEW-CONTRACT (truncation + receipt) | no (A resolved)
"""

from types import SimpleNamespace
from typing import Any

import pytest

from src.app import app
from src.calculator.program.build import roster_program as _roster_program
from src.calculator.program.views.survival import survival as _survival_view
from src.calculator.defensive_effects import StartingDefenses
from src.calculator import delivery_eligibility as de
from src.calculator.participant_timeline import (
    Combatant,
    _WalkCompiler,
    _simulate_survival as _simulate_survival_walk,
)
from src.calculator.state_lifecycle import SourceReceipt
from src.calculator.survival.actions import (
    ActionKind,
    TransitionRank,
    support_transition_rank,
)
from src.calculator.interpreters import uncompilable_item_receipt
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


try:  # P2 Slice 4 planned kernel — not landed yet; rows fail with the marker.
    from src.calculator import cleanse_eligibility as ce
except ImportError:  # pragma: no cover - expected until the kernel lands
    ce = None


def _require_contract():
    """Return the planned cleanse-eligibility kernel.

    The module does not exist until the RLM-1 owner lands P2 Slice 4;
    every contract-API assertion calls this so the suite collects and each
    NEW-CONTRACT row fails with the named pending-kernel marker instead of
    one collection error (the intended signal, reported to the owner)."""
    if ce is None:
        pytest.fail(
            "PENDING KERNEL: src/calculator/cleanse_eligibility.py "
            "has not landed yet; this assertion targets the P2 Slice 4 "
            "contract API and is expected to fail until the owner lands it"
        )
    return ce


# ---------------------------------------------------------------------------
# Sourced wording constants (data/items.json — read at import, no network)
# ---------------------------------------------------------------------------

MIKAELS_SOURCE = "Mikael's Blessing — Purify"
QUICKSILVER_SOURCE = "Quicksilver Sash — Quicksilver"
MERCURIAL_SOURCE = "Mercurial Scimitar — Quicksilver"

#: data/items.json id 3222 active Purify branch (templates stripped).
MIKAELS_WORDING = (
    "Remove all crowd control debuffs (except Airborne, Blind, Disarm, "
    "Nearsight, and Suppression) from yourself or the target allied "
    "champion and heal the target for 100 to 250 (target's level)."
)
#: data/items.json id 3140 active Quicksilver branch (templates stripped).
QUICKSILVER_WORDING = (
    "Removes all crowd control debuffs (except Airborne) from your champion."
)
#: data/items.json id 3139 active Quicksilver branch (templates stripped).
MERCURIAL_WORDING = (
    "Removes all crowd control debuffs (except Airborne) from your champion "
    "and grants 50% bonus total movement speed and ghosting for 2 seconds."
)

#: Atom catalog facts (data/atoms/items.json) the declarations must attach.
MIKAELS_HEAL_ATOM = {
    "atom_id": "heal.flat",
    "behavior": "heal",
    "source": "Mikael's Blessing.actives[0].branches[0]",
    "name": "Purify",
    "values": [100.0, 250.0],
    "units": ["flat", "flat"],
    "evidence": ["active:Purify@kw:heal"],
    "hash": "cf9fe930ebd40602",
}
MERCURIAL_MOVEMENT_ATOM = {
    "atom_id": "control.movement_speed",
    "behavior": "control",
    "source": "Mercurial Scimitar.actives[0].branches[0]",
    "name": "Quicksilver",
    "values": [50.0, 2.0],
    "units": ["percent", "s"],
    "evidence": ["active:Quicksilver@kw:movement speed"],
    "hash": "5e5f100f08a793f9",
}

# ---------------------------------------------------------------------------
# App-level helpers
# ---------------------------------------------------------------------------


def _calculate(payload: dict) -> dict:
    app.config["TESTING"] = True
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _calculate_status(payload: dict) -> tuple[int, dict]:
    """POST and return (status_code, json) without asserting success."""
    app.config["TESTING"] = True
    response = app.test_client().post("/api/calculate", json=payload)
    try:
        body = response.get_json()
    except Exception:  # pragma: no cover - non-JSON error bodies
        body = {}
    return response.status_code, body


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


def _support_events(combat: dict, *, source: str | None = None) -> list[dict]:
    return [
        event
        for event in combat.get("support_events", [])
        if source is None or event.get("source") == source
    ]


def _cc_applied(combat: dict, target: str) -> list[dict]:
    """Events whose control landed (action downtime added)."""
    return [
        event
        for event in combat["events"]
        if event.get("target") == target and event.get("crowd_control")
    ]


def _main(champion: str = "Lux", *, items: list[str] | None = None) -> dict:
    return {
        "champion": champion,
        "level": 18,
        "items": items or [],
        "fight_mode": "time_based",
        "fight_duration": 8.0,
        "include_auto_attacks": False,
        "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
    }


def _ally(champion: str, *, items: list[str] | None = None) -> dict:
    return {
        "champion": champion,
        "level": 18,
        "items": items or [],
        "ally_effects_enabled": True,
        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
    }


def _enemy(
    champion: str, *, ranks: dict | None = None, options: dict | None = None
) -> dict:
    card = {
        "champion": champion,
        "level": 18,
        "items": [],
        "ability_ranks": ranks or {"Q": 5, "W": 5, "E": 5, "R": 0},
    }
    if options is not None:
        card["champion_options"] = options
    return card


def _lulu_qw() -> dict:
    """Lulu: Q damage (t=0) + W polymorph (t=0.25, 2.0s) — CCs everyone.

    Whimsy has two mutually exclusive cached branches ("Self / Ally Cast"
    grants attack speed, "Enemy Cast" polymorphs), and the module prices
    only the one ``lulu_whimsy_target`` names — the default is the self
    buff, which authors no control at all.  A fixture that wants the
    polymorph has to say so, which is the point: an enemy Lulu who was
    never told to cast W at anybody no longer polymorphs the board.
    """
    return _enemy(
        "Lulu",
        ranks={"Q": 5, "W": 5, "E": 0, "R": 0},
        options={"lulu_whimsy_target": "enemy"},
    )


def _ahri_e() -> dict:
    """Ahri: E charm only (t=0, 1.8s)."""
    return _enemy("Ahri", ranks={"Q": 0, "W": 0, "E": 5, "R": 0})


# ---------------------------------------------------------------------------
# Timeline-level helpers
# ---------------------------------------------------------------------------


def _dummy_combatant(
    participant_id: str,
    team: str,
    health: float = 3000.0,
) -> Combatant:
    """Minimal combatant for timeline rows (mirrors the pinned suite)."""
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


def _control_packet(
    time: float,
    *,
    kind: str = "stun",
    duration: float = 2.0,
    source: str = "E",
    target: str = "target",
    attacker: str = "enemy",
    sequence: int = 0,
    event_id: str | None = None,
) -> dict:
    """One authored control-only incoming packet."""
    return {
        "time": time,
        "damage": 0.0,
        "damage_type": "magic",
        "attacker": attacker,
        "target": target,
        "source_key": source,
        "source": source,
        "is_ability": True,
        "kind": "crowd_control",
        "sequence": sequence,
        "_event_id": event_id or f"cc-{sequence}",
        "cc_kind": kind,
        "cc_duration": duration,
    }


def _damage_packet(
    time: float,
    amount: float,
    *,
    source: str = "Q",
    target: str = "target",
    attacker: str = "enemy",
    sequence: int = 0,
) -> dict:
    """One authored damage packet (wounds a target so heals can apply)."""
    return {
        "time": time,
        "damage": amount,
        "damage_type": "magic",
        "attacker": attacker,
        "target": target,
        "source_key": source,
        "source": source,
        "is_ability": True,
        "kind": "damage",
        "sequence": sequence,
        "_event_id": f"dmg-{sequence}",
    }


def _cleanse_packet(
    time: float,
    *,
    source: str = QUICKSILVER_SOURCE,
    target: str = "target",
    attacker: str = "caster",
    amount: float = 1.0,
    sequence: int = 0,
    event_id: str | None = None,
) -> dict:
    """One authored cleanse-kind support packet (ActionKind.UTILITY today)."""
    return {
        "time": time,
        "kind": "cleanse",
        "amount": amount,
        "attacker": attacker,
        "target": target,
        "source": source,
        "source_key": source,
        "utility_kind": "cleanse",
        "sequence": sequence,
        "_event_id": event_id or f"cleanse-{sequence}",
    }


def _purify_packet(
    time: float,
    *,
    target: str = "target",
    attacker: str = "caster",
    amount: float = 100.0,
    sequence: int = 0,
) -> dict:
    """Mikael's Purify as authored today: a heal packet + cleanse marker."""
    return {
        "time": time,
        "kind": "heal",
        "amount": amount,
        "attacker": attacker,
        "target": target,
        "source": MIKAELS_SOURCE,
        "source_key": MIKAELS_SOURCE,
        "cleanse": True,
        "sequence": sequence,
        "_event_id": f"purify-{sequence}",
    }


def _movement_packet(
    time: float,
    *,
    target: str = "target",
    attacker: str = "caster",
    amount: float = 50.0,
    duration: float = 2.0,
    sequence: int = 0,
) -> dict:
    """Mercurial's movement as a SEPARATE utility effect (own atoms)."""
    return {
        "time": time,
        "kind": "movement",
        "amount": amount,
        "duration": duration,
        "bonus_move_speed_percent": amount,
        "attacker": attacker,
        "target": target,
        "source": MERCURIAL_SOURCE,
        "source_key": MERCURIAL_SOURCE,
        "utility_kind": "movement",
        "sequence": sequence,
        "_event_id": f"movement-{sequence}",
    }


def _black_shield_template(
    time: float = 0.0, amount: float = 320.0, duration: float = 5.0
) -> dict:
    """The authored Black Shield support template (Slice 3 style)."""
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


def _spell_shield_template(time: float = 0.0, duration: float = 3.0) -> dict:
    """One timed spell-shield template (Slice 2 style, e.g. Sivir E)."""
    return {
        "time": time,
        "kind": "spell_shield",
        "duration": duration,
        "attacker": "caster",
        "source": "Spell Shield",
    }


def _simulate(
    packets: list[dict],
    supports: list[dict] | None = None,
    *,
    combatants: list[Combatant] | None = None,
    duration: float = 10.0,
) -> tuple[dict[str, dict[str, Any]], list[dict]]:
    """One timeline run; returns (survival rows, annotated packets)."""
    if combatants is None:
        combatants = [
            _dummy_combatant("enemy", "enemy"),
            _dummy_combatant("target", "main"),
            _dummy_combatant("caster", "main"),
        ]
    result = _simulate_survival(
        combatants,
        {"target": packets},
        {},
        {"target": supports or []},
        duration,
    )
    return result, packets


# ---------------------------------------------------------------------------
# Kernel-level helpers
# ---------------------------------------------------------------------------


class _CleanseAction:
    """One cleanse activation with the typed fields the contract reads."""

    def __init__(
        self,
        *,
        time: float = 1.5,
        source_key: str = QUICKSILVER_SOURCE,
        sequence: int = 0,
        event_id: str = "cleanse",
        item: str = "Quicksilver Sash",
        target: str = "target",
        holder: str = "target",
        active_controls: list[dict] | None = None,
    ) -> None:
        self.time = time
        self.source_key = source_key
        self.sequence = sequence
        self.event_id = event_id
        self.item = item
        self.target = target
        self.holder = holder
        self.active_controls = active_controls or []


def _interval(
    kind: str,
    start: float,
    end: float,
    *,
    source: str = "E",
    recipient: str = "target",
) -> dict:
    """One active-control interval (the walk's interval shape)."""
    return {
        "recipient": recipient,
        "kind": kind,
        "start": start,
        "end": end,
        "source": source,
    }


def _declaration(item: str):
    """One item's cleanse declaration from the contract registry."""
    ce = _require_contract()
    return ce.ITEM_CLEANSE_DECLARATIONS[item]


def _eligibility(item: str = "Quicksilver Sash"):
    """One contract eligibility declaration (kernel rows)."""
    ce = _require_contract()
    return ce.CleanseEligibility(
        declaration=_declaration(item),
        source=SourceReceipt(
            label="Local League Wiki cache — " + item,
            url="https://wiki.leagueoflegends.com",
        ),
    )


# ---------------------------------------------------------------------------
# R1 — Mikael's cleanses + heals the SELECTED ally only
# ---------------------------------------------------------------------------


def test_r1_mikaels_heals_the_selected_ally_only_and_truncates_nothing_today():
    """App level, CURRENT surface: the enemy control lands on EVERY friendly
    (selected ally, unselected ally, caster); Mikael's Purify activates after
    the caster's own polymorph has ended and heals the SELECTED ally only —
    the unselected ally and the caster are not healed, and NO interval is
    truncated anywhere (the cleanse marker is authored but the walk records
    the heal only).  NEW-CONTRACT: the recipient's survival row carries the
    cleanse receipt (control_not_active — the polymorph already ended at
    activation) and the caster's row carries the use-state receipt."""
    combat = _calculate(
        {
            **_main(items=["Mikael's Blessing"]),
            "item_options": {"Mikael's Blessing": {"active_seconds": 2.5}},
            "support_target_selections": {"heal:Mikael's Blessing \u2014 Purify": 0},
            "enemies": [_lulu_qw()],
            "allies": [_ally("Jinx"), _ally("Ashe")],
        }
    )

    # CURRENT behavior: heal on the selected ally only; no truncation.
    (purify,) = _support_events(combat, source=MIKAELS_SOURCE)
    assert purify["time"] == pytest.approx(2.5)
    assert purify["target"] == "ally:Jinx"
    assert purify["amount"] == pytest.approx(250.0)
    assert purify["applied_amount"] == pytest.approx(131.578947, abs=0.01)
    assert purify.get("skipped_reason") is None
    assert purify["cleanse"] is True
    assert purify["target_selection_key"] == "heal:Mikael's Blessing \u2014 Purify"

    jinx = _survival(combat, "ally:Jinx")
    ashe = _survival(combat, "ally:Ashe")
    main = _survival(combat, "main")
    assert jinx["healing_received"] == pytest.approx(131.6)
    assert ashe["healing_received"] == pytest.approx(0.0)
    assert main["healing_received"] == pytest.approx(0.0)
    for row in (jinx, ashe, main):
        assert row["action_downtime"] == pytest.approx(2.0)
        assert [
            (i["kind"], i["start"], i["end"]) for i in row["crowd_control_intervals"]
        ] == [("polymorph", 0.25, 2.25)]
    # The heal-kind Purify counts as a cleanse utility event (P3 package
    # 3G): the packet carries the ``cleanse`` marker, so the utility panel
    # reports it alongside dedicated kind=="cleanse" packets.
    outcomes = combat["utility_outcomes"]["participants"]["main"]
    assert outcomes["cleanse"]["event_count"] == 1

    # NEW-CONTRACT: recipient cleanse receipt + caster use-state receipt.
    ce = _require_contract()
    receipt = jinx["cleanse"]
    assert receipt["item"] == "Mikael's Blessing"
    assert receipt["target"] == "ally:Jinx"
    assert receipt["activation_time"] == pytest.approx(2.5)
    assert receipt["decision"]["reason"] == "control_not_active"
    assert receipt["removed_controls"] == []
    assert receipt["rejected_controls"] == []
    assert receipt["downtime_before"] == pytest.approx(2.0)
    assert receipt["downtime_after"] == pytest.approx(2.0)
    assert [i["kind"] for i in receipt["intervals_after"]] == ["polymorph"]
    heal_entry = receipt["heal"]
    assert heal_entry["amount"] == pytest.approx(250.0)
    assert heal_entry["source"] == MIKAELS_SOURCE
    assert {atom["hash"] for atom in heal_entry["source_atoms"]} == {
        "cf9fe930ebd40602"  # heal.flat Purify 100-250 (data/atoms/items.json 3222)
    }
    # The unselected ally has no cleanse receipt; the caster consumed a use.
    assert "cleanse" not in ashe
    use = main["cleanse_use"]
    assert use["item"] == "Mikael's Blessing"
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0
    assert use["cooldown_seconds"] is None
    assert use["cooldown_source_gap"] is True


# ---------------------------------------------------------------------------
# R2 — Mikael's target-choice public receipt (selected ally only)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "selected,selected_ally,other_ally",
    [(0, "ally:Jinx", "ally:Ashe"), (1, "ally:Ashe", "ally:Jinx")],
)
def test_r2_mikaels_target_choice_receipt_follows_the_selection(
    selected, selected_ally, other_ally
):
    """App level, CURRENT + NEW-CONTRACT: with Mikael's Purify GATED while
    the caster is crowd-controlled (R22 — binary evidence: 3222Active has
    no canCastWhileDisabled), the app-level activation fires only AFTER the
    caster's own polymorph has ended (active_seconds=3.0 > polymorph
    [0.25, 2.25]).  The target-choice receipt names the SELECTED ally; the
    heal and the decision follow the selection — the unselected ally gets
    no cleanse receipt and no heal.  With no control active at activation
    the decision is control_not_active and the use is consumed; app-level
    TRUNCATION is covered by R23-new's QSS/Mercurial self-cast (R27)."""
    payload = {
        **_main(items=["Mikael's Blessing"]),
        "item_options": {"Mikael's Blessing": {"active_seconds": 3.0}},
        "support_target_selections": {"heal:Mikael's Blessing — Purify": selected},
        "enemies": [_lulu_qw()],
        "allies": [_ally("Jinx"), _ally("Ashe")],
    }
    combat = _calculate(payload)

    # CURRENT behavior: the heal fires at 3.0 (caster free) on the selected
    # ally only; nothing is truncated anywhere.
    (purify,) = _support_events(combat, source=MIKAELS_SOURCE)
    assert purify["time"] == pytest.approx(3.0)
    assert purify["target"] == selected_ally
    assert purify["amount"] == pytest.approx(250.0)
    assert purify.get("skipped_reason") is None
    selected_row = _survival(combat, selected_ally)
    other_row = _survival(combat, other_ally)
    assert selected_row["healing_received"] == pytest.approx(131.6)
    assert other_row["healing_received"] == pytest.approx(0.0)
    assert selected_row["action_downtime"] == pytest.approx(2.0)
    assert other_row["action_downtime"] == pytest.approx(2.0)

    # NEW-CONTRACT: the receipt names the selected ally; the other ally has
    # none; the caster consumed exactly one use.
    ce = _require_contract()
    receipt = selected_row["cleanse"]
    assert receipt["item"] == "Mikael's Blessing"
    assert receipt["target"] == selected_ally
    assert receipt["activation_time"] == pytest.approx(3.0)
    assert receipt["decision"]["reason"] == "control_not_active"
    assert receipt["removed_controls"] == []
    assert receipt["rejected_controls"] == []
    assert receipt["downtime_before"] == pytest.approx(2.0)
    assert receipt["downtime_after"] == pytest.approx(2.0)
    assert receipt["heal"]["amount"] == pytest.approx(250.0)
    assert "cleanse" not in other_row
    use = _survival(combat, "main")["cleanse_use"]
    assert use["item"] == "Mikael's Blessing"
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0


# ---------------------------------------------------------------------------
# R3 — Mikael's selected-ally semantics at timeline level
# ---------------------------------------------------------------------------


def test_r3_mikaels_truncates_only_the_selected_allys_interval():
    """Timeline level, NEW-CONTRACT: two allies both stunned; a free caster
    casts Purify (heal + cleanse marker) on ally:one mid-stun.  The heal
    applies to ally:one (CURRENT — heals land on a CC'd recipient), and the
    contract truncates ONLY ally:one's interval; ally:two's interval is
    untouched."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("ally:one", "main"),
        _dummy_combatant("ally:two", "main"),
        _dummy_combatant("caster", "main"),
    ]
    incoming = {
        "ally:one": [
            _damage_packet(0.5, 500.0, source="Q", target="ally:one"),
            _control_packet(1.0, duration=2.0, source="E", target="ally:one"),
        ],
        "ally:two": [_control_packet(1.0, duration=2.0, source="E", target="ally:two")],
    }
    support_effects = {
        "ally:one": [
            _purify_packet(1.5, target="ally:one", attacker="caster", amount=100.0)
        ]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)

    # CURRENT behavior: the heal applies to the CC'd recipient; the cleanse
    # marker truncates nothing.
    one = result["ally:one"]
    # CURRENT: the heal applies to the CC'd recipient; the unselected ally
    # keeps its full interval (the selected ally's truncation is the NEW
    # part below).
    assert one["healing_received"] == pytest.approx(100.0)
    assert result["ally:two"]["action_downtime"] == pytest.approx(2.0)

    # NEW-CONTRACT: only ally:one's interval is truncated.
    ce = _require_contract()
    receipt = one["cleanse"]
    assert receipt["target"] == "ally:one"
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"] == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(1.5),
            "end": pytest.approx(3.0),
            "reason": "",
        }
    ]
    assert [(i["kind"], i["start"], i["end"]) for i in receipt["intervals_after"]] == [
        ("stun", 1.0, 1.5)
    ]
    assert receipt["heal"]["amount"] == pytest.approx(100.0)
    assert one["action_downtime"] == pytest.approx(0.5)
    assert [
        (i["kind"], i["start"], i["end"]) for i in one["crowd_control_intervals"]
    ] == [("stun", 1.0, 1.5)]
    two = result["ally:two"]
    assert "cleanse" not in two
    assert [
        (i["kind"], i["start"], i["end"]) for i in two["crowd_control_intervals"]
    ] == [("stun", 1.0, 3.0)]


# ---------------------------------------------------------------------------
# R4 — ITEM_CLEANSE_DECLARATIONS: one sourced declaration per item
# ---------------------------------------------------------------------------


def test_r4_cleanse_declarations_three_sourced_items():
    """Kernel, NEW-CONTRACT: exactly three sourced declarations with the
    committed fields — item name, active name, target scope, excluded kinds,
    cooldown (None = source gap), heal (Mikael's), movement (Mercurial),
    source receipts and atoms."""
    ce = _require_contract()
    decls = ce.ITEM_CLEANSE_DECLARATIONS
    assert set(decls) == {"Mikael's Blessing", "Quicksilver Sash", "Mercurial Scimitar"}

    mikaels = decls["Mikael's Blessing"]
    assert mikaels["item"] == "Mikael's Blessing"
    assert mikaels["active_name"] == "Purify"
    assert mikaels["target_scope"] == "explicit_selected_ally"
    assert mikaels["excluded_control_kinds"] == (
        "airborne",
        "blind",
        "disarm",
        "nearsight",
        "suppression",
    )
    assert mikaels["cooldown_seconds"] is None  # items.json active cooldown null
    assert mikaels["cooldown_source_gap"] is True
    heal = mikaels["heal"]
    assert heal["amount_min"] == pytest.approx(100.0)
    assert heal["amount_max"] == pytest.approx(250.0)
    assert heal["scaling"] == "target_level"
    assert any(atom["hash"] == "cf9fe930ebd40602" for atom in heal["source_atoms"])
    assert mikaels["movement"] is None
    assert mikaels["source_receipts"]
    assert any("3222" in str(receipt) for receipt in mikaels["source_receipts"])

    qss = decls["Quicksilver Sash"]
    assert qss["item"] == "Quicksilver Sash"
    assert qss["active_name"] == "Quicksilver"
    assert qss["target_scope"] == "self"
    assert qss["excluded_control_kinds"] == ("airborne",)
    assert qss["cooldown_seconds"] is None
    assert qss["cooldown_source_gap"] is True
    assert qss["heal"] is None
    assert qss["movement"] is None
    assert any("3140" in str(receipt) for receipt in qss["source_receipts"])

    mercurial = decls["Mercurial Scimitar"]
    assert mercurial["item"] == "Mercurial Scimitar"
    assert mercurial["active_name"] == "Quicksilver"
    assert mercurial["target_scope"] == "self"
    assert mercurial["excluded_control_kinds"] == ("airborne",)
    assert mercurial["cooldown_seconds"] is None
    assert mercurial["cooldown_source_gap"] is True
    movement = mercurial["movement"]
    assert movement["amount"] == pytest.approx(50.0)
    assert movement["duration"] == pytest.approx(2.0)
    assert any(atom["hash"] == "5e5f100f08a793f9" for atom in movement["source_atoms"])
    assert any("3139" in str(receipt) for receipt in mercurial["source_receipts"])


# ---------------------------------------------------------------------------
# R5 — Mikael's excluded control kinds are row-specific per its wording
# ---------------------------------------------------------------------------


def test_r5_mikaels_excluded_kinds_per_sourced_wording():
    """Kernel, NEW-CONTRACT: each of the five kinds the Purify branch names
    (Airborne, Blind, Disarm, Nearsight, Suppression) is excluded for
    Mikael's and only for Mikael's; the wording receipt cites the branch."""
    ce = _require_contract()
    mikaels = ce.ITEM_CLEANSE_DECLARATIONS["Mikael's Blessing"]
    assert mikaels["excluded_control_kinds"] == (
        "airborne",
        "blind",
        "disarm",
        "nearsight",
        "suppression",
    )
    # Row-specific: QSS/Mercurial exclude ONLY airborne.
    for item in ("Quicksilver Sash", "Mercurial Scimitar"):
        assert ce.ITEM_CLEANSE_DECLARATIONS[item]["excluded_control_kinds"] == (
            "airborne",
        )
    # The declaration's source receipt reproduces the cached branch wording.
    assert any(
        MIKAELS_WORDING in str(receipt) for receipt in mikaels["source_receipts"]
    )
    assert any(
        QUICKSILVER_WORDING in str(receipt)
        for receipt in ce.ITEM_CLEANSE_DECLARATIONS["Quicksilver Sash"][
            "source_receipts"
        ]
    )
    assert any(
        MERCURIAL_WORDING in str(receipt)
        for receipt in ce.ITEM_CLEANSE_DECLARATIONS["Mercurial Scimitar"][
            "source_receipts"
        ]
    )
    # Blind/disarm are known SOFT kinds (never add downtime) and nearsight
    # is not even in the known set — the exclusion stays sourced per item.
    from src.calculator.crowd_control_eligibility import classify_control

    assert classify_control(SimpleNamespace(cc_kind="blind")).unknown is False
    assert classify_control(SimpleNamespace(cc_kind="nearsight")).unknown is True


# ---------------------------------------------------------------------------
# R6 — Suppression per item: Mikael's own wording excludes it
# ---------------------------------------------------------------------------


def test_r6_mikaels_does_not_cleanse_suppression():
    """Timeline level, NEW-CONTRACT: with a stun AND a suppression both
    active, Purify removes the stun (eligible) but the suppression interval
    survives — the rejection is receipted with the named
    excluded_control_kind reason.  A-dependent: the cached item wording
    (id 3222, 'except ... Suppression') is the pin; if RLM-2 A's audit of
    the removable-CC list contradicts it, the owner flips this row."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
        _dummy_combatant("caster", "main"),
    ]
    incoming = {
        "target": [
            _control_packet(1.0, duration=2.0, source="E", kind="stun"),
            _control_packet(1.5, duration=2.0, source="R", kind="suppression"),
        ]
    }
    support_effects = {
        "target": [_purify_packet(2.0, target="target", attacker="caster")]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    # CURRENT: no truncation anywhere.
    assert result["target"]["action_downtime"] == pytest.approx(2.5)

    # NEW-CONTRACT: stun removed, suppression rejected and preserved.
    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"] == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(2.0),
            "end": pytest.approx(3.0),
            "reason": "",
        }
    ]
    assert receipt["rejected_controls"] == [
        {
            "control_kind": "suppression",
            "source": "R",
            "start": pytest.approx(1.5),
            "end": pytest.approx(3.5),
            "reason": "excluded_control_kind",
        }
    ]
    kept = result["target"]["crowd_control_intervals"]
    assert [(i["kind"], i["start"], i["end"]) for i in kept] == [
        ("stun", 1.0, 2.0),
        ("suppression", 1.5, 3.5),
    ]
    # The suppression's own downtime contribution is untouched.
    assert result["target"]["action_downtime"] == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# R7 — Suppression per item: QSS/Mercurial wording excludes only Airborne
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "item,source",
    [
        ("Quicksilver Sash", QUICKSILVER_SOURCE),
        ("Mercurial Scimitar", MERCURIAL_SOURCE),
    ],
)
def test_r7_qss_and_mercurial_self_cast_denied_while_suppressed(item, source):
    """Timeline level, NEW-CONTRACT (PRIMARY, castability): the binary
    evidence (QuicksilverSash.mSpell / ItemMercurial.mSpell carry
    cannotBeSuppressed=true) and the cleanse atom ("castable while disabled,
    but not under suppression/stasis") settle CASTING: a self-only item
    cannot be cast while the caster is suppressed (caster == suppressed
    target), so the self-cast at 1.5 is DENIED with the named
    caster_control_blocks_cleanse reason, the suppression interval is
    untouched, and the use is NOT consumed.  The wording-based removal
    variant is the xfailed alternate; the removal SET stays pinned in
    R4/R5 (excluded_control_kinds == ("airborne",))."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    incoming = {
        "target": [_control_packet(1.0, duration=2.0, source="R", kind="suppression")]
    }
    support_effects = {
        "target": [
            _cleanse_packet(1.5, source=source, target="target", attacker="target")
        ]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    # CURRENT: the packet rides the gate today (applied as utility) and the
    # interval stands.
    (cleanse,) = support_effects["target"]
    assert cleanse.get("skipped_reason") is None
    assert result["target"]["action_downtime"] == pytest.approx(2.0)

    # NEW-CONTRACT: the castability denial is the observable behavior.
    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["item"] == item
    assert receipt["decision"]["reason"] == "caster_control_blocks_cleanse"
    assert receipt["removed_controls"] == []
    assert receipt["rejected_controls"] == [
        {
            "control_kind": "suppression",
            "source": "R",
            "start": pytest.approx(1.0),
            "end": pytest.approx(3.0),
            "reason": "caster_control_blocks_cleanse",
        }
    ]
    assert result["target"]["crowd_control_intervals"][0]["end"] == pytest.approx(3.0)
    assert result["target"]["action_downtime"] == pytest.approx(2.0)
    # Use NOT consumed (caster_control_blocks_cleanse does not consume).
    use = result["target"]["cleanse_use"]
    assert use["uses_before"] == 1
    assert use["uses_after"] == 1
    # The removal SET (per the item wording) stays pinned in the declaration.
    assert ce.ITEM_CLEANSE_DECLARATIONS[item]["excluded_control_kinds"] == ("airborne",)


# NOTE: the alternate suppression-removal variant (self-cast removes
# suppression per the raw item wording) was removed here — it is not a
# reachable branch, not just an unpinned one.  The binary evidence
# (QuicksilverSash.mSpell / ItemMercurial.mSpell cannotBeSuppressed=true)
# means a self-only QSS/Mercurial cast can never fire while its own caster
# is suppressed, so the wording-based removal path above is contradicted by
# the sourced castability rule, not merely untested.  The PRIMARY variant
# directly above (test_r7_qss_and_mercurial_self_cast_denied_while_suppressed)
# already pins the chosen branch: decision.reason ==
# "caster_control_blocks_cleanse", the suppression interval survives
# untouched, the use is not consumed, and excluded_control_kinds ==
# ("airborne",) is asserted from the same declaration the alt row would
# have re-read. Nothing about the primary/removal-set claim is lost.


# ---------------------------------------------------------------------------
# R8 — Airborne per item: all three exclude airborne
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "item,packet_builder",
    [
        ("Mikael's Blessing", _purify_packet),
        ("Quicksilver Sash", _cleanse_packet),
        ("Mercurial Scimitar", _cleanse_packet),
    ],
)
def test_r8_airborne_is_never_cleansed(item, packet_builder):
    """Timeline level, NEW-CONTRACT: every item's sourced wording excludes
    airborne, so an active airborne interval always survives the cleanse —
    rejected with the named excluded_control_kind reason, never truncated."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
        _dummy_combatant("caster", "main"),
    ]
    incoming = {
        "target": [_control_packet(1.0, duration=2.0, source="Q", kind="airborne")]
    }
    if item == "Mikael's Blessing":
        activation = packet_builder(1.5, target="target", attacker="caster")
    else:
        activation = packet_builder(
            1.5,
            target="target",
            attacker="target",
            source=(
                MERCURIAL_SOURCE if item == "Mercurial Scimitar" else QUICKSILVER_SOURCE
            ),
        )
    support_effects = {"target": [activation]}
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    assert result["target"]["action_downtime"] == pytest.approx(2.0)

    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["item"] == item
    assert receipt["removed_controls"] == []
    assert receipt["rejected_controls"] == [
        {
            "control_kind": "airborne",
            "source": "Q",
            "start": pytest.approx(1.0),
            "end": pytest.approx(3.0),
            "reason": "excluded_control_kind",
        }
    ]
    assert result["target"]["crowd_control_intervals"][0]["end"] == pytest.approx(3.0)
    assert result["target"]["action_downtime"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# R9 — slow/root/stun/charm/fear per sourced rules
# ---------------------------------------------------------------------------


def test_r9_soft_slow_never_creates_downtime_and_blocking_kinds_are_removed():
    """Kernel + timeline: slow is a known SOFT kind — a slow-only packet
    adds no interval and no downtime today (CURRENT), and since no interval
    exists the cleanse receipt names control_not_active (NEW-CONTRACT);
    root/stun/charm/fear are blocking kinds the declarations remove."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
        _dummy_combatant("caster", "main"),
    ]
    incoming = {"target": [_control_packet(1.0, duration=2.0, source="W", kind="slow")]}
    support_effects = {
        "target": [_cleanse_packet(1.5, target="target", attacker="target")]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    # CURRENT: the slow-only control adds no interval and no downtime.
    assert result["target"]["crowd_control_intervals"] == []
    assert result["target"]["action_downtime"] == pytest.approx(0.0)

    # NEW-CONTRACT: nothing to remove — the receipt names the rule.
    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == "control_not_active"
    assert receipt["removed_controls"] == []

    # Kernel: the blocking kinds Mikael's/QSS/Mercurial remove per the
    # sourced wording (none is excluded) — an active interval of each kind
    # is eligible and truncated; slow is known, never unknown.
    for kind in ("root", "stun", "charm", "fear"):
        action = _CleanseAction(active_controls=[_interval(kind, 1.0, 3.0)])
        decision = _eligibility("Quicksilver Sash").decide(action)
        assert decision.eligible is True, kind
        assert decision.reason == "", kind
        kept, removed = ce.truncate_intervals([_interval(kind, 1.0, 3.0)], 1.5, {kind})
        assert kept == [_interval(kind, 1.0, 1.5)]
        assert removed == [_interval(kind, 1.5, 3.0)]
    for item in ("Mikael's Blessing", "Quicksilver Sash", "Mercurial Scimitar"):
        for kind in ("root", "stun", "charm", "fear", "slow"):
            assert (
                kind not in ce.ITEM_CLEANSE_DECLARATIONS[item]["excluded_control_kinds"]
            )


# ---------------------------------------------------------------------------
# R10 — No active control at activation
# ---------------------------------------------------------------------------


def test_r10_no_active_control_qss_use_consumed_receipt_names_the_rule():
    """Kernel + timeline: with no active control at activation the cleanse
    is still usable — the use is consumed, the cooldown receipt is written
    (cooldown is a source gap -> fail-closed receipt), and the decision
    names control_not_active.  The receipt must name the rule; the pinned
    rule is that an activation always consumes the use (in-game activating
    QSS with nothing to remove still starts the cooldown)."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    support_effects = {
        "target": [_cleanse_packet(1.5, target="target", attacker="target")]
    }
    result = _simulate_survival(combatants, {}, {}, support_effects, 10.0)
    assert result["target"]["action_downtime"] == pytest.approx(0.0)

    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == "control_not_active"
    assert receipt["use_consumed"] is True
    assert receipt["removed_controls"] == []
    use = result["target"]["cleanse_use"]
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0
    assert use["cooldown_seconds"] is None
    assert use["cooldown_source_gap"] is True

    # Kernel decision: the named reason for an empty active set.
    decision = _eligibility("Quicksilver Sash").decide(_CleanseAction())
    assert decision.eligible is False
    assert decision.reason == "control_not_active"


def test_r10_no_active_control_mikaels_heal_still_fires():
    """Timeline: with no active control, Purify's heal still fires
    (CURRENT — the heal is unconditional in the item wording) and the
    contract receipt attaches the heal while naming control_not_active."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
        _dummy_combatant("caster", "main"),
    ]
    incoming = {"target": [_damage_packet(0.5, 500.0, target="target")]}
    support_effects = {
        "target": [
            _purify_packet(1.5, target="target", attacker="caster", amount=100.0)
        ]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    # CURRENT: the heal applies with no control present.
    assert result["target"]["healing_received"] == pytest.approx(100.0)
    assert result["target"]["action_downtime"] == pytest.approx(0.0)

    # NEW-CONTRACT: control_not_active decision + heal entry.
    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == "control_not_active"
    assert receipt["heal"]["amount"] == pytest.approx(100.0)
    assert receipt["heal"]["source"] == MIKAELS_SOURCE


def test_r10_no_active_control_mercurial_movement_still_grants():
    """Timeline: with no active control, Mercurial's movement utility still
    grants (CURRENT — recorded as a movement utility packet) and the
    contract receipt attaches the movement entry while naming
    control_not_active."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    support_effects = {
        "target": [
            _cleanse_packet(
                1.5, source=MERCURIAL_SOURCE, target="target", attacker="target"
            ),
            _movement_packet(1.5, target="target", attacker="target"),
        ]
    }
    result = _simulate_survival(combatants, {}, {}, support_effects, 10.0)
    assert result["target"]["action_downtime"] == pytest.approx(0.0)

    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == "control_not_active"
    movement = receipt["movement"]
    assert movement["amount"] == pytest.approx(50.0)
    assert movement["duration"] == pytest.approx(2.0)
    assert movement["source"] == MERCURIAL_SOURCE
    assert {atom["hash"] for atom in movement["source_atoms"]} == {
        "5e5f100f08a793f9"  # control.movement_speed 50%/2s (items.json 3139)
    }


# ---------------------------------------------------------------------------
# R11 — Control before / at / after activation
# ---------------------------------------------------------------------------


def test_r11_control_before_at_and_after_activation():
    """Timeline: historical downtime before activation REMAINS counted, the
    active interval ENDS at activation, a control landing AT activation is
    removed entirely (its packet resolves before the cleanse in the walk's
    total order), and a control landing AFTER activation applies in full.
    CURRENT: the walk truncates nothing (all four intervals stand)."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    incoming = {
        "target": [
            # A: ends before activation -> historical, remains.
            _control_packet(0.5, duration=1.0, source="A", kind="stun", sequence=0),
            # B: active at activation -> clamped.
            _control_packet(1.0, duration=2.5, source="B", kind="stun", sequence=1),
            # C: lands AT activation -> removed entirely.
            _control_packet(2.0, duration=2.0, source="C", kind="stun", sequence=2),
            # D: lands after activation -> applies in full.
            _control_packet(3.0, duration=1.0, source="D", kind="stun", sequence=3),
        ]
    }
    support_effects = {
        "target": [_cleanse_packet(2.0, target="target", attacker="target")]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    # NEW-CONTRACT: A remains [0.5,1.5]; B clamped [1.0,2.0]; C removed;
    # D applies [3.0,4.0].
    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["activation_time"] == pytest.approx(2.0)
    assert receipt["decision"]["reason"] == ""
    assert receipt["downtime_before"] == pytest.approx(3.5)
    kept = receipt["intervals_after"]
    assert [(i["source"], i["start"], i["end"]) for i in kept] == [
        ("A", 0.5, 1.5),
        ("B", 1.0, 2.0),
        ("D", 3.0, 4.0),
    ]
    assert receipt["downtime_after"] == pytest.approx(2.5)
    removed_by_source = {
        i["source"]: (i["start"], i["end"]) for i in receipt["removed_controls"]
    }
    assert removed_by_source == {
        "B": (pytest.approx(2.0), pytest.approx(3.5)),
        "C": (pytest.approx(2.0), pytest.approx(4.0)),
    }
    assert result["target"]["action_downtime"] == pytest.approx(2.5)
    assert [
        (i["source"], i["start"], i["end"])
        for i in result["target"]["crowd_control_intervals"]
    ] == [("A", 0.5, 1.5), ("B", 1.0, 2.0), ("D", 3.0, 4.0)]


# ---------------------------------------------------------------------------
# R12 — Two overlapping controls with different eligibility
# ---------------------------------------------------------------------------


def test_r12_overlapping_stun_and_suppression_only_stun_truncated():
    """Timeline, NEW-CONTRACT: an overlapping stun + suppression, both
    ACTIVE at activation; Mikael's removes the stun's remaining interval
    while the suppression (excluded) is untouched — the receipt lists the
    removed tail and the rejected suppression with its reason, and the
    survival downtime equals the merged kept intervals."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
        _dummy_combatant("caster", "main"),
    ]
    incoming = {
        "target": [
            _control_packet(1.0, duration=2.0, source="E", kind="stun"),
            _control_packet(1.5, duration=1.25, source="R", kind="suppression"),
        ]
    }
    support_effects = {
        "target": [_purify_packet(2.5, target="target", attacker="caster")]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"] == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(2.5),
            "end": pytest.approx(3.0),
            "reason": "",
        }
    ]
    assert receipt["rejected_controls"] == [
        {
            "control_kind": "suppression",
            "source": "R",
            "start": pytest.approx(1.5),
            "end": pytest.approx(2.75),
            "reason": "excluded_control_kind",
        }
    ]
    kept = result["target"]["crowd_control_intervals"]
    assert [(i["kind"], i["start"], i["end"]) for i in kept] == [
        ("stun", 1.0, 2.5),
        ("suppression", 1.5, 2.75),
    ]
    # Downtime = merged kept intervals (the overlap hides part of the tail).
    assert result["target"]["action_downtime"] == pytest.approx(1.75)
    assert receipt["downtime_before"] == pytest.approx(2.0)
    assert receipt["downtime_after"] == pytest.approx(1.75)


# ---------------------------------------------------------------------------
# R13 — Two controls ending at different times
# ---------------------------------------------------------------------------


def test_r13_two_controls_ending_at_different_times_each_tail_removed():
    """Timeline, NEW-CONTRACT: two eligible controls (stun, root) active at
    activation and ending at different times; each control's OWN remaining
    interval is removed (the root's longer tail is fully removed — not
    clamped to the stun's end), the receipts list both tails, and the
    survival downtime is the merged kept set."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
        _dummy_combatant("caster", "main"),
    ]
    incoming = {
        "target": [
            _control_packet(1.0, duration=2.0, source="E", kind="stun"),
            _control_packet(2.0, duration=2.0, source="Q", kind="root"),
        ]
    }
    support_effects = {
        "target": [_purify_packet(2.5, target="target", attacker="caster")]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)

    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"] == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(2.5),
            "end": pytest.approx(3.0),
            "reason": "",
        },
        {
            "control_kind": "root",
            "source": "Q",
            "start": pytest.approx(2.5),
            "end": pytest.approx(4.0),
            "reason": "",
        },
    ]
    assert receipt["rejected_controls"] == []
    kept = result["target"]["crowd_control_intervals"]
    assert [(i["kind"], i["start"], i["end"]) for i in kept] == [
        ("stun", 1.0, 2.5),
        ("root", 2.0, 2.5),
    ]
    assert result["target"]["action_downtime"] == pytest.approx(1.5)
    assert receipt["downtime_after"] == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# R14 — Repeated use and cooldown within one fight
# ---------------------------------------------------------------------------


def test_r14_repeated_use_second_activation_fails_closed():
    """Timeline + kernel, NEW-CONTRACT: one use per item per fight; the
    second activation is denied with the named use_spent reason and the
    cooldown receipt names the source gap (items.json carries no cooldown
    for any of the three actives — the kernel must not invent one)."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    incoming = {"target": [_control_packet(1.0, duration=2.0, source="E", kind="stun")]}
    support_effects = {
        "target": [
            _cleanse_packet(1.5, target="target", attacker="target", sequence=0),
            _cleanse_packet(2.0, target="target", attacker="target", sequence=1),
        ]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)

    ce = _require_contract()
    # First activation truncates; the second is denied and truncates nothing.
    first = result["target"]["cleanse"]
    assert first["decision"]["reason"] == ""
    assert first["use_consumed"] is True
    assert [
        (i["kind"], i["start"], i["end"])
        for i in result["target"]["crowd_control_intervals"]
    ] == [("stun", 1.0, 1.5)]
    use = result["target"]["cleanse_use"]
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0
    assert use["activations"] == 2
    assert use["cooldown_seconds"] is None
    assert use["cooldown_source_gap"] is True
    # The second activation's denial is receipted (walk-level) and the
    # kernel decision names the spent use.
    assert result["target"]["cleanse_denied"] == [
        {"time": pytest.approx(2.0), "reason": "use_spent"}
    ]
    # Kernel: use_spent is decided ONLY from the holder's live use state —
    # a fully-historical interval with a fresh one-use holder is
    # control_not_active (the use is still consumed); with
    # holder uses_remaining == 0 the decision is use_spent and does NOT
    # consume.
    decision = _eligibility("Quicksilver Sash").decide(
        _CleanseAction(time=2.0, active_controls=[_interval("stun", 1.0, 1.5)])
    )
    assert decision.eligible is False
    assert decision.reason == "control_not_active"
    spent = _eligibility("Quicksilver Sash").decide(
        _CleanseAction(time=2.0, active_controls=[_interval("stun", 1.0, 1.5)]),
        holder={"uses_remaining": 0},
    )
    assert spent.eligible is False
    assert spent.reason == "use_spent"
    assert spent.public_receipt()["use_consumed"] is False


# ---------------------------------------------------------------------------
# R15 — Unknown control kind fails closed
# ---------------------------------------------------------------------------


def test_r15_unknown_control_kind_is_refused_by_the_closed_vocabulary():
    """Kernel + timeline: what an *unknown* control kind means here.

    The merge ruling: ours keeps the closed ``ability_spec.CC_KIND_VOCABULARY``
    and ``trigger_stream`` raises on anything outside it, because a misspelled
    kind must never author a no-op control.  So a ``'dance'`` packet can no
    longer reach the walk at all -- the branch main's version of this test
    drove (apply the interval, then deny the cleanse with ``unknown_control``)
    is unreachable *through the timeline*, and asserting it there would pin a
    fail-open path this tree does not have.

    Three halves, at the two seams that still exist:

    * the timeline refuses the kind by name (ours' ruling);
    * ``classify_control`` and the cleanse eligibility still answer
      ``unknown`` for a kind handed straight to them -- they are pure
      classifiers with no engine in front, and "an unknown control is not
      cleansable and truncates nothing" is still their contract;
    * a real non-blocking vocabulary kind (``slow``) carries the walk-level
      half: it is authored, it adds no action downtime, and the activation
      finds no active control to remove.
    """
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    support_effects = {
        "target": [_cleanse_packet(1.5, target="target", attacker="target")]
    }

    # 1. The closed vocabulary refuses the kind, by name, before the walk.
    with pytest.raises(ValueError, match="CC_KIND_VOCABULARY"):
        _simulate_survival(
            combatants,
            {"target": [_control_packet(1.0, duration=2.0, source="?", kind="dance")]},
            {},
            support_effects,
            10.0,
        )

    # 2. The kernel seam still classifies an unknown kind as unknown, and an
    #    unknown control is neither cleansable nor truncatable.
    ce = _require_contract()
    from src.calculator.crowd_control_eligibility import classify_control

    profile = classify_control(SimpleNamespace(cc_kind="dance"))
    assert profile.unknown is True
    decision = _eligibility("Quicksilver Sash").decide(
        _CleanseAction(active_controls=[_interval("dance", 1.0, 3.0)])
    )
    assert decision.eligible is False
    assert decision.reason == "unknown_control"
    kept, removed = ce.truncate_intervals(
        [_interval("dance", 1.0, 3.0)], 1.5, {"dance"}
    )
    assert kept == [_interval("dance", 1.0, 3.0)]
    assert removed == []

    # 3. The walk-level half, on a kind the vocabulary declares: a slow is
    #    known and non-blocking, so it authors no downtime interval and the
    #    activation names control_not_active with nothing removed.
    assert classify_control(SimpleNamespace(cc_kind="slow")).blocking is False
    result = _simulate_survival(
        combatants,
        {"target": [_control_packet(1.0, duration=2.0, source="?", kind="slow")]},
        {},
        support_effects,
        10.0,
    )
    assert result["target"]["action_downtime"] == pytest.approx(0.0)
    assert result["target"]["crowd_control_intervals"] == []
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == "control_not_active"
    assert receipt["removed_controls"] == []
    assert receipt["rejected_controls"] == []


# ---------------------------------------------------------------------------
# R16 — Walk order stays; a blocked control is NOT present at cleanse time
# ---------------------------------------------------------------------------


def test_r16_spell_shield_blocked_control_not_present_at_cleanse():
    """Timeline: a control blocked by a spell shield never creates an
    interval, so a later cleanse finds nothing (control_not_active) while
    the spell-shield block receipt stands — the pinned walk order
    (stasis -> projectile -> spell shield -> CC immunity -> damage) is
    unchanged."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    incoming = {"target": [_control_packet(1.0, duration=2.0, source="E", kind="stun")]}
    support_effects = {
        "target": [
            _spell_shield_template(),
            _cleanse_packet(2.0, target="target", attacker="target"),
        ]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    (control,) = incoming["target"]
    assert control["skipped_reason"] == "spell_shield"
    assert "crowd_control" not in control
    assert result["target"]["spell_shield_used"] is True
    assert result["target"]["action_downtime"] == pytest.approx(0.0)

    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == "control_not_active"
    assert receipt["removed_controls"] == []


def test_r16_immunity_blocked_control_not_present_at_cleanse():
    """Timeline: a control blocked by Black Shield immunity (Slice 3) is
    NOT present at cleanse time — the blocked receipt stands, zero downtime,
    and the later cleanse names control_not_active."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    incoming = {"target": [_control_packet(1.0, duration=2.0, source="E", kind="stun")]}
    support_effects = {
        "target": [
            _black_shield_template(),
            _cleanse_packet(2.0, target="target", attacker="target"),
        ]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    (control,) = incoming["target"]
    assert control["crowd_control_blocked"]["source"] == "Black Shield"
    assert "crowd_control" not in control
    assert result["target"]["action_downtime"] == pytest.approx(0.0)

    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == "control_not_active"
    assert receipt["removed_controls"] == []


def test_r16_app_spell_shield_blocks_control_mikaels_heal_still_fires():
    """App level, CURRENT: the enemy charm on the shielded ally is blocked
    by a spell shield (walk order receipts unchanged — spell_shield skip,
    no crowd_control receipt); Mikael's later heals that ally with nothing
    to truncate (NEW-CONTRACT receipt names control_not_active)."""
    combat = _calculate(
        {
            **_main(items=["Mikael's Blessing"]),
            "item_options": {"Mikael's Blessing": {"active_seconds": 2.5}},
            "support_target_selections": {"heal:Mikael's Blessing \u2014 Purify": 0},
            "enemies": [_ahri_e()],
            "allies": [
                _ally("Sivir", items=["Banshee's Veil"]),
                _ally("Jinx"),
            ],
        }
    )
    sivir_events = _events(combat, target="ally:Sivir", source="E")
    blocked = [
        event for event in sivir_events if event.get("skipped_reason") == "spell_shield"
    ]
    assert blocked
    assert blocked[0]["spell_shield_source"] in {
        "Spell Shield",
        "Banshee's Veil \u2014 Annul",
    }
    assert "crowd_control" not in blocked[0]
    sivir = _survival(combat, "ally:Sivir")
    assert sivir["action_downtime"] == pytest.approx(0.0)
    assert sivir["spell_shield_used"] is True
    (purify,) = _support_events(combat, source=MIKAELS_SOURCE)
    assert purify["target"] == "ally:Sivir"
    assert purify.get("skipped_reason") is None
    # The unshielded allies take the charm (the order stays pinned).
    assert _survival(combat, "main")["action_downtime"] == pytest.approx(1.8)
    assert _survival(combat, "ally:Jinx")["action_downtime"] == pytest.approx(1.8)

    ce = _require_contract()
    assert sivir["cleanse"]["decision"]["reason"] == "control_not_active"
    assert sivir["cleanse"]["removed_controls"] == []


# ---------------------------------------------------------------------------
# R17 — Cleanse at the same timestamp as a control packet (total order)
# ---------------------------------------------------------------------------


def test_r17_same_timestamp_control_and_cleanse_total_order():
    """Timeline + kernel, NEW-CONTRACT: a control packet and a cleanse at
    one timestamp resolve by the walk's total order — the control applies
    (phase 0.0) before the cleanse (phase 1.0), so the same-timestamp
    control is removed ENTIRELY (start >= activation); the outcome is
    deterministic across repeated runs and identified by stable_event_key."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    incoming = {"target": [_control_packet(2.0, duration=2.0, source="E", kind="stun")]}
    support_effects = {
        "target": [_cleanse_packet(2.0, target="target", attacker="target")]
    }

    def run():
        return _simulate_survival(
            combatants,
            {"target": [dict(incoming["target"][0])]},
            {},
            {"target": [dict(support_effects["target"][0])]},
            10.0,
        )

    first = run()
    second = run()
    assert first == second  # deterministic

    ce = _require_contract()
    receipt = first["target"]["cleanse"]
    assert receipt["activation_time"] == pytest.approx(2.0)
    assert receipt["removed_controls"] == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(2.0),
            "end": pytest.approx(4.0),
            "reason": "",
        }
    ]
    # The same-timestamp control never survives: no interval remains.
    assert first["target"]["crowd_control_intervals"] == []
    assert first["target"]["action_downtime"] == pytest.approx(0.0)

    # Kernel: the decision identity is the stable event key and the control
    # phase precedes the cleanse phase (arming-priority baseline, R26).
    control_key = de.stable_event_key(
        SimpleNamespace(time=2.0, source_key="E", sequence=0)
    )
    cleanse_key = de.stable_event_key(
        SimpleNamespace(time=2.0, source_key=QUICKSILVER_SOURCE, sequence=0)
    )
    assert control_key == "E:2.0:0"
    assert cleanse_key == f"{QUICKSILVER_SOURCE}:2.0:0"
    decision = _eligibility("Quicksilver Sash").decide(
        _CleanseAction(
            time=2.0,
            source_key=support_effects["target"][0]["source_key"],
            active_controls=[_interval("stun", 2.0, 4.0)],
        )
    )
    assert decision.eligible is True
    # After the control phase: a cleanse arms at the end of its
    # timestamp, which is what UTILITY_ARM outranking DAMAGE says.
    assert support_transition_rank({"kind": "cleanse"}) > TransitionRank.DAMAGE


# ---------------------------------------------------------------------------
# R18 — Receipt-versus-result parity
# ---------------------------------------------------------------------------


def test_r18_parity_downtime_equals_removed_intervals():
    """Timeline, NEW-CONTRACT: for non-overlapping intervals the survival
    row's action_downtime after equals the sum of the truncated tails, the
    removed controls equal the receipt list, and the kept intervals equal
    the intervals after — receipts and results cannot drift."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    incoming = {"target": [_control_packet(1.0, duration=1.0, source="E", kind="stun")]}
    support_effects = {
        "target": [_cleanse_packet(1.5, target="target", attacker="target")]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["downtime_before"] == pytest.approx(1.0)
    assert receipt["downtime_after"] == pytest.approx(0.5)
    (removed,) = receipt["removed_controls"]
    assert removed["control_kind"] == "stun"
    assert removed["end"] - removed["start"] == pytest.approx(0.5)
    # Parity: survival downtime == merged kept intervals; the delta equals
    # the sum of the truncated tails (non-overlapping case).
    assert result["target"]["action_downtime"] == pytest.approx(0.5)
    assert (receipt["downtime_before"] - receipt["downtime_after"]) == pytest.approx(
        removed["end"] - removed["start"]
    )
    assert [
        (i["start"], i["end"]) for i in result["target"]["crowd_control_intervals"]
    ] == [(1.0, 1.5)]
    assert [(i["start"], i["end"]) for i in receipt["intervals_after"]] == [(1.0, 1.5)]


def test_r18_app_parity_today():
    """App level, CURRENT parity: every participant's action_downtime equals
    the merged duration of its own crowd-control intervals and every landed
    event's crowd_control receipt matches the survival row (the contract
    receipt must reproduce the same intervals when it lands)."""
    combat = _calculate(
        {
            **_main(items=["Mikael's Blessing"]),
            "item_options": {"Mikael's Blessing": {"active_seconds": 2.5}},
            "support_target_selections": {"heal:Mikael's Blessing \u2014 Purify": 0},
            "enemies": [_lulu_qw()],
            "allies": [_ally("Jinx"), _ally("Ashe")],
        }
    )
    for pid in ("main", "ally:Jinx", "ally:Ashe"):
        row = _survival(combat, pid)
        intervals = row["crowd_control_intervals"]
        # Simple parity case: exactly one interval per participant.
        assert len(intervals) == 1
        (interval,) = intervals
        assert row["action_downtime"] == pytest.approx(
            interval["end"] - interval["start"]
        )
        applied = _cc_applied(combat, pid)
        assert len(applied) == 1
        assert applied[0]["crowd_control"]["duration"] == pytest.approx(
            interval["end"] - interval["start"]
        )
    # The Purify heal restored exactly the recipient's missing health
    # (Lulu Q lands twice; the heal at 2.5 covers the unhealed remainder).
    (purify,) = _support_events(combat, source=MIKAELS_SOURCE)
    jinx = _survival(combat, "ally:Jinx")
    assert purify["applied_amount"] == pytest.approx(jinx["healing_received"], abs=0.05)

    ce = _require_contract()
    receipt = jinx["cleanse"]
    assert [(i["start"], i["end"]) for i in receipt["intervals_after"]] == [
        (i["start"], i["end"]) for i in jinx["crowd_control_intervals"]
    ]


# ---------------------------------------------------------------------------
# R19 — Score-path fail-closed (compiled walk)
# ---------------------------------------------------------------------------


def test_r19_compiled_walk_current_fail_closed_surface():
    """Unit, CURRENT + NEW-CONTRACT: the compiled score kernel rejects
    cleanse- and movement-kind support templates with named receipts and
    raises UncompilableActionError; the three items themselves and a plain
    heal are representable (CURRENT).  NEW-CONTRACT (post-integration
    compile gate): a heal template carrying the cleanse marker must FAIL
    CLOSED with the named 'support_cleanse' receipt instead of compiling as
    a plain HEAL — today the marker is silently dropped (the gap this row
    closes)."""
    # CURRENT: kind-level rejections, item representability, plain heal.
    assert (
        unrepresentable_template_receipt({"kind": "cleanse", "amount": 1.0})
        == "support_kind=cleanse"
    )
    assert (
        unrepresentable_template_receipt(
            {"kind": "movement", "amount": 50.0, "duration": 2.0}
        )
        == "support_kind=movement"
    )
    assert unrepresentable_template_receipt({"kind": "heal", "amount": 100.0}) is None
    for item in ("Mikael's Blessing", "Quicksilver Sash", "Mercurial Scimitar"):
        assert uncompilable_item_receipt([{"name": item}]) is None

    # CURRENT: cleanse/movement kinds raise with the named receipt.
    for kind, receipt in (
        ("cleanse", "support_kind=cleanse"),
        ("movement", "support_kind=movement"),
    ):
        compiler = _WalkCompiler()
        try:
            compiler.add_support_templates(
                [
                    {
                        "kind": kind,
                        "amount": 1.0,
                        "attacker": "caster",
                        "target": "main",
                        "time": 1.0,
                    }
                ],
                0,
                {"main": 0, "caster": 1},
            )
        except Exception as exc:  # noqa: BLE001 - the named receipt is the contract
            assert receipt in str(exc)
        else:  # pragma: no cover - today the compile must fail closed
            raise AssertionError(f"{kind} compiled without a fail-closed receipt")

    # NEW-CONTRACT: the heal+cleanse template fails closed after integration
    # (today it compiles as a plain HEAL — the pinned gap).
    ce = _require_contract()
    assert (
        unrepresentable_template_receipt(
            {"kind": "heal", "amount": 100.0, "cleanse": True}
        )
        == "support_cleanse"
    )
    compiler = _WalkCompiler()
    template = {
        "kind": "heal",
        "amount": 100.0,
        "cleanse": True,
        "source": MIKAELS_SOURCE,
        "attacker": "caster",
        "target": "main",
        "time": 2.5,
    }
    try:
        compiler.add_support_templates([template], 0, {"main": 0, "caster": 1})
    except Exception as exc:  # noqa: BLE001 - the named receipt is the contract
        assert "support_cleanse" in str(exc)
    else:  # pragma: no cover - the gate must fail closed after integration
        raise AssertionError(
            "heal+cleanse template compiled without the named support_cleanse gate"
        )


def test_r19_compiled_walk_gate_names_the_cleanse_it_cannot_stage():
    """Unit: the compiled-support gate FAILS CLOSED with a named receipt
    when a template carries a cleanse marker the compiled kernel cannot
    reproduce, and leaves a plain heal representable."""
    template = {
        "kind": "heal",
        "amount": 100.0,
        "cleanse": True,
        "source": MIKAELS_SOURCE,
        "attacker": "caster",
        "target": "main",
        "time": 2.5,
    }
    assert unrepresentable_template_receipt(template) == "support_cleanse"
    # A plain heal stays representable.
    assert (
        unrepresentable_template_receipt(
            {
                "kind": "heal",
                "amount": 100.0,
                "attacker": "caster",
                "target": "main",
                "time": 2.5,
            }
        )
        is None
    )


# ---------------------------------------------------------------------------
# R20 — Public receipt contents
# ---------------------------------------------------------------------------


def test_r20_public_receipt_field_sets():
    """Kernel, NEW-CONTRACT: the exact public receipt shapes the owner's
    required fields demand — declaration receipt, decision receipt,
    recipient survival-row cleanse receipt, caster cleanse_use receipt,
    removed/rejected entries, heal and movement entries."""
    ce = _require_contract()

    declaration = _declaration("Mikael's Blessing")
    decl_receipt = declaration
    assert set(decl_receipt) == {
        "item",
        "active_name",
        "target_scope",
        "excluded_control_kinds",
        "cooldown_seconds",
        "cooldown_source_gap",
        "heal",
        "movement",
        "source_receipts",
        "source_atoms",
    }

    action = _CleanseAction(
        item="Quicksilver Sash",
        active_controls=[_interval("stun", 1.0, 3.0, source="E")],
    )
    decision = _eligibility("Quicksilver Sash").decide(action)
    receipt = decision.public_receipt()
    assert set(receipt) == {
        "eligible",
        "reason",
        "item",
        "activation_time",
        "target",
        "active_controls_before",
        "removed_controls",
        "rejected_controls",
        "intervals_after",
        "downtime_before",
        "downtime_after",
        "use_consumed",
    }
    assert receipt["eligible"] is True
    assert receipt["reason"] == ""
    assert receipt["item"] == "Quicksilver Sash"
    assert receipt["activation_time"] == pytest.approx(1.5)
    assert receipt["target"] == "target"
    assert receipt["active_controls_before"] == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(1.0),
            "end": pytest.approx(3.0),
        }
    ]
    assert receipt["removed_controls"] == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(1.5),
            "end": pytest.approx(3.0),
            "reason": "",
        }
    ]
    assert receipt["rejected_controls"] == []
    assert receipt["intervals_after"] == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(1.0),
            "end": pytest.approx(1.5),
        }
    ]
    assert receipt["downtime_before"] == pytest.approx(2.0)
    assert receipt["downtime_after"] == pytest.approx(0.5)
    assert receipt["use_consumed"] is True

    # Heal and movement entry shapes (Mikael's heal / Mercurial movement).
    heal_entry = _declaration("Mikael's Blessing")["heal"]
    assert set(heal_entry) == {
        "amount_min",
        "amount_max",
        "scaling",
        "source",
        "source_atoms",
    }
    movement_entry = _declaration("Mercurial Scimitar")["movement"]
    assert set(movement_entry) == {
        "amount",
        "duration",
        "source",
        "source_atoms",
    }


# ---------------------------------------------------------------------------
# R21 — Caster crowd-control at activation TODAY
# ---------------------------------------------------------------------------


def test_r21_app_mikaels_heal_blocked_while_caster_is_ccd_today():
    """App level, CURRENT: with the caster crowd-controlled at the
    activation time, today's walk skips the Purify heal with the named
    attacker_state_blocked receipt — no heal, no truncation.  (The
    NEW-CONTRACT exemption is R22.)"""
    combat = _calculate(
        {
            **_main(items=["Mikael's Blessing"]),
            "item_options": {"Mikael's Blessing": {"active_seconds": 1.0}},
            "support_target_selections": {"heal:Mikael's Blessing \u2014 Purify": 0},
            "enemies": [_lulu_qw()],
            "allies": [_ally("Jinx"), _ally("Ashe")],
        }
    )
    (purify,) = _support_events(combat, source=MIKAELS_SOURCE)
    assert purify["time"] == pytest.approx(1.0)
    assert purify["skipped_reason"] == "attacker_state_blocked"
    for pid in ("main", "ally:Jinx", "ally:Ashe"):
        row = _survival(combat, pid)
        assert row["healing_received"] == pytest.approx(0.0)
        assert row["action_downtime"] == pytest.approx(2.0)


def test_r21_timeline_self_cast_cleanse_rides_the_gate_today():
    """Timeline level, CURRENT + NEW-CONTRACT: the attacker-state gate sits
    AFTER the utility branch, so a self-cast cleanse-kind packet while the
    caster is crowd-controlled is APPLIED today (recorded as utility —
    never skipped with attacker_state_blocked).  NEW-CONTRACT: the cast
    fires (QSS/Mercurial castability, R27) and truncates the caster's OWN
    stun; the use receipt names fired_while_crowd_controlled=True."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    incoming = {"target": [_control_packet(1.0, duration=2.0, source="E", kind="stun")]}
    support_effects = {
        "target": [_cleanse_packet(1.5, target="target", attacker="target")]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    (cleanse,) = support_effects["target"]
    # CURRENT: rides the gate (stays true after integration — the cast
    # fires, it is never skipped).
    assert cleanse.get("skipped_reason") is None
    assert cleanse["applied_amount"] == pytest.approx(1.0)

    # NEW-CONTRACT: the self-cast fires and truncates its own stun.
    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"] == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(1.5),
            "end": pytest.approx(3.0),
            "reason": "",
        }
    ]
    assert [
        (i["kind"], i["start"], i["end"])
        for i in result["target"]["crowd_control_intervals"]
    ] == [("stun", 1.0, 1.5)]
    assert result["target"]["action_downtime"] == pytest.approx(0.5)
    use = result["target"]["cleanse_use"]
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0
    assert use["fired_while_crowd_controlled"] is True


# ---------------------------------------------------------------------------
# R22 — Cleanse fires while the caster is crowd-controlled (item purpose)
# ---------------------------------------------------------------------------


def test_r22_mikaels_heal_stays_gated_while_caster_is_ccd():
    """Timeline level, NEW-CONTRACT (PRIMARY, sourced castability): the
    binary audit shows 3222Active carries NO canCastWhileDisabled (and no
    cannotBeSuppressed), so Mikael's Purify (heal + cleanse) stays GATED
    while the caster is crowd-controlled — R21's attacker_state_blocked
    receipt is the pinned behavior.  The caster's use receipt names the
    rule (fired_while_crowd_controlled=False) and the use is NOT consumed
    (the activation was skipped).  TODAY the heal is blocked (CURRENT); the
    receipt is pending."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
        _dummy_combatant("caster", "main"),
    ]
    incoming = {
        "target": [
            _damage_packet(0.5, 500.0, target="target"),
            _control_packet(
                1.0, duration=2.0, source="E", kind="stun", target="target"
            ),
        ],
        "caster": [
            _control_packet(0.5, duration=2.0, source="W", kind="stun", target="caster")
        ],
    }
    support_effects = {
        "target": [
            _purify_packet(1.5, target="target", attacker="caster", amount=100.0)
        ]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    # CURRENT: the heal is blocked while the caster is crowd-controlled.
    assert result["target"]["healing_received"] == pytest.approx(0.0)
    assert result["target"]["action_downtime"] == pytest.approx(2.0)

    # NEW-CONTRACT: the gate stays (no truncation) and the use receipt names
    # the rule; the gated activation does NOT consume a use.
    ce = _require_contract()
    assert result["target"]["healing_received"] == pytest.approx(0.0)
    assert result["target"]["action_downtime"] == pytest.approx(2.0)
    assert [
        (i["kind"], i["start"], i["end"])
        for i in result["target"]["crowd_control_intervals"]
    ] == [("stun", 1.0, 3.0)]
    caster_use = result["caster"]["cleanse_use"]
    assert caster_use["fired_while_crowd_controlled"] is False
    assert caster_use["uses_before"] == 1
    assert caster_use["uses_after"] == 1
    # The caster's own crowd control is untouched by the blocked activation.
    assert result["caster"]["action_downtime"] == pytest.approx(2.0)


# NOTE: the alternate Mikael's caster-CC exemption variant (Purify fires
# while the caster is crowd-controlled, truncating the target's stun and
# marking fired_while_crowd_controlled=True on the caster's use receipt) was
# removed here — it is not a reachable branch, not just an unpinned one.
# The binary audit (3222Active carries NEITHER canCastWhileDisabled NOR
# cannotBeSuppressed, unlike QuicksilverSash.mSpell / ItemMercurial.mSpell)
# means Mikael's Purify can never fire while its own caster is
# crowd-controlled, so the exemption variant above is contradicted by the
# sourced castability evidence, not merely untested.  The PRIMARY variant
# directly above (test_r22_mikaels_heal_stays_gated_while_caster_is_ccd)
# already pins the chosen branch: the heal is blocked (healing_received ==
# 0.0), the target's stun interval is untouched ([1.0, 3.0]), and the
# caster's cleanse_use receipt names fired_while_crowd_controlled=False with
# the use NOT consumed.  Nothing about the removed alternate's claim is
# lost — it is the unchosen, now-unreachable branch of the same decision the
# primary settles.


# ---------------------------------------------------------------------------
# R23 — QSS/Mercurial actives: option validation today vs post-contract
# ---------------------------------------------------------------------------


# NOTE: the CURRENT "rejected with a named 400" variant (neither self item
# declared an active option in ITEM_INPUT_OPTIONS, so an explicit active
# option was rejected with "Unknown item option target: <item>") was removed
# here — it no longer describes the tree.  The owner landed the P2 Slice 4
# active option for both Quicksilver Sash and Mercurial Scimitar, so the
# named-400 rejection this row asserted is not reachable anymore; it is
# superseded, not merely unpinned.  The PRIMARY variant directly below
# (test_r23_new_self_cleanse_option_accepted_and_applied, both items) already
# pins the current branch: POST /api/calculate returns 200 for both items
# with the active armed, the cleanse receipt names the item/target/
# activation_time, the holder's charm interval is truncated at the
# self-cast, and (Mercurial only) the separate movement utility fires.
# Nothing about the removed row's claim is lost — it is the now-unreachable
# branch of the same decision the primary settles.


@pytest.mark.parametrize(
    "item,source",
    [
        ("Quicksilver Sash", QUICKSILVER_SOURCE),
        ("Mercurial Scimitar", MERCURIAL_SOURCE),
    ],
)
def test_r23_new_self_cleanse_option_accepted_and_applied(item, source):
    """App level, NEW-CONTRACT: the slice adds an active option for both
    self items; arming it authors a self-cast cleanse that truncates the
    holder's active charm and (Mercurial only) grants the separate movement
    utility receipted in utility_outcomes.  Today the option is rejected
    with the named 400, so the row fails with the pending-kernel marker."""
    payload = {
        **_main(items=[item]),
        "item_options": {item: {"active_seconds": 1.0}},
        "enemies": [_ahri_e()],
    }
    status, body = _calculate_status(payload)
    if status == 400 and "Unknown item option target" in str(body.get("error", "")):
        pytest.fail(
            "PENDING KERNEL: item_options for "
            f"{item} are not accepted yet (400 'Unknown item option "
            "target') — the slice must add the active option before this "
            "row can assert the self-cast cleanse"
        )
    assert status == 200, body
    combat = body["combat"]

    main = _survival(combat, "main")
    receipt = main["cleanse"]
    assert receipt["item"] == item
    assert receipt["target"] == "main"
    assert receipt["activation_time"] == pytest.approx(1.0)
    # Ahri's charm [0, 1.8] truncated at the self-cast (the caster-CC
    # exemption of R22 lets QSS fire while charmed — its purpose).
    assert receipt["removed_controls"][0]["control_kind"] == "immobilize"
    assert [
        (i["kind"], i["start"], i["end"]) for i in main["crowd_control_intervals"]
    ] == [("immobilize", 0.0, 1.0)]
    assert main["action_downtime"] == pytest.approx(1.0)
    use = main["cleanse_use"]
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0
    assert use["cooldown_seconds"] is None
    assert use["cooldown_source_gap"] is True

    if item == "Mercurial Scimitar":
        movement = combat["utility_outcomes"]["participants"]["main"]["movement"]
        assert movement["event_count"] == 1
        assert movement["speed_percent_seconds"] == pytest.approx(100.0)
        assert receipt["movement"]["amount"] == pytest.approx(50.0)
        assert receipt["movement"]["duration"] == pytest.approx(2.0)
        assert {atom["hash"] for atom in receipt["movement"]["source_atoms"]} == {
            "5e5f100f08a793f9"
        }
    else:
        assert receipt["movement"] is None


# ---------------------------------------------------------------------------
# R24 — Mercurial: self cleanse + SEPARATE movement utility effect
# ---------------------------------------------------------------------------


def test_r24_mercurial_movement_is_a_separate_utility_effect():
    """Timeline: Mercurial's movement speed is a SEPARATE utility effect
    with its own atoms — the movement packet is recorded in native units
    today (CURRENT: applied_amount 50, no truncation) and the contract
    receipt carries the movement entry beside the cleanse (NEW-CONTRACT)."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    incoming = {"target": [_control_packet(1.0, duration=2.0, source="E", kind="stun")]}
    support_effects = {
        "target": [
            _cleanse_packet(
                1.5, source=MERCURIAL_SOURCE, target="target", attacker="target"
            ),
            _movement_packet(1.5, target="target", attacker="target"),
        ]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    # CURRENT: the movement utility is recorded in native units (50% / 2s);
    # the cleanse truncates nothing.
    cleanse, movement = support_effects["target"]
    # CURRENT: the movement utility is recorded in native units (50% / 2s).
    assert movement["applied_amount"] == pytest.approx(50.0)
    assert movement["duration"] == pytest.approx(2.0)

    # NEW-CONTRACT: truncation + the movement entry with its own atoms.
    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["item"] == "Mercurial Scimitar"
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"][0]["control_kind"] == "stun"
    movement_entry = receipt["movement"]
    assert movement_entry["amount"] == pytest.approx(50.0)
    assert movement_entry["duration"] == pytest.approx(2.0)
    assert movement_entry["source"] == MERCURIAL_SOURCE
    assert {atom["hash"] for atom in movement_entry["source_atoms"]} == {
        "5e5f100f08a793f9"  # control.movement_speed (data/atoms/items.json 3139)
    }
    assert result["target"]["action_downtime"] == pytest.approx(0.5)
    assert [
        (i["kind"], i["start"], i["end"])
        for i in result["target"]["crowd_control_intervals"]
    ] == [("stun", 1.0, 1.5)]


# ---------------------------------------------------------------------------
# R25 — A cleanse packet today: records utility, truncates nothing
# ---------------------------------------------------------------------------


def test_r25_cleanse_packet_records_utility_and_truncates_nothing():
    """Timeline level, CURRENT (the canonical baseline the slice replaces):
    a cleanse-kind packet is recorded as a utility effect (applied_amount)
    and truncates NOTHING — the stun interval and its downtime stand."""
    cleanse = _cleanse_packet(1.5, target="target", attacker="caster")
    result, _ = _simulate(
        [_control_packet(1.0, duration=2.0, source="E", kind="stun")],
        [cleanse],
    )
    target = result["target"]
    assert target["action_downtime"] == pytest.approx(2.0)
    assert [
        (i["kind"], i["start"], i["end"]) for i in target["crowd_control_intervals"]
    ] == [("stun", 1.0, 3.0)]
    assert target["crowd_control_until"] == pytest.approx(3.0)
    assert cleanse["applied_amount"] == pytest.approx(1.0)
    assert "crowd_control" not in cleanse
    assert "crowd_control_blocked" not in cleanse
    assert "cleanse" not in cleanse


# ---------------------------------------------------------------------------
# R26 — Support-packet arming-priority baseline (total-order baseline)
# ---------------------------------------------------------------------------


def test_r26_cleanse_and_movement_arm_after_the_controls_at_their_time():
    """Kernel, CURRENT: cleanse and movement support packets take the
    kind ladder's fall-through rank, ``UTILITY_ARM`` — strictly after the
    same-timestamp damage and control packets that arm at ``DAMAGE`` —
    which is the total-order baseline the same-timestamp row (R17) pins;
    the stable event key keeps the deterministic identity.  Read off the
    one rank ladder, because the parallel float table it used to read is
    retired and a second home for one ordering is how the two drift."""
    for kind in ("cleanse", "movement"):
        rank = support_transition_rank({"kind": kind})
        assert rank is TransitionRank.UTILITY_ARM
        assert rank > TransitionRank.DAMAGE
    # The stable identity used by both the cleanse and control decisions.
    action = SimpleNamespace(time=1.5, source_key=QUICKSILVER_SOURCE, sequence=2)
    assert de.stable_event_key(action) == f"{QUICKSILVER_SOURCE}:1.5:2"
    action = SimpleNamespace(time=1.5, source_key="E", sequence=0)
    assert de.stable_event_key(action) == "E:1.5:0"


# ---------------------------------------------------------------------------
# R27 — QSS/Mercurial castability: fires while the caster is stunned/charmed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "item,source,kind",
    [
        ("Quicksilver Sash", QUICKSILVER_SOURCE, "stun"),
        ("Quicksilver Sash", QUICKSILVER_SOURCE, "charm"),
        ("Mercurial Scimitar", MERCURIAL_SOURCE, "stun"),
        ("Mercurial Scimitar", MERCURIAL_SOURCE, "charm"),
    ],
)
def test_r27_self_cast_fires_while_caster_is_stunned_or_charmed(item, source, kind):
    """Timeline level, NEW-CONTRACT: the sourced castability rule
    (QuicksilverSash.mSpell / ItemMercurial.mSpell carry
    canCastWhileDisabled=true) exempts the QSS/Mercurial self-cast from the
    attacker crowd-control gate while the caster is stunned or charmed: the
    cast fires, truncates the caster's OWN interval, and the use receipt
    names fired_while_crowd_controlled=True.  The suppression castability
    denial is R7 (caster_control_blocks_cleanse); airborne stays
    excluded_control_kind (R8).  TODAY the packet rides the gate (applied
    as utility, R21) — the truncation and receipt are pending."""
    combatants = [
        _dummy_combatant("enemy", "enemy"),
        _dummy_combatant("target", "main"),
    ]
    incoming = {"target": [_control_packet(0.5, duration=2.0, source="E", kind=kind)]}
    support_effects = {
        "target": [
            _cleanse_packet(1.5, source=source, target="target", attacker="target")
        ]
    }
    result = _simulate_survival(combatants, incoming, {}, support_effects, 10.0)
    (cleanse,) = support_effects["target"]
    # CURRENT: the self-cast is never skipped by the attacker gate.
    assert cleanse.get("skipped_reason") is None
    assert cleanse["applied_amount"] == pytest.approx(1.0)

    # NEW-CONTRACT: fires + truncates the caster's own interval + receipt.
    ce = _require_contract()
    receipt = result["target"]["cleanse"]
    assert receipt["item"] == item
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"] == [
        {
            "control_kind": kind,
            "source": "E",
            "start": pytest.approx(1.5),
            "end": pytest.approx(2.5),
            "reason": "",
        }
    ]
    assert [
        (i["kind"], i["start"], i["end"])
        for i in result["target"]["crowd_control_intervals"]
    ] == [(kind, 0.5, 1.5)]
    assert result["target"]["action_downtime"] == pytest.approx(1.0)
    use = result["target"]["cleanse_use"]
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0
    assert use["fired_while_crowd_controlled"] is True


# ---------------------------------------------------------------------------
# Matrix summary (row id | dimension | level | status | depends on)
# ---------------------------------------------------------------------------
#
# R1  | Mikael's cleanses + heals the SELECTED ally only (other allies and the
#      caster unaffected; enemy control lands on unselected allies)
#      | app | CURRENT (heal + no truncation) / NEW-CONTRACT (cleanse receipt) | no
# R2  | Mikael's target-choice public receipt (which ally was selected; heal,
#      decision and use follow the selection; activation after the caster's
#      control ends — app-level truncation is covered by R23-new/R27)
#      | app | CURRENT (heal follows selection) / NEW-CONTRACT (receipt) | no
# R3  | Mikael's selected-ally semantics at timeline level (two allies, mid-CC
#      activation, free caster) | timeline | NEW-CONTRACT | no
# R4  | ITEM_CLEANSE_DECLARATIONS: one sourced declaration per item (name /
#      active / scope / exclusions / cooldown / heal / movement / atoms)
#      | kernel | NEW-CONTRACT | no
# R5  | Mikael's excluded control kinds are row-specific per its wording
#      (airborne, blind, disarm, nearsight, suppression) | kernel | NEW-CONTRACT | no
# R6  | Suppression per item: Mikael's own wording excludes it -> NOT cleansed
#      | timeline | NEW-CONTRACT | A-dependent (suppression question)
# R7  | Suppression CASTABILITY per item: QSS/Mercurial self-casts are DENIED
#      while the caster is suppressed (caster_control_blocks_cleanse; use NOT
#      consumed); removal SET stays pinned in R4/R5 (excluded == (airborne,))
#      | timeline | NEW-CONTRACT (denial primary; wording-removal alternate
#      xfailed) | no (A resolved)
# R8  | Airborne per item: all three exclude airborne -> never cleansed,
#      interval untouched | timeline | NEW-CONTRACT | no
# R9  | slow/root/stun/charm/fear per sourced rules (blocking kinds removed;
#      soft slow never creates downtime) | kernel+timeline
#      | CURRENT (soft no-downtime) / NEW-CONTRACT (removal) | no
# R10 | No active control at activation (per item: heal still fires / movement
#      still grants / use consumed; receipt names the rule)
#      | kernel+timeline | CURRENT (heal fires) / NEW-CONTRACT (receipts) | no
# R11 | Control before / at / after activation (historical remains; active
#      ends at activation; future removed; total order)
#      | timeline | CURRENT (no truncation) / NEW-CONTRACT (truncation) | no
# R12 | Two overlapping controls with different eligibility (stun cleansed,
#      suppression not) | timeline | NEW-CONTRACT | no
# R13 | Two controls ending at different times (only each cleansed control's
#      own remaining tail removed) | timeline | NEW-CONTRACT | no
# R14 | Repeated use and cooldown within one fight (use state; cooldown source
#      gap fails closed) | kernel+timeline | NEW-CONTRACT | no
# R15 | Unknown control kind fails closed (named reason; no truncation)
#      | kernel+timeline | CURRENT (walk applies unknown intervals today)
#      / NEW-CONTRACT (decision) | no
# R16 | Walk order stays: stasis -> projectile -> spell shield -> CC immunity
#      -> damage; a blocked control is NOT present at cleanse time
#      | app+timeline | CURRENT (order) / NEW-CONTRACT (cleanse receipt) | no
# R17 | Cleanse at the same timestamp as a control packet: kernel total order
#      (stable_event_key + action_key) | kernel+timeline | NEW-CONTRACT | no
# R18 | Receipt-versus-result parity: action_downtime == merged intervals;
#      removed tails; receipts consistent | app+timeline
#      | CURRENT (parity) / NEW-CONTRACT (cleanse receipts) | no
# R19 | Score-path fail-closed: compiled walk with Mikael's/QSS/Mercurial
#      armed | unit | CURRENT (representable today; cleanse/movement kinds
#      rejected) / NEW-CONTRACT (named gate) | A/B-dependent
# R20 | Public receipt contents (the owner's required receipt field sets)
#      | kernel | NEW-CONTRACT | no
# R21 | Caster crowd-control at activation TODAY (cleanse-kind utility rides
#      the gate; Mikael's heal is blocked) | app+timeline | CURRENT | no
# R22 | Caster crowd-control at activation (sourced castability): Mikael's
#      Purify stays GATED (attacker_state_blocked; use NOT consumed); the
#      caster's use receipt names the rule | timeline | NEW-CONTRACT (gated
#      primary; exemption alternate xfailed — binary evidence) | no (A resolved)
# R23 | QSS/Mercurial actives: option validation today (named 400) vs
#      post-contract options | app | CURRENT (named 400) / NEW-CONTRACT
#      (accepted) | no
# R24 | Mercurial: self cleanse + SEPARATE movement utility effect (amount
#      50%, duration 2s, its own atoms) | timeline+app
#      | CURRENT (utility recorded) / NEW-CONTRACT (atoms + grant) | no
# R25 | A cleanse packet today: records utility and truncates nothing
#      (canonical CURRENT baseline) | timeline | CURRENT | no
# R26 | Support-packet arming-priority baseline: cleanse/movement ride
#      phase 1.0 (total-order baseline) | kernel | CURRENT | no
# R27 | QSS/Mercurial castability exemption: self-cast fires while the caster
#      is stunned/charmed (truncates the caster's own interval; receipt
#      fired_while_crowd_controlled=true); suppression denial = R7; airborne
#      stays excluded_control_kind (R8) | timeline
#      | CURRENT (packet rides the gate) / NEW-CONTRACT (truncation + receipt)
#      | no (A resolved)
