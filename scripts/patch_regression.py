"""Patch-day staleness gate: wiki cache vs game-file ground truth.

Every two weeks a LoL patch lands and the wiki cache (``data/champions.json``,
``data/items.json``) silently drifts from the shipped game.  This script is
the DAY-ZERO detector: it compares the cached values against the game files
for the current patch and writes ``data/staleness.json``.

Extraction method
-----------------
- Live patch is resolved with the CommunityDragon Toolbox CLI
  (``cdtb versions game -a``) — the same tool the wiki pipeline uses.
- Ground truth is the game files themselves as exported by cdtb's own
  converter (``BinConverter``, the exact format ``cdtb export`` produces and
  raw.communitydragon.org serves):

  * champions: ``game/data/characters/<name>/<name>.bin.json`` — the
    ``CharacterRecords/Root`` per-champion WAD bin.  Downloading the raw
    per-champion WADs themselves is not patch-day feasible (174 WADs,
    ~16 GB uncompressed); the cdtb raw export is the same bytes through the
    same converter, and it is the precedent this repo already trusts
    (gnar.py: "verify ... against the GAME FILES — Community Dragon
    gnarbig.bin.json CharacterRecords").
  * items: ``game/items.cdtb.bin.json`` — cdtb's merged export of the game
    items bin (``ItemData`` entries carry the raw stat mods).
- ``--verify-wads`` spot-checks the equivalence claim: it downloads the real
  champion WAD(s) via the cdtb Python API (wad-env interpreter), extracts the
  champion bin, bin-dumps it, and compares the CharacterRecord stats against
  the raw export.

Comparison contract
-------------------
- Champion stats map by CharacterRecord field (``baseHPModifiable``,
  ``hpPerLevelModifiable``, ``baseStaticHPRegenModifiable`` (x5 = HP5),
  ``baseDamageModifiable``, ... and the hashed ``AbilityResourceSlotInfo``
  fields for mana/mana regen).  Mana-family stats are only compared for
  MANA/ENERGY resources (``arType`` 0/1); anything else is "unchecked".
- Item stats map by ``ItemData`` mod field (``mFlatHPPoolMod``,
  ``mPercentAttackSpeedMod`` (x100), ``PercentOmnivampMod``, ...).  A cache
  stat whose game field is absent is "unchecked", never stale.
- Tolerances: a drift inside 0.5% or +-2 flat is rounding noise, not stale;
  ability rows use the same 0.5% with a +-0.5 flat carve-out (values are
  exact in both sources; the tighter carve-out only absorbs float noise).
- Ability-leveling comparison is BEST-EFFORT: cooldown/cost rows map to the
  spell's ``cooldownTime``/``mana`` arrays; damage/scaling rows map to named
  ``DataValues`` rows by value (any rank slice) and are only ever "stale"
  when the wiki attribute name matches a game row name but the numbers do
  not.  Rows that cannot be mapped are recorded as unchecked — never claimed
  checked, never claimed stale.

Exit code: 0 = nothing stale; 1 = any stale champion or item (patch gate).

cdtb resolution, in order: the ``CDTB_BIN`` env var, else the
``cdtb`` executable on PATH, else an actionable error.  When cdtb is
unavailable, pin the comparison with ``--patch <version>`` — the gate then
uses the pinned patch instead of resolving the live one.

Usage:
    python scripts/patch_regression.py check [--patch 16.15] [--cache-dir DIR]
                                             [--out FILE]
    python scripts/patch_regression.py check --verify-wads Ahri,Gnar

Configuration:
    CDTB_BIN       path to the cdtb CLI (default: cdtb on PATH)
    CDTB_PYTHON    interpreter with the cdtb module for --verify-wads
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_GAME_DIR = DEFAULT_DATA_DIR / "gamefiles"
DEFAULT_OUT = DEFAULT_DATA_DIR / "staleness.json"

# cdtb CLI (CommunityDragonToolbox).  Resolvable via CDTB_BIN or PATH, with no
# developer-home fallback: on any other machine the missing binary is an
# actionable error, not a silent crash or a wrong-machine tool.
CDTB_BIN = os.environ.get("CDTB_BIN") or shutil.which("cdtb") or "cdtb"
# Python interpreter that has the cdtb module (used only by --verify-wads).
CDTB_PYTHON = os.environ.get("CDTB_PYTHON") or shutil.which("python3") or "python3"

CDRAGON_RAW = "https://raw.communitydragon.org/{patch}/game/data/characters/{name}/{name}.bin.json"
ITEMS_URL = "https://raw.communitydragon.org/{patch}/game/items.cdtb.bin.json"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

REL_TOLERANCE = 0.005  # 0.5% relative drift is rounding noise
FLAT_TOLERANCE = 2.0  # +-2 flat drift is rounding noise (stats)
ABILITY_FLAT_TOLERANCE = 0.5  # damage rows are exact; absorb float noise only
COOLDOWN_FLAT_TOLERANCE = 0.25  # cooldowns move in 0.5s steps; 0.25 absorbs noise
COST_FLAT_TOLERANCE = 1.0  # costs move in whole mana; 1 absorbs rounding

# CharacterRecord fields -> wiki cache stat components.
#   (cache stat, cache component, game field, multiplier)
CHAMPION_STAT_MAP = [
    ("health", "flat", "baseHPModifiable", 1.0),
    ("health", "perLevel", "hpPerLevelModifiable", 1.0),
    ("healthRegen", "flat", "baseStaticHPRegenModifiable", 5.0),  # per-s -> HP5
    ("healthRegen", "perLevel", "hpRegenPerLevelModifiable", 5.0),
    ("attackDamage", "flat", "baseDamageModifiable", 1.0),
    ("attackDamage", "perLevel", "damagePerLevelModifiable", 1.0),
    ("armor", "flat", "baseArmorModifiable", 1.0),
    ("armor", "perLevel", "armorPerLevelModifiable", 1.0),
    ("magicResistance", "flat", "baseMR", 1.0),
    ("magicResistance", "perLevel", "{01262a25}", 1.0),  # mrPerLevel (hashed)
    ("attackSpeed", "flat", "attackSpeedModifiable", 1.0),
    ("attackSpeed", "perLevel", "attackSpeedPerLevelModifiable", 1.0),
    ("attackSpeedRatio", "flat", "attackSpeedRatioModifiable", 1.0),
    ("movespeed", "flat", "baseMoveSpeedModifiable", 1.0),
    ("attackRange", "flat", "attackRangeModifiable", 1.0),
    # acquisitionRange is deliberately NOT compared: the wiki's "Acquisition
    # Radius" is a different concept from the game field (12/173 champions
    # "drifted" 50-200 while every real stat matched), so it would only
    # manufacture noise.  attackRange covers the playable stat.
]

# AbilityResourceSlotInfo hashed fields, verified against the game files
# because the hashes are not in cdtb's public hash lists.
RESOURCE_POOL = "{726ee5cd}"  # base pool
RESOURCE_POOL_PER_LEVEL = "{6216bf7b}"
RESOURCE_REGEN = "{c4ab3550}"  # base regen, x5 for the per-5s figure
RESOURCE_REGEN_PER_LEVEL = "{3a509002}"  # regen per level, x5

# ItemData mod fields -> wiki cache stat components.  Percent fractions are
# scaled to the cache's 0-100 convention; HP regen is per-second in the bin.
ITEM_STAT_MAP = [
    ("health", "flat", "mFlatHPPoolMod", 1.0),
    ("healthRegen", "flat", "mFlatHPRegenMod", 5.0),
    ("healthRegen", "percentBase", "mPercentBaseHPRegenMod", 100.0),
    ("mana", "flat", "flatMPPoolMod", 1.0),
    ("manaRegen", "flat", "flatMPRegenMod", 1.0),
    ("manaRegen", "percentBase", "percentBaseMPRegenMod", 100.0),
    ("attackDamage", "flat", "mFlatPhysicalDamageMod", 1.0),
    ("abilityPower", "flat", "mFlatMagicDamageMod", 1.0),
    ("armor", "flat", "mFlatArmorMod", 1.0),
    ("magicResistance", "flat", "mFlatSpellBlockMod", 1.0),
    ("attackSpeed", "flat", "mPercentAttackSpeedMod", 100.0),
    ("attackSpeed", "percentBonus", "mPercentMultiplicativeAttackSpeedMod", 100.0),
    ("movespeed", "flat", "mFlatMovementSpeedMod", 1.0),
    ("movespeed", "percent", "mPercentMovementSpeedMod", 100.0),
    ("criticalStrikeChance", "percent", "mFlatCritChanceMod", 100.0),
    ("criticalStrikeDamage", "flat", "mFlatCritDamageMod", 100.0),
    ("lifesteal", "percent", "mPercentLifeStealMod", 100.0),
    ("omnivamp", "percent", "PercentOmnivampMod", 100.0),
    ("abilityHaste", "flat", "mAbilityHasteMod", 1.0),
    ("lethality", "flat", "PhysicalLethality", 1.0),
    ("armorPenetration", "flat", "mFlatArmorPenetrationMod", 1.0),
    ("armorPenetration", "percent", "mPercentArmorPenetrationMod", 100.0),
    ("magicPenetration", "flat", "mFlatMagicPenetrationMod", 1.0),
    ("magicPenetration", "percent", "mPercentMagicPenetrationMod", 100.0),
    ("tenacity", "percent", "mPercentTenacityItemMod", 100.0),
    ("healAndShieldPower", "percent", "mPercentHealingAmountMod", 100.0),
    ("cooldownReduction", "percent", "mPercentCooldownMod", 100.0),
]

_SLOT_ORDER = ("Q", "W", "E", "R")


# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------


def within_tolerance(
    cached, game, relative: float = REL_TOLERANCE, flat=FLAT_TOLERANCE
):
    """True when a drift is rounding noise (inside 0.5% or +-flat)."""
    if cached == game:
        return True
    delta = abs(game - cached)
    return delta <= flat or delta <= relative * abs(cached)


# ---------------------------------------------------------------------------
# Patch + download layer
# ---------------------------------------------------------------------------


def resolve_patch(cdtb_bin=None):
    """Return the live game patch version via `cdtb versions game -a`."""
    binary = cdtb_bin or CDTB_BIN
    if not binary or (not Path(binary).is_file() and shutil.which(binary) is None):
        raise RuntimeError(
            "cdtb not found — install it and set CDTB_BIN, or pin with "
            "--patch <version>"
        )
    # cdtb's default storage is a relative `cdn/` directory; run it inside
    # the (gitignored) game-file cache so the repo root never grows a copy.
    scratch = DEFAULT_GAME_DIR / ".cdtb"
    scratch.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [binary, "versions", "game", "-a"],
        cwd=str(scratch),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"cdtb could not resolve the live game patch ({binary}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines or not re.fullmatch(r"\d+\.\d+", lines[-1]):
        raise RuntimeError(f"unexpected cdtb output: {result.stdout!r}")
    return lines[-1]


def _download(url, dest):
    """Download one URL to dest (browser UA; raw CDN 403s default agents)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


