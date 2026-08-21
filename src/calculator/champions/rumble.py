"""Rumble — CP10.6 packet module with the E9-1 R gap fix.

E9-1 closes the remaining audit gap: R (The Equalizer) priced ONE tick
of the Burning DoT.  The wiki cache carries "Magic Damage per Tick"
(30/50/70 + 8.75% AP) and "Maximum Magic Damage" (600/1000/1400 +
175% AP): 20 ticks at 0.25 seconds over up to 5 seconds of Burning
("Enemies may be Burning for up to 5 seconds, for a total of 20
instances of its effect"). This module's packet timing declaration
prices all 20 ticks.

Q/E damage packets are correct.

Roadmap session (2026-08-21): closes both of Rumble's remaining
out_of_scope slots (P, W).

  - P (Junkyard Titan) is NOT a no-damage slot. Its third effect row,
    Overheated, carries a real sourced on-hit damage formula: "empowers
    his basic attacks to deal 5 : 44.12 (based on level) (+ 25% AP)
    (+ 4% of the target's maximum health) bonus magic damage on-hit"
    (``data/champions.json`` Rumble P, effect 3, leveling attribute
    "Bonus Magic Damage" — a 20-entry per-LEVEL array, one 25% AP
    modifier, one 4% target-max-health modifier). The game binary
    agrees exactly (``data/bin/characters/rumble.bin.json``, record
    ``RumbleHeatSystem``: ``TotalBaseDamage`` ByCharLevel 5 -> 40 with
    the level-20 extrapolation to 44.12, ``+ 0.25`` AP coefficient, and
    ``OverheatPercBonusDamage`` 0.04). The packet's ``no_damage`` label
    was therefore INCOMPLETE, not merely stale.

    Overheat is a heat-state window the fight engine does not simulate,
    so the number of empowered autos is explicit state: the
    ``overheat_autos`` option (0 by default), exactly the Rammus
    ``w_thorns_autos`` template for a proc whose trigger count the
    engine cannot derive.

    Two sourced rows in the same effect are deliberately NOT modeled:
      * The 50% : 142.54% bonus attack speed. It is inseparable from
        the very cost the same sentence states — "disabling his
        abilities as his Heat decays back down to 0 over 4 seconds".
        This engine has no ability-lockout channel, so importing the
        upside without the downside would systematically overstate
        Rumble. Both halves stay state (see ASSUMPTIONS).
      * The "Bonus Damage" leveling row (65 : 163.32 by level). Read in
        context it is not a damage source at all — it is the cap on the
        %max-health term, "capped at 65 : 163.32 (based on level)
        against monsters". It is monster-only and this engine's
        ``target_class`` has no monster value, so it never binds on the
        champion-target surface and is documented, never added.

  - W (Scrap Shield) is a sourced self-shield with no damage row of any
    kind: "Rumble generates 20 Heat to grant himself a shield for 1.5
    seconds", Shield Strength 25/55/85/115/145 (+ 30% AP) (+ 4% of
    maximum health). Being shield-only it cannot carry
    ``attach_self_shield`` (that payload rides damage-event rows), so it
    stays priced by the ally-support scanner, which already derives it
    at target scope "self" (pinned by tests/test_support_effects.py).
    Reclassified out_of_scope -> modeled, the Ekko-W precedent for a
    scanner-priced shield-only slot.

    NOTE: closing this slot required a genuine kernel repair. The 4%
    max-health term uses the wiki spelling "% of maximum health", which
    was absent from ``champions/scaling.py``'s ``_SIMPLE_UNITS`` table
    (only the "% maximum health" spelling was mapped), so
    ``resolve_scaling`` fell through to its unrecognized-unit ``0.0``
    and SILENTLY dropped the term — the exact fail-open this codebase
    bans. The alias is now mapped; see that module's comment for the
    full blast radius (it also zeroed Galio's W shield outright).

    Danger Zone Bonus (+50% shield strength and bonus movement speed)
    is heat state and is not applied: the scanner prices the base
    "Shield Strength" row, the conservative no-heat reading this module
    has always taken for Q/E/R.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "c18c1e6e7005c17066acf180ec68a2013bb656c20a88655a536f0a2bc9a078f5"

# Upper bound on the explicit Overheated auto count. Overheat lasts a
# sourced 4 seconds; the bound is a sanity rail on user input, not a
# modeled game value (the Rammus w_thorns_autos rail).
_MAX_OVERHEAT_AUTOS = 30

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Rumble",
    PACKET_SHA256,
    packet_tick_fixes={
        "The Equalizer": {
            "count": 20,
            "first_tick": 0.25,
            "tick_interval": 0.25,
            "dot_duration": 5.0,
        }
    },
)
PACKET_SPEC = SLOTS.packet_spec


def _junkyard_titan(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the Overheated on-hit bonus magic damage, per empowered auto.

    The "Bonus Magic Damage" leveling row is a per-LEVEL array (20
    entries), so it is read at ``ctx.level``, not at an ability rank —
    Junkyard Titan is an innate with no rank of its own (the
    ``module_helpers.named_damage`` P convention, which substitutes
    ``ctx.level`` for the rank on passive slots).

    ``extract_named`` resolves all three modifiers together: the flat
    per-level term, "% AP", and "% of the target's maximum health".
    """
    ability = ctx.ability("P")
    if ability is None:
        return None
    autos = min(max(int(ctx.options.get("overheat_autos", 0)), 0), _MAX_OVERHEAT_AUTOS)
    per_auto = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    total = per_auto * autos
    entry = damage_entry(
        "Junkyard Titan (Overheated)",
        ctx.level,
        extract_cooldown(ability, ctx.level),
        total,
        "magic",
    )
    # Only override the parts when a swing actually lands: the fight
    # engine reads ONLY ``parts``, so a floored count would price a full
    # proc at the default of zero empowered autos (the bug this session
    # fixed in Rammus' thorns).
    if autos > 0:
        entry["parts"] = (DamagePart("magic", per_auto, count=autos),)
    entry["detail"] = (
        f"Overheated: {per_auto:.2f} bonus magic damage on-hit "
        f"(level-{ctx.level} flat + 25% AP + 4% target maximum health) "
        f"x {autos} empowered auto(s); the 4-second Overheat window's "
        "attack-speed bonus and its ability lockout are both unmodeled "
        "state, and the 'Bonus Damage' row is the monster-only cap on "
        "the %max-health term, not a damage source"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["P"] = _junkyard_titan
parse_abilities = build_parser(SLOTS, "Rumble")

OPTIONS = list(OPTIONS) + [
    {
        "key": "overheat_autos",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": _MAX_OVERHEAT_AUTOS,
        "label": "Basic attacks landed while Overheated",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (The Equalizer) prices all 20 Burning ticks (Magic Damage per "
    "Tick x20 == Maximum Magic Damage 600/1000/1400 + 175% AP) at "
    "0.25-second intervals over up to 5 seconds (packet_module "
    "local packet timing declaration). The initial rocket impact has no separate "
    "damage row in the cache.",
    "The heat/Danger Zone system is state outside the damage model: "
    "Q/E/R rotation numbers assume no heat state (the CP-era review "
    "boundary), and W's Danger Zone Bonus (+50% shield strength) is not "
    "applied - the base Shield Strength row is priced.",
    "P (Junkyard Titan) prices the Overheated on-hit bonus magic damage - "
    "5:44.12 by level + 25% AP + 4% of the target's maximum health per "
    "empowered basic attack (cached P effect 3, leveling attribute 'Bonus "
    "Magic Damage', a per-level array; corroborated by the game binary's "
    "RumbleHeatSystem TotalBaseDamage / 0.25 AP coefficient / "
    "OverheatPercBonusDamage 0.04). The fight engine does not simulate "
    "heat, so overheat_autos is the explicit count of empowered autos "
    "(0 = none, the default). The same effect's 50%:142.54% bonus attack "
    "speed is NOT modeled: it is inseparable from the ability lockout "
    "stated in the same sentence ('disabling his abilities as his Heat "
    "decays back down to 0 over 4 seconds') and this engine has no "
    "ability-lockout channel, so pricing the upside alone would overstate "
    "Rumble. The 'Bonus Damage' leveling row (65:163.32 by level) is the "
    "monster-only cap on the %max-health term, not a damage source, and "
    "never binds against a champion target. Reclassified from "
    "out_of_scope to modeled; the packet's no_damage label was incomplete, "
    "not stale.",
    "W (Scrap Shield) is a sourced self-shield with no damage row: 25/55/"
    "85/115/145 + 30% AP + 4% of maximum health for 1.5 seconds. Shield-"
    "only abilities cannot carry attach_self_shield (that payload rides "
    "damage-event rows), so W stays priced by the ally-support scanner, "
    "which derives it at target scope 'self'. Its 4% max-health term was "
    "silently dropped until this session: the wiki spelling '% of maximum "
    "health' was missing from the scaling unit table and resolved to 0.0; "
    "the alias is now mapped. The bonus movement speed row is not damage "
    "and remains state. Reclassified from out_of_scope to modeled (the "
    "Ekko-W precedent for a scanner-priced shield-only slot).",
]
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "modeled",
}
REVIEW_STATUS = "reviewed_module"
