"""Fail-closed coverage labels for item mechanics used by BIS search.

Raw item stats are always sourced by :mod:`stats`.  This module answers the
separate question the optimiser needs: is every outgoing-damage mechanic on
this item represented by the current fight model?
"""

from typing import Any, Literal

from .item_effects import ALLY_ITEM_EFFECTS, ITEM_EFFECTS, ITEM_INPUT_OPTIONS

ItemCoverageStatus = Literal[
    "modeled_effect",
    "modeled_state",
    "stats_only",
    "blocked",
    "review_pending",
]


# These mechanics can change TDD, casts, resources, or target durability.  The
# optimiser withholds them until the named mechanic has an explicit model.
_BLOCKED_REASONS: dict[str, str] = {}

# A calculation may expose a fully sourced combat sub-effect even while the
# optimiser must withhold the item because a separate progression/economy
# state is not simulated.  Keep this list narrow and explicit: the API should
# never silently turn an incomplete combat mechanic into a partial result.
_CALCULATION_ALLOWED_BLOCKED = frozenset({"Fimbulwinter"})

# Items can have a registered damage packet while still carrying an
# unrepresented sibling passive or state transition.  Keep those items
# fail-closed until every fight-relevant child effect is covered; a name in
# ``ITEM_EFFECTS`` is not proof that the whole item is modelled.
_PARTIAL_BLOCKED_REASONS: dict[str, str] = {
    "Fimbulwinter": (
        "Everlasting's shield formula, trigger class, duration, and cooldown "
        "remain typed. The current source set does not authorize the historical "
        "20%-maximum-mana gate, its comparison operator, its mana terms, or "
        "manaless behavior. Eligible trigger events therefore emit a named "
        "mana_gate_authority_unavailable receipt, and optimizer selection is "
        "withheld. The sourced 1.8 shield branch also requires more than one "
        "enemy champion within 1200 units of the holder. The actor model has "
        "no typed spatial snapshot, so the runtime keeps the base shield and "
        "emits nearby_enemy_spatial_input_unavailable when a test-authorized "
        "mana gate reaches that branch."
    ),
}

