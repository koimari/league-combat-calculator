"""F3 — algorithmic optimal-order derivation for every registered champion.

The F2 combo layer hand-curated the ``COMBO_TABLE`` seeds; every other
champion fell back to the certified/default order with a generic
rationale.  F3 replaces that with a fully algorithmic derivation
(:func:`src.calculator.rotation_resolver.derive_champion_rule`): the
order is computed on the fly from the atomized ability data — typed
parsed atoms (``dot_duration``, ``on_hit``, ``applies_dot_stack``,
``post_hit_proc``, ``target_debuff``, ``stat_buff``, ``cc_kind``),
module OPTION rotation declarations (``target_poisoned``,
``blight_stacks``, ``p_illumination_procs``, ``moonlight_reset``, ...),
and the structured wiki attribute rows.

This suite asserts the combo invariants the product owner asked for, for
EVERY champion:

(a) a derived order never violates a detected setup/consume edge
    (setup before consume: E-before-poison, detonate-before-stack-
    application, shred/buff before the burst, execute after the burst);
(b) the rationale cites real atoms (option keys, attribute names, parsed
    atom keys) — never a generic fallback for a signal-bearing kit;
(c) the order is deterministic and stable across levels/items for the
    same champion;
(d) the order is a permutation of the certified/base slots (no invented
    slots, none dropped), and the verified seeds stay as overrides.
"""

import pytest

from src.calculator.cast_dependency import (
    DEPENDENCY_KINDS,
    INFERRED_EDGE_KINDS,
    CastDependency,
    ConflictingInferenceError,
    MissingLatentReasonError,
    SuppressedInference,
)
from src.calculator.champions import get_champion_cast_order
from src.calculator.data_fetcher import fetch_champion_data, fetch_item_data
from src.calculator.rotation_resolver import (
    COMBO_TABLE,
    DependencyReceipt,
    _Edge,
    detect_setup_consume_edges,
    merge_declared_edges,
    resolve_cast_order,
    resolved_edges,
)

# ── the verified seeds stay as documented overrides ──
_OVERRIDE_CHAMPIONS = [
    "Cassiopeia",
    "Varus",
    "Brand",
    "Vladimir",
    "Aatrox",
    "Jhin",
    "Annie",
    "Lux",
    "Zed",
    "Aphelios",
    "Syndra",
]

# Documented seed exceptions: the verified F2 seed deliberately deviates
# from a data edge (the seed's judgment wins; each is justified in the
# seed's own rationale).
#   - Cassiopeia: W (Miasma) also applies poison, so the data says W→E,
#     but the seed casts E before W to start the 0.75s spam cadence
#     earlier on the shared timeline (W is zoning, Q is the poison).
#   - Varus: R applies Blight stacks, so the data says R→Q, but the seed
#     puts the Blight DETONATOR Q first (the auto-applied stacks ride Q;
#     R's own stacks land later in the burst).
#   - Syndra: E's authored stun makes the generic cc-setup fan-out say
#     E→(Q, Q2, W, R), but the stun only exists by scattering a sphere Q
#     provides — the dependency runs Q→E, so the seed opens Q and keeps
#     W/R inside the stun window.
_OVERRIDE_SEED_EXCEPTIONS = {
    "Cassiopeia": {("W", "E")},
    "Varus": {("R", "Q")},
    "Syndra": {("E", "Q"), ("E", "Q2")},
}

# Level x build reference matrix (mirrors scripts/golden_snapshot.py).
_MATRIX_BUILDS = (
    ("L11", 11, ()),
    ("L18", 18, ()),
    ("L18_magic", 18, ("Luden's Echo", "Shadowflame", "Rabadon's Deathcap")),
    ("L18_physical", 18, ("Kraken Slayer", "Infinity Edge", "Lord Dominik's Regards")),
    ("L18_spellblade", 18, ("Trinity Force", "Infinity Edge", "Berserker's Greaves")),
)

