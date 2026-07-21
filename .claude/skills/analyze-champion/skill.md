---
name: analyze-champion
description: Analyze a LoL champion's wiki page and ask the user targeted questions about assumptions before generating a /add-champion prompt. Use this BEFORE implementing a champion to catch edge cases upfront.
user-invocable: true
disable-model-invocation: true
---

# Champion Analyst

You are a champion analyst preparing a champion for implementation in the LoL damage calculator. Your job is to **read the wiki**, **identify every edge case**, **ask the user targeted questions**, and **output a complete `/add-champion` prompt** with all decisions baked in.

## Input

The user provides a champion name:

$ARGUMENTS

## Process

### Step 1: Fetch the Wiki Page

Fetch the champion's wiki page at: `https://wiki.leagueoflegends.com/en-us/<ChampionName>`

Extract for each ability (P, Q, W, E, R):
- Name
- Damage type (physical / magic / true / mixed)
- Base damage values and scaling ratios
- Cooldown
- Any conditional mechanics

### Step 2: Inspect the Champion JSON

Run this to see what the parser actually has access to:

```python
import json
from src.calculator.data_fetcher import get_champion
champion_data = get_champion("ChampionName")
for slot in ['P', 'Q', 'W', 'E', 'R']:
    for k, ab in enumerate(champion_data['abilities'][slot]):
        print(f'=== {slot}[{k}]: {ab["name"]} ===')
        print(f'damageType: {ab.get("damageType")}  targeting: {ab.get("targeting")}')
        for i, effect in enumerate(ab.get('effects', [])):
            for j, lev in enumerate(effect.get('leveling', [])):
                attr = lev.get('attribute', '')
                mods = [{'values': m['values'][:5], 'units': m['units'][:5]}
                        for m in lev.get('modifiers', [])]
                print(f'  effect[{i}].leveling[{j}]: attr="{attr}" mods={mods}')
```

Iterate **every** entry in each slot's list — recasts and subspells live in
the extra entries (Ambessa Q2 is `Q[1]`; reading only `[0]` is how its %HP
component was missed).

Cross-reference the wiki page with the JSON to identify any discrepancies.

### Step 3: Classify Every Ability

For **each** ability (P, Q, W, E, R), classify it into one of these categories:

| Category | Description | Example |
|---|---|---|
| **Simple** | Base + ratio, single hit | Annie Q |
| **Skip** | Utility/healing/shield only, no damage to enemies | Alistar Passive (heal), Akshan W |
| **Multi-hit** | Hits multiple times, need to decide total vs per-hit | Alistar E (10 ticks + empowered auto) |
| **Multi-cast** | Multiple casts with same damage | Ahri R (3 dashes) |
| **Multi-cast-varied** | Multiple casts with different damage per cast | Aatrox Q (3 casts, each different) |
| **Recast** | A second cast of the same ability with different damage | Ambessa Q1 → Q2 |
| **Conditional** | Damage depends on game state (sweetspot, stacks, missing HP) | Aatrox Q sweetspot, Darius R bleed stacks |
| **Stat-buff** | Grants stats instead of/in addition to dealing damage | Aatrox R (bonus AD), Ambessa R (armor pen) |
| **Pet/summon** | Summons an entity with its own damage pattern | Annie R (Tibbers + aura) |
| **Empowered-auto** | Empowers next auto attack(s) | Alistar E (bonus damage on next auto), Aatrox P |
| **DoT/tick** | Damage over time, need to decide duration | Darius passive bleed, Alistar E ticks |
| **Retaliation** | Damages enemies that attack you (shield damage) | Annie E |
| **Unusual-scaling** | Non-standard scaling (crit, AS, stacks, etc.) | Akshan R (crit at 30% effectiveness), Garen E (AS/crit) |

An ability can belong to multiple categories.

### Step 4: Identify Red Flags

Check for these **specific pitfalls** that have caused bugs in past implementations. For each one found, you MUST flag it:

1. **Pet/summon secondary damage**: Tibbers aura, Daisy, Heimer turrets — the summon's ongoing DPS is usually NOT modeled. Flag it and ask.

2. **Retaliation/shield damage**: Annie E, Rammus W — enemies take damage for hitting you. Usually NOT modeled. Flag it and ask.

3. **Stat-granting abilities not applied before damage calc**: If R grants bonus AD/AP/armor pen, it must be a BUFF-phase slot (the `stat_buff` archetype with `apply_to=` for parse-time scaling stats) so the engine guarantees damage slots see buffed stats. Past bug (pre-engine): Ambessa R armor pen wasn't applied before Q/W/E damage. Note: fight-engine-applied stats like armor pen take no `apply_to`.

4. **Empowered auto applied every auto instead of once**: Alistar E's empowered auto only applies ONCE per cast, not on every auto. If an ability says "next basic attack," it's once. Flag and clarify frequency.

5. **Passive with cooldown treated as always-available**: Aatrox passive has a cooldown. It should NOT apply on every auto. Ask how many procs to assume.

6. **Recast abilities missing the recast**: Ambessa Q has Q1 and Q2. If Q2 always follows Q1, both should be calculated. Past bug: Q2 casts weren't matched to Q1 casts.

7. **% max HP damage component missed**: Ambessa Q2 has %HP damage that was initially missed. Check every ability's description for "%HP", "% maximum health", "% current health", "% missing health".

8. **Missing HP scaling on R**: Akali R2, Akshan R — damage scales with target's missing health. Need to decide: assume full HP target? 50% HP? Configurable?

9. **Unusual crit scaling**: Some abilities scale with crit chance/damage at reduced effectiveness (Akshan R at 30%). The wiki value might be misread. Verify the exact formula.

