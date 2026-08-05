# CP44 — Stateful item families (#44)

Status: implementation complete locally; preview/production promotion remains
open until the CP44 deployment and browser evidence are recorded.

## Scope

The shared typed item-state ledger now covers the conversion, resource,
progression, transformation, activation, expiry, and terminal-state branches
for Actualizer, Archangel's Staff, Manamune, Whispering Circlet, Winter's
Approach, Rod of Ages, Hubris, Axiom Arc, Endless Hunger, Heartsteel,
Overlord's Bloodmail, Riftmaker, Swiftmarch, Yun Tal Wildarrows, The
Collector, Experimental Hexplate, Fiendhunter Bolts, Zeke's Convergence, and
Malignance. The same receipt is emitted by manual and optimizer fight paths.

Actualizer uses an explicit 0–8 second window. Its doubled resource cost,
ability amplification, and basic-ability cooldown progression are applied only
inside that window; cooldowns that cross the expiry boundary resume at the
ordinary rate. Riftmaker's fully stacked Void Corruption uses the complete Wiki
branch: 10% omnivamp for melee champions and 6% for ranged champions.

## Full-entry source requirement

Every item in this checkpoint was checked against its complete League Wiki
parent entry, not only the tooltip. The machine receipt is
`docs/wiki-full-entry-audit.json`; the relevant current revisions include
Actualizer 3991377, Riftmaker 4047644, Heartsteel 4044274, Whispering Circlet
4015267, Winter's Approach 3984418, Hubris 4013949, Axiom Arc 4013645,
Endless Hunger 4019625, Zeke's Convergence 4046570, Malignance 4019543,
Swiftmarch 4030448, and Yun Tal Wildarrows 4046569. The requirement and its
fail-closed rule are documented in
`docs/full-wiki-entry-review-requirement.md`.

The full-entry audit currently records 410 audited pages: 290 ready and 120
review-pending generated champion packets. Those 120 are the known #15/#18
blocker, not an item-source omission; the release gate therefore remains open.

## Local evidence

- `.venv/bin/python -m pytest -q`: **3017 passed**.
- `.venv/bin/python -m pylint src/ --fail-under=9`: **9.60/10**.
- `.venv/bin/python -m black --check src/ tests/`: **378 files unchanged**.
- `node --check static/js/app.js`: passed.
- `git diff --check`: passed.
- `.venv/bin/python scripts/golden_snapshot.py compare scripts/golden_baseline.json`: identical.
- `.venv/bin/python scripts/acceptance_matrix.py --json`: 10/10 scenarios passed; two are honestly withheld for the existing CP6 coarse-source exclusions.
- `.venv/bin/python scripts/champion_optimizer_matrix.py --json`: 173/173 exercised, zero partial/unexhaustive outcomes.
- `.venv/bin/python scripts/item_umbrella_audit.py --output docs/item-umbrella-audit.json --json`: review_pending 0, path mismatches 0, unexplained blocks 0; 13 attacker and 4 target blocks remain explicitly assigned to later child checkpoints.

No issue is closed by this local receipt. Closure requires a PR, a matching
Vercel preview, production deployment at the merged SHA, and the dedicated
browser scenario against production.
