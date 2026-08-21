"""Sivir — CP10.7 full-entry-reviewed packet module, plus the E9-3 Q fix.

E9-3: Boomerang Blade (Q) is a two-way blade: "Upon reaching maximum
range, the crossblade returns to her ... dealing the same damage to
enemies on its way back" — the cached "Total Maximum Champion Damage"
row (120-320 + 140% bonus AD + 120% AP) is exactly double the
single-pass "Physical Damage" row the reviewed packet priced.  The
module now prices the Total row so a full out-and-back pass deals the
in-game 2x damage (320 at rank 5 vs the old 160).

E (Spell Shield) is ``modeled`` as a timed ``self_state_events`` window:
the sourced 1.5s shield blocks one hostile effect and, after the sourced
0.25s delay, heals Sivir for the cached Heal row (60-80% AD + 50% AP by
rank), scoped to herself — "she heals herself and activates Fleet of
Foot" names no ally.

Roadmap session (2026-08-21): adjudicates Sivir's two remaining
out_of_scope slots.  They resolve DIFFERENTLY, and the difference is the
point.

  - P (Fleet of Foot) closes as ``no_damage``.  Its single cached effect
    is a self movement-speed buff — "basic attacks on-attack and ability
    hits against enemy champions grant her 55 : 75 (based on level) bonus
    movement speed decaying over 1.5 seconds" — with no enemy-damage row
    anywhere in the entry, and the game binary agrees: the
    ``SivirPassive`` record's ONLY calculation is ``FlatMS`` (plus a
    ``HasteDuration`` of 1.5), with no damage formula at all.  The label
    was a stale ``out_of_scope`` for a slot that is sourced-non-damaging
    (the Vayne-P / Kalista-P / Pyke-P precedent).

    The flat grant is deliberately NOT converted into a ``stat_buff``.
    Naafiri's W established the boundary for a PERCENT movement buff;
    the flat case fails for a sharper, arithmetic reason.
    ``_apply_stat_buff_ultimates`` adds the buff value straight onto
    ``champion_stats["move_speed"]`` and never re-runs
    ``stats.apply_movement_speed_soft_caps``, which has already been
    applied — so above 415 raw movement speed the in-game grant is worth
    0.8x what the channel would credit (and 0.5x above 490).  The one
    live consumer of that stat is ``item_effects``'
    ``adaptive_force_per_total_move_speed`` (Swiftmarch), i.e. an
    over-credited movement number would become DAMAGE.  The buff is also
    transient (1.5s, refreshing on hit), so its uptime is not derivable
    either.  It stays state.

  - R (On the Hunt) stays OPEN ``out_of_scope`` with a receipt.  It is a
    real, sourced, unmodeled mechanic, so the Olaf-R rule applies: it is
    NOT ``no_damage``.  The binary confirms there is no damage to miss
    (``SivirR``'s ``mSpellCalculations`` is empty), but both of its two
    sourced combat effects hit a named kernel gap:
      * the bonus movement speed (20/25/30% by rank) is an additive
        PERCENT, and ``calculate_total_stats`` exposes only the final
        soft-capped ``move_speed`` scalar — there is no
        ``move_speed_flat`` / ``move_speed_percent`` pair to compose
        against — so a percent-to-flat decomposition would have to be
        invented.  Same Swiftmarch damage path as P.
      * "Sivir's basic attacks on-attack reduce her basic abilities'
        current cooldowns by 0.5 seconds each" has no channel:
        ``on_attack_cooldown_refund`` is a field of
        ``item_effects.CooldownProcEffect`` (Scout's Slingshot) read only
        by the item-proc scheduler, so there is no ability-cooldown
        refund surface for a champion to author.
    One further binary row is a genuine SOURCE CONFLICT and is recorded
    rather than used: ``SivirR`` carries ``HuntAttackSpeed`` (rank 1-3 =
    5%/6%/7%) that the cached wiki text does not mention at all.
    Fail-closed: an uncorroborated attack-speed steroid is not modeled.
"""

from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    required_ability_atom,
    required_ranked_attribute_atom,
    ranked_ability_atom_value,
)
from ..ability_spec import DamagePart
from .engine import SlotCtx
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "ac50a4316c8ffc3f6f326c6be14ec20867f6301066621ff49ec26c1fad1b97a7"


