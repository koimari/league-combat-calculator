# F2 — Optimal Event-Order Engine (combo layer)

Status: implemented on `codex/f2-rotation`.
Owner: Scryglass combat pipeline (`src/calculator/rotation_resolver.py`).
Gate: `pytest`, `pylint src/ --fail-under=9`, `black --check src/ tests/`,
`node --check static/js/eventorder.js`, golden snapshot re-capture.

## Problem

The fight engine's default rotation was the fixed `DEFAULT_CAST_ORDER`
`("Q", "Q2", "W", "E", "R")` — every champion cast Q, then W, then E,
then R. That order is wrong for kits whose abilities have real
setup/consume relationships:

- Cassiopeia's `E` (Twin Fang) only deals its enhanced damage to
  **poisoned** targets — the rotation must open with `Q` (Noxious Blast)
  and reapply the poison as soon as its cooldown is back, spamming `E`
  between reapplications.  A fixed `E`-last order prices the E-spam
  cadence late, costing casts in short windows.
- Varus' `Q` (Piercing Arrow) **detonates** the Blight stacks that
  basic attacks (W) apply — the detonator must come after the appliers.
- Vladimir's `R` (Hemoplague) amplifies all damage taken by 10% for 4s —
  it must open, not close, the burst.
- Aatrox's `R` grants bonus AD as a percentage of total AD — the buff
  must be up before The Darkin Blade is priced.

Once abilities and champions are atomized (per-ability leveling rows in
`data/champions.json`, typed `DamagePart`s and module metadata in
`src/calculator/champions/`), the optimal order can be **derived from
data** instead of hard-coded per champion in the engine.

## Design

### Where the order comes from

The fight's cast order is resolved in one place,
`src/calculator/rotation_resolver.py`, as a four-signal score:

| # | Signal | Data source | Weight |
|---|--------|-------------|--------|
| a | **Setup/consume relationships** | `on_hit` + `post_hit_proc` (Varus W→Q), `dot_duration` + poisoned-option (Cassiopeia Q→E), Blaze stack applications (Brand P), AMP pseudo-slot (Vladimir R), `stat_buff` (Aatrox R), mark/proc rows (Lux P, Zed R stored damage) | strongest |
| b | **DPS contribution per rank** | `total_raw` / effective per-rank `cooldown` at the fight's stats, weighted by the number of enemy champions an AoE slot can hit (`rank_ability_dps` with `aoe` + `target_count`) | strong |
| c | **Cooldown gating** | the engine's shared cast timeline (`_schedule_shared_casts`): placing the low-cooldown spam tool right after its setup starts its cadence earliest | tie-break |
| d | **Buffs before damage** | `stat_buff` / AMP slots must resolve before the abilities they amplify | strong |

Signal (a) is encoded as each combo rule's `setup` / `consume` slot
lists; signal (b) is computed from the parsed ability rows; signals (c)
and (d) are encoded in the rule's `order` and enforced by the engine's
existing scheduler.

### AoE — abilities that hit more than one champion

Every combo rule carries an `aoe` map: slot → maximum enemy champions the
ability can hit (conservative caps from the kit's shape — a ground zone or
cone is capped at 5, Jhin's Dancing Grenade at 4 bounces, Lux's Light
Binding at 2 roots, Aatrox's Infernal Chains at 2).  The AoE metadata
feeds two things:

- **The DPS signal (b)** multiplies an AoE slot's effective DPS by
  `min(roster target count, cap)` — `rank_ability_dps(..., target_count=N)`
  ranks an ability that hits all five enemies five times higher than the
  same raw damage on a single target, so the derived order reflects the
  actual roster, not a 1v1 abstraction.
- **The rotation receipt** carries `aoe` verbatim so the UI can explain
  "this slot is AoE — it hits up to N champions" next to the rationale.

The fight engine's own multi-target plumbing (`roster_target_count` in
`FightConfig`/`target_stats`, item procs, Karthus Q) is untouched; the
combo layer uses the same count for ranking.  The conservative cap keeps
the model honest: we never claim more hits than the ability's shape
allows, and the default 1v1 fight is unchanged (multiplier 1).

### Resolution chain (explicit order wins)

```
/api/calculate payload cast_order  (user-supplied, validated permutation)
   -> COMBO_TABLE rule              (this module — optimal per-champion order)
   -> champion module CAST_ORDER    (certified orders: Jayce, Kai'Sa, ...)
   -> DEFAULT_CAST_ORDER            (Q, Q2, W, E, R — no combo signal)
```

A combo rule's `order` may omit slots (Aatrox has no E; Annie's E is
shield-only); the engine skips entries absent from the parsed ability
package, and `resolve_auto_attack_policy` skips them too.

### The combo table (batch 1 — 10 champions)

