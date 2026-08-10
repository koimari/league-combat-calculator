"""The champion→engine ability-damage contract and the closed vocabularies.

An ability entry carries its damage arithmetic as a tuple of DamageParts;
the fight engine evaluates parts generically
(``damage._evaluate_cast_parts``) and never branches on
champion-specific keys. Champion-unique scaling math lives in the
champion module as a ``hp_scaled_damage`` closure on the part.

This module is a dependency-free leaf between the champion layer and the
fight engine: both import the contract, neither imports the other. That
is also why the campaign's four closed vocabularies live here —
``DamageClass``, ``AttackClass``, ``Disposition`` and ``Authority`` are
declared once, in the one module every layer may import, so no consumer
has to re-spell a member as a bare string.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class DamageClass(Enum):
    """Which resistance mitigates a number.

    The string values are the engine's own spellings, so
    ``part_damage_types()`` is the enum's projection rather than a second
    list that can drift from it.
    """

    MAGIC = "magic"
    PHYSICAL = "physical"
    TRUE = "true"


class AttackClass(Enum):
    """How a number was delivered, independent of what mitigates it.

    A damage-restricted mechanic declares both axes: Abyssal Mask's Unmake
    is ``{MAGIC}`` from every attack class ("from all sources"), while a
    basic-attack-only amplifier is every damage class from
    ``{BASIC_ATTACK}``. ``OTHER`` covers damage that is neither — item
    procs, burns and the environment.
    """

    BASIC_ATTACK = "basic_attack"
    ABILITY = "ability"
    OTHER = "other"


class Disposition(Enum):
    """What a numeric leaf *is* — the campaign's one invariant, as a type.

    A number the model did not compute must never be indistinguishable
    from a number the model computed as zero, so every serialized leaf is
    exactly one of these:

    * ``MEASURED`` — a rule ran against adequate inputs and produced this
      value, zero included.
    * ``STRUCTURAL_ZERO`` — a declaration says the mechanic does not apply
      here; zero is the answer and the declaration is the receipt.
    * ``WITHHELD`` — coverage refused to model it: a named receipt and no
      number.
    * ``STARVED`` — a projection could not answer the question a rule
      asked. A programming error.

    Each member's value is its own name, because these spellings are also
    receipt strings and reason prefixes: a symbol and its serialized form
    cannot drift when they are one string.
    """

    MEASURED = "MEASURED"
    STRUCTURAL_ZERO = "STRUCTURAL_ZERO"
    WITHHELD = "WITHHELD"
    STARVED = "STARVED"


class Authority(Enum):
    """Which engine owns a mechanic — the pair engine, the coupled walk, or both.

    Authority belongs to the smallest engine that can see every input the
    mechanic's rule reads: all-pair-local inputs are ``PAIR_ONLY``, and any
    roster input (another participant's damage, another holder's stacks,
    the subject's live HP under combined fire) is coupled-authoritative.

    * ``PAIR_ONLY`` — every input is pair-local.
    * ``SPLIT`` — the pair-local restriction of the rule is exactly the
      holder's own contribution, the two halves are provably disjoint, and
      the owner skip is machine-checked. This is the only member that
      carries an ``owner``.
    * ``COUPLED_AUTHORITATIVE`` — the coupled walk owns it outright.
    * ``COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW`` — the walk owns the
      applied number and a pair-side preview survives, tagged theoretical
      so it is never summed into the coupled total.
    * ``COUPLED_ONLY`` — the walk owns it and no pair-side half exists at
      all.

    Declared here in 0A because 0B declares members on packets before
    ``trigger_stream`` — the eventual re-export home — exists.
    """

    PAIR_ONLY = "PAIR_ONLY"
    SPLIT = "SPLIT"
    COUPLED_AUTHORITATIVE = "COUPLED_AUTHORITATIVE"
    COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW = "COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW"
    COUPLED_ONLY = "COUPLED_ONLY"


# The projection every DamagePart is validated against, computed from the
# enum once at import: the vocabulary has one home (DamageClass) and this
# is its cached string view, not a second declaration of the same fact.
_PART_DAMAGE_TYPES = frozenset(damage_class.value for damage_class in DamageClass)


def part_damage_types() -> frozenset[str]:
    """The string projection of ``DamageClass``.

    The engine and the champion layer speak damage types as strings; this
    is the only place those strings come from, so a fourth damage class is
    added to the enum and nowhere else.
    """
    return _PART_DAMAGE_TYPES


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

# Every value a module may author as a part's ``cc_kind``. "slow" is real
# crowd control that never counts as an immobilize; "none" is an explicit
# reviewed no-CC result. Anything else is a typo the engine rejects —
# a misspelled kind must never author a no-op stun.
CC_KIND_VOCABULARY = IMMOBILIZING_CC_KINDS | frozenset({"slow", "none"})


# The predicate that reads a raw row against the two constants above lives
# in ``trigger_stream``, not here: authoring vocabulary belongs beside
# ``DamagePart``, classification is transport.  This module keeps the
# vocabulary and nothing that reads an event with it.


@dataclass(frozen=True)
class DamagePart:  # pylint: disable=too-many-instance-attributes
    """One mitigation unit of one ability cast.

    The attribute-count check is disabled because this is a data record and
    the fields *are* the vocabulary: every one is a declared, documented
    mitigation axis a champion module names by keyword, and collapsing any
    of them into an untyped bag is the silent-default shape this module
    exists to refuse.  Same reasoning as ``trigger_stream``'s builder.

    The engine evaluates parts in order, threading the target's running
    mitigated damage: a part's ``hp_scaled_damage`` sees the damage of
    parts (and casts) evaluated before it — Akali R2 scales off the HP
    remaining after R1.

    A "mixed" ability is never a mixed PART — it is two typed parts,
    with the triggering (magic) part FIRST: the evaluator's first-part
    return is the Horizon Focus trigger for mixed entries.

    Attributes:
        damage_type: one of ``part_damage_types()``, the string projection
            of ``DamageClass`` (anything else raises at construction — a
            typo must never mitigate as magic).
        amount: Raw damage when ``hp_scaled_damage`` is None.
        count: Times the part hits per cast (Fox-Fire subsequent ×2).
        hp_scaled_damage: missing_ratio (0..1) → raw damage for one hit;
            overrides ``amount``.
        crit_effectiveness: >0 — the part crits at this effectiveness
            (Akshan R: 0.3).
        basic_damage: the part is classified basic damage in-game (a
            forced basic-attack swing, Caitlyn's Headshot rider) —
            basic-damage amplifiers (Hexoptics C44) apply to it.
        bonus_ad_ratio: raw damage this part gains per point of bonus AD
            granted MID-FIGHT, on top of what ``amount`` already prices
            (Darius' Noxian Might). It is the part's derivative in bonus
            AD, so a total-AD scaling declares its total-AD ratio.
            Ignored unless the fight grants such a buff — ``amount``
            alone remains the whole story for every static build.
        dot_stack_scaled: the part hits once per stacking-DoT stack on
            the target when the cast lands (Darius R's per-stack bonus).
            The fight engine ALWAYS resolves the count from the fight's
            stack timeline — no timeline means no stacks, so the part
            deals nothing and ``count`` is ignored. A champion that
            wants a fixed stack count says so with a plain part.
        time_offset: authored seconds from cast start to the first hit.
            ``None`` means the source has not certified sub-cast timing.
        hit_interval: authored seconds between repeated hits. Required for
            a repeated part to emit an exact event timeline.
    """

    damage_type: str
    amount: float = 0.0
    count: int = 1
    hp_scaled_damage: Callable[[float], float] | None = None
    crit_effectiveness: float = 0.0
    basic_damage: bool = False
    bonus_ad_ratio: float = 0.0
    dot_stack_scaled: bool = False
    time_offset: float | None = None
    hit_interval: float | None = None
    # Explicit crowd-control provenance for ordered item triggers.  ``None``
    # means the module has not reviewed this part's control effect; ``none``
    # is an explicit reviewed no-CC result.  The engine never infers control
    # from an ability name or description at runtime.
    cc_kind: str | None = None

    def __post_init__(self) -> None:
        if self.damage_type not in part_damage_types():
            raise ValueError(
                f"DamagePart damage_type must be one of "
                f"{sorted(part_damage_types())}, got {self.damage_type!r}"
            )
        if self.time_offset is not None and self.time_offset < 0:
            raise ValueError("DamagePart time_offset cannot be negative")
        if self.hit_interval is not None and self.hit_interval < 0:
            raise ValueError("DamagePart hit_interval cannot be negative")
        if self.cc_kind is not None and not isinstance(self.cc_kind, str):
            raise ValueError("DamagePart cc_kind must be a string or None")

    def __repr__(self) -> str:
        # Deterministic repr: the golden snapshot serializes entries via
        # repr(), and a closure's default repr embeds a memory address.
        hp_scaled = "yes" if self.hp_scaled_damage is not None else "no"
        # Optional fields appear only when set, keeping the golden reprs
        # of every pre-existing part byte-identical.
        extras = ", basic_damage=yes" if self.basic_damage else ""
        if self.bonus_ad_ratio:
            extras += f", bonus_ad_ratio={self.bonus_ad_ratio}"
        if self.dot_stack_scaled:
            extras += ", dot_stack_scaled=yes"
        if self.time_offset is not None:
            extras += f", time_offset={self.time_offset}"
        if self.hit_interval is not None:
            extras += f", hit_interval={self.hit_interval}"
        if self.cc_kind is not None:
            extras += f", cc_kind={self.cc_kind!r}"
        return (
            f"DamagePart({self.damage_type}, amount={self.amount}, "
            f"count={self.count}, hp_scaled={hp_scaled}, "
            f"crit_effectiveness={self.crit_effectiveness}{extras})"
        )


def parts_raw_total(
    parts: tuple[DamagePart, ...],
    damage_type: str | None = None,
) -> float:
    """Sum the raw per-cast damage of *parts*, optionally for one type.

    HP-scaled parts contribute their static ``amount`` (0.0 unless set) —
    their live value exists only at evaluation time.
    """
    return sum(
        part.amount * part.count
        for part in parts
        if damage_type is None or part.damage_type == damage_type
    )
