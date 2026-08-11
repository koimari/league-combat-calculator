"""The defensive resolver: sourced defences ready before the fight engine runs.

This module used to *be* the defences.  Twenty-three mechanics lived here as
a ladder of ``if "<item name>" in names`` branches, each reading the number
registry directly, each carrying its own hand-written provenance record, and
the order they appeared in the function was the only statement anywhere of
the order they apply in.

Now it resolves declarations.  Which defences a build has is answered by
:mod:`~.item_behavior_catalog` from the registry entries' own keys; how much
each is worth is answered by the family's interpreter; and the order they
apply in is the declaration order of
:class:`~.item_behavior.DefenseMechanic`, which is arithmetic rather than
presentation — Boundless Vitality multiplies shields three earlier mechanics
granted, so moving it is not a refactor.

Two mechanics are still resolved by name, and both are named out loud in
``item_behavior_catalog.DEFENSE_UNMIGRATED_MECHANICS`` with the slice that
retires them: Death's Dance defers damage (``damage_routing``) and Spirit
Visage multiplies healing received (``sustain``).  Both families are 3.7's,
and declaring them here would be another slice's work smuggled in under this
one's zero-diff claim.
"""

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .champions.skill_orders import get_ability_rank
from .interpreters import opening_defense, resolve_defense
from .interpreters.defense_state import declared_defenses
from .item_behavior import (
    AllyProducer,
    DEFENSE_FIELD_COMBINE,
    DefenseCombine,
    DefenseField,
    DefenseMechanic,
    DefenseSubject,
    KernelField,
    RuleFamily,
)
from .item_behavior_catalog import DEFENSE_RECEIPTS, behavior_rules
from .item_effects import ITEM_EFFECTS, required_effect_value
from .value_ref import SourceReceipt

# How each defensive source is published.  A template per mechanic, because
# the label is presentation of a citation rather than policy of a rule: most
# name the item the declaration carries, and Time Stop names both items it
# can be read from because one wiki page is the source for both.
DEFENSE_SOURCE_LABEL: Mapping[DefenseMechanic, str] = {
    DefenseMechanic.SHIELD_OF_DURAND: "{owner} — Shield of Durand",
    DefenseMechanic.NOXIAN_ENDURANCE: "{owner} — Noxian Endurance / Plating",
    DefenseMechanic.NOXIAN_PERSISTENCE: "{owner} — Noxian Persistence",
    DefenseMechanic.BLESSING_OF_THE_MOUNTAIN: "{owner} — Blessing of the Mountain",
    DefenseMechanic.ICHORSHIELD: "{owner} — Ichorshield",
    DefenseMechanic.EVERLASTING: "{owner} — Everlasting",
    DefenseMechanic.ANNUL: "{owner} — Annul",
    DefenseMechanic.MAGEBANE: "{owner} — Magebane",
    DefenseMechanic.LIFELINE_SHIELDBOW: "{owner} — Lifeline",
    DefenseMechanic.LIFELINE_HEXDRINKER: "{owner} — Lifeline",
    DefenseMechanic.LIFELINE_MAW: "{owner} — Lifeline",
    DefenseMechanic.LIFELINE_SERAPH: "{owner} — Lifeline",
    DefenseMechanic.LIFELINE_STERAK: "{owner} — Lifeline",
    DefenseMechanic.LIFELINE_PROTOPLASM: "{owner} — Lifeline",
    DefenseMechanic.REBIRTH: "{owner} — Rebirth",
    DefenseMechanic.IGNORE_PAIN: "{owner} — Ignore Pain / Defy",
    DefenseMechanic.STEADFAST: "{owner} — Steadfast",
    DefenseMechanic.VOIDBORN_RESILIENCE: "{owner} — Voidborn Resilience",
    # One page is the source for both stasis items and the published label
    # says so, which is why this template carries no owner placeholder.
    DefenseMechanic.TIME_STOP: ("Zhonya's Hourglass / Seeker's Armguard — Time Stop"),
    DefenseMechanic.BOUNDLESS_VITALITY: "{owner} — Boundless Vitality",
    DefenseMechanic.PLATING: "{owner} — Plating",
    DefenseMechanic.ROCK_SOLID: "{owner} — Rock Solid",
    DefenseMechanic.RESILIENCE: "{owner} — Resilience",
    DefenseMechanic.THORNS: "{owner} — Thorns",
}


