You are fixing BIS certification for the last 5 champions whose item builds never certify (E9-BIS-A) in a League of Legends combat calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-e9-bis-a (branch codex/e9-bis-a). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

PROBLEM: /api/bis returns 0 certified candidates for: Smolder, Talon, Twitch, Velkoz, Viego (all 96 candidates are 'partial'; coverage says 'No candidate has complete sourced event order'). This is the same failure Varus had: the champion module's ability entries lack authored event-order certification, so the optimizer cannot certify ANY item build.

THE PATTERN (copy Varus's fix from src/calculator/champions/varus.py, committed at 938bf9a):
- varus.py now wraps each one-instance slot with _certified_single_hit(simple_damage(...)) setting entry["event_order_certified"] = "single_hit"; on-hit slots set "auto_stack_proc"; multi-part procs (blight_detonation) carry DamagePart(time_offset=...) so damage.py's _apply_post_hit_proc marks timing_is_authored and the timeline coverage goes exact.
- Verify with: /api/calculate (timeline_coverage complete==true, coarse_sources==[]) then /api/bis (certified_candidate_count > 0).

FOR EACH CHAMPION (src/calculator/champions/<name>.py — check what the module emits; every damaging entry needs event_order_certified):
- Smolder (smolder.py): Q burn proc row (post_hit_proc? verify), P, Q crit-scaled entry — certify single_hit / proc timing.
- Talon (talon.py): Q/W/R single hits; P Blade's End bleed proc (16 sourced ticks — the ticks carry authored cadence already? verify timeline coverage after adding markers).
- Twitch (twitch.py): P poison DoT ticks, E Contaminate detonation, R stat_buff — certify with authored timing.
- Velkoz (velkoz.py): P Deconstruction proc, R 13-tick channel (dot_duration authored).
- Viego (viego.py): Q active + on-hit + second strike, R base + hp-scaled part.
The exact markers depend on the entry shape; the gate is EMPIRICAL: timeline_coverage complete + BIS certified_candidate_count > 0 for all 5 (test /api/calculate one_rotation + time_based 10s and /api/bis with role mid/bottom at level 18).

RULES: only touch src/calculator/champions/<the five>.py + tests/test_e9_bis_a.py (new). Follow the module conventions; no invented numbers (markers are timing metadata, not numbers).
GATES: pytest tests/test_e9_bis_a.py; pytest -q (full); pylint src/ --fail-under=9; black --check src/ tests/; golden compare (should be IDENTICAL — markers do not change damage totals; if golden changes, explain).
COMMIT "feat(E9-BIS-A): certify event order for Smolder, Talon, Twitch, Velkoz, Viego" and PUSH origin/codex/e9-bis-a. Do NOT merge.
Reply to parent: per champion — the markers added + BIS certified count before/after, test results, gates, golden status, commit SHA.