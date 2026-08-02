const DDRAGON = "https://ddragon.leagueoflegends.com/cdn/16.15.1/img";

let DATA;
let BIS_PROFILES = {};
let EFFECT_CATALOG = {};
let pickerContext = null;
let bisContext = null;
const ABILITY_SLOTS = ["P", "Q", "W", "E", "R"];
const engine = {
  ready: false,
  reviewed: new Set(),
  backend: new Set(),
  availability: new Map(),
  itemOptions: {},
  championOptions: {},
  keystones: [],
  fightLimits: { fight_duration: [1, 10] },
  pendingTimer: null,
  requestId: 0,
  responses: null,
  pending: false,
};

const state = {
  attacker: {
    champion: null,
    level: 1,
    role: null,
    roleQuestComplete: false,
    buildA: [0, 0, 0, 0, 0, 0],
    buildAStacks: [0, 0, 0, 0, 0, 0],
    buildB: [0, 0, 0, 0, 0, 0],
    buildBStacks: [0, 0, 0, 0, 0, 0],
    questBootA: 0,
    questBootB: 0,
    includeBootsA: true,
    includeBootsB: true,
    keystoneA: "",
    keystoneB: "",
    comparisonEnabled: false,
    baseDamage: 0,
    apRatio: 0,
    physicalDamage: 0,
    adRatio: 0,
    abilityInputs: {},
  },
  targets: [],
  allies: [],
  fight: { rotations: 1, duration: 10, aaUptime: 0 },
  optimizer: { running: false, summary: null, scope: null },
};

const TIER_TWO_BOOTS = [3006, 3009, 3008, 3158, 3111, 3047, 3020];
const TIER_THREE_BOOTS = [3172, 3170, 3168, 3171, 3173, 3174, 3175];
const ALL_ROLE_BOOTS = new Set([...TIER_TWO_BOOTS, ...TIER_THREE_BOOTS]);

const $ = (id) => document.getElementById(id);
const fmt = (value) => Math.round(value).toLocaleString("en-US");
const one = (value) => Number(value).toFixed(1).replace(/\.0$/, "");
const percent = (value) => `${value.toFixed(value < 10 ? 1 : 0)}%`;
const plural = (count, singular, pluralForm = `${singular}s`) => count === 1 ? singular : pluralForm;
const escapeHtml = (value) => String(value).replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);

function invalidateOptimization() {
  if (!state.optimizer.running) state.optimizer.summary = null;
  engine.responses = null;
}

function getChampion(name) {
  return name ? DATA.champions.find((entry) => entry.name === name) || null : null;
}

function mergeAbilityCatalog(catalog) {
  if (!catalog?.champions?.length || !DATA?.champions?.length) return;
  const entries = new Map(catalog.champions.map((entry) => [entry.name, entry]));
  DATA.champions.forEach((champion) => {
    const entry = entries.get(champion.name);
    if (!entry) return;
    const formulaBySlot = new Map((champion.abilities || []).map((ability) => [ability.slot, ability]));
    champion.ingestedAbilities = (entry.abilities || []).map((ability) => ({
      ...ability,
      formulaReviewed: formulaBySlot.has(ability.slot),
      source: catalog.source,
    }));
    champion.abilities = (champion.abilities || []).map((ability) => ({
      ...ability,
      formulaSource: ability.formulaSource || "Patch client formula graph",
    }));
  });
}

function wikiDamageType(type) {
  const normalized = String(type || "").toUpperCase();
  if (normalized.includes("TRUE")) return "true";
  if (normalized.includes("MAGIC")) return "magical";
  if (normalized.includes("PHYSICAL")) return "physical";
  return null;
}

function wikiFallbackVariant(form, packet = null) {
  const source = packet || (form?.packets || []).find((entry) => wikiDamageType(entry?.damageType));
  const ratios = source?.ratios || {};
  const levelScaled = Array.isArray(source?.base) && source.base.length > 6;
  return {
    name: packet?.attribute || form?.name || "Wiki-derived form",
    levelBase: levelScaled ? source.base : undefined,
    base: levelScaled ? undefined : (source?.base || []),
    ap: ratios.ap,
    ad: ratios.ad,
    bonusAd: ratios.bonusAd,
    targetMaxHp: ratios.targetMaxHp,
    targetCurrentHp: ratios.targetCurrentHp,
    targetMissingHp: ratios.targetMissingHp,
    packets: source ? [{ type: wikiDamageType(source.damageType) }] : [],
  };
}

function wikiFallbackAbility(slot, forms, metadata) {
  const normalized = (forms || []).flatMap((form) => {
    const packets = (form.packets || []).filter((packet) => wikiDamageType(packet?.damageType));
    return packets.length ? packets.map((packet) => wikiFallbackVariant(form, packet)) : [wikiFallbackVariant(form)];
  });
  const first = normalized[0] || { name: metadata?.name || slot, packets: [] };
  return {
    slot,
    name: metadata?.name || first.name || slot,
    icon: metadata?.icon || "",
    maxRank: Math.max(...(forms || []).map((form) => Number(form.maxRank) || (slot === "R" ? 3 : slot === "P" ? 1 : 5)), slot === "R" ? 3 : slot === "P" ? 1 : 5),
    variants: normalized.length ? normalized : [first],
    formulaSource: "Wiki-derived local cache",
    wikiDescription: metadata?.description || metadata?.blurb || "",
  };
}

function mergeBisProfiles(profiles) {
  if (!profiles?.champions || typeof profiles.champions !== "object") return;
  BIS_PROFILES = profiles.champions;
  if (!DATA?.champions?.length) return;
  DATA.champions.forEach((champion) => {
    const profile = BIS_PROFILES[champion.name];
    if (!profile?.abilities) return;
    const existing = new Map((champion.abilities || []).map((ability) => [ability.slot, ability]));
    const metadata = new Map((champion.ingestedAbilities || []).map((ability) => [ability.slot, ability]));
    Object.entries(profile.abilities).forEach(([slot, forms]) => {
      if (existing.has(slot)) return;
      existing.set(slot, wikiFallbackAbility(slot, forms, metadata.get(slot)));
    });
    champion.abilities = ABILITY_SLOTS.map((slot) => existing.get(slot)).filter(Boolean);
    champion.wikiAbilitySlots = champion.abilities.filter((ability) => ability.formulaSource === "Wiki-derived local cache").map((ability) => ability.slot);
  });
}

function mergeEffectCatalog(catalog) {
  if (catalog?.items && typeof catalog.items === "object") EFFECT_CATALOG = catalog.items;
}

function getItem(id) {
  return Number(id) ? DATA.items.find((entry) => entry.id === Number(id)) || null : null;
}

function getKeystone(name) {
  return name ? engine.keystones.find((entry) => entry.name === name) || null : null;
}

function activeAbilityKit() {
  return getChampion(state.attacker.champion)?.abilities || [];
}

function resetAbilityInputs() {
  const defaultRanks = defaultAbilityRanks({
    champion: state.attacker.champion,
    level: state.attacker.level,
  });
  state.attacker.abilityInputs = Object.fromEntries(activeAbilityKit().map((ability) => [ability.slot, {
    rank: ability.slot === "P" ? 1 : Number(defaultRanks[ability.slot] || 0),
    casts: 1,
    hits: 1,
    variant: 0,
  }]));
}

function syncAbilityInputsToLevel() {
  if (!state.attacker.champion) return;
  const defaultRanks = defaultAbilityRanks(state.attacker);
  activeAbilityKit().forEach((ability) => {
    const input = abilityInput(ability.slot);
    input.rank = ability.slot === "P" ? 1 : Number(defaultRanks[ability.slot] || 0);
    state.attacker.abilityInputs[ability.slot] = input;
  });
}

function abilityInput(slot) {
  return state.attacker.abilityInputs[slot] || { rank: 0, casts: 0, hits: 1, variant: 0 };
}

function championImage(name) {
  const champion = getChampion(name);
  return champion ? `${DDRAGON}/champion/${champion.key}.png` : "";
}

function itemImage(id) {
  return `${DDRAGON}/item/${Number(id)}.png`;
}

function abilityImage(ability) {
  if (!ability?.icon) return "";
  if (ability.icon.startsWith("http")) return ability.icon;
  return `${DDRAGON}/${ability.slot === "P" ? "passive" : "spell"}/${ability.icon}`;
}

function itemName(id, fallback = "Empty slot") {
  return getItem(id)?.name || fallback;
}

function pathValue(path) {
  return path.split(".").reduce((value, part) => value?.[Number.isNaN(Number(part)) ? part : Number(part)], state);
}

function setPath(path, nextValue) {
  const parts = path.split(".");
  const last = parts.pop();
  const parent = parts.reduce((value, part) => value[Number.isNaN(Number(part)) ? part : Number(part)], state);
  // Keep boots in the dedicated field even if a stale browser state or an
  // older picker path tries to write a boots id into an ordinary item slot.
  // The backend rejects that inventory, so normalize it before any request
  // can reach the coupled optimizer.
  if (parts.at(-1) === "items" && ALL_ROLE_BOOTS.has(Number(nextValue))) {
    const index = Number(parts[1]);
    if (parts[0] === "targets" || parts[0] === "allies") {
      const loadout = state[parts[0]]?.[index];
      if (loadout) {
        loadout.boots = Number(nextValue);
        loadout.includeBoots = true;
        parent[Number(last)] = 0;
        invalidateOptimization();
        return;
      }
    }
  }
  if (parts[0] === "attacker" && (parts[1] === "buildA" || parts[1] === "buildB") && ALL_ROLE_BOOTS.has(Number(nextValue))) {
    const side = parts[1].slice(-1);
    state.attacker[`questBoot${side}`] = Number(nextValue);
    state.attacker[`includeBoots${side}`] = true;
    parent[Number(last)] = 0;
    invalidateOptimization();
    return;
  }
  parent[Number.isNaN(Number(last)) ? last : Number(last)] = nextValue;
  invalidateOptimization();
}

function stackSpec(id) {
  if (Number(id) === 1082) return { max: 10, ap: 4, moveSpeedPercentAt: null };
  if (Number(id) === 3041) return { max: 25, ap: 5, moveSpeedPercentAt: 10 };
  return null;
}

function stackValue(path) {
  const parts = path.split(".");
  if (parts[0] === "attacker" && parts[1] === "buildA") return state.attacker.buildAStacks[Number(parts[2])] || 0;
  if (parts[0] === "attacker" && parts[1] === "buildB") return state.attacker.buildBStacks[Number(parts[2])] || 0;
  if (parts[0] === "targets" && parts[2] === "items") return state.targets[Number(parts[1])]?.itemStacks?.[Number(parts[3])] || 0;
  if (parts[0] === "allies" && parts[2] === "items") return state.allies[Number(parts[1])]?.itemStacks?.[Number(parts[3])] || 0;
  return 0;
}

function setStackValue(path, value) {
  const parts = path.split(".");
  if (parts[0] === "attacker" && parts[1] === "buildA") state.attacker.buildAStacks[Number(parts[2])] = value;
  else if (parts[0] === "attacker" && parts[1] === "buildB") state.attacker.buildBStacks[Number(parts[2])] = value;
  else if (parts[0] === "targets" && parts[2] === "items") state.targets[Number(parts[1])].itemStacks[Number(parts[3])] = value;
  else if (parts[0] === "allies" && parts[2] === "items") state.allies[Number(parts[1])].itemStacks[Number(parts[3])] = value;
  invalidateOptimization();
}

function buildStats(itemIds, stackCounts = []) {
  const entries = itemIds.map((id, index) => ({ item: getItem(id), stacks: Number(stackCounts[index] || 0) })).filter((entry) => entry.item);
  const total = entries.reduce((sum, entry) => {
    const { item, stacks } = entry;
    for (const key of ["ap", "hp", "mana", "ad", "armor", "mr", "haste", "pen", "percentPen", "lethality", "percentArmorPen", "attackSpeed", "moveSpeed", "moveSpeedPercent", "crit"]) {
      sum[key] += Number(item[key] || 0);
    }
    const spec = stackSpec(item.id);
    if (spec) {
      sum.ap += Math.min(stacks, spec.max) * spec.ap;
      if (spec.moveSpeedPercentAt && stacks >= spec.moveSpeedPercentAt) sum.moveSpeedPercent += 10;
    }
    return sum;
  }, { ap: 0, hp: 0, mana: 0, ad: 0, armor: 0, mr: 0, haste: 0, pen: 0, percentPen: 0, lethality: 0, percentArmorPen: 0, attackSpeed: 0, moveSpeed: 0, moveSpeedPercent: 0, crit: 0 });
  total.apBeforeMultiplier = total.ap;
  total.apMultiplier = entries.some(({ item }) => item.id === 3089) ? 1.3 : 1;
  total.ap *= total.apMultiplier;
  return total;
}

function attackerLevelCap() {
  // Levels 19-20 are the top-lane role quest reward; everyone else caps at 18.
  return state.attacker.role === "top" && state.attacker.roleQuestComplete ? 20 : 18;
}

function championStats(name, level, itemIds = [], stackCounts = []) {
  const champion = getChampion(name);
  const boundedLevel = Math.max(1, Math.min(20, Number(level) || 1));
  const scale = (boundedLevel - 1) * (0.7025 + 0.0175 * (boundedLevel - 1));
  const build = buildStats(itemIds, stackCounts);
  const baseHp = (champion?.hp || 0) + (champion?.hpPerLevel || 0) * scale;
  return {
    baseHp,
    bonusHp: build.hp,
    hp: baseHp + build.hp,
    mana: (champion?.mana || 0) + (champion?.manaPerLevel || 0) * scale + build.mana,
    ad: (champion?.ad || 0) + (champion?.adPerLevel || 0) * scale + build.ad,
    ap: build.ap,
    armor: (champion?.armor || 0) + (champion?.armorPerLevel || 0) * scale + build.armor,
    mr: (champion?.mr || 0) + (champion?.mrPerLevel || 0) * scale + build.mr,
    haste: build.haste,
    pen: build.pen,
    percentPen: build.percentPen,
    lethality: build.lethality,
    percentArmorPen: build.percentArmorPen,
    attackSpeed: (champion?.attackSpeed || 0) + (champion?.attackSpeedRatio || champion?.attackSpeed || 0) * ((((champion?.attackSpeedPerLevel || 0) * scale) + build.attackSpeed) / 100),
    crit: Math.min(100, build.crit),
    moveSpeed: ((champion?.moveSpeed || 0) + build.moveSpeed) * (1 + build.moveSpeedPercent / 100),
    range: champion?.range || 0,
  };
}

function attackerChampionStats(itemIds = [], stackCounts = [], combatant = state.attacker) {
  const stats = championStats(combatant.champion, combatant.level, itemIds, stackCounts);
  if (combatant.role === "mid" && combatant.roleQuestComplete) {
    const build = buildStats(itemIds, stackCounts);
    const baseAd = stats.ad - build.ad;
    stats.ad = baseAd + build.ad * 1.08;
    stats.ap *= 1.08;
  }
  return stats;
}

function rosterChampionStats(loadout) {
  const stats = championStats(loadout.champion, loadout.level, loadout.items, loadout.itemStacks);
  if (loadout.role === "mid" && loadout.roleQuestComplete) {
    const build = buildStats(loadout.items, loadout.itemStacks);
    const baseAd = stats.ad - build.ad;
    stats.ad = baseAd + build.ad * 1.08;
    stats.ap *= 1.08;
  }
  return stats;
}

function usesQuestBootSlot() {
  return state.attacker.roleQuestComplete && ["mid", "bottom"].includes(state.attacker.role);
}

function attackerLevelCap() {
  return state.attacker.role === "top" && state.attacker.roleQuestComplete ? 20 : 18;
}

function ordinarySlotCount(side = "A") {
  if (state.attacker.role === "bottom" && state.attacker.roleQuestComplete) return 6;
  return includeBootsForSide(side) ? 5 : 6;
}

function includeBootsForSide(side) {
  return side === "B" ? state.attacker.includeBootsB : state.attacker.includeBootsA;
}

function questBootIds() {
  return state.attacker.role === "mid" ? TIER_THREE_BOOTS : TIER_TWO_BOOTS;
}

function magicPenLabel(stats) {
  if (stats.percentPen && stats.pen) return `${one(stats.percentPen)}% + ${one(stats.pen)}`;
  if (stats.percentPen) return `${one(stats.percentPen)}%`;
  return one(stats.pen);
}

function armorPenLabel(stats) {
  if (stats.percentArmorPen && stats.lethality) return `${one(stats.percentArmorPen)}% + ${one(stats.lethality)}`;
  if (stats.percentArmorPen) return `${one(stats.percentArmorPen)}%`;
  return one(stats.lethality);
}

function statMatrix(stats, compareStats = null, compact = false) {
  const rows = [
    ["Base health", fmt(stats.baseHp), compareStats && fmt(compareStats.baseHp)],
    ["Bonus health", fmt(stats.bonusHp), compareStats && fmt(compareStats.bonusHp)],
    ["Total health", fmt(stats.hp), compareStats && fmt(compareStats.hp)],
    ["Resource", fmt(stats.mana), compareStats && fmt(compareStats.mana)],
    ["Attack damage", one(stats.ad), compareStats && one(compareStats.ad)],
    ["Ability power", one(stats.ap), compareStats && one(compareStats.ap)],
    ["Armor", one(stats.armor), compareStats && one(compareStats.armor)],
    ["Magic resist", one(stats.mr), compareStats && one(compareStats.mr)],
    ["Attack speed", one(stats.attackSpeed), compareStats && one(compareStats.attackSpeed)],
    ["Move speed", one(stats.moveSpeed), compareStats && one(compareStats.moveSpeed)],
    ["Ability haste", one(stats.haste), compareStats && one(compareStats.haste)],
    ["Critical chance", `${one(stats.crit)}%`, compareStats && `${one(compareStats.crit)}%`],
    ["Armor pen", armorPenLabel(stats), compareStats && armorPenLabel(compareStats)],
    ["Magic pen", magicPenLabel(stats), compareStats && magicPenLabel(compareStats)],
  ];
  return `<div class="stat-matrix ${compact ? "compact" : ""}">${rows.map(([label, a, b]) => `<div class="stat-cell"><span>${label}</span><strong>${a}</strong>${b !== null && b !== false ? `<b>${b}</b>` : ""}</div>`).join("")}</div>`;
}

function itemStatsLine(item) {
  if (!item) return "Remove item";
  const stats = [];
  if (item.ap) stats.push(`${item.ap} AP`);
  if (item.id === 3089) stats.push("+30% total AP");
  if (item.ad) stats.push(`${item.ad} AD`);
  if (item.hp) stats.push(`${item.hp} HP`);
  if (item.armor) stats.push(`${item.armor} armor`);
  if (item.mr) stats.push(`${item.mr} MR`);
  if (item.haste) stats.push(`${item.haste} haste`);
  if (item.pen) stats.push(`${item.pen} pen`);
  if (item.percentPen) stats.push(`${item.percentPen}% pen`);
  if (item.attackSpeed) stats.push(`${item.attackSpeed}% AS`);
  if (item.crit) stats.push(`${item.crit}% crit`);
  if (item.lethality) stats.push(`${item.lethality} lethality`);
  if (item.percentArmorPen) stats.push(`${item.percentArmorPen}% armor pen`);
  return stats.join(" · ") || "Item effect";
}

function bisReadyForPath(path) {
  const [root, indexText] = String(path).split(".");
  const index = Number(indexText);
  if (root === "attacker") return Boolean(state.attacker.champion && state.targets.length && state.targets.every((target) => target.champion));
  if (root === "allies") return Boolean(state.allies[index]?.champion && state.allies[index]?.role && state.targets.some((target) => target.champion));
  if (root === "targets") return Boolean(state.targets[index]?.champion && state.targets[index]?.role && state.attacker.champion);
  return false;
}

function itemSlot(path, id, compact = false, allowBis = false) {
  const item = getItem(id);
  const bisReady = bisReadyForPath(path);
  return `<div class="slot-wrap ${compact ? "compact" : ""}">
    <button class="item-slot" type="button" data-picker="item" data-path="${path}" aria-label="${item ? `Change ${escapeHtml(item.name)}` : "Add item"}">
      <span class="item-icon ${item ? "" : "empty"}">${item ? `<img src="${itemImage(id)}" alt="" />` : `<span aria-hidden="true">+</span>`}</span>
      ${compact ? "" : `<small>${escapeHtml(item?.name || "Add item")}</small>`}
    </button>
    ${stackSpec(id) ? stackControl(path, id, compact) : ""}
    ${allowBis ? `<button class="bis-trigger" type="button" data-bis-path="${path}" title="Rank this slot" ${bisReady ? "" : "disabled"}>BIS</button>` : ""}
  </div>`;
}

