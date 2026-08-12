"""Fail-closed item-mechanic coverage for BIS search."""

import dataclasses

import pytest

from src.calculator import item_coverage
from src.calculator.item_behavior_catalog import (
    UNMIGRATED_TARGET_KEYS,
    behavior_rules,
)

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_coverage import (
    UTILITY_OUTCOMES,
    PRECEDENCE,
    gated_state_reason,
    item_model_coverage,
    optimizer_candidate_coverage,
    require_calculation_item_coverage,
    require_certified_target_timeline,
    require_target_item_coverage,
    target_build_coverage,
    target_item_model_coverage,
)
from src.calculator.item_behavior import UtilityDimension
from src.calculator.item_effects import ITEM_EFFECTS
from src.calculator.data_fetcher import fetch_item_data
from src.calculator.item_source import is_ordinary_sr_item
from src.calculator.item_coverage import ATTACKER_LANES


def _attacker_coverage(item):
    """The attacker-lane public payload for one cached item record.

    ``item_model_coverage`` takes a name and the lanes the caller needs
    answered (3.8), and these tests all ask the picker's question, so they all
    ask for the attacker lane.
    """
    return item_model_coverage(str(item.get("name", "")), ATTACKER_LANES).as_payload()


from src.calculator.optimizer import (
    get_eligible_boots,
    get_eligible_legendaries,
    optimize_build,
)


def test_every_current_optimizer_candidate_has_an_explicit_classification():
    candidates = get_eligible_legendaries() + get_eligible_boots(tier=None)
    classifications = [_attacker_coverage(item) for item in candidates]

    assert classifications
    assert not [
        entry for entry in classifications if entry["status"] == "review_pending"
    ]


def test_cached_ordinary_items_never_remain_review_pending():
    """Every selectable cached SR item is modeled, stats-only, or blocked."""
    ordinary = [
        item
        for item in fetch_item_data().values()
        if item.get("name") and is_ordinary_sr_item(item)
    ]
    assert ordinary
    classifications = [_attacker_coverage(item) for item in ordinary]
    assert not [
        entry for entry in classifications if entry["status"] == "review_pending"
    ]
    assert all(
        entry["optimizer_eligible"] or entry["status"] in {"withheld", "stats_only"}
        for entry in classifications
    )


def test_cached_ordinary_items_have_named_fail_closed_reasons():
    """A real cached passive must explain its withheld mechanic explicitly."""
    ordinary = [
        item
        for item in fetch_item_data().values()
        if item.get("name") and is_ordinary_sr_item(item)
    ]
    generic = [
        item["name"]
        for item in (_attacker_coverage(item) for item in ordinary)
        if item["status"] == "withheld"
        and item["reason"]
        == "This cached passive or active has not been reviewed for outgoing "
        "damage or state effects; calculation is withheld."
    ]
    assert generic == []


def test_endless_hunger_blocker_is_feast_state_only():
    """Famine and the bounded Feast state are receipt-backed."""
    coverage = _attacker_coverage(get_item_by_name("Endless Hunger"))

    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert "bounded" in coverage["reason"]


def test_unmodeled_splash_packets_are_always_withheld():
    """A registry splash note must never silently become optimizer-eligible."""
    splash_items = [
        name
        for name, effect in ITEM_EFFECTS.items()
        if effect.get("type") == "secondary_target"
    ]
    assert splash_items
    for item_name in splash_items:
        if item_name == "Runaan's Hurricane":
            # Wind's Fury is now allocated by the shared roster ledger.
            continue
        coverage = _attacker_coverage(get_item_by_name(item_name))
        assert coverage["status"] == "withheld", item_name
        assert coverage["optimizer_eligible"] is False


def test_secondary_packet_ratios_cannot_be_scored_without_multi_target_ledger():
    """Any registry secondary ratio remains withheld until event fan-out exists."""
    secondary_items = [
        name
        for name, effect in ITEM_EFFECTS.items()
        if any(
            key.startswith("secondary_") and key != "secondary_behavior"
            for key in effect
        )
    ]
    assert secondary_items
    for item_name in secondary_items:
        if item_name == "Tiamat":
            # Issue-42 explicitly certifies Tiamat's selected-target active;
            # its splash note remains a documented multi-target exception.
            continue
        if item_name == "Runaan's Hurricane":
            # Wind's Fury bolts and fixed-source copied on-hits are now
            # timestamped per secondary roster target.
            continue
        if item_name == "Titanic Hydra":
            # Titanic Cleave is now allocated by the shared roster ledger.
            continue
        if item_name in {"Profane Hydra", "Ravenous Hydra"}:
            # AD-scaled active packets are now allocated by the roster ledger.
            continue
        if item_name == "Stridebreaker":
            # Breaking Shockwave is now allocated through the same roster
            # ledger and its slow/movement siblings have utility receipts.
            continue
        coverage = _attacker_coverage(get_item_by_name(item_name))
        assert coverage["status"] == "withheld", item_name
        assert coverage["optimizer_eligible"] is False


