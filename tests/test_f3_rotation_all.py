"""Algorithmic optimal-order derivation, for every registered champion.

:func:`src.calculator.rotation_resolver.derive_champion_rule` computes a
champion's cast order on the fly from the atomized ability data — typed
parsed atoms (``dot_duration``, ``on_hit``, ``applies_dot_stack``,
``post_hit_proc``, ``target_debuff``, ``stat_buff``, ``cc_kind``),
module OPTION rotation declarations (``target_poisoned``,
``blight_stacks``, ``p_illumination_procs``, ``moonlight_reset``, ...),
and the structured wiki attribute rows.  The hand seeds it defers to, and
the receipt the resolver publishes, are ``tests/test_f2_rotation.py``'s.

This suite asserts the combo invariants for EVERY champion:

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

from dataclasses import replace

import pytest

from src.calculator import data_registry
from src.calculator.cast_dependency import (
    DEPENDENCY_KINDS,
    INFERRED_EDGE_KINDS,
    CastDependency,
    ConflictingInferenceError,
    MissingLatentReasonError,
    ResolvedCycleError,
    SuppressedInference,
)
from src.calculator.champions import get_champion_cast_order
from src.calculator.data_fetcher import fetch_champion_data, fetch_item_data
from src.calculator.data_registry import data_version
from src.calculator.rotation_resolver import (
    CAST_ORDER_OVERRIDES,
    _DERIVED_RULE_CACHE,
    _MATRIX_DPS_CACHE,
    _PRE_CAMPAIGN_CC_ORDERING,
    DependencyReceipt,
    _Edge,
    derive_champion_rule,
    detect_setup_consume_edges,
    merge_declared_edges,
    resolve_cast_order,
    resolved_edges,
)

# Documented seed exceptions: the verified F2 seed deliberately deviates
# from a data edge (the seed's judgment wins; each is justified in the
# seed's own rationale).
#   - Cassiopeia: W (Miasma) also applies poison, so the data says W→E,
#     but the seed casts E before W to start the 0.75s spam cadence
#     earlier on the shared timeline (W is zoning, Q is the poison).
#   - Varus: R applies Blight stacks, so the data says R→Q, but the seed
#     puts the Blight DETONATOR Q first (the auto-applied stacks ride Q;
#     R's own stacks land later in the burst).
# Syndra's two entries are gone (D-84): E's authored stun made the generic
# cc-setup fan-out say E→Q, and the seed's judgment was written down here
# where nothing could check it. Her module now DECLARES that E requires the
# sphere and nests the suppression that says the inference reads the
# mechanic backwards, so the merge drops the edge and there is no
# exception left to document. The ("E","Q2") half was vacuous besides —
# no such edge exists, which is the fact her suppression's latent_reason
# now carries where the audit can see it.
_OVERRIDE_SEED_EXCEPTIONS = {
    "Cassiopeia": {("W", "E")},
    "Varus": {("R", "Q")},
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
    # Retired seed (D-89): R's bonus-AD stat_buff is a detected edge to Q
    # and W, so the derivation puts World Ender first on its own.
    "Aatrox": ["R", "Q", "W"],
    # Retired seed (D-89): no edge is detected at all, so the certified
    # order survives untouched — the flat-kit path, honestly labelled.
    "Jhin": ["Q", "W", "E", "R"],
    # Retired seed (D-89): same flat-kit path as Jhin's.
    "Aphelios": ["Q", "W", "R"],
    # Syndra's retired seed (D-89): E requires Q and E requires Q2, declared
    # by her module, derive the order the hand seed used to pin.
    "Syndra": ["Q", "Q2", "E", "W", "R"],
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
    """The ordering constraints the derivation runs under.

    Reads ``resolved_edges`` — the resolver's own detect→merge surface —
    so a suite can never assert against a set of edges production does
    not use.
    """
    return list(
        resolved_edges(
            champion_name, parsed, champion_data, _slot_options(champion_name)
        )[0]
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
    """Which champions seed, and why, is stated once in
    ``tests/test_f2_rotation.py``; this suite asks only what the derivation
    does when it meets one."""

    def test_seed_rules_are_not_marked_derived(self) -> None:
        for name, rule in CAST_ORDER_OVERRIDES.items():
            assert rule.derived is False, f"{name} is a curated seed, not derived"
            assert rule.sources, f"{name} seed has no sourced atoms"

    def test_seed_orders_win_over_the_algorithm(self, champion_by_name) -> None:
        """The table is checked FIRST — the derived path never touches seeds."""
        for name in CAST_ORDER_OVERRIDES:
            parsed = _parse(champion_by_name[name], 11, (), {})
            order, rule = _resolve(champion_by_name[name], parsed)
            assert rule is not None and rule.derived is False
            assert order == list(CAST_ORDER_OVERRIDES[name].order)


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
            if name in CAST_ORDER_OVERRIDES:
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
        for name in CAST_ORDER_OVERRIDES:
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            order = list(CAST_ORDER_OVERRIDES[name].order)
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
                if edge.origin == "declared":
                    assert (
                        edge.kind in DEPENDENCY_KINDS
                    ), f"{name}: declared edge wears an inferred kind {edge.kind}"
                    continue
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
            if name in CAST_ORDER_OVERRIDES:
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

    def test_no_module_authored_kit_fact_orders_a_rotation(
        self, champion_by_name, items_by_name
    ) -> None:
        """Roster-wide: a module's crowd control constrains no cast order.

        A champion module recording its reviewed crowd control states what
        a cast APPLIES, whether it says so per slot in ``MODULE_CC`` or on
        the part at its construction site.  Ordering stays with the
        declared ``CAST_DEPENDENCIES`` vocabulary, so the only ``cc_setup``
        edges left on the roster are the closed pre-rule table's — checked
        here, over every champion, so the next kit to record a slow cannot
        quietly reorder its rotation.
        """
        unearned = []
        for name in sorted(champion_by_name):
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            pinned = _PRE_CAMPAIGN_CC_ORDERING.get(name, frozenset())
            for edge in _detect_edges(name, data, parsed):
                if edge.kind != "cc_setup" or edge.origin == "declared":
                    continue
                if edge.setup not in pinned:
                    unearned.append((name, edge.setup, edge.consume))
        assert unearned == [], "module crowd control fanned ordering edges: " + repr(
            unearned[:10]
        )

    def test_the_pinned_pre_rule_slots_are_the_only_cc_orderers(
        self, champion_by_name, items_by_name
    ) -> None:
        """The other half: every pinned entry still earns its place.

        A pin that stopped producing its edge would be a permanent
        exemption for an inference nobody can see — the shape the
        suppression ledger's ``latent_reason`` exists to refuse.
        """
        earning = set()
        for name, slots in _PRE_CAMPAIGN_CC_ORDERING.items():
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), items_by_name)
            edges = _detect_edges(name, data, parsed)
            for slot in slots:
                marks = {
                    part.cc_kind
                    for part in parsed[slot].get("parts", ())
                    if part.cc_kind
                }
                assert marks - {
                    "none"
                }, f"{name} {slot} no longer records a crowd-control kind"
                if any(e.kind == "cc_setup" and e.setup == slot for e in edges):
                    earning.add((name, slot))
        assert earning == {
            (name, slot)
            for name, slots in _PRE_CAMPAIGN_CC_ORDERING.items()
            for slot in slots
        }


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
            if name in CAST_ORDER_OVERRIDES:
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
            if name in CAST_ORDER_OVERRIDES:
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
        """The derivation must stay algorithmic: at least 32 champions carry
        detected edges and at least 21 derive a non-base order.  A regression
        back to the default path would break these floors.

        The floors are re-measured whenever a retirement changes the counted
        population — the walk skips seeded champions, so retiring a seed adds
        that champion to it — and they move UP only.  D-89's four retirements
        added Syndra and Aatrox to both counts (Jhin and Aphelios derive by
        the flat-kit path, so they enter the population without raising
        either floor), taking 25 -> 32 and 15 -> 21.  A floor lowered to make
        a red suite green would turn the one check that says "the derivation
        is still doing the work" into a check that says nothing.
        """
        edge_champions = 0
        nonbase_champions = 0
        for name in sorted(champion_by_name):
            if name in CAST_ORDER_OVERRIDES:
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
            edge_champions >= 32
        ), f"only {edge_champions} champions have detected edges"
        assert (
            nonbase_champions >= 21
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


# Syndra's certified splinter axis, split by whether Q2 is in the parse.
# Below forty the second charge does not exist, so the recast declaration
# is inactive and its suppression is inert with it.
_SYNDRA_Q2_LIVE = (
    (11, 40),
    (11, 60),
    (11, 120),
    (18, 40),
    (18, 60),
    (18, 119),
    (18, 120),
)
_SYNDRA_Q2_ABSENT = ((11, 0), (11, 39), (18, 0), (18, 39))


def _syndra_declarations(**stripped):
    """Syndra's real declarations, with one of them replaced.

    ``stripped`` maps a ``requires`` slot to the replacement kwargs, so a
    test says "her E-requires-Q declaration, minus its suppression" and
    keeps every other field the module authored.  Rebuilding the
    declaration by hand instead would test a fixture, which is exactly
    what the synthetic negatives already do.
    """
    from src.calculator.champions import get_champion_cast_dependencies

    return tuple(
        replace(dep, **stripped[dep.requires]) if dep.requires in stripped else dep
        for dep in get_champion_cast_dependencies("Syndra")
    )


def _syndra_merge(champion_data, level, splinters, declarations):
    """One merge of *declarations* over the edges Syndra really produces."""
    parsed = _parse(
        champion_data, level, (), {}, champion_options={"splinters": splinters}
    )
    return resolved_edges(
        "Syndra", parsed, champion_data, _slot_options("Syndra"), declarations
    )


class TestSyndrasSuppressionsAreLoadBearing:
    """Criterion 4's Syndra clause, against the real declarations.

    Every ``ConflictingInferenceError`` negative in this suite was
    synthetic — a hand-built declaration meeting a hand-built edge.  That
    proves the merge raises; it does not prove that Syndra's own
    suppression is what holds her own conflict down, which is the claim
    the criterion makes and the one a broadened or deleted suppression
    would falsify.

    Her two suppressions are not symmetric, and criterion 4's original
    "either" could not be honoured as written.  ``E requires Q`` is
    **matched**: the detector's ``cc_setup`` fan-out really does emit
    ``E -> Q``, so removing the suppression is a direct red.  ``E requires
    Q2`` is **latent** by D-84 — ``_castable()`` wants ``cooldown > 0``
    and Q2 carries the ``0.0`` cast-exactly-once cooldown, so no
    ``E -> Q2`` edge can exist and no removal can ever raise here.  Its
    evidence is the other half of that same fact, and it is stricter than
    a raise-on-removal: the latency is measured in every certified state,
    and clearing the ``latent_reason`` makes the merge refuse the
    unexplained claim rather than carry it.
    """

    @pytest.mark.parametrize("level,splinters", _SYNDRA_Q2_LIVE + _SYNDRA_Q2_ABSENT)
    def test_the_opposing_inference_is_one_syndra_really_produces(
        self, champion_by_name, level, splinters
    ) -> None:
        """The premise: E -> Q cc_setup is in the detector's own output."""
        data = champion_by_name["Syndra"]
        parsed = _parse(data, level, (), {}, champion_options={"splinters": splinters})
        inferred = detect_setup_consume_edges(
            "Syndra", parsed, data, _slot_options("Syndra")
        )
        assert ("E", "Q", "cc_setup") in {
            (e.setup, e.consume, e.kind) for e in inferred
        }

    @pytest.mark.parametrize("level,splinters", _SYNDRA_Q2_LIVE + _SYNDRA_Q2_ABSENT)
    def test_removing_the_matched_suppression_raises(
        self, champion_by_name, level, splinters
    ) -> None:
        """D-82 on the live surface: the two surfaces disagree, loudly."""
        declarations = _syndra_declarations(Q={"suppresses": ()})
        with pytest.raises(ConflictingInferenceError) as caught:
            _syndra_merge(champion_by_name["Syndra"], level, splinters, declarations)
        message = str(caught.value)
        assert "Syndra: the detector infers E -> Q (cc_setup" in message
        assert "E requires Q (declared cc_enabler)" in message
        assert "wiki.leagueoflegends.com/en-us/Syndra@" in message

    @pytest.mark.parametrize("level,splinters", _SYNDRA_Q2_LIVE + _SYNDRA_Q2_ABSENT)
    def test_the_real_declarations_raise_nothing(
        self, champion_by_name, level, splinters
    ) -> None:
        """The control: the raise is the removal's, not the state's."""
        edges, receipt = _syndra_merge(
            champion_by_name["Syndra"], level, splinters, _syndra_declarations()
        )
        assert ("E", "Q") not in _edges_to_slot_pairs(edges)
        assert len(receipt.suppressed) == 1

    @pytest.mark.parametrize("level,splinters", _SYNDRA_Q2_LIVE + _SYNDRA_Q2_ABSENT)
    def test_no_inference_opposes_the_recast_declaration_anywhere(
        self, champion_by_name, level, splinters
    ) -> None:
        """D-84 measured, not quoted: the E -> Q2 edge exists in no state."""
        data = champion_by_name["Syndra"]
        parsed = _parse(data, level, (), {}, champion_options={"splinters": splinters})
        inferred = detect_setup_consume_edges(
            "Syndra", parsed, data, _slot_options("Syndra")
        )
        assert ("E", "Q2") not in {(e.setup, e.consume) for e in inferred}

    @pytest.mark.parametrize("level,splinters", _SYNDRA_Q2_LIVE)
    def test_clearing_the_latent_reason_refuses_the_unexplained_claim(
        self, champion_by_name, level, splinters
    ) -> None:
        """The latent half's red: a suppression matching nothing must say why.

        This is what removal cannot test.  The suppression is live and
        active — its parent declaration is active wherever Q2 is — and
        the merge still finds it matched no inferred edge, which is D-84's
        claim proven by the merge rather than asserted by the module.
        """
        suppression = _syndra_declarations()[1].suppresses[0]
        declarations = _syndra_declarations(
            Q2={"suppresses": (replace(suppression, latent_reason=None),)}
        )
        with pytest.raises(MissingLatentReasonError) as caught:
            _syndra_merge(champion_by_name["Syndra"], level, splinters, declarations)
        assert "E -> Q2 (cc_setup) matched no inferred edge" in str(caught.value)

    @pytest.mark.parametrize("level,splinters", _SYNDRA_Q2_LIVE)
    def test_removing_the_latent_suppression_is_inert(
        self, champion_by_name, level, splinters
    ) -> None:
        """And why criterion 4's "either" was half-undischargeable.

        Nothing opposes ``E requires Q2``, so dropping its suppression
        raises nothing and moves no edge — only the latent receipt row it
        published goes with it.
        """
        data = champion_by_name["Syndra"]
        real_edges, real_receipt = _syndra_merge(
            data, level, splinters, _syndra_declarations()
        )
        edges, receipt = _syndra_merge(
            data, level, splinters, _syndra_declarations(Q2={"suppresses": ()})
        )
        assert list(edges) == list(real_edges)
        assert len(real_receipt.latent) == 1 and receipt.latent == ()
        assert replace(receipt, latent=real_receipt.latent) == real_receipt