# Expected derived orders for the signal-bearing champions (locks the
# derivation against silent regressions back to the default order).
_EXPECTED_DERIVED_ORDERS = {
    "Ahri": ["E", "Q", "W", "R"],  # charm cc setup opens the burst
    "Ambessa": ["R", "Q", "Q2", "W", "E"],  # R armor pen buff first
    "Bel'Veth": ["Q", "W", "R", "E"],  # E missing-health execute last
    "Briar": ["Q", "E", "R", "W"],  # Q shred first, W execute last
    "Corki": ["E", "Q", "W", "R"],  # E resistance shred opens
    "Darius": ["E", "Q", "W", "R"],  # E pen buff + Q/W stacks feed R
    "Dr. Mundo": ["E", "Q", "W", "R"],  # E bonus-AD buff first
    "Evelynn": ["W", "Q", "E", "R"],  # W charm+shred, Q consumes mark, R execute
    "Ezreal": ["W", "Q", "E", "R"],  # W mark detonated by any ability
    "Garen": ["E", "Q", "W", "R"],  # E armor shred opens
    "Hwei": ["R", "Q", "W", "E"],  # Q missing-health execute after R's burst
    "Pantheon": ["W", "E", "R", "Q"],  # W stun opens, Q execute closes
    "Ryze": ["E", "Q", "W", "R"],  # E Flux mark consumed by basic abilities
    "Shaco": ["Q", "W", "R", "E"],  # E execute closes
    "Sion": ["E", "Q", "W", "R"],  # E armor shred opens
    "Twitch": ["W", "R", "Q", "E"],  # W poison stacks, R AD buff, E detonates
    "Vayne": ["R", "Q", "W", "E"],  # R bonus-AD buff first
}

# Edge kinds that mean "setup before burst" / "consume after setup".
_SETUP_FANOUT_KINDS = {"shred", "buff", "cc_setup", "amp", "recast", "mark_applier"}


@pytest.fixture(scope="session")
def champion_by_name():
    champions = fetch_champion_data()
    return {data.get("name"): data for data in champions.values()}


@pytest.fixture(scope="session")
def items_by_name():
    return {data["name"]: data for data in fetch_item_data().values()}


def _parse(champion_data, level, items, items_by_name, champion_options=None):
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.stats import calculate_total_stats

    build = [items_by_name[n] for n in (items or ()) if n in items_by_name]
    stats = calculate_total_stats(champion_data, level, build)
    return parse_champion_abilities(
        champion_data,
        level,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
        champion_options=champion_options,
    )


def _resolve(champion_data, parsed, certified_order=None, champion_options=None):
    return resolve_cast_order(
        champion_data.get("name", ""),
        parsed,
        champion_data=champion_data,
        certified_order=certified_order,
        champion_options=champion_options,
    )


def _slot_options(champion_name):
    """``slot -> option keys`` from the PUBLIC rotation accessor.

    The same authoritative declaration the resolver consumes, so
    production and tests cannot drift (issue #145: the old shared
    ``_CONSUME_OPTIONS`` allowlist is gone).
    """
    from src.calculator.champions import (
        get_champion_option_rotation,
        get_champion_options_meta,
    )

    meta = get_champion_options_meta(champion_name)
    rotations = get_champion_option_rotation(champion_name)
    slot_options = {}
    for opt in meta.get("options", []):
        key = str(opt.get("key", ""))
        decl = rotations.get(key)
        if not decl or decl.get("role") not in ("setup", "consume", "execute"):
            continue
        slot = decl.get("slot")
        if slot:
            slot_options.setdefault(slot, []).append(key)
        else:
            slot_options.setdefault("__all__", []).append(key)
    return slot_options


def _resolved(champion_data, parsed):
    """The resolver's one detect→merge surface: ``(edges, receipt)``."""
    name = champion_data.get("name", "")
    return resolved_edges(name, parsed, champion_data, _slot_options(name))


def _detect_edges(champion_name, champion_data, parsed):
    """Re-run the resolver's own edge detector (mirrors the derive path)."""
    return detect_setup_consume_edges(
        champion_name, parsed, champion_data, _slot_options(champion_name)
    )


def _base_order(champion_name, parsed):
    certified = get_champion_cast_order(champion_name)
    return [
        s
        for s in (certified or ["Q", "Q2", "W", "E", "R"])
        if isinstance(parsed.get(s), dict)
    ]


def _edges_to_slot_pairs(edges):
    return {(e.setup, e.consume) for e in edges}


def _edge_kinds(edges):
    return sorted({e.kind for e in edges})


# ---------------------------------------------------------------------------
# (d) the verified seeds stay as documented overrides
# ---------------------------------------------------------------------------


