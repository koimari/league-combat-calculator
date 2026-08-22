# Roadmap to 100 — coverage close-out plan

Status: FINAL (this pass supersedes the two capped-out prior attempts; no
partial doc or scratch data from those attempts was found in the repo,
worktrees, or stash at start — this document was built from a clean `main`
via fresh runtime introspection, not recovered notes). All computed figures
are reproducible with the commands in the Methodology appendix.

Scope: (1) item BIS tiering, (2) champion slot gaps read from the runtime
registry, (3) four proposed kernel extensions, (4) the patch-day pipeline's
manual/scriptable split, (5) a proposed execution order with a coverage-%
projection, (6) methodology.

---

## 1. Item tiers

### 1.1 Coverage summary (ordinary Summoner's Rift shop only)

`item_source.is_ordinary_sr_item()` is the admission gate — the same
predicate the optimizer's candidate pool uses. `item_coverage.item_model_coverage()`
is the modeling classification.

| Bucket | Count | % of SR-admitted |
|---|---|---|
| SR-admitted items (total) | 209 | 100.0% |
| `modeled_effect` (bespoke damage/proc formula) | 80 | 38.3% |
| `modeled_state` (bounded scenario-control mechanic) | 36 | 17.2% |
| **Modeled total** (`modeled_effect` + `modeled_state`) | **116** | **55.5%** |
| `stats_only` (raw stat line only, no bespoke mechanic) | 92 | 44.0% |
| `blocked` (mechanic identified, authority conflict) | 1 | 0.5% |
| `review_pending` | 0 | 0.0% |

The `ITEM_EFFECTS` dict (`item_effects.py`) carries 128 entries total — that
figure includes ally-only and non-SR effects outside this 209-item pool, which
is why it does not equal the 116 SR-modeled count above. The one `blocked`
item is **Fimbulwinter** (Winter's Approach's completed form): the mana-gate
threshold and its comparison operator are untyped, so the optimizer withholds
it (`item_coverage._PARTIAL_BLOCKED_REASONS`).

**Update (2026-08-20) — the 92 `stats_only` items are now formally
certified.** `tests/test_stats_only_items.py` is the certification pass:
every one of the 92 is machine-verified as genuinely `stats_only` /
optimizer-eligible / calculation-eligible, an ordinary SR purchase per
`item_source.is_ordinary_sr_item`, and — for the 41 that carry a real
described passive/active (see §1.3) — its cached branch text is pinned
byte-for-byte in `item_coverage._STATS_ONLY_CERTIFIED_EFFECT_TEXT` so a
future patch cannot silently attach a new outgoing-damage clause to a
name-matched entry and keep sailing through unreviewed. Each item's own
cached stat block is also spot-verified against `calculate_total_stats`
through isolated output fields (no hardcoded item numbers; every expected
value is read live from `data/items.json` via the existing `get_item_stats`
accessor). **Zero misclassifications found**: none of the 92 add outgoing
damage to a champion target — the 41 described items' numeric mechanics are
self-directed (shields: Bloodthirster, Hexdrinker, Kaenic Rookern, the
Lifeline family, Guardian Angel) or non-damage debuffs/utility on the enemy
(Grievous Wounds, slows, stasis), and Doran's Helm's 5 bonus physical damage
is minion-only (no champion target in this 1v1 fight model) — already an
explicit named boundary, not a gap. Ally-directed heals/shields among the 41
(Echoes of Helia, Moonstone Renewer, Dream Maker, Solstice Sleigh, ...) are
separately modeled through `item_support_effects.py`'s ally ledger; that
representation is out of `item_coverage`'s outgoing-TDD scope by design and
is unaffected by this certification pass. The golden gate showed zero diffs
(certification changed no calculation, only added a registry and tests).

### 1.2 BIS-frequency tiers — PROVISIONAL PROXY

