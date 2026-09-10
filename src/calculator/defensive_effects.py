"""The defensive resolver: sourced defences ready before the fight engine runs.

It resolves declarations.  Which defences a build has is answered by
:mod:`~.item_behavior_catalog` from the registry entries' own keys; how much
each is worth is answered by the family's interpreter; and the order they
apply in is the declaration order of
:class:`~.item_behavior.DefenseMechanic`, which is arithmetic rather than
presentation: Boundless Vitality multiplies shields three earlier mechanics
granted, so moving it is not a refactor.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .champion_opening_defenses import _apply_champion_revive, _apply_galio
from .interpreters import opening_defense, resolve_defense
from .interpreters.defense_state import declared_defenses
from .interpreters.sustain import received_healing_multiplier
from .item_behavior import (
    AllyProducer,
    BehaviorRule,
    DefenseField,
    DefenseMechanic,
    DefenseSubject,
    RuleFamily,
)
from .item_behavior_catalog import DEFENSE_RECEIPTS, behavior_rules
from .item_effects import ITEM_EFFECTS, input_option_float_value
from .starting_defenses import StartingDefenses, _DefenseLedger

# ── champion-owned defences ───────────────────────────────────────────────


# ── the one defence still resolved by name (3.7) ─────────────────────────
#
# One defence is a *fold over the ledger* rather than a set of granted
# fields: Boundless Vitality multiplies state three earlier mechanics wrote,
# so the arithmetic belongs where the state lives.  Its number, the field it
# lands in and its citation all come from its own declaration; what stays
# here is the fold and the three sentences that describe it.


_SHIELD_FIELDS = (
    DefenseField.MAGIC_SHIELD,
    DefenseField.PHYSICAL_SHIELD,
    DefenseField.GENERAL_SHIELD,
    DefenseField.REACTIVE_SHIELD_AMOUNT,
    DefenseField.THRESHOLD_SHIELD_AMOUNT,
)


# The three sentences the fold publishes.  The percentage is interpolated
# from the declared multiplier rather than typed: a registry that moved the
# number and a note that did not would be prose outrunning code, in the one
# place a reader looks to check it.
_BOUNDLESS_SHIELD_NOTE = (
    "Boundless Vitality increases every modeled shield by {share:.0%}."
)
_BOUNDLESS_THRESHOLD_NOTE = (
    "Boundless Vitality increases Protoplasm Harness's modeled healing by "
    "{share:.0%}."
)
_BOUNDLESS_ALL_HEALS_NOTE = (
    "Boundless Vitality increases all modeled healing received by {share:.0%}."
)


def _apply_boundless_vitality(
    ledger: _DefenseLedger,
    declared: Mapping[DefenseMechanic, BehaviorRule],
) -> None:
    """Spirit Visage's received-healing multiplier, folded over the ledger."""
    rule = declared.get(DefenseMechanic.BOUNDLESS_VITALITY)
    if rule is None:
        return
    owner = rule.owner
    multiplier = received_healing_multiplier(rule)
    share = multiplier - 1.0
    has_shield = any(ledger.read(field) > 0 for field in _SHIELD_FIELDS)
    if has_shield:
        ledger.write(DefenseField.HEALING_RECEIVED_MULTIPLIER, multiplier)
        for field in _SHIELD_FIELDS:
            ledger.fields[field] = ledger.read(field) * multiplier
        ledger.notes.append(_BOUNDLESS_SHIELD_NOTE.format(share=share))
        ledger.cite(DefenseMechanic.BOUNDLESS_VITALITY, owner, rule.receipt)

    if ledger.read(DefenseField.THRESHOLD_HEALTH_HEAL) > 0:
        ledger.write(DefenseField.HEALING_RECEIVED_MULTIPLIER, multiplier)
        ledger.fields[DefenseField.THRESHOLD_HEALTH_HEAL] = (
            ledger.read(DefenseField.THRESHOLD_HEALTH_HEAL) * multiplier
        )
        ledger.notes.append(_BOUNDLESS_THRESHOLD_NOTE.format(share=share))
        ledger.cite(DefenseMechanic.BOUNDLESS_VITALITY, owner, rule.receipt)

    # Boundless Vitality applies to every heal received, including
    # timestamped item/champion heals handled by the participant ledger.
    # Starting shields and Protoplasm's threshold heal above are already
    # pre-resolved with this same multiplier and are not multiplied again
    # by the survival walk.
    ledger.write(DefenseField.HEALING_RECEIVED_MULTIPLIER, multiplier)
    ledger.cite(DefenseMechanic.BOUNDLESS_VITALITY, owner, rule.receipt)
    if not any("all modeled heals" in note for note in ledger.notes):
        ledger.notes.append(_BOUNDLESS_ALL_HEALS_NOTE.format(share=share))


