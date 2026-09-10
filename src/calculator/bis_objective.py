"""What BIS optimises for, and how one candidate folds into that number."""

import math
from collections.abc import Callable, Iterable, Mapping

from .bis_candidates import enemy_bis_rank_key
from .fight_request_bounds import DEFAULT_FIGHT_DURATION
from .interpreters import survival_ledger_note
from .program.tagged import Tagged, ranked_total
from .program.views.dispositions import (
    published_quantity,
    published_tag,
    refuse_previewed,
)
from .program.views.leaf import RankingWriter, name_every_number
from .program.views.view_tag import UnrankableNumber
from .public_response import https_icon

# Best-in-slot is an objective selector, not a second stat-only optimizer.
# Keep the definitions in one place so the API receipt and the browser filter
# cannot silently disagree about direction or units.
BIS_OBJECTIVES: dict[str, dict[str, str]] = {
    "team_outcome": {
        "label": "Team damage advantage",
        "direction": "higher",
        "metric": "selected-side damage minus opposing-side damage before defeat",
        "description": (
            "Selected-side damage before defeat minus opposing-side damage before "
            "defeat, from the coupled fight. This score measures damage advantage; "
            "it is not a win probability."
        ),
    },
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
            "objective must be one of: team_outcome, overall, kill, survival, damage, utility"
        )
    return {"key": key, **meta}


def bis_objective_contract() -> dict[str, dict[str, str]]:
    """Return the complete objective map for public clients."""
    units = {
        "team_outcome": "TDD",
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

    Matched by identity rather than participant id: two participants of the
    same champion at the same level publish equal dicts, so a path naming
    the wrong one would carry the wrong meaning with no symptom.
    """
    for index, row in enumerate(combat.get("participants", ())):
        if row is focus:
            return f"participants[{index}].survival"
    raise UnrankableNumber(
        BIS_SURFACE, "a row the payload does not publish", ["participants"]
    )


def _team_damage_advantage(
    subject_team: str,
    objective: Mapping[str, object],
    part: Callable[[str, float], Tagged],
) -> tuple[float, str, dict[str, float], None]:
    """Subtract the opposing side's published damage from the selected side."""
    damage = {
        team: ranked_total(
            [
                part(
                    f"objective.{team}_team_damage_before_death",
                    float(objective[f"{team}_team_damage_before_death"]),
                )
            ],
            surface=BIS_SURFACE,
        )
        for team in ("main", "enemy")
    }
    selected, opposing = (
        ("enemy", "main") if subject_team == "enemy" else ("main", "enemy")
    )
    return (
        damage[selected] - damage[opposing],
        BIS_OBJECTIVES["team_outcome"]["metric"],
        {
            "selected_side_damage_before_death": damage[selected],
            "opposing_side_damage_before_death": damage[opposing],
        },
        None,
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
    preview.  ``THEORETICAL`` is never an optimizer objective and never feeds
    BIS: a retagged field is an ordinary ``MEASURED`` float, so nothing on
    this path could tell it from a delivered one without asking the entry.

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
        """One published number, with the quantity read from its own entry so
        a withheld leaf refuses instead of reading as an uncomputed zero.
        """
        return Tagged(
            published_quantity(dispositions, path, value, surface=BIS_SURFACE),
            published_tag(dispositions, path, surface=BIS_SURFACE),
        )

    focus_survival = focus.get("survival", {})
    focus_survival = focus_survival if isinstance(focus_survival, Mapping) else {}
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
    if objective_key == "team_outcome":
        return _team_damage_advantage(subject_team, objective, part)
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
    withheld_candidates: Iterable[dict[str, object]],
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


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def _bis_dispositions(payload: dict) -> dict[str, dict[str, object]]:
    """The payload's parallel ``dispositions`` map, keyed by leaf path."""
    return name_every_number(payload, RankingWriter())