def champion_dir(name):
    """A cache champion key as its CommunityDragon dir: lowercase alphanumeric."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def extract_ddragon_version(champions_cache):
    """Derive the Data Dragon patch from the cache's champion icon URLs.

    The cache pins icons to one CDN release (e.g. 16.15.1 for game 16.15);
    fall back to the ddragon versions API when no icon carries a version.
    """
    for entry in champions_cache.values():
        icon = (entry.get("icon") or "").replace("http://", "https://")
        match = re.search(r"cdn/([0-9]+\.[0-9]+\.[0-9]+)/img/champion/", icon)
        if match:
            return match.group(1)
    try:
        request = urllib.request.Request(
            "https://ddragon.leagueoflegends.com/api/versions.json",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            versions = json.load(response)
        if versions and re.fullmatch(r"\d+\.\d+\.\d+", versions[0]):
            return versions[0]
    except OSError:
        pass
    return None


def fetch_ddragon_for_pending(ddragon_version, pending, game_dir, concurrency: int = 8):
    """Fetch Riot's official per-spell tooltip data for champions that need
    cooldown/cost arbitration (targeted; never the whole roster)."""
    game_dir = Path(game_dir)
    ddragon_dir = game_dir / "ddragon"
    targets = []
    for name in pending:
        dest = ddragon_dir / f"{name}.json"
        url = (
            "https://ddragon.leagueoflegends.com/cdn/"
            f"{ddragon_version}/data/en_US/champion/{name}.json"
        )
        targets.append((url, dest, name))

    def fetch(target):
        url, dest, name = target
        try:
            _download(url, dest)
            with Path(dest).open(encoding="utf-8") as handle:
                payload = json.load(handle)
            return name, ddragon_rows_by_slot(payload["data"][name])
        except (OSError, KeyError, json.JSONDecodeError):
            return name, None

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return {name: row for name, row in pool.map(fetch, targets) if row is not None}


def _parse_burn(burn):
    """Parse a ddragon 'cooldownBurn'/'costBurn' string into floats."""
    if burn is None:
        return None
    values = []
    for part in str(burn).split("/"):
        try:
            values.append(float(part.strip()))
        except ValueError:
            return None
    return values


def ddragon_rows_by_slot(ddragon_champion):
    """Map ddragon spells (Q/W/E/R order) to cooldown/cost value rows."""
    by_slot = {}
    spells = ddragon_champion.get("spells") or []
    for slot, spell in zip(_SLOT_ORDER, spells, strict=False):
        cooldown = _parse_burn(spell.get("cooldownBurn"))
        cost = _parse_burn(spell.get("costBurn"))
        by_slot[slot] = {
            "cooldown": cooldown,
            "cost": cost,
        }
    return by_slot


def _expanded_match(wiki_values, dd_values, flat_tolerance: float):
    """Match wiki values against ddragon values (constants expand to rank)."""
    if not dd_values:
        return False
    if len(dd_values) == 1:
        dd_values = [dd_values[0]] * len(wiki_values)
    return _slices_match(wiki_values, dd_values, flat_tolerance)


def download_game_files(patch, game_dir, champion_names, concurrency=8):
    """Fetch the cdtb raw exports for the given champions + the items bin."""
    game_dir = Path(game_dir)
    champions_dir = game_dir / "characters"
    targets = [
        (
            CDRAGON_RAW.format(patch=patch, name=champion_dir(name)),
            champions_dir / f"{champion_dir(name)}.bin.json",
        )
        for name in champion_names
    ]
    targets.append((ITEMS_URL.format(patch=patch), game_dir / "items.bin.json"))
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(lambda pair: _download(*pair), targets))
    return game_dir


# ---------------------------------------------------------------------------
# Champion stat comparison
# ---------------------------------------------------------------------------


def _character_record_key(bin_data, champion_name):
    """Pick the champion's own CharacterRecord key.

    A bin can carry several records (Gnar ships Mini + Mega/GnarBig, and
    skins/alt-units may add more); the champion's own record is the one whose
    path has a segment exactly matching the champion name (case-insensitive),
    falling back to the first record otherwise.
    """
    keys = [key for key in bin_data if "CharacterRecords" in key]
    if not keys:
        return None
    wanted = champion_dir(champion_name)
    for key in keys:
        segments = [re.sub(r"[^a-z0-9]", "", s.lower()) for s in key.split("/")]
        if wanted in segments:
            return key
    return keys[0]


def champion_game_stats(bin_data, champion_name=""):
    """Extract the CharacterRecord stat snapshot from a champion bin."""
    record_key = _character_record_key(bin_data, champion_name)
    if record_key is None:
        return {}, None
    root = bin_data[record_key]
    resource = root.get("primaryAbilityResource") or {}
    stats = {}

    def value(holder, field):
        entry = holder.get(field)
        if isinstance(entry, dict):
            return entry.get("baseValue")
        return entry

    for cache_stat, component, game_field, multiplier in CHAMPION_STAT_MAP:
        raw = value(root, game_field)
        if raw is None:
            continue
        stats[(cache_stat, component)] = raw * multiplier

    ar_type = resource.get("arType")
    if ar_type in (0, 1):  # MANA / ENERGY: pool + regen fields are comparable
        pool = value(resource, RESOURCE_POOL)
        pool_per_level = value(resource, RESOURCE_POOL_PER_LEVEL)
        regen = value(resource, RESOURCE_REGEN)
        regen_per_level = value(resource, RESOURCE_REGEN_PER_LEVEL)
        if pool is not None:
            stats[("mana", "flat")] = pool
        if pool_per_level is not None:
            stats[("mana", "perLevel")] = pool_per_level
        if regen is not None:
            stats[("manaRegen", "flat")] = regen * 5.0
        if regen_per_level is not None:
            stats[("manaRegen", "perLevel")] = regen_per_level * 5.0
    return stats, ar_type


def compare_champion_stats(cache_stats, game_stats):
    """Return (stat_drift, checked_count, unchecked_count).

    ``stat_drift`` maps "stat.component" -> {"cached": .., "game": ..} for
    every cache stat that could be compared and drifted beyond tolerance.
    Stats the game source cannot express are unchecked, never stale.
    """
    drift = {}
    checked = 0
    unchecked = 0
    stat_keys = [(stat, comp) for stat, comp, _f, _m in CHAMPION_STAT_MAP]
    # The resource-family stats are not in CHAMPION_STAT_MAP: the pool/regen
    # fields only exist for MANA/ENERGY resources, so they are compared when
    # present and counted unchecked (never stale) when the source lacks them.
    stat_keys += [
        ("mana", "flat"),
        ("mana", "perLevel"),
        ("manaRegen", "flat"),
        ("manaRegen", "perLevel"),
    ]
    for cache_stat, component in stat_keys:
        cached = (cache_stats.get(cache_stat) or {}).get(component)
        if not isinstance(cached, (int, float)):
            continue
        game = game_stats.get((cache_stat, component))
        if game is None:
            if cached == 0:
                continue  # both sources agree there is nothing to check
            unchecked += 1
            continue
        checked += 1
        if not within_tolerance(cached, game):
            drift[f"{cache_stat}.{component}"] = {
                "cached": cached,
                "game": round(game, 4),
            }
    return drift, checked, unchecked


# ---------------------------------------------------------------------------
# Ability-leveling comparison (best-effort)
# ---------------------------------------------------------------------------


def _numeric_values(values):
    """Return the numeric entries of a wiki modifier values list."""
    return [value for value in values if isinstance(value, (int, float))]


def _is_scaled_display_row(units):
    """True when the wiki row's units describe a stack/level-scaled display
    (e.g. "(based on Rampage stacks)") rather than a per-rank value list."""
    text = " ".join(units or []).lower()
    return "based on" in text or "stack" in text


def _downsample_match(wiki_values, game_values, flat_tolerance: float):
    """Try matching every-other wiki value, for interpolated display rows: a
    3-rank game cooldown shown as five (100/85/70 -> 100/92.5/85/77.5/70)
    matches exactly at the odd positions."""
    if len(wiki_values) == 2 * len(game_values) - 1:
        return _slices_match(wiki_values[::2], game_values, flat_tolerance)
    return False


def _slices_match(wiki_values, game_values, flat_tolerance):
    """True when any contiguous rank-slice of game_values equals wiki_values."""
    n = len(wiki_values)
    if n == 0 or not game_values:
        return False
    for start in range(len(game_values) - n + 1):
        window = game_values[start : start + n]
        if all(
            isinstance(g, (int, float)) and within_tolerance(w, g, flat=flat_tolerance)
            for w, g in zip(wiki_values, window, strict=False)
        ):
            return True
    return False


def _data_value_matches(wiki_values, spell):
    """Return (matched, game_row_name) against the spell's DataValues rows."""
    for data_value in spell.get("DataValues") or []:
        row = data_value.get("values") or []
        candidates = [row]
        numerics = [v for v in row if isinstance(v, (int, float))]
        if numerics and max(abs(v) for v in numerics) <= 10.0:
            candidates.append([v * 100 for v in row])  # ratio rows (x100)
        # Game files store slows/speeds as negatives; the wiki shows the
        # magnitude, so absolute-value variants are legitimate candidates.
        candidates.append([abs(v) for v in row])
        if numerics and max(abs(v) for v in numerics) <= 10.0:
            candidates.append([abs(v) * 100 for v in row])
        seen = set()
        for candidate in candidates:
            key = tuple(candidate)
            if key in seen:
                continue
            seen.add(key)
            if _slices_match(wiki_values, candidate, ABILITY_FLAT_TOLERANCE):
                return True, data_value.get("name")
    return False, None