@dataclass(frozen=True, slots=True)
class DefenseCitation:
    """One published defensive source: which mechanic, whose, and from where.

    The successor to the hand-written provenance records this module used to
    carry.  Nothing here is authored beside the behaviour any more:
    the receipt comes from the rule that granted the defence — resolved from
    the registry entry's own citation or from the family constant, in
    ``receipt_for``'s ruled order — and the label is derived from the
    mechanic and its owner rather than typed a second time.
    """

    mechanic: DefenseMechanic
    owner: str
    receipt: SourceReceipt

    @property
    def label(self) -> str:
        """The published name of this source."""
        return DEFENSE_SOURCE_LABEL[self.mechanic].format(owner=self.owner)


@dataclass(frozen=True, slots=True)
class StartingDefenses:
    """Defenses assumed ready when the modeled exchange begins."""

    magic_shield: float = 0.0
    physical_shield: float = 0.0
    general_shield: float = 0.0
    # A reactive shield is granted after an explicitly typed incoming
    # champion-damage event (for example Noxian Endurance/Persistence).  It
    # is kept separate from opening shields so the trigger packet cannot
    # accidentally absorb the hit that armed it.
    reactive_shield_amount: float = 0.0
    reactive_shield_damage_type: str = ""
    reactive_shield_duration: float = 0.0
    reactive_shield_cooldown: float = 0.0
    reactive_shield_source: str = ""
    bloodthirster_shield_cap: float = 0.0
    bloodthirster_starting_shield: float = 0.0
    spell_shield_ready: bool = False
    spell_shield_source: str = ""
    basic_damage_multiplier: float = 1.0
    incoming_damage_multiplier: float = 1.0
    incoming_damage_linger: float = 0.0
    incoming_damage_cooldown: float = 0.0
    incoming_damage_source: str = ""
    basic_damage_flat_reduction: float = 0.0
    basic_damage_flat_reduction_cap: float = 0.0
    critical_strike_damage_multiplier: float = 1.0
    healing_received_multiplier: float = 1.0
    # Maw's Lifeline grants a temporary omnivamp stat after its shield fires;
    # the ordered timeline toggles this only on the authored threshold event.
    maw_lifeline_omnivamp_percent: float = 0.0
    threshold_shield_amount: float = 0.0
    threshold_shield_health_ratio: float = 0.0
    threshold_shield_duration: float = 0.0
    threshold_shield_damage_type: str = "all"
    threshold_health_bonus: float = 0.0
    threshold_health_heal: float = 0.0
    threshold_health_ratio: float = 0.0
    threshold_health_duration: float = 0.0
    revive_health_amount: float = 0.0
    revive_delay: float = 0.0
    revive_cooldown: float = 0.0
    revive_source: str = ""
    # Death's Dance ordered defenses.  The participant timeline consumes
    # these fields only when the item is present; zero is the fail-closed
    # absence state for every other loadout.
    damage_deferral_fraction: float = 0.0
    damage_deferral_duration: float = 0.0
    damage_deferral_ticks: int = 0
    defy_window: float = 0.0
    defy_heal_bonus_ad_ratio: float = 0.0
    defy_heal_duration: float = 0.0
    defy_heal_ticks: int = 0
    # Combat-state item defenses.  These are metadata for the ordered ledger;
    # no stack is assumed active at t=0.
    force_stack_duration: float = 0.0
    force_max_stacks: int = 0
    force_stack_interval: float = 0.0
    force_immobilize_stacks: int = 0
    force_bonus_magic_resistance: float = 0.0
    force_bonus_move_speed_percent: float = 0.0
    jaksho_stack_interval: float = 0.0
    jaksho_max_stacks: int = 0
    jaksho_bonus_resistance_multiplier: float = 0.0
    starting_stasis_duration: float = 0.0
    starting_stasis_source: str = ""
    assumptions: tuple[str, ...] = ()
    sources: tuple[DefenseCitation, ...] = ()
    coverage: str = "base_and_items_only"

    def public_summary(self) -> dict[str, object]:
        """Return a JSON-safe explanation of the resolved state."""
        incoming_damage = {
            "basic_damage_multiplier": round(self.basic_damage_multiplier, 3),
            "basic_damage_flat_reduction": round(self.basic_damage_flat_reduction, 1),
            "basic_damage_flat_reduction_cap": round(
                self.basic_damage_flat_reduction_cap, 3
            ),
            "critical_strike_damage_multiplier": round(
                self.critical_strike_damage_multiplier, 3
            ),
        }
        if (
            self.incoming_damage_multiplier != 1.0
            or self.incoming_damage_linger > 0.0
            or self.incoming_damage_cooldown > 0.0
            or self.incoming_damage_source
        ):
            incoming_damage.update(
                {
                    "incoming_damage_multiplier": round(
                        self.incoming_damage_multiplier, 3
                    ),
                    "incoming_damage_linger": round(self.incoming_damage_linger, 1),
                    "incoming_damage_cooldown": round(self.incoming_damage_cooldown, 1),
                    "source": self.incoming_damage_source,
                }
            )
        return {
            "magic_shield": round(self.magic_shield, 1),
            "physical_shield": round(self.physical_shield, 1),
            "general_shield": round(self.general_shield, 1),
            "reactive_shield": {
                "amount": round(self.reactive_shield_amount, 1),
                "damage_type": self.reactive_shield_damage_type,
                "duration": round(self.reactive_shield_duration, 1),
                "cooldown": round(self.reactive_shield_cooldown, 1),
                "source": self.reactive_shield_source,
            },
            "ichorshield": {
                "cap": round(self.bloodthirster_shield_cap, 1),
                "starting": round(self.bloodthirster_starting_shield, 1),
            },
            "spell_shield": {
                "ready": bool(self.spell_shield_ready),
                "source": self.spell_shield_source,
            },
            "incoming_damage": incoming_damage,
            "healing_received_multiplier": round(self.healing_received_multiplier, 3),
            "maw_lifeline_omnivamp_percent": round(
                self.maw_lifeline_omnivamp_percent, 3
            ),
            "threshold_shield": {
                "amount": round(self.threshold_shield_amount, 1),
                "health_ratio": round(self.threshold_shield_health_ratio, 3),
                "duration": round(self.threshold_shield_duration, 1),
                "damage_type": self.threshold_shield_damage_type,
            },
            "threshold_health": {
                "bonus_health": round(self.threshold_health_bonus, 1),
                "healing": round(self.threshold_health_heal, 1),
                "health_ratio": round(self.threshold_health_ratio, 3),
                "duration": round(self.threshold_health_duration, 1),
            },
            "revive": {
                "health_amount": round(self.revive_health_amount, 1),
                "delay": round(self.revive_delay, 1),
                "cooldown": round(self.revive_cooldown, 1),
            },
            "death_dance": {
                "damage_deferral_fraction": round(self.damage_deferral_fraction, 3),
                "damage_deferral_duration": round(self.damage_deferral_duration, 1),
                "damage_deferral_ticks": int(self.damage_deferral_ticks),
                "defy_window": round(self.defy_window, 1),
                "defy_heal_bonus_ad_ratio": round(self.defy_heal_bonus_ad_ratio, 3),
                "defy_heal_duration": round(self.defy_heal_duration, 1),
                "defy_heal_ticks": int(self.defy_heal_ticks),
            },
            "combat_state": {
                "force_of_nature": {
                    "stack_duration": round(self.force_stack_duration, 1),
                    "max_stacks": int(self.force_max_stacks),
                    "stack_interval": round(self.force_stack_interval, 1),
                    "immobilize_stacks": int(self.force_immobilize_stacks),
                    "bonus_magic_resistance": round(
                        self.force_bonus_magic_resistance, 1
                    ),
                    "bonus_move_speed_percent": round(
                        self.force_bonus_move_speed_percent, 1
                    ),
                },
                "jaksho": {
                    "stack_interval": round(self.jaksho_stack_interval, 1),
                    "max_stacks": int(self.jaksho_max_stacks),
                    "bonus_resistance_multiplier": round(
                        self.jaksho_bonus_resistance_multiplier, 3
                    ),
                },
                "starting_stasis": {
                    "duration": round(self.starting_stasis_duration, 3),
                    "source": self.starting_stasis_source,
                },
            },
            "assumptions": list(self.assumptions),
            "sources": [
                {
                    "label": source.label,
                    "url": source.receipt.url,
                    "revision_id": source.receipt.revision_id,
                    "revision_timestamp": source.receipt.revision_timestamp,
                }
                for source in self.sources
            ],
            "coverage": self.coverage,
        }


