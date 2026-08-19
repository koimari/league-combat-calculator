"""Front-door tests for the rotation resolver.

The F2 and F3 suites keep the historical campaign cases and the broad
champion matrix.  These tests make the resolver easy to find by module name.
"""

import dataclasses

import pytest

from src.calculator import rotation_resolver
from src.calculator import champions as champions_package
from src.calculator.champions import get_champion_cast_order, parse_champion_abilities
from src.calculator.champions.engine import _apply_module_cc
from src.calculator.damage import DEFAULT_CAST_ORDER
from src.calculator.data_fetcher import fetch_champion_data
from src.calculator.rotation_resolver import (
    _DERIVED_RULE_CACHE,
    _PRE_CAMPAIGN_CC_ORDERING,
    detect_setup_consume_edges,
    rank_ability_dps,
    resolve_cast_order,
)
from src.calculator.stats import calculate_total_stats


def test_unknown_empty_kit_uses_the_engine_default_order() -> None:
    order, rule = resolve_cast_order("Synthetic Fixture", {})

    assert order == list(DEFAULT_CAST_ORDER)
    assert rule is None


def test_dps_ranking_uses_the_effective_cooldown() -> None:
    ranked = rank_ability_dps(
        {
            "Q": {"total_raw": 100.0, "cooldown": 10.0},
            "W": {"total_raw": 100.0, "cooldown": 5.0},
        }
    )

    assert [slot for slot, *_ in ranked] == ["W", "Q"]


class TestAReviewedAbsenceOfControlOrdersNothing:
    """``cc_kind="none"`` is a reviewed absence, so it is not an apply atom.

    The detector fans a ``cc_setup`` edge from every slot that applies
    crowd control, out to every castable damage row.  Reading a reviewed
    *absence* as an application would rewrite a whole kit's derived cast
    order around a stun the module explicitly said does not exist — and
    the receipt would cite it in prose.
    """

    CHAMPION = "Corki"  # migrated cc-free, whole kit

    @pytest.fixture(scope="class")
    def champion_data(self):
        champions = fetch_champion_data()
        return next(
            data for data in champions.values() if data.get("name") == self.CHAMPION
        )

    @pytest.fixture(scope="class")
    def parsed(self, champion_data):
        stats = calculate_total_stats(champion_data, 18, [])
        return parse_champion_abilities(
            champion_data,
            18,
            stats["ability_power"],
            champion_stats=stats,
            target_stats={
                "target_max_health": 2000.0,
                "target_current_health": 2000.0,
                "target_missing_health": 0.0,
            },
        )

    @staticmethod
    def _edges(champion_name, parsed, champion_data):
        return detect_setup_consume_edges(champion_name, parsed, champion_data, {})

    def test_the_kit_is_actually_declared_cc_free(self, parsed) -> None:
        """The premise: every part of every slot carries the review."""
        kinds = {
            part.cc_kind for entry in parsed.values() for part in entry.get("parts", ())
        }
        assert kinds == {"none"}

    def test_no_cc_setup_edge_is_fanned(self, parsed, champion_data) -> None:
        edges = self._edges(self.CHAMPION, parsed, champion_data)
        assert [e for e in edges if e.kind == "cc_setup"] == []

    def test_no_derived_rationale_cites_crowd_control(
        self, parsed, champion_data
    ) -> None:
        _order, rule = resolve_cast_order(
            self.CHAMPION, parsed, champion_data=champion_data
        )
        assert "cc_kind" not in (rule.rationale if rule else "")
        assert "crowd control" not in (rule.rationale if rule else "")

    def test_a_real_kind_on_the_same_row_still_fans_edges(
        self, parsed, champion_data
    ) -> None:
        """The suppression is about the reviewed absence and nothing else:
        the same row carrying a real kind still orders the rotation.

        No kind a champion MODULE carries is an ordering claim, so the row
        is read here under a name with no module behind it — a synthetic
        kit, which is the form the fan-out still reads
        (:class:`TestAModuleAuthoredKitFactDoesNotOrderTheRotation`).
        """
        stunned = dict(parsed)
        stunned["E"] = dict(parsed["E"])
        stunned["E"]["parts"] = tuple(
            dataclasses.replace(part, cc_kind="stun") for part in stunned["E"]["parts"]
        )
        edges = self._edges("Synthetic Fixture", stunned, champion_data)
        assert [(e.setup, e.consume) for e in edges if e.kind == "cc_setup"]


