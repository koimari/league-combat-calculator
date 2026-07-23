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

### Kog'Maw — Q damage inflated by own resistance shred
- **What happened:** Q showed 248 damage instead of 211 against 100 MR target. Q's 32% MR/armor shred was being applied before Q's own damage.
- **Root cause:** `target_debuff` processing ran in a pre-loop block before all ability damage calculations, so Q's shred reduced MR globally before Q itself was evaluated. In-game, Q's shred only applies after Q hits.
- **Pattern to watch for:** Abilities that apply resistance shred/reduction must NOT benefit from their own debuff. Process the debuff AFTER calculating the source ability's damage, inside the cast order loop, so only subsequent abilities benefit.

### Kog'Maw / General — Terminus pen applied to ability damage
- **What happened:** With Terminus equipped, all ability damage was calculated with Terminus's average armor/magic penetration, inflating ability damage and showing reduced effective MR (70 instead of 100).
- **Root cause:** Terminus pen was computed as a weighted average across autos and applied to the global `armor_pen_percent` / `magic_pen_percent` variables, which were then used for both ability and auto-attack damage. Terminus pen stacks only build from auto attacks, so abilities should get zero Terminus pen.
- **Pattern to watch for:** Item penetration that stacks via auto attacks (Terminus Juxtaposition) must use separate pen variables for abilities vs autos. Split into `ability_*_pen_percent` (no item-stacking pen) and `auto_*_pen_percent` (with weighted average). Switch from ability pen to auto pen after the ability damage loop.

### Gnar — Mega form stats wrong: wiki stat box stale vs game files
- **What happened:** Mega Q/W were ~2 too high and R was 318 instead of 300 (level 18, no items, 100 armor). The Mega AD delta was implemented as 6 + 2.5/lvl (→48.5 @18) from the wiki's "6 − 48.5" range; the real game files (Community Dragon `gnarbig.bin.json` vs `gnar.bin.json` CharacterRecords) give 66/5.5 vs 60/3.2 → 6 + 2.3/lvl (→45.1 @18). Armor/MR deltas were also slightly off.
- **Root cause:** The wiki's Mega Gnar stat box is hand-maintained prose and was stale (claimed 5.7 AD growth; the game has 5.5). ddragon is no help — it lists Gnar's AD growth as 0 (handled by the transform script).
- **Pattern to watch for:** Transform/multi-form champions (Gnar, Nidalee, Jayce, Elise, Shyvana...) — verify form stat deltas against Community Dragon game files (`<unit>.bin.json` CharacterRecords/Root), never the wiki stat box alone. An in-game practice-tool measurement of two AD-scaling abilities pins total AD exactly.

### Gnar — form stat grant misclassified as bonus AD
- **What happened:** R (75% **bonus** AD ratio) scaled off Mega's +45.1 AD; in-game an itemless Mega Gnar has 0 bonus AD and R deals its flat base.
- **Root cause:** Mega Gnar's AD increase is a BASE-stat increase (it's GnarBig's own base AD block), but the module emitted it as `bonus_attack_damage`. Base vs bonus also matters for Sheen-type base-AD item scalings.
- **Pattern to watch for:** When a form/steroid grants AD, determine base vs bonus explicitly. Form swaps that are separate in-game units grant BASE stats; ability steroids (Vayne R, Aatrox R) grant BONUS AD. The fight engine supports both keys (`base_attack_damage` / `bonus_attack_damage`) and re-resolves total AD for either.

### Gnar — UI stats panel ignored the form toggle
- **What happened:** Selecting Mega Gnar changed damage numbers but the champion stats panel kept showing Mini stats (HP 1883/AD 114 instead of 2714/159).
- **Root cause:** `run_fight` reported the pre-buff base+items stats dict; the fight engine applied `stat_buff` entries to its own copy, which was discarded. Fixed in `pipeline.py`: the reported `champion_stats` is now the fight engine's post-buff copy ("fight-effective stats") — this also made Vayne/Aatrox R steroids visible in the panel.
- **Pattern to watch for:** After implementing any stat-buff champion, verify `run_fight()["champion_stats"]` reflects the buff — the parse-context mutation alone only feeds ability ratios, not the display.

### Gnar — Sterak's Gage didn't grow with Mega's base AD
- **What happened:** Sterak's (45% base AD → bonus AD) gave ~55 bonus AD on Mega Gnar at level 20 instead of ~78.
- **Root cause:** Sterak's is computed at build-stats time from pre-buff base AD; the Mega base-AD grant lands later (BUFF phase / fight engine). Fixed: `_apply_stat_buff_ultimates` now recomputes base-AD-derived item stats (via the `item_effects.steraks_bonus_ad` accessor — linear, so the delta composes) when a `base_attack_damage` stat_buff lands.
- **Pattern to watch for:** When a champion grants BASE stats via `stat_buff`, check every item that converts a base stat (Sterak's: base AD; Overlord's Bloodmail: bonus health — correctly unaffected by base-HP grants). The recompute hook lives in `_apply_stat_buff_ultimates`; extend it there, numbers stay in `item_effects`.

