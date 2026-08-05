"""Coverage gates for the generated explicit champion packet modules."""

import importlib
import json

from src.calculator.champions import _GENERIC_CHAMPION_MODULES


def _asset() -> dict:
    with open("static/reviewed-packets.json", encoding="utf-8") as handle:
        return json.load(handle)


def test_packet_asset_covers_all_173_cached_champions():
    asset = _asset()
    assert asset["champion_count"] == 173
    assert len(asset["champions"]) == 173
    assert all(champion.get("sources") for champion in asset["champions"].values())


def test_every_generated_champion_has_an_explicit_unreviewed_packet_module():
    asset = _asset()
    assert set(_GENERIC_CHAMPION_MODULES) <= set(asset["champions"])
    assert len(_GENERIC_CHAMPION_MODULES) == 14
    for champion, module_name in _GENERIC_CHAMPION_MODULES.items():
        module = importlib.import_module(f"src.calculator.champions.{module_name}")
        assert module.REVIEW_STATUS == "generated_packet", champion
        assert callable(module.parse_abilities), champion
        assert isinstance(module.SOURCES, list) and module.SOURCES, champion
        assert isinstance(module.ASSUMPTIONS, list) and module.ASSUMPTIONS, champion
