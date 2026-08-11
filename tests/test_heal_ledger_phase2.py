"""Issue #143 phase 2 — one authoritative ledger owner per heal, continued.

Phase 1 locked Taric Q / Shyvana W / Naafiri Q.  Phase 2 extends the
``_MODULE_AUTHORED_HEAL_SLOTS`` registry to the remaining audited slots and
locks the ledger outcomes:

- SELF-heal double-grants (scanner re-derived a heal the champion rule
  already authors): Sona W, Janna R, Milio R, Irelia Q, Vladimir Q,
  Volibear W, Ekko R, Gangplank W, Kha'Zix W, Tahm Kench Q.  One cast now
  pays the self heal exactly once (the rule's sourced amount).
- FABRICATED ally heals for self-only abilities: Sylas W, Tryndamere Q,
  Talon Q, Yorick Q, Kindred W.  The scanner's ally packet is gone; the
  rule's self heal is the only event.
- Sona W / Janna R / Milio R additionally fan the RULE's event out to
  selected teammates (the game heals allies with the same ability), with
  provable ``source_event_id`` linkage.
- Rakan Q keeps the scanner's ALLY branch at its own (rank-indexed) amount
  while the champion rule owns the self heal at the per-level amount
  (210 at level 18) — the deliberate 210-self / 80-ally split.
"""

import pytest

from src.calculator.champions.slotlib import extract_named
from src.calculator.data_fetcher import get_champion
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.healing import derive_self_healing
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.support_effects import (
    _MODULE_AUTHORED_HEAL_SLOTS,
    derive_ally_effects,
)

# The 15 slots this phase adds to the registry (phase 1's three are locked
# in tests/test_issue_143.py).
PHASE2_SLOTS = [
    ("Sona", "W"),
    ("Janna", "R"),
    ("Milio", "R"),
    ("Irelia", "Q"),
    ("Vladimir", "Q"),
    ("Volibear", "W"),
    ("Ekko", "R"),
    ("Gangplank", "W"),
    ("Kha'Zix", "W"),
    ("Tahm Kench", "Q"),
    ("Sylas", "W"),
    ("Tryndamere", "Q"),
    ("Talon", "Q"),
    ("Yorick", "Q"),
    ("Kindred", "W"),
]


def _fight(
    champion: str,
    *,
    with_ally: bool = False,
    duration: float = 5.0,
    auto_uptime: float = 0.0,
    include_autos: bool = False,
    options: dict | None = None,
    ranks: dict | None = None,
) -> dict:
    """One deterministic 1v1 (or roster) fight at level 18, no items."""
    data = get_champion(champion)
    params = FightParams.from_request(
        {
            "fight_mode": "one_rotation" if duration == 5.0 else "time_based",
            "role": "mid",
            "fight_duration": duration,
            "include_auto_attacks": include_autos,
            "auto_attack_uptime": auto_uptime,
            **({"champion_options": options} if options else {}),
            **({"ability_ranks": ranks} if ranks else {}),
        },
        deterministic=True,
    )
    enemies = [
        ChampionLoadout(
            champion="Ahri",
            level=18,
            role="mid",
            ability_ranks={"E": 0},
        ).resolve()
    ]
    allies = (
        [ChampionLoadout(champion="Ashe", level=18, role="bottom").resolve()]
        if with_ally
        else []
    )
    stats = calculate_total_stats(data, 18, [], role="mid")
    defenses = resolve_starting_defenses(champion, 18, stats, [])
    return build_participant_timeline(
        data,
        18,
        [],
        params,
        main_stats=stats,
        main_defenses=defenses,
        enemies=enemies,
        allies=allies,
    )


def _main_heals(res: dict, source: str) -> list[dict]:
    return [
        event
        for event in res["healing_events"]
        if event.get("attacker") == "main" and str(event.get("source", "")) == source
    ]


def _support_heals(res: dict, source: str) -> list[dict]:
    return [
        event
        for event in res["support_events"]
        if event.get("attacker") == "main"
        and event.get("kind") == "heal"
        and source in str(event.get("source", ""))
    ]


