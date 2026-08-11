"""Authoritative public control capabilities for the calculator.

The API already owns the validation and serialization contracts for loadouts,
champion options, item options, and fight windows.  This module publishes the
same contract to the browser so a control can be rendered only when the
backend can consume the value, or disabled with an honest reason when it
cannot.  The strings in ``frontend_token`` are intentionally stable: contract
tests use them to ensure a supported field has a mounted browser control.

The contract is the single source of truth for the mounted control surface:
participant loadout fields, scenario fields, feature-level controls (view
switch, game-state lens, objective, best-in-slot, optimizer, quick mode,
share, picker dialog, roster membership, manual damage package), and the
catalogs that feed them (champion options, item options, role quest, keystone,
and ability metadata).  test_issues_78.py proves every control attribute and
id the frontend renders maps to a declared ``frontend_token`` and that the
API responses behind those controls expose exactly the declared fields.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

CAPABILITY_SCHEMA_VERSION = 1

# This is an API receipt, not a UI hint.  It names the one ordered ledger that
# resolves every participant's state transition.  Keeping the phase names in
# the public contract lets the frontend explain why a result is unavailable
# instead of reconstructing event order from individual controls.
# Closed support-targeting vocabulary (issue #142).  The first set is the one
# the coupled resolver actually resolves (champion-side packets); the second
# extends it with the item-module disclosure scopes (item packets carry an
# explicit roster target and these labels only describe the authored selection
# rule).  Keeping both here makes the vocabulary a single source of truth: the
# contract below is derived from the resolution set, so they cannot drift.
SUPPORT_TARGET_RESOLUTION_SCOPES: frozenset[str] = frozenset(
    {
        "self",
        "one_teammate",
        "all_teammates",
        "self_and_all_teammates",
        "self_and_one_teammate",
    }
)

# Item-module disclosure scopes.  These packets carry an explicit roster
# target and never resolve through ``_support_target_ids``; the labels are
# audited at emit time so the whole vocabulary stays closed.
# TODO(issue #142): ``item_support_effects._packet`` should validate
# ``target_scope`` against this set at emit time (owned by the item-support
# group; the source-scan contract test in tests/test_issue_142.py covers it
# until then).
SUPPORT_TARGET_SCOPES: frozenset[str] = SUPPORT_TARGET_RESOLUTION_SCOPES | frozenset(
    {
        "all_selected_teammates",
        "enemy_champions_in_radius",
        "enemy_champions_within_range",  # damage-event disclosure (damage.py)
        "explicit_selected_ally",
        "healed_or_shielded_ally",
        "holder_from_worthy_damage",
        "most_wounded_ally",
        "nearest_most_wounded_ally",
        "nova_allied_champions",
        "other_nearest_wounded_ally",
        "redemption_allies_in_radius",
        "self_per_champion_hit",
    }
)


def _target_policy_label(scope: str) -> str:
    """Map one resolution scope to its public target-policy label."""
    return {
        "self": "self",
        "all_teammates": "all_selected_teammates",
        "self_and_all_teammates": "self_and_all_selected_teammates",
        "self_and_one_teammate": "self_and_first_selected_teammate",
        "one_teammate": "first_selected_teammate",
    }[scope]


PARTICIPANT_LEDGER_CONTRACT: dict[str, Any] = {
    "name": "ordered_participant_ledger",
    "certification": "event_order_certified",
    "phases": [
        "state_transition",
        "shield_or_temporary_health",
        "damage_and_mitigation",
        "reactive_effect",
        "healing_and_regeneration",
        "death_or_terminal_cutoff",
    ],
    "target_policy": {
        scope: _target_policy_label(scope)
        for scope in sorted(SUPPORT_TARGET_RESOLUTION_SCOPES)
    }
    | {"none_selected": "no_selected_teammate"},
    "fail_closed": True,
}


# The descriptor is deliberately explicit: each public capability has a
# payload key, browser state path, control token, and availability metadata.
def _field(  # pylint: disable=too-many-arguments
    *,
    payload_field: str,
    state_path: str,
    frontend_token: str,
    supported: bool = True,
    reason: str | None = None,
    conditional: bool = False,
    availability: str = "static",
) -> dict[str, Any]:
    """Build one immutable-in-practice public field descriptor."""
    if not supported and not reason:
        raise ValueError(f"Unavailable capability {payload_field} needs a reason")
    return {
        "supported": supported,
        "reason": reason,
        "payload_field": payload_field,
        "state_path": state_path,
        "frontend_token": frontend_token,
        "conditional": conditional,
        "availability": availability,
    }


def _participant_fields(kind: str) -> dict[str, dict[str, Any]]:
    """Return the public loadout fields for one participant kind."""
    is_main = kind == "main"
    is_ally = kind == "ally"
    state_root = "attacker" if is_main else ("allies" if is_ally else "targets")

    def loadout_path(field: str) -> str:
        """Return a state path that names the actual browser collection."""
        return f"{state_root}.*.{field}"

    fields = {
        "champion": _field(
            payload_field="champion",
            state_path=("attacker.champion" if is_main else loadout_path("champion")),
            frontend_token='data-picker="champion"',
        ),
        "level": _field(
            payload_field="level",
            state_path=("attacker.level" if is_main else loadout_path("level")),
            frontend_token="data-level",
        ),
        "role": _field(
            payload_field="role",
            state_path=("attacker.role" if is_main else loadout_path("role")),
            frontend_token=("#roleSelect" if is_main else "data-roster-role"),
        ),
        "role_quest_complete": _field(
            payload_field="role_quest_complete",
            state_path=(
                "attacker.roleQuestComplete"
                if is_main
                else loadout_path("roleQuestComplete")
            ),
            frontend_token=("#questToggle" if is_main else "data-roster-quest"),
        ),
        "boots": _field(
            payload_field="boots",
            state_path=(
                "attacker.questBoot{side}" if is_main else loadout_path("boots")
            ),
            frontend_token='data-picker="item"',
        ),
        "include_boots": _field(
            payload_field="include_boots",
            state_path=(
                "attacker.includeBoots{side}"
                if is_main
                else loadout_path("includeBoots")
            ),
            frontend_token=(
                "data-include-boots" if is_main else "data-include-roster-boots"
            ),
        ),
        "items": _field(
            payload_field="items",
            state_path=("attacker.build{side}" if is_main else loadout_path("items")),
            frontend_token='data-picker="item"',
        ),
        "item_options": _field(
            payload_field="item_options",
            state_path=(
                "attacker.build{side}Stacks" if is_main else loadout_path("itemStacks")
            ),
            frontend_token="data-stack-path",
        ),
        "ability_ranks": _field(
            payload_field="ability_ranks",
            state_path=(
                "attacker.abilityInputs.*.rank"
                if is_main
                else loadout_path("abilityRanks")
            ),
            frontend_token=('data-ability-rank="' if is_main else "data-roster-rank"),
        ),
        "champion_options": _field(
            payload_field="champion_options",
            state_path=(
                "attacker.championOptions"
                if is_main
                else loadout_path("championOptions")
            ),
            frontend_token=(
                "data-champion-option" if is_main else "data-roster-champion-option"
            ),
            conditional=True,
            availability="champion_declared",
        ),
        "support_target_selections": _field(
            payload_field="support_target_selections",
            state_path=(
                "attacker.supportTargetSelections"
                if is_main
                else loadout_path("supportTargetSelections")
            ),
            frontend_token="data-capability-field",
        ),
        "cast_order": _field(
            payload_field="cast_order",
            state_path=("attacker.castOrder" if is_main else loadout_path("castOrder")),
            frontend_token="data-cast-order",
            supported=False,
            reason=(
                "The backend derives the authored cast order; explicit order "
                "overrides are not exposed by the public control surface."
            ),
        ),
    }

    if is_main:
        fields.update(
            {
                "ability_casts": _field(
                    payload_field="champion_options",
                    state_path="attacker.abilityInputs.*.casts",
                    frontend_token='data-ability-casts="',
                    conditional=True,
                    availability="champion_option_binding",
                ),
                "ability_hits": _field(
                    payload_field="champion_options",
                    state_path="attacker.abilityInputs.*.hits",
                    frontend_token='data-ability-hits="',
                    conditional=True,
                    availability="champion_option_binding",
                ),
                "ability_variants": _field(
                    payload_field="champion_options",
                    state_path="attacker.abilityInputs.*.variant",
                    frontend_token='data-ability-variant="',
                    conditional=True,
                    availability="champion_option_binding",
                ),
                "keystone": _field(
                    payload_field="keystone",
                    state_path="attacker.keystone{side}",
                    frontend_token='data-picker="keystone"',
                ),
                "ally_effects_enabled": _field(
                    payload_field="ally_effects_enabled",
                    state_path="attacker.allyEffectsEnabled",
                    frontend_token="data-ally-effects",
                    supported=False,
                    reason="Only ally participants can opt into modeled ally effects.",
                ),
            }
        )
    elif is_ally:
        fields["ally_effects_enabled"] = _field(
            payload_field="ally_effects_enabled",
            state_path="allies.*.allyEffectsEnabled",
            frontend_token="data-ally-effects",
        )
        for key, label in (
            ("ability_casts", "cast counts"),
            ("ability_hits", "hit counts"),
            ("ability_variants", "ability variants"),
        ):
            fields[key] = _field(
                payload_field=key,
                state_path=f"allies.*.{key}",
                frontend_token=f"data-{key}",
                supported=False,
                reason=(
                    f"Roster payloads accept ranks and declared champion options, "
                    f"not free-form ally {label}."
                ),
            )
    else:
        for key, label in (
            ("ability_casts", "cast counts"),
            ("ability_hits", "hit counts"),
            ("ability_variants", "ability variants"),
        ):
            fields[key] = _field(
                payload_field=key,
                state_path=f"targets.*.{key}",
                frontend_token=f"data-{key}",
                supported=False,
                reason=(
                    f"Roster payloads accept ranks and declared champion options, "
                    f"not free-form enemy {label}."
                ),
            )

    return fields


def _feature_fields() -> dict[str, dict[str, Any]]:
    """Return the public contract for the app-level control families.

    Participant and scenario sections describe loadout inputs; these describe
    the remaining families the frontend mounts: the quick/analyst view switch,
    the snapshot-lens game state, the comparison objective, the best-in-slot
    and roster optimizer flows, quick mode, build sharing, the shared picker
    dialog, roster add/remove actions, and the manual damage package.  Each
    carries the same stable ``frontend_token`` discipline as participant
    fields so the coverage test can prove one contract owns every mounted
    control.
    """
    return {
        "game_state": _field(
            payload_field="game_state",
            state_path="ui.gameState",
            frontend_token="data-game-state",
        ),
        "objective": _field(
            payload_field="objective",
            state_path="ui.objective",
            frontend_token="data-objective",
        ),
        "best_in_slot": _field(
            payload_field="best_in_slot",
            state_path="optimization.bis",
            frontend_token="data-bis-path",
        ),
        "optimize": _field(
            payload_field="optimize",
            state_path="optimization.roster",
            frontend_token="data-optimize-roster",
        ),
        "purchase_optimize": _field(
            payload_field="purchase_optimize",
            state_path="optimization.purchase",
            frontend_token='id="economicsGold"',
        ),
        "share": _field(
            payload_field="share",
            state_path="share",
            frontend_token='id="sharePanel"',
        ),
        "picker": _field(
            payload_field="picker",
            state_path="ui.picker",
            frontend_token='id="picker"',
        ),
        "roster_membership": _field(
            payload_field="roster_membership",
            state_path="targets|allies",
            frontend_token="data-remove-target",
        ),
    }


def public_capability_contract(
    *,
    input_limits: Mapping[str, tuple[float, float]],
    max_rotations: int,
    champion_option_count: int,
    item_option_count: int,
) -> dict[str, Any]:
    """Build the API contract consumed by the main and roster frontends."""
    participants = {
        kind: {
            "supported": True,
            "fields": _participant_fields(kind),
        }
        for kind in ("main", "enemy", "ally")
    }
    scenario_fields = {
        "rotations": _field(
            payload_field="rotations",
            state_path="fight.rotations",
            frontend_token='data-proto-range="rotations"',
        ),
        "window": _field(
            payload_field="fight_duration",
            state_path="fight.duration",
            frontend_token='data-proto-range="duration"',
        ),
        "auto_attack_uptime": _field(
            payload_field="auto_attack_uptime",
            state_path="fight.aaUptime",
            frontend_token='data-proto-range="aaUptime"',
        ),
        "auto_attack_uptime_mode": _field(
            payload_field="auto_attack_uptime_mode",
            state_path="fight.aaUptimeMode",
            frontend_token="uptimeModeToggle",
        ),
    }
    return {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "scope": "public_calculator_controls",
        "participant_ledger": deepcopy(PARTICIPANT_LEDGER_CONTRACT),
        "participants": participants,
        "scenario": {
            "supported": True,
            "fields": scenario_fields,
            "limits": {key: list(value) for key, value in input_limits.items()},
            "rotations": {"min": 1, "max": max_rotations},
        },
        "controls": {
            "supported": True,
            "fields": _feature_fields(),
        },
        "catalogs": {
            "champion_options": {
                "supported": champion_option_count > 0,
                "count": champion_option_count,
                "keys": ["options", "assumptions", "sources"],
                "reason": (
                    None
                    if champion_option_count > 0
                    else "No declared champion options are available in the pinned modules."
                ),
            },
            "item_options": {
                "supported": item_option_count > 0,
                "count": item_option_count,
                "keys": [
                    "options",
                    "stat_effects",
                    "source_url",
                    "source_revision_id",
                ],
                "reason": (
                    None
                    if item_option_count > 0
                    else "No stateful item options are available in the pinned item catalog."
                ),
            },
            "role_quest": {
                "supported": True,
                "keys": ["support_item", "boot_upgrades"],
                "reason": None,
            },
            "keystones": {
                "supported": True,
                "reason": None,
            },
            "abilities": {
                "supported": True,
                "slots": ["P", "Q", "W", "E", "R"],
                "keys": [
                    "slot",
                    "name",
                    "icon",
                    "blurb",
                    "description",
                    "damage_type",
                    "targeting",
                    "ingested",
                ],
                "reason": None,
            },
        },
    }


def copy_capability_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return a safe response copy for callers that may mutate JSON values."""
    return deepcopy(dict(contract))
