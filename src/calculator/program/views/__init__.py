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

from collections.abc import Container, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from enum import Enum

from ...ability_spec import Disposition, Measured, Quantity, StructuralZero, Withheld

__all__ = [
    "DISCARD",
    "LeafBlock",
    "LeafOut",
    "LeafWriter",
    "RankingWriter",
    "UnrankableNumber",
    "name_every_number",
    "published_quantity",
    "published_tag",
    "refuse_previewed",
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


class UnrankableNumber(TypeError):
    """A number the surfaces that pick a winner may not fold into a score.

    D-62's second half — ``THEORETICAL`` is never an optimizer objective and
    never feeds BIS — as a refusal rather than as a review note.  A preview
    is what one attacker-versus-one-defender fight *would* have produced;
    ranking builds by it means ranking by a number no roster delivered, and
    the failure has no symptom because a preview is a perfectly ordinary
    ``MEASURED`` float.

    A ``TypeError`` for two reasons.  :class:`~..build.MixedViewFold`'s: the
    operand is not the right *kind* of number, so its sum is not a wrong
    total but not a total.  And an operational one — ``bis`` wraps each
    candidate in ``except (KeyError, ValueError)`` and turns what it catches
    into a withheld row.  A previewed number is not a bad candidate to drop
    with a receipt; it is the payload meaning something other than what the
    ranking assumed, and being swallowed into ``candidate_loadout_
    unavailable`` would be this rule failing in exactly the shape it exists
    to stop.
    """

    def __init__(self, surface: str, reason: str, paths: Sequence[str]) -> None:
        """Name the surface, what it refused, and the leaves that caused it.

        Assigned, not handed to ``TypeError.__init__``: the audit reads this.
        """
        self.surface = surface
        self.reason = reason
        self.paths = tuple(paths)
        self.args = (f"{surface} may not rank {reason}: {sorted(paths)}",)


def refuse_previewed(
    dispositions: Mapping[str, Mapping[str, object]], *, surface: str
) -> None:
    """Refuse a payload any of whose numbers is a preview, naming them.

    Asks the payload's own map rather than a list of the leaves a scorer
    happens to read, so retagging *any* field ``THEORETICAL`` makes the
    surface fail.  A derived figure is covered too, because the leaves it is
    derived from are in the map.
    """
    previewed = [
        path
        for path, entry in dispositions.items()
        if entry["view_tag"] != ViewTag.APPLIED.value
    ]
    if previewed:
        raise UnrankableNumber(surface, "a previewed number", previewed)


def published_tag(
    dispositions: Mapping[str, Mapping[str, object]], path: str, *, surface: str
) -> "ViewTag":
    """What the payload says the number at *path* means, or a refusal.

    A leaf with no entry is refused rather than assumed applied: a number
    with no published meaning is what a fold may not carry.
    """
    try:
        entry = dispositions[path]
    except (KeyError, TypeError):
        raise UnrankableNumber(surface, "a number no entry names", [path]) from None
    return ViewTag(entry["view_tag"])


def published_quantity(
    dispositions: Mapping[str, Mapping[str, object]],
    path: str,
    value: float,
    *,
    surface: str,
) -> Quantity:
    """The quantity the payload published at *path* — disposition and all.

    The companion of :func:`published_tag`, and the half without which
    :class:`Quantity`'s propagation never reaches a serving surface.  A
    ``WITHHELD`` leaf is **absent** from the payload by ruling, so a consumer
    that reads it as ``payload.get(path, 0.0)`` gets a zero no rule computed
    and folds it into a total that then claims to be measured — the incident,
    at the aggregate, inside the one surface the algebra exists to protect.
    Reading the entry rather than the leaf is what makes the refusal
    propagate.

    ``STRUCTURAL_ZERO`` folds as ``0.0`` and therefore cannot move a number;
    it is reconstructed anyway so the total's disposition is derived from what
    the payload said rather than from what the caller assumed.  ``STARVED``
    never reaches a payload — :func:`serialize_leaf` raises while producing
    it — so an entry claiming it is a malformed payload and is refused here
    rather than reconstructed into a raise somewhere further along.
    """
    try:
        entry = dispositions[path]
    except (KeyError, TypeError):
        raise UnrankableNumber(surface, "a number no entry names", [path]) from None
    disposition = entry.get("disposition")
    if disposition == Disposition.WITHHELD.value:
        receipts = tuple(entry.get("receipts") or ())
        if not receipts:
            # ``Withheld`` refuses a receiptless refusal at construction, and
            # that raise is a bare ``ValueError`` from the vocabulary leaf.
            # A surface that promises to refuse a malformed payload has to
            # refuse it in its *own* words, or one class of malformed entry
            # leaves by a door no caller of this function is watching.
            # Unreachable from a ``serialize_leaf`` payload -- it always
            # writes the receipts -- which is exactly why it is caught here
            # rather than trusted.
            raise UnrankableNumber(
                surface, "a withheld entry carrying no receipt", [path]
            )
        return Withheld(receipts=receipts)
    if disposition == Disposition.STRUCTURAL_ZERO.value:
        reason = str(entry.get("reason") or "")
        if not reason.strip():
            # The same door, one disposition over: a declared zero with no
            # declaration is an ordinary zero, and ``StructuralZero`` says so
            # with a ``ValueError`` this surface would otherwise pass on.
            raise UnrankableNumber(
                surface, "a structural zero carrying no reason", [path]
            )
        return StructuralZero(reason=reason)
    if disposition != Disposition.MEASURED.value:
        raise UnrankableNumber(
            surface, f"a {disposition!r} disposition no payload may carry", [path]
        )
    return Measured(amount=value)


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

    One writer, so the parallel map cannot drift from the leaves it
    describes.  The four dispositions serialize as three shapes:

    * ``MEASURED`` -- the number, and an entry saying a rule produced it.
    * ``STRUCTURAL_ZERO`` -- ``0.0``, and an entry carrying the declaration
      that makes zero the answer, so the receipt is published.
    * ``WITHHELD`` -- **no number at all**, and an entry carrying every
      receipt.  ``present`` is False and the payload key is never written.
    * ``STARVED`` -- never reaches an entry: reading the quantity raises
      ``ProjectionStarvation``, which one handler turns into a named 500.
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
    total_damage``.  Passing the path separately would let a rename move one
    and not the other, leaving the map describing a leaf that is not there.
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

        An empty prefix is the payload's own root, whose keys carry no
        leading dot: ``duration``, not ``.duration``.  ``_records``, ``_set``
        and ``_dot`` are bound once because the optimizer walks every
        participant of every candidate through here.
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

        A withheld quantity writes no key and still lands its entry, so a
        consumer tells "refused, and why" from "no such field".
        """
        out = serialize_leaf(f"{self._dot}{key}", quantity, self._tag)
        # pylint: disable-next=protected-access
        self._writer._record(out)
        if out.present:
            self._target[key] = out.value

    def nested(self, target: MutableMapping[str, object], key: str) -> "LeafBlock":
        """A block for a sub-object of this one, at ``prefix.key``."""
        return LeafBlock(self._writer, target, f"{self._dot}{key}", self._tag)

    def structure(self, key: str, value: object) -> None:
        """Publish a nested object or list, naming every quantity inside it."""
        self._set(key, self._walk(value, f"{self._dot}{key}"))

    def publish(self, key: str, value: object) -> None:
        """One payload member, named by what it *is*.

        A quantity gets a leaf and an entry, a nested shape is walked, and
        anything else is a label, so an assembler classifies nothing itself.
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
                self._member(member, f"{path}[{index}]")
                for index, member in enumerate(value)
            ]
        return value

    def _member(self, value: object, path: str) -> object:
        """One list member, with a bare number inside it written as a leaf.

        A float sitting directly in a list is as published as one behind a
        key, so one function emits its leaf and its entry too.

        The discarding branch is :meth:`measured`'s, for :data:`DISCARD`'s
        reason and no other: a member nobody records is the same float.
        """
        if not isinstance(value, float):
            return self._walk(value, path)
        if not self._records:
            return float(value)
        out = serialize_leaf(path, Measured(amount=float(value)), self._tag)
        # pylint: disable-next=protected-access
        self._writer._record(out)
        return out.value

    def raw(self, key: str, value: object) -> None:
        """Publish a non-numeric leaf: a label, a flag, a list, an id."""
        self._set(key, value)

    def optional_measured(self, key: str, value: float | None) -> None:
        """A number the walk may not have: published as ``null``, with no entry.

        ``null`` is not a number, so it carries no disposition.
        """
        if value is None:
            self._set(key, None)
            return
        self.measured(key, value)

    def measured(self, key: str, value: float) -> None:
        """``put`` for the overwhelmingly common case: a rule produced this.

        The short branch is the same expression with two allocations out.
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
        """A binder for one sub-object of the payload at ``prefix``."""
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


class RankingWriter(LeafWriter):
    """The writer for a payload whose numbers choose a build.

    The write half of D-62's second rule.  ``/api/bis`` and ``/api/optimize``
    do not merely publish their numbers, they *rank* by them, so a preview
    reaching one of those payloads is a build chosen by a fight that never
    happened.  Refusing it here means a view that retagged a block
    ``THEORETICAL`` fails the moment a ranking surface asks it for a payload,
    with no map to consult and no per-leaf check to remember.

    :meth:`~LeafWriter.block` is the one place a tag enters — ``nested``,
    ``structure`` and the nested walk all carry the block's own tag down —
    so refusing a non-``APPLIED`` block is total over every leaf the payload
    can hold.  That induction is asserted by source scan rather than
    believed: ``LeafBlock`` is constructed nowhere outside this module.

    The read half is :func:`refuse_previewed`, and both halves exist because
    the two surfaces are not symmetrical: BIS scores a *published* payload
    and can be asked what its numbers mean, while the optimizer scores
    thousands of candidate payloads written through :data:`DISCARD`, which
    by ruling carries no map at all.
    """

    __slots__ = ()

    def block(
        self,
        target: MutableMapping[str, object],
        prefix: str,
        tag: ViewTag = ViewTag.APPLIED,
    ) -> LeafBlock:
        """Open a block, or refuse the meaning it declares."""
        if tag is not ViewTag.APPLIED:
            raise UnrankableNumber(
                "a payload that picks a winner",
                f"a {tag.value} block",
                [prefix or "<payload root>"],
            )
        return super().block(target, prefix, tag)


class _DiscardingWriter(RankingWriter):
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

    It is a :class:`RankingWriter` because of who discards: the optimizer's
    candidate payloads are the ones it scores, and a payload with no map is
    a payload nothing can be asked about afterwards.  Refusing a previewed
    block on the way in is the only moment left to refuse it.
    """

    __slots__ = ()

    records = False

    def _record(self, out: LeafOut) -> None:
        """Record nothing; the caller has already said nobody will read it."""

    def entries(self) -> dict[str, dict[str, object]]:
        """Always empty -- and a payload that published this would say so."""
        return {}


DISCARD = _DiscardingWriter()


def name_every_number(
    payload: MutableMapping[str, object],
    writer: LeafWriter,
    *,
    skip: Container[str] = (),
) -> dict[str, dict[str, object]]:
    """Re-write a finished payload through *writer* and return its map.

    One pass over the three payloads a consumer is handed, rebuilding every
    nested container.  ``skip`` names blocks carrying a map of their own.
    """
    root = writer.block(payload, "")
    for key, value in list(payload.items()):
        if key not in skip:
            root.publish(key, value)
    return writer.entries()
