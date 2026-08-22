"""Slot-archetype engine — runs any champion from a slot map.

A champion is described by a **slot map**: ``{slot_key: slot_parser}``.
A slot parser is a plain function ``SlotCtx -> entry dict | None``,
produced either by an archetype factory in ``slotlib`` (configured with
data) or written as a custom function in the champion's own module.

Slots are evaluated **phase by phase** in ``PHASE_ORDER``
(BUFF -> DEBUFF -> DAMAGE -> ONHIT -> AMP), and in slot-map insertion
order within a phase. BUFF/DEBUFF parsers mutate the shared
``ctx.stats`` / ``ctx.target`` contexts, so damage slots always see
buffed stats — an engine guarantee, not a per-module comment. Parsers
carry their phase as a ``.phase`` attribute stamped by their factory;
plain functions without one default to DAMAGE. ``ctx.results`` is
readable within a phase, so a cross-slot dependent lists after its
dependency in the map.

Engine contract: any non-None entry a parser returns IS emitted —
including zero-damage entries (stat-buff ultimates must never silently
vanish). Dropping a non-damaging slot is the parser's decision.
"""

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping

from ..ability_spec import (
    CC_KIND_VOCABULARY,
    DamagePart,
    Disposition,
    ZeroPolicy,
    part_damage_types,
)
from .inputs import (
    ChampionInputError,
    champion_stat,
    declared_option_defaults,
    target_stat,
)
from .skill_orders import get_ability_rank

# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

BUFF = "buff"  # mutates ctx.stats (e.g. R steroids) — no damage yet
DEBUFF = "debuff"  # mutates ctx.target (e.g. resist shreds)
DAMAGE = "damage"  # emits castable damage entries (the default phase)
ONHIT = "onhit"  # emits on-hit entries layered onto auto attacks
AMP = "amp"  # scales already-computed entries (reads ctx.results)

PHASE_ORDER = (BUFF, DEBUFF, DAMAGE, ONHIT, AMP)

SlotParser = Callable[["SlotCtx"], dict[str, Any] | None]

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


# ---------------------------------------------------------------------------
# Slot context
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SlotCtx:
    """Everything a slot parser may read (and, per phase, mutate).

    ``stats``, ``target``, and ``results`` are shared across all slots of
    one parse: BUFF/DEBUFF phases mutate the first two, and ``results``
    accumulates emitted entries in evaluation order.

    The three input blocks are read through :meth:`stat`, :meth:`target_stat`
    and :meth:`option`, never with a ``.get(key, <literal>)``: a fallback
    literal keeps a formula answering after its input stops arriving, and the
    resulting zero would be stamped ``MEASURED``.  ``champions/inputs.py``
    holds the vocabularies and their declared defaults.
    """

    slot: str  # slot-map key being parsed
    champion_name: str  # for skill-order lookup
    abilities: dict[str, list] = field(default_factory=dict)
    level: int = 1
    stats: dict[str, float] = field(default_factory=dict)
    target: dict[str, float] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    ability_ranks: dict[str, int] | None = None
    # The champion's declared OPTIONS defaults, resolved once per parse.
    # Empty for a synthetic fixture with no module, which is why reading an
    # option it never declared raises there too.
    option_defaults: Mapping[str, Any] = field(default_factory=dict)

    def stat(self, name: str) -> float:
        """One build stat by declared name (``inputs.CHAMPION_STATS``)."""
        return champion_stat(self.stats, name, champion=self.champion_name)

    def target_stat(self, name: str) -> float:
        """One target stat by declared name (``inputs.TARGET_STATS``)."""
        return target_stat(self.target, name, champion=self.champion_name)

    def option(self, key: str) -> Any:
        """One declared option: the user's value, or the module's default.

        The default is the module's own ``OPTIONS`` row, the row the frontend
        renders, so the fallback and the number the user sees cannot
        disagree.  An undeclared key raises rather than yielding a zero that
        would be published as a measured number.
        """
        if key not in self.option_defaults:
            raise ChampionInputError(
                f"{self.champion_name or 'a champion module'} read option "
                f"{key!r}, which its OPTIONS declaration does not contain — "
                f"an undeclared option is unwired input, not a default (D-24)"
            )
        value = self.options.get(key)
        return self.option_defaults[key] if value is None else value

    def bump_stat(self, name: str, delta: float) -> float:
        """Accumulate onto a declared build stat, returning the new value."""
        updated = self.stat(name) + delta
        self.stats[name] = updated
        return updated

    def ability(self, slot: str | None = None, index: int = 0) -> dict | None:
        """The ability JSON at (slot, index), or ``None`` if absent.

        Defaults to entry 0 of this parser's own slot.
        """
        entries = self.abilities.get(slot or self.slot, [])
        if index >= len(entries):
            return None
        return entries[index]

    def rank_for(self, slot: str | None = None) -> int:
        """Resolve the ability rank: explicit override, else skill order."""
        key = slot or self.slot
        if self.ability_ranks and key in self.ability_ranks:
            return self.ability_ranks[key]
        return get_ability_rank(key, self.level, self.champion_name)

    def ranked(
        self, slot: str | None = None, index: int = 0
    ) -> tuple[dict, int] | None:
        """The ``(ability, rank)`` a slot parser needs, or ``None``.

        ``None`` is either reason the slot prices nothing, and a parser must
        not tell them apart: no such entry cached, or no point in it yet.
        """
        ability = self.ability(slot, index)
        if ability is None:
            return None
        rank = self.rank_for(slot)
        return None if rank < 1 else (ability, rank)


