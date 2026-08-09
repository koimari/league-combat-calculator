"""Public contract and regression tests for the shared participant ledger."""

from src import app as app_module
from src.calculator.capabilities import (
    PARTICIPANT_LEDGER_CONTRACT,
    SUPPORT_TARGET_RESOLUTION_SCOPES,
)


def test_capability_contract_publishes_one_ordered_participant_ledger():
    response = app_module.app.test_client().get("/api/config")
    assert response.status_code == 200
    ledger = response.get_json()["capabilities"]["participant_ledger"]

    assert ledger == PARTICIPANT_LEDGER_CONTRACT
    assert ledger["certification"] == "event_order_certified"
    assert ledger["fail_closed"] is True
    assert ledger["phases"] == [
        "state_transition",
        "shield_or_temporary_health",
        "persistent_aura_arming",
        "damage_and_mitigation",
        "reactive_effect",
        "healing_and_regeneration",
        "death_or_terminal_cutoff",
    ]


def test_participant_controls_share_the_same_target_policy_receipt():
    contract = (
        app_module.app.test_client().get("/api/config").get_json()["capabilities"]
    )
    policies = contract["participant_ledger"]["target_policy"]
    assert policies["self_and_one_teammate"] == "self_and_first_selected_teammate"
    assert policies["one_teammate"] == "first_selected_teammate"
    assert policies["none_selected"] == "no_selected_teammate"
    for kind in ("main", "enemy", "ally"):
        assert contract["participants"][kind]["supported"] is True
        assert (
            contract["participants"][kind]["fields"]["role_quest_complete"]["supported"]
            is True
        )


def test_target_policy_contract_is_the_closed_resolution_vocabulary():
    """Issue #142: the published target-policy map is exactly the closed
    resolver vocabulary plus ``none_selected`` — the contract and the
    resolver cannot drift."""
    policies = PARTICIPANT_LEDGER_CONTRACT["target_policy"]
    assert set(policies) == SUPPORT_TARGET_RESOLUTION_SCOPES | {"none_selected"}
    assert policies["one_teammate"] == "first_selected_teammate"
    assert policies["none_selected"] == "no_selected_teammate"
    assert PARTICIPANT_LEDGER_CONTRACT["fail_closed"] is True
