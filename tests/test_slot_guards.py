"""The two guard decorators every champion slot parser is built out of.

``ability_slot`` owns the cached-entry guard and ``ranked_slot`` adds the
rank gate on top of it, so what ``None`` means at a slot is stated once
(``champions/module_helpers.py``) rather than at every parser.
"""

import pytest

from src.calculator.champions.module_helpers import ability_slot, ranked_slot
from src.calculator.champions.slot_context import SlotCtx


def _ctx(slot: str = "Q", **overrides) -> SlotCtx:
    """A slot context holding whatever abilities the case declares."""
    fields = {
        "slot": slot,
        "champion_name": "TestChamp",
        "level": 9,
        "ability_ranks": {"P": 1, "Q": 3, "W": 2, "E": 1, "R": 0},
    }
    fields.update(overrides)
    return SlotCtx(**fields)


def _named_slot(**kwargs):
    @ability_slot(**kwargs)
    def _named(ctx: SlotCtx, ability: dict) -> dict:
        """What the body documents."""
        return {"name": ability["name"], "slot": ctx.slot}

    return _named


class TestAbilitySlot:
    """The cached-entry guard the champion modules wear as a decorator."""

    def test_the_body_receives_its_own_slots_cached_entry(self) -> None:
        ctx = _ctx("W", abilities={"W": [{"name": "Move Quick"}]})
        assert _named_slot()(ctx) == {"name": "Move Quick", "slot": "W"}

    def test_a_named_slot_and_index_read_past_the_parsers_own(self) -> None:
        ctx = _ctx("W", abilities={"P": [{"name": "Innate"}, {"name": "Second"}]})
        assert _named_slot(slot="P")(ctx)["name"] == "Innate"
        assert _named_slot(slot="P", index=1)(ctx)["name"] == "Second"

    def test_an_absent_entry_prices_nothing_and_never_runs_the_body(self) -> None:
        @ability_slot()
        def _never(ctx: SlotCtx, ability: dict) -> dict:
            raise AssertionError("the body must not run without a cached entry")

        assert _never(_ctx("R", abilities={"Q": [{"name": "Q"}]})) is None
        one = _ctx(abilities={"P": [{"name": "Innate"}]})
        assert _named_slot(slot="P", index=1)(one) is None

    def test_the_wrapper_keeps_the_bodys_identity(self) -> None:
        slot = _named_slot()
        assert slot.__name__ == "_named"
        assert slot.__doc__ == "What the body documents."
        assert slot.__module__ == __name__

    def test_the_wrapper_carries_a_phase_the_module_states(self) -> None:
        slot = _named_slot()
        slot.phase = "buff"
        assert slot.phase == "buff"


class TestRankedSlot:
    """The rank gate ``ranked_slot`` adds over the same cached-entry guard."""

    @staticmethod
    def _learned():
        @ranked_slot
        def _learned(ctx: SlotCtx, ability: dict, rank: int) -> dict:
            """What the ranked body documents."""
            return {"name": ability["name"], "rank": rank}

        return _learned

    def test_a_learned_slot_is_priced_at_its_resolved_rank(self) -> None:
        ctx = _ctx("W", abilities={"W": [{"name": "Move Quick"}]})
        assert self._learned()(ctx) == {"name": "Move Quick", "rank": 2}

    @pytest.mark.parametrize(
        ("slot", "abilities"),
        [("R", {"R": [{"name": "Unlearned"}]}), ("W", {})],
        ids=["unlearned", "uncached"],
    )
    def test_neither_reason_to_price_nothing_reaches_the_body(
        self, slot, abilities
    ) -> None:
        assert self._learned()(_ctx(slot, abilities=abilities)) is None

    def test_the_wrapper_keeps_the_bodys_identity(self) -> None:
        assert self._learned().__doc__ == "What the ranked body documents."
        assert self._learned().__module__ == __name__