class TestTheDerivationReadsDeclarations:
    """The merge is what ``derive_champion_rule`` orders against."""

    def test_syndra_derives_her_seed_order_from_the_declaration(
        self, champion_by_name
    ) -> None:
        """Q, Q2, E, W, R — the order her hand seed pins, now derived.

        Without the declaration the cc-setup fan-out opens with a
        sphere-less E; this is the retirement candidate's proof (D-89),
        asserted while the seed is still live (P5-e).
        """
        data = champion_by_name["Syndra"]
        for level in (11, 18):
            for splinters in (40, 60, 119, 120):
                parsed = _parse(
                    data, level, (), {}, champion_options={"splinters": splinters}
                )
                rule = derive_champion_rule(
                    "Syndra", parsed, data, get_champion_cast_order("Syndra")
                )
                assert list(rule.order) == [
                    "Q",
                    "Q2",
                    "E",
                    "W",
                    "R",
                ], f"L{level} at {splinters} splinters derives {rule.order}"

    def test_below_forty_splinters_she_derives_the_three_slot_order(
        self, champion_by_name
    ) -> None:
        data = champion_by_name["Syndra"]
        for splinters in (0, 39):
            parsed = _parse(data, 18, (), {}, champion_options={"splinters": splinters})
            rule = derive_champion_rule(
                "Syndra", parsed, data, get_champion_cast_order("Syndra")
            )
            assert list(rule.order) == ["Q", "E", "W", "R"]

    def test_the_declaring_champions_merge_reports_their_declarations(
        self, champion_by_name
    ) -> None:
        """The merge receipt ``scripts/cast_dependency_audit.py`` joins on."""
        for name in ("Syndra", "Zed", "Brand"):
            data = champion_by_name[name]
            parsed = _parse(data, 11, (), {})
            _edges, receipt = _resolved(data, parsed)
            assert receipt.active, f"{name} merged with no active row"

    def test_a_declared_cycle_in_a_live_parse_raises(
        self, champion_by_name, monkeypatch
    ) -> None:
        """A declaring champion never falls back from a cycle (D-85).

        Ahri declares nothing; with two declarations that oppose each
        other in a parse where both slots are live, no order satisfies
        the module, and serving the base order would be exactly the
        silent fallback this phase exists to end.
        """
        from src.calculator import champions as champions_module

        cycle = (
            CastDependency(
                slot="W",
                requires="R",
                kind="damage_enabler",
                reason="synthetic",
                source="https://wiki.leagueoflegends.com/en-us/Ahri@4024662",
            ),
            CastDependency(
                slot="R",
                requires="W",
                kind="damage_enabler",
                reason="synthetic",
                source="https://wiki.leagueoflegends.com/en-us/Ahri@4024662",
            ),
        )
        monkeypatch.setattr(
            champions_module, "get_champion_cast_dependencies", lambda name: cycle
        )
        _DERIVED_RULE_CACHE.clear()
        data = champion_by_name["Ahri"]
        parsed = _parse(data, 11, (), {})
        try:
            with pytest.raises(ResolvedCycleError) as caught:
                derive_champion_rule(
                    "Ahri", parsed, data, get_champion_cast_order("Ahri")
                )
        finally:
            _DERIVED_RULE_CACHE.clear()
        assert "declared" in str(caught.value)

    def test_the_same_cycle_without_a_declaration_still_falls_back(
        self, champion_by_name
    ) -> None:
        """The 170 keep the silent fallback — that is what D-85 buys."""
        data = champion_by_name["Ahri"]
        parsed = _parse(data, 11, (), {})
        rule = derive_champion_rule(
            "Ahri", parsed, data, get_champion_cast_order("Ahri")
        )
        assert rule.derived and rule.order