class TestOverrideSeeds:
    def test_table_holds_exactly_the_verified_seeds(self) -> None:
        assert set(COMBO_TABLE) == set(_OVERRIDE_CHAMPIONS)

    def test_seed_rules_are_not_marked_derived(self) -> None:
        for name, rule in COMBO_TABLE.items():
            assert rule.derived is False, f"{name} is a curated seed, not derived"
            assert rule.sources, f"{name} seed has no sourced atoms"

    def test_seed_orders_win_over_the_algorithm(self, champion_by_name) -> None:
        """The table is checked FIRST — the derived path never touches seeds."""
        for name in _OVERRIDE_CHAMPIONS:
            parsed = _parse(champion_by_name[name], 11, (), {})
            order, rule = _resolve(champion_by_name[name], parsed)
            assert rule is not None and rule.derived is False
            assert order == list(COMBO_TABLE[name].order)


# ---------------------------------------------------------------------------
# (a) edge invariants — every champion, every detected edge
# ---------------------------------------------------------------------------


class TestEdgeInvariants:
    def test_derived_orders_never_violate_a_detected_edge(
        self, champion_by_name, items_by_name
    ) -> None:
        """For every NON-override champion the algorithmic order satisfies
        every detected setup→consume edge (setup casts before its consume)."""
        violations = []
        for name in sorted(champion_by_name):
            if name in COMBO_TABLE:
                continue
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            order, rule = _resolve(
                data, parsed, certified_order=get_champion_cast_order(name)
            )
            assert rule is not None and rule.derived, f"{name} should be derived"
            edges = _detect_edges(name, data, parsed)
            if not edges:
                continue
            pos = {slot: index for index, slot in enumerate(order)}
            for edge in edges:
                if (
                    edge.setup in pos
                    and edge.consume in pos
                    and pos[edge.setup] > pos[edge.consume]
                ):
                    violations.append(
                        (name, edge.setup, edge.consume, edge.kind, order)
                    )
        assert (
            violations == []
        ), "derived order violates detected setup/consume edges: " + repr(
            violations[:10]
        )

    def test_override_seeds_satisfy_detected_edges_except_documented_exceptions(
        self, champion_by_name, items_by_name
    ) -> None:
        """The verified seeds are truth; where a seed deviates from a data
        edge it is a DOCUMENTED exception with the seed's own judgment."""
        for name in _OVERRIDE_CHAMPIONS:
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            order = list(COMBO_TABLE[name].order)
            edges = _detect_edges(name, data, parsed)
            pos = {slot: index for index, slot in enumerate(order)}
            exceptions = _OVERRIDE_SEED_EXCEPTIONS.get(name, set())
            violated = [
                (e.setup, e.consume, e.kind)
                for e in edges
                if e.setup in pos
                and e.consume in pos
                and pos[e.setup] > pos[e.consume]
                and (e.setup, e.consume) not in exceptions
            ]
            assert violated == [], f"{name} seed violates edges {violated}"

    def test_edge_kind_taxonomy_is_closed(
        self, champion_by_name, items_by_name
    ) -> None:
        """Every edge the detector emits belongs to the documented taxonomy.

        The vocabulary is read from ``cast_dependency``, never retyped: a
        second copy here would keep passing after the leaf's set changed,
        which is the whole failure this campaign audits for.  Set equality
        against what the detector *can* emit is asserted at its source in
        ``tests/test_cast_dependency.py``; this walk asserts the roster
        stays inside it.
        """
        allowed = INFERRED_EDGE_KINDS
        assert not allowed & DEPENDENCY_KINDS
        observed = set()
        for name in sorted(champion_by_name):
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            for edge in _detect_edges(name, data, parsed):
                observed.add(edge.kind)
                assert edge.kind in allowed, f"{name}: unknown edge kind {edge.kind}"
                assert (
                    edge.kind not in DEPENDENCY_KINDS
                ), f"{name}: inferred edge wears a declared kind {edge.kind}"
                assert edge.setup != edge.consume, f"{name}: self edge"
                assert edge.setup in {
                    "Q",
                    "Q2",
                    "W",
                    "E",
                    "R",
                }, f"{name}: bad setup {edge.setup}"
                assert edge.consume in {
                    "Q",
                    "Q2",
                    "W",
                    "E",
                    "R",
                }, f"{name}: bad consume {edge.consume}"
        assert observed, "the roster walk detected no edges at all"

    def test_setup_consume_receipt_matches_detected_edges(
        self, champion_by_name, items_by_name
    ) -> None:
        """The machine-readable setup/consume lists on the derived rule cover
        every edge endpoint that appears in the cast order."""
        for name in sorted(champion_by_name):
            if name in COMBO_TABLE:
                continue
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            order, rule = _resolve(
                data, parsed, certified_order=get_champion_cast_order(name)
            )
            edges = _detect_edges(name, data, parsed)
            present = set(order)
            for edge in edges:
                if edge.setup in present and edge.consume in present:
                    assert (
                        edge.setup in rule.setup
                    ), f"{name}: {edge.setup} missing from setup"
                    assert (
                        edge.consume in rule.consume
                    ), f"{name}: {edge.consume} missing from consume"


