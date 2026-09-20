# Traps

Hard-won findings, one per bullet: the fact, then the fix. Invariants and
ownership live in `architecture.md`; rules, domain facts and gates in `CLAUDE.md`.

## Tests and CI

- **Four concurrent full `pytest -n auto` runs take this machine out of memory.**
  A parallel campaign runs the full suite once per wave, on the merged tree, by
  one integrator. A worker runs only the test files it touched, one pytest at a
  time, no `-n`, and passes `--jobs=4` to pylint.
- **A test that mutates shared state races the CI's `pytest -n auto` workers, and
  only there.** A memo-eviction test that cleared one of five unbounded memos
  measured a sibling worker's warm cache as retained generations, and a
  zero-policy fixture that wrote a real `.py` into `src/calculator/champions/`
  was caught mid-test by a parallel scan. A gate that needs a dirty world builds
  it in `tmp_path`: scan roots are parameters (`zero_policy_frontier(root=...)`,
  `_input_fallback_sites(root=...)`). A gate that needs a clean world
  `monkeypatch`es every member of its table to a fresh object, derived from the
  table, never a hand-listed subset. Never `.clear()` a process-wide cache in a
  test: it passes, it costs every later test the warm cache, and it reaches every
  `from ... import` alias where a `setattr` on the owner would not. Borrow a cold
  one through `tests/conftest.py`'s `cold_memo`.
- **A test that leaves `src.app` state changed decides it for every later test on
  the same xdist worker**, as whole-file cascades in files the diff never
  touched, green serially and green on rerun. `tests/conftest.py`'s autouse
  `_process_state_is_given_back` brackets every test and fails the one that moved
  something. `tests/process_state.py` holds the watched surfaces and the two
  singletons deliberately outside them: `db._engine`, which any DB-touching route
  creates, and `data_registry._DATA_VERSION`, monotonic by contract. Borrow
  shared config through `tests/app_config.py` or `monkeypatch.setitem`, never
  `config[key] = ...`: `config.get(key)` cannot tell absent from
  present-as-`None`, so a hand-rolled restore deletes a `None`-valued key, and
  Flask reads `PROPAGATE_EXCEPTIONS` by subscript, turning the next route error
  on that worker into a `KeyError` instead of a 500.
- **A full-suite run is untrustworthy while another process edits `src/`.** A
  test that reads a module's source off disk sees the new bytes while the import
  holds the old module, so concurrent edits produce large phantom failure sets
  that vanish on re-run. `test_trigger_stream` reads through
  `inspect.getsource`, `test_import_namespace` and `test_gate_receipt` through
  `Path.read_text`; the hazard is the disk read, not the API. Gate a shared tree
  only after every writer stops, or against a `git archive HEAD` copy.
- **CI's pylint gate is a score (`--fail-under=9`), so an undefined name passes
  it at 9.70.** `--fail-on=E0601,E0602` fails on the undefined-name family
  whatever the score. The rest of the tree's E-class messages are vendor-path
  import errors, pylint's NamedTuple `_replace` false positive, and one real
  `E0102`: `rune_parser._percent_ratio` has two definitions with identical
  bodies. Widen `--fail-on` past that family only with those accounted for.
- **Parallel lint workers pass alone and fail together.** A helper one worker
  adds meets the rules another worker owns only after the merge, as a new
  one-line helper is unannotated, over-wide, or positional past four; and a phase
  one worker extracts calls a helper another made keyword-only, positionally.
  Merge, re-audit the whole tree, and re-run the suite before trusting any
  worker's zero. Resolve a conflict hunk that is the middle of an expression by
  reading the whole expression afterwards: taking one side's `def` line leaves
  the other side's tail behind it.
- **`pull_request` CI never runs while the PR is CONFLICTING.** GitHub cannot
  build the merge ref, so a PR behind `main` shows only Vercel checks and no
  Actions run. Catch up with `main` first, then read CI.
- **A guard whose reader set comes from string literals is armed by its own
  test.** `tests/` is one of the roots `tracked_data_lint.Readers.in_tree`
  harvests, so a live receipt name or family glob spelled in a fixture makes the
  guard cover that receipt and the negative passes for the wrong reason. Generate
  an absent name with `uuid4`, and spell predicate patterns so none matches a
  tracked file. Prove such a lint by dropping a real reader and watching its
  receipts surface, never by reading its green output.
- **A glob counts as a reader only where it pins something past the suffix.**
  `*` and `*.json` exist in any tree this size, so counting them makes a
  reader-coverage lint zero by construction. `names_a_family` is the predicate. A
  docstring mention is not a reader either: `read_literals` skips every
  `ast.Expr`-wrapped string.
- **A guard over tracked files reads `git ls-files`, never `rglob`.** A test that
  writes a scratch file into a tracked directory races a directory scan under
  xdist, so `tests/test_patch_update.py::TestEscalatedCachedDataLines` builds its
  negative in `tmp_path`.
- **A codemod over `tests/test_*.py` eats the file you just wrote the new tests
  into.** Exclude the destination from the glob, and stage the hand-written
  change first so `git checkout -- tests/` restores it.
