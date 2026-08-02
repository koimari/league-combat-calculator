"""Slot-archetype engine — runs any champion from a slot map.

A champion is described by a **slot map**: ``{slot_key: slot_parser}``.
A slot parser is a plain function ``SlotCtx -> entry dict | None``,
produced either by an archetype factory in ``slotlib`` (configured with
data) or written as a custom function in the champion's own module.

Slots are evaluated **phase by phase** in ``PHASE_ORDER``
(BUFF -> DEBUFF -> DAMAGE -> ONHIT -> AMP), and in slot-map insertion
order within a phase. BUFF/DEBUFF parsers mutate the shared
``ctx.stats`` / ``ctx.target`` contexts, so damage slots always see
buffed stats — an engine guarantee, not a per-module comment. Parsers
carry their phase as a ``.phase`` attribute stamped by their factory;
plain functions without one default to DAMAGE. ``ctx.results`` is
readable within a phase, so a cross-slot dependent lists after its
dependency in the map.

Engine contract: any non-None entry a parser returns IS emitted —
including zero-damage entries (stat-buff ultimates must never silently
vanish). Dropping a non-damaging slot is the parser's decision.
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from .skill_orders import get_ability_rank

# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

BUFF = "buff"  # mutates ctx.stats (e.g. R steroids) — no damage yet
DEBUFF = "debuff"  # mutates ctx.target (e.g. resist shreds)
DAMAGE = "damage"  # emits castable damage entries (the default phase)
ONHIT = "onhit"  # emits on-hit entries layered onto auto attacks
AMP = "amp"  # scales already-computed entries (reads ctx.results)

PHASE_ORDER = (BUFF, DEBUFF, DAMAGE, ONHIT, AMP)

SlotParser = Callable[["SlotCtx"], dict[str, Any] | None]

# Every key an emitted entry may carry. The fight engine reads the first
# group; the second is producer-side diagnostics and champion display
# metadata (never engine-read). An unknown key raises at parse time —
# a misspelled key must never silently zero an ability.
_ALLOWED_ENTRY_KEYS = frozenset(
    {
        # fight-engine contract
        "name",
        "rank",
        "cooldown",
        "cast_time",
        "resource_cost",
        "resource_type",
        "resource_restore",
        "resource_restore_per_proc",
        "resource_maximum_bonus",
        "resource_maximum_bonus_duration",
        "damage_type",
        "parts",
        "cast_instances",
        "recast_of",
        "empowers_next_auto",
        "stat_buff",
        "target_debuff",
        "on_hit",
        "proc_count",
        "dot_duration",
        "stacking_dot",
        "stack_triggered_buff",
        "applies_dot_stack",
        "applies_item_on_hits",
        "basic_attack_true_ratio",
        "spellblade_true_ratio",
        "spellblade_bonus_true_ratio",
        "auto_attack_override",
        "auto_attack_conversion",
        "double_shot",
        "target_max_health_sensitive",
        "detail",  # display text copied onto the ability's breakdown row
        "unit",  # count label for a proc row ("cleaves"); default is "hits"
        # producer diagnostics / display metadata
        "total_raw",
        "damage_per_tick",
        "total_ticks",
        "tibbers_aura",
        "initial_burst",
    }
)

# Keys a ``target_debuff`` payload may carry. Validated for the same
# reason as the entry keys one level up: a misspelled
# ``mr_reduction_flatt`` would silently shred nothing.
_ALLOWED_DEBUFF_KEYS = frozenset(
    {
        "armor_reduction_percent",
        "mr_reduction_percent",
        "armor_reduction_flat",
        "mr_reduction_flat",
        "stacks",  # ramp the reduction one share per hit, up to N
        "duration",  # seconds the shred lasts; absent = rest of the fight
    }
)


# ---------------------------------------------------------------------------
# Slot context
# ---------------------------------------------------------------------------


@dataclass
class SlotCtx:
    """Everything a slot parser may read (and, per phase, mutate).

    ``stats``, ``target``, and ``results`` are shared across all slots of
    one parse: BUFF/DEBUFF phases mutate the first two, and ``results``
    accumulates emitted entries in evaluation order.
    """

    slot: str  # slot-map key being parsed
    champion_name: str  # for skill-order lookup
    abilities: dict[str, list] = field(default_factory=dict)
    level: int = 1
    stats: dict[str, float] = field(default_factory=dict)
    target: dict[str, float] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    ability_ranks: dict[str, int] | None = None

    def ability(self, slot: str | None = None, index: int = 0) -> dict | None:
        """Return the ability JSON at (slot, index), or None if absent.

        Defaults to entry 0 of this parser's own slot; archetypes pass
        their ``source=(slot, index)`` here for multi-entry slots.
        """
        entries = self.abilities.get(slot or self.slot, [])
        if index >= len(entries):
            return None
        return entries[index]

    def rank_for(self, slot: str | None = None) -> int:
        """Resolve the ability rank: explicit override, else skill order."""
        key = slot or self.slot
        if self.ability_ranks and key in self.ability_ranks:
            return self.ability_ranks[key]
        return get_ability_rank(key, self.level, self.champion_name)


# ---------------------------------------------------------------------------
# Parser builder
# ---------------------------------------------------------------------------


def _stamp_cast_time(
    entry: dict[str, Any], ability_json: dict[str, Any] | None
) -> None:
    """Stamp a castable entry with its slot JSON's cast time.

    One home instead of every slot parser (module or generic) plumbing
    it. Only castable entries (they carry a cooldown) occupy the timed
    fight's shared cast timeline; slot-fn-supplied values win; instant
    casts (0.0) stay unstamped so entries stay lean and cast-time-less
    data keeps legacy cast counts.
    """
    if "cooldown" not in entry or "cast_time" in entry or ability_json is None:
        return
    # Deferred import: slotlib imports the phase constants from this
    # module, so engine.py must not import slotlib at module level.
    # pylint: disable-next=import-outside-toplevel,cyclic-import
    from .slotlib import extract_cast_time

    cast_time = extract_cast_time(ability_json)
    if cast_time > 0:
        entry["cast_time"] = cast_time


def _stamp_resource_cost(
    entry: dict[str, Any],
    ability_json: dict[str, Any] | None,
    *,
    rank: int,
    level: int,
    resource_type: str,
) -> None:
    """Stamp a cast's locally sourced resource cost onto its engine entry."""
    if "resource_cost" in entry or ability_json is None:
        return
    if resource_type not in {"MANA", "ENERGY"} or "cooldown" not in entry:
        return
    entry["resource_type"] = resource_type
    if entry.get("recast_of"):
        entry["resource_cost"] = 0.0
        return
    modifiers = (ability_json.get("cost") or {}).get("modifiers", [])
    if not modifiers:
        entry["resource_cost"] = 0.0
        return
    values = modifiers[0].get("values", [])
    if not values:
        entry["resource_cost"] = 0.0
        return
    index = level - 1 if len(values) >= 18 else rank - 1
    if index < 0:
        entry["resource_cost"] = 0.0
        return
    entry["resource_cost"] = float(values[min(index, len(values) - 1)])


