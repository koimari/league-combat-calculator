"""Typed evidence for coverage claims — the vocabulary and the load gate.

``item_coverage`` answers "is this item's damage mechanic represented by the
fight model", and every one of its answers used to be backed by a sentence.
A sentence cannot be checked, so one of them went on describing both halves
of Imperial Mandate's Command long after only one half existed.  This module
is the type that replaces the sentence: a :class:`Claim` names an item or a
precedence rule, the lane it is claimed on, the status it is expected to
classify as, and a closed union of **evidence members** that say what backs
it.

Three tiers catch three different failures, and the boundary between them is
ruled (D-20).  This module is the *load* tier and nothing more: it catches
structural impossibility — a claim whose shape cannot be backed by anything,
whatever the codebase happens to contain.  So it imports nothing from
``src.calculator``, reads no file, touches no ``data/`` cache, and runs a
single pass of string and set checks over the table, raising
:class:`CoverageClaimError`.  Whether a claim's evidence resolves against the
real tree is the *resolution* tier's question (``tests/coverage_resolver.py``,
on every ``pytest`` run); exact node ids and duplicate detection are the *full
session* tier's.  A load gate that imported the modules it describes would be
a startup cost on every request and a violation of the repo's caching rule,
and it would still not be able to prove more than the resolver already does.

Every evidence member holds **strings, never objects**.  That is what keeps
this module a standard-library leaf nothing can cycle against, and what makes
every read injectable in the resolver's three seams — a member holding a live
function object would resolve itself at authoring time and prove nothing.
The union is closed at nine members; ``StreamMembership`` is deliberately
absent, because it would resolve against name sets Phase 2 has deleted.

``ClaimLane`` lives here and Phase 3's ``EngineLane`` lives in
``item_behavior`` (D-45): two lane vocabularies answering different questions
must never both be spelled ``Lane``.
"""

import keyword
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

# ── vocabularies ──────────────────────────────────────────────────────────

ClaimLane = Literal["attacker", "target", "support_packet", "utility"]

ClaimStatus = Literal[
    "modeled_effect",
    "modeled_state",
    "stats_only",
    "blocked",
    "review_pending",
    "modeled",
    "modeled_event_certified",
    "not_target_relevant",
]

SubjectKind = Literal["item", "rule"]

SymbolRole = Literal[
    "pair_engine",
    "walk_packet_builder",
    "value_accessor",
    "tag_handler",
    "certification_guard",
    "compiler",
]

# How a dual-sided mechanic keeps its two halves from pricing one thing
# twice: the walk skips the holder, the holder is not a source of the
# effect at all, or the walk prices the holder too and the pair engine
# stands down.
OwnerPolicy = Literal[
    "owner_skips_holder",
    "holder_is_not_a_source",
    "holder_priced_by_walk",
]

# The registries an ``EffectKey`` may name.  Deliberately **not** Phase 3's
# ``ValueRegistry``: that union is three members (D-46) and must not admit
# ``ITEM_INPUT_OPTIONS``, which holds scenario controls rather than sourced
# numbers.  An evidence member may name an option control's key, so the
# evidence union is four.
EvidenceRegistry = Literal[
    "ITEM_EFFECTS",
    "ALLY_ITEM_EFFECTS",
    "RUNE_EFFECTS",
    "ITEM_INPUT_OPTIONS",
]

LANES: frozenset[str] = frozenset({"attacker", "target", "support_packet", "utility"})
CLAIM_STATUSES: frozenset[str] = frozenset(
    {
        "modeled_effect",
        "modeled_state",
        "stats_only",
        "blocked",
        "review_pending",
        "modeled",
        "modeled_event_certified",
        "not_target_relevant",
    }
)
SUBJECT_KINDS: frozenset[str] = frozenset({"item", "rule"})
SYMBOL_ROLES: frozenset[str] = frozenset(
    {
        "pair_engine",
        "walk_packet_builder",
        "value_accessor",
        "tag_handler",
        "certification_guard",
        "compiler",
    }
)
OWNER_POLICIES: frozenset[str] = frozenset(
    {"owner_skips_holder", "holder_is_not_a_source", "holder_priced_by_walk"}
)
EVIDENCE_REGISTRIES: frozenset[str] = frozenset(
    {"ITEM_EFFECTS", "ALLY_ITEM_EFFECTS", "RUNE_EFFECTS", "ITEM_INPUT_OPTIONS"}
)

