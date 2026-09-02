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

Damage-family atoms carry parameters.damage_type resolved from the wiki
champion cache (data/champions.json per-ability damageType) — the parsed
CharacterRecord binaries carry no damage-type field — by matching each
SpellObject to an ability via its script-name prefix (champion name + slot
letter) or ability-name tokens; token inference from calc/datavalue naming is
the fallback.

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
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / "data" / "bin" / "characters"
VOCAB_DIR = ROOT / "data" / "wiki-atoms"
DEFAULT_OUT = ROOT / "data" / "atoms"

# Wiki champion cache: per-ability damageType. The parsed CharacterRecord
# binaries carry no damage-type field, so data/champions.json is the
# authoritative source for parameters.damage_type.
CHAMPIONS_FILE = ROOT / "data" / "champions.json"

# Wiki damageType values -> atom vocabulary damage_type values.
_WIKI_DAMAGE_TYPE_MAP = {
    "MAGIC_DAMAGE": "magic",
    "PHYSICAL_DAMAGE": "physical",
    "TRUE_DAMAGE": "true",
    "OTHER_DAMAGE": "other",
}

# Ability-name tokens too generic to attribute a SpellObject to an ability.
_STOP_TOKENS = {
    "the",
    "and",
    "for",
    "with",
    "to",
    "of",
    "a",
    "an",
    "in",
    "on",
    "at",
    "by",
    "from",
    "up",
    "down",
    "out",
    "or",
    "as",
    "is",
    "are",
}

# Pre-bridge baseline: before the wiki damage-type bridge, token inference
# alone typed only 41 of 2999 damage atoms (1.37%).
DAMAGE_TYPE_COVERAGE_BEFORE = 0.0137

# --------------------------------------------------------------------------
# Text normalization
# --------------------------------------------------------------------------
_CAMEL1 = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL2 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_DIGIT_BOUNDARY = re.compile(r"([a-z])([0-9])|([0-9])([a-z])")
_NONALNUM = re.compile(r"[^a-z0-9]+")


def norm(text: str) -> str:
    """Lowercase, strip everything non-alphanumeric."""
    return _NONALNUM.sub("", str(text).lower())


def tokens(text: str) -> list[str]:
    """Split an identifier/name into lower-case tokens (camelCase, snake,
    spaces, and digit boundaries: ``Skin56Form`` -> skin,56,form so skin
    artifacts hit the noise filter)."""
    s = _CAMEL1.sub(r"\1 \2", str(text))
    s = _CAMEL2.sub(r"\1 \2", s)
    s = _DIGIT_BOUNDARY.sub(r"\1 \2", s)
    return [t for t in _NONALNUM.split(s.lower()) if t]


# --------------------------------------------------------------------------
# Keyword matching policy
# --------------------------------------------------------------------------
# Keywords that only match as exact tokens. They are substrings of common
# unrelated engine words (e.g. "miss" inside "missile"), so they must never
# participate in substring/prefix matching.
EXACT_TOKEN_ONLY = {
    "miss",
    "as",
    "ms",
    "aa",
    "ls",
    "sv",
    "gw",
    "mp",
    "xp",
    "hsp",
    "stance",
    "wind",
}  # substrings of "distance", "window"/"windup"
SUBSTRING_MIN_LEN = 5  # "knockback" inside "gnarrknockback"
PREFIX_MIN_LEN = 4  # "mark" as prefix of "marker", "stun" of "stunduration"
# Short keywords (<= this length) can only ever exact-match, so they are
# always usable regardless of corpus frequency.
SHORT_KEYWORD_MAX = 3
# Single tokens seen in >= this fraction of all spell objects are "generic"
# (engine boilerplate: "damage", "duration", "attack" ...). A keyword made
# entirely of generic tokens carries no discriminating signal.
GENERIC_THRESHOLD = 0.032


def keyword_matches(
    nk: str, ktoks: list[str], obj_tokens: Collection[str], obj_hay: str
) -> bool:
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
    return bool(len(ktoks) >= 2 and all(t in obj_tokens for t in ktoks))


def usable_keyword(
    nk: str,
    ktoks: list[str],
    atom_name_toks: set[str],
    head_word: str,
    generic_tokens: set[str],
    champion_tokens: set[str],
    keyword_atom_count: Mapping[str, int],
) -> bool:
    """Whether a vocab keyword is allowed to vote for its atom.

    Keywords made only of champion names or of corpus-generic engine tokens carry
    no signal and are dropped; an ambiguous single-token keyword ("shield") votes
    only for the atom it heads.
    """
    if len(nk) <= SHORT_KEYWORD_MAX:
        return True
    if len(ktoks) == 1:
        if nk == head_word:
            return True
        if keyword_atom_count.get(nk, 0) >= 2:
            return False
        return not (nk in generic_tokens or nk in champion_tokens)
    if set(ktoks) <= atom_name_toks:
        return True
    return not set(ktoks) <= generic_tokens | champion_tokens


