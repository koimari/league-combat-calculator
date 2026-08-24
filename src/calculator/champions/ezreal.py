"""Ezreal — slot map for the archetype engine.

Why each slot is non-generic:
- P (Rising Spell Force) is a stat-buff-only passive with NO JSON
  leveling data (pure stack mechanic): 10% bonus attack speed per stack,
  up to 5 stacks, driven by the ``passive_stacks`` option. The generic
  path drops it entirely; here it is a BUFF-phase zero-damage entry
  (Bel'Veth precedent — stat-buff slots never silently vanish).
- Q (Mystic Shot) applies item on-hit AND on-attack effects (wiki
  explicit), cannot crit, and every hit refunds 1.5s on ALL of Ezreal's
  current cooldowns including Q's own — the kit-wide refund is emitted
  as adjusted entry cooldowns (Gnar Q pickup-refund precedent; math in
  ``_q_hasted_period`` / ``_refund_rate_factor``).
- W (Essence Flux): its damage lives at effect[1] under "Bonus Magic
  Damage" (the projectile itself deals zero — all damage is the mark
  detonation, assumed always triggered), plus the Q-refund cooldown.
- E (Arcane Shift): plain "Magic Damage" read; module-owned for the
  Q-refund cooldown (blink/reveal utility ignored).
- R (Trueshot Barrage) must read "Magic Damage" exactly: effect[1]
  carries "Modified Damage" — the minion/non-epic-monster value — which
  must never leak into champion damage. Plus the Q-refund cooldown.
"""

from typing import Any

from .engine import BUFF, SlotCtx, SlotParser, build_parser
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)
from .source_receipts import load_champion_sources
from .inputs import int_option
from ..binary_roots import data_value, spell_object

# ROOTED IN THE BINARY (data/bin/characters/ezreal.bin.json): the passive
# stack shape is EzrealPassive DataValues, Q's cooldown refund is
# EzrealQ.CDRefund, and Essence Flux's mark lifetime/refund flat are
# EzrealW.DetonationTimeout / ManaReturn.  A patch that moves a root moves
# the module; a missing dump fails closed at import.
# https://wiki.leagueoflegends.com/en-us/Ezreal
_EZ_P_SPELL = spell_object("Ezreal", "EzrealPassive")
_EZ_Q_SPELL = spell_object("Ezreal", "EzrealQ")
_EZ_W_SPELL = spell_object("Ezreal", "EzrealW")
PASSIVE_AS_PER_STACK = data_value(_EZ_P_SPELL, "AttackSpeedPerStack") * 100.0
PASSIVE_MAX_STACKS = int(data_value(_EZ_P_SPELL, "MaxStacks"))
Q_REFUND_SECONDS = data_value(_EZ_Q_SPELL, "CDRefund")
Q_MIN_PERIOD = 1.0  # sanity floor on Q's post-refund cast period (model choice)

# Essence Flux's mark-detonation refund flat: the binary ManaReturn
# DataValue (the "+ mana cost of that ability" clause is script-side,
# wiki-sourced only).
# https://wiki.leagueoflegends.com/en-us/Ezreal (revision 4041697)
W_MARK_REFUND_FLAT = data_value(_EZ_W_SPELL, "ManaReturn")

# Essence Flux's mark lifetime: three roots agree — the cached prose
# "marks ... for 4 seconds" (effects[0]), the binary DetonationTimeout, and
# atom b32849b968950b8e (``timing.active_duration`` [4.0]).  A detonation
# landing after the window is receipted ``mark_expired`` and never refunds.
W_MARK_WINDOW_SECONDS = data_value(_EZ_W_SPELL, "DetonationTimeout")


# ---------------------------------------------------------------------------
# Q cooldown-refund model (continuous rate, every Q assumed to hit)
# ---------------------------------------------------------------------------


