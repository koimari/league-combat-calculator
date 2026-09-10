"""The five projections of one walk (Phase 4).

A view answers one consumer's shape and re-runs no arithmetic: every number
it emits is already a leaf of the walk's result, and every digit count it
publishes comes from :mod:`program.precision`.  That is what makes "score
mode and receipt mode agree" a property of the layering instead of a claim
two code paths have to keep true.

The package exports nothing.  Each view, the tag a number carries
(:mod:`view_tag`), the disposition readers (:mod:`dispositions`) and the
leaf writers (:mod:`leaf`) are imported by their own dotted path, so a
reader -- and the derived front-door registry -- can see which module
answers which consumer.
"""

from __future__ import annotations

__all__ = []
