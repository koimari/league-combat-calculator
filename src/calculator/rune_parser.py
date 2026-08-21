"""Parse League Wiki ``Template:Rune data <name>`` wikitext into rune payloads.

The wiki keeps one machine-readable template per rune with named params
(``path``, ``slot``, ``cooldown``, ``description``). Inside descriptions,
numbers appear in a small set of template forms:

- ``{{pp|60 + 10 * x|1 to 20 by 1}}`` — a leveling formula over champion level
- ``{{pp|4 + (20-4)/17*(x-1) for 20}}`` — the same, range given as a suffix
- ``{{pp|80 to 150}}`` — a stepless span, linear-filled over the wiki's
  default 18 columns (Module:Ability progression, ``defaultSize = 18``)
- ``{{pp|0 to 100 by 5|0 to 750|type=distance ...}}`` — a distance-keyed table
  (values enumerated by the first param, keyed over the second's span)
- ``{{pp|4*x*(x-1);∞|0 to 70 for 8;∞|type=minutes}}`` — a table whose columns
  are keyed by something other than champion level: ``x`` is the column's
  ordinal, the second param's span is recorded as ``<type>_range``, and the
  ``;∞`` final column is the wiki's "and beyond" mark, not a value
- ``{{rd|<melee formula>|<ranged formula>|pp=true}}`` — a melee/ranged pair of
  level tables (``color=heal`` marks a heal table, not damage)
- ``{{as|(+ 10% '''bonus''' AD)}}`` / ``{{as|(+ 5% AP)}}`` — scaling ratios
- ``{{adaptive|1.8 + (4-1.8)/17*(x-1)|20}}`` — per-level adaptive force
- ``{{fd|0.25}}-second delay`` / ``lands after {{rutngt|0.8}}`` /
  ``pounce ... over {{fd|0.45}} seconds, dealing`` — proc delays
- ``{{as|7% '''bonus''' true damage}}`` — a post-mitigation true-damage ratio
- ``{{g|10}}`` — flat gold grants
- ``{{rd|50%|35%}}`` — a melee/ranged scalar split (melee first, per
  Template:Rd), recorded under a key naming its quantity (attack speed,
  movement speed, gold conversion, heal share, max-health damage/heal)
- ``deals 30 {{as|(+ 11 per Soul)}}`` — flat base plus per-soul damage
- ``(+ {{as|1.5%|attack speed}} per ''Legend'' {{tip|stack}})`` — a per-stack
  step, recorded as the step alone (the stack count is a compiler's option)
- display wrappers ``{{fd|3.5}}`` / ``{{ap|6*0.8}}`` / ``{{sti|...}}`` /
  ``{{#vardefineecho:x|3}}`` and ``0.6{{recurring|6}}`` repeating decimals are
  inlined first so the value patterns can see through them
- prose stack rules — "Applying 3 stacks to a target within a 3 second period"
- prose buff windows — "grants ... for 3 seconds, causing"
- prose refreshing stacks — "apply a stack for 4 seconds ... stacking up to 3 times"
- prose damage amps — "grant you 8% increased damage against champions"
- ``every {{fd|0.5}} seconds`` — a damage-over-time tick interval
- ``8% increased damage to champions below {{as|40% '''maximum''' health}}`` —
  a conditional damage amplifier and the health gate it reads; a second such
  sentence is the same amplifier's escalated end (Last Stand's 11% at 30%)
- ``Your ultimate has 12% increased damage (reduced to 8% for ...)`` — an amp
  that reaches the ultimate alone, with its area-of-effect reduction
- ``while above {{as|70% of your '''maximum''' health}}`` — a self-health gate
- ``* Level 5: + 5 [[ability haste]].`` — a stat a rune grants only on
  reaching one champion level, recorded with the level that gates it
- ``After reaching 15 stacks`` — the stack count a rune names as its threshold
- ``within 4 seconds of using a {{tip|dash}}`` — how long a movement event
  leaves a rune armed
- flat stat grants: ``{{as|10% '''bonus''' attack speed}}``,
  ``{{as|65 '''bonus''' health}}``, ``8 ability haste``,
  ``{{as|2.5% '''bonus''' movement speed}}``
- ratios reading a quantity other than AD or AP:
  ``{{as|(+ 2.5% '''bonus''' health)}}``, ``{{as|(+ 15% shield amount)}}``
- ``Gain 6 (+ 5 per ''Bounty Hunter'' [[stack]]) [[ultimate haste]], up to 31
  at 5 stacks`` — a base, a step, a ceiling and the total they make
- ``For each ''Jack'' stack, gain {{as|1 ability haste}}`` plus
  ``At 5 ''Jack'' stacks, gain {{adaptive|8}}`` — a per-stack step and the
  stack gates a second grant arrives at

"up to ... at maximum stacks/range" clauses restate per-stack (or minimum)
values times a maximum — derived numbers, masked before scalar parsing so
they never conflict with their sources.  Two sentences restate a *sum*
rather than a product the same way ("up to 31 at 5 stacks", "for a total of
20 at 10 stacks"); both are read to certify the parts they restate, and the
parts are dropped with a warning when they stop adding up.

This module is pure parsing: no network, no file writes. ``data_updater``
fetches the wikitext and writes the resulting payloads to ``data/runes.json``;
``rune_effects`` consumes them with fail-closed typed accessors. A value this
parser cannot read is simply absent from the payload — never defaulted, and a
key matched with two different values is dropped, not guessed at.

``data/runes.json`` is keyed by rune name, plus the reserved keys in
:data:`RESERVED_CACHE_KEYS` for the page-level facts no single rune owns:
the stat-shard table and the adaptive-force conversion.
"""

import ast
import re
from typing import Any

