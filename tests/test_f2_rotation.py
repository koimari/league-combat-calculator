"""F2 optimal event-order engine — rotation resolver and cooldown cadence.

Covers the combo layer (src/calculator/rotation_resolver.py) end to end:

1. Per-combo-champion parse-level assertions: ``run_fight`` derives the
   documented cast order for each champion in the batch, and the
   ``/api/calculate``-shaped ``rotation`` receipt carries the order plus
   a rationale that names the setup/consume relationship.
2. The DPS-scoring helper ranks the parsed abilities against their
   per-rank cooldowns (the data-driven signal behind the table).
3. Time-based fights prove the derived order respects cooldowns:
   Cassiopeia recasts Q at its cooldown intervals with Twin Fang spam
   between reapplications (and strictly more E casts than the fixed
   default order in a short window); Varus' Blight detonation rides the
   Q cast that follows the auto-applied stacks.
"""

import re
from collections.abc import Iterable
from pathlib import Path

import pytest

from src.calculator.cast_dependency import CustomOrderViolatesDependencyError
from src.calculator.champions import registered_champion_names
from src.calculator.damage import DEFAULT_CAST_ORDER
from src.calculator.data_fetcher import fetch_champion_data
from src.calculator.pipeline import ONE_ROTATION_DURATION, FightParams, run_fight
from src.calculator.rotation_resolver import (
    CAST_ORDER_OVERRIDES,
    ORDER_OVERRIDE_REASONS,
    ComboRule,
    _validate_override_reasons,
    build_rotation_receipt,
    rank_ability_dps,
    resolve_cast_order,
)

_OVERRIDE_CHAMPIONS = [
    "Cassiopeia",
    "Varus",
    "Brand",
    "Vladimir",
    "Annie",
    "Lux",
    "Zed",
]

_EXPECTED_ORDERS = {
    "Cassiopeia": ["Q", "E", "W", "R"],
    "Varus": ["Q", "E", "R", "W"],
    "Brand": ["Q", "R", "E", "W"],
    "Vladimir": ["R", "Q", "E", "W"],
    "Annie": ["E", "R", "Q", "W"],
    "Lux": ["E", "Q", "R", "W"],
    "Zed": ["W", "E", "Q", "R"],
}

_RATIONALE_FRAGMENTS = {
    "Cassiopeia": ("poison", "E-spam"),
    "Varus": ("Blight", "detonat"),
    "Brand": ("Blaze", "spread"),
    "Vladimir": ("amplif", "mark"),
    "Annie": ("stun", "Tibbers", "shield"),
    "Lux": ("slow", "root"),
    "Zed": ("shadow", "Death Mark"),
}


# The engine's ``DEFAULT_CAST_ORDER`` still names ``Q2`` positionally, which
# is the resolver's own fallback and not something a caller may request: a
# requested order may name only slots the champion's parse offers, and
# neither Cassiopeia nor Zed has a recast row (D-11).  The Q2 element was
# always inert for them, so dropping it is what "the fixed order" meant here.
FIXED_ORDER = [slot for slot in DEFAULT_CAST_ORDER if slot != "Q2"]


@pytest.fixture(scope="module")
def champion_by_name():
    champions = fetch_champion_data()
    return {data.get("name"): data for data in champions.values()}


def _params(one_rotation=True, duration=None, uptime=0.0, cast_order=None):
    return FightParams(
        target_health=2000.0,
        target_bonus_health=0.0,
        target_armor=50.0,
        target_magic_resistance=40.0,
        fight_duration_seconds=(
            duration if duration is not None else ONE_ROTATION_DURATION
        ),
        auto_attack_uptime=uptime,
        one_rotation=one_rotation,
        include_actives=True,
        cast_order=cast_order,
        auto_attacks_only=False,
        ability_ranks=None,
        champion_options=None,
        deterministic=True,
    )


def _parse_for(champion_data, *, level=18, splinters=None):
    """One champion's parse, optionally at a splinter count, for receipts."""
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.stats import calculate_total_stats

    stats = calculate_total_stats(dict(champion_data), level, [])
    return parse_champion_abilities(
        dict(champion_data),
        level,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
        champion_options=None if splinters is None else {"splinters": splinters},
    )


def _run(champion_data, level=11, one_rotation=True, duration=None, uptime=0.0):
    return run_fight(
        champion_data,
        level,
        [],
        _params(one_rotation=one_rotation, duration=duration, uptime=uptime),
    )


