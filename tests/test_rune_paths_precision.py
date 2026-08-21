"""Precision's minor runes: what each one compiles to, and what it costs.

Precision's rows split three ways and each half of the split is pinned here.
Row 1 pays on an event the pair engine never produces, so all three compile
to receipted refusals. Row 2 grows with a game-long ``Legend`` counter, which
becomes a declared option: Alacrity's attack speed and Bloodline's bonus
health are real grants read through the real pipeline, while Haste's *basic*
ability haste has no rune channel and is refused with its number quoted. Row
3's Coup de Grace is pinned in ``test_rune_paths.py`` beside the other
exemplars.
"""

import pytest

from src.calculator import rune_effects
from src.calculator.calculate import calculate_payload
from src.calculator.rune_paths import precision

# The two probe requests, each chosen so the grant under test is the only
# thing that moves. Jinx's window is long enough that three percent of
# attack speed buys a whole extra auto; Ashe's rotation reads nothing but
# her stat block, so bonus health shows up there and nowhere else.
_ATTACK_SPEED_PROBE = {
    "champion": "Jinx",
    "level": 12,
    "items": ["Doran's Blade"],
    "fight_mode": "time_based",
    "fight_duration": 30.0,
    "auto_attack_uptime_mode": "calculated",
    "ability_ranks": {"Q": 4, "W": 3, "E": 3, "R": 2},
    "target_health": 10000.0,
    "target_armor": 100.0,
    "target_mr": 100.0,
}
_HEALTH_PROBE = {
    "champion": "Ashe",
    "level": 18,
    "items": [],
    "fight_mode": "one_rotation",
    "target_health": 2000.0,
    "target_armor": 100.0,
    "target_mr": 100.0,
}


class TestLegendAlacrity:
    """Row 2: bonus attack speed, a cached base plus a cached per-stack step."""

    def test_it_grants_the_base_and_the_step_the_cache_states(self):
        """3% flat, 1.5% per stack, 18% at the ten-stack maximum."""
        effect = rune_effects.resolve_rune("Legend: Alacrity")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is rune_effects.RuneStat.ATTACK_SPEED_PERCENT
        assert effect.amount(_context()) == pytest.approx(3.0)
        assert effect.amount(_context(stacks=1)) == pytest.approx(4.5)
        assert effect.amount(_context(stacks=10)) == pytest.approx(18.0)

    def test_the_default_is_no_stacks_and_the_disclosure_says_so(self):
        effect = rune_effects.resolve_rune("Legend: Alacrity")
        assert "18% at its 10-stack maximum" in effect.disclosures[0]
        assert "'legend_stacks' option, whose default is no stacks" in (
            effect.disclosures[0]
        )

    def test_its_option_is_a_count_bounded_by_the_cached_ceiling(self):
        option = precision.OPTIONS["Legend: Alacrity"][0]
        assert option.key == "legend_stacks"
        assert option.kind is rune_effects.RuneOptionKind.COUNT
        assert (option.default, option.bounds) == (0.0, (0.0, 10.0))
        with pytest.raises(ValueError, match="between 0 and 10"):
            option.validated(11)
        with pytest.raises(ValueError, match="whole number"):
            option.validated(2.5)


class TestLegendBloodline:
    """Row 2: the bonus health its last stack grants, and the life steal it cannot."""

    def test_the_bonus_health_arrives_only_at_the_cached_maximum(self):
        """85 bonus health at fifteen stacks; nothing at fourteen."""
        effect = rune_effects.resolve_rune("Legend: Bloodline")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is rune_effects.RuneStat.BONUS_HEALTH
        assert effect.amount(_context()) == 0.0
        assert effect.amount(_context(stacks=14)) == 0.0
        assert effect.amount(_context(stacks=15)) == pytest.approx(85.0)

    def test_the_life_steal_is_withheld_with_its_numbers_quoted(self):
        """0.45% per stack, 6.75% at fifteen — refused, never estimated."""
        effect = rune_effects.resolve_rune("Legend: Bloodline")
        assert "0.45% per stack, 6.75% at maximum" in effect.disclosures[1]
        assert "no rune grants into it" in effect.disclosures[1]

    def test_its_option_ceiling_is_fifteen_not_ten(self):
        """Bloodline banks five more stacks than its row siblings."""
        option = precision.OPTIONS["Legend: Bloodline"][0]
        assert option.bounds == (0.0, 15.0)
        with pytest.raises(ValueError, match="between 0 and 15"):
            option.validated(16)


class TestLegendHaste:
    """Row 2: a real stat, refused because the rune channels would misplace it."""

    def test_it_is_withheld_and_names_the_haste_it_would_have_granted(self):
        effect = rune_effects.resolve_rune("Legend: Haste")
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert effect.zero_policy.disposition.name == "WITHHELD"
        assert "1.5 basic ability haste per Legend stack (15 at its" in (
            effect.zero_policy.reason
        )
        assert "which the ultimate reads as well" in effect.zero_policy.reason

    def test_it_declares_no_option_because_it_prices_nothing(self):
        assert "Legend: Haste" not in precision.OPTIONS


