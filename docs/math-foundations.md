# Mathematical Foundations of the Scryglass Combat Calculator (P2)

Branch: `codex/p2-math-foundations` · Date: 2026-08-06
Engine: `src/calculator/` (`damage.py`, `participant_timeline.py`, `healing.py`,
`optimizer.py`, `resistance.py`, `stats.py`)
Input contract: deterministic combat outcomes derived from the League Wiki cache
(`data/champions.json`, `data/items.json`) and game files. Every number below
traces to a wiki/game source. Production attackers use validated named modules;
the generic parser is restricted to explicit synthetic/development fixtures.

This document states, for every modeling family, the mathematical identity the
engine instantiates, the theorem that justifies it, the cases where the engine
is exact versus approximate, and — where a formula deviates from the game — the
edge case and the recommended resolution. arXiv identifiers are the primary
literature anchors (free toolkit: `~/.local/mcp/helpers.py`, no paid APIs).

---

## 0. Semantics of the deterministic single number

The engine runs with `deterministic=True` in every public path (API, optimizer,
golden corpus). In that mode **every stochastic draw is replaced by its
expectation**: crits are blended at their probability-weighted mean, procs fire
on their deterministic cadence, and health-dependent terms are evaluated along
the expected damage path. The output is a single number

```
T = E[ D | model, config ]      (point estimate under the expectation heuristic)
```

It is *not* a sample from a distribution, and it is *not* a confidence
statement (Section 4). The validity of replacing `E[f(X)]` by `f(E[X])` is the
one place the engine is genuinely approximate: it is exact for affine `f`
(linearity of expectation) and biased for strictly convex/concave `f` (Jensen).
Every family below is labeled accordingly.

---

## 1. Expected damage & combat simulation

### 1.1 Renewal theory for cast + auto timing schedules

**Model.** A basic-attack stream is a deterministic periodic renewal process:
swings land at `0, Δ, 2Δ, …` with `Δ = 1/(AS · u)` where `AS` is total attack
speed and `u` is the auto-attack uptime fraction. The engine computes the swing
count as

```
N(T) = ⌊AS · u · T⌋                  (damage.py: num_auto_attacks = floor(...))
```

with swing timestamps `t_i = i·Δ, i = 0..N(T)−1` (the last swing is strictly
inside the window). This is the **counting function of a renewal process with
deterministic interarrival time Δ**: `N(t) = max{n ≥ 0 : S_n ≤ t}`, `S_n = nΔ`.
The schedule is exact for the model's own convention — a swing whose impact
would land *exactly* at the window boundary is excluded, a measure-zero
boundary choice.

Ability recasts are scheduled on **one shared timeline** (the champion has one
set of hands): each cast occupies its sourced cast time, an ability recasts
when its effective cooldown has elapsed *and* no other cast is in progress, and
a cast counts when it *starts* within the window
(`_schedule_shared_casts`). With `c_i` the effective cooldown of ability `i`,
the cast epochs of a solo ability are `0, c_i, 2c_i, …` — again a deterministic
renewal schedule; the shared-timeline version is the superposition with
mutual-exclusion, resolved greedily by cast order. This replaced the legacy
`1 + T/c` independent-timeline count, which overcounted short-cooldown
abilities (Cassiopeia E: 5 vs. 3 in-game casts over 3 s).

**Theorem (renewal-reward).** For a renewal process with interarrival times
`X_i` and i.i.d. rewards `R_i` attached to each cycle, the long-run average
reward rate is `E[R]/E[X]` (the elementary renewal theorem / renewal-reward
theorem). The engine's totals are the *finite-horizon* version of this:
`Σ_{i<N(T)} R_i` with `N(T) = ⌊T/Δ⌋`. The expected-damage-per-second of a
rotation is the reward rate `E[cycle damage]/E[cycle time]`; every sustained
fight number in the engine is this finite-horizon renewal-reward functional.

- M. Vlasiou, *Renewal processes with costs and rewards*, arXiv:1404.5601
  (review of the renewal-reward theorem with a simplified proof).