# The measured outcome-dimension set.  It is pinned as a **set** and never as
# a count: ``item_coverage._UTILITY_DIMENSIONS`` is a 43-key dict over these
# 29 distinct strings, so either integer is a plausible-looking wrong answer.
# ``tests/test_coverage_evidence.py`` asserts set equality against that dict,
# which is what keeps this literal honest without importing it here.
#
# Admission rule: a new member arrives in the same commit as a claim carrying
# a ``PacketSource`` or an ``OptionSchema`` that names the mechanism producing
# it, or as a ``FRONTIER`` entry with an issue ref.  A dimension that names no
# mechanism is a product label, and product labels drift into coverage claims.
UTILITY_DIMENSIONS: frozenset[str] = frozenset(
    {
        "ally_support",
        "attack_speed_reduction",
        "cleanse",
        "copied_on_hit",
        "critical_mitigation",
        "damage_amplification",
        "defense",
        "economy",
        "energized",
        "execute",
        "health_state",
        "movement",
        "multi_target",
        "on_hit",
        "progression",
        "quest",
        "range",
        "resource",
        "revive",
        "shield",
        "slow",
        "slow_resistance",
        "spell_protection",
        "stasis",
        "stat_buff",
        "stat_conversion",
        "sustain",
        "takedown_state",
        "vision",
    }
)


class CoverageClaimError(ValueError):
    """A claim whose shape cannot be backed; raised at import, never caught.

    A ``ValueError`` because a malformed declaration is a programming error
    in the module that authored it — the import fails, loudly, at the first
    claim that cannot be true.
    """


# ── shared shape checks ───────────────────────────────────────────────────


def _require_text(value: object, *, claim: str, field: str) -> str:
    """A non-blank string, or a :class:`CoverageClaimError` naming *field*."""
    if not isinstance(value, str) or not value.strip():
        raise CoverageClaimError(
            f"{claim}: {field} must be a non-blank string, got {value!r}"
        )
    return value


def _require_no_whitespace(value: str, *, claim: str, field: str) -> None:
    """Reject internal whitespace in a token that names a code location."""
    if any(character.isspace() for character in value):
        raise CoverageClaimError(
            f"{claim}: {field} {value!r} carries whitespace; it names one "
            "location, not a sentence"
        )


def _require_identifier(value: object, *, claim: str, field: str) -> None:
    """A bare Python identifier that is not a keyword."""
    text = _require_text(value, claim=claim, field=field)
    if not text.isidentifier() or keyword.iskeyword(text):
        raise CoverageClaimError(f"{claim}: {field} {text!r} is not a plain identifier")


def _require_dotted_path(value: object, *, claim: str, field: str) -> None:
    """A dotted path of at least two identifier segments.

    Two is the floor because every path this module can carry names
    something *inside* a module — ``module.function`` at the shortest — and a
    single bare segment is a module name that no resolver can import a symbol
    out of.
    """
    text = _require_text(value, claim=claim, field=field)
    _require_no_whitespace(text, claim=claim, field=field)
    segments = text.split(".")
    if len(segments) < 2 or not all(
        segment.isidentifier() and not keyword.iskeyword(segment)
        for segment in segments
    ):
        raise CoverageClaimError(
            f"{claim}: {field} {text!r} is not a dotted path of at least two "
            "identifier segments"
        )


def _require_membership(
    value: object, allowed: frozenset[str], *, claim: str, field: str
) -> None:
    """A member of a closed vocabulary, named in the message when it is not."""
    if value not in allowed:
        raise CoverageClaimError(
            f"{claim}: {field} {value!r} is not one of {sorted(allowed)}"
        )


def _looks_numeric(text: str) -> bool:
    """Whether *text* is a bare number — the shape rule 5 forbids as a key."""
    try:
        float(text)
    except ValueError:
        return False
    return True


