"""The ability-payload schema is the one home for a field's absent meaning."""

import pytest

from src.calculator import damage
from src.calculator.ability_atoms import (
    ABILITY_PAYLOAD_SCHEMA,
    EMPTY_PAYLOAD,
    REQUIRED,
    ability_field,
    ability_payload,
    ability_sub_payload,
)


class TestAbilityField:
    """What an authored, an absent, and a required-but-absent field read as."""

    def test_an_authored_field_reads_back_unchanged(self):
        assert ability_field({"dot_duration": 3.5}, "dot_duration") == 3.5

    def test_an_absent_field_reads_the_schema_default(self):
        assert ability_field({}, "dot_duration") == 0.0
        assert ability_field({}, "cast_instances") == 1
        assert ability_field({}, "resource_type") == "NONE"

    def test_an_authored_none_reads_as_the_unauthored_field(self):
        """A module that writes None declared the absence, not a value."""
        assert ability_field({"cooldown": None}, "cooldown") == 0.0

    def test_a_required_field_raises_naming_the_ability_and_the_key(self):
        with pytest.raises(KeyError) as excinfo:
            ability_field({"parts": ()}, "name")
        assert "name" in str(excinfo.value)

    def test_the_raise_names_the_ability_the_module_authored(self):
        payload = {"name": "Ranger's Focus"}
        with pytest.raises(KeyError) as excinfo:
            ability_field(payload, "damage_type", form="on_hit")
        assert "damage_type" in str(excinfo.value)

    def test_a_field_no_form_declares_is_a_schema_error(self):
        with pytest.raises(KeyError) as excinfo:
            ability_field({}, "not_a_declared_field")
        assert "not_a_declared_field" in str(excinfo.value)

    def test_each_form_carries_its_own_default_for_a_shared_key(self):
        assert ability_field({}, "damage_type", form="stacking_dot") == "physical"
        assert ability_field({}, "damage_type", form="conversion") == "magic"


class TestPayloadLookups:
    """An unauthored slot or sub-payload reads as the one empty payload."""

    def test_a_missing_slot_reads_as_the_empty_payload(self):
        assert ability_payload({}, "Q") is EMPTY_PAYLOAD
        assert ability_payload({"Q": None}, "Q") is EMPTY_PAYLOAD

    def test_an_authored_slot_reads_back_unchanged(self):
        payload = {"name": "Q"}
        assert ability_payload({"Q": payload}, "Q") is payload

    def test_a_missing_sub_payload_reads_as_the_empty_payload(self):
        assert ability_sub_payload({}, "auto_attack_override") is EMPTY_PAYLOAD

    def test_an_authored_sub_payload_reads_back_unchanged(self):
        override = {"ad_ratio": 0.5}
        assert ability_sub_payload({"on_hit": override}, "on_hit") is override


class TestTheSchemaIsTheOnlyHome:
    """No engine call site may restate what the table already declares."""

    def test_every_form_declares_at_least_one_field(self):
        assert all(ABILITY_PAYLOAD_SCHEMA.values())

    def test_the_required_sentinel_is_not_a_value_a_payload_can_hold(self):
        assert ability_field({"name": REQUIRED}, "name") is REQUIRED


class TestDeclaredOptionSpec:
    """A user option's default and bounds come from its own OPTIONS spec."""

    def test_a_champion_option_reads_its_declared_default(self):
        assert damage.declared_option_default("champion", "Ashe", "q_focus_stacks") == 4
        assert (
            damage.declared_option_default("champion", "Senna", "senna_mist_stacks")
            == 40
        )

    def test_an_item_and_a_keystone_option_read_theirs(self):
        assert (
            damage.declared_option_default(
                "item", "Tear of the Goddess", "manaflow_bonus_mana"
            )
            == 0
        )
        assert (
            damage.declared_option_default("keystone", "Conqueror", "starting_stacks")
            == 0
        )

    def test_an_undeclared_option_raises_naming_family_owner_and_key(self):
        with pytest.raises(KeyError) as excinfo:
            damage.declared_option_default("champion", "Ashe", "not_an_option")
        assert "not_an_option" in str(excinfo.value)

    def test_a_seeded_stack_option_is_bounded_by_its_own_spec(self):
        """The cap lives beside the control, not beside the walk."""
        seed = damage._seeded_option_stacks
        assert seed({}, "champion", "Ashe", "q_focus_stacks") == 4
        assert seed({"q_focus_stacks": 2}, "champion", "Ashe", "q_focus_stacks") == 2
        assert seed({"q_focus_stacks": 99}, "champion", "Ashe", "q_focus_stacks") == 4
        assert seed({"q_focus_stacks": -5}, "champion", "Ashe", "q_focus_stacks") == 0

    def test_an_unparsable_selection_reads_as_the_unset_one(self):
        seed = damage._seeded_option_stacks
        assert seed({"p_ferocity": "x"}, "champion", "Rengar", "p_ferocity") == 0
