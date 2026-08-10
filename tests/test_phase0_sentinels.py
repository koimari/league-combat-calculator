"""Phase 0 sentinels — deferred semantics pinned, with zero ``src/`` change.

A correction with no reachable fixture is a declaration wearing a
correction's clothes, so where Phase 0 declines to change behaviour it says
so in a test instead: the sentinel pins today's answer, names the decision
that deferred it, and goes red on the commit that changes the answer without
re-reading this file.  Each sentinel also pins the size of its own
population, because a sentinel that is green over an empty set proves
nothing (D-26).

Six sentinels, one class each:

* :class:`TestNoTwoCommandWindowsOverlap` — D-12, repeat-Command stacking.
* :class:`TestCommandExpiryBoundaryDiverges` — D-13, ``start < t <= end``.
* :class:`TestIsAttackOrSpellVersusFromAllSources` — D-04, the delivery gate.
* :class:`TestCommandMarksOnlyTheFirstPairDefender` — H2, ``CcScope``.
* :class:`TestAbyssalAuraHasNoRangeOrDeathCondition` — D-66, arm-time keys.
* :class:`TestSupportValueMixesUnits` — D-14/H3, the utility objective.
"""

import math
from functools import lru_cache
from typing import NamedTuple

import pytest

from src import app as app_module
from src.calculator import item_effects
from src.calculator.ability_spec import (
    AttackClass,
    DamageClass,
    is_immobilizing_event,
)
from src.calculator.champions import registered_champion_names
from src.calculator.damage import _in_cc_window, _merged_cc_windows
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_support_effects import cross_participant_authorities
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.survival.accumulate import accumulate_support_values
from src.calculator.survival.actions import SurvivalAction, attack_class_of
from src.calculator.survival.transitions import (
    _apply_cross_participant_modifiers,
    _apply_damage_modifier,
    _modifier_applies,
)

from tests.test_item_support_effects import (
    declared_classes_by_producer,
    declared_packet_keywords,
)

# Every producer whose declaration admits AttackClass.OTHER — the packets for
# which the walk's delivery gate is strictly narrower than what they say.
# Pinned, not counted at run time from the same expression the assertions
# use: five of the six producers, all but Blue Dream Bubble.
FROM_ALL_SOURCES_PRODUCERS = 5

# Registered champions that author an immobilizing ``cc_kind`` a Mandate
# holder's own fight can read: Ahri (Charm), Pantheon (Aegis Assault) and
# Syndra (Scatter the Weak).  This is the Command sentinels' population and
# umbrella criterion 15 requires it to be non-empty.
COMMAND_CC_AUTHORS = 3

# Champion modules that withhold a time-based answer and are swept through
# one rotation instead.  Pinned so the sweep cannot shrink in silence: a
# champion that starts withholding is a champion whose later immobilizes
# stop being swept.
TIME_BASED_WITHHOLDING_CHAMPIONS = 4

# The cross-participant producers whose packet carries a finite expiry, and
# whose closing instant the two engines therefore answer separately.  Five of
# the six: Abyssal Mask's Unmake is a persistent aura and has no closing
# instant to disagree about.
TIMED_CROSS_PARTICIPANT_PRODUCERS = 5

# The sentinel rosters' enemy count.  One authored immobilize could mark any
# of the three; the scan marks exactly one, and the aura curses all three.
SENTINEL_ROSTER_ENEMIES = 3
COMMAND_MARKED_ENEMIES = 1

# The support events one Mandate-plus-Locket holder contributes to a single
# ``support_value`` sum: two shields in hit points and one unitless amp.
UNIT_MIXED_SUPPORT_EVENTS = 3
UNIT_MIXED_SUPPORT_UNITS = 2

# The fields ``_apply_damage_modifier`` writes onto an armed modifier.
# Pinned because this sentinel's claim is about what is *absent*: there is no
# position, no radius and no holder-liveness key, so neither Unmake's range
# nor its holder's death can gate it (D-66).
ARMED_MODIFIER_FIELDS = frozenset(
    {
        "source",
        "until",
        "multiplier",
        "reduction",
        "damage_reduction",
        "next_event_only",
        "armor_reduction_percent",
        "mr_reduction_percent",
        "resistance_type",
        "owner",
        "damage_classes",
        "attack_classes",
    }
)

