"""E9-BIS-B: certify/audit the remaining BIS item withholdings.

Covers the support starter upgrades (Bloodsong, Celestial Opposition, Dream
Maker, Solstice Sleigh, Zaz'Zak's Realmspike) and the three explicitly
audited timing exclusions (Bastionbreaker Shaped Charge, Eclipse Ever Rising
Moon, Muramana Shock).  Every item must now appear as a certified /api/bis
candidate for the champions that previously withheld it; the support quest
state gate stays an honest, sourced withholding when the quest is not
complete.
"""

import pytest

from src.app import app


def _bis_payload(
    champion: str,
    role: str,
    *,
    objective: str = "utility",
    role_quest_complete: bool = False,
) -> dict:
    return {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": role,
        "enemies": [{"champion": "Annie", "level": 18}],
        "objective": objective,
        "slot_index": 0,
        "slot_kind": "item",
        "subject_team": "main",
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "role_quest_complete": role_quest_complete,
    }


def _bis_body(champion: str, role: str, **kwargs) -> dict:
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/bis", json=_bis_payload(champion, role, **kwargs)
    )
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()


def _assert_certified(body: dict, item_name: str) -> dict:
    candidates = {row["name"]: row for row in body["candidates"]}
    assert item_name in candidates, (
        f"{item_name} missing from certified candidates; "
        f"withheld={[w['name'] for w in body['withheld_candidates']]} "
        f"partial={[p['name'] for p in body['partial_candidates']]}"
    )
    row = candidates[item_name]
    assert row["timeline_coverage"]["complete"] is True
    return row


# ---------------------------------------------------------------------------
# Support starter upgrades (quest complete -> certified candidates)
# ---------------------------------------------------------------------------

SUPPORT_STARTERS = [
    "Bloodsong",
    "Celestial Opposition",
    "Dream Maker",
    "Solstice Sleigh",
    "Zaz'Zak's Realmspike",
]


@pytest.mark.parametrize("champion", ["Lulu", "Sona", "Nami"])
def test_support_starters_certify_for_support_champions(champion):
    """Every support starter upgrade is a certified BIS candidate."""
    body = _bis_body(champion, "support", role_quest_complete=True)
    for item in SUPPORT_STARTERS:
        row = _assert_certified(body, item)
        # Utility objective: the certified row carries a real support score.
        assert row["objective_value"] > 0


def test_support_starter_without_quest_stays_a_sourced_state_gate():
    """Upgraded support items only exist after quest completion.

    With the quest incomplete the loadout is rejected by the item's own
    legality rule; the API keeps that an explicit, visible withholding
    instead of inventing a score.
    """
    body = _bis_body("Lulu", "support")
    withheld = {w["name"]: w for w in body["withheld_candidates"]}
    for item in SUPPORT_STARTERS:
        row = withheld[item]
        assert row["reason"] == "candidate_loadout_unavailable"
        assert "support quest" in row["detail"]
        assert row["timeline_coverage"]["certification"] == "candidate_not_evaluated"


def test_bloodsong_expose_weakness_is_event_ordered_for_support_champions():
    """Bloodsong's Expose Weakness amp lands on the post-proc ledger."""
    for champion in ("Lulu", "Sona"):
        body = _bis_body(champion, "support", role_quest_complete=True)
        row = _assert_certified(body, "Bloodsong")
        assert "expose_weakness_Bloodsong" in row["timeline_coverage"]["exact_sources"]


# ---------------------------------------------------------------------------
# Timing-exclusion items (previously withheld before ranking)
# ---------------------------------------------------------------------------


def test_bastionbreaker_certifies_for_ahri_and_aatrox():
    """Shaped Charge now rides the ordered ability ledger."""
    for champion in ("Ahri", "Aatrox"):
        body = _bis_body(champion, "mid")
        row = _assert_certified(body, "Bastionbreaker")
        assert (
            "shaped_charge_Bastionbreaker" in row["timeline_coverage"]["exact_sources"]
        )


@pytest.mark.parametrize("champion", ["Ahri", "Lux", "Aatrox"])
def test_muramana_certifies_for_champions_that_previously_withheld_it(champion):
    """Shock rides the ability's sourced cast-instance boundary."""
    body = _bis_body(champion, "mid")
    row = _assert_certified(body, "Muramana")
    assert "muramana_ability" in row["timeline_coverage"]["exact_sources"]


@pytest.mark.parametrize("champion", ["Ziggs", "Garen"])
def test_eclipse_certifies_for_champions_that_previously_withheld_it(champion):
    """Ever Rising Moon stacks on authored single-hit packets."""
    body = _bis_body(champion, "mid")
    row = _assert_certified(body, "Eclipse")
    assert "proc_Eclipse" in row["timeline_coverage"]["exact_sources"]


def test_ahri_utility_bis_reaches_full_certification_without_timing_exclusions():
    """The corpus cp21 pin: no candidate is withheld before ranking."""
    body = _bis_body("Ahri", "mid", objective="utility")
    assert body["certified_candidate_count"] == 95
    assert body["withheld_candidate_count"] == 0
    assert "Bastionbreaker" not in {w["name"] for w in body["withheld_candidates"]}
    assert "Muramana" not in {w["name"] for w in body["withheld_candidates"]}
