#!/usr/bin/env python3
"""E7 — decompose every item into behavior atoms (mirrors the champion atomizer).

Each item's stats, passives, and active are classified into the wiki behavior
atom vocabulary (data/wiki-atoms/*.json) with provenance (item name + passive/
active name + riotDescription text). Outputs data/item-atoms/<id>.json and a
summary receipt.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB_DIR = ROOT / "data/wiki-atoms"
ITEMS_JSON = ROOT / "data/items.json"
OUT_DIR = ROOT / "data/item-atoms"

STAT_FAMILY = {
    "health": "stats.health", "mana": "stats.mana", "attackDamage": "stats.attack-damage",
    "abilityPower": "stats.ability-power", "armor": "stats.armor", "magicResistance": "stats.magic-resistance",
    "attackSpeed": "stats.attack-speed", "cooldownReduction": "stats.ability-haste",
    "criticalStrikeChance": "stats.critical-chance", "armorPenetration": "stats.armor-penetration",
    "magicPenetration": "stats.magic-penetration", "lifeSteal": "stats.life-steal",
    "healAndShieldPower": "stats.heal-shield-power", "moveSpeed": "stats.move-speed",
    "goldPer10": "stats.gold-per-10", "lethality": "stats.lethality",
    "abilityHaste": "stats.ability-haste", "tenacity": "stats.tenacity",
}


def load_vocab() -> dict[str, dict]:
    atoms = {}
    for f in VOCAB_DIR.glob("*.json"):
        if f.name in ("spell-tags.json", "champion-passive-atoms.json", "champion-spell-atoms.json"):
            continue
        data = json.loads(f.read_text())
        if not isinstance(data, list):
            continue
        for a in data:
            atoms[a["atom_id"]] = a
    return atoms


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def tokens(s: str) -> set[str]:
    return {norm(t) for t in re.split(r"[^A-Za-z0-9]+", s) if t}


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "")


# Meta/reference atoms that must never vote on item prose (they describe the
# engine or generic damage accounting, not an item mechanic).
META_ATOMS = {
    "stack-transform-summon-resource.internal-resource-index",
    "stack-transform-summon-resource.flow",
    "damage.damage-instance",
    "damage.damage-tags",
    "damage.spell-effects",
    "damage.on-damage",
    "damage.tag-basicattack", "damage.tag-activespell", "damage.tag-periodic",
    "damage.tag-item", "damage.tag-pet", "damage.reactive", "damage.modifier",
    "damage.persistent-area", "damage.capped", "damage.properties",
    "crowd-control-mobility.combat-status", "crowd-control-mobility.cc-score",
}


def corpus_prune(vocab: dict[str, dict], items: dict) -> set[str]:
    """Drop vocab keywords that fire on too many items (>25%) — they carry no
    signal on item prose (e.g. 'true' in random stats text, 'deep' substrings).
    Returns the set of pruned atom_ids."""
    from collections import Counter
    fire = Counter()
    total = 0
    for item in items.values():
        hay = tokens(strip_html(" ".join([
            item.get("name") or "",
            item.get("simpleDescription") or "",
            strip_html(item.get("riotDescription") or ""),
        ])))
        for atom_id, a in vocab.items():
            if a.get("family") == "interaction":
                continue
            for kw in a.get("keywords", []):
                nk = norm(kw)
                ktoks = tokens(kw)
                if not nk or len(nk) < 4:
                    continue
                if ktoks and ktoks <= set(hay):
                    fire[atom_id] += 1
                    break
        total += 1
    pruned = {aid for aid, n in fire.items() if total and n / total > 0.25}
    return pruned


def classify(text: str, vocab: dict[str, dict], existing: set[str]) -> list[tuple[str, str]]:
    """Return [(atom_id, family)] for keywords that appear as TOKENS in the
    text (token-level, never substring — "heal" must not fire on "health").
    A passive identity name (e.g. "Lifeline") matches its atom's keywords too."""
    hay_toks = tokens(strip_html(text))
    hits = []
    for atom_id, a in vocab.items():
        if atom_id in existing or atom_id in META_ATOMS or a.get("family") == "interaction":
            continue
        for kw in a.get("keywords", []):
            nk = norm(kw)
            ktoks = tokens(kw)
            if not nk or len(nk) < 4:
                continue
            if ktoks and ktoks <= hay_toks:
                hits.append((atom_id, a["family"]))
                break
    return hits


def decompose_item(item: dict, vocab: dict[str, dict], relations: dict) -> dict:
    name = item.get("name", "?")
    atoms = []
    seen = set()
    # stats -> stat atoms
    for stat_key, atom_id in STAT_FAMILY.items():
        stat = (item.get("stats") or {}).get(stat_key) or {}
        flat = float(stat.get("flat", 0.0) or 0.0)
        pct = float(stat.get("percent", 0.0) or 0.0)
        if flat or pct:
            atoms.append({
                "atom_id": atom_id, "family": "stats", "behavior": stat_key,
                "parameters": {"flat": flat, "percent": pct},
                "relations": relations.get(atom_id, []),
                "provenance": {"wiki": [name], "binary": [], "evidence": "stats"},
            })
            seen.add(atom_id)
    full_text = " ".join([
        name,
        item.get("simpleDescription") or "",
        strip_html(item.get("riotDescription") or ""),
    ])
    # passives
    for passive in item.get("passives") or []:
        pname = passive.get("name") or ""
        text = f"{pname} {full_text}"
        for atom_id, family in classify(text, vocab, seen):
            atoms.append({
                "atom_id": atom_id, "family": family,
                "behavior": pname or "passive",
                "parameters": {},
                "relations": relations.get(atom_id, []),
                "provenance": {"wiki": [name], "binary": [], "evidence": f"passive:{pname}"},
            })
            seen.add(atom_id)
    # actives
    for active in item.get("active") or []:
        aname = active.get("name") or ""
        text = f"{aname} {full_text}"
        for atom_id, family in classify(text, vocab, seen):
            atoms.append({
                "atom_id": atom_id, "family": family,
                "behavior": aname or "active",
                "parameters": {},
                "relations": relations.get(atom_id, []),
                "provenance": {"wiki": [name], "binary": [], "evidence": f"active:{aname}"},
            })
            seen.add(atom_id)
    return {"name": name, "id": item.get("id"), "atoms": atoms}


def load_relations() -> dict[str, list[str]]:
    p = VOCAB_DIR / "atom-relations.json"
    if p.exists():
        return json.loads(p.read_text())
    return {}


def main():
    vocab = load_vocab()
    relations = load_relations()
    items = json.loads(ITEMS_JSON.read_text())
    pruned = corpus_prune(vocab, items)
    print(f"pruned {len(pruned)} over-firing atom_ids: {sorted(pruned)[:20]}")
    vocab = {aid: a for aid, a in vocab.items() if aid not in pruned}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary: dict[str, set[str]] = {}
    total = 0
    for item_id, item in items.items():
        dec = decompose_item(item, vocab, relations)
        (OUT_DIR / f"{item_id}.json").write_text(json.dumps(dec, indent=1))
        total += len(dec["atoms"])
        for a in dec["atoms"]:
            summary.setdefault(a["family"], set()).add(dec["name"])
    agg = {fam: sorted(champs) for fam, champs in sorted(summary.items())}
    (OUT_DIR / "item-atom-summary.json").write_text(json.dumps(agg, indent=1))
    print(f"items: {len(items)} | atoms: {total}")
    for fam, names in agg.items():
        print(f"  {fam}: {len(names)} items")


if __name__ == "__main__":
    main()
