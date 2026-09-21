"""Champion ability registry.

Every champion in the pinned Wiki cache has a dedicated importable module.
The reviewed modules are explicit, source-pinned packet modules for the
entire roster; there is no generated or generic middle lane and no runtime
archetype registration in the reviewed surface.
"""

from collections.abc import Callable
from types import ModuleType
from typing import Any

from ..cast_dependency import CastDependency
from ..stat_conversion import BonusHealthConversion
from . import (
    aatrox,
    ahri,
    akali,
    akshan,
    alistar,
    ambessa,
    amumu,
    anivia,
    annie,
    aphelios,
    ashe,
    aurelion_sol,
    aurora,
    azir,
    bard,
    belveth,
    blitzcrank,
    brand,
    braum,
    briar,
    caitlyn,
    camille,
    cassiopeia,
    chogath,
    corki,
    darius,
    diana,
    dr_mundo,
    draven,
    ekko,
    elise,
    evelynn,
    ezreal,
    fiddlesticks,
    fiora,
    fizz,
    galio,
    gangplank,
    garen,
    gnar,
    gragas,
    graves,
    gwen,
    hecarim,
    heimerdinger,
    hwei,
    illaoi,
    irelia,
    ivern,
    janna,
    jarvan_iv,
    jax,
    jayce,
    jhin,
    jinx,
    kaisa,
    kalista,
    karma,
    karthus,
    kassadin,
    katarina,
    kayle,
    kayn,
    kennen,
    khazix,
    kindred,
    kled,
    kogmaw,
    ksante,
    leblanc,
    lee_sin,
    leona,
    lillia,
    lissandra,
    locke,
    lucian,
    lulu,
    lux,
    malphite,
    malzahar,
    maokai,
    master_yi,
    mel,
    milio,
    miss_fortune,
    mordekaiser,
    morgana,
    naafiri,
    nami,
    nasus,
    nautilus,
    neeko,
    nidalee,
    nilah,
    nocturne,
    nunu_willump,
    olaf,
    orianna,
    ornn,
    pantheon,
    poppy,
    pyke,
    qiyana,
    quinn,
    rakan,
    rammus,
    reksai,
    rell,
    renata_glasc,
    renekton,
    rengar,
    riven,
    rumble,
    ryze,
    samira,
    sejuani,
    senna,
    seraphine,
    sett,
    shaco,
    shen,
    shyvana,
    singed,
    sion,
    sivir,
    skarner,
    smolder,
    sona,
    soraka,
    swain,
    sylas,
    syndra,
    tahm_kench,
    taliyah,
    talon,
    taric,
    teemo,
    thresh,
    tristana,
    trundle,
    tryndamere,
    twisted_fate,
    twitch,
    udyr,
    urgot,
    varus,
    vayne,
    veigar,
    velkoz,
    vex,
    vi,
    viego,
    viktor,
    vladimir,
    volibear,
    warwick,
    wukong,
    xayah,
    xerath,
    xin_zhao,
    yasuo,
    yone,
    yorick,
    yunara,
    yuumi,
    zaahen,
    zac,
    zed,
    zeri,
    ziggs,
    zilean,
    zoe,
    zyra,
)
from .contract_vocabulary import ChampionModuleContract
from .inputs import use_options_rows
from .module_contract import contract_from_module

