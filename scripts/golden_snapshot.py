"""Golden snapshot harness for the July 2026 refactor campaign (Phase 0).

Captures the numeric behavior of the full calculation pipeline (stats ->
ability parsing -> fight damage) across every champion and item, so later
refactor phases can prove numeric equivalence. Fight scenarios enter through
``pipeline.run_fight`` just like the app and optimizer, with
``deterministic=True``. Fights cover both a
one-rotation burst (no autos) and, for registered champions, a sustained
scenario with auto_attack_uptime=1.0 so auto-attack and on-hit item paths
(Statikk, Voltaic, BorK, Kraken, Rageblade phantom hits, spellblade,
energized procs, Vayne W) are locked too; the item sweep runs with
auto_attack_uptime=1.0 for the same reason.

Compare contract: every float is rounded to 2 decimals before writing, and
``compare`` recomputes the snapshot with identical rounding — so "equal to
2 decimals" is plain equality.  ``compare`` prints each differing path as
``path: old -> new`` and exits 1 on any difference, 0 when identical.  The
provenance keys in ``COMPARE_EXCLUDED_PROVENANCE`` are excluded from the
comparison (they change per commit or per data pull); nothing else is.
Exceptions raised by the pipeline are captured as {"error": "Type: msg"}
snapshot values — a refactor turning a crash into a number (or vice versa)
shows up as a diff.

Two baselines, two jurisdictions (runbook R-11).  ``capture``/``compare``
own the **pair engine**: every scenario enters through ``pipeline.run_fight``,
so this snapshot proves no pair-engine leak and nothing about the coupled
roster walk.  ``capture-coupled``/``compare`` own the **roster path**: those
scenarios enter through ``scenario.resolve_scenario`` and
``participant_timeline.build_participant_timeline``, which is where item
support packets, cross-participant damage modifiers and the coupled ledger
live.  A slice touching those cites the coupled baseline, never this one.

Usage:
    python scripts/golden_snapshot.py capture <outfile.json>
    python scripts/golden_snapshot.py compare <baseline.json> [--report <path>]
    python scripts/golden_snapshot.py capture-coupled <outfile.json> [--exact]
    python scripts/golden_snapshot.py fingerprint <snapshot.json>
"""

import argparse
import ast
import copy
import inspect
import json
import math
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.source_receipt import cache_patch
from src.calculator.champions import (
    parse_champion_abilities,
    registered_champion_names,
)
from src.calculator import damage
from src.calculator.data_fetcher import fetch_champion_data, fetch_item_data
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.item_behavior import (
    Basis,
    DefenseField,
    EmpoweredHitRule,
    PartAmpRule,
    PeriodicRule,
    TemporaryLethality,
    ThresholdDefenseRule,
)
from src.calculator.item_behavior_catalog import (
    DELTA_AMP_UNMIGRATED_TAGS,
    behavior_rules,
    registry_entries,
    rule_owners,
)
from src.calculator.item_support_effects import producer_item

# The sys.path bootstrap above forces every first-party import below it;
# this one line carries the disable rather than the whole block.
from src.calculator.trigger_stream import (  # pylint: disable=wrong-import-position
    CAPABILITIES,
    cross_participant_packet_source,
)
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams, ONE_ROTATION_DURATION, run_fight
from src.calculator.public_response import serialize_fight_result
from src.calculator.scenario import parse_scenario_request, resolve_scenario
from src.calculator.stats import calculate_total_stats

FINGERPRINTS_PATH = REPO_ROOT / "docs" / "receipts" / "campaign-fingerprints.json"
SCHEDULE_RECEIPT_PATH = (
    REPO_ROOT / "docs" / "receipts" / "receipt-walk-retirement-schedule.json"
)

# Metadata keys ``compare`` ignores.  ``git_head`` moves every commit, the
# ``src`` tree sha moves on a comment-only edit, and the two fetch stamps move
# on every data pull — without one named home for them, "zero diffs on a pure
# refactor" is false for every commit and the strongest gate in the campaign
# gets routinely waived (R-14).
COMPARE_EXCLUDED_PROVENANCE: frozenset[str] = frozenset(
    {"git_head", "src_tree_sha", "champions_fetched_at", "items_fetched_at"}
)

# ``fingerprint``'s domain is the numeric sections; ``metadata`` is excluded
# whole, because it carries exactly the provenance above plus counts derived
# from the sections themselves — counting it makes the published figure wrong
# on its first run.
FINGERPRINT_EXCLUDED_SECTIONS: frozenset[str] = frozenset({"metadata"})

STAT_LEVELS = (1, 11, 18)
ABILITY_LEVEL = 11
FIGHT_LEVELS = (11, 18)
PHYSICAL_BUILD = ["Kraken Slayer", "Infinity Edge", "Lord Dominik's Regards"]
MAGIC_BUILD = ["Luden's Echo", "Shadowflame", "Rabadon's Deathcap"]
# Spellblade + crit + attack speed: the only sweep build that exercises
# the spellblade proc path and champion riders on it (Corki's Hextech
# Munitions true damage). Without it those live on unit tests alone —
# the blind spot that hid the timed-burn bug.
SPELLBLADE_BUILD = ["Trinity Force", "Infinity Edge", "Berserker's Greaves"]
# The item sweep's timed arm. Windowed and stacking item mechanics — Eclipse's
# two-stacks-in-two-seconds pairing, the Muramana/Bastionbreaker proc walkers,
# burn and periodic cadence, threshold-shield expiry, stack counters that ramp
# — only differ across fight LENGTH and cast DENSITY, and the one-rotation arm
# holds both fixed (one 5s rotation, two dense-cast champions). That is why
# wave 1F re-priced 237 Eclipse fights and landed a byte-identical baseline.
# Ziggs casts sparsely enough that a second stack is not always waiting when a
# cooldown expires. Both lengths were chosen against that re-price, not by
# taste: on the grid 5/8/10/12/15/20/25/30 at this sweep's own level, 1F moved
# Eclipse at 12, 20, 25 and 30 and at no shorter length. 12s is the shortest
# that sees it (and the shortest that authors Hullbreaker's on-hit at all);
# 30s outlives every cooldown and window in the catalogue, is the only length
# that authors Voltaic Cyclosword's once-per-fight row, and is where 1F's
# Eclipse delta is largest.
SWEEP_TIMED_CHAMPION = "Ziggs"
SWEEP_TIMED_DURATIONS = (12.0, 30.0)
# Deliberately non-default regression scenario; product defaults live in pipeline.py.
SNAPSHOT_TARGET_HEALTH = 2000.0
SNAPSHOT_TARGET_ARMOR = 50.0
SNAPSHOT_TARGET_MR = 40.0


def _rounded(value):
    """Recursively round floats to 2 decimals and normalize containers."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, dict):
        return {str(k): _rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_rounded(v) for v in value), key=str)
    return repr(value)


def _error_entry(exc):
    return {"error": f"{type(exc).__name__}: {exc}"}


def _default_target_stats():
    return {
        "target_max_health": SNAPSHOT_TARGET_HEALTH,
        "target_current_health": SNAPSHOT_TARGET_HEALTH,
        "target_missing_health": 0.0,
    }


def _parse_abilities_fresh(champion_data, level, items):
    """Mirror the app/optimizer pipeline up through parse_abilities.

    Deep-copies inputs (each web request re-reads data from disk, so every
    call sees fresh dicts) and returns (stats, ability_damages).
    """
    data = copy.deepcopy(champion_data)
    stats = calculate_total_stats(data, level, items)
    abilities = parse_champion_abilities(
        data,
        level,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats=_default_target_stats(),
        champion_options=None,
    )
    return stats, abilities


def _run_fight(
    champion_data,
    level,
    items,
    auto_attack_uptime=0.0,
    one_rotation=True,
    duration=ONE_ROTATION_DURATION,
):
    """Fight at fixed regression target stats, mirroring _evaluate_build.

    Default is a one-rotation burst with no autos. Pass
    auto_attack_uptime=1.0 (and one_rotation=False for the sustained
    scenario) to exercise auto-attack and on-hit item paths, and
    ``duration`` for the timed arm that lets a fight outlive an item's
    cooldown, window or stack cadence.
    """
    items = copy.deepcopy(items)
    params = FightParams(
        target_health=SNAPSHOT_TARGET_HEALTH,
        target_bonus_health=0.0,
        target_armor=SNAPSHOT_TARGET_ARMOR,
        target_magic_resistance=SNAPSHOT_TARGET_MR,
        fight_duration_seconds=duration,
        auto_attack_uptime=auto_attack_uptime,
        one_rotation=one_rotation,
        include_actives=True,
        cast_order=None,
        auto_attacks_only=False,
        ability_ranks=None,
        champion_options=None,
        deterministic=True,
    )
    return run_fight(champion_data, level, items, params)


def _fight_summary(result):
    summary = {
        "total_damage": round(float(result.get("total_damage", 0.0)), 2),
        "breakdown_totals": {
            key: round(float(entry.get("total_damage", 0.0)), 2)
            for key, entry in result.get("breakdown", {}).items()
        },
    }
    if "dps" in result:
        summary["dps"] = round(float(result["dps"]), 2)
    return summary


def snapshot_champion_baselines(champions):
    """Section 1: stats at levels 1/11/18 and level-11 abilities, all champions."""
    out = {}
    for key in sorted(champions):
        data = champions[key]
        entry = {"stats": {}}
        for level in STAT_LEVELS:
            try:
                entry["stats"][str(level)] = _rounded(
                    calculate_total_stats(copy.deepcopy(data), level, [])
                )
            except Exception as exc:
                entry["stats"][str(level)] = _error_entry(exc)
        try:
            _, abilities = _parse_abilities_fresh(data, ABILITY_LEVEL, [])
            entry[f"abilities_level_{ABILITY_LEVEL}"] = _rounded(abilities)
        except Exception as exc:
            entry[f"abilities_level_{ABILITY_LEVEL}"] = _error_entry(exc)
        out[key] = entry
    return out


def _resolve_build(requested_names, items_by_name, substitutions):
    """Resolve build item names against cached data, logging missing names."""
    build = []
    for name in requested_names:
        used = name if name in items_by_name else None
        if used != name:
            substitutions.append({"requested": name, "used": used})
        if used is not None:
            build.append(items_by_name[used])
    return build


def snapshot_registered_fights(champions, items_by_name, substitutions):
    """Section 2: fights for every registered champion, 4 builds x 2 levels.

    Each level holds the original one-rotation entries under the build keys,
    plus a "sustained" sibling (auto_attack_uptime=1.0, one_rotation=False,
    5s) that exercises auto-attack and on-hit item paths.
    """
    builds = {
        "no_items": [],
        "physical_build": _resolve_build(PHYSICAL_BUILD, items_by_name, substitutions),
        "magic_build": _resolve_build(MAGIC_BUILD, items_by_name, substitutions),
        "spellblade_build": _resolve_build(
            SPELLBLADE_BUILD, items_by_name, substitutions
        ),
    }
    by_display_name = {data.get("name"): data for data in champions.values()}
    out = {}
    for display_name in registered_champion_names():
        levels = {}
        for level in FIGHT_LEVELS:
            fights = {"sustained": {}}
            for build_name, build_items in builds.items():
                champion_data = by_display_name[display_name]
                try:
                    fights[build_name] = _fight_summary(
                        _run_fight(champion_data, level, build_items)
                    )
                except Exception as exc:
                    fights[build_name] = _error_entry(exc)
                try:
                    fights["sustained"][build_name] = _fight_summary(
                        _run_fight(
                            champion_data,
                            level,
                            build_items,
                            auto_attack_uptime=1.0,
                            one_rotation=False,
                        )
                    )
                except Exception as exc:
                    fights["sustained"][build_name] = _error_entry(exc)
            levels[str(level)] = fights
        out[display_name] = levels
    return out


def _sweep_entry(champion_data, item, **fight_kwargs):
    """One item's sweep reading: its total and the rows it authored."""
    try:
        result = _run_fight(
            champion_data, ABILITY_LEVEL, [item], auto_attack_uptime=1.0, **fight_kwargs
        )
    except Exception as exc:
        return _error_entry(exc)
    return {
        "total_damage": round(float(result.get("total_damage", 0.0)), 2),
        "breakdown_keys": sorted(result.get("breakdown", {})),
    }