# ---------------------------------------------------------------------------
# Parser builder
# ---------------------------------------------------------------------------


# The coupled optimizer re-parses the same champion for thousands of fights,
# so values derived purely from the cached ability JSON are memoized by
# object identity.  Entries keep a strong reference to their source dict and
# verify it on every hit (the ``resolve_damage_effects`` pattern), so a
# data refresh that rebuilds the champion cache can never serve stale
# values through a recycled ``id()``.  Superseded generations are kept, not
# evicted — a deliberate, patch-cadence-bounded leak shared by every
# identity memo in this codebase.
_CAST_TIME_MEMO: dict[int, tuple[dict[str, Any], float]] = {}
_RESOURCE_COST_MEMO: dict[tuple[int, int, int], tuple[dict[str, Any], float]] = {}


def _stamp_cast_time(
    entry: dict[str, Any], ability_json: dict[str, Any] | None
) -> None:
    """Stamp a castable entry with its slot JSON's cast time.

    One home instead of every slot parser plumbing it. Only castable
    entries (they carry a cooldown) occupy the timed fight's shared cast
    timeline; slot-fn-supplied values win; instant casts (0.0) stay
    unstamped, so an entry with no cast time is counted as an instant.
    """
    if "cooldown" not in entry or "cast_time" in entry or ability_json is None:
        return
    memo = _CAST_TIME_MEMO.get(id(ability_json))
    if memo is not None and memo[0] is ability_json:
        cast_time = memo[1]
    else:
        # Deferred import: slotlib imports the phase constants from this
        # module, so engine.py must not import slotlib at module level.
        # pylint: disable-next=import-outside-toplevel,cyclic-import
        from .slotlib import extract_cast_time

        cast_time = extract_cast_time(ability_json)
        _CAST_TIME_MEMO[id(ability_json)] = (ability_json, cast_time)
    if cast_time > 0:
        entry["cast_time"] = cast_time


# Camille's and Ambessa's Q2 are free recasts: one paid cast buys both halves.
# A charge is not one, it is a whole cast stocked in advance, and a slot
# parser that knows the difference stamps its own ``resource_cost``.
def _is_free_recast(entry: dict[str, Any]) -> bool:
    """Whether this entry is a recast the parent cast already paid for."""
    return bool(entry.get("recast_of"))


