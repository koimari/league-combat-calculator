"""The three stat-shard rows.

Shards belong to no path, so they get their own module and their own key
shape: ``(row, name)``, because the same shard name appears in two rows
(Adaptive Force in rows 1 and 2, Health Scaling in rows 2 and 3) and the two
are different selections.

A compiler takes the cached shard-option record — the same
``{name, description, effects}`` shape a rune entry carries — from
``rune_effects.RUNE_SHARDS``, and returns one ``rune_effects`` effect, almost
always a ``RuneStatGrantEffect``. Nothing is declared yet: an undeclared
shard is refused at the request boundary by ``rune_effects.resolve_shard``.
"""

from typing import Any, Callable, Mapping

from ..rune_effects import RuneEffect

COMPILERS: dict[tuple[int, str], Callable[[Mapping[str, Any]], RuneEffect]] = {}