# The resolved state as a mutable ledger, keyed by the declared field.  It
# exists because a defence is a *fold*: two boots both plate and their
# multipliers compose, Boundless Vitality multiplies shields three other
# mechanics granted, and a champion passive that already claimed the revive
# keeps its label when Guardian Angel is also held.  How each of those
# composes is :data:`DEFENSE_FIELD_COMBINE`, stated once per field.
_DEFAULTS = StartingDefenses()

_COVERAGE_ITEM_DEFENSES = "modeled_starting_defenses"
_COVERAGE_CHAMPION_PASSIVE = "modeled_starting_passive"


class _DefenseLedger:
    """Every defensive field, its notes and its citations, mid-resolution."""

    __slots__ = ("fields", "notes", "citations")

    def __init__(self) -> None:
        """Seed every field with the state of a build holding nothing."""
        self.fields: dict[DefenseField, Any] = {
            field: getattr(_DEFAULTS, field.value) for field in DefenseField
        }
        self.notes: list[str] = []
        self.citations: list[DefenseCitation] = []

    def read(self, field: DefenseField) -> Any:
        """One resolved field as it stands now."""
        return self.fields[field]

    def write(self, field: DefenseField, value: Any) -> None:
        """Fold one value into a field, by the field's own combine rule."""
        combine = DEFENSE_FIELD_COMBINE[field]
        current = self.fields[field]
        if combine is DefenseCombine.ADD:
            self.fields[field] = current + value
        elif combine is DefenseCombine.MULTIPLY:
            self.fields[field] = current * value
        elif combine is DefenseCombine.FILL_IF_EMPTY:
            self.fields[field] = current or value
        else:
            self.fields[field] = value

    def apply(self, granted: Sequence[KernelField]) -> None:
        """Fold every field one resolved defence granted."""
        for field in granted:
            self.write(DefenseField(field.name), field.value)

    def cite(
        self, mechanic: DefenseMechanic, owner: str, receipt: SourceReceipt
    ) -> None:
        """Publish one defensive source, once per mechanic."""
        if any(citation.mechanic is mechanic for citation in self.citations):
            return
        self.citations.append(DefenseCitation(mechanic, owner, receipt))

    def frozen(self) -> StartingDefenses:
        """The resolved state, with the coverage its citations earned."""
        if not self.citations:
            if self.read(DefenseField.REVIVE_HEALTH_AMOUNT) > 0.0:
                return StartingDefenses(
                    revive_health_amount=self.read(DefenseField.REVIVE_HEALTH_AMOUNT),
                    revive_delay=self.read(DefenseField.REVIVE_DELAY),
                    revive_cooldown=self.read(DefenseField.REVIVE_COOLDOWN),
                    revive_source=self.read(DefenseField.REVIVE_SOURCE),
                    coverage=_COVERAGE_CHAMPION_PASSIVE,
                )
            return StartingDefenses()
        return StartingDefenses(
            **{field.value: value for field, value in self.fields.items()},
            assumptions=tuple(self.notes),
            sources=tuple(self.citations),
            coverage=_COVERAGE_ITEM_DEFENSES,
        )


