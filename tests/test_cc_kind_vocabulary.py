"""One crowd-control kind vocabulary, one home (F-9, issue #212).

``ability_spec.CC_KIND_VOCABULARY`` is the only set that says what a
champion module may author as a ``cc_kind``.  Every other crowd-control
set in the calculator is a *classification over* it — immobilizing vs
not, action-blocking vs not, known-to-the-cleanse vs not — and each one
must stay total and closed over the vocabulary.

They did not.  ``crowd_control_eligibility.KNOWN_CONTROL_KINDS`` was a
second hand-written vocabulary: it declared ``disarm`` and ``ground``,
which no module can author, and omitted ``berserk``, ``cripple``,
``flee``, ``pull``, ``snare`` and ``stasis``, which modules do author
(Renata R, Malphite E, Pyke/Diana/Sett/Rell/Yone/Mordekaiser/Kled, Bard
R).  An omitted kind classified ``unknown`` and every cleanse touching it
failed closed, so a Quicksilver Sash could not remove a root spelled
``snare`` and Milio's Breath of Life could not touch a Renata berserk.

The assertions below are the structural guard: the classifications are
derived in source, and a future hand-written member fails here.
"""

import pytest

from src.calculator.ability_spec import (
    ACTION_BLOCKING_CC_KINDS,
    CC_KIND_VOCABULARY,
    DISPLACEMENT_CC_KINDS,
    IMMOBILIZING_CC_KINDS,
    NO_CONTROL_KIND,
    NON_BLOCKING_CC_KINDS,
    NON_IMMOBILIZING_CC_KINDS,
    cc_kind_reviewed,
)
from src.calculator.cleanse_eligibility import (
    CHAMPION_CLEANSE_DECLARATIONS,
    ITEM_CLEANSE_DECLARATIONS,
    NEVER_CLEANSABLE_CONTROL_KINDS,
    TOOLTIP_ONLY_CONTROL_KINDS,
    resolve_excluded_kinds,
)
from src.calculator.crowd_control_eligibility import (
    KNOWN_CONTROL_KINDS,
    classify_control,
)


class _Action:  # pylint: disable=too-few-public-methods
    """The minimum an action needs to be classified."""

    def __init__(self, cc_kind: str) -> None:
        self.cc_kind = cc_kind
        self.source_key = "probe"
        self.time = 0.0


ALL_DECLARATIONS = (
    *ITEM_CLEANSE_DECLARATIONS.values(),
    *CHAMPION_CLEANSE_DECLARATIONS.values(),
)