class TestTheRowThatPaysOnATakedown:
    """Row 1: three rewards for events one simulated fight never produces."""

    @pytest.mark.parametrize(
        "name,phrase",
        [
            ("Absorb Life", "there is nothing to kill"),
            ("Triumph", "the simulated fight scores none"),
            ("Presence of Mind", "not gated by a resource"),
        ],
    )
    def test_each_is_withheld_for_the_reason_it_states(self, name, phrase):
        effect = rune_effects.resolve_rune(name)
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert effect.zero_policy.disposition.name == "WITHHELD"
        assert phrase in effect.zero_policy.reason

    def test_absorb_life_also_discloses_that_its_number_never_parsed(self):
        """The wiki states a piecewise rule; the cache holds no heal at all."""
        effect = rune_effects.resolve_rune("Absorb Life")
        assert rune_effects.RUNE_EFFECTS["Absorb Life"]["effects"] == {}
        assert "the amount is unknown on top of being unpriced" in effect.receipts[1]


class TestTheGrantsReachTheRealPipeline:
    def test_alacrity_moves_attack_speed_and_the_autos_it_buys(self):
        """1.3428 -> 1.3615 at no stacks is +3%, and buys a 31st auto.

        Ten stacks is 1.4553 (+18%) and 33 autos. The damage moves with the
        auto count, so the rune is priced through the swing rate rather than
        through a row of its own.
        """
        bare = calculate_payload(dict(_ATTACK_SPEED_PROBE))
        unstacked = calculate_payload(
            {**_ATTACK_SPEED_PROBE, "minor_runes": ["Legend: Alacrity"]}
        )
        stacked = calculate_payload(
            {
                **_ATTACK_SPEED_PROBE,
                "minor_runes": ["Legend: Alacrity"],
                "rune_options": {"Legend: Alacrity": {"legend_stacks": 10}},
            }
        )
        speeds = [
            result["champion_stats"]["attack_speed"]
            for result in (bare, unstacked, stacked)
        ]
        assert speeds == [
            pytest.approx(1.3428, abs=5e-5),
            pytest.approx(1.3615, abs=5e-5),
            pytest.approx(1.4553, abs=5e-5),
        ]
        # Bonus attack speed enters as base_AS + AS_ratio x percent/100, so
        # the eighteen-percent delta is exactly six times the three-percent
        # one — the grant is a percent of the ratio, never of the total.
        assert speeds[2] - speeds[0] == pytest.approx(6 * (speeds[1] - speeds[0]))
        autos = [
            result["auto_attack_schedule"]["expected_autos_total"]
            for result in (bare, unstacked, stacked)
        ]
        assert autos == [30, 31, 33]
        assert bare["total_damage"] == pytest.approx(2238.9, abs=0.05)
        assert unstacked["total_damage"] == pytest.approx(2289.4, abs=0.05)
        assert stacked["total_damage"] == pytest.approx(2390.4, abs=0.05)

    def test_bloodline_moves_health_only_at_its_maximum(self):
        """2327 health, and 2412 once the fifteenth stack lands."""
        bare = calculate_payload(dict(_HEALTH_PROBE))
        request = {**_HEALTH_PROBE, "minor_runes": ["Legend: Bloodline"]}
        unstacked = calculate_payload(dict(request))
        short = calculate_payload(
            {**request, "rune_options": {"Legend: Bloodline": {"legend_stacks": 14}}}
        )
        full = calculate_payload(
            {**request, "rune_options": {"Legend: Bloodline": {"legend_stacks": 15}}}
        )
        assert bare["champion_stats"]["health"] == 2327
        assert unstacked["champion_stats"]["health"] == 2327
        assert short["champion_stats"]["health"] == 2327
        assert full["champion_stats"]["health"] == 2412

    def test_a_withheld_rune_publishes_its_receipt_and_moves_no_number(self):
        bare = calculate_payload(dict(_HEALTH_PROBE))
        withheld = calculate_payload(
            {**_HEALTH_PROBE, "minor_runes": ["Triumph", "Legend: Haste"]}
        )
        assert withheld["total_damage"] == pytest.approx(bare["total_damage"])
        assert withheld["champion_stats"] == bare["champion_stats"]
        assert any("Triumph is not priced" in note for note in withheld["notes"])
        assert any("Legend: Haste is not priced" in note for note in withheld["notes"])


class TestThePathIsCovered:
    #: Unit A2 owns these two: both need the flat damage-amp kind it adds.
    _AWAITING_THE_FLAT_AMP = {"Cut Down", "Last Stand"}

    def test_every_precision_minor_rune_compiles(self):
        catalog = {
            entry["name"]: entry["implemented"]
            for entry in rune_effects.rune_catalog()
            if entry["path"] == "Precision" and entry["row"] > 0
        }
        assert len(catalog) == 9
        uncovered = {name for name, done in catalog.items() if not done}
        assert uncovered <= self._AWAITING_THE_FLAT_AMP
        assert set(precision.COMPILERS) == set(catalog) - uncovered

    def test_every_compiled_precision_rune_resolves_to_an_effect(self):
        for name in precision.COMPILERS:
            assert rune_effects.resolve_rune(name) is not None


def _context(*, stacks=None):
    """A stat context at level 18, optionally carrying a Legend stack count."""
    options = {}
    if stacks is not None:
        options = {
            name: {"legend_stacks": stacks}
            for name in ("Legend: Alacrity", "Legend: Bloodline")
        }
    return rune_effects.RuneStatContext(
        level=18,
        is_melee=False,
        bonus_attack_damage=0.0,
        ability_power=0.0,
        options=options,
    )