# Two requests for one champion that the memo key cannot tell apart, per
# row: ``(champion, narrow, wide)`` where a parse spec is ``(level,
# options)``.  The key is ``(champion, option signature, data version)``, so
# BOTH axes below collapse onto one cache row — the option axis whenever a
# caller does not thread ``champion_options`` (the roster path does not),
# and the LEVEL axis always, because no level component exists in the key at
# all.  The level axis is the wide one: emulating the pre-fix store (cache
# the fitted rule) and warming at level 1 changes the level-18 order for 54
# of the 173 cached champions, 50 of them unseeded and therefore reachable
# through ``resolve_cast_order`` today.  Ahri and Pantheon are two of those
# 50, and neither declares a dependency — the defect is kit-wide and has
# nothing to do with declarations or splinters.
_MEMO_CROSS_TALK = (
    ("Syndra", (18, {"splinters": 39}), (18, {"splinters": 120})),
    ("Syndra", (1, None), (18, None)),
    ("Ahri", (1, None), (18, None)),
    ("Pantheon", (1, None), (18, None)),
)


class TestTheDerivedMemoHoldsTheFullKitRule:
    """A memoised rule must be the full-kit derivation, never one fight's fit.

    ``_fit_rule_to_fight`` narrows the full-kit order to the slots a
    particular parse holds, and it is applied on both the cold and the warm
    path exactly so the answer does not depend on cache warmth.  Storing the
    *narrowed* rule defeats that: whichever request arrives first decides
    what every later one is served, and nothing in the response says the
    order was derived for a differently shaped fight.

    Two axes reach it, and ``_MEMO_CROSS_TALK`` carries rows for both.  A
    Syndra priced below 40 splinters caches an order with no second charge,
    and the next 120-splinter request gets ``Q2`` appended after ``R``
    instead of riding its parent.  A champion priced at level 1 caches an
    order over the one or two slots that parse holds, and the next level-18
    request gets the rest of the kit appended in fallback order — which is
    the larger half of the defect, because the memo key holds no level
    component for any champion.
    """

    @staticmethod
    def _rule(champion, data, spec):
        """The derived rule for one request spec, against a warm cache."""
        level, options = spec
        parsed = _parse(data, level, (), {}, champion_options=options)
        return derive_champion_rule(
            champion,
            parsed,
            data,
            get_champion_cast_order(champion),
        )

    @pytest.mark.parametrize(("champion", "narrow", "wide"), _MEMO_CROSS_TALK)
    def test_the_two_requests_really_do_differ_in_shape(
        self, champion, narrow, wide, champion_by_name
    ) -> None:
        """Guard the guard: a row whose two requests agree tests nothing."""
        data = champion_by_name[champion]
        try:
            _DERIVED_RULE_CACHE.clear()
            narrow_cold = self._rule(champion, data, narrow)
            _DERIVED_RULE_CACHE.clear()
            wide_cold = self._rule(champion, data, wide)
        finally:
            _DERIVED_RULE_CACHE.clear()
        assert set(narrow_cold.order) < set(wide_cold.order)

    @pytest.mark.parametrize(("champion", "narrow", "wide"), _MEMO_CROSS_TALK)
    def test_a_narrow_parse_does_not_poison_a_wider_one(
        self, champion, narrow, wide, champion_by_name
    ) -> None:
        data = champion_by_name[champion]
        try:
            _DERIVED_RULE_CACHE.clear()
            cold = self._rule(champion, data, wide)
            _DERIVED_RULE_CACHE.clear()
            self._rule(champion, data, narrow)
            warm = self._rule(champion, data, wide)
        finally:
            _DERIVED_RULE_CACHE.clear()
        assert list(warm.order) == list(cold.order)

    @pytest.mark.parametrize(("champion", "narrow", "wide"), _MEMO_CROSS_TALK)
    def test_the_wider_parse_does_not_shrink_the_narrower_one(
        self, champion, narrow, wide, champion_by_name
    ) -> None:
        """The other direction: a slot the fight does not hold stays out."""
        data = champion_by_name[champion]
        try:
            _DERIVED_RULE_CACHE.clear()
            cold = self._rule(champion, data, narrow)
            _DERIVED_RULE_CACHE.clear()
            wide_cold = self._rule(champion, data, wide)
            _DERIVED_RULE_CACHE.clear()
            self._rule(champion, data, wide)
            warm = self._rule(champion, data, narrow)
        finally:
            _DERIVED_RULE_CACHE.clear()
        assert list(warm.order) == list(cold.order)
        assert set(warm.order) < set(wide_cold.order)


