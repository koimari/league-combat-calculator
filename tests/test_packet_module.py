"""Tests for the champion-agnostic packet compiler.

The claim under test is provenance, not arithmetic: every number a packet
slot serves must come from the cache row the packet says it is evidence of.
So each assertion is computed from ``data/champions.json`` at the rank the
entry reports, never written as a literal — a patch that moves a cooldown
moves both sides together.

The compiler is exercised directly, over every packet in the reviewed
asset, so the population is the evidence itself rather than whichever
champions a test session happens to import first.
"""

import json
import sys
from pathlib import Path

import pytest

from src.calculator.champions.engine import SlotCtx
from src.calculator.champions.packet_module import (
    _packet_parser,
    build_packet_module,
    packet_spec_sha256,
)
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.slotlib import extract_cooldown
from src.calculator.scenario import load_public_champion

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.source_receipt import cache_patch  # noqa: E402

LEVEL = 18
RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
STATS = {
    "ability_power": 200.0,
    "attack_damage": 200.0,
    "base_attack_damage": 100.0,
    "bonus_attack_damage": 100.0,
    "health": 2000.0,
    "base_health": 1200.0,
    "bonus_health": 800.0,
    "armor": 100.0,
    "bonus_armor": 50.0,
    "magic_resistance": 60.0,
    "bonus_magic_resistance": 30.0,
    "max_mana": 1000.0,
    "bonus_mana": 400.0,
}
TARGET = {
    "target_max_health": 2500.0,
    "target_current_health": 2500.0,
    "target_missing_health": 0.0,
}

_ASSET = Path(__file__).resolve().parents[1] / "static" / "reviewed-packets.json"


def _packet_specs():
    """Every ``(champion, slot, spec)`` the asset declares as a packet."""
    champions = json.loads(_ASSET.read_text(encoding="utf-8"))["champions"]
    rows = []
    for champion, entry in champions.items():
        for slot, spec in (entry.get("slots") or {}).items():
            if spec.get("kind") == "packet":
                rows.append((champion, slot, spec))
            elif spec.get("kind") == "variants":
                for variant in spec.get("variants") or []:
                    if variant.get("kind") == "packet":
                        rows.append((champion, slot, variant))
    return rows


PACKET_SPECS = _packet_specs()

# The 16.15-built asset against 16.16 champion data: one packet's rank-1
# cooldown moved under it.  Camille's Tactical Sweep went 15/14/13/12/11 ->
# 12/11.5/11/10.5/10 in 16.16.1, and the asset predates that.  Closed by the
# patch-day rebuild (``python scripts/patch_update.py run``), which needs the
# wiki index and the Axword checkout this tree does not carry.
PATCH_DAY_STALE = {("Camille", "W"): (15.0, 12.0)}


def _ctx(champion: str, slot: str) -> SlotCtx:
    return SlotCtx(
        slot=slot,
        champion_name=champion,
        abilities=load_public_champion(champion).get("abilities") or {},
        level=LEVEL,
        stats=dict(STATS),
        target=dict(TARGET),
        ability_ranks=dict(RANKS),
    )


def _source_ability(champion: str, slot: str, spec: dict):
    source = tuple(spec["source"]) if spec.get("source") else (slot, 0)
    entries = (load_public_champion(champion).get("abilities") or {}).get(source[0], [])
    return entries[source[1]] if source[1] < len(entries) else None


def _compiled(champion: str, slot: str, spec: dict):
    return _packet_parser(spec, slot)(_ctx(champion, slot))


