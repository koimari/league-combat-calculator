"""Singed — CP10.7 full-entry-reviewed packet module.

Roadmap session (2026-08-21): closes all 3 of Singed's out_of_scope slots
(P, W, R) — Q and E were already modeled.

  - P (Noxious Slipstream): the pinned packet spec already declares P
    ``kind: "no_damage"`` (``static/reviewed-packets.json``), so
    ``build_packet_module`` was already returning a proper zero-damage
    entry for it — ``MODULE_COVERAGE`` was simply stale, still reading
    "out_of_scope" for a slot the parser had already closed. Cross-checked
    against both atom captures and the game binary: neither
    ``data/atoms/singed.atoms.json``/``v2/singed.atoms.v2.json`` nor
    ``data/bin/characters/singed.bin.json``'s
    ``Characters/Singed/Spells/SingedPAbility/SingedP`` record carries a
    damage/damage-type field anywhere — only ``MSPercent`` (0.25),
    ``MSDuration`` (2.0s), ``PerTargetCD`` (8.0s), and ``TriggerArea``
    (225.0) — matching the wiki's "25% bonus movement speed per stack,
    stacks up to 25, 8s same-target cooldown, 225-radius trigger" text
    exactly. Reclassified to no_damage (no behavior change; the parser
    output is unchanged, only the label was wrong).
  - W (Mega Adhesive): also already declared ``kind: "no_damage"`` in the
    packet spec — same stale-label bug as P. Confirmed against the
    binary: ``Characters/Singed/Spells/MegaAdhesiveAbility/MegaAdhesive``'s
    ``DataValues`` are exactly ``SlowPercent``, ``WDuration``,
    ``WRadius``, ``DelayExecute``, ``Radius`` — no base-damage or
    damage-ratio field exists for this spell at all, matching the wiki
    ("creates a field ... that grounds enemies within and slows them" —
    no damage clause). Note for the atoms record itself:
    ``data/atoms/singed.atoms.json`` (v1) carries two now-provably-wrong
    entries tagged ``behavior: "MegaAdhesive"`` — ``damage.aoe`` and
    ``damage.execute`` with provenance evidence ``"Execution"``/``"True
    damage"`` — that do not correspond to anything in Mega Adhesive's
    game-file spell object (no execute threshold, no true-damage field,
    no ``NonChampionDamageCap``-style clamp). The v2 atoms capture
    (``data/atoms/v2/singed.atoms.v2.json``) already dropped both and
    replaced them with the correct ``crowd-control-mobility.ground`` /
    ``crowd-control-mobility.slow`` pair, so this is stale v1 extraction
    noise already superseded, not a live discrepancy — flagged here for
    the record, not corrected (the atoms files are outside this module's
    scope). Reclassified to no_damage on the v2/binary evidence, no
    behavior change.
  - R (Insanity Potion): unlike P/W, the packet spec's "no_damage"
    declaration for R undersold it — Insanity Potion IS a real, sourced
    steroid (Vayne R / Bel'Veth True Form / Syndra P precedent: a BUFF-
    phase ``stat_buff``), so it gets a slot-parser override rather than
    just a relabel. The wiki's single "Bonus Stats" leveling row
    (``data/champions.json`` Singed R effects[0], values 25/55/85 by
    rank) is confirmed by the game binary
    (``InsanityPotionAbility/InsanityPotion``'s ``StatAmount`` DataValue,
    padded to a 7-slot rank template with the 3 real R ranks at indices
    1-3: -5/25/55/85/115/145/175) to be the SAME flat number the wiki
    text grants to four different stats at once — "ability power, bonus
    armor, bonus magic resistance, bonus movement speed". Only two of
    those four get a ``stat_buff`` key: ability power (Poison Trail's Q
    and Fling's E both read ``ctx.stats["ability_power"]`` mid-parse,
    Syndra-P precedent — ``DEFAULT_CAST_ORDER`` already casts R before
    Q/E) and move speed (``damage.py``'s ``_apply_stat_buff_ultimates``
    folds every ``stat_buff`` key into ``champion_stats``
    unconditionally, and ``move_speed`` is then read back out for
    ``item_state_receipts``' ``total_move_speed`` input — a real,
    if narrow, consumer). Modeled as BUFF phase (mutates ``ctx.stats``
    in-parse) so Q/E scale off the buffed AP whenever both are parsed in
    the same fight.

    Roadmap session (2026-08-21, closing task): bonus armor and bonus
    magic resistance were DROPPED from ``stat_buff`` after a concrete,
    traced-and-probed "does anything consume this" check, per the same
    no-consumer bar the HP/mana-regen and Grievous Wounds riders below
    were already held to.

    Trace: ``_apply_stat_buff_ultimates`` (``damage.py``) folds every
    ``stat_buff`` key into ``state.champion_stats`` unconditionally, but
    only a named allow-list of keys does anything further with the
    result — AD/pen/health/attack-speed recompute, or (for
    ``move_speed``) the ``item_state_receipts`` read above. Neither
    ``bonus_armor`` nor ``bonus_magic_resistance`` appears in that
    allow-list. The one place in ``damage.py`` that reads
    ``champion_stats["bonus_armor"]``/``["bonus_magic_resistance"]`` at
    all is K'Sante's own Path Maker (W) self-referential formula — a
    different champion's module, not a generic consumer. Separately, the
    survival subsystem (``participant_timeline.py`` /
    ``survival/receipt_state.py``) builds each combatant's defensive
    ``bonus_armor``/``bonus_magic_resistance`` state from the static,
    pre-fight ``Combatant.stats`` snapshot (``roster_composition.py``,
    set once from base+items+runes before any ability is parsed) — the
    per-fight buffed ``champion_stats`` dict is grepped in
    ``participant_timeline.py`` exactly twice, both feeding AP-scaling
    ally-support formulas (Aery's shield, ``derive_ally_effects``),
    never a defensive stat. The engine's dynamic-resistance channel used
    by the survival walk (``dynamic_bonus_armor`` /
    ``dynamic_bonus_magic_resistance`` in ``survival/transitions.py``)
    is owned entirely by Jak'Sho stacks, Force of Nature stacks, and the
    Aftershock rune; nothing in that path reads an ability's
    ``stat_buff`` dict either.

    Live probe (``/api/calculate``, Singed vs. Ashe, level 18, R rank 0
    vs. rank 3): with Singed as the ATTACKER, his own reported ``stats``
    row (the public snapshot) is identical at every R rank
    (``bonus_armor: 0``, ``bonus_magic_resistance: 0``, unaffected by R)
    while his own outgoing ``total_damage`` rises 290.2 -> 386.4 (the AP
    feed into Q/E, matching the sourced ratios) — proving AP is
    genuinely read while armor/MR are not, from the same buff. With
    Singed as the DEFENDER (an enemy roster slot) being autoattacked by
    Ashe, ``survival.damage_taken`` is bit-identical at R rank 0 and
    rank 3 (859.2 either way) and his reported ``stats.bonus_armor`` /
    ``stats.bonus_magic_resistance`` do not move — confirming the
    survival subsystem never sees the buff.

    Verdict: bonus armor and bonus magic resistance are sourced facts
    (the same "Bonus Stats" leveling row that feeds AP) but have no
    consumer anywhere in this engine today, exactly like the HP/mana
    regen grant and the Grievous Wounds rider below — so they are
    documented in ``ASSUMPTIONS`` as sourced-but-unmodeled riders
    instead of carrying an inert ``stat_buff`` key. If a future session
    wires bonus armor/MR into either the survival subsystem's dynamic
    resistance channel or a defender-side consumer, add them back with a
    named consumer, not preemptively.

    Two more sourced numbers on this same ability do NOT get a
    ``stat_buff`` key and stay documented-not-modeled: the "HP/Mana
    Regenerated per 0.5 Seconds" grant (2.5/5.5/8.5 by rank, 25s
    duration) has no health/mana-regen consumer anywhere in this
    fixed-window burst-combat engine (no other champion module carries a
    regen ``stat_buff`` key either — there is nothing for it to feed);
    and the "Poison Trail additionally applies Grievous Wounds" rider
    has no anti-heal/incoming-heal mechanic modeled anywhere in the
    codebase (``grep`` for "grievous" across ``src/calculator/champions/``
    returns zero champion modules), so there is no rider slot to attach
    it to. Both are sourced facts, not silent gaps — adding either key
    today would sit inert.
"""

