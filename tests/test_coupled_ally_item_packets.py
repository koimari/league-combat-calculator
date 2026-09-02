"""Imperial Mandate and Echoes of Helia, priced from a *roster ally*.

Both items are classified fully modelled, and the half nothing pinned by
number was the one that matters for a coupled fight: the item sits on an ally
and the packet it authors lands on somebody else.  This file is that half,
driven through the public request path so the numbers quoted are the ones the
API publishes.

Three things are asserted and each is a different kind of claim.

* **The packet's number is the cached sentence.**  Soul Siphon is "30% of
  pre-mitigation damage dealt to champions ... up to 80 to 250", so the heal
  is re-derived here from the published ``raw_damage`` of the holder's own
  events and from the sourced ramp, on both sides of the cap.
* **A trigger-less fight prices nothing.**  Command needs an authored
  immobilize and Soul Siphon needs an authored heal or shield onto an ally;
  a roster whose ally holds the item and never does that is bit-identical to
  one holding nothing.  Item held is not item fired.
* **Neither item deals damage.**  Command is an amplifier and the current
  Soul Siphon is a heal conversion — the damage half the Wiki carried before
  the item was reworked is gone from the cached record, and no packet or
  breakdown row may reintroduce it.

:class:`TestDeclaredRampSubjects` is the fourth thing and the one that pays
on patch day: every level ramp's declared :class:`LevelSubject` is read back
out of the ``{{pp|…|type=…}}`` qualifier in its owner's cached branch text,
joined to the ramp by the two numbers the registry holds for it.  A patch
that re-scales one of these turns this red instead of moving a number quietly.
"""

from __future__ import annotations

import re

import pytest

from src import app as app_module
from src.calculator import item_behavior_catalog as catalog
from src.calculator import item_source
from src.calculator.data_fetcher import fetch_item_data
from src.calculator.item_behavior import LevelSubject
from src.calculator.item_effects import ally_item_effect_value, ally_item_level_value

HELIA = "Echoes of Helia"
MANDATE = "Imperial Mandate"

# One holder per behaviour, chosen for what its kit authors rather than for
# its build: Sona's W is an ally heal (Soul Siphon's trigger), Syndra's E is a
# stun (Command's), and Ahri and Garen author neither while still fighting.
HEAL_HOLDER = "Sona"
NO_HEAL_HOLDER = "Ahri"
IMMOBILIZE_HOLDER = "Syndra"
NO_IMMOBILIZE_HOLDER = "Garen"


def _roster(ally: str, ally_items: tuple[str, ...], *, main: str, duration: int = 8):
    """One coupled response through the public request path."""
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": main,
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": duration,
            "include_auto_attacks": False,
            "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
            "allies": [
                {
                    "champion": ally,
                    "level": 18,
                    "items": list(ally_items),
                    "ally_effects_enabled": True,
                }
            ],
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    return response.get_json()


def _packets(response, source: str) -> list[dict]:
    """Every walk packet the roster published for one item mechanic."""
    return [
        event
        for event in response["combat"]["support_events"]
        if event["source"] == source
    ]


def _outgoing(response, participant_id: str) -> dict[str, float]:
    """One participant's per-source outgoing damage, by row name."""
    row = next(
        entry
        for entry in response["combat"]["breakdown"]
        if entry.get("participant_id") == participant_id
    )
    return {source["name"]: source["total_damage"] for source in row.get("sources", ())}