# The refund is a flat 1.5 s of real time, so refund math runs in hasted
# seconds and converts back through this factor when writing pre-haste entry
# cooldowns.
def _haste_factor(ctx: SlotCtx) -> float:
    """(100 + ability haste) / 100, the divisor the fight engine applies later."""
    return 1.0 + ctx.stat("ability_haste") / 100.0


def _q_hasted_period(ctx: SlotCtx) -> float | None:
    """Q's modeled cast period in real (post-haste) seconds, None unranked.

    Assuming every Q hits, each cast refunds ``Q_REFUND_SECONDS`` off Q's
    own cooldown once per cycle, so the period is the hasted cooldown minus
    the refund, floored at ``Q_MIN_PERIOD``.
    """
    ranked = ctx.ranked("Q")
    if ranked is None:
        return None
    ability, rank = ranked
    hasted = extract_cooldown(ability, rank) / _haste_factor(ctx)
    return max(Q_MIN_PERIOD, hasted - Q_REFUND_SECONDS)


def _refund_rate_factor(ctx: SlotCtx) -> float:
    """Cooldown speed-up W/E/R receive from the Q refund stream.  Dividing a
    PRE-haste cooldown by it commutes with the engine's later haste division.
    Spear of Shojin's extra basic-ability haste is applied fight-side only
    and is not folded into this inversion."""
    period = _q_hasted_period(ctx)
    if period is None:
        return 1.0
    return 1.0 + Q_REFUND_SECONDS / period


def _with_q_refund(parser: SlotParser) -> SlotParser:
    """Wrap a damage slot so its cooldown rides the Q refund stream."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        if entry is not None:
            entry["cooldown"] /= _refund_rate_factor(ctx)
        return entry

    parse.phase = parser.phase
    return parse


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------


def _rising_spell_force(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: stat-buff only — 10% bonus attack speed per stack, no damage.

    BUFF-phase zero-damage entry; the fight engine applies the
    ``stat_buff`` to champion stats before the fight. Attack speed is
    not a parse-time scaling stat for any of Ezreal's damage reads, so
    ``ctx.stats`` is left untouched.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = min(max(int(ctx.option("passive_stacks")), 0), PASSIVE_MAX_STACKS)
    bonus_as = PASSIVE_AS_PER_STACK * stacks
    entry = damage_entry(ability_name(ability), ctx.level, 0.0, 0.0, "physical")
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = f"+{bonus_as:.0f}% bonus attack speed ({stacks} stacks)"
    return entry


_rising_spell_force.phase = BUFF


def _mystic_shot(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: physical skillshot; applies item on-hit and on-attack effects
    at full effectiveness, cannot crit; cooldown carries its own refund.

    Muramana is NOT applied through the on-hit application — its Shock
    ability damage already procs once per cast on the per-cast path,
    and the two never stack on one ability hit (item taxonomy:
    ``superseded_by_ability_proc``).
    """
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    total = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    period = _q_hasted_period(ctx)
    entry = damage_entry(
        ability_name(ability),
        rank,
        (period if period is not None else 0.0) * _haste_factor(ctx),
        total,
        "physical",
    )
    # Wiki-explicit: Mystic Shot applies on-hit AND on-attack effects —
    # it counts on shared on-hit counters (Kraken every-3rd) and
    # advances on-attack cadences (Guinsoo phantom stacking).
    entry["applies_item_on_hits"] = {
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit", "on_attack"),
    }
    # One bolt, one enemy, no sourced travel phase in the cached packet —
    # the claim that puts Q's hit in the event ledger, where MODULE_CC's
    # reviewed "no control" can be read.
    entry["event_order_certified"] = "single_hit"
    return entry


