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
from .slotlib import damage_entry, extract_cooldown, extract_named, simple_damage

# HARDCODED: verify on patch updates — wiki-prose values with no JSON
# home (P has no leveling data; the refund is prose on Q).
# https://wiki.leagueoflegends.com/en-us/Ezreal
PASSIVE_AS_PER_STACK = 10.0  # % bonus attack speed per passive stack
PASSIVE_MAX_STACKS = 5
Q_REFUND_SECONDS = 1.5  # each Q hit refunds this off every current cooldown
Q_MIN_PERIOD = 1.0  # sanity floor on Q's post-refund cast period (seconds)


# ---------------------------------------------------------------------------
# Q cooldown-refund model (continuous rate, every Q assumed to hit)
# ---------------------------------------------------------------------------


def _haste_factor(ctx: SlotCtx) -> float:
    """(100 + ability haste) / 100 — the divisor the fight engine will
    later apply to entry cooldowns. The refund is a flat 1.5s of REAL
    time, so the refund math runs in hasted seconds and converts back
    through this factor when writing pre-haste entry cooldowns."""
    return 1.0 + ctx.stats.get("ability_haste", 0.0) / 100.0


def _q_hasted_period(ctx: SlotCtx) -> float | None:
    """Q's modeled cast period in real (post-haste) seconds.

    Assuming every Q hits, each cast refunds ``Q_REFUND_SECONDS`` off
    Q's own cooldown exactly once per cycle, so the period is the
    hasted cooldown minus the refund, floored at ``Q_MIN_PERIOD``.
    Returns None when Q is unranked (no refund stream exists).
    """
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    hasted = extract_cooldown(ability, rank) / _haste_factor(ctx)
    return max(Q_MIN_PERIOD, hasted - Q_REFUND_SECONDS)


def _refund_rate_factor(ctx: SlotCtx) -> float:
    """Cooldown speed-up W/E/R receive from the Q refund stream.

    Q hits every ``q_period`` real seconds, each hit shaving
    ``Q_REFUND_SECONDS`` off every running cooldown. Over T wall-clock
    seconds a cooldown therefore elapses T + (T / q_period) x
    Q_REFUND_SECONDS cooldown-seconds — it completes faster by the rate
    factor 1 + Q_REFUND_SECONDS / q_period. Entries carry PRE-haste
    cooldowns (the fight engine divides by the haste factor later), and
    dividing the base cooldown by this factor commutes with that
    division, so hasted_cd / rate_factor comes out exact. (Spear of
    Shojin's extra basic-ability haste is applied fight-side only and
    is not folded into the refund inversion.)
    """
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
    stacks = min(max(int(ctx.options.get("passive_stacks", 5)), 0), PASSIVE_MAX_STACKS)
    bonus_as = PASSIVE_AS_PER_STACK * stacks
    entry = damage_entry(
        ability.get("name", "Rising Spell Force"), ctx.level, 0.0, 0.0, "physical"
    )
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
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    period = _q_hasted_period(ctx)
    entry = damage_entry(
        ability.get("name", "Mystic Shot"),
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
    return entry


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "passive_stacks",
        "type": "int",
        "default": 5,
        "min": 0,
        "max": 5,
        "label": "Passive stacks (Rising Spell Force)",
    },
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
    "W's mana refund and mana costs are not modeled",
    "Life steal applying to Q is not modeled (healing out of scope)",
]

SLOTS = {
    "P": _rising_spell_force,
    "Q": _mystic_shot,
    "W": _with_q_refund(simple_damage(attr="Bonus Magic Damage", dmg_type="magic")),
    "E": _with_q_refund(simple_damage(attr="Magic Damage", dmg_type="magic")),
    "R": _with_q_refund(simple_damage(attr="Magic Damage", dmg_type="magic")),
}

parse_abilities = build_parser(SLOTS, "Ezreal")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Ezreal",
        "revision_id": 4041697,
        "revision_timestamp": "2026-07-10T18:11:03Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
