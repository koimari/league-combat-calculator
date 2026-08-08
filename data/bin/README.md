# data/bin — decomposed game binaries (regenerable)

Parsed output of the local League client binaries (16.15.8024387) — the exact
numeric layer behind the wiki cache. **Gitignored** (17 MB, regenerable).

Regenerate (requires the installed client + tool venv):

    uv venv --python 3.12 ~/.local/mcp/wad-env
    uv pip install --python ~/.local/mcp/wad-env/bin/python league-tools cdtb
    ~/.local/mcp/wad-env/bin/python scripts/decompose_binaries.py --champions --items --map11

Hash tables auto-download from raw.communitydragon.org/data/hashes/lol/.

Contents:
- `characters/<name>.bin.json` — 203 CharacterRecords (base stats, spell data,
  buff data) parsed from `Champions/<name>.wad.client`.
- `decompose-receipt.json` — extraction receipt (counts, sizes) — tracked.
- `characters/aatrox.bin.json.sample`, `behavior-index.json` (per-champion heal/shield name index) — tracked.

Cross-validation: binary values match `data/champions.json` exactly
(e.g. Ahri HP 590/+104, AD 53/+3, Armor 21/+4.2, MR 30/+1.3, MS 330, Range 550).
