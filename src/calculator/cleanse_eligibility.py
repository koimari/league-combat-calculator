"""Typed item-cleanse eligibility and action-downtime truncation kernel
(roadmap P2 Slice 4).

One dependency-light leaf owns the typed contracts for item actives that
remove crowd-control debuffs — Mikael's Blessing (Purify), Quicksilver Sash
and Mercurial Scimitar (Quicksilver) — orthogonal to delivery type
(:mod:`delivery_eligibility`), crowd-control classification and immunity
(:mod:`crowd_control_eligibility`), and state lifecycle
(:mod:`state_lifecycle`).  Nine separation concerns:

- CONTROL CLASSIFICATION — reused from :mod:`crowd_control_eligibility`
  (:data:`KNOWN_CONTROL_KINDS`, :func:`classify_control`); unknown kinds
  fail closed with the named ``unknown_control`` reason.
- CLEANSE ELIGIBILITY — one sourced declaration per item
  (:data:`ITEM_CLEANSE_DECLARATIONS`); ``CleanseEligibility.decide`` is a
  pure function of the activation and the recipient's ACTIVE control
  intervals at activation.
- ACTIVATION TIME — the walk's total order (``action_key``) resolves
  same-time packets; the decision identity is
  :func:`delivery_eligibility.stable_event_key`.
- TARGET SELECTION — each item declares its target scope
  (``self`` / ``explicit_selected_ally``); a packet whose recipient does
  not match the scope fails closed with ``target_not_selected``.
- USE CONSUMPTION — one use per item per fight (per-fight latch, the
  spell-shield precedent); a second activation fails closed with
  ``use_spent``; the sourced cooldown is receipted
  (:data:`ITEMS` cache carries ``cooldown: null`` for all three actives —
  :attr:`CleanseDeclaration.cooldown_source_gap` names the gap; the local
  client binaries carry 120 s (Mikael's) / 90 s (Mercurial) / 90-vs-0
  conflicting (QSS) — binary-cache-only values are receipted, never
  enforced).
- INTERVAL TRUNCATION — :func:`truncate_intervals` is a pure function:
  historical downtime before activation REMAINS; an active interval ENDS
  at activation (end clamped); a control landing AT activation (same-time
  packets resolve before the cleanse in the walk's total order) is removed
  entirely; controls landing AFTER activation are untouched (a cleanse
  creates NO immunity).
- HEAL — Mikael's Purify heals the target 100-250 by target level, sourced
  from the wiki atom ``heal.flat`` cf9fe930ebd40602.  The heal is a SEPARATE
  effect (its own packet and receipt entry) that fires even when no control
  is active.
- MOVEMENT UTILITY — Mercurial's 50% bonus total movement speed for 2 s,
  sourced from the wiki atom ``control.movement_speed`` 5e5f100f08a793f9,
  is a SEPARATE utility effect (its own packet and receipt entry).
- RECEIPTS — decision/recipient/use receipts with the exact field sets
  pinned by the acceptance matrix.

CASTABILITY (sourced): the wiki Cleanse atom
(``data/wiki-atoms/crowd-control-mobility.json``) and the local client
binaries (``data/bin/items.bin.json``, 16.15.8024387) evidence that
QSS/Mercurial self-casts are castable while disabled
(``canCastWhileDisabled: true``) but NOT under suppression
(``cannotBeSuppressed: true``; the atom: "castable while disabled, but not
under suppression/stasis"); Mikael's ``3222Active`` carries neither flag
so its cast stays gated by the walk's attacker crowd-control gate.  The
kernel encodes the self-scope castability rule as the named
``caster_control_blocks_cleanse`` denial; Mikael's gating is the walk's
pinned attacker-state gate (receipt ``attacker_state_blocked``).

Design rules (HANDOVER section 11): categorical mechanics are small typed
declarations with public receipts; missing values raise naming the
declaration; the kernel never invents a number or policy the caches do
not evidence.
"""

from __future__ import annotations

# pylint: disable=too-many-lines,too-many-return-statements  # one
# dependency-light leaf owns the typed contracts; the decision path's named
# reasons map one-to-one onto returns.
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .ability_spec import DISPLACEMENT_CC_KINDS
from .crowd_control_eligibility import KNOWN_CONTROL_KINDS
from .delivery_eligibility import PacketIdentity, stable_event_key
from .item_effects import ally_item_effect_value, mercurial_quicksilver_movement
from .state_lifecycle import SourceReceipt

_EPS = 1e-9


class CleanseActivation(
    PacketIdentity, Protocol
):  # pylint: disable=too-few-public-methods
    """One cleanse activation as :meth:`CleanseEligibility.decide` reads it.

    The walk builds it from the activating action, the recipient and holder
    ids, and the recipient's live control intervals.
    """

    event_id: str
    target: str
    holder: str
    active_controls: Sequence[Mapping[str, Any]]


# ---------------------------------------------------------------------------
# Sourced item declarations
# ---------------------------------------------------------------------------

#: The three active sources and the item each names (packet ``source`` /
#: ``source_key`` -> declaration item).  Item actives are authored with the
#: display source ("Item — Active"); the resolver accepts the item name
#: itself too.
CLEANSE_ACTIVE_SOURCES: dict[str, str] = {
    "Mikael's Blessing": "Mikael's Blessing",
    "Mikael's Blessing — Purify": "Mikael's Blessing",
    "Quicksilver Sash": "Quicksilver Sash",
    "Quicksilver Sash — Quicksilver": "Quicksilver Sash",
    "Mercurial Scimitar": "Mercurial Scimitar",
    "Mercurial Scimitar — Quicksilver": "Mercurial Scimitar",
}

MIKAELS_WORDING = (
    "Remove all crowd control debuffs (except Airborne, Blind, Disarm, "
    "Nearsight, and Suppression) from yourself or the target allied "
    "champion and heal the target for 100 to 250 (target's level)."
)
QUICKSILVER_WORDING = (
    "Removes all crowd control debuffs (except Airborne) from your champion."
)
MERCURIAL_WORDING = (
    "Removes all crowd control debuffs (except Airborne) from your champion "
    "and grants 50% bonus total movement speed and ghosting for 2 seconds."
)
REMOVE_SCURVY_WORDING = (
    "Active: Gangplank consumes a large quantity of citrus fruit, cleansing "
    "himself from all crowd control and healing himself.  CC-only: debuffs "
    "that are not crowd control are NOT removed (Exhaust's slow is dispelled, "
    "its damage reduction is not); the stun under airborne is removable but "
    "a blink or dash is required to override the displacement."
)

