"""The holder, the fixture and the registry every kernel-equivalence suite is built from."""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

from src.calculator.champion_loadout import ChampionLoadout
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.fight_params import FightParams
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.stats import calculate_total_stats


def _timeline(
    champion_name,
    level,
    items,
    params,
    enemies,
    allies=(),
    *,
    role="mid",
    **kwargs,
):
    champion = get_champion(champion_name)
    stats = calculate_total_stats(champion, level, items, role=role)
    # The production seam wires item_options into the starting defenses
    # (calculate.py:_combat_receipt); the parity harness must do the same
    # or an explicit active input (Zhonya Time Stop) would be priced by
    # neither walk and the comparison would be trivially equal (P3-3F).
    defenses = resolve_starting_defenses(
        champion_name,
        level,
        stats,
        items,
        item_options=params.item_options,
    )
    return build_participant_timeline(
        champion,
        level,
        items,
        params,
        main_stats=stats,
        main_defenses=defenses,
        enemies=list(enemies),
        allies=list(allies),
        **kwargs,
    )


def _walk_both(champion_name, items, params, enemies, allies, *, level, role):
    """The same fight down both walks: ``(receipt, score, search_context)``.

    Both runs take the scoring subset (``include_receipt=False``) — the
    receipt walk's is the authority the score adapter must reproduce — and
    the context records which path the score adapter actually took."""
    legacy = _timeline(
        champion_name,
        level,
        items,
        params,
        enemies,
        allies,
        role=role,
        include_receipt=False,
    )
    context = CoupledSearchContext()
    fast = _timeline(
        champion_name,
        level,
        items,
        params,
        enemies,
        allies,
        role=role,
        include_receipt=False,
        pair_result_cache={},
        search_context=context,
    )
    return legacy, fast, context


def _assert_rung(name, context, *, compiled, invariant):
    """The score adapter took the documented rung — compiled, fallback or
    poisoned.

    Its own function because the rung is a property of every scenario,
    including one whose two walks are pinned as *disagreeing*: a divergence
    that moved to a different rung is a different divergence."""
    assert (
        context.uncompilable is invariant
    ), f"{name}: expected invariant={invariant}, got {context.uncompilable}"
    if invariant:
        # The failure poisoned the context: no panel may be reused later.
        assert not context.panels, f"{name}: expected no panels after poisoning"
    elif compiled:
        assert context.panels, f"{name}: expected the compiled path to be used"
    else:
        # Candidate-local fallback: the panel may exist (it is built before
        # the fresh compile raises); the context must not be poisoned.
        assert not context.uncompilable


def _assert_contract(
    name,
    champion_name,
    items,
    params,
    enemies,
    allies=(),
    *,
    level=18,
    role="mid",
    compiled=True,
    invariant=False,
    _kv_total_delta=False,
):
    """The score path must deep-equal the receipt path on the whole scoring
    receipt, and must have taken the documented path."""
    legacy, fast, context = _walk_both(
        champion_name, items, params, enemies, allies, level=level, role=role
    )
    if _kv_total_delta:
        # P3 package 3S: the compiled total_damage is the applied-based
        # sum; the legacy total is the outgoing event ledger sum (CC-
        # blocked packets included at full event values).  The CC-blocked
        # attacker's total is the named delta; everything else stays
        # byte-equal.
        for fast_row, legacy_row in zip(
            fast["breakdown"], legacy["breakdown"], strict=False
        ):
            assert fast_row["participant_id"] == legacy_row["participant_id"], name
            assert fast_row["health_damage"] == legacy_row["health_damage"], name
            assert fast_row["healing_received"] == legacy_row["healing_received"], name
            assert fast_row["death_time"] == legacy_row["death_time"], name
            assert fast_row["survived_window"] == legacy_row["survived_window"], name
        assert fast["participants"] == legacy["participants"], name
        assert fast["duration"] == legacy["duration"], name
    else:
        assert fast == legacy, f"{name}: score path diverged from the receipt walk"
    _assert_rung(name, context, compiled=compiled, invariant=invariant)


@cache
def _item(name):
    """One cached item record by name.

    Deliberately *not* a fixed vocabulary: the suite's required item set is
    derived from the registries below, so a scenario reaching a new item may
    not have to extend a hand list to name it (slice 0A.9)."""
    return get_item_by_name(name)


