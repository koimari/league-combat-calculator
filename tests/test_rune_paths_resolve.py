"""Resolve's minor runes: one stat grant and eight receipted refusals.

Resolve is the durability path and the pair engine prices outgoing damage,
so eight of its nine runes compile to a refusal that says which half this
engine holds no channel for. Overgrowth is the exception: its stacks buy
maximum health, which the fight's stat block does read and health-scaling
damage does spend.
"""

import pytest

from src.calculator import rune_effects, rune_parser
from src.calculator.calculate import calculate_payload
from src.calculator.rune_paths import resolve

#: Every Resolve rune that books no damage, with the words its receipt must
#: carry — the reason is the receipt, so it is pinned per rune rather than
#: asserted as "some string".
REFUSALS = {
    "Demolish": "damages turrets",
    "Font of Life": "no rune healing channel",
    "Shield Bash": "self-shield events",
    "Conditioning": "outgoing damage",
    "Second Wind": "no rune healing channel",
    "Bone Plating": "damage the holder receives",
    "Revitalize": "no rune healing channel",
    "Unflinching": "while the holder is crowd controlled",
}


def _context(*, level=11, stacks=None):
    options = {"Overgrowth": {"stacks": stacks}} if stacks is not None else {}
    return rune_effects.RuneStatContext(
        level=level,
        is_melee=True,
        bonus_attack_damage=0.0,
        ability_power=0.0,
        options=options,
    )


def _request(**overrides):
    payload = {
        "champion": "Cho'Gath",
        "level": 11,
        "items": [],
        "fight_mode": "one_rotation",
    }
    payload.update(overrides)
    return payload


class TestOvergrowth:
    """Resolve row 3: permanent maximum health, one share per stack."""

    def test_it_grants_the_share_the_cache_states_per_stack(self):
        """The cache states 3 bonus health a stack, un-stacked by default."""
        effect = rune_effects.resolve_rune("Overgrowth")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is rune_effects.RuneStat.BONUS_HEALTH
        assert effect.amount(_context()) == 0.0
        assert effect.amount(_context(stacks=1)) == pytest.approx(3.0)
        assert effect.amount(_context(stacks=15)) == pytest.approx(45.0)

    def test_the_option_is_bounded_by_the_threshold_the_rune_names(self):
        """Its text states one count: after reaching 15 stacks."""
        option = resolve.OPTIONS["Overgrowth"][0]
        assert option.key == "stacks"
        assert option.kind is rune_effects.RuneOptionKind.COUNT
        assert option.default == 0.0
        assert option.bounds == (0.0, 15.0)
        with pytest.raises(ValueError, match="between 0 and 15"):
            option.validated(16)

    def test_the_percentage_half_is_disclosed_as_withheld(self):
        effect = rune_effects.resolve_rune("Overgrowth")
        assert "'stacks' option, worth 3 maximum health each" in effect.disclosures[0]
        assert "at 15 stacks" in effect.disclosures[1]
        assert "stacks indefinitely in game" in effect.disclosures[1]

    def test_a_record_with_no_threshold_bounds_nothing_and_fails_closed(self):
        with pytest.raises(KeyError, match="stack_threshold"):
            resolve.COMPILERS["Overgrowth"]({"effects": {"bonus_health": 3.0}})
        with pytest.raises(KeyError, match="bounds nothing"):
            resolve.COMPILERS["Overgrowth"](
                {"effects": {"bonus_health": 3.0, "stack_threshold": 0}}
            )

    def test_the_health_reaches_the_fight_and_health_scaling_damage_spends_it(self):
        """Cho'Gath's damage scales with his own maximum health."""
        bare = calculate_payload(_request())
        grown = calculate_payload(
            _request(
                minor_runes=["Overgrowth"],
                rune_options={"Overgrowth": {"stacks": 15}},
            )
        )
        assert bare["champion_stats"]["health"] == pytest.approx(2189.0)
        assert grown["champion_stats"]["health"] == pytest.approx(2234.0)
        assert bare["total_damage"] == pytest.approx(1058.5, abs=0.1)
        assert grown["total_damage"] == pytest.approx(1063.0, abs=0.1)

    def test_un_stacked_is_the_default_through_the_whole_pipeline(self):
        bare = calculate_payload(_request())
        selected = calculate_payload(_request(minor_runes=["Overgrowth"]))
        assert selected["champion_stats"]["health"] == (
            bare["champion_stats"]["health"]
        )
        assert selected["total_damage"] == pytest.approx(bare["total_damage"])


class TestResolveRefusals:
    """Eight runes the pair engine holds no channel for, each saying which."""

    @pytest.mark.parametrize("name,reason", sorted(REFUSALS.items()))
    def test_each_refusal_is_withheld_and_names_the_half_it_refuses(self, name, reason):
        effect = rune_effects.resolve_rune(name)
        assert isinstance(effect, rune_effects.RuneNoDamageEffect), name
        assert effect.zero_policy.disposition.name == "WITHHELD", name
        assert reason in effect.zero_policy.reason, name
        assert effect.receipts[0].startswith(f"{name} is not priced:")

    def test_shield_bash_names_both_what_stops_it_and_what_is_unparsed(self):
        """Its trigger has no rune stream, and two of its three terms are gone."""
        effect = rune_effects.resolve_rune("Shield Bash")
        assert "armed by the holder gaining a shield" in effect.zero_policy.reason
        assert any("share of the shield's own amount" in r for r in effect.receipts)

    def test_a_selected_refusal_publishes_its_receipt_and_moves_nothing(self):
        bare = calculate_payload(_request())
        with_rune = calculate_payload(_request(minor_runes=["Bone Plating"]))
        assert any("Bone Plating is not priced" in note for note in with_rune["notes"])
        assert with_rune["total_damage"] == pytest.approx(bare["total_damage"])


class TestResolveCoverage:
    def test_every_resolve_minor_compiles(self):
        catalog = [
            entry
            for entry in rune_effects.rune_catalog()
            if entry["path"] == "Resolve" and entry["row"]
        ]
        assert len(catalog) == 9
        assert all(entry["implemented"] is True for entry in catalog)

    def test_the_declared_option_reaches_the_catalog(self):
        catalog = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        options = catalog["Overgrowth"]["options"]
        assert [option["key"] for option in options] == ["stacks"]
        assert options[0]["maximum"] == 15.0
        assert options[0]["default"] == 0.0


class TestTheParseOvergrowthNeeded:
    def test_a_stated_threshold_is_recorded_as_the_count_it_is(self):
        effects, warnings = rune_parser.parse_effects(
            "After reaching 15 stacks (120 monsters or minions), your health "
            "is permanently increased."
        )
        assert effects["stack_threshold"] == 15
        assert warnings == []