# These items have explicit scenario state and a single shared receipt ledger
# for their timed/progression branches.  They remain separate from ordinary
# ``ITEM_EFFECTS`` so an item cannot become optimizer-eligible merely because
# one static stat conversion was parsed.
_STATEFUL_MODELED_ITEMS: dict[str, str] = {
    "Ardent Censer": (
        "Sanctify is represented by the shared participant support ledger: an "
        "explicit heal or shield trigger schedules the sourced holder/ally "
        "attack-speed and on-hit-magic packets."
    ),
    "Bandlepipes": (
        "Fanfare is represented by the shared participant support ledger: an "
        "authored immobilize or slow schedules the sourced movement and "
        "holder/ally attack-speed packets."
    ),
    "Imperial Mandate": (
        "Command is represented by the shared participant support ledger: an "
        "authored crowd-control event schedules its all-source damage amplifier "
        "for the selected target and duration."
    ),
    "Actualizer": "Mana Made Real is represented by its bounded active window, resource multiplier, and cooldown-progress receipt.",
    "Archangel's Staff": "Awe and Manaflow state are represented by the bounded bonus-mana control and transformation receipt.",
    "Manamune": "Awe and Manaflow state are represented by the bounded bonus-mana control and transformation receipt.",
    "Whispering Circlet": "Harmony, Manaflow, and Diadem state are represented by the bounded bonus-mana control and transformation receipt.",
    "Winter's Approach": "Awe, Manaflow, and Fimbulwinter transformation state are represented by the bounded bonus-mana control and transformation receipt.",
    "Hubris": "Eminence's bounded starting stacks and timed window are represented by a sourced state receipt.",
    "Axiom Arc": "Flux's sourced takedown refund fraction and trigger window are represented by a terminal-state receipt.",
    "Endless Hunger": "Famine's conversion and Feast's bounded omnivamp window are represented by a sourced state receipt.",
    "Immortal Path": "Slay stacks, above-half damage amplification, and the bounded health-state receipt are represented; below-half recovery is applied by the ordered ledger.",
    "Catalyst of Aeons": (
        "Eternity's pre-mitigation champion-damage mana restoration rides the "
        "typed mana resource ledger (10% at the hit timestamp, capped at max "
        "mana), and the mana-spent heal (25%, capped 20 per cast and 20 per "
        "second) is an automatic projection of the ledger's accepted spend "
        "receipts — no user input is required, and a fight without the typed "
        "account emits no heal with a named note."
    ),
    "Mikael's Blessing": (
        "Purify is represented by the shared participant support ledger: an "
        "explicit bounded active_seconds input emits the sourced 100-250 "
        "level-scaled heal AND the named cleanse to the SELECTED teammate; "
        "item presence alone never creates a cast or cleanse, excluded "
        "control kinds (airborne/blind/disarm/nearsight/suppression) fail "
        "closed with named reasons, and the 120s cooldown is receipted as a "
        "binary-only source gap (one use per fight, never enforced)."
    ),
    "Cryptbloom": (
        "Life From Death is represented by the shared participant support "
        "ledger: a synthesized champion takedown (first defender pair, "
        "holder alive at the kill) schedules the sourced 100 + 20% AP heal "
        "packets to the holder and selected teammates at the takedown time, "
        "with the 1.75s nova window and the 60s cooldown carried as typed "
        "receipts (cooldown never enforced — one takedown per holder per "
        "fight).  The 600-unit nova radius is NOT locally sourced and not "
        "modeled: every selected roster member is assumed hit (named "
        "boundary)."
    ),
    "Gluttonous Greaves": (
        "Slay stacks are supplied through the explicit bounded scenario "
        "control (slay_stacks 0..10) and their omnivamp (0.6% per stack, "
        "6% maximum) is priced on the fight's explicitly single-target "
        "attack/on-hit packets (the engine's conservative omnivamp scope — "
        "area/pet/copied rows are withheld with a named receipt); the 4% "
        "base omnivamp remains a parsed stat.  Takedown-driven stack "
        "admission is NOT modeled: stats resolve pre-fight, so the authored "
        "stack count is the valid champion-takedown admission (named "
        "boundary)."
    ),
    "Eclipse": (
        "Ever Rising Moon's two-hit stack gate (WindowStackGate: 2 stacks "
        "within 2s, 6s per-target cooldown) rides the state-lifecycle kernel; "
        "ordinary direct-damage and reviewed control-only cast instances use "
        "typed cast and target identities, with damage plus control from the "
        "same cast deduplicated.  The Wiki also authorizes DoT applications, "
        "but the generic event packet does not source their application "
        "timestamp, so those candidates emit a named zero-damage unavailable "
        "receipt instead of counting ticks.  "
        "The sourced melee/ranged max-health proc and the timed 160/80 + "
        "40%/20% bonus-AD self shield (2s) attach to the certified pair "
        "events in the ordered participant ledger.  A malformed proc ledger "
        "keeps its duration-scaled coarse price but is stamped with a named "
        "withheld reason and no shield (never a guessed event); the "
        "proc_Eclipse timing source stays excluded before optimizer ranking "
        "until every ability in the fight is event-certified."
    ),
    "Bastionbreaker": (
        "Shaped Charge (wiki rev 4046567): the next damaging champion-ability "
        "cast after the 20s cooldown deals 50/25 + 1.5/0.75-per-lethality "
        "TRUE damage (unmitigated), preferring authored ability-hit packets "
        "and marking cast-boundary rows coarse; basic attacks and item procs "
        "never trigger; a malformed cast ledger keeps a named zero-damage "
        "withheld row (malformed_proc_receipt) that makes the shaped_charge "
        "timing source coarse and optimizer-excluded.  Sabotage (takedown -> "
        "next basic attack vs turret/epic monster, 300/240 + 25/20 per "
        "lethality true damage over 3s) is a NAMED BOUNDARY: its targets do "
        "not exist in the 1v1 champion-only model, so it is not modeled (the "
        "full-entry audit's 'modeled' claim for it is stale)."
    ),
    "Muramana": (
        "Shock (wiki rev 4005926): one physical proc per DAMAGING ability "
        "instance (4% melee / 3% ranged max mana) plus a 1.2% max-mana "
        "on-hit on real basic attacks only — ability-carried on-hit "
        "applications (Ezreal Q) never double-count, and zero-damage casts "
        "never proc.  Authored ability-hit times are preferred; cast-boundary "
        "rows are marked coarse and optimizer-excluded (muramana_ability); a "
        "malformed or count-mismatched ledger keeps its aggregate price but "
        "is stamped with a named withheld reason.  Awe (2% max mana as bonus "
        "AD) is a separate stat conversion.  The sourced 6.5s per-target "
        "Shock lockout (wiki + binary PerCastIDLockout + typed timing atom) "
        "uses the shared lifecycle cadence keyed by exact target and cast "
        "identity. Missing identity or exact timing keeps only the existing "
        "named malformed-receipt aggregate."
    ),
    "Cull": (
        "Reap's authored minion-kill progression, completion payout, and on-hit "
        "health receipt share one explicit state/economy ledger."
    ),
    "Phage": (
        "Rage is emitted once per authored basic attack with the sourced melee or "
        "ranged movement-speed window."
    ),
    "Runic Compass": (
        "Support Quest, Shared Riches, and Ward charges are explicit state/economy "
        "and vision receipts."
    ),
    "Tear of the Goddess": (
        "Manaflow's sourced 8-second charge cadence, 3/6 bonus-mana trigger "
        "amounts, 360 bonus-mana cap, and minion-only Helping Hand boundary are "
        "explicit ordered resource and state receipts projected from the typed "
        "mana resource ledger (P3 slice 1): only proven accepted eligible hits "
        "consume charges, and each granted bonus max-mana enters the same "
        "account the cast admission reads."
    ),
    "Lost Chapter": (
        "Enlighten's sourced 20%-max-mana-over-3-seconds level-up restore is an "
        "explicit ordered resource receipt: the smallest public timing choice "
        "(level-up at N seconds) authors one deterministic restore schedule on "
        "the typed mana resource ledger; a missing choice creates no trigger. "
        "It adds no direct damage."
    ),
    "Umbral Glaive": (
        "Nightstalker's unseen-ready state gates a typed first-auto true-damage "
        "packet; Blackout is a sourced vision-dimension receipt (ward denial "
        "aura), never converted into champion damage."
    ),
    "World Atlas": (
        "Support Quest, Shared Riches, and Ward charges are explicit state/economy "
        "and vision receipts."
    ),
    "Quicksilver Sash": (
        "Quicksilver is the sourced self-cast cleanse: an explicit "
        "active_seconds input emits the cleanse packet that truncates "
        "eligible active crowd-control downtime (P2 Slice 4)."
    ),
}


