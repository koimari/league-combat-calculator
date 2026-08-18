"""Wave 1D: engine-side coarse-row producers author real damage events.

Every test is a runtime probe through the public ``calculate_payload``
pipeline (timed mode, autos included, level 18) asserting that the named
(champion, item) pair certifies a complete event timeline — the frozen
classifier ``damage._event_timeline_coverage`` accepts a row only when its
authored events sum-reconcile with the row's priced total.
"""

import pytest

from src.calculator.calculate import calculate_payload


def _coverage(champion: str, items: list[str], **extra):
    """One timed level-18 fight's coverage block, through the public path."""
    return calculate_payload(
        {
            "champion": champion,
            "level": 18,
            "items": items,
            "fight_mode": "timed",
            "include_auto_attacks": True,
            **extra,
        }
    )["timeline_coverage"]


class TestSwingScheduleUnderAttackSpeedKits:
    """Mechanism 1: the swing schedule resolves instead of falling back.

    A kit-granted attack-speed steroid used to recompute the auto count on
    the flat model while the Rageblade ramp schedule kept its own length;
    the mismatch dropped the schedule and every static on-hit row stayed
    eventless.
    """

    def test_ashe_rageblade_certifies_complete(self):
        coverage = _coverage("Ashe", ["Guinsoo's Rageblade"])
        assert coverage["coarse_sources"] == []
        assert coverage["complete"] is True
        assert "on_hit_Guinsoo's Rageblade" in coverage["exact_sources"]


class TestEmpoweredSwingReattributionStaysCoarse:
    """Mechanism 1, stopped half: the reattributed auto row keeps its gap.

    ``_reattribute_empowered_swings`` moves consumed swings to the forcing
    ability at the row's *blended* per-hit average while trimming the
    ledger's tail, so whenever the stream's swings differ from each other
    the surviving events no longer sum to the row and ``auto_attacks``
    goes coarse. Both closures were measured and both move numbers this
    wave may not move: pricing the move from the ledger's own front slice
    shifts an exact-capture total, and rescaling the surviving events
    re-prices packets with no restatement (``scripts/term_census.py``).
    The row therefore stays coarse until a wave allowed to re-price it.
    """

    def test_draven_collector_auto_row_is_still_coarse(self):
        coverage = _coverage("Draven", ["The Collector"])
        assert "auto_attacks" in coverage["coarse_sources"]


class TestAbilityAttackOnHitRows:
    """Mechanism 2: ``on_hit_items_<slot>`` rows author per-application events.

    Attacks granted by abilities apply the build's on-hit items; each
    application already carries its accepted-cast timestamp, so the row
    authors one typed event per application at that hit's time.
    """

    def test_irelia_wits_end_certifies_complete(self):
        coverage = _coverage("Irelia", ["Wit's End"])
        assert "on_hit_items_Q" in coverage["exact_sources"]
        assert coverage["complete"] is True

    def test_fiora_bork_certifies_complete(self):
        coverage = _coverage("Fiora", ["Blade of the Ruined King"])
        assert "on_hit_items_Q" in coverage["exact_sources"]
        assert coverage["complete"] is True


class TestPhantomHitRows:
    """Mechanism 3: Rageblade phantom hits on ability attacks author events.

    Each phantom re-application fires immediately after its triggering
    ability attack, whose accepted-cast timestamp the application record
    already carries.
    """

    def test_belveth_rageblade_certifies_complete(self):
        coverage = _coverage("Bel'Veth", ["Guinsoo's Rageblade"])
        assert "on_hit_items_phantom" in coverage["exact_sources"]
        assert coverage["complete"] is True


class TestStackingCounterItemRows:
    """Mechanism 4: every-Nth stack counters author their proc events.

    Ability-carried applications lead the shared counter; a proc landing on
    one fires at that application's authored time, and auto-segment procs
    keep riding their swings.
    """

    @pytest.mark.parametrize("champion", ["Akshan", "Bel'Veth", "Ezreal", "Viego"])
    def test_kraken_slayer_certifies_complete(self, champion):
        coverage = _coverage(champion, ["Kraken Slayer"])
        assert "on_hit_Kraken Slayer" in coverage["exact_sources"]
        assert coverage["complete"] is True

    @pytest.mark.parametrize("champion", ["Akshan", "Bel'Veth"])
    def test_hullbreaker_certifies_complete(self, champion):
        coverage = _coverage(champion, ["Hullbreaker"])
        assert "on_hit_Hullbreaker" in coverage["exact_sources"]
        assert coverage["complete"] is True


class TestDoubleOnHitRows:
    """Mechanism 4: Dusk and Dawn's double on-hit authors its proc events.

    Each double application rides the weave-timed attack that consumed the
    spellblade charge, at that proc's accepted time.
    """

    @pytest.mark.parametrize("champion", ["Vayne", "Gwen"])
    def test_dusk_and_dawn_certifies_complete(self, champion):
        coverage = _coverage(champion, ["Dusk and Dawn"])
        assert "double_on_hit_Dusk and Dawn" in coverage["exact_sources"]
        assert coverage["complete"] is True


