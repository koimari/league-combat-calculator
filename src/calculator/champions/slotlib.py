"""The archetype factories a champion slot parser is built from.

Each factory returns a :class:`SlotParser`: ``simple_damage`` for a slot whose
damage is one named attribute, ``stat_buff`` for a steroid, ``by_option`` for a
slot an input switches between shapes, ``proc_damage`` for a per-proc total, and
``with_item_on_hits`` for a slot that re-applies the build's on-hits.

The rest of the layer lives beside it, one concept per module: the
``effects[].leveling[].modifiers[]`` walk in :mod:`slot_extract`, the entry
dicts a parser hands the fight engine in :mod:`slot_entries`, and control atoms,
cast resolution and recharge in :mod:`slot_control`.
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ..ability_spec import DamagePart, ZeroPolicy
from .attribute_classifier import classify_damage_type
from .slot_context import BUFF, DAMAGE, SlotCtx, SlotParser
from .slot_control import extract_recharge, resolve_casts, resolve_source
from .slot_entries import MODULE_FORMULA_ZERO, STEROID_ZERO, damage_entry, on_hit_entry
from .slot_extract import (
    ability_name,
    extract_auto,
    extract_cooldown,
    extract_named,
    extract_value,
)


def simple_damage(
    attr: str | None = None,
    dmg_type: str = "auto",
    casts: int | str = 1,
    source: tuple[str, int] | None = None,
    cooldown_from: tuple[str, int] | None = None,
    cooldown: str = "standard",
    ranks: str = "rank",
    dot_duration: float | None = None,
    cc_kind: str | None = None,
    *,
    zero_policy: ZeroPolicy = MODULE_FORMULA_ZERO,
    event_order_certified: str | None = None,
    crit_effectiveness: float = 0.0,
) -> SlotParser:
    """Standard castable damage slot.

    With ``attr=None`` (auto mode) this is the old generic-parser
    behavior: classifier-driven attribute detection, in-slot on-hit
    passive detection (targeting "Passive", e.g. Vayne W), and the
    generic drop rule (no damage found AND no damageType field -> slot
    omitted). With an explicit ``attr`` the named attribute is summed
    and the entry is always emitted, even at zero damage.

    Args:
        attr: Exact leveling attribute to sum, or None to auto-detect.
        dmg_type: "magic"/"physical"/"true"/"mixed", or "auto" to
            classify from the ability JSON.
        casts: Damage multiplier — int, or leveling attribute name.
        source: (slot, index) of the JSON entry to read; defaults to
            entry 0 of the parser's own slot.
        cooldown_from: (slot, index) to read cooldown from instead of
            the damage source (subspell/recast containers).
        cooldown: "standard" (the ability's cooldown field) or
            "recharge" (charge abilities — rechargeRate at rank, e.g.
            Amumu Q).
        ranks: "rank" (skill order / overrides, slot skipped below
            rank 1) or "level" (rank pinned to champion level).
        dot_duration: Seconds the ability keeps dealing ability damage
            after the cast (poisons, zone ticks). Item burns (Liandry's,
            Blackfire) stay refreshed for this tail — see
            ``_add_burn_damage``. None (default) emits nothing.
        cc_kind: Reviewed crowd control the cast applies ("stun",
            "immobilize", "root", "slow", …), stamped on the entry's
            first part so CC-triggered item passives can see the cast
            in the event ledger. Requires a single-part slot
            (``dmg_type != "mixed"``). None (default) authors no CC.
            A whole kit's kinds are better declared once in the module's
            ``MODULE_CC``; this stays for a kind that is genuinely a
            property of one construction rather than of the slot.
        zero_policy: Keyword-only. What a zero total from this slot means.
            Defaults to
            :data:`MODULE_FORMULA_ZERO`, the champion tree's one declared
            disposition (D-24); pass a different policy where a zero is a
            declaration rather than a computed result.
        event_order_certified: Keyword-only. ``"single_hit"`` states that
            this cast's one hit lands at the cast boundary, so the engine
            exports it as an authored event instead of folding it into a
            coarse aggregate row. It is a claim about timing and nothing
            else — an ability with sourced travel or delay authors the
            part's ``time_offset`` instead of certifying. A ``"mixed"``
            slot is one landing split into a magic and a true part, which
            certifies too: ``engine.certify_shared_instant`` gives the
            split parts the instant they share.
        crit_effectiveness: Keyword-only. The crit-probability scale this
            slot's own sourced text states ("affected by critical strike
            modifiers" is 1.0, Xin Zhao Q). Default 0.0 is the wiki's
            general rule that ability damage does not crit unless stated.

    Returns:
        A DAMAGE-phase slot parser.
    """
    if cooldown not in ("standard", "recharge"):
        raise ValueError(
            f"simple_damage: unknown cooldown mode {cooldown!r} "
            "(must be 'standard' or 'recharge')"
        )
    if cc_kind is not None and dmg_type == "mixed":
        # The engine exports a certified single-hit event only for a
        # one-part cast; a two-part "mixed" entry would silently drop
        # the CC marker from the ledger. Fail closed instead.
        raise ValueError(
            "simple_damage: cc_kind requires a single-part slot "
            "(dmg_type must not be 'mixed')"
        )
    extract_cd = extract_recharge if cooldown == "recharge" else extract_cooldown

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability, src_slot = resolve_source(ctx, source)
        if ability is None:
            return None

        # In-slot on-hit passives (e.g. Vayne W Silver Bolts) are only
        # auto-detected in auto mode; explicit specs say what they want.
        if attr is None and (ability.get("targeting") or "").lower() == "passive":
            return _slot_passive_on_hit(ctx, ability)

        rank = ctx.level if ranks == "level" else ctx.rank_for(src_slot)
        if rank < 1:
            return None

        cd_ability = ctx.ability(*cooldown_from) if cooldown_from else ability
        cd_value = extract_cd(cd_ability, rank, level=ctx.level) if cd_ability else 0.0

        if attr is None:
            total, resolved_type = extract_auto(
                ability,
                rank,
                ctx.stats,
                ctx.target,
                level=ctx.level,
            )
            if total <= 0 and not ability.get("damageType"):
                # Non-damaging ability (shields, buffs, etc.)
                return None
        else:
            total = extract_named(
                ability, attr, rank, ctx.stats, ctx.target, level=ctx.level
            )
            resolved_type = classify_damage_type(ability)

        if dmg_type != "auto":
            resolved_type = dmg_type

        total *= resolve_casts(casts, ability, rank, ctx.level)
        name = ability_name(ability)
        entry = damage_entry(
            name,
            rank,
            cd_value,
            total,
            resolved_type,
            cc_kind,
            zero_policy=zero_policy,
            event_order_certified=event_order_certified,
            crit_effectiveness=crit_effectiveness,
        )
        if dot_duration is not None:
            entry["dot_duration"] = dot_duration
        return entry

    parse.phase = DAMAGE
    return parse


def stat_buff(
    attr: str,
    stat: str,
    *,
    mode: str = "flat",
    percent_of: str = "attack_damage",
    apply_to: tuple[str, ...] = (),
    damage_attr: str | None = None,
    couples: tuple[str, str] | None = None,
    uptime_option: str | None = None,
) -> SlotParser:
    """BUFF-phase stat steroid (Vayne/Aatrox/Ambessa R pattern).

    Emits a standard damage entry (zero damage unless ``damage_attr``)
    carrying a ``stat_buff`` dict for the fight engine, and optionally
    feeds the buff into the shared ``ctx.stats`` so every later damage
    slot scales off buffed stats (the BUFF phase guarantee).

    Args:
        attr: Leveling attribute holding the buff value.
        stat: Key inside the emitted ``stat_buff`` dict (the fight
            engine dispatches on it, e.g. ``"bonus_attack_damage"``).
        mode: "flat" — the leveling value IS the buff (Vayne R);
            "percent_of" — the leveling value is a percentage of the
            ``percent_of`` stat (Aatrox R: % of total AD).
        percent_of: Stat the percentage applies to (mode="percent_of").
        apply_to: ctx.stats keys the buff value is added to, for
            in-parse scaling. Empty when only the fight engine applies
            it (Ambessa R's armor pen is not a parse-time scaling stat).
        damage_attr: Leveling attribute for the ability's own active
            damage (Ambessa R), extracted from PRE-buff stats. None
            emits 0.0 damage.
        couples: ``(stats_key, attr_name)`` — publish another leveling
            value into ``ctx.stats`` under ``stats_key`` for a dependent
            slot listed later (Vayne R's Tumble cooldown reduction,
            read by Q). The key never leaves the parse context.
        uptime_option: A 0..1 champion option scaling the buff, for a
            steroid the champion only holds part of the fight — a zone he
            has to stand in (Trundle W's Frozen Domain). The scaled value
            is the buff's fight average, which for a bonus-attack-speed
            steroid is exact: attack speed is linear in the bonus percent,
            so ``AS(b x f)`` equals ``f`` seconds at ``AS(b)`` plus
            ``1 - f`` at ``AS(0)``. None applies the buff for the whole
            fight, the reading with no option to dial.

    Returns:
        A BUFF-phase slot parser.
    """
    if mode not in ("flat", "percent_of"):
        raise ValueError(
            f"stat_buff: unknown mode {mode!r} (must be 'flat' or 'percent_of')"
        )

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ranked = ctx.ranked()
        if ranked is None:
            return None
        ability, rank = ranked

        value = extract_value(ability, attr, rank, level=ctx.level)
        if mode == "percent_of":
            value = value / 100.0 * ctx.stat(percent_of)
        uptime = 1.0
        if uptime_option is not None:
            uptime = min(max(float(ctx.option(uptime_option)), 0.0), 1.0)
            value *= uptime

        damage = 0.0
        if damage_attr is not None:
            damage = extract_named(
                ability, damage_attr, rank, ctx.stats, ctx.target, level=ctx.level
            )

        for key in apply_to:
            ctx.stats[key] = ctx.stat(key) + value
        if couples is not None:
            stats_key, couple_attr = couples
            ctx.stats[stats_key] = extract_value(
                ability, couple_attr, rank, level=ctx.level
            )

        name = ability_name(ability)
        entry = damage_entry(
            name,
            rank,
            extract_cooldown(ability, rank, level=ctx.level),
            damage,
            "physical",
            zero_policy=(
                MODULE_FORMULA_ZERO if damage_attr is not None else STEROID_ZERO
            ),
        )
        entry["stat_buff"] = {stat: value}
        if uptime_option is not None:
            entry["detail"] = (
                f"{attr} priced at {uptime:.0%} uptime ({value:g} applied "
                "across the fight window)"
            )
        return entry

    parse.phase = BUFF
    return parse


def by_option(
    option: str,
    cases: Mapping[bool | int | str, SlotParser],
    default: bool | int | str,
) -> SlotParser:
    """Dispatch a slot to one of several parsers by a champion option.

    The q_variant/condemn_wall pattern: the option value picks which
    configured parser runs (Vayne Q's condemn triad vs its plain strike).
    All cases MUST emit the same entry keys, because an option may change
    values and never the emitted shape, and must share one engine phase,
    which is checked at factory time.

    Bool-keyed cases normalize the option value with ``bool()``, so a truthy
    int from the frontend selects the True case.  An unmatched selector emits
    nothing.
    """
    phases = {getattr(parser, "phase", DAMAGE) for parser in cases.values()}
    if len(phases) != 1:
        raise ValueError(
            f"by_option({option!r}): case parsers span multiple engine "
            f"phases {sorted(phases)} — a slot has exactly one phase"
        )
    bool_cases = all(isinstance(key, bool) for key in cases)

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        value = ctx.options.get(option, default)
        if bool_cases:
            value = bool(value)
        case = cases.get(value)
        return case(ctx) if case is not None else None

    parse.phase = phases.pop()
    return parse


ProcDamageResolver = Callable[[SlotCtx, dict[str, Any]], float]


def proc_damage(
    per_proc: ProcDamageResolver,
    dmg_type: str,
    *,
    count_option: str = "passive_procs",
    default_count: int = 4,
    emit_at_zero: bool = False,
    name: str | None = None,
    phase_order_events: bool = False,
) -> SlotParser:
    """Passive that procs N times per fight (Akali/Ambessa/Akshan P).

    Per-proc damage scales per LEVEL (rank pinned to champion level);
    the proc count comes from a champion option. Emits
    ``{name, damage_type, parts: (per-proc DamagePart,), total_raw:
    per_proc * count, proc_count}`` — damage.py schedules entries with a
    ``proc_count`` outside the cast rotation.

    Args:
        per_proc: Champion-owned damage resolver for one proc.
        dmg_type: "magic"/"physical"/"true" — picks the per-proc key.
        count_option: Champion option holding the proc count.
        default_count: Proc count when the option is absent.
        emit_at_zero: Emit the row even at a zero count, for a slot whose
            count the FIGHT derives (an ``armed_procs`` rule): the row has
            to exist for the walk to fill, and a walk that finds nothing
            leaves it priced at zero exactly as before.
        name: Optional emitted label override.

    Returns:
        A DAMAGE-phase slot parser; emits nothing at zero procs or zero
        per-proc damage.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None

        count = int(ctx.options.get(count_option, default_count))
        if count <= 0 and not emit_at_zero:
            return None

        per_proc_damage = per_proc(ctx, ability)
        if per_proc_damage <= 0:
            return None

        result = {
            "name": name or ability_name(ability),
            "damage_type": dmg_type,
            "total_raw": per_proc_damage * count,
            "parts": (DamagePart(dmg_type, per_proc_damage),),
            "proc_count": count,
        }
        if phase_order_events:
            # Only modules with an explicit sourced post-ability trigger
            # order opt into this ledger. Other fixed-count passives remain
            # partial and are withheld by BIS rather than guessed.
            result["event_phase"] = "effect"
            result["damage_events"] = [
                {
                    "time": 0.0,
                    "damage_type": dmg_type,
                    "damage": per_proc_damage,
                    "event_precision": "phase_order",
                }
                for _ in range(count)
            ]
        return result

    parse.phase = DAMAGE
    return parse


def _slot_passive_on_hit(
    ctx: SlotCtx,
    ability: dict[str, Any],
) -> dict[str, Any] | None:
    """Parse a Q/W/E/R ability with ``targeting: "Passive"`` as on-hit."""
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total, resolved_type = extract_auto(
        ability, rank, ctx.stats, ctx.target, level=ctx.level
    )
    if total <= 0:
        return None

    name = ability_name(ability)
    return on_hit_entry(name, total, resolved_type)


def with_item_on_hits(
    parser: SlotParser,
    *,
    effectiveness: float,
    hits: int = 1,
    triggers: Iterable[str] = ("on_hit",),
) -> SlotParser:
    """Wrap a slot parser so its entry declares item on-hit application.

    Used by named champion modules to add wiki-sourced
    ``applies_item_on_hits`` metadata to abilities that apply item on-hits
    (spellblade charges, on-hit items) without rewriting the packet parser.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        if entry is None:
            return None
        entry["applies_item_on_hits"] = {
            "effectiveness": effectiveness,
            "hits": hits,
            "triggers": tuple(triggers),
        }
        return entry

    return parse