# ── the nine evidence members ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Symbol:
    """A dotted path and the role it plays — a claim's engine half.

    ``role`` is what makes two Symbols on one claim distinguishable: an
    ``modeled_event_certified`` claim carries its implementation *and* the
    guard that certifies the event, and without the role nothing could say
    which of the two is missing.
    """

    path: str
    role: SymbolRole

    def validate(self, *, claim: str) -> None:
        """Dotted-path shape and a role from the closed set."""
        _require_dotted_path(self.path, claim=claim, field="Symbol.path")
        _require_membership(self.role, SYMBOL_ROLES, claim=claim, field="Symbol.role")


@dataclass(frozen=True, slots=True)
class PacketSource:
    """A walk packet's exact ``source=`` string; ``{}`` is an f-string slot.

    The string is the packet's public receipt text, so it is carried
    verbatim.  Where the producer builds it with an f-string the interpolated
    parts collapse to bare ``{}`` slots, matching what
    ``render_source_argument`` renders out of the AST — a member spelling
    ``{item}`` would never match the rendering and could never resolve.
    """

    source: str

    def validate(self, *, claim: str) -> None:
        """Non-blank, and every brace is an empty ``{}`` slot."""
        text = _require_text(self.source, claim=claim, field="PacketSource.source")
        residue = text.replace("{}", "")
        if "{" in residue or "}" in residue:
            raise CoverageClaimError(
                f"{claim}: PacketSource.source {text!r} carries a named or "
                "unbalanced brace; an f-string slot collapses to '{}'"
            )


@dataclass(frozen=True, slots=True)
class PairedSides:
    """A Phase-2 mechanic id whose two engine halves must both exist.

    The incident shipped with one half present and a hand list that agreed
    with it, so this member names the mechanic and the handshake policy only:
    the resolution tier is what checks that the capability exists, that its
    ``authority`` is ``SPLIT``, and that ``pair_of`` closes in both
    directions.
    """

    mechanic: str
    owner_policy: OwnerPolicy

    def validate(self, *, claim: str) -> None:
        """``<owner_slug>.<effect_slug>`` plus a policy from the closed set."""
        text = _require_text(self.mechanic, claim=claim, field="PairedSides.mechanic")
        owner, dot, effect = text.partition(".")
        if not dot or "." in effect:
            raise CoverageClaimError(
                f"{claim}: PairedSides.mechanic {text!r} is not "
                "'<owner_slug>.<effect_slug>'"
            )
        _require_identifier(owner, claim=claim, field="PairedSides.mechanic owner")
        _require_identifier(effect, claim=claim, field="PairedSides.mechanic effect")
        _require_membership(
            self.owner_policy,
            OWNER_POLICIES,
            claim=claim,
            field="PairedSides.owner_policy",
        )


@dataclass(frozen=True, slots=True)
class EffectKey:
    """One key in one value registry — the key, never its number (rule 5).

    A number copied into a declaration is a stale literal waiting to happen,
    and that exact failure once hid a 3x Statikk Shiv overstatement.  So the
    member names where the number lives and a numeric-looking key is
    rejected outright.
    """

    registry: EvidenceRegistry
    item: str
    key: str

    def validate(self, *, claim: str) -> None:
        """A known registry, a named holder, and a key that is not a value."""
        _require_membership(
            self.registry,
            EVIDENCE_REGISTRIES,
            claim=claim,
            field="EffectKey.registry",
        )
        _require_text(self.item, claim=claim, field="EffectKey.item")
        key = _require_text(self.key, claim=claim, field="EffectKey.key")
        _require_no_whitespace(key, claim=claim, field="EffectKey.key")
        if _looks_numeric(key):
            raise CoverageClaimError(
                f"{claim}: EffectKey.key {key!r} is a number; evidence names "
                "the registry key, never its value (CLAUDE.md rule 5)"
            )