- M. Zamparo, *Large deviations in renewal theory and renewal models of
  statistical mechanics*, arXiv:1801.09941 (formal renewal-reward framework,
  including rewards that grow with the interarrival time).
- C. Duval, *Nonparametric estimation of a renewal reward process from discrete
  data*, arXiv:1207.1611 (renewal-reward processes have non-stationary,
  dependent increments — motivating exact simulation rather than closed-form
  aggregation).

**Exact vs approximate.** The *counting* is exact under the deterministic
model. Two modeling choices are approximations, both documented in code:

1. **Uptime as a rate scale.** `u` multiplies the attack *rate* (`AS·u`)
   rather than modeling an on/off attacking process. For an on/off process the
   expected count is `E[N(T)] = λ·E[attacking time]` only when the interarrival
   clock is memoryless; for deterministic schedules it is exact in
   expectation only if swings are uniformly spread (Wald-style rate scaling).
   The error is bounded by ±1 swing and vanishes as `T` grows.
2. **Navori Flickerblade refunds** (`_navori_effective_cd`) simulate the
   discrete event process exactly — natural decay of the remaining cooldown
   between attack epochs, then `remaining ← (remaining − Δ)·(1 − r)` at each
   attack — an Euler discretization of the continuous process `dR/dt = −1`
   with multiplicative jumps at attack epochs. Exact for the discrete-event
   model; the only freedom is the in-game order of the natural tick vs. the
   refund, which the engine resolves as decay-then-refund.

### 1.2 Linearity of expectation for multi-hit abilities, procs, DoT ticks

**Theorem (linearity of expectation).** `E[Σ_i X_i] = Σ_i E[X_i]` for any
(random) variables, dependent or not. Three engine applications:

1. **Multi-hit abilities.** A part with `h` identical hits is mitigated per hit
   and summed: `Σ_h m(R)·raw = h·m(R)·raw` (`_mitigate_hits`). This is exact
   because the mitigation operator `x ↦ x·100/(100+R)` is *linear in raw
   damage* for a fixed resistance — splitting a 3×100 hit packet into three
   100-hit packets, or summing it into one 300 packet, gives the same
   post-mitigation total. (The operator is *not* linear in `R`, which is why
   averaging resistances is only approximate — Section 2.3.)
2. **DoT ticks.** A DoT total is partitioned into ticks by a uniform partition
   of its window (`_periodic_damage_events`): `⌊duration/interval⌋` full ticks
   of `(total/duration)·interval` plus a remainder tick at `duration`.
   Conservation `Σ ticks = total` is enforced with a drift correction on the
   last tick. This is the **Riemann-sum identity** for a constant rate over
   `[0, duration]` with the convention that the residual `duration mod interval`
   is paid at the window end (matching Riot's fixed-total DoTs, whose listed
   total is always delivered).
3. **Proc chains.** A Bernoulli "chance on hit" proc over `n` attacks has
   expected count `E[#procs] = n·p` (binomial mean = linearity of
   expectation). Deterministic every-`N`th-hit procs (Kraken Slayer, Hullbreaker)
   have exact count `⌊n/N⌋` — modular counting over the shared hit sequence
   (`_calculate_stacking_procs`). The engine models every-Nth cadences exactly
   and fixed-count chains exactly; no item in the current cache needs a
   *geometric* chain (Statikk Shiv's chain-lightning target count is a
   deterministic level-scaled integer, 4–8 by level).

**Literature anchors.** Linearity of expectation is the founding tool of the
probabilistic method (Alon & Spencer, *The Probabilistic Method*); for an
arXiv treatment of expectation identities in Bernoulli trials see
- E. Schlemm, *On the expected number of successes in a sequence of nested
  Bernoulli trials*, arXiv:1303.4979.

