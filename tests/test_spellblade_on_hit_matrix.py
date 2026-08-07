"""Pin the wiki on-hit application matrix to reviewed module declarations.

The "attack or not attack" classification (Bel'Veth P, Ezreal Q, Warwick Q,
...) is the spellblade contract: abilities that apply item on-hits consume
spellblade charges and advance on-hit counters.  A patch-day re-parse can
silently flip these classifications; this test regenerates the ground truth
from data/champions.json (scripts/build_onhit_matrix.py) and asserts every
wiki-documented on-hit-applying ability of a reviewed champion is either
declared in its module, rides the auto stream, or is explicitly out of scope.
"""

import json
from pathlib import Path

import pytest

from src.calculator.stats import calculate_total_stats
from src.calculator.champions import parse_champion_abilities

ROOT = Path(__file__).resolve().parents[1]
MATRIX = json.loads((ROOT / "data" / "onhit-matrix.json").read_text(encoding="utf-8"))
DATA = json.loads((ROOT / "data" / "champions.json").read_text(encoding="utf-8"))

# Hand-reviewed expectation table.  status:
#   "declared"    — module must declare applies_item_on_hits with this eff
#   "override"    — module declares a game-verified effectiveness different
#                   from the wiki text (e.g. Bel'Veth passive-wide 75% rule)
#   "auto_stream" — the ability rides the basic-attack stream (on-hit via autos)
#   "out_of_scope"— the slot is not modeled by the module
#   "generic"     — champion has no reviewed module (generic path)
# effectiveness is the wiki reading; module_eff overrides for "override".
REVIEWED = {
    "Akshan": {
        "P": {"status": "auto_stream", "eff": 1.0, "on_attack": True},
        "E": {"status": "declared", "eff": 0.25},
    },
    "Aphelios": {
        "Q": {
            "status": "declared",
            "eff": 0.25,
            "parse_options": {"aphelios_main_weapon": "severum"},
            "note": "Onslaught (severum) 0.25; Duskwave (calibrum) 1.0 via module wrap",
        },
        "R": {
            "status": "out_of_scope",
            "eff": 1.0,
            "note": "Moonlight Vigil follow-up attacks unmodeled",
        },
    },
    "Ashe": {
        "Q": {
            "status": "auto_stream",
            "eff": 1.0,
            "note": "flurry autos; on-hit once per flurry",
        }
    },
    "Belveth": {
        "Q": {
            "status": "declared",
            "eff": 1.0,
            "note": "26.15 removed the 75% on-hit rider reduction (patch notes: Undocumented/Removed)",
        }
    },
    "Briar": {"Q": {"status": "declared", "eff": 1.0, "on_attack": True}},
    "Elise": {"Q": {"status": "declared", "eff": 1.0, "parse_options": {"q_form": 1}}},
    "Evelynn": {"E": {"status": "declared", "eff": 1.0}},
    "Ezreal": {"Q": {"status": "declared", "eff": 1.0, "on_attack": True}},
    "Fiora": {"Q": {"status": "declared", "eff": 1.0}},
    "Fizz": {"Q": {"status": "declared", "eff": 1.0}},
    "Gangplank": {"Q": {"status": "declared", "eff": 1.0, "on_attack": True}},
    "Graves": {
        "P": {
            "status": "auto_stream",
            "eff": 1.0,
            "note": "pellet autos; first pellet applies on-hit",
        }
    },
    "Irelia": {"Q": {"status": "declared", "eff": 1.0}},
    "Katarina": {
        "P": {"status": "declared", "eff": 1.0},
        "E": {"status": "declared", "eff": 1.0},
    },
    "Kayle": {"E": {"status": "declared", "eff": 1.0}},
    "Locke": {"E": {"status": "declared", "eff": 1.0}},
    "Lucian": {
        "P": {
            "status": "out_of_scope",
            "eff": 1.0,
            "note": "Lightslinger second shot unmodeled",
        }
    },
    "MasterYi": {
        "P": {"status": "generic", "eff": 1.0},
        "Q": {"status": "generic", "eff": 0.75},
    },
    "MissFortune": {"Q": {"status": "generic", "eff": 1.0}},
    "Nocturne": {"P": {"status": "declared", "eff": 1.0}},
    "Pantheon": {"W": {"status": "out_of_scope", "eff": 1.0}},
    "Renekton": {"W": {"status": "declared", "eff": 1.0, "hits": 2}},
    "Samira": {"P": {"status": "out_of_scope", "eff": 1.0}},
    "Senna": {"Q": {"status": "declared", "eff": 1.0, "on_attack": True}},
    "Smolder": {"Q": {"status": "declared", "eff": 1.0, "on_attack": True}},
    "Twitch": {"R": {"status": "auto_stream", "eff": 1.0, "note": "bolts ride autos"}},
    "Viego": {
        "Q": {"status": "declared", "eff": 1.0},
        "R": {"status": "declared", "eff": 1.0},
    },
    "Volibear": {"W": {"status": "out_of_scope", "eff": 1.0}},
    "Warwick": {
        "Q": {"status": "declared", "eff": 1.0, "on_attack": True},
        "R": {
            "status": "out_of_scope",
            "eff": 1.0,
            "note": "Infinite Duress unmodeled",
        },
    },
    "Yunara": {"Q": {"status": "declared", "eff": 0.3}},
    "Zaahen": {"Q": {"status": "declared", "eff": 1.0}},
    "Zeri": {
        "E": {
            "status": "auto_stream",
            "eff": 1.0,
            "note": "zaps ride autos; first target on-hit",
        }
    },
}


def _data_name(name: str) -> str:
    for key in DATA:
        if key.lower() == name.lower():
            return key
    return name


@pytest.mark.parametrize("champion", sorted(MATRIX["champions"]))
def test_every_wiki_on_hit_ability_is_reviewed(champion):
    """The wiki matrix and the reviewed table must agree (both directions)."""
    matrix_slots = {row["slot"] for row in MATRIX["champions"][champion]}
    reviewed = REVIEWED.get(champion)
    assert reviewed is not None, f"{champion} has wiki on-hit abilities but no review"
    reviewed_slots = set(reviewed)
    assert (
        matrix_slots == reviewed_slots
    ), f"{champion}: matrix slots {sorted(matrix_slots)} vs reviewed {sorted(reviewed_slots)}"


@pytest.mark.parametrize("champion", sorted(REVIEWED))
@pytest.mark.parametrize("slot", ["P", "Q", "W", "E", "R"])
def test_declared_on_hit_application_reaches_the_entry(champion, slot):
    spec = REVIEWED[champion].get(slot)
    if spec is None or spec["status"] not in {"declared", "override"}:
        return
    champion_data = DATA[_data_name(champion)]
    stats = calculate_total_stats(champion_data, 9, [])
    options = spec.get("parse_options") or {}
    abilities = parse_champion_abilities(
        champion_data,
        9,
        stats.get("ability_power", 0.0),
        champion_stats=stats,
        champion_options=options,
    )
    entry = abilities.get(slot) or (abilities.get("passive") if slot == "P" else None)
    assert entry is not None, f"{champion} {slot} produced no entry"
    declared = entry.get("applies_item_on_hits")
    assert declared is not None, f"{champion} {slot} lacks applies_item_on_hits"
    expected = spec.get("module_eff", spec["eff"])
    assert (
        abs(declared["effectiveness"] - expected) < 1e-9
    ), f"{champion} {slot}: declared {declared['effectiveness']} != {expected}"
    if spec.get("on_attack"):
        assert "on_attack" in declared.get(
            "triggers", ()
        ), f"{champion} {slot}: missing on_attack trigger"
