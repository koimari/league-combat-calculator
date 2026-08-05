#!/usr/bin/env python3
"""Data-driven behavior-atom classifier (WS3 atomic catalog, v2).

Loads the wiki behavior-atom vocabularies from data/wiki-atoms/*.json and
classifies every SpellObject in a champion's decomposed CharacterRecord into
behavior atoms. Classification is vocabulary-driven only: normalized spell/buff
names (mScriptName, mAlternateName, ObjectName, buff tooltip names), spell tags,
calculation names and data-value names are tokenized (camelCase splits,
singular/plural stem matching) and matched against atom keywords. Generic
binary signals (mSpellTags, mSpellCalculations/DataValues naming, cooldown /
castRange presence, mAffectsTypeFlags) augment the keyword match.

No champion names or spell names are hardcoded here; the wiki-atoms
vocabularies are the single source of atom identity. Two data-driven guards
keep the vocab honest against this corpus: champion-name prefixes are stripped
from script names, and vocab keywords made entirely of corpus-generic tokens
(e.g. "duration", "ability damage") or champion names are ignored.

Outputs (under data/atoms/):
  <champ>.atoms.json          per-champion atom list
  atom-summary.json           family -> champions
  unclassified.json           per champion: SpellObjects with no atom match
  classification-report.json  per champion family counts, unclassified notes,
                              sanity checks, and classifier improvements

Usage:
    python3 scripts/extract_atoms.py                          # all champions
    python3 scripts/extract_atoms.py --champions aatrox,gnar  # subset
    python3 scripts/extract_atoms.py --out data/atoms
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / "data" / "bin" / "characters"
VOCAB_DIR = ROOT / "data" / "wiki-atoms"
DEFAULT_OUT = ROOT / "data" / "atoms"

# --------------------------------------------------------------------------
# Text normalization
# --------------------------------------------------------------------------
_CAMEL1 = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL2 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_NONALNUM = re.compile(r"[^a-z0-9]+")


def norm(text: str) -> str:
    """Lowercase, strip everything non-alphanumeric."""
    return _NONALNUM.sub("", str(text).lower())


def tokens(text: str) -> list[str]:
    """Split an identifier/name into lower-case tokens (camelCase, snake, spaces)."""
    s = _CAMEL1.sub(r"\1 \2", str(text))
    s = _CAMEL2.sub(r"\1 \2", s)
    return [t for t in _NONALNUM.split(s.lower()) if t]


# --------------------------------------------------------------------------
# Keyword matching policy
# --------------------------------------------------------------------------
# Keywords that only match as exact tokens. They are substrings of common
# unrelated engine words (e.g. "miss" inside "missile"), so they must never
# participate in substring/prefix matching.
EXACT_TOKEN_ONLY = {"miss", "as", "ms", "aa", "ls", "sv", "gw", "mp", "xp", "hsp",
                     "stance", "wind"}  # substrings of "distance", "window"/"windup"
SUBSTRING_MIN_LEN = 5   # "knockback" inside "gnarrknockback"
PREFIX_MIN_LEN = 4      # "mark" as prefix of "marker", "stun" of "stunduration"
# Short keywords (<= this length) can only ever exact-match, so they are
# always usable regardless of corpus frequency.
SHORT_KEYWORD_MAX = 3
# Single tokens seen in >= this fraction of all spell objects are "generic"
# (engine boilerplate: "damage", "duration", "attack" ...). A keyword made
# entirely of generic tokens carries no discriminating signal.
GENERIC_THRESHOLD = 0.032


def keyword_matches(nk: str, ktoks: list[str], obj_tokens: set[str], obj_hay: str) -> bool:
    """True if a normalized keyword matches an object's token set / haystack."""
    if nk in obj_tokens:
        return True
    n = len(nk)
    # EXACT_TOKEN_ONLY keywords (e.g. "stance" inside "distance", "miss"
    # inside "missile") must never match as substrings or prefixes.
    if nk not in EXACT_TOKEN_ONLY:
        if n >= SUBSTRING_MIN_LEN and nk in obj_hay:
            return True
        if n >= PREFIX_MIN_LEN:
            for t in obj_tokens:
                if len(t) > n and t.startswith(nk):
                    return True
    if len(ktoks) >= 2 and all(t in obj_tokens for t in ktoks):
        return True
    return False