from typing import Any

from .packet_module import build_packet_module
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_value, with_control

PACKET_SHA256 = "d6e04f1cd92d4f7ddd569c7ba4bb306cdd06c18e230c7ed2a57ef89ba45b3c9c"

# Insanity Potion (R): one sourced "Bonus Stats" number (25/55/85 by rank,
# data/champions.json Singed R effects[0], corroborated by the game
# binary's StatAmount DataValue) grants the SAME flat amount to all four
# stats named in the wiki text at once — "ability power, bonus armor,
# bonus magic resistance, bonus movement speed" — but only two of them
# have a traced consumer in this engine (see the module docstring's R
# entry for the consumer trace + live probe): ability power (feeds Q/E's
# AP ratios) and move speed (feeds item_state_receipts' total_move_speed
# input). Bonus armor and bonus magic resistance are sourced but
# unmodeled — see ASSUMPTIONS.
_INSANITY_POTION_STATS = (
    "ability_power",
    "move_speed",
)


def _insanity_potion(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: flat AP/move-speed steroid, 25s duration.

    See the module docstring's R entry for the sourcing, the consumer
    trace + live probe that dropped bonus armor/bonus magic resistance
    from ``stat_buff``, and the two other sourced-but-unmodeled riders
    (HP/mana regen, the Poison Trail Grievous Wounds application).
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    value = extract_value(ability, "Bonus Stats", rank)
    for stat_key in _INSANITY_POTION_STATS:
        ctx.stats[stat_key] = ctx.stats.get(stat_key, 0.0) + value

    entry = damage_entry(
        ability.get("name", "Insanity Potion"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "magic",
    )
    entry["stat_buff"] = {stat_key: value for stat_key in _INSANITY_POTION_STATS}
    entry["detail"] = (
        f"+{value:g} ability power and move speed for 25s (sourced "
        "'Bonus Stats' leveling, data/champions.json Singed R effects[0], "
        "corroborated by the game binary's StatAmount DataValue); the same "
        f"leveling row also sources +{value:g} bonus armor and bonus magic "
        "resistance, and the sourced HP/mana-regen grant and the Poison "
        "Trail Grievous Wounds rider are two more riders on this ability — "
        "none of those four have a consumer in this fixed-window combat "
        "engine (traced + live-probed) and stay unmodeled — see the module "
        "docstring and ASSUMPTIONS."
    )
    return entry


_insanity_potion.phase = BUFF

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Singed",
    PACKET_SHA256,
    single_hit_slots=frozenset({"E"}),
    slot_parsers={"R": _insanity_potion},
)
ASSUMPTIONS.append(
    "R (Insanity Potion)'s sourced 'Bonus Stats' leveling grants ability "
    "power, bonus armor, bonus magic resistance, and move speed all at "
    "once; only ability power (feeds Q/E's AP ratios) and move speed "
    "(feeds item_state_receipts' total_move_speed input) have a traced "
    "consumer in this engine, so only those two carry a stat_buff key. "
    "Bonus armor and bonus magic resistance are sourced but have no "
    "consumer anywhere: not in this champion's own outgoing damage "
    "math (the only reader of a buffed champion_stats bonus_armor/MR "
    "is K'Sante's own Path Maker formula), and not in the survival "
    "subsystem, whose defensive bonus_armor/bonus_magic_resistance "
    "state is built once from the pre-fight roster stats snapshot and "
    "never sees a mid-fight ability stat_buff (confirmed with a live "
    "/api/calculate probe: Singed's own reported armor/MR and an "
    "opponent's damage_taken against him are bit-identical at R rank 0 "
    "and rank 3)."
)
ASSUMPTIONS.append(
    "R (Insanity Potion) also sources an 'HP/Mana Regenerated per 0.5 "
    "Seconds' grant (2.5/5.5/8.5 by rank, 25s duration) and a rider "
    "that Poison Trail additionally applies Grievous Wounds; neither "
    "has a regen or anti-heal consumer anywhere in this fixed-window "
    "combat engine, so both stay sourced-but-unmodeled."
)

PACKET_SPEC = SLOTS.packet_spec
SLOTS["E"] = with_control(
    SLOTS["E"],
    kind="root",
    duration_attr="Root Duration",
)
parse_abilities = build_parser(SLOTS, "Singed")
MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "no_damage",
    "E": "modeled",
    "R": "modeled",
}
REVIEW_STATUS = "reviewed_module"