def snapshot_item_sweep(champions, items):
    """Section 3: every item, alone, at level 11, in two arms.

    The one-rotation arm runs Vayne and Ahri with auto_attack_uptime=1.0 —
    most item effects (on-hit, energized, spellblade) only fire with autos,
    and it locks per-item behavior at a fixed 5s rotation.

    The timed arm runs ``SWEEP_TIMED_CHAMPION`` at each of
    ``SWEEP_TIMED_DURATIONS``, because a single rotation length on two
    dense-cast champions cannot see any mechanic whose answer depends on
    how long the fight ran or how sparsely it was cast — the blind spot
    that made wave 1F's Eclipse re-price invisible here. Both arms sweep
    EVERY item rather than a named windowed subset: a hand-kept list of
    "items with a cadence" drifts away from the catalogue exactly like a
    hand-kept availability list would.
    """
    by_display_name = {data.get("name"): data for data in champions.values()}
    sweep_champions = [
        ("ahri", by_display_name["Ahri"]),
        ("vayne", by_display_name["Vayne"]),
    ]
    timed_champion = by_display_name[SWEEP_TIMED_CHAMPION]
    timed_label = SWEEP_TIMED_CHAMPION.lower().replace("'", "").replace(" ", "_")
    out = {}
    for item in sorted(items.values(), key=lambda i: i.get("name", "")):
        entry = {}
        for label, champion_data in sweep_champions:
            entry[label] = _sweep_entry(champion_data, item)
        for duration in SWEEP_TIMED_DURATIONS:
            entry[f"{timed_label}_{duration:g}s"] = _sweep_entry(
                timed_champion, item, one_rotation=False, duration=duration
            )
        out[item.get("name", "")] = entry
    return out


def _git(*args):
    """One git command's stdout, or "" when git rejects the request."""
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _meta_fetched_at(filename):
    meta_path = REPO_ROOT / "data" / f".{filename}.meta"
    return json.loads(meta_path.read_text(encoding="utf-8")).get("fetched_at")


def snapshot_provenance():
    """Exactly the keys ``compare`` excludes — one producer, one exclusion set."""
    return {
        "git_head": _git("rev-parse", "HEAD"),
        "src_tree_sha": _git("rev-parse", "HEAD:src"),
        "champions_fetched_at": _meta_fetched_at("champions.json"),
        "items_fetched_at": _meta_fetched_at("items.json"),
    }


def snapshot_metadata(champions, items, substitutions, sweep_error_count, sections):
    """Section 4: patch, provenance, counts, and the shape fingerprint.

    The fingerprint block is computed by ``fingerprint_counts`` over the
    numeric sections — the same function ``fingerprint`` prints — so the
    receipt figure and every consumer's figure are one number by
    construction.
    """
    return {
        "patch_last_changed_max": cache_patch(champions),
        "snapshot_kind": PAIR_SNAPSHOT_KIND,
        **snapshot_provenance(),
        "champion_count": len(champions),
        "registered_champion_count": len(registered_champion_names()),
        "item_count": len(items),
        "item_sweep_error_count": sweep_error_count,
        "build_substitutions": substitutions,
        "fingerprint": fingerprint_counts(sections),
    }


def build_snapshot():
    """Compute the full golden snapshot as a plain-JSON-serializable dict."""
    champions = fetch_champion_data()
    items = fetch_item_data()
    items_by_name = {data["name"]: data for data in items.values()}
    substitutions = []
    item_sweep = snapshot_item_sweep(champions, items)
    sweep_errors = sum(
        1 for entry in item_sweep.values() for side in entry.values() if "error" in side
    )
    sections = {
        "champion_baselines": snapshot_champion_baselines(champions),
        "registered_champion_fights": snapshot_registered_fights(
            champions, items_by_name, substitutions
        ),
        "item_sweep": item_sweep,
    }
    return {
        **sections,
        "metadata": snapshot_metadata(
            champions, items, substitutions, sweep_errors, sections
        ),
    }


# ---------------------------------------------------------------------------
# Fingerprint — the one home of every golden shape figure
# ---------------------------------------------------------------------------

PAIR_SNAPSHOT_KIND = "pair"
COUPLED_SNAPSHOT_KIND = "coupled"

# The shape figures ``fingerprint`` publishes.  ``metadata['fingerprint']``
# carries exactly these, from this same function.
FINGERPRINT_COUNT_FIELDS = ("sections", "entries", "leaves", "numeric_leaves")


def numeric_sections(snapshot):
    """Every top-level section ``fingerprint`` counts — ``metadata`` excluded."""
    return {
        key: value
        for key, value in snapshot.items()
        if key not in FINGERPRINT_EXCLUDED_SECTIONS
    }


def _count_leaves(value):
    """(leaves, numeric_leaves) under one node; a leaf is any non-container."""
    if isinstance(value, Mapping):
        totals = [_count_leaves(item) for item in value.values()]
    elif isinstance(value, (list, tuple)):
        totals = [_count_leaves(item) for item in value]
    else:
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        return 1, int(numeric)
    return sum(pair[0] for pair in totals), sum(pair[1] for pair in totals)


def fingerprint_counts(sections):
    """The shape figures for one set of numeric sections."""
    leaves, numeric = _count_leaves(sections)
    return {
        "sections": ",".join(sorted(sections)),
        "entries": sum(len(value) for value in sections.values()),
        "leaves": leaves,
        "numeric_leaves": numeric,
    }


def fingerprint(snapshot):
    """The leaf/entry counts plus ``src_tree_sha`` — the one source of those figures.

    Domain: the numeric sections only.  ``metadata`` is excluded, because it
    holds the provenance keys ``compare`` already pops plus the counts this
    function produced; counting them makes the published figure wrong on its
    first run.  ``excluded_metadata`` reports which provenance keys the
    snapshot actually carries, so a test can assert that set is exactly
    ``COMPARE_EXCLUDED_PROVENANCE`` and the two exclusions cannot drift apart.
    """
    metadata = snapshot.get("metadata", {})
    return {
        **fingerprint_counts(numeric_sections(snapshot)),
        "snapshot_kind": str(metadata.get("snapshot_kind", PAIR_SNAPSHOT_KIND)),
        "excluded_metadata": ",".join(
            sorted(set(metadata) & COMPARE_EXCLUDED_PROVENANCE)
        ),
        "src_tree_sha": str(metadata.get("src_tree_sha", "")),
    }


# ---------------------------------------------------------------------------
# Classified diffs — R-15's triage, not an eyeball
# ---------------------------------------------------------------------------

Transition = Literal[
    "value",
    "zero_to_value",
    "value_to_zero",
    "value_to_error",
    "error_to_value",
    "absent_to_value",
    "value_to_absent",
    "text_change",
]

# A leaf whose path names damage: the sections differ between the two
# baselines, so the rule is stated over the path rather than the section.
DAMAGE_LEAF_TOKENS = ("damage", "dps", "breakdown_totals")

# R-15's thresholds.
INVESTIGATION_PERCENT = 10.0
INVESTIGATION_DAMAGE_ABS_DELTA = 1.0
# A slice owes an investigator on its largest-|abs_delta| leaf per scenario
# once its differing-leaf count clears this fraction of the numeric leaves.
INVESTIGATION_LEAF_RATIO = 0.01


class _Absent:  # pylint: disable=too-few-public-methods
    """The sentinel a missing key compares as; never a snapshot value."""

    def __repr__(self):
        return "<absent>"


ABSENT = _Absent()

# The field a snapshot list member carries when it has a stable identity of
# its own: the event's origin — the attacker or holder id — plus that
# origin's ordinal, which is what ``program.identity.event_id_text`` writes
# and what nothing about a *list position* can change.  Members of a list
# every one of whose members carries this are paired by it; see
# ``_identity_index``.
IDENTITY_FIELD = "event_id"