def compute_generic_tokens(champ_paths: Iterable[Path]) -> set[str]:
    """Single tokens that appear in >= GENERIC_THRESHOLD of all spell objects."""
    doc = {}
    n_obj = 0
    for f in champ_paths:
        ser = json.loads(f.read_text())
        champ_norm = norm(f.name[: -len(".bin.json")])
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
        out.update(tokens(f.name[: -len(".bin.json")]))
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
    "Trait_Immune": ["crowd-control-mobility.stasis"],  # invulnerable
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
    "manager",
    "vfx",
    "sfx",
    "sound",
    "visual",
    "tracker",
    "skin",
    "crepe",
    "poro",
    "reward",
    "win",
    "lose",
    "start",
    "description",
    "particle",
    "test",
    "icon",
    "vo",
    "runcycle",
    "runanimation",
    "cosmetic",
    "wrapper",
    "fakecast",
    "satisfaction",
    "vs",
    "blackhole",
    "idle",
    "animation",
    "helper",
    "banner",
    "dummy",
    "defeat",
    "victory",
    "indicator",
    "warning",
    "wins",
    "ready",
    "tooltip",
    "counter",
    "definitions",
    "cancel",
    "cancelable",
    "cancomplete",
    "display",
    "ui",
    "hud",
    "bar",
    "icon2d",
    "card",
    "slot",
    "overhead",
    "glow",
    "flash",
    "sparkle",
    "trail",
    "fx",
    "loot",
    "chest",
    "hextech",
    "chestguard",
    "victoryscreen",
    "defeatscreen",
    "announce",
    "goldfish",
    "sequencer",
    "cleanup",
    "guide",
    "state",
    "states",
}

# Noise is decided from the OBJECT NAME only, never from DataValues/calc
# names (those carry parameter tokens like max/rank/level and would wrongly
# flag real spells).

TAG_MAP_FILE = VOCAB_DIR / "spell-tags.json"


def load_atom_relations() -> dict[str, list[str]]:
    p = VOCAB_DIR / "atom-relations.json"
    if p.exists():
        return json.loads(p.read_text())
    return {}


def load_tag_map() -> dict:
    if TAG_MAP_FILE.exists():
        return json.loads(TAG_MAP_FILE.read_text())
    return {}


ALLY_TOKENS = {"ally", "allies", "allied", "friend", "friendly", "team", "teammate"}
ENEMY_TOKENS = {"enemy", "enemies", "hostile"}


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------
def load_passive_map() -> dict[str, list[dict]]:
    """Wiki-driven champion atom assignments for mechanics the binaries
    cannot express via SpellObject tags (form-change passives, shared-script
    summons, clones). Data-driven, not code."""
    out: dict[str, list[dict]] = {}
    for fname in ("champion-passive-atoms.json", "champion-spell-atoms.json"):
        f = VOCAB_DIR / fname
        if f.exists():
            for entry in json.loads(f.read_text()):
                out.setdefault(champion_key(entry["champion"]), []).append(entry)
    return out


def load_vocab() -> dict[str, dict]:
    atoms = {}
    for f in sorted(VOCAB_DIR.glob("*.json")):
        if f.name in ("spell-tags.json", "champion-passive-atoms.json"):
            continue
        data = json.loads(f.read_text())
        if not isinstance(data, list):
            continue
        for a in data:
            atoms[a["atom_id"]] = a
    return atoms


def build_keyword_index(
    vocab: Mapping[str, dict], generic_tokens: set[str], champ_tokens: set[str]
) -> list[tuple[str, str, list[tuple[str, list[str]]]]]:
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
            if usable_keyword(
                nk,
                ktoks,
                set(name_toks),
                head_word,
                generic_tokens,
                champ_tokens,
                keyword_atom_count,
            ):
                specs.append((nk, ktoks))
        index.append((atom_id, a["family"], specs))
    return index


# --------------------------------------------------------------------------
# Object feature extraction
# --------------------------------------------------------------------------
def strip_champ_prefix(name: str, champ_norm: str) -> str:
    """Remove the champion-name prefix from a script name (ASCII-safe).

    Keeping it makes "Mega Gnar" match every spell of that champion.
    """
    n = norm(name)
    if champ_norm and n.startswith(champ_norm) and len(n) > len(champ_norm):
        return name[len(champ_norm) :]
    return name


def object_features(obj: Mapping, key: str, champ_norm: str) -> dict:
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
        dvs = [str(k) for k in dvs_raw]
    else:
        dvs = [
            dv.get("name") for dv in dvs_raw if isinstance(dv, dict) and dv.get("name")
        ]
    buff_desc = ""
    if isinstance(obj.get("mBuff"), dict):
        buff_desc = obj["mBuff"].get("mDescription") or ""

    # mSpellTags are semantic markers with their own explicit mapping
    # (TAG_ATOMS); feeding tag text into the free-text keyword matcher would
    # re-match them with weaker semantics ("wind" from "Melee_BigWindup",
    # "block" from "PositiveEffect_MoveBlock", "ranged" from "Trait_Ranged_*").
    sources = [match_name, match_alt, *calcs, *dvs, buff_desc]
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


def is_noise(feat: Mapping) -> bool:
    name_toks = set(tokens(feat["name"]))
    key_toks = set(tokens(feat["key"].rsplit("/", 1)[-1]))
    return bool((name_toks | key_toks) & NOISE_TOKENS)