# ---------------------------------------------------------------------------
# (b) rationale cites real atoms
# ---------------------------------------------------------------------------


class TestRationaleCitesAtoms:
    def test_signal_champions_cite_typed_atoms(
        self, champion_by_name, items_by_name
    ) -> None:
        """A rationale for a signal-bearing champion names the driving atom:
        an option key, a structured attribute, or a parsed atom key."""
        atom_tokens = (
            "option ",
            "attribute ",
            "dot_duration",
            "on_hit",
            "applies_dot_stack",
            "stacking_dot",
            "post_hit_proc",
            "target_debuff",
            "stat_buff",
            "cc_kind",
            "recast",
            "recast_of",
            "per stack",
            "enhanced",
            "missing-health",
            "execute",
            "shred",
            "amplif",
            "mark",
            "poison",
            "stacks",
        )
        for name in sorted(champion_by_name):
            if name in COMBO_TABLE:
                continue
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            order, rule = _resolve(
                data, parsed, certified_order=get_champion_cast_order(name)
            )
            edges = _detect_edges(name, data, parsed)
            if not edges:
                continue
            rationale = rule.rationale.lower()
            sources = " ".join(rule.sources).lower()
            assert any(
                token in rationale or token in sources for token in atom_tokens
            ), f"{name} rationale cites no real atom: {rule.rationale[:200]}"
            assert rule.sources, f"{name} derived rule has no sources"

    def test_flat_champions_say_no_signal_and_keep_base(
        self, champion_by_name, items_by_name
    ) -> None:
        """A champion with NO detectable edge keeps the certified/default
        order and the rationale says exactly that (data-driven, honest)."""
        for name in sorted(champion_by_name):
            if name in COMBO_TABLE:
                continue
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            order, rule = _resolve(
                data, parsed, certified_order=get_champion_cast_order(name)
            )
            edges = _detect_edges(name, data, parsed)
            if edges:
                continue
            assert order == _base_order(
                name, parsed
            ), f"{name}: flat kit should keep base order"
            assert (
                "no detectable setup/consume signal" in rule.rationale
            ), f"{name} flat rationale should say no signal"
            assert rule.setup == () and rule.consume == ()


# ---------------------------------------------------------------------------
# (c) determinism + stability across levels/items
# ---------------------------------------------------------------------------


