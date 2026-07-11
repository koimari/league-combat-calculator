"""Fight damage engine — orchestrates all damage sources over a fight duration.

This module is champion-agnostic. Champion ability data (including cooldowns)
is provided by the caller via the ``ability_damages`` dict. Item effects are
delegated to ``item_effects``.

Ability On-Hit Framework
~~~~~~~~~~~~~~~~~~~~~~~~
Champions with abilities that augment auto attacks can participate in the
on-hit system via two mechanisms:

**Case 1 — Stack acceleration** (e.g. Vayne W Silver Bolts):
    Abilities that build stacks per auto and proc on reaching N stacks.
    Phantom hits grant an extra stack per proc. The ``phantom_hit_autos``
    set is returned in the fight result so champion-specific calculators
    can model accelerated stack procs. The champion module is responsible
    for counting stacks and determining when procs happen.

**Case 2 — On-hit damage** (e.g. Viego passive % health on auto):
    Abilities that add flat/scaling damage per auto attack. These are
    registered by adding an ``on_hit`` key to the ability's entry in
    ``ability_damages``::

        ability_damages["passive"] = {
            "name": "Blade of the Ruined Blade",
            "on_hit": {
                "name": "Viego Passive (on-hit)",
                "damage_per_hit": 42.0,
                "damage_type": "physical",
            },
        }

    The fight engine processes these alongside item on-hits, and phantom
    hits automatically double them.
"""

import math
import random
from collections import Counter
from typing import Any

from . import item_effects
from .resistance import (
    apply_resistance,
    apply_magic_penetration,
    apply_armor_penetration,
)
from .champions.common import effective_cooldown


def _calculate_phantom_hits(
    num_auto_attacks: int,
    item_names: list[str],
) -> tuple[int, set[int]]:
    """Calculate Guinsoo's Rageblade phantom hit count and which autos trigger.

    Rageblade grants stacking attack speed per auto (Seething Strike).
    The 4th auto maxes Seething AND starts Phantom stacking. At 2
    Phantom stacks, the next auto consumes them to trigger a Phantom Hit
    that applies all on-hit effects an additional time.

    Sequence: 5 autos to build up, 6th triggers, then every 3rd after
    (6, 9, 12, 15, 18, ...).

    Args:
        num_auto_attacks: Total auto attacks in the fight.
        item_names: List of item names the champion has.

    Returns:
        Tuple of (phantom_hit_count, set of 0-indexed auto numbers that
        trigger phantom hits).
    """
    has_rageblade = "Guinsoo's Rageblade" in item_names
    if not has_rageblade or num_auto_attacks < 6:
        return 0, set()

    effect = item_effects.ITEM_EFFECTS["Guinsoo's Rageblade"]
    stacking_autos = effect.get("stacking_autos", 5)
    interval = effect.get("phantom_interval", 3)

    phantom_autos: set[int] = set()
    # First phantom hit at auto index = stacking_autos (0-indexed, so 6th auto)
    auto_index = stacking_autos
    while auto_index < num_auto_attacks:
        phantom_autos.add(auto_index)
        auto_index += interval

    return len(phantom_autos), phantom_autos


def _calculate_kraken_procs(
    num_auto_attacks: int,
    phantom_hit_autos: set[int],
    double_on_hit_procs: int = 0,
) -> tuple[int, list[int]]:
    """Simulate Kraken Slayer stacking with phantom hit awareness.

    Kraken Slayer procs every 3rd on-hit application. Phantom hits grant
    an extra stack (not an extra damage proc). Each stack application is
    checked individually, so a phantom hit auto can push stacks to 3 and
    trigger a proc mid-auto.

    Dusk and Dawn double on-hit procs also grant an extra stack each.

    Args:
        num_auto_attacks: Total auto attacks in the fight.
        phantom_hit_autos: Set of 0-indexed autos that trigger phantom hits.
        double_on_hit_procs: Number of Dusk and Dawn double on-hit procs.

    Returns:
        Tuple of (proc_count, list of 0-indexed auto indices where procs
        fire). An auto can have multiple procs if both phantom and double
        on-hit push stacks past 3 on the same auto.
    """
    stacks = 0
    proc_autos: list[int] = []

    # Build a set of auto indices that get a double-on-hit proc.
    # Dusk and Dawn procs happen on the first N autos that have spellblade.
    # For simplicity, assign them to the first N autos.
    double_on_hit_auto_set: set[int] = set()
    if double_on_hit_procs > 0:
        assigned = 0
        for i in range(num_auto_attacks):
            if assigned >= double_on_hit_procs:
                break
            double_on_hit_auto_set.add(i)
            assigned += 1

    for i in range(num_auto_attacks):
        # Normal auto: +1 stack
        stacks += 1
        if stacks >= 3:
            proc_autos.append(i)
            stacks = 0

        # Phantom hit: +1 extra stack
        if i in phantom_hit_autos:
            stacks += 1
            if stacks >= 3:
                proc_autos.append(i)
                stacks = 0

        # Double on-hit: +1 extra stack
        if i in double_on_hit_auto_set:
            stacks += 1
            if stacks >= 3:
                proc_autos.append(i)
                stacks = 0

    return len(proc_autos), proc_autos


def _calculate_hullbreaker_procs(
    num_auto_attacks: int,
    phantom_hit_autos: set[int],
    double_on_hit_procs: int = 0,
    hits_required: int = 5,
) -> tuple[int, list[int]]:
    """Simulate Hullbreaker Skipper stacking with phantom hit awareness.

    Same stacking mechanic as Kraken Slayer: phantom hits and double
    on-hit procs each grant an extra stack (not an extra damage proc).

    Args:
        num_auto_attacks: Total auto attacks in the fight.
        phantom_hit_autos: Set of 0-indexed autos that trigger phantom hits.
        double_on_hit_procs: Number of Dusk and Dawn double on-hit procs.
        hits_required: Stacks needed to proc (default 5).

    Returns:
        Tuple of (proc_count, list of 0-indexed auto indices where procs
        fire).
    """
    stacks = 0
    proc_autos: list[int] = []

    double_on_hit_auto_set: set[int] = set()
    if double_on_hit_procs > 0:
        for i in range(min(double_on_hit_procs, num_auto_attacks)):
            double_on_hit_auto_set.add(i)

    for i in range(num_auto_attacks):
        stacks += 1
        if stacks >= hits_required:
            proc_autos.append(i)
            stacks = 0

        if i in phantom_hit_autos:
            stacks += 1
            if stacks >= hits_required:
                proc_autos.append(i)
                stacks = 0

        if i in double_on_hit_auto_set:
            stacks += 1
            if stacks >= hits_required:
                proc_autos.append(i)
                stacks = 0

    return len(proc_autos), proc_autos


def _simulate_kraken_damage(
    target_health: float,
    num_auto_attacks: int,
    auto_damage_per_hit: float,
    other_on_hit_per_hit: float,
    effective_armor: float,
    is_melee: bool,
    level: int,
    kraken_proc_autos: list[int],
) -> float:
    """Simulate Kraken Slayer damage with decreasing target HP.

    Kraken's bonus damage scales with the target's missing health at
    the time of each proc: ``base * (1 + 0.75 * missing_ratio)``.
    This must be simulated per-auto because each auto (and its on-hit
    effects) reduces target HP, changing the missing ratio for later procs.

    Args:
        target_health: Target's starting (max) health.
        num_auto_attacks: Number of auto attacks in the fight.
        auto_damage_per_hit: Mitigated base auto attack damage per hit.
        other_on_hit_per_hit: Mitigated damage from other on-hit items per hit.
        effective_armor: Target's effective armor after penetration.
        is_melee: Whether the champion is melee.
        level: Champion level.
        kraken_proc_autos: Sorted list of 0-indexed auto indices where Kraken
            procs (from ``_calculate_kraken_procs``).

    Returns:
        Total mitigated Kraken Slayer damage across all procs.
    """
    effect = item_effects.ITEM_EFFECTS.get("Kraken Slayer")
    if not effect or not kraken_proc_autos:
        return 0.0

    # Base damage: flat from levels 1-8, then +5 (melee) or +4 (ranged)
    # per level from level 9 onward.
    scaling_start = effect.get("scaling_start_level", 9)
    if is_melee:
        base = effect["base_melee"]
        per_level = effect["per_level_melee"]
    else:
        base = effect["base_ranged"]
        per_level = effect["per_level_ranged"]

    if level >= scaling_start:
        base += per_level * (level - scaling_start + 1)

    missing_hp_bonus_max = effect.get("missing_hp_bonus_max", 0.75)

    # Convert proc list to a counter: how many procs fire on each auto
    proc_counts: dict[int, int] = Counter(kraken_proc_autos)

    current_hp = target_health
    total_kraken_damage = 0.0

    for i in range(num_auto_attacks):
        procs_this_auto = proc_counts.get(i, 0)

        for _ in range(procs_this_auto):
            missing_ratio = max(0.0, 1.0 - current_hp / target_health)
            bonus_multiplier = 1.0 + missing_hp_bonus_max * missing_ratio
            raw_kraken = base * bonus_multiplier
            mitigated = apply_resistance(raw_kraken, effective_armor)
            total_kraken_damage += mitigated
            current_hp -= mitigated

        # Reduce HP from auto attack + other on-hit damage
        current_hp -= auto_damage_per_hit + other_on_hit_per_hit
        if current_hp < 0:
            current_hp = 0

    return total_kraken_damage


