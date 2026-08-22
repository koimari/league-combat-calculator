"""W3 — the ally-support scanner grants to whoever its sentence names.

A leveling row used to default to ``one_teammate`` whenever its declaring
sentence named no ally, so six casts arrived in served results as a heal or
shield on an ally the game never gives one:

    Bel'Veth R, Cassiopeia E, Ekko W, Locke W, Vladimir R, Zilean R

``support_effects._row_target`` reads the sentence now.  Three of the six
are self grants their sentences declare; the other three are already paid
by another owner and defer to it.  The two ally grants whose sentence names
no ally -- Kindred R and Zilean R -- keep their packets through a named
registry, which is what this file pins alongside the six.

The claim is the ledger, not the emitter: every absence and every presence
below is read off ``/api/calculate``'s coupled walk unless the test says it
is pricing the row (``derive_ally_effects`` with quoted stats).
"""

import pytest

from src import app as app_module
from src.calculator.champions.zilean import starting_revive_defense
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from src.calculator.support_effects import (
    _ALLY_PROSE,
    _MODULE_AUTHORED_HEAL_SLOTS,
    _SCOPE_OVERRIDES,
    _row_target,
    derive_ally_effects,
)

# The six casts whose ally packet was a fabrication, with the sentence that
# declares the row (cached ``data/champions.json`` prose, lowercased here as
# ``_row_prose`` reads it).
FABRICATED_ALLY_PACKETS = [
    (
        "Bel'Veth",
        "R",
        "Endless Banquet",
        "consuming a void coral refreshes the duration of true form and "
        "heals bel'veth",
    ),
    (
        "Cassiopeia",
        "E",
        "Twin Fang",
        "twin fang deals bonus magic damage and heals cassiopeia",
    ),
    (
        "Ekko",
        "W",
        "Parallel Convergence",
        "it detonates to grant him a shield for 2 seconds",
    ),
    (
        "Locke",
        "W",
        "Soul Ignition",
        "locke ends soul ignition and consumes his grey health to heal for "
        "the same amount",
    ),
    (
        "Vladimir",
        "R",
        "Hemoplague",
        "heal vladimir for each infected champion",
    ),
    (
        "Zilean",
        "R",
        "Chronoshift",
        "zilean places a protective time rune on the target allied champion "
        "or himself",
    ),
]


def _coupled(champion, *, allies=("Jinx",), items=(), duration=12.0):
    """One coupled walk with *champion* as main and *allies* on the roster."""
    payload = {
        "champion": champion,
        "level": 18,
        "items": list(items),
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": True,
        "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        "allies": [
            {
                "champion": ally,
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            }
            for ally in allies
        ],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    return response.get_json()["combat"]


def _grants(combat, source_prefix):
    """Every heal/shield the main published from *source_prefix*."""
    return [
        event
        for event in combat["support_events"]
        if event["attacker"] == "main"
        and event["kind"] in {"heal", "shield"}
        and event["source"].startswith(source_prefix)
    ]


def _priced(champion, slot, *, ability_power=200.0):
    """The scanner's own rows for one cast of *slot*, at quoted stats."""
    data = get_champion(champion)
    stats = calculate_total_stats(data, 18, [])
    stats["ability_power"] = ability_power
    return derive_ally_effects(data, 18, stats, [{"slot": slot, "time": 1.0}])


# ---------------------------------------------------------------------------
# The six: no ally receives what the kit never grants an ally
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("champion", "slot", "ability", "sentence"),
    FABRICATED_ALLY_PACKETS,
    ids=[f"{name}-{slot}" for name, slot, _ability, _s in FABRICATED_ALLY_PACKETS],
)
def test_no_ally_is_granted_a_packet_its_sentence_never_gave_them(
    champion, slot, ability, sentence
):
    """No sentence of these six grants an ally anything, so no ally gets it.

    ``sentence`` is the cached prose the row is read from, carried here so a
    wiki rewrite that turns one of these INTO an ally grant fails loudly
    rather than quietly restoring the fabrication.
    """
    prose = " ".join(
        str(effect.get("description", "")).lower()
        for effect in get_champion(champion)["abilities"][slot][0].get("effects", [])
    )
    assert sentence in prose

    combat = _coupled(champion, items=["Rabadon's Deathcap"])
    to_allies = [
        event for event in _grants(combat, ability) if event["recipient"] != "main"
    ]
    assert to_allies == [], f"{champion} {slot} still grants an ally {to_allies}"


