const DDRAGON = "https://ddragon.leagueoflegends.com/cdn/16.15.1/img";

let DATA = { champions: [], items: [] };
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
  keystoneOptions: {},
  keystones: [],
  defaultTarget: { health: 1000, bonus_health: 0, armor: 100, mr: 100 },
  fightDefaults: {},
  exclusivityGroups: {},
  roleQuest: {},
  capabilities: { participants: {}, scenario: { fields: {} } },
  itemCatalogReady: false,
  fightLimits: { fight_duration: [1, 10] },
  pendingTimer: null,
  requestId: 0,
  responses: null,
  pending: false,
  loadoutStats: null,
  loadoutStatsKey: "",
  loadoutStatsTimer: null,
  // The last cached stats stay on screen while a fresh request is in flight
  // (#151). They are only reusable for the champion they were fetched for,
  // and only the newest request may write them.
  loadoutStatsChampion: "",
  loadoutStatsRequestId: 0,
  loadoutStatsPending: false,
};

const state = {
  ui: {
    objective: "overall",
    gameState: "theory",
  },
  attacker: {
    champion: null,
    level: 1,
    role: "mid",
    roleQuestComplete: false,
    buildA: [0, 0, 0, 0, 0, 0],
    buildAStacks: [0, 0, 0, 0, 0, 0],
    buildAItemOptions: [{}, {}, {}, {}, {}, {}],
    buildB: [0, 0, 0, 0, 0, 0],
    buildBStacks: [0, 0, 0, 0, 0, 0],
    buildBItemOptions: [{}, {}, {}, {}, {}, {}],
    questBootA: 0,
    questBootB: 0,
    includeBootsA: true,
    includeBootsB: true,
    keystoneA: "",
    keystoneB: "",
    keystoneOptionsA: {},
    keystoneOptionsB: {},
    comparisonEnabled: false,
    baseDamage: 0,
    apRatio: 0,
    physicalDamage: 0,
    adRatio: 0,
    abilityInputs: {},
    championOptions: {},
    supportTargetSelections: {},
  },
  targets: [],
  allies: [],
  fight: { rotations: 1, duration: 10, aaUptime: 0, aaUptimeMode: "calculated" },
  optimizer: { running: false, summary: null, scope: null, rosterErrors: {}, availableGold: 0 },
};

const OBJECTIVES = {
  overall: { label: "Overall", direction: "higher" },
  kill: { label: "Kill pressure", direction: "lower", metric: "targetClose" },
  survival: { label: "Survival", direction: "higher", metric: "mainEhp" },
  damage: { label: "Damage", direction: "higher", metric: "teamDamage" },
  utility: { label: "Utility", direction: "higher", metric: "utility" },
};

const TIER_TWO_BOOTS = [3006, 3009, 3008, 3158, 3111, 3047, 3020];
const TIER_THREE_BOOTS = [3172, 3170, 3168, 3171, 3173, 3174, 3175];
const ALL_ROLE_BOOTS = new Set([...TIER_TWO_BOOTS, ...TIER_THREE_BOOTS]);
// These kits do not have a standard five-rank Q/W/E plus three-rank R
// allocation.  The backend owns their sourced level-derived rank order;
// sending the generic UI allocation would be an invalid manual request.
const LEVEL_DERIVED_RANK_CHAMPIONS = new Set(["Elise", "Jayce", "Karma", "Nidalee", "Udyr"]);

function usesLevelDerivedRanks(championName) {
  return LEVEL_DERIVED_RANK_CHAMPIONS.has(String(championName || ""));
}

const $ = (id) => document.getElementById(id);
const fmt = (value) => Math.round(value).toLocaleString("en-US");
const one = (value) => Number(value).toFixed(1).replace(/\.0$/, "");
// An event's timestamp, or null when the receipt withheld one. Number(null)
// and Number("") are both 0, so a bare Number.isFinite check silently dates a
// timestamp-less event to 0.0s — a wrong number wearing an exact face.
const eventTime = (event) => {
  if (event?.time == null || event.time === "") return null;
  const time = Number(event.time);
  return Number.isFinite(time) ? time : null;
};
const percent = (value) => `${value.toFixed(value < 10 ? 1 : 0)}%`;
const plural = (count, singular, pluralForm = `${singular}s`) => count === 1 ? singular : pluralForm;
const escapeHtml = (value) => String(value).replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);

function invalidateOptimization() {
  if (!state.optimizer.running) state.optimizer.summary = null;
  engine.responses = null;
  // The cached stats are stale, not worthless: clearing the key re-requests
  // them while the last known values stay on screen as a pending panel.
  // Dropping engine.loadoutStats here is what blanked the whole champion card
  // on every level step (#151).
  engine.loadoutStatsKey = "";
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

function mergeItemCoverage(catalog) {
  if (!Array.isArray(catalog) || !catalog.length || !Array.isArray(DATA?.items)) return;
  const byId = new Map(catalog.map((entry) => [Number(entry.id), entry]).filter(([id]) => id));
  const existingIds = new Set(DATA.items.map((item) => Number(item.id)));
  DATA.items = DATA.items.map((item) => {
    const metadata = byId.get(Number(item.id));
    if (!metadata) return { ...item, backendAvailable: false };
    return {
      ...item,
      ...metadata,
      // /api/items reports price 0 in this cache generation; keep the patch
      // snapshot's real gold so quick-mode cards can show "cheapest slot".
      price: Number(metadata.price) > 0 ? metadata.price : item.price,
      backendName: metadata.name,
      backendAvailable: true,
      modelCoverage: metadata.model_coverage || null,
      targetModelCoverage: metadata.target_model_coverage || null,
      supportQuestStage: metadata.support_quest_stage || metadata.supportQuestStage || null,
      upgradeFrom: metadata.upgrade_from || metadata.upgradeFrom || null,
      upgradeTo: metadata.upgrade_to || metadata.upgradeTo || null,
    };
  });
  catalog.forEach((entry) => {
    const id = Number(entry.id);
    if (!id || existingIds.has(id)) return;
    DATA.items.push({
      ...entry,
      backendName: entry.name,
      backendAvailable: true,
      modelCoverage: entry.model_coverage || null,
      targetModelCoverage: entry.target_model_coverage || null,
      into: entry.into || [],
      categories: entry.categories || [],
      supportQuestStage: entry.support_quest_stage || entry.supportQuestStage || null,
      upgradeFrom: entry.upgrade_from || entry.upgradeFrom || null,
      upgradeTo: entry.upgrade_to || entry.upgradeTo || null,
    });
  });
  engine.itemCatalogReady = true;
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

function participantKindForPath(path) {
  const root = String(path || "").split(".")[0];
  if (root === "targets") return "enemy";
  if (root === "allies") return "ally";
  return "main";
}

/**
 * Disable the scenario actions whose prerequisites are not met yet, and say
 * why next to the control.
 *
 * Backend capability gating (applyControlCapabilities) is a boot-time fact;
 * these blocks are state-derived and change with every edit, so this runs on
 * every render. Issue #152: "Find best item for a slot" looked actionable
 * with an empty enemy roster and only wrote its warning into the result
 * column, far from the button that appeared to do nothing.
 */
function applyPrerequisiteGates() {
  const bisButton = document.getElementById("bisButton");
  if (bisButton && !bisButton.dataset.capabilityGated) {
    const blocked = !state.attacker.champion
      ? "Choose a champion to rank items for."
      : !state.targets.length
        ? "Best-in-slot needs an enemy to rank against."
        : !state.targets.every((target) => target.champion)
          ? "Finish every enemy in the roster before ranking items."
          : "";
    bisButton.disabled = Boolean(blocked);
    bisButton.title = blocked;
    const note = document.getElementById("bisPrerequisite");
    if (note) {
      note.hidden = !blocked;
      const text = document.getElementById("bisPrerequisiteText");
      if (text) text.textContent = blocked;
      // The shortcut only helps when an enemy is what is missing.
      const addEnemy = document.getElementById("bisAddEnemy");
      if (addEnemy) addEnemy.hidden = !blocked || !state.attacker.champion;
    }
  }

  const economicsBtn = document.getElementById("economicsOptimize");
  if (economicsBtn) {
    let block = "";
    const equipped = state.attacker.buildA.filter(Boolean).length + (state.attacker.questBootA ? 1 : 0);
    if (!state.attacker.champion) block = "Choose a champion first.";
    else if (!optimizerDamagePackageReady()) block = "Select a reviewed damage package first.";
    else if (!state.targets.length || !state.targets.every((target) => target.champion)) block = "Add at least one enemy first.";
    else if (!Number.isInteger(state.optimizer.availableGold) || state.optimizer.availableGold < 1) block = "Enter available gold.";
    else if (equipped >= (state.attacker.role === "bottom" && state.attacker.roleQuestComplete ? 7 : 6)) block = "Build A inventory is full.";
    else if (state.optimizer.running) block = "Optimization is already running.";
    economicsBtn.disabled = Boolean(block);
    economicsBtn.title = block;
  }
}

function applyControlCapabilities() {
  // P2 (#78 follow-up): consume contract.controls so the backend can
  // runtime-disable a control family; unsupported families get disabled
  // with the backend reason instead of silently ignoring input.
  const fields = engine.capabilities?.controls?.fields || {};
  const gated = (token) => {
    const hit = Object.values(fields).find((f) => f.frontend_token === token);
    return hit && hit.supported === false ? hit : null;
  };
  if (gated("data-bis-path")) {
    document.querySelectorAll(".bis-trigger, #bisButton").forEach((b) => {
      b.disabled = true;
      b.title = gated("data-bis-path").reason || "BIS unavailable";
      // Marks the control as backend-gated so the per-render prerequisite
      // pass leaves it disabled instead of re-enabling it. Deliberately not
      // dataset.capabilityField — that names a payload field, and this is a
      // control family.
      b.dataset.capabilityGated = "true";
    });
  }
  applyPrerequisiteGates();
  if (gated("data-game-state")) {
    document.querySelectorAll("[data-game-state]").forEach((b) => {
      b.disabled = true;
      b.title = gated("data-game-state").reason || "Unavailable";
    });
  }
  if (gated("data-objective")) {
    document.querySelectorAll("[data-objective]").forEach((b) => {
      b.disabled = true;
      b.title = gated("data-objective").reason || "Unavailable";
    });
  }
  if (gated('id="sharePanel"')) {
    document.querySelectorAll("#sharePanel, #shareAnalystButton").forEach((b) => {
      if (b) b.hidden = true;
    });
  }
  if (gated("data-remove-target")) {
    document.querySelectorAll("#addEnemy, #addAlly").forEach((b) => {
      if (b) b.disabled = true;
    });
  }
}

function maybeInitConsentAnalytics() {
  // P2(d): privacy-respecting analytics with consent. One anonymous
  // page_view ping per session via the existing /api/metrics/event
  // endpoint; nothing is sent without explicit consent (localStorage).
  if (localStorage.getItem("scryglass_analytics_consent") === "true") {
    fetch("/api/metrics/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event: "page_view", took_ms: 0 }),
    }).catch(() => {});
    return;
  }
  if (localStorage.getItem("scryglass_analytics_consent") !== null) return; // declined
  const banner = document.createElement("div");
  banner.className = "consent-banner";
  banner.setAttribute("role", "dialog");
  banner.innerHTML =
    '<span>Allow anonymous usage stats to improve Scryglass? No personal data is collected.</span>' +
    '<button type="button" id="consentYes">Yes</button>' +
    '<button type="button" id="consentNo">No</button>';
  banner.style.cssText =
    "position:fixed;bottom:12px;left:12px;right:12px;z-index:99;display:flex;gap:10px;align-items:center;" +
    "flex-wrap:wrap;padding:12px 16px;background:var(--paper,#f6f2df);color:var(--ink,#181818);" +
    "border:1px solid var(--line,#c9c2a8);border-radius:8px;font:14px/1.4 system-ui,sans-serif;";
  banner.querySelector("#consentYes").addEventListener("click", () => {
    localStorage.setItem("scryglass_analytics_consent", "true");
    banner.remove();
    fetch("/api/metrics/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event: "page_view", took_ms: 0 }),
    }).catch(() => {});
  });
  banner.querySelector("#consentNo").addEventListener("click", () => {
    localStorage.setItem("scryglass_analytics_consent", "false");
    banner.remove();
  });
  document.body.appendChild(banner);
}

function capabilityFor(kind, field) {
  return engine.capabilities?.participants?.[kind]?.fields?.[field]
    || { supported: false, reason: "This control is not declared by the backend capability contract." };
}

function scenarioCapabilityFor(field) {
  return engine.capabilities?.scenario?.fields?.[field]
    || { supported: false, reason: "This scenario control is not declared by the backend capability contract." };
}

function capabilityReason(descriptor, fallback = "This input is unavailable in the current backend model.") {
  return descriptor?.reason || fallback;
}

function capabilityTitle(descriptor) {
  return descriptor?.supported === false ? capabilityReason(descriptor) : "";
}

function capabilityDescriptorAttributes(field, descriptor, extra = {}) {
  const supported = descriptor.supported !== false;
  const reason = capabilityReason(descriptor);
  const attrs = [`data-capability-field="${escapeHtml(field)}"`];
  if (!supported) {
    attrs.push("disabled", `title="${escapeHtml(reason)}"`, `aria-disabled="true"`);
  }
  if (extra.className) attrs.push(`class="${escapeHtml(extra.className)}"`);
  return attrs.join(" ");
}

function capabilityAttributes(kind, field, extra = {}) {
  return capabilityDescriptorAttributes(field, capabilityFor(kind, field), extra);
}


function championOptionCapability(kind, championName) {
  const base = capabilityFor(kind, "champion_options");
  if (base.supported === false) return base;
  if (!championName) return { ...base, supported: false, reason: "Choose a champion before setting champion-specific options." };
  const availability = engine.availability.get(championName);
  if (availability && availability.ready === false) {
    const reason = availability.blockers?.[0]?.label || "This champion has no certified public option contract.";
    return { ...base, supported: false, reason };
  }
  return base;
}

function abilityOptionBinding(slot, field, championName = state.attacker.champion) {
  // Legacy explicit overrides first (sourced module option keys).
  const bindings = {
    "P:ability_casts": "passive_procs",
    "E:ability_hits": "mines_hit",
    "R:ability_variants": "r_sweet_spot",
  };
  const overrideKey = bindings[`${slot}:${field}`];
  const options = engine.championOptions[championName]?.options || [];
  if (overrideKey) {
    return options.some((option) => option.key === overrideKey) ? overrideKey : null;
  }
  if (field !== "ability_variants") {
    // Cast/hit counts only bind to explicitly declared per-slot count options.
    return null;
  }
  // Data-driven variant binding: a slot's variant control is enabled when the
  // champion module declares an option that drives that slot's form — a
  // per-slot variant/stance/mode key, or a global form toggle (Jayce
  // hammer_stance, Gnar mega, stance) that re-shapes every Q/W/E/R entry.
  const slotKey = slot.toLowerCase();
  const perSlot = [
    `${slotKey}_variant`, `${slotKey}_stance`, `${slotKey}_mode`,
    `${slotKey}_form`, `${slotKey}_charge`, `${slotKey}_style`,
    `accelerated_${slotKey}`, `${slotKey}_accelerated`,
  ];
  const declared = new Set(options.map((option) => option.key));
  const direct = perSlot.find((key) => declared.has(key));
  if (direct) return direct;
  if (slot !== "R" && (declared.has("hammer_stance") || declared.has("mega"))) {
    return "hammer_stance" in declared ? "hammer_stance" : "mega";
  }
  if (slot !== "R" && declared.has("stance")) return "stance";
  // A generic variant-family option for the slot (e.g. q_variant on Heimer).
  const family = [...declared].find((key) =>
    key.startsWith(slotKey) && /variant|stance|mode|form|style/.test(key)
  );
  return family || null;
}

function abilityCapability(slot, field, championName = state.attacker.champion) {
  const base = capabilityFor("main", field);
  if (base.supported === false) return base;
  if (field === "ability_ranks") return base;
  const binding = abilityOptionBinding(slot, field, championName);
  if (!binding) {
    return {
      ...base,
      supported: false,
      reason: "This ability control is unavailable because the selected champion declares no matching backend option.",
    };
  }
  return { ...base, supported: true, payload_field: "champion_options", binding };
}

function abilityCapabilityAttributes(slot, field, championName = state.attacker.champion) {
  const descriptor = abilityCapability(slot, field, championName);
  const attrs = [`data-capability-field="${escapeHtml(field)}"`];
  if (descriptor.supported === false) {
    attrs.push("disabled", `title="${escapeHtml(capabilityReason(descriptor))}"`, "aria-disabled=\"true\"");
  }
  return attrs.join(" ");
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

function resetChampionOptions() {
  const definitions = engine.championOptions[state.attacker.champion]?.options || [];
  state.attacker.championOptions = Object.fromEntries(
    definitions.map((option) => [option.key, option.default]),
  );
  state.attacker.supportTargetSelections = {};
}

function resetRosterChampionOptions(loadout) {
  const definitions = engine.championOptions[loadout?.champion]?.options || [];
  loadout.championOptions = Object.fromEntries(
    definitions.map((option) => [option.key, option.default]),
  );
  loadout.supportTargetSelections = {};
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
  const item = getItem(id);
  return item?.backendName || item?.name || fallback;
}

function backendItemReady(item) {
  return !engine.itemCatalogReady || item?.backendAvailable !== false;
}

function roleQuestStateForPath(path) {
  const parts = String(path || "").split(".");
  if (parts[0] === "attacker") {
    return {
      role: state.attacker.role || "",
      complete: Boolean(state.attacker.roleQuestComplete),
    };
  }
  if ((parts[0] === "targets" || parts[0] === "allies") && parts.length > 1) {
    const loadout = state[parts[0]]?.[Number(parts[1])];
    return {
      role: loadout?.role || "",
      complete: Boolean(loadout?.roleQuestComplete),
    };
  }
  return { role: "", complete: false };
}

function supportQuestItemBlockReason(item, path) {
  const stage = item?.supportQuestStage;
  if (!stage) return "";
  const { role, complete } = roleQuestStateForPath(path);
  if (role !== "support") return "Support quest items require the support role.";
  if (complete && stage !== "upgraded") {
    return "A completed support quest requires an upgraded support item.";
  }
  if (!complete && stage === "upgraded") {
    return "Complete the support role quest before equipping an upgraded support item.";
  }
  return "";
}

function roleQuestBootUpgradeName(item, complete) {
  const role = state.attacker.role;
  if (!item || role !== "mid") {
    return Number(item?.tier) >= 3
      ? (item?.upgradeFrom || null)
      : item?.name;
  }
  if (complete && Number(item.tier) < 3) return item.upgradeTo || null;
  if (!complete && Number(item.tier) >= 3) return item.upgradeFrom || null;
  return item.name;
}

function normalizeAttackerBootForRole(bootId) {
  const item = getItem(bootId);
  if (!item) return 0;
  const targetName = roleQuestBootUpgradeName(item, Boolean(state.attacker.roleQuestComplete));
  if (!targetName || targetName === item.name) return Number(bootId);
  return findItemByBackendName(targetName)?.id || Number(bootId);
}

function normalizeAttackerBootsForRole() {
  ["A", "B"].forEach((side) => {
    const key = "questBoot" + side;
    if (!state.attacker[key]) return;
    state.attacker[key] = normalizeAttackerBootForRole(state.attacker[key]);
  });
}

function normalizeAttackerSupportItemsForRole() {
  ["A", "B"].forEach((side) => {
    const items = state.attacker[`build${side}`] || [];
    const stacks = state.attacker[`build${side}Stacks`] || [];
    const options = state.attacker[`build${side}ItemOptions`] || [];
    items.forEach((itemId, index) => {
      const item = getItem(itemId);
      const stage = item?.supportQuestStage;
      if (!stage) return;
      const legal = state.attacker.role === "support"
        && (state.attacker.roleQuestComplete ? stage === "upgraded" : stage !== "upgraded");
      if (!legal) {
        items[index] = 0;
        stacks[index] = 0;
        options[index] = {};
      }
    });
  });
}

function normalizeRosterBootForRole(loadout) {
  const item = getItem(loadout?.boots);
  if (!item) return;
  const midUpgrade = loadout.role === "mid" && Boolean(loadout.roleQuestComplete);
  const targetName = midUpgrade
    ? (Number(item.tier) < 3 ? item.upgradeTo : item.name)
    : (Number(item.tier) >= 3 ? item.upgradeFrom : item.name);
  if (targetName && targetName !== item.name) {
    loadout.boots = findItemByBackendName(targetName)?.id || loadout.boots;
  }
}

function normalizeRosterSupportItemsForRole(loadout) {
  if (!loadout?.items) return;
  loadout.items = loadout.items.map((itemId, index) => {
    const item = getItem(itemId);
    const stage = item?.supportQuestStage;
    if (!stage) return itemId;
    const legal = loadout.role === "support"
      && (loadout.roleQuestComplete ? stage === "upgraded" : stage !== "upgraded");
    if (!legal) {
      if (loadout.itemStacks) loadout.itemStacks[index] = 0;
      if (loadout.itemOptions) loadout.itemOptions[index] = {};
      return 0;
    }
    return itemId;
  });
}

function normalizeRosterRoleState(loadout) {
  normalizeRosterBootForRole(loadout);
  normalizeRosterSupportItemsForRole(loadout);
}

function findItemByBackendName(name) {
  return DATA.items.find((item) => item.backendName === name || item.name === name) || null;
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
        if (loadout.itemOptions) loadout.itemOptions[Number(last)] = {};
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
    if (state.attacker[`build${side}ItemOptions`]) state.attacker[`build${side}ItemOptions`][Number(last)] = {};
    invalidateOptimization();
    return;
  }
  parent[Number.isNaN(Number(last)) ? last : Number(last)] = nextValue;
  if (parts[0] === "attacker" && (parts[1] === "buildA" || parts[1] === "buildB") && /^\d+$/.test(String(last))) {
    const optionKey = `${parts[1]}ItemOptions`;
    if (!state.attacker[optionKey]) state.attacker[optionKey] = [{}, {}, {}, {}, {}, {}];
    state.attacker[optionKey][Number(last)] = {};
  } else if ((parts[0] === "targets" || parts[0] === "allies") && parts[2] === "items") {
    const loadout = state[parts[0]]?.[Number(parts[1])];
    if (loadout) {
      if (!loadout.itemOptions) loadout.itemOptions = [{}, {}, {}, {}, {}, {}];
      loadout.itemOptions[Number(last)] = {};
    }
  }
  invalidateOptimization();
}

function itemOptionSpec(id) {
  const specs = itemOptionSpecs(id);
  return specs.length === 1 ? specs[0] : null;
}

