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

# The cast-slot vocabulary, from the stdlib-only leaf that owns it.
from .cast_dependency import BASE_CAST_SLOTS

# The price of deriving the published phase list instead of hand-listing it
# (0A.6): the public schema now points at the kernel.  Note the reach —
# importing ``.survival.actions``
# executes ``survival/__init__.py``, so compile, transitions, accumulate,
# receipt_state and score_state all load with this module, which is heavier
# than the import line reads for a module whose job is publishing a contract.
# Acyclic: nothing under ``survival/`` imports ``capabilities``.
from .survival.actions import TransitionRank, public_phase

# D-63's chain, in commit order: 1 at 0A's derivation (a starting value, not a
# bump), 2 at 0B's C4 — which published ``persistent_aura_arming`` as the
# ledger's seventh phase — and 3 here, at Phase 3's 3.8 coverage flip.  The
# flip changed the serialized coverage payload: ``blocked`` became
# ``withheld`` (D-23's spelling for a refusal that carries a receipt and no
# number), and every status and reason is now computed from declarations
# rather than read out of a hand registry.  4 is Phase 4's S9: every payload
# that publishes a number now publishes a parallel ``dispositions`` map beside
# it, keyed by leaf path, whose entries carry the leaf's ``Disposition`` and
# its ``ViewTag``.  Measured and structurally-zero leaves are unchanged bare
# numbers; a withheld leaf is *absent* from the payload while its entry
# remains, carrying the receipts.  S6's rank split was asserted payload-
# neutral, so it took no value and S9 takes 4 rather than 5 (D-63).
#
# 5 is the rune page: the request gained ``minor_runes``, ``stat_shards``
# and ``rune_options``, and ``/api/config`` gained the whole rune catalog
# (with each rune's path, row and model coverage) and the stat-shard table
# beside the keystone list it already published.
#
#
# 6 is the survival row's certification fields: the participant ledger row
# gained the crowd-control interval and immunity block, the cleanse receipt,
# the revive-stasis lifecycle, the projectile-defense and spell-shield
# receipts, the Guardian and Aftershock blocks, the action-downtime union and
# the permanent-bonus-health ledger.
#
# 7 is the unsupported fields' locators: ``state_path`` and ``frontend_token``
# are now ``null`` on every field the backend refuses, which is a value change
# on ten published descriptors and so takes a version.
#
# The version moves for a change to the *published payload* and for nothing
# else, so a derivation edit that comes out byte-identical leaves it alone.
# 8 is ``stat_surfaces``: the response publishes two stat blocks that answer
# two different questions, and each now names which one it is.
CAPABILITY_SCHEMA_VERSION = 8

# The two states a published stat block can report. Both are correct and
# neither can replace the other: a loadout block is renderable before any
# fight is run (``/api/loadout-stats`` has no scenario to read), and the
# fight's own block is an outcome — the engine folds each cast ability's
# stat buff (Tristana Q, Olaf R, Lulu W and R, Warwick W) onto its own
# copy of it. Every published block carries ``stats_state``, so a consumer
# reads which fight state it is holding instead of inferring it from where
# the block sits.
PRE_COMBAT_STATS = "pre_combat"
FIGHT_EFFECTIVE_STATS = "fight_effective"
STAT_SURFACE_CONTRACT: dict[str, Any] = {
    "name": "published_stat_surfaces",
    "label_key": "stats_state",
    "states": {
        PRE_COMBAT_STATS: (
            "base stats and level growth, items and their declared state, "
            "and rune stat grants; no ability stat buff, because no fight "
            "has been run"
        ),
        FIGHT_EFFECTIVE_STATS: (
            "the pre-combat block plus every ability stat buff the fight's "
            "cast schedule actually applied"
        ),
    },
}

# This is an API receipt, not a UI hint.  It names the one ordered ledger that
# resolves every participant's state transition.  Keeping the phase names in
# the public contract lets the frontend explain why a result is unavailable
# instead of reconstructing event order from individual controls.
# Closed support-targeting vocabulary.  The first set is the one
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
# TODO: ``item_support_effects._packet`` should validate ``target_scope``
# against this set at emit time.  A source-scan contract test covers it
# meanwhile.
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


