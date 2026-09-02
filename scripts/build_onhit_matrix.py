"""Generate the ground-truth on-hit application matrix from the wiki cache.

Scans data/champions.json for the wiki's standard item-on-hit phrasing
("applies on-hit effects" / "applies item effects") and records, per reviewed
champion ability, whether the ability applies item on-hits (and/or triggers
on-attack effects) with the wiki-stated effectiveness.  Negated phrasing
("cannot ... apply on-hit effects") is handled explicitly.

Output: data/onhit-matrix.json — consumed by
tests/test_spellblade_on_hit_matrix.py, which pins the module declarations
so a patch-day re-parse cannot silently change an attack classification.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "data" / "onhit-matrix.json"

_APPLIES = re.compile(r"appl(?:ies|y|ying|ied).{0,60}on[- ]?hit effects", re.IGNORECASE)
_TRIGGERS_ON_ATTACK = re.compile(r"trigger(?:s|ing).{0,40}on[- ]?attack", re.IGNORECASE)
_NEGATED = re.compile(
    r"(?:cannot|does not|don'?t|no longer|not).{0,50}(?:apply|trigger).{0,40}on[- ]?hit",
    re.IGNORECASE,
)
_EFFECTIVENESS = re.compile(
    r"with on[- ]?hit damage reduced to (\d+)% effectiveness|"
    r"on[- ]?hit effects at (\d+)% effectiveness|"
    r"appl(?:ies|y|ying).{0,30}on[- ]?hit effects at (\d+)%|"
    r"appl(?:ies|y|ying).{0,30}item on[- ]?hit effects at (\d+)%",
    re.IGNORECASE,
)
_ONLY_ONCE = re.compile(r"apply on[- ]?hit effects only once", re.IGNORECASE)


def ability_text(entry: Mapping) -> str:
    parts = [str(entry.get("name", ""))]
    parts.extend(
        str(effect.get("description", ""))
        for effect in entry.get("effects") or []
        if isinstance(effect, dict)
    )
    return " ".join(parts)


def build() -> dict[str, dict[str, list[dict[str, Any]]]]:
    champions = json.loads(
        (REPO_ROOT / "data" / "champions.json").read_text(encoding="utf-8")
    )
    rows = {}
    for champion_name, champion in champions.items():
        for slot, entries in (champion.get("abilities") or {}).items():
            for entry in entries:
                text = ability_text(entry)
                applies = bool(_APPLIES.search(text)) and not _NEGATED.search(text)
                if not applies:
                    continue
                on_attack = bool(_TRIGGERS_ON_ATTACK.search(text))
                effectiveness = 1.0
                match = _EFFECTIVENESS.search(text)
                if match:
                    for group in match.groups():
                        if group:
                            effectiveness = int(group) / 100.0
                            break
                once = bool(_ONLY_ONCE.search(text))
                rows.setdefault(champion_name, []).append(
                    {
                        "slot": slot,
                        "name": entry.get("name"),
                        "effectiveness": effectiveness,
                        "on_attack": on_attack,
                        "only_once_per_cast": once,
                    }
                )
    return {"champions": rows}


if __name__ == "__main__":
    payload = build()
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    count = sum(len(v) for v in payload["champions"].values())
    print(
        f"wrote {OUT}: {count} on-hit-applying abilities across "
        f"{len(payload['champions'])} champions"
    )
