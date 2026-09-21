"""Which local resources this machine has, and what a run owes when one is absent.

A test whose evidence is a locally built game file, or a browser probe that
shells out to ``node``, cannot run where the resource is not there.  The
ruling is that the nodes needing it are deselected and counted rather
than skipped, because a skip prints green for work that did not happen.

This is the vocabulary; ``tests/conftest.py`` holds the hooks that act on it
and ``scripts/resource_markers.py`` is the gate that every guarded test
carries its marker.  It lives outside conftest so the gate can read it
without importing half of ``src/calculator``.

This is a test helper, not a test module: it holds no assertions.
"""

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


#: A local resource a test cannot run without, and how to ask whether this
#: machine has it.  The three game-file trees are three resources, because a
#: checkout answers them differently: the character binaries are tracked and
#: every checkout has them, while the item dump and the cdtb export are
#: gitignored and exist only where a patch day built them.  A probe that
#: reads them as one resource can never be satisfied, and deselects every
#: node that names it on every machine.
RESOURCES = {
    "needs_game_files": (
        "the tracked character binaries under data/bin/characters",
        lambda: any((ROOT / "data/bin/characters").glob("*.bin.json")),
    ),
    "needs_item_binary": (
        "data/bin/items.bin.json, the gitignored item dump",
        (ROOT / "data/bin/items.bin.json").exists,
    ),
    "needs_gamefile_cache": (
        "the gitignored cdtb export under data/gamefiles/characters",
        lambda: any((ROOT / "data/gamefiles/characters").glob("*.bin.json")),
    ),
    "needs_node": (
        "node, for the browser probes that shell out to it",
        lambda: shutil.which("node") is not None,
    ),
}


#: What this session did not run, by resource, for the terminal summary.
NOT_RUN: pytest.StashKey[dict[str, int]] = pytest.StashKey()


#: The same counts crossing the xdist wire, where a stash cannot reach.
NOT_RUN_WIRE = "not_run_by_resource"


def absent_resources() -> set[str]:
    """Every resource marker whose resource this machine does not have."""
    return {marker for marker, (_, present) in RESOURCES.items() if not present()}
