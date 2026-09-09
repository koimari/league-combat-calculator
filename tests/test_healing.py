"""Front-door tests for champion-owned healing rules.

Detailed issue and champion cases remain in the E1 and ledger suites.  The
Taric case here gives the shared healing module an obvious first file.
"""

import pytest

from src.calculator import healing_helpers as _healing
from src.calculator.champions.healing_contract import (
    heal_receipt_order,
    self_healing_rule,
)
from src.calculator.champions.slotlib import extract_named
from src.calculator.data_fetcher import get_champion
from src.calculator.healing import derive_self_healing


def test_taric_q_prices_the_sourced_five_charge_self_heal() -> None:
    heals = derive_self_healing(
        get_champion("Taric"),
        {"level": 18, "health": 2000.0, "ability_power": 0.0},
        {"Q": {"rank": 5}},
        [],
        [{"slot": "Q", "time": 1.0}],
        5.0,
    )

    assert len(heals) == 1
    assert heals[0]["amount"] == pytest.approx(225.0)
    assert heals[0]["source"] == "Starlight's Touch"
    assert heals[0]["charges"] == 5


def test_unknown_champion_has_no_inferred_healing() -> None:
    assert (
        derive_self_healing(
            {"name": "Synthetic Fixture"},
            {"level": 18},
            {},
            [],
        )
        == []
    )


class TestTheAnchorIsDeclaredNotInferred:
    """What a self-heal rule pays on comes from the rule, not the ledger.

    Every case here feeds the same rule two ledgers that differ only in how
    many events one activation was priced with — which is exactly what a
    champion module changes when it authors an ability's true hit cadence.
    """

    @staticmethod
    def _event(source, time, damage=100.0, sequence=0):
        return {
            "slot": source,
            "time": time,
            "damage": damage,
            "raw_damage": damage,
            "source": source,
            "source_key": source,
            "sequence": sequence,
            "target": "enemy",
        }

    def test_a_cast_rule_pays_once_however_many_hits_the_cast_authors(self):
        """Kha'Zix's Void Spike explodes once per cast.

        One cast priced as one hit and the same cast priced as four hits
        are the same explosion, so they are the same heal.
        """
        khazix = get_champion("Kha'Zix")
        stats = {"level": 18, "health": 2000.0, "ability_power": 0.0}
        casts = [{"slot": "W", "time": 2.0}]
        one_hit = derive_self_healing(
            khazix, stats, {"W": {"rank": 5}}, [self._event("W", 2.0)], casts, 10.0
        )
        four_hits = derive_self_healing(
            khazix,
            stats,
            {"W": {"rank": 5}},
            [self._event("W", 2.0 + 0.2 * index, sequence=index) for index in range(4)],
            casts,
            10.0,
        )
        assert len(one_hit) == 1
        assert [event["source"] for event in four_hits] == ["Void Spike"]
        assert four_hits[0]["amount"] == pytest.approx(one_hit[0]["amount"])
        assert four_hits[0]["time"] == pytest.approx(2.0)

    def test_a_cast_rule_pays_once_per_cast_when_there_are_several(self):
        khazix = get_champion("Kha'Zix")
        heals = derive_self_healing(
            khazix,
            {"level": 18, "health": 2000.0, "ability_power": 0.0},
            {"W": {"rank": 5}},
            [self._event("W", 2.0), self._event("W", 2.3), self._event("W", 9.0)],
            [{"slot": "W", "time": 2.0}, {"slot": "W", "time": 9.0}],
            10.0,
        )
        assert [round(event["time"], 3) for event in heals] == [2.0, 9.0]

    def test_a_per_hit_rule_pays_per_hit_and_skips_a_hit_that_dealt_nothing(self):
        """Warwick's Jaws of the Beast heals "for a percentage of the
        damage dealt", so it follows the hits — and a hit that dealt
        nothing is nothing to take a percentage of.
        """
        warwick = get_champion("Warwick")
        stats = {"level": 18, "health": 2000.0, "ability_power": 0.0}
        heals = derive_self_healing(
            warwick,
            stats,
            {"Q": {"rank": 5}},
            [
                self._event("Q", 1.0, damage=100.0),
                self._event("Q", 1.5, damage=0.0, sequence=1),
                self._event("Q", 2.0, damage=50.0, sequence=2),
            ],
            [{"slot": "Q", "time": 1.0}],
            10.0,
        )
        assert [round(event["time"], 3) for event in heals] == [1.0, 2.0]
        assert heals[0]["amount"] == pytest.approx(2.0 * heals[1]["amount"])

    def test_a_scheduled_rule_counts_from_the_cast_not_from_the_damage(self):
        """Briar charges Chilling Scream for a second, "during which she
        ... heals herself every 0.25 seconds", and only then screams.

        Timing the scream at the end of the charge must not carry the
        charge's healing along with it.
        """
        briar = get_champion("Briar")
        stats = {"level": 18, "health": 2000.0, "ability_power": 0.0}
        heals = derive_self_healing(
            briar,
            stats,
            {"E": {"rank": 5}},
            [self._event("E", 4.0)],
            [{"slot": "E", "time": 3.0}],
            10.0,
        )
        ticks = [
            round(event["time"], 3)
            for event in heals
            if event["source"] == "Chilling Scream"
        ]
        assert ticks == [3.25, 3.5, 3.75, 4.0]

    def test_a_cast_anchor_needs_one_slot_to_match_casts(self):
        """A predicate cannot be matched against the cast timeline, so a
        rule asking for a cast anchor over one fails closed rather than
        quietly counting events."""
        from src.calculator.healing_helpers import HealAnchor, payments

        with pytest.raises(ValueError, match="one slot"):
            payments(HealAnchor.CAST, lambda source: True, [], None)

    def test_an_event_no_cast_names_stands_in_for_its_own_activation(self):
        """Without a cast to point at, one instant is one activation.

        It is the most a rule can honestly conclude, and it still refuses
        to turn the several parts of one instant into several heals.
        """
        khazix = get_champion("Kha'Zix")
        heals = derive_self_healing(
            khazix,
            {"level": 18, "health": 2000.0, "ability_power": 0.0},
            {"W": {"rank": 5}},
            [self._event("W", 2.0), self._event("W", 2.0, sequence=1)],
            None,
            10.0,
        )
        assert len(heals) == 1


