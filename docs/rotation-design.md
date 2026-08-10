# F3 — Optimal Event-Order Engine (algorithmic derivation for all 173 champions)

Status: implemented on `codex/f3-rotation-all`.
Owner: Scryglass combat pipeline (`src/calculator/rotation_resolver.py`).
Gate: `pytest`, `pylint src/ --fail-under=9`, `black --check src/ tests/`,
`node --check static/js/eventorder.js`, golden snapshot re-capture.

## Problem

The F2 engine derived a cast order for ten hand-curated combo champions
and fell back to the certified/default `DEFAULT_CAST_ORDER`
`("Q", "Q2", "W", "E", "R")` for everyone else, with a generic rationale.
That fallback is wrong for kits whose abilities have real setup/consume
relationships (Cassiopeia's poison-fed Twin Fang, Varus' Blight
detonation, Darius' Hemorrhage-stack execute, ...) — and the product
owner's directive is explicit: **derive the order on the fly from the
atomized ability data, never from a hand-maintained combo database**:

> "trust 100% that results are correct only via atomized and math-backed
> analysis understanding what exactly each ability does. having that on
> the go seems faster than having a database of every single possible
> combo for every champion."

F3 makes that derivation fully algorithmic for ALL 173 champions.  The
ten F2 seeds stay as **documented overrides** (verified by hand); every
other champion's order is computed per request by
`src/calculator/rotation_resolver.py`.

## Design

### Resolution chain (explicit order wins)

```
/api/calculate payload cast_order  (user-supplied, validated permutation,
                                    checked against the declarations)
   -> CAST_ORDER_OVERRIDES rule     (hand seeds — each with an override_reason)
   -> ALGORITHMIC DERIVATION        (this module — every champion with atomized data)
        declarations + inference merged  (resolved_edges, the precedence table)
        edges?  -> constrained topological order + matrix-consistent DPS tie-break
        no edges -> certified module CAST_ORDER or DEFAULT_CAST_ORDER (honest flat-kit)
```

### The declared lane

Two surfaces make ordering claims and `resolved_edges` is where they
meet.  A champion module DECLARES what its own kit requires in
`CAST_DEPENDENCIES` (`src/calculator/cast_dependency.py` owns the
vocabulary: `cc_enabler`, `damage_enabler`, `resource_enabler`,
`recast_of`); the detector INFERS ordering from the markers it parses
(`INFERRED_EDGE_KINDS`, twelve kinds).  The two vocabularies are closed
and asserted disjoint, and every merged edge carries an `origin` naming
the surface that produced it.

`merge_declared_edges` folds one over the other for an unordered pair
{A, B}:

| declared A→B | inferred A→B | inferred B→A | active suppression B→A | outcome |
|---|---|---|---|---|
| – | ✓ | – | – | inferred A→B — the 170 non-declaring champions' path |
| ✓ | – | – | – | declared A→B |
| ✓ | ✓ | – | – | declared A→B, deduped; receipt flags `confirmed_by_inference` |
| ✓ | – | ✓ | ✓ | declared A→B; B→A dropped; receipt cites the suppression |
| ✓ | – | ✓ | ✗ | **`ConflictingInferenceError`** |
| ✓ | – | – | ✓ matching nothing | declared A→B; suppression `latent`, with its reason |

A suppression nests inside its parent declaration and can express only
the exact reverse pair, so an over-broad suppression is unwriteable
rather than merely discouraged.  A declaration is *active* only when
both endpoints exist in this parse — Syndra's `E requires Q2` is inert
below 40 splinters — and an inactive declaration takes its suppression
out of force with it.  What the merge did rides the response as
`rotation.dependencies`.

`resolve_cast_order` returns a rule for EVERY champion in the cached
data.  The derived rule carries `derived=True`; the ten seeds are the
only `derived=False` rules.

### The four signals (unchanged priorities)

| # | Signal | Atom surface | Weight |
|---|--------|--------------|--------|
| a | **Setup/consume edges** | parsed keys (`dot_duration`, `on_hit`, `applies_dot_stack`, `stacking_dot`, `post_hit_proc`, `target_debuff`, `stat_buff`, `cc_kind`, `recast_of`), module OPTION keys (`target_poisoned`, `blight_stacks`, `p_illumination_procs`, `r_hemoplague_debuff`, execute options, ...), structured wiki attribute rows ("Enhanced Damage", "Bonus Damage Per Stack", "Missing Health Damage") | strongest |
| b | **Per-rank DPS** | `total_raw` / effective per-rank `cooldown` × AoE weight (`rank_ability_dps`) | strong, but matrix-gated |
| c | **Cooldown gating** | the engine's shared cast timeline (`_schedule_shared_casts`) — placing the low-cooldown spam tool right after its setup starts its cadence earliest | tie-break |
| d | **Buffs before damage** | `stat_buff` rows with damage-amp keys (bonus AD/AP, penetration) and damage-taken amplifiers open the burst | strong |

### Edge detection — typed atoms only

`detect_setup_consume_edges` reads THREE typed atom surfaces and nothing
else; free-form ability prose is never scanned (the only phrases used are
the wiki's stable structured rows — "applies a stack of X", "become
Chilled", "consumes the mark", "takes X% increased damage"):

1. **Parsed ability package** (`ability_damages`) — `dot_duration`
   (DoT application), `on_hit` (per-auto application), `applies_dot_stack`
   / `stacking_dot` (stack application), `post_hit_proc` (detonation),
   `target_debuff` (resistance shred / charm), `stat_buff` (damage-amp),
   `cc_kind` on `parts` (crowd control), `recast_of` (parent cast).
2. **Module OPTION keys** (`get_champion_options_meta`) — the typed
   setup/consume atoms authored by the champion modules:
   `target_poisoned`, `poison_stacks`, `blight_stacks`, `rend_stacks`,
   `r_overwhelm_stacks`, `plasma_starting_stacks`,
   `denting_blows_starting_stacks`, `p_illumination_procs`,
   `q_marked_target`, `w_wounded`, `q_consume`, `q_execute`,
   `e_execute`, `r_execute_ready`, `target_missing_hp_pct`,
   `q_missing_health`, `w_target_missing_health`, `r_hemoplague_debuff`.
   Self-generated stacks/buffs (`r_stacks`, `q_gathering_storm`,
   `e_true_grit_stacks`, ...) are excluded by a closed vocabulary — they
   are not target setup and create no cross-slot edge.
3. **Structured wiki attribute rows** (`data/champions.json` leveling
   rows) — "Enhanced Damage", "Total Enhanced Damage", "Bonus Damage Per
   Stack", "Detonation Magic Damage", "Missing Health Damage", "Mark
   Magic Damage", "Stored Damage".  These are the wiki's atomized
   attributes, not prose.

The edge taxonomy (closed, asserted by the tests):

| Edge kind | Direction | Meaning |
|-----------|-----------|---------|
| `dot_consume` | Q/W → E | the consumer is enhanced vs the champion's DoT (Cassiopeia poison) |
| `stack_consume` | applier → consumer | the consumer's damage scales per target stack (Darius R, Twitch E, Mel R, Kalista E) |
| `detonate` | applier → detonator | the detonator procs the applied stacks (`post_hit_proc`, "Detonation Magic Damage") |
| `mark_consume` | applier → consumer | the consumer detonates/consumes the mark (Evelynn Q, Lux R) |
| `mark_applier` | applier → burst | the mark is consumed by ANY next damaging ability (LeBlanc Q, Ezreal W, Ryze E) |
| `enhanced_consume` | applier → consumer | the consumer's "Enhanced Damage" row is conditional on a TARGET state (Anivia chill) |
| `execute` | burst → execute | missing-health / stored-damage executes cast after the burst (Veigar R, Mel R, Pantheon Q) |
| `shred` | shredder → burst | resistance-reduction `target_debuff` opens so the burst benefits (Sion E, Corki E, Jayce R) |
| `buff` | buffer → burst | damage-amp `stat_buff` resolves before the abilities it amplifies (Vayne R, Twitch R, Darius E pen) |
| `cc_setup` | CC → burst | `cc_kind` crowd control opens the burst (Ahri charm, Pantheon stun) |
| `amp` | amplifier → burst | damage-taken amplifiers resolve first (Vladimir R Hemoplague) |
| `recast` | parent → recast | a recast rides its parent's casts on the shared timeline (Q → Q2, Ambessa) |

Consumers that are also detonators (e.g. Varus Q — `post_hit_proc` +
missing-health rider) are positioned by the consume relationship; the
execute rider does not re-order them.  Self-consumed mechanics
(Tristana's Explosive Charge, Yasuo's Ride the Wind, Xerath's Arcane
Perfection) produce no cross-slot edge and are flagged for the
verification swarm when a known combo exists.

### DPS tie-break with a stability gate

Among the slots left unconstrained by the edges, the derivation ranks by
per-rank DPS at the fight's stats — `total_raw` / effective cooldown,
AoE-weighted (`rank_ability_dps`; ability haste cancels out of the
relative ranking).  A DPS promotion is only applied when the resulting
order **reproduces at every point of a reference matrix** — level 1/11/18
× no-items/magic/physical/spellblade builds (the same builds the golden
snapshot sweeps).  If the fight's DPS ranking disagrees with any matrix
point, the free slots keep their certified/base relative order and the
rationale says so explicitly.  This makes the derived order
**deterministic across levels and items by construction** — the invariant
the tests assert.

The matrix parses are cached per champion (they depend only on the
cached champion data, never on the request's level/build).

### Fallback — the honest flat-kit classification

A champion with NO detectable edge and flat abilities keeps the certified
module `CAST_ORDER` when one exists (Jayce, Kai'Sa, Karthus, Shen,
Taliyah, Vi), else the engine's historical `DEFAULT_CAST_ORDER`, and the
rationale says exactly that: "no detectable setup/consume signal in the
atomized ability data — no DoT/poison/mark/stack consumer, no resistance
shred, no damage-amplifying buff, no missing-health execute".  This is
the data-driven, honest fallback — not a hidden combo database.

### The hand seeds remain documented overrides

`CAST_ORDER_OVERRIDES` (renamed from `COMBO_TABLE`) holds the hand-verified
seeds — Cassiopeia, Varus, Brand, Vladimir, Aatrox, Jhin, Annie, Lux, Zed,
Aphelios.  The resolver checks the table FIRST; the derivation
never touches them.  Syndra is no longer among them: her module declares
`E requires Q` and `E requires Q2`, the derivation reproduces the order the
seed pinned, and the seed retired against that declaration (D-89) — which
is the only ground on which a seed may be retired.  Every entry carries an `override_reason` from the
closed `ORDER_OVERRIDE_REASONS` set (`scheduling_preference`,
`dps_tiebreak`, `defensive_precast`, `pending_primitive`), so "why is
this order still held by hand?" is a countable field rather than a claim
in this document.  Two seeds deliberately
deviate from a detected data edge (the seed's judgment wins, documented
in `tests/test_f3_rotation_all.py`):

- **Cassiopeia**: W (Miasma) also applies poison → data says W→E, but
  the seed casts E before W to start the 0.75s Twin Fang spam cadence
  earlier on the shared timeline (W is zoning; Q is the poison).
- **Varus**: R applies Blight stacks → data says R→Q, but the seed puts
  the Blight DETONATOR Q first (the auto-applied stacks ride Q; R's own
  stacks land later in the burst).

### AoE — abilities that hit more than one champion

The derived rule carries an `aoe` map (slot → conservative cap from the
structured row fields: `targeting`/`spellEffects` "aoe"/"Area of effect"
→ 5).  The DPS signal multiplies an AoE slot's effective DPS by
`min(roster target count, cap)`, so roster fights (multi-target) rank AoE
tools above single-target nukes of the same raw damage; the default 1v1
fight is unchanged (multiplier 1).

## Rotation receipt (`/api/calculate`)

Every calculate response carries a `rotation` receipt:

```json
{
  "rotation": {
    "order": ["E", "Q", "W", "R"],
    "rationale": "E applies cc_kind crowd control — setup before Q. E applies cc_kind ... Derived order: E → Q → W → R.",
    "cast_order": ["E", "Q", "W", "R"],
    "sources": ["E applies cc_kind crowd control — setup before Q", "...", "free slots ranked by per-rank DPS ..."],
    "setup": ["E"],
    "consume": ["Q", "W", "R"]
  }
}
```

- `rationale` names the specific atoms that drove the order (the edge
  citations); `sources` lists them machine-readably.
- `setup` / `consume` expose the detected relationship; `aoe` the caps.
- The flat-kit fallback receipt says "no detectable setup/consume signal"
  with the kept certified/default order.

## Cooldown gating in timed mode

Unchanged from F2: the engine's shared cast timeline schedules recasts at
per-rank cooldowns running from the end of each cast, ties broken by
`cast_order` position.  The derivation's job is the *permutation*; the
cadence comes from the engine.

## Frontend

Unchanged from F2 (`static/js/eventorder.js` is self-contained).

## Verification

- `tests/test_f3_rotation_all.py` — the combo-invariant suite for ALL 173
  champions: (a) a derived order never violates a detected edge (setup
  before consume); (b) the rationale cites real atoms; (c) the order is
  deterministic and stable across the level/build matrix; (d) the order
  is a permutation of the certified/base slots and the ten seeds stay as
  overrides.  The two documented seed exceptions are pinned.
- `tests/test_f2_rotation.py` — unchanged (F2 contract).
- `docs/rotation-verification-gaps.md` — champions whose derivation is
  ambiguous (conflicting atoms, or no data signal where a known combo
  exists), queued for the F4 verification swarm.
- Golden snapshot re-captured: derived orders change sustained-fight
  totals for the reordered champions (Sion E-first shred, Dr. Mundo
  E-first buff, Twitch R/W-first, Vayne R-first, Hwei R-first, Ahri
  charm-first, ...) — every diff explained in the commit.
