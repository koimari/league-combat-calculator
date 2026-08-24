"""Rammus — CP10.6 full-entry-reviewed packet module, plus the E9-3 W fix.

E9-3: Defensive Ball Curl (W) is a defensive stance whose damage is the
THORNS proc against basic-attacking enemies: "enemies that use a basic
attack on-hit against Rammus are dealt 15 (+ 10% total armor) (+ 10%
total magic resistance) magic damage".  The reviewed packet misread the
stance's 'Bonus Armor' leveling row as magic damage (47 + 60% armor
against MR at rank 5); the thorns formula has NO leveling row in the
cache, so it is pinned here as wiki prose with the source cited.  The
module prices the thorns damage per enemy basic attack that lands
during the stance via the ``w_thorns_autos`` option (0 by default — the
fight engine has no incoming-auto hook, so the enemy's auto count is
explicit state); the stance's bonus armor/MR rows are the defensive
buff, not damage, and remain state.

Roadmap session (2026-08-21): closes both of Rammus' out_of_scope slots
(P, E).

  - P (Spiked Shell) is NOT the thorns reflect (that is W, above) — it is
    a pure bonus-AD conversion: "Rammus gains bonus attack damage equal to
    the sum of 15% total armor and 15% total magic resistance"
    (``data/champions.json`` Rammus P, one effect row, ``leveling: []``).
    Both ratios are corroborated by the game binary
    (``data/bin/characters/rammus.bin.json``, record
    ``Characters/Rammus/Spells/RammusPAbility/RammusP``): ``ArmorRatio``
    and ``MagicResistRatio`` are 0.15 at every rank index, and the spell's
    only calculation, ``TotalDamage``, is exactly the two
    ``StatByNamedDataValueCalculationPart`` terms (armor stat + magic
    resist stat) with no third part — so the record's stray
    ``BaseDamage`` DataValue (10.0) is NOT in the formula and is not
    modeled here (the wiki text carries no flat term either). Modeled as
    a BUFF-phase ``stat_buff`` on ``bonus_attack_damage`` (the Dr. Mundo
    ``_passive_bonus_ad`` precedent for a percent-of-a-stat passive
    steroid), so autos and every bonus-AD-scaling item see it.
    ``stat_buff``'s percent_of mode reads one stat, never a sum, so
    the addition is written in the module rather than declared.
    Reclassified out_of_scope -> modeled; this one IS a behavior change
    (see the golden receipt), not a stale label.
  - E (Frenzying Taunt): the taunt itself is already modeled (the
    ``with_control_event`` wrapper below emits the sourced 1.2-2.0s taunt),
    and the packet declares E ``kind: "no_damage"``. The cached entry does
    carry one damage row — "Monster Magic Damage" (80-160 + 70% AP) — but
    the sourced description restricts it by target class: "Monsters are
    additionally dealt magic damage upon being affected." Against this
    engine's fight target it is exactly zero: ``FightConfig.target_class``
    is a two-value label (``"champion"`` default / ``"minion"``, roadmap
    §3.1) with no monster class at all, and champion-ability class clauses
    are a named, still-open kernel boundary of that same slice (§3.1 item
    3), not a Rammus gap. Reclassified out_of_scope -> no_damage on the
    champion-target surface, with the monster row documented in
    ASSUMPTIONS rather than silently priced against a champion (the Lulu W
    control-only precedent plus the Doran's Helm minion-only boundary).
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import BUFF, CC_PER_PART, SlotCtx
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    ability_name,
    damage_entry,
    extract_cooldown,
    with_control_event,
)
from .inputs import int_option
from .module_contract import coverage

# The thorns ratios are binary DataValues (DefensiveBallCurl — W —
# DamageArmorRatio / DamageMRRatio); the cached W description prose
# corroborates ("15 (+ 10% total armor) (+ 10% total magic resistance)").
# The flat 15 stays wiki-prose-rooted: the binary's BaseDamage reads 10.0
# and the spell's own TotalDamage calculation does not reference it (a
# documented divergence, not a silent root).
_RAMMUS_W_SPELL = spell_object("Rammus", "DefensiveBallCurl")
_THORNS_BASE = 15.0
_THORNS_ARMOR_RATIO = data_value(_RAMMUS_W_SPELL, "DamageArmorRatio")
_THORNS_MAGIC_RESISTANCE_RATIO = data_value(_RAMMUS_W_SPELL, "DamageMRRatio")

# Spiked Shell's two ratios are binary DataValues (RammusP
# ArmorRatio / MagicResistRatio); the cached P description corroborates
# ("bonus attack damage equal to the sum of 15% total armor and 15% total
# magic resistance").
_RAMMUS_P_SPELL = spell_object("Rammus", "RammusP")
_SPIKED_SHELL_ARMOR_RATIO = data_value(_RAMMUS_P_SPELL, "ArmorRatio")
_SPIKED_SHELL_MAGIC_RESISTANCE_RATIO = data_value(_RAMMUS_P_SPELL, "MagicResistRatio")


def _spiked_shell(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: bonus AD equal to 15% total armour plus 15% total magic resist.

    BUFF phase so the grant lands in ``ctx.stats`` before any later slot
    reads AD, and echoed in ``stat_buff`` so the fight engine applies it
    to the auto-attack stream and to every bonus-AD item conversion (the
    Dr. Mundo ``_passive_bonus_ad`` precedent).  Spiked Shell is an innate
    with no cast, no cooldown row, and no rank of its own — the entry is a
    zero-damage carrier for the buff, exactly like the packet ``no_damage``
    row it replaces.
    """
    ability = ctx.ability("P")
    if ability is None:
        return None

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


