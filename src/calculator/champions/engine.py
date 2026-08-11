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
        "resource_restore_per_auto",
        "mark_refund",
        # P4-14: Darius W's asserted kill rule (cooldown halved + flat
        # mana refund) — emitted only when the w_kill_assertion option is
        # on; validated by the resource walk's fail-closed declaration.
        "kill_refund",
        "resource_maximum_bonus",
        "resource_maximum_bonus_duration",
        "damage_type",
        "parts",
        # P3 package 3V: the Ferocity-empowered part set (Rengar Q/W/E) —
        # the engine prices it for live empowered casts chosen by the
        # post-rotation stack walk.
        "ferocity_parts",
        "cast_instances",
        "recast_of",
        "empowers_next_auto",
        # P4: documentary certification surfaces on state rows (Yasuo/
        # Yone P crit-conversion constants — the Asol rule pattern).
        "atom_ids",
        "certified_constants",
        "stat_buff",
        "target_debuff",
        "post_hit_proc",
        "on_hit",
        "proc_count",
        "dot_duration",
        "dot_tick_interval",
        "deathfire_category",
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
        "requires_auto_timeline_coupling",
        "execute_threshold_ratio",
        "execute_source",
        "detail",  # display text copied onto the ability's breakdown row
        "unit",  # count label for a proc row ("cleaves"); default is "hits"
        # producer diagnostics / display metadata
        "total_raw",
        "damage_per_tick",
        "total_ticks",
        "tibbers_aura",
        "initial_burst",
        # Authored event ledgers for fixed-count effects.  These are copied
        # into the damage timeline by the fight engine; they are not inferred
        # from aggregate totals.
        "damage_events",
        "control_events",
        "control_source_atoms",
        "cc_reviewed",
        "event_phase",
        # Explicit module-owned proof that a dynamic packet is one hit at
        # the cast boundary; this is never inferred from part count alone.
        "event_order_certified",
        "auto_stack_every",
        "short_fuse_cooldown",
        "short_fuse_refund",
        "timeline_event_model",
        "dot_stack_count",
        # Module-authored self-shield payloads (E8c).  A list aligned to the
        # ability's damage-event ordinals; the fight engine copies each entry
        # onto the matching damage event row as ``self_shield``, which the
        # participant ledger turns into a timed self-shield event at that
        # event's timestamp (the Eclipse item authors the same payload shape).
        "self_shield_events",
        # Module-authored non-damage state packets.  The pipeline expands
        # these once per accepted cast and sends them to the participant
        # ledger as typed state transitions.
        "self_state_events",
        # Champion-owned critical-strike conversion (Yasuo/Yone P): total
        # crit chance doubled, crit damage scaled by a factor, and excess
        # crit chance converted to bonus AD.  The fight engine resolves it
        # once in ``_apply_stat_buff_ultimates`` so ability crit scaling and
        # the auto-attack simulation share the converted values.
        "crit_modifier",
        # A source-backed ability projectile marker used by the coupled
        # target-defense ledger.  It is stamped from the cached ability row.
        "skillshot",
        # A source-backed area-ability marker used by Jax Counter Strike.
        "area_damage",
        "defensive_interaction",
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
        "threshold_hits",  # apply the full reduction after N hits
        "duration",  # seconds the shred lasts; absent = rest of the fight
    }
)

_ALLOWED_POST_HIT_PROC_KEYS = frozenset(
    {
        "name",
        "breakdown_key",
        "parts",
        "target_debuff",
        "detail",
    }
)


# ---------------------------------------------------------------------------
# Slot context
# ---------------------------------------------------------------------------


@dataclass(slots=True)
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


# The coupled optimizer re-parses the same champion for thousands of fights,
# so values derived purely from the cached ability JSON are memoized by
# object identity.  Entries keep a strong reference to their source dict and
# verify it on every hit (the ``resolve_damage_effects`` pattern), so a
# data refresh that rebuilds the champion cache can never serve stale
# values through a recycled ``id()``.  Superseded generations are kept, not
# evicted — a deliberate, patch-cadence-bounded leak shared by every
# identity memo in this codebase.
_CAST_TIME_MEMO: dict[int, tuple[dict[str, Any], float]] = {}
_RESOURCE_COST_MEMO: dict[tuple[int, int, int], tuple[dict[str, Any], float]] = {}


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
    memo = _CAST_TIME_MEMO.get(id(ability_json))
    if memo is not None and memo[0] is ability_json:
        cast_time = memo[1]
    else:
        # Deferred import: slotlib imports the phase constants from this
        # module, so engine.py must not import slotlib at module level.
        # pylint: disable-next=import-outside-toplevel,cyclic-import
        from .slotlib import extract_cast_time

        cast_time = extract_cast_time(ability_json)
        _CAST_TIME_MEMO[id(ability_json)] = (ability_json, cast_time)
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
    memo_key = (id(ability_json), rank, level)
    memo = _RESOURCE_COST_MEMO.get(memo_key)
    if memo is not None and memo[0] is ability_json:
        entry["resource_cost"] = memo[1]
        return
    modifiers = (ability_json.get("cost") or {}).get("modifiers", [])
    values = modifiers[0].get("values", []) if modifiers else []
    if not values:
        cost = 0.0
    else:
        index = level - 1 if len(values) >= 18 else rank - 1
        cost = 0.0 if index < 0 else float(values[min(index, len(values) - 1)])
    _RESOURCE_COST_MEMO[memo_key] = (ability_json, cost)
    entry["resource_cost"] = cost


