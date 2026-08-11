"""The load tier — one negative per forbidden claim shape.

``coverage_evidence`` catches structural impossibility and nothing else
(D-20): a claim whose shape cannot be backed by *anything*, whatever the
codebase happens to contain.  Every rule it enforces therefore owes a test
that reaches it, because a validator whose branch no test can trigger is
indistinguishable from a validator that returns ``None`` — which is the
failure this whole campaign is about, one size smaller.

Resolution — does this evidence name something that actually exists — is
``tests/coverage_resolver.py``'s and is deliberately absent here.  The two
tests that read outside this module are the boundary checks: the source
assertion that the load gate imports nothing and reads nothing, and the set
equality that keeps ``UTILITY_DIMENSIONS`` honest against the dict it was
measured from.
"""

import ast
import io
import tokenize
from pathlib import Path

import pytest

from src.calculator import coverage_evidence
from src.calculator.coverage_evidence import (
    CLAIM_STATUSES,
    EVIDENCE_KINDS,
    EVIDENCE_TYPES,
    LANE_STATUSES,
    LANES,
    NEGATIVE_STATUSES,
    UTILITY_DIMENSIONS,
    Absence,
    Claim,
    CoverageClaimError,
    EffectKey,
    EffectTag,
    OptionSchema,
    PacketSource,
    PairedSides,
    PrecedenceRule,
    SourceRef,
    Symbol,
    TestRef,
    status_policy,
    validate_claim,
    validate_claim_table,
    validate_evidence,
    validate_precedence,
    validate_precedence_rule,
)
from src.calculator.item_coverage import PRECEDENCE, _UTILITY_DIMENSIONS

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "calculator" / "coverage_evidence.py"
)

# Well-formed members, one per kind, reused by every negative below so a
# failure names the one field the case broke.
IMPL = Symbol(
    path="item_support_effects.derive_item_support_effects",
    role="walk_packet_builder",
)
PAIR_IMPL = Symbol(path="damage._apply_command_amp", role="pair_engine")
GUARD = Symbol(path="damage._validate_cc_event_contract", role="certification_guard")
NODE = TestRef(node_id="tests/test_command_amp_roster.py::test_command_amp_is_priced")
OTHER_NODE = TestRef(node_id="tests/test_item_support_effects.py::test_mandate_packet")
PACKET = PacketSource(source="Imperial Mandate — Command")
OPTION = OptionSchema(item="Rod of Ages", option="rod_of_ages_stacks")
EFFECT_KEY = EffectKey(
    registry="ITEM_EFFECTS", item="Imperial Mandate", key="command_amp_percent"
)
SOURCE = SourceRef(
    url="https://wiki.leagueoflegends.com/en-us/Abyssal_Mask", revision_id=2864060
)
ABSENCE = Absence(
    reason="No walk packet prices Bandlepipes' Fanfare movement window.",
    issue_refs=(40,),
)


def claim(**overrides) -> Claim:
    """A valid attacker ``modeled_effect`` claim, with fields overridden."""
    fields = {
        "subject_kind": "item",
        "subject": "Imperial Mandate",
        "lane": "attacker",
        "status": "modeled_effect",
        "evidence": (IMPL, NODE),
        "dimensions": (),
        "issue_refs": (),
        "unreachable_reason": "",
    }
    fields.update(overrides)
    return Claim(**fields)


def table(*claims: Claim) -> dict:
    """The claim table keyed the way the load gate expects."""
    return {(c.subject_kind, c.subject, c.lane): c for c in claims}


# ---------------------------------------------------------------------------
# The valid case, so every negative below is known to fail on its own rule
# ---------------------------------------------------------------------------


def test_a_well_formed_table_validates() -> None:
    """The load gate accepts one claim per lane, each with its own shape."""
    validate_claim_table(
        table(
            claim(),
            claim(
                lane="target",
                status="modeled_event_certified",
                evidence=(IMPL, GUARD, NODE),
            ),
            claim(
                subject="Bandlepipes",
                lane="support_packet",
                status="modeled_state",
                evidence=(IMPL, NODE, OPTION, PACKET),
            ),
            claim(
                subject="Ardent Censer",
                lane="utility",
                status="stats_only",
                evidence=(SOURCE,),
                dimensions=("ally_support", "sustain"),
            ),
            claim(
                subject_kind="rule",
                subject="item_effects_membership",
                lane="attacker",
                status="blocked",
                evidence=(ABSENCE,),
            ),
        )
    )


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


