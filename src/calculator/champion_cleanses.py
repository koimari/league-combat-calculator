"""The sourced champion abilities that remove control."""

from __future__ import annotations

from typing import Any

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
