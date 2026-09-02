"""Item atomizer per-effect correctness (issue #140).

The item domain of the unified Atomizer must:
- classify every passive/active from its OWN fragment text (never a
  whole-item blob), so the first passive cannot absorb later effects;
- dedup at emission by (atom_id, behavior) while preserving ALL per-effect
  evidence receipts;
- name the exact effect + keyword in every receipt.

These tests pin the issue fixture, the fixture classes from the findings
report (damage, heal, shield, crowd-control mobility, on-hit, burn, stats),
and add full-corpus gates: 0% silent later-position effects and a
provenance gate over all 324 items.
"""

import re
from pathlib import Path

from src.calculator.atomizer import split_effect_fragments
from src.calculator.atomizer_domains import (
    _ITEM_KEYWORDS,
    atomize_item,
)
from src.calculator.data_fetcher import fetch_item_data

ROOT = Path(__file__).resolve().parents[1]
KEYWORDS = {kw for kw, _, _ in _ITEM_KEYWORDS}


def _evidence_atoms(atoms, kind, ename):
    prefix = f"{kind}:{ename}@kw:"
    return [a for a in atoms if any(ev.startswith(prefix) for ev in a["evidence"])]


# ---------------------------------------------------------------------------
# Issue fixture + fixture classes
# ---------------------------------------------------------------------------


def test_issue_fixture_active_not_absorbed_by_passive():
    """The exact issue #140 fixture: shield passive + dash active.

    Both effects must emit atoms, each attributed to ITS OWN effect, and no
    atom's evidence may name the wrong effect.
    """
    item = {
        "name": "Test Buckler",
        "simpleDescription": "Grants a shield and lets you dash.",
        "riotDescription": "<mainText>Grants a shield. Dash to a target.</mainText>",
        "passives": [{"name": "Shield", "branches": ["Grants a shield."]}],
        "active": [{"name": "Dash", "branches": ["Dash to a target."]}],
    }
    atoms = atomize_item(item)
    evidence = {ev for atom in atoms for ev in atom["evidence"]}
    assert "passive:Shield@kw:shield" in evidence
    assert "active:Dash@kw:dash" in evidence

    shield_atoms = _evidence_atoms(atoms, "passive", "Shield")
    dash_atoms = _evidence_atoms(atoms, "active", "Dash")
    assert shield_atoms
    assert dash_atoms
    assert [a["atom_id"] for a in shield_atoms] == ["shield.flat"]
    assert [a["atom_id"] for a in dash_atoms] == ["control.dash"]
    # the active emits exactly one atom (issue body: "active atoms emitted: 0")
    assert len(dash_atoms) == 1
    # no atom's evidence names the wrong effect
    for atom in atoms:
        for ev in atom["evidence"]:
            assert ev in {"passive:Shield@kw:shield", "active:Dash@kw:dash"}, ev


def test_keyword_table_covers_fixture_classes():
    """The atomizer keyword table covers every fixture class from the
    findings report: damage, heal, shield, crowd-control mobility, on-hit,
    burn, stats."""
    fixtures = {
        "damage": (
            {
                "passives": [
                    {"name": "Smash", "branches": ["Deal 100 physical damage."]}
                ]
            },
            "damage.physical",
        ),
        "heal": (
            {
                "passives": [
                    {"name": "Vigor", "branches": ["Heal for 30% of damage dealt."]}
                ]
            },
            "heal.flat",
        ),
        "shield": (
            {"passives": [{"name": "Aegis", "branches": ["Grants a shield."]}]},
            "shield.flat",
        ),
        "crowd-control mobility": (
            {
                "passives": [
                    {"name": "Blitz", "branches": ["Dash to a target and slow them."]}
                ]
            },
            "control.dash",
        ),
        "on-hit": (
            {
                "passives": [
                    {"name": "Rend", "branches": ["Basic attacks apply on-hit damage."]}
                ]
            },
            "damage.on_hit",
        ),
        "burn": (
            {
                "passives": [
                    {
                        "name": "Cinder",
                        "branches": ["Ignite and burn enemies over 3 seconds."],
                    }
                ]
            },
            "damage.burn",
        ),
        "stats": (
            {
                "stats": {"attackDamage": {"flat": 30.0}},
                "passives": [{"name": "Edge", "branches": ["Deal bonus damage."]}],
            },
            "stat.attack_damage",
        ),
    }
    for label, (item, expected_atom) in fixtures.items():
        atoms = atomize_item(item)
        ids = [a["atom_id"] for a in atoms]
        assert expected_atom in ids, (label, ids)


