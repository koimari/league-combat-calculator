"""Optimal event-order engine (F3) — algorithmic per-champion combo layer.

Derives the fight's ``cast_order`` from the atomized ability data for ALL
champions, replacing the naive ``DEFAULT_CAST_ORDER`` whenever the data
supports a setup/consume structure.  The ten hand-verified seeds in
:data:`COMBO_TABLE` remain as documented OVERRIDES; every other champion
is derived on the fly by :func:`derive_champion_rule` — no combo database.

Scoring model (see ``docs/rotation-design.md`` for the full write-up)
----------------------------------------------------------------------
For each champion the order of damaging abilities is ranked by four
signals, in decreasing weight:

1. **Setup/consume relationships** (the strongest signal): an ability
   that applies a debuff/mark/poison/stun/shred/buff must cast BEFORE the
   abilities that consume it.  Detected from TYPED atoms only — the
   parsed keys (``dot_duration``, ``on_hit``, ``applies_dot_stack``,
   ``stacking_dot``, ``post_hit_proc``, ``target_debuff``, ``stat_buff``,
   ``cc_kind`` on parts, ``recast_of``), the module OPTION keys
   (``target_poisoned``, ``blight_stacks``, ``p_illumination_procs``,
   ``r_hemoplague_debuff``, ...), and the structured wiki attribute rows
   ("Enhanced Damage", "Bonus Damage Per Stack", "Missing Health
   Damage").  Free-form ability prose is never scanned; the only phrases
   used are the wiki's anchored application rows ("applies a stack of
   X", "become Chilled", "consumes the mark").
2. **DPS contribution per rank at the fight's stats** — ``total_raw``
   divided by the effective per-rank cooldown from the atomized ability
   rows (see :func:`rank_ability_dps`), weighted by the number of enemy
   champions an AoE slot can hit.  A DPS promotion only applies when it
   is CONSISTENT across a level/build reference matrix (L1/L18 x
   no-items/magic/physical/spellblade); otherwise the certified/base
   relative order is kept (deterministic across builds by construction).
3. **Cooldown gating** — the fight engine schedules recasts on one
   shared timeline, so the derived order doubles as the tie-break: a
   low-cooldown spam tool placed right after its setup ability starts
   its cadence earliest and maximizes casts in the window
   (``_schedule_shared_casts``).
4. **Buffs before damage** — ``stat_buff`` rows that amplify ability
   damage (bonus AD / AP / penetration) and damage-taken amplifiers must
   resolve before the abilities they amplify; resistance-shred
   ``target_debuff`` rows open the burst.

Fallback: a champion with NO detectable setup/consume signal keeps the
certified module ``CAST_ORDER`` (when present) or the engine's historical
``DEFAULT_CAST_ORDER``, with a rationale that says exactly that — the
"flat kit" classification is itself data-driven and honest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .ability_spec import ACTION_BLOCKING_CC_KINDS
from .damage import DEFAULT_CAST_ORDER, effective_cooldown

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
            hand-verified seeds in :data:`COMBO_TABLE`.
    """

    champion: str
    order: tuple[str, ...]
    rationale: str
    sources: tuple[str, ...] = ()
    setup: tuple[str, ...] = ()
    consume: tuple[str, ...] = ()
    aoe: dict[str, int] = field(default_factory=dict)
    derived: bool = False


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


# ─────────────────────────────────────────────────────────────────────
# F3 — algorithmic derivation from the atomized ability data
#
# The derivation consumes THREE typed atom surfaces and nothing else:
#
#  1. the parsed ability package (``ability_damages``) — ``dot_duration``,
#     ``on_hit``, ``applies_dot_stack``, ``stacking_dot``,
#     ``post_hit_proc``, ``target_debuff``, ``stat_buff``, ``cc_kind`` on
#     ``parts``, ``recast_of``, ``total_raw``, ``cooldown``;
#  2. the module OPTION rotation declarations
#     (``get_champion_option_rotation``) — the typed setup/consume/execute
#     atoms authored by the champion modules (``target_poisoned``,
#     ``blight_stacks``, ``rend_stacks``, ``p_illumination_procs``,
#     ``moonlight_reset``, execute options, ...), with self_state and
#     irrelevant options acknowledged in the receipt without inventing
#     edges;
#  3. the structured wiki attribute rows in ``data/champions.json``
#     ("Enhanced Damage", "Bonus Damage Per Stack", "Detonation Magic
#     Damage", "Missing Health Damage", "Mark Magic Damage", "Stored
#     Damage").  The only anchored phrases used are the wiki's stable
#     application rows ("applies a stack of X", "become Chilled",
#     "consumes the mark", "takes X% increased damage") — free-form ability
#     prose is never scanned.
# ─────────────────────────────────────────────────────────────────────

# ── typed rotation semantics for option keys ──
# The module OPTIONS declarations (via ``get_champion_option_rotation``)
# are the single authoritative vocabulary: roles setup/consume/execute feed
# ``slot_options`` and edge detection, self_state/irrelevant options are
# acknowledged in the receipt without inventing edges, and an unclassified
# option fails the exhaustiveness contract.  There is deliberately no
# hand-maintained second table in this module anymore (issue #145).

# Default direct-edge kind for consume/execute declarations that carry a
# ``setup_slot`` but no explicit ``kind`` (the declaration is authoritative;
# this is only a fallback for the two direct-edge families).
_DIRECT_EDGE_KIND = {"consume": "mark_consume", "execute": "execute"}

# Damage-amplifying stat_buff keys: buffs-first applies to these only.
_DAMAGE_AMP_STAT_KEYS = {
    "bonus_attack_damage",
    "ability_power",
    "armor_penetration_percent",
    "magic_penetration_percent",
    "bonus_ability_power",
    "bonus_magic_damage",
    "bonus_physical_damage",
    "lethality",
}

# structured wiki attribute rows (exact leveling-row attribute names)
_ATTR_PER_STACK = re.compile(
    r"per stack|per additional stack|per subsequent stack|damage per stack|"
    r"stack bonus|full stack|at max stacks|max stacks|one stack|two stacks|three stacks"
)
_ATTR_ENHANCED_DMG = re.compile(r"enhanc[a-z]* (damage|physical|magic)|prowl-enhanc")
_ATTR_DETONATION = re.compile(r"detonat")
_ATTR_MISSING = re.compile(r"missing")
_ATTR_MARK_DMG = re.compile(r"mark magic damage")
_ATTR_STORED_DMG = re.compile(r"stored damage")