# ---------------------------------------------------------------------------
# Combo table shape
# ---------------------------------------------------------------------------

_RESOLVER_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "calculator" / "rotation_resolver.py"
)
_OVERRIDES_LITERAL_OPEN = "CAST_ORDER_OVERRIDES: dict[str, ComboRule] = {"
_ENTRY_LINE = re.compile(r'^ {4}"([^"]+)": ComboRule\($')


def resolver_source() -> str:
    """The resolver module as text, for the source-shape assertions below."""
    return _RESOLVER_PATH.read_text(encoding="utf-8")


def seed_comment_blocks(source: str) -> tuple[tuple[str | None, tuple[str, ...]], ...]:
    """Every comment block inside the ``CAST_ORDER_OVERRIDES`` literal.

    Each pair is ``(the entry the block introduces, the block's lines)``.
    A ``None`` champion is a block that introduces nothing — the shape a
    retirement leaves behind when it takes the ``ComboRule`` and not the
    paragraph above it.  Only column-4 comment lines are blocks; the
    trailing notes inside an entry body sit deeper and are that entry's.
    """
    body = source.split(_OVERRIDES_LITERAL_OPEN, 1)[1].split("\n}\n", 1)[0]
    blocks: list[tuple[str | None, tuple[str, ...]]] = []
    block: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and len(line) - len(line.lstrip()) == 4:
            block.append(stripped.lstrip("#").strip())
            continue
        entry = _ENTRY_LINE.match(line)
        if entry:
            blocks.append((entry.group(1), tuple(block)))
            block = []
    if block:
        blocks.append((None, tuple(block)))
    return tuple(blocks)


def seed_comment_faults(source: str, roster: Iterable[str]) -> tuple[str, ...]:
    """Every seed comment that describes something other than its entry.

    The empty tuple is the pass condition.  A block must introduce an
    entry, name that entry's champion, and name no other champion in the
    cached roster — which is what makes a retirement that leaves its
    paragraph behind a failure instead of a reading hazard.
    """
    names = tuple(roster)
    faults: list[str] = []
    for champion, block in seed_comment_blocks(source):
        text = " ".join(block)
        if champion is None:
            faults.append(f"a comment block introduces no entry: {text[:60]!r}")
            continue
        if not block:
            faults.append(f"{champion} carries no comment block")
            continue
        named = [name for name in names if re.search(rf"\b{re.escape(name)}\b", text)]
        if champion not in named:
            faults.append(f"{champion}'s comment never names {champion}")
        faults.extend(
            f"{champion}'s comment describes {other}"
            for other in named
            if other != champion
        )
    return tuple(faults)


