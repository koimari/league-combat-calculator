"""The re-adjudication brief a docketed dissent cluster needs, assembled.

``docs/receipts/standing-dissent-docket.json`` made twenty-two standing
dissents startable: each cluster names the defect in its members' shared brief,
which is what the R-15/R-18 amendment's clause 3 requires a superseding receipt
to cite, and three of the four carry the well-posed brief clause 1 needs.  What
the docket deliberately does *not* carry is the pre-change series itself --
*"a sha is that instruction; a value pasted here is a second home for it"* --
so assembling the brief is still a step somebody performs by hand.

That step is the one place the whole apparatus can leak.  The amendment spends
its longest paragraph on a single line: the **pre-change** side and the
committed scenario definitions may be quoted, and the **post-change** side may
not, because the post-change side is the answer.  A hand-assembled brief
obeying that line obeys it by care.  This script obeys it by construction: the
only baseline it can read is ``git show <pre-change sha>:...``, it never opens
the working tree's copy, and a source assertion in its gate pins that.

Everything it emits is derived.  The series a cluster is about comes from the
leaf paths of the cluster's own receipts -- take each disputed leaf, walk up to
the list it sits in, and the union of those containers is the record the
amendment says is the unit of investigation.  The export the investigator gets
is R-18's, quoted out of the runbook at run time rather than re-spelled here,
because that command's sole home is the ruling.

**What this file is not.**  It decides nothing and no output of it states or
implies an answer.  It refuses a cluster routed to a ruling rather than
quietly briefing it, because clause 3 makes a re-run whose receipt names no
defect in the prior brief unwritable and that cluster has no defect to name --
briefing it anyway would be oracle shopping with a script in front of it.  It
refuses a cluster whose re-adjudication has already run for the same reason
from the other end: the brief it was posed under was this docket's own and was
well posed, so a second one would cite no defect either, and what that row
owes is clause 2's ruled ``src/`` slice.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKET_PATH = REPO_ROOT / "docs" / "receipts" / "standing-dissent-docket.json"
RECEIPTS_DIR = REPO_ROOT / "docs" / "receipts"
RUNBOOK_PATH = REPO_ROOT / "docs" / "plans" / "silent-failure-runbook.md"

#: The committed baseline, addressed inside a git object and never on disk.
#: The working tree's copy is the post-change side, which is the answer.
BASELINE_IN_TREE = "scripts/golden_coupled_baseline.json"

#: Where R-18's export command lives.  Read, never re-spelled: the runbook
#: calls itself that command's sole home.
R18_HEADING = "**R-18 —"

_INDEXED = re.compile(r"^(?P<name>.+)\[(?P<index>\d+)\]$")


class BriefError(RuntimeError):
    """A brief cannot be assembled from what the docket and the tree hold."""


def docket() -> Mapping[str, Any]:
    """The committed docket this script builds briefs out of."""
    return json.loads(DOCKET_PATH.read_text(encoding="utf-8"))


def clusters() -> dict[str, Mapping[str, Any]]:
    """Every docketed cluster, by id."""
    return {entry["id"]: entry for entry in docket()["clusters"]}


def export_command() -> str:
    """R-18's export command, read from the runbook.

    The one tree an investigator sees is built by exactly this command, and
    the runbook is its sole home.  Reading it means a brief cannot hand an
    investigator a wider export than the ruling allows -- and means the gate
    over this script goes red if the ruling's command ever changes.
    """
    lines = RUNBOOK_PATH.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(R18_HEADING):
            continue
        fenced: list[str] = []
        inside = False
        for candidate in lines[index + 1 :]:
            if candidate.startswith("```"):
                if inside:
                    return "\n".join(fenced)
                inside = True
                continue
            if inside:
                fenced.append(candidate)
    raise BriefError(
        "R-18's export command is not readable from the runbook; a brief "
        "refuses to re-spell it, because the ruling is that command's sole home"
    )


def _receipt_leaf(name: str) -> tuple[str, str]:
    """One receipt's scenario and its leaf path inside that scenario."""
    receipt = json.loads((RECEIPTS_DIR / name).read_text(encoding="utf-8"))
    path = str(receipt["leaf_path"]).strip("/")
    prefix = "coupled_scenarios/"
    if path.startswith(prefix):
        remainder = path[len(prefix) :]
        scenario, _, inner = remainder.partition("/")
        return scenario, inner
    scenario = receipt.get("scenario")
    if not scenario:
        raise BriefError(
            f"{name} names neither a scenario nor a scenario-qualified leaf "
            "path, so the series it belongs to cannot be located"
        )
    return str(scenario), path


