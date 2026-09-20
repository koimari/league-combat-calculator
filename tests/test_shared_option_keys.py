"""The shared option-key names answer live OPTIONS declarations.

A key declared in one champion module and read in another is spelled
once, in ``champions/shared_option_keys.py`` or in
``aphelios_weapons.OPTION_KEYS``, and the reader imports that name.
A rename of the declaring row leaves the name pointing at a key nobody
declares, which would withhold the reader's whole ledger with no error;
these tests are what fail instead.
"""

import ast
from pathlib import Path

from src.calculator.champions import champion_options_meta_map, shared_option_keys
from src.calculator.champions.aphelios_weapons import OPTION_KEYS

#: Every engine module, which is the whole package but the champion
#: modules: a module reading the key it declares itself is not a contract.
ENGINE = Path(__file__).resolve().parent.parent / "src" / "calculator"
CHAMPIONS = ENGINE / "champions"

#: The helpers that take an option key as their last argument.
_KEYED_HELPERS = {
    "_seeded_option_stacks",
    "declared_option_default",
    "declared_option_spec",
}


def _published() -> dict[str, str]:
    """Every option-key spelling the shared homes publish, by its name."""
    names: dict[str, str] = {
        f"OPTION_KEYS.{field}": key for field, key in OPTION_KEYS._asdict().items()
    }
    for name, value in vars(shared_option_keys).items():
        if name.startswith("_"):
            continue
        if isinstance(value, str):
            names[name] = value
        elif isinstance(value, tuple) and hasattr(value, "_asdict"):
            for field, member in value._asdict().items():
                if isinstance(member, str):
                    names[f"{name}.{field}"] = member
    return names


def _declared() -> set[str]:
    return {
        row["key"]
        for meta in champion_options_meta_map().values()
        for row in meta["options"]
    }


def _literal_reads(tree: ast.AST, keys: set[str]) -> list[tuple[int, str]]:
    """Every option key this module reads as a literal, with its line."""

    def key_of(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and node.value in keys:
            return str(node.value)
        return None

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(
            isinstance(op, (ast.In, ast.NotIn)) for op in node.ops
        ):
            key = key_of(node.left)
            if key:
                found.append((node.lineno, key))
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name == "get" and node.args:
            key = key_of(node.args[0])
            if key:
                found.append((node.lineno, key))
        elif name in _KEYED_HELPERS:
            found += [
                (node.lineno, key)
                for key in (key_of(argument) for argument in node.args)
                if key
            ]
    return found


def test_every_shared_name_is_a_declared_option_key() -> None:
    """A name here that no champion declares is a rename that drifted."""
    declared = _declared()
    published = _published()
    assert published, "the shared option-key homes publish nothing"
    orphans = {name: key for name, key in published.items() if key not in declared}
    assert not orphans, (
        f"shared option-key names answer no OPTIONS row: {orphans} — "
        "the declaring module renamed the key and the reader was left behind"
    )


def test_the_engine_reads_no_champion_option_by_literal() -> None:
    """An engine read spells the key with its imported name, never a literal.

    A literal there is the silent failure: the declaring module renames
    the key, the gate stops matching, and the walk withholds its whole
    ledger with the damage numbers unchanged.
    """
    keys = _declared()
    sites = {
        f"{path.relative_to(ENGINE).as_posix()}:{line}": key
        for path in sorted(ENGINE.rglob("*.py"))
        if CHAMPIONS not in path.parents
        for line, key in _literal_reads(
            ast.parse(path.read_text(encoding="utf-8")), keys
        )
    }
    assert not sites, (
        f"engine modules read a champion option by literal: {sites} — "
        "import the name from champions/shared_option_keys.py instead"
    )
