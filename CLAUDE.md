# League of Legends Calculator

Three files beside this one, and each fact lives in exactly one of them:

- `architecture.md`: the module map, the pipeline, and every ownership invariant.
- `TRAPS.md`: hard-won findings, in six sections. Append a new one there, not here.
- `benchmarks.md`: every performance number.

## Important Rules

1. **vendor/lolstaticdata/ is external code**: Don't refactor or restructure it. Minimal, targeted bug fixes are OK when they block functionality (e.g., parser crashes on specific champions).
2. **Always use the caching layer**: `data_fetcher.py` reads from `data/`. Never bypass it or add network calls to it. Data updates go through `data_updater.py` and the rune pull it owns, `rune_pull.py`.
3. **All calculation functions must have corresponding tests.**
4. **Run tests before considering any task complete.**
5. **No item numbers outside `item_effects.py`**: All numeric item values come from `item_effects` typed accessors, with NO literal fallbacks at call sites (a `.get(key, stale_literal)` silently wins when the parser breaks: that exact failure hid a 3× Statikk Shiv overstatement). Missing keys must raise, naming the item and key. Runes follow the same rule through `rune_effects.py` and `rune_paths/` over `data/runes.json`; only compiled runes are selectable and everything else fails closed.
6. **Item availability comes from cached source data, never a name list**: `item_source.py` decides what an ordinary Summoner's Rift build may hold from the cached `modes` table, champion restriction, and acquisition note. An item whose sources are missing is withheld, not assumed available. Effect text lives in `passives[].branches` / `active[].branches` (every Wiki `description`, `description2`, … of one effect); read it through `item_source.effect_text`, never by indexing a single description.
7. **Named champion modules are the only runtime path**: every attacker must resolve to a validated `src/calculator/champions/<name>.py` contract. Unknown names fail closed; there is no generic or fallback parser.
8. **Item names come from the cache**: parser configuration and build scenarios use the exact names in `data/items.json`. Verify the cached name before adding an item.

## Domain Knowledge

These LoL-specific facts affect calculations and must be correct:

- **Critical strike base damage = 200%** (2.0 multiplier, not the old 175%)
- **Penetration order:** Percent penetration applies before flat penetration; result cannot go below 0
- **Lethality = flat armor pen, 1:1**, no level scaling (since V14.1; the old `0.6 + 0.4 × level/18` formula is retired). Like all penetration, it cannot reduce the target's armor below 0 for damage calculation (only armor *reduction* effects can go negative)
- **Level cap is 20** (top lane only; a seasonal rule, re-verify on patch day); the stat growth formula below applies unchanged through level 20
- **Stat growth formula:** `base + growth × (level - 1) × (0.7025 + 0.0175 × (level - 1))`
- **Attack speed:** `base_AS + AS_ratio × (bonus_percent / 100)`. AS_ratio is separate from base_AS
- **Ability haste → CDR:** `effective_cd = base_cd × 100 / (100 + ability_haste)`
- **Resistance math:** `actual_damage = raw × 100 / (100 + resistance)`. Negative resistance amplifies damage
- **True damage** ignores all resistances entirely

## Commands and gates

```bash
pytest                # Run all tests
pytest --cov=src      # Run tests with coverage
black src/ tests/ scripts/          # Format code
black --check src/ tests/ scripts/  # Formatting gate (CI runs this)
pylint src/ --jobs=4 --fail-under=9 --fail-on=E0601,E0602,E0102   # Lint gate, as CI runs it: a score, plus the undefined-name and redefinition families whatever the score
python scripts/golden_snapshot.py compare scripts/golden_baseline.json   # Numeric regression gate
python scripts/coverage_census.py check docs/coverage-census.json        # Coverage frontier gate (own CI job, 4 shards; ~1 min on 16 cores)
python scripts/prose_lint.py          # Python prose gate over src/ and scripts/: docstrings and comments hold current state, none longer than its body, no banner over an empty section, and under champions/ a 20-line module header and a 120-character assumption string. `pointer` holds every citation of the project's own history -- a phase, a decision id, a runbook rule, a review stage, a named unit of work, an issue, a pull request, a commit -- and fails unless the same line names a path that resolves and holds the citation; `history` holds the tenses alone. `pointer` is the one rule that reaches tests/, and the one that reads every string a module states: a docstring, the note under a constant, a command's help text, and published assumption text. `unsourced_constant` reports under a ceiling tests/test_prose_lint.py holds, which may only fall. It reads no markdown; the plugin hook `comment_lint.lint_prose` is the markdown one
python scripts/literal_defaults.py    # Rule-5 report: literal fallbacks on cached data. It prints every site with the bucket that licenses it and exits 1 on any, so it exits 1 on this tree. `scripts/literal_defaults_baseline.txt` holds the covered roots, the frozen sites and the uncovered-tail ceiling; tests/test_literal_defaults.py is the gate over it
python scripts/one_spelling.py        # One concept, one spelling over src/ and scripts/: the refusal vocabulary `src/calculator/quantity.py` owns (`withheld`, `starved`, `refusal`), plus `catalog`, `ally` and `holder`. Its `ALLOWED` table carries every name that keeps a banned word with the reason, and tests/test_one_spelling.py fails on an entry the tree no longer defines
python scripts/swing_stream_audit.py  # Swing-stream gate: a cached per-attack rider or Bonus Attack Speed row publishes a swing key or sits on the script's pinned FRONTIER with its reason
python scripts/patch_update.py run    # Patch day, the one orchestrator: detect/audit/fetch/bis/packets are its other subcommands (see /patch-update skill)
python scripts/bench_request.py --compare benchmarks.md  # Request-latency instrument, not a gate (its medians are one machine's); benchmarks.md is the one home for perf numbers
python scripts/build_icon_sprite.py --check   # The icon sheet the scoreboard reader matches against must cover the caches (rebuilt on patch day)
python scripts/scoreboard_corpus.py read <frame> --sheet sheet.png   # Read a scoreboard frame through the shipped matcher; docs/scoreboard-autofill.md covers scan, grab, label
python scripts/coverage_status.py --check   # docs/coverage-status.md: how much of the game is modelled on every axis, measured from the tree (--write regenerates)
python scripts/certify_damage_casts.py --check   # The authored-cast table (src/calculator/certified_casts.py) must match what the registered modules price; --write regenerates it
```

