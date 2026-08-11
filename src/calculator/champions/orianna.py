"""Orianna — slot map for the archetype engine.

Why each slot is non-generic:
- P (Clockwork Windup) is a stack-ramped on-hit the generic path misreads:
  the JSON's P[0] holds THREE leveling rows and the generic on-hit
  detector sums the wrong one (the pre-computed 2-stack row, leveling[2])
  as a flat per-hit value. Only leveling[0] (0-stack base, LEVEL-indexed
  + 15% AP) is a source of truth; leveling[1] is the per-stack increment
  (15% of base, + 2.25% AP) and leveling[2] the derived 2-stack total.
  The custom fn reads base + increment, derives the stack cap from the
  2-stack row (cross-checked, fail-loudly), and emits a ``stack_ramp``
  on-hit payload so the fight engine models the natural single-target
  ramp: auto 1 at 0 stacks (x1.00), auto 2 at 1 (x1.15), auto 3+ at 2
  (x1.30). The passive applies SPELL effects, not on-hit effects — it
  never declares ``applies_item_on_hits``.
- Q must read "Magic Damage" explicitly so the 70%-effectiveness
  "Reduced Damage" row (secondary targets) can never be picked up — the
  single-target calc always uses full damage on the primary target.
- W reads "Magic Damage" explicitly; the speed-field/slow row
  ("Movement Speed Modifier") is utility and must not leak into damage.
- E's pass-through damage is gated by the ``e_passes_through_target``
  option (false = pure utility cast, zero damage); the shield
  ("Shield Strength") and ball-attached resistances ("Bonus
  Resistances") are defensive-only and excluded.
- R reads "Magic Damage" explicitly for symmetry with the rest of the
  kit; the sourced stun is attached to the damage part.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    on_hit_entry,
    simple_damage,
    sum_modifiers,
    with_control,
)


def _clockwork_windup(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: bonus magic on every basic attack, ramping with Winding stacks.

    Emits the 0-stack base as ``damage_per_hit`` plus a ``stack_ramp``
    payload; the fight engine applies hit k at min(k, cap) stacks.
    All three numbers come from the JSON's own leveling rows — the stack
    cap is reconstructed from the pre-computed 2-stack row rather than
    hardcoded, and a mismatch raises (patch-drift guard).
    """
    ability = ctx.ability()
    if ability is None:
        return None

    base_row = find_named_leveling(ability, "Bonus Magic Damage")
    per_stack_row = find_named_leveling(ability, "Per-Level Scaling")
    full_row = find_named_leveling(ability, "Bonus Magic Damage", occurrence=1)
    if base_row is None or per_stack_row is None or full_row is None:
        raise ValueError(
            "Orianna P: expected 'Bonus Magic Damage' (0-stack), "
            "'Per-Level Scaling' (per-stack increment), and a second "
            "'Bonus Magic Damage' (2-stack) leveling row in the passive JSON"
        )

    base = sum_modifiers(base_row, ctx.level, ctx.stats, ctx.target)
    per_stack = sum_modifiers(per_stack_row, ctx.level, ctx.stats, ctx.target)
    full = sum_modifiers(full_row, ctx.level, ctx.stats, ctx.target)

    max_stacks = round((full - base) / per_stack) if per_stack > 0 else 0
    if max_stacks < 1 or abs(base + max_stacks * per_stack - full) > 0.5:
        raise ValueError(
            f"Orianna P: full-stack row ({full:g}) is not base ({base:g}) "
            f"+ N x per-stack ({per_stack:g}) — the passive JSON shape "
            "changed; re-derive the stack ramp"
        )

    entry = on_hit_entry(ability.get("name", "Clockwork Windup"), base, "magic")
    entry["on_hit"]["stack_ramp"] = {
        "damage_per_stack": per_stack,
        "max_stacks": max_stacks,
    }
    return entry


_clockwork_windup.phase = ONHIT


def _command_attack(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: primary-target magic damage plus reduced hits beyond the first.

    The cached prose: the ball "deal[s] magic damage to enemies it
    passes through and nearby enemies upon arrival, reduced to 70%
    against those hit beyond the first" — the "Reduced Damage" row is
    exactly 70% of "Magic Damage" at every rank.  Each secondary target
    selected via ``q_secondary_targets`` takes one reduced hit.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    primary = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    reduced = extract_named(ability, "Reduced Damage", rank, ctx.stats, ctx.target)
    secondary = min(max(int(ctx.options.get("q_secondary_targets", 0)), 0), 5)
    total = primary + reduced * secondary
    entry = damage_entry(
        ability.get("name", "Command: Attack"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    parts = [DamagePart("magic", primary)]
    if secondary:
        parts.append(DamagePart("magic", reduced, count=secondary))
        entry["detail"] = (
            f"primary target + {secondary} secondary target(s) at the "
            f"sourced {reduced / primary * 100:g}% Reduced Damage row each"
        )
    entry["parts"] = tuple(parts)
    return entry


def _command_protect(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: pass-through magic damage; zero when the ball stops on an ally.

    ``extract_named`` skips effect[0]'s "Bonus Resistances" and the
    "Shield Strength" row by name — only the fly-through "Magic Damage"
    is a damage source, and only when the ball crosses the target.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total = 0.0
    if ctx.options.get("e_passes_through_target", True):
        total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    return damage_entry(
        ability.get("name", "Command: Protect"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "q_secondary_targets",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 5,
        "label": (
            "Enemies hit by the ball beyond the first (each takes the "
            "sourced 70% Reduced Damage row)"
        ),
        "rotation": {"role": "irrelevant", "slot": "Q"},
    },
    {
        "key": "e_passes_through_target",
        "type": "bool",
        "default": True,
        "label": "E ball passes through target",
    },
]

ASSUMPTIONS = [
    "Passive stacks ramp naturally on a single target: auto 1 at 0 "
    "stacks, auto 2 at +15%, auto 3+ at +30%; stacks never drop "
    "mid-fight (4s refresh window, sustained attacking)",
    "Passive applies spell effects, not on-hit effects — it does not "
    "trigger on-hit items",
    "Q prices the primary target at full damage plus one sourced 70% "
    "Reduced Damage hit per q_secondary_targets (default 0) — the "
    "cached prose's 'reduced to 70% against those hit beyond the first'",
    "W speed field and slow are not modeled (utility)",
    "E shield (55-195 +45% AP) and bonus armor/MR (6-30) are not "
    "modeled (defensive only)",
    "E damage assumes the ball passes through the target (toggleable "
    "via champion option)",
    "R stuns the target for the sourced 0.75-second interval; the pull is "
    "utility and is not modeled",
]

SLOTS = {
    "Q": _command_attack,
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": _command_protect,
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "P": _clockwork_windup,
}
SLOTS["R"] = with_control(
    SLOTS["R"],
    kind="stun",
    duration_attr="Stun Duration",
)

parse_abilities = build_parser(SLOTS, "Orianna")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Orianna",
        "revision_id": 3892665,
        "revision_timestamp": "2025-05-02T11:28:16Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