class TestAModuleAuthoredKitFactDoesNotOrderTheRotation:
    """A module's ``cc_kind`` says what a cast APPLIES, never when to cast it.

    A module recording its reviewed crowd control is stating a kit fact of
    the same class as "this ability deals magic damage".  Reading it as an
    ordering constraint made the coverage campaign expensive in exactly the
    wrong currency: recording a true slow reordered the rotation and moved
    published damage, so a pass withheld facts it had verified rather than
    move numbers nobody had reviewed.  Ordering belongs to the declared
    ``CAST_DEPENDENCIES`` vocabulary.

    Three worlds over one real kit, one variable apart, all three driving
    the real parser and the real derivation:

    ``silent``    no kind anywhere — the kit before its review;
    ``declared``  the module's ``MODULE_CC`` names the slots, and the
                  engine's own :func:`_apply_module_cc` stamps the parts;
    ``authored``  the identical parts with no declaration behind them — a
                  marker written at its construction site, the only way to
                  say a kind that varies across one cast's hits.

    Both must equal ``silent``.  Which authoring site a module happened to
    use is not something a reviewer should have to hold in mind, and
    Morgana's R cannot even choose between them.
    """

    # Kits outside _PRE_CAMPAIGN_CC_ORDERING, so nothing here is pinned.
    CHAMPIONS = ("Corki", "Garen", "Ezreal")

    @pytest.fixture(scope="class")
    def champions(self):
        by_name = {data.get("name"): data for data in fetch_champion_data().values()}
        return {name: by_name[name] for name in self.CHAMPIONS}

    @staticmethod
    def _parse(champion_data):
        stats = calculate_total_stats(champion_data, 11, [])
        return parse_champion_abilities(
            champion_data,
            11,
            stats["ability_power"],
            champion_stats=stats,
            target_stats={
                "target_max_health": 2000.0,
                "target_current_health": 2000.0,
                "target_missing_health": 0.0,
            },
        )

    @classmethod
    def _silent(cls, champion_data):
        """The kit with no crowd control marked anywhere."""
        parsed = cls._parse(champion_data)
        return {
            slot: {
                **entry,
                "parts": tuple(
                    dataclasses.replace(part, cc_kind=None)
                    for part in entry.get("parts", ())
                ),
            }
            for slot, entry in parsed.items()
        }

    @classmethod
    def _marked(cls, champion_name, champion_data, kind="stun"):
        """The kit with *kind* stamped on every part, by the engine itself."""
        parsed = cls._silent(champion_data)
        for slot, entry in parsed.items():
            _apply_module_cc(entry, kind, champion_name, slot)
        return parsed

    @staticmethod
    def _declaring(monkeypatch, champion_name, slots):
        """Make the champion's module declare ``MODULE_CC`` over *slots*.

        The contract is the declaration's one home, so this is where a
        module's ``MODULE_CC`` is faked — nothing in the resolver is
        stubbed, and the gate under test runs its real lookup.
        """
        real = champions_package.get_champion_module_contract
        monkeypatch.setattr(
            champions_package,
            "get_champion_module_contract",
            lambda name: (
                dataclasses.replace(real(name), cc_kinds={s: "stun" for s in slots})
                if name == champion_name
                else real(name)
            ),
        )

    @staticmethod
    def _derive(monkeypatch, champion_name, champion_data, parsed):
        """The derived rule for *parsed*, through the production path.

        ``derive_champion_rule`` re-parses the canonical kit itself, so the
        injection point is that parse — everything after it (edge
        detection, the declared merge, the DPS ranking, the rationale) is
        the shipped code.
        """
        monkeypatch.setattr(
            rotation_resolver, "_canonical_kit_parse", lambda *_a, **_k: parsed
        )
        _DERIVED_RULE_CACHE.clear()
        try:
            return resolve_cast_order(
                champion_name,
                parsed,
                champion_data=champion_data,
                certified_order=get_champion_cast_order(champion_name),
            )
        finally:
            _DERIVED_RULE_CACHE.clear()

    @pytest.mark.parametrize("champion_name", CHAMPIONS)
    @pytest.mark.parametrize("authoring", ("declared", "authored"))
    def test_recording_control_changes_no_order_and_no_rationale(
        self, champions, monkeypatch, champion_name, authoring
    ) -> None:
        """The ruling itself, on the strongest form of each authoring site:
        every slot of the kit carries a stun, and nothing moves."""
        data = champions[champion_name]
        silent = self._silent(data)
        marked = self._marked(champion_name, data)

        silent_order, silent_rule = self._derive(
            monkeypatch, champion_name, data, silent
        )
        self._declaring(
            monkeypatch, champion_name, marked if authoring == "declared" else ()
        )
        marked_order, marked_rule = self._derive(
            monkeypatch, champion_name, data, marked
        )

        assert marked_order == silent_order
        assert marked_rule.rationale == silent_rule.rationale
        assert marked_rule.sources == silent_rule.sources
        assert "crowd control" not in marked_rule.rationale

    @pytest.mark.parametrize("champion_name", CHAMPIONS)
    def test_the_marks_actually_reached_every_part(
        self, champions, champion_name
    ) -> None:
        """The premise: the pins above are not passing on an empty stamp.

        A slot with no damage parts carries no marker to stamp (it emits
        no row the ledger could read), so the claim is over the rows that
        do — and that there are some.
        """
        marked = self._marked(champion_name, champions[champion_name])
        stamped = [slot for slot, entry in marked.items() if entry.get("parts")]

        assert stamped
        for slot in stamped:
            assert {part.cc_kind for part in marked[slot]["parts"]} == {"stun"}, slot

    @pytest.mark.parametrize("champion_name", CHAMPIONS)
    @pytest.mark.parametrize("authoring", ("declared", "authored"))
    def test_neither_authoring_site_fans_a_setup_edge(
        self, champions, monkeypatch, champion_name, authoring
    ) -> None:
        """The same claim at the edge level, where the fan-out lives."""
        data = champions[champion_name]
        marked = self._marked(champion_name, data)
        self._declaring(
            monkeypatch, champion_name, marked if authoring == "declared" else ()
        )

        edges = detect_setup_consume_edges(champion_name, marked, data, {})

        assert [e for e in edges if e.kind == "cc_setup"] == []

    def test_the_same_marks_on_a_kit_with_no_module_still_fan(self, champions) -> None:
        """The inference is narrowed, not switched off.

        What the rule refuses is a *champion module's* statement about its
        own kit.  A synthetic or development fixture has no module, so its
        markers still order — which is what keeps the detector's own
        negative-test evidence (``__synthetic__`` kits in
        ``tests/test_cast_dependency_audit.py``) load-bearing rather than
        quietly inert.
        """
        data = champions["Corki"]
        marked = self._marked("Corki", data)

        edges = detect_setup_consume_edges("Synthetic Fixture", marked, data, {})

        assert [e for e in edges if e.kind == "cc_setup"]


