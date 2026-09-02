"""Seraphine — CP10.7 full-entry-reviewed packet module.

E8d ally-support: W (Surround Sound) shields the caster and every selected
teammate (Shield Strength 60-140 + 20% AP; scope self_and_all_teammates).
The event is authored by the engine's ally-support scanner from cached
leveling at the W cast time; the module declares W in SLOTS so the fight
rotation casts it.  W's conditional pulse heal ("% of target's missing
health") uses a live missing-health formula and the caster's shield state.

P1 addition over the reviewed packet:
- Q (High Note) prices the missing-health amplifier: "Against champions
  and monsters, the damage is increased by 0% : 75% (based on target's
  missing health)" (cached Q description, second effect).  The base row
  "Magic Damage" (60-160 + 40% AP) is the flat part; a second
  hp-scaled part adds 0.75 x base x missing-health-ratio, so at full
  missing health the total equals the cached "Maximum Enhanced Damage"
  row (105-280 + 70% AP = 1.75 x base).  The engine evaluates the
  hp-scaled part at the cast with the target's live missing health —
  deterministic given the fight's health walk (Akshan R precedent).

Roadmap session (2026-08-21): closes both remaining out_of_scope slots
(P, W).

  - P (Stage Presence) is NOT a no-damage slot.  Its third effect row
    carries a real sourced on-hit damage formula: "While any amount of
    Notes are active, Seraphine's next basic attack is empowered ... and
    fire all Notes at the target, with each one dealing 4 : 27.47 (based
    on level) (+ 4% AP) magic damage" (``data/champions.json`` Seraphine
    P, effect 2, leveling attribute "Bonus Magic Damage" — a 20-entry
    per-LEVEL array plus one 4% AP modifier).  The game binary agrees
    exactly (``data/bin/characters/seraphine.bin.json``, record
    ``SeraphinePassive``: ``AutoDamage`` ByCharLevel 4 -> 25 with the
    level-20 extrapolation to 27.47, and ``NoteAPRatio`` 0.04).  The
    packet's ``no_damage`` label was therefore INCOMPLETE, not stale.

    Notes are a stack window the fight engine does not simulate (they
    are granted by ability casts, last 6 seconds and cap at 4 per unit),
    so the number of Notes fired is explicit state: the ``p_notes_fired``
    option (0 by default), the Rumble ``overheat_autos`` / Rammus
    ``w_thorns_autos`` template for a proc whose trigger count the engine
    cannot derive.  Its ceiling of 4 is the sourced ``MaxNotes`` cap, and
    the option prices ONE empowered basic attack — a fight with a second
    empowered attack would fire more Notes, so the reading is
    conservative in the fail-closed direction.

    Two sourced riders in the same effect are deliberately NOT modeled:
      * Ally Notes ("reduced by 75% for Notes from allies", binary
        ``AllyNoteDamagePercent`` 0.25).  They require allied champions
        standing in range at Seraphine's cast times — structurally
        outside the 1v1 damage surface (the Rakan-E / Kai'Sa-R
        ally-coupling boundary).  Only Seraphine's own Notes are priced.
      * The empowered attack's "uncancellable windup" and "25 bonus
        attack range per Note".  Neither is damage and this engine has
        no attack-range or windup channel.

  - W (Surround Sound) is a sourced self-and-ally shield with no damage
    row of any kind: Shield Strength 60/80/100/120/140 (+ 20% AP) for
    2.5 seconds, plus the conditional missing-health pulse heal already
    described above.  Being shield-only it cannot carry
    ``attach_self_shield`` (that payload rides damage-event rows), so it
    stays priced by the ally-support scanner, which already derives BOTH
    rows — the shield at target scope ``self_and_all_teammates`` with
    ``target_self`` true, and the gated heal with its typed live
    missing-health atom (pinned by tests/test_support_effects.py).
    Reclassified out_of_scope -> modeled, the Ekko-W / Rumble-W
    precedent for a scanner-priced shield-only slot.

    W's SELF movement grant (20% + 2% per 100 AP, decaying) is published
    as a ``move_speed_percent`` stat buff, which ``damage.py`` re-folds
    through ``stats.resolve_move_speed`` (soft caps included).  Its
    magnitude is prose in the cached description rather than a leveling
    row, so it is a pinned module constant; the ally half (8% + 0.8% per
    100 AP) has no 1v1 channel.  The 2-stack shield rule is state and
    the base row is priced.
"""

from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
)
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import ONHIT, SlotCtx
from .inputs import bool_option, int_option
from .module_helpers import buff_window_share
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    with_control,
)

PACKET_SHA256 = "4814ec27868dfc6c584834af7a9e7e17d4febc980aa3532143466c34cf7b995b"


# The sourced cap on Notes held by one unit: "stacks up to 4 times on
# each unit" (cached P effect 1), corroborated by the game binary's
# SeraphinePassive ``MaxNotes`` = 4.  Unlike the Rumble/Rammus rails this
# IS a modeled game value, so it doubles as the option's ceiling.
_MAX_NOTES = 4

