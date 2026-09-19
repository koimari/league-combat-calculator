# Slop audit: documentation

Scope: every `.md` at the repo root, all of `docs/` (43 `.md`, 209 `.json`),
`data/README.md`, `vendor/README.md`, `.claude/skills/*/SKILL.md`, `ui/**/*.md`,
and `Project Design.tldraw`. Read only. Nothing was edited.

## Headline

| Measure | Now | After the proposed cuts |
|---|---:|---:|
| Markdown lines in scope | 12,978 | about 4,600 |
| Markdown files in scope | 65 | about 43 |
| JSON receipts under `docs/` | 209 files, 7.0 MB | 23 files, about 4.4 MB |
| Docs no file references | 16 | 0 |
| Docs describing finished work | 17 | 0 |
| `TRAPS.md` | does not exist | exists, about 250 lines |

About 8,400 markdown lines and 186 JSON receipts (about 2.6 MB) can go. One
file carries most of it: `HANDOVER.md`, 5,987 lines of dated narrative whose
only live use is a single test docstring citing section 4.26.

The house rule this tree breaks hardest is "current state only, never history".
Seventeen documents are logs of finished campaigns. No `TRAPS.md` exists, so
the 38 hard-won traps among `CLAUDE.md`'s 62 Known Quirks entries sit there
instead, which is why a rules-and-commands file runs to 5,620 words with 86
percent of them under one heading. Five of those entries cite something that no
longer holds, which is what a 4,800-word section with no gate produces over
time. Section 9.1 has each one with its reproducing command.

## 1. Inventory

The `readers` column counts files under `src/`, `tests/`, `scripts/`,
`.github/`, `.claude/`, `docs/`, `static/`, `ui/src/`, `Makefile`, `CLAUDE.md`,
`architecture.md`, and `README.md` that name the file. Self-references and
`.claude/worktrees/` are excluded.

### Repo root

| File | Lines | Purpose | Done | Readers | Verdict | Lines removable |
|---|---:|---|---|---:|---|---:|
| `CLAUDE.md` | 124 | Rules, domain facts, gates, 60 traps | living | 85 | split into TRAPS.md and architecture.md | about 55 |
| `architecture.md` | 242 | Module map and ownership | living | 10 | keep, absorb the design entries | plus 20 |
| `README.md` | 63 | Product, run, verify | living | 8 | keep | 0 |
| `benchmarks.md` | 161 | Canonical perf numbers | living | 5 | keep | 0 |
| `HANDOVER.md` | 5,987 | 70 dated work-package logs | done | 2 | cut, lift section 4.26 into its test | 5,930 |
| `GOAL-0fails.md` | 87 | Drive the suite to 0 failed, 0 xfailed | done | 1 | cut | 87 |
| `DESIGN.md` | 37 | Scryglass design direction | superseded | 0 | cut, it contradicts design-language.md | 37 |
| `PRODUCT.md` | 58 | Users, purpose, principles | living | 0 | keep, link it from README | 0 |
| `Agents.md` | 5 | Pointer to CLAUDE.md and the skills | living | 0 | fold into README | 5 |
| `NOTICE.md` | 8 | Upstream licence notice | living | 1 | keep | 0 |
| `Project Design.tldraw` | binary, 33 KB | tldraw board, untouched since 2026-08-04 | unknown | 0 | cut | 33 KB |

### docs, live or generated

| File | Lines | Purpose | Done | Readers | Verdict | Lines removable |
|---|---:|---|---|---:|---|---:|
| `coverage-status.md` | 138 | Generated and gated coverage truth | living | 14 | keep, it is the one home | 0 |
| `scoreboard-autofill.md` | 110 | Scoreboard reader parts, how a read works | living | 2 | keep | 0 |
| `math-foundations.md` | 532 | The math identity behind every family | living | 150 | keep, strip the header | 8 |
| `ci-local.md` | 56 | Local CI, job for job | living | 1 | keep | 0 |
| `calculator-service.md` | 26 | Bearer-token service contract | living | 1 | keep | 0 |
| `issue-closure-policy.md` | 9 | Closure gate | living | 4 | keep | 0 |
| `full-wiki-entry-review-requirement.md` | 52 | Full-page review gate | living | 2 | keep | 0 |
| `wiki-refresh.md` | 59 | The `wiki-refresh` subcommand and its launchd job | living | 0 | keep, link it from the skill | 0 |
| `patch-day-runbook.md` | 423 | SLA, roles, steps 0 to 5, escalation | living | 7 | shrink, it repeats the skill | about 120 |
| `surface-area-backlog.md` | 21 rows | Open campaign residue, the one home | mostly done | 23 | shrink, 9 of 11 rows are closed | 9 rows |
| `database-schema.md` | 133 | Table shapes | living | 3 | keep | 0 |
| `beta-metrics.md` | 233 | Beta gate and endpoints | living | 7 | keep | 0 |
| `monitoring.md` | 126 | Five ops signals | living | 1 | merge into beta-operations.md | about 40 |
| `backup-runbook.md` | 122 | Backup and restore | living | 3 | keep | 0 |
| `beta-operations.md` | 37 | Weekly checklist | living | 4 | keep, absorb monitoring.md | 0 |
| `deploy.md` | 56 | Vercel baseline | living | 4 | keep | 0 |
| `deploy-runbook.md` | 169 | Managed infra and rollback | living | 4 | merge into deploy.md | about 70 |
| `invite-flow.md` | 115 | Invite issuance and the invitee path | living | 1 | shrink, the env table repeats deploy-runbook | about 25 |
| `onboarding-guide.md` | 115 | Five-minute user guide | living | 2 | shrink, it points at itself | about 20 |
| `patch-announcement-template.md` | 47 | Two post templates | living | 2 | keep | 0 |
| `item-source-reconciliation.md` | 80 | Four adjudicated source conflicts | closed | 3 | keep, it is the reason home | 0 |
| `rotation-design.md` | 277 | Event-order engine | living | 4 | keep, retitle it | about 10 |
| `redesign/design-language.md` | 78 | The 2a and 2b token system | living | 3 | keep | 0 |
| `redesign/gap-ledger.md` | 110 | Feature-to-home map, four decisions | living | 3 | keep | 0 |
| `redesign/README.md` | 22 | Folder index and provenance | living | 0 | shrink, the provenance is history | about 8 |
| `data/README.md` | 40 | Cache contract | living | n/a | keep | 0 |
| `vendor/README.md` | 22 | Vendored scraper layout | living | n/a | keep | 0 |
| `ui/README.md` | 45 | Shared React component | living | n/a | keep, fix the Node version | 0 |
| `ui/assets/league/README.md` | 38 | HUD atlas geometry | living | n/a | keep | 0 |

The raw grep credited `docs/redesign/README.md` with 8 readers. Those are
basename collisions with the other `README.md` files. Its true count is 0.

### docs, finished work

