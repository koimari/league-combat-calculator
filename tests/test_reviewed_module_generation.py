"""Gate the checked-in generated packet modules against what the generator emits.

The generator used to write module source as raw text, so its 173 modules were
never black-clean and every regeneration re-dirtied them. These tests pin the
rendering so that drift fails here instead of in a formatter run.
"""

import json
from pathlib import Path

import black

from scripts.build_reviewed_modules import _option_keys, _render_module, _slug

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "src" / "calculator" / "champions" / "generated"


def _packets() -> dict:
    return json.loads(
        (ROOT / "static" / "reviewed-packets.json").read_text(encoding="utf-8")
    )


def test_checked_in_modules_match_the_generator_output():
    """Every generated module is byte-identical to a fresh render."""
    champions = _packets()["champions"]
    assert champions, "reviewed-packets.json carries no champions"
    for name, entry in champions.items():
        path = GENERATED / f"{_slug(name)}.py"
        assert path.exists(), f"missing generated module for {name}"
        expected = _render_module(name, _option_keys(entry["slots"]))
        assert path.read_text(encoding="utf-8") == expected, f"{name} module is stale"


def test_rendered_modules_are_black_clean():
    """The renderer's output survives black unchanged, so `black --check` stays green."""
    champions = _packets()["champions"]
    mode = black.Mode()
    for name, entry in champions.items():
        rendered = _render_module(name, _option_keys(entry["slots"]))
        assert rendered == black.format_str(
            rendered, mode=mode
        ), f"{name} render is not black-clean"


def test_render_preserves_the_champion_name_and_option_keys():
    """Names with punctuation still round-trip, and variant slots emit their option comment."""
    rendered = _render_module("Nunu & Willump", [])
    assert "build_packet_module(" in rendered
    assert "Nunu & Willump" in rendered
    assert "Packet option keys" not in rendered

    with_options = _render_module("Aphelios", ["q_variant", "r_variant"])
    assert (
        '# Packet option keys consumed by packet_module: ["q_variant", "r_variant"]'
        in with_options
    )


def test_option_keys_only_reports_variant_slots():
    slots = {
        "Q": {"kind": "variants"},
        "W": {"kind": "packet"},
        "R": {"kind": "variants"},
        "E": {"kind": "no_damage"},
    }
    assert _option_keys(slots) == ["q_variant", "r_variant"]


def test_slug_matches_the_checked_in_filenames():
    assert _slug("Aatrox") == "aatrox"
    assert _slug("K'Sante") == "k_sante"
    assert _slug("Nunu & Willump") == "nunu_willump"
