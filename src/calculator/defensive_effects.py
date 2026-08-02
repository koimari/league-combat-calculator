"""Champion-owned starting defenses compiled from sourced mechanics."""

from dataclasses import dataclass

from .champions.skill_orders import get_ability_rank


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
) -> StartingDefenses:
    """Resolve the champion's default ready-at-start defensive state."""
    if champion_name == "Galio":
        return _galio_starting_defenses(level, stats["health"])
    return StartingDefenses()
