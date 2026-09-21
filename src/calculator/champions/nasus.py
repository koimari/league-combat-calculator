"""Nasus: slot map for the archetype engine.

Q (Siphoning Strike) is the permanent-scaling stack: each stack adds 1 bonus
damage to the flat ranked row.  The count is the ``q_stacks`` option, default 0
for a fresh Nasus, because the target never dies here and the kill gain cannot
be modeled.  Q empowers the next basic attack, so it carries
``empowers_next_auto``.
E (Spirit Fire) prices the initial hit plus ten sourced 0.5s zone ticks, its
burn tail keeping item burns refreshed.
R (Fury of the Sands) prices all thirty sourced 0.5s ticks; its bonus health and
resistances are self-stats and its Siphoning Strike cooldown halving is not
modeled.
P (Soul Eater) and W (Wither) both emit rows that deal no enemy damage, and they
are not the same claim.  P is modeled, the Soul Eater heal rule pricing its
lifesteal off every physical hit through ``COVERAGE_CHANNELS``.  W is a
``no_damage`` row whose slow and cripple magnitude stays unpriced, its kind
riding ``MODULE_CC``.
"""

from typing import Any

from ..ability_atoms import ability_payload
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from ..control_spec import ControlScope
from ..damage_event_row import event_damage as _row_damage
from ..healing_helpers import HealAnchor, heal_from_damage
from .contract_vocabulary import coverage
from .engine import SlotCtx, build_parser
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import bool_option, champion_stat, int_option
from .module_helpers import ability_slot, ranked_slot
from .shared_mechanics import innate_zero_row, ticked_channel
from .slot_control import with_control_event
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .source_receipts import load_champion_sources

# E2-sourced tick cadences (data/worklists/e2-dot-ticks.json and the
# ability descriptions): Spirit Fire's zone ticks every 0.5s over 5s
# (first tick 0.5s after the initial hit's 0.264s delay); Fury of the
# Sands ticks every 0.5s over 15s.
#
# HARDCODED: verify on patch updates — wiki prose, not a leveling row:
# the cached R description states "Siphoning Strike's cooldown is
# halved" while Fury of the Sands is active (eff[1] prose).
# ROOTED IN THE BINARY: NasusR.QCDR / NasusE.Duration DataValues; the
# cached R prose ("Siphoning Strike's cooldown is halved") corroborates
# the multiplier.
_NASUS_R_SPELL = spell_object("Nasus", "NasusR")
_NASUS_E_SPELL = spell_object("Nasus", "NasusE")
_R_Q_COOLDOWN_MULTIPLIER = data_value(_NASUS_R_SPELL, "QCDR")
_E_INITIAL_DELAY = 0.264
_E_TICKS = 10
_E_TICK_INTERVAL = 0.5
_E_DOT_DURATION = data_value(_NASUS_E_SPELL, "Duration")
_R_TICK_INTERVAL = data_value(_NASUS_R_SPELL, "TickRate")
_R_DOT_DURATION = data_value(_NASUS_R_SPELL, "Duration")
_R_TICKS = int(_R_DOT_DURATION / _R_TICK_INTERVAL)


