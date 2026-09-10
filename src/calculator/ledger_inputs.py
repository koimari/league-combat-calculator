"""The narrowed result row and the typed facts a projection decision reads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, NamedTuple, Protocol

from .ledger_declarations import DECLARATIONS, AdequacyCondition, UndeclaredStatRead
from .rune_effects import RunePage
from .trigger_stream import ChampionSlotOwner


class ResultProjection(Enum):
    """One shape a pair fight's result may be returned in.

    Four members and two questions.  The ledger pair answers "may this
    fight's damage events be positional tuples"; the shield pair answers "may
    the one-pair shield outcome be skipped".  Naming the wide member of each
    pair rather than treating it as "not the narrow one" is what lets
    :data:`_UNSERVED` be total over the enum: a projection that serves every
    reader declares an empty unserved set, which is a statement, where an
    absent entry would be a hole.
    """

    LIGHT_TUPLE_LEDGER = "light_tuple_ledger"
    DICT_ROW_LEDGER = "dict_row_ledger"
    SKIPPED_SHIELD_OUTCOME = "skipped_shield_outcome"
    RESOLVED_SHIELD_OUTCOME = "resolved_shield_outcome"


class LightRow(NamedTuple):
    """One positional row of the light tuple ledger, by name.

    The light ledger is one of the two shapes
    :attr:`ResultProjection.LIGHT_TUPLE_LEDGER` names, and this is the
    whole of what it carries.  Declared here, beside the projection that
    decides when a fight may be served in it, so the engine that writes
    the rows, the compiler that walks them and a test that compares them
    against the dict shape all read one statement of the layout rather
    than three agreeing sets of indices.

    A tuple subclass on purpose: ``LightRow._make(row)`` names the
    positions without building a dict, which the compiler does tens of
    thousands of times per request.
    """

    sort_key: tuple[Any, ...]
    damage: float
    damage_type: str
    source_key: str
    raw_formula: Any
    raw_damage: float
    declared: Any


#: The light row fields a dict row spells the same way.  A reader holding
#: both shapes compares exactly these; everything else is either the dict
#: row's receipt metadata or the light row's packed sort key.
SHARED_ROW_FIELDS: tuple[str, ...] = (
    "damage",
    "damage_type",
    "source_key",
    "raw_damage",
)


class ThresholdHealFacts(Protocol):  # pylint: disable=too-few-public-methods
    """The one fact both gates' shared condition is derived from.

    A structural type rather than a base class: the two input records below
    are independent and neither should inherit from the other, but the probe
    they share must be *one function*, so what it accepts is the field it
    reads and nothing more.
    """

    target_threshold_health_heal: float


class HeldItemFacts(Protocol):  # pylint: disable=too-few-public-methods
    """The held build, as the name list every item-keyed projection reads."""

    item_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShieldOutcomeInputs:
    """The facts the one-pair shield outcome's readers are decided by.

    Deliberately narrower than :class:`LedgerInputs`: the damage engine holds
    no champion name and no self-heal declaration at the point it decides
    whether to resolve the shield outcome, and a record with fields it could
    only fill with a placeholder would make an unrelated condition answer
    "no demand" for the wrong reason.
    """

    item_names: tuple[str, ...]
    target_threshold_health_heal: float


@dataclass(frozen=True, slots=True)
class LedgerInputs:  # pylint: disable=too-many-instance-attributes
    """The facts the damage ledger's readers are decided by.

    ``self_heal_rule`` is the champion half of the answer, supplied as a
    typed owner by ``healing.self_heal_rule_owner`` rather than as a name
    this module checks against a set: the registry that knows which champions
    declare a rule is the registry that should say so, and it imports the
    champion package, which this leaf must not.  It is also the only champion
    fact here, so a bare ``champion_name`` beside it would be a field with no
    reader.
    """

    self_heal_rule: ChampionSlotOwner | None
    item_names: tuple[str, ...]
    stats: Mapping[str, Any]
    damage_effects: Any
    ability_damages: Mapping[str, Any]
    rune_page: RunePage
    fight_duration_seconds: float
    is_melee: bool
    target_threshold_health_heal: float

    # Uncoerced: the regen condition treats an unparseable stat as a demand
    # and the vamp conditions treat it as no demand, so a shared coercion
    # here would silently pick one of them.
    def raw_stat(self, condition: AdequacyCondition, field: str) -> object:
        """One declared champion stat, uncoerced, or a refusal."""
        if field not in DECLARATIONS[condition].requires_fields:
            raise UndeclaredStatRead(condition, field)
        return self.stats.get(field, 0.0)