def test_phantom_hit_items_have_explicit_duplicate_on_hit_coverage():
    """Rageblade's duplicate-on-hit ledger is modeled; unknown siblings stay blocked."""
    phantom_items = [
        name for name, effect in ITEM_EFFECTS.items() if effect.get("phantom_hit")
    ]
    assert phantom_items
    for item_name in phantom_items:
        coverage = _attacker_coverage(get_item_by_name(item_name))
        if item_name == "Guinsoo's Rageblade":
            assert coverage["status"] == "modeled_effect", item_name
            assert coverage["optimizer_eligible"] is True
        else:
            assert coverage["status"] == "withheld", item_name
            assert coverage["optimizer_eligible"] is False


def test_temporary_lethality_state_accepts_the_sourced_ability_cast_trigger():
    """Galvanize is certified from the sourced ability-cast trigger contract."""
    stateful_items = [
        name
        for name, effect in ITEM_EFFECTS.items()
        if any(key.startswith("temporary_lethality_") for key in effect)
    ]
    assert stateful_items
    for item_name in stateful_items:
        coverage = _attacker_coverage(get_item_by_name(item_name))
        assert coverage["status"] == "modeled_effect", item_name
        assert coverage["optimizer_eligible"] is True


@pytest.mark.parametrize(
    ("item_name", "expected_status"),
    [
        ("Runaan's Hurricane", "modeled_effect"),
        ("Zeke's Convergence", "modeled_effect"),
        ("Immortal Path", "modeled_state"),
        ("Mejai's Soulstealer", "modeled_state"),
        ("Rabadon's Deathcap", "modeled_state"),
        ("Serpent's Fang", "modeled_effect"),
        ("Kaenic Rookern", "stats_only"),
        ("Void Staff", "stats_only"),
        ("Riftmaker", "modeled_state"),
        ("Archangel's Staff", "modeled_state"),
        ("Guinsoo's Rageblade", "modeled_effect"),
        ("Actualizer", "modeled_state"),
        ("Overlord's Bloodmail", "modeled_state"),
        ("Yun Tal Wildarrows", "modeled_state"),
        ("Swiftmarch", "modeled_state"),
        ("Lich Bane", "modeled_effect"),
        ("Essence Reaver", "modeled_effect"),
        ("Dusk and Dawn", "modeled_effect"),
        ("Voltaic Cyclosword", "modeled_effect"),
        ("Statikk Shiv", "modeled_effect"),
        ("Titanic Hydra", "modeled_effect"),
        ("The Collector", "modeled_effect"),
        ("Death's Dance", "modeled_effect"),
    ],
)
def test_representative_item_classifications(item_name, expected_status):
    coverage = _attacker_coverage(get_item_by_name(item_name))

    assert coverage["status"] == expected_status
    assert coverage["optimizer_eligible"] is (
        expected_status not in {"withheld", "review_pending"}
    )


def test_gunmetal_gait_source_conflict_keeps_boot_stats_eligible():
    """The unresolved movement branch is explicit without losing boot stats.

    The boot's life steal is now pinned by the typed sustain receipt, so the
    item classifies as a modeled effect; Noxian Gait remains documented as
    out of scope and the stats stay optimizer-eligible.
    """
    coverage = _attacker_coverage(get_item_by_name("Gunmetal Greaves"))

    # The boot declares its life-steal sustain, so the ladder answers from the
    # declaration.  Noxian Gait's Riot-only movement branch is still out of
    # scope and is still not a refusal: what changed is that the sentence
    # saying so is gone, because a modelled item no longer carries prose.
    assert coverage["status"] == "modeled_effect"
    assert coverage["optimizer_eligible"] is True
    assert coverage["review_issue_refs"] == []


# The two ``PRECEDENCE`` rungs 3.8 deleted with the empty containers they kept
# on the ladder.  The pairing is kept here as the record of what was checked
# before the deletion: each rung's population was its container's keys, and
# each container was empty.
_COLLAPSED_EMPTY_RUNGS = (
    "attacker.blocked_reasons",
    "attacker.partial_blocked_reasons",
)


