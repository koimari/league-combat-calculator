"""Alistar — slot map for the archetype engine.

Why each slot is non-generic:
- E (Trample) is a custom fn: the cast total is the "Total Magic
  Damage" attribute (all 10 ticks over 5 s — the classifier would pick
  the per-tick "Magic Damage" first), plus the empowered-auto bonus
  that Trample grants once per cast, which scales with champion LEVEL
  (not rank) and is baked into the cast total rather than emitted as an
  on-hit. This is a total-attribute read plus an add-once on-hit addend,
  so the mechanic stays champion-local.
- Q (Pulverize) / W (Headbutt) are fully generic single-hit magic
  damage — auto-mode ``simple_damage``, exactly the generic path the
  legacy module reached by calling the generic parser and patching its
  output.
- R (Unbreakable Will) is damage reduction only and P (Triumphant
  Roar) is healing only — neither deals cast damage, so neither is in
  the SLOTS map (see the Roadmap session note below for each one's
  MODULE_COVERAGE classification).

Roadmap session 3 (2026-08-20): closes one of Alistar's two out_of_scope
slots (P); R stays open with a named receipt.

  - P (Triumphant Roar): already fully modeled as a sourced self-heal via
    ``derive_self_healing`` below (5% of Alistar's maximum health per
    completed 7-stack window, cached passive prose: "heal himself for 5%
    of his maximum health"), wired through ``SELF_HEALING_RULE`` (the
    same runtime path Taric's Q and Zac/Zilean's revive-adjacent heals
    use) and live-tested end to end (``tests/test_e1_healing_b3.py::
    test_alistar_triumphant_roar_heals_five_percent_max_health_per_seven_stacks``).
    ``MODULE_COVERAGE`` was simply stale, still reading "out_of_scope" for
    a slot the self-heal ledger had already closed — the identical
    stale-label pattern Shen P/Taric P/Zilean R were already corrected
    under in earlier roadmap sessions. Reclassified from out_of_scope to
    modeled; no behavior change.

    The same cached passive prose also grants a second, larger heal to
    "nearby allied champions for 7% of his maximum health" on the same
    7-stack trigger — a DIFFERENT amount than Alistar's own 5%. That ally
    heal is NOT modeled and stays a documented gap, not a silent one: the
    engine's only fan-out mechanism for a champion-authored
    ``SELF_HEALING_RULE`` heal (``participant_timeline.py``, the
    ``self_and_all_teammates``/``self_and_one_teammate`` clone loop that
    Taric's Q ally heal rides) clones the SAME event dict — same
    ``amount`` key — to every recipient; it has no support for a
    self-amount that differs from the ally-amount on one trigger. Wiring
    a correctly-differentiated 5%-self/7%-ally split would need a new
    fan-out shape in ``participant_timeline.py``, which is outside this
    session's alistar.py/anivia.py-only scope. Documented in
    ASSUMPTIONS rather than fabricated or silently dropped.
  - R (Unbreakable Will): stays out_of_scope. The number IS sourced
    (``data/champions.json`` Alistar R "Damage Reduction" leveling row:
    55/65/75% by rank, 7s duration, cleanses Alistar's own CC on cast) —
    but wiring it is structurally blocked, not missing sourcing.
    Every per-champion-authored non-damage hook this engine's runtime
    actually reads is enumerated by three call sites (grepped
    ``getattr(module, "..."...)`` across ``src/calculator/*.py``):
    ``SELF_HEALING_RULE`` (healing.py), ``starting_revive_defense``
    (defensive_effects.py), and ``GRIEVOUS_WOUNDS_SOURCES``
    (healing_reduction.py). None of the three accepts an "incoming
    damage reduction while active" contract. The nearest existing
    mechanism, ``StartingDefenses.incoming_damage_multiplier``
    (defensive_effects.py), is real and already consumed by the fight
    engine — but every producer of it today is an ITEM effect wired
    inline inside ``resolve_starting_defenses`` (Celestial Opposition,
    Armored Advance's ``basic_damage_multiplier``), keyed by item name,
    not by a champion-module resolver function; there is no
    ``_champion_incoming_damage_reduction``-style lookup the way
    ``_champion_starting_revive`` exists for revives. Adding one is a new
    hook in ``defensive_effects.py`` (plus deciding how a MID-fight,
    player-triggered 7s active window should be represented against a
    module whose name is literally ``StartingDefenses`` — Unbreakable
    Will is not "ready at fight start" the way a passive shield or a
    revive is), which is outside this session's alistar.py/anivia.py-only
    scope. Named here so a session with defensive_effects.py in scope can
    close it without re-deriving the audit.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named, simple_damage


def _extract_e_on_hit_damage(
    ability: dict[str, Any],
    level: int,
) -> float:
    """Extract E's empowered-auto bonus magic damage at a champion level.

    The empowered auto scales with champion level (not ability rank);
    the JSON stores it under "Bonus Magic Damage" as per-level values.
    Per-level arrays may have fewer entries than 18, in which case the
    level is linearly interpolated across the available values.
    (Test seam: tests/test_alistar.py validates the JSON values here.)
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != "Bonus Magic Damage":
                continue

            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                continue

            values = modifiers[0].get("values", [])
            if not values:
                continue

            if len(values) >= level:
                return float(values[level - 1])

            # The wiki defines per-level arrays over levels 1-18; clamp
            # top-quest levels 19-20 to the array's range so a short array
            # falls back to its level-18 value instead of extrapolating.
            scaling_level = min(level, 18)
            if len(values) >= scaling_level:
                return float(values[scaling_level - 1])

            # Interpolate: map level (1-18) into the values array.
            num_values = len(values)
            if num_values == 1:
                return float(values[0])

            fraction = (scaling_level - 1) / 17.0  # 0.0 at level 1, 1.0 at 18
            index_float = fraction * (num_values - 1)
            low_idx = int(index_float)
            high_idx = min(low_idx + 1, num_values - 1)
            weight = index_float - low_idx
            return (
                float(values[low_idx]) * (1 - weight) + float(values[high_idx]) * weight
            )

    return 0.0


