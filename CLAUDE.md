# League of Legends Calculator

Module map and pipeline: see `architecture.md`.

## Important Rules

1. **vendor/lolstaticdata/ is external code** — Don't refactor or restructure it. Minimal, targeted bug fixes are OK when they block functionality (e.g., parser crashes on specific champions).
2. **Always use the caching layer** — `data_fetcher.py` reads from `data/`. Never bypass it or add network calls to it. Data updates go through `data_updater.py`.
3. **All calculation functions must have corresponding tests.**
4. **Run tests before considering any task complete.**
5. **No item numbers outside `item_effects.py`** — All numeric item values come from `item_effects` typed accessors, with NO literal fallbacks at call sites (a `.get(key, stale_literal)` silently wins when the parser breaks — that exact failure hid a 3× Statikk Shiv overstatement). Missing keys must raise, naming the item and key. Runes follow the same rule through `rune_effects.py` and `rune_paths/` over `data/runes.json`; only compiled runes are selectable and everything else fails closed.
6. **Item availability comes from cached source data, never a name list** — `item_source.py` decides what an ordinary Summoner's Rift build may hold from the cached `modes` table, champion restriction, and acquisition note. An item whose sources are missing is withheld, not assumed available. Effect text lives in `passives[].branches` / `active[].branches` (every Wiki `description`, `description2`, … of one effect); read it through `item_source.effect_text`, never by indexing a single description.
7. **Named champion modules are the only runtime path** — every attacker must resolve to a validated `src/calculator/champions/<name>.py` contract. Unknown names fail closed; there is no generic or fallback parser.

## Domain Knowledge

These LoL-specific facts affect calculations and must be correct:

- **Critical strike base damage = 200%** (2.0 multiplier, not the old 175%)
- **Penetration order:** Percent penetration applies before flat penetration; result cannot go below 0
- **Lethality = flat armor pen, 1:1** — no level scaling (since V14.1; the old `0.6 + 0.4 × level/18` formula is retired). Like all penetration, it cannot reduce the target's armor below 0 for damage calculation (only armor *reduction* effects can go negative)
- **Level cap is 20** (top lane only, as of this season); the stat growth formula below applies unchanged through level 20
- **Stat growth formula:** `base + growth × (level - 1) × (0.7025 + 0.0175 × (level - 1))`
- **Attack speed:** `base_AS + AS_ratio × (bonus_percent / 100)` — AS_ratio is separate from base_AS
- **Ability haste → CDR:** `effective_cd = base_cd × 100 / (100 + ability_haste)`
- **Resistance math:** `actual_damage = raw × 100 / (100 + resistance)` — negative resistance amplifies damage
- **True damage** ignores all resistances entirely

## Commands and gates

```bash
pytest                # Run all tests
pytest --cov=src      # Run tests with coverage
black src/ tests/ scripts/          # Format code
black --check src/ tests/ scripts/  # Formatting gate (CI runs this)
pylint src/           # Lint code
python scripts/golden_snapshot.py compare scripts/golden_baseline.json   # Numeric regression gate
python scripts/coverage_census.py check docs/coverage-census.json        # Coverage frontier gate (own CI job, 4 shards; ~1 min on 16 cores)
python scripts/prose_lint.py                                            # Docstrings/comments: current state only, none longer than its body
python scripts/literal_defaults.py    # Rule-5 lint over the whole package: literal fallbacks on cached data (tests/test_literal_defaults.py owns the covered set `ROOTS` and the ratcheted `ER5_TAIL`)
python scripts/patch_update.py run    # Patch day, the one orchestrator: detect/audit/fetch/bis/packets are its other subcommands (see /patch-update skill)
python scripts/bench_request.py --compare benchmarks.md  # Request-latency instrument, not a gate (its medians are one machine's); benchmarks.md is the one home for perf numbers
```

`pytest` gates every task; `pylint src/` and `black --check` gate any code change.
Formatter settings live in `pyproject.toml`, and the version is pinned in
`requirements.txt` — black's stable style shifts yearly, so an unpinned run reformats
files it shouldn't. `scripts/build_reviewed_modules.py` writes packet evidence only;
executable champion modules are named, reviewed source files.

**The golden gate is the one with non-obvious semantics** — run it whenever calculation
code changed: a pure refactor must show zero diffs, while a behavior fix re-captures the
baseline with every diff explained in the commit.

## Known Quirks

