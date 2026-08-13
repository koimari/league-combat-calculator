"""H5 — the compiled score kernel's timed, typed damage modifiers.

The umbrella records H5 as **SCOPED**: the compiled score kernel is taught
timed, typed damage modifiers, as its own stage after Phase 4's S7, **with
its own equivalence fixture**.  This file is that fixture, and it is the
condition on which the stage may ship at all — a compiled lane that prices a
build differently from the receipt walk is the divergent lane the stage is
forbidden to land.

It is deliberately the same idiom as :mod:`tests.test_survival_kernel` and
deliberately not the same file.  Same idiom, because that suite already
knows how to run one fight down both walks and how to derive what it owes a
fixture from the registries rather than from a list somebody maintains; its
harness is imported here rather than re-typed, so the two suites cannot
disagree about what "the same fight" means.  Not the same file, because the
two ask different questions: that suite pins the adapters over the mechanics
the kernel already staged, and this one pins the mechanics the kernel
learned to stage, whose population is read from the
``damage_modifier`` producer table.

**What the stage actually changed, and therefore what is asserted here.**
The walk never lacked the transition — ``_apply_damage_modifier`` and
``_apply_cross_participant_modifiers`` are kernel functions both ledgers have
always driven.  What refused was compilation, in three places that had to
move together, and each has its own test below:

1. ``unrepresentable_template_receipt`` rejected the *kind* categorically;
2. the one ``SurvivalAction`` constructor had no armed-modifier branch;
3. the compiled damage rows carried neither delivery flag nor either
   resistance baseline, so a modifier restricted by attack class (D-04)
   reached only the rows whose ``source_key`` happened to be
   ``auto_attacks``, and a resistance reduction re-priced nothing.

Point 3 is the one worth reading twice: it was **inert** while no modifier
could compile, and it is exactly the shape S7's own comment warns about —
admitting a kind to compilation lands more than one behaviour change.
"""

from dataclasses import dataclass

import pytest

from src.calculator.item_support_effects import _declared_authorities, producer_item
from src.calculator.program.build import arming_stacking
from src.calculator.program.compile import (
    WalkCompiler,
    action_from_event,
    modifier_delivery_receipt,
    pair_resistance_baselines,
)
from src.calculator.survival import (
    ActionKind,
    SurvivalAction,
    support_transition_rank,
)
from src.calculator.survival.compile import (
    UncompilableActionError,
    unrepresentable_modifier_receipt,
    unrepresentable_template_receipt,
)
from src.calculator.trigger_stream import HolderStacking

from tests.test_survival_kernel import (
    Holder,
    KernelFixture,
    _differing_leaves,
    _item,
    _reached_keys,
)

# ---------------------------------------------------------------------------
# What the compiled path refuses, read from the declaration
# ---------------------------------------------------------------------------


def aura_armed_producers() -> frozenset[str]:
    """Producers whose arming dedupe the compiled panels cannot answer.

    Read from ``arming_stacking()`` — the projection of every dual-sided
    mechanic's declared :class:`HolderStacking` — and never typed, so a
    second ``IDEMPOTENT_AURA`` mechanic joins this set on the commit that
    declares it rather than on the commit somebody remembers.

    An aura's key is ``(subject, mechanic)``: two holders curse one enemy
    once, and answering that needs one ledger over the whole composed
    fight.  The compiled path has no such moment — the roster panel is
    compiled once per search and the candidate's actions once per
    evaluation — so it declines instead of arming a second curse the walk
    would have dropped.
    """
    return frozenset(
        source
        for source, (_mechanic, stacking) in arming_stacking().items()
        if stacking is HolderStacking.IDEMPOTENT_AURA
    )


def compilable_producers() -> frozenset[str]:
    """Every ``damage_modifier`` producer the compiled kernel now stages.

    Both halves derived: the producer table is
    ``item_support_effects._declared_authorities()`` — the same table
    :mod:`tests.test_survival_kernel` reads for its own coverage — and the
    exclusion is the aura set above.  A seventh producer therefore becomes
    a required fixture here on the commit that adds it.
    """
    return frozenset(_declared_authorities()) - aura_armed_producers()


