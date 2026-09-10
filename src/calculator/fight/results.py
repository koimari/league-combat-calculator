"""The typed values the fight's steps hand each other."""

from dataclasses import dataclass, field
from typing import Any, NamedTuple

#: What a producer id says when the magnitude is a champion module's and no
#: item rule declares it.  The slot follows the prefix, so one fight's
#: ability-carried on-hits stay apart from each other and from every item.
CHAMPION_PRODUCER_PREFIX = "champion:"


class SwingStream(NamedTuple):
    """The auto stream every strike step reads, resolved once per fight.

    ``times`` is the schedule a row may stamp its events at, and is empty
    when there is no stream or when it disagrees with the priced swing count:
    a step reads that emptiness as "this row stays coarse" rather than
    inventing a boundary.  ``effectiveness`` is what one item effect is worth
    on those swings, which a replaced auto (an Azir soldier) scales down.
    """

    times: list[float]
    effectiveness: float


class OnHitShare(NamedTuple):
    """One producer's share of one on-hit application.

    An on-hit application is a *sum* over its producers, which is exactly the
    shape a declaration cannot carry: a declaration is one producer's
    magnitude (D-60).  So the producers are kept apart, each beside the
    mechanic that declared it, and every pooled reading is derived from this
    list rather than accumulated a second time.

    ``producer_id`` is a declared item mechanic, or
    :data:`CHAMPION_PRODUCER_PREFIX` and a slot where the magnitude is a
    champion module's.  ``raw`` is the pre-mitigation magnitude a declaration
    would state.
    """

    producer_id: str
    damage_type: str
    mitigated: float
    raw: float

    def declared_mechanic(self) -> str | None:
        """The item mechanic that declared this share, ``None`` for a
        champion's: a routed declaration fails closed there rather than
        attributing it to whichever item shared its damage type."""
        if self.producer_id.startswith(CHAMPION_PRODUCER_PREFIX):
            return None
        return self.producer_id


@dataclass(frozen=True)
class AbilityItemApplication:
    """One ability-carried item application in the rotation's hit order.

    ``on_hit`` applications deal per-hit item damage and count on the
    shared on-hit counters (Kraken/Hullbreaker); ``on_attack``
    applications advance on-attack cadences (Guinsoo's phantom hit).
    Bel'Veth Q is on_hit only; her E slashes are both.
    """

    effectiveness: float
    target_hp: float  # modeled target HP when the hit landed
    on_hit: bool
    on_attack: bool
    # Authored hit boundary for the ability carrier.  ``None`` is for modules
    # that publish no intra-cast ledger; stateful on-hit effects must fail
    # closed when any required carrier is untimed.
    time: float | None = None


@dataclass
class RotationResult:
    """Values produced by the ability rotation and consumed by later steps."""

    total_ability_casts: int = 0
    total_ability_hits: int = 0  # damaging hit instances, for stack counters
    # Basic attacks forced by empowered-auto casts when there is no auto
    # stream (one-rotation, or timed at zero uptime). These are real
    # attacks: they consume spellblade charges like any auto.
    forced_basic_attacks: int = 0
    # How many CASTS forced those attacks. A spellblade charge is armed
    # per ability cast, so one cast spends at most one however many
    # attacks it forces: Jayce's single Hyper Charge cast fires 3 attacks
    # but cannot proc Essence Reaver three times, while Camille's Q1 and
    # Q2 are two casts and legitimately proc twice.
    forced_swing_casts: int = 0
    total_muramana_procs: int = 0  # one per cast; multi-cast R counts each
    first_ability_damage: float = 0.0  # Horizon Focus trigger (not amped)
    has_navori: bool = False
    navori_refund: float = 0.0
    autos_per_second: float = 0.0
    last_cast_time: float = 0.0  # timed mode: when the final recast lands
    cast_events: list[dict[str, Any]] = field(default_factory=list)
    control_events: list[dict[str, Any]] = field(default_factory=list)
    resource_spent: float = 0.0
    resource_remaining: float = 0.0
    # The typed mana ledger's public section, built only by the MANA
    # admission path and ``None`` on every other walk.
    resource_ledger: dict[str, Any] | None = None
    # Ability-carried item applications, in rotation order. They lead
    # the fight's shared counters — autos continue the same counters
    # afterwards (which counter a source advances is decided by the
    # item taxonomy, item_effects.counter_trigger).
    ability_item_applications: list[AbilityItemApplication] = field(
        default_factory=list
    )


