# data/bin — decomposed game binaries (regenerable)

Parsed output of the local League client binaries (16.15.8024387) — the exact
numeric layer behind the wiki cache. `characters/*.bin.json` are **tracked**:
runtime constants root in them (`src/calculator/binary_roots.py`), so a
champion dump missing from the checkout fails closed instead of silently
pricing from stale literals. The item and map dumps stay gitignored
(regenerable; nothing at runtime reads them).

Regenerate (requires the installed client + tool venv):

    uv venv --python 3.12 ~/.local/mcp/wad-env
    uv pip install --python ~/.local/mcp/wad-env/bin/python league-tools cdtb
    ~/.local/mcp/wad-env/bin/python scripts/decompose_binaries.py --champions --items --map11

Hash tables auto-download from raw.communitydragon.org/data/hashes/lol/.

Contents:
- `characters/<name>.bin.json` — 203 CharacterRecords (base stats, spell data,
  buff data) parsed from `Champions/<name>.wad.client`.
- `characters/gnarbig.bin.json` — the GnarBig (Mega Gnar) CharacterRecords
  root. `decompose_binaries.py` only walks `Champions/<name>.wad.client` per
  champion, and GnarBig is not its own WAD unit, so this file was fetched
  directly from `https://raw.communitydragon.org/latest/game/data/characters/gnarbig/gnarbig.bin.json`
  (same fallback pattern as `decompose_items`'s CommunityDragon dump).
  Verifies `src/calculator/champions/gnar.py`'s `MEGA_BONUS_*` /
  `MEGA_ATTACK_SPEED_LOSS` constants — see `tests/test_gnar_mega_gamefile.py`.
- `decompose-receipt.json` — extraction receipt (counts, sizes) — tracked.
- `characters/aatrox.bin.json.sample`, `behavior-index.json` (per-champion heal/shield name index) — tracked.

Provenance spot-check (2026-08-20): `characters/renata.bin.json` was re-fetched
from `https://raw.communitydragon.org/latest/game/data/characters/renata/renata.bin.json`
and is **byte-identical** to the locally decomposed file
(sha256 `d05e6d6eabc614f8821be6ec4c01e09018f6606c6b94eee1712ca04f00e4211e`), so
the two provenance routes above (client WAD vs CommunityDragon) agree for at
least this champion. The same check established that these dumps carry **no**
damage-class data: `mDamageType` — the only such field in
`hashes.binfields.txt` — occurs zero times across all 203 champion bins and
`items.bin.json`. See `src/calculator/champions/renata_glasc.py`
(`BAILOUT_AUTHORITY["adjudication"]["fields"]["burn_damage_class"]["searched"]`).

Cross-validation: binary values match `data/champions.json` exactly
(e.g. Ahri HP 590/+104, AD 53/+3, Armor 21/+4.2, MR 30/+1.3, MS 330, Range 550).