# Each entry was reviewed against the cached Wiki passive/active description.
# The effect does not add outgoing TDD in the calculator's current attacker
# event model; the item's ordinary stats still flow through stats.py.
_REVIEWED_STATS_ONLY: dict[str, str] = {
    "Banshee's Veil": "Annul is defensive spell protection.",
    "Doran's Ring": (
        "Drain restores mana first and converts to a sourced health packet only "
        "when the actor cannot gain mana; Helping Hand is minion-only."
    ),
    "Doran's Helm": (
        "Helping Hand's 5 bonus physical damage is restricted to minions; the "
        "full Wiki entry has no champion-facing sustain branch."
    ),
    "Doran's Shield": (
        "Enduring Focus's sourced missing-health regeneration is replayed after "
        "incoming champion damage; Helping Hand is minion-only."
    ),
    "Scorchclaw Pup": "The jungle companion and evolved Smite buff affect monsters, not the champion target model.",
    "Gustwalker Hatchling": "The jungle companion and evolved Smite buff affect monsters, not the champion target model.",
    "Mosstomper Seedling": "The jungle companion and evolved Smite buff affect monsters, not the champion target model.",
    "Refillable Potion": "Potion charges restore the holder's health; they add no outgoing target damage.",
    "Seeker's Armguard": "Time Stop is defensive stasis.",
    "Executioner's Calling": "Grievous Wounds reduces recipient healing; it adds no direct damage.",
    "Oblivion Orb": "Grievous Wounds reduces recipient healing; it adds no direct damage.",
    "Quicksilver Sash": "Quicksilver is defensive cleanse.",
    "Verdant Barrier": "Annul is defensive spell protection.",
    "Armored Advance": "Plating and Noxian Endurance are defensive effects.",
    "Bloodthirster": "Ichorshield is a defensive shield.",
    "Celestial Opposition": "Blessing of the Mountain is defensive mitigation.",
    "Chempunk Chainsword": (
        "Hackshorn applies sourced three-second Grievous Wounds in the coupled "
        "timeline; it does not add direct damage."
    ),
    "Cosmic Drive": "Spelldance grants movement speed, not direct damage.",
    "Gunmetal Greaves": (
        "Noxian Gait's Riot-only movement branch remains explicitly out of scope "
        "because its magnitude and spacing input are not sourced; the boot's "
        "attack-speed and life-steal stats are still applied."
    ),
    "Death's Dance": "Ignore Pain and Defy change incoming damage and healing.",
    "Diadem of Songs": "Harmony and Consonance change healing, not outgoing damage.",
    "Dream Maker": "Dream Maker affects an ally, not the item holder's TDD.",
    "Echoes of Helia": "Soul Siphon stores damage only to heal an ally.",
    "Edge of Night": "Annul is defensive spell protection.",
    "Force of Nature": "Steadfast grants defensive stats and movement speed.",
    "Frozen Heart": "Winter's Caress reduces enemy attack speed.",
    "Guardian Angel": "Rebirth is a defensive revive.",
    "Immortal Shieldbow": "Lifeline is a defensive shield.",
    "Jak'Sho, The Protean": "Voidborn Resilience changes defensive resistances.",
    "Kaenic Rookern": "Magebane is a defensive magic shield.",
    "Chainlaced Crushers": "Noxian Persistence is a defensive magic shield.",
    "Knight's Vow": "Sacrifice and Pledge redirect damage and heal the holder.",
    "Locket of the Iron Solari": "Devotion shields allies.",
    "Maw of Malmortius": "Lifeline is a defensive shield.",
    "Mercurial Scimitar": "Quicksilver cleanses crowd control and grants movement speed.",
    "Mikael's Blessing": "Purify cleanses and heals an ally.",
    "Moonstone Renewer": "Starlit Grace chains healing or shielding.",
    "Morellonomicon": (
        "Grievous Wounds reduces recipient healing in the coupled timeline; it "
        "does not add direct damage."
    ),
    "Mortal Reminder": (
        "Grievous Wounds reduces recipient healing in the coupled timeline; it "
        "does not add direct damage."
    ),
    "Phantom Dancer": "Spectral Waltz grants ghosting.",
    "Plated Steelcaps": "Plating reduces incoming basic damage.",
    "Protoplasm Harness": "Lifeline is an incoming-damage defensive trigger.",
    "Randuin's Omen": "Resilience and Humility reduce incoming damage.",
    "Rylai's Crystal Scepter": "Rimefrost slows without adding direct damage.",
    "Crimson Lucidity": "Its passives grant summoner haste and movement speed.",
    "Serylda's Grudge": "Bitter Cold slows without adding direct damage.",
    "Shurelya's Battlesong": "Inspiring Speech grants movement speed.",
    "Solstice Sleigh": "Going Sledding heals and grants movement speed.",
    "Spirit Visage": "Boundless Vitality increases healing and shielding received.",
    "Boots of Swiftness": "Fleetfooted grants slow resistance.",
    "Ionian Boots of Lucidity": "Ionian Insight grants summoner spell haste.",
    "Youmuu's Ghostblade": "Haunt and Wraith Step grant movement speed.",
    "Zhonya's Hourglass": "Time Stop is defensive stasis.",
}


