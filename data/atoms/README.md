# data/atoms — fundamental behavior atoms (WS3)

The atomic catalog: every champion mechanic decomposed into typed behavior
atoms with dual provenance (wiki page + game binary). Schema:
`atoms.schema.json`. Per-champion atom files are gitignored (regenerable from
`data/bin`); `atom-summary.json` and the Vladimir sample are tracked.

Current seed (extracted from all 203 champion CharacterRecords):

| Family | Champions |
|---|---|
| buff | 194 |
| crowd_control | 105 |
| damage | 136 |
| heal | 27 |
| shield | 60 |
| resource | 1 |

Extraction is name-pattern based (seed); the next step refines classification
using the wiki mechanics pages and the binary mDataValues for exact parameters.