# ---------------------------------------------------------------------------
# The fixture table — one build per producer group, on each side
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AmpFixture:
    """One compiled-vs-receipt scenario, and the refusals it is allowed.

    ``expected_receipts`` is the load-bearing field and the reason this
    table does not simply reuse ``_assert_rung``.  That helper asserts a
    panel exists, which a candidate-local fallback also satisfies; here the
    *named* receipt of every refusal the score path raised is captured and
    compared as a set.  An empty set is the strong claim — this build
    compiled with nothing declined — and a non-empty one names the
    mechanic, so a build that started falling back for a new reason fails
    with that reason printed rather than passing as "still has panels".
    """

    name: str
    items: tuple[str, ...]
    side: str
    champion: str
    role: str = "mid"
    expected_receipts: frozenset[str] = frozenset()
    invariant: bool = False

    def kernel_fixture(self) -> KernelFixture:
        """The shared harness's fixture for this build, holder side applied."""
        enemies = (Holder("Aatrox", role="top"),)
        if self.side == "candidate":
            return KernelFixture(
                name=self.name,
                champion=self.champion,
                items=self.items,
                enemies=enemies,
                allies=(Holder("Ashe", role="bottom"),),
                role=self.role,
            )
        return KernelFixture(
            name=self.name,
            champion="Ahri",
            items=(),
            enemies=enemies,
            allies=(
                Holder(
                    self.champion,
                    items=self.items,
                    role=self.role,
                    ally_effects=True,
                ),
            ),
        )


_COMMAND_BUILD = ("Imperial Mandate",)
_SCAN_BUILD = ("Black Cleaver", "Bloodletter's Curse", "Bloodsong")
_BUBBLE_BUILD = ("Dream Maker",)
_AURA_BUILD = ("Abyssal Mask",)

# Dream Maker's own build declines for a mechanic that is *not* an amp:
# Help, Pix! is an on-hit magic grant, and ``support_kind=on_hit_magic`` is
# the standing refusal for that kind.  It is named here rather than removed
# from the build because the Blue Dream Bubble packet rides the same item,
# and a fixture that equipped the producer without reaching it would prove
# nothing (the point ``_reached_keys`` exists to make).
_ON_HIT_REFUSAL = frozenset({"support_kind=on_hit_magic"})
_AURA_REFUSAL = frozenset({"modifier_aura_arming=Abyssal Mask — Unmake"})

AMP_FIXTURES = (
    AmpFixture("command_candidate", _COMMAND_BUILD, "candidate", "Pantheon", "support"),
    AmpFixture("command_ally", _COMMAND_BUILD, "ally", "Pantheon", "support"),
    AmpFixture("scan_candidate", _SCAN_BUILD, "candidate", "Ahri"),
    AmpFixture("scan_ally", _SCAN_BUILD, "ally", "Pantheon", "support"),
    AmpFixture(
        "bubble_candidate",
        _BUBBLE_BUILD,
        "candidate",
        "Lulu",
        "support",
        expected_receipts=_ON_HIT_REFUSAL,
    ),
    AmpFixture(
        "bubble_ally",
        _BUBBLE_BUILD,
        "ally",
        "Lulu",
        "support",
        expected_receipts=_ON_HIT_REFUSAL,
        invariant=True,
    ),
    AmpFixture(
        "aura_candidate",
        _AURA_BUILD,
        "candidate",
        "Ahri",
        expected_receipts=_AURA_REFUSAL,
    ),
    AmpFixture(
        "aura_ally",
        _AURA_BUILD,
        "ally",
        "Pantheon",
        "support",
        expected_receipts=_AURA_REFUSAL,
        invariant=True,
    ),
)


