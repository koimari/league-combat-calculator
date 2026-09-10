"""The champions whose cast order is asserted by hand, and the reason each one is."""

from __future__ import annotations

from dataclasses import dataclass, field

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
        derived: ``True`` when the rule was produced algorithmically by
            :func:`derive_champion_rule` (F3), ``False`` for the
            hand-verified seeds in :data:`CAST_ORDER_OVERRIDES`.
        override_reason: Why this order is still hand-held — a member of
            :data:`ORDER_OVERRIDE_REASONS`, required on every entry of
            :data:`CAST_ORDER_OVERRIDES` and ``None`` on a derived rule.
            It is what makes the retirement frontier machine-countable
            instead of doc-claimed (P5-f).
    """

    champion: str
    order: tuple[str, ...]
    rationale: str
    sources: tuple[str, ...] = ()
    setup: tuple[str, ...] = ()
    consume: tuple[str, ...] = ()
    aoe: dict[str, int] = field(default_factory=dict)
    derived: bool = False
    override_reason: str | None = None


# Why an order is still hand-held.  Closed, because "some judgment" is
# how a seed survives forever: a reason that is not one of these four is
# either a mechanic the module should DECLARE or a preference nobody has
# written down.
ORDER_OVERRIDE_REASONS: frozenset[str] = frozenset(
    {
        # The order exists to start a cadence earlier on the shared cast
        # timeline, not because a mechanic requires it.
        "scheduling_preference",
        # The order ranks abilities by damage per second in a way the
        # matrix-consistency gate will not reproduce.
        "dps_tiebreak",
        # A defensive cast is placed before the engage.
        "defensive_precast",
        # The derivation already reproduces this order and the seed is
        # held only until its deletion commit proves it on both baselines.
        "pending_primitive",
    }
)


CAST_ORDER_OVERRIDES: dict[str, ComboRule] = {
    # Cassiopeia — Q applies the 3s poison; E consumes it (poisoned
    # bonus) and is the 0.75s-cooldown spam tool; W/R close the burst.
    # Putting E before W starts E's cadence earlier on the shared cast
    # timeline, which is strictly more E casts in timed fights (the
    # scheduling tie-break).
    "Cassiopeia": ComboRule(
        champion="Cassiopeia",
        override_reason="dps_tiebreak",
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
    # Varus — autos apply Blight (W on-hit); Q detonates every stack as
    # % max HP magic damage (post_hit_proc).  The consume relationship is
    # the whole kit: Q/E/R all detonate, so the detonator order is Q then
    # E then R.
    "Varus": ComboRule(
        champion="Varus",
        override_reason="dps_tiebreak",
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
    # Brand — Q applies Blaze; R applies one Blaze stack per bounce; only
    # then E spreads the already-applied Blaze.  W is the biggest hit and
    # closes.  The stacks feed P's 3-stack detonation (2% max HP per
    # stack).
    "Brand": ComboRule(
        champion="Brand",
        override_reason="dps_tiebreak",
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
    # Vladimir — R marks the target for 4s and amplifies ALL damage taken
    # by 10%; it must open so the whole burst sits inside the mark.
    "Vladimir": ComboRule(
        champion="Vladimir",
        override_reason="dps_tiebreak",
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
    # Annie — Molten Shield opens (buffs-first), Pyromania stuns with the
    # burst, R opens the damage (initial blast + MR shred + aura +
    # Tibbers autos).
    "Annie": ComboRule(
        champion="Annie",
        override_reason="dps_tiebreak",
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
    # Lux — E slows so the root lands; Q roots; R consumes the
    # Illumination mark.
    "Lux": ComboRule(
        champion="Lux",
        override_reason="dps_tiebreak",
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
    # Zed — W places the shadow first so E and Q hit from it; R stores
    # that burst and detonates 3s later for 100% AD + % of stored damage.
    "Zed": ComboRule(
        champion="Zed",
        override_reason="dps_tiebreak",
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
}


def _validate_override_reasons() -> None:
    """Every override says why it is still hand-held, in the closed set.

    Raises:
        ValueError: An entry declares no ``override_reason`` or one
            outside :data:`ORDER_OVERRIDE_REASONS`.
    """
    for name, rule in CAST_ORDER_OVERRIDES.items():
        if rule.override_reason not in ORDER_OVERRIDE_REASONS:
            raise ValueError(
                f"{name}'s cast-order override declares override_reason "
                f"{rule.override_reason!r}, which is not one of "
                f"{sorted(ORDER_OVERRIDE_REASONS)} — a hand-held order that "
                "cannot say why it is still hand-held is a seed nobody can "
                "retire"
            )
