"""A charge ability's cadence is its recharge, and its stock is cached.

The defect these pin: a charge slot carries two cached timers twelve times
apart, and pricing the short one as the recast cadence put eleven Electro
Harpoons in a ten-second fight. See ``champions/charge_cadence.py``.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import (
    _CHAMPION_MODULES,
    parse_champion_abilities,
)
from src.calculator.champions.charge_cadence import ChargeRule, _cached_stock
from src.calculator.data_fetcher import get_champion

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_STATS = {
    "attack_damage": 150.0,
    "bonus_attack_damage": 80.0,
    "ability_power": 100.0,
    "health": 2500.0,
    "bonus_health": 800.0,
    "armor": 100.0,
    "magic_resist": 50.0,
    "attack_speed": 1.2,
    "attack_speed_ratio": 0.7,
    "bonus_attack_speed": 40.0,
    "critical_strike_chance": 0.0,
}
_TARGET = {"health": 2000.0, "max_health": 2000.0, "armor": 100.0, "mr": 60.0}


def _entries(name: str, ranks: dict[str, int] = _RANKS, level: int = 18) -> dict:
    return parse_champion_abilities(
        get_champion(name),
        level,
        100.0,
        dict(ranks),
        champion_stats=dict(_STATS),
        target_stats=dict(_TARGET),
    )


def _charge_slots() -> list[tuple[str, str]]:
    """Every (champion, slot) the CACHE calls a charge ability."""
    found = []
    for name in sorted(_CHAMPION_MODULES):
        abilities = get_champion(name).get("abilities", {})
        for slot in ("Q", "W", "E", "R"):
            for ability in abilities.get(slot) or ():
                if ability.get("rechargeRate"):
                    found.append((name, slot))
                    break
    return found


class TestEveryChargeSlotIsReviewed:
    """The cache decides which slots are charge slots, not a name list."""

    def test_the_cache_still_holds_the_charge_slots_this_suite_reviews(self) -> None:
        assert len(_charge_slots()) == 21

    @pytest.mark.parametrize("ranks", [{"Q": 1, "W": 1, "E": 1, "R": 1}, _RANKS])
    def test_every_module_parses_at_both_ends_of_the_rank_axis(self, ranks) -> None:
        """A slot that prices the short timer raises, so this is the gate."""
        for name in sorted(_CHAMPION_MODULES):
            _entries(name, ranks=ranks, level=18 if ranks is _RANKS else 1)

    def test_a_charge_slot_prices_its_cached_recharge(self) -> None:
        for name, slot in _charge_slots():
            entry = _entries(name).get("passive" if slot == "P" else slot)
            if not isinstance(entry, dict) or "cooldown" not in entry:
                continue
            ability = get_champion(name)["abilities"][slot][0]
            rates = ability.get("rechargeRate")
            if not rates:
                continue
            rank = _RANKS[slot]
            recharge = float(rates[min(rank, len(rates)) - 1])
            # Syndra owns its cadence (authored_cadence) and says why.
            if name == "Syndra":
                continue
            assert entry["cooldown"] == pytest.approx(recharge), f"{name} {slot}"


class TestTheStockComesFromTheCache:
    """Two cached shapes state it; nothing here types a count."""

    def test_a_leveling_row_states_the_stock(self) -> None:
        ability = get_champion("Gangplank")["abilities"]["E"][0]
        assert [_cached_stock(ability, rank) for rank in (1, 3, 5)] == [3, 4, 5]

    def test_the_stocking_sentence_states_the_stock(self) -> None:
        ability = get_champion("Rumble")["abilities"]["E"][0]
        assert _cached_stock(ability, 5) == 2

    def test_a_debuff_stack_sentence_is_not_read_as_a_stock(self) -> None:
        """Rumble E's page also says the SHRED stacks 'up to 2 times'; the
        stocking verb is what keeps the two apart, so a page that loses its
        stocking sentence must answer None rather than the debuff's limit."""
        ability = dict(get_champion("Rumble")["abilities"]["E"][0])
        ability["notes"] = "These effects stack additively, up to a maximum of 5 times."
        ability["effects"] = ()
        ability["blurb"] = ""
        assert _cached_stock(ability, 5) is None

    def test_the_reviewed_stock_reaches_the_entry(self) -> None:
        assert _entries("Rumble")["E"]["charge_pool"] == 2
        assert _entries("Rumble")["E"]["charge_between_casts"] == pytest.approx(0.5)


class TestTheScheduleSpendsTheStockThenRecharges:
    """The behavior the whole change exists for."""

    @staticmethod
    def _casts(champion: str, seconds: float, slot: str) -> int:
        payload = calculate_payload(
            {
                "champion": champion,
                "level": 18,
                "items": [],
                "runes": {},
                "target": {"champion": "Malphite", "level": 18},
                "fight_mode": "time_based",
                "fight_duration": seconds,
                "deterministic": True,
                "auto_attack_uptime": 1.0,
            }
        )
        return int(payload["breakdown"][slot]["casts"])

    def test_a_ten_second_fight_spends_two_banked_harpoons_and_one_recharge(
        self,
    ) -> None:
        """Rumble E: 2 stocked + 1 banked at 6s. Eleven before this."""
        assert self._casts("Rumble", 10.0, "E") == 3

    def test_a_one_second_fight_spends_only_what_is_banked(self) -> None:
        """Both charges are already in hand, held apart by the cached 0.5s
        gap and by nothing else."""
        assert self._casts("Rumble", 1.0, "E") == 2

    def test_a_single_charge_slot_is_held_by_its_recharge_alone(self) -> None:
        """Vel'Koz W banks two rifts and then waits 15s for the third."""
        assert self._casts("Vel'Koz", 10.0, "W") == 2
        assert self._casts("Vel'Koz", 16.0, "W") == 3


class TestTheRuleRefusesWhatItCannotPrice:
    def test_a_rule_needs_its_review(self) -> None:
        with pytest.raises(ValueError, match="why"):
            ChargeRule(why="   ")

    def test_a_stock_below_one_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            ChargeRule(why="a slot under test", charges=0)
