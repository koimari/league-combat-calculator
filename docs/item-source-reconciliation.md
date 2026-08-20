# Item source reconciliation (issue #86)

Resolutions recorded 2026-08-06 against patch **16.15** (game files via cdtb / Community Dragon; wiki revisions; Riot ddragon tooltips as arbiter for tooltip-vs-bin disputes).

Authority order (from `scripts/patch_regression.py`): game files (Community Dragon bin, verified against local WADs) > Riot ddragon tooltip > wiki cache revision. The wiki cache stays authoritative for **mode availability** (classic SR 5v5 flag in `data/items.json`).

## 1. Gunmetal Greaves (3172) — Noxian Gait

- **Conflict**: Riot 16.15 cache text advertised Noxian Gait (on-hit movement speed); wiki page (rev 4013706, 2026-04-29) records V26.01 removed Noxian Gait, leaving only the stat line.
- **Resolution**: **Wiki-authoritative** — Noxian Gait removed in V26.01; the game file (16.15) has no Noxian Gait branch on 3172 (verified by the P3 stat/ability regression; item flagged `noEffects=true`, stat-only). 
- **Mode availability**: classic SR 5v5 = true (a tier-3 boot).
- **Resulting coverage**: `stats_only`, optimizer-eligible — a stat boot with the Riot-only movement branch explicitly out of scope. `data/staleness.json` reports no drift on 3172.

## 2. Radiant Virtue (446667) — Judgement passive

- **Conflict**: Riot cache advertised a Judgement passive granting 30 ultimate haste; wiki page (rev 3976494, 2025-12-16) is an Arena-only entry with no Judgement branch in its item table.
- **Resolution**: **Arena-only** — the cache itself marks classic SR 5v5 = false (AR = true); the wiki agrees. The Judgement branch is not a Classic SR effect and is not selectable for SR builds.
- **Resulting coverage**: `blocked` (not reviewed for SR outgoing damage/state), optimizer-ineligible, excluded from SR selection — the correct fail-closed state for an Arena-only item.

## 3. Fimbulwinter (3121) — Everlasting in windows without an auto stream

Recorded 2026-08-20.

- **Conflict**: b0f7252 gave a forced empowered swing its slot's reviewed control kind and said no number moved. In the windows with no auto stream (one_rotation; timed and time_based at zero auto uptime) that moved Everlasting's trigger for Cho'Gath (Q's knock-up at 1.127 s → E's slow at the E cast) and Darius (no trigger → W's slow at the W cast), and with it the served survival numbers of the holder against an attacking enemy. The coupled golden held no such cell.
- **Source**: Fimbulwinter rev 3984419 (the registry pin): "Immobilizing, or slowing if you are melee, an enemy champion grants a 100 (+ 4.5% current mana) shield for 3 seconds (8 second cooldown)." Cho'Gath E (rev 3892600): the spikes ride the three empowered attacks, "dealt magic damage and slowed by an amount that decays over 1.5 seconds". Darius W (rev 4022598): the next attack "deal[s] bonus physical damage and slow[s] the target by 90% for 1 second". Both holders are melee.
- **Resolution**: **Engine stands** — a melee holder's slow arms Everlasting, so the forced swing is the first qualifying trigger. Its time is the cast instant, the convention the stream path already used (timed with autos at 72eb89c: trigger `slow` at the E cast, 1.0 s); in the kit the attack reset lands the swing one windup after the cast, still before Rupture's 0.5 s cast + 0.627 s delay. The windows that moved now agree with the one that was already right.
- **Resulting numbers** (HEAD vs 72eb89c; level 18, Fimbulwinter, vs an attacking Darius with Stridebreaker): Cho'Gath one_rotation, autos on or off — shield absorbed 190.9 → 164.8, health damage 2230.8 → 2257.0, ending health 711.2 → 685.0 (the shield expires at 3.0 s with 26.1 unspent). Darius one_rotation — absorbed 0 → 158.6, 2374.0 → 2215.4, 1265.7 → 1424.3; timed and time_based autos-off — 0 → 158.6, 2892.3 → 2733.7, 829.7 → 961.3. Solo totals unchanged everywhere. Fiora's trigger lands at 0.0 s (E's forced swing) instead of 0.5 s (W) with no value moved; 23 further champions flip `fimbulwinter_everlasting` from coarse to certified with no value moved. Covered by the coupled golden scenario `everlasting_forced_swing_roster`.

## Gate

Every entry exits the reconciliation gate with the source, revision/date, mode availability, and resulting coverage recorded above. Related: #40 (parent), #51, #85.
