"""Sourced Summoner's Rift lane-minion base stats, and the gap beside them.

Every number here is transcribed from a CommunityDragon character binary
tracked under ``data/bin/characters/sru_{chaos,order}minion{melee,ranged,
siege,super}.bin.json`` (fetched from
``https://raw.communitydragon.org/latest/game/data/characters/<name>/<name>.bin.json``,
the same route ``data/bin/README.md`` records for ``gnarbig.bin.json``).
``tests/test_minion_stats.py`` re-reads those files and pins every constant
below against them, so a transcription error fails a test rather than
riding in a call site.

Two properties of the source shape this module, and both are the reason it
exists rather than a dict of numbers somewhere:

**The stat block is team-independent.** ``SRU_ChaosMinionMelee`` and
``SRU_OrderMinionMelee`` carry byte-identical stat fields; they differ only
in display name, tooltip key, health-bar height and selection height. Both
teams' files are tracked and the test compares them field by field, so this
is a checked property, not an assumption — a patch that splits them fails
the test instead of silently pricing one team's minion for both.

**Magic resistance is not in the source at all.** No minion record carries
``baseSpellBlockModifiable``, and the substring ``spellblock`` occurs zero
times across all eight files. A lane minion's magic resistance is therefore
*unknown here*, not zero: :func:`sourced_stat` raises for it. Writing 0.0
would be the exact failure mode CLAUDE.md's fail-closed rule names, and it
would be invisible — every magic-damage number against a minion would look
plausible and be unsourced.

Two further fields are absent from single records rather than from all of
them, and are handled the same way: ``attackSpeedRatioModifiable`` is not
present in the siege record (it is present for melee, ranged and super),
so the siege attack-speed ratio is unavailable.

Time scaling — the wave upgrades — is a separate, larger gap with its own
receipt: see :data:`MINION_SCALING_AUTHORITY`. The short version is that
the upgrade table is machine-readable but *ambiguous*: eight candidate
configurations exist and nothing reachable binds one of them to Classic
Summoner's Rift, so no accessor scales a stat by elapsed time.
Consequently every constant in this module is a **spawn-time** stat, and
:data:`MINION_BASE_STATS` must never be read as "the minion's stats at
minute N".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .application_errors import ApplicationError

#: The four Summoner's Rift lane-minion kinds, spelled as the character
#: records spell them.  ``"ranged"`` is the source's own word for the unit
#: the wiki calls a caster minion; no alias is accepted, because an alias
#: table is a place for a silent mismatch to live.
MINION_TYPES = ("melee", "ranged", "siege", "super")

#: The two team prefixes.  Both files are tracked and compared; the stat
#: block itself is keyed by type alone because the comparison passes.
MINION_TEAMS = ("chaos", "order")

#: Client dump these records were read from, matching the other
#: binary-backed receipts in this repo.
SOURCE_PATCH = "16.15.8024387"


class MinionStatUnavailable(ApplicationError):
    """A requested minion stat is not stated by the cached record."""

    error_code = "minion_stat_unsourced"


@dataclass(frozen=True)
class SourcedMinionBaseStats:
    """One minion type's spawn-time stats, as its record states them.

    ``attack_speed_ratio`` is ``None`` where the record omits the field.
    ``None`` means *the source does not state this*, never zero — read it
    through :func:`sourced_stat`, which raises, rather than directly.
    """

    minion_type: str
    record: str
    health: float
    attack_damage: float
    armor: float
    attack_speed: float
    attack_range: float
    move_speed: float
    health_regen: float
    gold_on_death: float
    experience_on_death: float
    critical_strike_damage_multiplier: float
    attack_speed_ratio: float | None


# The record field each stat is transcribed from.  One home: the accessor
# names it in its failure text and tests/test_minion_stats.py reads the
# binaries through it, so a stat cannot be pinned against a different field
# than the one the error message cites.
SOURCE_FIELDS: Mapping[str, str] = {
    "health": "baseHPModifiable",
    "attack_damage": "baseDamageModifiable",
    "armor": "baseArmorModifiable",
    "attack_speed": "attackSpeedModifiable",
    "attack_speed_ratio": "attackSpeedRatioModifiable",
    "attack_range": "attackRangeModifiable",
    "move_speed": "baseMoveSpeedModifiable",
    "health_regen": "baseStaticHPRegenModifiable",
    "gold_on_death": "goldGivenOnDeath",
    "experience_on_death": "expGivenOnDeath",
    "critical_strike_damage_multiplier": "critDamageMultiplier",
}

# Stats a caller may reasonably ask a target for that NO minion record
# states.  The mapping is stat -> the record field searched for it, so the
# denial can say what was looked for instead of only what was missing.
# ``magic_resistance`` is the load-bearing one: the fight model needs a
# target MR for every magic-damage instance, and this module refuses to
# supply one rather than defaulting it.
ABSENT_FROM_EVERY_RECORD: Mapping[str, str] = {
    "magic_resistance": "baseSpellBlockModifiable",
}


_MELEE = SourcedMinionBaseStats(
    minion_type="melee",
    record="Characters/SRU_ChaosMinionMelee/CharacterRecords/Root",
    health=430.0,
    attack_damage=11.0,
    armor=0.0,
    attack_speed=1.25,
    attack_range=110.0,
    move_speed=350.0,
    health_regen=0.0,
    gold_on_death=20.0,
    experience_on_death=62.0,
    critical_strike_damage_multiplier=2.0,
    attack_speed_ratio=1.25,
)

_RANGED = SourcedMinionBaseStats(
    minion_type="ranged",
    record="Characters/SRU_ChaosMinionRanged/CharacterRecords/Root",
    health=275.0,
    attack_damage=19.5,
    armor=0.0,
    # The record stores a 32-bit float; both values below are the exact
    # doubles that binary widens to, so the pin is equality, not a
    # tolerance that would hide a real patch change.
    attack_speed=0.6669999957084656,
    attack_range=550.0,
    move_speed=350.0,
    health_regen=0.0,
    gold_on_death=14.0,
    experience_on_death=31.0,
    critical_strike_damage_multiplier=2.0,
    attack_speed_ratio=0.6669999957084656,
)

_SIEGE = SourcedMinionBaseStats(
    minion_type="siege",
    record="Characters/SRU_ChaosMinionSiege/CharacterRecords/Root",
    health=750.0,
    attack_damage=36.0,
    armor=0.0,
    attack_speed=1.0,
    attack_range=300.0,
    move_speed=350.0,
    health_regen=0.0,
    gold_on_death=49.0,
    experience_on_death=75.0,
    critical_strike_damage_multiplier=2.0,
    # The siege record has no attackSpeedRatioModifiable field; the other
    # three do.  Unavailable, not 1.0 and not equal to attack_speed.
    attack_speed_ratio=None,
)

_SUPER = SourcedMinionBaseStats(
    minion_type="super",
    record="Characters/SRU_ChaosMinionSuper/CharacterRecords/Root",
    health=1500.0,
    attack_damage=180.0,
    armor=100.0,
    attack_speed=0.8500000238418579,
    attack_range=170.0,
    move_speed=350.0,
    health_regen=10.0,
    gold_on_death=49.0,
    experience_on_death=75.0,
    critical_strike_damage_multiplier=2.0,
    attack_speed_ratio=0.8500000238418579,
)

#: Spawn-time stats by minion type.  NOT stats at an arbitrary game time —
#: see :data:`MINION_SCALING_AUTHORITY`.
MINION_BASE_STATS: Mapping[str, SourcedMinionBaseStats] = {
    "melee": _MELEE,
    "ranged": _RANGED,
    "siege": _SIEGE,
    "super": _SUPER,
}


# The receipt for the half that did not land, kept in the shape
# champions/renata_glasc.py's BAILOUT_AUTHORITY established: a runtime
# contract flag, a named reason, and the evidence the denial cites.
#
# What was found: map11.bin.json (CommunityDragon,
# game/data/maps/shipping/map11/map11.bin.json) holds eight BarracksConfig
# entries, each with UpgradeIntervalSecs, UpgradesBeforeLateGameScaling and
# a units[].MinionUpgradeStats MinionUpgradeConfig carrying HPUpgrade,
# HPUpgradeLate, DamageUpgrade, DamageUpgradeLate, ArmorUpgrade,
# ArmorUpgradeGrowth, MagicResistanceUpgrade and the caps HpMaxBonus,
# DamageMax, ArmorMax.  The table is real and machine-readable.
#
# Why it is still not sourceable: those eight are four distinct
# configurations duplicated per team, and NOTHING reachable says which one
# Classic Summoner's Rift uses.  They differ in exactly the fields a
# calculation would need — the upgrade period is 90s in one pair, 60s in
# two, 40s in another — so choosing is not a rounding decision, it changes
# every scaled number.  The searched paths are listed below; each returned
# either nothing or a reference that does not exist.
#
# One near-miss worth keeping: the unhashed field {db0e9d5b} inside
# MinionUpgradeConfig holds 90.0, which reads like the 90-second upgrade
# cadence and is not — CommunityDragon's hash table resolves it to
# GoldMax.  The sibling {726ae049} is still unresolved and is not guessed
# at here.
MINION_SCALING_AUTHORITY: Mapping[str, object] = {
    "runtime_available": False,
    "reason": "barracks_config_not_bound_to_classic",
    "source_patch": SOURCE_PATCH,
    "table_found_at": (
        "game/data/maps/shipping/map11/map11.bin.json"
        " :: 8 x BarracksConfig / units[].MinionUpgradeStats"
    ),
    # The four distinct configurations, by the two fields that decide a
    # scaled number's cadence.  Entry keys are the binary's own unresolved
    # entry-name hashes, because they have no resolvable name.
    "candidates": (
        {
            "entries": ("{147211fb}", "{e61e55a3}"),
            "initial_spawn_seconds": 30.0,
            "upgrade_interval_seconds": 90.0,
            "upgrades_before_late_game_scaling": 5,
        },
        {
            "entries": ("{34854695}", "{e5d995ed}"),
            "initial_spawn_seconds": 50.0,
            "upgrade_interval_seconds": 60.0,
            "upgrades_before_late_game_scaling": 4,
        },
        {
            "entries": ("{40ee1f1a}", "{609d79ca}"),
            "initial_spawn_seconds": 50.0,
            "upgrade_interval_seconds": 60.0,
            "upgrades_before_late_game_scaling": 4,
        },
        {
            "entries": ("{4b1f14b9}", "{ac54b461}"),
            "initial_spawn_seconds": 30.0,
            "upgrade_interval_seconds": 40.0,
            "upgrades_before_late_game_scaling": 5,
        },
    ),
    # Every route tried to bind one candidate to Classic, and what it gave.
    "searched": (
        "hashes.binentries.txt + hashes.binhashes.txt"
        " -> all 8 entry-name hashes unresolved",
        "map11.bin.json referrer scan"
        " -> 0 referrers; each hash occurs exactly once, as its own key",
        "Maps/Shipping/Map11/Modes/CLASSIC .Configs"
        " -> 13 links, none of type BarracksConfig",
        "Maps/Shipping/Map11/Modes/CLASSIC .AdditionalPropertyDataPaths"
        " -> Maps/ModeSpecificData/{CLASSIC,WASD}, neither present in map11",
        "game/maps/modespecificdata/*.bin.json (15 modes incl. classic)"
        " -> 0 references, 0 BarracksConfig entries",
        "game/data/maps/shipping/common/common.bin.json -> 0 matches",
        "game/data/maps/mapgeometry/map11/ -> materials only",
        "fields BarracksLink / LinkedBarracks -> 0 occurrences in map11",
    ),
    # What a caller is refused until the binding is found.
    "denied_reads": (
        "wave_upgrade_count",
        "upgrade_interval_seconds",
    ),
}


def _require_type(minion_type: str) -> SourcedMinionBaseStats:
    """Resolve a minion type, failing closed on any other spelling."""
    stats = MINION_BASE_STATS.get(minion_type)
    if stats is None:
        raise KeyError(
            f"MINION_BASE_STATS[{minion_type!r}] does not exist; "
            f"the sourced types are {', '.join(MINION_TYPES)}"
        )
    return stats


def base_stats(minion_type: str) -> SourcedMinionBaseStats:
    """The spawn-time stat block for one minion type."""
    return _require_type(minion_type)


def sourced_stat(minion_type: str, stat: str) -> float:
    """One stat, or a named refusal when the record does not state it.

    Never returns a default.  The three refusals are a stat absent from
    every record (magic resistance), a stat absent from this one record
    (the siege attack-speed ratio), and a name no record has a field for.
    """
    stats = _require_type(minion_type)
    searched = ABSENT_FROM_EVERY_RECORD.get(stat)
    if searched is not None:
        raise MinionStatUnavailable(
            f"{stat!r} is not stated for any Summoner's Rift lane minion: "
            f"no minion character record carries {searched!r}. "
            "It is unknown, not zero; supply it explicitly or do not "
            "price it.",
            error_stat=stat,
            minion_type=minion_type,
            searched_field=searched,
            source_patch=SOURCE_PATCH,
        )
    field_name = SOURCE_FIELDS.get(stat)
    if field_name is None:
        raise KeyError(
            f"{stat!r} is not a minion stat; the sourced names are "
            f"{', '.join(sorted(SOURCE_FIELDS))}, and the known-absent "
            f"ones are {', '.join(sorted(ABSENT_FROM_EVERY_RECORD))}"
        )
    value = getattr(stats, stat)
    if value is None:
        raise MinionStatUnavailable(
            f"{stat!r} is not stated for the {minion_type} minion: "
            f"{stats.record} has no {field_name!r} field. "
            "It is unknown, not zero.",
            error_stat=stat,
            minion_type=minion_type,
            searched_field=field_name,
            record=stats.record,
            source_patch=SOURCE_PATCH,
        )
    return float(value)
