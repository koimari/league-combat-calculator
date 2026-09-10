"""The parsed-text markers and slot corpus a cast edge or an AoE cap is read out of."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .champions import get_champion_module_contract

# Default direct-edge kind for consume/execute declarations that carry a
# ``setup_slot`` but no explicit ``kind`` (the declaration is authoritative;
# this is only a fallback for the two direct-edge families).
_DIRECT_EDGE_KIND = {"consume": "mark_consume", "execute": "execute"}


# Damage-amplifying stat_buff keys: buffs-first applies to these only.
_DAMAGE_AMP_STAT_KEYS = {
    "bonus_attack_damage",
    "ability_power",
    "armor_penetration_percent",
    "magic_penetration_percent",
    "bonus_ability_power",
    "bonus_magic_damage",
    "bonus_physical_damage",
    "lethality",
}


# structured wiki attribute rows (exact leveling-row attribute names)
_ATTR_PER_STACK = re.compile(
    r"per stack|per additional stack|per subsequent stack|damage per stack|"
    r"stack bonus|full stack|at max stacks|max stacks|one stack|two stacks|three stacks"
)


_ATTR_ENHANCED_DMG = re.compile(r"enhanc[a-z]* (damage|physical|magic)|prowl-enhanc")


_ATTR_DETONATION = re.compile(r"detonat")


_ATTR_MISSING = re.compile(r"missing")


_ATTR_MARK_DMG = re.compile(r"mark magic damage")


_ATTR_STORED_DMG = re.compile(r"stored damage")


# anchored wiki application/consume rows (confirmation only — never the
# sole signal; every edge also carries a typed atom or structured attr)
_P_APPLIES_STACK = re.compile(r"appl(y|ies|ied|ying).{0,40}\bstack")


_P_MARKS_TARGET = re.compile(
    r"mark(s|ed) (the target|them|enemies|the first enemy|with)"
)


_P_ABILITY_CONSUMES_MARK = re.compile(
    r"abilit(y|ies).{0,80}(consume|detonat).{0,40}mark", re.IGNORECASE
)


_P_TARGET_MISSING = re.compile(
    r"target's? missing|target’s? missing|missing health of the target|missing hp",
    re.IGNORECASE,
)


_P_NAMED_APPLIER_STACK = re.compile(
    r"([\w' ]+?) apply a stack of ([A-Za-z']+)", re.IGNORECASE
)


_P_NAMED_APPLIER_COND = re.compile(
    r"enemies? hit by ([\w' ]+?) (?:or ([\w' ]+?))?.{0,40}?become (chilled|poisoned|marked)",
    re.IGNORECASE,
)


_P_NAMED_CONSUMER = re.compile(
    r"([\w' ]+?) against an enemy with ([A-Za-z']+) stacks? consumes", re.IGNORECASE
)


_P_PASSIVE_ABILITIES_APPLY = re.compile(
    r"abilit(y|ies).{0,80}apply a stack of ([A-Za-z']+)", re.IGNORECASE
)


_P_PASSIVE_ABILITIES_MARK = re.compile(
    r"abilit(y|ies).{0,80}(apply a mark|become marked|are marked)", re.IGNORECASE
)


# target-oriented condition phrase for "Enhanced Damage" consumers
_P_COND_PHRASE = re.compile(
    r"(if|when|while|against|on|vs\.?|versus|doubled|increased|bonus).{0,50}"
    r"(the target|they|it|enemies|an enemy|a target|them|targets?|enemy)"
    r".{0,30}(is|are|were|has|had|take|takes|become)",
    re.IGNORECASE,
)


_P_SELF_RESOURCE = re.compile(
    r"\b(heat|fury|rage|mana|energy|reign of anger|has at least|gains? a stack|"
    r"generates? a stack|at max stacks)\b",
    re.IGNORECASE,
)


# named conditions shared by consume phrases and apply rows
_CONDITIONS = (
    ("poisoned", r"poison"),
    ("chilled", r"chill|frost"),
    ("ablaze", r"ablaze|blaze"),
    ("bleeding", r"bleed"),
    ("marked", r"mark"),
    ("stunned", r"stun"),
    ("rooted", r"root"),
    ("slowed", r"slow"),
    ("charmed", r"charm"),
    ("feared", r"fear"),
    ("wounded", r"wound"),
    ("immobilized", r"immobiliz"),
)


_CAST_SLOTS = ("Q", "Q2", "W", "E", "R")


@dataclass(frozen=True)
class _Edge:
    """One setup→consume ordering constraint between two cast slots.

    Attributes:
        setup: The slot that must be cast first.
        consume: The slot that depends on it.
        kind: A member of ``INFERRED_EDGE_KINDS`` when ``origin`` is
            ``"inferred"``, of ``DEPENDENCY_KINDS`` when it is
            ``"declared"``.  The two vocabularies are asserted disjoint,
            so the kind alone identifies the surface — ``origin`` says it
            out loud rather than leaving the reader to look it up (D-80).
        cite: The rationale sentence for the receipt.
        origin: Which surface produced the constraint — the detector
            reading markers, or the champion module asserting it.
    """

    setup: str
    consume: str
    kind: str
    cite: str
    origin: Literal["declared", "inferred"] = "inferred"

    def sentence(self) -> str:
        """A rationale sentence naming the atoms that drove the edge."""
        if self.kind == "recast":
            return f"{self.consume} is the recast of {self.setup} — {self.cite}"
        return self.cite


def _slot_corpus(
    champion_data: Mapping[str, Any],
    slot: str,
    *,
    recast_of: str | None = None,
) -> dict[str, list[str]] | None:
    """Structured row corpus for a slot, borrowing its recast parent's rows.

    A recast slot (Syndra's ``Q2``) has no wiki row of its own — the
    parent ability's rows describe both casts — so it reads the parent's
    corpus.  ``recast_of`` comes from the parsed ability entry and from
    nowhere else, because a slot name is only a guess: three synthetic
    non-recast slots read as recasts by name alone.
    """
    abilities = champion_data.get("abilities", {})
    rows = abilities.get(slot, []) or (
        abilities.get(recast_of, []) if recast_of else []
    )
    if not rows:
        return None
    out: dict[str, list[str]] = {
        "names": [],
        "attrs": [],
        "descs": [],
        "notes": [],
        "blurb": [],
        "fields": [],
    }
    for row in rows:
        out["names"].append(str(row.get("name") or ""))
        for eff in row.get("effects") or []:
            out["attrs"].extend(
                str(lvl.get("attribute") or "") for lvl in eff.get("leveling") or []
            )
            out["descs"].append(str(eff.get("description") or ""))
        out["notes"].append(str(row.get("notes") or ""))
        out["blurb"].append(str(row.get("blurb") or ""))
        for f in ("targeting", "spellEffects", "affects", "damageType"):
            v = row.get(f)
            if v:
                out["fields"].append(str(v))
    return out


def _corpus_text(corpus: Mapping[str, list[str]]) -> str:
    return " ".join(
        corpus["names"]
        + corpus["attrs"]
        + corpus["descs"]
        + corpus["notes"]
        + corpus["blurb"]
    ).lower()


def _corpus_attrs(corpus: Mapping[str, list[str]]) -> str:
    return " ".join(corpus["attrs"]).lower()


def _recast_parent(entry: Any) -> str | None:
    """The slot a parsed ability entry is a recast of, or ``None``.

    ``recast_of`` is the single authority; a slot with no stamp has no parent.
    """
    if not isinstance(entry, Mapping):
        return None
    parent = entry.get("recast_of")
    return parent if isinstance(parent, str) and parent else None


def _is_damage_row(info: Mapping[str, Any]) -> bool:
    if float(info.get("total_raw", 0.0) or 0.0) > 0:
        return True
    return any(
        float(getattr(p, "amount", 0.0) or 0.0) > 0 for p in info.get("parts", ())
    )


def _castable(info: Mapping[str, Any], slot: str) -> bool:
    """A slot that appears on the shared cast timeline (R always casts once)."""
    if slot == "R":
        return True
    return float(info.get("cooldown", 0.0) or 0.0) > 0


# Slots whose crowd control orders the rotation, pinned because their
# published orders predate the rule below.  A module's ``cc_kind`` states
# what a cast APPLIES and is never an ordering constraint, so it must not
# fan ``cc_setup`` edges across the kit: a coverage pass that records a slow
# honestly would otherwise reorder the rotation and move published damage,
# which is the pressure that makes an author withhold a true fact.
#
# That holds however the module said it.  Reading a per-part marker as an
# ordering claim and a ``MODULE_CC`` slot declaration as a kit fact would
# make "does recording this move my damage?" turn on which authoring site a
# module happened to use, and Morgana's R cannot even choose: its parts
# carry different kinds and ``MODULE_CC`` admits one per slot.  Every other
# reader of the ``cc_kind=`` atom sees every kind unchanged; only the
# ``cc_setup`` fan-out asks where the marker came from.
#
# The table is closed and shrinks only through the module: declare the
# ordering in ``CAST_DEPENDENCIES``, the home architecture.md gives it, and
# delete the entry.  Nothing may be added — a kit that needs cc-driven
# ordering has the declared vocabulary for it.
_PRE_CAMPAIGN_CC_ORDERING: dict[str, frozenset[str]] = {
    "Ahri": frozenset({"E"}),  # Charm opens the burst
    "Pantheon": frozenset({"W"}),  # Shield Vault's stun opens the burst
    "Syndra": frozenset({"E"}),  # Scatter the Weak's stun (E->Q suppressed)
}


def _has_champion_module(champion_name: str) -> bool:
    """Whether this name resolves to a validated champion module.

    Synthetic and development fixtures do not: a test or a scratch kit
    authored their markers, not a reviewed module.
    """
    try:
        get_champion_module_contract(champion_name)
    except KeyError:
        return False
    return True


def _cc_orders_the_burst(champion_name: str, slot: str) -> bool:
    """Whether this slot's crowd control is an ORDERING claim, not a kit fact."""
    if slot in _PRE_CAMPAIGN_CC_ORDERING.get(champion_name, frozenset()):
        return True
    return not _has_champion_module(champion_name)


def detect_aoe_cap(
    champion_data: Mapping[str, Any], slot: str, *, recast_of: str | None = None
) -> int:
    """Conservative AoE cap from the structured row fields.

    A recast slot reads its parent's rows (``recast_of`` from the parsed
    entry); a slot with no rows of its own and no recast parent — a
    module's synthetic buff or on-hit row — caps at one, because no wiki
    row says otherwise.
    """
    corpus = _slot_corpus(champion_data, slot, recast_of=recast_of)
    if not corpus:
        return 1
    fields = " ".join(corpus["fields"]).lower()
    if any(t in fields for t in ("aoe", "area of effect")) or "Location" in " ".join(
        corpus["fields"]
    ):
        return 5
    return 1
