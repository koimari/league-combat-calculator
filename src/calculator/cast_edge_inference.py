"""The twelve edge kinds inferred from a champion's own rows."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from functools import partial
from typing import Any, NamedTuple

from .cast_edge_markers import (
    _ATTR_DETONATION,
    _ATTR_ENHANCED_DMG,
    _ATTR_MARK_DMG,
    _ATTR_MISSING,
    _ATTR_PER_STACK,
    _ATTR_STORED_DMG,
    _CAST_SLOTS,
    _CONDITIONS,
    _DAMAGE_AMP_STAT_KEYS,
    _DIRECT_EDGE_KIND,
    _P_ABILITY_CONSUMES_MARK,
    _P_APPLIES_STACK,
    _P_COND_PHRASE,
    _P_MARKS_TARGET,
    _P_NAMED_APPLIER_COND,
    _P_NAMED_APPLIER_STACK,
    _P_NAMED_CONSUMER,
    _P_PASSIVE_ABILITIES_APPLY,
    _P_PASSIVE_ABILITIES_MARK,
    _P_SELF_RESOURCE,
    _P_TARGET_MISSING,
    _castable,
    _cc_orders_the_burst,
    _corpus_attrs,
    _corpus_text,
    _Edge,
    _EdgeScan,
    _is_damage_row,
    _recast_parent,
    _slot_corpus,
)
from .champions import get_champion_option_rotation
from .control_spec import NO_CONTROL_KIND


def detect_setup_consume_edges(
    champion_name: str,
    ability_damages: Mapping[str, Any],
    champion_data: Mapping[str, Any],
    option_keys: Mapping[str, list[str]],
) -> list[_Edge]:
    """Detect setup→consume ordering constraints from typed atoms.

    See the module docstring for the atom taxonomy.  Returns a list of
    :class:`_Edge` constraints; a champion with no detectable signal
    returns ``[]`` and keeps its certified/default order.

    The steps run in the order the edges are cited in: a later step's
    citation of an edge an earlier one already recorded is dropped by the
    deduplication at the end, so the order below is the answer.
    """
    scan = _scan_slots(ability_damages, champion_data)
    if scan is None:
        return []
    _recast_edges(scan)
    _read_apply_atoms(scan, champion_data)
    _read_consume_atoms(scan, champion_name, option_keys)
    _pairwise_edges(scan)
    _self_declared_mark_applier_edges(scan)
    _fan_out_edges(scan, champion_name)
    return _first_citation_of_each(scan.edges)


def _scan_slots(
    ability_damages: Mapping[str, Any], champion_data: Mapping[str, Any]
) -> _EdgeScan | None:
    """The champion's slot corpora and their text, or ``None`` if it has none."""
    slots = [s for s in _CAST_SLOTS if isinstance(ability_damages.get(s), Mapping)]
    corpora = {
        s: _slot_corpus(
            champion_data, s, recast_of=_recast_parent(ability_damages.get(s))
        )
        for s in slots
    }
    corpora = {s: c for s, c in corpora.items() if c}
    if not corpora:
        return None
    slot_by_name: dict[str, str] = {}
    for s, c in corpora.items():
        for n in c["names"]:
            if n:
                slot_by_name[n.lower()] = s
    return _EdgeScan(
        slots=slots,
        corpora=corpora,
        infos={s: ability_damages[s] for s in corpora},
        texts={s: _corpus_text(c) for s, c in corpora.items()},
        atexts={s: _corpus_attrs(c) for s, c in corpora.items()},
        slot_by_name=slot_by_name,
    )


def _recast_edges(scan: _EdgeScan) -> None:
    """A recast rides its parent's casts, on ``recast_of``'s authority alone.

    A name-based "Q plus Q2" fallback would mask every unstamped recast.
    """
    for s in scan.slots:
        parent = scan.infos.get(s, {}).get("recast_of")
        if parent and parent in scan.corpora:
            scan.add(parent, s, "recast", f"{s} is {parent}'s recast (recast_of atom)")