function rosterAbilityRankControls(loadout, index, root) {
  if (!loadout?.champion) return "";
  const profile = bisChampionProfile(loadout);
  const rows = ["Q", "W", "E", "R"].map((slot) => {
    const forms = profile.abilities?.[slot] || [];
    if (!forms.length) return "";
    const maxRank = Math.max(...forms.map((ability) => ability.maxRank || (slot === "R" ? 3 : 5)));
    const rank = bisRankFor(loadout, slot, maxRank);
    return `<span class="roster-rank"><b>${slot}</b><button type="button" data-roster-rank="${root}.${index}.${slot}" data-delta="-1" aria-label="Decrease ${slot} rank">−</button><output>${rank}</output><button type="button" data-roster-rank="${root}.${index}.${slot}" data-delta="1" aria-label="Increase ${slot} rank">+</button></span>`;
  }).join("");
  return `<div class="roster-ranks"><small>Wiki ability ranks</small>${rows}</div>`;
}

function rosterRoleControls(loadout, path) {
  const roles = [["", "Role"], ["top", "Top"], ["jungle", "Jungle"], ["mid", "Mid"], ["bottom", "Bottom"], ["support", "Support"]];
  const role = loadout.role || "";
  const quest = Boolean(loadout.roleQuestComplete);
  return `<div class="roster-context-controls">
    <label><span>Role</span><select data-roster-role="${path}.role" aria-label="${escapeHtml(path)} role">${roles.map(([value, label]) => `<option value="${value}" ${role === value ? "selected" : ""}>${label}</option>`).join("")}</select></label>
    <button class="quest-toggle compact ${quest ? "active" : ""}" type="button" data-roster-quest="${path}" aria-pressed="${quest}" ${role ? "" : "disabled"}><i></i><span>${quest ? "Quest complete" : "Role quest"}</span></button>
  </div>`;
}

function stackControl(path, id, compact = false) {
  const spec = stackSpec(id);
  const value = Math.min(stackValue(path), spec.max);
  return `<div class="stack-control ${compact ? "compact" : ""}" aria-label="${escapeHtml(itemName(id))} stacks">
    <button type="button" data-stack-path="${path}" data-delta="-1" aria-label="Decrease stacks">−</button>
    <output>${value}/${spec.max}</output>
    <button type="button" data-stack-path="${path}" data-delta="1" aria-label="Increase stacks">+</button>
  </div>`;
}

function rosterCard(loadout, index, kind) {
  const isAlly = kind === "ally";
  const root = isAlly ? "allies" : "targets";
  const label = isAlly ? "ally" : "enemy";
  const statItemIds = loadout.items.slice(0, loadout.includeBoots ? 5 : 6);
  if (loadout.includeBoots && loadout.boots) statItemIds.push(loadout.boots);
  const stats = rosterChampionStats({ ...loadout, items: statItemIds });
  const champion = getChampion(loadout.champion);
  const effectToggle = isAlly
    ? `<button class="ally-toggle ${loadout.allyEffectsEnabled ? "active" : ""}" type="button" data-ally-effects="${index}" aria-pressed="${Boolean(loadout.allyEffectsEnabled)}"><i></i><span>${loadout.allyEffectsEnabled ? "Apply modeled effects" : "Effects off"}</span></button>`
    : "";
  const path = `${root}.${index}`;
  const rosterReady = Boolean(loadout.champion && bisReadyForPath(path));
  const itemSlotCount = loadout.includeBoots ? 5 : 6;
  return `<article class="target-card ${isAlly ? "ally-card" : ""}">
    <header>
      <button class="target-pick ${champion ? "" : "empty-pick"}" type="button" data-picker="champion" data-path="${root}.${index}.champion" aria-label="${champion ? `Change ${escapeHtml(loadout.champion)}` : `Choose ${label} champion`}">${champion ? `<img src="${championImage(loadout.champion)}" alt="" />` : "+"}</button>
      <div class="target-title"><button type="button" data-picker="champion" data-path="${root}.${index}.champion">${escapeHtml(loadout.champion || "Choose champion")}</button><span>${escapeHtml(champion?.title || `${isAlly ? "Ally" : "Enemy"} slot`)}</span></div>
      <div class="target-level"><button type="button" data-level="${root}.${index}.level" data-delta="-1" aria-label="Decrease level">−</button><output>Lv ${loadout.level}</output><button type="button" data-level="${root}.${index}.level" data-delta="1" aria-label="Increase level">+</button></div>
      <button class="remove-target" type="button" ${isAlly ? `data-remove-ally="${index}"` : `data-remove-target="${index}"`} aria-label="Remove ${escapeHtml(loadout.champion || `${label} slot`)}">×</button>
    </header>
    <div class="target-build">${loadout.items.slice(0, itemSlotCount).map((id, slot) => itemSlot(`${root}.${index}.items.${slot}`, id, true, true)).join("")}${loadout.includeBoots ? itemSlot(`${root}.${index}.boots`, loadout.boots, true, true) : ""}</div>
    <button class="boots-toggle ${loadout.includeBoots ? "active" : ""}" type="button" data-include-roster-boots="${root}.${index}" aria-pressed="${Boolean(loadout.includeBoots)}">${loadout.includeBoots ? "Boots included" : "No boots"}</button>
    ${rosterRoleControls(loadout, path)}
    <div class="roster-build-actions"><button class="optimize-build roster-optimize" type="button" data-optimize-roster="${path}" ${rosterReady && !state.optimizer.running ? "" : "disabled"}>Optimize build</button></div>
    ${rosterAbilityRankControls(loadout, index, root)}
    ${effectToggle}
    ${champion ? statMatrix(stats, null, true) : `<div class="matrix-placeholder">Choose a champion to show the full stat matrix.</div>`}
  </article>`;
}

function targetCard(target, index) {
  return rosterCard(target, index, "enemy");
}

function allyCard(ally, index) {
  return rosterCard(ally, index, "ally");
}

function segmented(label, values, active, attribute) {
  return `<div class="control-group"><span>${label}</span><div class="segmented">${values.map(([value, text]) => `<button type="button" data-fight="${attribute}" data-value="${value}" class="${String(active) === String(value) ? "active" : ""}">${text}</button>`).join("")}</div></div>`;
}

function stepper(label, value, attributes, minusDisabled = false, plusDisabled = false) {
  return `<div class="ability-step"><span>${label}</span><div><button type="button" ${attributes} data-delta="-1" ${minusDisabled ? "disabled" : ""}>−</button><output>${value}</output><button type="button" ${attributes} data-delta="1" ${plusDisabled ? "disabled" : ""}>+</button></div></div>`;
}

function renderAbilityPackage(champion) {
  const coverage = champion?.abilityCoverage;
  const formulaBySlot = new Map((champion?.abilities || []).map((ability) => [ability.slot, ability]));
  const ingestedBySlot = new Map((champion?.ingestedAbilities || []).map((ability) => [ability.slot, ability]));
  if (!formulaBySlot.size && !ingestedBySlot.size) return `<div class="ability-empty"><strong>Ability metadata unavailable.</strong><span>${coverage?.withheld?.length ? `${coverage.withheld.join("/")} could not be resolved unambiguously · ` : ""}Use the manual package below.</span></div>`;

  const rows = ABILITY_SLOTS.map((slot) => {
    const ability = formulaBySlot.get(slot);
    const ingested = ingestedBySlot.get(slot);
    if (!ability) {
      const description = ingested?.blurb || ingested?.description || "Ability metadata was ingested, but its exact combat formula is not reviewed yet.";
      return `<article class="ability-row ability-withheld" title="${escapeHtml(ingested?.description || description)}">
        <div class="ability-name"><img src="${abilityImage(ingested)}" alt="" /><b>${slot}</b><span><strong>${escapeHtml(ingested?.name || slot)}</strong><small>Wiki description ingested · numeric packet pending</small></span></div>
        <p class="ability-note">${escapeHtml(description)}</p>
      </article>`;
    }
    const input = abilityInput(ability.slot);
    const rankLabel = ability.slot === "P" ? "Level scales" : "Rank";
    const rankControl = ability.slot === "P"
      ? `<div class="ability-step fixed"><span>${rankLabel}</span><strong>Lv ${state.attacker.level}</strong></div>`
      : stepper(rankLabel, input.rank, `data-ability-rank="${ability.slot}"`, input.rank <= 0, input.rank >= ability.maxRank);
    const hitControl = ability.maxHits
      ? stepper("Mines hit", input.hits, `data-ability-hits="${ability.slot}"`, input.hits <= 1, input.hits >= ability.maxHits)
      : "";
    const variants = ability.variants.length > 1 ? `<div class="ability-variants">${ability.variants.map((variant, index) => `<button type="button" data-ability-variant="${ability.slot}" data-value="${index}" class="${input.variant === index ? "active" : ""}">${escapeHtml(variant.name)}</button>`).join("")}</div>` : `<small>${escapeHtml(ability.variants[0].name)}</small>`;
    const sourceLabel = ability.formulaSource === "Wiki-derived local cache" ? "Wiki-derived formula" : "Reviewed formula";
    return `<article class="ability-row">
      <div class="ability-name"><img src="${abilityImage(ability)}" alt="" /><b>${ability.slot}</b><span><strong>${escapeHtml(ability.name)}</strong>${variants}</span></div>
      ${rankControl}
      ${stepper(ability.slot === "P" ? "Procs" : "Casts", input.casts, `data-ability-casts="${ability.slot}"`, input.casts <= 0, input.casts >= 10)}
      ${hitControl}
      <small class="ability-source">${sourceLabel}</small>
    </article>`;
  }).join("");
  const reviewed = [...formulaBySlot.values()].filter((ability) => ability.formulaSource !== "Wiki-derived local cache").length;
  const wikiFormulas = [...formulaBySlot.values()].filter((ability) => ability.formulaSource === "Wiki-derived local cache" && ability.variants?.some((variant) => variant.packets?.length)).length;
  const wikiDescriptions = [...formulaBySlot.values()].filter((ability) => ability.formulaSource === "Wiki-derived local cache" && !ability.variants?.some((variant) => variant.packets?.length)).length;
  const withheld = coverage?.withheld?.filter((slot) => !formulaBySlot.has(slot)).length ? ` · pending ${coverage.withheld.filter((slot) => !formulaBySlot.has(slot)).join("/")}` : "";
  return `<div class="ability-package"><div class="ability-package-head"><div><strong>Ability catalogue</strong><span>${reviewed} reviewed formulas · ${wikiFormulas} Wiki formulas · ${wikiDescriptions} Wiki descriptions · ${ingestedBySlot.size}/5 metadata ingested${withheld}</span></div><small>${escapeHtml(champion.ingestedAbilities?.[0]?.source?.kind || champion.source?.label || "Patch data")}</small></div><div class="ability-rows" style="--ability-count:5">${rows}</div></div>`;
}

function roleQuestNote() {
  if (!state.attacker.role) return "Choose a role to apply its completed quest rules.";
  if (!state.attacker.roleQuestComplete) return "Role quest not completed.";
  if (state.attacker.role === "mid") return "+8% bonus AD and AP · Tier 3 boots use one of six slots.";
  if (state.attacker.role === "bottom") return "Six item slots · boots move into the dedicated quest slot.";
  if (state.attacker.role === "top") return "+600 XP · +12.5% future XP · level cap 20 · no item-slot change.";
  if (state.attacker.role === "support") return "Reserved ward / support quest slot · excluded from damage scoring.";
  if (state.attacker.role === "top") return "Level cap raised to 20 · no item-slot change.";
  return "No item-slot change for this role.";
}

function renderRoleControls() {
  const roles = [["top", "Top"], ["jungle", "Jungle"], ["mid", "Mid"], ["bottom", "Bottom"], ["support", "Support"]];
  return `<div class="role-rules">
    <div class="role-picker"><span>Role</span><div>${roles.map(([value, label]) => `<button type="button" data-role="${value}" class="${state.attacker.role === value ? "active" : ""}">${label}</button>`).join("")}</div></div>
    <button class="quest-toggle ${state.attacker.roleQuestComplete ? "active" : ""}" type="button" data-role-quest aria-pressed="${state.attacker.roleQuestComplete}" ${state.attacker.role ? "" : "disabled"}><i></i><span>Role quest complete</span></button>
    <p>${escapeHtml(roleQuestNote())}</p>
  </div>`;
}

function buildArray(side) {
  return side === "A" ? state.attacker.buildA : state.attacker.buildB;
}

function buildStackArray(side) {
  return side === "A" ? state.attacker.buildAStacks : state.attacker.buildBStacks;
}

function questBootPath(side) {
  return `attacker.questBoot${side}`;
}

function keystoneSlot(side) {
  const name = state.attacker[`keystone${side}`];
  const keystone = getKeystone(name);
  return `<div class="quest-item keystone-item"><span>Keystone</span><div class="slot-wrap">
    <button class="item-slot keystone-slot" type="button" data-picker="keystone" data-path="attacker.keystone${side}" aria-label="${keystone ? `Change ${escapeHtml(keystone.name)}` : "Add keystone"}">
      <span class="item-icon keystone-icon ${keystone ? "" : "empty"}">${keystone ? `<img src="${keystone.icon}" alt="" />` : `<span aria-hidden="true">+</span>`}</span>
      <small>${escapeHtml(keystone?.name || "Add keystone")}</small>
    </button>
  </div></div>`;
}

function renderBuildStrip(side) {
  const build = buildArray(side);
  const normalSlots = Array.from({ length: ordinarySlotCount(side) }, (_, index) => itemSlot(`attacker.build${side}.${index}`, build[index], false, true)).join("");
  const boot = includeBootsForSide(side)
    ? `<div class="quest-item"><span>${state.attacker.role === "mid" && usesQuestBootSlot() ? "Tier 3 boots" : "Boots"}</span>${itemSlot(questBootPath(side), state.attacker[`questBoot${side}`], false, true)}</div>`
    : "";
  const support = state.attacker.role === "support" && state.attacker.roleQuestComplete
    ? `<div class="utility-slot" title="This slot is not included in damage scoring"><span>Quest / wards</span><b>◆</b><small>Utility</small></div>`
    : "";
  return `<div class="complete-build build-${side.toLowerCase()}">
    <div class="complete-build-head"><strong>Build ${side}</strong><span>${ordinarySlotCount(side) + (includeBootsForSide(side) ? 1 : 0)} combat ${plural(ordinarySlotCount(side) + (includeBootsForSide(side) ? 1 : 0), "slot")} + keystone${support ? " + utility" : ""}</span><button class="boots-toggle ${includeBootsForSide(side) ? "active" : ""}" type="button" data-include-boots="${side}" aria-pressed="${includeBootsForSide(side)}">${includeBootsForSide(side) ? "Boots included" : "No boots"}</button></div>
    <div class="hero-slots">${normalSlots}${boot}${keystoneSlot(side)}${support}</div>
  </div>`;
}

function renderBuilder() {
  const attacker = state.attacker;
  const statsA = attackerChampionStats(buildAIds(), buildAStacks());
  const statsB = attackerChampionStats(buildBIds(), buildBStacks());
  const champion = getChampion(attacker.champion);
  const optimizePackageReady = optimizerDamagePackageReady();
  const optimizeReady = Boolean(attacker.champion && optimizePackageReady && state.targets.length && state.targets.every((target) => target.champion));
  const optimizerSummary = state.optimizer.summary
    ? `<div class="optimizer-summary ${state.optimizer.summary.withheld ? "withheld" : ""}" role="status" aria-live="polite"><strong>${state.optimizer.summary.tested.toLocaleString("en-US")} builds · ${one(state.optimizer.summary.elapsedMs)} ms${state.optimizer.summary.withheld ? " · NO BUILD APPLIED" : ""}</strong><span>${escapeHtml(state.optimizer.summary.label || "Build A now shows the complete highest-damage build.")}</span></div>`
    : "";
  $("builder").innerHTML = `
    <section class="board-section hero-section">
      <div class="section-bar"><h2>Champion to optimize</h2><small><i class="legend-a"></i>A <i class="legend-b"></i>B values in the matrix</small></div>
      <div class="hero-board">
        <div class="hero-identity">
          <button class="hero-pick ${champion ? "" : "empty-hero"}" type="button" data-picker="champion" data-path="attacker.champion">${champion ? `<img src="${championImage(attacker.champion)}" alt="" />` : `<b>+</b>`}<span>${champion ? "Change champion" : "Choose champion"}</span></button>
          <div><p>${escapeHtml(champion?.title || "Start here")}</p><h2>${escapeHtml(attacker.champion || "Choose a champion")}</h2>${champion ? `<div class="level-control"><span>Level</span><button type="button" data-level="attacker.level" data-delta="-1">−</button><output>${attacker.level}</output><button type="button" data-level="attacker.level" data-delta="1">+</button></div>` : ""}</div>
        </div>
        <div class="hero-matrix"><div class="matrix-head"><strong>Complete champion stats</strong><span>${attacker.comparisonEnabled ? "Build A / Build B" : "Build A"}</span></div>${champion ? statMatrix(statsA, attacker.comparisonEnabled ? statsB : null) : `<div class="matrix-placeholder hero-placeholder">Select the champion whose build you want to compare or optimize.</div>`}</div>
      </div>
      ${champion ? renderAbilityPackage(champion) : ""}
      <div class="hero-build">
        ${renderRoleControls()}
        <div class="build-label"><div><strong>Complete builds</strong><span>${optimizePackageReady ? "Every occupied slot is scored into the full enemy roster" : "Add a sourced skill rotation or manual damage package to optimize"}</span></div><button class="optimize-build" type="button" data-optimize-build title="${optimizePackageReady ? "Search the strongest complete Build A" : "No sourced damage package for this champion yet"}" ${optimizeReady && !state.optimizer.running ? "" : "disabled"}>${state.optimizer.running ? "Optimizing…" : "Optimize Build A"}</button></div>
        ${optimizerSummary}
        ${renderBuildStrip("A")}
        <button class="compare-toggle" type="button" data-toggle-compare>${attacker.comparisonEnabled ? "Hide Build B" : "+ Compare another full build"}</button>
        ${attacker.comparisonEnabled ? renderBuildStrip("B") : ""}
      </div>
    </section>
    <section class="board-section">
      <div class="section-bar"><h2>Enemy roster</h2><div class="section-actions"><small>${state.targets.length}/5 · every card includes full stats</small><button class="text-button" type="button" data-optimize-roster-all="targets" ${state.targets.some((target) => target.champion) && !state.optimizer.running ? "" : "disabled"}>Optimize all enemies</button><button class="text-button" type="button" data-add-target ${state.targets.length >= 5 ? "disabled" : ""}>+ Add enemy</button></div></div>
      <div class="target-grid">${state.targets.length ? state.targets.map(targetCard).join("") : `<div class="empty-roster">Add an enemy champion to begin.</div>`}</div>
    </section>
    <section class="board-section">
      <div class="section-bar"><h2>Allied context</h2><div class="section-actions"><small>${state.allies.length}/4 · buffs are opt-in and sourced</small><button class="text-button" type="button" data-optimize-roster-all="allies" ${state.allies.some((ally) => ally.champion) && !state.optimizer.running ? "" : "disabled"}>Optimize all allies</button><button class="text-button" type="button" data-add-ally ${state.allies.length >= 4 ? "disabled" : ""}>+ Add ally</button></div></div>
      <div class="target-grid">${state.allies.length ? state.allies.map(allyCard).join("") : `<div class="empty-roster">Add an ally to include their build and any explicitly modeled outgoing effect.</div>`}</div>
    </section>
    <section class="board-section">
      <div class="section-bar"><h2>Time window</h2><small>Applied to every target</small></div>
      <div class="fight-controls">
        ${segmented("Rotations", [[1,"1"],[2,"2"],[3,"3"],[4,"4"],[5,"5"],[6,"6"]], state.fight.rotations, "rotations")}
        ${windowControl()}
        <div class="control-group"><span>Auto-attack uptime</span><label class="uptime-control"><input type="range" min="0" max="100" step="5" value="${Math.round(state.fight.aaUptime * 100)}" data-fight-range="aaUptime" /><output>${Math.round(state.fight.aaUptime * 100)}%</output></label></div>
        <div class="auto-count"><span>Expected autos per rotation</span><strong><i class="legend-a"></i>A ${autoAttacksForStats(statsA)}${attacker.comparisonEnabled ? ` <i class="legend-b"></i>B ${autoAttacksForStats(statsB)}` : ""}</strong><small>attack speed × time × 0.92 × uptime</small></div>
      </div>
    </section>`;
}

