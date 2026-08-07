"""Focused rotation-semantics tests for issue #145's five named options.

The resolver derives setup/consume edges from the module OPTIONS rotation
declarations (``get_champion_option_rotation``).  These tests lock the
semantics that were previously invisible to the receipt:

- Diana ``moonlight_reset`` — consume(E <- Q): a real ``Q→E`` mark_consume
  edge cited with the option; the option gates E's dash count, not the edge.
- Kalista ``soul_mark_proc`` — consume(W, auto-stream setup): W enters the
  derived order when armed and is cited in the receipt; the result is
  deterministic across cache warmth (cold == warm).
- Viego ``q_second_strike`` / Renata Glasc ``p_leverage_procs`` —
  ``self_state``: acknowledged in the receipt, orders unchanged.
- Fiddlesticks ``q_target_already_feared`` — ``irrelevant``: acknowledged
  in the receipt instead of a silent unclassified no-signal claim.
"""

import pytest

from src.calculator import rotation_resolver
from src.calculator.champions import (
    get_champion_cast_order,
    get_champion_options_meta,
)
from src.calculator.data_fetcher import fetch_champion_data, fetch_item_data
from src.calculator.rotation_resolver import (
    detect_setup_consume_edges,
    resolve_cast_order,
)


@pytest.fixture(autouse=True)
def _clear_resolver_cache():
    """The resolver cache is process-global; keep tests order-independent."""
    yield
    rotation_resolver._DERIVED_RULE_CACHE.clear()


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


def _resolve(champion_data, parsed, champion_options=None):
    return resolve_cast_order(
        champion_data.get("name", ""),
        parsed,
        champion_data=champion_data,
        certified_order=get_champion_cast_order(champion_data.get("name", "")),
        champion_options=champion_options,
    )


def _detect_edges(champion_name, champion_data, parsed):
    """Re-run the resolver's edge detector through the public accessor."""
    from src.calculator.champions import get_champion_option_rotation

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
    return detect_setup_consume_edges(
        champion_name, parsed, champion_data, slot_options
    )


def _receipt_text(rule) -> str:
    return " ".join(rule.sources) + " " + rule.rationale


class TestDianaMoonlightReset:
    def test_moonlight_reset_declares_the_q_to_e_consume_edge(
        self, champion_by_name, items_by_name
    ) -> None:
        data = champion_by_name["Diana"]
        parsed = _parse(data, 11, (), items_by_name)
        edges = _detect_edges("Diana", data, parsed)
        assert ("Q", "E", "mark_consume") in {
            (e.setup, e.consume, e.kind) for e in edges
        }
        order, rule = _resolve(data, parsed)
        assert order == ["Q", "W", "E", "R"]
        assert rule.setup == ("Q",)
        assert rule.consume == ("E",)
        assert "moonlight_reset" in _receipt_text(rule)
        assert "no detectable setup/consume signal" not in rule.rationale

    def test_option_on_and_off_keep_the_same_order_and_edge(
        self, champion_by_name, items_by_name
    ) -> None:
        """The option gates E's dash count, NOT the Q->E edge."""
        for options in ({"moonlight_reset": True}, {"moonlight_reset": False}):
            data = champion_by_name["Diana"]
            parsed = _parse(data, 11, (), items_by_name, champion_options=options)
            edges = _detect_edges("Diana", data, parsed)
            assert ("Q", "E", "mark_consume") in {
                (e.setup, e.consume, e.kind) for e in edges
            }
            order, _ = _resolve(data, parsed, champion_options=options)
            assert order == ["Q", "W", "E", "R"]


class TestFiddlesticksIrrelevantOption:
    def test_q_target_already_feared_is_acknowledged_not_unclassified(
        self, champion_by_name, items_by_name
    ) -> None:
        data = champion_by_name["Fiddlesticks"]
        parsed = _parse(data, 11, (), items_by_name)
        order, rule = _resolve(data, parsed)
        assert order == ["Q", "W", "E", "R"]
        assert rule.setup == () and rule.consume == ()
        text = _receipt_text(rule)
        assert "q_target_already_feared" in text
        assert "(irrelevant" in text
        assert "unclassified" not in text
        assert "no detectable setup/consume signal" in rule.rationale