def _slot_apply_atoms(info: Mapping[str, Any], text: str) -> list[str]:
    """The typed apply atoms one slot's parsed entry and prose carry."""
    atoms: list[str] = []
    if float(info.get("cooldown", 0.0) or 0.0) <= 0:
        atoms.append("passive-row(cd=0)")  # auto-stream row, not a cast
    if info.get("dot_duration"):
        atoms.append(f"dot_duration={info['dot_duration']}")
    if info.get("on_hit"):
        atoms.append("on_hit")
    if info.get("applies_dot_stack"):
        atoms.append("applies_dot_stack")
    if info.get("stacking_dot"):
        atoms.append("stacking_dot")
    if info.get("target_debuff"):
        atoms.append("target_debuff")
    if info.get("stat_buff") and isinstance(info["stat_buff"], Mapping):
        amp = sorted(set(info["stat_buff"]) & _DAMAGE_AMP_STAT_KEYS)
        if amp:
            atoms.append(f"stat_buff({','.join(amp)})")
    for part in info.get("parts", ()):
        # ``"none"`` is a reviewed ABSENCE of crowd control, so it is
        # not an apply atom: fanning a cc_setup edge out of it would
        # order the whole rotation around a stun the module explicitly
        # said does not exist.  Every reader below (the fan-out, the
        # enhanced-vs-condition pairing, ``applies_condition``) sees
        # atoms, so refusing the atom here is the one place the rule
        # has to hold.  A real kind is an atom wherever it was
        # authored; whether it also ORDERS the rotation is a separate
        # question, asked once at the fan-out
        # (:func:`_cc_orders_the_burst`).
        kind = getattr(part, "cc_kind", None)
        if kind and kind != NO_CONTROL_KIND:
            atoms.append(f"cc_kind={kind}")
    if _P_APPLIES_STACK.search(text):
        atoms.append("phrase:applies-stack")
    if _P_MARKS_TARGET.search(text):
        atoms.append("phrase:marks-target")
    return atoms


def _read_apply_atoms(scan: _EdgeScan, champion_data: Mapping[str, Any]) -> None:
    """Fill the per-slot apply atoms and the champion passive's own applies.

    A passive reading "abilities apply a stack/mark of X" means EVERY slot
    applies X (Mel Overwhelm, Lux Illumination).
    """
    for s in scan.corpora:
        scan.apply_atoms[s] = _slot_apply_atoms(scan.infos[s], scan.texts[s])
    for ps in ("P", "passive"):
        pc = _slot_corpus(champion_data, ps)
        if not pc:
            continue
        t = _corpus_text(pc)
        scan.passive_applies.extend(
            m.group(2).strip().lower() for m in _P_PASSIVE_ABILITIES_APPLY.finditer(t)
        )
        if _P_PASSIVE_ABILITIES_MARK.search(t):
            scan.passive_applies.append("__mark__")


def applies_condition(scan: _EdgeScan, slot: str, cond_token: str) -> bool:
    """Whether *slot* applies the condition a consumer names.

    A cd-0 row (on-hit or passive) applies through the AUTO STREAM rather than
    a cast, so it can never be a cast-order setup endpoint.
    """
    atoms = scan.apply_atoms[slot]
    t = scan.texts[slot]
    if "passive-row(cd=0)" in atoms:
        return False
    if scan.passive_applies:
        if cond_token == "stack":
            return True
        if cond_token == "mark" and "__mark__" in scan.passive_applies:
            return True
        if any(nm != "__mark__" and nm in t for nm in scan.passive_applies):
            return True
    if cond_token == "stack":
        return any("stack" in a for a in atoms)
    if cond_token == "mark":
        return "phrase:marks-target" in atoms or "target_debuff" in " ".join(atoms)
    return any(cond_token in a for a in atoms)


def _declared_consume_atoms(
    scan: _EdgeScan, slot: str, rotations: Mapping[str, Any], keys: Iterable[str]
) -> list[tuple[str, str, str]]:
    """The consume atoms one slot's OPTIONS rotation declarations carry.

    A consume/execute declaration with ``setup_slot`` carries the FULL edge
    (setup_slot → this slot) and is recorded here, never depending on the
    applier-corpus phrase.  Declarations without ``setup_slot`` fall back to
    the corpus-based pairing, keyed by their ``kind``.
    """
    info = scan.infos[slot]
    cons: list[tuple[str, str, str]] = []
    for key in keys:
        decl = rotations.get(key)
        if not decl:
            continue
        role = str(decl.get("role", ""))
        if role in ("self_state", "irrelevant", "unsupported"):
            continue
        setup_slot = decl.get("setup_slot")
        if setup_slot:
            _declared_setup_edge(scan, slot, setup_slot, decl=decl, key=key, role=role)
            continue
        kind = str(decl.get("kind") or role)
        cond = str(decl.get("condition") or kind)
        if role == "execute" and not _is_damage_row(info):
            continue
        cons.append((kind, cond, f"option {key}"))
    return cons