**Exact vs approximate.** All three applications above are exact for the
deterministic model. The subtle case is **stacking on-hit damage that reads
the target's current health** (Kraken's missing-health term): the engine
simulates the health path sequentially, proc by proc and auto by auto
(`_simulate_stacking_on_hit_damage`), instead of using a closed-form
"average missing health". Because the Kraken term `base·(1 + 0.75·missing)`
is *affine* in current health, evaluating it on the expected health path is
exact in expectation: `E[base·(1+0.75·(1−H/H₀))] = base·(1+0.75·(1−E[H]/H₀))`.
The sequential simulation is therefore the correct expectation computation,
not a heuristic. (The champion execute terms in Section 1.3 are *not* affine,
and there the deterministic path is genuinely an approximation.)

### 1.3 Order statistics, quantiles and hitting times for executes

**The Collector.** The execute boundary is the threshold `θ = 0.05·H₀` (5% of
maximum health). In probabilistic terms, an execute is a **quantile event**:
`P(target executed) = P(H(τ) ≤ θ) = F_H(θ)`, the CDF of target health at the
damage event. The engine prices the threshold as a display row and does *not*
add execute damage to totals (`_add_execute_display`) — the kill boundary is
documented, not double-counted. This is the conservative choice: an execute is
an absorbing event, not a damage instance.

**Pyke R (Death from Below).** The module prices the sourced *non-execute*
damage row (50% of the threshold) and documents the threshold
`250:550 + 80% bonus AD + 1.5 per lethality` as a boundary rather than damage.
For a full-health target above the threshold this is exact; the "what if the
target were below threshold" branch is the quantile event `P(H ≤ θ)` and is
deliberately not priced.

**Veigar R (Primordial Burst).** The reviewed module instantiates the wiki's
"increased by 0% : 100% (based on target's missing health)" as a piecewise
affine ramp:

```
d(m) = d_min · (1 + clamp((m − 2/3)/(1/3), 0, 1)),   m = missing-health ratio
```

evaluated per cast against the target's live health (`_primordial_burst_scaled`,
`_EXECUTE_MISSING_RATIO_START = 2/3`). The ramp is convex (slope 0 below
`m = 2/3`, slope `3·d_min` above). Consequently **Jensen's inequality
`E[d(M)] ≥ d(E[M])` bites**: evaluating the deterministic expected path
understates the expected execute damage whenever the target's health
distribution straddles the ramp region. The engine documents this; the error is
first-order in the health-path variance and vanishes when the target is far
from the ramp or when the damage path is deterministic (as it is in
deterministic mode — the residual bias is only from the *champion-side*
randomness that deterministic mode averages away).

**Theorem (hitting time / first-passage).** "When does the target's health
first cross θ?" is the first-passage time `τ = inf{t : H(t) ≤ θ}` of the
damage process. For the deterministic model, `τ` is the index of the first
cumulative-damage event exceeding `H₀ − θ` — an order statistic of the
cumulative damage sequence. The engine computes these exactly for threshold
triggers (Stormsurge's rolling window: `_damage_threshold_trigger_time` scans
the event ledger with a sliding-window sum — the exact crossing time of a
discrete cumulative process).

**Literature anchors.**
- I. Pinelis, *Order statistics on the spacings between order statistics for
  the uniform distribution*, arXiv:1909.06406 (order-statistic distributions,
  relevant to gap/quantile questions on uniform event streams).
- *Precise quantile function estimation from the characteristic function*,
  arXiv:2502.13537 (quantile-function identities; the execute threshold is a
  quantile of the health distribution).
- *Recurrence rates and hitting-time distributions for random walks on the
  line*, arXiv:1003.5073 (first-passage/hitting-time distributions — the
  crossing-time analogue for the damage process).

### 1.4 Geometric sums for proc chains

Where geometric structure genuinely appears:

- **Expected trials until a proc.** For an every-`N`th-hit proc, the gap
  between procs is deterministic `N`; for a Bernoulli proc with chance `p` the
  gap is geometric with `E[gap] = 1/p` and the expected number of procs in `n`
  hits is `n·p`. Both identities are pinned by the engine's counting functions.
- **Chain-lightning / bounce effects.** Statikk Shiv's Electrospark bounces to
  a deterministic level-scaled count; the single-target fight prices one
  allocation across the roster (`statikk_chain_target_count`). No engine
  formula needs an infinite geometric series; if a future item grants
  "chance to re-proc", the correct total is `E = base·p/(1−p)` (the geometric
  series `Σ_{k≥1} base·p^k`), which is the identity to reach for.

