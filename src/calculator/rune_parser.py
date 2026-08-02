"""Parse League Wiki ``Template:Rune data <name>`` wikitext into rune payloads.

The wiki keeps one machine-readable template per rune with named params
(``path``, ``slot``, ``cooldown``, ``description``). Inside descriptions,
numbers appear in a small set of template forms:

- ``{{pp|60 + 10 * x|1 to 20 by 1}}`` — a leveling formula over champion level
- ``{{as|(+ 10% '''bonus''' AD)}}`` / ``{{as|(+ 5% AP)}}`` — scaling ratios
- ``{{fd|0.25}}-second delay`` — fixed decimals
- ``{{as|7% '''bonus''' true damage}}`` — a post-mitigation true-damage ratio
- ``{{g|10}}`` — flat gold grants
- ``{{rd|50%|35%}}`` — a melee/ranged value split (melee first, per Template:Rd)
- prose stack rules — "Applying 3 stacks to a target within a 3 second period"
- prose buff windows — "grants ... for 3 seconds, causing"
- prose refreshing stacks — "apply a stack for 4 seconds ... stacking up to 3 times"
- prose damage amps — "grant you 8% increased damage against champions"

This module is pure parsing: no network, no file writes. ``data_updater``
fetches the wikitext and writes the resulting payloads to ``data/runes.json``;
``rune_effects`` consumes them with fail-closed typed accessors. A value this
parser cannot read is simply absent from the payload — never defaulted.
"""

import ast
import re
from typing import Any

_PARAM_LINE = re.compile(r"^\|(\w+)\s*=\s?(.*)$")
_PP_TEMPLATE = re.compile(r"\{\{pp\|([^{}]+)\}\}")
_AS_RATIO = re.compile(
    r"\{\{as\|\(\+\s*([\d.]+)%\s*(?:('''bonus'''|bonus)\s*)?(AD|AP)\)"
)
_STACK_RULE = re.compile(r"Applying (\d+) stacks? to a target within a ([\d.]+) second")
_STACK_DURATION = re.compile(r"apply a \{\{tip\|stacks?\}\} for ([\d.]+) seconds")
_MAX_STACKS = re.compile(r"stacking up to (\d+) times")
_DAMAGE_AMP = re.compile(r"([\d.]+)% increased damage against champions")
_BONUS_TRUE_DAMAGE = re.compile(r"\{\{as\|([\d.]+)%\s*'''bonus'''\s*true damage\}\}")
_FLAT_GOLD = re.compile(r"\{\{g\|([\d.]+)\}\}")
_MELEE_RANGED_SPLIT = re.compile(r"\{\{rd\|([\d.]+)%\|([\d.]+)%\}\}")
_BUFF_WINDOW = re.compile(r"for ([\d.]+) seconds, causing")
_PROC_DELAY = re.compile(r"\{\{fd\|([\d.]+)\}\}-second delay")
_TT_TEMPLATE = re.compile(r"\{\{tt\|([^|}]+)")
_RANGE_SPEC = re.compile(r"^([\d.]+)\s+to\s+([\d.]+)(?:\s+by\s+([\d.]+))?$")

_ALLOWED_PP_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.USub,
    ast.Constant,
    ast.Name,
    ast.Load,
)


def parse_rune_template(wikitext: str) -> dict[str, str]:
    """Split a rune-data template into its named ``|param = value`` fields.

    The wiki formats these one param per line; a value continues until the
    next param line or the template's closing ``}}`` line.
    """
    params: dict[str, str] = {}
    current_key: str | None = None
    lines = wikitext.splitlines()
    for line in lines[1:]:  # line 0 is the template header
        if line.strip() == "}}":
            current_key = None
            continue
        match = _PARAM_LINE.match(line)
        if match:
            current_key = match.group(1)
            params[current_key] = match.group(2).strip()
        elif current_key is not None:
            params[current_key] = f"{params[current_key]}\n{line}".strip()
    return {key: _strip_unbalanced_close(value) for key, value in params.items()}


def _strip_unbalanced_close(value: str) -> str:
    """Drop a trailing ``}}`` that closes the template, not a value's brace."""
    while value.endswith("}}") and value.count("}}") > value.count("{{"):
        value = value[:-2].rstrip()
    return value


def evaluate_pp(formula: str, range_spec: str | None) -> list[float]:
    """Evaluate one ``{{pp}}`` body into its per-step numeric values.

    Two sourced forms exist: a semicolon list of literal values, and an
    arithmetic formula in ``x`` evaluated over an ``N to M by S`` range.
    """
    formula = formula.strip()
    if ";" in formula and "x" not in formula:
        return [float(part) for part in formula.split(";") if part.strip()]
    if not range_spec:
        raise ValueError(f"pp formula {formula!r} has no level range")
    range_match = _RANGE_SPEC.match(range_spec.strip())
    if not range_match:
        raise ValueError(f"Unsupported pp range spec {range_spec!r}")
    start, stop, step = (
        float(range_match.group(1)),
        float(range_match.group(2)),
        float(range_match.group(3) or 1),
    )
    expression = _safe_pp_expression(formula)
    values = []
    x = start
    while x <= stop + 1e-9:
        values.append(_evaluate_pp_node(expression.body, x))
        x += step
    return values