def _declared_setup_edge(
    scan: _EdgeScan,
    slot: str,
    setup_slot: Any,
    *,
    decl: Mapping[str, Any],
    key: str,
    role: str,
) -> None:
    """The setup slot a declaration names must cast before its consumer.

    Diana's Q Moonlight before the E reset: the declaration carries the whole
    edge, so no corpus phrase is consulted.
    """
    if setup_slot not in scan.corpora or setup_slot == slot:
        return
    kind = str(decl.get("kind") or _DIRECT_EDGE_KIND.get(role, "mark_consume"))
    scan.add(
        setup_slot,
        slot,
        kind,
        f"{slot} consumes {setup_slot}'s setup via option {key} ({kind})",
    )


def _attribute_consume_atoms(scan: _EdgeScan, slot: str) -> list[tuple[str, str, str]]:
    """The consume atoms one slot's own attributes and prose carry."""
    info = scan.infos[slot]
    at = scan.atexts[slot]
    cons: list[tuple[str, str, str]] = []
    if info.get("post_hit_proc"):
        proc = info["post_hit_proc"]
        nm = proc.get("name", "proc") if isinstance(proc, Mapping) else "proc"
        cons.append(("detonation_consume", "stacks", f"post_hit_proc {nm!r}"))
    execute_ratio = float(info.get("execute_threshold_ratio", 0.0) or 0.0)
    if execute_ratio > 0 and _is_damage_row(info):
        cons.append(
            ("execute", "execute", f"execute_threshold_ratio={execute_ratio:g}")
        )
    per_stack = _ATTR_PER_STACK.search(at)
    if per_stack:
        cons.append(("stack_consume", "stacks", f"attribute {per_stack.group(0)!r}"))
    enhanced = _ATTR_ENHANCED_DMG.search(at)
    if enhanced and _P_TARGET_MISSING.search(scan.texts[slot]) and _is_damage_row(info):
        # "Enhanced ... based on the target's missing health" rows are
        # missing-health executes, not conditional-vs-state consumes
        # (Seraphine Q: up to 75% bonus vs missing health).
        cite = f"attribute {enhanced.group(0)!r} + target-missing-health"
        cons.append(("execute", "execute", cite))
    elif enhanced:
        cons.append(
            ("enhanced_consume", "enhanced", f"attribute {enhanced.group(0)!r}")
        )
    detonation = _ATTR_DETONATION.search(at)
    if detonation:
        cite = f"attribute {detonation.group(0)!r}"
        cons.append(("detonation_consume", "stacks", cite))
    if (
        _ATTR_MISSING.search(at)
        and _P_TARGET_MISSING.search(scan.texts[slot])
        and _is_damage_row(info)
    ):
        cons.append(
            ("execute", "execute", "attribute Missing Health + target-missing-health")
        )
    if _ATTR_MARK_DMG.search(at) or _P_ABILITY_CONSUMES_MARK.search(scan.texts[slot]):
        cons.append(("mark_consume", "mark", "mark consumption"))
    stored = _ATTR_STORED_DMG.search(at)
    if stored:
        cons.append(("stored_consume", "stored", f"attribute {stored.group(0)!r}"))
    return cons


def _read_consume_atoms(
    scan: _EdgeScan, champion_name: str, option_keys: Mapping[str, list[str]]
) -> None:
    """Fill the per-slot consume atoms, declarations before attributes."""
    rotations = get_champion_option_rotation(champion_name)
    for b in scan.corpora:
        keys = option_keys.get(b, []) + option_keys.get("__all__", [])
        scan.consume_atoms[b] = _declared_consume_atoms(
            scan, b, rotations, keys
        ) + _attribute_consume_atoms(scan, b)


def _dot_consume_edges(scan: _EdgeScan, b: str, cite: str) -> None:
    """Every slot whose own row applies the champion's poison comes first."""
    for a in scan.corpora:
        atoms = scan.apply_atoms[a]
        if (
            a != b
            and any(x.startswith("dot_duration") for x in atoms)
            and "passive-row(cd=0)" not in " ".join(atoms)
        ):
            scan.add(
                a,
                b,
                "dot_consume",
                f"{b} {cite} consumes the champion's poison; {a} "
                f"{', '.join(atoms)} applies it",
            )


def _condition_appliers(scan: _EdgeScan, b: str, cond_token: str) -> Iterator[str]:
    """Every other slot that applies the condition *b* consumes."""
    return (
        a for a in scan.corpora if a != b and applies_condition(scan, a, cond_token)
    )


class _ConditionFan(NamedTuple):
    """One consume atom paired against every slot applying its condition.

    Three consume atoms are the same rule under three names, so they are one
    function over three rows rather than three near-identical bodies.
    ``edge_kind`` is the edge the pairing emits — ``detonation_consume``
    emits ``detonate`` — and ``verb``/``what`` are the two halves of its
    rationale sentence.
    """

    cond_token: str
    edge_kind: str
    verb: str
    what: str


