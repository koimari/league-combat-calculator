"""Resolve's minor runes.

Nothing here yet: Resolve's nine minor runes are declared as they are
reviewed, each as one entry in ``COMPILERS`` beside its compile function.
Most of them are durability — a shield, a heal, a resistance — which is the
half the pair engine holds no channel for, so several will compile to a
``RuneNoDamageEffect`` carrying that reason rather than to a number.
"""

from typing import Any, Callable, Mapping

from ..rune_effects import RuneEffect, RuneOption

COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {}
