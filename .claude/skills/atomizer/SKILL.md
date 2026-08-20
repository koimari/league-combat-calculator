---
name: atomizer
description: The unified way to atomize anything numerical and quantifiable in this repo — items, abilities, runes, economics, stats, champions. Use when adding/updating items or champions, verifying data, building catalogues, or doing patch-day work; never write a new ad-hoc extractor.
---

# Atomizer

One Atom contract for everything numerical: items, abilities, runes,
economics tables, champion stats, and champion combat atoms.

## Run it

```bash
python scripts/atomize.py --list
python scripts/atomize.py all --out data/atoms     # every domain
python scripts/atomize.py items runes --out data/atoms
```

Output per domain: `data/atoms/<domain>.json` (atomic write, manifest in
`data/atoms/manifest.json` with object/atom counts + sha256 + source refs).

## The Atom contract

Every atom is a dict with: `atom_id`, `behavior`, `source`, `name`,
`values` (numeric array), `units`, `evidence` (receipt strings), `hash`.

Rules (enforced by `src/calculator/atomizer.py` + tests):
1. **Per-effect independence** — each effect fragment (branches, then
   sentences) is classified on its own. No cross-effect "seen" set; the
   old item atomizer's first-passive-absorbs-everything bug is forbidden.
2. **Dedup at emission** by `(atom_id, behavior)`, merging evidence.
3. **No atom without a receipt** — evidence names the exact effect + keyword
   (e.g. `active:Ravenous Crescent@kw:life steal`).
4. Atomic file writes + a manifest.

## Domains

| Domain | Source | Extractor |
|---|---|---|
| items | data/items.json | atomizer_domains.atomize_item_catalogue |
| abilities | data/champions.json | atomizer_domains.atomize_abilities |
| runes | data/runes.json | atomizer_domains.atomize_rune_catalogue |
| economics | data/economics-sourced.json | atomizer_domains.atomize_economics |
| stats | data/champions.json | atomizer_domains.atomize_stats |
| champions | data/champions.json | atomize.py delegates to specialist scripts/extract_atoms.py |

## When to use

- Adding a new item or champion: run the item/ability domains and inspect
  the atoms for that object before wiring effects.
- Patch day: run `atomize.py all` after the data pull; diff the manifest
  counts against the previous run to see what changed numerically.
- Any new numerical data family: add a domain extractor to
  `src/calculator/atomizer_domains.py` (same Atom contract), a CLI branch in
  `scripts/atomize.py`, and tests in `tests/test_atomizer.py`. Do NOT build
  a separate extractor with its own output format.
