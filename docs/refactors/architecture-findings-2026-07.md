# Architecture Findings — July 2026 Sweep

Four-lens architecture audit (navigability · separation · single source of truth ·
module depth), run 2026-07-15 on `feature/build-optimizer` via four parallel
exploration passes: item-knowledge chain, fight engine + champion layer,
consumers/data edges, and tests/meta. The detailed evidence below records the
pre-refactor state; the completion record immediately below is authoritative.

Baseline at time of audit: 794 tests passing, golden snapshot identical to
`scripts/golden_baseline.json`.

## Implementation status — complete

Completed 2026-07-15 in the recommended order:

1. **Finding 2:** `pipeline.py` now owns `FightParams`, request-mode resolution,
   defaults, and the complete stats → abilities → fight path.
2. **Finding 5:** the API/UI/optimizer/golden defaults agree; CI runs the golden
   gate; docs, README, and both operator skills describe the live system.
3. **Finding 1:** `item_effects.resolve_damage_effects()` compiles validated,
   typed build behavior; `damage.py` has neither raw registry reads nor
   item-name dispatch. The design record is `item-engine-boundary.md`.
4. **Finding 4:** single-user slot factories were inlined and the actual shared
   units (`proc_damage`, on-hit shell, modifier traversal) live in `slotlib.py`.
5. **Finding 3:** `tests/conftest.py` owns attacker-stat and fight harnesses,
   champion data fixtures share one factory, and scenario parsers use the
   display-name-aware dispatcher.

The minor findings are also closed: cached JSON reads are keyed by resolved
path + mtime; the mixed item test class was split per item; dependency-manifest
ownership is documented; the frontend reads target bonus health from config;
phantom cadence has one typed production owner; and item-name engine registries
were eliminated or consolidated by Finding 1. Line references below describe
the pre-refactor audit state and are intentionally historical.

Final verification: **800 tests passed**, the numeric golden snapshot is
identical, Pylint is **9.38/10** (threshold 9), changed Python files are Black
clean, both skill mirrors are byte-identical, and independent critical review
approved the result with no remaining findings.

**Convergence note:** two independent passes (item chain, fight engine) surfaced
Finding 1's core evidence without seeing each other's work. Treat that one as
high-confidence.

---

## Applied during the audit

**`damage.py:2358` — stale-literal fallback in The Collector's display note.**
The note re-read the registry via `.get('threshold', 0.05)` — the exact
silent-fallback anti-pattern CLAUDE.md rule 5 forbids — two lines below the loud
accessor call that computes the real threshold. Fixed by deriving the displayed
percentage from the accessor's own output (`collector_threshold / target_health`),
eliminating the item-number read from `damage.py` entirely. Verified: 794 passed,
golden gate zero diffs. (Uncommitted at time of writing.)

---

## Finding 1 — The item↔engine boundary is broken: `damage.py` is a hand-maintained per-item ladder

**Lenses:** all four · **Scope: LARGE** · the flagship refactor

The architecture's central invariant (architecture.md: "typed accessors (`get_*`)
are the only way other modules read item numbers"; CLAUDE.md rule 5) is
materially false in `damage.py`.

### Evidence

- **~30 raw `ITEM_EFFECTS[...]["key"]` numeric reads in `damage.py`**, bypassing
  the loud `_required_effect_value` path:
  `_calculate_phantom_hits` (271–273), `_simulate_kraken_damage` (429–446),
  `_simulate_bork_damage` (511–517), `_calculate_shadowflame_bonus` (581–586),
  `_compute_ability_rotation` (967–970), `_add_spellblade_damage` (1726–1728),
  `_add_burn_damage` (1803, 1826), `_add_item_proc_damage` (1929–1933).
  A parser break on these keys raises a bare KeyError with no item context — or
  nothing at all — instead of the named, loud failure the item layer promises.