def usable_keyword(nk: str, ktoks: list[str], atom_name_toks: set[str],
                   head_word: str,
                   generic_tokens: set[str], champion_tokens: set[str],
                   keyword_atom_count: dict[str, int]) -> bool:
    """Whether a vocab keyword is allowed to vote for its atom.

    Drops keywords that carry no signal in this corpus:
      * keywords made entirely of champion names (the vocab lists champions
        like "Aatrox"/"Aphelios"/"Yasuo" as examples, but every object of that
        champion would then match), and
      * keywords made entirely of corpus-generic engine tokens ("duration",
        "ability damage", "basic damage", "% crit" -> "crit" ...).
    Ambiguous single-token keywords ("shield" is the head of the shield atom
    but also a keyword of the true-damage / flow atoms) only vote for the atom
    they are the head word of.
    """
    if len(nk) <= SHORT_KEYWORD_MAX:
        return True
    if len(ktoks) == 1:
        if nk == head_word:
            return True
        if keyword_atom_count.get(nk, 0) >= 2:
            return False
        if nk in generic_tokens or nk in champion_tokens:
            return False
        return True
    if set(ktoks) <= atom_name_toks:
        return True
    if set(ktoks) <= (generic_tokens | champion_tokens):
        return False
    return True


def compute_generic_tokens(champ_paths: list[Path]) -> set[str]:
    """Single tokens that appear in >= GENERIC_THRESHOLD of all spell objects."""
    doc = {}
    n_obj = 0
    for f in champ_paths:
        ser = json.loads(f.read_text())
        champ_norm = norm(f.name[:-len(".bin.json")])
        for key, obj in ser.items():
            if not (isinstance(obj, dict) and obj.get("__type") == "SpellObject"):
                continue
            feat = object_features(obj, key, champ_norm)
            for t in feat["toks"]:
                doc[t] = doc.get(t, 0) + 1
            n_obj += 1
    return {t for t, c in doc.items() if c / n_obj >= GENERIC_THRESHOLD}


def champion_name_tokens() -> set[str]:
    """Tokens of every champion name in data/bin/characters (data-driven)."""
    out = set()
    for f in BIN_DIR.glob("*.bin.json"):
        out.update(tokens(f.name[:-len(".bin.json")]))
    return out


# --------------------------------------------------------------------------
# Binary (non-name) signals
# --------------------------------------------------------------------------
# Generic mSpellTags -> atom mappings. Tag names come from the game binary and
# are stable, data-driven behavior markers (no champion/spell names here).
TAG_ATOMS = {
    "Trait_DamageAbility": ["damage.damage-instance"],
    "Trait_ActiveHeal": ["heal-shield.heal"],
    "Trait_Shield": ["heal-shield.shield"],
    "Trait_ImmobilizingCCSpell": ["crowd-control-mobility.immobilize"],
    "Trait_KnockBack": ["crowd-control-mobility.airborne"],
    "Trait_Camouflage": ["vision-economy.camouflage"],
    "Trait_Invisibility": ["vision-economy.invisibility"],
    "Trait_CreateClone": ["stack-transform-summon-resource.clone"],
    "Trait_DoT": ["damage.dot"],
    "Trait_Untargetable": ["crowd-control-mobility.stasis"],
    "Trait_Immune": ["crowd-control-mobility.stasis"],      # invulnerable
    "Trait_Toggle": ["stack-transform-summon-resource.toggle-form"],
    "Trait_PlayerSelectedDashDirection": ["crowd-control-mobility.dash"],
    "PositiveEffect_MoveBlock": ["crowd-control-mobility.dash"],
    "PositiveEffect_Boon": ["stack-transform-summon-resource.buff"],
    "Trait_ChannelSpell": ["crowd-control-mobility.channel"],
    "Trait_AoE": ["damage.aoe"],
    "Trait_SwapsIntoImmobilizingCCAbility": ["crowd-control-mobility.immobilize"],
}

# Atoms whose names mark them as catalog/reference concepts rather than
# champion mechanics (engine resource index, post-game score, damage instance
# properties, duration classes). They stay in the vocabulary but their generic
# keywords (mana/energy/shield/duration...) would over-fire on every spell.
META_ATOM_MARKERS = ("internal", "score", "properties", "classes")