| File | Lines | Purpose | Done | Readers | Verdict | Lines removable |
|---|---:|---|---|---:|---|---:|
| `plans/2026-09-09-fight-navigability-modules.md` | 303 | Pre-split roster of 218 new modules | done | 0 | cut, 147 of 300 paths are gone | 303 |
| `roadmap-100.md` | 512 | Coverage close-out plan | done and stale | 3 | cut, keep a section 1.3 pointer | about 490 |
| `zero-residue-ledger.md` | 32 lines, 2,685 words | Iteration log, appended never rewritten | log | 0 | cut | 32 |
| `sightline-zero-campaign.md` | 36 | Phases 1 to 5, before and after counts | done | 0 | cut | 36 |
| `surface-area-resolution-results.md` | 26 | Per-row campaign outcomes | done | 0 | cut | 26 |
| `coverage-frontier.md` | 124 | Frontier at one campaign's merge head | superseded | 0 | move the axis tables into coverage-status.md | about 95 |
| `rotation-verification-gaps.md` | 66 | Gaps queued for a swarm that no longer exists | stale | 1 | move the rows into surface-area-backlog.md | about 50 |
| `monetization-design.md` | 209 | Monetization proposal | not built | 0 | cut, or shrink to a plan of 150 lines | 209 |
| `source-admission-issue-307-2026-09-08.md` | 74 | Five-champion source review | findings open | 0 | move the findings into the backlog | about 60 |
| `plans/2026-08-21-merge-202-followups.md` | 54 | Fourteen asides, all filed as issues | done | 1 | cut, the issues are the home | 54 |
| `plans/2026-09-02-issue-closeout-campaign.md` | 70 | Two waves, both merged | done | 0 | cut | 70 |
| `plans/2026-09-09-fight-navigability.md` | 93 | Sightline phase 5 plan | done | 5 | shrink to about 10 lines | 83 |
| `receipts/roadmap-closeout-verification-2026-08-21.md` | 167 | Closeout sweep | done and stale | 1 | cut | 167 |
| `receipts/golden-recapture-2026-08-21-slots17.md` | 30 | Batch L diff attribution | done | 0 | cut | 30 |
| `receipts/golden-recapture-2026-08-21-slots18.md` | 16 | Alistar R diff attribution | done | 1 | cut | 16 |
| `receipts/golden-recapture-2026-08-21-slots19.md` | 16 | Warwick E diff attribution | done | 0 | cut | 16 |
| `receipts/golden-recapture-2026-08-21-slots20.md` | 23 | Final dispositions attribution | done | 1 | cut | 23 |
| `receipts/self-shield-carrier-rebind-2026-08-21.md` | 60 | The rider re-bind rule | rule is live | 3 | keep, move it and drop the date | about 6 |

### Skills

| File | Lines | Purpose | Verdict | Lines removable |
|---|---:|---|---|---:|
| `add-champion/SKILL.md` | 88 | Add or update a champion module | keep | 0 |
| `add-item-effect/SKILL.md` | 275 | Add an item effect | keep | 0 |
| `atomizer/SKILL.md` | 57 | One atom contract | keep | 0 |
| `patch-update/SKILL.md` | 160 | Patch-day workflow | keep | 0 |
| `analyze-champion/SKILL.md` | 184 | Pre-implementation interview | keep | 0 |
| `analyze-champion/bug-history.md` | 208 lines, 6,104 words | Logged champion bugs | move into TRAPS.md | 208 |

`.agents/skills/README.md` sits outside the audited scope. It is two lines and
points at `.claude/skills/`, which is the right shape.

## 2. Cut: finished work with no reader

### HANDOVER.md, 5,987 lines

The file holds 95 sections. The 70 numbered work packages total 5,447 lines,
91 percent of the file, and every one carries the same date in its title.

Section 5, "Current worktree boundary", describes an uncommitted worktree from
2026-08-09 and asks the reader to preserve it. Quoting it: "The worktree is
shared and heavily dirty." Branch `main` is clean. The section lists files
"present as user-owned changes or additions" that have been committed for a
month.

Section 6, "Last validation evidence", pins `5533 passed, 7 xfailed`. The suite
now runs about 16,420 tests, per the last row of `docs/zero-residue-ledger.md`
dated 2026-09-18. The black line, `501 files would be left unchanged`, is a
snapshot of the same moment.

754 lines of the file carry an em dash, 12 percent of it. That is 64 percent of
the whole tracked-markdown em-dash debt that `CLAUDE.md` warns about.

One live use exists. `tests/test_eclipse_shield_selection.py` cites
"HANDOVER.md section 4.26" on line 3, "HANDOVER.md:1311" on line 18, and
"HANDOVER 4.26" on line 336, as the Eclipse shield and proc evidence. Section
4.26 runs 152 lines. Move the Eclipse numbers into that test's docstring, or
into a short `docs/receipts/eclipse-shield-certification.md`, then delete the
file.

Path rot is not the problem here. Only 11 of 241 path tokens have gone:
`docs/cp20-remaining-item-gaps.json`, `docs/deep-audit-2026-08.md`,
`data/bin/items.bin.json`, `tests/test_cp10_batch_07.py`, and six bare module
names. The problem is that the whole file is a diary.

### GOAL-0fails.md

The file records its own completion. Its last line reads: "Full suite:
`.venv/bin/pytest -q --tb=no` to 7688 passed, 0 failed, 0 xfailed, goal
condition met." It then keeps a "Progress" section with "Round 1", "Round 2 (in
progress)", and "Round 3". The baseline is dated 2026-08-12. Its one reader,
`tests/test_eclipse_shield_selection.py` line 13, cites it as grounds, and that
ground survives the file's deletion.

### docs/plans/2026-09-09-fight-navigability-modules.md

147 of its 300 backticked paths do not resolve. Each one names a module the
plan proposed and the split then renamed. Examples:
`src/calculator/keystone_ledger_walk.py`, `single_proc_on_hits.py`,
`stack_ledgers/account.py`, `damage_breakdown.py`, `shield_absorption.py`,
`survival/action_key.py`, `program/folds.py`, `coverage_claim_gate.py`,
`cast_order_request.py`, `src/result_cache.py`, `src/user_records.py`. The
file's own last paragraph records the drift: "75 modules shipped against these
67 rows." It also cites `sl_scratch/phase-27/modules.md` and `plan.md`, neither
of which is in the tree. No file references it.

### docs/roadmap-100.md, 512 lines, one table off by a factor of 29

Section 2.1, "Runtime coverage totals", reads `modeled 693`, `no_damage 23`,
`out_of_scope 149` at 17.2 percent, and concludes "Overall runtime coverage:
716/865 = 82.8%". The generated and gated `docs/coverage-status.md` reads
`771`, `89`, and `5`, which is 89.1 percent. The `out_of_scope` count is 5, not
149. Section 2.2, "92 of 173 champions carry at least one `out_of_scope` slot",
is wrong by the same measure. Section 2.3 cross-references "CLAUDE.md's
8-champion list" of degraded parses, and that list now has nine entries plus
Gnar.

All three citations of this file point at section 1 or 1.3, the `stats_only`
certification. That one fact already has four prose homes and two values:

| Home | Number |
|---|---|
| `docs/roadmap-100.md` sections 1.1 and 1.3 | 90 |
| `src/calculator/item_coverage.py` line 280 comment | 92 |
| `tests/test_stats_only_items.py` line 38 comment | "91-plus" |
| `tests/test_stats_only_items.py` line 71 docstring | "90, not the roadmap's 92" |

The test computes the live value. Keep a five-line pointer to
`tests/test_stats_only_items.py` and cut the rest.

Aside, outside this dimension: the comment at `item_coverage.py:280` is a stale
count in source.

### docs/zero-residue-ledger.md, a log that says it is a log

