"""Pricing an ability's typed damage parts over its casts."""

from collections.abc import Callable, Mapping
from typing import Any

from ...ability_atoms import ability_field
from ...ability_spec import ControlScope, DamagePart, cc_kind_reviewed
from ..ledger.event_rows import _damage_type_fields
from ..mitigation import _crit_scaled_raw, _mitigate_hits
from ..resists import _resistance_met_fields
from ..results import CastPricing
from ..setup.target_debuffs import _apply_target_shred, _debuff_coverage
from ..state import FightState


def _evaluate_cast_parts(
    state: "FightState",
    parts: tuple[DamagePart, ...],
    num_casts: int,
    ability_mr: float,
    running_damage: float,
    *,
    on_hit: "Callable[[float], float] | None" = None,
    pricing: "tuple[CastPricing, ...] | None" = None,
    cast_times: "tuple[float, ...] | None" = None,
    single_hit_event_certified: bool = False,
    damage_over_time: bool = False,
    ferocity_empowered: "tuple[bool, ...] | None" = None,
    empowered_parts: "tuple[DamagePart, ...] | None" = None,
    cc_reviewed: bool = False,
    cc_scope: ControlScope | None = None,
    landed_by: "Callable[[float], float] | None" = None,
) -> tuple[float, float, dict[str, float], list[dict[str, Any]]]:
    """Evaluate an ability's typed damage parts over its casts.

    Returns total mitigated damage pre-amp; the first part's mitigated
    damage on the first cast (the Horizon Focus trigger value for mixed
    entries); per-damage-type mitigated totals pre-amp; and any authored
    absolute hit events.
    Threads running target damage through every part and cast so
    HP-scaled parts see prior hits (Akali R2 after R1, Kog'Maw R shot
    after shot).

    ``on_hit`` runs after every individual hit and returns the ability's
    MR for the hits that follow — the seam a ramped resistance shred uses
    to land between an ability's own ticks (Corki E), keeping the "a
    shred never boosts the hit that applied it" rule per tick. Without
    it a part's hits are priced in one multiply, as they always were.

    ``landed_by`` answers "how much damage had actually landed on the
    target by time *t*", and it is what an HP-scaled part reads instead of
    the rotation's running total.  The two differ whenever the rotation
    order is not the landing order: Veigar's R is evaluated after his W but
    lands before W's meteor does, so the running total credited R with
    damage that had not happened yet.  The walk has one clock and prices
    the part against the state at its landing instant; this is that same
    clock on the pair path, so the event's ``pair_damage``, its
    ``raw_damage`` and the walk's number are one number.  Absent, the
    rotation's running total is used, which is what every fight whose
    rotation order *is* its landing order already means.

    ``pricing`` carries one :class:`CastPricing` per cast, from the
    fight's stack timeline: a mid-fight bonus-AD steroid active at that
    cast (re-pricing ``bonus_ad_ratio`` parts) and the DoT stacks on the
    target (counting ``dot_stack_scaled`` parts). Absent, every cast is
    priced against the fight's static stats, exactly as before.
    """
    target_health = state.target_health
    entry_running_damage = running_damage
    total = 0.0
    by_type: dict[str, float] = {}
    damage_events: list[dict[str, Any]] = []
    first_part_first_cast = 0.0
    has_dynamic_part = any(part.hp_scaled_damage is not None for part in parts)
    for cast_index in range(num_casts):
        price = pricing[cast_index] if pricing is not None else _NO_PRICING
        rock_solid_consumed = False
        # P3 package 3V: a live Ferocity-empowered cast prices the
        # module's empowered part set instead of the base parts.
        cast_parts = (
            empowered_parts
            if empowered_parts is not None
            and ferocity_empowered is not None
            and cast_index < len(ferocity_empowered)
            and ferocity_empowered[cast_index]
            else parts
        )
        for part_index, part in enumerate(cast_parts):
            if part.hp_scaled_damage is not None:
                prior_damage = running_damage
                if landed_by is not None and cast_times is not None:
                    # No ``cast_times`` is no clock: this part has no landing
                    # instant to read a state at, so the rotation's running
                    # total is the only answer there is.
                    cast_time_for_part = (
                        cast_times[cast_index]
                        if cast_index < len(cast_times)
                        else cast_times[-1] if cast_times else 0.0
                    )
                    landing = cast_time_for_part + (
                        part.time_offset if part.time_offset is not None else 0.0
                    )
                    # What had landed by this instant, plus what THIS ability
                    # has already put on the target in this call -- its own
                    # earlier parts and casts are in landing order already.
                    prior_damage = landed_by(landing) + (
                        running_damage - entry_running_damage
                    )
                hp_now = max(0.0, target_health - prior_damage)
                missing_ratio = (
                    1.0 - hp_now / target_health if target_health > 0 else 1.0
                )
                raw = part.hp_scaled_damage(missing_ratio)
            else:
                raw = part.amount
            # A mid-fight bonus-AD steroid re-prices the part's declared
            # derivative in bonus AD (Darius' Noxian Might).
            raw += part.bonus_ad_ratio * price.bonus_attack_damage
            hits = price.dot_stacks if part.dot_stack_scaled else part.count
            raw = _crit_scaled_raw(
                state, raw, part.crit_effectiveness, part.damage_type
            )
            rock_solid_instances = int(
                part.basic_damage
                and part.damage_type != "true"
                and hits > 0
                and raw > 0
                and not rock_solid_consumed
            )
            # Hits after the first are identical calls when nothing varies
            # per hit: no per-hit event authoring, no on-hit MR seam, and
            # no Hexoptics bonus tracking (its info-row accumulates per
            # call).  Price one hit and replay the identical value — the
            # same float added the same number of times in the same order.
            repeat_pure = (
                on_hit is None
                and not has_dynamic_part
                and part.time_offset is None
                and not (part.basic_damage and state.basic_amp > 1.0)
            )
            repeat_damage = (
                _mitigate_hits(
                    state,
                    part,
                    raw,
                    ability_mr,
                    hits=1,
                    damage_over_time=damage_over_time,
                )
                if repeat_pure and hits > 1
                else None
            )
            # Dynamic target-health parts need to escape the aggregate
            # breakdown as well.  The normal cast-boundary fallback prices
            # them once against the pair's full-health target; the coupled
            # participant ledger can then re-price the event against the
            # live target HP.  When the source does not give sub-hit
            # timing, all of the part's hits intentionally share the cast
            # boundary and are marked as such below.  If one part reads
            # live target HP, export every part of the cast so the coupled
            # ledger does not lose a preceding flat hit (Akali R1 + R2 is
            # the important example).  Everything constant across the hits
            # is resolved here, once per part and cast.
            # A reviewed module may explicitly certify a single static hit at
            # the cast boundary (for example a direct spell whose cached
            # packet has no separate travel/tick phase).  Carry that proof
            # into the ledger so ordered item triggers such as Eclipse do not
            # fall back to an aggregate/coarse proc merely because the
            # ability has no sub-cast offset.
            emit_events = (
                (single_hit_event_certified and hits == 1 and len(parts) == 1)
                or (
                    part.time_offset is not None
                    and (hits == 1 or part.hit_interval is not None)
                )
                or has_dynamic_part
                or part.cc_duration > 0.0
                or part.skillshot
            )
            if emit_events:
                cast_time = (
                    cast_times[cast_index]
                    if cast_times is not None and cast_index < len(cast_times)
                    else 0.0
                )
                event_base_time = cast_time + (
                    part.time_offset if part.time_offset is not None else 0.0
                )
                event_interval = part.hit_interval or 0.0
                event_precision = (
                    "exact"
                    if single_hit_event_certified and hits == 1 and len(parts) == 1
                    else (
                        "exact"
                        if part.time_offset is not None
                        and part.hit_interval is not None
                        else (
                            "hit" if part.time_offset is not None else "cast_boundary"
                        )
                    )
                )
                event_missing_ratio = (
                    missing_ratio if part.hp_scaled_damage is not None else None
                )
            mitigated = 0.0
            for hit_index in range(hits):
                if repeat_damage is not None and (
                    hit_index > 0 or not rock_solid_instances
                ):
                    mitigated += repeat_damage
                    continue
                hit_damage = _mitigate_hits(
                    state,
                    part,
                    raw,
                    ability_mr,
                    hits=1,
                    rock_solid_instances=int(
                        rock_solid_instances > 0 and hit_index == 0
                    ),
                    damage_over_time=damage_over_time,
                )
                mitigated += hit_damage
                cc_reaches_target = cc_scope is None or cc_scope.reaches(
                    state.roster_target_index
                )
                if emit_events:
                    damage_events.append(
                        {
                            "time": event_base_time + hit_index * event_interval,
                            "damage_type": part.damage_type,
                            "damage": hit_damage,
                            # Forced/empowered basic attacks ride an ability
                            # row (for example Blitzcrank E or Vayne Q), so
                            # preserve their attack identity for reactive
                            # defender effects such as Bramble/Thornmail.
                            "basic_attack": bool(part.basic_damage),
                            "raw_damage": raw,
                            "raw_formula": part.hp_scaled_damage,
                            "source_missing_ratio": event_missing_ratio,
                            "event_precision": event_precision,
                            # The resistance THIS hit met, read off the same
                            # two arguments its own mitigation was handed:
                            # a shred landing between an ability's ticks
                            # moves it, and the fight's published figure is
                            # the one after every shred.
                            **_resistance_met_fields(
                                part.damage_type,
                                state.resists,
                                ability_mr=ability_mr,
                            ),
                            **({"damage_over_time": True} if damage_over_time else {}),
                            **(
                                {
                                    "cc_kind": str(part.cc_kind),
                                }
                                if part.cc_kind is not None and cc_reaches_target
                                else {}
                            ),
                            **(
                                {"cc_reviewed": True}
                                if cc_reviewed or cc_kind_reviewed(part.cc_kind)
                                else {}
                            ),
                            **(
                                {"cc_duration": float(part.cc_duration)}
                                if part.cc_duration > 0.0 and cc_reaches_target
                                else {}
                            ),
                            **(
                                {
                                    "control_source_atoms": [
                                        dict(atom) for atom in part.control_source_atoms
                                    ]
                                }
                                if part.control_source_atoms and cc_reaches_target
                                else {}
                            ),
                            **({"skillshot": True} if part.skillshot else {}),
                        }
                    )
                if on_hit is not None:
                    ability_mr = on_hit(ability_mr)
            if rock_solid_instances:
                rock_solid_consumed = True
            if cast_index == 0 and part_index == 0:
                first_part_first_cast = mitigated
            total += mitigated
            by_type[part.damage_type] = by_type.get(part.damage_type, 0.0) + mitigated
            running_damage += mitigated
    return total, first_part_first_cast, by_type, damage_events


