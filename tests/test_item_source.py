"""Tests for the ingested-source view of cached items.

Covers the three questions ``item_source`` answers: what effect branches an
item has, whether it is an ordinary Summoner's Rift purchase, and whether
every source-declared effect is accounted for.
"""

import pytest

from src.calculator.data_fetcher import fetch_item_data, get_item_by_name
from src.calculator.item_source import (
    ACKNOWLEDGED_SOURCE_CONFLICTS,
    OPEN_SOURCE_CONFLICTS,
    branches,
    effect_entries,
    effect_text,
    is_ordinary_sr_item,
    item_source_audit,
    merge_item_sources,
    riot_declared_effects,
    source_audit,
    sr_availability,
)


def _wiki_entry(**overrides):
    """A minimal Wiki item-table entry."""
    entry = {
        "id": 1,
        "tier": 3,
        "type": ["Legendary"],
        "modes": {"classic sr 5v5": True, "aram": True, "nb": True, "ar": True},
        "stats": {"ad": 40},
        "effects": {
            "pass": {"name": "Carve", "description": "First branch."},
        },
    }
    entry.update(overrides)
    return entry


def _cached_item(**overrides):
    """A minimal vendor-shaped cached item, before enrichment."""
    item = {
        "name": "Test Item",
        "id": 1,
        "rank": ["LEGENDARY"],
        "requiredChampion": "",
        "requiredAlly": "",
        "passives": [{"name": "Carve", "effects": "First branch."}],
        "active": [],
        "shop": {"purchasable": True, "prices": {"total": 3000}},
    }
    item.update(overrides)
    return item


class TestBranchAccessors:
    def test_branches_returns_every_stored_branch(self) -> None:
        entry = {"name": "Shock", "branches": ["attacks", "abilities"]}
        assert branches(entry) == ("attacks", "abilities")

    def test_effect_text_joins_branches_for_parsers(self) -> None:
        entry = {"name": "Shock", "branches": ["attacks", "abilities"]}
        assert effect_text(entry) == "attacks\nabilities"

    def test_entry_without_branches_reads_as_empty(self) -> None:
        assert branches({"name": "Nothing"}) == ()
        assert effect_text({"name": "Nothing"}) == ""

    def test_effect_entries_pairs_passives_and_actives_with_their_kind(self) -> None:
        item = {
            "passives": [{"name": "Carve", "branches": ["a"]}],
            "active": [{"name": "Supersonic", "branches": ["b"]}],
        }
        assert effect_entries(item) == (
            ("passive", item["passives"][0]),
            ("active", item["active"][0]),
        )


class TestMergeItemSources:
    def test_records_mode_availability_verbatim(self) -> None:
        merged = merge_item_sources(
            {"1": _cached_item()}, {"Test Item": _wiki_entry()}, {}
        )
        assert merged["1"]["modes"] == {
            "classic sr 5v5": True,
            "aram": True,
            "nb": True,
            "ar": True,
        }

    def test_records_every_effect_branch_not_just_the_first(self) -> None:
        wiki = {
            "Test Item": _wiki_entry(
                effects={
                    "pass": {
                        "name": "Carve",
                        "description": "First branch.",
                        "description2": "Second branch.",
                    }
                }
            )
        }
        merged = merge_item_sources({"1": _cached_item()}, wiki, {})

        assert merged["1"]["passives"][0]["branches"] == [
            "First branch.",
            "Second branch.",
        ]

    def test_branch_list_replaces_the_truncated_effects_string(self) -> None:
        merged = merge_item_sources(
            {"1": _cached_item()}, {"Test Item": _wiki_entry()}, {}
        )
        assert "effects" not in merged["1"]["passives"][0]

    def test_records_champion_restriction_from_the_wiki_and_riot(self) -> None:
        wiki = {"Test Item": _wiki_entry(champion=["Kalista", "Sylas"])}
        item = _cached_item(requiredChampion="Kalista")
        merged = merge_item_sources({"1": item}, wiki, {})

        assert merged["1"]["championRestriction"] == ["Kalista", "Sylas"]

    def test_records_the_acquisition_requirement_note(self) -> None:
        wiki = {"Test Item": _wiki_entry(req="Requires the support quest.")}
        merged = merge_item_sources({"1": _cached_item()}, wiki, {})

        assert merged["1"]["acquisitionNote"] == "Requires the support quest."

    def test_records_the_special_stat_line(self) -> None:
        wiki = {
            "Test Item": _wiki_entry(
                stats={"ad": 7, "spec": "+3 [[health]] [[on-hit]]"}
            )
        }
        merged = merge_item_sources({"1": _cached_item()}, wiki, {})

        assert merged["1"]["specialStats"] == "+3 [[health]] [[on-hit]]"

    def test_records_the_riot_description_for_offline_verification(self) -> None:
        merged = merge_item_sources(
            {"1": _cached_item()},
            {"Test Item": _wiki_entry()},
            {1: "<mainText><passive>Carve</passive></mainText>"},
        )
        assert merged["1"]["riotDescription"] == (
            "<mainText><passive>Carve</passive></mainText>"
        )

    def test_resolves_inherited_fields_from_the_parent_item(self) -> None:
        wiki = {
            "Manamune": _wiki_entry(id=2),
            "Muramana": _wiki_entry(
                id=1,
                modes="=>Manamune",
                effects={
                    "pass": "=>Manamune",
                    "pass2": {"name": "Shock", "description": "shock"},
                },
            ),
        }
        item = _cached_item(
            name="Muramana",
            passives=[
                {"name": "Carve", "effects": "First branch."},
                {"name": "Shock", "effects": "shock"},
            ],
        )
        merged = merge_item_sources({"1": item}, wiki, {})

        assert merged["1"]["modes"]["classic sr 5v5"] is True
        assert [p["branches"] for p in merged["1"]["passives"]] == [
            ["First branch."],
            ["shock"],
        ]

    def test_unmatched_item_keeps_its_text_and_warns(self) -> None:
        merged = merge_item_sources({"1": _cached_item()}, {}, {})
        entry = merged["1"]

        assert entry["passives"][0]["branches"] == ["First branch."]
        assert entry["modes"] == {}
        assert any("Test Item" in warning for warning in entry["sourceWarnings"])

    def test_source_side_effect_the_vendor_dropped_is_warned_not_lost(self) -> None:
        wiki = {
            "Test Item": _wiki_entry(
                effects={
                    "pass": {"name": "Carve", "description": "First branch."},
                    "consume": {"description": "Consume for a reroll."},
                }
            )
        }
        merged = merge_item_sources({"1": _cached_item()}, wiki, {})

        assert any("consume" in warning for warning in merged["1"]["sourceWarnings"])

    def test_merge_does_not_mutate_the_input_items(self) -> None:
        item = _cached_item()
        merge_item_sources({"1": item}, {"Test Item": _wiki_entry()}, {})

        assert item["passives"][0]["effects"] == "First branch."
        assert "modes" not in item


