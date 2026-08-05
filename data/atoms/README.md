# data/atoms — fundamental behavior atoms (WS3)

The atomic catalog: every champion mechanic decomposed into typed behavior
atoms with dual provenance (wiki page + game binary). Per-champion atom files
are gitignored (regenerable from `data/bin`); the summaries and report are
tracked.

## Pipeline

`scripts/extract_atoms.py` (v2, data-driven) classifies every SpellObject in a
champion's CharacterRecord:

1. Loads the wiki behavior-atom vocabularies (`../wiki-atoms/*.json`, 177 atoms
   in 5 families) — the only source of atom identity. No champion names or
   spell names are hardcoded in the classifier.
2. Tokenizes spell/buff names (`mScriptName`, `mAlternateName`, ObjectName,
   buff tooltip names), `mSpellCalculations` names and `DataValues` names
   (camelCase splits, singular/plural stem matching) and matches them against
   atom keywords.
3. Augments with binary signals: `mSpellTags` (explicit tag->atom map),
   cooldown/castRange presence, `mAffectsTypeFlags` (raw), and generic rules
   (execute = ultimate + damage-cap datavalues; crit-attack names; nuke names).
4. Data-driven noise guards: champion-name prefixes are stripped from script
   names; vocab keywords made of champion names or corpus-generic tokens
   ("duration", "ability damage") are ignored; ambiguous shared keywords only
   vote for their home atom; substring traps ("miss" in missile, "stance" in
   distance, "wind" in window) are blocked.

## Files

| File | Contents |
|---|---|
| `<champ>.atoms.json` | per-champion atom list (gitignored, regenerable) |
| `atom-summary.json` | family -> champions |
| `unclassified.json` | per champion: SpellObjects with no atom match, each flagged noise vs real-looking |
| `classification-report.json` | per champion family counts, unclassified notes, sanity checks, classifier improvements |

## Validation set (2026-08 deep audit)

20 diverse champions: Aatrox, Aphelios, Cho'Gath, Gnar, Jinx, Kayle, Kha'Zix,
Kindred, Nasus, Neeko, Pyke, Senna, Sion, Sylas, Thresh, Udyr, Veigar, Viktor,
Zeri, Vladimir.

Result: 1029 atoms, 256 unclassified SpellObjects (103 real-looking, 153
engine/cosmetic artifacts). 5/7 curated sanity mechanics pass; Neeko and
Kayle transform fail because their binaries never contain transform/disguise
tokens (see classification-report.json suggestions).