_SWEEP_TARGET = {
    "target_health": 10000,
    "target_armor": 0,
    "target_mr": 0,
    "level": 18,
}


class _CommandSweep(NamedTuple):
    """One pass of the registered-champion sweep, holding Imperial Mandate."""

    authors: dict[str, tuple[tuple[float, ...], tuple[tuple[float, float], ...]]]
    amped: dict[str, tuple[str, ...]]
    swept: tuple[str, ...]
    withheld: tuple[str, ...]
    duration: float


@lru_cache(maxsize=1)
def command_sweep() -> _CommandSweep:
    """Every registered champion's authored immobilizes, holding Mandate.

    The sweep is the whole registry, not a sample, because D-12's question —
    can two Command windows ever overlap? — is a question about the corpus
    of authored markers rather than about one champion.  Time-based is the
    maximal fight mode for that question (a longer window authors more
    immobilizes); the modules that withhold a time-based answer are swept
    through one rotation and counted, never skipped.
    """
    mandate = get_item_by_name("Imperial Mandate")
    effect = item_effects.command_amp_effect([mandate])
    assert effect is not None, "D-12: the sweep needs Command's sourced window"
    authors: dict[str, tuple] = {}
    amped: dict[str, tuple[str, ...]] = {}
    swept: list[str] = []
    withheld: list[str] = []
    for name in registered_champion_names():
        champion = get_champion(name)
        try:
            result = run_fight(
                champion,
                18,
                [mandate],
                FightParams.from_request(
                    {**_SWEEP_TARGET, "fight_mode": "time_based", "fight_duration": 10}
                ),
            )
        except ValueError:
            withheld.append(name)
            result = run_fight(
                champion,
                18,
                [mandate],
                FightParams.from_request(
                    {**_SWEEP_TARGET, "fight_mode": "one_rotation"}
                ),
            )
        swept.append(name)
        times = tuple(
            sorted(
                float(event.get("time", 0.0) or 0.0)
                for entry in result["breakdown"].values()
                if isinstance(entry, dict)
                for event in entry.get("damage_events") or ()
                if isinstance(event, dict) and is_immobilizing_event(event)
            )
        )
        if not times:
            continue
        authors[name] = (times, tuple(_merged_cc_windows(list(times), effect.duration)))
        amped[name] = tuple(
            key for key in result["breakdown"] if str(key).startswith("damage_amp_")
        )
    return _CommandSweep(authors, amped, tuple(swept), tuple(withheld), effect.duration)


@lru_cache(maxsize=8)
def sentinel_roster(items, enemies, item_options=()):
    """One roster response through the public request path.

    ``items``/``enemies``/``item_options`` are tuples so the response can be
    cached: three sentinels read the same two rosters and a roster costs a
    full coupled walk.
    """
    app_module.app.config["TESTING"] = True
    payload = {
        "champion": "Ahri",
        "level": 18,
        "items": list(items),
        "fight_mode": "time_based",
        "fight_duration": 8,
        "include_auto_attacks": False,
        "enemies": [{"champion": name, "level": 18, "items": []} for name in enemies],
        "allies": [
            {
                "champion": "Pantheon",
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            }
        ],
    }
    if item_options:
        payload["item_options"] = {
            item: dict(options) for item, options in item_options
        }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    return response.get_json()["combat"]


def _support_events(combat, source_prefix):
    """The holder's support events from one source, in emission order."""
    return [
        event
        for event in combat["support_events"]
        if event["attacker"] == "main" and event["source"].startswith(source_prefix)
    ]


