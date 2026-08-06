You are creating the CLOSED-BETA LEGAL pages (P0c) for the Scryglass calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p0c (branch codex/p0c-legal). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CONTEXT: The app is a League of Legends combat calculator (Scryglass) using League wiki data (CC-BY-SA) + game-file values, no Riot affiliation. It stores: saved builds, share links (public), validation feedback receipts (loadout + observed damage), session cookies (7-day signed). New beta auth adds invite codes.

DELIVERABLES (all server-rendered templates in templates/ + routes in src/app.py, following the existing /privacy pattern from P0a):
1. templates/terms.html + /terms: usage terms (beta access, invite-code responsibility, no warranty on calculations, acceptable use).
2. templates/riot_disclaimer.html + /riot-disclaimer: the Riot Games disclaimer (not endorsed by Riot, not affiliated; data sources: League Wiki (CC-BY-SA), game files; no Riot API used).
3. Link all three (privacy/terms/riot-disclaimer) from the beta landing (templates/beta_landing.html) + the main page footer.
4. tests/test_p0c_legal.py — each page renders 200 + contains required content anchors; gate-exempt paths include the three legal pages.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; git diff --check; golden identical.
COMMIT "feat(P0c): terms + Riot disclaimer + footer links" and PUSH origin/codex/p0c-legal. Do NOT merge.
Reply to parent: page contents, routing, test evidence, gates, commit SHA.