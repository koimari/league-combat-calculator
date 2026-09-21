# Traps

Hard-won findings, one per bullet: the fact, then the fix. Invariants and
ownership live in `architecture.md`; rules, domain facts and gates in `CLAUDE.md`.

## Tests and CI

- **Four concurrent full `pytest -n auto` runs take this machine out of memory.**
  Run the full suite once per wave, on the merged tree, by one integrator. A
  worker runs only the files it touched, one pytest at a time, no `-n`, with
  `--jobs=4` on pylint.
- **A test that mutates shared state races the CI's `pytest -n auto` workers, and
  only there.** A gate needing a dirty world builds it in `tmp_path`, scan roots
  being parameters (`zero_policy_frontier(root=...)`). A gate needing a clean
  world `monkeypatch`es every member of its table, derived from the table, not a
  hand-listed subset. Never `.clear()` a process-wide cache; `cold_memo` lends a
  cold one.
- **A test that leaves `src.app` state changed decides it for every later test on
  the same xdist worker**, as whole-file cascades green serially and on rerun. The
  autouse `_process_state_is_given_back` fails the test that moved a surface
  `tests/process_state.py` names. Borrow shared config through
  `tests/app_config.py` or `monkeypatch.setitem`: `config.get(key)` cannot tell
  absent from `None`, so a hand-rolled restore deletes a `None`-valued key and
  Flask's subscript read of `PROPAGATE_EXCEPTIONS` raises.
- **A full-suite run is untrustworthy while another process edits `src/`.** A test
  reading a module's source off disk sees new bytes while the import holds the old
  module, so phantom failures appear and vanish on re-run. Gate after every writer
  stops, or against a `git archive HEAD` copy, the safe way to read the branch
  base from a worktree.
- **CI's pylint gate is a score (`--fail-under=9`), so an undefined name passes it
  at 9.70.** `--fail-on=E0601,E0602,E0102` fails on those families whatever the
  score. The 13 other E-class messages are false: `E0401` vendor-path imports,
  `E1101` on a NamedTuple `_replace` and on `re.Pattern[str].search`. Read the
  output for `: E[0-9]`, never the score.
- **A bare `# pylint: disable=` at column 0 is a module-scope block disable running
  to end of file**, not a decoration on the next `def`, so dropping one token can
  surface messages in every later function. Measure with
  `--enable=useless-suppression` under the normal check set;
  `--disable=all --enable=I0021` calls every suppression useless.
- **pylint cannot infer any decorator that returns a closure**, so calling a
  decorated parser by name raises E1120 against the body's own signature, which
  only a `signature-mutators` config this tree lacks would fix. A parser
  `@ability_slot` decorates is never called by name.
- **Parallel lint workers pass alone and fail together.** A helper one worker adds
  meets the rules another owns only after the merge, and a phase one worker
  extracts calls positionally a helper another made keyword-only. Re-audit the
  tree and re-run the suite before trusting a worker's zero.
- **`pull_request` CI never runs while the PR is CONFLICTING.** GitHub cannot
  build the merge ref, so a PR behind `main` shows only Vercel checks. Catch up
  with `main` first, then read CI.
- **A tracked-data guard is armed by its own test, and by any bare glob.**
  `tracked_data_lint.Readers.in_tree` harvests `tests/`, so a receipt name in a
  fixture makes the guard cover it: generate absent names with `uuid4`. A glob
  counts as a reader only where it pins past the suffix (`names_a_family`), a
  docstring mention not at all. Read tracked files with `git ls-files`, never
  `rglob`, which races a scratch file under xdist.
- **A codemod over `tests/test_*.py` eats the file you just wrote the new tests
  into**, and one walking its own home wrote an import of itself into itself.
  Refuse the destination by name, and stage the hand-written change first so
  `git checkout -- tests/` restores it.
- **`tests/test_<champion>.py` is not a champion module's test set.** Option pins
  live in slice files named `test_<module>_<slice>.py`, so selecting only
  `test_<module>.py` left about 40 files unrun, four of them red. Select
  `test_<module>.py` or `test_<module>_*.py`.
- **A test that reads source text, not behaviour, breaks on a rewrite that
  changes nothing.** A phrase matched in a module's `__doc__` with a plain `in`
  fails once the rewrite rewraps it, and `test_champion_options.py` and
  `test_derived_champion_options.py` grep a module's source for an option key's
  literal, so typing that key turns them red. Keep a cited phrase on one line, and
  teach both scans the name.
- **A whole-row equality pin is an encoded home that a grep for the field name
  cannot find.** The closer is an AST scan of `tests/` for a dict literal inside a
  `Compare` carrying a `key` and a `label` entry. Re-run it whenever an OPTIONS
  field moves.