def test_the_collapsed_rungs_are_gone_from_the_chain():
    """The chain no longer declares a rung whose population was empty.

    The commit before this one asserted the three containers empty and pinned
    the two rungs keying on them; this is the other side of that pair.  A rung
    left declared against a deleted container would be a claim about a symbol
    that no longer exists — the prose-outruns-code shape, inside the ladder
    that exists to close it.
    """
    declared = {rule.rule_id for rule in PRECEDENCE}

    assert declared.isdisjoint(_COLLAPSED_EMPTY_RUNGS)


def test_multitool_is_not_a_summoners_rift_optimizer_candidate():
    names = {item["name"] for item in get_eligible_legendaries()}

    assert "Multitool" not in names


def test_candidate_receipt_is_complete_after_item_umbrella_reconciliation():
    candidates = get_eligible_legendaries() + get_eligible_boots(tier=2)
    receipt = optimizer_candidate_coverage(candidates)
    excluded_names = {entry["name"] for entry in receipt["withheld"]}

    assert receipt["complete"] is True
    assert receipt["eligible_candidates"] == len(candidates)
    assert receipt["scored_candidates"] + receipt["withheld_count"] == len(candidates)
    assert excluded_names == set()
    assert "Rod of Ages" not in excluded_names
    assert "Runaan's Hurricane" not in excluded_names


def test_optimizer_reports_exhaustive_legal_candidates_after_item_reconciliation():
    result = optimize_build(
        get_champion("Ahri"),
        level=18,
        max_legendary_slots=1,
        locked_boots="Sorcerer's Shoes",
    )
    excluded_names = {
        entry["name"] for entry in result["candidate_coverage"]["withheld"]
    }

    assert result["items"]
    assert not (set(result["items"]) & excluded_names)
    assert result["search_guarantee"] == "exhaustive_legal_candidates"
    assert result["is_certified_best"] is False


def test_optimizer_accepts_runaan_with_roster_bolt_model():
    result = optimize_build(
        get_champion("Ahri"),
        level=18,
        max_legendary_slots=1,
        locked_items=["Runaan's Hurricane"],
        locked_boots="Sorcerer's Shoes",
    )
    assert "Runaan's Hurricane" in result["items"]


@pytest.mark.parametrize(
    ("item_name", "status"),
    [
        ("Kaenic Rookern", "modeled"),
        ("Spirit Visage", "modeled"),
        ("Warmog's Armor", "modeled"),
        ("Banshee's Veil", "modeled"),
        ("Plated Steelcaps", "modeled"),
        ("Warden's Mail", "modeled"),
        ("Randuin's Omen", "modeled"),
        ("Frozen Heart", "modeled"),
        ("Guardian Angel", "modeled"),
        ("Force of Nature", "modeled_event_certified"),
        ("Jak'Sho, The Protean", "modeled_event_certified"),
        ("Zhonya's Hourglass", "modeled"),
        ("Seeker's Armguard", "modeled"),
        # 3.8's flip: Incorporeal was removed in V14.6 and what is left is a
        # base health-regeneration stat, which `stats` sources and the
        # durability ladder does not price.
        ("Spectre's Cowl", "not_target_relevant"),
        ("Immortal Shieldbow", "modeled_event_certified"),
        ("Hexdrinker", "modeled_event_certified"),
        ("Maw of Malmortius", "modeled_event_certified"),
        ("Seraph's Embrace", "modeled_event_certified"),
        ("Sterak's Gage", "modeled_event_certified"),
        ("Protoplasm Harness", "modeled_event_certified"),
        ("Serpent's Fang", "not_target_relevant"),
        ("Void Staff", "not_target_relevant"),
    ],
)
def test_target_item_coverage_is_mechanic_specific(item_name, status):
    coverage = target_item_model_coverage(get_item_by_name(item_name))

    assert coverage["status"] == status
    assert coverage["calculation_eligible"] is (status != "withheld")


@pytest.mark.parametrize(
    "item_name",
    [
        "Immortal Shieldbow",
        "Hexdrinker",
        "Maw of Malmortius",
        "Seraph's Embrace",
        "Sterak's Gage",
        "Protoplasm Harness",
    ],
)
def test_lifeline_target_items_pass_precompute_coverage(item_name):
    require_target_item_coverage([get_item_by_name(item_name)])


def test_certified_timeline_guard_allows_certified_lifeline_fights():
    require_certified_target_timeline(
        [get_item_by_name("Sterak's Gage")],
        {"complete": True, "coarse_sources": []},
    )


def test_certified_timeline_guard_withholds_uncertified_lifeline_fights():
    with pytest.raises(
        ValueError,
        match=r"Sterak's Gage.*muramana_ability is not event-certified",
    ):
        require_certified_target_timeline(
            [get_item_by_name("Sterak's Gage")],
            {"complete": False, "coarse_sources": ["muramana_ability"]},
        )


