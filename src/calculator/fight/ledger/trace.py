"""One line per priced packet: what it met, what it cost, and which step wrote it."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from ...ability_spec import DamageClass
from ...survival.pricing import NO_RESISTANCE_PUBLISHED, AuthoredDeclaration
from .. import authorship

#: The packet stated no pre-mitigation magnitude, on its event or on a
#: declaration riding it.  Refused rather than divided back out of the
#: mitigated amount: a packet re-priced inside a shred or penetration window
#: met a resistance the fight never published, so the division prints a
#: number that is wrong exactly where it matters.
NO_RAW_PUBLISHED = "no_raw_damage_published"

#: No step claimed the row, which is what a fight run outside
#: :func:`authorship.recording` looks like.
NO_STEP_MEASURED = "no_measured_step"

#: A row prices more than the packets the ledger reconstructed for it, so the
#: difference belongs to no packet.  It rides its own line carrying the
#: residue, because a trace whose lines do not sum to the fight answers a
#: different question from the one it is read for.
UNACCOUNTED_ROW_TOTAL = "unaccounted_row_total"

#: A ledger row whose breakdown row is gone.
_NO_ROW: Mapping[str, Any] = {}


@dataclass(frozen=True)
class TraceLine:
    """One priced packet, or one amplifier, as a reader reads it."""

    time: float
    source: str
    mechanic: str
    raw: float | None
    damage_class: str
    resistance_met: float | None
    amp: str
    mitigated: float
    step: str
    refusals: tuple[str, ...]

    def published(self) -> dict[str, Any]:
        """This line as JSON-safe leaves."""
        return asdict(self) | {"refusals": list(self.refusals)}


@dataclass(frozen=True)
class FightTrace:
    """One fight's lines, beside the resistance baseline it published."""

    lines: tuple[TraceLine, ...]
    effective_armor: float
    effective_mr: float

    def published(self) -> dict[str, Any]:
        """This trace as JSON-safe leaves."""
        return {
            "effective_armor": self.effective_armor,
            "effective_mr": self.effective_mr,
            "lines": [line.published() for line in self.lines],
        }

    def refusals_by_source(self) -> dict[str, tuple[str, ...]]:
        """Which facts each source key left unstated, over the whole trace."""
        refused: dict[str, set[str]] = {}
        for line in self.lines:
            if line.refusals:
                refused.setdefault(line.source, set()).update(line.refusals)
        return {source: tuple(sorted(names)) for source, names in refused.items()}


def _declaration(event: Mapping[str, Any]) -> AuthoredDeclaration | None:
    """The declaration riding one ledger event, in its named shape."""
    declared = event.get("declared")
    return None if declared is None else AuthoredDeclaration(*declared)


def _mechanic(row: Mapping[str, Any], declaration: AuthoredDeclaration | None) -> str:
    """What this packet prices: an item's previewed rule, else the slot a
    champion rider names behind ``results.CHAMPION_PRODUCER_PREFIX``, which
    its own row carries because no declaration can hold it."""
    for stated in (row.get("pair_preview_of"), row.get("mechanic")):
        if stated is not None:
            return str(stated)
    return "" if declaration is None else str(declaration.rule_id)


def _amplifier_factor(row: Mapping[str, Any]) -> float | None:
    """The factor an amplifier row states; ``None`` for a row that prices packets."""
    for stated in (row.get("multiplier"), row.get("amplifier")):
        if stated is not None:
            return float(stated)
    return None


def _refusals(*facts: tuple[str, object]) -> tuple[str, ...]:
    """The names of the facts this line was handed no value for."""
    return tuple(name for name, stated in facts if stated is None)


def _packet_line(
    source: str,
    event: Mapping[str, Any],
    row: Mapping[str, Any],
    steps: Mapping[str, str],
) -> TraceLine:
    """One priced packet, stating only what the fight stated about it."""
    declaration = _declaration(event)
    raw = event.get("raw_damage")
    if raw is None and declaration is not None:
        raw = declaration.raw_amount
    damage_class = str(event["damage_type"])
    named = DamageClass.named(damage_class)
    # The class decides this column before any stated number does: a
    # resistance beside true damage is not a fact about the packet, whatever
    # put it there.
    meets_resistance = named is not None and named.is_mitigable
    resistance = None
    if meets_resistance:
        resistance = event.get("resistance_met")
        if resistance is None and declaration is not None:
            resistance = declaration.effective_resistance
    return TraceLine(
        time=float(event["time"]),
        source=source,
        mechanic=_mechanic(row, declaration),
        raw=None if raw is None else float(raw),
        damage_class=damage_class,
        resistance_met=None if resistance is None else float(resistance),
        amp="",
        mitigated=float(event["damage"]),
        step=steps.get(source, NO_STEP_MEASURED),
        refusals=_refusals(
            (NO_RAW_PUBLISHED, raw),
            # A class no resistance answers for meets none, so the blank
            # column is the fact and the class itself is what says so.
            (
                NO_RESISTANCE_PUBLISHED,
                resistance if meets_resistance else damage_class,
            ),
            (NO_STEP_MEASURED, steps.get(source)),
        ),
    )