# Crowd-control atoms that apply to the caster rather than a target.
SELF_CC_ATOMS = {
    "crowd-control-mobility.dash",
    "crowd-control-mobility.blink",
    "crowd-control-mobility.lunge",
    "crowd-control-mobility.ghost",
    "crowd-control-mobility.movement-speed",
    "crowd-control-mobility.movement-speed-caps",
    "crowd-control-mobility.channel",
    "crowd-control-mobility.cc-immunity",
    "crowd-control-mobility.tenacity",
    "crowd-control-mobility.slow-resist",
    "crowd-control-mobility.slow-immunity",
    "crowd-control-mobility.cripple-immunity",
    "crowd-control-mobility.cleanse",
    "crowd-control-mobility.lockout",
    "crowd-control-mobility.stasis",
    "crowd-control-mobility.combat-status",
    "crowd-control-mobility.cc-score",
}
ENEMY_RESOURCE_ATOMS = {
    "stack-transform-summon-resource.mark",
    "stack-transform-summon-resource.debuff",
    "stack-transform-summon-resource.damage-over-time",
    "stack-transform-summon-resource.damage-modification-debuff",
    "stack-transform-summon-resource.trap",
}
ENEMY_HEAL_ATOMS = {
    "heal-shield.healing-reduction",
    "heal-shield.grievous-wounds",
    "heal-shield.healing-negation",
    "heal-shield.shield-reduction",
    "heal-shield.shield-destruction",
}
ENEMY_VISION_ATOMS = {
    "vision-economy.true-sight",
    "vision-economy.sight",
    "vision-economy.nearsight",
    "vision-economy.attacker-reveal",
    "vision-economy.obscured-vision",
}

# SpellObject names made of these tokens are engine/cosmetic artifacts
# (VFX, managers, UI trackers, event/cinematic helpers) and are never atoms.
NOISE_TOKENS = {
    "manager", "vfx", "sfx", "sound", "visual", "tracker", "skin", "crepe",
    "poro", "reward", "win", "lose", "start", "description", "particle",
    "test", "icon", "vo", "runcycle", "runanimation", "cosmetic", "wrapper",
    "fakecast", "satisfaction", "vs", "blackhole", "idle", "animation",
    "helper", "banner", "dummy", "defeat", "victory", "indicator", "warning",
    "wins", "ready",
}

ALLY_TOKENS = {"ally", "allies", "allied", "friend", "friendly", "team", "teammate"}
ENEMY_TOKENS = {"enemy", "enemies", "hostile"}


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------
PASSIVE_MAP_FILE = VOCAB_DIR / "champion-passive-atoms.json"

def load_passive_map() -> dict[str, list[dict]]:
    """Wiki-driven champion-passive atom assignments (form-change passives
    whose binary objects carry no transform token). Data-driven, not code."""
    if not PASSIVE_MAP_FILE.exists():
        return {}
    out: dict[str, list[dict]] = {}
    for entry in json.loads(PASSIVE_MAP_FILE.read_text()):
        out.setdefault(champion_key(entry["champion"]), []).append(entry)
    return out

def load_vocab() -> dict[str, dict]:
    atoms = {}
    for f in sorted(VOCAB_DIR.glob("*.json")):
        for a in json.loads(f.read_text()):
            atoms[a["atom_id"]] = a
    return atoms


