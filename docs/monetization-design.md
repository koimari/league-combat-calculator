# Monetization & community design (P8)

Status: **design only — no implementation.**  This document scopes a premium
tier and community layer on top of the P4/P7 validation loop.  Nothing here
is built; every feature below is a proposal with the data dependencies and
compliance constraints called out.

## 1. Why monetization is credible now

The calculator's differentiation is *trust*: deterministic, source-pinned,
per-champion reviewed modules, an open validation loop (P7 receipts), and a
per-ability certainty label (P4).  That trust is the moat, and it is what a
premium tier can sell.  The pricing narrative is not "more items" — it is
"the numbers you can stake a ranked decision on, plus the community signal
that confirms them."

Validation loop dependency: every premium analytics surface consumes the
receipts written by `POST /api/receipts` (P7) and the certainty data served
by `GET /api/certainty` / `GET /api/not-modeled` (P4).  Premium cannot
launch before those endpoints are stable and the widget is shipping real
receipts (target: ≥ 5 receipts/champion for the bias flag to engage, per
the P7 `+-15% / n>=5` rule).

## 2. Tiers

### Free (today, minus caps that go into effect at launch)

| Cap | Free |
| --- | --- |
| Saved builds | 20 |
| Share links | 5 active |
| Comparisons | A/B only |
| Roster | current limits (max 5 enemies / 4 allies) |
| Validation dashboard | read-only, per-champion you submit to |
| Certainty / not-modeled labels | yes — free trust is the funnel |

### Premium ("Scryglass Pro")

| Feature | Free | Pro |
| --- | --- | --- |
| Saved builds | 20 | unlimited |
| Share links | 5 active | unlimited + custom slugs |
| Build comparisons | A/B | A/B/C + multi-champion curves |
| Export | — | CSV/JSON of fight ledger + receipts |
| Validation dashboards | own-champion bias | all champions, filters, alerting |
| Meta aggregation | — | patch-level build stats (Riot-compliant) |
| Community gallery | browse | create + featured placement |

## 3. Premium feature detail

### 3.1 Advanced comparisons
- **A/B/C+ builds** in one scenario: extend the result renderer from two
  columns to N with the same event ledger and per-source breakdown.  Pure
  frontend + `GET /api/calculate` fan-out; no new engine work.
- **Multi-champion curves**: comparison-curve output already exists per
  champion (`include_crossover`); Pro unlocks curve overlay across
  champions in one chart.
- **Patch-pinned replays**: re-run a saved build against the previous
  patch's pinned wiki cache (P3 already pins `data/staleness.json` per
  patch) to see "what this build would have done last patch".
- Data dependency: saved builds (`builds` table, P6) and per-patch cache
  pinning (P3).

### 3.2 Unlimited builds / shares
- Builds and `share_links` are already first-class rows (P6).  The cap is a
  lookup on `builds.champion = user` — no schema change needed, just an
  ownership column (see §7).  Custom slugs are `share_links.slug`; premium
  validates slug uniqueness and profanity.

### 3.3 Validation dashboards
Consumes `GET /api/validation?champion=&limit=`, `GET /api/validation/champions`,
and `GET /api/certainty?champion=`:
- **Per-champion bias time series**: signed mean % error per patch, with the
  `+-15% / n>=5` flag drawn as a threshold band.
- **Systematic-error queue**: the flagged champions list becomes a triage
  queue ("these modules need a review ticket").
- **Source mix**: receipts split by `manual | combat_log | practice_tool`.
- **Certainty matrix**: the P4 per-slot exact/estimate/boundary grid across
  all reviewed champions — a "which numbers can I trust" heatmap.
- **Alerts** (Pro): email/webhook when a champion you play crosses the bias
  threshold or flips certainty.
- Data dependency: receipts table (P6/P7), certainty derivation (P4).  No
  new engine work.

### 3.4 Meta aggregation
The most commercially interesting surface and the most compliance-sensitive
(§5):
- **Patch-level build popularity**: from *public share links* and *saved
  builds* (anonymized), count how often each item set appears for a
  champion+role+objective.
- **Build match rate**: of receipts, the fraction where `matched=true`,
  bucketed by build fingerprint — "builds the community confirms match the
  game".
- **Certainty-weighted display**: aggregate numbers are shown with the P4
  certainty of the underlying champion module, never without it.
- Pro only, and always *derived aggregates* — never individual users, never
  match-identifying data.

## 4. Community features