#: P2 Slice 5 — the champion-cast cleanse declaration (Gangplank W).
#:  Atom records from ``data/atoms/abilities.json`` + ``data/atoms/
#:  champions.json`` (hashes independently recomputed; the heal values live
#:  in the ability atoms — the binary heal atom carries cooldown+bitmask,
#:  NOT the heal numbers, so the ability atoms are the numeric receipt and
#:  the binary record is the mechanic receipt).
REMOVE_SCURVY_HEAL_ATOMS: list[dict[str, Any]] = [
    {
        "atom_id": "ability.heal.modifier_0",
        "behavior": "ability",
        "source": "Gangplank.W[0].effects[0].leveling[0].modifiers[0]",
        "name": "Heal",
        "values": [45.0, 70.0, 95.0, 120.0, 145.0],
        "units": ["", "", "", "", ""],
        "hash": "170a83b48f7844c3",
    },
    {
        "atom_id": "ability.heal.modifier_1",
        "behavior": "ability",
        "source": "Gangplank.W[0].effects[0].leveling[0].modifiers[1]",
        "name": "Heal",
        "values": [90.0, 90.0, 90.0, 90.0, 90.0],
        "units": ["% AP", "% AP", "% AP", "% AP", "% AP"],
        "hash": "c8f4c57b1502d6c1",
    },
    {
        "atom_id": "ability.heal.modifier_2",
        "behavior": "ability",
        "source": "Gangplank.W[0].effects[0].leveling[0].modifiers[2]",
        "name": "Heal",
        "values": [13.0, 13.0, 13.0, 13.0, 13.0],
        "units": [
            "% missing health",
            "% missing health",
            "% missing health",
            "% missing health",
            "% missing health",
        ],
        "hash": "a89abd1a84627e06",
    },
    {
        "atom_id": "timing.cooldown",
        "behavior": "timing",
        "source": "Gangplank.W[0].cooldown",
        "name": "Remove Scurvy",
        "values": [22.0, 20.0, 18.0, 16.0, 14.0],
        "units": ["s", "s", "s", "s", "s"],
        "hash": "3cab27d68bef338c",
    },
]

#: Atom records from ``data/atoms/items.json`` (hashes independently
#: recomputed; the atomizer's keyword artifacts ``control.blind`` and
#: ``vision.sight`` on Mikael's are documented NOT consumable).
MIKAELS_HEAL_ATOM: dict[str, Any] = {
    "atom_id": "heal.flat",
    "behavior": "heal",
    "source": "Mikael's Blessing.actives[0].branches[0]",
    "name": "Purify",
    "values": [100.0, 250.0],
    "units": ["flat", "flat"],
    "evidence": ["active:Purify@kw:heal"],
    "hash": "cf9fe930ebd40602",
}
#: Rule 5: Quicksilver's percent and window live in ITEM_EFFECTS, and both
#: the atom receipt's ``values`` and the declaration below are that one read
#: — read at import, like Purify's pair, because the entry is code-owned and
#: refresh-inert (D-47).
MERCURIAL_MOVEMENT = mercurial_quicksilver_movement()
MERCURIAL_MOVEMENT_ATOM: dict[str, Any] = MERCURIAL_MOVEMENT["atom"]


def _cache_receipt(
    item: str,
    item_id: int,
    revision_id: int,
    wording: str,
) -> dict[str, Any]:
    """One cache receipt reproducing the sourced branch wording."""
    return {
        "label": f"Local League Wiki cache — {item} (data/items.json id {item_id})",
        "url": "https://wiki.leagueoflegends.com",
        "revision_id": revision_id,
        "revision_timestamp": "cached data (patch cache)",
        "cache_key": f"data/items.json[{item_id}].active[0].branches[0]",
        "wording": wording,
    }


#: The sourced declarations — one per item, read-only at runtime.  Every
#: categorical rule and atom hash is receipted; the matrix pins the exact
#: field sets (R4/R5/R20).
ITEM_CLEANSE_DECLARATIONS: dict[str, dict[str, Any]] = {
    "Mikael's Blessing": {
        "item": "Mikael's Blessing",
        "active_name": "Purify",
        "target_scope": "explicit_selected_ally",
        "excluded_control_kinds": (
            "airborne",
            "blind",
            "disarm",
            "nearsight",
            "suppression",
        ),
        "cooldown_seconds": None,
        "cooldown_source_gap": True,
        "heal": {
            # Rule 5: Purify's two numbers live in ALLY_ITEM_EFFECTS and are
            # read through the typed accessor, which raises naming the item
            # and the key if the registry ever loses one — never a literal
            # here that could outlive the source.  Read at import because
            # that registry is hand-authored and refresh-inert (D-47), so
            # there is no generation for a re-read to catch.
            "amount_min": ally_item_effect_value("Mikael's Blessing", "heal_min"),
            "amount_max": ally_item_effect_value("Mikael's Blessing", "heal_max"),
            "scaling": "target_level",
            "source": "Mikael's Blessing — Purify",
            "source_atoms": [dict(MIKAELS_HEAL_ATOM)],
        },
        "movement": None,
        "source_receipts": [
            _cache_receipt("Mikael's Blessing", 3222, 3984364, MIKAELS_WORDING)
        ],
        "source_atoms": [dict(MIKAELS_HEAL_ATOM)],
    },
    "Quicksilver Sash": {
        "item": "Quicksilver Sash",
        "active_name": "Quicksilver",
        "target_scope": "self",
        "excluded_control_kinds": ("airborne",),
        "cooldown_seconds": None,
        "cooldown_source_gap": True,
        "heal": None,
        "movement": None,
        "source_receipts": [
            _cache_receipt("Quicksilver Sash", 3140, 3729899, QUICKSILVER_WORDING)
        ],
        "source_atoms": [],
    },
    "Mercurial Scimitar": {
        "item": "Mercurial Scimitar",
        "active_name": "Quicksilver",
        "target_scope": "self",
        "excluded_control_kinds": ("airborne",),
        "cooldown_seconds": None,
        "cooldown_source_gap": True,
        "heal": None,
        "movement": {
            "amount": MERCURIAL_MOVEMENT["move_speed_percent"],
            "duration": MERCURIAL_MOVEMENT["duration_seconds"],
            "source": "Mercurial Scimitar — Quicksilver",
            "source_atoms": [dict(MERCURIAL_MOVEMENT_ATOM)],
        },
        "source_receipts": [
            _cache_receipt("Mercurial Scimitar", 3139, 3984461, MERCURIAL_WORDING)
        ],
        "source_atoms": [dict(MERCURIAL_MOVEMENT_ATOM)],
    },
}


