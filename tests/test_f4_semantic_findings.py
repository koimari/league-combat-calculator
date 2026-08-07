"""F4 — semantic findings locked as regression tests.

One test per semantic finding from the F4 audit of the rotation resolver
(``src/calculator/rotation_resolver.py``).  Each test drives the real
pipeline — cached champion data → ``calculate_total_stats`` →
``parse_champion_abilities`` → ``resolve_cast_order`` /
``detect_setup_consume_edges`` — and pins the derived cast order plus the
specific setup→consume edge kind the audit identified:

- Zed's verified seed order is W → R → E → Q (the F2 combo table wins).
- Darius' E (Apprehend) is only a buff edge; it must NOT masquerade as a
  stack applier, so no E→R ``stack_consume`` edge exists.
- Yone opens with E (Soul Unbound) and its stored damage is consumed by Q.
- Karma opens with R (Mantra) empowering the next ability, e.g. Q.
- Tristana opens with E (Explosive Charge); the charge is a self-setup
  that R detonates (and W rides).
- Nasus and Rumble open with E applying resistance shred consumed by Q.
- Swain opens with E (Nevermove) crowd control before the burst.
- Anivia's Q chills and E's enhanced damage consumes the chilled mark.
- Draven and Veigar close with R as a missing-health execute after Q.
"""

import pytest

from src.calculator.champions import (
    get_champion_cast_order,
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.data_fetcher import fetch_champion_data
from src.calculator.rotation_resolver import (
    COMBO_TABLE,
    _CONSUME_OPTIONS,
    _resolve_option_slot,
    detect_setup_consume_edges,
    resolve_cast_order,
)
from src.calculator.stats import calculate_total_stats


@pytest.fixture(scope="module")
def champion_by_name():
    champions = fetch_champion_data()
    return {data.get("name"): data for data in champions.values()}


def _parse(champion_data, champion_options=None):
    stats = calculate_total_stats(champion_data, 11, [])
    return parse_champion_abilities(
        champion_data,
        11,
        stats["ability_power"],
        ability_ranks=None,
        champion_options=champion_options,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
    )


def _resolve(champion_data, parsed):
    return resolve_cast_order(
        champion_data.get("name", ""),
        parsed,
        champion_data=champion_data,
        certified_order=get_champion_cast_order(champion_data.get("name", "")),
    )[0]


def _edges(champion_name, champion_data, parsed):
    """Re-run the resolver's own edge detector (mirrors the derive path)."""
    meta = get_champion_options_meta(champion_name)
    slot_options = {}
    for opt in meta.get("options", []):
        key = str(opt.get("key", ""))
        if key not in _CONSUME_OPTIONS:
            continue
        slot = _resolve_option_slot(champion_name, key, parsed)
        slot_options.setdefault(slot or "__all__", []).append(key)
    return detect_setup_consume_edges(
        champion_name, parsed, champion_data, slot_options
    )


def _has_edge(edges, setup, consume, kind):
    return any(
        e.setup == setup and e.consume == consume and e.kind == kind for e in edges
    )


def _order(champion_by_name, name):
    parsed = _parse(champion_by_name[name])
    return _resolve(champion_by_name[name], parsed), _edges(
        name, champion_by_name[name], parsed
    )


# ---------------------------------------------------------------------------
# Cast orders
# ---------------------------------------------------------------------------


def test_zed_order_is_w_r_e_q(champion_by_name):
    order, _ = _order(champion_by_name, "Zed")
    assert order == ["W", "R", "E", "Q"]


def test_yone_order_starts_with_e(champion_by_name):
    order, edges = _order(champion_by_name, "Yone")
    assert order[0] == "E"
    assert _has_edge(edges, "E", "Q", "stored_setup")


def test_karma_order_starts_with_r(champion_by_name):
    order, edges = _order(champion_by_name, "Karma")
    assert order[0] == "R"
    assert _has_edge(edges, "R", "Q", "empower")


def test_tristana_order_starts_with_e(champion_by_name):
    order, edges = _order(champion_by_name, "Tristana")
    assert order[0] == "E"
    assert _has_edge(edges, "E", "R", "self_setup")


def test_swain_order_starts_with_e(champion_by_name):
    order, _ = _order(champion_by_name, "Swain")
    assert order[0] == "E"


def test_draven_order_starts_with_q_and_executes_with_r(champion_by_name):
    order, edges = _order(champion_by_name, "Draven")
    assert order[0] == "Q"
    assert _has_edge(edges, "Q", "R", "execute")


def test_veigar_order_executes_with_r(champion_by_name):
    _, edges = _order(champion_by_name, "Veigar")
    assert _has_edge(edges, "Q", "R", "execute")


# ---------------------------------------------------------------------------
# Setup→consume edges
# ---------------------------------------------------------------------------


def test_darius_has_no_e_to_r_stack_consume_edge(champion_by_name):
    """E applies no stack: only Q/W apply Hemorrhage stacks to feed R."""
    _, edges = _order(champion_by_name, "Darius")
    assert not _has_edge(edges, "E", "R", "stack_consume")


@pytest.mark.parametrize("name", ["Nasus", "Rumble"])
def test_shred_champion_has_e_to_q_shred_edge(champion_by_name, name):
    order, edges = _order(champion_by_name, name)
    assert order[0] == "E"
    assert _has_edge(edges, "E", "Q", "shred")


def test_anivia_q_to_e_enhanced_consume(champion_by_name):
    order, edges = _order(champion_by_name, "Anivia")
    assert order[0] == "Q"
    assert _has_edge(edges, "Q", "E", "enhanced_consume")


def test_seraphine_order_is_e_r_q_w_with_execute_edges(champion_by_name):
    """F4 gamma row: Seraphine's Q is a missing-health execute cast after E/R."""
    order, edges = _order(champion_by_name, "Seraphine")
    assert order == ["E", "R", "Q", "W"]
    assert _has_edge(edges, "E", "Q", "execute")
    assert _has_edge(edges, "R", "Q", "execute")


def test_variant_execute_atoms_do_not_leak_into_default_packets(champion_by_name):
    """Inactive form rows must not create false missing-health edges."""
    for name in ("Hwei", "Nidalee"):
        order, edges = _order(champion_by_name, name)
        assert not _has_edge(edges, "R", "Q", "execute")
        assert not _has_edge(edges, "W", "Q", "execute")
        assert not _has_edge(edges, "E", "Q", "execute")
    assert _order(champion_by_name, "Hwei")[0] == ["Q", "W", "E", "R"]
    assert _order(champion_by_name, "Nidalee")[0] == ["Q", "W", "E", "R"]


def test_hwei_qw_variant_keeps_its_missing_health_execute(champion_by_name):
    """QW/Severing Bolt retains the source-backed execute edge."""
    data = champion_by_name["Hwei"]
    parsed = _parse(data, {"q_variant": 1})
    assert parsed["Q"]["name"] == "Severing Bolt"
    order = _resolve(data, parsed)
    edges = _edges("Hwei", data, parsed)
    assert order == ["R", "Q", "W", "E"]
    assert _has_edge(edges, "R", "Q", "execute")


def test_brand_seed_does_not_mislabel_e_as_blaze_consumer():
    """Brand's Blaze detonation is passive P state, not E consumption."""
    assert COMBO_TABLE["Brand"].consume == ()
