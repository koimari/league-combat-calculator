"""The front door for ``value_ref`` — references resolve, or say why not.

A declaration holds references, never numbers.  These tests are about the two
halves of that sentence: a reference reads the live registry through the same
fail-loud accessor everything else uses, and the shapes that would let a raw
number in — an unsourced receipt, a non-integral ``Const``, an unknown
registry — are refusals rather than defaults.
"""

import math

import pytest

from src.calculator import item_effects, rune_effects
from src.calculator.value_ref import (
    Const,
    DerivedValueRef,
    LevelValueRef,
    SourceReceipt,
    UnsourcedDeclarationError,
    VALUE_REGISTRIES,
    ValueRef,
    ValueRefError,
    receipt_for,
    resolve,
)


def test_the_registry_union_is_three_members() -> None:
    """D-46: three registries own runtime numbers and a fourth is Phase 1's."""
    assert VALUE_REGISTRIES == frozenset(
        {"ITEM_EFFECTS", "ALLY_ITEM_EFFECTS", "RUNE_EFFECTS"}
    )
    assert "ITEM_INPUT_OPTIONS" not in VALUE_REGISTRIES


def test_an_item_reference_reads_the_live_registry() -> None:
    """The number comes from the registry, not from the declaration."""
    reference = ValueRef("ITEM_EFFECTS", "Black Cleaver", "reduction_per_stack")
    assert reference.get() == float(
        item_effects.required_effect_value("Black Cleaver", "reduction_per_stack")
    )


def test_a_missing_key_raises_naming_the_owner_and_key() -> None:
    """CLAUDE.md rule 5, one layer up: no literal fallback at the call site."""
    with pytest.raises(KeyError, match="Black Cleaver"):
        ValueRef("ITEM_EFFECTS", "Black Cleaver", "no_such_key").get()


def test_an_ally_reference_routes_through_the_ally_accessor() -> None:
    """The ally registry has its own accessor and the reference uses it."""
    reference = ValueRef("ALLY_ITEM_EFFECTS", "Abyssal Mask", "magic_damage_amp")
    assert reference.get() == item_effects.ally_item_effect_value(
        "Abyssal Mask", "magic_damage_amp"
    )


def test_a_rune_reference_routes_through_the_rune_accessor() -> None:
    """Keystones are runtime damage producers, so rule 5 reaches them too."""
    reference = ValueRef("RUNE_EFFECTS", "Press the Attack", "cooldown")
    assert reference.get() == rune_effects.rune_effect_value(
        "Press the Attack", "cooldown"
    )


def test_a_reference_into_an_unknown_registry_is_refused() -> None:
    """A fourth registry is a decision, not a typo that resolves anyway."""
    with pytest.raises(ValueRefError):
        ValueRef("ITEM_INPUT_OPTIONS", "Black Cleaver", "stacks")  # type: ignore[arg-type]


def test_a_reference_moves_when_the_registry_moves() -> None:
    """Liveness: the declaration holds a reference, not a copy (D-48's shape)."""
    reference = ValueRef("ITEM_EFFECTS", "Black Cleaver", "reduction_per_stack")
    before = reference.get()
    entry = item_effects.ITEM_EFFECTS["Black Cleaver"]
    entry["reduction_per_stack"] = before + 1.0
    try:
        assert reference.get() == before + 1.0
    finally:
        entry["reduction_per_stack"] = before


def test_a_structural_constant_may_not_be_a_magnitude() -> None:
    """Counts, caps, ranks and flags only; a quantity belongs in a registry."""
    assert Const(3, "count").get() == 3.0
    assert Const(0.01, "unit_scale").get() == 0.01
    with pytest.raises(ValueRefError, match="non-integral"):
        Const(0.35, "cap")
    with pytest.raises(ValueRefError, match="flag"):
        Const(2, "flag")
    with pytest.raises(ValueRefError):
        Const(3, "vibes")  # type: ignore[arg-type]
    with pytest.raises(ValueRefError):
        Const(math.inf, "cap")


def test_a_level_ramp_interpolates_between_two_live_keys() -> None:
    """The ends come from the registry; only the interpolation is declared."""
    reference = LevelValueRef(
        "ALLY_ITEM_EFFECTS",
        "Locket of the Iron Solari",
        "shield_min",
        "shield_max",
        "registry_start",
    )
    assert reference.get(1) == pytest.approx(
        item_effects.ally_item_level_value(
            "Locket of the Iron Solari", "shield_min", "shield_max", 1
        )
    )
    assert reference.get(18) >= reference.get(1)


def test_the_registry_start_scale_is_defined_for_one_registry() -> None:
    """It reads ALLY_ITEM_EFFECTS' own breakpoint and nothing else has one."""
    with pytest.raises(ValueRefError, match="registry_start"):
        LevelValueRef("ITEM_EFFECTS", "Black Cleaver", "a", "b", "registry_start")


