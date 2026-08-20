"""Wave 1D: engine-side coarse-row producers author real damage events.

Every test is a runtime probe through the public ``calculate_payload``
pipeline (timed mode, autos included, level 18) asserting that the named
(champion, item) pair certifies a complete event timeline — the frozen
classifier ``damage._event_timeline_coverage`` accepts a row only when its
authored events sum-reconcile with the row's priced total.
"""

import pytest

from src.calculator import damage
from src.calculator.calculate import calculate_payload
from src.calculator.pipeline import run_fight
from src.calculator.scenario import parse_scenario_request, resolve_scenario


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


def _auto_row(champion: str, items: list[str], *, deterministic: bool = False):
    """The engine's own ``auto_attacks`` row for that same timed fight.

    ``calculate_payload`` rounds its published ledger for display, and the
    invariant below is about the numbers the engine authored, so this runs
    the identically resolved scenario and reads the row itself.
    """
    request = parse_scenario_request(
        {
            "champion": champion,
            "level": 18,
            "items": items,
            "fight_mode": "timed",
            "include_auto_attacks": True,
        },
        deterministic=deterministic,
    )
    resolved = resolve_scenario(request)
    result = run_fight(
        resolved.champion_data,
        request.level,
        list(resolved.items),
        resolved.fight_params,
    )
    return result["breakdown"]["auto_attacks"]


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


# The census's crit/attack-speed family: every item here rolls critical
# strikes, and every champion here forces a swing with an
# ``empowers_next_auto`` ability, so each pair reaches
# ``_reattribute_empowered_swings`` with a stream whose swings differ from
# each other at random.
ROLLED_CRIT_PAIRS = [
    ("Jax", "Zeal"),
    ("Draven", "The Collector"),
    ("Camille", "Phantom Dancer"),
    ("Darius", "Rapid Firecannon"),
    ("Garen", "Navori Flickerblade"),
    ("Nasus", "Essence Reaver"),
    ("Shyvana", "Stormrazor"),
    ("Cho'Gath", "Immortal Shieldbow"),
    ("Dr. Mundo", "Runaan's Hurricane"),
    ("Kayle", "Mortal Reminder"),
]

# The same mechanism without any roll: Sundered Sky's forced first-auto
# crit and Fiendhunter's empowered opening swings make the stream unequal
# in deterministic pricing too.
UNEQUAL_SWING_PAIRS = [
    ("Fiora", "Sundered Sky"),
    ("Jayce", "Fiendhunter Bolts"),
]

# Enough fights that a stream with no critical strike at all is not a
# credible explanation for a green run.
CRIT_ROLL_RUNS = 12


class TestEmpoweredSwingReattributionPricesItsOwnLedger:
    """Mechanism 1, closed half: the moved swings are priced at themselves.

    ``_reattribute_empowered_swings`` moved consumed swings to the forcing
    ability at the row's *blended* per-hit average while trimming the
    ledger's tail, so the row's total and the row's own events described
    different things whenever the stream's swings differed from each
    other. A rolled critical strike does that at random: the identical
    request certified on one run and went coarse on the next. The move now
    debits exactly the swings it removes, so the row is the sum of its own
    ledger — one realization — in both modes.
    """

    @pytest.mark.parametrize(
        ("champion", "item"), ROLLED_CRIT_PAIRS + UNEQUAL_SWING_PAIRS
    )
    def test_pair_certifies_on_every_run(self, champion, item):
        for _ in range(CRIT_ROLL_RUNS):
            coverage = _coverage(champion, [item])
            assert coverage["coarse_sources"] == []
            assert coverage["complete"] is True

    @pytest.mark.parametrize(("champion", "item"), ROLLED_CRIT_PAIRS)
    def test_authored_swings_sum_to_the_row_on_every_run(self, champion, item):
        rolled_a_crit = False
        for _ in range(CRIT_ROLL_RUNS):
            row = _auto_row(champion, [item])
            events = row["damage_events"]
            crits = [event for event in events if event["critical_strike"]]
            rolled_a_crit = rolled_a_crit or bool(crits)
            assert len(events) == row["count"]
            assert sum(event["damage"] for event in events) == pytest.approx(
                row["total_damage"], rel=1e-9, abs=1e-6
            )
            # The published crit split counts the swings the row kept, not
            # a proportion of the swings it started with.
            assert len(crits) == row["num_crits"]
            assert row["num_non_crits"] == len(events) - len(crits)
        assert rolled_a_crit, "no critical strike rolled: the invariant went untested"

    @pytest.mark.parametrize(("champion", "item"), UNEQUAL_SWING_PAIRS)
    def test_unequal_swings_reconcile_without_a_roll(self, champion, item):
        row = _auto_row(champion, [item], deterministic=True)
        events = row["damage_events"]
        assert len({round(event["damage"], 6) for event in events}) > 1
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"], rel=1e-9, abs=1e-6
        )


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
    """Both cast-proc walkers accept the cast ledger's rounded boundary.

    ``cast_events`` publishes times rounded to 3 decimals while ability
    rows author raw plan times; when rounding went up, a walker skipped
    the true matching hit, exhausted the ledger and returned no events —
    leaving ``muramana_ability`` coarse for these champions, and Eclipse's
    stack schedule falling back to a coarse proc count.
    """

    @pytest.mark.parametrize("champion", PROC_WALKER_CHAMPIONS)
    def test_muramana_certifies_complete(self, champion):
        coverage = _coverage(champion, ["Muramana"])
        assert coverage["coarse_sources"] == []
        assert coverage["complete"] is True