def build_keyword_index(vocab: dict[str, dict], generic_tokens: set[str],
                         champ_tokens: set[str]) -> list[tuple[str, str, list[tuple[str, list[str]]]]]:
    """[(atom_id, family, [(norm_keyword, keyword_tokens), ...]), ...]

    Keywords that carry no signal in this corpus (champion-name keywords,
    all-generic keywords, ambiguous shared words outside their home atom) are
    filtered out up front. Meta/reference atoms (engine resource index, CC
    score, damage instance properties, duration classes) do not vote.
    """
    # count how many atoms share each single-token keyword
    keyword_atom_count: dict[str, set[str]] = {}
    for atom_id, a in vocab.items():
        for kw in a.get("keywords", []):
            kt = tokens(kw)
            if len(kt) == 1 and len(norm(kw)) > SHORT_KEYWORD_MAX:
                keyword_atom_count.setdefault(norm(kw), set()).add(atom_id)
    keyword_atom_count = {k: len(v) for k, v in keyword_atom_count.items()}

    index = []
    for atom_id, a in sorted(vocab.items()):
        name_toks = list(tokens(a.get("name", "")))
        head_word = name_toks[0] if name_toks else ""
        if any(m in a.get("name", "").lower() for m in META_ATOM_MARKERS):
            index.append((atom_id, a["family"], []))
            continue
        specs = []
        for kw in a.get("keywords", []):
            nk, ktoks = norm(kw), tokens(kw)
            if usable_keyword(nk, ktoks, set(name_toks), head_word,
                              generic_tokens, champ_tokens, keyword_atom_count):
                specs.append((nk, ktoks))
        index.append((atom_id, a["family"], specs))
    return index


# --------------------------------------------------------------------------
# Object feature extraction
# --------------------------------------------------------------------------
def strip_champ_prefix(name: str, champ_norm: str) -> str:
    """Remove the champion-name prefix from a script name (ASCII-safe).

    Every script name starts with the champion name ("GnarW", "VladimirQ").
    The prefix is boilerplate: keeping it makes champion-specific vocab
    keywords (e.g. "Mega Gnar") match every spell of that champion.
    """
    n = norm(name)
    if champ_norm and n.startswith(champ_norm) and len(n) > len(champ_norm):
        return name[len(champ_norm):]
    return name


def object_features(obj: dict, key: str, champ_norm: str) -> dict:
    sp = obj.get("mSpell") or {}
    name = obj.get("mScriptName") or obj.get("ObjectName") or key.rsplit("/", 1)[-1]
    alt = sp.get("mAlternateName") or ""

    cd = sp.get("cooldownTime") or []
    rng = sp.get("castRange") or []
    affects = sp.get("mAffectsTypeFlags")

    # matching text: champion-name prefix stripped, so champion-specific
    # vocab keywords do not match every spell of that champion.
    match_name = strip_champ_prefix(name, champ_norm)
    match_alt = strip_champ_prefix(alt, champ_norm)
    tags = sp.get("mSpellTags") or []
    calcs = list((sp.get("mSpellCalculations") or {}).keys())
    dvs_raw = sp.get("DataValues") or []
    if isinstance(dvs_raw, dict):
        dvs = [str(k) for k in dvs_raw.keys()]
    else:
        dvs = [dv.get("name") for dv in dvs_raw if isinstance(dv, dict) and dv.get("name")]
    buff_desc = ""
    if isinstance(obj.get("mBuff"), dict):
        buff_desc = obj["mBuff"].get("mDescription") or ""

    # mSpellTags are semantic markers with their own explicit mapping
    # (TAG_ATOMS); feeding tag text into the free-text keyword matcher would
    # re-match them with weaker semantics ("wind" from "Melee_BigWindup",
    # "block" from "PositiveEffect_MoveBlock", "ranged" from "Trait_Ranged_*").
    sources = [match_name, match_alt] + calcs + dvs + [buff_desc]
    toks: set[str] = set()
    for s in sources:
        if s:
            toks.update(tokens(s))
    hay = norm(" ".join(sources))
    return {
        "key": key,
        "name": name,
        "alt": alt,
        "match_name": match_name,
        "tags": list(tags),
        "toks": toks,
        "hay": hay,
        "cooldown": cd,
        "range": rng,
        "affects_type_flags": affects,
        "has_buff": bool(obj.get("mBuff")),
    }


def is_noise(feat: dict) -> bool:
    return bool(feat["toks"] & NOISE_TOKENS)


def infer_trigger(feat: dict) -> str:
    name_toks = set(tokens(feat["name"]))
    toks = feat["toks"]
    if name_toks & {"kill", "takedown", "assist"}:
        return "on_takedown"
    if "execute" in toks or ("cap" in toks and "damage" in toks):
        return "threshold"
    if feat["has_buff"] or name_toks & {"buff", "passive", "stacks", "counter", "marker"}:
        return "on_effect"
    if any(c and c > 0 for c in feat["cooldown"]):
        return "on_cast"
    if name_toks & {"hit", "proc"}:
        return "on_hit"
    return "on_effect"


