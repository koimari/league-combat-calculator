"""Optimal event-order engine (F3) — algorithmic per-champion combo layer.

Derives the fight's ``cast_order`` from the atomized ability data for ALL
champions, replacing the naive ``DEFAULT_CAST_ORDER`` whenever the data
supports a setup/consume structure.  The hand-verified seeds in
:data:`CAST_ORDER_OVERRIDES` remain as documented OVERRIDES; every other champion
is derived on the fly by :func:`derive_champion_rule` — no combo database.

Scoring model (see ``docs/rotation-design.md`` for the full write-up)
----------------------------------------------------------------------
Above every signal below sits the **declared** one: a champion module
may state what its own kit requires in ``CAST_DEPENDENCIES``, and
:func:`merge_declared_edges` folds those declarations over the inferred
edges under the precedence table written at that function.  The two
vocabularies are closed and disjoint — ``cast_dependency.DEPENDENCY_KINDS``
is what a module may assert, ``INFERRED_EDGE_KINDS`` what this module may
conclude — and every merged edge carries the ``origin`` that says which
surface produced it.  :func:`resolved_edges` is the one detect-then-merge
surface production and the suites both read.

The order of damaging abilities is then ranked by four signals, in
decreasing weight:

1. **Setup/consume relationships** (the strongest inferred signal): an ability
   that applies a debuff/mark/poison/stun/shred/buff must cast BEFORE the
   abilities that consume it.  Detected from TYPED atoms only — the
   parsed keys (``dot_duration``, ``on_hit``, ``applies_dot_stack``,
   ``stacking_dot``, ``post_hit_proc``, ``target_debuff``, ``stat_buff``,
   ``cc_kind`` on parts, ``recast_of``), the module OPTION keys
   (``target_poisoned``, ``blight_stacks``, ``p_illumination_procs``,
   ``r_hemoplague_debuff``, ...), and the structured wiki attribute rows
   ("Enhanced Damage", "Bonus Damage Per Stack", "Missing Health
   Damage").  Free-form ability prose is never scanned; the only phrases
   used are the wiki's anchored application rows ("applies a stack of
   X", "become Chilled", "consumes the mark").
2. **DPS contribution per rank at the fight's stats** — ``total_raw``
   divided by the effective per-rank cooldown from the atomized ability
   rows (see :func:`rank_ability_dps`), weighted by the number of enemy
   champions an AoE slot can hit.  A DPS promotion only applies when it
   is CONSISTENT across a level/build reference matrix (L1/L18 x
   no-items/magic/physical/spellblade); otherwise the certified/base
   relative order is kept (deterministic across builds by construction).
3. **Cooldown gating** — the fight engine schedules recasts on one
   shared timeline, so the derived order doubles as the tie-break: a
   low-cooldown spam tool placed right after its setup ability starts
   its cadence earliest and maximizes casts in the window
   (``_schedule_shared_casts``).
4. **Buffs before damage** — ``stat_buff`` rows that amplify ability
   damage (bonus AD / AP / penetration) and damage-taken amplifiers must
   resolve before the abilities they amplify; resistance-shred
   ``target_debuff`` rows open the burst.

Fallback: a champion with NO detectable setup/consume signal keeps the
certified module ``CAST_ORDER`` (when present) or the engine's historical
``DEFAULT_CAST_ORDER``, with a rationale that says exactly that — the
"flat kit" classification is itself data-driven and honest.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .cast_order_overrides import (
    _DEFAULT_RATIONALE,
    CAST_ORDER_OVERRIDES,
    ComboRule,
    _validate_override_reasons,
)
from .champion_rotation_rule import derive_champion_rule
from .champions import get_champion_cast_order
from .fight.cast_slots import DEFAULT_CAST_ORDER

# ─────────────────────────────────────────────────────────────────────
# Hand-held cast-order overrides
#
# Each entry is the curated output of the four-signal scoring above.
# ``sources`` names the atom/attribute that drives the ordering so a
# patch-day audit can re-verify the rule against the cached data, and
# ``override_reason`` says why the order is still held by hand rather
# than derived — the frontier this phase drives down, counted by the
# audit instead of claimed in prose (P5-f).
# ─────────────────────────────────────────────────────────────────────


_validate_override_reasons()


# ─────────────────────────────────────────────────────────────────────
# F3 — algorithmic derivation from the atomized ability data
#
# The derivation consumes THREE typed atom surfaces and nothing else:
#
#  1. the parsed ability package (``ability_damages``) — ``dot_duration``,
#     ``on_hit``, ``applies_dot_stack``, ``stacking_dot``,
#     ``post_hit_proc``, ``target_debuff``, ``stat_buff``, ``cc_kind`` on
#     ``parts``, ``recast_of``, ``total_raw``, ``cooldown``;
#  2. the module OPTION rotation declarations
#     (``get_champion_option_rotation``) — the typed setup/consume/execute
#     atoms authored by the champion modules (``target_poisoned``,
#     ``blight_stacks``, ``rend_stacks``, ``p_illumination_procs``,
#     ``moonlight_reset``, execute options, ...), with self_state and
#     irrelevant options acknowledged in the receipt without inventing
#     edges;
#  3. the structured wiki attribute rows in ``data/champions.json``
#     ("Enhanced Damage", "Bonus Damage Per Stack", "Detonation Magic
#     Damage", "Missing Health Damage", "Mark Magic Damage", "Stored
#     Damage").  The only anchored phrases used are the wiki's stable
#     application rows ("applies a stack of X", "become Chilled",
#     "consumes the mark", "takes X% increased damage") — free-form ability
#     prose is never scanned.
# ─────────────────────────────────────────────────────────────────────

# ── typed rotation semantics for option keys ──
# The module OPTIONS declarations (via ``get_champion_option_rotation``)
# are the single authoritative vocabulary: roles setup/consume/execute feed
# ``slot_options`` and edge detection, self_state/irrelevant options are
# acknowledged in the receipt without inventing edges, and an unclassified
# option fails the exhaustiveness contract.  There is deliberately no
# hand-maintained second table in this module.


# ─────────────────────────────────────────────────────────────────────
# Raw-row corpus (structured fields only: name, attributes, blurb, notes)
# ─────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────
# Edge detection
# ─────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────
# Declared-vs-inferred merge
#
# Two surfaces make ordering claims: a champion module DECLARES what its
# own kit requires, and the detector above INFERS ordering from the
# markers it parses.  This is where the two meet, under Phase 5's
# precedence table:
#
#   declared A→B  inferred A→B  inferred B→A  suppression B→A  outcome
#   ───────────────────────────────────────────────────────────────────
#        –             ✓             –              –          inferred A→B
#        ✓             –             –              –          declared A→B
#        ✓             ✓             –              –          declared, deduped,
#                                                              confirmed_by_inference
#        ✓             –             ✓              ✓          declared; B→A dropped
#        ✓             –             ✓              ✗          ConflictingInferenceError
#        ✓             –             –        ✓ matching       declared; suppression
#                                               nothing        latent (reason required)
#
# A champion that declares nothing takes the first row for every edge and
# reaches none of this code (D-85) — which is what makes the migration
# provably diff-free for the 170 non-declaring modules.
# ─────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────
# AoE classification + DPS ranking
# ─────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────
# Order construction: constraints + matrix-consistent DPS tie-break
# ─────────────────────────────────────────────────────────────────────


# Both rotation memos hold values derived from data/, so both key on
# data_registry.data_version() (D-49): a patch-day refresh bumps the
# counter and the next read misses, instead of serving a cast order
# derived from the numbers the refresh just replaced.


def resolve_cast_order(
    champion_name: str,
    ability_damages: Mapping[str, Any],
    *,
    champion_data: Mapping[str, Any] | None = None,
    certified_order: list[str] | None = None,
    champion_options: Mapping[str, Any] | None = None,
) -> tuple[list[str], ComboRule | None]:
    """Resolve the fight's ``cast_order``: override, then algorithmic derive.

    The hand-verified :data:`CAST_ORDER_OVERRIDES` seeds win.  Every other
    champion with atomized data is derived by :func:`derive_champion_rule`; one
    with no detectable setup/consume signal keeps its certified module order or
    the engine default with an honest data-driven rationale.  Unknown names
    (synthetic fixtures with no cached data) return ``None`` for the rule,
    preserving the F2 fallback contract.

    *ability_damages* is the parsed ability package, atoms plus per-rank
    ``total_raw`` and ``cooldown`` at the fight's stats, already baked with the
    fight's options.  *champion_options* become part of the derivation cache
    signature, so option-gated slots and option-sensitive edges derive per
    option state.
    """
    rule = CAST_ORDER_OVERRIDES.get(champion_name)
    if rule is not None:
        return list(rule.order), rule
    if champion_data is None and not ability_damages:
        return list(DEFAULT_CAST_ORDER), None
    if certified_order is None:

        certified_order = get_champion_cast_order(champion_name)
    derived = derive_champion_rule(
        champion_name,
        ability_damages,
        champion_data or {},
        certified_order,
        champion_options=champion_options,
    )
    return list(derived.order), derived


def build_rotation_receipt(
    *,
    cast_order: list[str],
    cast_timeline: Iterable[Mapping[str, Any]],
    rule: ComboRule | None,
    certified_order: list[str] | None = None,
    user_order: list[str] | None = None,
) -> dict[str, Any]:
    """Build the public ``rotation`` receipt for ``/api/calculate``.

    The receipt's ``order`` is the fight's actual cast sequence from the
    engine's cooldown-aware ``cast_timeline`` (one-rotation: the derived
    permutation, once per slot; timed mode: every recast at its cooldown,
    e.g. Cassiopeia Q, E, E, E, Q, E, ...).  ``rationale`` is the combo
    rule's plain-language explanation so the UI can show WHY the order is
    optimal; champions with no combo signal get a documented fallback
    rationale.

    Returns:
        ``{"order", "rationale", "cast_order", "sources", "setup",
        "consume", "aoe"}`` (JSON-safe; ``aoe`` maps each AoE slot to the
        maximum enemy champions it can hit).
    """
    order: list[str] = []
    for event in cast_timeline:
        if not isinstance(event, Mapping):
            continue
        slot = str(event.get("slot", ""))
        if not slot:
            continue
        order.append(slot)
    if not order:
        order = [str(slot) for slot in cast_order]

    setup: list[Any] = []
    consume: list[Any] = []
    aoe: dict[str, Any] = {}
    if user_order is not None:
        sequence = ", ".join(user_order)
        rationale = (
            f"Custom order supplied by the request — '{sequence}' is cast "
            "exactly as given; the combo layer defers to explicit input."
        )
        sources = ["request-supplied cast_order"]
    elif rule is not None:
        rationale = rule.rationale
        sources = list(rule.sources)
        setup = list(rule.setup)
        consume = list(rule.consume)
        aoe = dict(rule.aoe)
    elif certified_order is not None:
        sequence = ", ".join(certified_order)
        rationale = (
            f"Certified module rotation — '{sequence}' is the champion "
            "module's reviewed order (setup before damage, e.g. Jayce "
            "transforms before casting)."
        )
        sources = ["champion module CAST_ORDER (certified)"]
    else:
        rationale = _DEFAULT_RATIONALE
        sources = []

    return {
        "order": order,
        "rationale": rationale,
        "cast_order": list(cast_order),
        "sources": sources,
        "setup": setup,
        "consume": consume,
        "aoe": aoe,
    }