- **A pytest `-p` plugin proves what collection would otherwise hide**, loading
  before collection imports the test module, so it can wrap the callee or stub an
  absent resource's probe. Filter `at 0x[0-9A-Fa-f]+` out of any digest.
- **Deleting a test breaks two distant pins.** `tests/test_coverage_claims.py`
  names real pytest node ids as fixtures, and retiring a file can strand its
  module on `test_architecture.FRONT_DOOR_FRONTIER`, which asserts set equality
  both ways. Run both after any deletion, and give a module a real front door when
  a script already reads it.
- **A guard reached through a requested fixture is reached**, so
  `scripts/resource_markers.py` follows both edges where a call-graph-only scan
  left 14 node-guarded tests unmarked. Its other silent pass was
  `any(path.glob(pattern) for path in dirs)`, true because a generator is truthy.
- **A gate's name and docstring are not evidence that its body pins anything, and
  a lint claiming a published set has to be measured against the runtime, never
  against its own walk.** `prose_lint`'s assumption rule keyed on the binding
  shape `ASSUMPTIONS = ...`, so it missed `extend`, `+=` and two shared tuples,
  capped 566 strings that publish nothing, and printed zero with 343 published
  strings over the cap. Import the module, read the attribute, and diff the reader
  against it.
- **`scripts/literal_defaults_baseline.txt` has no regenerator and keys each row
  by the enclosing function and its occurrence count**, so a rename inside a
  covered function turns the gate red and retiring two of four sites under one row
  leaves it stale. It is LF here: read with `newline=""`.
  `tests/test_literal_defaults.py` names every row to drop.
- **A reference count cannot tell slop from a load-bearing symbol, and a re-grep
  that skips `scripts/` misses a live caller.** Cutting
  `patch_identity.client_patch` left `scripts/patch_update.py` unable to import,
  so check every `ImportFrom` under `src/`, `tests/` and `scripts/` against the
  names the diff removes. A revert switch holding one value, a Protocol unrelated
  dataclasses satisfy, a disambiguating alias and a derived index read by a gate
  all read as dead: count the reason.

## Goldens and receipts

- **Two zeros move the coupled golden with no number changing.**
  `LeafWriter.publish` gives a `float` leaf a disposition entry and an `int` leaf
  none, so `sum()` over an empty generator and over one `0.0` term publish
  different leaf sets: keep the membership filter and the value read separate.
  `public_response` skips a row with no damage, no amount and no `detail`, so a
  `detail` on a zero row makes it appear.
- **Two key orders are numeric, one is not.** Compiled slot order is Q,W,E,R,P
  while `REQUIRED_CHAMPION_SLOTS` is P,Q,W,E,R, and the ledger replays insertion
  order for float sums, so any reorder of either is a numeric change. A breakdown
  entry's own key order is replayed nowhere, but `src/app.py` sets
  `json.sort_keys = False`, so a published dict's key order is the API's bytes:
  rebuild a receipt in receipt order, never by appending aliases, and treat a
  `note` inside one as data, not prose. A JSON-safe copy recurses into mappings,
  which group terms, and copies sequences, which are values (Bard's tuple
  `stock_tiers`).
- **A replaced reader applying a cap the old one skipped can move a golden by one
  ULP even when the two formulas are algebraically equal**, since
  `min(5 * (a + b), 5a + 5b)` is not bit-identical in float. Check the arithmetic
  before assuming a re-enabled clamp is free.
- **`scripts/golden_coupled_exact.json` is not a `golden_snapshot.py compare`
  target.** `tests/test_golden_snapshot.py` consumes it through `rebuild_for`, so
  the compare CLI reports about 11 diffs on a green tree, including on `main`. The
  pinned targets are `golden_baseline.json` and `golden_coupled_baseline.json`.
- **A pure refactor leaves `git diff` on receipts empty, and two regenerators only
  re-stamp provenance.** `repin_corpus` and
  `capture_coverage_classification.py capture` rewrite `sha` and `git_head` with
  no value change. Revert those two rather than committing a stamp.
  `golden_snapshot.py capture` refuses outright while `src/` differs from HEAD,
  since the recorded `src_tree_sha` would name a tree it did not read, so a
  behaviour fix is two commits.
- **A field read with a literal default is the rule-5 failure shape, inside a
  raise message too.** `program/compile` reading a published raw as
  `row.get("raw_damage", 0.0)` held 172 coupled-golden raw leaves at zero, and
  `scripts/literal_defaults.py` counts one in a message like one on a live path.
  Read the stamp or refuse.
- **An assumption string is published, classified and pinned, so its wording is
  data.** `certainty.classify_assumption` scans substrings, so `assumed` carries
  the ESTIMATE marker `assum` and a reword empties that module's class set.
  A packet module's text has three homes and only `assumption_overrides=` is its
  own; `static/reviewed-packets.json` moves 76 `PACKET_SHA256` pins. Where one
  constant feeds an assumption and a golden-pinned `detail` (Mel's execute
  boundary), split the assumption, never the constant.
