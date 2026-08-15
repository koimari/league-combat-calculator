"""The campaign's plan documents, gated like source (runbook R-37, slice 0A.10).

The Silent-Failure Campaign machine-checks every claim it makes about ``src/``
and exempted the documents making them.  Those documents hold dozens of
measured counts and ``file.py:NNN`` citations, all verified once and rotting
from the next commit onward — three of the umbrella's own rev-2 corrections
were instances of that single gap.  This is the instrument that closes the
class rather than patching instances.

Three checks run over ``docs/plans/*.md``:

1. **Citations.**  Every ``file.ext:NNN`` names a file this repository has, at
   a line that file has.  Where a backtick fragment *adjoins* the citation, the
   fragment must be at the cited location.  The fragment is the authoritative
   referent and the line number only a locator, so the two outcomes are
   deliberately different: a fragment found elsewhere in the file is **drift**,
   refreshed in a doc-only commit; a fragment found nowhere is a **plan/tree
   divergence**, escalated to a human and never silently re-pointed.
2. **Golden shape figures.**  No plan document may state a golden or
   coupled-golden leaf or entry count (umbrella criterion 4) — those live only
   in ``docs/receipts/campaign-fingerprints.json``.  Two prongs, because the
   figure that was retired had been *wrong*: a value match against the retired
   literals and the live receipt counts catches a correct restatement, and a
   proximity-marker prong catches a wrong one.
3. **Decision inventory.**  ``docs/receipts/decision-inventory.json`` is
   asserted equal to what the umbrella's manifest and decision tables actually
   declare, with the reserve gaps asserted absent.  Umbrella criterion 11 reads
   this check instead of performing a prose audit.

Two definitions this module owns, because R-37 states the rule and not its
mechanics:

**Adjacency is parenthesis, and it is measured over the paragraph.**  A backtick
span adjoins a citation only when one parenthesises the other —
``(`file.py:12`)`` or ``` `file.py:12` (`frag`) ```.  A comma-separated
neighbour is an enumeration item, not a referent: Phase 2 writes
``(`survival/score_state.py:97`, `survival/compile.py:72`,
`SurvivalAction.defy_trigger_id`)``, a list of three sibling pointers in which
the third is nobody's fragment, while Phase 3 writes a comma-separated
parenthetical in which it is.  Comma cannot tell those apart; parenthesis can.

The pair is sought over the *paragraph*, not the source line: an author's
line wrap is invisible to a reader and must be invisible to the gate, or a
fragment that happens to land past the wrap is never verified — a class of
plan/tree divergence unreachable by construction, which is the failure shape
this campaign exists to kill.  ``_logical_lines`` joins each markdown block
into one string and keeps the source line of every offset, so findings still
name the line the citation is written on.  Blocks end where a reader stops
reading across: blank lines, table rows, headings, fences, block quotes and
list markers.  Check 2's proximity prong reads the same blocks for the same
reason — a shape keyword and the figure it labels are as adjacent across a
wrap as within one line.

**A fragment is at the cited location** when it appears, whitespace-insensitive,
within ``CITATION_WINDOW`` lines of the citation — or, for a Python file, when
the citation falls inside the extent of the definition the fragment names.  The
second clause is what lets a document name an enclosing function and cite a
block inside it, which is how the plans point at code they are about to move.

Usage:
    python scripts/plan_audit.py                     # the gate
    python scripts/plan_audit.py --write-inventory   # re-derive the inventory
"""

from __future__ import annotations

# Two thirds of this file is a committed exception table, not logic: the
# collision allowlist grows by one block every time a capture makes a shape
# count a small, common integer, and each row carries the sentence that
# excuses it.  The size warning would fire on every such capture and says
# nothing about the checks below, which is why it is silenced here and not
# ratcheted around.  The alternative -- moving the table to a receipt the way
# every other campaign allowlist lives -- is a change to where this gate reads
# its data and belongs to a slice of its own, not to a capture.
# pylint: disable=too-many-lines

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
PLANS_DIR = REPO_ROOT / "docs" / "plans"
UMBRELLA_NAME = "2026-08-08-silent-failure-campaign.md"
FINGERPRINTS_PATH = REPO_ROOT / "docs" / "receipts" / "campaign-fingerprints.json"
INVENTORY_PATH = REPO_ROOT / "docs" / "receipts" / "decision-inventory.json"

# How far from the cited line a quoted fragment may sit and still be "there".
CITATION_WINDOW = 5

