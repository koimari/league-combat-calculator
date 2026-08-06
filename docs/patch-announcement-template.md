# Patch-Day Announcement Template (P0d)

Fill in and post to the beta channel on patch day. Two posts: an early
"re-cert in flight" (runbook Step 0) and a final "re-cert complete"
(runbook Step 5). The early post must go out within the detection SLA
(< 4h of patch deploy).

## Early post (Step 0 — detection)

```
📦 Patch <16.16> detected — re-certifying

- Live game patch: <16.16> (detected <2026-08-19T10:00Z>, <1h> after deploy)
- What changed (patch notes): <summary of champion/item changes we model>
- Stale flags: <N> items, <M> champions (STALE badges will show on those)
- SLA: triage < 24h, full re-cert < 72h from patch deploy
- Until re-cert completes, numbers for stale champions/items are NOT trusted.
```

## Final post (Step 5 — re-cert complete)

```
✅ Patch <16.16> re-cert complete

- Staleness: 0 champions, 0 items stale (regression re-run, stale: false)
- Re-certified: <list of items/champions with new values>
- Boundary-documented: <list of values intentionally not modeled, with reasons>
- New items: <names + modeled passives>
- Golden baseline re-captured; every diff explained in <commit sha>
- Issues closed: <#n — gated by scripts/issue_gate.py>
- Known limitations: <known-degraded wiki parses, unmodeled mechanics>

Changelog highlights:
- <one line per user-visible change — see format below>
```

## Changelog format

- One line per user-visible change: `[Type] Scope: what changed`.
- Types: `[buff]`, `[nerf]`, `[rework]`, `[new]`, `[fix]`, `[data]`,
  `[boundary]`.
- Examples:
  - `[data] Items: Statikk Shiv crit chance updated to 20% (patch 16.16).`
  - `[fix] Champions: Aurelion Sol Q cooldown re-pinned to game files.`
  - `[boundary] Items: Hullbreaker melee/ranged split remains unmodeled
    (documented in item-source reconciliation).`