class TestTheDeclarationProbeStaysOutOfTheMemo:
    """``derive_champion_rule(declarations=...)`` asks a counterfactual.

    "What order would this champion take without this dependency?" is the
    question criterion 12 is made of, and the honest way to ask it is a
    parameter rather than a monkey-patch on the champion package — a
    patched lookup is not the code production runs.  The parameter carries
    one obligation: a probe's answer is about a kit the module does not
    declare, so it must never reach the memo, whose single row per
    (champion, option signature, data version) would then serve it to
    every later request.
    """

    def test_passing_the_module_s_own_declarations_changes_nothing(
        self, champion_by_name
    ) -> None:
        from src.calculator.champions import get_champion_cast_dependencies

        data = champion_by_name["Syndra"]
        parsed = _parse(data, 18, (), {})
        certified = get_champion_cast_order("Syndra")
        try:
            _DERIVED_RULE_CACHE.clear()
            implicit = derive_champion_rule("Syndra", parsed, data, certified)
            _DERIVED_RULE_CACHE.clear()
            explicit = derive_champion_rule(
                "Syndra",
                parsed,
                data,
                certified,
                declarations=get_champion_cast_dependencies("Syndra"),
            )
        finally:
            _DERIVED_RULE_CACHE.clear()
        assert list(explicit.order) == list(implicit.order)
        assert explicit.rationale == implicit.rationale

    def test_a_probe_is_live_and_leaves_no_trace(self, champion_by_name) -> None:
        """A reduced probe answers differently and the memo stays clean."""
        from src.calculator.champions import get_champion_cast_dependencies

        data = champion_by_name["Syndra"]
        parsed = _parse(data, 18, (), {}, champion_options={"splinters": 0})
        certified = get_champion_cast_order("Syndra")
        declared = get_champion_cast_dependencies("Syndra")
        try:
            _DERIVED_RULE_CACHE.clear()
            probe = derive_champion_rule(
                "Syndra",
                parsed,
                data,
                certified,
                {"splinters": 0},
                declarations=(),
            )
            assert _DERIVED_RULE_CACHE == {}, "a probe was memoised"
            real = derive_champion_rule(
                "Syndra", parsed, data, certified, {"splinters": 0}
            )
        finally:
            _DERIVED_RULE_CACHE.clear()
        assert declared, "Syndra declares nothing — this probe proves nothing"
        assert list(probe.order) != list(real.order)