**Literature anchor.** arXiv:1303.4979 (Schlemm) again covers the Bernoulli
success-count asymptotics used here.

---

## 2. Resistance and penetration

### 2.1 The 100/(100+R) identity

**Definition (damage multiplier).** With post-penetration resistance `R ≥ 0`,

```
m(R) = 100 / (100 + R)          (apply_resistance, resistance.py)
```

The reduction *fraction* is `1 − m(R) = R/(100+R)`; the **effective-health
identity** is the round-trip

```
post = raw · m(R)  ⟺  raw = post · (1 + R/100) = post · EHP_multiplier(R),
EHP(R) = H₀ · (1 + R/100).
```

A target with `H₀` health and resistance `R` survives exactly `H₀·(1+R/100)`
raw damage. The family `m(R) = 1/(1 + R/100)` is the **sigmoid/logistic
family** (with `R/100 = e^x`, `m = 1/(1+e^x)`); its signature property is
convexity in `R`, which drives every "average over a ramp is approximate"
result below.

**Negative resistance.** The game's piecewise extension (and the engine's):

```
m(R) = 2 − 100/(100 − R)   for R < 0          (apply_resistance)
```

This matches the general form at `R = 0` (`m(0⁺) = m(0⁻) = 1`) and saturates at
`m → 2` as `R → −∞` (a target at −∞ resistance takes double damage, never
more). It is *not* the analytic continuation `100/(100+R)` (which diverges at
`R = −100`). Only armor/magic *reduction* effects can push resistance negative;
penetration floors at 0 (Section 2.2).

**Literature anchor.** The logistic/sigmoid family:
- N. A. Kudryashov, M. A. Chmykhov, *Logistic function as solution of many
  nonlinear differential equations*, arXiv:1409.6896.

### 2.2 Penetration and reduction order: exact composition

The game applies, in order: **flat reduction → percentage reduction →
percentage penetration → flat penetration** (Wiki: "Armor reduction",
"Damage reduction"). The engine owns the two halves separately:

```
reduce_resistance(R, r_flat, r_pct):   R ← R − r_flat;  R ← R·(1 − r_pct/100)   [flat first, then %]
apply_{armor,magic}_penetration(R, f, p): R ← max(0, R·(1 − p) − f)              [% first, then flat, floor 0]
```

**Exactness.** When each step applies to the *running* value, the composition
is exact and order-sensitive:

```
R_final = max(0, (R − r_flat)·(1 − r_pct/100)·(1 − p) − f)
```

The engine's per-step composition reproduces this closed form exactly
(verified numerically, Section 3 of the tests). Percent-then-flat is exact per
the game's stated order — there is no commutativity, and the engine never
reorders.

**Floor.** Penetration cannot reduce resistance below 0; excess lethality/flat
pen is wasted, never converted into damage-amplifying negative resistance
(`max(0, …)`). Reduction *can* go negative, and penetration then leaves the
negative value untouched (a shred to −8 armor is neither deepened nor undone
by pen).

### 2.3 Where the composition is an approximation

Two averaging models enter the fight path, and both are Jensen-approximations
because `m(R)` is convex in `R`:

1. **Terminus stacking pen** (`StackingPenEffect.average_pen`): the engine
   replaces the per-swing pen ramp with its arithmetic mean `R̄` and mitigates
   every swing at `m(R̄)`. Since `m` is convex, `(1/n)Σ m(R_i) ≥ m(R̄)` — the
   average-pen model *understates* total damage relative to the true
   per-swing ramp. The error is second order in the ramp's spread and
   vanishes for ramps that are flat (all swings at max stacks).