`pytest` gates every task; `pylint src/` and `black --check` gate any code change.
Formatter settings live in `pyproject.toml`, and the version is pinned in
`requirements.txt`: black's stable style shifts yearly, so an unpinned run reformats
files it shouldn't. `scripts/build_reviewed_modules.py` writes packet evidence only;
executable champion modules are named, reviewed source files.

**The golden gate is the one with non-obvious semantics**. Run it whenever calculation
code changed: a pure refactor must show zero diffs, while a behavior fix re-captures the
baseline with every diff explained in the commit.

**Lint configuration has one machine home, `pyproject.toml`.** It carries
`[tool.ruff.lint] ignore` and `per-file-ignores`, `[tool.simply-elegant]`
`comment-rules-off` and `comment-per-file-off`, and `[tool.sightline]` `excludes`
and `rules-off`, each with its reason beside it. Run the tree gate with
`python <plugin cache>/simply-elegant/1.8.1/hooks/lint_gate.py --tree . --statistics`;
from 2.0.0 the hook has no tree mode and exits 0 silently. Neither suite is at
zero, and both counts may only fall: a new finding in a file you touched is a
regression. Ruff reports 126 findings, almost all in `tests/`, and
`sightline gate . --full` reports 22 blocking above `.sightline-baseline`, under
#27, #56, #37, #32, #14, #24 and #11. The baseline holds only what is deferred
with a reason, today 53 entries under #27 (48), #14 (2) and #11 (3);
`sightline baseline .` regenerates it and merges as a union, and a sightline 0.2
binary cannot read its format. The per-edit gate `sightline gate . --files`
skips the oracle and repo-scope rules, so judge a branch by the hits in the files
it changed and run `--full` before claiming a count.

**Derived receipts are regenerated, never hand-merged.**
`docs/cast-dependency-audit.json` (`scripts/cast_dependency_audit.py --output`),
`docs/behavior-frontier.json` (`scripts/behavior_frontier.py --write`),
`docs/receipts/receipt-walk-retirement-schedule.json`
(`scripts/receipt_walk_schedule.py --write`, whose family-to-owners map
`scripts/golden_snapshot.py` reads) and `data/runes.json` effects
(`rune_pull.reparse_cached_rune_effects()`) conflict on every parallel merge.
Take either side, regenerate over the merged tree, and grep for conflict markers
before committing: a marker left in a JSON receipt makes its own regenerator
fail.

**Regenerators after a merge, in order:** runes reparse, `receipt_walk_schedule --write`,
`behavior_frontier --write`, `cast_dependency_audit --output`, `repin_corpus`,
`item_umbrella_audit --output`, `capture_coverage_classification.py capture`,
`golden_snapshot.py capture` + `capture-coupled` (+ `--exact`), then refresh the three
fingerprint blocks in `docs/receipts/campaign-fingerprints.json`, then
`coverage_census.py run --output` + `check` (~10 min).

**Where a fight number comes from: `calculate_payload(trace=True)` or
`python scripts/fight_trace.py <request.json>`.** One line per priced packet with
time, source, the catalog mechanic that priced it, raw, damage class, the
resistance it met, the amplifier and the mitigated amount, plus the `fight/` step
that authored the row. `tests/fixtures/kogmaw_dusk_and_dawn_trace.json` pins
Kog'Maw with Dusk and Dawn with zero refusals, and
`raw * 100 / (100 + resistance_met) == mitigated` holds on every line. A refusal
names the fact a producer did not stamp.

**A module split is an assignment file, never a hand move:**
`python scripts/extract_modules.py scripts/assignments/<source>.json` (check mode
by default, `--write` to apply) cuts top-level units by AST span with their
comment block, computes each new module's imports from free names, refuses
cycles, and repoints every reader under `src/`, `tests/` and `scripts/` including
`monkeypatch.setattr` dotted strings. Run black after `--write`, then both golden
compares: a split moves import order, and compiled slot order and ledger
insertion order are numeric. Fallout it cannot pay:
`scripts/literal_defaults_baseline.txt` rows, `data_registry` memo keys,
`tests/test_data_writer_inventory`'s writer set,
`test_architecture.FRONT_DOOR_FRONTIER`, `rename_evidence.EVIDENCE_HOMES`, and
the residue docstring, which must name what stays and point at the sibling that
took the rest.