def _survival(res: dict, participant_id: str) -> dict:
    return next(
        row["survival"]
        for row in res["participants"]
        if row["participant_id"] == participant_id
    )


# ---------------------------------------------------------------------------
# Registry + mechanical scanner gate
# ---------------------------------------------------------------------------


def test_registry_covers_every_phase2_slot():
    """All 15 phase-2 slots are registry members (Rakan Q deliberately not:
    its scanner ally branch survives — see the scope override)."""
    assert all(slot in _MODULE_AUTHORED_HEAL_SLOTS for slot in PHASE2_SLOTS)
    assert ("Rakan", "Q") not in _MODULE_AUTHORED_HEAL_SLOTS


@pytest.mark.parametrize(("champion", "slot"), PHASE2_SLOTS)
def test_scanner_emits_no_heal_packet_for_registry_slots(champion, slot):
    """The mechanical acceptance gate: the generic scanner never re-derives
    a slot the champion heal rule owns.  Shields on the same slot stay
    scanner-owned (Sona W's Melody shield)."""
    effects = derive_ally_effects(
        get_champion(champion),
        18,
        {"ability_power": 0.0, "health": 2000.0},
        [{"slot": slot, "time": 1.0}],
    )
    assert [e for e in effects if e["kind"] == "heal" and e["slot"] == slot] == []


def test_sona_w_melody_shield_stays_scanner_owned():
    """Sona W is in the heal registry but its Melody shield has no module
    author, so the scanner still emits the sourced shield packet."""
    effects = derive_ally_effects(
        get_champion("Sona"),
        18,
        {"ability_power": 0.0, "health": 2000.0},
        [{"slot": "W", "time": 1.0}],
    )
    shields = [e for e in effects if e["kind"] == "shield" and e["slot"] == "W"]
    assert len(shields) == 1
    assert shields[0]["amount"] == pytest.approx(105.0)
    assert shields[0]["target_scope"] == "self_and_one_teammate"


def test_rakan_q_scanner_packet_targets_allies_only():
    """Rakan Q's scanner packet stays at its own (rank-indexed) amount but
    targets ALLIES ONLY: the champion rule owns the self heal (per-level
    210), so the packet must not double-grant the self."""
    effects = derive_ally_effects(
        get_champion("Rakan"),
        18,
        {"ability_power": 0.0, "health": 2000.0},
        [{"slot": "Q", "time": 1.0}],
    )
    heals = [e for e in effects if e["kind"] == "heal" and e["slot"] == "Q"]
    assert len(heals) == 1
    assert heals[0]["amount"] == pytest.approx(80.0)
    assert heals[0]["target_scope"] == "all_teammates"


# ---------------------------------------------------------------------------
# Self+ally fan-out champions
# ---------------------------------------------------------------------------


def test_sona_w_heals_self_once_and_fans_out_one_ally_clone():
    """One W cast: exactly one Aria of Perseverance heal event on the self
    ledger at the sourced rank row (90, 0 AP), and one identical clone to
    the selected teammate with linked event ids.  The 1v1 heals 90 once
    (never 90 + 90)."""
    res = _fight("Sona", with_ally=True)
    self_heals = _main_heals(res, "Aria of Perseverance")
    assert len(self_heals) == 1
    self_heal = self_heals[0]
    assert self_heal["amount"] == pytest.approx(90.0, abs=0.06)
    assert self_heal["applied_amount"] == pytest.approx(90.0, abs=0.06)
    assert _survival(res, "main")["healing_received"] == pytest.approx(90.0, abs=0.06)
    clones = _support_heals(res, "Aria of Perseverance")
    assert len(clones) == 1
    clone = clones[0]
    assert clone["target"] == "ally:Ashe"
    assert clone["amount"] == pytest.approx(90.0, abs=0.06)
    assert clone["time"] == self_heal["time"]
    assert clone["source_event_id"] == self_heal["event_id"]
    assert clone["event_id"] == f'{self_heal["event_id"]}:ally:1'
    assert _survival(res, "ally:Ashe")["healing_received"] == pytest.approx(
        90.0, abs=0.06
    )

    res_1v1 = _fight("Sona")
    assert len(_main_heals(res_1v1, "Aria of Perseverance")) == 1
    assert _survival(res_1v1, "main")["healing_received"] == pytest.approx(
        90.0, abs=0.06
    )
    assert _support_heals(res_1v1, "Aria of Perseverance") == []


