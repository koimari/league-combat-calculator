"""Champion-owned starting defenses compiled from sourced mechanics."""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .champions.skill_orders import get_ability_rank
from .item_effects import ITEM_EFFECTS


@dataclass(frozen=True, slots=True)
class DefenseSource:
    """Revision-backed provenance for one defensive mechanic."""

    label: str
    source_url: str
    revision_id: int
    revision_timestamp: str


@dataclass(frozen=True, slots=True)
class StartingDefenses:
    """Defenses assumed ready when the modeled exchange begins."""

    magic_shield: float = 0.0
    physical_shield: float = 0.0
    general_shield: float = 0.0
    assumptions: tuple[str, ...] = ()
    sources: tuple[DefenseSource, ...] = ()
    coverage: str = "base_and_items_only"

    def public_summary(self) -> dict[str, object]:
        """Return a JSON-safe explanation of the resolved state."""
        return {
            "magic_shield": round(self.magic_shield, 1),
            "physical_shield": round(self.physical_shield, 1),
            "general_shield": round(self.general_shield, 1),
            "assumptions": list(self.assumptions),
            "sources": [
                {
                    "label": source.label,
                    "url": source.source_url,
                    "revision_id": source.revision_id,
                    "revision_timestamp": source.revision_timestamp,
                }
                for source in self.sources
            ],
            "coverage": self.coverage,
        }


_GALIO_W_SOURCE = DefenseSource(
    label="Galio — Shield of Durand",
    source_url=(
        "https://wiki.leagueoflegends.com/en-us/" "Template:Data_Galio/Shield_of_Durand"
    ),
    revision_id=3990299,
    revision_timestamp="2026-02-07T07:08:21Z",
)

_KAENIC_SOURCE = DefenseSource(
    label="Kaenic Rookern — Magebane",
    source_url="https://wiki.leagueoflegends.com/en-us/Kaenic_Rookern",
    revision_id=3984971,
    revision_timestamp="2026-01-17T16:04:29Z",
)

_SPIRIT_VISAGE_SOURCE = DefenseSource(
    label="Spirit Visage — Boundless Vitality",
    source_url="https://wiki.leagueoflegends.com/en-us/Spirit_Visage",
    revision_id=4016166,
    revision_timestamp="2026-05-09T17:09:08Z",
)


def _galio_starting_defenses(level: int, maximum_health: float) -> StartingDefenses:
    if get_ability_rank("W", level, "Galio") < 1:
        return StartingDefenses()
    shield_percent = 7.5 + (13.5 - 7.5) * (level - 1) / 17.0
    return StartingDefenses(
        magic_shield=maximum_health * shield_percent / 100.0,
        assumptions=(
            "Anti-Magic Bulwark is ready because Galio has not recently taken damage.",
        ),
        sources=(_GALIO_W_SOURCE,),
        coverage="modeled_starting_passive",
    )


def resolve_starting_defenses(
    champion_name: str,
    level: int,
    stats: dict[str, float],
    items: Sequence[Mapping[str, Any]] = (),
) -> StartingDefenses:
    """Resolve sourced champion and item defenses ready at fight start."""
    champion_defenses = StartingDefenses()
    if champion_name == "Galio":
        champion_defenses = _galio_starting_defenses(level, stats["health"])

    names = {str(item.get("name", "")) for item in items}
    magic_shield = champion_defenses.magic_shield
    physical_shield = champion_defenses.physical_shield
    general_shield = champion_defenses.general_shield
    assumptions = list(champion_defenses.assumptions)
    sources = list(champion_defenses.sources)

    if "Kaenic Rookern" in names:
        ratio = float(
            ITEM_EFFECTS["Kaenic Rookern"]["magic_shield_max_health_ratio"]
        )
        magic_shield += stats["health"] * ratio
        assumptions.append(
            "Magebane is ready because the target has not taken magic damage "
            "during the previous 15 seconds."
        )
        sources.append(_KAENIC_SOURCE)

    has_shield = magic_shield > 0 or physical_shield > 0 or general_shield > 0
    if "Spirit Visage" in names and has_shield:
        multiplier = float(
            ITEM_EFFECTS["Spirit Visage"]["shield_received_multiplier"]
        )
        magic_shield *= multiplier
        physical_shield *= multiplier
        general_shield *= multiplier
        assumptions.append(
            "Boundless Vitality increases every modeled starting shield by 25%."
        )
        sources.append(_SPIRIT_VISAGE_SOURCE)

    if not sources:
        return StartingDefenses()
    return StartingDefenses(
        magic_shield=magic_shield,
        physical_shield=physical_shield,
        general_shield=general_shield,
        assumptions=tuple(assumptions),
        sources=tuple(sources),
        coverage="modeled_starting_defenses",
    )