class TestKalistaSoulMarkProc:
    def test_w_absent_when_unarmed_and_present_when_armed(
        self, champion_by_name, items_by_name
    ) -> None:
        data = champion_by_name["Kalista"]
        parsed_off = _parse(data, 11, (), items_by_name)
        order_off, _ = _resolve(data, parsed_off)
        assert "W" not in order_off
        assert order_off == ["Q", "E"]

        parsed_on = _parse(
            data, 11, (), items_by_name, champion_options={"soul_mark_proc": True}
        )
        order_on, rule_on = _resolve(
            data, parsed_on, champion_options={"soul_mark_proc": True}
        )
        assert "W" in order_on
        assert order_on == ["Q", "W", "E"]
        assert "soul_mark_proc" in _receipt_text(rule_on)

    def test_option_gated_w_is_deterministic_across_cache_warmth(
        self, champion_by_name, items_by_name
    ) -> None:
        """Cold cache must not drop the option-gated W slot (issue #145 §6)."""
        data = champion_by_name["Kalista"]
        parsed_on = _parse(
            data, 11, (), items_by_name, champion_options={"soul_mark_proc": True}
        )
        rotation_resolver._DERIVED_RULE_CACHE.clear()  # cold
        order_cold, rule_cold = _resolve(
            data, parsed_on, champion_options={"soul_mark_proc": True}
        )
        order_warm, rule_warm = _resolve(
            data, parsed_on, champion_options={"soul_mark_proc": True}
        )
        assert order_cold == order_warm == ["Q", "W", "E"]
        assert "W" in order_cold
        assert "soul_mark_proc" in _receipt_text(rule_cold)
        assert "soul_mark_proc" in _receipt_text(rule_warm)

    def test_pipeline_path_without_resolver_options_is_deterministic(
        self, champion_by_name, items_by_name
    ) -> None:
        """The pipeline calls the resolver without champion_options; the
        option-gated W must still survive a cold cache via the base-order
        fallback."""
        data = champion_by_name["Kalista"]
        parsed_on = _parse(
            data, 11, (), items_by_name, champion_options={"soul_mark_proc": True}
        )
        rotation_resolver._DERIVED_RULE_CACHE.clear()
        order_cold, _ = _resolve(data, parsed_on)
        order_warm, _ = _resolve(data, parsed_on)
        assert order_cold == order_warm
        assert "W" in order_cold


class TestSelfStateOptions:
    @pytest.mark.parametrize(
        ("champion", "option_key"),
        [("Viego", "q_second_strike"), ("Renata Glasc", "p_leverage_procs")],
    )
    def test_self_state_option_is_acknowledged_and_order_unchanged(
        self, champion_by_name, items_by_name, champion, option_key
    ) -> None:
        data = champion_by_name[champion]
        parsed = _parse(data, 11, (), items_by_name)
        order, rule = _resolve(data, parsed)
        assert rule.setup == () and rule.consume == ()
        assert option_key in _receipt_text(rule)
        assert "(self_state" in _receipt_text(rule)
        assert "no detectable setup/consume signal" in rule.rationale


class TestNoSignalGuard:
    def test_unclassified_option_never_claims_no_signal(
        self, champion_by_name, items_by_name, monkeypatch
    ) -> None:
        """A receipt cannot claim "no detectable setup/consume signal" while
        an enabled option is unclassified (issue #145 acceptance)."""
        from src.calculator import champions as champions_module

        data = champion_by_name["Fiddlesticks"]
        parsed = _parse(data, 11, (), items_by_name)

        real = champions_module.get_champion_option_rotation

        def unclassified(name):
            result = dict(real(name))
            result["q_target_already_feared"] = None
            return result

        monkeypatch.setattr(
            champions_module, "get_champion_option_rotation", unclassified
        )
        rotation_resolver._DERIVED_RULE_CACHE.clear()
        _order, rule = _resolve(data, parsed)
        assert "unclassified" in rule.rationale
        assert "no detectable setup/consume signal" not in rule.rationale