# Derived from :class:`TransitionRank` so the published vocabulary and the
# walk's ordering stay one fact.  ``CAPABILITY_SCHEMA_VERSION`` moves when the
# resulting list changes, never when this derivation is edited to no effect.
def _ledger_phases() -> list[str]:
    """``PARTICIPANT_LEDGER_CONTRACT['phases']``, in declaration order."""
    return list(dict.fromkeys(public_phase(rank) for rank in TransitionRank))


PARTICIPANT_LEDGER_CONTRACT: dict[str, Any] = {
    "name": "ordered_participant_ledger",
    "certification": "event_order_certified",
    "phases": _ledger_phases(),
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
    state_path: str | None = None,
    frontend_token: str | None = None,
    supported: bool = True,
    reason: str | None = None,
    conditional: bool = False,
    availability: str = "static",
) -> dict[str, Any]:
    """Build one immutable-in-practice public field descriptor.

    A locator is exactly what a *supported* field has: ``state_path`` and
    ``frontend_token`` name a control the browser mounts, and the contract
    tests hold every supported field to a token the frontend really carries.
    An unsupported field mounts nothing, so it publishes neither and carries
    its reason instead — a locator there names a control that does not exist
    and no test can catch, which is the one way this contract can lie.
    """
    if supported:
        if not state_path or not frontend_token:
            raise ValueError(f"Supported capability {payload_field} needs a locator")
    else:
        if not reason:
            raise ValueError(f"Unavailable capability {payload_field} needs a reason")
        if state_path or frontend_token:
            raise ValueError(
                f"Unavailable capability {payload_field} may not name a control"
            )
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
            supported=False,
            reason=(
                "The backend derives the authored cast order; explicit order "
                "overrides are not exposed by the public control surface."
            ),
        ),
    }

    if not is_main and not is_ally:
        fields["target_stats"] = _field(
            payload_field="target_stats",
            state_path="targets.*.targetStats",
            frontend_token="data-dummy-stat",
            conditional=True,
            availability="practice_dummy",
        )

    if is_main:
        fields.update(
            {
                # A module's count options (passive procs, mines hit) are
                # champion_options rendered on the ability card they name;
                # the engine schedules casts itself, so there is no cast
                # count control.
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
                "minor_runes": _field(
                    payload_field="minor_runes",
                    state_path="attacker.minorRunes{side}",
                    frontend_token='data-picker="minor-rune"',
                ),
                "stat_shards": _field(
                    payload_field="stat_shards",
                    state_path="attacker.statShards{side}",
                    frontend_token='data-picker="stat-shard"',
                ),
                "rune_options": _field(
                    payload_field="rune_options",
                    state_path="attacker.runeOptions{side}",
                    frontend_token="data-rune-option",
                ),
                "ally_effects_enabled": _field(
                    payload_field="ally_effects_enabled",
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
        # One fight-length slider. The engine's rotation count is not a public
        # control: the window is the one number a user sets.
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
        # Full kit or autos only: ``fight_mode`` is ``auto_only`` when the
        # Actions control says so, the module's timed mode otherwise.
        "actions": _field(
            payload_field="fight_mode",
            state_path="fight.autosOnly",
            frontend_token="data-fight-mode",
        ),
        # The Enemy Hits constraint: unchecked, enemies deal zero damage in
        # the coupled timeline (participant_timeline owns the semantics).
        "enemies_attack": _field(
            payload_field="enemies_attack",
            state_path="fight.enemiesAttack",
            frontend_token='id="enemyHitsToggle"',
        ),
    }
    return {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "scope": "public_calculator_controls",
        "participant_ledger": deepcopy(PARTICIPANT_LEDGER_CONTRACT),
        "stat_surfaces": deepcopy(STAT_SURFACE_CONTRACT),
        "participants": participants,
        "scenario": {
            "supported": True,
            "fields": scenario_fields,
            "limits": {key: list(value) for key, value in input_limits.items()},
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
            "runes": {
                "supported": True,
                "keys": ["name", "path", "row", "icon", "implemented", "options"],
                "reason": None,
            },
            "rune_shards": {
                "supported": True,
                "keys": ["row", "name", "options"],
                "reason": None,
            },
            "abilities": {
                "supported": True,
                "slots": list(BASE_CAST_SLOTS),
                "keys": ["slot", "name", "icon", "ingested"],
                "reason": None,
            },
        },
    }
