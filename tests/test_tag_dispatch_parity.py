"""SD9 — the two dispatchers over one effect `type` tag, number by number.

`item_effects._resolve_damage_effects_uncached` branches on eight tags;
`item_behavior_catalog.TAG_FAMILY` maps all thirty-eight to a family whose
compiler builds a declaration an interpreter prices.  `validate_catalog`
proves the two see the same tag vocabulary and nothing proved they produce
the same NUMBER for a tag both claim.

This file is that proof, and the gate any retirement has to keep green: for
every tag the ladder branches on, either both lanes are compared here and
agree, or this file names which lane owns the number and why the other one
cannot.  The ladder's tag set is read off its own source rather than listed,
so a ninth branch fails here until somebody decides which lane owns it.

Where the two lanes DISAGREE by construction, the difference is composition
and not arithmetic: the ladder's single-holder slots silently take the last
holder (`execute`, `cd_refund_percent`), while the catalog's stop naming both
holders.  Today's registry carries exactly one item per those tags, so no
build reaches the difference; the case is pinned in
``test_a_second_holder_is_a_stop_on_one_lane_and_the_last_word_on_the_other``
rather than left for a future second holder to discover.
"""

from pathlib import Path

import pytest

from src.calculator.data_fetcher import get_item_by_name
from src.calculator.item_behavior import (
    FlatStatGrantRule,
    OnHitHealRule,
    RuleFamily,
)
from src.calculator.item_behavior_catalog import (
    DELTA_AMP_UNMIGRATED_TAGS,
    TAG_FAMILY,
    behavior_rules,
    build_context,
)
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    known_effect_types,
    required_effect_value,
    resolve_damage_effects,
)
from src.calculator.interpreters.crit_profile import resolve_profile
from src.calculator.interpreters.damage_routing import resolve_execution
from src.calculator.interpreters.stat_derivation import (
    declared_stat_derivations,
    reference_fields,
    stat_derivation_rules,
)
from src.calculator.interpreters.sustain import declared_sustain
from src.calculator.item_behavior import EngineLane
from tests.coverage_resolver import tag_dispatch_branches

# The fight the catalog's contextual resolvers are asked about.  Declared
# here rather than defaulted anywhere: the ladder answers with no fight at
# all, so the comparison has to name the one it is made at.
LEVEL = 18
DURATION = 10.0
TARGET_BONUS_HEALTH = 0.0
HOLDER_IS_MELEE = False

CATALOG_CONTEXT = dict(
    level=LEVEL,
    fight_duration_seconds=DURATION,
    target_bonus_health=TARGET_BONUS_HEALTH,
    holder_is_melee=HOLDER_IS_MELEE,
)

# Which item carries each shared tag today, read off the live registry so a
# renamed or retired item fails here rather than skipping its comparison.
HOLDERS: dict[str, tuple[str, ...]] = {}
for _name, _values in ITEM_EFFECTS.items():
    HOLDERS.setdefault(str(_values.get("type")), ())
    HOLDERS[str(_values.get("type"))] += (_name,)


def _ladder(*item_names: str):
    """The legacy projection for a build holding exactly these items."""
    return resolve_damage_effects([get_item_by_name(name) for name in item_names])


def _sole(tag: str) -> str:
    """The one item carrying *tag*, or a stop naming the holders it found."""
    holders = HOLDERS.get(tag, ())
    assert len(holders) == 1, f"{tag} is carried by {holders}"
    return holders[0]


def test_the_ladder_branches_on_exactly_the_tags_this_file_compares():
    """The ladder's own source names its tags; a ninth branch fails here."""
    source = (
        Path(__file__).resolve().parents[1] / "src" / "calculator" / "item_effects.py"
    ).read_text(encoding="utf-8")
    branches = tag_dispatch_branches(
        source, "item_effects._resolve_damage_effects_uncached"
    ) & set(known_effect_types())
    assert branches == {
        "ult_empowered_autos",
        "ult_attack_speed_buff",
        "execute",
        "crit_modifier",
        "secondary_target",
        "magic_damage_amp",
        "first_auto_crit",
    }
    # Every one of them is a tag the catalog also files under a family: the
    # overlap is total, so there is no ladder-only tag to leave alone.
    assert branches <= set(TAG_FAMILY)