# ── champion-owned defences ───────────────────────────────────────────────

_GALIO_SHIELD_MIN_PERCENT = 7.5
_GALIO_SHIELD_MAX_PERCENT = 13.5

_GALIO_NOTE = "Anti-Magic Bulwark is ready because Galio has not recently taken damage."

# E8d follow-up: sourced revive-source labels for champions whose modules
# declare ``starting_revive_defense``; used by the ledger's revive receipts.
_CHAMPION_REVIVE_SOURCES = {
    "Anivia": "Rebirth",
    "Zac": "Cell Division",
    "Zilean": "Chronoshift",
}


_GALIO = "Galio"


def _apply_galio(
    ledger: _DefenseLedger, champion_name: str, level: int, stats: Mapping[str, float]
) -> None:
    """Galio's Shield of Durand, one of two defences no item carries."""
    if champion_name != _GALIO or get_ability_rank("W", level, _GALIO) < 1:
        return
    maximum_health = float(stats["health"])
    percent = (
        _GALIO_SHIELD_MIN_PERCENT
        + (_GALIO_SHIELD_MAX_PERCENT - _GALIO_SHIELD_MIN_PERCENT) * (level - 1) / 17.0
    )
    ledger.write(DefenseField.MAGIC_SHIELD, maximum_health * percent / 100.0)
    ledger.notes.append(_GALIO_NOTE)
    ledger.cite(
        DefenseMechanic.SHIELD_OF_DURAND,
        _GALIO,
        DEFENSE_RECEIPTS[DefenseMechanic.SHIELD_OF_DURAND],
    )


