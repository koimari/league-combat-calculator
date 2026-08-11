"""Parse League Wiki ``Template:Rune data <name>`` wikitext into rune payloads.

The wiki keeps one machine-readable template per rune with named params
(``path``, ``slot``, ``cooldown``, ``description``). Inside descriptions,
numbers appear in a small set of template forms:

- ``{{pp|60 + 10 * x|1 to 20 by 1}}`` — a leveling formula over champion level
- ``{{pp|0 to 100 by 5|0 to 750|type=distance ...}}`` — a distance-keyed table
  (values enumerated by the first param, keyed over the second's span)
- ``{{as|(+ 10% '''bonus''' AD)}}`` / ``{{as|(+ 5% AP)}}`` — scaling ratios
- ``{{fd|0.25}}-second delay`` / ``lands after {{rutngt|0.8}}`` — proc delays
- ``{{as|7% '''bonus''' true damage}}`` — a post-mitigation true-damage ratio
- ``{{g|10}}`` — flat gold grants
- ``{{rd|50%|35%}}`` — a melee/ranged value split (melee first, per Template:Rd)
- prose stack rules — "Applying 3 stacks to a target within a 3 second period"
- prose buff windows — "grants ... for 3 seconds, causing"
- prose refreshing stacks — "apply a stack for 4 seconds ... stacking up to 3 times"
- prose damage amps — "grant you 8% increased damage against champions"
- Summon Aery's sourced damage/shield flight, shield duration, and linger
  timings
- Dark Harvest's health threshold, base damage, Soul scaling, and takedown
  cooldown reset
- ``for N`` level spans used by current rune formulas
- Guardian's trigger window, shield duration, and bonus-health ratio
- Aftershock's implicit level-scaled endpoint tables and resistance fields
- Grasp's timed combat stacks and nested melee/ranged health ratios
- Hail of Blades' temporary attack-speed window and true-damage rider
- Lethal Tempo's stacked attack speed, bolt damage, and expiry cadence
- Glacial Augment's ray geometry, slow formula, and ally damage reduction
- Stormraider's Surge's damage threshold, movement speed, and slow resistance
- Fleet Footwork's level heal, scaling, movement speed, and minion modifier
- Conqueror's adaptive-force tables, stack timing, and max-stack healing

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
    r"\{\{as\|\(\+\s*([\d.]+)%\s*(?:('''bonus'''|bonus)\s*)?"
    r"(?:of your\s*)?(AD|AP)\)"
)
_BONUS_HEALTH_RATIO = re.compile(
    r"\{\{as\|\(\+\s*([\d.]+)%\s*(?:of your\s*)?" r"(?:'''bonus'''|bonus)\s+health\)"
)
_BONUS_RESISTANCE_RATIO = re.compile(
    r"\{\{as\|\(\+\s*([\d.]+)%\s*(?:'''bonus'''|bonus)\s+" r"(armor|magic resistance)\)"
)
_FLAT_RESISTANCE = re.compile(r"\{\{as\|([\d.]+)\|(armor|mr)\}\}")
_STACK_RULE = re.compile(r"Applying (\d+) stacks? to a target within a ([\d.]+) second")
_STACK_DURATION = re.compile(r"apply a \{\{tip\|stacks?\}\} for ([\d.]+) seconds")
_MAX_STACKS = re.compile(r"stacking (?:the effect )?up to (\d+) times")
_DAMAGE_AMP = re.compile(r"([\d.]+)% increased damage against champions")
_BONUS_TRUE_DAMAGE = re.compile(r"\{\{as\|([\d.]+)%\s*'''bonus'''\s*true damage\}\}")
_FLAT_GOLD = re.compile(r"\{\{g\|([\d.]+)\}\}")
_MELEE_RANGED_SPLIT = re.compile(r"\{\{rd\|([\d.]+)%\|([\d.]+)%\}\}")
_GRASP_DAMAGE_RATIO = re.compile(
    r"bonus''' magic damage\}\} equal to \{\{as\|"
    r"\{\{rd\|\{\{fd\|([\d.]+)\}\}%\|\{\{fd\|([\d.]+)\}\}%\}\}"
    r".*?maximum.*?health",
    re.DOTALL,
)
_GRASP_HEAL_RATIO = re.compile(
    r"heal\}\} you for \{\{as\|\(\+\s*"
    r"\{\{rd\|\{\{fd\|([\d.]+)\}\}%\|\{\{fd\|([\d.]+)\}\}%\}\}"
    r".*?maximum.*?health",
    re.DOTALL,
)
_GRASP_PERMANENT_HEALTH = re.compile(
    r"permanently grant you \{\{as\|\{\{rd\|([\d.]+)\|([\d.]+)\}\}"
    r"\s+'''bonus''' health"
)
_GRASP_COMBAT_STACKS = re.compile(
    r"generates? 1 .*? every (?:([\d.]+) )?seconds? for the next ([\d.]+) seconds?"
)
_GRASP_READY_WINDOW = re.compile(
    r"your next .*?basic attack.*?within ([\d.]+) seconds against an enemy .*?champion",
    re.DOTALL,
)
_HAIL_ATTACK_SPEED = re.compile(
    r"gain \{\{as\|\{\{rd\|([\d.]+)%\|([\d.]+)%\}\}" r".*?bonus''' attack speed",
    re.DOTALL,
)
_HAIL_INITIAL_STACKS = re.compile(
    r"gain (\d+) stacks? of the effect for ([\d.]+) seconds"
)
_HAIL_RESET_STACK_LIMIT = re.compile(
    r"generate an additional stack .*? up to (\d+) times",
    re.DOTALL,
)
_LETHAL_TEMPO_ATTACK_SPEED = re.compile(
    r"gain \{\{as\|\{\{rd\|([\d.]+)%\|\{\{ap\|([\d.]+)\*([\d.]+)\}\}%\}\}"
    r".*?bonus''' attack speed",
    re.DOTALL | re.IGNORECASE,
)
_LETHAL_TEMPO_BOLT_DAMAGE = re.compile(
    r"deals them \{\{rd\|([^|]+)\|([^|]+)\|pp=true\}\}",
    re.DOTALL,
)
_LETHAL_TEMPO_DAMAGE_AMP = re.compile(
    r"\{\{rd\|([\d.]+)%\|\{\{fd\|([\d.]+)" r"(?:\{\{recurring\|(\d)\}\})?%\}\}\}\} per",
    re.DOTALL,
)
_LETHAL_TEMPO_STACK_DURATION = re.compile(
    r"grant a .*?stack.*?for ([\d.]+) seconds", re.DOTALL | re.IGNORECASE
)
_LETHAL_TEMPO_EXPIRY_STEP = re.compile(
    r"expire one by one every \{\{fd\|([\d.]+)\}\} seconds",
    re.IGNORECASE,
)
_GLACIAL_RAY_COUNT = re.compile(
    r"will cause (\d+) glacial rays to emanate",
    re.IGNORECASE,
)
_GLACIAL_ZONE = re.compile(
    r"creating icy zones with a ([\d.]+) unit radius that last for "
    r"([\d.]+) \(\+ ([\d.]+)% of the",
    re.IGNORECASE,
)
_GLACIAL_ZONE_WIDTH = re.compile(
    r"icy zones, which have a width of ([\d.]+) units",
    re.IGNORECASE,
)
_GLACIAL_SLOW_BASE = re.compile(r"slowed\}\} by ([\d.]+)%", re.IGNORECASE)
_GLACIAL_SLOW_BONUS_AD = re.compile(
    r"\(\+ ([\d.]+)% per 100 (?:'''bonus'''|bonus) AD\)",
    re.IGNORECASE,
)
_GLACIAL_SLOW_AP = re.compile(
    r"\(\+ ([\d.]+)% per 100 AP\)",
    re.IGNORECASE,
)
_GLACIAL_SLOW_HEAL_SHIELD = re.compile(
    r"\(\+ ([\d.]+)% per 10% heal and shield power\)",
    re.IGNORECASE,
)
_GLACIAL_DAMAGE_REDUCTION = re.compile(
    r"damage reduced by ([\d.]+)% against your allies",
    re.IGNORECASE,
)
_STORMRAIDER_TRIGGER = re.compile(
    r"equal to \{\{as\|([\d.]+)% of their .*?maximum.*?health\}\}"
    r" within ([\d.]+) seconds",
    re.IGNORECASE,
)
_STORMRAIDER_DURATION = re.compile(
    r"grants you .*?for ([\d.]+) seconds",
    re.IGNORECASE | re.DOTALL,
)
_STORMRAIDER_MOVE_SPEED = re.compile(
    r"\{\{as\|\{\{rd\|([\d.]+)%\|([\d.]+)%\}\}" r" .*?movement speed\}\}",
    re.IGNORECASE | re.DOTALL,
)
_STORMRAIDER_SLOW_RESIST = re.compile(
    r"and ([\d.]+)% \{\{tip\|slow resist\}\}",
    re.IGNORECASE,
)
_FLEET_HEAL_BASE = re.compile(
    r"\{\{rd\|([^|]+)\|([^|]+)\|color=heal",
    re.IGNORECASE,
)
_FLEET_HEAL_SCALING = re.compile(
    r"\(\+\s*\{\{rd\|([\d.]+)%\|([\d.]+)%\}\}" r"\s*(?:'''bonus'''\s*)?(AD|AP)\)",
    re.IGNORECASE,
)
_FLEET_MOVE_SPEED = re.compile(
    r"\{\{as\|\{\{rd\|([\d.]+)%\|([\d.]+)%\}\}\|ms\}\}",
    re.IGNORECASE,
)
_FLEET_MOVE_DURATION = re.compile(
    r"movement speed\}\}\}\}\s+for\s+([\d.]+)\s+second",
    re.IGNORECASE,
)
_FLEET_MINION_EFFECTIVENESS = re.compile(
    r"Against .*?healing is ([\d.]+)% effective", re.IGNORECASE | re.DOTALL
)
_FLEET_CHARGE_CAP = re.compile(r"Charges'', up to ([\d.]+)", re.IGNORECASE)
_CONQUEROR_ADAPTIVE = re.compile(
    r"\{\{adaptive\|([^|{}]+)\|([^{}]+)\}\}", re.IGNORECASE
)
_CONQUEROR_HEAL_RATIO = re.compile(
    r"at which you also .*?heal\}\} for \{\{rd\|([\d.]+)%\|([\d.]+)%\}\}",
    re.IGNORECASE | re.DOTALL,
)
_CONQUEROR_STACK_DURATION = re.compile(
    r"Conqueror.*?lasting for ([\d.]+) seconds", re.IGNORECASE | re.DOTALL
)
_CONQUEROR_CAST_INSTANCE_INTERVAL = re.compile(
    r"once every (?:\{\{fd\|)?([\d.]+)(?:\}\})? seconds per "
    r"(?:\{\{tip\|)?cast instance(?:\}\})?",
    re.IGNORECASE,
)
_CONQUEROR_STACKS_PER_APPLICATION = re.compile(r"Gain (\d+) stacks? for", re.IGNORECASE)
_DEATHFIRE_RATIO = re.compile(
    r"\{\{ap\|([^|{}]+)(?:\|[^{}]+)?\}\}%\s*" r"(?:'''bonus'''\s*)?(AD|AP)",
    re.IGNORECASE,
)
_DEATHFIRE_TICK = re.compile(
    r"every (?:\{\{fd\|)?([\d.]+)(?:\}\})? seconds", re.IGNORECASE
)
_DEATHFIRE_DURATION = re.compile(
    r"\{\{tip\|([^|{}]+)(?:\|[^{}]+)?\}\}:\s*([\d.]+) seconds?",
    re.IGNORECASE,
)
_DEATHFIRE_AMP_DELAY = re.compile(
    r"burn has lingered on a target for ([\d.]+) seconds", re.IGNORECASE
)
_DEATHFIRE_AMP_RATIO = re.compile(r"increased\{\{ft\|by ([\d.]+)%", re.IGNORECASE)
_BUFF_WINDOW = re.compile(r"for ([\d.]+) seconds, causing")
_PROC_DELAY = re.compile(r"\{\{fd\|([\d.]+)\}\}-second delay")
_LANDING_DELAY = re.compile(r"lands after \{\{rutngt\|([\d.]+)\}\}")
_TT_TEMPLATE = re.compile(r"\{\{tt\|([^|}]+)")
_RANGE_SPEC = re.compile(r"^([\d.]+)\s+to\s+([\d.]+)(?:\s+by\s+([\d.]+))?$")
_FORMULA_FOR_LEVELS = re.compile(r"^(.*?)\s+for\s+(\d+)\s*$", re.DOTALL)
_AERY_DAMAGE_FLIGHT = re.compile(
    r"signal ''Aery'' to pounce at them over \{\{fd\|([\d.]+)\}\} seconds"
)
_AERY_SHIELD_FLIGHT = re.compile(
    r"signals? ''Aery'' to leap to their side over \{\{fd\|([\d.]+)\}\} seconds"
)
_AERY_SHIELD_DURATION = re.compile(
    r"shield\|shielding\}\} them for .*? for ([\d.]+) seconds", re.DOTALL
)
_AERY_LINGER = re.compile(r"lingers on the target for \{\{tt\|([\d.]+) seconds")
_DARK_HARVEST_DAMAGE = re.compile(
    r"deals\s+([\d.]+)\s+\{\{as\|\(\+\s*([\d.]+)\s+per\s+Soul\)\}\}"
)
_DARK_HARVEST_THRESHOLD = re.compile(
    r"below\s+\{\{as\|([\d.]+)%\s+of their .*?maximum.*?health\}\}",
    re.DOTALL,
)
_DARK_HARVEST_TAKEDOWN_RESET = re.compile(r"resetting to ([\d.]+) second")
_GUARDIAN_TRIGGER_WINDOW = re.compile(
    r"would take .*?damage within \{\{fd\|([\d.]+)\}\} seconds",
    re.DOTALL,
)
_GUARDIAN_SHIELD_DURATION = re.compile(
    r"gain a \{\{tip\|shield\}\}.*?for ([\d.]+) seconds", re.DOTALL
)
_AFTERSHOCK_DURATION = re.compile(
    r"grants? .*?for \{\{fd\|([\d.]+)\}\} seconds", re.DOTALL
)
_AFTERSHOCK_RADIUS = re.compile(r"\}\}\s*([\d.]+)\s+radius")

# The current Aftershock template uses ``{{pp|80 to 150}}`` and
# ``{{pp|25 to 120}}``. The page defines both pairs as level-scaled values,
# while the template omits the explicit span used by newer rune formulas.
AFTERSHOCK_IMPLICIT_LEVEL_RANGE = "1 to 20 by 1"

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

    Three sourced forms exist: a semicolon list of literal values, an
    ``N to M by S`` enumeration of the values themselves (the second
    param then carries the keys, e.g. a distance span), and an
    arithmetic formula in ``x`` evaluated over an ``N to M by S`` range.
    """
    formula = formula.strip()
    if ";" in formula and "x" not in formula:
        return [float(part) for part in formula.split(";") if part.strip()]
    shorthand = _RANGE_SPEC.match(formula)
    if shorthand and shorthand.group(3):
        # Only an explicit "by <step>" marks a value enumeration; a bare
        # "A to B" scales over an implicit level span the template does
        # not state, and expanding it would fabricate wrong values.
        return _enumerate_range(shorthand)
    if shorthand and range_spec:
        range_match = _RANGE_SPEC.match(range_spec.strip())
        if range_match is None:
            raise ValueError(f"Unsupported pp range spec {range_spec!r}")
        keys = _enumerate_range(range_match)
        if len(keys) < 2:
            raise ValueError(f"pp range {range_spec!r} has fewer than two steps")
        start = float(shorthand.group(1))
        stop = float(shorthand.group(2))
        # The Wiki's level-endpoint rune values use the standard level-1 to
        # level-18 span, while the cache keeps two extra level rows for the
        # project's level-20 scenarios. Preserve the source denominator when
        # those rows are present.
        denominator = 17.0 if len(keys) == 20 else float(len(keys) - 1)
        return [
            start + (stop - start) * index / denominator for index in range(len(keys))
        ]
    if not range_spec:
        formula_for_levels = _FORMULA_FOR_LEVELS.fullmatch(formula)
        if formula_for_levels:
            formula = formula_for_levels.group(1).strip()
            levels = int(formula_for_levels.group(2))
            if levels <= 0:
                raise ValueError(f"pp formula {formula!r} has no positive level span")
            range_spec = f"1 to {levels} by 1"
        else:
            raise ValueError(f"pp formula {formula!r} has no level range")
    range_match = _RANGE_SPEC.match(range_spec.strip())
    if not range_match:
        raise ValueError(f"Unsupported pp range spec {range_spec!r}")
    expression = _safe_pp_expression(formula)
    return [
        _evaluate_pp_node(expression.body, x) for x in _enumerate_range(range_match)
    ]


