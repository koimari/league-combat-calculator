"""The five projections of one walk (Phase 4).

A view answers one consumer's shape and re-runs no arithmetic: every number
it emits is already a leaf of the walk's result, and every digit count it
publishes comes from :mod:`program.precision`.  That is what makes "score
mode and receipt mode agree" a property of the layering instead of a claim
two code paths have to keep true.

The package re-exports no view.  Each view is imported by its own dotted
path so a reader -- and the derived front-door registry -- can see which
module answers which consumer.

What it does export is :class:`ViewTag`, because a tag is a property of the
*view* a number was produced for and the five views are what this package
is -- and, from S9, :func:`serialize_leaf` and :class:`LeafWriter`, because
every leaf the five views publish is born here or nowhere.

`serialize_leaf` is **the only producer of a payload leaf and of that leaf's
``dispositions`` entry** (D-72).  A bare JSON number cannot carry a field, so
the wire shape is a sibling map keyed by leaf path; the reason that map
cannot drift from the leaves is not a test but the fact that one function
emits both in one call.  The payload-schema test's two-way key-set equality
is a backstop behind that single writer, not the mechanism.

The one import this module takes is ``ability_spec`` -- the campaign's
dependency-free vocabulary leaf, which the declaring reader
(``trigger_stream``) already imports for ``Authority``.  It is the single
permitted reach and the views' own test pins it as such: the acyclicity
argument that keeps ``ViewTag`` declarable here is an argument about modules
that reach *further*, and a module that imports nothing cannot.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from enum import Enum

from ...ability_spec import Disposition, Measured, Quantity, StructuralZero, Withheld

__all__ = [
    "DISCARD",
    "LeafBlock",
    "LeafOut",
    "LeafWriter",
    "serialize_leaf",
    "ViewTag",
]


class ViewTag(Enum):
    """Whether a serialized number was *delivered* or merely *previewed*.

    Two members, and "requested" is deliberately not a third.  The ladder is
    requested -> priced -> applied: a request is a program node carrying no
    number and therefore nothing to tag, ``THEORETICAL`` is the pair
    engine's pre-coupling authoring of a number that one attacker-versus-one
    -defender fight would have produced, and ``APPLIED`` is what the coupled
    walk actually delivered against the roster.  Tagging a non-number would
    re-open the zero-versus-absent confusion this campaign exists to close.

    The distinction is load-bearing rather than descriptive.  Imperial
    Mandate's Command is priced twice today -- once pair-side as a preview
    and once by the walk -- and summing the two is a double count with no
    symptom.  So a sum may never mix tags, ``THEORETICAL`` is never an
    optimizer objective and never feeds BIS, and at most one ``APPLIED``
    contribution may exist for one ``(mechanic, subject, event_id)`` across
    every producer (D-62).
    """

    THEORETICAL = "theoretical"
    APPLIED = "applied"


@dataclass(frozen=True, slots=True)
class LeafOut:
    """One serialized leaf, beside the ``dispositions`` entry that names it.

    ``present`` is the whole point of the record.  A ``MEASURED`` or
    ``STRUCTURAL_ZERO`` leaf is a bare number in the payload and its entry
    says which of the two it is; a ``WITHHELD`` leaf is **absent** from the
    payload while its entry stays, carrying the receipts.  Returning a value
    of ``None`` for the withheld case and leaving the caller to decide would
    have made a serialized ``null`` one typo away, which is the blank this
    campaign exists to stop shipping.
    """

    path: str
    value: float | None
    entry: dict[str, object]
    present: bool


def serialize_leaf(path: str, quantity: Quantity, tag: ViewTag) -> LeafOut:
    """The only producer of a payload leaf **and** of its dispositions entry.

    One call emits both, which is what makes the parallel map structurally
    unable to drift from the leaves it describes: there is one writer, so
    there is nothing to keep in step.

    The four dispositions serialize as three shapes, because they answer three
    different questions:

    * ``MEASURED`` -- the number, and an entry saying a rule produced it.
    * ``STRUCTURAL_ZERO`` -- ``0.0``, and an entry carrying the declaration
      that makes zero the answer.  The reason is the receipt, so it is
      published rather than folded away into a bare zero.
    * ``WITHHELD`` -- **no number at all**, and an entry carrying every
      receipt.  ``present`` is False and the payload key is never written.
    * ``STARVED`` -- never reaches an entry: reading the quantity raises
      ``ProjectionStarvation`` here, at the moment the projection was asked
      for a number it cannot represent, and D-25's single handler at the
      request boundary turns it into a named 500.
    """
    entry: dict[str, object] = {
        "disposition": quantity.disposition.value,
        "view_tag": tag.value,
    }
    if isinstance(quantity, Withheld):
        entry["receipts"] = list(quantity.receipts)
        return LeafOut(path=path, value=None, entry=entry, present=False)
    if isinstance(quantity, StructuralZero):
        entry["reason"] = quantity.reason
    # Reading is what raises for a Starved quantity, so it happens before the
    # entry is handed back rather than after: an entry for a leaf whose value
    # blew up would be a receipt for a number nobody has.
    return LeafOut(path=path, value=quantity.read(), entry=entry, present=True)


class LeafBlock:
    """One payload sub-object, and the leaf paths its keys live at.

    A block binds a target mapping to a path prefix, which is what makes the
    ``dispositions`` key and the payload key the *same* name by construction:
    a leaf written as ``row["total_damage"]`` under prefix
    ``breakdown.main`` can only be described at ``breakdown.main.
    total_damage``.  Passing the path separately would have let a rename move
    one and not the other -- the map describing a leaf that is no longer
    there, which is the drift the single writer exists to make impossible.
    """

    __slots__ = ("_dot", "_prefix", "_records", "_set", "_tag", "_target", "_writer")

    def __init__(
        self,
        writer: "LeafWriter",
        target: MutableMapping[str, object],
        prefix: str,
        tag: ViewTag,
    ) -> None:
        """Bind one target mapping to the path prefix its keys hang under.

        An empty prefix is the payload's own root, and its keys are paths
        with no dot in front of them -- ``duration``, not ``.duration``.  A
        root block exists because a top-level number is a published number:
        the payload's own leaves were the ones no block owned, and a leaf no
        block owns is a leaf with no entry.

        ``_records``, ``_set`` and ``_dot`` are bound once because the
        optimizer walks every participant of every candidate through here:
        two attribute chases per leaf, times a few hundred leaves, times a
        thousand evaluations, is measurable against the phase's wall ratchet.
        """
        self._writer = writer
        self._target = target
        self._prefix = prefix
        self._dot = f"{prefix}." if prefix else ""
        self._tag = tag
        self._records = writer.records
        self._set = target.__setitem__

    def put(self, key: str, quantity: Quantity) -> None:
        """Serialize one leaf into the block and record its entry.

        A withheld quantity writes no key at all.  The entry lands either way,
        which is the asymmetry that lets a consumer tell "refused, and here is
        why" from "this payload has no such field".

        The tag is the block's.  It used to default to ``APPLIED`` on every
        write, which made "every serialized field carries exactly one
        ``ViewTag``" true of a constant rather than of anything anybody
        declared -- a map recording what the writer's signature said instead
        of what the view meant.  A block is the unit a projection lane
        applies to, so the tag is stated once, where the block is opened, and
        no leaf can acquire one by omission.
        """
        out = serialize_leaf(f"{self._dot}{key}", quantity, self._tag)
        # pylint: disable-next=protected-access
        self._writer._record(out)
        if out.present:
            self._target[key] = out.value

    def nested(self, target: MutableMapping[str, object], key: str) -> "LeafBlock":
        """A block for a sub-object of this one, at ``prefix.key``.

        The path grows with the payload rather than being respelled, so a
        nested leaf's map key is still the path a reader would walk to reach
        it.
        """
        return LeafBlock(self._writer, target, f"{self._dot}{key}", self._tag)

    def structure(self, key: str, value: object) -> None:
        """Publish a nested object or list, naming every quantity inside it.

        A receipt sub-object -- an armed multiplier, a resistance-reduction
        list, a per-source damage row -- holds real numbers, and a number
        inside a nested block is no less a published leaf than one at the top.
        Walking it here is what keeps "every published quantity is named" true
        of the shapes a payload nests rather than only of the ones it
        flattens; every float found is written through the same
        :func:`serialize_leaf`, at the path a reader would walk to reach it.
        """
        self._set(key, self._walk(value, f"{self._dot}{key}"))

    def publish(self, key: str, value: object) -> None:
        """One payload member, named by what it *is*.

        A quantity gets a leaf and an entry, a nested shape is walked, and
        anything else is a label.  It exists because a payload assembled
        elsewhere -- a ranked BIS candidate, an optimize response -- is
        published key by key without its assembler having to classify each
        one, which is exactly the classification that gets a key wrong: a
        row written through ``raw`` because nobody noticed it held floats is
        how a hundred numbers reach a consumer with nothing said about them.
        """
        if isinstance(value, (Mapping, list, tuple)):
            self.structure(key, value)
        elif isinstance(value, float) and not isinstance(value, bool):
            self.measured(key, value)
        else:
            self.raw(key, value)

    def _walk(self, value: object, path: str) -> object:
        """One nested value, rebuilt with every float written as a leaf."""
        if isinstance(value, Mapping):
            out: dict[str, object] = {}
            block = LeafBlock(self._writer, out, path, self._tag)
            for key, member in value.items():
                block.publish(key, member)
            return out
        if isinstance(value, (list, tuple)):
            return [
                self._walk(member, f"{path}[{index}]")
                for index, member in enumerate(value)
            ]
        return value

    def raw(self, key: str, value: object) -> None:
        """Publish a non-numeric leaf: a label, a flag, a list, an id.

        No entry, deliberately.  The ``dispositions`` map answers "is this
        number one a rule produced", and a string has no answer to give; an
        entry for one would make the map's own key set stop meaning "the
        payload's numbers".
        """
        self._set(key, value)

    def optional_measured(self, key: str, value: float | None) -> None:
        """A number the walk may not have: published as ``null``, with no entry.

        An actor who did not die has no death time, which is a different
        published answer from dying at t=0 -- and the row's own
        ``survived_window`` is that answer's receipt.  ``null`` is not a
        number, so it carries no disposition and the payload-schema test
        reads it as absent rather than as a leaf missing its entry.
        """
        if value is None:
            self._set(key, None)
            return
        self.measured(key, value)

    def measured(self, key: str, value: float) -> None:
        """``put`` for the overwhelmingly common case: a rule produced this.

        Spelled out rather than defaulted into ``put`` so that wrapping a
        number in ``Measured`` stays a thing a view *says*, and a leaf whose
        disposition is anything else cannot be written by forgetting to.

        The short branch is for a writer that records nothing.  It is not a
        second way of producing the leaf: ``serialize_leaf`` returns
        ``quantity.read()`` and ``Measured.read()`` is ``float(self.amount)``,
        so ``float(value)`` is the *same expression* with the two allocations
        that only the recording path needs taken out.  It exists because the
        optimizer runs this over every participant of every candidate, where
        three objects per leaf breached the phase's allocation ratchet by
        19%, and criterion 17 says that gate is never to be relaxed.  The two
        branches are pinned to produce identical rows by test.
        """
        if not self._records:
            self._set(key, float(value))
            return
        self.put(key, Measured(amount=float(value)))


class LeafWriter:
    """Builds one payload's leaves and its parallel ``dispositions`` map.

    A thin accumulator over :func:`serialize_leaf` rather than a second
    producer: every leaf it writes and every entry it records comes out of one
    ``serialize_leaf`` call, so "one writer" survives having an ergonomic
    front end.  Views use it because the alternative -- each view assembling a
    dict literal and a map separately -- is precisely the two-things-kept-in-
    step-by-hand arrangement the campaign exists to remove.

    Leaves are written through :meth:`block`, which writes into the caller's
    own mapping so the published key order stays the order the view spells;
    that order is part of the serialized shape.
    """

    __slots__ = ("_entries",)

    #: Whether leaves written through this writer are recorded.  False only
    #: for :data:`DISCARD`, and read on the hot path rather than branched on
    #: by type.
    records = True

    def __init__(self) -> None:
        """Start with an empty map; a payload with no leaves has no entries."""
        self._entries: dict[str, dict[str, object]] = {}

    def block(
        self,
        target: MutableMapping[str, object],
        prefix: str,
        tag: ViewTag = ViewTag.APPLIED,
    ) -> LeafBlock:
        """A binder for one sub-object of the payload at ``prefix``.

        ``tag`` is what the numbers in this block *mean*, and it defaults to
        ``APPLIED`` here and nowhere else: the five views project the coupled
        walk, which is what applied means, and a lane whose numbers are a
        pair-engine preview opens its block saying ``THEORETICAL``.  Stating
        it once per block rather than once per leaf is what stops a tag being
        acquired by forgetting to pass one.
        """
        return LeafBlock(self, target, prefix, tag)

    def _record(self, out: LeafOut) -> None:
        """File one serialized leaf's entry; the block writes the value."""
        self._entries[out.path] = out.entry

    def entries(self) -> dict[str, dict[str, object]]:
        """The parallel ``dispositions`` map, keyed by leaf path."""
        return dict(self._entries)

    def paths(self) -> frozenset[str]:
        """Every leaf path this writer has an entry for."""
        return frozenset(self._entries)

    def withheld_paths(self) -> frozenset[str]:
        """The paths whose leaves are absent by refusal rather than by shape."""
        return frozenset(
            path
            for path, entry in self._entries.items()
            if entry["disposition"] == Disposition.WITHHELD.value
        )


class _DiscardingWriter(LeafWriter):
    """The writer for rows nobody serializes.

    The optimizer evaluates thousands of candidates per search and never shows
    one to anybody: its score rows exist to be compared and thrown away.
    Building a ``dispositions`` map for each of them would put a few hundred
    dict entries per evaluation on the hot path, which the phase's allocation
    gate measures and refuses -- and it would be a map describing a payload
    that is never a payload.

    Discarding is a *stated* choice rather than an omission, which is the
    point of it being a named object: a leaf written through this writer is
    still born in :func:`serialize_leaf`, so the rows are identical to the
    published ones, and the only thing that does not happen is the recording.
    """

    __slots__ = ()

    records = False

    def _record(self, out: LeafOut) -> None:
        """Record nothing; the caller has already said nobody will read it."""

    def entries(self) -> dict[str, dict[str, object]]:
        """Always empty -- and a payload that published this would say so."""
        return {}


DISCARD = _DiscardingWriter()
