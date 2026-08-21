"""Leaf-for-leaf parity of control-carrying roster fights across two trees.

Run once per checkout (``--out``), then ``--compare a.json b.json``.  The
scenarios put a stun or root on the main champion and a resistance shred or
spell shield on the roster, in both score and receipt mode, so every
CROWD_CONTROL action the score panels compile is exercised.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import golden_snapshot as gs  # noqa: E402

MAINS = ("Xayah", "Veigar", "Soraka", "Annie")
ROSTERS = (
    {"enemies": ("Aatrox", "Veigar"), "allies": ("Pantheon",)},
    {"enemies": ("Aatrox",), "allies": ("Lulu",)},
)


def scenarios():
    """The control-carrying fights, score and receipt mode each."""
    for champion in MAINS:
        for roster in ROSTERS:
            for score_mode in (False, True):
                mode = "score" if score_mode else "receipt"
                name = f"{champion.lower()}_{len(roster['enemies'])}e_{mode}"
                request = gs._roster_request(  # pylint: disable=protected-access
                    champion,
                    ("Black Cleaver",),
                    include_auto_attacks=True,
                    auto_attack_uptime=1.0,
                    **roster,
                )
                yield gs.CoupledScenario(name, request, score_mode=score_mode)


def leaves(node, path=""):
    """Every scalar under ``node`` with its JSON-pointer-like path."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from leaves(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from leaves(value, f"{path}[{index}]")
    else:
        yield path, node


def main() -> int:
    """Capture (``--out``) or compare (``--compare a b``)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--compare", nargs=2)
    args = parser.parse_args()
    if args.compare:
        a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args.compare)
        la, lb = dict(leaves(a)), dict(leaves(b))
        moved = [k for k in la if k in lb and la[k] != lb[k]]
        only = sorted(set(la) ^ set(lb))
        print(
            f"leaves: {len(la)} vs {len(lb)}  moved: {len(moved)}  only-one-side: {len(only)}"
        )
        for k in (moved + only)[:20]:
            print(" ", k, la.get(k), lb.get(k))
        return 1 if moved or only else 0
    mine = tuple(scenarios())
    snapshot = gs.capture_coupled(
        tuple(gs.COUPLED_SCENARIOS) + mine, producers=gs.cross_participant_producers()
    )
    names = {scenario.name for scenario in mine}
    rows = {k: v for k, v in snapshot["coupled_scenarios"].items() if k in names}
    Path(args.out).write_text(
        json.dumps(rows, sort_keys=True, default=str), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
