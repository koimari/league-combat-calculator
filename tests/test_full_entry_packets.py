"""Every full-entry reviewed champion: its source receipts and its packet.

A full-entry module is one whose first source is the League Wiki *parent
entry* — the receipt that says the whole page was reviewed rather than one
ability template (``docs/full-wiki-entry-review-requirement.md``).  The
roster below is that population, written down so it cannot shrink in
silence; the tests derive everything else from the modules themselves.

Per-champion packet facts live in that champion's own test file.
"""

import urllib.parse

import pytest

from src.calculator.champions import (
    _CHAMPION_MODULES,
    engine_registration_kind,
    get_champion_module_contract,
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.data_fetcher import get_champion
from tests import row_review

FULL_ENTRY = (
    "Draven",
    "Ekko",
    "Elise",
    "Evelynn",
    "Fiddlesticks",
    "Fiora",
    "Fizz",
    "Gangplank",
    "Garen",
    "Gragas",
    "Graves",
    "Gwen",
    "Hecarim",
    "Heimerdinger",
    "Hwei",
    "Illaoi",
    "Irelia",
    "Ivern",
    "Janna",
    "Jax",
    "Jhin",
    "K'Sante",
    "Karma",
    "Kassadin",
    "Katarina",
    "Kayle",
    "Kayn",
    "Kennen",
    "Kha'Zix",
    "Kindred",
    "Kled",
    "LeBlanc",
    "Lee Sin",
    "Leona",
    "Lillia",
    "Locke",
    "Lucian",
    "Lulu",
    "Lux",
    "Malphite",
    "Malzahar",
    "Maokai",
    "Master Yi",
    "Mel",
    "Milio",
    "Miss Fortune",
    "Mordekaiser",
    "Morgana",
    "Naafiri",
    "Nami",
    "Nasus",
    "Nautilus",
    "Neeko",
    "Nidalee",
    "Nilah",
    "Nocturne",
    "Nunu & Willump",
    "Olaf",
    "Orianna",
    "Ornn",
    "Pantheon",
    "Poppy",
    "Pyke",
    "Quinn",
    "Rammus",
    "Rek'Sai",
    "Rell",
    "Renata Glasc",
    "Renekton",
    "Rengar",
    "Riven",
    "Rumble",
    "Ryze",
    "Samira",
    "Sejuani",
    "Senna",
    "Seraphine",
    "Sett",
    "Shaco",
    "Singed",
    "Sion",
    "Sivir",
    "Skarner",
    "Smolder",
    "Sona",
    "Swain",
    "Sylas",
    "Talon",
    "Taric",
    "Teemo",
    "Thresh",
    "Tristana",
    "Trundle",
    "Tryndamere",
    "Twisted Fate",
    "Twitch",
    "Udyr",
    "Urgot",
    "Varus",
    "Veigar",
    "Vel'Koz",
    "Vex",
    "Viego",
    "Viktor",
    "Vladimir",
    "Volibear",
    "Warwick",
    "Xayah",
    "Xerath",
    "Xin Zhao",
    "Yasuo",
    "Yone",
    "Yorick",
    "Yunara",
    "Yuumi",
    "Zaahen",
    "Zac",
    "Zed",
    "Zeri",
    "Zilean",
    "Zoe",
    "Zyra",
)

_SLOTS = {"passive", "Q", "W", "E", "R"}


def _module(name: str):
    return _CHAMPION_MODULES[name]


def _armed_options(name: str) -> dict:
    """Every declared option at the value that arms the row it gates.

    A packet slot the module hides behind an option (Ekko's Resonance
    stacks, Elise's spider form, Fiora's vitals) prices nothing at the
    default, so a coverage sweep that never arms them proves nothing.
    """
    armed: dict[str, object] = {}
    for option in get_champion_options_meta(name)["options"]:
        kind, default = option["type"], option["default"]
        if kind == "bool":
            armed[option["key"]] = True
        elif isinstance(default, (int, float)) and not isinstance(default, bool):
            armed[option["key"]] = option.get("max", default)
        else:
            armed[option["key"]] = default
    return armed


def test_the_roster_is_the_population_the_modules_declare() -> None:
    """The list above and the tree cannot disagree about who was reviewed."""
    declared = tuple(
        sorted(
            name
            for name in _CHAMPION_MODULES
            if str(_module(name).SOURCES[0]["label"]).endswith("parent entry")
        )
    )
    assert declared == FULL_ENTRY


@pytest.mark.parametrize("name", FULL_ENTRY)
def test_a_full_entry_module_cites_its_parent_page_and_every_ability(name) -> None:
    """The parent entry leads, and an ability template follows for each slot."""
    module = _module(name)
    assert engine_registration_kind(name) == "reviewed_module"
    parent = module.SOURCES[0]
    assert parent["label"].endswith("parent entry")
    page = urllib.parse.unquote(parent["url"].rsplit("/", 1)[-1]).replace("_", " ")
    assert page == name, f"{name}'s parent entry cites {page!r}"
    assert len(module.SOURCES) >= len(_SLOTS)


@pytest.mark.parametrize("name", FULL_ENTRY)
def test_a_full_entry_packet_prices_every_slot(name) -> None:
    """With its own options armed, every slot the contract models authors a typed row.

    A slot the contract prices through a ``COVERAGE_CHANNELS`` channel is
    modeled without a packet row of its own — the revive, shield or heal
    receipt is the row — so the packet is not asked for one.
    """
    contract = get_champion_module_contract(name)
    modeled = {
        "passive" if slot == "P" else slot
        for slot, state in contract.coverage.items()
        if state == "modeled" and slot not in contract.coverage_channels
    }
    parsed = parse_champion_abilities(
        get_champion(name),
        18,
        row_review.STATS["ability_power"],
        ability_ranks=dict(row_review.RANKS),
        champion_options=_armed_options(name),
        champion_stats=dict(row_review.STATS),
        target_stats=dict(row_review.TARGET),
    )
    assert modeled <= set(parsed), f"{name} prices no {sorted(modeled - set(parsed))}"
    for slot, entry in parsed.items():
        assert "parts" in entry, f"{name} {slot} authors no parts"
        assert "damage_type" in entry, f"{name} {slot} has no damage type"