@dataclass(frozen=True, slots=True)
class EffectTag:
    """One ``item_effects._KNOWN_EFFECT_TYPES`` member with a live handler.

    Both halves are load-bearing: a tag with no handler is a data label
    nothing reads, which is exactly the state four of the tags are in today.
    ``handler`` is the qualified name whose dispatch branches
    ``tag_dispatch_branches`` reads back as this member's oracle.
    """

    tag: str
    handler: str

    def validate(self, *, claim: str) -> None:
        """An identifier-shaped tag and a dotted handler qualname."""
        _require_identifier(self.tag, claim=claim, field="EffectTag.tag")
        _require_dotted_path(self.handler, claim=claim, field="EffectTag.handler")


@dataclass(frozen=True, slots=True)
class OptionSchema:
    """A bounded ``ITEM_INPUT_OPTIONS`` control backing ``modeled_state``.

    ``modeled_state`` says an item's damage-relevant state is supplied as an
    explicit scenario control rather than assumed, so the claim has to name
    the control.  Whether its declared bounds are real is the resolver's
    question; that it names one is this tier's.
    """

    item: str
    option: str

    def validate(self, *, claim: str) -> None:
        """A named holder and an identifier-shaped control."""
        _require_text(self.item, claim=claim, field="OptionSchema.item")
        _require_identifier(self.option, claim=claim, field="OptionSchema.option")