def test_unknown_lane_is_rejected() -> None:
    """A lane outside the closed four cannot be claimed on."""
    with pytest.raises(CoverageClaimError, match="lane 'jungle'"):
        validate_claim(claim(lane="jungle"))


def test_unknown_status_is_rejected() -> None:
    """A status outside the closed eight has no policy cell."""
    with pytest.raises(CoverageClaimError, match="status 'probably_fine'"):
        validate_claim(claim(status="probably_fine"))


def test_status_illegal_on_its_lane_is_rejected() -> None:
    """``not_target_relevant`` is the target classifier's spelling alone."""
    with pytest.raises(CoverageClaimError, match="not claimable on the 'attacker'"):
        validate_claim(claim(status="not_target_relevant", evidence=(SOURCE,)))


def test_unknown_subject_kind_is_rejected() -> None:
    """A claim's subject is an item or a precedence rule; there is no third."""
    with pytest.raises(CoverageClaimError, match="subject_kind 'champion'"):
        validate_claim(claim(subject_kind="champion"))


def test_blank_subject_is_rejected() -> None:
    """A claim that names nothing backs nothing."""
    with pytest.raises(CoverageClaimError, match="subject must be a non-blank"):
        validate_claim(claim(subject="   "))


def test_a_non_claim_value_is_rejected() -> None:
    """The table holds claims, not look-alike mappings."""
    with pytest.raises(CoverageClaimError, match="is not a Claim"):
        validate_claim({"subject": "Imperial Mandate"})


# ---------------------------------------------------------------------------
# The requirement matrix
# ---------------------------------------------------------------------------


def test_missing_required_evidence_kind_is_rejected() -> None:
    """``modeled_effect`` without a TestRef is a claim nothing can fail on."""
    with pytest.raises(CoverageClaimError, match=r"missing \['TestRef'\]"):
        validate_claim(claim(evidence=(IMPL, PAIR_IMPL)))


def test_absence_on_a_positive_claim_is_rejected() -> None:
    """A claim cannot say the mechanic is modelled and also that it is not."""
    with pytest.raises(CoverageClaimError, match=r"forbids evidence \['Absence'\]"):
        validate_claim(claim(evidence=(IMPL, NODE, ABSENCE)))


def test_positive_evidence_on_a_negative_claim_is_rejected() -> None:
    """A refusal carries its reason and nothing that looks like coverage."""
    with pytest.raises(CoverageClaimError, match="forbids evidence"):
        validate_claim(claim(status="blocked", evidence=(ABSENCE, IMPL)))


def test_two_absences_on_a_negative_claim_are_rejected() -> None:
    """A refusal has exactly one reason, so the receipt is unambiguous."""
    second = Absence(reason="A second, different reason.", issue_refs=(41,))
    with pytest.raises(CoverageClaimError, match="carries 2 Absence members"):
        validate_claim(claim(status="blocked", evidence=(ABSENCE, second)))


def test_min_count_below_the_cell_floor_is_rejected() -> None:
    """A certified event needs three members: impl, guard and test."""
    with pytest.raises(CoverageClaimError, match="at least 3 evidence members"):
        validate_claim(
            claim(
                lane="target",
                status="modeled_event_certified",
                evidence=(GUARD, NODE),
            )
        )


def test_certified_status_without_a_certification_guard_is_rejected() -> None:
    """The role rule the kind-level cell cannot express."""
    with pytest.raises(CoverageClaimError, match="role 'certification_guard'"):
        validate_claim(
            claim(
                lane="target",
                status="modeled_event_certified",
                evidence=(IMPL, PAIR_IMPL, NODE),
            )
        )


