"""Front-door tests for the public capability contract."""

from src.calculator.capabilities import public_capability_contract


def test_capability_contract_exposes_named_participant_and_catalogue_fields() -> None:
    contract = public_capability_contract(
        input_limits={"level": (1.0, 18.0)},
        max_rotations=6,
        champion_option_count=2,
        item_option_count=3,
    )

    assert contract["schema_version"] == 1
    assert contract["participants"]["main"]["fields"]["champion"]["supported"]
    assert contract["catalogs"]["champion_options"]["count"] == 2
    assert contract["catalogs"]["item_options"]["count"] == 3
