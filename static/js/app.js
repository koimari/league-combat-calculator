const DDRAGON = "https://ddragon.leagueoflegends.com/cdn/16.15.1/img";

let DATA = { champions: [], items: [] };
let BIS_PROFILES = {};
let EFFECT_CATALOG = {};
let pickerContext = null;
let bisContext = null;
const ABILITY_SLOTS = ["P", "Q", "W", "E", "R"];
const PRACTICE_DUMMY_KIND = "practice_dummy";
const PRACTICE_DUMMY_NAME = "Practice Dummy";
const PRACTICE_DUMMY_IMAGE = "/static/img/practice-dummy-enemy.png";
const PRACTICE_DUMMY_LEVEL = 18;
const PRACTICE_DUMMY_STATS = Object.freeze({
  health: 1000,
  bonus_health: 0,
  armor: 100,
  magic_resistance: 100,
  attack_damage: 0,
  ability_power: 0,
  attack_speed: 1,
  ability_haste: 0,
  move_speed: 325,
  critical_strike_chance: 0,
  max_mana: 0,
});
const PRACTICE_DUMMY_STAT_FIELDS = [
  ["health", "Health", "0.1", "1", "100000"],
  ["bonus_health", "Bonus health", "0.1", "0", "100000"],
  ["armor", "Armor", "0.1", "0", "10000"],
  ["magic_resistance", "Magic resistance", "0.1", "0", "10000"],
  ["attack_damage", "Attack damage", "0.1", "0", "100000"],
  ["ability_power", "Ability power", "0.1", "0", "100000"],
  ["attack_speed", "Attack speed", "0.01", "0", "100"],
  ["ability_haste", "Ability haste", "0.1", "0", "10000"],
  ["move_speed", "Move speed", "0.1", "0", "10000"],
  ["critical_strike_chance", "Critical strike chance", "0.1", "0", "100"],
  ["max_mana", "Maximum mana", "0.1", "0", "100000"],
];
const engine = {
  ready: false,
  reviewed: new Set(),
  backend: new Set(),
  availability: new Map(),
  itemOptions: {},
  championOptions: {},
  keystones: [],
  defaultTarget: { health: 1000, bonus_health: 0, armor: 100, mr: 100 },
  fightDefaults: {},
  exclusivityGroups: {},
  roleQuest: {},
  domainContract: {},
  boots: [],
  bootIds: new Set(),
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
    // Rail disclosure. At most one setup step and one constraints row are
    // open at a time; opening a step widens the rail and dims the canvas
    // (target-2b). `activeStep` is the step the canvas is currently
    // answering for, marked ACTIVE in the collapsed rail (target-2a).
    expandedStep: null,
    expandedConstraint: null,
    activeStep: "roster",
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
    comparisonEnabled: false,
    baseDamage: 0,
    apRatio: 0,
    physicalDamage: 0,
    adRatio: 0,
    abilityInputs: {},
    championOptions: {},
  },
  targets: [],
  allies: [],
  fight: { rotations: 1, duration: 10, aaUptime: 0, aaUptimeMode: "calculated", enemiesAttack: true },
  optimizer: { running: false, summary: null, scope: null, rosterErrors: {}, availableGold: 0 },
};

let OBJECTIVES = {};
let SPINE_METRICS = [];
let OBJECTIVE_UNITS = {};

function applyDomainContract(contract) {
  engine.domainContract = contract || {};
  OBJECTIVES = engine.domainContract.bis_objectives || {};
  OBJECTIVE_UNITS = Object.fromEntries(
    Object.entries(OBJECTIVES).map(([key, definition]) => [key, definition.unit || ""]),
  );
  SPINE_METRICS = Object.entries(OBJECTIVES).map(([key, definition]) => ({
    key,
    label: definition.label || key,
    unit: definition.unit || "",
    lower: definition.direction === "lower",
  }));
}

function domainValue(group, key, role, complete) {
  const contract = engine.domainContract?.[group]?.[key];
  const stateKey = complete ? "complete" : "incomplete";
  const value = contract?.by_role?.[role]?.[stateKey] ?? contract?.default;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function roleLevelCap(role, complete, currentLevel = 1) {
  return domainValue("role_quest", "level_cap", role || "", complete)
    ?? Math.max(1, Number(currentLevel) || 1);
}

function roleInventoryCapacity(role, complete, currentCount = 0) {
  return domainValue("role_quest", "inventory_capacity", role || "", complete)
    ?? Math.max(0, Number(currentCount) || 0);
}

function roleBootsTier(role, complete) {
  return domainValue("role_quest", "boots_tier", role || "", complete);
}

function isRoleBoot(id) {
  return engine.bootIds.has(Number(id));
}

function bootIdsForTier(tier) {
  if (!Number.isFinite(Number(tier))) return [];
  return engine.boots
    .filter((item) => Number(item.tier) === Number(tier))
    .map((item) => Number(item.id))
    .filter((id) => Number.isFinite(id) && id > 0);
}

function objectiveDefinition(key) {
  return OBJECTIVES[key] || null;
}

function selectedObjectiveDefinition() {
  return objectiveDefinition(state.ui.objective)
    || Object.values(OBJECTIVES)[0]
    || {};
}

function usesLevelDerivedRanks(championName) {
  const modes = engine.domainContract?.rank_allocation || {};
  return modes.by_champion?.[String(championName || "")] === "level_derived";
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
// Phase 4 S9's one budgeted UI change: how a *withheld* leaf renders.
//
// A payload publishes numbers plus a parallel `dispositions` map keyed by leaf
// path. Measured and structurally-zero leaves are unchanged bare numbers and
// every renderer below reads them exactly as before. A WITHHELD leaf is
// different in kind: coverage refused to model it, so the payload carries no
// number for it at all and the map carries the receipts instead.
//
// Rendering that as a blank, a 0 or a NaN is the failure this whole campaign
// is named after — a number nobody computed made indistinguishable from one
// computed as zero. So it renders as a named refusal, in one place, and every
// caller reaches it through `leafText`.
// Why a leaf carries no number, in one sentence. Separate from the markup
// below because two surfaces need the same words in two shapes: a rendered
// cell needs the marker, a title attribute and an accessible name need the
// sentence. One place decides what it says; each caller decides how.
const withheldReason = (entry) => {
  const receipts = (entry && entry.receipts) || [];
  return receipts.length ? receipts.join("; ") : "no receipt was published";
};
const withheldMarker = (entry) =>
  `<span class="leaf-withheld" title="${escapeHtml(withheldReason(entry))}">withheld</span>`;
// One published leaf, rendered: the number when there is one, the named
// refusal when the model declined to produce one.
const leafText = (value, path, dispositions, format = fmt) => {
  const entry = dispositions ? dispositions[path] : null;
  if (entry && entry.disposition === "WITHHELD") return withheldMarker(entry);
  if (value == null) return withheldMarker(entry);
  return escapeHtml(format(value));
};
// Where one participant's survival leaf lives in the combat payload, so a
// renderer can ask the map about the number it is about to print. The
// participants list and the map's `participants[i]` index are the same list.
const survivalLeafPath = (index, leaf) => `participants[${index}].survival.${leaf}`;
// Whether the payload refused to produce this leaf rather than measuring it.
// A refused leaf is *absent*, so `?? 0` would read it as a computed zero —
// which is the failure this whole campaign is named after, and the reason a
// total over a refused member is refused too rather than quietly short.
const leafWithheld = (path, dispositions) =>
  Boolean(dispositions && dispositions[path] && dispositions[path].disposition === "WITHHELD");
const withheldEntry = (paths, dispositions) =>
  (dispositions && paths.map((path) => dispositions[path]).find((entry) => entry && entry.disposition === "WITHHELD")) || null;

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

// Display-only numeric fields the patch snapshot carries and /api/items
// currently zeroes. The coverage endpoint answers "is this item modelled",
// not "what does it give you", so a 0 there means "not reported", never
// "the item lost this stat" — merging it verbatim blanked every item's stat
// line and price in the UI.
const SNAPSHOT_NUMERIC_FIELDS = [
  "price", "ap", "ad", "hp", "mana", "armor", "mr", "haste", "pen", "percentPen",
  "lethality", "percentArmorPen", "attackSpeed", "crit", "critDamage", "lifesteal",
  "omnivamp", "healAndShieldPower", "healthRegen", "manaRegen", "goldPer10",
  "tenacity", "moveSpeed", "tier",
];

function preferReportedNumbers(snapshotItem, metadata) {
  return Object.fromEntries(SNAPSHOT_NUMERIC_FIELDS.map((field) => [
    field,
    Number(metadata[field]) ? metadata[field] : snapshotItem[field],
  ]));
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
      ...preferReportedNumbers(item, metadata),
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
    else if (equipped >= roleInventoryCapacity(
      state.attacker.role,
      Boolean(state.attacker.roleQuestComplete),
      equipped,
    )) block = "Build A inventory is full.";
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
  banner.setAttribute("aria-label", "Analytics consent");
  // The look lives in static/css/style.css (.consent-banner) with the rest of
  // the design language; this only owns the copy and the two answers.
  banner.innerHTML =
    '<span>Allow anonymous usage stats to improve Scryglass? No personal data is collected.</span>' +
    '<button type="button" id="consentYes">Yes</button>' +
    '<button type="button" id="consentNo">No</button>';
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
  if (slot !== "R") {
    const toggle = Object.keys(GLOBAL_FORM_TOGGLES).find((key) => declared.has(key));
    if (toggle) return toggle;
    if (declared.has("stance")) return "stance";
  }
  // A generic variant-family option for the slot (e.g. q_variant on Heimer).
  const family = [...declared].find((key) =>
    key.startsWith(slotKey) && /variant|stance|mode|form|style/.test(key)
  );
  return family || null;
}

// Bool form toggles driven by the ability Variant buttons, mapped to the
// variant index that means "true".  The backend types these as booleans, so
// the payload must never carry the raw variant index (sending Gnar's
// ``mega: 0`` produced "champion_options.mega must be true or false" the
// moment he was selected).  Gnar's forms list Mini first (Mega = index 1);
// Jayce's hammer kit is the wiki's first entry (hammer_stance = index 0,
// cannon second).
const GLOBAL_FORM_TOGGLES = { "mega": 1, "hammer_stance": 0 };

/**
 * The variant index a slot starts on: the one matching its bound form
 * toggle's module default.  Variant 0 is Jayce's hammer kit, but his module
 * defaults hammer_stance to false (cannon) — a fresh pick must not flip the
 * form.  Slots without a bound form toggle start on their first variant.
 */
function defaultFormVariantIndex(slot) {
  const binding = abilityOptionBinding(slot, "ability_variants");
  if (!(binding in GLOBAL_FORM_TOGGLES)) return 0;
  const option = (engine.championOptions[state.attacker.champion]?.options || [])
    .find((entry) => entry.key === binding);
  const trueIndex = GLOBAL_FORM_TOGGLES[binding];
  return option?.default ? trueIndex : 1 - trueIndex;
}

/**
 * Mirror one slot's Variant selection onto every slot bound to the same
 * global form toggle.  Q/W/E all bind the toggle, but the payload reads the
 * first bound slot only — without the mirror, clicking Boulder Toss on Q
 * would leave W/E rendering (and the user reading) the Mini kit.
 */
function syncGlobalFormVariants(slot, variantIndex) {
  const binding = abilityOptionBinding(slot, "ability_variants");
  if (!(binding in GLOBAL_FORM_TOGGLES)) return;
  activeAbilityKit().forEach((ability) => {
    if (ability.slot === slot || !(ability.variants?.length > 1)) return;
    if (abilityOptionBinding(ability.slot, "ability_variants") !== binding) return;
    const input = abilityInput(ability.slot);
    input.variant = Math.min(variantIndex, ability.variants.length - 1);
    state.attacker.abilityInputs[ability.slot] = input;
  });
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
    variant: defaultFormVariantIndex(ability.slot),
  }]));
}

function resetChampionOptions() {
  const definitions = engine.championOptions[state.attacker.champion]?.options || [];
  state.attacker.championOptions = Object.fromEntries(
    definitions.map((option) => [option.key, option.default]),
  );
}

