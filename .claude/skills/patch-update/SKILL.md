---
name: patch-update
description: Patch-day workflow — re-pull wiki data when a new LoL patch drops, audit what the calculator implements, update code if needed, and re-capture the golden baseline. Use when the user says a new patch dropped or asks to update/re-pull wiki data.
---

# Patch Update

One command does the mechanical work; your job is interpreting its report
and finishing with an explained commit.

```bash
python scripts/patch_update.py run             # pull + audit + rebuild + gates (start here)
python scripts/patch_update.py audit           # re-print the audit, no pull
python scripts/patch_update.py detail NAME...  # full leaf diff vs HEAD for ANY champion/item
```

`run` clears lolstaticdata's page caches (stale caches silently "re-pull"
the old patch), fetches the new data, diffs it against the last committed
patch (git HEAD — `data/` is tracked), rebuilds the static catalogues the web
UI fetches, runs pytest and the golden compare, and re-captures the baseline
**only if pytest is green**.

The rebuild covers `static/ability-catalog.json` and `static/effect-catalog.json`.
It deliberately skips `static/bis-profiles.json`, which merges an Axword Meraki
kit reference from the `lol-strength-analysis` sibling repo supplying 24 damage
packets the wiki parser cannot read — rebuilding without that repo checked out
silently drops them. If its wiki inputs moved, check the sibling out and run
`python scripts/build_bis_profiles.py` by hand.

Modifier-parse ERROR spam during the pull ("FAILURE TO PARSE MODIFIER") is
normal lolstaticdata noise; only the `Skipped N` summary lines mean data was
actually dropped. The known offenders (gimmick scalings) are listed under
"Known-degraded wiki parses" in CLAUDE.md's Known Quirks — compare new spam
against that list. To attribute a NEW error to a champion: the ability names
streamed to stdout right before the error belong to the champion being parsed
(the `Processed X` line prints only after X finishes, so the error belongs to
the champion AFTER the last `Processed` line).

## Triage the audit report

**Champions** (every cached champion is a registered named module — issue #161):
- `text-only` — usually nothing to do. Exception: if that champion's module
  regex-parses prose (custom slots), confirm the parse still works — the
  golden gate will catch value drift either way.
- `NEEDS REVIEW` — a number we may hard-depend on moved. Check the
  champion's module and `tests/test_<champion>.py` for hand-validated
  expectations; update them citing old → new wiki values.

**Configured items:**
- `stats.*` diffs flow through the JSON automatically — no code change.
- Passive/active *text* diffs feed the parser: verify the item's values in
  the golden item sweep still look right; a broken parse raises by design.
- `NOTE: code-owned values [...]` — those keys live in
  `item_effects._OFFLINE_ITEM_EFFECTS` and the wiki does NOT update them.
  Read the new wiki text for that item and update by hand if they moved.

**Shop delta:**
- Removed item that is IMPLEMENTED → remove it from `_ITEM_PARSE_CONFIG`,
  `_OFFLINE_ITEM_EFFECTS`, and its tests.
- New item → stats already flow automatically; if it has a damage/on-hit/
  stat-conversion passive worth modeling, use `/add-item-effect`.

**Roster delta:** a new champion fails closed at runtime until a named,
tested module and full-entry evidence exist — run `/add-champion`.
`build_receipts.py` likewise refuses a cached champion without a registered
module, so the roster addition and its module must land together.

## Packet-evidence re-pin (issue #161)

Rebuilding `static/reviewed-packets.json` (`build_reviewed_modules.py`)
rewrites the manifest entry — including its revision receipts — for every
champion the patch touched. Each packet-backed module pins the SHA-256 of
the entry it accepted, so those champions now **fail closed at import**
("packet evidence drifted") until re-pinned. That failure IS the review
step, not an error to suppress:

1. `detail <name>` / diff the manifest entry to see what actually changed.
2. Re-review the module against the new evidence (tick counts, variants,
   assumptions still correct?).
3. Re-pin the module's `PACKET_SHA256` with the new digest:

   ```bash
   python -c "from src.calculator.champions.packet_module import _packet_specs, packet_spec_sha256; print(packet_spec_sha256(_packet_specs()['Ahri']))"
   ```

Hand-authored modules (no digest) never import-fail on evidence changes;
`full_entry_audit.py` instead reports an advisory `stale_review_sources`
field when their pinned SOURCES revision falls behind the manifest — use it
as the re-review triage list.

## Gates and the commit

- pytest red → hand-validated expectations drifted. Fix them with documented
  derivations (cite old → new wiki values), then
  `python scripts/golden_snapshot.py capture scripts/golden_baseline.json`.
- Golden compare diffs are EXPECTED after a real patch. Every line must be
  traced to a wiki change before committing — use `detail <name>` for the
  affected named modules. Also verify surprising *absences*
  (e.g. a buff that didn't move the baseline because the snapshot has 0 AP,
  0% crit, or the ability sits at rank 1 at the snapshot level).
- If `src/` changed, the E9 practice-corpus gate (`tests/test_e9_corpus.py`)
  fails until each non-legacy scenario `sha` in
  `data/practice-corpus/scenarios.json` is re-pinned to the new engine
  commit. Re-pin in a data-only follow-up commit; the fresh pin activates
  the receipt assertions, so run the corpus test locally to prove the
  receipts still reproduce before pushing.
- Commit `data/`, `scripts/golden_baseline.json`, and any code changes
  together, with every baseline diff explained in the commit message
  (see commit f7e8aad for the format).

## Patch-day gates (issue #134)

`python scripts/patch_update.py run` fails closed BEFORE re-capturing the
golden baseline when any of these are missing/stale:
- reviewed champion packets (packet freshness receipts vs champions.json +
  the Meraki axword kit; rebuild with `build_reviewed_modules.py` and commit
  the asset with its source receipts),
- the full-entry audit tool (`--query-tool`/`LCC_WIKI_QUERY`/PATH/vendor),
- the patch-regression staleness check (`CDTB_BIN` or `--patch`).

Environment: set `LCC_WIKI_DB` (wiki sqlite), `LCC_AXWORD_SOURCE` (Meraki
kit sibling repo), `LCC_WIKI_QUERY`, and `CDTB_BIN` in the runbook; every
path resolves repo-relative/env/CLI with an actionable error.

## Working environment (verified 2026-08-07)

- Wiki sqlite DB: `/Users/river/Projects/scryglass/data/lol/knowledge/league-wiki.sqlite3`
  (730MB, built 2026-08-01, 311k cataloged pages). Set `LCC_WIKI_DB` or pass
  `--wiki-db`; `build_reviewed_modules.py` embeds per-champion revision
  receipts + source hashes in `static/reviewed-packets.json`.
- Wiki query tool: vendored at `vendor/league-wiki-query/scripts/query_league_wiki.py`
  (from the codex skill); `LCC_WIKI_QUERY` overrides. `full_entry_audit.py`
  resolves PATH > vendor/ by default.
- Meraki axword kit: `/Users/river/Projects/lol-strength-analysis/src/data/generated/merakiAbilityKits.ts`
  (`--axword-source` / `LCC_AXWORD_SOURCE`).
- cdtb toolchain (game-file exports for `decompose_binaries.py`/`patch_regression.py`):
  NOT installed on this machine — those paths fail with actionable errors until
  cdtb + `league_tools` are available.