# The same identity spelled apart instead of pre-joined: an origin and that
# origin's own ordinal.  ``cast_timeline`` is the live case — its rows carry
# ``slot`` and a per-slot ``ordinal``, so ``Q#2`` names the same cast however
# many rows precede it — and it is the list whose insertion at Phase 0B's C6
# re-addressed seven later rows into three oracle briefs about casts nobody
# had disputed.  One concept, two spellings; nothing here is a second notion
# of identity.
ORIGIN_FIELD = "slot"
ORDINAL_FIELD = "ordinal"


@dataclass(frozen=True, slots=True)
class LeafDiff:
    """One differing golden leaf, classified for triage.

    ``identity`` is the ``event_id`` of the record the leaf sits inside when
    that record has one, so a report — and the investigator brief built from
    it — names *which* event it is talking about rather than only which
    ordinal the baseline happened to store it at.
    """

    path: str
    section: str
    old: float | str | None
    new: float | str | None
    abs_delta: float
    percent: float
    transition: Transition
    identity: str | None = None


def _is_error(value):
    return isinstance(value, Mapping) and set(value) == {"error"}


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _classify(old, new):
    """(transition, abs_delta, percent) for one pair of differing leaf values."""
    if old is ABSENT:
        return "absent_to_value", 0.0, math.inf
    if new is ABSENT:
        return "value_to_absent", 0.0, math.inf
    if _is_error(new):
        return "value_to_error", 0.0, math.inf
    if _is_error(old):
        return "error_to_value", 0.0, math.inf
    if _numeric(old) and _numeric(new):
        delta = abs(float(new) - float(old))
        if float(old) == 0.0:
            return "zero_to_value", delta, math.inf
        if float(new) == 0.0:
            return "value_to_zero", delta, -100.0
        return "value", delta, (float(new) - float(old)) / abs(float(old)) * 100.0
    return "text_change", 0.0, math.inf


def _identity(member):
    """One record's stable identity, or ``None`` when it has none.

    Two spellings of the one notion — an origin and that origin's ordinal.
    ``IDENTITY_FIELD`` carries it pre-joined; ``ORIGIN_FIELD`` beside
    ``ORDINAL_FIELD`` carries it apart, which is how a cast row spells the
    same fact.  A record's identity is never its *value*, so pairing by it
    can only ever re-address a member — it can never re-spell a changed
    field as a removal.
    """
    if isinstance(member, Mapping):
        value = member.get(IDENTITY_FIELD)
        if isinstance(value, str) and value:
            return value
        origin = member.get(ORIGIN_FIELD)
        ordinal = member.get(ORDINAL_FIELD)
        if (
            isinstance(origin, str)
            and origin
            and isinstance(ordinal, int)
            and not isinstance(ordinal, bool)
        ):
            return f"{origin}#{ordinal}"
    return None


def _value_identity(member):
    """A bare string's identity, which is the string — or ``None``.

    A list of bare strings holds members with no fields to be identified by,
    so the member *is* its address; the rotation record's ``setup``,
    ``consume`` and ``sources`` lists are the live case.  Numbers are
    deliberately excluded: a float's identity being its value would re-spell
    every numeric move as a removal plus an addition and throw away the
    ``percent`` and ``abs_delta`` that R-15 grades a value change by.
    """
    return member if isinstance(member, str) and member else None


def _index(members, identity_of):
    """``{identity: position}`` for a list whose every member is identified.

    ``None`` when any member carries no identity or two members share one.
    Partial or ambiguous indexing is refused rather than half-applied: a list
    matched by identity where it can be and by position where it cannot is
    exactly the substitution this indexing exists to end.
    """
    index = {}
    for position, member in enumerate(members):
        identity = identity_of(member)
        if identity is None or identity in index:
            return None
        index[identity] = position
    return index


def _identity_index(members):
    """``{identity: position}`` keyed on the members' own record identities."""
    return _index(members, _identity)


def _identity_keyed_diffs(path, old, new, out):
    """Diff two identity-bearing lists by identity, never by list position.

    A member both sides hold is compared field by field under the
    *baseline's* index, so a leaf keeps the address every committed
    allowlist, receipt and oracle brief already spells.  A member only one
    side holds is **one membership transition** at the record —
    ``value_to_absent`` for a removal, ``absent_to_value`` for an addition,
    both already in R-15's closed transition set — instead of a run of
    manufactured value changes against whichever record the shift slid into
    its place.

    Two index attempts, in that order, and the second is guarded:

    * by **record identity**, which is never the member's value, so it is
      always the honest pairing where it succeeds;
    * failing that, and **only when the two lists differ in length**, by the
      members' own string values.  The guard is what keeps this from
      relaxing anything: equal-length string lists cannot have gained or
      lost a member, so positional pairing is already the right reading and
      a substitution there stays the single ``text_change`` it is.  Unequal
      lengths mean a member arrived or left, and positional pairing is then
      *guaranteed* to compare strings that were never each other.

    Returns False when neither indexing applies, leaving the caller to fall
    back to positional pairing.
    """
    old_index = _identity_index(old)
    new_index = _identity_index(new)
    if old_index is None or new_index is None:
        if len(old) == len(new):
            return False
        old_index = _index(old, _value_identity)
        new_index = _index(new, _value_identity)
    if old_index is None or new_index is None:
        return False
    for identity, position in old_index.items():
        member_path = f"{path}[{position}]"
        if identity in new_index:
            _leaf_diffs(
                member_path, old[position], new[new_index[identity]], out, identity
            )
        else:
            out.append(_leaf_diff(member_path, old[position], ABSENT, identity))
    for identity, position in new_index.items():
        if identity not in old_index:
            out.append(
                _leaf_diff(f"{path}[{position}]", ABSENT, new[position], identity)
            )
    return True


def _leaf_diffs(path, old, new, out, identity=None):
    """Collect one LeafDiff per differing leaf, recursing through containers."""
    if _is_error(old) != _is_error(new):
        out.append(_leaf_diff(path, old, new, identity))
        return
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        for key in sorted(set(old) | set(new)):
            _leaf_diffs(
                f"{path}/{key}",
                old.get(key, ABSENT),
                new.get(key, ABSENT),
                out,
                identity,
            )
        return
    if isinstance(old, list) and isinstance(new, list):
        if _identity_keyed_diffs(path, old, new, out):
            return
        for index in range(max(len(old), len(new))):
            _leaf_diffs(
                f"{path}[{index}]",
                old[index] if index < len(old) else ABSENT,
                new[index] if index < len(new) else ABSENT,
                out,
                identity,
            )
        return
    if old is ABSENT or new is ABSENT or old != new:
        # A container facing a scalar is a shape change, reported once at the
        # node rather than fanned out into leaves that have no counterpart.
        out.append(_leaf_diff(path, old, new, identity))


def _leaf_diff(path, old, new, identity=None):
    transition, abs_delta, percent = _classify(old, new)
    return LeafDiff(
        path=path,
        section=path.lstrip("/").split("/", 1)[0],
        old=None if old is ABSENT else _reportable(old),
        new=None if new is ABSENT else _reportable(new),
        abs_delta=abs_delta,
        percent=percent,
        transition=transition,
        identity=identity,
    )


def _reportable(value):
    """A JSON-safe rendering of one leaf value for the report."""
    if _numeric(value) or isinstance(value, str) or value is None:
        return value
    return _format_value(value)


def leaf_report(old, new):
    """Every difference as a LeafDiff, grouped by scenario, sorted by |percent|.

    List members that carry a record identity — an ``event_id``, or a
    ``slot`` beside that slot's ``ordinal`` — are paired by it and never by
    position, so a removal or an insertion is one membership transition
    rather than a run of value changes against the record the shift slid
    into its place (R-15).  A list of bare strings whose length changed is
    paired by the strings themselves, for the same reason and under the
    length guard in ``_identity_keyed_diffs``: such a member has no fields to
    be identified by, so its value is the only address it has.
    """
    diffs = []
    _leaf_diffs("", old, new, diffs)
    return tuple(
        sorted(
            diffs, key=lambda d: (d.section, -abs(d.percent), d.path, d.identity or "")
        )
    )


def qualifies_for_investigation(diff):
    """R-15's threshold — the one predicate that decides an investigator is owed."""
    if diff.transition != "value":
        return True
    if abs(diff.percent) > INVESTIGATION_PERCENT:
        return True
    return diff.abs_delta > INVESTIGATION_DAMAGE_ABS_DELTA and any(
        token in diff.path for token in DAMAGE_LEAF_TOKENS
    )


def receipt_numeric_leaves(kind):
    """The numeric-leaf denominator R-15's ratio clause reads from the receipt.

    Never a figure written in a document: the receipt is the sole home of
    every golden shape count, and this returns ``None`` when it has not been
    captured yet rather than substituting one.
    """
    if not FINGERPRINTS_PATH.exists():
        return None
    receipt = json.loads(FINGERPRINTS_PATH.read_text(encoding="utf-8"))
    block = receipt.get("golden" if kind == PAIR_SNAPSHOT_KIND else "coupled_golden")
    value = (block or {}).get("numeric_leaves")
    if isinstance(value, Mapping):
        value = value.get("value")
    return value if isinstance(value, int) else None


# ---------------------------------------------------------------------------
# The coupled roster baseline — the jurisdiction golden cannot see (R-11, R-12)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoupledScenario:
    """One roster request captured through the coupled path.

    ``score_mode`` selects the scoring subset (``include_receipt=False``),
    which is how the optimizer evaluates a candidate and the only way the
    snapshot reaches the *tuple* damage ledger; the receipt mode reaches the
    dict ledger.  Both ledger shapes are therefore covered by scenarios, not
    by assumption.
    """

    name: str
    request: Mapping[str, Any]
    score_mode: bool = False

    def equipped(self):
        """Every item name this scenario puts on any participant."""
        names = set()
        for loadout in (
            self.request,
            *self.request.get("enemies", ()),
            *self.request.get("allies", ()),
        ):
            names.update(str(name) for name in loadout.get("items", ()))
            if loadout.get("boots"):
                names.add(str(loadout["boots"]))
        return frozenset(names)