class TestTheDeclarationAndTheRegistryAgreeBothWays:
    """``healing._load_declarations`` walks the registry and demands a
    declaration; these cover the other direction."""

    def test_declaring_a_rule_without_a_resolver_fails_closed(self):
        from src.calculator.champions.healing_contract import declare_healing_rule

        with pytest.raises(RuntimeError, match="without a resolver"):
            declare_healing_rule("Teemo", None)

    def test_no_champion_module_declares_a_rule_outside_the_set(self):
        from src.calculator import healing
        from src.calculator.champions import _CHAMPION_MODULES

        declared = {
            name
            for name, module in _CHAMPION_MODULES.items()
            if hasattr(module, "SELF_HEALING_RULE")
        }
        assert declared == set(healing.HEALING_RULE_CHAMPIONS)


class TestSelfHealingRuleDeclaration:
    """``self_healing_rule`` owns the receipt order every module hands back."""

    @staticmethod
    def _events() -> list[dict]:
        return [
            {"time": 2.0, "amount": 5.0, "source": "W"},
            {"time": 1.0, "amount": 5.0, "source": "R"},
            {"time": 1.0, "amount": 5.0, "source": "Q"},
        ]

    def _rule(self):
        return self_healing_rule("Taric")(lambda *args: self._events())

    def test_it_declares_the_named_champion(self) -> None:
        assert self._rule().champion_name == "Taric"

    def test_the_ledger_comes_back_ordered_by_time_then_source(self) -> None:
        ordered = self._rule().derive({}, {}, {}, [])
        assert [(e["time"], e["source"]) for e in ordered] == [
            (1.0, "Q"),
            (1.0, "R"),
            (2.0, "W"),
        ]

    def test_the_resolver_keeps_its_own_module_for_the_audit(self) -> None:
        """The contract audit reads ``resolver.__module__`` to prove a rule
        is champion-owned, so the ordering wrapper must not claim it."""

        def derive_self_healing(*args):
            return []

        rule = self_healing_rule("Taric")(derive_self_healing)
        assert rule.resolver.__module__ == derive_self_healing.__module__
        assert rule.resolver.__name__ == "derive_self_healing"

    def test_one_key_orders_both_the_declaration_and_the_entrypoint(self) -> None:
        event = {"time": 1.5, "amount": 1.0, "source": "Q"}
        assert heal_receipt_order(event) == (1.5, "Q")