@dataclass(frozen=True, slots=True)
class TestRef:
    """A pytest node id that must exist and must be able to fail.

    "Must be able to fail" is four separate rules the resolver runs — one
    collected node, no skip marker, no xfail in any form, no
    ``pytest.skip``/``importorskip`` in the body or its fixture closure — plus
    a fifth about relevance.  None of them is checkable here; what is
    checkable is that the string is a node id at all, because a bare test
    name would silently match nothing.
    """

    # pytest tries to collect any imported class whose name starts with
    # ``Test``.  The name is the campaign's, so the opt-out lives here once
    # rather than as an import alias every consuming test has to remember.
    __test__ = False

    node_id: str

    def validate(self, *, claim: str) -> None:
        """``<path>.py::<node>`` with no whitespace."""
        text = _require_text(self.node_id, claim=claim, field="TestRef.node_id")
        _require_no_whitespace(text, claim=claim, field="TestRef.node_id")
        path, separator, node = text.partition("::")
        if not separator or not node or not path.endswith(".py"):
            raise CoverageClaimError(
                f"{claim}: TestRef.node_id {text!r} is not " "'<path>.py::<node>'"
            )


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A wiki url + revision id present in the committed full-entry audit.

    The revision is what makes the citation reproducible: a bare url names a
    page whose text has moved on, and this campaign exists because a
    description outlived the thing it described.
    """

    url: str
    revision_id: int

    def validate(self, *, claim: str) -> None:
        """An https url and a positive revision id."""
        url = _require_text(self.url, claim=claim, field="SourceRef.url")
        _require_no_whitespace(url, claim=claim, field="SourceRef.url")
        if not url.startswith("https://") or len(url) <= len("https://"):
            raise CoverageClaimError(
                f"{claim}: SourceRef.url {url!r} is not an https url"
            )
        if not isinstance(self.revision_id, int) or isinstance(self.revision_id, bool):
            raise CoverageClaimError(
                f"{claim}: SourceRef.revision_id {self.revision_id!r} is not "
                "an integer"
            )
        if self.revision_id <= 0:
            raise CoverageClaimError(
                f"{claim}: SourceRef.revision_id {self.revision_id} is not a "
                "positive revision"
            )


@dataclass(frozen=True, slots=True)
class Absence:
    """The only evidence a negative claim may carry: reason + issue refs.

    A refusal is a claim like any other and owes the same receipt.  The issue
    refs live here rather than on the claim so a negative claim has exactly
    one home for them.
    """

    reason: str
    issue_refs: tuple[int, ...]

    def validate(self, *, claim: str) -> None:
        """A written reason and at least one tracked issue."""
        _require_text(self.reason, claim=claim, field="Absence.reason")
        if not isinstance(self.issue_refs, tuple) or not self.issue_refs:
            raise CoverageClaimError(
                f"{claim}: Absence.issue_refs is empty; a refusal names the "
                "issue that tracks it"
            )
        for ref in self.issue_refs:
            if not isinstance(ref, int) or isinstance(ref, bool) or ref <= 0:
                raise CoverageClaimError(
                    f"{claim}: Absence.issue_refs holds {ref!r}, which is not "
                    "a positive issue number"
                )


Evidence = (
    Symbol
    | PacketSource
    | PairedSides
    | EffectKey
    | EffectTag
    | OptionSchema
    | TestRef
    | SourceRef
    | Absence
)

# The union, closed and enumerated once.  ``StreamMembership`` is
# deliberately absent: it would have resolved against five hand name sets
# Phase 2 deleted, so it could only ever have been evidence for a thing that
# no longer exists.
EVIDENCE_TYPES: tuple[type, ...] = (
    Symbol,
    PacketSource,
    PairedSides,
    EffectKey,
    EffectTag,
    OptionSchema,
    TestRef,
    SourceRef,
    Absence,
)
EVIDENCE_KINDS: frozenset[str] = frozenset(kind.__name__ for kind in EVIDENCE_TYPES)
_POSITIVE_EVIDENCE_KINDS: frozenset[str] = EVIDENCE_KINDS - {"Absence"}


# ── the claim and the requirement matrix ──────────────────────────────────


# Eight fields, one over pylint's default: the record is a declaration, and
# every field below is separately load-checked.  Splitting it to satisfy the
# counter would put a claim's shape in two places, which is the failure this
# module exists to prevent.
@dataclass(frozen=True, slots=True)
class Claim:  # pylint: disable=too-many-instance-attributes
    """One coverage assertion about one item or rule, and what backs it.

    ``status`` is a **pinned expectation, never an authority**: the classifier
    in ``item_coverage`` stays the only answer to "what is this item's
    coverage", and a resolution-tier check asserts the two agree for every
    cached item.  Authoring it here is what makes the requirement matrix
    checkable with no imports and no ``data/`` read.

    Attributes:
        subject_kind: an item, or a precedence rule.  Hand-listed families
            get one claim per ``(item, lane)``; families recomputed from
            ``data/`` on every call get one claim per *rule*, because their
            membership is not a list anyone can enumerate at authoring time.
        subject: the item name or the rule id.
        lane: which classifier surface the claim is about.
        status: the status that surface is expected to yield.
        evidence: the closed union, at least one member, no duplicates.
        dimensions: outcome dimensions, each a ``UTILITY_DIMENSIONS`` member.
        issue_refs: tracked follow-on work on a *positive* claim.  A negative
            claim carries its refs on its ``Absence`` instead, so the refs
            have exactly one home per claim.
        unreachable_reason: why no cached item can reach this claim, for a
            claim an earlier precedence rung shadows.  Empty for the ordinary
            reachable claim; a shadowed one is still a claim and still owes
            its status policy.
    """

    subject_kind: SubjectKind
    subject: str
    lane: ClaimLane
    status: ClaimStatus
    evidence: tuple[Evidence, ...]
    dimensions: tuple[str, ...]
    issue_refs: tuple[int, ...]
    unreachable_reason: str


@dataclass(frozen=True, slots=True)
class EvidencePolicy:
    """Which evidence kinds a lane/status cell must carry, must not, and how many.

    ``min_count`` is a floor on the **total** member count, not a restatement
    of ``len(required)``: ``modeled_event_certified`` requires the kinds
    ``Symbol`` and ``TestRef`` but three members, because it needs two
    Symbols — the implementation and the certification guard.

    Attributes:
        required: evidence kind names that must each be present.
        forbidden: evidence kind names that must be absent.
        min_count: the smallest legal number of evidence members.
    """

    required: frozenset[str]
    forbidden: frozenset[str]
    min_count: int


# A status is negative when it withholds rather than models.  Both of them
# take exactly one ``Absence`` and no positive evidence at all.
NEGATIVE_STATUSES: frozenset[str] = frozenset({"blocked", "review_pending"})

# Which statuses each lane may claim, derived from the two live classifiers
# rather than invented: ``item_model_coverage`` yields exactly the attacker
# row and ``target_item_model_coverage`` exactly the target row.  The two
# derived lanes reuse the attacker spellings, less ``stats_only`` on
# ``support_packet`` — a support packet either exists or is withheld, and
# "the mechanic changes defense, not outgoing damage" is not a statement a
# packet claim can make.
LANE_STATUSES: Mapping[str, frozenset[str]] = {
    "attacker": frozenset({"modeled_effect", "modeled_state", "stats_only"})
    | NEGATIVE_STATUSES,
    "target": frozenset({"modeled", "modeled_event_certified", "not_target_relevant"})
    | NEGATIVE_STATUSES,
    "support_packet": frozenset({"modeled_effect", "modeled_state"})
    | NEGATIVE_STATUSES,
    "utility": frozenset({"modeled_effect", "modeled_state", "stats_only"})
    | NEGATIVE_STATUSES,
}

_STATUS_POLICIES: Mapping[str, EvidencePolicy] = {
    "modeled_effect": EvidencePolicy(
        required=frozenset({"Symbol", "TestRef"}),
        forbidden=frozenset({"Absence"}),
        min_count=2,
    ),
    "modeled": EvidencePolicy(
        required=frozenset({"Symbol", "TestRef"}),
        forbidden=frozenset({"Absence"}),
        min_count=2,
    ),
    "modeled_state": EvidencePolicy(
        required=frozenset({"Symbol", "TestRef", "OptionSchema"}),
        forbidden=frozenset({"Absence"}),
        min_count=3,
    ),
    "modeled_event_certified": EvidencePolicy(
        required=frozenset({"Symbol", "TestRef"}),
        forbidden=frozenset({"Absence"}),
        min_count=3,
    ),
    "stats_only": EvidencePolicy(
        required=frozenset({"SourceRef"}),
        forbidden=frozenset({"Absence", "PacketSource"}),
        min_count=1,
    ),
    "not_target_relevant": EvidencePolicy(
        required=frozenset({"SourceRef"}),
        forbidden=frozenset({"Absence", "PacketSource"}),
        min_count=1,
    ),
    "blocked": EvidencePolicy(
        required=frozenset({"Absence"}),
        forbidden=_POSITIVE_EVIDENCE_KINDS,
        min_count=1,
    ),
    "review_pending": EvidencePolicy(
        required=frozenset({"Absence"}),
        forbidden=_POSITIVE_EVIDENCE_KINDS,
        min_count=1,
    ),
}


def status_policy(lane: ClaimLane, status: ClaimStatus) -> EvidencePolicy:
    """The requirement matrix for one lane/status cell.

    ``modeled_*`` needs a ``Symbol`` and a ``TestRef``; ``modeled_state``
    additionally needs the ``OptionSchema`` naming its control;
    ``stats_only`` and ``not_target_relevant`` need a ``SourceRef`` and
    forbid a ``PacketSource``, because an item that emits a packet is not
    stats-only; ``blocked`` and ``review_pending`` need exactly one
    ``Absence`` and no positive evidence; the ``support_packet`` lane adds a
    ``PacketSource`` to every positive cell.

    Two of the matrix's rules are about a member's *fields* rather than its
    kind, so ``EvidencePolicy`` cannot carry them and :func:`validate_claim`
    enforces them beside this cell: ``modeled_event_certified`` needs one of
    its Symbols to be the ``certification_guard``, and a ``PairedSides`` is
    owed wherever Phase 2 declares the mechanic ``SPLIT`` — the second is the
    resolution tier's, since only the capability registry knows.
    """
    _require_membership(lane, LANES, claim="status_policy", field="lane")
    _require_membership(status, CLAIM_STATUSES, claim="status_policy", field="status")
    if status not in LANE_STATUSES[lane]:
        raise CoverageClaimError(
            f"status_policy: status {status!r} is not claimable on the {lane!r} "
            f"lane; that lane yields {sorted(LANE_STATUSES[lane])}"
        )
    policy = _STATUS_POLICIES[status]
    if status in NEGATIVE_STATUSES or lane != "support_packet":
        return policy
    return EvidencePolicy(
        required=policy.required | {"PacketSource"},
        forbidden=policy.forbidden,
        min_count=policy.min_count + 1,
    )


# ── validation ────────────────────────────────────────────────────────────


def claim_name(claim: Claim) -> str:
    """The claim's key rendered for an error message."""
    return f"{claim.subject_kind}:{claim.subject}@{claim.lane}"


