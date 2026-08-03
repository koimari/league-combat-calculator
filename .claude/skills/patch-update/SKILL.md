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
python scripts/patch_update.py detail NAME...  # full leaf diff vs HEAD for ANY
                                               # champion/item (incl. generic-path)
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
actually dropped. The known offenders (gimmick scalings, all generic-path)
are listed under "Known-degraded wiki parses" in CLAUDE.md's Known Quirks —
compare new spam against that list. To attribute a NEW error to a champion:
the ability names streamed to stdout right before the error belong to the
champion being parsed (the `Processed X` line prints only after X finishes,
so the error belongs to the champion AFTER the last `Processed` line).

## Triage the audit report

**Registered champions** (only these get detail — generic-path champions
need no code by design):
- `text-only` — usually nothing to do. Exception: if that champion's module
  regex-parses prose (tier-3 custom slots), confirm the parse still works —
  the golden gate will catch value drift either way.
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

**Roster delta:** new champions run the generic path automatically; verify
with tier 1 of `/add-champion` if the user cares about that champion.

## Gates and the commit

- pytest red → hand-validated expectations drifted. Fix them with documented
  derivations (cite old → new wiki values), then
  `python scripts/golden_snapshot.py capture scripts/golden_baseline.json`.
- Golden compare diffs are EXPECTED after a real patch. Every line must be
  traced to a wiki change before committing — use `detail <name>` for
  generic-path champions that appear. Also verify surprising *absences*
  (e.g. a buff that didn't move the baseline because the snapshot has 0 AP,
  0% crit, or the ability sits at rank 1 at the snapshot level).
- Commit `data/`, `scripts/golden_baseline.json`, and any code changes
  together, with every baseline diff explained in the commit message
  (see commit f7e8aad for the format).