# anchored wiki application/consume rows (confirmation only — never the
# sole signal; every edge also carries a typed atom or structured attr)
_P_APPLIES_STACK = re.compile(r"appl(y|ies|ied|ying).{0,40}\bstack")
_P_MARKS_TARGET = re.compile(
    r"mark(s|ed) (the target|them|enemies|the first enemy|with)"
)
_P_ABILITY_CONSUMES_MARK = re.compile(
    r"abilit(y|ies).{0,80}(consume|detonat).{0,40}mark", re.I
)
_P_TARGET_MISSING = re.compile(
    r"target's? missing|target’s? missing|missing health of the target|missing hp", re.I
)
_P_NAMED_APPLIER_STACK = re.compile(r"([\w' ]+?) apply a stack of ([A-Za-z']+)", re.I)
_P_NAMED_APPLIER_COND = re.compile(
    r"enemies? hit by ([\w' ]+?) (?:or ([\w' ]+?))?.{0,40}?become (chilled|poisoned|marked)",
    re.I,
)
_P_NAMED_CONSUMER = re.compile(
    r"([\w' ]+?) against an enemy with ([A-Za-z']+) stacks? consumes", re.I
)
_P_PASSIVE_ABILITIES_APPLY = re.compile(
    r"abilit(y|ies).{0,80}apply a stack of ([A-Za-z']+)", re.I
)
_P_PASSIVE_ABILITIES_MARK = re.compile(
    r"abilit(y|ies).{0,80}(apply a mark|become marked|are marked)", re.I
)
# target-oriented condition phrase for "Enhanced Damage" consumers
_P_COND_PHRASE = re.compile(
    r"(if|when|while|against|on|vs\.?|versus|doubled|increased|bonus).{0,50}"
    r"(the target|they|it|enemies|an enemy|a target|them|targets?|enemy)"
    r".{0,30}(is|are|were|has|had|take|takes|become)",
    re.I,
)
_P_SELF_RESOURCE = re.compile(
    r"\b(heat|fury|rage|mana|energy|reign of anger|has at least|gains? a stack|"
    r"generates? a stack|at max stacks)\b",
    re.I,
)
# named conditions shared by consume phrases and apply rows
_CONDITIONS = (
    ("poisoned", r"poison"),
    ("chilled", r"chill|frost"),
    ("ablaze", r"ablaze|blaze"),
    ("bleeding", r"bleed"),
    ("marked", r"mark"),
    ("stunned", r"stun"),
    ("rooted", r"root"),
    ("slowed", r"slow"),
    ("charmed", r"charm"),
    ("feared", r"fear"),
    ("wounded", r"wound"),
    ("immobilized", r"immobiliz"),
)

_CAST_SLOTS = ("Q", "Q2", "W", "E", "R")
_PARENT_SLOT = {"Q2": "Q", "R_buff": "R", "W_frenzy": "W", "R_onhit": "R"}


@dataclass(frozen=True)
class _Edge:
    """A detected setup→consume ordering constraint between two cast slots."""

    setup: str
    consume: str
    kind: str
    cite: str

    def sentence(self) -> str:
        """A rationale sentence naming the atoms that drove the edge.

        Edge citations are authored as full sentences ("E applies cc_kind
        crowd control — setup before Q", "Q is a missing-health execute —
        after E's damage"); recast edges get an explicit parent clause.
        """
        if self.kind == "recast":
            return f"{self.consume} is the recast of {self.setup} — {self.cite}"
        return self.cite


# ─────────────────────────────────────────────────────────────────────
# Raw-row corpus (structured fields only: name, attributes, blurb, notes)
# ─────────────────────────────────────────────────────────────────────


def _slot_corpus(
    champion_data: Mapping[str, Any], slot: str
) -> dict[str, list[str]] | None:
    """Structured row corpus for a slot (special slots fall back to parent)."""
    abilities = champion_data.get("abilities", {})
    rows = abilities.get(slot, []) or abilities.get(_PARENT_SLOT.get(slot, slot), [])
    if not rows:
        return None
    out: dict[str, list[str]] = {
        "names": [],
        "attrs": [],
        "descs": [],
        "notes": [],
        "blurb": [],
        "fields": [],
    }
    for row in rows:
        out["names"].append(str(row.get("name") or ""))
        for eff in row.get("effects") or []:
            out["attrs"].extend(
                str(lvl.get("attribute") or "") for lvl in eff.get("leveling") or []
            )
            out["descs"].append(str(eff.get("description") or ""))
        out["notes"].append(str(row.get("notes") or ""))
        out["blurb"].append(str(row.get("blurb") or ""))
        for f in ("targeting", "spellEffects", "affects", "damageType"):
            v = row.get(f)
            if v:
                out["fields"].append(str(v))
    return out


def _corpus_text(corpus: Mapping[str, list[str]]) -> str:
    return " ".join(
        corpus["names"]
        + corpus["attrs"]
        + corpus["descs"]
        + corpus["notes"]
        + corpus["blurb"]
    ).lower()


def _corpus_attrs(corpus: Mapping[str, list[str]]) -> str:
    return " ".join(corpus["attrs"]).lower()


def _is_damage_row(info: Mapping[str, Any]) -> bool:
    if float(info.get("total_raw", 0.0) or 0.0) > 0:
        return True
    return any(
        float(getattr(p, "amount", 0.0) or 0.0) > 0 for p in info.get("parts", ())
    )


def _castable(info: Mapping[str, Any], slot: str) -> bool:
    """A slot that appears on the shared cast timeline (R always casts once)."""
    if slot == "R":
        return True
    return float(info.get("cooldown", 0.0) or 0.0) > 0


# ─────────────────────────────────────────────────────────────────────
# Edge detection
# ─────────────────────────────────────────────────────────────────────