### Azir — proc-style item effects exempted from soldier 50% on-hit reduction
- **What happened:** Sand Soldier autos halved per-hit on-hit damage (Nashor's, BoRK) but left proc-style systems (spellblade, Energized, Kraken Slayer) at full value, based on wiki notes claiming Energized "stacks but is not consumed."
- **Root cause:** The wiki's notes section was stale. In-game (per user): spellblade/Lich Bane procs on soldier attacks at 50% damage; Energized IS consumed at 50% damage; Kraken procs every 3rd soldier attack at 50% damage. Sundered Sky is the only real exception — it does not apply at all.
- **Pattern to watch for:** Attack-replacement / on-hit-effectiveness mechanics (Azir W, and any "on-hit at X% effectiveness" ability) — apply the reduction to ALL per-attack and proc-style item effects uniformly unless a specific exclusion is verified in-game. The wiki's item-interaction notes are less reliable than its numbers; treat them as hypotheses, not ground truth.

### Bard — meep stock/recharge tier tables fabricated by summarized wiki fetch
- **What happened:** With 10 chimes and a 7s fight, only 1 auto was meep-empowered instead of 2. The module's stock table said 1–5 meeps at 5/15/25/35/50 chimes; the real game has 1–9 meeps at 0/10/30/50/65/80/90/95/100, and the recharge table (8→4s at 0/20/40/55/70) was also wrong.
- **Root cause:** The analysis WebFetch of the rendered champion page returned a plausible-looking condensed "progression table" that merged/invented breakpoints. The wiki stores these as `{{pp|...}}` hover-tooltip templates that a summarizing fetch garbles easily. The damage formula (plain text) survived; both breakpoint tables did not.
- **Pattern to watch for:** Any "based on number of Chimes/stacks/Souls" progression — do NOT trust a summarized fetch of the rendered page. Fetch the raw data template (`https://wiki.leagueoflegends.com/en-us/Template:Data_<Champion>/<Ability>?action=raw`) and read the `{{pp|values|breakpoints}}` calls verbatim. Cross-check any table the user can screenshot from a tooltip.

### Bel'Veth — ability-applied item on-hits documented away instead of modeled
- **What happened:** Q ("applies on-hit at 75%") and E (8–32%) were implemented without applying ITEM on-hit effects — the gap was listed as an assumption. On an on-hit champion whose every real build is Kraken/BotRK/Wit's End, this understated her fight total by 16% (3922 vs 4550).
- **Root cause:** The engine only applied item on-hits on the auto stream; the analysis treated "ability applies on-hit effects" as an ability-tuning detail rather than a cross-system item interaction, and the implementer documented the limitation instead of extending the engine (`applies_item_on_hits`).
- **Pattern to watch for:** Any ability wiki-tagged "applies on-hit effects" on a champion whose builds are on-hit items — item on-hit application is a large damage fraction and MUST be modeled, never assumption-listed. For marksman/on-hit champions, treat a "not modeled" item interaction as a blocker.

### Bel'Veth — ability on-hit applications didn't feed shared proc counters
- **What happened:** Q/E applied per-hit on-hit damage but never advanced Kraken Slayer's every-3rd counter (or Hullbreaker's every-5th), and couldn't consume the 3rd stack. In-game (per user), one Q dash adds one Kraken stack, each E slash adds one, and either can trigger the proc.
- **Root cause:** The engine kept counter-based procs on a separate auto-only timeline; ability applications were bolted on as damage-only. Counter procs are position-dependent — they need ONE shared hit sequence across autos + ability applications, with each proc firing at the effectiveness of the hit that landed the Nth stack.
- **Pattern to watch for:** When an ability applies on-hit effects, counter-gated items (Kraken, Hullbreaker) must share a single hit sequence with autos — no per-source counters. Proc damage inherits the triggering hit's on-hit effectiveness.