def _safe_pp_expression(formula: str) -> ast.Expression:
    """Parse a pp formula, rejecting anything beyond arithmetic in ``x``."""
    try:
        expression = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Unparseable pp formula {formula!r}") from exc
    for node in ast.walk(expression):
        if not isinstance(node, _ALLOWED_PP_NODES):
            raise ValueError(f"Unsupported pp syntax in {formula!r}")
        if isinstance(node, ast.Name) and node.id != "x":
            raise ValueError(f"Unknown pp variable {node.id!r} in {formula!r}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError(f"Non-numeric pp constant in {formula!r}")
    return expression


def _evaluate_pp_node(node: ast.AST, x: float) -> float:
    """Recursively evaluate a validated pp arithmetic node."""
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return x
    if isinstance(node, ast.UnaryOp):
        return -_evaluate_pp_node(node.operand, x)
    if isinstance(node, ast.BinOp):
        left = _evaluate_pp_node(node.left, x)
        right = _evaluate_pp_node(node.right, x)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        return left / right
    raise ValueError("Unreachable pp node")  # guarded by _safe_pp_expression


def parse_cooldown(value: str | None) -> float | None:
    """Read a cooldown param: a plain number or a ``{{tt|N|note}}`` wrapper."""
    if not value:
        return None
    tt_match = _TT_TEMPLATE.search(value)
    text = tt_match.group(1) if tt_match else value
    try:
        return float(text.strip())
    except ValueError:
        return None


def parse_effects(description: str) -> tuple[dict[str, Any], list[str]]:
    """Extract the numeric effect values a description carries.

    Returns the effects dict plus parse warnings. Keys are only present
    when their source text parsed — consumers fail closed on absence.
    """
    effects: dict[str, Any] = {}
    warnings: list[str] = []
    _parse_leveling(description, effects, warnings)
    _parse_scalar_templates(description, effects, warnings)
    _parse_prose_rules(description, effects)
    return effects, warnings


def _parse_leveling(
    description: str, effects: dict[str, Any], warnings: list[str]
) -> None:
    """Evaluate every ``{{pp}}`` template into a per-level value list."""
    leveling = []
    for pp_body in _PP_TEMPLATE.findall(description):
        parts = [part for part in pp_body.split("|") if "=" not in part]
        formula = parts[0] if parts else ""
        range_spec = parts[1] if len(parts) > 1 else None
        try:
            leveling.append(evaluate_pp(formula, range_spec))
        except ValueError as exc:
            warnings.append(str(exc))
    if leveling:
        effects["leveling"] = leveling


def _parse_scalar_templates(
    description: str, effects: dict[str, Any], warnings: list[str]
) -> None:
    """Read the single-value template forms: ratios, gold, range splits."""

    def record(key: str, value: Any) -> None:
        # A rune whose text matches the same key twice (Summon Aery's
        # damage AND shield ratios) would silently keep the last value —
        # a plausible-looking wrong number. Record the ambiguity so the
        # implementer sees it in data/runes.json.
        if key in effects and effects[key] != value:
            warnings.append(f"{key} matched more than once: {effects[key]}, {value}")
        effects[key] = value

    for percent, bonus_marker, stat in _AS_RATIO.findall(description):
        if stat == "AP":
            key = "ap_ratio"
        elif bonus_marker:
            key = "bonus_ad_ratio"
        else:
            key = "ad_ratio"
        record(key, float(percent) / 100.0)

    for percent in _BONUS_TRUE_DAMAGE.findall(description):
        record("bonus_true_damage_ratio", float(percent) / 100.0)

    for amount in _FLAT_GOLD.findall(description):
        record("flat_gold", float(amount))

    for melee_percent, ranged_percent in _MELEE_RANGED_SPLIT.findall(description):
        record(
            "melee_ranged_ratios",
            [float(melee_percent) / 100.0, float(ranged_percent) / 100.0],
        )


def _parse_prose_rules(description: str, effects: dict[str, Any]) -> None:
    """Read the prose-form rules: buff windows, stack rules, proc delays."""
    window_match = _BUFF_WINDOW.search(description)
    if window_match:
        effects["buff_duration_seconds"] = float(window_match.group(1))

    stack_match = _STACK_RULE.search(description)
    if stack_match:
        effects["stacks_required"] = int(stack_match.group(1))
        effects["stack_window_seconds"] = float(stack_match.group(2))

    duration_match = _STACK_DURATION.search(description)
    if duration_match:
        effects["stack_duration_seconds"] = float(duration_match.group(1))

    max_stacks_match = _MAX_STACKS.search(description)
    if max_stacks_match:
        effects["max_stacks"] = int(max_stacks_match.group(1))

    amp_match = _DAMAGE_AMP.search(description)
    if amp_match:
        effects["damage_amp_ratio"] = float(amp_match.group(1)) / 100.0

    delay_match = _PROC_DELAY.search(description)
    if delay_match:
        effects["proc_delay_seconds"] = float(delay_match.group(1))


def rune_payload(name: str, wikitext: str, icon: str = "") -> dict[str, Any]:
    """Build one ``data/runes.json`` entry from a rune's template wikitext."""
    params = parse_rune_template(wikitext)
    description = "\n".join(
        params.get(key, "") for key in ("description", "description2")
    ).strip()
    effects, warnings = parse_effects(description)
    payload: dict[str, Any] = {
        "name": name,
        "path": params.get("path", ""),
        "slot": params.get("slot", ""),
        "cooldown": parse_cooldown(params.get("cooldown")),
        "icon": icon,
        "description": description,
        "effects": effects,
    }
    if warnings:
        payload["parse_warnings"] = warnings
    return payload
