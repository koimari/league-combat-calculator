"""Test front door for ``champions/inputs.py`` — D-24's guard, asserted.

The champion tree discharges its ``zero_policy`` obligation with a declared
default at two builders instead of editing every call site, and D-24 makes
that exception conditional: *a source assertion over* ``champions/``
*forbids a* ``.get(key, <literal>)``-*shaped fallback from feeding a damage
formula*, because a zero produced by an input nothing wired would be stamped
``MEASURED`` by the default and become indistinguishable from a formula that
ran.

Three things are asserted here, and the third is the one that makes the
first two more than bookkeeping:

* **The shape is gone from source.**  No champion module reads one of the
  three input blocks with a literal fallback; the accessors are the only way
  in.  ``scripts/behavior_frontier.py --check`` fails on the same population,
  so the rule is enforced by the gate as well as by this file.
* **An unwired read raises.**  A name outside its vocabulary is a
  ``ChampionInputError``, not a zero.
* **The vocabulary is checked against its producers.**  Every ``BUILD`` name
  must be a key ``calculate_total_stats`` really emits and every ``TARGET``
  name a key ``FightParams.target_stats`` really emits — so a stat renamed
  upstream turns this red instead of silently zeroing a scaling term in 143
  modules, which is the failure the vocabulary exists to catch.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.calculator.champions import inputs
from src.calculator.champions.engine import SlotCtx
from src.calculator.champions.inputs import (
    CHAMPION_STATS,
    RESERVED_OPTION_DEFAULTS,
    TARGET_STATS,
    ChampionInputError,
    champion_stat,
    declared_option_defaults,
    target_stat,
)
from src.calculator.data_fetcher import fetch_champion_data
from src.calculator.pipeline import FightParams
from src.calculator.stats import calculate_total_stats

ROOT = Path(__file__).resolve().parents[1]
CHAMPIONS_ROOT = ROOT / "src" / "calculator" / "champions"

# The names a champion input block is bound to.  Duplicating the frontier's
# set here would be a second thing to maintain, so it is imported from the
# instrument that gates it.
from scripts.behavior_frontier import (  # noqa: E402  pylint: disable=wrong-import-position
    INPUT_BLOCK_NAMES,
    zero_policy_frontier,
)


def _literal_default(node: ast.AST) -> bool:
    """Whether a ``.get`` default is a bare number (or its negation)."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, ast.UnaryOp):
        return _literal_default(node.operand)
    return False


def _input_fallback_sites(root: Path = CHAMPIONS_ROOT) -> list[str]:
    """Every ``<input block>.get(key, <literal>)`` under ``root``.

    Measured here independently of ``behavior_frontier`` — the same rule
    spelled twice, so the assertion does not reduce to "the tool agrees with
    itself" — and the two are asserted equal below.

    ``root`` is a parameter for the same reason ``zero_policy_frontier``
    takes one: the negative-fixture test plants into a throwaway tree.
    Planting into the live ``champions/`` package raced every other worker
    under ``pytest -n auto`` — a parallel scan saw the fixture mid-test and
    failed on a gate that was working.
    """
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        module = path.relative_to(root).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) == 2
                and _literal_default(node.args[1])
            ):
                continue
            receiver = node.func.value
            names = {
                inner.attr
                for inner in ast.walk(receiver)
                if isinstance(inner, ast.Attribute)
            } | {
                inner.id for inner in ast.walk(receiver) if isinstance(inner, ast.Name)
            }
            if names & INPUT_BLOCK_NAMES:
                found.append(f"{module}:{node.lineno}  {ast.unparse(node)}")
    return sorted(found)


def test_no_champion_module_defaults_an_input_to_a_literal() -> None:
    """D-24's source assertion, stated over the tree it governs."""
    assert _input_fallback_sites() == [], (
        "a champion input read with a literal fallback keeps answering after "
        "the input stops being wired, and the declared zero_policy default "
        "would stamp the resulting zero MEASURED; read it through "
        "champions/inputs.py instead"
    )


def test_the_gate_measures_the_same_population_this_file_does() -> None:
    """The instrument and the assertion are the same rule, not two rules."""
    assert list(zero_policy_frontier().forbidden_input_fallbacks) == (
        _input_fallback_sites()
    )


def test_the_assertion_sees_a_planted_site(tmp_path: Path) -> None:
    """The check goes red on demand rather than being trusted (R-05)."""
    planted_root = tmp_path / "champions"
    planted_root.mkdir()
    planted = planted_root / "_zero_policy_negative_fixture.py"
    planted.write_text(
        "def read(ctx):\n"
        '    """A stack count nothing wired, defaulted to a literal."""\n'
        '    return ctx.options.get("q_stacks", 4)\n',
        encoding="utf-8",
    )
    sites = _input_fallback_sites(planted_root)
    assert any("_zero_policy_negative_fixture.py" in site for site in sites)
    # Same rule, same instrument, against the shipped package: still clean.
    assert _input_fallback_sites() == []
    assert list(zero_policy_frontier(planted_root).forbidden_input_fallbacks)


def test_every_build_stat_is_a_key_its_producer_really_emits() -> None:
    """The vocabulary cannot drift from ``calculate_total_stats``."""
    champions = fetch_champion_data()
    produced = set(calculate_total_stats(champions["Ashe"], 18, []))
    produced |= set(calculate_total_stats(champions["Kaisa"], 18, []))
    declared = {
        name
        for name, default in CHAMPION_STATS.items()
        if default.source in {"BUILD", "BUILD_CHAMPION"}
    }
    assert declared <= produced, sorted(declared - produced)