2. **Black Cleaver average stacks** (`ArmorReductionEffect.average_reduction`):
   the established model uses a fixed `0.8·max_stacks` constant (with a
   `hits/2` short-fight branch). Under the engine's own ordering convention
   (4 leading ability hits apply stacks before the auto stream) the exact
   Cesàro mean of the capped ramp `min(k, C)` over `h` hits is
   `C − C(C−1)/(2h)` for `h ≥ C`; the constant model equals the exact mean at
   ~10 autos and deviates by up to ±20% at the extremes. The stack *duration*
   (6 s) is always longer than the engine's inter-swing interval for any
   realistic AS·u > 1/6, so expiry does not rescue the constant — this is a
   documented tuning constant, not a theorem. **Recommendation:** replace the
   constant with the closed-form Cesàro mean when a champion module needs
   exact BC numbers (a candidate P3 item; changing it re-tunes every BC fight
   in the corpus, so it is not a P2 foundation change).
3. **Negative-armor percentage reduction** (`reduce_resistance`): the engine
   applies percentage reduction only while `R > 0`. The League Wiki's *Armor
   penetration* article states: "Flat armor reduction can reduce armor values
   below 0, while **percentage armor reduction cannot**." The engine's guard
   implements exactly that rule — percentage reduction acts on positive
   armor; negative armor is the exclusive domain of flat reduction. The
   residual ambiguity (whether the game multiplies an already-negative value,
   which would move it toward 0 and *reduce* the amplifier) is a
   game-file-verification item (Community Dragon character records), not a
   formula error; the guard's direction is fail-safe for the attacker.

---

## 3. BIS optimization

### 3.1 Exact formulation

The BIS problem is a **cardinality-constrained combinatorial optimization**
over loadout slots:

```
maximize   f(S)
subject to S ⊆ L,  |S| = k,  S respects exclusivity groups,
           gold(S) ≤ B,  boots choice fixed/optimized
```

where:

- `L` = eligible legendary items (116 in the current cache; the public
  coverage receipt reports the role-scoped subset — "~96" in the task
  statement is the coverage-filtered pool),
- `k` = `max_legendary_slots` (default 5),
- `f(S)` = the **coupled participant-timeline score**: deterministic total
  damage dealt by the main participant before its own death, summed over the
  fight window, with an infinitesimal effective-health tiebreak
  (`score + EHP·1e-9`, optimizer.py `_evaluate_build_uncached`),
- exclusivity groups: at most one item per group (Spellblade, Fatality,
  Blight, …), enforced by `loadout_rules`.

**Search-space size.** `|L| = 116`, so a 5-slot build has

```
C(116, 5) ≈ 1.60 × 10^8  subsets  (×7 boot choices ≈ 1.12 × 10^9 loadouts)
```

Each evaluation is a full coupled fight simulation (~ms). Exhaustive search is
infeasible; the engine therefore runs an **exact exhaustive pass only for the
one-item opening** (`slots_to_fill ≤ 1`, certified "exhaustive legal
candidates" when coverage is complete) and a **multi-start greedy + hill
climbing local search** for full builds.

### 3.2 Approximation and its guarantees

The greedy phase fills slots one at a time, each time picking the
highest-marginal item; three seeds (none, top-AD, top-AP) give multi-start
diversity; the hill-climb phase swaps one item (or the boots) at a time,
accepting strictly improving moves, for up to 10 iterations. The search is a
classic **local search / hill climbing** heuristic:

- If `f` were monotone submodular, greedy would carry the
  `(1 − 1/e)` approximation guarantee (Nemhauser–Wolsey–Fisher). It is not:
  `f` couples every slot through the shared timeline (death time, shield
  thresholds, proc cadence), so marginal gains are not monotone, and the
  engine never claims a guarantee — the public receipt labels full-build
  results `local_search` and explicitly *not* "certified best in slot".
- The score memo (`score_memo`, `pair_result_cache`, `CoupledSearchContext`)
  reuses every evaluation a candidate swap cannot change, which is what makes
  thousands of coupled evaluations tractable — a duality between
  "what changes when one slot changes" and the per-search cache key
  (see `architecture.md`, Optimization).

**Published theory for item-recommendation problems:**
- A. Dallmann, J. Kohlmann, D. Zoller, A. Hotho, *Sequential Item
  Recommendation in the MOBA Game Dota 2*, arXiv:2201.08724 — the closest
  published treatment of MOBA item recommendation (sequential purchase
  prediction); it is a learning task, whereas Scryglass ranks by *simulated
  deterministic outcome*, which is a different and stronger objective.
- H. Zhang, W. Luo, *A unified continuous greedy algorithm for k-submodular
  maximization under a down-monotone constraint*, arXiv:2311.18239 — the
  greedy-with-guarantee family the optimizer's greedy phase is a (non-
  guaranteed) instance of; the coupling of the score function is exactly what
  voids the guarantee.