class TestPacketCooldownProvenance:
    """The compiled cooldown is the cache's row at the rank being cast."""

    def test_population_is_the_whole_asset(self) -> None:
        assert len(PACKET_SPECS) > 400

    def test_the_asset_is_still_behind_the_cache_it_is_evidence_of(self) -> None:
        """The expiry on the exception below, asserted rather than trusted.

        ``reviewed-packets.json`` is a patch-day artifact: its builder
        pre-flights the Local Wiki sqlite index and the Axword sibling
        checkout and refuses to write without both, so it cannot be
        regenerated from this tree.  Merging origin/main brought 16.16 data
        in beside a 16.15-built asset.  When ``patch_update.py run``
        rebuilds it the stamps agree again and ``PATCH_DAY_STALE`` goes red
        as an unused exception — which is the point of pinning it here.
        """
        assert json.loads(_ASSET.read_text(encoding="utf-8"))["patch"] == "16.15"
        assert cache_patch() != "16.15"

    def test_stored_scalar_is_only_ever_the_cache_rank_one_value(self) -> None:
        """The asset's scalar is evidence of rank 1 and of nothing else.

        This is what makes reading the cache a *fix* rather than a second
        opinion: the two agree at the only rank a scalar can express, and
        the scalar has nothing to say about any other.

        ``PATCH_DAY_STALE`` is the one gap the merge opened and this tree
        cannot close (see the test above).  It is spelled as an exact
        expectation, not a skip: the stale scalar still has to be the value
        it was, so a *second* drift is a failure rather than a widening.
        """
        divergent = {}
        for champion, slot, spec in PACKET_SPECS:
            ability = _source_ability(champion, slot, spec)
            if ability is None:
                continue
            stored = float(spec.get("cooldown", 0.0))
            fresh = extract_cooldown(ability, 1)
            if abs(stored - fresh) > 1e-9:
                divergent[(champion, slot)] = (stored, fresh)
        assert divergent == PATCH_DAY_STALE

    def test_no_packet_serves_a_rank_one_cooldown_at_a_higher_rank(self) -> None:
        """The defect's own signature, swept over every packet in the asset."""
        frozen = []
        for champion, slot, spec in PACKET_SPECS:
            ability = _source_ability(champion, slot, spec)
            entry = _compiled(champion, slot, spec)
            if ability is None or entry is None:
                continue
            rank = entry["rank"]
            expected = extract_cooldown(ability, rank, level=LEVEL)
            if abs(float(entry["cooldown"]) - expected) > 1e-9:
                frozen.append((champion, slot, entry["cooldown"], expected))
        assert not frozen

    def test_the_sweep_covers_rank_varying_cooldowns(self) -> None:
        """The sweep above is only worth running because the axis moves."""
        varying = 0
        for champion, slot, spec in PACKET_SPECS:
            ability = _source_ability(champion, slot, spec)
            if ability is None:
                continue
            entry = _compiled(champion, slot, spec)
            if entry is None:
                continue
            if extract_cooldown(ability, 1) != extract_cooldown(
                ability, entry["rank"], level=LEVEL
            ):
                varying += 1
        assert varying > 100

    @pytest.mark.parametrize(
        "champion,slot",
        [("Thresh", "Q"), ("Vladimir", "E"), ("Talon", "R"), ("Samira", "Q")],
    )
    def test_a_maxed_ability_is_served_its_maxed_cooldown(
        self, champion: str, slot: str
    ) -> None:
        """End to end, through the champion's own registered module."""
        ability = load_public_champion(champion)["abilities"][slot][0]
        parsed = parse_champion_abilities(
            load_public_champion(champion),
            LEVEL,
            STATS["ability_power"],
            dict(RANKS),
            champion_stats=dict(STATS),
            target_stats=dict(TARGET),
        )
        served = parsed[slot]["cooldown"]
        assert served == extract_cooldown(ability, RANKS[slot])
        assert served < extract_cooldown(ability, 1)

    def test_alternate_source_reads_that_entry_cooldown(self) -> None:
        """A packet pricing a form entry reads that entry's cooldown row.

        Nidalee's Q packet is cougar-form Takedown (``["Q", 1]``), whose
        cooldown row is not Javelin Toss's.
        """
        spec = next(
            spec
            for champion, slot, spec in PACKET_SPECS
            if champion == "Nidalee" and slot == "Q" and spec.get("name") == "Takedown"
        )
        assert list(spec["source"]) == ["Q", 1]
        abilities = load_public_champion("Nidalee")["abilities"]["Q"]
        entry = _compiled("Nidalee", "Q", spec)
        assert entry["cooldown"] == extract_cooldown(abilities[1], RANKS["Q"])

    def test_per_level_cooldown_row_is_read_at_the_level(self) -> None:
        """Aphelios' weapon cooldowns hold one value per level, not per rank."""
        spec = next(
            spec
            for champion, slot, spec in PACKET_SPECS
            if champion == "Aphelios" and slot == "Q"
        )
        values = _source_ability("Aphelios", "Q", spec)["cooldown"]["modifiers"][0][
            "values"
        ]
        assert len(values) >= 18
        entry = _compiled("Aphelios", "Q", spec)
        assert entry["cooldown"] == pytest.approx(float(values[LEVEL - 1]))

    def test_a_packet_without_a_cached_cooldown_row_serves_zero(self) -> None:
        """No literal survives the cache going quiet — the row is the source."""
        rows = [
            (champion, slot, spec)
            for champion, slot, spec in PACKET_SPECS
            if (ability := _source_ability(champion, slot, spec)) is not None
            and not (ability.get("cooldown") or {}).get("modifiers")
        ]
        assert rows
        for champion, slot, spec in rows:
            entry = _compiled(champion, slot, spec)
            if entry is not None:
                assert entry["cooldown"] == 0.0