def validate_evidence(ev: Evidence, *, claim: str) -> None:
    """Reject a malformed evidence member; ``claim`` only names it in the message."""
    if not isinstance(ev, EVIDENCE_TYPES):
        raise CoverageClaimError(
            f"{claim}: {ev!r} is not one of the {len(EVIDENCE_TYPES)} evidence "
            f"kinds {sorted(EVIDENCE_KINDS)}"
        )
    ev.validate(claim=claim)


def _validate_vocabulary(claim: Claim, *, name: str) -> None:
    """Every closed vocabulary on the claim itself, named against the claim.

    ``status_policy`` checks the lane and the status again as its own public
    guard.  The repeat is deliberate: over a table of hundreds of claims an
    error that names only the bad value and not the claim carrying it is a
    grep, and the accessor called on its own still has to refuse a lane it
    has no cell for.
    """
    _require_membership(
        claim.subject_kind, SUBJECT_KINDS, claim=name, field="subject_kind"
    )
    _require_text(claim.subject, claim=name, field="subject")
    _require_membership(claim.lane, LANES, claim=name, field="lane")
    _require_membership(claim.status, CLAIM_STATUSES, claim=name, field="status")


def _validate_evidence_set(claim: Claim, policy: EvidencePolicy, *, name: str) -> None:
    """Every member valid and distinct, and the cell's matrix satisfied."""
    if not isinstance(claim.evidence, tuple) or not claim.evidence:
        raise CoverageClaimError(
            f"{name}: evidence is empty; every claim names what backs it"
        )
    seen: set[Evidence] = set()
    for member in claim.evidence:
        validate_evidence(member, claim=name)
        if member in seen:
            raise CoverageClaimError(
                f"{name}: evidence member {member!r} is repeated; a duplicate "
                "inflates the member count without backing anything"
            )
        seen.add(member)

    present = {type(member).__name__ for member in claim.evidence}
    missing = policy.required - present
    if missing:
        raise CoverageClaimError(
            f"{name}: status {claim.status!r} requires evidence "
            f"{sorted(policy.required)} and is missing {sorted(missing)}"
        )
    intruding = policy.forbidden & present
    if intruding:
        raise CoverageClaimError(
            f"{name}: status {claim.status!r} forbids evidence " f"{sorted(intruding)}"
        )
    if len(claim.evidence) < policy.min_count:
        raise CoverageClaimError(
            f"{name}: status {claim.status!r} needs at least "
            f"{policy.min_count} evidence members, got {len(claim.evidence)}"
        )
    _validate_field_rules(claim, name=name)


