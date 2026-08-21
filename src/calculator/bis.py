"""Best-in-slot application boundary and domain policy.

The BIS endpoint (/api/bis) is an objective selector over the coupled
participant event timeline, not a second stat-only optimizer.  Keeping the
objective contract, candidate orchestration, sorting, and receipt assembly in
this module means the API and any future consumer cannot silently disagree.
Flask owns only HTTP decoding, cache/rate policy, and error translation.
"""

from dataclasses import replace
import math
from collections.abc import Mapping

from .interpreters import (
    survival_ledger_certifications,
    survival_ledger_note,
)
from .item_effects import validate_item_input_options
from .loadout_rules import (
    required_boots_tier,
    role_quest_legal_items,
    role_scoped_shop_items,
)
from .optimizer import (
    get_eligible_boots,
    get_eligible_legendaries,
    optimizer_supported_items,
)
from .pipeline import DEFAULT_FIGHT_DURATION
from .program.build import Tagged, ranked_total
from .program.views import (
    RankingWriter,
    UnrankableNumber,
    name_every_number,
    published_quantity,
    published_tag,
    refuse_previewed,
)
from .participant_timeline import build_participant_timeline
from .public_response import https_icon
from .request_parsing import request_int, request_string
from .scenario import (
    MAX_LOADOUT_ITEMS,
    ChampionLoadout,
    ScenarioRequest,
    parse_scenario_request,
    resolve_scenario,
)
from .item_coverage import target_build_coverage
from .timeline_coverage import applicability_exclusion_sources


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
    # The browser represents empty slots as absent request entries.  A
    # candidate is therefore the only item introduced for a previously empty
    # slot; duplicate validation remains owned by ChampionLoadout.resolve.
    return replace(loadout, items=tuple(items), item_options=item_options)


def role_scoped_bis_candidates(
    candidates: list[dict],
    *,
    role: str,
) -> list[dict]:
    """Keep roster BIS candidates within the selected role's sourced shop scope.

    The item cache carries Riot's shop tags for each completed item.  A roster
    role is an explicit scenario input, so using those tags here prevents a
    support-only item from being recommended to a top/mid enemy and prevents a
    support ally's BIS from collapsing into raw-health tank items.  This is a
    candidate-legality boundary, not a champion archetype or damage heuristic;
    the surviving candidates are still scored by the coupled event timeline.
    """
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


