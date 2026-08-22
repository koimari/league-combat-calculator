"""Champion ability registry.

Every champion in the pinned Wiki cache has a dedicated importable module.
The reviewed modules are explicit, source-pinned packet modules for the
entire roster; there is no generated or generic middle lane and no runtime
archetype registration in the reviewed surface.
"""

import importlib
from typing import Any

from ..cast_dependency import CastDependency
from ..stat_conversion import BonusHealthConversion
from .module_contract import ChampionModuleContract, contract_from_module

# Map display name -> module name within this package.  This is the single
# explicit roster manifest: every cached champion has a reviewed module and
# no champion is routed through an archetype parser at runtime.
_CHAMPION_MODULES: dict[str, str] = {
    "Aatrox": "aatrox",
    "Ahri": "ahri",
    "Akali": "akali",
    "Akshan": "akshan",
    "Alistar": "alistar",
    "Ambessa": "ambessa",
    "Amumu": "amumu",
    "Aphelios": "aphelios",
    "Anivia": "anivia",
    "Annie": "annie",
    "Ashe": "ashe",
    "Aurelion Sol": "aurelion_sol",
    "Aurora": "aurora",
    "Azir": "azir",
    "Bard": "bard",
    "Bel'Veth": "belveth",
    "Blitzcrank": "blitzcrank",
    "Brand": "brand",
    "Braum": "braum",
    "Briar": "briar",
    "Caitlyn": "caitlyn",
    "Camille": "camille",
    "Cassiopeia": "cassiopeia",
    "Cho'Gath": "chogath",
    "Corki": "corki",
    "Darius": "darius",
    "Diana": "diana",
    "Dr. Mundo": "dr_mundo",
    "Draven": "draven",
    "Ezreal": "ezreal",
    "Ekko": "ekko",
    "Elise": "elise",
    "Evelynn": "evelynn",
    "Fiddlesticks": "fiddlesticks",
    "Fiora": "fiora",
    "Fizz": "fizz",
    "Gangplank": "gangplank",
    "Garen": "garen",
    "Gragas": "gragas",
    "Graves": "graves",
    "Gwen": "gwen",
    "Hecarim": "hecarim",
    "Heimerdinger": "heimerdinger",
    "Hwei": "hwei",
    "Illaoi": "illaoi",
    "Irelia": "irelia",
    "Ivern": "ivern",
    "Janna": "janna",
    "Jax": "jax",
    "Jhin": "jhin",
    "K'Sante": "ksante",
    "Karma": "karma",
    "Kassadin": "kassadin",
    "Katarina": "katarina",
    "Kayle": "kayle",
    "Kayn": "kayn",
    "Kennen": "kennen",
    "Kha'Zix": "khazix",
    "Kindred": "kindred",
    "Kled": "kled",
    "LeBlanc": "leblanc",
    "Lee Sin": "lee_sin",
    "Leona": "leona",
    "Lillia": "lillia",
    "Locke": "locke",
    "Lucian": "lucian",
    "Lulu": "lulu",
    "Lux": "lux",
    "Malphite": "malphite",
    "Malzahar": "malzahar",
    "Maokai": "maokai",
    "Master Yi": "master_yi",
    "Mel": "mel",
    "Milio": "milio",
    "Miss Fortune": "miss_fortune",
    "Mordekaiser": "mordekaiser",
    "Morgana": "morgana",
    "Naafiri": "naafiri",
    "Nami": "nami",
    "Nasus": "nasus",
    "Nautilus": "nautilus",
    "Neeko": "neeko",
    "Nidalee": "nidalee",
    "Nilah": "nilah",
    "Nocturne": "nocturne",
    "Nunu & Willump": "nunu_willump",
    "Olaf": "olaf",
    "Pantheon": "pantheon",
    "Poppy": "poppy",
    "Pyke": "pyke",
    "Quinn": "quinn",
    "Rammus": "rammus",
    "Rek'Sai": "reksai",
    "Rell": "rell",
    "Renata Glasc": "renata_glasc",
    "Renekton": "renekton",
    "Rengar": "rengar",
    "Riven": "riven",
    "Rumble": "rumble",
    "Ryze": "ryze",
    "Samira": "samira",
    "Sejuani": "sejuani",
    "Senna": "senna",
    "Seraphine": "seraphine",
    "Sett": "sett",
    "Shaco": "shaco",
    "Singed": "singed",
    "Sion": "sion",
    "Sivir": "sivir",
    "Skarner": "skarner",
    "Smolder": "smolder",
    "Sona": "sona",
    "Swain": "swain",
    "Sylas": "sylas",
    "Talon": "talon",
    "Taric": "taric",
    "Teemo": "teemo",
    "Thresh": "thresh",
    "Tristana": "tristana",
    "Trundle": "trundle",
    "Tryndamere": "tryndamere",
    "Twisted Fate": "twisted_fate",
    "Twitch": "twitch",
    "Udyr": "udyr",
    "Urgot": "urgot",
    "Varus": "varus",
    "Veigar": "veigar",
    "Vel'Koz": "velkoz",
    "Vex": "vex",
    "Viego": "viego",
    "Viktor": "viktor",
    "Vladimir": "vladimir",
    "Volibear": "volibear",
    "Warwick": "warwick",
    "Xayah": "xayah",
    "Xerath": "xerath",
    "Xin Zhao": "xin_zhao",
    "Yasuo": "yasuo",
    "Yone": "yone",
    "Yorick": "yorick",
    "Yunara": "yunara",
    "Yuumi": "yuumi",
    "Zaahen": "zaahen",
    "Zac": "zac",
    "Zed": "zed",
    "Zeri": "zeri",
    "Zilean": "zilean",
    "Zoe": "zoe",
    "Zyra": "zyra",
    "Galio": "galio",
    "Gnar": "gnar",
    "Jarvan IV": "jarvan_iv",
    "Jayce": "jayce",
    "Jinx": "jinx",
    "Kalista": "kalista",
    "Kai'Sa": "kaisa",
    "Karthus": "karthus",
    "Kog'Maw": "kogmaw",
    "Lissandra": "lissandra",
    "Orianna": "orianna",
    "Ornn": "ornn",
    "Qiyana": "qiyana",
    "Rakan": "rakan",
    "Shen": "shen",
    "Soraka": "soraka",
    "Syndra": "syndra",
    "Shyvana": "shyvana",
    "Taliyah": "taliyah",
    "Tahm Kench": "tahm_kench",
    "Vayne": "vayne",
    "Vi": "vi",
    "Wukong": "wukong",
    "Ziggs": "ziggs",
}