def _apply_post_hit_proc(
    state: "FightState",
    trigger_key: str,
    ability_info: Mapping[str, Any],
    num_casts: int,
    *,
    cast_times: tuple[float, ...],
    running_damage: float,
) -> float:
    """Apply a proc that lands after its triggering hit.

    Some passives cannot be flattened into their triggering spell without
    breaking resistance order. Vi's Denting Blows, for example, deals its
    third-stack damage at the old armor value and only then reduces armor for
    later hits. A champion module attaches ``post_hit_proc`` to the ability
    that completes the stack cycle; this hook prices the proc, records its
    authored hit event, and applies its debuff afterwards. It is not counted
    as a cast and therefore cannot invent Muramana, burn, or spell-effect
    triggers.
    """
    spec = ability_info.get("post_hit_proc")
    if not spec or num_casts <= 0:
        return 0.0

    parts = tuple(ability_field(spec, "parts", form="post_hit_proc"))
    if not parts:
        return 0.0
    total, _, by_type, events = _evaluate_cast_parts(
        state,
        parts,
        num_casts,
        state.resists.effective_mr,
        running_damage,
        cast_times=cast_times,
    )
    if total <= 0:
        return 0.0

    row_key = str(spec.get("breakdown_key", f"post_hit_proc_{trigger_key}"))
    row: dict[str, Any] = {
        "name": str(ability_field(spec, "name", form="post_hit_proc")),
        "count": num_casts,
        "damage_per_hit": total / num_casts,
        "unit": "procs",
        "total_damage": total,
        **_damage_type_fields(by_type),
    }
    if spec.get("detail"):
        row["detail"] = str(spec["detail"])
    timing_is_authored = all(
        part.time_offset is not None
        and (part.count <= 1 or part.hit_interval is not None)
        for part in parts
    )
    if timing_is_authored and events:
        row["damage_events"] = events
        row["event_phase"] = "proc"
    state.breakdown[row_key] = row
    state.total_damage += total

    debuff = spec.get("target_debuff")
    if debuff:
        coverage = (
            1.0
            if state.one_rotation
            else _debuff_coverage(
                cast_times,
                ability_field(debuff, "duration", form="target_debuff"),
                state.fight_duration_seconds,
            )
        )
        _apply_target_shred(state.resists, debuff, coverage)
    return total


_NO_PRICING = CastPricing()
