"""Criterion 3's third clause: every number a view emits is already a leaf.

*"A runtime fixture over the four bench scenarios asserts every numeric field
a view emits is bit-identical to a leaf already present in ``WalkResult``/
``Program``."*

The AST check next door proves no view **contains** arithmetic.  This one
proves the consequence the criterion actually cares about: that the numbers
which come out the other end are the walk's own.  A view could satisfy the
first and fail this one by reading a number off something that is neither the
program nor the result -- a module-level cache, a request, a second walk --
and that is precisely the shape ("a number that reached a view by some other
route") the one-walk criterion was written against.

**The rule, stated so the verdict is reproducible** (R-29):

*The haystack.*  Every ``float`` reachable from the ``Program`` and the
``WalkResult`` handed to the view -- dataclass fields, the kernel's state
dicts and pool records, the three event streams, the folds, the roster's
stats -- collected once per scenario.  ``bool`` is not a number here, for the
same reason the payload-schema check excludes it.

*The needles.*  Every ``float`` in the payload the view returned.

*The match.*  Bit-identical to a haystack value, **or** bit-identical to one
rounded at one of the digit counts ``program/precision`` declares.  The
second clause is there because rounding is presentation (D-71) and every
published digit count comes from that registry -- a rule this check reads
rather than restates.

*The scenarios.*  The four the bench harness declares, each at its own
``PROBE_BUILDS`` loadout, run through the same composition
``/api/calculate`` runs.  Both projections are checked: the receipt payload
and the score payload, because they are two views of one walk and the
criterion is about views rather than about endpoints.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bench_coupled_optimizer import PROBE_BUILDS, SCENARIOS  # noqa: E402
from src.calculator.defensive_effects import resolve_starting_defenses  # noqa: E402
from src.calculator.participant_timeline import (  # noqa: E402
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.program import precision  # noqa: E402
from src.calculator.program.views import receipt as receipt_view  # noqa: E402
from src.calculator.program.views import score as score_view  # noqa: E402
from src.calculator.scenario import (
    parse_scenario_request,
    resolve_scenario,
)  # noqa: E402
from src.calculator.stats import calculate_total_stats  # noqa: E402

#: Every digit count the precision registry declares, read rather than typed.
DECLARED_DIGITS = frozenset(precision.ROUNDING.values())


def _request(name: str) -> dict:
    """One bench scenario as a calculate request, at its pinned loadout.

    The build comes from ``PROBE_BUILDS`` for the reason the bench harness
    pins it: a scenario is only comparable across commits when the items are
    the same ones, and a fixture that let the search choose would be testing
    a different roster on every run.
    """
    request = dict(SCENARIOS[name])
    request.update(PROBE_BUILDS[name])
    request.setdefault("fight_mode", "one_rotation")
    return request


def _floats(node: object, into: set[float], seen: set[int]) -> None:
    """Every float reachable from *node*, following the shapes the walk uses."""
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, bool):
        return
    if isinstance(node, float):
        into.add(node)
        return
    if isinstance(node, int):
        # An ordinal is not a quantity, but the walk stores whole numbers as
        # ints in places a view republishes as floats, so they count as
        # available leaves rather than as published ones.
        into.add(float(node))
        return
    if isinstance(node, Mapping):
        for value in node.values():
            _floats(value, into, seen)
        return
    if isinstance(node, (list, tuple, set, frozenset)):
        for value in node:
            _floats(value, into, seen)
        return
    slots = getattr(node, "__slots__", None)
    if slots is not None:
        for name in slots:
            _floats(getattr(node, name, None), into, seen)
        return
    members = getattr(node, "__dict__", None)
    if isinstance(members, Mapping):
        for value in members.values():
            _floats(value, into, seen)


def _published(node: object, path: str, into: dict[str, float]) -> None:
    """Every float the payload publishes, keyed by the path it lives at."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key == "dispositions":
                continue
            _published(value, f"{path}.{key}" if path else str(key), into)
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            _published(value, f"{path}[{index}]", into)
    elif isinstance(node, bool):
        return
    elif isinstance(node, float):
        into[path] = node


