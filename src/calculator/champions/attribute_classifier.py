"""Classify ability leveling attributes as damage or non-damage.

The JSON ``effects[].leveling[].attribute`` field contains strings like
``"Magic Damage"``, ``"Shield Strength"``, ``"Slow"``, etc. This module
determines which attributes represent damage that should be included in
the calculator, and what damage type they imply.
"""

# Keywords that indicate a damage attribute (case-insensitive match)
_DAMAGE_KEYWORDS: set[str] = {
    "damage",
}

# Keywords that indicate the attribute is NOT primary damage even if
# "damage" appears in the name. These are filtered out.
_EXCLUDE_KEYWORDS: set[str] = {
    "reduction",
    "minion",
    "monster",
    "cap",
    "minimum",
    "total",  # "Total Damage" is a pre-computed sum, not primary
    "subsequent",  # "Subsequent Magic Damage" is secondary (use primary)
    "bounce",  # Bounced damage is secondary
}

# Attribute names that should always be treated as primary damage
# even though they might be excluded by the general rules above.
_FORCE_INCLUDE: set[str] = set()

# Map attribute substrings to damage types
_DAMAGE_TYPE_HINTS: list[tuple[str, str]] = [
    ("magic damage", "magic"),
    ("physical damage", "physical"),
    ("true damage", "true"),
    ("mixed damage", "mixed"),
]


def is_damage_attribute(attribute: str) -> bool:
    """Check if a leveling attribute represents primary damage.

    Args:
        attribute: The attribute string (e.g. ``"Magic Damage"``).

    Returns:
        True if this attribute is primary damage for the calculator.
    """
    lower = attribute.lower()

    if attribute in _FORCE_INCLUDE:
        return True

    # Must contain "damage"
    if not any(kw in lower for kw in _DAMAGE_KEYWORDS):
        return False

    # Exclude non-primary damage attributes
    if any(kw in lower for kw in _EXCLUDE_KEYWORDS):
        return False

    return True


def is_primary_damage_attribute(attribute: str) -> bool:
    """Stricter check — only matches the main damage attribute.

    Only matches attributes named exactly "Magic Damage", "Physical Damage",
    "Damage", "Bonus Physical Damage", etc. Does NOT match compound names
    like "Damage Per Pass" or "Primary Magic Damage" — those are left
    for the fallback tier in ``_find_damage_leveling``.

    Args:
        attribute: The attribute string.

    Returns:
        True if this is likely the primary damage attribute.
    """
    lower = attribute.lower()

    primary_names = {
        "damage",
        "magic damage",
        "physical damage",
        "true damage",
        "bonus damage",
        "bonus magic damage",
        "bonus physical damage",
        "bonus true damage",
    }
    return lower in primary_names


def infer_damage_type_from_attribute(attribute: str) -> str | None:
    """Infer damage type from the attribute name.

    Args:
        attribute: The attribute string.

    Returns:
        ``"magic"``, ``"physical"``, ``"true"``, ``"mixed"``, or None.
    """
    lower = attribute.lower()
    for hint, dtype in _DAMAGE_TYPE_HINTS:
        if hint in lower:
            return dtype

    # Generic "Damage" or "Bonus Damage" without type qualifier
    if "damage" in lower:
        return None  # Caller should use ability's damageType field

    return None


def classify_damage_type(ability_data: dict) -> str:
    """Determine the damage type of an ability from its JSON data.

    Uses the ``damageType`` field as the primary signal, with fallback
    to inspecting attribute names in the leveling data.

    Args:
        ability_data: Single ability dict from champion JSON.

    Returns:
        ``"magic"``, ``"physical"``, ``"true"``, or ``"mixed"``.
    """
    dtype_field = ability_data.get("damageType", "")

    type_map = {
        "MAGIC_DAMAGE": "magic",
        "PHYSICAL_DAMAGE": "physical",
        "TRUE_DAMAGE": "true",
        "MIXED_DAMAGE": "mixed",
    }

    if dtype_field in type_map:
        return type_map[dtype_field]

    # OTHER_DAMAGE or missing — inspect attributes
    if dtype_field == "OTHER_DAMAGE":
        for effect in ability_data.get("effects", []):
            for lev in effect.get("leveling", []):
                attr_type = infer_damage_type_from_attribute(lev["attribute"])
                if attr_type:
                    return attr_type

    # Default to magic for damaging abilities with no clear type
    return "magic"