class TestSoulSiphonPricesTheHoldersCharges:
    """Echoes of Helia on an ally, through the coupled walk."""

    SOURCE = f"{HELIA} — Soul Siphon"

    def test_the_heal_is_thirty_percent_of_the_holders_pre_mitigation_damage(self):
        """The sentence: gain 30% of pre-mitigation damage as charges."""
        response = _roster(HEAL_HOLDER, (HELIA,), main="Ahri")
        raw = sum(
            event.get("raw_damage") or event["damage"]
            for event in response["combat"]["events"]
            if event.get("attacker") == f"ally:{HEAL_HOLDER}"
        )
        ratio = ally_item_effect_value(HELIA, "charge_damage_ratio")
        packet = next(iter(_packets(response, self.SOURCE)))
        assert raw == pytest.approx(775.5)
        assert packet["amount"] == pytest.approx(raw * ratio)
        assert packet["amount"] == pytest.approx(232.65)
        # The heal *is* the consumed pool: "consumes all charges to heal them
        # equal to the consumed amount".
        assert packet["charges_consumed"] == packet["amount"]
        assert packet["kind"] == "heal"

    def test_a_longer_fight_stops_at_the_holders_own_sourced_cap(self):
        """The cap is "up to {{pp|80 to 250}}" — unqualified, so the holder's."""
        response = _roster(HEAL_HOLDER, (HELIA,), main="Ahri", duration=15)
        packet = next(iter(_packets(response, self.SOURCE)))
        assert packet["amount"] == pytest.approx(
            ally_item_level_value(HELIA, "charge_cap_min", "charge_cap_max", 18)
        )
        assert packet["amount"] == pytest.approx(250.0)

    def test_a_holder_who_never_heals_an_ally_prices_nothing(self):
        """Charges without a heal or shield stay charges."""
        held = _roster(NO_HEAL_HOLDER, (HELIA,), main="Pantheon")
        assert _packets(held, self.SOURCE) == []
        # ...and the fight is the one the empty-handed roster runs.
        bare = _roster(NO_HEAL_HOLDER, (), main="Pantheon")
        assert held["headline_total"] == bare["headline_total"]

    def test_the_current_item_authors_no_damage_anywhere(self):
        """The pre-rework damage half is gone from the cached record.

        The live text converts damage *into* a heal and nothing else — no
        charges consumed into magic damage on the nearest enemy — so the
        item's only reachable packet kind is a heal, asserted against the
        cached sentence rather than against a memory of which patch removed
        the damage half.
        """
        response = _roster(HEAL_HOLDER, (HELIA,), main="Ahri")
        assert {packet["kind"] for packet in _packets(response, self.SOURCE)} == {
            "heal"
        }
        assert not any(
            HELIA in name
            for entry in response["combat"]["breakdown"]
            if entry.get("participant_id")
            for name in _outgoing(response, entry["participant_id"])
        )
        text = " ".join(
            item_source.effect_text(passive)
            for passive in _cached(HELIA).get("passives", ())
        )
        assert "consumes all charges to heal them" in text
        assert "magic damage" not in text


class TestCommandAmpsTheMainChampionFromAnAlly:
    """Imperial Mandate on an ally: the half the pair engine cannot see."""

    SOURCE = f"{MANDATE} — Command"

    def test_the_mark_amplifies_the_main_champions_own_rows(self):
        """The sentence: the mark increases damage from all sources by 7%."""
        held = _roster(IMMOBILIZE_HOLDER, (MANDATE,), main="Pantheon")
        bare = _roster(IMMOBILIZE_HOLDER, (), main="Pantheon")
        amp = ally_item_effect_value(MANDATE, "command_damage_amp")
        packet = next(iter(_packets(held, self.SOURCE)))
        assert packet["owner"] == f"ally:{IMMOBILIZE_HOLDER}"
        assert packet["amount"] == pytest.approx(amp)
        assert packet["duration"] == pytest.approx(
            ally_item_effect_value(MANDATE, "command_duration")
        )
        # Pantheon's Comet Spear is the one row that lands inside the window
        # the ally's stun opened; everything before it is priced unamplified.
        before = _outgoing(bare, "main")
        after = _outgoing(held, "main")
        assert after["Comet Spear"] == pytest.approx(
            before["Comet Spear"] * (1.0 + amp), rel=1e-3
        )
        assert after["Comet Spear"] == pytest.approx(209.1)
        assert before["Comet Spear"] == pytest.approx(195.5)
        # Every other row is bit-identical: the window is a window, not a
        # fight-wide multiplier.
        assert {
            name: value for name, value in after.items() if name != "Comet Spear"
        } == {name: value for name, value in before.items() if name != "Comet Spear"}

    def test_an_ally_who_immobilizes_nothing_prices_nothing(self):
        """Held is not fired: no authored immobilize, no mark, no amp."""
        held = _roster(NO_IMMOBILIZE_HOLDER, (MANDATE,), main="Pantheon")
        bare = _roster(NO_IMMOBILIZE_HOLDER, (), main="Pantheon")
        assert _packets(held, self.SOURCE) == []
        assert _outgoing(held, "main") == _outgoing(bare, "main")

    def test_command_authors_an_amplifier_and_never_a_damage_packet(self):
        """The mechanic is a multiplier; no row may carry it as damage."""
        held = _roster(IMMOBILIZE_HOLDER, (MANDATE,), main="Pantheon")
        packets = _packets(held, self.SOURCE)
        assert packets
        assert all(packet["kind"] == "damage_modifier" for packet in packets)
        assert all(packet["multiplier"] > 1.0 for packet in packets)


