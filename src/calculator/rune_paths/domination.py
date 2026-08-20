"""Domination's minor runes.

Nothing here yet: Domination's nine minor runes are declared as they are
reviewed, each as one entry in ``COMPILERS`` beside its compile function.
An undeclared rune is refused at the request boundary by
``rune_effects.resolve_rune`` — never priced at zero.
"""

from typing import Any, Callable, Mapping

from ..rune_effects import RuneEffect, RuneOption

COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {}