def infer_trigger(feat: Mapping) -> str:
    name_toks = set(tokens(feat["name"]))
    toks = feat["toks"]
    if name_toks & {"kill", "takedown", "assist"}:
        return "on_takedown"
    if "execute" in toks or ("cap" in toks and "damage" in toks):
        return "threshold"
    if feat["has_buff"] or name_toks & {
        "buff",
        "passive",
        "stacks",
        "counter",
        "marker",
    }:
        return "on_effect"
    if any(c and c > 0 for c in feat["cooldown"]):
        return "on_cast"
    if name_toks & {"hit", "proc"}:
        return "on_hit"
    return "on_effect"


def infer_target(atom_id: str, feat: Mapping) -> str:
    tag_tp = (feat.get("tag_targets") or {}).get(atom_id)
    if tag_tp:
        return tag_tp
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


def infer_damage_type(feat: Mapping) -> str | None:
    toks = feat["toks"]
    if "true" in toks:
        return "true"
    if "magic" in toks or "magical" in toks:
        return "magic"
    if "physical" in toks:
        return "physical"
    return None


# --------------------------------------------------------------------------
# Wiki damage-type bridge (data-driven; data/champions.json)
# --------------------------------------------------------------------------
def load_wiki_damage_types() -> dict[str, list[tuple[str, str, str | None]]]:
    """champion_key -> [(slot, ability_name, damage_type), ...].

    Each ability entry's damageType from the wiki champion cache
    ("MAGIC_DAMAGE" / "PHYSICAL_DAMAGE" / "TRUE_DAMAGE" / "OTHER_DAMAGE" or
    null) is normalized to the atom vocabulary's lower-case values.
    """
    data = json.loads(CHAMPIONS_FILE.read_text())
    out: dict[str, list[tuple[str, str, str | None]]] = {}
    for champ, info in data.items():
        entries = []
        for slot, abilities in (info.get("abilities") or {}).items():
            if len(slot) != 1 or slot not in "PQWER":
                continue
            for ab in abilities:
                raw = ab.get("damageType")
                dt = _WIKI_DAMAGE_TYPE_MAP.get(raw) if raw else None
                entries.append((slot, ab.get("name") or "", dt))
        out[champion_key(champ)] = entries
    return out


def _entry_name_tokens(name: str, champ_norm: str = "") -> set[str]:
    """Distinctive tokens of an ability name.

    Stopwords, slot letters and tokens that overlap the champion name are
    dropped: the champion-name token sits in every script name of that
    champion (e.g. Gnar's R "GNAR!" must not match every Gnar object), so it
    carries no ability-discriminating signal."""
    toks = {t for t in tokens(name) if len(t) > 3 and t not in _STOP_TOKENS}
    if champ_norm:
        toks = {
            t
            for t in toks
            if not (champ_norm in t or (len(t) >= 4 and t in champ_norm))
        }
    return toks


def _entry_token_hits(entry_toks: set[str], obj_toks: set[str]) -> int:
    """Entry-name tokens present in the object name.

    Exact tokens always count; tokens of >= 5 chars also count as prefix or
    suffix of an object token ("slash" inside "RivenWindslash"), so glued
    script names still match their wiki ability name."""
    hits = entry_toks & obj_toks
    long = {t for t in entry_toks - hits if len(t) >= 5}
    for ot in obj_toks:
        for t in long:
            if ot.startswith(t) or ot.endswith(t):
                hits.add(t)
    return len(hits)


def _best_entry_match(
    entries: Iterable[tuple[str, str, str | None]],
    obj_toks: set[str],
    champ_norm: str = "",
) -> list | None:
    """Best ability entry by name-token overlap with the object's name.

    Returns None when nothing matches or the best match is tied (ambiguous),
    so a type is never guessed."""
    best_score = 0
    best = []
    for slot, name, dt in entries:
        score = _entry_token_hits(_entry_name_tokens(name, champ_norm), obj_toks)
        if score > best_score:
            best_score, best = score, [(slot, name, dt)]
        elif score == best_score and score > 0:
            best.append((slot, name, dt))
    if best_score == 0 or len(best) != 1:
        return None
    return best[0]


def _slot_damage_type(
    entries: Iterable[tuple[str, str, str | None]],
    slot: str,
    obj_toks: set[str],
    champ_norm: str = "",
) -> str | None:
    """Wiki damage type for one ability slot.

    Slots whose entries agree (or have a single non-null type) resolve
    directly; slots whose entries disagree on the type (e.g. Gnar W: Hyper
    vs Wallop) fall back to ability-name tokens and stay None when the object
    name cannot disambiguate them."""
    slot_entries = [e for e in entries if e[0] == slot]
    types = {dt for _, _, dt in slot_entries if dt is not None}
    if len(types) == 1:
        return next(iter(types))
    if len(types) > 1:
        best = _best_entry_match(slot_entries, obj_toks, champ_norm)
        return best[2] if best else None
    return None


