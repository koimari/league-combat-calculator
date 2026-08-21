"""When a persistent cross-participant aura arms (C4, D-05/D-06/D-63).

A ``damage_modifier`` some trigger armed is a debuff: it resolves after the
damage at its own timestamp, because the packet that triggered it landed
first.  A *persistent* one was already in force when the fight opened, so
the same ordering makes the opening exchange the one exchange the aura does
not price — which is what Abyssal Mask's Unmake did.

``TransitionRank.AURA_ARM`` is the rank that says so, at legacy phase -0.5,
between the barriers and the damage; ``item_support_effects._packet``
refuses a persistent modifier that does not declare it; and the ladder's new
member publishes the participant ledger's seventh phase name, which is the
change ``CAPABILITY_SCHEMA_VERSION`` moved to 2 to announce.
"""

import pytest

from src import app as app_module
from src.calculator.ability_spec import AttackClass, Authority, DamageClass
from src.calculator.capabilities import (
    CAPABILITY_SCHEMA_VERSION,
    PARTICIPANT_LEDGER_CONTRACT,
)
from src.calculator import item_support_effects
from src.calculator.item_support_effects import (
    SUPPORT_RANK_KEY,
    derive_item_support_effects,
)
from src.calculator.survival.actions import (
    TransitionRank,
    ordering_slot,
    public_phase,
    support_transition_rank,
)

from tests.test_item_support_effects import _ABYSSAL_ROSTER, _actor

UNMAKE = "Abyssal Mask — Unmake"


class TestTheAuraRank:
    """The one new member of the ladder, and where it sits."""

    def test_the_aura_arms_between_the_barriers_and_the_damage(self):
        assert (
            TransitionRank.BARRIER_GRANT
            < TransitionRank.AURA_ARM
            < TransitionRank.DAMAGE
        )
        assert ordering_slot(TransitionRank.AURA_ARM) is TransitionRank.AURA_ARM

    def test_the_kind_ladder_still_calls_an_untriggered_modifier_a_debuff(self):
        """AURA_ARM is reached by declaration, never by the kind alone.

        A ``damage_modifier`` a trigger armed must keep resolving after the
        damage at its own timestamp; only the packet's own declaration says
        otherwise, which is why C4 moves one packet and not six.
        """
        assert (
            support_transition_rank({"kind": "damage_modifier"})
            is TransitionRank.DEBUFF_ARM
        )
        declared = {
            "kind": "damage_modifier",
            SUPPORT_RANK_KEY: TransitionRank.AURA_ARM,
        }
        assert support_transition_rank(declared) is TransitionRank.AURA_ARM


class TestUnmakeDeclaresIt:
    """The one persistent cross-participant modifier in ``src/``."""

    def _unmake(self):
        holder = _actor("main", "main", ("Abyssal Mask",))
        enemy = _actor("enemy:Aatrox", "enemy", ())
        return [
            packet
            for packet in derive_item_support_effects(holder, {}, [holder, enemy])
            if packet["source"] == UNMAKE
        ]

    def test_the_derived_packet_declares_the_aura_rank(self):
        packets = self._unmake()
        assert packets
        for packet in packets:
            assert packet["persistent"] is True
            assert packet[SUPPORT_RANK_KEY] is TransitionRank.AURA_ARM
            assert support_transition_rank(packet) is TransitionRank.AURA_ARM

    def test_the_curse_arms_at_the_fight_s_first_instant(self):
        """The aura's own timestamp is 0.0 — it is in force from the first frame."""
        assert [packet["time"] for packet in self._unmake()] == [0.0]


