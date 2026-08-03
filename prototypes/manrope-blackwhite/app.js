const patch = "15.15.1";
const imageRoot = `https://ddragon.leagueoflegends.com/cdn/${patch}/img`;

const champions = {
  Akali: { title: "the Rogue Assassin", key: "Akali", hp: 600, hpPerLevel: 119, ad: 62, armor: 23, mr: 37, ap: 45, resource: 200, abilities: ["P", "Q", "W", "E", "R"] },
  Aatrox: { title: "the Darkin Blade", key: "Aatrox", hp: 650, hpPerLevel: 114, ad: 60, armor: 38, mr: 32, ap: 0, resource: 0, abilities: ["P", "Q", "W", "E", "R"] },
  Jinx: { title: "the Loose Cannon", key: "Jinx", hp: 630, hpPerLevel: 105, ad: 59, armor: 26, mr: 30, ap: 0, resource: 260, abilities: ["P", "Q", "W", "E", "R"] },
  Braum: { title: "the Heart of the Freljord", key: "Braum", hp: 610, hpPerLevel: 112, ad: 55, armor: 35, mr: 32, ap: 0, resource: 311, abilities: ["P", "Q", "W", "E", "R"] },
  Orianna: { title: "the Lady of Clockwork", key: "Orianna", hp: 585, hpPerLevel: 110, ad: 44, armor: 20, mr: 30, ap: 0, resource: 418, abilities: ["P", "Q", "W", "E", "R"] },
  Ambessa: { title: "Matriarch of War", key: "Ambessa", hp: 630, hpPerLevel: 110, ad: 63, armor: 35, mr: 32, ap: 0, resource: 200, abilities: ["P", "Q", "W", "E", "R"] },
  Lulu: { title: "the Fae Sorceress", key: "Lulu", hp: 565, hpPerLevel: 92, ad: 47, armor: 29, mr: 30, ap: 0, resource: 350, abilities: ["P", "Q", "W", "E", "R"] }
};

const abilities = {
  P: "Assassin's Mark", Q: "Five Point Strike", W: "Twilight Shroud", E: "Shuriken Flip", R: "Perfect Execution"
};

const items = {
  "Luden's Echo": { id: 6655, stat: "105 AP", value: 26 },
  "Zhonya's Hourglass": { id: 3157, stat: "105 AP · 50 Armor", value: 24 },
  Shadowflame: { id: 4645, stat: "110 AP · 15 Magic pen", value: 28 },
  "Sorcerer's Shoes": { id: 3020, stat: "12 Magic pen", value: 14, boots: true },
  "Liandry's Torment": { id: 6653, stat: "70 AP · 300 HP", value: 31 },
  Riftmaker: { id: 3116, stat: "70 AP · 350 HP", value: 29 },
  "Void Staff": { id: 3135, stat: "95 AP · 40% pen", value: 27 },
  "Mercury's Treads": { id: 3111, stat: "25 MR · 30 tenacity", value: 10, boots: true },
  "Unending Despair": { id: 2502, stat: "400 HP · 50 Armor", value: 18 },
  "Spirit Visage": { id: 3065, stat: "400 HP · 50 MR", value: 20 }
};

const state = {
  champion: "Akali",
  level: 8,
  role: "Mid",
  objective: "overall",
  stateMode: "theory",
  quest: false,
  boots: true,
  rotations: 1,
  uptime: 25,
  abilityRanks: { P: 1, Q: 3, W: 1, E: 1, R: 1 },
  builds: {
    a: ["Luden's Echo", "Zhonya's Hourglass", "Shadowflame", "Sorcerer's Shoes", null, null],
    b: ["Liandry's Torment", "Riftmaker", "Zhonya's Hourglass", "Sorcerer's Shoes", null, null]
  },
  enemies: ["Orianna", "Ambessa"],
  allies: ["Braum"]
};

const $ = (id) => document.getElementById(id);
const champImage = (name) => `${imageRoot}/champion/${champions[name]?.key || name}.png`;
const itemImage = (name) => `${imageRoot}/item/${items[name]?.id || 0}.png`;
const number = (value) => Math.round(value).toLocaleString("en-US");

function setImage(img, src, alt) {
  img.src = src;
  img.alt = alt;
  img.onerror = () => { img.removeAttribute("src"); img.classList.add("image-missing"); };
}