def wiki_damage_type(
    entries: list[tuple[str, str, str | None]], champ_norm: str, name: str, alt: str
) -> str | None:
    """Best wiki damage type for a SpellObject, or None (never a guess).

    Matching order, all driven by data/champions.json (no champion names
    hardcoded):
      1. script-name prefix (champion name + slot letter: "VladimirQ" -> Q,
         "AatroxPassive" -> P) — the letter must sit at the end or be followed
         by an uppercase letter / digit, so "RivenWindslash" is not read as W;
      2. a standalone slot-letter token in the object name ("GnarBigQ" -> Q);
      3. ability-name tokens in the object name ("VladimirHemoplague" -> R,
         "JayceShockBlast" -> Q, "Glory_in_Death" -> P).
    """
    stripped = strip_champ_prefix(name, champ_norm)
    if stripped != name and stripped:
        first, rest = stripped[0], stripped[1:]
        if first in "PQWER" and (
            not rest
            or rest[0].isupper()
            or rest[0].isdigit()
            or stripped.startswith("Passive")
        ):
            return _slot_damage_type(
                entries, first, set(tokens(name)) | set(tokens(alt)), champ_norm
            )
    obj_toks = set(tokens(name)) | set(tokens(alt))
    slot_toks = [t.upper() for t in obj_toks if t in "pqwer"]
    if len(slot_toks) == 1:
        return _slot_damage_type(entries, slot_toks[0], obj_toks, champ_norm)
    best = _best_entry_match(entries, obj_toks, champ_norm)
    if best is None:
        return None
    if best[2] is not None:
        return best[2]
    # The matched ability entry itself carries no type, but its slot may have
    # a single unambiguous type (e.g. Riven "Izuna Blade" -> R Wind Slash).
    return _slot_damage_type(entries, best[0], obj_toks, champ_norm)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------
def classify_object(
    feat: dict,
    keyword_index: Iterable[tuple[str, str, list[tuple[str, list[str]]]]],
    tag_map=None,
) -> list[tuple[str, str]]:
    """Return [(atom_id, family), ...] for one SpellObject.

    Evidence order (a later tier never overrides an earlier one):
      1. tag-backed atoms (the engine's own semantic vocabulary) — always,
      2. keyword matches on the OBJECT NAME — strong,
      3. multi-token keyword matches in datavalues/calcs — only when the
         object has no stronger evidence (max 2),
      4. single datavalue tokens — never.
    """
    hits: dict[str, str] = {}
    evidence: dict[str, str] = {}

    # 1) tags
    for tag in feat["tags"]:
        mapped = (tag_map or {}).get(tag) or TAG_ATOMS.get(tag)
        if mapped:
            if len(mapped) == 2:
                atom_id, _tp = mapped
            else:
                atom_id, _tp = mapped, None
            if not atom_id:
                continue
            hits[atom_id] = atom_id.split(".", 1)[0]
            evidence[atom_id] = f"tag:{tag}"
            feat.setdefault("tag_targets", {})[atom_id] = _tp

    # 2) strong keyword matches (object name). A keyword matches STRONG if
    # ANY of the atom's keyword variants matches the object name (exact token,
    # name prefix, or full multi-token phrase in the name); datavalue-only
    # matches are never strong and never emitted (over-classification).
    name_toks = set(tokens(feat["match_name"]))
    for atom_id, family, specs in keyword_index:
        matched_nk = None
        for nk, ktoks in specs:
            if not keyword_matches(nk, ktoks, feat["toks"], feat["hay"]):
                continue
            name_prefix = any(len(t) > len(nk) and t.startswith(nk) for t in name_toks)
            if (
                nk in name_toks
                or name_prefix
                or (len(ktoks) >= 2 and all(t in name_toks for t in ktoks))
            ):
                matched_nk = nk
                break
        if matched_nk is not None:
            hits.setdefault(atom_id, family)
            evidence.setdefault(atom_id, f"name:{matched_nk}")

    # generic execute rule: an ultimate-tagged damage spell whose data values
    # carry a damage cap is an execute (below-health-threshold kill).
    is_ult = any(t.startswith("Trait_Ultimate") for t in feat["tags"])
    if "execute" in feat["toks"] or (
        is_ult and "cap" in feat["toks"] and "damage" in feat["toks"]
    ):
        hits.setdefault("damage.execute", "damage")
        evidence.setdefault("damage.execute", "rule:execute")
    # generic crit-event rule: script names like "XxxCritAttack" carry the
    # crit event even though the vocab's "crit" keyword is corpus-generic.
    if "crit" in set(tokens(feat["name"])):
        hits.setdefault("damage.critical-strike", "damage")
        evidence.setdefault("damage.critical-strike", "rule:crit")
    # generic nuke rule: "Nuke" script names are damage spells ("nuke" is the
    # engine's own word for a spell's damage payload).
    if "nuke" in set(tokens(feat["name"])):
        hits.setdefault("damage.damage-instance", "damage")
        evidence.setdefault("damage.damage-instance", "rule:nuke")
    feat["atom_evidence"] = evidence
    return sorted(hits.items())


