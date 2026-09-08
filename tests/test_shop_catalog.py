"""Keep shop display metadata bound to the cached item source."""

import src.app as app_module
from src.calculator.data_fetcher import fetch_item_data
from src.calculator.item_source import effect_entries, effect_text
from tests.app_config import app_config


def _catalog(path):
    with app_config(TESTING=True, RATE_LIMIT_ENABLED=False):
        response = app_module.app.test_client().get(path)
    assert response.status_code == 200
    return {item["name"]: item for item in response.get_json()}


def test_rank_groups_distinguish_epic_from_legendary_at_the_same_numeric_tier():
    catalog = _catalog("/api/items")
    assert catalog["Infinity Edge"]["tier"] == catalog["Phage"]["tier"]
    assert catalog["Infinity Edge"]["rank"] == ["LEGENDARY"]
    assert catalog["Phage"]["rank"] == ["EPIC"]
    assert catalog["Long Sword"]["rank"] == ["BASIC"]
    assert catalog["Doran's Blade"]["rank"] == ["STARTER"]


def test_recipe_preserves_repeated_components_and_unselectable_basic_boots():
    catalog = _catalog("/api/boots")
    item = catalog["Berserker's Greaves"]
    components = item["builds_from"]
    assert [row["name"] for row in components] == ["Boots", "Dagger", "Dagger"]
    assert components[0]["catalog_available"] is False
    assert all(row["catalog_available"] for row in components[1:])
    assert all(row["price"] > 0 for row in components)


def test_catalog_edges_reproduce_cached_fields():
    sources = fetch_item_data()
    for path in ("/api/items", "/api/boots"):
        for item in _catalog(path).values():
            source = sources[str(item["id"])]
            assert "description" not in item
            assert [row["id"] for row in item["builds_from"]] == source["buildsFrom"]
            assert [row["id"] for row in item["builds_into"]] == source["buildsInto"]


def test_unknown_recipe_reference_has_no_invented_name_or_price():
    result = app_module._item_shop_fields({"buildsFrom": [999999999]}, {}, set())
    assert result["rank"] is None
    assert result["builds_from"] == [
        {
            "id": 999999999,
            "name": None,
            "icon": None,
            "price": None,
            "catalog_available": False,
        }
    ]


def test_every_effect_retains_all_source_branches_and_its_kind():
    sources = fetch_item_data()
    for path in ("/api/items", "/api/boots"):
        for item in _catalog(path).values():
            source = sources[str(item["id"])]
            expected = [
                {
                    "kind": kind,
                    "name": entry.get("name"),
                    "text": effect_text(entry),
                    "text_format": "wikitext",
                }
                for kind, entry in effect_entries(source)
            ]
            assert item["effects"] == expected
            assert item["shop_tags"] == source["shop"]["tags"]
    titanic = _catalog("/api/items")["Titanic Hydra"]
    crescent = next(
        effect for effect in titanic["effects"] if effect["kind"] == "active"
    )
    assert "resets" in crescent["text"]
    assert "\n" in crescent["text"]


def test_effects_keep_raw_source_text_without_executing_or_dropping_markup():
    source = {
        "passives": [
            {
                "name": "Example",
                "branches": ["First source branch.", "<em>Second</em> source branch."],
            }
        ],
        "active": [{"name": None, "branches": ["Third source branch."]}],
    }
    fields = app_module._item_shop_fields(source, {}, set())
    assert (
        fields["effects"][0]["text"]
        == "First source branch.\n<em>Second</em> source branch."
    )
    assert fields["effects"][1]["name"] is None
    assert fields["effects"][1]["kind"] == "active"
    assert fields["shop_tags"] == []
