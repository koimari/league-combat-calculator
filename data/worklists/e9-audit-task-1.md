You are re-auditing League of Legends calculator champions (E9 verification) after the E1-E8 modeling waves.

YOUR WORKTREE: /Users/river/Projects/lcc-e9-audit-1 (branch codex/e9-audit-1). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOUR CHAMPIONS (58):
Aatrox, Akshan, Amumu, Aphelios, Aurora, Belveth, Braum, Camille, Corki, DrMundo, Elise, Fiddlesticks, Galio, Gnar, Gwen, Hwei, Ivern, Jax, Jinx, Kalista, Kassadin, Kayn, Kindred, Leblanc, Lillia, Lucian, Malphite, MasterYi, MissFortune, Morgana, Nasus, Nidalee, Nunu, Ornn, Pyke, Rakan, Rell, Rengar, Ryze, Senna, Shaco, Singed, Skarner, Soraka, Syndra, Talon, Thresh, Tryndamere, Udyr, Vayne, Vex, Viktor, Warwick, XinZhao, Yorick, Zaahen, Zeri, Zoe

WHAT TO DO — for EACH champion produce a fresh verdict reflecting the CURRENT codebase (E1-E8 are merged):
1. Read the champion's runtime module: src/calculator/champions/<name>.py (custom module or packet wrapper). Read its MODULE_COVERAGE map (per-slot modeled/out_of_scope) and ASSUMPTIONS.
2. Read the champion's existing audit entry in data/champion-audit/batch-0.json..batch-7.json (verdict + gap_summary). This is the CP-era baseline; the E-series may have closed its gaps.
3. Check the E-series worklists in data/worklists/ (e2-dot-ticks.json, e3-stacks.json, e3-mechanics.json, e4-summons.json, e5-mismodeled.json, e8-interactions.json) — was this champion's mechanic implemented in E2/E3/E4/E5/E8? Check src/calculator/healing.py HEALING_RULE_CHAMPIONS for self-heal rules (E1).
4. NEW VERDICT RULES (reflect E1-E8 completion):
   - **ok**: every damaging slot has a modeled entry with sourced numbers AND every heal/shield/revive/summon/stack mechanic from the worklists is implemented (or documented as a boundary with a reason). The CP-era gap_summary items are closed.
   - **review**: one or more mechanics remain explicitly unmodeled but DOCUMENTED (boundary/state with a sourced reason in ASSUMPTIONS), OR the module is a reviewed packet that still prices an ability incorrectly.
   - **gap**: a mechanic from the worklists or wiki is NOT modeled and NOT documented (placeholder/absent with no boundary note).
5. Write your verdicts to data/champion-audit/batch-e9-1.json as {"ChampionName": {"verdict": "ok|review|gap", "gap_summary": "<one paragraph: what was fixed by E1-E8, what remains, if anything>", "module": "<name>.py", "slots": {"P": "modeled|out_of_scope|no_damage", ...}}}. Include ALL 58 of your champions (every champion gets an entry; fail-closed if a module is missing).
6. Where the current module has a custom implementation with stack/summon/shield/heal options (e.g. senna_mist_stacks, blight_stacks, voidling_attacks, self_shield_events, starting_revive_defense, grey-health), verify one option value resolves in a /api/calculate probe (level 18, no items) and note it in the gap_summary. Use the worktree's venv.

RULES: only touch data/champion-audit/batch-e9-1.json (new file). Do NOT modify champion modules, tests, or other audit files. Do not run the wiki CLI (source receipts already exist in the CP-era batches).
GATES: python -c "import json; json.load(open('data/champion-audit/batch-e9-1.json'))" (valid JSON, 58 entries, all verdicts in ok/review/gap).
COMMIT "feat(E9-1): refresh champion audit verdicts (58 champions post-E-series)" and PUSH origin/codex/e9-audit-1. Do NOT merge.
Reply to parent: counts of ok/review/gap, the champions whose verdict CHANGED vs the CP-era baseline (with the closing E-series workstream), and any champions still genuinely gapped (with why).