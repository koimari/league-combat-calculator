"""Validate user-authored spell casts before the combat engine prices them."""

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any

from .certified_casts import CERTIFIED_DAMAGE_CASTS


@dataclass(frozen=True, slots=True)
class CombatEvent:
    """One requested cast and its explicit recipient."""

    id: str
    time: float
    caster_id: str
    slot: str
    recipient_id: str


def parse_combat_events(value: object) -> tuple[CombatEvent, ...] | None:
    """Preserve absence and validate each cast without coercing user values."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError("combat_events must be an array with at most 256 casts")
    events = []
    seen = set()
    fields = {"id", "time", "caster_id", "slot", "recipient_id"}
    for index, row in enumerate(value):
        label = f"combat_events[{index}]"
        if not isinstance(row, Mapping) or set(row) != fields:
            raise ValueError(
                f"{label} requires id, time, caster_id, slot, recipient_id"
            )
        for key in fields - {"time"}:
            if (
                not isinstance(row[key], str)
                or not row[key].strip()
                or len(row[key]) > 120
            ):
                raise ValueError(f"{label}.{key} must be a nonempty short string")
        if row["id"] in seen:
            raise ValueError(f"{label}.id must be unique")
        seen.add(row["id"])
        time = row["time"]
        if (
            isinstance(time, bool)
            or not isinstance(time, (int, float))
            or not math.isfinite(time)
            or time < 0
        ):
            raise ValueError(f"{label}.time must be a finite nonnegative number")
        if row["slot"] not in {"Q", "W", "E", "R"}:
            raise ValueError(f"{label}.slot must be Q, W, E, or R")
        events.append(CombatEvent(**{**row, "time": float(time)}))
    return tuple(sorted(events, key=lambda event: event.time))


def event_receipt(event: CombatEvent) -> dict[str, Any]:
    """Return the public request fields for an accepted cast."""
    return {
        "id": event.id,
        "time": event.time,
        "caster_id": event.caster_id,
        "slot": event.slot,
        "recipient_id": event.recipient_id,
    }


def roster_ids(names: list[str], team: str) -> list[str]:
    """Use receipt IDs and suffix repeated champions in roster order."""
    counts: dict[str, int] = {}
    result = []
    for name in names:
        counts[name] = counts.get(name, 0) + 1
        result.append(
            f"{team}:{name}" + (f":{counts[name]}" if counts[name] > 1 else "")
        )
    return result


def parse_combat_events_mode(value: object) -> str:
    """Choose whether the list replaces a scene or only its named casters."""
    if value is None:
        return "replace"
    if value not in ("replace", "overrides"):
        raise ValueError("combat_events_mode must be replace or overrides")
    return str(value)


# Every champion slot the support scanner prices as a shield, heal, buff or
# state on the caster or an ally (support_effects.derive_ally_effects over
# the cached rows), with the recipients an authored cast of it may name.
# The recipients follow the packet's sourced scope: a self-only cast names
# the caster; a one-teammate cast names an ally, and the caster too when the
# prose says "or herself"; a self-and-one cast names the extra ally and
# always covers the caster; a whole-team cast covers the whole side whoever
# is named. tests/test_combat_events.py re-derives this table from the
# scanner, so a slot the cache starts or stops pricing fails closed here.
CERTIFIED_SUPPORT_CASTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("Annie", "E"): ("self", "ally"),
    ("Azir", "E"): ("self",),
    ("Bard", "W"): ("ally",),
    ("Bel'Veth", "R"): ("self",),
    ("Cassiopeia", "E"): ("self",),
    ("Diana", "W"): ("self",),
    ("Ekko", "W"): ("self",),
    ("Fiora", "R"): ("self", "ally"),
    ("Galio", "W"): ("self",),
    ("Garen", "W"): ("self",),
    ("Ivern", "E"): ("self", "ally"),
    ("Janna", "E"): ("self", "ally"),
    ("Jarvan IV", "W"): ("self",),
    ("K'Sante", "E"): ("self", "ally"),
    ("Kai'Sa", "R"): ("self",),
    ("Karma", "E"): ("self", "ally"),
    ("Kassadin", "Q"): ("self",),
    ("Kayle", "W"): ("ally",),
    ("Kayn", "E"): ("self",),
    ("Kindred", "R"): ("self", "ally"),
    ("Lee Sin", "W"): ("self", "ally"),
    ("Lulu", "E"): ("self", "ally"),
    ("Lux", "W"): ("self",),
    ("Mel", "W"): ("self",),
    ("Milio", "W"): ("ally",),
    ("Milio", "E"): ("self", "ally"),
    ("Morgana", "E"): ("self", "ally"),
    ("Naafiri", "R"): ("self",),
    ("Nami", "W"): ("self", "ally"),
    ("Nautilus", "W"): ("self",),
    ("Nidalee", "E"): ("self", "ally"),
    ("Nunu & Willump", "R"): ("self",),
    ("Olaf", "W"): ("self",),
    ("Orianna", "E"): ("self", "ally"),
    ("Rakan", "Q"): ("self", "ally"),
    ("Rakan", "E"): ("ally",),
    ("Rell", "W"): ("self",),
    ("Renata Glasc", "W"): ("self", "ally"),
    ("Renata Glasc", "E"): ("self", "ally"),
    ("Riven", "E"): ("self",),
    ("Rumble", "W"): ("self",),
    ("Senna", "R"): ("ally",),
    ("Seraphine", "W"): ("self", "ally"),
    ("Shen", "R"): ("ally",),
    ("Sion", "W"): ("self",),
    ("Sona", "W"): ("self", "ally"),
    ("Soraka", "W"): ("ally",),
    ("Soraka", "R"): ("self", "ally"),
    ("Tahm Kench", "R"): ("ally",),
    ("Taric", "W"): ("self", "ally"),
    ("Taric", "R"): ("self", "ally"),
    ("Thresh", "W"): ("ally",),
    ("Udyr", "W"): ("self",),
    ("Urgot", "E"): ("self",),
    ("Yone", "W"): ("self",),
    ("Yuumi", "E"): ("self", "ally"),
    ("Yuumi", "R"): ("ally",),
}

# Casts whose damage or control lands on one named enemy; each was
# reviewed with its own routing test before it was listed.
CERTIFIED_ENEMY_CASTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("Lulu", "Q"): ("enemy",),
    ("Lulu", "W"): ("self", "ally", "enemy"),
    ("Lulu", "E"): ("self", "ally", "enemy"),
    ("Lulu", "R"): ("self", "ally"),
    ("Nasus", "W"): ("enemy",),
    ("Elise", "E"): ("enemy",),
    ("Rammus", "E"): ("enemy",),
    ("Zilean", "E"): ("enemy",),
    ("Vayne", "E"): ("enemy",),
}


def certified_reach(champion: str, slot: str) -> str | None:
    """How far an authored damage cast of this slot reaches, or None."""
    return CERTIFIED_DAMAGE_CASTS.get((champion, slot))


def certified_recipients(champion: str, slot: str) -> tuple[str, ...] | None:
    """The recipients an authored cast of this slot may name, or None."""
    enemy = CERTIFIED_ENEMY_CASTS.get((champion, slot))
    support = CERTIFIED_SUPPORT_CASTS.get((champion, slot))
    damage = ("enemy",) if (champion, slot) in CERTIFIED_DAMAGE_CASTS else None
    if enemy is None and support is None and damage is None:
        return None
    ordered: list[str] = []
    for kind in ("self", "ally", "enemy"):
        if kind in (enemy or ()) or kind in (support or ()) or kind in (damage or ()):
            ordered.append(kind)
    return tuple(ordered)


def combat_event_contract() -> dict[str, Any]:
    """Publish the same certified recipients that request validation accepts."""
    champions: dict[str, dict[str, dict[str, Any]]] = {}
    for champion, slot in sorted(
        set(CERTIFIED_ENEMY_CASTS)
        | set(CERTIFIED_SUPPORT_CASTS)
        | set(CERTIFIED_DAMAGE_CASTS),
        key=lambda pair: (pair[0], "QWER".index(pair[1])),
    ):
        recipients = certified_recipients(champion, slot)
        assert recipients is not None
        entry: dict[str, Any] = {"recipients": list(recipients)}
        reach = certified_reach(champion, slot)
        if reach is not None:
            entry["reach"] = reach
        champions.setdefault(champion, {})[slot] = entry
    return {
        "schema_version": 1,
        "modes": ["overrides", "replace"],
        "champions": champions,
    }