def test_janna_r_heals_self_in_sourced_ticks_and_fans_out_every_tick():
    """One R channel: 12 sourced Monsoon ticks of 50 on the self ledger
    (total 600), each fanned out to the teammate as a linked clone — the
    ally receives the same ticked heal, never a second lump."""
    res = _fight("Janna", with_ally=True)
    self_heals = _main_heals(res, "Monsoon")
    assert len(self_heals) == 12
    assert all(h["amount"] == pytest.approx(50.0, abs=0.06) for h in self_heals)
    assert sum(h["amount"] for h in self_heals) == pytest.approx(600.0, abs=0.6)
    assert _survival(res, "main")["healing_received"] == pytest.approx(600.0, abs=0.6)
    clones = _support_heals(res, "Monsoon")
    assert len(clones) == 12
    self_by_time = {h["time"]: h for h in self_heals}
    for clone in clones:
        assert clone["target"] == "ally:Ashe"
        assert clone["amount"] == pytest.approx(50.0, abs=0.06)
        self_event = self_by_time[clone["time"]]
        assert clone["source_event_id"] == self_event["event_id"]
        assert clone["event_id"] == f'{self_event["event_id"]}:ally:1'
    assert sum(clone["raw_amount"] for clone in clones) == pytest.approx(600.0, abs=0.6)
    assert _survival(res, "ally:Ashe")["healing_received"] == pytest.approx(
        sum(clone["applied_amount"] for clone in clones), abs=0.6
    )

    res_1v1 = _fight("Janna")
    one_v_one_heals = _main_heals(res_1v1, "Monsoon")
    assert len(one_v_one_heals) == 12
    assert sum(event["raw_amount"] for event in one_v_one_heals) == pytest.approx(
        600.0, abs=0.6
    )
    assert _survival(res_1v1, "main")["healing_received"] == pytest.approx(
        sum(event["applied_amount"] for event in one_v_one_heals), abs=0.6
    )
    assert _support_heals(res_1v1, "Monsoon") == []


def test_milio_r_heals_self_once_and_fans_out_one_ally_clone():
    """One R cast: exactly one Breath of Life heal event on the self ledger
    at 350 and one linked clone to the teammate (the Cozy Campfire W ticks
    are a separate, scanner-owned heal and stay out of this assertion)."""
    res = _fight("Milio", with_ally=True)
    self_heals = _main_heals(res, "Breath of Life")
    assert len(self_heals) == 1
    self_heal = self_heals[0]
    assert self_heal["amount"] == pytest.approx(350.0, abs=0.06)
    clones = _support_heals(res, "Breath of Life")
    assert len(clones) == 1
    clone = clones[0]
    assert clone["target"] == "ally:Ashe"
    assert clone["amount"] == pytest.approx(350.0, abs=0.06)
    assert clone["source_event_id"] == self_heal["event_id"]
    assert _survival(res, "ally:Ashe")["healing_received"] >= 350.0

    res_1v1 = _fight("Milio")
    assert len(_main_heals(res_1v1, "Breath of Life")) == 1
    assert _support_heals(res_1v1, "Breath of Life") == []


# ---------------------------------------------------------------------------
# Self-only double-grant removals
# ---------------------------------------------------------------------------


def test_irelia_q_heals_self_once_at_the_sourced_ad_share():
    """Bladesurge heals Irelia herself (cached Q 'Heal' row, 9 : 13 % AD by
    rank); the scanner's cast-time packet is gone, so one cast pays the
    self heal exactly once."""
    stats = calculate_total_stats(get_champion("Irelia"), 18, [], role="mid")
    expected = extract_named(
        get_champion("Irelia")["abilities"]["Q"][0], "Heal", 5, stats, {}
    )
    assert expected == pytest.approx(16.12)

    res = _fight("Irelia", with_ally=True)
    heals = _main_heals(res, "Bladesurge")
    assert len(heals) == 1
    assert heals[0]["amount"] == pytest.approx(expected, abs=0.06)
    assert _survival(res, "main")["healing_received"] == pytest.approx(
        heals[0]["applied_amount"], abs=0.06
    )
    assert _support_heals(res, "Bladesurge") == []
    assert _survival(res, "ally:Ashe")["healing_received"] == 0.0