def test_multiple_passives_each_get_own_atoms():
    """A later passive must not be absorbed by the first passive."""
    item = {
        "name": "Twin Edge",
        "passives": [
            {
                "name": "Onslaught",
                "branches": ["Deal 50 physical damage to nearby enemies."],
            },
            {"name": "Vampirism", "branches": ["Heal for 30% of damage dealt."]},
        ],
    }
    atoms = atomize_item(item)
    onslaught = _evidence_atoms(atoms, "passive", "Onslaught")
    vampirism = _evidence_atoms(atoms, "passive", "Vampirism")
    assert any(a["atom_id"] == "damage.physical" for a in onslaught)
    assert any(a["atom_id"] == "heal.flat" for a in vampirism), vampirism
    for atom in vampirism:
        for ev in atom["evidence"]:
            assert ev.startswith("passive:Vampirism@"), ev


def test_multiple_actives_each_get_own_atoms():
    item = {
        "name": "Dual Caster",
        "active": [
            {"name": "Blink", "branches": ["Dash to a target location."]},
            {"name": "Blaze", "branches": ["Deal 100 magic damage and burn enemies."]},
        ],
    }
    atoms = atomize_item(item)
    blink = _evidence_atoms(atoms, "active", "Blink")
    blaze = _evidence_atoms(atoms, "active", "Blaze")
    assert any(a["atom_id"] == "control.dash" for a in blink)
    assert any(a["atom_id"] == "damage.magic" for a in blaze)
    assert any(a["atom_id"] == "damage.burn" for a in blaze)
    for atom in blink + blaze:
        for ev in atom["evidence"]:
            assert ev.startswith("active:"), ev


def test_same_atom_in_two_effects_merges_receipts():
    """Identical atom identities from two effects merge into ONE atom whose
    evidence preserves BOTH effects' receipts (issue acceptance criterion 4)."""
    item = {
        "name": "Dual Guard",
        "passives": [{"name": "Aegis", "branches": ["Grants a shield."]}],
        "active": [{"name": "Bulwark", "branches": ["Shield the target ally."]}],
    }
    atoms = atomize_item(item)
    shield_atoms = [a for a in atoms if a["atom_id"] == "shield.flat"]
    assert len(shield_atoms) == 1
    evidence = set(shield_atoms[0]["evidence"])
    assert evidence == {"passive:Aegis@kw:shield", "active:Bulwark@kw:shield"}
    # each effect still "produced" the atom: evidence names both effects
    assert any(ev.startswith("passive:Aegis@") for ev in evidence)
    assert any(ev.startswith("active:Bulwark@") for ev in evidence)


def test_unnamed_effect_falls_back_to_position_name():
    item = {
        "name": "Mystery Orb",
        "passives": [{"branches": ["Grants a shield."]}],
    }
    atoms = atomize_item(item)
    unnamed = _evidence_atoms(atoms, "passive", "Passive 1")
    assert unnamed, atoms
    assert any(a["atom_id"] == "shield.flat" for a in unnamed)
    for atom in unnamed:
        for ev in atom["evidence"]:
            assert ev.startswith("passive:Passive 1@"), ev


def test_mixed_stats_and_effects_keep_structured_receipts():
    item = {
        "name": "Stalwart Crest",
        "stats": {"health": {"flat": 150.0}},
        "passives": [{"name": "Vigor", "branches": ["Heal for 30% of damage dealt."]}],
    }
    atoms = atomize_item(item)
    by_id = {a["atom_id"]: a for a in atoms}
    stat_atom = by_id["stat.health"]
    assert stat_atom["evidence"] == ["stats.health.flat"]  # structured, no @kw
    assert stat_atom["values"] == [150.0]
    heal_atom = by_id["heal.flat"]
    assert heal_atom["evidence"] == ["passive:Vigor@kw:heal"]
    # effect atoms never steal stat receipts and vice versa
    for atom in atoms:
        for ev in atom["evidence"]:
            if ev.startswith("stats."):
                assert atom["behavior"] == "stat"
            if atom["behavior"] == "stat":
                assert not re.search(r"@kw:", ev)


