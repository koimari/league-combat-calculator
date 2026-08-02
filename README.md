# League Combat Calculator

A roster-aware League of Legends damage and build calculator. Choose one attacker, reconstruct up to five enemies and four allies, then compare builds or search for the highest modeled total damage dealt (TDD).

## What it calculates

- level-, rank-, item-, role-quest-, and stack-dependent stats;
- post-mitigation damage with League's penetration order;
- cooldown-limited casts, resource costs, regeneration, auto-attack uptime, burns, procs, shields, and per-skill attribution;
- per-target and roster-wide TDD, health damage, DPS, and two distinct build results;
- an exhaustive one-slot result among fully modelled candidates, promoted to certified best in slot only when no available candidate is withheld;
- a clearly labeled heuristic search for complete builds.

The public attacker picker enables only champion modules with reviewed formulas. All 173 cached champions remain available as allies or enemies because base stats and item stats are calculated separately. Unmodeled attacker kits fail closed; unmodeled ally or defensive effects are shown as assumptions instead of being presented as zero.

The optimizer withholds any candidate whose damage-relevant passive, active, or state is not yet modelled. The API names each withheld item and the missing mechanic; the interface labels the result `Best modelled` rather than silently treating that item as a plain stat block.

## Run locally

Requires Python 3.12. After starting the app, open `http://127.0.0.1:5000`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m flask --app src.app run
```

## Verify

```bash
python -m pytest -q
python -m pylint src/ --fail-under=9
python scripts/golden_snapshot.py compare scripts/golden_baseline.json
```

## Data and provenance

Champion and item data are read from the tracked League of Legends Wiki cache in `data/`. Patch refreshes run locally and enter production through reviewed commits. Revision-backed mechanics include their source metadata in the API where available.

The calculator combines the combat engine and tests from [Skyway1111/lol-calculator](https://github.com/Skyway1111/lol-calculator) with Scryglass's roster, comparison, optimizer, provenance, and interface work. The upstream repository has no licence file; redistribution remains closed until its author chooses a licence. See `NOTICE.md`.

Deployment instructions are in `docs/deploy.md`; calculation boundaries and module ownership are in `architecture.md`.