- Y. Bian, J. M. Buhmann, A. Krause, *Continuous Submodular Function
  Maximization*, arXiv:2006.13474 — background on the submodularity
  machinery and why the score's coupling breaks it.

---

## 4. Variance and confidence

**What the number claims.** The deterministic score is the point estimate
`E[D | model, config]` computed under the expectation heuristic of Section 0.
It claims nothing about:

- **Variance**: crit streaks, proc timing jitter, and target-health-path
  variance are averaged away. Two builds whose scores differ by less than the
  unmodeled variance are statistically indistinguishable — the engine's
  `1e-9` tiebreak is a *deterministic* total order, not a statistical claim.
- **Model error**: unmodeled mechanics (generic-parser champions, coarse
  event ordering, vision boundaries such as Pyke's out-of-vision grey-health
  consume) fail closed or are disclosed; the number is only as good as the
  reviewed module set.
- **Distributional shape**: no quantiles, no worst-case, no "will this kill
  at level 6" probability. Execute thresholds are boundaries, not
  probabilities (Section 1.3).

**How a validation corpus turns point estimates into calibrated statements.**
The golden snapshot (`scripts/golden_snapshot.py`) and the E-series corpus pin
point estimates against game-verified scenarios. The statistically principled
route from a corpus of `(model, observed)` pairs to a *calibrated* statement is
**conformal prediction**: with `n` exchangeable validation points, the rank of
a new point's error among the corpus errors gives a distribution-free
coverage guarantee `P(|model − game| ≤ q_{⌈(1−α)(n+1)⌉}) ≥ 1 − α` for the
empirical quantile `q` — no distributional assumptions. That is the exact
machinery to attach honest "the model is within X of the game with 95%
confidence" claims to the existing corpus, and it is the recommended next step
(P3) when a full validation corpus exists.

**Literature anchors.**
- A. N. Angelopoulos, S. Bates, *A Gentle Introduction to Conformal Prediction
  and Distribution-Free Uncertainty Quantification*, arXiv:2107.07511.
- *Monte Carlo: Basics*, arXiv:cond-mat/0104215 (point-estimate error scales as
  `σ/√n`; the deterministic number has `n = 1` by construction and therefore
  no error bar).

---

## 5. Formula-audit table

Legend: **EXACT** = instantiates the identity exactly under the deterministic
model; **APPROX** = documented approximation (never silently presented as
exact). All game-rule claims were cross-checked against the League Wiki
(armor/penetration, movement speed, crit, grievous wounds, executes).