# Resolved module ``parse_abilities`` callables — the import system already
# caches modules, but the coupled optimizer dispatches thousands of parses
# per request, so skip even the ``import_module`` lookup after the first.
_MODULE_CONTRACTS: dict[str, ChampionModuleContract] = {}


def get_champion_module_contract(champion_name: str) -> ChampionModuleContract:
    """Import and validate the authoritative module for *champion_name*."""

    module_name = _CHAMPION_MODULES.get(champion_name)
    if module_name is None:
        raise KeyError(f"no registered champion module for {champion_name!r}")
    cached = _MODULE_CONTRACTS.get(champion_name)
    if cached is not None and cached.module_name == module_name:
        return cached
    module = importlib.import_module(f".{module_name}", package=__name__)
    contract = contract_from_module(champion_name, module_name, module)
    _MODULE_CONTRACTS[champion_name] = contract
    return contract


# Option keys owned by the pipeline — never user input, never a module
# OPTIONS declaration (tests/test_champion_options.py enforces the
# no-collision rule). Injected by ``pipeline.run_fight`` for timed
# fights; absent in one-rotation mode and direct parse calls, where
# modules fall back to their per-cast models.
# ``fight_duration_seconds``: the fight window, so duration-driven
# mechanics (e.g. Aurelion Sol's continuous Q channel) can scale with it.
# ``auto_attack_uptime``: the fight's auto uptime, so auto-timeline
# mechanics (e.g. Braum's passive stack cycle) walk the same auto
# cadence (attack_speed x uptime) the fight engine schedules.
# ``auto_attacks_only``: the engine casts no abilities in this window,
# so a walk module must count ambient swings alone — without it a
# merged auto+ability stream (Braum P, Vi W, Caitlyn P) keeps pricing
# hits from casts that never happened.
RESERVED_OPTION_KEYS = frozenset(
    {"fight_duration_seconds", "auto_attack_uptime", "auto_attacks_only"}
)


