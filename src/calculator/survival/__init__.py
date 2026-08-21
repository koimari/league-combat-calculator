"""The survival kernel: one typed state-transition engine.

Package layout (top-level flow: compile -> transition -> accumulate):

* :mod:`actions` — typed :class:`SurvivalAction`/:class:`ActionKind`
  interface plus the shared ordering helpers;
* :mod:`transitions` — the single kernel: the :func:`run_survival_walk`
  loop with the one dispatch ladder per kind, and the embedded
  transitions (reactive shields, Maw omnivamp, Defy).  Shield and health
  absorption itself belongs to :mod:`calculator.shield_ledger`, which the
  one-pair engine drives too;
* :mod:`receipt_state` — the annotating ledger adapter (public timeline);
* :mod:`score_state` — the parallel-array ledger adapter (optimizer);
* :mod:`compile` — the packet compiler with fail-closed capability
  receipts (:class:`UncompilableActionError`);
* :mod:`pricing` — raw declared damage becoming a mitigated number: the
  one arithmetic home a family's declaration reaches the walk through;
* :mod:`accumulate` — per-attacker float-sum order, rounded death-time
  cutoff, breakdown rows.

``__all__`` is the package's declared API, so growing it is an API change.
It carries the transition vocabulary the item layer and the public schema
author against instead of writing floats, and ``EVENT_SLOTS``, because the
four reference fields are integer slots and a composition that authors packets
outside this package has to resolve an id string to the same slot the kernel
compares.  ``actions.ordering_slot``, the fold two groups of ranks share,
stays kernel-internal: no packet author outside this package orders anything.

``program -> survival`` runs one way, so the kernel never re-exports the
logical layer.  ``WalkCompiler``, ``revive_candidate_actions`` and
``action_from_event`` live in ``calculator.program.compile`` and are imported
from there.  ``trigger_time_key`` and ``TRIGGER_TIME_KEY_DIGITS`` sit on this
side of that boundary, because ``heal_trigger_key`` is their reader and cannot
import the registry that would otherwise own them.
"""

from .actions import (
    BARRIER_GRANT_KINDS,
    EVENT_SLOTS,
    SUPPORT_RANK_KEY,
    ActionKind,
    SurvivalAction,
    TransitionRank,
    action_key,
    classify_event_kind,
    event_sequence,
    participant_order,
    public_phase,
    support_transition_rank,
)
from .compile import (
    TRIGGER_TIME_KEY_DIGITS,
    UncompilableActionError,
    champion_wound_tuple,
    coalesce_darius_q_heals,
    heal_trigger_key,
    thorns_return_damage,
    trigger_time_key,
    unrepresentable_damage_receipt,
    unrepresentable_heal_receipt,
    unrepresentable_modifier_receipt,
    unrepresentable_template_receipt,
)
from .receipt_state import (
    ReceiptLedger,
    build_state,
    build_states,
)
from .accumulate import accumulate_damage_totals, accumulate_support_values
from .score_state import ScoreLedger
from .transitions import (
    RegenerationWindow,
    TransitionContext,
    evaluate_live_raw_formula,
    expire_temporary_health,
    finalize_states,
    participant_pools,
    resolve_grievous,
    run_survival_walk,
)

__all__ = [
    "ActionKind",
    "BARRIER_GRANT_KINDS",
    "EVENT_SLOTS",
    "SUPPORT_RANK_KEY",
    "TRIGGER_TIME_KEY_DIGITS",
    "ReceiptLedger",
    "ScoreLedger",
    "SurvivalAction",
    "RegenerationWindow",
    "TransitionContext",
    "TransitionRank",
    "UncompilableActionError",
    "accumulate_damage_totals",
    "accumulate_support_values",
    "action_key",
    "build_state",
    "build_states",
    "champion_wound_tuple",
    "classify_event_kind",
    "coalesce_darius_q_heals",
    "evaluate_live_raw_formula",
    "event_sequence",
    "expire_temporary_health",
    "finalize_states",
    "heal_trigger_key",
    "participant_pools",
    "participant_order",
    "public_phase",
    "resolve_grievous",
    "run_survival_walk",
    "support_transition_rank",
    "thorns_return_damage",
    "trigger_time_key",
    "unrepresentable_damage_receipt",
    "unrepresentable_heal_receipt",
    "unrepresentable_modifier_receipt",
    "unrepresentable_template_receipt",
]