class TestTheVocabularyIsTheOnlyVocabulary:
    """No second set of kinds; every classification is over this one."""

    def test_the_cleanse_knows_exactly_what_a_module_can_author(self):
        """The F-9 drift: ``KNOWN_CONTROL_KINDS`` is the vocabulary.

        ``"none"`` is a reviewed *absence* of control (it reaches the
        classifier as the empty kind), so it is the one member the
        control classifier does not carry.
        """
        assert CC_KIND_VOCABULARY - {NO_CONTROL_KIND} == KNOWN_CONTROL_KINDS

    def test_no_classification_names_a_kind_outside_the_vocabulary(self):
        for name, kinds in (
            ("ACTION_BLOCKING_CC_KINDS", ACTION_BLOCKING_CC_KINDS),
            ("DISPLACEMENT_CC_KINDS", DISPLACEMENT_CC_KINDS),
            ("IMMOBILIZING_CC_KINDS", IMMOBILIZING_CC_KINDS),
            ("NON_IMMOBILIZING_CC_KINDS", NON_IMMOBILIZING_CC_KINDS),
            ("NON_BLOCKING_CC_KINDS", NON_BLOCKING_CC_KINDS),
            ("NEVER_CLEANSABLE_CONTROL_KINDS", NEVER_CLEANSABLE_CONTROL_KINDS),
        ):
            stray = sorted(set(kinds) - CC_KIND_VOCABULARY)
            assert stray == [], (
                f"{name} names {stray}, which no champion module can author "
                "— the one home is ability_spec.CC_KIND_VOCABULARY"
            )

    def test_blocking_and_soft_partition_the_known_kinds(self):
        assert ACTION_BLOCKING_CC_KINDS | NON_BLOCKING_CC_KINDS == KNOWN_CONTROL_KINDS
        assert frozenset() == ACTION_BLOCKING_CC_KINDS & NON_BLOCKING_CC_KINDS

    def test_the_action_blocking_half_is_derived_from_the_immobilizes(self):
        """Every immobilize blocks actions; polymorph and berserk block
        them without immobilizing.  Re-spelling the fifteen was how the two
        drifted."""
        assert (
            IMMOBILIZING_CC_KINDS
            | {
                "polymorph",
                "berserk",
            }
            == ACTION_BLOCKING_CC_KINDS
        )

    def test_immobilizing_and_non_immobilizing_partition_the_vocabulary(self):
        assert (
            IMMOBILIZING_CC_KINDS | NON_IMMOBILIZING_CC_KINDS | {NO_CONTROL_KIND}
            == CC_KIND_VOCABULARY
        )
        assert frozenset() == IMMOBILIZING_CC_KINDS & NON_IMMOBILIZING_CC_KINDS

    @pytest.mark.parametrize("kind", sorted(CC_KIND_VOCABULARY - {NO_CONTROL_KIND}))
    def test_every_authorable_kind_classifies(self, kind):
        """No authorable kind reaches a consumer as ``unknown``."""
        profile = classify_control(_Action(kind))
        assert profile.unknown is False
        assert profile.kind == kind
        assert profile.blocking is (kind in ACTION_BLOCKING_CC_KINDS)

    def test_a_kind_no_module_can_author_still_fails_closed(self):
        profile = classify_control(_Action("mesmerize"))
        assert profile.unknown is True
        assert profile.blocking is False

    @pytest.mark.parametrize("kind", sorted(CC_KIND_VOCABULARY))
    def test_every_vocabulary_member_certifies_its_row(self, kind):
        """``cc_reviewed`` asks whether a reviewer classified the row, and
        every vocabulary member IS that classification — ``"none"``
        included, which certifies while narrowing nothing.  Answering it
        with ``ACTION_BLOCKING_CC_KINDS`` instead left a reviewed blind,
        cripple or silence publishing as unreviewed, and widened silently
        the moment that set grew."""
        assert cc_kind_reviewed(kind) is True
        assert cc_kind_reviewed(f"  {kind.upper()} ") is True

    @pytest.mark.parametrize("kind", [None, "", "   ", "mesmerize", "ground"])
    def test_nothing_outside_the_vocabulary_certifies_a_row(self, kind):
        assert cc_kind_reviewed(kind) is False


class TestCleanseCarveOutsSpeakTheVocabulary:
    """A carve-out naming a kind nothing can author removes nothing."""

    @pytest.mark.parametrize("declaration", ALL_DECLARATIONS, ids=lambda d: d["item"])
    def test_every_excluded_kind_is_authorable_or_a_declared_tooltip_word(
        self, declaration
    ):
        stray = sorted(
            set(declaration["excluded_control_kinds"])
            - CC_KIND_VOCABULARY
            - TOOLTIP_ONLY_CONTROL_KINDS
        )
        assert stray == [], (
            f"{declaration['item']} carves out {stray}: neither a kind a "
            "module can author nor a declared tooltip-only word"
        )

    def test_an_airborne_carve_out_reaches_every_subtype_a_module_authors(self):
        """``airborne`` is the wiki's umbrella and the subtypes are what
        modules author, so a declaration naming any part of it must protect
        all of it — otherwise Quicksilver removes a knockup it cannot
        remove a knockback from."""
        for declaration in ALL_DECLARATIONS:
            declared = frozenset(declaration["excluded_control_kinds"])
            if not declared & DISPLACEMENT_CC_KINDS:
                continue
            assert resolve_excluded_kinds(declared) >= DISPLACEMENT_CC_KINDS, (
                f"{declaration['item']} carves out {sorted(declared)} but the "
                "resolver leaves part of the Airborne class cleansable"
            )

    def test_the_umbrella_is_a_classification_over_the_vocabulary(self):
        """A forced displacement is an immobilize, so the umbrella is a
        subset of that classification rather than a list of its own."""
        assert DISPLACEMENT_CC_KINDS <= IMMOBILIZING_CC_KINDS
