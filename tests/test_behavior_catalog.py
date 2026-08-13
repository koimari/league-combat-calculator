"""The front door for ``item_behavior_catalog`` — closure, and its three reds.

The catalog's whole value is that it *cannot* be silently incomplete.  A new
effect tag, a new ``ActionKind`` or a new ``DefenseMechanic`` has
to be given a family before the module will import, and a module that will
not import fails collection rather than running with a hole in it.  Each of
those three closures therefore ships with the red it can reproduce on demand
(runbook R-05), driven through the validator's own seam — because a gate
nobody has seen fail is indistinguishable from a gate that always passes,
which is this campaign's founding observation.
"""

import ast
from pathlib import Path

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator.data_fetcher import fetch_item_data
from src.calculator.item_behavior import (
    Compilable,
    DefenseMechanic,
    ReceiptOnly,
    ReceiptScope,
    RuleFamily,
)
from src.calculator.item_effects import (
    ALLY_ITEM_EFFECTS,
    ITEM_EFFECTS,
    known_effect_types,
)
from src.calculator.survival.actions import ActionKind

MODULE_PATH = (
    Path(__file__).parents[1] / "src" / "calculator" / "item_behavior_catalog.py"
)


# ── closure ───────────────────────────────────────────────────────────────


def test_the_tag_map_is_total_and_single_valued() -> None:
    """Every registry tag has exactly one family; no family is invented for none."""
    assert frozenset(catalog.TAG_FAMILY) == frozenset(known_effect_types())
    assert all(isinstance(family, RuleFamily) for family in catalog.TAG_FAMILY.values())


def test_a_new_effect_tag_fails_the_catalog() -> None:
    """R-05's red for the tag closure, through the validator's seam."""
    with pytest.raises(catalog.BehaviorCatalogError, match="unmapped"):
        catalog._validate_tag_closure(  # pylint: disable=protected-access
            frozenset(known_effect_types()) | {"brand_new_mechanic"}
        )


def test_the_catalog_import_runs_the_tag_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam above is the same gate the import runs — not a parallel check."""
    monkeypatch.setattr(
        catalog.item_effects,
        "known_effect_types",
        lambda: frozenset(known_effect_types()) | {"brand_new_mechanic"},
    )
    with pytest.raises(catalog.BehaviorCatalogError):
        catalog.validate_catalog()


def test_validate_catalog_is_called_at_import() -> None:
    """A closure nobody runs is a comment; the call is at module scope."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    called = {
        node.value.func.id
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    }
    assert "validate_catalog" in called


def test_every_action_kind_has_a_family() -> None:
    """All nineteen survival transitions land in the eighteen families."""
    assert frozenset(catalog.ACTION_KIND_FAMILY) == frozenset(ActionKind)
    assert len(ActionKind) == 19


def test_a_new_action_kind_fails_the_catalog() -> None:
    """R-05's red for the ActionKind closure."""
    with pytest.raises(catalog.BehaviorCatalogError, match="ActionKind"):
        catalog._validate_action_kind_closure(  # pylint: disable=protected-access
            frozenset(ActionKind) | {"a_new_transition"}
        )


def test_every_defense_mechanic_has_a_family() -> None:
    """The closure's population is the closed enum, not a scrape of a module."""
    assert frozenset(catalog.DEFENSE_SOURCE_FAMILY) == frozenset(DefenseMechanic)


def test_every_defense_mechanic_is_declared_or_cited() -> None:
    """A mechanic with no declaration says why, and both reasons are named."""
    covered = frozenset(catalog.DEFENSE_DECLARATIONS) | frozenset(
        catalog.UNDECLARED_DEFENSE_MECHANICS
    )
    assert covered == frozenset(DefenseMechanic)
    assert not frozenset(catalog.DEFENSE_DECLARATIONS) & frozenset(
        catalog.UNDECLARED_DEFENSE_MECHANICS
    )
    assert frozenset(catalog.DEFENSE_UNMIGRATED_MECHANICS) <= frozenset(
        catalog.DEFENSE_DECLARATIONS
    )


def test_a_new_defense_mechanic_fails_the_catalog() -> None:
    """R-05's red for the defensive closure."""
    with pytest.raises(catalog.BehaviorCatalogError, match="unmapped"):
        catalog._validate_defense_source_closure(  # pylint: disable=protected-access
            frozenset(DefenseMechanic) | {"a_new_defence"}
        )