@dataclass(frozen=True)
class CastPlan:
    """When every ability entry casts, resolved BEFORE any damage is priced.

    Stack-timeline mechanics (Case 4/5) need the whole fight's cast
    schedule up front — a cast at t=3s must know which stacks and buffs
    the casts before it produced — so the resolution is a pass of its
    own.

    Mode rules: autos-only casts nothing, one-rotation
    casts every entry once at t=0, and timed mode reads the shared cast
    schedule (a recast rides its parent's count when the parent appears
    earlier in the cast order). ``times`` always holds one timestamp per
    cast, 0.0-filled for entries the scheduler never placed;
    ``last_cast_time`` counts only genuinely scheduled casts.
    """

    counts: dict[str, int]
    times: dict[str, tuple[float, ...]]
    last_cast_time: float
    resource_spent: float = 0.0
    resource_remaining: float = 0.0
    omitted_for_resource: tuple[str, ...] = ()
    resource_by_cast: dict[tuple[str, int], dict[str, float]] = field(
        default_factory=dict
    )
    # The typed mana ledger's public section, built only by the MANA
    # admission path and ``None`` on every other walk.
    resource_ledger: dict[str, Any] | None = None


@dataclass(frozen=True)
class StackApplication:
    """One stacking-DoT stack landing on the target."""

    time: float
    stacks_before: int  # stacks the target carried when this hit landed
    stacks_after: int  # after this application, capped at max_stacks
    buff_bonus_ad: float  # stack-triggered bonus AD already active


@dataclass(frozen=True)
class CastPricing:
    """What the fight timeline contributes to ONE cast's damage.

    ``bonus_attack_damage`` re-prices every part that declares a
    ``bonus_ad_ratio``; ``dot_stacks`` supplies the hit count of every
    part that declares ``dot_stack_scaled``. The all-zero default is
    what every fight without a stack timeline uses, so parts that
    declare neither are priced exactly as before.
    """

    bonus_attack_damage: float = 0.0
    dot_stacks: int = 0
    # P3 package 3V: the cast is a Ferocity-empowered one (Rengar) — the
    # engine prices the entry's ferocity_parts instead of parts.
    ferocity_empowered: bool = False


@dataclass(frozen=True)
class StackTimeline:
    """The fight's stacking-DoT applications and everything they gate.

    ONE home for "when does a stack land". The DoT integration
    (``_add_stacking_dot_damage``), the stack-triggered buff windows,
    per-cast stack reads (Darius R) and per-auto buff pricing all read
    THIS object, so they can never drift apart.

    ``applications`` is sorted by time; within one instant (one-rotation
    mode puts every cast at t=0) it keeps cast order, then autos.
    ``buff_windows`` are merged, sorted, half-open ``[start, end)``
    intervals of an active stack-triggered steroid.

    ``starting_stacks`` is the target's stack count at t=0 — stacks put
    on before the modeled fight. Because they were applied by pre-fight
    hits, they carry every consequence a mid-fight application would:
    they open the steroid window at t=0 when they meet
    ``trigger_stacks``, they scale ``dot_stack_scaled`` parts, and they
    tick. Seeding here is what keeps those three answers from
    disagreeing (a target cannot hold max stacks while the champion
    lacks the buff that reaching max stacks grants).
    """

    dot_key: str
    spec: dict[str, Any]
    applications: tuple[StackApplication, ...]
    buff_windows: tuple[tuple[float, float], ...]
    buff_bonus_ad: float
    buff_name: str
    starting_stacks: int
    _by_cast: dict[tuple[str, int], int]
    _by_auto: dict[int, int]

    def _at_time(self, time: float) -> StackApplication | None:
        """The last application strictly before *time*, if any."""
        found = None
        for application in self.applications:
            if application.time >= time:
                break
            found = application
        return found

    def cast_pricing(self, ability_key: str, ordinal: int, time: float) -> CastPricing:
        """Timeline-derived pricing for one cast of *ability_key*.

        A cast that applies a stack is priced from its OWN timeline slot: it
        reads the stacks it found on arrival, so the cast that lands the
        trigger stack is not buffed by the window its own damage opens."""
        index = self._by_cast.get((ability_key, ordinal))
        if index is not None:
            application = self.applications[index]
            return CastPricing(application.buff_bonus_ad, application.stacks_before)
        return CastPricing(self.bonus_ad_at(time), self.stacks_at(time))

    def auto_bonus_ad(self, auto_index: int, time: float) -> float:
        """Stack-triggered bonus AD active on auto attack *auto_index*."""
        index = self._by_auto.get(auto_index)
        if index is not None:
            return self.applications[index].buff_bonus_ad
        return self.bonus_ad_at(time)

    def bonus_ad_at(self, time: float) -> float:
        """Stack-triggered bonus AD active at *time*."""
        for start, end in self.buff_windows:
            if start <= time < end:
                return self.buff_bonus_ad
        return 0.0

    def stacks_at(self, time: float) -> int:
        """Stacks on the target at *time*, before anything landing there."""
        duration = float(self.spec["duration"])
        previous = self._at_time(time)
        if previous is None:
            # Pre-fight stacks, applied at t=0 and expiring like any
            # other application.
            return self.starting_stacks if time < duration else 0
        if time - previous.time >= duration:
            return 0
        return previous.stacks_after