class TestCastOrderOverrides:
    def test_the_table_holds_exactly_the_hand_seeds(self) -> None:
        assert set(CAST_ORDER_OVERRIDES) == set(_OVERRIDE_CHAMPIONS)

    def test_every_override_says_why_it_is_still_hand_held(self) -> None:
        """P5-f: the retirement frontier is counted, not claimed.

        A seed that cannot name its reason from the closed set is either a
        mechanic its module should declare or a preference nobody wrote
        down — and it would sit in the table forever either way.
        """
        for name, rule in CAST_ORDER_OVERRIDES.items():
            assert (
                rule.override_reason in ORDER_OVERRIDE_REASONS
            ), f"{name} declares override_reason {rule.override_reason!r}"

    def test_the_suite_agrees_with_the_published_frontier(self) -> None:
        """Criterion 13: the frontier is counted, and the counts agree.

        ``docs/cast-dependency-audit.json`` publishes which seeds survive
        and why.  A suite that listed a different set would let the
        frontier be driven down in the receipt while the tests kept
        passing against a set nobody had retired.
        """
        import json
        from pathlib import Path

        receipt = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "docs"
                / "cast-dependency-audit.json"
            ).read_text(encoding="utf-8")
        )
        from collections import Counter

        from src.calculator.champions import get_champion_cast_dependencies

        frontier = receipt["order_override_frontier"]
        assert sorted(_OVERRIDE_CHAMPIONS) == frontier["champions"]
        assert frontier["entries"] == len(_OVERRIDE_CHAMPIONS)
        # The WHOLE histogram, not one key of it: after the retirements
        # every survivor carries `dps_tiebreak` and three of the four
        # closed reasons have no user, so gating `pending_primitive`
        # alone left the other three unwatched in both directions.
        measured = Counter(
            rule.override_reason for rule in CAST_ORDER_OVERRIDES.values()
        )
        assert frontier["reasons"] == {
            reason: measured.get(reason, 0) for reason in ORDER_OVERRIDE_REASONS
        }
        assert frontier["unclassified"] == []
        # D-89's head-only seeds: a declaration decides the head, the seed
        # still decides the tail.  Nothing else in the frontier can tell
        # them from a seed held by hand end to end.
        assert frontier["head_only"] == sorted(
            name
            for name in CAST_ORDER_OVERRIDES
            if get_champion_cast_dependencies(name)
        )

    def test_the_design_doc_names_the_surviving_seeds_and_no_others(self) -> None:
        """The prose list is gated like the table it describes.

        ``docs/rotation-design.md``'s seed section named ten champions for
        a seven-entry table after three retirements moved the code and left
        the sentence alone, and nothing saw it.  This is what sees it: every live seed is named
        in that section and every retired one is absent from it.
        """
        from pathlib import Path

        design = (
            Path(__file__).resolve().parents[1] / "docs" / "rotation-design.md"
        ).read_text(encoding="utf-8")
        heading = "### The hand seeds remain documented overrides"
        section = design.split(heading, 1)[1].split("\n### ", 1)[0]
        named = section.split("\n\nFour names left the table", 1)[0]
        for champion in CAST_ORDER_OVERRIDES:
            assert champion in named, f"{champion} seeds but the doc omits it"
        for retired in ("Syndra", "Aatrox", "Jhin", "Aphelios"):
            assert (
                retired not in named
            ), f"{retired} retired but the doc still lists it as a seed"

    def test_every_seed_comment_describes_the_seed_it_introduces(self) -> None:
        """The table's own prose is gated like the table.

        The four retirements deleted their ``ComboRule`` entries and left
        their comment paragraphs behind: Aatrox's and Jhin's ended up
        directly above Annie's surviving entry, where two paragraphs about
        two retired champions read as documentation of hers, and
        Aphelios' dangled against the closing brace describing nothing.
        No commit body mentioned them and nothing could see them — the
        campaign's own prose-outruns-code shape, inside the table the
        campaign counts.  This is what sees them.
        """
        assert seed_comment_faults(resolver_source(), registered_champion_names()) == ()

    def test_the_comment_gate_sees_a_retirement_that_left_its_paragraph(self) -> None:
        """R-05: the exact drift the retirements caused, made to happen."""
        orphaned = resolver_source().replace(
            '    "Annie": ComboRule(',
            "    # Aatrox — R grants bonus AD as a percentage of total AD\n"
            "    # before Q/W are priced.\n"
            '    "Annie": ComboRule(',
        )
        faults = seed_comment_faults(orphaned, registered_champion_names())
        assert any("describes Aatrox" in fault for fault in faults), faults

    def test_the_comment_gate_sees_a_block_that_introduces_nothing(self) -> None:
        """R-05: the dangling half of the same drift."""
        closing = (
            '        aoe={"E": 5},  # Shadow Slash around Zed and the shadow\n    ),\n}'
        )
        dangling = resolver_source().replace(
            closing,
            closing[:-1] + "    # Aphelios — the main-hand weapon's Q form opens.\n}",
        )
        faults = seed_comment_faults(dangling, registered_champion_names())
        assert any("introduces no entry" in fault for fault in faults), faults

    def test_the_comment_gate_sees_an_entry_nobody_introduced(self) -> None:
        """R-05: the third shape — an entry whose block went away instead."""
        unintroduced = resolver_source().replace(
            "    # Lux — E slows so the root lands; Q roots; R consumes the\n"
            "    # Illumination mark.\n",
            "",
        )
        faults = seed_comment_faults(unintroduced, registered_champion_names())
        assert faults == ("Lux carries no comment block",)

    def test_a_derived_rule_carries_no_override_reason(self) -> None:
        assert (
            ComboRule(champion="X", order=("Q",), rationale="").override_reason is None
        )

    def test_an_unreasoned_override_fails_at_import(self) -> None:
        """The check is reachable: it fires on a table with a bad entry."""
        original = dict(CAST_ORDER_OVERRIDES)
        CAST_ORDER_OVERRIDES["Synthetic"] = ComboRule(
            champion="Synthetic", order=("Q",), rationale="", override_reason="vibes"
        )
        try:
            with pytest.raises(ValueError, match="override_reason"):
                _validate_override_reasons()
        finally:
            CAST_ORDER_OVERRIDES.clear()
            CAST_ORDER_OVERRIDES.update(original)

    def test_every_rule_has_order_rationale_and_sources(self) -> None:
        for name, rule in CAST_ORDER_OVERRIDES.items():
            assert rule.champion == name
            assert rule.order, f"{name} combo has an empty order"
            assert rule.rationale, f"{name} combo has no rationale"
            assert rule.sources, f"{name} combo has no sourced atoms"
            assert len(set(rule.order)) == len(
                rule.order
            ), f"{name} combo order repeats a slot"
            for slot in rule.order:
                assert slot in {
                    "Q",
                    "Q2",  # a recast slot rides its parent's schedule
                    "W",
                    "E",
                    "R",
                    "P",
                }, f"{name} combo references unknown slot {slot}"

    def test_resolve_cast_order_uses_table_then_default(self) -> None:
        order, rule = resolve_cast_order("Cassiopeia", {})
        assert order == ["Q", "E", "W", "R"]
        assert rule is not None
        assert rule.champion == "Cassiopeia"
        # A champion with no combo signal keeps the engine default (with Q2).
        order, rule = resolve_cast_order("NoSuchChampion", {})
        assert rule is None
        assert order == list(DEFAULT_CAST_ORDER)


