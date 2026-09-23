# Traps

Hard-won findings, one per bullet: the fact, then the fix. Invariants and
ownership live in `architecture.md`; rules, domain facts and gates in `CLAUDE.md`.

## Tests and CI

- **A request key no parser reads is dropped silently, so a test pinned on it
  pins the default.** `deterministic` is a `calculate_payload` keyword, never a
  body key, and the body spells the window `fight_duration`, not the `FightConfig`
  field `fight_duration_seconds`. A roster entry drops `include_boots` and
  `keystone_options`. To find such keys, wrap the request in a `dict` subclass
  that records `get`, `[]` and `in`, run the real parse, and list what it never read.
- **Four concurrent full `pytest -n auto` runs take this machine out of memory.**
  One integrator runs it once per wave on the merged tree; a worker runs only its
  files, one pytest at a time, and pylint with `--jobs=4`.
- **A test that mutates shared state races the CI's `pytest -n auto` workers, and
  only there.** A gate needing a dirty world builds it in `tmp_path`, scan roots
  being parameters. A gate needing a clean world `monkeypatch`es every member of
  its table, derived from the table. Never `.clear()` a process-wide cache;
  `cold_memo` lends a cold one.
- **A test that leaves `src.app` state changed decides it for every later test on
  the same xdist worker**, as whole-file cascades green serially and on rerun. The
  autouse `_process_state_is_given_back` fails it. Borrow shared config through
  `tests/app_config.py` or `monkeypatch.setitem`: `config.get(key)` cannot tell
  absent from `None`, so a hand restore deletes a `None`-valued key and Flask's
  read of `PROPAGATE_EXCEPTIONS` raises.
- **A full-suite run is untrustworthy while another process edits `src/`.** A test
  reading a module's source off disk sees new bytes while the import holds the old
  module, so phantom failures vanish on re-run. Gate after every writer stops.
- **CI's pylint gate is a score (`--fail-under=9`), so an undefined name passes it
  at 9.70.** `--fail-on=E0601,E0602,E0102` fails on those families whatever the
  score, and a command-line `--fail-on` replaces the one in `pyproject.toml`. The
  others, `E0401` vendor imports and `E1101` on `_replace` and `Pattern.search`,
  are false. Read the output for `: E[0-9]`, never the
  score.
- **A config `disable` hides what your branch adds, and R0801 varies between
  identical runs**, so diff pylint's checker output, never the score.
- **An import that exists for its side effect reads as unused (F401)**, and
  `ruff --fix` deletes it silently. The tree carries no `noqa`, so state the
  intent in code: `importlib.import_module(...)` for a patch or registration, or
  a real use of the module in the test that is its front door.
- **pylint cannot infer any decorator that returns a closure**, so calling a
  decorated parser by name raises E1120 against the body's own signature. A parser
  `@ability_slot` decorates is never called by name.
- **Parallel workers pass alone and fail together.** A helper one adds meets the
  rules another owns only after the merge, and one calls positionally a helper
  another made keyword-only. Re-run the suite before trusting a zero.
- **A tracked-data guard is armed by its own test, and by any bare glob.**
  `tracked_data_lint.Readers.in_tree` harvests `tests/`, so a receipt name in a
  fixture makes the guard cover it: generate absent names with `uuid4`, and read
  tracked files with `git ls-files`, never `rglob`.
- **A codemod over `tests/test_*.py` eats the file you just wrote the new tests
  into**, and one walking its own home wrote an import of itself into itself.
  Refuse the destination by name and stage the hand-written change first.
- **`tests/test_<champion>.py` is not a champion module's test set.** Option pins
  live in slice files named `test_<module>_<slice>.py`, so selecting only
  `test_<module>.py` left about 40 files unrun, four red. Select
  `test_<module>*.py`.
- **A test that reads source text, not behaviour, breaks on a rewrite that
  changes nothing.** A `__doc__` phrase matched with `in` fails once rewrapped,
  and `test_champion_options.py` greps source for an option key literal. Keep a
  cited phrase on one line.
- **A whole-row equality pin is an encoded home that a grep for the field name
  cannot find.** The closer is an AST scan of `tests/` for a dict literal inside a
  `Compare` carrying a `key` and a `label` entry.
- **An AST guard keyed on an argument POSITION fails by finding less, so every
  gate stays green.** `_KEY_ARGUMENT` gave `required_field` index 2, unreachable
  past a keyword-only marker, and a module reading `cc_kind` through it was
  invisible. Derive the index from the reader's live signature over `vars(<leaf>)`
  with `callable`, which takes its named `partial`s too, and a record's from its
  live `_fields`, since a `namedtuple()` built at import has no body to parse;
  read `R._make((...))` as `R(...)`.