def _validate_entry_keys(
    champion_name: str,
    result_key: str,
    entry: dict[str, Any],
) -> None:
    """Reject unknown keys on an emitted entry and its target_debuff.

    A misspelled key must never silently zero an ability (or, one level
    down, silently shred nothing).
    """
    for keys, allowed, label, constant in (
        (set(entry), _ALLOWED_ENTRY_KEYS, "entry", "_ALLOWED_ENTRY_KEYS"),
        (
            set(entry.get("target_debuff", ())),
            _ALLOWED_DEBUFF_KEYS,
            "target_debuff",
            "_ALLOWED_DEBUFF_KEYS",
        ),
    ):
        unknown = keys - allowed
        if unknown:
            raise ValueError(
                f"{champion_name} entry {result_key!r}: unknown {label} "
                f"key(s) {sorted(unknown)} (allowed keys are defined by "
                f"engine.{constant})"
            )


def _result_key(slot: str) -> str:
    """Map a slot-map key to its key in the results dict.

    The fight engine expects the passive under ``"passive"``; every
    other slot keeps its own key.
    """
    return "passive" if slot == "P" else slot


def build_parser(
    slot_map: dict[str, SlotParser],
    champion_name: str,
) -> Callable[..., dict[str, dict[str, Any]]]:
    """Build a ``parse_abilities``-signature function from a slot map.

    Slot evaluation order (phase, then insertion order) is fixed here,
    once, at build time.

    Args:
        slot_map: Mapping of slot key (Q/W/E/R/P/...) to slot parser.
        champion_name: Display name, used for skill-order lookup.

    Returns:
        A function with the standard champion-module signature
        ``(champion_data, level, total_ability_power, ability_ranks=None,
        champion_options=None, champion_stats=None, target_stats=None)
        -> results dict``.
    """
    ordered: list[tuple[str, SlotParser]] = []
    for phase in PHASE_ORDER:
        for slot, parser in slot_map.items():
            parser_phase = getattr(parser, "phase", DAMAGE)
            if parser_phase not in PHASE_ORDER:
                raise ValueError(
                    f"{champion_name} slot {slot!r}: unknown phase "
                    f"{parser_phase!r} (must be one of {PHASE_ORDER})"
                )
            if parser_phase == phase:
                ordered.append((slot, parser))

    def parse_abilities(
        champion_data: dict[str, Any],
        level: int,
        total_ability_power: float,
        ability_ranks: dict[str, int] | None = None,
        champion_options: dict[str, Any] | None = None,
        champion_stats: dict[str, float] | None = None,
        target_stats: dict[str, float] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Parse abilities by evaluating the slot map phase-by-phase."""
        # Deferred import: slotlib imports the phase constants from this
        # module, so engine.py must not import slotlib at module level.
        # pylint: disable-next=import-outside-toplevel,cyclic-import
        from .slotlib import build_stats_context

        stats = build_stats_context(champion_stats, total_ability_power)
        target = dict(target_stats) if target_stats else {}
        results: dict[str, dict[str, Any]] = {}

        for slot, parser in ordered:
            ctx = SlotCtx(
                slot=slot,
                champion_name=champion_name,
                abilities=champion_data.get("abilities", {}),
                level=level,
                stats=stats,
                target=target,
                options=champion_options or {},
                results=results,
                ability_ranks=ability_ranks,
            )
            entry = parser(ctx)
            if entry is not None:
                ability_json = ctx.ability()
                _stamp_cast_time(entry, ability_json)
                _stamp_resource_cost(
                    entry,
                    ability_json,
                    rank=ctx.rank_for(),
                    level=level,
                    resource_type=str(champion_data.get("resource", "NONE")),
                )
                results[_result_key(slot)] = entry

        # Validate AFTER all phases: AMP parsers mutate earlier entries,
        # and a mutated entry must obey the contract too.
        for result_key, entry in results.items():
            _validate_entry_keys(champion_name, result_key, entry)

        return results

    return parse_abilities