# Target loadouts are currently passive recipients of the selected attacker
# package.  Any equipped mechanic that changes their incoming damage, health,
# shields, or combat healing must either be represented here or stop the run.
_TARGET_MODELED_REASONS: dict[str, str] = {
    "Guardian's Horn": (
        "Undaunted blocks 15 post-mitigation damage from champion attacks and "
        "abilities, or 3.75 against damage-over-time abilities."
    ),
    "Armored Advance": (
        "Noxian Endurance grants a typed five-second physical shield after an "
        "authored champion physical-damage event; Plating reduces basic damage."
    ),
    "Chainlaced Crushers": (
        "Noxian Persistence grants a typed five-second magic shield after an "
        "authored champion magic-damage event."
    ),
    "Celestial Opposition": (
        "Blessing of the Mountain applies the sourced 35% champion-damage "
        "reduction and its two-second linger in the ordered ledger."
    ),
    "Bloodthirster": (
        "Ichorshield converts certified lifesteal excess into a persistent "
        "general shield capped by the sourced level maximum; an explicit "
        "starting state is accepted when supplied."
    ),
    "Banshee's Veil": (
        "Annul is ready at the opening and consumes every packet belonging to "
        "the first source-backed Q/W/E/R cast; auto attacks and later casts land."
    ),
    "Edge of Night": (
        "Annul is ready at the opening and consumes every packet belonging to "
        "the first source-backed Q/W/E/R cast; auto attacks and later casts land."
    ),
    "Verdant Barrier": (
        "Annul is ready at the opening and consumes every packet belonging to "
        "the first source-backed Q/W/E/R cast; auto attacks and later casts land."
    ),
    "Bramble Vest": (
        "Thorns' reactive damage and Grievous Wounds are scheduled from the "
        "attacker's modeled basic-attack events in the coupled timeline."
    ),
    "Thornmail": (
        "Thornmail's 20 magic damage plus 10% wearer bonus-armor Thorns and "
        "Grievous Wounds are scheduled from modeled basic-attack events."
    ),
    "Kaenic Rookern": "Magebane's ready maximum-health magic shield is modelled.",
    "Spirit Visage": (
        "Boundless Vitality amplifies modeled healing, shields, and regeneration "
        "received in the participant ledger."
    ),
    "Warmog's Armor": (
        "Warmog's Vitality modifies item health; combat regeneration stays "
        "inactive while the target is taking damage."
    ),
    "Doran's Shield": (
        "Enduring Focus's sourced missing-health regeneration is replayed after "
        "incoming champion damage."
    ),
    "Unending Despair": (
        "Anguish's every-four-second magic pulse and 250% post-mitigation "
        "self-heal are scheduled on the certified participant ledger for the "
        "selected enemy targets assumed within its 650-unit area."
    ),
    "Sundered Sky": (
        "Lightshield Strike's base-AD plus missing-health heal is replayed on "
        "the first attack; excess healing becomes sourced 8-second temporary "
        "health in the participant ledger."
    ),
    "Dusk and Dawn": (
        "Spellblade's self-heal is replayed from each certified empowered attack "
        "in the target actor's own participant timeline."
    ),
    "Cull": (
        "Reap's 3-health champion on-hit heal is replayed for the target actor; "
        "its minion progression and gold payout remain optimizer-only gaps."
    ),
    "Plated Steelcaps": "Plating's 10% non-true basic-damage reduction is modelled.",
    "Warden's Mail": (
        "Rock Solid's post-mitigation 15 reduction, capped at 20%, is modelled."
    ),
    "Randuin's Omen": (
        "Resilience's 30% incoming critical-strike damage reduction is modelled."
    ),
    "Frozen Heart": (
        "Winter's Caress applies its sourced 20% total attack-speed cripple to "
        "the opposing participant's authored swing schedule when the selected "
        "roster pair is assumed within the enemy-only 700-unit aura."
    ),
    "Knight's Vow": (
        "Pledge redirects 14% of eligible pre-mitigation physical or magic damage "
        "to the explicitly selected Worthy holder, and Sacrifice heals the holder "
        "from post-mitigation Worthy damage while its sourced range and health "
        "gates are active."
    ),
    "Guardian Angel": (
        "Rebirth restores 50% base health four seconds after the first lethal "
        "packet; the coupled survival ledger applies it once when the event "
        "falls inside the selected window."
    ),
    "Seeker's Armguard": (
        "Time Stop is priced only from the explicit bounded active-seconds "
        "scenario input; item presence alone never assumes stasis."
    ),
    "Zhonya's Hourglass": (
        "Time Stop is priced only from the explicit bounded active-seconds "
        "scenario input; item presence alone never assumes stasis.  The "
        "stasis window is unpriced in optimizer ranking (candidates default "
        "to zero active seconds); price it per candidate via "
        "candidate_item_options when a Time Stop matters to the build."
    ),
    "Locket of the Iron Solari": (
        "Devotion is represented by the shared participant support ledger: an "
        "explicit active_seconds input emits the sourced shield to the holder "
        "and selected teammates. Passive target calculations do not assume the "
        "active and therefore remain safe when no roster target is authored."
    ),
    "Mikael's Blessing": (
        "Purify is represented by the shared participant support ledger: an "
        "explicit active_seconds input emits the sourced cleanse/heal to the "
        "selected teammate. Passive target calculations do not invent a cast."
    ),
    "Redemption": (
        "Intervention is represented by the shared participant support ledger: "
        "an explicit active_seconds input schedules its delayed (2.5s beam) "
        "ally heal (150-350 by target level) and enemy 10%-max-health TRUE "
        "damage area packets for the selected roster, plus a vision receipt "
        "for the sourced call-down window.  The 5500-unit range is the "
        "sourced CAST-RANGE coverage assumption (the beam area is the "
        "sourced 550-radius area; every selected roster member is assumed "
        "inside — no proximity order is invented); the binary-only 90s "
        "cooldown is receipted and never enforced (one cast per fight); the "
        "10% heal-and-shield-power stat is parsed but does not amplify item "
        "ally heals (named limitation, cross-item).  Passive target "
        "calculations do not invent the active."
    ),
    "Spectre's Cowl": (
        "The current full Wiki entry confirms that Incorporeal was removed in "
        "V14.6; the remaining target-relevant behavior is its sourced base "
        "health-regeneration stat, with no post-damage passive to schedule."
    ),
}