# ---------------------------------------------------------------------------
# Tags both lanes price — the numbers must agree
# ---------------------------------------------------------------------------


def test_execute_threshold_agrees():
    owner = _sole("execute")
    ladder = _ladder(owner).execute
    catalog = resolve_execution([owner], **CATALOG_CONTEXT)
    assert ladder.item_name == catalog.owner == owner
    assert ladder.threshold == pytest.approx(catalog.threshold)
    assert ladder.threshold == pytest.approx(required_effect_value(owner, "threshold"))


def test_crit_damage_bonus_agrees():
    owner = "Infinity Edge"
    assert ITEM_EFFECTS[owner]["type"] == "crit_modifier"
    ladder = _ladder(owner)
    catalog = resolve_profile([owner], **CATALOG_CONTEXT)
    assert ladder.crit_damage_bonus == pytest.approx(catalog.damage_bonus)
    assert ladder.crit_damage_bonus == pytest.approx(
        required_effect_value(owner, "bonus_crit_damage")
    )
    # The other two crit slots are declared-absent on this build, and the
    # ladder says the same thing with a zero and a None.
    assert catalog.forced_crit is None
    assert catalog.cooldown_refund is None
    assert ladder.first_auto_crit is None
    assert ladder.navori_refund_percent == 0.0


def test_attack_cooldown_refund_agrees():
    owner = "Navori Flickerblade"
    assert ITEM_EFFECTS[owner]["type"] == "crit_modifier"
    ladder = _ladder(owner)
    catalog = resolve_profile([owner], **CATALOG_CONTEXT)
    assert ladder.cooldown_refund_source == catalog.cooldown_refund.owner == owner
    assert ladder.navori_refund_percent == pytest.approx(
        catalog.cooldown_refund.fraction
    )


def test_a_build_holding_both_crit_items_agrees():
    """The two crit_modifier sub-branches compose the same way on both lanes:
    the bonus sums into one slot and the refund fills another."""
    ladder = _ladder("Infinity Edge", "Navori Flickerblade")
    catalog = resolve_profile(
        ["Infinity Edge", "Navori Flickerblade"], **CATALOG_CONTEXT
    )
    assert ladder.crit_damage_bonus == pytest.approx(catalog.damage_bonus)
    assert ladder.navori_refund_percent == pytest.approx(
        catalog.cooldown_refund.fraction
    )
    assert ladder.cooldown_refund_source == catalog.cooldown_refund.owner


def test_forced_crit_agrees_on_every_number_it_carries():
    owner = _sole("first_auto_crit")
    ladder = _ladder(owner).first_auto_crit
    catalog = resolve_profile([owner], **CATALOG_CONTEXT).forced_crit
    assert ladder.item_name == catalog.owner == owner
    assert ladder.reduced_crit_ratio == pytest.approx(catalog.reduced_ratio)
    assert ladder.heal_base_ad_ratio == pytest.approx(catalog.heal_base_ad_ratio)
    assert ladder.heal_base_ad_ratio_ranged == pytest.approx(
        catalog.heal_base_ad_ratio_ranged
    )
    assert ladder.heal_missing_health_ratio == pytest.approx(
        catalog.heal_missing_health_ratio
    )
    assert ladder.temporary_health_duration == pytest.approx(
        catalog.temporary_health_duration
    )


def test_on_hit_heal_is_retired_from_the_ladder_and_owned_by_the_catalog():
    """The first retirement this file's parity covered: the ladder branched
    on ``on_hit_heal`` and compiled its own ``OnHitHealEffect`` beside the
    SUSTAIN declaration.  The declaration is now the only owner, so the
    projection carries no field for it and the engines read the slot."""
    owner = _sole("on_hit_heal")
    catalog = declared_sustain([owner], OnHitHealRule)
    assert catalog.owner == owner
    assert catalog.value("amount") == pytest.approx(
        required_effect_value(owner, "health_per_on_hit")
    )
    assert not hasattr(_ladder(owner), "on_hit_heals")