def _stamp_resource_cost(
    entry: dict[str, Any],
    ability_json: dict[str, Any] | None,
    *,
    rank: int,
    level: int,
    resource_type: str,
) -> None:
    """Stamp a cast's locally sourced resource cost onto its engine entry.

    A slot parser that stamps its own ``resource_cost`` wins outright — the
    price of a synthetic slot, which owns no ability JSON of its own, is
    champion knowledge and only the module has it.
    """
    if "resource_cost" in entry or ability_json is None:
        return
    if resource_type not in {"MANA", "ENERGY"} or "cooldown" not in entry:
        return
    entry["resource_type"] = resource_type
    if _is_free_recast(entry):
        entry["resource_cost"] = 0.0
        return
    memo_key = (id(ability_json), rank, level)
    memo = _RESOURCE_COST_MEMO.get(memo_key)
    if memo is not None and memo[0] is ability_json:
        entry["resource_cost"] = memo[1]
        return
    # Deferred import: slotlib imports the phase constants from this
    # module, so engine.py must not import slotlib at module level.
    # pylint: disable-next=import-outside-toplevel,cyclic-import
    from .slotlib import extract_resource_cost

    cost = extract_resource_cost(ability_json, rank, level)
    _RESOURCE_COST_MEMO[memo_key] = (ability_json, cost)
    entry["resource_cost"] = cost


def _stamp_slot_facts(
    entry: dict[str, Any],
    ctx: "SlotCtx",
    *,
    level: int,
    resource_type: str,
) -> None:
    """Stamp the facts a slot's own cached ability entry carries.

    One call site instead of two, so a slot's cast time and its price are
    read from the same ability JSON or from neither: a synthetic slot owns
    no entry at all, and both stamps hand it straight back.
    """
    ability_json = ctx.ability()
    _stamp_cast_time(entry, ability_json)
    if ability_json is not None:
        # Source-backed delivery markers the coupled target-defense ledger
        # reads (Braum E / Yasuo W block projectiles; Jax E counters area
        # damage): stamped from the cached ability row, never inferred.
        if ability_json.get("projectile") not in (None, ""):
            entry.setdefault("skillshot", True)
        spell_effects = str(ability_json.get("spellEffects", "")).lower()
        if "aoe" in spell_effects or "area of effect" in spell_effects:
            entry.setdefault("area_damage", True)
    _stamp_resource_cost(
        entry,
        ability_json,
        rank=ctx.rank_for(),
        level=level,
        resource_type=resource_type,
    )


# Key shapes that already passed validation.  Entries are rebuilt per
# parse but their key sets are fixed per (champion, slot, options) code
# path, so the optimizer's thousands of identical parses validate once.
# A never-seen shape — including one produced by a code change — is
# always fully checked.
_VALIDATED_ENTRY_SHAPES: set[tuple[Any, ...]] = set()