def _enumerate_range(match: re.Match) -> list[float]:
    """Enumerate a matched ``start to stop by step`` spec into its values.

    Descending specs count down (cooldowns shrink with level) — a spec
    must never enumerate to an empty list.
    """
    start, stop, step = (
        float(match.group(1)),
        float(match.group(2)),
        float(match.group(3) or 1),
    )
    if step <= 0:
        raise ValueError(f"pp range {match.group(0)!r} has a non-positive step")
    if start > stop:
        step = -step
    values = []
    value = start
    while (value <= stop + 1e-9) if step > 0 else (value >= stop - 1e-9):
        values.append(value)
        value += step
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


def parse_cooldown(value: str | None) -> float | list[float] | None:
    """Read a cooldown param into a number or a per-level list.

    Three sourced forms: a plain number, a ``{{tt|N|note}}`` wrapper,
    and a ``{{pp}}`` leveling formula (a per-level cooldown list).
    """
    if not value:
        return None
    pp_match = _PP_TEMPLATE.search(value)
    if pp_match:
        parts = [part for part in pp_match.group(1).split("|") if "=" not in part]
        if not parts:
            return None
        try:
            return evaluate_pp(parts[0], parts[1] if len(parts) > 1 else None)
        except ValueError:
            return None
    tt_match = _TT_TEMPLATE.search(value)
    text = tt_match.group(1) if tt_match else value
    try:
        return float(text.strip())
    except ValueError:
        return None


