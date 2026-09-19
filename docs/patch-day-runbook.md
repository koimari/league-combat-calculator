# Patch-day runbook

Who owns a League of Legends patch day, what the clock is, what the orchestrator returns,
and when to escalate.

The steps themselves are the `/patch-update` skill
(`.claude/skills/patch-update/SKILL.md`), which is the one home for the procedure and for
reading the audit report. `architecture.md` has the module map.

## When this runs

Riot ships a patch roughly every two weeks, normally a Wednesday. The wiki cache in
`data/` drifts from the shipped game files the moment the patch lands, so this is the
day-0 cycle: detect, re-pull, regression-check, triage, re-certify, gate, commit, push,
clear staleness.

## Roles

- **Patch owner**: one person accountable for the whole day-0 cycle. Runs every step, owns
  the SLA, writes the announcement.
- **Engine reviewers**: called in for escalations, meaning a champion kit rework or an
  item rework.

Any engineer can perform any step, but the patch owner signs off.

## SLA

| Phase | Target | Clock starts | Owner |
|---|---|---|---|
| Detection | < 4h | patch deploy time | patch owner |
| Triage: every stale flag re-certified *or* boundary-documented | < 24h | patch deploy time | patch owner |
| Full re-cert: engine re-validated, golden re-captured, committed, pushed | < 72h | patch deploy time | patch owner and reviewers |
| STALE badge | stays visible until re-cert | none | none |

- **Patch day** is the Riot deploy date announced in the patch notes.
- **Re-certified** means the flagged value was checked against the game files, the wiki
  cache or the code-owned copy was updated to match, and a fresh
  `scripts/patch_regression.py check` run leaves it unflagged.
- **Boundary-documented** means the flagged value is deliberately not modelled and the
  decision is recorded with a reason: a champion module `MODULE_COVERAGE` entry, an
  `ASSUMPTIONS` line, or an item-source reconciliation entry. A boundary is a documented
  decision, not a deferral, and it does not clear a badge. The badge stays until the
  regression re-run shows the entry as fresh.
- The STALE badge (`static/js/staleness.js`) reads `/api/staleness`, which serves the
  committed `data/staleness.json`, and stays visible until that report shows
  `stale: false` for the selected champion or item. **Never hand-edit
  `data/staleness.json` to hide a badge**, because it is a generated artifact of
  `scripts/patch_regression.py`.

## The one orchestrator

Every scriptable step is a subcommand of `scripts/patch_update.py`, and there is no second
orchestrator. `run` is the whole day-0 pipeline plus the gates; the rest are the same work
in isolation, for a re-run or a spot check. Nothing here commits, stages, or splices a
diff into a tracked file: triage, explaining golden diffs, committing and pushing stay
human.

```bash
python scripts/patch_update.py run                   # the full day-0 pipeline
python scripts/patch_update.py detect                # read-only
python scripts/patch_update.py audit                 # re-print the audit, no pull
python scripts/patch_update.py detail <name>...      # full leaf diff vs HEAD
python scripts/patch_update.py fetch --patch 16.16 [--limit 20] [--force]
python scripts/patch_update.py bis [--patch 16.16]
python scripts/patch_update.py packets [--no-rebuild]
```

| Subcommand | Covers | Exit codes | Fails closed on |
|---|---|---|---|
| `run` | pull, economics refresh, audit, catalogue and bis rebuild, packet currency, full-entry audit, game-file refresh, staleness, coverage census, pytest, golden compare, conditional re-capture | 0 green with the baseline re-captured, non-zero per the failing step | every gate below, in order; the golden baseline is re-captured only after pytest is green |
| `detect` | live against cached patch comparison, read-only | 0 current, 1 new patch available, 2 infra failure | `cdtb` and the CommunityDragon `content-metadata.json` fallback both unreachable; `data/staleness.json` missing, unreadable, or without a `patch` field; unparseable patch labels |
| `audit` / `detail` | the audit report without re-pulling | 0 clear, 1 BLOCKING entries (`audit`) | a vanished effect branch, an unreviewed source conflict, a removed-but-implemented item, a stale economics table |
| `fetch` | refreshes `data/gamefiles/`, the exact cache `patch_regression.py check` reads, plus the tracked Gnar, GnarBig and Renata game-file authority pair under `data/bin/characters/` | 0 clean, 1 partial when an authority file failed, 2 hard error | empty or unreadable champion roster; HTTP errors per file; malformed JSON. It always clears a prior patch's cached bin before fetching, so a stale copy cannot be silently re-served, and refuses to overwrite an uncommitted tracked authority file without `--force` |
| `bis` | rebuilds `static/bis-profiles.json`. It also runs inside `run`'s catalogue rebuild, so it is not a by-hand step | 0 ok, 2 on any invariant failure | missing `LCC_AXWORD_SOURCE` sibling-repo file; missing champion cache; zero champions produced; zero merged Meraki damage packets; a merged-packet count that regresses below the checked-in baseline, which is the Axword invariant in `tests/test_bis_profiles.py` |
| `packets` | one currency verdict on `static/reviewed-packets.json` from two checks that catch disjoint drift: the source receipts (champions.json and Axword sha256, per-champion wiki revision, roster membership, so a changed *source*) and a rebuild diff (regenerate to a scratch path and compare `slots` and `review_status`, so a changed *builder*, which no receipt can see). It never writes that file, and `--no-rebuild` runs the receipt half alone | 0 clean, 1 not current | missing checked-in asset; a missing wiki revision index, built with `decompose_wiki.py --wiki-db`; missing Axword source; zero wiki revision receipts |