def _armed(**overrides):
    """A cross-participant modifier as ``_apply_damage_modifier`` writes it."""
    modifier = {
        "source": "Imperial Mandate — Command",
        "until": 4.0,
        "multiplier": 1.07,
        "reduction": 0.0,
        "damage_reduction": False,
        "next_event_only": False,
        "armor_reduction_percent": 0.0,
        "mr_reduction_percent": 0.0,
        "resistance_type": "",
        "owner": "main",
        "damage_classes": frozenset(DamageClass),
        "attack_classes": frozenset(AttackClass),
    }
    modifier.update(overrides)
    return modifier


class _LedgerCtx:
    """The walk context these sentinels need: a ledger that records nothing.

    ``combatants`` is empty on purpose, so the source id resolves to ``""``
    and the owner skip cannot fire — these sentinels are about the window,
    not about who owns it.
    """

    class _Ledger:
        @staticmethod
        def write(action, **fields):  # pylint: disable=unused-argument
            """Record nothing."""

        @staticmethod
        def skip(action, reason):  # pylint: disable=unused-argument
            """Record nothing."""

    ledger = _Ledger()
    combatants = ()
    states: list = []


class TestNoTwoCommandWindowsOverlap:
    """Repeat-Command stacking has no reachable fixture today (D-12).

    ``_merged_cc_windows`` merges overlapping immobilizes by *extending* the
    window rather than stacking a second 7%, which is the Wiki's reading and
    the policy Phase 3 declares as ``merge=EXTEND``.  Whether that policy is
    a behaviour change depends on a fact about the corpus, not about the
    helper: does any registered champion author two immobilizes close enough
    together to merge?  Today none does — every authored marker across the
    whole registry opens its own window — so Phase 3's declaration is
    provably zero-diff.

    This sentinel is what turns red on the commit that authors the first
    overlapping pair, at which point ``merge=EXTEND`` stops being a
    formality and needs its own fixture and its own oracle.
    """

    def test_the_population_is_three_authors_and_is_not_empty(self):
        """D-26: the sentinel names how much it is green over."""
        sweep = command_sweep()
        assert sweep.authors, (
            "D-12: no registered champion authors an immobilize a Mandate "
            "holder can read, so every Command sentinel below is green over "
            "nothing.  The emission gate in damage._evaluate_cast_parts or "
            "the cc_kind markers themselves have regressed."
        )
        assert len(sweep.authors) == COMMAND_CC_AUTHORS, (
            "D-12: the Command population moved; it is now "
            f"{sorted(sweep.authors)}.  A new author is a new chance for two "
            "windows to overlap — re-read this sentinel before pinning it."
        )

    def test_the_sweep_covered_every_registered_champion(self):
        """A population is only a population if the sweep reached it."""
        sweep = command_sweep()
        assert sweep.swept == tuple(registered_champion_names())
        assert len(sweep.withheld) == TIME_BASED_WITHHOLDING_CHAMPIONS, (
            "D-12: the set of champions withholding a time-based answer "
            f"moved to {sorted(sweep.withheld)}.  Those are swept through one "
            "rotation instead, which authors fewer immobilizes, so a change "
            "here silently narrows this sentinel's population."
        )

    def test_every_author_actually_prices_the_amp(self):
        """Green over a population that reaches the code under discussion."""
        sweep = command_sweep()
        for name, rows in sweep.amped.items():
            assert "damage_amp_Imperial Mandate" in rows, (
                f"D-12: {name} authors an immobilize but its Mandate fight "
                "prices no Command row, so the sentinel's population is "
                "reachable in the marker stream and not in the amp."
            )

    def test_no_authored_pair_merges_into_one_window(self):
        """The corpus fact Phase 3's ``merge=EXTEND`` rides on."""
        sweep = command_sweep()
        for name, (times, windows) in sweep.authors.items():
            assert len(windows) == len(times), (
                f"D-12: {name} now authors two immobilizes within Command's "
                f"{sweep.duration}s window ({list(times)}), so repeat-Command "
                "stacking is reachable for the first time.  Phase 3's "
                "merge=EXTEND is no longer a zero-diff declaration: give it "
                "a fixture and an oracle receipt before landing it."
            )

    def test_the_check_is_live_and_not_vacuous(self):
        """R-05: the same predicate, over a pair that does overlap."""
        overlapping = _merged_cc_windows([0.0, 2.0], 4.0)
        assert len(overlapping) == 1
        assert overlapping == [(0.0, 6.0)]