def _walk_both_capturing(fixture: AmpFixture):
    """``(receipt, score, context, receipts)`` for one amp fixture.

    ``receipts`` is every ``UncompilableActionError`` the score path raised,
    captured at the one site that catches them, so a refusal is observed by
    name instead of being inferred from a panel's existence.
    """
    # Imported inside the helper: patching the module attribute has to
    # happen against the live module object the caller will execute.
    from src.calculator import participant_timeline as timeline

    raised: set[str] = set()
    original = timeline._score_with_search_context

    def capturing(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except UncompilableActionError as exc:
            raised.add(exc.receipt)
            raise

    timeline._score_with_search_context = capturing
    try:
        legacy, fast, context = fixture.kernel_fixture().walk_both()
    finally:
        timeline._score_with_search_context = original
    return legacy, fast, context, frozenset(raised)


@pytest.mark.parametrize(
    "fixture", AMP_FIXTURES, ids=[fixture.name for fixture in AMP_FIXTURES]
)
def test_the_compiled_amp_lane_equals_the_receipt_walk(fixture):
    """The whole scoring receipt, both walks, for every amp fixture.

    This is the stage's ship condition.  The receipt walk is the authority;
    the compiled lane must reproduce it leaf for leaf, and the leaves that
    differ are printed rather than counted so a failure names the mechanic
    instead of a magnitude.
    """
    legacy, fast, context, receipts = _walk_both_capturing(fixture)
    assert _differing_leaves(legacy, fast) == (), (
        f"{fixture.name}: the compiled lane diverged from the receipt walk. "
        "A divergent compiled lane may not ship (H5)."
    )
    assert fast == legacy
    assert receipts == fixture.expected_receipts, (
        f"{fixture.name}: the score path's named refusals moved. "
        f"expected {sorted(fixture.expected_receipts)}, got {sorted(receipts)}"
    )
    assert context.uncompilable is fixture.invariant


def test_every_modifier_producer_is_reached_from_both_sides():
    """The required set is derived and every producer has both fixtures.

    Coverage is credited off the *receipt* walk — the authority the compiled
    lane must reproduce — and attributed by each packet's own attacker, so a
    fixture that equips a producer's item without ever firing its packet
    contributes nothing.  A seventh ``damage_modifier`` producer therefore
    fails here on the commit that adds it.
    """
    required = frozenset(_declared_authorities())
    assert required, "the producer table may not be empty"
    candidate: set[str] = set()
    ally: set[str] = set()
    for fixture in AMP_FIXTURES:
        reached_candidate, reached_ally = _reached_keys(fixture.kernel_fixture())
        candidate |= reached_candidate
        ally |= reached_ally
    missing = sorted(
        (producer, side)
        for producer in required
        for side, reached in (("candidate", candidate), ("ally", ally))
        if producer not in reached
    )
    assert not missing, f"producers no amp fixture reaches: {missing}"


def test_the_aura_is_the_only_producer_the_compiled_lane_declines():
    """Which producers compile is a declaration, not a list.

    Both sides of the equality are derived: the refusal set from the
    declared :class:`HolderStacking`, and the fixtures' own expectation
    from the receipts they actually raise.  Nothing here names an item.
    """
    aura = aura_armed_producers()
    assert aura, "the aura set may not be empty while a mechanic declares one"
    assert compilable_producers() == frozenset(_declared_authorities()) - aura
    declined = {
        receipt.split("=", 1)[1]
        for fixture in AMP_FIXTURES
        for receipt in fixture.expected_receipts
        if receipt.startswith("modifier_aura_arming=")
    }
    assert declined == aura
    # And the item every one of those producers hangs on has a fixture on
    # both sides, so the refusal is exercised rather than merely declared.
    assert {producer_item(source) for source in aura} <= {
        name for fixture in AMP_FIXTURES for name in fixture.items
    }


# ---------------------------------------------------------------------------
# The three compilation changes, each pinned on its own
# ---------------------------------------------------------------------------


def _template(**overrides):
    """One armed modifier packet, in the shape the producers author."""
    from src.calculator.ability_spec import AttackClass, DamageClass

    template = {
        "time": 1.0,
        "kind": "damage_modifier",
        "amount": 0.07,
        "duration": 4.0,
        "source": "Test Producer — Amp",
        "source_key": "Test Producer — Amp",
        "attacker": "ally:Holder",
        "target": "enemy:Subject",
        "multiplier": 1.07,
        "all_sources": True,
        "owner": "ally:Holder",
        "damage_classes": frozenset(DamageClass),
        "attack_classes": frozenset(AttackClass),
        "_event_id": "enemy:Subject:support:0",
    }
    template.update(overrides)
    return template


def test_the_template_refusal_admits_the_kind_and_still_names_its_own():
    """Clause 1: the kind is no longer refused categorically.

    The negative half is what makes the positive one mean something (R-05):
    an amount only the walk can price, and a deferred transition, are still
    declined by name, so "admits ``damage_modifier``" is not "admits
    anything spelled ``damage_modifier``".
    """
    assert unrepresentable_template_receipt(_template()) is None
    assert unrepresentable_template_receipt(_template(persistent=True)) is None
    assert (
        unrepresentable_template_receipt(_template(amount_formula=lambda *_: 1.0))
        == "modifier_amount_formula"
    )
    assert (
        unrepresentable_template_receipt(_template(_deferred=True))
        == "deferred_transition"
    )
    # Every other kind is still refused, and a shield's duration still is.
    assert (
        unrepresentable_template_receipt(_template(kind="on_hit_magic"))
        == "support_kind=on_hit_magic"
    )
    assert unrepresentable_modifier_receipt(_template()) is None


def test_the_compiled_modifier_action_matches_the_receipt_builder():
    """Clause 2: one packet, two builders, one action.

    The receipt adapter converts a packet through ``action_from_event`` and
    the compiler builds its own tuple; every field the kernel's
    ``_apply_damage_modifier`` reads has to agree, or the two walks arm
    different debuffs from one declaration — failure mode C of the incident.
    The field list is read off the kernel's own reads rather than typed as a
    guess, and ``sort_key`` is compared separately because the compiler's
    subject id is the template's target while the receipt's is its ledger
    bucket (the same string, for a support packet).
    """
    index_of = {"ally:Holder": 1, "enemy:Subject": 2}
    template = _template()
    compiler = WalkCompiler()
    compiler.add_support_templates([template], 1, index_of)
    (compiled,) = compiler.actions
    receipted = action_from_event(
        template,
        support_transition_rank(template),
        index_of["enemy:Subject"],
        index_of,
        subject_id="enemy:Subject",
    )
    assert compiled.kind is ActionKind.DAMAGE_MODIFIER
    assert receipted.kind is ActionKind.DAMAGE_MODIFIER
    for field in (
        "time",
        "phase",
        "subject",
        "attacker",
        "holder",
        "amount",
        "duration",
        "persistent",
        "multiplier",
        "damage_reduction",
        "next_event_only",
        "armor_reduction_percent",
        "mr_reduction_percent",
        "resistance_type",
        "damage_classes",
        "attack_classes",
        "source",
        "source_key",
    ):
        assert getattr(compiled, field) == getattr(receipted, field), field
    assert compiled.sort_key == receipted.sort_key
    # It is support the holder provided, and it heals nobody.
    assert compiler.support_entries == [("enemy:Subject", 1, compiled.aidx, False)]
    assert compiler.staged_modifier is True


def test_a_compiled_damage_row_says_how_it_was_delivered():
    """Clause 3, first half: the two delivery flags reach the kernel tuple.

    They were unread while no modifier could compile, so both sat at their
    ``False`` class default and every compiled packet classified as
    ``OTHER``.  A modifier declaring all three attack classes would then have
    reached only the rows whose ``source_key`` happened to be
    ``auto_attacks`` — an amp the score path priced differently from the
    walk with nothing saying so.
    """
    from src.calculator.survival.actions import attack_class_of
    from src.calculator.ability_spec import AttackClass

    ability = SurvivalAction(is_ability=True, source_key="Q")
    basic = SurvivalAction(basic_attack=True, source_key="on_hit_Nashors")
    other = SurvivalAction(source_key="burn_Liandrys")
    assert attack_class_of(ability) is AttackClass.ABILITY
    assert attack_class_of(basic) is AttackClass.BASIC_ATTACK
    assert attack_class_of(other) is AttackClass.OTHER


def test_a_light_ledger_row_cannot_carry_a_modifier():
    """Clause 3, second half: the fail-closed pair, and its own red (R-05).

    The engine's light tuple ledger carries no per-packet delivery
    metadata, so an armed modifier restricted by attack class cannot be
    evaluated against it.  The two halves land in different compilers — an
    ally's curse in the invariant panel, the packets it amplifies in the
    candidate's own fresh result — which is why the question is asked of the
    assembled set.  Driven as a pure function over compilers, so the red is
    reproducible on demand rather than a claim about the past.
    """
    plain = WalkCompiler()
    modifier_only = WalkCompiler()
    modifier_only.staged_modifier = True
    light_only = WalkCompiler()
    light_only.unclassified_delivery = True

    assert modifier_delivery_receipt((plain,)) is None
    assert modifier_delivery_receipt((modifier_only,)) is None
    assert modifier_delivery_receipt((light_only,)) is None
    assert (
        modifier_delivery_receipt((modifier_only, light_only))
        == "modifier_over_light_ledger"
    )
    both = WalkCompiler()
    both.staged_modifier = True
    both.unclassified_delivery = True
    assert modifier_delivery_receipt((both,)) == "modifier_over_light_ledger"


def test_the_resistance_baselines_have_one_home():
    """Clause 3, third half: one reader for the figure both paths need.

    A resistance-reducing modifier re-prices its packet as the ratio of two
    mitigation factors against the pair fight's own final resistances.  The
    receipt path stamps them onto every enriched event and the compiler
    reads them off the result; the same figure has to reach the same kernel
    field either way.  ``None`` is the honest absence — the walk receipts
    ``support_resistance_reduction_unavailable`` rather than inventing a
    ratio — and a non-finite figure is an absence too.
    """
    assert pair_resistance_baselines(
        {"effective_armor": 80.0, "effective_mr": 45.5}
    ) == (80.0, 45.5)
    assert pair_resistance_baselines({}) == (None, None)
    assert pair_resistance_baselines(
        {"effective_armor": float("inf"), "effective_mr": "not a number"}
    ) == (None, None)