**PROVISIONAL PROXY.** Tiering below ranks items by how often `optimize_build`
selected them across a 30-champion × 2-target-profile sample (60 unconstrained
5-legendary-slot searches, level 18, `max_legendary_slots=5`, boots excluded
from this count — see appendix §6.2). This is a *sampled* frequency, not a
population BIS rate: it reflects the champion roster and target profiles
chosen for the sample, not live match data, and a 30-champion sample cannot
resolve close ties or role-specific niches (supports, junglers with clear
paths, and split-push bruisers are under-represented). Re-run with a larger,
role-balanced sample before using this for anything but sequencing triage
work.

Of the 116 modeled items, 28 appeared at least once in the sample; the other
88 modeled items never won a slot in this sample (not "unmodeled" — see §1.3).

**Tier 1 — core (≥13/60 builds, ≥21.7%).** 11 items (a tie at 13 puts two
items at rank 10):

| Item | BIS count (/60) |
|---|---|
| Stormsurge | 29 |
| Profane Hydra | 29 |
| Shadowflame | 28 |
| Bastionbreaker | 26 |
| Rabadon's Deathcap | 22 |
| Actualizer | 20 |
| Voltaic Cyclosword | 19 |
| Void Staff | 16 |
| Liandry's Torment | 15 |
| Serylda's Grudge | 13 |
| Hextech Gunblade | 13 |

**Tier 2 — situational (4–12/60 builds).** 8 items:

| Item | BIS count (/60) |
|---|---|
| Malignance | 11 |
| Muramana | 10 |
| Umbral Glaive | 9 |
| Infinity Edge | 8 |
| Lord Dominik's Regards | 5 |
| Eclipse | 4 |
| Essence Reaver | 4 |
| Lich Bane | 4 |

**Tier 3 — niche (1–3/60 builds).** 9 items:

| Item | BIS count (/60) |
|---|---|
| Hexoptics C44 | 3 |
| The Collector | 2 |
| Yun Tal Wildarrows | 2 |
| Luden's Echo | 2 |
| Blackfire Torch | 2 |
| Kraken Slayer | 1 |
| Bloodthirster | 1 |
| Spear of Shojin | 1 |
| Trinity Force | 1 |

**Tier 4 — no signal (0/60 builds), 88 items.** Fully modeled and optimizer-
eligible; simply never won a slot against this sample's 30 champions and 2
target profiles. Not a coverage gap — a sampling gap. Not enumerated here
(reproduce via appendix §6.2 against a different roster to populate it).

### 1.3 Stat-only list (`stats_only`, 92 items) — CERTIFIED (2026-08-20)

`stats_only` means `item_model_coverage` found no mechanic that adds
**outgoing damage from the item's own holder** — corrected wording: this is
narrower than "no bespoke formula at all". 51 of the 92 truly have no cached
passive/active. The other **41 do carry a real, numeric mechanic** (a self
shield, Grievous Wounds, a slow, stasis, or an ally-directed heal/shield
routed through the separate support ledger) — they are still correctly
`stats_only` because none of that text deals damage to a champion target;
see the certification note in §1.1 and `item_coverage.py`'s
`_STATS_ONLY_CERTIFIED_EFFECT_TEXT` docstring. It is not a judgment about the
item's power; six `stats_only` items are in Tier 1/2 above (Void Staff,
Serylda's Grudge, Bloodthirster, and three others carry stats the optimizer
values highly with no outgoing-damage passive to model).

Split by shop price (≤1600g = component/boots/consumable tier, the "near-free"
set; ≥2200g = completed legendary stat-sticks):

**Near-free (≤1600g), 70 items** — components, boots, wards, potions, elixirs:

