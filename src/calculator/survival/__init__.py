"""The survival kernel: one typed state-transition engine.

Package layout (top-level flow: compile -> transition -> accumulate):

* :mod:`typed_action` — the :class:`SurvivalAction`/:class:`ActionKind`
  interface, its live amplification and its trigger linkage;
* :mod:`actions` — the total order a walk consumes actions in (the shared
  ordering helpers) and the compiled damage row's field indices;
* :mod:`classify` — what an event *is*: its damage and attack class, the
  modifier classes it declares, and its transition rank;
* :mod:`phases` — when a transition resolves, and what the public timeline
  calls that phase;
* :mod:`event_slots` — the kernel's four event references, as integers;
* :mod:`transitions` — the single kernel: the :func:`run_survival_walk`
  loop with the one dispatch ladder per kind, and the embedded
  transitions (reactive shields, Maw omnivamp, Defy).  Shield and health
  absorption itself belongs to :mod:`calculator.shield_ledger`, which the
  one-pair engine drives too;
* :mod:`receipt_state` — the annotating ledger adapter (public timeline),
  over the outcome rows in :mod:`receipt_ledger` and the four interaction
  resolvers read into a participant state in :mod:`defense_contracts`;
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
compares.  ``phases.ordering_slot``, the fold two groups of ranks share,
stays kernel-internal: no packet author outside this package orders anything.

``program -> survival`` runs one way, so the kernel never re-exports the
logical layer.  ``WalkCompiler``, ``revive_candidate_actions`` and
``action_from_event`` live in ``calculator.program.compile`` and are imported
from there.  ``trigger_time_key`` and ``TRIGGER_TIME_KEY_DIGITS`` sit on this
side of that boundary, because ``heal_trigger_key`` is their reader and cannot
import the registry that would otherwise own them.
"""

from .accumulate import accumulate_damage_totals, accumulate_support_values
from .actions import action_key, event_sequence, participant_order
from .classify import (
    BARRIER_GRANT_KINDS,
    SUPPORT_RANK_KEY,
    classify_event_kind,
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
from .event_slots import EVENT_SLOTS
from .phases import TransitionRank, public_phase
from .receipt_ledger import ReceiptLedger
from .receipt_state import build_state, build_states
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
from .typed_action import ActionKind, SurvivalAction

__all__ = [
    "BARRIER_GRANT_KINDS",
    "EVENT_SLOTS",
    "SUPPORT_RANK_KEY",
    "TRIGGER_TIME_KEY_DIGITS",
    "ActionKind",
    "ReceiptLedger",
    "RegenerationWindow",
    "ScoreLedger",
    "SurvivalAction",
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
    "participant_order",
    "participant_pools",
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