function ludenDamage(ap, targetCount, targetIndex, hasLuden) {
  if (!hasLuden || targetIndex >= Math.min(6, targetCount)) return 0;
  const proc = 75 + 0.05 * ap;
  return targetIndex === 0 ? proc * (1 + 0.2 * Math.max(6 - targetCount, 0)) : proc;
}

function windowControl() {
  const [windowMin, windowMax] = engine.fightLimits.fight_duration;
  const presets = [3.5, 8, windowMax].map((value) => [value, `${one(value)}s`]);
  return `<div class="control-group"><span>Window per rotation</span><div class="duration-control"><div class="segmented">${presets.map(([value, text]) => `<button type="button" data-fight="duration" data-value="${value}" class="${state.fight.duration === value ? "active" : ""}">${text}</button>`).join("")}</div><label><input type="range" min="${windowMin}" max="${windowMax}" step="0.5" value="${state.fight.duration}" data-fight-range="duration" /><output>${one(state.fight.duration)}s</output></label></div></div>`;
}

function autoAttacksForStats(stats, combatant = state.attacker) {
  if (!combatant.champion || state.fight.aaUptime <= 0) return 0;
  const activeSeconds = state.fight.duration * Math.max(0, Math.min(1, state.fight.aaUptime));
  return Math.floor(Math.max(0.4, stats.attackSpeed) * activeSeconds * 0.92);
}

function effectiveMagicResistance(targetMr, build) {
  return Math.max(targetMr * (1 - build.percentPen / 100) - build.pen, 0);
}

function effectivePhysicalArmor(targetArmor, build) {
  return Math.max(targetArmor * (1 - build.percentArmorPen / 100) - build.lethality, 0);
}

function rankedValue(values, rank, levelScaled = false) {
  if (!Array.isArray(values) || !values.length) return 0;
  const index = levelScaled ? state.attacker.level - 1 : rank - 1;
  const selected = values[Math.max(0, Math.min(values.length - 1, index))];
  if (Array.isArray(selected)) return Number(selected[Math.max(0, Math.min(selected.length - 1, state.attacker.level - 1))] || 0);
  return Number(selected || 0);
}

function abilityDamageRows(attackerStats, targetStats) {
  const champion = getChampion(state.attacker.champion);
  const baseChampion = championStats(state.attacker.champion, state.attacker.level);
  return (champion?.abilities || []).flatMap((ability) => {
    const input = abilityInput(ability.slot);
    if (input.casts <= 0 || (ability.slot !== "P" && input.rank <= 0)) return [];
    const variant = ability.variants[input.variant] || ability.variants[0];
    const levelScaled = ability.slot === "P" && variant.levelBase;
    const rank = ability.slot === "P" ? 1 : input.rank;
    const base = rankedValue(variant.levelBase || variant.base, rank, levelScaled);
    const apRatio = rankedValue(variant.ap, rank, levelScaled);
    const adRatio = rankedValue(variant.ad, rank, levelScaled);
    const bonusAdRatio = rankedValue(variant.bonusAd, rank, levelScaled);
    const targetMaxHpRatio = rankedValue(variant.targetMaxHp, rank, levelScaled);
    const targetCurrentHpRatio = rankedValue(variant.targetCurrentHp, rank, levelScaled);
    const targetMissingHpRatio = rankedValue(variant.targetMissingHp, rank, levelScaled);
    const oneHit = base
      + apRatio * attackerStats.ap
      + adRatio * attackerStats.ad
      + bonusAdRatio * Math.max(0, attackerStats.ad - baseChampion.ad)
      + targetMaxHpRatio * targetStats.hp
      + targetCurrentHpRatio * targetStats.hp
      + targetMissingHpRatio * Math.max(0, targetStats.hp * 0.15);
    const hits = ability.maxHits ? input.hits : 1;
    const hitFactor = ability.subsequentMultiplier ? 1 + Math.max(0, hits - 1) * ability.subsequentMultiplier : hits;
    const raw = oneHit * hitFactor * input.casts;
    const detailParts = [`${input.casts} ${plural(input.casts, ability.slot === "P" ? "proc" : "cast")}`];
    if (ability.maxHits) detailParts.push(`${hits} ${plural(hits, "mine")}`);
    if (ability.variants.length > 1) detailParts.push(variant.name);
    const packets = variant.packets?.length ? variant.packets : [{ type: variant.type }];
    return packets.map((packet) => {
      const spec = typeof packet === "string" ? { type: packet } : packet;
      const targetValue = spec.targetScale === "targetMaxHp" || spec.targetScale === "targetCurrentHp" ? targetStats.hp : spec.targetScale === "targetMissingHp" ? 0 : 1;
      return { source: `${ability.slot} · ${ability.name}`, detail: detailParts.join(" · "), raw: raw * targetValue / Number(spec.targetScaleDivisor || 1), type: spec.type };
    });
  });
}

function addBreakdown(map, source, detail, damage, kind = "ability") {
  if (!(damage > 0)) return;
  const key = `${kind}:${source}:${detail}`;
  const row = map.get(key) || { source, detail, damage: 0, kind };
  row.damage += damage;
  map.set(key, row);
}

function allyStatBonuses() {
  return state.allies.filter((ally) => ally.champion && ally.allyEffectsEnabled).reduce((total, ally) => {
    // This mirrors the sourced frontend boundary in src/calculator/ally_effects.py:
    // Staff of Flowing Water applies its 40 AP + 15 haste window after the
    // ally heals or shields the attacker immediately before the fight.
    if (ally.items.includes(6616)) {
      total.ap += 40;
      total.haste += 15;
    }
    return total;
  }, { ap: 0, haste: 0 });
}

function calculateBuild(buildIds, rotations = state.fight.rotations, stackCounts = [], options = {}) {
  const build = buildStats(buildIds, stackCounts);
  const hasLiandry = buildIds.includes(6653);
  const hasShadowflame = buildIds.includes(4645);
  const hasLuden = buildIds.includes(6655);
  const combatant = options.combatant || state.attacker;
  const targetLoadouts = options.targetLoadouts || state.targets;
  const attackerStats = attackerChampionStats(buildIds, stackCounts, combatant);
  if (combatant === state.attacker) {
    const allyBonuses = options.allyBonuses || allyStatBonuses();
    attackerStats.ap += Number(allyBonuses.ap || 0);
    attackerStats.haste += Number(allyBonuses.haste || 0);
  }
  const autosPerRotation = autoAttacksForStats(attackerStats, combatant);
  const profile = options.profile || state.attacker;
  const useAbilities = options.useAbilities ?? (combatant === state.attacker && profile.useAbilities !== false);
  let cumulative = 0;
  const ledger = [];
  const breakdown = new Map();
  const recordBreakdown = (source, detail, damage, kind = "ability") => {
    if (!options.summaryOnly) addBreakdown(breakdown, source, detail, damage, kind);
  };

  for (let rotation = 1; rotation <= rotations; rotation += 1) {
    const steady = rotation > 1;
    const sufferingAmp = hasLiandry ? (steady ? 1.06 : 1) : 1;
    const burnTicks = steady ? 3 * 1.06 : 1.02 + 1.04 + 1.06;
    let rotationDamage = 0;

    targetLoadouts.forEach((target, targetIndex) => {
      const targetStats = options.targetStats?.[targetIndex] || championStats(target.champion, target.level, target.items, target.itemStacks);
      const effectiveMr = effectiveMagicResistance(targetStats.mr, build);
      const effectiveArmor = effectivePhysicalArmor(targetStats.armor, build);
      const magicMultiplier = 100 / (100 + effectiveMr);
      const physicalMultiplier = 100 / (100 + effectiveArmor);
      const rows = useAbilities ? abilityDamageRows(attackerStats, targetStats) : [];
      if (profile.baseDamage || profile.apRatio) rows.push({ source: "Manual · magic package", detail: "Entered below", raw: profile.baseDamage + profile.apRatio * attackerStats.ap, type: "magical" });
      if (profile.physicalDamage || profile.adRatio) rows.push({ source: "Manual · physical package", detail: "Entered below", raw: profile.physicalDamage + profile.adRatio * attackerStats.ad, type: "physical" });
      const triggersAbilityItems = rows.length > 0;
      if (targetIndex === 0 && autosPerRotation > 0) {
        const expectedCritMultiplier = 1 + (attackerStats.crit / 100) * 0.75;
        rows.push({ source: "Auto attacks", detail: `${autosPerRotation} ${plural(autosPerRotation, "attack")} · ${one(state.fight.duration)}s at ${Math.round(state.fight.aaUptime * 100)}% uptime`, raw: autosPerRotation * attackerStats.ad * expectedCritMultiplier, type: "physical", kind: "auto" });
      }
      let targetMagicDamage = 0;

      rows.forEach((row) => {
        const multiplier = row.type === "magical" ? magicMultiplier : row.type === "physical" ? physicalMultiplier : 1;
        const mitigated = row.raw * multiplier;
        recordBreakdown(row.source, row.detail, mitigated, row.kind || "ability");
        rotationDamage += mitigated;
        if (row.type === "magical") targetMagicDamage += mitigated;
        if (hasLiandry && sufferingAmp > 1 && row.type !== "true") {
          const ampDamage = mitigated * (sufferingAmp - 1);
          rotationDamage += ampDamage;
          if (row.type === "magical") targetMagicDamage += ampDamage;
          recordBreakdown("Liandry’s Torment · Suffering", `${percent((sufferingAmp - 1) * 100)} ability amplification`, ampDamage, "item");
        }
      });

      const burnRaw = hasLiandry && triggersAbilityItems ? 0.02 * targetStats.hp * burnTicks : 0;
      const burn = burnRaw * magicMultiplier;
      if (burn > 0) {
        rotationDamage += burn;
        targetMagicDamage += burn;
        recordBreakdown("Liandry’s Torment · Torment", `${one(burnTicks)} burn ticks`, burn, "item");
      }
      const ludenRaw = ludenDamage(attackerStats.ap, targetLoadouts.length, targetIndex, hasLuden && triggersAbilityItems);
      const luden = ludenRaw * magicMultiplier;
      if (luden > 0) {
        rotationDamage += luden;
        targetMagicDamage += luden;
        recordBreakdown("Luden’s Echo · Echo", targetIndex === 0 ? "Primary / returned charges" : "Secondary charge", luden, "item");
      }
      if (hasShadowflame && options.lowHealth && targetMagicDamage > 0) {
        const cinderbloom = targetMagicDamage * .2;
        rotationDamage += cinderbloom;
        recordBreakdown("Shadowflame · Cinderbloom", "Conditional: target below 40% HP", cinderbloom, "item");
      }
    });

    cumulative += rotationDamage;
    ledger.push({ rotation, rotationDamage, cumulative });
  }
  return { build, attackerStats, ledger, cumulative, breakdown: [...breakdown.values()] };
}

function buildIdsForSide(side) {
  const ids = buildArray(side)
    .slice(0, ordinarySlotCount(side))
    .filter((id) => id && !ALL_ROLE_BOOTS.has(Number(id)));
  if (includeBootsForSide(side) && state.attacker[`questBoot${side}`]) {
    ids.push(state.attacker[`questBoot${side}`]);
  }
  return ids;
}

function buildStacksForSide(side) {
  const stacks = buildStackArray(side)
    .slice(0, ordinarySlotCount(side))
    .filter((_, index) => !ALL_ROLE_BOOTS.has(Number(buildArray(side)[index])));
  if (includeBootsForSide(side) && state.attacker[`questBoot${side}`]) stacks.push(0);
  return stacks;
}

function buildAIds() { return buildIdsForSide("A"); }
function buildBIds() { return buildIdsForSide("B"); }
function buildAStacks() { return buildStacksForSide("A"); }
function buildBStacks() { return buildStacksForSide("B"); }

function resultReason(winnerName, winnerIds, winner, loser) {
  const apLead = winner.build.ap - loser.build.ap;
  const adLead = winner.build.ad - loser.build.ad;
  const attackSpeedLead = winner.build.attackSpeed - loser.build.attackSpeed;
  const critLead = winner.build.crit - loser.build.crit;
  const penLead = winner.build.pen - loser.build.pen;
  const percentPenLead = winner.build.percentPen - loser.build.percentPen;
  const lethalityLead = winner.build.lethality - loser.build.lethality;
  const armorPenLead = winner.build.percentArmorPen - loser.build.percentArmorPen;
  const averageHp = state.targets.length ? state.targets.reduce((sum, target) => sum + championStats(target.champion, target.level, target.items, target.itemStacks).hp, 0) / state.targets.length : 0;
  if (winnerIds.includes(6653) && !winnerName.includes(itemName(6653))) {
    return `<strong>${escapeHtml(winnerName)}</strong> wins because Liandry’s max-health burn repeats across ${state.targets.length} ${plural(state.targets.length, "enemy")} averaging ${fmt(averageHp)} HP.`;
  }
  if (winnerIds.includes(6653) && !winnerIds.includes(4645)) {
    return `<strong>${escapeHtml(winnerName)}</strong> wins because its max-health burn repeats across ${state.targets.length} ${plural(state.targets.length, "enemy")} averaging ${fmt(averageHp)} HP.`;
  }
  const advantages = [];
  if (apLead > 0) advantages.push(`${one(apLead)} more AP`);
  if (adLead > 0) advantages.push(`${one(adLead)} more AD`);
  if (attackSpeedLead > 0) advantages.push(`${one(attackSpeedLead)}% more attack speed`);
  if (critLead > 0) advantages.push(`${one(critLead)}% more crit`);
  if (percentPenLead > 0) advantages.push(`${one(percentPenLead)}% more magic penetration`);
  if (penLead > 0) advantages.push(`${one(penLead)} more flat magic penetration`);
  if (armorPenLead > 0) advantages.push(`${one(armorPenLead)}% more armor penetration`);
  if (lethalityLead > 0) advantages.push(`${one(lethalityLead)} more lethality`);
  return `<strong>${escapeHtml(winnerName)}</strong> wins ${advantages.length ? `through ${advantages.join(" and ")}` : "on the selected stats and damage package"}.`;
}

