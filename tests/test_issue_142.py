"""Issue #142 — fail closed on unknown support ``target_scope`` values.

The coupled resolver (``_support_target_ids``) used to land every
unrecognized / missing / structurally invalid scope in a terminal
catch-all that silently redirected the packet to teammate zero (or
dropped it for an enemy attacker) — contradicting the published
``fail_closed: True`` participant-ledger contract.  These tests lock the
closed vocabulary: every resolution scope has an explicit branch, the
terminal default is an unreachable exhaustiveness guard, and emitters
validate before any packet can be created.
"""

import inspect
from types import SimpleNamespace

import pytest

from src.calculator.capabilities import (
    PARTICIPANT_LEDGER_CONTRACT,
    SUPPORT_TARGET_RESOLUTION_SCOPES,
    SUPPORT_TARGET_SCOPES,
)
from src.calculator.participant_timeline import (
    Combatant,
    _support_effect_templates,
    _support_target_ids,
)
from src.calculator import support_effects
from src.calculator.support_effects import _SCOPE_OVERRIDES, _support_profile


def _combatant(participant_id: str, team: str, name: str) -> Combatant:
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": name},
        level=18,
        items=(),
        stats={},
        defenses=None,
        request=None,
    )


def _roster() -> list[Combatant]:
    ally = _combatant("ally:Lulu", "ally", "Lulu")
    main = _combatant("main", "main", "Lulu")
    enemy = _combatant("enemy:Ambessa", "enemy", "Ambessa")
    return [ally, main, enemy]


@pytest.mark.parametrize("actor", ["main", "ally:Lulu", "enemy:Ambessa"])
@pytest.mark.parametrize(
    "scope", ["typo_scope", "one_teammatee", None, 123, "", "self_and_all"]
)
def test_unknown_scope_fails_closed_for_all_teams(actor, scope):
    attacker = next(a for a in _roster() if a.participant_id == actor)
    effect = {"target_scope": scope, "source": "Test Shield"}
    with pytest.raises(ValueError) as exc:
        _support_target_ids(attacker, effect, _roster())
    message = str(exc.value)
    assert attacker.participant_id in message
    assert attacker.champion_data["name"] in message
    assert "Test Shield" in message
    assert repr(scope) in message
    for supported in sorted(SUPPORT_TARGET_RESOLUTION_SCOPES):
        assert supported in message


def test_missing_scope_key_fails_closed():
    attacker = _roster()[1]
    with pytest.raises(ValueError):
        _support_target_ids(attacker, {}, _roster())


# Expected tuples per actor in the shared roster [ally:Lulu, main,
# enemy:Ambessa].  The allied side is one bucket (main + ally), so an ally
# actor's teammates are [main] and an enemy actor has no teammates in this
# roster (the no-teammate fallbacks apply).
_EXPECTED = {
    "main": {
        "self": (["main"], "self"),
        "one_teammate": (["ally:Lulu"], "first_selected_teammate"),
        "all_teammates": (["ally:Lulu"], "all_selected_teammates"),
        "self_and_all_teammates": (
            ["main", "ally:Lulu"],
            "self_and_all_selected_teammates",
        ),
        "self_and_one_teammate": (
            ["main", "ally:Lulu"],
            "self_and_first_selected_teammate",
        ),
    },
    "ally:Lulu": {
        "self": (["ally:Lulu"], "self"),
        "one_teammate": (["main"], "first_selected_teammate"),
        "all_teammates": (["main"], "all_selected_teammates"),
        "self_and_all_teammates": (
            ["ally:Lulu", "main"],
            "self_and_all_selected_teammates",
        ),
        "self_and_one_teammate": (
            ["ally:Lulu", "main"],
            "self_and_first_selected_teammate",
        ),
    },
    "enemy:Ambessa": {
        "self": (["enemy:Ambessa"], "self"),
        "one_teammate": ([], "no_selected_teammate"),
        "all_teammates": ([], "no_selected_teammate"),
        "self_and_all_teammates": (
            ["enemy:Ambessa"],
            "self_only_no_selected_teammate",
        ),
        "self_and_one_teammate": (
            ["enemy:Ambessa"],
            "self_only_no_selected_teammate",
        ),
    },
}


@pytest.mark.parametrize("actor", ["main", "ally:Lulu", "enemy:Ambessa"])
@pytest.mark.parametrize(
    "scope",
    [
        "self",
        "one_teammate",
        "all_teammates",
        "self_and_all_teammates",
        "self_and_one_teammate",
    ],
)
def test_every_resolution_scope_has_an_explicit_branch(actor, scope):
    """The closed contract: every scope resolves to the exact tuple, with
    ``one_teammate`` promoted to an explicit branch (it previously rode the
    terminal catch-all)."""
    attacker = next(a for a in _roster() if a.participant_id == actor)
    expected = _EXPECTED[actor][scope]
    target_ids, policy = _support_target_ids(
        attacker, {"target_scope": scope}, _roster()
    )
    assert (target_ids, policy) == expected


def test_one_teammate_self_fallback_preserved():
    """Karma E / Orianna E self-or-target casts with no teammate still fall
    back to self when ``target_self`` is set."""
    main = _roster()[1]
    target_ids, policy = _support_target_ids(
        main,
        {"target_scope": "one_teammate", "target_self": True, "source": "Karma E"},
        [main],
    )
    assert (target_ids, policy) == (["main"], "self")