def _essence_flux(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: Essence Flux — mark bonus damage + the ability-detonation refund.

    The damage is the plain effect[1] read; the entry additionally carries
    the typed ``mark_refund`` rule so the shared resource walk can refund
    ``60 + <detonating ability's mana cost>`` when the mark is detonated
    BY AN ABILITY (the next accepted ability cast after this W in the
    fight's schedule).  The ``w_mark_detonation`` option chooses the
    detonation means; ``basic_attack`` disables the refund entirely (the
    mark is detonated by a basic attack, which sources no mana back).
    """
    entry = _with_q_refund(
        simple_damage(
            attr="Bonus Magic Damage",
            dmg_type="magic",
            event_order_certified="single_hit",
        )
    )(ctx)
    if entry is None:
        return None
    detonation = str(ctx.option("w_mark_detonation"))
    if detonation not in {"ability", "basic_attack"}:
        raise ValueError(
            f"unknown w_mark_detonation {detonation!r}; supported: "
            "ability, basic_attack"
        )
    entry["mark_refund"] = {
        "flat": W_MARK_REFUND_FLAT,
        "window_seconds": W_MARK_WINDOW_SECONDS,
        "source": "Ezreal W (Essence Flux) mark refund",
        "atoms": (),
        "detonation": detonation,
    }
    return entry


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "w_mark_detonation",
        "type": "select",
        "default": "ability",
        "label": "W mark detonation",
        "choices": [
            {"value": "ability", "label": "Ability (refunds 60 + its mana cost)"},
            {"value": "basic_attack", "label": "Basic attack (no mana refund)"},
        ],
    },
    int_option(
        "passive_stacks",
        5,
        minimum=0,
        maximum=5,
        label="Passive stacks (Rising Spell Force)",
    ),
]

ASSUMPTIONS = [
    "Every Q cast hits — drives item on-hit applications, the 1.5s "
    "cooldown refund model, and passive upkeep",
    "Q's 1.5s refund is modeled as a continuous rate: Q period = hasted "
    "CD - 1.5s (min 1s); other cooldowns divided by (1 + 1.5/Q period)",
    "W's mark is always detonated (by the next auto or Q within its 4s "
    "window); a missed detonation means the W missed anyway",
    "Q cannot critically strike",
    "Q consuming spellblade (Sheen/Trinity) in an auto-less burst "
    "rotation is not modeled; with an auto stream the engine's existing "
    "spellblade model yields the same proc count",
    "W's mana refund is modeled on the shared mana ledger: when the mark "
    "is detonated BY AN ABILITY (the next accepted ability cast after the "
    "W in the fight's schedule — every cast is assumed to hit), Ezreal "
    "restores 60 mana plus that ability's mana cost (the cost actually "
    "paid, Actualizer discount included). The w_mark_detonation option "
    "chooses the detonation means; basic_attack detonation restores "
    "nothing. The flat 60 is a typed rule declaration (wiki prose + game "
    "binary ManaReturn; no atom exists). The 4s mark window IS modeled "
    "(cache prose + the binary DetonationTimeout 4.0 + the atom "
    "timing.active_duration b32849b968950b8e): a detonation landing "
    "after the window is receipted mark_expired and never refunds. The "
    "mark is always detonated within its window (every cast is assumed "
    "to hit); target-side spell "
    "shields are not modeled); an undetonated mark at the end of the "
    "fight is receipted, never guessed",
    "Life steal applying to Q is not modeled (healing out of scope)",
]

SLOTS = {
    "P": _rising_spell_force,
    "Q": _mystic_shot,
    # W carries the mark-detonation mana refund as well as its damage.
    # Each of W/E/R is one damage instance with no sourced travel or tick
    # phase, so the single-hit certification is what carries them into the
    # event ledger MODULE_CC is read from.
    "W": _essence_flux,
    "E": _with_q_refund(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        )
    ),
    "R": _with_q_refund(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        )
    ),
}

# Ezreal's cached kit applies no crowd control at all: Q is a bolt that
# only refunds cooldowns, W marks and detonates, E blinks and reveals, R
# grants sight.  Every entry has been reviewed against the pinned Wiki
# record and the game binary.  P is the module's zero-damage attack-speed
# buff slot — it authors no damage part the ledger can carry a review on,
# so it is left undeclared rather than stamped.
MODULE_CC = {"Q": "none", "W": "none", "E": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Ezreal", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Ezreal")