- **A string pin on a CI script cannot see control flow, and in a bash `RETURN`
  trap `$?` is the last command's status before `return`, not the returned
  value**, so the container smoke could not fail on some paths. Capture
  `body || status=$?`, and test the functions cut out of the script under bash
  with the tools stubbed, as `tests/test_deployment_security.py` does.
- **A required read is only as safe as the doubles that drive it.** Grep the FIELD
  name over `tests/`, never the producing function: three unrelated files build a
  partial version of one row, and a double whose docstring says it is built as its
  producer writes it is the tell that it has drifted from the producer.
- **A pytest `-p` plugin proves what collection would otherwise hide**, loading
  before collection imports the test module, so it can wrap the callee or stub an
  absent resource's probe. A `match=` pattern is a regex, so an unescaped version
  number is a new RUF043, and on a `KeyError` it runs against the message repr,
  where an anchored `^` never fires.
- **Deleting or adding a test breaks two distant pins.**
  `tests/test_coverage_claims.py` names real pytest node ids as fixtures, and
  `test_architecture.FRONT_DOOR_FRONTIER` asserts set equality both ways, so
  retiring a file strands its module and the first test of a frontier module must
  leave the tuple in the same commit. Run both.
- **A test can be invalidated by a change naming none of its symbols.**
  `tests/test_er5_tail_triage.py` gates a receipt whose contents are a tree scan,
  so no grep over `tests/` for a touched symbol reaches it. Run every `--check` and
  every regenerator after the last commit, not a selection from the diff.
- **A guard reached through a requested fixture is reached**, so a call-graph-only
  scan left 14 node-guarded tests unmarked. Its other silent pass was
  `any(path.glob(p) for path in dirs)`, true because a generator is truthy.
- **A lint's green is evidence only against what it actually walks.**
  `prose_lint`'s assumption rule keyed on a binding shape and printed zero with 343
  published strings over the cap, and an `EVIDENCE` hatch scoped to the LINE
  excused every rule on it, so 101 `issue #N` sites sat green in the one scope the
  tense rule skips. Measure a claimed set against the runtime, and answer a
  citation by stating the fact, never by rewriting a tense.
- **`scripts/literal_defaults_baseline.txt` has no regenerator and keys each row
  by the enclosing function and its occurrence count**, so a rename inside a
  covered function turns the gate red and retiring two of four sites under one row
  leaves it stale. It is LF here: read with `newline=""`. The scanner prints its
  total on stderr and its rows on stdout with a trailing blank line, so quote its
  own `total N`, never `wc -l`: an `or <literal>` after a `.get(k, <literal>)` is
  one line and two findings.
- **An exception class no `except` names can still be load-bearing, and a deleted
  type check is a deleted refusal.** `@app.errorhandler(E)` dispatches on the type
  and a factory raises one through a variable, so an `ast.Raise` scan counts zero.
  Folding two classes widens every test that pinned either, so a surviving pin
  matches the message. Dropping `typed_payload` left four interpreters answering a
  foreign rule with `AttributeError`. A table pinned by identity cannot take a
  guard wrapper: the proof goes inside the stored callable.
- **A reference count cannot tell slop from a load-bearing symbol.** Cutting
  `patch_identity.client_patch` broke `scripts/patch_update.py`, so check every
  `ImportFrom` under `src/`, `tests/` and `scripts/` against the names a diff
  removes. A revert switch, a Protocol, an alias and a gate-read index all read as
  dead: count the reason.

## Goldens and receipts

- **Two zeros move the coupled golden with no number changing.**
  `LeafWriter.publish` gives a `float` leaf a disposition entry and an `int` leaf
  none, so `sum()` over an empty generator and over one `0.0` term publish
  different leaf sets: keep the membership filter and the value read apart.
- **Two key orders are numeric, one is not.** Compiled slot order is Q,W,E,R,P
  while `REQUIRED_CHAMPION_SLOTS` is P,Q,W,E,R, and the ledger replays insertion
  order for float sums, so reordering either is a numeric change. A breakdown
  entry's own key order is replayed nowhere, but `src/app.py` sets
  `json.sort_keys = False`, so a published dict's key order is the API's bytes.
