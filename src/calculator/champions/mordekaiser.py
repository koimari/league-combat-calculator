"""Mordekaiser — CP10.4 full-entry-reviewed packet module.

E8a: the W (Indestructible) grey-health receipts live in the shared
participant-timeline primitive, which stores 45% of post-mitigation
damage dealt + 7.5% of pre-mitigation damage taken as Potential Shield
(capped at 30% of maximum health) and pays the recast heal
("Shield to Healing" 35/37.5/40/42.5/45% by W rank) at the earliest
recast time (W cast + 0.5 s per the wiki).  The module keeps pricing W
as a non-damaging state-only slot; the engine's cast timeline still
schedules the W cast that arms the recast.

Roadmap session (2026-08-21): closes both of Mordekaiser's
out_of_scope slots (W, R).  Neither is a damage gap — both were
mislabeled, exactly like the Singed P/W stale-label bug: the pinned
packet already declares them ``kind: "no_damage"``
(``static/reviewed-packets.json``), so ``build_packet_module`` was
already emitting proper zero-damage rows while ``MODULE_COVERAGE``
still read "out_of_scope".  Both reclassified to ``no_damage`` on
three-channel evidence, with no behavior change (the parser output,
including each row's ``detail`` text, is byte-identical):

  - W (Indestructible): the wiki entry's three effect branches are
    "stores ... as Potential Shield" (passive), "consumes his Potential
    Shield to grant himself a shield" (active), and "consumes the
    remaining shield, healing" (recast) — no enemy-damage clause
    anywhere, and the only leveling rows are "Heal" (the 8-25 by-level
    decay) and "Shield to Healing" (35/37.5/40/42.5/45%).  The game
    binary agrees exactly: ``Characters/Mordekaiser/Spells/
    MordekaiserWAbility/MordekaiserW``'s ``DataValues`` are
    ``Duration`` (5.0), ``DamageConversion`` (0.45), ``BaseShield``
    (0.05), ``HealingPercent`` (padded 7-slot ``[.325, .35, .375, .40,
    .425, .45, .475]``, so W ranks 1-5 at indices 1-5 are exactly the
    wiki's 35/37.5/40/42.5/45%), ``MinionPenalty`` (0.25),
    ``DamageTakenConversion`` (0.075), ``MaxHealthCap`` (0.30),
    ``TimeBeforeDecay`` (1.0) and ``DecayPerSecond`` (0.005) — there is
    no base-damage or damage-ratio field on the spell at all, and its
    only calculations are ``HealthDecay`` / ``MaxHealthTooltip`` /
    ``MinHealthTooltip``.  The v2 atoms capture
    (``data/atoms/v2/mordekaiser.atoms.v2.json``) carries exactly two
    tags for ``MordekaiserW`` — ``Trait_ActiveHeal`` and
    ``Trait_Shield`` — plus a ``MordekaiserWPassive`` grey-health atom;
    no ``Trait_DamageAbility``/``Trait_AoE`` damage atom exists for the
    slot.  The shield/heal side is not withheld — it is already priced
    by the E8a grey-health primitive (see above and
    ``tests/test_e8_grey_health.py``), so ``no_damage`` here means "no
    outgoing damage", not "unmodeled".
  - R (Realm of Death): the wiki entry is a banish + slow + reveal, a
    heal for 10% of the TARGET's maximum health, and a 10% steal of the
    target's AP / total attack speed / maximum health / armor / magic
    resistance / base AD — no damage clause.  Binary agrees:
    ``MordekaiserRAbility/MordekaiserR`` carries only
    ``SpiritRealmDuration`` (7.0), ``StatStealPercentScalar`` (0.1),
    ``ZoneRadius`` (1200.0) and ``GhostAPRatio`` (0.6), with no damage
    field and no damage calculation.  v2 atoms tag it
    ``Trait_ImmobilizingCCSpell`` + ``Trait_ActiveHeal`` and split the
    steal into the ``MordekaiserR_StatSteal`` /
    ``MordekaiserR_StatStealEnemy`` buff objects — again no damage
    atom.  Both of R's sourced riders stay documented-not-modeled for
    the SAME named reason, and it is an input gap rather than a
    modeling choice: every term is a percentage of the DEFENDER's
    stats, and neither the outgoing self-heal ledger (``healing.py``)
    nor an ability ``stat_buff`` payload carries the defender's stats —
    ``_apply_stat_buff_ultimates`` (``damage.py``) folds ``stat_buff``
    keys into the attacker's own ``champion_stats`` only.  Adding a
    ``stat_buff`` today would have to invent the target's AP/AD/armor,
    which is exactly the fail-closed line; it stays a receipt until the
    coupled timeline can price it against the real defender.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "62dd25de0191c8de67cec4f56eaebf7ad2bfa32cf704569b553e18049647d228"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Mordekaiser", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec
ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Indestructible) stores 45% of post-mitigation damage dealt and "
    "7.5% of pre-mitigation damage taken as Potential Shield (capped at "
    "30% of maximum health); the recast (modeled at W cast + 0.5 s, the "
    "wiki's earliest available recast) heals the Shield-to-Healing % "
    "(35/37.5/40/42.5/45% by W rank) of the stored shield — the E8a "
    "grey-health primitive authors it from the incoming/outgoing "
    "ledgers. Shield conversion and both decay curves are state.",
    "R (Realm of Death) heals Mordekaiser for 10% of the TARGET's "
    "maximum health on cast (cached R prose).  The outgoing self-heal "
    "ledger (healing.py) carries only the main fighter's stats, so the "
    "target-maximum-health term has no live input there; the heal is "
    "documented-only until the coupled timeline can price it against "
    "the defender's max health.",
    "W (Indestructible) deals no enemy damage in any channel: the "
    "cached wiki entry lists only the Potential Shield store, the "
    "shield active and the recast heal, the game binary's MordekaiserW "
    "spell object has no damage field (only Duration/DamageConversion/"
    "BaseShield/HealingPercent/MinionPenalty/DamageTakenConversion/"
    "MaxHealthCap/TimeBeforeDecay/DecayPerSecond), and the v2 atoms "
    "capture tags it Trait_ActiveHeal + Trait_Shield with no damage "
    "atom.  Its shield and recast heal are priced by the E8a "
    "grey-health primitive, so the slot is no_damage, not withheld.",
    "R (Realm of Death) likewise deals no enemy damage (binary "
    "MordekaiserR carries only SpiritRealmDuration/"
    "StatStealPercentScalar/ZoneRadius/GhostAPRatio; v2 atoms tag it "
    "Trait_ImmobilizingCCSpell + Trait_ActiveHeal).  Its 10% stat "
    "steal (target AP, total attack speed, maximum health, armor, "
    "magic resistance and 10% of current total AD off base AD) is "
    "sourced but unmodeled for the same reason as the R heal above: "
    "every term is a percentage of the DEFENDER's stats, and the "
    "attacker-only stat_buff channel (_apply_stat_buff_ultimates) has "
    "no defender input, so pricing it would require inventing the "
    "target's stats.",
]
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "no_damage",
    "E": "modeled",
    "R": "no_damage",
}
REVIEW_STATUS = "reviewed_module"
