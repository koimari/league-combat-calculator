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

from ..ability_spec import DamagePart
from .engine import AMP, SlotCtx, build_parser
from .slotlib import (
    ability_name,
    damage_entry,
    extract_named,
    simple_damage,
    with_control,
)
from .source_receipts import load_champion_sources
from .inputs import bool_option, float_option

_CURSE_BONUS_FRACTION = 0.10  # 10% bonus true damage on magic damage
_W_TICK_SECONDS = 0.5  # Despair "deal[s] magic damage every 0.5 seconds"


def _apply_curse(result: dict[str, Any]) -> None:
    """Add Cursed Touch bonus true damage to one ability entry.

    Mutates *result* in place: appends one true-damage part per magic part,
    switches ``damage_type`` to ``"mixed"``, and increases ``total_raw``
    accordingly.

    The rider is "10% bonus true damage from all incoming pre-mitigation
    magic damage" — per instance, so it mirrors the magic part it rides:
    same count, same authored timing.  One lumped true part would sum to
    the same number and then strand the entry's timing, because a row's
    events are authored only when EVERY part places itself.
    """
    parts = result.get("parts", ())
    magic_parts = [part for part in parts if part.damage_type == "magic"]
    magic = sum(part.amount * part.count for part in magic_parts)
    if magic <= 0:
        return
    result["total_raw"] = magic + magic * _CURSE_BONUS_FRACTION
    result["damage_type"] = "mixed"
    result["parts"] = parts + tuple(
        DamagePart(
            "true",
            part.amount * _CURSE_BONUS_FRACTION,
            count=part.count,
            time_offset=part.time_offset,
            hit_interval=part.hit_interval,
        )
        for part in magic_parts
    )


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
        ctx.results["P"] = damage_entry(ability_name(ability), 1, 0.0, 0.0, "true")


def _despair(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: toggle DoT — ``w_seconds`` of 0.5 s ticks, per-tick keys."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    w_seconds = max(0.5, float(ctx.option("w_seconds")))
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    total_ticks = int(w_seconds / _W_TICK_SECONDS)
    total = per_tick * total_ticks

    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": 0.0,  # toggle ability, no cooldown
        "damage_type": "magic",
        "damage_per_tick": per_tick,
        "total_ticks": total_ticks,
        # The toggle's window is one aggregate placed at the cast, and the
        # part says so: an authored ``time_offset`` is what carries the
        # row's reviewed control answer into the event ledger.  It does NOT
        # certify ``single_hit`` — three seconds of a toggle is not one
        # landing — and it does not split into its 0.5 s ticks, which would
        # re-price Shadowflame.
        "parts": (DamagePart("magic", total, time_offset=0.0),),
        "total_raw": total,
    }


OPTIONS = [
    bool_option(
        "target_cursed", True, label="Target already Cursed (10% bonus true damage)"
    ),
    float_option(
        "w_seconds", 3.0, minimum=0.5, maximum=30, label="W seconds active", step=0.5
    ),
]

ASSUMPTIONS = [
    "Target is assumed already Cursed (Passive) — all magic damage gets 10% bonus true damage",
    "Q uses recharge timer as cooldown (fight engine determines cast count)",
    "Q's sourced 1-second stun and R's sourced 1.5-second stun count as "
    "target action downtime",
    "W defaults to 3 seconds active (6 ticks at 0.5s intervals)",
    "E passive reduces each physical raw damage instance with its sourced rank, bonus-resist scaling, and 50% instance cap",
]

# Q, E and R each land once at the cast: the bandage "deals magic damage
# to the first enemy hit", Tantrum "deal[s] magic damage to nearby
# enemies", and Curse of the Sad Mummy "deal[s] magic damage" as it
# entangles.  Cursed Touch then splits each of those landings into a magic
# and a true part, which is still one landing.
SLOTS = {
    "P": _cursed_touch_display,
    "Q": with_control(
        simple_damage(
            attr="Magic Damage",
            dmg_type="magic",
            cooldown="recharge",
            event_order_certified="single_hit",
        ),
        duration_attr="Stun Duration",
    ),
    "W": _despair,
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        duration_attr="Stun Duration",
    ),
    "curse": _cursed_touch_amp,
}

# Reviewed crowd control, read from the cached kit.  Q (Bandage Toss)
# "deals magic damage to the first enemy hit, stunning them for 1 second
# and pulling him to them"; R (Curse of the Sad Mummy) deals its damage
# "as well as knocking them down and stunning them for 1.5 seconds".  W
# (Despair) is a damage toggle and E (Tantrum) "releases his anger,
# dealing magic damage to nearby enemies" — neither controls anything, a
# reviewed absence.  P is the amplifier itself: its display row prices
# nothing, so it carries no declaration.
MODULE_CC = {"Q": "stun", "W": "none", "E": "none", "R": "stun"}

parse_abilities = build_parser(SLOTS, "Amumu", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Amumu")
