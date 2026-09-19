# Cross-cutting residue audit

Scope: the whole tree, 2,649 tracked files, minus `vendor/`. Read-only. Every count
comes from a script under `.audit/` (`cc1_archaeology.py`, `cc1b_narrative.py`,
`cc1c_where.py`, `cc2_naming.py`, `cc2b_names.py`, `cc3_gates.py`, `cc3b_lists.py`,
`cc4_suppress.py`, `cc5_leftovers.py`, `cc6_clones.py`, `cc8_receipts.py`,
`cc9_frontend.py`, `cc10_style.py`) and re-runs.

This tree is clean on the classic slop axes. It has 3 TODOs, no debug `print(` or
`console.log` in shipped code, no tracked build artefacts, no conflict markers,
consistent line endings, and no duplicate function bodies in `src/`. The residue sits
in three other places: narrative archaeology in prose, evidence corpora nothing reads,
and copy-pasted champion tests.

## Category table

| # | Category | Count | Cost | Proposal |
|---|---|---|---|---|
| 1 | Campaign and issue archaeology | 2,233 markers in 495 `.py` files: 1,421 docstring, 603 comment, 209 code. 69 test files named after a campaign | Each marker points at nothing. "Phase 4 S7's fourth authority move" is not greppable | Lint: a campaign token in prose must sit beside a path that exists. Rename the 69 test files by subject |
| 2 | One concept, many spellings | Refusal: 11 spellings, 20 files use 5 or more. `catalog` 55 vs `catalogue` 10. Provenance: 6 spellings | A reader cannot tell a synonym from a distinction. `Withheld` and `Starved` are types. `refused`, `denied`, `declined`, `blocked` are not | Give the refusal words one owner in `quantity.py`. Ban the rest by lint |
| 3 | Multiple homes for one fact | Gate list in 5 homes. Python version in 4 homes with one live divergence. 206 hand-listed constants, 4,696 entries. `ER5_TAIL` is provably derivable | A gate edit must land in 5 files or CI and `make ci-full` disagree silently | Generate `ci/*.sh` from `tests.yml`. Derive `ER5_TAIL`. Single-source the Python version |
| 4 | Suppression markers | 243 `pylint: disable`, 100 `type: ignore`, 53 `noqa`, 25 `pragma: no cover`, 18 `sightline-ok`, 9 real `xfail`, 52 `pytest.skip` | 163 of 243 pylint disables are arity and locals, the same shape sightline #23 and #55 already own | Fix the one cause behind 53 `type: ignore`. Pick one owner for arity. Leave the rest, they carry reasons |
| 5 | Leftovers | 3 TODO, 0 debug prints, 0 artefacts, 0 conflict markers, clean line endings. 194 absolute machine paths in tracked receipts | A committed `C:/Users/skywa/AppData/Local/Temp/claude/...` can never be reproduced | Strip scratch paths when a receipt is written. One lint over tracked JSON |
| 6 | Duplicate logic | 147 clone groups, 290 redundant copies, all inside `tests/`. Zero in `src/` or `scripts/`. 621 test functions whose name repeats in 5 or more files | 354 copies of three contract checks across 131, 118 and 105 champion test files | Parametrize the three checks over the champion registry. Delete about 350 function bodies |
| 7 | Config and tooling sprawl | 10 quality tools, 5 CI jobs on 8 runners, 35 global ruff ignores plus 22 per-file, `.sightline-baseline` 59 entries of which 53 are rule #27 | Small and well reasoned. The cost is drift: CLAUDE.md describes baseline entries the file does not hold | Derive the CLAUDE.md sentence from the file, or drop the detail |
| 8 | Data and receipt surface | 41.2 MB tracked JSON. `data/atoms/v2` is 166 files, 9.2 MB, 537,810 lines, no generator, 1 reader. `docs/receipts/oracle-*.json` is 141 files, 1.6 MB, 2 consulted. `data/item-atoms` is 325 files, documented as retired | About 12 MB of the repo is evidence nothing reads. Clone, checkout and grep all pay | Delete `data/item-atoms` and `data/atoms/v2`. Keep the 2 oracle leaves a test names |
| 9 | Frontend | `escapeHtml` duplicated verbatim twice. `render` in 3 files. 216 lines of inline `<style>` across 5 templates. 64 genuinely dead CSS classes | Two HTML escapers can drift apart | Extract `static/js/shared.js`. Move inline styles into `style.css` |
| 10 | Many agents, no editor | `HANDOVER.md` is 5,986 lines at the root and a test docstring cites `HANDOVER.md:1311`. `GOAL-0fails.md` is obsolete. 35 of 44 spent codemod inputs. 100 modules with docstrings over 40 lines | A test names a line number in a 6,000-line append-only log as its source of truth | Move HANDOVER and GOAL to `docs/archive/`. Quote the Eclipse sentence inside the test |