Its opening line reads: "One line per iteration of the zero-leftover-mechanics
campaign, appended never rewritten." Twelve timestamped rows hold 2,685 words
in 32 lines, each narrating what moved and why. No file references it.

Its four probes are worth keeping, as four lines in the "Where the remaining
work is written down" table of `docs/coverage-status.md`, which already holds
three of them. The rune split it tracks, 49 priced against 13 refused, is the
live number, and the ledger itself records that the "31 priced" in
`docs/coverage-frontier.md` is stale by 18.

### docs/sightline-zero-campaign.md and docs/surface-area-resolution-results.md

Both are phase tables of closed campaigns, and no file references either.
Resolution results opens with "Branch `surface-area-resolution`. Two waves of
isolated-worktree workers plus one consolidation pass". That branch is gone.
The same paragraph says residuals live in `docs/surface-area-backlog.md`, "the
one home", and traps went to `CLAUDE.md`, so the file is a pointer to two other
files. The sightline campaign's residue paragraph already appears in full in
the ruff and sightline entry of `CLAUDE.md` and in `.sightline-baseline`.

### The two plan docs for merge 202 and the issue closeout

The merge-202 plan states its own retirement rule: "each survivor filed as a
GitHub issue (the issue is the one home for detail; rows here are pointers).
Delete a row when it lands." Every row carries an issue number from #213 to
#230. The closeout campaign doc then records #216, #226, #228, #229, and #230
closed in wave 2, and #232, #233, #234, #236, and #263 closed in wave 1. Ten of
the fourteen rows landed and nobody deleted them. The merge-202 file also holds
a two-way "Coordination note" and "Reply", which is a chat log. The closeout
file's "Results" table holds PR numbers and merge SHAs, which is history.

### docs/receipts/roadmap-closeout-verification-2026-08-21.md

The file promises that "Every number below is computed live by the command
shown". It was, on 2026-08-21: `modeled 771`, `no_damage 88`, `out_of_scope 6`.
Today the tree reads `771`, `89`, `5`. Its section 1 blocker table lists six
slots where the tree has five, because Sivir R closed. The surviving five are
pinned in `tests/test_axis_less_slots.py`, which is the executable home for the
same fact.

### The four golden-recapture receipts

Each closes with the same sentence: "Recapture executed after this attribution;
compare re-verified identical." An attribution's job ends when the baseline is
captured. Files `slots17` and `slots19` have no reader at all. Files `slots18`
and `slots20` are named only inside other receipts. 85 lines in total.

### docs/monetization-design.md, 209 lines of unbuilt product

No file under `src/`, `tests/`, `scripts/`, or `.github/` references it. It
cites `docs/riot-compliance.md`, which does not exist and which the file itself
marks "to be written when". Under the house rule this is a plan, and plans run
to 150 lines. Cut it, or move it to a GitHub issue.

### DESIGN.md, a second and contradicting design system

`DESIGN.md` sits at the root, runs 37 lines, and no file references it.
`docs/redesign/design-language.md` runs 78 lines and
`tests/test_redesign_frontend.py` pins it. Both claim to be the visual system,
and they disagree on the type scale.

| Topic | `DESIGN.md` | `docs/redesign/design-language.md` |
|---|---|---|
| Surfaces | "restrained ivory paper and deep green proof panels" | rail `#0a1712` and canvas `#f6f2df`, with a full token table |
| Type scale | "a compact role scale rather than microprint: 12px metadata, 13px controls, 15px body" | "Micro-labels: 700 to 800, 9 to 10px" and "Body/controls: 11 to 13px. The UI is dense on purpose." |
| Motion | "150 to 210ms, state-driven" | not covered |

`PRODUCT.md` settles it: "The approved direction is one committed look ... 
`docs/redesign/design-language.md` is the written system and
`docs/redesign/target-2a.html` / `target-2b.html` are the pixel targets." So
`DESIGN.md` lost a settled decision. Cut it. Its motion and accessibility
paragraphs are its only unique content, and they belong in
`design-language.md`.

### Project Design.tldraw

A binary tldraw board, a zip holding `db.sqlite`, 33 KB, tracked, committed on
2026-08-04 under "chore: package accumulated calculator fixes", untouched
since, referenced by nothing. It is not readable in review and not diffable.

## 3. Merge: one fact, one home

### Deployment

`docs/deploy.md` runs 56 lines and `docs/deploy-runbook.md` runs 169. The
runbook opens by describing "the step-by-step path from 'code merged on
`codex/p0a-deploy`'". That remote branch belongs to an earlier era and nothing
ships from it. Both files carry the `SCRYGLASS_AUTH_REQUIRED`,
`SCRYGLASS_AUTH_SECRET`, and `SCRYGLASS_AUTH_USERS` block. Both tell the reader
to run the README gates before promoting. One home: `docs/deploy.md`, holding
the Vercel flow, the env table, the health check, and rollback. About 70 lines
go.

### Operations

`docs/beta-operations.md` item 3 says the restore path lives in
"`docs/deploy-runbook.md` sections 1 to 2". It does not. It lives in
`docs/backup-runbook.md`. That cross-reference has been wrong since it was
written, which is what happens when three files cover one surface.
`docs/monitoring.md` then restates in prose the four checks it already
tabulated, and hands DB recovery back to `backup-runbook.md`. One home:
`beta-operations.md` holds the weekly checklist and the five signals,
`backup-runbook.md` holds backup and restore, and `monitoring.md` folds into
the first.

### Coverage

`docs/coverage-frontier.md` disclaims itself in its own first line: "The live
numbers are in `coverage-status.md` ... the slot COUNTS here are that
snapshot's, and the labels have moved since." It then publishes 65 slots out of
scope against a live 5, and "Runes: 62 cached, 62 compiled, 31 priced" against
a live 49. A document that tells the reader not to trust its numbers should not
carry numbers.

Two assets in it are worth saving: the grouping of out-of-scope slots by axis,
and the table of rune refusals by axis. Move both into
`docs/coverage-status.md` as taxonomies with no counts, generated by
`scripts/coverage_status.py`, then delete the page. About 95 lines go.

### Rotation gaps

`docs/rotation-verification-gaps.md` says its entries "are queued for the F4
verification swarm". No such swarm exists. The open rows are real backlog
items: a charge-applier atom on Tristana E, the Caitlyn trap-to-Headshot link,
a `mark_detonate` atom on Kennen W, Volibear's self-consumed mark, Viego's
auto-consumed mark, Naafiri's recast consumer, Nidalee's Hunted mark, and
Illaoi's spirit and vessel. `docs/surface-area-backlog.md` is the declared one
home for "everything the campaigns surfaced and did not close". Move them there
as new rows.

### Source review

`docs/source-admission-issue-307-2026-09-08.md` reads as a source artifact but
its findings are open defects. It records that Gwen's "Current healing is 67%,
capped at 12 to 40 plus 7% AP; the module still uses 50%", that Gwen E's
"packet reads the attack-speed row as AP scaling", and that Azir W's "packet
flattens those axes incorrectly". No file references the document, so nobody
will find those. Move each finding to `surface-area-backlog.md` or a GitHub
issue. The JSON beside it keeps the evidence.

### Patch day

