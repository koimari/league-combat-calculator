"""Shared entry point for a complete champion fight calculation.

Consumers provide already-loaded champion and item data. This module owns the
cross-domain orchestration from stats through champion ability parsing into the
champion-agnostic fight engine; data fetching remains with each consumer.
"""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from .auto_attack_policy import (
    AUTO_ATTACK_UPTIME_MODE_CALCULATED,
    resolve_auto_attack_policy,
)
from .cast_dependency import check_order_satisfies_dependencies, expand_user_order
from .champions import (
    RESERVED_OPTION_KEYS,
    get_champion_cast_dependencies,
    get_champion_cast_order,
    get_champion_ultimate_recasts,
    parse_champion_abilities,
)
from .damage import calculate_fight_damage
from .data_registry import data_version
from .fight_params import FightParams
from .fight_receipts import (
    _annotate_deathfire_categories,
    _attach_display_splits,
    _attach_engine_receipts,
)
from .healing import derive_self_healing, self_heal_rule_owner
from .interpreters.crit_profile import declared_crit_profile
from .item_effects import BuildDamageEffects, resolve_damage_effects, resolved_item_name
from .item_sustain_events import _item_self_healing_events
from .ledger_inputs import LedgerInputs, ResultProjection
from .ledger_projection import ledger_projection
from .rotation_resolver import build_rotation_receipt, resolve_cast_order
from .rune_sustain_events import (
    _keystone_self_healing_events,
    _rune_self_healing_events,
)
from .self_state_effects import derive_self_state_effects


def resolve_ledger_inputs(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    params: "FightParams",
    champion_data: Mapping[str, Any],
    items: Iterable[dict[str, Any]],
    item_damage_effects: BuildDamageEffects,
    *,
    fight_stats: Mapping[str, Any],
    ability_damages: Mapping[str, Any],
) -> LedgerInputs:
    """One fight's facts, as the ledger projection's readers are decided by.

    The one place ``run_fight``'s locals become the projection's declared
    inputs, so the derivation's fixtures and the engine's live call build the
    same record from the same fields.
    """
    return LedgerInputs(
        self_heal_rule=self_heal_rule_owner(str(champion_data.get("name", ""))),
        item_names=tuple(str(item.get("name", "")) for item in items),
        stats=fight_stats,
        damage_effects=item_damage_effects,
        ability_damages=ability_damages,
        rune_page=params.rune_page,
        fight_duration_seconds=params.fight_duration_seconds,
        is_melee=bool(fight_stats.get("is_melee", True)),
        target_threshold_health_heal=params.target_threshold_health_heal,
    )


# The optimizer replays the same frozen FightParams for thousands of
# candidate fights, and the resolved cast order for one champion is almost
# always identical across candidates.  Memoize the derived params by
# (params identity, order): frozen instances are safe to share, the strong
# reference guards ``id()`` recycling, the leading ``data_version()``
# retires every entry derived from a replaced cache (D-49), and the bound
# keeps candidate churn from growing the memo without limit.
_CAST_ORDER_PARAMS_MEMO: dict[
    tuple[int, int, tuple[str, ...]], tuple["FightParams", "FightParams"]
] = {}
_CAST_ORDER_PARAMS_MEMO_LIMIT = 512


def _params_with_cast_order(
    params: "FightParams", declared_order: list[str]
) -> "FightParams":
    """``replace(params, cast_order=declared_order)`` with an identity memo."""
    key = (data_version(), id(params), tuple(declared_order))
    memo = _CAST_ORDER_PARAMS_MEMO.get(key)
    if memo is not None and memo[0] is params:
        return memo[1]
    resolved = replace(params, cast_order=declared_order)
    if len(_CAST_ORDER_PARAMS_MEMO) > _CAST_ORDER_PARAMS_MEMO_LIMIT:
        _CAST_ORDER_PARAMS_MEMO.clear()
    _CAST_ORDER_PARAMS_MEMO[key] = (params, resolved)
    return resolved