Ranked by payoff: 8, 6, 3, 1, 10, 2, 9, 4, 5, 7.

## 1. Campaign and issue archaeology

`.audit/cc1c_where.py` finds 2,233 campaign and issue markers across 495 Python files.

| Location | Hits | src | tests | scripts |
|---|---|---|---|---|
| docstring | 1,421 | 367 | 945 | 109 |
| comment | 603 | 209 | 348 | 46 |
| code or string | 209 | 53 | 92 | 64 |

By token, over the whole tree excluding `data/` and `vendor/`: `campaign` 445 hits in
167 files, `Phase N` 298 in 106, `issue #NNN` 142 in 94, `CP10.x` 97 in 86, "the
campaign's" 87 in 63, "this campaign exists to" 27 in 27, "the incident" 43 in 27,
`runbook R-NN` 22 in 20.

### What is load-bearing

Three markers resolve to something real.

- `docs/receipts/campaign-stages.json`, `campaign-slice-tags.json` and
  `campaign-fingerprints.json` are files that `scripts/behavior_frontier.py` reads at
  lines 655 and 662, and `scripts/golden_snapshot.py` reads at line 103.
- `ER5_TAIL` and `ROOTS` in `tests/test_literal_defaults.py` are real identifiers.
- `issue #NNN` where the issue is still open on the remote.

Everything else is narrative. Samples:

- `src/calculator/ability_spec.py:125`: "this campaign exists to remove."
- `src/calculator/item_behavior_catalog.py:2340`: "which is the shape this campaign
  exists to end.  Phase 4 corrects it."
- `src/calculator/trigger_stream.py:1465`: "Hypershot is Phase 4 S7's canary: the
  first of the seven authority moves"
- `src/calculator/champions/kayle.py:1`: "Kayle, full-entry reviewed CP10.3 module."
  86 champion modules carry a `CP10.x` stamp, and nothing in the tree defines `CP10.x`.

31 modules under `src/`, across 58 lines, reference a "Phase N" that no file defines.

### File names

69 test files are named after a campaign rather than a subject:
`test_e1_healing_b1.py` through `b6`, `test_e2_dot_1` through `_3`,
`test_e3_stacks_1` through `_3`, `test_e5_fix_1` through `_3`, `test_e9_fix_1` through
`_3`, `test_batch46_binary_roots.py` through `test_batch52_binary_roots.py`,
`test_p0a_deploy.py` through `test_p7_validation.py`, `test_wave2_stat_buffs.py`,
`test_cp20_items.py`, and `test_issue_137/142/143/158/159/162.py`. Somebody looking
for the DoT contract tests will not find `test_e2_dot_2.py`.

### The worst instance

`tests/test_eclipse_shield_selection.py` names `HANDOVER.md` section 4.26 at line 3
and `HANDOVER.md:1311` at line 18 as the test's source of truth. Line 182 of the same
file carries a `MERGE-TODO(interpreters)` that is an unfiled debt.

### Proposal

Rule: a campaign or issue token in a docstring or comment must be either a path that
exists, or `issue #N` for an open issue. Otherwise the sentence states the fact, not
the campaign that produced it.

Lint: about 30 lines added to `scripts/prose_lint.py`, which already walks every
docstring. Match `Phase \d|campaign|CP\d+\.\d|R-\d+|S\dH\d|E\d-\d` in docstrings and
comments under `src/` and `scripts/`, and allow a hit only when the same line holds a
path that resolves. Ratchet from today's count so it can only fall.

Codemod: rename the 69 test files by subject. A `git mv` plus a grep repoint covers it.

## 2. One concept, many spellings

Measured over defined Python names in `.audit/cc2b_names.py`, 31,158 definitions,
rather than prose. Names are what a reader has to learn.

### Refusal

Eleven spellings. Two are types. Nine are free prose.

| Spelling | Distinct names | Typed |
|---|---|---|
| `refused` | 141 | no |
| `withheld` | 61 | yes, `quantity.Withheld` |
| `blocked` | 45 | no, and also real CC vocabulary |
| `refusal` | 41 | no |
| `excluded` | 35 | no, and also real for exclusion lists |
| `denied` | 31 | no |
| `starved` | 16 | yes, `quantity.Starved` |
| `unavailable` | 16 | no |
| `refuse` | 11 | no |
| `withhold` | 3 | no |
| `declined` | 1 | no |

20 modules use 5 or more. The worst mixers are `tests/test_trigger_stream.py` with 7,
`src/calculator/participant_timeline.py` with 7, `src/calculator/item_coverage.py`
with 7, `src/calculator/survival/transitions.py` with 6,
`src/calculator/item_behavior_catalog.py` with 6, and `scripts/golden_snapshot.py`
with 6. `src/calculator/quantity.py` itself uses 5.