#: P2 Slice 5 — the champion-cast cleanse sources (Gangplank W Remove
#:  Scurvy).  The packet's source_key is the declaration key; the resolver
#:  also accepts the active name and the display source.  Kept SEPARATE
#:  from the item tables so the Slice 4 item contract (three sourced
#:  items) is untouched.
CHAMPION_CLEANSE_SOURCES: dict[str, str] = {
    "Gangplank W": "Gangplank W",
    "Gangplank W — Remove Scurvy": "Gangplank W",
    "Remove Scurvy": "Gangplank W",
    # P2 Slice 6: the EMPOWERED W self-cast (Rengar Battle Roar).  The
    #  packet's source_key is the declaration key; the resolver also
    #  accepts the active name and the display source.
    "Rengar W": "Rengar W",
    "Rengar W — Battle Roar": "Rengar W",
    "Battle Roar": "Rengar W",
    # P2 Slice 7: the R self+all-teammates cast (Milio Breath of Life).
    "Milio R": "Milio R",
    "Milio R — Breath of Life": "Milio R",
    "Breath of Life": "Milio R",
    # P2 Slice 8: the passive immunity declaration (Dr. Mundo Goes Where
    #  He Pleases) — the resist kernel reads the declaration receipts.
    "Dr. Mundo P": "Dr. Mundo P",
    "Dr. Mundo P — Goes Where He Pleases": "Dr. Mundo P",
    "Goes Where He Pleases": "Dr. Mundo P",
    # P2 Slice 9: the R cast (Olaf Ragnarok) — the cast-time cleanse +
    #  the 3s immunity window + the stat receipts ride the R packet.
    "Olaf R": "Olaf R",
    "Olaf R — Ragnarok": "Olaf R",
    "Ragnarok": "Olaf R",
}


#: P2 Slice 5 — the champion-cast cleanse declaration.  The heal is a
#:  SEPARATE authored effect (the E1 self-heal rule in healing.py prices
#:  flat + 90% AP + 13% missing health live); the declaration's heal is
#:  None so the kernel never mints a second one.  Castability: game
#:  canCastWhileDisabled true / cannotBeSuppressed true (the QSS/Mercurial
#:  flag pair).  Excluded: the displacement family — the wiki notes that
#:  the stun under airborne is removable but the displacement needs a
#:  blink/dash (never modeled as an interval split).
#: P2 Slice 6 — the EMPOWERED-W cleanse declaration (Rengar Battle Roar).
#:  The cleanse condition is the Ferocity-Bonus branch ONLY (the wiki
#:  effect-2 wording "Rengar cleanses himself from all crowd control"; the
#:  game file RengarWEmp uniquely carries canCastWhileDisabled true /
#:  cannotBeSuppressed true — the base RengarW record carries neither
#:  flag).  NO user toggle and NO base-W cleanse.  The E8a grey-health
#:  heal is the SEPARATE authored heal (heal None — the kernel never
#:  mints a second).  Excluded: NONE — the wording is "ALL crowd
#:  control" (no displacement carve-out, unlike Gangplank's).
RENGAR_EMPOWERED_W_CLEANSE_DECLARATION: dict[str, Any] = {
    "item": "Rengar W",
    "active_name": "Battle Roar",
    "target_scope": "self",
    "excluded_control_kinds": (),
    "cooldown_seconds": None,
    "cooldown_source_gap": True,
    "heal": None,
    "movement": None,
    "source_receipts": [
        {
            "label": "Local League Wiki cache — Rengar W template + parent entry",
            "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Rengar/W",
            "revision_id": 2864299,
            "revision_timestamp": "2019-11-03T20:10:49Z",
            "parent_revision_id": 3993826,
            "parent_revision_timestamp": "2026-02-24T04:02:53Z",
            "cache_key": "data/champions.json['Rengar'].abilities.W[0]",
            "wording": "Ferocity Bonus: Battle Roar's damage is modified "
            "to deal 50 : 240 (based on level) (+ 80% AP) magic damage. "
            "Rengar cleanses himself from all crowd control.",
            "game_file": "data/bin/characters/rengar.bin.json "
            "(RengarWEmp canCastWhileDisabled true / cannotBeSuppressed "
            "true — the QSS/Mercurial flag pair; the base RengarW record "
            "carries neither; DataValues W rows empty in the local dump — "
            "the W numbers come from the wiki rows)",
        }
    ],
    "source_atoms": [],
}


