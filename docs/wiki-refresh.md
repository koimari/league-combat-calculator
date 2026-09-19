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
leave `failure.txt` in the staged generation. An operating-system file lock prevents overlapping
runs. The system releases the lock when the process exits, including after
a crash. The persistent `*.refresh.lock` file can remain in place.

The upstream downloader reuses files whose revisions and hashes match. It
still requests every text page's wikitext during the scan. File namespace 6
stays metadata-only. Completed generations retain source evidence and use
disk space until an operator removes older generations.

This command reports `formula_authority: false`. Changed formulas require
the packet review and calculation gates in [the runbook](patch-day-runbook.md).
The command leaves champion caches, executable modules, accepted packets,
and golden files intact.

## Deterministic fortnightly schedule

Give any OS scheduler, cron, a systemd timer, launchd, or Task Scheduler, this
command. A scheduler has no shell environment to read `LCC_SCRYGLASS_ROOT`
from, so the source checkout comes from the flag and every path is absolute:

```bash
/abs/python /abs/repo/scripts/patch_update.py wiki-refresh \
  --scryglass-root /abs/scryglass --scheduled --anchor-date 2026-09-09
```

The command finds its own checkout from the script path, so the job entry
needs no working directory. `--scheduled` selects the most recent fortnight due date from the anchor and
runs that period once, so a wake after sleep catches up the due date. Receipts
in `data/wiki/wiki-schedule/` record attempts, failures, and successful
updates, and the command skips a period it already attempted. A failed period
has no automatic retry; run the command without `--scheduled` to retry it.
All steps use local scripts and source APIs. Model calls are absent.