def detect_setup_consume_edges(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-nested-blocks,too-many-return-statements,unused-argument
    champion_name: str,
    ability_damages: Mapping[str, Any],
    champion_data: Mapping[str, Any],
    option_keys: Mapping[str, list[str]],
) -> list[_Edge]:
    """Detect setup→consume ordering constraints from typed atoms.

    See the module docstring for the atom taxonomy.  Returns a list of
    :class:`_Edge` constraints; a champion with no detectable signal
    returns ``[]`` and keeps its certified/default order.
    """

    from .champions import (
        get_champion_option_rotation,
    )  # pylint: disable=import-outside-toplevel

    slots = [s for s in _CAST_SLOTS if isinstance(ability_damages.get(s), Mapping)]
    corpora = {s: _slot_corpus(champion_data, s) for s in slots}
    corpora = {s: c for s, c in corpora.items() if c}
    if not corpora:
        return []
    infos = {s: ability_damages[s] for s in corpora}
    texts = {s: _corpus_text(c) for s, c in corpora.items()}
    atexts = {s: _corpus_attrs(c) for s, c in corpora.items()}
    slot_by_name: dict[str, str] = {}
    for s, c in corpora.items():
        for n in c["names"]:
            if n:
                slot_by_name[n.lower()] = s

    def slot_from_name(nm: str) -> str | None:
        nm = nm.strip().lower()
        if nm in slot_by_name:
            return slot_by_name[nm]
        for key, s in slot_by_name.items():
            if key.startswith(nm) or nm.startswith(key):
                return s
        return None

    edges: list[_Edge] = []

    def add(a: str, b: str, kind: str, cite: str) -> None:
        if a != b and a in corpora and b in corpora:
            edges.append(_Edge(a, b, kind, cite))

    # recast adjacency: a recast rides its parent's casts on the timeline
    for s in slots:
        parent = infos.get(s, {}).get("recast_of")
        if parent and parent in corpora:
            add(parent, s, "recast", f"{s} is {parent}'s recast (recast_of atom)")
    if "Q" in corpora and "Q2" in corpora:
        add("Q", "Q2", "recast", "Q2 is Q's second cast")

    # ── typed apply atoms per slot ──
    apply_atoms: dict[str, list[str]] = {}
    immediate_cc_slots: set[str] = set()
    for s in corpora:
        info = infos[s]
        has_damage_part = any(
            float(getattr(part, "amount", 0.0) or 0.0) > 0.0
            or getattr(part, "hp_scaled_damage", None) is not None
            for part in info.get("parts", ())
        )
        cc_can_set_up_rotation = not has_damage_part or bool(info.get("skillshot"))
        atoms: list[str] = []
        if float(info.get("cooldown", 0.0) or 0.0) <= 0:
            atoms.append("passive-row(cd=0)")  # auto-stream row, not a cast
        if info.get("dot_duration"):
            atoms.append(f"dot_duration={info['dot_duration']}")
        if info.get("on_hit"):
            atoms.append("on_hit")
        if info.get("applies_dot_stack"):
            atoms.append("applies_dot_stack")
        if info.get("stacking_dot"):
            atoms.append("stacking_dot")
        if info.get("target_debuff"):
            atoms.append("target_debuff")
        if info.get("stat_buff") and isinstance(info["stat_buff"], Mapping):
            amp = sorted(set(info["stat_buff"]) & _DAMAGE_AMP_STAT_KEYS)
            if amp:
                atoms.append(f"stat_buff({','.join(amp)})")
        for part in info.get("parts", ()):
            if getattr(part, "cc_kind", None):
                atoms.append(f"cc_kind={part.cc_kind}")
                if (
                    str(part.cc_kind).lower() in ACTION_BLOCKING_CC_KINDS
                    and float(getattr(part, "cc_duration", 0.0) or 0.0) > 0.0
                    and cc_can_set_up_rotation
                    and (
                        getattr(part, "time_offset", None) is None
                        or float(getattr(part, "time_offset", 0.0) or 0.0) <= 0.0
                    )
                ):
                    immediate_cc_slots.add(s)
        for control in info.get("control_events", ()):
            if (
                str(getattr(control, "kind", "")).lower() in ACTION_BLOCKING_CC_KINDS
                and float(getattr(control, "duration", 0.0) or 0.0) > 0.0
                and cc_can_set_up_rotation
                and (
                    getattr(control, "time_offset", None) is None
                    or float(getattr(control, "time_offset", 0.0) or 0.0) <= 0.0
                )
            ):
                immediate_cc_slots.add(s)
        if _P_APPLIES_STACK.search(texts[s]):
            atoms.append("phrase:applies-stack")
        if _P_MARKS_TARGET.search(texts[s]):
            atoms.append("phrase:marks-target")
        apply_atoms[s] = atoms

    # champion passive: "abilities apply a stack/mark of X" -> every slot
    # applies X (Mel Overwhelm, Lux Illumination, ...)
    passive_applies: list[str] = []
    for ps in ("P", "passive"):
        pc = _slot_corpus(champion_data, ps)
        if pc:
            t = _corpus_text(pc)
            passive_applies.extend(
                m.group(2).strip().lower()
                for m in _P_PASSIVE_ABILITIES_APPLY.finditer(t)
            )
            if _P_PASSIVE_ABILITIES_MARK.search(t):
                passive_applies.append("__mark__")

    def applies_condition(s: str, cond_token: str) -> bool:
        atoms = apply_atoms[s]
        t = texts[s]
        # a cd-0 row (on-hit/passive) applies through the AUTO STREAM, not a
        # cast — it can never be a cast-order setup endpoint
        if "passive-row(cd=0)" in atoms:
            return False
        if passive_applies:
            if cond_token == "stack":
                return True
            if cond_token == "mark" and "__mark__" in passive_applies:
                return True
            if any(nm not in ("__mark__",) and nm in t for nm in passive_applies):
                return True
        if cond_token == "stack":
            return any("stack" in a for a in atoms)
        if cond_token == "mark":
            return "phrase:marks-target" in atoms or "target_debuff" in " ".join(atoms)
        return any(cond_token in a for a in atoms)

    # ── typed consume atoms per slot ──
    # The atom vocabulary is the module OPTIONS rotation declarations (issue
    # #145): a consume/execute declaration with ``setup_slot`` carries the
    # FULL edge (setup_slot -> this slot) and is added directly — it never
    # depends on the applier-corpus phrase.  Declarations without
    # ``setup_slot`` fall back to the corpus-based pairing below, keyed by
    # their ``kind`` (the closed edge taxonomy).
    rotations = get_champion_option_rotation(champion_name)
    consume_atoms: dict[str, list[tuple[str, str, str]]] = {}
    for b in corpora:
        info = infos[b]
        cons: list[tuple[str, str, str]] = []
        for key in option_keys.get(b, []) + option_keys.get("__all__", []):
            decl = rotations.get(key)
            if not decl:
                continue
            role = str(decl.get("role", ""))
            if role in ("self_state", "irrelevant", "unsupported"):
                continue
            setup_slot = decl.get("setup_slot")
            if setup_slot:
                # The declaration carries the full edge: the setup slot must
                # cast before this consumer (Diana Q Moonlight -> E reset).
                if setup_slot in corpora and setup_slot != b:
                    kind = str(
                        decl.get("kind") or _DIRECT_EDGE_KIND.get(role, "mark_consume")
                    )
                    add(
                        setup_slot,
                        b,
                        kind,
                        f"{b} consumes {setup_slot}'s setup via option {key} "
                        f"({kind})",
                    )
                continue
            kind = str(decl.get("kind") or role)
            cond = str(decl.get("condition") or kind)
            if role == "execute" and not _is_damage_row(info):
                continue
            cons.append((kind, cond, f"option {key}"))
        if info.get("post_hit_proc"):
            nm = (
                info["post_hit_proc"].get("name", "proc")
                if isinstance(info["post_hit_proc"], Mapping)
                else "proc"
            )
            cons.append(("detonation_consume", "stacks", f"post_hit_proc {nm!r}"))
        execute_ratio = float(info.get("execute_threshold_ratio", 0.0) or 0.0)
        if execute_ratio > 0 and _is_damage_row(info):
            cons.append(
                (
                    "execute",
                    "execute",
                    f"execute_threshold_ratio={execute_ratio:g}",
                )
            )
        at = atexts[b]
        if _ATTR_PER_STACK.search(at):
            cons.append(
                (
                    "stack_consume",
                    "stacks",
                    f"attribute {_ATTR_PER_STACK.search(at).group(0)!r}",
                )
            )
        if _ATTR_ENHANCED_DMG.search(at):
            if _P_TARGET_MISSING.search(texts[b]) and _is_damage_row(info):
                # "Enhanced ... based on the target's missing health" rows are
                # missing-health executes, not conditional-vs-state consumes
                # (Seraphine Q: up to 75% bonus vs missing health).
                cons.append(
                    (
                        "execute",
                        "execute",
                        f"attribute {_ATTR_ENHANCED_DMG.search(at).group(0)!r} + target-missing-health",
                    )
                )
            else:
                cons.append(
                    (
                        "enhanced_consume",
                        "enhanced",
                        f"attribute {_ATTR_ENHANCED_DMG.search(at).group(0)!r}",
                    )
                )
        if _ATTR_DETONATION.search(at):
            cons.append(
                (
                    "detonation_consume",
                    "stacks",
                    f"attribute {_ATTR_DETONATION.search(at).group(0)!r}",
                )
            )
        if (
            _ATTR_MISSING.search(at)
            and _P_TARGET_MISSING.search(texts[b])
            and _is_damage_row(info)
        ):
            cons.append(
                (
                    "execute",
                    "execute",
                    "attribute Missing Health + target-missing-health",
                )
            )
        if _ATTR_MARK_DMG.search(at) or _P_ABILITY_CONSUMES_MARK.search(texts[b]):
            cons.append(("mark_consume", "mark", "mark consumption"))
        if _ATTR_STORED_DMG.search(at):
            cons.append(
                (
                    "stored_consume",
                    "stored",
                    f"attribute {_ATTR_STORED_DMG.search(at).group(0)!r}",
                )
            )
        consume_atoms[b] = cons

    def has_consume_role(b: str, roles: tuple[str, ...]) -> bool:
        return any(r in roles for r, _, _ in consume_atoms[b])

    # ── pairwise edges: setup slots before their consumers ──
    for b, cons in consume_atoms.items():
        bt = texts[b]
        for kind, cond, cite in cons:
            if kind == "dot_consume":
                for a in corpora:
                    if (
                        a != b
                        and any(x.startswith("dot_duration") for x in apply_atoms[a])
                        and "passive-row(cd=0)" not in " ".join(apply_atoms[a])
                    ):
                        add(
                            a,
                            b,
                            "dot_consume",
                            f"{b} {cite} consumes the champion's poison; {a} {', '.join(apply_atoms[a])} applies it",
                        )
            elif kind == "stack_consume":
                for a in corpora:
                    if a != b and applies_condition(a, "stack"):
                        add(
                            a,
                            b,
                            "stack_consume",
                            f"{b} {cite} consumes stacks; {a} {', '.join(apply_atoms[a])} applies them",
                        )
            elif kind == "mark_consume":
                for a in corpora:
                    if a != b and applies_condition(a, "mark"):
                        add(
                            a,
                            b,
                            "mark_consume",
                            f"{b} {cite} consumes the mark; {a} {', '.join(apply_atoms[a])} applies it",
                        )
            elif kind == "mark_applier":
                for a in corpora:
                    if a != b and _is_damage_row(infos[a]) and _castable(infos[a], a):
                        add(
                            b,
                            a,
                            "mark_applier",
                            f"{b} {cite} applies a mark consumed by any next damaging ability",
                        )
            elif kind == "detonation_consume":
                for a in corpora:
                    if a != b and applies_condition(a, "stack"):
                        add(
                            a,
                            b,
                            "detonate",
                            f"{b} {cite} detonates stacks; {a} {', '.join(apply_atoms[a])} applies them",
                        )
            elif kind == "enhanced_consume":
                if not _P_COND_PHRASE.search(bt) or _P_SELF_RESOURCE.search(bt):
                    continue
                for condtok, pattern in _CONDITIONS:
                    if not re.search(pattern, bt):
                        continue
                    for a in corpora:
                        if a == b:
                            continue
                        at = texts[a]
                        if re.search(pattern, at) and any(
                            x.startswith(
                                (
                                    "dot_duration",
                                    "cc_kind",
                                    "phrase:applies-stack",
                                    "applies_dot_stack",
                                    "target_debuff",
                                )
                            )
                            for x in apply_atoms[a]
                        ):
                            add(
                                a,
                                b,
                                "enhanced_consume",
                                f"{b} {cite} enhanced vs {condtok}; {a} applies {condtok} ({', '.join(apply_atoms[a])})",
                            )
                    break
        # named appliers/consumers inside the consumer's own structured rows
        if has_consume_role(b, ("stack_consume", "detonation_consume", "mark_consume")):
            for m in _P_NAMED_APPLIER_STACK.finditer(bt):
                nm = m.group(1)
                if re.search(r"(does not|cannot|do not|won't|no)\s*$", nm):
                    continue
                a = slot_from_name(nm.split(" and ")[-1].strip()) or slot_from_name(nm)
                if a and a != b:
                    atom = cons[0][2] if cons else "stack consume"
                    add(
                        a,
                        b,
                        "stack_consume",
                        f"{b} names {nm.split(' and ')[-1].strip()} as the stack applier ({atom})",
                    )
            for m in _P_NAMED_APPLIER_COND.finditer(bt):
                for g in (m.group(1), m.group(2)):
                    a = slot_from_name(g)
                    if a and a != b:
                        add(
                            a,
                            b,
                            "enhanced_consume",
                            f"{b} names {g} as the condition applier",
                        )
            for m in _P_NAMED_CONSUMER.finditer(bt):
                a = slot_from_name(m.group(1))
                if a and a != b:
                    add(
                        b,
                        a,
                        "mark_applier",
                        f"{b} names {m.group(1)} as the stack consumer",
                    )
        # execute / stored-damage consumers come after ALL other damage;
        # slots that already consume stacks/marks (detonators) are exempt —
        # their consume relationship dominates the missing-health rider.
        if any(kind in ("execute", "stored_consume") for kind, _, _ in cons):
            if not has_consume_role(
                b,
                (
                    "stack_consume",
                    "detonation_consume",
                    "mark_consume",
                    "enhanced_consume",
                ),
            ):
                for a in corpora:
                    if a != b and _is_damage_row(infos[a]) and _castable(infos[a], a):
                        add(
                            a,
                            b,
                            "execute",
                            f"{b} is a missing-health/stored execute — after {a}'s damage",
                        )

    # mark applier by own text: slot says its mark is consumed by the
    # champion's abilities (Ezreal W, Ryze E) -> slot before the burst
    for b in corpora:
        if (
            _P_ABILITY_CONSUMES_MARK.search(texts[b])
            and "phrase:marks-target" in apply_atoms[b]
        ):
            for a in corpora:
                if a != b and _is_damage_row(infos[a]) and _castable(infos[a], a):
                    add(b, a, "mark_applier", f"{b}'s mark is consumed by abilities")

    # ── fan-out: shred / buff / cc / amp before all castable damage ──
    for s in corpora:
        info = infos[s]
        atoms = apply_atoms[s]
        if "passive-row(cd=0)" in atoms:
            continue
        if info.get("target_debuff"):
            for d in corpora:
                if d != s and _is_damage_row(infos[d]) and _castable(infos[d], d):
                    add(
                        s,
                        d,
                        "shred",
                        f"{s} applies target_debuff resistance shred — before {d}",
                    )
        amp_keys = [a for a in atoms if a.startswith("stat_buff(")]
        if amp_keys:
            for d in corpora:
                if d != s and _is_damage_row(infos[d]) and _castable(infos[d], d):
                    add(
                        s,
                        d,
                        "buff",
                        f"{s} {amp_keys[0]} amplifies ability damage — before {d}",
                    )
        if s in immediate_cc_slots:
            for d in corpora:
                if d != s and _is_damage_row(infos[d]) and _castable(infos[d], d):
                    if d in immediate_cc_slots and _CAST_SLOTS.index(
                        s
                    ) > _CAST_SLOTS.index(d):
                        continue
                    add(
                        s,
                        d,
                        "cc_setup",
                        f"{s} applies cc_kind crowd control — setup before {d}",
                    )
        if has_consume_role(s, ("amp",)):
            for d in corpora:
                if d != s and _is_damage_row(infos[d]) and _castable(infos[d], d):
                    add(
                        s,
                        d,
                        "amp",
                        f"{s} amplifies damage taken ({s}'s AMP atom) — before {d}",
                    )

    seen: set[tuple[str, str, str]] = set()
    out: list[_Edge] = []
    for e in edges:
        key = (e.setup, e.consume, e.kind)
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


