"""When a transition resolves, and what the public timeline calls that phase."""

from __future__ import annotations

from enum import IntEnum


class TransitionRank(IntEnum):
    """When a transition resolves, relative to everything at its timestamp.

    Dense ordinals in ordering order: a lower rank resolves first.  This is
    the campaign's single phase vocabulary, and since Phase 4 S2 it is also
    the only one: the float projection that stood between these names and
    the walk is deleted, so a ``phase`` is a member of this enum everywhere
    one is written, sorted, compared or dispatched on.

    ``TERMINAL`` has no producer.  It exists so the published phase list
    keeps ``death_or_terminal_cutoff`` (a name the ledger publishes but no
    transition emits) and is declared last because it resolves after
    everything else at its timestamp.

    ``AURA_ARM`` is the one rank no producer wrote before C4.  A persistent
    aura is *already in force* when the fight opens — Abyssal Mask's Unmake
    curses every enemy in range from the first frame — so it must resolve
    before the damage at its own timestamp, not after it like a debuff some
    trigger armed.  ``DEBUFF_ARM`` put it after, which made the opening
    exchange the one exchange the aura did not price.

    **One group still resolves as one.**  ``LATE_BARRIER``/``REACTIVE`` rode
    one float before S2 and ride one :func:`ordering_slot` after it, so
    their relative declaration order still changes nothing.

    ``DEBUFF_ARM``/``RECOVERY``/``UTILITY_ARM`` rode the other float and no
    longer share anything: Phase 4 S6 split them, so ``6 < 7 < 8`` is now
    the live tie-break between two transitions authored at one timestamp —
    a debuff arms before a heal lands, and both before a utility effect
    resolves.  That is the ordering the collapsed float could not express
    and could not be asked about; if it is wrong, it is wrong here and not
    at the call sites.
    """

    STATE_GRANT = 0
    BARRIER_GRANT = 1
    AURA_ARM = 2
    DAMAGE = 3
    LATE_BARRIER = 4
    REACTIVE = 5
    DEBUFF_ARM = 6
    RECOVERY = 7
    UTILITY_ARM = 8
    TERMINAL = 9


# ``REACTIVE`` folds onto ``LATE_BARRIER`` wherever the walk *orders* by
# rank, so the two resolve as one.  ``LATE_BARRIER`` is a barrier an
# authored packet places *after* damage (Eclipse's self-shield,
# Fimbulwinter's Everlasting), which is why it is not ``BARRIER_GRANT``.
#
# The fold is a preserved defect and is named as one: a barrier resolving
# after the damage at its own timestamp absorbs nothing at that timestamp.
# The row lives on ``docs/migration-frontier.json`` under
# ``preserved_defects``, because correcting it reorders the walk and owes
# its own measurement.
#
# Which ranks the receipt adapter classifies as a recovery is spelled as
# itself, in ``_RECOVERY_CLASSIFIED_RANKS`` below, rather than as this
# fold's output.  Every other read of a rank is fold-invariant by
# construction: the kernel's comparisons are thresholds at a group
# boundary, and the surviving pair does not straddle one.
_ORDERING_SLOTS: dict[TransitionRank, TransitionRank] = {
    TransitionRank.REACTIVE: TransitionRank.LATE_BARRIER,
}


def ordering_slot(rank: TransitionRank) -> TransitionRank:
    """The rank a transition sorts *as*; identity for a rank that sorts alone."""
    return _ORDERING_SLOTS.get(rank, rank)


# The published phase a rank belongs to.  Many-to-one for a different reason
# than ``ordering_slot``: the public contract names the *kind* of transition,
# so a late barrier is still a barrier, and arming a debuff or a utility
# effect is still a state transition.
#
# ``AURA_ARM`` is the one arming rank that does *not* fold into
# ``state_transition``, and the reason is the list's own ordering.  The
# published list is the ledger's phases in ledger order, keeping each name's
# first appearance; ``state_transition`` already appears first, at
# ``STATE_GRANT``.  Folding the aura slot into it would publish nothing for
# the one phase that resolves between the barriers and the damage — a phase
# the ledger has and the contract does not name, which is this campaign's
# own failure shape in the public schema.  It is a seventh published name
# and ``CAPABILITY_SCHEMA_VERSION`` moves with it (D-63).
_PUBLIC_PHASES: dict[TransitionRank, str] = {
    TransitionRank.STATE_GRANT: "state_transition",
    TransitionRank.BARRIER_GRANT: "shield_or_temporary_health",
    TransitionRank.AURA_ARM: "persistent_aura_arming",
    TransitionRank.DAMAGE: "damage_and_mitigation",
    TransitionRank.LATE_BARRIER: "shield_or_temporary_health",
    TransitionRank.REACTIVE: "reactive_effect",
    TransitionRank.DEBUFF_ARM: "state_transition",
    TransitionRank.RECOVERY: "healing_and_regeneration",
    TransitionRank.UTILITY_ARM: "state_transition",
    TransitionRank.TERMINAL: "death_or_terminal_cutoff",
}


def public_phase(rank: TransitionRank) -> str:
    """The published phase name one rank belongs to.

    ``capabilities`` derives ``PARTICIPANT_LEDGER_CONTRACT["phases"]`` from this
    by walking the enum in declaration order and keeping each name's first
    appearance, rather than from six hand-written strings.
    """
    try:
        return _PUBLIC_PHASES[rank]
    except KeyError:
        raise KeyError(
            f"TransitionRank.{rank.name} declares no published phase"
        ) from None