class TestSrAvailability:
    def test_summoners_rift_shop_item_is_selectable(self) -> None:
        item = _cached_item(modes={"classic sr 5v5": True, "aram": True})
        availability = sr_availability(item)

        assert availability.on_summoners_rift is True
        assert availability.acquisition == "shop"
        assert availability.selectable is True

    def test_item_absent_from_summoners_rift_is_withheld(self) -> None:
        item = _cached_item(modes={"classic sr 5v5": False, "aram": True})
        availability = sr_availability(item)

        assert availability.selectable is False
        assert "Summoner's Rift" in availability.reason

    def test_missing_mode_table_fails_closed(self) -> None:
        item = _cached_item(modes={})
        availability = sr_availability(item)

        assert availability.selectable is False
        assert availability.acquisition == "unknown_source"

    def test_champion_granted_item_is_withheld(self) -> None:
        item = _cached_item(
            modes={"classic sr 5v5": True}, championRestriction=["Kalista"]
        )
        availability = sr_availability(item)

        assert availability.acquisition == "champion_granted"
        assert availability.selectable is False
        assert "Kalista" in availability.reason

    def test_quest_transform_is_withheld_from_the_ordinary_shop(self) -> None:
        item = _cached_item(
            modes={"classic sr 5v5": True},
            acquisitionNote="Requires completion of the support quest.",
            shop={"purchasable": False, "prices": {"total": 400}},
        )
        availability = sr_availability(item)

        assert availability.acquisition == "quest_transform"
        assert availability.selectable is False

    def test_recipe_upgrade_without_a_quest_stays_selectable(self) -> None:
        """Muramana is not purchasable but is reached by upgrading Manamune."""
        item = _cached_item(
            modes={"classic sr 5v5": True},
            acquisitionNote="",
            shop={"purchasable": False, "prices": {"total": 2900}},
        )
        assert sr_availability(item).selectable is True

    @pytest.mark.parametrize("rank", ["TURRET", "TRINKET", "DISTRIBUTED"])
    def test_map_and_system_rank_is_not_a_player_shop_purchase(self, rank: str) -> None:
        item = _cached_item(
            modes={"classic sr 5v5": True},
            rank=[rank],
            shop={"purchasable": False, "prices": {"total": 0}},
        )
        availability = sr_availability(item)

        assert availability.on_summoners_rift is True
        assert availability.acquisition == "map_or_system"
        assert availability.selectable is False
        assert "not a player shop purchase" in availability.reason

    def test_zero_price_non_purchasable_record_fails_closed(self) -> None:
        item = _cached_item(
            modes={"classic sr 5v5": True},
            rank=["UNKNOWN"],
            shop={"purchasable": False, "prices": {"total": 0}},
        )
        availability = sr_availability(item)

        assert availability.acquisition == "map_or_system"
        assert availability.selectable is False


