"""The one crowd-control vocabulary, its three partitions, and the control event a cast carries."""

from dataclasses import dataclass
from enum import Enum

# The ``cc_kind`` values that count as an immobilize — the Wiki's
# "Immobilizing" crowd-control class (airborne, forced actions, root,
# sleep, stasis, stun, suppression), the trigger for Imperial Mandate's
# Command and Fimbulwinter's non-melee Everlasting. A slow is crowd
# control but not an immobilize.
# https://wiki.leagueoflegends.com/en-us/Types_of_Crowd_Control
IMMOBILIZING_CC_KINDS = frozenset(
    {
        "immobilize",  # generic reviewed immobilize (kind not narrowed)
        "airborne",
        "charm",
        "fear",
        "flee",
        "knockback",
        "knockup",
        "pull",
        "root",
        "sleep",
        "snare",
        "stasis",
        "stun",
        "suppression",
        "taunt",
    }
)


# Crowd control that is neither an immobilize nor a slow. Each is real
# control a reviewer read off the Wiki, and none of them arms Command or
# Everlasting, so they narrow a part to "reviewed, and it triggers nothing".
# They exist because the alternative for Malphite's Ground Slam cripple,
# Malzahar's Call of the Void silence and Teemo's Blinding Dart blind was to
# call them "slow" or "none", and both of those are false.
# Polymorph blocks actions (``ACTION_BLOCKING_CC_KINDS``) but the target
# keeps moving, so it is not an immobilize for Everlasting / Command.
# "berserk" (Renata Glasc's Hostile Takeover) is here rather than above for
# the same reason polymorph is: a berserked unit keeps moving and keeps
# attacking — it attacks its own allies — so the Wiki's Immobilizing class
# does not hold it, and neither Command nor Everlasting arms on it.  It is a
# forced action, which is real reviewed control and not a slow, and calling
# it either of those would be false.
NON_IMMOBILIZING_CC_KINDS = frozenset(
    {"slow", "cripple", "silence", "blind", "polymorph", "berserk"}
)


# The reviewed *absence* of control, and the one vocabulary member that is
# not a control kind: it reaches the classifiers as the empty kind.
NO_CONTROL_KIND = "none"


# Every value a module may author as a part's ``cc_kind`` — the ONE
# vocabulary. Every other crowd-control set in the calculator is a
# classification over this one and must stay closed and total over it
# (tests/test_cc_kind_vocabulary.py is the guard). Anything outside it is a
# typo the engine rejects — a misspelled kind must never author a no-op stun.
CC_KIND_VOCABULARY = (
    IMMOBILIZING_CC_KINDS | NON_IMMOBILIZING_CC_KINDS | frozenset({NO_CONTROL_KIND})
)


# The Wiki's Airborne class: one forced displacement, named by the umbrella
# ("airborne") or by the subtype a module actually authors. An item whose
# tooltip carves out "Airborne" carves out all four, so the umbrella is
# resolved here rather than re-spelled at each cleanse declaration.
# https://wiki.leagueoflegends.com/en-us/Airborne
DISPLACEMENT_CC_KINDS = frozenset({"airborne", "knockback", "knockup", "pull"})


def cc_kind_reviewed(kind: str | None) -> bool:
    """Whether ``cc_kind`` is a reviewed classification — ``"none"`` included."""
    return kind is not None and str(kind).lower().strip() in CC_KIND_VOCABULARY


# These control types stop a champion from taking a normal action for the
# authored interval: every immobilize, plus the two kinds that lock a
# champion's actions while it keeps moving — polymorph, and Renata's
# berserk (a berserked champion's actions are the enemy's).
# https://wiki.leagueoflegends.com/en-us/Types_of_Crowd_Control
ACTION_BLOCKING_CC_KINDS = IMMOBILIZING_CC_KINDS | frozenset({"polymorph", "berserk"})


# The other half of the same classification: real control the target keeps
# acting under. Slows change movement, cripple attack speed, blind the
# outcome of a swing and silence the ability to cast — none of them is
# action downtime. The two halves must partition the vocabulary
# (tests/test_cc_kind_vocabulary.py), so a new kind cannot arrive unclassified.
NON_BLOCKING_CC_KINDS = frozenset({"blind", "cripple", "silence", "slow"})


class ControlScope(Enum):
    """How many of the fight's enemies one authored control holds.

    The roster evaluates the same damage package against every selected
    enemy, so a control with no recipient of its own lands on all of them.
    That is the area answer, and the wrong one for a targeted cast: Lulu's
    Whimsy is cast "onto the target enemy champion".

    ``ONE_TARGET`` is allocated exactly as a target-limited item proc is —
    to the lowest roster index — so one enemy holds the control and the
    rest of the roster is scored without it.
    """

    EVERY_TARGET = "every_target"
    ONE_TARGET = "one_target"

    def reaches(self, roster_target_index: int) -> bool:
        """Whether the pair fight against this roster index holds the control."""
        return self is ControlScope.EVERY_TARGET or roster_target_index == 0


@dataclass(frozen=True)
class ControlEvent:  # pylint: disable=too-many-instance-attributes
    """One authored control interval without a damage packet.

    Damage parts carry control metadata when damage and control land together.
    This atom covers a control-only cast such as a trap or a stun field.
    """

    kind: str
    duration: float
    #: The control's sourced strength in the units the cached row states
    #: it -- a slow's percent.  Zero where the kind has none.
    magnitude: float = 0.0
    time_offset: float | None = 0.0
    count: int = 1
    hit_interval: float | None = None
    skillshot: bool = False
    #: Who the control lands on.  Unscoped means every enemy the cast hit,
    #: which is the area cast's reviewed answer.
    scope: ControlScope = ControlScope.EVERY_TARGET

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("ControlEvent kind must be a non-empty string")
        if self.duration <= 0.0:
            raise ValueError("ControlEvent duration must be positive")
        if self.magnitude < 0.0:
            raise ValueError("ControlEvent magnitude cannot be negative")
        if self.time_offset is not None and self.time_offset < 0.0:
            raise ValueError("ControlEvent time_offset cannot be negative")
        if self.count < 1:
            raise ValueError("ControlEvent count must be positive")
        if self.hit_interval is not None and self.hit_interval < 0.0:
            raise ValueError("ControlEvent hit_interval cannot be negative")
        if self.count > 1 and self.hit_interval is None:
            raise ValueError("Repeated ControlEvent requires hit_interval")

    def __repr__(self) -> str:
        extras = ""
        if self.magnitude:
            extras += f", magnitude={self.magnitude}"
        if self.time_offset is not None:
            extras += f", time_offset={self.time_offset}"
        if self.count != 1:
            extras += f", count={self.count}"
        if self.hit_interval is not None:
            extras += f", hit_interval={self.hit_interval}"
        if self.skillshot:
            extras += ", skillshot=yes"
        if self.scope is not ControlScope.EVERY_TARGET:
            extras += f", scope={self.scope.value}"
        return f"ControlEvent({self.kind!r}, duration={self.duration}" f"{extras})"
