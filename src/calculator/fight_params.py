"""The parsed fight request: every field one fight is run with, and what a public
request becomes."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from .auto_attack_policy import (
    AUTO_ATTACK_UPTIME_MODE_CALCULATED,
    AUTO_ATTACK_UPTIME_MODE_EXPLICIT,
    AUTO_ATTACK_UPTIME_MODE_LEGACY,
    AUTO_ATTACK_UPTIME_MODES,
)
from .cast_dependency import BASE_CAST_SLOTS, orderable_slots
from .champions import get_custom_cast_order_unavailable_reason
from .champions.skill_orders import get_ability_rank
from .fight.config import FightConfig
from .fight_request_bounds import (
    _NONSTANDARD_RANK_CHAMPIONS,
    _PUBLIC_FIGHT_MODES,
    DEFAULT_AUTO_ATTACK_UPTIME,
    DEFAULT_FIGHT_DURATION,
    DEFAULT_FIGHT_MODE,
    DEFAULT_TARGET,
    MAX_ALLIES,
    MAX_ROTATIONS,
    ONE_ROTATION_DURATION,
    _bounded_request_float,
    _request_minion_type,
    _request_target_class,
    _request_target_durability,
    cast_slot_surface,
    validate_cast_order_shape,
)
from .item_effects import validate_item_input_options
from .request_parsing import request_bool as _request_bool
from .request_parsing import request_index_map
from .request_parsing import request_int as _request_int
from .role_quests import max_champion_level, validate_role
from .rune_effects import validate_keystone_options, validate_rune_page
from .stats import resolve_pre_combat_stats


@dataclass(frozen=True)
class FightParams(FightConfig):
    """FightConfig plus the parse-layer inputs the engine never sees.

    The engine's typed contract is :class:`FightConfig`; ``run_fight``
    passes a ``FightParams`` straight through because it IS one.
    """

    ability_ranks: dict[str, int] | None = None
    champion_options: dict[str, Any] | None = None
    item_options: dict[str, dict[str, int | float]] | None = None
    support_target_selections: dict[str, int] | None = None
    role: str = ""
    role_quest_complete: bool = False
    ally_stat_bonuses: dict[str, float] | None = None
    # The Enemy Hits constraint. False composes no enemy pair fights in the
    # coupled timeline and suppresses every enemy-authored event (thorns,
    # authored reactives) — enemies deal exactly zero damage. The one-pair
    # engine never reads this; participant_timeline owns the semantics.
    enemies_attack: bool = True

    def pre_combat_stats(
        self,
        champion_data: dict[str, Any],
        level: int,
        items: list[dict[str, Any]],
    ) -> dict[str, float]:
        """This request's answer to every input of the pre-combat stat recipe."""
        return resolve_pre_combat_stats(
            champion_data,
            level,
            items,
            item_options=self.item_options,
            role=self.role,
            role_quest_complete=self.role_quest_complete,
            rune_page=self.rune_page,
            external_stat_bonuses=self.ally_stat_bonuses,
        )

    @classmethod
    def from_request(
        cls,
        data: Mapping[str, Any],
        *,
        deterministic: bool = False,
    ) -> "FightParams":
        """Parse request-shaped values and resolve fight-mode semantics once."""
        fight_mode = data.get("fight_mode", DEFAULT_FIGHT_MODE)
        if not isinstance(fight_mode, str) or fight_mode not in _PUBLIC_FIGHT_MODES:
            raise ValueError(
                "fight_mode must be one_rotation, time_based, timed, or auto_only"
            )
        one_rotation = fight_mode == "one_rotation"
        # ``auto_only`` is a public fight mode and says exactly what the flag
        # says, so it sets it.  Validating the name and then dropping it served
        # a full rotation — abilities, summons and all — to anyone who asked
        # for autos alone, and made the mode indistinguishable from time_based.
        # No cast means no cast: an ability stat grant (Tristana Q, Olaf R,
        # Lulu W/R, Warwick W) is bought with the cast that grants it, so
        # autos-only earns none of them and reports the unbuffed attack speed.
        # The full rotation stays in ``cast_order`` for the breakdown's slot
        # rows; ``damage._apply_stat_buff_ultimates`` is what reads the mode,
        # and it names every grant it withheld in the fight notes.
        auto_attacks_only = (
            _request_bool(data, "auto_attacks_only", False) or fight_mode == "auto_only"
        )
        requested_duration = _bounded_request_float(
            data, "fight_duration", DEFAULT_FIGHT_DURATION
        )
        requested_uptime = _bounded_request_float(
            data, "auto_attack_uptime", DEFAULT_AUTO_ATTACK_UPTIME
        )
        rotation_count = _request_int(
            data, "rotations", 1, minimum=1, maximum=MAX_ROTATIONS
        )
        uptime_mode = data.get(
            "auto_attack_uptime_mode", AUTO_ATTACK_UPTIME_MODE_LEGACY
        )
        if (
            not isinstance(uptime_mode, str)
            or uptime_mode not in AUTO_ATTACK_UPTIME_MODES
        ):
            raise ValueError(
                "auto_attack_uptime_mode must be legacy, explicit, or calculated"
            )

        if one_rotation:
            duration = ONE_ROTATION_DURATION
            uptime = (
                requested_uptime
                if uptime_mode == AUTO_ATTACK_UPTIME_MODE_EXPLICIT
                else 0.0
            )
        else:
            duration = requested_duration
            include_autos = _request_bool(data, "include_auto_attacks", False)
            uptime = (
                requested_uptime
                if (
                    include_autos
                    or auto_attacks_only
                    or uptime_mode == AUTO_ATTACK_UPTIME_MODE_CALCULATED
                )
                else 0.0
            )

        ability_ranks = data.get("ability_ranks")
        if ability_ranks is not None and not isinstance(ability_ranks, Mapping):
            raise ValueError("ability_ranks must be an object")
        champion_options = data.get("champion_options")
        if champion_options is not None and not isinstance(champion_options, Mapping):
            raise ValueError("champion_options must be an object")
        item_options = validate_item_input_options(data.get("item_options"))
        support_target_selections = request_index_map(
            data.get("support_target_selections"),
            field="support_target_selections",
            maximum_index=MAX_ALLIES - 1,
        )
        # One page validates the whole rune selection — keystone, minors,
        # shards and every rune's options — so a keystone-only validator is
        # not a second home for the same question.
        rune_page = validate_rune_page(
            data.get("keystone"),
            data.get("minor_runes"),
            data.get("stat_shards"),
            data.get("rune_options"),
        )
        # ``keystone_options`` is the older spelling of the keystone's own
        # entry in ``rune_options``.  It is validated against the page's
        # keystone and folded into the page, so every reader downstream asks
        # the page and a request may use either spelling without two homes
        # answering differently.
        requested_keystone_options = data.get("keystone_options")
        keystone_options = validate_keystone_options(
            requested_keystone_options, rune_page.keystone
        )
        if (
            isinstance(requested_keystone_options, Mapping)
            and requested_keystone_options
        ):
            rune_page = replace(
                rune_page,
                options={
                    **rune_page.options,
                    rune_page.keystone: {
                        **rune_page.options.get(rune_page.keystone, {}),
                        **{
                            key: float(value) for key, value in keystone_options.items()
                        },
                    },
                },
            )
        role = validate_role(data.get("role", ""))
        role_quest_complete = _request_bool(data, "role_quest_complete", False)
        if role_quest_complete and not role:
            raise ValueError("role is required when role_quest_complete is true")

        target_class = _request_target_class(data)
        minion_type = _request_minion_type(data, target_class)
        params = cls(
            **_request_target_durability(data, minion_type),
            target_magic_resistance=_bounded_request_float(
                data, "target_mr", DEFAULT_TARGET["mr"]
            ),
            fight_duration_seconds=duration,
            auto_attack_uptime=uptime,
            auto_attack_uptime_mode=uptime_mode,
            rotation_count=rotation_count,
            one_rotation=one_rotation,
            include_actives=_request_bool(data, "include_actives", True),
            cast_order=data.get("cast_order"),
            auto_attacks_only=auto_attacks_only,
            ability_ranks=dict(ability_ranks) if ability_ranks is not None else None,
            champion_options=(
                dict(champion_options) if champion_options is not None else None
            ),
            item_options=item_options or None,
            support_target_selections=support_target_selections or None,
            keystone=rune_page.keystone,
            minor_runes=rune_page.minor_runes,
            stat_shards=rune_page.stat_shards,
            rune_options=dict(rune_page.options) or None,
            keystone_options=keystone_options,
            target_class=target_class,
            minion_type=minion_type,
            role=role,
            role_quest_complete=role_quest_complete,
            enemies_attack=_request_bool(data, "enemies_attack", True),
            deterministic=deterministic,
        )
        params._validate_request_values()
        return params

    def _validate_request_values(self) -> None:
        """Reject malformed cast orders and ability ranks for every consumer.

        The cast-order check here is deliberately champion-agnostic: a
        request is a non-empty list of distinct ability slots, and *which*
        slots a given champion may be told to cast is decided against its
        parsed kit in :meth:`validate_for_champion` (D-11).
        """
        validate_cast_order_shape(self.cast_order, field="Cast order")

        if not self.ability_ranks:
            return
        unknown_keys = set(self.ability_ranks) - {"Q", "W", "E", "R"}
        if unknown_keys:
            raise ValueError(
                f"Unknown ability rank keys: {', '.join(sorted(unknown_keys))}"
            )
        for key in ("Q", "W", "E"):
            value = self.ability_ranks.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} rank must be an integer")
            if value < 0 or value > 5:
                raise ValueError(f"{key} rank must be 0-5")
        ultimate_rank = self.ability_ranks.get("R", 0)
        if isinstance(ultimate_rank, bool) or not isinstance(ultimate_rank, int):
            raise ValueError("R rank must be an integer")
        if ultimate_rank < 0 or ultimate_rank > 3:
            raise ValueError("R rank must be 0-3")

    def target_stats(self) -> dict[str, float]:
        """Build the champion-parser target context for a full-health target."""
        return {
            "target_max_health": self.target_health,
            "target_current_health": self.target_health,
            "target_missing_health": 0.0,
            "roster_target_index": float(self.roster_target_index),
            "roster_target_count": float(self.roster_target_count),
        }

    def validate_for_champion(
        self,
        champion_name: str,
        level: int,
        *,
        kit: Mapping[str, Any] | None = None,
    ) -> None:
        """Reject a rank allocation or a cast order this champion cannot run.

        Rank-free requests use the champion's sourced default order. Manual
        allocations are accepted only for the standard five-rank basic and
        three-rank ultimate layout. Transformation and auto-levelled kits fail
        closed until their individual allocation rules are represented.

        ``kit`` is the parsed ability package.  Which slots a request may
        name is a property of the parsed kit, not of the champion's name, so
        every caller that validates *before* the parse passes none, and the
        one caller that has a parse — ``run_fight``'s post-parse call site —
        asks :meth:`validate_cast_order_for_kit` directly instead of running
        this whole validator a second time.  Passing ``kit`` here is for a
        caller that wants both halves in one call.
        """
        if level > max_champion_level(self.role, self.role_quest_complete):
            raise ValueError(f"Level {level} requires the completed top role quest")

        custom_order_reason = get_custom_cast_order_unavailable_reason(champion_name)
        if self.cast_order is not None and custom_order_reason is not None:
            raise ValueError(custom_order_reason)
        if kit is not None:
            self.validate_cast_order_for_kit(champion_name, kit)

        if self.ability_ranks is None:
            return
        if champion_name in _NONSTANDARD_RANK_CHAMPIONS:
            raise ValueError(
                f"Manual ability ranks are unavailable for {champion_name}; "
                "use the level-derived ranks"
            )

        effective = {
            key: self.ability_ranks.get(
                key, get_ability_rank(key, level, champion_name)
            )
            for key in ("Q", "W", "E", "R")
        }
        for key in ("Q", "W", "E"):
            rank = effective[key]
            minimum_level = max(1, 2 * rank - 1) if rank else 0
            if rank and level < minimum_level:
                raise ValueError(
                    f"{key} rank {rank} requires champion level {minimum_level}"
                )
        ultimate_rank = effective["R"]
        minimum_ultimate_level = (0, 6, 11, 16)[ultimate_rank]
        if ultimate_rank and level < minimum_ultimate_level:
            raise ValueError(
                f"R rank {ultimate_rank} requires champion level "
                f"{minimum_ultimate_level}"
            )
        if sum(effective.values()) > min(level, 18):
            raise ValueError(
                "Ability ranks spend more skill points than the champion level allows"
            )

    def validate_cast_order_for_kit(
        self, champion_name: str, kit: Mapping[str, Any]
    ) -> None:
        """Every requested slot is one this champion's parse offers to a request.

        The one question a *parse* answers, on its own, so the post-parse
        call site can ask it without re-running the level, fight-mode and
        rank checks its caller already ran — or, for a caller that passed
        ``validated=True``, deliberately skipped.  A request with no cast
        order has nothing to check and returns.

        Recast slots are absent from the orderable set by construction: they
        ride their parent's casts, so naming one would schedule it twice.
        They are folded back in by ``expand_user_order`` instead of being
        silently dropped, which is the defect this check's other half fixes.

        Raises:
            ValueError: A requested slot is not orderable for this kit.
            cast_dependency.UnknownSlotError: The parse holds a cast slot
                that is neither a base slot nor stamped ``recast_of``, so
                nothing can say whether a request may name it (D-11).
        """
        if self.cast_order is None:
            return
        surface = cast_slot_surface(kit)
        orderable = orderable_slots(surface)
        # A base slot whose parse produced no damage row — Aatrox's dash E,
        # Aphelios's weapon-swap E — is still a slot the champion has, and
        # naming it stays legal and casts nothing, exactly as before. What
        # is refused is a slot the parse DOES hold and ``orderable_slots``
        # did not return: the passive, or a declared recast that rides its
        # parent instead of being scheduled on its own.
        unparsed_base = {slot for slot in BASE_CAST_SLOTS if slot != "P"} - set(surface)
        legal = set(orderable) | unparsed_base
        refused = [slot for slot in self.cast_order or () if slot not in legal]
        if refused:
            raise ValueError(
                f"Cast order names {', '.join(refused)}, which "
                f"{champion_name} cannot be told to cast; "
                f"orderable slots are {', '.join(orderable)}"
            )
