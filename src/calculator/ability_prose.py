"""The numbers a cached ability states in a sentence instead of a leveling row."""

import re
from collections.abc import Mapping
from typing import Any

_PROSE_SECONDS_RE = re.compile(
    r"(?<![\w.])(?P<value>\d+(?:\.\d+)?)\s+seconds?\b", re.IGNORECASE
)
_PROSE_SHIELD_SECONDS_RE = re.compile(
    r"\bshield(?:s|ed|ing)?\b.*?\bfor\s+(?:up to\s+)?"
    r"(?P<value>\d+(?:\.\d+)?)\s+seconds?\b",
    re.IGNORECASE,
)
_PROSE_INVULNERABILITY_DELAY_RE = re.compile(
    r"\bdescends?\b.*?\bover\s+(?P<value>\d+(?:\.\d+)?)\s+seconds?\b",
    re.IGNORECASE,
)
_PROSE_INVULNERABILITY_DURATION_RE = re.compile(
    r"\binvulnerable\b.*?\bfor\s+(?P<value>\d+(?:\.\d+)?)\s+seconds?\b",
    re.IGNORECASE,
)
_PROSE_CONTROL_DURATION_RE = re.compile(
    r"\b(?:airborne|charm(?:s|ed|ing)?|fear(?:s|ed|ing)?|"
    r"immobiliz(?:e|es|ed|ing)|knockback|knockup|"
    r"knock(?:s|ed|ing)?\s+(?:\w+\s+)?up|polymorph(?:s|ed|ing)?|"
    r"root(?:s|ed|ing)?|sleep(?:s|ed|ing)?|slow(?:s|ed|ing)?|"
    r"stun(?:s|ned|ning)?|"
    r"suppression|suppress(?:es|ed|ing)?|taunt(?:s|ed|ing)?)\b"
    r".*?\bfor\s+(?P<value>\d+(?:\.\d+)?)\s+seconds?\b",
    re.IGNORECASE,
)
_PROSE_DAMAGE_REDUCTION_CAP_RE = re.compile(
    r"\bcapped\s+at\s+(?P<value>\d+(?:\.\d+)?)\s*%\s+of\s+"
    r"(?:the\s+)?damage\s+instance\b",
    re.IGNORECASE,
)
_PROSE_DAMAGE_REDUCTION_RE = re.compile(
    r"\b(?:gains?|has)\s+(?P<value>\d+(?:\.\d+)?)\s*%\s+" r"damage\s+reduction\b",
    re.IGNORECASE,
)


def effect_description(ability: Mapping[str, Any], effect_index: int) -> str:
    """One cached effect's description text, or "" when that effect is gone.

    A mechanic the cache states only in prose (Annie's Pyromania charge,
    Kennen's Mark of the Storm) is read out of this string by the module
    that owns it, which then raises if the sentence stopped saying what it
    priced.  ``""`` is the one quiet answer: a patch that drops an effect
    row entirely is the same failure, and the caller names it.
    """
    effects = ability.get("effects")
    if not isinstance(effects, list) or not 0 <= effect_index < len(effects):
        return ""
    effect = effects[effect_index]
    if not isinstance(effect, dict):
        return ""
    description = effect.get("description")
    return "" if description is None else str(description)


def _prose_value(
    pattern: re.Pattern[str], ability: Mapping[str, Any], effect_index: int
) -> float | None:
    """The ``value`` group of *pattern*'s first match in one effect description."""
    match = pattern.search(effect_description(ability, effect_index))
    return float(match.group("value")) if match else None


def extract_description_duration(
    ability: Mapping[str, Any], effect_index: int = 0
) -> float | None:
    """Read the first seconds value from one cached effect description."""
    return _prose_value(_PROSE_SECONDS_RE, ability, effect_index)


def extract_description_shield_duration(
    ability: Mapping[str, Any], effect_index: int = 0
) -> float | None:
    """Read the duration attached to a shield phrase in one effect."""
    description = effect_description(ability, effect_index)
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", description)
    for sentence in sentences:
        match = _PROSE_SHIELD_SECONDS_RE.search(sentence)
        if match:
            return float(match.group("value"))
    return None


def extract_description_invulnerability_timing(
    ability: Mapping[str, Any], effect_index: int = 0
) -> tuple[float | None, float | None]:
    """Read a sourced invulnerability delay and window from one description."""
    return (
        _prose_value(_PROSE_INVULNERABILITY_DELAY_RE, ability, effect_index),
        _prose_value(_PROSE_INVULNERABILITY_DURATION_RE, ability, effect_index),
    )


def extract_description_control_duration(
    ability: dict[str, Any], effect_index: int = 0
) -> float | None:
    """Read the first action-blocking control duration from one description."""
    durations = extract_description_control_durations(ability, effect_index)
    return durations[0] if durations else None


def extract_description_control_durations(
    ability: Mapping[str, Any], effect_index: int = 0
) -> list[float]:
    """Read every action-blocking control duration from one description."""
    description = effect_description(ability, effect_index)
    return [
        float(match.group("value"))
        for match in _PROSE_CONTROL_DURATION_RE.finditer(description)
    ]


def extract_description_damage_reduction_cap(
    ability: Mapping[str, Any], effect_index: int = 0
) -> float | None:
    """Read a percentage cap on one pre-mitigation damage instance."""
    return _prose_value(_PROSE_DAMAGE_REDUCTION_CAP_RE, ability, effect_index)


def extract_description_damage_reduction(
    ability: Mapping[str, Any], effect_index: int = 0
) -> float | None:
    """Read a sourced percentage of incoming damage reduction."""
    return _prose_value(_PROSE_DAMAGE_REDUCTION_RE, ability, effect_index)