def _amplifier_line(
    source: str,
    row: Mapping[str, Any],
    steps: Mapping[str, str],
    pool: Sequence[Mapping[str, Any]],
) -> TraceLine:
    """One amplifier, naming the pool of packets its deltas rode.

    An amplifier prices no packet of its own: it takes a share of packets
    already priced, so it states no raw and meets no resistance, and the
    packets it amplified carry no amp of their own.
    """
    classes = {str(event["damage_type"]) for event in pool}
    return TraceLine(
        time=float(pool[0]["time"]),
        source=source,
        mechanic=_mechanic(row, None),
        raw=None,
        damage_class=next(iter(classes)) if len(classes) == 1 else "mixed",
        resistance_met=None,
        amp=f"x{_amplifier_factor(row):g} over {len(pool)} packets",
        mitigated=float(row["total_damage"]),
        step=steps.get(source, NO_STEP_MEASURED),
        refusals=_refusals((NO_STEP_MEASURED, steps.get(source))),
    )


def _residue_lines(
    breakdown: Mapping[str, Any],
    lines: Sequence[TraceLine],
    steps: Mapping[str, str],
) -> list[TraceLine]:
    """One line per row the packets under-account, carrying what is left.

    The residue is the row's own published total minus the packets filed
    under it, which is the one arithmetic this module does and the one it
    cannot avoid: without it a row the ledger under-states leaves the trace
    quietly short of the fight.  Its damage class is read off those packets,
    the way an amplifier's is, and never off the row.
    """
    accounted: dict[str, float] = {}
    latest: dict[str, float] = {}
    classes: dict[str, set[str]] = {}
    for line in lines:
        accounted[line.source] = accounted.get(line.source, 0.0) + line.mitigated
        latest[line.source] = max(latest.get(line.source, 0.0), line.time)
        classes.setdefault(line.source, set()).add(line.damage_class)
    residues: list[TraceLine] = []
    for source, row in breakdown.items():
        stated = row.get("total_damage") if isinstance(row, Mapping) else None
        residue = 0.0 if stated is None else float(stated) - accounted.get(source, 0.0)
        if round(residue, 6) == 0.0:
            continue
        met = classes.get(source, set())
        residues.append(
            TraceLine(
                time=latest.get(source, 0.0),
                source=source,
                mechanic=_mechanic(row, None),
                raw=None,
                damage_class=next(iter(met)) if len(met) == 1 else "mixed",
                resistance_met=None,
                amp="",
                mitigated=residue,
                step=steps.get(source, NO_STEP_MEASURED),
                refusals=(
                    UNACCOUNTED_ROW_TOTAL,
                    *_refusals((NO_STEP_MEASURED, steps.get(source))),
                ),
            )
        )
    return residues


def fight_trace(result: Mapping[str, Any]) -> FightTrace:
    """Read one fight result into one line per priced packet, in fight order.

    Every number is one the engine stated: the raw off the event or off the
    declaration riding it, the resistance the mitigation site stamped or the
    one that declaration met, the step off the recorded authorship table.  A
    true-damage line states no resistance because it met none.  A fact the
    fight left unstated is a named
    refusal carrying the row key, never a value derived here.  The lines sum
    to the fight: a row the reconstructed packets under-account keeps its
    difference on a refusal line of its own rather than losing it.
    """
    if result.get("damage_events_tuple"):
        raise ValueError("a light-ledger fight publishes no traceable events")
    breakdown = result["breakdown"]
    steps = authorship.steps_of(breakdown)
    events = result["damage_events"]
    pools: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        source = str(event["source_key"])
        if _amplifier_factor(breakdown.get(source, _NO_ROW)) is not None:
            pools.setdefault(source, []).append(event)
    lines: list[TraceLine] = []
    booked: set[str] = set()
    for event in events:
        source = str(event["source_key"])
        if source not in pools:
            lines.append(
                _packet_line(source, event, breakdown.get(source, _NO_ROW), steps)
            )
        elif source not in booked:
            booked.add(source)
            lines.append(
                _amplifier_line(source, breakdown[source], steps, pools[source])
            )
    lines.extend(_residue_lines(breakdown, lines, steps))
    return FightTrace(
        tuple(lines),
        float(result["effective_armor"]),
        float(result["effective_mr"]),
    )