# ---------------------------------------------------------------------------
# Full-corpus gates (324 items)
# ---------------------------------------------------------------------------


def _effect_fragments(item):
    """(kind, effect_name) -> [(fragment_path, fragment_text)] mirroring
    atomize_item's naming and fragment construction."""
    out = {}
    for kind, key in (("passive", "passives"), ("active", "active")):
        effects = item.get(key) or []
        if isinstance(effects, dict):
            effects = [effects]
        for index, effect in enumerate(effects):
            ename = str(effect.get("name") or f"{kind.capitalize()} {index + 1}")
            prefix = f"{item.get('name', 'Unknown')}.{kind}s"
            frags = split_effect_fragments(effect, prefix=prefix, index=index)
            out.setdefault((kind, ename), []).extend(frags)
    return out


def test_full_corpus_provenance_gate():
    """Every emitted atom's evidence names its exact effect + keyword, the
    keyword is really a table keyword present in that effect's fragment text,
    and the atom's source is one of that effect's fragments."""
    items = fetch_item_data()
    assert items
    checked = 0
    for item in items.values():
        atoms = atomize_item(item)
        frags = _effect_fragments(item)
        # every legitimate source path: effect fragments + stats/shop blocks
        all_paths = {path for paths in frags.values() for path, _ in paths}
        all_paths |= {
            f"{item.get('name', 'Unknown')}.stats.{stat_name}"
            for stat_name in (item.get("stats") or {})
        }
        all_paths |= {f"{item.get('name', 'Unknown')}.shop.prices.total"}
        texts = {key: [t.lower() for _, t in paths] for key, paths in frags.items()}
        for atom in atoms:
            for ev in atom["evidence"]:
                match = re.fullmatch(r"(passive|active):(.+)@kw:(.+)", ev)
                if not match:
                    # structured receipts only: stats block / shop prices
                    assert ev.startswith(("stats.", "shop.prices.")), (item["name"], ev)
                    continue
                kind, ename, kw = match.group(1), match.group(2), match.group(3)
                assert kw in KEYWORDS, (item["name"], ev)
                key = (kind, ename)
                assert key in frags, (item["name"], ev)
                assert any(kw in t for t in texts[key]), (item["name"], ev)
                assert atom["source"] in all_paths, (item["name"], ev)
                checked += 1
    assert checked > 1000, checked  # the gate really ran over the corpus


def test_full_corpus_zero_silent_later_effects():
    """Report corpus claim: 93 multi-effect items, 109 later effects, 94%
    of later effects emitted zero atoms on the old extractor. After the fix
    the target is 0% silent later effects."""
    items = fetch_item_data()
    multi = 0
    later_effects = 0
    silent = []
    for item in items.values():
        ordered = []
        for kind, key in (("passive", "passives"), ("active", "active")):
            effects = item.get(key) or []
            if isinstance(effects, dict):
                effects = [effects]
            for index, effect in enumerate(effects):
                ordered.append((kind, effect, index))
        has_branch = [
            (kind, effect, index)
            for kind, effect, index in ordered
            if any(
                isinstance(b, str) and b.strip() for b in (effect.get("branches") or [])
            )
        ]
        atoms = atomize_item(item)
        produced = {
            (m.group(1), m.group(2))
            for atom in atoms
            for ev in atom["evidence"]
            for m in [re.match(r"^(passive|active):(.+?)@kw:", ev)]
            if m
        }
        if len(has_branch) >= 2:
            multi += 1
            for kind, effect, index in has_branch[1:]:
                ename = str(effect.get("name") or f"{kind.capitalize()} {index + 1}")
                later_effects += 1
                if (kind, ename) not in produced:
                    silent.append((item["name"], kind, ename))
    assert multi == 93, multi  # corpus claim: 93 multi-effect items
    assert later_effects == 109, later_effects  # corpus claim: 109 later effects
    assert not silent, silent  # target: 0% silent later effects