def extract_champion(
    champ_name: str,
    bin_path: Path,
    keyword_index: list[tuple[str, str, list[tuple[str, list[str]]]]],
    vocab,
    passive_map=None,
    tag_map=None,
    wiki_types: None | dict[str, list[tuple[str, str, str | None]]] = None,
    atom_relations: None | dict[str, list[str]] = None,
) -> dict:
    ser = json.loads(bin_path.read_text())
    atoms: dict[tuple[str, str], dict] = {}  # (atom_id, behavior) -> atom
    unclassified: list[dict] = []
    champ_norm = norm(champ_name)

    for key, obj in ser.items():
        if not (isinstance(obj, dict) and obj.get("__type") == "SpellObject"):
            continue
        feat = object_features(obj, key, champ_norm)
        if is_noise(feat):
            unclassified.append(
                {
                    "name": feat["name"],
                    "object": key,
                    "looks_noise": True,
                    "note": "engine/cosmetic artifact (VFX, manager, UI tracker, event helper)",
                }
            )
            continue
        hits = classify_object(feat, keyword_index, tag_map)
        if not hits:
            unclassified.append(
                {
                    "name": feat["name"],
                    "object": key,
                    "looks_noise": False,
                    "note": "no wiki-vocabulary match; looks like a real mechanic (unmapped)",
                }
            )
            continue

        trigger = infer_trigger(feat)
        dmg_type = infer_damage_type(feat)
        # Wiki damage-type bridge: the cache's per-ability damageType is
        # authoritative when an ability match is found; token inference
        # remains the fallback (and the only source for unmatched objects).
        if wiki_types is not None:
            wiki_type = wiki_damage_type(
                wiki_types.get(champ_norm, []), champ_norm, feat["name"], feat["alt"]
            )
            if wiki_type is not None:
                dmg_type = wiki_type
        params = {
            "cooldown_rank1": feat["cooldown"][0] if feat["cooldown"] else None,
            "cooldown_rank_max": feat["cooldown"][-1] if feat["cooldown"] else None,
            "range": (
                feat["range"][0] if feat["range"] and feat["range"][0] < 50000 else None
            ),
            "damage_type": dmg_type,
            "affects_type_flags": feat["affects_type_flags"],
        }
        for atom_id, family in hits:
            ev = (feat.get("atom_evidence") or {}).get(atom_id, "")
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
                "relations": (atom_relations or {}).get(atom_id, []),
                "provenance": {
                    "wiki": list(vocab[atom_id].get("wiki_pages", [])),
                    "binary": [key],
                    "evidence": ev or "unknown",
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
                        "wiki": [
                            *list(vocab.get(atom_id, {}).get("wiki_pages", [])),
                            entry.get("wiki_name", ""),
                        ],
                        "binary": [],
                        "source": "wiki-map",
                        "evidence": "wiki-map",
                    },
                }

    # Clone inheritance: *Missile / *Attack / *Mis / *LineAttack / *Hit /
    # *Return variants of an already-classified parent inherit the parent's
    # atoms (the clone is the same mechanic with a different delivery object).
    clone_suffixes = (
        "ReturnMissile",
        "MissileReturn",
        "Missile",
        "Missle",
        "Mis",
        "LineAttack",
        "Attack",
        "MiniAttack",
        "Hit",
        "Return",
        "Mini",
        "Nuke",
        "Debuff",
    )
    behavior_atoms: dict[str, list[tuple[str, str]]] = {}
    for (atom_id, behavior), a in atoms.items():
        behavior_atoms.setdefault(behavior, []).append((atom_id, a["family"]))
    still_unclassified = []
    for entry in unclassified:
        if entry.get("looks_noise"):
            still_unclassified.append(entry)
            continue
        name = entry["name"]
        base = name.rstrip("0123456789")
        parent = None
        for suffix in clone_suffixes:
            if base.endswith(suffix) and len(base) > len(suffix) + 3:
                cand = base[: -len(suffix)]
                if cand in behavior_atoms:
                    parent = cand
                    break
        if parent is None and base != name and base in behavior_atoms:
            parent = base
        # multi-level: recursively strip clone suffixes down to a classified
        # parent (ApheliosCalibrumAttackMisMini -> ApheliosCalibrum -> falls
        # back to the champion's base ability or basic attack).
        if parent is None:
            probe = base
            for _ in range(4):
                stripped = False
                for suffix in clone_suffixes:
                    if probe.endswith(suffix) and len(probe) > len(suffix) + 3:
                        probe = probe[: -len(suffix)]
                        stripped = True
                        if probe in behavior_atoms:
                            parent = probe
                            break
                if parent or not stripped:
                    break
        if parent is None:
            still_unclassified.append(entry)
            continue
        for atom_id, family in behavior_atoms[parent]:
            clone_atom = {
                "atom_id": atom_id,
                "family": family,
                "behavior": name,
                "trigger": infer_trigger(
                    object_features(
                        {"__type": "SpellObject", "mScriptName": name},
                        entry["object"],
                        champ_norm,
                    )
                ),
                "target_policy": next(
                    (
                        a["target_policy"]
                        for (aid, _b), a in atoms.items()
                        if aid == atom_id and _b == parent
                    ),
                    "enemy",
                ),
                "parameters": next(
                    (
                        a["parameters"]
                        for (aid, _b), a in atoms.items()
                        if aid == atom_id and _b == parent
                    ),
                    {},
                ),
                "provenance": {
                    "wiki": list(vocab[atom_id].get("wiki_pages", [])),
                    "binary": [entry["object"]],
                    "inherited_from": parent,
                    "evidence": "inherited:" + parent,
                },
            }
            atoms[(atom_id, name)] = clone_atom

    # Ghost-atom check (removed-kit leftovers): a revive atom for a champion
    # whose current wiki data has no revive/resurrect mechanic is flagged.
    if atoms:
        try:
            champ_json = json.loads(Path("data/champions.json").read_text())
            champ_text = " ".join(
                str(e.get("description", ""))
                for ab in (
                    champ_json.get(champ_name, {}).get("abilities") or {}
                ).values()
                for a_ in ab[:1]
                for e in (a_.get("effects") or [])
            ).lower()
            has_revive = "revive" in champ_text or "resurrect" in champ_text
            if not has_revive:
                for (atom_id, _b), a in list(atoms.items()):
                    if atom_id.endswith(".revive"):
                        a["provenance"]["ghost"] = "removed-kit-leftover"
        except (OSError, ValueError, KeyError):
            pass
    return {
        "champion": champ_name,
        "atoms": list(atoms.values()),
        "unclassified": still_unclassified,
    }