# ─────────────────────────────────────────────────────────────────────
# AoE classification + DPS ranking
# ─────────────────────────────────────────────────────────────────────


def detect_aoe_cap(champion_data: Mapping[str, Any], slot: str) -> int:
    """Conservative AoE cap from the structured row fields."""
    corpus = _slot_corpus(champion_data, slot)
    if not corpus:
        return 1
    fields = " ".join(corpus["fields"]).lower()
    if any(t in fields for t in ("aoe", "area of effect")) or "Location" in " ".join(
        corpus["fields"]
    ):
        return 5
    return 1


# ─────────────────────────────────────────────────────────────────────
# Order construction: constraints + matrix-consistent DPS tie-break
# ─────────────────────────────────────────────────────────────────────


def _kahn_order(slots: list[str], edges: list[_Edge], tie_key: Any) -> list[str] | None:
    successors: dict[str, list[str]] = {s: [] for s in slots}
    indegree = {s: 0 for s in slots}
    for e in edges:
        if e.setup in successors and e.consume in successors:
            successors[e.setup].append(e.consume)
            indegree[e.consume] += 1
    ready = sorted([s for s in slots if indegree[s] == 0], key=tie_key)
    order: list[str] = []
    while ready:
        s = ready.pop(0)
        order.append(s)
        for nxt in successors[s]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
                ready.sort(key=tie_key)
    return order if len(order) == len(slots) else None


