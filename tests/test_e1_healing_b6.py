"""Sourced self-heal rules (E1 heal-rule batch b6).

One test per champion pins the heal event against values traced to
``data/champions.json`` (leveling attributes + description formulas) in a
``/api/calculate`` fight at level 18.

Implemented:
- Briar   — E Chilling Scream: "Heal Per Tick" 2.5%-4% max health per
  tick (4 ticks, "Maximum Heal" 10%-16% max health).
- Warwick — Q Jaws of the Beast: "Healing Percentage" 25%-75% of the
  post-mitigation damage dealt.
- Karma   — Mantra W Renewal: "Karma heals for 17% (+ 1% per 100 AP) of
  her missing health once on-cast, and again once the tether lasts its
  full duration" (2-second tether).
- Nami    — W Ebb and Flow: the first bounce returns to Nami at 80% of
  the base Heal ("each bounce modifying the effectiveness of the next by
  -20% (+ 15% per 100 AP)"), floored at "Minimum Heal".
- Nilah   — Q passive / R Apotheosis: 0%-20% / 20%-50% (based on
  critical strike chance) of the post-mitigation damage dealt to
  champions.
- Zaahen  — Q The Darkin Glaive: "Champion Healing" 5%-9% of his
  maximum health; R Grim Deliverance: "Healing per Champion hit"
  82.5 / 132 / 181.5 (+ 66% bonus AD).

Deliberately skipped (no sourced self-heal fits the 1v1 fight ledger):
- KSante      — no healing anywhere in the kit data (P/Q/W/E/R are
  damage/shield/buff only).
- Locke       — W Soul Ignition's grey-health heal is authored by the
  E8a grey-health primitive instead (participant_timeline, see
  tests/test_p1_review_1.py): 100% of the post-mitigation damage he
  *takes* during the 6s W active is stored (capped by the sourced
  "Damage taken grey health cap" row) and healed at the automatic 6s
  recast; the health-cost add and missing-health bonus remain dynamic
  self-state boundaries.
- Mordekaiser — W Indestructible's recast heal prices a shield built
  from damage dealt AND taken (taken term not in the ledger, exponential
  shield decay is state), and R Realm of Death heals 10% of the
  *target's* maximum health (target stats are not passed to the heal
  derivation).  Neither W nor R is modeled by the champion module, so no
  trigger event exists either.
"""

import pytest

from src import app as app_module

_ENEMY_NAMES = ["Ahri", "Annie", "Orianna"]


def _fight(
    champion: str,
    *,
    role: str = "mid",
    level: int = 18,
    ranks: dict | None = None,
    items: list[str] | None = None,
    options: dict | None = None,
    enemies: int = 1,
) -> dict:
    payload = {
        "champion": champion,
        "level": level,
        "items": items or [],
        "role": role,
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "enemies": [
            {
                "champion": _ENEMY_NAMES[index % len(_ENEMY_NAMES)],
                "level": 18,
                "items": [],
                "role": "mid",
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            }
            for index in range(enemies)
        ],
    }
    if ranks is not None:
        payload["ability_ranks"] = ranks
    if options is not None:
        payload["champion_options"] = options
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["combat"]


def _main_heals(combat: dict) -> list[dict]:
    return [e for e in combat.get("healing_events", []) if e.get("attacker") == "main"]


def _main_stats(combat: dict) -> dict:
    return next(
        p["stats"] for p in combat["participants"] if p["participant_id"] == "main"
    )


def _main_events(combat: dict, source: str) -> list[dict]:
    return [
        e
        for e in combat.get("events", [])
        if e.get("attacker") == "main" and e.get("source") == source
    ]


# ---------------------------------------------------------------------------
# Briar — E Chilling Scream
# ---------------------------------------------------------------------------


