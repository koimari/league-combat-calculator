# Phase 1 — Machine-Checked Coverage Evidence

Contract: [umbrella](2026-08-08-silent-failure-campaign.md) · protocol:
[runbook](silent-failure-runbook.md) · entry gate: [Phase 0](phase-0-gates-and-corrections.md)
· pairing evidence from [Phase 2](phase-2-trigger-bus.md) · successor:
[Phase 3](phase-3-behavior-rules.md). Owns **D-20…D-26, D-45, D-91, D-95**; D-92 is Phase 2's,
and every other cross-phase fact and number is the umbrella's. Closes the incident's fourth
layer: prose that survived a missing implementation. Prerequisites: Phase 0 complete and Phase
2 merged (barrier B2 — the capability registry backs the dual-sided claims). Worktree lane
**L3, alone within the serial chain** — `tests/conftest.py` is a global collection hook, so no
other chain lane may be live; L6 may be, because the hook is purely additive and
collection-order-independent (runbook, *Shape* — the paragraph under the worktree ownership map).

## Goal

Every coverage claim `item_coverage.py` makes carries typed evidence that resolves
against the real codebase, so an unbacked claim fails at import or on the very next
`pytest` run instead of surviving as prose.

## Decisions

**Evidence, not a classifier rewrite (D-91).** The sidecar attaches to the *existing*
registries. No `item_claims.py`, no replacement claim corpus, no deletion of the ten
private containers, no derivation of `item_model_coverage`. *Why: the classifier flip is
one event; doing it twice guarantees a merge nobody can attribute — Phase 3's step 3.8 owns it.*

**A claim's subject is an item *or* a precedence rule.** Hand-listed families
(`_STATEFUL_MODELED_ITEMS`, `_REVIEWED_STATS_ONLY`, the three `_TARGET_*` dicts, and the
five attacker special cases) get one claim per `(item, lane)`. Dynamic families —
`ITEM_EFFECTS` membership, `ITEM_INPUT_OPTIONS` membership, `_has_described_effect`, the
cached-record test, the target lane's `review_pending` passthrough — get one claim per
*rule*, because their membership is recomputed from `data/` on every call. *Why: the
alternative is 648 hand records (D-91 forbids it) or leaving the dynamic majority — 123
`ITEM_EFFECTS` items alone — unbacked.*

**A rule-claim declares its population, or it backs 123 items with one witness.** Every
rule-claim carries a **membership predicate as a resolvable dotted path**; the resolver
enumerates the population and asserts each member either resolves to its own backing (an
item claim, or a parametrized `TestRef` id containing the member name) or appears in
`FRONTIER` with an issue ref. The enumerated population is written into the classification
receipt. *Why: without this a rule-claim is one `Symbol` and one `TestRef` standing for a
whole registry — the exact "one sentence covers everything" shape this phase exists to kill,
reproduced inside its own evidence union.*

**`Claim.status` is a pinned expectation, never an authority.** The classifier stays the
only answer to "what is this item's coverage"; a resolution-tier check asserts the two
agree for every cached item, and a source assertion forbids any `src/` reader of
`Claim.status` outside the load gate. *Why: an authored status is what makes the
requirement matrix checkable with no imports and no `data/` read; the equality check is
what stops it becoming a second truth.*

**Evidence is a closed nine-member union** — `Symbol`, `PacketSource`, `PairedSides`,
`EffectKey`, `EffectTag`, `OptionSchema`, `TestRef`, `SourceRef`, `Absence` —
and every member **holds strings, never objects**. `StreamMembership` is dropped: it would
resolve against five name sets Phase 2 deletes. *Why: an open vocabulary is prose with a
dataclass around it, and the strings-only rule keeps `coverage_evidence.py` a stdlib leaf
nothing can cycle against while making every read injectable.*

**Three failure tiers with a ruled boundary.** *Load* (import of `item_coverage`):
structural impossibility only — vocabulary, requirement matrix, key uniqueness,
dotted-path shape, closed dimensions; no imports, no filesystem, no `data/`, raising
`CoverageClaimError`. *Resolution* (any `pytest` run, including `-k` and a bisect): every
evidence member resolves against source, the registries, Phase 2's capability registry, and
the committed audit receipts. *Full session*: exact node ids, marker facts, duplicate-nodeid
detection, read from `config.stash`. *Why: the drift window must be one commit, and a
check that only runs on patch day runs after the incident.* (The unit is an **evidence
member**, never an "atom" — D-44 retires that word for declared units, and `atomizer.Atom`
already owns it in `src/`.)

