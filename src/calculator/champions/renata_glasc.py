"""Renata Glasc — CP10.6 full-entry-reviewed packet module (E9-2 fixes).

E9-2 gap fixes:
- P (Leverage) is modeled as an on-hit mark: the first basic attack on an
  unmarked target deals bonus magic damage equal to 1% : 2% (based on
  level) (+ 2% per 100 AP) of the target's maximum health (cached P
  Per-Level Scaling row; the AP per-100 ratio is wiki prose).  The mark
  lasts 6 seconds and refreshes on subsequent hits, so a sustained 1v1
  prices ONE unmarked first-hit per target — the ``p_leverage_procs``
  option (default 1).
- E (Loyalty Program) grants Renata herself a shield: "Renata and allies
  struck are granted a shield for 3 seconds".  The shield strength is the
  cached "Shield Strength" row (50-110 + 50% AP) and rides the E damage
  entry as a module-authored self-shield (E8c payload), so the 1v1 ledger
  grants it without needing a teammate.
- Q/E damage remain modeled.

W (Bailout) grants "the target bonus attack speed and bonus movement
speed ... with both of the bonuses increasing in effectiveness by
0% : 100% (based on seconds elapsed)" across its 5 seconds, and the
cache carries both ends of that ramp: "Bonus Attack Speed" (10-30% + 1%
per 100 AP) at the start and "Maximum Bonus Attack Speed" (20-60% + 2%
per 100 AP) at the end.  The self cast's mean of the two rides a
BUFF-phase ``stat_buff``; an ally cast is the roster's and reaches it
through the ally-support scanner.  The movement-speed rows have no
engine channel, and R (Hostile Takeover) berserks its targets — control
the engine records as a kind without a magnitude.

Bailout's LETHAL half (the 100%-health restore paid for with a
maximum-health burn) stays fail-closed, and the conflict behind that
refusal is adjudicated field by field in ``BAILOUT_AUTHORITY``: the burn
CADENCE is settled in favour of the game binary on the repo's Gnar
precedent (0.25s, ten ticks, a 2.5s window), while the burn's damage
CLASS remains unresolved — the cached description calls it true damage,
the same entry's notes call it raw damage, and the binary defines no
damage class for it at all.  A class that cannot be resolved cannot
decide whether a shield or a damage-reduction window absorbs a tick, so
the survival result is unpublishable and the named denial receipts stand.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx
from .module_helpers import buff_window_share
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    proc_damage,
    with_control_event,
)
from .inputs import int_option
from .module_contract import coverage

PACKET_SHA256 = "384ce3a01847e53d1b8cdaaa0d444174ecfba6cfb31d913a020a45fab7d189fa"


# HARDCODED: verify on patch updates — wiki prose on P: the on-hit bonus
# is "+ 2% per 100 AP" of the target's maximum health; the per-level base
# is the cached Per-Level Scaling row (1% : 2%).
_P_AP_RATIO_PER_100 = 2.0
# E shield duration (cached E description: "granted a shield for 3
# seconds").
_E_SHIELD_DURATION = 3.0
# Bailout's window is cached W prose ("infuses ... for 5 seconds"); both
# ends of its ramp are JSON leveling rows.
_W_DURATION_SECONDS = 5.0
_W_SELF_CAST = "self"
_W_ALLY_CAST = "ally"

# --------------------------------------------------------------------------
# W (Bailout) — burn-authority conflict: adjudication record + standing denial
# --------------------------------------------------------------------------
# Bailout's lethal half (restore to full health, then a maximum-health burn
# that kills anyway unless a takedown lands) cannot enter the survival kernel
# until every number it needs has ONE local authority.  Two local sources
# speak to it — the cached Wiki W entry and the local Community Dragon
# character binary — and they did not agree.
#
# ``BAILOUT_AUTHORITY["adjudication"]`` below is the per-field record of that
# disagreement and how each field was settled.  The rule applied is the
# repo's standing precedent (CLAUDE.md, the Gnar Mega-form entry): where the
# game files and the Wiki disagree on a number, **the game files win** — the
# Wiki's stat boxes have been provably stale before (Gnar Mega AD growth 5.7
# on the Wiki against 5.5 in the game).
#
# The adjudication settled the CADENCE and left the DAMAGE CLASS open:
#
#   * cadence — SETTLED, binary.  The Wiki's lethal sentence says one tick
#     every 0.264s (2.64s across the ten ticks it also states).  The binary's
#     RenataW DataValues carry TicksPerSecond = 4.0 (0.25s) with
#     TicksBeforeDeath = 10.0, and the binary's own {85d7d7f0} calculation
#     is literally 0.25 x TicksBeforeDeath — the 2.5s burn window, in
#     the file.  The Wiki corroborates the 4/s clock against itself: the same
#     sentence that says 0.264s also says "Bailout's duration is reset every
#     0.25 seconds" while burning, which is TicksPerSecond = 4 surfacing.
#     0.264s is the outlier; the binary wins on the Gnar precedent.
#   * damage class — UNRESOLVED, fails closed.  The Wiki description calls it
#     a "true damage burn"; the SAME entry's notes call it "raw damage".  The
#     binary defines no damage-class field for the burn at all — the whole
#     RenataW record carries neither a health-loss magnitude nor a damage
#     type (verified: its DataValues are Duration, BonusAttackSpeed,
#     BonusMoveSpeed, APToPercentRatio, TriumphPercent, TicksBeforeDeath,
#     MaxStatMultiplier, TicksPerSecond, TagDuration — and nothing else).
#     The burn is script-side and is not shipped in the CharacterRecords
#     dump.  A SILENT source cannot break a tie, so the class stays open.
#
#     2026-08-20: that silence was re-tested against the CURRENT Community
#     Dragon dump rather than assumed (the search is recorded verbatim in
#     the ``searched`` row of ``burn_damage_class`` below).  The published
#     ``renata.bin.json`` is byte-identical to the tracked local evidence,
#     the champion bin holds no burn effect object at all (RenataWAbility's
#     only child spell IS RenataW), and the one damage-class field the game
#     schema even defines — ``mDamageType`` — occurs ZERO times across all
#     203 local champion bins and ``items.bin.json``.  The class is not
#     shipped as data for ANY champion, so no corroboration of an enum
#     against an uncontested spell is possible; the only damage-ish enum in
#     the dump is bot-AI metadata (``BotData.DamageTag``) that misses true
#     damage on abilities whose class nobody disputes (Vayne W, Sett W and
#     Smolder Q all tag 0) and that carries Renata's per-champion default
#     on W — the same 1 her zero-damage R carries.  Evidence, not proof of
#     absence by assertion: the field stays open.
#
# Why a settled cadence does not make the lethal half publishable:
# the two candidate classes agree only on an UNMITIGATED target.  "True
# damage" is absorbed by shields and scaled by damage reduction; "raw
# damage" is applied to health past both.  Renata's own E shields the very
# participant Bailout covers, so the shielded branch is the common case, not
# a corner — and in it the two readings give different survival answers.
# Publishing the restore without a decidable burn would also overstate
# survival outright: the restore is undone 2.5s later by design.  The
# withheld set therefore stays the full lethal half, and the reason keeps
# its committed name (``burn_authority_conflict``) because an authority
# conflict is exactly what is still open — now narrowed to one field.
#
# Conflict history is kept, never deleted: a resolved conflict that loses its
# record is one patch away from being re-litigated from scratch.
#
# ``tests/test_renata_w_bailout.py`` re-verifies the gamefile rows against
# the digest below when the (gitignored) evidence is present locally.
BAILOUT_AUTHORITY = {
    # -- runtime contract: fail-closed --------------------------------------
    # No survival contract implements Bailout's lethal half, and no number
    # below may be read as one.  ``support_effects`` raises if this flag is
    # flipped without an implementation behind it.
    "runtime_available": False,
    "reason": "burn_authority_conflict",
    # -- the evidence the denial cites --------------------------------------
    "wiki_burn_interval_seconds": 0.264,
    "gamefile_ticks_per_second": 4.0,
    "wiki_description_damage_class": "true",
    "wiki_notes_damage_class": "raw",
    "gamefile_path": "data/bin/characters/renata.bin.json",
    "gamefile_record": "Characters/Renata/Spells/RenataWAbility/RenataW",
    # The client dump this record was read from, matching the other
    # binary-backed receipts in this repo (Aurelion Sol Q, Gnar Mega,
    # items.bin.json).
    "gamefile_patch": "16.15.8024387",
    # sha256 of the RAW BYTES of the file named above, so a reader can
    # re-verify the conflicting evidence with `shasum -a 256`.  ``data/bin/``
    # is gitignored, so this digest is checkable locally only — the test that
    # compares it against the file skips when the evidence is absent rather
    # than passing on an unchecked literal.
    "gamefile_sha256": (
        "d05e6d6eabc614f8821be6ec4c01e09018f6606c6b94eee1712ca04f00e4211e"
    ),
    # The survival components this conflict withholds.  ``support_effects``
    # publishes one public denial receipt per component beside every Bailout
    # cast, so a covered participant's survival row is never read as a
    # complete answer (the alternative — reporting the plain death, or a
    # Guardian Angel resurrection the cached notes say Bailout pre-empts —
    # would be a silently wrong number rather than a named gap).
    "denied_survival_components": (
        "lethal_damage_restore",
        "maximum_health_burn",
        "resurrection_precedence",
    ),
    # -- per-field adjudication record: DESCRIPTIVE ONLY --------------------
    # Nothing in this sub-mapping is a runtime input.  It exists so the next
    # implementer inherits the settled fields instead of re-deriving them,
    # and so the one open field cannot be quietly closed by guesswork.
    # Each row is (binary value, wiki value, chosen value, basis); ``chosen``
    # is ``None`` exactly where no local source can decide the field.
    "adjudication": {
        "precedent": "CLAUDE.md Gnar Mega-form game-file authority",
        "rule": "gamefile_wins_over_wiki",
        "fields": {
            # ---- settled: both sources agree -----------------------------
            "active_duration_seconds": {
                "gamefile": 5.0,
                "gamefile_field": "Duration",
                "wiki": 5.0,
                "chosen": 5.0,
                "basis": "sources_agree",
            },
            "takedown_window_seconds": {
                "gamefile": 6.0,
                "gamefile_field": "TagDuration",
                "wiki": 6.0,
                "chosen": 6.0,
                "basis": "sources_agree",
            },
            "takedown_health_ratio": {
                "gamefile": 0.20,
                "gamefile_field": "TriumphPercent",
                "wiki": 0.20,
                "chosen": 0.20,
                "basis": "sources_agree",
            },
            "burn_ticks": {
                "gamefile": 10,
                "gamefile_field": "TicksBeforeDeath",
                # The Wiki states no tick count directly; ten 10%-maximum-
                # health ticks "until they reach 0 health" is the same 10.
                "wiki": 10,
                "chosen": 10,
                "basis": "sources_agree",
            },
            # ---- settled: the binary won ---------------------------------
            "burn_interval_seconds": {
                "gamefile": 0.25,
                "gamefile_field": "TicksPerSecond=4.0",
                "wiki": 0.264,
                "chosen": 0.25,
                "basis": "gamefile_wins_over_wiki",
                "corroboration": (
                    "spell calculation {85d7d7f0} = 0.25 x TicksBeforeDeath, "
                    "and the Wiki's own 'duration is reset every 0.25 "
                    "seconds' clause in the same sentence"
                ),
            },
            "burn_window_seconds": {
                "gamefile": 2.5,
                "gamefile_field": "TicksBeforeDeath/TicksPerSecond",
                "wiki": 2.64,
                "chosen": 2.5,
                "basis": "follows_burn_interval_adjudication",
            },
            # ---- settled: wiki-only, but nothing contradicts it ----------
            "lethal_restore_ratio": {
                # The binary carries no restore magnitude at all.
                "gamefile": None,
                "wiki": 1.0,
                "chosen": 1.0,
                "basis": "wiki_single_source_unconflicted",
            },
            "burn_health_ratio_per_tick": {
                # The binary carries no health-loss magnitude either.  Ten
                # ticks emptying a 100% restore COHERES with 10% per tick,
                # but that is a consistency check on the Wiki's own two
                # numbers — it is NOT an independent second source, and this
                # row must not be labelled double-sourced.
                "gamefile": None,
                "wiki": 0.10,
                "chosen": 0.10,
                "basis": "wiki_single_source_unconflicted",
            },
            "resurrection_precedence": {
                "gamefile": None,
                "wiki": "over_all_resurrection_and_zombie_state_effects",
                "chosen": "over_all_resurrection_and_zombie_state_effects",
                "basis": "wiki_notes_single_source_unconflicted",
            },
            # ---- OPEN: fails closed --------------------------------------
            "burn_damage_class": {
                # No damage-type field exists anywhere in the RenataW record.
                "gamefile": None,
                # One cached entry, two incompatible answers.
                "wiki": ("true", "raw"),
                "chosen": None,
                "basis": "unresolved_wiki_self_conflict_binary_silent",
                # What was searched before leaving this open, so the next
                # implementer re-runs it only when the game data changes.
                # Every path is a Community Dragon `latest` asset fetched on
                # 2026-08-20 with its sha256 at that time.
                "searched": {
                    "date": "2026-08-20",
                    "assets": (
                        (
                            "game/data/characters/renata/renata.bin.json",
                            "d05e6d6eabc614f8821be6ec4c01e09018f6606c6b94ee"
                            "e1712ca04f00e4211e",
                            "byte-identical to the tracked local evidence; "
                            "no burn effect object, no damage-class field",
                        ),
                        (
                            "game/data/characters/renata/skins/root.bin.json",
                            "e8e6fa554d10762b7508772e33a26c2f5cff540cf85847"
                            "0663a0591c5d5c5e89",
                            "skin/audio metadata only — RenataW appears as "
                            "sfx event names, zero 'damage' substrings",
                        ),
                        (
                            "game/data/characters/renata/skins/skin0.bin.json",
                            "6600c7d42a6e6007275969098af072dc48ace98c27a865"
                            "8cd896e7bc512e552c",
                            "vfx bin — zero 'damage' substrings; excluded by "
                            "the evidence bar in any case",
                        ),
                    ),
                    # Directory listings, not guesses: the champion folder
                    # ships renata.bin(.json), animations/ and skins/ only,
                    # and there is no shared spell-script asset family.
                    "directories": (
                        "game/data/characters/renata/",
                        "game/data/spells/",
                        "game/data/shared/spells/",
                    ),
                    # Field names looked for by name across every local bin
                    # dump (203 champion bins + items.bin.json), each 0 hits.
                    # `mDamageType` is the ONLY damage-class field the hash
                    # table `hashes.binfields.txt` defines at all.
                    "keys_absent_everywhere": (
                        "mDamageType",
                        "mDamageDisplayTypes",
                        "DamageResultType",
                        "mPhysicalDamageRatio",
                    ),
                    # The one enum that does exist, and why it cannot settle
                    # the field: it is BotsSpellData (bot targeting), it is
                    # spell-level rather than effect-level, and it is wrong
                    # on uncontested spells.  DamageTag 2 does line up with
                    # true damage where a spell's damage IS true (Garen R,
                    # Darius R, Fiora R, Cho'Gath R, Master Yi E, Olaf E,
                    # Camille Q2, Vel'Koz R, Urgot R recast), but it misses
                    # partial true damage (Vayne W = 0, Sett W = 0, Smolder
                    # Q = 0, Aurelion Sol Q = 1) and defaults per champion
                    # (every Renata spell = 1, including her zero-damage R).
                    "rejected_field": "BotData.DamageTag (RenataW = 1)",
                    "conclusion": "not_machine_decidable_from_shipped_data",
                },
                "blocker": (
                    "The class decides whether a shield or a damage-reduction "
                    "window absorbs a burn tick. Renata's own E shields the "
                    "participant Bailout covers, so the branch where the two "
                    "readings diverge is the common case. No local source "
                    "can decide it, so the lethal half stays withheld."
                ),
            },
        },
    },
}


def _leverage_per_proc(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """One Leverage proc: per-level % + 2% per 100 AP of target max health."""
    percent = extract_value(ability, "Per-Level Scaling", ctx.level, 0)
    ap = float(ctx.stat("ability_power") or 0.0)
    percent += _P_AP_RATIO_PER_100 * ap / 100.0
    target_max = float(ctx.target_stat("target_max_health") or 0.0)
    return percent / 100.0 * target_max


_leverage = proc_damage(
    _leverage_per_proc,
    "magic",
    count_option="p_leverage_procs",
    default_count=1,
    name="Leverage",
    phase_order_events=True,
)


def _bailout(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the self cast's ramping attack speed, at the ramp's mean."""
    ranked = ctx.ranked("W")
    if ranked is None:
        return None
    ability, rank = ranked

    on_self = str(ctx.option("w_bailout_target")) == _W_SELF_CAST
    start = extract_named(ability, "Bonus Attack Speed", rank, ctx.stats, {})
    end = extract_named(ability, "Maximum Bonus Attack Speed", rank, ctx.stats, {})
    ramp_mean = (start + end) / 2.0
    share = buff_window_share(ctx, _W_DURATION_SECONDS) if on_self else 0.0
    bonus_as = ramp_mean * share
    entry = damage_entry(
        ability.get("name", "Bailout"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = (
        f"+{start:g}% ramping to +{end:g}% bonus attack speed over "
        f"{_W_DURATION_SECONDS:g}s — mean {ramp_mean:g}%, "
        f"{bonus_as:g}% applied"
        if on_self
        else (
            f"cast on an ally: the same +{start:g}% to +{end:g}% ramp is "
            "the roster's and reaches it through the ally-support scanner"
        )
    )
    return entry


_bailout.phase = BUFF


def _loyalty_program(packet_e):
    """E: magic damage row plus Renata's own 3s shield from the rockets."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_e(ctx)
        if entry is None:
            return None
        # The self-shield payload rides the ability's damage-event rows, so the
        # packet part gets an authored cast-boundary offset (the rockets strike
        # targets around Renata on launch).
        entry["parts"] = tuple(
            DamagePart(
                part.damage_type,
                amount=part.amount,
                count=part.count,
                hp_scaled_damage=part.hp_scaled_damage,
                crit_effectiveness=part.crit_effectiveness,
                basic_damage=part.basic_damage,
                bonus_ad_ratio=part.bonus_ad_ratio,
                dot_stack_scaled=part.dot_stack_scaled,
                time_offset=0.0,
                hit_interval=part.hit_interval,
                cc_kind=part.cc_kind,
                cc_duration=part.cc_duration,
                skillshot=part.skillshot,
            )
            for part in entry["parts"]
        )
        ability = ctx.ability("E", 0)
        rank = ctx.rank_for("E")
        shield = (
            extract_named(ability, "Shield Strength", rank, ctx.stats, {})
            if ability is not None
            else 0.0
        )
        if shield > 0.0:
            return attach_self_shield(
                entry,
                amount=shield,
                duration=_E_SHIELD_DURATION,
                source="Loyalty Program",
                detail=(
                    "Magic damage row plus the sourced Shield Strength "
                    "(50-110 + 50% AP) granted to Renata herself for 3s — "
                    "'Renata and allies struck are granted a shield'."
                ),
            )
        return entry

    return parse


# Cached kit review.  Q's hook "deals magic damage to the first enemy hit
# and roots them for 1 second"; the recast's throw and its 0.5-second stun
# land on the enemies the thrown target passes through, not on the hooked
# target this row prices.  E's rockets are the kit's other damaging cast:
# "enemies struck are dealt magic damage and slowed by 30% for 2 seconds".
# W (Bailout) and R (Hostile Takeover) deal no damage — R's berserk is
# real control with no damage row to carry it — and P is an on-hit mark on
# the auto stream, so none of the three can carry an answer of its own.
# R (Hostile Takeover) prices no damage; berserk is a forced action, not
# an immobilize, so it arms no immobilize-gated item.
MODULE_CC = {"Q": "root", "E": "slow", "R": "berserk"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Renata Glasc",
    PACKET_SHA256,
    # The hook deals its damage to the first enemy it hits, once — the
    # boundary claim that carries MODULE_CC's reviewed answer for Q
    # into the event ledger.  E authors its own cast-boundary offset
    # below, beside the shield that rides its events.
    single_hit_slots=frozenset({"Q"}),
    slot_parsers={
        "P": _leverage,
        "W": _bailout,
    },
    slot_wrappers={
        "E": _loyalty_program,
        # Hostile Takeover prices no damage; the berserk it applies is
        # the cached "Berserk Duration" row (1.25/1.75/2.25s).
        "R": lambda parser: with_control_event(
            parser,
            duration_attr="Berserk Duration",
        ),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS: list[dict[str, Any]] = list(OPTIONS) + [
    int_option(
        "p_leverage_procs",
        1,
        minimum=0,
        maximum=10,
        label="Leverage on-hit procs (unmarked first-hits; the mark lasts 6s "
        "and refreshes, so a 1v1 prices one per target)",
        rotation={
            "role": "self_state",
            "slot": "P",
            "note": (
                "P Leverage is an on-hit mark applied/refreshed by the auto "
                "stream — self-state, no cross-slot cast edge."
            ),
        },
    ),
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Leverage) is an on-hit mark: the first basic attack on an "
    "unmarked target deals bonus magic damage equal to 1% : 2% (based on "
    "level) (+ 2% per 100 AP) of the target's maximum health — the "
    "cached Per-Level Scaling row; the mark refreshes on subsequent hits "
    "and expires on a new target, so the 1v1 prices the p_leverage_procs "
    "option (default 1)",
    "E (Loyalty Program) grants Renata herself a 3s shield for the "
    "sourced Shield Strength (50-110 + 50% AP) — the rockets strike "
    "'Renata and allies struck'; the ally half is a scanner packet with "
    "scope all_teammates (every selected teammate the rockets pass "
    "through), so a roster fight shields each selected ally and the 1v1 "
    "prices only the module-authored self shield",
    "W (Bailout) prices its SELF cast: the mean of the two cached "
    "attack-speed rows (Bonus Attack Speed 10-30% + 1% per 100 AP and "
    "Maximum Bonus Attack Speed 20-60% + 2% per 100 AP), which is what "
    "the sourced 0%-to-100% linear ramp averages to over its 5 seconds, "
    "time-weighted by the share of the fight window the buff covers.  "
    "w_bailout_target names who the cast lands on; an ally cast is the "
    "roster's and reaches it through the ally-support scanner.",
    "W's movement-speed rows have no engine channel, and R (Hostile "
    "Takeover) berserks its targets — control the engine records as a "
    "kind without a magnitude.",
    "W (Bailout)'s LETHAL half is documented-only. The Wiki cache "
    "describes a fatal-damage restore to 100% maximum health followed by "
    "10% maximum-health burn ticks that kill the target anyway unless a "
    "takedown lands within 6s. The burn CADENCE is adjudicated to the game "
    "binary (TicksPerSecond 4 -> 0.25s, TicksBeforeDeath 10 -> a 2.5s "
    "window) over the Wiki's 0.264s, on the repo's Gnar game-file "
    "precedent. The burn's DAMAGE CLASS is not adjudicated: the Wiki "
    "description calls it true damage, the same entry's notes call it raw "
    "damage, and the binary defines no damage class for it. That field "
    "decides whether a shield absorbs a tick, and Renata's own E shields "
    "the covered participant, so the survival result fails closed until a "
    "source resolves it — see BAILOUT_AUTHORITY for the per-field record. "
    "The ramping attack-speed and movement-speed buff has no survival "
    "impact on the recipient in this model.",
]

OPTIONS = list(OPTIONS) + [
    {
        "key": "w_bailout_target",
        "type": "select",
        "default": _W_SELF_CAST,
        "label": "Bailout (W) cast on",
        "rotation": {
            "role": "self_state",
            "slot": "W",
            "note": (
                "Names who W lands on; only the self branch reaches this "
                "fighter's stats."
            ),
        },
        "choices": [
            {"value": _W_SELF_CAST, "label": "Renata herself"},
            {"value": _W_ALLY_CAST, "label": "An allied champion"},
        ],
    },
]

# R is emitted and grants nothing the engine prices: berserk is a
# crowd-control kind, and the engine has no magnitude field for it.
MODULE_COVERAGE = coverage(no_damage="R")