class TestThePinnedPreCampaignOrdering:
    """The three slots whose control ordered the rotation before the rule.

    Their published orders predate it, so they are pinned rather than
    re-derived.  The table is closed — it can only shrink, by moving the
    ordering into the kit's ``CAST_DEPENDENCIES`` — so both halves are
    pinned here: what it holds, and that each entry still earns its keep.
    """

    @pytest.fixture(scope="class")
    def champions(self):
        return {data.get("name"): data for data in fetch_champion_data().values()}

    def test_the_table_holds_exactly_the_pre_campaign_slots(self) -> None:
        assert _PRE_CAMPAIGN_CC_ORDERING == {
            "Ahri": frozenset({"E"}),
            "Pantheon": frozenset({"W"}),
            "Syndra": frozenset({"E"}),
        }

    @pytest.mark.parametrize(
        "champion_name,slot",
        [("Ahri", "E"), ("Pantheon", "W"), ("Syndra", "E")],
    )
    def test_each_pinned_slot_still_fans_its_edges(
        self, champions, champion_name, slot
    ) -> None:
        data = champions[champion_name]
        stats = calculate_total_stats(data, 11, [])
        parsed = parse_champion_abilities(
            data,
            11,
            stats["ability_power"],
            champion_stats=stats,
            target_stats={
                "target_max_health": 2000.0,
                "target_current_health": 2000.0,
                "target_missing_health": 0.0,
            },
        )

        marks = {part.cc_kind for part in parsed[slot].get("parts", ()) if part.cc_kind}
        assert marks - {"none"}, f"{champion_name} {slot} no longer marks a kind"
        edges = detect_setup_consume_edges(champion_name, parsed, data, {})
        assert [e for e in edges if e.kind == "cc_setup" and e.setup == slot]