def _validate_field_rules(claim: Claim, *, name: str) -> None:
    """The two matrix rules that are about a member's fields, not its kind."""
    if claim.status in NEGATIVE_STATUSES:
        absences = [m for m in claim.evidence if isinstance(m, Absence)]
        if len(absences) != 1:
            raise CoverageClaimError(
                f"{name}: status {claim.status!r} carries {len(absences)} "
                "Absence members; a refusal has exactly one reason"
            )
        return
    if claim.status == "modeled_event_certified" and not any(
        isinstance(m, Symbol) and m.role == "certification_guard"
        for m in claim.evidence
    ):
        raise CoverageClaimError(
            f"{name}: status 'modeled_event_certified' needs a Symbol with "
            "role 'certification_guard'; without it the claim says an event "
            "is certified and names nothing that certifies it"
        )


def _validate_dimensions(claim: Claim, *, name: str) -> None:
    """Closed dimensions, no repeats, and a utility claim that names one."""
    if not isinstance(claim.dimensions, tuple):
        raise CoverageClaimError(f"{name}: dimensions must be a tuple")
    for dimension in claim.dimensions:
        _require_membership(
            dimension, UTILITY_DIMENSIONS, claim=name, field="dimension"
        )
    if len(set(claim.dimensions)) != len(claim.dimensions):
        raise CoverageClaimError(
            f"{name}: dimensions {list(claim.dimensions)} repeat a member"
        )
    if claim.lane == "utility" and not claim.dimensions:
        raise CoverageClaimError(
            f"{name}: a utility claim with no dimension names no outcome"
        )