def _simulate_bork_damage(
    target_health: float,
    num_auto_attacks: int,
    auto_damage_per_hit: float,
    other_on_hit_per_hit: float,
    effective_armor: float,
    is_melee: bool,
    phantom_hit_autos: set[int] | None = None,
    double_hit_all: bool = False,
) -> tuple[float, int]:
    """Simulate Blade of the Ruined King damage with decreasing target HP.

    BoRK's passive deals physical damage based on the target's *current*
    health, which drops after every auto attack. Once the modeled HP
    reaches zero, BoRK deals a flat minimum damage instead.

    On phantom hit autos, BoRK procs twice (the normal hit + phantom hit),
    both reducing the target's HP. When ``double_hit_all`` is True (e.g.
    Akshan double shot), BoRK procs an extra time on every auto.

    Args:
        target_health: Target's starting health.
        num_auto_attacks: Number of auto attacks in the fight.
        auto_damage_per_hit: Mitigated base auto attack damage per hit.
        other_on_hit_per_hit: Mitigated damage from non-BoRK on-hit items per hit.
        effective_armor: Target's effective armor after penetration.
        is_melee: Whether the champion is melee.
        phantom_hit_autos: Set of 0-indexed auto numbers that trigger phantom
            hits (from Guinsoo's Rageblade). BoRK procs an extra time on these.
        double_hit_all: If True, BoRK procs an extra time on every auto
            (e.g. Akshan's double shot applies on-hits).

    Returns:
        Tuple of (total mitigated BoRK damage, total BoRK hit count).
    """
    if phantom_hit_autos is None:
        phantom_hit_autos = set()

    bork_effect = item_effects.ITEM_EFFECTS["Blade of the Ruined King"]
    ratio = (
        bork_effect["current_hp_ratio_melee"]
        if is_melee
        else bork_effect["current_hp_ratio_ranged"]
    )
    min_damage = bork_effect.get("min_damage", 5.0)

    current_hp = target_health
    total_bork_damage = 0.0
    total_bork_hits = 0

    for i in range(num_auto_attacks):
        # How many times BoRK procs this auto (1 normally, +1 on phantom hit,
        # +1 if double_hit_all e.g. Akshan double shot)
        procs_this_auto = 1
        if i in phantom_hit_autos:
            procs_this_auto += 1
        if double_hit_all:
            procs_this_auto += 1

        for _ in range(procs_this_auto):
            if current_hp > 0:
                raw_bork = ratio * current_hp
            else:
                raw_bork = min_damage

            mitigated_bork = apply_resistance(raw_bork, effective_armor)
            total_bork_damage += mitigated_bork
            total_bork_hits += 1

            # Reduce target HP by BoRK damage this proc
            current_hp -= mitigated_bork

        # Also reduce HP by auto attack damage and other on-hit damage
        # (other on-hit phantom procs are accounted for in other_on_hit_per_hit
        #  which is already multiplied by the average hits-per-auto)
        on_hit_this_auto = other_on_hit_per_hit
        if i in phantom_hit_autos:
            on_hit_this_auto += other_on_hit_per_hit  # phantom extra proc
        current_hp -= auto_damage_per_hit + on_hit_this_auto
        if current_hp < 0:
            current_hp = 0

    return total_bork_damage, total_bork_hits


def _calculate_shadowflame_bonus(
    breakdown: dict[str, Any],
    ability_damages: dict[str, dict[str, Any]],
    target_health: float,
    cast_order: list[str] | None = None,
) -> float:
    """Calculate bonus damage from Shadowflame's Cinderbloom passive.

    Simulates damage dealt in ability-cast order. When the target's
    modeled HP drops below 40% maximum health, subsequent magic and
    true damage instances deal 120% damage (20% bonus).

    Args:
        breakdown: Current damage breakdown dict.
        ability_damages: Parsed ability data with damage types.
        target_health: Target's maximum health.
        cast_order: Ability cast order (e.g., ["E", "Q", "W", "R"]).

    Returns:
        Total bonus damage from Shadowflame crits.
    """
    if cast_order is None:
        cast_order = ["Q", "Q2", "W", "E", "R"]
    effect = item_effects.ITEM_EFFECTS.get("Shadowflame")
    if not effect:
        return 0.0

    threshold_hp = target_health * effect["health_threshold"]
    crit_bonus = effect["crit_multiplier"] - 1.0
    current_hp = target_health
    total_bonus = 0.0

    # Build events: (damage_amount, is_magic_or_true)
    events: list[tuple[float, bool]] = []

    # 1. Abilities in cast order
    for key in cast_order:
        if key not in breakdown:
            continue
        entry = breakdown[key]
        damage = entry["total_damage"]
        dtype = entry.get("damage_type", "magic")

        if dtype == "mixed" and key in ability_damages:
            # Split into magic (mitigated) and true portions
            casts = entry.get("casts", 1)
            true_per_cast = ability_damages[key].get("true_damage", 0)
            total_true = true_per_cast * casts
            magic_portion = damage - total_true
            events.append((magic_portion, True))
            events.append((total_true, True))
        elif dtype in ("magic", "true"):
            # R with multiple dashes: split into individual events
            if key == "R" and ability_damages.get("R", {}).get("total_casts", 1) > 1:
                total_dashes = ability_damages["R"]["total_casts"]
                casts = entry.get("casts", 1)
                per_event = damage / (total_dashes * casts)
                for _ in range(total_dashes * casts):
                    events.append((per_event, True))
            else:
                events.append((damage, True))
        else:
            events.append((damage, False))

    # 2. Auto attacks (physical, never crits from Shadowflame)
    auto = breakdown.get("auto_attacks")
    if auto and auto["total_damage"] > 0:
        events.append((auto["total_damage"], False))

    # 3. Item effect damage (burns, procs, on-hits, etc.)
    skip_keys = {"Q", "W", "E", "R", "auto_attacks", "damage_amplification", "execute"}
    for key, entry in breakdown.items():
        if key in skip_keys:
            continue
        damage = entry.get("total_damage", 0)
        if damage <= 0:
            continue
        dtype = entry.get("damage_type", "")
        events.append((damage, dtype in ("magic", "true")))

    # 4. Simulate damage order, tracking target HP
    for damage, is_crittable in events:
        if is_crittable and current_hp < threshold_hp:
            total_bonus += damage * crit_bonus
        current_hp -= damage

    return total_bonus


def _navori_effective_cd(
    base_cd: float,
    autos_per_second: float,
    refund_percent: float,
) -> float:
    """Compute effective cooldown with Navori Flickerblade CD refund.

    The cooldown ticks down in real time (1 second per 1 second).  Each
    auto attack that lands reduces the *remaining* cooldown by
    ``refund_percent`` (e.g. 15%).  We simulate this step-by-step:

    Example (7s CD, 1 auto/sec, 15% refund)::

        t=0  Cast, 7s remaining
        t=1  Auto → remaining = (7-1) * 0.85 = 5.10
        t=2  Auto → remaining = (5.10-1) * 0.85 = 3.485
        t=3  Auto → remaining = (3.485-1) * 0.85 = 2.112
        t=4  Auto → remaining = (2.112-1) * 0.85 = 0.945
        t=5  Auto → remaining ≤ 0, ability ready
        Effective CD ≈ 5.0s (down from 7.0s)

    Args:
        base_cd: Cooldown after ability haste (seconds).
        autos_per_second: Effective auto-attack rate (attack_speed * uptime).
        refund_percent: Fraction of remaining CD refunded per auto (0.15).

    Returns:
        Reduced effective cooldown in seconds.
    """
    if base_cd <= 0 or autos_per_second <= 0 or refund_percent <= 0:
        return base_cd

    retain = 1.0 - refund_percent  # 0.85 for 15% refund
    auto_interval = 1.0 / autos_per_second
    remaining = base_cd
    elapsed = 0.0

    # Simulate auto attacks landing at regular intervals
    next_auto = auto_interval
    while remaining > 0:
        if next_auto <= remaining:
            # Time passes until auto lands, then refund
            elapsed += next_auto
            remaining -= next_auto
            remaining *= retain
            next_auto = auto_interval
        else:
            # No more autos before CD expires — just wait it out
            elapsed += remaining
            remaining = 0.0

    return elapsed