- **`_add_single_proc_on_hits` (damage.py:1982–2193) is ~9 consecutive
  `if "Item Name" in item_names:` blocks** (Dead Man's Plate, Heartsteel, RFC,
  Stormrazor, Voltaic Cyclosword, Statikk Shiv, Titanic Hydra, Eclipse,
  Muramana), each with a bespoke formula and breakdown row. ~30 hardcoded
  item-name literals total across the engine. The registry's `type` field
  (`on_hit_once`, `on_hit_stacking`, …) promises polymorphic dispatch that only
  exists for 5 effect types (`on_hit`, `spellblade`, `burn`, `proc`, `active` —
  the generic loops at 1577/1717/1795/1886/1956). For everything else the
  add-item-effect skill's claim "the fight engine picks it up automatically"
  (SKILL.md:76) is false — a new item of those types means hand-writing a new
  `damage.py` branch.
- **`_DEFAULT_ITEM_EFFECTS` is a full shadow copy of parseable values**
  (item_effects.py:27–528, ~55 items). The docstring says defaults hold only
  "fields that cannot be parsed"; in reality most default fields ARE parsed, so
  every such number exists twice (default + wiki parse) with **no agreement
  test** — the fallback that activates exactly when parsing breaks is also the
  copy most likely to be stale.
- **Blast radius per item: 4–6 code sites.** Statikk Shiv, counted:
  `_parse_statikk_shiv` + `_ITEM_PARSE_CONFIG` entry (passive_parser.py),
  default entry + dedicated accessor (item_effects.py), a bespoke branch in
  `_add_single_proc_on_hits` (damage.py:2070–2083), plus test literals
  (test_stats.py:376–388, test_item_damage.py:3368–3400) and the golden
  baseline.
- **Wide-shallow accessor surface:** ~48 public functions in `item_effects.py`,
  many single-fact getters (`get_statikk_empowered_auto_count`,
  `get_hullbreaker_hits_required`, …) alongside shared functions that are
  internally per-item `if item_name == …` ladders (24 branches). Surface grows
  linearly with items — the opposite of a deep module.
