"""Samira — Style (6-stack) S-rank unlock system.

Stack mechanics modeled (E3):
- P (Daredevil Impulse): damaging basic attacks and abilities against
  unique champions build Style (cap 6). Each stack grants 2.75 / 3 /
  3.25 / 3.5% (levels 1 / 6 / 11 / 16) bonus movement speed, up to
  16.5 / 18 / 19.5 / 21% at 6 stacks.  At maximum stacks (S rank),
  Samira can cast Inferno Trigger; Style stacks are consumed at the end
  of the effect.  ``p_style_stacks`` is the explicit pre-stack state.
- R (Inferno Trigger) keeps the reviewed CP10.7 packet pricing (10
  sourced 0.2s shots, E2 fix); its detail notes the S-rank requirement
  when Style is maxed.

Q (Flair), W (Blade Whirl) and E (Wild Rush) keep the reviewed CP10.7
packet pricing. All numeric values are read from the champion JSON data.

P (Daredevil Impulse) prices its second innate on the shared hit-rider
axis (``slotlib.HitRider``).  "Blade attacks, Blade Whirl, Wild Rush, and
the slash and explosives of Flair deal 2 : 21 (based on level) (+ 3.5% :
11.32% (based on level) AD) bonus magic damage, increased by 0% : 100%
(based on target's missing health)" — one declared rider on two channels:
``with_hit_rider`` attaches it to the carrying ability slots' own parts,
and ``auto_entry`` puts it on the basic-attack stream, where the engine
prices every admitted swing against the target's decayed health.

The range gate is ``p_blade_zone``: her attacks use the blade inside 200
units and Flair slashes when "a targetable enemy is in front of Samira at
the time of cast".  Position is not a request input (the Shaco Backstab
precedent), and in this fight model's duel the two conditions are the one
posture, so one option states it.  Inferno Trigger is not a carrier — the
sentence does not name it.
"""

from __future__ import annotations

from typing import Any

from .engine import ONHIT, SlotCtx
from .inputs import bool_option, float_option, int_option
from .module_helpers import at_level, no_damage
from .packet_module import build_packet_module
from .slotlib import HitRider, ability_name, extract_value, with_hit_rider

PACKET_SHA256 = "26e75628def53875687d8141eb419c4f2d3a2adb6e68ee714cd39cb4e446ad4e"

_STYLE_MAX = 6
# Style bonus movement speed per stack by level bracket (wiki prose:
# 2.75% / 3% / 3.25% / 3.5% at levels 1 / 6 / 11 / 16).
_STYLE_MS_BRACKETS = ((16, 3.5), (11, 3.25), (6, 3.0), (1, 2.75))


def _style_stacks(ctx: SlotCtx) -> int:
    return min(max(int(ctx.option("p_style_stacks")), 0), _STYLE_MAX)


# The blade rider's two cached rows both live on P's third innate and
# both carry a full 20-level array: "Bonus Magic Damage" is the flat term
# (2 : 21) and the first "Per-Level Scaling" is the total-AD percentage
# (3.5% : 11.32%).  The two later "Per-Level Scaling" rows are the same
# numbers doubled — the wiki's "up to" maximum at the target's full
# missing health, which is the amplification below rather than a term of
# its own (tests/test_samira.py pins the doubling against them).
_RIDER_FLAT_ATTRIBUTE = "Bonus Magic Damage"
_RIDER_AD_ATTRIBUTE = "Per-Level Scaling"
RIDER_MISSING_HEALTH_AMP = 1.0


def _blade_rider(ctx: SlotCtx) -> HitRider | None:
    """The Daredevil Impulse rider one carrying hit deals."""
    ability = ctx.ability("P")
    if ability is None:
        return None
    level = ctx.level
    flat = extract_value(ability, _RIDER_FLAT_ATTRIBUTE, level, level=level)
    ad_percent = extract_value(ability, _RIDER_AD_ATTRIBUTE, level, level=level)
    amount = flat + ad_percent / 100.0 * ctx.stat("attack_damage")
    if amount <= 0:
        return None
    return HitRider(
        name=ability_name(ability),
        damage_type="magic",
        amount=amount,
        missing_health_amp=RIDER_MISSING_HEALTH_AMP,
    )


def _blade_zone_rider(ctx: SlotCtx) -> HitRider | None:
    """The rider on the carriers the blade zone gates (Flair's slash)."""
    return _blade_rider(ctx) if bool(ctx.option("p_blade_zone")) else None


def _style_state(ctx: SlotCtx) -> str:
    """The Style stack state both P rows disclose."""
    stacks = _style_stacks(ctx)
    per_stack = at_level(_STYLE_MS_BRACKETS, ctx.level)
    unlock = (
        "Inferno Trigger is available and consumes them all at the end of " "the effect"
        if stacks >= _STYLE_MAX
        else f"Inferno Trigger requires S rank ({_STYLE_MAX} stacks)"
    )
    return (
        f"Style {stacks}/{_STYLE_MAX}: each stack grants {per_stack:.2f}% "
        f"bonus movement speed (up to {per_stack * _STYLE_MAX:.1f}% at "
        f"maximum stacks); {unlock}"
    )