class TestDeterminismAndStability:
    def test_derivation_is_deterministic(self, champion_by_name, items_by_name) -> None:
        """Same champion + same parse → same order (pure function)."""
        for name in sorted(champion_by_name):
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            first, rule = _resolve(
                data, parsed, certified_order=get_champion_cast_order(name)
            )
            second, _ = _resolve(
                data, parsed, certified_order=get_champion_cast_order(name)
            )
            assert first == second, f"{name} derivation is not deterministic"

    def test_order_stable_across_full_kit_levels_and_builds(
        self, champion_by_name, items_by_name
    ) -> None:
        """Every champion derives the SAME order at L11/L18 across the
        no-items / magic / physical / spellblade builds."""
        unstable = []
        for name in sorted(champion_by_name):
            data = champion_by_name[name]
            orders = []
            for _label, level, build in _MATRIX_BUILDS:
                parsed = _parse(data, level, build, items_by_name)
                order, _rule = _resolve(
                    data, parsed, certified_order=get_champion_cast_order(name)
                )
                orders.append(tuple(order))
            if len(set(orders)) != 1:
                unstable.append((name, orders))
        assert (
            unstable == []
        ), f"orders differ across the level/build matrix: {unstable[:8]}"

    def test_level_one_order_is_restricted_prefix(self, champion_by_name) -> None:
        """At level 1 the kit is partial; the L1 order restricted to its own
        slots matches the full-kit order restricted the same way.  The
        derivation runs against the canonical full kit (the champion's
        mechanic surface is level-invariant), so W's poison-consume edge
        still promotes W above Q for Twitch even before E exists."""
        bad = []
        for name in sorted(champion_by_name):
            data = champion_by_name[name]
            parsed1 = _parse(data, 1, (), {})
            order1, _ = _resolve(
                data, parsed1, certified_order=get_champion_cast_order(name)
            )
            parsed11 = _parse(data, 11, (), {})
            order11, _ = _resolve(
                data, parsed11, certified_order=get_champion_cast_order(name)
            )
            shared = set(order1) & set(order11)
            r1 = tuple(s for s in order1 if s in shared)
            r11 = tuple(s for s in order11 if s in shared)
            if r1 != r11:
                bad.append((name, r1, r11))
        assert bad == [], f"level-1 restricted order differs: {bad}"

    def test_matrix_consistent_dps_orders_are_lockable(
        self, champion_by_name, items_by_name
    ) -> None:
        """The documented derived orders are reproduced by the resolver."""
        for name, expected in _EXPECTED_DERIVED_ORDERS.items():
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            order, rule = _resolve(
                data, parsed, certified_order=get_champion_cast_order(name)
            )
            assert order == expected, f"{name}: derived {order} != expected {expected}"


# ---------------------------------------------------------------------------
# structure: permutation of base slots + counts
# ---------------------------------------------------------------------------


class TestOrderStructure:
    def test_derived_order_is_a_permutation_of_base_slots(
        self, champion_by_name, items_by_name
    ) -> None:
        for name in sorted(champion_by_name):
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            order, rule = _resolve(
                data, parsed, certified_order=get_champion_cast_order(name)
            )
            base = _base_order(name, parsed)
            assert sorted(order) == sorted(
                base
            ), f"{name}: derived order {order} is not a permutation of base {base}"
            assert len(set(order)) == len(order), f"{name}: duplicate slot in order"

    def test_algorithmic_coverage_floors(self, champion_by_name, items_by_name) -> None:
        """The derivation must stay algorithmic: at least 25 champions carry
        detected edges and at least 15 derive a non-base order.  A regression
        back to the default path would break these floors."""
        edge_champions = 0
        nonbase_champions = 0
        for name in sorted(champion_by_name):
            if name in COMBO_TABLE:
                continue
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            order, rule = _resolve(
                data, parsed, certified_order=get_champion_cast_order(name)
            )
            edges = _detect_edges(name, data, parsed)
            if edges:
                edge_champions += 1
            if order != _base_order(name, parsed):
                nonbase_champions += 1
        assert (
            edge_champions >= 25
        ), f"only {edge_champions} champions have detected edges"
        assert (
            nonbase_champions >= 15
        ), f"only {nonbase_champions} derive non-base orders"

    def test_certified_orders_survive_when_edges_agree(
        self, champion_by_name, items_by_name
    ) -> None:
        """Champions with a certified module CAST_ORDER keep it when the data
        confirms it (or shows no signal) — the derivation never discards a
        reviewed order without a data reason."""
        for name in ("Jayce", "Kai'Sa", "Karthus", "Shen", "Taliyah", "Vi"):
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            order, rule = _resolve(
                data, parsed, certified_order=get_champion_cast_order(name)
            )
            certified = get_champion_cast_order(name)
            base = [s for s in certified if isinstance(parsed.get(s), dict)]
            assert (
                order == base
            ), f"{name}: derivation discarded the certified order {base} -> {order}"


# ---------------------------------------------------------------------------
# (e) declared dependencies merged over the inferred edges (Phase 5)
# ---------------------------------------------------------------------------


def _inferred(setup: str, consume: str, kind: str = "cc_setup") -> _Edge:
    """One inferred edge, as the detector would have emitted it."""
    return _Edge(setup, consume, kind, f"{setup} sets up {consume}")


