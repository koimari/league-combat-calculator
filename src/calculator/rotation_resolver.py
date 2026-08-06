"""Optimal event-order engine (F2) — the per-champion combo layer.

Derives the fight's ``cast_order`` from the atomized ability data and a
per-champion combo-priority table, replacing the naive
``DEFAULT_CAST_ORDER`` whenever a champion has a real combo signal.

Scoring model (see ``docs/rotation-design.md`` for the full write-up)
----------------------------------------------------------------------
For each champion the order of damaging abilities is ranked by four
signals, in decreasing weight:

1. **Setup/consume relationships** (the strongest signal): an ability
   that applies a debuff/mark/poison/stun must cast BEFORE the abilities
   that consume it.  This is read from the atomized data itself — the
   ``target_poisoned`` option and ``dot_duration`` (Cassiopeia Q/E), the
   ``on_hit`` + ``post_hit_proc`` pair (Varus W/Q Blight), the
   stack-application rows (Brand P), the AMP pseudo-slot
   (Vladimir R Hemoplague), the ``stat_buff`` (Aatrox R), the
   mark/proc rows (Lux P Illumination, Zed R stored damage).
2. **DPS contribution per rank at the fight's stats** — ``total_raw``
   divided by the effective per-rank cooldown from the atomized ability
   rows (see :func:`rank_ability_dps`).
3. **Cooldown gating** — the fight engine schedules recasts on one
   shared timeline, so the derived order doubles as the tie-break: a
   low-cooldown spam tool (Cassiopeia E, 0.75s) placed right after its
   setup ability starts its cadence earliest and maximizes casts in the
   window (``_schedule_shared_casts``).
4. **Buffs before damage** — stat/damage amplifiers must resolve before
   the abilities they amplify (Aatrox R, Vladimir R, Annie R's magic
   pen shred).

The table below is the curated per-champion output of that scoring,
with the atom/attribute that drives each entry in ``sources``.  The
fallback for a champion with no combo signal is the engine's historical
``DEFAULT_CAST_ORDER`` (Q, Q2, W, E, R); champions whose reviewed module
declares its own ``CAST_ORDER`` keep that certified order (see
``champions.get_champion_cast_order``) — those are themselves combos and
migrate into this table as they are re-certified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .damage import DEFAULT_CAST_ORDER

# Fallback rationale when no combo rule and no certified order exists.
_DEFAULT_RATIONALE = (
    "Default Q → W → E → R order — no setup/consume combo signal "
    "in the atomized ability data, so the rotation falls back to the "
    "engine's historical cast order."
)


@dataclass(frozen=True)
class ComboRule:
    """One champion's optimal event order and the atoms that justify it.

    Attributes:
        champion: Public champion display name (the ``data/champions.json``
            key and the module-registration key).
        order: The derived ``cast_order`` — the optimal permutation of the
            kit's meaningful slots (setup first, consume second, buffs
            before the damage they amplify).  Entries absent from the
            parsed ability package are skipped harmlessly by the engine.
        rationale: Plain-language explanation of WHY this order is
            optimal, shown verbatim in the UI rotation receipt.
        sources: The atomized attribute / module-metadata rows that drive
            the order (display strings for the receipt and design doc).
        setup: Slots that apply the setup (poison / mark / stacks / buff).
        consume: Slots that consume or detonate the setup.
        aoe: Slot → maximum enemy champions the ability can hit
            (conservative caps, single-target model default 1).  An AoE
            slot's DPS contribution in :func:`rank_ability_dps` is
            weighted by ``min(roster target count, cap)`` so the derived
            order and rationale reflect fights that hit more than one
            champion.
    """

    champion: str
    order: tuple[str, ...]
    rationale: str
    sources: tuple[str, ...] = ()
    setup: tuple[str, ...] = ()
    consume: tuple[str, ...] = ()
    aoe: dict[str, int] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────
# Per-champion combo-priority table (F2 batch 1 — 10 champions)
#
# Each entry is the curated output of the four-signal scoring above.
# ``sources`` names the atom/attribute that drives the ordering so a
# patch-day audit can re-verify the rule against the cached data.
# ─────────────────────────────────────────────────────────────────────

COMBO_TABLE: dict[str, ComboRule] = {
    # Q applies the 3s poison; E consumes it (poisoned bonus) and is the
    # 0.75s-cooldown spam tool; W/R close the burst.  Putting E before W
    # starts E's cadence earlier on the shared cast timeline, which is
    # strictly more E casts in timed fights (the scheduling tie-break).
    "Cassiopeia": ComboRule(
        champion="Cassiopeia",
        order=("Q", "E", "W", "R"),
        rationale=(
            "Q (Noxious Blast) applies the 3s poison (7 ticks) first; E "
            "(Twin Fang) consumes the poison for its enhanced damaged and is "
            "the 0.75s-cooldown spam tool — cast Q, E-spam, and reapply Q as "
            "soon as its cooldown is back. W (Miasma) zones and R (Petrifying "
            "Gaze) closes the burst."
        ),
        sources=(
            "Q 'Total Magic Damage' 3s poison (dot_duration 3.0, 7 ticks)",
            "E 'target_poisoned' option — poisoned bonus 20–120 + 55% AP",
            "E cooldown 0.75s at rank 5 (spam cadence)",
            "W 'Total Magic Damage' 5s zone (dot_duration 5.0)",
        ),
        setup=("Q", "W"),
        consume=("E",),
        aoe={"W": 5, "R": 5},  # Miasma zone + Petrifying Gaze cone
    ),
    # Autos apply Blight (W on-hit); Q detonates every stack as % max HP
    # magic damage (post_hit_proc).  The consume relationship is the whole
    # kit: Q/E/R all detonate, so the detonator order is Q then E then R.
    "Varus": ComboRule(
        champion="Varus",
        order=("Q", "E", "R", "W"),
        rationale=(
            "Basic attacks apply Blight stacks (W Blighted Quiver on-hit, max "
            "3); Q (Piercing Arrow) detonates all stacks for '% of the "
            "target's maximum health' bonus magic damage, so the Blight "
            "stacks must exist before Q fires. E and R detonate too and follow "
            "as burst; W stays last as the on-hit row that prices the per-auto "
            "Blight applications."
        ),
        sources=(
            "W 'Bonus Magic Damage per Stack' (% of target max health, "
            "blight_stacks option, max 3)",
            "W on_hit — every auto applies one Blight stack",
            "Q 'Maximum Physical Damage' + post_hit_proc Blight Detonation",
        ),
        setup=("W",),
        consume=("Q", "E", "R"),
        aoe={"E": 5},  # Hail of Arrows ground zone
    ),
    # Q applies Blaze; R applies one Blaze stack per bounce; only then E
    # spreads the already-applied Blaze.  W is the biggest hit and closes.
    # The stacks feed P's 3-stack detonation (2% max HP per stack).
    "Brand": ComboRule(
        champion="Brand",
        order=("Q", "R", "E", "W"),
        rationale=(
            "Q applies Blaze (and stuns an already-ablaze target); R "
            "(Pyroclasm) applies one Blaze stack per bounce; only then does E "
            "spread the Blaze to the target's surroundings. W (Pillar of "
            "Flame) is the highest-damage ability and closes the combo. The "
            "stacks feed P's 3-stack detonation (2% max HP per stack + "
            "'Max Health Damage')."
        ),
        sources=(
            "P 'Max Health Damage' 3-stack Blaze detonation",
            "Q/W/E each apply 1 Blaze stack (P stack applications)",
            "R applies 1 Blaze stack per bounce (r_bounces option)",
            "E spreads Blaze (wiki prose — utility-only in the packet)",
        ),
        setup=("Q", "R", "W"),
        consume=("E",),
        # Pillar of Flame and the Blaze spread hit every enemy; Pyroclasm
        # already bounces per the r_bounces option (one target per bounce).
        aoe={"W": 5, "E": 5},
    ),
    # R marks the target for 4s and amplifies ALL damage taken by 10% —
    # it must open so the whole burst sits inside the mark.
    "Vladimir": ComboRule(
        champion="Vladimir",
        order=("R", "Q", "E", "W"),
        rationale=(
            "R (Hemoplague) marks the target for 4s, amplifying all damage "
            "taken by 10% (r_hemoplague_debuff option) — it opens so the whole "
            "burst sits inside the mark. Q and E are the sustained damage, and "
            "W (Sanguine Pool) is the 2s DoT that finishes the amplified "
            "window."
        ),
        sources=(
            "R Hemoplague 10% increased damage taken (AMP pseudo-slot, "
            "r_hemoplague_debuff option)",
            "R detonation 'Magic Damage' (165/275/385 + 77% AP)",
            "W 'Total Magic Damage' 2s DoT (dot_duration 2.0)",
        ),
        setup=("R",),
        consume=(),
        aoe={"W": 5, "E": 5, "R": 5},  # pool, charged explosion, hemoplague
    ),
    # R grants bonus AD as a percentage of total AD before Q/W are priced.
    "Aatrox": ComboRule(
        champion="Aatrox",
        order=("R", "Q", "W"),
        rationale=(
            "R (World Ender) grants bonus AD as a percentage of total AD — "
            "the buff resolves before Q/W so The Darkin Blade and Infernal "
            "Chains scale off the buffed AD. Q is the primary damage (three "
            "sweetspot casts); W (Infernal Chains) lands its initial + "
            "pull-back damage after."
        ),
        sources=(
            "R stat_buff 'Bonus Attack Damage' percent_of attack_damage",
            "Q 'First/Second/Third Sweetspot Damage' (sweetspot option)",
            "W 'Total Damage' (initial + pull-back)",
        ),
        setup=("R",),
        consume=(),
        aoe={"Q": 5, "W": 2},  # Darkin Blade sweetspot arc, Infernal Chains
    ),
    # The rotation is anchored on Whisper's 4th shot (guaranteed crit +
    # missing-health bonus) from the auto stream; Q opens, W roots for R.
    "Jhin": ComboRule(
        champion="Jhin",
        order=("Q", "W", "E", "R"),
        rationale=(
            "The rotation is anchored on Whisper's 4th shot — the guaranteed "
            "crit with 15–25% missing-health bonus that the auto stream "
            "produces. Q opens as the fast poke, W (Deadly Flourish) roots the "
            "marked target, E zones, and R (Curtain Call) executes with its "
            "four shots."
        ),
        sources=(
            "P 'Per-Level Scaling' — 4th-shot guaranteed crit + "
            "missing-health bonus (p_final_shot / p_shot_number options)",
            "R 'Physical Damage' 4-shot barrage (3 shots + final round)",
            "W 'Physical Damage' root (Deadly Flourish)",
        ),
        setup=(),
        consume=("R",),
        aoe={"Q": 4, "E": 5},  # Dancing Grenade bounces, Captive Audience zone
    ),
    # Molten Shield opens (buffs-first), Pyromania stuns with the burst, R
    # opens the damage (initial blast + MR shred + aura + Tibbers autos).
    "Annie": ComboRule(
        champion="Annie",
        order=("E", "R", "Q", "W"),
        rationale=(
            "E (Molten Shield) opens so the shield is up before the engage; "
            "Pyromania (P) stuns with the next damaging ability once 4 stacks "
            "are held — the stun rides the burst. R (Tibbers) opens the "
            "damage: initial blast, magic-pen shred, aura, and Tibbers autos "
            "(tibbers_attacks row); then Q and W land while the target is "
            "stunned."
        ),
        sources=(
            "P Pyromania stun (zero-damage row — cc metadata)",
            "E Molten Shield (shield row, support_effects)",
            "R 'Initial Magic Damage' + magic-pen stat_buff + "
            "tibbers_attacks proc row",
            "Q/W 'Magic Damage' burst while stunned",
        ),
        setup=("P", "E"),
        consume=(),
        aoe={"W": 5, "R": 5},  # Incinerate cone, Tibbers summon blast
    ),
    # E slows so the root lands; Q roots; R consumes the Illumination mark.
    "Lux": ComboRule(
        champion="Lux",
        order=("E", "Q", "R", "W"),
        rationale=(
            "E (Lucent Singularity) slows first so the root lands; Q (Light "
            "Binding) roots, guaranteeing Final Spark; R consumes the "
            "Illumination mark (p_illumination_procs). W (Prismatic Barrier) "
            "is the shield and casts last."
        ),
        sources=(
            "E 'Magic Damage' + slow (wiki prose)",
            "Q 'Magic Damage' root (Light Binding)",
            "R 'Magic Damage' + P Illumination consumption "
            "(p_illumination_procs option)",
        ),
        setup=("E", "Q"),
        consume=("R",),
        aoe={"E": 5, "R": 5, "Q": 2},  # zone, Final Spark line, Light Binding
    ),
    # W places the shadow first so E and Q hit from it; R stores that
    # burst and detonates 3s later for 100% AD + % of stored damage.
    "Zed": ComboRule(
        champion="Zed",
        order=("W", "E", "Q", "R"),
        rationale=(
            "W (Living Shadow) places the shadow first so E and Q hit from "
            "it; E (Shadow Slash) slows, Q (Razor Shuriken) deals the primary "
            "damage, then R (Death Mark) stores that burst and detonates 3s "
            "later for 100% AD + 25/40/55% of the damage stored during the "
            "mark."
        ),
        sources=(
            "W 'Living Shadow' shadow placement (no-damage row)",
            "E 'Physical Damage' (70–160 + 70% bonus AD)",
            "Q 'Physical Damage' (80–240 + 100% bonus AD)",
            "R 'Physical Damage' — 100% AD + % of damage stored, "
            "3s detonation delay",
        ),
        setup=("W",),
        consume=("R",),
        aoe={"E": 5},  # Shadow Slash around Zed and the shadow
    ),
    # The main-hand weapon's Q form opens; W swaps the pair so the off-hand
    # Q form unlocks; R fires with the weapon setup landed.
    "Aphelios": ComboRule(
        champion="Aphelios",
        order=("Q", "W", "R"),
        rationale=(
            "The main-hand weapon's Q form opens (selected by the "
            "aphelios_main_weapon option — Calibrum marks for R, Gravitum "
            "roots, Infernum spreads, Crescendum places a turret, Severum "
            "sustains); W (Phase) swaps the weapon pair so the off-hand Q form "
            "unlocks; R (Moonlight Vigil) fires with the weapon setup landed."
        ),
        sources=(
            "Q weapon-form variants (q_variant / aphelios_main_weapon option)",
            "W Phase weapon swap (0.25s cooldown)",
            "R 'Magic Damage' initial blast + basic-attack follow-up",
        ),
        setup=("Q", "W"),
        consume=("R",),
        # Moonlight Vigil damages every enemy it passes through; Q's
        # Infernum form spreads to all in the cone (weapon-dependent).
        aoe={"R": 5, "Q": 5},
    ),
}


def resolve_cast_order(
    champion_name: str,
    ability_damages: Mapping[str, Any],
) -> tuple[list[str], ComboRule | None]:
    """Resolve the fight's ``cast_order`` from the combo table.

    The fallback is the engine's historical default order (with the
    optional second-cast ``Q2`` slot).  Champions whose reviewed module
    declares a certified ``CAST_ORDER`` are handled by the caller
    (:func:`src.calculator.pipeline.run_fight`) when this returns
    ``None``; those certified orders are themselves combo rules and
    migrate into :data:`COMBO_TABLE` as they are re-certified.

    Args:
        champion_name: Public champion display name.
        ability_damages: The parsed ability package.  Kept in the
            signature so a future data-driven pass can verify the rule's
            atoms against the parse (and so callers can skip slots absent
            from the parse).

    Returns:
        ``(cast_order, rule)`` — ``rule`` is the matching
        :class:`ComboRule`, or ``None`` when the champion has no combo
        signal and the default order applies.
    """
    rule = COMBO_TABLE.get(champion_name)
    if rule is not None:
        return list(rule.order), rule
    return list(DEFAULT_CAST_ORDER), None


def rank_ability_dps(
    ability_damages: Mapping[str, Any],
    *,
    ability_haste: float = 0.0,
    target_count: int = 1,
    aoe: Mapping[str, int] | None = None,
) -> list[tuple[str, float, float, float]]:
    """Rank damaging abilities by per-rank DPS at the fight's stats.

    Signal (b) of the scoring model: ``total_raw`` divided by the
    effective per-rank cooldown read from the atomized ability rows.
    Zero- or missing-cooldown rows (on-hits, procs, passives) are
    excluded — they are not rotation casts.  Used by the design doc and
    the F2 tests to prove the table matches the data.

    AoE weighting: a slot listed in ``aoe`` hits up to ``aoe[slot]``
    enemy champions, so its effective DPS is multiplied by
    ``min(target_count, cap)`` — an ability that hits every enemy in a
    five-man roster outranks a single-target nuke of the same raw
    damage.  This is how the optimal order stays optimal when an AoE
    skill hits more than one champion.

    Returns:
        ``[(slot, dps, total_raw, cooldown)]`` sorted by DPS descending.
    """
    aoe = aoe or {}
    target_count = max(1, int(target_count))
    ranked: list[tuple[str, float, float, float]] = []
    for slot, info in ability_damages.items():
        if not isinstance(info, Mapping):
            continue
        cooldown = float(info.get("cooldown", 0.0) or 0.0)
        if cooldown <= 0:
            continue
        raw = float(info.get("total_raw", 0.0) or 0.0)
        if raw <= 0:
            continue
        effective = cooldown * (100.0 / (100.0 + max(0.0, ability_haste)))
        targets = min(target_count, max(1, int(aoe.get(slot, 1))))
        ranked.append((slot, raw * targets / effective, raw, cooldown))
    ranked.sort(key=lambda row: (-row[1], row[0]))
    return ranked


def build_rotation_receipt(
    champion_name: str,
    *,
    cast_order: list[str],
    cast_timeline: list[Any],
    rule: ComboRule | None,
    certified_order: list[str] | None = None,
    user_order: list[str] | None = None,
) -> dict[str, Any]:
    """Build the public ``rotation`` receipt for ``/api/calculate``.

    The receipt's ``order`` is the fight's actual cast sequence from the
    engine's cooldown-aware ``cast_timeline`` (one-rotation: the derived
    permutation, once per slot; timed mode: every recast at its cooldown,
    e.g. Cassiopeia Q, E, E, E, Q, E, ...).  ``rationale`` is the
    combo rule's plain-language explanation so the UI can show WHY the
    order is optimal; champions with no combo signal get a documented
    fallback rationale.

    Returns:
        ``{"order", "rationale", "cast_order", "sources", "setup",
        "consume", "aoe"}`` (JSON-safe; ``aoe`` maps each AoE slot to
        the maximum enemy champions it can hit).
    """
    order: list[str] = []
    for event in cast_timeline:
        if not isinstance(event, Mapping):
            continue
        slot = str(event.get("slot", ""))
        if not slot:
            continue
        order.append(slot)
    if not order:
        order = [str(slot) for slot in cast_order]

    if user_order is not None:
        sequence = ", ".join(user_order)
        rationale = (
            f"Custom order supplied by the request — '{sequence}' is cast "
            "exactly as given; the combo layer defers to explicit input."
        )
        sources = ["request-supplied cast_order"]
        setup = []
        consume = []
        aoe = {}
    elif rule is not None:
        rationale = rule.rationale
        sources = list(rule.sources)
        setup = list(rule.setup)
        consume = list(rule.consume)
        aoe = dict(rule.aoe)
    elif certified_order is not None:
        sequence = ", ".join(certified_order)
        rationale = (
            f"Certified module rotation — '{sequence}' is the champion "
            "module's reviewed order (setup before damage, e.g. Jayce "
            "transforms before casting)."
        )
        sources = ["champion module CAST_ORDER (certified)"]
        setup = []
        consume = []
        aoe = {}
    else:
        rationale = _DEFAULT_RATIONALE
        sources = []
        setup = []
        consume = []
        aoe = {}

    return {
        "order": order,
        "rationale": rationale,
        "cast_order": list(cast_order),
        "sources": sources,
        "setup": setup,
        "consume": consume,
        "aoe": aoe,
    }