function scores() {
  const buildValues = Object.fromEntries(["a", "b"].map((side) => [side, state.builds[side].reduce((sum, item) => sum + (items[item]?.value || 0), 0)]));
  const base = state.level * 80 + state.enemies.length * 38 + state.allies.length * 12 + (state.stateMode === "live" ? 17 : 0);
  const objectiveWeight = { overall: [1, 1], kill: [1.08, 1.17], survival: [0.92, 1.05], damage: [1.03, 1.12], utility: [0.98, 1.08] }[state.objective];
  const a = Math.round((base + buildValues.a * objectiveWeight[0] + state.uptime * 1.6 + state.rotations * 18));
  const b = Math.round((base + buildValues.b * objectiveWeight[1] + state.uptime * 1.4 + state.rotations * 22));
  return { a, b, delta: Math.abs(a - b), winner: a >= b ? "a" : "b" };
}

function renderChampionOptions() {
  $("championSelect").innerHTML = Object.keys(champions).map((name) => `<option ${name === state.champion ? "selected" : ""}>${name}</option>`).join("");
}

function renderChampion() {
  const champion = champions[state.champion];
  $("championName").textContent = state.champion;
  $("championTitle").textContent = champion.title;
  setImage($("championImage"), champImage(state.champion), state.champion);
  $("levelInput").value = state.level;
  $("questToggle").textContent = state.quest ? "Quest on" : "Quest off";
  $("questToggle").setAttribute("aria-pressed", String(state.quest));
  $("bootsToggle").textContent = state.boots ? "Boots on" : "Boots off";
  $("bootsToggle").setAttribute("aria-pressed", String(state.boots));
  const level = state.level - 1;
  const stats = [
    ["HP", champion.hp + champion.hpPerLevel * level], ["Bonus HP", state.builds.a.reduce((sum, item) => sum + ((items[item]?.stat.match(/(\d+) HP/) || [0, 0])[1] * 1), 0)],
    ["Total HP", champion.hp + champion.hpPerLevel * level + 110], ["Resource", champion.resource], ["Attack damage", champion.ad + level * 3],
    ["Ability power", champion.ap + (state.builds.a.includes("Luden's Echo") ? 105 : 0)], ["Armor", champion.armor + level * 4.2], ["Magic resist", champion.mr + level * 1.3], ["Attack speed", "0.7"], ["Move speed", state.boots ? "390" : "345"], ["Ability haste", state.builds.a.includes("Zhonya's Hourglass") ? 10 : 0], ["Crit chance", "0%"]
  ];
  $("statsGrid").innerHTML = stats.map(([label, value]) => `<div class="stat"><span>${label}</span><strong>${typeof value === "number" ? number(value) : value}</strong></div>`).join("");
  $("stateReadout").textContent = `${state.stateMode === "live" ? "7:00 · 2,100g" : "7:00 · 2,100g"} · ${state.stateMode}`;
  $("roleSelect").value = state.role;
}

function renderAbilities() {
  $("abilityRow").innerHTML = abilities ? Object.entries(abilities).map(([slot, name]) => `<article class="ability-card"><div class="ability-icon"><span>${slot}</span></div><div><strong>${name}</strong><small>Wiki formula</small></div><div class="ability-rank"><button type="button" data-ability-slot="${slot}" data-delta="-1" aria-label="Decrease ${slot} rank">−</button><output>${state.abilityRanks[slot]}</output><button type="button" data-ability-slot="${slot}" data-delta="1" aria-label="Increase ${slot} rank">+</button></div></article>`).join("") : "";
}

function renderSlots(side) {
  const isBoot = (item) => item && items[item]?.boots;
  $(side === "a" ? "slotsA" : "slotsB").innerHTML = state.builds[side].map((item, index) => {
    if (!item) return `<button class="slot empty-slot" type="button" data-side="${side}" data-slot="${index}"><span>+</span><small>Add item</small></button>`;
    return `<button class="slot" type="button" data-side="${side}" data-slot="${index}" title="${item}"><span class="item-badge">${side.toUpperCase()}</span><img src="${itemImage(item)}" alt="${item}" /><strong>${item}</strong><small>${items[item].stat}${isBoot(item) ? " · boots" : ""}</small></button>`;
  }).join("");
}