@pytest.mark.parametrize(
    "home",
    [OPTION, PACKET, EFFECT_KEY],
    ids=["OptionSchema", "PacketSource", "EffectKey"],
)
def test_modeled_state_accepts_any_of_the_three_state_homes(home) -> None:
    """The live classifier reaches ``modeled_state`` by three routes.

    A bounded scenario control, an authored event the ledger schedules into a
    named packet, and a sourced registry value the engine reads are all
    "the state is supplied rather than assumed"; requiring the control alone
    would leave seven of the twenty stateful items unclaimable.
    """
    validate_claim(claim(status="modeled_state", evidence=(IMPL, NODE, home)))


def test_modeled_state_naming_no_state_home_is_rejected() -> None:
    """Three members are not enough if none of them supplies the state."""
    with pytest.raises(CoverageClaimError, match="needs one of"):
        validate_claim(
            claim(status="modeled_state", evidence=(IMPL, GUARD, NODE)),
        )


def test_support_packet_lane_without_a_packet_source_is_rejected() -> None:
    """The lane overlay: a support-packet claim names its packet."""
    with pytest.raises(CoverageClaimError, match=r"missing \['PacketSource'\]"):
        validate_claim(claim(lane="support_packet", evidence=(IMPL, NODE, OTHER_NODE)))


def test_stats_only_carrying_a_packet_source_is_rejected() -> None:
    """An item that emits a packet is not stats-only."""
    with pytest.raises(
        CoverageClaimError, match=r"forbids evidence \['PacketSource'\]"
    ):
        validate_claim(claim(status="stats_only", evidence=(SOURCE, PACKET)))


def test_empty_evidence_is_rejected() -> None:
    """Every claim names what backs it — that is the whole point."""
    with pytest.raises(CoverageClaimError, match="evidence is empty"):
        validate_claim(claim(evidence=()))


def test_repeated_evidence_member_is_rejected() -> None:
    """A duplicate inflates the member count without backing anything."""
    with pytest.raises(CoverageClaimError, match="is repeated"):
        validate_claim(
            claim(
                lane="target",
                status="modeled_event_certified",
                evidence=(IMPL, GUARD, NODE, NODE),
            )
        )


def test_a_foreign_object_in_the_evidence_tuple_is_rejected() -> None:
    """The union is closed; a bare string is not evidence."""
    with pytest.raises(CoverageClaimError, match="is not one of the 9 evidence kinds"):
        validate_claim(
            claim(evidence=(IMPL, NODE, "tests/test_smoke.py::test_imports"))
        )


# ---------------------------------------------------------------------------
# Dimensions, issue refs, unreachability
# ---------------------------------------------------------------------------


def test_dimension_outside_the_closed_set_is_rejected() -> None:
    """A dimension that names no measured outcome is a product label."""
    with pytest.raises(CoverageClaimError, match="dimension 'synergy'"):
        validate_claim(claim(dimensions=("synergy",)))


def test_repeated_dimension_is_rejected() -> None:
    """Dimensions are a set written as a tuple, so repeats are a typo."""
    with pytest.raises(CoverageClaimError, match="repeat a member"):
        validate_claim(claim(dimensions=("on_hit", "on_hit")))


def test_utility_claim_with_no_dimension_is_rejected() -> None:
    """A utility claim naming no outcome claims nothing."""
    with pytest.raises(CoverageClaimError, match="names no outcome"):
        validate_claim(claim(lane="utility", dimensions=()))


def test_issue_refs_on_a_negative_claim_are_rejected() -> None:
    """One home per claim: a refusal's refs live on its Absence."""
    with pytest.raises(CoverageClaimError, match="issue refs on its Absence"):
        validate_claim(claim(status="blocked", evidence=(ABSENCE,), issue_refs=(40,)))


def test_non_positive_issue_ref_is_rejected() -> None:
    """An issue number is a positive integer, never a flag."""
    with pytest.raises(CoverageClaimError, match="not a positive issue number"):
        validate_claim(claim(issue_refs=(0,)))


def test_blank_unreachable_reason_is_rejected() -> None:
    """Either say why nothing reaches the claim, or leave it empty."""
    with pytest.raises(CoverageClaimError, match="unreachable_reason is blank"):
        validate_claim(claim(unreachable_reason="  "))


