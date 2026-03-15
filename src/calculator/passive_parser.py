"""Parse item passive/active effect descriptions from wiki markup in JSON data.

Extracts numeric values (base damage, ratios, cooldowns, etc.) from the
wiki-style markup used in the ``effects`` field of item passives/actives.
These parsed values are consumed by ``item_effects.py`` to build the
``ITEM_EFFECTS`` registry dynamically from the cached JSON data, so the
calculator automatically picks up balance changes when data is refreshed.

Markup reference (subset used by the parser):
    ``{{as|VALUE}}``  — stat display (number, sometimes nested)
    ``{{rd|MELEE|RANGED}}`` — melee / ranged split
    ``{{fd|VALUE}}``  — floor-displayed number
    ``{{ap|VALUE}}``  — AP-colored value
    ``{{ft|DISPLAY|TOOLTIP}}`` — tooltip (display vs. full text)
    ``{{pp|FORMULA}}`` — per-level or per-stat scaling table
    ``'''text'''``    — bold wiki text
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template-aware utilities
# ---------------------------------------------------------------------------


def _find_template_end(text: str, start: int) -> int:
    """Find the closing '}}' for a template starting at '{{'.

    Correctly handles nested templates like ``{{as|{{ap|5}}%}}``.

    Args:
        text: Full text.
        start: Index of the opening '{{'.

    Returns:
        Index just past the closing '}}', or len(text) if not found.
    """
    depth = 0
    pos = start
    while pos < len(text) - 1:
        if text[pos:pos + 2] == "{{":
            depth += 1
            pos += 2
        elif text[pos:pos + 2] == "}}":
            depth -= 1
            pos += 2
            if depth == 0:
                return pos
        else:
            pos += 1
    return len(text)


def _split_template_args(text: str, start: int) -> list[str]:
    """Split the pipe-separated arguments of a template at ``start``.

    Respects nesting: pipes inside ``{{...}}`` are not treated as
    separators.  The leading ``{{NAME|`` is stripped from the first arg.

    Args:
        text: Full text.
        start: Index of the opening '{{'.

    Returns:
        List of argument strings (excluding the template name prefix
        of the first argument).
    """
    end = _find_template_end(text, start)
    # inner = everything between {{ and }}
    inner = text[start + 2:end - 2]

    # Split by | at depth 0
    args: list[str] = []
    current_start = 0
    depth = 0
    for i, ch in enumerate(inner):
        if inner[i:i + 2] == "{{":
            depth += 1
        elif inner[i:i + 2] == "}}":
            depth -= 1
        elif ch == "|" and depth == 0:
            args.append(inner[current_start:i])
            current_start = i + 1
    args.append(inner[current_start:])
    return args


def _resolve_simple_templates(text: str) -> str:
    """Resolve simple templates to their plain-text values.

    Handles:
        ``{{fd|N}}``  → N
        ``{{ap|EXPR}}`` → evaluated EXPR
        ``{{#vardefineecho:NAME|VALUE}}`` → VALUE
    """
    # Resolve {{#vardefineecho:...|VALUE}}
    text = re.sub(
        r"\{\{#vardefineecho:[^|]+\|([^}]+)\}\}",
        r"\1",
        text,
    )
    # Resolve {{fd|N}}
    text = re.sub(r"\{\{fd\|(\d+(?:\.\d+)?)\}\}", r"\1", text)
    # Resolve {{ap|VALUE}} — only resolve plain numbers, NOT expressions.
    # On the LoL wiki, {{ap|...}} is a color-formatting template.
    # Expressions like {{ap|5*3}} or {{ap|60/4}} are DISPLAY calculations
    # shown to the reader, NOT the actual game values.  Evaluating them
    # as arithmetic (5*3=15, 60/4=10) produces incorrect results.
    def _resolve_ap(match: re.Match) -> str:
        val = match.group(1).strip()
        if re.match(r"^\d+(?:\.\d+)?$", val):
            return val  # Plain number — keep as-is
        return match.group(0)  # Expression — leave the template intact
    text = re.sub(r"\{\{ap\|([^}]+)\}\}", _resolve_ap, text)
    return text


def _eval_simple_expr(expr: str) -> float:
    """Evaluate a simple arithmetic expression (only +, -, *, / with numbers).

    Used for wiki markup like ``{{ap|60*3}}`` or ``{{ap|5/4}}``.
    Only allows safe numeric operations.
    """
    expr = expr.strip()
    if not re.match(r"^[\d\s\+\-\*/\.\(\)]+$", expr):
        raise ValueError(f"Unsafe expression: {expr}")
    return float(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307


# ---------------------------------------------------------------------------
# Value extractors
# ---------------------------------------------------------------------------


def _extract_number(text: str) -> float | None:
    """Extract the first plain number from text."""
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def _extract_percentage(text: str) -> float | None:
    """Extract a percentage as a decimal (e.g. '6%' → 0.06)."""
    match = re.search(r"(\d+(?:\.\d+)?)%", text)
    return float(match.group(1)) / 100.0 if match else None


def _extract_rd_values(text: str) -> tuple[str, str] | None:
    """Extract melee and ranged text from ``{{rd|M|R...}}``.

    Uses depth-aware splitting to handle nested templates like
    ``{{rd|1%|{{fd|0.5}}%}}``.
    """
    idx = text.find("{{rd|")
    if idx == -1:
        return None
    args = _split_template_args(text, idx)
    if len(args) < 3:
        return None
    # args[0] = "rd", args[1] = melee, args[2] = ranged
    melee = _resolve_simple_templates(args[1].strip())
    ranged = _resolve_simple_templates(args[2].strip())
    return (melee, ranged)


def _extract_all_rd_values(text: str) -> list[tuple[str, str]]:
    """Extract all {{rd|M|R}} pairs from text."""
    results = []
    search_start = 0
    while True:
        idx = text.find("{{rd|", search_start)
        if idx == -1:
            break
        args = _split_template_args(text, idx)
        if len(args) >= 3:
            melee = _resolve_simple_templates(args[1].strip())
            ranged = _resolve_simple_templates(args[2].strip())
            results.append((melee, ranged))
        search_start = _find_template_end(text, idx)
    return results


def _extract_rd_percentages(text: str) -> tuple[float, float] | None:
    """Extract melee/ranged percentage values from ``{{rd|M%|R%}}``."""
    pair = _extract_rd_values(text)
    if pair:
        m_match = re.search(r"(\d+(?:\.\d+)?)%", pair[0])
        r_match = re.search(r"(\d+(?:\.\d+)?)%", pair[1])
        if m_match and r_match:
            return (float(m_match.group(1)) / 100.0,
                    float(r_match.group(1)) / 100.0)
    return None


def _extract_rd_numbers(text: str) -> tuple[float, float] | None:
    """Extract melee/ranged flat numbers from ``{{rd|M|R}}``."""
    pair = _extract_rd_values(text)
    if pair:
        m = _extract_number(pair[0])
        r = _extract_number(pair[1])
        if m is not None and r is not None:
            return (m, r)
    return None


def _extract_ft_parts(text: str) -> tuple[str, str] | None:
    """Extract display and tooltip parts from ``{{ft|DISPLAY|TOOLTIP}}``."""
    idx = text.find("{{ft|")
    if idx == -1:
        return None
    args = _split_template_args(text, idx)
    if len(args) < 3:
        return None
    # args[0] = "ft", args[1] = display, args[2] = tooltip
    return (args[1], args[2])


# ---------------------------------------------------------------------------
# Passive / active lookup helpers
# ---------------------------------------------------------------------------


def _find_passive_by_name(
    item_data: dict[str, Any], name: str,
) -> dict[str, Any] | None:
    """Find a passive entry by its name field."""
    for passive in item_data.get("passives", []):
        if passive.get("name", "").lower() == name.lower():
            return passive
    return None


def _find_active_by_name(
    item_data: dict[str, Any], name: str,
) -> dict[str, Any] | None:
    """Find an active entry by its name field."""
    for active in item_data.get("active", []):
        if active.get("name", "").lower() == name.lower():
            return active
    return None


def _get_effect_text(
    item_data: dict[str, Any], source: str, name: str,
) -> str | None:
    """Get effects text from a passive or active by name."""
    if source == "passive":
        entry = _find_passive_by_name(item_data, name)
    elif source == "active":
        entry = _find_active_by_name(item_data, name)
    else:
        return None
    return entry.get("effects", "") if entry else None


def _get_cooldown_field(
    item_data: dict[str, Any], source: str, name: str,
) -> float | None:
    """Get the cooldown from a passive/active's cooldown field."""
    if source == "passive":
        entry = _find_passive_by_name(item_data, name)
    else:
        entry = _find_active_by_name(item_data, name)
    if entry and entry.get("cooldown") is not None:
        try:
            return float(entry["cooldown"])
        except (ValueError, TypeError):
            pass
    return None


# ---------------------------------------------------------------------------
# Per-type parsers
# ---------------------------------------------------------------------------


def _parse_simple_on_hit(text: str) -> dict[str, Any]:
    """Parse a simple flat on-hit damage passive.

    Handles: ``{{as|30 '''bonus''' magic damage}}``
    and: ``{{as|15 {{as|(+ 15% AP)}} '''bonus''' magic damage}}``
    """
    text = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    result["damage_type"] = "magic" if "magic damage" in text.lower() else "physical"

    flat_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)\s+", text)
    if flat_match:
        result["base"] = float(flat_match.group(1))

    ap_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s*AP", text)
    if ap_match:
        result["ap_ratio"] = float(ap_match.group(1)) / 100.0

    return result


def _parse_current_hp_on_hit(text: str) -> dict[str, Any]:
    """Parse on-hit scaling with target's current health (BoRK)."""
    result: dict[str, Any] = {"damage_type": "physical"}
    rd_pcts = _extract_rd_percentages(text)
    if rd_pcts:
        result["current_hp_ratio_melee"] = rd_pcts[0]
        result["current_hp_ratio_ranged"] = rd_pcts[1]

    min_match = re.search(r"maximum\s+of\s+(\d+)", text)
    if min_match:
        result["min_damage"] = float(min_match.group(1))
    return result


def _parse_max_hp_on_hit(text: str) -> dict[str, Any]:
    """Parse on-hit scaling with champion's max health (Titanic Hydra)."""
    result: dict[str, Any] = {"damage_type": "physical"}
    rd_pcts = _extract_rd_percentages(text)
    if rd_pcts:
        result["max_hp_ratio_melee"] = rd_pcts[0]
        result["max_hp_ratio_ranged"] = rd_pcts[1]
    return result


def _parse_mana_on_hit(text: str) -> dict[str, Any]:
    """Parse Muramana's mana-scaling on-hit."""
    text = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "physical"}
    mana_match = re.search(r"(\d+(?:\.\d+)?)%\s+'''maximum'''\s+mana", text)
    if mana_match:
        result["max_mana_ratio_on_hit"] = float(mana_match.group(1)) / 100.0
    return result


def _parse_spellblade(text: str) -> dict[str, Any]:
    """Parse a spellblade passive (Trinity, Lich Bane, Iceborn, etc.)."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    result["damage_type"] = "magic" if "magic damage" in text.lower() else "physical"

    base_ad_match = re.search(r"(\d+(?:\.\d+)?)%\s+'''base'''\s+AD", text_resolved)
    if base_ad_match:
        result["base_ad_ratio"] = float(base_ad_match.group(1)) / 100.0

    ap_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s*AP", text_resolved)
    if ap_match:
        result["ap_ratio"] = float(ap_match.group(1)) / 100.0

    cd_match = re.search(r"(\d+(?:\.\d+)?)\s+second\s+cooldown", text_resolved)
    if cd_match:
        result["cooldown"] = float(cd_match.group(1))
        result["weave_delay"] = result["cooldown"]

    return result


def _parse_essence_reaver_spellblade(text: str) -> dict[str, Any]:
    """Parse Essence Reaver's spellblade with crit scaling."""
    result = _parse_spellblade(text)
    crit_match = re.search(r"\{\{pp\|0\s+to\s+(\d+)", text)
    if crit_match:
        result["crit_bonus_max"] = float(crit_match.group(1))
    return result


def _parse_bloodsong_spellblade(text: str) -> dict[str, Any]:
    """Parse Bloodsong's spellblade with Expose Weakness.

    The spellblade portion uses '100% base AD' format.
    Expose Weakness uses {{rd|8%|5%}} format.
    """
    result: dict[str, Any] = {"damage_type": "physical"}
    text_resolved = _resolve_simple_templates(text)

    base_ad_match = re.search(r"(\d+(?:\.\d+)?)%\s+'''base'''\s+AD", text_resolved)
    if base_ad_match:
        result["base_ad_ratio"] = float(base_ad_match.group(1)) / 100.0

    cd_match = re.search(r"(\d+(?:\.\d+)?)\s+second\s+cooldown", text_resolved)
    if cd_match:
        result["cooldown"] = float(cd_match.group(1))
        result["weave_delay"] = result["cooldown"]

    # Expose Weakness: {{rd|8%|5%}} increased damage
    rd_pcts = _extract_rd_percentages(text)
    if rd_pcts:
        result["expose_weakness_melee"] = rd_pcts[0]
        result["expose_weakness_ranged"] = rd_pcts[1]

    return result


def _parse_dusk_dawn_spellblade(text: str) -> dict[str, Any]:
    """Parse Dusk and Dawn's spellblade with double on-hit."""
    result = _parse_spellblade(text)
    if "on-hit" in text.lower() and ("again" in text.lower() or "delay" in text.lower()):
        result["double_on_hit"] = True
    return result


def _parse_burn_max_hp(text: str) -> dict[str, Any]:
    """Parse Liandry's Torment burn (% max HP).

    The markup uses {{ft|PER_TICK|TOTAL}} — we extract from the TOTAL
    section to get the full-duration values.
    """
    result: dict[str, Any] = {"damage_type": "magic"}

    # Try to extract from {{ft|...|TOTAL}} tooltip section
    ft_parts = _extract_ft_parts(text)
    if ft_parts:
        total_text = _resolve_simple_templates(ft_parts[1])
        hp_match = re.search(
            r"(\d+(?:\.\d+)?)%\s+(?:of\s+)?(?:the\s+)?(?:target's\s+)?'''maximum'''\s+health",
            total_text,
        )
        if hp_match:
            result["max_hp_ratio_total"] = float(hp_match.group(1)) / 100.0
    else:
        # Fallback: look for total in main text
        text_resolved = _resolve_simple_templates(text)
        # Look for 'total' context
        total_match = re.search(
            r"total.*?(\d+(?:\.\d+)?)%.*?'''maximum'''.*?health",
            text_resolved,
            re.DOTALL | re.IGNORECASE,
        )
        if total_match:
            result["max_hp_ratio_total"] = float(total_match.group(1)) / 100.0
        else:
            hp_match = re.search(
                r"(\d+(?:\.\d+)?)%\s+(?:of\s+)?(?:the\s+)?(?:target's\s+)?'''maximum'''\s+health",
                text_resolved,
            )
            if hp_match:
                result["max_hp_ratio_total"] = float(hp_match.group(1)) / 100.0

    dur_match = re.search(r"over\s+(\d+(?:\.\d+)?)\s+seconds", text)
    if dur_match:
        result["duration"] = float(dur_match.group(1))

    return result


def _parse_burn_flat_ap(text: str) -> dict[str, Any]:
    """Parse Blackfire Torch burn (flat base + AP ratio)."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "magic"}

    # Look for 'total of {{as|NUMBER'
    base_match = re.search(r"total\s+of\s+\{\{as\|(\d+(?:\.\d+)?)", text_resolved)
    if base_match:
        result["base_total"] = float(base_match.group(1))

    # AP ratio — search AFTER "total of" to avoid per-tick values
    total_idx = text_resolved.lower().find("total of")
    if total_idx >= 0:
        after_total = text_resolved[total_idx:]
        ap_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s*AP", after_total)
        if ap_match:
            result["ap_ratio_total"] = float(ap_match.group(1)) / 100.0

    dur_match = re.search(r"over\s+(\d+(?:\.\d+)?)\s+seconds", text)
    if dur_match:
        result["duration"] = float(dur_match.group(1))

    return result


def _parse_immolate(text: str) -> dict[str, Any]:
    """Parse immolate passive (Sunfire Aegis, Hollow Radiance)."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "magic"}

    # Pattern: {{as|NUMBER {{as|(+ NUMBER% '''bonus''' health)}} ... damage}}
    base_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)\s+\{\{as\|", text_resolved)
    if not base_match:
        # Simpler: just find a number before bonus health
        base_match = re.search(r"[Dd]eal\s+\{\{as\|(\d+(?:\.\d+)?)", text_resolved)
    if base_match:
        result["base_per_second"] = float(base_match.group(1))

    hp_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s+'''bonus'''\s+health", text_resolved)
    if hp_match:
        result["bonus_hp_ratio_per_second"] = float(hp_match.group(1)) / 100.0

    return result


def _parse_luden(
    text: str, cooldown_field: float | None = None,
) -> dict[str, Any]:
    """Parse Luden's Companion/Echo proc damage."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "magic"}

    base_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)\|?(?:magic )?damage\}", text_resolved)
    if not base_match:
        base_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)", text_resolved)
    if base_match:
        result["base_per_charge"] = float(base_match.group(1))

    ap_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s*AP", text_resolved)
    if ap_match:
        result["ap_ratio_per_charge"] = float(ap_match.group(1)) / 100.0

    charge_match = re.search(r"[Gg]ain\s+(\d+)\s+", text_resolved)
    if charge_match:
        result["charges"] = int(charge_match.group(1))

    result["single_target_multiplier"] = 2.0

    if cooldown_field is not None:
        result["cooldown"] = cooldown_field

    return result


def _parse_statikk_shiv(text: str) -> dict[str, Any]:
    """Parse Statikk Shiv empowered auto attacks with magic damage.

    Wiki markup: ``Your next 3 basic attacks...deal {{as|60 '''bonus'''
    magic damage}}...``
    """
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "magic"}

    base_match = re.search(
        r"\{\{as\|(\d+(?:\.\d+)?)\s+'''bonus'''\s+magic\s+damage", text_resolved,
    )
    if base_match:
        result["base"] = float(base_match.group(1))

    count_match = re.search(r"next\s+(\d+)\s+basic\s+attacks", text_resolved)
    if count_match:
        result["empowered_auto_count"] = int(count_match.group(1))

    return result


def _parse_proc_flat_ap(text: str) -> dict[str, Any]:
    """Parse a proc with flat base + AP ratio (Stormsurge)."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "magic"}

    base_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)\|?(?:magic )?damage\}", text_resolved)
    if not base_match:
        base_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)", text_resolved)
    if base_match:
        result["base"] = float(base_match.group(1))

    ap_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s*AP", text_resolved)
    if ap_match:
        result["ap_ratio"] = float(ap_match.group(1)) / 100.0

    return result