# The Q missing-health amplifier and W's self movement grant are binary
# DataValues (SeraphineQ.DamageAmp; SeraphineW.WMSBonus / WMSBonusAPRatio);
# the cached sentences corroborate them.  The ally MS half (8% + 0.8% per
# 100 AP) has no self channel.
_SERAPHINE_Q_SPELL = spell_object("Seraphine", "SeraphineQ")
_SERAPHINE_W_SPELL = spell_object("Seraphine", "SeraphineW")
_Q_MISSING_HEALTH_MAX_BONUS = data_value(_SERAPHINE_Q_SPELL, "DamageAmp") / 100.0
_W_MOVE_SPEED_PERCENT = data_value(_SERAPHINE_W_SPELL, "WMSBonus") * 100.0
_W_MOVE_SPEED_PER_100_AP = data_value(_SERAPHINE_W_SPELL, "WMSBonusAPRatio") * 10000.0

# Notes "stack up to 4 times on each unit" and every ability cast grants
# one, so a full Q/W/E/R rotation puts the cap on Seraphine — the default.
_NOTE_CAP = 4

# The grant's window, read as an atom rather than pinned: the shield and
# the movement share one sentence and one duration.
_W_WINDOW_SOURCE = "Seraphine.W[0].effects[0].description"


def _stage_presence(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the empowered attack fires every active Note at the target."""
    ability = ctx.ability()
    if ability is None:
        return None
    per_note = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target, level=ctx.level
    )
    if per_note <= 0:
        return None
    notes = min(max(0, int(ctx.option("p_notes"))), _NOTE_CAP)
    entry = on_hit_entry(ability_name(ability), per_note * notes, "magic")
    # One empowered attack fires every Note it holds; the next attack has
    # none until her abilities grant more.
    entry["on_hit"]["max_procs"] = 1 if notes else 0
    entry["detail"] = (
        f"{notes} Note(s) of {per_note:.2f} bonus magic damage each "
        "(4 : 27.47 based on level + 4% AP) on one empowered attack; Notes "
        "from allies (reduced by 75%) and Echo's free recast are unpriced"
    )
    return entry


_stage_presence.phase = ONHIT


def _w_window_seconds(ctx: SlotCtx) -> float:
    """W's sourced grant window, read as a typed atom.

    The cached sentence shields "for 2.5 seconds. For the same duration,
    she also gains ... bonus movement speed" — one window, so the
    movement rides the shield's own ``timing.active_duration`` atom
    rather than a second number.
    """
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    atom = required_ability_atom(
        ctx.champion_name,
        champion_data,
        "W",
        query=AbilityAtomQuery(
            source=_W_WINDOW_SOURCE,
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    if [str(unit).strip().lower() for unit in atom["units"]] != ["s"]:
        raise ValueError("Seraphine W active-duration atom must use seconds")
    return ranked_ability_atom_value(atom, 1, source=_W_WINDOW_SOURCE)


def _surround_sound(packet_w):
    """W: the shield is the scanner's; the cast's own movement is ours.

    Replaces the packet's generic "no enemy-damage formula" stub with
    the sourced grant, published as a ``move_speed_percent`` stat buff
    (the Teemo-W wiring).  Only Seraphine's own half is published: the
    ally half needs allied champions the 1v1 surface has no room for.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_w(ctx)
        if entry is None:
            return None
        granted = _W_MOVE_SPEED_PERCENT + _W_MOVE_SPEED_PER_100_AP * (
            ctx.stat("ability_power") / 100.0
        )
        # The cast expires, and a stat_buff is one scalar for the whole
        # fight, so the grant lands time-weighted by the share of the
        # window it covers (module_helpers.buff_window_share).
        window = _w_window_seconds(ctx)
        published = granted * buff_window_share(ctx, window)
        entry["stat_buff"] = {"move_speed_percent": published}
        entry["detail"] = (
            f"Shield only, priced by the ally-support scanner. The cast's "
            f"own {_W_MOVE_SPEED_PERCENT:g}% "
            f"(+ {_W_MOVE_SPEED_PER_100_AP:g}% per 100 AP) grant "
            f"({granted:g}% at this build, {published:g}% over the fight "
            f"window at the sourced {window:g}s) is published as a "
            "move_speed_percent stat buff, a term in the shared "
            "movement-speed fold; its decay, its 2-stack rule and the "
            "ally half of the grant are state."
        )
        return entry

    return parse


def _high_note(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: flat base + 0%:75% missing-health amplifier (hp-scaled part)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    base = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    maximum = extract_named(
        ability, "Maximum Enhanced Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        base,
        "magic",
    )
    entry["parts"] = (
        # Both the flat base and the missing-health amplifier land at the
        # cast boundary: authored time_offset 0.0 upgrades their events from
        # cast_boundary to hit precision so the coverage classifier certifies
        # the row instead of downgrading it coarse (Viego R pattern).
        DamagePart("magic", base, time_offset=0.0),
        DamagePart(
            "magic",
            hp_scaled_damage=lambda missing, base=base: base
            * _Q_MISSING_HEALTH_MAX_BONUS
            * max(0.0, min(1.0, missing)),
            time_offset=0.0,
        ),
    )
    entry["detail"] = (
        f"flat {base:g} + up to {_Q_MISSING_HEALTH_MAX_BONUS * 100:g}% of "
        f"base ({maximum:g} at full missing health, the cached Maximum "
        "Enhanced Damage row) scaled by the target's live missing-health "
        "ratio"
    )
    entry["event_order_certified"] = "single_hit"
    return entry


# Reviewed crowd control, read from the cached kit: Q (High Note) "deals
# magic damage to enemies within the area" and applies nothing else; E
# (Beat Drop) "slows them by 99%" (its root and stun are conditional on
# the target already being slowed / immobilized, which the duel model
# does not establish); R (Encore) "deals magic damage to enemies hit,
# charms them ... and slows them by 40%" — the charm is the control the
# damaged target takes.  W and P emit no damage event, so they carry no
# reviewable control.
MODULE_CC = {"Q": "none", "E": "slow", "R": "charm"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Seraphine",
    PACKET_SHA256,
    single_hit_slots=frozenset({"E", "R"}),
    slot_parsers={
        "Q": _high_note,
        "P": _stage_presence,
    },
    # The kinds above are the reviewed answer; these wrappers read each
    # one's sourced duration off the packet ("Disable Duration" is the
    # window E's 99% slow and R's charm both last).
    slot_wrappers={
        "E": lambda parser: with_control(parser, duration_attr="Disable Duration"),
        "R": lambda parser: with_control(parser, duration_attr="Disable Duration"),
        "W": _surround_sound,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "p_notes",
        _NOTE_CAP,
        minimum=0,
        maximum=_NOTE_CAP,
        label="Notes on the empowered attack",
    ),
    bool_option(
        "w_already_shielded",
        False,
        label="W caster already has a shield for the first pulse",
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "W (Surround Sound) pulses its sourced missing-health heal after 2.5 "
    "seconds when Seraphine has a shield at cast time; the first cast can "
    "use the explicit w_already_shielded option",
    "Q (High Note) prices the missing-health amplifier: base (60-160 + "
    "40% AP) plus 0.75 x base x the target's live missing-health ratio "
    "(0%:75% based on missing health; equals the cached Maximum Enhanced "
    "Damage row at full missing health)",
    "P (Stage Presence) prices the empowered basic attack's Note damage - "
    "4:27.47 by level + 4% AP per Note fired (cached P effect 3, leveling "
    "attribute 'Bonus Magic Damage', a per-level array; corroborated by "
    "the game binary's SeraphinePassive AutoDamage ByCharLevel 4->25 and "
    "NoteAPRatio 0.04). The fight engine does not simulate the Note stack "
    "window, so p_notes is the explicit count of Notes the empowered "
    "attack fires, capped at the sourced MaxNotes of 4 and defaulting to "
    "that cap because every ability cast grants a Note and a full Q/W/E/R "
    "rotation reaches it. The row rides the basic-attack stream as an "
    "on-hit with max_procs 1: one empowered attack fires every Note it "
    "holds and the next has none. Notes from allies (25% damage, binary "
    "AllyNoteDamagePercent 0.25) are NOT priced: they require allied "
    "champions in range at cast time and are structurally outside the 1v1 "
    "damage surface, as is Echo's free recast. The empowered attack's 25 "
    "bonus attack range per Note and its uncancellable windup are not "
    "damage and remain state. Reclassified from out_of_scope to modeled; "
    "the packet's no_damage label was incomplete, not stale.",
    "W (Surround Sound) is a sourced shield with no damage row: 60/80/100/"
    "120/140 + 20% AP for 2.5 seconds on Seraphine and nearby allies. "
    "Shield-only abilities cannot carry attach_self_shield (that payload "
    "rides damage-event rows), so W stays priced by the ally-support "
    "scanner, which derives the shield at target scope "
    "self_and_all_teammates with target_self true. The conditional "
    "missing-health pulse heal is REFUSED rather than published at zero: "
    "its amount depends on each recipient's live missing health, which the "
    "scanner cannot price per recipient, and w_already_shielded only drops "
    "the caster's shield gate - it must not resurrect a zero-amount pulse "
    "row (pinned by tests/test_e8_support.py). W's SELF movement grant "
    "(20% + 2% per 100 AP) is published as a move_speed_percent "
    "stat_buff, a term in the shared resolve_move_speed fold (soft caps "
    "included). Its magnitude is prose in the cached W description and "
    "not a leveling row, so it is a HARDCODED module constant pinned by "
    "the cached sentence, the way the Q missing-health amplifier and "
    "Naafiri's 20% AD are. The ALLY half (8% + 0.8% per 100 AP) is not "
    "published: it needs allied champions in range, which is outside the "
    "1v1 surface. The 2.5s decay, the 2-stack shield rule and the ally "
    "shield scope are state and the base Shield Strength row is "
    "priced. Reclassified from out_of_scope to modeled (the Ekko-W / "
    "Rumble-W precedent for a scanner-priced shield-only slot).",
]

# No MODULE_COVERAGE: every slot is emitted and priced, which is exactly
# what ``module_contract.default_coverage`` derives from SLOTS.  Restating
# it is refused as a second home for the same fact.