def run_fight(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    params: FightParams,
    *,
    precomputed_stats: dict[str, float] | None = None,
    validated: bool = False,
    score_only: bool = False,
) -> dict[str, Any]:
    """Run stats, champion ability parsing, and fight damage as one pipeline.

    ``precomputed_stats`` lets a caller that already ran this exact stat
    calculation (same champion, level, items, options, role, and external
    bonuses) hand it over instead of repeating it; the fight itself never
    mutates it.  Callers own that equality claim.

    ``validated=True`` is the same kind of caller-owned claim for
    ``params.validate_for_champion(champion, level)``: the coupled search
    validates its fixed per-pair params once instead of on each of
    thousands of identical fights.

    ``score_only=True`` skips result fields no scoring consumer reads —
    the one-pair shield outcome (unless the Protoplasm coverage downgrade
    needs it) and the auto/ability/type display splits.  Every field that
    remains carries the identical value.  When the champion additionally
    has no self-heal rule and the target arms no threshold heal, the
    returned ``damage_events`` are the engine's light ledger rows
    (``damage_events_tuple`` is set) — same events, same order, no dict
    per event; only the scoring fast path consumes that shape.
    """
    if not validated:
        params.validate_for_champion(champion_data.get("name", ""), level)
    champion_stats = (
        precomputed_stats
        if precomputed_stats is not None
        else params.pre_combat_stats(champion_data, level, items)
    )

    # Reserved option keys are pipeline-owned: strip whatever the caller
    # sent, then hand timed fights the fight window, the auto uptime and
    # whether the engine casts anything at all, so duration/timeline-driven
    # champion mechanics (Aurelion Sol's continuous Q channel, Braum's
    # passive stack cycle) scale with the same fight the engine runs — an
    # autos-only window schedules zero casts, so a walk module that merges
    # ability hits into its stream has to be told. One-rotation mode keeps
    # the per-cast ability models.
    champion_options = dict(params.champion_options or {})
    for reserved_key in RESERVED_OPTION_KEYS:
        champion_options.pop(reserved_key, None)
    if not params.one_rotation:
        champion_options["fight_duration_seconds"] = params.fight_duration_seconds
        champion_options["auto_attack_uptime"] = params.auto_attack_uptime
        champion_options["auto_attacks_only"] = params.auto_attacks_only

    # Champion mechanics priced in crit at parse time (Caitlyn's Headshot
    # rider) need the build's bonus crit damage above the 2.0 base
    # (Infinity Edge's +0.3). It comes off the build's crit declarations —
    # the same reading the fight engine folds into its crit multiplier — so
    # surface it to the parse context only, keeping the reported
    # champion_stats panel item-stats-only.
    parse_stats = dict(champion_stats)
    item_damage_effects = resolve_damage_effects(items)
    parse_stats["crit_damage_bonus"] = declared_crit_profile(
        [resolved_item_name(item) for item in items]
    ).damage_bonus

    ability_damages = parse_champion_abilities(
        champion_data,
        level,
        champion_stats["ability_power"],
        ability_ranks=params.ability_ranks,
        champion_stats=parse_stats,
        target_stats=params.target_stats(),
        champion_options=champion_options,
    )
    if params.keystone == "Deathfire Touch":
        _annotate_deathfire_categories(ability_damages, champion_data)
    # The fight engine applies ability stat buffs (Mega Gnar's form
    # stats, Vayne/Aatrox R, ...) to this copy in place — report THESE
    # as the champion's stats so the UI panel shows the fight-effective
    # values, not the pre-buff base+items snapshot.
    fight_stats = dict(champion_stats)
    # F2: the optimal event-order engine derives the fight's cast order
    # from the atomized ability data + the per-champion combo table (see
    # rotation_resolver.py) — e.g. Cassiopeia opens with Q so the poison
    # is up for E-spam, Varus puts the Blight detonator Q first, Aatrox
    # casts R before its AD-amped damage. An explicit caller-supplied
    # order still wins; champions with no combo signal fall back to their
    # certified module order, then the engine default.
    resolved_rotation_rule = None
    resolved_certified_order = None
    resolved_user_order = None
    if params.cast_order is None:
        # F3: the algorithmic resolver derives the order for EVERY champion
        # from the atomized ability data (setup/consume edges + per-rank DPS),
        # falling back to the champion module's certified CAST_ORDER or the
        # engine default when the data shows a flat kit.  The hand-verified seeds
        # remain documented overrides inside the resolver.
        declared_order, combo_rule = resolve_cast_order(
            champion_data.get("name", ""),
            ability_damages,
            champion_data=champion_data,
            certified_order=get_champion_cast_order(champion_data.get("name", "")),
            champion_options=champion_options,
        )
        params = _params_with_cast_order(params, declared_order)
        resolved_rotation_rule = combo_rule
        resolved_certified_order = (
            combo_rule.order
            if combo_rule is not None and not combo_rule.derived
            else None
        )
    else:
        # The post-parse cast-order call site: the requested order is checked
        # against the slots this parse actually offers, then every live recast
        # slot is folded back in after its parent.  Before this, a requested
        # order was passed to the engine verbatim and every recast row it did
        # not name — Syndra's second Dark Sphere charge — silently vanished
        # from the damage breakdown (D-11).
        resolved_user_order = list(params.cast_order)
        params.validate_cast_order_for_kit(
            champion_data.get("name", ""), ability_damages
        )
        # A declared ordering prerequisite states impossibility, not
        # preference (D-86): casting Syndra's E before her Q would have the
        # engine author a stun that cannot happen, and an amplifier price
        # off it.  The order checked is the EXPANDED one, because that is
        # what the engine casts — a recast folded in after its parent can
        # satisfy a dependency the request never named, and could equally
        # invert one.  A champion that declares nothing gets an empty tuple
        # and reaches no new failure mode (D-85).
        expanded_order = expand_user_order(resolved_user_order, ability_damages)
        check_order_satisfies_dependencies(
            expanded_order,
            get_champion_cast_dependencies(champion_data.get("name", "")),
            ability_damages,
        )
        params = _params_with_cast_order(params, expanded_order)
    resolved_uptime, auto_attack_policy = resolve_auto_attack_policy(
        champion_data,
        ability_damages,
        cast_order=params.cast_order,
        duration_seconds=params.fight_duration_seconds,
        requested_uptime=params.auto_attack_uptime,
        mode=params.auto_attack_uptime_mode,
        one_rotation=params.one_rotation,
    )
    if params.auto_attack_uptime_mode == AUTO_ATTACK_UPTIME_MODE_CALCULATED:
        params = replace(params, auto_attack_uptime=resolved_uptime)
        if not params.one_rotation:
            # Timed champion mechanics (channels and passive cycles) consume
            # the same resolved policy; do not let their parse context retain
            # the pre-resolution placeholder zero.
            champion_options["fight_duration_seconds"] = params.fight_duration_seconds
            champion_options["auto_attack_uptime"] = resolved_uptime
            ability_damages = parse_champion_abilities(
                champion_data,
                level,
                champion_stats["ability_power"],
                ability_ranks=params.ability_ranks,
                champion_stats=parse_stats,
                target_stats=params.target_stats(),
                champion_options=champion_options,
            )
            if params.keystone == "Deathfire Touch":
                _annotate_deathfire_categories(ability_damages, champion_data)
    # ``score_only`` is the request for a narrowed result; whether the light
    # tuple ledger can serve it is projection satisfaction over the declared
    # adequacy conditions, not a conjunction kept here (D-38, criterion 15).
    tuple_ledger = score_only and (
        ledger_projection(
            resolve_ledger_inputs(
                params,
                champion_data,
                items,
                item_damage_effects,
                fight_stats=fight_stats,
                ability_damages=ability_damages,
            )
        )
        is ResultProjection.LIGHT_TUPLE_LEDGER
    )
    # Whether the timed scheduler may recast R is the champion module's
    # reviewed answer, not the request's: a silent module and an
    # unregistered name both keep the conservative one-cast rule (CF18).
    ultimate_recasts = get_champion_ultimate_recasts(champion_data.get("name", ""))
    engine_config = (
        params
        if params.enforce_resource_limits
        and params.ultimate_recasts == ultimate_recasts
        else replace(
            params,
            enforce_resource_limits=True,
            ultimate_recasts=ultimate_recasts,
        )
    )
    result = calculate_fight_damage(
        fight_stats,
        ability_damages,
        items,
        engine_config,
        score_only=score_only,
        tuple_ledger=tuple_ledger,
        item_options=params.item_options,
        champion_options=params.champion_options,
    )
    result["self_state_events"] = derive_self_state_effects(
        ability_damages,
        list(result.get("cast_timeline", [])),
    )
    keystone_state_events: list[dict[str, Any]] = []
    fleet_row = result.get("breakdown", {}).get("keystone_Fleet Footwork")
    if isinstance(fleet_row, Mapping) and isinstance(
        fleet_row.get("movement_events"), list
    ):
        keystone_state_events.extend(fleet_row["movement_events"])
    conqueror_row = result.get("breakdown", {}).get("keystone_Conqueror")
    if isinstance(conqueror_row, Mapping) and isinstance(
        conqueror_row.get("stack_events"), list
    ):
        keystone_state_events.extend(conqueror_row["stack_events"])
    result["keystone_state_events"] = keystone_state_events
    result["champion_stats"] = fight_stats
    # F2 rotation receipt: the optimal order + WHY it is optimal, for the
    # event-order panel. ``order`` is the engine's actual cooldown-aware
    # cast sequence; ``rationale`` explains the combo.
    result["rotation"] = build_rotation_receipt(
        cast_order=list(params.cast_order or []),
        cast_timeline=list(result.get("cast_timeline", [])),
        rule=resolved_rotation_rule,
        certified_order=(
            resolved_certified_order if resolved_rotation_rule is None else None
        ),
        user_order=resolved_user_order,
    )
    _attach_engine_receipts(
        result, params, items, fight_stats, auto_attack_policy=auto_attack_policy
    )
    if tuple_ledger:
        # The predicate above IS derive_self_healing's dispatch gate, so
        # the empty list is the exact value the call would return.
        result["damage_events_tuple"] = True
        result["self_healing_events"] = []
        return result
    champion_healing = derive_self_healing(
        champion_data,
        fight_stats,
        ability_damages,
        list(result.get("damage_events", [])),
        list(result.get("cast_timeline", [])),
        params.fight_duration_seconds,
    )
    result["self_healing_events"] = sorted(
        champion_healing
        + _keystone_self_healing_events(result, params)
        + _item_self_healing_events(result, items, params.fight_duration_seconds)
        + _rune_self_healing_events(result, params.rune_page),
        key=lambda event: (
            float(event.get("time", 0.0)),
            str(event.get("kind", "")),
            str(event.get("source", "")),
            int(event.get("_trigger_sequence", 0)),
        ),
    )
    if score_only:
        return result
    _attach_display_splits(result)
    return result
