"""The refresh proof: a declaration holds a reference, not a number (D-48).

A declaration that stored the number it read would be right on the day it
was written and stale on every day after.  Proving it does not is harder
than it looks, and the trap is named in the ruling: ``refresh_item_effects()``
rebuilds ``ITEM_EFFECTS`` from ``data/``, so a monkeypatched *registry* value
is overwritten by the parse.  That test proves liveness and cannot tell
"holds a reference" from "was reconstructed by the same import".

So the mutation happens one layer further out — in the **cached item JSON**,
the text the parser reads — and nothing is re-imported.  The chain a passing
case exercises is the whole one: cached wiki text → parser → ``ITEM_EFFECTS``
→ the rule's ``ValueRef`` → the number a fight prices.

One rule per migrated family is proven this way, and the table below is
asserted **total over the migrated families**, so a family that lands without
a proof fails collection rather than being noticed later.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass

import pytest

from src.calculator import item_behavior_catalog as catalog
from src.calculator import item_effects
from src.calculator.data_fetcher import fetch_item_data
from src.calculator.item_behavior import RuleFamily
from src.calculator.value_ref import DerivedValueRef, LevelValueRef, ValueRef


def value_refs(payload: object) -> list[ValueRef | LevelValueRef]:
    """Every leaf reference a rule payload reaches, in declaration order."""
    found: list[ValueRef | LevelValueRef] = []

    def walk(node: object) -> None:
        if isinstance(node, (ValueRef, LevelValueRef)):
            found.append(node)
        elif isinstance(node, DerivedValueRef):
            for operand in node.operands:
                walk(operand)
        elif is_dataclass(node) and not isinstance(node, type):
            for field in fields(node):
                walk(getattr(node, field.name))
        elif isinstance(node, (tuple, list, set, frozenset)):
            for item in node:
                walk(item)

    walk(payload)
    return found


# One rule per family, with the exact cached-text edit that moves its number.
# The edit is spelled out rather than computed: a proof whose mutation is
# derived from the value it is checking can pass against itself.
REFRESH_PROOFS: dict[RuleFamily, tuple[str, str, str, str, float]] = {
    RuleFamily.ON_HIT_STRIKE: (
        "Recurve Bow",
        "base",
        "{{as|15 '''bonus''' physical damage}}",
        "{{as|24 '''bonus''' physical damage}}",
        24.0,
    ),
    RuleFamily.SECONDARY_TARGET: (
        "Runaan's Hurricane",
        "secondary_ad_ratio",
        "{{as|55% AD}}",
        "{{as|70% AD}}",
        0.70,
    ),
    RuleFamily.RESISTANCE_SHRED: (
        "Black Cleaver",
        "reduction_per_stack",
        "{{as|6% armor reduction}}",
        "{{as|9% armor reduction}}",
        0.09,
    ),
    RuleFamily.ACTIVE_CAST: (
        "Tiamat",
        "total_ad_ratio",
        "Deal {{as|75% AD}}",
        "Deal {{as|90% AD}}",
        0.90,
    ),
    RuleFamily.CHARGED_STRIKE: (
        "Stormrazor",
        "base",
        "attack deals {{as|100 '''bonus''' magic damage}}",
        "attack deals {{as|175 '''bonus''' magic damage}}",
        175.0,
    ),
    RuleFamily.CAST_PROC: (
        "Hextech Alternator",
        "base",
        "deals {{as|65 '''bonus''' magic damage}}",
        "deals {{as|90 '''bonus''' magic damage}}",
        90.0,
    ),
    RuleFamily.SPELLBLADE: (
        "Sheen",
        "base_ad_ratio",
        "deals {{as|100% '''base''' AD}}",
        "deals {{as|140% '''base''' AD}}",
        1.40,
    ),
    RuleFamily.PERIODIC: (
        "Unending Despair",
        "bonus_hp_ratio",
        "{{as|3% of your '''bonus''' health}}",
        "{{as|8% of your '''bonus''' health}}",
        0.08,
    ),
    RuleFamily.DELTA_AMP: (
        "Horizon Focus",
        "amp",
        "damage dealt to them by 10%",
        "damage dealt to them by 25%",
        0.25,
    ),
}

# The one migrated family with no rule that *can* pass the proof, and the
# reason, measured rather than asserted: every number an ally packet reads is
# either hand-authored in ``ALLY_ITEM_EFFECTS`` (refresh-inert by
# construction, D-47) or a code-owned key in ``_STATIC_ITEM_EFFECTS``, which a
# wiki edit cannot move either.  The test below proves that is still true, so
# the exemption fails the day one ally-packet number becomes parser-owned.
REFRESH_INERT_FAMILIES: dict[RuleFamily, str] = {
    RuleFamily.ALLY_PACKET: (
        "every value an ally packet reads is hand-authored (ALLY_ITEM_EFFECTS, "
        "D-47) or a code-owned static key; a refresh cannot move any of them, "
        "which is why scripts/patch_update.py audits them instead"
    ),
}


def migrated_families() -> frozenset[RuleFamily]:
    """The families with a real compiler — the population owing a proof."""
    return frozenset(catalog.RuleFamily) - frozenset(catalog.UNMIGRATED_FAMILIES)


@pytest.fixture(name="cached_items")
def _cached_items():
    """The parsed item cache, restored (and re-parsed) after every edit."""
    data = fetch_item_data()
    by_name = {
        str(entry.get("name")): entry
        for entry in data.values()
        if isinstance(entry, dict) and entry.get("name")
    }
    saved: list[tuple[list[str], list[str]]] = []

    def edit(owner: str, before: str, after: str) -> int:
        item = by_name[owner]
        hits = 0
        for effect in (item.get("passives") or []) + (item.get("active") or []):
            branches = effect.get("branches") or []
            for index, text in enumerate(branches):
                if before in text:
                    saved.append((branches, list(branches)))
                    branches[index] = text.replace(before, after)
                    hits += 1
        return hits

    yield edit

    for branches, original in reversed(saved):
        branches[:] = original
    item_effects.refresh_item_effects()


def test_every_migrated_family_carries_a_proof_or_a_measured_reason() -> None:
    """The table is total: a new family lands with its proof or fails here."""
    covered = frozenset(REFRESH_PROOFS) | frozenset(REFRESH_INERT_FAMILIES)
    assert covered == migrated_families()
    assert not frozenset(REFRESH_PROOFS) & frozenset(REFRESH_INERT_FAMILIES)


@pytest.mark.parametrize("family", sorted(REFRESH_PROOFS, key=lambda f: f.value))
def test_a_rules_number_follows_the_cached_text(family, cached_items) -> None:
    """Mutate the cached JSON, refresh, and the declaration's number moves."""
    owner, key, before, after, expected = REFRESH_PROOFS[family]
    reference = ValueRef("ITEM_EFFECTS", owner, key)
    assert reference.get() != expected, "the proof must start from a difference"

    assert cached_items(owner, before, after) == 1
    item_effects.refresh_item_effects()

    # No re-import: the same ValueRef object, resolved again.
    assert reference.get() == pytest.approx(expected)
    # And the rule the catalog compiles from that registry moves with it.
    moved = [
        node
        for rule in catalog.behavior_rules(owner)
        if rule.family is family
        for node in value_refs(rule.payload)
        if isinstance(node, ValueRef) and node.owner == owner and node.key == key
    ]
    assert moved, f"{owner} declares no {family.value} rule reading {key!r}"
    assert all(node.get() == pytest.approx(expected) for node in moved)