def _healing_champion() -> dict:
    """A champion whose W carries a flat Heal row and a missing-health one."""
    return {
        "name": "TestChamp",
        "abilities": {
            "W": [
                {
                    "name": "Frenzied Maul",
                    "effects": [
                        {
                            "leveling": [
                                {
                                    "attribute": "Heal",
                                    "modifiers": [
                                        {"values": [10, 20, 30], "units": ["", "", ""]},
                                        {
                                            "values": [4, 5, 6],
                                            "units": [
                                                "% of missing health",
                                                "% of missing health",
                                                "% of missing health",
                                            ],
                                        },
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ]
        },
    }


class TestRankedRows:
    """One slot's named rows at the rank the parser used."""

    def test_the_rows_are_read_at_the_emitted_rank(self) -> None:
        (flat,) = _healing.ranked_rows(
            _healing_champion(), {"W": {"rank": 2}}, {}, "W", "Heal"
        )
        assert flat == pytest.approx(20.0)

    def test_it_reads_several_rows_in_the_order_named(self) -> None:
        champion = _healing_champion()
        champion["abilities"]["W"][0]["effects"][0]["leveling"].append(
            {
                "attribute": "Bonus",
                "modifiers": [{"values": [7, 8, 9], "units": ["", "", ""]}],
            }
        )
        rows = _healing.ranked_rows(
            champion, {"W": {"rank": 3}}, {}, "W", "Heal", "Bonus"
        )
        assert rows == (pytest.approx(30.0), pytest.approx(9.0))

    def test_an_absent_slot_or_row_prices_zero_rather_than_guessing(self) -> None:
        assert _healing.ranked_rows({}, {}, {}, "W", "Heal") == (0.0,)
        assert _healing.ranked_rows(
            _healing_champion(), {"W": {"rank": 2}}, {}, "W", "Gone"
        ) == (0.0,)

    def test_the_target_free_read_matches_omitting_the_target(self) -> None:
        """Passing ``{}`` is what ``scaling.resolve_scaling`` reads for no target."""
        champion = _healing_champion()
        ability = champion["abilities"]["W"][0]
        assert _healing.ranked_rows(champion, {"W": {"rank": 1}}, {}, "W", "Heal") == (
            extract_named(ability, "Heal", 1, {}),
        )


def _damage_event(time: float, damage: float = 100.0) -> dict:
    return {"time": time, "damage": damage, "source_key": "W", "sequence": 0}


class TestCastHeals:
    """The self-heal a rule pays once per cast of one slot."""

    _EVENTS = [_damage_event(0.0), _damage_event(5.0), _damage_event(10.0)]
    _CASTS = [{"slot": "W", "time": t} for t in (0.0, 5.0, 10.0)]

    def test_a_flat_amount_pays_once_per_cast(self) -> None:
        heals = _healing.cast_heals("W", "Maul", self._EVENTS, self._CASTS, amount=30.0)
        assert [heal["time"] for heal in heals] == [0.0, 5.0, 10.0]
        assert {heal["amount"] for heal in heals} == {30.0}
        assert {heal["source"] for heal in heals} == {"Maul"}

    def test_skip_casts_drops_the_leading_activations(self) -> None:
        """The first W applies the Wound the heal reads; it pays from the second."""
        heals = _healing.cast_heals(
            "W", "Maul", self._EVENTS, self._CASTS, amount=30.0, skip_casts=1
        )
        assert [heal["time"] for heal in heals] == [5.0, 10.0]

    def test_a_flat_amount_reproduces_heal_from_damage(self) -> None:
        expected: list[dict] = []
        for event in self._EVENTS:
            _healing.heal_from_damage(expected, event, 30.0, "Maul")
        assert (
            _healing.cast_heals("W", "Maul", self._EVENTS, self._CASTS, amount=30.0)
            == expected
        )

    def test_a_zero_amount_pays_nothing_at_all(self) -> None:
        """The clamp and the ``amount <= 0`` skip are the flat path's, kept."""
        assert _healing.cast_heals("W", "Maul", self._EVENTS, self._CASTS) == []
        assert (
            _healing.cast_heals("W", "Maul", self._EVENTS, self._CASTS, amount=-5.0)
            == []
        )

    def test_a_linked_heal_skips_a_cast_whose_damage_never_landed(self) -> None:
        events = [_damage_event(0.0, damage=0.0)]
        casts = [{"slot": "W", "time": 0.0}]
        assert _healing.cast_heals("W", "Maul", events, casts, amount=30.0) == []
        unlinked = _healing.cast_heals(
            "W", "Maul", events, casts, amount=30.0, link_to_damage=False
        )
        assert len(unlinked) == 1

    def test_a_formula_heal_carries_the_formula_and_a_zero_amount(self) -> None:
        formula = _healing.flat_plus_missing_heal(20.0, 5.0)
        heals = _healing.cast_heals(
            "W", "Maul", self._EVENTS, self._CASTS, amount_formula=formula
        )
        assert [heal["amount"] for heal in heals] == [0.0, 0.0, 0.0]
        assert all(heal["amount_formula"] is formula for heal in heals)
        assert heals[0]["kind"] == "champion_ability"
        assert heals[0]["_trigger_source"] == "W"
