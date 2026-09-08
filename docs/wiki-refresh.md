# Scheduled Wiki source refresh

Run from the calculator checkout:

```bash
python scripts/patch_update.py wiki-refresh --scryglass-root /path/to/scryglass
```

`LCC_SCRYGLASS_ROOT` can supply the source checkout. The command uses its
`lol_kills.knowledge.league_wiki_vault` downloader and `league_wiki_db` index
builder. Supply `--seed-vault /path/to/validated/vault` on the first run to
reuse existing source documents. Later runs copy the vault named by the active
index. Copies preserve the accepted source when a download fails.

The default output is this checkout's `data/wiki/league-wiki.sqlite3`.
`--wiki-db` selects a different output. This command uses the local default
even when `LCC_WIKI_DB` points at another project. The rich index includes
article revisions, raw text, sections, and full-text search tables, so packet
checks and the query CLI can read the same file. Set
`SCRYGLASS_LEAGUE_WIKI_DB` to that path for the query CLI. The existing
`decompose_wiki.py --wiki-db` command creates a smaller revision-only index;
running it over this output removes the rich tables.

Each run stages its vault and report under `data/wiki/wiki-generation-*`.
After complete acquisition and index validation, the packet report and full-entry
audit identify drift before the command atomically replaces the active index.
Any written source page requires review, including a changed template whose
parent article revision stayed the same. Exit 1
means the refreshed source needs packet review; exit 0 means the packet check
is clean. Download, build, or report failures preserve the active index and
leave `failure.txt` in the staged generation. A lock prevents overlapping
runs. After a process crash, confirm that it stopped before removing the
`*.refresh-lock` directory.

The upstream downloader reuses files whose revisions and hashes match. It
still requests every text page's wikitext during the scan. File namespace 6
stays metadata-only. Completed generations retain source evidence and use
disk space until an operator removes older generations.

This command reports `formula_authority: false`. Changed formulas require
the packet review and calculation gates in [the runbook](patch-day-runbook.md).
The command leaves champion caches, executable modules, accepted packets,
and golden files intact.

## Deterministic macOS schedule

`scripts/install_wiki_refresh.py` writes a launchd plist. Supply absolute
`--repo`, `--python`, `--scryglass-root`, `--axword-source`, `--seed-vault`,
`--logs`, and `--output` paths. It checks that the required inputs exist.
Load the file with `launchctl bootstrap gui/$(id -u) /path/to/job.plist`.

The job wakes each Wednesday at 09:00 local time. `--scheduled` selects the
most recent fortnight due date from `--anchor-date 2026-09-09` and runs it
once. A Thursday wake after sleep catches up the due Wednesday. Receipts in
`data/wiki/wiki-schedule/` record attempts, failures, and successful updates.
The next weekly wake skips a period already attempted. A failed period has
no automatic retry; run the command without `--scheduled` to retry manually.
All steps use local scripts and source APIs. Model calls are absent.