# Lifeline defenses trigger mid-fight, so pricing them consumes the ordered
# damage ledger.  They are computed for one rotation and for timed fights whose
# every damage event carries a certified timestamp; an uncertified timed fight
# is withheld after computation instead of reporting a mis-timed trigger.
_TARGET_EVENT_CERTIFIED_REASONS: dict[str, str] = {
    "Protoplasm Harness": (
        "Lifeline's level-scaled temporary health and resist-scaled healing "
        "are modeled when every damage event is event-certified. The "
        "calculation fails closed if damage reaches the unsourced "
        "temporary-health expiry boundary."
    ),
    "Hexdrinker": (
        "Lifeline's level-scaled 30%-health magic shield is modeled when "
        "every damage event is event-certified; uncertified timed fights are "
        "withheld."
    ),
    "Immortal Shieldbow": (
        "Lifeline's level-scaled 30%-health shield is modeled when every "
        "damage event is event-certified; uncertified timed fights are "
        "withheld."
    ),
    "Maw of Malmortius": (
        "Lifeline's bonus-AD-scaled 30%-health magic shield is modeled when "
        "every damage event is event-certified; uncertified timed fights are "
        "withheld."
    ),
    "Seraph's Embrace": (
        "Lifeline's maximum-mana-scaled 30%-health shield is modeled when "
        "every damage event is event-certified; uncertified timed fights are "
        "withheld."
    ),
    "Sterak's Gage": (
        "Lifeline's bonus-health-scaled 30%-health shield is modeled when "
        "every damage event is event-certified; uncertified timed fights are "
        "withheld."
    ),
    "Fimbulwinter": (
        "Everlasting's typed shield formula waits for direct authority for its "
        "mana gate. The current Wiki entry, item cache, client binary, extracted "
        "scripts, and atom receipt provide no threshold or comparison contract. "
        "An eligible authored control event emits a named "
        "mana_gate_authority_unavailable receipt. Optimizer selection remains "
        "withheld. The 1200-unit multi-enemy multiplier is source-authorized, "
        "but typed holder-centered positions are unavailable. The runtime "
        "therefore withholds that multiplier and reports the spatial-input gap."
    ),
    "Force of Nature": (
        "Steadfast stacks are scheduled from exact incoming champion magic-damage "
        "events (per-cast-instance 1s cadence, 7s duration, 8-stack cap, "
        "immobilize +2, all-at-once expiry), and the maximum-stack bonus "
        "resistance is repriced prospectively per packet; the 6% bonus move "
        "speed is declared metadata only and the dealing-damage refresh is a "
        "named boundary."
    ),
    "Jak'Sho, The Protean": (
        "Voidborn Resilience's one-stack-per-second combat state is scheduled "
        "from the exact event ledger and multiplies bonus resistances at max."
    ),
}

_TARGET_BLOCKED_REASONS: dict[str, str] = {}

# Product-facing outcome dimensions for utility and non-TDD effects.  These
# labels are deliberately descriptive: they do not claim a combat formula is
# implemented.  A dimension with ``blocked`` coverage remains withheld rather
# than being silently presented as a stat-only item.
_UTILITY_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "Bandlepipes": ("ally_support", "stat_buff"),
    "Gunmetal Greaves": ("movement",),
    "Cull": ("economy", "progression", "on_hit"),
    "Phage": ("movement",),
    "Heartsteel": ("progression", "health_state"),
    "Hubris": ("progression", "stat_conversion"),
    "Axiom Arc": ("progression", "resource"),
    "Mejai's Soulstealer": ("progression", "stat_conversion"),
    "Rod of Ages": ("progression", "health_state", "resource"),
    "Solstice Sleigh": ("ally_support", "movement", "sustain"),
    "Swiftmarch": ("movement", "stat_conversion"),
    "World Atlas": ("economy", "quest", "ally_support", "vision"),
    "Runic Compass": ("economy", "quest", "ally_support", "vision"),
    "Tear of the Goddess": ("progression", "resource"),
    "Cryptbloom": ("ally_support", "sustain"),
    "Banshee's Veil": ("spell_protection",),
    "Verdant Barrier": ("spell_protection",),
    "Edge of Night": ("spell_protection",),
    "Zhonya's Hourglass": ("stasis",),
    "Guardian Angel": ("revive",),
    "Quicksilver Sash": ("cleanse",),
    "Mercurial Scimitar": ("cleanse", "movement"),
    "Boots of Swiftness": ("slow_resistance", "movement"),
    "Cosmic Drive": ("movement",),
    "Force of Nature": ("movement", "defense"),
    "Jak'Sho, The Protean": ("defense",),
    "Maw of Malmortius": ("defense",),
    "Phantom Dancer": ("movement",),
    "Shurelya's Battlesong": ("movement", "ally_support"),
    "Youmuu's Ghostblade": ("movement",),
    "Rylai's Crystal Scepter": ("slow",),
    "Serylda's Grudge": ("slow",),
    "Frozen Heart": ("attack_speed_reduction",),
    "Randuin's Omen": ("slow", "critical_mitigation"),
    "Runaan's Hurricane": ("multi_target", "copied_on_hit"),
    "Titanic Hydra": ("multi_target",),
    "Profane Hydra": ("multi_target",),
    "Ravenous Hydra": ("multi_target", "sustain"),
    "Stridebreaker": ("multi_target", "slow", "movement"),
    "Statikk Shiv": ("multi_target", "energized"),
    "Stormrazor": ("energized", "movement"),
    "Rapid Firecannon": ("energized", "range"),
    "Umbral Glaive": ("vision",),
    "Horizon Focus": ("vision", "damage_amplification"),
    "Locket of the Iron Solari": ("ally_support", "shield"),
    "Mikael's Blessing": ("ally_support", "cleanse", "sustain"),
    "Redemption": ("ally_support", "sustain"),
    "The Collector": ("execute", "takedown_state"),
}