@ranked_slot
def _siphoning_strike(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: bonus damage (flat + permanent stacks) riding the next auto."""

    stacks = max(0, int(ctx.option("q_stacks")))
    bonus = (
        extract_named(ability, "Bonus Physical Damage", rank, ctx.stats, ctx.target)
        + stacks
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        bonus,
        "physical",
        # The bonus rides one empowered basic attack — one hit, at the cast
        # boundary — which is the claim that carries MODULE_CC's reviewed
        # answer for Q into the event ledger.
        event_order_certified="single_hit",
    )
    # Fury of the Sands halves Siphoning Strike's cooldown while active
    # (cached R prose).  The module prices all 30 sourced R ticks, i.e.
    # the fight sits inside R's 15s window, so the halving applies to
    # the whole fight's Q schedule; the option turns it off to price an
    # un-empowered rotation.
    if ctx.rank_for("R") >= 1 and ctx.option("r_q_cooldown_halved"):
        entry["cooldown"] *= _R_Q_COOLDOWN_MULTIPLIER
    entry["parts"] = (DamagePart("physical", bonus),)
    entry["empowers_next_auto"] = True
    entry["detail"] = (
        f"flat {bonus - stacks:.2f} + {stacks} permanent Siphoning Strike "
        f"stack(s); Q cooldown halved during Fury of the Sands"
    )
    return entry


@ranked_slot
def _spirit_fire(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: initial hit + 10 sourced 0.5s zone ticks (E2 fix)."""

    initial = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    total = initial + per_tick * _E_TICKS
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", initial, time_offset=_E_INITIAL_DELAY),
        DamagePart(
            "magic",
            per_tick,
            count=_E_TICKS,
            time_offset=_E_INITIAL_DELAY + _E_TICK_INTERVAL,
            hit_interval=_E_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _E_DOT_DURATION
    entry["detail"] = (
        f"initial hit + {_E_TICKS} sourced {_E_TICK_INTERVAL:g}s-interval "
        f"ticks (Magic Damage Per Tick x{_E_TICKS} = Spirit Fire total)"
    )
    return entry


@ranked_slot
def _fury_of_the_sands(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: all 30 sourced 0.5s ticks (E2 fix)."""

    return ticked_channel(
        ctx,
        ability,
        rank,
        attr="Magic Damage Per Tick",
        dmg_type="magic",
        ticks=_R_TICKS,
        interval=_R_TICK_INTERVAL,
        dot_duration=_R_DOT_DURATION,
        detail=(
            f"{_R_TICKS} sourced {_R_TICK_INTERVAL:g}s-interval ticks "
            f"(Magic Damage Per Tick x{_R_TICKS} = Fury of the Sands total)"
        ),
    )


def _soul_eater(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: innate lifesteal with no enemy damage, self-heal via healing.py."""

    return innate_zero_row(
        ctx,
        detail=(
            "Innate lifesteal: heals for 12% / 18% / 24% (based on level; "
            "game-file breakpoints 7/13) of the post-mitigation physical "
            "basic-attack/on-hit damage dealt — authored by the Soul Eater "
            "heal rule (HEALING_RULE_CHAMPIONS), no enemy damage."
        ),
        dmg_type="physical",
    )


@ability_slot()
def _wither(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """W: slow/cripple — no enemy damage."""
    return damage_entry(
        ability_name(ability),
        ctx.rank_for(),
        extract_cooldown(ability, ctx.rank_for()),
        0.0,
        "magic",
        parts=(),
        detail="Slow and attack-speed cripple: CC only, no damage.",
    )


OPTIONS: list[dict[str, Any]] = [
    bool_option(
        "r_q_cooldown_halved",
        True,
        label="Fury of the Sands halves Siphoning Strike's cooldown "
        "(effective while R is ranked)",
        rotation={"role": "irrelevant", "slot": "Q"},
    ),
    int_option(
        "q_stacks",
        0,
        minimum=0,
        maximum=5000,
        label="Permanent Siphoning Strike stacks (each adds 1 bonus damage "
        "to Q; 3 per minion kill, 12 per champion kill)",
        rotation={"role": "self_state", "slot": "Q"},
    ),
]

ASSUMPTIONS = [
    "Q (Siphoning Strike) bonus damage is the rank flat 40 to 120 plus 100% of the "
    "q_stacks option total.",
    "Q's permanent gain, +3 per kill and +12 for champions, is not modeled: the "
    "option is the stack state.",
    "Q empowers the next basic attack, so its casts cap at the fight's auto count.",
    "With no auto stream Q forces its own swing.",
    "E (Spirit Fire) prices the initial hit + 10 sourced 0.5s zone "
    "ticks (E2 fix, unchanged from the reviewed packet)",
    "R (Fury of the Sands) prices all 30 sourced 0.5s ticks; its bonus health and "
    "resistances are self-stats.",
    "With R ranked and r_q_cooldown_halved on (the default), Siphoning Strike's "
    "cooldown halves.",
    "The module prices the whole fight inside R's 15s window, matching those 30 "
    "ticks.",
    "P (Soul Eater) life steal is 12/18/24% by level, breakpoints at 7 and 13 in the "
    "game file.",
    "It heals from post-mitigation physical basic-attack and on-hit damage; W's slow "
    "is a zero-damage row.",
    "W (Wither) is control only, a slow and attack-speed cripple with no enemy-damage "
    "formula.",
    "It emits the sourced zero-damage row as no_damage, and W is already a cast slot "
    "here.",
]

SLOTS = {
    "Q": _siphoning_strike,
    # Wither prices no damage; its slow is the effect's own window
    # ("ages the target enemy champion for 5 seconds"), carried by the
    # slot's active-duration atom, and its strength is the cached
    # "Maximum Slow" row (47/59/71/83/95%) at the end of that window.
    # The initial 35% and the cripple half are prose only and stay
    # unpriced: one slot carries one kind.  "the target enemy champion"
    # is one enemy, so the slow is allocated to the first roster enemy.
    "W": with_control_event(
        _wither,
        duration_source="active",
        magnitude_attr="Maximum Slow",
        scope=ControlScope.ONE_TARGET,
    ),
    "E": _spirit_fire,
    "R": _fury_of_the_sands,
    "P": _soul_eater,
}

# Cached kit review.  Nothing Nasus damages with applies control: Q only
# empowers a basic attack to "deal bonus physical damage", E's fire deals
# magic damage and "inflict[s] them with armor reduction" (a resistance
# shred, not a control class), and R "deals magic damage every 0.5 seconds
# to nearby enemies" while buffing his own stats.  W is the kit's one
# control ("slowing them by 35% and crippling them"); it deals no damage,
# so the answer rides its entry as a sourced ControlEvent rather than on
# a part.  P (lifesteal) damages nothing and applies none.
MODULE_CC = {"Q": "none", "W": "slow", "E": "none", "R": "none", "P": "none"}

parse_abilities = build_parser(SLOTS, "Nasus", cc_kinds=MODULE_CC)

# P emits a row that prices no enemy damage; what the engine prices for
# the slot is Soul Eater's lifesteal, authored by the healing rule below
# (48.6 over a level-18 itemless timed fight with autos).  W is a cast
# slot emitting the pinned packet's sourced zero-damage row: no_damage,
# not a gap — only its slow/cripple magnitude stays unpriced.
MODULE_COVERAGE = coverage(no_damage="W")
COVERAGE_CHANNELS = {"P": ("self_healing_rule",)}


# Soul Eater is level-gated lifesteal, not an ability packet: "Nasus has
# 12% / 18% / 24% (based on level) life steal" against the physical
# damage his attacks and on-hits deal, so the rule pays per damaging hit
# rather than per cast.
_SOUL_EATER_BREAKPOINTS = ((13, 0.24), (7, 0.18), (1, 0.12))


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Price Soul Eater's lifesteal off every physical basic-attack hit.

    The empowered swing counts.  Siphoning Strike does not replace a basic
    attack, it rides one ("Nasus's next basic attack ... deals bonus
    physical damage"), so the engine reattributes that swing to the Q row
    and publishes no ``auto_attacks`` row for it.  A rule reading only
    ``auto_attacks`` therefore pays nothing at all once R halves Q's
    cooldown and every swing is empowered.  Q rows and ``auto_attacks``
    rows partition the swings, so reading both is exactly one payment per
    swing, never two.
    """
    healing: list[dict[str, Any]] = []
    level = max(1, int(champion_stat(ctx.champion_stats, "level")))
    ratio = next(
        share for threshold, share in _SOUL_EATER_BREAKPOINTS if level >= threshold
    )
    empowered = bool(
        ability_payload(ctx.ability_damages, "Q").get("empowers_next_auto")
    )

    def is_swing(source: str) -> bool:
        if source == "auto_attacks" or source.startswith("on_hit_"):
            return True
        return empowered and source == "Q"

    for payment in ctx.payments(HealAnchor.DAMAGING_HIT, is_swing):
        event = payment.event
        if event.get("damage_type") != "physical":
            continue
        amount = max(0.0, _row_damage(event)) * ratio
        heal_from_damage(healing, event, amount, "Soul Eater")
    return healing


SELF_HEALING_RULE = self_healing_rule("Nasus")(derive_self_healing)

SOURCES = load_champion_sources("Nasus")