class TestCommandExpiryBoundaryDiverges:
    """The two engines answer the closing instant differently (D-13).

    The pair engine's ``_in_cc_window`` is ``start < t <= end``: a packet
    landing at exactly the window's closing instant is amped.  The walk keeps
    a modifier only while ``until > action.time``, so the same packet at the
    same instant is not.  Both agree everywhere else, including at the
    opening instant, where the pair engine excludes the trigger and the walk
    arms the modifier after equal-time damage.

    Reachable only on exact float equality, which no committed scenario
    produces, so Phase 0 characterises the divergence rather than unifying
    it: unifying it would be an unfixtured change to both engines at once.
    Phase 3 declares the boundary ``OPEN_CLOSED`` for every dual-sided
    mechanic, and this sentinel is what that declaration has to satisfy.
    """

    def test_the_population_is_five_timed_producers_and_is_not_empty(self):
        """D-26: only a producer with a closing instant can disagree."""
        declared = declared_packet_keywords("persistent", "duration")
        timed = {
            source
            for source, fields in declared.items()
            if not fields["persistent"] and fields["duration"]
        }
        assert timed, "D-13: no cross-participant producer carries an expiry"
        assert len(timed) == TIMED_CROSS_PARTICIPANT_PRODUCERS, (
            "D-13: the timed-producer population moved to "
            f"{sorted(timed)}; the boundary divergence now covers a "
            "different set of mechanics than the one this sentinel pins."
        )
        assert timed < set(cross_participant_authorities())

    def test_the_pair_engine_amps_the_closing_instant(self):
        effect = item_effects.command_amp_effect([get_item_by_name("Imperial Mandate")])
        windows = _merged_cc_windows([0.0], effect.duration)
        assert not _in_cc_window(windows, 0.0), "the trigger itself is excluded"
        assert _in_cc_window(windows, effect.duration - 0.001)
        assert _in_cc_window(windows, effect.duration), (
            "D-13: the pair engine stopped amping the closing instant.  That "
            "is one half of a two-engine unification, not a local fix — land "
            "it with the walk's half in the same slice."
        )

    def test_the_walk_drops_the_modifier_at_the_same_instant(self):
        effect = item_effects.command_amp_effect([get_item_by_name("Imperial Mandate")])
        end = effect.duration
        inside = {"active_damage_modifiers": [_armed(until=end)]}
        closing = {"active_damage_modifiers": [_armed(until=end)]}
        packet = {"damage_type": "magic", "is_ability": True, "attacker": -1}
        amped = _apply_cross_participant_modifiers(
            _LedgerCtx(),
            SurvivalAction(time=end - 0.001, **packet),
            inside,
            100.0,
        )
        boundary = _apply_cross_participant_modifiers(
            _LedgerCtx(),
            SurvivalAction(time=end, **packet),
            closing,
            100.0,
        )
        assert amped == pytest.approx(107.0)
        assert boundary == pytest.approx(100.0), (
            "D-13: the walk now amps the closing instant, which is the pair "
            "engine's answer.  If that is the intended unification it is a "
            "correction with its own slice, allowlist and oracle receipt — "
            "not a side effect; delete this sentinel in that commit."
        )