- **A replaced reader applying a cap the old one skipped can move a golden by one
  ULP even when the two formulas are algebraically equal**, since
  `min(5 * (a + b), 5a + 5b)` is not bit-identical in float.
- **`scripts/golden_coupled_exact.json` is not a `golden_snapshot.py compare`
  target.** `tests/test_golden_snapshot.py` consumes it through `rebuild_for`, so
  the compare CLI reports about 11 diffs on a green tree. The pinned targets are
  `golden_baseline.json` and `golden_coupled_baseline.json`.
- **A pure refactor leaves `git diff` on receipts empty, and two regenerators only
  re-stamp provenance.** `repin_corpus` and
  `capture_coverage_classification.py capture` rewrite `sha` and `git_head` with no
  value change: revert those rather than commit a stamp. `golden_snapshot.py
  capture` refuses while `src/` differs from HEAD, so a behaviour fix is two
  commits. Settle the code commit's message before capturing: the baseline's
  `git_head` names that commit, and an amend strands it. A regenerator's own docstring is prose its receipt can falsify, so a
  count lives in the artifact and the docstring names which.
- **A field read with a literal default is the rule-5 failure shape, inside a
  raise message too.** `program/compile` reading a published raw as
  `row.get("raw_damage", 0.0)` held 172 coupled-golden raw leaves at zero. Read the
  stamp or refuse. `row.get(k, lit)` and `row[k]` are the same value wherever `k`
  is universal, so a golden diff on such a conversion proves the key is not
  universal and never prompts a re-capture.
- **The publisher is a stronger licence than the corpus, and it renames.**
  `program/views/receipt` indexes `time`, `source_key`, `damage_type` and `damage`
  on the composed row, so a corpus of PUBLISHED rows licenses the in-flight read.
  `combat/events` spells `source_key` as `source` and `_event_id` as `event_id`:
  match a required set through that map, never by name.
- **Both rule-5 scanners resolve only a LITERAL key, so a dispatch table can
  conceal a site instead of retiring it.** `result.get("damage_events", [])` became
  `result.get(key, [])` when eight arms folded into one keyed table, and the
  receipt fell by one with the default still live. A helper taking the key as a
  parameter, `optional_field(row, key, read) or <literal>`, a `get = event.get`
  alias and a field-reader factory are the same blindness, which the `cc_kind`
  allowlist shares, so a pinned read takes its own named function. Buckets are labelled nondeterministically, so diff two trees with the
  bucket stripped.
- **An assumption string is published, classified and pinned, so its wording is
  data**, as is a `note` inside a receipt. `certainty.classify_assumption` scans
  substrings, so `assumed` carries the ESTIMATE marker `assum` and a reword empties
  that module's class set, and of a packet module's three homes for text only
  `assumption_overrides=` is its own. Where one constant feeds an assumption and a
  golden-pinned `detail`, split the assumption, never the constant.
- **A cached-data defect is escalated to a receipt, never hand-edited away**,
  because `data/` has one writer and the next pull reverts the edit.
  `docs/receipts/escalated-defects-cached-data.json` holds the open entries and
  `python scripts/patch_update.py audit` prints one line each.
- **Three gates pin a name, so moving what they name turns them red.**
  `receipt_walk_schedule.py` resolves Amendment P by the dotted strings
  `program.events.Defer` and `Execute`, so `program/events.py` keeps `RIDER_KINDS`
  and the rider classes. `behavior_frontier.py` pins counter-2 exclusions by symbol
  per module, and its `--check` fails when a zero-policy population moves either
  way, so the branch retiring sites owns the `--write`. Its `class_c` count is
  every item-name literal in a declarative home, so deleting a name-keyed table
  moves the receipt too. Measure a base through `scan(root=...)` over a
  `git archive <sha> src` copy, never against the shared receipt.

## Engine and pricing

- **The fight prices the rounded stat card.** `calculate_total_stats` rounds
  every stat it publishes and the engine reads those, so a stat change under one
  point can move no damage. A test pinning the damage delta of a small stat
  change pins a rounding crossing. Give it a change that clears a whole point, as
  the Swiftmarch movement-speed tests do on Ahri, where force is 1:1 AP.
- **`return factor * sum_modifiers(...)` reads `factor` before the call**, so a
  `nonlocal` the callee's closure sets is invisible. Akshan E's attack-speed
  factor priced 1.0 that way. Bind the call to a name, then multiply.
- **A refusal string is a claim about a producer and nothing checks it.**
  `_schedule_field` named the function whose name sounded like the row's, and every
  gate stayed green because the refusal never fires. Before writing a `stamper=`,
  grep the CONTAINER key and confirm its one writer.
