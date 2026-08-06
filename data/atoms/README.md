# data/atoms — fundamental behavior atoms (WS3, v3)

The atomic catalog: every champion mechanic decomposed into typed behavior
atoms with dual provenance (wiki page + game binary). Schema:
`atoms.schema.json`. Per-champion atom files are gitignored (regenerable from
`data/bin`); `atom-summary.json`, `classification-report.json`,
`unclassified.json`, and the Vladimir sample are tracked.

## Classifier v3 (data-driven)

- **Identity**: wiki vocabularies in `data/wiki-atoms/` (177+ atoms, 6
  families + `interaction`) are the only identity source — zero hardcoded
  champion/spell names in code.
- **Semantic layer**: `spell-tags.json` maps the game's own `mSpellTags`
  vocabulary (Trait_ActiveHeal, Trait_Shield, Trait_Invisibility,
  Trait_Pet, Trait_Transformation, Trait_AttackReset, PositiveEffect_MoveBlock,
  ...) to atoms + target policy.
- **Wiki-driven champion maps** (`champion-passive-atoms.json`,
  `champion-spell-atoms.json`): form-change passives (Neeko/Kayle), shared-
  script summons (Annie Tibbers, Heimer turrets, Malzahar Voidlings, Yorick,
  Zyra, Ivern, Azir, Kindred, Illaoi), traps, and clones (LeBlanc, Zed,
  Wukong) — behaviors the binaries cannot express as SpellObject tags.
- **Two-tier matching**: strong hits (object-name tokens, multi-token
  keywords, tags) always count; weak hits (single datavalue tokens) only when
  no strong hit exists (cap 2) — removed ~3,000 spurious atoms with zero
  object-level recall loss.
- **Clone inheritance**: `*Missile/*Attack/*Mis/*Mini/*Hit/*Return` variants
  (digit-stripped, incl. the game's "Missle" typo) inherit the parent spell's
  atoms.
- **Noise**: engine/cosmetic artifacts (Managers, VFX, Trackers, skins,
  tooltips, UI helpers) are excluded by object name only.

## Current state (v4 — no over-classification)

- 173-wiki-champion universe (excludes TFT/test entities).
- **5,345 atoms, 0 weak-evidence atoms** (over-classification = atoms guessed from datavalues only; none emitted). Evidence is tag/name/rule/inherited/wiki-map only. 19/19 sanity checks.
- **19/19 sanity checks** across 7 families (heals, shields, stealth,
  summons, clones, executes, resets, DoT, slows, dashes, transforms).
- Known limitation: damage_type is null for most damage atoms — the
  CharacterRecord bins do not carry damage types; that data lives in the
  wiki ability pages (WS1) and spell bins, and is the next iteration's fix.