class TestTrackedCacheAvailability:
    """Leakage regressions against the tracked cache."""

    @pytest.mark.parametrize(
        "name",
        [
            "Guardian's Amulet",
            "Guardian's Blade",
            "Guardian's Dirk",
            "Guardian's Hammer",
            "Guardian's Horn",
            "Guardian's Orb",
            "Guardian's Shroud",
            "Lifeline",
        ],
    )
    def test_off_rift_items_are_not_selectable(self, name: str) -> None:
        availability = sr_availability(get_item_by_name(name))
        assert availability.on_summoners_rift is False
        assert availability.selectable is False

    def test_champion_granted_black_spear_is_not_selectable(self) -> None:
        availability = sr_availability(get_item_by_name("Black Spear"))
        assert availability.acquisition == "champion_granted"
        assert availability.selectable is False

    def test_ordinary_legendaries_stay_selectable(self) -> None:
        for name in ("Infinity Edge", "Muramana", "Experimental Hexplate"):
            assert is_ordinary_sr_item(get_item_by_name(name)) is True

    def test_every_cached_item_carries_a_mode_table(self) -> None:
        missing = [
            item["name"] for item in fetch_item_data().values() if not item.get("modes")
        ]
        assert missing == []

    def test_every_ordinary_sr_item_has_no_unaccounted_source_warning(self) -> None:
        """Map-aware selection must not admit an item with dropped source text."""
        warnings = {
            item["name"]: list(item.get("sourceWarnings") or ())
            for item in fetch_item_data().values()
            if sr_availability(item).selectable and item.get("sourceWarnings")
        }
        assert warnings == {}


class TestSourceAudit:
    def test_riot_declared_effect_names_are_extracted(self) -> None:
        item = {
            "riotDescription": (
                "<mainText><passive>Reap</passive><br>"
                " <active>Active -</active> <active>Soul Anchor's</active></mainText>"
            )
        }
        assert riot_declared_effects(item) == ("Reap", "Soul Anchor")

    def test_effect_present_in_both_sources_is_parsed(self) -> None:
        item = _cached_item(
            passives=[{"name": "Carve", "branches": ["text"]}],
            riotDescription="<passive>Carve</passive>",
        )
        audit = item_source_audit(item)

        assert audit["conflicts"] == []
        assert audit["parsed"] == ["Carve"]

    def test_effect_only_riot_declares_is_a_source_conflict(self) -> None:
        item = _cached_item(
            passives=[],
            riotDescription="<passive>Unrecorded Gait</passive>",
        )
        audit = item_source_audit(item)

        assert [entry["effect"] for entry in audit["conflicts"]] == ["Unrecorded Gait"]
        assert audit["conflicts"][0]["acknowledged"] is False

    @pytest.mark.parametrize("table", [ACKNOWLEDGED_SOURCE_CONFLICTS])
    def test_reviewed_conflict_carries_its_status_and_note(self, table) -> None:
        name, effects = next(iter(table.items()))
        effect, note = next(iter(effects.items()))
        item = _cached_item(
            name=name,
            passives=[],
            active=[],
            riotDescription=f"<passive>{effect}</passive>",
        )
        conflict = item_source_audit(item)["conflicts"][0]

        assert conflict["status"] == "explained"
        assert conflict["acknowledged"] is True
        assert conflict["note"] == note

    def test_patch_inventory_has_no_unresolved_source_conflicts(self) -> None:
        """Every source discrepancy is acknowledged or deliberately blocked."""
        audit = source_audit(fetch_item_data().values())

        assert audit["open_conflicts"] == []
        assert audit["complete"] is True

    def test_tracked_cache_has_no_unacknowledged_source_conflict(self) -> None:
        audit = source_audit(fetch_item_data().values())
        unreviewed = [
            f"{entry['item']} / {entry['effect']}"
            for entry in audit["conflicts"]
            if not entry["acknowledged"]
        ]
        assert unreviewed == []

    def test_acknowledgements_do_not_outlive_their_conflict(self) -> None:
        """A stale acknowledgement would hide the next real divergence."""
        audit = source_audit(fetch_item_data().values())
        live = {(entry["item"], entry["effect"]) for entry in audit["conflicts"]}
        stale = [
            f"{item} / {effect}"
            for table in (ACKNOWLEDGED_SOURCE_CONFLICTS, OPEN_SOURCE_CONFLICTS)
            for item, effects in table.items()
            for effect in effects
            if (item, effect) not in live
        ]
        assert stale == []

    def test_cull_reap_keeps_its_completion_payout_branch(self) -> None:
        cull = get_item_by_name("Cull")
        reap = next(p for p in cull["passives"] if p["name"] == "Reap")

        assert len(branches(reap)) == 2
        assert "350" in branches(reap)[1]
        assert cull["specialStats"] == "+3 [[health]] [[on-hit]]"

    def test_muramana_shock_keeps_its_ability_branch(self) -> None:
        muramana = get_item_by_name("Muramana")
        shock = next(p for p in muramana["passives"] if p["name"] == "Shock")
        text = effect_text(shock)

        assert "{{rd|4%|3%}}" in text
        assert "6.5" in text
