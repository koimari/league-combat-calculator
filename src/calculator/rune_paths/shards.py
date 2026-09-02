"""The three stat-shard rows.

Shards belong to no path, so they get their own module and their own key
shape: ``(row, name)``, because the same shard name appears in two rows
(Adaptive Force in rows 1 and 2, Health Scaling in rows 2 and 3) and the two
are different selections.

A compiler takes the cached shard-option record — the same
``{name, description, effects}`` shape a rune entry carries — from
``rune_effects.RUNE_SHARDS``, and returns one ``rune_effects`` effect, almost
always a ``RuneStatGrantEffect``.

Eight of the nine grant into a channel ``stats.py`` reads, so they are stat
grants priced from the cached table and nothing else. The ninth is tenacity
and slow resist: the closed ``RuneStat`` set holds no channel for it because
no engine number reads one — the fight prices a rotation, and carries no
crowd-control duration to shorten — so it compiles to the disclosure kind,
selectable and receipted rather than silently worth zero.

No shard declares an option: every one of them states a number the cache
carries, gated on nothing, so this module has no ``OPTIONS`` to merge.
"""

from collections.abc import Callable, Mapping
from typing import Any

from ..ability_spec import Disposition
from ..rune_effects import (
    RuneEffect,
    RuneStat,
    RuneStatContext,
    RuneStatGrantEffect,
    RuneValues,
    at_level,
    no_damage_compiler,
    required_leveling,
    shard_row_name,
)

ShardCompiler = Callable[[Mapping[str, Any]], RuneEffect]

#: Which channel each flat shard grants into, and the cached key that
#: carries its size. The names are the wiki's own spelling — the ability
#: haste shard is "Cooldown Reduction" on the Rune page, and renaming it
#: here would put a second name on one fact.
_FLAT_GRANTS: Mapping[tuple[int, str], tuple[RuneStat, str]] = {
    (1, "Adaptive Force"): (RuneStat.ADAPTIVE_FORCE, "adaptive_force"),
    (1, "Attack Speed"): (RuneStat.ATTACK_SPEED_PERCENT, "attack_speed_percent"),
    (1, "Cooldown Reduction"): (RuneStat.ABILITY_HASTE, "ability_haste"),
    (2, "Adaptive Force"): (RuneStat.ADAPTIVE_FORCE, "adaptive_force"),
    (2, "Movement Speed"): (RuneStat.MOVE_SPEED_PERCENT, "move_speed_percent"),
    (3, "Health"): (RuneStat.BONUS_HEALTH, "bonus_health"),
}

#: The shards whose size is a per-level table rather than one number. Both
#: rows offer the same health scaling, and taking both is two grants.
_LEVELED_GRANTS: Mapping[tuple[int, str], RuneStat] = {
    (2, "Health Scaling"): RuneStat.BONUS_HEALTH,
    (3, "Health Scaling"): RuneStat.BONUS_HEALTH,
}

#: What a shard grant discloses beyond its number, keyed the same way. Only
#: movement speed needs words: it lands in a stat the engine publishes and
#: in no damage number, and a reader comparing two pages deserves to be told
#: which of those two happened.
_GRANT_DISCLOSURES: Mapping[tuple[int, str], tuple[str, ...]] = {
    (2, "Movement Speed"): (
        "The movement speed shard raises the build's movement speed and no "
        "damage number: the fight engine prices a rotation, not the "
        "positioning that reaches it.",
    ),
}

#: The one shard with no engine channel at all: disposition, the reason that
#: becomes its receipt, and the half this engine refuses.
_NO_DAMAGE: Mapping[tuple[int, str], tuple[Disposition, str, tuple[str, ...]]] = {
    (3, "Tenacity and Slow Resist"): (
        Disposition.WITHHELD,
        "tenacity and slow resist both shorten crowd control, and the fight "
        "engine carries no crowd-control duration to shorten — it prices a "
        "rotation against a target's health and resistances",
        (
            "The cache parses no number out of this shard's description "
            "either, so no figure the engine could have spent is being "
            "held back.",
        ),
    ),
}


def _shard_name(row: int, name: str) -> str:
    """One shard's receipt name, row included: a name alone can be two shards."""
    return f"{shard_row_name(row)} shard: {name}"


def _flat_grant_compiler(
    row: int, name: str, stat: RuneStat, key: str
) -> ShardCompiler:
    """Compile a shard granting one cached amount into one stat channel."""

    def compile_shard(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
        shard = _shard_name(row, name)
        granted = RuneValues(shard, entry.get("effects", {})).number(key)

        def amount(context: RuneStatContext) -> float:
            del context  # a flat shard reads nothing about the build
            return granted

        return RuneStatGrantEffect(
            rune_name=shard,
            stat=stat,
            amount=amount,
            disclosures=_GRANT_DISCLOSURES.get((row, name), ()),
        )

    return compile_shard


def _leveled_grant_compiler(row: int, name: str, stat: RuneStat) -> ShardCompiler:
    """Compile a shard whose grant is a per-level table (health scaling)."""

    def compile_shard(entry: Mapping[str, Any]) -> RuneStatGrantEffect:
        shard = _shard_name(row, name)
        by_level = required_leveling(shard, RuneValues(shard, entry.get("effects", {})))

        def amount(context: RuneStatContext) -> float:
            return at_level(by_level, context.level)

        return RuneStatGrantEffect(
            rune_name=shard,
            stat=stat,
            amount=amount,
            disclosures=_GRANT_DISCLOSURES.get((row, name), ()),
        )

    return compile_shard


def _no_damage_shard_compiler(
    row: int, name: str, declaration: tuple[Disposition, str, tuple[str, ...]]
) -> ShardCompiler:
    """Compile a shard this engine holds no channel for, receipt and all.

    The name resolves at compile time, not import time: the row's name is a
    cache read and this table is built before any request proves the cache."""

    def compile_shard(entry: Mapping[str, Any]) -> RuneEffect:
        return no_damage_compiler(_shard_name(row, name), *declaration)(entry)

    return compile_shard


COMPILERS: dict[tuple[int, str], ShardCompiler] = {
    **{
        (row, name): _flat_grant_compiler(row, name, stat, key)
        for (row, name), (stat, key) in _FLAT_GRANTS.items()
    },
    **{
        (row, name): _leveled_grant_compiler(row, name, stat)
        for (row, name), stat in _LEVELED_GRANTS.items()
    },
    **{
        (row, name): _no_damage_shard_compiler(row, name, declaration)
        for (row, name), declaration in _NO_DAMAGE.items()
    },
}