def test_every_target_stat_is_a_key_its_producer_really_emits() -> None:
    """Same for the target block, whose producer is one method."""
    produced = set(
        FightParams(
            target_health=2000.0,
            target_armor=100.0,
            target_magic_resistance=50.0,
            fight_duration_seconds=10.0,
        ).target_stats()
    )
    declared = {
        name for name, default in TARGET_STATS.items() if default.source == "TARGET"
    }
    assert declared <= produced, sorted(declared - produced)


def test_the_reserved_option_keys_are_the_pipeline_s_own_set() -> None:
    """One set of pipeline-owned keys, not two that can disagree."""
    # Imported here: champions/__init__ imports every champion module, and
    # this file's other assertions are source reads that must not need it.
    from src.calculator.champions import (  # pylint: disable=import-outside-toplevel
        RESERVED_OPTION_KEYS,
    )

    assert set(RESERVED_OPTION_DEFAULTS) == set(RESERVED_OPTION_KEYS)


def test_an_undeclared_stat_raises_instead_of_reading_zero() -> None:
    """The unwired read fails loud — the whole point of the vocabulary."""
    with pytest.raises(ChampionInputError, match="bonus_attack_speed_percent"):
        champion_stat({"attack_damage": 100.0}, "bonus_attack_speed_percent")
    with pytest.raises(ChampionInputError, match="target_shield"):
        target_stat({}, "target_shield")


def test_a_declared_stat_reads_its_wired_value_or_its_declared_default() -> None:
    """Behaviour identical to the literal it replaced, stated once."""
    assert champion_stat({"ability_power": 120.0}, "ability_power") == 120.0
    assert champion_stat({}, "ability_power") == 0.0
    assert target_stat({}, "roster_target_count") == 1.0
    assert target_stat({"roster_target_count": 3.0}, "roster_target_count") == 3.0


def test_every_declared_default_carries_a_reason() -> None:
    """A default without a reason is the literal it replaced, relocated."""
    for name, default in {**CHAMPION_STATS, **TARGET_STATS}.items():
        assert default.reason.strip(), name


def test_an_undeclared_option_raises_and_a_declared_one_falls_back() -> None:
    """An option nothing declared is unwired input, not a default."""
    ctx = SlotCtx(
        slot="Q",
        champion_name="TestChamp",
        options={"q_stacks": 2},
        option_defaults={"q_stacks": 4, "q_empowered": True},
    )
    assert ctx.option("q_stacks") == 2
    assert ctx.option("q_empowered") is True
    with pytest.raises(ChampionInputError, match="q_phantom"):
        ctx.option("q_phantom")


def test_option_defaults_come_from_the_module_s_own_options_rows() -> None:
    """The number a formula falls back to is the number the user is shown."""
    defaults = declared_option_defaults("Pantheon")
    assert defaults["q_mortal_will"] is True
    assert set(RESERVED_OPTION_DEFAULTS) <= set(defaults)


class TestTheEscalatedDefectIsStillTracked:
    """``docs/receipts/escalated-defects-P3-3.7.json``, gated (R-16 Shape).

    The vocabulary check found one champion reading a stat no producer
    emits.  This slice may not correct it — the correction moves committed
    baseline leaves and owes its own R-20 population — so it is recorded,
    dated and gated instead.  The gate closes the entry by going red the day
    the defect stops reproducing, which is what stops the next baseline
    re-capture from absorbing it in silence.
    """

    RECEIPT = ROOT / "docs" / "receipts" / "escalated-defects-P3-3.7.json"

    def _defect(self) -> dict:
        payload = json.loads(self.RECEIPT.read_text(encoding="utf-8"))
        (defect,) = payload["defects"]
        return defect

    def test_the_stat_the_defect_reads_is_still_absent_from_its_producer(
        self,
    ) -> None:
        """The reproducer, run — not the receipt quoting itself."""
        signature = self._defect()["live_signature"]
        champions = fetch_champion_data()
        produced = calculate_total_stats(champions[signature["champion"]], 18, [])
        assert signature["stat_read"] not in produced
        assert signature["stat_the_producer_emits"] in produced

    def test_the_scaling_term_still_does_not_move_with_attack_speed(self) -> None:
        """The defect itself: the term is zero at every attack speed."""
        # Imported here so the source assertions above do not depend on a
        # champion module importing cleanly.
        from src.calculator.champions.akshan import (  # pylint: disable=import-outside-toplevel
            _extract_e_per_shot,
        )

        signature = self._defect()["live_signature"]
        champions = fetch_champion_data()
        stats = calculate_total_stats(champions[signature["champion"]], 18, [])
        ability = champions[signature["champion"]]["abilities"][signature["slot"]][0]
        without = _extract_e_per_shot(ability, 5, dict(stats))
        with_speed = _extract_e_per_shot(
            ability, 5, {**stats, "bonus_attack_speed": 250.0}
        )
        assert without == with_speed == signature["measured_per_shot_rank_5"]


def test_an_input_default_refuses_an_unknown_source_or_an_empty_reason() -> None:
    """The declaration's own two structural checks."""
    with pytest.raises(ValueError, match="unknown input source"):
        inputs.InputDefault(0.0, "GUESSED", "a source nobody produces")
    with pytest.raises(ValueError, match="without a reason"):
        inputs.InputDefault(0.0, "BUILD", "   ")