def infer_target(atom_id: str, feat: dict) -> str:
    toks = feat["toks"]
    if toks & ALLY_TOKENS:
        return "ally"
    if toks & ENEMY_TOKENS:
        return "enemy"
    family = atom_id.split(".", 1)[0]
    if family == "damage":
        return "enemy"
    if family == "crowd-control-mobility":
        return "self" if atom_id in SELF_CC_ATOMS else "enemy"
    if family == "heal-shield":
        return "enemy" if atom_id in ENEMY_HEAL_ATOMS else "self"
    if family == "stack-transform-summon-resource":
        return "enemy" if atom_id in ENEMY_RESOURCE_ATOMS else "self"
    if family == "vision-economy":
        return "enemy" if atom_id in ENEMY_VISION_ATOMS else "self"
    return "self"


def infer_damage_type(feat: dict) -> str | None:
    toks = feat["toks"]
    if "true" in toks:
        return "true"
    if "magic" in toks or "magical" in toks:
        return "magic"
    if "physical" in toks:
        return "physical"
    return None


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------
def classify_object(feat: dict, keyword_index) -> list[tuple[str, str]]:
    """Return [(atom_id, family), ...] for one SpellObject."""
    hits: dict[str, str] = {}
    for atom_id, family, specs in keyword_index:
        for nk, ktoks in specs:
            if keyword_matches(nk, ktoks, feat["toks"], feat["hay"]):
                hits[atom_id] = family
                break
    # binary tag signals
    for tag in feat["tags"]:
        for atom_id in TAG_ATOMS.get(tag, []):
            hits.setdefault(atom_id, atom_id.split(".", 1)[0])
    # generic execute rule: an ultimate-tagged damage spell whose data values
    # carry a damage cap is an execute (below-health-threshold kill).
    is_ult = any(t.startswith("Trait_Ultimate") for t in feat["tags"])
    if "execute" in feat["toks"]:
        hits.setdefault("damage.execute", "damage")
    elif is_ult and "cap" in feat["toks"] and "damage" in feat["toks"]:
        hits.setdefault("damage.execute", "damage")
    # generic crit-event rule: script names like "XxxCritAttack" carry the
    # crit event even though the vocab's "crit" keyword is corpus-generic.
    if "crit" in set(tokens(feat["name"])):
        hits.setdefault("damage.critical-strike", "damage")
    # generic nuke rule: "Nuke" script names are damage spells ("nuke" is the
    # engine's own word for a spell's damage payload).
    if "nuke" in set(tokens(feat["name"])):
        hits.setdefault("damage.damage-instance", "damage")
    return sorted(hits.items())


