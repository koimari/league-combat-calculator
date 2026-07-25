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

### Caitlyn (and latent Vayne/Blitzcrank) — forced empowered attacks vanished in timed fights with autos off
- **What happened:** Time-based fight with "Include Auto Attacks" unchecked showed no Headshot row at all (Caitlyn), and Vayne Q / Blitzcrank E rows went to 0 casts — a much lower total than one-rotation mode for the same combo.
- **Root cause:** Two homes for one rule. The engine clamped `empowers_next_auto` casts to `num_auto_attacks` (0 with autos off) so the one-rotation swing append never fired; Caitlyn's `_headshot_counts` capped every granted headshot at the auto count the same way. But an empowered/granted attack is FORCED by the cast — zero auto uptime means "no sustained autoing," not "the champion never swings."
- **Pattern to watch for:** Any granted/forced basic attack (empowers_next_auto, Caitlyn trap/E headshots): with NO auto stream (one-rotation OR timed with zero uptime), casts run on cooldown and each carries the expected-crit base swing on the ability's own row. Only cap conversions by the auto count when autos exist to host them.

### Caitlyn / General — Hexoptics C44 showed 0 with forced swings ("basic damage" amp only lived on the auto stream)
- **What happened:** One-rotation Caitlyn with Hexoptics C44 showed the amp row at 0 damage even though her forced headshot attacks are basic attacks (and Headshot's rider is classified basic damage in-game).
- **Root cause:** `basic_amp` was applied only inside `_simulate_auto_attacks`; ability-row DamageParts had no way to declare themselves basic damage, and the info row's bonus was computed from auto totals alone.
- **Pattern to watch for:** Ability rows that carry basic-attack swings or basic-classified damage must set `DamagePart(basic_damage=True)` — both pricers (`_evaluate_cast_parts`, `_add_precomputed_proc_damage`) apply `state.basic_amp` to flagged parts and accumulate `state.basic_amp_ability_bonus` for the info row. When implementing a champion whose ability damage is wiki-classified "basic damage" (Headshot-style), flag those parts; spell-classified rows stay unflagged. The flag prints in repr only when set, keeping golden reprs of unflagged parts stable.

### Cassiopeia — summarized wiki fetch invented a mechanic ("cannot buy boots"), caught pre-implementation
- **What happened:** The analysis WebFetch of the champion page reported Serpentine Grace as "No boots purchasable (replaced by movement speed scaling)." The actual page says only the movement-speed amplification, with "No additional details." The fabricated restriction nearly shipped as a build-scenario assumption; the user caught it from a screenshot of the page.
- **Root cause:** The summarizing fetch model injected prior-game knowledge (Cassiopeia's old real-game boot restriction) that is not present on this reality's wiki. Sibling of the Bard entry — but where Bard's fetch garbled *numbers* in `{{pp}}` templates, this one invented a *rule* that reads as champion lore.
- **Pattern to watch for:** Treat mechanics/rules in a summarized fetch that famously existed in the champion's history (boot bans, old passives, removed mechanics) as prime hallucination bait — they're what the summarizer autocompletes. Any fetched claim that would constrain builds, items, or options must be verifiable in the JSON data or confirmed by the user before it becomes an ASSUMPTIONS entry; numbers cross-check against the champion JSON, rules don't, so rules need explicit confirmation.

### Cassiopeia — DoT abilities shipped without `dot_duration`, undercounting item burns
- **What happened:** One-rotation fights slightly undercounted her damage with burn items (Blackfire Torch, Liandry's): the burn window ended at the last cast instead of stretching through her poison ticks (user report).
- **Root cause:** The engine's burn-refresh tail (`dot_duration`, built for Brand's Blaze — every champion-DoT tick is ability damage that refreshes item burns) must be declared per ability, but the analysis classified Q/W as plain "DoT/tick" totals and never mapped the category to the flag; `simple_damage` also had no way to emit it (now takes a `dot_duration=` param).
- **Pattern to watch for:** ANY ability whose damage keeps ticking after the cast (poisons, ground zones, bleeds, burns) must declare `dot_duration` = its tick tail in seconds, or item burns end early. The DoT/tick category in analysis should always answer: "how long past the cast does this deal ability damage?" and put that number in the spec. Zone DoTs (Miasma-style) should use the same duration the damage assumption uses, so the two stay consistent.

### Cassiopeia / General — timed fights overcounted casts by ignoring cast times (5 E casts in 3s vs ~3 in-game)
- **What happened:** Timed-mode cast counting was `1 + int(fight_duration / cd)` per ability on independent timelines — no cast-time lockout, no cross-ability contention. Cassiopeia's 0.75s-cooldown E showed 5 casts in a 3s fight; in-game she fits ~3 because Q/W/R cast times (0.25/0.25/0.5s) occupy the same timeline and E's own 0.125s cast stretches its cycle to 0.875s.
- **Root cause:** The engine never read the wiki's `castTime` (present in the JSON for every ability, as free text: "0.25", "none", "0.25 • None", "0.25 : 0.1 (based on bonus attack speed)", "80% of X's windup time (0.4 at base attack speed)"). Fixed engine-wide: `slotlib.extract_cast_time` parses the text, the champion engine stamps `cast_time` on every castable entry (one home — no per-module plumbing), and `damage.py::_schedule_shared_casts` schedules all abilities on ONE timeline (cooldown runs from cast END; ties break by cast order; R still casts once). Entries without cast-time data keep legacy counts exactly.
- **Pattern to watch for:** Spam spells (sub-2s cooldowns) live or die by this — sanity-check a new champion's timed cast counts against `duration / (cast_time + cd)` AND expect other abilities' cast times to displace them. Also: a "known-good" pinned total captured under a since-fixed engine model embodies the old bug (Ahri+Bloodsong's 1161 assumed W's boundary cast at exactly t=5.0); when an engine-wide fix moves such a pin, re-derive it and document why, don't widen the tolerance.

### General (found on Cassiopeia) — timed fights capped item burns at fight_duration, ~3x undercount on short fights
- **What happened:** Blackfire Torch's burn in a 3s timed fight showed ~30 damage vs ~90 measured in-game. Timed mode computed `effective_burn_time = min(refresh_end + burn_duration, fight_duration)` — pricing the burn as rate x fight_duration — while one-rotation mode (correctly) let the final application resolve fully.
- **Root cause:** Wrong reading of "fight duration": refresh EVENTS stop with the last cast/DoT tick, but the burn they lit keeps ticking past the fight's end — those are consequences of casts made within the fight and the calculator counts consequences fully everywhere else (one-rotation burns, front-loaded DoT totals). Fixed by deleting the cap; both modes now share `refresh_end + burn_duration`.
- **Pattern to watch for:** Any timed-mode `min(..., fight_duration)` on damage that RESOLVES from an in-fight action (burns, DoT tails, delayed procs) is suspect — cap the triggering events, never the resolution. Also exposed a golden-gate blind spot: the sweep's build scenarios include no burn items, so timed-burn regressions produce ZERO golden diffs — burn-item behavior is only guarded by unit tests (`TestBurnTimedModeUptime`).

### Corki (caught pre-ship) — penetration clamped flat resistance REDUCTION back to zero
- **What happened:** Gatling Gun is the first ability with a FLAT armor/MR shred (3-5 per stack, 12-20 total). Against a low-resist target the shred should take resistances negative, where `raw x 100 / (100 + resist)` amplifies damage. It could not: `resistance.apply_armor_penetration` / `apply_magic_penetration` ended in `max(0.0, effective)`, and `Resists.shred_mr` clamped Malignance's reduction with `max(..., 0)` — every negative resistance was silently floored to 0 on the way to the damage math.
- **Root cause:** The zero floor was written for PENETRATION (lethality vs. low armor is wasted, per CLAUDE.md) and then applied to the whole resolve path, including reduction-driven values. Percent shreds never expose it because scaling a positive number can't cross zero — only flat reduction can, so the bug sat dormant until the first flat-shred champion.
- **Pattern to watch for:** Penetration floors at 0; REDUCTION does not. Any new flat resistance-reduction effect must be traced through every `max(x, 0)` between the debuff and `apply_resistance` — the fix is to floor at `min(0.0, input)` (no floor once already negative) rather than at a hard 0. Also verify percent modifiers (Black Cleaver, Vile Decay) skip already-negative resistances instead of scaling them back toward zero.

### Corki / General — a new auto-stream breakdown row was attributed to ability damage
- **What happened:** Hextech Munitions' true-damage instance rides every basic attack and got its own breakdown row (`auto_attacks_true_damage`). The web UI's auto-vs-ability split counted it as ABILITY damage, quietly moving ~370 damage into the wrong half of the summary while the total stayed right.
- **Root cause:** `damage.py::split_auto_vs_ability` matched the auto stream by EXACT key (`key == "auto_attacks"`) with an explicit special case for the one existing sibling (`fiendhunter_true_damage`); anything not named exactly right fell into the `else` = ability bucket. A wrong bucket is invisible in the total, so no test catches it by accident.
- **Pattern to watch for:** Any new row that rides the auto stream (champion riders, extra true/magic instances on basic attacks) must be named with the `auto_attacks` / `on_hit_` / `spellblade_` prefixes the split understands, and the split's prefix set checked. When adding a row type, assert its bucket in `auto_attack_damage` vs `ability_damage`, not just its `total_damage`.

### Corki — a charge ULTIMATE cannot get its cast count from the fight engine
- **What happened:** Missile Barrage fires up to 4 stored missiles plus whatever recharges mid-fight, with every 3rd a double-damage Big One. The Amumu rule ("report single-cast damage, use `rechargeRate` as the cooldown, let the engine count casts") cannot deliver that: `_schedule_shared_casts` puts every `R` in `single_cast`, so an ultimate is cast exactly once in EVERY mode regardless of its cooldown. Following the rule literally would have shown one missile per fight and no Big One at all.
- **Root cause:** The Amumu rule was written for a charge BASIC ability, where the engine's timed scheduler really does repeat the cast. Ultimates are exempt from recasting by design.
- **Pattern to watch for:** For a charge/ammo ULTIMATE, the module owns the cast count: keep per-missile damage single-cast on the `DamagePart.amount` and put the count on `DamagePart.count` (never multiplied into the amount — that is still the Amumu trap), set `cooldown` to `rechargeRate` so nothing downstream re-derives a rate from the inter-cast timer, and set `cast_instances` so per-cast item procs (Muramana) count each shot. An exact every-Nth cadence must be computed over the resulting count, never approximated as an average uplift.

### Corki / General (caught in review) — percent shred on NEGATIVE resistance made a shred item protect the target
- **What happened:** Once Corki's E could drive MR below zero, Bloodletter's Curse inverted: each Vile Decay stack made the target take LESS damage (100 raw magic → 106.54 / 106.17 / 105.80 / 105.43 at 0-3 stacks). Percent reduction is `mr * (1 - pct)`, and multiplying a NEGATIVE number by `(1 - pct)` moves it toward zero — i.e. gives resistance back. The guard that was there, `max(reduced, min(0.0, base))`, protected the wrong direction: it stopped the value going below `base` when the real failure was it rising above it.
- **Root cause:** The "percent reduction must not touch already-negative resistance" rule was written into a new shared helper, but two older sites (`_ability_mr`, and the post-rotation Vile Decay tail) kept open-coding the multiply. A rule with a home plus two copies that predate it is a rule that only half-applies.
- **Pattern to watch for:** Making negative resistance REACHABLE is a cross-cutting change, not a local one — it retroactively changes the meaning of every percent-reduction and every `max(x, 0)` in the engine. After adding any effect that can cross zero, grep the whole module for `* (1 -` and `max(..., 0)` on a resistance and route them all through the shared helper. Regression-test the monotonicity property directly ("more shred stacks must never deal less damage"), not just the individual numbers.

### General (caught on Corki) — target_debuff applied even when the ability was never cast
- **What happened:** In `auto_only` fight mode (a live UI checkbox) an ability with 0 casts still applied its full resistance shred, so autos got a free reduction from a spell never used. Pre-existing for Kog'Maw Q / Briar Q / Jarvan IV Q; Corki's E sharpened it into a flat shred that can drive resistances negative.
- **Root cause:** The `target_debuff` block in `_compute_ability_rotation` sat outside any `num_casts > 0` guard, unlike the `applies_item_on_hits` block 40 lines above it that does check. Zero-cast modes were simply never considered when the debuff hook was written.
- **Pattern to watch for:** Every per-ability side effect in the rotation loop (shreds, stat applications, stack seeding) must be gated on the ability actually having been cast — `auto_attacks_only` and zero-uptime timed fights both produce `num_casts == 0` while the entry is still present in `ability_damages`. When adding a side effect, test it in autos-only mode, which no golden scenario covers.

### Darius — a stack-count option let the user request a state the game cannot reach
- **What happened:** `hemorrhage_stacks_override=5` made R hit for 5 Hemorrhage stacks while Noxian Might stayed OFF, so Q/W/R/autos all priced at up to 280 bonus AD too little (roughly half his real output at level 20). Reported from in-game testing: the only way to put 5 stacks on a target is to apply them, and applying the 5th IS what grants Might.
- **Root cause:** Two inputs for one game state. The option was scoped to R's own stack read (`dot_stack_scaled=False` + a pinned `count`) and never touched the `StackTimeline`, which independently decided the buff windows and the bleed rate. The timeline was correctly built as the single home for "when does a stack land" — and then a champion option was allowed to out-vote it for one consumer.
- **Fix:** The option became `starting_hemorrhage_stacks` (default 5), which seeds `stacking_dot["starting_stacks"]` on the timeline; the buff window opens at t=0 when the seed already meets `trigger_stacks`, and R always keeps `dot_stack_scaled=True` so it can only ever read the derived count.
- **Pattern to watch for:** When a mechanic couples a target-side counter to a champion-side steroid (stacks that grant a buff at N), the calculator must take ONE input describing the state and derive both — never expose a per-ability override of a value another system also derives. Test for the invariant, not the number: assert the ability defers to the timeline at *every* option value. Generally, an "override" option is a smell whenever the overridden value has downstream consequences the override doesn't reproduce.

### Dr. Mundo — W's cached "Total Magic Damage" is a stale 16-tick total
- **What happened:** W's charge reads 80/140/200/260/320 in the champion JSON, which is per-tick x **16** ticks. W's duration has been **3 seconds since V12.23** (down from 4), so the charge is per-tick x **12** — 60/105/150/195/240. Taking the JSON attribute at face value overstates W's charge by a third (540 instead of 460 on a +2000 HP build at rank 5).
- **Root cause:** The wiki itself, not our cache and not our parser. A live single-champion pull (`LolWikiDataHandler(use_cache=False, target_champion="DrMundo")`) returns `Magic Damage per Tick` = [5, 8.75, 12.5, 16.25, 20] **and** `Total Magic Damage` = [80, 140, 200, 260, 320] in the same breath — a total the template carries as a hand-maintained derived field rather than computing from the duration, left behind when V12.23 shortened the ability. Every input array moved; only the derived total did not. Confirmed wrong by three independent sources: the wiki's own rendered page (3s duration / 0.25s per tick = 12); `drmundo.bin.json` `Duration` = 3.0; and the game's own formula `4 (ticks/sec) x DamagePerTick x Duration`.
- **Why it hid:** the rendered ability box does not display the Total row at all — it shows only "Magic Damage per Tick" and the recast's "Magic Damage". Reading the wiki page as a human shows nothing wrong; the stale number is visible only to the scraper. **Re-pulling the data does not fix it and never will** — do not chase this as a cache-staleness bug on patch day.
- **Pattern to watch for:** A "Total X Damage" attribute on a DoT or channel is **derived data the wiki computes by hand**, and a duration change silently invalidates it while every input array stays right. Whenever a duration-based ability offers both a per-tick and a total attribute, compute the total yourself from `duration x ticks_per_second x per_tick` and only use the cached total if it agrees — if it does not, the per-tick value wins. Check the ability's patch history for a duration change; the mismatch is almost always a stale derived field, not a stale per-tick one. Same family as the Gnar Mega stat box: hand-maintained wiki prose beside correctly-scraped arrays.

### Dr. Mundo — E's max-damage threshold (70% missing health) exists only in the game files
- **What happened:** E's bonus damage scales "0% - 40% (based on missing health)" per the wiki ability page, which reads as a linear ramp reaching +40% at 100% missing health. It actually reaches its maximum at **70%** missing health and plateaus there, so every damage figure between 70% and 100% missing was correct only by accident and everything below it was understated (at 30% missing: amp 1.171 vs the wiki-implied 1.12).
- **Root cause:** The threshold is simply not published on the wiki ability page — no attribute, no note. It lives in `drmundo.bin.json` as `MaxMissingHealthThreshold` = 0.7 with `MaxDamageAmp` = 1.4, and patch **V25.23** confirms it in prose ("Maximum bonus damage now correctly applies at 70% missing health") without the ability page ever being updated to match.
- **Pattern to watch for:** When a wiki ability says a value scales "X% - Y% (based on <resource>)" without naming the point where Y is reached, do **not** assume 100%. Pull the game file and look for a `Max...Threshold` key beside the `Max...Amp`; then grep the patch history for that threshold, since a "now correctly applies at" note is the usual fingerprint of a threshold the ability page never documented. The wiki's own "Maximum ..." leveling row is a useful cross-check: it should equal `minimum x max_amp` exactly, which also proves the amp multiplies the WHOLE expression (flat + ratio terms) rather than the flat part alone — and proves that row is the same damage, never a second source to add.

### General (found on Dr. Mundo) — an empowered auto's swing was invisible in timed fights
- **What happened:** Mundo E showed 116 for 2 casts while the auto row showed 6 hits. In-game an E cast produces ONE hit worth `attack + bonus` (~250), so a player casting E and reading the calculator saw less than half the number the game showed them. The same ability read as attack+bonus in one-rotation mode (239) and bonus-only in a timed fight (52.7) — two meanings for one row, differing by exactly one auto's damage.
- **Root cause:** `empowers_next_auto` was modeled as pure bonus riding the auto stream. `_compute_ability_rotation` appends the consumed swing to the ability row only when `num_auto_attacks == 0` (the Blitzcrank/Caitlyn fixes); with a stream, the swing stayed in the auto row and nothing told the reader which autos were empowered. Fixed engine-wide in `damage.py::_reattribute_empowered_swings`, which runs after `_apply_damage_amplifiers` and moves `casts x hits x auto_damage_per_hit` onto the ability row. Damage moves BETWEEN rows only — fight totals are untouched (verified: 120 golden diffs, all under `breakdown_totals/`, zero `total_damage` changes).
- **Semantic change to know about:** `breakdown["auto_attacks"]["count"]` now means **plain (non-empowered) attacks**, not total attacks. Anything needing the fight's true attack count must add back the empowering abilities' `casts x hits` — this immediately bit a Briar test that derived bleed applications from the auto row (the bleed row's 19 was right; the test's `13 + 4` was not). On-hit / proc / stacking-DoT rows are deliberately NOT re-attributed: the empowered attack really does trigger them, so they keep counting every attack.
- **Pattern to watch for:** When a champion's ability consumes or empowers a basic attack, the breakdown must show the swing on the ability's row in EVERY fight mode — a row whose meaning depends on whether autos are enabled is a usability bug even when the total is right. Cross-check a new empowered-auto champion by running one-rotation and timed-with-autos and asserting the ability row reports the same per-cast damage in both. Also note the degenerate case: when every attack is empowered (Vayne tumbling, Cho'Gath E's 3 swings on a short fight) the auto row legitimately drops to 0 hits.