def _condition_consume_edges(
    scan: _EdgeScan, b: str, cite: str, *, fan: _ConditionFan
) -> None:
    """Every applier of the condition *b* consumes comes before *b*."""
    for a in _condition_appliers(scan, b, fan.cond_token):
        atoms = ", ".join(scan.apply_atoms[a])
        sentence = f"{b} {cite} {fan.verb}; {a} {atoms} applies {fan.what}"
        scan.add(a, b, fan.edge_kind, sentence)


def _damaging_slots(scan: _EdgeScan, setup: str) -> Iterator[str]:
    """Every other slot whose row is castable damage, in corpus order."""
    return (
        d
        for d in scan.corpora
        if d != setup and _is_damage_row(scan.infos[d]) and _castable(scan.infos[d], d)
    )


def _mark_applier_edges(scan: _EdgeScan, b: str, cite: str) -> None:
    """A slot that applies a mark comes before every damaging ability."""
    sentence = f"{b} {cite} applies a mark consumed by any next damaging ability"
    for d in _damaging_slots(scan, b):
        scan.add(b, d, "mark_applier", sentence)


_ENHANCED_APPLY_ATOMS = (
    "dot_duration",
    "cc_kind",
    "phrase:applies-stack",
    "applies_dot_stack",
    "target_debuff",
)


def _enhanced_consume_edges(scan: _EdgeScan, b: str, cite: str) -> None:
    """The first condition the consumer's prose names, and who applies it.

    Only the first matching condition is paired: a row enhanced "against
    slowed or immobilized targets" names one state, and fanning out over both
    would order the rotation twice around one clause.
    """
    bt = scan.texts[b]
    if not _P_COND_PHRASE.search(bt) or _P_SELF_RESOURCE.search(bt):
        return
    for condtok, pattern in _CONDITIONS:
        if not re.search(pattern, bt):
            continue
        for a in scan.corpora:
            atoms = scan.apply_atoms[a]
            if (
                a != b
                and re.search(pattern, scan.texts[a])
                and any(x.startswith(_ENHANCED_APPLY_ATOMS) for x in atoms)
            ):
                scan.add(
                    a,
                    b,
                    "enhanced_consume",
                    f"{b} {cite} enhanced vs {condtok}; {a} applies "
                    f"{condtok} ({', '.join(atoms)})",
                )
        break


#: One fan-out per consume atom kind; a kind absent here pairs through the
#: named-applier prose below instead.  The three condition pairings are one
#: function over three rows, and their rows carry the edge each emits.
_CONSUME_FANS: dict[str, Callable[[_EdgeScan, str, str], None]] = {
    "dot_consume": _dot_consume_edges,
    "stack_consume": partial(
        _condition_consume_edges,
        fan=_ConditionFan("stack", "stack_consume", "consumes stacks", "them"),
    ),
    "mark_consume": partial(
        _condition_consume_edges,
        fan=_ConditionFan("mark", "mark_consume", "consumes the mark", "it"),
    ),
    "mark_applier": _mark_applier_edges,
    "detonation_consume": partial(
        _condition_consume_edges,
        fan=_ConditionFan("stack", "detonate", "detonates stacks", "them"),
    ),
    "enhanced_consume": _enhanced_consume_edges,
}

_NAMED_APPLIER_ROLES = ("stack_consume", "detonation_consume", "mark_consume")

_EXECUTE_EXEMPT_ROLES = (
    "stack_consume",
    "detonation_consume",
    "mark_consume",
    "enhanced_consume",
)


def _named_applier_edges(
    scan: _EdgeScan, b: str, cons: list[tuple[str, str, str]]
) -> None:
    """Appliers and consumers the consumer's own structured rows name."""
    if not scan.has_consume_role(b, _NAMED_APPLIER_ROLES):
        return
    bt = scan.texts[b]
    for m in _P_NAMED_APPLIER_STACK.finditer(bt):
        nm = m.group(1)
        if re.search(r"(does not|cannot|do not|won't|no)\s*$", nm):
            continue
        named = nm.split(" and ")[-1].strip()
        a = scan.slot_from_name(named) or scan.slot_from_name(nm)
        if a and a != b:
            atom = cons[0][2] if cons else "stack consume"
            cite = f"{b} names {named} as the stack applier ({atom})"
            scan.add(a, b, "stack_consume", cite)
    for m in _P_NAMED_APPLIER_COND.finditer(bt):
        _named_condition_edges(scan, b, m)
    for m in _P_NAMED_CONSUMER.finditer(bt):
        a = scan.slot_from_name(m.group(1))
        if a and a != b:
            cite = f"{b} names {m.group(1)} as the stack consumer"
            scan.add(b, a, "mark_applier", cite)