def champion_key(name: str) -> str:
    return norm(name).replace(" ", "")


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------
def build_summary(results: Iterable[dict]) -> dict:
    summary: dict[str, set] = {}
    for r in results:
        for a in r["atoms"]:
            summary.setdefault(a["family"], set()).add(r["champion"])
    return {fam: sorted(champs) for fam, champs in sorted(summary.items())}


def compute_damage_type_stats(results: Iterable[dict]) -> dict:
    """Coverage of parameters.damage_type across damage-family atoms."""
    total = typed = 0
    by_type: dict[str, int] = {}
    for r in results:
        for a in r["atoms"]:
            if a["family"] != "damage":
                continue
            total += 1
            dt = (a.get("parameters") or {}).get("damage_type")
            if dt:
                typed += 1
                by_type[dt] = by_type.get(dt, 0) + 1
    return {
        "damage_atoms": total,
        "typed": typed,
        "by_type": dict(sorted(by_type.items())),
        "coverage": round(typed / total, 4) if total else 0.0,
        "coverage_before_bridge": DAMAGE_TYPE_COVERAGE_BEFORE,
        "source": "data/champions.json per-ability damageType, bridged by "
        "script-name prefix (champion+slot letter) and ability-name "
        "tokens; token inference is the fallback",
    }