function resetRosterChampionOptions(loadout) {
  const definitions = engine.championOptions[loadout?.champion]?.options || [];
  loadout.championOptions = Object.fromEntries(
    definitions.map((option) => [option.key, option.default]),
  );
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

function isPracticeDummy(loadout) {
  return Boolean(
    loadout?.kind === PRACTICE_DUMMY_KIND
      || loadout?.isPracticeDummy
      || loadout?.champion === PRACTICE_DUMMY_NAME,
  );
}

function practiceDummyStatValue(loadout, key) {
  const value = Number(loadout?.targetStats?.[key]);
  return Number.isFinite(value) ? value : Number(PRACTICE_DUMMY_STATS[key] || 0);
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
  if (!item) return null;
  const requiredTier = roleBootsTier(role, complete);
  if (!Number.isFinite(requiredTier)) return item.name;
  const currentTier = Number(item.tier);
  if (currentTier === requiredTier) return item.name;
  return currentTier > requiredTier
    ? (item.upgradeFrom || item.name)
    : (item.upgradeTo || item.name);
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
  const requiredTier = roleBootsTier(loadout.role, Boolean(loadout.roleQuestComplete));
  if (!Number.isFinite(requiredTier)) return;
  const currentTier = Number(item.tier);
  const targetName = currentTier === requiredTier
    ? item.name
    : currentTier > requiredTier
      ? (item.upgradeFrom || item.name)
      : (item.upgradeTo || item.name);
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
  if (parts.at(-1) === "items" && isRoleBoot(nextValue)) {
    const index = Number(parts[1]);
    if (parts[0] === "targets" || parts[0] === "allies") {
      const loadout = state[parts[0]]?.[index];
      if (loadout) {
        if (isPracticeDummy(loadout)) {
          loadout.boots = 0;
          loadout.includeBoots = false;
          parent[Number(last)] = 0;
          invalidateOptimization();
          return;
        }
        loadout.boots = Number(nextValue);
        loadout.includeBoots = true;
        parent[Number(last)] = 0;
        if (loadout.itemOptions) loadout.itemOptions[Number(last)] = {};
        invalidateOptimization();
        return;
      }
    }
  }
  if (parts[0] === "attacker" && (parts[1] === "buildA" || parts[1] === "buildB") && isRoleBoot(nextValue)) {
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
  const itemCount = Array.isArray(loadout?.items) ? loadout.items.length : 0;
  const capacity = roleInventoryCapacity(loadout?.role, Boolean(loadout?.roleQuestComplete), itemCount);
  const bootsSlot = loadout?.includeBoots !== false ? 1 : 0;
  return Math.min(itemCount, Math.max(0, capacity - bootsSlot));
}

function attackerLevelCap() {
  return roleLevelCap(
    state.attacker.role,
    Boolean(state.attacker.roleQuestComplete),
    state.attacker.level,
  );
}

function ordinarySlotCount(side = "A") {
  const itemCount = buildArray(side).length;
  const capacity = roleInventoryCapacity(
    state.attacker.role,
    Boolean(state.attacker.roleQuestComplete),
    itemCount,
  );
  const bootsSlot = includeBootsForSide(side) ? 1 : 0;
  return Math.min(itemCount, Math.max(0, capacity - bootsSlot));
}

function includeBootsForSide(side) {
  return side === "B" ? state.attacker.includeBootsB : state.attacker.includeBootsA;
}

function questBootIds() {
  return bootIdsForTier(
    roleBootsTier(state.attacker.role, Boolean(state.attacker.roleQuestComplete)),
  );
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

// ---------------------------------------------------------------------------
// Item hover card
//
// A wiki-style reading of whatever item the pointer rests on: the catalogue's
// stat block plus the effect catalogue's passive/active wiki text, rendered
// through a small wiki-markup formatter. One popover element serves every
// anchor carrying data-item-tooltip; the popover API keeps it above the
// <dialog> pickers.
// ---------------------------------------------------------------------------

/** Stat fields the hover card lists, wiki-style, one per line. */
const ITEM_TIP_STATS = [
  ["ap", "ability power", "", "wk-ap"],
  ["ad", "attack damage", "", "wk-ad"],
  ["hp", "health", "", "wk-health"],
  ["mana", "mana", "", "wk-mana"],
  ["armor", "armor", "", "wk-stat"],
  ["mr", "magic resistance", "", "wk-stat"],
  ["haste", "ability haste", "", "wk-haste"],
  ["attackSpeed", "attack speed", "%", "wk-as"],
  ["crit", "critical strike chance", "%", "wk-ad"],
  ["critDamage", "critical strike damage", "%", "wk-ad"],
  ["lethality", "lethality", "", "wk-physical"],
  ["percentArmorPen", "armor penetration", "%", "wk-physical"],
  ["pen", "magic penetration", "", "wk-magic"],
  ["percentPen", "magic penetration", "%", "wk-magic"],
  ["lifesteal", "life steal", "%", "wk-health"],
  ["omnivamp", "omnivamp", "%", "wk-health"],
  ["healAndShieldPower", "heal and shield power", "%", "wk-health"],
  ["healthRegen", "base health regeneration", "%", "wk-health"],
  ["manaRegen", "base mana regeneration", "%", "wk-mana"],
  ["moveSpeed", "movement speed", "", "wk-ms"],
  ["tenacity", "tenacity", "%", "wk-stat"],
  ["goldPer10", "gold per 10 seconds", "", "wk-gold"],
];

/** Colour class for a wiki stat phrase, mirroring the wiki's stat tinting. */
const WIKI_STAT_CLASSES = [
  [/magic damage/i, "wk-magic"],
  [/physical damage/i, "wk-physical"],
  [/true damage/i, "wk-true"],
  [/ability power|\bAP\b/, "wk-ap"],
  [/attack damage|\bAD\b/, "wk-ad"],
  [/omnivamp|life steal|heal|health|\bHP\b/i, "wk-health"],
  [/shield/i, "wk-health"],
  [/mana|energy/i, "wk-mana"],
  [/movement speed|move speed/i, "wk-ms"],
  [/attack speed/i, "wk-as"],
  [/ability haste|cooldown/i, "wk-haste"],
  [/gold/i, "wk-gold"],
];

function wikiStatClass(text) {
  const match = WIKI_STAT_CLASSES.find(([pattern]) => pattern.test(text));
  return match ? match[1] : "wk-stat";
}

/**
 * Evaluate the arithmetic the wiki's {{ap|...}} template computes inline
 * (e.g. "60/6" → 10, "(60/6)+10" → 20). Returns null for anything that is
 * not a plain arithmetic expression — including 2+ bare slashes, which read
 * as a per-rank progression, not division. Hand-rolled recursive descent
 * because the site CSP has no unsafe-eval.
 */
function wikiArithmetic(expression) {
  const text = String(expression).trim();
  if (!text || !/^[\d+\-*/(). ]+$/.test(text)) return null;
  const slashes = (text.match(/\//g) || []).length;
  if (slashes > 1 && !/[+*()]/.test(text)) return null;
  if (!/[+\-*/]/.test(text)) return null;
  const tokens = text.match(/\d+(?:\.\d+)?|[+\-*/()]/g) || [];
  let cursor = 0;
  const peek = () => tokens[cursor];
  const parseExpr = () => {
    let value = parseTerm();
    while (peek() === "+" || peek() === "-") value = tokens[cursor++] === "+" ? value + parseTerm() : value - parseTerm();
    return value;
  };
  const parseTerm = () => {
    let value = parseFactor();
    while (peek() === "*" || peek() === "/") value = tokens[cursor++] === "*" ? value * parseFactor() : value / parseFactor();
    return value;
  };
  const parseFactor = () => {
    if (peek() === "-") { cursor += 1; return -parseFactor(); }
    if (peek() === "(") {
      cursor += 1;
      const value = parseExpr();
      if (peek() !== ")") return NaN;
      cursor += 1;
      return value;
    }
    const token = tokens[cursor++];
    return /^\d/.test(token || "") ? Number(token) : NaN;
  };
  const value = parseExpr();
  return cursor === tokens.length && Number.isFinite(value) ? Number(value.toFixed(2)) : null;
}

/** Resolve one already-innermost {{template|...}} body to display HTML. */
function resolveWikiTemplate(body) {
  const parts = body.split("|");
  const name = (parts.shift() || "").trim().toLowerCase();
  const positional = parts.filter((part) => !/^\s*\w[\w ]*=/.test(part)).map((part) => part.trim());
  const content = positional[0] || "";
  switch (name) {
    case "as": // coloured stat text, optional explicit stat hint as 2nd param
      return `<span class="wk ${wikiStatClass(positional[1] || content)}">${content}</span>`;
    case "ap":
    case "fd":
    case "nie": {
      const value = wikiArithmetic(content);
      return value == null ? content : String(value);
    }
    case "sbc":
      return `<b>${content}</b>`;
    case "tip":
    case "sti":
    case "tt":
    case "ft":
      return positional[1] || content;
    case "g":
      return `${content}g`;
    default:
      return content;
  }
}

/** Render wiki effect text (templates, links, bold/italic) to inline HTML. */
function wikiMarkupHtml(raw) {
  let text = escapeHtml(String(raw || ""));
  // Innermost templates first, so nesting like {{as|(+ {{ap|6/6}}% AP)}}
  // resolves the arithmetic before the colour wrap sees it.
  for (let pass = 0; pass < 24 && /\{\{[^{}]*\}\}/.test(text); pass += 1) {
    text = text.replace(/\{\{([^{}]*)\}\}/g, (_, body) => resolveWikiTemplate(body));
  }
  return text
    .replace(/\[\[(?:File|Image):[^\]]*\]\]/gi, "")
    .replace(/\[\[([^\]|]*)\|([^\]]*)\]\]/g, "$2")
    .replace(/\[\[([^\]]*)\]\]/g, "$1")
    .replace(/'''(.+?)'''/g, "<b>$1</b>")
    .replace(/''(.+?)''/g, "<i>$1</i>");
}

function itemTipHtml(item) {
  const effect = EFFECT_CATALOG[String(item.id)] || {};
  const stats = ITEM_TIP_STATS
    .filter(([key]) => Number(item[key]))
    .map(([key, label, unit, cls]) => `<li><span class="wk ${cls}">+${item[key]}${unit} ${label}</span></li>`);
  const passives = (effect.passives || [])
    .filter((passive) => passive?.text)
    .map((passive) => `<p class="tip-effect">${passive.name ? `<b class="tip-effect-name">${escapeHtml(passive.name)}:</b> ` : ""}${wikiMarkupHtml(passive.text)}</p>`);
  const actives = (Array.isArray(effect.active) ? effect.active : [])
    .map((active) => {
      const meta = [
        active.cooldown ? `${active.cooldown}s cooldown` : "",
        active.range ? `${active.range} range` : "",
      ].filter(Boolean).join(" · ");
      const branches = (active.branches || []).map(wikiMarkupHtml).join(" ");
      return `<p class="tip-effect">${active.name ? `<b class="tip-effect-name">${escapeHtml(active.name)}:</b> ` : ""}${branches}${meta ? ` <small>(${escapeHtml(meta)})</small>` : ""}</p>`;
    });
  return `<header class="tip-head"><span>${escapeHtml(itemName(item.id))}</span>${Number(item.price) ? `<b>${fmt(item.price)}g</b>` : ""}</header>
    <div class="tip-identity"><img src="${itemImage(item.id)}" alt="" />${stats.length ? `<ul class="tip-stats">${stats.join("")}</ul>` : ""}</div>
    ${passives.length ? `<p class="tip-section">Passive</p>${passives.join("")}` : ""}
    ${actives.length ? `<p class="tip-section">Active</p>${actives.join("")}` : ""}`;
}

const itemTip = (() => {
  const tip = document.createElement("div");
  tip.className = "item-tip";
  tip.setAttribute("popover", "manual");
  tip.setAttribute("role", "tooltip");
  if (!tip.showPopover) tip.classList.add("no-popover");
  document.body.appendChild(tip);
  return tip;
})();
let itemTipAnchor = null;
let itemTipPending = null;
let itemTipTimer = null;

function closeItemTip() {
  clearTimeout(itemTipTimer);
  itemTipTimer = null;
  itemTipPending = null;
  itemTipAnchor = null;
  if (itemTip.hidePopover) {
    try { itemTip.hidePopover(); } catch { /* already closed */ }
  } else {
    itemTip.classList.remove("is-open");
  }
}

/**
 * Position the card beside the pointer when a hover produced it — wide
 * anchors like duel rows would otherwise push it clear across the delta
 * spine. Keyboard focus has no pointer, so it anchors to the element edge.
 */
function placeItemTip(anchor, point = null) {
  const tipRect = itemTip.getBoundingClientRect();
  const margin = 10;
  const offset = 16;
  let left;
  let top;
  if (point) {
    left = point.x + offset;
    if (left + tipRect.width > window.innerWidth - margin) left = point.x - offset - tipRect.width;
    top = point.y + offset;
    if (top + tipRect.height > window.innerHeight - margin) top = point.y - offset - tipRect.height;
  } else {
    const rect = anchor.getBoundingClientRect();
    left = rect.right + margin;
    if (left + tipRect.width > window.innerWidth - margin) left = rect.left - margin - tipRect.width;
    top = rect.top;
  }
  left = Math.max(margin, Math.min(left, window.innerWidth - tipRect.width - margin));
  top = Math.max(margin, Math.min(top, window.innerHeight - tipRect.height - margin));
  itemTip.style.left = `${Math.round(left)}px`;
  itemTip.style.top = `${Math.round(top)}px`;
}

function showItemTip(anchor, point = null) {
  const item = getItem(anchor.dataset.itemTooltip);
  if (!item) return;
  itemTipAnchor = anchor;
  itemTip.innerHTML = itemTipHtml(item);
  if (itemTip.showPopover) {
    try { itemTip.showPopover(); } catch { /* already open */ }
  } else {
    itemTip.classList.add("is-open");
  }
  placeItemTip(anchor, point);
}

document.addEventListener("pointerover", (event) => {
  const anchor = event.target.closest?.("[data-item-tooltip]");
  if (!anchor || anchor === itemTipAnchor || anchor === itemTipPending) return;
  clearTimeout(itemTipTimer);
  itemTipPending = anchor;
  const point = { x: event.clientX, y: event.clientY };
  itemTipTimer = setTimeout(() => {
    itemTipPending = null;
    showItemTip(anchor, point);
  }, 140);
});
document.addEventListener("pointerout", (event) => {
  const anchor = event.target.closest?.("[data-item-tooltip]");
  if (!anchor || anchor.contains(event.relatedTarget)) return;
  if (itemTipPending === anchor) {
    clearTimeout(itemTipTimer);
    itemTipTimer = null;
    itemTipPending = null;
  }
  if (itemTipAnchor === anchor) closeItemTip();
});
document.addEventListener("focusin", (event) => {
  const anchor = event.target.closest?.("[data-item-tooltip]");
  // :focus-visible keeps this a keyboard affordance — a mouse click already
  // has the pointerover card and shouldn't re-flash it while a dialog opens.
  if (anchor && anchor.matches(":focus-visible")) showItemTip(anchor);
  else if (!anchor && itemTipAnchor) closeItemTip();
});
// Any scroll or press invalidates the anchored position; just dismiss.
document.addEventListener("scroll", () => { if (itemTipAnchor || itemTipPending) closeItemTip(); }, true);
document.addEventListener("pointerdown", () => { if (itemTipAnchor || itemTipPending) closeItemTip(); });

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


function abilityBindsChampionOption(key) {
  const abilities = activeAbilityKit();
  if (key === "passive_procs") return abilities.some((ability) => ability.slot === "P");
  if (key === "mines_hit") return abilities.some((ability) => ability.slot === "E" && Number(ability.maxHits) > 1);
  if (key === "r_sweet_spot") return abilities.some((ability) => ability.slot === "R" && ability.variants?.length > 1);
  return abilities.some((ability) =>
    ability.variants?.length > 1
      && abilityOptionBinding(ability.slot, "ability_variants") === key
  );
}

function renderChampionOptions() {
  const capability = championOptionCapability("main", state.attacker.champion);
  const optionAttributes = capabilityDescriptorAttributes("champion_options", capability);
  const definitions = (engine.championOptions[state.attacker.champion]?.options || [])
    .filter((option) => !abilityBindsChampionOption(option.key));
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

function buildIdsForSide(side) {
  const ids = buildArray(side)
    .slice(0, ordinarySlotCount(side))
    .filter((id) => id && !isRoleBoot(id));
  if (includeBootsForSide(side) && state.attacker[`questBoot${side}`]) {
    ids.push(state.attacker[`questBoot${side}`]);
  }
  return ids;
}

function buildStacksForSide(side) {
  const stacks = buildStackArray(side)
    .slice(0, ordinarySlotCount(side))
    .filter((_, index) => !isRoleBoot(buildArray(side)[index]));
  if (includeBootsForSide(side) && state.attacker[`questBoot${side}`]) stacks.push(0);
  return stacks;
}


function buildAIds() { return buildIdsForSide("A"); }
function buildBIds() { return buildIdsForSide("B"); }

function fitItemSlots(ids, slotCount = state.attacker.buildA.length) {
  return [
    ...ids,
    ...Array(Math.max(0, slotCount - ids.length)).fill(0),
  ].slice(0, slotCount);
}


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
    ? (state.attacker[`questBoot${side}`] || ids.find((id) => isRoleBoot(id)) || 0)
    : 0;
  const itemIds = ids.filter((id) => !isRoleBoot(id));
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
  };
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
    const variantAbility = activeAbilityKit().find((ability) =>
      ability.variants?.length > 1
        && abilityOptionBinding(ability.slot, "ability_variants") === option.key
    );
    if (variantAbility) {
      // Share-restore clears abilityInputs; without a real variant input the
      // option keeps its stored/default value instead of reading the
      // synthetic variant-0 fallback (which would flip Jayce to hammer).
      const input = state.attacker.abilityInputs[variantAbility.slot];
      if (option.key in GLOBAL_FORM_TOGGLES) {
        if (input) options[option.key] = input.variant === GLOBAL_FORM_TOGGLES[option.key];
      } else if (input) {
        options[option.key] = input.variant;
      }
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
  let remaining = Math.min(state.attacker.level, attackerLevelCap());
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
  const practiceDummy = isPracticeDummy(target);
  const selectedBoot = Number(target.boots || 0);
  const itemIds = target.items
    .slice(0, rosterOrdinarySlotCount(target))
    .filter(Boolean)
    .filter((id) => !isRoleBoot(id));
  return {
    kind: practiceDummy ? PRACTICE_DUMMY_KIND : "champion",
    champion: target.champion,
    level: target.level,
    items: itemIds.map((id) => itemName(id)).filter(Boolean),
    boots: target.includeBoots && selectedBoot ? itemName(selectedBoot) : "",
    include_boots: Boolean(target.includeBoots),
    item_options: engineItemOptions(itemIds, target.itemStacks, target.itemOptions),
    role: target.role || "",
    role_quest_complete: Boolean(target.roleQuestComplete),
    ...(practiceDummy
      ? {
        target_stats: Object.fromEntries(
          Object.entries(target.targetStatOverrides || {}).map(([key, value]) => [
            key,
            Number(value),
          ]),
        ),
      }
      : {}),
    champion_options: Object.fromEntries(
      Object.entries(target.championOptions || {}).map(([key, value]) => [key, value]),
    ),
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
    ability_ranks: engineAbilityRanks(),
    rotations: state.fight.rotations,
  };
  payload.auto_attack_uptime_mode = state.fight.aaUptimeMode || "calculated";
  // The Enemy Hits constraint: unchecked, every enemy deals zero damage.
  payload.enemies_attack = state.fight.enemiesAttack !== false;
  // The Window is a timed window: abilities recast whenever their cooldown
  // is back up inside it (the engine's shared cast schedule). one_rotation —
  // a fixed 5s window where every ability casts exactly once — is only sent
  // for the few champions whose module certifies nothing else.
  const timedMode = championSupportsTimedWindow(state.attacker.champion)
    ? "time_based"
    : "one_rotation";
  if (state.fight.aaUptimeMode === "calculated") {
    payload.fight_mode = timedMode;
    payload.fight_duration = configuredFightWindow();
    payload.include_auto_attacks = true;
    payload.auto_attack_uptime = 0;
  } else if (state.fight.aaUptime > 0) {
    payload.fight_mode = timedMode;
    payload.fight_duration = configuredFightWindow();
    payload.include_auto_attacks = true;
    payload.auto_attack_uptime = state.fight.aaUptime;
  } else {
    payload.fight_mode = timedMode;
    payload.fight_duration = configuredFightWindow();
    payload.include_auto_attacks = false;
    payload.auto_attack_uptime = 0;
  }
  return payload;
}

/**
 * Whether the champion's module certifies timed-window (recast) fights.
 * Unrestricted modules (the overwhelming majority) certify every mode; a
 * restricted module names its modes and carries a sourced reason, shown in
 * the Window constraint by renderRail.
 */
function championSupportsTimedWindow(championName) {
  const modes = getChampion(championName)?.supportedFightModes;
  return !Array.isArray(modes) || modes.includes("time_based");
}

/**
 * The fight window the constraints bar configures: rotations × seconds per
 * rotation, capped by the engine's fight-duration limit. This is the same
 * number engineFightPayload requests, so the fight timeline's x-axis and the
 * calculation window can never disagree.
 */
function configuredFightWindow() {
  const maxWindow = Number(engine.fightLimits.fight_duration?.[1] || 30);
  return Math.min(maxWindow, Math.max(1, state.fight.duration * state.fight.rotations));
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
  const eventRows = (aResult?.combat?.events || []).filter((event) => Number(event.damage || 0) > 0 || event.skipped_reason).map((event) => `<tr><td><strong>${one(event.time)}s · ${escapeHtml(labels.get(event.attacker) || event.attacker || "Participant")}</strong><small>${escapeHtml(labels.get(event.target) || event.target || "Target")} · ${escapeHtml(event.source || "event")} · ${escapeHtml(event.event_precision || "exact")}${event.skipped_reason ? ` · ${escapeHtml(event.skipped_reason)}` : ""}</small></td><td>${fmt(event.damage || 0)}</td></tr>`).join("");
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
      event.cleanse ? "cleanse" : "",
    ].filter(Boolean).join(" · ");
    return `<tr><td><strong>${one(event.time)}s · ${escapeHtml(labels.get(event.attacker) || event.attacker || "Participant")}</strong><small>${escapeHtml(event.source || "support")} · ${escapeHtml(event.kind || "support")} · to ${escapeHtml(target)}${details ? ` · ${escapeHtml(details)}` : ""}</small></td><td>${fmt(event.applied_amount || event.amount || 0)}<small>${escapeHtml(policy)}</small></td></tr>`;
  }).join("");
  const utility = aResult?.combat?.utility_outcomes?.focus || null;
  const targetAllocation = aResult?.combat?.target_allocation || null;
  const utilitySummary = utility ? `<section class="utility-outcome-ledger" aria-label="Utility outcome dimensions"><header><div><p class="eyebrow">Utility objective</p><h2>Applied non-TDD outcomes</h2></div><span>Native units · no guessed conversion</span></header><p class="utility-outcome-note">${escapeHtml(utility.metric_note || "Movement, slows, cleanse, economy, and vision remain separate from TDD.")}</p><div class="utility-outcome-chips"><span>Movement ${fmt(utility.movement?.speed_percent_seconds || 0)} %·s</span><span>Slow ${fmt(utility.slow?.percent_seconds || 0)} %·s</span><span>Cleanse ${fmt(utility.cleanse?.event_count || 0)} events</span><span>Economy ${fmt(utility.economy?.gold || 0)} gold</span><span>Vision ${fmt(utility.vision?.ward_uses || 0)} wards</span><span>Secondary ${fmt(utility.multi_target?.allocated_packet_count || 0)}/${fmt(utility.multi_target?.packet_count || 0)} allocated</span></div></section>` : "";
  const allocationNote = targetAllocation && targetAllocation.secondary_packet_count ? `<p class="utility-target-allocation" role="status">Target allocation: ${targetAllocation.complete ? "complete" : "withheld"} · ${fmt(targetAllocation.allocated_secondary_packet_count || 0)}/${fmt(targetAllocation.secondary_packet_count || 0)} secondary packets use the authored roster-index policy.</p>` : "";
  const eventSection = eventRows || healingRows || supportRows || utilitySummary ? `<details class="breakdown-audit"><summary>Audit trail <span>Event order · timestamps</span></summary>${utilitySummary}${allocationNote}<section class="combat-event-ledger" aria-label="Event order audit"><header><div><p class="eyebrow">Event order</p><h2>Timestamped events</h2></div><span>Outgoing · incoming · recovery · support</span></header><div class="damage-table-wrap"><table class="damage-table"><thead><tr><th>Event</th><th>Applied value</th></tr></thead><tbody>${eventRows}${healingRows}${supportRows}</tbody></table></div></section></details>` : "";
  const outcome = `<p class="breakdown-outcome" role="status">${escapeHtml(breakdownOutcome(aMainTotal, bResult ? bMainTotal : null))}</p>`;
  $("damageBreakdown").innerHTML = `${outcome}${combatSection}${eventSection}<header><div><p class="eyebrow">Damage breakdown</p><h2>Damage sources</h2></div><span>${state.targets.length} ${plural(state.targets.length, "target")} · ${state.fight.rotations} ${plural(state.fight.rotations, "rotation")}</span></header><div class="damage-table-wrap"><table class="damage-table"><thead><tr><th>Source</th><th><i class="legend-a"></i>Build A</th>${bResult ? `<th><i class="legend-b"></i>Build B</th><th>A − B</th>` : ""}</tr></thead><tbody>${body}<tr class="damage-total"><td><strong>Main output before defeat</strong><small>Post-mitigation output · ${escapeHtml(survivalStatus((aResult?.combat?.participants || []).find((participant) => participant.participant_id === "main")?.survival))}</small></td><td>${fmt(aMainTotal)}</td>${totalB}</tr></tbody></table></div>`;
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
  ["scoreA", "scoreB"].forEach((id) => {
    const element = $(id);
    if (element) element.textContent = "Unavailable";
  });
}