def _declaration(**overrides) -> CastDependency:
    """A synthetic declaration: E requires Q, sourced, no suppression."""
    fields = {
        "slot": "E",
        "requires": "Q",
        "kind": "cc_enabler",
        "reason": "the cone stuns only what the sphere passed through",
        "source": "https://wiki.leagueoflegends.com/en-us/Synthetic@4024662",
    }
    fields.update(overrides)
    return CastDependency(**fields)


def _reverse_suppression(**overrides) -> SuppressedInference:
    """The exact reverse pair of ``_declaration()``, as D-81 requires."""
    fields = {
        "setup": "E",
        "consume": "Q",
        "kind": "cc_setup",
        "reason": "the inference reads the mechanic backwards",
    }
    fields.update(overrides)
    return SuppressedInference(**fields)


_LIVE = {"Q", "W", "E", "R"}


class TestPrecedenceTable:
    """Every row of Phase 5's explicit-vs-inferred precedence table."""

    def test_no_declaration_keeps_the_inference_untouched(self) -> None:
        """Row 1 — today's behaviour, byte-identical (D-85)."""
        inferred = [_inferred("E", "Q"), _inferred("E", "W")]
        edges, receipt = merge_declared_edges("Synthetic", inferred, (), _LIVE)
        assert edges == inferred
        assert receipt == DependencyReceipt()
        assert {edge.origin for edge in edges} == {"inferred"}

    def test_a_declaration_with_no_inference_becomes_an_edge(self) -> None:
        """Row 2 — the declared direction is setup=requires, consume=slot."""
        edges, receipt = merge_declared_edges("Synthetic", [], [_declaration()], _LIVE)
        assert [(e.setup, e.consume, e.kind, e.origin) for e in edges] == [
            ("Q", "E", "cc_enabler", "declared")
        ]
        assert len(receipt.active) == 1
        assert receipt.conflicts == ()

    def test_an_agreeing_inference_is_deduped_and_flagged(self) -> None:
        """Row 3 — one edge, and the receipt says the surfaces agreed."""
        edges, receipt = merge_declared_edges(
            "Synthetic", [_inferred("Q", "E", "mark_consume")], [_declaration()], _LIVE
        )
        assert [(e.setup, e.consume, e.origin) for e in edges] == [
            ("Q", "E", "declared")
        ]
        assert len(receipt.confirmed_by_inference) == 1
        assert "mark_consume" in receipt.confirmed_by_inference[0]

    def test_a_suppressed_opposition_is_dropped_with_a_citation(self) -> None:
        """Row 4 — the reverse edge goes, the receipt cites the suppression."""
        declaration = _declaration(suppresses=(_reverse_suppression(),))
        edges, receipt = merge_declared_edges(
            "Synthetic",
            [_inferred("E", "Q"), _inferred("E", "W")],
            [declaration],
            _LIVE,
        )
        assert [(e.setup, e.consume, e.origin) for e in edges] == [
            ("Q", "E", "declared"),
            ("E", "W", "inferred"),
        ]
        assert "backwards" in receipt.suppressed[0]
        assert len(receipt.conflicts) == 1

    def test_an_uncovered_opposition_raises(self) -> None:
        """Row 5 — D-82: declared-always-wins would settle it silently."""
        with pytest.raises(ConflictingInferenceError) as caught:
            merge_declared_edges(
                "Synthetic", [_inferred("E", "Q")], [_declaration()], _LIVE
            )
        message = str(caught.value)
        assert "cc_setup" in message and "SuppressedInference" in message
        assert "wiki.leagueoflegends.com" in message

    def test_a_suppression_naming_another_kind_does_not_cover(self) -> None:
        """Scope is one ``(setup, consume, kind)`` triple, never a pair."""
        declaration = _declaration(
            suppresses=(_reverse_suppression(kind="amp", latent_reason="not here"),)
        )
        with pytest.raises(ConflictingInferenceError):
            merge_declared_edges(
                "Synthetic", [_inferred("E", "Q")], [declaration], _LIVE
            )

    def test_a_suppression_matching_nothing_must_say_why(self) -> None:
        """Row 6 — a latent suppression is a claim about an absent inference."""
        declaration = _declaration(suppresses=(_reverse_suppression(),))
        with pytest.raises(MissingLatentReasonError) as caught:
            merge_declared_edges("Synthetic", [], [declaration], _LIVE)
        assert "latent_reason" in str(caught.value)

    def test_a_declared_latent_suppression_is_recorded(self) -> None:
        declaration = _declaration(
            suppresses=(_reverse_suppression(latent_reason="Q2 has no cooldown"),)
        )
        _, receipt = merge_declared_edges("Synthetic", [], [declaration], _LIVE)
        assert receipt.latent == ("E -> Q (cc_setup) is latent: Q2 has no cooldown",)

    def test_an_inactive_declaration_constrains_nothing(self) -> None:
        """Active-slot tier 2: the receipt names the absent endpoint."""
        declaration = _declaration(requires="Q2", suppresses=(_reverse_suppression(),))
        edges, receipt = merge_declared_edges(
            "Synthetic", [_inferred("E", "W")], [declaration], _LIVE
        )
        assert [(e.setup, e.consume) for e in edges] == [("E", "W")]
        assert receipt.active == ()
        assert "Q2 not in this parse" in receipt.inactive[0]

    def test_an_inactive_declarations_suppression_is_inert(self) -> None:
        """You may not suppress an inference while the declaration is dead."""
        declaration = _declaration(requires="Q2", suppresses=(_reverse_suppression(),))
        edges, receipt = merge_declared_edges(
            "Synthetic", [_inferred("E", "Q2")], [declaration], _LIVE
        )
        assert [(e.setup, e.consume) for e in edges] == [("E", "Q2")]
        assert receipt.suppressed == () and receipt.latent == ()