- **Bidirectional modeling/value leak:** fight-model math lives in the value
  layer (`calculate_proc_damage`'s `num_procs = 1 + int(duration/cd)`,
  `get_armor_reduction`'s buried `avg_stacks = max_stacks * 0.8` fudge) while
  per-item value math lives in the engine (Titanic Crescent inline at
  damage.py:2086–2100, Malignance at 1929–1937).
- **Related dedup inside `damage.py`:** the mitigate-by-damage-type block
  (`magic → apply_resistance(raw, mr) * magic_amp / physical → armor / true → raw`)
  is copy-pasted ~8× (1241–1248, 1591–1596, 1627–1632, 1731–1738, 1899–1906,
  1965–1972, burn variants at 1839/1854/1871). A single
  `_mitigate(raw, dmg_type, resists, magic_amp)` is the obvious first commit.
- Minor but same-family: `get_stacking_mr_reduction` (item_effects.py:1611–1627)
  returns the raw effect dict, which `damage.py` then string-indexes (1033, 1037,
  1201) — accessor in name only.

### Cost paid today

Every balance patch is a multi-file hunt with no compiler help; "what does item
X do in a fight" has no single answer location; parser breakage on half the
items fails quietly instead of loudly; onboarding docs point at a happy path
that doesn't exist.

### Direction (needs a design pass — do not execute without a plan)

Type-polymorphic dispatch: each registry `type` maps to exactly one engine
handler that consumes only accessor output; per-item branches become registry
data. Kill or test-pin `_DEFAULT_ITEM_EFFECTS` against parser output. Candidate
interface shapes should be explored in parallel (minimal interface vs.
handler-registry vs. optimized-for-`_layer_on_hit_effects`) before committing —
this is the one finding wide enough for multiple legitimate framings.
Plan home when started: `docs/refactors/item-engine-boundary.md`.

---

## Finding 2 — The fight pipeline glue is copy-pasted 3× and has already drifted

**Lenses:** separation · SSOT · **Scope: MEDIUM** · best value-per-effort; fixes a live bug

### Evidence

- The sequence `calculate_total_stats → parse_abilities → dict(stats) copy →
  calculate_fight_damage` is independently implemented in **three places**:
  `app.py:211–261` (`api_calculate`), `optimizer.py:159–198` (`_evaluate_build`),
  `golden_snapshot.py:81–116`. Each copy independently repeats the load-bearing
  details (the defensive `dict(stats)` copy because the engine mutates stats;
  `deterministic=True` on two of three; display-name resolution). The
  duplication is acknowledged in each file's prose — but no function embodies
  "the pipeline."
- **Live drift, user-visible to API callers:** fight-mode resolution exists
  twice and the copies disagree. For `auto_attacks_only=true` +
  `include_auto_attacks=false`, `app.py:236–243` yields `effective_uptime = 0.0`
  while `optimizer.py:459–469` (which has an extra `elif auto_attacks_only:`
  branch) yields `effective_uptime = auto_attack_uptime`. `/api/optimize` can
  select a build that `/api/calculate` then scores differently. Only a UI hack
  masks it (`app.js:634–641` force-checks the include-autos box).
- **The ~18-field request block is duplicated verbatim** across `api_calculate`
  (app.py:147–165) and `api_optimize` (app.py:331–359). "Add one fight
  parameter" currently touches: `index.html` → `app.js buildFightPayload`
  (687–724) → both app.py blocks → `optimize_build` signature (408–428) →
  optimizer `eval_kwargs` (477–493) → `calculate_fight_damage` signature.
- **Three disagreeing default-target value sets** (plus a fourth copy):
  canonical `DEFAULT_TARGET` = 1000/100/100 (damage.py:55–60, served via
  `/api/config`); `optimize_build` signature defaults = **2000/50/40**
  (optimizer.py:412–415, dead on the web path, a trap for direct callers);
  `golden_snapshot.py:51` = 2000/50/40; `index.html` input `value=` attrs
  (271/294/301) = 1000/100/100 hardcoded — the values users actually see.
- **Unnamed magic fight constants, 3–4 homes each:** `fight_duration` default
  `8` (app.py:158, app.py:352, optimizer.py:417, index.html:324);
  `auto_attack_uptime` `0.8` (app.py:160, app.py:354, optimizer.py:419,
  index.html:342); one-rotation duration `5.0s` (app.py:239, optimizer.py:462,
  golden_snapshot.py:112) — a domain constant with no name and no home.

### Cost paid today

A pipeline change is a three-site byte-identical edit; the golden gate is itself
one of the three copies, so drift shared by all three is invisible to it; the
calculate/optimize inconsistency is live behavior.

### Direction

One `run_fight(champion, build, FightParams) → result` home (natural location:
`damage.py` or a thin `pipeline.py`), plus one `FightParams.from_request(dict)`
parser both routes share, owning the mode-resolution branch and all defaults.
`app.py`, `optimizer.py`, `golden_snapshot.py` become callers. `index.html`
defaults should be template-rendered from the same constants (or fetched from
`/api/config`). Behavior note: unifying mode resolution intentionally changes
the drifted `auto_attacks_only` edge — the golden baseline may need a
re-capture with that diff documented.

---

## Finding 3 — Test setup has no shared home

**Lenses:** SSOT · depth · **Scope: MEDIUM**

### Evidence

`tests/conftest.py` deepened only as far as *data* fixtures (champion/item
lookups, `parse_at`); there is no fixture that builds attacker stats or runs a
fight. Counted consequences:

- **136** hand-assembled `calculate_fight_damage(...)` call sites across 13 files.
- **Six** copy-pasted `_make_stats` builders inside `test_item_damage.py` alone
  (3321, 3449, 3563, 3706, 3823, 3968), each a ~20-key dict; the
  `"attack_speed_ratio": 0.625` stats block appears 26× in that file.
- The 1000/100/100 target dummy inlined **70×** (63 in test_item_damage.py);
  `one_rotation=True` 75×.
- **101 in-function `from src.calculator...` imports** in test_item_damage.py
  (31 more in test_stats.py).
- `parse_ahri_abilities(ahri_data, 18, stats["ability_power"])` repeated 22×
  verbatim.

Related, smaller: numeric expectations for the same scenario live in three
independently-maintained places (parsed-value literals in tests, hand-fixed
totals in `test_known_good.py`, the golden baseline) — a known, recurring
patch-reconciliation chore. Tests in two files import ~7 `damage.py` underscore
internals (`test_damage.py:19–21`, `test_item_damage.py:16–21`) — a documented
judgment call, but it doubles the breakage surface of any engine reshape.

### Cost paid today

Any engine-signature or stats-shape change is a dozens-of-sites edit; every new
item test starts life as a 20-line paste.

### Direction

An `attacker_stats(**overrides)` + `fight(**kwargs)` fixture pair in conftest,
adopted file-by-file. **Sequencing:** land after Findings 1–2 so tests converge
once on the final engine interface, not twice.

---

## Finding 4 — slotlib's "≥2 users" archetype rule is inverted in practice

**Lenses:** SSOT · depth · **Scope: MEDIUM**

### Evidence

architecture.md:47 and the redesign doc state: "an archetype exists only with
≥2 users." Actual caller counts:

- **Six single-user factories** (~330 of slotlib's 1004 lines):
  `multi_hit_sum` (609) → Aatrox Q only; `on_hit_pct_health` (658) → Aatrox P
  only; `toggle_dot` (728) → Anivia R only; `multi_cast` (798) → Ahri R only;
  `proc_damage` (860) → Akali P only; `utility` (910) → Annie E only. Each is
  double-tested (synthetic in test_engine.py + the champion test).
- **The genuinely ≥2-user patterns are copy-pasted instead of hoisted:**
  the proc-emit dict shape has 3 users (Akali via factory; `ambessa.py:122–128`
  and `akshan.py:252–258` by hand); the on-hit-in-castable-shell shape has 2
  (`vayne.py:68–80`, `kogmaw.py:101–109`); `pct_health_per_hit` math has 3 users
  but only Aatrox reaches it through the factory.
- `akshan.py:_extract_e_per_shot` (53–109) and `ambessa.py:_parse_passive_damage`
  (35–104) each hand-roll the modifier walk that `slotlib._sum_modifiers`
  (47–79) already owns.
- Same family: `common.calculate_ability_damage` (common.py:10–27) is a public
  base+ratio one-liner with **zero internal callers** — it reads as *the*
  canonical scaling formula but everything actually goes through
  `resolve_scaling`. Misleads readers; delete or document.

### Cost paid today

Docs promise reuse that isn't there; a fix to any actually-shared shape lands in
2–3 champion files; ~330 lines of indirection are maintained for single callers.

### Direction

Inline the six single-user factories into their champions (or keep only those
with a concrete second user on the roadmap), and hoist the real shared units
(a `per_proc` callable on `proc_damage`; an on-hit-shell helper). Golden gate
must show zero diffs — this is a pure restructure.

---

## Finding 5 — Truth sweep: the meta layer misleads the next reader

**Lens:** navigability (docs/CI as infrastructure) · **Scope: SMALL, bundle**

Each item is cheap; each actively lies to the next contributor or AI assistant:

1. **`_NAME_ALIASES` is an empty dict** (passive_parser.py:1587–1591), yet
   CLAUDE.md:52, architecture.md:30, and add-item-effect SKILL.md:268 all name
   it as the wiki-vs-JSON alias mechanism. The live alias is
   `BUILD_SUBSTITUTES = {"Luden's Companion": "Luden's Echo"}` in
   `golden_snapshot.py:50`. A developer following the docs edits a dead dict.
   Fix: make `_NAME_ALIASES` real (and move the golden substitution into it) or
   correct all three docs.
2. **CI never runs the golden gate** (`.github/workflows/tests.yml` runs pytest
   only) — the repo's headline numeric regression lock is discipline-only.
   Also `pylint --fail-under=5` is far below meaningful. Add the golden compare
   step; raise or justify the pylint bar.
3. **README.md is stale:** claims "337 tests" (actual: 794) and omits the build
   optimizer — a shipped feature with a route, module, and 24 tests.
4. **add-item-effect SKILL.md Step 5 (88–101) directs fight tests into one
   mixed class**, contradicting the accessor-vs-fight altitude split
   (`test_item_effects.py` / `test_item_damage.py`) the July campaign
   established. Also SKILL.md:76 overpromises automatic engine pickup (see
   Finding 1).
5. **The "11-step pipeline" label is soft:** `calculate_fight_damage`
   (damage.py:2454–2508) makes ~18 step calls with 11 numbered; internal
   comments reference a phantom "step 9.5/10/11" scheme. Renumber or drop
   numbers for names.

---

## Minor findings (recorded so they aren't lost)

| Finding | Location | Cost |
|---|---|---|
| `data_fetcher` re-parses full JSON per call; optimizer triggers 2+ full item-JSON parses per request | data_fetcher.py:108–159; optimizer eligible-pool calls | Pure overhead; a `functools.lru_cache` keyed on path+mtime would do |
| Item-name strings form 3+ uncoordinated registries (defaults keys, parse-config keys, damage.py literals, optimizer groups/blocklist) | item_effects / passive_parser / damage / optimizer:16–66 | Renames touch many files, caught only at runtime; largely subsumed by Finding 1 |
| `TestNewItemDamageEffects` grab-bag holds Shiv/Stormrazor/Titanic/Shojin against the file's one-class-per-item convention | test_item_damage.py:3318 | "Shiv damage wrong" lands in a mixed bag — and that's the known-bug item |
| `conftest.py` has 12 near-identical `<champ>_data` fixtures | conftest.py:39–115 | Parametrizable; mild |
| Some champion tests import module `parse_abilities` directly, bypassing dispatcher + `parse_at` | test_vayne/kogmaw/akali/ahri, test_known_good, test_damage, test_item_damage | Misses dispatcher name-routing coverage (the documented Kog'Maw naming trap) |
| Two dependency manifests (root requirements.txt overlaps lolstaticdata/requirements.txt) | requirements.txt | Negligible; note only |
| `app.js:675` hardcodes bonus-health fallback `0` instead of `defaultTarget.bonus_health`; stat display labels live in index.html+app.js, not config | app.js, index.html:408–472 | Low; frontend otherwise clean |
| Phantom-hit cadence table hand-maintained at two test altitudes | test_damage.py:338–350 vs test_item_damage.py:2415–2433 | Two owners can silently diverge |

---

## Verified healthy (checked, not vibes)

- `engine.py` phase evaluation is genuinely deep (compile-time phase ordering,
  not a wrapper); `Resists` correctly encapsulates the ability/auto pen split,
  Terminus weighting, and Malignance pre/post-ult MR.
- `data_fetcher` / `data_updater` honor their contracts exactly (single read
  path, single network module, contained Windows monkey-patch).
- `app.js` is presentation-only as claimed — exclusivity groups, champion
  options, and lists all arrive from the API; no formulas crept in.
- Test macro-structure is sound: altitude split between `test_item_effects` and
  `test_item_damage` is real and documented; `test_known_good.py` is a
  deliberate hand-validated anchor, not a stale layer; `test_item_effects`'s
  monkeypatch pattern is drift-proof by construction.
- add-champion skill matches code; `test_champion_options.py` enforces the
  option-key rule it promises.
- requirements.txt matches actual imports.

---

## Recommended order

1. **Finding 2** (pipeline home) — bounded, fixes live drift, unlocks a single
   place for Finding 5's constants. One session.
2. **Finding 5** (truth sweep) — ride-along; keeps docs honest before the big
   refactor starts leaning on them.
3. **Finding 1** (item↔engine boundary) — flagship; parallel interface designs
   → `docs/refactors/item-engine-boundary.md` plan → staged commits behind the
   golden gate. Start with the `_mitigate()` hoist as commit 1.
4. **Finding 4** (slotlib rebalance) — pure restructure under the golden gate.
5. **Finding 3** (test fixture home) — last, so tests converge once on the
   post-refactor interfaces.