def test_vladimir_q_heals_self_once_at_the_rank_row():
    """Transfusion heals Vladimir himself (40 + 35% AP at rank 5); the
    scanner's duplicate 40 packet is gone — the Q heals once per cast (his
    W pool and R are separate rule-owned heals)."""
    res = _fight("Vladimir", with_ally=True)
    heals = _main_heals(res, "Transfusion")
    assert len(heals) == 1
    assert heals[0]["amount"] == pytest.approx(40.0, abs=0.06)
    assert _support_heals(res, "Transfusion") == []

    res_1v1 = _fight("Vladimir")
    assert len(_main_heals(res_1v1, "Transfusion")) == 1
    assert _support_heals(res_1v1, "Transfusion") == []


def test_volibear_w_first_cast_applies_wound_only_and_never_scanner_heals():
    """Frenzied Maul's first W only applies Wound (no heal); the heal lands
    on later Ws of an already-Wounded target.  The scanner's flat 80 at
    every cast (including the spurious first-W heal) is gone: one-rotation
    fight -> zero W heals; two W hits -> exactly one rule heal."""
    res = _fight("Volibear", with_ally=True)
    assert _main_heals(res, "Frenzied Maul") == []
    assert _support_heals(res, "Frenzied Maul") == []
    assert _survival(res, "main")["healing_received"] == 0.0

    def w_event(time: float, sequence: int) -> dict:
        return {
            "slot": "W",
            "time": time,
            "damage": 100.0,
            "raw_damage": 100.0,
            "source": "W",
            "source_key": "W",
            "sequence": sequence,
            "target": "enemy",
        }

    volibear = get_champion("Volibear")
    heals = derive_self_healing(
        volibear,
        {"level": 18, "health": 2000.0, "ability_power": 0.0},
        {"W": {"rank": 5}},
        [w_event(1.0, 1), w_event(3.0, 2)],
        [{"slot": "W", "time": 1.0}],
        5.0,
    )
    assert len(heals) == 1
    assert heals[0]["source"] == "Frenzied Maul"
    assert heals[0]["time"] == pytest.approx(3.0)


def test_ekko_r_heals_self_once_at_the_minimum_heal_row():
    """Chronobreak heals Ekko himself at the sourced Minimum Heal (200 at
    rank 3, 0 AP); the scanner's duplicate 'Minimum Heal' packet is gone."""
    res = _fight("Ekko", with_ally=True)
    heals = _main_heals(res, "Chronobreak")
    assert len(heals) == 1
    assert heals[0]["amount"] == pytest.approx(200.0, abs=0.06)
    assert _survival(res, "main")["healing_received"] == pytest.approx(
        heals[0]["applied_amount"], abs=0.06
    )
    assert _support_heals(res, "Chronobreak") == []
    assert _survival(res, "ally:Ashe")["healing_received"] == 0.0


def test_gangplank_w_heals_self_once_with_the_missing_health_formula():
    """Remove Scurvy heals Gangplank himself via the rule's live formula
    (145 + 13% missing health at rank 5, 0 AP); the scanner's flat 145
    packet is gone, so the heal pays once at the formula's price."""
    res = _fight("Gangplank", with_ally=True)
    heals = _main_heals(res, "Remove Scurvy")
    assert len(heals) == 1
    assert heals[0]["applied_amount"] >= 145.0
    assert _survival(res, "main")["healing_received"] == pytest.approx(
        heals[0]["applied_amount"], abs=0.06
    )
    assert _support_heals(res, "Remove Scurvy") == []
    assert _survival(res, "ally:Ashe")["healing_received"] == 0.0


