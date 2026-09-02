"""The three vocabularies a champion formula may read, declared once.

CLAUDE.md rule 5 keeps item numbers out of call sites because a
``.get(key, <stale literal>)`` keeps answering after the value behind it
stops arriving — that exact shape hid a 3x Statikk Shiv overstatement.  A
champion formula reads three inputs: the build's stats, the target's
stats, and the user's options.  The same shape had grown at 370 call sites
across the champion tree, each one a literal that would keep a formula
running after its input stopped being wired, and D-24's declared
``zero_policy`` default makes that quieter rather than louder — the zero
such a formula produces is stamped ``MEASURED``, which says a formula
*computed* it.

So the exception ships with this module, and the guard has two halves:

* **No call site holds the fallback.**  ``scripts/behavior_frontier.py``
  fails on any ``x.get(<key>, <numeric literal>)`` whose receiver is one of
  the three input blocks, anywhere under ``champions/``, and
  ``tests/test_champion_inputs.py`` asserts the same over source.  The
  accessors below are the only way in.
* **The vocabulary is checked against its producer.**  Every ``BUILD`` stat
  named here must be a key ``stats.calculate_total_stats`` really emits and
  every ``TARGET`` stat a key ``FightParams.target_stats`` really emits, so
  a stat renamed on the producing side turns red *here*, naming the
  champion-side readers, instead of silently pricing zero in 143 modules.

An accessor raises :class:`ChampionInputError` for a name outside its
vocabulary, so an unwired read fails loud instead of pricing a literal.  A
name inside it returns the wired value, or the default this module declares
when the input block does not carry the key.  That declared default is the
number's one home, stated once and with a reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "CHAMPION_STATS",
    "RESERVED_OPTION_DEFAULTS",
    "SCALING_INPUTS",
    "TARGET_STATS",
    "ChampionInputError",
    "InputDefault",
    "bool_option",
    "champion_stat",
    "declared_option_defaults",
    "float_option",
    "int_option",
    "scaling_input",
    "target_stat",
]


class ChampionInputError(KeyError):
    """A champion formula read an input outside its declared vocabulary."""


@dataclass(frozen=True, slots=True)
class InputDefault:
    """One input's declared value when the block does not carry the key.

    ``source`` says who is supposed to put the key there, which is what
    makes the vocabulary checkable against a producer rather than against
    somebody's memory:

    ``BUILD``   the build's stat block (``stats.calculate_total_stats``)
    ``BUILD_CHAMPION``
                the same producer, but emitted only for one named champion
    ``TARGET``  the target block (``pipeline.FightParams.target_stats``)
    ``PARSE``   added to the parse context by ``pipeline.run_fight`` only
    ``SLOT``    written mid-parse by a BUFF-phase slot, so it does not
                exist until the slot that owns it has run
    """

    value: float
    source: str
    reason: str

    def __post_init__(self) -> None:
        if self.source not in {
            "BUILD",
            "BUILD_CHAMPION",
            "TARGET",
            "PARSE",
            "SLOT",
        }:
            raise ValueError(f"unknown input source {self.source!r}")
        if not self.reason.strip():
            raise ValueError("an input default without a reason is a literal")


def _build(reason: str) -> InputDefault:
    return InputDefault(0.0, "BUILD", reason)


_ABSENT_MEANS_NONE = "the build grants none of this stat, so the formula's term is zero"


CHAMPION_STATS: Mapping[str, InputDefault] = {
    "ability_haste": _build(_ABSENT_MEANS_NONE),
    "ability_power": _build(_ABSENT_MEANS_NONE),
    "armor": _build(_ABSENT_MEANS_NONE),
    "attack_damage": _build(_ABSENT_MEANS_NONE),
    "attack_speed": _build(_ABSENT_MEANS_NONE),
    "attack_speed_ratio": _build(_ABSENT_MEANS_NONE),
    "base_attack_damage": _build(_ABSENT_MEANS_NONE),
    "base_health": _build(_ABSENT_MEANS_NONE),
    "basic_ability_haste": _build(_ABSENT_MEANS_NONE),
    "bonus_armor": _build(_ABSENT_MEANS_NONE),
    "bonus_attack_damage": _build(_ABSENT_MEANS_NONE),
    "bonus_attack_speed": _build(_ABSENT_MEANS_NONE),
    "bonus_health": _build(_ABSENT_MEANS_NONE),
    "bonus_magic_resistance": _build(_ABSENT_MEANS_NONE),
    "bonus_mana": _build(_ABSENT_MEANS_NONE),
    "critical_strike_chance": _build(_ABSENT_MEANS_NONE),
    "heal_and_shield_power_percent": _build(_ABSENT_MEANS_NONE),
    "health": _build(_ABSENT_MEANS_NONE),
    "lethality": _build(_ABSENT_MEANS_NONE),
    "level": InputDefault(
        1.0,
        "BUILD",
        "a champion is always at least level 1, so the per-level rows a "
        "module reads price their first rank rather than a zeroth one; "
        "calculate_total_stats always emits level, so this is reached "
        "only by a caller that supplied no build stats at all",
    ),
    "lifesteal_percent": _build(_ABSENT_MEANS_NONE),
    "magic_penetration_percent": _build(_ABSENT_MEANS_NONE),
    "magic_resistance": _build(_ABSENT_MEANS_NONE),
    "max_mana": _build(_ABSENT_MEANS_NONE),
    "move_speed": _build(_ABSENT_MEANS_NONE),
    "evolution_attack_damage": InputDefault(
        0.0,
        "BUILD_CHAMPION",
        "Kai'Sa's evolution-threshold AD, emitted by calculate_total_stats "
        "for Kai'Sa alone; zero for every other champion, which is what a "
        "champion with no evolutions has",
    ),
    "evolution_ability_power": InputDefault(
        0.0,
        "BUILD_CHAMPION",
        "Kai'Sa's evolution-threshold AP, emitted for Kai'Sa alone",
    ),
    "crit_damage_bonus": InputDefault(
        0.0,
        "PARSE",
        "bonus crit damage above the 2.0 base, surfaced to the parse "
        "context by pipeline.run_fight; a direct parse call has no items "
        "and therefore no bonus",
    ),
    "tumble_cd_reduction_percent": InputDefault(
        0.0,
        "SLOT",
        "written by Vayne's Q buff slot during the parse; absent until "
        "that slot has run, and zero before it",
    ),
}
"""Every champion stat a module may read, and what its absence means.