# Concrete GitHub owners for source-backed gaps.  The full-entry audit exposes
# these references beside every withheld effect so a page review cannot end
# with an untracked prose note.  The umbrella #40 remains the release gate;
# child issues own the implementation family.
_REVIEW_ISSUE_REFS: dict[str, tuple[int, ...]] = {
    "Stridebreaker": (43,),
    "Voltaic Cyclosword": (43,),
    "Runaan's Hurricane": (43,),
    "Fimbulwinter": (44, 46),
    "Endless Hunger": (44, 45),
    "Whispering Circlet": (44,),
    "Archangel's Staff": (44,),
    "Manamune": (44,),
    "Winter's Approach": (44,),
    "Zeke's Convergence": (44,),
    "Axiom Arc": (44,),
    "Hubris": (44,),
    "Doran's Helm": (45,),
    "Actualizer": (45,),
    "Catalyst of Aeons": (45,),
    "Immortal Path": (45,),
    "Ardent Censer": (48,),
    "Bandlepipes": (48,),
    "Imperial Mandate": (48,),
    "Redemption": (48,),
    "Mikael's Blessing": (48,),
    "Locket of the Iron Solari": (46, 48),
}


def review_issue_refs(item_name: str) -> list[int]:
    """Return concrete child issues for a source-backed coverage gap."""
    return list(_REVIEW_ISSUE_REFS.get(str(item_name), (40,)))


def _has_described_effect(item: dict[str, Any]) -> bool:
    """Return whether cached Wiki data describes a passive or active."""
    return bool(item.get("passives") or item.get("active") or item.get("actives"))


# Named receipt-only boundaries: the item has a typed registry entry (so
# the generic ITEM_EFFECTS/ITEM_INPUT_OPTIONS branches would over-claim),
# but its passive cannot be represented by the 1v1 champion fight model —
# the typed value rides the item_state_receipts row only, and the ordinary
# stats still flow through stats.py.
_RECEIPT_ONLY_BOUNDARY_REASONS: dict[str, str] = {
    "Doran's Helm": (
        "Helping Hand's 5 bonus physical damage is minion-only and "
        "receipt-only (item_state_receipts.helping_hand_minion_only); "
        "the champion fighter model has no minion targets, so the branch "
        "is a named boundary, never an on-champion packet."
    ),
    "Ionian Boots of Lucidity": (
        "Ionian Insight grants summoner spell haste, which is receipt-only "
        "(item_state_receipts.ionian_insight_summoner_spell_haste): the "
        "champion fighter model has no summoner-spell action state, so the "
        "branch is a named boundary, never an ability-haste packet."
    ),
}


# Named modeled-state reasons: the item's registry entry IS a scenario-
# controlled state, but the generic ITEM_INPUT_OPTIONS wording would hide
# the specific mechanic from the coverage surface.
_MODELED_STATE_REASONS: dict[str, str] = {
    "Knight's Vow": (
        "Pledge designates the authored Worthy ally and Sacrifice redirects "
        "14% of eligible pre-mitigation physical or magic damage to the "
        "holder (healing it for 12% of post-mitigation Worthy damage) while "
        "the authored tether/health gates are active; the compiled and "
        "receipt walks stage the same split (item_state_receipts sacrifice "
        "row, P3 package 3S)."
    ),
}


# Named modeled-effect reasons: the item's registry entry IS a modeled
# fight effect, but the generic ITEM_EFFECTS wording would hide the
# specific mechanic and its named boundaries from the coverage surface.
_MODELED_EFFECT_REASONS: dict[str, str] = {
    "Force of Nature": (
        "Steadfast is modeled from exact incoming champion magic-damage "
        "events (per-cast-instance 1s cadence, 7s duration, 8-stack cap, "
        "immobilize +2, all-at-once expiry) with the maximum-stack +70 "
        "magic resistance repriced prospectively on the shared survival "
        "kernel; the 6% bonus move speed is declared metadata only and the "
        "dealing-damage refresh is a named boundary (item_state_receipts "
        "steadfast row)."
    ),
    "Maw of Malmortius": (
        "Lifeline arms a magic shield (melee 200 + 150% bonus AD / ranged "
        "150 + 112.5% bonus AD, 3 seconds, magic-damage-only) when a magic "
        "hit would reduce the holder below 30% maximum health, and grants "
        "10% omnivamp until the end of combat; the threshold shield and "
        "the omnivamp heals ride the shared survival kernel on both walks "
        "(item_state_receipts lifeline row, P3 package 3T)."
    ),
    "Jak'Sho, The Protean": (
        "Voidborn Resilience stacks one per second of champion combat from "
        "the exact event ledger (5-stack cap) and multiplies BONUS armor and "
        "magic resistance by 30% at maximum stacks — the bonus-resistance "
        "reprice is prospective per packet on the shared survival kernel; "
        "combat time is the packet timestamp, the holder's own outgoing "
        "damage does not advance its stacks, and the fight window is the "
        "combat window (named boundaries, item_state_receipts voidborn row)."
    ),
}