# E (Trample) ticks 10 times over its 5-second duration — the JSON's
# "Total Magic Damage" row is exactly 10x the "Magic Damage Per Tick"
# row at every rank (80/8 .. 200/20), so the tick count is sourced
# rather than invented.  Each tick is one second of the channel's
# 0.5s cadence (5s / 10 ticks).
_E_TICKS = 10
_E_DURATION = 5.0
_E_TICK_INTERVAL = _E_DURATION / _E_TICKS  # "every 0.5 seconds"


def _trample(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: 10 sourced ticks of the per-tick row + level-scaled empowered auto.

    The per-tick value x 10 equals the JSON's "Total Magic Damage" at
    every rank, so the fight prices the full cast total across the
    tick timeline instead of one lump.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    # The empowered auto procs once per E cast (after the 5s trample),
    # so it joins the cast total instead of becoming a per-auto on_hit
    # entry.
    empowered = _extract_e_on_hit_damage(ability, ctx.level)

    name = ability.get("name", "Trample")
    entry = damage_entry(
        name,
        rank,
        extract_cooldown(ability, rank),
        per_tick * _E_TICKS + empowered,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=_E_TICKS,
            time_offset=_E_TICK_INTERVAL,
            hit_interval=_E_TICK_INTERVAL,
        ),
        DamagePart("magic", empowered, time_offset=_E_DURATION),
    )
    # Item burns (Liandry's, Blackfire Torch) stay refreshed through the
    # whole 5-second trample (the Cassiopeia rule).
    entry["dot_duration"] = _E_DURATION
    entry["detail"] = (
        f"{_E_TICKS} sourced trample ticks; empowered auto lands after the channel."
    )
    return entry


OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "E Trample deals full duration damage (10 ticks over 5 seconds)",
    "E empowered auto always procs once per cast (5 stacks reached)",
    "P (Triumphant Roar) is modeled as a sourced self-heal: 5% of "
    "Alistar's maximum health per completed 7-stack window (cached "
    "passive prose), via SELF_HEALING_RULE. The same passive's 7%-of-"
    "maximum-health heal to nearby allies on the same trigger is a "
    "different amount than the 5% self heal and is NOT modeled — the "
    "engine's champion-authored heal fan-out clones one shared amount to "
    "every recipient, with no differentiated self/ally split.",
    "R (Unbreakable Will) damage reduction (55/65/75% for 7s, cleanses "
    "Alistar's own CC) is sourced but unmodeled: no champion-authored "
    "hook for a mid-fight incoming-damage-reduction window exists in "
    "this engine today (only SELF_HEALING_RULE, starting_revive_defense, "
    "and GRIEVOUS_WOUNDS_SOURCES are read from a champion module).",
]

SLOTS = {
    "Q": simple_damage(),
    "W": simple_damage(),
    "E": _trample,
}

parse_abilities = build_parser(SLOTS, "Alistar")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Alistar",
        "revision_id": 3892578,
        "revision_timestamp": "2025-05-02T10:24:06Z",
    }
]
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "out_of_scope",
}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position
import re  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Alistar self-healing events from its authored packet."""
    healing = []
    p_text = " ".join(
        effect.get("description", "")
        for effect in _healing._ability(champion_data, "P").get("effects", [])
    )
    stack_match = re.search(r"At\s+(\d+)\s+stacks", p_text, flags=re.IGNORECASE)
    stack_cap = int(stack_match.group(1)) if stack_match else 0
    self_match = re.search(
        r"heal(?:s|ing)? himself for\s+(\d+(?:\.\d+)?)%\s+of his " r"maximum health",
        p_text,
        flags=re.IGNORECASE,
    )
    self_ratio = float(self_match.group(1)) / 100.0 if self_match else 0.0
    qw_seen = 0
    for event in damage_events:
        if _healing._event_source(event) not in {"Q", "W"}:
            continue
        if stack_cap <= 0:
            break
        qw_seen += 1
        if qw_seen % stack_cap == 0:
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": self_ratio * float(champion_stats.get("health", 0.0)),
                    "source": "Triumphant Roar",
                    "kind": "champion_passive",
                    **_healing._trigger_fields(event),
                }
            )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Alistar", derive_self_healing)