def _roster(champion, level=18, items=(), role="mid", quest=False, ally_effects=False):
    """One roster participant's resolved loadout.

    ``ally_effects`` is load-bearing, not cosmetic: ``derive_item_support_effects``
    early-returns ``[]`` for a participant on the ally team whose request does
    not enable them, so an ally fixture that leaves this False equips its items
    and fires nothing at all.  Every ally-holder fixture below sets it, and it
    is the sole reason any ally-side packet exists to be counted."""
    return ChampionLoadout(
        champion=champion,
        level=level,
        role=role,
        items=items,
        role_quest_complete=quest,
        ally_effects_enabled=ally_effects,
    ).resolve()


@dataclass(frozen=True, slots=True)
class Holder:
    """One roster participant and the items it carries into the fight.

    Two of these fields change the loadout rather than describing it, so both
    are stated here rather than left to be discovered:

    * a holder carrying items has completed its role quest (``quest`` is
      ``bool(items)`` in :meth:`resolve`), because half the required set is
      support-quest gear and an unfinished quest would change what the fixture
      equips rather than what it reaches;
    * ``ally_effects`` enables the ally-side packet path — see :func:`_roster`
      — and without it an ally holder equips its build and fires nothing."""

    champion: str
    items: tuple[str, ...] = ()
    role: str = "mid"
    level: int = 18
    ally_effects: bool = False

    def resolve(self):
        """The loadout the timeline builder consumes."""
        return _roster(
            self.champion,
            level=self.level,
            items=self.items,
            role=self.role,
            quest=bool(self.items),
            ally_effects=self.ally_effects,
        )


@dataclass(frozen=True, slots=True)
class KernelFixture:
    """One compiled-vs-receipt scenario, and what it puts on the board.

    ``pinned_divergence`` is a *characterization*: a named, reproduced
    disagreement between the two walks that Phase 0A may not fix, because 0A
    moves no number in ``src/``.  A pinned fixture asserts the walks still
    disagree, so the commit that fixes the mechanic turns this suite red and
    its author has to read the reason rather than inherit it.
    """

    name: str
    champion: str
    items: tuple[str, ...]
    enemies: tuple[Holder, ...]
    allies: tuple[Holder, ...] = ()
    role: str = "mid"
    level: int = 18
    duration: float = 8.0
    compiled: bool = True
    invariant: bool = False
    pinned_divergence: str = ""

    def params(self):
        """This fixture's deterministic time-based request."""
        return FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": self.duration,
                "role": self.role,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            },
            deterministic=True,
        )

    def walk_both(self):
        """``(receipt, score, search_context)`` for this fixture."""
        return _walk_both(
            self.champion,
            [_item(name) for name in self.items],
            self.params(),
            [holder.resolve() for holder in self.enemies],
            [holder.resolve() for holder in self.allies],
            level=self.level,
            role=self.role,
        )

    def receipt(self):
        """The annotating receipt — the only mode carrying the support rows."""
        return _timeline(
            self.champion,
            self.level,
            [_item(name) for name in self.items],
            self.params(),
            [holder.resolve() for holder in self.enemies],
            [holder.resolve() for holder in self.allies],
            role=self.role,
            include_receipt=True,
        )


# Four candidate-holder fixtures and their four ally-holder rung variants.
# The candidate builds ride the compiled or the candidate-local fallback rung.
# An ally build poisons the search context when its holder carries a
# ``damage_modifier`` producer, which three of the four do — that is the rung
# difference these variants exist to pin.  ``takedown_ally`` is the stated
# exception: Cryptbloom is an event-view holder and not a producer, so its
# ally roster stays compilable and what it pins is a dropped packet on an
# un-poisoned context rather than a poisoning.
_CC_TRIGGER_BUILD = (
    "Imperial Mandate",
    "Bandlepipes",
    "Solstice Sleigh",
    "Fimbulwinter",
)


_EVENT_SCAN_BUILD = (
    "Black Cleaver",
    "Bloodletter's Curse",
    "Bloodsong",
    "Phage",
    "Abyssal Mask",
)