| Champion | Derived order | Driving atom / metadata | Setup → Consume |
|----------|---------------|-------------------------|-----------------|
| *(AoE caps)* | — | every rule carries `aoe` (slot → max champions hit, e.g. Brand W/E 5, Lux R 5, Jhin Q 4) | weighted into signal (b) |
| Cassiopeia | `Q, E, W, R` | Q `Total Magic Damage` 3s poison (`dot_duration` 3.0, 7 ticks); E poisoned bonus via `target_poisoned` option; E cooldown 0.75s | Q/W → E |
| Varus | `Q, E, R, W` | W `Bonus Magic Damage per Stack` (% max HP, `blight_stacks` max 3); W `on_hit` applies Blight per auto; Q `post_hit_proc` Blight Detonation | W(autos) → Q/E/R |
| Brand | `Q, R, E, W` | P `Max Health Damage` 3-stack detonation; Q/W/E apply 1 Blaze stack; R applies 1 per bounce (`r_bounces`); E spreads Blaze | Q/R/W → E |
| Vladimir | `R, Q, E, W` | R Hemoplague 10% damage-taken AMP (`r_hemoplague_debuff`); R detonation; W 2s DoT | R → all |
| Aatrox | `R, Q, W` | R `stat_buff` `Bonus Attack Damage` percent_of AD; Q `Sweetspot Damage` rows; W `Total Damage` | R → Q/W |
| Jhin | `Q, W, E, R` | P 4th-shot guaranteed crit + 15–25% missing health (`p_final_shot`/`p_shot_number`); R 4-shot barrage | autos → R |
| Annie | `R, Q, W` | P Pyromania stun; R `Initial Magic Damage` + magic-pen `stat_buff` + `tibbers_attacks` | P → R/Q/W |
| Lux | `E, Q, R, W` | E slow; Q root; R consumes Illumination (`p_illumination_procs`) | E/Q → R |
| Zed | `W, E, Q, R` | W Living Shadow placement; E/Q `Physical Damage`; R Death Mark 100% AD + % of stored damage, 3s detonation | W → R(stores E+Q) |
| Aphelios | `Q, W, R` | Q weapon-form variants (`aphelios_main_weapon`); W Phase swap (0.25s CD); R initial blast + follow-up | Q/W → R |

Every rationale and source list is authored in `COMBO_TABLE` with the
atom/attribute that drives it, so patch-day audits can re-verify each
rule against the cached `data/champions.json` rows.

### Fallback

Champions with **no combo signal** keep the engine's historical
`DEFAULT_CAST_ORDER` (`Q, Q2, W, E, R`) with a documented fallback
rationale in the rotation receipt; champions with a certified module
`CAST_ORDER` keep that reviewed order (those are themselves combos and
migrate into `COMBO_TABLE` as they are re-certified).

## Rotation receipt (`/api/calculate`)

Every calculate response now carries a `rotation` receipt so the UI can
show *why* the order is optimal:

```json
{
  "rotation": {
    "order": ["Q", "E", "W", "R", "E", "E", "E", "Q", "E", ...],
    "rationale": "Q (Noxious Blast) applies the 3s poison (7 ticks) first; E (Twin Fang) consumes the poison ...",
    "cast_order": ["Q", "E", "W", "R"],
    "sources": ["Q 'Total Magic Damage' 3s poison (dot_duration 3.0, 7 ticks)", "..."],
    "setup": ["Q", "W"],
    "consume": ["E"]
  }
}
```

- `order` is the fight's **actual** cast sequence from the engine's
  cooldown-aware `cast_timeline` — one-rotation mode: the derived
  permutation, once per slot; timed mode: every recast at its cooldown
  (Cassiopeia Q at t=0 / 3.75 / 7.5 with E-spam between, exactly the
  "apply-before-consume, reapply at CD" cadence the product asked for).
- `rationale` is the plain-language explanation shown verbatim.
- `cast_order` is the derived permutation; `sources` names the atoms;
  `setup` / `consume` expose the relationship machine-readably.
- The fallback receipt for a champion with no combo signal explains that
  the default order applies.

## Cooldown gating in timed mode

The resolver derives the *permutation*; the engine's existing shared
cast timeline (`_schedule_shared_casts`) does the *cadence*: each cast
occupies its `cast_time`, an ability recasts when its per-rank cooldown
— running from the end of its cast — is back up and no other cast is in
progress, with ties broken by `cast_order` position.  Putting the setup
ability (Q) before the spam tool (E) means the spam cadence starts at
the earliest possible moment: in a 3s fight the combo order lands 4
Twin Fangs vs 3 under the fixed order; Zed's W-first order (zero cast
time) lets E fire at t=0 and again at t=5.0 where the fixed order
delays E to t=0.25 and misses the second cast.  These are the
"expected and desired" golden diffs.

## Frontend

`static/js/eventorder.js` is a self-contained module (no `app.js`
edits).  It installs a read-only `window.fetch` wrapper before `app.js`
loads, captures each `/api/calculate` response the app already makes,
and renders the event-order panel into `#eventOrderPanel`
(templates/index.html mount point): a chip rail of the cast sequence
with times, the combo rationale, and the atom sources.  It never
re-fetches, never mutates the app's responses, and stays hidden when no
rotation receipt exists.

## Verification

- `tests/test_f2_rotation.py` — per-combo-champion parse-level rotation
  assertions (order + rationale + setup/consume) and time-based fights
  asserting cooldown-respecting cadence (Cassiopeia Q at CD intervals
  with E in between; Varus autos/Blight before Q detonation).
- Golden snapshot re-captured: 13 entries change across 6 combo
  champions (Cassiopeia, Brand, Vladimir, Aatrox, Annie, Zed) — every
  diff is the optimal-order change (Shadowflame threshold allocation in
  the magic build, or timed-mode cast counts), explained in the commit.