# ---------------------------------------------------------------------------
# Table-level shape
# ---------------------------------------------------------------------------


def test_key_disagreeing_with_its_claim_is_rejected() -> None:
    """A claim filed against an item it says nothing about."""
    entry = claim()
    with pytest.raises(CoverageClaimError, match="disagrees with the claim"):
        validate_claim_table({("item", "Abyssal Mask", "attacker"): entry})


def test_key_that_is_not_a_triple_is_rejected() -> None:
    """The key is ``(subject_kind, subject, lane)`` and nothing shorter."""
    with pytest.raises(CoverageClaimError, match="is not a .subject_kind"):
        validate_claim_table({"Imperial Mandate": claim()})


# ---------------------------------------------------------------------------
# Evidence-member shapes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("member", "message"),
    [
        pytest.param(
            Symbol(path="damage", role="pair_engine"),
            "is not a dotted path",
            id="symbol-single-segment-path",
        ),
        pytest.param(
            Symbol(path="damage._apply command_amp", role="pair_engine"),
            "carries whitespace",
            id="symbol-path-with-whitespace",
        ),
        pytest.param(
            Symbol(path="damage.9lives", role="pair_engine"),
            "is not a dotted path",
            id="symbol-non-identifier-segment",
        ),
        pytest.param(
            Symbol(path="damage._apply_command_amp", role="referee"),
            "Symbol.role 'referee'",
            id="symbol-unknown-role",
        ),
        pytest.param(
            PacketSource(source=""),
            "PacketSource.source must be a non-blank",
            id="packet-source-empty",
        ),
        pytest.param(
            PacketSource(source="Imperial Mandate — {item}"),
            "named or unbalanced brace",
            id="packet-source-named-fstring-slot",
        ),
        pytest.param(
            PacketSource(source="Imperial Mandate — {"),
            "named or unbalanced brace",
            id="packet-source-unbalanced-brace",
        ),
        pytest.param(
            PairedSides(mechanic="command", owner_policy="owner_skips_holder"),
            "is not '<owner_slug>.<effect_slug>'",
            id="paired-sides-no-dot",
        ),
        pytest.param(
            PairedSides(
                mechanic="items.imperial_mandate.command",
                owner_policy="owner_skips_holder",
            ),
            "is not '<owner_slug>.<effect_slug>'",
            id="paired-sides-two-dots",
        ),
        pytest.param(
            PairedSides(
                mechanic="imperial mandate.command", owner_policy="owner_skips_holder"
            ),
            "is not a plain identifier",
            id="paired-sides-non-identifier-owner",
        ),
        pytest.param(
            PairedSides(mechanic="imperial_mandate.command", owner_policy="both"),
            "PairedSides.owner_policy 'both'",
            id="paired-sides-unknown-owner-policy",
        ),
        pytest.param(
            EffectKey(registry="ITEM_STATS", item="Imperial Mandate", key="amp"),
            "EffectKey.registry 'ITEM_STATS'",
            id="effect-key-unknown-registry",
        ),
        pytest.param(
            EffectKey(registry="ITEM_EFFECTS", item="Imperial Mandate", key="0.07"),
            "never its value",
            id="effect-key-is-a-number",
        ),
        pytest.param(
            EffectKey(registry="ITEM_EFFECTS", item="", key="amp"),
            "EffectKey.item must be a non-blank",
            id="effect-key-blank-item",
        ),
        pytest.param(
            EffectKey(registry="ITEM_EFFECTS", item="Imperial Mandate", key="amp pct"),
            "carries whitespace",
            id="effect-key-with-whitespace",
        ),
        pytest.param(
            EffectTag(tag="on.hit", handler="damage.apply_on_hit"),
            "is not a plain identifier",
            id="effect-tag-not-an-identifier",
        ),
        pytest.param(
            EffectTag(tag="on_hit", handler="damage"),
            "is not a dotted path",
            id="effect-tag-handler-single-segment",
        ),
        pytest.param(
            OptionSchema(item="", option="rod_of_ages_stacks"),
            "OptionSchema.item must be a non-blank",
            id="option-schema-blank-item",
        ),
        pytest.param(
            OptionSchema(item="Rod of Ages", option="rod-of-ages-stacks"),
            "is not a plain identifier",
            id="option-schema-non-identifier-option",
        ),
        pytest.param(
            TestRef(node_id="test_command_amp_roster"),
            "is not '<path>.py::<node>'",
            id="test-ref-not-a-node-id",
        ),
        pytest.param(
            TestRef(node_id="tests/test_command_amp_roster::test_priced"),
            "is not '<path>.py::<node>'",
            id="test-ref-path-is-not-a-module",
        ),
        pytest.param(
            TestRef(node_id="tests/test_command_amp_roster.py::"),
            "is not '<path>.py::<node>'",
            id="test-ref-empty-node",
        ),
        pytest.param(
            TestRef(node_id="tests/test_a.py::test_x or test_y"),
            "carries whitespace",
            id="test-ref-is-a-k-expression",
        ),
        pytest.param(
            TestRef(node_id="tests/test_a.py::test_x[Ardent Censer"),
            "never closes it",
            id="test-ref-unclosed-parametrization",
        ),
        pytest.param(
            SourceRef(url="http://wiki.leagueoflegends.com/en-us/X", revision_id=1),
            "is not an https url",
            id="source-ref-not-https",
        ),
        pytest.param(
            SourceRef(url="https://", revision_id=1),
            "is not an https url",
            id="source-ref-bare-scheme",
        ),
        pytest.param(
            SourceRef(url="https://wiki.leagueoflegends.com/en-us/X", revision_id=0),
            "not a positive revision",
            id="source-ref-zero-revision",
        ),
        pytest.param(
            SourceRef(url="https://wiki.leagueoflegends.com/en-us/X", revision_id="7"),
            "is not an integer",
            id="source-ref-revision-is-a-string",
        ),
        pytest.param(
            SourceRef(url="https://wiki.leagueoflegends.com/en-us/X", revision_id=True),
            "is not an integer",
            id="source-ref-revision-is-a-bool",
        ),
        pytest.param(
            Absence(reason="   ", issue_refs=(40,)),
            "Absence.reason must be a non-blank",
            id="absence-blank-reason",
        ),
        pytest.param(
            Absence(reason="Not modelled yet.", issue_refs=()),
            "Absence.issue_refs is empty",
            id="absence-no-issue-refs",
        ),
        pytest.param(
            Absence(reason="Not modelled yet.", issue_refs=(-3,)),
            "not a positive issue number",
            id="absence-negative-issue-ref",
        ),
    ],
)
def test_malformed_evidence_member_is_rejected(member, message: str) -> None:
    """Each evidence kind's shape rule, reached by the case that breaks it."""
    with pytest.raises(CoverageClaimError, match=message):
        validate_evidence(member, claim="item:Imperial Mandate@attacker")