def _defensive_ball_curl(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the thorns damage per enemy basic attack during the stance."""
    ranked = ctx.ranked("W")
    if ranked is None:
        return None
    ability, rank = ranked
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
MODULE_CC = {"Q": "immobilize", "W": CC_PER_PART, "E": "taunt", "R": "slow"}

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
        "E": lambda parser: with_control_event(
            parser,
            duration_attr="Taunt Duration",
        ),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    int_option(
        "w_thorns_autos",
        0,
        minimum=0,
        maximum=30,
        label="Enemy basic attacks during Defensive Ball Curl",
    ),
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Defensive Ball Curl) prices the thorns damage — 15 + 10% total "
    "armor + 10% total magic resistance magic damage per enemy basic "
    "attack that hits Rammus during the stance (cached W description "
    "prose; there is no leveling row). The fight engine has no "
    "incoming-auto hook, so w_thorns_autos is the explicit count of "
    "enemy autos (0 = none). The reviewed packet's misread of the "
    "'Bonus Armor' row as magic damage is removed; the stance's bonus "
    "armor/MR rows are the defensive buff and remain state.",
    "P (Spiked Shell) grants bonus attack damage equal to 15% total armor "
    "+ 15% total magic resistance (cached P description prose; the P "
    "leveling array is empty, and both ratios are corroborated by the game "
    "binary's RammusP ArmorRatio/MagicResistRatio DataValues). It is "
    "emitted as a BUFF-phase stat_buff on bonus_attack_damage, so the auto "
    "stream and bonus-AD item conversions see it. The armor/MR read is the "
    "pre-fight total: Defensive Ball Curl's own bonus armor/MR (W) are "
    "state, not stats, so the in-stance AD spike is a documented boundary. "
    "The binary's unused BaseDamage DataValue (10.0) is not modeled - the "
    "spell's own TotalDamage calculation does not reference it and the "
    "wiki text carries no flat term.",
    "E (Frenzying Taunt) deals no damage to a champion target: its one "
    "sourced damage row is 'Monster Magic Damage' (80-160 + 70% AP), "
    "restricted by the cached description to monsters ('Monsters are "
    "additionally dealt magic damage upon being affected'). This engine's "
    "target_class label has no monster value (champion/minion only) and "
    "champion-ability target-class clauses are a named open kernel "
    "boundary, so the row is documented rather than priced against a "
    "champion. The sourced taunt (1.2-2.0s by rank) is already emitted as "
    "a control event. Reclassified from out_of_scope to no_damage on the "
    "champion-target surface.",
]

# E is emitted and grants nothing the engine prices against a champion.
MODULE_COVERAGE = coverage(no_damage="E")