- **A cached-data defect is escalated to a receipt, never hand-edited away**,
  because `data/` has one writer and the next pull reverts the edit.
  `docs/receipts/escalated-defects-cached-data.json` holds the open entries and
  `python scripts/patch_update.py audit` prints one line each.
- **Three gates pin a name, so moving what they name turns them red.**
  `receipt_walk_schedule.py` resolves Amendment P by the dotted strings
  `program.events.Defer` and `Execute`, so `program/events.py` keeps `RIDER_KINDS`
  and the rider classes. `behavior_frontier.py` pins counter-2 exclusions by
  symbol per module, so drop the row and regenerate with `--write`.
  `docs/receipts/er5-tail-triage.json` counts `x.get(key, literal)` sites under
  `src/`, regenerated by `python scripts/tail_site_triage.py write`.

## Engine and pricing

- **`return factor * sum_modifiers(...)` reads `factor` before the call**, so a
  `nonlocal` the callee's closure sets is invisible. Akshan E's attack-speed
  factor priced 1.0 that way. Bind the call to a name, then multiply.
- **A charge ability's `cooldown` is its cached `rechargeRate`, never the cached
  `cooldown`.** `champions/charge_cadence.py`'s docstring is the one home for each
  timer, which slots need a reviewed `ChargeRule`, and where the banked stock
  comes from.
- **`slot_extract.extract_value(ability, attr, rank)` indexes a row's last value
  when `rank` exceeds the row's axis**, because `_axis_index` falls through to
  `-1`, so a rankless or short row prices the maximum. Check the row's length
  before a ranked read (Aphelios Weapon Master is the guarded case).
- **Crit rolls are random unless `deterministic` is set.**
  `fight/autos/simulation.py` rolls `random.random() < crit_chance` per swing, so
  every probe, test and golden capture on a crit build passes `deterministic=True`.
  It is not a drop-in for a `random.random` patch forcing a crit COUNT: that
  branch blends crit and non-crit at expected value and sets `natural_crit` False,
  so `num_crits` is 0 and a crit-only rider publishes no row.
- **The walk mutates the `actions` list its caller passes.** `run_survival_walk`
  re-reads `len(actions)` every iteration because three producers insert into it
  mid-walk, after `ledger.current_index`. That is how an action is rescheduled: a
  `NamedTuple._replace` at a new time keeps the `aidx` and event dict, so the
  ledger records one outcome. Pass a real list and read it back; a copy drops
  every walk-authored packet silently.
- **cProfile shares lie about the fight engine, and the optimizer benches cannot
  resolve a small win.** Cost is spread across millions of one-line helpers, so
  per-call overhead over-weights them roughly 2x. A memo timed over one build
  hides the miss the search pays per evaluation, and a figure at six items hides
  that the greedy search mostly evaluates partial builds.
  `scripts/bench_optimize_build.py --budget` and `--by-build-size` encode both.
- **A section-numbered citation into an append-only log is a second home for every
  number it quotes, and it drifts silently.** One was stale in two of its six
  Eclipse number groups against `item_effects.py`, with no way for the test naming
  it as source of truth to notice. Cite the accessor key.
- **A reader placed before the schedule installers calls
  `_restore_stream_attack_timestamps`, never `_auto_attack_timestamps`.** At that
  point the hail and lethal attack times are empty and the spellblade speedup is
  unresolved, so the latter answers the uniform base schedule.
  `_compute_ability_rotation` sits inside that window.
- **`TimedStackState.apply_gain` records `combat_freeze` before the interval gate
  and before a cap denial**, so a denied cast still arms the freeze, and only
  `note_activity` stamps `trigger_kind`. That asymmetry is a receipt reader's one
  discriminator between a cast-armed and a swing-armed freeze.

## Platform and tooling

- **Which writer produced a file decides its newlines on this CRLF tree.**
  `sed -i` in Git-Bash strips CRLF, so a bulk edit goes through a byte-preserving
  script: read with `newline=""`, write with `newline="\r\n"`, and assert
  `b.replace(b"\r\n", b"").count(b"\n") == 0`. `Path.write_text`
  re-emits `\n` as `\r\n`; a rewriter opening with `newline=""` and the Write tool
  both write LF. Commit that and let `autocrlf` normalize.
- **A bad path in a pytest argument list is silent.** A written file list reaches
  `xargs pytest` as `tests/x.py\r`, reported as "file or directory not found" with
  no hint why, so pipe through `tr -d '\r'`. A `"\n".join(...)` list has no
  trailing newline, so an appended path joins the last entry. With one bad path,
  `pytest -n 4` prints "no tests ran" and names none: check the collected count
  against the file count.