| Engine family (location) | Theorem / identity it instantiates | Verdict | Edge case the math says is wrong / must be documented |
|---|---|---|---|
| Resistance mitigation (`apply_resistance`) | `m(R)=100/(100+R)`; EHP round-trip `raw = post·(1+R/100)`; sigmoid family | **EXACT** | Negative branch is `2−100/(100−R)` (not the analytic continuation); continuous at 0, saturates at 2× |
| Penetration (`apply_{armor,magic}_penetration`) | percent-then-flat, floor at 0; reduction-then-penetration composition | **EXACT** | Penetration never deepens negative resistance (reduction-only); composition order is non-commutative and reproduced exactly |
| Percent reduction on negative armor (`reduce_resistance`) | Wiki rule: "Flat armor reduction can reduce armor values below 0, while **percentage armor reduction cannot**" (League Wiki, *Armor penetration*) | **EXACT** | Engine applies % reduction only while R>0, matching the wiki rule; residual ambiguity (game behavior on an input already below 0) is a game-file-verification item, not a formula error |
| Stat growth (`growth_stat`) | `base + growth·(L−1)·(0.7025 + 0.0175·(L−1))` | **EXACT** | Level cap 20 (top lane); formula season-volatile, single source of truth `MAX_LEVEL` |
| Attack speed (`calculate_attack_speed`) | `base_AS + AS_ratio·bonus/100` | **EXACT** | Total AS cap 3.003 deliberately NOT clamped fight-wide (Jayce reads it) |
| Ability haste (`effective_cooldown`) | `cd' = cd·100/(100+AH)`; casts/unit time affine in AH | **EXACT** | R casts exactly once per timed fight (model constraint, documented) |
| Auto DPS / auto count (`_auto_attack_timestamps`, `num_auto_attacks`) | renewal counting `N(T)=⌊AS·u·T⌋`; periodic schedule `t_i=i/rate` | **EXACT*** | *uptime-as-rate-scale approximation; swing exactly at T excluded (measure-zero boundary) |
| Crit expectation (`_simulate_auto_attacks`, `_evaluate_cast_parts`) | `E[swing] = (1−p)·1 + p·CM = 1+p·(CM−1)`; mitigation commutes with expectation (linear in raw) | **EXACT** | Deterministic path evaluates `f(E[H])` for health-dependent terms; exact for affine f (Kraken), Jensen-biased for convex f (Veigar R ramp) |
| Ability rotation casts (`_schedule_shared_casts`, `_compute_ability_rotation`) | shared-timeline renewal schedule; cast starts within window | **EXACT** | GCD/0.5s inter-cast estimate used only in one-rotation burn spread (see burn row); R single-cast |
| DoT totals (`_periodic_damage_events`) | uniform partition / Riemann sum; conservation `Σ ticks = total`; remainder < interval paid at window end | **EXACT** | First tick at +interval (no immediate tick); interval > duration → single remainder tick at duration |
| Stacking DoT (`_DotTickLedger`) | integral of piecewise-constant stack rate bucketed at tick boundaries; `Σ raw·scale = total` | **EXACT** | Overlapping re-applications: chain clock anchored per application chain; refresh-reset semantics are per-chain, total conserved |
| Ability DoT event authoring (`_ability_dot_tick_events`) | even split of row total across casts | **APPROX** | Splits by cast count even when casts land at different mitigation states (Vile Decay ramp); total conserved, per-tick pairing approximate |
| On-hit stacking (`_calculate_stacking_procs`, `_simulate_stacking_on_hit_damage`) | modular every-Nth counting; sequential health-path expectation (affine ⇒ exact) | **EXACT** | Ability-carried on-hits lead the shared counter (ordering convention); double-on-hit extra stacks attributed to a prefix of autos, not the spellblade's actual weave times |
| Phantom hits (`_calculate_phantom_hits`) | deterministic cadence: first phantom at attack `stacking_autos+1`, then every `interval` | **EXACT** | Assumes the Seething-stack window never lapses (true for continuous streams; approximate for gappy uptime) |
| Burn/DoT items (`_add_burn_damage`) | refresh model: window = last-refresh + duration, total scaled by window/duration | **APPROX** | One-rotation cast spread uses a 0.5 s GCD estimate (engine casts at t=0); burn resolves past the fight end by design; timed mode uses the real `last_cast_time` (exact) |
| Grievous Wounds (`healing_reduction.py`, survival walk) | multiplicative factor 0.60 (40% reduction); strongest-wins composition via `min` of factors; duration refresh via `max` | **EXACT** | Heal landing exactly at window expiry is un-reduced (boundary convention); sources do not stack (min is the game rule) |
| Shield absorption (survival walk) | clipping identity `absorbed = min(shield, damage)`, `overkill = max(0, damage−absorbed)`; `absorbed+overkill = damage` | **EXACT** | Consumption order = earliest-expiring timed shields first, then untimed pools (FIFO proxy); venom cuts non-magic shields granted under the wound |
| Grey health (`_grey_health_receipts`) | saturating accumulator `pool = min(cap, ratio·Σ post-mitigation incoming)` | **EXACT** | Out-of-vision consume (Pyke) is a vision boundary, documented not authored; cap = min(80 + 800% bAD, 55% max health) |
| Revive (survival walk) | absorbing-state machine: earliest lethal packet triggers revive at `death_time + delay`; restore = min(max_health, amount) | **EXACT** | Candidate revive authored after every damage event, applied only when dead — exact earliest-trigger semantics; post-window revives visible but not applied |
| BIS score (`_evaluate_build_uncached`) | finite-horizon renewal-reward functional: cumulative damage until death; EHP·1e-9 lexicographic tiebreak | **EXACT*** | *the tiebreak is an infinitesimal regularizer (documented), never a material ordering; `effective_health` receipt is "total resources", not remaining health |
| Stat rounding (`calculate_total_stats`) | display-level integer rounding of health/AD/AP/armor/MR before damage | **APPROX** | Riot computes with full precision; rounding drifts mitigation and scalings by <1 unit — corpus-wide convention, pinned by golden |
| Terminus/BC ramps (`average_pen`, `average_reduction`) | Cesàro mean of the per-hit ramp | **APPROX** | m(R) convex ⇒ averaging understates ramp damage (Jensen); BC constant = exact mean at ~10 autos, ±20% at extremes (Section 2.3) |

