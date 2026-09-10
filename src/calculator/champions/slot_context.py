"""What a slot parser is handed, and the phases it runs in."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .inputs import ChampionInputError, champion_stat, target_stat
from .skill_orders import get_ability_rank

# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

BUFF = "buff"  # mutates ctx.stats (e.g. R steroids) — no damage yet
DEBUFF = "debuff"  # mutates ctx.target (e.g. resist shreds)
DAMAGE = "damage"  # emits castable damage entries (the default phase)
ONHIT = "onhit"  # emits on-hit entries layered onto auto attacks
AMP = "amp"  # scales already-computed entries (reads ctx.results)

PHASE_ORDER = (BUFF, DEBUFF, DAMAGE, ONHIT, AMP)

SlotParser = Callable[["SlotCtx"], dict[str, Any] | None]

# What a declared OPTIONS row may hold: bool, int, float, select (str or
# int) and string_list rows, per ``champions/inputs.py``.
OptionValue = bool | int | float | str | list[str]

#: Where ``slotlib.with_control_event`` parks a sourced control interval
#: whose kind it did not author.  ``engine._apply_module_cc`` turns each into
#: an :class:`ability_spec.ControlEvent` carrying the module's declared kind,
#: and ``engine._resolve_pending_control_events`` refuses whatever is left, so
#: an interval on a slot ``MODULE_CC`` does not declare stops the parse instead
#: of publishing a control the kit never listed.  Private to ``slotlib`` and
#: ``engine``: it never survives one parse, and no reader outside sees it.
PENDING_CONTROL_EVENTS = "_pending_control_events"


# ---------------------------------------------------------------------------
# Slot context
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SlotCtx:
    """Everything a slot parser may read (and, per phase, mutate).

    ``stats``, ``target``, and ``results`` are shared across all slots of
    one parse: BUFF/DEBUFF phases mutate the first two, and ``results``
    accumulates emitted entries in evaluation order.

    The three input blocks are read through :meth:`stat`, :meth:`target_stat`
    and :meth:`option`, never with a ``.get(key, <literal>)``: a fallback
    literal keeps a formula answering after its input stops arriving, and the
    resulting zero would be stamped ``MEASURED``.  ``champions/inputs.py``
    holds the vocabularies and their declared defaults.
    """

    slot: str  # slot-map key being parsed
    champion_name: str  # for skill-order lookup
    abilities: dict[str, list] = field(default_factory=dict)
    level: int = 1
    stats: dict[str, float] = field(default_factory=dict)
    target: dict[str, float] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    ability_ranks: dict[str, int] | None = None
    # The champion's declared OPTIONS defaults, resolved once per parse.
    # Empty for a synthetic fixture with no module, which is why reading an
    # option it never declared raises there too.
    option_defaults: Mapping[str, Any] = field(default_factory=dict)

    def stat(self, name: str) -> float:
        """One build stat by declared name (``inputs.CHAMPION_STATS``)."""
        return champion_stat(self.stats, name, champion=self.champion_name)

    def target_stat(self, name: str) -> float:
        """One target stat by declared name (``inputs.TARGET_STATS``)."""
        return target_stat(self.target, name, champion=self.champion_name)

    def option(self, key: str) -> OptionValue:
        """One declared option: the user's value, or the module's default.

        The default is the module's own ``OPTIONS`` row, the row the frontend
        renders, so the fallback and the number the user sees cannot
        disagree.  An undeclared key raises rather than yielding a zero that
        would be published as a measured number.
        """
        if key not in self.option_defaults:
            raise ChampionInputError(
                f"{self.champion_name or 'a champion module'} read option "
                f"{key!r}, which its OPTIONS declaration does not contain — "
                f"an undeclared option is unwired input, not a default (D-24)"
            )
        value = self.options.get(key)
        return self.option_defaults[key] if value is None else value

    def bump_stat(self, name: str, delta: float) -> float:
        """Accumulate onto a declared build stat, returning the new value."""
        updated = self.stat(name) + delta
        self.stats[name] = updated
        return updated

    def ability(self, slot: str | None = None, index: int = 0) -> dict | None:
        """The ability JSON at (slot, index), or ``None`` if absent.

        Defaults to entry 0 of this parser's own slot.
        """
        entries = self.abilities.get(slot or self.slot, [])
        if index >= len(entries):
            return None
        return entries[index]

    def rank_for(self, slot: str | None = None) -> int:
        """Resolve the ability rank: explicit override, else skill order."""
        key = slot or self.slot
        if self.ability_ranks and key in self.ability_ranks:
            return self.ability_ranks[key]
        return get_ability_rank(key, self.level, self.champion_name)

    def ranked(
        self, slot: str | None = None, index: int = 0
    ) -> tuple[dict, int] | None:
        """The ``(ability, rank)`` a slot parser needs, or ``None``.

        ``None`` is either reason the slot prices nothing, and a parser must
        not tell them apart: no such entry cached, or no point in it yet.
        """
        ability = self.ability(slot, index)
        if ability is None:
            return None
        rank = self.rank_for(slot)
        return None if rank < 1 else (ability, rank)

    def ranked_sub(
        self, slot: str | None = None, index: int = 1
    ) -> tuple[dict, dict, int] | None:
        """The parent entry, its sub-entry, and the rank both are priced at.

        ``None`` is the answer :meth:`ranked` gives, for the same two
        reasons plus a third: either entry absent.
        """
        parent = self.ability(slot, 0)
        sub = self.ability(slot, index)
        if parent is None or sub is None:
            return None
        rank = self.rank_for(slot)
        return None if rank < 1 else (parent, sub, rank)
