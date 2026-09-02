"""The synthetic both-engine acceptance property (criterion 10).

Every other test in this phase exercises a declaration that a *real* item
carries, so every one of them is also a test of that item's engine code.  This
file removes the item.  Three owners exist here and nowhere else — they are in
no cache, no build, no scenario and no other source file — so the only thing
that can make a number appear for them is the declaration itself plus the
interpreter registered for its lane.  If the property holds for an item that
exists only as a declaration, it holds because the declaration is the
mechanism rather than a description of one.

The property, one clause per engine, over ``delta_amp``, ``ally_packet`` and
``threshold_defense``:

* the **pair engine** prices it, and the number is re-derived from the
  declaration's own references rather than pinned as a constant;
* the **receipt walk** applies it to other participants and *not* the holder,
  with the ``owner`` handshake the incident's own fix installed;
* the **compiled walk** either matches it or refuses with a named receipt —
  never silently drops it.  All three answers occur here: the lifeline is
  matched, the amp is D-101's categorical refusal, and the aura is the support
  kernel's;
* the **light-tuple path** raises rather than pricing the declaration at zero,
  which is the one failure a returned number could not disclose.

The three families are the ones criterion 10 names, and they are named because
they are the three shapes: a number the holder's own engine multiplies, a
packet another participant receives, and a defence the resolver builds.
"""

import ast
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from src.calculator import interpreters, item_effects, trigger_stream
from src.calculator import item_behavior_catalog as catalog
from src.calculator.ability_spec import AttackClass, Authority, DamageClass, DamagePart
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.interpreters import delta_amp
from src.calculator.item_behavior import (
    AmpChainSlot,
    Compilable,
    EngineLane,
    ReceiptOnly,
    ReceiptScope,
    RuleFamily,
    Subject,
)
from src.calculator.item_support_effects import (
    EventViewStarvationError,
    derive_item_support_effects,
    require_event_view,
)
from src.calculator.program.views import ViewTag
from src.calculator.roster_composition import ActorRequest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The three declaration-only owners.  Spelled once, here, and asserted below
# to appear in no other file of the tree.
AMP = "Declaration Testbed Amp"
AURA = "Declaration Testbed Aura"
LIFELINE = "Declaration Testbed Lifeline"

# Their registry entries.  Every key is one the *compilers* dispatch on — the
# amp's ramp schema, Unmake's one rate, the Seraph-shaped lifeline's four
# fields — so these are declarations in the registries' own vocabulary and not
# a private fixture format that could drift from what the catalog reads.
AMP_ENTRY = {"type": "damage_amp", "amp_per_second": 0.02, "amp_max": 0.30}
AURA_ENTRY = {"magic_damage_amp": 0.11}
LIFELINE_ENTRY = {
    "type": "target_threshold_shield",
    "shield_max_mana_ratio": 0.2,
    "health_threshold": 0.3,
    "duration": 3.0,
    "damage_type": "all",
}

FIGHT_DURATION = 5.0

_STATS = {
    "ability_haste": 0.0,
    "armor_penetration_bonus_percent": 0.0,
    "basic_ability_haste": 0.0,
    "bonus_attack_damage": 0.0,
    "bonus_health": 0.0,
    "bonus_mana": 0.0,
    "flat_armor_penetration": 0.0,
    "health": 0.0,
    "max_mana": 0.0,
    "move_speed": 0.0,
    "omnivamp_percent": 0.0,
    "resource_regen_per_second": 0.0,
    "ultimate_haste": 0.0,
    "attack_damage": 60.0,
    "base_attack_damage": 60.0,
    "attack_speed": 0.7,
    "attack_speed_ratio": 0.625,
    "critical_strike_chance": 0.0,
    "magic_penetration_flat": 0.0,
    "magic_penetration_percent": 0.0,
    "armor_penetration_percent": 0.0,
    "lethality": 0.0,
    "ability_power": 100.0,
    "is_melee": False,
    "level": 18,
}

_ABILITY = {
    "Q": {
        "name": "Test Q",
        "parts": (DamagePart("magic", 300.0),),
        "total_raw": 300.0,
        "damage_type": "magic",
        "cooldown": 6.0,
    }
}


@pytest.fixture(name="declared")
def _declared(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str, str]:
    """The three owners, present as declarations and as nothing else."""
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, AMP, AMP_ENTRY)
    monkeypatch.setitem(item_effects.ALLY_ITEM_EFFECTS, AURA, AURA_ENTRY)
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, LIFELINE, LIFELINE_ENTRY)
    return AMP, AURA, LIFELINE


def _fight(item_names: tuple[str, ...]) -> dict:
    """One pair fight holding *item_names*, everything else fixed."""
    return calculate_fight_damage(
        dict(_STATS),
        {key: dict(value) for key, value in _ABILITY.items()},
        [{"name": name} for name in item_names],
        FightConfig(
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=FIGHT_DURATION,
            auto_attack_uptime=0.0,
            one_rotation=True,
            cast_order=["Q"],
        ),
    )


