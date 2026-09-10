"""The ComboRule fitted to one fight from a champion's DPS matrix."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any

from .ability_dps_matrix import _matrix_dps_rows, rank_ability_dps
from .cast_dependency import CastDependency, ResolvedCycleError
from .cast_edge_markers import _recast_parent, detect_aoe_cap
from .cast_edge_resolution import _kahn_order, resolved_edges
from .cast_order_overrides import ComboRule
from .champions import (
    get_champion_cast_dependencies,
    get_champion_option_rotation,
    get_champion_options_meta,
    parse_champion_abilities,
)
from .data_registry import data_version
from .fight.cast_slots import DEFAULT_CAST_ORDER
from .stats import calculate_total_stats

# per-(champion, option-signature, data version) cache: the FULL-KIT derived
# rule (order is matrix-invariant by construction; the fight's own level/build
# only narrows which slots exist, and the option signature keeps option-gated
# slots and option-sensitive edges deterministic across cache warmth).
_DERIVED_RULE_CACHE: dict[
    tuple[str, frozenset[tuple[str, Any]] | None, int], ComboRule
] = {}


def _canonical_kit_parse(
    champion_data: Mapping[str, Any],
    champion_options: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """The full-kit parse (level 11, no items) used for the cached derivation.

    The derived order is matrix-invariant by construction, so the derivation
    runs once against the canonical kit; a request's own level/build only
    narrow which slots exist.  The request's OPTION state is part of the
    derivation: option-gated slots (Kalista's Soul-Marked W) and
    option-sensitive edges are derived per option state, so a cold cache
    cannot drop a slot the fight actually casts.
    """

    data = dict(champion_data)
    stats = calculate_total_stats(data, 11, [])
    return parse_champion_abilities(
        data,
        11,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
        champion_options=champion_options,
    )


def _freeze_option_value(value: Any) -> Any:
    """Convert JSON-shaped option values into stable cache-key values."""
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (str(key), _freeze_option_value(item)) for key, item in value.items()
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_option_value(item) for item in value)
    return value


def _option_signature(
    champion_name: str, champion_options: Mapping[str, Any] | None
) -> frozenset[tuple[str, Any]] | None:
    """A canonical cache discriminator for the derivation's option state.

    Only the champion's DECLARED option keys participate, so pipeline keys
    (``fight_duration_seconds``, ...) never split the cache; ``None``/empty
    maps to ``None`` so the default-option derivation keeps one cache row
    per champion.
    """
    if not champion_options:
        return None

    declared = {
        str(opt.get("key", ""))
        for opt in get_champion_options_meta(champion_name).get("options", [])
    }
    return frozenset(
        (key, _freeze_option_value(champion_options[key]))
        for key in sorted(champion_options)
        if key in declared
    )


def _fit_rule_to_fight(
    cached: ComboRule,
    champion_name: str,
    fight_slots: Collection[str],
    certified_order: list[str] | None,
) -> ComboRule:
    """Filter a full-kit rule to the fight's parsed slots.

    The cached rule is the FULL-KIT derivation (matrix-invariant); the
    fight's own parse decides which slots exist — filter the order to the
    available slots, preserving relative positions.  Option-gated slots
    absent from the canonical kit (Kalista's Soul-Marked W, Gnar's Mega R)
    fall back to their base-order position.  Applied on BOTH the warm-cache
    and cold-cache paths so the result is deterministic across cache warmth.
    """
    available = [s for s in cached.order if s in fight_slots]
    base = [
        s for s in (certified_order or list(DEFAULT_CAST_ORDER)) if s in fight_slots
    ]
    for slot in base:
        if slot not in available:
            available.append(slot)
    return ComboRule(
        champion=champion_name,
        order=tuple(available) if available else cached.order,
        rationale=cached.rationale,
        sources=cached.sources,
        setup=cached.setup,
        consume=cached.consume,
        aoe=dict(cached.aoe),
        derived=True,
    )


# comment-ok: width - a pylint pragma cannot wrap
def derive_champion_rule(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-arguments
    champion_name: str,
    ability_damages: Mapping[str, Any],
    champion_data: Mapping[str, Any],
    certified_order: list[str] | None = None,
    champion_options: Mapping[str, Any] | None = None,
    *,
    declarations: Sequence[CastDependency] | None = None,
) -> ComboRule:
    """Algorithmically derive the champion's optimal cast order.

    Steps (see the module docstring and ``docs/rotation-design.md``):

    1. Detect setup/consume edges from the typed atoms and the module
       OPTIONS rotation declarations (see
       :func:`detect_setup_consume_edges`).
    2. Base order = certified module ``CAST_ORDER`` when present, else the
       engine ``DEFAULT_CAST_ORDER``.
    3. No edges → keep the base order (honest flat-kit fallback; the
       rationale never claims "no signal" while an enabled option is
       unclassified or unsupported).
    4. Edges → topological sort; free slots ranked by per-rank DPS at the
       fight's stats, but only when the ranking is CONSISTENT across the
       level/build matrix (else the certified/base relative order is kept,
       which is deterministic across builds by construction).
    5. Build a :class:`ComboRule` with a rationale citing the driving
       atoms and the setup/consume/aoe receipts.

    The derivation is cached per (champion, option signature): the canonical
    kit is parsed with the request's option state, so option-gated slots
    (Kalista's Soul-Marked W) and option-sensitive edges derive per option
    state instead of dropping out on a cold cache.

    Args:
        declarations: A declaration set to derive against *instead of* the
            module's own — the probe seam.  Passing one asks a
            counterfactual ("what order would this champion take without
            this dependency?"), which is how the audit measures whether a
            declaration is load-bearing without monkey-patching the
            champion package.  A probe is never memoised: its answer is
            about a kit the module does not declare, and the memo has one
            row per (champion, option signature, data version) to serve it
            to everybody from.

    Returns:
        The derived rule (``derived=True``).  The order is a permutation
        of the fight's base slots — no new slots, none dropped.
    """
    fight_slots = {
        s for s in ability_damages if isinstance(ability_damages.get(s), Mapping)
    }
    signature = _option_signature(champion_name, champion_options)
    cache_key = (champion_name, signature, data_version())
    memoised = declarations is None
    cached = _DERIVED_RULE_CACHE.get(cache_key) if memoised else None
    if cached is not None:
        return _fit_rule_to_fight(cached, champion_name, fight_slots, certified_order)

    def remember(rule: ComboRule) -> ComboRule:
        """Memoise the FULL-KIT rule, then return this fight's fit."""
        # Cache the FULL-KIT rule and never the fitted one:
        # ``_fit_rule_to_fight`` narrows the order to the slots one parse
        # holds, so caching the fit would let whichever request arrived
        # first decide what every later one is served.
        if memoised:
            _DERIVED_RULE_CACHE[cache_key] = rule
        return _fit_rule_to_fight(rule, champion_name, fight_slots, certified_order)

    # Derive from the CANONICAL full-kit parse (level 11, no items), not the
    # request's parse — the request may be a partial kit (level 1) and the
    # derivation must reflect the champion's complete mechanic surface.  The
    # request's option state is honored so option-gated slots participate.
    ability_damages = _canonical_kit_parse(champion_data, champion_options)

    base = [
        s
        for s in (certified_order or list(DEFAULT_CAST_ORDER))
        if isinstance(ability_damages.get(s), Mapping)
    ]
    aoe = {
        s: detect_aoe_cap(
            champion_data, s, recast_of=_recast_parent(ability_damages[s])
        )
        for s in ability_damages
        if isinstance(ability_damages[s], Mapping)
    }

    # slot_options is built from the AUTHORITATIVE rotation declarations:
    # roles setup/consume/execute feed edge detection; self_state and
    # irrelevant options are acknowledged in the receipt without inventing
    # edges; an unclassified or unsupported option is surfaced verbatim.
    meta = get_champion_options_meta(champion_name)
    rotations = get_champion_option_rotation(champion_name)
    slot_options: dict[str, list[str]] = {}
    option_receipts: list[str] = []
    for opt in meta.get("options", []):
        key = str(opt.get("key", ""))
        decl = rotations.get(key)
        if not decl:
            option_receipts.append(f"option {key} (unclassified rotation semantics)")
            continue
        role = str(decl.get("role", ""))
        slot = decl.get("slot")
        if role in ("setup", "consume", "execute"):
            if slot:
                slot_options.setdefault(slot, []).append(key)
            else:
                slot_options.setdefault("__all__", []).append(key)
            option_receipts.append(
                f"option {key} ({role}"
                + (f", slot {slot}" if slot else "")
                + (f", consumes {decl['setup_slot']}" if decl.get("setup_slot") else "")
                + ")"
            )
        elif role in ("self_state", "irrelevant"):
            option_receipts.append(
                f"option {key} ({role}" + (f", slot {slot}" if slot else "") + ")"
            )
        elif role == "unsupported":
            option_receipts.append(f"option {key} (unsupported rotation semantics)")

    if declarations is None:
        declarations = get_champion_cast_dependencies(champion_name)
    merged, _receipt = resolved_edges(
        champion_name,
        ability_damages,
        champion_data,
        slot_options,
        declarations=declarations,
    )
    edges = list(merged)

    if not edges:
        unclassified = [
            line
            for line in option_receipts
            if "unclassified" in line or "unsupported" in line
        ]
        if unclassified:
            # A rotation receipt cannot claim "no detectable setup/consume
            # signal" while an enabled semantic option is unclassified or
            # unsupported.
            rationale = (
                f"{champion_name} has option(s) not yet classified for "
                "rotation semantics: "
                + "; ".join(unclassified)
                + ". The certified module order"
                + (
                    " " + " → ".join(certified_order)
                    if certified_order
                    else " (engine default Q → Q2 → W → E → R)"
                )
                + " is kept exactly as reviewed."
            )
        else:
            rationale = (
                f"{champion_name} has no detectable setup/consume signal in the "
                "atomized ability data — no DoT/poison/mark/stack consumer, no "
                "resistance shred, no damage-amplifying buff, no missing-health "
                "execute. The certified module order"
                + (
                    " " + " → ".join(certified_order)
                    if certified_order
                    else " (engine default Q → Q2 → W → E → R)"
                )
                + " is kept exactly as reviewed; the flat kit derives no reorder."
            )
            if option_receipts:
                rationale += (
                    " Declared options classified for rotation: "
                    + ", ".join(option_receipts)
                    + "."
                )
        rule = ComboRule(
            champion=champion_name,
            order=tuple(base),
            rationale=rationale,
            sources=(
                "no setup/consume atoms detected (flat kit)",
                *tuple(option_receipts),
            ),
            setup=(),
            consume=(),
            aoe=aoe,
            derived=True,
        )
        return remember(rule)

    base_idx = {s: i for i, s in enumerate(base)}
    outgoing = {s: any(e.setup == s for e in edges) for s in base}

    def tie_base(s: str) -> tuple[int, int]:
        return (0 if outgoing.get(s) else 1, base_idx.get(s, 99))

    stable = _kahn_order(base, edges, tie_base)
    if stable is None and declarations:
        # A declaring champion's cycle is a disagreement between a module
        # and the interpreter that a human must settle — falling back
        # would serve an order no rule derived (D-85 gates the raise on
        # the declaration, so the 170 non-declaring champions keep the
        # silent fallback below).
        raise ResolvedCycleError(
            f"{champion_name}: the declared and inferred edges form a cycle "
            "in this parse — "
            + "; ".join(f"{e.setup}->{e.consume} ({e.origin} {e.kind})" for e in edges)
            + ". A declaration and the detector disagree about the kit's "
            "order; settle it in the module rather than falling back."
        )
    if stable is None:
        # cycle in the detected edges — fall back to the certified order and
        # flag the ambiguity for the verification swarm.
        rationale = (
            f"{champion_name}'s detected setup/consume edges form a cycle "
            "(conflicting atoms) — the certified module order "
            + (" ".join(certified_order) if certified_order else "Q → Q2 → W → E → R")
            + " is kept; the ambiguous atoms are listed for the F4 swarm."
        )
        sources = tuple(e.sentence() for e in edges) + tuple(option_receipts)
        rule = ComboRule(
            champion=champion_name,
            order=tuple(base),
            rationale=rationale,
            sources=sources,
            setup=tuple(sorted({e.setup for e in edges})),
            consume=tuple(sorted({e.consume for e in edges})),
            aoe=aoe,
            derived=True,
        )
        return remember(rule)

    fight_dps = rank_ability_dps(ability_damages, target_count=1, aoe=aoe)
    dps_idx = {s: i for i, (s, *_) in enumerate(fight_dps)}

    def tie_by(idx: Mapping[str, int]) -> Callable[[str], tuple[Any, ...]]:
        """Rank a slot by its row in *idx*, then outgoing edges, then base order."""
        return lambda s: (
            idx.get(s, 10**9),
            0 if outgoing.get(s) else 1,
            base_idx.get(s, 99),
        )

    fight_order = _kahn_order(base, edges, tie_by(dps_idx))
    use_dps_order = fight_order is not None
    if fight_order is not None:
        for point_rows in _matrix_dps_rows(champion_name, champion_data, aoe):
            idx = {s: i for i, (s, *_) in enumerate(point_rows)}
            if _kahn_order(base, edges, tie_by(idx)) != fight_order:
                use_dps_order = False
                break

    order = fight_order if use_dps_order else stable

    setup = tuple(sorted({e.setup for e in edges}))
    consume = tuple(sorted({e.consume for e in edges}))
    source_lines = [e.sentence() for e in edges] + list(option_receipts)
    if use_dps_order:
        source_lines.append(
            "free slots ranked by per-rank DPS (total_raw / effective cooldown) — "
            "consistent across the L1/L18 x no-items/magic/physical/spellblade matrix"
        )
    else:
        source_lines.append(
            "DPS ranking is build-sensitive across the reference matrix — free slots "
            "keep their certified/base relative order (deterministic)"
        )
    rationale_lines = [e.sentence() for e in edges]
    if use_dps_order:
        rationale_lines.append(
            "Remaining abilities are ranked by per-rank DPS at the fight's stats "
            "(total_raw / effective cooldown, AoE-weighted) — the ranking is "
            "consistent across the level/build reference matrix."
        )
    else:
        rationale_lines.append(
            "The DPS ranking between the unconstrained abilities is build-sensitive "
            "across the reference matrix, so they keep their certified/base relative "
            "order — the derivation is deterministic across levels and items."
        )
    rationale_lines.append(f"Derived order: {' → '.join(order)}.")
    rule = ComboRule(
        champion=champion_name,
        order=tuple(order),
        rationale=" ".join(rationale_lines),
        sources=tuple(source_lines),
        setup=setup,
        consume=consume,
        aoe=aoe,
        derived=True,
    )
    return remember(rule)