# ---------------------------------------------------------------------------
# The matrix and the union as declarations
# ---------------------------------------------------------------------------


def test_the_evidence_union_is_the_closed_nine() -> None:
    """Nine members, and ``StreamMembership`` deliberately absent.

    It would have resolved against five hand name sets Phase 2 deleted, so it
    could only ever have been evidence for something that no longer exists.
    """
    assert EVIDENCE_KINDS == {
        "Symbol",
        "PacketSource",
        "PairedSides",
        "EffectKey",
        "EffectTag",
        "OptionSchema",
        "TestRef",
        "SourceRef",
        "Absence",
    }
    assert len(EVIDENCE_TYPES) == len(EVIDENCE_KINDS)
    assert "StreamMembership" not in EVIDENCE_KINDS


def test_every_legal_cell_has_a_coherent_policy() -> None:
    """The matrix is total over the legal cells and never self-contradicts."""
    for lane in sorted(LANES):
        for status in sorted(LANE_STATUSES[lane]):
            policy = status_policy(lane, status)
            assert policy.required <= EVIDENCE_KINDS
            assert policy.forbidden <= EVIDENCE_KINDS
            assert not policy.required & policy.forbidden
            assert policy.min_count >= len(policy.required)


def test_the_matrix_refuses_every_illegal_cell() -> None:
    """The accessor is a guard in its own right, not only through a claim."""
    for lane in sorted(LANES):
        for status in sorted(CLAIM_STATUSES - LANE_STATUSES[lane]):
            with pytest.raises(CoverageClaimError, match="not claimable on the"):
                status_policy(lane, status)
    with pytest.raises(CoverageClaimError, match="lane 'jungle'"):
        status_policy("jungle", "modeled_effect")
    with pytest.raises(CoverageClaimError, match="status 'probably_fine'"):
        status_policy("attacker", "probably_fine")