def _projections(name: str) -> list[tuple[str, dict, object, object]]:
    """The receipt and score payloads of one scenario, beside their inputs."""
    captured: list[tuple[str, dict, object, object]] = []

    def spy(label, module, attribute):
        original = getattr(module, attribute)

        def wrapped(program, result):
            payload = original(program, result)
            captured.append((label, payload, program, result))
            return payload

        return original, wrapped

    parsed = parse_scenario_request(_request(name), deterministic=True)
    resolved = resolve_scenario(parsed)
    params = resolved.fight_params
    stats = calculate_total_stats(
        resolved.champion_data,
        parsed.level,
        list(resolved.items),
        item_options=params.item_options,
        role=params.role,
        role_quest_complete=params.role_quest_complete,
        external_stat_bonuses=params.ally_stat_bonuses,
    )
    defenses = resolve_starting_defenses(
        resolved.champion_data["name"],
        parsed.level,
        stats,
        list(resolved.items),
        item_options=params.item_options,
    )
    originals = {}
    for label, module, attribute in (
        ("receipt", receipt_view, "receipt"),
        ("score", score_view, "score"),
    ):
        originals[(module, attribute)], wrapped = spy(label, module, attribute)
        setattr(module, attribute, wrapped)
    try:
        for score_mode in (False, True):
            build_participant_timeline(
                resolved.champion_data,
                parsed.level,
                list(resolved.items),
                params,
                main_stats=stats,
                main_defenses=defenses,
                enemies=list(resolved.enemies),
                allies=list(resolved.allies),
                include_receipt=not score_mode,
                search_context=CoupledSearchContext() if score_mode else None,
                pair_result_cache={} if score_mode else None,
            )
    finally:
        for (module, attribute), original in originals.items():
            setattr(module, attribute, original)
    return captured


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_number_a_view_emits_is_a_leaf_of_the_walk(scenario: str) -> None:
    """The four bench scenarios, both projections, every published float."""
    projections = _projections(scenario)
    assert {label for label, _, _, _ in projections} == {"receipt", "score"}
    for label, payload, program, result in projections:
        available: set[float] = set()
        _floats(program, available, set())
        _floats(result, available, set())
        assert available, "a walk with no numbers in it cannot prove anything"
        rounded = {
            round(value, digits) for value in available for digits in DECLARED_DIGITS
        }
        published: dict[str, float] = {}
        _published(payload, "", published)
        assert published, f"{scenario}/{label} published no numbers"
        invented = {
            path: value
            for path, value in published.items()
            if value not in available and value not in rounded
        }
        assert not invented, f"{scenario}/{label} invented: {sorted(invented.items())}"


def _invented(scenario: str, label: str) -> dict[str, float]:
    """The published numbers no leaf of *scenario*'s walk can account for."""
    for found, payload, program, result in _projections(scenario):
        if found != label:
            continue
        available: set[float] = set()
        _floats(program, available, set())
        _floats(result, available, set())
        rounded = {
            round(value, digits) for value in available for digits in DECLARED_DIGITS
        }
        published: dict[str, float] = {}
        _published(payload, "", published)
        return {
            path: value
            for path, value in published.items()
            if value not in available and value not in rounded
        }
    raise AssertionError(f"no {label} projection was captured")


def test_a_view_that_adds_is_caught_by_this_fixture() -> None:
    """R-05: the check ships with the red it exists to reproduce.

    The doctored view emits every survival number one part in a billion off
    the walk's own -- the smallest lie the campaign's rounding rules could
    hide, far under golden's two decimals and under every declared precision.
    A check that could not see this one would be a check that only catches
    arithmetic somebody spelled loudly.
    """
    from src.calculator.program.views import survival as survival_view

    assert not _invented("cassiopeia_3champ", "receipt")
    original = survival_view.round_field
    survival_view.round_field = lambda field, value: original(field, value) + 1e-9
    try:
        invented = _invented("cassiopeia_3champ", "receipt")
    finally:
        survival_view.round_field = original
    assert invented, "a one-part-in-a-billion invention went unnoticed"
    # Only the doctored view's rows, wherever the payload republishes them.
    assert all("survival" in path for path in invented), sorted(invented)