def _normalize_attr(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _attr_matches_game_row(attribute, spell):
    """True when the wiki attribute name equals a DataValues row name."""
    normalized = _normalize_attr(attribute)
    if not normalized:
        return False
    return any(
        _normalize_attr(row.get("name")) == normalized
        for row in spell.get("DataValues") or []
    )


def game_spells_by_slot(bin_data, champion_name, cache_abilities):
    """Locate the game SpellDataResource per wiki ability slot (best-effort).

    Q/W/E/R come from CharacterRecord.spellNames in slot order; form-heavy
    champions consume one spell per wiki entry in list order, so entries
    without a matching game spell fall back to unchecked.  P uses
    mCharacterPassiveSpell.
    """
    record_key = _character_record_key(bin_data, champion_name)
    root = bin_data.get(record_key) if record_key else None
    by_slot = {"P": [], "Q": [], "W": [], "E": [], "R": []}
    if not root:
        return by_slot

    game_spells = []
    for spell_name in root.get("spellNames") or []:
        key = f"Characters/{champion_name}/Spells/{spell_name}"
        obj = bin_data.get(key)
        if obj is None:
            candidates = [
                k
                for k in bin_data
                if isinstance(bin_data[k], dict)
                and bin_data[k].get("__type") == "SpellObject"
                and k.endswith("/" + spell_name)
            ]
            obj = bin_data.get(candidates[0]) if candidates else None
        if obj and obj.get("__type") == "SpellObject":
            game_spells.append(obj.get("mSpell") or {})

    # spellNames is exactly one spell per slot in Q/W/E/R order for every
    # champion in the roster (verified across all 173), so each slot gets at
    # most one game spell; extra wiki forms (Elise spider, Gnar Mega, Jayce
    # ranged, ...) have no game spell here and stay unchecked rather than
    # being paired with a wrong slot's spell.
    for slot in _SLOT_ORDER:
        if game_spells:
            by_slot[slot] = [game_spells.pop(0)]
        else:
            by_slot[slot] = []

    passive_key = root.get("mCharacterPassiveSpell")
    passive = bin_data.get(passive_key) if passive_key else None
    if passive and passive.get("__type") == "SpellObject":
        by_slot["P"] = [passive.get("mSpell") or {}]
    return by_slot


def compare_ability_rows(cache_abilities, bin_data, champion_name, ddragon=None):
    """Compare wiki ability rows against the game bin (best-effort).

    ``ddragon`` is the champion's official tooltip row dict keyed by slot
    (see ddragon_rows_by_slot).  Returns
    (rows_checked, rows_stale, unchecked, notes, needs_ddragon) where
    needs_ddragon names the slots whose cooldown/cost rows could not be
    arbitrated from the bin alone.
    """
    by_slot = game_spells_by_slot(bin_data, champion_name, cache_abilities)
    checked = 0
    stale = 0
    unchecked = 0
    notes = []
    needs_ddragon = set()
    for slot in ("P", "Q", "W", "E", "R"):
        entries = cache_abilities.get(slot) or []
        spells = by_slot.get(slot) or []
        for index, entry in enumerate(entries):
            spell = spells[index] if index < len(spells) else None
            if not isinstance(entry, dict):
                continue
            if spell is None:
                rows = _wiki_row_count(entry)
                unchecked += rows
                if rows:
                    notes.append(f"{slot}[{index}] no game spell")
                continue
            (
                rows_checked,
                rows_stale,
                rows_unchecked,
                row_notes,
                row_needs,
            ) = _compare_entry_rows(
                entry,
                spell,
                slot,
                index,
                ddragon=(ddragon or {}).get(slot),
            )
            checked += rows_checked
            stale += rows_stale
            unchecked += rows_unchecked
            notes.extend(row_notes)
            needs_ddragon.update(row_needs)
    return checked, stale, unchecked, notes, needs_ddragon


def _wiki_row_count(entry):
    """Count numeric cooldown/cost/leveling rows an entry contributes."""
    count = 0
    for key in ("cooldown", "cost"):
        modifiers = (entry.get(key) or {}).get("modifiers") or []
        if modifiers and _numeric_values(modifiers[0].get("values") or []):
            count += 1
    for effect in entry.get("effects") or []:
        for leveling in effect.get("leveling") or []:
            for modifier in leveling.get("modifiers") or []:
                if _numeric_values(modifier.get("values") or []):
                    count += 1
                    break
    return count


def _compare_entry_rows(entry, spell, slot: str, index: int, ddragon=None):
    """Compare one wiki ability entry against one game spell.

    ``ddragon`` is Riot's official per-spell tooltip row dict (cooldown/cost),
    which arbitrates rows the raw bin mechanic fields cannot express: the
    bin's ``cooldownTime``/``mana`` provably diverge from the shipped tooltip
    for some spells (Jax Q cost 65 in bin vs 50 shipped, Volibear Q cooldown
    14/13/12/11/10 vs 12/11.5/11/10.5/10 shipped), so a bin-only mismatch is
    recorded unchecked — never claimed stale — while a mismatch against both
    the bin and the official tooltip is a genuine stale row.
    """
    checked = 0
    stale = 0
    unchecked = 0
    notes = []
    needs_ddragon = set()
    prefix = f"{slot}[{index}]"

    # Cooldown: wiki row vs cooldownTime and any cooldown-named DataValues.
    cd_modifiers = (entry.get("cooldown") or {}).get("modifiers") or []
    for modifier in cd_modifiers:
        values = _numeric_values(modifier.get("values") or [])
        if not values:
            continue
        if all(value == 0 for value in values):
            unchecked += 1  # wiki "no cooldown" display convention
            break
        if len(values) > 6 or _is_scaled_display_row(modifier.get("units")):
            # Per-level or stack-scaled display rows have no single game row.
            unchecked += 1
            break
        bin_values = spell.get("cooldownTime") or []
        data_cooldowns = [
            (data_value.get("values") or [])
            for data_value in spell.get("DataValues") or []
            if "cooldown" in _normalize_attr(data_value.get("name"))
        ]
        matched = _slices_match(values, bin_values, COOLDOWN_FLAT_TOLERANCE) or any(
            _slices_match(values, row, COOLDOWN_FLAT_TOLERANCE)
            for row in data_cooldowns
        )
        if matched:
            checked += 1
        else:
            dd_values = (ddragon or {}).get("cooldown")
            game_has_no_cooldown = (
                bool(bin_values)
                and all(value == bin_values[0] for value in bin_values)
                and bin_values[0] <= 1.0
            )
            if game_has_no_cooldown or (
                dd_values and all(value == 0 for value in dd_values)
            ):
                # The game encodes no real cooldown (auto-attack-based
                # spells, e.g. Rengar Q/W/E; Karthus Q); the wiki's number
                # comes from elsewhere and is not comparable.
                unchecked += 1
                notes.append(f"{prefix} cooldown unchecked (game files: no cooldown)")
            elif dd_values and (
                _expanded_match(values, dd_values, COOLDOWN_FLAT_TOLERANCE)
                or _downsample_match(values, dd_values, COOLDOWN_FLAT_TOLERANCE)
            ):
                checked += 1
                notes.append(f"{prefix} cooldown matched ddragon tooltip")
            elif dd_values:
                stale += 1
                notes.append(
                    f"{prefix} cooldown drifted (bin and ddragon: "
                    f"{dd_values[:3]}...)"
                )
            else:
                unchecked += 1
                needs_ddragon.add("cooldown")
                notes.append(f"{prefix} cooldown unchecked (mechanic field)")
        break

    # Cost: wiki row vs the spell's mana array.
    cost_modifiers = (entry.get("cost") or {}).get("modifiers") or []
    for modifier in cost_modifiers:
        values = _numeric_values(modifier.get("values") or [])
        if not values:
            continue
        if all(value == 0 for value in values):
            unchecked += 1  # wiki "no cost" display convention
            break
        if len(values) > 6 or _is_scaled_display_row(modifier.get("units")):
            # Per-level (Udyr stances) or stack-scaled (Kassadin R) display
            # rows have no single game row.
            unchecked += 1
            break
        mana = spell.get("mana")
        if mana is not None and _slices_match(values, mana, COST_FLAT_TOLERANCE):
            checked += 1
        else:
            dd_values = (ddragon or {}).get("cost")
            if dd_values and all(value == 0 for value in dd_values):
                # Ability costs no mana; the wiki's row is a health/other
                # cost (Briar, Dr. Mundo, Vladimir, Zac, Zyra, ...) that the
                # game's mana field cannot express — not comparable.
                unchecked += 1
                notes.append(f"{prefix} cost unchecked (game files: no mana cost)")
            elif dd_values and (
                _expanded_match(values, dd_values, COST_FLAT_TOLERANCE)
                or _downsample_match(values, dd_values, COST_FLAT_TOLERANCE)
            ):
                checked += 1
                notes.append(f"{prefix} cost matched ddragon tooltip")
            elif dd_values:
                stale += 1
                notes.append(
                    f"{prefix} cost drifted (bin and ddragon: " f"{dd_values[:3]}...)"
                )
            else:
                unchecked += 1
                needs_ddragon.add("cost")
                notes.append(f"{prefix} cost unchecked (no bin/ddragon source)")
        break

    # Leveling rows: match named DataValues rows by value; only rows whose
    # attribute name equals a game row name can be declared stale.
    for effect in entry.get("effects") or []:
        for leveling in effect.get("leveling") or []:
            attribute = leveling.get("attribute") or ""
            row_checked = False
            row_has_values = False
            for modifier in leveling.get("modifiers") or []:
                values = _numeric_values(modifier.get("values") or [])
                if not values:
                    continue
                row_has_values = True
                matched, matched_name = _data_value_matches(values, spell)
                if matched:
                    row_checked = True
                    notes.append(f"{prefix} {attribute} matched {matched_name}")
            if not row_has_values:
                continue
            if row_checked:
                checked += 1
            elif _attr_matches_game_row(attribute, spell):
                stale += 1
                notes.append(f"{prefix} {attribute} drifted vs game row")
            else:
                unchecked += 1
    return checked, stale, unchecked, notes, needs_ddragon


# ---------------------------------------------------------------------------
# Item comparison
# ---------------------------------------------------------------------------


def items_by_id(game_items):
    """Map game ItemData entries by itemID (as strings)."""
    by_id = {}
    for entry in game_items.values():
        if not isinstance(entry, dict) or entry.get("__type") != "ItemData":
            continue
        item_id = entry.get("itemID")
        if item_id is not None:
            by_id[str(item_id)] = entry
    return by_id


def compare_item_stats(cache_item, game_item):
    """Return (stat_drift, checked_count, unchecked_count) for one item."""
    drift = {}
    checked = 0
    unchecked = 0
    cache_stats = cache_item.get("stats") or {}
    for cache_stat, component, game_field, multiplier in ITEM_STAT_MAP:
        cached = (cache_stats.get(cache_stat) or {}).get(component)
        if not isinstance(cached, (int, float)) or cached == 0:
            continue
        game_value = game_item.get(game_field)
        if game_value is None:
            unchecked += 1
            continue
        checked += 1
        game = game_value * multiplier
        if not within_tolerance(cached, game):
            drift[f"{cache_stat}.{component}"] = {
                "cached": cached,
                "game": round(game, 4),
            }
    return drift, checked, unchecked


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------


def build_staleness(patch, champions_cache, items_cache, game_dir, ddragon=None):
    """Compare the wiki cache against the game files -> staleness document.

    ``ddragon`` (optional) maps champion name -> official tooltip rows and is
    used only to arbitrate cooldown/cost rows (see _compare_entry_rows).
    """
    game_dir = Path(game_dir)
    with (game_dir / "items.bin.json").open(encoding="utf-8") as handle:
        game_items = json.load(handle)
    game_items_by_id = items_by_id(game_items)

    champions = {}
    pending = {}
    for name, cache_entry in champions_cache.items():
        bin_path = game_dir / "characters" / f"{champion_dir(name)}.bin.json"
        try:
            with Path(bin_path).open(encoding="utf-8") as handle:
                bin_data = json.load(handle)
        except OSError as exc:
            champions[name] = {
                "stale": False,
                "stat_drift": {},
                "ability_rows_checked": 0,
                "ability_rows_stale": 0,
                "note": f"game file unavailable: {exc}",
            }
            continue
        game_stats, _ar_type = champion_game_stats(bin_data, name)
        stat_drift, checked, unchecked = compare_champion_stats(
            cache_entry.get("stats") or {}, game_stats
        )
        (
            rows_checked,
            rows_stale,
            rows_unchecked,
            row_notes,
            row_needs,
        ) = compare_ability_rows(
            cache_entry.get("abilities") or {},
            bin_data,
            name,
            ddragon=(ddragon or {}).get(name),
        )
        if row_needs:
            pending[name] = sorted(row_needs)
        notes = []
        if unchecked:
            notes.append(f"{unchecked} stat(s) unchecked (no game field)")
        if rows_unchecked:
            notes.append(f"{rows_unchecked} ability row(s) unchecked (no game mapping)")
        notes.extend(row_notes[:3])
        champions[name] = {
            "stale": bool(stat_drift) or rows_stale > 0,
            "stat_drift": stat_drift,
            "stats_checked": checked,
            "ability_rows_checked": rows_checked,
            "ability_rows_stale": rows_stale,
            "note": "; ".join(notes),
        }

    items = {}
    for item_id, cache_entry in items_cache.items():
        game_item = game_items_by_id.get(item_id)
        name = cache_entry.get("name") or item_id
        if game_item is None:
            items[item_id] = {
                "name": name,
                "stale": False,
                "stat_drift": {},
                "note": "not present in game item bin",
            }
            continue
        stat_drift, checked, unchecked = compare_item_stats(cache_entry, game_item)
        note = f"{unchecked} stat(s) unchecked" if unchecked else ""
        items[item_id] = {
            "name": name,
            "stale": bool(stat_drift),
            "stat_drift": stat_drift,
            "stats_checked": checked,
            "note": note,
        }

    document = {
        "patch": patch,
        "checked_at": datetime.now(UTC).isoformat(),
        "champions": champions,
        "items": items,
    }
    return document, pending


# ---------------------------------------------------------------------------
# cdtb WAD spot-check (proves the raw export equals the real WADs)
# ---------------------------------------------------------------------------


def verify_wads(patch, champion_names, game_dir, storage=None):
    """Download real champion WADs via cdtb and diff CharacterRecords.

    Uses the wad-env interpreter that has cdtb installed; the helper script
    downloads only the bundles needed for the requested WADs and extracts the
    champion bin, then ``cdtb bin-dump --json`` produces the ground truth.
    Returns a per-champion report of stat deltas (empty = identical).
    """
    tmp_root = os.environ.get("TMPDIR", "/tmp")  # noqa: S108 - cdtb scratch
    storage = storage or str(Path(tmp_root) / "lcc-p3-cdtb")
    report = {}
    for name in champion_names:
        champ_dir = champion_dir(name)
        wad_path = extract_champion_bin_via_cdtb(patch, name, storage, CDTB_PYTHON)
        if wad_path is None:
            report[name] = {"error": "cdtb extraction failed"}
            continue
        dump = subprocess.run(
            [CDTB_BIN, "bin-dump", "--json", str(wad_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if dump.returncode != 0:
            report[name] = {"error": dump.stderr.strip() or dump.stdout.strip()}
            continue
        wad_bin = json.loads(dump.stdout)
        game_stats, _ = champion_game_stats(wad_bin, name)
        raw_bin = json.loads(
            (Path(game_dir) / "characters" / f"{champ_dir}.bin.json").read_text(
                encoding="utf-8"
            )
        )
        raw_stats, _ = champion_game_stats(raw_bin, name)
        deltas = {
            ".".join(key): {"wad": value, "raw": raw_stats.get(key)}
            for key, value in game_stats.items()
            if raw_stats.get(key) is not None and abs(value - raw_stats[key]) > 1e-9
        }
        report[name] = {
            "wad": str(wad_path),
            "stat_deltas": deltas,
            "identical": not deltas,
        }
    return report


def extract_champion_bin_via_cdtb(patch, name, storage, python_bin):
    """Download/extract one champion WAD through the cdtb Python API.

    Returns the path of the extracted champion bin, or None on failure.
    """
    champ_dir = champion_dir(name)
    helper = r"""
import json, os, sys
from cdtb.patcher import PatcherStorage

patch = sys.argv[1]
wanted = sys.argv[2].lower()
storage = sys.argv[3]
os.makedirs(storage, exist_ok=True)
os.chdir(storage)
st = PatcherStorage.from_path("patcher:cdn")
st.patch(patch)  # ensure release info is fetched
game = [e for e in st.patch(patch).elements if e.name == "game"][0]
manif = game.elem.manif
files = [f for f in manif.filter_files(langs=False)
         if f.name.lower() == f"data/final/champions/{wanted}.wad.client"]
if not files:
    sys.exit("wad not found: " + wanted)
bundle_ids = {c.bundle.bundle_id for f in files for c in f.chunks}
for bundle_id in sorted(bundle_ids):
    st.download_bundle(bundle_id)
for f in files:
    game.elem.extract_file(f)
print(os.path.abspath(game.elem.extract_path(files[0])))
"""
    result = subprocess.run(
        [python_bin, "-c", helper, patch, name, storage],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    wad_path = result.stdout.strip().splitlines()[-1]
    if not Path(wad_path).is_file():
        return None
    extract_dir = wad_path + ".x"
    extract = subprocess.run(
        [CDTB_BIN, "wad-extract", wad_path, "-o", extract_dir, "-u", "no"],
        capture_output=True,
        text=True,
        check=False,
    )
    if extract.returncode != 0:
        return None
    candidates = list(Path(extract_dir).rglob(f"{champ_dir}.bin"))
    candidates = [c for c in candidates if "characters" in str(c).lower()]
    return str(candidates[0]) if candidates else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: None | list[str] = None):
    parser = argparse.ArgumentParser(
        description="Compare the wiki cache against game-file ground truth.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("check", help="write data/staleness.json")
    check.add_argument("--patch", help="game patch to compare (default: live via cdtb)")
    check.add_argument(
        "--cache-dir", default=str(DEFAULT_GAME_DIR), help="game JSON cache dir"
    )
    check.add_argument("--out", default=str(DEFAULT_OUT), help="staleness output")
    check.add_argument(
        "--data-dir", default=str(DEFAULT_DATA_DIR), help="wiki cache dir"
    )
    check.add_argument(
        "--verify-wads",
        help="comma-separated champions to spot-check via real cdtb WAD download",
    )
    check.add_argument("--limit", type=int, help="compare only the first N champions")
    check.add_argument("--cdtb-bin", default=CDTB_BIN, help="path to the cdtb CLI")
    check.add_argument(
        "--no-ddragon",
        action="store_true",
        help="skip Riot ddragon tooltip arbitration (cooldown/cost rows "
        "then stay unchecked when the raw bin fields do not match)",
    )
    args = parser.parse_args(argv)
    if args.command != "check":
        parser.print_help()
        return 2

    # A missing cdtb is an infrastructure failure (exit 2), not a bare
    # FileNotFoundError traceback: the message points at CDTB_BIN / --patch.
    try:
        patch = args.patch or resolve_patch(args.cdtb_bin)
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    data_dir = Path(args.data_dir)
    with (data_dir / "champions.json").open(encoding="utf-8") as handle:
        champions_cache = json.load(handle)
    with (data_dir / "items.json").open(encoding="utf-8") as handle:
        items_cache = json.load(handle)
    names = list(champions_cache)
    if args.limit:
        names = names[: args.limit]

    print(
        f"patch {patch}: comparing {len(names)} champions and "
        f"{len(items_cache)} items against game files"
    )
    download_game_files(patch, args.cache_dir, names)

    document, pending = build_staleness(
        patch,
        {n: champions_cache[n] for n in names},
        items_cache,
        args.cache_dir,
        ddragon=None,
    )
    if not args.no_ddragon and pending:
        ddragon_version = extract_ddragon_version(champions_cache)
        if ddragon_version:
            ddragon = fetch_ddragon_for_pending(
                ddragon_version, pending, args.cache_dir
            )
            print(
                f"ddragon tooltip arbitration ({ddragon_version}): "
                f"{len(ddragon)} champions"
            )
            document, _ = build_staleness(
                patch,
                {n: champions_cache[n] for n in names},
                items_cache,
                args.cache_dir,
                ddragon=ddragon,
            )
        else:
            print(
                "ddragon version not found; cooldown/cost rows stay "
                "conservatively unchecked"
            )

    if args.verify_wads:
        report = verify_wads(patch, args.verify_wads.split(","), args.cache_dir)
        print(json.dumps({"wad_verification": report}, indent=2))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    stale_champions = sum(1 for e in document["champions"].values() if e["stale"])
    stale_items = sum(1 for e in document["items"].values() if e["stale"])
    print(f"stale: {stale_champions} champions, {stale_items} items -> {out}")
    return 1 if (stale_champions or stale_items) else 0


if __name__ == "__main__":
    sys.exit(main())
