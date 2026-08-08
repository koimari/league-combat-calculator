# UI redesign reference pack

The finished design references for the Scryglass frontend rebuild (branch `ui-redesign`).
Everything needed to implement the redesign is in this folder — the original
Claude Design handoff bundle is not required.

| File | What it is |
|---|---|
| `kickoff-prompt.md` | The prompt that starts an implementation session. Start here. |
| `target-2a.html` | Approved mock, resting state: rail collapsed, duel gets the full canvas. Standalone — open in a browser at ≥1500px. |
| `target-2b.html` | Approved mock, Roster step expanded in place; duel dimmed but live behind it. |
| `design-language.md` | Distilled visual system: layout concept, palette tokens, type, shape, voice. |
| `gap-ledger.md` | Every current frontend feature mapped to its home in the new design, plus the four locked scope decisions. |

Provenance: options 2a/2b of a Claude Design exploration (turn 2 of
"Scryglass Redesign", 2026-08-08), chosen by Matthew as the final direction —
1c's mirrored duel layout on 1b's wizard rail. The target HTML files are faithful
standalone extractions with the design tool's template placeholders resolved
using its own mock data. Discarded explorations (1a workspace tabs, 1b dark
console, 1c standalone duel) intentionally omitted; two idioms from them are
referenced by the ledger where the mock has no coverage (1a's keystone slot chip,
1c's gold-delta spine footer).
