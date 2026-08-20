# Scryglass Patch-Day Runbook (P0d)

Operating procedure for a League of Legends patch day. This turns the P3
automation (`scripts/patch_regression.py`, `scripts/patch_update.py`,
`data/staleness.json`, `scripts/issue_gate.py`) into a repeatable,
SLA-bound operating procedure.

Read `architecture.md` for the module map and the `/patch-update` skill
(`.agents/skills/patch-update/SKILL.md`) for the audit-report interpretation
detail this runbook summarizes.

## When this runs

Riot ships a patch roughly every two weeks (normally a Wednesday, EUW/NA
deploy day). The wiki cache in `data/` drifts from the shipped game files the
moment the patch lands. This runbook is the day-0 procedure: detect, re-pull,
regression-check, triage, re-certify, gate, commit, push, clear staleness.

## Roles

- **Patch owner** — one person accountable for the whole day-0 cycle. Runs
  steps 0-5, owns the SLA, writes the announcement.
- **Engine reviewers** — called in for escalations (champion kit rework,
  item rework).
- Any engineer can perform any step, but the patch owner signs off.

## SLA

| Phase | Target | Clock starts | Owner |
|---|---|---|---|
| Detection | < 4h | patch deploy time | patch owner |
| Triage — every stale flag re-certified *or* boundary-documented | < 24h | patch deploy time | patch owner |
| Full re-cert — engine re-validated, golden re-captured, committed, pushed | < 72h | patch deploy time | patch owner + reviewers |
| STALE badge | stays visible until re-cert | — | — |

Definitions:

- **Patch day** = the Riot deploy date for the patch (announced in the patch
  notes; normally a Wednesday).
- **Re-certified** = the flagged value was checked against the game files and
  either the wiki cache was updated to match or the code-owned copy was
  updated, and `scripts/patch_regression.py check` no longer flags it.
- **Boundary-documented** = the flagged value is deliberately not modeled and
  that decision is recorded with a reason (champion module `MODULE_COVERAGE`
  entry, `ASSUMPTIONS` line, or a worklist / item-source reconciliation
  entry). A boundary is a *documented decision*, not a TODO, and it is not a
  way to clear a badge without explanation — the badge stays until the
  regression re-run shows the entry as no longer stale (Step 5).
- The STALE badge (`static/js/staleness.js`) reads `/api/staleness`, which
  serves the committed `data/staleness.json`. The badge stays visible until
  the committed report shows `stale: false` for the selected champion/item.
  **Never hand-edit `data/staleness.json` to hide a badge** — it is a
  generated artifact of `scripts/patch_regression.py`.

## Step 0 — Detect the patch (< 4h SLA)

1. Confirm the live game patch:
   ```bash
   cdtb versions game -a          # live patch, e.g. "16.16"
   ```
   (`CDTB_BIN=/path/to/cdtb cdtb versions game -a` when cdtb is not on PATH —
   the regression script itself resolves the same way.)
2. Compare against the committed staleness report:
   ```bash
   python -c "import json; print(json.load(open('data/staleness.json'))['patch'])"
   ```
   If `staleness.json.patch !=` the live patch, a new patch has landed;
   proceed. Also check the wiki's `patchLastChanged` fields in
   `data/champions.json` / `data/items.json` to see what the wiki thinks
   moved.
3. Read the Riot patch notes
   (https://www.leagueoflegends.com/en-us/news/tags/patch-notes/) and note
   which registered champions / configured items are touched.
4. Open the patch-day tracking issue (or thread): patch version, suspected
   scope, patch owner. Post the early announcement
   (`docs/patch-announcement-template.md`) so the beta channel knows a
   re-cert is in flight.

Escalate immediately (see Escalation) if the patch notes a **champion kit
rework** or an **item rework** for anything we model.

## Step 1 — Re-pull the wiki cache -> audit report

```bash
python scripts/patch_update.py run
```

What `run` does:

1. **Clears lolstaticdata's page caches** (`vendor/lolstaticdata/__cache__`,
   `__wiki__`) so the pull cannot silently re-serve the old patch.
2. **Streams `data_updater.update_data()`** — new `data/champions.json`,
   `data/items.json`, `data/runes.json`; the patch string is printed on
   completion.