**Audit conclusion.** Every *core* formula family instantiates its stated
identity exactly under the deterministic model (renewal counting, linearity of
expectation, mitigation linearity, uniform DoT partition, modular proc
counting, crit expectation, clip identities, strongest-wins GW, saturating
grey-health accumulator, earliest-trigger revive). The approximations found are
all **documented in code** (burn GCD estimate, BC stack constant, Terminus pen
average, R single-cast, DoT even-split, stat rounding, prefix double-on-hit
attribution) — none is silently presented as exact. The one previously-suspect
rule (percent reduction on negative armor) matches the League Wiki's stated
boundary ("percentage armor reduction cannot [reduce below 0]"), with a
game-file-verification footnote remaining. No combat formula was found
mathematically wrong, so **no combat-number change was made**; the P2 hardening
is the documentation above plus the pinned identity suite in
`tests/test_p2_math_foundations.py`.

---

## 6. References (arXiv)

1. M. Vlasiou, *Renewal processes with costs and rewards*, arXiv:1404.5601.
2. M. Zamparo, *Large deviations in renewal theory and renewal models of
   statistical mechanics*, arXiv:1801.09941.
3. C. Duval, *Nonparametric estimation of a renewal reward process from
   discrete data*, arXiv:1207.1611.
4. E. Schlemm, *On the expected number of successes in a sequence of nested
   Bernoulli trials*, arXiv:1303.4979.
5. I. Pinelis, *Order statistics on the spacings between order statistics for
   the uniform distribution*, arXiv:1909.06406.
6. *Precise quantile function estimation from the characteristic function*,
   arXiv:2502.13537.
7. *Recurrence rates and hitting-time distributions for random walks on the
   line*, arXiv:1003.5073.
8. N. A. Kudryashov, M. A. Chmykhov, *Logistic function as solution of many
   nonlinear differential equations*, arXiv:1409.6896.
9. A. Dallmann, J. Kohlmann, D. Zoller, A. Hotho, *Sequential Item
   Recommendation in the MOBA Game Dota 2*, arXiv:2201.08724.
10. H. Zhang, W. Luo, *A unified continuous greedy algorithm for k-submodular
    maximization under a down-monotone constraint*, arXiv:2311.18239.
11. Y. Bian, J. M. Buhmann, A. Krause, *Continuous Submodular Function
    Maximization*, arXiv:2006.13474.
12. A. N. Angelopoulos, S. Bates, *A Gentle Introduction to Conformal
    Prediction and Distribution-Free Uncertainty Quantification*,
    arXiv:2107.07511.
13. *Monte Carlo: Basics*, arXiv:cond-mat/0104215.