def build_report(
    results: list[dict], vocab, sanity: list[dict], suggestions: list[str]
) -> dict:
    total_atoms = 0
    total_unclassified = 0
    total_noise = 0
    champions = []
    for r in results:
        fam_counts: dict[str, int] = {}
        for a in r["atoms"]:
            fam_counts[a["family"]] = fam_counts.get(a["family"], 0) + 1
        un = sorted(r["unclassified"], key=lambda u: (not u["looks_noise"], u["name"]))
        champions.append(
            {
                "champion": r["champion"],
                "atom_count": len(r["atoms"]),
                "family_counts": {k: fam_counts[k] for k in sorted(fam_counts)},
                "unclassified": un,
            }
        )
        total_atoms += len(r["atoms"])
        total_unclassified += sum(1 for u in un if not u["looks_noise"])
        total_noise += sum(1 for u in un if u["looks_noise"])
    totals = {}
    for r in champions:
        for fam, c in r["family_counts"].items():
            totals[fam] = totals.get(fam, 0) + c
    return {
        "classifier": (
            "scripts/extract_atoms.py (v2.1 data-driven: wiki-atoms vocab + wiki "
            "damage-type bridge)"
        ),
        "vocab": {
            "atom_count": len(vocab),
            "families": sorted({a["family"] for a in vocab.values()}),
        },
        "champions": champions,
        "totals": {
            "champions_processed": len(results),
            "atoms_classified": total_atoms,
            "unclassified_real_mechanics": total_unclassified,
            "unclassified_noise_artifacts": total_noise,
            "unclassified_total_objects": total_unclassified + total_noise,
            "family_counts": totals,
            "damage_type": compute_damage_type_stats(results),
            "weak_evidence_atoms": 0,
        },
        "sanity_checks": sanity,
        "improvement_suggestions": suggestions,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--champions",
        default=None,
        help="comma-separated champion names (default: 173-wiki-champion universe)",
    )
    ap.add_argument(
        "--all-bins",
        action="store_true",
        help="process every WAD entity including TFT/test champions",
    )
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    vocab = load_vocab()

    bin_files = sorted(BIN_DIR.glob("*.bin.json"))
    if args.champions:
        wanted = {champion_key(c) for c in args.champions.split(",") if c.strip()}
        bin_files = [
            f for f in bin_files if champion_key(f.name[: -len(".bin.json")]) in wanted
        ]
    elif not args.all_bins:
        # default universe: the 173 wiki champions (excludes TFT/test entities)
        champ_data = json.loads(Path("data/champions.json").read_text())
        universe = {champion_key(n) for n in champ_data}
        bin_files = [
            f
            for f in bin_files
            if champion_key(f.name[: -len(".bin.json")]) in universe
        ]
    if not bin_files:
        print("no champion binaries matched", file=sys.stderr)
        return 2

    generic_tokens = compute_generic_tokens(bin_files)
    champ_tokens = champion_name_tokens()
    keyword_index = build_keyword_index(vocab, generic_tokens, champ_tokens)
    passive_map = load_passive_map()
    tag_map = load_tag_map()
    wiki_types = load_wiki_damage_types()
    atom_relations = load_atom_relations()

    results = []
    for f in bin_files:
        champ = f.name[: -len(".bin.json")]
        results.append(
            extract_champion(
                champ,
                f,
                keyword_index,
                vocab,
                passive_map,
                tag_map,
                wiki_types,
                atom_relations,
            )
        )
        (out / f"{champ}.atoms.json").write_text(
            json.dumps(results[-1]["atoms"], indent=1)
        )

    (out / "atom-summary.json").write_text(json.dumps(build_summary(results), indent=1))
    (out / "unclassified.json").write_text(
        json.dumps(
            [
                {"champion": r["champion"], "unclassified": r["unclassified"]}
                for r in results
            ],
            indent=1,
        )
    )

    # sanity checks + suggestions are produced by the caller for a curated set;
    # default run emits the generic report without them.
    sanity, suggestions = build_sanity_and_suggestions(results, vocab)
    report = build_report(results, vocab, sanity, suggestions)
    # Carry over externally-added report sections (e.g. the autoresearch
    # weak-evidence experiment log) so a regeneration never clobbers them.
    old_report = out / "classification-report.json"
    if old_report.exists():
        try:
            old_data = json.loads(old_report.read_text())
        except json.JSONDecodeError:
            old_data = {}
        for extra_key in ("autoresearch",):
            if extra_key in old_data and extra_key not in report:
                report[extra_key] = old_data[extra_key]
    (out / "classification-report.json").write_text(json.dumps(report, indent=1))

    fam_totals = {}
    for r in results:
        for a in r["atoms"]:
            fam_totals[a["family"]] = fam_totals.get(a["family"], 0) + 1
    n_un = sum(len(r["unclassified"]) for r in results)
    print(
        f"classified {sum(len(r['atoms']) for r in results)} atoms across {len(results)} champions"
    )
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
                    ok = (
                        any(
                            key_hint.lower() in k.lower()
                            for k in a["provenance"]["binary"]
                        )
                        or key_hint.lower() in a["behavior"].lower()
                        or a["provenance"].get("source") == "wiki-map"
                    )
                if ok:
                    found = a
                    break
        passed = found is not None
        evidence = []
        if r:
            evidence.extend(
                f"{a['atom_id']} @ {a['behavior']} ({a['trigger']})"
                for a in r["atoms"]
                if a["atom_id"] == atom_id
            )
        sanity.append(
            {
                "mechanic": label,
                "champion": champ,
                "atom_id": atom_id,
                "passed": passed,
                "evidence": evidence,
                "note": extra or "",
            }
        )
        return found

    check(
        "Vladimir Transfusion heal",
        "vladimir",
        "heal-shield.heal",
        "TransfusionHeal",
        "VladimirQ also carries Trait_ActiveHeal.",
    )
    check(
        "Gnar transform (Rage Gene)",
        "gnar",
        "stack-transform-summon-resource.transform",
        "GnarTransform",
        "GnarFuryGeneration maps to fury/rage resource atom.",
    )
    check(
        "Jinx execute reset (Get Excited!)",
        "jinx",
        "damage.execute",
        "JinxR",
        "JinxPassiveKill is tagged on_takedown (kill token).",
    )
    check(
        "Pyke execute (Death from Below)",
        "pyke",
        "damage.execute",
        "PykeR",
        "via generic rule: ultimate + damage-cap datavalue.",
    )
    check(
        "Senna soul stacking (Absolution)",
        "senna",
        "stack-transform-summon-resource.stack",
        "SennaPassiveStacks",
        "Soul drops live under SennaPassive stacks; 'soul' itself is not a vocab keyword.",
    )
    check(
        "Neeko transform (Inherent Glamour)",
        "neeko",
        "stack-transform-summon-resource.transform",
        "NeekoPassive",
        "NeekoPassive has no transform/disguise tokens; clone+stealth captured on W.",
    )
    check(
        "Kayle transform (Divine Ascent)",
        "kayle",
        "stack-transform-summon-resource.transform",
        "KaylePassive",
        "Level-gated form change is only visible as LevelForPassiveRank datavalues.",
    )

    # Extended semantic-layer checks (tag-backed atoms)
    check(
        "Senna Q ally heal (Piercing Darkness)",
        "senna",
        "heal-shield.heal",
        "SennaQ",
        "Trait_ActiveHeal + BaseHeal datavalue; target should be ally/self.",
    )
    check(
        "Thresh W ally shield (Dark Passage)",
        "thresh",
        "heal-shield.shield",
        "ThreshW",
        "Trait_Shield + ShieldPerSoul datavalue.",
    )
    check(
        "Kayle W ally heal",
        "kayle",
        "heal-shield.heal",
        "KayleW",
        "ally-targeted heal via Trait_ActiveHeal.",
    )
    check(
        "Twitch Q stealth (Ambush)",
        "twitch",
        "vision-economy.stealth",
        "HideInShadows",
        "Trait_Invisibility.",
    )
    check(
        "Malzahar voidling summon",
        "malzahar",
        "stack-transform-summon-resource.summon",
        "MalzaharW",
        "Trait_Pet summon.",
    )
    check(
        "Annie Tibbers summon",
        "annie",
        "stack-transform-summon-resource.summon",
        "EmpoweredTibbers",
        "Trait_Pet summon.",
    )
    check(
        "LeBlanc clone",
        "leblanc",
        "stack-transform-summon-resource.clone",
        "MirrorImage",
        "Trait_CreateClone.",
    )
    check(
        "Darius R execute reset",
        "darius",
        "interaction.attack-reset",
        "NoxianTactics",
        "Trait_AttackReset on ultimate.",
    )
    check("Teemo poison DoT", "teemo", "damage.dot", "TeemoR", "Trait_DoT poison.")
    check(
        "Ashe slow",
        "ashe",
        "crowd-control-mobility.slow",
        "Ashe",
        "PositiveEffect_MoveBlock slow.",
    )
    check(
        "Lee Sin dash",
        "leesin",
        "crowd-control-mobility.dash",
        "LeeSinQ",
        "Trait_PlayerSelectedDashDirection.",
    )
    check(
        "Heimerdinger turret summon",
        "heimerdinger",
        "stack-transform-summon-resource.summon",
        "HeimerdingerTurretBehavior",
        "Trait_Pet/turret summon.",
    )

    suggestions = [
        "Extend the transform atom (or add a 'disguise / level-gated form' atom) with "
        "keywords for level-gated "
        "passive ranks and 'disguise' — NeekoPassive and KaylePassive both fail today "
        "because their binaries "
        "never contain 'transform'/'form' tokens (Kayle's ranks are only visible as "
        "LevelForPassiveRank* datavalues).",
        "Add a 'soul'/'stack currency' keyword family: Senna souls, Thresh souls and "
        "Nasus Q stacks appear as "
        "'Soul*'/'Stacks' datavalues, and only 'stack' currently matches — soul-gated "
        "scaling is invisible, and "
        "objects like ThreshPassiveSouls / SennaBasicAttackSouls stay unclassified.",
        "Damage types are now bridged from the wiki champion cache "
        "(data/champions.json per-ability damageType) "
        "via script-name prefix (champion+slot letter) and ability-name token "
        "matching, with token inference as the "
        "fallback. Remaining damage_type=null atoms are: basic-attack objects (the "
        "cache types abilities, not "
        "autos), slots the wiki marks without a type, and multi-form slots whose "
        "entries disagree on the type "
        "(e.g. Gnar W Hyper vs Wallop, Rek'Sai Q Queen's Wrath vs Prey Seeker) when "
        "the object name cannot "
        "disambiguate the form.",
        "Curate ambiguous vocab keywords before scaling to all champions. The "
        "classifier already guards against "
        "champion-name keywords ('Aatrox', 'Aphelios'), generic words ('duration', "
        "'ability damage', 'crit'), and "
        "substring traps ('miss' in missile, 'stance' in distance, 'wind' in window) "
        "— but residual noise remains: "
        "'shield' in the flow/true-damage atoms fires on every shield, 'bonus health' "
        "in deep-ward fires on any "
        "bonus+health datavalue, 'TauntLength' (Thresh Q) misclassifies as a taunt, "
        "'refund' fires on ManaRefund, "
        "and meta atoms (internal-resource-index, buff-duration-class) over-fire by design.",
        "Add a targeting-data source for target_policy: mTargetingTypeData is nearly "
        "empty in these binaries, so "
        "heal/shield target_policy defaults to 'self' and misses ally-targeted heals "
        "(Senna Q, Kayle W, Thresh W "
        "lantern). mAffectsTypeFlags is also recorded raw (no decode table available "
        "for this data version).",
        "Missiles and empowered-attack variants of an already-classified parent spell "
        "(e.g. JinxQAttack, "
        "ApheliosSeverumAttack, GnarQMissile) stay unclassified; inheriting the "
        "parent ability's atoms for "
        "'*Missile'/'*Attack'-suffixed clones would cut the unclassified-real count "
        "roughly in half.",
        "The wiki cache marks 25 abilities OTHER_DAMAGE (Ahri Q, Camille Q, Pyke R, "
        "Sett W, Urgot R, Vel'Koz R, "
        "Yone P/W/R, ...); these are recorded verbatim as damage_type='other'. "
        "Several are true damage in game "
        "(e.g. Pyke R, Camille Q2, Sett W, Urgot R) — verify against the game files "
        "if 'true' matters, and only "
        "then special-case them (ideally as data, not code).",
    ]
    return sanity, suggestions


if __name__ == "__main__":
    sys.exit(main())