3. **Prints the audit report** — diff of the new cache vs the last committed
   patch (git HEAD; `data/` is tracked):
   - **Registered champions** — `NEEDS REVIEW` (numeric diff) vs
     `text-only`.
   - **Configured items** — same flags, plus `NOTE: code-owned values` when
     `item_effects._REFERENCE_ITEM_EFFECTS` holds values the wiki does not
     update (verify by hand against the new wiki text).
   - **Shop delta** — net-new / removed items; removed IMPLEMENTED items are
     flagged `** IMPLEMENTED — code must be updated **`.
   - **Roster delta** — new champions block runtime promotion until a named,
     tested champion module and full-entry evidence are added.
   - **Item source completeness** — `BLOCKING` when an effect branch
     disappeared or an unreviewed Riot-declared effect is missing from the
     wiki; the run stops there until each entry is recorded in `item_source`
     (`APPROVED_BRANCH_REMOVALS` / `ACKNOWLEDGED_SOURCE_CONFLICTS` /
     `OPEN_SOURCE_CONFLICTS`).
   - **Item economics** — `BLOCKING` when `data/economics-sourced.json` is
     pinned to another DDragon release than the cache, an ordinary item has
     no sourced sell row, or a shop total disagrees with the cache without a
     reviewed entry in `refresh_economics_data.ACKNOWLEDGED_TOTAL_DIVERGENCES`.
     (Between steps 2 and 3 the run already refreshed the file from DDragon
     for the release the new cache pins — `scripts/refresh_economics_data.py`,
     the file's only writer; `economy.py` prices every purchase plan from it.
     DDragon lagging the patch fails the run: re-run once it has published.)
4. **Rebuilds the static catalogues** the UI fetches at runtime
   (`scripts/build_ability_catalog.py`, `scripts/build_effect_catalog.py`,
   `scripts/build_receipts.py`).
   `static/bis-profiles.json` is NOT rebuilt by the script — it needs the
   Axword Meraki sibling repo (`lol-strength-analysis`); rebuild by hand
   (`python scripts/build_bis_profiles.py`) if its wiki inputs moved.
5. **Runs the gates**: reviewed-packet freshness, the full-entry audit, the
   staleness gate (`patch_regression check`), and the coverage census
   (`coverage_census.py run --output docs/coverage-census.json`, ~10 min; it
   refreshes its receipt and fails on a frontier entry no
   `docs/coverage-residue.json` row acknowledges or a row that no longer
   reproduces) — each fails closed and aborts the run — then pytest, golden
   compare (diffs printed — expected after a real patch), and re-captures the
   golden baseline ONLY if pytest is green. If pytest is red, hand-validated
   expectations drifted — fix them first (Step 4).

Notes:

- `FAILURE TO PARSE MODIFIER` spam during the pull is normal lolstaticdata
  noise; only `Skipped N` summary lines mean data was dropped. Compare new
  spam against the known-degraded list in `Agents.md`.
- Re-print the audit later without re-pulling:
  ```bash
  python scripts/patch_update.py audit
  python scripts/patch_update.py detail <ChampionOrItem>   # full leaf diff vs HEAD
  ```

Then read the report against the `/patch-update` skill's triage guidance.
**Do not commit yet** — commit data + code + golden together in Step 4.

## Step 2 — Regression check -> stale champions/items

```bash
python scripts/patch_regression.py check
```

What it does:

- Resolves the live patch via `cdtb versions game -a` (override with
  `--patch 16.16`).
- Downloads the game-file ground truth for the live patch
  (raw.communitydragon.org per-champion `CharacterRecords/Root` bin.json plus
  `items.cdtb.bin.json`) into `data/gamefiles/`.
- Compares the wiki cache against the game files with documented tolerances
  (0.5% relative or ±2 flat for stats; ±0.5 flat for ability damage rows;
  ±0.25 cooldowns; ±1 costs). Mana-family stats compare only for
  MANA/ENERGY resources; a cache stat with no game field is `unchecked`,
  never stale. Ability rows that cannot be mapped are `unchecked` — never
  claimed checked, never claimed stale.
- Writes `data/staleness.json` (`patch`, `checked_at`, per-champion and
  per-item `stale` flags) and exits 1 if anything is stale.

Useful variants:

```bash
python scripts/patch_regression.py check --patch 16.16            # pinned patch
python scripts/patch_regression.py check --verify-wads Ahri,Gnar  # spot-check the
                    # raw export against real champion WADs via cdtb
python scripts/patch_regression.py check --limit 20               # fast smoke pass
```