# The Syndra cast-order pin: one parameter set, three splinter counts.  The
# splinter count is load-bearing — Q's second charge arrives at 40 stacks and
# W's bonus true damage at 60 — so a pin without that axis is ambiguous.  This
# scenario definition is the ONE home of the parameter set; the totals live in
# the committed baseline, and every consumer runs the scenario by name and
# reads that file rather than retyping a figure.
SYNDRA_PIN_SPLINTERS = (39, 60, 120)
SYNDRA_PIN_ITEMS = (
    "Luden's Echo",
    "Shadowflame",
    "Banshee's Veil",
    "Zhonya's Hourglass",
    "Void Staff",
    "Mejai's Soulstealer",
)
# 600 ability power and 10 ability haste exactly, at level 18: the haste is
# what puts Q's recast at 5.0 s and W's at 7.273 s, and no covered build
# reaches 600 AP without Mejai's stack option carrying the last 65.
SYNDRA_PIN_ITEM_OPTIONS = {"Mejai's Soulstealer": {"glory_stacks": 13}}
SYNDRA_PIN_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
SYNDRA_CUSTOM_ORDER = ["Q", "W", "E", "R"]


def _syndra_pin_request(splinters, *, cast_order):
    """One Syndra pin request: level 18, 600 AP, 10 AH, 12 s, 10000 HP target.

    The ally carries the same request so the roster loadout's own cast-order
    validation is on the captured path too, not only the main champion's.
    """
    ally = {
        "champion": "Syndra",
        "level": 18,
        "items": [],
        "ability_ranks": dict(SYNDRA_PIN_RANKS),
        "champion_options": {"splinters": splinters},
        "ally_effects_enabled": True,
    }
    request = {
        "champion": "Syndra",
        "level": 18,
        "items": list(SYNDRA_PIN_ITEMS),
        "item_options": {
            item: dict(options) for item, options in SYNDRA_PIN_ITEM_OPTIONS.items()
        },
        "fight_mode": "time_based",
        "fight_duration": 12,
        "target_health": 10000,
        "target_armor": 0,
        "target_mr": 0,
        "ability_ranks": dict(SYNDRA_PIN_RANKS),
        "champion_options": {"splinters": splinters},
        "allies": [ally],
    }
    if cast_order is not None:
        request["cast_order"] = list(cast_order)
        ally["cast_order"] = list(cast_order)
    return request


def _syndra_pin_scenarios():
    """``syndra_custom_order`` and ``syndra_derived_order`` at each splinter count."""
    scenarios = []
    for splinters in SYNDRA_PIN_SPLINTERS:
        scenarios.append(
            CoupledScenario(
                f"syndra_custom_order_{splinters}",
                _syndra_pin_request(splinters, cast_order=SYNDRA_CUSTOM_ORDER),
            )
        )
        scenarios.append(
            CoupledScenario(
                f"syndra_derived_order_{splinters}",
                _syndra_pin_request(splinters, cast_order=None),
            )
        )
    return tuple(scenarios)


def _roster_request(champion, items, *, enemies, allies, enemy_cards=None, **extra):
    """A time-based roster request with the fields every scenario shares.

    ``enemy_cards`` equips a *defender*, keyed by champion name and carrying
    that card's own loadout fields — ``items``, ``boots``.  Two covering
    scenarios need one: the max-health reprice joins an attacker's
    declaration to a defender's lifeline, and the swing terms are declared
    entirely on the defender's side, one of them by a pair of *boots*.  One
    card mapping rather than one mapping per slot, because a defender's
    loadout is one thing and a request that could equip its items but not its
    boots could not arm the plating multiplier at all.
    """
    cards = dict(enemy_cards or {})
    request = {
        "champion": champion,
        "level": 18,
        "items": list(items),
        "fight_mode": "time_based",
        "fight_duration": 8,
        "enemies": [
            {
                "champion": name,
                "level": 18,
                "items": [],
                **{
                    field: (list(value) if field == "items" else value)
                    for field, value in cards.get(name, {}).items()
                },
            }
            for name in enemies
        ],
        "allies": [
            {
                "champion": name,
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            }
            for name in allies
        ],
    }
    request.update(extra)
    return request