# Map display name -> module name within this package.  This is the single
# explicit roster manifest: every cached champion has a reviewed module and
# no champion is routed through an archetype parser at runtime.
_CHAMPION_MODULES: dict[str, ModuleType] = {
    "Aatrox": aatrox,
    "Ahri": ahri,
    "Akali": akali,
    "Akshan": akshan,
    "Alistar": alistar,
    "Ambessa": ambessa,
    "Amumu": amumu,
    "Aphelios": aphelios,
    "Anivia": anivia,
    "Annie": annie,
    "Ashe": ashe,
    "Aurelion Sol": aurelion_sol,
    "Aurora": aurora,
    "Azir": azir,
    "Bard": bard,
    "Bel'Veth": belveth,
    "Blitzcrank": blitzcrank,
    "Brand": brand,
    "Braum": braum,
    "Briar": briar,
    "Caitlyn": caitlyn,
    "Camille": camille,
    "Cassiopeia": cassiopeia,
    "Cho'Gath": chogath,
    "Corki": corki,
    "Darius": darius,
    "Diana": diana,
    "Dr. Mundo": dr_mundo,
    "Draven": draven,
    "Ezreal": ezreal,
    "Ekko": ekko,
    "Elise": elise,
    "Evelynn": evelynn,
    "Fiddlesticks": fiddlesticks,
    "Fiora": fiora,
    "Fizz": fizz,
    "Gangplank": gangplank,
    "Garen": garen,
    "Gragas": gragas,
    "Graves": graves,
    "Gwen": gwen,
    "Hecarim": hecarim,
    "Heimerdinger": heimerdinger,
    "Hwei": hwei,
    "Illaoi": illaoi,
    "Irelia": irelia,
    "Ivern": ivern,
    "Janna": janna,
    "Jax": jax,
    "Jhin": jhin,
    "K'Sante": ksante,
    "Karma": karma,
    "Kassadin": kassadin,
    "Katarina": katarina,
    "Kayle": kayle,
    "Kayn": kayn,
    "Kennen": kennen,
    "Kha'Zix": khazix,
    "Kindred": kindred,
    "Kled": kled,
    "LeBlanc": leblanc,
    "Lee Sin": lee_sin,
    "Leona": leona,
    "Lillia": lillia,
    "Locke": locke,
    "Lucian": lucian,
    "Lulu": lulu,
    "Lux": lux,
    "Malphite": malphite,
    "Malzahar": malzahar,
    "Maokai": maokai,
    "Master Yi": master_yi,
    "Mel": mel,
    "Milio": milio,
    "Miss Fortune": miss_fortune,
    "Mordekaiser": mordekaiser,
    "Morgana": morgana,
    "Naafiri": naafiri,
    "Nami": nami,
    "Nasus": nasus,
    "Nautilus": nautilus,
    "Neeko": neeko,
    "Nidalee": nidalee,
    "Nilah": nilah,
    "Nocturne": nocturne,
    "Nunu & Willump": nunu_willump,
    "Olaf": olaf,
    "Pantheon": pantheon,
    "Poppy": poppy,
    "Pyke": pyke,
    "Quinn": quinn,
    "Rammus": rammus,
    "Rek'Sai": reksai,
    "Rell": rell,
    "Renata Glasc": renata_glasc,
    "Renekton": renekton,
    "Rengar": rengar,
    "Riven": riven,
    "Rumble": rumble,
    "Ryze": ryze,
    "Samira": samira,
    "Sejuani": sejuani,
    "Senna": senna,
    "Seraphine": seraphine,
    "Sett": sett,
    "Shaco": shaco,
    "Singed": singed,
    "Sion": sion,
    "Sivir": sivir,
    "Skarner": skarner,
    "Smolder": smolder,
    "Sona": sona,
    "Swain": swain,
    "Sylas": sylas,
    "Talon": talon,
    "Taric": taric,
    "Teemo": teemo,
    "Thresh": thresh,
    "Tristana": tristana,
    "Trundle": trundle,
    "Tryndamere": tryndamere,
    "Twisted Fate": twisted_fate,
    "Twitch": twitch,
    "Udyr": udyr,
    "Urgot": urgot,
    "Varus": varus,
    "Veigar": veigar,
    "Vel'Koz": velkoz,
    "Vex": vex,
    "Viego": viego,
    "Viktor": viktor,
    "Vladimir": vladimir,
    "Volibear": volibear,
    "Warwick": warwick,
    "Xayah": xayah,
    "Xerath": xerath,
    "Xin Zhao": xin_zhao,
    "Yasuo": yasuo,
    "Yone": yone,
    "Yorick": yorick,
    "Yunara": yunara,
    "Yuumi": yuumi,
    "Zaahen": zaahen,
    "Zac": zac,
    "Zed": zed,
    "Zeri": zeri,
    "Zilean": zilean,
    "Zoe": zoe,
    "Zyra": zyra,
    "Galio": galio,
    "Gnar": gnar,
    "Jarvan IV": jarvan_iv,
    "Jayce": jayce,
    "Jinx": jinx,
    "Kalista": kalista,
    "Kai'Sa": kaisa,
    "Karthus": karthus,
    "Kog'Maw": kogmaw,
    "Lissandra": lissandra,
    "Orianna": orianna,
    "Ornn": ornn,
    "Qiyana": qiyana,
    "Rakan": rakan,
    "Shen": shen,
    "Soraka": soraka,
    "Syndra": syndra,
    "Shyvana": shyvana,
    "Taliyah": taliyah,
    "Tahm Kench": tahm_kench,
    "Vayne": vayne,
    "Vi": vi,
    "Wukong": wukong,
    "Ziggs": ziggs,
}

# Validated contracts: the coupled optimizer dispatches thousands of parses
# per request, so a module is validated once, not per lookup.
_MODULE_CONTRACTS: dict[str, ChampionModuleContract] = {}