**A filtered session downgrades a tier, never skips it.** `pytest.skip` prints green, so
full-session checks are not collected at all when `_is_full_session(config)` is false, and
the resolution tier independently proves the weaker fact by source scan. A test asserts
CI's pytest step carries no `-k`, `-m`, or path filter. *Why: a decorative tier launders
absence as success.*

**Resolver topology.** `tests/coverage_resolver.py` is an uncollected helper that
module-scope-imports nothing from `src.calculator` but `coverage_evidence`; every read
goes through `ResolverContext.importer` / `read_source` / `nodes`. *Why: production code
must not import pytest, the audit needs a collected node set, and three seams are the
entire mutation harness — a direct import would be an untestable branch.*

**Five rules on every `TestRef`** — four about skipping, one about relevance: the id
resolves to exactly one collected node; no `skip`/`skipif` marker at any level including
class and module `pytestmark`; no `xfail` in any form, strict or not; neither the body nor
any fixture in its closure calls `pytest.skip` or `pytest.importorskip`; and **the node is
about the claim** — its module text or its parametrization id contains the claim's
`subject`, or one of the claim's `Symbol` / `PacketSource` / `EffectKey` strings. A
`TestRef` failing relevance raises `EvidenceUnresolved` like any other. *Why: a claim
backed by a test that can pass without executing its assertions is the prose this phase
deletes — the repo already has four `pytest.skip("node is not installed")` calls of exactly
that shape — and without the fifth rule `tests/test_smoke.py::test_imports` discharges every
claim in the table.*

**Dual-sided evidence resolves against Phase 2, not a name list.** `PairedSides(mechanic)`
requires the `MechanicCapability` to exist with `authority == SPLIT`, its `pair_of` to
name a capability that points back, and both halves' `impl` and `packet_source` to
resolve. The pairing-exception set is asserted **empty** (D-92). *Why: the incident
shipped with one side present and a hand list that agreed with it.*

**M1–M9 are permanent tests driven through the seams; no source file is ever edited.**
Rename `item_effects.command_amp_effect`; delete `damage._apply_command_amp`; remove the
`"Imperial Mandate — Command"` packet literal; drop `owner=` from a dual-sided packet;
clear a `MechanicCapability`'s `pair_of`; rename an effect tag; a dangling `TestRef`; a
skip-guarded `TestRef`; **M9, an irrelevant `TestRef`** — a node id that resolves, is
unskipped and unxfailed, and has nothing to do with its claim. Each asserts the specific
`EvidenceUnresolved` it produces. *Why: "demonstrated once during development" is an
unverifiable claim about the past.* Two halves of the umbrella's criterion 2 are **not**
here and must not be re-claimed: emptying a trigger stream is Phase 2's A9, and the
number-level Command fixture is Phase 0's criterion 18. M1–M9 prove that *evidence
resolution* notices; they do not prove a number moves.