_PARAM_LINE = re.compile(r"^\|(\w+)\s*=\s?(.*)$")
_PP_TEMPLATE = re.compile(r"\{\{pp\|([^{}]+)\}\}")
_RD_TEMPLATE = re.compile(r"\{\{rd\|([^{}]+)\}\}")
_AS_RATIO = re.compile(
    r"\{\{as\|\(\+\s*([\d.]+)%\s*(?:('''bonus'''|bonus)\s*)?(AD|AP)\)"
)
_AS_RATIO_PAIR = re.compile(
    r"\{\{as\|\(\+\s*\{\{rd\|([\d.]+)%\|([\d.]+)%\}\}\s*"
    r"(?:('''bonus'''|bonus)\s*)?(AD|AP)\)"
)
#: The scaling ratios that read something other than the holder's attack
#: damage or ability power.  One key per quantity and each pattern spelled
#: for exactly the sentence that states it: Aftershock's and Guardian's
#: "of your '''bonus''' health" is a different quantity from Shield Bash's
#: "'''bonus''' health" and must not read as it.
_AS_QUANTITY_RATIO_RULES: tuple[tuple[str, re.Pattern], ...] = (
    (
        "bonus_health_ratio",
        re.compile(r"\{\{as\|\(\+\s*([\d.]+)%\s*'''bonus'''\s*health\)"),
    ),
    (
        "shield_amount_ratio",
        re.compile(r"\{\{as\|\(\+\s*([\d.]+)%\s*shield amount\)"),
    ),
)
_STACK_RULE = re.compile(r"Applying (\d+) stacks? to a target within a ([\d.]+) second")
_STACK_DURATION = re.compile(r"apply a \{\{tip\|stacks?\}\} for ([\d.]+) seconds")
_MAX_STACKS = re.compile(r"stacking up to (\d+) times")
_DAMAGE_AMP = re.compile(r"([\d.]+)% increased damage against champions")
_BONUS_TRUE_DAMAGE = re.compile(r"\{\{as\|([\d.]+)%\s*'''bonus'''\s*true damage\}\}")
_FLAT_GOLD = re.compile(r"\{\{g\|([\d.]+)\}\}")
#: Flat stat grants, one key per stat.  Every rune and stat shard that grants
#: a stat outright states it in one of these forms; a grant stated any other
#: way is absent from the payload rather than guessed at.  Ability haste is
#: matched only in its bare and plainly-linked forms, so Cosmic Insight's
#: ``[[ability haste#…|summoner spell haste]]`` — a different stat that links
#: to the same page — reads as the absence it is.
_FLAT_STAT_RULES: tuple[tuple[str, re.Pattern], ...] = (
    (
        "attack_speed_percent",
        re.compile(r"\{\{as\|([\d.]+)% '''bonus''' attack speed\}\}"),
    ),
    (
        "move_speed_percent",
        re.compile(r"\{\{as\|([\d.]+)% '''bonus''' movement speed\}\}"),
    ),
    ("bonus_health", re.compile(r"\{\{as\|([\d.]+) '''bonus''' health\}\}")),
    ("ability_haste", re.compile(r"([\d.]+) (?:\[\[ability haste\]\]|ability haste)")),
)
#: Grants stated per stack of a named counter — "(+ 1.5% attack speed per
#: ''Legend'' stack)".  What is recorded is the *step*, never a total: the
#: stack count is an input the request does not carry, so a compiler declares
#: it as an option and multiplies.  The "up to N at maximum stacks" clause
#: that restates step × ceiling is masked before these ever see the text.
_PER_STACK_TAIL = r" per ''\w[^']*'' \{\{tip\|stack\}\}"
#: Legend: Alacrity states its base and its step in one sentence, so one rule
#: reads both — splitting them would let a reworded page keep one and drop
#: the other without either looking wrong.
_ATTACK_SPEED_PER_STACK = re.compile(
    r"\{\{as\|([\d.]+)%\|attack speed\}\} \(\+ \{\{as\|([\d.]+)%\|attack speed\}\}"
    + _PER_STACK_TAIL
)
_PER_STACK_RULES: tuple[tuple[str, re.Pattern], ...] = (
    (
        "basic_ability_haste_per_stack",
        re.compile(r"\{\{as\|([\d.]+) basic ability haste\}\}" + _PER_STACK_TAIL),
    ),
    (
        "life_steal_percent_per_stack",
        re.compile(r"\{\{fd\|([\d.]+)% life steal\}\}+" + _PER_STACK_TAIL),
    ),
)
#: "Gain 6 (+ 5 per ''Bounty Hunter'' [[stack]]) [[ultimate haste]], up to 31
#: at 5 stacks." — Ultimate Hunter states its base, its step, its ceiling and
#: the total they make in one sentence, so one rule reads all four and
#: :func:`_parse_per_stack_grants` certifies the total against the other
#: three.  Splitting them would let a reworded page keep one and drop the
#: rest without any of them looking wrong.
_ULTIMATE_HASTE_PER_STACK = re.compile(
    r"Gain ([\d.]+) \(\+ ([\d.]+) per ''\w[^']*'' \[\[stack\]\]\) "
    r"\[\[ultimate haste\]\], up to ([\d.]+) at (\d+) stacks"
)
#: "Gain ''Legend'' stacks for every 100 points earned, up to 10:" — the
#: ceiling that bounds a per-stack grant's option.
_STACK_CEILING = re.compile(r"stacks for every \d+ points earned, up to (\d+):")
_BUFF_WINDOW = re.compile(r"for ([\d.]+) seconds, causing")
_PROC_DELAY = re.compile(r"\{\{fd\|([\d.]+)\}\}-second delay")
_POUNCE_DELAY = re.compile(r"over \{\{fd\|([\d.]+)\}\} seconds, dealing")
_LANDING_DELAY = re.compile(r"lands after \{\{rutngt\|([\d.]+)\}\}")
_TICK_INTERVAL = re.compile(r"every \{\{fd\|([\d.]+)\}\} seconds")
_AFTER_DELAY = re.compile(r"damage(?:\}\})? after ([\d.]+) seconds?")
# "Deal 8% increased damage to champions below 40% maximum health" — the amp
# and its gate in one sentence.  ``while`` marks the holder's own health as
# the subject (Last Stand); without it the gate reads the target's.
_CONDITIONAL_DAMAGE_AMP = re.compile(
    r"(?P<ratio>[\d.]+)% increased damage to champions (?P<subject>while )?"
    r"(?P<side>above|below) \{\{as\|(?P<health>[\d.]+)% '''maximum''' health\}\}"
)
# The escalated end of a ramping amplifier: "…This increases further based on
# your missing health, up to 11% increased damage while below 30% maximum
# health."  A continuation sentence, so it names neither the verb nor the
# subject the first one did — "up to" is what marks it as the same
# amplifier's other end rather than a second amplifier.
_ESCALATED_DAMAGE_AMP = re.compile(
    r"up to (?P<ratio>[\d.]+)% increased damage (?:to champions )?"
    r"(?P<subject>while )?(?P<side>above|below) "
    r"\{\{as\|(?P<health>[\d.]+)% '''maximum''' health\}\}"
)
_SELF_HEALTH_GATE = re.compile(
    r"while (above|below) \{\{as\|([\d.]+)% of your '''maximum''' health\}\}"
)
# "* Level 5: + 5 [[ability haste]]." — the level gating a grant is as
# load-bearing as the number: a rune stating two of these grants neither
# until its own level is reached.
_LEVEL_GATED_HASTE = re.compile(r"Level (\d+): \+ ([\d.]+) \[\[ability haste\]\]")
# "After reaching 15 stacks" — the count a rune names as its own threshold.
_STACK_THRESHOLD = re.compile(r"After reaching (\d+) stacks")
# "within 4 seconds of using a {{tip|dash}}" — how long a movement event
# leaves a rune armed.  The window is a fact about the rune and not about
# the fight, so it is parsed rather than assumed, and a compiler that
# cannot enforce it quotes it in its disclosure instead of implying none.
_ARMING_WINDOW = re.compile(r"within ([\d.]+) seconds of using a \{\{tip\|dash\}\}")
# "Your ultimate has 12% increased damage (reduced to 8% for area of effect
# abilities)" — an amplifier that reaches one ability slot rather than the
# holder's whole output.  Both ends are matched in one pattern because the
# reduction is stated only as a parenthetical of the headline number: a
# description that dropped the parenthetical would otherwise leave the
# reduced rate silently absent while the headline stayed.
_ULTIMATE_DAMAGE_AMP = re.compile(
    r"ultimate has ([\d.]+)% increased damage \(reduced to ([\d.]+)% for "
    r"\[\[area of effect\]\] abilities\)"
)
#: A conditional amp's two ends and the key prefix each is recorded under:
#: the gate that arms the amplifier, then the escalated gate it ramps to.
_AMP_RAMP_ENDS: tuple[tuple[str, re.Pattern], ...] = (
    ("", _CONDITIONAL_DAMAGE_AMP),
    ("escalated_", _ESCALATED_DAMAGE_AMP),
)
_TT_TEMPLATE = re.compile(r"\{\{tt\|([^|}]+)")
_RANGE_SPEC = re.compile(r"^([\d.]+)\s+to\s+([\d.]+)(?:\s+by\s+([\d.]+))?$")
_FOR_SUFFIX = re.compile(r"^(.+?)\s+for\s+(\d+)$")
# "0 to 70 for 8" — eight columns keyed 0, 10, … 70.  The keys are not the
# numbers the formula takes: ``x`` is the column's ordinal, exactly as the
# ``for N`` suffix reads it, and the span is what the columns are keyed by.
_COLUMN_SPAN = re.compile(r"^([\d.]+)\s+to\s+([\d.]+)\s+for\s+(\d+)$")
# "…;∞" — the wiki's mark that a table's formula continues past its last
# stated column.  It states no value, so it is dropped, never evaluated.
_UNBOUNDED_COLUMN = re.compile(r"\s*;\s*∞\s*$")
# What a non-level pp table's key span is recorded under: the pp's own
# ``type``, so "minutes" reads back as ``minutes_range``.
_KEY_WORD = re.compile(r"\W+")
_ADAPTIVE_FORCE = re.compile(r"\{\{adaptive\|([^{}|]+)\|(\d+)\}\}")
_ADAPTIVE_FLAT = re.compile(r"\{\{adaptive\|([\d.]+)\}\}")
_SOUL_DAMAGE = re.compile(r"deals ([\d.]+) \{\{as\|\(\+ ([\d.]+) per Soul\)\}\}")