class TestAPersistentModifierMustSayItIsAnAura:
    """The fail-closed half: the next aura cannot arrive undeclared."""

    def _modifier(self, **overrides):
        holder = _actor("main", "main", ())
        enemy = _actor("enemy:Aatrox", "enemy", ())
        fields = {
            "attacker": holder,
            "target": enemy,
            "time": 0.0,
            "kind": "damage_modifier",
            "source": UNMAKE,
            "authority": Authority.SPLIT,
            "owner": holder.participant_id,
            "damage_classes": frozenset({DamageClass.MAGIC}),
            "attack_classes": frozenset(AttackClass),
            "persistent": True,
            "rank": TransitionRank.AURA_ARM,
        }
        fields.update(overrides)
        return item_support_effects._packet(**fields)

    def test_a_declared_persistent_modifier_builds(self):
        assert self._modifier()[SUPPORT_RANK_KEY] is TransitionRank.AURA_ARM

    def test_a_persistent_modifier_with_no_rank_raises(self):
        with pytest.raises(ValueError, match="must declare TransitionRank.AURA_ARM"):
            self._modifier(rank=None)

    def test_a_persistent_modifier_declaring_another_rank_raises(self):
        with pytest.raises(ValueError, match="must declare TransitionRank.AURA_ARM"):
            self._modifier(rank=TransitionRank.DEBUFF_ARM)

    def test_a_triggered_modifier_is_untouched(self):
        """Bloodsong, Carve, Vile Decay, Command and the Bubble keep the ladder."""
        packet = self._modifier(persistent=False, rank=None, duration=4.0)
        assert SUPPORT_RANK_KEY not in packet
        assert support_transition_rank(packet) is TransitionRank.DEBUFF_ARM


class TestTheAuraPricesItsOwnTimestamp:
    """C4's observable, end to end: damage at exactly ``t = 0`` gains the curse."""

    def _events(self):
        app_module.app.config["TESTING"] = True
        response = app_module.app.test_client().post(
            "/api/calculate", json=_ABYSSAL_ROSTER
        )
        assert response.status_code == 200
        return response.get_json()["combat"]["events"]

    def _amped(self, event):
        return (event.get("support_damage_multiplier") or {}).get("source") == UNMAKE

    def test_an_ally_s_magic_at_time_zero_now_carries_the_curse(self):
        opening = [
            event
            for event in self._events()
            if float(event["time"]) == 0.0
            and event["attacker"] == "ally:Ahri"
            and event["target"] == "enemy:Aatrox"
            and event["damage_type"] == "magic"
        ]
        assert opening
        assert all(self._amped(event) for event in opening)

    def test_the_holder_s_own_opening_damage_is_still_skipped(self):
        """C2's owner handshake survives being armed earlier (R-30)."""
        opening = [
            event
            for event in self._events()
            if float(event["time"]) == 0.0 and event["attacker"] == "main"
        ]
        assert opening
        assert not any(self._amped(event) for event in opening)

    def test_the_opening_true_damage_is_still_excluded(self):
        """C3's class restriction survives being armed earlier."""
        opening = [
            event
            for event in self._events()
            if float(event["time"]) == 0.0
            and event["attacker"] == "ally:Ahri"
            and event["damage_type"] == "true"
        ]
        assert not any(self._amped(event) for event in opening)


class TestThePublishedLedgerGainsItsSeventhPhase:
    """D-63's second value: a published payload changed, so the version moved."""

    def test_the_aura_slot_is_published_between_the_barriers_and_the_damage(self):
        phases = PARTICIPANT_LEDGER_CONTRACT["phases"]
        assert public_phase(TransitionRank.AURA_ARM) == "persistent_aura_arming"
        assert (
            phases.index("persistent_aura_arming")
            == phases.index(public_phase(TransitionRank.BARRIER_GRANT)) + 1
        )
        assert phases.index("persistent_aura_arming") + 1 == phases.index(
            public_phase(TransitionRank.DAMAGE)
        )

    def test_the_schema_version_moved_with_the_payload(self):
        # C4 took 2 for this phase list; 3.8's coverage flip took 3 for a
        # different payload and S9's dispositions took 4, so the seven names
        # are still C4's and the version has moved twice past it (5 is the
        # rune page's request fields and catalogs, 6 the survival row's
        # certification fields).
        assert CAPABILITY_SCHEMA_VERSION == 6
        assert len(PARTICIPANT_LEDGER_CONTRACT["phases"]) == 7