# ---------------------------------------------------------------------------
# Three of the six are self grants; the ledger owner is the scanner
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("champion", "slot", "ability", "attribute", "kind", "amount"),
    [
        # True Form "Heal" 100/250/400 (+150% bonus AD) (+150% AP), rank 3,
        # 200 AP and no bonus AD: 400 + 300.
        ("Bel'Veth", "R", "Endless Banquet", "Heal", "heal", 700.0),
        # Twin Fang "Heal" 10/11.5/13/14.5/16% AP, rank 5, 200 AP: 32.0.
        ("Cassiopeia", "E", "Twin Fang", "Heal", "heal", 32.0),
        # Parallel Convergence "Shield Strength" 100/120/140/160/180
        # (+150% AP), rank 5, 200 AP: 180 + 300.
        ("Ekko", "W", "Parallel Convergence", "Shield Strength", "shield", 480.0),
    ],
)
def test_the_sentence_that_names_only_the_caster_prices_a_self_grant(
    champion, slot, ability, attribute, kind, amount
):
    rows = [row for row in _priced(champion, slot) if row["slot"] == slot]

    assert rows, f"{champion} {slot} priced nothing"
    assert len(rows) == 1
    assert rows[0]["kind"] == kind
    assert rows[0]["source"] == f"{ability} · {attribute}"
    assert rows[0]["target_scope"] == "self"
    assert rows[0]["amount"] == pytest.approx(amount)


@pytest.mark.parametrize(
    ("champion", "slot", "ability", "kind", "amount"),
    [
        # The same rows at 0 AP, arriving on the main in the coupled walk.
        # Cassiopeia's is absent: Twin Fang's heal is an AP share alone, so
        # a no-item Cassiopeia heals for 0 and the packet is dropped.
        ("Bel'Veth", "R", "Endless Banquet", "heal", 400.0),
        ("Ekko", "W", "Parallel Convergence", "shield", 180.0),
    ],
)
def test_a_self_grant_reaches_the_caster_in_the_coupled_walk(
    champion, slot, ability, kind, amount
):
    combat = _coupled(champion)
    published = [event for event in _grants(combat, ability) if event["kind"] == kind]

    assert published, f"{champion} {slot} published no {kind}"
    assert {event["recipient"] for event in published} == {"main"}
    assert published[0]["amount"] == pytest.approx(amount)
    assert published[0]["target_scope"] == "self"


def test_cassiopeia_heals_herself_on_every_twin_fang_of_the_walk():
    """Twin Fang's heal is 16% AP at rank 5 and nothing else, so it needs an
    AP item to be visible at all: one Rabadon's (169 AP) is 27.04 a cast, to
    Cassiopeia, on each of the walk's thirteen casts."""
    combat = _coupled("Cassiopeia", items=["Rabadon's Deathcap"])
    published = _grants(combat, "Twin Fang")

    assert len(published) == 13
    assert {event["recipient"] for event in published} == {"main"}
    assert {event["target_scope"] for event in published} == {"self"}
    assert {round(event["amount"], 2) for event in published} == {27.04}


# ---------------------------------------------------------------------------
# The other three defer: one owner per grant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("champion", "slot", "ability", "owner_source"),
    [
        # The healing rule's Hemoplague receipt (full amount, with the
        # reduced copy attached for later roster targets).
        ("Vladimir", "R", "Hemoplague", "Hemoplague"),
        # The participant timeline's grey-health payback, authored off the
        # INCOMING ledger (``GREY_HEALTH_RULE_CHAMPIONS``).
        ("Locke", "W", "Soul Ignition", "Soul Ignition (grey health)"),
    ],
)
def test_a_slot_whose_owner_already_pays_emits_nothing_from_the_scanner(
    champion, slot, ability, owner_source
):
    assert (champion, slot) in _MODULE_AUTHORED_HEAL_SLOTS
    assert [row for row in _priced(champion, slot) if row["slot"] == slot] == []

    combat = _coupled(champion, items=["Rabadon's Deathcap"])
    assert _grants(combat, ability) == []
    paid = [
        event
        for event in combat["healing_events"]
        if event.get("attacker") == "main" and event.get("source") == owner_source
    ]
    assert paid, f"{champion} {slot} lost its owner's receipt too"
    assert max(float(event["amount"]) for event in paid) > 0.0


