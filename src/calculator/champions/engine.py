"""Slot-archetype engine — runs any champion from a slot map.

A champion is described by a **slot map**: ``{slot_key: slot_parser}``.
A slot parser is a plain function ``SlotCtx -> entry dict | None``,
produced either by an archetype factory in ``slotlib`` (configured with
data, over the JSON walk in ``slot_extract``, the entry dicts in
``slot_entries`` and the control atoms in ``slot_control``) or written as a
custom function in the champion's own module.

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

from collections.abc import Callable, Mapping
from typing import Any

from .entry_shape import EmittedSlot, certify_shared_instant, validate_entry_keys
from .inputs import declared_option_defaults
from .slot_cc import (
    _apply_module_cc,
    _refuse_undeclared_part_cc,
    _resolve_pending_control_events,
    _validate_cc_event_contract,
)
from .slot_context import (
    AMP,
    BUFF,
    DAMAGE,
    DEBUFF,
    ONHIT,
    PHASE_ORDER,
    SlotCtx,
    SlotParser,
)
from .slot_extract import build_stats_context, extract_cast_time, extract_resource_cost

__all__ = [
    "AMP",
    "BUFF",
    "DAMAGE",
    "DEBUFF",
    "ONHIT",
    "PHASE_ORDER",
    "SlotCtx",
    "SlotParser",
    "build_parser",
]


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

    One home instead of every slot parser plumbing it. Only castable
    entries (they carry a cooldown) occupy the timed fight's shared cast
    timeline; slot-fn-supplied values win; instant casts (0.0) stay
    unstamped, so an entry with no cast time is counted as an instant.
    """
    if "cooldown" not in entry or "cast_time" in entry or ability_json is None:
        return
    memo = _CAST_TIME_MEMO.get(id(ability_json))
    if memo is not None and memo[0] is ability_json:
        cast_time = memo[1]
    else:
        cast_time = extract_cast_time(ability_json)
        _CAST_TIME_MEMO[id(ability_json)] = (ability_json, cast_time)
    if cast_time > 0:
        entry["cast_time"] = cast_time


# Camille's and Ambessa's Q2 are free recasts: one paid cast buys both halves.
# A charge is not one, it is a whole cast stocked in advance, and a slot
# parser that knows the difference stamps its own ``resource_cost``.
def _is_free_recast(entry: Mapping[str, Any]) -> bool:
    """Whether this entry is a recast the parent cast already paid for."""
    return bool(entry.get("recast_of"))


def _stamp_resource_cost(
    entry: dict[str, Any],
    ability_json: dict[str, Any] | None,
    *,
    rank: int,
    level: int,
    resource_type: str,
) -> None:
    """Stamp a cast's locally sourced resource cost onto its engine entry.

    A slot parser that stamps its own ``resource_cost`` wins outright — the
    price of a synthetic slot, which owns no ability JSON of its own, is
    champion knowledge and only the module has it.
    """
    if "resource_cost" in entry or ability_json is None:
        return
    if resource_type not in {"MANA", "ENERGY"} or "cooldown" not in entry:
        return
    entry["resource_type"] = resource_type
    if _is_free_recast(entry):
        entry["resource_cost"] = 0.0
        return
    memo_key = (id(ability_json), rank, level)
    memo = _RESOURCE_COST_MEMO.get(memo_key)
    if memo is not None and memo[0] is ability_json:
        entry["resource_cost"] = memo[1]
        return
    cost = extract_resource_cost(ability_json, rank, level)
    _RESOURCE_COST_MEMO[memo_key] = (ability_json, cost)
    entry["resource_cost"] = cost