`detect`, `fetch`, `bis` and `packets` each print one JSON report to stdout with
`--indent 2, sort_keys`, so they compose with `jq` in a cron wrapper or a CI step. `run`,
`audit` and `detail` print for a human.

Neither the import-time `PACKET_SHA256` pin nor either half of `packets` replaces the
others. The pin proves only that the 76 packet-backed champion modules accepted *this*
asset, since the other 97 modules are hand-authored and never import-fail on it, and it
says nothing about whether the asset is current.

Splicing a drifted champion's reviewed-packet sub-object back into
`static/reviewed-packets.json` stays a by-hand `build_reviewed_modules.py` edit. `packets`
only reports the diff.

## Escalation

A number update is ordinary triage. A rework is an escalation, and it moves the triage
clock: the affected champion or item is announced as re-cert in progress and the STALE
badge stays visible until the re-cert completes, which is the point of the badge. The 72h
full re-cert SLA still applies.

**Champion kit rework.** A kit rework changes abilities, not just numbers, so it takes a
full module review:

1. Run the `/analyze-champion` skill's red-flag checklist: pet and summon secondary
   damage, retaliation and shield damage, stat-granting abilities applied before the
   damage calculation, empowered autos once per cast, passive cooldowns, recasts,
   max, current and missing-health components, unusual crit scaling, DoT tick counts,
   stacking stat grants, passive and active hybrids, form-swap stat grants sourced from
   Community Dragon game files rather than the wiki stat box, and on-hit application
   scope.
2. Re-verify the champion's JSON shape through `get_champion(name)`, iterating every entry
   in every slot, because recasts live in extra entries (Ambessa Q2 is `Q[1]`).
3. Check the champion's workstream files under `data/worklists/` and its audit verdict
   under `data/champion-audit/`. A rework may close or reopen gaps.
4. Update `src/calculator/champions/<name>.py` and `tests/test_<name>.py` with cited old
   and new values, and re-pin `data/practice-corpus/scenarios.json` if the scenario is
   affected.
5. Re-capture the golden with every diff explained, then run the full gates.

**Item rework.** Treat it as a full re-cert of every item sharing the mechanic, per
`/add-item-effect` and `docs/item-source-reconciliation.md`. Update the `item_effects`
typed accessors and `_REFERENCE_ITEM_EFFECTS` with no literal fallbacks at call sites
(`CLAUDE.md` rule 5), update tests, re-run the regression, re-capture the golden with
explained diffs.

**New item.** Stats flow automatically once the cache carries it. If it has a damage,
on-hit or stat-conversion passive worth modelling, use `/add-item-effect` with the exact
name from `data/items.json`, and add it to the golden item sweep if the sweep should cover
it.

## Not covered here

- Mid-patch hotfix data: re-run the regression and re-cert steps on the pinned patch if a
  hotfix changes game files.
- Public launch and auth operations: `docs/deploy.md`.
- Issue-closure policy: `docs/issue-closure-policy.md`.

## Environment

Every source resolves repo-relative by default, so a variable is only needed to point at a
copy somewhere else.

- `LCC_WIKI_DB` is the wiki revision index the `packets` gate reads. Build it at the
  default path with `python scripts/decompose_wiki.py --wiki-db`, then leave the variable
  unset. The run takes 490 requests to the wiki API and about 4.5 minutes, and writes
  24,452 namespace-0 revisions to `data/wiki/league-wiki.sqlite3`, 1.6 MB and gitignored.
  Rebuild it on patch day before `packets`, because it holds each page's current revision
  only.
- `LCC_AXWORD_SOURCE` is `src/data/generated/merakiAbilityKits.ts` from a
  `koimari/lol-strength-analysis` checkout, which the default expects as a sibling of this
  repo.
- `LCC_WIKI_QUERY` is the read-only wiki CLI `full_entry_audit.py` shells out to. It is
  vendored at `vendor/league-wiki-query/scripts/query_league_wiki.py` and found there
  without the variable. Its own database is the full source-preserving index
  (`SCRYGLASS_LEAGUE_WIKI_DB`, schema in `vendor/league-wiki-query/references/schema.md`),
  not the revision index above.