def test_one_compiler_per_family_and_every_stub_names_its_slice() -> None:
    """D-52's registry: closed enum key, module-level defs, totality asserted."""
    compilers = catalog._COMPILERS  # pylint: disable=protected-access
    assert frozenset(compilers) == frozenset(RuleFamily)
    assert all(
        getattr(compiler, "__name__", "") and not compiler.__name__ == "<lambda>"
        for compiler in compilers.values()
    )
    stubbed = frozenset(
        family
        for family, compiler in compilers.items()
        if compiler.__name__ == "_unmigrated"
    )
    assert frozenset(catalog.UNMIGRATED_FAMILIES) == stubbed
    assert RuleFamily.DELTA_AMP not in stubbed


def test_a_partly_migrated_family_still_names_what_it_refuses() -> None:
    """Leaving UNMIGRATED_FAMILIES must not retire promises nobody kept."""
    delta_tags = frozenset(
        tag
        for tag, family in catalog.TAG_FAMILY.items()
        if family is RuleFamily.DELTA_AMP
    )
    named = catalog.MIGRATED_DELTA_AMP_TAGS | frozenset(
        catalog.DELTA_AMP_UNMIGRATED_TAGS
    )
    assert named == delta_tags
    assert not catalog.MIGRATED_DELTA_AMP_TAGS & frozenset(
        catalog.DELTA_AMP_UNMIGRATED_TAGS
    )
    for tag, slice_name in catalog.DELTA_AMP_UNMIGRATED_TAGS.items():
        assert slice_name.strip(), tag


def test_an_unnamed_delta_amp_tag_fails_the_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-05's red for the partial-migration closure."""
    monkeypatch.setattr(catalog, "MIGRATED_DELTA_AMP_TAGS", frozenset())
    with pytest.raises(catalog.BehaviorCatalogError, match="unnamed"):
        catalog.validate_catalog()


# ── H4's ten tags ─────────────────────────────────────────────────────────


def test_the_ten_undispatched_tags_are_declared_four_and_six() -> None:
    """The split is the phase document's; this table must agree with it."""
    assert catalog.H4_DEAD_TAGS == frozenset(
        {
            "conditional_attack_speed",
            "shield_reduction",
            "target_state",
            "target_attack_speed_aura",
        }
    )
    assert catalog.H4_SELF_REFERENTIAL_TAGS == frozenset(
        {
            "defensive_start",
            "stat_conversion",
            "sustain",
            "target_mitigation",
            "target_threshold_health",
            "target_threshold_shield",
        }
    )
    assert not catalog.H4_DEAD_TAGS & catalog.H4_SELF_REFERENTIAL_TAGS


def test_each_h4_tag_fails_closed_into_a_family_with_a_reason() -> None:
    """Declared, not deleted: deleting them is the human's call, not a side effect."""
    ten = catalog.H4_DEAD_TAGS | catalog.H4_SELF_REFERENTIAL_TAGS
    assert frozenset(catalog.H4_TAG_REASONS) == ten
    for tag in ten:
        assert isinstance(catalog.TAG_FAMILY[tag], RuleFamily)
        assert catalog.H4_TAG_REASONS[tag].strip()


def test_an_h4_tag_without_a_reason_fails_the_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fail-closed mapping with no stated cause is the prose this phase kills."""
    reasons = dict(catalog.H4_TAG_REASONS)
    reasons.pop("target_state")
    monkeypatch.setattr(catalog, "H4_TAG_REASONS", reasons)
    with pytest.raises(catalog.BehaviorCatalogError, match="reason"):
        catalog.validate_catalog()


# ── compilation ───────────────────────────────────────────────────────────


def test_what_is_not_declared_yet_is_named_rather_than_zeroed() -> None:
    """Counter 3's population is entries, and every undeclared one is named."""
    entries = len(ITEM_EFFECTS) + len(ALLY_ITEM_EFFECTS)
    declared_entries = sum(
        len(catalog.registry_entries(owner)) for owner in catalog.declared_owners()
    )
    assert catalog.undeclared_entry_count() == entries - declared_entries
    assert catalog.declared_owners() | catalog.undeclared_owners() == (
        catalog.registry_owners()
    )
    assert not catalog.declared_owners() & catalog.undeclared_owners()


def test_the_hypershot_slot_is_declared_and_holds_no_number() -> None:
    """3.2's canary: the amp is a reference into the registry, not a literal."""
    (rule,) = catalog.behavior_rules("Horizon Focus")
    assert rule.family is RuleFamily.DELTA_AMP
    assert rule.mechanic_id == "horizon_focus.hypershot"
    assert rule.payload.magnitude.value.registry == "ITEM_EFFECTS"
    assert rule.payload.magnitude.value.key == "amp"
    assert rule.receipt.url.endswith("Horizon_Focus")
    # Since H5's stage the canary compiles: the one amp answer is
    # ``Compilable`` and every amp rule declares that one symbol.
    assert rule.compilability is catalog.AMP_COMPILABILITY
    assert isinstance(rule.compilability, Compilable)


