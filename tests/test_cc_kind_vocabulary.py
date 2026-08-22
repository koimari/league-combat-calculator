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
    NON_IMMOBILIZING_CC_KINDS,
    NO_CONTROL_KIND,
)
from src.calculator.cleanse_eligibility import (
    CHAMPION_CLEANSE_DECLARATIONS,
    ITEM_CLEANSE_DECLARATIONS,
    NEVER_CLEANSABLE_CONTROL_KINDS,
    TOOLTIP_ONLY_CONTROL_KINDS,
)
from src.calculator.crowd_control_eligibility import (
    CONTROL_BLOCKING_KINDS,
    CONTROL_SOFT_KINDS,
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
        assert KNOWN_CONTROL_KINDS == CC_KIND_VOCABULARY - {NO_CONTROL_KIND}

    def test_no_classification_names_a_kind_outside_the_vocabulary(self):
        for name, kinds in (
            ("ACTION_BLOCKING_CC_KINDS", ACTION_BLOCKING_CC_KINDS),
            ("DISPLACEMENT_CC_KINDS", DISPLACEMENT_CC_KINDS),
            ("IMMOBILIZING_CC_KINDS", IMMOBILIZING_CC_KINDS),
            ("NON_IMMOBILIZING_CC_KINDS", NON_IMMOBILIZING_CC_KINDS),
            ("CONTROL_BLOCKING_KINDS", CONTROL_BLOCKING_KINDS),
            ("CONTROL_SOFT_KINDS", CONTROL_SOFT_KINDS),
            ("NEVER_CLEANSABLE_CONTROL_KINDS", NEVER_CLEANSABLE_CONTROL_KINDS),
        ):
            stray = sorted(set(kinds) - CC_KIND_VOCABULARY)
            assert stray == [], (
                f"{name} names {stray}, which no champion module can author "
                "— the one home is ability_spec.CC_KIND_VOCABULARY"
            )

    def test_blocking_and_soft_partition_the_known_kinds(self):
        assert CONTROL_BLOCKING_KINDS | CONTROL_SOFT_KINDS == KNOWN_CONTROL_KINDS
        assert CONTROL_BLOCKING_KINDS & CONTROL_SOFT_KINDS == frozenset()

    def test_immobilizing_and_non_immobilizing_partition_the_vocabulary(self):
        assert (
            IMMOBILIZING_CC_KINDS | NON_IMMOBILIZING_CC_KINDS | {NO_CONTROL_KIND}
            == CC_KIND_VOCABULARY
        )
        assert IMMOBILIZING_CC_KINDS & NON_IMMOBILIZING_CC_KINDS == frozenset()

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

    def test_the_displacement_umbrella_covers_every_displacement_kind(self):
        """``airborne`` is the wiki's umbrella; the subtypes are what
        modules actually author, so a carve-out naming the umbrella must
        reach all four."""
        assert DISPLACEMENT_CC_KINDS == frozenset(
            {"airborne", "knockback", "knockup", "pull"}
        )