### Bel'Veth — on-attack vs on-hit item taxonomy missing from the engine
- **What happened:** After abilities could apply on-hits, the engine used a blanket "on-attack mechanics never trigger from abilities" rule. Wrong for E: the wiki says slashes apply "on-hit, on-attack, and ability effects" — slashes advance Guinsoo's phantom-hit cadence (a slash-fired phantom re-applies on-hits at the slash's effectiveness); Q, on-hit only, must not.
- **Root cause:** The engine had no per-item trigger classification. The wiki's On-Attacking list is short and closed (Guinsoo's Rageblade, Navori Flickerblade, Rapid Firecannon, Runaan's Hurricane, Voltaic Cyclosword, Yun Tal Wildarrows — triggers on completing an attack windup); everything else per-hit is on-hit. Now lives in `item_effects.ON_ATTACK_TRIGGER_ITEMS` + `counter_trigger()`; ability applications declare `triggers: ("on_hit",)` or `("on_hit","on_attack")`.
- **Pattern to watch for:** Abilities that apply on-hit effects need their trigger scope classified per the wiki notes: on-hit only vs on-hit + on-attack. Spellblade is neither (consumed by next basic attack). Get the interaction list from the wiki's ability notes AND the user — notes sections can be stale (see Azir entry).

### Akshan (latent, found during Bel'Veth work) — E attack-speed scaling silently reads 0
- **What happened:** `akshan.py` reads `stats_context.get("bonus_attack_speed_percent", 0.0)` for E's AS scaling, but no stats path ever populates that key — E's AS component is 0 with every real build. Unfixed as of logging (fix would change his golden numbers; use the `bonus_attack_speed` stat added in the Bel'Veth work).
- **Root cause:** A `.get` with a silent 0.0 fallback on a never-populated key — the rule-5 failure mode (silent stale fallback) applied to stats instead of items.
- **Pattern to watch for:** Champion modules must not `.get(..., default)` stats keys speculatively; a missing stats key should raise or come from a verified single home (`stats.py`). Audit any module reading a stats key no producer writes.

### General — proc breakdown rows had a second schema the UI silently dropped
- **What happened:** Kraken/spellblade/energized proc rows showed damage but an empty detail cell in the web UI ("no kraken procs" report on Bel'Veth one-rotation). Pre-existing for every champion.
- **Root cause:** Two row spellings for one concept: `procs`/`damage_per_proc` vs `count`/`damage_per_hit`/`unit` — app.py's API row builder and app.js only understood the latter, silently dropping the former's fields. (app.py also dropped `unit`, so even correct rows read "N hits" instead of "N procs".)
- **Pattern to watch for:** New breakdown rows MUST use the unified shape: `count` / `damage_per_hit` / `unit` (+ optional engine-minted `detail`). Never invent new row field names — app.py's whitelist row builder silently drops unknown keys; verify a new row type end-to-end through `POST /api/calculate`, not just the pipeline dict. Also: the web server (`run_web.bat`) runs Flask without auto-reload — restart it before judging UI behavior against fresh code.

### Blitzcrank (and latent Vayne) — empowered-auto base swing dropped in one-rotation mode
- **What happened:** One-rotation Power Fist showed 147 (the 100% AD + 25% AP bonus only) vs 268 in-game (122 AD × 2 + 25). The consumed basic attack's damage appeared nowhere in the total — one-rotation mode forces `auto_attack_uptime = 0`, so there is no auto row to carry the swing. Vayne Q had the identical hole since its implementation.
- **Root cause:** `empowers_next_auto` modeled the ability as pure bonus riding the auto stream. Correct in time-based mode (casts capped by autos; the stream carries the swing), but in one-rotation the ability still casts once with zero autos, silently dropping a full attack's damage.
- **Pattern to watch for:** Any `empowers_next_auto` ability ("next basic attack deals...") — in a mode with no auto stream, the cast still forces its basic attack. The engine now appends the base swing (full expected-crit, physical) to the ability's own row when `num_auto_attacks == 0` (`damage.py::_compute_ability_rotation`); new empowered-auto champions get this for free, but verify the one-rotation row equals the in-game "attack + bonus" tooltip number.

### Amumu — Q damage doubled by fight engine
- **What happened:** Q showed ~265 damage instead of ~110 for a single cast with Liandry's at level 18 against 100 MR.
- **Root cause:** Two compounding issues: (1) Q result had both `damage_per_cast`/`total_casts` AND pre-multiplied `magic_damage`, causing fight engine double-counting. (2) Module pre-baked `q_casts=2` into `magic_damage`, but fight engine already determines cast count from cooldown. In one-rotation mode the engine casts once, but `magic_damage` already had 2 casts of damage.
- **Pattern to watch for:** Charge abilities (2+ charges) should report **single-cast damage** and use `rechargeRate` (not the inter-cast CD) as `cooldown`. Let the fight engine determine cast count. Never pre-multiply cast count into `magic_damage`/`physical_damage` — the fight engine handles repetition via `num_casts`. The `damage_per_cast`/`total_casts` pattern is only for sub-casts within a single ability use (e.g., Ahri R's 3 dashes per activation).