function renderBuilds() {
  renderSlots("a"); renderSlots("b");
  const result = scores();
  $("buildAScore").textContent = number(result.a);
  $("buildBScore").textContent = number(result.b);
  $("winnerCaption").textContent = `${result.winner === "b" ? "winner · " : "lead · "}${state.objective}`;
  document.querySelector(".build-a").classList.toggle("is-winner", result.winner === "a");
  document.querySelector(".build-b").classList.toggle("is-winner", result.winner === "b");
}

function renderRoster(kind) {
  const names = state[kind];
  $(kind).innerHTML = names.map((name, index) => `<article class="roster-card"><img src="${champImage(name)}" alt="${name}" /><div><strong>${name}</strong><span>${champions[name].title}</span><div class="roster-meta">Lv ${state.level} · full participant</div></div><button class="remove-roster" type="button" data-kind="${kind}" data-index="${index}" aria-label="Remove ${name}">×</button></article>`).join("");
  $(kind === "enemies" ? "enemyCount" : "allyCount").textContent = names.length;
}

function renderResult() {
  const result = scores();
  const winnerName = result.winner === "a" ? "Build A" : "Build B";
  const objectiveName = state.objective[0].toUpperCase() + state.objective.slice(1);
  $("resultObjective").textContent = objectiveName;
  $("winnerLetter").textContent = result.winner.toUpperCase();
  $("winnerLabel").textContent = "wins";
  $("resultDelta").textContent = `+${number(result.delta)}`;
  $("resultSummary").textContent = `${winnerName} carries the strongest ${state.objective} package against this roster.`;
  $("metricLegend").textContent = "A / B · higher is better except Kill time";
  $("scoreA").textContent = number(result.a); $("scoreB").textContent = number(result.b);
  const metrics = [
    ["Overall", result.a, result.b], ["Kill time", 7.4, 6.8], ["Survival", 2218, 2076], ["Damage", result.a, result.b], ["Utility", 240, 260]
  ];
  $("metricList").innerHTML = metrics.map(([label, a, b]) => {
    const lowerIsBetter = label === "Kill time";
    const lead = lowerIsBetter ? (a <= b ? "A" : "B") : (a >= b ? "A" : "B");
    return `<div class="metric-row"><span>${label}</span><strong class="metric-a">${typeof a === "number" && a % 1 ? a.toFixed(1) : number(a)}</strong><strong class="metric-b">${typeof b === "number" && b % 1 ? b.toFixed(1) : number(b)}</strong><b>${lead}</b></div>`;
  }).join("");
  const participants = [{ name: state.champion, kind: "main", hp: result.winner === "a" ? 66 : 73 }, ...state.enemies.map((name, index) => ({ name, kind: "enemy", hp: Math.max(0, 21 - index * 16) })), ...state.allies.map((name) => ({ name, kind: "ally", hp: 62 }))];
  $("healthRows").innerHTML = participants.map((person) => `<div class="health-row"><div class="health-person"><img src="${champImage(person.name)}" alt="" /><span><strong>${person.name}</strong><small>${person.kind}</small></span></div><div class="health-track"><span style="width:${person.hp}%"></span></div><b>${person.hp === 0 ? "defeated" : `${person.hp}%`}</b></div>`).join("");
  $("timeline").innerHTML = `<div class="timeline-axis"><span>0:00</span><span>0:01</span><span>0:03</span><span>0:05</span><span>0:07</span><span>0:10</span></div><div class="timeline-row"><span class="timeline-label">${state.champion}</span><div class="timeline-line"><i style="left:12%">Q</i><i style="left:32%">P</i><i style="left:56%">E</i><i style="left:74%">R</i></div></div><div class="timeline-row"><span class="timeline-label">${state.enemies[0] || "Enemy"}</span><div class="timeline-line muted-line"><i style="left:34%">E</i><i style="left:69%">R</i></div></div>`;
  $("ledgerTable").innerHTML = `<div class="ledger-line"><span>Damage before defeat</span><strong>${number(result.a + result.b)}</strong></div><div class="ledger-line"><span>${state.enemies[0] || "Enemy"} · health at end</span><strong>${participants[1]?.hp === 0 ? "defeated" : `${participants[1]?.hp || 0}%`}</strong></div>`;
}

function renderAll() { renderChampionOptions(); renderChampion(); renderAbilities(); renderBuilds(); renderRoster("enemies"); renderRoster("allies"); renderResult(); }

