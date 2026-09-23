"""The one walk over the ally packet blocks' damage-modifier sites.

A cross-participant damage modifier is declared at a
`_packet(kind=PacketKind.DAMAGE_MODIFIER.value, ...)` call.  The authority
table is `trigger_stream.CAPABILITIES`, and each site names the member it
answers to literally, so the two cannot drift apart.  The runtime check in
`_packet` only fires on a packet that is built; this reads the construction
sites, so a branch no fixture reaches is held to the same declaration.

    python scripts/packet_declarations.py

Findings are the sites that name no literal source or no literal
`Authority.<member>`.  `tests/test_item_support_effects.py` and
`tests/test_deferred_semantics_sentinels.py` read the sites through this module, which is
why there is one walk rather than one per suite.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lint_report import report

from src.calculator import item_support_effects
from src.calculator.ability_spec import Authority

PACKET_KIND = "damage_modifier"


class Site(NamedTuple):
    """One packet construction site: where it is and what it declares."""

    line: int
    keywords: Mapping[str, ast.expr]
    module: ModuleType

    def keyword(self, name: str) -> ast.expr | None:
        """The value node of one keyword, or ``None`` when the site omits it."""
        return self.keywords.get(name)


def block_modules() -> tuple[ModuleType, ...]:
    """The modules the dispatch tables send a packet block to, in table order.

    Read off the tables rather than listed, so a sixth block module is walked
    the day it is registered.
    """
    return tuple(
        dict.fromkeys(
            sys.modules[build.__module__]
            for table in item_support_effects.PRODUCER_TABLES
            for build in table.values()
        )
    )


def _names_kind(node: ast.expr | None, kind: str) -> bool:
    """Whether a ``kind=`` node spells ``PacketKind.<KIND>.value``."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "value"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == kind.upper()
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "PacketKind"
    )


def sites(kind: str = PACKET_KIND) -> list[Site]:
    """Every ``_packet`` construction site of one kind, in block order."""
    found = []
    for module in block_modules():
        source = Path(module.__file__).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_packet"
            ):
                continue
            keywords = {k.arg: k.value for k in node.keywords if k.arg}
            if _names_kind(keywords.get("kind"), kind):
                found.append(Site(node.lineno, keywords, module))
    return found


def _literal_source(site: Site) -> str | None:
    """The site's declared source string, or ``None`` when it names none."""
    node = site.keyword("source")
    return node.value if isinstance(node, ast.Constant) else None


def _literal_authority(site: Site) -> str | None:
    """The site's declared ``Authority`` member name, or ``None``."""
    node = site.keyword("authority")
    return (
        node.attr
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Authority"
        and node.attr in Authority.__members__
        else None
    )


def authorities() -> dict[str, str]:
    """Each site's source and the ``Authority`` member name it declares."""
    declared = {}
    for site in sites():
        source, authority = _literal_source(site), _literal_authority(site)
        if source is not None and authority is not None:
            declared[source] = authority
    return declared


def declared(*names: str) -> dict[str, dict[str, Any]]:
    """Each site's declared keywords, evaluated in the module's namespace."""
    return {
        _literal_source(site): {
            name: _evaluate(site.keyword(name), site.module) for name in names
        }
        for site in sites()
    }


def _evaluate(expression: ast.expr | None, module: ModuleType) -> Any:
    """One declared keyword's value, or ``None`` when the site omits it."""
    if expression is None:
        return None
    return eval(
        compile(ast.Expression(expression), "<declaration>", "eval"),
        vars(module),
    )


def check() -> list[str]:
    """Every site that leaves the registry nothing to check it against."""
    findings = []
    for site in sites():
        where = f"{site.module.__name__.rsplit('.', 1)[-1]} line {site.line}"
        if _literal_source(site) is None:
            findings.append(
                f"{where} names no literal source; the registry "
                "cannot be checked against an expression"
            )
        elif _literal_authority(site) is None:
            findings.append(
                f"{_literal_source(site)} declares no literal Authority member "
                f"at {where}; one of "
                f"{sorted(member.value for member in Authority)} is required"
            )
    return findings


if __name__ == "__main__":
    raise SystemExit(report(check(), f"OK: {len(sites())} sites, each declared"))