def calculate_fight_damage(
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    target_health: float,
    target_armor: float,
    target_magic_resistance: float,
    fight_duration_seconds: float,
    auto_attack_uptime: float = 0.0,
    ability_haste: float = 0.0,
    items: list[dict[str, Any]] | None = None,
    one_rotation: bool = False,
    include_actives: bool = True,
    cast_order: list[str] | None = None,
    auto_attacks_only: bool = False,
    target_bonus_health: float = 0.0,
    deterministic: bool = False,
) -> dict[str, Any]:
    """Calculate total damage dealt over a fight duration.

    In time-based mode, abilities recast when their cooldown expires within
    the fight duration. In one-rotation mode, each ability is cast exactly
    once (fight_duration still matters for burns/DoTs/procs).

    Args:
        champion_stats: Calculated champion stats dictionary.
        ability_damages: Parsed ability damage dictionary.
        target_health: Target's total maximum health (base + bonus).
        target_armor: Target's armor.
        target_magic_resistance: Target's magic resistance.
        fight_duration_seconds: Duration of the fight in seconds.
        auto_attack_uptime: Fraction of time spent auto-attacking (0.0-1.0).
        ability_haste: Total ability haste from items.
        items: List of item data for checking passives.
        one_rotation: If True, each basic ability is cast exactly once.
        include_actives: Whether to include item active damage.
        cast_order: Ability cast order (e.g., ["E", "Q", "W", "R"]).
            Defaults to ["Q", "W", "E", "R"].
        auto_attacks_only: If True, skip all cast abilities (Q/W/E/R casts
            = 0) but still process ability on-hit effects (passives that
            augment auto attacks, e.g. Vayne W, Viego passive).
        target_bonus_health: Target's bonus health from items (used for
            Lord Dominik's Regards Giant Slayer amp).

    Returns:
        Dictionary with damage breakdown and total.
    """
    if cast_order is None:
        cast_order = ["Q", "Q2", "W", "E", "R"]
    if items is None:
        items = []

    is_melee = champion_stats.get("is_melee", True)
    level = int(champion_stats.get("level", 1))

    # ── Step 1: Calculate effective resistances ───────────────────────────
    magic_pen_flat = champion_stats.get("magic_penetration_flat", 0.0)
    magic_pen_percent = champion_stats.get("magic_penetration_percent", 0.0) / 100.0

    # Malignance MR reduction only activates on R cast, so abilities before
    # R in the cast_order use base MR.  We compute both effective values and
    # track which one to use per-ability in the cast loop.
    malignance_mr_reduction = 0.0
    for item in items:
        effect = item_effects.ITEM_EFFECTS.get(item.get("name", ""), {})
        if effect.get("type") == "ult_proc" and "R" in ability_damages:
            malignance_mr_reduction += effect.get("mr_reduction", 0)

    base_mr = max(target_magic_resistance, 0)
    reduced_mr = max(target_magic_resistance - malignance_mr_reduction, 0)

    # Stacking MR reduction (Bloodletter's Curse Vile Decay)
    mr_reduction_effect = item_effects.get_stacking_mr_reduction(items)

    effective_mr_pre_ult = apply_magic_penetration(
        base_mr, magic_pen_flat, magic_pen_percent
    )
    effective_mr_post_ult = apply_magic_penetration(
        reduced_mr, magic_pen_flat, magic_pen_percent
    )
    # For non-ability damage (items, burns) that occurs throughout the fight,
    # use the post-ult MR since most of the fight has Hatefog active.
    effective_mr = effective_mr_post_ult

    # Armor penetration: percent pen + lethality (flat)
    armor_pen_percent = champion_stats.get("armor_penetration_percent", 0.0) / 100.0
    flat_armor_pen = champion_stats.get("flat_armor_penetration", 0.0)

    # Black Cleaver armor reduction (applied before penetration)
    attack_speed = champion_stats["attack_speed"]
    as_ratio = champion_stats.get("attack_speed_ratio", 0.625)

    # ── Ultimate-triggered AS buffs (Fiendhunter Bolts) ──────
    # NOTE: Hexplate 50% bonus AS is now baked into champion stats (stats.py)
    item_name_list = [i.get("name", "") for i in items]
    has_hexplate = "Experimental Hexplate" in item_name_list
    has_fiendhunter = "Fiendhunter Bolts" in item_name_list
    empowered_autos = 0  # Fiendhunter: count of empowered auto attacks
    normal_autos = 0  # Non-empowered auto attacks

    if has_fiendhunter and auto_attack_uptime > 0:
        buff_effect = item_effects.ITEM_EFFECTS.get("Fiendhunter Bolts")
        bonus_as_pct = buff_effect["bonus_attack_speed_percent"]
        buffed_as = attack_speed + as_ratio * (bonus_as_pct / 100.0)

        # Fiendhunter: 3 empowered autos at buffed AS, then normal AS
        max_empowered = buff_effect["empowered_auto_count"]
        buff_dur = min(buff_effect["duration"], fight_duration_seconds)
        possible_in_window = math.floor(buffed_as * buff_dur * auto_attack_uptime)
        empowered_autos = min(max_empowered, possible_in_window)
        if empowered_autos > 0 and buffed_as > 0:
            time_for_empowered = empowered_autos / (buffed_as * auto_attack_uptime)
        else:
            time_for_empowered = 0.0
        remaining_dur = fight_duration_seconds - time_for_empowered
        normal_autos = math.floor(
            attack_speed * max(0, remaining_dur) * auto_attack_uptime
        )
        num_auto_attacks = empowered_autos + normal_autos
    else:
        num_auto_attacks = math.floor(
            attack_speed * fight_duration_seconds * auto_attack_uptime
        )
    # Terminus Juxtaposition: stacking armor/magic pen every other auto.
    # The pen is displayed in champion stats at max stacks, but in the fight
    # engine we compute a weighted average pen across all autos (like Black
    # Cleaver) since stacks ramp up: 0%, 10%, 10%, 20%, 20%, 30%, 30%...
    # Terminus pen only applies to auto attacks, NOT abilities.
    # We strip the max-stack pen from stats for ability calculations, and
    # compute separate auto-attack pen values with the weighted average.
    has_terminus = "Terminus" in item_name_list
    # Pen values for abilities (no Terminus pen)
    ability_armor_pen_percent = armor_pen_percent
    ability_magic_pen_percent = magic_pen_percent
    # Pen values for auto attacks (with Terminus average pen)
    auto_armor_pen_percent = armor_pen_percent
    auto_magic_pen_percent = magic_pen_percent
    if has_terminus:
        terminus_avg_pen = item_effects.get_terminus_pen_stacks(num_auto_attacks)
        terminus_effect = item_effects.ITEM_EFFECTS.get("Terminus", {})
        terminus_stat_pen = terminus_effect.get(
            "dark_pen_per_stack", 0.10
        ) * terminus_effect.get("dark_max_stacks", 3)
        # Strip max-stack pen for abilities (Terminus pen doesn't apply)
        ability_armor_pen_percent = max(0.0, armor_pen_percent - terminus_stat_pen)
        ability_magic_pen_percent = max(0.0, magic_pen_percent - terminus_stat_pen)
        # Strip max-stack pen, then add weighted average for autos
        auto_armor_pen_percent = max(0.0, armor_pen_percent - terminus_stat_pen)
        auto_magic_pen_percent = max(0.0, magic_pen_percent - terminus_stat_pen)
        if terminus_avg_pen > 0:
            auto_armor_pen_percent = 1.0 - (1.0 - auto_armor_pen_percent) * (
                1.0 - terminus_avg_pen
            )
            auto_magic_pen_percent = 1.0 - (1.0 - auto_magic_pen_percent) * (
                1.0 - terminus_avg_pen
            )
    # Recompute effective MR for abilities (without Terminus pen)
    effective_mr_pre_ult = apply_magic_penetration(
        base_mr, magic_pen_flat, ability_magic_pen_percent
    )
    effective_mr_post_ult = apply_magic_penetration(
        reduced_mr, magic_pen_flat, ability_magic_pen_percent
    )
    effective_mr = effective_mr_post_ult

    bc_reduction = item_effects.get_armor_reduction(
        items, fight_duration_seconds, num_auto_attacks
    )
    reduced_armor = target_armor * (1.0 - bc_reduction)

    # Use ability-specific armor pen (no Terminus) for ability damage.
    # Auto-attack armor pen (with Terminus average) is applied after Step 2.
    effective_armor = apply_armor_penetration(
        reduced_armor, flat_armor_pen, ability_armor_pen_percent
    )

    # Abyssal Mask magic damage amplifier
    magic_amp = item_effects.get_magic_damage_amplifier(items)

    # Ability-specific damage amplifier (Actualizer)
    ability_amp = item_effects.get_ability_damage_amplifier(
        items, champion_stats, include_actives
    )

    # Basic (auto attack) damage amplifier (Hexoptics C44 Magnification)
    basic_amp = item_effects.get_basic_damage_amplifier(items)

    # Horizon Focus Hypershot: 10% damage amp after first ability triggers it
    hypershot_amp = item_effects.get_hypershot_amplifier(items)

    # ── Stat buffs from abilities (e.g. Aatrox R bonus AD) ───────────────
    for ability_info in ability_damages.values():
        stat_buff = ability_info.get("stat_buff")
        if stat_buff:
            for stat_key, buff_value in stat_buff.items():
                champion_stats[stat_key] = (
                    champion_stats.get(stat_key, 0.0) + buff_value
                )
            # Recalculate attack_damage if bonus_attack_damage was buffed
            if "bonus_attack_damage" in stat_buff:
                champion_stats["attack_damage"] = champion_stats.get(
                    "base_attack_damage", 0.0
                ) + champion_stats.get("bonus_attack_damage", 0.0)
            # Recalculate magic penetration if it was buffed
            if "magic_penetration_percent" in stat_buff:
                magic_pen_percent = (
                    champion_stats.get("magic_penetration_percent", 0.0) / 100.0
                )
                # Recompute ability/auto pen variants with new base
                ability_magic_pen_percent = magic_pen_percent
                auto_magic_pen_percent = magic_pen_percent
                if has_terminus:
                    ability_magic_pen_percent = max(
                        0.0, magic_pen_percent - terminus_stat_pen
                    )
                    auto_magic_pen_percent = max(
                        0.0, magic_pen_percent - terminus_stat_pen
                    )
                    if terminus_avg_pen > 0:
                        auto_magic_pen_percent = 1.0 - (
                            1.0 - auto_magic_pen_percent
                        ) * (1.0 - terminus_avg_pen)
                effective_mr_pre_ult = apply_magic_penetration(
                    base_mr, magic_pen_flat, ability_magic_pen_percent
                )
                effective_mr_post_ult = apply_magic_penetration(
                    reduced_mr, magic_pen_flat, ability_magic_pen_percent
                )
                effective_mr = effective_mr_post_ult
            # Recalculate armor penetration if it was buffed
            if "armor_penetration_percent" in stat_buff:
                armor_pen_percent = (
                    champion_stats.get("armor_penetration_percent", 0.0) / 100.0
                )
                ability_armor_pen_percent = armor_pen_percent
                auto_armor_pen_percent = armor_pen_percent
                if has_terminus:
                    ability_armor_pen_percent = max(
                        0.0, armor_pen_percent - terminus_stat_pen
                    )
                    auto_armor_pen_percent = max(
                        0.0, armor_pen_percent - terminus_stat_pen
                    )
                    if terminus_avg_pen > 0:
                        auto_armor_pen_percent = 1.0 - (
                            1.0 - auto_armor_pen_percent
                        ) * (1.0 - terminus_avg_pen)
                reduced_armor = target_armor * (1.0 - bc_reduction)
                effective_armor = apply_armor_penetration(
                    reduced_armor, flat_armor_pen, ability_armor_pen_percent
                )
            # Recalculate attack speed and auto count if AS was buffed
            if "bonus_attack_speed" in stat_buff:
                bonus_as_pct = stat_buff["bonus_attack_speed"]
                attack_speed = attack_speed + as_ratio * (bonus_as_pct / 100.0)
                champion_stats["attack_speed"] = attack_speed
                num_auto_attacks = math.floor(
                    attack_speed * fight_duration_seconds * auto_attack_uptime
                )

    # Compute crit stats early — needed by both ability crit scaling (Step 2)
    # and auto-attack simulation (Step 3).
    crit_chance = min(
        champion_stats.get("critical_strike_chance", 0) / 100.0,
        1.0,
    )
    crit_multiplier = item_effects.get_crit_multiplier(items)

    # ── Step 2: Ability damage ────────────────────────────────────────────
    breakdown: dict[str, Any] = {}
    total_damage = 0.0
    total_ability_casts = 0
    total_ability_hits = 0  # Individual damage instances (for burn refresh)
    total_muramana_procs = 0  # One proc per cast, but multi-cast R counts each
    vile_decay_stacks = 0  # Bloodletter's Curse MR reduction stacks
    ult_cast = False  # Tracks if R has been reached in cast_order
    mitigated_damage_dealt = 0.0  # Running total for missing-HP scaling
    first_ability_damage = 0.0  # Track for Horizon Focus (trigger, not amped)
    first_ability_key: str | None = None

    # NOTE: Blackfire Torch's 4% AP amp is baked into champion_stats, but
    # the first ability in cast_order fires before any target is burning
    # (so it should use ~4% less AP).  This is a known minor inaccuracy
    # (~2% on the first ability) that would require re-parsing ability
    # damages mid-fight to fix properly.

    # Navori Flickerblade: auto attacks reduce basic ability CDs
    navori_effect = item_effects.ITEM_EFFECTS.get("Navori Flickerblade")
    has_navori = "Navori Flickerblade" in [i.get("name", "") for i in items]
    navori_refund = (
        navori_effect.get("cd_refund_percent", 0.15)
        if has_navori and navori_effect
        else 0.0
    )
    autos_per_second = attack_speed * auto_attack_uptime if navori_refund > 0 else 0.0

    basic_ability_haste = champion_stats.get("basic_ability_haste", 0.0)

    recast_counts: dict[str, int] = {}  # Track casts for recast pairing

    for ability_key in cast_order:
        if ability_key not in ability_damages:
            continue
        ability_info = ability_damages[ability_key]

        if auto_attacks_only:
            num_casts = 0
        elif one_rotation or ability_key == "R":
            num_casts = 1
        else:
            # Recasts (e.g. Q2) always match their parent ability's casts
            parent_key = ability_info.get("recast_of")
            if parent_key and parent_key in recast_counts:
                num_casts = recast_counts[parent_key]
            else:
                base_cd = ability_info.get("cooldown", 0.0)
                # Basic ability haste (e.g. Spear of Shojin) applies to Q, W, E
                total_haste = ability_haste
                if ability_key in ("Q", "W", "E"):
                    total_haste += basic_ability_haste
                cd = effective_cooldown(base_cd, total_haste)
                # Navori reduces basic ability CDs (Q, W, E) via auto attacks
                if navori_refund > 0 and cd > 0 and ability_key in ("Q", "W", "E"):
                    cd = _navori_effective_cd(cd, autos_per_second, navori_refund)
                num_casts = 1 + int(fight_duration_seconds / cd) if cd > 0 else 1

        recast_counts[ability_key] = num_casts

        # Malignance MR reduction activates when R is cast
        if ability_key == "R":
            ult_cast = True

        total_ability_casts += num_casts
        damage_type = ability_info["damage_type"]

        # Determine base MR for this ability: pre-ult or post-ult
        current_base_mr = reduced_mr if ult_cast else base_mr

        # Bloodletter's Curse: magic damage abilities apply a Vile Decay
        # stack. The ability's own damage benefits from its stack.
        if mr_reduction_effect and damage_type in ("magic", "mixed"):
            vile_decay_stacks = min(
                vile_decay_stacks + 1,
                mr_reduction_effect["max_stacks"],
            )
            mr_reduced = current_base_mr * (
                1 - mr_reduction_effect["mr_reduction_per_stack"] * vile_decay_stacks
            )
            mr_reduced = max(mr_reduced, 0)
            ability_mr = apply_magic_penetration(
                mr_reduced, magic_pen_flat, ability_magic_pen_percent
            )
        else:
            ability_mr = effective_mr_post_ult if ult_cast else effective_mr_pre_ult

        if damage_type == "mixed":
            magic_per_cast = (
                apply_resistance(ability_info["magic_damage"], ability_mr) * magic_amp
            )
            true_per_cast = ability_info["true_damage"]
            ability_total = (magic_per_cast + true_per_cast) * num_casts
        elif damage_type == "magic":
            # Field-based dispatch: check for multi-part ability fields
            if "initial_damage" in ability_info:
                # Multi-part ability (e.g. Fox-Fire: initial + subsequent)
                initial_mit = apply_resistance(
                    ability_info["initial_damage"], ability_mr
                )
                subsequent_mit = apply_resistance(
                    ability_info["subsequent_damage"], ability_mr
                )
                per_cast = (initial_mit + subsequent_mit * 2) * magic_amp
                ability_total = per_cast * num_casts
            elif "damage_per_cast" in ability_info:
                # Multi-cast ability (e.g. Spirit Rush: 3 dashes)
                per_dash = (
                    apply_resistance(ability_info["damage_per_cast"], ability_mr)
                    * magic_amp
                )
                ability_total = per_dash * ability_info["total_casts"] * num_casts
            elif ability_info.get("missing_hp_scaling"):
                if "r_base_damage" in ability_info:
                    # Single-damage ability with missing-HP multiplier
                    # (e.g. Kog'Maw R: 0-50% bonus scaling linearly
                    # with missing HP up to 60% missing, then 100%
                    # bonus below 40% max HP).
                    r_base = ability_info["r_base_damage"]
                    ability_total = 0.0
                    running_dmg = mitigated_damage_dealt
                    for _ in range(num_casts):
                        hp_now = max(
                            0.0,
                            target_health - running_dmg,
                        )
                        if target_health > 0:
                            missing_pct = 1.0 - (hp_now / target_health)
                        else:
                            missing_pct = 1.0
                        if missing_pct >= 0.6:
                            multiplier = 2.0
                        else:
                            multiplier = 1.0 + 0.5 * (missing_pct / 0.6)
                        raw = r_base * multiplier
                        mit = apply_resistance(raw, ability_mr) * magic_amp
                        ability_total += mit
                        running_dmg += mit
                else:
                    # Two-part ability with missing-HP scaling on the
                    # second cast (e.g. Akali R: R1 flat + R2 scales
                    # 0-200% with target missing HP). Compute R2 based
                    # on damage dealt so far in the rotation.
                    r1_raw = ability_info.get("magic_damage", 0)
                    r2_min = ability_info.get("r2_min", 0)
                    r2_max = ability_info.get("r2_max", 0)
                    r1_mit = apply_resistance(r1_raw, ability_mr) * magic_amp
                    # After R1, estimate target HP to scale R2
                    hp_after_r1 = max(
                        0.0,
                        target_health - mitigated_damage_dealt - r1_mit,
                    )
                    missing_ratio = (
                        1.0 - (hp_after_r1 / target_health)
                        if target_health > 0
                        else 1.0
                    )
                    # R2 damage linearly interpolates min→max by
                    # missing %
                    r2_raw = r2_min + (r2_max - r2_min) * missing_ratio
                    r2_mit = apply_resistance(r2_raw, ability_mr) * magic_amp
                    ability_total = (r1_mit + r2_mit) * num_casts
            else:
                raw = ability_info.get("magic_damage", ability_info.get("total_raw", 0))
                ability_total = (
                    apply_resistance(raw, ability_mr) * magic_amp * num_casts
                )
        elif damage_type == "physical":
            raw = ability_info.get("physical_damage", ability_info.get("total_raw", 0))
            # Crit scaling at reduced effectiveness (e.g. Akshan R)
            if "crit_effectiveness" in ability_info:
                eff = ability_info["crit_effectiveness"]
                bonus_crit = crit_multiplier - 2.0
                raw *= 1 + eff * crit_chance + eff * bonus_crit * crit_chance
            # Missing HP scaling (e.g. Akshan R: 0-200% bonus)
            if "missing_hp_max_bonus" in ability_info:
                max_bonus = ability_info["missing_hp_max_bonus"]
                hp_remaining = max(
                    0.0,
                    target_health - mitigated_damage_dealt,
                )
                missing_ratio = (
                    1.0 - (hp_remaining / target_health) if target_health > 0 else 1.0
                )
                raw *= 1 + max_bonus * missing_ratio
            ability_total = apply_resistance(raw, effective_armor) * num_casts
        else:
            ability_total = ability_info.get("total_raw", 0) * num_casts

        # Apply ability-specific damage amplifiers (e.g., Actualizer)
        ability_total *= ability_amp

        # Count individual hits for burn refresh tracking.
        # Use field-based detection: multi-cast abilities have total_casts,
        # multi-part abilities have initial_damage.
        total_casts_per_use = ability_info.get("total_casts", 1)
        if "initial_damage" in ability_info:
            total_ability_hits += 3 * num_casts  # 3 hits per multi-part
        else:
            total_ability_hits += total_casts_per_use * num_casts

        # Muramana procs once per ability cast. Multi-cast abilities
        # (e.g. Ahri R with 3 dashes) proc once per sub-cast.
        total_muramana_procs += total_casts_per_use * num_casts

        # Track the first ability hit for Horizon Focus (trigger, not amped).
        # For mixed-type abilities (e.g. Ahri Q: magic outgoing + true return),
        # only the first hit (magic portion) triggers — the return is amped.
        if first_ability_key is None and num_casts > 0:
            first_ability_key = ability_key
            if damage_type == "mixed":
                first_ability_damage = magic_per_cast
            else:
                first_ability_damage = ability_total / num_casts

        breakdown[ability_key] = {
            "name": ability_info["name"],
            "casts": num_casts,
            "total_damage": ability_total,
            "damage_type": damage_type,
        }
        total_damage += ability_total
        mitigated_damage_dealt += ability_total

        # Apply target debuffs (e.g. Kog'Maw Q resistance shred) AFTER
        # computing this ability's own damage, so subsequent abilities
        # benefit from the shred but the source ability does not.
        target_debuff = ability_info.get("target_debuff")
        if target_debuff:
            armor_reduction_pct = target_debuff.get("armor_reduction_percent", 0.0)
            if armor_reduction_pct > 0:
                target_armor *= 1.0 - armor_reduction_pct / 100.0
                reduced_armor = target_armor * (1.0 - bc_reduction)
                effective_armor = apply_armor_penetration(
                    reduced_armor, flat_armor_pen, ability_armor_pen_percent
                )

            mr_reduction_pct = target_debuff.get("mr_reduction_percent", 0.0)
            if mr_reduction_pct > 0:
                base_mr *= 1.0 - mr_reduction_pct / 100.0
                reduced_mr = base_mr - malignance_mr_reduction
                reduced_mr = max(reduced_mr, 0)
                effective_mr_pre_ult = apply_magic_penetration(
                    base_mr, magic_pen_flat, ability_magic_pen_percent
                )
                effective_mr_post_ult = apply_magic_penetration(
                    reduced_mr, magic_pen_flat, ability_magic_pen_percent
                )
                effective_mr = effective_mr_post_ult

    # Update effective MR for non-ability damage using final Vile Decay stacks.
    # Non-ability damage occurs during/after the full rotation, so use
    # post-ult MR (Malignance reduction active).
    if mr_reduction_effect and vile_decay_stacks > 0:
        mr_with_stacks = reduced_mr * (
            1 - mr_reduction_effect["mr_reduction_per_stack"] * vile_decay_stacks
        )
        mr_with_stacks = max(mr_with_stacks, 0)
        effective_mr = apply_magic_penetration(
            mr_with_stacks, magic_pen_flat, auto_magic_pen_percent
        )

    # ── Switch to auto-attack pen values (with Terminus average) ──────────
    # Abilities are done; remaining damage (autos, on-hit, item procs) should
    # use Terminus average penetration for auto attacks.
    if has_terminus and terminus_avg_pen > 0:
        effective_armor = apply_armor_penetration(
            reduced_armor, flat_armor_pen, auto_armor_pen_percent
        )
        effective_mr_pre_ult = apply_magic_penetration(
            base_mr, magic_pen_flat, auto_magic_pen_percent
        )
        effective_mr_post_ult = apply_magic_penetration(
            reduced_mr, magic_pen_flat, auto_magic_pen_percent
        )
        effective_mr = effective_mr_post_ult

    # ── Step 2a: Pre-calculated proc damage (e.g. Akali passive) ─────────
    # Ability entries with a proc_count field represent damage that occurs
    # a fixed number of times (not tied to cooldowns or auto attacks).
    for key, info in ability_damages.items():
        if key in cast_order or "on_hit" in info or "stat_buff" in info:
            continue
        proc_count = info.get("proc_count", 0)
        if proc_count <= 0:
            continue

        raw_per_proc = info.get(
            "magic_damage",
            info.get(
                "physical_damage",
                info.get("total_raw", 0),
            ),
        )
        if raw_per_proc <= 0:
            continue

        dtype = info.get("damage_type", "magic")
        if dtype == "magic":
            per_proc = apply_resistance(raw_per_proc, effective_mr) * magic_amp
        elif dtype == "physical":
            per_proc = apply_resistance(raw_per_proc, effective_armor)
        else:
            per_proc = raw_per_proc

        proc_total = per_proc * proc_count
        breakdown[key] = {
            "name": info.get("name", key),
            "count": proc_count,
            "damage_per_hit": per_proc,
            "total_damage": proc_total,
            "damage_type": dtype,
        }
        total_damage += proc_total

    # ── Step 2b: Bastionbreaker Shaped Charge ─────────────────────────────
    if "Bastionbreaker" in [i.get("name", "") for i in items]:
        shaped_charge = item_effects.calculate_shaped_charge_damage(
            champion_stats, is_melee, fight_duration_seconds
        )
        if shaped_charge > 0:
            breakdown["shaped_charge_Bastionbreaker"] = {
                "name": "Bastionbreaker (Shaped Charge)",
                "total_damage": shaped_charge,
                "damage_type": "true",
            }
            total_damage += shaped_charge

    # ── Step 3: Auto attacks (per-auto crit simulation) ───────────────────
    attack_damage = champion_stats["attack_damage"]

    # Detect auto_attack_override (e.g. Ashe passive — crit chance converts
    # to bonus damage instead of crit strikes; Q changes AD ratio).
    auto_attack_override: dict[str, Any] | None = None
    for _ov_key, _ov_info in ability_damages.items():
        if "auto_attack_override" in _ov_info:
            auto_attack_override = _ov_info["auto_attack_override"]
            break

    # Detect champion double-shot passive (e.g. Akshan — second auto per
    # attack at reduced AD ratio, applies on-hits and can crit).
    double_shot_info: dict[str, Any] | None = None
    for _ds_key, _ds_info in ability_damages.items():
        if "double_shot" in _ds_info:
            double_shot_info = _ds_info["double_shot"]
            break

    # Simulate each auto attack individually, rolling for crits
    auto_physical_total = 0.0
    fiendhunter_true_total = 0.0
    num_crits = 0
    crit_damage_per_hit = 0.0
    non_crit_damage_per_hit = 0.0

    fh_effect = item_effects.ITEM_EFFECTS.get("Fiendhunter Bolts")
    fh_reduced_crit = fh_effect["reduced_crit_ratio"] if fh_effect else 0.0
    fh_true_ratio = fh_effect["natural_crit_true_damage_ratio"] if fh_effect else 0.0

    # Sundered Sky: first auto crits at reduced crit ratio, overrides natural crit
    has_sundered_sky = "Sundered Sky" in item_name_list
    ss_effect = item_effects.ITEM_EFFECTS.get("Sundered Sky")
    ss_reduced_crit = ss_effect["reduced_crit_ratio"] if ss_effect else 0.0

    sundered_sky_damage_diff = 0.0  # + = bonus damage, - = lost damage

    # Ashe-style override: crit chance converts to bonus AD ratio on every
    # auto instead of random crit strikes.  ad_ratio replaces the normal 1.0.
    override_ad_ratio = 0.0
    override_crit_as_bonus = False
    if auto_attack_override:
        override_ad_ratio = auto_attack_override.get("ad_ratio", 1.0)
        override_crit_as_bonus = auto_attack_override.get("crit_as_bonus", False)

    for i in range(num_auto_attacks):
        is_empowered = has_fiendhunter and i < empowered_autos
        is_sundered = has_sundered_sky and i == 0
        if deterministic:
            natural_crit = False
        else:
            natural_crit = random.random() < crit_chance

        if natural_crit:
            num_crits += 1

        if override_crit_as_bonus:
            # Crit chance converts to bonus damage on every auto (e.g. Ashe).
            # Passive: "bonus damage equal to X% of the attack's damage."
            # The bonus is multiplicative with the attack's base damage ratio,
            # because each Q arrow individually applies Frost Shot.
            # Formula: AD * ad_ratio * (1 + crit_chance * (crit_mult - 1))
            # Without IE: AD * ratio * (1 + crit_chance)
            # With IE:    AD * ratio * (1 + crit_chance * 1.30)
            bonus_crit_ratio = crit_multiplier - 1.0
            raw_phys = (
                attack_damage * override_ad_ratio * (1 + crit_chance * bonus_crit_ratio)
            )
            raw_true = 0.0
        elif is_empowered:
            if deterministic:
                # Expected-value for empowered autos
                raw_phys_crit = attack_damage * crit_multiplier
                raw_true_crit = raw_phys_crit * fh_true_ratio
                raw_phys_no = attack_damage * crit_multiplier * fh_reduced_crit
                raw_phys = crit_chance * raw_phys_crit + (1 - crit_chance) * raw_phys_no
                raw_true = crit_chance * raw_true_crit
            elif natural_crit:
                # Full crit + bonus true damage
                raw_phys = attack_damage * crit_multiplier
                raw_true = raw_phys * fh_true_ratio
            else:
                # Reduced crit (80% of normal crit damage)
                raw_phys = attack_damage * crit_multiplier * fh_reduced_crit
                raw_true = 0.0
            fiendhunter_true_total += raw_true
        elif is_sundered:
            # Sundered Sky: forced crit at reduced ratio, overrides natural crit
            raw_phys = attack_damage * crit_multiplier * ss_reduced_crit
            # Calculate what the auto would have dealt without Sundered Sky
            if deterministic:
                normal_raw = attack_damage * (
                    crit_chance * crit_multiplier + (1 - crit_chance)
                )
            elif natural_crit:
                normal_raw = attack_damage * crit_multiplier
            else:
                normal_raw = attack_damage
            sundered_sky_damage_diff = raw_phys - normal_raw
            raw_true = 0.0
        else:
            if deterministic:
                # Expected-value: blend crit and non-crit damage
                raw_phys = attack_damage * (
                    crit_chance * crit_multiplier + (1 - crit_chance)
                )
            elif natural_crit:
                raw_phys = attack_damage * crit_multiplier
            else:
                raw_phys = attack_damage
            raw_true = 0.0

        mitigated = apply_resistance(raw_phys, effective_armor)
        auto_physical_total += mitigated

        # Track per-hit damage for crits vs non-crits (last value wins;
        # all crits deal the same and all non-crits deal the same)
        if deterministic:
            non_crit_damage_per_hit = mitigated
        elif natural_crit:
            crit_damage_per_hit = mitigated
        else:
            non_crit_damage_per_hit = mitigated

    # Apply basic damage amplification (e.g. Hexoptics C44 Magnification)
    auto_physical_total *= basic_amp
    fiendhunter_true_total *= basic_amp
    crit_damage_per_hit *= basic_amp
    non_crit_damage_per_hit *= basic_amp

    auto_total = auto_physical_total
    auto_damage_per_hit = auto_total / num_auto_attacks if num_auto_attacks > 0 else 0.0
    num_non_crits = num_auto_attacks - num_crits

    breakdown["auto_attacks"] = {
        "name": "Auto Attacks",
        "count": num_auto_attacks,
        "num_crits": num_crits,
        "num_non_crits": num_non_crits,
        "crit_damage_per_hit": crit_damage_per_hit if num_crits > 0 else None,
        "non_crit_damage_per_hit": (
            non_crit_damage_per_hit if num_non_crits > 0 else None
        ),
        "damage_per_hit": auto_damage_per_hit,
        "total_damage": auto_total,
        "damage_type": "physical",
    }
    if has_fiendhunter and empowered_autos > 0:
        breakdown["auto_attacks"]["empowered_count"] = empowered_autos

    # Sundered Sky breakdown: show the damage difference on first auto
    if has_sundered_sky and num_auto_attacks > 0:
        mitigated_diff = (
            apply_resistance(
                abs(sundered_sky_damage_diff),
                effective_armor,
            )
            * basic_amp
        )
        if sundered_sky_damage_diff > 0:
            ss_note = f"+{mitigated_diff:.0f} bonus damage (non-crit turned into {ss_reduced_crit * 100:.0f}% crit)"
        elif sundered_sky_damage_diff < 0:
            ss_note = f"-{mitigated_diff:.0f} lost damage (normal crit overridden to {ss_reduced_crit * 100:.0f}% crit)"
        else:
            ss_note = "No damage change"
        breakdown["sundered_sky"] = {
            "name": "Sundered Sky (Lightshield Strike)",
            "total_damage": mitigated_diff,
            "sundered_sky_note": ss_note,
        }

    if fiendhunter_true_total > 0:
        breakdown["fiendhunter_true_damage"] = {
            "name": "Fiendhunter Bolts (true damage)",
            "count": empowered_autos,
            "total_damage": fiendhunter_true_total,
            "damage_type": "true",
        }

    # Add basic damage amp breakdown entry (informational — already applied)
    if basic_amp > 1.0:
        basic_amp_items = [
            i.get("name", "")
            for i in items
            if item_effects.ITEM_EFFECTS.get(i.get("name", ""), {}).get("type")
            == "basic_damage_amp"
        ]
        amp_name = basic_amp_items[0] if basic_amp_items else "Hexoptics C44"
        basic_amp_bonus = (
            (auto_total + fiendhunter_true_total) * (basic_amp - 1.0) / basic_amp
        )
        breakdown[f"basic_amp_{amp_name}"] = {
            "name": f"Damage Amplification ({amp_name})",
            "multiplier": basic_amp,
            "total_damage": basic_amp_bonus,
            "note": "included in auto attack totals above",
        }

    # Double shot: second auto per attack at reduced AD (e.g. Akshan passive)
    double_shot_total = 0.0
    if double_shot_info and num_auto_attacks > 0:
        ds_ratio = double_shot_info.get("ad_ratio", 0.5)
        ds_crits = 0
        for i in range(num_auto_attacks):
            ds_ad = attack_damage * ds_ratio
            if deterministic:
                ds_crit = False
                raw_ds = ds_ad * (crit_chance * crit_multiplier + (1 - crit_chance))
            else:
                ds_crit = random.random() < crit_chance
                if ds_crit:
                    ds_crits += 1
                    raw_ds = ds_ad * crit_multiplier
                else:
                    raw_ds = ds_ad
            double_shot_total += apply_resistance(raw_ds, effective_armor) * basic_amp

        ds_non_crits = num_auto_attacks - ds_crits
        breakdown["double_shot"] = {
            "name": double_shot_info.get("name", "Double Shot"),
            "count": num_auto_attacks,
            "num_crits": ds_crits,
            "num_non_crits": ds_non_crits,
            "total_damage": double_shot_total,
            "damage_type": "physical",
        }

    total_damage += auto_total + fiendhunter_true_total + double_shot_total

    # ── Step 4: On-hit item damage ────────────────────────────────────────
    on_hit_total = 0.0
    item_names = item_effects.get_item_effect_names(items)
    has_bork = "Blade of the Ruined King" in item_names

    # Calculate Guinsoo's Rageblade phantom hits centrally — these apply
    # ALL on-hit effects (items AND abilities) an additional time.
    phantom_hit_count, phantom_hit_autos = _calculate_phantom_hits(
        num_auto_attacks, item_names
    )
    # Double shot applies on-hit effects an additional time per auto
    double_shot_extra = num_auto_attacks if double_shot_info else 0
    on_hit_hits = num_auto_attacks + phantom_hit_count + double_shot_extra

    # Process non-BoRK on-hit items (constant damage per hit)
    non_bork_on_hit_per_hit = 0.0  # Track for BoRK HP simulation
    avg_bork_per_hit = 0.0  # Set later if BoRK is present

    for name in item_names:
        effect = item_effects.ITEM_EFFECTS.get(name, {})
        if effect.get("type") != "on_hit":
            continue
        if name == "Blade of the Ruined King":
            continue  # Handled separately below

        raw_per_hit = item_effects.get_on_hit_damage(
            name, champion_stats, target_health, is_melee
        )
        if raw_per_hit <= 0:
            continue

        dmg_type = effect.get("damage_type", "magic")
        if dmg_type == "magic":
            per_hit = apply_resistance(raw_per_hit, effective_mr) * magic_amp
        elif dmg_type == "physical":
            per_hit = apply_resistance(raw_per_hit, effective_armor)
        else:
            per_hit = raw_per_hit

        # All on-hit items get phantom hit bonus procs
        hits = on_hit_hits

        item_damage = per_hit * hits
        on_hit_total += item_damage
        non_bork_on_hit_per_hit += per_hit

        breakdown[f"on_hit_{name}"] = {
            "name": f"{name} (on-hit)",
            "count": hits,
            "damage_per_hit": per_hit,
            "total_damage": item_damage,
            "damage_type": dmg_type,
        }

    # Process ability on-hit effects (Case 2: abilities that add damage per
    # auto attack, e.g. Viego passive % health on-hit). These are passed in
    # ability_damages with an "on_hit" key containing per-hit damage info.
    # Phantom hits also apply these an additional time.
    for ability_key, ability_info in ability_damages.items():
        on_hit_data = ability_info.get("on_hit")
        if not on_hit_data or num_auto_attacks == 0:
            continue

        raw_per_hit = on_hit_data.get("damage_per_hit", 0.0)
        if raw_per_hit <= 0:
            continue

        dmg_type = on_hit_data.get("damage_type", "magic")
        if dmg_type == "magic":
            per_hit = apply_resistance(raw_per_hit, effective_mr) * magic_amp
        elif dmg_type == "physical":
            per_hit = apply_resistance(raw_per_hit, effective_armor)
        else:
            per_hit = raw_per_hit

        hits = on_hit_hits
        ability_on_hit_damage = per_hit * hits
        on_hit_total += ability_on_hit_damage
        non_bork_on_hit_per_hit += per_hit

        ability_name = on_hit_data.get("name", f"{ability_key} (on-hit)")
        stacks_required = on_hit_data.get("stacks_required", 0)
        if stacks_required > 1:
            # Stack-based on-hit (e.g. Vayne W): display as procs
            proc_count = hits // stacks_required
            damage_per_proc = per_hit * stacks_required
            breakdown[f"on_hit_ability_{ability_key}"] = {
                "name": ability_name,
                "count": proc_count,
                "damage_per_hit": damage_per_proc,
                "total_damage": ability_on_hit_damage,
                "damage_type": dmg_type,
                "unit": "procs",
            }
        else:
            breakdown[f"on_hit_ability_{ability_key}"] = {
                "name": ability_name,
                "count": hits,
                "damage_per_hit": per_hit,
                "total_damage": ability_on_hit_damage,
                "damage_type": dmg_type,
            }

    # BoRK: simulate with decreasing target current HP per auto attack.
    # Phantom hit autos cause BoRK to proc twice (at different current HP).
    # Double shot (e.g. Akshan) also procs BoRK an extra time per auto.
    if has_bork and num_auto_attacks > 0:
        bork_total, bork_hits = _simulate_bork_damage(
            target_health=target_health,
            num_auto_attacks=num_auto_attacks,
            auto_damage_per_hit=auto_damage_per_hit,
            other_on_hit_per_hit=non_bork_on_hit_per_hit,
            effective_armor=effective_armor,
            is_melee=is_melee,
            phantom_hit_autos=phantom_hit_autos,
            double_hit_all=double_shot_info is not None,
        )
        avg_bork_per_hit = bork_total / bork_hits if bork_hits > 0 else 0.0
        on_hit_total += bork_total

        breakdown["on_hit_Blade of the Ruined King"] = {
            "name": "Blade of the Ruined King (on-hit)",
            "count": bork_hits,
            "damage_per_hit": avg_bork_per_hit,
            "total_damage": bork_total,
            "damage_type": "physical",
        }

    total_damage += on_hit_total

    # ── Step 5: Spellblade damage ─────────────────────────────────────────
    spellblade_item = None
    sb_mitigated = 0.0
    sb_procs = 0

    for name in item_names:
        effect = item_effects.ITEM_EFFECTS.get(name, {})
        if effect.get("type") == "spellblade":
            spellblade_item = name
            break  # Only one spellblade can be active

    if spellblade_item and num_auto_attacks > 0:
        raw_sb = item_effects.get_spellblade_damage(spellblade_item, champion_stats)
        sb_type = item_effects.get_spellblade_damage_type(spellblade_item)
        sb_effect = item_effects.ITEM_EFFECTS[spellblade_item]
        sb_cd = sb_effect.get("cooldown", 1.5)
        weave_delay = sb_effect.get("weave_delay", 0.0)
        effective_sb_cd = sb_cd + weave_delay

        if sb_type == "magic":
            sb_mitigated = apply_resistance(raw_sb, effective_mr) * magic_amp
        elif sb_type == "physical":
            sb_mitigated = apply_resistance(raw_sb, effective_armor)
        else:
            sb_mitigated = raw_sb

        # Number of procs: limited by ability casts and cooldown
        sb_procs = min(
            total_ability_casts,
            1 + int(fight_duration_seconds / effective_sb_cd),
            num_auto_attacks,
        )
        sb_total = sb_mitigated * sb_procs

        breakdown[f"spellblade_{spellblade_item}"] = {
            "name": f"{spellblade_item} (Spellblade)",
            "procs": sb_procs,
            "damage_per_proc": sb_mitigated,
            "total_damage": sb_total,
            "damage_type": sb_type,
        }
        total_damage += sb_total

    # ── Step 5b: Double on-hit from spellblade (Dusk and Dawn) ──────────
    double_on_hit_procs = 0
    if spellblade_item and sb_procs > 0:
        sb_doh_effect = item_effects.ITEM_EFFECTS.get(spellblade_item, {})
        if sb_doh_effect.get("double_on_hit"):
            double_on_hit_procs = sb_procs
            extra_on_hit = non_bork_on_hit_per_hit * double_on_hit_procs

            # BoRK extra procs (approximate with average per-hit damage)
            if has_bork and num_auto_attacks > 0:
                extra_on_hit += avg_bork_per_hit * double_on_hit_procs

            if extra_on_hit > 0:
                breakdown[f"double_on_hit_{spellblade_item}"] = {
                    "name": f"{spellblade_item} (Double On-Hit)",
                    "procs": double_on_hit_procs,
                    "total_damage": extra_on_hit,
                    "damage_type": "mixed",
                }
                total_damage += extra_on_hit

    # Double shot on-hit stacking: each auto generates an extra on-hit
    # application, accelerating Kraken Slayer / Hullbreaker procs.
    if double_shot_info:
        double_on_hit_procs += num_auto_attacks

    # ── Step 6: Burn / DoT damage ─────────────────────────────────────────
    for name in item_names:
        effect = item_effects.ITEM_EFFECTS.get(name, {})
        etype = effect.get("type", "")

        if etype == "burn":
            raw_burn = item_effects.calculate_burn_damage(
                name, champion_stats, target_health
            )
            burn_duration = effect.get("duration", 3.0)
            # Burn refreshes on each ability hit (including R dashes).
            r_info = ability_damages.get("R")
            r_extra = 0
            if r_info:
                r_extra = r_info.get("total_casts", 3) - 1
            # Estimate time from first to last ability hit.  In a fast
            # one-rotation combo, casts are ~0.5s apart (GCD-limited).
            inter_cast_delay = 0.5
            cast_spread = (total_ability_casts - 1 + r_extra) * inter_cast_delay

            # Other item DoTs (e.g. Malignance Hatefog) deal ability
            # damage that also refreshes burns.  Hatefog starts at R cast
            # (not at fight start), so its refresh window begins partway
            # through the cast_spread.
            dot_refresh_end = cast_spread  # default: last ability hit
            for other_name in item_names:
                other_eff = item_effects.ITEM_EFFECTS.get(other_name, {})
                if other_eff.get("type") == "ult_proc" and "R" in ability_damages:
                    # R1 is cast at (cast_spread - r_extra) into the fight
                    r_start = cast_spread - r_extra
                    hatefog_end = r_start + other_eff.get("duration", 3.0)
                    dot_refresh_end = max(dot_refresh_end, hatefog_end)

            if one_rotation:
                effective_burn_time = dot_refresh_end + burn_duration
            else:
                effective_burn_time = min(
                    dot_refresh_end + burn_duration,
                    fight_duration_seconds,
                )
            if effective_burn_time > burn_duration:
                burn_multiplier = effective_burn_time / burn_duration
                raw_burn *= burn_multiplier
            burn_mitigated = apply_resistance(raw_burn, effective_mr) * magic_amp

            breakdown[f"burn_{name}"] = {
                "name": f"{name} (burn)",
                "total_damage": burn_mitigated,
                "damage_type": "magic",
            }
            total_damage += burn_mitigated

        elif etype == "immolate":
            raw_immolate = item_effects.calculate_immolate_damage(
                name, champion_stats, fight_duration_seconds
            )
            immolate_mitigated = (
                apply_resistance(raw_immolate, effective_mr) * magic_amp
            )

            breakdown[f"immolate_{name}"] = {
                "name": f"{name} (Immolate)",
                "total_damage": immolate_mitigated,
                "damage_type": "magic",
            }
            total_damage += immolate_mitigated

    # ── Step 6b: Unending Despair periodic AoE ─────────────────────────────
    if "Unending Despair" in item_names:
        raw_despair = item_effects.calculate_unending_despair_damage(
            champion_stats, fight_duration_seconds
        )
        if raw_despair > 0:
            despair_mitigated = apply_resistance(raw_despair, effective_mr) * magic_amp
            breakdown["periodic_Unending Despair"] = {
                "name": "Unending Despair (Anguish)",
                "total_damage": despair_mitigated,
                "damage_type": "magic",
            }
            total_damage += despair_mitigated

    # ── Step 7: Proc damage ───────────────────────────────────────────────
    for name in item_names:
        effect = item_effects.ITEM_EFFECTS.get(name, {})
        if effect.get("type") != "proc":
            continue

        raw_proc = item_effects.calculate_proc_damage(
            name,
            champion_stats,
            target_health,
            fight_duration_seconds,
            level,
        )
        dmg_type = effect.get("damage_type", "magic")
        if dmg_type == "magic":
            proc_mitigated = apply_resistance(raw_proc, effective_mr) * magic_amp
        elif dmg_type == "physical":
            proc_mitigated = apply_resistance(raw_proc, effective_armor)
        else:
            proc_mitigated = raw_proc

        # Stormsurge and Zaz'Zak deal ability damage — amplified by Actualizer
        if effect.get("is_ability_damage"):
            proc_mitigated *= ability_amp

        breakdown[f"proc_{name}"] = {
            "name": f"{name} (proc)",
            "total_damage": proc_mitigated,
            "damage_type": dmg_type,
        }
        total_damage += proc_mitigated

    # ── Step 7b: Ultimate-triggered procs (Malignance) ─────────────────────
    for name in item_names:
        effect = item_effects.ITEM_EFFECTS.get(name, {})
        if effect.get("type") != "ult_proc":
            continue
        # Only triggers if R was cast
        r_info = ability_damages.get("R")
        if r_info is None:
            continue
        ap = champion_stats.get("ability_power", 0)
        raw = effect.get("base", 0) + effect.get("ap_ratio", 0) * ap

        # Hatefog zone refreshes on each R dash.  Effective duration is
        # the time from R1 to R_last plus the base zone duration.
        hatefog_duration = effect.get("duration", 3.0)
        r_total_casts = r_info.get("total_casts", 1)
        r_dash_spread = (r_total_casts - 1) * 0.5  # ~0.5s between dashes
        effective_hatefog = r_dash_spread + hatefog_duration
        raw *= effective_hatefog / hatefog_duration

        ult_proc_mitigated = apply_resistance(raw, effective_mr) * magic_amp

        breakdown[f"ult_proc_{name}"] = {
            "name": f"{name} (Hatefog)",
            "total_damage": ult_proc_mitigated,
            "damage_type": "magic",
        }
        total_damage += ult_proc_mitigated

    # ── Step 8: Active item damage ────────────────────────────────────────
    if include_actives:
        for name in item_names:
            effect = item_effects.ITEM_EFFECTS.get(name, {})
            if effect.get("type") != "active":
                continue

            raw_active = item_effects.calculate_active_damage(
                name, champion_stats, target_health
            )
            dmg_type = effect.get("damage_type", "magic")
            if dmg_type == "magic":
                active_mitigated = (
                    apply_resistance(raw_active, effective_mr) * magic_amp
                )
            elif dmg_type == "physical":
                active_mitigated = apply_resistance(raw_active, effective_armor)
            else:
                active_mitigated = raw_active

            breakdown[f"active_{name}"] = {
                "name": f"{name} (active)",
                "total_damage": active_mitigated,
                "damage_type": dmg_type,
            }
            total_damage += active_mitigated

    # ── Step 9: Single-proc on-hit items ──────────────────────────────────
    # Dead Man's Plate: one proc at fight start
    if "Dead Man's Plate" in item_names and num_auto_attacks > 0:
        raw_dmp = item_effects.calculate_dead_mans_plate_damage(champion_stats)
        dmp_mitigated = apply_resistance(raw_dmp, effective_armor)
        breakdown["on_hit_once_Dead Man's Plate"] = {
            "name": "Dead Man's Plate (first hit)",
            "total_damage": dmp_mitigated,
            "damage_type": "physical",
        }
        total_damage += dmp_mitigated

    # Heartsteel: one proc per fight (30s CD, assumed single proc)
    if "Heartsteel" in item_names and num_auto_attacks > 0:
        raw_hs = item_effects.calculate_heartsteel_damage(champion_stats)
        hs_mitigated = apply_resistance(raw_hs, effective_armor)
        breakdown["on_hit_once_Heartsteel"] = {
            "name": "Heartsteel (Colossal Consumption)",
            "total_damage": hs_mitigated,
            "damage_type": "physical",
        }
        total_damage += hs_mitigated

    # Rapid Firecannon: one energized proc on first auto
    if "Rapid Firecannon" in item_names and num_auto_attacks > 0:
        rfc_effect = item_effects.ITEM_EFFECTS.get("Rapid Firecannon", {})
        raw_rfc = rfc_effect.get("base", 40.0)
        rfc_mitigated = apply_resistance(raw_rfc, effective_mr)
        breakdown["on_hit_once_Rapid Firecannon"] = {
            "name": "Rapid Firecannon (Sharpshooter)",
            "total_damage": rfc_mitigated,
            "damage_type": "magic",
        }
        total_damage += rfc_mitigated

    # Stormrazor: one energized proc on first auto
    if "Stormrazor" in item_names and num_auto_attacks > 0:
        sr_effect = item_effects.ITEM_EFFECTS.get("Stormrazor", {})
        raw_sr = sr_effect.get("base", 100.0)
        sr_mitigated = apply_resistance(raw_sr, effective_mr)
        breakdown["on_hit_once_Stormrazor"] = {
            "name": "Stormrazor (Bolt)",
            "total_damage": sr_mitigated,
            "damage_type": "magic",
        }
        total_damage += sr_mitigated

    # Voltaic Cyclosword: one energized proc on first auto (physical).
    # Firmament deals a % of the target's CURRENT health (melee/ranged
    # split), capped. The proc lands on the first auto, when the target is
    # still at full health (same convention as BoRK's simulation start).
    if "Voltaic Cyclosword" in item_names and num_auto_attacks > 0:
        vc_effect = item_effects.ITEM_EFFECTS.get("Voltaic Cyclosword", {})
        vc_ratio = (
            vc_effect.get("current_hp_ratio_melee", 0.09)
            if is_melee
            else vc_effect.get("current_hp_ratio_ranged", 0.07)
        )
        vc_cap = vc_effect.get("damage_cap", 200.0)
        raw_vc = min(vc_ratio * target_health, vc_cap)
        vc_mitigated = apply_resistance(raw_vc, effective_armor)
        breakdown["on_hit_once_Voltaic Cyclosword"] = {
            "name": "Voltaic Cyclosword (Firmament)",
            "total_damage": vc_mitigated,
            "damage_type": "physical",
        }
        total_damage += vc_mitigated

    # Statikk Shiv: one empowered chain-lightning auto per energize cycle.
    # Single-target model: the chain (chain_targets_min/max) has nothing to
    # bounce to, so damage is one base-damage proc.
    if "Statikk Shiv" in item_names and num_auto_attacks > 0:
        ss_effect = item_effects.ITEM_EFFECTS.get("Statikk Shiv", {})
        ss_count = min(
            int(ss_effect.get("empowered_auto_count", 1)),
            num_auto_attacks,
        )
        raw_ss = ss_effect.get("base", 60.0) * ss_count
        ss_mitigated = apply_resistance(raw_ss, effective_mr)
        breakdown["on_hit_once_Statikk Shiv"] = {
            "name": "Statikk Shiv (Electrospark)",
            "procs": ss_count,
            "total_damage": ss_mitigated,
            "damage_type": "magic",
        }
        total_damage += ss_mitigated

    # Titanic Hydra Crescent active: empowered Cleave on next auto (10s CD)
    if "Titanic Hydra" in item_names and num_auto_attacks > 0:
        th_effect = item_effects.ITEM_EFFECTS.get("Titanic Hydra", {})
        th_active_ratio = (
            th_effect.get("active_max_hp_ratio_melee", 0.04)
            if is_melee
            else th_effect.get("active_max_hp_ratio_ranged", 0.02)
        )
        if th_active_ratio > 0:
            th_cd = th_effect.get("active_cooldown", 10.0)
            th_procs = 1 + int(fight_duration_seconds / th_cd) if th_cd > 0 else 1
            th_procs = min(th_procs, num_auto_attacks)
            champion_hp = champion_stats.get("health", 0)
            raw_th_active = th_active_ratio * champion_hp * th_procs
            th_mitigated = apply_resistance(raw_th_active, effective_armor)
            breakdown["active_Titanic Hydra"] = {
                "name": "Titanic Hydra (Titanic Crescent)",
                "procs": th_procs,
                "total_damage": th_mitigated,
                "damage_type": "physical",
            }
            total_damage += th_mitigated

    # Kraken Slayer: every 3rd on-hit application. Phantom hits and double
    # on-hit procs each grant an extra stack (not an extra damage proc).
    # Damage scales with target's missing HP, so we simulate per-auto.
    if "Kraken Slayer" in item_names and num_auto_attacks > 0:
        kraken_procs, kraken_proc_autos = _calculate_kraken_procs(
            num_auto_attacks,
            phantom_hit_autos,
            double_on_hit_procs,
        )
        if kraken_procs > 0:
            # Estimate total on-hit damage per auto for HP tracking
            # (auto damage + non-BoRK on-hits + average BoRK per hit)
            kraken_other_on_hit = non_bork_on_hit_per_hit
            if has_bork and avg_bork_per_hit > 0:
                kraken_other_on_hit += avg_bork_per_hit

            kraken_total = _simulate_kraken_damage(
                target_health=target_health,
                num_auto_attacks=num_auto_attacks,
                auto_damage_per_hit=auto_damage_per_hit,
                other_on_hit_per_hit=kraken_other_on_hit,
                effective_armor=effective_armor,
                is_melee=is_melee,
                level=level,
                kraken_proc_autos=kraken_proc_autos,
            )
            breakdown["on_hit_Kraken Slayer"] = {
                "name": "Kraken Slayer (Bring It Down)",
                "procs": kraken_procs,
                "damage_per_proc": kraken_total / kraken_procs,
                "total_damage": kraken_total,
                "damage_type": "physical",
            }
            total_damage += kraken_total

    # Hullbreaker Skipper: every 5th on-hit application. Phantom hits and
    # double on-hit procs each grant an extra stack (not extra damage).
    # Damage is constant per proc (base AD ratio + champion max HP ratio).
    if "Hullbreaker" in item_names and num_auto_attacks > 0:
        hb_effect = item_effects.ITEM_EFFECTS.get("Hullbreaker", {})
        hb_hits = hb_effect.get("hits_required", 5)
        hb_procs, _ = _calculate_hullbreaker_procs(
            num_auto_attacks,
            phantom_hit_autos,
            double_on_hit_procs,
            hits_required=hb_hits,
        )
        if hb_procs > 0:
            raw_per_proc = item_effects.calculate_hullbreaker_proc_damage(
                champion_stats,
                is_melee,
            )
            hb_mitigated = apply_resistance(
                raw_per_proc * hb_procs,
                effective_armor,
            )
            breakdown["on_hit_Hullbreaker"] = {
                "name": "Hullbreaker (Skipper)",
                "procs": hb_procs,
                "damage_per_proc": hb_mitigated / hb_procs,
                "total_damage": hb_mitigated,
                "damage_type": "physical",
            }
            total_damage += hb_mitigated

    # Eclipse: Ever Rising Moon proc (% max HP physical damage)
    if "Eclipse" in item_names:
        raw_eclipse = item_effects.calculate_eclipse_damage(
            target_health,
            is_melee,
            fight_duration_seconds,
        )
        eclipse_mitigated = apply_resistance(raw_eclipse, effective_armor)
        breakdown["proc_Eclipse"] = {
            "name": "Eclipse (Ever Rising Moon)",
            "total_damage": eclipse_mitigated,
            "damage_type": "physical",
        }
        total_damage += eclipse_mitigated

    # Muramana ability damage bonus — procs once per ability cast, but
    # multi-cast abilities (e.g. Ahri R with 3 dashes) proc each sub-cast.
    if "Muramana" in item_names:
        raw_mura = item_effects.get_muramana_ability_damage(
            champion_stats, is_melee, total_muramana_procs
        )
        mura_mitigated = apply_resistance(raw_mura, effective_armor)
        breakdown["muramana_ability"] = {
            "name": "Muramana (Shock - abilities)",
            "total_damage": mura_mitigated,
            "damage_type": "physical",
        }
        total_damage += mura_mitigated

    # ── Step 9.5: Shadowflame Cinderbloom ──────────────────────────────────
    if "Shadowflame" in item_names:
        shadowflame_bonus = _calculate_shadowflame_bonus(
            breakdown,
            ability_damages,
            target_health,
            cast_order,
        )
        if shadowflame_bonus > 0:
            breakdown["shadowflame_Shadowflame"] = {
                "name": "Shadowflame (Cinderbloom)",
                "total_damage": shadowflame_bonus,
                "damage_type": "mixed",
            }
            total_damage += shadowflame_bonus

    # ── Step 9.6: Expose Weakness (Bloodsong) ──────────────────────────────
    if spellblade_item and sb_procs > 0:
        sb_ew_effect = item_effects.ITEM_EFFECTS.get(spellblade_item, {})
        expose_rate = (
            sb_ew_effect.get("expose_weakness_melee", 0)
            if is_melee
            else sb_ew_effect.get("expose_weakness_ranged", 0)
        )
        if expose_rate > 0:
            # First ability cast + first auto + first spellblade proc
            # occur before Expose Weakness is applied and don't benefit.
            first_ability_key = next((k for k in cast_order if k in breakdown), None)
            damage_before_expose = 0.0
            if first_ability_key:
                entry = breakdown[first_ability_key]
                casts = entry.get("casts", 1)
                if casts > 0:
                    damage_before_expose += entry["total_damage"] / casts
            damage_before_expose += auto_damage_per_hit
            damage_before_expose += sb_mitigated

            amped_damage = max(0, total_damage - damage_before_expose)
            expose_bonus = amped_damage * expose_rate

            breakdown[f"expose_weakness_{spellblade_item}"] = {
                "name": f"{spellblade_item} (Expose Weakness)",
                "amplifier": 1.0 + expose_rate,
                "total_damage": expose_bonus,
                "damage_type": "mixed",
            }
            total_damage += expose_bonus

    # ── Step 10: Damage amplifiers ────────────────────────────────────────
    amp_sources, amp = item_effects.get_damage_amplifier_breakdown(
        items,
        fight_duration_seconds,
        target_bonus_health=max(0, target_bonus_health),
    )
    if amp > 1.0:
        amp_bonus = total_damage * (amp - 1.0)
        # Create per-source breakdown entries
        for source_name, source_amp in amp_sources:
            if source_amp > 0:
                source_bonus = total_damage * source_amp
                breakdown[f"damage_amp_{source_name}"] = {
                    "name": f"Damage Amplification ({source_name})",
                    "multiplier": 1.0 + source_amp,
                    "total_damage": source_bonus,
                }
        total_damage += amp_bonus

    # Actualizer ability damage amp — show as separate breakdown entry.
    # The amp was already applied per-ability in Step 2 and per-proc in
    # Step 7, so this entry is informational only (damage already counted).
    if ability_amp > 1.0:
        # Sum all ability + ability-proc damage that was amplified
        amped_base = sum(
            v.get("total_damage", 0)
            for k, v in breakdown.items()
            if isinstance(v, dict)
            and k
            not in (
                "auto_attacks",
                "damage_amplification",
            )
            and not k.startswith("damage_amp_")
        )
        # The amplified damage = base * amp, so the amp contribution is
        # base * (amp - 1) / amp  (since base already includes the amp).
        actualizer_bonus = amped_base * (ability_amp - 1.0) / ability_amp
        actualizer_items = [
            i.get("name", "")
            for i in items
            if item_effects.ITEM_EFFECTS.get(i.get("name", ""), {}).get("type")
            == "ability_damage_amp"
        ]
        amp_name = actualizer_items[0] if actualizer_items else "Actualizer"
        breakdown[f"ability_amp_{amp_name}"] = {
            "name": f"Damage Amplification ({amp_name})",
            "multiplier": ability_amp,
            "total_damage": actualizer_bonus,
            "note": "included in ability/proc totals above",
        }

    # Horizon Focus Hypershot: amp all damage except the first ability cast
    # (the first ability triggers the mark; its own damage is not amped).
    if hypershot_amp > 1.0:
        amped_damage = total_damage - first_ability_damage
        hypershot_bonus = amped_damage * (hypershot_amp - 1.0)
        breakdown["damage_amp_Horizon Focus"] = {
            "name": "Damage Amplification (Horizon Focus)",
            "multiplier": hypershot_amp,
            "total_damage": hypershot_bonus,
        }
        total_damage += hypershot_bonus

    # ── Step 11: Execute threshold display (The Collector) ────────────────
    # The Collector's execute damage is NOT added to the total; instead we
    # display the HP threshold at which the target would be executed.
    collector_threshold = item_effects.get_collector_execution_threshold(
        items, target_health
    )
    if collector_threshold is not None:
        breakdown["execute"] = {
            "name": "The Collector (Execute)",
            "total_damage": 0.0,
            "damage_type": "true",
            "execution_threshold_hp": collector_threshold,
            "note": (
                f"Collector Execution Threshold: {collector_threshold:.0f} HP "
                f"({item_effects.ITEM_EFFECTS.get('The Collector', {}).get('threshold', 0.05) * 100:.0f}% "
                f"of {target_health:.0f})"
            ),
        }

    # ── Notes for conditional item assumptions ─────────────────────────────
    notes: list[str] = []
    if has_hexplate:
        notes.append(
            "R is assumed to be cast at the start of the fight. "
            "Experimental Hexplate Overdrive (50% bonus AS) is applied "
            "from time 0."
        )
    if has_fiendhunter:
        notes.append(
            "R is assumed to be cast at the start of the fight. "
            "Fiendhunter Bolts empowered attacks (50% bonus AS, "
            "guaranteed crits) are applied from time 0."
        )

    if has_navori and navori_refund > 0 and autos_per_second > 0:
        notes.append(
            f"Navori Flickerblade: basic ability CDs reduced by "
            f"{navori_refund:.0%} per auto attack "
            f"({autos_per_second:.2f} autos/sec effective)."
        )

    if phantom_hit_count > 0:
        notes.append(
            f"Guinsoo's Rageblade: {phantom_hit_count} phantom hit(s) — "
            f"all on-hit effects apply an additional time on autos "
            f"#{', #'.join(str(a + 1) for a in sorted(phantom_hit_autos))}."
        )

    return {
        "breakdown": breakdown,
        "total_damage": total_damage,
        "effective_mr": effective_mr,
        "effective_armor": effective_armor,
        "notes": notes,
        # Exposed for champion-specific ability calculators (Case 1: stack
        # acceleration). Champions like Vayne can check which autos grant
        # double stacks to calculate ability procs more accurately.
        "phantom_hit_autos": phantom_hit_autos,
        "phantom_hit_count": phantom_hit_count,
    }