def series_containers(cluster: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """The list every disputed leaf of this cluster sits in.

    The amendment's unit of investigation is the series, not the member, and a
    series is a run of members one mechanic produced into one record.  So each
    receipt's leaf path is walked up to its deepest indexed component and the
    container is the path through that component's name --
    ``rotation/cast_order[2]`` gives ``rotation/cast_order``.  A member with no
    index is a key of a mapping the same mechanic produced --
    ``rotation/aoe/passive``, one of the keys a derivation added -- and its
    container is its parent, ``rotation/aoe``.  The union over a cluster's
    receipts is the record: five containers for a rotation record, one for a
    cast timeline.
    """
    found: set[tuple[str, str]] = set()
    for name in cluster["receipts"]:
        scenario, path = _receipt_leaf(name)
        parts = path.split("/")
        container = None
        for depth, part in enumerate(parts):
            match = _INDEXED.match(part)
            if match:
                container = "/".join([*parts[:depth], match.group("name")])
        if container is None:
            if len(parts) < 2:
                raise BriefError(
                    f"{name}'s leaf path {path!r} is a scenario-level leaf with "
                    "no container, so it sits in no series and this cluster is "
                    "not one a series brief can pose"
                )
            container = "/".join(parts[:-1])
        found.add((scenario, container))
    return tuple(sorted(found))


def pre_change_baseline(sha: str) -> Mapping[str, Any]:
    """The committed coupled baseline as of *sha* -- the question's side.

    Read out of the git object and never off disk.  The working tree's copy is
    the post-change side, which the R-18 amendment forbids a brief to carry,
    and a script that could open it would obey that line by care rather than
    by construction.
    """
    shown = subprocess.run(
        ["git", "show", f"{sha}:{BASELINE_IN_TREE}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if shown.returncode != 0:
        raise BriefError(
            f"the committed baseline is not readable at {sha}: "
            f"{shown.stderr.strip()}"
        )
    return json.loads(shown.stdout)["coupled_scenarios"]


def _at(tree: Mapping[str, Any], scenario: str, container: str) -> Any:
    """One container's contents inside one scenario of a capture."""
    node: Any = tree[scenario]
    for part in container.split("/"):
        node = node[part]
    return node


def refusal(cluster_id: str, entry: Mapping[str, Any]) -> str | None:
    """Why this cluster may not be briefed, or ``None`` if it may.

    Both refusals are clause 3 read in the two directions a docket row can
    lack a brief.  A cluster *routed to a ruling* never had a defect to name.
    A cluster whose re-adjudication has *already run* has no defect to name
    either -- the brief it was posed under is this docket's own, and it was
    well posed -- so what it owes is clause 2's ruled ``src/`` slice and not a
    second investigator.  Naming which one it is matters more than refusing:
    "not startable" would read as a gap, and neither of these is one.
    """
    if "brief_for_the_re_adjudication" in entry:
        return None
    if "re_adjudication_filed" in entry:
        return (
            f"{cluster_id} has been re-adjudicated and carries no brief on "
            "purpose: clause 1 is spent, and clause 3 requires a re-run to cite "
            "a specific defect in the brief it replaces -- the brief this docket "
            "wrote, which has none. What it owes is clause 2, the producing "
            "correction re-opened as its own ruled src/ slice. Briefing it again "
            "is oracle shopping. See its re_adjudication_filed block and the "
            "receipts it names"
        )
    return (
        f"{cluster_id} is routed to a ruling and carries no brief on "
        "purpose: its prior brief has no defect to name, and clause 3 "
        "makes a re-run whose receipt names none unwritable. Briefing it "
        f"anyway is oracle shopping. See {entry.get('owed_ruling_id')!r} in "
        "docs/receipts/rulings-owed.json"
    )


def build(cluster_id: str) -> dict[str, Any]:
    """The whole brief for one cluster, ready to hand to an investigator."""
    entry = clusters().get(cluster_id)
    if entry is None:
        raise BriefError(f"no docketed cluster is called {cluster_id!r}")
    refused = refusal(cluster_id, entry)
    if refused is not None:
        raise BriefError(refused)
    sha = entry["pre_change_capture"]
    tree = pre_change_baseline(sha)
    containers = series_containers(entry)
    return {
        "cluster": cluster_id,
        "instructions_to_the_spawning_agent": (
            "Run the export command below into a scratch directory and give the "
            "investigator that directory and this brief. It must have read "
            "neither the prior receipts nor the docket. It computes the whole "
            "series from scratch and returns one receipt per leaf, each naming "
            "the defect in the prior brief quoted below and the receipt it "
            "supersedes (R-15/R-18 amendment, clauses 1 and 3)."
        ),
        "export_command": export_command(),
        "what_the_investigator_may_not_be_given": entry[
            "brief_for_the_re_adjudication"
        ]["what_the_brief_may_not_carry"],
        "unit": entry["brief_for_the_re_adjudication"]["unit"],
        "question": entry["brief_for_the_re_adjudication"]["question"],
        "scenario_parameters": entry["brief_for_the_re_adjudication"][
            "scenario_parameters"
        ],
        "defect_in_the_prior_brief": entry["defect_in_the_prior_brief"],
        "receipts_this_supersedes": list(entry["supersedes_on_filing"]),
        "pre_change_capture": sha,
        "pre_change_series": {
            f"{scenario}/{container}": _at(tree, scenario, container)
            for scenario, container in containers
        },
        "why_only_the_pre_change_side_is_here": (
            "The R-18 amendment of 2026-08-14: the pre-change side and the "
            "committed scenario definitions are facts of the QUESTION and may "
            "be quoted in full; the post-change side is the answer and may "
            "not. This brief is assembled from the git object at "
            f"{sha} and never from the working tree, so the line holds "
            "structurally rather than by care."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """``--cluster ID`` prints one brief; ``--list`` names the startable ones."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster", help="the docketed cluster to brief")
    parser.add_argument(
        "--list", action="store_true", help="which clusters a brief can be built for"
    )
    args = parser.parse_args(argv)
    if args.list or not args.cluster:
        for cluster_id, entry in sorted(clusters().items()):
            if "brief_for_the_re_adjudication" in entry:
                state = "startable"
            elif "re_adjudication_filed" in entry:
                state = "re-adjudicated; owes a ruled src/ slice (clause 2)"
            else:
                state = f"routed to ruling {entry.get('owed_ruling_id')}"
            print(f"{cluster_id}: {state}")
        return 0
    print(json.dumps(build(args.cluster), indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
