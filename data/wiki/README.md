# data/wiki — full wiki article inventory

`article-index.json` — the complete namespace-0 article inventory of
https://wiki.leagueoflegends.com/en-us (4,231 non-redirect articles), each
with pageid, wikitext length, and category list. This is the map for the
full-wiki ingestion (WS1): per-family parsers follow the lolstaticdata
pattern, since the wiki is template-heavy (content lives in templates, raw
wikitext is thin).

Rebuild:
    python scripts/decompose_wiki.py --index

`league-wiki.sqlite3` (gitignored) is the revision index the reviewed-packet
gate reads: one `pages` row per namespace-0 page with its current revision id
and timestamp, redirects included. It carries no wikitext, so the
`league-wiki-query` CLI cannot read it.

Rebuild:
    python scripts/decompose_wiki.py --wiki-db

Raw wikitext fetches go to `data/wiki-raw/` (gitignored, on demand).