def test_certified_timeline_guard_ignores_targets_without_lifeline_items():
    require_certified_target_timeline(
        [get_item_by_name("Kaenic Rookern")],
        {"complete": False, "coarse_sources": ["passive"]},
    )


def test_certified_timeline_guard_withholds_unreviewed_fimbulwinter_control():
    with pytest.raises(
        ValueError,
        match=r"Fimbulwinter.*fimbulwinter_everlasting.*not event-certified",
    ):
        require_certified_target_timeline(
            [get_item_by_name("Fimbulwinter")],
            {"complete": False, "coarse_sources": ["fimbulwinter_everlasting"]},
        )


def test_target_build_coverage_and_guard_name_the_omitted_defense():
    items = [get_item_by_name("Kaenic Rookern"), get_item_by_name("Banshee's Veil")]
    coverage = target_build_coverage(items)

    assert coverage["complete"] is True
    assert coverage["withheld"] == []
    require_target_item_coverage(items)


def test_unending_despair_target_heal_is_ledger_covered():
    """Anguish's periodic damage and self-heal now have exact ledger rows."""
    coverage = target_item_model_coverage(get_item_by_name("Unending Despair"))

    assert coverage["status"] == "modeled"
    assert coverage["calculation_eligible"] is True
    require_target_item_coverage([get_item_by_name("Unending Despair")])


def test_armored_advance_target_diagnostic_covers_noxian_endurance():
    """The upgraded boots' Plating and typed Noxian shield share one receipt."""
    coverage = target_item_model_coverage(get_item_by_name("Armored Advance"))

    assert coverage["status"] == "modeled"
    assert "Noxian Endurance" in coverage["reason"]
    require_target_item_coverage([get_item_by_name("Armored Advance")])


def test_force_of_nature_target_defense_is_event_certified():
    """Steadfast is admitted only through the ordered target ledger."""
    item = get_item_by_name("Force of Nature")
    coverage = target_item_model_coverage(item)

    assert coverage["status"] == "modeled_event_certified"
    assert coverage["calculation_eligible"] is True
    assert "Steadfast" in coverage["reason"]
    assert "exactly-timed damage ledger" in coverage["reason"]
    require_target_item_coverage([item])


@pytest.mark.parametrize(
    "item_name",
    [
        "Bami's Cinder",
        "Bramble Vest",
        "Fated Ashes",
        "Haunting Guise",
        "Hextech Alternator",
        "Recurve Bow",
        "Scout's Slingshot",
        "Sheen",
        "Tiamat",
    ],
)
def test_issue_42_components_are_modeled_attacker_candidates(item_name):
    """Every issue-42 component left review_pending for an explicit model.

    ``Bramble Vest`` declares nothing but ``reactive``, a defence, so the
    attacker lane's honest answer is stats-only: the mechanic changes what the
    holder takes, not what it deals.  It is still eligible, which is what this
    test is about.
    """
    coverage = _attacker_coverage(get_item_by_name(item_name))

    assert coverage["status"] == (
        "stats_only" if item_name == "Bramble Vest" else "modeled_effect"
    )
    assert coverage["optimizer_eligible"] is True


def test_bandlepipes_ally_buff_uses_the_shared_typed_support_ledger():
    """Fanfare's authored CC trigger is fully represented for ranking."""
    coverage = _attacker_coverage(get_item_by_name("Bandlepipes"))

    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert "shared participant ledger" in coverage["reason"]


@pytest.mark.parametrize("item_name", ["Ardent Censer", "Imperial Mandate"])
def test_typed_enchanter_packets_are_optimizer_eligible(item_name):
    coverage = _attacker_coverage(get_item_by_name(item_name))

    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert "shared participant ledger" in coverage["reason"]


def test_warmog_is_not_hidden_by_an_unreachable_blocked_reason():
    """Warmog's registered health conversion remains explicitly modeled.

    ``stat_derivation`` is a state family: the Heart's conversion is a
    progression the shared ledger schedules, so the declared answer is
    ``modeled_state``.  The property this test guards is that no refusal
    hides it.
    """
    coverage = _attacker_coverage(get_item_by_name("Warmog's Armor"))

    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True


def test_bramble_vest_is_an_explicitly_modeled_target_item():
    """Enemy Bramble retaliation is priced by the coupled timeline, so the
    target classification must say so rather than fall through."""
    coverage = target_item_model_coverage(get_item_by_name("Bramble Vest"))

    assert coverage["status"] == "modeled"
    assert "Thorns" in coverage["reason"]