def _champion_starting_revive(
    champion_name: str, level: int, stats: dict[str, float]
) -> dict[str, float]:
    """Resolve a champion module's sourced revive fields, if it declares any.

    Mirrors the healing_reduction champion-source lookup: modules that
    implement ``starting_revive_defense`` (Anivia Rebirth, Zac Cell
    Division, Zilean Chronoshift) return the revive payload; every other
    champion fails closed with zero revive fields.
    """
    # pylint: disable=import-outside-toplevel
    from .champions import _CHAMPION_MODULES
    from importlib import import_module

    module_name = _CHAMPION_MODULES.get(champion_name)
    if module_name is None:
        return {}
    package = f"{__name__.rsplit('.', 1)[0]}.champions"
    module = import_module(f".{module_name}", package=package)
    resolver = getattr(module, "starting_revive_defense", None)
    if resolver is None:
        return {}
    return resolver(level, stats)


def _apply_champion_revive(
    ledger: _DefenseLedger, champion_name: str, level: int, stats: dict[str, float]
) -> None:
    """A champion passive's own resurrection, which no item declares."""
    fields = _champion_starting_revive(champion_name, level, stats)
    if not fields:
        return
    ledger.write(
        DefenseField.REVIVE_HEALTH_AMOUNT,
        float(fields.get("revive_health_amount", 0.0)),
    )
    ledger.write(DefenseField.REVIVE_DELAY, float(fields.get("revive_delay", 0.0)))
    ledger.write(
        DefenseField.REVIVE_COOLDOWN, float(fields.get("revive_cooldown", 0.0))
    )
    ledger.write(
        DefenseField.REVIVE_SOURCE, _CHAMPION_REVIVE_SOURCES.get(champion_name, "")
    )


# ── defences still resolved by name (3.7) ────────────────────────────────
#
# Two mechanics whose family sits outside this slice.  Each keeps the branch
# it always had, in the position the resolution order gives it, and is named
# in ``item_behavior_catalog.DEFENSE_UNMIGRATED_MECHANICS`` with the slice
# that retires it — a refusal with a date rather than an omission.


def _apply_ignore_pain(ledger: _DefenseLedger, names: frozenset[str], subject) -> None:
    """Death's Dance's deferral schedule — ``damage_routing``, retired at 3.7."""
    owner = "Death's Dance"
    if owner not in names:
        return
    melee = subject.is_melee
    ledger.write(
        DefenseField.DAMAGE_DEFERRAL_FRACTION,
        float(
            required_effect_value(
                owner, "damage_deferral_melee" if melee else "damage_deferral_ranged"
            )
        ),
    )
    ledger.write(
        DefenseField.DAMAGE_DEFERRAL_DURATION,
        float(required_effect_value(owner, "damage_deferral_duration")),
    )
    ledger.write(
        DefenseField.DAMAGE_DEFERRAL_TICKS,
        int(required_effect_value(owner, "damage_deferral_ticks")),
    )
    ledger.write(
        DefenseField.DEFY_WINDOW, float(required_effect_value(owner, "defy_window"))
    )
    ledger.write(
        DefenseField.DEFY_HEAL_BONUS_AD_RATIO,
        float(required_effect_value(owner, "defy_heal_bonus_ad_ratio")),
    )
    ledger.write(
        DefenseField.DEFY_HEAL_DURATION,
        float(required_effect_value(owner, "defy_heal_duration")),
    )
    ledger.write(
        DefenseField.DEFY_HEAL_TICKS,
        int(required_effect_value(owner, "defy_heal_ticks")),
    )
    ledger.notes.append(
        "Death's Dance Ignore Pain defers the sourced fraction of each "
        "post-mitigation physical or magic packet; Defy clears the "
        "remaining store and heals after a qualifying champion takedown."
    )
    ledger.cite(
        DefenseMechanic.IGNORE_PAIN,
        owner,
        DEFENSE_RECEIPTS[DefenseMechanic.IGNORE_PAIN],
    )


_SHIELD_FIELDS = (
    DefenseField.MAGIC_SHIELD,
    DefenseField.PHYSICAL_SHIELD,
    DefenseField.GENERAL_SHIELD,
    DefenseField.REACTIVE_SHIELD_AMOUNT,
    DefenseField.THRESHOLD_SHIELD_AMOUNT,
)