# ---------------------------------------------------------------------------
# Parse-level rotation assertions per combo champion
# ---------------------------------------------------------------------------


class TestDerivedPathRotations:
    """Champions whose order the derivation computes, not a hand seed.

    Every row here is a retired ``_OVERRIDE_CHAMPIONS`` seed.  A retirement
    moves its assertions rather than deleting them: the same order, the
    same mechanic, asserted on the path that computes it.  Syndra's
    row additionally demands the declared kind and the wiki revision in
    the rationale, which a hand seed's prose never carried; the others
    were seeds the derivation already reproduced, held only until a
    deletion commit proved it on both baselines (``pending_primitive``).

    The rows pin the receipt's whole ordering projection — ``cast_order``,
    ``setup``, ``consume`` and ``aoe`` — because a retirement moves more of
    it than the order.  ``order`` is what the engine executes; the other
    four are published beside it through ``build_rotation_receipt`` and
    reach the public API, and for Aatrox, Jhin and Aphelios no numeric gate
    can see them at all: none is a coupled attacker, and the pair snapshot
    holds no rotation receipt.  A seed hand-listed these fields; a derived
    rule computes them, so each retirement moved them and the moves are
    recorded in ``_SEED_PUBLISHED`` rather than left to be rediscovered.
    """

    # What each retired seed published, for the fields the derivation now
    # computes.  Kept beside the live expectations so the delta a retirement
    # caused is legible instead of implicit: the derivation reads its AoE
    # caps from the structured targeting rows and its setup/consume sets
    # from the edges it actually ordered against, where the seed carried
    # whatever its author wrote down.  None of these deltas moves a damage
    # number — ``aoe`` weights the DPS tie-break by ``min(target_count,
    # cap)`` and the derivation ranks at ``target_count=1``, so every cap
    # collapses to 1 there, and ``setup``/``consume`` are receipt fields no
    # engine reads back.
    _SEED_PUBLISHED = {
        "Syndra": {
            "setup": ["Q"],
            "consume": ["E"],
            "aoe": {"E": 5},
            "moved": {"setup", "consume", "aoe"},
        },
        "Aatrox": {
            "setup": ["R"],
            "consume": [],
            "aoe": {"Q": 5, "W": 2},  # W's hand-written cap of 2 becomes 1
            "moved": {"consume", "aoe"},
        },
        "Jhin": {
            "setup": [],
            "consume": ["R"],
            "aoe": {"Q": 4, "E": 5},  # Q's hand-written cap of 4 becomes 5
            "moved": {"consume", "aoe"},
        },
        "Aphelios": {
            "setup": ["Q", "W"],
            "consume": ["R"],
            "aoe": {"R": 5, "Q": 5},  # gains W and passive at 1
            "moved": {"setup", "consume", "aoe"},
        },
    }

    @pytest.mark.parametrize(
        ("champion", "order", "setup", "consume", "aoe", "fragments"),
        [
            (
                "Syndra",
                ["Q", "Q2", "E", "W", "R"],
                # W joined the setup set with main's Syndra execute edge
                # (R is a missing-health/stored execute, so it follows
                # W's damage).  The ORDER is unchanged: a new edge that
                # agrees with the pinned sequence adds a member here and
                # moves nothing.
                ["E", "Q", "Q2", "W"],
                ["E", "Q2", "R", "W"],
                {"Q": 5, "Q2": 5, "W": 5, "E": 5, "R": 1, "passive": 1},
                ("sphere", "stun", "cc_enabler", "@4024662"),
            ),
            (
                "Aatrox",
                ["R", "Q", "W", "E"],
                ["R"],
                ["Q", "W"],
                {"Q": 5, "W": 1, "E": 5, "R": 1, "passive": 1},
                ("stat_buff(bonus_attack_damage)", "amplifies ability damage"),
            ),
            # Jhin's seed named a mechanic the atomized data does not carry:
            # his kit detects no setup/consume edge at all, so the derivation
            # keeps the certified order and SAYS it found no signal.  The
            # order is the seed's; the claim behind it is not, which is the
            # honest half of retiring a seed nothing could check.  Its
            # ``consume=("R",)`` went with the claim: there is no edge to
            # consume anything, so the derived sets are empty.
            (
                "Jhin",
                ["Q", "W", "E", "R"],
                [],
                [],
                {"Q": 5, "W": 1, "E": 5, "R": 1, "passive": 1},
                ("no detectable setup/consume signal", "kept exactly as reviewed"),
            ),
            # Aphelios is Jhin's case again: the weapon-swap story his seed
            # told is a module OPTION, not a parsed setup/consume atom, so
            # the derivation keeps the certified order and names the absence
            # — and publishes empty setup/consume for the same reason.
            (
                "Aphelios",
                ["Q", "W", "E", "R"],
                [],
                [],
                {"Q": 5, "W": 1, "E": 1, "R": 5, "passive": 1},
                ("no detectable setup/consume signal", "aphelios_main_weapon"),
            ),
        ],
    )
    def test_the_derivation_reproduces_the_order_the_seed_pinned(
        self, champion, order, setup, consume, aoe, fragments, champion_by_name
    ) -> None:
        rotation = _run(champion_by_name[champion])["rotation"]
        assert rotation["cast_order"] == order
        assert rotation["order"][: len(order)] == order
        assert rotation["setup"] == setup
        assert rotation["consume"] == consume
        assert rotation["aoe"] == aoe
        rationale = rotation["rationale"].lower()
        for fragment in fragments:
            assert (
                fragment.lower() in rationale
            ), f"{champion} rationale should mention {fragment!r}: {rationale}"

    @pytest.mark.parametrize("champion", ["Syndra", "Aatrox", "Jhin", "Aphelios"])
    def test_the_published_projection_moved_off_the_seed(
        self, champion, champion_by_name
    ) -> None:
        """Each retirement moved a published field, and this says which.

        A retirement is allowed to move these — they are the derivation's
        own account of what it ordered against, and the seed's were hand
        entries.  What is not allowed is moving them invisibly, which is
        what happens when the only pins are on ``order``.
        """
        rotation = _run(champion_by_name[champion])["rotation"]
        seed = self._SEED_PUBLISHED[champion]
        moved = {
            field
            for field in ("setup", "consume", "aoe")
            if rotation[field] != seed[field]
        }
        assert moved == seed["moved"], (
            f"{champion}'s derived rotation moves {sorted(moved)} off its "
            f"seed, not {sorted(seed['moved'])} — record the move rather "
            "than letting a published field drift unrecorded"
        )

    @pytest.mark.parametrize("champion", ["Syndra", "Aatrox", "Jhin", "Aphelios"])
    def test_the_rule_is_derived_and_carries_no_override_reason(
        self, champion, champion_by_name
    ) -> None:
        _, rule = resolve_cast_order(
            champion,
            _parse_for(champion_by_name[champion]),
            champion_data=champion_by_name[champion],
        )
        assert rule is not None
        assert rule.derived is True
        assert rule.override_reason is None
        assert champion not in CAST_ORDER_OVERRIDES