def item_model_coverage(item: dict[str, Any]) -> dict[str, Any]:
    """Return the optimiser coverage classification for one resolved item."""
    name = str(item.get("name", ""))
    effect_type = ITEM_EFFECTS.get(name, {}).get("type")
    if name == "Death's Dance" and effect_type == "defensive_start":
        status: ItemCoverageStatus = "modeled_effect"
        reason = (
            "Ignore Pain's post-mitigation deferral ticks and Defy's takedown "
            "clear/heal are represented in the ordered participant timeline."
        )
    elif effect_type in {
        "defensive_start",
        "target_mitigation",
        "target_threshold_health",
        "target_threshold_shield",
    }:
        status: ItemCoverageStatus = "stats_only"
        reason = (
            "Guardian Angel's Rebirth is modeled in the target survival ledger; "
            "it changes defense, not outgoing TDD."
            if name == "Guardian Angel"
            else (
                "Time Stop is priced only from the explicit bounded active-seconds "
                "scenario input; item presence alone never assumes stasis."
                if name in {"Zhonya's Hourglass", "Seeker's Armguard"}
                else (
                    "Annul's spell shield is ready at the opening and blocks the "
                    "first authored hostile ability for the holder (one use per "
                    "cast; the 60s cooldown and the damage-restart rule are "
                    "receipted named boundaries — rearm is not modeled inside "
                    "one fight)."
                    if name in {"Banshee's Veil", "Edge of Night", "Verdant Barrier"}
                    else "The represented mechanic changes defense, not outgoing TDD."
                )
            )
        )
    elif name in _STATEFUL_MODELED_ITEMS:
        status = "modeled_state"
        reason = _STATEFUL_MODELED_ITEMS[name]
    elif name in _PARTIAL_BLOCKED_REASONS:
        status = "blocked"
        reason = _PARTIAL_BLOCKED_REASONS[name]
    elif name == "Heartsteel" and name in ITEM_INPUT_OPTIONS:
        status = "modeled_state"
        reason = (
            "Colossal Consumption's permanent bonus-health state is supplied "
            "through the explicit bounded scenario control."
        )
    elif name == "Rod of Ages" and name in ITEM_INPUT_OPTIONS:
        status = "modeled_state"
        reason = (
            "Timeless stacks and their sourced health, mana, and ability-power "
            "conversions are supplied through the explicit bounded scenario control."
        )
    elif name == "Overlord's Bloodmail" and name in ITEM_INPUT_OPTIONS:
        status = "modeled_state"
        reason = (
            "Tyranny is modeled and Retribution uses the explicit bounded "
            "starting missing-health scenario control."
        )
    elif name in _BLOCKED_REASONS:
        status = "blocked"
        reason = _BLOCKED_REASONS[name]
    elif name == "Gunmetal Greaves":
        # The boot's life steal is pinned by the typed sustain receipt and
        # Noxian Gait's Riot-only movement branch is a typed named boundary
        # (item_state_receipts noxian_gait_boundary): the magnitude is
        # unsourced and the fight model has no decaying-movement input, so
        # the movement sub-effect stays out of scope; the ordinary stats
        # (40% attack speed, 45 move speed, 5% life steal) still apply.
        status: ItemCoverageStatus = "modeled_effect"
        reason = (
            "Noxian Gait's Riot-only movement branch remains explicitly out of "
            "scope: its magnitude is unsourced (the Wiki cache has no passive "
            "branch) and the fight model has no decaying-movement input — the "
            "sourced 2.0s decay and champions-only target ride the "
            "noxian_gait_boundary receipt; the boot's attack-speed and "
            "life-steal stats are still applied."
        )
    elif name in _RECEIPT_ONLY_BOUNDARY_REASONS:
        status, reason = "stats_only", _RECEIPT_ONLY_BOUNDARY_REASONS[name]
    elif name in ITEM_EFFECTS:
        status: ItemCoverageStatus = "modeled_effect"
        reason = _MODELED_EFFECT_REASONS.get(
            name, "Damage-relevant effects are represented by the fight model."
        )
    elif name in ITEM_INPUT_OPTIONS:
        status = "modeled_state"
        reason = _MODELED_STATE_REASONS.get(
            name,
            "The item exposes its damage-relevant state as a scenario control.",
        )
    elif name in _REVIEWED_STATS_ONLY:
        status = "stats_only"
        reason = _REVIEWED_STATS_ONLY[name]
    elif not _has_described_effect(item):
        status = "stats_only"
        reason = "The item has no separate passive or active in the cached Wiki data."
    elif item.get("id") is not None or item.get("icon"):
        # A cached source item is a real selectable record, even when its
        # passive/active has not been reviewed yet.  Keep the public contract
        # fail-closed and explicit: ``review_pending`` is reserved for
        # synthetic/unknown fixtures that do not belong to the cached shop.
        status = "blocked"
        reason = (
            "This cached passive or active has not been reviewed for outgoing "
            "damage or state effects; calculation is withheld."
        )
    else:
        status = "review_pending"
        reason = "This passive or active has not yet been reviewed for outgoing TDD."

    return {
        "name": name,
        "status": status,
        "optimizer_eligible": status
        in {"modeled_effect", "modeled_state", "stats_only"},
        "calculation_eligible": (
            status != "review_pending"
            and (status != "blocked" or name in _CALCULATION_ALLOWED_BLOCKED)
        ),
        "outcome_dimensions": list(_UTILITY_DIMENSIONS.get(name, ())),
        "review_issue_refs": (
            review_issue_refs(name) if status in {"blocked", "review_pending"} else []
        ),
        "reason": reason,
    }