This is the costliest split in the tree, because the whole design rests on failing
closed with a named reason, and the reason has six names.

### Provenance

`receipt` 451, `audit` 56, `evidence` 46, `provenance` 9, `citation` 5, `source_ref`
5, `SourceRef` 1. `receipt` has won. The stragglers are islands in
`coverage_evidence.py`, `value_source_receipt.py`, and `_routing_provenance`.

### Collections

`catalog` 55 against `catalogue` 10. Every `catalogue` sits in the atomizer:
`atomize_item_catalogue`, `atomize_rune_catalogue`, `catalogue_champions`. One rename.

### Unit

`row` 575, `packet` 306, `event` 232, `entry` 192, `atom` 126, `record` 70, `leaf` 45.
These are mostly real pipeline stages, and architecture.md documents the path from
`PairEvent` through routing to a breakdown row. `record`, at 70, is the one with no
documented stage.

### Ally

`holder` 192, `ally` 139, `recipient` 27, `teammate` 13, `allies` 12, `wearer` 1.
`holder` and `wearer` are synonyms, so are `ally` and `teammate`. `recipient` is a
real distinction, owned by `ally_packet_recipient.py`. Two files use 10 or more of the
12 role words.

### Proposal

Give the refusal vocabulary one owner. Add `Refused`, `Denied` and `Blocked` to
`quantity.py` as types or documented aliases of `Withheld`, then add a
`scripts/prose_lint.py` rule: outside `quantity.py` and `control_spec.py` the refusal
words are `withheld`, `starved` and `refusal`.

Codemod `catalogue` to `catalog`, `teammate` to `ally`, `wearer` to `holder`, and
`record` to `row`. All four are safe, since none crosses a public API.

## 3. Multiple homes for one fact

### Gate commands live in five homes

Every gate invocation is hand-typed in five places.

1. `.github/workflows/tests.yml`
2. `ci/static.sh`, `ci/test.sh`, `ci/fast.sh`, `ci/coverage_census.sh`,
   `ci/shared_ui.sh`, `ci/container.sh`, each headed "Local equivalent of tests.yml
   job", each re-typing the command
3. `Makefile`, both the target names and the usage comment listing them
4. `docs/ci-local.md`, the mapping
5. `CLAUDE.md`, the "Commands and gates" block

`ci/static.sh:27` and `.github/workflows/tests.yml:120` both spell
`pylint src/ --jobs=0 --fail-under=9 --fail-on=E0601,E0602`, and both carry the same
justifying comment above them. Nothing checks that the five agree.

`.audit/cc3_gates.py` cross-checks the 16 CLAUDE.md commands against every home:

