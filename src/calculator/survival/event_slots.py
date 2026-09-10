"""The kernel's four event references as integers."""

from __future__ import annotations

from threading import Lock

# "This action names no such reference."  The integer spelling of the ``None``
# the four ``str | None`` reference fields carried before Phase 4 S1, and the
# same sentinel ``subject``/``attacker``/``trigger``/``holder`` already use.
NO_SLOT = -1


class EventSlots:
    """The one text-to-integer registry for the walk's event references.

    Four kernel fields carry event references: the packet's own id, its trigger's,
    its deferral batch's and its Defy trigger's.  Every use of them is an identity
    question, is this the packet that trigger applied? is this batch cleared?, and
    a slot answers it with an int compare rather than a string comparison inside
    the hot loop.

    A slot is a dense integer standing for exactly one id string.  The sets and
    dicts the walk keys by a reference become int-keyed, and :meth:`text` gives the
    string back at the one place that still authors a derived id.

    **The registry is process-wide, deliberately.**  Actions outlive the call that
    built them: a pair packet's typed actions ride the packet cache, a signature
    panel's compiled actions ride the search context, and both are replayed inside
    walks built later.  A per-call registry would give two such actions slots from
    two different numberings inside one walk, two different events answering to one
    integer, with no symptom.  One numbering for the process makes that
    unrepresentable.

    Growth is bounded rather than merely slow: every id is assembled from a closed
    vocabulary (roster slots ``main``/``ally:n``/``enemy:n``, mechanic labels, item
    names, source keys) and a small ordinal, so the distinct set converges instead
    of scaling with traffic.  Nothing is ever evicted, because a slot handed to a
    cached action must keep meaning the same event for as long as that action can
    be walked.
    """

    __slots__ = ("_by_text", "_lock", "_texts")

    def __init__(self) -> None:
        self._by_text: dict[str, int] = {}
        self._texts: list[str] = []
        self._lock = Lock()

    def slot(self, text: str) -> int:
        """The slot standing for *text*, assigning one on first sight.

        The hit path takes no lock -- a dict read is atomic and the mapping
        is append-only -- and the miss path re-checks under one, so two
        threads cannot hand two slots to one string.
        """
        known = self._by_text.get(text)
        if known is not None:
            return known
        with self._lock:
            known = self._by_text.get(text)
            if known is None:
                known = len(self._texts)
                self._texts.append(text)
                self._by_text[text] = known
            return known

    def text(self, slot: int) -> str:
        """The id string one slot stands for; ``""`` for :data:`NO_SLOT`."""
        if slot == NO_SLOT:
            return ""
        return self._texts[slot]

    def __len__(self) -> int:
        """How many distinct event ids this process has interned."""
        return len(self._texts)


# The one registry.  A second instance would be a second numbering, which is
# the failure the class docstring exists to prevent, so consumers reference
# this name rather than constructing their own.
EVENT_SLOTS = EventSlots()