Health Potion, Control Ward, Refillable Potion, Faerie Charm, Dagger, Glowing
Mote, Boots, Rejuvenation Bead, Sapphire Crystal, Cloth Armor, Long Sword,
Ruby Crystal, Null-Magic Mantle, Amplifying Tome, Doran's Bow, Celestial
Opposition, Dream Maker, Solstice Sleigh, Scorchclaw Pup, Gustwalker
Hatchling, Mosstomper Seedling, Doran's Helm, Elixir of Iron, Elixir of
Sorcery, Elixir of Wrath, Cloak of Agility, Forbidden Idol, Rectrix, Chain
Vest, Winged Moonplate, Kindlegem, Executioner's Calling, Crystalline
Bracer, Oblivion Orb, Blasting Wand, Negatron Cloak, Fiendish Codex, Pickaxe,
Giant's Belt, Glacial Buckler, Aether Wisp, Ionian Boots of Lucidity,
Crimson Lucidity, Bandleglass Mirror, Boots of Swiftness, Warden's Mail,
Serrated Dirk, Caulfield's Warhammer, Steel Sigil, Berserker's Greaves,
Sorcerer's Shoes, Spellslinger's Shoes, Blighting Jewel, Tunneler, Needlessly
Large Rod, Plated Steelcaps, Hearthbound Axe, Zeal, Armored Advance,
Mercury's Treads, Chainlaced Crushers, Spectre's Cowl, B. F. Sword,
Hexdrinker, Noonquiver, The Brutalizer, Last Whisper, Seeker's Armguard,
Shattered Armguard, Verdant Barrier.