def _actor(participant_id: str, team: str, item_names: tuple[str, ...]):
    """One participant, in the shape the support emitters read."""
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in item_names),
        stats={"mana": 1000.0, "max_mana": 1000.0, "is_melee": False},
        request=ActorRequest(item_options={}, ally_effects_enabled=True),
    )


def _rule(owner: str, family: RuleFamily):
    """The one rule *owner* declares in *family*, or a failed assertion."""
    rules = [rule for rule in catalog.behavior_rules(owner) if rule.family is family]
    assert len(rules) == 1, f"{owner} declares {len(rules)} {family.value} rules"
    return rules[0]


def test_the_three_families_compile_from_declarations_alone(declared) -> None:
    """The premise: nothing but a registry entry stands behind these owners."""
    amp, aura, lifeline = declared
    assert _rule(amp, RuleFamily.DELTA_AMP).payload.subject is Subject.HOLDER
    assert _rule(aura, RuleFamily.ALLY_PACKET).payload.producer.value == "unmake"
    assert _rule(lifeline, RuleFamily.THRESHOLD_DEFENSE)
    for owner in declared:
        assert catalog.behavior_rules(owner), f"{owner} compiles no rule"


def test_the_pair_engine_prices_a_declaration_only_amp(declared) -> None:
    """Clause 1: the holder's own engine multiplies by the declared fraction.

    The expected ratio is read back through the interpreter from the same
    references the declaration holds, so this asserts the engine and the
    declaration agree rather than that the engine reproduces a number somebody
    captured once.  A pinned constant here would still pass if both moved.
    """
    amp, _, _ = declared
    slot = delta_amp.resolve_slot(
        (amp,),
        AmpChainSlot.WHOLE_TOTAL,
        level=18,
        fight_duration_seconds=FIGHT_DURATION,
        target_bonus_health=0.0,
        holder_is_melee=False,
    )
    assert slot is not None, "the declared whole-total slot resolved to nothing"
    (fraction,) = slot.fractions
    assert fraction > 0.0

    control = _fight(())
    priced = _fight((amp,))
    assert priced["total_damage"] == pytest.approx(
        control["total_damage"] * (1.0 + fraction)
    )
    assert f"damage_amp_{amp}" in priced["breakdown"]
    assert f"damage_amp_{amp}" not in control["breakdown"]


def test_the_receipt_walk_applies_the_aura_to_others_and_not_the_holder(
    declared,
) -> None:
    """Clause 2, and the incident's own handshake.

    One packet per enemy, none for the holder or his ally, and every packet
    carrying ``owner`` so the pair engine's half and the walk's half can never
    both price the same participant.  The multiplier is re-read from the
    declaration for the same reason the amp's fraction is.
    """
    _, aura, _ = declared
    holder = _actor("main:Holder", "main", (aura,))
    ally = _actor("ally:Friend", "ally", ())
    enemy = _actor("enemy:Foe", "enemy", ())
    other_enemy = _actor("enemy:Foe2", "enemy", ())
    roster = [holder, ally, enemy, other_enemy]

    packets = derive_item_support_effects(holder, {"damage_events": []}, roster)
    curse = [packet for packet in packets if packet["kind"] == "damage_modifier"]
    declared_rate = float(AURA_ENTRY["magic_damage_amp"])

    assert {packet["target"] for packet in curse} == {
        enemy.participant_id,
        other_enemy.participant_id,
    }
    assert holder.participant_id not in {packet["target"] for packet in curse}
    assert ally.participant_id not in {packet["target"] for packet in curse}
    for packet in curse:
        assert packet["owner"] == holder.participant_id
        assert packet["multiplier"] == pytest.approx(1.0 + declared_rate)
        # D-04: both restriction axes are required and neither is empty-means-
        # all, so the packet carries what the declaration says it modifies.
        assert packet["damage_classes"] == frozenset({DamageClass.MAGIC})
        assert packet["attack_classes"] == frozenset(AttackClass)


def test_the_compiled_walk_matches_or_receipts_every_declaration(declared) -> None:
    """Clause 3: matched, or refused by name — never dropped.

    Both answers are present, which is why the three owners are worth
    having: the lifeline is representable and folds to ``Compilable`` in
    every scope; the amp is representable too since H5's stage taught the
    kernel a timed, typed damage modifier, and it is asserted against the
    one symbol every amp declares so it cannot have become compilable by
    some other route; and the aura is the support kernel's own refusal,
    naming the packet kind it still cannot stage.  A refusal that did not
    name the kernel would be indistinguishable from an item nobody looked
    at.
    """
    amp, aura, lifeline = declared
    for scope in ReceiptScope:
        assert isinstance(interpreters.compilability_for(lifeline, scope), Compilable)

    amp_verdict = interpreters.compilability_for(
        amp, ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER
    )
    assert isinstance(amp_verdict, Compilable)
    assert isinstance(catalog.AMP_COMPILABILITY, Compilable)

    aura_verdict = interpreters.compilability_for(
        aura, ReceiptScope.SUPPORT_TEMPLATE_SHAPE
    )
    assert isinstance(aura_verdict, ReceiptOnly)
    assert "compiled score kernel" in aura_verdict.reason
    assert "damage_modifier" in aura_verdict.reason