class TestModuleOverrides:
    """Everything a module says about its packet goes INTO the compiler.

    ``slot_parsers`` replaces any compiled slot or appends a new one,
    ``slot_wrappers`` hands a module the compiled parser to build on,
    ``slot_order`` states the module's slot surface, and the pin rides the
    parser the compiler returns — so a module never rebinds
    ``parse_abilities`` and the contract can read the pin off what runs.
    """

    @staticmethod
    def _build(champion: str, **overrides):
        spec = json.loads(_ASSET.read_text(encoding="utf-8"))["champions"][champion]
        return build_packet_module(champion, packet_spec_sha256(spec), **overrides)

    @staticmethod
    def _parse(parser, champion: str):
        return parser(
            load_public_champion(champion),
            LEVEL,
            STATS["ability_power"],
            ability_ranks=dict(RANKS),
            champion_stats=dict(STATS),
            target_stats=dict(TARGET),
        )

    def test_the_compiled_parser_and_slot_map_carry_the_pin(self) -> None:
        spec = json.loads(_ASSET.read_text(encoding="utf-8"))["champions"]["Singed"]
        parser, slots, *_ = self._build("Singed")
        assert parser.packet_sha256 == slots.packet_sha256 == packet_spec_sha256(spec)
        assert parser.packet_spec == slots.packet_spec == spec

    def test_slot_parsers_replace_a_slot_of_any_kind_in_place(self) -> None:
        """Singed's W is a no_damage packet slot; the override still lands."""

        def custom(ctx):
            return None

        _, slots, *_ = self._build("Singed", slot_parsers={"W": custom})
        assert slots["W"] is custom
        assert list(slots) == ["Q", "W", "E", "R", "P"]

    def test_slot_parsers_append_a_slot_the_packet_lacks(self) -> None:
        def custom(ctx):
            return None

        _, slots, *_ = self._build("Singed", slot_parsers={"R_buff": custom})
        assert list(slots) == ["Q", "W", "E", "R", "P", "R_buff"]

    def test_slot_wrappers_receive_the_compiled_parser(self) -> None:
        seen = []

        def certify(compiled):
            seen.append(compiled)

            def parse(ctx):
                entry = compiled(ctx)
                if entry is not None:
                    entry["detail"] = "wrapped"
                return entry

            return parse

        parser, slots, *_ = self._build("Singed", slot_wrappers={"Q": certify})
        assert seen and slots["Q"] is not seen[0]
        assert self._parse(parser, "Singed")["Q"]["detail"] == "wrapped"

    def test_a_wrapper_for_a_slot_nothing_compiled_is_refused(self) -> None:
        with pytest.raises(KeyError, match="slot_wrappers names 'Z'"):
            self._build("Singed", slot_wrappers={"Z": lambda compiled: compiled})

    def test_slot_order_states_the_surface_in_order(self) -> None:
        _, slots, *_ = self._build("Singed", slot_order=("P", "Q", "E"))
        assert list(slots) == ["P", "Q", "E"]

    def test_slot_order_naming_an_unknown_slot_is_refused(self) -> None:
        with pytest.raises(KeyError, match=r"slot_order names \['Z'\]"):
            self._build("Singed", slot_order=("P", "Q", "Z"))

    def test_single_hit_slots_certify_a_wiki_attribute_row(self) -> None:
        """Zac's Q is a wiki_attribute slot; the certification reaches it."""
        plain, *_ = self._build("Zac")
        certified, *_ = self._build("Zac", single_hit_slots=frozenset({"Q"}))
        assert "event_order_certified" not in self._parse(plain, "Zac")["Q"]
        assert (
            self._parse(certified, "Zac")["Q"]["event_order_certified"] == "single_hit"
        )

    def test_single_hit_slots_naming_a_slot_with_no_row_is_refused(self) -> None:
        """The same refusal ``slot_wrappers`` and ``slot_order`` give a typo:
        a certification that reaches no row would otherwise certify nothing
        in silence.  Singed's W is a ``no_damage`` slot; a ticked
        ``wiki_attribute`` row is rebuilt by its tick fix, not certified."""
        with pytest.raises(KeyError, match=r"single_hit_slots names \['Z'\]"):
            self._build("Singed", single_hit_slots=frozenset({"Z"}))
        with pytest.raises(KeyError, match=r"single_hit_slots names \['W'\]"):
            self._build("Singed", single_hit_slots=frozenset({"W"}))
        with pytest.raises(KeyError, match=r"single_hit_slots names \['W'\]"):
            self._build(
                "Zac",
                single_hit_slots=frozenset({"W"}),
                wiki_attribute_tick_fixes={"W": {"ticks": 1}},
            )