_ENCHANTER_BUILD = ("Dream Maker", "Echoes of Helia")


_TAKEDOWN_BUILD = ("Cryptbloom",)


# A level-1 enemy is what makes the takedown fixtures reach a takedown at
# all: Cryptbloom's Life From Death fires on a kill, and a level-18 enemy
# survives the window.
_LIVE_ENEMY = (Holder("Aatrox", role="top"),)


_DOOMED_ENEMY = (Holder("Aatrox", role="top", level=1),)


REGISTRY_FIXTURES = (
    KernelFixture(
        name="cc_trigger_candidate",
        champion="Ahri",
        items=_CC_TRIGGER_BUILD,
        enemies=_LIVE_ENEMY,
        allies=(Holder("Pantheon", role="support"),),
        compiled=False,
    ),
    KernelFixture(
        name="event_scan_candidate",
        champion="Ahri",
        items=_EVENT_SCAN_BUILD,
        enemies=_LIVE_ENEMY,
        allies=(Holder("Pantheon", role="support"),),
    ),
    KernelFixture(
        name="enchanter_trigger_candidate",
        champion="Lulu",
        items=_ENCHANTER_BUILD,
        enemies=_LIVE_ENEMY,
        allies=(Holder("Jax", role="top"),),
        role="support",
    ),
    KernelFixture(
        name="takedown_candidate",
        champion="Ahri",
        items=_TAKEDOWN_BUILD,
        enemies=_DOOMED_ENEMY,
        allies=(Holder("Pantheon", role="support"),),
        duration=20.0,
    ),
    KernelFixture(
        name="cc_trigger_ally",
        champion="Ahri",
        items=(),
        enemies=_LIVE_ENEMY,
        allies=(
            Holder(
                "Pantheon",
                items=_CC_TRIGGER_BUILD,
                role="support",
                ally_effects=True,
            ),
        ),
        compiled=False,
        invariant=True,
    ),
    KernelFixture(
        name="event_scan_ally",
        champion="Ahri",
        items=(),
        enemies=_LIVE_ENEMY,
        allies=(
            Holder(
                "Pantheon",
                items=_EVENT_SCAN_BUILD,
                role="support",
                ally_effects=True,
            ),
        ),
        compiled=False,
        invariant=True,
    ),
    KernelFixture(
        name="enchanter_trigger_ally",
        champion="Ahri",
        items=(),
        enemies=_LIVE_ENEMY,
        allies=(
            Holder("Lulu", items=_ENCHANTER_BUILD, role="support", ally_effects=True),
        ),
        compiled=False,
        invariant=True,
    ),
    KernelFixture(
        name="takedown_ally",
        champion="Ahri",
        items=(),
        enemies=_DOOMED_ENEMY,
        allies=(
            Holder(
                "Pantheon",
                items=_TAKEDOWN_BUILD,
                role="support",
                ally_effects=True,
            ),
        ),
        duration=20.0,
        pinned_divergence=(
            "a roster ally's takedown-triggered support packets never reach "
            "the compiled score path: the receipt composition passes "
            "target_id=defender.participant_id into _support_effect_templates "
            "while the base and signature panels pass no target_id at all, so "
            "the takedown synthesis that reads it never fires and Cryptbloom's "
            "Life From Death authors zero packets"
        ),
    ),
)


def _differing_leaves(left: Any, right: Any, path: str = "") -> tuple[str, ...]:
    """Every leaf path at which two scoring receipts disagree."""
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return tuple(
            leaf
            for key in sorted(set(left) | set(right))
            for leaf in _differing_leaves(
                left.get(key), right.get(key), f"{path}.{key}"
            )
        )
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return (f"{path}[]",)
        return tuple(
            leaf
            for index, (one, other) in enumerate(zip(left, right, strict=False))
            for leaf in _differing_leaves(one, other, f"{path}[{index}]")
        )
    return () if left == right else (path,)


def _ally_survival(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """The one roster ally's survival row of a scoring receipt."""
    allies = [
        participant
        for participant in result["participants"]
        if participant["team"] == "ally"
    ]
    assert len(allies) == 1, "the pinned fixture carries exactly one roster ally"
    return allies[0]["survival"]