COUPLED_SCENARIOS = (
    # Three cross-participant producers on one holder, with an ally to price
    # and an authored charm to arm Command.
    CoupledScenario(
        "mandate_abyssal_curse_roster",
        _roster_request(
            "Ahri",
            ("Imperial Mandate", "Abyssal Mask", "Bloodletter's Curse"),
            enemies=("Aatrox",),
            allies=("Pantheon",),
        ),
    ),
    # The two stack-ledger producers: Carve reads physical damage, Expose
    # Weakness rides a spellblade proc, so this build attacks.
    CoupledScenario(
        "cleaver_bloodsong_roster",
        _roster_request(
            "Jax",
            ("Black Cleaver", "Bloodsong"),
            enemies=("Aatrox",),
            allies=("Lulu",),
            role="support",
            role_quest_complete=True,
            include_auto_attacks=True,
            auto_attack_uptime=1.0,
        ),
    ),
    # The sixth producer: Blue Dream Bubble rides the holder's own authored
    # shield onto an ally, and declares no owner.
    CoupledScenario(
        "dream_maker_roster",
        _roster_request(
            "Lulu",
            ("Dream Maker",),
            enemies=("Aatrox",),
            allies=("Jax",),
            role="support",
            role_quest_complete=True,
        ),
    ),
    # The cross-pass roster: Catalyst's Eternity restores are an external,
    # timestamped input the walk consumes on a second pass.
    CoupledScenario(
        "catalyst_roster",
        _roster_request(
            "Ahri",
            ("Catalyst of Aeons",),
            enemies=("Aatrox", "Malphite"),
            allies=("Pantheon",),
        ),
    ),
    # Both damage-ledger shapes, in score mode.  A score-only fight takes the
    # light positional *tuple* rows unless something held needs the enriched
    # dict view; the three scenarios below sit on either side of that gate and
    # on the seam between them.
    #
    # 1. Nothing held reads the event stream: tuple rows.
    CoupledScenario(
        "score_plain_tuple",
        _roster_request(
            "Annie",
            ("Luden's Echo",),
            enemies=("Aatrox",),
            allies=("Pantheon",),
        ),
        score_mode=True,
    ),
    # 2. A holder that scans the per-event *view* but not the damage stream.
    #    Today the gate does not notice, so its scan is handed tuple rows —
    #    the starvation C1 corrects, visible here as a coupled diff.
    CoupledScenario(
        "score_event_view_holder",
        _roster_request(
            "Annie",
            ("Luden's Echo", "Imperial Mandate"),
            enemies=("Aatrox",),
            allies=("Pantheon",),
        ),
        score_mode=True,
    ),
    # 3. A holder that scans the damage stream: dict rows, before and after.
    CoupledScenario(
        "score_event_scan_holder",
        _roster_request(
            "Annie",
            ("Luden's Echo", "Black Cleaver"),
            enemies=("Aatrox",),
            allies=("Pantheon",),
        ),
        score_mode=True,
    ),
    # The nine deferral families the baseline was blind to (umbrella
    # Amendment L, Ruling 2).  Both rosters are ordinary builds rather than
    # item lists assembled to satisfy a check: every declaring item below is
    # one a real build of that champion holds, and each one produces a number
    # in the captured snapshot — which is the whole point, since a family's
    # retirement slice has to be *seen* moving its price out of the pair
    # engine's rows and into the walk's own.
    #
    # A crit carry, covering five: crit_profile (Infinity Edge),
    # secondary_target (Runaan's Hurricane), on_hit_strike (Blade of the
    # Ruined King), charged_strike (Kraken Slayer) and threshold_defense
    # (Immortal Shieldbow).  Two enemies, because Runaan's bolts have nowhere
    # to go against one; autos at full uptime, because four of the five ride
    # a basic attack.
    CoupledScenario(
        "crit_onhit_carry_roster",
        _roster_request(
            "Caitlyn",
            (
                "Infinity Edge",
                "Runaan's Hurricane",
                "Blade of the Ruined King",
                "Kraken Slayer",
                "Immortal Shieldbow",
            ),
            enemies=("Aatrox", "Malphite"),
            allies=("Lulu",),
            include_auto_attacks=True,
            auto_attack_uptime=1.0,
        ),
    ),
    # A melee bruiser, covering the remaining four: periodic (Sunfire Aegis's
    # immolate), active_cast (Stridebreaker's active), damage_routing (Death's
    # Dance's deferral) and opening_defense (Randuin's Omen, and Plated
    # Steelcaps beside it — the one owner of that family whose reduction
    # prices every incoming basic attack rather than only a critical one).
    # It attacks and is attacked, because half of these price incoming damage.
    CoupledScenario(
        "immolate_active_bruiser_roster",
        _roster_request(
            "Darius",
            ("Sunfire Aegis", "Stridebreaker", "Randuin's Omen", "Death's Dance"),
            enemies=("Aatrox",),
            allies=("Lulu",),
            boots="Plated Steelcaps",
            include_auto_attacks=True,
            auto_attack_uptime=1.0,
        ),
    ),
    # The three static holder amps (umbrella Amendment M, Ruling 2).  A
    # holder's own amplifier is a term the pair engine applies and the walk's
    # from-declaration price does not yet carry, so a family re-priced while
    # no scenario arms one would delete a measured contribution from every
    # total that holds it — invisibly, because a baseline in which every amp
    # is 1.0 observes only the case that cannot fail.
    #
    # A mana mage, arming two of them at once on the two cases Ruling 1 names
    # as its seed fixtures: an Abyssal Mask holder's item active (Hextech
    # Rocketbelt, mitigated against the holder's own magic amp) and an Abyssal
    # Mask holder's ability-triggered item proc (Stormsurge, multiplied by the
    # holder's ability amp).  Actualizer declares that ability amp and it
    # rides an item active, so the window is authored explicitly — an amp
    # nobody triggered amplifies nothing, and an unarmed Actualizer would be
    # the same emptiness with a scenario name on it.
    CoupledScenario(
        "amp_armed_mage_roster",
        _roster_request(
            "Ahri",
            ("Actualizer", "Abyssal Mask", "Hextech Rocketbelt", "Stormsurge"),
            enemies=("Aatrox",),
            allies=("Pantheon",),
            item_options={"Actualizer": {"mana_made_real_active": 1}},
        ),
    ),
    # A crit carry, arming the third: Hexoptics C44's Magnification amplifies
    # every basic-damage part, so the roster attacks at full uptime and its
    # holder is ranged, which is the side of the declared range split that
    # earns the whole amp.  Infinity Edge beside it because the amp lands on a
    # crit_profile roster rather than on a bare weapon.
    CoupledScenario(
        "hexoptics_basic_amp_carry",
        _roster_request(
            "Caitlyn",
            ("Hexoptics C44", "Infinity Edge"),
            enemies=("Aatrox",),
            allies=("Lulu",),
            include_auto_attacks=True,
            auto_attack_uptime=1.0,
        ),
    ),
    # The two windows in which the pair engine re-prices a packet it already
    # authored (umbrella Amendment N, Ruling 3).  The walk's
    # from-declaration price knows only the one effective resistance a fight
    # publishes, so a family retired while no scenario arms a window would
    # price every packet at that baseline and delete the window — the
    # measurement that stopped the active_cast retirement, which only the
    # bench could see because no committed scenario armed one.  Armed means
    # *fired*: a holder whose window opens on no packet is the same emptiness
    # with a scenario name on it.
    #
    # An assassin, arming the lethality window: Voltaic Cyclosword's
    # Firmament grants its flat lethality *after* its own energized packet,
    # so `damage._apply_temporary_lethality_windows` rescales the later
    # timestamped physical packets once the complete ledger exists.  The
    # roster attacks at full uptime because the charge is spent by an attack,
    # and Eclipse is beside it because its proc is one of the packets the
    # window re-prices — the `cast_proc` family the stopped retirement names
    # as blocked next, by the same term.
    CoupledScenario(
        "lethality_window_assassin_roster",
        _roster_request(
            "Zed",
            ("Voltaic Cyclosword", "Eclipse", "Serylda's Grudge"),
            enemies=("Aatrox",),
            allies=("Lulu",),
            include_auto_attacks=True,
            auto_attack_uptime=1.0,
        ),
    ),
    # A mage, arming the max-health reprice: Liandry's Torment burns for a
    # share of the target's maximum health, and a Protoplasm Harness lifeline
    # raises that maximum mid-fight, so `damage._apply_liandry_reprice` folds
    # the difference back onto every tick after the lifeline.  It needs two
    # participants, which is why this is the one window the holder's own
    # items cannot cover.
    #
    # Its duration departs from the roster set's shared eight seconds, and
    # the departure is the mechanic rather than a tuned number: a fight that
    # reaches the lifeline's own expiry is *withheld* rather than priced
    # (`threshold_defense.ThresholdExpiryWithheld`), because the Wiki does
    # not document what the temporary maximum does to current health when it
    # lapses.  Measured on this roster, the lifeline arms at t = 2.5 s and
    # expires at 7.5 s, so eight seconds captures nothing at all and five
    # captures the reprice.
    CoupledScenario(
        "liandry_reprice_mage_roster",
        _roster_request(
            "Ahri",
            ("Liandry's Torment", "Rabadon's Deathcap", "Void Staff"),
            enemies=("Malphite",),
            allies=("Pantheon",),
            enemy_cards={"Malphite": {"items": ("Protoplasm Harness",)}},
            fight_duration=5,
        ),
    ),
    # The three target-side terms a basic-attack swing meets on its way into
    # a defender (umbrella Amendment R, Ruling 4).  `_mitigate` carries a
    # resistance and the holder's own amps and nothing else, so a family
    # whose packets are delivered as swings and re-priced from their
    # declarations would lose the plating multiplier, the crit-damage
    # reduction and Warden's Mail's capped flat subtraction — and the last of
    # those is not a factor on a magnitude at all, so no declaration could
    # reproduce it.
    #
    # *Armed means met*: the term has to be on a defender this roster
    # actually swings at, which is the join Ruling 4 makes the derivation
    # read.  Two of the three were already observable on a defender —
    # `immolate_active_bruiser_roster`'s Darius holds Randuin's Omen and
    # Plated Steelcaps and is attacked as well as attacking — and Rock Solid
    # was armed by no committed scenario and no bench roster at all.
    #
    # A crit carry into two enemy cards, because the two ordinary builds that
    # carry these terms cannot be one card: Warden's Mail is the *component*
    # Randuin's Omen is built out of, so a defender holding both is not a
    # build anybody plays.  Aatrox takes the finished-tank half, whose
    # Randuin's Omen meets the primary swings of an Infinity Edge holder with
    # the crit-damage reduction; Malphite takes the mid-game half — Warden's
    # Mail with Plated Steelcaps, arming Rock Solid and the plating
    # multiplier on one card.
    #
    # Malphite is second on purpose.  Runaan's Hurricane allocates its bolt
    # to the second roster target, and the measurement that opened this
    # amendment is a *bolt*: the copied packet a basic-attack router delivers
    # at a second subject is priced by the same swing composition, and a
    # second subject that takes less from the bolt carries more health into
    # the current-health on-hit strikes that follow it — so the bolt row and
    # the copied on-hit row move in OPPOSITE directions, and a roster that
    # armed the terms anywhere but under the bolt would read green over the
    # row that moved.
    CoupledScenario(
        "swing_term_armed_carry_roster",
        _roster_request(
            "Caitlyn",
            ("Infinity Edge", "Runaan's Hurricane", "Blade of the Ruined King"),
            enemies=("Aatrox", "Malphite"),
            allies=("Lulu",),
            enemy_cards={
                "Aatrox": {"items": ("Randuin's Omen",)},
                "Malphite": {
                    "items": ("Warden's Mail",),
                    "boots": "Plated Steelcaps",
                },
            },
            include_auto_attacks=True,
            auto_attack_uptime=1.0,
        ),
    ),
    # Everlasting armed by a melee holder's own forced swing in a window with
    # no auto stream.  Cho'Gath's E slows on the attack it forces, which the
    # one-rotation ledger lands at the cast, before Q's knock-up at 1.127 s;
    # the shield's timing is what an attacking enemy prices
    # (docs/item-source-reconciliation.md, entry 3).
    CoupledScenario(
        "everlasting_forced_swing_roster",
        _roster_request(
            "Cho'Gath",
            ("Fimbulwinter",),
            enemies=("Darius",),
            allies=(),
            enemy_cards={"Darius": {"items": ("Stridebreaker",)}},
            fight_mode="one_rotation",
            enemies_attack=True,
        ),
    ),
    *_syndra_pin_scenarios(),
)


def bench_roster_scenarios():
    """The four bench rosters, as coupled scenarios — read, never typed.

    Phase 4's criterion 14 ends *"per-attacker totals are asserted bit-exact
    on the four bench scenarios against ``scripts/golden_coupled_exact.json``"*.
    The assertion existed and was gated, over :data:`COUPLED_SCENARIOS`'
    thirteen — and the intersection with the four the sentence names was
    empty, so the clause named one instrument and cited another and was never
    dischargeable as written.

    The two sets answer two different questions and both are kept.
    :data:`COUPLED_SCENARIOS` is R-12's, derived from the ``damage_modifier``
    producer set so a seventh producer with no covering scenario fails; these
    four are R-07's and R-27's, chosen to move the optimizer's work counters.
    The bench requests are *rosters* — the searched champion carries no items,
    the enemies and allies do — so one coupled fight over each is well defined
    and deterministic, which an optimizer *search* over one would not be.

    Read from ``bench_coupled_optimizer.SCENARIOS`` rather than restated, for
    the same reason ``producers`` is read: a fifth bench scenario must arrive
    here on the commit that adds it, not on the commit somebody notices.

    **The rounded coupled baseline does not gain them.**  Only the exact
    capture does, so R-01 row 3's jurisdiction is exactly what it was and this
    adds a bit-exactness assertion rather than a new golden surface.
    """
    # Local and unresolvable to a static checker on purpose: the two scripts
    # sit in one directory that neither puts on ``sys.path`` at import time,
    # and hoisting this to the top would make importing the capture harness
    # import the bench harness -- a scripts-to-scripts dependency at module
    # scope, for a set only ``--exact`` reads.
    # pylint: disable-next=import-error,import-outside-toplevel
    from bench_coupled_optimizer import SCENARIOS

    return tuple(
        CoupledScenario(name, dict(request))
        for name, request in sorted(SCENARIOS.items())
    )


def _uncovered_producers(scenarios, producers):
    """Producers no scenario equips the item for — R-12's derived coverage."""
    equipped = frozenset().union(*(s.equipped() for s in scenarios))
    return tuple(sorted(p for p in producers if producer_item(p) not in equipped))


def receipt_walk_families():
    """Every receipt-walk deferral family, mapped to the items that declare it.

    R-12's coverage is derived and never typed, and this is its second
    reading.  :func:`cross_participant_producers` answers *can the baseline
    see every cross-participant packet source*; this answers *can it see
    every family whose numbers the walk still defers to the pair engine*.
    The umbrella's Amendment L, Ruling 2 makes that a covering scenario's
    job: against a family the baseline holds no roster for, a retirement
    slice's ``Expected qualifying occurrences`` line reads zero, no
    investigator is ever owed, and the re-pricing ships unseen.

    The mapping is **read** from
    ``docs/receipts/receipt-walk-retirement-schedule.json``, which is the
    committed home of the family-to-owner join and is itself derived — from
    the behaviour frontier's ``(family, receipt_walk)`` deferral rows and
    ``item_behavior_catalog``'s declarations — and gated against the tree by
    ``receipt_walk_schedule.py --check``.  So a fifteenth family, or an item
    that changes hands between families, reaches this guard on the commit
    that declares it: the schedule goes red until it is regenerated, and the
    regenerated schedule fails the capture until a scenario covers the
    family.  A hand list here would be the third copy of a mapping the tree
    already derives twice.
    """
    schedule = json.loads(SCHEDULE_RECEIPT_PATH.read_text(encoding="utf-8"))
    return {
        family: frozenset(entry["owners"])
        for family, entry in schedule["families"].items()
    }


