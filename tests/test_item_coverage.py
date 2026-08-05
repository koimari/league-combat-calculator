"""Fail-closed item-mechanic coverage for BIS search."""

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_coverage import (
    _PARTIAL_BLOCKED_REASONS,
    _TARGET_BLOCKED_REASONS,
    _UTILITY_DIMENSIONS,
    item_model_coverage,
    optimizer_candidate_coverage,
    require_calculation_item_coverage,
    require_certified_target_timeline,
    require_target_item_coverage,
    target_build_coverage,
    target_item_model_coverage,
)
from src.calculator.item_effects import ITEM_EFFECTS
from src.calculator.data_fetcher import fetch_item_data
from src.calculator.item_source import is_ordinary_sr_item
from src.calculator.optimizer import (
    get_eligible_boots,
    get_eligible_legendaries,
    optimize_build,
)


def test_every_current_optimizer_candidate_has_an_explicit_classification():
    candidates = get_eligible_legendaries() + get_eligible_boots(tier=None)
    classifications = [item_model_coverage(item) for item in candidates]

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
    classifications = [item_model_coverage(item) for item in ordinary]
    assert not [
        entry for entry in classifications if entry["status"] == "review_pending"
    ]
    assert all(
        entry["optimizer_eligible"] or entry["status"] in {"blocked", "stats_only"}
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
        for item in (item_model_coverage(item) for item in ordinary)
        if item["status"] == "blocked"
        and item["reason"]
        == "This cached passive or active has not been reviewed for outgoing "
        "damage or state effects; calculation is withheld."
    ]
    assert generic == []


def test_endless_hunger_blocker_is_feast_state_only():
    """Famine and the bounded Feast state are receipt-backed."""
    coverage = item_model_coverage(get_item_by_name("Endless Hunger"))

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
        coverage = item_model_coverage(get_item_by_name(item_name))
        assert coverage["status"] == "blocked", item_name
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
        coverage = item_model_coverage(get_item_by_name(item_name))
        assert coverage["status"] == "blocked", item_name
        assert coverage["optimizer_eligible"] is False


def test_phantom_hit_items_have_explicit_duplicate_on_hit_coverage():
    """Rageblade's duplicate-on-hit ledger is modeled; unknown siblings stay blocked."""
    phantom_items = [
        name for name, effect in ITEM_EFFECTS.items() if effect.get("phantom_hit")
    ]
    assert phantom_items
    for item_name in phantom_items:
        coverage = item_model_coverage(get_item_by_name(item_name))
        if item_name == "Guinsoo's Rageblade":
            assert coverage["status"] == "modeled_effect", item_name
            assert coverage["optimizer_eligible"] is True
        else:
            assert coverage["status"] == "blocked", item_name
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
        coverage = item_model_coverage(get_item_by_name(item_name))
        assert coverage["status"] == "modeled_effect", item_name
        assert coverage["optimizer_eligible"] is True


