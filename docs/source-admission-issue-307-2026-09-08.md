# Issue 307 source review

The JSON beside this file preserves five complete champion parent pages and
26 ability pages. The extra page is Camille Wall Dive, which the parent reaches
through its grouped E entry. Each page has its revision, timestamp, source URL,
and SHA-256 of the complete wikitext.

The original 30 pages were captured on 2026-09-08 at 11:58 UTC. Wall Dive was
fetched through the same Wiki API at 15:19 UTC. Its revision is 4007586, dated
2026-04-12. The supplement used `Scryglass-wiki-decompose/0.1 (research)`.

## Source boundary

The current source admission uses public patch 26.17 and client patch 16.17.
The calculation cache remains source version 16.16.1. Packet regeneration uses
that frozen cache. The older rich Wiki index was retrieved on 2026-07-31 and
serves as comparison evidence. Its older ability values cannot establish the
current patch. A parent revision identifies the parent page; ability templates
have their own revisions.

This review covers every P/Q/W/E/R entry for the five issue champions, including
Camille E's second page. It records existing behavior and evidence limits.
Runtime formulas and their certification remain outside this source artifact.

## Full-entry findings

| Champion | Slot review |
|---|---|
| Azir | P summons a separate Sun Disc; the modeled encounter excludes it. Q now states 75/95/115/135/155 plus 35–55% AP. W mixes level and rank axes; its packet flattens those axes incorrectly, while the named module reads them separately and places attacks in the auto stream. E retains 70–230 plus 60% AP with a separate equal shield. R retains 200/400/600 plus 75% AP. |
| Camille | P's current template gives 10/15/20/25% maximum-health shields at levels 1/7/13/19 and a 14/11/8-second cooldown. Cached prose lists 10/15/20%; the named module uses 20% and a general shield before combat. Q's packet describes Q1; its module owns delayed Q2 and true conversion. W now has a 12–10-second cooldown and 7–9% maximum-health outer damage plus its bonus-AD scaling. E damage comes from Wall Dive, with cooldown supplied by Hookshot; the module applies the attack-speed buff throughout the fight. R adds current-health damage to attacks inside the zone. |
| Gwen | P's champion damage remains 1% plus 0.6% per 100 AP of target maximum health. The cache's Bonus Damage row is a healing cap. Current healing is 67%, capped at 12–40 plus 7% AP; the module still uses 50%. Q's module owns center conversion and snip events, with stacks 1–3 currently treated as zero bonus snips. W supplies defensive state. E's packet reads the attack-speed row as AP scaling; its module uses 15 plus 20% AP for one empowered attack. R's packet describes one needle, while the module owns the cast groups and passive rider. |
| Kennen | P supplies mark and stun state. Q remains 75–275 plus 75% AP. W's packet selects the passive attack; active damage is 70–170 plus 80% AP and the named module separates these branches. E retains 80–240 plus 80% AP. R now states 40/80/120 plus 25% AP per bolt, with 25/50/75 bonus resistances. Successive strikes add 10% damage up to 150%; all six total 7.5 first-bolt equivalents. The module's base parts repeat equal bolts, so downstream escalation requires its own runtime evidence. |
| Yasuo | P grants Flow shield and critical-strike state. Its cached Bonus Damage row stores shield strength, so damage packet promotion is invalid. The module's detail calls it a magic-damage shield although the source gives a general shield. Q's current revision changes critical formula markup; base damage remains 20–120 plus 105% AD. W supplies a selected projectile-defense window. E's module owns stack damage and per-target lockout. R's packet retains 200/350/500 plus 150% bonus AD; its other effects remain separate runtime concerns. |

## Gwen and Yasuo packet decisions

Gwen P needs evidence that identifies its named module and source formula.
Additive packet ratios cannot express AP multiplied by target maximum health.
The 41 changed numeric leaves reported for its prior packet describe the heal
cap, so they cannot become champion damage. The minion-only damage row also
requires its own target restriction.

Yasuo P remains a no-damage slot. Its complete template has no enemy-damage
formula. Flow shield values belong to defensive state.

The source JSON preserves the formulas and their revision evidence. Packet
changes require focused checks against the frozen cache and the named module.

## Scoped parent revision index

The packet check uses a metadata-only SQLite index at
`data/wiki/league-wiki.sqlite3`. Four API batches requested exactly the 173
cached champion display names with redirects left unresolved. The source JSON
keeps those raw revision responses. This index has the five-column schema from
`scripts/decompose_wiki.py`; it contains no article text.

Twenty parent revisions changed from the prior packet asset. The JSON also
preserves their complete current wikitext and a diff from the rich index.
Caitlyn, Hecarim, Draven, Ekko, LeBlanc, Lulu, Swain, Skarner, Pyke, Samira,
Seraphine, and Gwen changed trivia, links, or presentation. Blitzcrank,
Bel'Veth, Malzahar, Maokai, and Zaahen have unchanged text in the rich-index
comparison despite newer parent receipts.

Azir's parent changes the soldier level increment from five to eight, while
its ability template already states eight. The source also retains a parent
AP range that differs from its W template; the named module reads the cached
ability entry. Illaoi's parent changes tentacle targeting text and section
markup. Zac adds a knockdown category. Complete current P/Q/W/E/R dependencies
for Illaoi and Zac are included because those parent changes touch mechanics.
Zac's ability damage formulas remain unchanged in the comparison. Illaoi's
new notes concern spawn positions, movement restrictions, overlapping slams,
and item/rune interactions. These require separate runtime reviews when their
behavior is changed. This packet refresh does not certify those interactions.