10. **DoT assumed wrong duration**: Alistar E ticks every 0.5s for 5s = 10 ticks. Always calculate: `total_ticks = duration / tick_interval`. Don't assume the tick count.

11. **Stacking mechanics that grant stats**: Darius passive at 5 stacks grants 30-280 AD. When do we assume this is active? It drastically changes all damage numbers. Must ask.

12. **Abilities with both passive and active components**: Ambessa R has passive (armor pen) + active (damage). Both need handling. The passive stat should always be active if ranked.

13. **Transform/form-swap champions** (Gnar, Nidalee, Jayce, Elise, Shyvana...): four coupled traps, all hit on Gnar —
    - The alternate form's stat grants often parse as empty JSON. Source them from the **Community Dragon game files** (`<unit>.bin.json` CharacterRecords/Root, e.g. `gnarbig`), NOT the wiki stat box (it was stale for Gnar: 5.7 vs real 5.5 AD growth) and not ddragon (lists Gnar's AD growth as 0).
    - Classify the grant **base vs bonus**: a form that is a separate in-game unit grants BASE stats (bonus-AD ratios like Gnar R must see 0 without items); ability steroids (Vayne/Aatrox R) grant BONUS AD.
    - Base-stat grants interact with base-stat-converting items (Sterak's) — the `_apply_stat_buff_ultimates` hook handles it, but verify with the item equipped.
    - Verify the UI stats panel (`run_fight()["champion_stats"]`) reflects the form toggle, not just the damage rows.

### Step 5: Present Findings and Ask the User

First, present your ability analysis as a text summary. For each ability show:
```
**[Key]: [Name]** — [Category]
[1-line description of what it does]
[Any red flags found, with specific numbers from wiki]
```

Then use the **AskUserQuestion** tool to ask decision questions as interactive pop-ups. You can ask up to 4 questions per AskUserQuestion call, so batch related decisions together. Make multiple AskUserQuestion calls if you have more than 4 questions.

**Guidelines for AskUserQuestion:**
- Each question should cover one decision point for an ability
- Put your recommended answer as the first option with "(Recommended)" in the label
- Use clear, short headers like "Passive", "Q mechanic", "R scaling"
- Use `multiSelect: false` for yes/no or either/or decisions
- Group questions logically: handle skips/includes first, then mechanic details, then champion options

**Example questions:**
- "Annie E deals 25 (+40% AP) to enemies that hit the shielded target. Should we model this?" → Options: "Skip (Recommended)" / "Include"
- "Aatrox passive has a cooldown. How should we handle it?" → Options: "Configurable proc count (Recommended)" / "Assume always available" / "Skip entirely"
- "Darius gains 30-280 AD at 5 bleed stacks. When should we assume this is active?" → Options: "Always active (Recommended)" / "Champion option toggle" / "Never active"

### Step 6: Launch Implementation Agent

After the user answers all questions, do NOT paste the `/add-champion` prompt as text. Instead:

1. Build the complete `/add-champion` prompt internally with all the user's decisions baked in (format below).
2. Use the **Agent** tool to launch an implementation agent that will execute the skill.

**Agent call format:**
```
Agent tool:
  description: "Implement <ChampionName> champion"
  prompt: |
    You are implementing a new champion for the LoL damage calculator.
    Use the /add-champion skill with the following specification:

    /add-champion <ChampionName>
    Passive: [detailed description with explicit numbers, or "Skip - [reason]"]
    Q: [detailed description with explicit numbers, attribute names from JSON, assumptions]
    W: [detailed description with explicit numbers, or "Skip - [reason]"]
    E: [detailed description with explicit numbers]
    R: [detailed description with explicit numbers]

    Champion Options:
    - [option name]: [type] — [description and default value]

    Assumptions:
    - [each assumption as a bullet, to be shown in the UI]

    Known JSON quirks:
    - [any discrepancies between wiki and JSON data found in Step 2]
```

**Critical rules for the prompt you pass to the agent:**
- Say which triage tier you expect (generic path / archetype slot map / custom slot fns) — most champions should need NO module at all; verify the generic path first
- Include the exact JSON `attribute` names for each damage value (e.g., "use `Total Physical Damage` attribute, not `Physical Damage`")
- Specify damage types explicitly
- For stat buffs: specify a BUFF-phase `stat_buff` slot (with `apply_to=` when the stat scales other abilities at parse time)
- Champion options become the module's `OPTIONS` declarations (key/type/default/label/min/max) and assumptions become `ASSUMPTIONS` — no JS work
- For skipped abilities: explain WHY so the implementer doesn't add them
- For multi-hit: specify exact hit count or formula
- For conditionals: specify the default assumption AND the champion option toggle
- Include expected damage ranges at a reference level (e.g., "at rank 3 with 100 AD, Q should do ~X damage") if you can calculate them from the wiki values — this helps the implementer verify correctness

## Reference: Past Issues by Champion

These are real bugs from past implementations. Use them to calibrate your analysis. **Also check `.claude/skills/analyze-champion/bug-history.md`** for additional bugs logged after implementation — that file is the living record and may have entries not yet in this table.

| Champion | Issue | Root Cause |
|---|---|---|
| Aatrox | R showed damage in breakdown | R is stat-buff only, should be `total_raw: 0.0` |
| Aatrox | Passive applied every auto | Passive has cooldown, should be configurable proc count |
| Akshan | R damage overestimated | Crit/crit-damage scaling at 30% effectiveness misunderstood |
| Alistar | E empowered auto every attack | Empowered auto is once per cast, not per auto |
| Ambessa | R stats not applied before calc | Armor pen from R passive must go into stats_context first |
| Ambessa | Q missed %HP damage | Q2 has % max HP component in addition to flat+ratio |
| Ambessa | Q2 casts didn't match Q1 | Recast should always have same cast count as original |
