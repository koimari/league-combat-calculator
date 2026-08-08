"""Zaahen — CP10.10 full-entry-reviewed packet module.

Wiki-sourced item on-hit application is attached as a post-process on the
batch parser output (the batch parser builds its slot map at build time, so
declarations cannot be injected into the slot dict after the fact).
"""

from .packet_module import build_packet_module, repeat_damage_parser

PACKET_SHA256 = "5f5796aa0364becd253cbb3b7b05939147841a3f76e41cfa061242d344ec9f63"

_base_parse, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Zaahen",
    PACKET_SHA256,
    assumption_overrides=(
        "The Darkin Glaive prices both strikes (Physical Damage per Hit x 2 "
        "== Total Physical Damage).",
    ),
    slot_parsers={
        "Q": repeat_damage_parser(
            attr="Physical Damage per Hit",
            dmg_type="physical",
            count=2,
            time_offset=0.0,
            hit_interval=0.0,
        )
    },
)
PACKET_SPEC = SLOTS.packet_spec

_ON_HIT_SPECS: dict[str, dict] = {
    "Q": {"effectiveness": 1.0, "hits": 1, "triggers": ("on_hit",)},
}

_parse_abilities = _base_parse


def parse_abilities(*args, **kwargs):
    """Parse abilities, then declare wiki-sourced item on-hit application."""
    result = _parse_abilities(*args, **kwargs)
    for slot, spec in _ON_HIT_SPECS.items():
        entry = result.get(slot) or (result.get("passive") if slot == "P" else None)
        if entry is not None:
            entry["applies_item_on_hits"] = dict(spec)
    return result


MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