class TestIsAttackOrSpellVersusFromAllSources:
    """C3 expresses "from all sources" as ``attack_classes``; the walk's gate
    still prices only attacks and spells (D-04).

    Abyssal Mask's Unmake, Bloodsong's Expose Weakness and Imperial
    Mandate's Command all read "from all sources" on the Wiki, and Carve and
    Vile Decay reduce a resistance without naming a delivery.  All five
    therefore declare every :class:`AttackClass`.  The walk's live gate is
    ``is_ability or basic_attack or source_key == "auto_attacks"``, which is
    Blue Dream Bubble's own restriction — "the next attack or spell they
    receive" — generalised to every modifier before any of them could say
    otherwise, so ``AttackClass.OTHER`` damage (item procs, burns, thorns
    returns) goes unpriced for those five.

    C3 declines to widen the gate: silently widening a gate inside a commit
    labelled "add a typed field" is a second correction riding the first,
    and no committed baseline scenario reaches the branch, so the widening
    would land unfixtured.  When a later slice widens it, this sentinel is
    what turns red.
    """

    def test_the_population_is_five_producers_and_is_not_empty(self):
        """D-26: the sentinel names how much it is green over."""
        admitting_other = {
            source
            for source, declared in declared_classes_by_producer().items()
            if AttackClass.OTHER in declared["attack_classes"]
        }
        assert len(admitting_other) == FROM_ALL_SOURCES_PRODUCERS, (
            "D-04: the sentinel's population moved; a producer changed which "
            "attack classes it declares, and the divergence this pins is "
            f"now over {sorted(admitting_other)}"
        )
        assert admitting_other < set(cross_participant_authorities())

    def test_other_class_damage_is_declared_but_not_priced(self):
        """The divergence itself, at the one predicate that decides it."""
        proc = SurvivalAction(damage_type="magic", source_key="item_burn")
        assert attack_class_of(proc) is AttackClass.OTHER
        unmake = {
            "source": "Abyssal Mask — Unmake",
            "owner": "main",
            "damage_classes": frozenset({DamageClass.MAGIC}),
            "attack_classes": frozenset(AttackClass),
        }
        assert AttackClass.OTHER in unmake["attack_classes"]
        assert not _modifier_applies(unmake, proc, "ally:Lulu"), (
            "D-04: the walk now prices AttackClass.OTHER damage for a "
            "from-all-sources modifier.  That is the correction this "
            "sentinel defers, not a free improvement: re-read Phase 0's "
            "is_attack_or_spell ruling, land it as its own slice with a "
            "declared qualifying population, and delete this sentinel."
        )

    def test_the_one_producer_whose_text_matches_the_gate_is_blue_dream_bubble(self):
        """The gate is not arbitrary — it is one producer's own restriction."""
        declared = declared_classes_by_producer()
        assert declared["Dream Maker — Blue Dream Bubble"]["attack_classes"] == (
            frozenset({AttackClass.BASIC_ATTACK, AttackClass.ABILITY})
        ), "D-04: Blue Dream Bubble is the reading the walk's gate encodes"


class TestCommandMarksOnlyTheFirstPairDefender:
    """One authored immobilize marks one enemy, chosen by roster position (H2).

    The item scan reads the *first* pair's damage events and stamps every one
    of them with that pair's defender id, so the Command packet's target is a
    construction accident of running the rotation once per defender rather
    than a reading of how many enemies the ability actually immobilised.
    Reordering the roster moves the mark, which is the proof that no
    targeting rule is involved.

    H2 is the human-owned decision that answers it — how many roster targets
    does one cone stun, and on what source — and the umbrella's recorded
    ruling until then is *deferred, default shipped*: ``CcScope.Unreviewed``
    resolves to a single target.  This sentinel pins the default so the day
    ``CcScope`` takes a sourced value is a day this file is re-read.
    """

    def test_the_population_is_three_enemies_and_one_is_marked(self):
        """D-26: three enemies could be marked; exactly one is."""
        combat = sentinel_roster(("Imperial Mandate",), ("Aatrox", "Malphite", "Garen"))
        enemies = [
            row["participant_id"]
            for row in combat["breakdown"]
            if row["participant_id"].startswith("enemy:")
        ]
        assert len(enemies) == SENTINEL_ROSTER_ENEMIES
        marked = _support_events(combat, "Imperial Mandate — Command")
        assert len(marked) == COMMAND_MARKED_ENEMIES, (
            "H2: one authored immobilize now marks "
            f"{len(marked)} of {len(enemies)} enemies.  That is CcScope "
            "taking a value, which is H2's to rule and Phase 4's to land — "
            "not a change this sentinel may absorb."
        )
        assert marked[0]["target"] == enemies[0]

    def test_reordering_the_roster_moves_the_mark(self):
        """Positional, not targeted — the fact H2 has to replace."""
        forward = sentinel_roster(
            ("Imperial Mandate",), ("Aatrox", "Malphite", "Garen")
        )
        reversed_ = sentinel_roster(
            ("Imperial Mandate",), ("Garen", "Malphite", "Aatrox")
        )
        assert _support_events(forward, "Imperial Mandate")[0]["target"] == (
            "enemy:Aatrox"
        )
        assert _support_events(reversed_, "Imperial Mandate")[0]["target"] == (
            "enemy:Garen"
        ), (
            "H2: the Command mark no longer follows roster order, so the "
            "first-defender scan has been replaced.  Read the umbrella's H2 "
            "row before pinning whatever replaced it."
        )