def _validate_issue_refs(claim: Claim, *, name: str) -> None:
    """Issue refs have one home per claim, and a reason is never blank."""
    if not isinstance(claim.issue_refs, tuple):
        raise CoverageClaimError(f"{name}: issue_refs must be a tuple")
    if claim.status in NEGATIVE_STATUSES and claim.issue_refs:
        raise CoverageClaimError(
            f"{name}: a negative claim carries its issue refs on its Absence, "
            f"not on the claim; drop {list(claim.issue_refs)}"
        )
    for ref in claim.issue_refs:
        if not isinstance(ref, int) or isinstance(ref, bool) or ref <= 0:
            raise CoverageClaimError(
                f"{name}: issue_refs holds {ref!r}, which is not a positive "
                "issue number"
            )
    if not isinstance(claim.unreachable_reason, str):
        raise CoverageClaimError(f"{name}: unreachable_reason must be a string")
    if claim.unreachable_reason and not claim.unreachable_reason.strip():
        raise CoverageClaimError(
            f"{name}: unreachable_reason is blank; either say why no cached "
            "item reaches this claim or leave it empty"
        )


def validate_claim(claim: Claim) -> None:
    """Vocabulary, matrix, dotted-path shape, closed dimensions."""
    if not isinstance(claim, Claim):
        raise CoverageClaimError(f"{claim!r} is not a Claim")
    name = claim_name(claim)
    _validate_vocabulary(claim, name=name)
    policy = status_policy(claim.lane, claim.status)
    _validate_evidence_set(claim, policy, name=name)
    _validate_dimensions(claim, name=name)
    _validate_issue_refs(claim, name=name)


def validate_claim_table(
    claims: Mapping[tuple[SubjectKind, str, ClaimLane], Claim],
) -> None:
    """The load gate (D-20): per-claim validity and key agreement.

    One pass over the table, so the cost is linear in the number of claims
    and nothing here imports, reads a file, or touches ``data/``.  The
    matrix's own rules carry the rest: a positive claim cannot hold an
    ``Absence`` and a negative one cannot hold positive evidence, because
    :func:`status_policy` forbids each in the other's cell.

    Key uniqueness is not the mapping's guarantee — a dict cannot repeat a
    key — it is that the key **agrees** with the claim it addresses, which is
    what stops a claim being filed against an item it says nothing about.
    """
    for key, claim in claims.items():
        if not isinstance(key, tuple) or len(key) != 3:
            raise CoverageClaimError(
                f"claim key {key!r} is not a (subject_kind, subject, lane) triple"
            )
        validate_claim(claim)
        expected = (claim.subject_kind, claim.subject, claim.lane)
        if key != expected:
            raise CoverageClaimError(
                f"claim key {key!r} disagrees with the claim it addresses, "
                f"{expected!r}"
            )


__all__ = [
    "Absence",
    "CLAIM_STATUSES",
    "Claim",
    "ClaimLane",
    "ClaimStatus",
    "CoverageClaimError",
    "EVIDENCE_KINDS",
    "EVIDENCE_REGISTRIES",
    "EVIDENCE_TYPES",
    "EffectKey",
    "EffectTag",
    "Evidence",
    "EvidencePolicy",
    "EvidenceRegistry",
    "LANES",
    "LANE_STATUSES",
    "NEGATIVE_STATUSES",
    "OWNER_POLICIES",
    "OptionSchema",
    "OwnerPolicy",
    "PacketSource",
    "PairedSides",
    "SUBJECT_KINDS",
    "SYMBOL_ROLES",
    "SourceRef",
    "SubjectKind",
    "Symbol",
    "SymbolRole",
    "TestRef",
    "UTILITY_DIMENSIONS",
    "claim_name",
    "status_policy",
    "validate_claim",
    "validate_claim_table",
    "validate_evidence",
]
