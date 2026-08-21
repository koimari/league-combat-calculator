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

## 4. Off-map stat drift — six Arena records (16.16.1 re-pull)

Recorded 2026-08-20 against patch **16.16** (client) / **26.16** (public), wiki
source version 16.16.1 (`data/.items.json.meta`).

`scripts/patch_regression.py check` flags six items as `stale` on a stat
compare against the 16.16 game files. **All six are off-map**: every one has
`modes["classic sr 5v5"] = false` in the cached mode table, so
`item_source.sr_availability` returns `selectable = false` and
`item_source.audit_scope` returns `in_scope = false,
classification = "off_map"`. Their stale cache values therefore cannot reach
any admitted Summoner's Rift build — this is **out-of-surface drift**, not a
re-cert.

| Item | ID | Cached → game file (16.16) | Mode table | `audit_scope` |
|---|---|---|---|---|
| Hellfire Hatchet | 4017 | attackDamage 35 → 40 | sr=false, ar=true | off_map |
| Spectral Cutlass | 224004 | attackDamage 50 → 60; lethality 15 → 21 | sr=false, aram=true, nb=true, ar=true | off_map |
| The Golden Spatula | 224403 | health 350 → 250; mana 350 → 250; armor 40 → 30; magicResistance 40 → 30; omnivamp 15% → 10% | sr=false, ar=true, mayhem=true | off_map |
| Hexbolt Companion | 443081 | attackSpeed 75 → 50 | sr=false, ar=true | off_map |
| Prowler's Claw | 446693 | attackDamage 55 → 60 | sr=false, ar=true | off_map |
| Diamond-Tipped Spear | 447120 | attackSpeed 30 → 40 | sr=false, ar=true | off_map |

- **Conflict**: the 16.16.1 wiki re-pull left all six entries byte-identical to
  the previous commit (no `stats` diff, no `patchLastChanged`), while the
  refreshed `data/gamefiles/items.bin.json` carries the values above. The
  wiki's Arena item pages lag the game files.
- **Corroboration**: none of the six appears in Riot's patch 26.16 notes
  (<https://www.leagueoflegends.com/en-us/news/game-updates/league-of-legends-patch-26-16-notes/>),
  and each wiki page classifies the item as Arena-only. The identical flags are
  already present in the committed 16.15 `data/staleness.json`, so this is a
  standing off-map gap, not a 16.16 regression.
- **Resolution**: **Arena-only / map-granted**, following the Radiant Virtue
  precedent in §2. Four of the six (224403, 443081, 446693, 447120) are also
  `rank = DISTRIBUTED`, so `sr_availability` classifies them
  `map_or_system` — withheld twice over. No cache value is hand-edited: rule 2
  keeps `data/items.json` a pure `data_updater` artifact, and rule 6 keeps
  admission a function of the cached `modes` table rather than a name list.
- **Resulting coverage**: `blocked` — not reviewed for SR outgoing damage or
  state, optimizer-ineligible, excluded from SR selection. Fail-closed and
  correct.
- **Known gap (not fixed here)**: `patch_regression.py` compares every cached
  item, including off-map records, so these six keep `stale: true` and keep
  their STALE badges. Scoping the item compare to
  `item_source.audit_scope(...).in_scope` would retire six permanent false
  positives; that is a gate-behaviour change and is deliberately left for a
  separate, reviewed commit.

## Gate

Sections 1-3 exit the reconciliation gate with the source, revision/date, mode availability, and resulting coverage recorded above. Related: #40 (parent), #51, #85. Section 4 records six off-map records as out-of-surface; they carry no SR coverage obligation.
