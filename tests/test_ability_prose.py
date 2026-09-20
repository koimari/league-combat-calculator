"""`CachedSentence`: the numbers a cached ability states only in prose.

The type exists so a reworded wiki row raises naming the champion and the
sentence instead of answering a stale value or a measured zero, which is
what every hand-rolled reader it replaced did.
"""

import re

import pytest

from src.calculator.ability_prose import CachedSentence

MISSING = "Test P: the cached innate no longer states its sentence"


def _ability(*descriptions: str | None) -> dict:
    return {"effects": [{"description": text} for text in descriptions]}


class TestMatch:
    """One sentence, searched over each cached effect description in turn."""

    _SENTENCE = CachedSentence(
        re.compile(r"shields for (?P<value>\d+(?:\.\d+)?)%"), missing=MISSING
    )

    def test_it_answers_the_first_effect_that_states_the_sentence(self):
        ability = _ability("no numbers here", "shields for 12% of maximum health")
        assert self._SENTENCE.match(ability).group("value") == "12"

    def test_a_reworded_cache_raises_naming_the_champion_and_the_sentence(self):
        with pytest.raises(ValueError, match=MISSING):
            self._SENTENCE.match(_ability("no numbers here"))

    def test_an_ability_with_no_effects_raises_rather_than_answering(self):
        with pytest.raises(ValueError, match=MISSING):
            self._SENTENCE.match({})

    def test_an_effect_with_no_description_is_walked_past(self):
        assert self._SENTENCE.value(_ability(None, "shields for 8%")) == 8.0


class TestTypedReads:
    """The three reads a module declares beside its sentence."""

    def test_value_is_the_value_group_as_a_number(self):
        sentence = CachedSentence(
            re.compile(r"for (?P<value>\d+(?:\.\d+)?) seconds"), missing=MISSING
        )
        assert sentence.value(_ability("lasts for 2.5 seconds")) == 2.5

    def test_stack_terms_are_a_stack_s_life_and_the_cap(self):
        sentence = CachedSentence(
            re.compile(
                r"for (?P<seconds>\d+(?:\.\d+)?) seconds[^.]*?"
                r"stacking up to (?P<stacks>\d+) times"
            ),
            missing=MISSING,
        )
        ability = _ability("apply a stack for 6 seconds, stacking up to 3 times")
        assert sentence.stack_terms(ability) == (6.0, 3)

    def test_level_values_are_the_numbers_of_one_level_row(self):
        sentence = CachedSentence(
            re.compile(r"deal (?P<values>[\d.\s/]+?) \(based on level\)"),
            missing=MISSING,
        )
        ability = _ability("deal 15 / 40 / 80 / 150 (based on level) magic damage")
        assert sentence.level_values(ability) == (15.0, 40.0, 80.0, 150.0)

    def test_every_typed_read_raises_on_a_reworded_cache(self):
        sentence = CachedSentence(re.compile(r"(?P<value>\d+)%"), missing=MISSING)
        for read in (sentence.value, sentence.level_values, sentence.stack_terms):
            with pytest.raises(ValueError, match=MISSING):
                read(_ability("no numbers here"))