function openPicker(kind, side, slot) {
  const dialog = $("pickerDialog");
  $("pickerLabel").textContent = kind === "item" ? "Build slot" : kind === "enemy" ? "Enemy roster" : "Allied context";
  $("pickerTitle").textContent = kind === "item" ? "Choose an item" : "Add a champion";
  const choices = kind === "item" ? Object.keys(items) : Object.keys(champions);
  $("pickerGrid").innerHTML = choices.map((choice) => kind === "item" ? `<button class="picker-choice" type="button" data-choice="${choice}"><img src="${itemImage(choice)}" alt="" /><span><strong>${choice}</strong><small>${items[choice].stat}</small></span></button>` : `<button class="picker-choice" type="button" data-choice="${choice}"><img src="${champImage(choice)}" alt="" /><span><strong>${choice}</strong><small>${champions[choice].title}</small></span></button>`).join("");
  dialog.showModal();
  dialog.querySelectorAll("[data-choice]").forEach((button) => button.addEventListener("click", () => {
    const choice = button.dataset.choice;
    if (kind === "item") state.builds[side][slot] = choice;
    else if (!state[kind === "enemy" ? "enemies" : "allies"].includes(choice)) state[kind === "enemy" ? "enemies" : "allies"].push(choice);
    dialog.close(); renderAll();
  }));
}

document.addEventListener("click", (event) => {
  const abilityRank = event.target.closest("[data-ability-slot][data-delta]");
  if (abilityRank) {
    const slot = abilityRank.dataset.abilitySlot;
    const maxRank = slot === "R" ? 3 : slot === "P" ? 1 : 5;
    state.abilityRanks[slot] = Math.max(1, Math.min(maxRank, state.abilityRanks[slot] + Number(abilityRank.dataset.delta)));
    renderAbilities();
  }
  const objective = event.target.closest("[data-objective]");
  if (objective) {
    state.objective = objective.dataset.objective;
    document.querySelectorAll(".objective").forEach((button) => {
      const selected = button === objective;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    renderBuilds(); renderResult();
  }
  const slot = event.target.closest("[data-side][data-slot]");
  if (slot) openPicker("item", slot.dataset.side, Number(slot.dataset.slot));
  const remove = event.target.closest("[data-kind][data-index]");
  if (remove) { state[remove.dataset.kind].splice(Number(remove.dataset.index), 1); renderAll(); }
  const copy = event.target.closest("[data-copy]");
  if (copy) { const from = copy.dataset.copy; const to = from === "a" ? "b" : "a"; state.builds[to] = [...state.builds[from]]; renderAll(); }
  if (event.target.closest("#bisButton")) {
    const slot = state.builds.a.findIndex((item) => !item);
    openPicker("item", "a", slot === -1 ? 0 : slot);
  }
});

$("championSelect").addEventListener("change", (event) => { state.champion = event.target.value; renderAll(); });
$("roleSelect").addEventListener("change", (event) => { state.role = event.target.value; renderChampion(); });
$("levelInput").addEventListener("change", (event) => { state.level = Math.min(18, Math.max(1, Number(event.target.value) || 1)); renderChampion(); renderResult(); });
$("questToggle").addEventListener("click", () => { state.quest = !state.quest; renderChampion(); });
$("bootsToggle").addEventListener("click", () => { state.boots = !state.boots; renderChampion(); renderResult(); });
$("stateTheory").addEventListener("click", () => { state.stateMode = "theory"; $("stateTheory").classList.add("active"); $("stateLive").classList.remove("active"); renderChampion(); renderBuilds(); renderResult(); });
$("stateLive").addEventListener("click", () => { state.stateMode = "live"; $("stateLive").classList.add("active"); $("stateTheory").classList.remove("active"); renderChampion(); renderBuilds(); renderResult(); });
$("addEnemy").addEventListener("click", () => openPicker("enemy"));
$("addAlly").addEventListener("click", () => openPicker("ally"));
$("rotationRange").addEventListener("input", (event) => { state.rotations = Number(event.target.value); $("rotationOutput").textContent = state.rotations; renderBuilds(); renderResult(); });
$("uptimeRange").addEventListener("input", (event) => { state.uptime = Number(event.target.value); $("uptimeOutput").textContent = `${state.uptime}%`; renderBuilds(); renderResult(); });

renderAll();