class TestSpellbladeTrueConversionRows:
    """Mechanism 4: Camille's converted spellblade procs author events.

    The engine prices conversion on the assumption that procs land on the
    flagged casts first; the authored events restate exactly that priced
    assignment over the certified weave-timed proc schedule.
    """

    def test_camille_dusk_and_dawn_certifies_complete(self):
        coverage = _coverage("Camille", ["Dusk and Dawn"])
        assert "spellblade_Dusk and Dawn_true" in coverage["exact_sources"]
        assert coverage["complete"] is True


class TestHorizonFocusTriggerIsolation:
    """Mechanism 4: Hypershot's exclusion isolates multi-event trigger casts.

    A first cast split into several ledger events (a multi-hit or
    multi-tick opener) matched no single event, so the amp authored
    nothing. The accepted cast ledger now scopes the trigger cast — its
    slot's events before that slot's second cast — leaving the amp's delta
    to ride everything after it. A mixed opener, whose priced trigger is
    only a part of its cast, still resolves by value or stays coarse.
    """

    @pytest.mark.parametrize("champion", ["Ekko", "Garen", "Ziggs"])
    def test_horizon_focus_certifies_complete(self, champion):
        coverage = _coverage(champion, ["Horizon Focus"])
        assert "damage_amp_Horizon Focus" in coverage["exact_sources"]
        assert coverage["complete"] is True


class TestExposeWeaknessRow:
    """Mechanism 4: Bloodsong's Expose Weakness amp authors delta events.

    The arming sequence (first cast, its consuming attack, the first
    spellblade proc) completes when the proc lands; the amp's bonus rides
    every ledger event after that boundary, pro-rata, at those events'
    own times.
    """

    def test_braum_bloodsong_support_certifies_complete(self):
        coverage = _coverage(
            "Braum",
            ["Bloodsong"],
            role="support",
            role_quest_complete=True,
        )
        assert "expose_weakness_Bloodsong" in coverage["exact_sources"]
        assert coverage["complete"] is True

    def test_camille_bloodsong_support_certifies_complete(self):
        coverage = _coverage(
            "Camille",
            ["Bloodsong"],
            role="support",
            role_quest_complete=True,
        )
        assert "expose_weakness_Bloodsong" in coverage["exact_sources"]
        assert coverage["complete"] is True


class TestRepresentativePairsStayComplete:
    """The wave's representative pairs that already certified stay certified."""

    @pytest.mark.parametrize(
        ("champion", "item"),
        [
            ("Vayne", "Blade of the Ruined King"),
            ("Jax", "Terminus"),
            ("Gwen", "Nashor's Tooth"),
            ("Ezreal", "Muramana"),
            ("Ashe", "Dusk and Dawn"),
            ("Ashe", "Kraken Slayer"),
        ],
    )
    def test_pair_certifies_complete(self, champion, item):
        coverage = _coverage(champion, [item])
        assert coverage["coarse_sources"] == []
        assert coverage["complete"] is True


PROC_WALKER_CHAMPIONS = [
    "Dr. Mundo",
    "Jayce",
    "Kalista",
    "Kayle",
    "Malphite",
    "Qiyana",
    "Sejuani",
    "Shyvana",
    "Smolder",
    "Tahm Kench",
    "Talon",
    "Twitch",
    "Varus",
    "Vel'Koz",
    "Viego",
    "Ziggs",
]


class TestCastProcWalkerRoundingTolerance:
    """The Muramana walker accepts the cast ledger's rounded boundary.

    ``cast_events`` publishes times rounded to 3 decimals while ability
    rows author raw plan times; when rounding went up, the walker skipped
    the true matching hit, exhausted the ledger and returned no events —
    leaving ``muramana_ability`` coarse for these champions.

    Eclipse's walker deliberately keeps the exact comparison: its receipts
    decide a stack pairing and a cooldown gate, so completing the walk
    moves the row's proc count off the coarse fallback.  ``proc_Eclipse``
    stays coarse for these champions until a wave allowed to re-price it.
    """

    @pytest.mark.parametrize("champion", PROC_WALKER_CHAMPIONS)
    def test_muramana_certifies_complete(self, champion):
        coverage = _coverage(champion, ["Muramana"])
        assert coverage["coarse_sources"] == []
        assert coverage["complete"] is True

    def test_eclipse_row_stays_coarse_rather_than_repricing(self):
        """The stop is pinned: closing Eclipse here would move a number."""
        coverage = _coverage("Ziggs", ["Eclipse"])
        assert coverage["coarse_sources"] == ["proc_Eclipse"]