class TestTheRotationMemosInvalidateOnData:
    """D-49: both rotation caches key on ``data_version()``.

    Every value in them is derived from ``data/``, so a mid-process
    refresh must make them miss.  Without the component a patch-day
    refresh serves a cast order derived from pre-patch numbers, which is
    a number no rule computed against the data the response cites.
    """

    def test_both_cache_keys_carry_the_counter(self, champion_by_name) -> None:
        _DERIVED_RULE_CACHE.clear()
        _MATRIX_DPS_CACHE.clear()
        data = champion_by_name["Ahri"]
        parsed = _parse(data, 11, (), {})
        derive_champion_rule("Ahri", parsed, data, get_champion_cast_order("Ahri"))
        version = data_version()
        assert any(key[-1] == version for key in _DERIVED_RULE_CACHE)
        assert any(key[-1] == version for key in _MATRIX_DPS_CACHE)

    def test_a_refresh_is_not_served_a_pre_refresh_order(
        self, champion_by_name, monkeypatch
    ) -> None:
        """Bump the counter and the stale rule cannot be handed back.

        The cached rule is poisoned with an order no derivation produces;
        at the same version it is served (proving the cache is live), and
        after the bump it is gone.
        """
        _DERIVED_RULE_CACHE.clear()
        data = champion_by_name["Ahri"]
        parsed = _parse(data, 11, (), {})
        fresh = derive_champion_rule(
            "Ahri", parsed, data, get_champion_cast_order("Ahri")
        )
        key = next(iter(_DERIVED_RULE_CACHE))
        stale = replace(_DERIVED_RULE_CACHE[key], order=("R", "W", "E", "Q"))
        _DERIVED_RULE_CACHE[key] = stale

        served = derive_champion_rule(
            "Ahri", parsed, data, get_champion_cast_order("Ahri")
        )
        assert list(served.order) == ["R", "W", "E", "Q"], "the memo is not live"

        monkeypatch.setattr(data_registry, "_DATA_VERSION", data_version() + 1)
        after = derive_champion_rule(
            "Ahri", parsed, data, get_champion_cast_order("Ahri")
        )
        assert list(after.order) == list(fresh.order)
        _DERIVED_RULE_CACHE.clear()