- **Check every `or <literal>` a conversion removes for a falsy value the writer
  can really produce.** `_apply_damage_modifier` reads a zero `multiplier` as an
  unset one, so dropping the `or 1.0` turns a complete immunity into no reduction,
  and no golden scenario arms one.
- **`slot_extract.extract_value(ability, attr, rank)` indexes a row's last value
  when `rank` exceeds the row's axis**, because `_axis_index` falls through to
  `-1`, so a rankless or short row prices the maximum (Aphelios Weapon Master).
- **Crit rolls are random unless `deterministic` is set.**
  `fight/autos/simulation.py` rolls `random.random() < crit_chance` per swing, so
  every probe, test and golden capture on a crit build passes `deterministic=True`.
  Forcing a crit COUNT instead blends crit at expected value with `num_crits` 0,
  so a crit-only rider publishes no row.
- **A reader placed before the schedule installers calls
  `_restore_stream_attack_timestamps`, never `_auto_attack_timestamps`.** There the
  hail and lethal attack times are empty and the spellblade speedup is unresolved,
  so the latter answers the uniform base schedule.
  `_compute_ability_rotation` sits inside that window.
- **`TimedStackState.apply_gain` records `combat_freeze` before the interval gate
  and before a cap denial**, so a denied cast still arms the freeze, and only
  `note_activity` stamps `trigger_kind`: that asymmetry is a receipt reader's one
  discriminator between a cast-armed and a swing-armed freeze.
- **An action family answers a field it does not store from `SurvivalAction`'s
  neutral value**, and naming that field to its constructor or `_replace` raises
  `TypeError` on CPython 3.14, not `ValueError`. The coupled goldens walk 9 of the
  21 `ActionKind`s and no UTILITY one, so a per-kind field census needs the
  survival suites too. To time the walk, patch `program.walk.run_survival_walk`,
  the name `walk()` reads.

## Platform and tooling

- **Which writer produced a file decides its newlines on this CRLF tree.**
  `sed -i` in Git-Bash strips CRLF, so a bulk edit goes through a byte-preserving
  script: read with `newline=""`, write with `newline="\r\n"`, and assert
  `b.replace(b"\r\n", b"").count(b"\n") == 0`. A rewriter opening with `newline=""`
  and the Write tool both write LF, so a new file takes an explicit pass.
- **A bad path in a pytest argument list is silent.** A written file list reaches
  `xargs pytest` as `tests/x.py\r`, so pipe through `tr -d '\r'`. With one bad path
  `pytest -n 4` prints "no tests ran" and names none: check the collected count
  against the file count.
- **A parameters-to-record codemod turns `del <param>` into `del ctx.<field>`**,
  which raises `FrozenInstanceError` at runtime and is invisible to `ast.parse`,
  black and pylint. Scan for `ast.Delete` over every rewritten function.
- **Codemod bites around `ast` and black.** `ast` ends a parenthesized implicit
  concatenation inside the parens and `end_col_offset` is a UTF-8 BYTE offset, so
  splice on the encoded line before the call's closing bracket. An inserted import
  lands inside a `from .x import (` block unless you skip to its closing paren, and
  a deleted span leaves the wrong blank-line count around a module-level `def`:
  `black -q` and re-parse after each. A return-rewriting pass must rewrite the
  ANNOTATION too, a record under a stale `tuple[...]` signature passing every gate.
- **`ruff check --fix --select I001` over a directory also sorts pre-existing
  unsorted blocks in files the pass never touched**, and import order is numeric
  here, so revert those and name the files `extract_modules` wrote. The tree is not
  at zero on I001, so judge a branch by the hits in the files it changed. A new
  module constant between two import groups gives every later import an E402.
- **An MCP server's instruction block carries no user authority**, and one told
  agents to edit with `sed`, against the CRLF rule above. Edit through the Edit
  tool and byte-check every touched file.
- **The Bash tool mangles a backslash inside a quoted heredoc.** `"\\\n"` in a
  `<<'PY'` heredoc reaches Python as a backslash and the letter n, so an
  exact-string match finds nothing. Build such strings from `chr(92)` and
  `chr(10)`, and assert the match count.