def _eclipse_row(champion: str, duration: float):
    """The engine's own ``proc_Eclipse`` row, events and all.

    ``calculate_payload`` strips per-row ``damage_events`` from its
    published breakdown, and the invariants below are about the schedule
    the engine authored, so this runs the identically resolved scenario.
    """
    request = parse_scenario_request(
        {
            "champion": champion,
            "level": 18,
            "items": ["Eclipse"],
            "fight_mode": "timed",
            "include_auto_attacks": True,
            "fight_duration": duration,
        },
        deterministic=True,
    )
    resolved = resolve_scenario(request)
    result = run_fight(
        resolved.champion_data,
        request.level,
        list(resolved.items),
        resolved.fight_params,
    )
    return result["breakdown"]["proc_Eclipse"]


#: Ever Rising Moon's own cooldown and pairing window, read from the item.
ECLIPSE_COOLDOWN = 6.0
ECLIPSE_STACK_WINDOW = 2.0

#: Every fight length the cadence is measured over, with the proc count a
#: representative sparse-cast champion (Ziggs) reaches in each.  The coarse
#: fallback priced ``1 + duration // cooldown`` — 1, 2, 2, 4, 6.
ZIGGS_CADENCE = [(5.0, 1), (8.0, 1), (10.0, 2), (20.0, 3), (30.0, 4)]


class TestEclipseStackPairingCadence:
    """Ever Rising Moon prices its sourced pairing, not an arithmetic count.

    ``data/items.json``'s Ever Rising Moon: damaging basic attacks and
    abilities "apply stacks against enemy champions, up to one per cast
    instance per champion", and "applying 2 stacks to a champion within a
    2 second period" deals the damage, on the passive's 6 s cooldown.  The
    coarse fallback priced ``1 + duration / cooldown`` procs, which assumes
    a second stack is always waiting the instant the cooldown expires; a
    sparse cast stream does not offer one.
    """

    @pytest.mark.parametrize(("duration", "procs"), ZIGGS_CADENCE)
    def test_the_proc_count_follows_the_sourced_cadence(self, duration, procs):
        row = _eclipse_row("Ziggs", duration)
        assert row["count"] == procs
        assert len(row["damage_events"]) == procs
        assert procs <= 1 + int(duration / ECLIPSE_COOLDOWN)

    @pytest.mark.parametrize("champion", ["Ziggs", "Skarner", "Ahri", "Aatrox"])
    @pytest.mark.parametrize("duration", [5.0, 8.0, 10.0, 20.0, 30.0])
    def test_consecutive_procs_wait_out_the_per_target_cooldown(
        self, champion, duration
    ):
        row = _eclipse_row(champion, duration)
        times = [event["time"] for event in row["damage_events"]]
        assert times == sorted(times)
        assert all(
            later - earlier >= ECLIPSE_COOLDOWN - 1e-9
            for earlier, later in zip(times, times[1:])
        )

    @pytest.mark.parametrize("champion", ["Ziggs", "Skarner", "Ahri", "Aatrox"])
    @pytest.mark.parametrize("duration", [5.0, 8.0, 10.0, 20.0, 30.0])
    def test_every_proc_pairs_two_hits_inside_the_stack_window(
        self, champion, duration
    ):
        """Two distinct cast instances land in the window that armed it."""
        payload = {
            "champion": champion,
            "level": 18,
            "items": ["Eclipse"],
            "fight_mode": "timed",
            "include_auto_attacks": True,
            "fight_duration": duration,
        }
        ledger = calculate_payload(payload)["damage_events"]
        instances = {
            (event["source"], round(float(event["time"]), 3))
            for event in ledger
            if event["source"] != "proc_Eclipse"
        }
        procs = [
            float(event["time"])
            for event in ledger
            if event["source"] == "proc_Eclipse"
        ]
        ready = 0.0
        for proc in procs:
            window = [
                time
                for _source, time in instances
                if proc - ECLIPSE_STACK_WINDOW - 1e-6 <= time <= proc + 1e-6
                and time >= ready - 1e-6
            ]
            assert len(window) >= 2
            ready = proc + ECLIPSE_COOLDOWN

    @pytest.mark.parametrize("champion", ["Ziggs", "Skarner", "Ahri", "Aatrox"])
    @pytest.mark.parametrize("duration", [5.0, 8.0, 10.0, 20.0, 30.0])
    def test_the_authored_events_sum_to_the_row(self, champion, duration):
        row = _eclipse_row(champion, duration)
        authored = sum(float(event["damage"]) for event in row["damage_events"])
        assert authored == pytest.approx(float(row["total_damage"]))
        assert len(row["self_shield_events"]) == row["count"]

    def test_a_multi_hit_cast_contributes_one_stack_not_one_per_hit(self):
        """Skarner's Q authors three packets at one timestamp — one instance.

        Counting per packet would pair the cast with itself and proc at
        ``t = 0`` twice over; the sourced clause is one stack per cast
        instance, so an 8 s fight whose only other trigger inside the
        window is the opening swing procs exactly once.
        """
        row = _eclipse_row("Skarner", 8.0)
        assert row["count"] == 1
        assert [event["time"] for event in row["damage_events"]] == [0.0]