# ---------------------------------------------------------------------------
# (f) every declaration earns its place
# ---------------------------------------------------------------------------


# The committed record of which surface would notice if a declaration were
# deleted lives in ``docs/cast-dependency-audit.json`` --
# ``declared_dependency_activation[].load_bearing_routes`` -- beside every
# other declaration-level ledger (R-36).  A disposition kept in a suite is a
# disposition a reader of the receipt cannot see, and this suite is the
# SECOND opinion on it: it re-measures the routes here, over the live tree
# and by different code from the audit's, and asserts the two agree.  The
# audit's own gate compares the receipt against a fresh audit run; this one
# compares the receipt against an independent measurement.
#
#   derived_order          removing it changes the order the derivation
#                          returns (or makes the derivation refuse to
#                          return one) in at least one certified state
#   confirmed_by_inference an inferred edge agrees with it and the merge
#                          receipt says so
#   custom_order_refusal   removing it makes a request order that is
#                          currently refused legal again (D-86)
_DECLARING_CHAMPIONS = ("Syndra", "Zed", "Brand")


def _recorded_routes():
    """``(champion, slot, requires) -> routes`` from the committed receipt."""
    import json
    from pathlib import Path

    receipt = json.loads(
        (
            Path(__file__).resolve().parents[1] / "docs" / "cast-dependency-audit.json"
        ).read_text(encoding="utf-8")
    )
    return {
        (row["champion"], row["slot"], row["requires"]): set(row["load_bearing_routes"])
        for row in receipt["declared_dependency_activation"]
    }