def test_an_owner_in_both_registries_owes_two_declarations() -> None:
    """Six owners hold one entry of each, and each entry is its own obligation."""
    both = frozenset(ITEM_EFFECTS) & frozenset(ALLY_ITEM_EFFECTS)
    assert both
    for owner in sorted(both):
        assert len(catalog.registry_entries(owner)) == 2


def test_an_item_with_no_registry_entry_has_no_rules_and_no_refusal() -> None:
    """No entry is an answer — stats only — and a different thing from a refusal."""
    assert catalog.behavior_rules("Boots") == ()
    assert catalog.registry_entries("Boots") == ()


def test_an_unknown_tag_in_the_registry_raises_rather_than_compiling_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tag no family claims is a stop, not an item that quietly does nothing."""
    entry = dict(ITEM_EFFECTS["Black Cleaver"])
    entry["type"] = "not_a_known_tag"
    monkeypatch.setitem(ITEM_EFFECTS, "Black Cleaver", entry)
    with pytest.raises(catalog.BehaviorCatalogError, match="no family claims"):
        catalog.behavior_rules("Black Cleaver")


def test_the_build_context_carries_the_data_version() -> None:
    """D-49: every downstream memo keys on one counter, read in one place."""
    from src.calculator import data_registry  # pylint: disable=import-outside-toplevel

    context = catalog.build_context(
        "Black Cleaver",
        18,
        fight_duration_seconds=5.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    assert context.data_version == data_registry.data_version()
    assert context.owner == "Black Cleaver"
    assert context.level == 18


def test_an_unexplained_certified_mechanic_fails_the_catalog() -> None:
    """R-05's red for the certification closure, through the validator's seam.

    A certified mechanic withholds a whole calculation when the timeline is
    coarse.  Certifying one with a blank reason would make that refusal
    unexplainable to the caller it refuses, which is the failure this campaign
    exists to remove rather than a new one it may introduce.
    """
    with pytest.raises(catalog.BehaviorCatalogError, match="unexplained"):
        catalog._validate_event_certification(  # pylint: disable=protected-access
            {DefenseMechanic.LIFELINE_MAW: ""}
        )


def test_every_certified_mechanic_is_one_the_catalog_declares() -> None:
    """The live set passes the closure the seam above reproduces red."""
    catalog._validate_event_certification()  # pylint: disable=protected-access
    assert catalog.EVENT_CERTIFIED_MECHANICS
    assert all(
        isinstance(mechanic, DefenseMechanic)
        for mechanic in catalog.EVENT_CERTIFIED_MECHANICS
    )


# ── the refusal scope axis ────────────────────────────────────────────────


def _live_refusals() -> tuple[ReceiptOnly, ...]:
    """Every ``ReceiptOnly`` the live catalog compiles, in owner order."""
    return tuple(
        rule.compilability
        for owner in sorted(catalog.rule_owners())
        for rule in catalog.behavior_rules(owner)
        if isinstance(rule.compilability, ReceiptOnly)
    )


def test_every_refusal_scope_is_reached_by_a_live_declaration() -> None:
    """D-51's orphan-branch direction, applied to the refusal axis.

    A scope no declaration carries is a member that means nothing — the
    reader learns a distinction the tree does not make, which is how the
    single free-text reason came to stand for three unrelated refusals in the
    first place.  Two members are live: the ledger scope carries the defences
    the walk authors and the template scope the support kinds the kernel
    stages nothing of.

    The third is live in a different sense and the difference is stated
    rather than absorbed.  ``SCORE_KERNEL_DAMAGE_MODIFIER`` exists because a
    flip needs a set it can name, and H5's stage flipped that set: its live
    population is now **empty**, which is the stage having landed and not a
    member nobody argued about.  Its declaration survives as the flip's
    revert target (``COMPILED_KERNEL_CANNOT_AMP``), so the scope is still
    carried by a ``ReceiptOnly`` a reader can go and look at — and the
    emptiness is asserted here rather than left to be noticed, which is D-92's
    own idiom read in the other direction.
    """
    reached = {refusal.scope for refusal in _live_refusals()}
    assert reached == set(ReceiptScope) - {ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER}
    assert (
        catalog.COMPILED_KERNEL_CANNOT_AMP.scope
        is ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER
    )


def test_the_amp_flip_took_delta_amp_and_nothing_else() -> None:
    """The scope earned its member by being a set a later flip could name.

    H5's stage flipped ``delta_amp`` to ``Compilable`` — and nothing else.
    The claim survives the flip by being read off the symbol the flip moved
    rather than off the refusal it moved away from: if any other family had
    declared ``AMP_COMPILABILITY``, the flip would have taken a mechanic
    nobody scoped with it, and that is still the thing worth checking.
    """
    families = {
        rule.family
        for owner in sorted(catalog.rule_owners())
        for rule in catalog.behavior_rules(owner)
        if rule.compilability is catalog.AMP_COMPILABILITY
    }
    assert families == {RuleFamily.DELTA_AMP}
    # And no rule is left carrying the refusal the flip moved away from.
    assert not [
        rule
        for owner in sorted(catalog.rule_owners())
        for rule in catalog.behavior_rules(owner)
        if rule.compilability is catalog.COMPILED_KERNEL_CANNOT_AMP
    ]


# ── the ledger-scope refusals, derived by shape ───────────────────────────


def _ledger_refusing_owners() -> frozenset[str]:
    """Every owner with a rule the compiled *survival ledger* cannot stage."""
    return frozenset(
        owner
        for owner in catalog.rule_owners()
        for rule in catalog.behavior_rules(owner)
        if isinstance(rule.compilability, ReceiptOnly)
        and rule.compilability.scope is ReceiptScope.SURVIVAL_LEDGER_TRANSITION
    )


def test_each_unstageable_sustain_shape_refuses_and_the_others_do_not() -> None:
    """The four shapes are refused *as shapes*, and nothing else is.

    The hand set records these four as per-item comments, two of them called
    conservatism notes.  Read at the compiler's granularity they are neither:
    each is one payload type the score ledger has nowhere to put.  The second
    half is the half that matters — a shape-keyed table that refused every
    sustain rule would reproduce the hand set by over-withholding, which is
    the family-predicate failure D-43 rejects.
    """
    refused: dict[type, set[str]] = {}
    allowed: set[type] = set()
    for owner in sorted(catalog.rule_owners()):
        for rule in catalog.behavior_rules(owner):
            if rule.family is not RuleFamily.SUSTAIN:
                continue
            shape = type(rule.payload)
            if shape in catalog.LEDGER_UNSTAGEABLE_SUSTAIN:
                refused.setdefault(shape, set()).add(owner)
                assert isinstance(rule.compilability, ReceiptOnly)
                assert (
                    rule.compilability.scope is ReceiptScope.SURVIVAL_LEDGER_TRANSITION
                )
            else:
                allowed.add(shape)
                assert isinstance(rule.compilability, Compilable)

    assert set(refused) == set(catalog.LEDGER_UNSTAGEABLE_SUSTAIN), (
        "a declared unstageable shape that no live rule carries is a refusal "
        "for nobody (D-92)"
    )
    assert allowed, "every sustain shape is refused; the table is a blanket"


def test_a_self_shield_is_one_refusal_in_the_two_shapes_that_declare_one() -> None:
    """Eclipse declares it as a cast proc, Fimbulwinter as an ally packet.

    Two families can express "the holder shields itself", and the kernel
    refuses both through one clause — ``unrepresentable_damage_receipt``'s
    ``self_shield_payload``.  Writing the reason twice is how one fact
    becomes two that can disagree, so both compilers reach the same constant
    and this test is what says so.
    """
    carriers = {
        rule.owner: rule.family
        for owner in sorted(catalog.rule_owners())
        for rule in catalog.behavior_rules(owner)
        if rule.compilability is catalog.COMPILED_KERNEL_CANNOT_SELF_SHIELD
    }
    assert carriers == {
        "Eclipse": RuleFamily.CAST_PROC,
        "Fimbulwinter": RuleFamily.ALLY_PACKET,
    }


def test_the_ledger_scope_is_derived_from_shapes_and_never_from_a_name() -> None:
    """The catalog holds no item-name literal, so none of this is a list.

    Counter 1 measures the tree for item-name dispatch and this module is in
    no exclusion set, so its own emptiness is the proof: every refusal above
    is reached through a payload type, a packet recipient or a defence
    mechanic, and an item joins or leaves the withheld population by growing
    or losing that shape.
    """
    names = frozenset(
        entry["name"]
        for entry in fetch_item_data().values()
        if isinstance(entry, dict) and entry.get("name")
    )
    literals = {
        node.value
        for node in ast.walk(ast.parse(MODULE_PATH.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in names
    }
    assert literals == set()
    assert _ledger_refusing_owners()


def test_one_entry_declares_both_halves_of_a_health_state_passive() -> None:
    """Immortal Path's tag names one half and a value key names the other.

    The entry is tagged ``damage_amp`` for the amplifier it grants above the
    boundary; the healing bonus it grants below one is a second mechanic on
    the same entry, routed by its own value key.  Without the routing the
    below-half number would keep moving fights with no declaration behind it,
    which is the shape this phase exists to end — so both families are
    asserted, not just the count.
    """
    families = {rule.family for rule in catalog.behavior_rules("Immortal Path")}
    assert families == {RuleFamily.DELTA_AMP, RuleFamily.SUSTAIN}
    assert (
        catalog.SECONDARY_KEY_FAMILY["ITEM_EFFECTS"][catalog.BELOW_HALF_HEALING_KEY]
        is RuleFamily.SUSTAIN
    )
    assert catalog.BELOW_HALF_HEALING_KEY in ITEM_EFFECTS["Immortal Path"]


def test_the_two_halves_answer_in_two_scopes() -> None:
    """One owner, two answers, and neither answers for the other.

    Immortal Path declares an amp and a healing bonus.  Since H5's stage the
    amp compiles and the healing bonus is still refused by the survival
    ledger's transition scope — which makes the point *better* than two
    refusals did: a fold over both scopes would now report a compilable owner
    as unstageable, or an unstageable one as compilable, depending on which
    way it folded.  That is why :func:`compilability_for` takes the scope it
    is answering for.
    """
    scopes = {
        rule.family: rule.compilability.scope
        for rule in catalog.behavior_rules("Immortal Path")
        if isinstance(rule.compilability, ReceiptOnly)
    }
    assert scopes == {RuleFamily.SUSTAIN: ReceiptScope.SURVIVAL_LEDGER_TRANSITION}
    assert {
        rule.family
        for rule in catalog.behavior_rules("Immortal Path")
        if isinstance(rule.compilability, Compilable)
    } == {RuleFamily.DELTA_AMP}


# ── a dropped signature key is a stop, not an un-declaration ──────────────
#
# A secondary family is claimed by one key on an entry whose tag names a
# different family.  Looked for in the live entry, a parse that dropped that
# one key would take the whole mechanic out of the catalog — and a mechanic
# nothing declares is priced as nothing by every lane at once, silently,
# which is the failure this campaign is named after.  The schema is the
# authority, so the family is still claimed and the missing key raises.

SECONDARY_SIGNATURE_KEYS = (
    ("Riftmaker", "max_stack_omnivamp", RuleFamily.SUSTAIN),
    (
        "Guinsoo's Rageblade",
        "seething_attack_speed_per_stack",
        RuleFamily.CHARGED_STRIKE,
    ),
    ("Yun Tal Wildarrows", "attack_refund_base", RuleFamily.CHARGED_STRIKE),
)


@pytest.mark.parametrize("owner,key,family", SECONDARY_SIGNATURE_KEYS)
def test_a_dropped_secondary_signature_key_still_claims_its_family(
    monkeypatch: pytest.MonkeyPatch, owner: str, key: str, family: RuleFamily
) -> None:
    """The claim comes off the schema, so the parse cannot withdraw it."""
    entry = {name: value for name, value in ITEM_EFFECTS[owner].items() if name != key}
    monkeypatch.setitem(ITEM_EFFECTS, owner, entry)
    (_registry, primary, live), *_ = catalog.registry_entries(owner)
    assert family in catalog.entry_families("ITEM_EFFECTS", primary, live, owner)


@pytest.mark.parametrize("owner,key,family", SECONDARY_SIGNATURE_KEYS)
def test_a_dropped_secondary_signature_key_raises_naming_item_and_key(
    monkeypatch: pytest.MonkeyPatch, owner: str, key: str, family: RuleFamily
) -> None:
    """Rule 5's fail-loud contract, reached through the declaration."""
    entry = {name: value for name, value in ITEM_EFFECTS[owner].items() if name != key}
    monkeypatch.setitem(ITEM_EFFECTS, owner, entry)
    (rule,) = [rule for rule in catalog.behavior_rules(owner) if rule.family is family]
    with pytest.raises(KeyError, match=key):
        for reference in _declared_references(rule.payload):
            reference.get()


def _declared_references(payload: object) -> list:
    """Every ``ValueRef`` one payload holds, one level of record deep."""
    from dataclasses import fields, is_dataclass

    from src.calculator.value_ref import ValueRef

    found: list = []
    if not is_dataclass(payload):
        return found
    for field in fields(payload):
        value = getattr(payload, field.name)
        if isinstance(value, ValueRef):
            found.append(value)
        else:
            found.extend(_declared_references(value))
    return found