def test_the_light_tuple_path_raises_rather_than_pricing_a_declaration_at_zero(
    declared, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clause 4: the one failure a returned number could not disclose.

    A holder whose mechanic reads a raw stream cannot be scanned off the
    positional score-only ledger — every scan reads it as an empty stream and
    prices the item at zero *without failing*, which is the incident's shape
    exactly.  So the declaration is given a capability that reads a raw
    stream, and the light ledger is handed to the scan: it raises, and the
    message names the holder and the stream it could not read.

    The negative half is asserted with it: the same holder against the dict
    ledger raises nothing, so the tripwire is the ledger shape and not the
    holder's presence.
    """
    _, aura, _ = declared
    capability = trigger_stream.MechanicCapability(
        mechanic="declaration_testbed_aura.unmake",
        owner=trigger_stream.ItemOwner(aura),
        engine=trigger_stream.Engine.WALK,
        reads=frozenset({trigger_stream.Stream.DAMAGE}),
        needs=frozenset(),
        authority=Authority.COUPLED_ONLY,
        pairing=trigger_stream.Pairing.SOLO,
        pair_of=None,
        divergence_ref=None,
        impl="item_support_effects.derive_item_support_effects",
        packet_source="Abyssal Mask — Unmake",
        view_tags=MappingProxyType({trigger_stream.Engine.WALK: ViewTag.APPLIED}),
        holder_stacking=None,
    )
    grown = MappingProxyType(
        {**trigger_stream.CAPABILITIES, capability.mechanic: capability}
    )
    monkeypatch.setattr(trigger_stream, "CAPABILITIES", grown)
    trigger_stream.tuple_incapable_items.cache_clear()
    trigger_stream.streams_for.cache_clear()
    try:
        assert aura in trigger_stream.tuple_incapable_items()
        require_event_view({"damage_events": []}, (aura,))
        with pytest.raises(EventViewStarvationError) as raised:
            require_event_view({"damage_events_tuple": True}, (aura,))
        assert aura in str(raised.value)
        assert "damage_events" in str(raised.value)
        assert "STARVED" in str(raised.value)
    finally:
        trigger_stream.tuple_incapable_items.cache_clear()
        trigger_stream.streams_for.cache_clear()


def test_deleting_an_interpreter_withholds_the_synthetic_item_too(
    declared, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal is not a property of being a real item.

    Criterion 11 is asserted per family over the cached registries; here it is
    asserted over an owner that has no engine code of its own, which is the
    only way to see that the *interpreter* is what produces the number rather
    than something the item's own branch would have produced anyway.
    """
    amp, _, lifeline = declared
    from src.calculator import item_coverage

    for owner, family, lane in (
        (amp, RuleFamily.DELTA_AMP, EngineLane.PAIR_ENGINE),
        (lifeline, RuleFamily.THRESHOLD_DEFENSE, EngineLane.DEFENSE_RESOLVER),
    ):
        needed = frozenset({lane})
        assert item_coverage.item_model_coverage(owner, needed).status != "withheld"
        monkeypatch.setattr(
            item_coverage,
            "INTERPRETERS",
            {
                key: value
                for key, value in interpreters.INTERPRETERS.items()
                if key != (family, lane)
            },
        )
        coverage = item_coverage.item_model_coverage(owner, needed)
        assert coverage.status == "withheld"
        assert f"{family.value}/{lane.value}" in coverage.reason
        monkeypatch.setattr(item_coverage, "INTERPRETERS", interpreters.INTERPRETERS)


def test_no_file_outside_this_fixture_names_a_synthetic_owner() -> None:
    """The source assertion criterion 10 requires.

    The whole argument rests on these owners existing only as declarations, so
    a name that leaked into ``src/`` — a branch, a set membership, a coverage
    sentence — would silently turn the acceptance property into a test of that
    branch.  ``interpreters/`` is the one package the criterion exempts, and it
    names none of them either, which is asserted rather than assumed.
    """
    synthetic = (AMP, AURA, LIFELINE)
    offenders = []
    for root in ("src", "tests", "scripts"):
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if path.resolve() == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            offenders.extend(
                f"{path.relative_to(REPO_ROOT).as_posix()}: {name}"
                for name in synthetic
                if name in text
            )
    assert offenders == []


def test_the_synthetic_entries_are_gone_once_the_fixture_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And they leave nothing behind: the registries are as they were.

    Written as its own case rather than trusted to ``monkeypatch``, because a
    fixture that leaked one entry would make every later test in the session
    run against a registry this file grew — including the frontier's counters.
    """
    del monkeypatch
    for name in (AMP, AURA, LIFELINE):
        assert name not in item_effects.ITEM_EFFECTS
        assert name not in item_effects.ALLY_ITEM_EFFECTS
        assert catalog.behavior_rules(name) == ()


def test_this_file_is_the_declared_front_door_for_the_property() -> None:
    """The fixture's own shape: three owners, declared once, in one place."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert {"AMP", "AURA", "LIFELINE"} <= assigned