def _without(dependency, declarations):
    """The declaration set minus one member."""
    return tuple(other for other in declarations if other is not dependency)


def _derived_order_route(name, dependency, declarations, champion_data):
    """Does the derived order notice this declaration going away?"""
    from scripts.cast_dependency_audit import option_states

    rest = _without(dependency, declarations)
    certified = get_champion_cast_order(name)

    def order(kept, parsed, options):
        _DERIVED_RULE_CACHE.clear()
        try:
            return list(
                derive_champion_rule(
                    name,
                    parsed,
                    champion_data,
                    certified,
                    options,
                    declarations=kept,
                ).order
            )
        except ResolvedCycleError:
            return None
        finally:
            _DERIVED_RULE_CACHE.clear()

    for _label, options in option_states(name):
        for level in (11, 18):
            parsed = _parse(champion_data, level, (), {}, champion_options=options)
            if order(rest, parsed, options) != order(declarations, parsed, options):
                return True
    return False


def _custom_order_route(name, dependency, declarations, champion_data):
    """Does a currently-illegal request order become legal without it?

    Measured over the same certified option states as the derived-order
    route, because the answer depends on them: below 40 splinters Syndra's
    ``E requires Q2`` is inactive, so ``E requires Q`` is the only thing
    left refusing the sphere-less order.
    """
    from scripts.cast_dependency_audit import option_states
    from src.calculator.cast_dependency import (
        CustomOrderViolatesDependencyError,
        check_order_satisfies_dependencies,
    )

    def refused(order, kept, live):
        try:
            check_order_satisfies_dependencies(order, kept, live)
        except CustomOrderViolatesDependencyError:
            return True
        return False

    for _label, options in option_states(name):
        parsed = _parse(champion_data, 18, (), {}, champion_options=options)
        live = {slot for slot in parsed if slot != "passive"}
        if not {dependency.slot, dependency.requires} <= live:
            continue
        inverted = [dependency.slot, dependency.requires] + [
            slot
            for slot in ("Q", "Q2", "W", "E", "R")
            if slot in live and slot not in (dependency.slot, dependency.requires)
        ]
        if refused(inverted, declarations, live) and not refused(
            inverted, _without(dependency, declarations), live
        ):
            return True
    return False