def _recurring_decimal(value: str, recurring_digit: str | None) -> float:
    """Resolve a decimal whose final displayed digit repeats forever."""
    if not recurring_digit:
        return float(value)
    text = value.strip()
    whole, separator, fraction = text.partition(".")
    if not separator or not fraction:
        raise ValueError(f"invalid recurring decimal {value!r}")
    nonrecurring = fraction[:-1]
    base = float(f"{whole}.{nonrecurring}") if nonrecurring else float(whole)
    place = 10 ** len(nonrecurring)
    return base + float(recurring_digit) / (9.0 * place)


def parse_effects(
    description: str, *, implicit_level_range: str | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Extract the numeric effect values a description carries.

    Returns the effects dict plus parse warnings. Keys are only present
    when their source text parsed — consumers fail closed on absence.
    """
    effects: dict[str, Any] = {}
    warnings: list[str] = []
    _parse_leveling(description, effects, warnings, implicit_level_range)
    _parse_scalar_templates(description, effects, warnings)
    _parse_prose_rules(description, effects)
    return effects, warnings


def _parse_leveling(
    description: str,
    effects: dict[str, Any],
    warnings: list[str],
    implicit_level_range: str | None = None,
) -> None:
    """Evaluate every ``{{pp}}`` template into a per-level value list.

    A template whose ``type=`` names a distance is keyed by travel
    distance, not champion level — it is stored as ``distance_scaling``
    (values plus the distance span) instead of joining ``leveling``.
    """
    leveling = []
    for pp_body in _PP_TEMPLATE.findall(description):
        parts = pp_body.split("|")
        named = dict(part.split("=", 1) for part in parts if "=" in part)
        positional = [part for part in parts if "=" not in part]
        formula = positional[0] if positional else ""
        range_spec = positional[1] if len(positional) > 1 else None
        try:
            values = evaluate_pp(formula, range_spec)
        except ValueError as exc:
            if (
                implicit_level_range is not None
                and range_spec is None
                and _RANGE_SPEC.fullmatch(formula.strip())
            ):
                try:
                    values = evaluate_pp(formula, implicit_level_range)
                except ValueError:
                    warnings.append(str(exc))
                    continue
            else:
                warnings.append(str(exc))
                continue
        if named.get("type", "").startswith("distance"):
            span = _RANGE_SPEC.match((range_spec or "").strip())
            if not span:
                warnings.append(f"distance pp has no distance span: {pp_body!r}")
                continue
            scaling = {
                "values": values,
                "distance_range": [float(span.group(1)), float(span.group(2))],
            }
            # Like duplicate ratios: silently keeping the last table would
            # be a plausible-looking wrong number. Record the ambiguity.
            if "distance_scaling" in effects and effects["distance_scaling"] != scaling:
                warnings.append(f"distance_scaling matched more than once: {pp_body!r}")
            effects["distance_scaling"] = scaling
        else:
            leveling.append(values)
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

    for percent in _BONUS_HEALTH_RATIO.findall(description):
        record("bonus_health_ratio", float(percent) / 100.0)

    for percent, resistance in _BONUS_RESISTANCE_RATIO.findall(description):
        key = (
            "bonus_magic_resistance_ratio"
            if resistance == "magic resistance"
            else "bonus_armor_ratio"
        )
        record(key, float(percent) / 100.0)

    for amount, resistance in _FLAT_RESISTANCE.findall(description):
        key = "flat_magic_resistance" if resistance == "mr" else "flat_armor"
        record(key, float(amount))

    for percent in _BONUS_TRUE_DAMAGE.findall(description):
        record("bonus_true_damage_ratio", float(percent) / 100.0)

    for amount in _FLAT_GOLD.findall(description):
        record("flat_gold", float(amount))

    for melee_percent, ranged_percent in _MELEE_RANGED_SPLIT.findall(description):
        record(
            "melee_ranged_ratios",
            [float(melee_percent) / 100.0, float(ranged_percent) / 100.0],
        )

    grasp_damage = _GRASP_DAMAGE_RATIO.search(description)
    if grasp_damage:
        record(
            "grasp_damage_melee_ranged_ratios",
            [float(value) / 100.0 for value in grasp_damage.groups()],
        )

    grasp_heal = _GRASP_HEAL_RATIO.search(description)
    if grasp_heal:
        record(
            "grasp_heal_melee_ranged_ratios",
            [float(value) / 100.0 for value in grasp_heal.groups()],
        )

    grasp_health = _GRASP_PERMANENT_HEALTH.search(description)
    if grasp_health:
        record(
            "grasp_bonus_health_melee_ranged",
            [float(value) for value in grasp_health.groups()],
        )

    hail_attack_speed = _HAIL_ATTACK_SPEED.search(description)
    if hail_attack_speed:
        record(
            "hail_bonus_attack_speed_melee_ranged",
            [float(value) for value in hail_attack_speed.groups()],
        )

    lethal_attack_speed = _LETHAL_TEMPO_ATTACK_SPEED.search(description)
    if lethal_attack_speed:
        melee, ranged_base, ranged_multiplier = lethal_attack_speed.groups()
        record(
            "lethal_tempo_attack_speed_percent_melee_ranged",
            [float(melee), float(ranged_base) * float(ranged_multiplier)],
        )

    lethal_damage = _LETHAL_TEMPO_BOLT_DAMAGE.search(description)
    if lethal_damage:
        try:
            record(
                "lethal_tempo_bolt_damage_melee_by_level",
                evaluate_pp(lethal_damage.group(1), None),
            )
            record(
                "lethal_tempo_bolt_damage_ranged_by_level",
                evaluate_pp(lethal_damage.group(2), None),
            )
        except ValueError as exc:
            warnings.append(f"Lethal Tempo bolt damage: {exc}")

    lethal_damage_amp = _LETHAL_TEMPO_DAMAGE_AMP.search(description)
    if lethal_damage_amp:
        melee, ranged_base, recurring_digit = lethal_damage_amp.groups()
        ranged = _recurring_decimal(ranged_base, recurring_digit)
        record(
            "lethal_tempo_bolt_damage_increase_ratio_melee_ranged",
            [float(melee) / 100.0, ranged / 100.0],
        )

    glacial_fields = (
        (_GLACIAL_RAY_COUNT, "glacial_ray_count", lambda value: int(value)),
        (_GLACIAL_ZONE_WIDTH, "glacial_zone_width_units", float),
        (
            _GLACIAL_SLOW_BASE,
            "glacial_slow_base_ratio",
            lambda value: float(value) / 100.0,
        ),
        (
            _GLACIAL_SLOW_BONUS_AD,
            "glacial_slow_bonus_ad_ratio_per_100",
            lambda value: float(value) / 100.0,
        ),
        (
            _GLACIAL_SLOW_AP,
            "glacial_slow_ap_ratio_per_100",
            lambda value: float(value) / 100.0,
        ),
        (
            _GLACIAL_SLOW_HEAL_SHIELD,
            "glacial_slow_heal_shield_ratio_per_10",
            lambda value: float(value) / 100.0,
        ),
        (
            _GLACIAL_DAMAGE_REDUCTION,
            "glacial_damage_reduction_ratio",
            lambda value: float(value) / 100.0,
        ),
    )
    for pattern, key, converter in glacial_fields:
        match = pattern.search(description)
        if match:
            record(key, converter(match.group(1)))

    glacial_zone = _GLACIAL_ZONE.search(description)
    if glacial_zone:
        record("glacial_zone_radius_units", float(glacial_zone.group(1)))
        record("glacial_zone_base_duration_seconds", float(glacial_zone.group(2)))
        record(
            "glacial_zone_duration_cc_ratio",
            float(glacial_zone.group(3)) / 100.0,
        )

    stormraider_trigger = _STORMRAIDER_TRIGGER.search(description)
    if stormraider_trigger:
        record(
            "stormraider_damage_threshold_ratio",
            float(stormraider_trigger.group(1)) / 100.0,
        )
        record(
            "stormraider_damage_window_seconds",
            float(stormraider_trigger.group(2)),
        )

    stormraider_duration = _STORMRAIDER_DURATION.search(description)
    if stormraider_duration:
        record("stormraider_duration_seconds", float(stormraider_duration.group(1)))

    stormraider_move_speed = _STORMRAIDER_MOVE_SPEED.search(description)
    if stormraider_move_speed:
        record(
            "stormraider_bonus_move_speed_melee_ranged",
            [float(value) for value in stormraider_move_speed.groups()],
        )

    stormraider_slow_resist = _STORMRAIDER_SLOW_RESIST.search(description)
    if stormraider_slow_resist:
        record(
            "stormraider_slow_resist_ratio",
            float(stormraider_slow_resist.group(1)) / 100.0,
        )

    fleet_heal = _FLEET_HEAL_BASE.search(description)
    if fleet_heal:
        try:
            record(
                "fleet_heal_melee_by_level",
                evaluate_pp(fleet_heal.group(1).strip(), None),
            )
            record(
                "fleet_heal_ranged_by_level",
                evaluate_pp(fleet_heal.group(2).strip(), None),
            )
        except ValueError as exc:
            warnings.append(f"Fleet Footwork healing: {exc}")

    fleet_scalings = _FLEET_HEAL_SCALING.findall(description)
    if fleet_scalings:
        for percent_melee, percent_ranged, stat in fleet_scalings:
            key = (
                "fleet_bonus_ad_ratio_melee_ranged"
                if stat.upper() == "AD"
                else "fleet_ap_ratio_melee_ranged"
            )
            record(
                key,
                [float(percent_melee) / 100.0, float(percent_ranged) / 100.0],
            )

    fleet_move_speed = _FLEET_MOVE_SPEED.search(description)
    if fleet_move_speed:
        record(
            "fleet_bonus_move_speed_melee_ranged",
            [float(value) for value in fleet_move_speed.groups()],
        )

    fleet_move_duration = _FLEET_MOVE_DURATION.search(description)
    if fleet_move_duration:
        record(
            "fleet_move_speed_duration_seconds",
            float(fleet_move_duration.group(1)),
        )

    fleet_minion = _FLEET_MINION_EFFECTIVENESS.search(description)
    if fleet_minion:
        record(
            "fleet_minion_heal_effectiveness",
            float(fleet_minion.group(1)) / 100.0,
        )

    fleet_charge_cap = _FLEET_CHARGE_CAP.search(description)
    if fleet_charge_cap:
        record("fleet_charge_cap", float(fleet_charge_cap.group(1)))

    conqueror_adaptive = _CONQUEROR_ADAPTIVE.findall(description)
    if conqueror_adaptive:
        for index, (formula, level_span) in enumerate(conqueror_adaptive[:2]):
            try:
                level_count = int(float(level_span.strip()))
                values = evaluate_pp(formula.strip(), f"1 to {level_count} by 1")
            except ValueError as exc:
                warnings.append(f"Conqueror adaptive force: {exc}")
                continue
            key = (
                "conqueror_adaptive_force_by_level"
                if index == 0
                else "conqueror_adaptive_force_max_by_level"
            )
            record(key, values)

    conqueror_heal = _CONQUEROR_HEAL_RATIO.search(description)
    if conqueror_heal:
        record(
            "conqueror_heal_melee_ranged_ratios",
            [float(value) / 100.0 for value in conqueror_heal.groups()],
        )

    deathfire_ratios: dict[str, list[float]] = {"AD": [], "AP": []}
    for formula, stat in _DEATHFIRE_RATIO.findall(description):
        try:
            value = evaluate_pp(f"{formula.strip()} for 1", None)[0] / 100.0
        except ValueError as exc:
            warnings.append(f"Deathfire Touch ratio: {exc}")
            continue
        deathfire_ratios[stat.upper()].append(value)
    if deathfire_ratios["AD"]:
        record("deathfire_bonus_ad_ratios_by_state", deathfire_ratios["AD"][:2])
    if deathfire_ratios["AP"]:
        record("deathfire_ap_ratios_by_state", deathfire_ratios["AP"][:2])


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

    conqueror_duration = _CONQUEROR_STACK_DURATION.search(description)
    if conqueror_duration:
        effects["conqueror_stack_duration_seconds"] = float(conqueror_duration.group(1))

    conqueror_interval = _CONQUEROR_CAST_INSTANCE_INTERVAL.search(description)
    if conqueror_interval:
        effects["conqueror_cast_instance_interval_seconds"] = float(
            conqueror_interval.group(1)
        )

    conqueror_stacks = _CONQUEROR_STACKS_PER_APPLICATION.search(description)
    if conqueror_stacks:
        effects["conqueror_stacks_per_application"] = int(conqueror_stacks.group(1))

    deathfire_tick = _DEATHFIRE_TICK.search(description)
    if deathfire_tick:
        effects["deathfire_tick_interval_seconds"] = float(deathfire_tick.group(1))

    deathfire_delay = _DEATHFIRE_AMP_DELAY.search(description)
    if deathfire_delay:
        effects["deathfire_amp_delay_seconds"] = float(deathfire_delay.group(1))

    deathfire_amp = _DEATHFIRE_AMP_RATIO.search(description)
    if deathfire_amp:
        effects["deathfire_amp_ratio"] = float(deathfire_amp.group(1)) / 100.0

    deathfire_durations = {
        category.strip().lower().replace(" ", "_"): float(duration)
        for category, duration in _DEATHFIRE_DURATION.findall(description)
    }
    if deathfire_durations:
        effects["deathfire_duration_seconds"] = deathfire_durations

    max_stacks_match = _MAX_STACKS.search(description)
    if max_stacks_match:
        effects["max_stacks"] = int(max_stacks_match.group(1))

    grasp_stacks = _GRASP_COMBAT_STACKS.search(description)
    if grasp_stacks:
        effects["combat_stack_cadence_seconds"] = float(grasp_stacks.group(1) or 1.0)
        effects["combat_stack_generation_seconds"] = float(grasp_stacks.group(2))

    grasp_window = _GRASP_READY_WINDOW.search(description)
    if grasp_window:
        effects["ready_window_seconds"] = float(grasp_window.group(1))

    hail_stacks = _HAIL_INITIAL_STACKS.search(description)
    if hail_stacks:
        effects["hail_initial_stacks"] = int(hail_stacks.group(1))
        effects["hail_stack_duration_seconds"] = float(hail_stacks.group(2))

    hail_reset_limit = _HAIL_RESET_STACK_LIMIT.search(description)
    if hail_reset_limit:
        effects["hail_reset_stack_limit"] = int(hail_reset_limit.group(1))

    lethal_stack_duration = _LETHAL_TEMPO_STACK_DURATION.search(description)
    if lethal_stack_duration:
        effects["lethal_tempo_stack_duration_seconds"] = float(
            lethal_stack_duration.group(1)
        )

    lethal_expiry_step = _LETHAL_TEMPO_EXPIRY_STEP.search(description)
    if lethal_expiry_step:
        effects["lethal_tempo_expiry_step_seconds"] = float(lethal_expiry_step.group(1))

    amp_match = _DAMAGE_AMP.search(description)
    if amp_match:
        effects["damage_amp_ratio"] = float(amp_match.group(1)) / 100.0

    delay_match = _PROC_DELAY.search(description) or _LANDING_DELAY.search(description)
    if delay_match:
        effects["proc_delay_seconds"] = float(delay_match.group(1))

    dark_harvest_damage = _DARK_HARVEST_DAMAGE.search(description)
    if dark_harvest_damage:
        effects["base_damage"] = float(dark_harvest_damage.group(1))
        effects["soul_damage"] = float(dark_harvest_damage.group(2))

    dark_harvest_threshold = _DARK_HARVEST_THRESHOLD.search(description)
    if dark_harvest_threshold:
        effects["health_threshold_ratio"] = (
            float(dark_harvest_threshold.group(1)) / 100.0
        )

    dark_harvest_reset = _DARK_HARVEST_TAKEDOWN_RESET.search(description)
    if dark_harvest_reset:
        effects["takedown_reset_seconds"] = float(dark_harvest_reset.group(1))

    guardian_window = _GUARDIAN_TRIGGER_WINDOW.search(description)
    if guardian_window:
        effects["trigger_window_seconds"] = float(guardian_window.group(1))

    guardian_duration = _GUARDIAN_SHIELD_DURATION.search(description)
    if guardian_duration:
        effects["shield_duration_seconds"] = float(guardian_duration.group(1))

    aftershock_duration = _AFTERSHOCK_DURATION.search(description)
    if aftershock_duration:
        effects["resistance_duration_seconds"] = float(aftershock_duration.group(1))

    aftershock_radius = _AFTERSHOCK_RADIUS.search(description)
    if aftershock_radius:
        effects["shockwave_radius"] = float(aftershock_radius.group(1))

    # Summon Aery carries two separate flight times and a target linger in
    # prose.  Keep these source-specific fields separate so a consumer never
    # applies the damage landing time to the ally shield.
    aery_fields = (
        (_AERY_DAMAGE_FLIGHT, "damage_flight_seconds"),
        (_AERY_SHIELD_FLIGHT, "shield_flight_seconds"),
        (_AERY_SHIELD_DURATION, "shield_duration_seconds"),
        (_AERY_LINGER, "linger_seconds"),
    )
    for pattern, key in aery_fields:
        match = pattern.search(description)
        if match:
            effects[key] = float(match.group(1))


def rune_payload(name: str, wikitext: str, icon: str = "") -> dict[str, Any]:
    """Build one ``data/runes.json`` entry from a rune's template wikitext."""
    params = parse_rune_template(wikitext)
    description_keys = ["description"]
    description_keys.extend(
        sorted(
            (key for key in params if re.fullmatch(r"description\d+", key)),
            key=lambda key: int(key.removeprefix("description")),
        )
    )
    description = "\n".join(params.get(key, "") for key in description_keys).strip()
    effects, warnings = parse_effects(
        description,
        implicit_level_range=(
            AFTERSHOCK_IMPLICIT_LEVEL_RANGE if name == "Aftershock" else None
        ),
    )
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
