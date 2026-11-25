"""Kayn's reviewed crowd control (``MODULE_CC`` plus W's per-form part).

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

import pytest

from src.calculator.champions import kayn, parse_champion_abilities
from src.calculator.champions.slot_cc import CC_PER_PART
from src.calculator.stats import calculate_total_stats
from tests import cc_review


def _w_kinds(form):
    data = cc_review.kit("Kayn")
    parsed = parse_champion_abilities(
        data,
        18,
        100.0,
        champion_stats=calculate_total_stats(data, 18, []),
        champion_options={"form": form},
    )
    return sorted({part.cc_kind for part in parsed["W"]["parts"]})


class TestReviewedCrowdControl:
    """Blade's Reach answers by form, so its kind rides the part."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert kayn.MODULE_CC == {
            "Q": "none",
            "W": CC_PER_PART,
            "R": "none",
            "P": "none",
            "E": "none",
        }

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Kayn")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    @pytest.mark.parametrize(
        ("form", "kind"),
        [("base", "slow"), ("shadow_assassin", "slow"), ("darkin", "knockup")],
    )
    def test_blades_reach_carries_the_forms_own_kind(self, form, kind):
        text = cc_review.slot_text(cc_review.kit("Kayn"), "W")
        assert "slowing them by 90% decaying over 1.5 seconds" in text
        assert "blade's reach knocks up enemies hit for 1 second" in text
        assert _w_kinds(form) == [kind]


def test_darkin_reaping_slash_health_part_ignores_the_live_max_health_argument():
    """The walk calls the part as ``f(missing, max_health)``; the captured
    health share must survive that call, not become the target's max health."""
    from src.calculator.survival.transitions import evaluate_live_raw_formula
    from tests import champion_closure as closure

    parsed = closure.abilities("Kayn", options={"form": "darkin"})
    _, health = parsed["Q"]["parts"]
    share = 2000.0 * (0.06 + 0.035 * closure.stats("Kayn")["bonus_attack_damage"] / 100)
    assert health.amount == pytest.approx(share)
    assert evaluate_live_raw_formula(health.hp_scaled_damage, 0.4, 9999.0) == (
        pytest.approx(share)
    )
