"""Swain — CP10.8 full-entry-reviewed packet module."""

from dataclasses import replace

from .reviewed_batch_08 import build_batch_module

_parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Swain")


def parse_abilities(*args, **kwargs):
    """Batch parse, plus the sourced E root branch typed onto Nevermove.

    The sourced E (Nevermove) row is the return detonation: "At maximum
    range, the wave homes back to Swain and detonates upon the first
    enemy hit, dealing magic damage to nearby enemies and rooting them
    for 1.5 seconds".  The packet prices that single sourced hit, so its
    damage part carries ``cc_kind="root"``.
    """
    result = _parse_abilities(*args, **kwargs)
    e = result.get("E")
    if e is not None and e.get("parts"):
        e["parts"] = tuple(replace(part, cc_kind="root") for part in e["parts"])
        e["detail"] = (
            e["detail"] + " " if e.get("detail") else ""
        ) + "Sourced root branch: the detonation roots enemies it damages."
    return result


VARIANT_OPTION_KEYS = ("r_variant",)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