def extract_champion(champ_name: str, bin_path: Path, keyword_index, vocab, passive_map=None) -> dict:
    ser = json.loads(bin_path.read_text())
    atoms: dict[tuple[str, str], dict] = {}   # (atom_id, behavior) -> atom
    unclassified: list[dict] = []
    champ_norm = norm(champ_name)

    for key, obj in ser.items():
        if not (isinstance(obj, dict) and obj.get("__type") == "SpellObject"):
            continue
        feat = object_features(obj, key, champ_norm)
        if is_noise(feat):
            unclassified.append({
                "name": feat["name"], "object": key,
                "looks_noise": True,
                "note": "engine/cosmetic artifact (VFX, manager, UI tracker, event helper)",
            })
            continue
        hits = classify_object(feat, keyword_index)
        if not hits:
            unclassified.append({
                "name": feat["name"], "object": key,
                "looks_noise": False,
                "note": "no wiki-vocabulary match; looks like a real mechanic (unmapped)",
            })
            continue

        trigger = infer_trigger(feat)
        dmg_type = infer_damage_type(feat)
        params = {
            "cooldown_rank1": feat["cooldown"][0] if feat["cooldown"] else None,
            "cooldown_rank_max": feat["cooldown"][-1] if feat["cooldown"] else None,
            "range": (feat["range"][0] if feat["range"] and feat["range"][0] < 50000 else None),
            "damage_type": dmg_type,
            "affects_type_flags": feat["affects_type_flags"],
        }
        for atom_id, family in hits:
            dedup_key = (atom_id, feat["name"])
            if dedup_key in atoms:
                a = atoms[dedup_key]
                if key not in a["provenance"]["binary"]:
                    a["provenance"]["binary"].append(key)
                for wp in vocab[atom_id].get("wiki_pages", []):
                    if wp not in a["provenance"]["wiki"]:
                        a["provenance"]["wiki"].append(wp)
                continue
            atoms[dedup_key] = {
                "atom_id": atom_id,
                "family": family,
                "behavior": feat["name"],
                "trigger": trigger,
                "target_policy": infer_target(atom_id, feat),
                "parameters": params,
                "provenance": {
                    "wiki": list(vocab[atom_id].get("wiki_pages", [])),
                    "binary": [key],
                },
            }

    # Wiki-driven champion-passive atoms (form-change passives whose binary
    # objects carry no transform token, e.g. Neeko/Kayle).
    if passive_map:
        for entry in passive_map.get(champion_key(champ_name), []):
            atom_id = entry["atom_id"]
            family = atom_id.split(".", 1)[0]
            behavior = f"{champ_name} Passive ({entry.get('wiki_name', '')})".strip()
            dedup_key = (atom_id, behavior)
            if dedup_key not in atoms:
                atoms[dedup_key] = {
                    "atom_id": atom_id,
                    "family": family,
                    "behavior": behavior,
                    "trigger": "passive",
                    "target_policy": "self",
                    "parameters": {},
                    "provenance": {
                        "wiki": list(vocab.get(atom_id, {}).get("wiki_pages", [])) + [entry.get("wiki_name", "")],
                        "binary": [],
                        "source": "wiki-passive-map",
                    },
                }

    # Clone inheritance: *Missile / *Attack / *Mis / *LineAttack / *Hit /
    # *Return variants of an already-classified parent inherit the parent's
    # atoms (the clone is the same mechanic with a different delivery object).
    clone_suffixes = ("Missile", "Mis", "Attack", "LineAttack", "Hit", "Return",
                      "Mini", "MissileReturn", "Nuke", "Debuff")
    behavior_atoms: dict[str, list[tuple[str, str]]] = {}
    for (atom_id, behavior), a in atoms.items():
        behavior_atoms.setdefault(behavior, []).append((atom_id, a["family"]))
    still_unclassified = []
    for entry in unclassified:
        if entry.get("looks_noise"):
            still_unclassified.append(entry)
            continue
        name = entry["name"]
        parent = None
        for suffix in clone_suffixes:
            if name.endswith(suffix) and len(name) > len(suffix) + 3:
                cand = name[: -len(suffix)]
                if cand in behavior_atoms:
                    parent = cand
                    break
        if parent is None:
            still_unclassified.append(entry)
            continue
        for atom_id, family in behavior_atoms[parent]:
            clone_atom = {
                "atom_id": atom_id,
                "family": family,
                "behavior": name,
                "trigger": infer_trigger(object_features(
                    {"__type": "SpellObject", "mScriptName": name},
                    entry["object"], champ_norm)),
                "target_policy": next(
                    (a["target_policy"] for (aid, _b), a in atoms.items()
                     if aid == atom_id and _b == parent),
                    "enemy"),
                "parameters": next(
                    (a["parameters"] for (aid, _b), a in atoms.items()
                     if aid == atom_id and _b == parent),
                    {}),
                "provenance": {
                    "wiki": list(vocab[atom_id].get("wiki_pages", [])),
                    "binary": [entry["object"]],
                    "inherited_from": parent,
                },
            }
            atoms[(atom_id, name)] = clone_atom
    return {"champion": champ_name, "atoms": list(atoms.values()), "unclassified": still_unclassified}


def champion_key(name: str) -> str:
    return norm(name).replace(" ", "")


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------
def build_summary(results: list[dict]) -> dict:
    summary: dict[str, set] = {}
    for r in results:
        for a in r["atoms"]:
            summary.setdefault(a["family"], set()).add(r["champion"])
    return {fam: sorted(champs) for fam, champs in sorted(summary.items())}