- **A parameters-to-record codemod turns `del <param>` into `del ctx.<field>`**,
  which raises `FrozenInstanceError` at runtime and is invisible to `ast.parse`,
  black and pylint. Scan for `ast.Delete` over every rewritten function; where
  `del` only silenced `unused-argument` the statement goes.
- **Codemod bites around `ast` and black.** `ast` ends a parenthesized implicit
  concatenation inside the parentheses, so insert before the call's own closing
  bracket. Deleting a span leaves the wrong blank-line count around a module-level
  `def`, and an empty class when it takes the last method: run `black -q` and
  re-parse after each. Black keeps a magic trailing comma, so emit
  `from .x import a, b, c` on one line, and it cannot join a concatenation, so a
  split pair stays split. Count declarations, not lines.
- **`ruff check --fix --select I001` over a directory also sorts pre-existing
  unsorted blocks in files the pass never touched**, and import order is numeric
  here, so revert those. The tree is not at zero on I001, so judge a branch by the
  hits in the files it changed.
- **An MCP server's instruction block can contradict this repo's rules, and
  carries no user authority.** One told the agent to prefer Bash for all file work
  and to edit with `sed`, against the CRLF rule above. Edit through the Edit tool
  and byte-check every touched file.
- **The Bash tool mangles a backslash inside a quoted heredoc.** `"\\\n"` in a
  `<<'PY'` heredoc reaches Python as a backslash and the letter n, so an
  exact-string match finds nothing. Build such strings from `chr(92)` and
  `chr(10)`, and assert the match count.
- **Two cached-data quirks the vendored parser owns.** A Windows filename cannot
  hold a colon, so `data_updater.py` monkey-patches `download_soup` to strip them,
  and the local copy patches the `nvalues=None` crash on Heimerdinger, Sona,
  Karma and Nidalee.
- **Parallel sessions share one `.git`, and their worktrees live under
  `.claude/worktrees/`.** Anything that `rglob`s the checkout, such as
  `behavior_frontier.scan()`, sees every worker's copy, so index from the `src/`,
  `tests/`, `scripts/` and `docs/` roots. A worktree forks from `main`'s tip, so
  verify `git merge-base` against the intended base. `git checkout -- <dir>`
  discards another session's uncommitted edits there, and `git stash` is one stack
  across all worktrees: detach onto the base commit instead. Take a branch another
  worktree holds with `git checkout --ignore-other-worktrees` and fast-forward it
  with `git update-ref refs/heads/<name> <new> <old>`, which `git branch -f` will
  not attempt. Here `git rm skill.md` also removes `SKILL.md`.
- **`sorted()` over `Path` folds case on Windows.** Two receipts sorting
  differently on Linux and Windows gave `declared_exact_moves` a
  platform-dependent winner. Sort on `path.name` or an explicit key wherever order
  decides precedence.
- **`data/atoms/manifest.json` `source_ref` digests hash LF bytes.** The corpus is
  generated on Linux and this checkout is CRLF, so a test hashing
  `path.read_bytes()` raw disagrees here and agrees on CI: hash with `\r\n`
  normalized to `\n`. The CommunityDragon bins under `data/bin/characters` are
  tracked, so the champions domain resolves locally; regenerate `data/atoms` on
  Linux only.
- **The simply-elegant hooks resolve `pyproject.toml` per-file rules against the
  main checkout**, so every edit inside `.claude/worktrees/<name>/` reports the
  exemptions as errors. Verify a worktree hit at the repo root rather than adding
  a marker.
- **A Bash task that times out and is moved to the background re-runs its whole
  command when it resumes.** A one-shot patch script left on disk ran again an
  hour later and clobbered `static/js/scoreboard.js`. Edit with the Edit tool or
  an exact-string script deleted right after. A `re.S` regex over an optional
  docblock is the same trap in one step, swallowing the file from its first
  docblock to the target.
- **Three ruff autofixes bite on this tree.** F401 strips an accidental re-export
  (`healing_helpers` over three `slotlib` functions 33 modules read as
  `_healing.x`) and a test's front-door import the architecture test counts.
  C414's `tuple(list(x))` to `tuple(x)` returns the same object for a tuple.
  PLW0108's lambda removal hoists a forward reference into a `NameError`.
  Import-check every champion module afterwards.
- **A `sightline-ok` marker covers its own line, or the whole definition when it
  sits on the `def` line.** Rule #1 reports once per signature at the `def` line,
  so a marker on the `) -> Any:` line of a multi-line signature covers nothing.
- **Sightline counts move in both directions after a record or leaf extraction,
  with no duplication added.** #14 counts typed signatures only, so extracting
  `SlotCtx` typed a 13-function clump and took the anchor from
  `slot_extract.extract_named`, and #55 reports a six-positional signature once
  its siblings stop sharing the shape. Dissolve them on the record.