# Directories the citation resolver never looks in: vendored third-party code
# (repo rule 1), build scratch, and the data cache — whose thousands of JSON
# files are addressed by path, not by basename.
UNINDEXED_DIRS = frozenset(
    {".git", "__pycache__", "node_modules", ".venv", "vendor", "data"}
)

# The retired golden figure's literal spellings.  Empty, deliberately: the
# umbrella retired the scenario-entry figure *and its value together* —
# criterion 4 forbids restating it even as a warning, "because a doc figure a
# reader cannot regenerate is exactly how the retired one survived" — so no
# spelling of it survives here to pin.  The constant is the home R-37 gives
# such a literal, and the next retired figure lands here because there is
# nowhere else it may be written.  The prong is not thereby vacuous: live
# golden counts are read from the fingerprints receipt at run time and matched
# the same way, and its red is driven on demand by tests/test_plan_audit.py.
RETIRED_GOLDEN_FIGURES: tuple[str, ...] = ()

# Blocks of the fingerprints receipt whose integer members are golden shape
# counts, and therefore forbidden in prose.
GOLDEN_FINGERPRINT_BLOCKS = ("golden", "coupled_golden", "coupled_golden_exact")

# Prose that makes an adjacent integer a golden shape claim.  ``golden`` matches
# as a bare word only: ``golden_snapshot.py`` is an identifier, not a figure.
GOLDEN_SHAPE_KEYWORDS = ("golden", "leaf count", "entry count", "scenario entr")

# The citation marker an integer near those keywords must carry, and how many
# whitespace tokens count as "adjacent" for the proximity prong.
FINGERPRINT_MARKER = "fingerprint:"
PROXIMITY_TOKENS = 6


@dataclass(frozen=True, slots=True)
class Allowance:
    """One legitimate coincidence between prose and a golden shape count.

    ``context`` is a literal that must appear on the same line, so an allowance
    survives the line numbers moving but does not blanket a whole document
    unless it is deliberately empty.
    """

    doc: str
    value: int
    context: str
    reason: str

    def admits(self, doc: str, value: int, line: str) -> bool:
        """Whether this allowance covers one integer occurrence."""
        return self.doc == doc and self.value == value and self.context in line