def roster_target_coverage(loadouts: list[ChampionLoadout]) -> list[dict[str, object]]:
    """Return unsupported target mechanics for the coupled roster.

    Roster BIS candidates are later used as passive targets by the main
    champion's event timeline. Do not apply a candidate whose target-side
    item effect is outside the sourced target model; that would either fail
    the next main optimization late or silently ignore the mechanic.
    """
    blocked: list[dict[str, object]] = []
    for loadout in loadouts:
        coverage = target_build_coverage(list(loadout.item_data))
        for entry in coverage.get("withheld", []):
            blocked.append(
                {
                    "champion": loadout.champion_data.get(
                        "name", loadout.request.champion
                    ),
                    "name": entry.get("name", ""),
                    "reason": entry.get("reason", ""),
                }
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


# Best-in-slot is an objective selector, not a second stat-only optimizer.
# Keep the definitions in one place so the API receipt and the browser filter
# cannot silently disagree about direction or units.
BIS_OBJECTIVES: dict[str, dict[str, str]] = {
    "overall": {
        "label": "Overall",
        "direction": "higher",
        "metric": "event-ordered team-fight value",
    },
    "kill": {
        "label": "Kill pressure",
        "direction": "lower",
        "metric": "time to first target defeat",
    },
    "survival": {
        "label": "Survival",
        "direction": "higher",
        "metric": "effective health (event-applied)",
    },
    "damage": {
        "label": "Damage",
        "direction": "higher",
        "metric": "damage before focus defeat",
    },
    "utility": {
        "label": "Utility",
        "direction": "higher",
        "metric": "healing, shields, and support value",
    },
}

# Retained as an explicit API field for clients that display the audit
# contract.  A non-empty entry means the candidate is withheld; the certified
# half beside it is read from the declarations by
# `interpreters.survival_ledger_certifications`, so nothing here says which
# items are certified.
BIS_UNMODELED_DEFENSIVE_EFFECTS: dict[str, str] = {}


def bis_defensive_effect_receipt(
    item_name: str, survival: Mapping[str, object]
) -> dict[str, object]:
    """Describe why a defensive item did or did not affect candidate eHP.

    The certification is the declaration's, not this module's: an item is
    certified exactly when one of its rules declares a contribution to its
    holder's survival ledger — a proc's self shield, a routing rule's
    deferral, a forced strike's heal — which is what the effective health
    below was computed over.
    """
    certified_note = survival_ledger_note(item_name)
    if certified_note is None:
        return {"status": "no_special_defensive_effect", "sources": []}
    return {
        "status": "certified",
        "sources": [item_name],
        "note": certified_note,
        "evidence": {
            "healing_received": round(
                float(survival.get("healing_received", 0.0) or 0.0), 1
            ),
            "temporary_health_received": round(
                float(survival.get("temporary_health_received", 0.0) or 0.0), 1
            ),
            "effective_health": round(
                float(survival.get("effective_health", 0.0) or 0.0), 1
            ),
        },
    }


def bis_objective_meta(key: str) -> dict[str, str]:
    """Return a defensive copy of the API's objective contract."""
    meta = BIS_OBJECTIVES.get(key)
    if meta is None:
        raise ValueError(
            "objective must be one of: overall, kill, survival, damage, utility"
        )
    return {"key": key, **meta}


def bis_objective_contract() -> dict[str, dict[str, str]]:
    """Return the complete objective map for public clients."""
    units = {
        "overall": "TDD",
        "kill": "",
        "survival": "eHP",
        "damage": "TDD",
        "utility": "",
    }
    return {key: {**meta, "unit": units[key]} for key, meta in BIS_OBJECTIVES.items()}


def bis_time_to_target_defeat(
    combat: Mapping[str, object],
    *,
    subject_team: str,
    focus_id: str,
    duration: float,
) -> float:
    """Return an explicit event-derived kill-time objective in seconds.

    For a main/ally item, kill pressure means the first enemy defeat.  For an
    enemy item, it means how quickly the selected enemy is defeated.  An
    undefeated participant is assigned the requested window, never zero or a
    guessed extrapolation.
    """
    participants = combat.get("participants", [])
    if not isinstance(participants, list):
        participants = []
    if subject_team == "enemy":
        participant_ids = {focus_id}
    else:
        participant_ids = {
            str(row.get("participant_id", ""))
            for row in participants
            if isinstance(row, Mapping) and row.get("team") == "enemy"
        }
    times: list[float] = []
    for row in participants:
        if (
            not isinstance(row, Mapping)
            or str(row.get("participant_id", "")) not in participant_ids
        ):
            continue
        survival = row.get("survival", {})
        if not isinstance(survival, Mapping):
            continue
        death_time = survival.get("death_time")
        if death_time is None:
            continue
        try:
            parsed = float(death_time)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            times.append(max(0.0, min(duration, parsed)))
    return min(times, default=duration)


#: The consumer every BIS refusal names.  A message that said which function
#: raised would answer the wrong question: what a reader needs to know is
#: that the surface which picks a build refused to pick one.
BIS_SURFACE = "the BIS objective"


def _focus_survival_path(
    combat: Mapping[str, object], focus: Mapping[str, object]
) -> str:
    """Where the focus participant's survival row lives in the payload.

    Matched by identity rather than by participant id, because the entry
    describing a number has to be the entry for *that* row: two participants
    of the same champion at the same level publish equal dicts, and a path
    that named the wrong one would carry the wrong meaning with no symptom.
    """
    for index, row in enumerate(combat.get("participants", ())):
        if row is focus:
            return f"participants[{index}].survival"
    raise UnrankableNumber(
        BIS_SURFACE, "a row the payload does not publish", ["participants"]
    )


def bis_objective_score(
    objective_key: str,
    *,
    subject_team: str,
    focus_id: str,
    combat: Mapping[str, object],
    objective: Mapping[str, object],
    focus: Mapping[str, object],
) -> tuple[float, str, dict[str, float], tuple[float, ...] | None]:
    """Derive one candidate's selected objective from the shared timeline.

    Every score below is folded through :func:`~.program.build.ranked_total`
    out of parts carrying the meaning the payload published for them, and the
    candidate's whole map is refused first if any of its numbers is a
    preview.  D-62: ``THEORETICAL`` is never an optimizer objective and never
    feeds BIS.  Before this, a retagged field would have been ranked exactly
    like a delivered one -- both are ordinary ``MEASURED`` floats, and
    nothing on this path ever asked what they meant.

    The refusal is an ``UnrankableNumber``, which is a ``TypeError`` and so
    passes through the candidate loop's ``except (KeyError, ValueError)``
    rather than being turned into a withheld row: a previewed number is not a
    candidate that could not be evaluated, it is a payload meaning something
    other than what the ranking assumed.
    """
    dispositions = combat.get("dispositions", {})
    refuse_previewed(dispositions, surface=BIS_SURFACE)
    survival_path = _focus_survival_path(combat, focus)

    def part(path: str, value: float) -> Tagged:
        """One published number, carrying what its own entry says it means.

        Both halves come from the entry: what the number *means* (its view)
        and whether there is a number at all (its disposition).  The second
        matters because a withheld leaf is absent from the payload, so the
        ``.get(..., 0.0)`` above it reads a zero no rule computed; taking the
        quantity from the entry is what makes the fold propagate the refusal
        instead of ranking the candidate on it.

        Two raise sites now, and Python evaluates arguments left to right, so
        a path with no ``dispositions`` entry fails inside the *quantity*
        read rather than the tag read.  Same ``UnrankableNumber`` and the
        same message; different origin, which is worth a sentence for
        anything reading the traceback.
        """
        return Tagged(
            published_quantity(dispositions, path, value, surface=BIS_SURFACE),
            published_tag(dispositions, path, surface=BIS_SURFACE),
        )

    focus_survival = focus.get("survival", {})
    if not isinstance(focus_survival, Mapping):
        focus_survival = {}
    duration = float(combat.get("duration", 0.0) or 0.0)
    if duration <= 0.0:
        duration = DEFAULT_FIGHT_DURATION
    focus_damage = float(objective.get("focus_damage_before_death", 0.0) or 0.0)
    effective_health = float(focus_survival.get("effective_health", 0.0) or 0.0)
    healing = float(focus_survival.get("healing_received", 0.0) or 0.0)
    support_shield = float(focus_survival.get("support_shield_received", 0.0) or 0.0)
    support_value = float(objective.get("focus_support_value", 0.0) or 0.0)
    damage_part = part("objective.focus_damage_before_death", focus_damage)
    health_part = part(f"{survival_path}.effective_health", effective_health)
    if objective_key == "overall":
        if subject_team == "main":
            score = ranked_total([damage_part], surface=BIS_SURFACE)
            metric = "main TTD (survival-coupled)"
            components = {
                "damage_before_death": focus_damage,
                "effective_health": effective_health,
                "healing": healing,
                "support_shield_received": support_shield,
            }
            return score, metric, components, None
        if subject_team == "ally":
            team_damage = float(
                objective.get("main_team_damage_before_death", 0.0) or 0.0
            )
            score = ranked_total(
                [
                    part("objective.main_team_damage_before_death", team_damage),
                    part("objective.focus_support_value", support_value),
                    health_part,
                ],
                surface=BIS_SURFACE,
            )
            metric = "team damage + ally utility + effective health"
            components = {
                "main_team_damage_before_death": team_damage,
                "outgoing_support": support_value,
                "healing": float(objective.get("focus_healing", 0.0) or 0.0),
                "effective_health": effective_health,
            }
            return score, metric, components, None
        survival_time = bis_time_to_target_defeat(
            combat,
            subject_team=subject_team,
            focus_id=focus_id,
            duration=duration,
        )
        rank_key = enemy_bis_rank_key(objective, focus_survival, duration=duration)
        score = ranked_total([damage_part], surface=BIS_SURFACE)
        metric = "enemy survival gate · threat before defeat"
        components = {
            "survival_time": survival_time,
            "effective_health": effective_health,
            "threat_before_defeat": focus_damage,
            "healing": healing,
            "shield_absorbed": float(focus_survival.get("shield_absorbed", 0.0) or 0.0),
        }
        return score, metric, components, rank_key

    if objective_key == "kill":
        score = bis_time_to_target_defeat(
            combat,
            subject_team=subject_team,
            focus_id=focus_id,
            duration=duration,
        )
        metric = BIS_OBJECTIVES[objective_key]["metric"]
        components = {
            "time_to_target_defeat": score,
            "damage_before_death": focus_damage,
        }
        return score, metric, components, None
    if objective_key == "survival":
        score = ranked_total([health_part], surface=BIS_SURFACE)
        metric = BIS_OBJECTIVES[objective_key]["metric"]
        components = {
            "effective_health": effective_health,
            "healing": healing,
            "support_shield_received": support_shield,
        }
        return score, metric, components, None
    if objective_key == "damage":
        if subject_team == "ally":
            score = ranked_total(
                [
                    part(
                        "objective.main_team_damage_before_death",
                        float(
                            objective.get("main_team_damage_before_death", 0.0) or 0.0
                        ),
                    )
                ],
                surface=BIS_SURFACE,
            )
        else:
            score = ranked_total([damage_part], surface=BIS_SURFACE)
        metric = BIS_OBJECTIVES[objective_key]["metric"]
        components = {
            "damage_before_death": score,
            "effective_health": effective_health,
        }
        return score, metric, components, None
    # Utility is intentionally an additive receipt of values that the event
    # walk actually applied.  It does not infer movement, range, or a value
    # for an unmodelled item tooltip -- and "actually applied" is now the
    # fold's own refusal rather than a comment: three parts, one meaning.
    score = ranked_total(
        [
            part("objective.focus_support_value", support_value),
            part(f"{survival_path}.healing_received", healing),
            part(f"{survival_path}.support_shield_received", support_shield),
        ],
        surface=BIS_SURFACE,
    )
    metric = BIS_OBJECTIVES[objective_key]["metric"]
    components = {
        "support_value": support_value,
        "healing": healing,
        "support_shield_received": support_shield,
    }
    return score, metric, components, None


def _withheld_candidate(
    candidate: Mapping[str, object],
    *,
    reason: str,
    detail: str | None,
    timeline_coverage: Mapping[str, object],
    **extra: object,
) -> dict[str, object]:
    """Build one stable receipt for a candidate excluded from ranking."""
    receipt = {
        "name": candidate["name"],
        "icon": https_icon(candidate.get("icon", "")),
        "reason": reason,
        "timeline_coverage": dict(timeline_coverage),
        **extra,
    }
    if detail is not None:
        receipt["detail"] = detail
    return receipt


def _bis_coverage_receipt(
    certified_ranked: list[dict],
    partial_ranked: list[dict],
    withheld_candidates: list[dict[str, object]],
    target_coverage_filtered: list[dict[str, object]],
) -> tuple[dict[str, object], str, list[dict[str, object]]]:
    """Classify exhaustive coverage and return its public explanation."""
    timing_excluded = [
        row
        for row in withheld_candidates
        if row.get("reason") == "candidate_excluded_unresolved_timing"
    ]
    blocking_withheld = [
        row
        for row in withheld_candidates
        if row.get("reason") != "candidate_excluded_unresolved_timing"
    ]
    complete = bool(certified_ranked) and not partial_ranked and not blocking_withheld
    target_note = ""
    if target_coverage_filtered:
        first = target_coverage_filtered[0]
        target_note = (
            f"Target-side coverage filtered {len(target_coverage_filtered)} candidate "
            f"receipts; {first['champion']} · {first['name']}: {first['reason']}"
        )
    certification = (
        "bis_event_order_certified_with_exclusions"
        if complete and timing_excluded
        else (
            "bis_event_order_certified"
            if complete
            else (
                "bis_certified_subset_not_exhaustive"
                if certified_ranked
                else "bis_no_certified_candidates"
            )
        )
    )
    if complete:
        note = "Every candidate has complete sourced event order."
    elif certified_ranked:
        note = (
            "Certified candidates are available, but exhaustive BIS is withheld "
            "because one or more candidates were not fully evaluated or still "
            "have partial event order."
        )
    else:
        note = (
            "No candidate has complete sourced event order; BIS is withheld and "
            "only partial or pre-timeline receipts are shown."
        )
    if timing_excluded:
        note += (
            f" {len(timing_excluded)} candidate timing receipt(s) were excluded "
            "before ranking."
        )
    if target_note:
        note += f" {target_note}"
    return (
        {"complete": complete, "certification": certification, "note": note},
        target_note,
        timing_excluded,
    )


# The public interface stays deliberately small; the internal orchestration
# mirrors one candidate through every coverage and scoring gate.
# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def _bis_dispositions(payload: dict) -> dict[str, dict[str, object]]:
    """The payload's parallel ``dispositions`` map, keyed by leaf path.

    Every member of the finished payload is re-written through the one
    writer at the path it lives at -- assigning an existing key keeps its
    position, so each row is byte-identical and every entry is produced
    beside its leaf by ``serialize_leaf`` rather than by a second pass that
    describes numbers it did not write.

    It walks the whole payload rather than two named leaves.  Naming only
    ``score`` and ``objective_value`` left 14 959 of this endpoint's 18 807
    numbers with no entry -- including each candidate's
    ``components.{damage_before_death, effective_health, healing,
    support_shield_received}``, which are the components the objective is
    folded from, and every candidate's stat block.  The endpoint that ranks
    builds was serving the calculator's largest undispositioned numeric
    surface while its own test asserted its two headline leaves were there.

    The survival entries are produced here rather than carried from the
    combat receipt on a private ``_survival_dispositions`` key smuggled
    through the public row.  That key was inserted first in each row and
    popped later, and the coverage receipt ran *before* the pop -- so a row
    reaching the payload by any other route would have leaked it.  Writing
    the leaf and its entry in the same ``serialize_leaf`` call is what the
    single writer means; re-serialising a value at the path it now lives at
    is that writer, not a second one.

    The writer is a :class:`~.program.views.RankingWriter`: this payload is a
    ranking, so a block a view opened ``THEORETICAL`` may not reach it.  That
    is the write half of D-62's rule; the read half is
    :func:`~.program.views.refuse_previewed`, which
    :func:`bis_objective_score` runs over each candidate's own combat map
    before folding a score out of it.
    """
    return name_every_number(payload, RankingWriter())


def bis_payload(data: Mapping[str, object]) -> dict:
    """Rank one slot and return the complete JSON-safe BIS receipt."""
    request = parse_scenario_request(data, deterministic=True, parse_crossover=False)
    subject_team = request_string(data, "subject_team", "main")
    if subject_team not in {"main", "ally", "enemy"}:
        raise ValueError("subject_team must be main, ally, or enemy")
    slot_index = request_int(data, "slot_index", 0, 0, MAX_LOADOUT_ITEMS - 1)
    slot_kind = request_string(data, "slot_kind", "item")
    if slot_kind not in {"item", "boots"}:
        raise ValueError("slot_kind must be item or boots")
    subject_index = request_int(data, "subject_index", 0, 0, 4)
    objective_meta = bis_objective_meta(request_string(data, "objective", "overall"))
    objective_key = objective_meta["key"]
    if subject_team == "ally" and subject_index >= len(request.allies):
        raise ValueError("subject_index is outside the selected ally roster")
    if subject_team == "enemy" and subject_index >= len(request.enemies):
        raise ValueError("subject_index is outside the selected enemy roster")

    resolved = resolve_scenario(request)
    main_request = bis_main_request(request, data)
    main_loadout = main_request.resolve()
    candidate_item_options = validate_item_input_options(
        data.get("candidate_item_options")
    )
    enemies = list(resolved.enemies)
    allies = list(resolved.allies)
    subject_base = (
        main_request
        if subject_team == "main"
        else (
            request.allies[subject_index]
            if subject_team == "ally"
            else request.enemies[subject_index]
        )
    )
    if subject_team != "main" and not subject_base.role:
        raise ValueError(
            f"{subject_team} role is required before roster BIS can be scored"
        )
    subject_id = (
        "main" if subject_team == "main" else f"{subject_team}:{subject_base.champion}"
    )
    role = subject_base.role
    candidates = bis_candidate_pool(
        slot_kind,
        boots_tier=required_boots_tier(role, subject_base.role_quest_complete),
        role=role,
        role_quest_complete=subject_base.role_quest_complete,
    )
    equipped_slot_item = (
        subject_base.boots
        if slot_kind == "boots"
        else (
            subject_base.items[slot_index]
            if slot_index < len(subject_base.items)
            else ""
        )
    )
    if equipped_slot_item:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.get("name") != equipped_slot_item
        ]

    ranked: list[dict] = []
    withheld: list[dict[str, object]] = []
    target_filtered: list[dict[str, object]] = []
    fight_params = resolved.fight_params
    for candidate in candidates:
        try:
            candidate_params = fight_params
            candidate_options = candidate_item_options.get(candidate["name"])
            if candidate_options:
                candidate_params = replace(
                    fight_params,
                    item_options={
                        **(fight_params.item_options or {}),
                        candidate["name"]: candidate_options,
                    },
                )
            candidate_request = bis_replaced_loadout(
                subject_base,
                slot_index=slot_index,
                slot_kind=slot_kind,
                candidate_name=candidate["name"],
                candidate_item_options=candidate_options,
            )
            resolved_subject = candidate_request.resolve()
            candidate_main = (
                resolved_subject if subject_team == "main" else main_loadout
            )
            candidate_enemies = list(enemies)
            candidate_allies = list(allies)
            if subject_team == "enemy":
                candidate_enemies[subject_index] = resolved_subject
            elif subject_team == "ally":
                candidate_allies[subject_index] = resolved_subject
            blocked_targets = roster_target_coverage(
                [*candidate_enemies, *candidate_allies]
            )
            if blocked_targets:
                target_filtered.extend(blocked_targets)
                withheld.append(
                    _withheld_candidate(
                        candidate,
                        reason="target_coverage_blocked",
                        detail=None,
                        timeline_coverage={
                            "complete": False,
                            "certification": "target_coverage_blocked",
                            "exact_sources": [],
                            "coarse_sources": [],
                            "note": (
                                "Candidate was not evaluated because a selected "
                                "roster item is outside the sourced target model."
                            ),
                        },
                        target_coverage=blocked_targets,
                    )
                )
                continue
            focus_id = "main" if subject_team == "main" else subject_id
            combat = build_participant_timeline(
                candidate_main.champion_data,
                candidate_main.request.level,
                list(candidate_main.item_data),
                candidate_params,
                main_stats=candidate_main.stats,
                main_defenses=candidate_main.defenses,
                enemies=candidate_enemies,
                allies=candidate_allies,
                focus_participant_id=focus_id,
            )
            coverage = combat.get("timeline_coverage", {})
            timing_exclusions = applicability_exclusion_sources(coverage)
            if timing_exclusions:
                names = ", ".join(timing_exclusions)
                withheld.append(
                    _withheld_candidate(
                        candidate,
                        reason="candidate_excluded_unresolved_timing",
                        exclusion_type="applicability",
                        excluded_sources=timing_exclusions,
                        detail=(
                            "Candidate was excluded before BIS ranking because "
                            f"{names} has no sourced hit boundary for this rotation."
                        ),
                        timeline_coverage=coverage,
                    )
                )
                continue
            objective = combat["objective"]
            focus = next(
                row
                for row in combat["participants"]
                if row["participant_id"] == focus_id
            )
            score, metric, components, rank_key = bis_objective_score(
                objective_key,
                subject_team=subject_team,
                focus_id=focus_id,
                combat=combat,
                objective=objective,
                focus=focus,
            )
            ranked.append(
                {
                    "name": candidate["name"],
                    "icon": https_icon(candidate.get("icon", "")),
                    "score": round(score, 1),
                    "objective_value": round(score, 3),
                    "metric": metric,
                    "components": components,
                    "stats": candidate.get("stats", {}),
                    "survival": focus["survival"],
                    "defensive_effect_receipt": bis_defensive_effect_receipt(
                        candidate["name"], focus["survival"]
                    ),
                    "timeline_coverage": coverage,
                    "_sort_score": score,
                    **({"_rank_key": rank_key} if rank_key is not None else {}),
                }
            )
        except (KeyError, ValueError) as exc:
            withheld.append(
                _withheld_candidate(
                    candidate,
                    reason="candidate_loadout_unavailable",
                    detail=str(exc),
                    timeline_coverage={
                        "complete": False,
                        "certification": "candidate_not_evaluated",
                        "exact_sources": [],
                        "coarse_sources": [],
                        "note": "Candidate was withheld before timeline evaluation.",
                    },
                )
            )

    if objective_key == "overall" and subject_team == "enemy":
        ranked.sort(key=lambda row: row["_rank_key"], reverse=True)
    else:
        ranked.sort(
            key=lambda row: row["_sort_score"],
            reverse=objective_meta["direction"] == "higher",
        )
    for row in ranked:
        row.pop("_rank_key", None)
        row.pop("_sort_score", None)
    partial = [
        row for row in ranked if not row["timeline_coverage"].get("complete", False)
    ]
    certified = [
        row for row in ranked if row["timeline_coverage"].get("complete", False)
    ]
    coverage_receipt, target_note, timing_excluded = _bis_coverage_receipt(
        certified, partial, withheld, target_filtered
    )
    payload = {
        "objective": objective_meta,
        "defensive_effects": {
            "certified": dict(survival_ledger_certifications()),
            "withheld": BIS_UNMODELED_DEFENSIVE_EFFECTS,
        },
        "subject_team": subject_team,
        "subject_index": subject_index,
        "slot_index": slot_index,
        "slot_kind": slot_kind,
        "excluded_equipped_item": equipped_slot_item or None,
        "candidate_scope": (
            f"role-tagged:{role}" if role and slot_kind != "boots" else "all-supported"
        ),
        "candidates": certified,
        "partial_candidates": partial,
        "candidate_count": len(candidates),
        "certified_candidate_count": len(certified),
        "partial_candidate_count": len(partial),
        "withheld_candidate_count": len(withheld),
        "withheld_candidates": withheld,
        "coverage": coverage_receipt,
        "target_coverage_filtered": len(target_filtered),
        "target_coverage_note": target_note,
        "timing_excluded_candidate_count": len(timing_excluded),
    }
    payload["dispositions"] = _bis_dispositions(payload)
    return payload