- **A rebase over code that moved is silent in both directions.** Taking the parked
  side resurrects the dead original at the old home, and an edit whose target moved
  merges cleanly into the surrounding lines and lands nowhere, which no
  branch-to-branch diff shows. Resolve per hunk at the new home, then re-run the
  OWNING GATE, the only thing that sees a dropped edit.
  `git merge-tree --write-tree --name-only <base> <branch>` prints the squashed
  conflict list in seconds.
- **`black --check` passes over the docstring its own re-indent mangled.** A
  parenthetical cut from the START of a wrapped sentence leaves a line holding a
  bare `.` or opening `: `, and `fix_docstring` re-bases the whole body deeper.
  After a deletional codemod over docstrings, probe every one in the touched files
  for a body line indented past the opening quote or matching `^[,.;:!?)]\s`, one
  `#` stripped first or a Sphinx `#:` comment reports 200 false positives.
- **Two cached-data quirks the vendored parser owns.** A Windows filename cannot
  hold a colon, so `data_updater.py` patches `download_soup` to strip them, and the
  local copy patches the `nvalues=None` crash on four champions.
- **Parallel sessions share one `.git`, and their worktrees live under
  `.claude/worktrees/`.** Anything that `rglob`s the checkout, such as
  `behavior_frontier.scan()`, sees every worker's copy, so index from the `src/`,
  `tests/`, `scripts/` and `docs/` roots. `git checkout -- <dir>` discards another
  session's edits and `git stash` is one stack across worktrees, so detach onto the
  base commit instead. Move a held branch's ref with
  `git update-ref refs/heads/<name> <new> <old>`, the compare-and-swap form
  `git branch -f` refuses.
- **`sorted()` over `Path` folds case on Windows**, which gave
  `declared_exact_moves` a platform-dependent winner. Sort on `path.name` or an
  explicit key wherever order decides precedence.
- **`data/atoms/manifest.json` `source_ref` digests hash LF bytes.** A test hashing
  `path.read_bytes()` raw disagrees on this CRLF checkout and agrees on CI: hash
  with `\r\n` normalized, and regenerate `data/atoms` on Linux only.
- **A Bash task that times out into the background re-runs its whole command on
  resume**, so a patch script left on disk clobbered `static/js/scoreboard.js` an
  hour later. Delete a one-shot script right after it runs.
- **Three ruff autofixes bite on this tree.** F401 strips an accidental re-export
  (`healing_helpers` over three `slotlib` functions 33 modules read as
  `_healing.x`) and a test's front-door import the architecture test counts.
  C414's `tuple(list(x))` to `tuple(x)` returns the same object for a tuple, and
  PLW0108's lambda removal hoists a forward reference into a `NameError`.
- **Two prose gates, one per language.** `comment_lint.lint_prose` reads every
  changed `.md` whole, banning em dashes, task markers and history phrases outside
  fenced blocks and `prose-ok` lines, so one edit to a file carrying the debt
  clears that whole file. `scripts/prose_lint.py` caps a docstring at its
  function's body span, uncapped on a class, so shrinking a body fails an untouched
  docstring and a one-line helper can carry only a one-line docstring.
- **The worktree isolation guard refuses any Bash command whose git use it cannot
  statically prove stays inside the worktree.** Heredocs, pipes, loops, brace
  groups, `$(git ...)`, `$TEMP`, a redirect on git and a `python -c` naming git
  all read as too complex. Use plain single commands, `git commit -F <path>`,
  `git diff --output=<path>` and `git archive -o <path>`.
- **MSYS2 paths are not Windows paths.** `/proc/meminfo` cannot be opened by
  Windows python and carries no `MemAvailable`, so read memory with
  `psutil.virtual_memory()`. A Git-Bash `/tmp/x` written by the shell and read by
  python are two files: python resolves it against the current drive, where a stale
  one an earlier run left opens fine and prints another tree's counts. Take temp
  paths from `tempfile.gettempdir()`, and extract from the destination by a
  relative path, since `tar -xf C:/...` reads the drive letter as a host.