# Display wrappers the value patterns must see through.  {{ap}} resolves
# only a single positional arithmetic param: a named param (``round=3``)
# marks a wiki-side derived display value, and resolving it would conflict
# with the source number it was derived from.
_FD_NUMBER = re.compile(r"\{\{fd\|([\d.]+%?)\}\}")
_STI_WRAPPER = re.compile(r"\{\{sti\|([^{}|]*)\}\}")
_AP_ARITHMETIC = re.compile(r"\{\{ap\|([^{}|=]+)\}\}")
# ``0.6{{recurring|6}}`` overlines the repeating decimals (Template:Recurring).
_RECURRING = re.compile(r"(\d+)\.(\d*)\{\{recurring\|(\d+)\}\}")
# ``{{#vardefineecho:basealacrity|3}}`` defines a wiki variable *and* prints
# its value, so the value is the rendered text.  The plain ``{{#var:}}`` read
# and ``{{#expr:}}`` arithmetic that restate it later are deliberately left
# alone: those appear only inside "up to … at maximum stacks" restatements,
# which are masked before any value pattern sees them.
_VARDEFINEECHO = re.compile(r"\{\{#vardefineecho:[^{}|]+\|([^{}|]*)\}\}")

# "up to <derived value> at maximum stacks/range" — a restatement, never a
# second source value.  Tempered so the span starts at the *nearest* "up to"
# (an earlier "stacking up to N times" must not widen it).
_MAXIMUM_RESTATEMENT = re.compile(
    r"up to (?:(?!up to).)*? at maximum (?:stacks|range)",
    re.IGNORECASE | re.DOTALL,
)