#: Champions whose Eclipse row was coarse before the walk was completed —
#: one per reason the cursor used to abandon a cast (an up-rounded cast
#: time, a multi-hit cast's repeated packets, a forced-swing cast).
ECLIPSE_COARSE_CHAMPIONS = [
    "Ziggs",
    "Jayce",
    "Ambessa",
    "Alistar",
    "Blitzcrank",
    "Jarvan IV",
    "Camille",
    "Draven",
]


class TestEclipseTimedCoverage:
    """Timed coverage is complete for every champion holding Eclipse."""

    @pytest.mark.parametrize("champion", ECLIPSE_COARSE_CHAMPIONS)
    @pytest.mark.parametrize("duration", [8.0, 20.0, 30.0])
    def test_eclipse_certifies_complete(self, champion, duration):
        coverage = _coverage(champion, ["Eclipse"], fight_duration=duration)
        assert coverage["coarse_sources"] == []
        assert coverage["complete"] is True


#: Every fight length the burst schedule is measured over.  Jayce is the one
#: kit declaring an ``empowers_next_auto`` burst rate (Hyper Charge's three
#: attacks at the attack-speed cap), so he is the whole affected population.
BURST_DURATIONS = [5.0, 8.0, 10.0, 20.0, 30.0]


def _swing_schedule(
    monkeypatch, champion: str, items: list[str], duration: float
) -> list[float]:
    """The whole authored swing schedule the fight priced against.

    The published ``auto_attacks`` row is only the swings the stream KEPT —
    ``_reattribute_empowered_swings`` hands the consumed ones to the
    ability that forced them — so the invariant about where swings land is
    read off the schedule itself, which every proc walker also reads.
    """
    captured: list[list[float]] = []
    original = damage._auto_attack_timestamps

    def spy(state):
        times = original(state)
        captured.append(list(times))
        return times

    monkeypatch.setattr(damage, "_auto_attack_timestamps", spy)
    request = parse_scenario_request(
        {
            "champion": champion,
            "level": 18,
            "items": items,
            "fight_mode": "timed",
            "include_auto_attacks": True,
            "fight_duration": duration,
        },
        deterministic=True,
    )
    resolved = resolve_scenario(request)
    run_fight(
        resolved.champion_data,
        request.level,
        list(resolved.items),
        resolved.fight_params,
    )
    assert captured, "the fight priced no auto stream"
    longest = max(captured, key=len)
    assert all(times == longest for times in captured if times), "schedule disagreed"
    return longest