def test_zilean_r_is_the_revive_channel_and_not_a_scanner_packet():
    """Chronoshift has one home: the sourced revive state.

    "If the target takes fatal damage within the duration, they enter
    resurrection ... Afterwards, they revive while being healed" is the row
    ``zilean.starting_revive_defense`` reads; the scanner emitted the same
    1100 as a second, unconditional heal on a teammate.
    """
    assert ("Zilean", "R") in _MODULE_AUTHORED_HEAL_SLOTS
    assert [row for row in _priced("Zilean", "R") if row["slot"] == "R"] == []
    assert _grants(_coupled("Zilean"), "Chronoshift") == []

    revive = starting_revive_defense(18, {"ability_power": 0.0})
    assert revive["revive_health_amount"] == pytest.approx(1100.0)
    assert revive["revive_delay"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# The genuine ally grant the general rule would have lost
# ---------------------------------------------------------------------------


def test_kindred_r_heals_every_selected_teammate():
    """ "All targetable units within the zone are healed when the blessing
    ends" names no ally, so the scope override is what keeps the packet --
    and "all units" is every selected teammate, not the first one.

    "Heal" 225/300/375 at rank 3, flat (no AP term), so both allies read the
    same 375 the healing rule pays Kindred herself.
    """
    assert _SCOPE_OVERRIDES[("Kindred", "R")] == "all_teammates"

    combat = _coupled("Kindred", allies=("Jinx", "Ashe"))
    published = _grants(combat, "Lamb's Respite")

    assert {event["recipient"] for event in published} == {"ally:Jinx", "ally:Ashe"}
    assert {event["target_scope"] for event in published} == {"all_teammates"}
    assert [event["amount"] for event in published] == [
        pytest.approx(375.0),
        pytest.approx(375.0),
    ]
    self_copy = [
        event
        for event in combat["healing_events"]
        if event.get("attacker") == "main" and event.get("source") == "Lamb's Respite"
    ]
    assert len(self_copy) == 1
    assert self_copy[0]["amount"] == pytest.approx(375.0)


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


class TestTheRecipientRule:
    """``_row_target``'s three answers, and the ally test's one narrowing."""

    def _resolve(self, prose, champion="Ekko"):
        return _row_target(
            prose,
            champion=champion,
            scope="one_teammate",
            target_self=False,
            override=None,
        )

    def test_a_named_ally_lets_the_row_leave_the_caster(self):
        assert self._resolve("grants a shield to the target allied champion") == (
            "one_teammate",
            False,
        )
        assert self._resolve("heals allies") == ("one_teammate", False)
        assert self._resolve("shields her teammates") == ("one_teammate", False)

    def test_only_the_caster_named_is_a_self_grant(self):
        assert self._resolve("it detonates to grant him a shield") == ("self", True)
        assert self._resolve(
            "consuming a void coral heals bel'veth", champion="Bel'Veth"
        ) == ("self", True)
        assert self._resolve("she heals herself") == ("self", True)

    def test_a_sentence_naming_no_recipient_is_refused(self):
        assert self._resolve("they revive while being healed") is None
        assert self._resolve("all targetable units within the zone are healed") is None

    def test_an_override_still_wins_over_the_sentence(self):
        assert _row_target(
            "they revive while being healed",
            champion="Zilean",
            scope="one_teammate",
            target_self=False,
            override="all_teammates",
        ) == ("all_teammates", False)

    def test_allied_alone_is_not_a_recipient(self):
        """Bel'Veth R's True Form sentence ends "...spawn from allied and
        enemy minions that die nearby" -- "allied" qualifying a noun that
        receives nothing used to carry her heal to a teammate."""
        assert _ALLY_PROSE.search("allied and enemy minions that die nearby") is None
        assert _ALLY_PROSE.search("the target allied champion") is not None
        assert _ALLY_PROSE.search("all allied units") is not None
