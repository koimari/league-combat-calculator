# Autoresearch Review — Atomization Engine (WS3/WS4) + First Champion Build (Vladimir)

**Date:** 2026-08-05 · **Branch:** `codex/deep-audit-2026-08` · **Worktree:** `/Users/river/Projects/league-combat-calculator-audit`
**Reviewer:** independent autoresearch review (read-only; only this document written)
**Scope:** atom classifier (`scripts/extract_atoms.py`), its outputs (`data/atoms/`, `data/wiki-atoms/`, `data/champion-audit/`), the wiki damage-type bridge, and the first WS4 build (Vladimir healing + participant-ledger fix, commit `a963d58`).

---

## 0. Executive summary / Go-No-Go

**Verdict: GO on the atom engine as an audit/prioritization substrate, with three caveats; GO on the WS4 heal-batch direction conditional on one prerequisite (a heal-basis standard).**

- Every claimed metric re-verified on an independent re-run: **5,345 atoms / 173 champions, 0 weak-evidence atoms, 19/19 sanity, damage-type coverage 53.9% (was 1.4%), 1,274 unclassified real + 652 noise**. The re-run is **byte-identical to the committed tree** (deterministic; `git status` clean after running).
- The evidence-tier design (tag → name → rule → inherited → wiki-map, no datavalue-only votes) is **sound in mechanism and effective at killing over-classification** (the E1→E5 experiment log is real: removing weak evidence cut 444 → 0 >4-atom objects... residual issues are semantic, not mechanical).
- **Real residual over-classification exists** in the *strong* tiers, not the weak tier: **ghost atoms from removed kits** (Aatrox `heal-shield.revive` ×2 — Aatrox has had no revive since the 2018 rework; the audit swarm itself was misled by them) and **ambiguous single-token keywords** (Senna `Skin56Form` → `transform`, Senna `QuestActive` → `gold-income-item`). "No weak evidence" does not mean "no wrong atoms".
- **Real under-classification exists too** (Nasus W Wither has no slow atom; target_policy defaults mislabel self-heals as `ally`; autos are damage_type=null), but the 1,274 unclassified-real objects are mostly low-value engine-state objects; the high-value misses are fixable via the existing wiki-map mechanism.
- **The Vladimir build is numerically correct vs the wiki cache** for Q/W/R heal values, and the ledger re-price fix is **sound and consistent across receipt/score paths** (all 3,205 tests pass; golden gate identical). **One real bug found: the W Sanguine Pool heal is computed on post-mitigation damage while the wiki cache (and the code's own comment) specify pre-mitigation** — a ~34% under-heal at 52 MR.
- The audit swarm's gap inventory is **trustworthy as a prioritization list** (spot-checked: every sampled atom-level claim matched the atom files), with one systematic caveat: it inherits the classifier's ghost atoms (Aatrox "revive" listed as a real mechanic).

---

## 1. Measured metrics (independent verification)

Re-ran `python3 scripts/extract_atoms.py` in the repo, then recomputed every metric from the regenerated artifacts:

| Metric | Claimed | Measured (independent) | Verdict |
|---|---|---|---|
| Champions processed | 173 | 173 | ✓ |
| Atoms classified | 5,345 | 5,345 (sum of per-champion files) | ✓ |
| Weak-evidence atoms | 0 | **0** (all 5,345 carry `tag:`/`name:`/`rule:`/`inherited:`/`wiki-map:` evidence) | ✓ |
| Evidence breakdown | name 1,611 / tag 2,161 / rule 256 / inherited 1,295 / wiki-map 22 | identical (recomputed per atom) | ✓ |
| Sanity checks | 19/19 | 19 passed of 19 | ✓ |
| Damage-type coverage | 0.5388 (1,616/2,999) | 0.5388 (1,616/2,999: magic 939, physical 571, other 88, true 18) | ✓ |
| Coverage before bridge | 0.0137 (41/2,999) | arithmetic ✓ (41/2999 = 0.0137) | ✓ |
| Unclassified real / noise | 1,274 / 652 (1,926 total) | ✓ (sum over `unclassified.json`) | ✓ |
| Family totals | CC 1,035 · dmg 2,999 · heal-shield 274 · interaction 156 · stacks 807 · vision 74 | identical | ✓ |
| Determinism | — | re-run produced **zero git diff** | ✓ |
| Test suite | — | `pytest`: **3,205 passed** | ✓ |
| Golden gate | — | `golden_snapshot.py compare`: **identical** | ✓ |

Also verified: the `autoresearch` experiment log (E1 baseline → E5 no-weak) is internally consistent with the current artifact state, and the report's `improvement_suggestions` each map to a reproducible example in the artifacts (verified below).

## 2. Evidence model review

### 2.1 Tier soundness

The five tiers are ordered by semantic strength, and the ordering is respected in code (`classify_object`: tags first, then name keywords, then rules; datavalue-only matches are never emitted). Strong points:

- **Tag tier is the right top tier.** `mSpellTags` are the engine's own semantic vocabulary, they rarely lie about *existence* of a mechanic, and they carry target hints (`spell-tags.json`). 40% of all atoms (2,161/5,345) ride on tags.
- **The no-weak-evidence policy works as advertised.** Zero datavalue-guessed atoms survived; this is the correct call because datavalue *names* are engine boilerplate (`max`, `rank`, `level`, `damage`) that over-fire. The E2→E3→E5 history shows the policy was reached empirically, not assumed.
- **Generic-token and champion-token guards are real and necessary** (keyword made entirely of corpus-generic tokens is dropped; champion-name keywords dropped). Spot-checked: `damage`/`duration`/`crit` are suppressed as standalone keywords, which is why the 2,999 damage atoms come from tags/rules rather than the word "damage".
- **Clone inheritance is a large, sound recall gain** (1,295 atoms, 24%) and the suffix list (incl. the game's real "Missle" typo) is faithful. Risk is bounded because inheritance never invents a family the parent didn't have.
- **Wiki-map tier is honest**: only 22 atoms, each with a `wiki_name` note, used exactly where the binary cannot express the mechanic (Neeko/Kayle transforms, shared-script summons). This is the correct escape hatch and it is small.

### 2.2 Over-classification that survives the strong tiers (findings)

The "no-weak" policy eliminated weak *evidence*, but strong evidence can still be **wrong semantics**:

1. **Ghost atoms from removed kits (highest severity).** `AatroxRRevive`/`AatroxRevive` (binary objects from the pre-2018 Aatrox kit) classify as `heal-shield.revive` ×2 with `name:revive` evidence. Aatrox's live R (World Ender) has no revive; the wiki cache lists only AD/healing-amp. **The audit swarm inherited the error** — batch-0 lists "revive (R World Ender)" and "R revive (passive utility)" as real mechanics. This is the one systematic risk of the engine: binaries contain unused legacy objects, and the classifier has no "is this mechanic live" check.
2. **Single-token keyword over-fire.** `transform`'s keyword `form` fires on `SennaSkin56Form` (a *skin* model-swap object → `transform` atom; Senna has no gameplay transform) and defensibly-but-loosely on `SennaEWraithForm`/`SennaEWraithFormMoveSpeed`. `gold-income-item`'s keyword `quest` fires on `SennaQuestActive`/`SennaQuestActiveThresh` (the Senna/Thresh *light-and-shadow quest* — not a gold-income item). The report's suggestion #4 names these honestly; measured residual: `transform` atoms exist for 40 champions (a few are wrong), `gold-income-item` for ~6 (mostly support items, Senna's two are wrong).
3. **Known-but-accepted noise** (documented in the report): "shield" keyword in flow/true-damage atoms firing on every shield, `TauntLength` (Thresh Q) → taunt, `ManaRefund` → refund, meta atoms over-firing by design. These are bounded and named; acceptable for a catalog tool, not for final champion numbers.

### 2.3 Under-classification (findings)

1. **Untagged, unprefixed-name objects fall through.** `NasusW` (Wither — one of the game's strongest slows, 95% at max rank) has **no slow atom**: the object carries no `mSpellTags` and the champion-prefix strip leaves the empty token `W`. The designed fix (wiki champion map) exists but only covers summons/clones/transforms/traps. Expanding `champion-spell-atoms.json` to named CC/utility spells (or a "wiki-name → slot" pass) would close this class.
2. **target_policy mislabels self-heals as `ally`.** `Trait_ActiveHeal` maps to `(heal, ally)` in `spell-tags.json`, so Vladimir Q/W/R self-heals are tagged `target=ally` (Vladimir's kit has no ally heals). The more specific `Trait_SelfHeal` exists but only some objects carry it. Consequence for WS4: a naive "heal atoms with target=ally → support ledger" step would route self-heals into the ally-support channel.
3. **damage_type=null on basic attacks** (1,383 untyped damage atoms, dominated by `*BasicAttack` objects): the wiki cache types abilities, not autos. Autos are physical by game rule; this is a one-line policy fix, not an atom problem.

### 2.4 Spot-checks (7 champions vs `data/champions.json`)

| Champion | Verified correct | Verified wrong/missing |
|---|---|---|
| **Vladimir** | Q/W/R heals, R 10% amp debuff (3 atoms), E channel, W untargetable, health-as-resource, all damage typed magic | target_policy `ally` on self-heals; R "damage-modification-debuff" not modeled in module (audit review) |
| **Aatrox** | Q/W damage, dash, attack-reset, slow, P healing | **`heal-shield.revive` ×2 ghost atoms (removed kit)** — audit misled |
| **Senna** | Q heal, R shield, souls, mark, stack | `transform` ×3 (Skin56Form = skin object), `gold-income-item` ×2 (quest ≠ gold item) |
| **Gnar** | transform/fury/knockback/slow, W slow, Mega Q inherited, damage_type None on W (multi-form disagreement — documented) | — |
| **Teemo** | R trap, E poison DoT (tag + inherited), stealth | — |
| **Pyke** | R execute (rule), grey-health heal atoms present (P), damage_type `other` verbatim from cache (in-game true damage — known) | — |
| **Nasus** | Q stack atom exists | **W Wither missing entirely (no slow atom)** |
| **Kayle/Thresh/Annie/Malzahar** | W heal, transform (wiki-map), W shield, souls, Tibbers/Voidling summons (tag + wiki-map) | — |

Net: the engine is a **good recall instrument with precision defects at the margins**; both defect classes (ghost atoms, ambiguous keywords) are enumerable and fixable in the vocab/map layer, not in the matcher.

## 3. Vladimir WS4 build review (commit `a963d58`)

### 3.1 Healing rules vs the wiki cache — numbers correct, one semantic bug

- **Q Transfusion**: flat `Heal: 20/25/30/35/40 (+35% AP)` — **exact match** to `data/champions.json` Q leveling. Rank + AP tests pass. (Empowered Crimson Rush *extra* heal `30–220 + missing-health%` is **not** modeled — documented gap; the 85% empowered *damage* is handled by the module.)
- **R Hemoplague**: full `150/250/350 (+70% AP)` + `Reduced Heal 60/100/140 (+28% AP)` — **exact match** (40% of full, incl. 28% = 40% × 70% AP). Multi-target test asserts {350, 140} ✓.
- **E Tides of Blood**: correctly no heal in the current patch (test asserts absence) ✓.
- **W Sanguine Pool — REAL BUG vs the project's own source of truth.** The wiki cache says *"heals himself for 30% of the pre-mitigation damage dealt"*, and the code comment repeats "pre-mitigation". The implementation computes `0.30 * event["damage"]`, and the engine's event `damage` is **post-mitigation** (verified: rank-5 tick raw 75 vs Ahri MR 52.1 → event damage 49.3 → heal 14.8; correct pre-mitigation heal would be 22.5/tick, ~34% higher). The test `test_vladimir_sanguine_pool_heals_thirty_percent_of_damage` validates the code against itself (`0.30 × event.damage`), so it cannot catch the discrepancy. **This is exactly the failure class the heal-rule batch will multiply across ~40 champions — a heal-basis standard (pre- vs post-mitigation) must be decided and the engine must expose the raw basis before the batch scales.**

### 3.2 Ledger fix (multi-target heals re-priced by roster index) — sound

- The `_later_target_amount` receipt design is correct: each pair fight cannot see the roster, so the engine authors the full value with an explicit reduced receipt; the coupled ledger re-prices defenders past the first (`defender_index > 0`).
- **Consistency verified across all three paths:** public receipt (`_pair_packet`), fresh score compile (`_WalkCompiler.add_engine_result` via `_score_with_search_context`), and the invariant base/sig compilers (packets pre-built with the same `defender_index`). Index semantics match the legacy attack groups everywhere: allied attackers → enemies indexed from 0; enemy attackers → `[main, *allies]` with main at 0 and allies at 1+. `fast == legacy` assertions cover both walks.
- **Dedup interaction is safe:** the `(source, time)` dedup only applies to `actor_wide` heals; Vladimir's champion-ability heals carry trigger links and are never collapsed (test asserts 2 distinct event ids / trigger receipts / trigger targets).
- **No internal-field leak:** `_later_target_amount` does not appear in the serialized API receipt.

### 3.3 Edge cases

| Case | Behavior | Verdict |
|---|---|---|
| Single-enemy fight | defender_index 0 → full R heal; Q/W heals fire | ✓ correct |
| Main vs N enemies | enemy[0] full, rest reduced | ✓ correct values |
| Enemy Vladimir vs main + allies | main gets full (index 0), allies reduced (1+) | ✓ consistent across paths |
| No allies in roster | `1 + ally_index.get(id, -1)` → 0 for main | ✓ full heal |
| **Infection order ≠ roster order** | "first infected champion" is proxied by roster index 0 | ⚠ approximation, deterministic and documented; wrong whenever the R's actual first hit differs from roster order (unavoidable in pair-fight model) |
| Q heal when Q damage event = 0 (full shield block / immunity) | `_heal_from_damage` guard `damage <= 0 → return` drops the **flat** heal | ⚠ design wart: the flat heal is not damage-proportional; guard should only apply to proportional heals (W) |
| Empowered Crimson Rush Q | extra missing-health heal unmodeled | ⚠ documented gap (option-gated state) |
| R 10% damage-taken amp | 3 atoms exist; module R packet emits only burst+heal | ⚠ the build's own champion keeps a `review` verdict because of this |

## 4. Audit swarm synthesis → ranked experiment plan

**Swarm totals (173/173): 68 ok · 43 review · 62 gap.** Gap composition (hand-coded from the 62 gap summaries + 43 review summaries): **~47 unmodeled self/ally-healing** (nearly all "absent from `HEALING_RULE_CHAMPIONS`"), **10–15 DoT/channel tick-count undercounts** (Lucian R 1×22 shots, Miss Fortune R 1×24 waves / E 1×8 ticks, Malzahar E 1×16 ticks, Morgana W 1×10 ticks, Samira R 1×10 shots, Urgot W, Teemo E, Trundle R, Yunara W), **~30 stack-system misses** (Varus W blight, Twitch P/E poison, Vel'Koz research, Tristana E bomb, Nasus Q, Senna/Thresh souls), **~16 summons** (Zyra plants, Yorick walkers/Maiden, Ivern Daisy, Malzahar voidlings), **~30 mis-modeled rows** (Nunu Q wrong basis, Rammus W armor row as damage, Tryndamere Q heal-as-magic-damage, Zed R % read as flat, Yone E % reads 0, Sion Q %, Poppy P %maxHP, TF W 3 merged cards, Veigar R max-only, Pyke R 13-value array), plus execute branches (Pantheon Q, Shaco E, Naafiri recast) and damage-mod debuffs (Vladimir R amp, Wukong Q shred). Spot-verified the atom-level claims for Rakan/Sylas/Senna/Nidalee/Vladimir — all match the atom files.

Experiments below are ordered by dependency (each builds on the previous). Format mirrors the autoresearch `program.md` style used for the classifier rounds (goal / method / expected metric / overfitting risk).

### E0 — Heal-basis standard + pre-mitigation exposure *(prerequisite, small)*
- **Goal:** one sourced convention for damage-linked heals (pre- vs post-mitigation) and engine access to the raw basis, so every future heal rule uses identical semantics.
- **Method:** pick the wiki cache's wording as truth ("pre-mitigation damage dealt" for W); expose raw (pre-mitigation) damage on damage events or add a `basis` field to heal receipts; fix the Sanguine Pool rule + test (assert against wiki raw values, not `event.damage`).
- **Expected metric:** Vladimir W heal correct at nonzero MR (14.8 → 22.5/tick at 52 MR); new test pins raw-basis; golden re-captured with one explained diff.
- **Overfitting risk:** low; but *skipping this* would encode ~40 champions with inconsistent pre/post semantics — the highest-leverage decision in the whole plan.

### E1 — Heal-rule batch: close the ~47 gap healers (WS4 continuation)
- **Goal:** all gap/review healers with sourced wiki formulas enter `HEALING_RULE_CHAMPIONS` + `derive_self_healing` branches (Alistar P, Aphelios P, Camille W, Illaoi P, K'Sante R, Karma W, Kayle W, Khazix W, Kindred W/R, Lissandra R, Mordekaiser W/R, Nami W, Nidalee E, Pyke P, Rakan P/Q/E, Rengar W, Senna Q/R, Smolder R, Swain R, Sylas W, Tahm Kench Q/E, Volibear W, Xin Zhao W, Yorick Q, Yuumi P/E/R, Zaahen Q/R, … + review-tier Bard W, Janna R/E, Kayn E/R, Leona E, Malphite P, Nocturne P, Olaf W, Sona W, Seraphine W, Vex W).
- **Method:** one rule per champion, sourced from `data/champions.json` leveling attributes via `extract_named` (same pattern as Vladimir); per-champion heal tests; extend `HEALING_RULE_CHAMPIONS` with a source-pinning test.
- **Expected metric:** gap verdicts 62 → ~25; `HEALING_RULE_CHAMPIONS` 10 → ~50; heal-shield family coverage in module audit from ~274 atoms → >90% of heal-bearing champions.
- **Overfitting risk:** **high** — heal semantics vary per kit (flat vs %damage vs missing-health vs grey-health conversion vs per-target caps, minion penalties). Each rule must cite its cache attribute; the grey-health family (Pyke P, Rengar W, Tahm Kench E, K'Sante R) needs one shared primitive or it will be re-implemented 4 ways. Gate on E0.

### E2 — DoT / channel tick-count fix
- **Goal:** multi-instance channels and DoTs price their full tick counts (Lucian R, MF E/R, Malzahar E/R, Morgana W, Samira R, Urgot W, Teemo E, Trundle R drain, Yunara W linger, Naafiri Q bleed, Talon P bleed).
- **Method:** derive tick count from the wiki cache's own pairs (`Damage Per Tick` vs `Total Magic Damage`, or `Per Shot` vs `Total`, incl. duration/interval); add a `hits`/`tick_count` field to packet specs; per-champion tests pinning total = per-tick × count.
- **Expected metric:** closes ~10–15 gap/review verdicts; largest single-champion damage corrections (Morgana W ~10×, MF R ~24×, Malzahar E ~16×); golden re-capture with explained diffs.
- **Overfitting risk:** medium-high — counts must respect real conditions (channel interruptibility, per-target caps "can be damaged only once", isolated/shared damage, minion penalties). Using the cache's `Total` attributes verbatim is the right start but will need per-champion exceptions.

### E3 — Stack systems (stateful mechanics)
- **Goal:** Varus W blight + detonation, Twitch P/W poison stacks driving E, Vel'Koz P research detonate, Tristana E active bomb, Nasus Q stack scaling, Senna/Thresh soul scaling.
- **Method:** add a stack-state primitive (count, cap, per-stack scaling, consume-on-detonate, source attribution) to the engine; option-gated rows for stack-dependent abilities; souls as a permanent stack-currency input.
- **Expected metric:** closes 5–6 gap verdicts (Varus, Twitch, Vel'Koz, Tristana, Nasus) and unblocks soul-scaled Thresh/Senna modules; audit verdicts → ok for those champions.
- **Overfitting risk:** **highest** — stack timing is the most stateful surface (unique-hit rules, auto-attack counts, detonation windows, 3-stack-on-3rd-hit). Expect per-champion exceptions; keep the primitive generic and the rules data-driven.

### E4 — Summons (pet damage)
- **Goal:** Zyra plants, Yorick Mist Walkers/Maiden, Ivern Daisy, Malzahar Voidlings, Annie Tibbers damage contribution to sustained DPS.
- **Method:** pet attack-interval packets sourced from wiki (`Pet attacks every Xs`, per-attack damage), composed into the attacker's DPS as `Trait_Pet`-tagged damage; pet death/respawn coarse-modeled.
- **Expected metric:** closes 4–6 gap verdicts; meaningful sustained-DPS corrections for Zyra/Yorick (their core damage).
- **Overfitting risk:** high — pet AI (targeting, focus-fire, leash, death) is the classic coarse-model trap; keep pets as documented approximations, never cite as exact.

### E5 — Mis-modeled rows batch
- **Goal:** fix the ~30 wrong-basis packet rows: Nunu Q champion row, Rammus W damage row, Tryndamere Q (heal, not damage), Zed R / Yone E percentage rows, Sion Q % multiplier, Poppy P %maxHP, Nautilus P, TF W merged cards, Veigar R min/max, Pyke R 13-value array, Shaco E / Pantheon Q execute branches, Sett W / Pyke R `other`→true verification.
- **Method:** per-champion packet-spec corrections with wiki receipts + one test each; where the cache marks `OTHER_DAMAGE` but the mechanic is true damage in game, decide the standard (data override vs code).
- **Expected metric:** ~10+ verdict fixes (Nunu, Rammus, Tryndamere, Zed, Yone, Sion, Poppy, TF, Veigar, Shaco, Pantheon); golden re-captured with itemized diffs.
- **Overfitting risk:** low-moderate — each fix is independent and mechanical; risk is *churn* (30 separate diffs) and the `other`→true decision needing game-file evidence.

### E6 — Damage-modification debuffs (small, high-value)
- **Goal:** model "increased damage taken" amps (Vladimir R 10%, Wukong Q shred) using the existing target_debuff precedent (Kog'Maw Caustic Spittle).
- **Method:** wire `stack-transform-summon-resource.damage-modification-debuff` atoms to the target-debuff engine row; option-gated R amp on Vladimir.
- **Expected metric:** Vladimir review → ok; Wukong gap closed; future amps (Bard, Janna, Sylas…) get a template.
- **Overfitting risk:** medium — amp stacking/order vs penetration (percent → flat → amp) must be defined once.

### E7 — Classifier hardening (parallel, engine-quality)
- **Goal:** kill ghost atoms and raise recall on untagged objects: (a) cross-check binary objects against the live wiki kit (drop `AatroxRRevive`-class ghosts — 14 revive atoms today, ~2 are wrong), (b) extend `champion-spell-atoms.json` to named CC/utility spells (Nasus W class), (c) fix `Trait_ActiveHeal` target to `self-or-ally` or champion-aware, (d) type basic attacks physical.
- **Method:** new experiment rounds in the existing autoresearch loop (E6+): add a "live-kit provenance" check fed by `data/champions.json` ability names; measure ghost-atom count per round.
- **Expected metric:** unclassified_real 1,274 → <900; ghost atoms → 0 known instances; sanity stays 19/19; weak stays 0.
- **Overfitting risk:** medium — the live-kit check can drop *live* atoms when the cache is stale (the Gnar Mega precedent in AGENTS.md warns exactly about this); the check must be conservative (only drop objects whose name has no live-kit counterpart AND no wiki-map entry).

**Dependency order:** E0 → E1 → E2 → E3/E4 (parallel) → E5 → E6; E7 runs alongside everything (pure catalog quality, unblocks audit trust). Expected cumulative effect: 62 gap verdicts → <10, and the audit's `ok` share 68 → >130.

## 5. Recommendation

- **Atom engine: GO (with caveats).** The measured claims are real and reproducible; the evidence model is the right architecture. Treat it as a *prioritization and audit substrate*, never as authoritative champion numbers, until E7 removes ghost atoms and the wiki-map covers the untagged-mechanic class. The engine's output is already good enough to drive the experiment plan above.
- **Vladimir build: ACCEPT with one required fix.** Numbers and ledger mechanics are right; the W pre-mitigation bug (E0) must be fixed before the heal batch copies the pattern, and the `damage<=0 → drop flat heal` guard should be tightened.
- **Next commit order:** E0 (small, unlocks everything) → E1 heal batch (the 47-champion dominant gap) → E2 tick counts (largest numeric corrections) → E3/E4/E5 per the plan.
