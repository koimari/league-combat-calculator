# Scoreboard autofill

Paste a broadcast or in-game scoreboard screenshot on the page, or pick a file
from the Roster step's **Read a scoreboard screenshot** button. The page reads
the ten champions and their items and loads them as attacker, enemies and
allies through `loadSharedBuildIntoAnalyst`, the door a shared build comes in
by. A scoreboard shows no runes, ability ranks or levels. The read keeps the
current attacker level and resets the rest, as a shared build does.

## Where each piece lives

| piece | home |
|---|---|
| reference art, one cell per cached champion and item | `static/icon-sprite.webp` and `static/icon-sprite.json`, written by `scripts/build_icon_sprite.py` in the rebuild phase of `patch_update.py run` |
| matcher (`ScoreboardVision`, DOM-free) and page wiring | `static/js/scoreboard.js` |
| review dialog | `#scoreboardDialog` in `templates/index.html`, styles under "scoreboard reader dialog" in `static/css/style.css` |
| Node harness that tests and tooling read through | `tests/js/scoreboard_harness.mjs` |
| Node harness that drives the paste handler with files the reader refuses (over `MAX_SCREENSHOT_MB`, not an image) | `tests/js/scoreboard_paste_harness.mjs` over `tests/fixtures/scoreboard/paste_cases.json` |
| corpus frames and labels | `tests/fixtures/scoreboard/`, held by `tests/test_scoreboard_vision.py` |
| corpus tooling: read, scan, grab, label | `scripts/scoreboard_corpus.py` |

## How a read works

The matcher compares every cell to the sprite by normalized cross-correlation
of an area-resampled RGB fingerprint: 4x4 projected to 12 dimensions to
search, 8x8 projected to 24 to shortlist, 24x24 exact to decide. The search is
anchored. It finds the strongest portrait anywhere, then its column for
teammates, then one row for an opponent and that opponent's column, then each
row band for items at one shared size. Grid fills recover what the searches
missed: rows sit on a uniform pitch, a whole number of pitches apart when a
row between them was missed, strips sit on a uniform pitch, and the matcher
classifies each empty slot in place. A slot a crop cuts up to `EDGE_OVERHANG`
of a cell off is read where it is, the pixels past the edge repeating the edge.

Every tuned number is a named constant in the block at the top of
`scoreboard.js`, each with the reason beside it. They were set on 1080p LCK
frames, whose portraits are 24 to 36 px. A frame whose anchor comes out larger
than `PORTRAIT.typical`, a zoomed crop of the panel, is resampled to that size
and read there, so the constants meet every frame at the scale they were tuned
at. The corpus test holds them at what the tree reads and reads one crop at
twice its size. If a new overlay fails, add its frames to the corpus before
you move one.

## Grow the corpus

Download the VoD once with yt-dlp, then scan, grab, label and verify:

```
yt-dlp -f "bv*[height=1080][ext=mp4]" -o "%(id)s-1080.%(ext)s" URL
python scripts/scoreboard_corpus.py scan ID-1080.mp4
python scripts/scoreboard_corpus.py grab ID-1080.mp4 --at T --out tests/fixtures/scoreboard/<league>-<match>-T.jpg
python scripts/scoreboard_corpus.py label tests/fixtures/scoreboard/<frame> --league LEC --source youtube:ID@T
python scripts/scoreboard_corpus.py read tests/fixtures/scoreboard/<frame> --sheet sheet.png
```

`scan` reads every tenth second of the VoD and ranks frames by champions and
items found. It takes about 4 seconds per 1080p frame. A 480p stream puts
portraits below the 24 px floor in `PORTRAIT`, so scan the 1080p stream.

`label` writes the reader's rows into `labels.json` as a starting point. A
label is truth, not the reader's output. Check every pair on the contact sheet
from `read --sheet`, then edit `labels.json`: write `"?"` for an icon you
cannot name from the frame and `null` for an empty slot. The test holds
champions exact and items to `ITEM_FLOOR` read with at most `EXTRA_CEILING`
phantom, both ratcheted to what the tree reads.

## Known gaps

The corpus holds five 2026 LCK frames, one a 1361x399 crop with 55 px
portraits whose bottom row runs past the frame, and one 2026 LEC frame. A dead
player's greyed portrait is not read (the crop reads 9 of 10). LEC and LCS
share Riot's broadcast package, whose portraits carry a level badge over art
that is the square icon for some champions and a tight face crop for others;
the `badge` style in `PORTRAIT_STYLES` reads them, and the icon-only style is
tried first so LCK keeps its margins. A gold-difference label drawn over a
portrait still hides it: the LEC frame at `youtube:qHAn7zWJE_Q@1450` reads 8
of 10 and the LCS frame at `youtube:yDHo-UNcICo@1530` reads 8 of 10. The 2026
LPL panel (`youtube:dQpiSHdwgls@1290`) reads one portrait; its portraits are
smaller and ringed, and need their own look before a third style is added.