CHAMPION_CLEANSE_DECLARATIONS: dict[str, dict[str, Any]] = {
    "Gangplank W": {
        "item": "Gangplank W",
        "active_name": "Remove Scurvy",
        "target_scope": "self",
        "excluded_control_kinds": ("airborne", "knockback", "knockup"),
        "cooldown_seconds": None,
        "cooldown_source_gap": True,
        "heal": None,
        "movement": None,
        "source_receipts": [
            {
                "label": "Local League Wiki cache — Gangplank W template + parent entry",
                "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Gangplank/W",
                "revision_id": 2864237,
                "revision_timestamp": "2019-11-03T20:09:46Z",
                "parent_revision_id": 4002542,
                "parent_revision_timestamp": "2026-03-26T01:37:40Z",
                "cache_key": "data/champions.json['Gangplank'].abilities.W[0]",
                "game_file": "data/bin/characters/gangplank.bin.json "
                "(BaseHeal [20..170], PercentHeal 13, StatByCoefficient 0.9 "
                "AP, canCastWhileDisabled true, cannotBeSuppressed true, "
                "mCastTime 0.25, cooldownTime [24..14], mana [60..110])",
                "wording": REMOVE_SCURVY_WORDING,
            }
        ],
        "source_atoms": [dict(atom) for atom in REMOVE_SCURVY_HEAL_ATOMS],
    },
    "Rengar W": dict(RENGAR_EMPOWERED_W_CLEANSE_DECLARATION),
    # P2 Slice 7 — Milio R Breath of Life (the self+all-teammates cast).
    #  Scope: Milio AND every nearby allied champion (the E8d heal
    #  fan-out roster — "cleansing himself and nearby allied champions").
    #  Excluded: the displacement family — the wording is "non-airborne
    #  crowd control".  Heal: None — the E8d rule owns the R heal (the
    #  cleanse rides the heal packet as a Mikael's-style marker).  The
    #  tenacity (65% for 3s) is utility state.  Castability: the R CANNOT
    #  be used while the caster is crowd-controlled (wiki effects[1]
    #  "cast-inhibiting"; the game file MilioR carries NEITHER
    #  canCastWhileDisabled nor cannotBeSuppressed — the Mikael's-gated
    #  pattern, NOT the QSS/Mercurial/RengarWEmp carve-out).  Cooldown
    #  160/145/130 receipted, never enforced (the engine's single-cast
    #  rule is the operative limit).
    # P2 Slice 8 — Dr. Mundo P Goes Where He Pleases (the passive
    #  immunity declaration).  The resist kernel (survival/transitions
    #  _apply_mundo_p_resist) reads the sourced values from the same
    #  receipts; the declaration is the provenance home.  Scope self;
    #  NO exclusions (the immunity resists every hostile immobilizing
    #  kind); cooldown 60 -> 15 by level (wiki row; the game step
    #  function agrees at levels 1 and 18 — flagged) receipted, never
    #  enforced; heal None (the pickup heal is a named-unsupported
    #  timing — the canister drop heals nothing).
    # P2 Slice 9 — Olaf R Ragnarok (the cast-time cleanse + the 3s
    #  immunity window).  Scope self; excluded the displacement family
    #  (the notes: the stun under airborne is removed but the forced
    #  displacement needs a blink/dash — the GP precedent); cooldown
    #  100/90/80 receipted, never enforced (the engine's single-cast
    #  rule is the operative limit); heal None (the R heals nothing —
    #  the bonus-stat receipts are separate authored effects); the
    #  castability carve-out is the game flag pair (canCastWhileDisabled
    #  + cannotBeSuppressed — R fires while CC'd, not under
    #  suppression/stasis).
    "Olaf R": {
        "item": "Olaf R",
        "active_name": "Ragnarok",
        "target_scope": "self",
        "excluded_control_kinds": ("airborne", "knockback", "knockup"),
        "cooldown_seconds": [100.0, 90.0, 80.0],
        "cooldown_source_gap": False,
        "heal": None,
        "movement": None,
        "source_receipts": [
            {
                "label": "Local League Wiki cache — Olaf R template + parent entry",
                "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Olaf/R",
                "revision_id": 2864579,
                "revision_timestamp": "2019-11-03T20:16:31Z",
                "parent_revision_id": 3952811,
                "parent_revision_timestamp": "2025-09-10T02:36:32Z",
                "cache_key": "data/champions.json['Olaf'].abilities.R[0]",
                "wording": "Active: Olaf becomes enraged for 3 seconds, "
                "cleansing himself of all crowd control and becoming "
                "immune to them, as well as gaining bonus attack damage "
                "(10/20/30 + 25% attack damage — the 25% scaling "
                "amplifies the flat bonus as well) and 10% increased "
                "size.  Ragnarok removes the underlying stun from "
                "airborne effects, but not the forced displacement, "
                "which requires him to use a blink or dash ability to "
                "override it.  Ragnarok's duration is increased by and "
                "up to 2.5 seconds for each basic attack on-hit or cast "
                "of Reckless Swing against an enemy champion.",
                "game_file": "data/bin/characters/olaf.bin.json "
                "(OlafRagnarok: Resists 10/15/20, Duration 3.0, FlatAD "
                "10/20/30, PercentTotalADAmp 0.25, HasteDuration 1.0, "
                "Haste 20/45/70 %, DurationExtension 2.5, cooldownTime "
                "100/90/80, mana 100 — canCastWhileDisabled true / "
                "cannotBeSuppressed true, Trait_CCImmune)",
            }
        ],
        "source_atoms": [
            {
                "atom_id": "ability.bonus _resistances",
                "behavior": "ability",
                "source": "Olaf.R[0].effects[0].leveling[0].modifiers[0]",
                "name": "Bonus Resistances",
                "values": [10.0, 15.0, 20.0],
                "units": ["", "", ""],
                "hash": "54fe668651879d7d",
            },
            {
                "atom_id": "timing.cooldown",
                "behavior": "timing",
                "source": "Olaf.R[0].cooldown",
                "name": "Ragnarok",
                "values": [100.0, 90.0, 80.0],
                "units": ["s", "s", "s"],
                "hash": "6f8e85af3ce9f5ef",
            },
        ],
    },
    "Dr. Mundo P": {
        "item": "Dr. Mundo P",
        "active_name": "Goes Where He Pleases",
        "target_scope": "self",
        "excluded_control_kinds": (),
        "cooldown_seconds": [
            60.0,
            57.35294117647059,
            54.705882352941174,
            52.05882352941177,
            49.411764705882355,
            46.76470588235294,
            44.11764705882353,
            41.470588235294116,
            38.82352941176471,
            36.17647058823529,
            33.529411764705884,
            30.88235294117647,
            28.235294117647058,
            25.588235294117645,
            22.94117647058824,
            20.294117647058826,
            17.647058823529413,
            15.0,
        ],
        "cooldown_source_gap": False,
        "heal": None,
        "movement": None,
        "source_receipts": [
            {
                "label": "Local League Wiki cache — Dr. Mundo P entry",
                "url": "https://wiki.leagueoflegends.com/en-us/Dr._Mundo",
                "revision_id": 4007950,
                "revision_timestamp": "2026-04-12T23:57:05Z",
                "cache_key": "data/champions.json['DrMundo'].abilities.P[0]",
                "wording": "Periodically, Dr. Mundo gains immunity to the "
                "next hostile immobilizing effect to affect him. Upon "
                "resisting one, Dr. Mundo pays a health cost equal to 4% "
                "of his current health and propels a canister that lands "
                "525 units in the general direction of the immobilization "
                "source, remaining on the ground for 7 seconds.  Dr. "
                "Mundo can move near the canister to consume it, healing "
                "himself for 4% of his maximum health and reducing the "
                "cooldown of Goes Where He Pleases by 15 seconds. Enemy "
                "champions can move near it to destroy it.",
                "game_file": "data/bin/characters/drmundo.bin.json "
                "(DrMundoP: CurrentHealthLoss 0.04, MaxHealthGain 0.04, "
                "PassiveCooldownRefund 15.0, CannisterGroundDuration 7.0, "
                "CannisterDistanceAway 525.0, CannisterPickupRadius 115.0, "
                "CannisterMaxAngle 70.0; PassiveCooldown 60 with -9 "
                "breakpoints at levels 3/6/9/12/15/21 — the trigger "
                "scope + enemy-destroy + respawn reset are wiki-prose "
                "only)",
            }
        ],
        "source_atoms": [
            {
                "atom_id": "timing.cooldown",
                "behavior": "timing",
                "source": "DrMundo.P[0].cooldown",
                "name": "Goes Where He Pleases",
                "values": [
                    60.0,
                    57.35294117647059,
                    54.705882352941174,
                    52.05882352941177,
                    49.411764705882355,
                    46.76470588235294,
                    44.11764705882353,
                    41.470588235294116,
                    38.82352941176471,
                    36.17647058823529,
                    33.529411764705884,
                    30.88235294117647,
                    28.235294117647058,
                    25.588235294117645,
                    22.94117647058824,
                    20.294117647058826,
                    17.647058823529413,
                    15.0,
                ],
                "units": [
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                    "s",
                ],
                "hash": "8953fa74569fe1ab",
            },
        ],
    },
    "Milio R": {
        "item": "Milio R",
        "active_name": "Breath of Life",
        "target_scope": "self_and_all_teammates",
        "excluded_control_kinds": ("airborne", "knockback", "knockup"),
        "cooldown_seconds": [160.0, 145.0, 130.0],
        "cooldown_source_gap": False,
        "heal": None,
        "movement": None,
        "source_receipts": [
            {
                "label": "Local League Wiki cache — Milio R template + parent entry",
                "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Milio/R",
                "revision_id": 3535281,
                "revision_timestamp": "2023-03-06T17:24:55Z",
                "parent_revision_id": 3892686,
                "parent_revision_timestamp": "2025-05-02T11:29:04Z",
                "cache_key": "data/champions.json['Milio'].abilities.R[0]",
                "wording": "Active: Milio explodes in soothing flames, "
                "healing and cleansing himself and nearby allied champions "
                "of non-airborne crowd control, and granting them 65% "
                "tenacity for 3 seconds.  Milio cannot cast his other "
                "abilities for 0.75 seconds after Breath of Life's "
                "activation. Breath of Life cannot be used while affected "
                "by cast-inhibiting crowd control.",
                "game_file": "data/bin/characters/milio.bin.json (MilioR: "
                "HealBase 150/250/350 + 0.5 AP, TenacityAmount 0.65 / "
                "TenacityDuration 3.0, cooldownTime 160/145/130, mana 100, "
                "SelfAoe, castRange 700 — NO canCastWhileDisabled / "
                "cannotBeSuppressed; the cast-inhibiting gate is the "
                "Mikael's pattern)",
            }
        ],
        "source_atoms": [
            {
                "atom_id": "ability.heal.modifier_0",
                "behavior": "ability",
                "source": "Milio.R[0].effects[0].leveling[0].modifiers[0]",
                "name": "Heal",
                "values": [150.0, 250.0, 350.0],
                "units": ["", "", ""],
                "hash": "838c3aab52b4e9c6",
            },
            {
                "atom_id": "ability.heal.modifier_1",
                "behavior": "ability",
                "source": "Milio.R[0].effects[0].leveling[0].modifiers[1]",
                "name": "Heal",
                "values": [50.0, 50.0, 50.0],
                "units": ["% AP", "% AP", "% AP"],
                "hash": "f01d47304a7cab5a",
            },
            {
                "atom_id": "timing.cooldown",
                "behavior": "timing",
                "source": "Milio.R[0].cooldown",
                "name": "Breath of Life",
                "values": [160.0, 145.0, 130.0],
                "units": ["s", "s", "s"],
                "hash": "5c61af44e7eb944d",
            },
        ],
    },
}


