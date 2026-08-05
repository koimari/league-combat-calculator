"""Coverage gates for the generated explicit champion packet modules."""

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
    assert _GENERIC_CHAMPION_MODULES == {}
    assert not any(
        record.get("review_status") == "generated_packet"
        for record in asset["champions"].values()
    )
