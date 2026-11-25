"""``@ranked_at`` is the cross-slot rank guard, stated once."""

from types import SimpleNamespace

from src.calculator.champions.ranked_slots import ranked_at


def _ctx(answer):
    calls = []

    def ranked(slot, index):
        calls.append((slot, index))
        return answer

    return SimpleNamespace(ranked=ranked), calls


@ranked_at("W", 1)
def _priced(ctx, ability, rank):
    """A body that echoes what the guard handed it."""
    return ability["name"], rank


def test_the_body_receives_the_slots_ability_and_rank():
    ctx, calls = _ctx(({"name": "Hammer W"}, 4))
    assert _priced(ctx) == ("Hammer W", 4)
    assert calls == [("W", 1)]


def test_an_unranked_or_absent_slot_answers_none_without_calling_the_body():
    ctx, calls = _ctx(None)
    assert _priced(ctx) is None
    assert calls == [("W", 1)]


def test_the_wrapped_function_keeps_its_name_and_docstring():
    assert _priced.__name__ == "_priced"
    assert "echoes" in _priced.__doc__