def resolve_cleanse_item(source_or_item: str) -> str:
    """Resolve one packet source / item name to a declared cleanse.

    Fails closed (KeyError naming the source) when the source is not a
    declared cleanse active — a packet that cannot be attributed to a
    sourced declaration must never guess.
    """
    key = str(source_or_item or "").strip()
    if key in CLEANSE_ACTIVE_SOURCES:
        return CLEANSE_ACTIVE_SOURCES[key]
    if key in CHAMPION_CLEANSE_SOURCES:
        return CHAMPION_CLEANSE_SOURCES[key]
    raise KeyError(
        f"cleanse active source {key!r} is not a declared item — "
        "Mikael's Blessing / Quicksilver Sash / Mercurial Scimitar / "
        "Gangplank W only"
    )


def item_declaration(item: str) -> dict[str, Any]:
    """Return one item's sourced cleanse declaration, fail-closed."""
    if item in ITEM_CLEANSE_DECLARATIONS:
        return ITEM_CLEANSE_DECLARATIONS[item]
    if item in CHAMPION_CLEANSE_DECLARATIONS:
        return CHAMPION_CLEANSE_DECLARATIONS[item]
    raise KeyError(
        f"no cleanse declaration for item {item!r} — "
        "Mikael's Blessing / Quicksilver Sash / Mercurial Scimitar / "
        "Gangplank W only"
    )