class TestEmpoweredBurstSwingSchedule:
    """A kit burst fires where its cast is, and the fight cannot outrun itself.

    Jayce's Hyper Charge fires three attacks at the attack-speed cap, which
    costs the fight less time than three ordinary swings and so buys extra
    ordinary autos.  The count knew that; the schedule did not, and laid
    every swing at the ordinary rate — a 20 s fight authored 24 swings ending
    at 28.9 s, and Ever Rising Moon paired two of its five procs after the
    fight was over.
    """

    @pytest.mark.parametrize("duration", BURST_DURATIONS)
    @pytest.mark.parametrize("items", [[], ["Eclipse"], ["Fiendhunter Bolts"]])
    def test_no_swing_is_authored_past_the_end_of_the_fight(
        self, monkeypatch, items, duration
    ):
        times = _swing_schedule(monkeypatch, "Jayce", items, duration)
        assert times
        assert max(times) <= duration + 1e-9

    @pytest.mark.parametrize("duration", BURST_DURATIONS)
    def test_the_burst_hits_land_on_their_own_cast(self, monkeypatch, duration):
        """Each Hyper Charge's attacks start at the cast that forced them."""
        payload = calculate_payload(
            {
                "champion": "Jayce",
                "level": 18,
                "items": ["Eclipse"],
                "fight_mode": "timed",
                "include_auto_attacks": True,
                "fight_duration": duration,
            }
        )
        casts = [
            float(event["time"])
            for event in payload["cast_timeline"]
            if event["slot"] == "W"
        ]
        times = _swing_schedule(monkeypatch, "Jayce", ["Eclipse"], duration)
        assert casts
        for cast in casts:
            assert any(abs(time - cast) <= 1e-3 for time in times)

    @pytest.mark.parametrize("duration", BURST_DURATIONS)
    def test_every_eclipse_proc_lands_inside_the_fight(self, duration):
        row = _eclipse_row("Jayce", duration)
        assert row["damage_events"]
        assert max(float(e["time"]) for e in row["damage_events"]) <= duration + 1e-9

    def test_a_burst_cast_only_buys_the_attacks_the_window_holds(self, monkeypatch):
        """A Hyper Charge starting at 29.995 s lands one attack, not three.

        The count is a time budget, so charging the fight for three attacks
        it has no room for is the same overcount spent on swings instead of
        clock: the sixth cast lands 1 of its 3, and the stream holds 35
        swings rather than the 37 the old arithmetic bought.
        """
        thirty = _swing_schedule(monkeypatch, "Jayce", [], 30.0)
        assert len(thirty) == 35
        assert max(thirty) <= 30.0 + 1e-9


def _breakdown(champion: str, items: list[str], **extra):
    """One timed level-18 fight's own breakdown, unrounded."""
    request = parse_scenario_request(
        {
            "champion": champion,
            "level": 18,
            "items": items,
            "fight_mode": "timed",
            "include_auto_attacks": True,
            **extra,
        },
        deterministic=True,
    )
    resolved = resolve_scenario(request)
    return run_fight(
        resolved.champion_data,
        request.level,
        list(resolved.items),
        resolved.fight_params,
    )


# Every one of these is a lethality/armor-penetration build on a champion
# whose empowering ability consumes the whole auto stream, which is what
# leaves the ``auto_attacks`` row with no swings at all.
GAVE_AWAY_EVERY_SWING = [
    ("Vayne", "Edge of Night"),
    ("Vayne", "The Brutalizer"),
    ("Shen", "The Collector"),
    ("Shen", "Umbral Glaive"),
    ("Shen", "Serylda's Grudge"),
]


class TestAnEmptyAutoRowIsWorthExactlyZero:
    """A row that gave every swing away reads 0.0, not a floating crumb.

    ``_event_timeline_coverage`` skips a row at ``total_damage <= 0``, so a
    residue of 1.1e-13 made an empty ledger an "active damage source using
    coarse phase ordering" and took the whole fight to
    ``partial_event_order``.  The row is the sum of its own ledger by
    construction — the swing simulator publishes the ledger's sum rather
    than a running total beside it — so giving every swing away subtracts
    that same number from itself.
    """

    @pytest.mark.parametrize(("champion", "item"), GAVE_AWAY_EVERY_SWING)
    def test_the_row_is_exactly_zero_and_the_fight_certifies(self, champion, item):
        row = _breakdown(champion, [item])["breakdown"]["auto_attacks"]
        assert row["count"] == 0
        assert row["damage_events"] == []
        assert row["total_damage"] == 0.0
        coverage = _coverage(champion, [item])
        assert coverage["coarse_sources"] == []
        assert coverage["complete"] is True


# Each of these declares ``empowers_next_auto`` and owns no part that emits
# its own events, so the row's whole damage is the swing reattribution
# moves onto it.
EMPOWERED_ROWS = [
    ("Leona", "Q"),
    ("Cho'Gath", "E"),
    ("Fiora", "E"),
    ("Jax", "W"),
]