@dataclass
class AutoAttackResult:
    """Values produced by the auto-attack simulation for later steps."""

    auto_damage_per_hit: float = 0.0
    double_shot_info: dict[str, Any] | None = None


@dataclass
class OnHitResult:
    """Values produced by on-hit layering and consumed by later steps."""

    phantom_hit_count: int = 0  # auto-segment phantom hits only
    phantom_hit_autos: set[int] = field(default_factory=set)
    static_on_hit_per_hit: float = 0.0  # mitigated, for HP simulations
    # One entry per producer of one on-hit application, in the order the
    # layering paid them: every item strike and every champion
    # ability-carried on-hit.  The one home of the attribution, so a copied
    # packet's routed declaration and the spellblade's typed pool are two
    # readings of one list instead of two accumulations that could disagree.
    static_on_hit_shares: list[OnHitShare] = field(default_factory=list)
    current_health_on_hit_avg: float = 0.0
    current_health_damage_type: str = "physical"
    has_current_health_on_hit: bool = False
    # Indices in the rotation's ON-HIT application sequence whose attack
    # fired a phantom hit — each grants one extra on-hit counter stack
    # (consumed by _add_stacking_strikes).
    phantom_ability_stack_positions: set[int] = field(default_factory=set)

    def static_on_hit_by_type(self) -> dict[str, float]:
        """One on-hit application's mitigated damage, pooled by damage type.

        Folded in the shares' own order, which is the order the layering paid
        them, so the pool is the same sum a per-type accumulator would build.
        """
        pooled: dict[str, float] = {}
        for share in self.static_on_hit_shares:
            pooled[share.damage_type] = (
                pooled.get(share.damage_type, 0.0) + share.mitigated
            )
        return pooled


@dataclass
class SpellbladeResult:
    """Values produced by the spellblade step and consumed by later steps."""

    item: str | None = None
    procs: int = 0
    damage_per_proc: float = 0.0  # mitigated damage per proc
    double_on_hit_procs: int = 0  # extra on-hit stacks (Dusk and Dawn + double shot)
    mana_restored: float = 0.0
    self_healing: float = 0.0


@dataclass
class FerocityTimeline:
    """Rengar's live Ferocity walk result (P3 package 3V).

    The stack machine is the kernel's ``TimedStackState`` built from the
    module's typed ``RENGAR_FEROCITY_STACK_RULE``; the per-cast empowered
    flags are derived by walking the plan's accepted Q/W/E cast times in
    the same order the post-rotation receipt walk consumes them, so the
    damage pricing and the receipts cannot disagree.
    """

    stack: Any
    starting_stacks: int = 0
    _empowered_by_cast: dict[tuple[str, int], bool] = field(default_factory=dict)
    receipts: list[dict[str, Any]] = field(default_factory=list)

    def cast_empowered(self, ability_key: str, ordinal: int) -> bool:
        """Whether one accepted Q/W/E cast consumed the 4-stack cap."""
        return self._empowered_by_cast.get((ability_key, ordinal), False)