Then:

- Record the stale list (champions + items) in the tracking issue.
- Every stale entry is now on the 24h triage clock. Stale items get STALE
  badges in the UI automatically (`/api/staleness`).
- If a *champion* is stale, its numbers are not trustworthy for build advice
  — say so in the announcement.

## Step 3 — Triage stale items & champions (< 24h SLA)

For EVERY stale flag, pick exactly one of these outcomes:

### A. Re-certify (values updated + re-pinned)

- The flag is a genuine patch change: the wiki cache already carries the new
  value (re-pulled in Step 1) — verify it against the game files in
  `data/gamefiles/` and the patch notes, then re-run the regression so the
  flag flips to false.
- **Code-owned values** (`NOTE: code-owned values` in the audit): update
  `item_effects._REFERENCE_ITEM_EFFECTS` by hand from the new wiki text
  (`Agents.md` rule 5 — no literal fallbacks at call sites; missing keys must
  raise).
- **Champion modules with hand-validated expectations**: update
  `tests/test_<champion>.py` with cited old → new values, and update the
  module if the kit's numbers moved.
- **Re-pin** = re-run `scripts/patch_regression.py check` and see the flag
  flip; the flip is committed in Steps 4-5.

### B. Boundary-documented (marked, not modeled)

- The flagged value is deliberately out of scope (e.g. a known-degraded wiki
  parse listed in `Agents.md`, or a mechanic the module declares out of
  scope). Record the boundary where it lives:
  - Champion module: the slot left out of `SLOTS` (the contract derives
    `out_of_scope`) or a declared `MODULE_COVERAGE` entry, + `ASSUMPTIONS` line.
  - Item: worklist entry or `docs/item-source-reconciliation.md` note.
- The boundary must name the value, the patch that moved it, and why it is
  not modeled.
- The entry must still resolve to `stale: false` on the next regression run —
  a genuinely out-of-scope value is one the regression cannot compare (no
  game mapping -> `unchecked`, never stale) or one whose cache value was
  updated while the calc deliberately does not consume it.

Triage rules of thumb:

- **Item stat changes** (health/AD/AP/...): flow through the JSON
  automatically; re-cert is usually a re-run + commit.
- **Item passive/active changes**: the parser feeds the engine; verify the
  item's golden sweep values still look right (a broken parse raises by
  design). Use `/add-item-effect` if a passive gained a damage/on-hit/stat-
  conversion mechanic worth modeling.
- **Champion numeric changes**: update module + tests, re-pin.
- **Removed item**: remove from `_ITEM_PARSE_CONFIG`,
  `_REFERENCE_ITEM_EFFECTS`, and its tests.
- **New item**: stats flow automatically; model passives via
  `/add-item-effect` (verify the exact name in `data/items.json` first —
  parser config and build scenarios use exact cached names).

Escalate (see Escalation) when the change is a kit rework, item rework, or
net-new item.

## Step 4 — Golden re-capture, full gates, commit, push

Golden semantics (`Agents.md`): after a real patch, golden diffs are
EXPECTED; the gate is that every diff is explained in the commit.

```bash
python scripts/patch_update.py run     # Step 1 already ran pytest + golden
                                       # compare and re-captured when green
# if pytest was red in Step 1 and you fixed expectations since:
python scripts/golden_snapshot.py compare scripts/golden_baseline.json
python scripts/golden_snapshot.py capture scripts/golden_baseline.json
```

1. Explain every golden diff in the commit message — trace each to a wiki
   change (use `python scripts/patch_update.py detail <name>` for
   affected named modules). Also verify surprising *absences*
   (a buff that didn't move the baseline because the snapshot has 0 AP /
   0% crit / the ability sits at rank 1 at the snapshot level).
2. Full gates:
   ```bash
   pytest -q
   pylint src/ --fail-under=9         # any code change
   black --check src/ tests/ scripts/ # any code change
   git diff --check
   ```
3. Commit data + code + golden together, e.g.
   `feat(patch): re-cert 16.16 — every golden diff explained in the body`
   (see commit f7e8aad for the established format).