- **Sightline #11 normalizes names and literals and has a size floor**, so a
  wrapper differing only in its regex is still a clone, a one-statement `main`
  counts, and `ctx.damage_events, ctx.cast_timeline` crossed the floor where the
  bare names did not. A record or a `partial` binding dissolves a clone group
  where one shared helper does not. The plugin's ruff wants `x.get("k") or ()`
  (FURB110) where the rule-5 lint reads an or-default: bind first, then iterate
  over it.
- **A codemod that writes files with Python bypasses the per-edit hook entirely**,
  and `sightline gate . --files` skips the repo-scope rules, so a cross-file #11
  passes every edit gate. Only `--full` sees it, against the branch base. One
  added import can be the whole finding: `champions/heimerdinger.py` at nine
  internal imports goes to ten and #27 fires, so a new leaf goes into one its
  readers already import.
- **Two prose gates, one per language.** `comment_lint.lint_prose` reads every
  changed `.md` whole, banning em dashes, task markers and a history phrase list
  outside fenced blocks and `prose-ok` lines, so one edit to a file carrying the
  debt clears that whole file, and most tracked markdown outside the three root
  docs and the five skill files still carries em dashes. `scripts/prose_lint.py`
  compares a docstring against its function body span, so cutting body lines
  pushes an unchanged docstring over its budget, and it scans itself.
- **A skill's frontmatter `description:` cannot hold a colon.** An unquoted `: `
  breaks the YAML, and the harness then lists the skill by its heading with no
  trigger text. Use a comma or a period.
- **The worktree isolation guard refuses any Bash command whose git use it cannot
  statically prove stays inside the worktree.** Heredocs, `git ... | xargs`, brace
  groups, `$(...)` arithmetic, a redirect on `git show` and a `python -c` naming
  git in a data literal all read as too complex. Use plain single commands, short
  `python -c` one-liners and `git commit -F <path>`, and keep scratch inside the
  worktree.
- **MSYS2 paths are not Windows paths.** `/tmp/x` and `/proc/meminfo` cannot be
  opened by Windows python, and MSYS2's `/proc/meminfo` carries no `MemAvailable`,
  so a reader of it computes 100% used. Read memory with
  `psutil.virtual_memory()`. A scan rooted at a Git-Bash `/tmp` path resolves
  against the current drive and reports every counter zero rather than failing,
  so take temp paths from `tempfile.gettempdir()`.
- **A Windows esbuild run reproduces the committed bundle byte for byte.** Compare
  a build against `git show HEAD:<path>`, never the autocrlf working file: the
  byte deltas on `calculator.js` and `calculator.css` are those files' newline
  counts, not a platform difference.