def _validate_entry_keys(
    champion_name: str,
    result_key: str,
    entry: dict[str, Any],
) -> None:
    """Reject unknown keys on an emitted entry and its target_debuff.

    A misspelled key must never silently zero an ability (or, one level
    down, silently shred nothing).
    """
    post_hit_proc = entry.get("post_hit_proc") or {}
    shape = (
        champion_name,
        result_key,
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
            raise ValueError(
                f"{champion_name} entry {result_key!r}: unknown {label} "
                f"key(s) {sorted(unknown)} (allowed keys are defined by "
                f"engine.{constant})"
            )
    _VALIDATED_ENTRY_SHAPES.add(shape)


def _validate_cc_event_contract(
    champion_name: str,
    result_key: str,
    entry: dict[str, Any],
) -> None:
    """A part-authored ``cc_kind`` must be a known kind that reaches the
    event ledger.

    CC-triggered item passives (Imperial Mandate's Command, Fimbulwinter's
    Everlasting) read the marker off authored damage events only. A marker
    on an entry the fight engine will aggregate coarsely — no single-hit
    certification, no authored ``time_offset``, no dynamic part, no
    module-authored event list — silently never triggers anything, so it
    is rejected here, at parse time, instead. Mirrors the emission gate in
    ``damage._evaluate_cast_parts``. ``cc_kind="none"`` is held to the same
    standard: a reviewed *absence* of control is only worth declaring where
    the ledger can see it, because that is where the control token is
    cleared — a "none" that never reaches an event proves nothing about the
    fight it was supposed to certify, and would read as a reviewed slot
    while leaving the coarse row it rides on unreviewed.
    """
    parts = entry.get("parts") or ()
    for part in parts:
        # A sourced duration with no kind is half a declaration; the kind
        # arrives from the part itself or from MODULE_CC (stamped before
        # this check), never later.
        if (
            getattr(part, "cc_duration", 0.0) > 0
            and getattr(part, "cc_kind", None) is None
        ):
            raise ValueError(
                f"{champion_name} entry {result_key!r}: a part authors "
                f"cc_duration={part.cc_duration} without a cc_kind"
            )
    cc_parts = [part for part in parts if getattr(part, "cc_kind", None) is not None]
    if not cc_parts:
        return
    for part in cc_parts:
        if part.cc_kind.lower().strip() not in CC_KIND_VOCABULARY:
            raise ValueError(
                f"{champion_name} entry {result_key!r}: unknown cc_kind "
                f"{part.cc_kind!r} (known kinds are defined by "
                "ability_spec.CC_KIND_VOCABULARY)"
            )
    certified = entry.get("event_order_certified") == "single_hit"
    has_dynamic_part = any(part.hp_scaled_damage is not None for part in parts)
    has_authored_events = isinstance(entry.get("damage_events"), list)
    # An empowering cast is delivered BY the basic attacks it forces, so
    # its row's events are authored from the swings the fight engine
    # reattributes to it (``damage._author_empowered_swing_events``) and
    # the marker on them is this entry's own declaration, read back by
    # ``damage._declared_cc_marker``. That producer is the carrier, so the
    # part-timing tests below are the wrong question to ask of this row.
    empowers = bool(entry.get("empowers_next_auto"))
    for part in cc_parts:
        emits = (
            (certified and len(parts) == 1 and part.count <= 1)
            or (
                part.time_offset is not None
                and (part.count <= 1 or part.hit_interval is not None)
            )
            or has_dynamic_part
            or has_authored_events
            or empowers
        )
        if not emits:
            raise ValueError(
                f"{champion_name} entry {result_key!r}: cc_kind "
                f"{part.cc_kind!r} would never reach the event ledger — "
                "certify event_order_certified='single_hit' (one landing), "
                "author the part's time_offset, author damage_events, or "
                "empower a basic attack; without one of these the CC "
                "silently triggers nothing"
            )


# A cast whose only damage is the basic attack it forces prices at zero on
# its own account.  That is a declaration, not a computation, so the marker
# part it carries is a structural zero with a reason.
_EMPOWER_MARKER_ZERO = ZeroPolicy(
    disposition=Disposition.STRUCTURAL_ZERO,
    reason=(
        "an empowering cast deals no damage of its own: its bonus rides the "
        "basic attacks it forces, so this part exists only to carry the "
        "module's reviewed cc_kind onto the swings the fight engine "
        "reattributes to the row"
    ),
)


# The channels that ride the holder's basic attacks as a *rate* rather
# than as a cast: an entry declaring one is priced per swing, forever, in
# every branch it has (Corki's Hextech Munitions, Gangplank's Trial by
# Fire).  Its damage lands on the auto stream, which is never an ability
# event, so a crowd-control declaration on such a row can never be read.
#
# An ``on_hit`` payload is deliberately NOT here: it belongs to a cast
# that may or may not force a swing depending on the fight's options
# (Kassadin's W does both), so an on-hit row with no swing this parse is
# simply a row that prices nothing — the quiet answer below, not a
# contradiction.
_SWING_RIDER_CHANNELS = frozenset(
    {
        "basic_attack_true_ratio",
        "spellblade_true_ratio",
        "spellblade_bonus_true_ratio",
        "auto_attack_override",
        "auto_attack_conversion",
        "double_shot",
    }
)


def _empower_marker_part(
    entry: dict[str, Any],
    kind: str,
    champion_name: str,
    slot: str,
) -> DamagePart | None:
    """The carrier for a declaration on a slot that emits no damage part.

    ``ability_on_hit_entry`` and the empower shells return ``parts = ()``:
    their bonus rides the on-hit stream and the row's own damage is the
    consumed swing ``damage._reattribute_empowered_swings`` moves onto it.
    Those swings DO author events, and ``damage._declared_cc_marker`` reads
    the kind to stamp on them off this entry's parts — so a partless shell
    is exactly the case where a declaration would look landed and reach
    nothing.  One zero-damage part gives the marker somewhere to live.

    A partless slot that prices itself per swing
    (:data:`_SWING_RIDER_CHANNELS`) has no cast in any branch, so its
    declaration can never be read and is refused rather than stamped.

    ``None`` is the third answer, and the only quiet one: an entry with no
    parts and no swing rider prices nothing this parse — an option emptied
    it (Corki's barrage at zero charges, Kassadin's unempowered W) or the
    slot is pure state.  A row with no damage authors no event for
    anything to miss.
    """
    if not entry.get("empowers_next_auto"):
        channels = sorted(_SWING_RIDER_CHANNELS & set(entry))
        if not channels:
            return None
        raise ValueError(
            f"{champion_name} slot {slot!r}: MODULE_CC declares {kind!r} but "
            f"the slot prices itself per basic attack through {channels} and "
            "emits no damage part — that damage never becomes an ability "
            "event, so the declaration would reach nothing"
        )
    damage_type = str(entry.get("damage_type", ""))
    if damage_type not in part_damage_types():
        raise ValueError(
            f"{champion_name} slot {slot!r}: MODULE_CC declares {kind!r} on a "
            f"partless empower whose damage_type is {damage_type!r}, which is "
            "not a part damage type (known types are defined by "
            "ability_spec.part_damage_types)"
        )
    return DamagePart(
        damage_type,
        0.0,
        cc_kind=kind,
        zero_policy=_EMPOWER_MARKER_ZERO,
    )


#: The ``MODULE_CC`` value for a slot whose control is not one answer.
#:
#: A slot-level kind is a constant, and some slots do not have one: the
#: kind varies by part (Zac's Elastic Slingshot knocks back the first
#: bounce and slows the rest), by option (Aphelios' weapon, Sion's charge
#: time, Yasuo's two Q stacks) or by both.  Those slots author the kind on
#: the part that carries it, and name themselves here so the declaration
#: still lists every reviewed slot in one place.  It is a pointer, not a
#: second home: :func:`_apply_module_cc` stamps nothing for such a slot,
#: and authoring a kind on a slot NOT declared here is refused
#: (:func:`_refuse_undeclared_part_cc`), so the pointer cannot go stale.
CC_PER_PART = "per_part"


def _apply_module_cc(
    entry: dict[str, Any],
    kind: str,
    champion_name: str,
    slot: str,
) -> None:
    """Stamp the module's declared cc kind on every part this slot emits.

    ``MODULE_CC`` declares the kit fact once, per slot; a slot emits one
    cast, so every part of that cast carries the same reviewed control
    state.  Stamping here rather than at each construction site is what
    makes the declaration true of parts a module rebuilds after
    ``damage_entry`` (Pantheon's Q and R do exactly that) and of parts an
    AMP-phase slot appends to a finished entry (Amumu's Cursed Touch),
    instead of only of the ones that happened to go through a builder
    keyword.

    A part that carries its own kind under a constant declaration is a
    second home for one fact — whether it agrees or not — so it raises: a
    slot whose control really does vary within the cast declares
    :data:`CC_PER_PART` instead, and one whose control is a constant keeps
    the constant in ``MODULE_CC`` alone.

    A slot with no parts at all gets one built for it, stops the import,
    or is a row that prices nothing: :func:`_empower_marker_part` rules
    which.  A declaration on a row that does price damage always stamps
    rather than returning quietly.
    """
    if kind == CC_PER_PART:
        # The parts already carry the answer, and a branch that reviewed
        # its way to *no* answer (Rammus' aggregated thorns row) leaves
        # them bare on purpose.  Stamping here would overwrite both.
        return
    parts = entry.get("parts") or ()
    if kind == "none":
        # The reviewed no-CC statement: the fight engine's event rows read
        # it as ``cc_reviewed`` (a row with no kind at all is unreviewed).
        if entry.get("control_events"):
            raise ValueError(
                f"{champion_name} slot {slot!r}: MODULE_CC declares no crowd "
                "control but the entry authors control_events"
            )
        entry["cc_reviewed"] = True
    if not parts:
        marker = _empower_marker_part(entry, kind, champion_name, slot)
        if marker is not None:
            entry["parts"] = (marker,)
        return
    stamped: list[Any] = []
    for part in parts:
        existing = getattr(part, "cc_kind", None)
        if existing is not None:
            raise ValueError(
                f"{champion_name} slot {slot!r}: MODULE_CC declares "
                f"{kind!r} and a part declares {existing!r} — one cast's "
                "crowd control has one home; drop the part's cc_kind, or "
                f"declare the slot {CC_PER_PART!r} if the kind really does "
                "vary within the cast"
            )
        stamped.append(replace(part, cc_kind=kind))
    entry["parts"] = tuple(stamped)


def _refuse_undeclared_part_cc(
    champion_name: str,
    result_key: str,
    entry: dict[str, Any],
    declared_keys: frozenset[str],
) -> None:
    """A part may only author a kind for a slot ``MODULE_CC`` names.

    Raises:
        ValueError: The entry's parts author crowd control for a slot the
            module's ``MODULE_CC`` does not declare, so the kit's control
            has a second, unlisted home.
    """
    if result_key in declared_keys:
        return
    authored = sorted(
        {
            part.cc_kind
            for part in entry.get("parts") or ()
            if getattr(part, "cc_kind", None) is not None
        }
    )
    if authored:
        raise ValueError(
            f"{champion_name} entry {result_key!r}: parts author cc_kind(s) "
            f"{authored} for a slot MODULE_CC does not declare — declare the "
            f"slot (the constant kind, or {CC_PER_PART!r} when the kind "
            "varies within the cast)"
        )


# The instant a multi-part ``single_hit`` row occupies: the cast boundary
# itself, which is where its one landing has always been priced.
_SHARED_INSTANT = 0.0


def _certify_shared_instant(
    champion_name: str,
    result_key: str,
    entry: dict[str, Any],
) -> None:
    """Give a multi-part ``single_hit`` row the instant it certifies.

    ``single_hit`` says the row is ONE landing.  A landing is regularly
    computed in more than one part: Syndra's W lands magic plus
    Transcendent's true bonus, Ahri's Q is one pass out and one back,
    Amumu's Cursed Touch appends a true part to every entry in the kit,
    Seraphine's Q is a flat term plus a missing-health term, and
    Malphite's W is the empowered attack's bonus plus its cone.  The fight
    engine's certified export carries only a one-part cast
    (``damage._evaluate_cast_parts``), so the split parts say what they
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
            raise ValueError(
                f"{champion_name} entry {result_key!r}: "
                "event_order_certified='single_hit' but a part hits "
                f"{part.count} times — a repeated part is a schedule, not "
                "one landing; author its time_offset and hit_interval "
                "instead of certifying"
            )
    offsets = {part.time_offset for part in parts if part.time_offset is not None}
    if len(offsets) > 1:
        raise ValueError(
            f"{champion_name} entry {result_key!r}: "
            "event_order_certified='single_hit' but its parts author "
            f"{sorted(offsets)} — a row whose parts sit at different "
            "instants is not one landing"
        )
    instant = offsets.pop() if offsets else _SHARED_INSTANT
    if any(part.time_offset is None for part in parts):
        entry["parts"] = tuple(replace(part, time_offset=instant) for part in parts)


def _result_key(slot: str) -> str:
    """The results-dict key for a slot; the fight engine wants ``"passive"``."""
    return "passive" if slot == "P" else slot


def build_parser(
    slot_map: dict[str, SlotParser],
    champion_name: str,
    *,
    cc_kinds: Mapping[str, str] | None = None,
) -> Callable[..., dict[str, dict[str, Any]]]:
    """Build a ``parse_abilities``-signature function from a slot map.

    Slot evaluation order (phase, then insertion order) is fixed here,
    once, at build time.

    Args:
        slot_map: Mapping of slot key (Q/W/E/R/P/...) to slot parser.
        champion_name: Display name, used for skill-order lookup.
        cc_kinds: The module's ``MODULE_CC`` declaration — ``{slot: kind}``
            reviewed crowd control, stamped onto every part the slot emits
            (:func:`_apply_module_cc`).  Keyword-only, and echoed on the
            returned parser so ``module_contract`` can prove the wiring and
            the declaration are the same dict.  Absent for the synthetic
            slot map, which declares no kit facts of its own.

    Returns:
        A function with the standard champion-module signature
        ``(champion_data, level, total_ability_power, ability_ranks=None,
        champion_options=None, champion_stats=None, target_stats=None)
        -> results dict``.
    """
    ordered: list[tuple[str, SlotParser]] = []
    for phase in PHASE_ORDER:
        for slot, parser in slot_map.items():
            parser_phase = getattr(parser, "phase", DAMAGE)
            if parser_phase not in PHASE_ORDER:
                raise ValueError(
                    f"{champion_name} slot {slot!r}: unknown phase "
                    f"{parser_phase!r} (must be one of {PHASE_ORDER})"
                )
            if parser_phase == phase:
                ordered.append((slot, parser))

    # The module's OPTIONS defaults, resolved on the first parse rather than
    # here: this builder runs while the champion module is still executing,
    # so its OPTIONS list does not exist yet.  A module's declaration is
    # source, so one resolution per champion per process is the whole cost.
    declared_options: dict[str, Any] | None = None
    declared_cc_kinds: Mapping[str, str] = dict(cc_kinds) if cc_kinds else {}
    declared_result_keys = frozenset(_result_key(slot) for slot in declared_cc_kinds)

    def parse_abilities(
        champion_data: dict[str, Any],
        level: int,
        total_ability_power: float,
        ability_ranks: dict[str, int] | None = None,
        champion_options: dict[str, Any] | None = None,
        champion_stats: dict[str, float] | None = None,
        target_stats: dict[str, float] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Parse abilities by evaluating the slot map phase-by-phase."""
        nonlocal declared_options
        # Deferred import: slotlib imports the phase constants from this
        # module, so engine.py must not import slotlib at module level.
        # pylint: disable-next=import-outside-toplevel,cyclic-import
        from .slotlib import build_stats_context

        if declared_options is None:
            declared_options = declared_option_defaults(champion_name)
        stats = build_stats_context(champion_stats, total_ability_power)
        target = dict(target_stats) if target_stats else {}
        resource_type = str(champion_data.get("resource", "NONE"))
        results: dict[str, dict[str, Any]] = {}

        for slot, parser in ordered:
            ctx = SlotCtx(
                slot=slot,
                champion_name=champion_name,
                abilities=champion_data.get("abilities", {}),
                level=level,
                stats=stats,
                target=target,
                options=champion_options or {},
                results=results,
                ability_ranks=ability_ranks,
                option_defaults=declared_options,
            )
            entry = parser(ctx)
            if entry is not None:
                _stamp_slot_facts(entry, ctx, level=level, resource_type=resource_type)
                results[_result_key(slot)] = entry

        # Stamp and validate AFTER all phases: AMP parsers mutate earlier
        # entries, and a mutated entry must obey the contract too — Amumu's
        # Cursed Touch appends a true part to every damage slot in the kit,
        # and a part the declaration never reached is an unreviewed event.
        for slot, declared_cc in declared_cc_kinds.items():
            entry = results.get(_result_key(slot))
            if entry is not None:
                _apply_module_cc(entry, declared_cc, champion_name, slot)
        for result_key, entry in results.items():
            _certify_shared_instant(champion_name, result_key, entry)
            _validate_entry_keys(champion_name, result_key, entry)
            _refuse_undeclared_part_cc(
                champion_name, result_key, entry, declared_result_keys
            )
            _validate_cc_event_contract(champion_name, result_key, entry)

        return results

    if cc_kinds is not None:
        parse_abilities.cc_kinds = declared_cc_kinds
    return parse_abilities
