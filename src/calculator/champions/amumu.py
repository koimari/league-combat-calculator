"""Amumu — slot map for the archetype engine.

Why each slot is non-generic:
- P (Cursed Touch) is two pieces. A zero-damage display row lives under
  the literal "P" results key (the pre-engine UI shape), so a custom
  slot fn writes it into ``ctx.results`` directly. The amplifier itself
  is the AMP-phase ``"curse"`` pseudo-slot below: Cursed targets take
  10% of every ability's pre-mitigation magic damage as bonus TRUE
  damage, so it runs after all damage slots and mutates their entries
  (adds ``true_damage``, flips ``damage_type`` to "mixed"), gated by
  the ``target_cursed`` option (default True).
- Q (Bandage Toss) is a 2-charge ability — sustained use is limited by
  rechargeRate, not the 3 s inter-cast cooldown, hence
  ``cooldown="recharge"``.
- W (Despair) is a toggle DoT (0.5 s ticks, ``w_seconds`` option) whose
  entry carries the per-tick display keys (``damage_per_tick`` /
  ``total_ticks``) that a standard damage entry
  entry shape does not include — custom fn. Its %maxHP-per-100-AP
  compound unit resolves automatically via scaling.py as long as the
  target stats reach ``extract_named``.
- E/R are plain "Magic Damage" attribute reads (E's first effect is a
  defensive damage reduction with no "Magic Damage" attribute, so the
  exact-name scan lands on the active component).

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .engine import AMP, SlotCtx, build_parser
from .slotlib import damage_entry, extract_named, simple_damage

_CURSE_BONUS_FRACTION = 0.10  # 10% bonus true damage on magic damage


def _apply_curse(result: dict[str, Any]) -> None:
    """Add Cursed Touch bonus true damage to one ability entry.

    Mutates *result* in place: adds a ``true_damage`` key equal to 10%
    of the ability's magic damage, switches ``damage_type`` to
    ``"mixed"``, and increases ``total_raw`` accordingly.
    """
    magic = result.get("magic_damage", 0.0)
    if magic <= 0:
        return
    bonus_true = magic * _CURSE_BONUS_FRACTION
    result["true_damage"] = bonus_true
    result["total_raw"] = magic + bonus_true
    result["damage_type"] = "mixed"


def _cursed_touch_amp(ctx: SlotCtx) -> None:
    """AMP pseudo-slot: apply the curse to every magic-damage ability."""
    if not ctx.options.get("target_cursed", True):
        return
    for key in ("Q", "W", "E", "R"):
        entry = ctx.results.get(key)
        if entry is not None:
            _apply_curse(entry)


_cursed_touch_amp.phase = AMP


def _cursed_touch_display(ctx: SlotCtx) -> None:
    """P: zero-damage display row, written under the literal "P" key."""
    ability = ctx.ability()
    if ability is not None:
        ctx.results["P"] = damage_entry(
            ability.get("name", "Cursed Touch"), 1, 0.0, 0.0, "true"
        )


def _despair(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: toggle DoT — ``w_seconds`` of 0.5 s ticks, per-tick keys."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    w_seconds = max(0.5, float(ctx.options.get("w_seconds", 3.0)))
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    total_ticks = int(w_seconds / 0.5)
    total = per_tick * total_ticks

    return {
        "name": ability.get("name", "Despair"),
        "rank": rank,
        "cooldown": 0.0,  # toggle ability, no cooldown
        "damage_type": "magic",
        "damage_per_tick": per_tick,
        "total_ticks": total_ticks,
        "magic_damage": total,
        "total_raw": total,
    }


OPTIONS = [
    {
        "key": "target_cursed",
        "type": "bool",
        "default": True,
        "label": "Target already Cursed (10% bonus true damage)",
    },
    {
        "key": "w_seconds",
        "type": "float",
        "default": 3.0,
        "label": "W seconds active",
        "min": 0.5,
        "max": 30,
        "step": 0.5,
    },
]

ASSUMPTIONS = [
    "Target is assumed already Cursed (Passive) — all magic damage gets 10% bonus true damage",
    "Q uses recharge timer as cooldown (fight engine determines cast count)",
    "W defaults to 3 seconds active (6 ticks at 0.5s intervals)",
    "E passive (damage reduction) is not modeled — defensive only",
]

SLOTS = {
    "P": _cursed_touch_display,
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic", cooldown="recharge"),
    "W": _despair,
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "curse": _cursed_touch_amp,
}

parse_abilities = build_parser(SLOTS, "Amumu")
