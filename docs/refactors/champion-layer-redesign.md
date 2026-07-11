# Champion layer redesign (campaign Phase 3) — approved design

Synthesis of a three-way design bake-off (declarative spec tables / generic-plus-hooks /
slot archetypes). Verdict: **slot-archetype engine** (Design C's skeleton) with the
strongest ideas from the other two grafted on, and single-user archetypes cut.

## Shape

One engine, `champions/engine.py`, runs every champion — registered or not — from a
**slot map**: `{slot: slot_parser}`. A slot parser is a plain function `SlotCtx -> entry
dict | None`, produced either by an **archetype factory** (configured with data) or
written as a **custom function in the champion's own file** (the escape hatch — no string
registries, no separate post-processor module).

Engine evaluates slots in **phase order: BUFF → DEBUFF → DAMAGE → ONHIT → AMP**
(phase stamped on the parser by its factory). BUFF/DEBUFF parsers mutate the shared
`ctx.stats` / target context, so damage slots always see buffed stats — the invariant
that today lives in twelve "process R first" comments becomes an engine guarantee.

## Archetype library — ≥2 real users or it doesn't exist

From the slot inventory across the 12 modules, ONLY multi-user mechanics become
archetypes (in `champions/slotlib.py`):

| Archetype | Users today |
|---|---|
| `simple_damage(attr=None, dmg_type, casts=1, cooldown="standard")` | nearly every slot; `attr=None` = classifier auto-detect (the old generic path) |
| `by_option(option, {value: parser})` | Aatrox Q, Ambessa Q/W, Vayne E |
| `multi_hit_sum(attrs, dmg_type)` | Aatrox Q casts, Ahri W, Akshan Q, Ambessa E, Alistar E |
| `stat_buff(attr, stat, mode=flat|percent_of, couples=...)` | Aatrox/Vayne/Annie/Ambessa R, Ashe/Kog'Maw Q/R |
| `on_hit_pct_health(attr, dmg_type, scale=rank|level, floor_attr, stacks_required)` | Aatrox P, Kog'Maw W, Vayne W |
| `proc_damage(attr, count_option, dmg_type)` | Akali P, Ambessa P, Akshan P |
| `toggle_dot(per_tick_attr, interval, duration_option, phases)` | Amumu W, Alistar E, Anivia R |
| `missing_hp(base_attr, ...)` | Akali R, Akshan R, Kog'Maw R |
| `utility()` | zero-damage display placeholders |

Single-user mechanics stay **custom slot functions in the champion file**: Ahri's
mixed magic/true split and ×3 R, Ashe's auto_attack_override, Amumu's curse amplifier
(AMP phase), Kog'Maw's shred (DEBUFF phase), Annie's Tibbers aura (data-gap constants
stay quarantined at the top of annie.py), all of Akshan's prose-regex parsing.
Guardrail (from Design C, enforced in review): an archetype may not grow a flag that
changes which fight-engine keys it emits — that's the signal to split or go custom.

## What's kept from the other designs

- **Design B's attribute-table insight**: the dominant reason modules exist is "generic
  parser picked the wrong attribute" — in this design that's `simple_damage(attr="...")`,
  one data argument, zero code.
- **Design B's zero-damage-slot trap**: the current engine drops slots with no damage
  (generic_parser.py:212). Stat-buff ultimates emit zero damage; the engine must still
  emit their entries (stat_buff must never silently vanish). Implementation must add an
  explicit test for this.
- **Design A's options-as-data**: each champion module declares
  `OPTIONS = [OptionDecl(key, type, default, label)]` and `ASSUMPTIONS = [...]` next to
  its `SLOTS`. The dispatcher exposes `get_champion_options_meta()`, which app.py serves —
  this REPLACES app.js's 315-line `championOptionsDefs` (moved here from Phase 2, since
  it lands naturally with the spec).

## File layout (one champion, one home — navigability rule)

- `champions/engine.py` — phase-ordered loop, SlotCtx, build_parser (~130 lines)
- `champions/slotlib.py` — the archetype factories + ONE extraction core
  (`_sum_modifiers`, `extract_named`, `extract_auto`, `extract_cooldown`,
  `build_stats_context` — absorbs the duplicated halves of common.py and
  generic_parser.py) (~350 lines)
- `champions/<name>.py` — per champion: `SLOTS`, `OPTIONS`, `ASSUMPTIONS`, any custom
  slot fns, `parse_abilities = build_parser(SLOTS, "<Name>")` (~15-40 lines each;
  Akshan ~120)
- `champions/__init__.py` — dispatcher unchanged in signature; unregistered champions get
  `GENERIC_SLOTS = {Q/W/E/R: simple_damage(), P: on_hit_auto()}`
- generic_parser.py and the extraction half of common.py are deleted at the end
  (common.py keeps `calculate_ability_damage`/`effective_cooldown` used elsewhere).

## Migration order (green suite + clean golden compare after every commit)