def test_every_status_is_claimable_on_some_lane() -> None:
    """No orphan status: the vocabulary and the lane table agree both ways."""
    claimable = set().union(*LANE_STATUSES.values())
    assert claimable == CLAIM_STATUSES
    assert set(LANE_STATUSES) == LANES


def test_a_negative_cell_ignores_the_lane_overlay() -> None:
    """A refusal on the support-packet lane still owes only its Absence."""
    for status in sorted(NEGATIVE_STATUSES):
        assert status_policy("support_packet", status) == status_policy(
            "attacker", status
        )


def test_the_support_packet_overlay_adds_exactly_one_requirement() -> None:
    """Positive cells on that lane gain a PacketSource and one to the floor."""
    base = status_policy("attacker", "modeled_effect")
    overlaid = status_policy("support_packet", "modeled_effect")
    assert overlaid.required == base.required | {"PacketSource"}
    assert overlaid.min_count == base.min_count + 1
    assert overlaid.forbidden == base.forbidden


def test_utility_dimensions_equal_the_measured_set() -> None:
    """Set equality against the dict it was measured from — never a count.

    ``item_coverage._UTILITY_DIMENSIONS`` maps item names to dimension
    tuples, so its key count and its distinct-value count are different
    numbers and either is a plausible-looking wrong answer.  Pinning the set
    is what makes this checkable at all.
    """
    measured = {
        dimension
        for dimensions in _UTILITY_DIMENSIONS.values()
        for dimension in dimensions
    }
    assert UTILITY_DIMENSIONS == measured


# ---------------------------------------------------------------------------
# The load tier's own boundary (D-20, criterion 2)
# ---------------------------------------------------------------------------

_STDLIB_IMPORTS = frozenset({"keyword", "collections.abc", "dataclasses", "typing"})
_FORBIDDEN_CALLS = frozenset({"open", "exec", "eval", "compile", "__import__"})


def _code_only(text: str) -> str:
    """Source with every comment and string literal removed.

    Prose may name ``data/`` and ``src.calculator`` — it does, in the module
    docstring that explains why neither is reachable — so the textual checks
    below have to run over code and nothing else.
    """
    return " ".join(
        token.string
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type not in (tokenize.STRING, tokenize.COMMENT)
    )


def test_the_load_gate_imports_nothing_and_reads_nothing() -> None:
    """No package import, no filesystem, no ``data/`` — asserted over source.

    The tier boundary is the ruling (D-20), and a load gate that quietly
    grew an import would be a startup cost on every request plus a bypass of
    the caching layer.  Checking it over the AST rather than by reading is
    what keeps it true on the commit that breaks it.
    """
    text = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "the load gate declares no relative import"
            imported.add(node.module or "")
    assert imported <= _STDLIB_IMPORTS, f"unexpected imports: {sorted(imported)}"

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called & _FORBIDDEN_CALLS

    code = _code_only(text)
    assert "src.calculator" not in code
    assert "data/" not in code


def test_claim_lane_is_exported_here_and_is_not_spelled_lane() -> None:
    """D-45: two lane vocabularies, never both spelled ``Lane``."""
    assert "ClaimLane" in coverage_evidence.__all__
    assert not hasattr(coverage_evidence, "Lane")


# ---------------------------------------------------------------------------
# The classifier chain as data
# ---------------------------------------------------------------------------