function renderResistanceOutput(aBuild, bBuild) {
  const host = $("resistanceOutput");
  if (!aBuild || !state.targets.length) {
    host.innerHTML = "";
    return;
  }
  const rows = state.targets.map((target) => {
    const stats = championStats(target.champion, target.level, target.items, target.itemStacks);
    const armor = `${one(effectivePhysicalArmor(stats.armor, aBuild))}${bBuild ? ` / ${one(effectivePhysicalArmor(stats.armor, bBuild))}` : ""}`;
    const mr = `${one(effectiveMagicResistance(stats.mr, aBuild))}${bBuild ? ` / ${one(effectiveMagicResistance(stats.mr, bBuild))}` : ""}`;
    return `<tr><td>${escapeHtml(target.champion)}</td><td>${one(stats.armor)} → ${armor}</td><td>${one(stats.mr)} → ${mr}</td></tr>`;
  }).join("");
  host.innerHTML = `<div class="resistance-head"><span>Effective defenses</span><b>% pen → flat pen</b></div><div class="resistance-table-wrap"><table><thead><tr><th>Enemy</th><th>Armor → A${bBuild ? " / B" : ""}</th><th>MR → A${bBuild ? " / B" : ""}</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderDamageBreakdown(aResult, bResult) {
  const host = $("damageBreakdown");
  if (!aResult) {
    host.innerHTML = "";
    host.hidden = true;
    return;
  }
  host.hidden = false;
  const rows = new Map();
  const ingest = (result, side) => result.breakdown.forEach((entry) => {
    const key = `${entry.source}:${entry.detail}`;
    const row = rows.get(key) || { source: entry.source, detail: entry.detail, a: 0, b: 0, kind: entry.kind };
    row[side] += entry.damage;
    rows.set(key, row);
  });
  ingest(aResult, "a");
  if (bResult) ingest(bResult, "b");

  const lowA = buildAIds().includes(4645) ? calculateBuild(buildAIds(), state.fight.rotations, buildAStacks(), { lowHealth: true }) : null;
  const lowB = bResult && buildBIds().includes(4645) ? calculateBuild(buildBIds(), state.fight.rotations, buildBStacks(), { lowHealth: true }) : null;
  const conditionalA = lowA?.breakdown.find((row) => row.source.includes("Cinderbloom"))?.damage || 0;
  const conditionalB = lowB?.breakdown.find((row) => row.source.includes("Cinderbloom"))?.damage || 0;
  if (conditionalA || conditionalB) rows.set("conditional:cinderbloom", { source: "Shadowflame · Cinderbloom", detail: "Conditional bonus below 40% HP · not included in TDD above", a: conditionalA, b: conditionalB, kind: "conditional" });

  const body = [...rows.values()].map((row) => {
    const delta = row.a - row.b;
    const value = (amount) => row.kind === "conditional" && amount > 0 ? `+${fmt(amount)}` : fmt(amount);
    const comparison = bResult ? `<td>${value(row.b)}</td><td class="${delta > .5 ? "delta-a" : delta < -.5 ? "delta-b" : ""}">${Math.abs(delta) < .5 ? "—" : `${delta > 0 ? "+" : ""}${fmt(delta)}`}</td>` : "";
    return `<tr class="${row.kind === "item" || row.kind === "conditional" ? "item-damage-row" : ""}"><td><strong>${escapeHtml(row.source)}</strong><small>${escapeHtml(row.detail)}</small></td><td>${value(row.a)}</td>${comparison}</tr>`;
  }).join("");
  const comparisonHead = bResult ? `<th><i class="legend-b"></i>Build B</th><th>A − B</th>` : "";
  const comparisonTotal = bResult ? `<td>${fmt(bResult.cumulative)}</td><td>${Math.abs(aResult.cumulative - bResult.cumulative) < .5 ? "—" : `${aResult.cumulative > bResult.cumulative ? "+" : ""}${fmt(aResult.cumulative - bResult.cumulative)}`}</td>` : "";
  host.innerHTML = `<header><div><p class="eyebrow">Damage breakdown</p><h2>Every skill, proc and burn</h2></div><span>${state.targets.length} ${plural(state.targets.length, "target")} · ${state.fight.rotations} ${plural(state.fight.rotations, "rotation")}</span></header>
    <div class="damage-table-wrap"><table class="damage-table"><thead><tr><th>Source</th><th><i class="legend-a"></i>Build A</th>${comparisonHead}</tr></thead><tbody>${body}<tr class="damage-total"><td><strong>Total damage dealt</strong><small>After selected enemy resistances</small></td><td>${fmt(aResult.cumulative)}</td>${comparisonTotal}</tr></tbody></table></div>`;
}

function engineItemOptions(ids, stacks = []) {
  const options = {};
  ids.forEach((id, index) => {
    const item = getItem(id);
    const definition = item && engine.itemOptions[item.name];
    if (!item || !definition?.options?.glory_stacks) return;
    options[item.name] = { glory_stacks: Number(stacks[index] || 0) };
  });
  return options;
}

function engineBuild(side) {
  const ids = buildArray(side).slice(0, ordinarySlotCount(side)).filter(Boolean);
  const stacks = buildStacksForSide(side);
  const bootId = includeBootsForSide(side)
    ? (state.attacker[`questBoot${side}`] || ids.find((id) => ALL_ROLE_BOOTS.has(Number(id))) || 0)
    : 0;
  const itemIds = ids.filter((id) => !ALL_ROLE_BOOTS.has(Number(id)));
  const itemStacks = itemIds.map((id) => {
    const originalIndex = ids.indexOf(id);
    return stacks[originalIndex] || 0;
  });
  return {
    boots: bootId ? itemName(bootId) : "",
    include_boots: includeBootsForSide(side),
    items: itemIds.map((id) => itemName(id)).filter(Boolean),
    item_options: engineItemOptions(itemIds, itemStacks),
    keystone: state.attacker[`keystone${side}`] || "",
  };
}

function engineChampionOptions() {
  const champion = state.attacker.champion;
  const definition = engine.championOptions[champion];
  if (!definition?.options) return {};
  const options = {};
  definition.options.forEach((option) => {
    if (option.key === "passive_procs" && activeAbilityKit().some((ability) => ability.slot === "P")) {
      options[option.key] = abilityInput("P").casts;
    } else if (option.key === "mines_hit" && activeAbilityKit().some((ability) => ability.slot === "E")) {
      options[option.key] = abilityInput("E").hits;
    } else if (option.key === "r_sweet_spot" && activeAbilityKit().some((ability) => ability.slot === "R")) {
      options[option.key] = abilityInput("R").variant === 0;
    }
  });
  return options;
}

function engineAbilityRanks() {
  const requested = {};
  activeAbilityKit().forEach((ability) => {
    if (ability.slot === "P") return;
    const input = abilityInput(ability.slot);
    const levelCap = ability.slot === "R"
      ? (state.attacker.level >= 16 ? 3 : state.attacker.level >= 11 ? 2 : state.attacker.level >= 6 ? 1 : 0)
      : Math.min(5, Math.floor((state.attacker.level + 1) / 2));
    requested[ability.slot] = Math.max(0, Math.min(ability.maxRank, levelCap, Number(input.rank) || 0));
  });
  let remaining = Math.min(state.attacker.level, 18);
  const ranks = {};
  // Preserve the user's allocation as far as the level budget allows, then
  // trim the last-ranked basics first. Every request reaching the engine is
  // therefore legal even while a user is clicking through a new level.
  const slots = ["Q", "W", "E", "R"];
  slots.forEach((slot) => {
    ranks[slot] = Math.min(requested[slot] || 0, remaining);
    remaining -= ranks[slot];
  });
  return ranks;
}

function engineTarget(target) {
  const selectedBoot = Number(target.boots || 0);
  const itemIds = target.items
    .slice(0, target.includeBoots ? 5 : 6)
    .filter(Boolean)
    .filter((id) => !ALL_ROLE_BOOTS.has(Number(id)));
  return {
    champion: target.champion,
    level: target.level,
    items: itemIds.map((id) => itemName(id)).filter(Boolean),
    boots: target.includeBoots && selectedBoot ? itemName(selectedBoot) : "",
    include_boots: Boolean(target.includeBoots),
    item_options: engineItemOptions(itemIds, target.itemStacks),
    role: target.role || "",
    role_quest_complete: Boolean(target.roleQuestComplete),
    ability_ranks: Object.fromEntries(Object.entries(target.abilityRanks || {}).map(([slot, rank]) => [slot, Number(rank) || 0])),
  };
}

function engineAlly(ally) {
  return {
    ...engineTarget(ally),
    ally_effects_enabled: Boolean(ally.allyEffectsEnabled),
  };
}

function engineFightPayload(side) {
  const build = engineBuild(side);
  const payload = {
    champion: state.attacker.champion,
    level: state.attacker.level,
    ...build,
    target_health: 1000,
    target_bonus_health: 0,
    target_armor: 100,
    target_mr: 100,
    enemies: state.targets.filter((target) => target.champion).map(engineTarget),
    allies: state.allies.filter((ally) => ally.champion).map(engineAlly),
    role: state.attacker.role || "",
    role_quest_complete: state.attacker.roleQuestComplete,
    include_actives: true,
    include_crossover: state.attacker.comparisonEnabled || state.fight.rotations > 1,
    champion_options: engineChampionOptions(),
    ability_ranks: engineAbilityRanks(),
  };
  if (state.fight.aaUptime > 0) {
    payload.fight_mode = "time_based";
    payload.fight_duration = Math.max(1, state.fight.duration * state.fight.rotations);
    payload.include_auto_attacks = true;
    payload.auto_attack_uptime = state.fight.aaUptime;
  } else {
    payload.fight_mode = "one_rotation";
    payload.fight_duration = state.fight.duration;
    payload.include_auto_attacks = false;
    payload.auto_attack_uptime = 0;
  }
  return payload;
}

function exactStatMatrix(result) {
  const stats = result?.champion_stats;
  if (!stats) return null;
  return {
    baseHp: Number(stats.base_health || 0),
    bonusHp: Number(stats.bonus_health || 0),
    hp: Number(stats.health || 0),
    mana: Number(stats.max_mana || 0),
    ad: Number(stats.attack_damage || 0),
    ap: Number(stats.ability_power || 0),
    armor: Number(stats.armor || 0),
    mr: Number(stats.magic_resistance || 0),
    haste: Number(stats.ability_haste || 0),
    pen: Number(stats.magic_penetration_flat || 0),
    percentPen: Number(stats.magic_penetration_percent || 0),
    lethality: Number(stats.lethality || 0),
    percentArmorPen: Number(stats.armor_penetration_percent || 0),
    attackSpeed: Number(stats.attack_speed || 0),
    crit: Number(stats.critical_strike_chance || 0),
    moveSpeed: Number(stats.move_speed || 0),
  };
}

function renderEngineUnavailable() {
  const availability = engine.availability.get(state.attacker.champion) || {};
  const reason = availability.blockers?.[0] || "This champion has no reviewed event-ordered combat model yet.";
  $("resultContext").textContent = "Engine unavailable";
  $("winnerVisual").innerHTML = `<div class="result-empty-mark">—</div><div><span>Calculation withheld</span><strong>${escapeHtml(state.attacker.champion)}</strong><b>Reviewed model required</b></div>`;
  $("scoreGrid").innerHTML = `<div class="empty-score single-score">${escapeHtml(reason)}</div>`;
  $("why").textContent = "The calculator does not substitute a stat-only estimate for an unreviewed mechanic.";
  $("threshold").innerHTML = "<span>Crossover</span><strong>Unavailable until the attacker is reviewed</strong>";
  $("resistanceOutput").innerHTML = "";
  $("mechanicsOutput").innerHTML = "";
  $("rotationTable").innerHTML = "";
  $("damageBreakdown").innerHTML = "";
}

function exactPoint(result) {
  const curve = Array.isArray(result?.comparison_curve) ? result.comparison_curve : [];
  const selected = curve.find((row) => Number(row.rotation) === Number(state.fight.rotations));
  return selected || { total_damage: Number(result?.total_damage || 0), dps: Number(result?.total_damage || 0) / Math.max(1, state.fight.duration) };
}

function exactBreakdown(result) {
  return Object.values(result?.breakdown || {}).map((entry) => ({
    source: entry.name || entry.slot || "Damage source",
    detail: entry.casts ? `${entry.casts} cast${entry.casts === 1 ? "" : "s"}` : entry.count ? `${entry.count} hit${entry.count === 1 ? "" : "s"}` : "Event-ordered output",
    damage: Number(entry.total_damage || 0),
  }));
}

function renderExactStatMatrix(aResult, bResult) {
  const host = document.querySelector(".hero-matrix");
  if (!host) return;
  const aStats = exactStatMatrix(aResult);
  if (!aStats) return;
  host.innerHTML = `<div class="matrix-head"><strong>Complete champion stats</strong><span>${bResult ? "Build A / Build B" : "Build A"}</span></div>${statMatrix(aStats, bResult ? exactStatMatrix(bResult) : null)}`;
}

function renderExactResistance(aResult, bResult) {
  const rows = (aResult?.targets || []).map((entry, index) => {
    const target = entry.target || {};
    const result = entry.result || {};
    const other = bResult?.targets?.[index]?.result;
    const armor = `${one(result.effective_armor)}${other ? ` / ${one(other.effective_armor)}` : ""}`;
    const mr = `${one(result.effective_mr)}${other ? ` / ${one(other.effective_mr)}` : ""}`;
    const shield = Number(target.starting_defenses?.magic_shield || 0);
    return `<tr><td>${escapeHtml(target.champion || "Target")}</td><td>${armor}</td><td>${mr}${shield ? ` · ${fmt(shield)} shield` : ""}</td></tr>`;
  }).join("");
  $("resistanceOutput").innerHTML = rows ? `<div class="resistance-head"><span>Effective defenses</span><b>After build penetration</b></div><div class="resistance-table-wrap"><table><thead><tr><th>Enemy</th><th>Armor${bResult ? " · A / B" : ""}</th><th>MR${bResult ? " · A / B" : ""}</th></tr></thead><tbody>${rows}</tbody></table></div>` : "";
}

function renderExactBreakdown(aResult, bResult) {
  $("damageBreakdown").hidden = false;
  const rows = new Map();
  const ingest = (result, side) => exactBreakdown(result).forEach((entry) => {
    const key = `${entry.source}:${entry.detail}`;
    const row = rows.get(key) || { ...entry, a: 0, b: 0 };
    row[side] += entry.damage;
    rows.set(key, row);
  });
  ingest(aResult, "a");
  if (bResult) ingest(bResult, "b");
  const body = [...rows.values()].map((row) => `<tr><td><strong>${escapeHtml(row.source)}</strong><small>${escapeHtml(row.detail)}</small></td><td>${fmt(row.a)}</td>${bResult ? `<td>${fmt(row.b)}</td><td>${Math.abs(row.a - row.b) < .5 ? "—" : `${row.a > row.b ? "+" : ""}${fmt(row.a - row.b)}`}</td>` : ""}</tr>`).join("");
  const mainTotal = (result) => Number(result?.combat?.breakdown?.find((entry) => entry.participant_id === "main")?.total_damage ?? result?.total_damage ?? 0);
  const aMainTotal = mainTotal(aResult);
  const bMainTotal = bResult ? mainTotal(bResult) : 0;
  const totalB = bResult ? `<td>${fmt(bMainTotal)}</td><td>${Math.abs(aMainTotal - bMainTotal) < .5 ? "—" : `${aMainTotal > bMainTotal ? "+" : ""}${fmt(aMainTotal - bMainTotal)}`}</td>` : "";
  const combatRows = (aResult?.combat?.breakdown || []).map((entry) => {
    const survival = (aResult.combat.participants || []).find((participant) => participant.participant_id === entry.participant_id)?.survival || {};
    const status = survival.survived_window ? "alive at window end" : `defeated at ${one(survival.death_time)}s`;
    const appliedIncoming = Number(survival.health_damage || 0) + Number(survival.shield_absorbed || 0);
    return `<tr><td><strong>${escapeHtml(`${entry.champion} · ${entry.team}`)}</strong><small>${escapeHtml(status)} · ${fmt(survival.effective_health || 0)} eHP · ${fmt(survival.healing_received || 0)} healing</small></td><td>${fmt(entry.total_damage)}</td><td>${fmt(appliedIncoming)}</td>${bResult ? `<td>—</td><td>—</td>` : ""}</tr>`;
  }).join("");
  const combatSection = combatRows ? `<section class="combat-participant-ledger"><header><div><p class="eyebrow">Team-fight ledger</p><h2>Every selected champion participates</h2></div><span>Event-ordered output · applied incoming damage · eHP</span></header><div class="damage-table-wrap"><table class="damage-table"><thead><tr><th>Participant</th><th><i class="legend-a"></i>Output before defeat</th><th>Applied incoming damage</th>${bResult ? `<th><i class="legend-b"></i>Build B</th><th>A − B</th>` : ""}</tr></thead><tbody>${combatRows}</tbody></table></div></section>` : "";
  const labels = new Map((aResult?.combat?.participants || []).map((participant) => [participant.participant_id, `${participant.champion} · ${participant.team}`]));
  const eventRows = (aResult?.combat?.events || []).filter((event) => Number(event.damage || 0) > 0 || event.skipped_reason).map((event) => `<tr><td><strong>${one(event.time)}s · ${escapeHtml(labels.get(event.attacker) || event.attacker || "Participant")}</strong><small>${escapeHtml(labels.get(event.target) || event.target || "Target")} · ${escapeHtml(event.source || "event")} · ${escapeHtml(event.event_precision || "exact")}${event.skipped_reason ? ` · ${escapeHtml(event.skipped_reason)}` : ""}</small></td><td>${fmt(event.damage || 0)}</td></tr>`).join("");
  const eventSection = eventRows ? `<section class="combat-event-ledger"><header><div><p class="eyebrow">Event order</p><h2>Outgoing and incoming events</h2></div><span>Every selected champion · timestamped</span></header><div class="damage-table-wrap"><table class="damage-table"><thead><tr><th>Event</th><th>Applied damage</th></tr></thead><tbody>${eventRows}</tbody></table></div></section>` : "";
  $("damageBreakdown").innerHTML = `${combatSection}${eventSection}<header><div><p class="eyebrow">Damage breakdown</p><h2>Every skill, proc and burn</h2></div><span>${state.targets.length} ${plural(state.targets.length, "target")} · ${state.fight.rotations} ${plural(state.fight.rotations, "rotation")}</span></header><div class="damage-table-wrap"><table class="damage-table"><thead><tr><th>Source</th><th><i class="legend-a"></i>Build A</th>${bResult ? `<th><i class="legend-b"></i>Build B</th><th>A − B</th>` : ""}</tr></thead><tbody>${body}<tr class="damage-total"><td><strong>Total damage before defeat</strong><small>Post-mitigation output from the coupled participant timeline</small></td><td>${fmt(aMainTotal)}</td>${totalB}</tr></tbody></table></div>`;
}

function fightOrderAbility(slot) {
  const champion = getChampion(state.attacker.champion);
  return (champion?.abilities || []).find((ability) => ability.slot === slot)
    || (champion?.ingestedAbilities || []).find((ability) => ability.slot === slot)
    || null;
}

function fightOrderTimeline(result) {
  const duration = Math.max(1, Number(state.fight.duration) || 10);
  const events = (result?.cast_timeline || []).map((event) => ({ ...event, time: Math.min(Number(event.time) || 0, duration) }));
  if (!events.length) return "";
  const laneGap = 13; // % of track width a cast occupies before neighbours stack upward
  const laneEnds = [];
  const chips = events.map((event) => {
    const pct = (event.time / duration) * 100;
    let lane = laneEnds.findIndex((end) => pct - end >= laneGap);
    if (lane === -1) lane = laneEnds.push(pct) - 1;
    else laneEnds[lane] = pct;
    const ability = fightOrderAbility(event.slot);
    const icon = ability ? abilityImage(ability) : "";
    const name = event.name || ability?.name || event.slot;
    return `<span class="fight-cast" style="--x:${pct.toFixed(2)}%;--lane:${lane}" title="${escapeHtml(name)} · ${one(event.time)}s">${icon ? `<img src="${icon}" alt="${escapeHtml(name)}" />` : `<i>${escapeHtml(String(event.slot || "?").charAt(0))}</i>`}<b>${escapeHtml(event.slot || "")}</b></span>`;
  }).join("");
  const labelGap = 7; // % of axis width between time labels before the later one is dropped
  const labels = [];
  [...events.map((event) => event.time), duration].forEach((time) => {
    const pct = (time / duration) * 100;
    if (!labels.some((label) => Math.abs(label.pct - pct) < labelGap)) labels.push({ time, pct });
  });
  const axis = labels.map((label) => `<span style="--x:${label.pct.toFixed(2)}%"><i></i>${one(label.time)}s</span>`).join("");
  return `<div class="fight-timeline" style="--lane-count:${laneEnds.length}"><div class="fight-lanes">${chips}</div><div class="fight-axis">${axis}</div></div><small class="fight-caption">One rotation · ${one(duration)}s window</small>`;
}

function renderExactMechanics(aResult, bResult) {
  const result = aResult;
  const coverage = result?.timeline_coverage || {};
  const timeline = fightOrderTimeline(result);
  const notes = [...(result?.notes || []), coverage.note].filter(Boolean);
  $("mechanicsOutput").innerHTML = `<div class="mechanics-head"><span>Reviewed engine output</span><b>${escapeHtml(coverage.certification || "event ordered")}</b></div><article class="mechanic-row"><div><strong>Fight order</strong>${timeline || "<p>No cast timeline returned</p>"}</div><span class="modelled">Calculated</span></article>${notes.map((note) => `<article class="mechanic-row"><div><strong>Model note</strong><p>${escapeHtml(note)}</p></div><span class="text-only">Boundary</span></article>`).join("")}`;
}

function renderExactResults(aResult, bResult) {
  const aPoint = exactPoint(aResult);
  const bPoint = bResult ? exactPoint(bResult) : null;
  const participantTotal = (result, fallback) => Number(result?.combat?.breakdown?.find((entry) => entry.participant_id === "main")?.total_damage ?? fallback);
  const aTotal = participantTotal(aResult, Number(aPoint.total_damage || 0));
  const bTotal = bPoint ? participantTotal(bResult, Number(bPoint.total_damage || 0)) : 0;
  const tied = bResult && Math.abs(aTotal - bTotal) < .5;
  const aWins = !bResult || aTotal > bTotal;
  const winner = bResult ? (aWins ? "Build A" : "Build B") : "Build A";
  const outputLabel = "Reviewed engine output";
  const edge = bResult && Math.min(aTotal, bTotal) > 0 ? Math.abs(aTotal / bTotal - 1) * 100 : 0;
  $("resultContext").textContent = `${state.targets.length} ${plural(state.targets.length, "enemy")} · ${state.fight.rotations} ${plural(state.fight.rotations, "rotation")}`;
  $("winnerVisual").innerHTML = tied ? `<div></div><div><span>${outputLabel}</span><strong>Tie</strong><b>Less than 1 damage apart</b></div>` : `<img src="${championImage(state.attacker.champion)}" alt="" /><div><span>${bResult ? "Better here" : outputLabel}</span><strong>${winner}</strong><b>${bResult ? `${percent(edge)} more total damage` : "Event-ordered result"}</b></div>`;
  $("scoreGrid").innerHTML = [{ name: "Build A", total: aTotal, point: aPoint, winner: aWins && !tied }, ...(bResult ? [{ name: "Build B", total: bTotal, point: bPoint, winner: !aWins && !tied }] : [])].map((entry) => `<div class="score ${entry.winner ? "winner" : ""} ${bResult ? "" : "single-score"}"><header><img src="${championImage(state.attacker.champion)}" alt="" /><span>${entry.name}</span></header><strong>${fmt(entry.total)}</strong><small>TDD · ${fmt(entry.point.dps || entry.total / Math.max(1, state.fight.duration))} DPS</small></div>`).join("");
  renderExactStatMatrix(aResult, bResult);
  renderExactResistance(aResult, bResult);
  const certification = aResult.timeline_coverage?.certification || "event ordered";
  const shield = Number(aResult.shield_absorbed || 0);
  const resource = Number(aResult.resource_remaining || 0);
  const mainParticipant = (aResult?.combat?.participants || []).find((participant) => participant.participant_id === "main");
  const mainSurvival = mainParticipant?.survival;
  const combatNote = mainSurvival ? ` · ${fmt(mainSurvival.effective_health || 0)} eHP · ${mainSurvival.survived_window ? "alive through the window" : `defeated at ${one(mainSurvival.death_time)}s`}` : "";
  $("why").innerHTML = `<strong>${escapeHtml(certification)}</strong> · ${fmt(shield)} shield damage absorbed · ${fmt(resource)} resource remaining${combatNote}.`;
  $("threshold").innerHTML = `<span>Crossover</span><strong>${bResult ? (tied ? "No meaningful difference at this window" : `${escapeHtml(winner)} leads at the selected window`) : `${fmt(aTotal)} event-ordered damage`}</strong>`;
  const aCurve = aResult.comparison_curve || [{ rotation: state.fight.rotations, total_damage: aTotal }];
  const bCurve = bResult?.comparison_curve || [];
  $("tableA").textContent = "Build A";
  $("tableB").textContent = bResult ? "Build B" : "—";
  $("rotationTable").innerHTML = aCurve.map((row, index) => {
    const other = bCurve[index];
    const lead = other ? (Math.abs(row.total_damage - other.total_damage) < .5 ? "Tie" : row.total_damage > other.total_damage ? "Build A" : "Build B") : "Build A";
    return `<tr><td>${row.rotation}</td><td>${fmt(row.total_damage)}</td><td>${other ? fmt(other.total_damage) : "—"}</td><td>${lead}</td></tr>`;
  }).join("");
  renderExactMechanics(aResult, bResult);
  renderExactBreakdown(aResult, bResult);
}

function scheduleEngineCalculation() {
  if (engine.pendingTimer) clearTimeout(engine.pendingTimer);
  if (!engine.ready || !state.attacker.champion || !state.targets.length || !state.targets.every((target) => target.champion)) return;
  if (!engine.reviewed.has(state.attacker.champion) && !engine.backend.has(state.attacker.champion)) return;
  engine.pendingTimer = setTimeout(() => {
    const requestId = ++engine.requestId;
    engine.pending = true;
    const builds = state.attacker.comparisonEnabled ? ["A", "B"] : ["A"];
    Promise.all(builds.map((side) => fetch("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(engineFightPayload(side)),
    }).then((response) => response.json())))
      .then((results) => {
        if (requestId !== engine.requestId) return;
        const failure = results.find((result) => result.error);
        if (failure) {
          $("resultContext").textContent = "Engine boundary";
          $("why").textContent = failure.error;
          return;
        }
        engine.responses = { a: results[0], b: results[1] || null };
        renderExactResults(engine.responses.a, engine.responses.b);
      })
      .catch((error) => {
        if (requestId === engine.requestId) $("why").textContent = `Engine request failed: ${error.message}`;
      })
      .finally(() => { if (requestId === engine.requestId) engine.pending = false; });
  }, 40);
}

function renderResults() {
  $("resultFootnote").textContent = `DPS uses ${one(state.fight.duration)}s per rotation · autos use ${Math.round(state.fight.aaUptime * 100)}% uptime · TDD sums selected targets.`;
  const scenarioReady = state.attacker.champion && state.targets.length && state.targets.every((target) => target.champion);
  const hasA = buildAIds().some(Boolean);
  const hasB = state.attacker.comparisonEnabled && buildBIds().some(Boolean);
  if (!scenarioReady || !hasA) {
    $("resultContext").textContent = "Waiting for scenario";
    $("winnerVisual").innerHTML = `<div class="result-empty-mark">+</div><div><span>Nothing calculated</span><strong>Build a scenario</strong><b>Champion · builds · enemies</b></div>`;
    $("scoreGrid").innerHTML = `<div class="empty-score">Build A</div><div class="empty-score">${state.attacker.comparisonEnabled ? "Build B" : "Comparison optional"}</div>`;
    $("why").textContent = "Choose a champion, add Build A and select at least one enemy.";
    $("threshold").innerHTML = `<span>Crossover</span><strong>Waiting for complete inputs</strong>`;
    renderResistanceOutput(null, null);
    renderMechanicsOutput(0, 0);
    renderDamageBreakdown(null, null);
    $("rotationTable").innerHTML = "";
    return;
  }
  const reviewedAttacker = engine.reviewed.has(state.attacker.champion);
  const aCurrent = calculateBuild(buildAIds(), state.fight.rotations, buildAStacks());
  const aAll = state.fight.rotations === 6 ? aCurrent : calculateBuild(buildAIds(), 6, buildAStacks());
  const aTotal = aCurrent.cumulative;
  const seconds = state.fight.rotations * state.fight.duration;
  $("resultContext").textContent = `${state.targets.length} ${plural(state.targets.length, "enemy")} · ${state.fight.rotations} ${plural(state.fight.rotations, "rotation")}`;

  if (!hasB) {
    $("winnerVisual").innerHTML = `<img src="${championImage(state.attacker.champion)}" alt="" /><div><span>${reviewedAttacker ? "Modeled output" : "Wiki-derived estimate"}</span><strong>Build A</strong><b>${buildAIds().filter(Boolean).length} items scored</b></div>`;
    $("scoreGrid").innerHTML = `<div class="score winner single-score"><header><img src="${championImage(state.attacker.champion)}" alt="" /><span>Build A</span></header><strong>${fmt(aTotal)}</strong><small>TDD · ${fmt(aTotal / seconds)} DPS</small></div>`;
    renderResistanceOutput(aCurrent.build, null);
    $("why").innerHTML = reviewedAttacker
      ? `<strong>Build A</strong> is scored as one complete build. Enable Build B only for a full-build comparison.`
      : `<strong>Build A</strong> is scored with the Wiki-derived champion packets and item event catalogue. The exact registry has not yet certified this champion.`;
    $("threshold").innerHTML = `<span>Six-rotation total</span><strong>${fmt(aAll.cumulative)} modeled damage</strong>`;
    $("tableA").textContent = "Build A";
    $("tableB").textContent = "—";
    $("rotationTable").innerHTML = aAll.ledger.map((row) => `<tr><td>${row.rotation}</td><td>${fmt(row.cumulative)}</td><td>—</td><td>Build A</td></tr>`).join("");
    renderMechanicsOutput(aTotal, 0);
    renderDamageBreakdown(aCurrent, null);
    return;
  }

  const bCurrent = calculateBuild(buildBIds(), state.fight.rotations, buildBStacks());
  const bAll = state.fight.rotations === 6 ? bCurrent : calculateBuild(buildBIds(), 6, buildBStacks());
  const bTotal = bCurrent.cumulative;
  const tied = Math.abs(aTotal - bTotal) < 0.5;
  const aWins = aTotal > bTotal;
  const winner = aWins ? { ...aAll, cumulative: aTotal } : { ...bAll, cumulative: bTotal };
  const loser = aWins ? { ...bAll, cumulative: bTotal } : { ...aAll, cumulative: aTotal };
  const winnerIds = aWins ? buildAIds() : buildBIds();
  const edge = loser.cumulative > 0 ? Math.abs(winner.cumulative / loser.cumulative - 1) * 100 : 0;
  const aName = "Build A";
  const bName = "Build B";

  $("winnerVisual").innerHTML = tied
    ? `<div></div><div><span>Dead even</span><strong>Tie</strong><b>Less than 1 damage apart</b></div>`
    : `<img src="${championImage(state.attacker.champion)}" alt="" /><div><span>Better here</span><strong>${aWins ? "Build A" : "Build B"}</strong><b>${percent(edge)} more total damage</b></div>`;
  $("scoreGrid").innerHTML = [
    { total: aTotal, name: aName, winner: aWins && !tied },
    { total: bTotal, name: bName, winner: !aWins && !tied },
  ].map((entry) => `<div class="score ${entry.winner ? "winner" : ""}"><header><img src="${championImage(state.attacker.champion)}" alt="" /><span>${entry.name}</span></header><strong>${fmt(entry.total)}</strong><small>TDD · ${fmt(entry.total / seconds)} DPS</small></div>`).join("");
  renderResistanceOutput(aCurrent.build, bCurrent.build);
  $("why").innerHTML = tied ? "Both builds deal effectively the same damage in this setup." : resultReason(aWins ? "Build A" : "Build B", winnerIds, winner, loser);

  const leads = aAll.ledger.map((row, rowIndex) => Math.sign(row.cumulative - bAll.ledger[rowIndex].cumulative));
  const firstLead = leads[0];
  const crossoverIndex = leads.findIndex((lead, rowIndex) => rowIndex > 0 && lead !== 0 && lead !== firstLead);
  let thresholdText;
  if (crossoverIndex >= 0) {
    thresholdText = `${escapeHtml(leads[crossoverIndex] > 0 ? aName : bName)} takes over at rotation ${crossoverIndex + 1}`;
  } else {
    thresholdText = firstLead === 0 ? "No meaningful difference through 6 rotations" : `${escapeHtml(firstLead > 0 ? aName : bName)} stays ahead through 6 rotations`;
  }
  $("threshold").innerHTML = `<span>Crossover</span><strong>${thresholdText}</strong>`;
  $("tableA").textContent = aName;
  $("tableB").textContent = bName;
  $("rotationTable").innerHTML = aAll.ledger.map((row, rowIndex) => {
    const bRow = bAll.ledger[rowIndex];
    const lead = Math.abs(row.cumulative - bRow.cumulative) < .5 ? "Tie" : row.cumulative > bRow.cumulative ? aName : bName;
    return `<tr><td>${row.rotation}</td><td>${fmt(row.cumulative)}</td><td>${fmt(bRow.cumulative)}</td><td>${escapeHtml(lead)}</td></tr>`;
  }).join("");
  renderMechanicsOutput(aTotal, bTotal);
  renderDamageBreakdown(aCurrent, bCurrent);
}

function itemOccurrence(id) {
  const occurrences = [];
  state.attacker.buildA.forEach((itemId, index) => { if (itemId === id) occurrences.push({ path: `attacker.buildA.${index}`, build: "A" }); });
  if (state.attacker.questBootA === id) occurrences.push({ path: "attacker.questBootA", build: "A" });
  if (state.attacker.comparisonEnabled) {
    state.attacker.buildB.forEach((itemId, index) => { if (itemId === id) occurrences.push({ path: `attacker.buildB.${index}`, build: "B" }); });
    if (state.attacker.questBootB === id) occurrences.push({ path: "attacker.questBootB", build: "B" });
  }
  return occurrences[0] || null;
}

function mechanicDetail(id, occurrence, aTotal, bTotal) {
  const stacks = occurrence ? stackValue(occurrence.path) : 0;
  if (id === 1082) return `${stacks}/10 Glory · +${stacks * 4} AP from stacks`;
  if (id === 3041) return `${stacks}/25 Glory · +${stacks * 5} AP${stacks >= 10 ? " · 10% bonus move speed active" : " · move speed activates at 10"}`;
  if (id === 3089) {
    const apA = buildStats(buildAIds(), buildAStacks());
    const apB = buildStats(buildBIds(), buildBStacks());
    const ap = occurrence?.build === "B" ? apB : apA;
    const finalAp = occurrence?.build === "B" ? attackerChampionStats(buildBIds(), buildBStacks()).ap : attackerChampionStats(buildAIds(), buildAStacks()).ap;
    const quest = state.attacker.role === "mid" && state.attacker.roleQuestComplete ? ` · Mid quest × 1.08 = ${one(finalAp)} final AP` : "";
    return `Magical Opus: ${one(ap.apBeforeMultiplier)} AP before the passive × 1.30 = ${one(ap.ap)} AP${quest}.`;
  }
  if (id === 6653) return "Torment burn and the 2% → 6% Suffering ramp are applied automatically over time.";
  if (id === 6655) return `Six Echo charges are distributed across ${state.targets.length} ${plural(state.targets.length, "enemy")}; unused charges return to the primary target at 20% damage.`;
  if (id === 4645) {
    if (occurrence?.build === "A") {
      const low = calculateBuild(buildAIds(), state.fight.rotations, buildAStacks(), { lowHealth: true }).cumulative;
      return `Above 40%: ${fmt(aTotal)} TDD · Below 40%: ${fmt(low)} TDD with Cinderbloom.`;
    }
    if (occurrence?.build === "B") {
      const low = calculateBuild(buildBIds(), state.fight.rotations, buildBStacks(), { lowHealth: true }).cumulative;
      return `Above 40%: ${fmt(bTotal)} TDD · Below 40%: ${fmt(low)} TDD with Cinderbloom.`;
    }
    return "Cinderbloom’s 20% damage increase is conditional on the enemy already being below 40% health.";
  }
  return getItem(id)?.passiveText || "No conditional item effect in the patch data.";
}

function renderMechanicsOutput(aTotal, bTotal) {
  const ids = [...new Set([...buildAIds(), ...(state.attacker.comparisonEnabled ? buildBIds() : [])].filter(Boolean))];
  const modeled = new Set([1082, 3041, 3089, 6653, 6655, 4645]);
  $("mechanicsOutput").innerHTML = ids.length ? `<div class="mechanics-head"><span>Item-specific output</span><b>${ids.length} selected</b></div>${ids.map((id) => {
    const item = getItem(id);
    const occurrence = itemOccurrence(id);
    return `<article class="mechanic-row"><img src="${itemImage(id)}" alt="" /><div><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(mechanicDetail(id, occurrence, aTotal, bTotal))}</p></div><span class="${modeled.has(id) ? "modelled" : "text-only"}">${modeled.has(id) ? "Calculated" : "Patch text"}</span></article>`;
  }).join("")}` : "";
}

function scenarioSentence() {
  if (!state.attacker.champion) return "Choose a champion, a build and an enemy roster to begin.";
  const buildA = buildAIds().map(getItem).filter(Boolean).map((item) => item.name);
  const names = state.targets.map((target) => target.champion);
  const allyNames = state.allies.map((ally) => ally.champion).filter(Boolean);
  const roster = names.length <= 1 ? (names[0] || "no enemies") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
  const compareText = state.attacker.comparisonEnabled && buildBIds().some(Boolean) ? `, comparing <strong>Build A</strong> with <strong>Build B</strong>` : "";
  const targetText = names.length ? `, into ${escapeHtml(roster)}` : "";
  const allyText = allyNames.length ? ` · ${allyNames.length} ${plural(allyNames.length, "ally")} in context` : "";
  const keystoneA = getKeystone(state.attacker.keystoneA);
  const keystoneText = keystoneA ? ` running ${escapeHtml(keystoneA.name)}` : "";
  return `<strong>${escapeHtml(state.attacker.champion)} level ${state.attacker.level}</strong>${buildA.length ? ` with ${escapeHtml(buildA.join(" + "))}` : ""}${keystoneText}${compareText}${targetText} over ${state.fight.rotations} ${plural(state.fight.rotations, "rotation")} · ${one(state.fight.duration)}s each · ${Math.round(state.fight.aaUptime * 100)}% auto uptime${allyText}.`;
}

function render() {
  renderBuilder();
  renderResults();
  $("scenarioSentence").innerHTML = scenarioSentence();
  scheduleEngineCalculation();
}

function openPicker(type, path) {
  pickerContext = { type, path };
  $("pickerKind").textContent = type === "champion" ? "Champion roster" : type === "keystone" ? "Rune keystones" : "Item catalogue";
  $("pickerTitle").textContent = type === "champion" ? "Choose a champion" : type === "keystone" ? "Choose a keystone" : "Choose an item";
  $("pickerSearch").value = "";
  renderPicker("");
  $("picker").showModal();
  requestAnimationFrame(() => $("pickerSearch").focus());
}

function createPickerContent(entries, selected, query, includeEmpty) {
  const fragment = document.createDocumentFragment();
  const makeText = (name, detail) => {
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    const description = document.createElement("small");
    title.textContent = name;
    description.textContent = detail;
    copy.append(title, description);
    return copy;
  };

  if (includeEmpty) {
    const isKeystone = pickerContext.type === "keystone";
    const button = document.createElement("button");
    const icon = document.createElement("span");
    button.type = "button";
    button.className = `picker-option ${(isKeystone ? !selected : Number(selected) === 0) ? "selected" : ""}`;
    button.dataset.pickerValue = isKeystone ? "" : "0";
    icon.className = "empty-icon";
    icon.textContent = "×";
    button.append(icon, makeText(isKeystone ? "No keystone" : "Empty slot", isKeystone ? "Remove keystone" : "Remove item"));
    fragment.append(button);
  }

  entries.forEach((entry) => {
    const isKeystone = pickerContext.type === "keystone";
    const value = pickerContext.type === "item" ? entry.id : entry.name;
    const imageUrl = pickerContext.type === "champion" ? championImage(entry.name) : isKeystone ? entry.icon : itemImage(entry.id);
    const detail = pickerContext.type === "champion"
      ? `${entry.tags.join(" · ")} · ${entry.resource}`
      : isKeystone
        ? `${entry.path} keystone${entry.implemented ? "" : " · not modeled yet"}`
        : itemStatsLine(entry);
    const button = document.createElement("button");
    const image = document.createElement("img");
    button.type = "button";
    button.className = `picker-option ${String(selected) === String(value) ? "selected" : ""} ${isKeystone && !entry.implemented ? "locked" : ""}`;
    button.dataset.pickerValue = String(value);
    if (isKeystone && !entry.implemented) {
      button.disabled = true;
      button.title = "This keystone is not modeled yet; its numbers would be estimates.";
    }
    image.src = imageUrl;
    image.alt = "";
    image.loading = "lazy";
    button.append(image, makeText(entry.name, detail));
    fragment.append(button);
  });

  if (!fragment.childNodes.length) {
    const empty = document.createElement("p");
    empty.className = "picker-empty";
    empty.textContent = `No matches for “${query}”.`;
    fragment.append(empty);
  }
  return fragment;
}

function renderPicker(query) {
  if (!pickerContext) return;
  const normalized = query.trim().toLowerCase();
  const selected = pathValue(pickerContext.path);
  const source = pickerContext.type === "champion" ? DATA.champions : pickerContext.type === "keystone" ? engine.keystones : DATA.items;
  const entries = source.filter((entry) => {
    if (!entry.name.toLowerCase().includes(normalized)) return false;
    if (pickerContext.type !== "item") return true;
    const dedicatedBoot = ALL_ROLE_BOOTS.has(Number(entry.id));
    if (pickerContext.path.endsWith(".boots") || pickerContext.path.includes("questBoot")) {
      return dedicatedBoot;
    }
    if (pickerContext.path.includes(".items.")) return !dedicatedBoot;
    if (pickerContext.path.includes("questBoot")) return questBootIds().includes(entry.id);
    if (pickerContext.path.match(/^attacker\.build[AB]\./)) return !dedicatedBoot;
    return true;
  });
  const grid = $("pickerGrid");
  grid.replaceChildren(createPickerContent(
    entries,
    selected,
    query,
    pickerContext.type !== "champion" && !normalized,
  ));
}

function closePicker() {
  $("picker").close();
  pickerContext = null;
}

function idsForBis(path, candidateId) {
  const side = path.includes("buildB") || path.includes("questBootB") ? "B" : "A";
  const ids = buildArray(side).slice(0, ordinarySlotCount(side));
  if (path.match(/^attacker\.build[AB]\./)) ids[Number(path.split(".").at(-1))] = candidateId;
  if (usesQuestBootSlot()) ids.push(path.includes("questBoot") ? candidateId : state.attacker[`questBoot${side}`]);
  return ids;
}

function stacksForBis(path, candidateId) {
  const side = path.includes("buildB") || path.includes("questBootB") ? "B" : "A";
  const paths = Array.from({ length: ordinarySlotCount(side) }, (_, index) => `attacker.build${side}.${index}`);
  const stacks = paths.map((itemPath) => itemPath === path && Number(pathValue(path)) !== Number(candidateId) ? 0 : stackValue(itemPath));
  if (usesQuestBootSlot()) stacks.push(0);
  return stacks;
}

function bisProfile() {
  const selectedAbilities = activeAbilityKit().filter((ability) => abilityInput(ability.slot).casts > 0 && (ability.slot === "P" || abilityInput(ability.slot).rank > 0));
  if (selectedAbilities.length) {
    const wikiSelected = selectedAbilities.some((ability) => ability.formulaSource === "Wiki-derived local cache");
    if (wikiSelected) return { ...statOnlyProfile(state.attacker), useAbilities: true, exact: false, wiki: true };
    return { baseDamage: 0, apRatio: 0, physicalDamage: 0, adRatio: 0, useAbilities: true, label: "Selected skill rotation", exact: true };
  }
  const exact = state.attacker.baseDamage > 0 || state.attacker.apRatio > 0 || state.attacker.physicalDamage > 0 || state.attacker.adRatio > 0;
  if (exact) return { ...state.attacker, label: "Exact damage package", exact: true };
  return statOnlyProfile(state.attacker);
}

function statOnlyProfile(combatant) {
  const champion = getChampion(combatant.champion);
  const profile = BIS_PROFILES[combatant?.champion] || {};
  const roles = [...new Set([...(profile.roles || []), ...(champion?.tags || [])].map((role) => String(role).toUpperCase()))];
  const primary = bisRole({ roles });
  const label = { warden: "Warden", tank: "Tank", enchanter: "Enchanter", support: "Support", marksman: "Marksman", mage: "Mage", assassin: "Assassin", fighter: "Fighter" }[primary] || "Champion";
  return { baseDamage: 0, apRatio: 0, physicalDamage: 0, adRatio: 0, useAbilities: false, label: `Wiki-derived ${label} estimate`, exact: false, roles, wiki: Boolean(profile.name) };
}

function bisChampionProfile(combatant) {
  const champion = getChampion(combatant?.champion);
  const profile = BIS_PROFILES[combatant?.champion] || {};
  const roles = [...new Set([...(profile.roles || []), ...(champion?.tags || [])].map((role) => String(role).toUpperCase()))];
  return { ...profile, roles, champion };
}

function bisHasRole(profile, ...roles) {
  return roles.some((role) => profile.roles?.includes(role));
}

function bisRole(profile) {
  if (bisHasRole(profile, "WARDEN")) return "warden";
  if (bisHasRole(profile, "ENCHANTER")) return "enchanter";
  if (bisHasRole(profile, "TANK", "JUGGERNAUT")) return "tank";
  if (bisHasRole(profile, "MARKSMAN")) return "marksman";
  if (bisHasRole(profile, "ASSASSIN")) return "assassin";
  if (bisHasRole(profile, "MAGE", "ARTILLERY", "BURST")) return "mage";
  if (bisHasRole(profile, "FIGHTER", "DIVER")) return "fighter";
  if (bisHasRole(profile, "SUPPORT")) return "support";
  return "fighter";
}

function defaultAbilityRanks(combatant) {
  const level = Math.max(1, Math.min(18, Number(combatant?.level) || 1));
  const profile = bisChampionProfile(combatant);
  const ranks = { Q: 0, W: 0, E: 0, R: 0 };
  const basicSlots = ["Q", "W", "E"].filter((slot) => (profile.abilities?.[slot] || []).length);
  const ultimateRanks = level >= 16 ? 3 : level >= 11 ? 2 : level >= 6 ? 1 : 0;
  ranks.R = Math.min(ultimateRanks, Math.max(...(profile.abilities?.R || []).map((ability) => ability.maxRank || 3), 3));
  let points = Math.max(0, level - ranks.R);
  let cursor = 0;
  while (points > 0 && basicSlots.length) {
    const slot = basicSlots[cursor % basicSlots.length];
    const maxRank = Math.max(...(profile.abilities?.[slot] || []).map((ability) => ability.maxRank || 5), 5);
    if (ranks[slot] < maxRank) {
      ranks[slot] += 1;
      points -= 1;
    }
    cursor += 1;
    if (cursor > 30) break;
  }
  return ranks;
}

function bisRankFor(combatant, slot, maxRank) {
  const level = Math.max(1, Math.min(18, Number(combatant?.level) || 1));
  if (slot === "P") return level;
  const cap = slot === "R" ? (level >= 16 ? 3 : level >= 11 ? 2 : level >= 6 ? 1 : 0) : Math.min(5, Math.floor((level + 1) / 2));
  const hasRequested = Object.prototype.hasOwnProperty.call(combatant?.abilityRanks || {}, slot);
  const requested = hasRequested ? Number(combatant?.abilityRanks?.[slot]) : Number(defaultAbilityRanks(combatant)[slot] || 0);
  return Math.max(0, Math.min(maxRank || (slot === "R" ? 3 : 5), Number.isFinite(requested) ? requested : cap));
}

function bisPacketValue(packet, rank, level, stats, targetStats) {
  const valueAt = (values) => {
    if (!Array.isArray(values) || !values.length) return 0;
    const longLeveling = values.length > 6;
    const index = longLeveling ? Math.max(0, Math.min(values.length - 1, level - 1)) : Math.max(0, Math.min(values.length - 1, rank - 1));
    return Number(values[index] || 0);
  };
  const ratios = packet?.ratios || {};
  const ratioValue = (key, value) => valueAt(ratios[key]) * value;
  return valueAt(packet?.base)
    + ratioValue("ap", stats.ap)
    + ratioValue("ad", stats.ad)
    + ratioValue("bonusAd", Math.max(0, stats.ad - (stats.baseAd || 0)))
    + ratioValue("bonusHp", stats.bonusHp)
    + ratioValue("selfMaxHp", stats.hp)
    + ratioValue("targetMaxHp", targetStats.hp)
    + ratioValue("targetCurrentHp", targetStats.hp * 0.85)
    + ratioValue("targetMissingHp", targetStats.hp * 0.15)
    + ratioValue("armor", stats.armor)
    + ratioValue("bonusArmor", Math.max(0, stats.armor - (stats.baseArmor || 0)))
    + ratioValue("mr", stats.mr)
    + ratioValue("bonusMr", Math.max(0, stats.mr - (stats.baseMr || 0)));
}

function bisDamageMultiplier(type, attackerStats, targetStats) {
  if (String(type || "").toUpperCase().includes("TRUE")) return 1;
  if (String(type || "").toUpperCase().includes("MAGIC")) return 100 / (100 + effectiveMagicResistance(targetStats.mr, attackerStats));
  return 100 / (100 + effectivePhysicalArmor(targetStats.armor, attackerStats));
}

function bisAbilityDamage(combatant, stats, targetStats, duration = 10) {
  const profile = bisChampionProfile(combatant);
  const baseStats = championStats(combatant.champion, combatant.level);
  stats.baseAd ??= baseStats.ad;
  stats.baseArmor ??= baseStats.armor;
  stats.baseMr ??= baseStats.mr;
  const rows = [];
  const forms = profile.abilities || {};
  Object.entries(forms).forEach(([slot, abilities]) => {
    if (!Array.isArray(abilities) || !abilities.length) return;
    const rank = bisRankFor(combatant, slot, Math.max(...abilities.map((ability) => ability.maxRank || 1)));
    const formRows = abilities.map((ability) => {
      const packets = (ability.packets || []).map((packet) => ({ packet, value: bisPacketValue(packet, rank, combatant.level || 1, stats, targetStats) })).filter((entry) => entry.value > 0);
      const chosen = packets.sort((a, b) => b.value - a.value)[0];
      if (!chosen) return null;
      const cooldown = Number(ability.cooldown?.[Math.max(0, Math.min((ability.cooldown?.length || 1) - 1, rank - 1))] || 0);
      const casts = slot === "P" ? 1 : Math.max(1, Math.min(4, Math.floor(duration / Math.max(2, cooldown || (slot === "R" ? 30 : 8))) + 1));
      const persistentFactor = ability.signals?.persistent ? 1.25 : 1;
      return { ability, packet: chosen.packet, raw: chosen.value * casts * persistentFactor, casts };
    }).filter(Boolean);
    const strongest = formRows.sort((a, b) => b.raw - a.raw)[0];
    if (strongest) rows.push(strongest);
  });
  return rows;
}

function bisAutoDamage(combatant, stats, duration = 10) {
  const role = bisRole(bisChampionProfile(combatant));
  const uptime = { marksman: 0.82, fighter: 0.58, assassin: 0.45, tank: 0.38, warden: 0.32, enchanter: 0.2, support: 0.2, mage: 0.16 }[role] || 0.35;
  const attacks = Math.max(0, Math.max(0.4, stats.attackSpeed) * duration * uptime * 0.92);
  const critMultiplier = 1 + (stats.crit / 100) * 0.75;
  return { attacks, raw: attacks * stats.ad * critMultiplier, uptime };
}

function bisUtilityValue(combatant, stats, kind, duration = 10) {
  const profile = bisChampionProfile(combatant);
  return Object.entries(profile.abilities || {}).reduce((total, [slot, abilities]) => {
    if (!Array.isArray(abilities) || !abilities.length) return total;
    const rank = bisRankFor(combatant, slot, Math.max(...abilities.map((ability) => ability.maxRank || 1)));
    const values = abilities.map((ability) => {
      const packets = (ability[kind] || []).map((packet) => bisPacketValue(packet, rank, combatant.level || 1, stats, stats)).filter((value) => value > 0);
      if (!packets.length) return 0;
      const cooldown = Number(ability.cooldown?.[Math.max(0, Math.min((ability.cooldown?.length || 1) - 1, rank - 1))] || 0);
      const casts = slot === "P" ? 1 : Math.max(1, Math.min(4, Math.floor(duration / Math.max(2, cooldown || 8)) + 1));
      return Math.max(...packets) * casts;
    });
    return total + Math.max(...values, 0);
  }, 0);
}

function bisItemEffects(item) {
  const text = String(item?.passiveText || "").toLowerCase();
  const categories = new Set(item?.categories || []);
  const wiki = EFFECT_CATALOG[String(item?.id)] || {};
  const tags = new Set(wiki.tags || []);
  return {
    antiHeal: tags.has("healing_reduction") || /wounds|grievous/.test(text),
    burn: item?.id === 6653 || tags.has("damage_over_time") || /burn|damage over time/.test(text),
    damageAmp: item?.id === 6653 || tags.has("damage_amp") || /bonus damage|more damage|damage amp/.test(text),
    onHit: tags.has("on_hit") || categories.has("OnHit") || /on[- ]hit|attacks deal/.test(text),
    aura: categories.has("Aura") || tags.has("aura") || /nearby allies|nearby enemy/.test(text),
    allyAura: categories.has("Aura") || tags.has("aura") || /nearby allies|allied champions/.test(text),
    active: categories.has("Active") || tags.has("active") || /activate|grant nearby|shield/.test(text),
    healing: tags.has("healing") || categories.has("LifeSteal") || categories.has("HealthRegen"),
    allyShield: /shield(?:ing)? an ally|nearby allies|allied champions/.test(text),
    allyHealing: /heal(?:ing)? an ally|allied units|target allied champion|nearby allies/.test(text),
    eventOrder: wiki.eventOrder || [],
    defensive: categories.has("Health") || categories.has("Armor") || categories.has("MagicResist") || categories.has("SpellBlock"),
  };
}

function bisOutgoingSupport(combatant, stats, duration = 10) {
  const shields = bisUtilityValue(combatant, stats, "shields", duration);
  const heals = bisHealingPotential(combatant, stats, duration);
  const profile = bisChampionProfile(combatant);
  const control = Object.values(profile.abilities || {}).flat().reduce((total, ability) => total + (ability.signals?.control ? 1 : 0), 0);
  return shields * 2.2 + heals * 1.5 + control * 35;
}

function bisSupportItemValue(item, stats) {
  const effect = bisItemEffects(item);
  if (!effect.allyShield && !effect.allyHealing && !effect.allyAura) return 0;
  const sourcedEffect = (effect.allyShield ? 460 : 0) + (effect.allyHealing ? 420 : 0) + (effect.allyAura ? 180 : 0);
  return sourcedEffect + Number(item?.ap || 0) * 5 + Number(item?.haste || 0) * 12 + Number(item?.hp || 0) * 0.18;
}

function bisHealingPotential(combatant, stats, duration = 10) {
  const profile = bisChampionProfile(combatant);
  let exact = 0;
  Object.entries(profile.abilities || {}).forEach(([slot, abilities]) => {
    if (!Array.isArray(abilities) || !abilities.length) return;
    const rank = bisRankFor(combatant, slot, Math.max(...abilities.map((ability) => ability.maxRank || 1)));
    const values = abilities.map((ability) => {
      const packets = (ability.heals || [])
        .map((packet) => bisPacketValue(packet, rank, combatant.level || 1, stats, stats))
        .filter((value) => value > 0);
      if (!packets.length) return 0;
      const cooldown = Number(ability.cooldown?.[Math.max(0, Math.min((ability.cooldown?.length || 1) - 1, rank - 1))] || 0);
      const casts = slot === "P" ? 1 : Math.max(1, Math.min(4, Math.floor(duration / Math.max(2, cooldown || 8)) + 1));
      return Math.max(...packets) * casts;
    });
    exact += Math.max(...values, 0);
  });
  if (exact > 0) return exact;
  // Some Wiki entries describe healing without a numeric packet. Keep that
  // fallback deliberately small and signal-based instead of inventing HP regen.
  const signals = Object.values(profile.abilities || {}).flat().reduce((total, ability) => total + (ability.signals?.heal ? 1 : 0), 0);
  return signals * stats.hp * 0.025;
}

function bisIncomingPressure(opponents, candidateStats, duration = 10) {
  let physical = 0;
  let magical = 0;
  let trueDamage = 0;
  opponents.forEach((opponent) => {
    const opponentStats = championStats(opponent.champion, opponent.level, opponent.items, opponent.itemStacks);
    const rows = bisAbilityDamage(opponent, opponentStats, candidateStats, duration);
    rows.forEach((row) => {
      const type = String(row.packet?.damageType || "").toUpperCase();
      if (type.includes("MAGIC")) magical += row.raw;
      else if (type.includes("TRUE")) trueDamage += row.raw;
      else physical += row.raw;
    });
    physical += bisAutoDamage(opponent, opponentStats, duration).raw;
  });
  return { physical, magical, trueDamage };
}

function bisBuildScore(buildIds, combatant, opponents, path) {
  const duration = Math.max(3, Number(state.fight.duration) || 10);
  const stats = championStats(combatant.champion, combatant.level, buildIds, combatant.itemStacks || []);
  stats.baseAd = championStats(combatant.champion, combatant.level).ad;
  stats.baseArmor = championStats(combatant.champion, combatant.level).armor;
  stats.baseMr = championStats(combatant.champion, combatant.level).mr;
  const profile = bisChampionProfile(combatant);
  const role = bisRole(profile);
  const incoming = bisIncomingPressure(opponents, stats, duration);
  const pressureTotal = incoming.physical + incoming.magical + incoming.trueDamage;
  const physicalMitigation = 1 + stats.armor / 100;
  const magicalMitigation = 1 + stats.mr / 100;
  const mix = pressureTotal ? (incoming.physical / pressureTotal) / physicalMitigation + (incoming.magical / pressureTotal) / magicalMitigation + (incoming.trueDamage / pressureTotal) : 0;
  const effectiveHealth = mix > 0 ? stats.hp / mix : stats.hp;
  const ownRows = opponents.map((target) => {
    const targetStats = championStats(target.champion, target.level, target.items, target.itemStacks);
    const damage = bisAbilityDamage(combatant, stats, targetStats, duration).reduce((sum, row) => sum + row.raw * bisDamageMultiplier(row.packet?.damageType, stats, targetStats), 0);
    const targetShield = bisUtilityValue(target, targetStats, "shields", duration);
    return { damage: Math.max(0, damage - targetShield), shield: targetShield };
  });
  const ownAbilityDamage = ownRows.reduce((sum, value) => sum + value.damage, 0);
  const targetShields = ownRows.reduce((sum, value) => sum + value.shield, 0);
  const autos = bisAutoDamage(combatant, stats, duration);
  const effects = buildIds.map((id) => bisItemEffects(getItem(id)));
  const hasAbilityDamage = Object.values(profile.abilities || {}).flat().some((ability) => ability.signals?.hasDamage || ability.packets?.length);
  const hasHealing = bisHealingPotential(combatant, stats, duration);
  const ownShields = bisUtilityValue(combatant, stats, "shields", duration);
  const outgoingSupport = bisOutgoingSupport(combatant, stats, duration);
  const supportItems = buildIds.reduce((sum, id) => sum + bisSupportItemValue(getItem(id), stats), 0);
  const enemyPath = path.startsWith("targets.");
  const supportPath = path.startsWith("allies.") || (path === "attacker" && state.attacker.role === "support" && (role === "enchanter" || role === "warden"));
  const survivalPool = effectiveHealth + hasHealing * 0.7 + ownShields;
  const pressurePerSecond = pressureTotal / duration;
  const survivalSeconds = pressurePerSecond > 0 ? Math.min(duration, survivalPool / pressurePerSecond) : duration;
  const survivalFraction = Math.max(0, Math.min(1, survivalSeconds / duration));
  const targetHealing = opponents.reduce((sum, target) => sum + bisHealingPotential(target, championStats(target.champion, target.level, target.items, target.itemStacks), duration), 0);
  const antiHeal = effects.some((effect) => effect.antiHeal) && targetHealing > 0 ? targetHealing * 0.4 * Math.min(1, duration / 3) : 0;
  const liandry = effects.some((effect) => effect.burn) && hasAbilityDamage ? opponents.reduce((sum, target) => {
    const targetStats = championStats(target.champion, target.level, target.items, target.itemStacks);
    return sum + targetStats.hp * 0.06 * bisDamageMultiplier("MAGIC_DAMAGE", stats, targetStats);
  }, 0) + ownAbilityDamage * 0.06 : 0;
  const onHitBonus = effects.some((effect) => effect.onHit) ? autos.attacks * Math.max(8, stats.ad * 0.03) : 0;
  const teamUtility = effects.reduce((sum, effect, index) => sum + (effect.aura ? 38 : 0) + (effect.active ? 42 : 0) + (effect.healing ? 24 : 0), 0);
  const tradeOutput = (ownAbilityDamage + autos.raw + onHitBonus + liandry + antiHeal) * survivalFraction;
  let score;
  let metric;
  if (role === "tank" || role === "warden") {
    const allyPath = supportPath;
    const allyUtilityWeight = role === "warden" && allyPath ? 22 : 8;
    score = enemyPath
      ? tradeOutput * 0.85 + survivalPool * 0.62 + teamUtility * 10 + stats.haste * 10
      : effectiveHealth * (role === "warden" && allyPath ? 0.48 : 1) + (allyPath ? outgoingSupport * 1.9 + supportItems : teamUtility * allyUtilityWeight) + stats.haste * 10 + hasHealing * 0.8 + ownShields * 1.1 + ownAbilityDamage * 0.18;
    metric = enemyPath ? "trade output + survival window" : allyPath ? "outgoing protection + effective health" : "effective health + team utility";
  } else if (role === "enchanter" || role === "support") {
    const allyPath = supportPath;
    score = allyPath
      ? outgoingSupport * 2.4 + supportItems + ownAbilityDamage * 0.12 + effectiveHealth * 0.12 + stats.haste * 8
      : enemyPath ? tradeOutput * 0.8 + survivalPool * 0.55 + teamUtility * 8 + stats.haste * 10 : ownAbilityDamage * 0.45 + effectiveHealth * 0.45 + teamUtility * 10 + stats.haste * 12 + hasHealing * 1.1 + ownShields * 1.25;
    metric = allyPath ? "ally protection + sourced utility" : enemyPath ? "trade output + survival window" : "utility + effective health";
  } else if (role === "marksman") {
    score = enemyPath ? tradeOutput * 0.95 + survivalPool * 0.38 + stats.attackSpeed * 7 + stats.crit * 2 : ownAbilityDamage + autos.raw + onHitBonus + stats.attackSpeed * 7 + stats.crit * 2;
    metric = enemyPath ? "trade output + survival window" : "estimated 10s output";
  } else if (role === "mage" || role === "assassin") {
    score = enemyPath ? tradeOutput * 0.95 + survivalPool * 0.38 + stats.haste * 5 : ownAbilityDamage + autos.raw * 0.35 + liandry + antiHeal + stats.haste * 5;
    metric = enemyPath ? "trade output + survival window" : "estimated 10s output";
  } else {
    score = enemyPath ? tradeOutput * 0.9 + survivalPool * 0.45 + stats.haste * 5 : ownAbilityDamage * 0.75 + autos.raw * 0.65 + onHitBonus + effectiveHealth * 0.35 + stats.haste * 5;
    metric = enemyPath ? "trade output + survival window" : "damage + effective health";
  }
  const eventOrder = [];
  if (hasAbilityDamage) eventOrder.push("ability/attack hit");
  if (enemyPath && pressureTotal > 0) eventOrder.push("incoming damage and mitigation set the survival window");
  if (enemyPath) eventOrder.push("only damage dealt before defeat counts toward trade output");
  if (effects.some((effect) => effect.antiHeal)) eventOrder.push("apply 40% Wounds for 3s");
  if (effects.some((effect) => effect.burn)) eventOrder.push("Liandry burn after the damaging ability, then periodic ticks");
  if (hasHealing) eventOrder.push("healing resolves after incoming damage and modifiers");
  if (targetShields > 0) eventOrder.push(`target shields absorb ${fmt(targetShields)} before later damage`);
  if (ownShields > 0) eventOrder.push("champion shields resolve before subsequent incoming damage");
  const wikiEvents = effects.flatMap((effect) => effect.eventOrder || []).filter((value, index, values) => values.indexOf(value) === index);
  wikiEvents.forEach((value) => { if (!eventOrder.includes(value)) eventOrder.push(value); });
  return { score, metric, stats, ownAbilityDamage, autos, antiHeal, liandry, targetShields, ownShields, outgoingSupport, supportItems, survivalPool, survivalSeconds, survivalFraction, tradeOutput, eventOrder, targetHealing, role };
}

function rosterBisContext(path) {
  const [root, indexText] = String(path).split(".");
  const index = Number(indexText);
  const combatant = root === "allies" ? state.allies[index] : state.targets[index];
  if (!combatant?.champion) return null;
  if (root === "allies") {
    return { root, index, combatant, opponents: state.targets.filter((target) => target.champion) };
  }
  if (root === "targets") {
    const attacker = {
      champion: state.attacker.champion,
      level: state.attacker.level,
      items: buildAIds(),
      itemStacks: buildAStacks(),
      role: state.attacker.role,
      roleQuestComplete: state.attacker.roleQuestComplete,
    };
    return { root, index, combatant, opponents: [attacker, ...state.allies.filter((ally) => ally.champion)] };
  }
  return null;
}

function rosterBisIds(path, candidateId) {
  const context = rosterBisContext(path);
  if (!context) return [];
  const ids = [...context.combatant.items];
  ids[Number(String(path).split(".").at(-1))] = candidateId;
  return ids;
}

function rosterBisStacks(path, candidateId) {
  const context = rosterBisContext(path);
  if (!context) return [];
  const ids = [...context.combatant.items];
  const stacks = [...(context.combatant.itemStacks || [])];
  const slot = Number(String(path).split(".").at(-1));
  if (Number(ids[slot]) !== Number(candidateId)) stacks[slot] = 0;
  return stacks;
}

function rosterBisCandidates(path, profile) {
  const currentIds = rosterBisIds(path, 0).filter(Boolean);
  const role = bisRole(profile);
  return DATA.items.filter((item) => {
    const completed = item.price >= 2200 && item.into.length === 0;
    return completed && bisItemMatchesRole(item, role, path) && !ALL_ROLE_BOOTS.has(item.id) && !currentIds.includes(item.id);
  });
}

function bisItemMatchesRole(item, role, path = "") {
  const categories = new Set(item.categories || []);
  const effect = bisItemEffects(item);
  if (String(path).startsWith("allies.") && (role === "enchanter" || role === "support")) {
    // Ally optimization is an outgoing-support problem. Keep raw AP items
    // only when they carry a sourced support signal or the support mana loop;
    // defensive/AP damage items must not masquerade as enchanter BIS.
    return Boolean(effect.allyShield || effect.allyHealing || effect.allyAura || (item.ap && categories.has("ManaRegen")));
  }
  const defensive = effect.defensive || item.hp || item.haste || categories.has("AbilityHaste") || categories.has("Aura") || categories.has("Active");
  const offensive = item.ad || item.ap || item.attackSpeed || item.crit || item.pen || item.percentPen || item.lethality || item.percentArmorPen || categories.has("OnHit");
  if (role === "tank" || role === "warden") return Boolean(defensive || (item.ad && item.hp));
  if (role === "enchanter" || role === "support") return Boolean(defensive || item.ap || effect.healing);
  if (role === "marksman") return Boolean(offensive);
  if (role === "mage" || role === "assassin") return Boolean(item.ap || item.pen || item.percentPen || item.haste || effect.burn || effect.antiHeal);
  return Boolean(offensive || defensive);
}

function bisBackendPayload(path) {
  const parts = String(path).split(".");
  const payload = { ...engineFightPayload("A") };
  if (parts[0] === "attacker") {
    const side = path.includes("buildB") || path.includes("questBootB") ? "B" : "A";
    Object.assign(payload, engineFightPayload(side));
    payload.subject_team = "main";
    payload.subject_index = 0;
    payload.slot_kind = parts[1]?.startsWith("questBoot") ? "boots" : "item";
    payload.slot_index = parts[1]?.startsWith("questBoot") ? 0 : Number(parts.at(-1));
    return payload;
  }
  if ((parts[0] !== "allies" && parts[0] !== "targets") || parts.length < 3) return null;
  payload.subject_team = parts[0] === "allies" ? "ally" : "enemy";
  payload.subject_index = Number(parts[1]);
  payload.slot_kind = parts[2] === "boots" ? "boots" : "item";
  payload.slot_index = payload.slot_kind === "boots" ? 0 : Number(parts[3]);
  return payload;
}

function bisMetricLabel(value) {
  return String(value || "team-fight value")
    .replaceAll("effective health", "eHP")
    .replaceAll("before defeat", "before defeat")
    .replaceAll("sourced", "sourced");
}

function bisComponentLine(components) {
  return Object.entries(components || {})
    .filter(([, value]) => Number.isFinite(Number(value)) && Number(value) !== 0)
    .slice(0, 3)
    .map(([key, value]) => `${key.replaceAll("_", " ")} ${fmt(value)}`)
    .join(" · ");
}

async function openBackendBis(path) {
  if (!bisReadyForPath(path)) return;
  const payload = bisBackendPayload(path);
  if (!payload) return;
  const isMain = payload.subject_team === "main";
  const subject = isMain
    ? state.attacker
    : state[payload.subject_team === "ally" ? "allies" : "targets"][payload.subject_index];
  if (!subject?.champion) return;
  const subjectLabel = isMain ? "" : `${payload.subject_team === "ally" ? "Ally" : "Enemy"} `;
  const slotLabel = payload.slot_kind === "boots" ? "boots" : `slot ${payload.slot_index + 1}`;
  $("bisTitle").textContent = `Best ${payload.slot_kind === "boots" ? "boots" : "item"} for ${subjectLabel}${subject.champion} · ${slotLabel}`;
  $("bisSummary").textContent = "Scoring the simultaneous event timeline · loading sourced candidates…";
  $("bisList").innerHTML = `<p class="picker-empty">Scoring every legal candidate against the selected team-fight…</p>`;
  bisContext = { path };
  $("bis").showModal();
  try {
    const response = await fetch("/api/bis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || result.error) throw new Error(result.error || "BIS service unavailable");
    const rows = result.candidates || [];
    const coverage = result.coverage?.complete
      ? "complete sourced coverage"
      : "BIS withheld until event order is complete";
    $("bisSummary").textContent = `${subject.champion} · ${rows.length} of ${result.candidate_count || rows.length} legal candidates · ${coverage}`;
    $("bisList").innerHTML = rows.map((entry, index) => {
      const item = DATA.items.find((candidate) => candidate.name === entry.name);
      const detail = `${item ? itemStatsLine(item) : "Sourced item stats"} · ${bisComponentLine(entry.components)}`;
      return `<article class="bis-row"><span class="bis-rank">${String(index + 1).padStart(2, "0")}</span><img src="${item ? itemImage(item.id) : escapeHtml(entry.icon || "")}" alt="" /><div><strong>${escapeHtml(entry.name)}</strong><small>${escapeHtml(detail)}</small></div><p><strong>${fmt(entry.score)}</strong><span>${escapeHtml(bisMetricLabel(entry.metric))}</span></p><button type="button" data-bis-value="${item ? item.id : ""}" ${item ? "" : "disabled"}>Use</button></article>`;
    }).join("") || `<p class="picker-empty">${escapeHtml(result.coverage?.note || "No legal candidate has complete sourced mechanics for this timeline.")}</p>`;
  } catch (error) {
    $("bisSummary").textContent = "BIS unavailable";
    $("bisList").innerHTML = `<p class="picker-empty">${escapeHtml(error.message)}</p>`;
  }
}

function openRosterBis(path) {
  return openBackendBis(path);
}

function optimizerDamagePackageReady() {
  const champion = getChampion(state.attacker.champion);
  const completeSourcedKit = activeAbilityKit().filter((ability) => ["Q", "W", "E", "R"].includes(ability.slot)).length === 4;
  const selectedAbilities = completeSourcedKit && activeAbilityKit().some((ability) => abilityInput(ability.slot).casts > 0 && (ability.slot === "P" || abilityInput(ability.slot).rank > 0));
  const manualPackage = state.attacker.baseDamage > 0 || state.attacker.apRatio > 0 || state.attacker.physicalDamage > 0 || state.attacker.adRatio > 0;
  // The backend has a dedicated reviewed module for every cached champion.
  // A sparse client formula catalogue (for example a passive-only tank kit)
  // must not make the optimizer button appear dead; the sourced BIS profile
  // still supplies the selectable package while the engine remains the
  // authority for the final score.
  const reviewedBackend = Boolean(champion && (engine.reviewed.has(champion.name) || engine.backend.has(champion.name)));
  return reviewedBackend && (selectedAbilities || manualPackage || Boolean(bisChampionProfile(state.attacker)));
}

function bisCandidates(path, profile) {
  const wikiMode = Boolean(profile?.wiki) || String(profile?.label || "").startsWith("Wiki-derived");
  const selectedTypes = profile.useAbilities ? activeAbilityKit().flatMap((ability) => ability.variants.flatMap((variant) => variant.packets?.map((packet) => typeof packet === "string" ? packet : packet.type) || [variant.type])) : [];
  const physical = profile.physicalDamage > 0 || profile.adRatio > 0 || selectedTypes.includes("physical");
  const magical = profile.baseDamage > 0 || profile.apRatio > 0 || selectedTypes.includes("magical");
  const currentIds = idsForBis(path, 0).filter(Boolean);
  if (path.includes("questBoot")) return DATA.items.filter((item) => questBootIds().includes(item.id) && !currentIds.includes(item.id));
  if (wikiMode && state.attacker.champion) {
    return DATA.items.filter((item) => item.price >= 2200 && item.into.length === 0 && bisItemMatchesRole(item, bisRole(bisChampionProfile(state.attacker))) && !ALL_ROLE_BOOTS.has(item.id) && !currentIds.includes(item.id));
  }
  return DATA.items.filter((item) => {
    const completed = item.price >= 2200 && item.into.length === 0;
    const relevant = (magical && (item.ap || item.pen || item.percentPen || [6653, 6655].includes(item.id))) || (physical && (item.ad || item.lethality || item.percentArmorPen));
    return completed && relevant && !ALL_ROLE_BOOTS.has(item.id) && !currentIds.includes(item.id);
  });
}

const optimizerExclusiveGroups = [
  new Set([3135, 3137]), // Void Staff / Cryptbloom
  new Set([3033, 3036, 6694]), // Last Whisper upgrades
];

function legalOptimizerBuild(ids) {
  if (new Set(ids).size !== ids.length) return false;
  return optimizerExclusiveGroups.every((group) => ids.filter((id) => group.has(id)).length <= 1);
}

function optimizerCandidatePool(profile, targetStats) {
  const selectedTypes = profile.useAbilities ? activeAbilityKit().flatMap((ability) => ability.variants.flatMap((variant) => variant.packets?.map((packet) => typeof packet === "string" ? packet : packet.type) || [variant.type])) : [];
  const hasMagicalAbilities = profile.baseDamage > 0 || profile.apRatio > 0 || selectedTypes.includes("magical");
  const hasPhysicalAbilities = profile.physicalDamage > 0 || profile.adRatio > 0 || selectedTypes.includes("physical");
  const physical = hasPhysicalAbilities;
  const magical = hasMagicalAbilities;
  const relevant = DATA.items.filter((item) => {
    const completed = item.price >= 2200 && item.into.length === 0;
    const damageStat = (magical && (item.ap || item.pen || item.percentPen || [6653, 6655].includes(item.id)))
      || (physical && (item.ad || item.lethality || item.percentArmorPen || item.attackSpeed || item.crit));
    return completed && damageStat;
  });
  const scoreOptions = { profile, summaryOnly: true, targetStats, allyBonuses: allyStatBonuses() };
  const scored = relevant.map((item) => ({
    item,
    total: calculateBuild([item.id], state.fight.rotations, [0], scoreOptions).cumulative,
  })).sort((a, b) => b.total - a.total);
  if (!(magical && physical)) return scored.slice(0, 15);

  const isMagicalItem = ({ item }) => item.ap || item.pen || item.percentPen || [6653, 6655].includes(item.id);
  const isPhysicalItem = ({ item }) => item.ad || item.lethality || item.percentArmorPen || item.attackSpeed || item.crit;
  const magicalQuota = hasPhysicalAbilities ? 8 : 11;
  const physicalQuota = 15 - magicalQuota;
  const chosen = [];
  const chosenIds = new Set();
  const take = (entries, count) => {
    for (const entry of entries) {
      if (chosen.length >= 15 || count <= 0) break;
      if (chosenIds.has(entry.item.id)) continue;
      chosen.push(entry);
      chosenIds.add(entry.item.id);
      count -= 1;
    }
  };
  take(scored.filter(isMagicalItem), magicalQuota);
  take(scored.filter(isPhysicalItem), physicalQuota);
  take(scored, 15 - chosen.length);
  return chosen;
}

function roleAwareOptimizerCandidatePool(role, path = "attacker") {
  const candidates = DATA.items.filter((item) => {
    const completed = item.price >= 2200 && item.into.length === 0;
    const candidatePath = role === "enchanter" || role === "support" ? "allies.0" : path;
    return completed && !ALL_ROLE_BOOTS.has(item.id) && bisItemMatchesRole(item, role, candidatePath);
  });
  const currentIds = buildAIds().filter((id) => id && !ALL_ROLE_BOOTS.has(Number(id))).map(Number);
  const scored = candidates.map((item) => ({
    item,
    total: bisBuildScore([item.id, 0, 0, 0, 0, 0], state.attacker, state.targets, path).score,
  })).sort((a, b) => b.total - a.total);
  const selected = [];
  const seen = new Set();
  [...currentIds.map((id) => ({ item: getItem(id), total: Number.POSITIVE_INFINITY })), ...scored].forEach((entry) => {
    if (!entry.item || seen.has(entry.item.id)) return;
    seen.add(entry.item.id);
    selected.push(entry.item);
  });
  return selected.slice(0, 12);
}

function optimizeRoleAwareBuild(role) {
  const started = performance.now();
  const pool = roleAwareOptimizerCandidatePool(role);
  if (pool.length < 6) throw new Error("Not enough completed role-compatible items for this build.");
  const ids = pool.map((item) => item.id);
  const evaluated = [];
  const selected = [];
  function search(from) {
    if (selected.length === 6) {
      if (!legalOptimizerBuild(selected)) return;
      const build = [...selected];
      evaluated.push({ build, total: bisBuildScore(build, state.attacker, state.targets, "attacker").score });
      return;
    }
    const needed = 6 - selected.length;
    for (let index = from; index <= ids.length - needed; index += 1) {
      selected.push(ids[index]);
      if (legalOptimizerBuild(selected)) search(index + 1);
      selected.pop();
    }
  }
  search(0);
  evaluated.sort((a, b) => b.total - a.total);
  const best = evaluated[0];
  if (!best) throw new Error("No legal complete role-aware build matched this champion.");
  return {
    build: best.build,
    questBoot: 0,
    tested: evaluated.length,
    elapsedMs: performance.now() - started,
    total: best.total,
    candidateCount: pool.length,
    role,
    roleAware: true,
  };
}

function optimizeFullBuild() {
  const started = performance.now();
  const profile = bisProfile();
  const role = bisRole(bisChampionProfile(state.attacker));
  if (["enchanter", "warden", "tank", "support"].includes(role)) return optimizeRoleAwareBuild(role);
  const targetStats = state.targets.map((target) => championStats(target.champion, target.level, target.items, target.itemStacks));
  const pool = optimizerCandidatePool(profile, targetStats);
  const slotCount = ordinarySlotCount("A");
  if (pool.length < slotCount) throw new Error("Not enough completed damage items for this package.");
  const ids = pool.map((entry) => entry.item.id);
  const boots = usesQuestBootSlot() ? questBootIds() : [0];
  const evaluated = [];
  const selected = [];
  const scoreOptions = { profile, summaryOnly: true, targetStats, allyBonuses: allyStatBonuses() };

  function search(from) {
    if (selected.length === slotCount) {
      if (!legalOptimizerBuild(selected)) return;
      for (const bootId of boots) {
        const buildIds = bootId ? [...selected, bootId] : [...selected];
        evaluated.push({ ids: [...selected], questBoot: bootId, total: calculateBuild(buildIds, state.fight.rotations, [], scoreOptions).cumulative });
      }
      return;
    }
    const needed = slotCount - selected.length;
    for (let index = from; index <= ids.length - needed; index += 1) {
      selected.push(ids[index]);
      if (legalOptimizerBuild(selected)) search(index + 1);
      selected.pop();
    }
  }

  search(0);
  evaluated.sort((a, b) => b.total - a.total);
  const best = evaluated[0];
  if (!best) throw new Error("No legal complete build matched this package.");
  const elapsedMs = performance.now() - started;
  return { build: best.ids, questBoot: best.questBoot, tested: evaluated.length, elapsedMs, total: best.total, candidateCount: pool.length };
}

function rosterOptimizerCandidatePool(path) {
  const context = rosterBisContext(path);
  if (!context) return [];
  const profile = bisChampionProfile(context.combatant);
  const role = bisRole(profile);
  const current = context.combatant.items.filter((id) => id && !ALL_ROLE_BOOTS.has(Number(id))).map(Number);
  const candidates = DATA.items.filter((item) => {
    const completed = item.price >= 2200 && item.into.length === 0;
    return completed && !ALL_ROLE_BOOTS.has(item.id) && bisItemMatchesRole(item, role, path);
  });
  const scored = candidates.map((item) => {
    const ids = [item.id, 0, 0, 0, 0, 0];
    return { item, total: bisBuildScore(ids, context.combatant, context.opponents, path).score };
  }).sort((a, b) => b.total - a.total);
  const selected = [];
  const seen = new Set();
  [...current.map((id) => ({ item: getItem(id), total: Number.POSITIVE_INFINITY })), ...scored].forEach((entry) => {
    if (!entry.item || seen.has(entry.item.id)) return;
    seen.add(entry.item.id);
    selected.push(entry.item);
  });
  // Keep the exhaustive search small enough for an in-browser interaction.
  return selected.slice(0, 12);
}

function optimizeRosterBuild(path) {
  const started = performance.now();
  const context = rosterBisContext(path);
  const pool = rosterOptimizerCandidatePool(path);
  if (!context || pool.length < 6) throw new Error("Not enough completed role-compatible items for this roster build.");
  const evaluated = [];
  const selected = [];
  const ids = pool.map((item) => item.id);
  function search(from) {
    if (selected.length === 6) {
      if (!legalOptimizerBuild(selected)) return;
      const build = [...selected];
      evaluated.push({ build, total: bisBuildScore(build, context.combatant, context.opponents, path).score });
      return;
    }
    const needed = 6 - selected.length;
    for (let index = from; index <= ids.length - needed; index += 1) {
      selected.push(ids[index]);
      if (legalOptimizerBuild(selected)) search(index + 1);
      selected.pop();
    }
  }
  search(0);
  evaluated.sort((a, b) => b.total - a.total);
  const best = evaluated[0];
  if (!best) throw new Error("No legal complete roster build matched this champion.");
  return {
    build: best.build,
    tested: evaluated.length,
    elapsedMs: performance.now() - started,
    total: best.total,
    candidateCount: pool.length,
    metric: bisBuildScore(best.build, context.combatant, context.opponents, path).metric,
  };
}

function applyRosterBuild(path, result) {
  const [root, indexText] = String(path).split(".");
  const loadout = state[root]?.[Number(indexText)];
  if (!loadout) return;
  loadout.items = [...result.build, ...Array(Math.max(0, 6 - result.build.length)).fill(0)].slice(0, 6);
  loadout.itemStacks = [0, 0, 0, 0, 0, 0];
}

function reoptimizeAttackerAfterRosterChange() {
  if (!state.attacker.champion || !optimizerDamagePackageReady() || !state.targets.length || !state.targets.every((target) => target.champion)) return null;
  try {
    const result = optimizeFullBuild();
    state.attacker.buildA = [...result.build, ...Array(Math.max(0, 6 - result.build.length)).fill(0)].slice(0, 6);
    state.attacker.buildAStacks = [0, 0, 0, 0, 0, 0];
    state.attacker.questBootA = result.questBoot || 0;
    return result;
  } catch {
    return null;
  }
}

function rosterOptimizationPaths(rootOrPath) {
  if (String(rootOrPath).includes(".")) return bisReadyForPath(rootOrPath) ? [rootOrPath] : [];
  return (state[rootOrPath] || []).map((loadout, index) => `${rootOrPath}.${index}`).filter((path) => bisReadyForPath(path));
}

async function requestBis(path) {
  const payload = bisBackendPayload(path);
  if (!payload) throw new Error("Invalid roster optimization path");
  const response = await fetch("/api/bis", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok || result.error) throw new Error(result.error || "BIS service unavailable");
  return result;
}

async function optimizeRosterPathFromTimeline(path) {
  let tested = 0;
  const [root, indexText] = path.split(".");
  const loadout = state[root][Number(indexText)];
  if (loadout.includeBoots) {
    const bootResult = await requestBis(`${path}.boots`);
    if (!bootResult.coverage?.complete) throw new Error(bootResult.coverage?.note || "BIS withheld until event order is complete");
    tested += Number(bootResult.candidate_count || 0);
    const boot = bootResult.candidates?.[0] && DATA.items.find((entry) => entry.name === bootResult.candidates[0].name);
    if (boot) loadout.boots = boot.id;
  }
  // Greedy slot passes keep every candidate on the same complete team
  // timeline.  Re-running after each slot lets item interactions and deaths
  // change the next slot's result instead of freezing a stat-only estimate.
  for (let slot = 0; slot < (loadout.includeBoots ? 5 : 6); slot += 1) {
    const result = await requestBis(`${path}.items.${slot}`);
    if (!result.coverage?.complete) throw new Error(result.coverage?.note || "BIS withheld until event order is complete");
    tested += Number(result.candidate_count || 0);
    const candidate = result.candidates?.[0];
    const item = candidate && DATA.items.find((entry) => entry.name === candidate.name);
    if (!item) continue;
    setPath(`${path}.items.${slot}`, item.id);
    state[root][Number(indexText)].itemStacks[slot] = 0;
  }
  return tested;
}

async function startRosterOptimization(rootOrPath) {
  if (state.optimizer.running) return;
  const paths = rosterOptimizationPaths(rootOrPath);
  if (!paths.length) return;
  state.optimizer.running = true;
  state.optimizer.scope = String(rootOrPath).includes(".") ? "roster" : rootOrPath;
  state.optimizer.summary = null;
  renderBuilder();
  const started = performance.now();
  let tested = 0;
  try {
    const changed = [];
    for (const path of paths) {
      tested += await optimizeRosterPathFromTimeline(path);
      // The main build is deliberately re-solved after each roster change;
      // an ally/enemy build can change the main champion's best response.
      if (state.attacker.champion && optimizerDamagePackageReady() && state.targets.length && state.targets.every((target) => target.champion)) {
        const mainResult = await optimizeMainBuildFromBackend();
        tested += Number(mainResult?.evaluations || 0);
      }
      const [root, indexText] = path.split(".");
      changed.push(state[root][Number(indexText)].champion);
    }
    const scope = paths.length === 1 ? `${changed[0]} build` : `${rootOrPath === "targets" ? "all enemy" : "all ally"} builds`;
    state.optimizer.summary = {
      tested,
      elapsedMs: performance.now() - started,
      label: `${scope} optimized from the coupled event timeline; Build A was rebalanced after each roster change.`,
    };
  } catch (error) {
    state.optimizer.summary = { tested, elapsedMs: performance.now() - started, label: `Optimization stopped: ${error.message}` };
  } finally {
    state.optimizer.running = false;
    state.optimizer.scope = null;
    render();
  }
}

async function optimizeMainBuildFromBackend() {
    const payload = engineFightPayload("A");
    payload.objective = "total_damage";
    payload.locked_items = [];
    payload.locked_boots = "";
    payload.max_legendary_slots = ordinarySlotCount("A");
    const response = await fetch("/api/optimize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || result.error) throw new Error(result.error || "Optimizer unavailable");
    if (!result.is_certified_best) {
      // A partial candidate timeline is a receipt, not a build recommendation.
      // Keep the user's current build intact until every active source in the
      // search is event-order certified.
      state.optimizer.summary = {
        tested: Number(result.evaluations || 0),
        elapsedMs: Number(result.optimization_time_ms || 0),
        withheld: true,
        label: `BIS withheld — no build applied. ${result.search_timeline_coverage?.note || "Event-order coverage is incomplete."}`,
      };
      return result;
    }
    const ids = (result.items || []).map((name) => DATA.items.find((item) => item.name === name)?.id || 0);
    state.attacker.buildA = [...ids, ...Array(Math.max(0, 6 - ids.length)).fill(0)].slice(0, 6);
    state.attacker.buildAStacks = [0, 0, 0, 0, 0, 0];
    state.attacker.questBootA = DATA.items.find((item) => item.name === result.boots)?.id || 0;
    state.optimizer.summary = {
      tested: Number(result.evaluations || 0),
      elapsedMs: Number(result.optimization_time_ms || 0),
      label: "Coupled event-ordered BIS: TTD is counted only while the champion is alive.",
    };
    return result;
}

async function startOptimizeBuild() {
  if (state.optimizer.running || !state.attacker.champion || !optimizerDamagePackageReady() || !state.targets.length || !state.targets.every((target) => target.champion)) return;
  state.optimizer.running = true;
  state.optimizer.summary = null;
  renderBuilder();
  try {
    await optimizeMainBuildFromBackend();
  } catch (error) {
    state.optimizer.summary = { tested: 0, elapsedMs: 0, withheld: true, label: `Optimization stopped — no build applied. ${error.message}` };
  } finally {
    state.optimizer.running = false;
    render();
  }
}

function openBis(path) {
  return openBackendBis(path);
}

function closeBis() {
  $("bis").close();
  bisContext = null;
}

function updateDamagePackage() {
  invalidateOptimization();
  state.attacker.baseDamage = Math.max(0, Number($("baseDamage").value) || 0);
  state.attacker.apRatio = Math.max(0, Number($("apRatio").value) || 0);
  state.attacker.physicalDamage = Math.max(0, Number($("physicalDamage").value) || 0);
  state.attacker.adRatio = Math.max(0, Number($("adRatio").value) || 0);
  render();
}

document.addEventListener("click", (event) => {
  const rosterOptimizeAll = event.target.closest("[data-optimize-roster-all]");
  if (rosterOptimizeAll) return startRosterOptimization(rosterOptimizeAll.dataset.optimizeRosterAll);
  const rosterOptimize = event.target.closest("[data-optimize-roster]");
  if (rosterOptimize) return startRosterOptimization(rosterOptimize.dataset.optimizeRoster);
  if (event.target.closest("[data-optimize-build]")) return startOptimizeBuild();
  const roleButton = event.target.closest("[data-role]");
  if (roleButton) {
    state.attacker.role = roleButton.dataset.role;
    state.attacker.questBootA = 0;
    state.attacker.questBootB = 0;
    state.attacker.level = Math.min(state.attacker.level, attackerLevelCap());
    syncAbilityInputsToLevel();
    invalidateOptimization();
    return render();
  }
  if (event.target.closest("[data-role-quest]")) {
    state.attacker.roleQuestComplete = !state.attacker.roleQuestComplete;
    state.attacker.questBootA = 0;
    state.attacker.questBootB = 0;
    state.attacker.level = Math.min(state.attacker.level, attackerLevelCap());
    syncAbilityInputsToLevel();
    invalidateOptimization();
    return render();
  }
  if (event.target.closest("[data-toggle-compare]")) {
    state.attacker.comparisonEnabled = !state.attacker.comparisonEnabled;
    if (state.attacker.comparisonEnabled && !state.attacker.buildB.some(Boolean)) {
      state.attacker.buildB = [...state.attacker.buildA];
      state.attacker.buildBStacks = [...state.attacker.buildAStacks];
      state.attacker.questBootB = state.attacker.questBootA;
      state.attacker.keystoneB = state.attacker.keystoneA;
    }
    return render();
  }
  const pickerButton = event.target.closest("[data-picker]");
  if (pickerButton) return openPicker(pickerButton.dataset.picker, pickerButton.dataset.path);
  const bisButton = event.target.closest("[data-bis-path]");
  if (bisButton) return openBis(bisButton.dataset.bisPath);
  const bootsButton = event.target.closest("[data-include-boots]");
  if (bootsButton) {
    const side = bootsButton.dataset.includeBoots;
    const key = side === "B" ? "includeBootsB" : "includeBootsA";
    state.attacker[key] = !state.attacker[key];
    if (!state.attacker[key]) state.attacker[`questBoot${side}`] = 0;
    invalidateOptimization();
    return render();
  }
  const rosterBootsButton = event.target.closest("[data-include-roster-boots]");
  if (rosterBootsButton) {
    const [root, indexText] = rosterBootsButton.dataset.includeRosterBoots.split(".");
    const loadout = state[root]?.[Number(indexText)];
    if (!loadout) return;
    loadout.includeBoots = !loadout.includeBoots;
    if (!loadout.includeBoots) loadout.boots = 0;
    invalidateOptimization();
    return render();
  }
  const rosterQuestButton = event.target.closest("[data-roster-quest]");
  if (rosterQuestButton) {
    const path = rosterQuestButton.dataset.rosterQuest;
    const loadout = pathValue(path);
    if (!loadout?.role) return;
    loadout.roleQuestComplete = !loadout.roleQuestComplete;
    if (loadout.role !== "top" && loadout.level > 18) loadout.level = 18;
    invalidateOptimization();
    return render();
  }
  const levelButton = event.target.closest("[data-level]");
  if (levelButton) {
    const rosterLevel = levelButton.dataset.level.match(/^(targets|allies)\.(\d+)\.level$/);
    const rosterLoadout = rosterLevel ? state[rosterLevel[1]]?.[Number(rosterLevel[2])] : null;
    const cap = levelButton.dataset.level === "attacker.level"
      ? attackerLevelCap()
      : (rosterLoadout?.role === "top" && rosterLoadout.roleQuestComplete ? 20 : 18);
    setPath(levelButton.dataset.level, Math.max(1, Math.min(cap, Number(pathValue(levelButton.dataset.level)) + Number(levelButton.dataset.delta))));
    if (levelButton.dataset.level === "attacker.level") syncAbilityInputsToLevel();
    return render();
  }
  const rosterRankButton = event.target.closest("[data-roster-rank]");
  if (rosterRankButton) {
    invalidateOptimization();
    const [root, indexText, slot] = rosterRankButton.dataset.rosterRank.split(".");
    const loadout = state[root]?.[Number(indexText)];
    const forms = BIS_PROFILES[loadout?.champion]?.abilities?.[slot] || [];
    const maxRank = Math.max(...forms.map((ability) => ability.maxRank || (slot === "R" ? 3 : 5)), slot === "R" ? 3 : 5);
    const current = bisRankFor(loadout, slot, maxRank);
    const cap = slot === "R" ? ((loadout.level >= 16 ? 3 : loadout.level >= 11 ? 2 : loadout.level >= 6 ? 1 : 0)) : Math.min(5, Math.floor((loadout.level + 1) / 2));
    const next = { ...defaultAbilityRanks(loadout), ...(loadout.abilityRanks || {}) };
    next[slot] = Math.max(0, Math.min(maxRank, cap, current + Number(rosterRankButton.dataset.delta)));
    const total = () => ["Q", "W", "E", "R"].reduce((sum, key) => sum + Number(next[key] || 0), 0);
    const trimOrder = ["Q", "W", "E", "R"].filter((key) => key !== slot).sort((a, b) => Number(next[b] || 0) - Number(next[a] || 0));
    while (total() > Math.max(1, Number(loadout.level) || 1)) {
      const trim = trimOrder.find((key) => next[key] > 0);
      if (!trim) break;
      next[trim] -= 1;
    }
    loadout.abilityRanks = next;
    return render();
  }
  const stackButton = event.target.closest("[data-stack-path]");
  if (stackButton) {
    const path = stackButton.dataset.stackPath;
    const spec = stackSpec(pathValue(path));
    setStackValue(path, Math.max(0, Math.min(spec.max, stackValue(path) + Number(stackButton.dataset.delta))));
    return render();
  }
  const abilityRankButton = event.target.closest("[data-ability-rank]");
  if (abilityRankButton) {
    invalidateOptimization();
    const slot = abilityRankButton.dataset.abilityRank;
    const ability = activeAbilityKit().find((entry) => entry.slot === slot);
    const input = abilityInput(slot);
    input.rank = Math.max(0, Math.min(ability.maxRank, input.rank + Number(abilityRankButton.dataset.delta)));
    state.attacker.abilityInputs[slot] = input;
    return render();
  }
  const abilityCastButton = event.target.closest("[data-ability-casts]");
  if (abilityCastButton) {
    invalidateOptimization();
    const slot = abilityCastButton.dataset.abilityCasts;
    const input = abilityInput(slot);
    input.casts = Math.max(0, Math.min(10, input.casts + Number(abilityCastButton.dataset.delta)));
    state.attacker.abilityInputs[slot] = input;
    return render();
  }
  const abilityHitButton = event.target.closest("[data-ability-hits]");
  if (abilityHitButton) {
    invalidateOptimization();
    const slot = abilityHitButton.dataset.abilityHits;
    const ability = activeAbilityKit().find((entry) => entry.slot === slot);
    const input = abilityInput(slot);
    input.hits = Math.max(1, Math.min(ability.maxHits, input.hits + Number(abilityHitButton.dataset.delta)));
    state.attacker.abilityInputs[slot] = input;
    return render();
  }
  const abilityVariantButton = event.target.closest("[data-ability-variant]");
  if (abilityVariantButton) {
    invalidateOptimization();
    const slot = abilityVariantButton.dataset.abilityVariant;
    const input = abilityInput(slot);
    input.variant = Number(abilityVariantButton.dataset.value);
    state.attacker.abilityInputs[slot] = input;
    return render();
  }
  const fightButton = event.target.closest("[data-fight]");
  if (fightButton) {
    invalidateOptimization();
    const key = fightButton.dataset.fight;
    state.fight[key] = Number(fightButton.dataset.value);
    return render();
  }
  const removeButton = event.target.closest("[data-remove-target]");
  if (removeButton) {
    invalidateOptimization();
    state.targets.splice(Number(removeButton.dataset.removeTarget), 1);
    return render();
  }
  if (event.target.closest("[data-add-target]")) {
    invalidateOptimization();
    if (state.targets.length < 5) {
      const index = state.targets.length;
      state.targets.push({ champion: null, level: 1, role: "", roleQuestComplete: false, items: [0, 0, 0, 0, 0, 0], itemStacks: [0, 0, 0, 0, 0, 0], boots: 0, includeBoots: true, abilityRanks: {} });
      render();
      return openPicker("champion", `targets.${index}.champion`);
    }
    return;
  }
  const removeAllyButton = event.target.closest("[data-remove-ally]");
  if (removeAllyButton) {
    invalidateOptimization();
    state.allies.splice(Number(removeAllyButton.dataset.removeAlly), 1);
    return render();
  }
  if (event.target.closest("[data-add-ally]")) {
    invalidateOptimization();
    if (state.allies.length < 4) {
      const index = state.allies.length;
      state.allies.push({ champion: null, level: 1, role: "", roleQuestComplete: false, items: [0, 0, 0, 0, 0, 0], itemStacks: [0, 0, 0, 0, 0, 0], boots: 0, includeBoots: true, abilityRanks: {}, allyEffectsEnabled: false });
      render();
      return openPicker("champion", `allies.${index}.champion`);
    }
    return;
  }
  const allyEffectsButton = event.target.closest("[data-ally-effects]");
  if (allyEffectsButton) {
    invalidateOptimization();
    const index = Number(allyEffectsButton.dataset.allyEffects);
    state.allies[index].allyEffectsEnabled = !state.allies[index].allyEffectsEnabled;
    return render();
  }
  const option = event.target.closest("[data-picker-value]");
  if (option && pickerContext) {
    const selectedPath = pickerContext.path;
    if (pickerContext.type === "item") setStackValue(pickerContext.path, 0);
    setPath(pickerContext.path, pickerContext.type === "item" ? Number(option.dataset.pickerValue) : option.dataset.pickerValue);
    if (pickerContext.type === "champion" && selectedPath === "attacker.champion") resetAbilityInputs();
    if (pickerContext.type === "champion" && /^(targets|allies)\.\d+\.champion$/.test(selectedPath)) {
      const [root, indexText] = selectedPath.split(".");
      const loadout = state[root][Number(indexText)];
      loadout.abilityRanks = defaultAbilityRanks(loadout);
    }
    closePicker();
    return render();
  }
  const bisOption = event.target.closest("[data-bis-value]");
  if (bisOption && bisContext) {
    setStackValue(bisContext.path, 0);
    setPath(bisContext.path, Number(bisOption.dataset.bisValue));
    closeBis();
    return render();
  }
});

document.addEventListener("input", (event) => {
  const range = event.target.closest("[data-fight-range]");
  if (!range) return;
  invalidateOptimization();
  const key = range.dataset.fightRange;
  state.fight[key] = key === "aaUptime" ? Number(range.value) / 100 : Number(range.value);
  const output = range.parentElement.querySelector("output");
  if (output) output.textContent = key === "aaUptime" ? `${Math.round(state.fight.aaUptime * 100)}%` : `${one(state.fight.duration)}s`;
  const statsA = attackerChampionStats(buildAIds(), buildAStacks());
  const statsB = attackerChampionStats(buildBIds(), buildBStacks());
  const autoCount = document.querySelector(".auto-count strong");
  if (autoCount) autoCount.innerHTML = `<i class="legend-a"></i>A ${autoAttacksForStats(statsA)}${state.attacker.comparisonEnabled ? ` <i class="legend-b"></i>B ${autoAttacksForStats(statsB)}` : ""}`;
  renderResults();
  $("scenarioSentence").innerHTML = scenarioSentence();
  scheduleEngineCalculation();
});

document.addEventListener("change", (event) => {
  const roleSelect = event.target.closest("[data-roster-role]");
  if (!roleSelect) return;
  const loadout = pathValue(roleSelect.dataset.rosterRole.replace(/\.role$/, ""));
  if (!loadout) return;
  loadout.role = roleSelect.value;
  if (!loadout.role) loadout.roleQuestComplete = false;
  if (loadout.role !== "top" && loadout.level > 18) loadout.level = 18;
  invalidateOptimization();
  render();
});

document.addEventListener("change", (event) => {
  if (event.target.closest("[data-fight-range]")) renderBuilder();
});

$("pickerSearch").addEventListener("input", (event) => renderPicker(event.target.value));
$("pickerClose").addEventListener("click", closePicker);
$("picker").addEventListener("click", (event) => { if (event.target === $("picker")) closePicker(); });
$("bisClose").addEventListener("click", closeBis);
$("bis").addEventListener("click", (event) => { if (event.target === $("bis")) closeBis(); });
for (const id of ["baseDamage", "apRatio", "physicalDamage", "adRatio"]) $(id).addEventListener("input", updateDamagePackage);

Promise.all([
  fetch("/static/data.json").then((response) => { if (!response.ok) throw new Error("Patch snapshot failed to load"); return response.json(); }),
  fetch("/api/champions").then((response) => { if (!response.ok) throw new Error("Champion availability failed to load"); return response.json(); }),
  fetch("/api/config").then((response) => { if (!response.ok) throw new Error("Calculator config failed to load"); return response.json(); }),
  fetch("/static/ability-catalog.json").then((response) => { if (!response.ok) throw new Error("Ability catalogue failed to load"); return response.json(); }),
  fetch("/static/bis-profiles.json").then((response) => { if (!response.ok) throw new Error("Wiki BIS profile failed to load"); return response.json(); }),
  fetch("/static/effect-catalog.json").then((response) => { if (!response.ok) throw new Error("Wiki effect catalogue failed to load"); return response.json(); }),
])
  .then(([data, championAvailability, config, abilityCatalog, bisProfiles, effectCatalog]) => {
    DATA = data;
    mergeAbilityCatalog(abilityCatalog);
    mergeBisProfiles(bisProfiles);
    mergeEffectCatalog(effectCatalog);
    championAvailability.forEach((entry) => {
      engine.availability.set(entry.name, entry.availability || {});
      if (entry.availability?.ready) engine.reviewed.add(entry.name);
      if (entry.engine_backend_enabled) engine.backend.add(entry.name);
    });
    engine.itemOptions = config.item_options || {};
    engine.championOptions = config.champion_options || {};
    engine.keystones = config.keystones || [];
    engine.fightLimits = { ...engine.fightLimits, ...(config.input_limits || {}) };
    engine.ready = true;
    render();
  })
  .catch(() => { $("builder").innerHTML = `<p class="empty-roster">The patch snapshot could not load. Refresh to try again.</p>`; });