def _apply_everlasting(ledger: _DefenseLedger, names: frozenset[str]) -> None:
    """Fimbulwinter's Everlasting: cited here, declared as an ally packet.

    The one defence this resolver publishes without a defensive declaration
    of its own, because it already has one: the ally packet that grants the
    shield.  What the opening resolver has to say about it is a *refusal* —
    the trigger needs authored crowd-control metadata this model will not
    infer — and saying that twice, once as a second declaration, is the
    duplicated authority this campaign exists to remove.
    """
    for owner in ITEM_EFFECTS:
        if owner not in names:
            continue
        for rule in behavior_rules(owner):
            if rule.family is not RuleFamily.ALLY_PACKET:
                continue
            if rule.payload.producer is not AllyProducer.EVERLASTING:
                continue
            ledger.notes.append(opening_defense.EVERLASTING_NOTE.format(owner=owner))
            ledger.cite(
                DefenseMechanic.EVERLASTING,
                owner,
                DEFENSE_RECEIPTS[DefenseMechanic.EVERLASTING],
            )
            return


# The two defences this resolver applies itself rather than through
# ``resolve_defense``, and why each one is here.  **Neither is undeclared**:
# Everlasting is declared as the ally packet that grants the shield, and
# Boundless Vitality is declared as ``sustain`` — what they have in common is
# that what they publish is not a set of fields the ledger can simply apply.
# One is a refusal to model a trigger, the other a fold over state three
# earlier mechanics wrote, and both take the position the resolution order
# gives them.
_LEDGER_APPLIED_DEFENSES: Mapping[
    DefenseMechanic,
    Callable[
        [
            _DefenseLedger,
            frozenset[str],
            Mapping[DefenseMechanic, BehaviorRule],
            DefenseSubject,
        ],
        None,
    ],
] = {
    DefenseMechanic.EVERLASTING: lambda ledger, names, declared, subject: (
        _apply_everlasting(ledger, names)
    ),
    DefenseMechanic.BOUNDLESS_VITALITY: (
        lambda ledger, names, declared, subject: _apply_boundless_vitality(
            ledger, declared
        )
    ),
}


# ── the resolver ──────────────────────────────────────────────────────────


def option_reader(
    item_options: Mapping[str, Mapping[str, int | float]],
) -> Callable[[str, str], float]:
    """The typed option reader a :class:`DefenseSubject` is built with.

    One home for how a defence reads a scenario input: through the item's
    own schema (bounds, step, finiteness), never off the raw mapping.
    """

    def read(owner: str, key: str) -> float:
        return input_option_float_value(
            [{"name": owner}], {owner: item_options.get(owner) or {}}, owner, key
        )

    return read


def resolve_starting_defenses(
    champion_name: str,
    level: int,
    stats: dict[str, float],
    items: Sequence[Mapping[str, Any]] = (),
    *,
    item_options: Mapping[str, Mapping[str, int | float]] | None = None,
) -> StartingDefenses:
    """Resolve the sourced champion and item defences ready at fight start.

    The loop is over :class:`~.item_behavior.DefenseMechanic` rather than
    over the build, because the mechanic order *is* the resolution order: a
    defence that multiplies an earlier one has to run after it, and reading
    the enum in order is what makes that a declaration rather than an
    accident of how the branches were once typed.
    """
    ledger = _DefenseLedger()
    subject = DefenseSubject(
        level=level,
        stats=stats,
        options=item_options or {},
        option_value=option_reader(item_options or {}),
    )
    _apply_galio(ledger, champion_name, level, stats)
    _apply_champion_revive(ledger, champion_name, level, stats)

    names = frozenset(str(item.get("name", "")) for item in items)
    declared = declared_defenses(names)
    for mechanic in DefenseMechanic:
        applied = _LEDGER_APPLIED_DEFENSES.get(mechanic)
        if applied is not None:
            applied(ledger, names, declared, subject)
            continue
        rule = declared.get(mechanic)
        if rule is None:
            continue
        outcome = resolve_defense(rule, subject)
        ledger.apply(outcome.fields)
        ledger.notes.extend(outcome.notes)
        if outcome.fields or outcome.notes:
            ledger.cite(mechanic, rule.owner, rule.receipt)
    return ledger.frozen()


def armed_revive(defenses: StartingDefenses) -> tuple[float, float, str, str] | None:
    """``(amount, delay, source, source_key)`` of an armed revive, or ``None``.

    The source is the champion's own passive when the module declares one
    (Anivia Rebirth, Zac Cell Division, Zilean Chronoshift); Guardian Angel
    stays the item-source label.
    """
    revive_amount = max(0.0, float(defenses.revive_health_amount))
    revive_delay = max(0.0, float(defenses.revive_delay))
    if revive_amount <= 0.0 or revive_delay <= 0.0:
        return None
    revive_source = str(defenses.revive_source) or "Guardian Angel (Rebirth)"
    revive_key = (
        f"revive_{revive_source.replace(' ', '_')}"
        if revive_source != "Guardian Angel (Rebirth)"
        else "revive_Guardian Angel"
    )
    return revive_amount, revive_delay, revive_source, revive_key


__all__ = ["armed_revive", "resolve_starting_defenses"]
