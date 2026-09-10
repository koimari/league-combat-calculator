"""The twelve edge kinds inferred from a champion's own rows."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

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
    _is_damage_row,
    _recast_parent,
    _slot_corpus,
)
from .champions import get_champion_option_rotation
from .control_spec import NO_CONTROL_KIND


# comment-ok: width - a pylint pragma cannot wrap
def detect_setup_consume_edges(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-nested-blocks,too-many-return-statements,unused-argument
    champion_name: str,
    ability_damages: Mapping[str, Any],
    champion_data: Mapping[str, Any],
    option_keys: Mapping[str, list[str]],
) -> list[_Edge]:
    """Detect setup→consume ordering constraints from typed atoms.

    See the module docstring for the atom taxonomy.  Returns a list of
    :class:`_Edge` constraints; a champion with no detectable signal
    returns ``[]`` and keeps its certified/default order.
    """

    slots = [s for s in _CAST_SLOTS if isinstance(ability_damages.get(s), Mapping)]
    corpora = {
        s: _slot_corpus(
            champion_data, s, recast_of=_recast_parent(ability_damages.get(s))
        )
        for s in slots
    }
    corpora = {s: c for s, c in corpora.items() if c}
    if not corpora:
        return []
    infos = {s: ability_damages[s] for s in corpora}
    texts = {s: _corpus_text(c) for s, c in corpora.items()}
    atexts = {s: _corpus_attrs(c) for s, c in corpora.items()}
    slot_by_name: dict[str, str] = {}
    for s, c in corpora.items():
        for n in c["names"]:
            if n:
                slot_by_name[n.lower()] = s

    def slot_from_name(nm: str) -> str | None:
        nm = nm.strip().lower()
        if nm in slot_by_name:
            return slot_by_name[nm]
        for key, s in slot_by_name.items():
            if key.startswith(nm) or nm.startswith(key):
                return s
        return None

    edges: list[_Edge] = []

    def add(a: str, b: str, kind: str, cite: str) -> None:
        if a != b and a in corpora and b in corpora:
            edges.append(_Edge(a, b, kind, cite))

    # recast adjacency: a recast rides its parent's casts on the timeline.
    # ``recast_of`` on the parsed entry is the ONLY authority for that link
    # (D-11) — the name-based "Q plus Q2 means a recast" fallback that used
    # to sit here masked every unstamped recast slot, so the fail-closed
    # half of the rule could never fire.
    for s in slots:
        parent = infos.get(s, {}).get("recast_of")
        if parent and parent in corpora:
            add(parent, s, "recast", f"{s} is {parent}'s recast (recast_of atom)")

    # ── typed apply atoms per slot ──
    apply_atoms: dict[str, list[str]] = {}
    for s in corpora:
        info = infos[s]
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
        if _P_APPLIES_STACK.search(texts[s]):
            atoms.append("phrase:applies-stack")
        if _P_MARKS_TARGET.search(texts[s]):
            atoms.append("phrase:marks-target")
        apply_atoms[s] = atoms

    # champion passive: "abilities apply a stack/mark of X" -> every slot
    # applies X (Mel Overwhelm, Lux Illumination, ...)
    passive_applies: list[str] = []
    for ps in ("P", "passive"):
        pc = _slot_corpus(champion_data, ps)
        if pc:
            t = _corpus_text(pc)
            passive_applies.extend(
                m.group(2).strip().lower()
                for m in _P_PASSIVE_ABILITIES_APPLY.finditer(t)
            )
            if _P_PASSIVE_ABILITIES_MARK.search(t):
                passive_applies.append("__mark__")

    def applies_condition(s: str, cond_token: str) -> bool:
        atoms = apply_atoms[s]
        t = texts[s]
        # a cd-0 row (on-hit/passive) applies through the AUTO STREAM, not a
        # cast — it can never be a cast-order setup endpoint
        if "passive-row(cd=0)" in atoms:
            return False
        if passive_applies:
            if cond_token == "stack":
                return True
            if cond_token == "mark" and "__mark__" in passive_applies:
                return True
            if any(nm != "__mark__" and nm in t for nm in passive_applies):
                return True
        if cond_token == "stack":
            return any("stack" in a for a in atoms)
        if cond_token == "mark":
            return "phrase:marks-target" in atoms or "target_debuff" in " ".join(atoms)
        return any(cond_token in a for a in atoms)

    # ── typed consume atoms per slot ──
    # The atom vocabulary is the module OPTIONS rotation declarations (issue
    # #145): a consume/execute declaration with ``setup_slot`` carries the
    # FULL edge (setup_slot -> this slot) and is added directly — it never
    # depends on the applier-corpus phrase.  Declarations without
    # ``setup_slot`` fall back to the corpus-based pairing below, keyed by
    # their ``kind`` (the closed edge taxonomy).
    rotations = get_champion_option_rotation(champion_name)
    consume_atoms: dict[str, list[tuple[str, str, str]]] = {}
    for b in corpora:
        info = infos[b]
        cons: list[tuple[str, str, str]] = []
        for key in option_keys.get(b, []) + option_keys.get("__all__", []):
            decl = rotations.get(key)
            if not decl:
                continue
            role = str(decl.get("role", ""))
            if role in ("self_state", "irrelevant", "unsupported"):
                continue
            setup_slot = decl.get("setup_slot")
            if setup_slot:
                # The declaration carries the full edge: the setup slot must
                # cast before this consumer (Diana Q Moonlight -> E reset).
                if setup_slot in corpora and setup_slot != b:
                    kind = str(
                        decl.get("kind") or _DIRECT_EDGE_KIND.get(role, "mark_consume")
                    )
                    add(
                        setup_slot,
                        b,
                        kind,
                        f"{b} consumes {setup_slot}'s setup via option {key} "
                        f"({kind})",
                    )
                continue
            kind = str(decl.get("kind") or role)
            cond = str(decl.get("condition") or kind)
            if role == "execute" and not _is_damage_row(info):
                continue
            cons.append((kind, cond, f"option {key}"))
        if info.get("post_hit_proc"):
            nm = (
                info["post_hit_proc"].get("name", "proc")
                if isinstance(info["post_hit_proc"], Mapping)
                else "proc"
            )
            cons.append(("detonation_consume", "stacks", f"post_hit_proc {nm!r}"))
        execute_ratio = float(info.get("execute_threshold_ratio", 0.0) or 0.0)
        if execute_ratio > 0 and _is_damage_row(info):
            cons.append(
                (
                    "execute",
                    "execute",
                    f"execute_threshold_ratio={execute_ratio:g}",
                )
            )
        at = atexts[b]
        if _ATTR_PER_STACK.search(at):
            cons.append(
                (
                    "stack_consume",
                    "stacks",
                    f"attribute {_ATTR_PER_STACK.search(at).group(0)!r}",
                )
            )
        if _ATTR_ENHANCED_DMG.search(at):
            if _P_TARGET_MISSING.search(texts[b]) and _is_damage_row(info):
                # "Enhanced ... based on the target's missing health" rows are
                # missing-health executes, not conditional-vs-state consumes
                # (Seraphine Q: up to 75% bonus vs missing health).
                cons.append(
                    (
                        "execute",
                        "execute",
                        f"attribute {_ATTR_ENHANCED_DMG.search(at).group(0)!r} + "
                        f"target-missing-health",
                    )
                )
            else:
                cons.append(
                    (
                        "enhanced_consume",
                        "enhanced",
                        f"attribute {_ATTR_ENHANCED_DMG.search(at).group(0)!r}",
                    )
                )
        if _ATTR_DETONATION.search(at):
            cons.append(
                (
                    "detonation_consume",
                    "stacks",
                    f"attribute {_ATTR_DETONATION.search(at).group(0)!r}",
                )
            )
        if (
            _ATTR_MISSING.search(at)
            and _P_TARGET_MISSING.search(texts[b])
            and _is_damage_row(info)
        ):
            cons.append(
                (
                    "execute",
                    "execute",
                    "attribute Missing Health + target-missing-health",
                )
            )
        if _ATTR_MARK_DMG.search(at) or _P_ABILITY_CONSUMES_MARK.search(texts[b]):
            cons.append(("mark_consume", "mark", "mark consumption"))
        if _ATTR_STORED_DMG.search(at):
            cons.append(
                (
                    "stored_consume",
                    "stored",
                    f"attribute {_ATTR_STORED_DMG.search(at).group(0)!r}",
                )
            )
        consume_atoms[b] = cons

    def has_consume_role(b: str, roles: tuple[str, ...]) -> bool:
        return any(r in roles for r, _, _ in consume_atoms[b])

    # ── pairwise edges: setup slots before their consumers ──
    for b, cons in consume_atoms.items():
        bt = texts[b]
        for kind, _cond, cite in cons:
            if kind == "dot_consume":
                for a in corpora:
                    if (
                        a != b
                        and any(x.startswith("dot_duration") for x in apply_atoms[a])
                        and "passive-row(cd=0)" not in " ".join(apply_atoms[a])
                    ):
                        add(
                            a,
                            b,
                            "dot_consume",
                            f"{b} {cite} consumes the champion's poison; {a} "
                            f"{', '.join(apply_atoms[a])} applies it",
                        )
            elif kind == "stack_consume":
                for a in corpora:
                    if a != b and applies_condition(a, "stack"):
                        add(
                            a,
                            b,
                            "stack_consume",
                            f"{b} {cite} consumes stacks; {a} "
                            f"{', '.join(apply_atoms[a])} applies them",
                        )
            elif kind == "mark_consume":
                for a in corpora:
                    if a != b and applies_condition(a, "mark"):
                        add(
                            a,
                            b,
                            "mark_consume",
                            f"{b} {cite} consumes the mark; {a} "
                            f"{', '.join(apply_atoms[a])} applies it",
                        )
            elif kind == "mark_applier":
                for a in corpora:
                    if a != b and _is_damage_row(infos[a]) and _castable(infos[a], a):
                        add(
                            b,
                            a,
                            "mark_applier",
                            f"{b} {cite} applies a mark consumed by any next damaging ability",
                        )
            elif kind == "detonation_consume":
                for a in corpora:
                    if a != b and applies_condition(a, "stack"):
                        add(
                            a,
                            b,
                            "detonate",
                            f"{b} {cite} detonates stacks; {a} "
                            f"{', '.join(apply_atoms[a])} applies them",
                        )
            elif kind == "enhanced_consume":
                if not _P_COND_PHRASE.search(bt) or _P_SELF_RESOURCE.search(bt):
                    continue
                for condtok, pattern in _CONDITIONS:
                    if not re.search(pattern, bt):
                        continue
                    for a in corpora:
                        if a == b:
                            continue
                        at = texts[a]
                        if re.search(pattern, at) and any(
                            x.startswith(
                                (
                                    "dot_duration",
                                    "cc_kind",
                                    "phrase:applies-stack",
                                    "applies_dot_stack",
                                    "target_debuff",
                                )
                            )
                            for x in apply_atoms[a]
                        ):
                            add(
                                a,
                                b,
                                "enhanced_consume",
                                f"{b} {cite} enhanced vs {condtok}; {a} applies "
                                f"{condtok} ({', '.join(apply_atoms[a])})",
                            )
                    break
        # named appliers/consumers inside the consumer's own structured rows
        if has_consume_role(b, ("stack_consume", "detonation_consume", "mark_consume")):
            for m in _P_NAMED_APPLIER_STACK.finditer(bt):
                nm = m.group(1)
                if re.search(r"(does not|cannot|do not|won't|no)\s*$", nm):
                    continue
                a = slot_from_name(nm.split(" and ")[-1].strip()) or slot_from_name(nm)
                if a and a != b:
                    atom = cons[0][2] if cons else "stack consume"
                    add(
                        a,
                        b,
                        "stack_consume",
                        f"{b} names {nm.split(' and ')[-1].strip()} as the stack applier ({atom})",
                    )
            for m in _P_NAMED_APPLIER_COND.finditer(bt):
                for g in (m.group(1), m.group(2)):
                    a = slot_from_name(g)
                    if a and a != b:
                        add(
                            a,
                            b,
                            "enhanced_consume",
                            f"{b} names {g} as the condition applier",
                        )
            for m in _P_NAMED_CONSUMER.finditer(bt):
                a = slot_from_name(m.group(1))
                if a and a != b:
                    add(
                        b,
                        a,
                        "mark_applier",
                        f"{b} names {m.group(1)} as the stack consumer",
                    )
        # execute / stored-damage consumers come after ALL other damage;
        # slots that already consume stacks/marks (detonators) are exempt —
        # their consume relationship dominates the missing-health rider.
        if any(
            kind in ("execute", "stored_consume") for kind, _, _ in cons
        ) and not has_consume_role(
            b,
            (
                "stack_consume",
                "detonation_consume",
                "mark_consume",
                "enhanced_consume",
            ),
        ):
            for a in corpora:
                if a != b and _is_damage_row(infos[a]) and _castable(infos[a], a):
                    add(
                        a,
                        b,
                        "execute",
                        f"{b} is a missing-health/stored execute — after {a}'s damage",
                    )

    # mark applier by own text: slot says its mark is consumed by the
    # champion's abilities (Ezreal W, Ryze E) -> slot before the burst
    for b in corpora:
        if (
            _P_ABILITY_CONSUMES_MARK.search(texts[b])
            and "phrase:marks-target" in apply_atoms[b]
        ):
            for a in corpora:
                if a != b and _is_damage_row(infos[a]) and _castable(infos[a], a):
                    add(b, a, "mark_applier", f"{b}'s mark is consumed by abilities")

    # ── fan-out: shred / buff / cc / amp before all castable damage ──
    for s in corpora:
        info = infos[s]
        atoms = apply_atoms[s]
        if "passive-row(cd=0)" in atoms:
            continue
        if info.get("target_debuff"):
            for d in corpora:
                if d != s and _is_damage_row(infos[d]) and _castable(infos[d], d):
                    add(
                        s,
                        d,
                        "shred",
                        f"{s} applies target_debuff resistance shred — before {d}",
                    )
        amp_keys = [a for a in atoms if a.startswith("stat_buff(")]
        if amp_keys:
            for d in corpora:
                if d != s and _is_damage_row(infos[d]) and _castable(infos[d], d):
                    add(
                        s,
                        d,
                        "buff",
                        f"{s} {amp_keys[0]} amplifies ability damage — before {d}",
                    )
        if any(a.startswith("cc_kind=") for a in atoms) and _cc_orders_the_burst(
            champion_name, s
        ):
            for d in corpora:
                if d != s and _is_damage_row(infos[d]) and _castable(infos[d], d):
                    add(
                        s,
                        d,
                        "cc_setup",
                        f"{s} applies cc_kind crowd control — setup before {d}",
                    )
        if has_consume_role(s, ("amp",)):
            for d in corpora:
                if d != s and _is_damage_row(infos[d]) and _castable(infos[d], d):
                    add(
                        s,
                        d,
                        "amp",
                        f"{s} amplifies damage taken ({s}'s AMP atom) — before {d}",
                    )

    seen: set[tuple[str, str, str]] = set()
    out: list[_Edge] = []
    for e in edges:
        key = (e.setup, e.consume, e.kind)
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out