**`docs/receipts/item-coverage-classification.json` is this phase's numeric gate** — the
full public dict of both classifiers for every cached item on both lanes (648 records at
HEAD, read from **this receipt's own** `metadata.item_count` × 2, never from
`golden_baseline.json`'s field of the same name), captured from
unmodified behaviour before the sidecar lands and diff-gated after. *Why: golden is
near-vacuous here (`pipeline.py` does not import `item_coverage`), so per D-93 this phase
needs a non-golden gate, and only a before-image proves "evidence added, nothing moved".*

**`PRECEDENCE` lands beside the if/elif chain as a read-only derivation, not its
replacement**, with a test that it reproduces the live chain's status for every cached item
on both lanes and no `src/` consumer. *Why: D-98's derivation-beside-legacy template — it
makes Phase 3's step 3.8's flip a one-symbol commit and reachability computable now.*

**The shadowed set is derived and pinned as a set, never a count** — two independent
reproductions disagreed on 28 vs 29 — and every member carries a non-empty
`unreachable_reason`. *Why: a claim no cached item can reach is dead prose in a
live-looking home, and a wrong pinned integer is a second thing to maintain.*

**`UTILITY_DIMENSIONS` is closed at the measured dimension set;** a new member needs, in
the same commit, a claim carrying a `PacketSource` or `OptionSchema`, or a `FRONTIER` entry
with an issue ref. It is derived from `item_coverage._UTILITY_DIMENSIONS`, which is a
**43-key dict over 29 distinct dimension strings** — the set is the 29, and anyone counting
keys gets 43, which is why this is pinned as a set and never as an integer. At Phase 3's
step 3.8 it becomes a projection of `item_behavior.UtilityDimension`, the single home; that
is a **fifth declared handoff** into Phase 3, listed with the other four below. *Why: a
dimension that names no mechanism is a product label, and product labels drift into coverage
claims — and three homes for one vocabulary is the drift this campaign exists to end.*

**Front doors are derived and `SUBSTANTIAL_MODULE_FRONT_DOORS` is deleted (D-95).** A front
door is *a test module importing the production module's dotted path* — an `Import` or
`ImportFrom` node naming `src.calculator.<module>`, or naming its package and binding the
module as a symbol. A textual mention is not a front door, and `from src.calculator.survival
import X` imports the **package**, not `survival.transitions`; those two rules are what make
the count reproducible and they live in `front_door_report`, not in prose. The denominator is
read off the tree — `src/calculator/**/*.py` minus `__init__.py` — with `champions/` excluded
by declaration (its front door is the per-champion convention plus `champions/module_contract`
validation). `FRONT_DOOR_FRONTIER` is **whatever the instrument reports on the tip it is
pinned against**, by set equality, and no figure for it is written here: run against the
pre-campaign tree at `1274615` the derivation reports `application_errors`, `healing_legacy`,
`practice_dummy`, `request_parsing` and all six `survival/` submodules — the reading this
phase was planned from — and against the Phase 1 tip it reports the same list less
`survival/{accumulate, actions, compile, transitions}`, which Phase 0's and Phase 2's new
suites now import directly. A frontier pinned at the planning-time reading would have been red
on arrival, and the shrink is the frontier doing its job. *Why: a line threshold cannot
reproduce the hand tuple (`healing.py` is 71 lines), the tuple is itself the prose-registry
shape this campaign kills, and an earlier reading of this same frontier produced a shorter
list because the package-versus-submodule rule was unstated — a pin taken from that reading
would have been wrong on its first run.*

**Every new module a later phase adds owes a front door or an exclusion.** Phase 3 adds
`value_ref`, `item_behavior`, `item_behavior_catalog`, `interpreters/__init__` and 18
`interpreters/<family>` modules (**22**); Phase 4 adds 11 `program/*`, 5 `program/views/*` and
`survival/outcome_state` (**17**). Each names its test front door in its own Shape table, or declares
an exclusion the way `champions/` is excluded. *Why: `FRONT_DOOR_FRONTIER` is set-equality
gated, so the **38** new modules this frontier's own denominator counts — the 39 the two phases add,
less `interpreters/__init__`, which `src/calculator/**/*.py` minus `__init__.py` excludes — would break
the gate in the phase that added them and the cheapest fix would be to grow the frontier.*

**The claim frontier may not hold a damage or durability lane.** Economy, vision,
movement and stat-buff dimensions plus `stats_only` / `not_target_relevant` claims may sit
on `FRONTIER` with an issue ref; an attacker or target claim that prices damage or
durability may not. Measured authoring debt is roughly ten focused tests (Locket, Mikael's,
Stridebreaker, Echoes of Helia, Moonstone, Diadem, Dream Maker ×2, Iceborn Gauntlet); the
ten effect-tag claims blocked on umbrella decision **H4** enter `FRONTIER` naming H4. *Why:
a frontier that can absorb a damage claim is the escape hatch this campaign closes.*

**Migration frontier into Phase 3 — exactly five handoffs and nothing else.**
`COVERAGE_EVIDENCE` (3.8 extends it with compiler-derived evidence, never re-authors it),
`PRECEDENCE` (3.8's one-symbol flip target), the classification receipt (3.8 re-captures
with an enumerated diff against Phase 1's before-image), `FRONTIER` (3.8 may only
shrink it), and `UTILITY_DIMENSIONS` (3.8 makes it a projection of
`item_behavior.UtilityDimension` and deletes `item_coverage._UTILITY_DIMENSIONS`). The two
membership rule-claims are precisely the records Phase 3 replaces with per-family
declarations; frontier Counters 1–3 are Phase 3's to move. *Why: an undeclared handoff is how
two phases ended up owning `COMPILED_WALK_UNREPRESENTABLE_ITEMS` — and the utility vocabulary
was on its way to three homes for the same reason.*

## Shape

| File | Responsibility |
|---|---|
| `src/calculator/coverage_evidence.py` *(new)* | Evidence vocabulary, `Claim`, the requirement matrix, load-time validators. Stdlib only. |
| `src/calculator/item_coverage.py` *(edited)* | Gains `COVERAGE_EVIDENCE`, `PRECEDENCE`, `FRONTIER`, one import-time validate call. Chain and containers untouched. |
| `tests/coverage_resolver.py` *(new, uncollected)* | `ResolverContext` and the resolution of every evidence kind; the shadow, front-door and packet-site reports. |
| `tests/conftest.py` *(edited)* | Stashes the collected node set; answers `_is_full_session`. |
| `tests/test_coverage_evidence.py` *(new)* | Load-tier negatives, one per forbidden claim shape. |
| `tests/test_coverage_claims.py` *(new)* | Resolution and full-session tiers, the receipt gate, M1–M9. |
| `tests/test_architecture.py` *(edited)* | Consumes `front_door_report`; owns `FRONT_DOOR_FRONTIER`; the hand tuple is deleted. |
| `docs/receipts/item-coverage-classification.json` *(new)* | One record per (cached item, lane) — before-image and diff gate. |

```python
# src/calculator/coverage_evidence.py — stdlib only, no package import, no filesystem
ClaimLane     = Literal["attacker", "target", "support_packet", "utility"]      # D-45
ClaimStatus   = Literal["modeled_effect", "modeled_state", "stats_only", "blocked",
                        "review_pending", "modeled", "modeled_event_certified",
                        "not_target_relevant"]
SubjectKind   = Literal["item", "rule"]
SymbolRole    = Literal["pair_engine", "walk_packet_builder", "value_accessor",
                        "tag_handler", "certification_guard", "compiler"]
OwnerPolicy   = Literal["owner_skips_holder", "holder_is_not_a_source",
                        "holder_priced_by_walk"]
EvidenceRegistry = Literal["ITEM_EFFECTS", "ALLY_ITEM_EFFECTS", "RUNE_EFFECTS",
                           "ITEM_INPUT_OPTIONS"]   # deliberately NOT ValueRegistry: Phase 3's
                                                   # three-member ValueRegistry (D-46) must not
                                                   # admit ITEM_INPUT_OPTIONS, which only
                                                   # OptionSchema needs
UTILITY_DIMENSIONS: frozenset[str]     # the measured dimension set; admission ruled above

class Symbol:        """A dotted path and the role it plays — a claim's engine half."""
class PacketSource:  """A walk packet's exact ``source=`` string; ``{}`` is an f-string slot."""
class PairedSides:   """A Phase-2 mechanic id whose two engine halves must both exist."""
class EffectKey:     """One key in one value registry — the key, never its number (rule 5)."""
class EffectTag:     """One ``item_effects._KNOWN_EFFECT_TYPES`` member (38) with a live handler."""
class OptionSchema:  """A bounded ``ITEM_INPUT_OPTIONS`` control backing modeled_state."""
class TestRef:       """A pytest node id that must exist and must be able to fail."""
class SourceRef:     """A wiki url + revision id present in the committed full-entry audit."""
class Absence:       """The only evidence a negative claim may carry: reason + issue refs."""
Evidence = Symbol | PacketSource | PairedSides | EffectKey | EffectTag | OptionSchema \
         | TestRef | SourceRef | Absence

@dataclass(frozen=True, slots=True)
class Claim:
    """One coverage assertion about one item or rule, and what backs it."""
    subject_kind: SubjectKind; subject: str; lane: ClaimLane; status: ClaimStatus
    evidence: tuple[Evidence, ...]; dimensions: tuple[str, ...]
    issue_refs: tuple[int, ...]; unreachable_reason: str

@dataclass(frozen=True, slots=True)
class EvidencePolicy:
    """Which evidence kinds a lane/status cell must carry, must not, and how many."""
    required: frozenset[str]; forbidden: frozenset[str]; min_count: int

@dataclass(frozen=True, slots=True)
class PrecedenceRule:
    """One rung of the classifier chain as data: id, lane, the container or predicate
    name it keys on, and the status it yields. Read-only in this phase."""

class CoverageClaimError(ValueError):
    """A claim whose shape cannot be backed; raised at import, never caught."""

def status_policy(lane: ClaimLane, status: ClaimStatus) -> EvidencePolicy:
    """The matrix: modeled_* needs Symbol+TestRef; modeled_state needs OptionSchema;
    stats_only/not_target_relevant needs SourceRef and forbids PacketSource;
    blocked/review_pending needs exactly one Absence with issue refs;
    modeled_event_certified adds a certification_guard Symbol; support_packet needs a
    PacketSource, and PairedSides whenever Phase 2 declares SPLIT."""
def validate_evidence(ev: Evidence, *, claim: str) -> None:
    """Reject a malformed evidence member; ``claim`` only names it in the message."""
def validate_claim(claim: Claim) -> None:
    """Vocabulary, matrix, dotted-path shape, closed dimensions."""
def validate_claim_table(claims: Mapping[tuple[SubjectKind, str, ClaimLane], Claim]) -> None:
    """The load gate (D-20): per-claim validity, key uniqueness, no Absence on a
    positive claim, no positive evidence on a negative one. Pure; O(n)."""

# src/calculator/item_coverage.py — additions only
COVERAGE_EVIDENCE: Mapping[tuple[SubjectKind, str, ClaimLane], Claim]
PRECEDENCE: tuple[PrecedenceRule, ...]    # ordered mirror of the if/elif chain, read-only
FRONTIER: Mapping[str, str]               # claim key -> reason; shrinks by edit, never grows
validate_claim_table(COVERAGE_EVIDENCE)   # at import

# tests/coverage_resolver.py — the only place a string becomes an object
# Frozen report records, each naming its claim: EvidenceUnresolved, ShadowedClaim,
# MissingFrontDoor, PacketSite, TestRefVerdict, CollectedNode.
@dataclass(frozen=True, slots=True)
class ResolverContext:
    """The three seams. No module-level caching — a memo defeats every mutation."""
    importer: Callable[[str], object]; read_source: Callable[[str], str]
    nodes: Mapping[str, CollectedNode]
def live_context() -> ResolverContext:
    """The production seams — real importlib, real file reads, the stashed node set.
    The only zero-argument constructor; every mutation test builds its own."""
def resolve(ev: Evidence, ctx: ResolverContext, *, claim: str) -> None:
    """Single dispatch over the nine kinds; raises EvidenceUnresolved naming both."""
def resolve_table(claims, ctx) -> list[EvidenceUnresolved]:
    """Collect-all, report-all — one run names every broken member, not the first."""
def packet_sites(module_text: str) -> tuple[PacketSite, ...]:
    """Every call carrying ``source=``, with its keyword-name set.  Measured 29 in
    item_support_effects.py; the measurement, not a pinned integer, is the contract, and
    Phase 3's producer count is derived from it (len of the distinct ``source`` set)."""
def render_source_argument(node: ast.AST) -> str | None:
    """Render one ``source=`` argument; f-strings collapse to ``{}`` slots."""
def tag_dispatch_branches(module_text: str, qualname: str) -> frozenset[str]:
    """The effect tags a handler actually branches on — EffectTag's oracle."""
def test_ref_verdict(ref, ctx, *, full_session: bool) -> TestRefVerdict:
    """The four skip/xfail rules; downgrades to a source-defined check when filtered."""
def first_matching_rule(precedence, item, lane) -> PrecedenceRule:
    """The chain as data — asserted equal to the live classifier for every cached item."""
def shadow_report(precedence, cached_items) -> tuple[ShadowedClaim, ...]:
    """Every claim no cached item can reach, with the rule that outranks it."""
def front_door_report(src_root: Path, test_root: Path) -> tuple[MissingFrontDoor, ...]:
    """Modules outside champions/ that no test module imports (D-95)."""

# tests/conftest.py — additions only
def pytest_collection_modifyitems(config, items) -> None:
    """Stash the collected node set with markers and fixture closures."""
def _is_full_session(config) -> bool:
    """True when no -k, -m, or path filter narrowed collection."""
```

## Success criteria

1. `docs/receipts/item-coverage-classification.json` holds one record per `(cached item,
   lane)` — the full public dict of both classifiers, read from **that receipt's own**
   `metadata.item_count` × 2 rather than a typed integer, 648 at HEAD. It is a coverage-record
   count, not a golden leaf or entry count, and it never reads `golden_baseline.json`'s
   like-named field, so umbrella criterion 4 does not reach it. A fresh capture on the phase tip
   diffs to **zero**.
2. Importing `item_coverage` with a malformed claim raises `CoverageClaimError`; the load
   gate performs no import of a described module, no filesystem read and no `data/` read,
   asserted by a source assertion over `coverage_evidence.py`, which has no package import.
3. `resolve_table(COVERAGE_EVIDENCE, live_context())` returns an empty list, and every
   rule-claim's enumerated population is fully backed — each member resolving to its own
   claim, a parametrized `TestRef` id, or a `FRONTIER` entry with an issue ref.
4. Every hand-listed entry in the **seven non-empty** `item_coverage.py` containers and every
   rule in `PRECEDENCE` carries exactly one claim on its lane; `(subject_kind, subject, lane)`
   is unique; unclaimed hand entries number zero. The three empty containers
   (`_BLOCKED_REASONS`, `_CALCULATION_ALLOWED_BLOCKED`, `_PARTIAL_BLOCKED_REASONS` — all empty at
   HEAD, but as two dicts and one frozenset: `_CALCULATION_ALLOWED_BLOCKED` is `frozenset()` at
   `item_coverage.py:60`, so the assertion is emptiness, never `== {}`) are asserted **empty**
   rather than claim-covered, and Phase 3's step 3.8 deletes
   them — so "ten registries collapse to two" is seven real ones plus three already-empty.
5. `first_matching_rule` reproduces the live classifier's status for every cached item on both
   lanes, and no `src/` module consumes `PRECEDENCE`.
6. Every claim `shadow_report` returns carries a non-empty `unreachable_reason`, and the
   shadowed set matches the receipt's derived shadow section by set equality — no count is
   authored anywhere.
7. Every `TestRef` passes all five rules; one naming a skipped, xfailed, fixture-skipped,
   duplicated **or irrelevant** node fails the suite. Under `-k` filtering the resolution tier
   still fails a dangling `TestRef`, and no coverage test ever reports as `skipped`.
8. A test asserts `.github/workflows/tests.yml` runs `pytest` with no `-k`, `-m`, or path
   filter, so the full-session tier is not decorative.
9. Every claim whose Phase-2 capability declares `authority == SPLIT` carries a
   `PairedSides` **evidence member** — the word "atom" is retired for every unit this phase
   declares (D-44); both halves resolve, `pair_of` closes in both directions, and the
   pairing-exception set is **empty**.
10. M1–M9 are nine passing tests, each asserting the specific `EvidenceUnresolved` its
    mutation produces, with a clean working tree after `pytest`.
11. Each of the 38 `item_effects._KNOWN_EFFECT_TYPES` members either resolves to a handler
    branch outside the claim system or sits in `FRONTIER` naming H4; the union is total.
12. `UTILITY_DIMENSIONS` equals the measured dimension set by **set equality** — no count is
    authored anywhere, because the source dict has 43 keys over 29 distinct values and either
    integer is a plausible-looking wrong answer — and every dimension on every claim is a
    member.
13. `SUBSTANTIAL_MODULE_FRONT_DOORS` has zero occurrences in `src/`, `tests/` and `scripts/`
    — asserted by a text scan with its own injection seam, so a regrown registry is a finding
    rather than a review miss; the phase documents that ordered the deletion may name it.
    `front_door_report` equals `FRONT_DOOR_FRONTIER` by set equality; that frontier holds
    exactly the members the instrument measures on the tip, each with a reason and an owning
    phase (the surviving `survival/` members are Phase 4's); the package-versus-submodule and
    import-versus-mention rules live in `front_door_report`'s docstring; and the frontier
    lives in the consumer, not in the tool that measures it.
14. `FRONTIER` holds no attacker or target claim that prices damage or durability, and every
    member carries an issue ref.
15. `docs/item-umbrella-audit.json` and the full-entry audit receipt are byte-identical to
    their pre-phase state, and no `reason` string or status in `item_coverage.py` changed.
16. All eleven gates in the [runbook](silent-failure-runbook.md) matrix are green on the
    tip, including zero diffs on both golden baselines and identical bench counters,
    residual, winners and scores — this phase changes no number.