The split between `docs/patch-day-runbook.md` at 423 lines and
`.claude/skills/patch-update/SKILL.md` at 160 is stated and sound: the skill
covers what to do, the runbook covers the SLA, the roles, the per-subcommand
exit codes, and escalation. But steps 1 through 4 of the runbook restate the
skill's description of `run` and its triage rules. Keep the SLA, the roles, the
escalation checklists, and the exit-code table. Delete the repeated step
narration and point at the skill. About 120 lines go.

### The Node version

| Home | Says |
|---|---|
| `README.md` line 33 | "Node.js 24 is required" |
| `docs/ci-local.md` line 44 | "Node 24 or newer" |
| `.github/workflows/tests.yml` line 28 | `node-version: "24"` |
| `ui/README.md` line 21 | "Use Node 22.18 or later" |

`ui/package.json` carries no `engines` field, so no machine home exists at all.
Add `"engines": {"node": ">=24"}` to `ui/package.json` and have the three prose
sites point at it.

## 4. Shrink: live docs carrying dead weight

### docs/surface-area-backlog.md, 9 of 11 rows are closed

Its first paragraph states the rule: "Delete a row when its fix lands; this
file is the one home for the list."

| Row | Action column | Keep |
|---|---|---|
| CF11 | parser work parked for patch day | yes |
| ER5 | "Nothing outstanding." | no |
| SR1 | "CLOSED ... Nothing." | no |
| SR2 | "CLOSED by mounting ... Nothing." | no |
| SR3 | "CLOSED ... Nothing." | no |
| SR4 | "Source the field cap" | yes, trim to three lines |
| SR5 | "CLOSED ... Nothing." | no |
| SR6 | "CLOSED ... Nothing." | no |
| SR7 | "CLOSED for proc counts" | fold into SR8 |
| SR8 | "Source the two missing attack rates" | yes, trim |
| SR9 | "CLOSED ... Nothing." | no |

The file is 21 lines and 2,177 words, because each row is a paragraph-length
essay where a table row belongs. SR2 and SR4 each run past 400 words. Target
four rows and about 350 words. Note that `scripts/coverage_status.py` line 357
counts the rows and republishes the count into `docs/coverage-status.md`, so
regenerate after the trim.

### docs/plans/2026-09-09-fight-navigability.md, executed but cited for its reasons

Four source files cite it: `fight/autos/on_hit_layering.py` line 44,
`item_behavior.py` line 37, `item_behavior_catalog.py` line 29, and
`scripts/golden_snapshot.py` line 43. `docs/sightline-zero-campaign.md` cites
it too. The plan is fully executed. The `fight/` package, the per-fight trace,
and `scripts/extract_modules.py` all exist, and `architecture.md` describes
them.

What those four citations need is the list of sightline rule 27 leaves and the
reason each stays. `CLAUDE.md` already states that list in full, in its ruff
and sightline entry. Either shrink the plan to a note of about 10 lines, or
repoint the four comments at the `CLAUDE.md` or `TRAPS.md` entry and delete the
plan.

`scripts/prose_lint.py` already has a `pointer` rule for this exact shape,
described in its docstring as "prose citing a campaign document where the
reason itself belongs". It reports without failing. Promote it to failing once
the campaign docs are gone.

### docs/math-foundations.md, keep the body and cut the letterhead

150 source and test files cite this as the math home, so its 532 lines earn
their place. Lines 3 to 8 are a status block: "Branch:
`codex/p2-math-foundations` · Date: 2026-08-06". The branch is dead and the
date sits on a document of timeless identities. Its section 5 formula-audit
table and section 1.1 cite `damage.py` function names, among them
`_schedule_shared_casts`, `_navori_effective_cd`, `_mitigate_hits`, and
`_periodic_damage_events`, which moved into `fight/` during the navigability
split. They resolve by basename but no longer name their file.

The overlap with the domain knowledge in `CLAUDE.md` is larger than a formula
against its derivation, and it carries a live drift risk. Section 9.2 sets the
two texts side by side. Four of the eight `CLAUDE.md` domain bullets appear in
the section 5 formula-audit table of math-foundations in the same form, and
that table also names the owning function and the edge case, so it is the
better home. Worse, both files state the level cap of 20, which `CLAUDE.md`
itself marks "a seasonal rule, re-verify on patch day". A fact flagged as
volatile should not have two homes.

### docs/onboarding-guide.md points at itself

Line 4 reads: "This is the companion to the first-run overlay
(`docs/onboarding-guide.md`)". That pointer names the file the reader is
already in. The guide also describes the pre-redesign interface. The string "vs
practice target" appears nowhere in `templates/`, `static/js/`, or `ui/src/`,
and `docs/redesign/gap-ledger.md` already records that the overlay copy
"references removed Quick mode (stale even today)". Fix the pointer, re-walk
the four-click path against `/advanced`, and say that `/` is now the React
surface.

### docs/receipts/self-shield-carrier-rebind-2026-08-21.md, a rule in a receipt's clothes

`src/calculator/participant_timeline.py` line 4887 and
`tests/test_w2_sustain.py` line 327 both cite it. It documents live behaviour,
not a past event. Only its first two lines are history: "Status: closed (issue
#229). Landed 2026-09-02." Drop those, drop the date from the filename, and
move it to `docs/self-shield-rebinding.md`. Folding it into `architecture.md`
beside `shield_ledger.py` would work too.

### docs/redesign/README.md

The provenance paragraph is history. It names the design exploration, its turn
number, its date, and the discarded options. The file table is worth keeping.

### .claude/skills/analyze-champion/bug-history.md

208 lines and 6,104 words, opening with "When a user reports a bug or incorrect
behavior after a champion is implemented, log it here so future
`/analyze-champion` runs can catch the same pattern."

This is the repo's champion traps file under another name. Its entries are
exactly the shape a trap takes: "Empowers next basic attack = once per cast",
"verify the crit effectiveness ratio", "Always check every ability description
for %HP". It is good content in the wrong building. A skill directory is not a
traps home, and `CLAUDE.md` holds 60 traps that never see it. Move it to a
champion section of `TRAPS.md` and have the skill point there.

## 5. The JSON receipts under docs

209 files, 7.0 MB.

### Live and gated, keep, 13 files

`behavior-frontier.json`, `cast-dependency-audit.json`, `coverage-census.json`,
`coverage-residue.json`, `item-umbrella-audit.json`,
`wiki-full-entry-audit.json`, `receipts/campaign-fingerprints.json`,
`receipts/campaign-slice-tags.json`, `receipts/campaign-stages.json`,
`receipts/frontier-open-debts.json`, `receipts/internal-row-census.json`,
`receipts/item-coverage-classification.json`, and
`receipts/receipt-walk-retirement-schedule.json`. A script or a test reads each
one, and the documented regenerator ladder rewrites it.

### Live and single-purpose, keep, 5 files

`cp47-production-acceptance.json` for `test_mikael_packet.py` and
`test_redemption_packet.py`. `receipts/er5-tail-triage.json` for
`scripts/tail_site_triage.py`. `receipts/escalated-defects-cached-data.json`
for `scripts/patch_update.py`. `receipts/escalated-defects-P3-3.7.json` for
`akshan.py` and `test_champion_inputs.py`. `receipts/oracle-P3-3.8-leaf24.json`
for `test_coverage_reason_source_assertion.py`.

### expected-golden-diff receipts: 49 files, 980 KB, all vacuous

Measured this session through the tests' own functions:

```
standing coupled diffs:              0
standing pair diffs:                 0
claimed coupled paths in receipts:   2,992
claimed pair paths in receipts:      2,464
receipts with at least one live claimed path: none
```

`tests/test_coupled_golden_allowlist.py` predicts this in its own docstring:
"The predicate is a subset and not an equality, deliberately: it stays true
across the boundary re-capture that empties the difference set." The re-capture
has happened. Both pinned baselines are clean, so all 5,456 claimed paths are
claims against an empty set. The three tests that read the receipts pass by
emptiness. Only `test_the_allowlist_mechanism_has_receipts_to_read` would
notice if all 49 files vanished, and it asserts nothing beyond non-emptiness.

Two receipts still carry live content.

| Receipt | Live content |
|---|---|
| `expected-golden-diff-C6.json` | Two `coupled_exact` keys, plus membership asserted directly by `tests/test_golden_snapshot.py` line 1486 and by `tests/test_syndra.py` |
| `expected-golden-diff-slots18-alistar-r.json` | Eleven of the thirteen `coupled_exact` keys that `declared_exact_moves()` returns |

Cut 47, keep 2. About 940 KB. If the allowlist mechanism is worth keeping for
future slices, the two survivors demonstrate it and the next slice writes its
own.

### oracle-C6-leaf receipts: 139 files, 1.6 MB, 2 load-bearing

`tests/test_golden_snapshot.py` line 1389 globs `oracle-C6-*.json` and looks
for the receipt covering a scenario's `Q2` breakdown row. Measured:

```
receipts covering a Q2 breakdown row: 2
  oracle-C6-leaf5.json   syndra_custom_order_120  .../breakdown/Q2  old=<absent>
  oracle-C6-leaf74.json  syndra_custom_order_60   .../breakdown/Q2  old=<absent>
scenarios covered: syndra_custom_order_120 (69), syndra_custom_order_60 (69), one pair-engine note
```

137 files are opened and discarded on every run of that test. Each holds a
per-leaf adjudication of a slice that landed and whose baseline was re-captured
afterwards. Keep `leaf5` and `leaf74`, cut 137. About 1.58 MB.

### Orphans, cut, 3 files

`docs/manual-rank-sources.json`, which nothing reads.
`docs/source-admission-issue-307-2026-09-08.json`, which is evidence for the
markdown covered above. Keep it only if the findings become issues that cite
it. `docs/receipts/oracle-P4B-leaf29.json`, which nothing reads.

Receipt total: 186 of 209 files can go, about 2.6 MB. The 23 that stay hold
about 4.4 MB, nearly all of it `docs/coverage-census.json` and the other
generated receipts that a gate reads on every run.

The sixteen documents that no file references: `Agents.md`, `DESIGN.md`,
`PRODUCT.md`, `Project Design.tldraw`, `docs/coverage-frontier.md`,
`docs/monetization-design.md`, `docs/sightline-zero-campaign.md`,
`docs/source-admission-issue-307-2026-09-08.md`,
`docs/surface-area-resolution-results.md`, `docs/wiki-refresh.md`,
`docs/zero-residue-ledger.md`,
`docs/plans/2026-09-02-issue-closeout-campaign.md`,
`docs/plans/2026-09-09-fight-navigability-modules.md`,
`docs/receipts/golden-recapture-2026-08-21-slots17.md`,
`docs/receipts/golden-recapture-2026-08-21-slots19.md`, and
`docs/redesign/README.md`. Three of them describe current state and should stay
once something links them: `PRODUCT.md`, `docs/wiki-refresh.md`, and
`docs/redesign/README.md`.

## 6. Staleness ledger

Every backticked path in every in-scope markdown file was resolved against the
tree.

| Doc | Missing of total | Tokens |
|---|---|---|
| `docs/plans/2026-09-09-fight-navigability-modules.md` | 147 of 300 | see section 2 |
| `docs/patch-day-runbook.md` | 3 of 44 | `content-metadata.json`, `items.cdtb.bin.json`, `src/data/generated/merakiAbilityKits.ts` |
| `docs/roadmap-100.md` | 3 of 35 | `items.bin.json`, `items.cdtb.bin.json`, `timeline_optimizer.py` |
| `docs/plans/2026-09-09-fight-navigability.md` | 2 of 18 | `modules.md`, `sl_scratch/phase-27/modules.md` |
| `HANDOVER.md` | 2 of 81 backticked, 11 of 241 over all path tokens | `docs/cp20-remaining-item-gaps.json`, `docs/deep-audit-2026-08.md` |
| `architecture.md` | 1 of 205 | `scripts/sync-calculator-ui.mjs` |
| `docs/item-source-reconciliation.md` | 1 of 5 | `data/gamefiles/items.bin.json` |
| `docs/monetization-design.md` | 1 of 4 | `docs/riot-compliance.md`, declared "to be written" |
| The other 44 | 0 | none |

Line 210 of `architecture.md` says "Scryglass imports the reviewed source
through `scripts/sync-calculator-ui.mjs`". That file does not exist in this
repo. Only `ui/build.mjs` does. Either the script lives in the sibling
Scryglass repo, in which case say so, or the sentence is stale. It is the only
broken path in the repo's most-trusted document, so fix it on sight.

Numbers that no longer hold, in files whose paths all resolve:

| Doc | Claim | Live |
|---|---|---|
| `docs/roadmap-100.md` section 2.1 | 149 `out_of_scope` slots, 82.8 percent coverage | 5 slots, 89.1 percent |
| `docs/coverage-frontier.md` | 65 `out_of_scope`, 31 runes priced | 5, and 49 |
| `docs/receipts/roadmap-closeout-verification-2026-08-21.md` | 88 `no_damage`, 6 `out_of_scope` | 89, and 5 |
| `HANDOVER.md` section 6 | 5,533 tests passing | about 16,420 |
| `GOAL-0fails.md` | 7,688 passing, goal met | about 16,420 |
| `docs/deploy-runbook.md` | deploys from `codex/p0a-deploy` | `main` |
| `ui/README.md` | Node 22.18 | 24 everywhere else |

## 7. History and narrative prose

Sections whose subject is what changed rather than what is:

| Doc | The prose |
|---|---|
| `HANDOVER.md` | 70 numbered packages all dated 2026-08-09, "Wave 1", "Wave 2", "Pass-16 correction", "Current worktree boundary", "Last validation evidence" |
| `GOAL-0fails.md` | "Progress", "Round 1", "Round 2 (in progress)", "Round 3" |
| `docs/zero-residue-ledger.md` | Twelve rows stamped from `2026-09-16T20:55Z` to `2026-09-18T18:16Z`, "appended never rewritten" |
| `docs/sightline-zero-campaign.md` | "Findings per phase" with before and after counts, "Phase 3/4/5 residue" |
| `docs/surface-area-resolution-results.md` | "Two waves of isolated-worktree workers plus one consolidation pass" |
| `docs/plans/2026-09-02-issue-closeout-campaign.md` | "Results" with PR numbers and merge SHAs, "Two workers were sent back once" |
| `docs/plans/2026-08-21-merge-202-followups.md` | "Coordination note (2026-08-21...)" and "Reply (2026-08-22, merge-202 side)", a chat log |
| `docs/receipts/golden-recapture-*.md` | "Recapture executed after this attribution; compare re-verified identical", four times |
| `docs/roadmap-100.md` | "Status: FINAL (this pass supersedes the two capped-out prior attempts...)" |
| `docs/redesign/README.md` | "Discarded explorations (1a workspace tabs, 1b dark console, 1c standalone duel) intentionally omitted" |
| `docs/receipts/self-shield-carrier-rebind-2026-08-21.md` | "Status: closed (issue #229). Landed 2026-09-02." |
| `docs/math-foundations.md` | "Branch: `codex/p2-math-foundations` · Date: 2026-08-06" |
| `docs/surface-area-backlog.md` | Nine rows whose Action column reads "CLOSED ... Nothing." |
| `benchmarks.md` | The `@7bb9701e` rows, which the file declares and bounds: "A `@7bb9701e` row is history and is not gated." This is the only well-handled case in the tree. |