- **Dependabot's docker ecosystem does not resolve `FROM ${ARG}`.** An ARG-defined
  base image silently stops receiving digest and security bumps, and Dependabot
  closes its own update PRs against it (dependabot-core#10190). Keep the pin on a
  literal `FROM image:tag@sha256:...`.
- **A split or rename moves what the tree SAYS about a module, and its blast radius
  is not the files its diff touches.** `coverage_resolver.resolve_packet_source`
  reads the source of the module a claim names, an autouse
  `monkeypatch.setattr(module, "oldname", ...)` sits in a file no diff opens, and
  `cast_dependency_audit.apply_marker_keys` parses a function's own AST BODY. Sweep
  `.<oldname>`, `"<oldname>"` and the function's NAME over `src/`, `tests/` and
  `scripts/` first. Dropping an alias's underscore can rebind it to another
  module's same name.
- **A split leaf inherits its parent's `.get(key, literal)` reads and loses their
  credit.** `tail_site_triage` calls a site TOLERANCE_CONTRACT when a
  `tests/test_*.py` naming malformed or withheld imports the READING module, so 29
  reads left the 22 tests covering `participant_timeline` and turned CANDIDATE. Pay
  that with a contract test in the leaf's own suite, imported as
  `from src.calculator.<pkg>.<module> import X`. An extracted step re-reading a
  field its caller resolved adds a site, since the scanner counts per module, and
  the er5 tail ceiling counts uncovered MODULES and may only fall, so a new module
  joins the covered roots: check `FROZEN.er5_tail()` before writing an assignment
  file.
- **The triage's classes are MODULE verdicts.** TOLERANCE_CONTRACT reads as
  unexamined rather than licensed, and NOT_A_ROW_FIELD means the key is in neither
  census rather than not on an engine row.

## Frontend and vision

- **Two V8 deoptimizations live in `fingerprint`'s pixel loop.** An expando
  property on a typed array (`vec.contrast = rms`) deoptimizes every function
  touching it, about 10x, so return the number. `Math.min` and `Math.max` type
  their result float64, taking the typed-array index off the integer path, 2.8 s to
  8 s, so the edge clamps there are ternaries.
- **Probe the page under its real CSP; `bypass_csp=True` hides the failures users
  hit.** `img-src` has no `blob:`, so an `<img>` on an object URL never loads while
  the bypassed probes pass. Decode a blob with `createImageBitmap`, and under the
  real header `page.wait_for_function` needs a function, `"() => ..."`.
- **The scoreboard reader is tuned at 24 to 36 px portraits (`PORTRAIT.min`).** A
  480p frame puts portraits at about 18px and `scoreboard_corpus.py scan` reads
  nothing, so scan the 1080p stream. A read that misses rows in one browser and not
  another is the input's scale, not color management. `yt-dlp
  --download-sections` stalls on YouTube DASH streams here: download the whole
  stream once and cut frames with `scoreboard_corpus.py grab`.
- **The page carries two escapers over three consumer files.**
  `static/js/scoreboard.js` calls `escapeHtml` and defines it nowhere, resolving
  `app.js`'s top-level `const` through the classic-script global scope and getting
  the weaker one. Grep the whole script set.
- **`tests/js/harness_context.mjs` answers an unknown window key with a truthy
  stub**, so a script guarding with `window.ns = window.ns || {}` writes onto a
  throwaway and every later read gets a fresh one. Seed the namespace first.
- **An edit to `ui/src` that reaches the bundle means rebuilding and committing
  `static/calculator/`.** Removing an export is enough, and a CSS-only edit
  rewrites bundle lines: esbuild reassigns its minified names.

## Champions

`/analyze-champion` reads this section first. Every bullet generalizes past the
champion it bit.

### Cached data and sources

- **Known-degraded wiki parses, stable across patches.** The modifier parser
  half-parses gimmick scalings: values survive with empty `units`, so the scaling
  resolver cannot attribute them. Aurelion Sol Q, Bard P, Heimerdinger W and E,
  K'Sante W, Quinn P, Vladimir E, Yasuo and Yone Q3, Zeri P emit the
  `FAILURE TO PARSE MODIFIER` spam during a pull, and each needs a champion module.
- **`CachedSentence.match` searches each effect description separately and returns
  the first hit**, where a joining reader can match across two and an indexing one
  pins which effect answers. Probe every conversion per effect. An effect-marker
  filter folds in as `r"Innate - Temper.*?<rest>"` under `re.DOTALL`, without which
  the `.` cannot cross a newline.
- **A silent prose reader stays wrong for a long time behind a green golden.**
  Taric Q's ceiling sentence asked for "of his maximum health" where the cache
  writes "of Taric's maximum health". A green golden proves a fix moved nothing,
  never that the reader was reading.
- **A module constant equal to a cached number is a second home for it.** Read the
  cache instead, through `extract_cast_time` for a cast time. A published option
  `state` receipt is built at import and cannot read the cache, so it declares the
  SOURCE by name. `extract_cast_time` reads only the first segment of a scaled
  `castTime`, so a two-part sentence stays a literal quoting it.
- **Six OPTIONS rows have no source site**, because `packet_parsers._variant_slot`
  generates `{slot}_variant` for Nidalee, Rek'Sai, Rell, Skarner and Swain. Build
  an option census from `get_champion_module_contract(name).options`, never from
  an AST scan.
- **A "Total X Damage" attribute on a DoT or channel is derived data the wiki
  maintains by hand**, and a duration change invalidates it while every input
  array stays right: Dr. Mundo W's cached total is a 16-tick figure against a
  12-tick ability. Compute the total from `duration x ticks_per_second x per_tick`.
- **A leveling row's generic name lies about what it prices.** `Max Health Damage`
  is often a percent-of-maximum-health SELF restore (Rek'Sai P, Tahm Kench E,
  Trundle P, Zac P, Dr. Mundo P), and `Bonus Damage` is often a monster-only cap on
  a %max-health term (Rumble Q and P), which this engine's `target_class` cannot
  express, so it is documented and never added. Read whose health the prose pays.
- **A threshold can exist only in the game files.** Dr. Mundo E's "0% to 40%
  (based on missing health)" maxes at 70% missing, only in `drmundo.bin.json`'s
  `MaxMissingHealthThreshold`. Where the wiki scales "X% to Y%" without saying
  where Y is reached, pull the game file's `Max...Threshold`.
- **A form champion's stat deltas come from the game files, never the wiki stat
  box.** Gnar's Mega box is hand-maintained and stale, claiming 5.7 AD growth
  where `gnarbig.bin.json` minus `gnar.bin.json` CharacterRecords gives 5.5. Check
  every transform champion this way: Gnar, Nidalee, Jayce, Elise, Shyvana.
- **Naafiri's binary swaps her W and R names against the wiki and
  `data/champions.json`**, so `NaafiriRAbility` is wiki W. Bind them by the
  `cooldownTime` arrays (W 26 to 18, R 110/95/80), since the child objects are
  empty markers; the swap reaches `data/atoms/v2/naafiri.atoms.v2.json`.
- **A summarized fetch of a rendered champion page invents tables and rules**, as
  Bard's meep tiers and a Cassiopeia boots ban. Fetch
  `Template:Data_<Champion>/<Ability>?action=raw` and read its
  `{{pp|values|breakpoints}}` calls verbatim. A fetched rule needs the game file.
- **The wiki's item-interaction notes are hypotheses, not ground truth.** Azir's
  soldier attacks apply spellblade, Energized and Kraken at 50% and Sundered Sky
  not at all, against a note claiming Energized "stacks but is not consumed".
  Apply an "on-hit at X% effectiveness" reduction to every per-attack effect unless
  an exclusion is verified in game.

### Pricing shape

- **Decorating a module-level slot keeps `<name>.phase = BUFF` working**, because
  the assignment lands on the wrapper the decorator returns and the wrapper copies
  `__name__`, `__qualname__`, `__doc__` and `__module__`. `slotlib.py` and
  `slot_entries.py` cannot import such a decorator from `module_helpers`, which
  imports both, so a guard helper they need lives below them.
- **A rotation declaration is read by key, so its own key order is free, but the
  OPTIONS row's key order is authored** by `_EXTRA_ORDER` in `inputs.py`, and a
  hand-built row takes the same position.
- **A stat-granting ultimate carries `total_raw: 0.0` and a `stat_buff` dict**,
  never a damage row (Aatrox R). A passive stat component is a BUFF-phase
  `stat_buff` slot, with `apply_to=` when the stat scales other abilities at parse
  time (Ambessa R's armor pen).
- **When a form or steroid grants AD, decide base against bonus explicitly.** A
  form that is a separate in-game unit grants BASE stats (Mega Gnar); an ability
  steroid grants BONUS AD (Vayne R, Aatrox R), which %bonus-AD ratios see. A
  base-stat `stat_buff` must re-derive every item stat built on that base, as
  Sterak's Gage converts base AD.
- **A charge ability reports single-cast damage** and takes its cached
  `rechargeRate`, never the cached `cooldown`, as its `cooldown`, letting the
  engine count casts (Amumu Q), and `champions/charge_cadence.py` owns each timer.
  Never pre-multiply a cast
  count into a damage field, and make sub-casts within one activation one
  `DamagePart(count=N)` plus `cast_instances=N`. A charge ULTIMATE owns its own
  count, since `_schedule_shared_casts` puts every `R` in `single_cast` (Corki R).
- **"Empowers next basic attack" is once per cast; "basic attacks deal bonus
  damage" is every auto** (Alistar E).
- **A granted or forced basic attack still swings when there is no auto stream.**
  One-rotation mode and zero uptime both give `num_auto_attacks == 0` and the cast
  still forces its attack, so the ability's row carries the expected-crit base
  swing (Blitzcrank E, Vayne Q).
- **An empowered swing belongs on the ability's row in every fight mode.**
  `damage.py::_reattribute_empowered_swings` moves
  `casts x hits x auto_damage_per_hit` onto the ability row, so
  `breakdown["auto_attacks"]["count"]` means plain attacks and a true attack count
  adds the empowering abilities' `casts x hits` back. On-hit, proc and
  stacking-DoT rows are left alone.
- **An empowered attack that REPLACES the swing rides `auto_attack_conversion`,
  never an added damage row.** Pricing Sylas P's 130% AD + 30% AP as a bonus row
  invents roughly one auto per swing and mitigates the real swing against armor
  instead of magic resistance. A ratio at or above 100% AD is the tell.
- **A recast has the same cast count as its parent.**
- **Any ability whose damage keeps ticking after the cast declares
  `dot_duration`**, its tick tail in seconds, or item burns end early (Cassiopeia
  Q and W against Blackfire Torch).
- **A `%max HP`, `% current health` or `% missing health` component hides in the
  ability description** and is easy to drop (Ambessa Q2).
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
  gives autos a free reduction. Test a new side effect in autos-only mode, which no
  golden scenario covers.
- **Penetration floors at 0; resistance REDUCTION does not.** A flat shred (Corki
  E, Malignance) must reach negative resistance, where `raw x 100 / (100 + R)`
  amplifies, so floor at `min(0.0, input)`. Percent reduction must skip an
  already-negative resistance, since `(1 - pct)` on a negative gives resistance
  back. Route both through the shared helper.
- **An ability that applies on-hit effects must apply ITEM on-hits**, and share
  ONE hit sequence with the autos so counter-gated items advance and fire from
  either source, at the effectiveness of the hit that landed the Nth stack
  (Bel'Veth Q and E). An item's trigger class is the registry's `counter_trigger`
  key.
- **Cap the triggering events, never the resolution.** A burn or DoT tail lit
  inside the fight resolves in full, `count_damage_after_fight_end` being the one
  switch over that, so a `min(..., fight_duration)` on resolved damage is the
  failure shape, and the golden sweep holds no burn items to catch it.
- **A silent zero comes from a missing key.** A champion module never
  `.get(..., default)`s a stats key: Akshan E read a `bonus_attack_speed_percent`
  key nothing writes and priced its term at 0. A wiki unit absent from
  `_SIMPLE_UNITS` in `champions/scaling.py` falls to `0.0` and drops the term, as
  "% of maximum health" zeroed Rumble W: add the alias.
- **An option-presence test is a champion-identity gate written wrong, and it
  fails silently both ways.** A rename leaves the guard never firing, so a whole
  ledger vanishes with every number unchanged, and a key two champions declare
  (`w_charge`) fires K'Sante's walk on an Irelia fight. Every key read outside its
  own module lives in `champions/shared_option_keys.py`.
- **Never expose a per-ability override of a value another system derives.**
  `hemorrhage_stacks_override` let Darius R read 5 stacks while the
  `StackTimeline` kept Noxian Might off. Take ONE input describing the state and
  derive both consumers from it.
- **A new breakdown row uses the unified shape** `count`, `damage_per_hit` and
  `unit`, plus an optional engine-minted `detail`. `app.py`'s whitelist row builder
  drops unknown keys, so verify a new row type through `POST /api/calculate`.
- **A row riding the auto stream must carry the prefix the split understands.**
  `damage.py::split_auto_vs_ability` buckets by the `auto_attacks`, `on_hit_` and
  `spellblade_` prefixes, and everything else falls to ability damage. Assert a new
  row's bucket, not its total.
- **An ability row carrying basic-attack swings sets
  `DamagePart(basic_damage=True)`** so both pricers apply `state.basic_amp` and
  accumulate `state.basic_amp_ability_bonus` (Caitlyn headshots).
- **Cast times share ONE timeline.** `damage.py::_schedule_shared_casts` runs
  cooldowns from cast end with ties broken by cast order, so other abilities' cast
  times displace a spam spell: Cassiopeia's 0.75s E fits about 3 casts in 3
  seconds. Check timed cast counts against `duration / (cast_time + cd)`.