def _parse_stormsurge_trigger(text: str) -> dict[str, Any]:
    """Parse Stormsurge's Stormraider trigger for cooldown."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    cd_match = re.search(r"(\d+(?:\.\d+)?)\s+second\s+cooldown", text_resolved)
    if cd_match:
        result["cooldown"] = float(cd_match.group(1))
    return result


def _parse_terminus_pen(text: str) -> dict[str, Any]:
    """Parse Terminus Juxtaposition dark/light hit stacking.

    Extracts:
    - dark_pen_per_stack: % armor/magic pen per dark hit stack
    - dark_max_stacks: max number of stacks
    - light_resist_min: bonus armor/MR per light stack at level 1
    - light_resist_max: bonus armor/MR per light stack at max level
    """
    result: dict[str, Any] = {}
    pen_match = re.search(r"(\d+(?:\.\d+)?)%\s+\{\{as\|armor\s+penetration", text)
    if not pen_match:
        pen_match = re.search(
            r"''Dark''\s+hits\s+grant\s+(\d+(?:\.\d+)?)%", text,
        )
    if pen_match:
        result["dark_pen_per_stack"] = float(pen_match.group(1)) / 100.0

    stacks_match = re.search(r"up\s+to\s+(\d+)\s+times", text)
    if stacks_match:
        result["dark_max_stacks"] = int(stacks_match.group(1))

    # Light hit resistances: {{pp|6 to 8 for 3|1;11;14|type=level}}
    light_match = re.search(
        r"''Light''\s+hits\s+grant\s+\{\{pp\|(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)\s+for",
        text,
    )
    if light_match:
        result["light_resist_min"] = float(light_match.group(1))
        result["light_resist_max"] = float(light_match.group(2))

    return result


def _parse_zazzak(
    text: str, cooldown_field: float | None = None,
) -> dict[str, Any]:
    """Parse Zaz'Zak's Realmspike proc damage."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "magic"}

    base_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)\|?(?:magic )?damage\}", text_resolved)
    if not base_match:
        base_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)", text_resolved)
    if base_match:
        result["base"] = float(base_match.group(1))

    ap_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s*AP", text_resolved)
    if ap_match:
        result["ap_ratio"] = float(ap_match.group(1)) / 100.0

    hp_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+(?:of\s+)?(?:each\s+)?target's\s+'''maximum'''\s+health",
        text_resolved,
    )
    if hp_match:
        result["target_max_hp_ratio"] = float(hp_match.group(1)) / 100.0

    if cooldown_field is not None:
        result["cooldown"] = cooldown_field

    return result


def _parse_malignance(text: str) -> dict[str, Any]:
    """Parse Malignance Hatefog ult proc damage.

    The markup uses ``{{ft|PER_TICK|TOTAL}}`` where the total section
    contains evaluated expressions like ``{{ap|60*3}}`` and
    ``{{ap|5*3}}% AP``.
    """
    result: dict[str, Any] = {"damage_type": "magic"}

    ft_parts = _extract_ft_parts(text)
    if ft_parts:
        total_text = _resolve_simple_templates(ft_parts[1])

        # Base total: first number in an {{as|NUMBER... pattern
        base_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)", total_text)
        if base_match:
            result["base"] = float(base_match.group(1))

        # AP ratio total: (+ NUMBER% AP)
        ap_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s*AP", total_text)
        if ap_match:
            result["ap_ratio"] = float(ap_match.group(1)) / 100.0

    # MR reduction: 'magic resistance by NUMBER'
    mr_match = re.search(r"magic\s+resistance\s+by\s+(\d+(?:\.\d+)?)", text)
    if mr_match:
        result["mr_reduction"] = float(mr_match.group(1))

    return result


def _parse_active_flat_ap(text: str) -> dict[str, Any]:
    """Parse an active with flat base + AP ratio (Rocketbelt)."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "magic"}

    base_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)\s+\{\{as\|", text_resolved)
    if not base_match:
        base_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)", text_resolved)
    if base_match:
        result["base"] = float(base_match.group(1))

    ap_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s*AP", text_resolved)
    if ap_match:
        result["ap_ratio"] = float(ap_match.group(1)) / 100.0

    return result


def _parse_hydra_active(text: str) -> dict[str, Any]:
    """Parse Hydra/Stridebreaker active (total AD ratio)."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "physical"}

    ad_match = re.search(r"(\d+(?:\.\d+)?)%\s*AD", text_resolved)
    if ad_match:
        result["total_ad_ratio"] = float(ad_match.group(1)) / 100.0

    return result


def _parse_gunblade_active(text: str) -> dict[str, Any]:
    """Parse Hextech Gunblade's level-scaling active."""
    result: dict[str, Any] = {"damage_type": "magic"}

    # Pattern: {{pp|175 + (253-175)/17*(x-1) for 20}}
    pp_match = re.search(
        r"\{\{pp\|(\d+(?:\.\d+)?)\s*\+\s*\((\d+(?:\.\d+)?)-\1\)/(\d+(?:\.\d+)?)\*\(x-1\)\s+for\s+(\d+)",
        text,
    )
    if pp_match:
        min_val = float(pp_match.group(1))
        max_at_denom = float(pp_match.group(2))
        denom = float(pp_match.group(3))
        num_points = int(pp_match.group(4))
        result["base_min"] = min_val
        result["base_max"] = round(
            min_val + (max_at_denom - min_val) / denom * (num_points - 1), 1,
        )

    ap_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s*AP", text)
    if ap_match:
        result["ap_ratio"] = float(ap_match.group(1)) / 100.0

    return result


def _parse_damage_amp_per_second(
    text: str,
    key_prefix: str = "",
) -> dict[str, Any]:
    """Parse a damage amp stacking per second (Riftmaker, Liandry's Suffering).

    Args:
        text: The passive effects text.
        key_prefix: Optional prefix for keys (e.g. 'damage_' for Liandry's).
    """
    result: dict[str, Any] = {}
    amp_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+increased\s+damage.*?"
        r"stacking\s+up\s+to\s+(\d+)\s+times.*?"
        r"total\s+of\s+(\d+(?:\.\d+)?)%",
        text,
        re.DOTALL,
    )
    if amp_match:
        result[f"{key_prefix}amp_per_second"] = float(amp_match.group(1)) / 100.0
        result[f"{key_prefix}amp_max"] = float(amp_match.group(3)) / 100.0
    return result


def _parse_blackfire_amp(text: str) -> dict[str, Any]:
    """Parse Blackfire Torch's AP amplification passive."""
    result: dict[str, Any] = {}
    # Text: 'increase your {{as|ability power}} by 4%'
    amp_match = re.search(
        r"(?:ability\s+power)\}\}\s+by\s+(\d+(?:\.\d+)?)%",
        text,
        re.IGNORECASE,
    )
    if not amp_match:
        amp_match = re.search(
            r"(?:ability\s+power|AP)\s+by\s+(\d+(?:\.\d+)?)%",
            text,
            re.IGNORECASE,
        )
    if amp_match:
        result["ap_amp_per_target"] = float(amp_match.group(1)) / 100.0
    return result


def _parse_lord_dominik(text: str) -> dict[str, Any]:
    """Parse Lord Dominik's Regards Giant Slayer passive."""
    result: dict[str, Any] = {}
    pp_match = re.search(
        r"\{\{pp\|0\s+to\s+(\d+(?:\.\d+)?)\s+for\s+\d+\|0\s+to\s+(\d+(?:\.\d+)?)",
        text,
    )
    if pp_match:
        result["max_amp"] = float(pp_match.group(1)) / 100.0
        result["bonus_hp_cap"] = float(pp_match.group(2))
    return result


def _parse_hexoptics_magnification(text: str) -> dict[str, Any]:
    """Parse Hexoptics C44 Magnification distance-based basic damage amp.

    The passive scales from 0% to a maximum increased basic damage based on
    distance to target, using the ``{{pp|0 to MAX for N|0 to DIST|...}}``
    template.
    """
    result: dict[str, Any] = {}
    pp_match = re.search(
        r"\{\{pp\|0\s+to\s+(\d+(?:\.\d+)?)\s+for\s+\d+\|0\s+to\s+(\d+(?:\.\d+)?)",
        text,
    )
    if pp_match:
        result["max_amp"] = float(pp_match.group(1)) / 100.0
        result["max_distance"] = float(pp_match.group(2))
    return result


def _parse_horizon_focus(text: str) -> dict[str, Any]:
    """Parse Horizon Focus Hypershot damage amplification.

    Extracts the flat damage amp percentage from text like
    ``increasing your damage dealt to them by 10%``.
    """
    result: dict[str, Any] = {}
    amp_match = re.search(
        r"increasing\s+your\s+damage\s+dealt\s+to\s+them\s+by\s+"
        r"(\d+(?:\.\d+)?)%",
        text,
    )
    if amp_match:
        result["amp"] = float(amp_match.group(1)) / 100.0
    return result


def _parse_hullbreaker(text: str) -> dict[str, Any]:
    """Parse Hullbreaker Skipper stacking on-hit proc.

    Extracts base AD ratios and max HP ratios (melee/ranged) from the
    two ``{{rd|...}}`` pairs, and the hits required from the stacking text.
    """
    result: dict[str, Any] = {"damage_type": "physical"}

    # Extract all rd pairs: first is base AD ratio, second is max HP ratio
    rd_pairs = _extract_all_rd_values(text)

    if len(rd_pairs) >= 1:
        melee_ad, ranged_ad = rd_pairs[0]
        # Melee: "120%" -> 1.20
        m = re.search(r"(\d+(?:\.\d+)?)%", melee_ad)
        if m:
            result["base_ad_ratio_melee"] = float(m.group(1)) / 100.0
        # Ranged: may be "{{ap|120*0.7}}%" — need to eval the expression
        r_match = re.search(r"\{\{ap\|([^}]+)\}\}", ranged_ad)
        if r_match:
            try:
                result["base_ad_ratio_ranged"] = (
                    _eval_simple_expr(r_match.group(1)) / 100.0
                )
            except ValueError:
                pass
        elif not r_match:
            r_plain = re.search(r"(\d+(?:\.\d+)?)%", ranged_ad)
            if r_plain:
                result["base_ad_ratio_ranged"] = (
                    float(r_plain.group(1)) / 100.0
                )

    if len(rd_pairs) >= 2:
        melee_hp, ranged_hp = rd_pairs[1]
        m = re.search(r"(\d+(?:\.\d+)?)%", melee_hp)
        if m:
            result["max_hp_ratio_melee"] = float(m.group(1)) / 100.0
        r_match = re.search(r"\{\{ap\|([^}]+)\}\}", ranged_hp)
        if r_match:
            try:
                result["max_hp_ratio_ranged"] = (
                    _eval_simple_expr(r_match.group(1)) / 100.0
                )
            except ValueError:
                pass
        elif not r_match:
            r_plain = re.search(r"(\d+(?:\.\d+)?)%", ranged_hp)
            if r_plain:
                result["max_hp_ratio_ranged"] = (
                    float(r_plain.group(1)) / 100.0
                )

    # Hits required: "stacking up to N times"
    stacks_match = re.search(r"stacking\s+up\s+to\s+(\d+)\s+times", text)
    if stacks_match:
        result["hits_required"] = int(stacks_match.group(1))

    return result


def _parse_spear_of_shojin(text: str) -> dict[str, Any]:
    """Parse Spear of Shojin stacking ability damage amp."""
    result: dict[str, Any] = {}
    amp_match = re.search(r"(\d+(?:\.\d+)?)%\s+increased\s+damage", text)
    if amp_match:
        result["amp_per_stack"] = float(amp_match.group(1)) / 100.0

    stacks_match = re.search(r"stacking\s+up\s+to\s+(\d+)\s+times", text)
    if stacks_match:
        result["max_stacks"] = int(stacks_match.group(1))
    return result


def _parse_abyssal_mask(text: str) -> dict[str, Any]:
    """Parse Abyssal Mask magic damage amplification."""
    result: dict[str, Any] = {}
    amp_match = re.search(r"(\d+(?:\.\d+)?)%\s+increased\s+magic\s+damage", text)
    if amp_match:
        result["magic_amp"] = float(amp_match.group(1)) / 100.0
    return result


def _parse_actualizer(text: str) -> dict[str, Any]:
    """Parse Actualizer active ability damage amp."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}

    # Pattern: 'gain 15% (+ 0.5% per 100 bonus mana) increased ability damage'
    # Need to match '15%' specifically before the '(+'
    amp_match = re.search(
        r"gain\s+(\d+(?:\.\d+)?)%\s+(?:\{\{as\|)?\(?",
        text_resolved,
        re.IGNORECASE,
    )
    if amp_match:
        result["base_amp"] = float(amp_match.group(1)) / 100.0

    per_mana_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+per\s+100\s+'''bonus'''\s+mana",
        text_resolved,
    )
    if per_mana_match:
        result["amp_per_100_bonus_mana"] = float(per_mana_match.group(1)) / 100.0

    return result


def _parse_eclipse(
    text: str, cooldown_field: float | None = None,
) -> dict[str, Any]:
    """Parse Eclipse Ever Rising Moon proc."""
    result: dict[str, Any] = {"damage_type": "physical"}
    rd_pcts = _extract_rd_percentages(text)
    if rd_pcts:
        result["target_max_hp_ratio_melee"] = rd_pcts[0]
        result["target_max_hp_ratio_ranged"] = rd_pcts[1]
    if cooldown_field is not None:
        result["cooldown"] = cooldown_field
    return result


def _parse_bastionbreaker(
    text: str, cooldown_field: float | None = None,
) -> dict[str, Any]:
    """Parse Bastionbreaker Shaped Charge true damage."""
    result: dict[str, Any] = {}
    all_rds = _extract_all_rd_values(text)

    if len(all_rds) >= 1:
        m = _extract_number(all_rds[0][0])
        r = _extract_number(all_rds[0][1])
        if m is not None and r is not None:
            result["base_melee"] = m
            result["base_ranged"] = r

    if len(all_rds) >= 2:
        m = _extract_number(all_rds[1][0])
        r = _extract_number(all_rds[1][1])
        if m is not None and r is not None:
            result["lethality_ratio_melee"] = m
            result["lethality_ratio_ranged"] = r

    if cooldown_field is not None:
        result["cooldown"] = cooldown_field

    return result


def _parse_overlord_tyranny(text: str) -> dict[str, Any]:
    """Parse Overlord's Bloodmail Tyranny bonus AD from bonus health."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    ratio_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+'''bonus'''\s+health", text_resolved,
    )
    if ratio_match:
        result["bonus_health_to_ad_ratio"] = float(ratio_match.group(1)) / 100.0
    return result


def _parse_mana_to_ap_awe(text: str) -> dict[str, Any]:
    """Parse Awe passive: bonus mana to AP conversion.

    Used by both Archangel's Staff (1%) and Seraph's Embrace (2%).
    Wiki markup: ``Grants {{as|ability power}} equal to {{as|N% '''bonus''' mana}}.``
    """
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    ratio_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+'''bonus'''\s+mana", text_resolved,
    )
    if ratio_match:
        result["bonus_mana_to_ap_ratio"] = float(ratio_match.group(1)) / 100.0
    return result


def _parse_rabadons_opus(text: str) -> dict[str, Any]:
    """Parse Rabadon's Deathcap Magical Opus: percentage AP increase.

    Wiki markup: ``Increase your {{as|ability power}} by 30%.``
    """
    result: dict[str, Any] = {}
    amp_match = re.search(
        r"(?:ability\s+power)\}\}\s+by\s+(\d+(?:\.\d+)?)%",
        text,
        re.IGNORECASE,
    )
    if amp_match:
        result["ap_percent_increase"] = float(amp_match.group(1)) / 100.0
    return result


def _parse_dawncore_first_light(text: str) -> dict[str, Any]:
    """Parse Dawncore First Light: AP per additional base mana regen.

    Wiki markup: ``...{{as|10 ability power}} for every additional
    {{as|100% '''base''' mana regeneration}}.``
    """
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    ap_match = re.search(
        r"(\d+(?:\.\d+)?)\s+ability\s+power", text_resolved,
    )
    if ap_match:
        result["ap_per_mana_regen_unit"] = float(ap_match.group(1))
    regen_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+'''base'''\s+mana\s+regeneration",
        text_resolved,
    )
    if regen_match:
        result["mana_regen_threshold_percent"] = float(regen_match.group(1))
    return result


def _parse_bandlepipes_fanfare(text: str) -> dict[str, Any]:
    """Parse Bandlepipes Fanfare: melee/ranged bonus attack speed.

    Wiki markup contains: ``{{as|{{rd|30|20}}% '''bonus''' attack speed}}``
    The text has multiple ``{{rd|...}}`` templates; we need the one
    followed by ``attack speed``.
    """
    result: dict[str, Any] = {}
    all_rds = _extract_all_rd_values(text)
    for melee_text, ranged_text in all_rds:
        m = _extract_number(melee_text)
        r = _extract_number(ranged_text)
        if m is not None and r is not None and m > r and m >= 20:
            result["bonus_attack_speed_melee"] = m
            result["bonus_attack_speed_ranged"] = r
            break
    return result


def _parse_muramana_awe(text: str) -> dict[str, Any]:
    """Parse Muramana Awe passive: max mana to bonus AD conversion.

    Wiki markup: ``Grants {{as|'''bonus''' attack damage}} equal to
    {{as|2% '''maximum''' mana}}.``
    """
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    ratio_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+'''maximum'''\s+mana", text_resolved,
    )
    if ratio_match:
        result["max_mana_to_ad_ratio"] = float(ratio_match.group(1)) / 100.0
    return result


def _parse_shojin_dragonforce(text: str) -> dict[str, Any]:
    """Parse Spear of Shojin Dragonforce: basic ability haste.

    Wiki markup: ``Gain 25 [[Haste#Basic ability haste|basic ability haste]].``
    """
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    haste_match = re.search(
        r"(\d+)\s+.*?basic\s+ability\s+haste", text_resolved, re.IGNORECASE,
    )
    if haste_match:
        result["basic_ability_haste"] = float(haste_match.group(1))
    return result


def _parse_flowing_water_rapids(text: str) -> dict[str, Any]:
    """Parse Staff of Flowing Water Rapids: bonus AP from healing/shielding.

    Wiki markup: ``...grants you and them {{as|45 ability power}} for 6 seconds.``
    """
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    ap_match = re.search(r"(\d+)\s+ability\s+power", text_resolved)
    if ap_match:
        result["rapids_bonus_ap"] = float(ap_match.group(1))
    return result


def _parse_steraks_claws(text: str) -> dict[str, Any]:
    """Parse Sterak's Gage The Claws that Catch: base AD to bonus AD.

    Wiki markup: ``Gain {{as|'''bonus''' attack damage}} equal to
    {{as|45% '''base''' AD}}.``
    """
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    ratio_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+'''base'''\s+AD", text_resolved,
    )
    if ratio_match:
        result["base_ad_to_bonus_ad_ratio"] = float(ratio_match.group(1)) / 100.0
    return result


def _parse_stormrazor_bolt(text: str) -> dict[str, Any]:
    """Parse Stormrazor Bolt: energized magic damage on first auto.

    Wiki markup: ``...deals {{as|100 '''bonus''' magic damage}} [[on-hit]]...``
    """
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "magic"}
    dmg_match = re.search(
        r"(\d+)\s+'''bonus'''\s+magic\s+damage", text_resolved,
    )
    if dmg_match:
        result["base"] = float(dmg_match.group(1))
    return result


def _parse_titanic_active(text: str) -> dict[str, Any]:
    """Parse Titanic Hydra Titanic Crescent active: max HP bonus damage.

    Wiki markup: ``...deal {{as|{{rd|4%|2%}} '''maximum''' health|hp}}
    {{as|'''bonus''' physical damage}} to the primary target...``
    """
    result: dict[str, Any] = {"damage_type": "physical"}
    all_rds = _extract_all_rd_values(text)
    if len(all_rds) >= 1:
        m = _extract_percentage(all_rds[0][0])
        r = _extract_percentage(all_rds[0][1])
        if m is not None and r is not None:
            result["active_max_hp_ratio_melee"] = m
            result["active_max_hp_ratio_ranged"] = r
    return result


def _parse_opportunity_preparation(text: str) -> dict[str, Any]:
    """Parse Opportunity's Preparation bonus lethality passive.

    Extracts the melee/ranged bonus lethality values and the duration
    the bonus persists after dealing damage.
    """
    result: dict[str, Any] = {}
    rd_pair = _extract_rd_numbers(text)
    if rd_pair:
        result["bonus_lethality_melee"] = rd_pair[0]
        result["bonus_lethality_ranged"] = rd_pair[1]

    duration_match = re.search(
        r"remains\s+for\s+(\d+(?:\.\d+)?)\s+seconds", text,
    )
    if duration_match:
        result["duration"] = float(duration_match.group(1))
    return result


def _parse_armor_reduction(text: str) -> dict[str, Any]:
    """Parse Black Cleaver armor reduction stacking."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    red_match = re.search(r"(\d+(?:\.\d+)?)%\s+armor\s+reduction", text_resolved)
    if red_match:
        result["reduction_per_stack"] = float(red_match.group(1)) / 100.0

    stacks_match = re.search(r"at\s+(\d+)\s+stacks", text_resolved)
    if stacks_match:
        result["max_stacks"] = int(stacks_match.group(1))
    return result


def _parse_mr_reduction(text: str) -> dict[str, Any]:
    """Parse Bloodletter's Curse MR reduction stacking."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    red_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+magic\s+resistance\s+reduction", text_resolved,
    )
    if red_match:
        result["mr_reduction_per_stack"] = float(red_match.group(1)) / 100.0

    stacks_match = re.search(r"stacking\s+up\s+to\s+(\d+)\s+times", text_resolved)
    if stacks_match:
        result["max_stacks"] = int(stacks_match.group(1))
    return result


def _parse_execute(text: str) -> dict[str, Any]:
    """Parse The Collector execute threshold."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    thresh_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+of\s+their\s+'''maximum'''\s+health",
        text_resolved,
    )
    if thresh_match:
        result["threshold"] = float(thresh_match.group(1)) / 100.0
    return result


def _parse_navori(text: str) -> dict[str, Any]:
    """Parse Navori Flickerblade CD refund."""
    result: dict[str, Any] = {}
    cd_match = re.search(r"by\s+(\d+(?:\.\d+)?)%", text)
    if cd_match:
        result["cd_refund_percent"] = float(cd_match.group(1)) / 100.0
    return result


def _parse_shadowflame(text: str) -> dict[str, Any]:
    """Parse Shadowflame magic/true crit below health threshold."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}

    crit_match = re.search(r"(\d+(?:\.\d+)?)%\}\}\s*damage", text_resolved)
    if not crit_match:
        crit_match = re.search(
            r"critically?\s+strike.*?for\s+\{\{as\|(\d+(?:\.\d+)?)%",
            text_resolved,
        )
    if crit_match:
        result["crit_multiplier"] = float(crit_match.group(1)) / 100.0

    thresh_match = re.search(
        r"below\s+(\d+(?:\.\d+)?)%\s+'''maximum'''\s+health", text_resolved,
    )
    if thresh_match:
        result["health_threshold"] = float(thresh_match.group(1)) / 100.0
    return result


def _parse_dead_mans_plate(text: str) -> dict[str, Any]:
    """Parse Dead Man's Plate on-hit at max momentum."""
    result: dict[str, Any] = {"damage_type": "physical"}

    # Base flat: {{pp|0 to 40 for 11|...}} — max value at full momentum
    pp_base_match = re.search(
        r"\{\{as\|\{\{pp\|0\s+to\s+(\d+(?:\.\d+)?)\s+for",
        text,
    )
    if pp_base_match:
        result["base"] = float(pp_base_match.group(1))

    # Base AD ratio: {{pp|0 to 100 for 11|...}} as percentage
    pp_ad_match = re.search(
        r"\+\s*\{\{pp\|0\s+to\s+(\d+(?:\.\d+)?)\s+for",
        text,
    )
    if pp_ad_match:
        result["base_ad_ratio"] = float(pp_ad_match.group(1)) / 100.0

    return result


def _parse_heartsteel(text: str) -> dict[str, Any]:
    """Parse Heartsteel Colossal Consumption proc."""
    result: dict[str, Any] = {"damage_type": "physical"}

    base_match = re.search(
        r"\{\{as\|(\d+(?:\.\d+)?)\|physical\s+damage\}\}", text,
    )
    if base_match:
        result["base"] = float(base_match.group(1))

    hp_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s+'''maximum'''\s+health", text)
    if hp_match:
        result["max_hp_ratio"] = float(hp_match.group(1)) / 100.0

    cd_match = re.search(r"(\d+)\s+second\s+cooldown", text)
    if cd_match:
        result["cooldown"] = float(cd_match.group(1))
    return result


def _parse_kraken_slayer(text: str) -> dict[str, Any]:
    """Parse Kraken Slayer Bring It Down stacking on-hit damage.

    The passive text contains level-scaling formulas in
    ``{{rd|MELEE_FORMULA|RANGED_FORMULA|levels=...|pp=true}}``.
    """
    result: dict[str, Any] = {"damage_type": "physical"}

    rd_pair = _extract_rd_values(text)
    if rd_pair:
        melee_formula, ranged_formula = rd_pair

        # Extract melee base and per-level from formula like
        # '150 + (200-150)/10*(x-1) for 13'
        melee_base_match = re.search(r"^(\d+(?:\.\d+)?)", melee_formula.strip())
        if melee_base_match:
            result["base_melee"] = float(melee_base_match.group(1))

        melee_scale = re.search(
            r"\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)/(\d+(?:\.\d+)?)",
            melee_formula,
        )
        if melee_scale:
            max_val = float(melee_scale.group(1))
            min_val = float(melee_scale.group(2))
            denom = float(melee_scale.group(3))
            result["per_level_melee"] = (max_val - min_val) / denom

        # Ranged: may use MELEE*0.8 pattern
        ranged_base_match = re.search(r"^(\d+(?:\.\d+)?)", ranged_formula.strip())
        if ranged_base_match:
            ranged_base = float(ranged_base_match.group(1))
            if "*0.8" in ranged_formula or "* 0.8" in ranged_formula:
                result["base_ranged"] = ranged_base * 0.8
                if "per_level_melee" in result:
                    result["per_level_ranged"] = result["per_level_melee"] * 0.8
            else:
                result["base_ranged"] = ranged_base
                # Try to extract ranged scaling separately
                ranged_scale = re.search(
                    r"\((\d+(?:\.\d+)?)\*0\.8-(\d+(?:\.\d+)?)\*0\.8\)/(\d+(?:\.\d+)?)",
                    ranged_formula,
                )
                if ranged_scale:
                    max_r = float(ranged_scale.group(1)) * 0.8
                    min_r = float(ranged_scale.group(2)) * 0.8
                    denom_r = float(ranged_scale.group(3))
                    result["per_level_ranged"] = (max_r - min_r) / denom_r

    # Scaling start level
    levels_match = re.search(r"levels=\d+;(\d+)\s+to\s+(\d+)", text)
    if levels_match:
        result["scaling_start_level"] = int(levels_match.group(1))

    # Missing HP bonus max — from {{pp|0 to 75 by 5|...}}
    missing_match = re.search(r"\{\{pp\|0\s+to\s+(\d+(?:\.\d+)?)\s+by", text)
    if missing_match:
        result["missing_hp_bonus_max"] = float(missing_match.group(1)) / 100.0

    # Hits required: 'At 2 stacks' → 3 hits
    hits_match = re.search(r"At\s+(\d+)\s+stacks", text)
    if hits_match:
        result["hits_required"] = int(hits_match.group(1)) + 1

    return result


def _parse_hexplate(text: str) -> dict[str, Any]:
    """Parse Experimental Hexplate Overdrive passive."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}

    as_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+'''bonus'''\s+attack\s+speed", text_resolved,
    )
    if as_match:
        result["bonus_attack_speed_percent"] = float(as_match.group(1))

    dur_match = re.search(r"for\s+(\d+(?:\.\d+)?)\s+seconds", text_resolved)
    if dur_match:
        result["duration"] = float(dur_match.group(1))

    cd_match = re.search(
        r"(\d+(?:\.\d+)?)\s+second\s+cooldown", text_resolved,
    )
    if cd_match:
        result["cooldown"] = float(cd_match.group(1))

    return result


def _parse_fiendhunter(text: str) -> dict[str, Any]:
    """Parse Fiendhunter Bolts Opening Barrage passive."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}

    as_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+'''bonus'''\s+attack\s+speed", text_resolved,
    )
    if as_match:
        result["bonus_attack_speed_percent"] = float(as_match.group(1))

    count_match = re.search(r"next\s+(\d+)\s+basic\s+attacks", text_resolved)
    if count_match:
        result["empowered_auto_count"] = int(count_match.group(1))

    # Reduced crit ratio: find first 'N% '''total''' critical damage'
    # This appears inside nested {{ft|...|{{sti|{{as|80% ...}}}}}} templates
    crit_matches = re.findall(
        r"(\d+(?:\.\d+)?)%\s+'''total'''\s+critical\s+damage", text,
    )
    if crit_matches:
        result["reduced_crit_ratio"] = float(crit_matches[0]) / 100.0

    # Natural crit true damage ratio: 'equal to N% of the triggering'
    true_match = re.search(
        r"equal\s+to\s+(\d+(?:\.\d+)?)%\s+of\s+the\s+triggering",
        text_resolved,
    )
    if true_match:
        result["natural_crit_true_damage_ratio"] = float(true_match.group(1)) / 100.0

    dur_match = re.search(r"within\s+(\d+(?:\.\d+)?)\s+seconds", text_resolved)
    if dur_match:
        result["duration"] = float(dur_match.group(1))

    return result


def _parse_guinsoo_phantom(text: str) -> dict[str, Any]:
    """Parse Guinsoo's Rageblade Seething Strike phantom hit mechanics."""
    result: dict[str, Any] = {}
    text_resolved = _resolve_simple_templates(text)

    stack_match = re.search(
        r"stacking\s+up\s+to\s+(\d+)\s+times", text_resolved,
    )
    if stack_match:
        max_stacks = int(stack_match.group(1))
        result["stacking_autos"] = max_stacks + 1

    phantom_match = re.search(
        r"''Phantom''\s+stack.*?up\s+to\s+(\d+)\s+stacks.*?"
        r"At\s+(\d+)\s+''Phantom''",
        text_resolved,
        re.DOTALL,
    )
    if phantom_match:
        phantom_needed = int(phantom_match.group(2))
        result["phantom_interval"] = phantom_needed + 1

    return result


def _parse_sundered_sky(text: str) -> dict[str, Any]:
    """Parse Sundered Sky Lightshield Strike crit passive.

    Wiki markup: ``...{{sti|{{as|80% '''total''' critical damage}}}}...``
    Extracts the reduced crit ratio (80%) and cooldown.
    """
    result: dict[str, Any] = {}

    # Reduced crit ratio from tooltip: "80% '''total''' critical damage"
    crit_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+'''total'''\s+critical\s+damage", text,
    )
    if crit_match:
        result["reduced_crit_ratio"] = float(crit_match.group(1)) / 100.0

    # Cooldown: "10 second cooldown"
    cd_match = re.search(
        r"(\d+(?:\.\d+)?)\s+second\s+cooldown", text,
    )
    if cd_match:
        result["cooldown"] = float(cd_match.group(1))

    return result


def _parse_voltaic_firmament(text: str) -> dict[str, Any]:
    """Parse Voltaic Cyclosword Firmament energized damage.

    Wiki markup: ``...deals {{as|100 '''bonus''' physical damage}} [[on-hit]]...``
    """
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "physical"}

    dmg_match = re.search(
        r"(\d+)\s+'''bonus'''\s+physical\s+damage", text_resolved,
    )
    if dmg_match:
        result["base"] = float(dmg_match.group(1))

    return result


def _parse_unending_despair(text: str) -> dict[str, Any]:
    """Parse Unending Despair Anguish periodic damage.

    Wiki markup: ``Every 4 seconds...deal {{as|magic damage}} equal to
    {{as|3% of your '''bonus''' health}}...``
    """
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "magic"}

    # Interval: "Every N seconds"
    interval_match = re.search(
        r"[Ee]very\s+(\d+(?:\.\d+)?)\s+seconds", text_resolved,
    )
    if interval_match:
        result["interval"] = float(interval_match.group(1))

    # Bonus health ratio: "N% of your '''bonus''' health"
    hp_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+of\s+your\s+'''bonus'''\s+health",
        text_resolved,
    )
    if hp_match:
        result["bonus_hp_ratio"] = float(hp_match.group(1)) / 100.0

    return result


def _parse_terminus_juxtaposition_pen(text: str) -> dict[str, Any]:
    """Parse Terminus Juxtaposition for per-stack armor/magic penetration.

    Already handled by _parse_terminus_pen for dark_pen_per_stack and
    dark_max_stacks. This is the same parser — kept as alias.
    """
    return _parse_terminus_pen(text)


def _parse_yun_tal_flurry(text: str) -> dict[str, Any]:
    """Parse Yun Tal Wildarrows Flurry bonus attack speed.

    Wiki markup: ``...grants you {{as|30% '''bonus''' attack speed}}
    for 6 seconds (30 second cooldown...)``
    """
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}

    as_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+'''bonus'''\s+attack\s+speed",
        text_resolved,
    )
    if as_match:
        result["bonus_attack_speed_percent"] = float(as_match.group(1))

    dur_match = re.search(
        r"for\s+(\d+(?:\.\d+)?)\s+seconds", text_resolved,
    )
    if dur_match:
        result["duration"] = float(dur_match.group(1))

    cd_match = re.search(
        r"(\d+(?:\.\d+)?)\s+second\s+cooldown", text_resolved,
    )
    if cd_match:
        result["cooldown"] = float(cd_match.group(1))

    return result


# ---------------------------------------------------------------------------
# Item parse configuration
# ---------------------------------------------------------------------------

_NAME_ALIASES: dict[str, str] = {
    # Add entries here when JSON item name differs from code name.
    # Format: "JSON name": "Code name"
}
_REVERSE_ALIASES: dict[str, str] = {v: k for k, v in _NAME_ALIASES.items()}


def _json_name(code_name: str) -> str:
    """Get the JSON item name for a code name."""
    return _REVERSE_ALIASES.get(code_name, code_name)


# Maps item code name → list of (source, name, parser_func, extra_kwargs).
_ITEM_PARSE_CONFIG: dict[str, list[tuple]] = {
    # ── On-Hit ──
    "Nashor's Tooth": [("passive", "Icathian Bite", _parse_simple_on_hit, {})],
    "Blade of the Ruined King": [("passive", "Mist's Edge", _parse_current_hp_on_hit, {})],
    "Wit's End": [("passive", "Fray", _parse_simple_on_hit, {})],
    "Terminus": [
        ("passive", "Shadow", _parse_simple_on_hit, {}),
        ("passive", "Juxtaposition", _parse_terminus_pen, {}),
    ],
    "Titanic Hydra": [
        ("passive", "Cleave", _parse_max_hp_on_hit, {}),
        ("active", "Titanic Crescent", _parse_titanic_active, {}),
    ],
    "Guinsoo's Rageblade": [
        ("passive", "Wrath", _parse_simple_on_hit, {}),
        ("passive", "Seething Strike", _parse_guinsoo_phantom, {}),
    ],
    "Muramana": [
        ("passive", "Shock", _parse_mana_on_hit, {}),
        ("passive", "Awe", _parse_muramana_awe, {}),
    ],

    # ── Spellblade ──
    "Trinity Force": [("passive", "Spellblade", _parse_spellblade, {})],
    "Lich Bane": [("passive", "Spellblade", _parse_spellblade, {})],
    "Essence Reaver": [("passive", "Spellblade", _parse_essence_reaver_spellblade, {})],
    "Iceborn Gauntlet": [("passive", "Spellblade", _parse_spellblade, {})],
    "Bloodsong": [("passive", "Spellblade", _parse_bloodsong_spellblade, {})],
    "Dusk and Dawn": [("passive", "Spellblade", _parse_dusk_dawn_spellblade, {})],

    # ── Burn / DoT ──
    "Liandry's Torment": [
        ("passive", "Torment", _parse_burn_max_hp, {}),
        ("passive", "Suffering", _parse_damage_amp_per_second, {"key_prefix": "damage_"}),
    ],
    "Blackfire Torch": [
        ("passive", "Baleful Blaze", _parse_burn_flat_ap, {}),
        ("passive", "Blackfire", _parse_blackfire_amp, {}),
    ],
    "Sunfire Aegis": [("passive", "Immolate", _parse_immolate, {})],
    "Hollow Radiance": [("passive", "Immolate", _parse_immolate, {})],

    # ── Proc ──
    "Luden's Echo": [("passive", "Echo", _parse_luden, {"use_cooldown_field": True})],
    "Statikk Shiv": [("passive", "Electrospark", _parse_statikk_shiv, {})],
    "Stormsurge": [
        ("passive", "Squall", _parse_proc_flat_ap, {}),
        ("passive", "Stormraider", _parse_stormsurge_trigger, {}),
    ],
    "Zaz'Zak's Realmspike": [("passive", "Void Explosion", _parse_zazzak, {"use_cooldown_field": True})],

    # ── Ult Proc ──
    "Malignance": [("passive", "Hatefog", _parse_malignance, {})],

    # ── Active Items ──
    "Hextech Rocketbelt": [("active", "Supersonic", _parse_active_flat_ap, {})],
    "Hextech Gunblade": [("active", "Lightning Bolt", _parse_gunblade_active, {})],
    "Profane Hydra": [("active", "Heretical Cleave", _parse_hydra_active, {})],
    "Ravenous Hydra": [("active", "Ravenous Crescent", _parse_hydra_active, {})],
    "Stridebreaker": [("active", "Breaking Shockwave", _parse_hydra_active, {})],

    # ── Damage Amplification ──
    "Riftmaker": [("passive", "Void Corruption", _parse_damage_amp_per_second, {})],
    "Lord Dominik's Regards": [("passive", "Giant Slayer", _parse_lord_dominik, {})],
    "Spear of Shojin": [
        ("passive", "Focused Will", _parse_spear_of_shojin, {}),
        ("passive", "Dragonforce", _parse_shojin_dragonforce, {}),
    ],
    "Abyssal Mask": [("passive", "Unmake", _parse_abyssal_mask, {})],
    "Actualizer": [("active", "Mana Made Real", _parse_actualizer, {})],
    "Hexoptics C44": [("passive", "Magnification", _parse_hexoptics_magnification, {})],
    "Horizon Focus": [("passive", "Hypershot", _parse_horizon_focus, {})],

    # ── Ult Attack Speed Buffs ──
    "Experimental Hexplate": [("passive", "Overdrive", _parse_hexplate, {})],
    "Fiendhunter Bolts": [("passive", "Opening Barrage", _parse_fiendhunter, {})],

    # ── Max HP Proc ──
    "Eclipse": [("passive", "Ever Rising Moon", _parse_eclipse, {"use_cooldown_field": True})],

    # ── Lethality Proc ──
    "Bastionbreaker": [("passive", "Shaped Charge", _parse_bastionbreaker, {"use_cooldown_field": True})],

    # ── Bonus Lethality ──
    "Opportunity": [("passive", "Preparation", _parse_opportunity_preparation, {})],

    # ── Resistance Reduction ──
    "Black Cleaver": [("passive", "Carve", _parse_armor_reduction, {})],
    "Bloodletter's Curse": [("passive", "Vile Decay", _parse_mr_reduction, {})],

    # ── Execute ──
    "The Collector": [("passive", "Death", _parse_execute, {})],

    # ── Critical Strike ──
    # Infinity Edge has no passives — bonus_crit_damage comes from stats section
    # (handled automatically by parse_item_effect's stats check)
    "Infinity Edge": [],
    "Navori Flickerblade": [("passive", "Transcendence", _parse_navori, {})],
    "Shadowflame": [("passive", "Cinderbloom", _parse_shadowflame, {})],

    # ── Stat Conversion ──
    "Overlord's Bloodmail": [("passive", "Tyranny", _parse_overlord_tyranny, {})],
    "Seraph's Embrace": [("passive", "Awe", _parse_mana_to_ap_awe, {})],
    "Archangel's Staff": [("passive", "Awe", _parse_mana_to_ap_awe, {})],
    "Rabadon's Deathcap": [("passive", "Magical Opus", _parse_rabadons_opus, {})],
    "Dawncore": [("passive", "First Light", _parse_dawncore_first_light, {})],
    "Bandlepipes": [("passive", "Fanfare", _parse_bandlepipes_fanfare, {})],
    "Staff of Flowing Water": [("passive", "Rapids", _parse_flowing_water_rapids, {})],
    "Sterak's Gage": [("passive", "The Claws that Catch", _parse_steraks_claws, {})],

    # ── Energized ──
    "Rapid Firecannon": [("passive", "Sharpshooter", _parse_simple_on_hit, {})],
    "Stormrazor": [("passive", "Bolt", _parse_stormrazor_bolt, {})],
    "Voltaic Cyclosword": [("passive", "Firmament", _parse_voltaic_firmament, {})],

    # ── Crit Modifier (first-auto) ──
    "Sundered Sky": [("passive", "Lightshield Strike", _parse_sundered_sky, {})],

    # ── Periodic AoE ──
    "Unending Despair": [("passive", "Anguish", _parse_unending_despair, {})],

    # ── Conditional AS ──
    "Yun Tal Wildarrows": [("passive", "Flurry", _parse_yun_tal_flurry, {})],

    # ── Single-proc / Special ──
    "Dead Man's Plate": [("passive", "Shipwrecker", _parse_dead_mans_plate, {})],
    "Heartsteel": [("passive", "Colossal Consumption", _parse_heartsteel, {})],
    "Kraken Slayer": [("passive", "Bring It Down", _parse_kraken_slayer, {})],
    "Hullbreaker": [("passive", "Skipper", _parse_hullbreaker, {})],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _find_item_data_by_name(
    items_data: dict[str, Any], item_name: str,
) -> dict[str, Any] | None:
    """Find an item entry in JSON data by name (case-insensitive)."""
    json_name = _json_name(item_name)
    for _, item_data in items_data.items():
        if item_data.get("name", "").lower() == json_name.lower():
            return item_data
    return None


def parse_item_effect(
    item_name: str, items_data: dict[str, Any],
) -> dict[str, Any] | None:
    """Parse a single item's effect values from JSON data.

    Args:
        item_name: The code name used in ITEM_EFFECTS.
        items_data: Full items.json data dict.

    Returns:
        Dict of parsed effect values, or None if not found/configured.
    """
    config = _ITEM_PARSE_CONFIG.get(item_name)
    if config is None:
        return None

    item_data = _find_item_data_by_name(items_data, item_name)
    if not item_data:
        logger.debug("Item '%s' not found in JSON data", item_name)
        return None

    merged: dict[str, Any] = {}

    for source, entry_name, parser_func, extra in config:
        text = _get_effect_text(item_data, source, entry_name)
        if text is None:
            logger.debug(
                "No %s '%s' found for item '%s'",
                source, entry_name, item_name,
            )
            continue

        # Build kwargs from extra config
        kwargs: dict[str, Any] = {}
        if extra.get("use_cooldown_field"):
            kwargs["cooldown_field"] = _get_cooldown_field(
                item_data, source, entry_name,
            )
        if "key_prefix" in extra:
            kwargs["key_prefix"] = extra["key_prefix"]

        if kwargs:
            parsed = parser_func(text, **kwargs)
        else:
            parsed = parser_func(text)

        merged.update(parsed)

    # Check stats section for crit damage bonus (e.g. Infinity Edge)
    stats = item_data.get("stats", {})
    crit_dmg = stats.get("criticalStrikeDamage", {})
    if crit_dmg.get("percent", 0) > 0:
        merged["bonus_crit_damage"] = crit_dmg["percent"] / 100.0

    return merged if merged else None


def parse_all_item_effects(
    items_data: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Parse all configured item effects from JSON data.

    Args:
        items_data: Full items.json data dict (keyed by item ID).

    Returns:
        Dict mapping item code names to parsed effect values.
    """
    results: dict[str, dict[str, Any]] = {}
    for item_name in _ITEM_PARSE_CONFIG:
        parsed = parse_item_effect(item_name, items_data)
        if parsed:
            results[item_name] = parsed
    return results
