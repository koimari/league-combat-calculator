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
| corpus frames and labels | `tests/fixtures/scoreboard/`, held by `tests/test_scoreboard_vision.py` |
| corpus tooling: read, scan, grab, label | `scripts/scoreboard_corpus.py` |

## How a read works

The matcher compares every cell to the sprite by normalized cross-correlation
of an area-resampled RGB fingerprint: 4x4 projected to 12 dimensions to
search, 8x8 projected to 24 to shortlist, 24x24 exact to decide. The search is
anchored. It finds the strongest portrait anywhere, then its column for
teammates, then one row for an opponent and that opponent's column, then each
row band for items at one shared size. Grid fills recover what the searches
missed: rows sit on a uniform pitch, strips sit on a uniform pitch, and the
matcher classifies each empty slot in place.

The thresholds `MIN_SCORE`, `MIN_GAP`, `FILL_SCORE`, `FILL_GAP`, `SURE_FILL`
and `THUMB_GATE` in `scoreboard.js` were set on the LCK frames, and the corpus
test holds them. If a new overlay fails, add its frames to the corpus before
you move a threshold.

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
champions exact and items to at least 95% read with at most 5% phantom.