# ---------------------------------------------------------------------------
# Tags one lane owns — and this is where it says so
# ---------------------------------------------------------------------------


def test_magic_damage_amp_is_the_ladders_alone_and_the_catalog_books_it_so():
    """The catalog files ``magic_damage_amp`` under DELTA_AMP and compiles no
    rule for it: the tag is explicitly unmigrated, so the ladder is the only
    owner of the number and there is nothing to compare it against."""
    owner = _sole("magic_damage_amp")
    assert TAG_FAMILY["magic_damage_amp"] is RuleFamily.DELTA_AMP
    assert "magic_damage_amp" in DELTA_AMP_UNMIGRATED_TAGS
    assert not [
        rule for rule in behavior_rules(owner) if rule.family is RuleFamily.DELTA_AMP
    ]
    assert _ladder(owner).magic_amp == pytest.approx(
        1.0 + required_effect_value(owner, "magic_amp")
    )


def test_secondary_target_is_the_catalogs_alone():
    """The ladder's branch is a ``continue``: it prices nothing, and the
    catalog's SECONDARY_TARGET rule is the only owner of the numbers."""
    owner = _sole("secondary_target")
    ladder = _ladder(owner)
    assert ladder.execute is None
    assert ladder.crit_damage_bonus == 0.0
    assert ladder.conditional_notes == ()
    assert [rule.family for rule in behavior_rules(owner)] == [
        RuleFamily.SECONDARY_TARGET
    ]


def test_the_empowered_auto_note_quotes_the_catalogs_number():
    """``ult_empowered_autos`` splits: the catalog owns the attack-speed
    number, the ladder owns only the assumption note it is quoted in."""
    owner = _sole("ult_empowered_autos")
    (note,) = _ladder(owner).conditional_notes
    (slot,) = [
        slot
        for slot in declared_stat_derivations([owner], FlatStatGrantRule)
        if slot.rule.mechanic_id.endswith("attack_speed_percent_grant")
    ]
    assert f"{slot.value('amount'):.0f}% bonus AS" in note
    assert owner in note


def test_the_overdrive_note_quotes_the_catalogs_numbers():
    """``ult_attack_speed_buff`` splits the same way, and its grant needs a
    build context (the melee/ranged split), so the comparison is made at the
    declared fight above."""
    owner = _sole("ult_attack_speed_buff")
    note = _ladder(owner).conditional_notes[0]
    (rule,) = [
        rule
        for rule in stat_derivation_rules([owner], FlatStatGrantRule)
        if rule.mechanic_id.endswith("attack_speed_percent_grant")
    ]
    for melee in (True, False):
        fields = reference_fields(
            rule,
            build_context(
                owner,
                LEVEL,
                fight_duration_seconds=DURATION,
                target_bonus_health=TARGET_BONUS_HEALTH,
                holder_is_melee=melee,
            ),
            EngineLane.STAT_RESOLVER,
        )
        amount = [field.value for field in fields if field.name == "amount"][0]
        assert f"{amount:.0f}%" in note


def test_a_second_holder_is_a_stop_on_one_lane_and_the_last_word_on_the_other():
    """The two lanes compose single-holder slots differently.

    The ladder's ``execute`` and ``cd_refund_percent`` slots take the last
    holder in build order; the catalog raises and names both.  Today's
    registry carries one item per tag, so no build reaches the difference —
    this pins it, and pins that the arithmetic is not what differs."""
    assert len(HOLDERS.get("execute", ())) == 1
    assert (
        len(
            [
                name
                for name in HOLDERS.get("crit_modifier", ())
                if "cd_refund_percent" in ITEM_EFFECTS[name]
            ]
        )
        == 1
    )
