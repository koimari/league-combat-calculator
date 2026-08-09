"""The survival kernel — one typed state-transition engine (issue #137).

Package layout (top-level flow: compile -> transition -> accumulate):

* :mod:`actions` — typed :class:`SurvivalAction`/:class:`ActionKind`
  interface plus the shared ordering helpers;
* :mod:`transitions` — the single kernel: :func:`apply_transition` per
  kind, the shared :func:`run_survival_walk` loop, and the embedded
  transitions (reactive shields, Maw omnivamp, Defy).  Shield and health
  absorption itself belongs to :mod:`calculator.shield_ledger`, which the
  one-pair engine drives too (issue #159);
* :mod:`receipt_state` — the annotating ledger adapter (public timeline);
* :mod:`score_state` — the parallel-array ledger adapter (optimizer);
* :mod:`compile` — the packet compiler with fail-closed capability
  receipts (:class:`UncompilableActionError`);
* :mod:`accumulate` — per-attacker float-sum order, rounded death-time
  cutoff, breakdown rows.
"""

from .actions import (
    ActionKind,
    SurvivalAction,
    TransitionRank,
    action_key,
    classify_event_kind,
    event_sequence,
    legacy_phase,
    participant_order,
    survival_action_from_event,
)
from .compile import (
    COMPILED_WALK_UNREPRESENTABLE_ITEMS,
    UncompilableActionError,
    WalkCompiler,
    champion_wound_tuple,
    coalesce_darius_q_heals,
    heal_trigger_key,
    revive_candidate_actions,
    thorns_return_damage,
    uncompilable_item_receipt,
    unrepresentable_damage_receipt,
    unrepresentable_heal_receipt,
    unrepresentable_template_receipt,
)
from .receipt_state import (
    ReceiptLedger,
    assemble_survival_rows,
    build_state,
    build_states,
)
from .accumulate import accumulate_damage_totals, accumulate_support_values
from .score_state import ScoreLedger
from .transitions import (
    TransitionContext,
    apply_transition,
    evaluate_live_raw_formula,
    expire_temporary_health,
    finalize_states,
    participant_pools,
    resolve_grievous,
    run_survival_walk,
)

__all__ = [
    "ActionKind",
    "COMPILED_WALK_UNREPRESENTABLE_ITEMS",
    "ReceiptLedger",
    "ScoreLedger",
    "SurvivalAction",
    "TransitionContext",
    "TransitionRank",
    "UncompilableActionError",
    "WalkCompiler",
    "accumulate_damage_totals",
    "accumulate_support_values",
    "action_key",
    "apply_transition",
    "assemble_survival_rows",
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
    "legacy_phase",
    "participant_pools",
    "participant_order",
    "resolve_grievous",
    "run_survival_walk",
    "survival_action_from_event",
    "thorns_return_damage",
    "uncompilable_item_receipt",
    "unrepresentable_damage_receipt",
    "unrepresentable_heal_receipt",
    "unrepresentable_template_receipt",
]