# level x build reference matrix for the DPS-consistency gate (mirrors the
# golden snapshot's sweep builds)
_MATRIX_SPECS = (
    (1, ()),
    (11, ()),
    (18, ()),
    (18, ("Luden's Echo", "Shadowflame", "Rabadon's Deathcap")),
    (18, ("Kraken Slayer", "Infinity Edge", "Lord Dominik's Regards")),
    (18, ("Trinity Force", "Infinity Edge", "Berserker's Greaves")),
)

# per-champion cache: matrix DPS rows at the reference points
_MATRIX_DPS_CACHE: dict[str, list[list[tuple[str, float]]]] = {}

# per-(champion, option-signature) cache: the FULL-KIT derived rule (order is
# matrix-invariant by construction; the fight's own level/build only narrows
# which slots exist, and the option signature keeps option-gated slots and
# option-sensitive edges deterministic across cache warmth — issue #145 §6).
_DERIVED_RULE_CACHE: dict[tuple[str, frozenset[tuple[str, Any]] | None], ComboRule] = {}


def _matrix_dps_rows(  # pylint: disable=import-outside-toplevel
    champion_name: str, champion_data: Mapping[str, Any], aoe: Mapping[str, int]
) -> list[list[tuple[str, float]]]:
    """Per-rank DPS at the reference level/build matrix (cached per champion).

    The matrix is a pure function of the champion's cached data — it never
    depends on the request's level or build — so it is computed once per
    process and reused by every fight.
    """
    cached = _MATRIX_DPS_CACHE.get(champion_name)
    if cached is not None:
        return cached

    from .champions import (
        parse_champion_abilities,
    )  # pylint: disable=import-outside-toplevel
    from .data_fetcher import fetch_item_data  # pylint: disable=import-outside-toplevel
    from .stats import calculate_total_stats  # pylint: disable=import-outside-toplevel

    items_by_name = {d["name"]: d for d in fetch_item_data().values()}
    target_stats = {
        "target_max_health": 2000.0,
        "target_current_health": 2000.0,
        "target_missing_health": 0.0,
    }
    rows: list[list[tuple[str, float]]] = []
    for level, build in _MATRIX_SPECS:
        items = [items_by_name[n] for n in build if n in items_by_name]
        stats = calculate_total_stats(dict(champion_data), level, items)
        parsed = parse_champion_abilities(
            dict(champion_data),
            level,
            stats["ability_power"],
            ability_ranks=None,
            champion_stats=stats,
            target_stats=target_stats,
            champion_options=None,
        )
        rows.append(rank_ability_dps(parsed, target_count=1, aoe=aoe))
    _MATRIX_DPS_CACHE[champion_name] = rows
    return rows