def _stamp_slot_facts(
    entry: dict[str, Any],
    ctx: "SlotCtx",
    *,
    level: int,
    resource_type: str,
) -> None:
    """Stamp the facts a slot's own cached ability entry carries.

    One call site instead of two, so a slot's cast time and its price are
    read from the same ability JSON or from neither: a synthetic slot owns
    no entry at all, and both stamps hand it straight back.
    """
    ability_json = ctx.ability()
    _stamp_cast_time(entry, ability_json)
    if ability_json is not None:
        # Source-backed delivery markers the coupled target-defense ledger
        # reads (Braum E / Yasuo W block projectiles; Jax E counters area
        # damage): stamped from the cached ability row, never inferred.
        if ability_json.get("projectile") not in (None, ""):
            entry.setdefault("skillshot", True)
        spell_effects = str(ability_json.get("spellEffects", "")).lower()
        if "aoe" in spell_effects or "area of effect" in spell_effects:
            entry.setdefault("area_damage", True)
    _stamp_resource_cost(
        entry,
        ability_json,
        rank=ctx.rank_for(),
        level=level,
        resource_type=resource_type,
    )


def _result_key(slot: str) -> str:
    """The results-dict key for a slot; the fight engine wants ``"passive"``."""
    return "passive" if slot == "P" else slot


def build_parser(
    slot_map: dict[str, SlotParser],
    champion_name: str,
    *,
    cc_kinds: Mapping[str, str] | None = None,
) -> Callable[..., dict[str, dict[str, Any]]]:
    """Build a ``parse_abilities``-signature function from a slot map.

    Slot evaluation order (phase, then insertion order) is fixed here,
    once, at build time.

    Args:
        slot_map: Mapping of slot key (Q/W/E/R/P/...) to slot parser.
        champion_name: Display name, used for skill-order lookup.
        cc_kinds: The module's ``MODULE_CC`` declaration — ``{slot: kind}``
            reviewed crowd control, stamped onto every part the slot emits
            (:func:`_apply_module_cc`).  Keyword-only, and echoed on the
            returned parser so ``module_contract`` can prove the wiring and
            the declaration are the same dict.  Absent for the synthetic
            slot map, which declares no kit facts of its own.

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

    # The module's OPTIONS defaults, resolved on the first parse rather than
    # here: this builder runs while the champion module is still executing,
    # so its OPTIONS list does not exist yet.  A module's declaration is
    # source, so one resolution per champion per process is the whole cost.
    declared_options: dict[str, Any] | None = None
    declared_cc_kinds: Mapping[str, str] = dict(cc_kinds) if cc_kinds else {}
    declared_result_keys = frozenset(_result_key(slot) for slot in declared_cc_kinds)

    def parse_abilities(
        champion_data: dict[str, Any],
        level: int,
        total_ability_power: float,
        ability_ranks: dict[str, int] | None = None,
        *,
        champion_options: dict[str, Any] | None = None,
        champion_stats: dict[str, float] | None = None,
        target_stats: dict[str, float] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Parse abilities by evaluating the slot map phase-by-phase."""
        nonlocal declared_options
        if declared_options is None:
            declared_options = declared_option_defaults(champion_name)
        stats = build_stats_context(champion_stats, total_ability_power)
        target = dict(target_stats) if target_stats else {}
        resource_type = str(champion_data.get("resource", "NONE"))
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
                option_defaults=declared_options,
            )
            entry = parser(ctx)
            if entry is not None:
                _stamp_slot_facts(entry, ctx, level=level, resource_type=resource_type)
                results[_result_key(slot)] = entry

        # Stamp and validate AFTER all phases: AMP parsers mutate earlier
        # entries, and a mutated entry must obey the contract too — Amumu's
        # Cursed Touch appends a true part to every damage slot in the kit,
        # and a part the declaration never reached is an unreviewed event.
        for slot, declared_cc in declared_cc_kinds.items():
            entry = results.get(_result_key(slot))
            if entry is not None:
                _apply_module_cc(entry, declared_cc, champion_name, slot)
        declared_by_key = {_result_key(s): k for s, k in declared_cc_kinds.items()}
        for result_key, entry in results.items():
            emitted = EmittedSlot(champion_name, result_key)
            _resolve_pending_control_events(emitted, entry)
            certify_shared_instant(emitted, entry)
            validate_entry_keys(emitted, entry)
            _refuse_undeclared_part_cc(emitted, entry, declared_result_keys)
            _validate_cc_event_contract(emitted, entry, declared_by_key.get(result_key))

        return results

    if cc_kinds is not None:
        parse_abilities.cc_kinds = declared_cc_kinds
    return parse_abilities