# ---------------------------------------------------------------------------
# Interval primitives
# ---------------------------------------------------------------------------


def _interval_bounds(interval: Mapping[str, Any]) -> tuple[float, float]:
    start = float(interval.get("start", 0.0) or 0.0)
    end = float(interval.get("end", 0.0) or 0.0)
    return start, end


def _interval_kind(interval: Mapping[str, Any]) -> str:
    return str(interval.get("kind", "") or "").strip().lower()


def interval_active(interval: Mapping[str, Any], at: float) -> bool:
    """Whether one interval is ACTIVE at a time (start inclusive, end
    exclusive — the walk's DefenseWindow convention)."""
    start, end = _interval_bounds(interval)
    return start <= at + _EPS and end > at + _EPS


def merged_spans(
    spans: Iterable[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    """Sort ``[start, end)`` spans and fuse any that touch or overlap.

    The ONE interval fold: the union length below is its total length, and
    the engine's empowered-burst blocks are the same spans read as blocks.
    """
    merged: list[list[float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return tuple((start, end) for start, end in merged)


def merged_interval_duration(intervals: Sequence[Mapping[str, Any]]) -> float:
    """The union length of authored inactive intervals, which both the
    truncation below and the survival row's published downtime call.

    Union rather than sum: two controls overlapping in time cost the actor one
    window of downtime and not two, so a total that added them would publish
    more downtime than the fight is long.
    """
    # The overwhelmingly common answer, taken without allocating: almost no
    # participant of almost any fight is ever inactive, and the survival row
    # runs this once per participant per walk on the optimizer's hot path.
    if not intervals:
        return 0.0
    spans = merged_spans(
        bounds
        for bounds in (_interval_bounds(interval) for interval in intervals)
        if bounds[1] > bounds[0]
    )
    # A window opening before the fight clock is measured from zero, and the
    # blocks are added one at a time: ``sum()`` compensates and this walk's
    # published downtime is the uncompensated total.
    total = 0.0
    for start, end in spans:
        if end > 0.0:
            total += end - max(0.0, start)
    return max(0.0, total)


def movement_entry(declaration: Mapping[str, Any]) -> dict[str, Any] | None:
    """The movement utility entry of a cleanse declaration (Mercurial's 50%
    bonus total movement speed for 2 s, own atoms) — the ONE builder both
    the authoring layer and the walk use, so the receipt shape cannot
    drift."""
    movement = declaration.get("movement")
    if movement is None:
        return None
    return {
        "amount": max(0.0, float(movement.get("amount", 0.0) or 0.0)),
        "duration": max(0.0, float(movement.get("duration", 0.0) or 0.0)),
        "source": str(movement.get("source", "") or ""),
        "source_atoms": [dict(atom) for atom in movement.get("source_atoms", ())],
    }


def truncate_intervals(
    intervals: Iterable[Mapping[str, Any]],
    activation_time: float,
    eligible_kinds: Iterable[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One pure interval-truncation operation.

    Returns ``(kept, removed)`` for the intervals passed at the activation
    instant:

    - an interval whose kind is outside :data:`KNOWN_CONTROL_KINDS` is
      NEVER truncated (unknown kinds fail closed — R15);
    - an interval whose kind is not in ``eligible_kinds`` is untouched
      (rejected by the caller, never truncated);
    - an interval that ended at/before activation (historical) is kept;
    - an interval ACTIVE at activation (start < time < end) is clamped:
      ``[start, time)`` kept, ``[time, end)`` removed;
    - an interval STARTING at activation (``start == time`` — the
      same-time control packet, which the walk's total order applies
      before the cleanse) is removed entirely;
    - an interval starting after activation (future control) is untouched
      (a cleanse creates NO immunity).

    Removed entries are the input dicts with ``start``/``end`` adjusted
    (the tail or the whole interval), so receipts can attribute them.
    """
    activation = float(activation_time)
    eligible = frozenset(str(kind) for kind in eligible_kinds)
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for interval in intervals:
        row = dict(interval)
        kind = _interval_kind(row)
        if kind not in KNOWN_CONTROL_KINDS or kind not in eligible:
            kept.append(row)
            continue
        start, end = _interval_bounds(row)
        if end <= activation + _EPS:
            # Historical downtime: remains counted.
            kept.append(row)
            continue
        if start >= activation - _EPS:
            # Same-timestamp control (already applied by the walk's total
            # order): removed entirely.  A control landing later is not in
            # this list yet and stays untouched.
            removed.append({**row, "start": start, "end": end})
            continue
        # Active interval: ends at activation; the future tail is removed.
        kept.append({**row, "end": activation})
        removed.append({**row, "start": activation, "end": end})
    return kept, removed


# ---------------------------------------------------------------------------
# Cleanse eligibility
# ---------------------------------------------------------------------------


#: Kinds a cleanse cannot be cast under (self-scope castability rule).
#: Sourced from the wiki Cleanse atom + client binary flags: QSS and
#: Mercurial carry canCastWhileDisabled and cannotBeSuppressed; Mikael's
#: 3222Active carries neither.  The atom's own wording — "castable while
#: disabled, but not under suppression/stasis" — names both, and the wiki
#: Stasis entry agrees: stasis "will prevent the activation of abilities
#: that would usually remove crowd control effects".
CAST_BLOCKING_CONTROL_KINDS: frozenset[str] = frozenset({"stasis", "suppression"})

#: Kinds no cleanse removes, whatever its item declares — the wiki Stasis
#: entry: "Cannot be removed by any means (except through death)".  This is
#: a property of the kind, not of the item, so it lives here once instead of
#: in every declaration's carve-out tuple.
#: https://wiki.leagueoflegends.com/en-us/Stasis
NEVER_CLEANSABLE_CONTROL_KINDS: frozenset[str] = frozenset({"stasis"})

#: Words an item tooltip carves out that no champion module can author, so
#: they never match an interval.  They stay in the declarations because the
#: declaration IS the sourced transcription of the tooltip; naming them here
#: is what keeps them from reading as a drifted kind
#: (tests/test_cc_kind_vocabulary.py).
TOOLTIP_ONLY_CONTROL_KINDS: frozenset[str] = frozenset({"disarm", "nearsight"})


def resolve_excluded_kinds(declared: Iterable[str]) -> frozenset[str]:
    """The kinds a declaration's carve-out protects — the ONE reader of
    ``excluded_control_kinds``, so the umbrella cannot resolve two ways.
    """
    kinds = frozenset(str(kind) for kind in declared)
    if kinds & DISPLACEMENT_CC_KINDS:
        kinds |= DISPLACEMENT_CC_KINDS
    return kinds | NEVER_CLEANSABLE_CONTROL_KINDS


def _control_entries(interval: Mapping[str, Any]) -> dict[str, Any]:
    """One receipt-shaped control entry from an interval row."""
    start, end = _interval_bounds(interval)
    return {
        "control_kind": _interval_kind(interval),
        "source": str(interval.get("source", "") or ""),
        "start": round(start, 9),
        "end": round(end, 9),
    }


@dataclass(frozen=True, slots=True)
class CleanseEligibility:
    """One item's cleanse eligibility contract.

    ``declaration`` is the sourced item declaration
    (:data:`ITEM_CLEANSE_DECLARATIONS`); ``source`` is the provenance
    record the walk attaches.  ``decide`` is a pure function of the
    activation and the recipient's ACTIVE control intervals at activation
    (the walk passes them; kernel rows author them) — same-time
    determinism comes from the walk's total order, which the kernel
    mirrors in :func:`delivery_eligibility.stable_event_key`.
    """

    declaration: dict[str, Any]
    source: SourceReceipt | None = None

    # -- helpers -----------------------------------------------------------

    def _item(self) -> str:
        return str(self.declaration.get("item", ""))

    def _excluded(self) -> frozenset[str]:
        return resolve_excluded_kinds(
            self.declaration.get("excluded_control_kinds", ())
        )

    def _scope(self) -> str:
        return str(self.declaration.get("target_scope", ""))

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe eligibility declaration receipt."""
        return {
            "item": self._item(),
            "active_name": self.declaration.get("active_name"),
            "target_scope": self._scope(),
            "excluded_control_kinds": sorted(self._excluded()),
            "cooldown_seconds": self.declaration.get("cooldown_seconds"),
            "cooldown_source_gap": bool(self.declaration.get("cooldown_source_gap")),
            "source": self.source.public() if self.source is not None else None,
        }

    # -- decision ----------------------------------------------------------

    def decide(
        self,
        action: CleanseActivation,
        *,
        holder: Mapping[str, Any] | None = None,
    ) -> CleanseDecision:
        """Decide one cleanse activation (deterministic, receipted).

        ``holder`` is the item holder's live use state (the walk resolves
        it; kernel rows may omit it — a fresh one-use state is assumed).
        The action reads: ``time``, ``source_key``, ``sequence``,
        ``event_id``, ``target`` (recipient participant id), ``holder``
        (owner participant id; defaults to the target for self items) and
        ``active_controls`` (the recipient's control intervals at
        activation).
        """
        activation = float(getattr(action, "time", 0.0) or 0.0)
        event_key = stable_event_key(action)
        target = str(getattr(action, "target", "") or "")
        holder_id = str(getattr(action, "holder", "") or "") or target
        intervals = [
            dict(interval)
            for interval in (getattr(action, "active_controls", None) or ())
        ]
        holder_state = dict(holder or {})
        raw_uses = holder_state.get("uses_remaining", 1)
        uses_remaining = int(raw_uses) if raw_uses is not None else 1
        item_held = holder_state.get("item_held", True)
        if not isinstance(item_held, bool):
            item_held = True
        excluded = self._excluded()
        scope = self._scope()

        # -- activation-level gates (denials never consume the use) --------
        if scope == "self":
            if target != holder_id:
                return self._decision(
                    eligible=False,
                    reason="target_not_selected",
                    action=action,
                    intervals=intervals,
                    activation=activation,
                    use_consumed=False,
                    event_key=event_key,
                )
        elif scope == "self_and_all_teammates":
            # P2 Slice 7 (Milio R): the walk authors one packet per
            # recipient (the E8d fan-out roster — Milio + every selected
            # teammate), so any authored target is valid; an empty target
            # fails closed (identity missing).  The caster-CC gate is the
            # WALK's attacker gate (the heal+marker rides it — the whole
            # cast is blocked while the caster is crowd-controlled); each
            # recipient's OWN control intervals decide here.
            if not target:
                return self._decision(
                    eligible=False,
                    reason="target_not_selected",
                    action=action,
                    intervals=intervals,
                    activation=activation,
                    use_consumed=False,
                    event_key=event_key,
                )
        elif scope == "explicit_selected_ally" and (not target or target == holder_id):
            return self._decision(
                eligible=False,
                reason="target_not_selected",
                action=action,
                intervals=intervals,
                activation=activation,
                use_consumed=False,
                event_key=event_key,
            )
        if not item_held:
            return self._decision(
                eligible=False,
                reason="not_armed",
                action=action,
                intervals=intervals,
                activation=activation,
                use_consumed=False,
                event_key=event_key,
            )
        if uses_remaining <= 0:
            return self._decision(
                eligible=False,
                reason="use_spent",
                action=action,
                intervals=intervals,
                activation=activation,
                use_consumed=False,
                event_key=event_key,
            )

        # -- interval analysis (fail closed on unknown kinds) --------------
        unknown = [
            interval
            for interval in intervals
            if _interval_kind(interval) not in KNOWN_CONTROL_KINDS
        ]
        if unknown:
            return self._decision(
                eligible=False,
                reason="unknown_control",
                action=action,
                intervals=intervals,
                activation=activation,
                use_consumed=False,
                event_key=event_key,
            )

        active = [i for i in intervals if interval_active(i, activation)]

        # Self-scope castability: a QSS/Mercurial self-cast cannot be
        # performed while the caster is suppressed or in stasis (cleanse
        # atom + binary cannotBeSuppressed).  The denial keeps the use.
        if scope == "self":
            blocked = [
                i for i in active if _interval_kind(i) in CAST_BLOCKING_CONTROL_KINDS
            ]
            if blocked:
                return self._decision(
                    eligible=False,
                    reason="caster_control_blocks_cleanse",
                    action=action,
                    intervals=intervals,
                    activation=activation,
                    use_consumed=False,
                    event_key=event_key,
                )

        eligible_active = [i for i in active if _interval_kind(i) not in excluded]
        if not eligible_active:
            # Nothing removable: the activation still happens (the use is
            # consumed) but the receipt names the rule.  ``use_spent`` is
            # ONLY ever decided from the holder's live use state above —
            # a list of historical intervals (nothing active) is
            # ``control_not_active``, never a spent-use guess.
            if not active:
                reason = "control_not_active"
                use_consumed = True
            else:
                reason = "excluded_control_kind"
                use_consumed = True
            return self._decision(
                eligible=False,
                reason=reason,
                action=action,
                intervals=intervals,
                activation=activation,
                use_consumed=use_consumed,
                event_key=event_key,
            )

        eligible_kinds = frozenset(KNOWN_CONTROL_KINDS) - excluded
        kept, removed = truncate_intervals(intervals, activation, eligible_kinds)
        return self._decision(
            eligible=True,
            reason="",
            action=action,
            intervals=intervals,
            activation=activation,
            use_consumed=True,
            event_key=event_key,
            _kept=kept,
            _removed=removed,
        )

    def _decision(
        self,
        *,
        eligible: bool,
        reason: str,
        action: CleanseActivation,
        intervals: list[dict[str, Any]],
        activation: float,
        use_consumed: bool,
        event_key: str,
        _kept: list[dict[str, Any]] | None = None,
        _removed: list[dict[str, Any]] | None = None,
    ) -> CleanseDecision:
        """Build the decision receipt from the analysis outcome.

        Only an eligible outcome truncates: every denial
        (control_not_active / excluded_control_kind / unknown_control /
        target_not_selected / not_armed / use_spent /
        caster_control_blocks_cleanse) leaves the interval lists untouched
        — ``removed_controls`` is empty and ``intervals_after`` is the full
        input list.
        """
        if _kept is None:
            if eligible:
                eligible_kinds = frozenset(KNOWN_CONTROL_KINDS) - self._excluded()
                _kept, _removed = truncate_intervals(
                    intervals, activation, eligible_kinds
                )
            else:
                _kept, _removed = list(intervals), []
        active = [i for i in intervals if interval_active(i, activation)]
        excluded = self._excluded()
        if reason == "caster_control_blocks_cleanse":
            # The cast is denied (the caster is suppressed or in stasis):
            # every active control is rejected with the castability reason —
            # nothing was removed.
            rejected = list(active)
            rejected_reason = "caster_control_blocks_cleanse"
        else:
            rejected = [
                i
                for i in active
                if _interval_kind(i) not in KNOWN_CONTROL_KINDS
                or _interval_kind(i) in excluded
            ]
            rejected_reason = (
                "excluded_control_kind"
                if reason != "unknown_control"
                else "unknown_control"
            )
        return CleanseDecision(
            eligible=eligible,
            reason=reason,
            item=self._item(),
            activation_time=float(activation),
            target=str(getattr(action, "target", "") or ""),
            event_key=event_key,
            active_controls_before=[_control_entries(i) for i in active],
            removed_controls=[
                {
                    **_control_entries(i),
                    "reason": "",
                }
                for i in _removed
            ],
            rejected_controls=[
                {**_control_entries(i), "reason": rejected_reason} for i in rejected
            ],
            intervals_after=[_control_entries(i) for i in _kept],
            downtime_before=merged_interval_duration(intervals),
            downtime_after=merged_interval_duration(_kept),
            use_consumed=use_consumed,
            declaration=self.declaration,
        )


@dataclass(frozen=True, slots=True)
class CleanseDecision:
    """One cleanse activation decision with its public receipts.

    ``eligible`` True means at least one active control was removed.
    ``eligible`` False carries a named ``reason``: ``control_not_active`` /
    ``excluded_control_kind`` / ``unknown_control`` /
    ``target_not_selected`` / ``not_armed`` / ``use_spent`` /
    ``caster_control_blocks_cleanse`` (fail-closed).  ``use_consumed`` is
    True only when the activation actually happened (the item's one use is
    spent even when there was nothing removable).
    """

    eligible: bool
    reason: str = ""
    item: str = ""
    activation_time: float = 0.0
    target: str = ""
    event_key: str = ""
    active_controls_before: list[dict[str, Any]] = field(default_factory=list)
    removed_controls: list[dict[str, Any]] = field(default_factory=list)
    rejected_controls: list[dict[str, Any]] = field(default_factory=list)
    intervals_after: list[dict[str, Any]] = field(default_factory=list)
    downtime_before: float = 0.0
    downtime_after: float = 0.0
    use_consumed: bool = False
    declaration: dict[str, Any] = field(default_factory=dict)

    def public_receipt(self) -> dict[str, Any]:
        """JSON-safe decision receipt (the matrix's exact field set)."""
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "item": self.item,
            "activation_time": round(self.activation_time, 6),
            "target": self.target,
            "active_controls_before": [
                dict(entry) for entry in self.active_controls_before
            ],
            "removed_controls": [dict(entry) for entry in self.removed_controls],
            "rejected_controls": [dict(entry) for entry in self.rejected_controls],
            "intervals_after": [dict(entry) for entry in self.intervals_after],
            "downtime_before": round(self.downtime_before, 6),
            "downtime_after": round(self.downtime_after, 6),
            "use_consumed": self.use_consumed,
        }


__all__ = [
    "CAST_BLOCKING_CONTROL_KINDS",
    "CLEANSE_ACTIVE_SOURCES",
    "ITEM_CLEANSE_DECLARATIONS",
    "MERCURIAL_MOVEMENT_ATOM",
    "MIKAELS_HEAL_ATOM",
    "CleanseDecision",
    "CleanseEligibility",
    "interval_active",
    "item_declaration",
    "merged_interval_duration",
    "merged_spans",
    "movement_entry",
    "resolve_cleanse_item",
    "resolve_excluded_kinds",
    "truncate_intervals",
]
