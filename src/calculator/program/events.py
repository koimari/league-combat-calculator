"""The five riders an event may carry, as a closed union.

A rider modifies a damage event without being one: an execute threshold, a
deferral, a redirect, a wound and an amp bonus.  **Riders travel with their
host and die with it.**  That is the whole reason they are their own axis: a
rider on an event the walk never applied is an effect that never happened,
and a spell-shielded hit emits no bonus because the bonus was never an event
of its own.

:data:`RIDER_KINDS` is the vocabulary itself, read off this module rather
than re-listed: ``scripts/receipt_walk_schedule.py`` resolves its named
kernel mechanisms against it, so a rider that leaves the tree stops
resolving on the commit that removes it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .identity import EventId, PIdx


@dataclass(frozen=True, slots=True)
class Execute:
    """This damage kills outright below a health ratio, named by its source."""

    threshold_ratio: float
    source: str


@dataclass(frozen=True, slots=True)
class Defer:
    """This damage lands in a later batch rather than at its own timestamp."""

    batch: EventId


@dataclass(frozen=True, slots=True)
class Redirect:
    """A share of this damage is taken by another participant instead.

    ``holder_health_ratio`` is the gate the sharing holder must clear; the
    walk cancels the child when the holder cannot pay, which is why the
    original amount rides here rather than being recomputed.
    """

    holder: PIdx
    holder_health_ratio: float = 0.0
    original_amount: float = 0.0


@dataclass(frozen=True, slots=True)
class Wound:
    """Grievous Wounds applied by this hit, for a duration, from a source."""

    duration: float
    source: str


@dataclass(frozen=True, slots=True)
class AmpBonus:
    """Extra damage a live predicate adds to *this* hit, read before absorption.

    A rider rather than an event because it must die with its host: a
    spell-shielded, state-blocked or post-death trigger emits no bonus, and
    an independent event would have to be cancelled by hand to achieve that.
    """

    multiplier: float
    mechanic: str


Rider = Execute | Defer | Redirect | Wound | AmpBonus

RIDER_KINDS: tuple[type, ...] = (Execute, Defer, Redirect, Wound, AmpBonus)


__all__ = [
    "RIDER_KINDS",
    "AmpBonus",
    "Defer",
    "Execute",
    "Redirect",
    "Rider",
    "Wound",
]