- **Two codemod bites on this CRLF tree.** Rebuilding a docstring with `\n`
  joins leaves lone LFs black does not normalise, so read with `newline=""`,
  write with `newline="\r\n"`, and assert
  `b.replace(b"\r\n", b"").count(b"\n") == 0` over `tests/` after black.
  Deleting an AST span leaves the wrong blank-line count around a module-level
  `def`, and an invalid empty class when it takes the last method, so run
  `black -q` and re-parse after each.
- **A pytest `-p` plugin proves what collection would otherwise hide.** It loads
  before collection imports the test module, so it can wrap the callee, where
  digesting every result proves a fixture move changed no number, or stub an
  absent resource's probe on a machine that has it. Filter `at 0x[0-9A-Fa-f]+`
  out of any digest: closure reprs differ run to run.
- **`tests/test_coverage_claims.py` names real pytest node ids as fixtures**, so
  deleting a test can break it from two files away. Run that file after any test
  deletion.
- **A guard reached through a requested fixture is reached.**
  `scripts/resource_markers.py` follows both edges; a call-graph-only scan left
  14 node-guarded tests unmarked. Its other silent pass is
  `any(path.glob(pattern) for path in dirs)`, always True because a generator is
  truthy, where `any(any(path.glob(pattern)) for ...)` is meant.
- **A `_today` or `_is_still_tracked` test name is not evidence that the body
  pins a defect, and a docstring claiming singularity is not a gate.** Four of
  Olaf's and Milio's assert the completed behaviour, and one fixture helper
  called itself the tree's only AST walk over its call sites while the tree held
  three. Read the body, then rename or delete.

## Goldens and receipts

- **A published zero's type is load-bearing.**
  `program/views/leaf.LeafWriter.publish` gives a `float` leaf a disposition
  entry and an `int` leaf none, so `sum()` over an empty generator (int `0`) and
  over one `0.0` term publish different leaf sets. Changing which items a stat
  fold iterates, not just what each contributes, moves the coupled golden with no
  number changing (`dream_maker_roster` `stats.ultimate_haste`). Keep the
  membership filter and the value read separate;
  `tests/test_item_effects.py::TestDeclaredSiblingReads::test_a_build_with_no_registry_item_sums_no_terms`
  pins it.