function syncPracticeDummyStatsFromResponse(result) {
  const targetRows = Array.isArray(result?.targets) ? result.targets : [];
  state.targets.forEach((loadout, index) => {
    if (!isPracticeDummy(loadout)) return;
    const stats = targetRows[index]?.target?.stats;
    if (!stats || typeof stats !== "object") return;
    const overrides = loadout.targetStatOverrides || {};
    if (!loadout.targetStats) loadout.targetStats = { ...PRACTICE_DUMMY_STATS };
    PRACTICE_DUMMY_STAT_FIELDS.forEach(([key]) => {
      if (Object.prototype.hasOwnProperty.call(overrides, key)) return;
      const value = Number(stats[key]);
      if (Number.isFinite(value)) loadout.targetStats[key] = value;
    });
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
        // Clear the in-flight flag before rendering: the verdict strip reads
        // it to decide between RECALCULATING and the settled delta.
        engine.pending = false;
        engine.responses = { a: results[0], b: results[1] || null };
        syncPracticeDummyStatsFromResponse(engine.responses.a);
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
  const objectiveLabel = selectedObjectiveDefinition().label || "";
  return `<strong>${escapeHtml(state.attacker.champion)} level ${state.attacker.level}</strong>${buildA.length ? ` with ${escapeHtml(buildA.join(" + "))}` : ""}${keystoneText}${compareText}${targetText} · ${escapeHtml(objectiveLabel)} · ${stateLabel} · ${one(configuredFightWindow())}s fight window · ${Math.round(state.fight.aaUptime * 100)}% auto uptime${state.fight.enemiesAttack === false ? " · enemies deal no damage" : ""}${allyText}.`;
}

// ---------------------------------------------------------------------------
// Setup rail
//
// The rail is a three-step wizard that is always visible. Collapsed
// (target-2a) each step shows a read-only brief; opening one (target-2b)
// widens the rail into that step's editor and dims the duel canvas behind it.
// Every function below only reads `state` and backend receipts.
// ---------------------------------------------------------------------------

// Setup steps that live in the rail. Builds is deliberately absent: the duel
// panel on the canvas is the only place a build is edited.
const STEP_IDS = ["champion", "roster"];

/**
 * List-price total of one side's build.
 *
 * Prices are ingested catalogue data from the patch snapshot — the same field
 * the item picker already shows — not a modeled number, so summing them here
 * does not break the receipts-only contract (no formula, no item-id literal).
 */
function buildListPrice(side) {
  return buildIdsForSide(side).reduce((total, id) => total + Number(getItem(id)?.price || 0), 0);
}

function championBriefMeta() {
  if (!state.attacker.champion) return "Choose a champion to begin";
  const parts = [state.attacker.role ? state.attacker.role.toUpperCase() : "NO ROLE", `LV ${state.attacker.level}`];
  parts.push(includeBootsForSide("A") ? "BOOTS ON" : "BOOTS OFF");
  if (state.attacker.roleQuestComplete) parts.push("QUEST");
  return parts.join(" · ");
}

function renderChampionBrief() {
  const champion = getChampion(state.attacker.champion);
  const portrait = $("championBriefPortrait");
  if (portrait) {
    portrait.innerHTML = champion
      ? `<img src="${championImage(champion.name)}" alt="" />`
      : "";
  }
  const name = $("championBriefName");
  if (name) name.textContent = champion?.name || "No champion";
  const meta = $("championBriefMeta");
  if (meta) meta.textContent = championBriefMeta();
  const chips = $("championBriefChips");
  if (chips) {
    chips.innerHTML = activeAbilityKit().map((ability) => {
      const input = abilityInput(ability.slot);
      const rank = ability.slot === "P" ? "—" : String(Number(input.rank) || 0);
      return `<div class="brief-chip"><b>${escapeHtml(ability.slot)}</b><span>${escapeHtml(rank)}·${Number(input.casts) || 0}</span></div>`;
    }).join("");
  }
  const summary = $("championSummary");
  if (summary) summary.textContent = champion ? `${champion.name} · ${championBriefMeta()}` : "";
}

function briefCardHtml(loadout, team) {
  const champion = getChampion(loadout.champion);
  const label = team === "enemy" ? "enemy" : "ally";
  return `<div class="brief-card ${team === "ally" ? "is-ally" : ""}">
    <span class="brief-card-portrait">${champion ? `<img src="${championImage(champion.name)}" alt="" />` : ""}</span>
    <b>${escapeHtml(champion?.name || `Choose ${label}`)}</b>
    <span class="brief-card-meta">LV ${Number(loadout.level) || 1} · ${escapeHtml(label.toUpperCase())}</span>
  </div>`;
}

function renderRosterBrief() {
  const host = $("rosterBriefList");
  const rows = [
    ...state.targets.map((loadout) => briefCardHtml(loadout, "enemy")),
    ...state.allies.map((loadout) => briefCardHtml(loadout, "ally")),
  ];
  if (host) {
    host.innerHTML = rows.join("") || `<p class="brief-empty">+ Add an enemy to start the coupled timeline</p>`;
  }
  const summary = $("rosterSummary");
  if (summary) {
    summary.textContent = `${state.targets.length} ${plural(state.targets.length, "ENEMY", "ENEMIES")} · ${state.allies.length} ${plural(state.allies.length, "ALLY", "ALLIES")}`;
  }
}

function windowSummary() {
  const uptime = state.fight.aaUptimeMode === "calculated"
    ? "AA calc"
    : `${Math.round(state.fight.aaUptime * 100)}% AA`;
  // A restricted module runs the engine's fixed one-cast rotation instead of
  // the timed window; say so where the window is read, not just in the body.
  if (state.attacker.champion && !championSupportsTimedWindow(state.attacker.champion)) {
    return `1 rotation · 5s · ${uptime}`;
  }
  return `${one(configuredFightWindow())}s window · ${uptime}`;
}

function renderConstraintSummaries() {
  const gold = $("goldValue");
  if (gold) gold.textContent = state.optimizer.availableGold > 0 ? fmt(state.optimizer.availableGold) : "—";
  const objective = $("objectiveValue");
  if (objective) objective.textContent = selectedObjectiveDefinition().label || "";
  const windowValue = $("windowValue");
  if (windowValue) windowValue.textContent = windowSummary();
  const stateValue = $("stateValue");
  if (stateValue) stateValue.textContent = state.ui.gameState === "live" ? "Snapshot lens" : "Theory";
  const enemyHitsValue = $("enemyHitsValue");
  if (enemyHitsValue) enemyHitsValue.textContent = state.fight.enemiesAttack !== false ? "On" : "Off";
  const enemyHitsToggle = $("enemyHitsToggle");
  if (enemyHitsToggle) enemyHitsToggle.checked = state.fight.enemiesAttack !== false;
}

/**
 * Apply the open/closed disclosure state to the rail and the canvas.
 *
 * One step at a time, in one of two places. Before the scenario is ready the
 * canvas middle is empty, so the open step's editor (.step-body) is moved
 * into #startEditor and edits front-and-centre. Once the duel is live the
 * editor returns to the widening rail (2b) and the canvas dims, inert, so a
 * stale click cannot land on numbers that are about to change.
 */
function applyRailDisclosure() {
  const grid = $("appGrid");
  const editing = Boolean(state.ui.expandedStep);
  const centreEditing = editing && !scenarioReady();
  const railEditing = editing && !centreEditing;
  if (grid) grid.classList.toggle("is-editing", railEditing);
  const canvas = $("canvas");
  if (canvas) {
    canvas.inert = railEditing;
    canvas.setAttribute("aria-hidden", String(railEditing));
    canvas.classList.toggle("is-start-editing", centreEditing);
  }
  const centreHost = $("startEditor");
  STEP_IDS.forEach((step) => {
    const sectionId = `step${step[0].toUpperCase()}${step.slice(1)}`;
    const section = $(sectionId);
    if (!section) return;
    const open = state.ui.expandedStep === step;
    section.classList.toggle("is-open", open && railEditing);
    section.classList.toggle(
      "is-active",
      (open && centreEditing) || (!editing && state.ui.activeStep === step),
    );
    const toggle = section.querySelector("[data-step-toggle]");
    if (toggle) toggle.setAttribute("aria-expanded", String(open));
    const body = $(`${sectionId}Body`);
    if (body) {
      if (open && centreEditing) {
        if (centreHost && body.parentElement !== centreHost) centreHost.appendChild(body);
      } else if (body.parentElement !== section) {
        section.appendChild(body);
      }
      body.hidden = !open;
    }
    const action = section.querySelector(".step-action");
    if (action) action.textContent = open ? "Editing" : (!editing && state.ui.activeStep === step ? "Active" : "Edit");
  });
  if (centreHost) {
    centreHost.hidden = !centreEditing;
    const head = $("startEditorHead");
    if (head && centreEditing) {
      head.textContent = `Setup · step ${STEP_IDS.indexOf(state.ui.expandedStep) + 1} of ${STEP_IDS.length}`;
    }
  }
  // The checklist and the centre editor share the canvas middle.
  const band = $("startBand");
  if (band) band.hidden = scenarioReady() || centreEditing;
  document.querySelectorAll("[data-constraint-toggle]").forEach((toggle) => {
    const open = state.ui.expandedConstraint === toggle.dataset.constraintToggle;
    toggle.setAttribute("aria-expanded", String(open));
    const body = document.getElementById(toggle.getAttribute("aria-controls") || "");
    if (body) body.hidden = !open;
  });
  const patch = $("railPatch");
  if (patch && editing) {
    patch.textContent = `SETUP · STEP ${STEP_IDS.indexOf(state.ui.expandedStep) + 1} OF ${STEP_IDS.length}`;
  } else if (patch) {
    patch.textContent = "26.15";
  }
}

function renderScenarioRail() {
  const roleSelect = $("roleSelect");
  if (roleSelect) {
    roleSelect.value = state.attacker.role || "";
    const roleCapability = capabilityFor("main", "role");
    roleSelect.disabled = roleCapability.supported === false;
    roleSelect.title = capabilityTitle(roleCapability);
    roleSelect.dataset.capabilityField = "role";
  }
  renderChampionBrief();
  renderRosterBrief();
  renderConstraintSummaries();
  applyRailDisclosure();

  const stateReadout = $("stateReadout");
  if (stateReadout) {
    stateReadout.textContent = `${state.ui.gameState === "live" ? "Snapshot lens" : "Theory state"} · ${windowSummary()}`;
  }
  document.querySelectorAll("[data-objective]").forEach((button) => {
    const selected = button.dataset.objective === state.ui.objective;
    button.classList.toggle("is-on", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  // Every game-state button carries its own description for assistive tech
  // (#150). The active one is mirrored into the visible summary so sighted
  // users read the same sentence — the copy lives in the template only.
  const summary = $("gameStateHelp");
  document.querySelectorAll("[data-game-state]").forEach((button) => {
    const selected = button.dataset.gameState === state.ui.gameState;
    button.classList.toggle("is-on", selected);
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
  // kill. Only explicit finite death timestamps qualify for this objective.
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

function killTimeLabel(value) {
  // A finite kill always shows its real time-to-defeat from the timeline.
  // Zero (or a value that rounds to 0.0) is a defeat at the first event, not
  // "no time elapsed" — render it as a sub-second label instead of "0 s".
  if (value == null) return null;
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds <= 0) return "<1 s";
  return seconds < 0.05 ? "<1 s" : `${one(seconds)} s`;
}

function objectiveWinner(aValue, bValue) {
  if (aValue == null || bValue == null) return { winner: null, delta: null };
  const lower = selectedObjectiveDefinition().direction === "lower";
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

function prototypeRosterItemSlot(root, index, loadout, slot) {
  const isBoots = slot === "boots";
  const id = isBoots ? loadout.boots : loadout.items[slot];
  const path = isBoots ? `${root}.${index}.boots` : `${root}.${index}.items.${slot}`;
  const item = getItem(id);
  const emptyLabel = isBoots ? "Add boots" : "Add item";
  const slotLabel = isBoots ? `<span class="roster-slot-label">Boots</span>` : "";
  const kind = root === "allies" ? "ally" : "enemy";
  const field = isBoots ? "boots" : "items";
  return `<div class="roster-slot-wrap ${isBoots ? "roster-boots-wrap" : ""}">${slotLabel}<button class="roster-item-slot ${item ? "" : "is-empty"}" type="button" ${capabilityAttributes(kind, field)} data-picker="item" data-path="${path}"${item ? ` data-item-tooltip="${item.id}"` : ""} aria-label="${item ? `Change ${escapeHtml(item.name)}` : emptyLabel}"${item ? "" : ` title="${emptyLabel}"`}>${item ? `<img src="${itemImage(id)}" alt="${escapeHtml(item.name)}" />` : "+"}</button>${item && stackSpec(id) ? stackControl(path, id, true) : ""}${item && !isBoots ? itemOptionControls(path, id, true) : ""}${isPracticeDummy(loadout) ? "</div>" : `${bisTrigger(path, true)}</div>`}`;
}

function renderPracticeDummyCard(root, index, loadout, label) {
  const itemSlots = Array.from(
    { length: rosterOrdinarySlotCount(loadout) },
    (_, slot) => prototypeRosterItemSlot(root, index, loadout, slot),
  ).join("");
  const statControls = PRACTICE_DUMMY_STAT_FIELDS.map(
    ([key, statLabel, step, minimum, maximum]) => {
      const value = practiceDummyStatValue(loadout, key);
      const path = `${root}.${index}.targetStats.${key}`;
      return `<label class="practice-dummy-stat"><span>${escapeHtml(statLabel)}</span><input type="number" inputmode="decimal" data-dummy-stat="${path}" value="${escapeHtml(value)}" step="${step}" min="${minimum}" max="${maximum}" aria-label="${escapeHtml(`Practice Dummy ${statLabel}`)}" /></label>`;
    },
  ).join("");
  return `<article class="roster-card roster-card--dummy"><div class="roster-pick roster-pick--dummy"><img src="${PRACTICE_DUMMY_IMAGE}" alt="Practice Dummy" /></div><div class="roster-card-copy"><strong>${PRACTICE_DUMMY_NAME}</strong><span>League Practice Tool · no abilities</span><div class="roster-meta">Passive target · exact stats</div></div><button class="remove-roster" type="button" data-remove-${label === "enemy" ? "target" : "ally"}="${index}" aria-label="Remove ${label}">×</button><div class="roster-card-editor"><div class="practice-dummy-note"><strong>No skills or outgoing actions</strong><span>Items can add target effects. Each edited field is the final value sent to the engine.</span></div><div class="practice-dummy-stat-grid" aria-label="Practice Dummy exact stats">${statControls}</div><button class="practice-dummy-reset" type="button" data-reset-dummy-stats="${root}.${index}">Use item totals for every stat</button><p class="roster-strip-label">Items · target effects only</p><div class="roster-item-strip">${itemSlots}</div></div></article>`;
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
  document.querySelector(".editor-identity")?.classList.toggle("is-empty", !champion);
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
  $("questToggle").classList.toggle("is-on", Boolean(state.attacker.roleQuestComplete));
  $("questToggle").disabled = questCapability.supported === false || !state.attacker.role;
  $("questToggle").title = capabilityTitle(questCapability);
  $("questToggle").dataset.capabilityField = "role_quest_complete";
  const bootsCapability = capabilityFor("main", "include_boots");
  $("bootsToggle").textContent = includeBootsForSide("A") ? "Boots on" : "Boots off";
  $("bootsToggle").setAttribute("aria-pressed", String(includeBootsForSide("A")));
  $("bootsToggle").classList.toggle("is-on", includeBootsForSide("A"));
  $("bootsToggle").disabled = bootsCapability.supported === false;
  $("bootsToggle").title = capabilityTitle(bootsCapability);
  $("bootsToggle").dataset.capabilityField = "include_boots";
  $("stateReadout").textContent = `${state.ui.gameState === "live" ? "Snapshot lens" : "Theory state"} · ${one(configuredFightWindow())}s window`;
  // The placeholder is for "no stats yet", not "stats are refreshing" (#151):
  // a recalculation keeps the previous values on screen and marks the grid
  // pending, so the portrait, identity and controls never flash empty.
  const statsGrid = $("statsGrid");
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
    if (isPracticeDummy(loadout)) {
      return renderPracticeDummyCard(root, index, loadout, kind === "targets" ? "enemy" : "ally");
    }
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
    return `<article class="roster-card"><button class="roster-pick" type="button" ${capabilityAttributes(participantKind, "champion")} data-picker="champion" data-path="${root}.${index}.champion" aria-label="${champion ? `Change ${escapeHtml(champion.name)}` : `Choose ${label} champion`}">${champion ? `<img src="${championImage(champion.name)}" alt="${escapeHtml(champion.name)}" />` : "+"}</button><div class="roster-card-copy"><strong>${escapeHtml(champion?.name || `Choose ${label}`)}</strong><span>${escapeHtml(champion?.title || "Empty participant slot")}</span><div class="roster-meta">Lv ${loadout.level} · full participant</div></div><button class="remove-roster" type="button" data-remove-${kind === "targets" ? "target" : "ally"}="${index}" aria-label="Remove ${label}">×</button><div class="roster-card-editor"><div class="roster-controls-row"><label class="roster-role-control"><span>Role</span><select ${roleCapability} data-roster-role="${root}.${index}.role" aria-label="${label} role">${roleOptions.map(([value, name]) => `<option value="${value}" ${loadout.role === value ? "selected" : ""}>${name}</option>`).join("")}</select></label><div class="roster-level-control"><span>Level</span><button type="button" ${levelCapability} data-level-path="${root}.${index}.level" data-level-delta="-1" aria-label="Decrease ${label} level">−</button><output>Lv ${loadout.level}</output><button type="button" ${levelCapability} data-level-path="${root}.${index}.level" data-level-delta="1" aria-label="Increase ${label} level">+</button></div>${roleQuestButton}<button class="roster-boots-toggle ${bootsEnabled ? "active" : ""}" type="button" ${bootsCapability} data-include-roster-boots="${root}.${index}" aria-pressed="${bootsEnabled}">${bootsEnabled ? "Boots on" : "Boots off"}</button></div><p class="roster-strip-label">Items · affects your BIS</p><div class="roster-item-strip">${itemSlots}${bootsSlot}</div>${abilityRanks}${championOptions}${effectToggle}</div></article>`;
  }).join("") || `<p class="roster-empty">${kind === "targets" ? "No enemies yet — the coupled timeline needs at least one." : "No allies in context."}</p>`;
  // The 2b mock shows a "…pushes your best fifth slot from X to Y" callout
  // here. No backend receipt produces that sentence today, and the renderer
  // never invents prose, so the callout stays out until one does.
  // The roster counts have one home: renderRosterBrief() writes the step
  // summary and the collapsed brief from the same state.
}

function renderPrototypeBuilder() {
  const champion = getChampion(state.attacker.champion);
  renderPrototypeChampion();
  $("abilityRow").innerHTML = champion ? prototypeAbilityCards(champion) : `<p class="roster-empty">Choose a champion to load its sourced ability package.</p>`;
  $("championOptionsRow").innerHTML = champion ? renderChampionOptions() : "";
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
  const windowModeNote = $("windowModeNote");
  if (windowModeNote) {
    const restricted = Boolean(state.attacker.champion)
      && !championSupportsTimedWindow(state.attacker.champion);
    windowModeNote.hidden = !restricted;
    if (restricted) {
      windowModeNote.textContent = getChampion(state.attacker.champion)?.fightModeReason
        || "This champion is certified for single-rotation calculations only; the timed window and its cooldown recasts are withheld.";
    }
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
    : `First ${shown.length} of ${combatEvents.length} ordered events — the full sequence is in the ledger below`;
  return `<div class="timeline-axis"><span>0:00</span><span>${one(duration / 2)}s</span><span>${one(duration)}s</span></div>
    <ol class="timeline-events" aria-label="Ordered combat events">${lanes}</ol>
    <small class="timeline-note">${escapeHtml(note)}</small>`;
}

// ---------------------------------------------------------------------------
// Duel canvas
//
// Three stacked bands read left-to-right as the answer: the verdict strip,
// the mirrored builds around a delta spine, and the fight timeline. Every
// number here comes from an /api/calculate receipt; nothing is derived.
// ---------------------------------------------------------------------------

function metricValueLabel(metric, value, alive = "") {
  if (value == null) return alive || "—";
  return metric.lower ? (killTimeLabel(value) || alive || "—") : fmt(value);
}

/**
 * Build B's signed divergence from Build A for one metric.
 *
 * The bar always reads as "what B does to A": it grows right in green when B
 * is ahead and left in red when B is behind, whichever direction is better
 * for that metric. The ×4 display gain means a 25% divergence saturates the
 * half-bar, so ordinary single-item swings stay visible instead of
 * collapsing to a hairline (it matches the approved mock's bar lengths).
 */
function spineDivergence(metric, aValue, bValue) {
  if (aValue == null || bValue == null) return { percent: 0, favours: null };
  const scale = Math.max(Math.abs(aValue), Math.abs(bValue));
  if (!scale) return { percent: 0, favours: "tie" };
  const raw = Number(bValue) - Number(aValue);
  const percent = Math.min(100, (Math.abs(raw) / scale) * 400);
  if (percent < 0.5) return { percent: 0, favours: "tie" };
  return { percent, favours: (metric.lower ? raw < 0 : raw > 0) ? "b" : "a" };
}

function spineRowHtml(metric, aValue, bValue, comparing, aAlive = "", bAlive = "") {
  // A kill-time row with no death shows a short "alive" token; the full
  // remaining-health receipt rides along as the cell's title and in the
  // row's accessible name, so the column stays 52px and still says why.
  const aLabel = metricValueLabel(metric, aValue, aAlive && "alive");
  const bLabel = metricValueLabel(metric, bValue, bAlive && "alive");
  const aTitle = aValue == null && aAlive ? ` title="${escapeHtml(aAlive)}"` : "";
  const bTitle = bValue == null && bAlive ? ` title="${escapeHtml(bAlive)}"` : "";
  const spoken = (label, alive) => (label === "alive" && alive ? alive : label);
  if (!comparing) {
    return `<div class="spine-row is-solo" role="group" aria-label="${escapeHtml(metric.label)}: ${escapeHtml(spoken(aLabel, aAlive))}${metric.unit ? ` ${metric.unit}` : ""}">
      <p class="spine-label">${escapeHtml(metric.label)}</p>
      <p class="spine-solo-value"${aTitle}>${escapeHtml(aLabel)}${aValue == null || !metric.unit ? "" : `<small>${escapeHtml(metric.unit)}</small>`}</p>
    </div>`;
  }
  const divergence = spineDivergence(metric, aValue, bValue);
  const verdict = divergence.favours === "b"
    ? "Build B ahead"
    : divergence.favours === "a"
      ? "Build A ahead"
      : divergence.favours === "tie" ? "level" : "not available";
  const loseWidth = divergence.favours === "a" ? divergence.percent : 0;
  const winWidth = divergence.favours === "b" ? divergence.percent : 0;
  return `<div class="spine-row" role="group" aria-label="${escapeHtml(metric.label)}: Build A ${escapeHtml(spoken(aLabel, aAlive))}, Build B ${escapeHtml(spoken(bLabel, bAlive))} — ${verdict}">
    <p class="spine-label">${escapeHtml(metric.label)}</p>
    <div class="spine-bars">
      <span class="spine-value is-a"${aTitle}>${escapeHtml(aLabel)}</span>
      <span class="spine-half is-a"><span class="spine-bar is-lose" style="width:${loseWidth.toFixed(1)}%"></span></span>
      <span class="spine-axis"></span>
      <span class="spine-half is-b"><span class="spine-bar is-win" style="width:${winWidth.toFixed(1)}%"></span></span>
      <span class="spine-value is-b"${bTitle}>${escapeHtml(bLabel)}</span>
    </div>
  </div>`;
}

/**
 * One build slot on the duel canvas: the picker row plus everything that
 * slot owns — its BIS trigger, anchored to the row's outer edge, and the
 * stack/item-option scenario controls the item declares. All three are
 * siblings of the row, never children: a button cannot nest interactive
 * children.
 */
function duelRowHtml(id, path) {
  const item = getItem(id);
  const field = path.includes("questBoot") ? "boots" : "items";
  const kind = participantKindForPath(path);
  const controlAttrs = capabilityAttributes(kind, field);
  const row = item
    ? `<button type="button" class="duel-row" ${controlAttrs} data-picker="item" data-path="${path}" data-item-tooltip="${item.id}" aria-label="Change ${escapeHtml(itemName(id))}"><span class="item-icon item-slot"><img src="${itemImage(id)}" alt="${escapeHtml(item.name)}" /></span><span class="duel-row-copy"><strong>${escapeHtml(itemName(id))}</strong><small>${escapeHtml(itemStatsLine(item))}${Number(item.price) > 0 ? ` · ${fmt(item.price)}g` : ""}</small></span></button>`
    : `<button type="button" class="duel-row is-empty" ${controlAttrs} data-picker="item" data-path="${path}" title="${escapeHtml(capabilityTitle(capabilityFor(kind, field)))}" aria-label="Add an item to this slot"><span class="item-icon item-slot"></span><span class="duel-row-copy"><strong>Empty slot</strong><small>click to add an item</small></span></button>`;
  const controls = `${item && stackSpec(id) ? stackControl(path, id, true) : ""}${item ? itemOptionControls(path, id, true) : ""}`;
  return `<div class="duel-slot">${row}${bisTrigger(path, true)}${controls ? `<div class="duel-slot-controls">${controls}</div>` : ""}</div>`;
}

/**
 * The build panel for one side. This is the only build editor in the app:
 * a labelled head with the whole-side copy move, one row per slot, the
 * keystone row, and the list-price foot.
 */
function renderDuelSide(side) {
  const host = $(side === "A" ? "duelA" : "duelB");
  if (!host) return;
  const slotIds = buildArray(side).slice(0, ordinarySlotCount(side));
  const keystone = getKeystone(state.attacker[`keystone${side}`]);
  const filled = buildIdsForSide(side);
  const from = side === "A" ? "B" : "A";
  const head = `<div class="duel-side-head"><span class="duel-side-kicker">Build ${side} · ${side === "A" ? "baseline" : "challenger"}</span><button class="link-button" type="button" data-copy="${from.toLowerCase()}">Copy ${from} → ${side}</button></div>`;
  const rows = slotIds.map((id, index) => duelRowHtml(id, `attacker.build${side}.${index}`));
  if (includeBootsForSide(side)) {
    rows.push(duelRowHtml(state.attacker[`questBoot${side}`], questBootPath(side)));
  }
  const keystoneRow = `<button type="button" class="duel-row is-keystone ${keystone ? "" : "is-empty"}" ${capabilityAttributes("main", "keystone")} data-picker="keystone" data-path="attacker.keystone${side}" aria-label="${keystone ? `Change ${escapeHtml(keystone.name)}` : "Add a keystone"}"><span class="item-icon">${keystone ? `<img src="${escapeHtml(keystone.icon)}" alt="${escapeHtml(keystone.name)}" />` : ""}</span><span class="duel-row-copy"><strong>${keystone ? escapeHtml(keystone.name) : "Add keystone"}</strong><small>${keystone ? `${escapeHtml(keystone.path || "")} keystone` : "rune slot"}</small></span></button>`;
  const invite = filled.length || keystone
    ? ""
    : `<p class="duel-empty">Build ${side} is empty<small>click any slot below to add an item</small></p>`;
  const foot = filled.length
    ? `<p class="duel-foot">${filled.length} ${plural(filled.length, "item")} · ${fmt(buildListPrice(side))}g list price</p>`
    : "";
  host.innerHTML = `${head}${invite}${rows.join("")}${keystoneRow}${foot}`;
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
  const participants = result?.combat?.participants || [];
  const dispositions = result?.combat?.dispositions || null;
  const enemyIndexes = participants
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => row.team === "enemy" || String(row.participant_id || "").startsWith("enemy:"));
  if (!enemyIndexes.length) return "";
  // A total that reads one refused member as zero is a total that quietly
  // counted a number nobody produced. If any enemy's ending health was
  // withheld, the sum is withheld and says which receipt refused it.
  const refused = withheldEntry(
    enemyIndexes.map(({ index }) => survivalLeafPath(index, "ending_health")),
    dispositions,
  );
  if (refused) return `alive · health withheld (${withheldReason(refused)})`;
  const ending = enemyIndexes.reduce((sum, { row }) => sum + Math.max(0, Number(row.survival?.ending_health ?? 0)), 0);
  if (ending <= 0) return "";
  const max = enemyIndexes.reduce((sum, { row }) => sum + Math.max(0, Number(row.survival?.max_health ?? row.survival?.effective_health ?? 0)), 0);
  const pct = max > 0 ? Math.round((ending / max) * 100) : null;
  return `alive · ${fmt(ending)} HP${pct != null ? ` (${pct}%)` : ""}`;
}

function enemyOverkill(result, totalDamage) {
  const enemies = enemyParticipants(result);
  const exact = enemies.reduce((sum, row) => sum + Math.max(0, Number(row.survival?.overkill || 0)), 0);
  const formula = Math.max(0, Number(totalDamage || 0) - enemyEffectiveHealth(result));
  return Math.max(exact, formula);
}

/** Cumulative main-attacker damage from the ordered event ledger. */
function mainDamageSeries(result) {
  const rows = (result?.combat?.events || [])
    .filter((event) => event.attacker === "main" && Number(event.damage || 0) > 0)
    .map((event) => ({ time: eventTime(event), damage: Number(event.damage) }))
    .filter((row) => row.time !== null)
    .sort((a, b) => a.time - b.time);
  const points = [{ time: 0, total: 0 }];
  let running = 0;
  rows.forEach((row) => {
    running += row.damage;
    points.push({ time: row.time, total: running });
  });
  return { points, total: running };
}

/** Ability and auto-attack casts the main attacker landed, in event order.
    Sized for a timed window: an opening burst, the auto stream, and every
    cooldown recast a 30s window can reasonably hold. */
const CHART_MARK_LIMIT = 14;
function castMarkers(result) {
  // Casts that land on the same timestamp share one marker: two ticks at the
  // same x would overlap into an unreadable smear.
  const byTime = new Map();
  (result?.combat?.events || []).forEach((event) => {
    if (event.attacker !== "main") return;
    const time = eventTime(event);
    if (time === null) return;
    const label = event.source === "auto_attacks" ? "AA" : (ABILITY_SLOTS.includes(event.source) ? event.source : "");
    if (!label) return;
    const labels = byTime.get(time) || [];
    if (!labels.includes(label)) labels.push(label);
    byTime.set(time, labels);
  });
  return [...byTime.entries()]
    .sort(([a], [b]) => a - b)
    .slice(0, CHART_MARK_LIMIT)
    .map(([time, slots]) => ({ time, slots, ultimate: slots.includes("R") }));
}

/** Icon strip for one cast marker: real ability icons, a text chip for AA. */
function castMarkIcons(slots) {
  const abilities = new Map((getChampion(state.attacker.champion)?.abilities || []).map((ability) => [ability.slot, ability]));
  return slots.map((slot) => {
    const icon = slot === "AA" ? "" : abilityImage(abilities.get(slot));
    return icon
      ? `<img src="${escapeHtml(icon)}" alt="${escapeHtml(slot)}" title="${escapeHtml(slot)}" />`
      : `<b class="mark-chip" title="${slot === "AA" ? "Auto attack" : escapeHtml(slot)}">${escapeHtml(slot)}</b>`;
  }).join("");
}

/**
 * Cast markers for one build's curve. Build A hangs its icons from the top
 * edge, Build B raises its icons from the bottom edge, so the two rotations
 * stay readable even when their timestamps interleave.
 */
function chartMarksHtml(result, side, duration) {
  return castMarkers(result).map((mark) =>
    `<span class="chart-mark mark-${side}${mark.ultimate ? " is-ult" : ""}" style="left:${((mark.time / duration) * 100).toFixed(2)}%">
      <i></i><span class="mark-icons">${castMarkIcons(mark.slots)}</span>${side === "a" ? `<span class="mark-time">${one(mark.time)}s</span>` : ""}
    </span>`).join("");
}

/** Round an axis top up to a readable 1/2/5-family value. */
function niceCeiling(value) {
  if (!(Number(value) > 0)) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10].find((factor) => value <= factor * magnitude);
  return (step || 10) * magnitude;
}

/** Round an axis floor down to a readable 1/2/5-family value. */
function niceFloor(value) {
  if (!(Number(value) > 0)) return 0;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [10, 7.5, 5, 4, 3, 2.5, 2, 1.5, 1.25, 1].find((factor) => value >= factor * magnitude);
  return (step || 1) * magnitude;
}

/** Cumulative total a series has reached by `time` (0 before its first event). */
function seriesValueAt(series, time) {
  let total = 0;
  for (const point of series.points) {
    if (point.time > time) break;
    total = point.total;
  }
  return total;
}

/**
 * The damage axis floor. Burst rotations park both curves in a narrow band
 * near the top, where a zero-based axis flattens real differences into
 * overlapping hairlines. When both builds have banked at least a quarter of
 * the axis early in the window, the floor rises to a nice value under the
 * lowest landed total — every curve stays fully in frame and the opening
 * burst simply enters from the bottom edge. Sustained ramps keep the zero
 * floor: zooming those would crop half the story.
 */
function chartAxisFloor(seriesList, duration, top) {
  const earlyTotals = seriesList.map((series) => seriesValueAt(series, duration * 0.1));
  const floor = niceFloor(Math.min(...earlyTotals));
  return floor >= top * 0.25 && floor < top ? floor : 0;
}

function polylinePoints(series, duration, top, low = 0) {
  const last = series.points.at(-1);
  // Carry the final total flat to the end of the window: the curve is
  // cumulative, so stopping at the last event would read as damage vanishing.
  const points = last && last.time < duration
    ? [...series.points, { time: duration, total: last.total }]
    : series.points;
  const span = Math.max(top - low, 1e-9);
  return points
    .map((point) => {
      const y = Math.min(200, Math.max(0, 200 - ((point.total - low) / span) * 200));
      return `${((point.time / duration) * 1000).toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

/**
 * Draw the fight timeline: cumulative damage polylines for both builds,
 * cast markers at their real event timestamps, and each build's end value.
 */
function renderFightChart(aResult, bResult) {
  const host = $("timelineChart");
  const title = $("timelineTitle");
  if (!host) return;
  const seriesA = aResult ? mainDamageSeries(aResult) : null;
  const seriesB = bResult ? mainDamageSeries(bResult) : null;
  const hasCurve = (seriesA?.points.length || 0) > 1 || (seriesB?.points.length || 0) > 1;
  if (!hasCurve) {
    if (title) title.textContent = "Fight timeline";
    host.innerHTML = `<p class="chart-empty">The fight timeline appears once the reviewed engine returns an ordered event ledger.</p>`;
    return;
  }
  const times = [...(seriesA?.points || []), ...(seriesB?.points || [])].map((point) => point.time);
  // The axis spans the window the engine actually simulated (its receipt —
  // for a one-rotation-only champion that is the fixed 5s rotation, not the
  // slider), falling back to the configured Window before a receipt exists.
  // An event past the window stretches the axis rather than being clipped.
  const reported = Math.max(
    Number(aResult?.combat?.duration || 0),
    Number(bResult?.combat?.duration || 0),
  );
  const duration = Math.max(reported > 0 ? reported : configuredFightWindow(), ...times, 1);
  const aTotal = mainTotalDamage(aResult);
  const bTotal = bResult ? mainTotalDamage(bResult) : null;
  const top = niceCeiling(Math.max(seriesA?.total || 0, seriesB?.total || 0, aTotal || 0, bTotal || 0, 1));
  const low = chartAxisFloor([seriesA, seriesB].filter(Boolean), duration, top);
  if (title) title.textContent = `Fight timeline · 0 → ${one(duration)} s`;

  const lineB = seriesB ? `<polyline class="line-b" points="${polylinePoints(seriesB, duration, top, low)}" fill="none" stroke-width="2.5" vector-effect="non-scaling-stroke" stroke-linejoin="round"></polyline>` : "";
  const lineA = seriesA ? `<polyline class="line-a" points="${polylinePoints(seriesA, duration, top, low)}" fill="none" stroke-width="2.5" vector-effect="non-scaling-stroke" stroke-linejoin="round"></polyline>` : "";
  const gridX = [250, 500, 750]
    .map((x) => `<line x1="${x}" y1="0" x2="${x}" y2="200" stroke="rgba(22,72,58,.08)" stroke-width="1"></line>`)
    .join("");
  const marks = `${chartMarksHtml(aResult, "a", duration)}${bResult ? chartMarksHtml(bResult, "b", duration) : ""}`;
  const ends = [
    bTotal == null ? "" : `<div class="chart-end is-b" data-chart-focus="b"><strong>${fmt(bTotal)}</strong><span>Build B</span></div>`,
    aTotal == null ? "" : `<div class="chart-end is-a" data-chart-focus="a"><strong>${fmt(aTotal)}</strong><span>Build A</span></div>`,
  ].join("");
  // The curve is drawn from ordered events; a coarse source contributes to
  // TDD without an authored timestamp, so say when the two disagree rather
  // than letting the curve imply it covered everything.
  const uncovered = aTotal == null || !seriesA ? 0 : Math.max(0, aTotal - seriesA.total);
  const note = uncovered > 0.5
    ? `<p class="chart-note">Curve covers ${fmt(seriesA.total)} of Build A's ${fmt(aTotal)} TDD; ${fmt(uncovered)} comes from sources without an authored timestamp.</p>`
    : "";
  host.innerHTML = `<div class="chart-frame">
    <div class="chart-axis"><span>${fmt(top)}</span><span>${fmt((top + low) / 2)}</span><span>${fmt(low)}</span></div>
    <div class="chart-plot">
      <svg viewBox="0 0 1000 200" preserveAspectRatio="none" aria-hidden="true">
        ${gridX}
        <line x1="0" y1="100" x2="1000" y2="100" stroke="rgba(22,72,58,.16)" stroke-width="1"></line>
        ${lineA}${lineB}
      </svg>
      ${marks}
    </div>
    <div class="chart-ends">${ends}</div>
  </div>${note}`;
}

// ---------------------------------------------------------------------------
// Optimizer receipt band
//
// The gap ledger's home for every optimizer outcome: a canvas takeover band
// under the verdict strip, never a toast. `state.optimizer.summary` carries
// the structured receipt; this renders it verbatim, including the notes that
// say a search was withheld or not exhaustive.
// ---------------------------------------------------------------------------

function optimizerReceiptRows(summary) {
  return (summary.lines || [])
    .filter((line) => line && line.value)
    .map((line) => `<div class="buy-line"><span>${escapeHtml(line.label)}</span><strong>${escapeHtml(line.value)}</strong></div>`)
    .join("");
}

function renderBuyBand() {
  const host = $("buyBand");
  if (!host) return;
  if (state.optimizer.running) {
    host.hidden = false;
    host.innerHTML = `<header class="band-head"><p class="band-title">Optimizer</p><p class="band-note" role="status">Searching…</p></header>
      <p class="buy-headline">Scoring legal builds against the coupled event timeline.</p>`;
    return;
  }
  const summary = state.optimizer.summary;
  if (!summary) {
    host.hidden = true;
    host.innerHTML = "";
    return;
  }
  const notes = (summary.notes || []).filter(Boolean)
    .map((note) => `<p class="buy-note">${escapeHtml(note)}</p>`).join("");
  const search = [
    summary.tested ? `${fmt(summary.tested)} ${plural(summary.tested, "candidate")} evaluated` : "",
    summary.elapsedMs ? `${one(summary.elapsedMs / 1000)}s` : "",
  ].filter(Boolean).join(" · ");
  host.hidden = false;
  host.innerHTML = `<header class="band-head">
      <p class="band-title">${escapeHtml(summary.title || "Optimizer result")}</p>
      <p class="band-note">${escapeHtml(summary.applied ? `Applied to ${summary.scope}` : "Nothing applied")}</p>
    </header>
    <p class="buy-headline">${escapeHtml(summary.headline || "")}</p>
    <div class="buy-lines">${optimizerReceiptRows(summary)}</div>
    ${notes}
    <div class="buy-actions">
      ${search ? `<span class="buy-search mono">${escapeHtml(search)}</span>` : ""}
      <button class="buy-dismiss" id="buyDismiss" type="button">Dismiss receipt</button>
    </div>`;
}

function mainTotalDamage(result) {
  if (!result) return null;
  const row = (result.combat?.breakdown || []).find((entry) => entry.participant_id === "main");
  const total = Number(row?.total_damage ?? result.total_damage ?? 0);
  return Number.isFinite(total) ? total : null;
}

function heroValue(value, objectiveKey) {
  if (value == null) return "—";
  if (objectiveDefinition(objectiveKey)?.direction === "lower") return escapeHtml(killTimeLabel(value) || "—");
  const unit = OBJECTIVE_UNITS[objectiveKey] || "";
  return `${fmt(value)}${unit ? `<span class="unit">${escapeHtml(unit)}</span>` : ""}`;
}

function signedGold(delta) {
  if (!delta) return "0g";
  return `${delta > 0 ? "+" : "−"}${fmt(Math.abs(delta))}g`;
}

/**
 * A duel needs a champion and at least one enemy. Items are NOT required:
 * an empty Build A shows as clickable empty slots on the live board (the
 * engine already scores the itemless champion), which beats sending the
 * user back through a checklist whose only open step is "add an item".
 */
function scenarioReady() {
  return Boolean(state.attacker.champion)
    && state.targets.some((target) => target.champion);
}

/**
 * The pre-duel start state: a two-step checklist instead of a ghost duel.
 *
 * Until the scenario is ready there is nothing honest to duel, so the canvas
 * leads with the two moves that get there. Each row opens its rail step
 * through the shared data-step-toggle delegation. Filling the build is not a
 * step: the duel panel that appears next is where that happens.
 */
function renderStartBand(ready) {
  const band = $("startBand");
  if (!band) return;
  // Visibility is owned by applyRailDisclosure (the checklist also yields to
  // the centre editor); this function only fills the content.
  if (ready) return;
  const champion = getChampion(state.attacker.champion);
  const enemies = state.targets.filter((target) => target.champion).length;
  const row = (index, step, done, title, detail) => `
    <button type="button" class="start-step ${done ? "is-done" : ""}" data-step-toggle="${step}">
      <span class="start-index" aria-hidden="true">${done ? "✓" : index}</span>
      <span class="start-copy"><b>${title}</b>${detail ? `<small>${detail}</small>` : ""}</span>
      <span class="step-action">${done ? "Edit" : "Open"}</span>
    </button>`;
  band.innerHTML = `
    <p class="start-kicker">New scenario</p>
    <h2 class="start-title">Set the duel in two steps</h2>
    <div class="start-steps">
      ${row(1, "champion", Boolean(champion),
        champion ? escapeHtml(champion.name) : "Choose your champion",
        champion
          ? `LV ${state.attacker.level}${state.attacker.role ? ` · ${escapeHtml(state.attacker.role)}` : ""}`
          : "The attacker every number is computed for")}
      ${row(2, "roster", enemies > 0,
        enemies > 0 ? `${enemies} ${plural(enemies, "enemy", "enemies")} set` : "Add an enemy",
        enemies > 0 ? "" : "Or use “vs target dummy” for a dummy")}
    </div>
    <p class="start-note">The duel opens when both are set — you fill Build A on its slots there. Objective, gold and window live under Constraints.</p>`;
}

function renderPrototypeResult(aResult = null, bResult = null) {
  const aTotal = aResult ? Number(aResult.combat?.breakdown?.find((row) => row.participant_id === "main")?.total_damage ?? aResult.total_damage ?? 0) : null;
  const bTotal = bResult ? Number(bResult.combat?.breakdown?.find((row) => row.participant_id === "main")?.total_damage ?? bResult.total_damage ?? 0) : null;
  const aValues = aResult ? exactObjectiveMetric(aResult, aTotal) : { overall: null, damage: null, kill: null, survival: null, utility: null };
  const bValues = bResult ? exactObjectiveMetric(bResult, bTotal) : { overall: null, damage: null, kill: null, survival: null, utility: null };
  const aValue = aValues[state.ui.objective];
  const bValue = bValues[state.ui.objective];
  // Layout follows the compare toggle; numbers follow whatever came back.
  const duelling = Boolean(state.attacker.comparisonEnabled);
  const comparing = Boolean(bResult);
  const selectedAvailable = aResult && aValue != null;
  const outcome = comparing
    ? objectiveWinner(aValue, bValue)
    : selectedAvailable
      ? { winner: "A", delta: null }
      : { winner: null, delta: null };
  const objective = selectedObjectiveDefinition();
  const autoPolicy = aResult?.auto_attack_policy || {};
  if (state.fight.aaUptimeMode === "calculated" && autoPolicy.status === "calculated") {
    state.fight.aaUptime = Number(autoPolicy.uptime || 0);
  }
  const coverage = aResult?.timeline_coverage || {};

  // --- verdict strip -------------------------------------------------------
  const qualified = Boolean(aResult) && (coverage.complete === false || autoPolicy.status === "unknown");
  // The middle column of the verdict strip names what it is showing: a delta
  // between two builds, one build's selected objective, or why neither is
  // final yet. "qualified" is the timeline-coverage signal — the not-modeled
  // disclosure below carries the separate mechanics one.
  $("resultStatus").textContent = engine.pending
    ? (duelling ? "recalculating" : "calculating")
    : !aResult
      ? "waiting"
      : qualified ? "qualified" : duelling ? "delta" : "objective";
  $("resultObjective").textContent = objective.label;
  $("winnerLetter").textContent = outcome.winner === "A" ? "A" : outcome.winner === "B" ? "B" : "—";
  $("winnerLabel").textContent = outcome.winner === "tie" ? "tie" : comparing && outcome.winner ? "wins" : selectedAvailable ? "selected" : aResult ? "unavailable" : "waiting";
  const delta = $("resultDelta");
  delta.textContent = outcome.delta == null
    ? (selectedAvailable && !duelling ? objective.label : "—")
    : state.ui.objective === "kill" ? `+${one(outcome.delta)}s` : `+${fmt(outcome.delta)}`;
  delta.classList.toggle("is-tie", outcome.winner === "tie" || outcome.delta == null);
  const goldDelta = buildListPrice("B") - buildListPrice("A");
  const share = comparing && outcome.delta && aValue ? Math.abs(outcome.delta / aValue) * 100 : null;
  $("verdictLine").textContent = !comparing
    ? (selectedAvailable ? "SINGLE BUILD · NO CHALLENGER" : "")
    : outcome.winner === "tie"
      ? "LEVEL ON THE SELECTED OBJECTIVE"
      : outcome.winner
        ? `${outcome.winner} WINS${share == null ? "" : ` · ${percent(share)}`} · ${signedGold(goldDelta)}`
        : "OBJECTIVE UNAVAILABLE";
  $("scoreA").innerHTML = heroValue(aValue, state.ui.objective);
  $("scoreB").innerHTML = heroValue(bValue, state.ui.objective);
  const sideSummary = (side) => {
    const ids = buildIdsForSide(side);
    return ids.length ? `${ids.length} ${plural(ids.length, "ITEM")} · ${fmt(buildListPrice(side))}g` : "NO ITEMS";
  };
  $("verdictSubA").textContent = sideSummary("A");
  $("verdictSubB").textContent = duelling ? sideSummary("B") : "";
  document.querySelector(".verdict")?.classList.toggle("is-solo", !duelling);

  $("resultSummary").textContent = !aResult
    ? "Choose a complete scenario to receive a reviewed comparison."
    : !comparing
      ? selectedAvailable
        ? "Build A is the selected build for this scenario. Enable Build B to compare a second build."
        : `${objective.label} is unavailable until the reviewed event ledger supplies that outcome.`
      : outcome.winner === "tie"
        ? `Build A and Build B are level on ${objective.label.toLowerCase()} against this roster.`
        : outcome.winner
          ? `${outcome.winner === "A" ? "Build A" : "Build B"} carries the strongest ${objective.label.toLowerCase()} package against this roster.`
          : "The selected objective is unavailable for this comparison.";

  // --- start checklist vs live duel ----------------------------------------
  const ready = scenarioReady();
  document.getElementById("canvas")?.classList.toggle("is-start", !ready);
  renderStartBand(ready);

  // --- mirrored builds and delta spine -------------------------------------
  document.querySelector(".duel")?.classList.toggle("is-solo", !duelling);
  renderDuelSide("A");
  if (duelling) renderDuelSide("B");
  const aAlive = enemyHealthRemaining(aResult);
  const bAlive = bResult ? enemyHealthRemaining(bResult) : "";
  $("metricList").innerHTML = SPINE_METRICS
    .map((metric) => spineRowHtml(
      metric,
      aValues[metric.key],
      bValues[metric.key],
      duelling,
      metric.lower ? aAlive : "",
      metric.lower ? bAlive : "",
    ))
    .join("");
  const lowerObjective = Object.values(OBJECTIVES).find((definition) => definition.direction === "lower");
  const directionNote = lowerObjective?.label ? ` Higher is better except ${lowerObjective.label}.` : "";
  $("metricLegend").textContent = duelling
    ? `Bars read Build B against Build A — green ahead, red behind.${directionNote}`
    : `Absolute values for Build A.${directionNote}`;
  $("spineFoot").textContent = duelling && comparing && outcome.winner && outcome.winner !== "tie" && outcome.delta != null
    ? `Gold delta ${signedGold(goldDelta)} · Build ${outcome.winner} leads ${objective.label} by ${objective.direction === "lower" ? `${one(outcome.delta)}s` : fmt(outcome.delta)}.`
    : "";

  // --- team-fight health ---------------------------------------------------
  const participants = prototypeParticipants(aResult);
  const healthDispositions = aResult?.combat?.dispositions || null;
  $("healthRows").innerHTML = participants.map((person, personIndex) => {
    const survival = person.survival || {};
    const max = Number(survival.max_health || survival.effective_health || person.stats?.health || person.health || 0);
    const explicitHealth = survival.ending_health ?? survival.health_remaining ?? survival.current_health;
    const incoming = Number(survival.health_damage ?? survival.incoming_damage ?? 0);
    // A participant the ledger says did not survive the window ends at zero,
    // whatever the last recorded health sample was.
    const health = survival.survived_window === false
      ? 0
      : explicitHealth != null ? Math.max(0, Number(explicitHealth)) : Math.max(0, max - incoming);
    const pct = max > 0 ? Math.max(0, Math.min(100, health / max * 100)) : 0;
    // Every number in this line goes through `leafText`, so a leaf the model
    // refused renders as a named refusal instead of the 0 that `?? 0` above
    // would otherwise have printed as a measurement.
    const healthPath = survivalLeafPath(personIndex, "ending_health");
    const status = survival.survived_window === false
      ? "defeated"
      : leafWithheld(healthPath, healthDispositions)
        ? leafText(null, healthPath, healthDispositions)
        : max > 0
          ? `${escapeHtml(fmt(health))} · ${Math.round(pct)}%`
          : incoming > 0
            ? `−${escapeHtml(fmt(incoming))} dmg`
            : "alive";
    const enemy = person.team === "enemy" || String(person.participant_id || "").startsWith("enemy:");
    return `<div class="health-row ${enemy ? "is-enemy" : ""}"><div class="health-person"><img src="${championImage(person.champion)}" alt="" /><span><strong>${escapeHtml(person.champion || person.participant_id || "Participant")}</strong><small>${escapeHtml(person.team || "participant")}</small></span></div><div class="health-track"><span style="width:${pct}%"></span></div><b>${status}</b></div>`;
  }).join("") || `<p class="roster-empty">Participant health appears after the reviewed engine returns.</p>`;
  renderFightChart(aResult, bResult);
  const participantLabels = new Map((aResult?.combat?.participants || []).map((person) => [person.participant_id, person.champion || person.participant_id]));
  const combatEvents = Array.isArray(aResult?.combat?.events) ? aResult.combat.events : [];
  const healingEvents = healingEventsForResult(aResult);
  const supportEvents = Array.isArray(aResult?.combat?.support_events) ? aResult.combat.support_events : [];
  const duration = Math.max(1, Number(aResult?.combat?.duration || state.fight.duration));
  const eventLabel = (participantId) => participantLabels.get(participantId) || participantId || "Participant";
  $("timeline").innerHTML = renderEventTimeline(combatEvents, duration, eventLabel);
  // data-event-index matches the timeline lane above, so a row and its lane
  // are traceably the same event (#155).
  const eventRows = combatEvents.slice(0, 24).map((event, index) => {
    const time = eventTime(event);
    const timeLabel = time === null ? "time withheld" : `${one(time)}s`;
    const value = Number(event.damage || 0);
    const precision = event.event_precision && event.event_precision !== "exact" ? ` · ${event.event_precision}` : "";
    const source = `${eventLabel(event.attacker)} → ${eventLabel(event.target)} · ${event.source || "event"}${precision}`;
    return `<div class="ledger-line" data-event-index="${index}"><span>${escapeHtml(timeLabel)} · ${escapeHtml(source)}</span><strong>${value > 0 ? `${fmt(value)} damage` : escapeHtml(event.skipped_reason || "No damage")}</strong></div>`;
  });
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
      event.cleanse ? "cleanse" : "",
    ].filter(Boolean).join(" · ");
    return `<div class="ledger-line"><span>${escapeHtml(timeLabel)} · ${escapeHtml(eventLabel(event.attacker))} → ${escapeHtml(recipient)} · ${escapeHtml(event.source || "support")}${details ? ` · ${escapeHtml(details)}` : ""}</span><strong>${fmt(Number(event.applied_amount ?? event.amount ?? 0))} ${escapeHtml(event.kind || "support")} · ${escapeHtml(policy)}</strong></div>`;
  });
  const overflow = combatEvents.length > 24 || healingEvents.length > 12 || supportEvents.length > 12
    ? `<div class="ledger-line"><span>Additional receipts</span><strong>${combatEvents.length > 24 ? combatEvents.length - 24 : 0} damage · ${healingEvents.length > 12 ? healingEvents.length - 12 : 0} healing · ${supportEvents.length > 12 ? supportEvents.length - 12 : 0} support</strong></div>`
    : "";
  const enemyEhp = enemyEffectiveHealth(aResult);
  const overkill = aTotal == null ? 0 : enemyOverkill(aResult, aTotal);
  $("ledgerTable").innerHTML = `<div class="ledger-line"><span>Selected objective</span><strong>${escapeHtml(objective.label)}</strong></div><div class="ledger-line"><span>Event order</span><strong>${escapeHtml(coverage.certification || "pending")}</strong></div><div class="ledger-line"><span>Main output</span><strong>${aTotal == null ? "—" : `${fmt(aTotal)} TDD${overkill > 0 ? ` · ${fmt(overkill)} overkill` : ""}`}</strong></div><div class="ledger-line"><span>Enemy effective HP</span><strong>${enemyEhp > 0 ? fmt(enemyEhp) : "—"}</strong></div>${eventRows.join("")}${healingRows.join("")}${supportRows.join("")}${overflow}`;
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
  renderBuyBand();
  renderScenarioRail();
  $("scenarioSentence").innerHTML = scenarioSentence();
  applyPrerequisiteGates();
  scheduleEngineCalculation();
  scheduleLoadoutStats();
  // Announce the pass: trust labels, staleness and share hydration listen.
  document.dispatchEvent(new Event("scryglass:engine-ready"));
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
    if (pickerContext.type === "item") button.dataset.itemTooltip = String(entry.id);
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
    const dedicatedBoot = isRoleBoot(entry.id);
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
  const requestedLevel = Number(combatant?.level) || 1;
  const level = Math.max(
    1,
    Math.min(
      roleLevelCap(combatant?.role, Boolean(combatant?.roleQuestComplete), requestedLevel),
      requestedLevel,
    ),
  );
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
  const requestedLevel = Number(combatant?.level) || 1;
  const level = Math.max(
    1,
    Math.min(
      roleLevelCap(combatant?.role, Boolean(combatant?.roleQuestComplete), requestedLevel),
      requestedLevel,
    ),
  );
  if (slot === "P") return level;
  const cap = slot === "R" ? (level >= 16 ? 3 : level >= 11 ? 2 : level >= 6 ? 1 : 0) : Math.min(5, Math.floor((level + 1) / 2));
  const hasRequested = Object.prototype.hasOwnProperty.call(combatant?.abilityRanks || {}, slot);
  const requested = hasRequested ? Number(combatant?.abilityRanks?.[slot]) : Number(defaultAbilityRanks(combatant)[slot] || 0);
  return Math.max(0, Math.min(maxRank || (slot === "R" ? 3 : 5), Number.isFinite(requested) ? requested : cap));
}

function bisBackendPayload(path, objective = state.ui.objective) {
  const parts = String(path).split(".");
  const payload = { ...engineFightPayload("A") };
  payload.objective = objectiveDefinition(objective)
    ? objective
    : Object.keys(OBJECTIVES)[0] || objective;
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
  const selectedObjective = bisContext?.path === path && objectiveDefinition(bisContext.objective)
    ? bisContext.objective
    : (objectiveDefinition(state.ui.objective) ? state.ui.objective : Object.keys(OBJECTIVES)[0]);
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
    const objectiveLabel = responseObjective.label
      || objectiveDefinition(selectedObjective)?.label
      || "";
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
  for (let slot = 0; slot < rosterOrdinarySlotCount(loadout); slot += 1) {
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
      kind: "roster",
      title: "Roster optimization",
      scope,
      applied: true,
      tested,
      elapsedMs: performance.now() - started,
      headline: `${scope} optimized from the coupled event timeline.`,
      lines: [{ label: "Rebalanced", value: "Build A was re-solved after each roster change" }],
      notes: [],
    };
  } catch (error) {
    if (activePath) state.optimizer.rosterErrors[activePath] = error.message;
    state.optimizer.summary = {
      kind: "roster",
      title: "Roster optimization · stopped",
      scope: "Roster",
      applied: false,
      tested,
      elapsedMs: performance.now() - started,
      headline: `Optimization stopped: ${error.message}`,
      lines: [],
      notes: ["Earlier slots that already resolved keep their applied items."],
    };
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
        kind: "build",
        title: "Full build search · withheld",
        scope: "Build A",
        applied: false,
        tested: Number(result.evaluations || 0),
        elapsedMs: Number(result.optimization_time_ms || 0),
        headline: "Best in slot withheld — no build applied.",
        lines: [],
        notes: [
          result.search_timeline_coverage?.note || "Event-order coverage is incomplete.",
          withheldDetail.trim(),
        ].filter(Boolean),
      };
      return result;
    }
    const ids = (result.items || []).map((name) => findItemByBackendName(name)?.id || 0);
    state.attacker.buildA = fitItemSlots(ids);
    state.attacker.buildAStacks = state.attacker.buildA.map(() => 0);
    state.attacker.buildAItemOptions = state.attacker.buildA.map(() => ({}));
    state.attacker.questBootA = findItemByBackendName(result.boots)?.id || 0;
    state.optimizer.summary = {
      kind: "build",
      title: "Full build search",
      scope: "Build A",
      applied: true,
      tested: Number(result.evaluations || 0),
      elapsedMs: Number(result.optimization_time_ms || 0),
      headline: (result.items || []).join(" + ") || "Build applied",
      lines: [
        { label: "Boots", value: result.boots || "" },
        { label: "Gold cost", value: result.gold_cost ? `${fmt(result.gold_cost)}g` : "" },
        { label: "Search guarantee", value: String(result.selection_certification || "").replaceAll("_", " ") },
      ],
      notes: [
        result.selection_certification === "event_ordered_local_search"
          ? "Event-ordered local-search build applied; coarse candidates were excluded and time-to-death stops at death."
          : "Coupled event-ordered best in slot: time-to-death is counted only while the champion is alive.",
        result.search_timeline_coverage?.note,
      ].filter(Boolean),
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
        kind: "purchase",
        title: "Best buy",
        scope: "Build A",
        applied: false,
        tested: 0,
        elapsedMs: performance.now() - started,
        headline: `No legal modeled purchase fits ${fmt(state.optimizer.availableGold)} gold.`,
        lines: [{ label: "Available gold", value: `${fmt(state.optimizer.availableGold)}g` }],
        notes: [],
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
    // Every recommended item must land in a visible slot; anything that
    // cannot be placed is reported, never silently dropped.
    const resultNames = result.items || [];
    const mappedIds = resultNames.map((name) => findItemByBackendName(name)?.id || 0);
    const unplaced = resultNames.filter((_, index) => !mappedIds[index]);
    const resultIds = mappedIds.filter(Boolean);
    const slotCap = ordinarySlotCount("A");
    if (resultIds.length > slotCap) unplaced.push(...resultIds.slice(slotCap).map((id) => itemName(id)));
    state.attacker.buildA = fitItemSlots(resultIds);
    state.attacker.buildAStacks = state.attacker.buildA.map((id) => previous.get(itemName(id))?.stack || 0);
    state.attacker.buildAItemOptions = state.attacker.buildA.map((id) => previous.get(itemName(id))?.options || {});
    state.attacker.questBootA = findItemByBackendName(result.boots)?.id || 0;
    const purchase = (result.purchase_items || []).join(" + ");
    const baseTitle = result.recommendation_type === "sell_pivot" ? "Best buy · sell pivot" : "Best buy";
    // The search guarantee is a label, never a reason to withhold: a plan
    // always lands in the build, and the note says how strong the claim is.
    const guaranteeNote = result.exhaustive_within_scope
      ? "Certified best buy — every affordable plan was searched."
      : result.search_guarantee === "purchase_local_search"
        ? "Best plan found by budget-aware local search of the full shop; a better combination may exist."
        : result.truncated
          ? "Search hit its time budget; applying the best plan found so far."
          : "Best plan across the modeled candidates; unmodeled items are excluded from certification.";
    state.optimizer.summary = {
      kind: "purchase",
      title: result.exhaustive_within_scope ? baseTitle : `${baseTitle} · best found`,
      scope: "Build A",
      applied: true,
      tested: Number(result.evaluations || result.candidate_count || 0),
      elapsedMs: Number(result.optimization_time_ms || performance.now() - started),
      headline: purchase
        ? `Buy ${purchase}`
        : (result.recommendation_type === "keep_gold"
          ? "No purchase improves this fight — keep your gold"
          : "Rebalance the current inventory"),
      lines: [
        { label: "Sell", value: soldNames.size ? [...soldNames].join(" + ") : "" },
        { label: "Combines", value: (result.combine_items || []).join(" + ") },
        { label: "Gold spent", value: `${fmt(result.spent_gold)}g` },
        { label: "Sell refund", value: result.sell_refund ? `${fmt(result.sell_refund)}g` : "" },
        { label: "Gold remaining", value: `${fmt(result.remaining_gold)}g` },
        { label: "Boots", value: result.boots || "" },
      ],
      notes: [
        guaranteeNote,
        result.search_timeline_coverage?.note,
        unplaced.length ? `Could not be placed in the build interface: ${unplaced.join(", ")}.` : "",
      ].filter(Boolean),
    };
  } catch (error) {
    state.optimizer.summary = {
      kind: "purchase",
      title: "Best buy · stopped",
      scope: "Build A",
      applied: false,
      tested: 0,
      elapsedMs: performance.now() - started,
      headline: `Best-buy search stopped: ${error.message}`,
      lines: [],
      notes: ["No build was applied."],
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
    state.optimizer.summary = {
      kind: "build",
      title: "Full build search · stopped",
      scope: "Build A",
      applied: false,
      tested: 0,
      elapsedMs: 0,
      headline: `Optimization stopped — no build applied. ${error.message}`,
      lines: [],
      notes: [],
    };
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
  const stepToggle = event.target.closest("[data-step-toggle]");
  if (stepToggle) {
    const step = stepToggle.dataset.stepToggle;
    const next = STEP_IDS.includes(step) && state.ui.expandedStep !== step ? step : null;
    state.ui.expandedStep = next;
    if (next) {
      state.ui.activeStep = next;
      state.ui.expandedConstraint = null;
    }
    applyRailDisclosure();
    if (next === "champion" && !state.attacker.champion) {
      // "Choose your champion" means choose one: the editor opens AND the
      // roster dialog is already up, one click saved.
      return openPicker("champion", "attacker.champion");
    }
    if (next) {
      document.getElementById(stepToggle.getAttribute("aria-controls") || "")?.querySelector("button, select, input, a")?.focus();
    } else {
      document.querySelector(`#step${state.ui.activeStep[0].toUpperCase()}${state.ui.activeStep.slice(1)} [data-step-toggle]`)?.focus();
    }
    return;
  }
  if (
    state.ui.expandedStep
    && event.target.closest("#appGrid")
    && !event.target.closest(".rail")
    && !event.target.closest("#startEditor")
  ) {
    // Clicking the canvas while a step editor is open closes it, same as
    // Done — and the click still does whatever it hit (a constraint row,
    // the compare toggle), so this never swallows a live control. While the
    // rail editor is open the canvas is inert, so only the grid itself can
    // be the target. Dialog clicks land outside #appGrid entirely.
    state.ui.expandedStep = null;
    applyRailDisclosure();
  }
  if (event.target.closest("#buyDismiss")) {
    state.optimizer.summary = null;
    renderBuyBand();
    return;
  }
  const constraintToggle = event.target.closest("[data-constraint-toggle]");
  if (constraintToggle) {
    const row = constraintToggle.dataset.constraintToggle;
    state.ui.expandedConstraint = state.ui.expandedConstraint === row ? null : row;
    applyRailDisclosure();
    return;
  }
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
      : roleLevelCap(
        rosterLoadout?.role,
        Boolean(rosterLoadout?.roleQuestComplete),
        rosterLoadout?.level,
      );
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
    state.ui.objective = objectiveDefinition(objectiveButton.dataset.objective)
      ? objectiveButton.dataset.objective
      : Object.keys(OBJECTIVES)[0] || state.ui.objective;
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
    state.targets.push({ champion: null, level: 1, role: "", roleQuestComplete: false, items: [0, 0, 0, 0, 0, 0], itemStacks: [0, 0, 0, 0, 0, 0], itemOptions: [{}, {}, {}, {}, {}, {}], boots: 0, includeBoots: true, abilityRanks: {}, championOptions: {} });
    render();
    return openPicker("champion", `targets.${index}.champion`);
  }
  if (event.target.closest("#addPracticeEnemy")) {
    if (state.targets.length >= 5 || state.targets.some(isPracticeDummy)) return;
    const present = new Set(state.targets.map((target) => target.champion));
    const practice = PRACTICE_TARGETS.find((candidate) => !present.has(candidate.champion));
    if (!practice) return;
    state.targets.push({
      kind: PRACTICE_DUMMY_KIND,
      isPracticeDummy: true,
      champion: practice.champion,
      level: PRACTICE_DUMMY_LEVEL,
      role: "",
      roleQuestComplete: false,
      items: [0, 0, 0, 0, 0, 0],
      itemStacks: [0, 0, 0, 0, 0, 0],
      itemOptions: [{}, {}, {}, {}, {}, {}],
      boots: 0,
      includeBoots: false,
      abilityRanks: {},
      championOptions: {},
      targetStats: { ...PRACTICE_DUMMY_STATS },
      targetStatOverrides: {},
    });
    invalidateOptimization();
    return render();
  }
  if (event.target.closest("#addAlly")) {
    if (state.allies.length >= 4) return;
    const index = state.allies.length;
    state.allies.push({ champion: null, level: 1, role: "", roleQuestComplete: false, items: [0, 0, 0, 0, 0, 0], itemStacks: [0, 0, 0, 0, 0, 0], itemOptions: [{}, {}, {}, {}, {}, {}], boots: 0, includeBoots: true, abilityRanks: {}, championOptions: {}, allyEffectsEnabled: false });
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
          ? "Best-in-slot needs an enemy roster — add an enemy or use “vs target dummy” first."
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
    syncGlobalFormVariants(slot, input.variant);
    return render();
  }
  const resetDummyStats = event.target.closest("[data-reset-dummy-stats]");
  if (resetDummyStats) {
    const loadout = pathValue(resetDummyStats.dataset.resetDummyStats);
    if (!isPracticeDummy(loadout)) return;
    loadout.targetStats = { ...PRACTICE_DUMMY_STATS };
    loadout.targetStatOverrides = {};
    invalidateOptimization();
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
      state.targets.push({ champion: null, level: 1, role: "", roleQuestComplete: false, items: [0, 0, 0, 0, 0, 0], itemStacks: [0, 0, 0, 0, 0, 0], itemOptions: [{}, {}, {}, {}, {}, {}], boots: 0, includeBoots: true, abilityRanks: {}, championOptions: {} });
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
      state.allies.push({ champion: null, level: 1, role: "", roleQuestComplete: false, items: [0, 0, 0, 0, 0, 0], itemStacks: [0, 0, 0, 0, 0, 0], itemOptions: [{}, {}, {}, {}, {}, {}], boots: 0, includeBoots: true, abilityRanks: {}, championOptions: {}, allyEffectsEnabled: false });
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
  const dummyStat = event.target.closest("[data-dummy-stat]");
  if (dummyStat) {
    const parts = dummyStat.dataset.dummyStat.split(".");
    const loadout = state[parts[0]]?.[Number(parts[1])];
    const key = parts.at(-1);
    const parsed = Number(dummyStat.value);
    if (!loadout || !isPracticeDummy(loadout) || !Object.prototype.hasOwnProperty.call(PRACTICE_DUMMY_STATS, key)) return;
    if (!Number.isFinite(parsed)) {
      dummyStat.value = practiceDummyStatValue(loadout, key);
      return;
    }
    if (!loadout.targetStats) loadout.targetStats = { ...PRACTICE_DUMMY_STATS };
    if (!loadout.targetStatOverrides) loadout.targetStatOverrides = {};
    loadout.targetStats[key] = parsed;
    loadout.targetStatOverrides[key] = parsed;
    invalidateOptimization();
    return render();
  }
  const economicsGold = event.target.closest("#economicsGold");
  if (economicsGold) {
    const value = Number.parseInt(economicsGold.value, 10);
    state.optimizer.availableGold = Number.isInteger(value) ? Math.max(0, Math.min(30_000, value)) : 0;
    return render();
  }
  const enemyHits = event.target.closest("#enemyHitsToggle");
  if (enemyHits) {
    state.fight.enemiesAttack = Boolean(enemyHits.checked);
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

// Hovering a build's cumulative-damage label spotlights its curve on the
// fight timeline and greys the other one out (CSS owns the treatment).
{
  const chartHost = $("timelineChart");
  if (chartHost) {
    chartHost.addEventListener("pointerover", (event) => {
      const end = event.target.closest("[data-chart-focus]");
      if (!end) return;
      chartHost.classList.toggle("is-focus-a", end.dataset.chartFocus === "a");
      chartHost.classList.toggle("is-focus-b", end.dataset.chartFocus === "b");
    });
    chartHost.addEventListener("pointerout", (event) => {
      const end = event.target.closest("[data-chart-focus]");
      if (!end || end.contains(event.relatedTarget)) return;
      chartHost.classList.remove("is-focus-a", "is-focus-b");
    });
  }
}

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
  fetch("/api/config").then((response) => response.ok ? response.json() : { item_options: {}, champion_options: {}, keystones: [], input_limits: {} }),
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
      if (champion) {
        champion.engineRegistration = entry.engine_registration || null;
        champion.supportedFightModes = entry.supported_fight_modes || null;
        champion.fightModeReason = entry.unsupported_fight_mode_reason || "";
      }
      engine.availability.set(entry.name, entry.availability || {});
      if (entry.availability?.ready && entry.engine_registration === "reviewed_module") engine.reviewed.add(entry.name);
      if (entry.engine_backend_enabled) engine.backend.add(entry.name);
    });
    engine.itemOptions = config.item_options || {};
    engine.championOptions = config.champion_options || {};
    engine.capabilities = config.capabilities || { participants: {}, scenario: { fields: {} } };
    applyControlCapabilities();
    maybeInitConsentAnalytics();
    engine.keystones = config.keystones || [];
    engine.defaultTarget = config.default_target || engine.defaultTarget;
    engine.fightDefaults = config.fight_defaults || {};
    engine.exclusivityGroups = config.exclusivity_groups || {};
    engine.roleQuest = config.role_quest || {};
    applyDomainContract(config.domain_contract || {});
    engine.boots = Array.isArray(bootCatalog) ? bootCatalog : [];
    engine.bootIds = new Set(engine.boots.map((item) => Number(item.id)).filter((id) => id > 0));
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
// Build sharing + trust labels
// A self-contained layer on top of the analyst engine above. It owns:
//   - build sharing (POST /api/builds + POST /api/share + ?share=<token>)
//   - trust chips (GET /api/certainty, GET /api/not-modeled) with a
//     contract-shaped mock fallback until the P7 backend routes deploy.
// (The casual Quick view that used to live here left with its DOM in
// 2026-08; the analyst view is the app.)
// ============================================================================

// One League Practice Tool target dummy. The array name stays stable for
// shared frontend contracts that already inspect this affordance.
const PRACTICE_TARGETS = [
  { kind: PRACTICE_DUMMY_KIND, champion: PRACTICE_DUMMY_NAME, level: PRACTICE_DUMMY_LEVEL },
];

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
  const champion = state.attacker.champion || "";
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
  const panel = document.getElementById("notModeledPanel");
  const items = NOT_MODELED_STATE.items || [];
  if (panel) {
    // Product principle 6: the qualified-result marker is visible *when
    // relevant*. A permanent band saying "nothing is unmodeled" trains the
    // reader to ignore it, so the marker only exists when the list does.
    panel.hidden = !champion || !items.length;
    if (panel.hidden) panel.open = false;
    document.getElementById("notModeledList").innerHTML = items
      .map((item) => `<li>${escapeHtml(item)}</li>`)
      .join("");
  }
}

function postJson(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function mintShareUrl(payload, slug) {
  // /api/builds stores ability_ranks in a dedicated JSON column and rejects
  // null, while /api/calculate needs null for level-derived transform kits
  // transform kits. Save the empty object (level-derived for every kit) and
  // let the read-only renderer restore null for those kits.
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
  } catch {
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
    const column = document.getElementById("banners") || document.querySelector(".canvas");
    if (!column) return;
    column.prepend(host);
  }
  host.textContent = message;
}

/** Freeze or release the analyst builder while a shared build is on screen. */
function setSharedReadOnly(readOnly) {
  const analyst = document.getElementById("analystView");
  if (analyst) analyst.classList.toggle("is-shared", readOnly);
  const builder = document.querySelector(".rail-steps");
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
    window.scrollTo({ top: 0 });
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
  const nextA = fitItemSlots(itemIds);
  state.attacker.buildA = nextA;
  state.attacker.buildAStacks = nextA.map(() => 0);
  state.attacker.buildAItemOptions = nextA.map(() => ({}));
  const bootName = request.boots || "";
  const bootId = bootName ? (findItemByBackendName(bootName) || {}).id || 0 : 0;
  state.attacker.questBootA = bootId;
  state.attacker.includeBootsA = bootName ? Boolean(bootId) : true;
  state.attacker.keystoneA = "";
  state.attacker.abilityInputs = {};
  state.attacker.championOptions = {};
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
      const practiceDummy = entry?.kind === PRACTICE_DUMMY_KIND
        || entry?.is_practice_dummy
        || entry?.champion === PRACTICE_DUMMY_NAME;
      const ids = fitItemSlots(
        (entry.items || [])
          .map((name) => (findItemByBackendName(name) || {}).id || 0)
          .filter(Boolean),
      );
      const rosterBoot = (findItemByBackendName(entry.boots || "") || {}).id || 0;
      const targetStatOverrides = practiceDummy && entry.target_stats && typeof entry.target_stats === "object"
        ? Object.fromEntries(
          Object.entries(entry.target_stats).map(([key, value]) => [key, Number(value)]),
        )
        : {};
      roster.push({
        kind: practiceDummy ? PRACTICE_DUMMY_KIND : "champion",
        isPracticeDummy: practiceDummy,
        champion: entry.champion || "",
        level: practiceDummy ? PRACTICE_DUMMY_LEVEL : Number(entry.level || 18),
        role: practiceDummy ? "" : entry.role || "",
        roleQuestComplete: practiceDummy ? false : Boolean(entry.role_quest_complete),
        items: ids,
        itemStacks: ids.map(() => 0),
        itemOptions: ids.map(() => ({})),
        boots: practiceDummy ? 0 : rosterBoot,
        includeBoots: practiceDummy ? false : entry.include_boots !== false,
        abilityRanks: {},
        championOptions: {},
        allyEffectsEnabled: practiceDummy ? false : entry.ally_effects_enabled !== false,
        targetStats: { ...PRACTICE_DUMMY_STATS, ...targetStatOverrides },
        targetStatOverrides,
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
  state.fight.enemiesAttack = fightParams.enemies_attack !== false;
  engine.responses = null;
  // A shared build was authored under one role-quest state; re-normalize the
  // restored quest boot and support items so an illegal stage never renders
  // in the editor.  The backend remains the authority for the tier contract.
  normalizeAttackerBootsForRole();
  normalizeAttackerSupportItemsForRole();
  render();
}

// --- Share controls ---------------------------------------------------------

/**
 * Wire every build-sharing control and honor a ?share= token.
 *
 * Issue #147: this wiring once rode along with the removed quick view's
 * initializer and silently died with it. Sharing is its own concern with its
 * own initializer, and it depends on nothing but the analyst view.
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
      } catch {
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

// render() announces every pass as scryglass:engine-ready; trust labels
// follow the selected champion off that signal (loadTrustLabels self-guards
// against repeat fetches for the same champion).
document.addEventListener("scryglass:engine-ready", () => {
  loadTrustLabels(state.attacker.champion || "");
});

initShareControls();


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
  } catch {
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
    } catch {
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
