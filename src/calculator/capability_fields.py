"""One public field descriptor per loadout, scenario and feature control the browser mounts."""

from __future__ import annotations

from typing import Any


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

    Every family here is built ``supported: True`` and there is no condition
    that would refuse one: each is served by a route this deployment always
    mounts, and the catalogs that could be empty answer for themselves in
    ``catalogs``.  The browser's runtime-disable pass over this section
    (``app.js`` ``applyControlCapabilities``) is therefore contract coverage,
    driven by tests over synthetic contracts rather than by a served refusal.
    Publishing the first real refusal is all that pass waits on — it already
    runs at render time, so it reaches render-created controls too.
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
        # The one locator no control answers: app.js reads
        # ``data-optimize-roster`` (and ``-all``, ``data-optimize-build``) in
        # its click delegate, and emits none of them, so the roster and
        # full-build searches have no entry point on the page.  Named in
        # ``app.js`` ``CONTROL_FAMILY_EXEMPTIONS``; backlog row SC2.
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
        # The scoreboard reader (static/js/scoreboard.js) fills the attacker
        # and both rosters from a pasted screenshot through the shared-build
        # loader; its dialog is the control the page mounts.
        "scoreboard": _field(
            payload_field="scoreboard",
            state_path="attacker|targets|allies",
            frontend_token='id="scoreboardDialog"',
        ),
    }
