"""What a cross-participant damage modifier applies to (C3, D-04).

Two vocabularies and one predicate.  A damage packet *belongs to* one
:class:`DamageClass` and one :class:`AttackClass`; a ``damage_modifier``
packet *declares the sets* it applies to, with no default and no empty set;
and ``transitions._modifier_applies`` is the single place the two meet, for
both the reduction and the multiplier branch that were separately untyped.
"""

import pytest

from src.calculator.ability_spec import AttackClass, DamageClass
from src.calculator.program.compile import action_from_event
from src.calculator.survival.actions import (
    SurvivalAction,
    attack_class_of,
    damage_class_of,
    declared_modifier_classes,
)
from src.calculator.survival.transitions import (
    _apply_damage_modifier,
    _modifier_applies,
)

ALL_DAMAGE = frozenset(DamageClass)
ALL_ATTACK = frozenset(AttackClass)

# The owner skip compares roster slots, not participant ids: the holder's own
# pair engine already priced its half, so a modifier armed by slot 0 is the
# one packets from slot 0 skip and packets from any other slot pay.
_MAIN = 0
_OTHER = 1


def _modifier(**overrides):
    """An armed modifier as ``_apply_damage_modifier`` writes it."""
    armed = {
        "source": "Abyssal Mask — Unmake",
        "holder": _MAIN,
        "damage_classes": frozenset({DamageClass.MAGIC}),
        "attack_classes": ALL_ATTACK,
    }
    armed.update(overrides)
    return armed


def _packet(**overrides):
    """A damage action as the walk sees it.

    ``attacker`` is the roster slot that delivered the packet: the owner
    skip is now an index compare, so a packet with no attacker (``-1``)
    is what "somebody other than the holder" looks like.
    """
    fields = {"damage_type": "magic", "is_ability": True, "attacker": _OTHER}
    fields.update(overrides)
    return SurvivalAction(**fields)


class TestPacketClasses:
    """The two readers: what one damage packet *is*."""

    @pytest.mark.parametrize(
        "damage_type,expected",
        [
            ("magic", DamageClass.MAGIC),
            ("physical", DamageClass.PHYSICAL),
            ("true", DamageClass.TRUE),
            ("", None),
            ("unknown", None),
        ],
    )
    def test_damage_class_of_reads_the_engine_spelling(self, damage_type, expected):
        assert damage_class_of(_packet(damage_type=damage_type)) is expected

    def test_a_packet_with_no_damage_type_matches_no_restriction(self):
        """``None`` is honest, and it is in no declared set."""
        action = _packet(damage_type="")
        assert damage_class_of(action) is None
        assert not _modifier_applies(_modifier(holder=-1), action)

    @pytest.mark.parametrize(
        "fields,expected",
        [
            ({"basic_attack": True}, AttackClass.BASIC_ATTACK),
            ({"source_key": "auto_attacks"}, AttackClass.BASIC_ATTACK),
            ({"is_ability": True}, AttackClass.ABILITY),
            ({"source_key": "item_burn"}, AttackClass.OTHER),
            ({}, AttackClass.OTHER),
        ],
    )
    def test_attack_class_of_names_the_delivery(self, fields, expected):
        action = SurvivalAction(damage_type="magic", **fields)
        assert attack_class_of(action) is expected


class TestTheDeclarationIsRequired:
    """D-04: both axes, no default, empty banned — enforced where it arms."""

    def test_a_complete_declaration_is_returned_unchanged(self):
        action = _packet(
            damage_classes=frozenset({DamageClass.MAGIC}), attack_classes=ALL_ATTACK
        )
        assert declared_modifier_classes(action) == (
            frozenset({DamageClass.MAGIC}),
            ALL_ATTACK,
        )

    @pytest.mark.parametrize("axis", ["damage_classes", "attack_classes"])
    def test_an_empty_axis_raises_at_arming(self, axis):
        fields = {"damage_classes": ALL_DAMAGE, "attack_classes": ALL_ATTACK}
        fields[axis] = frozenset()
        with pytest.raises(ValueError, match="empty-means-all is banned"):
            declared_modifier_classes(_packet(source="Synthetic — Modifier", **fields))

    def test_the_arming_transition_refuses_an_undeclared_modifier(self):
        """The raise precedes the availability gate, so a zero-duration
        packet cannot slip through undeclared either."""
        action = _packet(source="Synthetic — Modifier", duration=0.0)
        with pytest.raises(ValueError, match="Synthetic — Modifier"):
            _apply_damage_modifier(None, action, None)

    def test_an_event_without_a_declaration_fails_closed_to_empty(self):
        """Absent metadata is the neutral value, never a guessed set."""
        action = action_from_event({"kind": "damage_modifier", "time": 0.0}, 1.0, 0, {})
        assert action.damage_classes == frozenset()
        assert action.attack_classes == frozenset()

    def test_an_event_declaring_strings_raises(self):
        """A spelling that looks like a class is the drift the enum retires."""
        with pytest.raises(TypeError, match="DamageClass members are required"):
            action_from_event(
                {"kind": "damage_modifier", "damage_classes": ["magic"]}, 1.0, 0, {}
            )

    def test_the_armed_modifier_carries_the_declaration(self):
        armed = []
        state = {"active_damage_modifiers": armed}
        action = _packet(
            source="Synthetic — Modifier",
            persistent=True,
            multiplier=1.5,
            damage_classes=frozenset({DamageClass.TRUE}),
            attack_classes=frozenset({AttackClass.OTHER}),
        )
        _apply_damage_modifier(_LedgerCtx(), action, state)
        assert armed[0]["damage_classes"] == frozenset({DamageClass.TRUE})
        assert armed[0]["attack_classes"] == frozenset({AttackClass.OTHER})