def _canonical_kit_parse(  # pylint: disable=import-outside-toplevel,unused-argument
    champion_name: str,
    champion_data: Mapping[str, Any],
    champion_options: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """The full-kit parse (level 11, no items) used for the cached derivation.

    The derived order is matrix-invariant by construction, so the derivation
    runs once against the canonical kit; a request's own level/build only
    narrow which slots exist.  The request's OPTION state is part of the
    derivation: option-gated slots (Kalista's Soul-Marked W) and
    option-sensitive edges are derived per option state, so a cold cache
    cannot drop a slot the fight actually casts (issue #145 §6).
    """

    from .champions import (
        parse_champion_abilities,
    )  # pylint: disable=import-outside-toplevel
    from .stats import calculate_total_stats  # pylint: disable=import-outside-toplevel

    data = dict(champion_data)
    stats = calculate_total_stats(data, 11, [])
    return parse_champion_abilities(
        data,
        11,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
        champion_options=champion_options,
    )


def _freeze_option_value(value: Any) -> Any:
    """Convert JSON-shaped option values into stable cache-key values."""
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (str(key), _freeze_option_value(item)) for key, item in value.items()
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_option_value(item) for item in value)
    return value


def _option_signature(
    champion_name: str, champion_options: Mapping[str, Any] | None
) -> frozenset[tuple[str, Any]] | None:
    """A canonical cache discriminator for the derivation's option state.

    Only the champion's DECLARED option keys participate, so pipeline keys
    (``fight_duration_seconds``, ...) never split the cache; ``None``/empty
    maps to ``None`` so the default-option derivation keeps one cache row
    per champion.
    """
    if not champion_options:
        return None

    from .champions import (
        get_champion_options_meta,
    )  # pylint: disable=import-outside-toplevel

    declared = {
        str(opt.get("key", ""))
        for opt in get_champion_options_meta(champion_name).get("options", [])
    }
    return frozenset(
        (key, _freeze_option_value(champion_options[key]))
        for key in sorted(champion_options)
        if key in declared
    )


def _fit_rule_to_fight(
    cached: ComboRule,
    champion_name: str,
    fight_slots: set[str],
    certified_order: list[str] | None,
) -> ComboRule:
    """Filter a full-kit rule to the fight's parsed slots.

    The cached rule is the FULL-KIT derivation (matrix-invariant); the
    fight's own parse decides which slots exist — filter the order to the
    available slots, preserving relative positions.  Option-gated slots
    absent from the canonical kit (Kalista's Soul-Marked W, Gnar's Mega R)
    fall back to their base-order position.  Applied on BOTH the warm-cache
    and cold-cache paths so the result is deterministic across cache warmth
    (issue #145 §6).
    """
    available = [s for s in cached.order if s in fight_slots]
    base = [
        s for s in (certified_order or list(DEFAULT_CAST_ORDER)) if s in fight_slots
    ]
    for slot in base:
        if slot not in available:
            available.append(slot)
    return ComboRule(
        champion=champion_name,
        order=tuple(available) if available else cached.order,
        rationale=cached.rationale,
        sources=cached.sources,
        setup=cached.setup,
        consume=cached.consume,
        aoe=dict(cached.aoe),
        derived=True,
    )