Em-dash debt: 1,183 lines across tracked markdown carry the character, and 754
of them sit in `HANDOVER.md`. Cutting that one file clears 64 percent of it.

One naming collision is worth fixing. `scripts/prose_lint.py` sets
`TARGETS = ("src", "scripts")` and never reads markdown. The plugin hook
`comment_lint.lint_prose` is what reads markdown. `CLAUDE.md` calls both "prose
lint", one under Commands and gates and one under Known Quirks, with nothing to
say they are different programs.

## 8. The proposed CLAUDE.md, TRAPS.md, architecture.md split

Today `CLAUDE.md` runs 124 lines and 5,620 words. About 4,200 of those words
are the Known Quirks paragraphs, three quarters of a file whose own first line
says "Module map and pipeline: see `architecture.md`". Every session pays that
cost. No `TRAPS.md` exists, though the user's global convention names it as the
per-repo home for hard-won findings, and Known Quirks is that file under
another name.

### Target shape

| File | Holds | Target |
|---|---|---|
| `CLAUDE.md` | The seven important rules, domain knowledge, commands and gates, and one pointer line to each of the other two files | 70 lines or fewer, 1,600 words or fewer |
| `TRAPS.md` | Every entry that is a gotcha, the thing that bit someone and will bite again, grouped by surface, one paragraph each | about 250 lines |
| `architecture.md` | Every entry that states an invariant or an ownership fact: which module owns what, which vocabulary is closed, which direction an import runs | 242 lines now, about 300 after |

### Grouping for TRAPS.md

Six sections, not one flat list of 40 paragraphs, so a reader greps the surface
they are standing on.

```
TRAPS.md
  Tests and CI           xdist shared state, src.app state bleed, concurrent src/ edits,
                         the pylint score gate, CI on a conflicting PR
  Goldens and receipts   the published zero's type, a zero row needing a detail,
                         compiled slot order, derived receipts, the exact-moves glob,
                         the regenerator order after a merge
  Engine and pricing     charge rechargeRate, slot_extract's -1 fallthrough,
                         ability_mr binding, the stun-only passive, deterministic crits,
                         literal-default reads
  Platform and tooling   sed and CRLF, sorted() over Path on Windows, the worktree base,
                         one .git across sessions, worktree lint false positives,
                         a resumed Bash task re-running its command
  Frontend and vision    the expando deopt, the Math.min and Math.max deopt, CSP and blob:,
                         the portrait floor, rescale rather than blame the browser,
                         yt-dlp download sections
  Champions              moved in from .claude/skills/analyze-champion/bug-history.md
```

### Which Known Quirks entries go where

Section 9 below holds the per-entry classification, with every cited symbol
checked against the tree.

### How to stop it growing back

The second time an instruction gets written it should become structure. Two
cheap ones fit here.

1. A test that fails when `CLAUDE.md` passes its word budget, in the shape
   `tests/test_p0b_ops.py` already uses to assert doc contents. The budget is
   what sends the next trap to `TRAPS.md` instead.
2. Promote the `pointer` rule in `scripts/prose_lint.py` from reporting to
   failing, once the campaign docs are gone. It already detects prose citing a
   campaign document where the reason belongs, which is the exact shape this
   audit had to find by hand.

## 9. Every Known Quirks entry, classified

`CLAUDE.md` holds 62 bullets under Known Quirks. Measured:

| Section | Words | Share |
|---|---:|---:|
| Preamble | 11 | 0.2% |
| Important Rules | 243 | 4.3% |
| Domain Knowledge | 178 | 3.2% |
| Commands and gates | 343 | 6.1% |
| Known Quirks | 4,845 | 86.2% |
| Total | 5,620 | |

Four verdicts. TRAP means a gotcha that bit someone and will bite again.
DESIGN means an invariant or an ownership fact. RULE means an instruction
about working in this repo. DATA means a list of open frontier items.

Every module, script, and test file named across the 62 entries exists. Five
entries cite something inside those files that does not hold. Section 9.1 lists
them with the command that shows each.

