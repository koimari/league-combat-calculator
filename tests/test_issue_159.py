"""Issue #159 — one transition kernel drives every shield absorption path.

Absorption order and shield/health mutation used to be hand-maintained in
five places: two ordered walks in ``damage.py``, the authoritative receipt
walk, and both damage branches of the compiled score walk.  They now all
execute ``shield_ledger.absorb``.

The per-transition contract lives in ``tests/test_shield_ledger.py``; these
are the ownership guards and the end-to-end proof that the two engines agree.
"""

import re
from pathlib import Path

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    build_participant_timeline,
)

SRC = Path(__file__).parents[1] / "src" / "calculator"
LEDGER = SRC / "shield_ledger.py"

#: Draining a pool is the transition's own business.  Any other module doing
#: this arithmetic is a second implementation of the absorption order.
_POOL_DRAIN = re.compile(r"\.(physical|magic|general)_shield\s*(-=|\+=)")


class TestOneOwner:
    """No module outside the ledger may move a shield pool."""

    def test_no_other_module_consumes_or_grants_a_shield_pool(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            if path == LEDGER:
                continue
            source = path.read_text(encoding="utf-8")
            for match in _POOL_DRAIN.finditer(source):
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}")
        assert offenders == [], (
            "shield pools may only be moved by shield_ledger.absorb/grant/"
            f"expire_timed; found direct arithmetic at {offenders}"
        )

    def test_the_retired_duplicate_walks_are_gone(self):
        """The five hand-maintained copies named by the issue stay deleted."""
        retired = (
            "_LifelineShieldState",
            "_consume_typed_shield",
            "_consume_general_shield",
            "_expire_timed_shields",
        )
        for path in (SRC / "damage.py", SRC / "participant_timeline.py"):
            source = path.read_text(encoding="utf-8")
            for name in retired:
                assert name not in source, f"{name} came back in {path.name}"

    def test_every_absorption_consumer_calls_the_kernel(self):
        """Both damage.py walks and all three participant walks drive it."""
        damage = (SRC / "damage.py").read_text(encoding="utf-8")
        timeline = (SRC / "participant_timeline.py").read_text(encoding="utf-8")
        assert damage.count("shield_ledger.absorb(") == 2
        # Receipt walk, compiled plain-damage branch, compiled general branch.
        assert timeline.count("shield_ledger.absorb(") == 3


def _coupled(items, **kwargs):
    """Cassiopeia into a roster whose defenders carry real shields."""
    champion = get_champion("Cassiopeia")
    params = FightParams.from_request(
        {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
    )
    enemies = [
        ChampionLoadout(
            champion="Alistar",
            level=13,
            role="support",
            boots="Plated Steelcaps",
            items=("Randuin's Omen", "Bramble Vest"),
        ).resolve(),
        ChampionLoadout(
            champion="Dr. Mundo",
            level=13,
            role="top",
            boots="Mercury's Treads",
            items=("Kaenic Rookern",),
        ).resolve(),
    ]
    stats = calculate_total_stats(champion, 13, items, role="mid")
    return build_participant_timeline(
        champion,
        13,
        items,
        params,
        main_stats=stats,
        main_defenses=resolve_starting_defenses(champion["name"], 13, stats, items),
        enemies=enemies,
        allies=[],
        **kwargs,
    )


class TestBothRepresentationsAgree:
    """Integration proof, kept alongside the per-transition contract."""

    def test_compiled_and_receipt_walks_score_identically(self):
        cache: dict = {}
        context = CoupledSearchContext()
        for items in (
            [get_item_by_name("Rabadon's Deathcap")],
            [get_item_by_name("Void Staff")],
        ):
            fast = _coupled(
                items,
                pair_result_cache=cache,
                search_context=context,
                include_receipt=False,
            )
            assert fast == _coupled(items, include_receipt=False)

    def test_a_threshold_lifeline_falls_back_instead_of_being_dropped(self):
        """The compiled walk stages no Lifeline, so it must not score one."""
        champion = get_champion("Cassiopeia")
        params = FightParams.from_request(
            {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
        )
        enemies = [
            ChampionLoadout(
                champion="Dr. Mundo",
                level=13,
                role="top",
                items=("Sterak's Gage",),
            ).resolve()
        ]
        items = [get_item_by_name("Rabadon's Deathcap")]
        stats = calculate_total_stats(champion, 13, items, role="mid")

        def run(**kwargs):
            return build_participant_timeline(
                champion,
                13,
                items,
                params,
                main_stats=stats,
                main_defenses=resolve_starting_defenses(
                    champion["name"], 13, stats, items
                ),
                enemies=enemies,
                allies=[],
                include_receipt=False,
                **kwargs,
            )

        assert enemies[0].defenses.threshold_shield_amount > 0.0
        assert run(pair_result_cache={}, search_context=CoupledSearchContext()) == run()


class TestReviewedSemantics:
    """The two corrections unifying the walks exposed, both sourced."""

    def test_maw_lifeline_shield_is_magic_only(self):
        """ "a shield that absorbs ... magic damage for 3 seconds"."""
        maw = get_item_by_name("Maw of Malmortius")
        stats = calculate_total_stats(get_champion("Dr. Mundo"), 13, [maw])
        defenses = resolve_starting_defenses("Dr. Mundo", 13, stats, [maw])
        assert defenses.threshold_shield_amount > 0.0
        assert defenses.threshold_shield_damage_type == "magic"

    def test_a_lifeline_that_lands_exactly_on_the_threshold_does_not_arm(self):
        """ "damage that would reduce you *below*" — strict, in both walks."""
        from src.calculator.shield_ledger import ThresholdShield, absorb, build_pools

        pools = build_pools(
            1000.0,
            threshold_shield_amount=500.0,
            threshold_shield_health_ratio=0.3,
            threshold_shield_duration=4.5,
        )
        assert isinstance(pools.threshold_shield, ThresholdShield)
        absorb(pools, 700.0, "physical", 0.0)
        assert pools.threshold_shield.triggered is False
        assert pools.health == pytest.approx(300.0)
        absorb(pools, 1.0, "physical", 0.1)
        assert pools.threshold_shield.triggered is True