def test_a_derived_reference_folds_its_operands_live() -> None:
    """A derivation is arithmetic over references, never a precomputed float."""
    derived = DerivedValueRef("ADD", (Const(2, "count"), Const(3, "count")))
    assert derived.get() == 5.0
    assert DerivedValueRef("MUL", (Const(2, "count"), Const(3, "count"))).get() == 6.0
    assert DerivedValueRef("MIN", (Const(2, "count"), Const(3, "count"))).get() == 2.0
    assert DerivedValueRef("MAX", (Const(2, "count"), Const(3, "count"))).get() == 3.0
    assert DerivedValueRef("RATIO", (Const(3, "count"), Const(2, "count"))).get() == 1.5


def test_a_derived_reference_refuses_an_arity_it_cannot_fold() -> None:
    """RATIO is two operands and an empty fold has no answer."""
    with pytest.raises(ValueRefError):
        DerivedValueRef("RATIO", (Const(1, "count"),))
    with pytest.raises(ValueRefError):
        DerivedValueRef("ADD", ())
    with pytest.raises(ValueRefError):
        DerivedValueRef("POW", (Const(1, "count"),))  # type: ignore[arg-type]


def test_a_zero_denominator_raises_rather_than_returning_a_number() -> None:
    """A zero denominator is a registry defect; a result would hide it."""
    with pytest.raises(ValueRefError, match="divides by zero"):
        DerivedValueRef("RATIO", (Const(1, "count"), Const(0, "count"))).get()


def test_resolve_rejects_a_bare_number() -> None:
    """The one entry point consumers use will not take a float."""
    with pytest.raises(ValueRefError):
        resolve(1.0)  # type: ignore[arg-type]


def test_a_level_scaled_reference_needs_a_level() -> None:
    """A ramp with no level is a question the reference cannot answer."""
    ramp = LevelValueRef(
        "ALLY_ITEM_EFFECTS",
        "Locket of the Iron Solari",
        "shield_min",
        "shield_max",
        "registry_start",
    )
    with pytest.raises(ValueRefError, match="level-scaled"):
        resolve(ramp)


def test_a_receipt_must_cite_something_checkable() -> None:
    """A citation with no URL or no stamp is a memory, not a receipt."""
    receipt = SourceReceipt("https://example.test/Item", 42, "2026-01-01T00:00:00Z")
    assert receipt.revision_id == 42
    with pytest.raises(ValueRefError):
        SourceReceipt("Item", 42, "2026-01-01T00:00:00Z")
    with pytest.raises(ValueRefError):
        SourceReceipt("https://example.test/Item", 42, "  ")
    with pytest.raises(ValueRefError):
        SourceReceipt("https://example.test/Item", -1, "2026-01-01T00:00:00Z")


def test_a_zero_revision_is_the_explicit_cache_backed_marker() -> None:
    """The precedent defensive_effects already sets: cache-backed, spelled."""
    receipt = SourceReceipt(
        "https://example.test/Item", 0, "cached data/items.json (patch 16.15)"
    )
    assert receipt.revision_id == 0


def test_receipt_for_reads_the_entry_when_the_citation_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first rung: the owner's own entry cites url, revision and stamp."""
    entry = dict(item_effects.ITEM_EFFECTS["Black Cleaver"])
    entry.update(
        {
            "source_url": "https://wiki.leagueoflegends.com/en-us/Black_Cleaver",
            "source_revision_id": 4040404,
            "source_revision_timestamp": "2026-07-01T00:00:00Z",
        }
    )
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Black Cleaver", entry)
    receipt = receipt_for("ITEM_EFFECTS", "Black Cleaver")
    assert receipt.revision_id == 4040404


def test_a_partial_citation_is_not_silently_completed() -> None:
    """Two of three keys is not a receipt, and no rung invents the third."""
    with pytest.raises(UnsourcedDeclarationError, match="Abyssal Mask"):
        receipt_for("ALLY_ITEM_EFFECTS", "Abyssal Mask")


def test_the_declared_constant_is_the_second_rung() -> None:
    """A family may supply the receipt its registry entry does not carry."""
    declared = SourceReceipt(
        "https://wiki.leagueoflegends.com/en-us/Abyssal_Mask",
        3984960,
        "2026-01-17T15:12:22Z",
    )
    assert (
        receipt_for("ALLY_ITEM_EFFECTS", "Abyssal Mask", declared=declared) is declared
    )


def test_an_unsourced_owner_raises_rather_than_returning_a_blank_receipt() -> None:
    """No rule is declared against a number nobody can point at."""
    with pytest.raises(UnsourcedDeclarationError):
        receipt_for("ITEM_EFFECTS", "No Such Item")