| # | Entry | Verdict | Goes to | Words | Note |
|---:|---|---|---|---:|---|
| 1 | Windows filenames, `download_soup` colon strip | TRAP | TRAPS, Platform | 16 | |
| 2 | Three things are named "champions" | DESIGN | architecture | 30 | It points at `vendor/README.md` and `data/README.md`, and both already say it. Reduce to one line. |
| 3 | Wiki parser `nvalues=None` crash patch | TRAP | TRAPS, Platform | 21 | |
| 4 | Known-degraded wiki parses | DATA | coverage-status, or backlog row CF11 | 168 | Line 43 of `docs/coverage-frontier.md` restates the same list. The Gnar clause is restated again in `src/calculator/champions/gnar.py` lines 59 to 60. Three homes. |
| 5 | Item names come from `data/items.json` | RULE | CLAUDE, Rules | 22 | |
| 6 | A published zero's type is load-bearing | TRAP | TRAPS, Goldens | 73 | |
| 7 | `receipt-walk-retirement-schedule.json` is derived | RULE | fold into entry 15 | 25 | Same statement as entry 15, different file. |
| 8 | Compiled slot order is Q,W,E,R,P | TRAP | TRAPS, Goldens | 25 | |
| 9 | `_threshold_regeneration_thresholds` stops the whole call | DESIGN | architecture | 17 | "intended since 5055dc5" is history. Drop the SHA. |
| 10 | `sed -i` in Git-Bash strips CRLF | TRAP | TRAPS, Platform | 16 | |
| 11 | Agent worktrees live under `.claude/worktrees/` | TRAP | TRAPS, Platform | 31 | |
| 12 | Agent worktrees fork from `main`'s tip | TRAP | TRAPS, Platform | 54 | |
| 13 | Parallel sessions share one `.git` | TRAP | TRAPS, Platform | 62 | |
| 14 | Crit rolls are random unless `deterministic` is set | TRAP | TRAPS, Engine | 49 | Section 0 of `docs/math-foundations.md` states the same rule, including that `/api/calculate` alone still rolls natural crits. |
| 15 | Derived receipts are regenerated, never hand-merged | RULE | CLAUDE, Commands | 49 | Absorbs entry 7. |
| 16 | `data/atoms/manifest.json` digests hash LF bytes | TRAP | TRAPS, Platform | 56 | Wrong on one clause: it calls the bins under `data/bin/characters` gitignored. They are tracked. See 9.1. |
| 17 | CI never runs while a PR is conflicting | TRAP | TRAPS, Tests and CI | 37 | |
| 18 | `DefenseSubject` reads options through an injected reader | DESIGN | architecture | 37 | |
| 19 | Regenerators after a merge, in order | RULE | CLAUDE, Commands | 42 | A command list, not a trap. |
| 20 | `sorted()` over `Path` folds case on Windows | TRAP | TRAPS, Platform | 38 | |
| 21 | A test that mutates shared state races `pytest -n auto` | TRAP | TRAPS, Tests and CI | 136 | |
| 22 | A test that leaves `src.app` state changed | TRAP | TRAPS, Tests and CI | 120 | |
| 23 | Full-suite runs are untrustworthy while `src/` is edited | TRAP | TRAPS, Tests and CI | 56 | Two of the three named tests do not use the cited API. See 9.1. |
| 24 | A stun-only passive cannot reach the event ledger | DESIGN | architecture | 79 | |
| 25 | A zero-damage row publishes only with a `detail` | TRAP | TRAPS, Goldens | 61 | Sibling of entry 6. Keep the two adjacent. |
| 26 | `slot_extract.extract_value` indexes a row's last value | TRAP | TRAPS, Engine | 49 | |
| 27 | `control_spec.CC_KIND_VOCABULARY` is the one vocabulary | DESIGN | architecture | 111 | The header comments of `src/calculator/control_spec.py` carry the same partitions and the wiki URL. |
| 28 | A one-ally packet is priced before its recipient | DESIGN | architecture | 77 | The leaf table of `architecture.md` already carries the fact, as "`ally_packet_recipient.py`, re-pricing a one-ally packet for the ally actually selected". |
| 29 | cProfile lies, and the optimizer benches cannot resolve a small win | TRAP | TRAPS, Engine | 116 | It repeats numbers `benchmarks.md` owns. Point at that file. |
| 30 | `golden_coupled_exact.json` is not a compare target | TRAP | TRAPS, Goldens | 39 | |
| 31 | The ruff suite is at zero, overrules in `pyproject.toml` | TRAP | TRAPS, Tooling | 135 | The three autofix cases are traps. The config location is a pointer. |
| 32 | The comment standard and sightline live in `pyproject.toml` | RULE, one **STALE** clause | CLAUDE, Commands | 282 | The largest bullet in the file. Its inventory of `.sightline-baseline` is wrong: no rule 54 or 35 row is in that file. See 9.1. `pyproject.toml` and `.sightline-baseline` are the machine homes, so reduce this to a pointer plus the baseline policy and the drift goes away. |
| 33 | A `sightline-ok` marker covers its own line | TRAP | TRAPS, Tooling | 56 | |
| 34 | `item_support_effects` loads 17 internal modules | DESIGN | architecture | 83 | |
| 35 | CI's pylint gate is a score | TRAP | TRAPS, Tests and CI | 73 | The duplicate `_percent_ratio` is real but the cited line numbers have moved. See 9.1. |
| 36 | Manaflow is one passive over five items | DESIGN | architecture | 162 | The docstring of `src/calculator/manaflow_ledger.py` is its title sentence. |
| 37 | The rune paths publish their compiler tables once | DESIGN | architecture | 86 | |
| 38 | Sightline rule 14 counts typed signatures only | TRAP | TRAPS, Tooling | 85 | |
| 39 | Sightline rule 11 normalizes names and literals | TRAP | TRAPS, Tooling | 130 | Both parenthetical files name where the helper is defined, not where the binding lives. See 9.1. Also: "217 findings to 216, 206 keys to 205" is a phase-3 measurement, and `.sightline-baseline` now holds 60 lines. Drop the counts. |
| 40 | A pure refactor leaves `git diff` on receipts empty | TRAP | TRAPS, Goldens | 44 | |
| 41 | Where a fight number comes from | RULE | CLAUDE, Commands | 128 | It is a command: `calculate_payload(trace=True)` and `scripts/fight_trace.py`. `architecture.md` already describes `fight/ledger/trace.py`. |
| 42 | A charge ability's `cooldown` is its `rechargeRate` | TRAP | TRAPS, Engine | 165 | The docstring of `src/calculator/champions/charge_cadence.py` states the same thing at greater length. Cut to two sentences and point there. |
| 43 | `count_damage_after_fight_end` is the one switch | DESIGN | architecture | 114 | |
| 44 | The rotation binds resistance before its own shred | DESIGN | architecture | 55 | |
| 45 | A module split is an assignment file | RULE | CLAUDE, Commands | 155 | How to run `scripts/extract_modules.py`, plus the fallout list. |
| 46 | `program/compile` read a raw with a literal default | TRAP | TRAPS, Goldens | 45 | |
| 47 | Parallel lint workers pass alone and fail together | TRAP | TRAPS, Tests and CI | 105 | |
| 48 | The walk mutates the `actions` list its caller passes | TRAP | TRAPS, Engine | 111 | |
| 49 | The hooks resolve per-file rules against the main checkout | TRAP | TRAPS, Platform | 67 | |
| 50 | The stop gate reads every changed `.md`, and a skill `description:` takes no colon | TRAP | TRAPS, Tooling | 109 | Two traps in one bullet. Split them. |
| 51 | A backgrounded Bash task re-runs its whole command | TRAP | TRAPS, Platform | 90 | |
| 52 | An expando property on a typed array deoptimizes V8 | TRAP | TRAPS, Frontend | 36 | |
| 53 | The scoreboard reader's floor is a 24px portrait | TRAP | TRAPS, Frontend | 32 | |
| 54 | A bad scoreboard read is the input's scale, not the browser | TRAP | TRAPS, Frontend | 89 | |
| 55 | `Math.min` and `Math.max` in the pixel loop cost 3x | TRAP | TRAPS, Frontend | 54 | |
| 56 | `yt-dlp --download-sections` stalls | TRAP | TRAPS, Frontend | 25 | |
| 57 | Probe the page under its real CSP | TRAP | TRAPS, Frontend | 89 | |
| 58 | A kit attack-speed grant walks the build's own ramp | DESIGN | architecture | 81 | |
| 59 | A champion on-hit is an `on_hit` entry, never a cast row | DESIGN | architecture | 84 | |
| 60 | Terminus's Juxtaposition pen is a champion stat | DESIGN | architecture | 118 | Lines 17 to 28 of `src/calculator/fight/resists.py` say the same thing in the `Resists` docstring. |
| 61 | The attack-speed window opens at the first cast | DESIGN | architecture | 188 | |
| 62 | A module-walked ledger is `timeline_event_model` | DESIGN | architecture | 54 | |

### 9.1 Five entries cite something that does not hold

Each was checked twice, once by me and once by a second reader, and each
command below reproduces the finding.

**Entry 32, the one stale claim.** It says `.sightline-baseline` holds
"#27 on both arms, #54 the damage-type switch (`DamageClass` owning its
resistance axis), and one #35 registry cycle". The file holds three rules and
neither 54 nor 35 is among them.

```
$ cut -d'|' -f1 .sightline-baseline | sort | uniq -c | sort -rn
     53 27
      3 14
      3 11
```

The CC-switch and registry-cycle deferrals were either cleared or never
written. A reader trusting this bullet would look for a baseline row that is
not there.

**Entry 23, two of three tests use a different API.** The bullet says
`test_trigger_stream`, `test_import_namespace` and `test_gate_receipt` "pin
`inspect.getsource(...)`". Only the first does.