``BUILD`` names are asserted against ``calculate_total_stats``'s real key
set, so this table cannot drift from the producer.  A name that is not
here raises rather than reading zero: a stat renamed upstream is a wiring
break, not a champion whose scaling term vanished.
"""


TARGET_STATS: Mapping[str, InputDefault] = {
    "target_max_health": InputDefault(
        0.0,
        "TARGET",
        "no target block was supplied, so a %max-health row has no target "
        "to scale against",
    ),
    "target_current_health": InputDefault(
        0.0, "TARGET", "no target block was supplied"
    ),
    "target_missing_health": InputDefault(
        0.0,
        "TARGET",
        "the target block always reports a full-health target, so missing "
        "health is zero unless a caller states otherwise",
    ),
    "roster_target_index": InputDefault(
        0.0,
        "TARGET",
        "a fight with no roster is the first (and only) target",
    ),
    "roster_target_count": InputDefault(
        1.0,
        "TARGET",
        "a fight with no roster has exactly one target",
    ),
}
"""Every target stat a module may read.  Asserted against its producer too."""


RESERVED_OPTION_DEFAULTS: Mapping[str, float | bool] = {
    "fight_duration_seconds": 0.0,
    "auto_attack_uptime": 0.0,
    "auto_attacks_only": False,
}
"""The pipeline-owned option keys and what their absence means.

