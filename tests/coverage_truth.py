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

This is a test helper, not a test module: it holds no assertions.
"""

from src.calculator.champions import parse_champion_abilities
from src.calculator.scenario import load_public_champion
from tests import row_review

PRICED = "priced"
ZERO = "zero"
ABSENT = "absent"


def emitted(champion, **options):
    """``{slot: priced|zero|absent}`` for P/Q/W/E/R from one parse.

    Options are the module's own, passed through so a slot the module
    hides behind one (Rumble's ``p_overheated``) can be read in either
    state.  Stats, ranks and target come from :mod:`tests.row_review`, so
    every champion is read at the same level 18 vantage.
    """
    parsed = parse_champion_abilities(
        load_public_champion(champion),
        18,
        row_review.STATS["ability_power"],
        dict(row_review.RANKS),
        champion_stats=dict(row_review.STATS),
        target_stats=dict(row_review.TARGET),
        champion_options=options or None,
    )
    answers = {}
    for slot in "PQWER":
        entry = parsed.get("passive" if slot == "P" else slot)
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