def test_briar_chilling_scream_heals_percent_of_max_health_per_tick():
    """E rank 5: "Heal Per Tick" = 4 (% max health), "Maximum Heal" = 16
    (% max health) -> 4 ticks of 4% max health every 0.25s."""
    combat = _fight("Briar", role="top", ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    heals = [h for h in _main_heals(combat) if h["source"] == "Chilling Scream"]
    assert heals, "Chilling Scream heal missing"
    max_health = _main_stats(combat)["health"]
    per_tick = 0.04 * max_health
    assert heals[0]["amount"] == pytest.approx(per_tick, rel=0.01)
    assert [round(h["time"], 2) for h in heals] == [0.25, 0.5, 0.75, 1.0]
    assert all(h["amount"] == pytest.approx(per_tick, rel=0.01) for h in heals)


# ---------------------------------------------------------------------------
# Warwick — Q Jaws of the Beast
# ---------------------------------------------------------------------------


def test_warwick_jaws_of_the_beast_heals_ranked_percentage_of_damage():
    """Q rank 5: "Healing Percentage" = 75 of the post-mitigation damage
    dealt (wiki: "healing himself for a percentage of the post-mitigation
    damage dealt")."""
    combat = _fight("Warwick", role="top", ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    q_events = _main_events(combat, "Q")
    q_heals = [h for h in _main_heals(combat) if h["source"] == "Jaws of the Beast"]
    assert q_events and q_heals
    assert len(q_heals) == len(q_events)
    for heal, event in zip(q_heals, q_events):
        assert heal["amount"] == pytest.approx(0.75 * event["damage"], rel=0.01)


# ---------------------------------------------------------------------------
# Karma — Mantra W Renewal (missing-health heal)
# ---------------------------------------------------------------------------


def _karma_renewal_heals(combat: dict) -> list[dict]:
    return [h for h in _main_heals(combat) if h["source"] == "Renewal"]


def test_karma_renewal_heals_missing_health_on_cast_and_tether_completion():
    """Renewal (Mantra W) heals 17% (+ 1% per 100 AP) of missing health
    once on-cast and again when the 2-second tether completes.  With no
    items AP = 0, so every heal is 17% of the missing health priced by the
    coupled timeline at its timestamp."""
    combat = _fight("Karma", role="mid", options={"w_renewal": True})
    heals = _karma_renewal_heals(combat)
    # One W cast in a 10s window -> exactly two Renewal heals.
    assert len(heals) == 2
    assert [round(h["time"], 2) for h in heals] == [0.25, 2.25]
    max_health = _main_stats(combat)["health"]
    for heal in heals:
        assert 0.0 < heal["raw_amount"]
        assert heal["raw_amount"] <= 0.17 * max_health + 1e-9
    # The main is damaged by the enemy before the first heal, so the
    # missing-health formula must price a positive amount that matches the
    # sourced 17% ratio against the incoming damage the fight exposes.
    incoming_before_cast = sum(
        e["damage"]
        for e in combat["events"]
        if e.get("target") == "main" and e.get("time", 0.0) <= 0.25
    )
    assert heals[0]["raw_amount"] == pytest.approx(
        0.17 * incoming_before_cast, rel=0.01
    )
    # The tether-completion heal lands after more incoming damage and the
    # on-cast heal, so it prices strictly more missing health.
    assert heals[1]["raw_amount"] > heals[0]["raw_amount"]


def test_karma_renewal_ratio_scales_with_ap():
    """The sourced formula "17% (+ 1% per 100 AP)" must widen the heal
    exactly: the heal must grow by (0.17 + AP/10000)/0.17 with the fight's
    own AP (Deathcap amplifies its flat 120 AP by +40%)."""
    plain = _fight("Karma", role="mid", options={"w_renewal": True})
    ap = _fight(
        "Karma",
        role="mid",
        options={"w_renewal": True},
        items=["Rabadon's Deathcap"],
    )
    plain_heals = _karma_renewal_heals(plain)
    ap_heals = _karma_renewal_heals(ap)
    assert plain_heals and ap_heals
    # Deathcap's passive raises the build's total AP above the item's flat
    # 120; use the fight's own sourced AP so the ratio is exact.
    ap = _main_stats(ap)["ability_power"]
    ratio_gain = (0.17 + ap / 10000.0) / 0.17
    assert ap_heals[0]["raw_amount"] == pytest.approx(
        plain_heals[0]["raw_amount"] * ratio_gain, rel=0.01
    )


def test_karma_focused_resolve_has_no_renewal_heal():
    """Without the Mantra toggle the W is Focused Resolve (damage only);
    no Renewal heal may be authored."""
    combat = _fight("Karma", role="mid")
    assert not _karma_renewal_heals(combat)


# ---------------------------------------------------------------------------
# Nami — W Ebb and Flow
# ---------------------------------------------------------------------------


def test_nami_ebb_and_flow_heals_first_bounce_amount():
    """W rank 5: base "Heal" = 155, "Minimum Heal" = 93.  Cast on the
    enemy, the stream's first bounce returns to Nami at 80% effectiveness
    ("each bounce modifying the effectiveness of the next by -20%
    (+ 15% per 100 AP)" of the original): 155 x 0.8 = 124 >= 93."""
    combat = _fight("Nami", role="mid", ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    heals = [h for h in _main_heals(combat) if h["source"] == "Ebb and Flow"]
    assert heals, "Ebb and Flow heal missing"
    assert all(h["amount"] == pytest.approx(124.0, rel=0.01) for h in heals)


# ---------------------------------------------------------------------------
# Nilah — Q passive and R Apotheosis
# ---------------------------------------------------------------------------


def test_nilah_apotheosis_heals_twenty_percent_of_post_mitigation_damage():
    """At 0% critical strike chance R heals for the sourced floor: 20% of
    the post-mitigation damage dealt to champions.  The Q passive heal is
    0%-20% based on crit, so at 0 crit no Formless Blade heal may appear."""
    combat = _fight("Nilah", role="mid", ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    r_events = _main_events(combat, "R")
    r_heals = [h for h in _main_heals(combat) if h["source"] == "Apotheosis"]
    assert r_events and r_heals
    assert len(r_heals) == len(r_events)
    for heal, event in zip(r_heals, r_events):
        assert heal["amount"] == pytest.approx(0.20 * event["damage"], rel=0.02)
    assert not [h for h in _main_heals(combat) if h["source"] == "Formless Blade"]


def test_nilah_formless_blade_heal_scales_with_critical_strike_chance():
    """Cloak of Agility gives 15% crit: the Q passive heal is
    0%-20% linearly -> 3% of post-mitigation damage; R is 20%-50%
    linearly -> 24.5% of post-mitigation damage."""
    combat = _fight(
        "Nilah",
        role="mid",
        ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        items=["Cloak of Agility"],
    )
    assert _main_stats(combat)["critical_strike_chance"] == pytest.approx(15.0)
    q_events = _main_events(combat, "Q")
    q_heals = [h for h in _main_heals(combat) if h["source"] == "Formless Blade"]
    assert q_events and q_heals
    assert q_heals[0]["amount"] == pytest.approx(0.03 * q_events[0]["damage"], rel=0.02)
    r_events = _main_events(combat, "R")
    r_heals = [h for h in _main_heals(combat) if h["source"] == "Apotheosis"]
    assert r_events and r_heals
    assert r_heals[0]["amount"] == pytest.approx(
        0.245 * r_events[0]["damage"], rel=0.02
    )


# ---------------------------------------------------------------------------
# Zaahen — Q The Darkin Glaive and R Grim Deliverance
# ---------------------------------------------------------------------------


def test_zaahen_darkin_glaive_heals_percent_of_maximum_health():
    """Q rank 5: "Champion Healing" = 9 (% of his maximum health)."""
    combat = _fight("Zaahen", role="top", ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    heals = [h for h in _main_heals(combat) if h["source"] == "The Darkin Glaive"]
    assert heals, "Darkin Glaive heal missing"
    max_health = _main_stats(combat)["health"]
    assert all(h["amount"] == pytest.approx(0.09 * max_health, rel=0.01) for h in heals)


def test_zaahen_grim_deliverance_heals_flat_per_champion_hit():
    """R rank 3: "Healing per Champion hit" = 181.5 (no bonus AD)."""
    combat = _fight("Zaahen", role="top", ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    heals = [h for h in _main_heals(combat) if h["source"] == "Grim Deliverance"]
    assert heals, "Grim Deliverance heal missing"
    assert all(h["amount"] == pytest.approx(181.5, rel=0.01) for h in heals)


# ---------------------------------------------------------------------------
# Deliberately skipped champions — no sourced self-heal in the 1v1 ledger
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("champion", "role"),
    [
        # KSante's P/Q/W/E/R carry damage, shields and buffs only — the
        # kit has no heal term at all in data/champions.json (its All Out
        # 20% omnivamp is priced by the engine's omnivamp channel instead,
        # see tests/test_p1_review_1.py).
        ("KSante", "top"),
        # Locke W's grey-health heal is now implemented by the E8a
        # grey-health primitive (see tests/test_p1_review_1.py) — Locke
        # authors a heal and no longer belongs in this list.
        # Mordekaiser's W recast heal is now implemented by the E8a
        # grey-health primitive (see tests/test_e8_grey_health.py); its R
        # heals 10% of the TARGET's maximum health and stays out of the
        # self-heal rule set.
    ],
)
def test_champion_without_sourced_1v1_self_heal_authors_nothing(champion, role):
    combat = _fight(champion, role=role, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
    assert not _main_heals(combat)