class TestParseLevelRotations:
    @pytest.mark.parametrize("champion", _OVERRIDE_CHAMPIONS)
    def test_derived_cast_order_matches_the_combo_table(
        self, champion, champion_by_name
    ) -> None:
        result = _run(champion_by_name[champion])
        rotation = result["rotation"]
        assert rotation["cast_order"] == _EXPECTED_ORDERS[champion]
        assert rotation["order"] == _EXPECTED_ORDERS[champion]

    @pytest.mark.parametrize("champion", _OVERRIDE_CHAMPIONS)
    def test_rationale_names_the_driving_mechanic(
        self, champion, champion_by_name
    ) -> None:
        result = _run(champion_by_name[champion])
        rationale = result["rotation"]["rationale"].lower()
        for fragment in _RATIONALE_FRAGMENTS[champion]:
            assert fragment.lower() in rationale, (
                f"{champion} rationale should mention {fragment!r}: "
                f"{result['rotation']['rationale']}"
            )

    def test_cassiopeia_opens_with_poison_and_consumes_with_e(
        self, champion_by_name
    ) -> None:
        result = _run(champion_by_name["Cassiopeia"])
        rotation = result["rotation"]
        assert rotation["setup"] == ["Q", "W"]
        assert rotation["consume"] == ["E"]
        assert rotation["sources"]

    def test_varus_marks_blight_as_setup_and_q_as_detonator(
        self, champion_by_name
    ) -> None:
        result = _run(champion_by_name["Varus"])
        rotation = result["rotation"]
        assert rotation["setup"] == ["W"]
        assert rotation["consume"] == ["Q", "E", "R"]
        # The atom that drives the rule: W's on-hit applies Blight and Q's
        # post_hit_proc prices the detonation.
        abilities = _parse_abilities(champion_by_name["Varus"])
        assert abilities["W"]["on_hit"]
        assert abilities["Q"]["post_hit_proc"]["name"] == "Blight Detonation"

    def test_vladimir_opens_with_r_hemoplague(self, champion_by_name) -> None:
        result = _run(champion_by_name["Vladimir"])
        rotation = result["rotation"]
        assert rotation["cast_order"][0] == "R"
        assert rotation["setup"] == ["R"]
        assert "10%" in rotation["rationale"]

    def test_lux_slows_roots_then_ults(self, champion_by_name) -> None:
        result = _run(champion_by_name["Lux"])
        rotation = result["rotation"]
        assert rotation["cast_order"] == ["E", "Q", "R", "W"]
        assert rotation["setup"] == ["E", "Q"]
        assert rotation["consume"] == ["R"]

    def test_zed_places_shadow_before_burst(self, champion_by_name) -> None:
        result = _run(champion_by_name["Zed"])
        rotation = result["rotation"]
        assert rotation["cast_order"] == ["W", "E", "Q", "R"]
        assert rotation["setup"] == ["W"]
        assert rotation["consume"] == ["R"]

    @pytest.mark.parametrize(
        ("champion", "aoe_slots"),
        [
            ("Cassiopeia", {"W": 5, "R": 5}),
            ("Varus", {"E": 5}),
            ("Brand", {"W": 5, "E": 5}),
            ("Vladimir", {"W": 5, "E": 5, "R": 5}),
            ("Annie", {"W": 5, "R": 5}),
            ("Lux", {"E": 5, "R": 5, "Q": 2}),
            ("Zed", {"E": 5}),
        ],
    )
    def test_receipt_carries_aoe_target_caps(
        self, champion, aoe_slots, champion_by_name
    ) -> None:
        """AoE modeling: the receipt tells the UI which slots hit more than
        one champion and how many."""
        result = _run(champion_by_name[champion])
        assert result["rotation"]["aoe"] == aoe_slots

    def test_annie_opens_with_molten_shield(self, champion_by_name) -> None:
        """Buffs-first: Annie's shield row is in the derived cast order so
        the E8 shield ledger still casts it."""
        result = _run(champion_by_name["Annie"])
        rotation = result["rotation"]
        assert rotation["cast_order"][0] == "E"
        assert "shield" in rotation["rationale"].lower()
        assert "E" in result["breakdown"]