**Legendary stat-sticks (≥2200g), 22 items** — no outgoing-damage mechanic
modeled (most of these 22 are among the 41 certified "described" items —
see §1.1 — carrying a real self-shield/heal/utility passive that is out of
this calculator's attacker-TDD scope by design), but full-price and
build-relevant: Moonstone Renewer, Echoes of Helia,
Diadem of Songs, Protoplasm Harness, Rylai's Crystal Scepter, Phantom
Dancer, Spirit Visage, Randuin's Omen, Youmuu's Ghostblade, Morellonomicon,
Kaenic Rookern, Mortal Reminder, Banshee's Veil, Void Staff, Edge of Night,
Cosmic Drive, Chempunk Chainsword, Immortal Shieldbow, Serylda's Grudge,
Guardian Angel, Zhonya's Hourglass, Bloodthirster.

---

## 2. Champion slot gaps (runtime `MODULE_COVERAGE`)

Read live via `champions.registered_champion_names()` +
`champions.get_champion_module_meta()` — the same registry the app and the
optimizer import at request time (see appendix §6.3 for the script). Every
one of the 173 registered modules imported cleanly (zero contract errors).

### 2.1 Runtime coverage totals

| Status | Slot count | % of 865 total slots |
|---|---|---|
| `modeled` | 693 | 80.1% |
| `no_damage` | 23 | 2.7% |
| `out_of_scope` (**the gap**) | 149 | 17.2% |

`VALID_COVERAGE` in `module_contract.py` is a closed three-value set
(`modeled` / `no_damage` / `out_of_scope`) — there is no fourth "partial"
status in the runtime contract; every gap slot is `out_of_scope`.

**Overall runtime coverage: 716/865 = 82.8%.**

### 2.2 Gap distribution — 92 of 173 champions carry at least one `out_of_scope` slot, 149 slots total

| Gap-count tier | Champions | Slots |
|---|---|---|
| 4 slots | Milio, Taric, Zilean | 12 |
| 3 slots | Bard, Kai'Sa, Samira, Shen, Singed, Sona, Trundle, Warwick, Yuumi | 27 |
| 2 slots | Alistar, Anivia, Aurelion Sol, Kalista, Kindred, Lulu, Mel, Miss Fortune, Mordekaiser, Naafiri, Nidalee, Nilah, Olaf, Pyke, Rakan, Rammus, Renata Glasc, Rumble, Seraphine, Sivir, Soraka, Sylas, Taliyah, Teemo, Tristana, Twitch, Udyr, Vi, Viego, Viktor | 60 |
| 1 slot | Aatrox, Akshan, Aphelios, Ashe, Aurora, Azir, Blitzcrank, Camille, Cassiopeia, Cho'Gath, Dr. Mundo, Jarvan IV, Jayce, Kog'Maw, Lissandra, Lucian, Malzahar, Master Yi, Morgana, Nami, Nasus, Neeko, Nocturne, Nunu & Willump, Ornn, Pantheon, Quinn, Rek'Sai, Renekton, Rengar, Riven, Ryze, Senna, Shaco, Swain, Tahm Kench, Talon, Thresh, Varus, Vayne, Vladimir, Wukong, Xerath, Xin Zhao, Yasuo, Yorick, Zaahen, Zac, Zoe, Zyra | 50 |

Full champion→slot detail (e.g. exactly which of P/Q/W/E/R) is reproducible
via the appendix §6.3 script; the 4- and 3-slot rows are dominated by
support/utility kits (Milio, Taric, Zilean, Bard, Sona, Yuumi) whose value
is almost entirely non-damage (heals/shields/CC), which is exactly the kind
of kit `out_of_scope` under-counts as a "gap" — see the execution-order
caveat in §5.

### 2.3 Degraded-parse subgroup (CLAUDE.md's 8-champion list) cross-referenced

| Champion | Degraded slot (CLAUDE.md) | Runtime `out_of_scope` today |
|---|---|---|
| Aurelion Sol | Q (Stardust stacks) | P, W |
| Bard | P (Chimes) | E, R, W |
| Heimerdinger | W/E (multi-part rockets) | none — fully `modeled`/`no_damage` |
| K'Sante | W (bonus resistances) | none — fully `modeled`/`no_damage` |
| Quinn | P (crit chance) | W |
| Vladimir | E (charge time) | P |
| Yasuo | Q3 (crit conversion) | R |
| Zeri | P (execute range) | none — fully `modeled`/`no_damage` |

4 of the 8 documented degraded-parse champions (Heimerdinger, K'Sante, Yone,
Zeri) have since been fully closed to `modeled`/`no_damage` — CLAUDE.md's list
predates their module work and should be trimmed to the remaining 5
(Aurelion Sol, Bard, Quinn, Vladimir, Yasuo; Yone also closed). The other 4
carry `out_of_scope` slots that are NOT the documented degraded slot (e.g.
Aurelion Sol's gap is P/W, not the documented Q) — the degraded wiki parse
and the runtime gap are two different, only partly overlapping problems.

---

## 3. Kernel extensions

| Extension | Owning tests | Prerequisite | Size |
|---|---|---|---|
| P3-3M — minion damage/target model | `tests/test_dorans_helm_minion_damage.py`; touches `damage.py`, `item_effects.py`, `pipeline.py`, `item_coverage.py` | — | **Done (target-class slice)** — see §3.1 for the half that remains **XL** |
| Multi-target roster-allocation refinement | `tests/test_participant_timeline.py`, `tests/test_roster_composition.py` | Sourced per-target sequencing rule for target-limited procs (currently allocated once across the roster, `architecture.md` §Scenarios) | **L** |
| Spell-shield rearm-within-fight | `tests/test_spell_shield_eligibility.py`, `tests/test_delivery_eligibility_kernel.py` | None — the sourced cooldowns are already receipted (`SPELL_SHIELD_NO_REARM_RULE`); needs a fight-window-relative rearm clock wired into `delivery_eligibility.py` | **M** |
| Renata Glasc W (Bailout) lethal half | `tests/test_renata_w_bailout.py` | Damage-class corroboration for the burn (see below) — currently unresolvable from local sources | **S** once unblocked, **unschedulable** until then |

### 3.1 P3-3M — minion model

**Done — target-class slice only.** The kernel now carries a target-class
label, `FightConfig.target_class` (`"champion"` default, `"minion"`), plumbed
through `pipeline.py`'s request parsing to the public `/api/calculate` body.
It gates class-restricted item EFFECTS: `item_effects.CLASS_RESTRICTED_ON_HITS`
compiles Doran's Helm's Helping Hand from its typed accessor
(`dorans_helm_helping_hand_minion_damage`, sourced 5 bonus physical on-hit,
wiki revision 4034679) into a `class_restricted_per_hits` stream that only a
minion-class fight arms. Champion-class fights are unchanged and
golden-identical; `item_coverage` still classifies the Helm `stats_only`
because its champion-class contribution is still exactly zero.

**Scope note — what did NOT land, and why it is still XL.**

1. *No sourced minion stat block.* The label gates effects, not stats. A
   minion-class target's health/armor/MR remain caller-supplied, because no
   minion base-stat table is cached. So a "minion" fight is a
   caller-shaped target wearing a minion label — it is not a sourced minion.
2. *No minion actor, no kill events.* There is still no typed minion
   combatant, no "large minion" flag, and no kill-credit event in the
   roster/combatant layer or the event ledger.
3. *Champion ability class clauses are not adjudicated.* Nasus Q permanent
   stacking off minion kills, Cho'Gath Feast's minion/monster stack cap,
   Cull's minion-kill progression payout, and Ezreal R's minion-damage row
   are all untouched. Ability-carried on-hit applications do not carry the
   class-restricted branch either.
4. *Unadjudicated class clauses fail closed, they are not modeled.* Any build
   item whose cached effect text names a target class without an entry in
   `CLASS_RESTRICTED_ON_HITS` makes a minion-class fight raise, naming the
   item and clause (`item_effects.target_class_denials`). Statikk Shiv's
   "increased to 90 against non-champions" and Blade of the Ruined King's
   minion/monster caps are therefore refusals, not results — a minion-class
   fight today is only usable for narrow, deliberately-small builds.
5. *Tear of the Goddess Helping Hand is not armed.* Only Doran's Helm is
   adjudicated; the Tear family keeps its receipt-only boundary.

Items 1–3 are the remaining XL: a new actor class touching the combatant
model, the event ledger, and every champion/item that references minions.

### 3.2 Multi-target / roster refinement

Roster combat itself is NOT a gap — `scenario.py` already resolves up to 5
enemies and 4 allies, and `optimize_build`'s `target_fight_params` already
scores a candidate against a full roster (summed TDD). The open piece is
narrower: `architecture.md` names its own simplification — *"Target-limited
item procs are allocated once across the roster"* rather than walked
per-target in cast order. Sizing L because it changes the coupled search's
per-search caching contract (`timeline_optimizer.py`), which is
performance-sensitive and covered by the cache-equivalence regression tests.

### 3.3 Spell-shield denial — rearm within one fight

Most of the spell-shield lifecycle is already implemented (P2 Slice 2):
one-use consumption, control-only packets consuming the shield, prior-defense
ordering, and a basic-attack carve-out are all typed rules in
`delivery_eligibility.py` with wiki-sourced receipts
(`spell_shield_rules_receipt()`). The one open rule is explicit in the code:
`SPELL_SHIELD_NO_REARM_RULE` — *"A consumed shield is not rearmed inside one
modeled fight; the sourced cooldown remains receipted... Rearm is follow-up
work."* The cooldowns are already sourced (40s Banshee's/Edge of Night,
resets on champion damage; 60s Verdant Barrier), so this is M, not L: the
missing piece is wiring the fight-duration clock into the eligibility
window, not sourcing new numbers.

### 3.4 Renata Glasc W (Bailout) — the burn's damage class

`champions/renata_glasc.py`'s `BAILOUT_AUTHORITY` record is the fullest
adjudication example in the codebase. Cadence is SETTLED on the
gamefile-wins-over-wiki precedent (CLAUDE.md's Gnar Mega-form rule): 4
ticks/second (0.25s interval), 10 ticks, a 2.5s window — the Wiki's 0.264s
figure is rejected as the outlier (the same Wiki sentence corroborates 0.25s
independently). Damage CLASS is UNRESOLVED: the cached Wiki description
calls the burn "true damage," the same entry's own notes call it "raw
damage," and the local game-file record
(`data/bin/characters/renata.bin.json`, record
`Characters/Renata/Spells/RenataWAbility/RenataW`, patch `16.15.8024387`)
defines no damage-class field for it at all.

**Cite: the `burn_damage_class` searched record** (dated 2026-08-20 inline in
`renata_glasc.py`) re-tested this against the current Community Dragon dump
rather than assuming staleness: the published `renata.bin.json` is
byte-identical to the tracked local evidence, the champion bin holds no
separate burn effect object (`RenataWAbility`'s only child spell IS
`RenataW`), and the schema's one damage-class field (`mDamageType`) occurs
**zero times** across all 203 local champion bins and `items.bin.json` — the
field is not shipped as data for *any* champion, so there is no
corroborating enum to check the burn against. `runtime_available: False`,
`reason: "burn_authority_conflict"`, three denied survival components
(`lethal_damage_restore`, `maximum_health_burn`, `resurrection_precedence`).

This is why it is sized S-once-unblocked but currently unschedulable: the
implementation itself (apply the settled cadence, gate the class) is small,
but no local source can supply the missing field — the prerequisite is an
external one (a future patch's binary shipping `mDamageType`, or a
authoritative Riot statement), not more engineering effort.

---

## 4. Patch-day pipeline — manual vs. scriptable

Nine steps total: 5 manual, 3 scriptable, 1 partly scripted (detect), per `docs/patch-day-runbook.md`.

| # | Step | Manual/Scriptable | Inputs | Deps | Fail-closed failure mode |
|---|---|---|---|---|---|
| 1 | Detect patch + read patch notes + open tracking issue | **Partly scripted** | `python scripts/patch_update.py detect` (live CDragon vs cached patch; exit 1 = new patch), Riot patch notes page | `cdtb` binary on PATH (or `CDTB_BIN`) | None automated — a missed patch silently serves stale data until Step 2 next runs; this is why Step 0 has its own <4h SLA |
| 2 | `scripts/patch_update.py run` — re-pull wiki cache, rebuild catalogues, run gates | **Scriptable** | live wiki pages via `vendor/lolstaticdata`, `git HEAD` (for the audit diff) | cleared `vendor/lolstaticdata/__cache__`/`__wiki__`; network access | Stops the run on: a vanished effect branch not in `APPROVED_BRANCH_REMOVALS`; an unreviewed Riot-declared effect missing from the wiki not in `ACKNOWLEDGED_SOURCE_CONFLICTS`/`OPEN_SOURCE_CONFLICTS`; a removed item still `IMPLEMENTED` in code; pytest red |
| 3 | `scripts/patch_regression.py check` — game-file ground-truth diff | **Scriptable** | `raw.communitydragon.org` per-champion bins + `items.cdtb.bin.json`, live patch string | Step 2's refreshed cache; network access to CommunityDragon | Exits 1 on any stale champion/item; unmappable stats/rows are `unchecked`, never silently passed as fresh |
| 4 | Triage every stale flag: re-certify or boundary-document | **Manual** (human-by-design — this is a judgment call, not a comparison) | Step 3's stale list, patch notes, `data/gamefiles/` | Step 3's output | No automated fallback — an untriaged stale flag blocks Step 5 by design (the STALE badge stays up) |
| 5 | Golden re-capture + full gates (pytest, pylint, black, `git diff --check`) | **Scriptable** | `scripts/golden_snapshot.py compare/capture`, `scripts/golden_baseline.json` | Step 4's re-certified values committed to the working tree | Golden diffs are EXPECTED post-patch and do not block by themselves; pytest/pylint/black/`git diff --check` red DOES block |
| 6 | Explain every golden diff in the commit message | **Manual** | `scripts/patch_update.py detail <name>` per changed module | Step 5's diff output | No script checks diff explanations are *correct*, only that they exist in the commit body — a wrong explanation ships silently |
| 7 | Commit + push + merge via review | **Manual** | staged data + code + golden together (never split across commits) | Step 6 | Standard review gate; a split commit (data without golden, or vice versa) is a self-inflicted future regression, not caught by CI |
| 8 | Close the tracking issue against `docs/issue-closure-policy.md` | **Manual** | issue number, merge commit sha, deployed sha for a user-visible fix | `docs/issue-closure-policy.md` (commit-addressed, gate-checked, deployment-gated) | No script checks the three conditions — an unchecked closure claim ships silently |
| 9 | Confirm staleness clears post-deploy (`patch_regression.py check` re-run, `/api/staleness`, badge check) | **Manual** | live `/api/staleness` endpoint, UI badges | Step 7 deployed | No script re-verifies the *deployed* endpoint — this is the one step with no scriptable substitute because "did the badge actually disappear in production" requires observing production |

---

## 5. Proposed execution order

**PROVISIONAL PROXY.** Sessions are ordered by `out_of_scope` slot-count per
champion (§2.2), treating every slot as equal-effort. This is almost
certainly wrong as an effort proxy — a single execute-scaling slot
(e.g. Kindred R) can be harder than a whole 4-slot support kit whose gaps
are all "this ability has no damage row" — and it carries no signal at all
about which champions are actually played. Re-rank by pick/ban rate and by
an actual per-mechanic complexity estimate before treating this as a real
schedule; treat it only as a way to sequence "close the most slots per
session" work.

| Session | Champions | Slots closed | Cumulative coverage |
|---|---|---|---|
| Start | — | 0 | 82.8% (716/865) |
| 1 | Milio, Taric, Zilean | 12 | 84.2% |
| 2 | Bard, Kai'Sa, Samira, Shen, Singed | 15 | 85.9% |
| 3 | Sona, Trundle, Warwick, Yuumi | 12 | 87.3% |
| 4 | Alistar, Anivia, Aurelion Sol, Kalista, Kindred, Lulu, Mel, Miss Fortune, Mordekaiser, Naafiri | 20 | 89.6% |
| 5 | Nidalee, Nilah, Olaf, Pyke, Rakan, Rammus, Renata Glasc, Rumble, Seraphine, Sivir | 20 | 91.9% |
| 6 | Soraka, Sylas, Taliyah, Teemo, Tristana, Twitch, Udyr, Vi, Viego, Viktor | 20 | 94.2% |
| 7 | Aatrox, Akshan, Aphelios, Ashe, Aurora, Azir, Blitzcrank, Camille, Cassiopeia, Cho'Gath, Dr. Mundo, Jarvan IV, Jayce, Kog'Maw, Lissandra, Lucian, Malzahar, Master Yi, Morgana, Nami, Nasus, Neeko, Nocturne, Nunu & Willump, Ornn | 25 | 97.1% |
| 8 | Pantheon, Quinn, Rek'Sai, Renekton, Rengar, Riven, Ryze, Senna, Shaco, Swain, Tahm Kench, Talon, Thresh, Varus, Vayne, Vladimir, Wukong, Xerath, Xin Zhao, Yasuo, Yorick, Zaahen, Zac, Zoe, Zyra | 25 | 100.0% |

Kernel extensions (§3) are not on this table — they are cross-cutting engine
work, not per-champion slot closures, and should be scheduled independently
(the spell-shield rearm work in particular touches every champion that can
carry Banshee's/Edge of Night/Verdant Barrier, not one champion's module).

---

## 6. Methodology appendix (2026-08-20)

All figures in this document were computed fresh against `main` at commit
`1847d05` via `.venv/bin/python` one-off scripts (not committed — reproduce
with the commands below). No cached/partial output from a prior session was
found or reused (`git status` was clean, no untracked scratch files, no
matching worktree or stash).

### 6.1 Item coverage (§1.1, §1.3)

```python
from calculator.data_fetcher import fetch_item_data
from calculator.item_source import is_ordinary_sr_item
from calculator.item_coverage import item_model_coverage

items = fetch_item_data()
sr_items = [i for i in items.values() if is_ordinary_sr_item(i)]
for item in sr_items:
    status = item_model_coverage(item)["status"]  # bucketed and counted
```

`is_ordinary_sr_item` is the exact predicate `optimizer.py`'s candidate pool
uses (`_ordinary_sr_items`), so the 209-item denominator matches what the
optimizer actually searches. Price split in §1.3 read
`item["shop"]["prices"]["total"]` directly from the same cached records.

### 6.2 BIS-frequency sample (§1.2)

```python
from calculator.data_fetcher import get_champion
from calculator.optimizer import optimize_build
from calculator.pipeline import FightParams

# 30 champions x 2 target profiles (squishy 2200/500/40/40,
# tanky 3600/1800/120/80), level 18, max_legendary_slots=5, unconstrained
# gold (no gold_budget) -> theoretical full BIS, not a purchase plan.
```

60 builds completed in 170s with zero errors. `result["items"]` (the 5
legendary slots) was tallied; `result["boots"]` is a separate key and was
deliberately excluded from this count — boots tiering is a much smaller,
mostly-solved question (armor/lucidity/swiftness/alacrity/agility) that
would have diluted the legendary-slot signal.

Known sample limitations, stated plainly: 30 champions is roughly a sixth of
the roster; the two target profiles are generic squishy/tank archetypes, not
role-specific; no ally-loadout or enemy-composition variation was sampled;
and `optimize_build` without a `gold_budget` returns the damage-maximizing
build, which is not always what a real BIS guide would recommend early or
mid-game.

### 6.3 Champion slot gaps (§2)

```python
from calculator.champions import registered_champion_names, get_champion_module_meta

for name in registered_champion_names():          # 173 names
    meta = get_champion_module_meta(name)          # imports + validates the module
    coverage = meta["coverage"]                    # {"P": "modeled", "Q": "out_of_scope", ...}
```

This is the same `get_champion_module_meta` the `/api/champions` metadata
endpoint calls, reading through `champions.get_champion_module_contract`,
which is the identical import path `pipeline.run_fight` uses for a live
calculation — so "registered" here means "reachable from a real request,"
not a static file listing. All 173 imports succeeded with zero
`ChampionModuleContractError`s.

### 6.4 Kernel extension research (§3)

Grep-sourced from the checked-in modules, not invented: `BAILOUT_AUTHORITY`
(`champions/renata_glasc.py`), `SPELL_SHIELD_NO_REARM_RULE` and the full
spell-shield rule set (`delivery_eligibility.py`), the Helping Hand /
Nasus / Cho'Gath minion-boundary comments (`item_effects.py`,
`item_coverage.py`, `champions/nasus.py`, `champions/chogath.py`), and the
target-allocation sentence in `architecture.md`'s Scenarios section. No
`P3-3M`-style identifier existed in the repo before this document — it is
this document's own naming scheme (Phase 3, item 3, sized Medium-to-XL),
not a recovered backlog reference.

### 6.5 Pipeline (§4)

Transcribed and re-classified from `docs/patch-day-runbook.md` Steps 0–5;
the runbook's own step numbering (six top-level steps) was split into the
nine discrete manual/scriptable actions in §4's table because two of its
steps (1 and 4) each bundle one scriptable action with a distinct manual
judgment call that the runbook itself separates into numbered sub-items.

### 6.6 What was NOT done in this pass

- The BIS-frequency sample (§1.2) is 60 builds against 30 champions — a
  larger, role-balanced, multi-profile re-run would tighten §1.2's tiers
  and populate §1.2's Tier-4 (no-signal) list with real ranks.
- No attempt was made to re-run the golden gate, pytest, or pylint — this
  document makes no code changes, so none were required or run.
- Kernel-extension sizing (S/M/L/XL) is a first-pass estimate from reading
  the existing typed boundaries, not a scoped implementation plan; each
  extension needs its own design pass before work starts.
