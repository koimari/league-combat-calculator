"""Tests for lolstaticdata wiki parser — specifically champions that set nvalues=None."""

import sys
from pathlib import Path

import pytest

# Add the vendored lolstaticdata to path
_LOLSTATICDATA_ROOT = (
    Path(__file__).resolve().parent.parent / "vendor" / "lolstaticdata"
)
sys.path.insert(0, str(_LOLSTATICDATA_ROOT))

# Apply the Windows download_soup patch before importing the parser
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from lolstaticdata.champions.pull_champions_wiki import LolWikiDataHandler

import calculator.data_updater  # noqa: F401  — triggers the monkey-patch

# Champions that have nvalues=None in the parser
NVALUES_NONE_CHAMPIONS = ["Heimerdinger", "Sona", "Karma", "Nidalee"]

# The parser reads the vendored scraper's gitignored page cache
# (vendor/lolstaticdata/__cache__).  When it is absent (CI) the handler
# falls back to a live wiki fetch, which is nondeterministic and rate-limit
# prone -- skip instead, per the repo's absence-guard convention.  The test
# runs fully on any machine that has pulled wiki data (local / patch day).
_WIKI_CACHE = _LOLSTATICDATA_ROOT / "__cache__"


@pytest.mark.parametrize("champion_name", NVALUES_NONE_CHAMPIONS)
def test_champion_with_none_nvalues_parses_successfully(champion_name: str) -> None:
    """Champions with nvalues=None must not crash the parser.

    These champions have non-standard ability rank structures and the parser
    sets nvalues=None.  All downstream code must handle None gracefully
    instead of passing it to range().
    """
    if not _WIKI_CACHE.is_dir():
        pytest.skip("vendor wiki page cache absent (gitignored; CI has no copy)")
    handler = LolWikiDataHandler(
        use_cache=True,
        target_champion=champion_name,
        process_stats=True,
        process_abilities=True,
        process_skins=False,
    )
    champions = list(handler.get_champions())
    assert len(champions) >= 1, f"{champion_name} should be parsed successfully"

    champion = champions[0]
    assert champion.name == champion_name
    assert champion.stats is not None
