"""Every key an emitted entry may carry, and the refusal for one it may not."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, NamedTuple

from ..ability_spec import DamagePart

# Every key an emitted entry may carry. The fight engine reads the first
# group; the second is producer-side diagnostics and champion display
# metadata (never engine-read). An unknown key raises at parse time —
# a misspelled key must never silently zero an ability.
_ALLOWED_ENTRY_KEYS = frozenset(
    {
        # fight-engine contract
        "name",
        "rank",
        "cooldown",
        "cast_time",
        # charge_cadence.py: the cached inter-cast gap and the reviewed
        # stock of a charge slot, whose ``cooldown`` is its recharge.
        "charge_between_casts",
        "charge_pool",
        "resource_cost",
        "resource_type",
        "resource_restore",
        "resource_restore_per_proc",
        "resource_restore_per_auto",
        "mark_refund",
        # P4-14: Darius W's asserted kill rule (cooldown halved + flat
        # mana refund) — emitted only when the w_kill_assertion option is
        # on; validated by the resource walk's fail-closed declaration.
        "kill_refund",
        "resource_maximum_bonus",
        "resource_maximum_bonus_duration",
        "damage_type",
        "parts",
        # P3 package 3V: the Ferocity-empowered part set (Rengar Q/W/E) —
        # the engine prices it for live empowered casts chosen by the
        # post-rotation stack walk.
        "ferocity_parts",
        "cast_instances",
        "recast_of",
        "empowers_next_auto",
        # P4: documentary certification surfaces on state rows (Yasuo/
        # Yone P crit-conversion constants — the Asol rule pattern).
        "atom_ids",
        "certified_constants",
        "stat_buff",
        # A ``stat_buff`` an active grants is earned by casting it: the fight
        # engine skips the grant of a slot the resolved rotation never casts.
        # A module whose rotation deliberately omits a zero-damage cast and
        # prices its grant across the window anyway (Kai'Sa E's Supercharge,
        # a duration-weighted average) says so with this flag.
        "off_rotation_grant",
        # A grant that needs NO cast at all: an always-on passive hanging off
        # an active slot's row (Darius E's armor penetration). Autos-only
        # withholds every cast-bought grant and keeps these.
        "innate_grant",
        "target_debuff",
        "post_hit_proc",
        "on_hit",
        "proc_count",
        "dot_duration",
        "dot_tick_interval",
        "deathfire_category",
        "stacking_dot",
        "stack_triggered_buff",
        "applies_dot_stack",
        "applies_item_on_hits",
        "basic_attack_true_ratio",
        # A share of each CRITICAL strike's pre-mitigation damage dealt again
        # as magic (Yunara P); the auto simulation prices it on the crits.
        "critical_strike_magic_ratio",
        "spellblade_true_ratio",
        "spellblade_bonus_true_ratio",
        "auto_attack_override",
        "auto_attack_conversion",
        "double_shot",
        "target_max_health_sensitive",
        "requires_auto_timeline_coupling",
        "stored_damage",
        "execute_threshold_ratio",
        "execute_source",
        "detail",  # display text copied onto the ability's breakdown row
        "unit",  # count label for a proc row ("cleaves"); default is "hits"
        # producer diagnostics / display metadata
        "total_raw",
        "damage_per_tick",
        "total_ticks",
        "tibbers_aura",
        "initial_burst",
        # Authored event ledgers for fixed-count effects.  These are copied
        # into the damage timeline by the fight engine; they are not inferred
        # from aggregate totals.
        "damage_events",
        "control_events",
        "control_scope",
        "control_source_atoms",
        "cc_reviewed",
        "event_phase",
        # Explicit module-owned proof that a dynamic packet is one hit at
        # the cast boundary; this is never inferred from part count alone.
        "event_order_certified",
        "auto_stack_every",
        "short_fuse_cooldown",
        "short_fuse_refund",
        "timeline_event_model",
        "dot_stack_count",
        # Module-authored self-shield payloads (E8c).  A list aligned to the
        # ability's damage-event ordinals; the fight engine copies each entry
        # onto the matching damage event row as ``self_shield``, which the
        # participant ledger turns into a timed self-shield event at that
        # event's timestamp (the Eclipse item authors the same payload shape).
        "self_shield_events",
        # Module-owned share of THIS row's own post-mitigation damage that
        # heals the caster, for a share the healing rule cannot derive from
        # the cache because it is champion-option state (Warwick's Eternal
        # Hunger heals 100% of its damage below 50% maximum health, 250%
        # below 25%).  The champion's own heal resolver reads it
        # off the entry.
        "self_heal_share_of_damage",
        # Module-declared state the champion's self-heal rule reads
        # (``healing.derive_self_healing``).  That rule is handed the parsed
        # entries but neither the champion options nor the target stats, so
        # a heal whose size or count is player state — Cho'Gath's kills,
        # Trundle's nearby deaths, Alistar's carried Triumph stacks,
        # Rek'Sai's Fury, the share of a target's maximum health
        # Mordekaiser's Realm of Death drains — is priced here, where both
        # are in hand, and placed there.  The fight engine never reads it.
        "self_heal_state",
        # Module-authored non-damage state packets.  The pipeline expands
        # these once per accepted cast and sends them to the participant
        # ledger as typed state transitions.
        "self_state_events",
        # Seconds of the fight the champion silences ITSELF and can cast
        # nothing (Rumble's Overheat).  ``fight.rotation.cast_schedule._schedule_shared_casts``
        # takes them off the shared timeline's horizon, so the fight buys
        # the casts the lockout leaves rather than the casts it would have
        # had.  WHERE in the fight the span sits is deliberately not
        # declared: a module that cannot source the instant prices how much
        # casting the window costs, never which casts it eats.
        # The self-silencing resource a kit's own casts build, walked by
        # fight/rotation/cast_resource_lockout.py over the cast plan. It
        # replaced self_cast_lockout_seconds, which asked for the answer.
        "cast_resource_lockout",
        # champions/armed_procs.py: the rule that arms a kit's empowered
        # basic attack, walked over the cast and swing schedules.
        "armed_procs",
        # Champion-owned critical-strike conversion (Yasuo/Yone P): total
        # crit chance doubled, crit damage scaled by a factor, and excess
        # crit chance converted to bonus AD.  The fight engine resolves it
        # once in ``_apply_stat_buff_ultimates`` so ability crit scaling and
        # the auto-attack simulation share the converted values.
        "crit_modifier",
        # A source-backed ability projectile marker used by the coupled
        # target-defense ledger.  It is stamped from the cached ability row.
        "skillshot",
        # A source-backed area-ability marker used by Jax Counter Strike.
        "area_damage",
        # This row's damage is NOT the caster's own action -- pets, summons
        # and persistent zones.  A charmed, stunned or rooted Zyra stops
        # casting; her plants keep attacking, and so does an Annie Tibbers
        # or a Malzahar voidling.  The walk's attacker-state gate exempts
        # such a row from crowd control only: the *target's* stasis,
        # invulnerability and untargetability still block it, because those
        # are facts about who is being hit rather than about who is acting.
        "cast_while_disabled",
        "defensive_interaction",
    }
)


# Keys a ``target_debuff`` payload may carry. Validated for the same
# reason as the entry keys one level up: a misspelled
# ``mr_reduction_flatt`` would silently shred nothing.
_ALLOWED_DEBUFF_KEYS = frozenset(
    {
        "armor_reduction_percent",
        "mr_reduction_percent",
        "armor_reduction_flat",
        "mr_reduction_flat",
        "stacks",  # ramp the reduction one share per hit, up to N
        "threshold_hits",  # apply the full reduction after N hits
        "duration",  # seconds the shred lasts; absent = rest of the fight
    }
)


_ALLOWED_POST_HIT_PROC_KEYS = frozenset(
    {
        "name",
        "breakdown_key",
        "parts",
        "target_debuff",
        "detail",
    }
)


# Key shapes that already passed validation.  Entries are rebuilt per
# parse but their key sets are fixed per (champion, slot, options) code
# path, so the optimizer's thousands of identical parses validate once.
# A never-seen shape — including one produced by a code change — is
# always fully checked.
_VALIDATED_ENTRY_SHAPES: set[tuple[Any, ...]] = set()


class EmittedSlot(NamedTuple):
    """Which champion's entry a parse-time refusal is about.

    Every validator below names the same two facts, so the prefix they
    share is built here once.
    """

    champion_name: str
    result_key: str

    def refuse(self, message: str) -> ValueError:
        """The refusal for this entry, for the caller to raise."""
        return ValueError(f"{self.champion_name} entry {self.result_key!r}: {message}")


def validate_entry_keys(
    emitted: EmittedSlot,
    entry: dict[str, Any],
) -> None:
    """Reject unknown keys on an emitted entry and its target_debuff.

    A misspelled key must never silently zero an ability (or, one level
    down, silently shred nothing).
    """
    post_hit_proc = entry.get("post_hit_proc") or {}
    shape = (
        emitted,
        tuple(entry),
        tuple(entry.get("target_debuff", ())),
        tuple(post_hit_proc),
        tuple(post_hit_proc.get("target_debuff", ()) if post_hit_proc else ()),
    )
    if shape in _VALIDATED_ENTRY_SHAPES:
        return
    for keys, allowed, label, constant in (
        (set(entry), _ALLOWED_ENTRY_KEYS, "entry", "_ALLOWED_ENTRY_KEYS"),
        (
            set(entry.get("target_debuff", ())),
            _ALLOWED_DEBUFF_KEYS,
            "target_debuff",
            "_ALLOWED_DEBUFF_KEYS",
        ),
        (
            set(entry.get("post_hit_proc", ())),
            _ALLOWED_POST_HIT_PROC_KEYS,
            "post_hit_proc",
            "_ALLOWED_POST_HIT_PROC_KEYS",
        ),
        (
            set((entry.get("post_hit_proc") or {}).get("target_debuff", ())),
            _ALLOWED_DEBUFF_KEYS,
            "post_hit_proc.target_debuff",
            "_ALLOWED_DEBUFF_KEYS",
        ),
    ):
        unknown = keys - allowed
        if unknown:
            raise emitted.refuse(
                f"unknown {label} key(s) {sorted(unknown)} (allowed keys "
                f"are defined by engine.{constant})"
            )
    _VALIDATED_ENTRY_SHAPES.add(shape)


def part_reaches_event_ledger(entry: Mapping[str, Any], part: DamagePart) -> bool:
    """Whether one part's hits become authored events the ledger can read.

    The parse-side reading of the emission gate in
    ``fight.rotation.cast_parts._evaluate_cast_parts``, clause for clause: a part with one
    certified landing, an authored instant, a live target-health formula,
    module-authored events, an empowered swing behind it, a sourced control
    interval of its own or a skillshot's own event lands somewhere a
    control marker can be read; anything else is priced into the row's
    aggregate and carries no marker anywhere. Two readers share it — the
    contract below, and the roster census that counts the declarations no
    row can carry.
    """
    parts = entry["parts"]
    return bool(
        (
            entry.get("event_order_certified") == "single_hit"
            and len(parts) == 1
            and part.count <= 1
        )
        or (
            part.time_offset is not None
            and (part.count <= 1 or part.hit_interval is not None)
        )
        or any(other.hp_scaled_damage is not None for other in parts)
        or isinstance(entry.get("damage_events"), list)
        # An empowering cast is delivered BY the basic attacks it forces, so
        # its row's events are authored from the swings the fight engine
        # reattributes to it (``fight.after.empowered_swings._author_empowered_swing_events``) and
        # the marker on them is this entry's own declaration, read back by
        # ``fight.cast_control_marker._declared_cc_marker``.
        or entry.get("empowers_next_auto")
        or part.cc_duration > 0.0
        or part.skillshot
    )


# The instant a multi-part ``single_hit`` row occupies: the cast boundary
# itself, which is where its one landing has always been priced.
_SHARED_INSTANT = 0.0


def certify_shared_instant(
    emitted: EmittedSlot,
    entry: dict[str, Any],
) -> None:
    """Give a multi-part ``single_hit`` row the instant it certifies.

    ``single_hit`` says the row is ONE landing.  A landing is regularly
    computed in more than one part: Syndra's W lands magic plus
    Transcendent's true bonus, Ahri's Q is one pass out and one back, and
    Malphite's W is the empowered attack's bonus plus its cone.  The fight
    engine's certified export carries only a one-part cast
    (``fight.rotation.cast_parts._evaluate_cast_parts``), so the split parts say what they
    are instead: each authors the shared instant as its own
    ``time_offset``, the per-part path that already exports an authored
    hit.  Modules that hand-wrote that offset (Twitch E, Seraphine Q) keep
    theirs — this is the same statement, made once.

    **A landing is not a schedule**, and two tests separate them:

    * a part that hits more than once (``count > 1``) is that part's own
      repetition — Syndra's spheres, Ahri's flames and dashes — and needs
      a sourced cadence, not an instant it does not have;
    * parts authoring DIFFERENT offsets sit at different instants, so the
      row spans an interval rather than landing.

    Either raises, naming the slot: certifying a schedule as a landing is
    the same silent overstatement, in the other direction.
    """
    if entry.get("event_order_certified") != "single_hit":
        return
    parts = entry.get("parts") or ()
    if len(parts) <= 1:
        # One part is the fight engine's own certified export path; leave
        # it exactly as it is rather than authoring an offset it never had.
        return
    for part in parts:
        if part.count > 1:
            raise emitted.refuse(
                "event_order_certified='single_hit' but a part hits "
                f"{part.count} times — a repeated part is a schedule, not "
                "one landing; author its time_offset and hit_interval "
                "instead of certifying"
            )
    offsets = {part.time_offset for part in parts if part.time_offset is not None}
    if len(offsets) > 1:
        raise emitted.refuse(
            "event_order_certified='single_hit' but its parts author "
            f"{sorted(offsets)} — a row whose parts sit at different "
            "instants is not one landing"
        )
    instant = offsets.pop() if offsets else _SHARED_INSTANT
    if any(part.time_offset is None for part in parts):
        entry["parts"] = tuple(replace(part, time_offset=instant) for part in parts)