``pipeline.run_fight`` injects them for timed fights and strips them
otherwise, so absence is the one-rotation mode saying "no fight window" —
a declaration, not a missing value.  ``auto_attacks_only`` defaults to
``False`` for the same reason: a window the pipeline did not mark is one
where the engine casts the rotation, so a walk module counts ability
hits.  They are never in a module's ``OPTIONS``, which is why the option
accessor consults this table too (``champions.RESERVED_OPTION_KEYS`` is
the same set, asserted equal).
"""


def _resolve(
    block: Mapping[str, Any],
    name: str,
    vocabulary: Mapping[str, InputDefault],
    *,
    champion: str,
    kind: str,
) -> float:
    """One vocabulary read: wired value, declared default, or raise."""
    declared = vocabulary.get(name)
    if declared is None:
        raise ChampionInputError(
            f"{champion or 'a champion module'} read {kind} {name!r}, which "
            f"is not a declared {kind} — champions/inputs.py holds the "
            f"vocabulary, and an undeclared read is an unwired input rather "
            f"than a zero (D-24)"
        )
    value = block.get(name)
    return declared.value if value is None else value


def champion_stat(stats: Mapping[str, Any], name: str, *, champion: str = "") -> float:
    """One champion stat, by declared name — never a call-site literal."""
    return _resolve(stats, name, CHAMPION_STATS, champion=champion, kind="stat")


def target_stat(target: Mapping[str, Any], name: str, *, champion: str = "") -> float:
    """One target stat, by declared name — never a call-site literal."""
    return _resolve(target, name, TARGET_STATS, champion=champion, kind="target stat")


SCALING_INPUTS: Mapping[str, InputDefault] = {**CHAMPION_STATS, **TARGET_STATS}
"""Both vocabularies, for the one reader that is handed both blocks merged.

``scaling._parse_compound_unit`` resolves units like ``"% (+ 1.5% per 100 AP)
of target's maximum health"``, which name a build stat and a target stat in
one string, so its caller merges the two dicts and it reads names from both.
It is the only such reader; everything else knows which block it is holding.
"""


def scaling_input(block: Mapping[str, Any], name: str, *, champion: str = "") -> float:
    """One name from the merged build+target block (see SCALING_INPUTS)."""
    return _resolve(
        block, name, SCALING_INPUTS, champion=champion, kind="scaling input"
    )


def declared_option_defaults(champion: str) -> dict[str, Any]:
    """A champion's option keys mapped to the defaults its module declares.

    The module's own ``OPTIONS`` list is the declaration, and the same rows
    the frontend renders, so the default a formula falls back to and the
    default the user sees are one value.  The pipeline-owned reserved keys
    join it because no module declares them and every module may read them.
    """
    # pylint: disable-next=import-outside-toplevel,cyclic-import
    from . import get_champion_options_meta

    defaults: dict[str, Any] = dict(RESERVED_OPTION_DEFAULTS)
    for option in get_champion_options_meta(champion)["options"]:
        key = option.get("key")
        if isinstance(key, str):
            defaults[key] = option.get("default")
    return defaults


# ---------------------------------------------------------------------------
# Option row constructors
# ---------------------------------------------------------------------------

#: The keys a row may carry beyond the canonical five, in the order they are
#: written.  One declared order means a row's shape is the same wherever it
#: was authored, so a reader compares rows instead of re-reading key names.
_EXTRA_ORDER = (
    "step",
    "choices",
    "max_items",
    "state",
    "rotation",
    "legacy_bool",
    "legacy_keys",
)


def _option(
    kind: str,
    key: str,
    default: Any,
    label: str,
    *,
    minimum: float | None,
    maximum: float | None,
    extra: dict[str, Any],
) -> dict[str, Any]:
    """One OPTIONS row in the canonical key order."""
    row: dict[str, Any] = {"key": key, "type": kind, "default": default}
    if minimum is not None:
        row["min"] = minimum
    if maximum is not None:
        row["max"] = maximum
    row["label"] = label
    for name in _EXTRA_ORDER:
        if name in extra:
            row[name] = extra.pop(name)
    row.update(extra)
    return row


def bool_option(key: str, default: bool, label: str, **extra: Any) -> dict[str, Any]:
    """A checkbox row: a piece of fight state the user turns on or off."""
    return _option("bool", key, default, label, minimum=None, maximum=None, extra=extra)


def int_option(
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
    label: str,
    **extra: Any,
) -> dict[str, Any]:
    """A whole-count row (stacks, casts, targets) and the range it accepts."""
    return _option(
        "int", key, default, label, minimum=minimum, maximum=maximum, extra=extra
    )


def float_option(
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
    label: str,
    **extra: Any,
) -> dict[str, Any]:
    """A fractional row (shares, seconds, uptimes) and the range it accepts."""
    return _option(
        "float", key, default, label, minimum=minimum, maximum=maximum, extra=extra
    )