def _apply_boundless_vitality(
    ledger: _DefenseLedger, names: frozenset[str], subject
) -> None:
    """Spirit Visage's received-healing multiplier — ``sustain``, retired at 3.7."""
    del subject
    owner = "Spirit Visage"
    if owner not in names:
        return
    multiplier = float(ITEM_EFFECTS[owner]["shield_received_multiplier"])
    has_shield = any(ledger.read(field) > 0 for field in _SHIELD_FIELDS)
    if has_shield:
        ledger.write(DefenseField.HEALING_RECEIVED_MULTIPLIER, multiplier)
        for field in _SHIELD_FIELDS:
            ledger.fields[field] = ledger.read(field) * multiplier
        ledger.notes.append("Boundless Vitality increases every modeled shield by 25%.")
        ledger.cite(
            DefenseMechanic.BOUNDLESS_VITALITY,
            owner,
            DEFENSE_RECEIPTS[DefenseMechanic.BOUNDLESS_VITALITY],
        )

    if ledger.read(DefenseField.THRESHOLD_HEALTH_HEAL) > 0:
        ledger.write(DefenseField.HEALING_RECEIVED_MULTIPLIER, multiplier)
        ledger.fields[DefenseField.THRESHOLD_HEALTH_HEAL] = (
            ledger.read(DefenseField.THRESHOLD_HEALTH_HEAL) * multiplier
        )
        ledger.notes.append(
            "Boundless Vitality increases Protoplasm Harness's modeled healing by 25%."
        )
        ledger.cite(
            DefenseMechanic.BOUNDLESS_VITALITY,
            owner,
            DEFENSE_RECEIPTS[DefenseMechanic.BOUNDLESS_VITALITY],
        )

    # Boundless Vitality applies to every heal received, including
    # timestamped item/champion heals handled by the participant ledger.
    # Starting shields and Protoplasm's threshold heal above are already
    # pre-resolved with this same multiplier and are not multiplied again
    # by the survival walk.
    ledger.write(DefenseField.HEALING_RECEIVED_MULTIPLIER, multiplier)
    ledger.cite(
        DefenseMechanic.BOUNDLESS_VITALITY,
        owner,
        DEFENSE_RECEIPTS[DefenseMechanic.BOUNDLESS_VITALITY],
    )
    if not any("all modeled heals" in note for note in ledger.notes):
        ledger.notes.append(
            "Boundless Vitality increases all modeled healing received by 25%."
        )


def _apply_everlasting(
    ledger: _DefenseLedger, names: frozenset[str], subject: DefenseSubject
) -> None:
    """Fimbulwinter's Everlasting: cited here, declared as an ally packet.

    The one defence this resolver publishes without a defensive declaration
    of its own, because it already has one: the ally packet that grants the
    shield.  What the opening resolver has to say about it is a *refusal* —
    the trigger needs authored crowd-control metadata this model will not
    infer — and saying that twice, once as a second declaration, is the
    duplicated authority this campaign exists to remove.
    """
    del subject
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


# Defences resolved outside the four defence families: one declared by
# another family (Everlasting) and two whose own family lands in 3.7.
_UNMIGRATED_DEFENSES: Mapping[
    DefenseMechanic, Callable[[_DefenseLedger, frozenset[str], DefenseSubject], None]
] = {
    DefenseMechanic.EVERLASTING: _apply_everlasting,
    DefenseMechanic.IGNORE_PAIN: _apply_ignore_pain,
    DefenseMechanic.BOUNDLESS_VITALITY: _apply_boundless_vitality,
}


# ── the resolver ──────────────────────────────────────────────────────────


def resolve_starting_defenses(
    champion_name: str,
    level: int,
    stats: dict[str, float],
    items: Sequence[Mapping[str, Any]] = (),
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
    subject = DefenseSubject(level=level, stats=stats, options=item_options or {})
    _apply_galio(ledger, champion_name, level, stats)
    _apply_champion_revive(ledger, champion_name, level, stats)

    names = frozenset(str(item.get("name", "")) for item in items)
    declared = declared_defenses(names)
    for mechanic in DefenseMechanic:
        legacy = _UNMIGRATED_DEFENSES.get(mechanic)
        if legacy is not None:
            legacy(ledger, names, subject)
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


__all__ = [
    "DEFENSE_SOURCE_LABEL",
    "DefenseCitation",
    "StartingDefenses",
    "resolve_starting_defenses",
]