class TestAbyssalAuraHasNoRangeOrDeathCondition:
    """Unmake declares a radius it never checks and outlives its holder (D-66).

    The packet carries ``range_assumption="within_700_units"`` — an honest
    declaration that positioning is assumed rather than modelled — and arms
    ``persistent``, so the armed modifier's expiry is ``inf``.  Nothing the
    walk holds can retract it: the armed record carries no position, no
    radius and no holder-liveness field, so a dead holder's curse still
    prices the enemy's incoming magic damage for the rest of the window.

    Phase 0 does not fix this.  Both conditions are arm-time preconditions on
    an idempotent aura, and D-66 is where an aura's arm key and its arming
    conditions are ruled — with a `HolderStacking` field Phase 4 introduces
    and Phase 0 cannot write against.  Pricing a curse whose precondition
    never ran is the campaign's own invariant, so it is pinned here rather
    than left as a comment.
    """

    def test_the_population_is_every_enemy_and_is_not_empty(self):
        """D-26: the aura curses the whole enemy team, unconditionally."""
        combat = sentinel_roster(
            ("Imperial Mandate", "Abyssal Mask"), ("Aatrox", "Malphite", "Garen")
        )
        cursed = _support_events(combat, "Abyssal Mask — Unmake")
        assert len(cursed) == SENTINEL_ROSTER_ENEMIES, (
            "D-66: Unmake now curses "
            f"{len(cursed)} of {SENTINEL_ROSTER_ENEMIES} enemies, so some "
            "precondition has started running.  If that is a range or "
            "liveness gate it is a correction with its own slice."
        )
        assert all(event["persistent"] for event in cursed)
        assert all("expires_at" not in event for event in cursed)

    def test_the_declared_range_is_an_assumption_and_not_a_check(self):
        combat = sentinel_roster(
            ("Imperial Mandate", "Abyssal Mask"), ("Aatrox", "Malphite", "Garen")
        )
        cursed = _support_events(combat, "Abyssal Mask — Unmake")
        assert {event["range_assumption"] for event in cursed} == {
            "within_700_units"
        }, "D-66: the assumption is declared on the packet, in every roster"

    def test_the_armed_curse_carries_no_range_and_no_liveness_field(self):
        """The absence is the claim, so the field set is pinned."""
        armed: list[dict] = []
        state = {"active_damage_modifiers": armed}
        _apply_damage_modifier(
            _LedgerCtx(),
            SurvivalAction(
                source="Abyssal Mask — Unmake",
                owner="main",
                persistent=True,
                multiplier=1.12,
                amount=0.12,
                damage_classes=frozenset({DamageClass.MAGIC}),
                attack_classes=frozenset(AttackClass),
            ),
            state,
        )
        assert set(armed[0]) == ARMED_MODIFIER_FIELDS, (
            "D-66: the armed modifier's field set moved.  If a range or "
            "holder-liveness key joined it, the aura has gained a "
            "precondition and this sentinel is the correction's fixture."
        )
        assert armed[0]["until"] == math.inf

    def test_a_persistent_curse_survives_any_later_instant(self):
        """No expiry means no death condition either — nothing retracts it."""
        state = {
            "active_damage_modifiers": [
                _armed(
                    source="Abyssal Mask — Unmake",
                    until=math.inf,
                    multiplier=1.12,
                    damage_classes=frozenset({DamageClass.MAGIC}),
                )
            ]
        }
        late = _apply_cross_participant_modifiers(
            _LedgerCtx(),
            SurvivalAction(damage_type="magic", is_ability=True, time=1e6, attacker=-1),
            state,
            100.0,
        )
        assert late == pytest.approx(112.0), (
            "D-66: something now expires a persistent aura.  Read this "
            "sentinel's docstring: the range and death conditions are "
            "deferred, and expiring the aura is neither of them."
        )


