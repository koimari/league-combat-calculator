"""Measure how much of the game the calculator models, on every axis at once.

``docs/coverage-status.md`` is the human reading of the repo's own receipts
and of a live scan of the registered modules; this script is what writes it,
so the page cannot drift from the tree the way a hand-kept table does. The
same drift is why it has a ``--check`` mode: a change that moves any number
here fails the gate until the page is regenerated.

What it measures, and where each number comes from:

* **Champion slots** — the ``coverage`` map every named module publishes
  through its contract, which is the module's own claim about each of its
  five slots and is validated against what the slot actually emits by
  ``tests/test_coverage_truth_sweep.py``.
* **Items and runes** — the typed registries (``item_effects.ITEM_EFFECTS``,
  the published rune compilers) against the caches they are read from.
* **Declared axes** — champion options, split by whether the option asks the
  user for a fact about the fight (a count of procs, a number of stacks) or
  states a choice only a player can make (which variant, how many enemies a
  cone catches). The first class is the engine's remaining depth debt.
* **Named frontiers** — the receipts that already hold what is deliberately
  not modelled, each with its own reason.

Usage::

    python scripts/coverage_status.py --write
    python scripts/coverage_status.py --check
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.calculator import (  # noqa: E402  pylint: disable=wrong-import-position
    item_effects,
    rune_effects,
)
from src.calculator.champions import (  # noqa: E402  pylint: disable=wrong-import-position
    _CHAMPION_MODULES,
    get_champion_module_contract,
    get_champion_options_meta,
)

TARGET = ROOT / "docs" / "coverage-status.md"
SLOTS = ("P", "Q", "W", "E", "R")

# An option whose key names a COUNT is one of two very different things,
# and lumping them together overstates the debt. A count of events INSIDE
# the modelled fight (procs landed, ticks taken, casts made) is a
# derivation the engine could do from the cast plan and the swing
# schedule. A count of state the champion walked in WITH (stacks farmed
# over a game, souls collected, a mark already on the target) is a
# scenario fact no engine can derive, and asking for it is correct.
_COUNT_WORDS = (
    "procs",
    "stacks",
    "autos",
    "casts",
    "recasts",
    "hits",
    "windows",
    "charges",
    "shots",
    "ticks",
    "attacks",
)

# The label phrases that say "this is what the champion arrived with".
# Matching is on the label, not the key, because the label is where a
# module states the reading; an option matching none of these is reported
# as needing review rather than silently counted either way.
_PRE_FIGHT_PHRASES = (
    "carried into the fight",
    "when the fight opens",
    "at the opening",
    "already",
    "pre-stacked",
    "stored at fight start",
    "at fight start",
    "permanent",
    "on spawn",
    "before q",
)

# A count of events inside the fight that nonetheless nobody's engine can
# derive, because the number is a fact about the ENEMY or about where the
# champion stood: how many attacks an evasion dodged, how many swings
# landed from behind, how many distinct enemies a mark tagged. Each is
# reviewed here with the fact it depends on, and each is reported as
# player state rather than as engine debt.
# Counts the fight COULD walk, if any source the repo holds stated the one
# number the walk needs. Each names the missing datum, because "not yet
# derived" and "cannot be derived from anything here" are different
# frontiers and only the second is blocked on data.
_BLOCKED_ON_DATA = {
    "q_turret_attacks:Heimerdinger": (
        "the turret's attack speed, which is in no cached field and in no "
        "spell object this repo tracks"
    ),
    "w_attacks:Kindred": (
        "Wolf's base attack rate; the cache states only that it scales with "
        "25% of Kindred's bonus attack speed"
    ),
}

# An option the engine ALREADY answers whenever the fight has a clock, and
# that only speaks for the clockless reading (a one-rotation request, a
# direct parse). Nothing is owed here: a fight with a duration never asks.
_CLOCKLESS_ONLY = {
    "e_ticks:Karthus": (
        "a timed Karthus fight derives the Defile ticks from the window and "
        "the mana pool; this option speaks only for one rotation"
    ),
}

# A stack level the champion ACCUMULATES outside a fight: farm, kills,
# takedowns, souls collected over a game. No fight walk reaches these, so
# asking is correct and permanent.
_CARRIED_STACKS = {
    "stardust_stacks",
    "feast_stacks",
    "adoration_stacks",
    "senna_mist_stacks",
    "scalemail_stacks",
    "p_stacks:Smolder",
    "lavender_stacks",
    "q_stacks:Nasus",
}

# Which enemy skillshots a blocking ability caught. That is what the ENEMY
# threw and where they aimed it, so it is the same class as an evasion's
# dodge count.
_BLOCK_LISTS = (
    "e_blocked_skillshots",
    "w_blocked_skillshots",
)

# A stack level the fight itself builds, from the attacks and ability hits
# it already schedules, and reads at the moment of a cast. Deriving these
# means walking a stack timeline into the cast pricing rather than counting
# procs, which is the next campaign and NOT the in-fight proc frontier this
# page's first row measures; they are reported apart so neither number
# flatters the other.
_IN_FIGHT_STACK_LEVELS = {
    "q_focus_stacks",
    "passive_stacks",
    "e_true_grit_stacks",
    "q_stacks",
    "p_stacks",
    "jinx_rev_up_stacks",
    "jinx_get_excited_stacks",
    "rend_stacks",
    "r_stacks",
    "w_hunters_vigor_stacks",
    "e_stacks",
    "r_overwhelm_stacks",
    "p_style_stacks",
    "blight_stacks",
    "relentless_storm_stacks",
    "stone_skin_stacks",
    "clean_cuts_stacks",
    "p_determination_stacks",
}

_ENEMY_OR_POSITIONAL = {
    "e_dodged_attacks": "how many attacks the enemy threw into the evasion",
    "w_thorns_autos": "how many basic attacks the enemy spent on the curl",
    "p_procs:Shaco": "whether each swing landed from behind the target",
    "p_procs:Miss Fortune": "how many distinct enemies the Love Taps tagged",
    "p_leverage_procs": "how many distinct enemies the mark moved between",
    "passive_procs:Akali": "whether the champion walked back through her ring",
    "e_shots:Akshan": "how long the hook held while he swung around the anchor",
    "soldier_autos:Azir": "whether the attacks were taken through a soldier",
    "q_casts:Shyvana": "how many strikes of the chain one cast spent",
    "r_casts:Wukong": (
        "whether the ultimate was recast, which the module does not certify"
    ),
}


# Options whose count is genuinely in-fight but whose label carries no
# phrase either way: each is listed with the reading a reader would apply,
# so the split is reviewed rather than inferred from wording.
_IN_FIGHT_KEYS = frozenset(
    {
        "e_shots",
        "q_casts",
        "r_casts",
        "q_recasts",
        "w_ticks",
        "r_ticks",
        "p_ticks",
        "e_ticks",
        "e_attacks",
        "w_attacks",
        "p_procs",
        "passive_procs",
        "we_hits",
        "r_shots",
        "q_turret_attacks",
        "w_box_attacks",
        "r_clone_attacks",
        "tibbers_attacks",
        "voidling_attacks",
        "daisy_attacks",
        "maiden_attacks",
        "mist_walker_attacks",
        "plant_attacks",
        "soldier_autos",
        "q_empowered_attacks",
        "q_attacks_landed",
        "w_thorns_autos",
        "e_dodged_attacks",
        "p_illumination_procs",
        "p_leverage_procs",
        "q_snippy_stacks",
    }
)


def _champion_slots() -> (
    tuple[collections.Counter, dict[str, collections.Counter], list]
):
    """Every registered module's own coverage claim, slot by slot."""
    totals: collections.Counter = collections.Counter()
    per_slot: dict[str, collections.Counter] = {
        slot: collections.Counter() for slot in SLOTS
    }
    out_of_scope: list[tuple[str, str]] = []
    for name in sorted(_CHAMPION_MODULES):
        coverage = get_champion_module_contract(name).coverage
        for slot in SLOTS:
            state = coverage.get(slot)
            if state is None:
                continue
            totals[state] += 1
            per_slot[slot][state] += 1
            if state == "out_of_scope":
                out_of_scope.append((name, slot))
    return totals, per_slot, out_of_scope