# Committed collision allowlist (R-37): each row names its document and reason.
COLLISION_ALLOWLIST: tuple[Allowance, ...] = tuple(
    Allowance(
        doc=doc,
        value=0,
        context="",
        reason=(
            "coupled_golden_exact.numeric_leaves is 0 because the exact snapshot "
            "holds only repr(float) strings; a bare 0 in prose is a diff count, "
            "an occurrence count or a float, never that shape figure"
        ),
    )
    for doc in (
        UMBRELLA_NAME,
        "silent-failure-runbook.md",
        "phase-0-gates-and-corrections.md",
        "phase-1-coverage-evidence.md",
        "phase-2-trigger-bus.md",
        "phase-3-behavior-rules.md",
        "phase-4-program-engine.md",
        "phase-5-cast-dependency.md",
    )
) + (
    Allowance(
        doc="phase-0-gates-and-corrections.md",
        value=13,
        context="R-01 rows",
        reason="R-01's eleven rows are numbered; 13 here is a row list, not an entry count",
    ),
    Allowance(
        doc="phase-3-behavior-rules.md",
        value=13,
        context="modules",
        reason="the 13 modules holding runtime item-name dispatch — a source count",
    ),
    Allowance(
        doc="phase-0-gates-and-corrections.md",
        value=0,
        context="Expected qualifying occurrences",
        reason=(
            "an R-20 occurrence declaration beside the word 'golden' is a measured "
            "diff count, exempt under criterion 4"
        ),
    ),
    Allowance(
        doc="phase-0-gates-and-corrections.md",
        value=0,
        context="Pair-engine golden is structurally",
        reason="the same R-20 declaration, restated as the reason it is structural",
    ),
    Allowance(
        doc="phase-0-gates-and-corrections.md",
        value=0,
        context="pair-engine golden's 0 is asserted",
        reason="the same R-20 declaration, in criterion 14",
    ),
    Allowance(
        doc=UMBRELLA_NAME,
        value=2,
        context="rounds to 2 dp",
        reason="golden's rounding precision (R-13), not a count of anything",
    ),
    *(
        Allowance(
            doc=doc,
            value=value,
            context=context,
            reason=(
                f"{what}, which happens to equal "
                f"coupled_golden_exact.{field} since the four bench rosters "
                "joined that capture on 2026-08-14"
            ),
        )
        # The exact capture's counts became small, common integers the day it
        # grew: these are collisions, which is what this allowlist is for.
        for doc, value, field, context, what in (
            (
                "phase-5-cast-dependency.md",
                119,
                "leaves",
                "splinters",
                "a Syndra splinter count in a cast-order pin",
            ),
            (
                "silent-failure-runbook.md",
                17,
                "entries",
                "criterion 17",
                "R-32's citation of Phase 4's criterion 17",
            ),
            (
                "phase-1-coverage-evidence.md",
                17,
                "entries",
                "survival/outcome_state",
                "a per-module claim count in the coverage table",
            ),
            (
                "phase-3-behavior-rules.md",
                17,
                "entries",
                "RuleFamily",
                "the closed size of the RuleFamily union",
            ),
            (
                "phase-4-program-engine.md",
                17,
                "entries",
                "new modules",
                "the count of new program/ modules naming a test front door",
            ),
            (
                "phase-4-program-engine.md",
                17,
                "entries",
                "undeclared modules",
                "the same module count, as what would break the frontier",
            ),
            (
                "phase-4-program-engine.md",
                17,
                "entries",
                "criterion 17",
                "a citation of this phase's own criterion 17",
            ),
            (
                "phase-4-program-engine.md",
                17,
                "entries",
                "criteria 2 and 17",
                "the same criterion citation, in the pair it is read with",
            ),
        )
    ),
    Allowance(
        doc=UMBRELLA_NAME,
        value=5,
        context="golden rows | **Recorded ruling: Phase 5",
        reason="H6's ruling names Phase 5; the integer is a phase number",
    ),
    *(
        Allowance(
            doc=doc,
            value=value,
            context=context,
            reason=(
                f"{what}, which happens to equal coupled_golden{block}.entries "
                "since the two covering rosters joined the coupled scenario set "
                "on 2026-08-15 (umbrella Amendment L, Ruling 2)"
            ),
        )
        # The same shape as the block above, one capture later: a scenario
        # count is a small integer, and small integers are everywhere in
        # prose about margins, members and sites.
        for doc, value, block, context, what in (
            (
                "phase-0-gates-and-corrections.md",
                15,
                "",
                "IMMOBILIZING_CC_KINDS",
                "the member count of an ability-spec constant",
            ),
            (
                "phase-3-behavior-rules.md",
                15,
                "",
                "sites are all",
                "the count of `ast.Call` name sites in `damage.py`",
            ),
            (
                "phase-3-behavior-rules.md",
                15,
                "",
                "name sites",
                "the same site count, in the migration's own inventory",
            ),
            (
                "phase-4-program-engine.md",
                15,
                "",
                "margin",
                "an allocation-probe margin in percent",
            ),
            (
                "silent-failure-runbook.md",
                15,
                "",
                "peak, one isolated evaluation",
                "the same margin, where R-28 declares it",
            ),
            (
                "silent-failure-runbook.md",
                15,
                "",
                "allocation_probe` peak stays within its",
                "the same margin, in the criterion that reads it",
            ),
            (
                "phase-3-behavior-rules.md",
                19,
                "_exact",
                "ALLY_ITEM_EFFECTS",
                "the entry count of a registry and the size of `ActionKind`",
            ),
            (
                "phase-3-behavior-rules.md",
                19,
                "_exact",
                "Undeclared `ITEM_EFFECTS`",
                "the same registry count, in the frontier table",
            ),
            (
                "phase-3-behavior-rules.md",
                19,
                "_exact",
                "`ActionKind`s, every support producer",
                "the size of `ActionKind`, in the closure criterion",
            ),
        )
    ),
)


@dataclass(frozen=True, slots=True)
class Finding:
    """One reason the plan documents fail their gate."""

    check: str
    doc: str
    line: int
    message: str

    def __str__(self) -> str:
        where = f"{self.doc}:{self.line}" if self.line else self.doc
        return f"[{self.check}] {where}: {self.message}"


def plan_documents(directory: Path = PLANS_DIR) -> tuple[Path, ...]:
    """Every campaign plan document, in a stable order."""
    return tuple(sorted(Path(directory).glob("*.md")))


# ---------------------------------------------------------------------------
# Check 1 — citations
# ---------------------------------------------------------------------------

