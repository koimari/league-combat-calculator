import json
from pathlib import Path

from scripts.build_bis_profiles import ABILITY_SLOTS, build_profiles

ROOT = Path(__file__).resolve().parents[1]


def test_wiki_bis_profiles_cover_every_champion_and_slot():
    profiles = build_profiles(ROOT / "data" / "champions.json", "26.15")
    assert profiles["champion_count"] == 173
    assert len(profiles["champions"]) == 173
    assert all(
        set(champion["abilities"]) == set(ABILITY_SLOTS)
        for champion in profiles["champions"].values()
    )


def test_checked_in_bis_profiles_preserve_role_and_scaling_signals():
    checked_in = json.loads((ROOT / "static" / "bis-profiles.json").read_text())
    fresh = build_profiles(ROOT / "data" / "champions.json", "26.15")
    assert checked_in["champion_count"] == 173
    assert checked_in["source"]["sha256"] == fresh["source"]["sha256"]
    assert {"WARDEN", "TANK"}.issubset(checked_in["champions"]["Braum"]["roles"])
    assert "MARKSMAN" in checked_in["champions"]["Aphelios"]["roles"]
    assert (
        "targetCurrentHp"
        in checked_in["champions"]["Dr. Mundo"]["abilities"]["Q"][0]["packets"][0][
            "ratios"
        ]
    )
    assert (
        "bonusHp"
        in checked_in["champions"]["Dr. Mundo"]["abilities"]["E"][0]["packets"][0][
            "ratios"
        ]
    )
    assert checked_in["champions"]["Orianna"]["abilities"]["E"][0]["shields"][0]["base"]
    assert (
        "ap"
        in checked_in["champions"]["Orianna"]["abilities"]["E"][0]["shields"][0][
            "ratios"
        ]
    )


def test_axword_meraki_reference_can_fill_unparsed_wiki_packets():
    auxiliary = (
        ROOT.parent
        / "lol-strength-analysis"
        / "src"
        / "data"
        / "generated"
        / "merakiAbilityKits.ts"
    )
    if not auxiliary.exists():
        return
    profiles = build_profiles(ROOT / "data" / "champions.json", "26.15", auxiliary)
    assert profiles["auxiliary_source"]["merged_damage_packets"] > 0