# Jack Of All Trades states its whole rule in three sentences, and all three
# have to be claimed together: the per-stack step, the two stack gates, and
# the total the gates add up to.  Left to the general rules the two gates
# would arrive as two values of one adaptive-force key and be dropped as a
# conflict — which is exactly what the cache showed before these existed.
_ABILITY_HASTE_PER_STACK = re.compile(
    r"For each ''\w[^']*'' stack, gain \{\{as\|([\d.]+) ability haste\}\}"
)
_ADAPTIVE_STACK_GATE = re.compile(
    r"At (\d+) ''\w[^']*'' stacks, gain (?:an additional )?\{\{adaptive\|([\d.]+)\}\}"
)
#: ", for a total of {{adaptive|20}} at 10 ''Jack'' stacks" — the gates
#: restated as their sum, exactly like "up to N at maximum stacks", and read
#: to certify them rather than recorded as a third value.
_STACK_GATE_TOTAL = re.compile(
    r",? for a total of \{\{adaptive\|([\d.]+)\}\} at \d+ ''\w[^']*'' stacks"
)

# One key, one quantity: every {{rd|X%|Y%}} scalar split is claimed by the
# context rule naming what it measures.  An unclaimed pair warns and records
# nothing.
_RD_SPLIT_RULES: tuple[tuple[str, re.Pattern], ...] = (
    (
        "attack_speed_ratios",
        re.compile(
            r"\{\{as\|\{\{rd\|([\d.]+)%\|([\d.]+)%\}\}[^{}|]*attack speed\|as\}\}"
        ),
    ),
    (
        "move_speed_ratios",
        re.compile(
            r"\{\{as\|\{\{rd\|([\d.]+)%\|([\d.]+)%\}\}"
            r"(?:\|ms\}\}|[^{}|]*movement speed\}\})"
        ),
    ),
    (
        "gold_conversion_ratios",
        re.compile(
            r"gold\}?\}? equal to \{\{rd\|([\d.]+)%\|([\d.]+)%\}\} of all "
            r"(?:'''bonus'''|bonus) damage"
        ),
    ),
    (
        "heal_share_ratios",
        re.compile(
            r"\{\{tip\|heal\}\} for \{\{rd\|([\d.]+)%\|([\d.]+)%\}\} of the "
            r"\{\{tt\|post-mitigation damage"
        ),
    ),
    (
        "max_health_damage_ratios",
        re.compile(
            r"equal to \{\{as\|\{\{rd\|([\d.]+)%\|([\d.]+)%\}\} of your "
            r"'''maximum''' health\}\}"
        ),
    ),
    (
        "max_health_heal_ratios",
        re.compile(
            r"\{\{tip\|heal\}\} you for \{\{as\|\(\+ \{\{rd\|([\d.]+)%\|([\d.]+)%\}\} "
            r"of your '''maximum''' health\)\}\}"
        ),
    ),
    (
        "damage_per_bonus_attack_speed_ratios",
        re.compile(
            r"increased by \{\{rd\|([\d.]+)%\|([\d.]+)%\}\} per "
            r"\{\{as\|1% '''bonus''' attack speed\}\}"
        ),
    ),
)

#: Melee/ranged splits of a flat quantity — counts and flat stat grants,
#: recorded as stated rather than divided by 100.
_RD_FLAT_RULES: tuple[tuple[str, re.Pattern], ...] = (
    (
        "basic_damage_stacks",
        re.compile(
            r"Gain \{\{rd\|([\d.]+)\|([\d.]+)\}\} stacks for \{\{tip\|basic damage\}\}"
        ),
    ),
    (
        "permanent_bonus_health",
        re.compile(
            r"permanently grant you \{\{as\|\{\{rd\|([\d.]+)\|([\d.]+)\}\} "
            r"'''bonus''' health\}\}"
        ),
    ),
)

# An rd template (up to two nesting levels deep) no rule claimed.
_UNCLAIMED_RD = re.compile(r"\{\{rd\|(?:[^{}]|\{\{(?:[^{}]|\{\{[^{}]*\}\})*\}\})*\}\}")