def test_a_priced_fight_follows_the_cached_text(cached_items) -> None:
    """The end of the chain: the number a fight prices moves too.

    One family carries this rather than all four.  The per-family cases above
    prove the declaration is live; this proves nothing downstream re-froze it
    into a build-time constant on the way to a damage total.
    """
    from src.calculator.interpreters.on_hit_strike import per_hit_effects
    from src.calculator.item_effects import DamageInputs

    def priced() -> float:
        """What one Recurve Bow auto adds, through the interpreter."""
        effects = per_hit_effects(
            ["Recurve Bow"],
            level=11,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        )
        inputs = DamageInputs(
            champion_stats={},
            level=11,
            is_melee=True,
            target_max_health=2000.0,
            target_current_health=2000.0,
        )
        return effects[0].source.raw_damage(inputs)

    before = priced()
    owner, _key, old_text, new_text, _expected = REFRESH_PROOFS[
        RuleFamily.ON_HIT_STRIKE
    ]
    assert cached_items(owner, old_text, new_text) == 1
    item_effects.refresh_item_effects()

    assert priced() == pytest.approx(24.0)
    assert before == pytest.approx(15.0)


def test_the_inert_families_reason_is_still_true() -> None:
    """The exemption is measured on every run, never carried as prose."""
    static_keys = item_effects._STATIC_VALUE_KEYS_BY_ITEM  # noqa: SLF001
    for family, reason in REFRESH_INERT_FAMILIES.items():
        assert reason.strip()
        parser_owned: list[str] = []
        for owner in sorted(catalog.declared_owners()):
            for rule in catalog.behavior_rules(owner):
                if rule.family is not family:
                    continue
                for node in value_refs(rule.payload):
                    key = getattr(node, "key", None) or getattr(node, "min_key", "")
                    if node.registry != "ITEM_EFFECTS":
                        continue
                    if key not in static_keys.get(node.owner, ()):
                        parser_owned.append(f"{node.owner}.{key}")
        assert parser_owned == [], (
            f"{family.value} now reads a parser-owned number; it owes a "
            f"refresh proof rather than an exemption: {sorted(set(parser_owned))}"
        )