```
tests/test_trigger_stream.py      getsource:1  read_text:8
tests/test_import_namespace.py    getsource:0  read_text:3
tests/test_gate_receipt.py        getsource:0  read_text:2
```

The trap survives, because `Path.read_text` reads from disk while imports hold
the old module, which is the same hazard. Name the hazard, not the API.

**Entry 35, moved line numbers.** The bullet says
`rune_parser._percent_ratio` "is defined at 982 and again at 1544".

```
$ grep -n "def _percent_ratio" src/calculator/rune_parser.py
1088:def _percent_ratio(value: str) -> float:
1650:def _percent_ratio(raw: str) -> float:
```

The duplicate definition is real and the `E0102` it causes is real. The line
numbers are two edits behind. A line number in prose is a fact with a short
shelf life. Cite the symbol and let `grep` find it.

**Entry 16, the bins are tracked, not gitignored.** The bullet says the
champions domain "needs the gitignored CommunityDragon bins under
`data/bin/characters`". 183 files there are tracked, and `.gitignore` says so
in its own comment:

```
.gitignore:38: # data/bin: decomposed game binaries. The per-champion dumps are TRACKED
.gitignore:41: data/bin/*
.gitignore:42: !data/bin/characters
.gitignore:43: data/bin/characters/*
.gitignore:44: !data/bin/characters/*.bin.json
```

`git check-ignore data/bin/characters/gnar.bin.json` matches nothing. The rest
of the entry, about LF digests against a CRLF checkout, holds.

**Entry 39, both parentheticals name the wrong file.** The bullet cites
`main = partial(write_or_check, ...)` as "(`scripts/generated_file.py`)" and
`_required = partial(required_field, ...)` as "(`event_row_field.py`)". Those
two files define `write_or_check` and `required_field`. The bindings the
sentence quotes live elsewhere:

```
scripts/certify_damage_casts.py:134: main = partial(
scripts/coverage_status.py:631:      main = partial(
src/calculator/cast_event_row.py:48:  _required = partial(required_field, kind="cast event", ...)
src/calculator/damage_event_row.py:51: _required = partial(
```

A reader following the citation greps the named file for the quoted line and
finds nothing. Name both ends: the helper's home and one call site.

**Entry 42, two numbers for one measurement.** The bullet says pricing the
short timer "put 11 Electro Harpoons in a 10 s fight". The docstring of
`src/calculator/champions/charge_cadence.py` line 8 says the same defect
produced "16 basic-ability casts in a ten-second fight". The two may be
counting different things, Harpoons against all basic-ability casts, but
nothing in either text says so. Reconcile them, and keep one.

### 9.2 Domain Knowledge against math-foundations section 5

`CLAUDE.md` holds eight domain bullets in 178 words. Five are already stated in
`docs/math-foundations.md`, four of them in the section 5 formula-audit table,
which also names the owning function and the edge case.

| Fact | `CLAUDE.md` | `docs/math-foundations.md` |
|---|---|---|
| Stat growth | `base + growth × (level - 1) × (0.7025 + 0.0175 × (level - 1))` | section 5: `base + growth·(L−1)·(0.7025 + 0.0175·(L−1))`, under `growth_stat`, with "Level cap 20 (top lane)" |
| Attack speed | `base_AS + AS_ratio × (bonus_percent / 100)` | section 5: `base_AS + AS_ratio·bonus/100`, under `calculate_attack_speed` |
| Ability haste | `effective_cd = base_cd × 100 / (100 + ability_haste)` | section 5: `cd' = cd·100/(100+AH)`, under `effective_cooldown` |
| Resistance math | `actual_damage = raw × 100 / (100 + resistance)`, negative resistance amplifies | sections 2.1 and 5: `m(R)=100/(100+R)`, with the negative branch written out as `2−100/(100−R)` |
| Penetration order | percent before flat, floor at 0 | section 2.2, same order and floor |
| Level cap 20 | "a seasonal rule, re-verify on patch day" | section 5: "Level cap 20 (top lane)" |
| Crit base 200% | stated | not stated |
| Lethality 1:1, no level scaling | stated | not stated |
| True damage ignores resistances | stated | not stated |

Recommendation: `CLAUDE.md` keeps the three facts math-foundations does not
state, plus one line pointing at the section 5 table for the rest. That drops
about 110 words and, more usefully, leaves the seasonal level cap with one
home. Under the existing rules 5 and 6, a number with two prose homes is the
shape the repo already refuses in code.

### 9.3 Totals by verdict

| Verdict | Entries | Words | Destination |
|---|---:|---:|---|
| TRAP | 38 | about 2,595 | `TRAPS.md` |
| DESIGN | 16 | about 1,376 | `architecture.md` |
| RULE | 7 | about 703 | `CLAUDE.md`, Rules and Commands |
| DATA | 1 | 168 | `docs/coverage-status.md` or the backlog |

Entry 32 counts as RULE. One clause inside it is stale, not the whole entry.

### Size target

After the split `CLAUDE.md` carries the 775 words of rules, domain knowledge,
and commands, plus about 700 words of absorbed rules, plus three pointer lines.
That is about 1,500 words and 65 lines, down from 5,620 words and 124 lines.
`architecture.md` grows from 5,779 words to about 7,150. `TRAPS.md` starts at
about 2,600 words in six sections, plus the champion section moved in from
`.claude/skills/analyze-champion/bug-history.md`.

### Entries that narrate instead of state

- Entry 9 says a behaviour is "intended since 5055dc5". That commit is
  `refactor(item_effects): the registry fails closed`, dated 2026-08-20. Git
  carries the history. Say the behaviour is intended and stop.
- Entry 39 reports "217 findings to 216, 206 keys to 205". Those are phase-3
  measurements, and `.sightline-baseline` holds 60 lines today. The rule
  survives without them: expect an anchor swap, not a rise, when a leaf
  extraction lands.
- Entry 4's champion list has drifted out of step with the same list in
  `docs/coverage-frontier.md`. Generate it, or keep it in one file.

### Eight entries already have a home elsewhere

In each case the other copy is at least as complete. `scripts/prose_lint.py`
caps a docstring at the length of its body, so where the second home is a
docstring it is also the terse one, which makes the `CLAUDE.md` copy the
redundant side.

| Entry | Second home | Kind |
|---|---|---|
| 4, Gnar Mega constants | `src/calculator/champions/gnar.py` lines 59 to 60 | comment |
| 4, degraded-parse list | `docs/coverage-frontier.md` line 43 | doc |
| 14, deterministic crits | `docs/math-foundations.md` section 0 | doc |
| 27, CC vocabulary | header comments of `src/calculator/control_spec.py`, with the wiki URL | comment |
| 28, one-ally packet | the leaf table of `architecture.md` | doc |
| 36, Manaflow | the leaf table of `architecture.md`, and the docstring of `src/calculator/manaflow_ledger.py` | both |
| 41, where a number comes from | the combat-model and public-boundary sections of `architecture.md` | doc |
| 42, charge cadence | `src/calculator/champions/charge_cadence.py` lines 1 to 23 | docstring |
| 60, Terminus pen | `src/calculator/fight/resists.py` lines 17 to 28 | docstring |

Entries 15 and 19 also restate each other: both say derived receipts are
regenerated rather than hand-edited, over an overlapping script list.

Each of these should keep one sentence in `TRAPS.md` or `architecture.md` and
point at the other home for the rest.