_SPAN = re.compile(r"`([^`]+)`")
_CITATION = re.compile(
    r"^(?P<target>[A-Za-z0-9_./\\-]+\.(?:py|json|yml|yaml|js|md|txt))"
    r":(?P<start>\d+)(?:-(?P<end>\d+))?"
)
# A gap that parenthesises: brackets plus markdown emphasis and nothing else.
_PARENTHETIC_GAP = re.compile(r"^[\s*_]*[()][\s*_]*$")
# A line that opens its own markdown block and never joins the one above it.
_BLOCK_START = re.compile(r"^(?:\s*$|\s*\||#{1,6}\s|\s*```|\s*>|\s*[-*+]\s|\s*\d+\.\s)")
# A span that is itself a locator rather than a fragment.
_LOCATOR_SPAN = re.compile(r"^:?\d")
_QUALIFIED = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+(?:\(\))?$")
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")


@dataclass(frozen=True, slots=True)
class Citation:
    """One ``file.ext:NNN`` reference and the fragment adjoining it, if any."""

    doc: str
    doc_line: int
    target: str
    start: int
    end: int
    fragment: str | None


def _adjoining_fragment(line: str, spans: Sequence[re.Match], index: int) -> str | None:
    """The backtick span parenthesising the citation at ``index``, if any.

    Only a parenthesis counts as adjacency, and a neighbour that is itself a
    locator is a sibling pointer rather than this citation's referent.
    """
    neighbours = []
    if index + 1 < len(spans):
        neighbours.append(
            (spans[index + 1], line[spans[index].end() : spans[index + 1].start()])
        )
    if index:
        neighbours.append(
            (spans[index - 1], line[spans[index - 1].end() : spans[index].start()])
        )
    for neighbour, gap in neighbours:
        candidate = neighbour.group(1)
        if not _PARENTHETIC_GAP.match(gap):
            continue
        if _CITATION.match(candidate) or _LOCATOR_SPAN.match(candidate):
            continue
        return candidate.replace(r"\|", "|")
    return None


@dataclass(frozen=True, slots=True)
class LogicalLine:
    """One markdown block as a single string, plus where its offsets came from.

    ``origins`` holds ``(offset, source line number)`` for each joined line, so
    a citation found anywhere in ``text`` still reports the line an author
    would edit.
    """

    text: str
    origins: tuple[tuple[int, int], ...]

    def source_line(self, offset: int) -> int:
        """The document line the character at ``offset`` was written on."""
        number = self.origins[0][1]
        for start, line in self.origins:
            if start > offset:
                break
            number = line
        return number


def _logical_lines(text: str) -> tuple[LogicalLine, ...]:
    """The document's markdown blocks, each joined into one line.

    A wrapped paragraph is one thing a reader reads, so it is one thing the
    citation check reads.  A line that opens its own block — blank, table row,
    heading, fence, block quote, or a new list item — never joins the block
    above it.
    """
    blocks: list[LogicalLine] = []
    parts: list[str] = []
    origins: list[tuple[int, int]] = []
    width = 0

    def flush() -> None:
        nonlocal width
        if parts:
            blocks.append(LogicalLine(" ".join(parts), tuple(origins)))
        parts.clear()
        origins.clear()
        width = 0

    for number, line in enumerate(text.splitlines(), 1):
        if _BLOCK_START.match(line):
            flush()
            if line.strip():
                blocks.append(LogicalLine(line, ((0, number),)))
            continue
        origins.append((width, number))
        parts.append(line)
        width += len(line) + 1
    flush()
    return tuple(blocks)


def parse_citations(text: str, doc: str) -> tuple[Citation, ...]:
    """Every citation in one plan document, with its adjoining fragment."""
    found: list[Citation] = []
    for block in _logical_lines(text):
        spans = list(_SPAN.finditer(block.text))
        for index, span in enumerate(spans):
            match = _CITATION.match(span.group(1))
            if match is None:
                continue
            found.append(
                Citation(
                    doc=doc,
                    doc_line=block.source_line(span.start()),
                    target=match.group("target"),
                    start=int(match.group("start")),
                    end=int(match.group("end") or match.group("start")),
                    fragment=_adjoining_fragment(block.text, spans, index),
                )
            )
    return tuple(found)


@lru_cache(maxsize=1)
def _basename_index() -> dict[str, tuple[str, ...]]:
    """Repository files by path suffix, for resolving a bare citation target."""
    index: dict[str, tuple[str, ...]] = {}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(REPO_ROOT)
        if UNINDEXED_DIRS & set(relative.parts):
            continue
        posix = relative.as_posix()
        parts = posix.split("/")
        for depth in range(len(parts)):
            suffix = "/".join(parts[depth:])
            index[suffix] = index.get(suffix, ()) + (posix,)
    return index