def _options() -> dict:
    """Champion options, split by who can answer them.

    ``in_fight`` is the engine's remaining depth debt: a count of events
    the modelled fight already holds. ``pre_fight`` is state the champion
    arrived with, which no engine derives. ``to_review`` is a counting
    option whose label says neither, and it is reported rather than
    assigned, because a silent guess here is exactly the overstatement
    this split exists to avoid.
    """
    total = 0
    buckets: dict[str, list[tuple[str, str, str]]] = {
        "in_fight": [],
        "blocked": [],
        "stack_levels": [],
        "full_by_default": [],
        "derived_default": [],
        "pre_fight": [],
        "to_review": [],
    }
    for name in sorted(_CHAMPION_MODULES):
        for option in get_champion_options_meta(name).get("options") or ():
            total += 1
            key = str(option.get("key", ""))
            label = str(option.get("label", ""))
            if not any(word in key for word in _COUNT_WORDS):
                continue
            lowered = label.lower()
            if key in _ENEMY_OR_POSITIONAL or f"{key}:{name}" in _ENEMY_OR_POSITIONAL:
                buckets["pre_fight"].append((name, key, label))
                continue
            if f"{key}:{name}" in _CLOCKLESS_ONLY:
                buckets["derived_default"].append((name, key, label))
                continue
            if key in _CARRIED_STACKS or f"{key}:{name}" in _CARRIED_STACKS:
                buckets["pre_fight"].append((name, key, label))
                continue
            if key in _BLOCK_LISTS:
                buckets["pre_fight"].append((name, key, label))
                continue
            if key in _IN_FIGHT_STACK_LEVELS:
                buckets["stack_levels"].append((name, key, label))
                continue
            blocked = _BLOCKED_ON_DATA.get(f"{key}:{name}")
            if blocked is not None:
                buckets["blocked"].append((name, key, blocked))
                continue
            default = option.get("default")
            maximum = option.get("max")
            minimum = option.get("min")
            whole = (
                isinstance(default, (int, float))
                and default == maximum
                and maximum != minimum
            )
            if key in _IN_FIGHT_KEYS:
                # Three readings, and only the last is debt. A default that
                # already derives is an OVERRIDE. A default at the top of the
                # range prices the whole sourced thing and the option only
                # removes from it (an interrupted channel). A default below
                # that prices less than the cache states until someone
                # answers, which is the shape that silently under-counts.
                if any(word in lowered for word in ("default", "derive", "unset")):
                    bucket = "derived_default"
                elif whole:
                    bucket = "full_by_default"
                else:
                    bucket = "in_fight"
            elif any(phrase in lowered for phrase in _PRE_FIGHT_PHRASES):
                bucket = "pre_fight"
            else:
                bucket = "to_review"
            buckets[bucket].append((name, key, label))
    return {"total": total, **buckets}