class TestOnePredicateDecidesApplicability:
    """The owner skip, the class match and the delivery gate, in one place."""

    def test_the_owner_is_skipped_because_the_pair_engine_priced_it(self):
        assert not _modifier_applies(_modifier(), _packet(attacker=_MAIN))

    def test_every_other_source_is_priced(self):
        assert _modifier_applies(_modifier(), _packet())

    @pytest.mark.parametrize("damage_type", ["physical", "true"])
    def test_a_magic_only_curse_leaves_the_other_classes_alone(self, damage_type):
        """C3's correction, at the predicate: 12% *magic* damage."""
        assert not _modifier_applies(_modifier(), _packet(damage_type=damage_type))

    def test_a_from_all_sources_amp_prices_every_class(self):
        for damage_type in ("magic", "physical", "true"):
            assert _modifier_applies(
                _modifier(damage_classes=ALL_DAMAGE),
                _packet(damage_type=damage_type),
            )

    def test_the_attack_axis_is_live_and_not_decorative(self):
        """D-26: no shipped producer restricts to one attack class, so the
        branch is proven with a synthetic declaration rather than left
        untested because nothing reaches it today."""
        basic_only = _modifier(
            damage_classes=ALL_DAMAGE,
            attack_classes=frozenset({AttackClass.BASIC_ATTACK}),
        )
        assert _modifier_applies(
            basic_only, _packet(is_ability=False, basic_attack=True)
        )
        assert not _modifier_applies(basic_only, _packet())

    def test_the_delivery_gate_still_excludes_what_is_neither(self):
        """Characterized, not corrected: see the sentinel for why it stays."""
        proc = _packet(is_ability=False, source_key="item_burn")
        assert attack_class_of(proc) is AttackClass.OTHER
        assert AttackClass.OTHER in _modifier()["attack_classes"]
        assert not _modifier_applies(_modifier(), proc)


class TestTheHolderIsARosterSlot:
    """S1: the kernel's owner string became an integer slot.

    ``owner: str`` and ``holder: int`` never coexisted and never both went
    missing -- one commit deleted the first and added the second -- so this
    suite asserts both halves rather than only the one that is present.
    """

    def test_the_action_carries_a_holder_slot_and_no_owner_string(self):
        fields = SurvivalAction._fields
        assert "holder" in fields
        assert "owner" not in fields
        assert SurvivalAction().holder == -1

    def test_a_packet_owner_resolves_to_its_roster_slot(self):
        """The packet declares a participant id; the kernel stores the index."""
        action = action_from_event(
            {"kind": "damage_modifier", "owner": "ally:Lulu"},
            1.0,
            0,
            {"main": _MAIN, "ally:Lulu": _OTHER},
        )
        assert action.holder == _OTHER

    def test_an_owner_outside_the_roster_arms_no_skip(self):
        """Byte-identical to the string compare: an unresolvable id matched
        nothing then and is ``-1`` now, which the predicate reads as
        "declares no holder"."""
        action = action_from_event(
            {"kind": "damage_modifier", "owner": "enemy:Ghost"},
            1.0,
            0,
            {"main": _MAIN},
        )
        assert action.holder == -1
        assert _modifier_applies(_modifier(holder=action.holder), _packet())

    def test_the_skip_is_an_index_compare_not_an_id_compare(self):
        """Two slots, one modifier: the arming slot skips, the other pays."""
        armed = _modifier(holder=_MAIN)
        assert not _modifier_applies(armed, _packet(attacker=_MAIN))
        assert _modifier_applies(armed, _packet(attacker=_OTHER))


class _LedgerCtx:
    """The two ledger calls ``_apply_damage_modifier`` makes, and nothing else."""

    class _Ledger:
        @staticmethod
        def write(action, **fields):  # pylint: disable=unused-argument
            """Record nothing: this suite reads the armed modifier, not the receipt."""

        @staticmethod
        def skip(action, reason):  # pylint: disable=unused-argument
            """Record nothing."""

    ledger = _Ledger()
