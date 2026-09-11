"""What one fight is configured to be, and the specs a user's option selections resolve through."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import cache
from types import MappingProxyType
from typing import Any

from .. import item_effects, minion_stats, rune_effects
from ..attack_windows import AttackSpeedWindow
from ..combat_events import CombatEvent
from ..champions import get_champion_options_meta

# Critical strikes deal 200% base damage (this changed once before, from
# 175%). Items add on top via crit_damage_bonus; anything recovering the
# item bonus from a total multiplier must subtract this same constant.
BASE_CRIT_MULTIPLIER = 2.0


def _declared_options(meta: Mapping[str, Any], owner: str) -> Mapping[str, Any]:
    """The option block one meta provider declares for an owner."""
    return meta[owner]["options"] if owner in meta else {}


# Where each family of user options declares its own spec.  The engine never
# restates an option's default: it reads the one the spec declares.
_OPTION_SPECS: dict[str, Callable[[str], Mapping[str, Any]]] = {
    "champion": lambda owner: {
        str(option["key"]): option
        for option in get_champion_options_meta(owner)["options"]
    },
    "item": lambda owner: _declared_options(
        item_effects.item_input_options_meta(), owner
    ),
    "keystone": lambda owner: _declared_options(
        rune_effects.keystone_input_options_meta(), owner
    ),
}


@cache
def declared_option_spec(family: str, owner: str, key: str) -> Mapping[str, Any]:
    """One OPTIONS spec entry, the home of its default and its bounds.
    An option the spec does not declare is a data error, not a zero: the
    engine would otherwise price a state nobody can select."""
    spec = _OPTION_SPECS[family](owner).get(key)
    if not isinstance(spec, Mapping) or "default" not in spec:
        raise KeyError(f"{family} option {owner}.{key} declares no default")
    return spec


def declared_option_default(  # sightline-ok: 1 - key-typed read
    family: str, owner: str, key: str
) -> Any:
    """The value an unset option prices at, as its own spec declares it."""
    return declared_option_spec(family, owner, key)["default"]


def _seeded_option_stacks(
    options: Mapping[str, Any], family: str, owner: str, key: str
) -> int:
    """One integer stack option, defaulted and bounded by its own spec.

    A blank or unparsable selection is the unset one.  The bounds are the
    spec's own ``min``/``max``, so the cap lives beside the control the user
    turns rather than beside each walk that seeds from it.
    """
    spec = declared_option_spec(family, owner, key)
    default = spec["default"]
    try:
        seeded = int(options.get(key, default) or default)
    except (TypeError, ValueError):
        seeded = int(default)
    return max(int(spec["min"]), min(seeded, int(spec["max"])))


#: The ``FightConfig`` target fields a named lane minion decides, and the
#: ``minion_stats`` stat each one reads.  ``None`` marks a field the source
#: settles by construction rather than through a field of its own: a lane
#: minion's character record states one stat block and no minion grants
#: itself a bonus, so all of its health and armor is BASE and the bonus is
#: 0.0.  That is a different claim from "unsourced, so assume zero" — magic
#: resistance IS unsourced, and is absent from this table because
#: ``minion_stats.sourced_stat`` raises for it rather than answering 0.0.
#:
#: One table, both directions: :meth:`FightConfig.for_minion` FILLS exactly
#: these fields and :meth:`FightConfig._validate_minion_target` REFUSES any
#: other answer for them, so a field cannot be filled without also being
#: pinned, nor pinned without being filled.
MINION_SOURCED_TARGET_FIELDS: Mapping[str, str | None] = MappingProxyType(
    {
        "target_health": "health",
        "target_armor": "armor",
        "target_bonus_health": None,
        "target_bonus_armor": None,
    }
)


def sourced_minion_target(minion_type: str) -> dict[str, float]:
    """Every fight-target field the named lane minion decides for itself.

    Raises through ``minion_stats`` for a type no character record names,
    so a misspelling can never arrive as a silently caller-shaped target.
    """
    return {
        field_name: (
            0.0 if stat is None else minion_stats.sourced_stat(minion_type, stat)
        )
        for field_name, stat in MINION_SOURCED_TARGET_FIELDS.items()
    }


@dataclass(frozen=True)
class FightConfig:
    """Everything configurable about one fight, in one spelling.

    Pure configuration — champion_stats / ability_damages / items are
    DATA and stay positional arguments to the engine. Defaults mirror
    the engine's historical keyword defaults.
    """

    target_health: float
    target_armor: float
    target_magic_resistance: float
    fight_duration_seconds: float
    target_bonus_health: float = 0.0
    # None = split unknown; the quick-scenario total-pen reading applies
    # to percent BONUS penetration (LDR family).
    target_bonus_armor: float | None = None
    auto_attack_uptime: float = 0.0
    auto_attack_uptime_mode: str = "legacy"
    rotation_count: int = 1
    one_rotation: bool = False
    include_actives: bool = True
    # Whether damage a cast lights inside the window but lands after it
    # counts: a fused bomb, a channel's payload, a DoT's remaining ticks, a
    # burn's tail. True is the action-window reading (the fight is when you
    # act; what you lit finishes); False clips every landing at the end.
    count_damage_after_fight_end: bool = True
    cast_order: list[str] | None = None
    combat_events: tuple[CombatEvent, ...] | None = None
    combat_events_mode: str = "replace"
    event_actor_id: str = "main"
    event_target_id: str = ""
    event_attack_speed_windows: tuple[AttackSpeedWindow, ...] = ()
    auto_attacks_only: bool = False
    # Whether the timed scheduler may recast R on its (hasted) cooldown.
    # Set from the champion module's reviewed ``ULTIMATE_RECASTS``
    # certification by ``pipeline.run_fight``; False is the conservative
    # one-cast rule every uncertified kit keeps, and the default so a
    # direct engine caller never silently gains extra ultimate casts.
    ultimate_recasts: bool = False
    deterministic: bool = False
    target_magic_shield: float = 0.0
    target_physical_shield: float = 0.0
    target_general_shield: float = 0.0
    target_basic_damage_multiplier: float = 1.0
    target_basic_damage_flat_reduction: float = 0.0
    target_basic_damage_flat_reduction_cap: float = 0.0
    target_physical_damage_flat_reduction: float = 0.0
    target_physical_damage_flat_reduction_cap: float = 0.0
    target_champion_damage_flat_reduction: float = 0.0
    target_champion_dot_damage_flat_reduction: float = 0.0
    target_critical_strike_damage_multiplier: float = 1.0
    # Target-side auras such as Frozen Heart reduce the attacker's total
    # attack speed before the authored swing schedule is compiled.
    attacker_attack_speed_multiplier: float = 1.0
    target_threshold_shield_amount: float = 0.0
    target_threshold_shield_health_ratio: float = 0.0
    target_threshold_shield_duration: float = 0.0
    target_threshold_shield_damage_type: str = "all"
    target_threshold_health_bonus: float = 0.0
    target_threshold_health_heal: float = 0.0
    target_threshold_health_ratio: float = 0.0
    target_threshold_health_duration: float = 0.0
    enforce_resource_limits: bool = False
    # Ordered external resource restores (time, amount) are supplied by the
    # coupled participant ledger for items such as Catalyst of Aeons.  The
    # engine consumes them before a simultaneous cast is admitted; ordinary
    # one-pair callers leave this empty.
    resource_restore_events: tuple[tuple[float, float], ...] = ()
    # Account owner for the typed mana resource ledger (P3 slice 1).  The
    # one-pair engine defaults to "main"; the coupled participant timeline
    # keys each attacker's fight by its participant id.
    resource_ledger_owner: str = "main"
    roster_target_index: int = 0
    roster_target_count: int = 1
    # Whether a roster composition consumes this fight.  It drops the rows
    # whose mechanic ``program.build.dropped_preview_mechanics`` names and
    # prices those mechanics on the coupled walk instead, so the engine can
    # skip computing them.  A one-pair caller is the surface where the
    # preview is the answer, and leaves this False.
    roster_composed: bool = False
    # The rune page, by name — the keystone ("" = none), the minor runes,
    # the positional stat shards (entry i is shard row i+1), and the explicit
    # options a rune declares.  Resolution fails closed in rune_effects for
    # anything unknown or unmodeled; the config holds names, not compiled
    # effects, so it stays a value object.
    keystone: str = ""
    minor_runes: tuple[str, ...] = ()
    stat_shards: tuple[str, ...] = ()
    rune_options: dict[str, dict[str, float]] | None = None
    # Explicit state inputs for the selected keystone. The parser validates
    # this mapping before it reaches the fight engine.
    keystone_options: Mapping[str, int | float] = field(default_factory=dict)
    # P3-3M: the target's actor CLASS.  "champion" is the 1v1 model and the
    # default for every existing caller; "minion" arms the sourced
    # minion-only item branches (Doran's Helm's Helping Hand).  Unknown
    # spellings fail closed.
    target_class: str = item_effects.DEFAULT_TARGET_CLASS
    # Which lane minion, when the target class is "minion".  "" leaves the
    # target caller-shaped (a minion LABEL over caller-supplied stats) and is
    # the default for every existing caller.  A named type binds the fields
    # MINION_SOURCED_TARGET_FIELDS lists to the minion's own spawn-time
    # record: build such a config through FightConfig.for_minion, which fills
    # them, and __post_init__ then REFUSES any config that claims a type
    # while carrying some other target's numbers.  Magic resistance is NOT
    # among them and stays caller-supplied, because no minion character
    # record states one — see minion_stats.
    minion_type: str = ""

    @classmethod
    def for_minion(
        cls,
        minion_type: str,
        *,
        target_magic_resistance: float,
        fight_duration_seconds: float,
        **overrides: Any,
    ) -> "FightConfig":
        """A fight whose target IS the named lane minion, at spawn-time stats.

        The durability fields come from the minion's own character record —
        no call site spells its health or armor — and supplying one of them
        here is refused rather than merged, so "sourced" and "caller-supplied"
        never both answer for one field.

        ``target_magic_resistance`` has no default because it is the one
        durability stat no minion record states; a default here would put an
        invented magic resistance behind a sourced-looking constructor, which
        is the failure :mod:`minion_stats` exists to prevent.
        """
        sourced = sourced_minion_target(minion_type)
        # "minion_type" needs no entry here: it is a named parameter above, so
        # passing it again raises before this runs.
        collisions = sorted(set(overrides) & (set(sourced) | {"target_class"}))
        if collisions:
            raise ValueError(
                f"for_minion({minion_type!r}) decides {', '.join(collisions)}; "
                "the sourced target fields are "
                f"{', '.join(sorted(sourced))} and the class is fixed. "
                "Pass a champion-class FightConfig instead of overriding them."
            )
        return cls(
            target_magic_resistance=target_magic_resistance,
            fight_duration_seconds=fight_duration_seconds,
            target_class=item_effects.MINION_TARGET_CLASS,
            minion_type=minion_type,
            **sourced,
            **overrides,
        )

    @property
    def rune_page(self) -> "rune_effects.RunePage":
        """The four rune fields as the one page object they describe."""
        return rune_effects.RunePage(
            keystone=self.keystone,
            minor_runes=tuple(self.minor_runes),
            stat_shards=tuple(self.stat_shards),
            options=self.rune_options or {},
        )

    def __post_init__(self) -> None:
        """Reject a target the fight model cannot represent."""
        if self.target_class not in item_effects.TARGET_CLASSES:
            raise ValueError(
                "target_class must be one of "
                f"{', '.join(item_effects.TARGET_CLASSES)}; "
                f"got {self.target_class!r}"
            )
        self._validate_minion_target()

    def _validate_minion_target(self) -> None:
        """Hold a named minion type to its own sourced stat block.

        Three refusals, each a silent-error class: a type no character
        record names, a minion type on a champion-class fight, and a target
        field that disagrees with the source the type claims.
        """
        if not self.minion_type:
            return
        if self.minion_type not in minion_stats.MINION_TYPES:
            raise ValueError(
                "minion_type must be one of "
                f"{', '.join(minion_stats.MINION_TYPES)}; "
                f"got {self.minion_type!r}"
            )
        if self.target_class != item_effects.MINION_TARGET_CLASS:
            raise ValueError(
                f"minion_type={self.minion_type!r} requires "
                f"target_class={item_effects.MINION_TARGET_CLASS!r}; "
                f"got {self.target_class!r}"
            )
        record = minion_stats.base_stats(self.minion_type).record
        for field_name, sourced in sourced_minion_target(self.minion_type).items():
            supplied = getattr(self, field_name)
            if supplied is not None and float(supplied) == sourced:
                continue
            stat = MINION_SOURCED_TARGET_FIELDS[field_name]
            cited = (
                f"{stat}={sourced!r}, {minion_stats.SOURCE_FIELDS[stat]} in {record}"
                if stat is not None
                else f"{sourced!r}, since all of a spawn-time minion's "
                f"durability is base ({record} states no bonus)"
            )
            raise ValueError(
                f"{field_name}={supplied!r} contradicts the sourced "
                f"{self.minion_type} minion ({cited}). Build a sourced-minion "
                "fight with FightConfig.for_minion, which fills these fields; "
                "it does not accept a second answer for them."
            )