# Key shapes that already passed validation.  Entries are rebuilt per
# parse but their key sets are fixed per (champion, slot, options) code
# path, so the optimizer's thousands of identical parses validate once.
# A never-seen shape — including one produced by a code change — is
# always fully checked.
_VALIDATED_ENTRY_SHAPES: set[tuple[Any, ...]] = set()


def _validate_entry_keys(
    champion_name: str,
    result_key: str,
    entry: dict[str, Any],
) -> None:
    """Reject unknown keys on an emitted entry and its target_debuff.

    A misspelled key must never silently zero an ability (or, one level
    down, silently shred nothing).
    """
    post_hit_proc = entry.get("post_hit_proc") or {}
    shape = (
        champion_name,
        result_key,
        tuple(entry),
        tuple(entry.get("target_debuff", ())),
        tuple(post_hit_proc),
        tuple(post_hit_proc.get("target_debuff", ()) if post_hit_proc else ()),
    )
    if shape in _VALIDATED_ENTRY_SHAPES:
        return
    for keys, allowed, label, constant in (
        (set(entry), _ALLOWED_ENTRY_KEYS, "entry", "_ALLOWED_ENTRY_KEYS"),
        (
            set(entry.get("target_debuff", ())),
            _ALLOWED_DEBUFF_KEYS,
            "target_debuff",
            "_ALLOWED_DEBUFF_KEYS",
        ),
        (
            set(entry.get("post_hit_proc", ())),
            _ALLOWED_POST_HIT_PROC_KEYS,
            "post_hit_proc",
            "_ALLOWED_POST_HIT_PROC_KEYS",
        ),
        (
            set((entry.get("post_hit_proc") or {}).get("target_debuff", ())),
            _ALLOWED_DEBUFF_KEYS,
            "post_hit_proc.target_debuff",
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
    _VALIDATED_ENTRY_SHAPES.add(shape)


def _result_key(slot: str) -> str:
    """Map a slot-map key to its key in the results dict.

    The fight engine expects the passive under ``"passive"``; every
    other slot keeps its own key.
    """
    return "passive" if slot == "P" else slot


def _stamp_reviewed_no_cc(
    champion_name: str,
    result_key: str,
    entry: dict[str, Any],
) -> None:
    """Stamp one entry only when its module certifies that it has no CC."""
    parts = tuple(entry.get("parts", ())) + tuple(entry.get("ferocity_parts", ()))
    has_typed_control = bool(entry.get("control_events")) or any(
        getattr(part, "cc_kind", None) is not None for part in parts
    )
    if has_typed_control:
        raise ValueError(
            f"{champion_name} entry {result_key!r} emits crowd control "
            "under reviewed_no_cc"
        )
    entry["cc_reviewed"] = True


def build_parser(
    slot_map: dict[str, SlotParser],
    champion_name: str,
    *,
    cc_review_status: str | None = None,
) -> Callable[..., dict[str, dict[str, Any]]]:
    """Build a ``parse_abilities``-signature function from a slot map.

    Slot evaluation order (phase, then insertion order) is fixed here,
    once, at build time.

    Args:
        slot_map: Mapping of slot key (Q/W/E/R/P/...) to slot parser.
        champion_name: Display name, used for skill-order lookup.
        cc_review_status: Explicit module-level crowd-control review status.
            ``"reviewed_no_cc"`` certifies that every emitted entry has no
            enemy crowd control. An absent value leaves every untyped entry
            unreviewed.

    Returns:
        A function with the standard champion-module signature
        ``(champion_data, level, total_ability_power, ability_ranks=None,
        champion_options=None, champion_stats=None, target_stats=None)
        -> results dict``.
    """
    if cc_review_status not in {None, "reviewed_no_cc"}:
        raise ValueError(
            f"{champion_name}: unsupported cc_review_status " f"{cc_review_status!r}"
        )

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
                if ability_json is not None and ability_json.get("projectile") not in (
                    None,
                    "",
                ):
                    entry.setdefault("skillshot", True)
                if ability_json is not None:
                    spell_effects = str(ability_json.get("spellEffects", "")).lower()
                    if "aoe" in spell_effects or "area of effect" in spell_effects:
                        entry.setdefault("area_damage", True)
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
            if cc_review_status == "reviewed_no_cc":
                _stamp_reviewed_no_cc(champion_name, result_key, entry)
            _validate_entry_keys(champion_name, result_key, entry)

        return results

    setattr(parse_abilities, "cc_review_status", cc_review_status)
    return parse_abilities