#: Module:Ability progression's ``defaultSize``: a stepless ``A to B`` with
#: no explicit range renders 18 columns, endpoints anchored at levels 1/18.
#: Public because it is the width of a legitimately short level table, and
#: ``rune_effects`` must admit one rather than call it a degraded parse.
DEFAULT_LEVEL_COUNT = 18

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

    Sourced forms: a semicolon list of literal values, an ``N to M by S``
    enumeration of the values themselves (the second param then carries
    the keys, e.g. a distance span), a stepless ``N to M`` span
    (linear-filled with endpoints anchored — over the explicit range when
    one is given, else the wiki's default 18 columns), and an arithmetic
    formula in ``x``.  A ``for N`` suffix on the formula supplies the
    range ``1..N`` when no second param does.
    """
    formula = _drop_unbounded_column(formula)
    range_spec = _drop_unbounded_column(range_spec) if range_spec else range_spec
    for_suffix = _FOR_SUFFIX.match(formula)
    if for_suffix:
        formula = for_suffix.group(1).strip()
        if not range_spec:
            range_spec = f"1 to {for_suffix.group(2)} by 1"
    if ";" in formula and "x" not in formula:
        return [float(part) for part in formula.split(";") if part.strip()]
    shorthand = _RANGE_SPEC.match(formula)
    if shorthand and shorthand.group(3):
        return _enumerate_range(shorthand)
    if shorthand:
        return _interpolate_endpoints(shorthand, range_spec)
    if not range_spec:
        raise ValueError(f"pp formula {formula!r} has no level range")
    columns = _COLUMN_SPAN.match(range_spec.strip())
    if columns:
        expression = _safe_pp_expression(formula)
        return [
            _evaluate_pp_node(expression.body, float(column))
            for column in range(1, int(columns.group(3)) + 1)
        ]
    range_match = _RANGE_SPEC.match(range_spec.strip())
    if not range_match:
        raise ValueError(f"Unsupported pp range spec {range_spec!r}")
    expression = _safe_pp_expression(formula)
    return [
        _evaluate_pp_node(expression.body, x) for x in _enumerate_range(range_match)
    ]


def _drop_unbounded_column(spec: str) -> str:
    """Strip a ``;∞`` final column: the wiki's "and beyond", not a value."""
    return _UNBOUNDED_COLUMN.sub("", spec.strip())


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


def _interpolate_endpoints(match: re.Match, range_spec: str | None) -> list[float]:
    """Linear-fill a stepless ``A to B`` span, endpoints anchored.

    Mirrors Module:Ability progression's linear filling: A at the first
    level, B at the last, over the explicit range's count when one is
    given, else the default 18 columns.
    """
    start_value, finish_value = float(match.group(1)), float(match.group(2))
    if range_spec:
        spec = _RANGE_SPEC.match(range_spec.strip())
        if not spec:
            raise ValueError(f"Unsupported pp range spec {range_spec!r}")
        count = len(_enumerate_range(spec))
    else:
        count = DEFAULT_LEVEL_COUNT
    if count < 2:
        raise ValueError(f"pp span {match.group(0)!r} needs at least two levels")
    step = (finish_value - start_value) / (count - 1)
    return [start_value + step * index for index in range(count)]


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


class _EffectRecorder:
    """Collects parsed effect values, failing closed on conflicts.

    Two different numbers arriving under one key is a parse defect —
    keeping either would be a plausible-looking wrong number.  The key is
    dropped (consumers fail closed on absence) and the conflict recorded
    as a warning.  Equal re-matches are one fact stated twice, not a
    conflict.
    """

    def __init__(self) -> None:
        self.effects: dict[str, Any] = {}
        self.warnings: list[str] = []
        self._conflicted: set[str] = set()

    def warn(self, message: str) -> None:
        """Record one parse warning for ``data/runes.json`` to carry."""
        self.warnings.append(message)

    def record(self, key: str, value: Any) -> None:
        """Record one value, dropping the key on a conflicting duplicate."""
        if key in self._conflicted:
            self.warn(f"{key} matched again after a conflict: {value!r}")
            return
        if key in self.effects and self.effects[key] != value:
            self.warn(
                f"{key} matched conflicting values, dropped: "
                f"{self.effects[key]!r}, {value!r}"
            )
            del self.effects[key]
            self._conflicted.add(key)
            return
        self.effects[key] = value


def parse_effects(description: str) -> tuple[dict[str, Any], list[str]]:
    """Extract the numeric effect values a description carries.

    Returns the effects dict plus parse warnings. Keys are only present
    when their source text parsed — consumers fail closed on absence.
    """
    recorder = _EffectRecorder()
    _parse_leveling(description, recorder)
    _parse_scalar_templates(description, recorder)
    _parse_prose_rules(description, recorder)
    return recorder.effects, recorder.warnings


def _resolve_ap_arithmetic(match: re.Match) -> str:
    """Evaluate one ``{{ap|<arithmetic>}}`` body, or leave it untouched."""
    try:
        expression = _safe_pp_expression(match.group(1).strip())
    except ValueError:
        return match.group(0)
    if any(isinstance(node, ast.Name) for node in ast.walk(expression)):
        return match.group(0)
    return f"{_evaluate_pp_node(expression.body, 0.0):g}"


def _resolve_recurring(match: re.Match) -> str:
    """Expand ``0.6{{recurring|6}}`` into its exact repeating-decimal value."""
    integer, fixed, repeating = match.groups()
    scale = 10 ** len(fixed)
    period = 10 ** len(repeating)
    value = (int(integer + fixed + repeating) - int(integer + fixed)) / (
        scale * period - scale
    )
    return repr(value)


def _resolve_display_templates(text: str) -> str:
    """Inline ``{{fd}}``/``{{ap}}``/``{{sti}}`` wrappers to a fixpoint.

    Nesting like ``{{rd|{{fd|3.5}}%|{{fd|1.4}}%}}`` resolves inside-out;
    anything a pass cannot resolve (unknown templates, ``{{ap|...|round=3}}``
    derived displays) stays verbatim and its enclosing pattern simply
    fails to match — absence, never a guess.
    """
    for _ in range(4):
        resolved = _RECURRING.sub(_resolve_recurring, text)
        resolved = _VARDEFINEECHO.sub(lambda match: match.group(1), resolved)
        resolved = _FD_NUMBER.sub(lambda match: match.group(1), resolved)
        resolved = _STI_WRAPPER.sub(lambda match: match.group(1), resolved)
        resolved = _AP_ARITHMETIC.sub(_resolve_ap_arithmetic, resolved)
        if resolved == text:
            break
        text = resolved
    return text


def _parse_leveling(description: str, recorder: _EffectRecorder) -> None:
    """Evaluate every level-table template into per-level value lists.

    ``{{pp}}`` tables join ``leveling`` in sentence order (a ``type=``
    naming a distance is keyed by travel distance instead and stored as
    ``distance_scaling``).  ``{{rd|...|pp=true}}`` melee/ranged formula
    pairs land under ``melee_ranged_leveling`` (``heal_melee_ranged_
    leveling`` when ``color=heal`` marks them as a heal table).
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
            recorder.warn(str(exc))
            continue
        if named.get("type", "").startswith("distance"):
            span = _RANGE_SPEC.match((range_spec or "").strip())
            if not span:
                recorder.warn(f"distance pp has no distance span: {pp_body!r}")
                continue
            recorder.record(
                "distance_scaling",
                {
                    "values": values,
                    "distance_range": [float(span.group(1)), float(span.group(2))],
                },
            )
        else:
            _record_key_span(named, range_spec, recorder)
            leveling.append(values)
    if leveling:
        recorder.effects["leveling"] = leveling
    _parse_split_leveling(description, recorder)


def _record_key_span(
    named: dict[str, str], range_spec: str | None, recorder: _EffectRecorder
) -> None:
    """Record what a non-level table's columns are keyed by, when it says.

    A ``type=`` plus a column-count span means the table is read by
    something other than champion level — game minutes, not levels — and
    the span is the only statement of the step between its columns. Without
    it the values are a list nothing can index.
    """
    span = _COLUMN_SPAN.match(_drop_unbounded_column(range_spec or ""))
    if not span or not named.get("type"):
        return
    key = _KEY_WORD.sub("_", named["type"].strip().lower()).strip("_")
    recorder.record(f"{key}_range", [float(span.group(1)), float(span.group(2))])


def _parse_split_leveling(description: str, recorder: _EffectRecorder) -> None:
    """Read ``{{rd|<melee>|<ranged>|pp=true}}`` level-table pairs."""
    for rd_body in _RD_TEMPLATE.findall(description):
        parts = rd_body.split("|")
        named = dict(part.split("=", 1) for part in parts if "=" in part)
        if named.get("pp") != "true":
            continue
        positional = [part for part in parts if "=" not in part]
        if len(positional) != 2:
            recorder.warn(f"rd pp pair needs melee and ranged formulas: {rd_body!r}")
            continue
        try:
            pair = [evaluate_pp(formula, None) for formula in positional]
        except ValueError as exc:
            recorder.warn(str(exc))
            continue
        key = (
            "heal_melee_ranged_leveling"
            if named.get("color") == "heal"
            else "melee_ranged_leveling"
        )
        recorder.record(key, pair)


def _claim_split_pairs(text: str, recorder: _EffectRecorder) -> str:
    """Record every classified ``{{rd|...}}`` pair and blank its text."""

    def claim(key: str):
        def _claim(match: re.Match) -> str:
            recorder.record(
                key,
                [float(match.group(1)) / 100.0, float(match.group(2)) / 100.0],
            )
            return " "

        return _claim

    def claim_flat(key: str):
        def _claim(match: re.Match) -> str:
            recorder.record(key, [float(match.group(1)), float(match.group(2))])
            return " "

        return _claim

    for key, pattern in _RD_SPLIT_RULES:
        text = pattern.sub(claim(key), text)
    for key, pattern in _RD_FLAT_RULES:
        text = pattern.sub(claim_flat(key), text)

    def claim_ratio_pair(match: re.Match) -> str:
        melee_percent, ranged_percent, bonus_marker, stat = match.groups()
        if stat == "AP":
            key = "ap_ratios"
        elif bonus_marker:
            key = "bonus_ad_ratios"
        else:
            key = "ad_ratios"
        recorder.record(
            key, [float(melee_percent) / 100.0, float(ranged_percent) / 100.0]
        )
        return " "

    return _AS_RATIO_PAIR.sub(claim_ratio_pair, text)


def _claim_stack_gated_grants(text: str, recorder: _EffectRecorder) -> str:
    """Record a rune's per-stack and stack-gated grants, blanking their text.

    Blanking is what makes them claimable at all: left in place, the general
    flat rules would read the per-stack ability haste as a flat grant and
    the two adaptive gates as two values of one key — dropping both as a
    conflict, which is what the cache showed before this existed.

    The trailing "for a total of X at N stacks" sentence is the gates
    restated as their sum, so it certifies them rather than being recorded:
    a page whose parts stop adding up is a rewording nothing should price
    through, and the gates are dropped with a warning instead.
    """
    text = _ABILITY_HASTE_PER_STACK.sub(
        lambda match: recorder.record("ability_haste_per_stack", float(match.group(1)))
        or " ",
        text,
    )
    gates = [
        [int(stacks), float(force)]
        for stacks, force in _ADAPTIVE_STACK_GATE.findall(text)
    ]
    text = _ADAPTIVE_STACK_GATE.sub(" ", text)
    total_match = _STACK_GATE_TOTAL.search(text)
    text = _STACK_GATE_TOTAL.sub(" ", text)
    if not gates:
        return text
    if (
        total_match
        and abs(sum(force for _, force in gates) - float(total_match.group(1))) > 1e-9
    ):
        recorder.warn(
            f"stack-gated adaptive force {gates!r} does not add up to the "
            f"stated total {total_match.group(1)}; dropped"
        )
        return text
    recorder.record("adaptive_force_stack_gates", gates)
    return text


def _parse_per_stack_grants(text: str, recorder: _EffectRecorder) -> None:
    """Read the stat grants a rune states per stack of a named counter.

    Only the step is recorded — the stack count is an input the request does
    not carry, so a compiler declares it as an option and multiplies. Legend:
    Alacrity states a base beside its step in one sentence, and one rule
    reads both so a reworded page cannot keep one and drop the other.
    """
    base_and_step = _ATTACK_SPEED_PER_STACK.search(text)
    if base_and_step:
        recorder.record("attack_speed_percent", float(base_and_step.group(1)))
        recorder.record("attack_speed_percent_per_stack", float(base_and_step.group(2)))
    _parse_ultimate_haste_stacks(text, recorder)
    for key, pattern in _PER_STACK_RULES:
        for amount in pattern.findall(text):
            recorder.record(key, float(amount))


def _parse_ultimate_haste_stacks(text: str, recorder: _EffectRecorder) -> None:
    """Read a base ultimate-haste grant, its per-stack step and its ceiling.

    The sentence states the total as well, and it is read to *certify* the
    other three rather than recorded: base + step × ceiling is the total, so
    a page whose four numbers stop agreeing is a rewording the compiler must
    not price through.  Nothing is recorded in that case — absence, never a
    plausible-looking wrong number.
    """
    match = _ULTIMATE_HASTE_PER_STACK.search(text)
    if not match:
        return
    base, step, total, ceiling = (float(value) for value in match.groups())
    if abs(base + step * ceiling - total) > 1e-9:
        recorder.warn(
            f"ultimate haste states {base:g} + {step:g} per stack up to "
            f"{total:g} at {ceiling:g} stacks, which do not agree; dropped"
        )
        return
    recorder.record("ultimate_haste", base)
    recorder.record("ultimate_haste_per_stack", step)
    recorder.record("max_stacks", int(ceiling))


def _parse_scalar_templates(description: str, recorder: _EffectRecorder) -> None:
    """Read the single-value template forms: ratios, gold, range splits.

    Works on resolved text (display wrappers inlined) with "up to ... at
    maximum" restatements masked out — those are derived values whose
    only effect would be conflicting with their sources.
    """
    text = _MAXIMUM_RESTATEMENT.sub(" ", _resolve_display_templates(description))
    text = _claim_split_pairs(text, recorder)
    text = _claim_stack_gated_grants(text, recorder)

    for percent, bonus_marker, stat in _AS_RATIO.findall(text):
        if stat == "AP":
            key = "ap_ratio"
        elif bonus_marker:
            key = "bonus_ad_ratio"
        else:
            key = "ad_ratio"
        recorder.record(key, float(percent) / 100.0)

    for key, pattern in _AS_QUANTITY_RATIO_RULES:
        for percent in pattern.findall(text):
            recorder.record(key, float(percent) / 100.0)

    for percent in _BONUS_TRUE_DAMAGE.findall(text):
        recorder.record("bonus_true_damage_ratio", float(percent) / 100.0)

    for amount in _FLAT_GOLD.findall(text):
        recorder.record("flat_gold", float(amount))

    for key, pattern in _FLAT_STAT_RULES:
        for amount in pattern.findall(text):
            recorder.record(key, float(amount))

    _parse_per_stack_grants(text, recorder)

    for formula, levels in _ADAPTIVE_FORCE.findall(text):
        try:
            values = evaluate_pp(formula, f"1 to {levels} by 1")
        except ValueError as exc:
            recorder.warn(str(exc))
            continue
        recorder.record("adaptive_force_leveling", values)

    for amount in _ADAPTIVE_FLAT.findall(text):
        recorder.record("adaptive_force", float(amount))

    for base, per_soul in _SOUL_DAMAGE.findall(text):
        recorder.record("base_damage", float(base))
        recorder.record("damage_per_soul", float(per_soul))

    text = _RD_TEMPLATE.sub(
        lambda match: " " if "pp=true" in match.group(1) else match.group(0), text
    )
    for leftover in _UNCLAIMED_RD.findall(text):
        recorder.warn(f"unclassified melee/ranged split: {leftover}")


def _parse_prose_rules(description: str, recorder: _EffectRecorder) -> None:
    """Read the prose-form rules: buff windows, stack rules, proc delays."""
    window_match = _BUFF_WINDOW.search(description)
    if window_match:
        recorder.record("buff_duration_seconds", float(window_match.group(1)))

    stack_match = _STACK_RULE.search(description)
    if stack_match:
        recorder.record("stacks_required", int(stack_match.group(1)))
        recorder.record("stack_window_seconds", float(stack_match.group(2)))

    duration_match = _STACK_DURATION.search(description)
    if duration_match:
        recorder.record("stack_duration_seconds", float(duration_match.group(1)))

    max_stacks_match = _MAX_STACKS.search(description) or _STACK_CEILING.search(
        description
    )
    if max_stacks_match:
        recorder.record("max_stacks", int(max_stacks_match.group(1)))

    threshold_match = _STACK_THRESHOLD.search(description)
    if threshold_match:
        recorder.record("stack_threshold", int(threshold_match.group(1)))

    arming_match = _ARMING_WINDOW.search(description)
    if arming_match:
        recorder.record("arming_window_seconds", float(arming_match.group(1)))

    level_gates = [
        [int(level), float(bonus)]
        for level, bonus in _LEVEL_GATED_HASTE.findall(description)
    ]
    if level_gates:
        recorder.record("ability_haste_level_gates", level_gates)

    _parse_conditional_amp(description, recorder)

    delay_match = (
        _PROC_DELAY.search(description)
        or _POUNCE_DELAY.search(description)
        or _LANDING_DELAY.search(description)
        or _AFTER_DELAY.search(description)
    )
    if delay_match:
        recorder.record("proc_delay_seconds", float(delay_match.group(1)))

    tick_match = _TICK_INTERVAL.search(description)
    if tick_match:
        recorder.record("tick_interval_seconds", float(tick_match.group(1)))


def _parse_conditional_amp(description: str, recorder: _EffectRecorder) -> None:
    """Read a damage amplifier and, when it has one, the health gate it reads.

    Three keys rather than one because the amp is one fact and the condition
    is another: a compiler that reads ``damage_amp_ratio`` without
    ``damage_amp_health_ratio`` is amplifying unconditionally, and the
    subject says whose health the gate measures — the target's (Coup de
    Grace, Cut Down) or the holder's own (Last Stand).

    A rune stating the amp twice states a *ramp*: Last Stand's 5% arms below
    60% health and reaches 11% below 30%.  The second sentence is recorded
    under its own escalated keys rather than as a second value for the first
    ones, which the recorder would (rightly) drop as a conflict.
    """
    amp_match = _DAMAGE_AMP.search(description)
    if amp_match:
        recorder.record("damage_amp_ratio", float(amp_match.group(1)) / 100.0)

    for prefix, pattern in _AMP_RAMP_ENDS:
        gate_match = pattern.search(description)
        if not gate_match:
            continue
        recorder.record(
            f"{prefix}damage_amp_ratio", float(gate_match.group("ratio")) / 100.0
        )
        recorder.record(
            f"{prefix}damage_amp_health_ratio",
            float(gate_match.group("health")) / 100.0,
        )
        subject = "self" if gate_match.group("subject") else "target"
        recorder.record(
            f"{prefix}damage_amp_health_gate", f"{subject}_{gate_match.group('side')}"
        )

    ultimate_match = _ULTIMATE_DAMAGE_AMP.search(description)
    if ultimate_match:
        recorder.record(
            "ultimate_damage_amp_ratio", float(ultimate_match.group(1)) / 100.0
        )
        recorder.record(
            "ultimate_aoe_damage_amp_ratio", float(ultimate_match.group(2)) / 100.0
        )

    self_gate = _SELF_HEALTH_GATE.search(description)
    if self_gate:
        recorder.record("self_health_gate", f"self_{self_gate.group(1)}")
        recorder.record("self_health_gate_ratio", float(self_gate.group(2)) / 100.0)


def rune_payload(
    name: str, wikitext: str, icon: str = "", *, path: str, row: int
) -> dict[str, Any]:
    """Build one ``data/runes.json`` entry from a rune's template wikitext.

    ``path`` and ``row`` are the roster's facts (Data Dragon's
    ``runesReforged.json``, where row 0 is the keystone row); the wikitext
    supplies the text.  The template states its own path and slot, and they
    are read here only to certify the two sources agree — a disagreement is
    a parse warning, never a second copy of the fact.
    """
    params = parse_rune_template(wikitext)
    description = "\n".join(
        params.get(key, "") for key in ("description", "description2")
    ).strip()
    effects, warnings = parse_effects(description)
    warnings = _certify_roster_agreement(params, path, row) + warnings
    payload: dict[str, Any] = {
        "name": name,
        "path": path,
        "row": row,
        "cooldown": parse_cooldown(params.get("cooldown")),
        "icon": icon,
        "description": description,
        "effects": effects,
    }
    if warnings:
        payload["parse_warnings"] = warnings
    return payload


def _certify_roster_agreement(params: dict[str, str], path: str, row: int) -> list[str]:
    """Warn when the wiki template disagrees with the Data Dragon roster.

    The template spells its slot ``Keystone`` on row 0 and the row number
    on rows 1-3, so both facts are checkable without keeping a second copy
    of either.
    """
    warnings: list[str] = []
    template_path = params.get("path", "").strip()
    if template_path and template_path.casefold() != path.casefold():
        warnings.append(
            f"roster path {path!r} disagrees with the template's {template_path!r}"
        )
    template_slot = params.get("slot", "").strip()
    expected_slot = "Keystone" if row == 0 else str(row)
    if template_slot and template_slot.casefold() != expected_slot.casefold():
        warnings.append(
            f"roster row {row} expects slot {expected_slot!r} and the template "
            f"says {template_slot!r}"
        )
    return warnings


# The Rune page's Trees table names the five paths in the order the game
# shows them, which is the order the roster is cached in.  Data Dragon
# carries no such order, and a hand list of five path names is exactly the
# kind of second copy this campaign removes.
_RUNE_TABLE_ROW = re.compile(r"\{\{Rune table row\|(\w+)\}\}")


def path_order(wikitext: str) -> list[str]:
    """The five rune paths, in the order the Rune page lists them."""
    order = _RUNE_TABLE_ROW.findall(wikitext)
    if not order:
        raise ValueError("Rune page lists no rune paths")
    return order


# The Rune page's shard table, the one source for the three stat-shard rows.
# The wiki keeps no ``Template:Rune data`` page for a shard, so the table is
# read where it is written and cached with the revision it was read at.
_SHARD_SECTION = re.compile(r"===\s*Shards\s*===(.*?)(?=\n==)", re.DOTALL)
_SHARD_ROW = re.compile(r"^!.*?\|\s*Slot (\d+)<br />\{\{sbc\|(\w+)\}\}\s*$")
_SHARD_OPTION = re.compile(
    r"^\|\s*\[\[File:Rune shard (.+?)\.png\|[^\]]*\]\]<br />(.*)$"
)


def shard_payload(wikitext: str, *, source: str, revision: int) -> dict[str, Any]:
    """Build the cached stat-shard table from the Rune page's wikitext.

    Each row is one of the page's three shard slots (Offense, Flex,
    Defense) and each option keeps its verbatim cell text beside the values
    :func:`parse_effects` could read from it — the same split every rune
    entry carries, so a shard compiler reads a shard exactly the way a rune
    compiler reads a rune.
    """
    section = _SHARD_SECTION.search(wikitext)
    if section is None:
        raise ValueError("Rune page has no Shards section")
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in section.group(1).splitlines():
        row_match = _SHARD_ROW.match(line.strip())
        if row_match:
            current = {
                "row": int(row_match.group(1)),
                "name": row_match.group(2),
                "options": [],
            }
            rows.append(current)
            continue
        option_match = _SHARD_OPTION.match(line.strip())
        if option_match is None or current is None:
            continue
        description = option_match.group(2).strip()
        effects, warnings = parse_effects(description)
        option: dict[str, Any] = {
            "name": option_match.group(1),
            "description": description,
            "effects": effects,
        }
        if warnings:
            option["parse_warnings"] = warnings
        current["options"].append(option)
    if not rows:
        raise ValueError("Rune page's Shards section holds no shard rows")
    return {"source": source, "revision": revision, "slots": rows}


# ``Template:Adaptive``'s own conversion variable: adaptive force is worth
# ``af`` bonus attack damage or its full value in ability power, and the
# template branches on Wild Rift.  Summoner's Rift is the second value.
_ADAPTIVE_CONVERSION = re.compile(
    r"\{\{#vardefine:af\|\{\{#ifeq:\{\{\{wr\|\}\}\}\|true\|[\d.]+\|([\d.]+)\}\}\}\}"
)


def adaptive_force_payload(
    wikitext: str, *, source: str, revision: int
) -> dict[str, Any]:
    """Read the adaptive-force conversion from ``Template:Adaptive``.

    Every rune and shard that grants adaptive force states the force, not
    what it converts to; the template that renders them owns the ratio, so
    that is where it is read from rather than spelled in a compiler.
    """
    match = _ADAPTIVE_CONVERSION.search(wikitext)
    if match is None:
        raise ValueError("Template:Adaptive states no Summoner's Rift af conversion")
    return {
        "attack_damage_ratio": float(match.group(1)),
        "source": source,
        "revision": revision,
    }


#: Top-level keys of ``data/runes.json`` that are not runes: the page-level
#: facts no single rune owns.  One tuple so every reader agrees on which keys
#: to skip when walking the rune roster.
SHARDS_KEY = "shards"
ADAPTIVE_FORCE_KEY = "adaptive_force"
RESERVED_CACHE_KEYS: tuple[str, ...] = (SHARDS_KEY, ADAPTIVE_FORCE_KEY)