def covering_scenarios(scenarios, families):
    """Which scenarios put one of a family's declaring items on a participant.

    One home for the predicate, because two readers ask it: this module's
    capture guard, and the schedule receipt's own per-family population.  A
    covering scenario and a scheduled population that disagreed about what
    "covering" means is the silent divergence the campaign exists to remove.
    """
    return {
        family: tuple(
            sorted(
                scenario.name
                for scenario in scenarios
                if scenario.equipped() & frozenset(items)
            )
        )
        for family, items in families.items()
    }


def _uncovered_families(scenarios, families):
    """Deferral families no scenario equips a declaring item of (R-12)."""
    covering = covering_scenarios(scenarios, families)
    return tuple(sorted(family for family, names in covering.items() if not names))


def holder_amp_declarations():
    """Each static holder amp, mapped to the items whose declaration produces it.

    R-12's coverage is derived and never typed, and this is its third
    reading.  :func:`cross_participant_producers` answers *can the baseline
    see every cross-participant packet source*, :func:`receipt_walk_families`
    *can it see every family whose numbers the walk still defers*; this
    answers *can it see every amplifier the holder's own build brings to
    those numbers*.  The umbrella's Amendment M, Ruling 2 makes that a
    covering scenario's job: a family re-priced out of the pair engine's rows
    while no scenario arms an amp would drop the holder's own amplifier from
    every total that holds it, and a baseline in which every amp is ``1.0``
    observes only the case that cannot fail.

    Two readings, because the tree declares the holder's static amps two ways
    and neither of them is an item name.  A **per-part** amp is a
    :class:`PartAmpRule` in the behaviour catalog, and the part it prices is
    its own ``typing.attack_classes`` — the question
    ``delta_amp.part_amp_rules`` asks when the engine prices an ability or a
    basic attack — so the kind is the declaration's own mechanic suffix and a
    part amp for a third attack class arrives here already named.  The
    **magic** amp is the one holder amp that occupies no chain slot, which
    the catalog says in its own words: ``DELTA_AMP_UNMIGRATED_TAGS`` records
    it as applied by ``_mitigate`` on the defender's side, so it is read as
    the registry tag it is declared under rather than as a compiled rule it
    deliberately has none of.

    Read live from the catalog over every owner in ``rule_owners()``, the way
    :func:`cross_participant_producers` reads the capability registry, so a
    fourth amp kind reaches this guard on the commit that declares it and
    fails the capture until a scenario arms it — rather than being discovered
    by whoever next re-prices a family.
    """
    kinds: dict[str, set[str]] = {}
    for owner in sorted(rule_owners()):
        for rule in behavior_rules(owner):
            if isinstance(rule.payload, PartAmpRule):
                kinds.setdefault(rule.mechanic_id.rsplit(".", 1)[-1], set()).add(owner)
        for _registry, _family, entry in registry_entries(owner):
            tag = str(entry.get("type", "")) if isinstance(entry, Mapping) else ""
            if tag in DELTA_AMP_UNMIGRATED_TAGS:
                kinds.setdefault(tag, set()).add(owner)
    return {kind: frozenset(owners) for kind, owners in sorted(kinds.items())}


def _unarmed_amp_kinds(scenarios, amps):
    """Static holder amps no scenario equips a declaring item of (R-12).

    The same predicate as :func:`_uncovered_families` over a different
    declaration join, which is why both read :func:`covering_scenarios`
    rather than spelling "covering" a second time.
    """
    covering = covering_scenarios(scenarios, amps)
    return tuple(sorted(kind for kind, names in covering.items() if not names))


# The two re-pricing windows' kind names are the tree's own vocabulary for
# the declaration that opens each one, never a label invented here: the
# lethality window is the ``EmpoweredHitRule`` field that carries it, and the
# max-health window is the defence field a lifeline writes.  A rename in
# either declaration therefore arrives as a renamed window rather than as a
# guard that quietly stopped matching.
LETHALITY_WINDOW = next(
    field.name
    for field in fields(EmpoweredHitRule)
    if TemporaryLethality.__name__ in str(field.type)
)
MAX_HEALTH_WINDOW = DefenseField.THRESHOLD_HEALTH_BONUS.value


def _temporary_lethality_holders():
    """Items whose empowered hit grants its holder lethality for a window."""
    return frozenset(
        owner
        for owner in rule_owners()
        for rule in behavior_rules(owner)
        if isinstance(rule.payload, EmpoweredHitRule)
        and rule.payload.temporary_lethality is not None
    )


def _target_max_health_periodic_owners():
    """Items whose periodic damage is priced off the target's maximum health."""
    return frozenset(
        owner
        for owner in rule_owners()
        for rule in behavior_rules(owner)
        if isinstance(rule.payload, PeriodicRule)
        for term in rule.payload.formula.terms
        if term.basis is Basis.TARGET_MAX_HEALTH
    )


def _threshold_health_raisers():
    """Items whose lifeline raises its holder's maximum health mid-fight."""
    return frozenset(
        owner
        for owner in rule_owners()
        for rule in behavior_rules(owner)
        if isinstance(rule.payload, ThresholdDefenseRule)
        and DefenseField.THRESHOLD_HEALTH_BONUS in rule.payload.writes
    )


def repricing_window_declarations():
    """Each re-pricing window, mapped to the declaration sides a scenario must equip.

    R-12's coverage is derived and never typed, and this is its fourth
    reading.  :func:`cross_participant_producers` answers *can the baseline
    see every cross-participant packet source*, :func:`receipt_walk_families`
    *can it see every family whose numbers the walk still defers*,
    :func:`holder_amp_declarations` *can it see every amplifier the holder's
    own build brings to those numbers*; this answers *can it see every
    window in which the pair engine re-prices a packet it already authored*.

    The umbrella's Amendment N, Ruling 3 makes that a covering scenario's
    job.  ``survival.pricing.price_declared_packet`` prices a declaration at
    the one effective resistance a fight publishes, while the pair engine
    re-prices already-authored packets once the complete ledger exists — so a
    family retired while no scenario arms a window would price every packet
    at the fight's baseline, delete the temporal windows, and do it behind a
    green zero-occurrence line, which is exactly how the ``active_cast``
    retirement was stopped (``expected-golden-diff-campaign-close-active-cast-retirement.json``).

    **Two joins, not one**, because the tree declares the two windows from
    opposite ends of a fight.  The lethality window is one *holder*
    declaration: an ``EmpoweredHitRule`` carrying a
    :class:`~.item_behavior.TemporaryLethality`, which
    ``damage._apply_temporary_lethality_windows`` reads back off the authored
    row to rescale later physical packets.  The max-health window is an
    *attacker* declaration joined to a *defender's*: a periodic burn priced
    off :attr:`~.item_behavior.Basis.TARGET_MAX_HEALTH`, and a lifeline that
    writes :attr:`~.item_behavior.DefenseField.THRESHOLD_HEALTH_BONUS` and so
    raises that maximum mid-fight, which is the pair the
    ``damage._apply_liandry_reprice`` walk needs before it can move a number
    at all.  A mapping keyed only on the holder's own items would report the
    magic half covered by an empty set.

    Each value is therefore a tuple of *sides*, and a covering scenario is
    one that equips a declaring item of **every** side — which is what makes
    the returned mapping usable by the one :func:`covering_scenarios`
    predicate rather than by a second spelling of "covering".  Read live from
    the catalog over every owner in ``rule_owners()``, so a third re-pricing
    window that no scenario arms reaches this guard on the commit that
    declares it.
    """
    windows = {}
    holders = _temporary_lethality_holders()
    if holders:
        windows[LETHALITY_WINDOW] = (holders,)
    scaled = _target_max_health_periodic_owners()
    raisers = _threshold_health_raisers()
    if scaled and raisers:
        windows[MAX_HEALTH_WINDOW] = (scaled, raisers)
    return dict(sorted(windows.items()))


def window_covering_scenarios(scenarios, windows):
    """Which scenarios equip a declaring item of *every* side of each window.

    One side is :func:`covering_scenarios` asked once; a window is the
    intersection over its sides.  Composing the one predicate is what keeps a
    two-ended join from growing a second definition of "covering".
    """
    covering = {}
    for kind, sides in windows.items():
        names = None
        for side in sides:
            per_side = set(covering_scenarios(scenarios, {kind: side})[kind])
            names = per_side if names is None else names & per_side
        covering[kind] = tuple(sorted(names or ()))
    return covering


def _unarmed_repricing_windows(scenarios, windows):
    """Re-pricing windows no scenario arms (R-12)."""
    covering = window_covering_scenarios(scenarios, windows)
    return tuple(sorted(kind for kind, names in covering.items() if not names))


# The pair engine's one basic-attack swing pricing entry point, named rather
# than described: `_mitigate_basic_attack_swing` resolves one primary
# basic-attack damage instance against the target, and every target-side term
# a swing meets is applied inside it or inside a helper it calls.  A rename
# arrives here as an AttributeError on the commit that renames it, which is
# the same guarantee the window kinds get from reading their own declaration
# fields rather than from a label typed into this module.
SWING_PRICING_ENTRY = "_mitigate_basic_attack_swing"