4. Push the patch branch and merge via the normal review flow.
5. If the patch closes GitHub issues, gate the closures:
   ```bash
   python scripts/issue_gate.py check --issue <n> --commit <sha> [--deploy-sha <sha>]
   ```
   (per `docs/issue-closure-policy.md`: commit-addressed, merged on the
   working branch, clean tree, gates green, deployment ancestor when known).

## Step 5 — Clear staleness; confirm badges disappear

1. Re-run the regression on the committed data:
   ```bash
   python scripts/patch_regression.py check
   ```
   Expect `stale: 0 champions, 0 items` (or only entries that are
   boundary-documented with `stale: false`).
2. Commit the refreshed `data/staleness.json` (`patch` = the new patch).
3. After deploy, confirm:
   - `/api/staleness` serves the new report (new `patch`, all `stale: false`).
   - STALE badges are gone for previously-flagged champions/items
     (`static/js/staleness.js` renders badges only for `stale: true` entries).
4. Update the tracking issue and send the final announcement
   (`docs/patch-announcement-template.md`).

## Escalation

### Champion kit rework — full module review (E-series checklist)

A kit rework changes abilities, not just numbers. A number update is Step
3-A; a rework is a full module review:

1. Run the `/analyze-champion` skill's red-flag checklist (Step 4 of
   `.agents/skills/analyze-champion/skill.md`): pet/summon secondary damage,
   retaliation/shield damage, stat-granting abilities applied before damage
   calc, empowered-autos once per cast, passive cooldowns, recasts,
   %max/%current/%missing-HP components, unusual crit scaling, DoT tick
   counts, stacking stat grants, passive+active hybrids, form-swap stat
   grants (source from Community Dragon game files, NOT the wiki stat box),
   and on-hit application scope (`triggers=` vs on-attack).
2. Re-verify the champion's JSON shape (`get_champion(name)` — iterate every
   entry in every slot; recasts live in extra entries, e.g. Ambessa Q2 is
   `Q[1]`).
3. Check the E-series workstreams for the champion
   (`data/worklists/e2-dot-ticks.json`, `e3-stacks.json`, `e4-summons.json`,
   `e5-mismodeled.json`, `e8-interactions.json`) and its audit verdict
   (`data/champion-audit/batch-*.json`) — a rework may close or reopen gaps.
4. Update `src/calculator/champions/<name>.py` (slot map, `MODULE_COVERAGE`,
   `ASSUMPTIONS`, `OPTIONS`) and `tests/test_<name>.py` with cited old → new
   values; re-pin `data/practice-corpus/scenarios.json` if the scenario is
   affected.
5. Re-capture golden with every diff explained; run the full gates.

### Item rework

1. Treat as a full re-cert of that item family (all items sharing the
   mechanic — see `/add-item-effect` and
   `docs/item-source-reconciliation.md`).
2. Update the `item_effects` typed accessors and `_REFERENCE_ITEM_EFFECTS`; no
   literal fallbacks at call sites (`Agents.md` rule 5).
3. Update tests, re-run the regression, re-capture golden with explained
   diffs.

### New item added

1. Stats flow automatically once the cache carries it (Step 1).
2. If it has a damage/on-hit/stat-conversion passive worth modeling, use
   `/add-item-effect` (exact name from `data/items.json`).
3. Add it to the golden item sweep if the sweep should cover it; re-capture
   with explained diffs.

### Escalation SLA impact

A rework escalates the triage clock: the affected champion/item is announced
as "re-cert in progress" and the STALE badge stays visible until the re-cert
completes — the badge is the point; it tells users not to trust those
numbers yet. The < 72h full re-cert SLA still applies.

## Non-goals (this runbook does not cover)

- Mid-patch hotfix data (between patches): re-run Steps 2-5 on the pinned
  patch if a hotfix changes game files.
- `bis-profiles.json` rebuilds (needs the Meraki sibling repo) — manual,
  documented in Step 1.
- Public launch / auth operations — see `docs/deploy-runbook.md`.
- Issue-closure policy details — see `docs/issue-closure-policy.md`.

## Environment (2026-08-07)

- `LCC_WIKI_DB=/Users/river/Projects/scryglass/data/lol/knowledge/league-wiki.sqlite3`
- `LCC_WIKI_QUERY=<repo>/vendor/league-wiki-query/scripts/query_league_wiki.py`
- `LCC_AXWORD_SOURCE=/Users/river/Projects/lol-strength-analysis/src/data/generated/merakiAbilityKits.ts`
