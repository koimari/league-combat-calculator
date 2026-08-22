"""What a champion module's five slots actually emit, per slot.

``MODULE_COVERAGE`` is a claim about damage, and a claim no test reads is
a claim that drifts: between ``b03bbad9`` and the coverage-frontier
campaign, Samira's, Yasuo's and Kindred's maps each named the wrong set
of slots while every row they price stayed correct.  So the modules that
declare a map assert it against this read, taken off a real parse, and
the two can only disagree by failing.

The three answers are deliberately coarser than the coverage vocabulary:
this says what the parse *did*, and the module's map says what that
means.  ``priced`` covers an on-hit shell too (Kog'Maw W, Rumble P
overheated), whose damage rides the basic-attack stream rather than the
row's own ``total_raw``.

Two vantages, because a kit can be honest in one and silent in the other:
:data:`PER_CAST` is one rotation, and :data:`TIMED` is the fight window
the pipeline injects for a timed fight (``fight_duration_seconds``, the
auto uptime, and an attack speed for the swings those two imply).  A
passive that walks a hit timeline (Braum's Concussive Blows, Vi's Denting
Blows) prices nothing at all in the first and everything in the second.

This is a test helper, not a test module: it holds no assertions.
"""

from src.calculator.champions import parse_champion_abilities
from src.calculator.scenario import load_public_champion
from tests import row_review

PRICED = "priced"
ZERO = "zero"
ABSENT = "absent"

#: One rotation: the vantage every per-champion row review already uses.
PER_CAST: dict = {}

#: The timed fight window ``pipeline`` injects when ``one_rotation`` is
#: off.  The three keys are reserved and pipeline-owned, so a module reads
#: them from its options exactly as it does in a real request.
TIMED = {
    "fight_duration_seconds": 30.0,
    "auto_attack_uptime": 1.0,
    "auto_attacks_only": False,
}

#: ``row_review.STATS`` carries no attack speed, because a row review
#: prices one cast and never a swing stream.  Both vantages here supply
#: one: without it a hit-timeline passive walks an empty stream and reports
#: itself absent for a reason that is the vantage's rather than the
#: module's, and a kit reading the ratio (Ashe's Frost Shot) cannot be read
#: at all.
SWING_STATS = {
    "attack_speed": 1.0,
    "attack_speed_ratio": 0.625,
    "base_attack_speed": 0.625,
    "ability_haste": 0.0,
}


def parse(champion, *, vantage=None, **options):
    """One champion's parsed entries at the named vantage.

    Options are the module's own, passed through so a slot the module
    hides behind one (Rumble's ``overheat_autos``) can be read in either
    state.  ``vantage`` is :data:`PER_CAST` (the default) or :data:`TIMED`.
    Stats, ranks and target come from :mod:`tests.row_review`, so every
    champion is read at the same level 18 vantage.
    """
    return parse_champion_abilities(
        load_public_champion(champion),
        18,
        row_review.STATS["ability_power"],
        dict(row_review.RANKS),
        champion_stats={**row_review.STATS, **SWING_STATS},
        target_stats=dict(row_review.TARGET),
        champion_options={**dict(vantage or PER_CAST), **options} or None,
    )


def emitted(champion, *, vantage=None, **options):
    """``{slot: priced|zero|absent}`` for P/Q/W/E/R from one parse."""
    parsed = parse(champion, vantage=vantage, **options)
    answers = {}
    for slot in "PQWER":
        entry = slot_entry(parsed, slot)
        if entry is None:
            answers[slot] = ABSENT
        elif (
            float(entry.get("total_raw") or 0.0) > 0.0
            or entry.get("on_hit")
            or entry.get("stat_buff")
            or entry.get("target_debuff")
        ):
            answers[slot] = PRICED
        else:
            answers[slot] = ZERO
    return answers


def slot_entry(parsed, slot):
    """The parsed entry for *slot*, under either key a P row may occupy.

    A returned P-slot entry lands under ``"passive"``, but a parser that
    writes ``ctx.results`` itself may choose the literal ``"P"`` instead
    (Amumu's Cursed Touch, Annie's Pyromania) — reading only the first
    reported both of those rows absent when they were sitting right there.
    """
    if slot != "P":
        return parsed.get(slot)
    entry = parsed.get("passive")
    return entry if entry is not None else parsed.get("P")


def prices_enemy_damage(entry):
    """Whether *entry* puts damage on the enemy.

    Narrower than ``priced``: a self stat buff and a target debuff are
    real outcomes the coarse read counts, but neither is damage, and
    ``no_damage`` is a claim about damage alone.
    """
    if entry is None:
        return False
    return bool(float(entry.get("total_raw") or 0.0) > 0.0 or entry.get("on_hit"))