class TestSupportValueMixesUnits:
    """One ``support_value`` sum adds hit points to a unitless amp (D-14, H3).

    ``support_value`` is the sum of every non-damage support event's applied
    amount, with no unit axis anywhere in the accumulator: a Locket shield
    contributes 360 hit points and Imperial Mandate's Command contributes
    0.07, the amp *fraction*, to the same total.  A Mandate holder is
    therefore worth about a thousandth of a shield in the utility objective.

    H3 is the human-owned decision — does amplification count as support
    value at all, and in what unit — and D-14 rules that Phase 0 pins the
    behaviour by characterisation and excludes it from every coverage
    expectation, because it is a product decision about the objective and
    not a defect with an oracle.
    """

    def _roster(self):
        return sentinel_roster(
            ("Imperial Mandate", "Locket of the Iron Solari"),
            ("Aatrox",),
            (("Locket of the Iron Solari", (("active_seconds", 1.0),)),),
        )

    def test_the_population_is_three_events_over_two_units(self):
        """D-26: the sum is green over a real mixture, not one event."""
        events = [
            event
            for event in self._roster()["support_events"]
            if event["attacker"] == "main"
        ]
        assert len(events) == UNIT_MIXED_SUPPORT_EVENTS, (
            "D-14: the holder's support-event population moved to "
            f"{[event['source'] for event in events]}; this sentinel pins a "
            "sum that mixes units and needs both units present."
        )
        assert len({event["kind"] for event in events}) == UNIT_MIXED_SUPPORT_UNITS
        assert {event["kind"] for event in events} == {"shield", "damage_modifier"}

    def test_one_sum_holds_hit_points_and_a_unitless_fraction(self):
        combat = self._roster()
        events = [
            event for event in combat["support_events"] if event["attacker"] == "main"
        ]
        amounts = [event["applied_amount"] for event in events]
        shields = [
            event["applied_amount"] for event in events if event["kind"] == "shield"
        ]
        amps = [
            event["applied_amount"]
            for event in events
            if event["kind"] == "damage_modifier"
        ]
        assert shields == [360.0, 360.0]
        assert amps == [0.07]
        holder = next(
            row for row in combat["breakdown"] if row["participant_id"] == "main"
        )
        assert holder["support_value"] == pytest.approx(round(sum(amounts), 1)), (
            "D-14: support_value stopped being the raw sum of applied "
            "amounts.  Weighting or converting the amp is H3's answer, not a "
            "refactor's — record the ruling in the umbrella first."
        )
        assert holder["support_value"] == pytest.approx(720.1)

    def test_the_accumulator_has_no_unit_axis(self):
        """The mixing is structural: one array, one ``+=``, no unit tag."""
        entries = [
            ("ally:Pantheon", 0, 0, False),
            ("enemy:Aatrox", 0, 1, False),
        ]
        support_value, healing_output = accumulate_support_values(
            [360.0, 0.07], entries, (), (), 1
        )
        assert support_value == [pytest.approx(360.07)], (
            "D-14: the support accumulator gained a unit axis.  That is H3 "
            "being answered, and it belongs in the umbrella's H3 row with "
            "the objective's own re-derivation, not here."
        )
        assert healing_output == [0.0]
