"""The logical layer of the coupled simulation (Phase 4).

``program/`` answers "what happened, and to whom"; ``survival/`` answers
"what that does to state".  The dependency runs one way, ``program ->
survival``, and never back: the kernel's hot loop must never dispatch on a
logical type, which is why the narrowing aliases this package declares
(``PIdx``, ``MechanicId``, ``EventId``) stay on this side of the boundary
and the kernel sees plain ints.

The package deliberately re-exports nothing.  Each module is imported by its
own dotted path so that a reader -- and the derived front-door registry --
can see which module holds which concept.
"""