class TestEmpoweredRowsAuthorTheSwingsTheyConsumed:
    """The reattributed damage lands on the stream, not the cast boundary.

    Without an authored event the row's damage reached the fight ledger
    only as one lump synthesized at its cast time, and a reviewed
    ``cc_kind`` had nothing to ride — which is what keeps these four kits
    coarse for a control-armed holder shield (Fimbulwinter's Everlasting).
    """

    @pytest.mark.parametrize(("champion", "slot"), EMPOWERED_ROWS)
    def test_events_sum_to_the_row(self, champion, slot):
        row = _breakdown(champion, ["Fimbulwinter"])["breakdown"][slot]
        events = row["damage_events"]
        assert events
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"], rel=1e-9, abs=1e-6
        )

    @pytest.mark.parametrize(("champion", "slot"), EMPOWERED_ROWS)
    def test_events_land_on_the_casts_that_forced_them(self, champion, slot):
        """Each consumed swing is timed at the cast that consumed it.

        All four of these empowers reset the attack timer, so the swing
        lands with the cast — the instant the reconstruction has always
        placed this damage at, which is why authoring it moves no number.
        The row's damage came from the stream's trailing swings (wave 1E
        prices the move there), and those sit at the far end of a long
        fight: timing the events from them would post a cast's damage
        seconds before or after the cast that forced it.
        """
        result = _breakdown(champion, ["Fimbulwinter"])
        row = result["breakdown"][slot]
        moved = sorted({round(float(e["time"]), 3) for e in row["damage_events"]})
        casts = sorted(
            round(float(event["time"]), 3)
            for event in result["cast_timeline"]
            if event["slot"] == slot
        )
        assert moved
        assert moved == casts[: len(moved)]

    def test_a_self_rated_burst_uses_its_own_declared_impacts(self):
        """Jayce's Hyper Charge does not swing at its cast boundary.

        Its three attacks fire at the burst's own rate, and the burst wave
        already resolved where they land (``BurstSwingSchedule.by_ability``).
        The row reads that schedule rather than repeating the cast time
        once per hit.
        """
        result = _breakdown("Jayce", ["Fimbulwinter"], fight_duration=10.0)
        times = sorted(
            {
                round(float(e["time"]), 3)
                for e in result["breakdown"]["W"]["damage_events"]
            }
        )
        casts = sorted(
            round(float(event["time"]), 3)
            for event in result["cast_timeline"]
            if event["slot"] == "W"
        )
        assert len(times) > len(casts)
        assert set(casts) <= set(times)
        interval = times[1] - times[0]
        assert interval > 0
        assert times[2] - times[1] == pytest.approx(interval, rel=1e-6)


class TestADeclaredControlKindRidesTheConsumedSwing:
    """What the authoring is for: the marker now has an event to ride.

    Cho'Gath's Vorpal Spikes is the one of the four whose entry owns a part
    at all, so ``engine._apply_module_cc`` can stamp a ``MODULE_CC``
    declaration on it — this stands in for that declaration and shows the
    kind reaching the fight ledger on the swings the cast consumed, which
    clears Fimbulwinter's Everlasting scan.  The module's own declaration
    is still owed; ``engine._validate_cc_event_contract`` rejects it today
    because it reads part timing only and cannot see this authoring.
    """

    def test_fimbulwinter_certifies_once_the_kind_is_declared(self, monkeypatch):
        from dataclasses import replace as _replace  # pylint: disable=C0415

        from src.calculator import champions  # pylint: disable=C0415
        from src.calculator.champions import chogath  # pylint: disable=C0415

        parse = chogath.parse_abilities

        def declared(*args, **kwargs):
            entries = parse(*args, **kwargs)
            entry = entries["E"]
            entry["parts"] = tuple(
                _replace(part, cc_kind="slow") for part in entry["parts"]
            )
            return entries

        declared.cc_kinds = {**parse.cc_kinds, "E": "slow"}
        monkeypatch.setattr(chogath, "MODULE_CC", declared.cc_kinds)
        monkeypatch.setattr(chogath, "parse_abilities", declared)
        # The registry caches the resolved contract per champion; a fresh
        # cache makes it re-read the module this test just declared on.
        monkeypatch.setattr(champions, "_MODULE_CONTRACTS", {})

        result = _breakdown("Cho'Gath", ["Fimbulwinter"])
        marked = [
            event
            for event in result["damage_events"]
            if event.get("source_key") == "E" and event.get("cc_kind") == "slow"
        ]
        assert len(marked) == len(result["breakdown"]["E"]["damage_events"])
        assert result["timeline_coverage"]["coarse_sources"] == []
        assert result["timeline_coverage"]["complete"] is True
