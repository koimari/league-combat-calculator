"""The defensive state a fight starts with, the citation each source publishes, and their ledger."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .item_behavior import (
    DEFENSE_FIELD_COMBINE,
    DefenseCombine,
    DefenseField,
    DefenseMechanic,
    KernelField,
)
from .item_behavior_catalog import DEFENSE_RECEIPTS
from .value_ref import receipt_for
from .value_source_receipt import SourceReceipt

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
    DefenseMechanic.UNDAUNTED: "{owner} — Undaunted",
    DefenseMechanic.RESILIENCE: "{owner} — Resilience",
    DefenseMechanic.THORNS: "{owner} — Thorns",
}


@dataclass(frozen=True, slots=True)
class DefenseCitation:
    """One published defensive source: which mechanic, whose, and from where.

    Nothing here is authored beside the behaviour: the receipt comes from the
    rule that granted the defence, resolved from the registry entry's own
    citation or from the family constant in ``receipt_for``'s ruled order, and
    the label is derived from the mechanic and its owner rather than typed a
    second time.
    """

    mechanic: DefenseMechanic
    owner: str
    receipt: SourceReceipt

    @property
    def label(self) -> str:
        """The published name of this source."""
        return DEFENSE_SOURCE_LABEL[self.mechanic].format(owner=self.owner)

    @property
    def source_url(self) -> str:
        """The page the receipt was read from."""
        return self.receipt.url

    @property
    def revision_id(self) -> int:
        """The revision the receipt names, or ``0`` for a cache-backed one."""
        return self.receipt.revision_id

    @property
    def revision_timestamp(self) -> str:
        """The human-checkable stamp for that revision."""
        return self.receipt.revision_timestamp


def defense_source(owner: str, mechanic: DefenseMechanic) -> DefenseCitation:
    """The citation one owner's declaration of *mechanic* resolves to.

    The receipt comes from the owner's own registry entry or from the family's
    declared constant, in ``receipt_for``'s ruled order, so there is no second
    place a revision can be typed and go stale.
    """
    return DefenseCitation(
        mechanic=mechanic,
        owner=owner,
        receipt=receipt_for(
            "ITEM_EFFECTS", owner, declared=DEFENSE_RECEIPTS.get(mechanic)
        ),
    )


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
    champion_damage_flat_reduction: float = 0.0
    champion_dot_damage_flat_reduction: float = 0.0
    champion_damage_flat_source: str = ""
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
        if (
            self.champion_damage_flat_reduction > 0.0
            or self.champion_dot_damage_flat_reduction > 0.0
            or self.champion_damage_flat_source
        ):
            incoming_damage.update(
                {
                    "champion_damage_flat_reduction": round(
                        self.champion_damage_flat_reduction, 2
                    ),
                    "champion_dot_damage_flat_reduction": round(
                        self.champion_dot_damage_flat_reduction, 2
                    ),
                    "champion_damage_flat_source": self.champion_damage_flat_source,
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

    __slots__ = ("citations", "fields", "notes")

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