def _census() -> dict:
    path = ROOT / "docs" / "coverage-census.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _residue() -> dict:
    path = ROOT / "docs" / "coverage-residue.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _backlog_rows() -> int:
    """Open rows in the surface-area backlog, which is a table of one each."""
    text = (ROOT / "docs" / "surface-area-backlog.md").read_text(encoding="utf-8")
    return sum(
        1
        for line in text.splitlines()
        if line.startswith("| ") and not line.startswith("| # ") and "---" not in line
    )


def _swing_frontier() -> int:
    """Rows on the swing-stream audit's pinned frontier."""
    import swing_stream_audit  # noqa: PLC0415  pylint: disable=import-outside-toplevel

    return len(swing_stream_audit.FRONTIER)


def measure() -> dict:
    """Every number the page states, measured in one pass."""
    totals, per_slot, out_of_scope = _champion_slots()
    options = _options()
    census = _census()
    return {
        "champions": {
            "modules": len(_CHAMPION_MODULES),
            "slots": dict(totals),
            "per_slot": {slot: dict(per_slot[slot]) for slot in SLOTS},
            "out_of_scope": out_of_scope,
        },
        "items": {
            "registry_entries": len(item_effects.ITEM_EFFECTS),
            "swept": census["items_swept"],
            "coarse_pairs": census["counts"]["item_pair_coarse"],
            "pair_failures": census["counts"]["item_pair_failures"],
        },
        "runes": {
            "compiled": len(rune_effects._COMPILERS),
            # The census records the NAMES; the page states how many.
            "keystones_compiled": len(census["keystones"]["compiled"]),
            "keystones_unmodeled": len(census["keystones"]["unmodeled"]),
        },
        "axes": options,
        "frontiers": {
            "census_total": census["counts"]["total"],
            "residue_rows": len(_residue()["acknowledged"]),
            "backlog_rows": _backlog_rows(),
            "swing_frontier": _swing_frontier(),
        },
    }