def _parse_abilities(champion_data):
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.stats import calculate_total_stats

    stats = calculate_total_stats(champion_data, 11, [])
    return parse_champion_abilities(
        champion_data,
        11,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
        champion_options=None,
    )


# ---------------------------------------------------------------------------
# DPS ranking signal (data-driven scoring behind the table)
# ---------------------------------------------------------------------------


class TestDpsRanking:
    def test_ranks_by_raw_over_effective_cooldown(self) -> None:
        abilities = {
            "Q": {"total_raw": 100.0, "cooldown": 10.0},
            "W": {"total_raw": 100.0, "cooldown": 5.0},
            "E": {"total_raw": 0.0, "cooldown": 2.0},
            "P": {"total_raw": 50.0, "cooldown": 0.0},  # passive: not a cast
        }
        ranked = rank_ability_dps(abilities)
        assert [slot for slot, *_ in ranked] == ["W", "Q"]

    def test_ability_haste_lowers_effective_cooldown(self) -> None:
        abilities = {"Q": {"total_raw": 100.0, "cooldown": 10.0}}
        base = rank_ability_dps(abilities)[0][1]
        hasted = rank_ability_dps(abilities, ability_haste=100.0)[0][1]
        assert hasted == pytest.approx(base * 2.0)

    def test_cassiopeia_e_outranks_q_as_the_spam_tool(self) -> None:
        """Signal (b): at the parsed per-rank numbers E's 0.75s cooldown
        makes it the highest-DPS cast even though Q's poison total is
        higher per cast."""
        abilities = _parse_abilities(
            next(
                c
                for c in fetch_champion_data().values()
                if c.get("name") == "Cassiopeia"
            )
        )
        ranked = rank_ability_dps(abilities)
        slots = [slot for slot, *_ in ranked]
        assert slots[0] == "E"
        assert "Q" in slots

    def test_aoe_slot_weights_by_roster_target_count(self) -> None:
        """AoE: at five enemies, an ability that hits all five outranks a
        single-target nuke of the same raw damage per cast."""
        abilities = {
            "Q": {"total_raw": 400.0, "cooldown": 10.0},  # single target
            "W": {"total_raw": 100.0, "cooldown": 10.0},  # AoE, hits 5
        }
        aoe = {"W": 5}
        solo = rank_ability_dps(abilities, aoe=aoe, target_count=1)
        assert [slot for slot, *_ in solo] == ["Q", "W"]
        five = rank_ability_dps(abilities, aoe=aoe, target_count=5)
        assert [slot for slot, *_ in five] == ["W", "Q"]
        # The multiplier is min(target_count, cap), never more than the cap.
        w_dps = {s: d for s, d, *_ in five}["W"]
        capped = rank_ability_dps(abilities, aoe=aoe, target_count=9)
        assert {s: d for s, d, *_ in capped}["W"] == w_dps