function itemOptionIdForPath(path) {
  const parts = String(path || "").split(".");
  if (parts[0] === "attacker" && (parts[1] === "buildA" || parts[1] === "buildB")) {
    const id = Number(state.attacker[parts[1]]?.[Number(parts[2])]);
    return Number.isFinite(id) && id > 0 ? id : 0;
  }
  if ((parts[0] === "targets" || parts[0] === "allies") && parts[2] === "items") {
    const loadout = state[parts[0]]?.[Number(parts[1])];
    const id = Number(loadout?.items?.[Number(parts[3])]);
    return Number.isFinite(id) && id > 0 ? id : 0;
  }
  const value = Number(pathValue(path));
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function itemOptionSpecsForPath(path) {
  return itemOptionSpecs(itemOptionIdForPath(path));
}

function itemOptionSpecs(id) {
  const item = getItem(id);
  const definition = item && engine.itemOptions[item.backendName || item.name];
  const entries = Object.entries(definition?.options || {});
  return entries.map(([key, schema]) => ({
    key,
    label: schema.label || key,
    min: Number(schema.min ?? 0),
    max: Number(schema.max ?? 0),
    step: Number(schema.step ?? 1),
    statEffects: definition.stat_effects?.[key] || {},
    derived: definition.derived || {},
  }));
}

// These controls predate the typed `itemOptions` map and still feed the
// legacy `itemStacks` arrays used by the local stat preview.  All other
// one-field inputs must render through itemOptionControls so that state such
// as Zhonya's explicit Time Stop duration is visible and serialized from the
// correct state bucket.
const LEGACY_STACK_ITEM_NAMES = new Set([
  "Dark Seal",
  "Mejai's Soulstealer",
  "Heartsteel",
  "Rod of Ages",
  "Yun Tal Wildarrows",
  "Overlord's Bloodmail",
]);

function stackSpec(id) {
  const configured = itemOptionSpec(id);
  if (configured && LEGACY_STACK_ITEM_NAMES.has(itemName(id))) return configured;
  // Keep the picker usable during the brief pre-catalogue loading window.
  if (Number(id) === 1082) return { key: "glory_stacks", label: "Glory stacks", min: 0, max: 10, step: 1, statEffects: { bonus_ap_per_unit: 4 } };
  if (Number(id) === 3041) return { key: "glory_stacks", label: "Glory stacks", min: 0, max: 25, step: 1, statEffects: { bonus_ap_per_unit: 5, move_speed_threshold: 10, move_speed_percent: 10 } };
  return null;
}

function itemOptionState(path) {
  const parts = path.split(".");
  if (parts[0] === "attacker" && (parts[1] === "buildA" || parts[1] === "buildB")) {
    const key = `${parts[1]}ItemOptions`;
    const optionBuckets = state.attacker[key] || (state.attacker[key] = [{}, {}, {}, {}, {}, {}]);
    return optionBuckets[Number(parts[2])] || (optionBuckets[Number(parts[2])] = {});
  }
  if ((parts[0] === "targets" || parts[0] === "allies") && parts[2] === "items") {
    const loadout = state[parts[0]][Number(parts[1])];
    if (!loadout.itemOptions) loadout.itemOptions = [{}, {}, {}, {}, {}, {}];
    return loadout.itemOptions[Number(parts[3])] || (loadout.itemOptions[Number(parts[3])] = {});
  }
  return {};
}

function itemOptionValue(path, key) {
  return Number(itemOptionState(path)[key] || 0);
}

function setItemOptionValue(path, key, value) {
  itemOptionState(path)[key] = Number(value);
  invalidateOptimization();
}

function itemOptionControls(path, id, compact = false) {
  const specs = itemOptionSpecs(id);
  // Legacy stack controls render the single state option for stack-backed
  // items. Every other one-option item (for example Time Stop or Ichorshield)
  // still needs its typed scenario control visible in the UI.
  if (specs.length === 0 || (specs.length === 1 && LEGACY_STACK_ITEM_NAMES.has(itemName(id)))) return "";
  const kind = participantKindForPath(path);
  return `<div class="item-option-controls ${compact ? "compact" : ""}" aria-label="${escapeHtml(itemName(id))} state">${specs.map((spec) => {
    const value = Math.min(Math.max(itemOptionValue(path, spec.key), spec.min), spec.max);
    return `<label><span>${escapeHtml(spec.label)}</span><span class="stack-control"><button type="button" ${capabilityAttributes(kind, "item_options")} data-item-option-path="${escapeHtml(path)}" data-item-option-id="${escapeHtml(id)}" data-item-option-key="${escapeHtml(spec.key)}" data-delta="-${spec.step}" aria-label="Decrease ${escapeHtml(spec.label)}">−</button><output>${value}/${spec.max}</output><button type="button" ${capabilityAttributes(kind, "item_options")} data-item-option-path="${escapeHtml(path)}" data-item-option-id="${escapeHtml(id)}" data-item-option-key="${escapeHtml(spec.key)}" data-delta="${spec.step}" aria-label="Increase ${escapeHtml(spec.label)}">+</button></span></label>`;
  }).join("")}</div>`;
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



function rosterOrdinarySlotCount(loadout) {
  if (loadout.role === "bottom" && loadout.roleQuestComplete) return 6;
  return loadout.includeBoots !== false ? 5 : 6;
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
  return state.attacker.role === "mid" && state.attacker.roleQuestComplete
    ? TIER_THREE_BOOTS
    : TIER_TWO_BOOTS;
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

function itemStatsLine(item) {
  if (!item) return "Remove item";
  const stats = [];
  if (item.ap) stats.push(`${item.ap} AP`);
  if (item.ad) stats.push(`${item.ad} AD`);
  if (item.hp) stats.push(`${item.hp} HP`);
  if (item.armor) stats.push(`${item.armor} armor`);
  if (item.mr) stats.push(`${item.mr} MR`);
  if (item.haste) stats.push(`${item.haste} haste`);
  if (item.pen) stats.push(`${item.pen} pen`);
  if (item.percentPen) stats.push(`${item.percentPen}% pen`);
  if (item.attackSpeed) stats.push(`${item.attackSpeed}% AS`);
  if (item.crit) stats.push(`${item.crit}% crit`);
  if (item.lifesteal) stats.push(`${item.lifesteal}% life steal`);
  if (item.omnivamp) stats.push(`${item.omnivamp}% omnivamp`);
  if (item.healAndShieldPower) stats.push(`${item.healAndShieldPower}% heal/shield power`);
  if (item.healthRegen) stats.push(`${item.healthRegen}% health regen`);
  if (item.manaRegen) stats.push(`${item.manaRegen}% mana regen`);
  if (item.goldPer10) stats.push(`${item.goldPer10} gold/10`);
  if (item.critDamage) stats.push(`${item.critDamage}% crit damage`);
  if (item.tenacity) stats.push(`${item.tenacity}% tenacity`);
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


function rosterAbilityRankControls(loadout, index, root) {
  if (!loadout?.champion) return "";
  const profile = bisChampionProfile(loadout);
  const championAbilities = Object.fromEntries((getChampion(loadout.champion)?.abilities || []).map((ability) => [ability.slot, [ability]]));
  const rows = ["Q", "W", "E", "R"].map((slot) => {
    const forms = profile.abilities?.[slot] || championAbilities[slot] || [];
    if (!forms.length) return "";
    const maxRank = Math.max(...forms.map((ability) => ability.maxRank || (slot === "R" ? 3 : 5)));
    const rank = bisRankFor(loadout, slot, maxRank);
    return `<span class="roster-rank"><b>${slot}</b><button type="button" ${capabilityAttributes(root === "allies" ? "ally" : "enemy", "ability_ranks")} data-roster-rank="${root}.${index}.${slot}" data-delta="-1" aria-label="Decrease ${slot} rank">−</button><output>${rank}</output><button type="button" ${capabilityAttributes(root === "allies" ? "ally" : "enemy", "ability_ranks")} data-roster-rank="${root}.${index}.${slot}" data-delta="1" aria-label="Increase ${slot} rank">+</button></span>`;
  }).join("");
  return `<div class="roster-ranks"><small>Wiki ability ranks</small>${rows}</div>`;
}


function stackControl(path, id, compact = false) {
  const spec = stackSpec(id);
  const value = Math.min(Math.max(stackValue(path), spec.min), spec.max);
  const label = `${itemName(id)} ${spec.label || "state"}`;
  const kind = participantKindForPath(path);
  return `<div class="stack-control ${compact ? "compact" : ""}" aria-label="${escapeHtml(label)}">
    <button type="button" ${capabilityAttributes(kind, "item_options")} data-stack-path="${path}" data-delta="-${spec.step}" aria-label="Decrease ${escapeHtml(spec.label || "value")}">−</button>
    <output>${value}/${spec.max}</output>
    <button type="button" ${capabilityAttributes(kind, "item_options")} data-stack-path="${path}" data-delta="${spec.step}" aria-label="Increase ${escapeHtml(spec.label || "value")}">+</button>
  </div>`;
}


const ABILITY_BOUND_CHAMPION_OPTIONS = new Set([
  "passive_procs",
  "mines_hit",
  "r_sweet_spot",
]);

function abilityBindsChampionOption(key) {
  const abilities = activeAbilityKit();
  if (key === "passive_procs") return abilities.some((ability) => ability.slot === "P");
  if (key === "mines_hit") return abilities.some((ability) => ability.slot === "E" && Number(ability.maxHits) > 1);
  if (key === "r_sweet_spot") return abilities.some((ability) => ability.slot === "R" && ability.variants?.length > 1);
  return false;
}


function stringListOptionValue(value) {
  return Array.isArray(value) ? value.join(", ") : String(value || "");
}


function parseStringListOption(value) {
  return [...new Set(String(value || "").split(",").map((item) => item.trim()).filter(Boolean))];
}

function renderChampionOptions() {
  const capability = championOptionCapability("main", state.attacker.champion);
  const optionAttributes = capabilityDescriptorAttributes("champion_options", capability);
  const definitions = (engine.championOptions[state.attacker.champion]?.options || [])
    .filter((option) => !ABILITY_BOUND_CHAMPION_OPTIONS.has(option.key) || !abilityBindsChampionOption(option.key));
  if (!definitions.length) return "";
  const controls = definitions.map((option) => {
    const value = state.attacker.championOptions[option.key] ?? option.default;
    const label = escapeHtml(option.label || option.key);
    if (option.type === "bool") {
      return `<label class="champion-option-toggle"><input type="checkbox" ${optionAttributes} data-champion-option="${escapeHtml(option.key)}" ${value ? "checked" : ""} /><span>${label}</span></label>`;
    }
    if (option.type === "select") {
      const choices = (option.choices || []).map((choice) => `<option value="${escapeHtml(choice.value)}" ${String(value) === String(choice.value) ? "selected" : ""}>${escapeHtml(choice.label || choice.value)}</option>`).join("");
      return `<label class="champion-option-field"><span>${label}</span><select ${optionAttributes} data-champion-option="${escapeHtml(option.key)}" data-option-type="select">${choices}</select></label>`;
    }
    if (option.type === "string_list") {
      return `<label class="champion-option-field"><span>${label}</span><input type="text" ${optionAttributes} data-champion-option="${escapeHtml(option.key)}" data-option-type="string_list" value="${escapeHtml(stringListOptionValue(value))}" placeholder="Q, W" /></label>`;
    }
    const step = option.step ?? (option.type === "int" ? 1 : "any");
    const min = option.min == null ? "" : ` min="${option.min}"`;
    const max = option.max == null ? "" : ` max="${option.max}"`;
    return `<label class="champion-option-field"><span>${label}</span><input type="number" ${optionAttributes} data-champion-option="${escapeHtml(option.key)}" data-option-type="${escapeHtml(option.type)}" value="${escapeHtml(value)}" step="${step}"${min}${max} /></label>`;
  }).join("");
  return `<div class="champion-options"><div class="champion-options-head"><strong>Scenario options</strong><span>These inputs are shared with the reviewed engine.</span></div><div class="champion-options-grid">${controls}</div></div>`;
}

function renderRosterChampionOptions(loadout, path, kind) {
  const definitions = engine.championOptions[loadout?.champion]?.options || [];
  if (!definitions.length) return "";
  const capability = championOptionCapability(kind, loadout.champion);
  const values = loadout.championOptions || {};
  const controls = definitions.map((option) => {
    const value = values[option.key] ?? option.default;
    const key = escapeHtml(option.key);
    const label = escapeHtml(option.label || option.key);
    const common = `${capabilityDescriptorAttributes("champion_options", capability)} data-roster-champion-option="${escapeHtml(path)}" data-option-key="${key}"`;
    if (option.type === "bool") {
      return `<label class="champion-option-toggle"><input type="checkbox" ${common} ${value ? "checked" : ""} /><span>${label}</span></label>`;
    }
    if (option.type === "select") {
      const choices = (option.choices || []).map((choice) => `<option value="${escapeHtml(choice.value)}" ${String(value) === String(choice.value) ? "selected" : ""}>${escapeHtml(choice.label || choice.value)}</option>`).join("");
      return `<label class="champion-option-field"><span>${label}</span><select ${common} data-option-type="select">${choices}</select></label>`;
    }
    if (option.type === "string_list") {
      return `<label class="champion-option-field"><span>${label}</span><input type="text" ${common} data-option-type="string_list" value="${escapeHtml(stringListOptionValue(value))}" placeholder="Q, W" /></label>`;
    }
    const step = option.step ?? (option.type === "int" ? 1 : "any");
    const min = option.min == null ? "" : ` min="${option.min}"`;
    const max = option.max == null ? "" : ` max="${option.max}"`;
    return `<label class="champion-option-field"><span>${label}</span><input type="number" ${common} data-option-type="${escapeHtml(option.type)}" value="${escapeHtml(value)}" step="${step}"${min}${max} /></label>`;
  }).join("");
  return `<div class="champion-options roster-champion-options"><div class="champion-options-head"><strong>Participant options</strong><span>Backend-declared ${escapeHtml(kind)} champion inputs.</span></div><div class="champion-options-grid">${controls}</div></div>`;
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
  const schemas = engine.keystoneOptions[name]?.options || {};
  const values = state.attacker[`keystoneOptions${side}`] || {};
  const controls = Object.entries(schemas).map(([key, option]) => {
    const value = values[key] ?? option.default;
    const min = option.min == null ? "" : ` min="${option.min}"`;
    const max = option.max == null ? "" : ` max="${option.max}"`;
    return `<label class="keystone-option"><span>${escapeHtml(option.label || key)}</span><input type="number" ${capabilityAttributes("main", "keystone")} data-keystone-option="${escapeHtml(side)}" data-keystone-option-key="${escapeHtml(key)}" value="${escapeHtml(value)}" step="1"${min}${max} /></label>`;
  }).join("");
  return `<div class="quest-item keystone-item"><span>Keystone</span><div class="slot-wrap">
    <button class="item-slot keystone-slot" type="button" ${capabilityAttributes("main", "keystone")} data-picker="keystone" data-path="attacker.keystone${side}" aria-label="${keystone ? `Change ${escapeHtml(keystone.name)}` : "Add keystone"}">
      <span class="item-icon keystone-icon ${keystone ? "" : "empty"}">${keystone ? `<img src="${keystone.icon}" alt="" />` : `<span aria-hidden="true">+</span>`}</span>
      <small>${escapeHtml(keystone?.name || "Add keystone")}</small>
    </button>
    ${controls ? `<div class="keystone-options">${controls}</div>` : ""}
  </div></div>`;
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


function survivalStatus(survival = {}) {
  if (survival?.revived && survival?.terminal_phase === "revived") {
    const reviveTime = Number(survival.revive_time);
    return Number.isFinite(reviveTime)
      ? `revived at ${one(reviveTime)}s · alive at window end`
      : "revived · alive at window end";
  }
  if (survival?.survived_window || survival?.death_time == null) return "alive at window end";
  const deathTime = Number(survival.death_time);
  if (!Number.isFinite(deathTime)) return "alive at window end";
  return `defeated at ${killTimeLabel(deathTime) || `${one(deathTime)}s`}`;
}

function breakdownOutcome(aTotal, bTotal = null) {
  if (bTotal == null) return `Build A is the selected build: ${fmt(aTotal)} damage in this window.`;
  if (Math.abs(aTotal - bTotal) < 0.5) return `Build A and Build B are effectively tied at this window: ${fmt(aTotal)} damage each.`;
  const winner = aTotal > bTotal ? "Build A" : "Build B";
  const winnerTotal = Math.max(aTotal, bTotal);
  const loserTotal = Math.min(aTotal, bTotal);
  return `${winner} wins this window: ${fmt(winnerTotal)} damage vs ${fmt(loserTotal)}.`;
}

function engineItemOptions(ids, stacks = [], optionValues = []) {
  const options = {};
  ids.forEach((id, index) => {
    const item = getItem(id);
    const specs = item && itemOptionSpecs(id);
    if (!item || !specs.length) return;
    if (specs.length === 1 && LEGACY_STACK_ITEM_NAMES.has(item.name || item.backendName)) {
      const spec = specs[0];
      options[item.backendName || item.name] = { [spec.key]: Number(stacks[index] || 0) };
      return;
    }
    const provided = optionValues[index] || {};
    options[item.backendName || item.name] = Object.fromEntries(specs.map((spec) => [
      spec.key,
      Math.min(Math.max(Number(provided[spec.key] || 0), spec.min), spec.max),
    ]));
  });
  return options;
}

// The two-argument call shape `engineItemOptions(itemIds, itemStacks)` remains
// valid for callers that do not have multi-field state.

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
  const itemOptionValues = itemIds.map((id) => {
    const originalIndex = ids.indexOf(id);
    return (state.attacker[`build${side}ItemOptions`] || [])[originalIndex] || {};
  });
  return {
    boots: bootId ? itemName(bootId) : "",
    include_boots: includeBootsForSide(side),
    items: itemIds.map((id) => itemName(id)).filter(Boolean),
    item_options: engineItemOptions(itemIds, itemStacks, itemOptionValues),
    keystone: state.attacker[`keystone${side}`] || "",
    keystone_options: engineKeystoneOptions(side),
  };
}

function engineKeystoneOptions(side) {
  const name = state.attacker[`keystone${side}`] || "";
  const schemas = engine.keystoneOptions[name]?.options || {};
  const provided = state.attacker[`keystoneOptions${side}`] || {};
  return Object.fromEntries(Object.entries(schemas).map(([key, option]) => {
    const parsed = Number.parseInt(provided[key] ?? option.default ?? 0, 10);
    const fallback = Number(option.default ?? 0);
    const value = Number.isFinite(parsed) ? parsed : fallback;
    return [key, Math.min(Math.max(value, Number(option.min ?? value)), Number(option.max ?? value))];
  }));
}

function engineChampionOptions() {
  const champion = state.attacker.champion;
  const definition = engine.championOptions[champion];
  if (!definition?.options) return {};
  const options = Object.fromEntries(
    definition.options.map((option) => [
      option.key,
      state.attacker.championOptions[option.key] ?? option.default,
    ]),
  );
  definition.options.forEach((option) => {
    if (option.key === "passive_procs" && abilityBindsChampionOption(option.key)) {
      options[option.key] = abilityInput("P").casts;
    } else if (option.key === "mines_hit" && abilityBindsChampionOption(option.key)) {
      options[option.key] = abilityInput("E").hits;
    } else if (option.key === "r_sweet_spot" && abilityBindsChampionOption(option.key)) {
      options[option.key] = abilityInput("R").variant === 0;
    }
  });
  return options;
}

function engineAbilityRanks() {
  if (usesLevelDerivedRanks(state.attacker.champion)) return null;
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
    .slice(0, rosterOrdinarySlotCount(target))
    .filter(Boolean)
    .filter((id) => !ALL_ROLE_BOOTS.has(Number(id)));
  return {
    champion: target.champion,
    level: target.level,
    items: itemIds.map((id) => itemName(id)).filter(Boolean),
    boots: target.includeBoots && selectedBoot ? itemName(selectedBoot) : "",
    include_boots: Boolean(target.includeBoots),
    item_options: engineItemOptions(itemIds, target.itemStacks, target.itemOptions),
    role: target.role || "",
    role_quest_complete: Boolean(target.roleQuestComplete),
    champion_options: Object.fromEntries(
      Object.entries(target.championOptions || {}).map(([key, value]) => [key, value]),
    ),
    support_target_selections: { ...(target.supportTargetSelections || {}) },
    // Let the backend apply the champion's sourced level order for
    // transformation/stance kits; their generic rank controls are not a
    // legal manual allocation.
    ability_ranks: usesLevelDerivedRanks(target.champion)
      ? null
      : Object.fromEntries(Object.entries(target.abilityRanks || {}).map(([slot, rank]) => [slot, Number(rank) || 0])),
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
    target_health: Number(engine.defaultTarget.health || 1000),
    target_bonus_health: Number(engine.defaultTarget.bonus_health || 0),
    target_armor: Number(engine.defaultTarget.armor || 100),
    target_mr: Number(engine.defaultTarget.mr || 100),
    enemies: state.targets.filter((target) => target.champion).map(engineTarget),
    allies: state.allies.filter((ally) => ally.champion).map(engineAlly),
    role: state.attacker.role || "",
    role_quest_complete: state.attacker.roleQuestComplete,
    include_actives: true,
    include_crossover: state.attacker.comparisonEnabled || state.fight.rotations > 1,
    champion_options: engineChampionOptions(),
    support_target_selections: { ...(state.attacker.supportTargetSelections || {}) },
    ability_ranks: engineAbilityRanks(),
    rotations: state.fight.rotations,
  };
  const maxWindow = Number(engine.fightLimits.fight_duration?.[1] || 30);
  const requestedWindow = Math.max(1, state.fight.duration * state.fight.rotations);
  payload.auto_attack_uptime_mode = state.fight.aaUptimeMode || "calculated";
  if (state.fight.aaUptimeMode === "calculated") {
    payload.fight_mode = state.fight.rotations > 1 ? "time_based" : "one_rotation";
    payload.fight_duration = Math.min(maxWindow, requestedWindow);
    payload.include_auto_attacks = true;
    payload.auto_attack_uptime = 0;
  } else if (state.fight.aaUptime > 0) {
    payload.fight_mode = "time_based";
    payload.fight_duration = Math.min(maxWindow, requestedWindow);
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


function exactBreakdown(result) {
  return Object.entries(result?.breakdown || {}).filter(([, entry]) => Number(entry.total_damage || 0) > 0).map(([slotKey, entry]) => ({
    slot: slotKey,
    source: entry.name || entry.slot || "Damage source",
    detail: (() => {
      const base = entry.casts ? `${entry.casts} cast${entry.casts === 1 ? "" : "s"}` : entry.count ? `${entry.count} hit${entry.count === 1 ? "" : "s"}` : "Event-ordered output";
      const window = entry.temporary_lethality;
      const targeting = entry.targeting;
      const targetDetail = targeting?.kind === "chain_lightning"
        ? ` · chain ${Number(targeting.chain_target_count || 0)} targets · roster slot ${Number(targeting.allocated_target_index || 0) + 1}`
        : targeting?.kind === "chain_lightning_copied_on_hit"
          ? ` · copied on-hit · roster slot ${Number(targeting.allocated_target_index || 0) + 1}`
          : targeting?.kind === "runaan_bolt"
            ? ` · Runaan bolt · roster slot ${Number(targeting.allocated_target_index || 0) + 1}`
            : targeting?.kind === "runaan_bolt_copied_on_hit"
              ? ` · Runaan copied on-hit · roster slot ${Number(targeting.allocated_target_index || 0) + 1}`
              : targeting?.kind === "hydra_cleave"
                ? ` · Titanic Cleave · roster slot ${Number(targeting.allocated_target_index || 0) + 1}`
                : targeting?.kind === "active_secondary"
                  ? ` · active secondary packet · roster slot ${Number(targeting.allocated_target_index || 0) + 1}`
                  : targeting?.kind === "cleave_secondary"
                    ? ` · Cleave on-hit · roster slot ${Number(targeting.allocated_target_index || 0) + 1}`
          : "";
      if (!window || Number(window.amount) <= 0 || Number(window.duration) <= 0) return `${base}${targetDetail}`;
      const applied = Number(window.applied_event_count || 0);
      const state = applied ? `${applied} later event${applied === 1 ? "" : "s"} applied` : "no later events applied";
      return `${base}${targetDetail} · +${one(window.amount)} lethality for ${one(window.duration)}s · ${state}`;
    })(),
    damage: Number(entry.total_damage || 0),
  }));
}


// Standalone calculations expose self-healing at the top level, while
// coupled combat responses place the same receipts under combat. Keep one
// UI path for both response shapes and prefer the ordered combat ledger when
// it is present so events are never rendered twice.
function healingEventsForResult(result) {
  const combatEvents = Array.isArray(result?.combat?.healing_events)
    ? result.combat.healing_events
    : [];
  if (combatEvents.length) return combatEvents;
  return (Array.isArray(result?.self_healing_events) ? result.self_healing_events : []).map((event) => ({
    ...event,
    attacker: event.attacker || "main",
    amount: Number(event.amount || 0),
    raw_amount: Number(event.raw_amount ?? event.amount ?? 0),
    applied_amount: Number(event.applied_amount ?? event.amount ?? 0),
  }));
}

function renderDefenseReceipts(aResult, bResult) {
  const host = document.getElementById("defenseReceipts");
  if (!host) return;
  const startingDefenseSummary = (defenses = {}) => {
    const rows = [];
    const magicShield = Number(defenses.magic_shield || 0);
    const physicalShield = Number(defenses.physical_shield || 0);
    const generalShield = Number(defenses.general_shield || 0);
    const thresholdShield = Number(defenses.threshold_shield?.amount || 0);
    if (magicShield > 0) rows.push(`${fmt(magicShield)} magic shield`);
    if (physicalShield > 0) rows.push(`${fmt(physicalShield)} physical shield`);
    if (generalShield > 0) rows.push(`${fmt(generalShield)} shield`);
    if (thresholdShield > 0) rows.push(`${fmt(thresholdShield)} threshold shield`);
    if (defenses.spell_shield?.ready) rows.push("opening spell shield");
    const incoming = defenses.incoming_damage || {};
    const basicMultiplier = Number(incoming.basic_damage_multiplier || 1);
    const basicReduction = Math.max(0, (1 - basicMultiplier) * 100);
    if (basicReduction > 0.01) rows.push(`${one(basicReduction)}% basic damage reduction`);
    const flatReduction = Number(incoming.basic_damage_flat_reduction || 0);
    if (flatReduction > 0) rows.push(`${fmt(flatReduction)} flat basic reduction`);
    const critMultiplier = Number(incoming.critical_strike_damage_multiplier || 1);
    if (critMultiplier < 0.999) rows.push(`${one((1 - critMultiplier) * 100)}% critical damage reduction`);
    return rows.length ? rows.join(" · ") : "—";
  };
  const targetRows = (aResult?.targets || []).map((entry, index) => {
    const target = entry.target || {};
    const result = entry.result || {};
    const other = bResult?.targets?.[index]?.result;
    const armor = `${one(result.effective_armor)}${other ? ` / ${one(other.effective_armor)}` : ""}`;
    const mr = `${one(result.effective_mr)}${other ? ` / ${one(other.effective_mr)}` : ""}`;
    const defenses = startingDefenseSummary(target.starting_defenses);
    return `<tr><td>${escapeHtml(target.champion || "Target")}</td><td>${armor}</td><td>${mr}</td><td>${escapeHtml(defenses)}</td></tr>`;
  }).join("");
  const shieldParts = [
    ["magic", aResult?.magic_shield_absorbed],
    ["physical", aResult?.physical_shield_absorbed],
    ["general", aResult?.general_shield_absorbed],
    ["threshold", aResult?.threshold_shield_absorbed],
  ].filter(([, amount]) => Number(amount || 0) > 0).map(([label, amount]) => `${fmt(amount)} ${label}`);
  const receiptLines = [];
  const shieldTotal = Number(aResult?.shield_absorbed || 0);
  if (shieldTotal > 0) receiptLines.push(`${fmt(shieldTotal)} shield damage absorbed${shieldParts.length ? ` (${escapeHtml(shieldParts.join(" · "))})` : ""}`);
  const selfHealing = Number(aResult?.self_healing || 0);
  if (selfHealing > 0) receiptLines.push(`${fmt(selfHealing)} self-healing`);
  const targetHealing = Number(aResult?.target_healing_received || 0);
  if (targetHealing > 0) receiptLines.push(`${fmt(targetHealing)} target healing received`);
  if (aResult?.threshold_health_triggered) receiptLines.push("threshold-health transition triggered");
  const thresholdBonus = Number(aResult?.threshold_health_bonus_gained || 0);
  if (thresholdBonus > 0) receiptLines.push(`${fmt(thresholdBonus)} threshold health gained`);
  const damageTypeOutputs = Object.entries(aResult?.damage_by_type || {})
    .filter(([, amount]) => Number(amount || 0) > 0)
    .map(([type, amount]) => `${fmt(amount)} ${type}`);
  if (damageTypeOutputs.length) receiptLines.push(`${escapeHtml(damageTypeOutputs.join(" · "))} output`);
  if (state.targets.length === 1 && Number.isFinite(Number(aResult?.target_ending_health)) && Number.isFinite(Number(aResult?.target_effective_max_health))) {
    receiptLines.push(`target endpoint ${fmt(aResult.target_ending_health)} / ${fmt(aResult.target_effective_max_health)} health`);
  }
  const mainParticipant = (aResult?.combat?.participants || []).find((participant) => participant.participant_id === "main");
  const mainSurvival = mainParticipant?.survival;
  if (mainSurvival) {
    const note = `${fmt(mainSurvival.effective_health || 0)} eHP${Number(mainSurvival.support_shield_received || 0) > 0 ? ` · ${fmt(mainSurvival.support_shield_received)} support shield received` : ""}${mainSurvival.revived && mainSurvival.terminal_phase === "revived" ? ` · revived at ${one(mainSurvival.revive_time)}s` : mainSurvival.survived_window ? " · alive through the window" : ` · defeated at ${one(mainSurvival.death_time)}s`}`;
    receiptLines.push(`main ${note}`);
  }
  const defenseRows = targetRows
    ? `<header><div><p class="eyebrow">Defense receipts</p><h2>Starting defenses</h2></div><span>After build penetration</span></header><div class="damage-table-wrap"><table class="damage-table"><thead><tr><th>Enemy</th><th>Armor${bResult ? " · A / B" : ""}</th><th>MR${bResult ? " · A / B" : ""}</th><th>Starting defenses</th></tr></thead><tbody>${targetRows}</tbody></table></div>`
    : "";
  const receiptSummary = receiptLines.length
    ? `<p class="breakdown-outcome" role="status">${escapeHtml(receiptLines.join(" · "))}</p>`
    : "";
  host.hidden = !(defenseRows || receiptSummary);
  host.innerHTML = defenseRows + receiptSummary;
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
  // The legacy per-target breakdown is scoped to the selected main attacker.
  // A coupled fight also has sourced output from every selected ally and
  // enemy.  Surface those participant/source pairs here so the detailed
  // table cannot silently look like a one-sided calculation when the ledger
  // above already contains a bidirectional event timeline.
  const survivalByParticipant = new Map((aResult?.combat?.participants || []).map((participant) => [participant.participant_id, participant.survival || {}]));
  const ingestCombatSources = (result, side) => (result?.combat?.breakdown || []).forEach((participant) => {
    (participant.sources || []).forEach((source) => {
      const participantLabel = `${participant.champion || "Participant"} · ${participant.team || ""}`.trim();
      const sourceLabel = `${participantLabel} · ${source.name || "Damage source"}`;
      const detail = `Before defeat · ${survivalStatus(survivalByParticipant.get(participant.participant_id))}`;
      const key = `${sourceLabel}:${detail}`;
      const row = rows.get(key) || { source: sourceLabel, detail, damage: 0, a: 0, b: 0 };
      row[side] += Number(source.total_damage || 0);
      rows.set(key, row);
    });
  });
  // Keep the exact main-attacker rows above for backwards-compatible naming,
  // then add the coupled participant rows (including main) with explicit
  // ownership labels.  The UI deduplicates only identical source/detail keys.
  ingestCombatSources(aResult, "a");
  if (bResult) ingestCombatSources(bResult, "b");
  const body = [...rows.values()].map((row) => `<tr><td><strong>${escapeHtml(row.source)}</strong>${certaintyChipHtml(row.slot)}<small>${escapeHtml(row.detail)}</small></td><td>${fmt(row.a)}</td>${bResult ? `<td>${fmt(row.b)}</td><td>${Math.abs(row.a - row.b) < .5 ? "—" : `${row.a > row.b ? "+" : ""}${fmt(row.a - row.b)}`}</td>` : ""}</tr>`).join("");
  const mainTotal = (result) => Number(result?.combat?.breakdown?.find((entry) => entry.participant_id === "main")?.total_damage ?? result?.total_damage ?? 0);
  const aMainTotal = mainTotal(aResult);
  const bMainTotal = bResult ? mainTotal(bResult) : 0;
  const totalB = bResult ? `<td>${fmt(bMainTotal)}</td><td>${Math.abs(aMainTotal - bMainTotal) < .5 ? "—" : `${aMainTotal > bMainTotal ? "+" : ""}${fmt(aMainTotal - bMainTotal)}`}</td>` : "";
  const combatRows = (aResult?.combat?.participants || []).map((participant) => {
    const entry = (aResult?.combat?.breakdown || []).find((row) => row.participant_id === participant.participant_id) || {};
    const survival = participant.survival || {};
    const status = survivalStatus(survival);
    const participantLabel = `${entry.champion || participant.champion || participant.participant_id || "Participant"}${entry.team || participant.team ? ` · ${entry.team || participant.team}` : ""}`;
    const appliedIncoming = Number(survival.health_damage || 0) + Number(survival.shield_absorbed || 0);
    const reduced = Number(survival.healing_reduced || 0);
    const supportShield = Number(survival.support_shield_received || 0);
    const temporaryHealth = Number(survival.temporary_health_received || 0);
    return `<tr><td><strong>${escapeHtml(participantLabel)}</strong><small>${escapeHtml(status)} · ${fmt(survival.effective_health || 0)} eHP · ${fmt(survival.healing_received || 0)} healing${temporaryHealth ? ` · ${fmt(temporaryHealth)} temporary health` : ""}${supportShield ? ` · ${fmt(supportShield)} support shield received` : ""}${reduced ? ` · ${fmt(reduced)} anti-heal prevented` : ""}</small></td><td>${fmt(entry.total_damage || 0)}</td><td>${fmt(appliedIncoming)}</td>${bResult ? `<td>—</td><td>—</td>` : ""}</tr>`;
  }).join("");
  const combatSection = combatRows ? `<section class="combat-participant-ledger"><header><div><p class="eyebrow">Team-fight ledger</p><h2>Participant survival</h2></div><span>Output · incoming · endpoint</span></header><div class="damage-table-wrap"><table class="damage-table"><thead><tr><th>Participant</th><th><i class="legend-a"></i>Output before defeat</th><th>Applied incoming damage</th>${bResult ? `<th><i class="legend-b"></i>Build B</th><th>A − B</th>` : ""}</tr></thead><tbody>${combatRows}</tbody></table></div></section>` : "";
  const labels = new Map((aResult?.combat?.participants || []).map((participant) => [participant.participant_id, `${participant.champion} · ${participant.team}`]));
  const healingRows = healingEventsForResult(aResult).filter((event) => Number(event.raw_amount || event.amount || 0) > 0).map((event) => {
    const factor = Number(event.healing_reduction_factor || 1);
    const wound = factor < 1 ? ` · Grievous Wounds ${Math.round((1 - factor) * 100)}%` : "";
    return `<tr><td><strong>${one(event.time)}s · ${escapeHtml(labels.get(event.attacker) || event.attacker || "Participant")}</strong>${certaintyChipHtml(event.source)}<small>${escapeHtml(event.source || "healing")} · ${escapeHtml(event.kind || "heal")}${wound}</small></td><td>${fmt(event.applied_amount || 0)}<small>${fmt(event.raw_amount || event.amount || 0)} sourced</small></td></tr>`;
  }).join("");
  const supportRows = (aResult?.combat?.support_events || []).filter((event) => Number(event.applied_amount || event.amount || 0) > 0).map((event) => {
    const target = labels.get(event.target || event.recipient) || event.target || event.recipient || "selected teammate";
    const policy = event.target_policy || event.target_scope || "explicit recipient";
    const details = [
      Number.isFinite(Number(event.bonus_attack_speed_percent)) ? `${fmt(event.bonus_attack_speed_percent)}% AS` : "",
      Number.isFinite(Number(event.on_hit_magic_damage)) ? `${fmt(event.on_hit_magic_damage)} on-hit magic` : "",
      Number.isFinite(Number(event.ability_power)) && Number(event.ability_power) ? `+${fmt(event.ability_power)} AP` : "",
      Number.isFinite(Number(event.ability_haste)) && Number(event.ability_haste) ? `+${fmt(event.ability_haste)} AH` : "",
      Number.isFinite(Number(event.bonus_move_speed_percent)) ? `${fmt(event.bonus_move_speed_percent)}% MS` : "",
      Number.isFinite(Number(event.chain_fraction)) ? `${Math.round(Number(event.chain_fraction) * 100)}% chain` : "",
      Number.isFinite(Number(event.armor_reduction_percent)) ? `${Math.round(Number(event.armor_reduction_percent) * 100)}% armor shred` : "",
      Number.isFinite(Number(event.mr_reduction_percent)) ? `${Math.round(Number(event.mr_reduction_percent) * 100)}% MR shred` : "",
      Number.isFinite(Number(event.multiplier)) && Number(event.multiplier) !== 1 ? `${Math.round((Number(event.multiplier) - 1) * 100)}% damage` : "",
      Number.isFinite(Number(event.gold_amount)) && Number(event.gold_amount) ? `${fmt(event.gold_amount)} gold` : "",
      Number.isFinite(Number(event.ward_uses)) && Number(event.ward_uses) ? `${fmt(event.ward_uses)} wards` : "",
      Number.isFinite(Number(event.bonus_mana_total)) && Number(event.bonus_mana_total) ? `${fmt(event.bonus_mana_total)} bonus mana` : "",
      Number.isFinite(Number(event.true_damage_on_ward_hit)) ? `${fmt(event.true_damage_on_ward_hit)} true dmg vs wards` : "",
      event.ward_only ? "Blackout" : "",
      event.cleanse ? "cleanse" : "",
    ].filter(Boolean).join(" · ");
    return `<tr><td><strong>${one(event.time)}s · ${escapeHtml(labels.get(event.attacker) || event.attacker || "Participant")}</strong><small>${escapeHtml(event.source || "support")} · ${escapeHtml(event.kind || "support")} · to ${escapeHtml(target)}${details ? ` · ${escapeHtml(details)}` : ""}</small></td><td>${fmt(event.applied_amount || event.amount || 0)}<small>${escapeHtml(policy)}</small></td></tr>`;
  }).join("");
  const utility = aResult?.combat?.utility_outcomes?.focus || null;
  const targetAllocation = aResult?.combat?.target_allocation || null;
  const supportControls = supportTargetControls(aResult);
  const utilitySummary = utility ? `<section class="utility-outcome-ledger" aria-label="Utility outcome dimensions"><header><div><p class="eyebrow">Utility objective</p><h2>Applied non-TDD outcomes</h2></div><span>Native units · no guessed conversion</span></header><p class="utility-outcome-note">${escapeHtml(utility.metric_note || "Movement, slows, cleanse, economy, and vision remain separate from TDD.")}</p><div class="utility-outcome-chips"><span>Movement ${fmt(utility.movement?.speed_percent_seconds || 0)} %·s</span><span>Slow ${fmt(utility.slow?.percent_seconds || 0)} %·s</span><span>Cleanse ${fmt(utility.cleanse?.event_count || 0)} events</span><span>Economy ${fmt(utility.economy?.gold || 0)} gold</span><span>Vision ${fmt(utility.vision?.ward_uses || 0)} wards</span><span>Resource ${fmt(utility.resource?.bonus_mana || 0)} bonus mana</span><span>Secondary ${fmt(utility.multi_target?.allocated_packet_count || 0)}/${fmt(utility.multi_target?.packet_count || 0)} allocated</span></div></section>` : "";
  const allocationNote = targetAllocation && targetAllocation.secondary_packet_count ? `<p class="utility-target-allocation" role="status">Target allocation: ${targetAllocation.complete ? "complete" : "withheld"} · ${fmt(targetAllocation.allocated_secondary_packet_count || 0)}/${fmt(targetAllocation.secondary_packet_count || 0)} secondary packets use the authored roster-index policy.</p>` : "";
  const eventSection = healingRows || supportRows || utilitySummary ? `<details class="breakdown-audit"><summary>Recovery and support <span>Healing · protection · utility</span></summary>${utilitySummary}${allocationNote}<section class="combat-event-ledger" aria-label="Recovery and support audit"><header><div><p class="eyebrow">Recovery and support</p><h2>Applied effects</h2></div><span>Healing · protection · utility</span></header><div class="damage-table-wrap"><table class="damage-table"><thead><tr><th>Effect</th><th>Applied value</th></tr></thead><tbody>${healingRows}${supportRows}</tbody></table></div></section></details>` : "";
  const outcome = `<p class="breakdown-outcome" role="status">${escapeHtml(breakdownOutcome(aMainTotal, bResult ? bMainTotal : null))}</p>`;
  $("damageBreakdown").innerHTML = `${outcome}${combatSection}${supportControls}${eventSection}<header><div><p class="eyebrow">Damage breakdown</p><h2>Damage sources</h2></div><span>${state.targets.length} ${plural(state.targets.length, "target")} · ${state.fight.rotations} ${plural(state.fight.rotations, "rotation")}</span></header><div class="damage-table-wrap"><table class="damage-table"><thead><tr><th>Source</th><th><i class="legend-a"></i>Build A</th>${bResult ? `<th><i class="legend-b"></i>Build B</th><th>A − B</th>` : ""}</tr></thead><tbody>${body}<tr class="damage-total"><td><strong>Main output before defeat</strong><small>Post-mitigation output · ${escapeHtml(survivalStatus((aResult?.combat?.participants || []).find((participant) => participant.participant_id === "main")?.survival))}</small></td><td>${fmt(aMainTotal)}</td>${totalB}</tr></tbody></table></div>`;
}


function supportSelectionOwner(attacker) {
  if (attacker === "main") return state.attacker;
  if (!String(attacker || "").startsWith("ally:")) return null;
  return state.allies.find((ally) => `ally:${ally.champion}` === attacker) || null;
}


function supportSelectionTeammates(attacker) {
  if (attacker === "main") return state.allies.filter((ally) => ally.champion);
  const owner = supportSelectionOwner(attacker);
  if (!owner) return [];
  return [
    ...(state.attacker.champion ? [state.attacker] : []),
    ...state.allies.filter((ally) => ally.champion && ally !== owner),
  ];
}


function supportTargetControls(result) {
  const selectionScopes = new Set([
    "one_teammate",
    "self_and_one_teammate",
    "explicit_selected_ally",
    "healed_or_shielded_ally",
    "most_wounded_ally",
    "nearest_most_wounded_ally",
    "other_nearest_wounded_ally",
  ]);
  const packets = new Map();
  (result?.combat?.support_events || []).forEach((event) => {
    const attacker = String(event.attacker || "");
    const key = String(event.target_selection_key || "");
    if (!attacker || !key || !selectionScopes.has(String(event.target_scope || ""))) return;
    if (String(event.target || "") === attacker) return;
    packets.set(attacker + ":" + key, event);
  });
  const controls = [...packets.values()].map((event) => {
    const owner = supportSelectionOwner(event.attacker);
    const teammates = supportSelectionTeammates(event.attacker);
    if (!owner || !teammates.length) return "";
    if (!owner.supportTargetSelections) owner.supportTargetSelections = {};
    const selected = Math.min(
      Math.max(0, Number(owner.supportTargetSelections[event.target_selection_key] ?? 0)),
      teammates.length - 1,
    );
    const choices = teammates.map((teammate, index) => {
      const name = teammate.champion || (teammate === state.attacker ? "Main champion" : "Teammate");
      return "<option value=\"" + index + "\" " + (index === selected ? "selected" : "") + ">" + escapeHtml(name) + "</option>";
    }).join("");
    const label = String(event.source || event.kind || "Support packet") + " · " + String(event.kind || "effect");
    return "<label class=\"support-target-control\"><span>" + escapeHtml(label) + "</span><select class=\"support-target-selection\" data-capability-field=\"support_target_selections\" data-option-key=\"" + escapeHtml(event.target_selection_key) + "\" data-value=\"" + escapeHtml(event.attacker) + "\" aria-label=\"Choose recipient for " + escapeHtml(label) + "\">" + choices + "</select></label>";
  }).filter(Boolean).join("");
  if (!controls) return "";
  return "<section class=\"support-target-panel\" aria-label=\"Support recipients\"><header><div><p class=\"eyebrow\">Support recipients</p><h2>Choose who receives each single-target effect</h2></div><span>Area effects keep their sourced roster scope</span></header><div class=\"support-target-grid\">" + controls + "</div></section>";
}


function engineErrorBox() {
  return document.getElementById("engineError");
}

function showEngineError(message) {
  const box = engineErrorBox();
  if (!box) return;
  box.textContent = String(message || "The engine could not compute this scenario.");
  box.hidden = false;
}

function hideEngineError() {
  const box = engineErrorBox();
  if (box) box.hidden = true;
}

function clearAnalystScores() {
  ["scoreA", "scoreB", "buildAScore", "buildBScore"].forEach((id) => {
    const element = $(id);
    if (element) element.textContent = "Unavailable";
  });
}

function scheduleEngineCalculation() {
  if (engine.pendingTimer) clearTimeout(engine.pendingTimer);
  if (!engine.ready || !state.attacker.champion || !state.targets.length || !state.targets.every((target) => target.champion)) return;
  if (!engine.reviewed.has(state.attacker.champion) && !engine.backend.has(state.attacker.champion)) return;
  engine.pendingTimer = setTimeout(() => {
    const requestId = ++engine.requestId;
    engine.pending = true;
    const status = document.getElementById("resultStatus");
    if (status) {
      status.textContent = "calculating";
      status.classList.add("calculating");
    }
    hideEngineError();
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
          if (status) {
            status.textContent = "error";
            status.classList.remove("calculating");
          }
          showEngineError(failure.error);
          clearAnalystScores();
          return;
        }
        if (status) status.classList.remove("calculating");
        hideEngineError();
        engine.responses = { a: results[0], b: results[1] || null };
        renderPrototypeBuilder();
        renderPrototypeResult(engine.responses.a, engine.responses.b);
        renderScenarioRail();
      })
      .catch((error) => {
        if (requestId === engine.requestId) {
          if (status) {
            status.textContent = "error";
            status.classList.remove("calculating");
          }
          showEngineError(`Engine request failed: ${error.message}`);
          clearAnalystScores();
        }
      })
      .finally(() => { if (requestId === engine.requestId) engine.pending = false; });
  }, 40);
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
  const stateLabel = state.ui.gameState === "live" ? "snapshot lens" : "theory state";
  const objectiveLabel = OBJECTIVES[state.ui.objective]?.label || "Overall";
  return `<strong>${escapeHtml(state.attacker.champion)} level ${state.attacker.level}</strong>${buildA.length ? ` with ${escapeHtml(buildA.join(" + "))}` : ""}${keystoneText}${compareText}${targetText} · ${escapeHtml(objectiveLabel)} · ${stateLabel} · ${state.fight.rotations} ${plural(state.fight.rotations, "rotation")} · ${one(state.fight.duration)}s each · ${Math.round(state.fight.aaUptime * 100)}% auto uptime${allyText}.`;
}

function scenarioViewModel() {
  const champion = getChampion(state.attacker.champion);
  const role = state.attacker.role ? state.attacker.role.toUpperCase() : "ROLE NOT SET";
  const objective = OBJECTIVES[state.ui.objective] || OBJECTIVES.overall;
  return {
    champion: champion?.name || "Choose champion",
    role,
    level: state.attacker.level,
    objective: objective.label,
    gameState: state.ui.gameState === "live" ? "Snapshot" : "Theory",
    roster: state.targets.filter((target) => target.champion).length,
    comparison: Boolean(state.attacker.comparisonEnabled),
  };
}

function renderScenarioRail() {
  const model = scenarioViewModel();
  const championButton = $("scenarioChampion");
  if (championButton) {
    championButton.textContent = model.champion;
    championButton.setAttribute("aria-label", `${model.champion}; choose champion`);
  }
  const role = $("scenarioRole");
  if (role) role.textContent = model.role;
  const roleSelect = $("roleSelect");
  if (roleSelect) {
    roleSelect.value = state.attacker.role || "";
    const roleCapability = capabilityFor("main", "role");
    roleSelect.disabled = roleCapability.supported === false;
    roleSelect.title = capabilityTitle(roleCapability);
    roleSelect.dataset.capabilityField = "role";
  }
  const stateReadout = $("stateReadout");
  if (stateReadout) stateReadout.textContent = `${model.gameState} · ${state.fight.rotations} ${plural(state.fight.rotations, "rotation")}`;
  document.querySelectorAll("[data-objective]").forEach((button) => {
    const selected = button.dataset.objective === state.ui.objective;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  // Every game-state button carries its own description for assistive tech
  // (#150). The active one is mirrored into the visible summary so sighted
  // users read the same sentence — the copy lives in the template only.
  const summary = $("gameStateHelp");
  document.querySelectorAll("[data-game-state]").forEach((button) => {
    const selected = button.dataset.gameState === state.ui.gameState;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
    const description = document.getElementById(button.getAttribute("aria-describedby") || "");
    if (description) {
      button.title = description.textContent;
      if (selected && summary) summary.textContent = description.textContent;
    }
  });
}

function participantRows(result) {
  const breakdown = result?.combat?.breakdown || [];
  const participants = result?.combat?.participants || [];
  const byId = new Map(participants.map((row) => [row.participant_id, row]));
  return breakdown.map((row) => ({ ...(byId.get(row.participant_id) || {}), ...row, survival: row.survival || byId.get(row.participant_id)?.survival })).concat(
    participants.filter((row) => !breakdown.some((entry) => entry.participant_id === row.participant_id)),
  );
}

function exactObjectiveMetric(result, fallbackDamage = 0) {
  const rows = participantRows(result);
  const main = rows.find((row) => row.participant_id === "main") || {};
  const enemies = rows.filter((row) => String(row.participant_id || "").startsWith("enemy:"));
  // Damage is the selected team's output.  Enemy retaliation belongs in the
  // survival ledger, never in the main team's damage objective.
  const alliedRows = rows.filter((row) => row.team === "main" || row.participant_id === "main" || String(row.participant_id || "").startsWith("ally:"));
  const teamDamage = alliedRows.reduce((sum, row) => sum + Number(row.total_damage || 0), 0);
  // Main-participant healing is serialized under the survival ledger.  Keep
  // the legacy top-level field as a compatibility fallback for older payloads.
  const healingReceived = result?.healing_received ?? main.survival?.healing_received;
  const hasHealingReceipt = healingReceived !== null && healingReceived !== undefined;
  const supportShield = result?.support_shield_received ?? main.survival?.support_shield_received;
  const hasSupportShieldReceipt = supportShield !== null && supportShield !== undefined;
  // `Number(null)` is 0, which used to turn an alive enemy into an instant
  // kill.  Only explicit finite death timestamps qualify for Kill pressure.
  const firstDeath = enemies
    .flatMap((row) => [row.survival?.first_death_time, row.survival?.death_time])
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map((value) => Number(value))
    .filter(Number.isFinite)
    .sort((a, b) => a - b)[0];
  return {
    overall: Number(main.total_damage ?? fallbackDamage),
    damage: alliedRows.length ? teamDamage : Number(main.total_damage ?? fallbackDamage),
    kill: firstDeath == null ? null : firstDeath,
    survival: Number(main.survival?.effective_health),
    utility: result?.shield_absorbed == null && !hasHealingReceipt && !hasSupportShieldReceipt
      ? null
      : Number(result?.shield_absorbed || 0) + Number(healingReceived || 0) + Number(supportShield || 0),
  };
}

function objectiveMetric(result, fallbackDamage = 0) {
  const key = state.ui.objective;
  const value = exactObjectiveMetric(result, fallbackDamage)[key];
  return Number.isFinite(value) ? value : null;
}

function killTimeLabel(value) {
  // A finite kill always shows its real time-to-defeat from the timeline.
  // Zero (or a value that rounds to 0.0) is a defeat at the first event, not
  // "no time elapsed" — render it as a sub-second label instead of "0 s".
  if (value == null) return null;
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds <= 0) return "<1 s";
  return seconds < 0.05 ? "<1 s" : `${one(seconds)} s`;
}

function objectiveFormat(value) {
  if (value == null) return "Unavailable";
  if (state.ui.objective === "kill") return killTimeLabel(value) || "Unavailable";
  const unit = { overall: "TDD", survival: "eHP", damage: "TDD", utility: "value" }[state.ui.objective] || "value";
  return `${fmt(value)} ${unit}`;
}

function objectiveWinner(aValue, bValue) {
  if (aValue == null || bValue == null) return { winner: null, delta: null };
  const lower = OBJECTIVES[state.ui.objective]?.direction === "lower";
  if (Math.abs(aValue - bValue) < (lower ? 0.05 : 0.5)) return { winner: "tie", delta: 0 };
  return { winner: lower ? (aValue < bValue ? "A" : "B") : (aValue > bValue ? "A" : "B"), delta: Math.abs(aValue - bValue) };
}

function prototypeStats(stats) {
  const champion = getChampion(state.attacker.champion);
  const resourceLabel = champion?.resource || "Resource";
  const rows = [
    ["HP", fmt(stats.hp), "HP"], ["Bonus HP", fmt(stats.bonusHp), "+HP"], ["Total HP", fmt(stats.hp), "MAX"], [resourceLabel, fmt(stats.mana), resourceLabel.slice(0, 3).toUpperCase()],
    ["Attack damage", one(stats.ad), "AD"], ["Ability power", one(stats.ap), "AP"], ["Armor", one(stats.armor), "AR"], ["Magic resist", one(stats.mr), "MR"],
    ["Attack speed", one(stats.attackSpeed), "AS"], ["Move speed", one(stats.moveSpeed), "MS"], ["Ability haste", one(stats.haste), "AH"], ["Crit chance", `${one(stats.crit)}%`, "CR"],
    ["Life steal", `${one(stats.lifesteal)}%`, "LS"], ["Omnivamp", `${one(stats.omnivamp)}%`, "OV"], ["Heal/shield power", `${one(stats.healAndShieldPower)}%`, "HS"],
    ["Health regen", one(stats.healthRegen), "HR"], ["Mana regen", `${one(stats.manaRegen)}`, "MR"], ["Gold per 10", one(stats.goldPer10), "G10"],
    ["Critical damage", `${one(stats.critDamage)}%`, "CD"], ["Tenacity", `${one(stats.tenacity)}%`, "TN"],
    ["Armor pen", armorPenLabel(stats), "AP"], ["Magic pen", magicPenLabel(stats), "MP"],
  ];
  return rows.map(([label, value, icon]) => `<div class="stat"><span><i class="stat-icon" aria-hidden="true">${escapeHtml(icon)}</i>${escapeHtml(label)}</span><strong>${value}</strong></div>`).join("");
}

function prototypeAbilityCards(champion) {
  return (champion?.abilities || []).map((ability) => {
    const input = abilityInput(ability.slot);
    const rank = ability.slot === "P" ? 1 : input.rank;
    const rankControl = ability.slot === "P" ? `<span class="ability-rank"><small>Level scales</small><output>Lv ${state.attacker.level}</output></span>` : `<span class="ability-rank"><small>Rank</small><button type="button" ${abilityCapabilityAttributes(ability.slot, "ability_ranks")} data-ability-rank="${ability.slot}" data-delta="-1">−</button><output>${rank}</output><button type="button" ${abilityCapabilityAttributes(ability.slot, "ability_ranks")} data-ability-rank="${ability.slot}" data-delta="1">+</button></span>`;
    const hitControl = ability.maxHits ? `<span class="ability-casts ability-hits"><small>Hits</small><button type="button" ${abilityCapabilityAttributes(ability.slot, "ability_hits")} data-ability-hits="${ability.slot}" data-delta="-1" ${input.hits <= 1 ? "disabled" : ""}>−</button><output>${input.hits}</output><button type="button" ${abilityCapabilityAttributes(ability.slot, "ability_hits")} data-ability-hits="${ability.slot}" data-delta="1" ${input.hits >= ability.maxHits ? "disabled" : ""}>+</button></span>` : "";
    const variantControl = ability.variants?.length > 1 ? `<span class="ability-variants"><small>Variant</small>${ability.variants.map((variant, index) => `<button type="button" ${abilityCapabilityAttributes(ability.slot, "ability_variants")} data-ability-variant="${ability.slot}" data-value="${index}" class="${input.variant === index ? "active" : ""}">${escapeHtml(variant.name)}</button>`).join("")}</span>` : "";
    const castAttributes = `${abilityCapabilityAttributes(ability.slot, "ability_casts")} data-ability-casts="${ability.slot}"`;
    return `<article class="ability-card"><img class="ability-icon-image" src="${abilityImage(ability)}" alt="" /><div><strong>${escapeHtml(ability.name)}</strong><small>${escapeHtml(ability.formulaSource === "Wiki-derived local cache" ? "Wiki formula" : "Reviewed formula")}</small></div>${rankControl}<span class="ability-casts"><small>${ability.slot === "P" ? "Procs" : "Casts"}</small><button type="button" ${castAttributes} data-delta="-1">−</button><output>${input.casts}</output><button type="button" ${castAttributes} data-delta="1">+</button></span>${hitControl}${variantControl}</article>`;
  }).join("");
}

function bisTrigger(path, compact = false) {
  const ready = bisReadyForPath(path);
  const kind = participantKindForPath(path);
  const reason = kind === "main"
    ? "Needs a champion and at least one enemy"
    : kind === "ally"
      ? "Needs a champion and role on this ally"
      : "Needs a champion and role on this enemy";
  const title = ready ? "Rank every legal item for this slot" : reason;
  return `<button class="bis-trigger${compact ? " compact" : ""}" type="button" data-bis-path="${path}" title="${escapeHtml(title)}" aria-label="Best item for this slot" ${ready ? "" : "disabled"}>BIS</button>`;
}

function prototypeItemSlot(id, path, side) {
  const item = getItem(id);
  const field = path.includes("questBoot") ? "boots" : "items";
  const kind = participantKindForPath(path);
  const emptyTitle = capabilityTitle(capabilityFor(kind, field));
  const controlAttrs = capabilityAttributes(kind, field);
  const title = item ? escapeHtml(itemStatsLine(item)) : escapeHtml(emptyTitle);
  return `<div class="slot-wrap"><button class="slot ${item ? "" : "empty-slot"}" type="button" ${controlAttrs} data-picker="item" data-path="${path}" aria-label="${item ? `Change ${escapeHtml(item.name)}` : "Add item"}"${title ? ` title="${title}"` : ""}>${item ? `<span class="item-badge">${side}</span><img src="${itemImage(id)}" alt="${escapeHtml(item.name)}" /><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(itemStatsLine(item))}</small>` : `<span>+</span><small>Add item</small>`}</button>${item && stackSpec(id) ? stackControl(path, id) : ""}${item ? itemOptionControls(path, id) : ""}${bisTrigger(path)}</div>`;
}

function prototypeRosterItemSlot(root, index, loadout, slot) {
  const isBoots = slot === "boots";
  const id = isBoots ? loadout.boots : loadout.items[slot];
  const path = isBoots ? `${root}.${index}.boots` : `${root}.${index}.items.${slot}`;
  const item = getItem(id);
  const emptyLabel = isBoots ? "Add boots" : "Add item";
  const slotLabel = isBoots ? `<span class="roster-slot-label">Boots</span>` : "";
  const kind = root === "allies" ? "ally" : "enemy";
  const field = isBoots ? "boots" : "items";
  return `<div class="roster-slot-wrap ${isBoots ? "roster-boots-wrap" : ""}">${slotLabel}<button class="roster-item-slot ${item ? "" : "is-empty"}" type="button" ${capabilityAttributes(kind, field)} data-picker="item" data-path="${path}" aria-label="${item ? `Change ${escapeHtml(item.name)}` : emptyLabel}" title="${item ? escapeHtml(itemStatsLine(item)) : emptyLabel}">${item ? `<img src="${itemImage(id)}" alt="${escapeHtml(item.name)}" />` : "+"}</button>${item && stackSpec(id) ? stackControl(path, id, true) : ""}${item && !isBoots ? itemOptionControls(path, id, true) : ""}${bisTrigger(path, true)}</div>`;
}

function prototypeBuildSlots(side) {
  const sideUpper = side.toUpperCase();
  const ids = buildArray(sideUpper);
  const count = ordinarySlotCount(sideUpper);
  const slots = [];
  // Bottom quest builds have six ordinary items plus a dedicated boots slot.
  // Keep the familiar six-column grid, but do not silently hide that seventh
  // slot from the user.
  const visibleCount = Math.max(6, count + (includeBootsForSide(sideUpper) ? 1 : 0));
  for (let index = 0; index < visibleCount; index += 1) {
    if (index < count) slots.push(prototypeItemSlot(ids[index], `attacker.build${sideUpper}.${index}`, sideUpper));
    else if (includeBootsForSide(sideUpper) && index === count) slots.push(prototypeItemSlot(state.attacker[`questBoot${sideUpper}`], questBootPath(sideUpper), sideUpper));
    else slots.push(`<span class="slot empty-slot slot-locked" aria-hidden="true"><span>·</span></span>`);
  }
  return `${slots.join("")}${keystoneSlot(sideUpper)}`;
}

function prototypeBuildScore(side) {
  const ids = side === "a" ? buildAIds() : buildBIds();
  if (!ids.some(Boolean)) return "—";
  if (!engine.responses) return "Unavailable";
  return objectiveFormat(objectiveMetric(engine.responses[side], 0));
}

function loadoutStatsPayload() {
  const build = engineFightPayload("A");
  return {
    champion: build.champion,
    level: build.level,
    items: build.items,
    boots: build.boots,
    item_options: build.item_options,
    role: build.role || "",
    role_quest_complete: Boolean(build.role_quest_complete),
  };
}

function loadoutStatsKey() {
  return JSON.stringify(loadoutStatsPayload());
}

function displayStatsFromBackend(stats) {
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
    attackSpeed: Number(stats.attack_speed || 0),
    moveSpeed: Number(stats.move_speed || 0),
    haste: Number(stats.ability_haste || 0),
    crit: Number(stats.critical_strike_chance || 0),
    lifesteal: Number(stats.lifesteal_percent || 0),
    omnivamp: Number(stats.omnivamp_percent || 0),
    healAndShieldPower: Number(stats.heal_and_shield_power_percent || 0),
    healthRegen: Number(stats.health_regen_per_five || 0),
    manaRegen: Number(stats.resource_regen_per_second || 0),
    goldPer10: Number(stats.gold_per_10 || 0),
    critDamage: Number(stats.critical_strike_damage_percent || 0),
    tenacity: Number(stats.tenacity_percent || 0),
    pen: Number(stats.magic_penetration_flat || 0),
    percentPen: Number(stats.magic_penetration_percent || 0),
    lethality: Number(stats.lethality || 0),
    percentArmorPen: Number(stats.armor_penetration_percent || 0),
  };
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

function mainParticipantBackendStats(result) {
  const main = (result?.combat?.participants || []).find((row) => row.participant_id === "main");
  return main?.stats || null;
}

function currentLoadoutStats() {
  // Cached stats survive an invalidation so a level step never blanks the
  // panel, but only for the champion they describe — showing one champion's
  // numbers under another's portrait would be worse than showing none.
  if (engine.loadoutStats?.stats && engine.loadoutStatsChampion === state.attacker.champion) {
    return displayStatsFromBackend(engine.loadoutStats.stats);
  }
  return displayStatsFromBackend(mainParticipantBackendStats(engine.responses?.a));
}

function scheduleLoadoutStats() {
  if (!state.attacker.champion || !document.getElementById("statsGrid")) return;
  const key = loadoutStatsKey();
  if (key === engine.loadoutStatsKey) return;
  if (engine.loadoutStatsTimer) clearTimeout(engine.loadoutStatsTimer);
  const champion = state.attacker.champion;
  // Rapid level steps queue several requests; only the newest may land, so a
  // slow earlier response cannot overwrite the level the user settled on.
  const requestId = (engine.loadoutStatsRequestId += 1);
  engine.loadoutStatsPending = true;
  engine.loadoutStatsTimer = setTimeout(() => {
    engine.loadoutStatsTimer = null;
    fetch("/api/loadout-stats", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(loadoutStatsPayload()),
    })
      .then((response) => response.json())
      .then((result) => {
        if (requestId !== engine.loadoutStatsRequestId) return;
        engine.loadoutStatsPending = false;
        if (!result || result.error || !result.stats) return;
        engine.loadoutStats = result;
        engine.loadoutStatsKey = key;
        engine.loadoutStatsChampion = champion;
        renderPrototypeChampion();
      })
      .catch(() => {
        if (requestId === engine.loadoutStatsRequestId) engine.loadoutStatsPending = false;
      });
  }, 60);
}

function renderPrototypeChampion() {
  const champion = getChampion(state.attacker.champion);
  const stats = champion ? currentLoadoutStats() : null;
  const portrait = $("championPicker");
  const portraitImage = $("championImage");
  $("championName").textContent = champion?.name || "Choose a champion";
  $("championTitle").textContent = champion?.title || "Start with the champion you want to compare.";
  portrait.classList.toggle("is-empty", !champion);
  portrait.setAttribute("aria-label", champion ? `Change ${champion.name}` : "Choose a champion");
  portraitImage.hidden = !champion;
  if (champion) {
    portraitImage.src = championImage(champion.name);
    portraitImage.alt = champion.name;
  } else {
    portraitImage.removeAttribute("src");
    portraitImage.alt = "";
  }
  document.querySelector(".champion-identity")?.classList.toggle("is-empty", !champion);
  document.querySelector(".champion-card")?.classList.toggle("is-empty", !champion);
  const identityControls = $("identityControls");
  if (identityControls) {
    identityControls.hidden = !champion;
    identityControls.setAttribute("aria-hidden", String(!champion));
  }
  const roleSelect = $("roleSelect");
  const roleCapability = capabilityFor("main", "role");
  if (roleSelect) {
    roleSelect.value = state.attacker.role || "";
    roleSelect.disabled = roleCapability.supported === false;
    roleSelect.title = capabilityTitle(roleCapability);
    roleSelect.dataset.capabilityField = "role";
  }
  const levelCapability = capabilityFor("main", "level");
  const levelInput = $("levelInput");
  levelInput.value = state.attacker.level;
  levelInput.max = attackerLevelCap();
  levelInput.disabled = levelCapability.supported === false;
  levelInput.title = capabilityTitle(levelCapability);
  levelInput.dataset.capabilityField = "level";
  document.querySelectorAll('button[data-level-path="attacker.level"]').forEach((button) => {
    button.disabled = levelCapability.supported === false;
    button.title = capabilityTitle(levelCapability);
    button.dataset.capabilityField = "level";
  });
  $("levelOutput").textContent = state.attacker.level;
  const questCapability = capabilityFor("main", "role_quest_complete");
  $("questToggle").textContent = state.attacker.roleQuestComplete ? "Quest on" : "Quest off";
  $("questToggle").setAttribute("aria-pressed", String(state.attacker.roleQuestComplete));
  $("questToggle").disabled = questCapability.supported === false || !state.attacker.role;
  $("questToggle").title = capabilityTitle(questCapability);
  $("questToggle").dataset.capabilityField = "role_quest_complete";
  const bootsCapability = capabilityFor("main", "include_boots");
  $("bootsToggle").textContent = includeBootsForSide("A") ? "Boots on" : "Boots off";
  $("bootsToggle").setAttribute("aria-pressed", String(includeBootsForSide("A")));
  $("bootsToggle").disabled = bootsCapability.supported === false;
  $("bootsToggle").title = capabilityTitle(bootsCapability);
  $("bootsToggle").dataset.capabilityField = "include_boots";
  $("stateReadout").textContent = `${state.ui.gameState === "live" ? "Snapshot lens" : "Theory state"} · ${state.fight.rotations} ${plural(state.fight.rotations, "rotation")}`;
  // The placeholder is for "no stats yet", not "stats are refreshing" (#151):
  // a recalculation keeps the previous values on screen and marks the grid
  // pending, so the portrait, identity and controls never flash empty.
  const statsGrid = $("statsGrid");
  statsGrid.hidden = !champion;
  statsGrid.setAttribute("aria-hidden", String(!champion));
  const refreshing = Boolean(stats) && engine.loadoutStatsPending;
  statsGrid.innerHTML = stats ? prototypeStats(stats) : `<div class="matrix-placeholder">Patch-pinned stats appear once the backend resolves this loadout.</div>`;
  statsGrid.classList.toggle("is-pending", refreshing);
  statsGrid.setAttribute("aria-busy", String(refreshing));
}

function renderPrototypeRoster(kind) {
  const root = kind === "targets" ? "targets" : "allies";
  const container = $(kind === "targets" ? "enemies" : "allies");
  const entries = state[root] || [];
  container.innerHTML = entries.map((loadout, index) => {
    const champion = getChampion(loadout.champion);
    const label = kind === "targets" ? "enemy" : "ally";
    const roleOptions = [["", "Choose role"], ["top", "Top"], ["jungle", "Jungle"], ["mid", "Mid"], ["bottom", "Bottom"], ["support", "Support"]];
    const itemSlots = Array.from({ length: rosterOrdinarySlotCount(loadout) }, (_, slot) => prototypeRosterItemSlot(root, index, loadout, slot)).join("");
    const bootsSlot = loadout.includeBoots !== false ? prototypeRosterItemSlot(root, index, loadout, "boots") : "";
    const abilityRanks = rosterAbilityRankControls(loadout, index, root);
    const championOptions = renderRosterChampionOptions(loadout, `${root}.${index}`, kind === "targets" ? "enemy" : "ally");
    const participantKind = kind === "targets" ? "enemy" : "ally";
    const roleCapability = capabilityAttributes(participantKind, "role");
    const levelCapability = capabilityAttributes(participantKind, "level");
    const questCapability = capabilityAttributes(participantKind, "role_quest_complete");
    const bootsCapability = capabilityAttributes(participantKind, "include_boots");
    const effectsCapability = capabilityAttributes("ally", "ally_effects_enabled");
    const bootsEnabled = loadout.includeBoots !== false;
    const roleQuestComplete = Boolean(loadout.roleQuestComplete);
    const roleQuestLabel = roleQuestComplete ? "Quest complete" : "Quest incomplete";
    const roleQuestButton = `<button class="roster-quest-toggle ${roleQuestComplete ? "active" : ""}" type="button" ${questCapability} data-roster-quest="${root}.${index}" aria-pressed="${roleQuestComplete}" aria-label="${roleQuestComplete ? "Mark" : "Mark"} ${label} role quest ${roleQuestComplete ? "incomplete" : "complete"}" ${loadout.role ? "" : "disabled"}>${roleQuestLabel}</button>`;
    const effectToggle = kind === "allies"
      ? `<button class="ally-toggle ${loadout.allyEffectsEnabled ? "active" : ""}" type="button" ${effectsCapability} data-ally-effects="${index}" aria-pressed="${Boolean(loadout.allyEffectsEnabled)}"><i></i><span>${loadout.allyEffectsEnabled ? "Apply modeled effects" : "Effects off"}</span></button>`
      : "";
    return `<article class="roster-card"><button class="roster-pick" type="button" ${capabilityAttributes(participantKind, "champion")} data-picker="champion" data-path="${root}.${index}.champion" aria-label="${champion ? `Change ${escapeHtml(champion.name)}` : `Choose ${label} champion`}">${champion ? `<img src="${championImage(champion.name)}" alt="${escapeHtml(champion.name)}" />` : "+"}</button><div class="roster-card-copy"><strong>${escapeHtml(champion?.name || `Choose ${label}`)}</strong><span>${escapeHtml(champion?.title || "Empty participant slot")}</span><div class="roster-meta">Lv ${loadout.level} · full participant</div></div><button class="remove-roster" type="button" data-remove-${kind === "targets" ? "target" : "ally"}="${index}" aria-label="Remove ${label}">×</button><div class="roster-card-editor"><div class="roster-controls-row"><label class="roster-role-control"><span>Role</span><select ${roleCapability} data-roster-role="${root}.${index}.role" aria-label="${label} role">${roleOptions.map(([value, name]) => `<option value="${value}" ${loadout.role === value ? "selected" : ""}>${name}</option>`).join("")}</select></label><div class="roster-level-control"><span>Level</span><button type="button" ${levelCapability} data-level-path="${root}.${index}.level" data-level-delta="-1" aria-label="Decrease ${label} level">−</button><output>Lv ${loadout.level}</output><button type="button" ${levelCapability} data-level-path="${root}.${index}.level" data-level-delta="1" aria-label="Increase ${label} level">+</button></div>${roleQuestButton}<button class="roster-boots-toggle ${bootsEnabled ? "active" : ""}" type="button" ${bootsCapability} data-include-roster-boots="${root}.${index}" aria-pressed="${bootsEnabled}">${bootsEnabled ? "Boots on" : "Boots off"}</button></div><div class="roster-item-strip">${itemSlots}${bootsSlot}</div>${abilityRanks}${championOptions}${effectToggle}</div></article>`;
  }).join("") || `<p class="roster-empty">Add ${kind === "targets" ? "a target" : "an ally"} to the coupled timeline.</p>`;
  $(kind === "targets" ? "enemyCount" : "allyCount").textContent = entries.length;
}

function renderPrototypeBuilder() {
  const champion = getChampion(state.attacker.champion);
  renderPrototypeChampion();
  $("abilityRow").innerHTML = champion ? prototypeAbilityCards(champion) : `<p class="roster-empty">Choose a champion to load its sourced ability package.</p>`;
  $("championOptionsRow").innerHTML = champion ? renderChampionOptions() : "";
  $("slotsA").innerHTML = prototypeBuildSlots("a");
  $("slotsB").innerHTML = prototypeBuildSlots("b");
  $("buildAScore").textContent = prototypeBuildScore("a");
  $("buildBScore").textContent = state.attacker.comparisonEnabled ? prototypeBuildScore("b") : "—";
  const aValue = state.attacker.comparisonEnabled ? objectiveMetric(engine.responses?.a, null) : null;
  const bValue = state.attacker.comparisonEnabled ? objectiveMetric(engine.responses?.b, null) : null;
  const outcome = objectiveWinner(aValue, bValue);
  $("winnerCaption").textContent = !state.attacker.comparisonEnabled ? "comparison off" : outcome.winner === "B" ? "winner · selected objective" : outcome.winner === "A" ? "lead · selected objective" : outcome.winner === "tie" ? "tie · selected objective" : "awaiting reviewed output";
  document.querySelector(".build-a")?.classList.toggle("is-winner", outcome.winner === "A");
  document.querySelector(".build-b")?.classList.toggle("is-winner", outcome.winner === "B");
  renderPrototypeRoster("targets");
  renderPrototypeRoster("allies");
  $("rotationOutput").textContent = state.fight.rotations;
  $("rotationRange").value = state.fight.rotations;
  const rotationCapability = scenarioCapabilityFor("rotations");
  $("rotationRange").disabled = rotationCapability.supported === false;
  $("rotationRange").title = capabilityTitle(rotationCapability);
  $("rotationRange").dataset.capabilityField = "rotations";
  const durationRange = $("durationRange");
  const durationOutput = $("durationOutput");
  const durationCapability = scenarioCapabilityFor("window");
  if (durationRange) {
    const [durationMin, durationMax] = engine.fightLimits.fight_duration || [1, 30];
    durationRange.min = durationMin;
    durationRange.max = durationMax;
    durationRange.value = state.fight.duration;
    durationRange.disabled = durationCapability.supported === false;
    durationRange.title = capabilityTitle(durationCapability);
    durationRange.dataset.capabilityField = "window";
  }
  if (durationOutput) durationOutput.textContent = `${one(state.fight.duration)}s`;
  const policy = engine.responses?.a?.auto_attack_policy;
  const schedule = engine.responses?.a?.auto_attack_schedule;
  const calculated = state.fight.aaUptimeMode === "calculated";
  $("uptimeOutput").textContent = calculated
    ? (policy?.status === "calculated"
      ? `${Math.round(Number(policy.uptime || 0) * 100)}% calculated${schedule?.expected_autos_per_rotation != null ? ` · ${one(Number(schedule.expected_autos_per_rotation))} autos/rotation` : ""}`
      : "CALCULATED")
    : `${Math.round(state.fight.aaUptime * 100)}% explicit`;
  $("uptimeRange").value = Math.round(state.fight.aaUptime * 100);
  const uptimeCapability = scenarioCapabilityFor("auto_attack_uptime");
  $("uptimeRange").disabled = calculated || uptimeCapability.supported === false;
  $("uptimeRange").title = calculated ? "Calculated uptime is owned by the backend auto-attack policy." : capabilityTitle(uptimeCapability);
  $("uptimeRange").dataset.capabilityField = "auto_attack_uptime";
  const modeButton = $("uptimeModeToggle");
  if (modeButton) {
    modeButton.textContent = calculated ? "Use explicit" : "Use calculated";
    modeButton.setAttribute("aria-pressed", String(calculated));
    const modeCapability = scenarioCapabilityFor("auto_attack_uptime_mode");
    modeButton.disabled = modeCapability.supported === false;
    modeButton.title = capabilityTitle(modeCapability);
    modeButton.dataset.capabilityField = "auto_attack_uptime_mode";
  }
}

/** Number of ordered events the timeline draws before it says it stopped. */
const TIMELINE_EVENT_LIMIT = 60;

/**
 * Draw the ordered event ledger as one lane per event.
 *
 * Issue #155: events used to be 17px markers absolutely positioned on a
 * single shared line, labelled with the first three characters of the source
 * — dense or simultaneous events overlapped and read as fragments. Giving
 * each event its own full-width row makes collision structurally impossible
 * and leaves room for the untruncated source, the actor pair and the value.
 * The proportional tick keeps the at-a-glance sense of when it landed, and
 * data-event-index ties each lane to the matching ledger-table line.
 */
function renderEventTimeline(combatEvents, duration, eventLabel) {
  const timed = combatEvents
    .map((event, index) => ({ event, index, time: eventTime(event) }))
    .filter(({ time }) => time !== null);
  if (!timed.length) return `<p class="roster-empty">No participant event ledger returned.</p>`;
  const shown = timed.slice(0, TIMELINE_EVENT_LIMIT);
  const lanes = shown.map(({ event, index, time }) => {
    const position = Math.min(100, Math.max(0, time / duration * 100));
    const precision = event.event_precision && event.event_precision !== "exact" ? ` · ${event.event_precision}` : "";
    const damage = Number(event.damage || 0);
    const value = damage > 0 ? `${fmt(damage)} damage` : event.skipped_reason || "no damage";
    return `<li class="timeline-event" data-event-index="${index}">
      <span class="timeline-time">${one(time)}s</span>
      <span class="timeline-what"><b>${escapeHtml(eventLabel(event.attacker))}</b> → ${escapeHtml(eventLabel(event.target))} · ${escapeHtml(event.source || "event")}${escapeHtml(precision)}</span>
      <b class="timeline-value">${escapeHtml(value)}</b>
      <span class="timeline-tick" style="--at:${position}%" aria-hidden="true"></span>
    </li>`;
  }).join("");
  const note = shown.length === combatEvents.length
    ? `${combatEvents.length} ordered ${plural(combatEvents.length, "event")}, oldest first`
    : `First ${shown.length} of ${combatEvents.length} ordered events`;
  return `<div class="timeline-axis"><span>0:00</span><span>${one(duration / 2)}s</span><span>${one(duration)}s</span></div>
    <ol class="timeline-events" aria-label="Ordered combat events">${lanes}</ol>
    <small class="timeline-note">${escapeHtml(note)}</small>`;
}

function prototypeMetricRow(label, a, b, lower = false, unit = "value", aAlive = "", bAlive = "") {
  const winner = objectiveWinner(a, b).winner;
  // Kill-time rows carry their own formatting: a live build shows the enemy
  // HP it failed to remove (or "—" when the result is missing), a defeated
  // build shows the real timeline time-to-death (never "0 s").
  const format = (value, alive) => value == null
    ? (alive || "—")
    : lower
      ? (killTimeLabel(value) || alive || "—")
      : `${fmt(value)} ${unit}`;
  return `<div class="metric-row"><span>${label}</span><strong class="metric-a">${format(a, aAlive)}</strong><strong class="metric-b">${format(b, bAlive)}</strong><b>${winner === "A" || winner === "B" ? winner : "—"}</b></div>`;
}

function prototypeParticipants(result) {
  return result?.combat?.participants || [];
}

function enemyParticipants(result) {
  return (result?.combat?.participants || []).filter((row) => row.team === "enemy" || String(row.participant_id || "").startsWith("enemy:"));
}

function enemyEffectiveHealth(result) {
  const enemies = enemyParticipants(result);
  if (enemies.length) {
    return enemies.reduce((sum, row) => sum + Number(row.survival?.effective_health || 0), 0);
  }
  // No coupled ledger (generic-path results): fall back to the serialized
  // target receipt surfaced by /api/calculate.
  return Number(result?.target_effective_health ?? result?.target_effective_max_health ?? 0);
}

function enemyHealthRemaining(result) {
  const enemies = enemyParticipants(result);
  if (!enemies.length) return "";
  const ending = enemies.reduce((sum, row) => sum + Math.max(0, Number(row.survival?.ending_health ?? 0)), 0);
  if (ending <= 0) return "";
  const max = enemies.reduce((sum, row) => sum + Math.max(0, Number(row.survival?.max_health ?? row.survival?.effective_health ?? 0)), 0);
  const pct = max > 0 ? Math.round((ending / max) * 100) : null;
  return `alive · ${fmt(ending)} HP${pct != null ? ` (${pct}%)` : ""}`;
}

function enemyOverkill(result, totalDamage) {
  const enemies = enemyParticipants(result);
  const exact = enemies.reduce((sum, row) => sum + Math.max(0, Number(row.survival?.overkill || 0)), 0);
  const formula = Math.max(0, Number(totalDamage || 0) - enemyEffectiveHealth(result));
  return Math.max(exact, formula);
}

function renderPrototypeResult(aResult = null, bResult = null) {
  const aTotal = aResult ? Number(aResult.combat?.breakdown?.find((row) => row.participant_id === "main")?.total_damage ?? aResult.total_damage ?? 0) : null;
  const bTotal = bResult ? Number(bResult.combat?.breakdown?.find((row) => row.participant_id === "main")?.total_damage ?? bResult.total_damage ?? 0) : null;
  const aValues = aResult ? exactObjectiveMetric(aResult, aTotal) : { overall: null, damage: null, kill: null, survival: null, utility: null };
  const bValues = bResult ? exactObjectiveMetric(bResult, bTotal) : { overall: null, damage: null, kill: null, survival: null, utility: null };
  const aValue = aValues[state.ui.objective];
  const bValue = bValues[state.ui.objective];
  const comparing = Boolean(bResult);
  const selectedAvailable = aResult && aValue != null;
  const outcome = comparing
    ? objectiveWinner(aValue, bValue)
    : selectedAvailable
      ? { winner: "A", delta: null }
      : { winner: null, delta: null };
  const objective = OBJECTIVES[state.ui.objective];
  const autoPolicy = aResult?.auto_attack_policy || {};
  if (state.fight.aaUptimeMode === "calculated" && autoPolicy.status === "calculated") {
    state.fight.aaUptime = Number(autoPolicy.uptime || 0);
  }
  const coverage = aResult?.timeline_coverage || {};
  $("resultStatus").textContent = !aResult
    ? "waiting"
    : coverage.complete === false || autoPolicy.status === "unknown" ? "qualified" : "reviewed";
  $("resultObjective").textContent = objective.label;
  $("winnerLetter").textContent = outcome.winner === "A" ? "A" : outcome.winner === "B" ? "B" : "—";
  $("winnerLabel").textContent = outcome.winner === "tie" ? "tie" : comparing && outcome.winner ? "wins" : selectedAvailable ? "selected" : aResult ? "unavailable" : "waiting";
  $("resultDelta").textContent = outcome.delta == null ? "—" : state.ui.objective === "kill" ? `+${one(outcome.delta)}s` : `+${fmt(outcome.delta)}`;
  $("resultSummary").textContent = !aResult
    ? "Choose a complete scenario to receive a reviewed comparison."
    : !comparing
      ? selectedAvailable
        ? "Build A is the selected build for this scenario. Enable Build B to compare a second build."
        : `${objective.label} is unavailable until the reviewed event ledger supplies that outcome.`
      : outcome.winner
        ? `${outcome.winner === "A" ? "Build A" : outcome.winner === "B" ? "Build B" : "Neither build"} carries the strongest ${objective.label.toLowerCase()} package against this roster.`
        : "The selected objective is unavailable for this comparison.";
  $("scoreA").textContent = objectiveFormat(aValue);
  $("scoreB").textContent = objectiveFormat(bValue);
  const aAlive = enemyHealthRemaining(aResult);
  const bAlive = bResult ? enemyHealthRemaining(bResult) : "";
  $("metricList").innerHTML = [
    prototypeMetricRow("Overall", aValues.overall, bValues.overall, false, "TDD"),
    prototypeMetricRow("Kill time", aValues.kill, bValues.kill, true, "s", aAlive, bAlive),
    prototypeMetricRow("Survival", aValues.survival, bValues.survival, false, "eHP"),
    prototypeMetricRow("Damage", aValues.damage, bValues.damage, false, "TDD"),
    prototypeMetricRow("Utility", aValues.utility, bValues.utility, false, "value"),
  ].join("");
  const participants = prototypeParticipants(aResult);
  $("healthRows").innerHTML = participants.map((person) => {
    const survival = person.survival || {};
    const max = Number(survival.max_health || survival.effective_health || person.stats?.health || person.health || 0);
    const explicitHealth = survival.health_remaining ?? survival.current_health;
    const incoming = Number(survival.health_damage ?? survival.incoming_damage ?? 0);
    const health = explicitHealth != null ? Math.max(0, Number(explicitHealth)) : Math.max(0, max - incoming);
    const pct = max > 0 ? Math.max(0, Math.min(100, health / max * 100)) : 0;
    const status = survival.survived_window === false ? "defeated" : max > 0 ? `${Math.round(pct)}%` : incoming > 0 ? `-${fmt(incoming)} dmg` : "alive";
    return `<div class="health-row"><div class="health-person"><img src="${championImage(person.champion)}" alt="" /><span><strong>${escapeHtml(person.champion || person.participant_id || "Participant")}</strong><small>${escapeHtml(person.team || "participant")}</small></span></div><div class="health-track"><span style="width:${pct}%"></span></div><b>${status}</b></div>`;
  }).join("") || `<p class="roster-empty">Participant health appears after the reviewed engine returns.</p>`;
  const participantLabels = new Map((aResult?.combat?.participants || []).map((person) => [person.participant_id, person.champion || person.participant_id]));
  const combatEvents = Array.isArray(aResult?.combat?.events) ? aResult.combat.events : [];
  const healingEvents = healingEventsForResult(aResult);
  const supportEvents = Array.isArray(aResult?.combat?.support_events) ? aResult.combat.support_events : [];
  const duration = Math.max(1, Number(aResult?.combat?.duration || state.fight.duration));
  const eventLabel = (participantId) => participantLabels.get(participantId) || participantId || "Participant";
  $("timeline").innerHTML = renderEventTimeline(combatEvents, duration, eventLabel);
  const healingRows = healingEvents.slice(0, 12).map((event) => {
    const time = eventTime(event);
    const timeLabel = time === null ? "time withheld" : `${one(time)}s`;
    const temporaryHealth = Number(event.temporary_health || 0);
    const value = `${fmt(Number(event.applied_amount ?? event.amount ?? 0))} healing${temporaryHealth ? ` + ${fmt(temporaryHealth)} temporary health` : ""}`;
    return `<div class="ledger-line"><span>${escapeHtml(timeLabel)} · ${escapeHtml(eventLabel(event.attacker))} · ${escapeHtml(event.source || "healing")}</span><strong>${value}</strong></div>`;
  });
  const supportRows = supportEvents.slice(0, 12).map((event) => {
    const time = eventTime(event);
    const timeLabel = time === null ? "time withheld" : `${one(time)}s`;
    const recipient = eventLabel(event.target || event.recipient);
    const policy = event.target_policy || event.target_scope || "explicit recipient";
    const details = [
      Number.isFinite(Number(event.bonus_attack_speed_percent)) ? `${fmt(event.bonus_attack_speed_percent)}% AS` : "",
      Number.isFinite(Number(event.on_hit_magic_damage)) ? `${fmt(event.on_hit_magic_damage)} on-hit magic` : "",
      Number.isFinite(Number(event.ability_power)) && Number(event.ability_power) ? `+${fmt(event.ability_power)} AP` : "",
      Number.isFinite(Number(event.ability_haste)) && Number(event.ability_haste) ? `+${fmt(event.ability_haste)} AH` : "",
      Number.isFinite(Number(event.bonus_move_speed_percent)) ? `${fmt(event.bonus_move_speed_percent)}% MS` : "",
      Number.isFinite(Number(event.chain_fraction)) ? `${Math.round(Number(event.chain_fraction) * 100)}% chain` : "",
      Number.isFinite(Number(event.armor_reduction_percent)) ? `${Math.round(Number(event.armor_reduction_percent) * 100)}% armor shred` : "",
      Number.isFinite(Number(event.mr_reduction_percent)) ? `${Math.round(Number(event.mr_reduction_percent) * 100)}% MR shred` : "",
      Number.isFinite(Number(event.multiplier)) && Number(event.multiplier) !== 1 ? `${Math.round((Number(event.multiplier) - 1) * 100)}% damage` : "",
      Number.isFinite(Number(event.gold_amount)) && Number(event.gold_amount) ? `${fmt(event.gold_amount)} gold` : "",
      Number.isFinite(Number(event.ward_uses)) && Number(event.ward_uses) ? `${fmt(event.ward_uses)} wards` : "",
      Number.isFinite(Number(event.bonus_mana_total)) && Number(event.bonus_mana_total) ? `${fmt(event.bonus_mana_total)} bonus mana` : "",
      Number.isFinite(Number(event.true_damage_on_ward_hit)) ? `${fmt(event.true_damage_on_ward_hit)} true dmg vs wards` : "",
      event.ward_only ? "Blackout" : "",
      event.cleanse ? "cleanse" : "",
    ].filter(Boolean).join(" · ");
    return `<div class="ledger-line"><span>${escapeHtml(timeLabel)} · ${escapeHtml(eventLabel(event.attacker))} → ${escapeHtml(recipient)} · ${escapeHtml(event.source || "support")}${details ? ` · ${escapeHtml(details)}` : ""}</span><strong>${fmt(Number(event.applied_amount ?? event.amount ?? 0))} ${escapeHtml(event.kind || "support")} · ${escapeHtml(policy)}</strong></div>`;
  });
  const overflow = healingEvents.length > 12 || supportEvents.length > 12
    ? `<div class="ledger-line"><span>Additional receipts</span><strong>${healingEvents.length > 12 ? healingEvents.length - 12 : 0} healing · ${supportEvents.length > 12 ? supportEvents.length - 12 : 0} support</strong></div>`
    : "";
  const enemyEhp = enemyEffectiveHealth(aResult);
  const overkill = aTotal == null ? 0 : enemyOverkill(aResult, aTotal);
  $("ledgerTable").innerHTML = `<div class="ledger-line"><span>Selected objective</span><strong>${escapeHtml(objective.label)}</strong></div><div class="ledger-line"><span>Event order</span><strong>${escapeHtml(coverage.certification || "pending")}</strong></div><div class="ledger-line"><span>Main output</span><strong>${aTotal == null ? "—" : `${fmt(aTotal)} TDD${overkill > 0 ? ` · ${fmt(overkill)} overkill` : ""}`}</strong></div><div class="ledger-line"><span>Enemy effective HP</span><strong>${enemyEhp > 0 ? fmt(enemyEhp) : "—"}</strong></div>${healingRows.join("")}${supportRows.join("")}${overflow}`;
  // P4: the per-ability damage table carries a certainty chip next to every
  // sourced number. It re-renders on every result so chips track the loaded
  // /api/certainty contract (or its placeholder fallback).
  renderExactBreakdown(aResult, bResult);
  // F0: the starting-defense and shield/healing receipts ride the same
  // result pass, now in the visible result column.
  renderDefenseReceipts(aResult, bResult);
}

function render() {
  renderPrototypeBuilder();
  renderPrototypeResult(engine.responses?.a || null, engine.responses?.b || null);
  renderScenarioRail();
  $("scenarioSentence").innerHTML = scenarioSentence();
  applyPrerequisiteGates();
  scheduleEngineCalculation();
  scheduleLoadoutStats();
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
    const targetItem = pickerContext.type === "item" && pickerContext.path.startsWith("targets.");
    const itemCoverage = pickerContext.type === "item"
      ? (targetItem ? entry.targetModelCoverage : entry.modelCoverage)
      : null;
    const calculationEligible = itemCoverage?.calculation_eligible
      ?? (itemCoverage?.optimizer_eligible ?? false);
    const roleQuestReason = pickerContext.type === "item"
      ? supportQuestItemBlockReason(entry, pickerContext.path)
      : "";
    const itemBlocked = Boolean(
      (itemCoverage && calculationEligible === false) || roleQuestReason
    );
    const detail = pickerContext.type === "champion"
      ? `${entry.tags.join(" · ")} · ${entry.resource}`
      : isKeystone
        ? `${entry.path} keystone${entry.implemented ? "" : " · not modeled yet"}`
        : `${itemStatsLine(entry)}${itemCoverage?.status ? ` · ${itemCoverage.status.replaceAll("_", " ")}` : ""}${roleQuestReason ? ` · ${roleQuestReason}` : ""}`;
    const button = document.createElement("button");
    const image = document.createElement("img");
    button.type = "button";
    button.className = `picker-option ${String(selected) === String(value) ? "selected" : ""} ${(isKeystone && !entry.implemented) || itemBlocked ? "locked" : ""}`;
    button.dataset.pickerValue = String(value);
    if ((isKeystone && !entry.implemented) || itemBlocked) {
      button.disabled = true;
      button.title = itemBlocked
        ? (roleQuestReason || itemCoverage?.reason || "This item is withheld until its selected model is supported.")
        : "This keystone is not modeled yet; its numbers would be estimates.";
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
    if (!backendItemReady(entry)) return false;
    const dedicatedBoot = ALL_ROLE_BOOTS.has(Number(entry.id));
    if (pickerContext.path.includes("questBoot")) {
      return questBootIds().includes(Number(entry.id));
    }
    if (pickerContext.path.endsWith(".boots")) {
      return dedicatedBoot;
    }
    if (pickerContext.path.includes(".items.")) return !dedicatedBoot;
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


function bisChampionProfile(combatant) {
  const champion = getChampion(combatant?.champion);
  const profile = BIS_PROFILES[combatant?.champion] || {};
  const roles = [...new Set([...(profile.roles || []), ...(champion?.tags || [])].map((role) => String(role).toUpperCase()))];
  return { ...profile, roles, champion };
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

function bisBackendPayload(path, objective = state.ui.objective) {
  const parts = String(path).split(".");
  const payload = { ...engineFightPayload("A") };
  payload.objective = OBJECTIVES[objective] ? objective : "overall";
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
  const selectedObjective = bisContext?.path === path && OBJECTIVES[bisContext.objective]
    ? bisContext.objective
    : (OBJECTIVES[state.ui.objective] ? state.ui.objective : "overall");
  const payload = bisBackendPayload(path, selectedObjective);
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
  bisContext = { path, objective: selectedObjective };
  const filter = $("bisObjectiveFilter");
  if (filter) {
    filter.innerHTML = Object.entries(OBJECTIVES).map(([key, definition]) => `<button type="button" data-bis-objective="${key}" class="${key === selectedObjective ? "active" : ""}" aria-pressed="${key === selectedObjective}">${escapeHtml(definition.label)}</button>`).join("");
  }
  $("bis").showModal();
  try {
    const response = await fetch("/api/bis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || result.error) throw new Error(result.error || "BIS service unavailable");
    const certifiedRows = result.candidates || [];
    const partialRows = result.partial_candidates || [];
    // Partial event order is an audit receipt, never a ranked preview.  The
    // backend remains the authority for ordering complete candidates.
    const rows = certifiedRows;
    const displayRows = rows.slice(0, 24);
    const displayPartialRows = partialRows.slice(0, 24);
    const coverage = result.coverage?.complete
      ? "complete sourced coverage"
      : certifiedRows.length
        ? "certified subset · search not exhaustive"
        : "no certified candidate · search not exhaustive";
    const candidateScope = result.candidate_scope?.startsWith("role-tagged:")
      ? `${result.candidate_scope.slice("role-tagged:".length)} role-compatible`
      : "all supported";
    const displayNote = rows.length > displayRows.length ? ` · showing top ${displayRows.length}` : "";
    const partialDisplayNote = partialRows.length > displayPartialRows.length
      ? ` · showing ${displayPartialRows.length} partial receipts`
      : "";
    const withheldRows = Array.isArray(result.withheld_candidates) ? result.withheld_candidates : [];
    const withheldCount = Number(result.withheld_candidate_count || withheldRows.length || 0);
    const withheldNames = withheldRows.slice(0, 3).map((entry) => entry.name).filter(Boolean).join(", ");
    const withheldNote = withheldCount
      ? ` · ${withheldCount} withheld before timeline${withheldNames ? ` (${withheldNames}${withheldCount > 3 ? ", …" : ""})` : ""}`
      : "";
    const responseObjective = result.objective || {};
    const objectiveLabel = responseObjective.label || OBJECTIVES[selectedObjective].label;
    const partialNote = partialRows.length
      ? ` · ${partialRows.length} partial receipts withheld${partialDisplayNote}`
      : "";
    $("bisSummary").textContent = `${subject.champion} · ${objectiveLabel} · ${certifiedRows.length} certified of ${result.candidate_count || rows.length} ${candidateScope} candidates · ${coverage}${displayNote}${withheldNote}${partialNote}`;
    const evaluatedCards = displayRows.map((entry, index) => {
      const item = findItemByBackendName(entry.name);
      const defensiveNote = entry.defensive_effect_receipt?.status === "certified"
        ? ` · ${entry.defensive_effect_receipt.note || "certified defensive receipt"}`
        : "";
      const detail = `${item ? itemStatsLine(item) : "Sourced item stats"} · ${bisComponentLine(entry.components)}${defensiveNote}`;
      return `<article class="bis-row"><span class="bis-rank">${String(index + 1).padStart(2, "0")}</span><img src="${item ? itemImage(item.id) : escapeHtml(entry.icon || "")}" alt="" /><div><strong>${escapeHtml(entry.name)}</strong><small>${escapeHtml(detail)}</small></div><p><strong>${fmt(entry.score)}</strong><span>${escapeHtml(bisMetricLabel(entry.metric))}</span></p><button type="button" data-bis-value="${item ? item.id : ""}" ${item ? "" : "disabled"}>Use</button></article>`;
    }).join("");
    const partialCards = displayPartialRows.map((entry) => {
      const item = findItemByBackendName(entry.name);
      const timeline = entry.timeline_coverage || {};
      const coarseSources = Array.isArray(timeline.coarse_sources) && timeline.coarse_sources.length
        ? ` · coarse: ${timeline.coarse_sources.join(", ")}`
        : "";
      const detail = timeline.note || "The candidate has incomplete event-order coverage.";
      return `<article class="bis-row partial"><span class="bis-rank">—</span><img src="${item ? itemImage(item.id) : escapeHtml(entry.icon || "")}" alt="" /><div><strong>${escapeHtml(entry.name || "Candidate")}</strong><small>Withheld · partial event order · ${escapeHtml(detail)}${escapeHtml(coarseSources)}</small></div><p><strong>—</strong><span>Not rankable</span></p><button type="button" disabled aria-label="${escapeHtml(entry.name || "Candidate")} partial event order">Withheld</button></article>`;
    }).join("");
    const withheldCards = withheldRows.slice(0, 24).map((entry) => {
      const item = findItemByBackendName(entry.name);
      const reason = String(entry.reason || "candidate not evaluated").replaceAll("_", " ");
      return `<article class="bis-row partial withheld"><span class="bis-rank">—</span><img src="${item ? itemImage(item.id) : escapeHtml(entry.icon || "")}" alt="" /><div><strong>${escapeHtml(entry.name || "Candidate")}</strong><small>Withheld · ${escapeHtml(reason)}${entry.detail ? ` · ${escapeHtml(entry.detail)}` : ""}</small></div><p><strong>—</strong><span>No score</span></p><button type="button" disabled aria-label="${escapeHtml(entry.name || "Candidate")} withheld">Withheld</button></article>`;
    }).join("");
    $("bisList").innerHTML = evaluatedCards + partialCards + withheldCards || `<p class="picker-empty">${escapeHtml(result.coverage?.note || "No legal candidate has complete sourced mechanics for this timeline.")}${withheldCount ? ` ${escapeHtml(withheldCount === 1 ? "One candidate was withheld before timeline evaluation." : `${withheldCount} candidates were withheld before timeline evaluation.`)}` : ""}</p>`;
  } catch (error) {
    $("bisSummary").textContent = "BIS unavailable";
    $("bisList").innerHTML = `<p class="picker-empty">${escapeHtml(error.message)}</p>`;
  }
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
    const boot = bootResult.candidates?.[0] && findItemByBackendName(bootResult.candidates[0].name);
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
    const item = candidate && findItemByBackendName(candidate.name);
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
  state.optimizer.rosterErrors = {};
  render();
  const started = performance.now();
  let tested = 0;
  let activePath = null;
  try {
    const changed = [];
    for (const path of paths) {
      activePath = path;
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
    if (activePath) state.optimizer.rosterErrors[activePath] = error.message;
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
    if (!response.ok || result.error) {
      const message = result.error_code === "no_complete_event_order"
        ? `${result.champion || state.attacker.champion}: exact event-order coverage unavailable. ${result.error || "Optimizer withheld."}`
        : (result.error || "Optimizer unavailable");
      throw new Error(message);
    }
    if (!result.is_certified_best) {
      // A partial candidate timeline is a receipt, not a build recommendation.
      // Keep the user's current build intact until every active source in the
      // search is event-order certified.
      const withheldRows = Array.isArray(result.timeline_withheld_candidates) ? result.timeline_withheld_candidates : [];
      const withheldCount = Number(result.timeline_withheld_candidate_count || withheldRows.length || 0);
      const firstWithheld = withheldRows[0];
      const withheldDetail = withheldCount
        ? ` ${withheldCount} candidate${withheldCount === 1 ? "" : "s"} withheld${firstWithheld?.reason ? ` (${firstWithheld.reason.replaceAll("_", " ")})` : ""}.`
        : "";
      state.optimizer.summary = {
        tested: Number(result.evaluations || 0),
        elapsedMs: Number(result.optimization_time_ms || 0),
        withheld: true,
        label: `BIS withheld — no build applied. ${result.search_timeline_coverage?.note || "Event-order coverage is incomplete."}${withheldDetail}`,
      };
      return result;
    }
    const ids = (result.items || []).map((name) => findItemByBackendName(name)?.id || 0);
    state.attacker.buildA = [...ids, ...Array(Math.max(0, 6 - ids.length)).fill(0)].slice(0, 6);
    state.attacker.buildAStacks = [0, 0, 0, 0, 0, 0];
    state.attacker.buildAItemOptions = [{}, {}, {}, {}, {}, {}];
    state.attacker.questBootA = findItemByBackendName(result.boots)?.id || 0;
    state.optimizer.summary = {
      tested: Number(result.evaluations || 0),
      elapsedMs: Number(result.optimization_time_ms || 0),
      label: result.selection_certification === "event_ordered_local_search"
        ? "Event-ordered local-search build applied; coarse candidates were excluded and TTD stops at death."
        : "Coupled event-ordered BIS: TTD is counted only while the champion is alive.",
    };
    return result;
}

async function startPurchaseOptimize() {
  if (state.optimizer.running || !Number.isInteger(state.optimizer.availableGold) || state.optimizer.availableGold < 1) return;
  state.optimizer.running = true;
  state.optimizer.scope = "purchase";
  state.optimizer.summary = null;
  render();
  const started = performance.now();
  try {
    const payload = engineFightPayload("A");
    const ownedIds = state.attacker.buildA.filter(Boolean);
    const ownedNames = ownedIds.map((id) => itemName(id));
    payload.optimization_scope = "purchase";
    payload.available_gold = state.optimizer.availableGold;
    payload.max_purchase_items = 2;
    payload.allow_sell = Boolean(document.getElementById("economicsSell")?.checked);
    payload.max_sell_items = 1;
    payload.combine_policy = "shop_combine";
    payload.objective = "total_damage";
    payload.locked_items = ownedNames;
    payload.locked_boots = state.attacker.questBootA ? itemName(state.attacker.questBootA) : "";
    const response = await fetch("/api/optimize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || result.error) throw new Error(result.error || "Best-buy search unavailable");
    if (result.recommendation_type === "no_affordable_purchase") {
      state.optimizer.summary = {
        tested: 0,
        elapsedMs: performance.now() - started,
        label: `No legal modeled purchase fits ${fmt(state.optimizer.availableGold)} gold.`,
      };
      return;
    }
    if (!result.is_certified_best || !result.winner_event_order_certified) {
      state.optimizer.summary = {
        tested: Number(result.evaluations || 0),
        elapsedMs: Number(result.optimization_time_ms || performance.now() - started),
        withheld: true,
        label: "Best buy withheld because the exhaustive candidate set is not fully event-order certified.",
      };
      return;
    }
    const previous = new Map();
    state.attacker.buildA.forEach((id, index) => {
      if (!id) return;
      previous.set(itemName(id), {
        stack: state.attacker.buildAStacks[index],
        options: state.attacker.buildAItemOptions[index],
      });
    });
    const soldNames = new Set(result.sell_items || []);
    const resultIds = (result.items || []).map((name) => findItemByBackendName(name)?.id || 0).filter(Boolean);
    state.attacker.buildA = [...resultIds, ...Array(Math.max(0, 6 - resultIds.length)).fill(0)].slice(0, 6);
    state.attacker.buildAStacks = state.attacker.buildA.map((id) => previous.get(itemName(id))?.stack || 0);
    state.attacker.buildAItemOptions = state.attacker.buildA.map((id) => previous.get(itemName(id))?.options || {});
    state.attacker.questBootA = findItemByBackendName(result.boots)?.id || 0;
    const purchase = (result.purchase_items || []).join(" + ");
    const sold = soldNames.size ? ` · sell ${[...soldNames].join(" + ")}` : "";
    const pivot = result.recommendation_type === "sell_pivot" ? " · pivot" : "";
    state.optimizer.summary = {
      tested: Number(result.evaluations || result.candidate_count || 0),
      elapsedMs: Number(result.optimization_time_ms || performance.now() - started),
      label: `Buy ${purchase}${sold}${pivot} · ${fmt(result.spent_gold)} spent${result.sell_refund ? ` · ${fmt(result.sell_refund)} from sells` : ""} · ${fmt(result.remaining_gold)} remaining. ${result.exhaustive_within_scope ? "Exhaustive purchase search within your gold." : "Best evaluated plan; the full space was truncated."}`,
    };
  } catch (error) {
    state.optimizer.summary = {
      tested: 0,
      elapsedMs: performance.now() - started,
      label: `Best-buy search stopped: ${error.message}`,
    };
  } finally {
    state.optimizer.running = false;
    state.optimizer.scope = null;
    render();
  }
}

async function startOptimizeBuild() {
  if (state.optimizer.running || !state.attacker.champion || !optimizerDamagePackageReady() || !state.targets.length || !state.targets.every((target) => target.champion)) return;
  state.optimizer.running = true;
  state.optimizer.summary = null;
  render();
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
  const baseDamage = $("baseDamage");
  const apRatio = $("apRatio");
  const physicalDamage = $("physicalDamage");
  const adRatio = $("adRatio");
  state.attacker.baseDamage = baseDamage ? Math.max(0, Number(baseDamage.value) || 0) : 0;
  state.attacker.apRatio = apRatio ? Math.max(0, Number(apRatio.value) || 0) : 0;
  state.attacker.physicalDamage = physicalDamage ? Math.max(0, Number(physicalDamage.value) || 0) : 0;
  state.attacker.adRatio = adRatio ? Math.max(0, Number(adRatio.value) || 0) : 0;
  render();
}

document.addEventListener("click", (event) => {
  if (event.target.closest("#uptimeModeToggle")) {
    invalidateOptimization();
    if (state.fight.aaUptimeMode === "calculated") {
      state.fight.aaUptimeMode = "explicit";
      state.fight.aaUptime = Number(engine.responses?.a?.auto_attack_policy?.uptime ?? state.fight.aaUptime ?? 0);
    } else {
      state.fight.aaUptimeMode = "calculated";
    }
    return render();
  }
  const levelButton = event.target.closest("[data-level-delta]");
  if (levelButton) {
    const levelPath = levelButton.dataset.levelPath || levelButton.dataset.level;
    if (!levelPath) return;
    const rosterMatch = levelPath.match(/^(targets|allies)\.(\d+)\.level$/);
    const rosterLoadout = rosterMatch ? state[rosterMatch[1]]?.[Number(rosterMatch[2])] : null;
    const cap = levelPath === "attacker.level"
      ? attackerLevelCap()
      : (rosterLoadout?.role === "top" && rosterLoadout.roleQuestComplete ? 20 : 18);
    setPath(levelPath, Math.max(1, Math.min(cap, Number(pathValue(levelPath)) + Number(levelButton.dataset.levelDelta || levelButton.dataset.delta || 0))));
    if (levelPath === "attacker.level") syncAbilityInputsToLevel();
    invalidateOptimization();
    return render();
  }
  const bisObjectiveButton = event.target.closest("[data-bis-objective]");
  if (bisObjectiveButton) {
    const objective = bisObjectiveButton.dataset.bisObjective;
    if (!OBJECTIVES[objective] || !bisContext?.path) return;
    state.ui.objective = objective;
    bisContext.objective = objective;
    return openBackendBis(bisContext.path);
  }
  const objectiveButton = event.target.closest("[data-objective]");
  if (objectiveButton) {
    state.ui.objective = OBJECTIVES[objectiveButton.dataset.objective] ? objectiveButton.dataset.objective : "overall";
    renderScenarioRail();
    renderPrototypeBuilder();
    renderPrototypeResult(engine.responses?.a || null, engine.responses?.b || null);
    return;
  }
  const gameStateButton = event.target.closest("[data-game-state]");
  if (gameStateButton) {
    state.ui.gameState = gameStateButton.dataset.gameState === "live" ? "live" : "theory";
    return render();
  }
  const copyButton = event.target.closest("[data-copy]");
  if (copyButton) {
    const from = copyButton.dataset.copy === "a" ? "A" : "B";
    const to = from === "A" ? "B" : "A";
    state.attacker[`build${to}`] = [...state.attacker[`build${from}`]];
    state.attacker[`build${to}Stacks`] = [...state.attacker[`build${from}Stacks`]];
    state.attacker[`build${to}ItemOptions`] = (state.attacker[`build${from}ItemOptions`] || []).map((entry) => ({ ...entry }));
    state.attacker[`questBoot${to}`] = state.attacker[`questBoot${from}`];
    state.attacker.comparisonEnabled = true;
    invalidateOptimization();
    return render();
  }
  if (event.target.closest("#questToggle")) {
    state.attacker.roleQuestComplete = !state.attacker.roleQuestComplete;
    normalizeAttackerBootsForRole();
    normalizeAttackerSupportItemsForRole();
    state.attacker.level = Math.min(state.attacker.level, attackerLevelCap());
    invalidateOptimization();
    return render();
  }
  if (event.target.closest("#bootsToggle")) {
    state.attacker.includeBootsA = !state.attacker.includeBootsA;
    if (!state.attacker.includeBootsA) state.attacker.questBootA = 0;
    invalidateOptimization();
    return render();
  }
  if (event.target.closest("#addEnemy")) {
    if (state.targets.length >= 5) return;
    const index = state.targets.length;
    state.targets.push({ champion: null, level: 1, role: "", roleQuestComplete: false, items: [0, 0, 0, 0, 0, 0], itemStacks: [0, 0, 0, 0, 0, 0], itemOptions: [{}, {}, {}, {}, {}, {}], boots: 0, includeBoots: true, abilityRanks: {}, championOptions: {}, supportTargetSelections: {} });
    render();
    return openPicker("champion", `targets.${index}.champion`);
  }
  if (event.target.closest("#addPracticeEnemy")) {
    if (state.targets.length >= 5) return;
    const present = new Set(state.targets.map((target) => target.champion));
    const practice = PRACTICE_TARGETS.find((candidate) => !present.has(candidate.champion)) || PRACTICE_TARGETS[0];
    state.targets.push({ champion: practice.champion, level: practice.level, role: practice.role, roleQuestComplete: false, items: [0, 0, 0, 0, 0, 0], itemStacks: [0, 0, 0, 0, 0, 0], itemOptions: [{}, {}, {}, {}, {}, {}], boots: 0, includeBoots: true, abilityRanks: {}, championOptions: {}, supportTargetSelections: {} });
    invalidateOptimization();
    return render();
  }
  if (event.target.closest("#addAlly")) {
    if (state.allies.length >= 4) return;
    const index = state.allies.length;
    state.allies.push({ champion: null, level: 1, role: "", roleQuestComplete: false, items: [0, 0, 0, 0, 0, 0], itemStacks: [0, 0, 0, 0, 0, 0], itemOptions: [{}, {}, {}, {}, {}, {}], boots: 0, includeBoots: true, abilityRanks: {}, championOptions: {}, supportTargetSelections: {}, allyEffectsEnabled: false });
    render();
    return openPicker("champion", `allies.${index}.champion`);
  }
  if (event.target.closest("#bisAddEnemy")) {
    // The blocked-state shortcut: jump straight from the prerequisite note to
    // the enemy the optimizer is waiting on (#152).
    return document.getElementById("addEnemy")?.click();
  }
  if (event.target.closest("#bisButton")) {
    // applyPrerequisiteGates() disables this button and states the reason
    // beside it, so reaching here without a roster means a stale gate.
    if (!bisReadyForPath("attacker.buildA.0")) {
      const summary = $("resultSummary");
      if (summary) {
        summary.textContent = state.attacker.champion
          ? "Best-in-slot needs an enemy roster — add an enemy or use “vs practice target” first."
          : "Choose a champion before ranking items.";
      }
      applyPrerequisiteGates();
      return;
    }
    return openBis("attacker.buildA.0");
  }
  const rosterOptimizeAll = event.target.closest("[data-optimize-roster-all]");
  if (rosterOptimizeAll) return startRosterOptimization(rosterOptimizeAll.dataset.optimizeRosterAll);
  const rosterOptimize = event.target.closest("[data-optimize-roster]");
  if (rosterOptimize) return startRosterOptimization(rosterOptimize.dataset.optimizeRoster);
  if (event.target.closest("#economicsOptimize")) return startPurchaseOptimize();
  if (event.target.closest("[data-optimize-build]")) return startOptimizeBuild();
  const roleButton = event.target.closest("[data-role]");
  if (roleButton) {
    state.attacker.role = roleButton.dataset.role;
    normalizeAttackerBootsForRole();
    normalizeAttackerSupportItemsForRole();
    state.attacker.level = Math.min(state.attacker.level, attackerLevelCap());
    syncAbilityInputsToLevel();
    invalidateOptimization();
    return render();
  }
  if (event.target.closest("[data-role-quest]")) {
    state.attacker.roleQuestComplete = !state.attacker.roleQuestComplete;
    normalizeAttackerBootsForRole();
    normalizeAttackerSupportItemsForRole();
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
      state.attacker.buildBItemOptions = (state.attacker.buildAItemOptions || []).map((entry) => ({ ...entry }));
      state.attacker.questBootB = state.attacker.questBootA;
      state.attacker.keystoneB = state.attacker.keystoneA;
      state.attacker.keystoneOptionsB = { ...(state.attacker.keystoneOptionsA || {}) };
    }
    return render();
  }
  const pickerButton = event.target.closest("[data-picker]");
  if (pickerButton) {
    if (pickerButton.dataset.path?.startsWith("attacker.buildB")) state.attacker.comparisonEnabled = true;
    return openPicker(pickerButton.dataset.picker, pickerButton.dataset.path);
  }
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
    // Keep the explicit boots selection in browser state.  A rerender or
    // quest toggle must not erase the user's item; the backend remains the
    // authority for whether its tier is legal for the new role state.
    normalizeRosterRoleState(loadout);
    if (loadout.role !== "top" && loadout.level > 18) loadout.level = 18;
    invalidateOptimization();
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
  const itemOptionButton = event.target.closest("[data-item-option-path]");
  if (itemOptionButton) {
    const path = itemOptionButton.dataset.itemOptionPath;
    const key = itemOptionButton.dataset.itemOptionKey;
    const optionId = Number(itemOptionButton.dataset.itemOptionId);
    let specs = Number.isFinite(optionId) && optionId > 0 ? itemOptionSpecs(optionId) : itemOptionSpecsForPath(path);
    let spec = specs.find((entry) => entry.key === key);
    if (!spec) {
      specs = itemOptionSpecsForPath(path);
      spec = specs.find((entry) => entry.key === key);
    }
    if (!spec) return;
    const next = Math.max(spec.min, Math.min(spec.max, itemOptionValue(path, key) + Number(itemOptionButton.dataset.delta || 0)));
    setItemOptionValue(path, key, next);
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
      state.targets.push({ champion: null, level: 1, role: "", roleQuestComplete: false, items: [0, 0, 0, 0, 0, 0], itemStacks: [0, 0, 0, 0, 0, 0], itemOptions: [{}, {}, {}, {}, {}, {}], boots: 0, includeBoots: true, abilityRanks: {}, championOptions: {}, supportTargetSelections: {} });
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
      state.allies.push({ champion: null, level: 1, role: "", roleQuestComplete: false, items: [0, 0, 0, 0, 0, 0], itemStacks: [0, 0, 0, 0, 0, 0], itemOptions: [{}, {}, {}, {}, {}, {}], boots: 0, includeBoots: true, abilityRanks: {}, championOptions: {}, supportTargetSelections: {}, allyEffectsEnabled: false });
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
    if (pickerContext.type === "item") {
      if (/^attacker\.build[AB]\./.test(selectedPath)) {
        normalizeAttackerSupportItemsForRole();
      } else if (/^(targets|allies)\.\d+\.(items|boots)$/.test(selectedPath)) {
        const [root, indexText] = selectedPath.split(".");
        normalizeRosterRoleState(state[root]?.[Number(indexText)]);
      }
    }
    if (pickerContext.type === "champion" && selectedPath === "attacker.champion") {
      resetAbilityInputs();
      resetChampionOptions();
    }
    if (pickerContext.type === "champion" && /^(targets|allies)\.\d+\.champion$/.test(selectedPath)) {
      const [root, indexText] = selectedPath.split(".");
      const loadout = state[root][Number(indexText)];
      loadout.abilityRanks = defaultAbilityRanks(loadout);
      resetRosterChampionOptions(loadout);
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
}, true);

document.addEventListener("input", (event) => {
  const protoRange = event.target.closest("[data-proto-range]");
  if (protoRange) {
    invalidateOptimization();
    const key = protoRange.dataset.protoRange;
    if (key === "aaUptime") state.fight.aaUptimeMode = "explicit";
    state.fight[key] = key === "aaUptime" ? Number(protoRange.value) / 100 : Number(protoRange.value);
    return render();
  }
  const range = event.target.closest("[data-fight-range]");
  if (!range) return;
  invalidateOptimization();
  const key = range.dataset.fightRange;
  if (key === "aaUptime") state.fight.aaUptimeMode = "explicit";
  state.fight[key] = key === "aaUptime" ? Number(range.value) / 100 : Number(range.value);
  const output = range.parentElement.querySelector("output");
  if (output) output.textContent = key === "aaUptime" ? `${Math.round(state.fight.aaUptime * 100)}%` : `${one(state.fight.duration)}s`;
  render();
  $("scenarioSentence").innerHTML = scenarioSentence();
  scheduleEngineCalculation();
});

document.addEventListener("change", (event) => {
  const economicsGold = event.target.closest("#economicsGold");
  if (economicsGold) {
    const value = Number.parseInt(economicsGold.value, 10);
    state.optimizer.availableGold = Number.isInteger(value) ? Math.max(0, Math.min(30_000, value)) : 0;
    return render();
  }
  const supportSelection = event.target.closest(".support-target-selection");
  if (supportSelection) {
    const owner = supportSelectionOwner(supportSelection.dataset.value);
    if (!owner) return;
    if (!owner.supportTargetSelections) owner.supportTargetSelections = {};
    owner.supportTargetSelections[supportSelection.dataset.optionKey] = Number(supportSelection.value) || 0;
    invalidateOptimization();
    return render();
  }
  const keystoneOption = event.target.closest("[data-keystone-option]");
  if (keystoneOption) {
    const side = keystoneOption.dataset.keystoneOption;
    const key = keystoneOption.dataset.keystoneOptionKey;
    const name = state.attacker[`keystone${side}`] || "";
    const option = engine.keystoneOptions[name]?.options?.[key];
    if (!option) return;
    const parsed = Number.parseInt(keystoneOption.value, 10);
    const fallback = Number(option.default ?? 0);
    const value = Number.isFinite(parsed) ? parsed : fallback;
    if (!state.attacker[`keystoneOptions${side}`]) {
      state.attacker[`keystoneOptions${side}`] = {};
    }
    state.attacker[`keystoneOptions${side}`][key] = Math.min(
      Math.max(value, Number(option.min ?? value)),
      Number(option.max ?? value),
    );
    invalidateOptimization();
    return render();
  }
  const championOption = event.target.closest("[data-champion-option]");
  if (championOption) {
    const key = championOption.dataset.championOption;
    const type = championOption.dataset.optionType || "bool";
    const definition = (engine.championOptions[state.attacker.champion]?.options || [])
      .find((option) => option.key === key);
    if (type === "bool") {
      state.attacker.championOptions[key] = Boolean(championOption.checked);
    } else if (type === "select") {
      state.attacker.championOptions[key] = championOption.value;
    } else if (type === "string_list") {
      state.attacker.championOptions[key] = parseStringListOption(championOption.value);
    } else {
      const parsed = type === "int"
        ? Number.parseInt(championOption.value, 10)
        : Number(championOption.value);
      const fallback = Number(definition?.default ?? 0);
      const bounded = Number.isFinite(parsed) ? parsed : fallback;
      const minimum = definition?.min == null ? bounded : Math.max(Number(definition.min), bounded);
      const maximum = definition?.max == null ? minimum : Math.min(Number(definition.max), minimum);
      state.attacker.championOptions[key] = type === "int" ? Math.round(maximum) : maximum;
    }
    invalidateOptimization();
    return render();
  }
  const rosterChampionOption = event.target.closest("[data-roster-champion-option]");
  if (rosterChampionOption) {
    const loadout = pathValue(rosterChampionOption.dataset.rosterChampionOption);
    if (!loadout) return;
    const key = rosterChampionOption.dataset.optionKey;
    const type = rosterChampionOption.dataset.optionType || "bool";
    const definition = (engine.championOptions[loadout.champion]?.options || [])
      .find((option) => option.key === key);
    if (!loadout.championOptions) loadout.championOptions = {};
    if (type === "bool") {
      loadout.championOptions[key] = Boolean(rosterChampionOption.checked);
    } else if (type === "select") {
      loadout.championOptions[key] = rosterChampionOption.value;
    } else if (type === "string_list") {
      loadout.championOptions[key] = parseStringListOption(rosterChampionOption.value);
    } else {
      const parsed = type === "int"
        ? Number.parseInt(rosterChampionOption.value, 10)
        : Number(rosterChampionOption.value);
      const fallback = Number(definition?.default ?? 0);
      const bounded = Number.isFinite(parsed) ? parsed : fallback;
      const minimum = definition?.min == null ? bounded : Math.max(Number(definition.min), bounded);
      const maximum = definition?.max == null ? minimum : Math.min(Number(definition.max), minimum);
      loadout.championOptions[key] = type === "int" ? Math.round(maximum) : maximum;
    }
    invalidateOptimization();
    return render();
  }
  const roleSelect = event.target.closest("#roleSelect");
  if (roleSelect) {
    state.attacker.role = roleSelect.value || null;
    if (!state.attacker.role) state.attacker.roleQuestComplete = false;
    normalizeAttackerBootsForRole();
    normalizeAttackerSupportItemsForRole();
    state.attacker.level = Math.min(state.attacker.level, attackerLevelCap());
    invalidateOptimization();
    return render();
  }
  const levelInput = event.target.closest("#levelInput");
  if (levelInput) {
    state.attacker.level = Math.max(1, Math.min(attackerLevelCap(), Number(levelInput.value) || 1));
    syncAbilityInputsToLevel();
    invalidateOptimization();
    return render();
  }
  const rosterRoleSelect = event.target.closest("[data-roster-role]");
  if (!rosterRoleSelect) return;
  const loadout = pathValue(rosterRoleSelect.dataset.rosterRole.replace(/\.role$/, ""));
  if (!loadout) return;
  loadout.role = rosterRoleSelect.value;
  if (!loadout.role) loadout.roleQuestComplete = false;
  // Role changes rerender the card but do not erase the selected boots.
  normalizeRosterRoleState(loadout);
  if (loadout.role !== "top" && loadout.level > 18) loadout.level = 18;
  invalidateOptimization();
  render();
});

document.addEventListener("change", (event) => {
  if (event.target.closest("[data-fight-range]")) render();
});

$("pickerSearch").addEventListener("input", (event) => renderPicker(event.target.value));
$("pickerClose").addEventListener("click", closePicker);
$("picker").addEventListener("click", (event) => { if (event.target === $("picker")) closePicker(); });
$("bisClose").addEventListener("click", closeBis);
$("bis").addEventListener("click", (event) => { if (event.target === $("bis")) closeBis(); });
for (const id of ["baseDamage", "apRatio", "physicalDamage", "adRatio"]) {
    const element = $(id);
    if (element) element.addEventListener("input", updateDamagePackage);
  }

Promise.all([
  fetch("/static/data.json").then((response) => { if (!response.ok) throw new Error("Patch snapshot failed to load"); return response.json(); }),
  fetch("/api/champions").then((response) => { if (!response.ok) throw new Error("Champion availability failed to load"); return response.json(); }),
  fetch("/api/config").then((response) => response.ok ? response.json() : { item_options: {}, champion_options: {}, keystone_options: {}, keystones: [], input_limits: {} }),
  fetch("/api/items").then((response) => response.ok ? response.json() : []),
  fetch("/api/boots").then((response) => response.ok ? response.json() : []),
  fetch("/static/ability-catalog.json").then((response) => { if (!response.ok) throw new Error("Ability catalogue failed to load"); return response.json(); }),
  fetch("/static/bis-profiles.json").then((response) => { if (!response.ok) throw new Error("Wiki BIS profile failed to load"); return response.json(); }),
  fetch("/static/effect-catalog.json").then((response) => { if (!response.ok) throw new Error("Wiki effect catalogue failed to load"); return response.json(); }),
])
  .then(([data, championAvailability, config, itemCoverage, bootCatalog, abilityCatalog, bisProfiles, effectCatalog]) => {
    DATA = data;
    mergeItemCoverage([...(itemCoverage || []), ...(bootCatalog || [])]);
    mergeAbilityCatalog(abilityCatalog);
    mergeBisProfiles(bisProfiles);
    mergeEffectCatalog(effectCatalog);
    championAvailability.forEach((entry) => {
      const champion = DATA.champions.find((candidate) => candidate.name === entry.name);
      if (champion) champion.engineRegistration = entry.engine_registration || null;
      engine.availability.set(entry.name, entry.availability || {});
      if (entry.availability?.ready && entry.engine_registration === "reviewed_module") engine.reviewed.add(entry.name);
      if (entry.engine_backend_enabled) engine.backend.add(entry.name);
    });
    engine.itemOptions = config.item_options || {};
    engine.championOptions = config.champion_options || {};
    engine.keystoneOptions = config.keystone_options || {};
    engine.capabilities = config.capabilities || { participants: {}, scenario: { fields: {} } };
    applyControlCapabilities();
    maybeInitConsentAnalytics();
    engine.keystones = config.keystones || [];
    engine.defaultTarget = config.default_target || engine.defaultTarget;
    engine.fightDefaults = config.fight_defaults || {};
    engine.exclusivityGroups = config.exclusivity_groups || {};
    engine.roleQuest = config.role_quest || {};
    normalizeAttackerBootsForRole();
    const fightDefaults = engine.fightDefaults;
    state.fight.aaUptimeMode = fightDefaults.auto_attack_uptime_mode || "calculated";
    if (fightDefaults.mode === "one_rotation") {
      const oneRotationDuration = Number(fightDefaults.one_rotation_duration_seconds);
      if (Number.isFinite(oneRotationDuration) && oneRotationDuration > 0) {
        state.fight.duration = oneRotationDuration;
      }
      state.fight.aaUptime = state.fight.aaUptimeMode === "calculated" ? 0 : state.fight.aaUptime;
    } else {
      const defaultDuration = Number(fightDefaults.duration_seconds);
      const defaultUptime = Number(fightDefaults.auto_attack_uptime);
      if (Number.isFinite(defaultDuration) && defaultDuration > 0) state.fight.duration = defaultDuration;
      if (Number.isFinite(defaultUptime) && defaultUptime >= 0) state.fight.aaUptime = defaultUptime;
    }
    engine.fightLimits = { ...engine.fightLimits, ...(config.input_limits || {}) };
    engine.ready = true;
    render();
  })
  .catch(() => {
    const status = document.getElementById("resultStatus");
    if (status) {
      status.textContent = "error";
      status.classList.remove("calculating");
    }
    showEngineError("The patch snapshot could not load. Refresh to try again.");
  });

// ============================================================================
// P5 · Casual quick mode + presets + build sharing + trust labels (P4)
// A self-contained layer on top of the analyst engine above. It owns:
//   - the Quick view (champion → role → enemy → "Best next item")
//   - preset scenarios (static/quick-presets.json)
//   - build sharing (POST /api/builds + POST /api/share + ?share=<token>)
//   - trust chips (GET /api/certainty, GET /api/not-modeled) with a
//     contract-shaped mock fallback until the P7 backend routes deploy.
// ============================================================================

const QUICK_ROLES = ["top", "jungle", "mid", "bottom", "support"];
const ROLE_LABELS = { top: "Top", jungle: "Jungle", mid: "Mid", bottom: "Bottom", support: "Support" };
// Implicit practice target used when the casual user skips enemy selection.
const QUICK_PRACTICE_ENEMY = { champion: "Jhin", level: 18, role: "bottom", items: [] };
// Practice dummies for the analyst roster's "vs practice target" affordance:
// a squishy, a tank, and a bruiser. Each click adds the next dummy that is
// not already in the roster so the engine's no-duplicate-champions rule
// never fires.
const PRACTICE_TARGETS = [
  QUICK_PRACTICE_ENEMY,
  { champion: "Ornn", level: 18, role: "top", items: [] },
  { champion: "Garen", level: 18, role: "top", items: [] },
];
const QUICK_MAX_ITEMS = 5;
const QUICK_LEVEL = 18;

const QUICK_STATE = {
  champion: null,
  role: "mid",
  enemy: null,           // null = practice target
  items: [],             // legendary item names already owned
  presetId: null,
  running: false,
  results: null,         // { baseline: {...}, candidates: [...], slot: {...}, payload: {...}, at: ts }
  share: null,           // { token, url, buildId }
};
let QUICK_PRESETS = [];
let QUICK_VIEW_READY = false;
let QUICK_INIT_STARTED = false;

// --- Trust labels (P4) ------------------------------------------------------
// Consumed contract (owned by the P7 backend agent):
//   GET /api/certainty?champion=X -> {"champion": "...", "slots": {"Q": {"certainty": "exact|estimate|boundary", "reason": "..."}}}
//   GET /api/not-modeled?champion=X -> {"champion": "...", "items": ["..."]}
// A missing/erroring route falls back to a contract-shaped mock; the UI shows
// a "placeholder" note whenever the fallback is active so no chip is ever
// presented as sourced data it is not.
const CERTAINTY_LABELS = {
  exact: { label: "EXACT", detail: "Fully sourced formula, no player-controlled options." },
  estimate: { label: "ESTIMATE", detail: "Uses a defaulted player-controlled option." },
  boundary: { label: "BOUNDARY", detail: "Documented mechanic that is not computed." },
};
const CERTAINTY_STATE = { source: "api", champion: null, slots: {}, loading: false };
const NOT_MODELED_STATE = { source: "api", champion: null, items: [], loading: false };

function certaintyMock(champion) {
  return {
    champion,
    slots: {
      P: { certainty: "boundary", reason: "Passive mechanics are documented but not computed by the shared event model." },
      Q: { certainty: "estimate", reason: "Placeholder contract — per-champion certainty data is pending from the validation service." },
      W: { certainty: "estimate", reason: "Placeholder contract — per-champion certainty data is pending from the validation service." },
      E: { certainty: "estimate", reason: "Placeholder contract — per-champion certainty data is pending from the validation service." },
      R: { certainty: "estimate", reason: "Placeholder contract — per-champion certainty data is pending from the validation service." },
    },
  };
}

function notModeledMock(champion) {
  return { champion, items: [] };
}

async function fetchTrustContract(path, champion, mockBuilder) {
  try {
    const response = await fetch(`${path}?champion=${encodeURIComponent(champion)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (!payload || typeof payload !== "object") throw new Error("malformed payload");
    return { ...payload, source: "api" };
  } catch (error) {
    const mock = mockBuilder(champion);
    return { ...mock, source: "mock", reason: `endpoint unavailable (${error.message})` };
  }
}

async function loadTrustLabels(champion) {
  if (!champion) return;
  if (CERTAINTY_STATE.champion === champion && !CERTAINTY_STATE.loading && !NOT_MODELED_STATE.loading) return;
  CERTAINTY_STATE.champion = champion;
  CERTAINTY_STATE.loading = true;
  NOT_MODELED_STATE.loading = true;
  const [certainty, notModeled] = await Promise.all([
    fetchTrustContract("/api/certainty", champion, certaintyMock),
    fetchTrustContract("/api/not-modeled", champion, notModeledMock),
  ]);
  CERTAINTY_STATE.source = certainty.source === "api" ? "api" : "mock";
  CERTAINTY_STATE.slots = (certainty && certainty.slots) || {};
  NOT_MODELED_STATE.source = notModeled.source === "api" ? "api" : "mock";
  NOT_MODELED_STATE.items = Array.isArray(notModeled && notModeled.items) ? notModeled.items : [];
  CERTAINTY_STATE.loading = false;
  NOT_MODELED_STATE.loading = false;
  renderTrustPanels();
  // Re-render an already-visible analyst breakdown so chips appear live.
  if (!document.getElementById("analystView").hidden && engine.responses?.a) {
    renderExactBreakdown(engine.responses.a, engine.responses.b || null);
  }
}

function certaintyForSlot(slot) {
  const entry = CERTAINTY_STATE.slots[String(slot || "")];
  if (!entry || !CERTAINTY_LABELS[entry.certainty]) return null;
  return {
    label: CERTAINTY_LABELS[entry.certainty].label,
    certainty: entry.certainty,
    reason: entry.reason || CERTAINTY_LABELS[entry.certainty].detail,
  };
}

function certaintyChipHtml(slot) {
  const meta = certaintyForSlot(slot);
  if (!meta) return "";
  return `<span class="certainty-chip certainty-${meta.certainty}" title="${escapeHtml(meta.reason)}">${meta.label}</span>`;
}

function renderTrustPanels() {
  const champion = state.attacker.champion || QUICK_STATE.champion || "";
  const placeholder = CERTAINTY_STATE.source === "mock" || NOT_MODELED_STATE.source === "mock";
  const legend = document.getElementById("trustLegend");
  if (legend) {
    legend.hidden = !champion;
    const note = legend.querySelector(".trust-legend-note");
    if (note) {
      note.textContent = placeholder
        ? "Placeholder chips — certainty endpoints are not deployed yet."
        : "";
      note.hidden = !placeholder;
    }
  }
  const quickLegendHost = document.querySelector("#quickView .trust-legend");
  const quickNote = quickLegendHost ? quickLegendHost.querySelector(".trust-legend-note") : null;
  if (quickNote) {
    quickNote.textContent = placeholder
      ? "Placeholder chips — certainty endpoints are not deployed yet."
      : "";
    quickNote.hidden = !placeholder;
  }
  const panel = document.getElementById("notModeledPanel");
  const quickPanel = document.getElementById("quickNotModeled");
  const items = NOT_MODELED_STATE.items || [];
  if (panel) {
    panel.hidden = !champion;
    document.getElementById("notModeledList").innerHTML = items.length
      ? items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
      : `<li class="not-modeled-empty">Nothing — every modeled item for ${escapeHtml(champion)} is included in calculations.</li>`;
  }
  if (quickPanel) {
    quickPanel.hidden = !champion;
    document.getElementById("quickNotModeledList").innerHTML = items.length
      ? items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
      : `<li class="not-modeled-empty">Nothing — every modeled item for ${escapeHtml(champion)} is included in calculations.</li>`;
  }
}

// --- Quick view rendering ---------------------------------------------------

function quickChampionEntries() {
  return (DATA?.champions || []).slice().sort((a, b) => a.name.localeCompare(b.name));
}

function quickItemEntries(query) {
  const q = String(query || "").trim().toLowerCase();
  return (DATA?.items || [])
    .filter((item) => item.backendAvailable !== false && Number(item.price) > 0)
    .filter((item) => !q || item.name.toLowerCase().includes(q))
    .slice(0, 30);
}

function quickGridButton(kind, entry, selected) {
  const isChampion = kind === "champion" || kind === "enemy";
  const icon = isChampion
    ? `<img src="${championImage(entry.name)}" alt="" loading="lazy" />`
    : `<img src="${itemImage(entry.id)}" alt="" loading="lazy" />`;
  const detail = isChampion
    ? escapeHtml(entry.title || "")
    : `${fmt(Number(entry.price) || 0)} gold`;
  return `<button type="button" class="quick-choice ${selected ? "selected" : ""}" data-quick-pick="${kind}" data-value="${escapeHtml(isChampion ? entry.name : entry.name)}" aria-pressed="${selected}">${icon}<span><strong>${escapeHtml(entry.name)}</strong><small>${detail}</small></span></button>`;
}

function renderQuickRole() {
  const host = document.getElementById("quickRole");
  if (!host) return;
  host.innerHTML = QUICK_ROLES.map((role) => `<button type="button" class="quick-role ${QUICK_STATE.role === role ? "active" : ""}" data-quick-role="${role}" aria-pressed="${QUICK_STATE.role === role}">${ROLE_LABELS[role]}</button>`).join("");
}

function renderQuickChampionGrid(query) {
  const host = document.getElementById("quickChampionGrid");
  if (!host) return;
  const q = String(query || "").trim().toLowerCase();
  const entries = quickChampionEntries().filter((entry) => !q || entry.name.toLowerCase().includes(q));
  host.innerHTML = entries.slice(0, 40).map((entry) => quickGridButton("champion", entry, QUICK_STATE.champion === entry.name)).join("");
  const note = document.getElementById("quickChampionNote");
  if (note) {
    note.textContent = QUICK_STATE.champion
      ? `Locked: ${QUICK_STATE.champion}. Pick a different champion to change it.`
      : `${entries.length} champions · type to filter`;
  }
}

function renderQuickEnemyGrid(query) {
  const host = document.getElementById("quickEnemyGrid");
  if (!host) return;
  const q = String(query || "").trim().toLowerCase();
  const entries = quickChampionEntries().filter((entry) => !q || entry.name.toLowerCase().includes(q));
  const practice = QUICK_STATE.enemy === null;
  host.innerHTML = `<button type="button" class="quick-choice ${practice ? "selected" : ""}" data-quick-pick="enemy" data-value="" aria-pressed="${practice}"><span class="quick-choice-icon quick-practice-icon" aria-hidden="true">🎯</span><span><strong>Practice target</strong><small>Default squishy dummy — no specific enemy</small></span></button>` + entries.slice(0, 40).map((entry) => quickGridButton("enemy", entry, !practice && QUICK_STATE.enemy?.champion === entry.name)).join("");
  const note = document.getElementById("quickEnemyNote");
  if (note) {
    note.textContent = QUICK_STATE.enemy
      ? `Fighting ${QUICK_STATE.enemy.champion}.`
      : "Leave empty to fight a default practice target.";
  }
  const clear = document.getElementById("quickEnemyClear");
  if (clear) clear.hidden = QUICK_STATE.enemy === null;
}

function renderQuickItemGrid(query) {
  const host = document.getElementById("quickItemGrid");
  if (!host) return;
  const q = String(query || "").trim().toLowerCase();
  const owned = new Set(QUICK_STATE.items);
  host.innerHTML = quickItemEntries(q).filter((item) => !owned.has(item.name)).slice(0, 24).map((entry) => quickGridButton("item", entry, false)).join("");
}

function renderQuickItemsStrip() {
  const host = document.getElementById("quickItems");
  if (!host) return;
  host.innerHTML = QUICK_STATE.items.length
    ? QUICK_STATE.items.map((name) => {
        const item = findItemByBackendName(name);
        return `<span class="quick-item-chip"><img src="${item ? itemImage(item.id) : ""}" alt="" /><b>${escapeHtml(name)}</b><button type="button" class="quick-item-remove" data-quick-remove="${escapeHtml(name)}" aria-label="Remove ${escapeHtml(name)}">×</button></span>`;
      }).join("")
    : `<span class="quick-items-empty">No items yet — the recommendation is for your first completed item.</span>`;
}

function renderQuickPresets() {
  const host = document.getElementById("quickPresets");
  if (!host) return;
  host.innerHTML = QUICK_PRESETS.map((preset) => `<button type="button" class="quick-preset ${QUICK_STATE.presetId === preset.id ? "active" : ""}" data-quick-preset="${escapeHtml(preset.id)}" title="${escapeHtml(preset.tagline || "")}" aria-pressed="${QUICK_STATE.presetId === preset.id}"><span class="quick-preset-emoji" aria-hidden="true">${preset.emoji || "🎮"}</span><span><strong>${escapeHtml(preset.label)}</strong><small>${escapeHtml(preset.tagline || "")}</small></span></button>`).join("");
}

function renderQuickView() {
  if (!QUICK_VIEW_READY) return;
  if (!document.getElementById("quickView")) return; // quick mode removed (2026-08-06)
  renderQuickRole();
  renderQuickChampionGrid(document.getElementById("quickChampionSearch")?.value || "");
  renderQuickEnemyGrid(document.getElementById("quickEnemySearch")?.value || "");
  renderQuickItemsStrip();
  renderQuickItemGrid(document.getElementById("quickItemSearch")?.value || "");
  renderQuickPresets();
  renderTrustPanels();
  const run = document.getElementById("quickRun");
  if (run) {
    run.disabled = !QUICK_STATE.champion || QUICK_STATE.running;
    run.textContent = QUICK_STATE.running ? "Working…" : "Best next item";
  }
}

// --- Payloads ---------------------------------------------------------------

function quickPreset() {
  return QUICK_PRESETS.find((preset) => preset.id === QUICK_STATE.presetId) || null;
}

function quickFightSettings() {
  const preset = quickPreset();
  if (preset) return { ...preset.fight };
  return {
    rotations: 1,
    fight_mode: "one_rotation",
    fight_duration: 10,
    auto_attack_uptime_mode: "calculated",
    include_auto_attacks: true,
  };
}

function quickEnemyLoadout() {
  if (QUICK_STATE.enemy) {
    return [
      {
        champion: QUICK_STATE.enemy.champion,
        level: QUICK_STATE.enemy.level || 18,
        role: QUICK_STATE.enemy.role || "top",
        items: QUICK_STATE.enemy.items || [],
      },
    ];
  }
  const preset = quickPreset();
  if (preset && Array.isArray(preset.enemies) && preset.enemies.length) {
    // A preset owns its full enemy roster (the 4v4 preset is a coupled
    // team fight); a user-picked enemy always overrides it.
    return preset.enemies.map((enemy) => ({ ...enemy }));
  }
  return [{ ...QUICK_PRACTICE_ENEMY }];
}

function quickCalculatePayload() {
  const fight = quickFightSettings();
  const preset = quickPreset();
  const payload = {
    champion: QUICK_STATE.champion,
    level: QUICK_LEVEL,
    role: QUICK_STATE.role,
    items: QUICK_STATE.items.slice(0, QUICK_MAX_ITEMS),
    item_options: {},
    ability_ranks: null,
    champion_options: {},
    enemies: quickEnemyLoadout(),
    allies: preset ? (preset.allies || []).slice() : [],
    role_quest_complete: false,
    include_actives: true,
    include_crossover: false,
    rotations: fight.rotations,
    fight_mode: fight.fight_mode,
    fight_duration: fight.fight_duration,
    auto_attack_uptime_mode: fight.auto_attack_uptime_mode,
    include_auto_attacks: fight.include_auto_attacks,
  };
  return payload;
}

function quickBisPayload() {
  const payload = quickCalculatePayload();
  const count = QUICK_STATE.items.length;
  if (count < QUICK_MAX_ITEMS) {
    payload.slot_index = count;
    payload.slot_kind = "item";
  } else {
    payload.slot_index = 0;
    payload.slot_kind = "boots";
  }
  payload.subject_team = "main";
  payload.objective = "overall";
  return payload;
}

function postJson(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function quickBaselineResult(payload) {
  const response = await postJson("/api/calculate", payload);
  const result = await response.json();
  if (!response.ok || result.error) throw new Error(result.error || `calculate failed (HTTP ${response.status})`);
  const main = (result.combat?.participants || []).find((participant) => participant.participant_id === "main");
  const mainBreakdown = (result.combat?.breakdown || []).find((row) => row.participant_id === "main");
  return {
    tdd: Number(mainBreakdown?.total_damage ?? result.total_damage ?? 0),
    ehp: Number(main?.survival?.effective_health ?? 0),
    effectiveArmor: Number(result.effective_armor ?? 0),
    effectiveMr: Number(result.effective_mr ?? 0),
    result,
  };
}

async function quickCandidates(payload) {
  const response = await postJson("/api/bis", payload);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || `best-next-item failed (HTTP ${response.status})`);
  const certified = Array.isArray(data.candidates) ? data.candidates : [];
  const partial = Array.isArray(data.partial_candidates) ? data.partial_candidates : [];
  const pool = certified.length ? certified : partial;
  return {
    candidates: pool.slice(0, 3).map((candidate) => ({
      name: candidate.name,
      icon: candidate.icon || "",
      score: Number(candidate.score ?? candidate.objective_value ?? 0),
      components: candidate.components || {},
      stats: candidate.stats || {},
      survival: candidate.survival || {},
      gold: Number((findItemByBackendName(candidate.name) || {}).price || 0),
      certified: Boolean(candidate.timeline_coverage?.complete),
    })),
    certified: certified.length > 0,
    coverageNote: data.coverage?.note || "",
  };
}

// --- One-line "why" ---------------------------------------------------------

function quickWhy(candidate, baseline, index, context) {
  const deltaD = candidate.score - baseline.tdd;
  const deltaE = (Number(candidate.survival.effective_health) || 0) - baseline.ehp;
  const stats = candidate.stats || {};
  const armorPen = Number(stats.armorPenetration || 0) + Number(stats.lethality || 0);
  const magicPen = Number(stats.magicPenetration || 0) + Number(stats.percentPen || 0);
  const defensive = Number(stats.hp || 0) + Number(stats.armor || 0) * 5 + Number(stats.magicResistance || 0) * 5;
  if (baseline.effectiveMr > 120 && magicPen > 0) {
    return "Bypasses the enemy's heavy magic resistance";
  }
  if (baseline.effectiveArmor > 120 && armorPen > 0) {
    return "Cuts through the enemy's heavy armor";
  }
  if (deltaE > 0 && defensive > 300 && baseline.ehp < 2200) {
    return "Adds durability — your current build is fragile here";
  }
  if (context.leadsDamage === candidate.name) {
    return `Biggest single-slot damage gain (+${fmt(deltaD)} TDD)`;
  }
  if (context.leadsSurvival === candidate.name) {
    return `Biggest survivability gain (+${fmt(deltaE)} eHP)`;
  }
  if (context.cheapest === candidate.name) {
    return `Cheapest slot improvement (${fmt(candidate.gold)} gold)`;
  }
  return "Strong all-round pick for this matchup";
}

function quickContext(candidates, baseline) {
  const withD = candidates.map((candidate) => ({ candidate, deltaD: candidate.score - baseline.tdd }));
  const withE = candidates.map((candidate) => ({ candidate, deltaE: (Number(candidate.survival.effective_health) || 0) - baseline.ehp }));
  // Only claim a "gain" when the delta is actually positive; a zero/negative
  // delta (e.g. an attack-speed boots pick for a mage) must not be sold as a
  // damage gain.
  const positiveD = withD.filter((row) => row.deltaD > 0.5);
  const positiveE = withE.filter((row) => row.deltaE > 0.5);
  const bestD = positiveD.reduce((best, row) => (row.deltaD > best.deltaD ? row : best), positiveD[0]);
  const bestE = positiveE.reduce((best, row) => (row.deltaE > best.deltaE ? row : best), positiveE[0]);
  const cheapest = candidates.reduce((best, candidate) => (!best || candidate.gold < best.gold ? candidate : best), null);
  return {
    leadsDamage: bestD ? bestD.candidate.name : null,
    leadsSurvival: bestE ? bestE.candidate.name : null,
    cheapest: cheapest ? cheapest.name : null,
  };
}

// --- Results rendering ------------------------------------------------------

function quickResultCard(candidate, index, baseline, context, certified) {
  const deltaD = candidate.score - baseline.tdd;
  const deltaE = (Number(candidate.survival.effective_health) || 0) - baseline.ehp;
  const deltaClass = (delta) => (Math.abs(delta) < 0.5 ? "quick-delta-flat" : delta > 0 ? "quick-delta-up" : "quick-delta-down");
  const why = quickWhy(candidate, baseline, index, context);
  return `<article class="quick-card ${index === 0 ? "quick-card-top" : ""}">
    <div class="quick-card-rank" aria-hidden="true">${index + 1}</div>
    <img class="quick-card-icon" src="${candidate.icon || ""}" alt="" loading="lazy" />
    <div class="quick-card-main">
      <div class="quick-card-title"><strong>${escapeHtml(candidate.name)}</strong>${candidate.gold ? `<span class="quick-card-gold">${fmt(candidate.gold)}g</span>` : ""}${certified ? "" : `<span class="certainty-chip certainty-estimate" title="Event order is partially certified for this coupled roster">PARTIAL</span>`}</div>
      <p class="quick-card-why">${escapeHtml(why)}</p>
    </div>
    <dl class="quick-card-deltas">
      <div><dt>TDD</dt><dd class="${deltaClass(deltaD)}">${deltaD >= 0 ? "+" : ""}${fmt(deltaD)}</dd></div>
      <div><dt>eHP</dt><dd class="${deltaClass(deltaE)}">${deltaE >= 0 ? "+" : ""}${fmt(deltaE)}</dd></div>
    </dl>
  </article>`;
}

function renderQuickResults(results) {
  const host = document.getElementById("quickResults");
  const after = document.getElementById("quickAfter");
  if (!results) {
    host.hidden = true;
    if (after) after.hidden = true;
    return;
  }
  host.hidden = false;
  if (after) after.hidden = false;
  const context = quickContext(results.candidates, results.baseline);
  const enemy = Array.isArray(results.enemies) && results.enemies.length ? results.enemies[0] : quickEnemyLoadout()[0] || QUICK_PRACTICE_ENEMY;
  const preset = quickPreset();
  const slotLabel = results.slot.kind === "boots" ? "boots slot" : `item slot ${results.slot.index + 1}`;
  const coverage = results.certified
    ? ""
    : `<p class="quick-coverage-note">${escapeHtml(results.coverageNote || "Coupled-roster event order is partially certified; scores below are estimates.")}</p>`;
  host.innerHTML = `
    <div class="quick-results-head">
      <div><p class="eyebrow">Recommended next item</p><h2>${escapeHtml(QUICK_STATE.champion)} · ${ROLE_LABELS[QUICK_STATE.role]}</h2></div>
      <p class="quick-scenario-line">vs ${results.enemies.length > 1 ? `${results.enemies.length} enemies` : escapeHtml(enemy.champion)}${preset ? ` · ${escapeHtml(preset.label)}` : ""} · filling the ${slotLabel}</p>
    </div>
    ${coverage}
    <div class="quick-card-list">
      ${results.candidates.map((candidate, index) => quickResultCard(candidate, index, results.baseline, context, results.certified)).join("")}
    </div>
    <p class="quick-baseline-line">Baseline (your current build): ${fmt(results.baseline.tdd)} TDD · ${fmt(results.baseline.ehp)} eHP before adding an item.</p>`;
}

// --- Quick → analyst bridge -------------------------------------------------

function openQuickInAnalyst() {
  if (!QUICK_STATE.champion) {
    document.getElementById("quickChampionSearch").focus();
    return;
  }
  const payload = QUICK_STATE.results?.payload || quickCalculatePayload();
  state.attacker.champion = QUICK_STATE.champion;
  state.attacker.level = QUICK_LEVEL;
  state.attacker.role = QUICK_STATE.role || "mid";
  state.attacker.roleQuestComplete = false;
  state.attacker.buildA = [0, 0, 0, 0, 0, 0];
  state.attacker.buildAStacks = [0, 0, 0, 0, 0, 0];
  state.attacker.buildAItemOptions = [{}, {}, {}, {}, {}, {}];
  state.attacker.questBootA = 0;
  state.attacker.includeBootsA = true;
  state.attacker.keystoneA = request.keystone || "";
  state.attacker.keystoneOptionsA = { ...(request.keystone_options || {}) };
  state.attacker.comparisonEnabled = false;
  (payload.items || []).forEach((name, index) => {
    if (index >= 6) return;
    const item = findItemByBackendName(name);
    if (item) state.attacker.buildA[index] = item.id;
  });
  const loadoutFrom = (loadout) => ({
    champion: loadout.champion,
    level: loadout.level || 18,
    role: loadout.role || "",
    roleQuestComplete: false,
    items: [0, 0, 0, 0, 0, 0],
    itemStacks: [0, 0, 0, 0, 0, 0],
    itemOptions: [{}, {}, {}, {}, {}, {}],
    boots: 0,
    includeBoots: true,
    abilityRanks: {},
    championOptions: {},
    supportTargetSelections: {},
    allyEffectsEnabled: false,
  });
  state.targets = (payload.enemies || []).filter((enemy) => enemy.champion).map(loadoutFrom);
  state.allies = (payload.allies || []).filter((ally) => ally.champion).map(loadoutFrom);
  state.fight.rotations = Number(payload.rotations) || 1;
  state.fight.duration = Number(payload.fight_duration) || 10;
  state.fight.aaUptimeMode = payload.auto_attack_uptime_mode || "calculated";
  state.ui.objective = "overall";
  state.ui.gameState = "theory";
  QUICK_STATE.results = null;
  switchView("analyst");
  loadTrustLabels(QUICK_STATE.champion);
  render();
}

// --- Best next item ---------------------------------------------------------

async function runQuickBestNextItem() {
  if (QUICK_STATE.running) return;
  if (!QUICK_STATE.champion) {
    document.getElementById("quickChampionSearch").focus();
    return;
  }
  QUICK_STATE.running = true;
  renderQuickView();
  const spinner = document.getElementById("quickSpinner");
  spinner.hidden = false;
  const results = document.getElementById("quickResults");
  results.hidden = true;
  document.getElementById("quickAfter").hidden = true;
  const started = Date.now();
  try {
    const payload = quickCalculatePayload();
    const bisPayload = quickBisPayload();
    const [baseline, candidatesData] = await Promise.all([quickBaselineResult(payload), quickCandidates(bisPayload)]);
    if (!candidatesData.candidates.length) {
      throw new Error("No event-ordered candidates were available for this scenario.");
    }
    QUICK_STATE.results = {
      baseline,
      candidates: candidatesData.candidates,
      certified: candidatesData.certified,
      coverageNote: candidatesData.coverageNote,
      slot: bisPayload.slot_kind === "boots" ? { kind: "boots", index: 0 } : { kind: "item", index: bisPayload.slot_index },
      enemies: payload.enemies,
      payload,
    };
    const elapsed = Date.now() - started;
    spinner.querySelector("#quickSpinnerText").textContent = `Crunching the event-ordered numbers… (${Math.max(1, Math.round(elapsed / 100) / 10)}s)`;
    renderQuickResults(QUICK_STATE.results);
    spinner.hidden = true;
    results.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    spinner.hidden = true;
    results.hidden = false;
    results.innerHTML = `<div class="quick-error" role="alert"><strong>Could not compute a recommendation</strong><p>${escapeHtml(error.message || String(error))}</p><p class="quick-error-hint">Try a different champion, role, or preset.</p></div>`;
  } finally {
    QUICK_STATE.running = false;
    renderQuickView();
  }
}

// --- Sharing ----------------------------------------------------------------

async function mintShareUrl(payload, slug) {
  // /api/builds stores ability_ranks in a dedicated JSON column and rejects
  // null, while /api/calculate needs null for level-derived transform kits
  // (Elise/Jayce/Karma/Nidalee/Udyr).  Save the empty object (level-derived
  // for every kit) and let the read-only renderer restore null for those kits.
  const savedPayload = { ...payload };
  if (savedPayload.ability_ranks === null) savedPayload.ability_ranks = {};
  const saved = await postJson("/api/builds", savedPayload);
  const savedData = await saved.json();
  if (!saved.ok || savedData.error) throw new Error(savedData.error || `saving the build failed (HTTP ${saved.status})`);
  const share = await postJson("/api/share", { build_id: savedData.build_id, slug: slug || null });
  const shareData = await share.json();
  if (!share.ok || shareData.error) throw new Error(shareData.error || `minting the share link failed (HTTP ${share.status})`);
  return {
    token: shareData.token,
    buildId: savedData.build_id,
    url: `${window.location.origin}/?share=${encodeURIComponent(shareData.token)}`,
  };
}

function openSharePanel(share) {
  const panel = document.getElementById("sharePanel");
  const urlInput = document.getElementById("shareUrl");
  const status = document.getElementById("shareStatus");
  urlInput.value = share.url;
  status.textContent = "";
  panel.hidden = false;
  requestAnimationFrame(() => urlInput.select());
}

async function shareQuickBuild() {
  if (!QUICK_STATE.results) {
    await runQuickBestNextItem();
  }
  if (!QUICK_STATE.results) return;
  const status = document.getElementById("shareStatus");
  try {
    status.textContent = "Creating your share link…";
    const share = await mintShareUrl(QUICK_STATE.results.payload, "quick-build");
    QUICK_STATE.share = share;
    openSharePanel(share);
  } catch (error) {
    status.textContent = error.message;
  }
}

async function shareAnalystBuild() {
  const payload = engineFightPayload("A");
  const status = document.getElementById("shareStatus");
  try {
    status.textContent = "Creating your share link…";
    const share = await mintShareUrl(payload, "analyst-build");
    openSharePanel(share);
  } catch (error) {
    status.textContent = error.message;
  }
}

// --- Shared build rendering (?share=<token>) --------------------------------

/**
 * Present a ?share= token in the analyst view, read-only.
 *
 * The shared payload is loaded into the analyst state so the recipient sees
 * the real build and its live result, but the builder column is inert until
 * they press "Open in editor". An invalid or expired token leaves no inert
 * controls behind: the banner stays hidden and the failure is stated inline.
 */
async function renderSharedBuild(token) {
  let payload = null;
  try {
    const response = await fetch(`/api/share/${encodeURIComponent(token)}`);
    payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || "share lookup failed");
  } catch (error) {
    dismissShareBanner();
    showShareError("This shared build link is invalid or expired.");
    return;
  }
  window.__sharedBuild = payload;
  document.getElementById("shareBanner").hidden = false;
  document.getElementById("shareBannerText").textContent = `Shared build · ${payload.champion || "unknown champion"} · level ${payload.level || 18} · created ${payload.created_at || ""}`;
  try {
    loadSharedBuildIntoAnalyst(payload);
    setSharedReadOnly(true);
    loadTrustLabels(payload.champion || "");
  } catch (error) {
    showShareError(`This shared build could not be opened: ${error.message}`);
  }
}

function showShareError(message) {
  let host = document.getElementById("shareError");
  if (!host) {
    host = document.createElement("p");
    host.id = "shareError";
    host.className = "engine-error";
    const column = document.querySelector(".result-column");
    if (!column) return;
    column.prepend(host);
  }
  host.textContent = message;
}

/** Freeze or release the analyst builder while a shared build is on screen. */
function setSharedReadOnly(readOnly) {
  const analyst = document.getElementById("analystView");
  if (analyst) analyst.classList.toggle("is-shared", readOnly);
  const builder = document.querySelector(".builder-column");
  if (builder) builder.inert = readOnly;
}

function openSharedBuildInEditor() {
  const payload = window.__sharedBuild;
  if (!payload) {
    document.getElementById("shareBannerText").textContent = "This shared build is no longer available to open.";
    return;
  }
  try {
    loadSharedBuildIntoAnalyst(payload);
    setSharedReadOnly(false);
    switchView("analyst");
    document.getElementById("championPicker")?.focus();
  } catch (error) {
    document.getElementById("shareBannerText").textContent = `Could not open in editor: ${error.message}`;
  }
}

function loadSharedBuildIntoAnalyst(payload) {
  const request = payload.request || payload;
  state.attacker.champion = request.champion || "";
  state.attacker.level = Number(request.level || 18);
  state.attacker.role = request.role || "mid";
  state.attacker.roleQuestComplete = Boolean(request.role_quest_complete);
  state.attacker.comparisonEnabled = false;
  const itemIds = (request.items || []).map((name) => (findItemByBackendName(name) || {}).id || 0).filter(Boolean);
  const nextA = [0, 0, 0, 0, 0, 0];
  itemIds.slice(0, 6).forEach((id, index) => { nextA[index] = id; });
  state.attacker.buildA = nextA;
  state.attacker.buildAStacks = [0, 0, 0, 0, 0, 0];
  state.attacker.buildAItemOptions = [{}, {}, {}, {}, {}, {}];
  const bootName = request.boots || "";
  const bootId = bootName ? (findItemByBackendName(bootName) || {}).id || 0 : 0;
  state.attacker.questBootA = bootId;
  state.attacker.includeBootsA = bootName ? Boolean(bootId) : true;
  state.attacker.keystoneA = "";
  state.attacker.keystoneOptionsA = {};
  state.attacker.abilityInputs = {};
  state.attacker.championOptions = {};
  state.attacker.supportTargetSelections = { ...(request.support_target_selections || {}) };
  // Restore the authored rank allocation so the analyst engine scores the
  // shared build identically.  An empty object (what the save endpoint stores
  // for level-derived kits) means "use level-derived defaults": seed them via
  // syncAbilityInputsToLevel for regular kits; transform kits keep empty
  // inputs and the backend applies its own level order.
  let appliedRanks = false;
  if (request.ability_ranks && typeof request.ability_ranks === "object") {
    activeAbilityKit().forEach((ability) => {
      if (ability.slot === "P") return;
      const rank = Number(request.ability_ranks[ability.slot] || 0);
      if (rank > 0) {
        state.attacker.abilityInputs[ability.slot] = { ...abilityInput(ability.slot), rank };
        appliedRanks = true;
      }
    });
  }
  if (!appliedRanks && !usesLevelDerivedRanks(state.attacker.champion)) {
    syncAbilityInputsToLevel();
  }
  const fillSide = (roster, entries) => {
    roster.length = 0;
    (entries || []).forEach((entry) => {
      const ids = [0, 0, 0, 0, 0, 0];
      (entry.items || []).map((name) => (findItemByBackendName(name) || {}).id || 0).filter(Boolean).slice(0, 6).forEach((id, index) => { ids[index] = id; });
      const rosterBoot = (findItemByBackendName(entry.boots || "") || {}).id || 0;
      roster.push({
        champion: entry.champion || "",
        level: Number(entry.level || 18),
        role: entry.role || "",
        roleQuestComplete: Boolean(entry.role_quest_complete),
        items: ids,
        itemStacks: [0, 0, 0, 0, 0, 0],
        itemOptions: [{}, {}, {}, {}, {}, {}],
        boots: rosterBoot,
        includeBoots: entry.include_boots !== false,
        abilityRanks: {},
        championOptions: {},
        supportTargetSelections: entry.support_target_selections || {},
        allyEffectsEnabled: entry.ally_effects_enabled !== false,
      });
    });
  };
  fillSide(state.targets, request.enemies || []);
  fillSide(state.allies, request.allies || []);
  const fightParams = request.fight_params || request;
  state.fight.rotations = Number(fightParams.rotations || 1);
  state.fight.duration = Number(fightParams.fight_duration || 10);
  state.fight.aaUptimeMode = fightParams.auto_attack_uptime_mode || "calculated";
  state.fight.aaUptime = Number(fightParams.auto_attack_uptime || 0);
  engine.responses = null;
  // A shared build was authored under one role-quest state; re-normalize the
  // restored quest boot and support items so an illegal stage never renders
  // in the editor.  The backend remains the authority for the tier contract.
  normalizeAttackerBootsForRole();
  normalizeAttackerSupportItemsForRole();
  render();
}

// --- View switching ---------------------------------------------------------

// Quick mode was removed in 2026-08; the analyst view is the app. Every hop
// here is guarded so a template without the quick shell (the shipped one)
// still switches cleanly instead of throwing on a missing node (#147).
function switchView(view) {
  const quick = document.getElementById("quickView");
  const analyst = document.getElementById("analystView");
  const quickTab = document.getElementById("viewQuickTab");
  const analystTab = document.getElementById("viewAnalystTab");
  const select = (tab, selected) => {
    if (!tab) return;
    tab.classList.toggle("active", selected);
    tab.setAttribute("aria-selected", String(selected));
  };
  if (view === "analyst" || !quick) {
    if (quick) quick.hidden = true;
    if (analyst) analyst.hidden = false;
    select(quickTab, false);
    select(analystTab, true);
    requestAnimationFrame(() => scheduleEngineCalculation());
  } else {
    if (analyst) analyst.hidden = true;
    quick.hidden = false;
    select(analystTab, false);
    select(quickTab, true);
    renderQuickView();
  }
  window.scrollTo({ top: 0 });
}

// --- Quick mode event wiring ------------------------------------------------

function bindQuickEvents() {
  // The Quick/Analyst tab bar was removed (product decision 2026-08-06): the
  // analyst view is the app. Guard for templates that still carry the tabs.
  const quickTab = document.getElementById("viewQuickTab");
  const analystTab = document.getElementById("viewAnalystTab");
  if (quickTab) quickTab.addEventListener("click", () => switchView("quick"));
  if (analystTab) analystTab.addEventListener("click", () => switchView("analyst"));

  const championSearch = document.getElementById("quickChampionSearch");
  championSearch.addEventListener("input", () => renderQuickChampionGrid(championSearch.value));
  const enemySearch = document.getElementById("quickEnemySearch");
  enemySearch.addEventListener("input", () => renderQuickEnemyGrid(enemySearch.value));
  const itemSearch = document.getElementById("quickItemSearch");
  itemSearch.addEventListener("input", () => renderQuickItemGrid(itemSearch.value));

  document.getElementById("quickChampionGrid").addEventListener("click", (event) => {
    const button = event.target.closest("[data-quick-pick='champion']");
    if (!button) return;
    QUICK_STATE.champion = button.dataset.value;
    loadTrustLabels(QUICK_STATE.champion);
    renderQuickChampionGrid(championSearch.value);
    renderQuickView();
  });

  document.getElementById("quickEnemyGrid").addEventListener("click", (event) => {
    const button = event.target.closest("[data-quick-pick='enemy']");
    if (!button) return;
    if (!button.dataset.value) {
      QUICK_STATE.enemy = null;
    } else {
      const champion = quickChampionEntries().find((entry) => entry.name === button.dataset.value);
      QUICK_STATE.enemy = champion
        ? { champion: champion.name, level: 18, role: "top", items: [] }
        : { champion: button.dataset.value, level: 18, role: "top", items: [] };
    }
    renderQuickEnemyGrid(enemySearch.value);
    renderQuickView();
  });
  document.getElementById("quickEnemyClear").addEventListener("click", () => {
    QUICK_STATE.enemy = null;
    enemySearch.value = "";
    renderQuickEnemyGrid("");
    renderQuickView();
  });

  document.getElementById("quickItemGrid").addEventListener("click", (event) => {
    const button = event.target.closest("[data-quick-pick='item']");
    if (!button) return;
    if (QUICK_STATE.items.length >= QUICK_MAX_ITEMS) return;
    QUICK_STATE.items.push(button.dataset.value);
    itemSearch.value = "";
    renderQuickItemsStrip();
    renderQuickItemGrid("");
  });
  document.getElementById("quickItems").addEventListener("click", (event) => {
    const remove = event.target.closest("[data-quick-remove]");
    if (!remove) return;
    QUICK_STATE.items = QUICK_STATE.items.filter((name) => name !== remove.dataset.quickRemove);
    renderQuickItemsStrip();
    renderQuickItemGrid(itemSearch.value);
  });

  document.getElementById("quickRole").addEventListener("click", (event) => {
    const button = event.target.closest("[data-quick-role]");
    if (!button) return;
    QUICK_STATE.role = button.dataset.quickRole;
    renderQuickRole();
  });

  document.getElementById("quickPresets").addEventListener("click", (event) => {
    const button = event.target.closest("[data-quick-preset]");
    if (!button) return;
    QUICK_STATE.presetId = QUICK_STATE.presetId === button.dataset.quickPreset ? null : button.dataset.quickPreset;
    renderQuickPresets();
  });

  document.getElementById("quickRun").addEventListener("click", runQuickBestNextItem);
  document.getElementById("quickShareButton").addEventListener("click", shareQuickBuild);
  document.getElementById("quickAnalystButton").addEventListener("click", openQuickInAnalyst);
}

// --- Share controls ---------------------------------------------------------

/**
 * Wire every build-sharing control and honor a ?share= token.
 *
 * Issue #147: this wiring used to live inside bindQuickEvents(), which
 * initQuickView() skips whenever #quickView is absent — and quick mode was
 * removed in 2026-08. That left the shared-build banner's "Open in editor"
 * and dismiss controls, the share panel, and the ?share= read all dead on the
 * shipped template. Sharing is its own concern with its own initializer, and
 * it depends on nothing but the analyst view.
 */
function initShareControls() {
  const openEditor = document.getElementById("shareOpenEditor");
  if (openEditor) openEditor.addEventListener("click", openSharedBuildInEditor);

  const dismiss = document.getElementById("shareDismiss");
  if (dismiss) {
    dismiss.addEventListener("click", () => {
      dismissShareBanner();
      const url = new URL(window.location.href);
      url.searchParams.delete("share");
      window.history.replaceState({}, "", url);
    });
  }

  const shareButton = document.getElementById("shareAnalystButton");
  if (shareButton) shareButton.addEventListener("click", shareAnalystBuild);

  const panelClose = document.getElementById("sharePanelClose");
  if (panelClose) {
    panelClose.addEventListener("click", () => { document.getElementById("sharePanel").hidden = true; });
  }

  const copyButton = document.getElementById("shareCopy");
  if (copyButton) {
    copyButton.addEventListener("click", async () => {
      const urlInput = document.getElementById("shareUrl");
      const status = document.getElementById("shareStatus");
      try {
        await navigator.clipboard.writeText(urlInput.value);
        status.textContent = "Copied to clipboard";
      } catch (error) {
        urlInput.select();
        status.textContent = "Select the link and copy it manually.";
      }
    });
  }

  const params = new URLSearchParams(window.location.search);
  const shareToken = params.get("share");
  // The controls above bind immediately — that is the whole point of #147 —
  // but applying the payload has to wait for the patch snapshot: it resolves
  // champion and item *names* against the catalogue, and an empty catalogue
  // would silently drop every item from the shared build.
  if (shareToken) whenEngineReady(() => renderSharedBuild(shareToken));
}

/** Run ``callback`` once the patch snapshot is loaded (now, or on ready). */
function whenEngineReady(callback) {
  if (DATA.champions.length && engine.itemCatalogReady) {
    callback();
    return;
  }
  document.addEventListener("scryglass:engine-ready", callback, { once: true });
}

function dismissShareBanner() {
  const banner = document.getElementById("shareBanner");
  if (banner) banner.hidden = true;
}

// --- Boot -------------------------------------------------------------------

async function initQuickView() {
  if (QUICK_INIT_STARTED) return;
  QUICK_INIT_STARTED = true;
  if (!document.getElementById("quickView")) return; // quick mode removed (2026-08-06)
  try {
    const response = await fetch("/static/quick-presets.json");
    if (!response.ok) throw new Error("presets failed to load");
    const data = await response.json();
    QUICK_PRESETS = Array.isArray(data?.presets) ? data.presets : [];
  } catch (error) {
    QUICK_PRESETS = [];
  }
  QUICK_VIEW_READY = true;
  bindQuickEvents();
  renderQuickView();
  // Share handling lives in initShareControls(); quick view only needs to
  // hand the analyst view its trust labels.
  if (state.attacker.champion) loadTrustLabels(state.attacker.champion);
}

document.addEventListener("scryglass:engine-ready", () => {
  if (!QUICK_VIEW_READY) initQuickView();
  if (document.getElementById("quickView")) renderQuickView();
  loadTrustLabels(state.attacker.champion || QUICK_STATE.champion || "");
});

// Boot the quick view immediately so its controls are live even before the
// patch snapshot finishes loading; grids repopulate on engine-ready.
initQuickView();
// Sharing boots unconditionally — it is not a quick-view feature (#147).
initShareControls();

// Patch the analyst champion selection so trust labels follow the analyst view.
const _originalRenderPrototypeChampion = renderPrototypeChampion;
renderPrototypeChampion = function (...args) {
  const result = _originalRenderPrototypeChampion.apply(this, args);
  const champion = state.attacker.champion;
  if (champion && !CERTAINTY_STATE.loading) loadTrustLabels(champion);
  return result;
};

// Hook the engine-ready signal into the existing bootstrap.
if (typeof window.__scryglassEngineReadyHook === "undefined") {
  window.__scryglassEngineReadyHook = true;
  const _originalRender = render;
  render = function (...args) {
    const result = _originalRender.apply(this, args);
    document.dispatchEvent(new Event("scryglass:engine-ready"));
    return result;
  };
}


// Temporary local design-review mode. It is opt-in via ?review=1 and has no
// effect on the calculator's normal interaction or persisted calculation state.
(function initDesignReview() {
  const params = new URLSearchParams(window.location.search);
  if (!params.has("review")) return;

  const storageKey = `scryglass-design-review:${window.location.pathname}`;
  let savedNotes = [];
  try { savedNotes = JSON.parse(localStorage.getItem(storageKey) || "[]"); } catch { savedNotes = []; }
  const state = {
    armed: false,
    suppressClick: false,
    target: null,
    editing: null,
    notes: Array.isArray(savedNotes) ? savedNotes : [],
  };
  const review = document.createElement("div");
  review.className = "design-review-ui";
  review.innerHTML = `<div class="design-review-toolbar" role="toolbar" aria-label="Design review tools">
    <strong>Design review</strong><span class="design-review-count">0 notes</span>
    <button type="button" data-review-action="arm">Add note</button>
    <button type="button" data-review-action="export">Export</button>
    <button type="button" data-review-action="copy">Copy Markdown</button>
    <button type="button" data-review-action="clear">Clear</button>
    <a href="${window.location.pathname}" data-review-action="exit">Exit</a>
  </div>
  <div class="design-review-editor" hidden>
    <div class="design-review-editor-head"><strong class="design-review-editor-title">New note</strong><button type="button" data-review-action="cancel" aria-label="Close note editor">×</button></div>
    <p class="design-review-target-summary"></p>
    <label>What is wrong?<textarea data-review-field="problem" rows="3" placeholder="e.g. This label is too faint against the map."></textarea></label>
    <label>Expected / reference<textarea data-review-field="expected" rows="2" placeholder="e.g. Match the prototype: white, bold, 14px."></textarea></label>
    <label>Priority<select data-review-field="priority"><option value="high">High</option><option value="medium" selected>Medium</option><option value="low">Low</option></select></label>
    <div class="design-review-editor-actions"><button type="button" data-review-action="cancel">Cancel</button><button type="button" data-review-action="save">Save note</button></div>
  </div>
  <div class="design-review-pins" aria-hidden="true"></div>`;
  document.body.append(review);

  const editor = review.querySelector(".design-review-editor");
  const pins = review.querySelector(".design-review-pins");
  const count = review.querySelector(".design-review-count");
  const armButton = review.querySelector('[data-review-action="arm"]');
  const field = (name) => review.querySelector(`[data-review-field="${name}"]`);

  const persist = () => localStorage.setItem(storageKey, JSON.stringify(state.notes));
  const escapeSelector = (value) => {
    if (window.CSS?.escape) return CSS.escape(value);
    return String(value).replace(/([ #;?%&,.+*~':!^$[\]()=>|/@])/g, "\\$1");
  };
  const selectorFor = (element) => {
    if (element.id) return `#${escapeSelector(element.id)}`;
    const parts = [];
    let node = element;
    while (node && node !== document.body && node.nodeType === 1) {
      let part = node.tagName.toLowerCase();
      const classes = [...node.classList].filter((name) => !name.startsWith("design-review"));
      if (classes.length) part += `.${classes.slice(0, 2).map(escapeSelector).join(".")}`;
      const siblings = node.parentElement ? [...node.parentElement.children].filter((child) => child.tagName === node.tagName) : [];
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(" > ") || element.tagName.toLowerCase();
  };
  const targetFor = (element) => element.closest("button,select,input,textarea,label,section,article,aside,h1,h2,h3,p,.stat,.slot") || element;
  const textFor = (element) => (element.getAttribute("aria-label") || element.innerText || element.textContent || "").replace(/\s+/g, " ").trim().slice(0, 180);
  const highlight = (element) => {
    document.querySelectorAll(".design-review-target").forEach((node) => node.classList.remove("design-review-target"));
    element?.classList.add("design-review-target");
  };
  const locate = (note) => {
    try { return document.querySelector(note.selector); } catch { return null; }
  };
  const updateCount = () => { count.textContent = `${state.notes.length} ${state.notes.length === 1 ? "note" : "notes"}`; };
  const renderPins = () => {
    pins.replaceChildren();
    state.notes.forEach((note, index) => {
      const element = locate(note);
      const rect = element?.getBoundingClientRect();
      const pin = document.createElement("button");
      pin.type = "button";
      pin.className = `design-review-pin priority-${note.priority || "medium"}`;
      pin.dataset.reviewIndex = String(index);
      pin.textContent = String(index + 1);
      pin.title = note.problem || `Review note ${index + 1}`;
      pin.style.left = `${rect ? rect.left + Math.min(rect.width, 28) : note.rect.x - window.scrollX}px`;
      pin.style.top = `${rect ? Math.max(8, rect.top - 12) : note.rect.y - window.scrollY}px`;
      pins.append(pin);
    });
    updateCount();
  };
  const closeEditor = () => {
    editor.hidden = true;
    highlight(null);
    state.target = null;
    state.editing = null;
  };
  const openEditor = (element, note = null) => {
    state.target = element || locate(note);
    state.editing = note;
    highlight(state.target);
    review.querySelector(".design-review-editor-title").textContent = note ? `Edit note ${state.notes.indexOf(note) + 1}` : "New note";
    review.querySelector(".design-review-target-summary").textContent = state.target ? `${state.target.tagName.toLowerCase()} · ${selectorFor(state.target)}\n“${textFor(state.target)}”` : "Target is no longer present in this state.";
    field("problem").value = note?.problem || "";
    field("expected").value = note?.expected || "";
    field("priority").value = note?.priority || "medium";
    editor.hidden = false;
    field("problem").focus();
  };
  const markdown = () => `# Scryglass design review\n\n${state.notes.map((note, index) => `## ${index + 1}. ${note.priority.toUpperCase()}\n- **Problem:** ${note.problem}\n- **Expected:** ${note.expected || "Not specified"}\n- **Target:** \`${note.selector}\`\n- **Viewport:** ${note.viewport.width}×${note.viewport.height}\n- **Snapshot:** ${note.snapshot || "(no visible text)"}\n`).join("\n")}`;
  const download = (filename, content, type) => {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  };
  const saveNote = () => {
    const problem = field("problem").value.trim();
    if (!problem) { field("problem").focus(); return; }
    const rect = state.target?.getBoundingClientRect();
    const note = state.editing || {};
    Object.assign(note, {
      problem,
      expected: field("expected").value.trim(),
      priority: field("priority").value,
      selector: state.target ? selectorFor(state.target) : note.selector,
      snapshot: state.target ? textFor(state.target) : note.snapshot,
      rect: { x: rect ? rect.left + window.scrollX : note.rect?.x || 0, y: rect ? rect.top + window.scrollY : note.rect?.y || 0, width: rect?.width || note.rect?.width || 0, height: rect?.height || note.rect?.height || 0 },
      viewport: { width: window.innerWidth, height: window.innerHeight },
      path: window.location.pathname + window.location.search,
      updatedAt: new Date().toISOString(),
    });
    if (!state.editing) state.notes.push(note);
    persist();
    closeEditor();
    renderPins();
  };

  review.addEventListener("click", (event) => {
    const action = event.target.closest("[data-review-action]")?.dataset.reviewAction;
    if (!action) return;
    if (action === "arm") {
      state.armed = !state.armed;
      armButton.classList.toggle("active", state.armed);
      armButton.textContent = state.armed ? "Click an element…" : "Add note";
    } else if (action === "export") {
      download("scryglass-design-review.json", JSON.stringify({ exportedAt: new Date().toISOString(), url: window.location.href, notes: state.notes }, null, 2), "application/json");
    } else if (action === "copy") {
      const copied = navigator.clipboard?.writeText(markdown());
      if (copied) copied.then(() => { event.target.textContent = "Copied"; setTimeout(() => { event.target.textContent = "Copy Markdown"; }, 1200); });
      else download("scryglass-design-review.md", markdown(), "text/markdown");
    } else if (action === "clear" && state.notes.length && window.confirm("Clear all design review notes for this page?")) {
      state.notes = [];
      persist();
      renderPins();
    } else if (action === "cancel") {
      closeEditor();
    } else if (action === "save") {
      saveNote();
    }
  });
  review.addEventListener("click", (event) => {
    const pin = event.target.closest("[data-review-index]");
    if (pin) openEditor(null, state.notes[Number(pin.dataset.reviewIndex)]);
  });
  document.addEventListener("pointerdown", (event) => {
    if (!state.armed || event.target.closest(".design-review-ui")) return;
    const element = targetFor(event.target);
    if (!element || element === document.body || element === document.documentElement) return;
    event.preventDefault();
    event.stopPropagation();
    state.armed = false;
    state.suppressClick = true;
    armButton.classList.remove("active");
    armButton.textContent = "Add note";
    openEditor(element);
  }, true);
  document.addEventListener("click", (event) => {
    if (!state.suppressClick) return;
    state.suppressClick = false;
    event.preventDefault();
    event.stopPropagation();
  }, true);
  window.addEventListener("resize", renderPins);
  window.addEventListener("scroll", renderPins, { passive: true });
  renderPins();
})();

// --- First-run onboarding overlay (P1a) -------------------------------------
// Additive and self-contained: drives the 3-step welcome tour markup in
// templates/index.html once per browser, keyed on localStorage
// "scryglass_onboarded". Never blocks — Skip / × / Escape all persist the
// flag — and motion stays CSS-driven so prefers-reduced-motion can disable
// it. If storage is unavailable the tour stays silent (no nagging every
// load), and if the markup is missing nothing happens.
(function initOnboardingOverlay() {
  "use strict";

  const ONBOARDING_KEY = "scryglass_onboarded";
  const overlay = document.getElementById("onboardingOverlay");
  if (!overlay) return;

  let seen = false;
  try {
    seen = localStorage.getItem(ONBOARDING_KEY) === "1";
  } catch (error) {
    return; // storage blocked — never show a tour we cannot remember
  }
  if (seen) return;

  const steps = Array.prototype.slice.call(overlay.querySelectorAll(".onboarding-step"));
  const dots = Array.prototype.slice.call(overlay.querySelectorAll(".onboarding-dots span"));
  const counter = overlay.querySelector(".onboarding-counter");
  const nextButton = overlay.querySelector(".onboarding-next");
  const backButton = overlay.querySelector(".onboarding-back");
  const skipButton = overlay.querySelector(".onboarding-skip");
  const closeButton = overlay.querySelector(".onboarding-close");
  const TOTAL = steps.length;
  let current = 0;

  function persistDismissal() {
    try {
      localStorage.setItem(ONBOARDING_KEY, "1");
    } catch (error) {
      // Best effort: the tour is dismissible either way.
    }
  }

  function dismiss() {
    overlay.hidden = true;
    overlay.classList.remove("is-open");
    document.body.classList.remove("onboarding-locked");
    document.removeEventListener("keydown", onKeyDown);
  }

  function finish() {
    persistDismissal();
    dismiss();
  }

  function showStep(index) {
    if (!steps.length) return;
    current = Math.max(0, Math.min(TOTAL - 1, index));
    steps.forEach((step, i) => {
      const active = i === current;
      step.classList.toggle("is-active", active);
      step.hidden = !active;
    });
    dots.forEach((dot, i) => dot.classList.toggle("is-active", i === current));
    if (counter) counter.textContent = `${current + 1} of ${TOTAL}`;
    if (backButton) backButton.hidden = current === 0;
    if (nextButton) {
      const last = current === TOTAL - 1;
      nextButton.textContent = last ? "Start building" : "Next";
      nextButton.setAttribute("aria-label", last ? "Start using Scryglass" : "Next step");
    }
  }

  function onKeyDown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      finish();
    } else if (event.key === "ArrowRight" && current < TOTAL - 1) {
      event.preventDefault();
      showStep(current + 1);
    } else if (event.key === "ArrowLeft" && current > 0) {
      event.preventDefault();
      showStep(current - 1);
    }
  }

  function open() {
    overlay.hidden = false;
    overlay.classList.add("is-open");
    document.body.classList.add("onboarding-locked");
    showStep(0);
    if (nextButton) nextButton.focus();
    document.addEventListener("keydown", onKeyDown);
  }

  if (nextButton) {
    nextButton.addEventListener("click", () => {
      if (current < TOTAL - 1) showStep(current + 1);
      else finish();
    });
  }
  if (backButton) backButton.addEventListener("click", () => showStep(current - 1));
  if (skipButton) skipButton.addEventListener("click", finish);
  if (closeButton) closeButton.addEventListener("click", finish);

  // Wait one frame so the page paints behind the tour before it opens.
  window.setTimeout(open, 150);
})();