### 4.1 Public shared-build gallery
- Share links are already public URLs (P6).  The gallery indexes them with
  consent: a share is listed only when the author opts in ("feature in
  gallery") or upgrades to Pro.
- Each gallery entry shows: build, champion/role/objective, patch,
  meta stats (views, copies, match-rate from receipts), certainty label
  (P4), and a **Verified** badge when the champion module is
  `reviewed_module` AND the build has ≥ 5 receipts with
  `bias <= 15%` — i.e. the P7 flag is the anti-badge.
- Sorting: newest / most viewed / highest match rate / most copied.
- Moderation: report button on every card; automated profanity + duplicate
  filters; a manual queue for anything flagged ≥ 3 times.

### 4.2 Build ratings
- Up/down vote per gallery build, one per signed-in account (anonymous
  votes counted but shown separately).
- **Ratings must never influence calculator output** — the engine remains
  deterministic and source-pinned; ratings are a community layer on top.
- Rating abuse: per-IP + per-account velocity caps; votes from accounts
  with zero receipts weigh 0.5× (receipt-weighted trust).
- Requires a lightweight auth identity beyond the current stateless session
  cookie (see §7 schema).

## 5. Riot-compliance constraints

These are hard rules for any aggregation, not suggestions:

1. **No official affiliation**: every page footer and the gallery must carry
   the standard Riot disclaimer (game data © Riot Games; not endorsed by
   Riot, Inc.).  Trademark use is nominative (identifying the game and
   champions), never as branding.
2. **No selling Riot's data**: the premium tier sells *our* computation,
   validation, and community features.  It cannot sell access to raw Riot
   game data or the wiki cache.  Derived aggregates over user-generated
   receipts are ours; the underlying champ/item formulas remain freely
   visible (free tier keeps the calculator fully functional).
3. **User-generated, not scraped**: receipt data comes from users pasting
   their own combat logs / observations (`manual | combat_log |
   practice_tool`).  No automated scraping of Riot's API or the live
   client.  The existing wiki cache pipeline is the only ingestion path and
   is governed by the existing patch-day process (P3).
4. **No match-level disclosure**: aggregation is patch+champion+build level
   only.  Never publish a single user's receipts, account names, or
   identifiable sequences of games.
5. **Client-safe sharing**: the share links stay manual; there is no
   auto-import into the game client (which Riot's policies prohibit for
   third-party tools).
6. **Review on policy change**: before GA, have the community-safety and
   legal pass documented in `docs/riot-compliance.md` (to be written when
   the gallery ships — design only here).

## 6. Pricing sketch

- **Free**: $0 — full calculator, certainty labels, own-champion validation.
- **Pro**: $4.99/mo or $39/yr (annual ≈ 35% off).  Includes everything in
  §3 + gallery creation + custom slugs.
- **Lifetime**: $99 one-time during beta as an early-trust play; may be
  withdrawn.
- **Why $4.99**: below the "expense report" threshold, above the
  "free app" noise floor; anchor against $9.99 comparison tools that do not
  offer validation.
- **Payments**: Stripe Checkout + webhooks; no card required for free tier;
  prorated refunds within 7 days; cancel-anytime self-serve.
- **Price anchoring**: the Pro upgrade prompt is contextual — shown at the
  validation dashboard and gallery, never inside the calculator result
  itself (the calculator stays trustworthy).
- **Free-to-Pro conversion hooks**: "your champion is flagged (±18% bias,
  9 receipts) — get Pro to see the fix queue and set alerts".

## 7. Schema / engineering notes (design only)

- Add `users` table (id, email, password-hash, pro_status, created_at) and
  `builds.owner_id` / `share_links.owner_id` nullable FKs; NULL = anonymous
  free row (current behavior unchanged).
- Add `gallery_entries` (share_link_id FK, patch, opted_in, created_at) and
  `build_ratings` (user_id, gallery_entry_id, value, created_at, unique
  (user, entry)).
- Alerts table: `validation_alerts` (user_id, champion, threshold, channel).
- All of the above are additive to the existing `db.py` models; no change
  to the engine or the calculation API.
- Rate limits: keep receipts on the `calculate` budget (§P7) so Pro cannot
  be used to farm engine time.

## 8. Metrics & rollout

North-star: **receipts per champion per patch** (the validation loop's fuel).
Secondary: activated Pro trials, gallery builds with ≥ 5 receipts, bias-flag
resolution time (flagged → module fix → unflag).

Phases:
1. **P7 now**: receipts + widget + systematic flags ship.
2. **P9 dashboard**: Pro-gated validation dashboards on existing endpoints
   (cheap, demonstrates value).
3. **Gallery beta**: opt-in public gallery + ratings, moderation tooling.
4. **Paid tier**: Stripe, caps on free tier, alerts, exports.
5. **Meta aggregation**: only after gallery volume and the compliance doc
   are in place.

## 9. Guardrails (things this design deliberately does NOT do)

- No paywalled *calculation correctness*: a champion's numbers are free
  whether exact or estimate.  Paying for accuracy would corrupt the trust
  brand.
- No ads inside calculator results.
- No purchase-driven bias: receipts, flags, and certainty are computed the
  same for free and Pro users.
- No "premium items" or content-gated game data: the wiki cache and pinned
  formulas stay fully open (`CLAUDE.md` pipeline rules unchanged).
