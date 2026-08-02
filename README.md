# League Combat Calculator

A source-backed League of Legends combat and build calculator. Start from an empty canvas, choose the champion being optimized, reconstruct both teams, select the exact damage package, and compare or optimize builds against the selected enemy roster.

This net-new repository keeps the battle-tested engine and interface direction from [Skyway1111/lol-calculator](https://github.com/Skyway1111/lol-calculator) and merges in Scryglass's roster builder, full stat matrices, build comparison, BIS workflow, and provenance-first product rules.

## Features

- **Empty, general scenario builder** — No hardcoded champion or matchup; add up to four allies and five enemies
- **Full stat matrices** — Level- and item-derived base HP, bonus HP, total HP, defenses, offense, haste, speed, and penetration for every selected champion
- **Champion stats** — Per-level stat calculations using the official growth formula
- **Item builds** — Reconstruct components, starters, completed items, boots, and item-specific inputs such as Dark Seal or Mejai's stacks
- **Ability damage** — Calculates Q/W/E/R damage at any rank with AP/AD/bonus scaling
- **Fight simulation** — One rotation or a timed window with cooldowns, auto-attack uptime, active items, falling health, burns, and skill-by-skill attribution
- **Roster-aware build optimizer** — Score legal candidate builds into every selected enemy and maximize summed post-mitigation total, physical, or magic damage
- **Role quests** — Current mid quest AP/bonus-AD and tier-3 boots rules plus the bottom quest's extra inventory slot
- **Allies** — Include allied champions and builds as sourced scenario context; ally buffs are counted only after an explicit tested rule exists
- **Per-target output** — See each enemy's HP/armor/MR and damage received alongside aggregate TDD
- **Item effects** — Supports on-hit (Nashor's, BotRK), spellblade (Lich Bane), burn (Liandry's), and more
- **Auto-updating data** — Fetches champion and item data from the LoL Wiki for the latest patch

Only champions with a dedicated module are labeled verified attackers. Every champion can still be used as an ally or target because their level and item stats are derived independently. Unsupported attacker kits fail closed in the public UI instead of presenting generic parsing as exact.

## Setup

Requires Python 3.10+.

```bash
# Clone the repo
git clone https://github.com/koimari/league-combat-calculator.git
cd league-combat-calculator

# Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt

# Run the app
python -m flask --app src.app run
```

Then open http://localhost:5000 in your browser.

The repository includes a tracked data cache. In local development, **Update to latest patch** refreshes that cache through the existing updater.

## Running Tests

```bash
python -m pytest
pylint src/
python scripts/golden_snapshot.py compare scripts/golden_baseline.json
```

## Credits

- **[lolstaticdata](https://github.com/meraki-analytics/lolstaticdata)** by Meraki Analytics — Champion and item data scraping library. This project vendors a copy of their code (`vendor/lolstaticdata/`) to pull accurate ability data from the wiki.
- **[League of Legends Wiki](https://wiki.leagueoflegends.com)** — The source of truth for champion ability values, item effects, and game formulas.
- **[Skyway1111/lol-calculator](https://github.com/Skyway1111/lol-calculator)** — Original calculator engine, champion-module architecture, test suite, and interface foundation retained in this repository's Git history.
- **Scryglass** — Roster-first scenario design, stat-card presentation, comparison/BIS requirements, ally context, and source/provenance constraints.

## Tech Stack

- **Backend:** Python / Flask
- **Frontend:** Vanilla HTML, CSS, JavaScript
- **Data:** Scraped from the League of Legends Wiki via [lolstaticdata](https://github.com/meraki-analytics/lolstaticdata)
- **Tests:** pytest plus a full-pipeline numeric golden snapshot