def _daredevil_impulse(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the blade rider on the basic-attack stream, plus Style state."""
    ability = ctx.ability("P")
    if ability is None:
        return None
    rider = _blade_zone_rider(ctx)
    if rider is None:
        return no_damage(
            ctx,
            name=ability_name(ability),
            reason=(
                "Samira attacks from outside the 200-unit blade zone, so no "
                f"basic attack carries the rider.  {_style_state(ctx)}."
            ),
        )
    entry = rider.auto_entry()
    entry["detail"] = (
        f"blade attacks (inside 200 units) each deal {rider.amount:.2f} "
        "bonus magic damage, doubled at the target's full missing health.  "
        f"{_style_state(ctx)}."
    )
    return entry


_daredevil_impulse.phase = ONHIT


def _inferno_trigger(packet_r):
    """R: reviewed packet pricing + the S-rank requirement note."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_r(ctx)
        if entry is not None and _style_stacks(ctx) >= _STYLE_MAX:
            entry["detail"] = (
                f"{entry.get('detail', '')} Requires S rank ({_STYLE_MAX} "
                "Style stacks); Style stacks are consumed at the end of the "
                "effect."
            )
        return entry

    return parse


# Cached kit review: reviewed cc-free on every damaging cast.  Flair's shot
# and slash, Blade Whirl's two slashes, Wild Rush's dash and Inferno
# Trigger's torrent all only deal damage; the projectile destruction on W
# and the takedown reset on E are not control applied to a target.  P is
# absent: Daredevil Impulse rides other slots' hits and the auto stream
# rather than casting, and its knock-up fires only on the empowered basic
# attack against a target that is already a monster or airborne — an
# auto-stream effect, not an ability event.
MODULE_CC = {"Q": "none", "W": "none", "E": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Samira",
    PACKET_SHA256,
    assumption_overrides=(
        "Style caps at 6 stacks (6-second expiry and unique-hit generation not modeled); "
        "p_style_stacks is the explicit pre-stack state",
        "At 6 stacks (S rank) Inferno Trigger is available and consumes all stacks at the end of "
        "the effect",
        "Style's bonus movement speed (2.75/3/3.25/3.5% per stack by level) is state, not damage",
        "Daredevil Impulse's blade rider (2 : 21 by level + 3.5% : 11.32% total AD bonus magic "
        "damage, increased by 0% : 100% of the target's missing health) is priced on every "
        "carrier the cached sentence names: blade basic attacks, Blade Whirl's two slashes, "
        "Wild Rush's dash and Flair's blade branch.  Inferno Trigger is not named and carries "
        "none",
        "p_blade_zone (default on) is the rider's range gate: inside 200 units her attacks use "
        "the blade, and Flair slashes when a targetable enemy is in front of her.  Position is "
        "not a request input, and in this duel the two conditions are one posture, so one "
        "option states both; turning it off prices Q as the ranged shot and no attack carries "
        "the rider (Blade Whirl and Wild Rush still do)",
        "Q/W/E and R damage keep the reviewed CP10.7 packet pricing (R: 10 sourced 0.2s shots)",
        "W Blade Whirl destroys selected champion projectiles during its sourced "
        "0.75 second window; the source selection is an explicit incoming-event "
        "contract.",
    ),
    packet_tick_fixes={
        "Blade Whirl": {
            "count": 2,
            "first_tick": 0.0,
            "tick_interval": 0.75,
        },
        "Inferno Trigger": {
            "count": 10,
            "first_tick": 0.0,
            "tick_interval": 0.2,
            "dot_duration": 2.013,
        },
    },
    # Flair's shot lands on "the first enemy hit" and Wild Rush damages
    # what its dash passes through once — the boundary claim that
    # carries MODULE_CC's reviewed answers into the event ledger.  W
    # and R already author their own slash and shot timings above.
    single_hit_slots=frozenset({"Q", "E"}),
    slot_parsers={
        "P": _daredevil_impulse,
    },
    # The rider's ability half: Blade Whirl and Wild Rush carry it on every
    # cast, Flair only on its blade branch.
    slot_wrappers={
        "Q": lambda packet_q: with_hit_rider(packet_q, _blade_zone_rider),
        "W": lambda packet_w: with_hit_rider(packet_w, _blade_rider),
        "E": lambda packet_e: with_hit_rider(packet_e, _blade_rider),
        "R": _inferno_trigger,
    },
    slot_order=("P", "Q", "W", "E", "R"),
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "p_style_stacks",
        0,
        minimum=0,
        maximum=6,
        label="Style stacks (6 = S rank, R ready)",
    ),
    bool_option(
        "p_blade_zone",
        True,
        label="Samira fights inside her 200-unit blade zone (blade attacks; "
        "Flair slashes) — the Daredevil Impulse rider's range gate",
    ),
    bool_option(
        "w_active", False, label="W (Blade Whirl) active against selected skillshots"
    ),
    float_option(
        "w_active_from",
        0.0,
        minimum=0.0,
        maximum=120.0,
        label="W active start time in seconds",
    ),
    float_option(
        "w_active_seconds",
        0.0,
        minimum=0.0,
        maximum=0.75,
        label="W active seconds; zero uses the sourced 0.75 second duration",
    ),
    {
        "key": "w_blocked_skillshots",
        "type": "string_list",
        "default": [],
        "max_items": 24,
        "label": "Skillshot slots to destroy; an empty list destroys all marked skillshots",
    },
]


# No MODULE_COVERAGE: P prices the blade rider, so every slot the
# contract derives from SLOTS is modeled.