def rung(**overrides) -> PrecedenceRule:
    """A valid attacker container rung, with fields overridden."""
    fields = {
        "rule_id": "attacker.reviewed_stats_only",
        "lane": "attacker",
        "kind": "container",
        "keys_on": ("item_coverage._REVIEWED_STATS_ONLY",),
        "items": (),
        "effect_types": (),
        "negated": False,
        "status": "stats_only",
    }
    fields.update(overrides)
    return PrecedenceRule(**fields)


TERMINAL = rung(
    rule_id="attacker.unreviewed_fixture",
    kind="terminal",
    keys_on=(),
    status="review_pending",
)


@pytest.mark.parametrize(
    "node_id",
    [
        "tests/test_coverage_claims.py::test_a_claim[Ardent Censer]",
        "tests/test_coverage_claims.py::test_a_claim[Jak'Sho, The Protean]",
        "tests/test_x.py::TestGroup::test_case[Rylai's Crystal Scepter-3]",
    ],
    ids=["space", "comma and apostrophe", "class and compound id"],
)
def test_a_parametrization_id_may_carry_the_spaces_pytest_puts_in_it(
    node_id: str,
) -> None:
    """The ``[...]`` suffix is a parameter value, not a location.

    pytest builds it out of the parameter verbatim, so an item name lands in
    it spaces and all.  Rejecting those would make every claim backed by a
    per-item parametrized node unauthorable, which is precisely how the
    dynamic families are meant to be backed.
    """
    validate_evidence(TestRef(node_id=node_id), claim="item:X@attacker")


def test_a_well_formed_ladder_validates() -> None:
    """One rung per shape, terminal last — the case every negative deviates from."""
    validate_precedence((rung(), TERMINAL))


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        (rung(lane="jungle"), "lane 'jungle'"),
        (rung(status="modeled"), "not claimable on the 'attacker' lane"),
        (rung(kind="vibes"), "kind 'vibes'"),
        (rung(keys_on=()), "reads 1 dotted path"),
        (rung(kind="named_item", keys_on=()), "pins an item and names none"),
        (rung(effect_types=("burn",)), "only an 'effect_type' rung"),
        (
            rung(kind="effect_type", keys_on=("item_effects.ITEM_EFFECTS",)),
            "names no type",
        ),
        (rung(negated=True), "only a 'predicate' rung may be negated"),
        (rung(rule_id="attacker reviewed"), "carries whitespace"),
        (rung(keys_on=("REVIEWED",)), "is not a dotted path"),
    ],
    ids=[
        "lane",
        "status off its lane",
        "kind",
        "path count",
        "pinned with no item",
        "effect types on the wrong kind",
        "effect type rung with no type",
        "negated membership",
        "rule id",
        "bare path",
    ],
)
def test_a_malformed_rung_is_rejected(rule: PrecedenceRule, message: str) -> None:
    """Each rung rule fails on its own, named in the message."""
    with pytest.raises(CoverageClaimError, match=message):
        validate_precedence_rule(rule)


def test_a_ladder_with_no_terminal_rung_is_rejected() -> None:
    """A classifier that can fall off its end classifies nothing."""
    with pytest.raises(CoverageClaimError, match="declares 0 terminal rungs"):
        validate_precedence((rung(),))


def test_a_ladder_whose_terminal_rung_is_not_last_is_rejected() -> None:
    """Every rung after the terminal one is unreachable by construction."""
    with pytest.raises(CoverageClaimError, match="ends on"):
        validate_precedence((TERMINAL, rung()))


def test_a_repeated_rule_id_is_rejected() -> None:
    """The id is a claim key; two rungs sharing one is two claims in one."""
    with pytest.raises(CoverageClaimError, match="is repeated"):
        validate_precedence((rung(), rung(), TERMINAL))


def test_the_live_ladder_validates_and_covers_both_classifier_lanes() -> None:
    """The declaration in ``item_coverage`` is checked at import; this says so."""
    validate_precedence(PRECEDENCE)
    assert {rule.lane for rule in PRECEDENCE} == {"attacker", "target"}
    assert len({rule.rule_id for rule in PRECEDENCE}) == len(PRECEDENCE)
