import re
from bs4 import BeautifulSoup
from pathlib import Path

import src.app as app_module


def test_level_controls_use_level_delta_path_contract():
    page = app_module.app.test_client().get("/").get_data(as_text=True)
    soup = BeautifulSoup(page, "html.parser")
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    level_buttons = soup.select("button[data-level-delta]")
    assert len(level_buttons) >= 2
    assert "data-level-delta" in level_buttons[0].attrs
    assert "data-level-path" in level_buttons[0].attrs
    assert 'data-level="' not in page

    for button in level_buttons:
        assert button.get("aria-label") in {"Decrease level", "Increase level"}
        assert button["data-level-delta"] in {"-1", "1"}
        assert button["data-level-path"].startswith("attacker.level")

    assert 'data-level-path="attacker.level" data-level-delta="-1"' in page
    assert 'data-level-path="attacker.level" data-level-delta="1"' in page
    assert len(re.findall(r'data-level-delta="[^"]+"', page)) >= 2

    assert 'closest("[data-level-delta]")' in source
    assert "data-level-delta]" in source
    assert "levelButton.dataset.levelPath || levelButton.dataset.level" in source
    assert (
        "const rosterMatch = levelPath.match(/^(targets|allies)\\.(\\d+)\\.level$/)"
        in source
    )
    assert 'data-level-path="${root}.${index}.level"' in source
    assert (
        "setPath(levelPath, Math.max(1, Math.min(cap, Number(pathValue(levelPath)) + Number(levelButton.dataset.levelDelta || levelButton.dataset.delta || 0))))"
        in source
    )


def test_level_controls_roster_path_selector_scope_is_attacker_specific():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert (
        "document.querySelectorAll('button[data-level-path=\"attacker.level\"]')"
        in source
    )
    assert 'data-level-path="${root}.${index}.level"' in source
    assert 'data-level-path="attacker.level"' in source