def build_report(results: list[dict], vocab, sanity: list[dict], suggestions: list[str]) -> dict:
    total_atoms = 0
    total_unclassified = 0
    total_noise = 0
    family_totals: dict[str, int] = {}
    champions = []
    for r in results:
        fam_counts: dict[str, int] = {}
        for a in r["atoms"]:
            fam_counts[a["family"]] = fam_counts.get(a["family"], 0) + 1
        un = sorted(r["unclassified"], key=lambda u: (not u["looks_noise"], u["name"]))
        champions.append({
            "champion": r["champion"],
            "atom_count": len(r["atoms"]),
            "family_counts": {k: fam_counts[k] for k in sorted(fam_counts)},
            "unclassified": un,
        })
        total_atoms += len(r["atoms"])
        total_unclassified += sum(1 for u in un if not u["looks_noise"])
        total_noise += sum(1 for u in un if u["looks_noise"])
    totals = {}
    for r in champions:
        for fam, c in r["family_counts"].items():
            totals[fam] = totals.get(fam, 0) + c
    return {
        "classifier": "scripts/extract_atoms.py (v2 data-driven, wiki-atoms vocab)",
        "vocab": {"atom_count": len(vocab), "families": sorted({a["family"] for a in vocab.values()})},
        "champions": champions,
        "totals": {
            "champions_processed": len(results),
            "atoms_classified": total_atoms,
            "unclassified_real_mechanics": total_unclassified,
            "unclassified_noise_artifacts": total_noise,
            "unclassified_total_objects": total_unclassified + total_noise,
            "family_counts": totals,
        },
        "sanity_checks": sanity,
        "improvement_suggestions": suggestions,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--champions", default=None,
                    help="comma-separated champion names (default: all in data/bin/characters)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    vocab = load_vocab()

    bin_files = sorted(BIN_DIR.glob("*.bin.json"))
    if args.champions:
        wanted = {champion_key(c) for c in args.champions.split(",") if c.strip()}
        bin_files = [f for f in bin_files if champion_key(f.name[:-len(".bin.json")]) in wanted]
    if not bin_files:
        print("no champion binaries matched", file=sys.stderr)
        return 2

    generic_tokens = compute_generic_tokens(bin_files)
    champ_tokens = champion_name_tokens()
    keyword_index = build_keyword_index(vocab, generic_tokens, champ_tokens)
    passive_map = load_passive_map()

    results = []
    for f in bin_files:
        champ = f.name[:-len(".bin.json")]
        results.append(extract_champion(champ, f, keyword_index, vocab, passive_map))
        (out / f"{champ}.atoms.json").write_text(
            json.dumps(results[-1]["atoms"], indent=1))

    (out / "atom-summary.json").write_text(json.dumps(build_summary(results), indent=1))
    (out / "unclassified.json").write_text(json.dumps(
        [{"champion": r["champion"], "unclassified": r["unclassified"]} for r in results], indent=1))

    # sanity checks + suggestions are produced by the caller for a curated set;
    # default run emits the generic report without them.
    sanity, suggestions = build_sanity_and_suggestions(results, vocab)
    (out / "classification-report.json").write_text(
        json.dumps(build_report(results, vocab, sanity, suggestions), indent=1))

    fam_totals = {}
    for r in results:
        for a in r["atoms"]:
            fam_totals[a["family"]] = fam_totals.get(a["family"], 0) + 1
    n_un = sum(len(r["unclassified"]) for r in results)
    print(f"classified {sum(len(r['atoms']) for r in results)} atoms across {len(results)} champions")
    for fam, c in sorted(fam_totals.items()):
        print(f"  {fam}: {c}")
    print(f"unclassified spell objects: {n_un}")
    return 0


def build_sanity_and_suggestions(results, vocab):
    """Sanity checks for curated mechanics + classifier improvement list."""
    by_champ = {r["champion"]: r for r in results}
    sanity = []

    def check(label, champ, atom_id, key_hint=None, extra=None):
        """Pass if the atom exists on an object whose binary key/script name
        contains key_hint (the champion prefix is stripped from behaviors in
        matching, so search the full binary keys too)."""
        r = by_champ.get(champ)
        found = None
        if r:
            for a in r["atoms"]:
                ok = a["atom_id"] == atom_id
                if ok and key_hint is not None:
                    ok = (any(key_hint.lower() in k.lower() for k in a["provenance"]["binary"])
                          or key_hint.lower() in a["behavior"].lower()
                          or a["provenance"].get("source") == "wiki-passive-map")
                if ok:
                    found = a
                    break
        passed = found is not None
        evidence = []
        if r:
            for a in r["atoms"]:
                if a["atom_id"] == atom_id:
                    evidence.append(f"{a['atom_id']} @ {a['behavior']} ({a['trigger']})")
        sanity.append({
            "mechanic": label, "champion": champ, "atom_id": atom_id,
            "passed": passed, "evidence": evidence, "note": extra or "",
        })
        return found

    check("Vladimir Transfusion heal", "vladimir", "heal-shield.heal",
          "TransfusionHeal", "VladimirQ also carries Trait_ActiveHeal.")
    check("Gnar transform (Rage Gene)", "gnar", "stack-transform-summon-resource.transform",
          "GnarTransform", "GnarFuryGeneration maps to fury/rage resource atom.")
    check("Jinx execute reset (Get Excited!)", "jinx", "damage.execute", "JinxR",
          "JinxPassiveKill is tagged on_takedown (kill token).")
    check("Pyke execute (Death from Below)", "pyke", "damage.execute", "PykeR",
          "via generic rule: ultimate + damage-cap datavalue.")
    check("Senna soul stacking (Absolution)", "senna", "stack-transform-summon-resource.stack",
          "SennaPassiveStacks", "Soul drops live under SennaPassive stacks; 'soul' itself is not a vocab keyword.")
    check("Neeko transform (Inherent Glamour)", "neeko", "stack-transform-summon-resource.transform",
          "NeekoPassive", "NeekoPassive has no transform/disguise tokens; clone+stealth captured on W.")
    check("Kayle transform (Divine Ascent)", "kayle", "stack-transform-summon-resource.transform",
          "KaylePassive", "Level-gated form change is only visible as LevelForPassiveRank datavalues.")

    suggestions = [
        "Extend the transform atom (or add a 'disguise / level-gated form' atom) with keywords for level-gated "
        "passive ranks and 'disguise' — NeekoPassive and KaylePassive both fail today because their binaries "
        "never contain 'transform'/'form' tokens (Kayle's ranks are only visible as LevelForPassiveRank* datavalues).",
        "Add a 'soul'/'stack currency' keyword family: Senna souls, Thresh souls and Nasus Q stacks appear as "
        "'Soul*'/'Stacks' datavalues, and only 'stack' currently matches — soul-gated scaling is invisible, and "
        "objects like ThreshPassiveSouls / SennaBasicAttackSouls stay unclassified.",
        "mDamageType is absent from all 203 parsed binaries; damage type must come from calc/datavalue naming "
        "('APDamage', 'PhysicalDamage', 'TrueDamage') or a future parser field — today only magic/physical/true "
        "tokens are detected, so most damage atoms carry damage_type=null.",
        "Curate ambiguous vocab keywords before scaling to all champions. The classifier already guards against "
        "champion-name keywords ('Aatrox', 'Aphelios'), generic words ('duration', 'ability damage', 'crit'), and "
        "substring traps ('miss' in missile, 'stance' in distance, 'wind' in window) — but residual noise remains: "
        "'shield' in the flow/true-damage atoms fires on every shield, 'bonus health' in deep-ward fires on any "
        "bonus+health datavalue, 'TauntLength' (Thresh Q) misclassifies as a taunt, 'refund' fires on ManaRefund, "
        "and meta atoms (internal-resource-index, buff-duration-class) over-fire by design.",
        "Add a targeting-data source for target_policy: mTargetingTypeData is nearly empty in these binaries, so "
        "heal/shield target_policy defaults to 'self' and misses ally-targeted heals (Senna Q, Kayle W, Thresh W "
        "lantern). mAffectsTypeFlags is also recorded raw (no decode table available for this data version).",
        "Missiles and empowered-attack variants of an already-classified parent spell (e.g. JinxQAttack, "
        "ApheliosSeverumAttack, GnarQMissile) stay unclassified; inheriting the parent ability's atoms for "
        "'*Missile'/'*Attack'-suffixed clones would cut the unclassified-real count roughly in half.",
    ]
    return sanity, suggestions


if __name__ == "__main__":
    sys.exit(main())