- **Dependabot's docker ecosystem does not resolve `FROM ${ARG}`.** An ARG-defined
  base image silently stops receiving digest and security bumps, and Dependabot
  closes its own update PRs against it (dependabot-core#10190). Keep the pin on a
  literal `FROM image:tag@sha256:...`.
- **`scripts/extract_modules.py` check mode refuses a checked-in assignment
  record**, reporting "not a unit of" the source because the split already landed.
  The records are review evidence, never a replay input.
- **Deleting a doc can delete the last executable copy of a command.** Put such a
  doc's code blocks through the real argument parser in a test; `shlex.split`
  needs `block.replace("\\\n", " ")` first.
- **The file-length hook measures against the committed file**, so any addition to
  a file already past the 500-line cap blocks the edit, and inside a worktree it
  reports growth on an edit that shrinks the file. Put a new pin in the small
  sibling that owns the idea; where the addition is a dict entry inside an
  existing assertion there is no sibling, so take the hit and add no marker.
- **A rename's blast radius is not the files its diff touches.** A
  `monkeypatch.setattr(module, "oldname", ...)` and an attribute read sit in files
  the diff never opens, so sweep `.<oldname>` and `"<oldname>"` over `src/`,
  `tests/` and `scripts/`. Dropping an alias's underscore can rebind it to another
  module's same name: `_coalesce_darius_q_heals` collided with the `survival`
  function the module imports plainly.
- **Cutting the `src/calculator` facade cannot reach a 100 ms
  `import src.calculator.quantity`.** `publish_rune_compilers()`, the one line that
  file keeps, pulls the 173-module champion roster through `rune_effects` to
  `champions.inputs.champion_stat`, which two `rune_paths` modules import too. The
  cut is worth about 130 ms; the rest needs `champions/inputs.py` out of the
  champions package.

## Frontend and vision

- **Two V8 deoptimizations live in `fingerprint`'s pixel loop.** An expando
  property on a typed array (`vec.contrast = rms`) deoptimizes every function
  touching it, about 10x, so return the number instead. `Math.min` and `Math.max`
  type their result float64, taking the typed-array index off the integer path,
  2.8 s to 8 s, so the edge clamps there are ternaries. Time any change against
  `git show HEAD:static/js/scoreboard.js`.
- **Probe the page under its real CSP; `bypass_csp=True` hides the failures users
  hit.** `img-src` has no `blob:`, so an `<img>` on an object URL never loads and
  every screenshot comes back "not an image the browser can open" while the
  bypassed probes pass. Decode a blob with `createImageBitmap`. Under the real
  header `page.wait_for_function` needs a function, `"() => ..."`.
- **The scoreboard reader is tuned at 24 to 36 px portraits (`PORTRAIT.min`).** A
  480p frame puts portraits at about 18px and `scoreboard_corpus.py scan` reads
  nothing, so scan the 1080p stream; `readScoreboard` resamples a larger anchor to
  `PORTRAIT.typical`. A read that misses rows in one browser and not another is
  the input's scale: rescale through `scoreboard_corpus.py read` rather than
  chasing color management.
- **`yt-dlp --download-sections` stalls on YouTube DASH streams here**, writing
  nothing for minutes. Download the whole stream once and cut frames with
  `scoreboard_corpus.py grab`.
- **The page carries two escapers over three consumer files.**
  `static/js/scoreboard.js` calls `escapeHtml` and defines it nowhere, resolving
  `app.js`'s top-level `const` through the classic-script global scope, so it gets
  the weaker one (no `'` escape, no null guard). Grep the whole script set.
- **`tests/js/harness_context.mjs` answers an unknown window key with a truthy
  stub**, so a script guarding with `window.ns = window.ns || {}` writes onto a
  throwaway and every later read gets a fresh one. Seed the namespace first, and
  gate the page's real load order in the template test.
- **An edit to `ui/src` that reaches the bundle means rebuilding and committing
  `static/calculator/`.** Removing an export is enough: dropping two moved 523
  bytes because esbuild reassigned its minified names.

## Champions

`/analyze-champion` reads this section first. Every bullet generalizes past the
champion it bit.

### Cached data and sources

- **Known-degraded wiki parses, stable across patches.** The modifier parser
  half-parses gimmick scalings: values survive with empty `units`, so the scaling
  resolver cannot attribute them. Aurelion Sol Q, Bard P, Heimerdinger W and E,
  K'Sante W, Quinn P, Vladimir E, Yasuo and Yone Q3, Zeri P emit the
  `FAILURE TO PARSE MODIFIER` spam during a pull. Each needs a champion module for
  its mechanic, so the parse fix belongs there.
- **`CachedSentence.match` searches each effect description separately and returns
  the first hit**, where a joining reader can match across two and an indexing one
  pins which effect answers. Probe every conversion, printing per effect what
  matched. Per-owner refusal messages are a dict keyed by owner over one compiled
  pattern, and an effect-marker filter folds in as `r"Innate - Temper.*?<rest>"`
  under `re.DOTALL`, without which the `.` cannot cross a newline.
- **A silent prose reader stays wrong for a long time behind a green golden.**
  Taric Q's ceiling sentence asked for "of his maximum health" where the cache
  writes "of Taric's maximum health", costing nothing only because the ceiling
  equals five per-charge heals. A green golden proves a fix moved nothing, never
  that the reader was reading.
- **A module constant equal to a cached number is a second home for it.** Read
  the cache instead, through `extract_cast_time` for a cast time. A published
  option `state` receipt is built at import and cannot read the cache, so it
  declares the SOURCE by name (`first_time_source`), not the value.
  `extract_cast_time` reads only the first segment of a scaled `castTime`, so a
  two-part sentence stays a literal quoting it.
- **Six OPTIONS rows have no source site**, because `packet_parsers._variant_slot`
  generates `{slot}_variant` for Nidalee, Rek'Sai, Rell, Skarner and Swain. Build
  an option census from `get_champion_module_contract(name).options`, never from
  an AST scan.
- **A "Total X Damage" attribute on a DoT or channel is derived data the wiki
  maintains by hand**, and a duration change invalidates it while every input
  array stays right: Dr. Mundo W's cached total is a 16-tick figure against a
  12-tick ability. Compute the total from `duration x ticks_per_second x per_tick`
  and use the cached total only if it agrees.
- **A cached `Max Health Damage` leveling row is often a percent-of-maximum-health
  SELF restore rather than enemy damage**, that being the parser's generic name
  for the shape. Read whose health the prose pays before pricing it: Rek'Sai P,
  Tahm Kench E, Trundle P, Zac P and Dr. Mundo P each carry a heal there.
- **A threshold can exist only in the game files.** Dr. Mundo E's "0% to 40%
  (based on missing health)" maxes at 70% missing health, published only in
  `drmundo.bin.json` as `MaxMissingHealthThreshold`. Where a wiki ability scales
  "X% to Y% (based on resource)" without naming where Y is reached, pull the game
  file for a `Max...Threshold`; the wiki's "Maximum ..." row cross-checks it as
  `minimum x max_amp`.
- **A form champion's stat deltas come from the game files, never the wiki stat
  box.** Gnar's Mega box is hand-maintained and stale, claiming 5.7 AD growth
  where `gnarbig.bin.json` minus `gnar.bin.json` CharacterRecords gives 5.5, and
  Gnar P's cached `leveling` is empty. Check every transform champion this way:
  Gnar, Nidalee, Jayce, Elise, Shyvana.
- **Naafiri's binary names her two upper spell slots the opposite way round from
  the live kit, the wiki and `data/champions.json`.** `.../NaafiriRAbility` is
  wiki W and `.../NaafiriWAbility` is wiki R. Bind them by the padded
  `cooldownTime` arrays (W: 26/24/22/20/18, R: 110/95/80), the only sound channel,
  because the child objects are empty markers the atomizer classifies by name. The
  swap reaches `data/atoms/v2/naafiri.atoms.v2.json` too.
- **A summarized fetch of a rendered champion page garbles progression tables and
  invents rules.** Bard's meep tiers came back invented against the game's 1 to 9
  meeps at 0/10/30/50/65/80/90/95/100, and Cassiopeia's page returned a "cannot
  buy boots" restriction it does not state. Fetch
  `Template:Data_<Champion>/<Ability>?action=raw` and read its
  `{{pp|values|breakpoints}}` calls verbatim. Numbers cross-check against the
  champion JSON and rules do not, so a fetched rule needs the game file.
- **The wiki's item-interaction notes are hypotheses, not ground truth.** Azir's
  soldier attacks apply spellblade, Energized and Kraken at 50%, and Sundered Sky
  not at all, against a note claiming Energized "stacks but is not consumed".
  Apply an "on-hit at X% effectiveness" reduction to every per-attack and
  proc-style item effect unless an exclusion is verified in game.
- **A `Bonus Damage` leveling row is often a monster-only cap, not a damage
  source.** Rumble Q's row is the per-level cap on the %max-health term, and
  Rumble P is the same shape. This engine's `target_class` has no monster value,
  so such a row is documented, never added.

### Pricing shape

- **Decorating a module-level slot keeps `<name>.phase = BUFF` working**, because
  the assignment lands on the wrapper the decorator returns and the wrapper copies
  `__name__`, `__qualname__`, `__doc__` and `__module__`. `slotlib.py` and
  `slot_entries.py` cannot import such a decorator from `module_helpers`, which
  imports both, so a guard helper those two need lives below them.
- **A rotation declaration is read by key, so its own key order is free, but the
  OPTIONS row's key order is authored.** `_EXTRA_ORDER` in `inputs.py` publishes
  `step`, `state` and `rotation`, then `derives`, `legacy_bool` and `legacy_keys`,
  and a hand-built row takes the same position.
- **A stat-granting ultimate carries `total_raw: 0.0` and a `stat_buff` dict**,
  never a damage row (Aatrox R). An ability with a passive stat component is a
  BUFF-phase `stat_buff` slot, with `apply_to=` when the stat scales other
  abilities at parse time (Ambessa R's armor pen).
- **When a form or steroid grants AD, decide base against bonus explicitly.** A
  form swap that is a separate in-game unit grants BASE stats (Mega Gnar); an
  ability steroid grants BONUS AD (Vayne R, Aatrox R). The choice decides whether
  %bonus-AD ratios see the grant and whether Sheen-type scalings grow.
- **A base-stat `stat_buff` must re-derive every item stat computed from that base
  stat.** Sterak's Gage converts base AD at build-stats time, before a Mega
  base-AD grant lands. `_apply_stat_buff_ultimates` holds the recompute hook and
  reads `item_effects.steraks_bonus_ad`.
- **A charge ability reports single-cast damage** and takes `rechargeRate` as its
  `cooldown`, letting the engine count casts (Amumu Q); never pre-multiply a cast
  count into a damage field, and make sub-casts within one activation one
  `DamagePart(count=N)` plus `cast_instances=N`. A charge ULTIMATE owns its own
  count, because `_schedule_shared_casts` puts every `R` in `single_cast` (Corki
  R), so `cast_instances` is what makes per-cast item procs count each shot.
- **"Empowers next basic attack" is once per cast; "basic attacks deal bonus
  damage" is every auto** (Alistar E). Read the wording.
- **A granted or forced basic attack still swings when there is no auto stream.**
  One-rotation mode and zero uptime both give `num_auto_attacks == 0` and the cast
  still forces its attack, so the ability's row carries the expected-crit base
  swing (Blitzcrank E, Vayne Q). Cap conversions by the auto count only when autos
  exist.
- **An empowered swing belongs on the ability's row in every fight mode.**
  `damage.py::_reattribute_empowered_swings` moves
  `casts x hits x auto_damage_per_hit` onto the ability row, so
  `breakdown["auto_attacks"]["count"]` means plain attacks and a reader wanting
  the true attack count adds the empowering abilities' `casts x hits` back.
  On-hit, proc and stacking-DoT rows are deliberately left alone.
- **An empowered attack that REPLACES the swing rides `auto_attack_conversion`,
  never an added damage row.** Pricing Sylas P's 130% AD + 30% AP as a bonus row
  invents roughly one auto per swing and mitigates the real swing against armor
  instead of magic resistance. The module supplies the non-AD remainder,
  `bonus_raw = 1.30 x AD + 0.30 x AP - AD`. A ratio at or above 100% AD is the
  tell.
- **A recast has the same cast count as its parent** (Ambessa Q2).
- **Any ability whose damage keeps ticking after the cast declares
  `dot_duration`**, its tick tail in seconds, or item burns end early (Cassiopeia
  Q and W against Blackfire Torch). A zone DoT uses the same duration its damage
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
  `num_casts == 0` with the entry still in `ability_damages`, so an ungated shred
  gives autos a free reduction from a spell never used. Test a new side effect in
  autos-only mode, which no golden scenario covers.
- **Penetration floors at 0; resistance REDUCTION does not.** A flat shred (Corki
  E, Malignance) must reach negative resistance, where `raw x 100 / (100 + R)`
  amplifies, so floor at `min(0.0, input)`. Percent reduction must skip an
  already-negative resistance, since multiplying a negative by `(1 - pct)` gives
  resistance back. Route every `* (1 -` and `max(..., 0)` on a resistance through
  the shared helper.
- **An ability that applies on-hit effects must apply ITEM on-hits**, and share
  ONE hit sequence with the autos so counter-gated items advance and fire from
  either source, at the effectiveness of the hit that landed the Nth stack
  (Bel'Veth Q and E). An item's trigger class is the registry's `counter_trigger`
  key, which owns the closed On-Attacking list.
- **Cap the triggering events, never the resolution.** A burn or DoT tail lit
  inside the fight resolves in full, `count_damage_after_fight_end` being the one
  switch over that, so a `min(..., fight_duration)` on resolved damage is the
  failure shape. The golden sweep holds no burn items, so a timed-burn regression
  produces zero golden diffs.
- **A silent zero comes from a missing key.** A champion module never
  `.get(..., default)`s a stats key: Akshan E read a `bonus_attack_speed_percent`
  key nothing writes and priced its term at 0. A missing stats key must raise or
  come from `stats.py`. A wiki unit absent from `_SIMPLE_UNITS` in
  `champions/scaling.py` falls through to `0.0` and drops the term, as "% of
  maximum health" against "% maximum health" zeroed Rumble W: add the alias.
- **An option-presence test is a champion-identity gate written wrong, and it
  fails silently both ways.** A rename leaves
  `if "stardust_stacks" not in state.champion_options: return` never firing, so a
  whole ledger vanishes with every number unchanged, and a key two champions
  declare (`w_charge`) fires K'Sante's walk on an Irelia fight. Every key read
  outside its own module lives in `champions/shared_option_keys.py`, and
  `tests/test_shared_option_keys.py` fails on a literal option read elsewhere.
- **Never expose a per-ability override of a value another system derives.**
  `hemorrhage_stacks_override` let Darius R read 5 stacks while the
  `StackTimeline` kept Noxian Might off, underpricing every slot. Take ONE input
  describing the state, derive both consumers from it, and assert the invariant.
- **A new breakdown row uses the unified shape** `count`, `damage_per_hit` and
  `unit`, plus an optional engine-minted `detail`. `app.py`'s whitelist row
  builder silently drops unknown keys, so verify a new row type through
  `POST /api/calculate`.
- **A row riding the auto stream must carry the prefix the split understands.**
  `damage.py::split_auto_vs_ability` buckets by the `auto_attacks`, `on_hit_` and
  `spellblade_` prefixes, and everything else falls to ability damage, invisible
  in the total. Assert a new row's bucket, not its total.
- **An ability row carrying basic-attack swings sets
  `DamagePart(basic_damage=True)`** so both pricers apply `state.basic_amp` and
  accumulate `state.basic_amp_ability_bonus` (Caitlyn headshots). Spell-classified
  rows stay unflagged.
- **Cast times share ONE timeline.** `damage.py::_schedule_shared_casts` runs
  cooldowns from cast end with ties broken by cast order, so other abilities' cast
  times displace a spam spell: Cassiopeia's 0.75s E fits about 3 casts in 3
  seconds, not 5. Check a new champion's timed cast counts against
  `duration / (cast_time + cd)` and expect displacement.