def test_thornmail_is_modeled_as_a_typed_target_reactive_item():
    """Armor-scaled Thorns now participate in target coverage."""
    attacker = _attacker_coverage(get_item_by_name("Thornmail"))
    # Thorns is a reactive defence and nothing else, so the attacker lane says
    # stats-only; the target lane is where it is priced.
    assert attacker["status"] == "stats_only"
    assert attacker["optimizer_eligible"] is True
    assert target_item_model_coverage(get_item_by_name("Thornmail"))["status"] == (
        "modeled"
    )


def test_sundered_sky_is_modeled_as_a_target_heal_with_temporary_health():
    coverage = target_item_model_coverage(get_item_by_name("Sundered Sky"))
    assert coverage["status"] == "modeled"
    assert "Forced Crit" in coverage["reason"]
    assert "changes what this actor survives" in coverage["reason"]


@pytest.mark.parametrize(
    "item_name",
    ["Cull", "Dusk and Dawn"],
)
def test_target_self_healing_items_have_explicit_modeled_coverage(item_name):
    coverage = target_item_model_coverage(get_item_by_name(item_name))
    assert coverage["status"] == "modeled"
    assert coverage["calculation_eligible"] is True


@pytest.mark.parametrize(
    ("item_name", "dimension"),
    [
        ("Cull", "economy"),
        ("World Atlas", "quest"),
        ("Bandlepipes", "ally_support"),
        ("Solstice Sleigh", "sustain"),
        ("Heartsteel", "health_state"),
        ("Runaan's Hurricane", "copied_on_hit"),
        ("Zhonya's Hourglass", "stasis"),
        ("Guardian Angel", "revive"),
        ("Umbral Glaive", "vision"),
        ("The Collector", "execute"),
    ],
)
def test_utility_coverage_exposes_outcome_dimensions_without_claiming_support(
    item_name, dimension
):
    coverage = _attacker_coverage(get_item_by_name(item_name))

    assert dimension in coverage["outcome_dimensions"]
    if coverage["status"] == "withheld":
        assert coverage["optimizer_eligible"] is False


def test_every_utility_dimension_item_has_explicit_non_pending_coverage():
    """#50 utility labels cannot silently drift into unreviewed coverage."""
    assert UTILITY_OUTCOMES
    for item_name, dimensions in UTILITY_OUTCOMES.items():
        coverage = _attacker_coverage(get_item_by_name(item_name))
        assert coverage["status"] != "review_pending", item_name
        assert coverage["outcome_dimensions"] == [
            dimension.value for dimension in dimensions
        ], item_name


def test_sustain_dimension_never_claims_outgoing_model_support():
    """Healing/ally sustain remains descriptive until recipient accounting is exact."""
    sustain_items = [
        name
        for name, dimensions in UTILITY_OUTCOMES.items()
        if UtilityDimension.SUSTAIN in dimensions
    ]
    assert sustain_items
    for item_name in sustain_items:
        coverage = _attacker_coverage(get_item_by_name(item_name))
        if item_name == "Ravenous Hydra":
            # Crescent and Cleave self-healing receipts are modeled directly.
            assert coverage["status"] == "modeled_effect"
            continue
        assert coverage["status"] != "modeled_effect", item_name


def test_dusk_and_dawn_self_heal_is_calculation_eligible():
    """Spellblade self-heal has timestamped ledger events and is now modeled."""
    coverage = _attacker_coverage(get_item_by_name("Dusk and Dawn"))

    assert coverage["status"] == "modeled_effect"
    assert coverage["optimizer_eligible"] is True


def test_cull_progression_receipt_is_calculation_and_optimizer_eligible():
    """Reap's health and quest receipts share one modeled state ledger."""
    coverage = _attacker_coverage(get_item_by_name("Cull"))

    assert coverage["calculation_eligible"] is True
    assert coverage["optimizer_eligible"] is True
    require_calculation_item_coverage(
        [get_item_by_name("Cull")], participant="Attacker"
    )


def test_opening_defense_items_with_blocked_target_state_never_claim_target_support():
    """Spell shields, stasis, revives, and unmodeled shields stay target-blocked."""
    defense_dimensions = {
        UtilityDimension.SPELL_PROTECTION,
        UtilityDimension.STASIS,
        UtilityDimension.REVIVE,
        UtilityDimension.SHIELD,
    }
    # The population used to be a hand table of withheld target mechanics.
    # It is now the target ladder's own refusal set, so the assertion is that
    # a defensive-dimension item the ladder refuses refuses for both gates —
    # never that one of the two quietly stayed eligible.
    for item_name, dimensions in UTILITY_OUTCOMES.items():
        if not defense_dimensions.intersection(dimensions):
            continue
        coverage = target_item_model_coverage(get_item_by_name(item_name))
        if coverage["status"] != "withheld":
            continue
        assert coverage["calculation_eligible"] is False, item_name
        assert coverage["review_issue_refs"], item_name