def parse_abilities(
    champion_name: str,
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
    champion_options: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Ability damage for any champion, keyed by cast slot.

    Dispatches to a dedicated reviewed module. Unknown names fail closed.
    """
    contract = get_champion_module_contract(champion_name)
    return contract.parse_abilities(
        champion_data,
        level,
        total_ability_power,
        ability_ranks=ability_ranks,
        champion_options=champion_options,
        champion_stats=champion_stats,
        target_stats=target_stats,
    )


def parse_champion_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
    champion_options: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse loaded champion data through its display-name dispatcher.

    Prefer this entry point when the cached champion object is already in
    hand. It prevents data keys such as ``KogMaw`` from accidentally bypassing
    the registered ``Kog'Maw`` module.
    """
    return parse_abilities(
        champion_data["name"],
        champion_data,
        level,
        total_ability_power,
        ability_ranks=ability_ranks,
        champion_stats=champion_stats,
        target_stats=target_stats,
        champion_options=champion_options,
    )


def get_champion_cast_order(champion_name: str) -> list[str] | None:
    """The champion's own rotation order, or ``None`` for the default.

    A module declares ``CAST_ORDER`` when the engine's ``(Q, Q2, W, E, R)``
    misrepresents how the kit is used: Jayce transforms into Cannon stance
    and only then casts, so his R resolves before Q/W.
    """
    try:
        module = get_champion_module_contract(champion_name).module
    except KeyError:
        return None
    declared = getattr(module, "CAST_ORDER", None)
    return list(declared) if declared else None


# ``False`` — an unregistered name, or a module that stays silent — keeps the
# scheduler's conservative one-cast rule.  Read off the validated contract,
# never off the module, whose own constant never passed the import gate.
def get_champion_ultimate_recasts(champion_name: str) -> bool:
    """Whether the timed scheduler may recast this champion's R."""
    try:
        return get_champion_module_contract(champion_name).ultimate_recasts
    except KeyError:
        return False


def get_champion_cast_dependencies(champion_name: str) -> tuple[CastDependency, ...]:
    """The validated ``CAST_DEPENDENCIES``, or ``()``; never read off the
    module, whose own copy never passed the import gate.
    """
    try:
        return get_champion_module_contract(champion_name).cast_dependencies
    except KeyError:
        return ()


# ``None`` for a champion with no registered module too: a kit the
# calculator has not reviewed keeps the stats its items grant.
def get_champion_stat_conversion(champion_name: str) -> BonusHealthConversion | None:
    """The validated ``MODULE_STAT_CONVERSION``, or ``None``."""
    try:
        return get_champion_module_contract(champion_name).stat_conversion
    except KeyError:
        return None


def get_champion_options_meta(champion_name: str) -> dict[str, Any]:
    """A champion's option/assumption metadata for the frontend.

    Registered modules declare ``OPTIONS`` (dicts of ``key``, ``type``,
    ``default``, ``label``, plus ``min``/``max``/``step`` for numeric
    inputs), ``ASSUMPTIONS`` (prose shown in the UI), and optionally
    revision-pinned ``SOURCES``; a source row carries ``label``, ``url``,
    ``revision_id``, ``revision_timestamp``. Unregistered: empty lists.
    """
    try:
        contract = get_champion_module_contract(champion_name)
    except KeyError:
        return {"options": [], "assumptions": [], "sources": []}
    return {
        "options": list(contract.options),
        "assumptions": list(contract.assumptions),
        "sources": list(contract.sources),
    }


# ─────────────────────────────────────────────────────────────────────────
# Typed rotation semantics for OPTIONS keys
#
# The rotation resolver builds its setup/consume edges FROM these
# declarations, and there is no second hand-maintained vocabulary in
# rotation_resolver.py.  A module OPTIONS entry may carry an
# inline ``rotation`` dict (authoritative at the option's source, e.g.
# Diana's ``moonlight_reset``); every other key is classified here, as
# data, so an unclassified option is a contract failure
# (tests/test_champion_options.py).
#
# Fields:
#   role       setup | consume | self_state | execute | irrelevant |
#              unsupported  (closed six-role vocabulary)
#   slot       the cast slot the option belongs to ("Q"/"W"/"E"/"R"/"P"),
#              "auto_stream" for auto/on-hit-stream inputs, or a
#              per-champion dict for keys whose slot differs by champion
#              (``target_missing_hp_pct``).
#   condition  free token used in the receipt cite (consume/setup/execute)
#   kind       edge-pairing behavior for the corpus fallback:
#              dot_consume | stack_consume | mark_consume | mark_applier |
#              execute | amp  (consume/setup/execute only)
#   setup_slot (consume/execute only) the slot whose setup is consumed —
#              produces the direct ``setup_slot -> slot`` edge without
#              depending on applier-corpus phrases.
#
# Classification notes for the bulk (self_state/irrelevant): cross-slot
# semantics of the remaining options (shreds, marks, executes, recasts) are
# already detected through parsed atoms (``target_debuff``,
# ``post_hit_proc``, ``recast_of``, ...), so their classification is
# receipt-only: they are acknowledged in the rotation receipt without
# inventing duplicate edges.
# ─────────────────────────────────────────────────────────────────────────

_ROTATION_CLASSIFICATIONS: dict[str, dict[str, Any]] = {
    "accelerated_q": {"role": "irrelevant", "slot": "Q"},
    # P4-14: Darius's W kill rule is a resource/cooldown assertion, NOT a
    # rotation edge (an execute role would reorder the derived rotation) —
    # classified irrelevant so the exhaustiveness contract passes.
    "w_kill_assertion": {"role": "irrelevant", "slot": "W"},
    # P4-Vayne-Q: the reset-throughput assertion is not a rotation edge
    # (classified irrelevant, the w_kill_assertion precedent).
    "q_tumble_reset": {"role": "irrelevant", "slot": "Q"},
    # P4-Mundo-E: the reset-throughput assertion is not a rotation edge
    # (classified irrelevant, the q_tumble_reset precedent).
    "e_reset_throughput": {"role": "irrelevant", "slot": "E"},
    "adoration_cash_in": {"role": "irrelevant", "slot": "P"},
    "adoration_stacks": {"role": "self_state", "slot": "P"},
    "all_out": {"role": "self_state", "slot": "R"},
    "aphelios_bonus_ad_points": {"role": "self_state", "slot": "P"},
    "aphelios_bonus_as_points": {"role": "self_state", "slot": "P"},
    "aphelios_lethality_points": {"role": "self_state", "slot": "P"},
    "aphelios_main_weapon": {"role": "irrelevant", "slot": "Q"},
    "aphelios_overheal_shield": {"role": "self_state", "slot": "P"},
    "bladecaller_feathers": {"role": "self_state", "slot": "E"},
    "blight_stacks": {
        "condition": "blight",
        "kind": "stack_consume",
        "role": "consume",
        "slot": "Q",
    },
    "blood_frenzy_active": {"role": "self_state", "slot": "W"},
    "bonus_movement_speed": {"role": "self_state", "slot": "auto_stream"},
    "champions_pulled": {"role": "self_state", "slot": "R"},
    "charge_fraction": {"role": "self_state", "slot": "R"},
    "chimes": {"role": "self_state", "slot": "P"},
    "clean_cuts_stacks": {"role": "self_state", "slot": "P"},
    "condemn_wall": {"role": "irrelevant", "slot": "E"},
    "e_active": {"role": "self_state", "slot": "E"},
    "e_active_from": {"role": "self_state", "slot": "E"},
    "e_active_seconds": {"role": "self_state", "slot": "E"},
    "e_tether_holds": {"role": "self_state", "slot": "E"},
    "e_blocked_skillshots": {"role": "irrelevant", "slot": "E"},
    "e_blocked_event_ids": {"role": "irrelevant", "slot": "E"},
    "daisy_attacks": {"role": "self_state", "slot": "R"},
    "denting_blows_starting_stacks": {
        "condition": "denting-blows",
        "kind": "stack_consume",
        "role": "consume",
        "slot": "W",
    },
    "dragon_form": {"role": "self_state", "slot": "R"},
    "e_attack_delay": {"role": "self_state", "slot": "E"},
    "e_attacks": {"role": "self_state", "slot": "E"},
    "e_chain_complete": {"role": "irrelevant", "slot": "E"},
    "e_charge": {"role": "self_state", "slot": "E"},
    "e_cone_uptime": {"role": "self_state", "slot": "E"},
    "e_dash": {"role": "self_state", "slot": "E"},
    "e_dash_distance": {"role": "self_state", "slot": "E"},
    "e_detonations": {"role": "irrelevant", "slot": "E"},
    "e_dodged_attacks": {"role": "self_state", "slot": "E"},
    "e_empowered": {"role": "irrelevant", "slot": "E"},
    "e_execute": {
        "condition": "execute",
        "kind": "execute",
        "role": "execute",
        "slot": "E",
    },
    "e_fury": {"role": "self_state", "slot": "E"},
    "e_nearest_target": {"role": "irrelevant", "slot": "E"},
    "e_passes_through_target": {"role": "irrelevant", "slot": "E"},
    "e_second_explosion": {"role": "irrelevant", "slot": "E"},
    "e_shield_retaliations": {"role": "self_state", "slot": "E"},
    "e_second_hit": {"role": "irrelevant", "slot": "E"},
    "e_shots": {"role": "self_state", "slot": "E"},
    "e_stacks": {"role": "self_state", "slot": "E"},
    "e_ticks": {"role": "self_state", "slot": "E"},
    "e_traps": {"role": "self_state", "slot": "E"},
    "e_true_grit_stacks": {"role": "self_state", "slot": "E"},
    "e_upgrade": {"role": "irrelevant", "slot": "E"},
    "e_variant": {"role": "irrelevant", "slot": "E"},
    "e_wall_collision": {"role": "irrelevant", "slot": "E"},
    "feast_stacks": {"role": "self_state", "slot": "R"},
    "form": {"role": "irrelevant", "slot": "P"},
    "hammer_stance": {"role": "irrelevant", "slot": "R"},
    "jinx_get_excited_stacks": {"role": "self_state", "slot": "P"},
    "jinx_rev_up_stacks": {"role": "self_state", "slot": "Q"},
    "jinx_weapon": {"role": "irrelevant", "slot": "Q"},
    "lavender_stacks": {"role": "self_state", "slot": "P"},
    "lulu_pix_bolts": {"role": "self_state", "slot": "P"},
    "maiden_attacks": {"role": "self_state", "slot": "R"},
    "mark_stacks": {"role": "self_state", "slot": "P"},
    "marks": {"role": "self_state", "slot": "P"},
    "mega": {"role": "self_state", "slot": "R"},
    "mines_hit": {"role": "self_state", "slot": "E"},
    "mist_walker_attacks": {"role": "self_state", "slot": "R"},
    "mist_walkers": {"role": "self_state", "slot": "R"},
    "mundo_missing_health_percent": {"role": "self_state", "slot": "E"},
    "near_flag": {"role": "self_state", "slot": "E"},
    "p_backstab": {"role": "self_state", "slot": "P"},
    "p_blade_zone": {"role": "self_state", "slot": "P"},
    "p_critical_pellets": {"role": "irrelevant", "slot": "P"},
    "p_daggers": {"role": "self_state", "slot": "P"},
    "p_essence_fragments": {"role": "self_state", "slot": "P"},
    "p_exalted": {"role": "self_state", "slot": "P"},
    "p_ferocity": {"role": "self_state", "slot": "P"},
    "p_final_shot": {"role": "irrelevant", "slot": "P"},
    "p_gloom_detonations": {"role": "self_state", "slot": "P"},
    "p_illumination_procs": {
        "condition": "illumination",
        "kind": "mark_consume",
        "role": "consume",
        "slot": "R",
    },
    "p_legs": {"role": "self_state", "slot": "P"},
    "p_marks": {"role": "self_state", "slot": "P"},
    "p_missing_health": {"role": "irrelevant", "slot": "P"},
    # Seraphine's Notes and Sylas' Unshackled stacks are both generated by
    # the champion's own ability casts, but each is a stack WINDOW the
    # fight engine does not simulate, so the count is caster state — the
    # Rumble ``overheat_autos`` classification, not a ``consume`` edge
    # (which would have to name one setup_slot, and every basic ability
    # cast feeds these).
    "p_notes_fired": {"role": "self_state", "slot": "P"},
    "p_pre_stacks": {"role": "self_state", "slot": "P"},
    "p_empowered_attacks": {"role": "self_state", "slot": "P"},
    "p_notes": {"role": "self_state", "slot": "P"},
    "p_power_chords": {"role": "self_state", "slot": "P"},
    "p_procs": {"role": "self_state", "slot": "P"},
    "p_ready": {"role": "self_state", "slot": "P"},
    "p_right_punches": {"role": "self_state", "slot": "P"},
    "p_self_health_percent": {"role": "self_state", "slot": "P"},
    # Mel P: how many Searing Brilliance stacks the empowered swing
    # consumes.  Deliberately ``self_state`` and NOT a ``stack_consume``
    # consume edge: the arming relation is already structural, not
    # inferred — the module's ``empower_window`` declares armed_by
    # (Q/W/E/R) and consumed_by ("auto"), and damage.py walks the real
    # accepted cast timeline against it.  A ``consume`` declaration would
    # also have to name ONE ``setup_slot``, which cannot express "any of
    # the four ability slots arms it" (the classification-notes rule:
    # acknowledge in the receipt, never invent a duplicate edge).
    "p_searing_brilliance_missiles": {"role": "self_state", "slot": "P"},
    "p_shot_number": {"role": "self_state", "slot": "P"},
    "p_stacks": {"role": "self_state", "slot": "P"},
    "p_style_stacks": {"role": "self_state", "slot": "P"},
    "p_tentacles": {"role": "self_state", "slot": "P"},
    "p_ticks": {"role": "self_state", "slot": "P"},
    "p_triggers": {"role": "self_state", "slot": "P"},
    "p_vitals": {"role": "self_state", "slot": "P"},
    "passive_procs": {"role": "self_state", "slot": "P"},
    "passive_stacks": {"role": "self_state", "slot": "P"},
    "plant_attacks": {"role": "self_state", "slot": "R"},
    "plant_count": {"role": "self_state", "slot": "R"},
    "plasma_starting_stacks": {
        "condition": "plasma",
        "kind": "stack_consume",
        "role": "consume",
        "slot": "W",
    },
    "poison_stacks": {
        "condition": "poison",
        "kind": "stack_consume",
        "role": "consume",
        "slot": "E",
    },
    "pyromania_stacks": {"role": "self_state", "slot": "P"},
    "q_active": {"role": "self_state", "slot": "Q"},
    "q_armor_reduction": {"role": "self_state", "slot": "Q"},
    "q_armor_shred": {"role": "self_state", "slot": "Q"},
    "q_attacks_landed": {"role": "self_state", "slot": "Q"},
    "q_awaken": {"role": "self_state", "slot": "Q"},
    "q_beams": {"role": "self_state", "slot": "Q"},
    "q_bounces": {"role": "self_state", "slot": "Q"},
    "q_casts": {"role": "self_state", "slot": "Q"},
    "q_center": {"role": "irrelevant", "slot": "Q"},
    "q_charge": {"role": "self_state", "slot": "Q"},
    "q_charge_fraction": {"role": "self_state", "slot": "Q"},
    "q_charge_seconds": {"role": "self_state", "slot": "Q"},
    "q_consume": {
        "condition": "sigil",
        "kind": "mark_applier",
        "role": "setup",
        "slot": "Q",
    },
    "q_dash_distance": {"role": "self_state", "slot": "Q"},
    "q_discharge": {"role": "self_state", "slot": "Q"},
    "q_empowered_attacks": {"role": "self_state", "slot": "Q"},
    "q_evolved": {"role": "irrelevant", "slot": "Q"},
    "q_execute": {
        "condition": "execute",
        "kind": "execute",
        "role": "execute",
        "slot": "Q",
    },
    "q_explosions": {"role": "self_state", "slot": "Q"},
    "q_first_attack_delay": {"role": "self_state", "slot": "Q"},
    "q_focus_stacks": {"role": "self_state", "slot": "Q"},
    "q_form": {"role": "irrelevant", "slot": "Q"},
    "q_fully_fermented": {"role": "irrelevant", "slot": "Q"},
    "q_gathering_storm": {"role": "self_state", "slot": "Q"},
    "q_ground": {"role": "irrelevant", "slot": "Q"},
    "q_isolated": {"role": "self_state", "slot": "Q"},
    "q_mantra": {"role": "self_state", "slot": "Q"},
    "q_marked_target": {
        "condition": "mark",
        "kind": "mark_consume",
        "role": "consume",
        "slot": "Q",
    },
    "q_missing_health": {
        "condition": "execute",
        "kind": "execute",
        "role": "execute",
        "slot": "Q",
    },
    "q_mortal_will": {"role": "self_state", "slot": "Q"},
    "q_outer_edge": {"role": "irrelevant", "slot": "Q"},
    "q_passive_stacks": {"role": "self_state", "slot": "Q"},
    "q_pickup": {"role": "irrelevant", "slot": "Q"},
    "q_pull": {"role": "irrelevant", "slot": "Q"},
    "q_recast": {"role": "self_state", "slot": "Q"},
    "q_recasts": {"role": "self_state", "slot": "Q"},
    "q_second_bomb": {"role": "self_state", "slot": "Q"},
    "q_shred": {"role": "self_state", "slot": "Q"},
    "q_snippy_stacks": {"role": "self_state", "slot": "Q"},
    "q_spirit_blade_hit": {"role": "irrelevant", "slot": "Q"},
    "q_stacks": {"role": "self_state", "slot": "Q"},
    "q_target_below_half": {"role": "self_state", "slot": "Q"},
    "q_target_deaths": {"role": "self_state", "slot": "Q"},
    "q_target_distance": {"role": "self_state", "slot": "Q"},
    "q_turret_attacks": {"role": "self_state", "slot": "Q"},
    "q_turrets": {"role": "self_state", "slot": "Q"},
    "q_variant": {"role": "irrelevant", "slot": "Q"},
    "r_arcane_perfection": {"role": "self_state", "slot": "R"},
    "r_big_one_cycle_position": {"role": "self_state", "slot": "R"},
    "r_bolts": {"role": "self_state", "slot": "R"},
    "r_bounces": {"role": "self_state", "slot": "R"},
    "r_casts": {"role": "self_state", "slot": "R"},
    "r_charged": {"role": "irrelevant", "slot": "R"},
    "r_clone_attacks": {"role": "self_state", "slot": "R"},
    "r_daggers": {"role": "self_state", "slot": "R"},
    "r_deaths_daughter": {"role": "irrelevant", "slot": "R"},
    "r_duration": {"role": "self_state", "slot": "R"},
    "r_edge": {"role": "irrelevant", "slot": "R"},
    "r_empowered": {"role": "self_state", "slot": "R"},
    "r_execute_ready": {
        "condition": "execute",
        "kind": "execute",
        "role": "execute",
        "slot": "R",
    },
    "r_fire_at_will": {"role": "irrelevant", "slot": "R"},
    "r_hemoplague_debuff": {
        "condition": "amp",
        "kind": "amp",
        "role": "setup",
        "slot": "R",
    },
    "r_mimic": {"role": "irrelevant", "slot": "R"},
    "r_nearby_champions": {"role": "self_state", "slot": "R"},
    "r_overwhelm_stacks": {
        "condition": "overwhelm",
        "kind": "stack_consume",
        "role": "consume",
        "slot": "R",
    },
    "r_passes": {"role": "self_state", "slot": "R"},
    "r_passive_ready": {"role": "self_state", "slot": "P"},
    "r_secondary_target": {"role": "irrelevant", "slot": "R"},
    "r_shots": {"role": "self_state", "slot": "R"},
    "r_shrooms": {"role": "self_state", "slot": "R"},
    "r_size": {"role": "irrelevant", "slot": "R"},
    "r_spheres": {"role": "self_state", "slot": "R"},
    "r_stacks": {"role": "self_state", "slot": "R"},
    "r_start_distance": {"role": "self_state", "slot": "R"},
    "r_starting_charges": {"role": "self_state", "slot": "R"},
    "r_sweet_spot": {"role": "irrelevant", "slot": "R"},
    "r_target_facing": {"role": "irrelevant", "slot": "R"},
    "r_terrain": {"role": "irrelevant", "slot": "R"},
    "r_ticks": {"role": "self_state", "slot": "R"},
    "r_transcendent": {"role": "self_state", "slot": "R"},
    "r_variant": {"role": "irrelevant", "slot": "R"},
    "r_wake": {"role": "irrelevant", "slot": "R"},
    "r_wall": {"role": "irrelevant", "slot": "R"},
    "relentless_storm_stacks": {"role": "self_state", "slot": "P"},
    "rend_stacks": {
        "condition": "rend",
        "kind": "stack_consume",
        "role": "consume",
        "slot": "E",
    },
    "sapling_empowered": {"role": "irrelevant", "slot": "E"},
    "scalemail_stacks": {"role": "self_state", "slot": "P"},
    "senna_mist_stacks": {"role": "self_state", "slot": "P"},
    "soldier_autos": {"role": "self_state", "slot": "R"},
    "soldier_count": {"role": "self_state", "slot": "R"},
    "soul_nails": {"role": "self_state", "slot": "P"},
    "souls": {"role": "self_state", "slot": "P"},
    "spider_form": {"role": "self_state", "slot": "R"},
    "splinters": {"role": "self_state", "slot": "P"},
    "stardust_stacks": {"role": "self_state", "slot": "P"},
    "starting_hemorrhage_stacks": {"role": "self_state", "slot": "R"},
    "stone_skin_stacks": {"role": "self_state", "slot": "P"},
    "sweetspot": {"role": "irrelevant", "slot": "Q"},
    "target_cursed": {"role": "self_state", "slot": "R"},
    "target_missing_hp_pct": {
        "condition": "execute",
        "kind": "execute",
        "role": "execute",
        "slot": {"Bel'Veth": "E", "Briar": "W", "Varus": "Q", "Warwick": "W"},
    },
    "target_poisoned": {
        "condition": "poison",
        "kind": "dot_consume",
        "role": "consume",
        "slot": "E",
    },
    "tibbers_attacks": {"role": "self_state", "slot": "R"},
    "tibbers_aura_seconds": {"role": "self_state", "slot": "R"},
    "true_form": {"role": "self_state", "slot": "R"},
    "voidling_attacks": {"role": "self_state", "slot": "R"},
    "voidling_count": {"role": "self_state", "slot": "R"},
    "w_active_empower": {"role": "self_state", "slot": "W"},
    "w_attacks": {"role": "self_state", "slot": "W"},
    "w_box_attacks": {"role": "self_state", "slot": "W"},
    "w_card": {"role": "irrelevant", "slot": "W"},
    "w_charge": {"role": "self_state", "slot": "W"},
    "w_charge_seconds": {"role": "self_state", "slot": "W"},
    "w_charmed": {"role": "irrelevant", "slot": "W"},
    "w_charm_triggered": {"role": "irrelevant", "slot": "W"},
    "w_empowered": {"role": "irrelevant", "slot": "W"},
    "w_epicenter": {"role": "irrelevant", "slot": "W"},
    "w_evolved": {"role": "irrelevant", "slot": "W"},
    "w_grit": {"role": "self_state", "slot": "W"},
    # Naafiri W: whether The Call of the Pack's hunt is running.  It is a
    # SELF steroid, so ``self_state`` and NOT ``setup``: the setup role in
    # this table is reserved for target-side conditions (``mark_applier``,
    # ``amp``), and W's ordering edge is already structural rather than
    # inferred — the slot emits a ``stat_buff`` payload keyed
    # ``bonus_attack_damage``, which is in the resolver's
    # ``_DAMAGE_AMP_STAT_KEYS``, so buffs-first derives W -> Q/E/R from the
    # parsed row itself.  A ``consume`` declaration would also have to name
    # ONE ``setup_slot``, which cannot express that the same hunt state
    # gates both W's own AD steroid and P's raised Packmate cap
    # (the classification-notes rule: acknowledge in the receipt, never
    # invent a duplicate edge).
    "w_hunt": {"role": "self_state", "slot": "W"},
    "w_hunters_vigor_stacks": {"role": "self_state", "slot": "W"},
    "w_in_brush": {"role": "irrelevant", "slot": "W"},
    "w_nearby_champions": {"role": "self_state", "slot": "W"},
    "w_outer_cone": {"role": "irrelevant", "slot": "W"},
    "w_passive_ready": {"role": "self_state", "slot": "W"},
    "w_patch_uptime": {"role": "self_state", "slot": "W"},
    "w_recast": {"role": "self_state", "slot": "W"},
    "w_renewal": {"role": "self_state", "slot": "W"},
    "w_rockets": {"role": "self_state", "slot": "W"},
    "w_seconds": {"role": "self_state", "slot": "W"},
    "w_summoner": {"role": "irrelevant", "slot": "W"},
    "w_target_distance": {"role": "self_state", "slot": "W"},
    "w_target_missing_health": {
        "condition": "execute",
        "kind": "execute",
        "role": "execute",
        "slot": "W",
    },
    "w_tether_holds": {"role": "irrelevant", "slot": "W"},
    "overheat_autos": {"role": "self_state", "slot": "P"},
    "w_thorns_autos": {"role": "self_state", "slot": "W"},
    "w_ticks": {"role": "self_state", "slot": "W"},
    "w_traps": {"role": "self_state", "slot": "W"},
    "w_variant": {"role": "irrelevant", "slot": "W"},
    "w_already_shielded": {"role": "self_state", "slot": "W"},
    "w_active": {"role": "self_state", "slot": "W"},
    "w_active_from": {"role": "self_state", "slot": "W"},
    "w_active_seconds": {"role": "self_state", "slot": "W"},
    "w_blocked_skillshots": {"role": "irrelevant", "slot": "W"},
    "w_blocked_event_ids": {"role": "irrelevant", "slot": "W"},
    "w_blocked_sources": {"role": "irrelevant", "slot": "W"},
    "w_mark_detonation": {"role": "irrelevant", "slot": "W"},
    "w_wounded": {
        "condition": "wounded",
        "kind": "mark_consume",
        "role": "consume",
        "slot": "W",
    },
    "wall_contact": {"role": "irrelevant", "slot": "W"},
    "we_hits": {"role": "self_state", "slot": "E"},
}

_ROTATION_ROLES = frozenset(
    {"setup", "consume", "self_state", "execute", "irrelevant", "unsupported"}
)


def get_champion_option_rotation(
    champion_name: str,
) -> dict[str, dict[str, Any] | None]:
    """Return the typed rotation declaration for every declared option.

    The declaration is authoritative at the option's source: a module
    OPTIONS entry may carry an inline ``rotation`` dict; keys without an
    inline declaration fall back to the central classification table.  An
    unclassified key maps to ``None`` — the exhaustiveness contract
    (``tests/test_champion_options.py``) fails when any declared option is
    unclassified, so a rotation receipt can never claim "no detectable
    setup/consume signal" while a semantic option is unclassified.

    Returns:
        ``{option_key: rotation_decl_or_None}`` for the champion's declared
        OPTIONS entries.  An unregistered name returns ``{}``.
    """
    try:
        contract = get_champion_module_contract(champion_name)
    except KeyError:
        return {}
    result: dict[str, dict[str, Any] | None] = {}
    for opt in contract.options:
        key = str(opt.get("key", ""))
        inline = opt.get("rotation")
        if isinstance(inline, dict) and inline.get("role") in _ROTATION_ROLES:
            decl = dict(inline)
        else:
            central = _ROTATION_CLASSIFICATIONS.get(key)
            decl = dict(central) if isinstance(central, dict) else None
        if decl is not None:
            slot = decl.get("slot")
            if isinstance(slot, dict):
                decl["slot"] = slot.get(champion_name)
        result[key] = decl
    return result


def get_champion_module_meta(champion_name: str) -> dict[str, Any]:
    """Return the module-level trust metadata used by the validation layer.

    Extends :func:`get_champion_options_meta` with the structural facts a
    trust label needs: the slot map keys, the contract's five-slot coverage
    (the module's ``MODULE_COVERAGE`` when declared, else derived from its
    ``SLOTS``; ``"modeled"`` / ``"no_damage"`` / ``"out_of_scope"`` per
    slot), and its review status.  ``slots`` is the ordered list of
    SLOTS-map keys the module actually implements.  Unknown champions
    return an empty metadata dict.

    Returns:
        ``{"options": [...], "assumptions": [...], "sources": [...],
        "slots": [...], "coverage": {...}, "review_status": str,
        "registration": str}`` — all JSON-safe.
    """
    try:
        contract = get_champion_module_contract(champion_name)
    except KeyError:
        return {
            "options": [],
            "assumptions": [],
            "sources": [],
            "slots": [],
            "coverage": {},
            "review_status": "unregistered",
            "registration": "unregistered",
        }
    result = get_champion_options_meta(champion_name)
    result["slots"] = list(contract.slots)
    result["coverage"] = dict(contract.coverage)
    result["review_status"] = contract.review_status
    result["registration"] = contract.review_status
    return result


def get_custom_cast_order_unavailable_reason(champion_name: str) -> str | None:
    """Explain why a module's certified cast sequence cannot be reordered."""
    try:
        module = get_champion_module_contract(champion_name).module
    except KeyError:
        return None
    reason = getattr(module, "CUSTOM_CAST_ORDER_UNAVAILABLE_REASON", None)
    return str(reason) if reason else None


def champion_options_meta_map() -> dict[str, dict[str, list]]:
    """Option, assumption, and source metadata for every champion with any.

    The shape /api/config serves: every cached champion can expose its
    options, assumptions, and source receipts.
    """
    result = {}
    for name in _CHAMPION_MODULES:
        meta = get_champion_options_meta(name)
        if meta["options"] or meta["assumptions"] or meta["sources"]:
            result[name] = meta
    return result


def registered_champion_names() -> list[str]:
    """Sorted display names of every champion with a validated module."""
    return sorted(_CHAMPION_MODULES)


def engine_registration_kind(champion_name: str) -> str | None:
    """The public registration kind of one module; ``None`` when unknown."""
    if champion_name not in _CHAMPION_MODULES:
        return None
    return get_champion_module_contract(champion_name).review_status


def is_champion_supported(champion_name: str) -> bool:
    """Whether this champion has a dedicated module with ability damage."""
    return champion_name in _CHAMPION_MODULES