| Command | tests.yml | ci/*.sh | A test |
|---|---|---|---|
| pytest, black, pylint | yes | yes | yes |
| `golden_snapshot.py compare` | yes | yes | yes |
| `coverage_census.py check` | yes | yes | no |
| `prose_lint.py` | no | no | `tests/test_prose_lint.py` |
| `swing_stream_audit.py` | no | no | `tests/test_swing_stream_audit.py` |
| `certify_damage_casts.py --check` | no | no | `tests/test_combat_events.py` |
| `coverage_status.py --check` | no | no | `tests/test_app.py` |
| `build_icon_sprite.py --check` | no | no | `tests/test_scoreboard_vision.py` |
| `bench_request.py --compare` | no | no | no |

Seven of the sixteen reach CI only through a test. That is fine, but CLAUDE.md
presents them as commands to run, so a contributor runs nine gates by hand that
`pytest` already covers.

### Python version, one live divergence

| Home | Value |
|---|---|
| `.python-version` | 3.14 |
| `.github/workflows/tests.yml`, three jobs | "3.14" |
| `pyproject.toml` | unset on purpose, comment says "The project runs 3.14 (Dockerfile, CI)" |
| `Dockerfile:6` | `python:3.15.0rc2-slim` |

The production image runs a release candidate of the next minor while every test runs
3.14. The `pyproject.toml` comment asserting the Dockerfile runs 3.14 is false. This
is off-task for a slop audit, but it is a real deploy risk and worth flagging.

### Hand-maintained selection lists

206 module-level literal string collections of 8 or more entries, 4,696 entries total:
128 in `src`, 57 in `tests`, 21 in `scripts`. The largest:

| Entries | Name | File |
|---|---|---|
| 257 | `_ROTATION_CLASSIFICATIONS` | `src/calculator/champions/__init__.py:579` |
| 173 | `_CHAMPION_MODULES` | `src/calculator/champions/__init__.py:197` |
| 133 | `_REFERENCE_ITEM_EFFECTS` | `src/calculator/item_effects.py:2043` |
| 122 | `FULL_ENTRY` | `tests/test_full_entry_packets.py:26` |
| 97 | `ROOTS` | `tests/test_literal_defaults.py:2104` |
| 89 | `ER5_TAIL` | `tests/test_literal_defaults.py:2220` |
| 45 | `FIGHT_STEPS_WITHOUT_A_FRONT_DOOR` | `tests/test_architecture.py:86` |

`ER5_TAIL` is fully derivable, and this is measured rather than assumed.
`src/calculator` holds 512 `.py` files. `ROOTS` covers 423 of them. The remainder is
89 files. `ER5_TAIL` lists exactly those 89, with nothing in one set and not the
other.

Its own docstring says "This tuple is a record, not a setting. A module leaves it by
joining `ROOTS`; adding one back is undoing finished work, and the test below exists
so that undoing it cannot be done by deletion alone." The ratchet only needs a count
or a committed derived receipt, not 89 hand-typed names:

```python
ER5_TAIL = tuple(sorted(_all_calculator_modules() - _covered_by(ROOTS)))
```

with a pinned length that may only fall. That removes 89 maintained lines and one
class of merge conflict. `scripts/extract_modules.py` already lists
"`test_literal_defaults` ROOTS/ER5_TAIL rows" among the fallout it cannot pay.

`_CHAMPION_MODULES` at 173 entries is defensible, because CLAUDE.md rule 7 wants an
unknown attacker to fail closed. It could still be
`sorted(p.stem for p in CHAMPIONS_DIR.glob("*.py"))` with `module_contract` validation
as the gate, which is the fail-closed property that matters.
`FRONT_DOOR_FRONTIER` and `EVIDENCE_HOMES` are small and genuinely declarative. Leave
them.

### Proposal

Generate `ci/*.sh` from `tests.yml`, about 60 lines plus a `--check` mode, or delete
`ci/*.sh` and have the Makefile call `act`. Pass `.python-version` into the Dockerfile
as a build arg. Derive `ER5_TAIL`.

## 4. Suppression markers

| Marker | Total | src | tests | scripts |
|---|---|---|---|---|
| `pylint: disable` | 243 | 153 | 65 | 25 |
| `type: ignore` | 100 | 8 | 90 | 2 |
| `noqa` | 53 | 10 | 28 | 15 |
| `pytest.skip(` | 52 | 0 | 52 | 0 |
| `pragma: no cover` | 25 | 6 | 15 | 4 |
| `sightline-ok` | 18 | 11 | 5 | 1 |
| `skipif` | 10 | 0 | 10 | 0 |
| `pytest.mark.skip` | 7 | 0 | 7 | 0 |
| `xfail`, real markers | 9 | 0 | 9 | 0 |
| `eslint-disable` | 2 | 0 | 0 | 0 |

By rule. `pylint: disable` breaks down as `too-many-arguments` 93,
`too-many-positional-arguments` 70, `unused-argument` 67, `too-many-locals` 48,
`import-outside-toplevel` 24, `too-few-public-methods` 19, `protected-access` 16 plus
`W0212` 13. `type: ignore` is `arg-type` 75, `misc` 8, everything else 4 or fewer.

### One cause behind 53 markers

53 of the 75 `arg-type` ignores sit on a subscript of a cached dict. From
`tests/test_interp_charged_strike.py:139`:

```python
base = float(entry["base_melee"])  # type: ignore[arg-type]
```

The cause is `ITEM_EFFECTS: dict[str, dict[str, Any]]` at `item_effects.py:4053`,
with siblings at lines 650, 2043 and 3986. That is a `dict[str, Any]` where rule 5
promises typed accessors. One typed accessor removes 53 markers. They concentrate in
six files: `test_interp_charged_strike.py` 14, `test_interp_periodic.py` 12,
`test_interp_cast_proc.py` 11, `test_interp_spellblade.py` 8,
`test_interp_active_cast.py` 6, `test_interp_on_hit_strike.py` 4.

### One unarbitrated overlap

163 disables are arity and locals. `pyproject.toml` already turns off ruff's
`PLR0913` and `PLR0915` with the reason "sightline #23 prices complexity and #55
arity; one owner per fact." Pylint is then silenced 163 times inline about the same
thing. Pick one owner and drop the other set of markers.

### What is legitimate

`unused-argument`, 67, sits on contract-shaped signatures, and `pyproject.toml`
already reasons the same exemption for ruff's `ARG00x`. All 18 `sightline-ok` markers
carry a reason. All 53 `noqa` carry a rule code. Only 9 real `xfail` markers exist,
and `tests/coverage_resolver.py:605` actively forbids skip and xfail, which is why
most of the 207 `xfail` word hits are policy prose. This is good discipline, not slop.

### Worth a look

52 `pytest.skip(` calls. The common reasons are
"local <champion> game-file evidence is unavailable", 13 times across Ashe, Gnar,
Renata and Aurelion Sol, "{_BIN_PATH} absent (gitignored local game-file cache)" 4
times, and "node is not installed" 12 times. These tests run neither in CI nor on a
fresh clone. They are not slop, but they are not coverage either, and
`docs/coverage-status.md` should not count them.

## 5. Leftovers

### Clean

3 TODO tree-wide, 0 FIXME, 0 XXX, 0 HACK. No `print(` debugging in `src/`. No
`console.log` in shipped JavaScript: the 6 hits are in `tests/js/*harness.mjs`, where
stdout is the protocol, and in `ui/build.mjs`. No tracked `*.pyc`, `*.orig`, `*.rej`,
`*~`, `.DS_Store` or `Thumbs.db`. No conflict markers. No two tracked files over 2 KB
share a checksum.

The three TODOs:

- `src/app.py:1940`, `TODO(cross-group): point docs/beta-metrics.md at src/metrics.py`
- `tests/test_eclipse_shield_selection.py:182`, `MERGE-TODO(interpreters)`
- `tests/test_gate_receipt.py:241`, which references the issue #139 TODO as closed

### Line endings

Clean. 2,421 files are `i/lf w/crlf`, correct under `autocrlf=true`. 190 are binary,
33 are `-text`. Four are forced LF: `.sightline-baseline` through `.gitattributes`,
plus `scripts/generated_file.py`, `src/calculator/event_row_field.py` and
`tests/test_event_row_field.py`, which have no attribute and are LF by accident. One
file is CRLF in the index, `ui/assets/league/rune-keystone-border.svg`. None of this
costs anything.

### 194 absolute machine paths in tracked receipts

96 `C:\Users\...` plus 98 `/Users/...`, nearly all in `docs/receipts/oracle-*.json`.
From `docs/receipts/oracle-C6-leaf1.json:16`:

```
"scratch": "C:/Users/skywa/AppData/Local/Temp/claude/
 C--Users-skywa-Desktop-claude-code-merged-calculator/a5d13eb4-.../scratch"
```

`HANDOVER.md:7` gives the repository as
`/Users/river/Projects/league-combat-calculator`, a path on a different machine.

### OS assumptions

Exactly one, and it is documented: `data_updater.py:25`,
`if sys.platform == "win32"`, the colon-stripping monkey-patch that CLAUDE.md lists
under Known Quirks. No `.venv/bin` hard-coded in `src/`. The 41 hits are in
`ci/common.sh`, which resolves it properly, in script help text, and in the two stale
root documents.

### Proposal

One lint over tracked JSON: no string matching `^[A-Za-z]:[\\/]` or
`^/(Users|home)/`. Strip the path when a receipt is written.

## 6. Duplicate logic

`.audit/cc6_clones.py` normalizes each function body by alpha-renaming names, folding
literals and stripping docstrings, then hashes it. It scans 11,159 functions of 4
statements or more.

- 147 clone groups, 437 functions, 290 redundant copies.
- Clone groups spanning more than one top-level directory: 0.
- Clone groups containing any `src/` or `scripts/` function: 0.

That last line is the important one. No script re-implements a `src` helper, and no
two `src` modules share a body. Sightline agrees: `.sightline-baseline` defers only
3 rule #11 findings.

All 290 redundant copies are in `tests/`, and they are one pattern. Test function
names repeated across 5 or more files: 29 names, 621 functions.

| Copies | Name |
|---|---|
| 131 | `test_a_timed_fimbulwinter_fight_is_fully_certified` |
| 118 | `test_declared_kinds_are_the_ones_the_cached_kit_gives` |
| 105 | `test_every_ability_event_carries_the_review` |
| 38 | `test_module_cc_is_the_declaration_the_parser_wired` |
| 24 | `test_every_reviewed_part_carries_its_kind` |
| 19 | `test_each_declared_kind_is_the_word_its_slot_text_uses` |
| 18 | `test_control_free_slots_name_every_word_their_text_contains` |
| 17 | `test_declared_kinds_quote_the_cached_text` |
| 14 | `test_reviewed_absences_read_the_whole_slot` |

The top three alone are 354 copies of three assertions. Each is a property of every
registered champion module, so each is one `@pytest.mark.parametrize` over
`champions._CHAMPION_MODULES`. That deletes about 350 function bodies and makes the
property total by construction. Today a new champion has no contract test unless its
author remembers to paste one.

Two other clones worth folding: `_resolve` duplicated between
`tests/test_e2_dot_2.py:96` and `tests/test_e4_summon_3.py:96` at 23 statements, and
`_resolve` between `tests/test_aurelion_sol_stardust.py:260` and
`tests/test_aurelion_sol_stardust_ledger.py:176` at 17 statements.

This overlaps the low-value-tests auditor. The cross-cutting claim is narrower: this
is the only duplicated-logic finding in the tree, and the fix is a codemod rather than
a judgement per test.

## 7. Config and tooling sprawl

Ten configured quality tools: black, pylint, ruff through the simply-elegant plugin,
sightline, bandit, pip-audit, trivy, `prose_lint.py`, `literal_defaults.py` and
`comment_lint`. On top of those sit the domain gates: `golden_snapshot`,
`coverage_census`, `swing_stream_audit`, `behavior_frontier`, `item_umbrella_audit`,
`certify_damage_casts`, `coverage_status`, `receipt_walk_schedule`,
`cast_dependency_audit` and `capture_coverage_classification`.

### Overlaps, all arbitrated in pyproject.toml

- Complexity and arity: ruff `C901`, `PLR0911`, `PLR0912`, `PLR0913` and `PLR0915`
  are off, ceded to sightline #23 and #55. Pylint still fires and is silenced 163
  times inline. This is the one unarbitrated overlap.
- Commented-out code: ruff `ERA001` off, ceded to sightline #34.
- Comment form: 4 simply-elegant comment rules off, ceded to `prose_lint.py`.
- Numeric literals: ruff `PLR2004` off, ceded to rule 5 and `literal_defaults.py`.

All 35 global ruff ignores and all 22 per-file entries carry their reason on the
adjacent line. This is disciplined, not sprawl.

### The baseline is small

`.sightline-baseline` is 60 lines holding 59 entries: 53 for rule #27, 3 for #14,
3 for #11.

CLAUDE.md describes it as also holding "#54 the damage-type switch (`DamageClass`
owning its resistance axis), and one #35 registry cycle (`champions/inputs` reads
option defaults at call time)". Neither rule appears in the file. Rules 11, 14 and 27
are the only ones present. Either those findings were fixed and the sentence was not
updated, or they are deferred elsewhere. Either way CLAUDE.md names a state the file
does not hold.

### CI

5 jobs on 8 runners: `shared-ui`, `test`, `static`, `coverage-census` across 4 shards,
and `container`. The census is sharded so it finishes inside the test job, about a
minute per shard against about ten minutes unsharded. `container` builds, smoke-tests
and trivy-scans the image. No dead jobs.

### Skills

Five, all live. `add-champion`, `add-item-effect`, `atomizer` and `patch-update` are
model-visible. `analyze-champion` sets `disable-model-invocation: true` with
`user-invocable: true`, so it is deliberately slash-only rather than broken
frontmatter. All five are referenced from CLAUDE.md or `Agents.md`.

### Two atomizers

The `atomizer` skill calls itself "the unified way to atomize anything numerical and
quantifiable in this repo" and says "never write a new ad-hoc extractor". It points at
`scripts/atomize.py`, which writes `data/atoms/<domain>.json` plus
`data/atoms/manifest.json`.

`scripts/extract_atoms.py` is a second, independent extractor. It writes
`data/atoms/<champ>.atoms.json`, `atom-summary.json`, `unclassified.json` and
`classification-report.json`, and its own docstring calls it "WS3 atomic catalog, v2".
Two extractors, two schemas, one output directory, one skill claiming there is one.

### One spent tool

`scripts/testing_flag_codemod.py` is a one-shot codemod whose work is finished, since
`tests/conftest.py` now borrows `TESTING` for the whole session. It and
`tests/test_testing_flag_borrow.py` remain. Same shape as the `scripts/assignments`
files in category 8.

## 8. Data and receipt surface

624 tracked JSON files in scope, 41.2 MB. Four findings.

### data/atoms/v2 is 9.2 MB with no generator and one reader

166 files, 537,810 lines, added in a single commit, `5b0ad6ea`, subject "feat:
depth-level-2 atom corpus, numeric spine, sub-states, cycle models (166 champions)",
dated 2026-08-12. That commit contained no code, only the 166 JSON files plus
`data/atoms/atoms.schema.v2.json`. Nothing has touched the directory since.

- No writer exists in the tree. `scripts/extract_atoms.py` writes `*.atoms.json`, not
  `*.atoms.v2.json`. `scripts/atomize.py` writes domain files.
- There is no manifest, unlike the v1 corpus.
- Readers tree-wide: one. `tests/test_milio_fired_up_blocker.py:49` reads
  `milio.atoms.v2.json`. There is also a docstring mention of `naafiri.atoms.v2.json`
  in `src/calculator/champions/naafiri.py:45`.
- `GOAL-0fails.md` records that the 48 baseline failures at the time were "all
  depth2-atom-corpus data drift", so this corpus's last effect was breaking the suite.

165 of 166 files are unread, unregenerable and undiffable. Delete the directory and
keep `milio.atoms.v2.json` beside its test as a fixture, or inline the values the test
asserts on.

### docs/receipts/oracle-*.json consults 2 of 141

141 oracle leaf receipts: 139 named `oracle-C6-leaf*`, plus `oracle-P4B-leaf29` and
`oracle-P4-3.8-leaf24`. The tree's only programmatic read is
`tests/test_golden_snapshot.py:1378`, `_q2_row_was_absent_before_c6`, which globs
`oracle-C6-*.json` and filters to
`leaf_path == "fights/manual_target/breakdown/Q2"`. Exactly 2 files match. The corpus
spans 72 distinct `leaf_path` values over 5 scenarios, so 139 files exist only to be
filtered out. They also hold all 194 hard-coded machine scratch paths from category 5,
and the sentence "runbook R-18/R-19 forbids me to read src/" appears 22 times.

Keep the 2 files the test names, or inline their two facts, and archive the rest
outside the repo.

### data/item-atoms is documented as retired

`tests/test_build_receipts.py:3` states it:

> "The item-atoms/ tree was retired by the unified Atomizer migration, but
> `scripts/build_receipts.py` still pointed at it: `data/item-atoms/items.json`"

325 files, 1.4 MB, last touched 2026-08-07, still fully tracked. Delete.

### scripts/assignments holds 35 spent codemod inputs

Module-split assignment files that `scripts/extract_modules.py` consumes. Once a split
lands, the file is a record of it. 35 of 44 are referenced by nothing, including
`ability_spec.json`, `aphelios.json`, `bis.json`, `capabilities.json`,
`damage_routing.json`, `item_source.json`, `ledger_projection.json` and
`module_contract.json`. Only 80 KB, but they make `scripts/` read as a data directory.

### What is healthy

`scripts/golden_baseline.json` at 2.5 MB has 11 readers across CI and tests.
`scripts/golden_coupled_baseline.json` at 6.5 MB has 10. `tests/fixtures/` holds 10
files, all live. `data/champions.json`, `data/items.json` and `data/runes.json` are
the tracked runtime caches with a single writer. `data/icons` at 7.8 MB and `data/bin`
at 12 MB are both documented in `.gitignore` and CLAUDE.md as deliberately tracked
with a stated reason.

### Proposal

Delete the four items above, minus the 2 oracle leaves. That removes about 12 MB and
about 1,300 tracked files. Then add one test: every tracked file under
`docs/receipts/` and `data/atoms/` must be named by a regenerator or read by a test,
and a new family must declare which.

## 9. Frontend

### Verified not slop

`ui/src/scoreboard-vision.js`, 972 lines, looks like a full copy of
`static/js/scoreboard.js`, 1,158 lines, including a 38,792-character
`ScoreboardVision` and 11 duplicated helpers. It is generated. `ui/build.mjs:12` reads
`../static/js/scoreboard.js`, cuts at the page-wiring marker and writes the file with
a `/* Generated by ui/build.mjs from static/js/scoreboard.js. Do not edit. */` header.
`node build.mjs --check` gates it in both `tests.yml` and `ci/fast.sh`, and
`ui/.prettierignore` lists it. Correct single sourcing.

`static/calculator/calculator.js` at 356 KB and `calculator.css` at 100 KB are the
committed esbuild output of `ui/src/`, gated by the same `--check`.

### Real findings

`escapeHtml` is duplicated verbatim, 7 identical lines, in
`static/js/eventorder.js:25` and `static/js/feedback.js:44`. Two HTML escapers that
can drift is the one duplication here with a security edge.

`render` is defined in 3 files: `app.js`, `eventorder.js` and `feedback.js`. `init` is
defined in 2: `feedback.js` and `staleness.js`. Each is module-scoped, so there is no
collision, but there is no `static/js/shared.js` and each of the four small scripts
re-derives its own setup.

Inline `<style>` blocks sit in 5 templates: `templates/index.html` 102 lines,
`beta_landing.html` 60, `privacy.html` 18, `terms.html` 18, `riot_disclaimer.html` 18.
That is 216 lines of CSS that `static/css/style.css`, at 2,678 lines, should own.
There is no inline `<script>` anywhere.

Dead CSS is 64 classes, not the 1,011 a raw scan reports. 947 of those sit in
`ui/assets/league/client-collections.css`, which `ui/assets/league/README.md:27`
documents as "the exact client CSS export retained as research evidence", so being
unused is the point. The real remainder: 59 in `static/calculator/calculator.css`,
which is generated and therefore really upstream in `ui/src/*.css`, 26 in
`ui/src/calculator.css`, 16 in `ui/src/champion-hud.css`, 9 of 15 in
`ui/src/tooltip.css`, 5 in `ui/src/timeline.css`, 4 in `static/css/style.css`.

`console.log` appears 5 times in `tests/js/*harness.mjs`, where stdout is the harness
protocol, and once in `ui/build.mjs`. None ships. `eslint-disable` appears twice in
`ui/`.

### Proposal

Extract `static/js/shared.js` for `escapeHtml` and the two other shared helpers. Move
the 216 inline CSS lines into `style.css`. Run a PurgeCSS pass over `ui/src/*.css`,
excluding `assets/league/`.

## 10. Many agents, no editor

### Stray root files

28 tracked files sit at the repo root. Counting references across the whole tree:

| File | Lines | Referenced by |
|---|---|---|
| `HANDOVER.md` | 5,986, 360 KB | 2, one of them a test |
| `GOAL-0fails.md` | 86 | 2 |
| `PRODUCT.md` | 57 | 0 |
| `Project Design.tldraw` | 36 KB | 0 |
| `Agents.md` | 4 | 0, but it is the non-Claude entry point, so keep it |
| `DESIGN.md` | 36 | 1, `HANDOVER.md` |
| `run_web.bat` | 11 | 4, live |

`HANDOVER.md` is an append-only agent session log. It opens "Status: active, resumed
2026-08-09", cites a goal thread UUID, and gives the repository as
`/Users/river/Projects/league-combat-calculator`. It has not been touched since
2026-08-23. It is the tree's largest single archaeology source: 310 `[A-Z]\d` tokens,
48 `xfail` mentions, 27 `wave` mentions, 8 `CP` tokens and 6 `.venv/bin` invocations.
`tests/test_eclipse_shield_selection.py` cites `HANDOVER.md:1311` as a source of
truth, and any edit to that file invalidates the reference.

`GOAL-0fails.md` pins a baseline "recorded 2026-08-12: Passing 7,584, Failed 48,
Xfailed 57". The suite is long past that. It is a finished campaign's goal document.

`PRODUCT.md` and `Project Design.tldraw` are referenced by nothing.

### Docstring discipline is otherwise good

1,195 Python modules, and 8 have no module docstring: `src/__init__.py`,
`src/calculator/__init__.py`, `tests/__init__.py`, and 5 tests. First-line style is
consistent, with 1,132 ending in a period against 55 that do not. Of 19
`__init__.py`, 3 have no docstring, 11 are docstring-only, matching architecture.md's
"Each `__init__.py` holds one docstring line and no re-export", and 6 hold code.

### Docstring length is unbounded where the narrative collects

100 modules have docstrings over 40 lines and 35 have over 80. The longest are almost
all tests:

| Lines | File |
|---|---|
| 193 | `tests/test_vladimir_e_charge_time.py` |
| 183 | `tests/test_zeri_p_execute_range.py` |
| 174 | `tests/test_cleanse_eligibility.py` |
| 169 | `tests/test_olaf_r_cleanse.py` |
| 154 | `tests/test_verdant_barrier_compiled_parity.py` |
| 124 | `src/calculator/champions/naafiri.py` |

`pyproject.toml` exempts tests on purpose, with the reason "A test's docstring is its
claim and is not bounded", and `prose_lint.py` bounds only `src/` and `scripts/`.
That exemption is where the campaign narrative collected: 945 of the 1,421 docstring
archaeology markers are in `tests/`. Keep the exemption, since a test's claim is
prose, but let the category 1 lint cover test docstrings, because the rule there is
"no dangling campaign pointer", not "be short".

### Clean

`.claude/worktrees/` is empty and `git worktree list` shows only the main checkout.
No orphaned worktrees.

### Proposal

Move `HANDOVER.md`, `GOAL-0fails.md` and `DESIGN.md` to `docs/archive/`. Delete
`PRODUCT.md` and `Project Design.tldraw`, or move them under `docs/`. Quote the
Eclipse sentence inside `tests/test_eclipse_shield_selection.py` instead of citing
`HANDOVER.md:1311`.

## Three things worth saying plainly

The codebase is in better shape than its prose. No duplicated function bodies in
`src/`, no debug leftovers, no tracked artefacts, one documented OS assumption, every
lint overrule reasoned where it sits. The slop is in the words around the code and in
evidence nobody reads.

The biggest payoff is deletion, not refactoring. Category 8 alone is about 12 MB and
about 1,300 files that no code path touches, and three of its four cases document
themselves as retired or arrived with no generator.

The second biggest is one `parametrize`. 354 copies of three champion contract
assertions collapse into three parametrized tests, which also makes the property
total instead of opt-in by copy-paste.