- **A zero-damage breakdown row is published only if it carries a `detail`.**
  `public_response` skips a row with no damage, no amount and no `detail`, so
  adding a detail string to a zero row (Annie E's retaliation) makes it appear in
  the API and moves the coupled golden's leaf count with no number changing.
- **Compiled slot order is Q,W,E,R,P while `REQUIRED_CHAMPION_SLOTS` is
  P,Q,W,E,R.** The ledger replays insertion order for float sums, so any reorder
  is a numeric change.
- **`scripts/golden_coupled_exact.json` is not a `golden_snapshot.py compare`
  target.** `tests/test_golden_snapshot.py` consumes it through `rebuild_for`
  (declared exact moves), so the compare CLI reports about 11 diffs on a green
  tree, including on `main`. The pinned compare targets are
  `golden_baseline.json` and `golden_coupled_baseline.json` only.
- **A pure refactor leaves `git diff` on receipts empty, and two regenerators
  only re-stamp provenance.** `repin_corpus` and
  `capture_coverage_classification.py capture` rewrite `sha` and `git_head`
  fields with no value change. Revert those two files rather than committing a
  stamp, so the diff says what the phase did.
- **A receipt field read with a literal default is the rule-5 failure shape.**
  `program/compile` reading a published raw as `row.get("raw_damage", 0.0)` held
  172 coupled-golden raw leaves at zero. Read it through the stamp or refuse.
- **Two cached-data defects on Imperial Mandate are open, and patch day is where
  they close.** `data/items.json["4005"].simpleDescription` reads "Defer damage
  until later.", which describes another item, and
  `scripts/build_effect_catalog.py::_text` puts that sentence ahead of every
  passive's own text. The same item's Control branch,
  `passives[0].branches[0]`, fans out into three atoms in
  `data/atoms/items.json`, `control.immobilize`, `stat.haste` and
  `timing.cooldown`, each valued 20.0, while the item's flat
  `stats.abilityHaste` is 15, so a consumer summing `stat.haste` overstates it
  by 20. Neither defect reaches a damage number, because rule 5 keeps every
  runtime item value in `item_effects.py`. `data/` has one writer, so the next
  pull reverts a hand edit to the cache. The entries live in
  `docs/receipts/escalated-defects-cached-data.json`, and
  `python scripts/patch_update.py audit` prints one line per open entry.
- **`golden_snapshot.py capture` refuses while `src/` differs from HEAD**,
  because the recorded `src_tree_sha` would name a tree the capture did not read.
  A behaviour fix is therefore two commits: the src change, then the re-capture.
- **Deleting the last reader of a tracked `docs/receipts/*.json` turns
  `tests/test_tracked_data_lint.py` red** with `orphan: <path>`. Check what names
  a receipt before deleting its test.
- **`docs/receipts/campaign-stages.json` outlives counter 4's deferrals**,
  because `creditor_stage` still publishes `retires_at` on every unserved-lane
  row. Deleting a table because one of its two readers left is how a receipt
  field goes unreadable.

## Engine and pricing

- **`return factor * sum_modifiers(...)` reads `factor` before the call**, so a
  `nonlocal` the callee's closure sets is invisible. Akshan E's attack-speed
  factor priced 1.0 that way, and a fix in the same shape was green on its unit
  test and moved no number. Bind the call to a name, then multiply.
- **A charge ability's `cooldown` is its cached `rechargeRate`, never the cached
  `cooldown`.** The docstring of `src/calculator/champions/charge_cadence.py` is
  the one home for what each timer means, which slots must carry a reviewed
  `ChargeRule`, and where the banked stock is sourced from.
  `tests/test_charge_cadence.py` pins it.
- **`slot_extract.extract_value(ability, attr, rank)` indexes a row's last value
  when `rank` exceeds the row's axis**, because `_axis_index` falls through to
  `-1`, so a rankless or short row silently prices the maximum instead of
  raising. Check the row's length before trusting a ranked read. The guarded case
  is Aphelios Weapon Master in `aphelios.py`.
- **Crit rolls are random unless `deterministic` is set.**
  `fight/autos/simulation.py` rolls `random.random() < crit_chance` per swing, so
  two identical `calculate_payload` requests on a crit build return different
  auto totals (Kai'Sa: 623, 739, 854). Every probe, test and golden capture on a
  crit-capable build passes `deterministic=True`. It is not a drop-in for a
  `random.random` patch that forces a crit COUNT: the deterministic branch blends
  crit and non-crit at expected value and sets `natural_crit` False, so
  `num_crits` is always 0 and an empowered Fiendhunter auto publishes a
  `fiendhunter_true_damage` row a forced-no-crit run has none of. Swap it in only
  under an inequality or a blended total.
- **The walk mutates the `actions` list its caller passes.** `run_survival_walk`
  re-reads `len(actions)` every iteration because three producers insert into it
  mid-walk: both ledgers' `schedule_heal` and the kernel's
  `_rebind_self_shields`, each at the sorted position after
  `ledger.current_index`. That is how an action is rescheduled: `SurvivalAction`
  is a `NamedTuple`, so a `_replace` at a new time and sort key keeps the same
  `aidx` and the same event dict, and the ledger records one outcome for the
  moved packet rather than two. Pass a real list and read it back after the call;
  `program.walk.walk` snapshots `tuple(actions)` only once the kernel returns. A
  tuple or a defensive copy drops every walk-authored packet with no error.
- **cProfile shares lie about the fight engine, and the optimizer benches cannot
  resolve a small win.** Cost is spread across millions of one-line helpers, so
  the profiler's per-call overhead over-weights them roughly 2x. A per-build memo
  timed in a loop over one build hides the miss the search pays on every
  evaluation, and a per-evaluation figure taken at six items hides that
  `optimize_build`'s greedy search mostly evaluates partial builds: a fold whose
  saving scales with held items and whose cost does not wins at six and loses at
  one. `scripts/bench_optimize_build.py --budget` and
  `--by-build-size [--against <other checkout>]` encode both measurements, and
  `benchmarks.md` owns the numbers.
- **A section-numbered citation into an append-only log is a second home for
  every number it quotes, and it drifts silently.** The retired `HANDOVER.md`
  4.26 was stale in two of its six Eclipse number groups against
  `item_effects.py`, and the test naming it as its source of truth had no way to
  notice. Cite the accessor key, never the log's number.

## Platform and tooling

- **`sed -i` in Git-Bash strips CRLF.** Use byte-preserving scripts for bulk
  edits on this tree.
- **A `Path.write_text` file list reaches `xargs pytest` as `tests/x.py\r`** and
  every path is "file or directory not found" with no hint why. Pipe through
  `tr -d '\r'`.
- **The Bash tool mangles a backslash inside a quoted heredoc.** `"\\\n"` in a
  `<<'PY'` heredoc reaches Python as a backslash and the letter n, so an
  exact-string match silently finds nothing. Build such strings from `chr(92)`
  and `chr(10)`, and assert the match count before writing.
- **`ruff --select I001` is not at zero on this tree**: 26 unsorted import blocks
  live in `src/`, so `lint_gate.py --tree .` reports about 145 findings across 90
  files a branch never touched. Judge a branch by the hits in the files it
  changed.
- **A Windows filename cannot hold a colon.** `data_updater.py` monkey-patches
  `lolstaticdata`'s `download_soup` to strip colons from cache filenames.
- **The vendored wiki parser crashes on `nvalues=None`** for Heimerdinger, Sona,
  Karma and Nidalee. The local copy patches it.
- **Agent worktrees live under `.claude/worktrees/`.** Anything that `rglob`s the
  checkout, such as `behavior_frontier.scan()`, sees every worker's copy. Index
  from the `src/`, `tests/`, `scripts/` and `docs/` roots, never the repo root.
- **An agent worktree forks from `main`'s tip, not the session's checked-out
  branch.** A subagent spawned with worktree isolation while a campaign branch is
  checked out still starts at `main`. Verify `git merge-base` against the
  intended base, and have the worker merge the campaign branch itself when the
  base is stale.
- **Parallel sessions share one `.git`.** `git checkout -- <dir>` in one worktree
  discards another session's uncommitted edits in that worktree, so use one
  worktree per session. `git stash` is one stack across all worktrees, so never
  stash as a base-state check; detach onto the base commit instead. On this
  case-insensitive filesystem `git rm skill.md` also removes `SKILL.md` from
  disk.
- **`sorted()` over `Path` folds case on Windows.** Two receipts that sort
  differently on Linux and Windows gave `tests/test_golden_snapshot.py`'s
  `declared_exact_moves` a platform-dependent winner. Sort on `path.name` or an
  explicit key, never on `Path` objects, wherever order decides precedence.
- **`data/atoms/manifest.json` `source_ref` digests hash LF bytes.** The corpus
  is generated on Linux and this checkout is CRLF (`core.autocrlf=true`), so a
  test hashing `path.read_bytes()` raw disagrees with the manifest here and
  agrees on CI. Hash with `\r\n` normalized to `\n`. The CommunityDragon bins
  under `data/bin/characters` are tracked, so the champions domain does resolve
  locally, but a local regeneration rewrites every digest against CRLF sources:
  regenerate `data/atoms` on Linux only.
- **The simply-elegant hooks resolve `pyproject.toml` per-file rules against the
  main checkout**, so every edit inside `.claude/worktrees/<name>/` reports the
  exemptions as errors: `comment-per-file-off` width on
  `tests/test_cleanse_eligibility.py`, ruff `per-file-ignores` on `tests/**`, and
  the file-length hook's `git show HEAD:<path>` baseline. A worktree hit is a
  false positive when the same line is clean at the repo root. Verify there with
  `python <plugin>/hooks/lint_gate.py --tree .` rather than adding a marker.
- **A Bash task that times out and is moved to the background re-runs its whole
  command when it resumes.** A one-shot patch script left on disk ran a second
  time an hour later and clobbered `static/js/scoreboard.js`. Edit files with the
  Edit tool or an exact-string script deleted right after; never leave a
  file-rewriting script for a resumed task to find. A regex over a docblock with
  `re.S` is the same trap in one step: an optional docblock group swallows
  everything from the file's first docblock to the target.
- **Three ruff autofixes bite on this tree.** F401 strips an accidental
  re-export, where `healing_helpers` re-exports three `slotlib` functions that 33
  modules read as `_healing.x`, and a test's front-door import, which the D-95
  architecture test counts. C414's `tuple(list(x))` to `tuple(x)` returns the
  same object when `x` is a tuple, caught by an identity assertion. PLW0108's
  lambda removal hoists a forward reference into a `NameError` in `hecarim.py`.
  Import-check every champion module after a fix pass, and keep a `noqa` reason
  short enough that black leaves the line intact, or the marker lands on a
  different line than ruff reports.
- **A `sightline-ok` marker covers its own line, or the whole definition when it
  sits on the `def` line.** Rule #1 reports once per signature at the `def` line,
  so a marker on the `) -> Any:` line of a multi-line signature covers nothing.
  Put it on the `def name(` line; black keeps a trailing comment there.
- **Sightline #14 counts typed signatures only, so moving a hot type into a small
  leaf surfaces a clump the baseline never listed.** Extracting `SlotCtx` into
  `champions/slot_context.py` made the `(ability, ctx, rank)` clump across 13
  champion slot functions typed, and its key took the anchor from
  `slot_extract.extract_named`. Expect an anchor swap, not a rise, when a leaf
  extraction lands; prove it with the finding count and dissolve the clump.
- **Sightline #11 normalizes names and literals**, so a wrapper differing only in
  its regex and message is still a clone, and a one-statement `main` is big
  enough to count. Six champion readers of a cached sentence stayed one clone
  group after they all called one helper. The record shape dissolves them: each
  module declares one `ability_prose.CachedSentence(pattern, missing)` and reads
  it at the call site, so no per-module function exists to compare. A shared
  entry point takes the same move. `write_or_check` lives in
  `scripts/generated_file.py` and binds as `main = partial(...)` in
  `scripts/coverage_status.py` and `scripts/certify_damage_casts.py`;
  `required_field` lives in `src/calculator/event_row_field.py` and binds as
  `_required = partial(...)` in `cast_event_row.py`, `damage_event_row.py` and
  `heal_event_row.py`. The plugin's ruff wants `x.get("k") or ()` (FURB110) where
  the rule-5 lint reads that as an or-default; bind first, then
  `for effect in effects or ():` satisfies both.
- **The stop gate's prose lint reads every changed `.md` whole.**
  `comment_lint.lint_prose` bans em dashes and history phrasing and runs over
  each changed markdown file in full, so one edit to a file carrying the debt
  means clearing that whole file. Most tracked markdown outside `CLAUDE.md`,
  `TRAPS.md`, `architecture.md` and the five skill files still carries em dashes.
  Grep for the character before editing one.
- **A skill's frontmatter `description:` cannot hold a colon.** An unquoted `: `
  inside it breaks the YAML, and the harness then lists the skill by its heading
  with no trigger text, showing `/patch-update` as "Patch Update". Use a comma or
  a period.
- **The worktree isolation guard refuses any Bash command whose git use it
  cannot statically prove stays inside the worktree.** Heredocs, `git ... |
  xargs`, brace groups and shell arithmetic over `$(...)` all read as too
  complex. Use plain single commands and `python -c` one-liners, and write
  scratch inside the worktree or `$TEMP`.
- **MSYS2 paths are not Windows paths.** `/tmp/x` and `/proc/meminfo` cannot be
  opened by Windows python, and MSYS2's `/proc/meminfo` carries `MemTotal` and
  `MemFree` but no `MemAvailable`, so a reader of it computes 100% used. Read
  memory with `psutil.virtual_memory()` and scratch from `$TEMP`.
- **`scripts/literal_defaults.py` prints `total N` to stderr and one site per
  line to stdout.** `2>&1 | wc -l` therefore reports N+1. Read the total from
  stderr alone.
- **A Windows esbuild run reproduces the committed bundle byte for byte, and
  `node build.mjs --check` passes here.** Compare a build against
  `git show HEAD:<path>`, never the autocrlf working file: the 17 / 1 / 56 byte
  deltas on `calculator.js`, `calculator.css` and the LEGAL text are those
  files' newline counts, not a platform difference.
- **`Path.write_text` on Windows re-emits `\n` as `\r\n`**, which is what keeps a
  rewritten data file matching its CRLF neighbours. A rewriter that opens with
  `newline=""` writes LF into a CRLF tree.
- **Dependabot's docker ecosystem does not resolve `FROM ${ARG}`.** An
  ARG-defined base image silently stops receiving digest and security bumps, and
  Dependabot closes its own update PRs against it (dependabot-core#10190). Keep
  the pin on a literal `FROM image:tag@sha256:...`.
- **`scripts/extract_modules.py` check mode refuses a checked-in assignment
  record**: the split has been applied, so it reports "not a unit of" the
  source. The records are review evidence, never a replay input.
- **Deleting an installer deletes the last executable copy of its command.**
  When a doc becomes a command's last carrier, put its code blocks through the
  real argument parser in a test; `shlex.split` needs
  `block.replace("\\\n", " ")` first or the continuation survives as a token.
- **A regex written as ``` ``?NAME``? ``` requires one mandatory backtick plus an
  optional second, not an optional pair.** It silently matches only the
  double-backticked spelling. Use `{0,2}`, and print what a new scanner found
  before trusting a green run.
- **`comment_lint.lint_prose` skips fenced code blocks and honours `prose-ok`.**
  An em dash inside a fence is not a finding. Its history rule matches a fixed
  phrase list, so "replaced", "now" and "was" pass it while still narrating
  history a reader has to skip.
- **A branch another worktree holds is taken with
  `git checkout --ignore-other-worktrees <branch>`.** A plain checkout refuses
  with "already used by worktree at ...", which reads like the branch is locked.
- **Sizes from `git ls-tree -r -l` are MiB when divided by `2**20`.** Two reports
  disagreeing by about 5% on tracked bytes are usually agreeing in different
  units.

## Frontend and vision

- **An expando property on a typed array deoptimizes V8 for every function that
  touches that array.** `vec.contrast = rms` on the fingerprint `Float32Array`
  made `fingerprint` about 10x slower in every caller. Return the number instead.
- **`Math.min` and `Math.max` in `fingerprint`'s pixel loop cost 3x.** V8 types
  their result as float64, so the typed-array index leaves the integer path and
  every read goes from 2.8 s to 8 s. The edge clamps there are ternaries. Time
  any change to that loop with the harness against
  `git show HEAD:static/js/scoreboard.js` before trusting it.
- **Probe the page under its real CSP; `bypass_csp=True` hides the failures users
  hit.** `img-src` has no `blob:`, so an `<img>` on an object URL never loads and
  every screenshot comes back "not an image the browser can open" while the
  bypassed probes pass. Decode a user's blob with `createImageBitmap`, which
  `tests/test_scoreboard_vision.py` pins. Under the real header a bare expression
  string in `page.wait_for_function` raises an EvalError, so pass a function
  (`"() => ..."`) and watch the console for "violates the following Content
  Security Policy".
- **The scoreboard reader's floor is a 24px portrait (`PORTRAIT.min`).** A 480p
  broadcast frame puts portraits at about 18px, so `scoreboard_corpus.py scan` on
  a 480p stream reads nothing. Scan the 1080p stream.
- **A scoreboard read that misses rows or most items in one browser and not
  another is the input's scale, not the browser.** The same PNG reads
  pixel-identically in Chromium, Playwright Firefox, and Firefox 155 under the
  ASUS Display P3 profile. Every threshold in `scoreboard.js` is tuned at 24 to
  36 px portraits, so `readScoreboard` resamples a frame whose anchor is larger
  to `PORTRAIT.typical` before reading. Reproduce a bad read by rescaling the
  frame through `scoreboard_corpus.py read`, never by chasing color management or
  canvas noise first.
- **`yt-dlp --download-sections` stalls on YouTube DASH streams here**, writing
  nothing for minutes. Download the whole stream once and cut frames with
  `scoreboard_corpus.py grab`.
- **The page carries two escapers over three consumer files.**
  `static/js/scoreboard.js` calls `escapeHtml` at :1100 and :1107 and defines it
  nowhere, resolving `app.js`'s top-level `const` through the classic-script
  global scope, so it gets the weaker one (no `'` escape, no null guard). Grep
  the whole script set, never the file that uses one.
- **`tests/js/harness_context.mjs` answers an unknown window key with a truthy
  stub.** A script guarding with `window.ns = window.ns || {}` writes onto a
  throwaway and every later read gets a fresh one. Seed the namespace
  (`context.window.scryglass = {}`) before running the script, and gate the
  page's real load order in the template test instead.
- **An edit to `ui/src` that reaches the bundle means rebuilding and committing
  `static/calculator/`.** Removing an export is enough: dropping two moved 523
  bytes of `calculator.js` because esbuild reassigned its minified names.

## Champions

`/analyze-champion` reads this section before its analysis step. Every bullet is
a pattern that bit one champion and generalizes to the next.

### Cached data and sources

- **Known-degraded wiki parses, stable across patches.** The modifier parser
  half-parses gimmick scalings, so values survive but `units` come back empty and
  the shared scaling resolver cannot attribute them. Aurelion Sol Q (Stardust
  stacks), Bard P (Chimes), Heimerdinger W and E (multi-part rockets), K'Sante W
  (bonus resistances), Quinn P (crit chance), Vladimir E (charge time), Yasuo and
  Yone Q3 (crit conversion), Zeri P (execute range). These emit the
  `FAILURE TO PARSE MODIFIER` spam during a data pull. Each needs a champion
  module with options for its stack or charge mechanic anyway, so the parse fix
  belongs to that work, not to patch day.
- **A "Total X Damage" attribute on a DoT or channel is derived data the wiki
  maintains by hand**, and a duration change invalidates it while every input
  array stays right. Dr. Mundo W's cached total is a 16-tick figure against a
  3-second, 12-tick ability, overstating the charge by a third. Compute the total
  from `duration x ticks_per_second x per_tick` and use the cached total only if
  it agrees; the per-tick value wins. Re-pulling the data never fixes this.
- **A threshold can exist only in the game files.** Dr. Mundo E's "0% to 40%
  (based on missing health)" reaches its maximum at 70% missing health, published
  nowhere on the ability page and present in `drmundo.bin.json` as
  `MaxMissingHealthThreshold`. When a wiki ability scales "X% to Y% (based on
  resource)" without naming where Y is reached, do not assume 100%: pull the game
  file for a `Max...Threshold` beside the `Max...Amp`. The wiki's own
  "Maximum ..." leveling row is the cross-check, and equals `minimum x max_amp`
  exactly.
- **A form champion's stat deltas come from the game files, never the wiki stat
  box.** Gnar's Mega box is hand-maintained and stale, claiming 5.7 AD growth
  where `gnarbig.bin.json` minus `gnar.bin.json` CharacterRecords gives 5.5, and
  Gnar P's cached `leveling` is empty entirely. Verify every transform champion
  the same way: Gnar, Nidalee, Jayce, Elise, Shyvana. An in-game practice-tool
  measurement of two AD-scaling abilities pins total AD exactly.
- **Naafiri's binary names her two upper spell slots the opposite way round from
  the live kit, the wiki and `data/champions.json`.**
  `Characters/Naafiri/Spells/NaafiriRAbility/NaafiriR` is wiki W, The Call of the
  Pack, and `.../NaafiriWAbility/NaafiriW` is wiki R, Hounds' Pursuit. Bind them
  by the padded `cooldownTime` arrays (W: 26/24/22/20/18, R: 110/95/80), the only
  sound channel: the `NaafiriR*` and `NaafiriW*` child objects are empty markers
  with no `DataValues` and no `mSpellCalculations`, and the atomizer classifies
  them by name. The same swap runs through
  `data/atoms/v2/naafiri.atoms.v2.json`, whose `behavior` field uses the binary
  names. `naafiri.py` is named by the live kit throughout.
- **A summarized fetch of a rendered champion page garbles progression tables and
  invents rules.** Bard's meep stock and recharge tiers came back as invented
  breakpoints where the game has 1 to 9 meeps at 0/10/30/50/65/80/90/95/100, and
  Cassiopeia's page returned a "cannot buy boots" restriction the page does not
  state. Fetch the raw data template
  (`https://wiki.leagueoflegends.com/en-us/Template:Data_<Champion>/<Ability>?action=raw`)
  and read the `{{pp|values|breakpoints}}` calls verbatim. Numbers cross-check
  against the champion JSON and rules do not, so any fetched rule that would
  constrain builds, items or options needs the game file or the user to confirm
  it.
- **The wiki's item-interaction notes are hypotheses, not ground truth.** Azir's
  soldier attacks apply spellblade, Energized and Kraken at 50%, and Sundered Sky
  alone does not apply at all, against a note claiming Energized "stacks but is
  not consumed". Apply an "on-hit at X% effectiveness" reduction to every
  per-attack and proc-style item effect unless an exclusion is verified in game.
- **A `Bonus Damage` leveling row is often a monster-only cap, not a damage
  source.** Rumble Q's row is the per-level cap on the %max-health term, "capped
  at 65 to 163.32 against monsters", and Rumble P carries the same shape. This
  engine's `target_class` has no monster value, so such a row never binds and is
  documented, never added. Read the row's own sentence before pricing it.

### Pricing shape

- **A stat-granting ultimate carries `total_raw: 0.0` and a `stat_buff` dict**,
  never a damage row (Aatrox R). An ability with a passive stat component is a
  BUFF-phase `stat_buff` slot, with `apply_to=` when the stat scales other
  abilities at parse time, so the damage slots see it (Ambessa R's armor pen).
- **When a form or steroid grants AD, decide base against bonus explicitly.** A
  form swap that is a separate in-game unit grants BASE stats (Mega Gnar); an
  ability steroid grants BONUS AD (Vayne R, Aatrox R). The fight engine supports
  both keys. The choice decides whether %bonus-AD ratios see the grant and
  whether Sheen-type base-AD scalings grow.
- **A base-stat `stat_buff` must re-derive every item stat computed from that
  base stat.** Sterak's Gage converts base AD and is computed at build-stats
  time, before a Mega base-AD grant lands. `_apply_stat_buff_ultimates` holds the
  recompute hook and reads `item_effects.steraks_bonus_ad`; the numbers stay in
  `item_effects`.
- **A charge basic ability reports single-cast damage** and takes `rechargeRate`
  as its `cooldown`, letting the engine count casts (Amumu Q). Never pre-multiply
  a cast count into `magic_damage` or `physical_damage`. Sub-casts within one
  activation, such as Ahri R's three dashes, are one `DamagePart(count=N)` plus
  `cast_instances=N`.
- **A charge ULTIMATE owns its own cast count**, because `_schedule_shared_casts`
  puts every `R` in `single_cast` in every mode (Corki R). Keep per-missile
  damage on `DamagePart.amount`, put the count on `DamagePart.count`, set
  `cooldown` to `rechargeRate`, and set `cast_instances` so per-cast item procs
  count each shot. An every-Nth cadence is computed over the resulting count,
  never approximated as an average uplift.
- **"Empowers next basic attack" is once per cast; "basic attacks deal bonus
  damage" is every auto** (Alistar E). Read the wording.
- **A granted or forced basic attack still swings when there is no auto stream.**
  One-rotation mode and a timed fight at zero uptime both give
  `num_auto_attacks == 0`, and the cast still forces its attack, so the ability's
  own row carries the expected-crit base swing. The cases are Blitzcrank E, Vayne
  Q and Caitlyn's headshots. Cap conversions by the auto count only when autos
  exist to host them.
- **An empowered swing belongs on the ability's row in every fight mode.**
  `damage.py::_reattribute_empowered_swings` moves
  `casts x hits x auto_damage_per_hit` onto the ability row, so
  `breakdown["auto_attacks"]["count"]` means plain, non-empowered attacks.
  Anything needing the fight's true attack count adds back the empowering
  abilities' `casts x hits`. On-hit, proc and stacking-DoT rows are deliberately
  not re-attributed, because the empowered attack really does trigger them.
- **An empowered attack that REPLACES the swing rides `auto_attack_conversion`,
  never an added damage row.** Sylas P deals 130% AD + 30% AP magic as the
  attack's whole damage; pricing it as a bonus row invents roughly one full auto
  per swing and mitigates the real swing against armor instead of magic
  resistance. The module supplies only the non-AD remainder,
  `bonus_raw = 1.30 x AD + 0.30 x AP - AD`, and the engine's swing path keeps the
  AD term, crits and mid-fight AD changes. A ratio at or above 100% AD is the
  tell that a row is the attack's damage and not a bonus.
- **A recast has the same cast count as its parent** (Ambessa Q2).
- **Any ability whose damage keeps ticking after the cast declares
  `dot_duration`**, its tick tail in seconds, or item burns end early. Cassiopeia
  Q and W against Blackfire Torch and Liandry's is the case. `simple_damage`
  takes `dot_duration=`, and a zone DoT uses the same duration its damage
  assumption uses.
- **A `%max HP`, `% current health` or `% missing health` component hides in the
  ability description** and is easy to drop (Ambessa Q2). Check every description
  for one.
- **A passive whose bonus is "% of the attack's damage" is multiplicative with a
  modified attack ratio, not additive.** Ashe P with Q active is
  `AD x flurry_ratio x (1 + crit_bonus)`; the additive form agrees only when
  `ad_ratio` is 1.0.
- **Verify the effectiveness ratio on any crit-scaling ability.** Akshan R scales
  crit chance and crit damage at 30% effectiveness, so 100% crit chance is 30%
  more damage.
- **An empowered auto passive with a proc cooldown is a configurable proc count,
  not a per-auto rider** (Aatrox P, through the `passive_procs` option).

### Engine coupling

- **An ability's own shred must not reduce the resistance its own damage meets.**
  Process a `target_debuff` after the source ability's damage, inside the cast
  order loop, so only later abilities benefit (Kog'Maw Q).
- **Every per-ability side effect in the rotation loop is gated on the ability
  having been cast.** `auto_attacks_only` and zero-uptime timed fights both leave
  `num_casts == 0` with the entry still present in `ability_damages`, and an
  ungated shred gives autos a free reduction from a spell never used. Test a new
  side effect in autos-only mode, which no golden scenario covers.
- **Penetration floors at 0; resistance REDUCTION does not.** A flat shred, such
  as Corki E or Malignance, must reach negative resistance, where
  `raw x 100 / (100 + R)` amplifies. Floor at `min(0.0, input)`, never at a hard
  0. Percent reduction must skip an already-negative resistance: multiplying a
  negative by `(1 - pct)` gives resistance back, so a shred item protects the
  target. Making negative resistance reachable is a cross-cutting change. Route
  every `* (1 -` and `max(..., 0)` on a resistance through the shared helper, and
  regression-test the monotonicity property, that more shred stacks never deal
  less damage, rather than the individual numbers.
- **An ability that applies on-hit effects must apply ITEM on-hits**, and share
  ONE hit sequence with the autos so counter-gated items such as Kraken Slayer
  and Hullbreaker advance and fire from either source, at the effectiveness of
  the hit that landed the Nth stack (Bel'Veth Q and E). Classify the trigger
  scope from the wiki notes: on-hit only against on-hit plus on-attack. The
  On-Attacking list is short and closed, holding Guinsoo's Rageblade, Navori
  Flickerblade, Rapid Firecannon, Runaan's Hurricane, Voltaic Cyclosword and Yun
  Tal Wildarrows; everything else per-hit is on-hit, and spellblade is neither.
  Each item declares its class as the registry's `counter_trigger` key, and an
  ability application declares `triggers=`.
- **Cap the triggering events, never the resolution.** A burn or DoT tail lit
  inside the fight resolves in full, and `count_damage_after_fight_end` is the
  one switch over that, so a `min(..., fight_duration)` on resolved damage is the
  failure shape. The golden sweep's build scenarios hold no burn items, so a
  timed-burn regression produces zero golden diffs.
- **A champion module does not `.get(..., default)` a stats key.** Akshan E read
  a `bonus_attack_speed_percent` key nothing writes and priced its attack-speed
  term at 0. A missing stats key raises or comes from `stats.py`.
- **A wiki unit spelling absent from `champions/scaling.py`'s `_SIMPLE_UNITS`
  falls through to `0.0` and drops the term silently.** "% of maximum health"
  against "% maximum health" zeroed Rumble W and Galio W outright. Add the alias
  and check the blast radius.
- **Never expose a per-ability override of a value another system derives.**
  `hemorrhage_stacks_override` let Darius R read 5 stacks while the
  `StackTimeline` kept Noxian Might off, underpricing every slot. Take ONE input
  describing the state, as `starting_hemorrhage_stacks` seeds the timeline, and
  derive both consumers from it. Assert the invariant at every option value, not
  one number.
- **A new breakdown row uses the unified shape** `count`, `damage_per_hit` and
  `unit`, plus an optional engine-minted `detail`. `app.py`'s whitelist row
  builder silently drops unknown keys, so verify a new row type end to end
  through `POST /api/calculate`.
- **A row riding the auto stream must carry the prefix the split understands.**
  `damage.py::split_auto_vs_ability` buckets by the `auto_attacks`, `on_hit_` and
  `spellblade_` prefixes, and everything else falls to ability damage, which is
  invisible in the total. Assert a new row's bucket, not just its total.
- **An ability row carrying basic-attack swings sets
  `DamagePart(basic_damage=True)`** so both pricers apply `state.basic_amp` and
  accumulate `state.basic_amp_ability_bonus`, the Caitlyn headshot case against
  Hexoptics C44. Spell-classified rows stay unflagged.
- **Cast times share ONE timeline.** `damage.py::_schedule_shared_casts` runs
  cooldowns from cast end with ties broken by cast order, so other abilities'
  cast times displace a spam spell: Cassiopeia's 0.75s E fits about 3 casts in 3
  seconds, not 5. Sanity-check a new champion's timed cast counts against
  `duration / (cast_time + cd)` and expect displacement. A pinned total captured
  under a superseded engine model embodies that model's defect, so re-derive it
  rather than widening the tolerance.
