"""The entry dicts a slot parser hands the fight engine."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from ..ability_spec import DamagePart, Disposition, ZeroPolicy
from .slot_context import DAMAGE, SlotCtx, SlotParser
from .slot_extract import extract_cooldown

MODULE_FORMULA_ZERO = ZeroPolicy(
    Disposition.MEASURED,
    "a champion module's formula ran against its parsed ability data and "
    "produced this total; a zero here is a computed zero, not a rule that "
    "never ran",
)
"""The one declared ``zero_policy`` default in the champion tree (D-24).

Every numeric leaf a champion authors is born in one of the two builders
below, so this is the single place the disposition has to be stated: the
399 call sites across 152 champion modules are deliberately **not** edited,
and a required-no-default field there would be a campaign-wide champion
sweep smuggled in by an idiom.  Those two figures are measured, not
recalled: ``tests/test_zero_policy.py`` counts the calls and states the
counting rule, so restating them anywhere turns it red.  ``MEASURED`` is the
honest default at this layer and only at this layer: a module formula that
evaluates to zero *computed* that zero.  Any slot whose zero means something
else passes its own policy.

The default's safety rests on the inputs being wired, which is why it ships
with a guard rather than on its own.  A ``.get(key, <literal>)`` on one of
the three champion input blocks is **forbidden** (``champions/inputs.py``
holds their vocabularies and declared defaults, and reading an undeclared
name raises), so a zero produced by an option that never resolved fails loud
instead of being stamped ``MEASURED`` here.
``scripts/behavior_frontier.py``'s zero-policy frontier enforces that
refusal and additionally pins the two ratcheted populations non-growing:
the same shape on a block the tree *produced*, and hand-built entries that
bypass these builders.
"""


STEROID_ZERO = ZeroPolicy(
    Disposition.STRUCTURAL_ZERO,
    "a steroid slot with no damage attribute grants a stat and deals no "
    "damage by declaration; the zero is the answer, not a missing formula",
)
"""The one place a champion-tree zero is a declaration rather than a result.