def test_self_and_all_teammates_no_teammate_falls_back_to_self():
    main = _roster()[1]
    target_ids, policy = _support_target_ids(
        main,
        {"target_scope": "self_and_all_teammates", "source": "Taric Q"},
        [main],
    )
    assert (target_ids, policy) == (["main"], "self_only_no_selected_teammate")


def test_no_catch_all_teammate_fallback():
    """The terminal catch-all is gone: the only ``teammates[0]`` return is
    inside the explicit ``one_teammate`` branch, and the function body ends
    with the unreachable exhaustiveness guard (repo precedent:
    tests/test_participant_timeline.py:4686)."""
    source = inspect.getsource(_support_target_ids)
    assert 'return [teammates[0].participant_id], "first_selected_teammate"' in source
    one_teammate_branch = (
        'if target_scope == "one_teammate":'
        + source.split('if target_scope == "one_teammate":', 1)[1]
    )
    assert one_teammate_branch.startswith(
        'if target_scope == "one_teammate":\n        # The one-teammate scope'
    )
    # The return is reachable only through the explicit branch: nothing after
    # it returns a first-teammate default, and the body ends on the guard.
    tail = source.split('if target_scope == "one_teammate":', 1)[1]
    assert "raise AssertionError" in tail
    assert "have drifted" in tail


def test_unknown_scope_template_rejected_before_application(monkeypatch):
    """A poisoned emitter result raises before any packet is appended."""
    attacker = _roster()[1]
    monkeypatch.setattr(
        "src.calculator.participant_timeline.derive_ally_effects",
        lambda *_args, **_kwargs: [
            {
                "time": 0.0,
                "kind": "shield",
                "amount": 100.0,
                "source": "poisoned",
                "target_scope": "typo_scope",
            }
        ],
    )
    support_effects: dict[str, list] = {}
    from src.calculator.participant_timeline import _attach_support_effects

    with pytest.raises(ValueError) as exc:
        _attach_support_effects(
            attacker,
            {"champion_stats": {"health": 2000.0}, "cast_timeline": []},
            _roster(),
            support_effects,
        )
    assert "typo_scope" in str(exc.value)
    assert support_effects == {}


def test_champion_emitter_validates_scope(monkeypatch):
    """derive_ally_effects itself rejects a scope outside the resolution set,
    naming the champion, slot, and supported values."""
    from src.calculator.support_effects import derive_ally_effects
    from src.calculator.data_fetcher import get_champion

    champion_data = get_champion("Lux")
    casts = [{"slot": "W", "time": 1.0}]
    # Sanity: the unpoisoned emitter accepts Lux W (scope override "self").
    derive_ally_effects(
        champion_data,
        18,
        {"ability_power": 0.0, "health": 2000.0},
        casts,
        ability_ranks={"W": 5},
    )
    monkeypatch.setattr(
        support_effects,
        "_SCOPE_OVERRIDES",
        {**support_effects._SCOPE_OVERRIDES, ("Lux", "W"): "typo_scope"},
    )
    with pytest.raises(ValueError) as exc:
        derive_ally_effects(
            champion_data,
            18,
            {"ability_power": 0.0, "health": 2000.0},
            casts,
            ability_ranks={"W": 5},
        )
    message = str(exc.value)
    assert "typo_scope" in message
    assert "Lux" in message
    assert "W" in message
    assert "Prismatic Barrier" in message


def test_support_profile_literals_are_closed():
    """Every literal the champion-side profile can emit is a resolution scope."""
    source = inspect.getsource(_support_profile)
    for scope in (
        "self_and_all_teammates",
        "self_and_one_teammate",
        "one_teammate",
        "self",
        "all_teammates",
    ):
        assert f'"{scope}"' in source
    for literal in (
        "self_and_all_teammates",
        "self_and_one_teammate",
        "one_teammate",
        "self",
        "all_teammates",
    ):
        assert literal in SUPPORT_TARGET_RESOLUTION_SCOPES


def test_scope_override_values_are_closed():
    for key, scope in _SCOPE_OVERRIDES.items():
        assert scope in SUPPORT_TARGET_RESOLUTION_SCOPES, key


def test_item_support_scope_literals_are_closed():
    """Every ``target_scope`` literal in the item-support emitter (including
    the ``_packet`` default) is a member of the extended vocabulary, and the
    damage-event disclosure scope is in the union."""
    import re

    source = inspect.getsource(
        __import__("src.calculator.item_support_effects", fromlist=["x"])
    )
    literals = set(re.findall(r'target_scope="([a-z_]+)"', source))
    literals.add("one_teammate")  # the _packet default
    for literal in literals:
        assert literal in SUPPORT_TARGET_SCOPES, literal
    assert "enemy_champions_within_range" in SUPPORT_TARGET_SCOPES


def test_contract_matches_the_resolution_vocabulary():
    policies = PARTICIPANT_LEDGER_CONTRACT["target_policy"]
    assert set(policies) == SUPPORT_TARGET_RESOLUTION_SCOPES | {"none_selected"}
    assert policies["none_selected"] == "no_selected_teammate"
    assert PARTICIPANT_LEDGER_CONTRACT["fail_closed"] is True
