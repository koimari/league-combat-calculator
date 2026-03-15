# LoL Damage Calculator

A web-based League of Legends damage calculator that lets you select a champion, equip items, configure fight parameters, and see exactly how much damage you'll deal to a target.

## Features

- **Champion stats** — Accurate per-level stat calculations using the official growth formula
- **Item builds** — Equip up to 6 items + boots with correct stat stacking and passive effects
- **Ability damage** — Calculates Q/W/E/R damage at any rank with AP/AD/bonus scaling
- **Fight simulation** — Set a fight duration and see total damage accounting for ability cooldowns and auto-attack uptime
- **Target configuration** — Set enemy health, armor, and magic resistance to see post-mitigation damage
- **Item effects** — Supports on-hit (Nashor's, BotRK), spellblade (Lich Bane), burn (Liandry's), and more
- **Auto-updating data** — Fetches champion and item data from the LoL Wiki for the latest patch

## Setup

Requires Python 3.10+.

```bash
# Clone the repo
git clone https://github.com/Skyway1111/lol-calculator.git
cd lol-calculator

# Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt

# Run the app
python -m flask --app src.app run
```

Then open http://localhost:5000 in your browser.

On first launch, click **"Update to latest patch"** to fetch champion and item data.

## Running Tests

```bash
pytest
```

## Tech Stack

- **Backend:** Python / Flask
- **Frontend:** Vanilla HTML, CSS, JavaScript
- **Data:** Scraped from the League of Legends Wiki via [lolstaticdata](https://github.com/meraki-analytics/lolstaticdata)
- **Tests:** pytest (337 tests)