:func:`slotlib.stat_buff` without a ``damage_attr`` emits a zero-damage entry
so the buff has a row to ride on.  That zero is ``STRUCTURAL_ZERO``, and saying
so here is what makes ``damage_entry``'s default overridable in fact rather
than only in signature.
"""


def damage_entry(
    name: str,
    rank: int,
    cooldown: float,
    total: float,
    dmg_type: str,
    cc_kind: str | None = None,
    *,
    zero_policy: ZeroPolicy = MODULE_FORMULA_ZERO,
    event_order_certified: str | None = None,
    crit_effectiveness: float = 0.0,
) -> dict[str, Any]:
    """Build a castable-ability entry in the fight-engine format.

    Damage arithmetic goes in typed ``parts``; "mixed" splits evenly between a
    magic part and a true part (like Ahri Q), magic first, because the first
    part is the Horizon Focus trigger.  ``total_raw`` is a producer-side
    test/golden diagnostic with per-entry semantics (usually the parts sum;
    proc entries store per-proc x count, and hp-scaled entries store a bound);
    the fight engine reads ONLY ``parts``.

    ``zero_policy`` says what a zero total *means*.  It defaults to
    :data:`MODULE_FORMULA_ZERO`, the one declared default in the champion tree,
    and a slot whose zero is a declaration rather than a computation passes its
    own.  It is **keyword-only**: a trailing positional would let a seventh
    positional argument at any of the hundreds of call sites bind a
    non-``ZeroPolicy`` value into it silently.

    ``cc_kind`` marks the cast's reviewed crowd control ("stun", "immobilize")
    on the entry's single part.  It is a statement about the kit and not about
    event timing: that the cast's hit lands at the cast boundary is a separate
    claim the caller makes with ``event_order_certified="single_hit"``.  A
    "mixed" entry is two parts, which the engine's certified single-hit export
    cannot carry, so that combination raises rather than silently dropping the
    marker.

    ``crit_effectiveness`` is the same declaration :func:`on_hit_entry` takes,
    on the cast channel instead of the on-hit one: the crit-probability scale
    the row's own sourced text states ("affected by critical strike
    modifiers" is 1.0).  The default 0.0 is the wiki's general rule that
    ability damage does not crit unless stated.
    """
    if cc_kind is not None and dmg_type == "mixed":
        raise ValueError(
            f"damage_entry({name!r}): cc_kind requires a single-part entry "
            "(dmg_type must not be 'mixed')"
        )
    entry: dict[str, Any] = {
        "name": name,
        "rank": rank,
        "cooldown": cooldown,
        "damage_type": dmg_type,
        "total_raw": total,
    }
    if dmg_type == "mixed":
        entry["parts"] = (
            DamagePart(
                "magic",
                total / 2.0,
                crit_effectiveness=crit_effectiveness,
                zero_policy=zero_policy,
            ),
            DamagePart(
                "true",
                total / 2.0,
                crit_effectiveness=crit_effectiveness,
                zero_policy=zero_policy,
            ),
        )
    else:
        entry["parts"] = (
            DamagePart(
                dmg_type,
                total,
                crit_effectiveness=crit_effectiveness,
                cc_kind=cc_kind,
                zero_policy=zero_policy,
            ),
        )
    if event_order_certified is not None:
        entry["event_order_certified"] = event_order_certified
    return entry


def post_hit_proc_row(
    *,
    name: str,
    breakdown_key: str,
    parts: tuple[DamagePart, ...],
    detail: str,
) -> dict[str, Any]:
    """Build the row a cast pays *after* its own hit (``post_hit_proc``).

    ``engine._ALLOWED_POST_HIT_PROC_KEYS`` is a four-key shape (plus an
    optional ``target_debuff``) that :func:`damage_entry`'s richer entry
    cannot be narrowed to, so the proc row gets its own builder — and a
    builder rather than a dict literal per module for the reason
    :data:`MODULE_FORMULA_ZERO` gives: every part it emits is a numeric leaf,
    and one born here says its zero was computed instead of carrying no
    disposition at all.  A part that already declares a policy keeps it.
    """
    return {
        "name": name,
        "breakdown_key": breakdown_key,
        "parts": tuple(
            (
                part
                if part.zero_policy is not None
                else replace(part, zero_policy=MODULE_FORMULA_ZERO)
            )
            for part in parts
        ),
        "detail": detail,
    }


def support_cast(
    *,
    default_name: str,
    detail: str,
    resource_cost: float | None = None,
) -> SlotParser:
    """A slot parser for a shield/heal-only ability that damages nothing.

    ``support_effects`` hangs its packet on a CAST, so a shield- or heal-only
    ability has to be in ``SLOTS`` for the rotation to schedule one — the
    slot exists to produce the cast, not to price damage.  ``resource_cost``
    is stated only when the cached cost row is something the engine's mana
    ledger would mislabel (Soraka W's 10%-of-max-health cost).
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ranked = ctx.ranked()
        if ranked is None:
            return None
        ability, rank = ranked
        entry = damage_entry(
            ability.get("name", default_name),
            rank,
            extract_cooldown(ability, rank),
            0.0,
            "magic",
        )
        # The shared builder always writes one part; a support cast has none
        # to price, and an authored zero part would put a zero-damage
        # instance in the ledger.
        entry["parts"] = ()
        entry["detail"] = detail
        if resource_cost is not None:
            entry["resource_cost"] = resource_cost
        return entry

    return parse


def attach_self_shield(
    entry: dict[str, Any],
    *,
    amount: float,
    duration: float,
    source: str,
    detail: str | None = None,
) -> dict[str, Any]:
    """Attach a module-authored self-shield payload to an ability entry.

    The payload shape mirrors the Eclipse item's ``self_shield_events``
    receipt.  The engine copies the list onto the ability's damage-event
    rows by ordinal and the ledger grants a timed self-shield at that
    timestamp.  ``actor_wide`` de-duplicates one activation across enemy
    pairs, and ``rebind_on_ability_hit`` moves the rider to the first
    ability packet that lands when its authored carrier is blocked.
    """
    entry["self_shield_events"] = [
        {
            "amount": round(float(amount), 6),
            "duration": float(duration),
            "source": str(source),
            "actor_wide": True,
            "rebind_on_ability_hit": True,
        }
    ]
    if detail:
        entry["detail"] = detail
    return entry


def on_hit_entry(
    name: str,
    damage_per_hit: float,
    dmg_type: str,
    *,
    crit_effectiveness: float = 0.0,
) -> dict[str, Any]:
    """Build an on-hit entry the fight engine applies per auto attack.

    ``crit_effectiveness`` is the crit-probability scale the row's own
    sourced text states ("affected by critical strike modifiers" is 1.0);
    the default 0.0 is the wiki's general rule that on-hit damage does not
    crit unless stated.
    """
    on_hit: dict[str, Any] = {
        "name": f"{name} (on-hit)",
        "damage_per_hit": damage_per_hit,
        "damage_type": dmg_type,
    }
    if crit_effectiveness:
        on_hit["crit_effectiveness"] = crit_effectiveness
    return {
        "name": name,
        "damage_type": dmg_type,
        "total_raw": 0.0,
        # Rotation consumers expect every ability row to expose an ordered
        # parts tuple, even when the row's damage is attached to the next
        # basic attack rather than dealt by the cast itself.
        "parts": (),
        "on_hit": on_hit,
    }


@dataclass(frozen=True)
class HitRider:
    """A per-hit bonus a champion's passive adds to declared carriers.

    Some passives ride more than one delivery channel: a bonus that lands
    on named ability hits AND on the basic attacks a range gate admits
    (Samira's Daredevil Impulse, on Blade Whirl, Wild Rush, Flair's blade
    branches and every attack inside the 200-unit blade zone).  One
    declaration serves both — :func:`with_hit_rider` attaches it to a
    slot's parts, :meth:`auto_entry` to the basic-attack stream — so the
    number and its missing-health amplification have one home.

    Attributes:
        name: The passive's own name, for the rows both channels publish.
        damage_type: The rider's type, which need not be its carrier's.
        amount: Raw damage of one application at the target's full health.
        missing_health_amp: Extra fraction at the target's full missing
            health; 1.0 doubles the rider (Daredevil Impulse).
    """

    name: str
    damage_type: str
    amount: float
    missing_health_amp: float = 0.0

    def _raw_at(self, missing_ratio: float) -> float:
        return self.amount * (1.0 + self.missing_health_amp * missing_ratio)

    def part(self, ridden: DamagePart) -> DamagePart:
        """The rider instance one ridden part's hits carry.

        It mirrors that part's hit count and authored timing, so a
        multi-hit or offset carrier rides its own schedule rather than a
        boundary this helper invents.
        """
        return DamagePart(
            self.damage_type,
            amount=self.amount,
            hp_scaled_damage=self._raw_at if self.missing_health_amp else None,
            count=ridden.count,
            time_offset=ridden.time_offset,
            hit_interval=ridden.hit_interval,
        )

    def auto_entry(self) -> dict[str, Any]:
        """The basic-attack half: this rider on every swing.

        The engine prices each swing against the target's health at it.
        """
        entry = on_hit_entry(self.name, self.amount, self.damage_type)
        if self.missing_health_amp:
            entry["on_hit"]["missing_health_amp"] = self.missing_health_amp
        return entry


def with_hit_rider(
    parser: SlotParser, rider_for: Callable[[SlotCtx], HitRider | None]
) -> SlotParser:
    """Wrap a slot so every hit its parts deal carries a declared rider.

    ``rider_for(ctx)`` returns this fight's :class:`HitRider`, or None when
    the slot is not a carrier at these options.  The rider parts LEAD the
    entry: they are priced against the target's health before the hit they
    ride lands, and a mixed row's magic instance is the one its readers
    take as the trigger (the Fizz Q shape).  A row certified as one hit at
    the cast gives up that single-part certification and authors the cast
    instant on both parts instead.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        if entry is None:
            return None
        rider = rider_for(ctx)
        ridden = tuple(entry.get("parts") or ())
        if rider is None or rider.amount <= 0 or not ridden:
            return entry
        if entry.get("event_order_certified") == "single_hit" and all(
            part.time_offset is None for part in ridden
        ):
            del entry["event_order_certified"]
            ridden = tuple(replace(part, time_offset=0.0) for part in ridden)
        riders = tuple(rider.part(part) for part in ridden)
        entry["parts"] = riders + ridden
        entry["total_raw"] = float(entry.get("total_raw") or 0.0) + sum(
            part.amount * part.count for part in riders
        )
        if any(part.damage_type != rider.damage_type for part in ridden):
            entry["damage_type"] = "mixed"
        return entry

    parse.phase = getattr(parser, "phase", DAMAGE)
    return parse


def fixed_count_pet_row(
    name: str,
    damage_type: str,
    damage_per_hit: float,
    attack_times: list[float],
    *,
    detail: str,
) -> dict[str, Any]:
    """Build a fixed-count pet-attack proc row (E4 summoned units).

    The fight engine prices ``proc_count`` independent procs for entries
    outside the cast rotation (Tibbers attacks, Voidling attacks, ...):
    one ``DamagePart`` per hit, the authored attack timestamps as an
    exact event ledger, and the row's own display detail.  ``total_raw``
    is the producer-side diagnostic (per-hit x count); the engine reads
    only ``parts``.
    """
    return {
        "name": name,
        "damage_type": damage_type,
        "total_raw": damage_per_hit * len(attack_times),
        "parts": (DamagePart(damage_type, damage_per_hit),),
        "proc_count": len(attack_times),
        "damage_events": [
            {
                "time": round(time, 3),
                "damage_type": damage_type,
                "damage": damage_per_hit,
                "event_precision": "exact",
            }
            for time in attack_times
        ],
        "event_phase": "effect",
        "detail": detail,
    }


def ability_on_hit_entry(
    name: str,
    rank: int,
    damage_type: str,
    on_hit: dict[str, Any],
    *,
    cooldown: float | None = None,
) -> dict[str, Any]:
    """Wrap an on-hit payload in a zero-direct-damage ability shell."""
    entry: dict[str, Any] = {
        "name": name,
        "rank": rank,
        "damage_type": damage_type,
        "total_raw": 0.0,
        "parts": (),
        "on_hit": on_hit,
    }
    if cooldown is not None:
        entry["cooldown"] = cooldown
    return entry