def _boomerang_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the two-way pass priced from the Total Maximum Champion Damage row."""
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    total = extract_named(
        ability, "Total Maximum Champion Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Boomerang Blade"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total / 2.0, count=2),)
    entry["detail"] = (
        "two-way Boomerang Blade: the crossblade hits out AND back for 2x "
        "(Total Maximum Champion Damage 120-320 + 140% bonus AD + 120% AP "
        "== 2 x the single-pass row)"
    )
    return entry


# Sourced from the cached Spell Shield description.  The duration is read
# through the typed ability-atom accessor (``timing.active_duration``, the
# description's "for 1.5 seconds" prose atom); the 0.25s heal delay has NO
# atom in the catalog (prose-only — recorded SOURCE GAP in the slice
# handover), so it stays a module-authored sourced literal.
_SPELL_SHIELD_HEAL_DELAY_SECONDS = 0.25

_ATOM_RECEIPT_KEYS = (
    "atom_id",
    "behavior",
    "source",
    "values",
    "units",
    "evidence",
    "hash",
)


def _atom_receipt(atom: dict[str, Any]) -> dict[str, Any]:
    """One JSON-safe atom receipt (the interaction-atoms shape)."""
    return {key: atom[key] for key in _ATOM_RECEIPT_KEYS}


def _spell_shield(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: one timed spell shield with its sourced block heal.

    Numeric values ride the typed ability-atom accessors: the 1.5s window
    (``timing.active_duration``) and the Heal row (60-80% AD + 50% AP by
    rank).  The 0.25s heal delay is prose-sourced (no atom exists).
    """
    ability = ctx.ability("E")
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    duration_atom = required_ability_atom(
        "Sivir",
        champion_data,
        "E",
        query=AbilityAtomQuery(
            source="Sivir.E[0].effects[0].description",
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    if duration_atom.get("units") != ["s"]:
        raise ValueError("Sivir E spell-shield duration atom must use seconds")
    duration = ranked_ability_atom_value(
        duration_atom, 1, source="Sivir.E[0].effects[0].description"
    )
    ad_ratio, ad_atom = required_ranked_attribute_atom(
        "Sivir", champion_data, "E", "Heal", rank, modifier_index=0
    )
    ap_ratio, ap_atom = required_ranked_attribute_atom(
        "Sivir", champion_data, "E", "Heal", rank, modifier_index=1
    )
    heal = (
        ad_ratio * ctx.stat("attack_damage") / 100.0
        + ap_ratio * ctx.stat("ability_power") / 100.0
    )
    return {
        "name": ability.get("name", "Spell Shield"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "total_raw": 0.0,
        "damage_type": "magic",
        "parts": (),
        "self_state_events": [
            {
                "kind": "spell_shield",
                "duration": duration,
                "source": ability.get("name", "Spell Shield"),
                "on_block_heal_amount": heal,
                "on_block_heal_delay": _SPELL_SHIELD_HEAL_DELAY_SECONDS,
                "on_block_heal_source": "Spell Shield · Heal",
                "source_atoms": [
                    _atom_receipt(duration_atom),
                    _atom_receipt(ad_atom),
                    _atom_receipt(ap_atom),
                ],
            }
        ],
        "detail": (
            "Spell Shield blocks one hostile effect during the sourced "
            f"{duration:g}s window and heals Sivir for {heal:g} after the "
            "sourced 0.25s delay."
        ),
    }


parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sivir",
    PACKET_SHA256,
    slot_parsers={
        "Q": _boomerang_blade,
        "E": _spell_shield,
    },
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (Boomerang Blade) prices the full two-way pass from the cached "
    "'Total Maximum Champion Damage' row (120-320 + 140% bonus AD + "
    "120% AP == 2 x the single-pass 'Physical Damage' row): the blade "
    "deals the same damage on the way out and back.",
    "The exact return cadence is not cached; both passes are priced at "
    "the cast boundary.",
    "E (Spell Shield) grants a 1.5 second shield (atom-backed: "
    "timing.active_duration 4d718bc78f540f0a). The first hostile ability "
    "effect during that window is blocked. The cached Heal row is applied "
    "after the sourced 0.25 second delay (prose-only — no catalog atom "
    "exists; recorded SOURCE GAP). Fleet of Foot is state and stays "
    "outside the damage ledger.",
    "P (Fleet of Foot) has no enemy-damage clause anywhere in its cached "
    "entry: the single effect grants Sivir 55:75 (based on level) bonus "
    "movement speed decaying over 1.5 seconds on her own attacks and "
    "ability hits, and the game binary's SivirPassive record carries only "
    "FlatMS and HasteDuration 1.5 with no damage formula at all. The slot "
    "emits a sourced zero-damage row (MODULE_COVERAGE: no_damage, not "
    "out_of_scope; the Vayne-P / Kalista-P / Pyke-P precedent). The flat "
    "movement grant is NOT modeled as a stat_buff: that channel adds the "
    "value straight onto champion_stats['move_speed'] without re-running "
    "stats.apply_movement_speed_soft_caps, so above 415 raw movement "
    "speed it would over-credit the in-game grant, and the one live "
    "consumer of that stat is item_effects' "
    "adaptive_force_per_total_move_speed (Swiftmarch) - an over-credited "
    "movement number would become damage. Its 1.5 second refreshing "
    "window also has no derivable uptime, so it stays state.",
    "R (On the Hunt) stays out_of_scope, NOT no_damage (the Olaf-R rule: "
    "a real, sourced, unmodeled mechanic is out_of_scope). There is no "
    "damage to miss - the binary's SivirR carries an empty "
    "mSpellCalculations - but both of its sourced combat effects hit a "
    "named kernel gap. (1) The bonus movement speed (20/25/30% by rank) "
    "is an additive PERCENT and calculate_total_stats exposes only the "
    "final soft-capped move_speed scalar, with no move_speed_flat / "
    "move_speed_percent pair to compose against, so a percent-to-flat "
    "decomposition would have to be invented (the same Swiftmarch damage "
    "path as P). (2) 'Sivir's basic attacks on-attack reduce her basic "
    "abilities' current cooldowns by 0.5 seconds each' has no channel: "
    "on_attack_cooldown_refund is a field of "
    "item_effects.CooldownProcEffect read only by the item-proc "
    "scheduler, so no ability-cooldown-refund surface exists for a "
    "champion to author. SOURCE CONFLICT recorded, not used: SivirR also "
    "carries HuntAttackSpeed (rank 1-3 = 5%/6%/7%) that the cached wiki "
    "text does not mention at all; fail-closed, an uncorroborated "
    "attack-speed steroid is not modeled.",
]
MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "out_of_scope",
}
