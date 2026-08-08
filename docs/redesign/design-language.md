# Scryglass redesign — design language

Distilled from the approved Claude Design mock (options 2a/2b). `target-2a.html`
is the canonical rendering; when this document and that file disagree, the file wins.

## Layout concept

One screen, two permanent regions:

- **Setup rail (left, dark `#0a1712`)** — a numbered wizard that is always visible:
  1 Champion, 2 Roster, 3 Builds, then a CONSTRAINTS block (gold, objective,
  window) and the "Find best buy" action. Collapsed width 236px (2a). A step
  expands **in place**, widening the rail to ~404px (2b) while the duel canvas
  stays live but dimmed (`opacity:.55`) with the delta strip reading RECALCULATING.
- **Duel canvas (right, cream `#f6f2df`)** — three stacked bands:
  1. **Verdict strip** (dark `#10201b`): Build A TDD left, DELTA center
     (`+158`, "B WINS · 14.6% · −300g"), Build B TDD right. Numerals 800/42px.
  2. **Mirrored builds**: A's slots left-aligned, B's mirrored right-aligned
     (`flex-direction:row-reverse`), around a center **delta spine** (268px,
     `#e0efd9`): per-metric A/B values with signed divergence bars from a
     center axis — green toward the winner, red toward the loser.
  3. **Fight timeline** (`#f2f6ea`): cumulative damage polylines for A and B,
     vertical cast markers (E/Q/R/W/Q/AA) with timestamps, end-value legend
     right, "Open event ledger" action.

## Palette

| Token | Value | Use |
|---|---|---|
| page wash | `#eae6d6` | page background behind the app card |
| paper | `#f6f2df` | canvas surface, buttons on dark |
| paper tint | `#f2f6ea` | timeline band |
| spine green | `#e0efd9` | delta spine column, light item-icon hatch (with `#d2e6c9`) |
| rail | `#0a1712` | setup rail background |
| rail active | `#122720` | active step background, rail chips |
| rail card | `#0f2119` | roster card in expanded step |
| rail chip | `#152d25` | item boxes, insight callout on dark |
| header band | `#10201b` | verdict strip, dark hatch base (`#183028`/`#1e3a30`) |
| ink | `#10201b` | primary text on light |
| ink soft | `#23443a` | secondary text on light |
| ink muted | `#3c6558` | labels, mono data, Build A line color |
| cream ink | `#f6f2df` | primary text on dark (alphas `.6–.78` for hierarchy) |
| win green | `#1f6f4e` | Build B line, winner bars/values on light |
| win green dark | `#7fd3a5` | winner accents on dark (delta, active step) |
| lose red | `#b4432c` | loser bars on light, enemy accent border |
| lose red dark | `#e08a72` | loser accents on dark, enemy ability keys |
| line light | `rgba(22,72,58,.14/.18/.24/.3)` | hairlines on light |
| line dark | `rgba(246,242,223,.08/.12/.2)` | hairlines on dark |

Semantics: green = winning/better, red = losing/worse, **never the only carrier**
(values and A/B position always accompany color). Enemy = red left-border accent;
active/selected = `#7fd3a5` inset 3px left bar on dark.

## Type

- **Manrope** (400–800) for everything except data labels.
- **Mono** (`ui-monospace, Menlo, monospace`) for data annotations: patch number,
  stat lines, timestamps, gold, ranks.
- Micro-labels: 700–800, 9–10px, uppercase, letter-spacing `.12–.16em`.
- Hero numerals: 800, 42–46px, letter-spacing `-.03em`, `TDD` unit in 13px mono.
- Body/controls: 11–13px, weights 600–800. The UI is dense on purpose.

## Shape and texture

- Radius ~2px everywhere — near-square, instrument-like. 1px borders, hairline dividers.
- Placeholder/icon texture: 135° repeating hatch (`repeating-linear-gradient`).
  In production these cells hold real champion/item art (Data Dragon sprites, as today).
- Primary action on dark = solid paper button (`#f6f2df` bg, dark text).
  Secondary = 1px outlined. No shadows inside the app; one soft shadow under the app card.
- Charts: plain SVG polylines — A `#3c6558` 2px, B `#1f6f4e` 3px; no fills, no easing tricks.

## Voice

Labels are terse and analytical ("B WINS · 14.6% · −300g", "1 ENEMY · 0 ALLIES",
"ITEMS · AFFECTS YOUR BIS"). Insight callouts are one sentence, concrete, and name
the mechanic ("Aatrox's 49 MR and Death's Dance push your best fifth slot from
Void Staff to Shadowflame."). No tutorial prose on the main surface.