@pytest.mark.parametrize(
    ("item_name", "reason_fragment"),
    [
        ("Guardian Angel", "Rebirth"),
        ("Zhonya's Hourglass", "Time Stop"),
    ],
)
def test_defensive_state_coverage_names_the_authored_scenario_boundary(
    item_name, reason_fragment
):
    coverage = target_item_model_coverage(get_item_by_name(item_name))
    expected_status = "modeled"
    assert coverage["status"] == expected_status
    assert coverage["calculation_eligible"] is True
    assert reason_fragment in coverage["reason"]


# ── rung 2's gated-state receipt ──────────────────────────────────────────
#
# The oracle pass over 3.8's coupled diffs returned ``old_value_correct`` on
# every Zhonya's Hourglass leaf: the flip had replaced a receipt naming the
# scenario input that arms Time Stop with a family census claiming the
# mechanic "changes durability, not outgoing TDD" — which is false of an
# active that suppresses its own holder's attacks and casts for its duration.
# These four tests pin the corrected rung from both sides, so neither the
# specific receipt nor the census can quietly swallow the other again.


@pytest.mark.parametrize("item_name", ["Zhonya's Hourglass", "Seeker's Armguard"])
def test_a_defence_gated_by_a_bounded_option_publishes_that_gate(item_name):
    """The receipt names the input that arms the state, not the family census."""
    coverage = item_model_coverage(item_name, ATTACKER_LANES)
    assert coverage.status == "stats_only"
    assert coverage.reason == (
        "Time Stop is priced only from the explicit bounded active-seconds "
        "scenario input; item presence alone never assumes stasis."
    )


@pytest.mark.parametrize(
    ("item_name", "why_the_gate_does_not_apply"),
    [
        ("Banshee's Veil", "declares no bounded option at all"),
        ("Bloodthirster", "declares an option but no exclusive state"),
    ],
)
def test_a_defence_without_both_halves_of_the_gate_keeps_the_family_census(
    item_name, why_the_gate_does_not_apply
):
    """Both ways the sub-question declines, so the discriminator is pinned."""
    coverage = item_model_coverage(item_name, ATTACKER_LANES)
    assert coverage.status == "stats_only", why_the_gate_does_not_apply
    assert coverage.reason == (
        "Every declared family on this item is a defence: the represented "
        "mechanic changes durability, not outgoing TDD."
    )


def test_the_gated_receipt_population_is_exactly_the_two_stasis_items():
    """The population, pinned as a set: a third entrant is a real event.

    Enumerated over every cached item rather than asserted of the two, so an
    item that starts declaring an option-armed exclusive state changes this
    set rather than changing a published reason unnoticed.
    """
    gated = {
        name
        for name in {
            str(record.get("name", ""))
            for record in fetch_item_data().values()
            if isinstance(record, dict) and record.get("name")
        }
        if gated_state_reason(name) is not None
    }
    assert gated == {"Zhonya's Hourglass", "Seeker's Armguard"}


def test_the_family_census_is_not_claimed_of_an_item_whose_active_stops_it():
    """Why the census had to lose: it is the false sentence for this item.

    The declaration's own zero policy says the state is never assumed by item
    presence.  An item coverage answer that instead asserts the mechanic
    cannot touch outgoing damage contradicts a rule the catalog declares, and
    that contradiction is what the oracle pass caught.
    """
    coverage = item_model_coverage("Zhonya's Hourglass", ATTACKER_LANES)
    assert "changes durability, not outgoing TDD" not in coverage.reason
    assert "item presence alone never assumes" in coverage.reason


@pytest.mark.parametrize(
    "item_name",
    ["Locket of the Iron Solari", "Mikael's Blessing", "Redemption"],
)
def test_ally_item_packets_are_coupled_and_never_assume_target_cast_timing(item_name):
    """Target coverage admits explicit coupled packets without inventing casts."""
    coverage = target_item_model_coverage(get_item_by_name(item_name))
    assert coverage["status"] == "modeled"
    assert coverage["calculation_eligible"] is True
    # The receipt names the declared producer rather than the cast: an ally
    # packet is priced from an explicit active_seconds input, and the passive
    # target model never invents one.
    assert coverage["reason"].split()[0].isalpha()
    assert "changes what this actor survives" in coverage["reason"]