- **Windows filenames:** `data_updater.py` monkey-patches `lolstaticdata`'s `download_soup` to strip colons from cache filenames (illegal on Windows)
- **Three things are named "champions":** `src/calculator/champions/` (our champion code), `data/champions.json` (our tracked data cache), and `vendor/lolstaticdata/champions*` (the scraper's gitignored scratch output — not read at runtime). See `vendor/README.md` and `data/README.md`.
- **Wiki parser bugs:** Some champions (Heimerdinger, Sona, Karma, Nidalee) previously crashed the lolstaticdata parser due to `nvalues=None` — these were patched in the local copy
- **Known-degraded wiki parses (stable across patches, fix when implementing the champion):** gimmick scalings the modifier parser half-parses — values survive but `units` come back empty, so the shared scaling resolver can't attribute them. Aurelion Sol Q (Stardust stacks), Bard P (Chimes), Heimerdinger W/E (multi-part rockets), K'Sante W (bonus resistances), Quinn P (crit chance), Vladimir E (charge time), Yasuo/Yone Q3 (crit conversion), Zeri P (execute range). These emit the `FAILURE TO PARSE MODIFIER` spam during data pulls; each needs a champion module (with options for its stack/charge mechanic) anyway, so parsing fixes belong to that work, not patch day. Gnar P (Rage Gene) is the worst case — its JSON `leveling` is entirely empty, so the Mega form stat bonuses live as tested constants in `src/calculator/champions/gnar.py` (implemented; on patch updates verify against the **game files** — Community Dragon `gnarbig.bin.json` CharacterRecords minus `gnar.bin.json`'s — NOT the wiki, whose Mega stat box has been stale before: it claimed 5.7 AD growth when the game had 5.5, and Mega's deltas are base stats, not bonus).
- **Item names:** Parser configuration and build scenarios use the exact names in `data/items.json`; verify the cached name before adding an item.
- **A published zero's *type* is load-bearing:** `program/views.publish` gives a `float` leaf a disposition entry and an `int` leaf none, so `sum()` over an empty generator (int `0`) and over one `0.0` term publish *different leaf sets*. Changing which items a stat fold iterates - not just what each contributes - moves the coupled golden with no number changing (`dream_maker_roster` `stats.ultimate_haste`). Keep the membership filter and the value read separate; `tests/test_item_effects.py::TestDeclaredSiblingReads::test_a_build_with_no_registry_item_sums_no_terms` pins it.
- **`docs/receipts/receipt-walk-retirement-schedule.json` is derived, not written:** `scripts/receipt_walk_schedule.py --write` regenerates it from a tree scan and `scripts/golden_snapshot.py` reads its family→owners map. Regenerate it, never hand-edit it.
- **Compiled slot order is Q,W,E,R,P while `REQUIRED_CHAMPION_SLOTS` is P,Q,W,E,R;** the ledger replays insertion order for float sums, so any reorder is a numeric change.
- **`interpreters._threshold_regeneration_thresholds` stops the whole `uncompilable_item_receipt` call on one broken declaration** (request-level, not per-item) — intended since 5055dc5.
- **`sed -i` in Git-Bash strips CRLF;** use byte-preserving scripts for bulk edits on this tree.
- **Agent worktrees live under `.claude/worktrees/`:** anything that `rglob`s the checkout (`behavior_frontier.scan()` indexes from `src/`) will see every worker's copy; index from `src/`, `tests/`, `scripts/`, `docs/` roots, never the repo root.
- **Agent worktrees fork from `main`'s tip, not the session's checked-out branch:** a subagent spawned with worktree isolation while a campaign branch is checked out still starts at `main`. Verify `git merge-base` against the intended base before reconciling delegated work, and have the worker merge the campaign branch itself when the base is stale.
- **Parallel sessions share one `.git`:** `git checkout -- <dir>` in one worktree discards another session's uncommitted edits in the same worktree (use one worktree per session), `git stash` is one stack across all worktrees (never stash as a base-state check — use a detached checkout of the base commit), and on this case-insensitive filesystem `git rm skill.md` also removes `SKILL.md` from disk.
- **Crit rolls are random unless `deterministic` is set:** `damage.py` rolls `random.random() < crit_chance` per swing, so two identical `calculate_payload` requests on a crit build return different auto totals (Kai'Sa: 623 / 739 / 854 / …). Every probe, test, and golden capture on a crit-capable build passes `deterministic=True`.
- **Derived receipts are regenerated, never hand-merged:** `docs/cast-dependency-audit.json` (`scripts/cast_dependency_audit.py --output`), `docs/behavior-frontier.json` (`scripts/behavior_frontier.py --write`) and `data/runes.json` effects (`data_updater.reparse_cached_rune_effects()`) conflict on every parallel merge; take either side, regenerate over the merged tree, and grep for conflict markers before committing — a marker left in a JSON receipt makes its own regenerator fail.
- **`data/atoms/manifest.json` `source_ref` digests hash LF bytes:** the corpus is generated on Linux; a Windows checkout is CRLF (`core.autocrlf=true`), so a test that hashes `path.read_bytes()` raw disagrees with the manifest here and agrees on CI. Hash with `\r\n` normalized to `\n`, and never regenerate `data/atoms` locally — the champions domain needs the gitignored CommunityDragon bins under `data/bin/characters`.
- **`pull_request` CI never runs while the PR is CONFLICTING:** GitHub cannot build the merge ref, so a PR behind `main` shows only Vercel checks and no Actions run — catch up with `main` first, then read CI.
- **`DefenseSubject` reads options through an injected reader:** `item_behavior.py` is a leaf (ability_spec + value_ref only); `defensive_effects.option_reader(item_options)` is the one typed reader, and a subject built without one fails closed on the first supplied option.
- **Regenerators after a merge, in order:** runes reparse, `receipt_walk_schedule --write`, `behavior_frontier --write`, `migration_frontier --write`, `cast_dependency_audit --output`, `plan_audit --refresh-drift`, `repin_corpus`, `item_umbrella_audit --output`, `capture_coverage_classification.py capture`, `golden_snapshot.py capture` + `capture-coupled` (+ `--exact`), then refresh the three fingerprint blocks in `docs/receipts/campaign-fingerprints.json`, then `coverage_census.py run --output` + `check` (~10 min).
- **`sorted()` over `Path` folds case on Windows:** two receipts that sort differently on Linux and Windows gave `tests/test_golden_snapshot.py`'s `declared_exact_moves` a platform-dependent winner; sort on `path.name` (or an explicit key), never on `Path` objects, wherever order decides precedence.
- **Full-suite runs are untrustworthy while another process edits `src/`:** tests that pin `inspect.getsource(...)` (`test_trigger_stream`, `test_import_namespace`, `test_gate_receipt`) read source from disk while imports hold the old module, so concurrent edits produce large phantom failure sets that vanish on re-run. Gate a shared tree only after all writers stop, or verify against a `git archive HEAD` copy.
- **A stun-only passive cannot reach the event ledger:** `P` is never in `damage.DEFAULT_CAST_ORDER`, so a P row's `control_events` (replayed per cast of their own slot) never fire, and `_ordered_damage_events` drops any authored `damage_event` whose `damage <= 0`. Braum's Concussive Blows stun rides its *damaging* proc events; Annie's Pyromania and Kennen's Mark of the Storm have no damage of their own, so their walks publish the derived stun schedule on the P row's `detail` and `MODULE_CC` stays empty.
- **A zero-damage breakdown row is published only if it carries a `detail`:** `public_response` skips a row with no damage, no amount and no `detail`, so adding a detail string to a zero row (Annie E's retaliation) makes it appear in the API and moves the *coupled* golden's leaf count with no number changing — the sibling of the published-zero-type trap above.
- **`slotlib.extract_value(ability, attr, rank)` indexes a row's *last* value when `rank` exceeds the row's axis** (`_axis_index` falls through to `-1`), so a rankless or short row silently prices the maximum instead of raising — check the row's length before trusting a ranked read (guarded case: Aphelios Weapon Master in `aphelios.py`).
- **`ability_spec.CC_KIND_VOCABULARY` is the ONE crowd-control vocabulary; every other cc set is a classification over it.** Three pairs partition it and `tests/test_cc_kind_vocabulary.py` is the guard: immobilizing / non-immobilizing (Everlasting + Command), action-blocking / non-blocking (action downtime, and `crowd_control_eligibility`'s blocking/soft split), and `DISPLACEMENT_CC_KINDS` (the Airborne umbrella — a cleanse tooltip carving out "Airborne" carves out knockback/knockup/pull too, resolved once in `cleanse_eligibility.resolve_excluded_kinds`). `KNOWN_CONTROL_KINDS` is *derived* from the vocabulary — never re-list kinds anywhere. The classifications are NOT interchangeable: polymorph blocks actions and is not an immobilize; cripple is control and is neither. Borrowing the wrong one is silent — it armed Everlasting on polymorph and left every authorable-but-unclassified kind failing closed through the whole cleanse path.
- **A one-ally item packet is priced before its recipient is chosen:** `item_support_effects` emits Mikael's Purify at `teammates[0]`, and `participant_timeline._apply_item_support_selection` is the only place a `support_target_selections` entry moves it — so a `LevelSubject.RECIPIENT` ramp must be re-read there through `repriced_for_recipient`, never left at the default ally's level. The fan-out producers (Locket Devotion, Redemption Intervention) already emit one row per ally at that ally's level; Solstice Sleigh's ramp is "your level" (holder) and has no per-recipient price at all.
- **`scripts/golden_coupled_exact.json` is not a `golden_snapshot.py compare` target:** `tests/test_golden_snapshot.py` consumes it through `rebuild_for` (declared exact moves), so the compare CLI reports ~11 "diffs" on a green tree — including on `main`. The pinned compare targets are `golden_baseline.json` and `golden_coupled_baseline.json` only.