1. Land engine + slotlib alongside existing code; port the GENERIC path; verify with
   test_generic_parser.py + the 173-champion golden section.
2. Port champions simplest-first, one commit each: Anivia, Annie, Akali, Amumu, Ahri,
   Ashe, Kog'Maw, Vayne, Aatrox, Alistar, Ambessa, Akshan (last).
3. Repoint the ~5-8 tests that import module privates (test_aatrox.py imports
   `_extract_r_bonus_ad_percent`, `common.extract_leveling_damage`) — mechanical;
   hand-validated expected VALUES never change.
4. Delete dead code; update the /add-champion skill (new flow: nothing → slot map →
   custom slot fn).

Projected: ~3,100 lines (12 modules + common + generic_parser) → ~1,050, with adding a
champion = 2-file touch (module + registry line; conftest fixture optional).

## Sizing context: the roadmap is the FULL roster (170+ champions)

The design must be judged at N=173, not N=12. Consequences:

- **The generic path is the product.** Most champions should need NO file at all —
  `GENERIC_SLOTS` + the classifier must carry the median champion. Every improvement to
  auto-detection (attribute tiers, on-hit sniffing) pays 100+ champions at once; every
  champion that needs a spec file is a small failure of the generic path. Triage order
  when onboarding: generic → attr-override spec row → archetype map → custom fns.
- **Archetype reuse compounds.** At 12 champions the library looked borderline (~14
  archetypes); at 173 the Xerath/Lucian/Illaoi pattern (stress test) predicts heavy
  reuse. Keep the ≥2-users rule — it will be satisfied quickly and often.
- **Per-champion test files don't scale to 173.** The golden snapshot (all champions,
  stats + abilities) plus the generic-parser coverage test (≥95% parse with damage) are
  the primary safety net; hand-written test files are reserved for champions with custom
  specs. (Phase 5 should note this.)
- **Known blocked class (future work, NOT Phase 3):** multi-kit champions — weapon
  systems (Aphelios), subspell casters (Hwei), transformers (Jayce/Elise/Udyr/Kayn/
  Nidalee/Gnar) — are blocked by the fight engine's four-castable-slot assumption and
  app.py's Q/W/E/R cast-order validation, not by the parse layer. Reaching true full
  roster requires a "rotation engine multi-kit" workstream after this campaign.
  Stack-dependent kits (Nasus, Veigar, Senna, Kindred) are NOT blocked: stacks arrive
  as champion options.

## Stress-test amendments (whiteboarded Aphelios, Xerath, Lucian, Bel'Veth, Hwei, Illaoi)

Six-champion whiteboard against real JSON shapes produced four interface amendments:

1. **`casts` accepts int or attribute name** — Xerath R's recast count is itself leveling
   data ("Number of Recasts"), not a constant like Ahri's ×3.
2. **Within-phase ordering is map insertion order** (deterministic, declared), and
   `ctx.results` is readable within a phase; cross-slot dependents list after their
   dependency. Illaoi falsified the earlier "order within a phase is irrelevant" claim:
   her Q's only attribute is "Damage Increase" — Q is defined in terms of P's computed
   slam damage. Cross-PHASE ordering (BUFF before DAMAGE) remains engine-guaranteed.
3. **`source=(slot, index)` and `cooldown_from` are first-class factory params** — the
   JSON stores Hwei's subspells (Q entries 1-3 under a cooldown-bearing container at
   index 0) and Aphelios's five weapon Qs (entries 1-5) as multi-entry slots; Ambessa Q2
   already needed this informally.
4. **`ranks="level"` mode** — Aphelios's Q/W/E take no skill points; damage scales via
   per-level modifiers with rank pinned (the Aatrox-P mechanism generalized).

Confidence result: the ≥2-users archetype rule held — the stress test PROMOTED archetypes
(Lucian's Lightslinger joins Akshan's double-shot; Illaoi W is the third
on_hit_pct_health-with-floor user; Bel'Veth's modified autos likely join Ashe's
auto_attack_override) rather than breaking any.

Scope honesty: for weapon/subspell champions (Aphelios, Hwei) the parse layer is NOT the
binding constraint — app.py validates cast order as a Q/W/E/R permutation and the
rotation engine assumes four castable slots. Product-level rotation/UI work for such
kits is an explicit non-goal of Phase 3. Prose-sourced values (Lucian R shot count,
passive ratio; Aphelios weapon behaviors) remain custom-fn territory, per the
data-vs-behavior boundary.

## Alternatives considered

- Pure declarative spec DSL (Design A): most uniform, but invents a config language with
  string-keyed function registries — debugging happens inside the engine, and stringly
  references are the weakest navigability. Rejected as primary; its options-as-data idea
  is adopted.
- Generic engine + champion-level prepare/adjust hooks (Design B): least machinery, but
  hooks hand-roll similar on-hit entries per champion, leaving cross-champion duplication
  (Vayne W / Kog'Maw W / Aatrox P) unsolved. Rejected as primary; its attribute-table and
  zero-damage-slot findings are adopted.