def resolve_target(target: str) -> tuple[Path | None, str]:
    """The file a citation names, or ``None`` with the reason it did not resolve."""
    normalized = target.replace("\\", "/")
    direct = REPO_ROOT / normalized
    if direct.is_file():
        return direct, ""
    matches = _basename_index().get(normalized, ())
    if not matches:
        return None, f"names no file in this repository ({target})"
    if len(matches) > 1:
        return None, f"is ambiguous — {len(matches)} files match: {', '.join(matches)}"
    return REPO_ROOT / matches[0], ""


def _squash(text: str) -> str:
    """Text with every whitespace character removed, for insensitive matching."""
    return re.sub(r"\s+", "", text)


@lru_cache(maxsize=None)
def _source_lines(path: Path) -> tuple[str, ...]:
    return tuple(path.read_text(encoding="utf-8", errors="replace").splitlines())


@lru_cache(maxsize=None)
def _definition_extents(path: Path) -> Mapping[str, tuple[tuple[int, int], ...]]:
    """Line extents of every ``def``/``class``/module constant a Python file defines.

    A citation landing inside one of these is "at" the name that owns it, which
    is how a plan names an enclosing function and cites a block within it.
    """
    if path.suffix != ".py":
        return {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return {}
    extents: dict[str, tuple[tuple[int, int], ...]] = {}

    def record(name: str, node: ast.AST) -> None:
        span = (node.lineno, getattr(node, "end_lineno", node.lineno) or node.lineno)
        extents[name] = extents.get(name, ()) + (span,)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            record(node.name, node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    record(target.id, node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            record(node.target.id, node)
    return extents


def _fragment_segments(fragment: str) -> tuple[str, ...]:
    """A fragment split into the names it is made of.

    A document writes ``Owner.member`` so the reader knows whose member it is;
    the source line at the citation holds only the member.  The last segment is
    therefore the locator and the leading ones are claims the file must still
    satisfy somewhere — a renamed owner is a divergence even when its member
    is exactly where the citation says.
    """
    stripped = fragment.strip()
    if _QUALIFIED.match(stripped):
        return tuple(stripped.rstrip("()").split("."))
    return (stripped,)


def check_citations(citations: Iterable[Citation]) -> tuple[Finding, ...]:
    """Every citation that names no file, no such line, or a moved fragment."""
    findings: list[Finding] = []
    for citation in citations:
        path, reason = resolve_target(citation.target)
        if path is None:
            findings.append(
                Finding("citations", citation.doc, citation.doc_line, reason)
            )
            continue
        lines = _source_lines(path)
        if citation.end > len(lines):
            findings.append(
                Finding(
                    "citations",
                    citation.doc,
                    citation.doc_line,
                    f"cites {citation.target}:{citation.end}, past its last line "
                    f"({len(lines)}) — the file shrank under the citation",
                )
            )
            continue
        if citation.fragment is None:
            continue
        findings.extend(_check_fragment(citation, path, lines))
    return tuple(findings)


def _check_fragment(
    citation: Citation, path: Path, lines: Sequence[str]
) -> tuple[Finding, ...]:
    """The fragment half: at the cited location, drifted, or gone."""
    segments = _fragment_segments(citation.fragment or "")
    name = segments[-1]
    probe = _squash(name)
    where = path.relative_to(REPO_ROOT).as_posix()
    whole = _squash("".join(lines))

    orphaned = [owner for owner in segments[:-1] if _squash(owner) not in whole]
    if orphaned:
        return (
            Finding(
                "citations",
                citation.doc,
                citation.doc_line,
                f"fragment `{citation.fragment}` names {', '.join(orphaned)}, which "
                f"is nowhere in {where} — a plan/tree divergence to escalate",
            ),
        )

    window = _squash(
        "".join(
            lines[
                max(0, citation.start - 1 - CITATION_WINDOW) : citation.end
                + CITATION_WINDOW
            ]
        )
    )
    if probe in window:
        return ()

    if _IDENTIFIER.match(name):
        for start, end in _definition_extents(path).get(name, ()):
            if start <= citation.start and citation.end <= end:
                return ()

    at = tuple(number for number, line in enumerate(lines, 1) if probe in _squash(line))
    if not at:
        return (
            Finding(
                "citations",
                citation.doc,
                citation.doc_line,
                f"fragment `{citation.fragment}` is nowhere in {where} — a "
                "plan/tree divergence to escalate, not a line number to refresh",
            ),
        )
    return (
        Finding(
            "citations",
            citation.doc,
            citation.doc_line,
            f"`{citation.target}:{citation.start}` has drifted: fragment "
            f"`{citation.fragment}` is at {where}:{at[0]}"
            + (f" (also {', '.join(str(n) for n in at[1:4])})" if len(at) > 1 else "")
            + " — refresh the locator in a doc-only commit",
        ),
    )


# ---------------------------------------------------------------------------
# Check 2 — golden shape figures
# ---------------------------------------------------------------------------

_STANDALONE_INT = re.compile(r"(?<![\w.\-])(\d+)(?![\w.\-])")
_BARE_GOLDEN = re.compile(r"(?<![\w/.\-])golden(?![\w/.\-])", re.IGNORECASE)


def live_golden_counts(fingerprints: Mapping[str, Any]) -> dict[int, tuple[str, ...]]:
    """Every golden shape count in the receipt, keyed by value.

    Read at run time and never typed: the receipt is the sole home of these
    figures, so the gate that forbids restating them must learn them from it.
    """
    counts: dict[int, tuple[str, ...]] = {}
    for block in GOLDEN_FINGERPRINT_BLOCKS:
        for key, value in (fingerprints.get(block) or {}).items():
            if isinstance(value, int) and not isinstance(value, bool):
                counts[value] = counts.get(value, ()) + (f"{block}.{key}",)
    return counts


def _allowed(doc: str, value: int, line: str) -> bool:
    return any(row.admits(doc, value, line) for row in COLLISION_ALLOWLIST)


def check_golden_figures(
    doc: str, text: str, counts: Mapping[int, tuple[str, ...]]
) -> tuple[Finding, ...]:
    """Both prongs over one document (R-37 check 2)."""
    findings: list[Finding] = []
    retired = set(RETIRED_GOLDEN_FIGURES)
    for number, line in enumerate(text.splitlines(), 1):
        for match in _STANDALONE_INT.finditer(line):
            value = int(match.group(1))
            if _allowed(doc, value, line):
                continue
            if match.group(1) in retired:
                findings.append(
                    Finding(
                        "golden-figures",
                        doc,
                        number,
                        f"restates the retired golden figure {match.group(1)} — it "
                        "was retired because it reproduced under no definition",
                    )
                )
            elif value in counts:
                findings.append(
                    Finding(
                        "golden-figures",
                        doc,
                        number,
                        f"states {value}, which is {', '.join(counts[value])} in "
                        "campaign-fingerprints.json — that receipt is the sole "
                        "home of every golden shape count (criterion 4)",
                    )
                )
    for block in _logical_lines(text):
        findings.extend(_check_proximity(doc, block))
    return tuple(findings)


def _keyword_token_indices(tokens: Sequence[str]) -> tuple[int, ...]:
    hits: list[int] = []
    for index, token in enumerate(tokens):
        lowered = token.lower()
        if _BARE_GOLDEN.search(token) or any(
            keyword in lowered for keyword in GOLDEN_SHAPE_KEYWORDS[1:]
        ):
            hits.append(index)
    return tuple(hits)


def _check_proximity(doc: str, block: LogicalLine) -> tuple[Finding, ...]:
    """The second prong: an integer beside a shape keyword must cite the receipt.

    Measured over the paragraph for the same reason adjacency is: a keyword and
    the figure it labels are as adjacent to a reader across a line wrap as they
    are within one line.
    """
    words = list(re.finditer(r"\S+", block.text))
    tokens = [word.group() for word in words]
    keywords = _keyword_token_indices(tokens)
    if not keywords:
        return ()
    findings: list[Finding] = []
    for index, token in enumerate(tokens):
        match = _STANDALONE_INT.search(token)
        if match is None:
            continue
        if not any(abs(index - hit) <= PROXIMITY_TOKENS for hit in keywords):
            continue
        value = int(match.group(1))
        number = block.source_line(words[index].start())
        if _allowed(doc, value, block.text):
            continue
        neighbourhood = tokens[
            max(0, index - PROXIMITY_TOKENS) : index + PROXIMITY_TOKENS + 1
        ]
        if any(FINGERPRINT_MARKER in near for near in neighbourhood):
            continue
        findings.append(
            Finding(
                "golden-figures",
                doc,
                number,
                f"states {value} beside a golden shape keyword with no "
                f"`{FINGERPRINT_MARKER}` citation marker — a shape figure a "
                "reader cannot regenerate is how the retired one survived",
            )
        )
    return tuple(findings)


# ---------------------------------------------------------------------------
# Check 3 — the decision inventory
# ---------------------------------------------------------------------------

_TABLE_DECISION = re.compile(r"^\|\s*(D-\d+)\s*\|")
_SPLIT_ROW = re.compile(r"^\|\s*\*\*(D-\d+)\*\*\s*\|\s*(.+?)\s*\|\s*$")
_MANIFEST_DOC = re.compile(r"`([^`]+\.md)`")
_ID_RANGE = re.compile(r"D-(\d+)\s*(?:…|\.\.\.)\s*D-(\d+)")
_ID = re.compile(r"D-(\d+)")
_EXCEPT = re.compile(r"except\s+((?:D-\d+(?:(?:,|\s+and)\s+)?)+)")
_RESERVE_PHRASE = "are unassigned reserve gaps"


def _identifier(number: int) -> str:
    return f"D-{number:02d}"


def declared_decisions(umbrella: str) -> tuple[str, ...]:
    """Every decision id the umbrella's decision tables define, in order."""
    return tuple(
        match.group(1)
        for line in umbrella.splitlines()
        if (match := _TABLE_DECISION.match(line))
    )


def split_halves(umbrella: str) -> dict[str, str]:
    """The split table: decision id to the sentence naming every half."""
    return {
        match.group(1): match.group(2)
        for line in umbrella.splitlines()
        if (match := _SPLIT_ROW.match(line))
    }


def reserve_gaps(umbrella: str) -> tuple[str, ...]:
    """The unassigned ids the manifest declares non-existent rather than missing."""
    end = umbrella.index(_RESERVE_PHRASE)
    start = umbrella.rindex("**", 0, end)
    phrase = umbrella[start + 2 : end]
    numbers: set[int] = set()
    for low, high in _ID_RANGE.findall(phrase):
        numbers |= set(range(int(low), int(high) + 1))
    numbers |= {int(one) for one in _ID.findall(phrase)}
    return tuple(_identifier(number) for number in sorted(numbers))


def manifest_owners(
    umbrella: str, declared: Sequence[str]
) -> dict[str, tuple[str, ...]]:
    """Which documents each declared id is owned by, per the manifest table.

    The manifest is authoritative (umbrella *Shape*), so ownership is read from
    it and never from a phase header.  A row owns decisions iff its cell says
    ``Owns``; the umbrella's own row lists what it *documents* and says no such
    thing, which is exactly the discriminator.
    """
    known = set(declared)
    owners: dict[str, list[str]] = {}
    for line in umbrella.splitlines():
        if not line.startswith("|") or "Owns" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        document = _MANIFEST_DOC.search(cells[0])
        if document is None:
            continue
        segment = cells[-1][cells[-1].find("Owns") :]
        ids: set[str] = set()
        for low, high in _ID_RANGE.findall(segment):
            ids |= {
                identifier
                for identifier in known
                if int(low) <= int(identifier.split("-")[1]) <= int(high)
            }
        ids |= {
            identifier
            for one in _ID.findall(segment)
            if (identifier := _identifier(int(one))) in known
        }
        for excepted in _EXCEPT.findall(segment):
            ids -= {_identifier(int(one)) for one in _ID.findall(excepted)}
        for identifier in ids:
            owners.setdefault(identifier, []).append(document.group(1))
    return {identifier: tuple(docs) for identifier, docs in owners.items()}


def derive_inventory(umbrella: str) -> dict[str, Any]:
    """The inventory the umbrella's manifest and decision tables actually declare."""
    declared = declared_decisions(umbrella)
    owners = manifest_owners(umbrella, declared)
    halves = split_halves(umbrella)
    return {
        "schema_version": 1,
        "derived_from": f"docs/plans/{UMBRELLA_NAME}",
        "note": (
            "Derived, never hand-reconciled: scripts/plan_audit.py re-computes this "
            "from the umbrella's manifest and decision tables and fails when the two "
            "disagree (R-37 check 3, umbrella criterion 11).  Regenerate with "
            "`python scripts/plan_audit.py --write-inventory`."
        ),
        "reserve_gaps": list(reserve_gaps(umbrella)),
        "decisions": [
            {
                "id": identifier,
                "documents": sorted(owners.get(identifier, ())),
                "split": identifier in halves,
                **({"halves": halves[identifier]} if identifier in halves else {}),
            }
            for identifier in declared
        ],
    }


def check_inventory(
    derived: Mapping[str, Any], committed: Mapping[str, Any] | None
) -> tuple[Finding, ...]:
    """The committed inventory against the umbrella, plus the governance clauses."""
    name = INVENTORY_PATH.name
    findings: list[Finding] = []

    gaps = set(derived["reserve_gaps"])
    declared = {row["id"] for row in derived["decisions"]}
    for identifier in sorted(gaps & declared):
        findings.append(
            Finding(
                "decision-inventory",
                UMBRELLA_NAME,
                0,
                f"{identifier} is declared by a decision table and also listed as an "
                "unassigned reserve gap — the manifest cannot mean both",
            )
        )
    for row in derived["decisions"]:
        if not row["documents"]:
            findings.append(
                Finding(
                    "decision-inventory",
                    UMBRELLA_NAME,
                    0,
                    f"{row['id']} is declared but no manifest row claims it",
                )
            )
        elif len(row["documents"]) > 1 and not row["split"]:
            findings.append(
                Finding(
                    "decision-inventory",
                    UMBRELLA_NAME,
                    0,
                    f"{row['id']} is owned by {len(row['documents'])} documents "
                    f"({', '.join(row['documents'])}) but the split table does not "
                    "name it — an unsplit decision has exactly one owner",
                )
            )

    if committed is None:
        findings.append(
            Finding("decision-inventory", name, 0, "is missing — nothing to diff-gate")
        )
        return tuple(findings)

    if list(committed.get("reserve_gaps", ())) != list(derived["reserve_gaps"]):
        findings.append(
            Finding(
                "decision-inventory",
                name,
                0,
                f"reserve gaps {committed.get('reserve_gaps')} do not match the "
                f"manifest's {derived['reserve_gaps']}",
            )
        )
    committed_rows = {row["id"]: row for row in committed.get("decisions", ())}
    derived_rows = {row["id"]: row for row in derived["decisions"]}
    for identifier in sorted(set(derived_rows) - set(committed_rows)):
        findings.append(
            Finding(
                "decision-inventory",
                name,
                0,
                f"{identifier} is declared by the umbrella and absent from the inventory",
            )
        )
    for identifier in sorted(set(committed_rows) - set(derived_rows)):
        findings.append(
            Finding(
                "decision-inventory",
                name,
                0,
                f"{identifier} is in the inventory and declared by no decision table",
            )
        )
    for identifier in sorted(set(derived_rows) & set(committed_rows)):
        if committed_rows[identifier] != derived_rows[identifier]:
            findings.append(
                Finding(
                    "decision-inventory",
                    name,
                    0,
                    f"{identifier} reads {committed_rows[identifier]} but the "
                    f"manifest declares {derived_rows[identifier]}",
                )
            )
    return tuple(findings)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def audit(
    *,
    documents: Sequence[Path] | None = None,
    fingerprints: Mapping[str, Any] | None = None,
    inventory: Mapping[str, Any] | None = None,
) -> tuple[Finding, ...]:
    """Every finding across the three checks — an empty tuple is the pass condition."""
    paths = plan_documents() if documents is None else tuple(documents)
    if fingerprints is None:
        fingerprints = _load_json(FINGERPRINTS_PATH) or {}
    counts = live_golden_counts(fingerprints)

    findings: list[Finding] = []
    umbrella = ""
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if path.name == UMBRELLA_NAME:
            umbrella = text
        findings.extend(check_citations(parse_citations(text, path.name)))
        findings.extend(check_golden_figures(path.name, text, counts))

    if umbrella:
        committed = _load_json(INVENTORY_PATH) if inventory is None else dict(inventory)
        findings.extend(check_inventory(derive_inventory(umbrella), committed))
    return tuple(findings)


def write_inventory(path: Path = INVENTORY_PATH) -> int:
    """Re-derive the committed inventory from the umbrella."""
    umbrella = (PLANS_DIR / UMBRELLA_NAME).read_text(encoding="utf-8")
    path.write_text(
        json.dumps(derive_inventory(umbrella), indent=1) + "\n", encoding="utf-8"
    )
    print(f"plan audit: wrote {path.relative_to(REPO_ROOT).as_posix()}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: the gate, or a re-derivation of the inventory."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write-inventory",
        action="store_true",
        help="re-derive docs/receipts/decision-inventory.json from the umbrella",
    )
    args = parser.parse_args(argv)
    if args.write_inventory:
        return write_inventory()

    findings = audit()
    for finding in findings:
        print(f"plan audit: {finding}", file=sys.stderr)
    if findings:
        return 1
    print(f"plan audit: {len(plan_documents())} plan documents clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