def target_item_model_coverage(item: dict[str, Any]) -> dict[str, Any]:
    """Classify one item for use on a passive enemy target."""
    name = str(item.get("name", ""))
    if name in _TARGET_MODELED_REASONS:
        status = "modeled"
        reason = _TARGET_MODELED_REASONS[name]
    elif name in _TARGET_EVENT_CERTIFIED_REASONS:
        status = "modeled_event_certified"
        reason = _TARGET_EVENT_CERTIFIED_REASONS[name]
    elif name in _TARGET_BLOCKED_REASONS:
        status = "blocked"
        reason = _TARGET_BLOCKED_REASONS[name]
    elif item_model_coverage(item)["status"] == "review_pending":
        status = "review_pending"
        reason = "This passive or active has not been reviewed for target durability."
    else:
        status = "not_target_relevant"
        reason = (
            "No reviewed effect on this item changes incoming damage or starting "
            "durability in the passive-target model."
        )
    return {
        "name": name,
        "status": status,
        "calculation_eligible": status not in {"blocked", "review_pending"},
        "outcome_dimensions": list(_UTILITY_DIMENSIONS.get(name, ())),
        "review_issue_refs": (
            review_issue_refs(name) if status in {"blocked", "review_pending"} else []
        ),
        "reason": reason,
    }


def target_build_coverage(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise whether a target inventory is safe to calculate."""
    entries = [target_item_model_coverage(item) for item in items]
    blocked = [entry for entry in entries if not entry["calculation_eligible"]]
    return {
        "complete": not blocked,
        "model": "passive_target",
        "items": entries,
        "blocked": blocked,
        "note": (
            "Every equipped item is supported by the passive-target model."
            if not blocked
            else "Calculation is withheld until the named target mechanic is modelled."
        ),
    }


def require_target_item_coverage(items: list[dict[str, Any]]) -> None:
    """Reject target inventories that would silently omit a defense."""
    coverage = target_build_coverage(items)
    if coverage["blocked"]:
        blocked = coverage["blocked"][0]
        raise ValueError(
            f"Enemy item {blocked['name']} is not supported yet: {blocked['reason']}"
        )


def require_certified_target_timeline(
    items: list[dict[str, Any]], timeline_coverage: dict[str, Any]
) -> None:
    """Withhold a computed fight that cannot price a conditional defense.

    Conditional defenses are priced from the ordered damage ledger, so a
    coarse source would mis-time the trigger.  This runs after the fight so
    the error can name the exact uncertified sources instead of guessing.
    """
    if bool(timeline_coverage.get("complete", False)):
        return
    conditional = next(
        (
            str(item.get("name", ""))
            for item in items
            if str(item.get("name", "")) in _TARGET_EVENT_CERTIFIED_REASONS
        ),
        None,
    )
    if conditional is None:
        return
    coarse = [str(source) for source in timeline_coverage.get("coarse_sources", [])]
    named = ", ".join(coarse) if coarse else "at least one damage source"
    verb = "is" if len(coarse) <= 1 else "are"
    raise ValueError(
        f"Result withheld: enemy item {conditional} needs a "
        f"certified event timeline, but {named} {verb} not event-certified."
    )


def optimizer_candidate_coverage(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise which legal item candidates can be scored without omission."""
    classified = [item_model_coverage(item) for item in items]
    included = [entry for entry in classified if entry["optimizer_eligible"]]
    excluded = [entry for entry in classified if not entry["optimizer_eligible"]]
    return {
        "eligible_candidates": len(classified),
        "scored_candidates": len(included),
        "excluded_count": len(excluded),
        "complete": not excluded,
        "excluded": excluded,
        "note": (
            "Every legal candidate is fully modelled."
            if not excluded
            else (
                f"{len(excluded)} legal item candidate"
                f"{' is' if len(excluded) == 1 else 's are'} withheld because "
                "a damage-relevant mechanic is not yet modelled."
            )
        ),
    }


def optimizer_supported_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return candidates whose outgoing TDD can be scored without omission."""
    return [item for item in items if item_model_coverage(item)["optimizer_eligible"]]


def require_optimizer_item_coverage(item: dict[str, Any]) -> None:
    """Reject a locked item whose damage-relevant mechanics are incomplete."""
    coverage = item_model_coverage(item)
    if not coverage["optimizer_eligible"]:
        raise ValueError(
            f"{coverage['name']} cannot be locked into BIS search yet: "
            f"{coverage['reason']}"
        )


def require_calculation_item_coverage(
    items: list[dict[str, Any]],
    *,
    participant: str,
    allow_ally_effects: bool = False,
) -> None:
    """Reject a participant loadout whose outgoing effects are incomplete.

    Manual calculations and coupled roster fights are calculation entry paths,
    not only optimiser requests.  Reusing the same per-item contract here
    prevents an incomplete item from being accepted by ``/api/calculate``
    while remaining selectable in the browser.
    """
    for item in items:
        coverage = item_model_coverage(item)
        if (
            allow_ally_effects
            and coverage["status"] == "blocked"
            and coverage["name"] in ALLY_ITEM_EFFECTS
        ):
            # CP17's cross-participant packet layer is the authoritative
            # calculation path for support items.  They remain withheld from
            # ordinary BIS ranking until every holder-side sibling is
            # modeled, but an explicitly rostered support item is safe to
            # calculate because its item-team effects are timestamped and
            # fail closed when their trigger is absent.
            continue
        if coverage["calculation_eligible"]:
            continue
        raise ValueError(
            f"{participant} item {coverage['name']} cannot be used in a "
            f"calculation yet: {coverage['reason']}"
        )


__all__ = [
    "item_model_coverage",
    "optimizer_candidate_coverage",
    "optimizer_supported_items",
    "require_calculation_item_coverage",
    "require_certified_target_timeline",
    "require_optimizer_item_coverage",
    "require_target_item_coverage",
    "review_issue_refs",
    "target_build_coverage",
    "target_item_model_coverage",
]