def test_khazix_w_heals_self_once_at_the_rank_row():
    """Void Spike heals Kha'Zix himself for the flat rank row (135 + 50% AP
    at rank 5); the scanner's duplicate 135 packet is gone."""
    res = _fight("Kha'Zix", with_ally=True)
    heals = _main_heals(res, "Void Spike")
    assert len(heals) == 1
    assert heals[0]["amount"] == pytest.approx(135.0, abs=0.06)
    assert _survival(res, "main")["healing_received"] == pytest.approx(
        heals[0]["applied_amount"], abs=0.06
    )
    assert _support_heals(res, "Void Spike") == []
    assert _survival(res, "ally:Ashe")["healing_received"] == 0.0


def test_tahm_kench_q_heals_self_once_with_the_missing_health_formula():
    """Tongue Lash heals Tahm Kench himself via the rule's live formula
    (30 + 7% missing health at rank 5, 0 AP); the scanner's flat 30 packet
    is gone (the Thick Skin grey-health heal is a separate rule-owned
    event and stays out of this assertion)."""
    res = _fight("Tahm Kench", with_ally=True)
    heals = _main_heals(res, "Tongue Lash")
    assert len(heals) == 1
    assert heals[0]["applied_amount"] >= 30.0
    assert _support_heals(res, "Tongue Lash") == []
    assert _survival(res, "ally:Ashe")["healing_received"] == 0.0


def test_sylas_w_heals_self_once_and_never_an_ally():
    """Kingslayer heals Sylas himself scaled by missing health (Minimum
    100 / Maximum 200 at rank 5); the fabricated ally packet is gone."""
    res = _fight("Sylas", with_ally=True)
    heals = _main_heals(res, "Kingslayer")
    assert len(heals) == 1
    assert 100.0 <= heals[0]["applied_amount"] <= 200.0
    assert _survival(res, "main")["healing_received"] == pytest.approx(
        heals[0]["applied_amount"], abs=0.06
    )
    assert _support_heals(res, "Kingslayer") == []
    assert _survival(res, "ally:Ashe")["healing_received"] == 0.0


def test_tryndamere_q_heals_self_once_at_the_zero_fury_row():
    """Bloodlust heals Tryndamere himself at the sourced 0-Fury Minimum
    Heal (70 + 30% AP at rank 5); the fabricated ally packet is gone."""
    res = _fight("Tryndamere", with_ally=True)
    heals = _main_heals(res, "Bloodlust")
    assert len(heals) == 1
    assert heals[0]["amount"] == pytest.approx(70.0, abs=0.06)
    assert _survival(res, "main")["healing_received"] == pytest.approx(
        heals[0]["applied_amount"], abs=0.06
    )
    assert _support_heals(res, "Bloodlust") == []
    assert _survival(res, "ally:Ashe")["healing_received"] == 0.0


def test_talon_q_heals_self_once_at_the_per_level_row():
    """Noxian Diplomacy heals Talon himself on a kill at the per-LEVEL row
    (9 : 60.41 based on level — 55 at level 18); the fabricated ally
    packet is gone."""
    res = _fight("Talon", with_ally=True)
    heals = _main_heals(res, "Noxian Diplomacy")
    assert len(heals) == 1
    assert heals[0]["amount"] == pytest.approx(55.0, abs=0.06)
    assert _survival(res, "main")["healing_received"] == pytest.approx(
        heals[0]["applied_amount"], abs=0.06
    )
    assert _support_heals(res, "Noxian Diplomacy") == []
    assert _survival(res, "ally:Ashe")["healing_received"] == 0.0


def test_yorick_q_heals_self_once_with_the_missing_health_formula():
    """Last Rites heals Yorick himself via the rule's live formula (per-
    level flat + per-rank missing-health share); the fabricated ally
    packet is gone."""
    res = _fight("Yorick", with_ally=True)
    heals = _main_heals(res, "Last Rites")
    assert len(heals) == 1
    assert heals[0]["applied_amount"] > 0.0
    assert _survival(res, "main")["healing_received"] == pytest.approx(
        heals[0]["applied_amount"], abs=0.06
    )
    assert _support_heals(res, "Last Rites") == []
    assert _survival(res, "ally:Ashe")["healing_received"] == 0.0