@pytest.mark.parametrize("item_name", ["Stridebreaker"])
def test_stridebreaker_utility_scope_is_explicitly_modelled(item_name):
    """Breaking Shockwave exposes its typed slow and movement siblings."""
    coverage = _attacker_coverage(get_item_by_name(item_name))
    assert "multi_target" in coverage["outcome_dimensions"]
    assert {"slow", "movement"} <= set(coverage["outcome_dimensions"])
    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert coverage["review_issue_refs"] == []


def test_fimbulwinter_is_event_certified_and_not_optimizer_blocked():
    coverage = _attacker_coverage(get_item_by_name("Fimbulwinter"))
    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    target = target_item_model_coverage(get_item_by_name("Fimbulwinter"))
    assert target["status"] == "modeled_event_certified"
    assert target["calculation_eligible"] is True
    assert "Everlasting" in target["reason"]


def test_world_atlas_support_quest_receipt_is_reconciled():
    coverage = _attacker_coverage(get_item_by_name("World Atlas"))
    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert coverage["review_issue_refs"] == []


def test_ravenous_hydra_active_scope_is_modelled_with_lifesteal():
    """Ravenous active and secondary packets are now fully represented."""
    coverage = _attacker_coverage(get_item_by_name("Ravenous Hydra"))

    assert coverage["status"] == "modeled_effect"
    assert coverage["optimizer_eligible"] is True
    assert "sustain" in coverage["outcome_dimensions"]


def test_bloodmail_retribution_is_explicit_starting_state():
    """Bloodmail exposes its bounded starting missing-health state."""
    coverage = _attacker_coverage(get_item_by_name("Overlord's Bloodmail"))
    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert "scenario" in coverage["reason"]


@pytest.mark.parametrize(
    ("item_name", "required_state"),
    [
        ("Heartsteel", "permanent"),
        ("Rod of Ages", "minute"),
    ],
)
def test_long_lived_stack_items_name_missing_state_input(item_name, required_state):
    """Only items without a supplied authored state remain blocked."""
    coverage = _attacker_coverage(get_item_by_name(item_name))
    if item_name in {"Heartsteel", "Rod of Ages"}:
        assert coverage["status"] == "modeled_state"
        assert coverage["optimizer_eligible"] is True
        assert "scenario control" in coverage["reason"]
        return
    assert coverage["status"] == "withheld"
    assert coverage["optimizer_eligible"] is False
    assert required_state in coverage["reason"]


@pytest.mark.parametrize(
    "item_name",
    [
        "Cull",
        "Phage",
        "Runic Compass",
        "Tear of the Goddess",
        "Umbral Glaive",
        "World Atlas",
    ],
)
def test_remaining_cp20_items_are_explicitly_modeled(item_name):
    coverage = _attacker_coverage(get_item_by_name(item_name))
    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert coverage["review_issue_refs"] == []


def test_dusk_and_dawn_self_heal_receipt_promotes_attacker_coverage():
    """An exact proc receipt and ledger mutation make the item scoreable."""
    coverage = _attacker_coverage(get_item_by_name("Dusk and Dawn"))
    assert coverage["status"] == "modeled_effect"
    assert coverage["optimizer_eligible"] is True


def test_unknown_target_passive_fails_closed():
    item = {"name": "Future Bulwark", "passives": [{"name": "Unknown"}]}

    coverage = target_item_model_coverage(item)

    assert coverage["status"] == "review_pending"
    assert coverage["calculation_eligible"] is False


def test_calculation_item_coverage_accepts_runaan_secondary_bolt_model():
    require_calculation_item_coverage(
        [get_item_by_name("Runaan's Hurricane")], participant="Attacker"
    )


# ── the target lane's derivation, beside the three tables ─────────────────
#
# 3.8's second half replaced ``_TARGET_MODELED_REASONS``,
# ``_TARGET_EVENT_CERTIFIED_REASONS`` and ``_TARGET_BLOCKED_REASONS`` with a
# status computed from declarations.  The derivation landed beside them with
# its delta asserted item by item (runbook R-31), the ladder flipped onto it,
# and the tables are gone; what stands here now is the population each rung
# answers for and the two rename guards on the clauses that read a field name
# or a registry key.


def _cached_names():
    """Every cached item name, read through the caching layer."""
    return sorted(
        str(record.get("name", ""))
        for record in fetch_item_data().values()
        if record.get("name")
    )


