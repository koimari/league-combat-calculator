import json
from pathlib import Path

from scripts.build_bis_profiles import build_profiles
from src.calculator.cast_dependency import BASE_CAST_SLOTS
from src.calculator.champions import registered_champion_names

ROOT = Path(__file__).resolve().parents[1]
PATCH = "26.15"
AUXILIARY = (
    ROOT.parent
    / "lol-strength-analysis"
    / "src"
    / "data"
    / "generated"
    / "merakiAbilityKits.ts"
)
# The auxiliary merge is the only thing allowed to differ from a wiki-only
# rebuild, and it only ever touches these three fields on a slot it fills.
AUX_MERGED_FIELDS = {"packets", "damageType", "signals"}


def _checked_in():
    return json.loads(
        (ROOT / "static" / "bis-profiles.json").read_text(encoding="utf-8")
    )


def test_wiki_bis_profiles_cover_every_champion_and_slot():
    profiles = build_profiles(ROOT / "data" / "champions.json", PATCH)
    assert profiles["champion_count"] == len(profiles["champions"])
    assert all(
        set(champion["abilities"]) == set(BASE_CAST_SLOTS)
        for champion in profiles["champions"].values()
    )


def test_checked_in_bis_profiles_preserve_role_and_scaling_signals():
    """Hand-checked domain signals the profile builder must keep carrying."""
    checked_in = _checked_in()

    assert checked_in["champion_count"] == len(checked_in["champions"])
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


def test_checked_in_bis_profiles_track_the_wiki_rebuild():
    """Everything the wiki can build must match; only aux-filled slots may differ.

    This artifact cannot be compared against a plain rebuild the way the other
    two catalogues can. It is built by merging a wiki parse with an Axword
    Meraki kit reference from a sibling repo that is usually absent, and that
    merge supplies 24 damage packets the wiki parser cannot read. Rebuilding
    without the sibling repo silently drops them, so the invariant checked here
    is a superset relation rather than equality:

      - every slot the wiki alone can fill matches the checked-in artifact
      - slots only the checked-in artifact fills are attributed to the auxiliary
      - fields the merge never touches match everywhere

    That still catches real staleness, and it also catches the specific
    accident this file invites -- regenerating without the sibling repo.
    """
    checked_in = _checked_in()
    fresh = build_profiles(ROOT / "data" / "champions.json", PATCH)

    assert set(checked_in["champions"]) == set(fresh["champions"])

    aux_filled = []
    for name, fresh_champion in fresh["champions"].items():
        stored_champion = checked_in["champions"][name]
        assert stored_champion["roles"] == fresh_champion["roles"], name
        assert set(stored_champion["abilities"]) == set(
            fresh_champion["abilities"]
        ), name

        for slot, fresh_entries in fresh_champion["abilities"].items():
            stored_entries = stored_champion["abilities"][slot]
            assert len(stored_entries) == len(fresh_entries), f"{name} {slot}"

            for index, (stored, built) in enumerate(zip(stored_entries, fresh_entries)):
                where = f"{name} {slot}[{index}]"
                filled_by_auxiliary = bool(stored["packets"]) and not built["packets"]
                if filled_by_auxiliary:
                    aux_filled.extend(stored["packets"])
                    for packet in stored["packets"]:
                        assert packet["source"] == "Axword Meraki generated kit", where
                else:
                    assert stored["packets"] == built["packets"], f"{where} is stale"

                untouched = set(built) - (
                    AUX_MERGED_FIELDS if filled_by_auxiliary else set()
                )
                for field in untouched:
                    assert stored[field] == built[field], f"{where}.{field} is stale"

    assert (
        aux_filled
    ), "auxiliary packets vanished — was this rebuilt without the sibling repo?"
    assert len(aux_filled) == checked_in["auxiliary_source"]["merged_damage_packets"]


def test_axword_meraki_reference_can_fill_unparsed_wiki_packets():
    if not AUXILIARY.exists():
        return
    profiles = build_profiles(ROOT / "data" / "champions.json", PATCH, AUXILIARY)
    assert profiles["auxiliary_source"]["merged_damage_packets"] > 0


def test_the_published_roster_is_the_engine_registry():
    """A BIS preview may only be offered for a champion the engine accepts."""
    checked_in = _checked_in()

    assert sorted(checked_in["champions"]) == sorted(registered_champion_names())
    assert all(
        set(champion["abilities"]) == set(BASE_CAST_SLOTS)
        for champion in checked_in["champions"].values()
    )
