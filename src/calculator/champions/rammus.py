"""Rammus: full-entry-reviewed packet module.

W (Defensive Ball Curl) does damage through thorns, not the stance:
enemies that basic attack Rammus take 15 (+ 10% total armor) (+ 10%
total magic resistance) magic.  That formula has no cached leveling row,
so its flat term and ratios are rooted in named binary fields, and the
fight engine has no incoming-auto hook, so the enemy's attack count is
explicit state through ``w_thorns_autos``, 0 by default.  The stance's
bonus armor and magic resistance rows are the defensive buff.
P (Spiked Shell) grants bonus attack damage equal to 15% total armor
plus 15% total magic resistance, a BUFF-phase ``stat_buff`` so autos and
every bonus-AD item see it.  ``stat_buff``'s ``percent_of`` reads one
stat and never a sum, so the addition is written here.  The binary
record's ``BaseDamage`` of 10.0 is not in its ``TotalDamage``
calculation and is not priced.
E (Frenzying Taunt) is ``no_damage`` on the champion surface, its taunt
emitted by ``with_control_event``.  Its cached "Monster Magic Damage"
row is restricted by target class, and ``FightConfig.target_class``
carries champion and minion only.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from ..control_spec import ControlScope
from .contract_vocabulary import coverage
from .engine import BUFF, SlotCtx
from .inputs import int_option
from .module_helpers import ability_slot, ranked_slot
from .packet_module import build_packet_module
from .slot_cc import CC_PER_PART
from .slot_control import with_control_event
from .slot_entries import STEROID_ZERO, damage_entry
from .slot_extract import ability_name, extract_cooldown

# The thorns flat damage and ratios are binary DataValues (DefensiveBallCurl
# — W — FlatDamageReturn / DamageArmorRatio / DamageMRRatio); the cached W
# description prose
# corroborates ("15 (+ 10% total armor) (+ 10% total magic resistance)").
# The binary's separate BaseDamage reads 10.0; the active ReturnDamageCalc
# uses FlatDamageReturn instead.
_RAMMUS_W_SPELL = spell_object("Rammus", "DefensiveBallCurl")
_THORNS_BASE = data_value(_RAMMUS_W_SPELL, "FlatDamageReturn")
_THORNS_ARMOR_RATIO = data_value(_RAMMUS_W_SPELL, "DamageArmorRatio")
_THORNS_MAGIC_RESISTANCE_RATIO = data_value(_RAMMUS_W_SPELL, "DamageMRRatio")

# Spiked Shell's two ratios are binary DataValues (RammusP
# ArmorRatio / MagicResistRatio); the cached P description corroborates
# ("bonus attack damage equal to the sum of 15% total armor and 15% total
# magic resistance").
_RAMMUS_P_SPELL = spell_object("Rammus", "RammusP")
_SPIKED_SHELL_ARMOR_RATIO = data_value(_RAMMUS_P_SPELL, "ArmorRatio")
_SPIKED_SHELL_MAGIC_RESISTANCE_RATIO = data_value(_RAMMUS_P_SPELL, "MagicResistRatio")


@ability_slot("P")
def _spiked_shell(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: bonus AD equal to 15% total armour plus 15% total magic resist.

    BUFF phase so the grant lands in ``ctx.stats`` before any later slot
    reads AD, and echoed in ``stat_buff`` so the fight engine applies it
    to the auto-attack stream and to every bonus-AD item conversion (the
    Dr. Mundo ``_passive_bonus_ad`` precedent).  Spiked Shell is an innate
    with no cast, no cooldown row, and no rank of its own — the entry is a
    zero-damage carrier for the buff, exactly like the packet ``no_damage``
    row it replaces.
    """

    armor = ctx.stat("armor")
    magic_resistance = ctx.stat("magic_resistance")
    bonus_ad = (
        _SPIKED_SHELL_ARMOR_RATIO * armor
        + _SPIKED_SHELL_MAGIC_RESISTANCE_RATIO * magic_resistance
    )
    ctx.stats["bonus_attack_damage"] = ctx.stat("bonus_attack_damage") + bonus_ad
    ctx.stats["attack_damage"] = ctx.stat("attack_damage") + bonus_ad
    entry = damage_entry(
        ability_name(ability),
        ctx.level,
        0.0,
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_damage": bonus_ad}
    entry["detail"] = (
        f"+{bonus_ad:.2f} bonus attack damage = "
        f"{_SPIKED_SHELL_ARMOR_RATIO * 100:g}% of {armor:.1f} armour + "
        f"{_SPIKED_SHELL_MAGIC_RESISTANCE_RATIO * 100:g}% of "
        f"{magic_resistance:.1f} magic resistance; Spiked Shell deals no "
        "damage of its own, and reads the build's resistances rather than "
        "the stance's, since W's bonus armour is a state row rather than "
        "a stat_buff"
    )
    return entry


_spiked_shell.phase = BUFF

PACKET_SHA256 = "e48aa5766d5565b485a6d7fa34421f25d11f56fdcfdec5bb0c0823acc991e0f0"


@ranked_slot
def _defensive_ball_curl(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: the thorns damage per enemy basic attack during the stance."""
    autos = min(max(int(ctx.option("w_thorns_autos")), 0), 30)
    armor = float(ctx.stat("armor") or 0.0)
    magic_resistance = float(ctx.stat("magic_resistance") or 0.0)
    per_auto = (
        _THORNS_BASE
        + _THORNS_ARMOR_RATIO * armor
        + _THORNS_MAGIC_RESISTANCE_RATIO * magic_resistance
    )
    total = per_auto * autos
    # The thorns row answers per part (MODULE_CC declares W CC_PER_PART),
    # because it can only answer when it prices a single reactive hit: the
    # stance retaliates against enemy basic attacks, whose arrival times
    # nothing sources, so a row of several of them is one aggregate with no
    # per-hit boundary for the marker to ride.  The stance applies no
    # control either way, and says so wherever the ledger can hear it.
    certified = autos <= 1
    entry = damage_entry(
        "Defensive Ball Curl (thorns)",
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
        cc_kind="none" if certified else None,
        event_order_certified="single_hit" if certified else None,
    )
    # The fight engine reads ONLY ``parts`` (damage_entry's contract), so
    # the count here is the real one: a ``count=max(autos, 1)`` floor priced
    # ONE full thorns proc at the DEFAULT ``w_thorns_autos`` of 0 - 23.50
    # phantom mitigated damage in a no-item level-18 fight, with autos=0 and
    # autos=1 scoring identically.  Zero enemy autos must cost zero, so at
    # autos <= 1 the entry keeps damage_entry's own single part (amount ==
    # total, so 0 when no auto landed) and only a multi-auto row overrides.
    if autos > 1:
        entry["parts"] = (DamagePart("magic", per_auto, count=autos),)
    entry["detail"] = (
        f"thorns: {per_auto:.2f} magic damage per enemy basic attack "
        f"(15 + 10% total armor ({armor:.1f}) + 10% total magic "
        f"resistance ({magic_resistance:.1f})) x {autos} auto(s) that hit "
        "Rammus during the stance; the stance's bonus armor/MR rows are "
        "the defensive buff, not damage"
    )
    return entry


# Cached kit review.  Q's collision deals magic damage while "knocking them
# back 125 units" and the enemies hit "are then stunned ... as well as
# slowed": two immobilize kinds from one cast, which is what the
# un-narrowed "immobilize" states.  R's impact "deals magic damage to
# nearby enemies and slows them for 1.5 seconds"; the epicentre knock-up is
# gated on Soaring Slam being cast during Powerball, a combination this
# module does not price.  W answers per part (``_defensive_ball_curl``).  E
# taunts, but "monsters are additionally dealt magic damage" is its only
# damage row, so against a champion it prices nothing and there is no part
# for a marker to ride: its sourced taunt is authored as a typed
# ``control_events`` interval by the slot wrapper below, which is why E is
# absent here.  P is a stat innate.
# E (Frenzying Taunt) prices no damage against a champion, so its reviewed
# control rides the entry as a sourced ControlEvent rather than on a part.
MODULE_CC = {
    "Q": "immobilize",
    "W": CC_PER_PART,
    "E": "taunt",
    "R": "slow",
    "P": "none",
}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Rammus",
    PACKET_SHA256,
    # Powerball stops on the enemy it collides with and Soaring Slam lands
    # one impact — the boundary claim that carries MODULE_CC's reviewed
    # answers into the event ledger.
    single_hit_slots=frozenset({"Q", "R"}),
    slot_parsers={
        "W": _defensive_ball_curl,
        "P": _spiked_shell,
    },
    slot_wrappers={
        # "taunts the target enemy champion or monster for a duration":
        # one enemy holds it, so it is allocated to the first roster enemy.
        "E": lambda parser: with_control_event(
            parser,
            duration_attr="Taunt Duration",
            scope=ControlScope.ONE_TARGET,
        ),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "w_thorns_autos",
        0,
        minimum=0,
        maximum=30,
        label="Enemy basic attacks during Defensive Ball Curl",
        rotation={"role": "self_state", "slot": "W"},
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "W (Defensive Ball Curl) prices thorns of 15 + 10% total armor + 10% total magic "
    "resist per enemy hit.",
    "That is cached W prose with no leveling row, per enemy basic attack landing "
    "during the stance.",
    "The engine has no incoming-auto hook, so w_thorns_autos is the explicit enemy "
    "auto count (0 = none).",
    "The stance's bonus armor and MR rows are the defensive buff and remain state.",
    "P (Spiked Shell) grants bonus AD of 15% total armor + 15% total magic resist "
    "(cached P prose).",
    "The P leveling array is empty; the binary's RammusP ArmorRatio and "
    "MagicResistRatio corroborate.",
    "It is a buff-phase stat_buff on bonus_attack_damage, so autos and bonus-AD items "
    "see it.",
    "P reads the pre-fight total: W's own bonus armor and MR are state, so the "
    "in-stance spike is a boundary.",
    "The binary's unused BaseDamage 10.0 is not modeled: TotalDamage never references "
    "it.",
    "E (Frenzying Taunt)'s one damage row is Monster Magic Damage, and target_class "
    "has no monster value.",
    "E deals no damage to a champion target: the cached description restricts that "
    "row to monsters.",
    "The row is 80 to 160 + 70% AP, and the class gap is a named open kernel "
    "boundary, so E is documented.",
    "E's sourced 1.2 to 2.0s taunt by rank is already emitted as a control event.",
]

# E is emitted and grants nothing the engine prices against a champion.
MODULE_COVERAGE = coverage(no_damage="E")