def derive_champion_rule(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    champion_name: str,
    ability_damages: Mapping[str, Any],
    champion_data: Mapping[str, Any],
    certified_order: list[str] | None = None,
    champion_options: Mapping[str, Any] | None = None,
) -> ComboRule:
    """Algorithmically derive the champion's optimal cast order.

    Steps (see the module docstring and ``docs/rotation-design.md``):

    1. Detect setup/consume edges from the typed atoms and the module
       OPTIONS rotation declarations (see
       :func:`detect_setup_consume_edges`).
    2. Base order = certified module ``CAST_ORDER`` when present, else the
       engine ``DEFAULT_CAST_ORDER``.
    3. No edges → keep the base order (honest flat-kit fallback; the
       rationale never claims "no signal" while an enabled option is
       unclassified or unsupported).
    4. Edges → topological sort; free slots ranked by per-rank DPS at the
       fight's stats, but only when the ranking is CONSISTENT across the
       level/build matrix (else the certified/base relative order is kept,
       which is deterministic across builds by construction).
    5. Build a :class:`ComboRule` with a rationale citing the driving
       atoms and the setup/consume/aoe receipts.

    The derivation is cached per (champion, option signature): the canonical
    kit is parsed with the request's option state, so option-gated slots
    (Kalista's Soul-Marked W) and option-sensitive edges derive per option
    state instead of dropping out on a cold cache.

    Returns:
        The derived rule (``derived=True``).  The order is a permutation
        of the fight's base slots — no new slots, none dropped.
    """
    fight_slots = {
        s for s in ability_damages if isinstance(ability_damages.get(s), Mapping)
    }
    signature = _option_signature(champion_name, champion_options)
    cache_key = (champion_name, signature)
    cached = _DERIVED_RULE_CACHE.get(cache_key)
    if cached is not None:
        return _fit_rule_to_fight(cached, champion_name, fight_slots, certified_order)

    # Derive from the CANONICAL full-kit parse (level 11, no items), not the
    # request's parse — the request may be a partial kit (level 1) and the
    # derivation must reflect the champion's complete mechanic surface.  The
    # request's option state is honored so option-gated slots participate.
    ability_damages = _canonical_kit_parse(
        champion_name, champion_data, champion_options
    )

    from .champions import (  # pylint: disable=import-outside-toplevel
        get_champion_option_rotation,
        get_champion_options_meta,
    )

    base = [
        s
        for s in (certified_order or list(DEFAULT_CAST_ORDER))
        if isinstance(ability_damages.get(s), Mapping)
    ]
    aoe = {
        s: detect_aoe_cap(champion_data, s)
        for s in ability_damages
        if isinstance(ability_damages[s], Mapping)
    }

    # slot_options is built from the AUTHORITATIVE rotation declarations:
    # roles setup/consume/execute feed edge detection; self_state and
    # irrelevant options are acknowledged in the receipt without inventing
    # edges; an unclassified or unsupported option is surfaced verbatim.
    meta = get_champion_options_meta(champion_name)
    rotations = get_champion_option_rotation(champion_name)
    slot_options: dict[str, list[str]] = {}
    option_receipts: list[str] = []
    for opt in meta.get("options", []):
        key = str(opt.get("key", ""))
        decl = rotations.get(key)
        if not decl:
            option_receipts.append(f"option {key} (unclassified rotation semantics)")
            continue
        role = str(decl.get("role", ""))
        slot = decl.get("slot")
        if role in ("setup", "consume", "execute"):
            if slot:
                slot_options.setdefault(slot, []).append(key)
            else:
                slot_options.setdefault("__all__", []).append(key)
            option_receipts.append(
                f"option {key} ({role}"
                + (f", slot {slot}" if slot else "")
                + (f", consumes {decl['setup_slot']}" if decl.get("setup_slot") else "")
                + ")"
            )
        elif role in ("self_state", "irrelevant"):
            option_receipts.append(
                f"option {key} ({role}" + (f", slot {slot}" if slot else "") + ")"
            )
        elif role == "unsupported":
            option_receipts.append(f"option {key} (unsupported rotation semantics)")

    edges = detect_setup_consume_edges(
        champion_name, ability_damages, champion_data, slot_options
    )

    if not edges:
        unclassified = [
            line
            for line in option_receipts
            if "unclassified" in line or "unsupported" in line
        ]
        if unclassified:
            # A rotation receipt cannot claim "no detectable setup/consume
            # signal" while an enabled semantic option is unclassified or
            # unsupported (issue #145 acceptance).
            rationale = (
                f"{champion_name} has option(s) not yet classified for "
                "rotation semantics: "
                + "; ".join(unclassified)
                + ". The certified module order"
                + (
                    " " + " → ".join(certified_order)
                    if certified_order
                    else " (engine default Q → Q2 → W → E → R)"
                )
                + " is kept exactly as reviewed."
            )
        else:
            rationale = (
                f"{champion_name} has no detectable setup/consume signal in the "
                "atomized ability data — no DoT/poison/mark/stack consumer, no "
                "resistance shred, no damage-amplifying buff, no missing-health "
                "execute. The certified module order"
                + (
                    " " + " → ".join(certified_order)
                    if certified_order
                    else " (engine default Q → Q2 → W → E → R)"
                )
                + " is kept exactly as reviewed; the flat kit derives no reorder."
            )
            if option_receipts:
                rationale += (
                    " Declared options classified for rotation: "
                    + ", ".join(option_receipts)
                    + "."
                )
        rule = ComboRule(
            champion=champion_name,
            order=tuple(base),
            rationale=rationale,
            sources=("no setup/consume atoms detected (flat kit)",)
            + tuple(option_receipts),
            setup=(),
            consume=(),
            aoe=aoe,
            derived=True,
        )
        _DERIVED_RULE_CACHE[cache_key] = rule
        return _fit_rule_to_fight(rule, champion_name, fight_slots, certified_order)

    base_idx = {s: i for i, s in enumerate(base)}
    outgoing = {s: any(e.setup == s for e in edges) for s in base}

    def tie_base(s: str) -> tuple[int, int]:
        return (0 if outgoing.get(s) else 1, base_idx.get(s, 99))

    stable = _kahn_order(base, edges, tie_base)
    if stable is None:
        # cycle in the detected edges — fall back to the certified order and
        # flag the ambiguity for the verification swarm.
        rationale = (
            f"{champion_name}'s detected setup/consume edges form a cycle "
            "(conflicting atoms) — the certified module order "
            + (" ".join(certified_order) if certified_order else "Q → Q2 → W → E → R")
            + " is kept; the ambiguous atoms are listed for the F4 swarm."
        )
        sources = tuple(e.sentence() for e in edges) + tuple(option_receipts)
        rule = ComboRule(
            champion=champion_name,
            order=tuple(base),
            rationale=rationale,
            sources=sources,
            setup=tuple(sorted({e.setup for e in edges})),
            consume=tuple(sorted({e.consume for e in edges})),
            aoe=aoe,
            derived=True,
        )
        _DERIVED_RULE_CACHE[cache_key] = rule
        return _fit_rule_to_fight(rule, champion_name, fight_slots, certified_order)

    fight_dps = rank_ability_dps(ability_damages, target_count=1, aoe=aoe)
    dps_idx = {s: i for i, (s, *_) in enumerate(fight_dps)}

    def tie_dps(s: str) -> tuple[Any, ...]:
        return (dps_idx.get(s, 10**9), 0 if outgoing.get(s) else 1, base_idx.get(s, 99))

    fight_order = _kahn_order(base, edges, tie_dps)
    use_dps_order = fight_order is not None
    if fight_order is not None:
        for point_rows in _matrix_dps_rows(champion_name, champion_data, aoe):
            idx = {s: i for i, (s, *_) in enumerate(point_rows)}

            def tie(s: str, idx=idx) -> tuple[Any, ...]:
                return (
                    idx.get(s, 10**9),
                    0 if outgoing.get(s) else 1,
                    base_idx.get(s, 99),
                )

            if _kahn_order(base, edges, tie) != fight_order:
                use_dps_order = False
                break

    order = fight_order if use_dps_order else stable

    setup = tuple(sorted({e.setup for e in edges}))
    consume = tuple(sorted({e.consume for e in edges}))
    source_lines = [e.sentence() for e in edges] + list(option_receipts)
    if use_dps_order:
        source_lines.append(
            "free slots ranked by per-rank DPS (total_raw / effective cooldown) — "
            "consistent across the L1/L18 x no-items/magic/physical/spellblade matrix"
        )
    else:
        source_lines.append(
            "DPS ranking is build-sensitive across the reference matrix — free slots "
            "keep their certified/base relative order (deterministic)"
        )
    rationale_lines = [e.sentence() for e in edges]
    if use_dps_order:
        rationale_lines.append(
            "Remaining abilities are ranked by per-rank DPS at the fight's stats "
            "(total_raw / effective cooldown, AoE-weighted) — the ranking is "
            "consistent across the level/build reference matrix."
        )
    else:
        rationale_lines.append(
            "The DPS ranking between the unconstrained abilities is build-sensitive "
            "across the reference matrix, so they keep their certified/base relative "
            "order — the derivation is deterministic across levels and items."
        )
    rationale_lines.append(f"Derived order: {' → '.join(order)}.")
    rule = ComboRule(
        champion=champion_name,
        order=tuple(order),
        rationale=" ".join(rationale_lines),
        sources=tuple(source_lines),
        setup=setup,
        consume=consume,
        aoe=aoe,
        derived=True,
    )
    _DERIVED_RULE_CACHE[cache_key] = rule
    return _fit_rule_to_fight(rule, champion_name, fight_slots, certified_order)