def test_kindred_w_hunters_vigor_heals_self_on_the_next_auto_and_never_an_ally():
    """Hunter's Vigor heals Kindred herself on the next basic attack at 100
    stacks (no autos in a one-rotation fight -> no event; sustained fight
    -> exactly one).  The fabricated 'Wolf's Frenzy' ally heal is gone."""
    res = _fight("Kindred", with_ally=True)
    assert _main_heals(res, "Hunter's Vigor") == []
    assert _support_heals(res, "Wolf's Frenzy") == []
    assert _support_heals(res, "Hunter's Vigor") == []
    # (the ally's non-zero healing_received in this fight is Kindred R's
    # Lamb's Respite scanner packet — a separate consistent-split slot
    # outside this issue's scope)

    sustained = _fight(
        "Kindred", with_ally=True, duration=8.0, auto_uptime=1.0, include_autos=True
    )
    vigors = _main_heals(sustained, "Hunter's Vigor")
    assert len(vigors) == 1
    assert vigors[0]["applied_amount"] > 0.0
    assert _support_heals(sustained, "Wolf's Frenzy") == []


def test_rakan_q_self_heal_wins_at_210_and_scanner_ally_branch_stays_at_80():
    """The champion rule owns Rakan's SELF heal at the per-LEVEL row (210
    at level 18, 3s after the Q marks a champion); the scanner's ALLY
    branch stays at its own rank-indexed amount (80).  1v1: exactly one
    self heal at 210 and no scanner packet; roster: self 210 once and one
    80 ally packet."""
    res = _fight(
        "Rakan",
        with_ally=True,
        ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
    )
    self_heals = _main_heals(res, "Gleaming Quill")
    assert len(self_heals) == 1
    assert self_heals[0]["amount"] == pytest.approx(210.0, abs=0.06)
    assert self_heals[0]["time"] == pytest.approx(3.0)
    assert _survival(res, "main")["healing_received"] == pytest.approx(210.0, abs=0.06)
    ally_heals = _support_heals(res, "Gleaming Quill")
    assert len(ally_heals) == 1
    assert ally_heals[0]["amount"] == pytest.approx(80.0, abs=0.06)
    assert ally_heals[0]["target"] == "ally:Ashe"
    assert ally_heals[0]["target_scope"] == "all_teammates"
    assert _survival(res, "ally:Ashe")["healing_received"] == pytest.approx(
        80.0, abs=0.06
    )

    res_1v1 = _fight(
        "Rakan",
        ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
    )
    assert len(_main_heals(res_1v1, "Gleaming Quill")) == 1
    assert _survival(res_1v1, "main")["healing_received"] == pytest.approx(
        210.0, abs=0.06
    )
    assert _support_heals(res_1v1, "Gleaming Quill") == []


# ---------------------------------------------------------------------------
# Compiled (optimizer) path parity for the fan-out
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("champion", ["Sona", "Janna", "Milio", "Rakan", "Sylas"])
def test_compiled_score_path_matches_legacy_receipt(champion):
    """The fan-out and the registry deferral ride both walks: the compiled
    optimizer path must deep-equal the legacy receipt for the 1v1 and the
    roster."""
    for with_ally in (False, True):
        data = get_champion(champion)
        params = FightParams.from_request(
            {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
        )
        enemies = [ChampionLoadout(champion="Ahri", level=18, role="mid").resolve()]
        allies = (
            [ChampionLoadout(champion="Ashe", level=18, role="bottom").resolve()]
            if with_ally
            else []
        )
        stats = calculate_total_stats(data, 18, [], role="mid")
        defenses = resolve_starting_defenses(champion, 18, stats, [])

        def timeline(**kwargs):
            return build_participant_timeline(
                data,
                18,
                [],
                params,
                main_stats=stats,
                main_defenses=defenses,
                enemies=enemies,
                allies=allies,
                **kwargs,
            )

        legacy_score = timeline(include_receipt=False)
        fast = timeline(
            pair_result_cache={},
            include_receipt=False,
            search_context=CoupledSearchContext(),
        )
        assert fast == legacy_score