@pytest.mark.parametrize(
    ("item_name", "expected_status"),
    [
        ("Runaan's Hurricane", "modeled_effect"),
        ("Zeke's Convergence", "modeled_effect"),
        ("Immortal Path", "modeled_state"),
        ("Mejai's Soulstealer", "modeled_state"),
        ("Rabadon's Deathcap", "modeled_effect"),
        ("Serpent's Fang", "modeled_effect"),
        ("Kaenic Rookern", "stats_only"),
        ("Void Staff", "stats_only"),
        ("Riftmaker", "modeled_effect"),
        ("Archangel's Staff", "modeled_state"),
        ("Guinsoo's Rageblade", "modeled_effect"),
        ("Actualizer", "modeled_state"),
        ("Overlord's Bloodmail", "modeled_state"),
        ("Yun Tal Wildarrows", "modeled_effect"),
        ("Swiftmarch", "modeled_effect"),
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
    coverage = item_model_coverage(get_item_by_name(item_name))

    assert coverage["status"] == expected_status
    assert coverage["optimizer_eligible"] is (
        expected_status not in {"blocked", "review_pending"}
    )


def test_gunmetal_gait_source_conflict_keeps_boot_stats_eligible():
    """The unresolved movement branch is explicit without losing boot stats."""
    coverage = item_model_coverage(get_item_by_name("Gunmetal Greaves"))

    assert coverage["status"] == "stats_only"
    assert coverage["optimizer_eligible"] is True
    assert "Noxian Gait" in coverage["reason"]
    assert "out of scope" in coverage["reason"]


def test_multitool_is_not_a_summoners_rift_optimizer_candidate():
    names = {item["name"] for item in get_eligible_legendaries()}

    assert "Multitool" not in names


def test_candidate_receipt_names_every_withheld_item():
    candidates = get_eligible_legendaries() + get_eligible_boots(tier=2)
    receipt = optimizer_candidate_coverage(candidates)
    excluded_names = {entry["name"] for entry in receipt["excluded"]}

    assert receipt["complete"] is False
    assert receipt["eligible_candidates"] == len(candidates)
    assert receipt["scored_candidates"] + receipt["excluded_count"] == len(candidates)
    assert "Umbral Glaive" in excluded_names
    assert "Rod of Ages" not in excluded_names
    assert "Runaan's Hurricane" not in excluded_names


def test_optimizer_withholds_unmodeled_candidates_and_returns_receipt():
    result = optimize_build(
        get_champion("Ahri"),
        level=18,
        max_legendary_slots=1,
        locked_boots="Sorcerer's Shoes",
    )
    excluded_names = {
        entry["name"] for entry in result["candidate_coverage"]["excluded"]
    }

    assert result["items"]
    assert not (set(result["items"]) & excluded_names)
    assert result["search_guarantee"] == "exhaustive_modeled_candidates"
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
        ("Spectre's Cowl", "modeled"),
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
    assert coverage["calculation_eligible"] is (status != "blocked")


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
    assert coverage["blocked"] == []
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
    assert "maximum-stack bonus resistance" in coverage["reason"]
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
    """Every issue-42 component left review_pending for an explicit model."""
    coverage = item_model_coverage(get_item_by_name(item_name))

    assert coverage["status"] == "modeled_effect"
    assert coverage["optimizer_eligible"] is True


def test_bandlepipes_ally_buff_uses_the_shared_typed_support_ledger():
    """Fanfare's authored CC trigger is fully represented for ranking."""
    coverage = item_model_coverage(get_item_by_name("Bandlepipes"))

    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert "shared participant support ledger" in coverage["reason"]


@pytest.mark.parametrize("item_name", ["Ardent Censer", "Imperial Mandate"])
def test_typed_enchanter_packets_are_optimizer_eligible(item_name):
    coverage = item_model_coverage(get_item_by_name(item_name))

    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    assert "shared participant support ledger" in coverage["reason"]


def test_warmog_is_not_hidden_by_an_unreachable_blocked_reason():
    """Warmog's registered health conversion remains explicitly modeled."""
    coverage = item_model_coverage(get_item_by_name("Warmog's Armor"))

    assert coverage["status"] == "modeled_effect"
    assert coverage["optimizer_eligible"] is True


def test_bramble_vest_is_an_explicitly_modeled_target_item():
    """Enemy Bramble retaliation is priced by the coupled timeline, so the
    target classification must say so rather than fall through."""
    coverage = target_item_model_coverage(get_item_by_name("Bramble Vest"))

    assert coverage["status"] == "modeled"
    assert "Thorns" in coverage["reason"]


def test_thornmail_is_modeled_as_a_typed_target_reactive_item():
    """Armor-scaled Thorns now participate in target coverage."""
    attacker = item_model_coverage(get_item_by_name("Thornmail"))
    assert attacker["status"] == "modeled_effect"
    assert attacker["optimizer_eligible"] is True
    assert target_item_model_coverage(get_item_by_name("Thornmail"))["status"] == (
        "modeled"
    )


def test_sundered_sky_is_modeled_as_a_target_heal_with_temporary_health():
    coverage = target_item_model_coverage(get_item_by_name("Sundered Sky"))
    assert coverage["status"] == "modeled"
    assert "temporary health" in coverage["reason"]


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
    coverage = item_model_coverage(get_item_by_name(item_name))

    assert dimension in coverage["outcome_dimensions"]
    if coverage["status"] == "blocked":
        assert coverage["optimizer_eligible"] is False


def test_every_utility_dimension_item_has_explicit_non_pending_coverage():
    """#50 utility labels cannot silently drift into unreviewed coverage."""
    assert _UTILITY_DIMENSIONS
    for item_name, dimensions in _UTILITY_DIMENSIONS.items():
        coverage = item_model_coverage(get_item_by_name(item_name))
        assert coverage["status"] != "review_pending", item_name
        assert coverage["outcome_dimensions"] == list(dimensions), item_name


def test_no_stale_partial_state_items_remain_after_shared_ledger_reconciliation():
    """All registered partial-state items are reconciled before ranking."""
    assert _PARTIAL_BLOCKED_REASONS == {}


def test_sustain_dimension_never_claims_outgoing_model_support():
    """Healing/ally sustain remains descriptive until recipient accounting is exact."""
    sustain_items = [
        name
        for name, dimensions in _UTILITY_DIMENSIONS.items()
        if "sustain" in dimensions
    ]
    assert sustain_items
    for item_name in sustain_items:
        coverage = item_model_coverage(get_item_by_name(item_name))
        if item_name == "Ravenous Hydra":
            # Crescent and Cleave self-healing receipts are modeled directly.
            assert coverage["status"] == "modeled_effect"
            continue
        assert coverage["status"] != "modeled_effect", item_name


def test_dusk_and_dawn_self_heal_is_calculation_eligible():
    """Spellblade self-heal has timestamped ledger events and is now modeled."""
    coverage = item_model_coverage(get_item_by_name("Dusk and Dawn"))

    assert coverage["status"] == "modeled_effect"
    assert coverage["optimizer_eligible"] is True


def test_cull_combat_receipt_is_calculation_eligible_but_optimizer_blocked():
    """Reap's health receipt is callable while its quest remains withheld."""
    coverage = item_model_coverage(get_item_by_name("Cull"))

    assert coverage["calculation_eligible"] is True
    assert coverage["optimizer_eligible"] is False
    require_calculation_item_coverage(
        [get_item_by_name("Cull")], participant="Attacker"
    )


def test_opening_defense_items_with_blocked_target_state_never_claim_target_support():
    """Spell shields, stasis, revives, and unmodeled shields stay target-blocked."""
    defense_dimensions = {"spell_protection", "stasis", "revive", "shield"}
    for item_name, dimensions in _UTILITY_DIMENSIONS.items():
        if not defense_dimensions.intersection(dimensions):
            continue
        if item_name not in _TARGET_BLOCKED_REASONS:
            continue
        coverage = target_item_model_coverage(get_item_by_name(item_name))
        assert coverage["status"] == "blocked", item_name
        assert coverage["calculation_eligible"] is False


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


@pytest.mark.parametrize(
    "item_name",
    ["Locket of the Iron Solari", "Mikael's Blessing", "Redemption"],
)
def test_ally_item_packets_are_coupled_and_never_assume_target_cast_timing(item_name):
    """Target coverage admits explicit coupled packets without inventing casts."""
    coverage = target_item_model_coverage(get_item_by_name(item_name))
    assert coverage["status"] == "modeled"
    assert coverage["calculation_eligible"] is True
    assert "explicit" in coverage["reason"]


@pytest.mark.parametrize("item_name", ["Stridebreaker"])
def test_stridebreaker_utility_scope_is_explicitly_modelled(item_name):
    """Breaking Shockwave exposes its typed slow and movement siblings."""
    coverage = item_model_coverage(get_item_by_name(item_name))
    assert "multi_target" in coverage["outcome_dimensions"]
    assert {"slow", "movement"} <= set(coverage["outcome_dimensions"])
    assert coverage["status"] == "modeled_effect"
    assert coverage["optimizer_eligible"] is True
    assert coverage["review_issue_refs"] == []


def test_fimbulwinter_is_event_certified_and_not_optimizer_blocked():
    coverage = item_model_coverage(get_item_by_name("Fimbulwinter"))
    assert coverage["status"] == "modeled_state"
    assert coverage["optimizer_eligible"] is True
    target = target_item_model_coverage(get_item_by_name("Fimbulwinter"))
    assert target["status"] == "modeled_event_certified"
    assert target["calculation_eligible"] is True
    assert "Everlasting" in target["reason"]


@pytest.mark.parametrize(
    ("item_name", "issue_refs"),
    [
        ("World Atlas", [48, 50, 82]),
    ],
)
def test_withheld_item_packets_are_linked_to_their_implementation_issues(
    item_name, issue_refs
):
    coverage = item_model_coverage(get_item_by_name(item_name))
    assert coverage["status"] == "blocked"
    assert coverage["review_issue_refs"] == issue_refs


def test_ravenous_hydra_active_scope_is_modelled_with_lifesteal():
    """Ravenous active and secondary packets are now fully represented."""
    coverage = item_model_coverage(get_item_by_name("Ravenous Hydra"))

    assert coverage["status"] == "modeled_effect"
    assert coverage["optimizer_eligible"] is True
    assert "sustain" in coverage["outcome_dimensions"]


def test_bloodmail_retribution_is_explicit_starting_state():
    """Bloodmail exposes its bounded starting missing-health state."""
    coverage = item_model_coverage(get_item_by_name("Overlord's Bloodmail"))
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
    coverage = item_model_coverage(get_item_by_name(item_name))
    if item_name in {"Heartsteel", "Rod of Ages"}:
        assert coverage["status"] == "modeled_state"
        assert coverage["optimizer_eligible"] is True
        assert "scenario control" in coverage["reason"]
        return
    assert coverage["status"] == "blocked"
    assert coverage["optimizer_eligible"] is False
    assert required_state in coverage["reason"]


@pytest.mark.parametrize(
    ("item_name", "reason_fragment"),
    [
        ("Cull", "100-minion"),
        ("World Atlas", "400 gold"),
    ],
)
def test_economy_and_quest_items_name_the_missing_progression_state(
    item_name, reason_fragment
):
    """Source-declared gold/quest transitions stay withheld and explain why."""
    coverage = item_model_coverage(get_item_by_name(item_name))

    assert coverage["status"] == "blocked"
    assert coverage["optimizer_eligible"] is False
    assert reason_fragment in coverage["reason"]


def test_dusk_and_dawn_self_heal_receipt_promotes_attacker_coverage():
    """An exact proc receipt and ledger mutation make the item scoreable."""
    coverage = item_model_coverage(get_item_by_name("Dusk and Dawn"))
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