def _named_condition_edges(scan: _EdgeScan, b: str, match: re.Match[str]) -> None:
    """Both halves of a "when X or Y has applied" clause, as edges."""
    for g in (match.group(1), match.group(2)):
        a = scan.slot_from_name(g)
        if a and a != b:
            scan.add(
                a, b, "enhanced_consume", f"{b} names {g} as the condition applier"
            )


def _execute_edges(
    scan: _EdgeScan, b: str, cons: Iterable[tuple[str, str, str]]
) -> None:
    """Execute and stored-damage consumers come after ALL other damage.

    A slot that already consumes stacks or marks is exempt: its consume
    relationship dominates the missing-health rider.
    """
    if not any(kind in ("execute", "stored_consume") for kind, _, _ in cons):
        return
    if scan.has_consume_role(b, _EXECUTE_EXEMPT_ROLES):
        return
    for a in _damaging_slots(scan, b):
        scan.add(
            a,
            b,
            "execute",
            f"{b} is a missing-health/stored execute — after {a}'s damage",
        )


def _pairwise_edges(scan: _EdgeScan) -> None:
    """Setup slots before their consumers, one fan-out per consume atom."""
    for b, cons in scan.consume_atoms.items():
        for kind, _cond, cite in cons:
            fan = _CONSUME_FANS.get(kind)
            if fan is not None:
                fan(scan, b, cite)
        _named_applier_edges(scan, b, cons)
        _execute_edges(scan, b, cons)


def _self_declared_mark_applier_edges(scan: _EdgeScan) -> None:
    """A slot whose own prose says the champion's abilities consume its mark.

    Ezreal W and Ryze E: the slot goes before the burst it feeds.
    """
    for b in scan.corpora:
        if (
            _P_ABILITY_CONSUMES_MARK.search(scan.texts[b])
            and "phrase:marks-target" in scan.apply_atoms[b]
        ):
            for d in _damaging_slots(scan, b):
                cite = f"{b}'s mark is consumed by abilities"
                scan.add(b, d, "mark_applier", cite)


def _shred_fan_out(scan: _EdgeScan, s: str) -> None:
    """A resistance shred comes before every castable damaging slot."""
    if not scan.infos[s].get("target_debuff"):
        return
    for d in _damaging_slots(scan, s):
        cite = f"{s} applies target_debuff resistance shred — before {d}"
        scan.add(s, d, "shred", cite)


def _buff_fan_out(scan: _EdgeScan, s: str) -> None:
    """A damage-amplifying stat buff comes before every castable damaging slot."""
    amp_keys = [a for a in scan.apply_atoms[s] if a.startswith("stat_buff(")]
    if not amp_keys:
        return
    for d in _damaging_slots(scan, s):
        cite = f"{s} {amp_keys[0]} amplifies ability damage — before {d}"
        scan.add(s, d, "buff", cite)


def _cc_fan_out(scan: _EdgeScan, s: str, champion_name: str) -> None:
    """Crowd control that orders the burst comes before its damage."""
    atoms = scan.apply_atoms[s]
    if not any(a.startswith("cc_kind=") for a in atoms):
        return
    if not _cc_orders_the_burst(champion_name, s):
        return
    for d in _damaging_slots(scan, s):
        cite = f"{s} applies cc_kind crowd control — setup before {d}"
        scan.add(s, d, "cc_setup", cite)


def _amp_fan_out(scan: _EdgeScan, s: str) -> None:
    """A damage-taken amplifier comes before every castable damaging slot."""
    if not scan.has_consume_role(s, ("amp",)):
        return
    for d in _damaging_slots(scan, s):
        cite = f"{s} amplifies damage taken ({s}'s AMP atom) — before {d}"
        scan.add(s, d, "amp", cite)


def _fan_out_edges(scan: _EdgeScan, champion_name: str) -> None:
    """Shred, buff, crowd control and amp before all castable damage."""
    for s in scan.corpora:
        if "passive-row(cd=0)" in scan.apply_atoms[s]:
            continue
        _shred_fan_out(scan, s)
        _buff_fan_out(scan, s)
        _cc_fan_out(scan, s, champion_name)
        _amp_fan_out(scan, s)


def _first_citation_of_each(edges: Iterable[_Edge]) -> list[_Edge]:
    """One edge per ``(setup, consume, kind)``, keeping the first citation."""
    seen: set[tuple[str, str, str]] = set()
    out: list[_Edge] = []
    for e in edges:
        key = (e.setup, e.consume, e.kind)
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out
