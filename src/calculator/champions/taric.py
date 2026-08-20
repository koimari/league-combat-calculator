"""Taric — CP10.8 full-entry-reviewed packet module.

E8d ally-support: Q (Starlight's Touch) heals himself and nearby allies per
stocked charge (cached prose: "25 (+ 15% AP) (+ 1% of his maximum health) per
charge"; the cached Q leveling exposes only "Maximum Charges", not a heal
row).  The engine's ally-support scanner cannot author the heal from the
cached leveling, so the Q heal is NOT emitted as a support packet — see E8d
reply for the missing hook.  R (Cosmic Radiance) is invulnerability state
(2.5s), documented as such, not a heal/shield.

Roadmap session 1 (2026-08-20): Q, W, and R are reclassified from
out_of_scope to modeled. Each already carried a real, sourced, tested
numeric effect via the ally-support/self-heal side channels before this
session — the label was simply stale:
  - Q (Starlight's Touch): self/ally heal authored below via
    ``derive_self_healing`` (25 + 15% AP + 1% max health per stocked
    charge, self_and_all_teammates fan-out via the E1 rule); Taric is in
    support_effects.py's ``_MODULE_AUTHORED_HEAL_SLOTS`` so the generic
    scanner correctly defers (pinned in tests/test_issue_143.py,
    tests/test_e1_healing_b5.py, tests/test_survival_kernel.py).
  - W (Bastion): ally/self shield via the support scanner's "Shield
    Strength" packet, an amount_formula keyed off the PROTECTED target's
    max health, 2.5s duration (support_effects.py; pinned in
    tests/test_survival_kernel.py's compiled/receipt-walk parity cases).
  - R (Cosmic Radiance): self_and_all_teammates invulnerability state,
    carried by the support scanner's ``_SUPPORT_STATE_SLOTS`` entry
    (support_effects.py; pinned in tests/test_e8_support.py's
    ``test_taric_cosmic_radiance_targets_the_caster_and_selected_ally``
    and tests/test_survival_kernel.py's delayed-ally-state cases).
P (Bravado) stays out_of_scope and is NOT closed this session: the
passive is a real, sourced number ("deal 25 : 101 (based on level) (+ 15%
bonus armor) bonus magic damage on-attack" on Taric's next two basic
attacks within 5 seconds of an ability cast, refreshing the window and
regranting an attack on a further cast), but correctly attributing it
needs the same live event-ordering/dedup decision as Milio P (Fired
Up!): which of Taric's own casts consumes/refreshes the window, and
whether back-to-back Q/W/E/R casts double/triple-count under the
engine's existing ``empowers_next_auto`` mechanism (flat multiply by
num_casts, no concept of a proc window being refreshed rather than
stacked). That decision belongs to the rotation/cast-scheduling engine
(damage.py), out of this session's ownership boundary; a static per-slot
approximation here risked an overcounted number rather than a sourced
one.
"""

from .engine import build_parser
from .packet_module import build_packet_module
from .slotlib import with_control

PACKET_SHA256 = "c4661e1dfa5a63e1d512d64efc3bbb6cfb5e5d22f3c5d3e08c363f4d5c672cb4"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Taric", PACKET_SHA256
)
SLOTS["E"] = with_control(
    SLOTS["E"],
    kind="stun",
    duration_attr="Stun Duration",
)
parse_abilities = build_parser(SLOTS, "Taric")
PACKET_SPEC = SLOTS.packet_spec
ASSUMPTIONS.append("E's sourced 1.5-second stun counts as target action downtime")
ASSUMPTIONS.extend(
    [
        "W (Bastion) shields Taric and the linked selected teammate the "
        "sourced Shield Strength as a live % of the PROTECTED TARGET's "
        "maximum health (scanner packet with a max-health amount formula "
        "and 2.5s duration, selection key shield:W:<cast>).",
        "Q (Starlight's Touch) heals Taric and every selected teammate "
        "the sourced per-charge heal (25 + 15% AP + 1% of his maximum "
        "health per charge, capped at the 5-charge maximum) via the E1 "
        "rule and its self_and_all_teammates fan-out; the scanner defers "
        "the slot (no heal row in the cached Q leveling).",
        "R (Cosmic Radiance) grants the caster and every selected "
        "teammate invulnerability after the sourced 2.5s descent for the "
        "sourced 2.5s window (state packet).",
    ]
)
MODULE_COVERAGE = {
    "P": "out_of_scope",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "modeled",
}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Taric self-healing events from its authored packet."""
    healing = []
    heal, charges = _healing._taric_starlights_touch(
        _healing._ability(champion_data, "Q"),
        _healing._rank(ability_damages, "Q"),
        champion_stats,
    )
    if heal > 0.0:
        for cast_index, cast in enumerate(cast_timeline or []):
            if cast.get("slot") != "Q":
                continue
            healing.append(
                {
                    "time": float(cast.get("time", 0.0)),
                    "amount": heal,
                    "source": "Starlight's Touch",
                    "kind": "champion_ability",
                    "actor_wide": True,
                    "target_scope": "self_and_all_teammates",
                    "charges": charges,
                    "_event_id": f"taric:q:{cast_index}",
                }
            )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Taric", derive_self_healing)