def _cached(name: str) -> dict:
    """One cached item record, read through the caching layer (rule 2)."""
    return next(item for item in fetch_item_data().values() if item.get("name") == name)


def _qualifiers(name: str) -> dict[tuple[float, float], str]:
    """Every ``{{pp|…}}`` in an item's cached text, by the two ends it names.

    The join is the ramp's own numbers rather than its position, because an
    item with two ramps (Dream Maker's bubbles) has two qualifiers and only
    the numbers say which is which.  An omitted ``type=`` is the Wiki's
    unqualified "based on level", which for an item passive is its holder's.
    """
    record = _cached(name)
    text = " ".join(
        item_source.effect_text(effect)
        for effect in (*record.get("passives", ()), *record.get("active", ()))
    )
    found: dict[tuple[float, float], str] = {}
    for fragment in re.findall(r"\{\{pp\|([^{}]*)\}\}", text):
        ends = re.match(r"\s*(\d+(?:\.\d+)?) to (\d+(?:\.\d+)?)", fragment)
        if ends is None:
            continue
        qualifier = re.search(r"type=([^|}]+)", fragment)
        found[(float(ends.group(1)), float(ends.group(2)))] = (
            qualifier.group(1).strip() if qualifier else LevelSubject.HOLDER.value
        )
    return found


class TestDeclaredRampSubjects:
    """Whose level scales a packet is the source's answer, not the emitter's."""

    @staticmethod
    def _ramps():
        for producer, declaration in catalog.ALLY_PACKET_DECLARATIONS.items():
            for owner in catalog.owners_for(producer):
                for ramp in declaration.ramps:
                    yield producer, owner, ramp

    def test_every_declared_subject_is_the_cached_qualifier(self):
        checked = 0
        for producer, owner, ramp in self._ramps():
            ends = (
                ally_item_effect_value(owner, ramp.min_key),
                ally_item_effect_value(owner, ramp.max_key),
            )
            qualifiers = _qualifiers(owner)
            assert ends in qualifiers, (
                f"{owner}'s cached text carries no {{{{pp}}}} for "
                f"{producer.value}'s {ends} ramp"
            )
            assert qualifiers[ends] == ramp.subject.value, (
                f"{producer.value} declares {ramp.subject.value} and "
                f"{owner}'s cached record now reads {qualifiers[ends]!r}"
            )
            checked += 1
        assert checked == 7, "every live ally-packet ramp is covered"

    def test_the_two_populations_are_both_non_empty(self):
        """A vocabulary only one member of which is ever used is a constant."""
        subjects = {ramp.subject for _producer, _owner, ramp in self._ramps()}
        assert subjects == {LevelSubject.HOLDER, LevelSubject.RECIPIENT}
