"""Front-door tests for champion-owned healing rules.

Detailed issue and champion cases remain in the E1 and ledger suites.  The
Taric case here gives the shared healing module an obvious first file.
"""

import pytest

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
        from src.calculator.healing_legacy import HealAnchor, _payments

        with pytest.raises(ValueError, match="one slot"):
            _payments(HealAnchor.CAST, lambda source: True, [], None)

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