def _swing_pricing_functions():
    """The swing pricing entry point and every module function it reaches.

    Read from ``damage``'s own source, not listed: the terms a swing meets
    are spread across the entry point and the helpers it calls, and a term
    added to a fourth helper has to arrive at the guard on the commit that
    adds it rather than on the commit somebody notices.
    """
    getattr(damage, SWING_PRICING_ENTRY)  # a rename is an error, not a silence
    module = ast.parse(inspect.getsource(damage))
    defined = {
        node.name: node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    reached, pending = {}, [SWING_PRICING_ENTRY]
    while pending:
        name = pending.pop()
        if name in reached or name not in defined:
            continue
        reached[name] = defined[name]
        pending.extend(
            node.func.id
            for node in ast.walk(defined[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        )
    return reached


def swing_target_terms():
    """Every defensive field the basic-attack swing pricing reads off its target.

    The pair engine holds a target's resolved defence as ``target_``-prefixed
    fight state, so the join back to the declaration vocabulary is the
    :class:`~.item_behavior.DefenseField` whose value is the rest of the
    attribute name.  Reading it that way is what makes the set *the terms a
    swing meets* rather than *the terms somebody remembered*: a fifth
    target-side field read by the swing pricing is a new member the moment
    the read is written, and a fight-state attribute that is not a declared
    defensive field is not a term any item can arm.
    """
    values = {field.value: field for field in DefenseField}
    return frozenset(
        values[node.attr[len("target_") :]]
        for function in _swing_pricing_functions().values()
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute)
        and node.attr.startswith("target_")
        and node.attr[len("target_") :] in values
    )


def swing_term_declarations():
    """Each target-side swing term, mapped to the items that declare it.

    R-12's coverage is derived and never typed, and this is its fifth
    reading.  :func:`cross_participant_producers` answers *can the baseline
    see every cross-participant packet source*, :func:`receipt_walk_families`
    *can it see every family whose numbers the walk still defers*,
    :func:`holder_amp_declarations` *can it see every amplifier the holder's
    own build brings to those numbers*, :func:`repricing_window_declarations`
    *can it see every window in which the pair engine re-prices a packet it
    already authored*; this answers *can it see every term the defender
    brings to a packet delivered as a basic-attack swing*.

    The umbrella's Amendment R, Ruling 4 makes that a covering scenario's
    job.  ``survival.pricing.price_declared_packet`` carries what ``_mitigate``
    carries — a resistance and the holder's own amps — while a swing is
    priced by ``damage._mitigate_basic_attack_swing``, which meets three
    further terms on the target's side.  Two of them fold into a declared
    magnitude because a pure factor on a linear mitigation prices to the same
    real number; Warden's Mail's Rock Solid never does, because
    ``min(flat, per_hit × cap)`` is a capped flat *subtraction* applied to the
    crit and non-crit branches separately, and no magnitude a declaration
    could state reproduces one.

    Keyed per field rather than per mechanic, because the field is the
    tree's own vocabulary and the mechanic's name is not: Rock Solid's flat
    and its cap are two fields of one subtraction and are declared by one
    owner, so keying per field costs nothing and keeps a renamed or added
    field arriving as a renamed or added term.

    Read live from the catalog over every owner in ``rule_owners()`` and over
    **every** defence shape that declares a ``writes``, which is the
    amendment's own load-bearing correction: the three terms are declared by
    four owners across two rule shapes — ``OpeningDefenseRule`` for the
    plating multiplier, the crit-damage reduction and Rock Solid, and
    ``ReactiveRule`` for a second declaration of the same plating multiplier —
    so a mapping keyed on the opening-defence shape alone would report the
    plating term covered by an incomplete set.
    """
    terms: dict[str, set[str]] = {}
    swing_fields = swing_target_terms()
    for owner in sorted(rule_owners()):
        for rule in behavior_rules(owner):
            for written in getattr(rule.payload, "writes", ()):
                if written in swing_fields:
                    terms.setdefault(written.value, set()).add(owner)
    return {term: frozenset(owners) for term, owners in sorted(terms.items())}


def swing_delivering_scenarios(scenarios):
    """Which scenarios deliver a basic-attack swing at all.

    Read through ``FightParams.from_request``, which is the tree's own answer
    to the question and not the request's literal: ``include_auto_attacks``,
    ``auto_attacks_only`` and the uptime mode together decide whether a
    request's uptime survives into the fight, and a scenario that names an
    uptime the fight mode discards swings exactly as often as one that names
    none.
    """
    return frozenset(
        scenario.name
        for scenario in scenarios
        if FightParams.from_request(
            dict(scenario.request), deterministic=True
        ).auto_attack_uptime
        > 0
    )


def swing_term_covering_scenarios(scenarios, terms):
    """Which scenarios arm a swing term *and* swing at the card that holds it.

    Ruling 4's *armed means met*: a defender holding the item in a fight
    nobody swings at is the same emptiness with a scenario name on it.  So
    this is a two-sided join like a re-pricing window's — but its second side
    is a *delivery* rather than a second declaring item, which is why it
    composes :func:`covering_scenarios` with a scenario predicate instead of
    reusing :func:`window_covering_scenarios`.  The declaration side stays the
    one "covering" predicate the four readings before it share.
    """
    delivering = swing_delivering_scenarios(scenarios)
    return {
        term: tuple(sorted(set(names) & delivering))
        for term, names in covering_scenarios(scenarios, terms).items()
    }


def _unarmed_swing_terms(scenarios, terms):
    """Target-side swing terms no scenario arms against a swing (R-12)."""
    covering = swing_term_covering_scenarios(scenarios, terms)
    return tuple(sorted(term for term, names in covering.items() if not names))


def _refuse_unarmed_swing_terms(scenarios, terms):
    """Refuse a capture whose scenario set swings at no holder of some term.

    Its own function rather than a fifth block inside :func:`capture_coupled`,
    because the refusal has to name *both* sides of the join it failed — the
    item to equip and the delivery to make — and a guard that only told a
    reader which item to add would send them to write the emptiness Ruling 4
    describes.
    """
    unarmed = _unarmed_swing_terms(scenarios, terms)
    if not unarmed:
        return
    raise ValueError(
        "no coupled scenario swings at a defender arming "
        + ", ".join(unarmed)
        + " — a basic-attack swing meets target-side terms the walk's "
        "from-declaration price does not carry, and one of them is a capped "
        "flat subtraction no declared magnitude can reproduce, so a family "
        "delivered as a swing and retired while no scenario arms them would "
        "delete them from every packet that met them, unseen (umbrella "
        "Amendment R, Ruling 4); add a covering scenario that both equips "
        "one of "
        + ", ".join(sorted({item for term in unarmed for item in terms[term]}))
        + " on a participant and delivers a basic attack, before capturing "
        "the baseline"
    )


def _coupled_receipt(parsed, resolved, *, score_mode):
    """The coupled participant receipt, mirroring calculate's own composition."""
    params = resolved.fight_params
    main_stats = calculate_total_stats(
        resolved.champion_data,
        parsed.level,
        list(resolved.items),
        item_options=params.item_options,
        role=params.role,
        role_quest_complete=params.role_quest_complete,
        external_stat_bonuses=params.ally_stat_bonuses,
    )
    return build_participant_timeline(
        resolved.champion_data,
        parsed.level,
        list(resolved.items),
        params,
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses(
            resolved.champion_data["name"],
            parsed.level,
            main_stats,
            list(resolved.items),
            item_options=params.item_options,
        ),
        enemies=list(resolved.enemies),
        allies=list(resolved.allies),
        include_receipt=not score_mode,
        # Score mode is the optimizer's own composition: a search context
        # opts the walk into the compiled panels, which is the only way a
        # snapshot reaches the tuple damage ledger.  A build the compiler
        # cannot represent falls back to the receipt walk and its dict rows,
        # which is the other ledger shape and not an error.
        search_context=CoupledSearchContext() if score_mode else None,
        pair_result_cache={} if score_mode else None,
    )


def coupled_entry(scenario):
    """One scenario's raw (unrounded) fights and coupled receipt."""
    parsed = parse_scenario_request(dict(scenario.request), deterministic=True)
    resolved = resolve_scenario(parsed)
    fights = {}
    if not resolved.enemies:
        fights["manual_target"] = serialize_fight_result(
            run_fight(
                resolved.champion_data,
                parsed.level,
                list(resolved.items),
                resolved.fight_params,
            )
        )
    else:
        for index, (enemy, target_params) in enumerate(
            zip(resolved.enemies, resolved.target_fight_params)
        ):
            fights[f"{index}:{enemy.champion_data['name']}"] = serialize_fight_result(
                run_fight(
                    resolved.champion_data,
                    parsed.level,
                    list(resolved.items),
                    target_params,
                )
            )
    return {
        "fights": fights,
        "combat": _coupled_receipt(parsed, resolved, score_mode=scenario.score_mode),
    }


def _exact_totals(entry):
    """Per-attacker totals at full precision — R-13's bit-exactness instrument.

    Golden equality is equality to two decimals, so a summation-order change
    under 0.005 per leaf is invisible to it.  These ``repr(float)`` strings
    are the only figures a bit-exactness claim may cite.
    """
    totals = {}
    for key, fight in entry["fights"].items():
        totals[f"fights/{key}"] = repr(float(fight.get("total_damage", 0.0)))
    for index, actor in enumerate(entry["combat"].get("breakdown", [])):
        # The index keeps the key unique for a roster-free scenario, whose
        # breakdown rows carry no participant id.
        participant = f"{index}:{actor.get('participant_id', '')}"
        totals[f"combat/{participant}/outgoing"] = repr(
            float(actor.get("total_damage", 0.0))
        )
        totals[f"combat/{participant}/incoming"] = repr(
            float(actor.get("incoming_damage", 0.0))
        )
    return totals


def cross_participant_producers():
    """Every packet source that modifies another participant's damage.

    Read from ``trigger_stream.CAPABILITIES`` (R-12), never typed, and read
    through the registry's own ``cross_participant_packet_source`` so that
    "modifies another participant's damage" is decided in one place (D-07,
    Amendment C) rather than re-spelled here as a pair of conditions this
    instrument would then own a second copy of.  Each member is the literal a
    scenario has to equip the owner of, so a seventh producer joins this set
    on the commit that declares it and fails capture until a scenario covers
    it.
    """
    return frozenset(
        source
        for capability in CAPABILITIES.values()
        if (source := cross_participant_packet_source(capability)) is not None
    )


def capture_coupled(
    scenarios,
    *,
    producers,
    families=None,
    amps=None,
    windows=None,
    swing_terms=None,
    exact=False,
):
    """Roster snapshots through the coupled path, covering every producer.

    ``producers`` is read, never typed: it was the ``ast`` table
    ``item_support_effects`` derived from its own packet call sites at
    0A/0B, and is :func:`cross_participant_producers` — the
    ``trigger_stream.CAPABILITIES`` reading — from P2a (R-12), so a seventh
    ``damage_modifier`` producer with no covering scenario fails here rather
    than passing silently.  ``families`` is R-12's second reading and is read
    the same way, defaulting to :func:`receipt_walk_families`; passing it is
    the seam a negative test drives the guard through (R-05).  ``amps`` is
    R-12's third reading, defaulting to :func:`holder_amp_declarations`,
    ``windows`` its fourth, defaulting to
    :func:`repricing_window_declarations`, and ``swing_terms`` its fifth,
    defaulting to :func:`swing_term_declarations`; all three carry the same
    seam.  ``exact`` writes ``repr(float)`` per-attacker totals instead of
    the 2-decimal snapshot.
    """
    uncovered = _uncovered_producers(scenarios, producers)
    if uncovered:
        raise ValueError(
            "the coupled scenario set covers no holder of "
            + ", ".join(uncovered)
            + " — add a scenario equipping "
            + ", ".join(sorted({producer_item(p) for p in uncovered}))
            + " before capturing the baseline"
        )
    families = receipt_walk_families() if families is None else families
    blind = _uncovered_families(scenarios, families)
    if blind:
        raise ValueError(
            "the coupled scenario set puts no declaring item of "
            + ", ".join(blind)
            + " on any participant — a deferral family the baseline is blind "
            "to cannot be seen to re-price, so its retirement slice would "
            "declare zero qualifying occurrences and ship unseen (umbrella "
            "Amendment L, Ruling 2); add a covering scenario equipping one of "
            "the items each family's row in "
            + SCHEDULE_RECEIPT_PATH.name
            + " names, before capturing the baseline"
        )
    amps = holder_amp_declarations() if amps is None else amps
    unarmed = _unarmed_amp_kinds(scenarios, amps)
    if unarmed:
        raise ValueError(
            "the coupled scenario set arms no holder of "
            + ", ".join(unarmed)
            + " — a static holder amp no scenario arms is a term the baseline "
            "cannot see, so a family re-priced out of the pair engine's rows "
            "would drop it from every total that holds it and every amp in "
            "the capture would read 1.0, which is the case that cannot fail "
            "(umbrella Amendment M, Ruling 2); add a covering scenario "
            "equipping one of "
            + ", ".join(sorted({item for kind in unarmed for item in amps[kind]}))
            + " before capturing the baseline"
        )
    windows = repricing_window_declarations() if windows is None else windows
    unarmed_windows = _unarmed_repricing_windows(scenarios, windows)
    if unarmed_windows:
        raise ValueError(
            "the coupled scenario set arms no "
            + ", ".join(unarmed_windows)
            + " window — the pair engine re-prices packets it already "
            "authored inside such a window while the walk's "
            "from-declaration price knows only the fight's published "
            "resistance, so a family retired while no scenario arms one "
            "would delete the window from every packet that met it, "
            "unseen (umbrella Amendment N, Ruling 3); add a covering "
            "scenario equipping one item from every side of "
            + "; ".join(
                f"{kind}: " + " + ".join(sorted(map(str, side)))
                for kind in unarmed_windows
                for side in windows[kind]
            )
            + " before capturing the baseline"
        )
    _refuse_unarmed_swing_terms(
        scenarios, swing_term_declarations() if swing_terms is None else swing_terms
    )
    entries = {}
    for scenario in scenarios:
        raw = coupled_entry(scenario)
        entries[scenario.name] = _exact_totals(raw) if exact else _rounded(raw)
    sections = {"coupled_scenarios": entries}
    return {
        **sections,
        "metadata": {
            "snapshot_kind": COUPLED_SNAPSHOT_KIND,
            "exact": bool(exact),
            **snapshot_provenance(),
            "scenario_count": len(entries),
            "producer_count": len(producers),
            "fingerprint": fingerprint_counts(sections),
        },
    }


def _format_value(value):
    text = json.dumps(value, sort_keys=True, default=repr)
    return text if len(text) <= 120 else text[:117] + "..."


def diff_snapshots(path, old, new, diffs):
    """Recursively collect 'path: old -> new' strings for every difference."""
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            if key not in old:
                diffs.append(f"{path}/{key}: <absent> -> {_format_value(new[key])}")
            elif key not in new:
                diffs.append(f"{path}/{key}: {_format_value(old[key])} -> <absent>")
            else:
                diff_snapshots(f"{path}/{key}", old[key], new[key], diffs)
    elif isinstance(old, list) and isinstance(new, list):
        for index in range(max(len(old), len(new))):
            if index >= len(old):
                diffs.append(
                    f"{path}[{index}]: <absent> -> {_format_value(new[index])}"
                )
            elif index >= len(new):
                diffs.append(
                    f"{path}[{index}]: {_format_value(old[index])} -> <absent>"
                )
            else:
                diff_snapshots(f"{path}[{index}]", old[index], new[index], diffs)
    elif old != new:
        diffs.append(f"{path}: {_format_value(old)} -> {_format_value(new)}")


def capture(outfile):
    """Capture the pair-engine snapshot to ``outfile``."""
    started = time.perf_counter()
    snapshot = build_snapshot()
    Path(outfile).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    meta = snapshot["metadata"]
    print(f"Captured snapshot -> {outfile}")
    print(
        f"  champions: {meta['champion_count']}  "
        f"registered: {meta['registered_champion_count']}  "
        f"items swept: {meta['item_count']}  "
        f"sweep errors: {meta['item_sweep_error_count']}"
    )
    print(f"  elapsed: {time.perf_counter() - started:.1f}s")
    return 0


def coupled_scenarios_for(*, exact):
    """Which scenario set a capture covers — one answer, two readers.

    The exact capture additionally holds the four bench rosters, because
    Phase 4's criterion 14 names them by name; the rounded one does not,
    because adding them would move R-01 row 3's jurisdiction rather than the
    bit-exactness assertion the criterion is about.
    """
    if not exact:
        return COUPLED_SCENARIOS
    return (*COUPLED_SCENARIOS, *bench_roster_scenarios())


def capture_coupled_file(outfile, *, exact=False):
    """Capture the coupled roster baseline (or its exact per-attacker totals)."""
    started = time.perf_counter()
    snapshot = capture_coupled(
        coupled_scenarios_for(exact=exact),
        producers=cross_participant_producers(),
        exact=exact,
    )
    Path(outfile).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    meta = snapshot["metadata"]
    print(f"Captured coupled snapshot -> {outfile}")
    print(
        f"  scenarios: {meta['scenario_count']}  "
        f"producers covered: {meta['producer_count']}  "
        f"exact: {meta['exact']}"
    )
    print(f"  elapsed: {time.perf_counter() - started:.1f}s")
    return 0


def rebuild_for(baseline):
    """Recompute the snapshot a baseline is a capture of, in its own mode."""
    metadata = baseline.get("metadata", {})
    if metadata.get("snapshot_kind") != COUPLED_SNAPSHOT_KIND:
        return build_snapshot()
    exact = bool(metadata.get("exact", False))
    return capture_coupled(
        coupled_scenarios_for(exact=exact),
        producers=cross_participant_producers(),
        exact=exact,
    )


def _write_report(path, diffs, kind):
    """One LeafDiff per differing leaf, plus the ratio clause's own arithmetic."""
    qualifying = [diff for diff in diffs if qualifies_for_investigation(diff)]
    denominator = receipt_numeric_leaves(kind)
    report = {
        "snapshot_kind": kind,
        "differing_leaves": len(diffs),
        "qualifying_leaves": len(qualifying),
        "numeric_leaves": denominator,
        "leaf_ratio": (len(diffs) / denominator) if denominator else None,
        "ratio_clause_triggered": (
            bool(denominator) and len(diffs) > INVESTIGATION_LEAF_RATIO * denominator
        ),
        "largest_abs_delta_per_section": {
            section: max(
                (d for d in diffs if d.section == section),
                key=lambda d: d.abs_delta,
            ).path
            for section in sorted({d.section for d in diffs})
        },
        "diffs": [asdict(diff) for diff in diffs],
    }
    Path(path).write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return report


def compare(baseline_path, report_path=None):
    """Recompute the baseline's own snapshot and report every differing leaf."""
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    kind = baseline.get("metadata", {}).get("snapshot_kind", PAIR_SNAPSHOT_KIND)
    current = rebuild_for(baseline)
    # Provenance legitimately changes between commits; everything else must not.
    for snapshot in (baseline, current):
        for key in COMPARE_EXCLUDED_PROVENANCE:
            snapshot.get("metadata", {}).pop(key, None)
    diffs = leaf_report(baseline, current)
    for diff in diffs:
        old = "<absent>" if diff.old is None else _format_value(diff.old)
        new = "<absent>" if diff.new is None else _format_value(diff.new)
        print(f"{diff.path}: {old} -> {new}")
    if report_path:
        report = _write_report(report_path, diffs, kind)
        print(
            f"  report -> {report_path} "
            f"({report['qualifying_leaves']} qualifying for investigation)"
        )
    if diffs:
        print(f"FAIL: {len(diffs)} difference(s) vs {baseline_path}")
        return 1
    print(f"OK: snapshot identical to {baseline_path}")
    return 0


def print_fingerprint(snapshot_path):
    """Print one snapshot's shape figures — the sole home of those numbers."""
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    print(json.dumps(fingerprint(snapshot), indent=2, sort_keys=True))
    return 0


def main():
    """CLI entry point: capture | compare | capture-coupled | fingerprint."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capture").add_argument("outfile")
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument(
        "--report",
        default=None,
        help="write the classified LeafDiff report to this path (R-15)",
    )
    coupled = commands.add_parser("capture-coupled")
    coupled.add_argument("outfile")
    coupled.add_argument(
        "--exact",
        action="store_true",
        help="write repr(float) per-attacker totals instead of the 2-dp snapshot",
    )
    commands.add_parser("fingerprint").add_argument("snapshot")
    args = parser.parse_args()
    if args.command == "capture":
        sys.exit(capture(args.outfile))
    if args.command == "capture-coupled":
        sys.exit(capture_coupled_file(args.outfile, exact=args.exact))
    if args.command == "fingerprint":
        sys.exit(print_fingerprint(args.snapshot))
    sys.exit(compare(args.baseline, report_path=args.report))


if __name__ == "__main__":
    main()