# ---------------------------------------------------------------------------
# Time-based fights: cooldown-aware cadence
# ---------------------------------------------------------------------------


class TestTimedCadence:
    def test_cassiopeia_q_recasts_at_cd_intervals_with_e_spam_between(
        self, champion_by_name
    ) -> None:
        """Q at t=0, then again at 0.25s cast + 3.5s cooldown = 3.75s; E
        fills the gap on its own 0.875s cycle.  The receipt order shows
        the Q, E, E, E, Q cadence."""
        result = _run(
            champion_by_name["Cassiopeia"],
            one_rotation=False,
            duration=8.0,
            uptime=0.0,
        )
        timeline = [
            (round(float(event["time"]), 2), event["slot"])
            for event in result["cast_timeline"]
        ]
        q_times = [time for time, slot in timeline if slot == "Q"]
        assert q_times[0] == 0.0
        assert q_times[1] == pytest.approx(3.75, abs=0.01)
        assert q_times[2] == pytest.approx(7.5, abs=0.01)
        # E casts sit between the Q reapplications.
        e_times = [time for time, slot in timeline if slot == "E"]
        assert any(0.25 < time < 3.75 for time in e_times)
        assert any(3.75 < time < 7.5 for time in e_times)
        # The receipt order reads Q, E, E, E, Q, ... (not E before Q).
        order = result["rotation"]["order"]
        assert order[0] == "Q"
        assert order[1] == "E"
        assert "Q" in order[2:]
        # W's zone cast happens after E on the shared timeline.
        w_time = next(time for time, slot in timeline if slot == "W")
        assert w_time > e_times[0]

    def test_cassiopeia_combo_order_lands_more_es_than_fixed_order(
        self, champion_by_name
    ) -> None:
        """The whole point: E before W on the shared timeline starts the
        spam cadence earlier — strictly more Twin Fangs in a 3s window."""
        data = champion_by_name["Cassiopeia"]
        combo = _run(data, one_rotation=False, duration=3.0)
        default = run_fight(
            data,
            11,
            [],
            _params(
                one_rotation=False,
                duration=3.0,
                cast_order=FIXED_ORDER,
            ),
        )
        assert combo["breakdown"]["E"]["casts"] > default["breakdown"]["E"]["casts"]
        assert combo["total_damage"] > default["total_damage"]

    def test_varus_autos_apply_blight_before_q_detonates(
        self, champion_by_name
    ) -> None:
        """Timed fight with an auto stream: the Blight detonation rides the
        Q cast (post_hit_proc) after the auto-applied stacks exist, and the
        receipt marks W (the on-hit applier) as setup."""
        result = _run(
            champion_by_name["Varus"],
            one_rotation=False,
            duration=5.0,
            uptime=1.0,
        )
        rotation = result["rotation"]
        assert rotation["setup"] == ["W"]
        assert rotation["consume"] == ["Q", "E", "R"]
        assert rotation["order"][0] == "Q"
        # The auto stream exists and the detonation is priced on Q.
        assert result["breakdown"]["auto_attacks"]["count"] > 0
        detonation = result["breakdown"]["blight_detonation"]
        assert detonation["total_damage"] > 0
        q_casts = result["breakdown"]["Q"]["casts"]
        # One sourced detonation per Q cast (conservative single-detonator
        # model, documented in the Varus module).
        assert detonation["count"] == q_casts

    def test_zed_w_first_lets_e_recast_inside_the_window(
        self, champion_by_name
    ) -> None:
        """The W-shadow opener costs zero cast time, so E fires at t=0 and
        again at t=5.0 — two casts instead of the later E's one.

        The control was the engine's fixed default order until Zed's module
        declared that Q and E each require the Shadow placement: an order
        opening on Q now inverts that declaration and is refused outright
        (D-86, asserted in the next test).  So the control moved to the
        nearest legal order — W still first, E one slot later — which is
        what isolates E's cadence rather than the opener.
        """
        data = champion_by_name["Zed"]
        combo = _run(data, one_rotation=False, duration=5.0, uptime=1.0)
        late_e = run_fight(
            data,
            11,
            [],
            _params(
                one_rotation=False,
                duration=5.0,
                uptime=1.0,
                cast_order=["W", "Q", "E", "R"],
            ),
        )
        assert combo["breakdown"]["E"]["casts"] > late_e["breakdown"]["E"]["casts"]
        assert combo["rotation"]["order"][0] == "W"

    def test_zeds_declaration_refuses_an_order_that_skips_the_shadow(
        self, champion_by_name
    ) -> None:
        """The fixed default order is not a legal request for Zed.

        D-86 at a champion the phase's criteria never name: a declared
        prerequisite states impossibility, so ``Q, W, E, R`` — the fixed
        default — comes back as a refusal quoting the
        Shadow-placement mechanic rather than as a fight priced against a
        kit Zed cannot cast.
        """
        with pytest.raises(CustomOrderViolatesDependencyError) as caught:
            run_fight(
                champion_by_name["Zed"],
                11,
                [],
                _params(
                    one_rotation=False,
                    duration=5.0,
                    uptime=1.0,
                    cast_order=FIXED_ORDER,
                ),
            )
        assert (caught.value.dependency.slot, caught.value.dependency.requires) == (
            "Q",
            "W",
        )
        assert caught.value.dependency.source in str(caught.value)

    def test_receipt_fallback_documents_the_default_order(self) -> None:
        receipt = build_rotation_receipt(
            cast_order=list(DEFAULT_CAST_ORDER),
            cast_timeline=[],
            rule=None,
        )
        assert receipt["order"] == list(DEFAULT_CAST_ORDER)
        assert "default" in receipt["rationale"].lower()
        assert receipt["setup"] == []
        assert receipt["consume"] == []

    def test_receipt_defers_to_explicit_user_order(self, champion_by_name) -> None:
        """An explicit caller-supplied order wins and is labelled as such —
        the combo layer never overrides it."""
        from src.calculator.pipeline import FightParams, run_fight

        data = champion_by_name["Cassiopeia"]
        params = FightParams(
            target_health=2000.0,
            target_bonus_health=0.0,
            target_armor=50.0,
            target_magic_resistance=40.0,
            fight_duration_seconds=ONE_ROTATION_DURATION,
            auto_attack_uptime=0.0,
            one_rotation=True,
            include_actives=True,
            cast_order=["R", "E", "Q", "W"],
            auto_attacks_only=False,
            ability_ranks=None,
            champion_options=None,
            deterministic=True,
        )
        result = run_fight(data, 11, [], params)
        rotation = result["rotation"]
        assert rotation["cast_order"] == ["R", "E", "Q", "W"]
        assert rotation["order"] == ["R", "E", "Q", "W"]
        assert "Custom order" in rotation["rationale"]
