"""Which items a BIS search ranks, for which subject, in which order."""

from collections.abc import Iterable, Mapping
from dataclasses import replace

from .champion_loadout import MAX_LOADOUT_ITEMS, ChampionLoadout
from .item_coverage import optimizer_supported_items, target_build_coverage
from .loadout_rules import role_quest_legal_items, role_scoped_shop_items
from .optimizer_candidates import get_eligible_boots, get_eligible_legendaries
from .scenario import ScenarioRequest


def bis_main_request(
    request: ScenarioRequest, data: Mapping[str, object]
) -> ChampionLoadout:
    """Rebuild the actual main champion loadout for focused BIS requests.

    The shared scenario boundary already validated every loadout field, so
    this only reassembles the typed ``ChampionLoadout`` (plus the BIS-only
    ``ally_effects_enabled`` toggle) from the validated request.
    """
    ally_effects_enabled = data.get("ally_effects_enabled", True)
    if not isinstance(ally_effects_enabled, bool):
        raise ValueError("ally_effects_enabled must be true or false")
    return ChampionLoadout(
        champion=request.champion,
        level=request.level,
        items=request.items,
        boots=request.boots,
        item_options=dict(request.fight_params.item_options or {}),
        role=request.fight_params.role,
        role_quest_complete=request.fight_params.role_quest_complete,
        ally_effects_enabled=ally_effects_enabled,
        # Focused BIS must use the same authored rank allocation as the
        # ordinary calculate/optimize paths.  Omitting this field makes
        # ChampionLoadout silently fall back to level-derived ranks.
        ability_ranks=dict(request.fight_params.ability_ranks or {}),
        champion_options=dict(request.fight_params.champion_options or {}),
        cast_order=request.fight_params.cast_order,
        # The rune page is part of the main champion's stats everywhere else
        # (calculate, optimize); a swap priced page-less would rank items
        # against a different champion than the one on screen.
        rune_page=request.fight_params.rune_page,
    )


def bis_replaced_loadout(
    loadout: ChampionLoadout,
    *,
    slot_index: int,
    slot_kind: str,
    candidate_name: str,
    candidate_item_options: dict[str, int | float] | None = None,
) -> ChampionLoadout:
    """Replace one ordinary or boots slot while preserving sourced options."""
    item_options = dict(loadout.item_options or {})
    if candidate_item_options:
        item_options[candidate_name] = dict(candidate_item_options)
    if slot_kind == "boots":
        return replace(loadout, boots=candidate_name, item_options=item_options)
    items = list(loadout.items)
    if slot_index < 0 or slot_index > MAX_LOADOUT_ITEMS - 1:
        raise ValueError("slot_index must be between 0 and 5")
    if slot_index >= len(items):
        # Empty browser slots are not serialized as placeholder items; the
        # next completed candidate therefore occupies the next legal slot.
        items.append(candidate_name)
    else:
        items[slot_index] = candidate_name
    # The browser represents empty slots as absent request entries, so a
    # candidate is the only item introduced for an empty slot; duplicate
    # validation is owned by ChampionLoadout.resolve.
    return replace(loadout, items=tuple(items), item_options=item_options)


# A candidate-legality boundary, not a champion archetype or damage
# heuristic: the item cache carries Riot's shop tags, and a roster role is an
# explicit scenario input, so the tags keep a support-only item off a top or
# mid enemy and keep a support ally's BIS out of raw-health tank items.  The
# survivors are still scored by the coupled event timeline.
def role_scoped_bis_candidates(
    candidates: list[dict],
    *,
    role: str,
) -> list[dict]:
    """Keep roster BIS candidates within the selected role's sourced shop scope."""
    return role_scoped_shop_items(candidates, role)


def bis_candidate_pool(
    slot_kind: str,
    *,
    boots_tier: int,
    role: str = "",
    role_quest_complete: bool = False,
) -> list[dict]:
    """Return the sorted legal candidate pool for one ranked slot.

    Boots use the role's eligible tier; ordinary slots use the optimizer's
    supported legendaries scoped to the role's sourced shop tags and the
    support quest's legal-item contract.
    """
    legal = (
        get_eligible_boots(tier=boots_tier)
        if slot_kind == "boots"
        else get_eligible_legendaries()
    )
    supported = optimizer_supported_items(legal)
    scoped = (
        supported
        if slot_kind == "boots"
        else role_scoped_bis_candidates(supported, role=role)
    )
    if slot_kind != "boots":
        scoped = role_quest_legal_items(
            scoped, role=role, role_quest_complete=role_quest_complete
        )
    return sorted(scoped, key=lambda item: item.get("name", ""))


def roster_target_coverage(
    loadouts: Iterable[ChampionLoadout],
) -> list[dict[str, object]]:
    """Return unsupported target mechanics for the coupled roster.

    Roster BIS candidates are later used as passive targets by the main
    champion's event timeline. Do not apply a candidate whose target-side
    item effect is outside the sourced target model; that would either fail
    the next main optimization late or silently ignore the mechanic.
    """
    blocked: list[dict[str, object]] = []
    for loadout in loadouts:
        coverage = target_build_coverage(list(loadout.item_data))
        blocked.extend(
            {
                "champion": loadout.champion_data.get("name", loadout.request.champion),
                "name": entry.get("name", ""),
                "reason": entry.get("reason", ""),
            }
            for entry in coverage.get("withheld", [])
        )
    return blocked


def enemy_bis_rank_key(
    objective: Mapping[str, object],
    survival: Mapping[str, object],
    *,
    duration: float,
) -> tuple[float, ...]:
    """Order enemy candidates by a survival-gated, event-derived objective.

    A roster enemy must remain a live participant before its outgoing damage
    can be useful, but surviving builds should not all collapse to a health
    race.  The first components are a hard event gate (alive through the
    requested window) and survival time, followed by damage dealt before
    defeat (the timeline's TTD-truncated threat).  Effective health and
    recovery actually applied by the timeline are deterministic tie-breakers.
    This is deliberately champion/event based: it does not infer a role or
    assign a damage/tank archetype from the champion name.
    """
    death_time = survival.get("death_time")
    survival_time = float(duration if death_time is None else death_time)
    threat = float(objective.get("focus_damage_before_death", 0.0))
    effective_health = float(survival.get("effective_health", 0.0))
    healing = float(survival.get("healing_received", 0.0))
    support_shield = float(survival.get("support_shield_received", 0.0))
    shield_absorbed = float(survival.get("shield_absorbed", 0.0))
    # Survival is a gate, not an archetype prior.  Survival time still
    # separates candidates that both die before the window; once candidates
    # live equally long, modeled threat is the first discriminator.  Remaining
    # event-derived durability/recovery fields only break ties.
    survived_window = 1.0 if death_time is None else 0.0
    return (
        survived_window,
        survival_time,
        threat,
        effective_health,
        healing,
        support_shield,
        shield_absorbed,
    )