def _percent(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "n/a"


def render(data: dict) -> str:
    """The page, written from the measurement and from nothing else."""
    champions = data["champions"]
    slots = champions["slots"]
    slot_total = sum(slots.values())
    modeled = slots.get("modeled", 0)
    no_damage = slots.get("no_damage", 0)
    out_of_scope = slots.get("out_of_scope", 0)
    axes = data["axes"]
    items = data["items"]
    runes = data["runes"]
    frontiers = data["frontiers"]

    lines = [
        "# Coverage status",
        "",
        "How much of the game the calculator models, measured on every axis at",
        "once. Every number here is written by `scripts/coverage_status.py` from",
        "the repo's own receipts and a live scan of the registered modules, and",
        "`--check` is a gate, so this page cannot drift from the tree.",
        "",
        "```bash",
        "python scripts/coverage_status.py --check",
        "```",
        "",
        "## The short answer",
        "",
        f"| Axis | Covered | Of |",
        "|---|---|---|",
        f"| Champion slots priced or stateful | {modeled} | {slot_total} "
        f"({_percent(modeled, slot_total)}) |",
        f"| Champion slots with nothing left to price | {no_damage} | {slot_total} "
        f"({_percent(no_damage, slot_total)}) |",
        f"| Champion slots the engine has no axis for | {out_of_scope} | {slot_total} "
        f"({_percent(out_of_scope, slot_total)}) |",
        f"| Runes compiled | {runes['compiled']} | every selectable rune |",
        f"| Keystones compiled | {runes['keystones_compiled']} | "
        f"{runes['keystones_compiled'] + runes['keystones_unmodeled']} |",
        f"| Items swept clean by the census | {items['swept'] - items['coarse_pairs']} | "
        f"{items['swept']} |",
        "",
        "A slot is `modeled` when it carries a priced row or a state row the engine",
        "consumes, `no_damage` when it is emitted and has nothing left to price, and",
        "`out_of_scope` when the engine has no axis for it at all and the module's",
        "own docstring says so.",
        "",
        "## Champions, slot by slot",
        "",
        f"{champions['modules']} named modules, which is every champion the cache",
        "holds. Unknown names fail closed: there is no generic parser.",
        "",
        "| Slot | modeled | no_damage | out_of_scope |",
        "|---|---|---|---|",
    ]
    for slot in SLOTS:
        row = champions["per_slot"][slot]
        lines.append(
            f"| {slot} | {row.get('modeled', 0)} | {row.get('no_damage', 0)} | "
            f"{row.get('out_of_scope', 0)} |"
        )
    lines += [
        "",
        f"The {out_of_scope} slots with no engine axis at all:",
        "",
        "| Champion | Slot |",
        "|---|---|",
    ]
    for name, slot in champions["out_of_scope"]:
        lines.append(f"| {name} | {slot} |")

    lines += [
        "",
        "## Depth: what the engine still asks the user",
        "",
        "A calculator is only as deep as the questions it answers for itself, so",
        "this is the number to steer by. Of",
        f"{axes['total']} champion options, {len(axes['in_fight'])} ask for a count of",
        "something that happens INSIDE the modelled fight: how many procs landed,",
        "how many ticks a channel took, how many attacks a pet made. Each of those",
        "is a derivation the engine could do from the cast plan and the swing",
        "schedule, the way Rumble's Heat now is",
        "(`fight/rotation/cast_resource_lockout.py`), and each retired one removes",
        "a way to get a wrong answer by leaving a default alone.",
        "",
        f"A further {len(axes['full_by_default'])} default to the whole sourced thing —",
        "a channel's every tick, a clip's every shot — so the option only removes",
        f"from a complete reading, and {len(axes['derived_default'])} derive their",
        "default outright and take an override.",
        f"{len(axes['pre_fight'])} are facts no engine holds: state the champion",
        "arrived with (stacks farmed over a game, souls collected) and facts about",
        "the ENEMY or about where the champion stood (how many attacks an evasion",
        "dodged, how many swings landed from behind). Asking for those is correct.",
        f"{len(axes['to_review'])} carry a label that says neither and need a reading.",
        "",
        "| Bucket | Options | Who can answer |",
        "|---|---|---|",
        f"| In-fight counts, still asked | {len(axes['in_fight'])} | the engine, once each is derived |",
        f"| In-fight counts, blocked on data | {len(axes['blocked'])} | nobody, until the missing number is sourced |",
        f"| In-fight STACK LEVELS | {len(axes['stack_levels'])} | the engine, once a stack timeline reaches the cast |",
        f"| In-fight counts, full by default | {len(axes['full_by_default'])} | already complete; the option removes |",
        f"| In-fight counts, derived default | {len(axes['derived_default'])} | the engine; the option is an override |",
        f"| Pre-fight state | {len(axes['pre_fight'])} | the player, permanently |",
        f"| Unreviewed | {len(axes['to_review'])} | undecided; read the label |",
        f"| Not a count at all | {axes['total'] - sum(len(axes[bucket]) for bucket in ('in_fight', 'blocked', 'stack_levels', 'full_by_default', 'derived_default', 'pre_fight', 'to_review'))} | the player: a variant, a target, a cone's reach |",
        "",
    ]
    if axes["in_fight"]:
        lines += [
            "The in-fight counts that price less than the cache states until",
            "someone answers them, which are the work:",
            "",
            "| Champion | Option | Asks for |",
            "|---|---|---|",
        ]
        for name, key, label in axes["in_fight"]:
            lines.append(f"| {name} | `{key}` | {label} |")
    else:
        lines += [
            "That first row is at zero. Every count of something inside the",
            "modelled fight is answered by the fight, and what remains below it",
            "is either blocked on a number no source here states, or a fact the",
            "engine has no standing to invent.",
        ]

    if axes["stack_levels"]:
        lines += [
            "",
            "Stack LEVELS the fight builds and a cast reads. Deriving these means",
            "walking a stack timeline into the cast pricing, not counting procs,",
            "so they are the next campaign and are reported apart from the row",
            "above rather than folded into it:",
            "",
            "| Champion | Option | Asks for |",
            "|---|---|---|",
        ]
        for name, key, label in axes["stack_levels"]:
            lines.append(f"| {name} | `{key}` | {label} |")

    if axes["blocked"]:
        lines += [
            "",
            "Counts the fight could walk if one missing number were sourced:",
            "",
            "| Champion | Option | Missing |",
            "|---|---|---|",
        ]
        for name, key, missing in axes["blocked"]:
            lines.append(f"| {name} | `{key}` | {missing} |")

    if axes["to_review"]:
        lines += [
            "",
            "Counting options whose label states neither reading:",
            "",
            "| Champion | Option | Asks for |",
            "|---|---|---|",
        ]
        for name, key, label in axes["to_review"]:
            lines.append(f"| {name} | `{key}` | {label} |")

    lines += [
        "",
        "## Items and runes",
        "",
        f"- **{items['registry_entries']} items** carry typed effect entries in",
        "  `item_effects.ITEM_EFFECTS`. Every number comes from the cache through a",
        "  typed accessor with no literal fallback, and a missing key raises.",
        f"- The census sweeps **{items['swept']} items** against every registered",
        f"  champion. {items['pair_failures']} pairs fail; {items['coarse_pairs']} price",
        "  coarsely, all of them one acknowledged mechanic",
        f"  (`docs/coverage-residue.json`, {frontiers['residue_rows']} rows).",
        f"- **{runes['compiled']} runes** compile, including all",
        f"  {runes['keystones_compiled']} keystones, with",
        f"  {runes['keystones_unmodeled']} unmodeled. Only compiled runes are",
        "  selectable; everything else fails closed.",
        "",
        "## Where the remaining work is written down",
        "",
        "Nothing unmodelled is silent. Each of these is a receipt with a reason per",
        "row, and each has a gate that fails when a row appears without one.",
        "",
        "| Receipt | Rows | What it holds |",
        "|---|---|---|",
        f"| `docs/coverage-census.json` | {frontiers['census_total']} | champion and item"
        " pairs that price coarsely or refuse |",
        f"| `docs/coverage-residue.json` | {frontiers['residue_rows']} | frontier entries"
        " that cannot close without inventing data |",
        f"| `docs/surface-area-backlog.md` | {frontiers['backlog_rows']} | everything the"
        " surface-area campaigns surfaced and did not close |",
        f"| `scripts/swing_stream_audit.py` | {frontiers['swing_frontier']} | cached"
        " per-attack riders that do not publish a swing key |",
        "",
        "## What 100% would mean, and what it would not",
        "",
        "Slot coverage is close to total, so it is the wrong number to steer by.",
        "The honest frontier is depth, and it has three parts:",
        "",
        "1. **Counts the engine still asks for** — the table above. Each is a",
        "   derivation the fight could do, and each retired one removes a way for a",
        "   reader to get a wrong answer by leaving a default alone.",
        "2. **Axes the engine does not have** — a summon that fights on its own, a",
        "   stat conversion with no channel, a persistent object with a field cap.",
        "   These need new engine shapes, not more packets.",
        "3. **Approximations that are stated rather than exact** — a fight-averaged",
        "   attack-speed share, a resistance bound once per ability row, a charge",
        "   stock capped at one where no cached field states the real cap. Each is",
        "   named where it is made.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render(measure())
    if args.write:
        TARGET.write_text(text, encoding="utf-8")
        print(f"wrote {TARGET.relative_to(ROOT)}")
        return 0
    current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    if current != text:
        print("docs/coverage-status.md is stale; run --write")
        return 1
    print("docs/coverage-status.md matches the tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
