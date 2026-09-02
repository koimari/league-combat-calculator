---
name: patch-update
description: Patch-day workflow — re-pull wiki data when a new LoL patch drops, audit what the calculator implements, update code if needed, and re-capture the golden baseline. Use when the user says a new patch dropped or asks to update/re-pull wiki data.
---

# Patch Update

One command does the mechanical work; your job is interpreting its report
and finishing with an explained commit.

```bash
python scripts/patch_update.py run             # the full day-0 pipeline (start here)
python scripts/patch_update.py detect          # is a new patch live? read-only
python scripts/patch_update.py audit           # re-print the audit, no pull
python scripts/patch_update.py detail NAME...  # full leaf diff vs HEAD for ANY champion/item
```

This script is the only patch-day orchestrator; every scriptable step is one
of its subcommands (`fetch`, `bis` and `packets` run the game-file refresh,
the bis-profiles rebuild and the packet-currency check in isolation). See
`docs/patch-day-runbook.md` for the per-subcommand exit codes.

`run` clears lolstaticdata's page caches (stale caches silently "re-pull"
the old patch), fetches the new data, refreshes `data/economics-sourced.json`
from DDragon for the release the new cache pins (`economy.py` prices every
purchase plan from it), diffs the data against the last committed patch (git
HEAD — `data/` is tracked), rebuilds the static catalogues the web UI fetches,
runs the patch-day gates, pytest and the golden compare, and re-captures the
baseline **only if pytest is green**.

The rebuild covers `static/ability-catalog.json`, `static/effect-catalog.json`
and `static/bis-profiles.json`. The last merges an Axword Meraki kit reference
from the `lol-strength-analysis` sibling repo supplying 24 damage packets the
wiki parser cannot read, so the run needs that repo checked out
(`LCC_AXWORD_SOURCE`) — it refuses to write rather than dropping them, on an
absent kit source, zero champions, zero merged packets, or a merged count
below the checked-in asset.

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
  `item_effects._REFERENCE_ITEM_EFFECTS` and the wiki does NOT update them.
  Read the new wiki text for that item and update by hand if they moved.

**Shop delta:**
- Removed item that is IMPLEMENTED → remove it from `_ITEM_PARSE_CONFIG`,
  `_REFERENCE_ITEM_EFFECTS`, and its tests.
- New item → stats already flow automatically; if it has a damage/on-hit/
  stat-conversion passive worth modeling, use `/add-item-effect`.

**Roster delta:** a new champion fails closed at runtime until a named,
tested module and full-entry evidence exist — run `/add-champion`.
`build_receipts.py` likewise refuses a cached champion without a registered
module, so the roster addition and its module must land together.

**Item economics:** `BLOCKING` means the DDragon refresh did not land for the
cache's release, an ordinary item has no sourced sell row, or a shop total
disagrees with the cache. Re-run `python scripts/refresh_economics_data.py`;
for a disagreement, review it against the wiki page and record it in that
script's `ACKNOWLEDGED_TOTAL_DIVERGENCES` (a row that stops reproducing is
reported too).

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
- The E9 practice-corpus gate (`tests/test_e9_corpus.py`) is anchored at the
  `src/` tree of the merge base with `main`, so an in-branch `src/` change
  leaves every scenario *executed* and a broken receipt fails on its numbers.
  A patch that legitimately moves a receipt is re-pinned with
  `python scripts/repin_corpus.py` in a data-only follow-up commit — it
  re-probes `/api/calculate` first and refuses to stamp a receipt that no
  longer reproduces — and `python scripts/repin_corpus.py --check` is the
  gate that the pins and the executed selection are both intact.
- Commit `data/`, `scripts/golden_baseline.json`, and any code changes
  together, with every baseline diff explained in the commit message
  (see commit f7e8aad for the format).

## Patch-day gates (issue #134)

`python scripts/patch_update.py run` fails closed BEFORE re-capturing the
golden baseline when any of these are missing/stale:
- reviewed champion packets — both halves of `patch_update.py packets`: the
  source receipts (vs champions.json + the Meraki axword kit + per-champion
  wiki revisions) and a rebuild that must still reproduce the asset's slots.
  They catch disjoint drift (a changed source vs a changed builder), and
  neither is covered by the import-time `PACKET_SHA256` pin, which only
  proves the 76 packet-backed modules accepted *this* asset. Rebuild with
  `build_reviewed_modules.py` and commit the asset with its source receipts,
- the full-entry audit tool (`--query-tool`/`LCC_WIKI_QUERY`/PATH/vendor),
- the game-file refresh and the patch-regression staleness check (`CDTB_BIN`
  or `--patch`). The refresh clears `data/gamefiles/` first: the downloader
  skips files that already exist and its filenames are not patch-versioned,
  so an un-cleared cache compares the new wiki data against the previous
  patch's game files,
- the item economics refresh (DDragon must have published the release the
  new cache pins) and its audit section,
- the coverage census (`scripts/coverage_census.py run --output
  docs/coverage-census.json`, ~1 min on 16 cores): a frontier entry no
  `docs/coverage-residue.json` row acknowledges, or a row that no longer
  reproduces, aborts. Commit the refreshed receipt with the data.

Environment: build the wiki revision index (`scripts/decompose_wiki.py
--wiki-db`, ~4.5 min, no variable needed at its default path), set
`LCC_WIKI_DB` only for a copy elsewhere, `LCC_AXWORD_SOURCE` (Meraki
kit in the `lol-strength-analysis` sibling repo), `LCC_WIKI_QUERY` (the query
CLI, vendored fallback at `vendor/league-wiki-query/scripts/`), and
`CDTB_BIN` (game-file exports) per the runbook; every path resolves
repo-relative/env/CLI with an actionable error when missing.
