"""An option the engine derives must say so, and the page must leave it out.

A champion module derives a reading when its option key is ABSENT, which it
states by testing ``ctx.options.get(key) is None``. The browser decides
whether the key arrives, so the two halves have to agree: the module's
branch and the option row's ``derives`` flag. They did not, and every
derived reading in the campaign was unreachable through ``/advanced`` while
the API answered it correctly (SR9).

The scan below is over the source, not over a hand-written list, so a new
derived option that forgets the flag fails here rather than shipping a
control nobody can reach.
"""

import ast
import re
from pathlib import Path

import pytest

from src.calculator.champions import champion_options_meta_map

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULES = REPO_ROOT / "src" / "calculator" / "champions"
APP_JS = REPO_ROOT / "static" / "js" / "app.js"

#: Keys whose ``is None`` test is NOT a derive branch, with the reason. A
#: module that tests a key for any other purpose belongs here, named, so the
#: scan below can stay mechanical.
NOT_A_DERIVE_BRANCH = {
    # Engine-injected, never a user option: the fight's own duration.
    "fight_duration_seconds": "the engine injects it; no OPTIONS row declares it",
    # Aphelios saves the caller's value, overrides it per weapon form and
    # restores it; the None test is the restore, not a derived reading.
    "q_variant": "aphelios saves and restores it around a per-weapon override",
}


def _keys_tested_against_none(tree: ast.AST) -> set[str]:
    """Option keys this module compares to ``None``, directly or through a name."""
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _option_get_key(node.value) is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound[target.id] = _option_get_key(node.value)
    tested: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
            continue
        if not any(
            isinstance(other, ast.Constant) and other.value is None
            for other in node.comparators
        ):
            continue
        direct = _option_get_key(node.left)
        if direct is not None:
            tested.add(direct)
        elif isinstance(node.left, ast.Name) and node.left.id in bound:
            tested.add(bound[node.left.id])
    return tested


def _option_get_key(node: ast.AST) -> str | None:
    """The key of a ``ctx.options.get("key")`` call, or ``None``."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "get"):
        return None
    if not (isinstance(func.value, ast.Attribute) and func.value.attr == "options"):
        return None
    if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant):
        return None
    key = node.args[0].value
    return key if isinstance(key, str) else None


def _declared_option_rows() -> dict[str, list[dict]]:
    """Every published option row, keyed by option key."""
    rows: dict[str, list[dict]] = {}
    for meta in champion_options_meta_map().values():
        for option in meta["options"]:
            rows.setdefault(option["key"], []).append(option)
    return rows


def _module_paths() -> list[Path]:
    return sorted(
        path for path in MODULES.glob("*.py") if not path.name.startswith("_")
    )


def test_a_module_that_derives_an_option_declares_it_on_the_row():
    """The branch and the flag are two halves of one statement."""
    rows = _declared_option_rows()
    missing: list[str] = []
    for path in _module_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for key in sorted(_keys_tested_against_none(tree)):
            if key in NOT_A_DERIVE_BRANCH or key not in rows:
                continue
            if not any(row.get("derives") for row in rows[key]):
                missing.append(f"{path.name}: {key}")
    assert missing == [], (
        "these options branch on an absent key and no OPTIONS row declares "
        "derives=True, so the page will send the default and pin them to the "
        "stated level: " + ", ".join(missing)
    )


def test_a_declared_derives_flag_has_a_module_branch_behind_it():
    """The reverse: a flag nothing reads would put an Auto button on a
    control that ignores it."""
    tested: set[str] = set()
    for path in _module_paths():
        tested |= _keys_tested_against_none(ast.parse(path.read_text(encoding="utf-8")))
    unread = sorted(
        key
        for key, rows in _declared_option_rows().items()
        if any(row.get("derives") for row in rows) and key not in tested
    )
    assert unread == [], (
        "these options declare derives=True and no module branches on the "
        "key being absent: " + ", ".join(unread)
    )


def test_the_campaign_s_derived_options_are_all_flagged():
    """The permanent floor: the count cannot silently fall to zero.

    A vacuous scan would pass both rows above, so this pins that the flag is
    actually carried by the roster the campaign derived.
    """
    flagged = {
        key
        for key, rows in _declared_option_rows().items()
        if any(row.get("derives") for row in rows)
    }
    for key in ("p_stacks", "jinx_rev_up_stacks", "q_stacks", "blight_stacks"):
        assert key in flagged, f"{key} is a derived option and is not flagged"
    assert len(flagged) >= 20


class TestThePageLeavesADerivedKeyOut:
    """The browser half, read off the shipped script.

    These are source assertions rather than a DOM run because the page has
    no test harness here; each names the exact clause that decides whether
    an absent key reaches the engine.
    """

    @staticmethod
    def _source() -> str:
        return APP_JS.read_text(encoding="utf-8")

    def test_seeding_skips_a_derived_option(self):
        source = self._source()
        assert "function seededChampionOptions(definitions)" in source
        seeder = source.split("function seededChampionOptions(definitions)", 1)[1]
        assert ".filter((option) => !option.derives)" in seeder.split("}", 1)[0]

    def test_serializing_omits_a_derived_option_with_no_stored_value(self):
        source = self._source()
        assert re.search(
            r"\.filter\(\(option\) => !\(option\.derives "
            r"&& state\.attacker\.championOptions\[option\.key\] == null\)\)",
            source,
        ), "engineChampionOptions no longer omits an unset derived key"

    def test_the_control_offers_an_auto_state_to_return_to(self):
        source = self._source()
        assert 'data-champion-option-auto="${key}"' in source
        assert "delete state.attacker.championOptions[" in source

    @pytest.mark.parametrize(
        "clause",
        [
            "function isAutoOption(option)",
            'option.derives && isAutoOption(option)\n    ? "Auto"',
        ],
    )
    def test_the_control_reads_auto_while_it_is_unset(self, clause):
        assert clause in self._source()
