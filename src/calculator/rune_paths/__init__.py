"""How a rune path registers the runes it compiles.

One module per path — ``precision``, ``domination``, ``sorcery``, ``resolve``,
``inspiration`` — plus ``shards`` for the three stat-shard rows and
``keystones`` for row 0, neither of which belongs to one path. Each module
declares exactly two mappings and nothing else:

``COMPILERS``
    ``{rune name: compiler}``, where a compiler takes that rune's cached
    ``data/runes.json`` record and returns one ``rune_effects`` effect. Every
    number it reads comes out of the record through the typed accessors
    ``rune_effects`` exports; a missing key raises, naming the rune and the
    key (CLAUDE.md rule 5). A rune with no entry here is unmodeled and is
    refused at the request boundary rather than priced at zero.

``OPTIONS``
    ``{rune name: (RuneOption, ...)}`` for the runes whose formula needs an
    input the request does not otherwise carry — a stack count, a game
    minute, whether the holder is above a health threshold. Decision 5: an
    explicit option with a disclosed default, never an inferred constant.
    A rune that needs no input declares nothing here.

``rune_effects`` merges the seven modules into one resolver and one catalog,
so nothing downstream distinguishes a keystone from a minor rune except where
the roster says its slot is.
"""

from collections.abc import Callable, Mapping
from typing import Any

from ..rune_effects import RuneEffect, RuneOption
from . import (
    domination,
    inspiration,
    keystones,
    precision,
    resolve,
    shards,
    sorcery,
)

#: What every entry of a path module's ``COMPILERS`` is.
RuneCompiler = Callable[[Mapping[str, Any]], RuneEffect]

#: The five paths, in the roster's own order.
PATH_MODULES = (precision, domination, sorcery, resolve, inspiration)


def path_compilers() -> dict[str, RuneCompiler]:
    """Every minor-rune compiler the paths declare, merged into one mapping.

    A name claimed by two paths raises: a rune belongs to one path, and two
    compilers for one rune is a declaration bug, not a preference.
    """
    merged: dict[str, RuneCompiler] = {}
    for module in PATH_MODULES:
        for name, compiler in module.COMPILERS.items():
            owner = _owner(merged, name)
            if owner is not None:
                raise ValueError(
                    f"rune {name!r} is compiled by both {owner} and "
                    f"{module.__name__.rsplit('.', 1)[-1]}"
                )
            merged[name] = compiler
    return merged


def path_options() -> dict[str, tuple[RuneOption, ...]]:
    """Every declared rune option, merged the same way as the compilers.

    A rune whose options two paths declare raises for the same reason a
    rune two paths compile does: one of the two would silently win.
    """
    merged: dict[str, tuple[RuneOption, ...]] = {}
    for module in PATH_MODULES:
        for name, options in module.OPTIONS.items():
            if name in merged:
                raise ValueError(
                    f"rune {name!r} has options declared by two paths, one of "
                    f"them {module.__name__.rsplit('.', 1)[-1]}"
                )
            merged[name] = options
    return merged


def keystone_compilers() -> dict[str, RuneCompiler]:
    """Every keystone compiler — row 0, which belongs to no one path."""
    return dict(keystones.COMPILERS)


def shard_compilers() -> dict[tuple[int, str], RuneCompiler]:
    """Every stat-shard compiler, keyed by the ``(row, name)`` that selects it."""
    return dict(shards.COMPILERS)


def _owner(merged: Mapping[str, RuneCompiler], name: str) -> str | None:
    """Which path already claimed ``name``, if any."""
    if name not in merged:
        return None
    for module in PATH_MODULES:
        if name in module.COMPILERS:
            return module.__name__.rsplit(".", 1)[-1]
    return "another path"