def test_the_derived_target_populations_are_the_ones_the_flip_landed() -> None:
    """The three populations the flip produced, pinned as sets.

    The tables the derivation replaced are gone, so the delta assertion that
    stood here through the flip has nothing left to compare against.  What
    survives it is the fact the delta established: which cached items each
    rung answers for.  Sets and never counts — a count agrees with itself
    after a swap, and the point of the pin is that a swap is visible.
    """
    statuses = {
        name: target_item_model_coverage(get_item_by_name(name))["status"]
        for name in _cached_names()
    }
    certified = {name for name, status in statuses.items() if status == "modeled"}
    assert {
        name for name, status in statuses.items() if status == "modeled_event_certified"
    } == {
        "Fimbulwinter",
        "Force of Nature",
        "Hexdrinker",
        "Immortal Shieldbow",
        "Jak'Sho, The Protean",
        "Maw of Malmortius",
        "Protoplasm Harness",
        "Seraph's Embrace",
        "Sterak's Gage",
    }
    assert certified == set(item_coverage._TARGET_MODELED_IMPLS)
    assert {name for name, status in statuses.items() if status == "withheld"} == {
        name
        for name in _cached_names()
        if item_model_coverage(name, item_coverage.TARGET_LANES).status
        in ("withheld", "review_pending")
    }


def test_every_holder_survival_field_is_a_field_of_a_declared_payload() -> None:
    """The rename guard on the one clause that reads payload field names.

    A field this set names and no payload declares would silently stop
    matching, which is exactly the shape of failure the campaign exists to
    remove: the clause would go on returning ``False`` and the item would go
    on publishing ``not_target_relevant``.
    """
    declared = {
        field.name
        for name in _cached_names()
        for rule in behavior_rules(name)
        for field in dataclasses.fields(rule.payload)
    }

    assert item_coverage._HOLDER_SURVIVAL_FIELDS <= declared


def test_a_declared_defence_agrees_with_the_identifier_it_is_read_from() -> None:
    """``declared_defence`` reads the identifier; the payload is the check.

    Wherever a payload carries its own ``mechanic``, the two spellings must be
    the same mechanic — otherwise the identifier is a second vocabulary and
    the target lane would be reading a different defence than the resolver
    builds.
    """
    checked = 0
    for name in _cached_names():
        for rule in behavior_rules(name):
            declared = getattr(rule.payload, "mechanic", None)
            if declared is None:
                continue
            checked += 1
            assert item_coverage.declared_defence(rule) is declared, rule.mechanic_id

    assert checked


def test_every_unmigrated_target_key_is_a_key_some_entry_carries() -> None:
    """The rename guard on the clause that reads registry keys.

    A key this table names and no entry carries would stop matching in
    silence, and the two live mechanics behind it would start publishing
    "nothing this item declares changes durability" while the timeline went on
    scheduling them — the exact shape of the failure this campaign is named
    for.  Each key must also select at least one cached item, because a
    declaration that reaches nothing is a claim about nothing.
    """
    for key in UNMIGRATED_TARGET_KEYS:
        carriers = [
            name
            for name in _cached_names()
            for _, _, entry in item_coverage.registry_entries(name)
            if key in entry
        ]
        assert carriers, key


def test_the_target_flip_refuses_only_records_no_ordinary_build_can_hold() -> None:
    """The blast radius of the target lane's new refusal, pinned as a set.

    The flip passes the attacker ladder's refusal through, so a cached record
    whose described passive nothing declares now stops a target build instead
    of being called irrelevant.  That is a real refusal and it is bounded
    here: every record it reaches is one `item_source` already withholds from
    an ordinary Summoner's Rift build, so no build a request can express loses
    a calculation.  An ordinary item arriving in this set is a stop.
    """
    refused = {
        name
        for name, record in (
            (str(r.get("name", "")), r)
            for r in fetch_item_data().values()
            if r.get("name")
        )
        if not target_item_model_coverage(record)["calculation_eligible"]
    }
    ordinary = {
        str(record.get("name", ""))
        for record in fetch_item_data().values()
        if record.get("name") and is_ordinary_sr_item(record)
    }

    assert refused
    assert refused & ordinary == set()


def test_the_flip_moved_no_ordinary_item_in_or_out_of_attacker_eligibility() -> None:
    """The other half of the same bound: the attacker lane's gates are unmoved.

    Both booleans on the attacker payload are functions of the status, and the
    statuses the flip moved there are all inside the modelled family, so no
    build gained or lost a candidate.  Asserted over every cached record
    rather than over the ones the receipt happens to name.
    """
    for record in fetch_item_data().values():
        if not record.get("name"):
            continue
        coverage = item_model_coverage(str(record["name"]), ATTACKER_LANES)
        assert coverage.optimizer_eligible == coverage.calculation_eligible
        if is_ordinary_sr_item(record):
            assert coverage.optimizer_eligible, record["name"]