def module_basename(module: ModuleType) -> str:
    """A champion module's own name inside this package (``"aurelion_sol"``)."""
    return module.__name__.rpartition(".")[2]


def get_champion_module_contract(champion_name: str) -> ChampionModuleContract:
    """Import and validate the authoritative module for *champion_name*."""

    module = _CHAMPION_MODULES.get(champion_name)
    if module is None:
        raise KeyError(f"no registered champion module for {champion_name!r}")
    cached = _MODULE_CONTRACTS.get(champion_name)
    if cached is not None and cached.module is module:
        return cached
    contract = contract_from_module(champion_name, module_basename(module), module)
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
    *,
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
    *,
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
    """The module's ``CAST_ORDER`` where the engine's default misrepresents the kit."""
    return _optional_declaration(champion_name, "CAST_ORDER", list)


def _module_declaration(champion_name: str, attribute: str) -> Any:
    """A module's optional declaration; None with no such module or attribute."""
    try:
        return getattr(
            get_champion_module_contract(champion_name).module, attribute, None
        )
    except KeyError:
        return None


def _optional_declaration[Declaration](
    champion_name: str, attribute: str, coerce: Callable[[Any], Declaration]
) -> Declaration | None:
    """A module's optional declaration read through *coerce*; None when it is empty."""
    declared = _module_declaration(champion_name, attribute)
    return coerce(declared) if declared else None


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
# Typed rotation semantics, declared on the OPTIONS row that owns them
#
# The rotation resolver builds its setup/consume edges FROM these
# declarations, and there is no second hand-maintained vocabulary in
# rotation_resolver.py.  An option row's ``rotation`` dict is the one
# home; an option without one is a contract failure
# (tests/test_champion_options.py).
#
# Fields:
#   role       setup | consume | self_state | execute | irrelevant |
#              unsupported  (closed six-role vocabulary)
#   slot       the cast slot the option belongs to ("Q"/"W"/"E"/"R"/"P")
#              or "auto_stream" for auto/on-hit-stream inputs
#   condition  free token used in the receipt cite (consume/setup/execute)
#   kind       edge-pairing behavior for the corpus fallback:
#              dot_consume | stack_consume | mark_consume | mark_applier |
#              execute | amp  (consume/setup/execute only)
#   setup_slot (consume/execute only) the slot whose setup is consumed —
#              produces the direct ``setup_slot -> slot`` edge without
#              depending on applier-corpus phrases.
#
# Classification notes for the bulk (self_state/irrelevant): cross-slot
# semantics of those options (shreds, marks, executes, recasts) are
# already detected through parsed atoms (``target_debuff``,
# ``post_hit_proc``, ``recast_of``, ...), so their classification is
# receipt-only: they are acknowledged in the rotation receipt without
# inventing duplicate edges.
# ─────────────────────────────────────────────────────────────────────────

_ROTATION_ROLES = frozenset(
    {"setup", "consume", "self_state", "execute", "irrelevant", "unsupported"}
)


def get_champion_option_rotation(
    champion_name: str,
) -> dict[str, dict[str, Any] | None]:
    """Return the typed rotation declaration of every declared option.

    The declaration is authoritative at the option's source, the module's
    OPTIONS row.  A row with no ``rotation``, or with a role outside the
    vocabulary, maps to ``None``, which the exhaustiveness contract
    (``tests/test_champion_options.py``) fails on: a rotation receipt can
    never claim "no detectable setup/consume signal" while a semantic
    option is unclassified.  An unregistered name returns ``{}``.
    """
    try:
        contract = get_champion_module_contract(champion_name)
    except KeyError:
        return {}
    result: dict[str, dict[str, Any] | None] = {}
    for opt in contract.options:
        decl = opt.get("rotation")
        classified = isinstance(decl, dict) and decl.get("role") in _ROTATION_ROLES
        result[str(opt.get("key", ""))] = dict(decl) if classified else None
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


def get_custom_cast_order_refusal(champion_name: str) -> str | None:
    """Explain why a module's certified cast sequence cannot be reordered."""
    return _optional_declaration(champion_name, "CUSTOM_CAST_ORDER_REFUSAL", str)


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


def declared_options_rows(champion_name: str) -> list[dict[str, Any]]:
    """The OPTIONS rows one champion's module declares, read by ``inputs``."""
    return get_champion_options_meta(champion_name)["options"]


# ``inputs`` is a leaf of this tree, so the registry hands it this reader
# rather than being imported back.  A contract is validated when a formula
# asks for a default, not here.
use_options_rows(declared_options_rows)