class TestEveryDeclarationIsLoadBearing:
    """Criterion 12: a declaration nothing would miss is prose in a dataclass.

    Without this the retired seed comes back as declarations with
    plausible wording, every other criterion still passes, and the order
    is as hand-held as it ever was — only now unfalsifiable, because the
    prose sits in a field a validator accepts.

    Zed's and Brand's head-only declarations change no derived order in
    any certified state and no inferred edge agrees with them, so their
    weight is carried entirely by ``custom_order_refusal``: without
    ``Q requires W``, the request order that skips the Shadow placement
    stops being refused (D-86), and an engine that accepts it authors
    damage for a kit Zed cannot cast.  That route is not a softening —
    a declaration on none of the three still fails here and fails the
    audit — and it is recorded per declaration in the committed receipt,
    so which declaration is load-bearing on what is readable without
    running anything.
    """

    def test_the_declaring_champions_are_the_ones_the_receipt_knows(self) -> None:
        """A fourth declarer must arrive with its own route, not silently."""
        from src.calculator.champions import get_champion_cast_dependencies

        declared = {
            (name, dep.slot, dep.requires)
            for name in _DECLARING_CHAMPIONS
            for dep in get_champion_cast_dependencies(name)
        }
        assert declared == set(_recorded_routes())

    def test_no_other_cached_champion_declares(self, champion_by_name) -> None:
        from src.calculator.champions import get_champion_cast_dependencies

        extra = sorted(
            name
            for name in champion_by_name
            if name not in _DECLARING_CHAMPIONS and get_champion_cast_dependencies(name)
        )
        assert extra == []

    def test_the_receipt_records_a_route_for_every_declaration(self) -> None:
        """Criterion 12's claim, read straight off the committed receipt."""
        from scripts.cast_dependency_audit import DECLARATION_ROUTES

        recorded = _recorded_routes()
        assert recorded, "the receipt records no declaration at all"
        for key, routes in recorded.items():
            assert routes, f"{key} is recorded as load-bearing on nothing"
            assert routes <= set(DECLARATION_ROUTES), f"{key} names an unknown route"

    @pytest.mark.parametrize("champion", _DECLARING_CHAMPIONS)
    def test_every_declaration_takes_the_route_the_receipt_records(
        self, champion, champion_by_name
    ) -> None:
        from src.calculator.champions import get_champion_cast_dependencies

        data = champion_by_name[champion]
        declarations = get_champion_cast_dependencies(champion)
        recorded = _recorded_routes()
        for dependency in declarations:
            key = (champion, dependency.slot, dependency.requires)
            routes = set()
            if _derived_order_route(champion, dependency, declarations, data):
                routes.add("derived_order")
            if _custom_order_route(champion, dependency, declarations, data):
                routes.add("custom_order_refusal")
            parsed = _parse(data, 11, (), {})
            _, receipt = _resolved(data, parsed)
            if any(
                f"{dependency.slot} requires {dependency.requires}" in row
                for row in receipt.confirmed_by_inference
            ):
                routes.add("confirmed_by_inference")
            assert routes, (
                f"{key} is load-bearing on nothing: deleting it changes no "
                "derived order, frees no refused request order, and no "
                "inference confirms it"
            )
            assert routes == recorded[key], (
                f"{key} measures {sorted(routes)} here but the committed "
                f"receipt records {sorted(recorded[key])}"
            )
