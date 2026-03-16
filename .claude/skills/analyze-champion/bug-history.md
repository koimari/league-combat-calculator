# Champion Implementation Bug History

When a user reports a bug or incorrect behavior after a champion is implemented, log it here so future `/analyze-champion` runs can catch the same pattern.

## Format

```
### <Champion> — <short description>
- **What happened:** <the incorrect behavior>
- **Root cause:** <why it was wrong>
- **Pattern to watch for:** <generalized rule for future champions>
```

## Logged Bugs

### Aatrox — R showed damage in breakdown
- **What happened:** R was calculating and displaying damage when it should only grant stats.
- **Root cause:** R is a stat-buff ultimate (bonus AD), not a damaging ability. Should use `total_raw: 0.0`.
- **Pattern to watch for:** Stat-granting ultimates (bonus AD, AP, armor pen, etc.) should have `total_raw: 0.0` and use `stat_buff` dict instead.

### Aatrox — Passive applied on every auto attack
- **What happened:** Passive empowered auto damage was added to every auto attack.
- **Root cause:** Aatrox passive has a cooldown between procs. It should be a configurable proc count, not applied per-auto.
- **Pattern to watch for:** Any empowered auto passive — check if it has a cooldown. If yes, use `passive_procs` champion option.

### Akshan — R damage overestimated
- **What happened:** Comeuppance damage was significantly higher than in-game.
- **Root cause:** Crit chance and crit damage scale R at 30% effectiveness, not 100%. E.g., 100% crit chance = 30% more damage, not 100%.
- **Pattern to watch for:** Any ability with crit scaling — verify the effectiveness ratio. Wiki sometimes phrases it ambiguously.

### Alistar — E empowered auto applied every auto
- **What happened:** E's bonus damage on next auto was applied on every auto attack in the fight.
- **Root cause:** "Next basic attack" means once per cast, not a permanent on-hit.
- **Pattern to watch for:** "Empowers next basic attack" = once per cast. "Basic attacks deal bonus damage" = every auto. Read the wording carefully.

### Ambessa — R armor pen not applied before damage calc
- **What happened:** Q/W/E damage was calculated without R's armor penetration bonus.
- **Root cause:** R passive grants armor pen per rank, which should always be active. Must apply to `stats_context` BEFORE calculating other abilities. Process R first in parse order.
- **Pattern to watch for:** Any ability with a passive stat component — process it first so other abilities benefit.

### Ambessa — Q missed % max HP damage
- **What happened:** Q2 (Sundering Slam) damage was lower than expected.
- **Root cause:** Q2 has a % max HP damage component in addition to flat + ratio damage. It was overlooked.
- **Pattern to watch for:** Always check every ability description for "%HP", "% maximum health", "% current health", "% missing health" components.

### Ambessa — Q2 casts didn't match Q1
- **What happened:** Q1 was calculated N times but Q2 was only calculated once.
- **Root cause:** Q2 is a recast that always follows Q1. If Q1 is cast 3 times, Q2 should also be cast 3 times.
- **Pattern to watch for:** Recasts should always have the same cast count as their parent ability.

### Ashe — Passive crit bonus additive instead of multiplicative with Q
- **What happened:** Auto attack damage with Q active was ~16% lower than in-game. With Q rank 5, 75% crit, and IE, calculator showed ~285/hit instead of ~332/hit.
- **Root cause:** Passive Frost Shot says bonus damage is "X% of the attack's damage." With Q active, each arrow individually applies Frost Shot, so the crit bonus multiplies the flurry damage. Formula was `AD * (flurry_ratio + crit_bonus)` (additive) instead of `AD * flurry_ratio * (1 + crit_bonus)` (multiplicative). Both give the same result when ad_ratio=1.0 (no Q), but diverge when Q is active.
- **Pattern to watch for:** When a passive says bonus damage is "% of the attack's damage" and another ability modifies the base attack ratio, the bonus must be multiplicative with the modified ratio, not additive.

### Amumu — Q damage doubled by fight engine
- **What happened:** Q showed ~265 damage instead of ~110 for a single cast with Liandry's at level 18 against 100 MR.
- **Root cause:** Two compounding issues: (1) Q result had both `damage_per_cast`/`total_casts` AND pre-multiplied `magic_damage`, causing fight engine double-counting. (2) Module pre-baked `q_casts=2` into `magic_damage`, but fight engine already determines cast count from cooldown. In one-rotation mode the engine casts once, but `magic_damage` already had 2 casts of damage.
- **Pattern to watch for:** Charge abilities (2+ charges) should report **single-cast damage** and use `rechargeRate` (not the inter-cast CD) as `cooldown`. Let the fight engine determine cast count. Never pre-multiply cast count into `magic_damage`/`physical_damage` — the fight engine handles repetition via `num_casts`. The `damage_per_cast`/`total_casts` pattern is only for sub-casts within a single ability use (e.g., Ahri R's 3 dashes per activation).