def resolve_cast_order(
    champion_name: str,
    ability_damages: Mapping[str, Any],
    *,
    champion_data: Mapping[str, Any] | None = None,
    certified_order: list[str] | None = None,
    champion_options: Mapping[str, Any] | None = None,
) -> tuple[list[str], ComboRule | None]:
    """Resolve the fight's ``cast_order``: override → algorithmic derive.

    The ten hand-verified :data:`COMBO_TABLE` seeds win (documented
    overrides).  Every other champion with atomized data is derived
    algorithmically by :func:`derive_champion_rule`; a champion with no
    detectable setup/consume signal keeps its certified module order or
    the engine default with an honest data-driven rationale.  Unknown
    names (synthetic fixtures with no cached data) return ``None`` for the
    rule, preserving the F2 fallback contract.

    Args:
        champion_name: Public champion display name.
        ability_damages: The parsed ability package (atoms + per-rank
            ``total_raw`` / ``cooldown`` at the fight's stats) — already
            baked with the fight's options.
        champion_data: The cached champion object (raw wiki rows).  When
            omitted and the name is unknown, the default order applies.
        certified_order: The champion module's reviewed ``CAST_ORDER``, if
            any; looked up when omitted.
        champion_options: The fight's champion options, when available.
            They become part of the derivation cache signature so
            option-gated slots and option-sensitive edges derive per option
            state (issue #145 §6).

    Returns:
        ``(cast_order, rule)`` — ``rule`` is ``None`` only for unknown
        names without atomized data.
    """
    rule = COMBO_TABLE.get(champion_name)
    if rule is not None:
        return list(rule.order), rule
    if champion_data is None and not ability_damages:
        return list(DEFAULT_CAST_ORDER), None
    if certified_order is None:

        from .champions import (
            get_champion_cast_order,
        )  # pylint: disable=import-outside-toplevel

        certified_order = get_champion_cast_order(champion_name)
    derived = derive_champion_rule(
        champion_name,
        ability_damages,
        champion_data or {},
        certified_order,
        champion_options=champion_options,
    )
    return list(derived.order), derived


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
    excluded — they are not rotation casts.  Used by the derivation, the
    design doc, and the F2 tests.

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
        effective = effective_cooldown(cooldown, ability_haste)
        targets = min(target_count, max(1, int(aoe.get(slot, 1))))
        ranked.append((slot, raw * targets / effective, raw, cooldown))
    ranked.sort(key=lambda row: (-row[1], row[0]))
    return ranked


def build_rotation_receipt(  # pylint: disable=unused-argument
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
    e.g. Cassiopeia Q, E, E, E, Q, E, ...).  ``rationale`` is the combo
    rule's plain-language explanation so the UI can show WHY the order is
    optimal; champions with no combo signal get a documented fallback
    rationale.

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