class TestResolvedEdgesIsTheOneSurface:
    """Production and the suites read the same detect-then-merge function."""

    def test_syndra_merges_her_declarations_over_the_fan_out(
        self, champion_by_name
    ) -> None:
        data = champion_by_name["Syndra"]
        parsed = _parse(data, 18, (), {}, champion_options={"splinters": 120})
        edges, receipt = _resolved(data, parsed)
        assert [
            (e.setup, e.consume, e.origin) for e in edges if e.origin == "declared"
        ] == [("Q", "E", "declared"), ("Q2", "E", "declared")]
        assert ("E", "Q") not in _edges_to_slot_pairs(edges)
        assert len(receipt.active) == 2
        assert len(receipt.suppressed) == 1
        assert len(receipt.latent) == 1

    def test_below_forty_splinters_the_recast_declaration_goes_inactive(
        self, champion_by_name
    ) -> None:
        data = champion_by_name["Syndra"]
        parsed = _parse(data, 18, (), {}, champion_options={"splinters": 39})
        edges, receipt = _resolved(data, parsed)
        assert [(e.setup, e.consume) for e in edges if e.origin == "declared"] == [
            ("Q", "E")
        ]
        assert len(receipt.inactive) == 1
        assert receipt.latent == ()

    def test_the_head_only_declarers_add_edges_and_oppose_nothing(
        self, champion_by_name
    ) -> None:
        expected = {"Zed": {("W", "Q"), ("W", "E")}, "Brand": {("Q", "W")}}
        for name, pairs in expected.items():
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), {})
            edges, receipt = _resolved(data, parsed)
            declared = {(e.setup, e.consume) for e in edges if e.origin == "declared"}
            assert declared == pairs
            assert receipt.conflicts == () and receipt.suppressed == ()

    def test_every_merged_edge_names_its_surface(
        self, champion_by_name, items_by_name
    ) -> None:
        """Criterion 2, over the whole roster: origin is closed, and the two
        kind vocabularies stay on their own side of it."""
        for name in sorted(champion_by_name):
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            edges, _ = _resolved(data, parsed)
            for edge in edges:
                assert edge.origin in {"declared", "inferred"}
                if edge.origin == "declared":
                    assert edge.kind in DEPENDENCY_KINDS
                else:
                    assert edge.kind in INFERRED_EDGE_KINDS

    def test_a_non_declaring_champion_gets_the_detectors_edges_verbatim(
        self, champion_by_name, items_by_name
    ) -> None:
        """D-85 behaviourally: 170 modules reach the merge and pass through."""
        for name in ("Ahri", "Cassiopeia", "Ezreal", "Pantheon", "Riven"):
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            edges, receipt = _resolved(data, parsed)
            assert list(edges) == detect_setup_consume_edges(
                name, parsed, data, _slot_options(name)
            )
            assert receipt == DependencyReceipt()
