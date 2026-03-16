document.addEventListener("DOMContentLoaded", () => {
    // === DOM References ===
    const championSelect = document.getElementById("champion-select");
    const championIcon = document.getElementById("champion-icon");
    const championPlaceholder = document.getElementById("champion-placeholder");
    const levelSlider = document.getElementById("level-slider");
    const levelDisplay = document.getElementById("level-display");
    const targetBaseHealth = document.getElementById("target-base-health");
    const targetBonusHealth = document.getElementById("target-bonus-health");
    const targetTotalHealth = document.getElementById("target-total-health");
    const targetArmor = document.getElementById("target-armor");
    const targetMr = document.getElementById("target-mr");
    const fightModeRadios = document.querySelectorAll('input[name="fight-mode"]');
    const fightTabs = document.querySelectorAll(".fight-tab");
    const timeBasedOptions = document.getElementById("time-based-options");
    const fightDuration = document.getElementById("fight-duration");
    const durationDisplay = document.getElementById("duration-display");
    const includeAutos = document.getElementById("include-autos");
    const uptimeOptions = document.getElementById("uptime-options");
    const autoUptime = document.getElementById("auto-uptime");
    const uptimeDisplay = document.getElementById("uptime-display");
    const calculateBtn = document.getElementById("calculate-btn");
    const btnText = calculateBtn.querySelector(".btn-text");
    const btnLoading = calculateBtn.querySelector(".btn-loading");
    const autoAttacksOnly = document.getElementById("auto-attacks-only");
    const includeActives = document.getElementById("include-actives");
    const autoRankCheckbox = document.getElementById("auto-rank");
    const abilitiesBar = document.getElementById("abilities-bar");
    const autoCastOrderCheckbox = document.getElementById("auto-cast-order");
    const castOrderContainer = document.getElementById("cast-order-container");
    const castOrderSelects = [
        document.getElementById("cast-order-1"),
        document.getElementById("cast-order-2"),
        document.getElementById("cast-order-3"),
        document.getElementById("cast-order-4"),
    ];

    // Result elements
    const resultsPlaceholder = document.getElementById("results-placeholder");
    const resultsContent = document.getElementById("results-content");
    const errorDisplay = document.getElementById("error-display");
    const errorMessage = document.getElementById("error-message");

    // Item picker elements
    const pickerOverlay = document.getElementById("item-picker-overlay");
    const pickerTitle = document.getElementById("picker-title");
    const pickerSearch = document.getElementById("picker-search");
    const pickerGrid = document.getElementById("picker-grid");
    const pickerClose = document.getElementById("picker-close");

    // Champion picker elements
    const champPickerOverlay = document.getElementById("champion-picker-overlay");
    const champPickerSearch = document.getElementById("champion-picker-search");
    const champPickerGrid = document.getElementById("champion-picker-grid");
    const champPickerClose = document.getElementById("champion-picker-close");
    const championPortraitBtn = document.getElementById("champion-portrait-btn");
    const championNameDisplay = document.getElementById("champion-name-display");
    const championNameText = document.getElementById("champion-name-text");

    // Champion options elements
    const championOptionsBtn = document.getElementById("champion-options-btn");
    const championOptionsPanel = document.getElementById("champion-options-panel");
    const championOptionsClose = document.getElementById("champion-options-close");
    const championOptionsContent = document.getElementById("champion-options-content");

    // === State ===
    let championsData = [];
    let itemsData = [];
    let bootsData = [];
    let itemIconMap = {};
    let hasCalculated = false;
    let isCalculating = false;
    let recalcTimer = null;

    // Track which items are selected in which slots
    // slots: { boots: "", 1: "", 2: "", 3: "", 4: "", 5: "", 6: "" }
    let selectedItems = { boots: "", 1: "", 2: "", 3: "", 4: "", 5: "", 6: "" };
    let activePickerSlot = null;

    // === Populate data ===

    fetch("/api/champions")
        .then((res) => res.json())
        .then((data) => {
            championsData = data;
            // Still populate hidden select for value tracking
            data.forEach((champ) => {
                const opt = document.createElement("option");
                opt.value = champ.name;
                opt.textContent = champ.name;
                championSelect.appendChild(opt);
            });
        });

    fetch("/api/items")
        .then((res) => res.json())
        .then((data) => {
            itemsData = data;
            data.forEach((item) => {
                itemIconMap[item.name] = item.icon;
            });
        });

    fetch("/api/boots")
        .then((res) => res.json())
        .then((data) => {
            bootsData = data;
            data.forEach((item) => {
                itemIconMap[item.name] = item.icon;
            });
        });

    // === Champion selection ===

    // Registry of champion-specific options.
    // To add options for a champion, add an entry keyed by champion name.
    // Each entry has a `render(container)` function that populates the panel
    // and optionally a `getValues()` function that returns current settings.
    // Example:
    //   championOptionsDefs["Viego"] = {
    //       render(container) {
    //           container.innerHTML = `
    //               <label class="toggle-label compact">
    //                   <input type="checkbox" id="opt-viego-passive">
    //                   <span class="toggle-text">Possessing enemy champion</span>
    //               </label>`;
    //       },
    //       getValues() {
    //           return { possessing: document.getElementById("opt-viego-passive")?.checked };
    //       }
    //   };
    const championOptionsDefs = {};

    championOptionsDefs["Aatrox"] = {
        render(container) {
            container.innerHTML = `
                <label class="toggle-label compact">
                    <input type="checkbox" id="opt-aatrox-sweetspot" checked>
                    <span class="toggle-text">Q Sweetspot hits</span>
                </label>`;
            document.getElementById("opt-aatrox-sweetspot")
                .addEventListener("change", scheduleRecalc);
        },
        getValues() {
            return {
                sweetspot: document.getElementById("opt-aatrox-sweetspot")?.checked ?? true,
            };
        },
        assumptions: [
            "Assumed R is always active",
            "W always hits both initial and pull-back damage",
        ],
    };

    championOptionsDefs["Akshan"] = {
        render(container) {
            container.innerHTML = `
                <label class="toggle-label compact">
                    <span class="toggle-text">Passive procs (3-stack)</span>
                    <input type="number" id="opt-akshan-passive-procs" value="3"
                           min="0" max="20" style="width:48px; margin-left:8px;
                           background:var(--bg-dark); color:var(--text-light);
                           border:1px solid var(--border-subtle); border-radius:4px;
                           padding:2px 6px; font-size:0.85rem;">
                </label>
                <label class="toggle-label compact" style="margin-top:6px;">
                    <span class="toggle-text">E shots fired</span>
                    <input type="number" id="opt-akshan-e-shots" value="5"
                           min="0" max="20" style="width:48px; margin-left:8px;
                           background:var(--bg-dark); color:var(--text-light);
                           border:1px solid var(--border-subtle); border-radius:4px;
                           padding:2px 6px; font-size:0.85rem;">
                </label>`;
            document.getElementById("opt-akshan-passive-procs")
                .addEventListener("input", scheduleRecalc);
            document.getElementById("opt-akshan-e-shots")
                .addEventListener("input", scheduleRecalc);
        },
        getValues() {
            return {
                passive_procs: parseInt(
                    document.getElementById("opt-akshan-passive-procs")?.value ?? "3", 10
                ),
                e_shots: parseInt(
                    document.getElementById("opt-akshan-e-shots")?.value ?? "5", 10
                ),
            };
        },
        assumptions: [
            "Q always hits both passes (outgoing and return)",
            "R assumes full channel (max bullets at max damage)",
            "R crit scaling at 30% effectiveness applied",
            "Double shot applies on-hit effects and can crit",
            "W is utility only (no damage)",
        ],
    };

    championOptionsDefs["Akali"] = {
        render(container) {
            container.innerHTML = `
                <label class="toggle-label compact">
                    <span class="toggle-text">Passive procs</span>
                    <input type="number" id="opt-akali-passive-procs" value="4"
                           min="0" max="20" style="width:48px; margin-left:8px;
                           background:var(--bg-dark); color:var(--text-light);
                           border:1px solid var(--border-subtle); border-radius:4px;
                           padding:2px 6px; font-size:0.85rem;">
                </label>`;
            document.getElementById("opt-akali-passive-procs")
                .addEventListener("input", scheduleRecalc);
        },
        getValues() {
            return {
                passive_procs: parseInt(
                    document.getElementById("opt-akali-passive-procs")?.value ?? "4", 10
                ),
            };
        },
        assumptions: [
            "E always hits both shuriken and recast dash",
            "R always hits both R1 dash and R2 execute",
            "R2 damage scales with target missing HP from prior abilities",
        ],
    };

    championOptionsDefs["Alistar"] = {
        render(container) {
            container.innerHTML = `<p style="color:var(--text-muted); font-size:0.85rem;">
                No configurable options for Alistar.</p>`;
        },
        getValues() {
            return {};
        },
        assumptions: [
            "E Trample deals full duration damage (10 ticks over 5 seconds)",
            "E empowered auto always procs once per cast (5 stacks reached)",
            "Passive (Triumphant Roar) healing is ignored",
            "R (Unbreakable Will) damage reduction is ignored",
        ],
    };

    championOptionsDefs["Ambessa"] = {
        render(container) {
            container.innerHTML = `
                <label class="toggle-label compact">
                    <input type="checkbox" id="opt-ambessa-sweetspot" checked>
                    <span class="toggle-text">Q/Q2 Sweetspot (doubled damage)</span>
                </label>
                <label class="toggle-label compact" style="margin-top:6px;">
                    <span class="toggle-text">Passive procs</span>
                    <input type="number" id="opt-ambessa-passive-procs" value="4"
                           min="0" max="20" style="width:48px; margin-left:8px;
                           background:var(--bg-dark); color:var(--text-light);
                           border:1px solid var(--border-subtle); border-radius:4px;
                           padding:2px 6px; font-size:0.85rem;">
                </label>`;
            document.getElementById("opt-ambessa-sweetspot")
                .addEventListener("change", scheduleRecalc);
            document.getElementById("opt-ambessa-passive-procs")
                .addEventListener("input", scheduleRecalc);
        },
        getValues() {
            return {
                sweetspot: document.getElementById("opt-ambessa-sweetspot")?.checked ?? true,
                passive_procs: parseInt(
                    document.getElementById("opt-ambessa-passive-procs")?.value ?? "4", 10
                ),
            };
        },
        assumptions: [
            "R passive (armor penetration) is always active when R is skilled",
            "W always uses increased (empowered) damage",
            "E always hits twice (both passes)",
            "Q2 (Sundering Slam) shown separately from Q1 (Cunning Sweep)",
        ],
    };

    championOptionsDefs["Anivia"] = {
        render(container) {
            container.innerHTML = `
                <label class="toggle-label compact">
                    <span class="toggle-text">R duration (seconds)</span>
                    <input type="number" id="opt-anivia-r-duration" value="5"
                           min="1.5" max="30" step="0.5" style="width:56px; margin-left:8px;
                           background:var(--bg-dark); color:var(--text-light);
                           border:1px solid var(--border-subtle); border-radius:4px;
                           padding:2px 6px; font-size:0.85rem;">
                </label>`;
            document.getElementById("opt-anivia-r-duration")
                .addEventListener("input", scheduleRecalc);
        },
        getValues() {
            return {
                r_duration: parseFloat(
                    document.getElementById("opt-anivia-r-duration")?.value ?? "5"
                ),
            };
        },
        assumptions: [
            "Q hits both pass-through and detonation (total damage used)",
            "E target is always Chilled (empowered damage used)",
            "R first 1.5s uses initial tick damage, remaining uses fully-formed tick damage",
            "W skipped (utility wall, no damage)",
            "Passive skipped (resurrection only, no damage)",
        ],
    };

    championOptionsDefs["Annie"] = {
        render(container) {
            container.innerHTML = `
                <label class="toggle-label compact">
                    <span class="toggle-text">Tibbers aura duration (seconds)</span>
                    <input type="number" id="opt-annie-tibbers-aura" value="5"
                           min="0" max="45" step="0.5" style="width:56px; margin-left:8px;
                           background:var(--bg-dark); color:var(--text-light);
                           border:1px solid var(--border-subtle); border-radius:4px;
                           padding:2px 6px; font-size:0.85rem;">
                </label>`;
            document.getElementById("opt-annie-tibbers-aura")
                .addEventListener("input", scheduleRecalc);
        },
        getValues() {
            return {
                tibbers_aura_seconds: parseFloat(
                    document.getElementById("opt-annie-tibbers-aura")?.value ?? "5"
                ),
            };
        },
        assumptions: [
            "R magic penetration passive is always active",
            "Tibbers auto-attack damage is not modeled (positioning-dependent)",
            "E retaliation damage is not modeled (requires enemies to hit Annie)",
            "Tibbers aura defaults to 5 seconds of damage",
        ],
    };

    championOptionsDefs["Amumu"] = {
        render(container) {
            container.innerHTML = `
                <label class="toggle-label compact">
                    <input type="checkbox" id="opt-amumu-cursed" checked>
                    <span class="toggle-text">Target already Cursed (10% bonus true damage)</span>
                </label>
                <label class="toggle-label compact" style="margin-top:6px;">
                    <span class="toggle-text">W seconds active</span>
                    <input type="number" id="opt-amumu-w-seconds" value="3"
                           min="0.5" max="30" step="0.5" style="width:48px; margin-left:8px;
                           background:var(--bg-dark); color:var(--text-light);
                           border:1px solid var(--border-subtle); border-radius:4px;
                           padding:2px 6px; font-size:0.85rem;">
                </label>`;
            document.getElementById("opt-amumu-cursed")
                .addEventListener("change", scheduleRecalc);
            document.getElementById("opt-amumu-w-seconds")
                .addEventListener("input", scheduleRecalc);
        },
        getValues() {
            return {
                target_cursed: document.getElementById("opt-amumu-cursed")?.checked ?? true,
                w_seconds: parseFloat(
                    document.getElementById("opt-amumu-w-seconds")?.value ?? "3"
                ),
            };
        },
        assumptions: [
            "Target is assumed already Cursed (Passive) — all magic damage gets 10% bonus true damage",
            "Q uses recharge timer as cooldown (fight engine determines cast count)",
            "W defaults to 3 seconds active (6 ticks at 0.5s intervals)",
            "E passive (damage reduction) is not modeled — defensive only",
        ],
    };

    championOptionsDefs["Ashe"] = {
        render(container) {
            container.innerHTML = `
                <label class="toggle-label compact">
                    <input type="checkbox" id="opt-ashe-q-active" checked>
                    <span class="toggle-text">Ranger's Focus active</span>
                </label>`;
            document.getElementById("opt-ashe-q-active")
                .addEventListener("change", scheduleRecalc);
        },
        getValues() {
            return {
                q_active: document.getElementById("opt-ashe-q-active")?.checked ?? true,
            };
        },
        assumptions: [
            "Q (Ranger's Focus) assumed active by default",
            "Passive bonus damage from crit chance applied to all auto attacks",
            "W hits a single target (one arrow per enemy)",
            "E (Hawkshot) is utility only and deals no damage",
        ],
    };

    function selectChampion(name, icon) {
        championSelect.value = name;
        championNameText.textContent = name || "Select Champion";

        if (icon) {
            championIcon.src = icon;
            championIcon.classList.remove("hidden");
        } else {
            championIcon.classList.add("hidden");
        }

        // Update champion options panel content
        updateChampionOptionsContent(name);

        // Show/hide the + button based on whether a champion is selected.
        // Auto-open the panel when the champion has custom options defined.
        if (name) {
            championOptionsBtn.classList.remove("hidden");
            if (championOptionsDefs[name]) {
                championOptionsPanel.classList.remove("hidden");
            } else {
                championOptionsPanel.classList.add("hidden");
            }
        } else {
            championOptionsBtn.classList.add("hidden");
            championOptionsPanel.classList.add("hidden");
        }

        // Fetch and display ability icons + names
        if (name) {
            fetch("/api/abilities/" + encodeURIComponent(name))
                .then((res) => res.json())
                .then((data) => {
                    ["P", "Q", "W", "E", "R"].forEach((key) => {
                        const iconEl = document.getElementById("ability-icon-" + key);
                        const info = data[key];
                        if (iconEl && info) {
                            iconEl.src = info.icon || "";
                            iconEl.title = info.name || key;
                        }
                    });
                });
        } else {
            ["P", "Q", "W", "E", "R"].forEach((key) => {
                const iconEl = document.getElementById("ability-icon-" + key);
                if (iconEl) { iconEl.src = ""; iconEl.title = ""; }
            });
        }

        scheduleRecalc();
    }

    function updateChampionOptionsContent(championName) {
        const def = championOptionsDefs[championName];
        if (def && def.render) {
            championOptionsContent.innerHTML = "";
            def.render(championOptionsContent);
        } else {
            championOptionsContent.innerHTML =
                '<p class="champion-options-empty">No special options for this champion.</p>';
        }
    }

    // + button toggles the options panel
    championOptionsBtn.addEventListener("click", (e) => {
        e.stopPropagation(); // Don't trigger champion picker
        championOptionsPanel.classList.toggle("hidden");
    });

    // Close button on the panel
    championOptionsClose.addEventListener("click", () => {
        championOptionsPanel.classList.add("hidden");
    });

    // === Champion Picker ===

    function openChampionPicker() {
        champPickerSearch.value = "";
        renderChampionGrid(championsData);
        champPickerOverlay.classList.remove("hidden");
        champPickerSearch.focus();
    }

    function closeChampionPicker() {
        champPickerOverlay.classList.add("hidden");
    }

    function renderChampionGrid(champs) {
        champPickerGrid.innerHTML = "";
        if (champs.length === 0) {
            champPickerGrid.innerHTML = '<div class="picker-empty">No champions found</div>';
            return;
        }
        champs.forEach((champ) => {
            const el = document.createElement("div");
            el.className = "picker-item";
            el.innerHTML = `<img src="${champ.icon}" alt="${champ.name}" loading="lazy"><div class="picker-tooltip">${champ.name}</div>`;
            el.addEventListener("click", () => {
                selectChampion(champ.name, champ.icon);
                closeChampionPicker();
            });
            champPickerGrid.appendChild(el);
        });
    }

    // Click portrait or name to open champion picker
    championPortraitBtn.addEventListener("click", openChampionPicker);
    championNameDisplay.addEventListener("click", openChampionPicker);

    // Close champion picker
    champPickerClose.addEventListener("click", closeChampionPicker);
    champPickerOverlay.addEventListener("click", (e) => {
        if (e.target === champPickerOverlay) closeChampionPicker();
    });

    // Champion picker search
    champPickerSearch.addEventListener("input", () => {
        const query = champPickerSearch.value.toLowerCase().trim();
        if (!query) {
            renderChampionGrid(championsData);
            return;
        }
        const filtered = championsData.filter((c) =>
            c.name.toLowerCase().includes(query)
        );
        renderChampionGrid(filtered);
    });

    // === Ability rank auto/manual toggle ===

    autoRankCheckbox.addEventListener("change", () => {
        if (autoRankCheckbox.checked) {
            abilitiesBar.classList.add("rank-disabled");
        } else {
            abilitiesBar.classList.remove("rank-disabled");
        }
        scheduleRecalc();
    });
    abilitiesBar.classList.add("rank-disabled");

    // Rank selects trigger recalc
    document.querySelectorAll(".rank-select").forEach((sel) => {
        sel.addEventListener("change", scheduleRecalc);
    });

    // === Cast order ===

    autoCastOrderCheckbox.addEventListener("change", () => {
        if (autoCastOrderCheckbox.checked) {
            castOrderContainer.classList.add("cast-order-disabled");
            const defaults = ["Q", "W", "E", "R"];
            castOrderSelects.forEach((sel, i) => { sel.value = defaults[i]; });
        } else {
            castOrderContainer.classList.remove("cast-order-disabled");
        }
        scheduleRecalc();
    });
    castOrderContainer.classList.add("cast-order-disabled");

    // Auto-swap logic
    castOrderSelects.forEach((sel, idx) => {
        sel.addEventListener("change", () => {
            const chosen = sel.value;
            castOrderSelects.forEach((other, otherIdx) => {
                if (otherIdx !== idx && other.value === chosen) {
                    const allUsed = castOrderSelects.map((s) => s.value);
                    const missing = ["Q", "W", "E", "R"].find(
                        (k) => allUsed.filter((v) => v === k).length === 0
                    );
                    if (missing) other.value = missing;
                }
            });
            scheduleRecalc();
        });
    });

    // === Item Build Slots ===

    const itemSlots = document.querySelectorAll(".item-slot");

    itemSlots.forEach((slot) => {
        // Left click on slot background/empty area opens picker
        slot.addEventListener("click", (e) => {
            const slotKey = slot.dataset.slot;
            if (!slotKey) return;
            // Don't open picker if they clicked the remove button
            if (e.target.closest(".item-remove-btn")) return;
            openItemPicker(slotKey);
        });

        // Right click to remove item
        slot.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            const slotKey = slot.dataset.slot;
            if (!slotKey || !selectedItems[slotKey]) return;
            clearItemSlot(slotKey);
            scheduleRecalc();
        });

        // Remove button click
        const removeBtn = slot.querySelector(".item-remove-btn");
        if (removeBtn) {
            removeBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                const slotKey = slot.dataset.slot;
                if (!slotKey) return;
                clearItemSlot(slotKey);
                scheduleRecalc();
            });
        }
    });

    // Get names of all currently selected items (for duplicate prevention)
    function getSelectedItemNames() {
        const names = new Set();
        for (const [key, name] of Object.entries(selectedItems)) {
            if (name) names.add(name);
        }
        return names;
    }

    function openItemPicker(slotKey) {
        activePickerSlot = slotKey;
        const isBoot = slotKey === "boots";
        const sourceItems = isBoot ? bootsData : itemsData;

        pickerTitle.textContent = isBoot ? "Select Boots" : "Select Item";
        pickerSearch.value = "";

        renderPickerItems(sourceItems);
        pickerOverlay.classList.remove("hidden");
        pickerSearch.focus();
    }

    function renderPickerItems(items) {
        pickerGrid.innerHTML = "";

        if (items.length === 0) {
            pickerGrid.innerHTML = '<div class="picker-empty">No items found</div>';
            return;
        }

        // Get already-selected items to mark as unavailable
        const selected = getSelectedItemNames();
        // The item currently in this slot is allowed (replacing itself)
        const currentInSlot = selectedItems[activePickerSlot] || "";

        items.forEach((item) => {
            const el = document.createElement("div");
            const isUsed = selected.has(item.name) && item.name !== currentInSlot;
            el.className = "picker-item" + (isUsed ? " picker-item-used" : "");
            el.innerHTML = `<img src="${item.icon}" alt="${item.name}" loading="lazy"><div class="picker-tooltip">${item.name}${isUsed ? " (already selected)" : ""}</div>`;
            if (!isUsed) {
                el.addEventListener("click", () => {
                    selectItem(activePickerSlot, item.name, item.icon);
                    closePicker();
                });
            }
            pickerGrid.appendChild(el);
        });
    }

    function selectItem(slotKey, name, icon) {
        selectedItems[slotKey] = name;

        const slot = document.querySelector(`.item-slot[data-slot="${slotKey}"]`);
        if (!slot) return;

        slot.title = name;

        const iconEl = slot.querySelector(".item-slot-icon");
        if (iconEl) {
            iconEl.src = icon;
            iconEl.alt = name;
            iconEl.classList.remove("hidden");
        }

        // Show remove button
        const removeBtn = slot.querySelector(".item-remove-btn");
        if (removeBtn) removeBtn.classList.remove("hidden");

        scheduleRecalc();
    }

    function clearItemSlot(slotKey) {
        selectedItems[slotKey] = "";

        const slot = document.querySelector(`.item-slot[data-slot="${slotKey}"]`);
        if (!slot) return;

        slot.title = slotKey === "boots" ? "Boots" : `Item ${slotKey}`;

        const iconEl = slot.querySelector(".item-slot-icon");
        if (iconEl) {
            iconEl.classList.add("hidden");
            iconEl.src = "";
            iconEl.alt = "";
        }

        // Hide remove button
        const removeBtn = slot.querySelector(".item-remove-btn");
        if (removeBtn) removeBtn.classList.add("hidden");
    }

    function closePicker() {
        pickerOverlay.classList.add("hidden");
        activePickerSlot = null;
    }

    pickerClose.addEventListener("click", closePicker);
    pickerOverlay.addEventListener("click", (e) => {
        if (e.target === pickerOverlay) closePicker();
    });

    // Picker search
    pickerSearch.addEventListener("input", () => {
        const query = pickerSearch.value.toLowerCase().trim();
        const isBoot = activePickerSlot === "boots";
        const sourceItems = isBoot ? bootsData : itemsData;

        if (!query) {
            renderPickerItems(sourceItems);
            return;
        }

        const filtered = sourceItems.filter((item) =>
            item.name.toLowerCase().includes(query)
        );
        renderPickerItems(filtered);
    });

    // Escape key closes pickers
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            if (!pickerOverlay.classList.contains("hidden")) closePicker();
            if (!champPickerOverlay.classList.contains("hidden")) closeChampionPicker();
        }
    });

    // === Level slider ===

    levelSlider.addEventListener("input", () => {
        levelDisplay.textContent = levelSlider.value;
        scheduleRecalc();
    });

    // === Fight settings ===

    fightDuration.addEventListener("input", () => {
        durationDisplay.textContent = fightDuration.value;
        scheduleRecalc();
    });

    autoUptime.addEventListener("input", () => {
        uptimeDisplay.textContent = autoUptime.value;
        scheduleRecalc();
    });

    // Fight mode tabs
    fightTabs.forEach((tab) => {
        tab.addEventListener("click", () => {
            fightTabs.forEach((t) => t.classList.remove("active"));
            tab.classList.add("active");
            const radio = tab.querySelector('input[type="radio"]');
            radio.checked = true;

            if (radio.value === "time_based") {
                timeBasedOptions.classList.remove("hidden");
            } else {
                timeBasedOptions.classList.add("hidden");
            }
            scheduleRecalc();
        });
    });

    includeAutos.addEventListener("change", () => {
        if (includeAutos.checked) {
            uptimeOptions.classList.remove("hidden");
        } else {
            uptimeOptions.classList.add("hidden");
            // Uncheck "Auto Attacks Only" if autos are disabled
            autoAttacksOnly.checked = false;
        }
        scheduleRecalc();
    });

    autoAttacksOnly.addEventListener("change", () => {
        if (autoAttacksOnly.checked) {
            // Auto-enable "Include Auto Attacks" and show uptime options
            includeAutos.checked = true;
            uptimeOptions.classList.remove("hidden");
        }
        scheduleRecalc();
    });

    // Update total HP display when base or bonus changes
    function updateTotalHealth() {
        const base = parseFloat(targetBaseHealth.value) || 0;
        const bonus = parseFloat(targetBonusHealth.value) || 0;
        targetTotalHealth.textContent = Math.round(base + bonus);
    }

    // Target stats trigger recalc
    [targetBaseHealth, targetBonusHealth, targetArmor, targetMr].forEach((input) => {
        input.addEventListener("change", () => { updateTotalHealth(); scheduleRecalc(); });
        input.addEventListener("input", () => { updateTotalHealth(); scheduleRecalc(); });
    });

    includeActives.addEventListener("change", scheduleRecalc);

    // === Auto-recalculate ===

    function scheduleRecalc() {
        if (!hasCalculated) return;
        if (recalcTimer) clearTimeout(recalcTimer);
        recalcTimer = setTimeout(doCalculate, 300);
    }

    // === Calculate ===

    calculateBtn.addEventListener("click", () => {
        doCalculate();
    });

    function doCalculate() {
        const champion = championSelect.value;
        if (!champion) {
            showError("Please select a champion.");
            return;
        }

        if (isCalculating) return;
        isCalculating = true;

        const fightMode = document.querySelector('input[name="fight-mode"]:checked').value;

        // Collect items from slots
        const items = [];
        for (let i = 1; i <= 6; i++) {
            if (selectedItems[i]) items.push(selectedItems[i]);
        }

        const payload = {
            champion: champion,
            level: parseInt(levelSlider.value, 10),
            boots: selectedItems.boots,
            items: items,
            target_health: (parseFloat(targetBaseHealth.value) || 1000) + (parseFloat(targetBonusHealth.value) || 0),
            target_bonus_health: parseFloat(targetBonusHealth.value) || 0,
            target_armor: targetArmor.value !== "" ? parseFloat(targetArmor.value) : 100,
            target_mr: targetMr.value !== "" ? parseFloat(targetMr.value) : 100,
            fight_mode: fightMode,
            fight_duration: parseInt(fightDuration.value, 10),
            include_auto_attacks: fightMode === "time_based" && includeAutos.checked,
            auto_attack_uptime: parseFloat(autoUptime.value) / 100,
            auto_attacks_only: fightMode === "time_based" && autoAttacksOnly.checked,
            include_actives: includeActives.checked,
        };

        // Ability ranks
        if (!autoRankCheckbox.checked) {
            payload.ability_ranks = {
                Q: parseInt(document.getElementById("rank-Q").value, 10),
                W: parseInt(document.getElementById("rank-W").value, 10),
                E: parseInt(document.getElementById("rank-E").value, 10),
                R: parseInt(document.getElementById("rank-R").value, 10),
            };
        }

        // Cast order
        if (!autoCastOrderCheckbox.checked) {
            payload.cast_order = castOrderSelects.map((sel) => sel.value);
        }

        // Champion-specific options
        const optDef = championOptionsDefs[champion];
        if (optDef && optDef.getValues) {
            payload.champion_options = optDef.getValues();
        }

        // Show loading state
        if (!hasCalculated) {
            btnText.textContent = "Calculating...";
            btnLoading.classList.remove("hidden");
            calculateBtn.disabled = true;
        } else {
            resultsContent.classList.add("recalculating");
        }

        fetch("/api/calculate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        })
            .then((res) => res.json())
            .then((data) => {
                if (data.error) {
                    showError(data.error);
                    return;
                }
                hideError();
                displayResults(data);

                if (!hasCalculated) {
                    hasCalculated = true;
                    // Switch to live mode
                    btnText.textContent = "Live";
                    calculateBtn.classList.add("live-mode");
                }
            })
            .catch((err) => {
                showError("Request failed: " + err.message);
            })
            .finally(() => {
                isCalculating = false;
                calculateBtn.disabled = false;
                btnLoading.classList.add("hidden");
                resultsContent.classList.remove("recalculating");
            });
    }

    // === Update data ===

    const updateBtn = document.getElementById("update-btn");
    const updateModal = document.getElementById("update-modal");
    const updateStatus = document.getElementById("update-status");
    const updateDetail = document.getElementById("update-detail");
    const updateModalTitle = document.getElementById("update-modal-title");
    const progressBar = document.getElementById("progress-bar");
    const updateCloseBtn = document.getElementById("update-close-btn");

    updateBtn.addEventListener("click", () => {
        updateBtn.disabled = true;
        updateModal.classList.remove("hidden");
        updateModalTitle.textContent = "Updating Data";
        updateStatus.textContent = "Initializing...";
        updateDetail.textContent = "";
        progressBar.style.width = "0%";
        updateCloseBtn.classList.add("hidden");

        const source = new EventSource("/api/update-data");

        source.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if (data.phase === "init") {
                updateStatus.textContent = data.status;
                progressBar.style.width = "5%";
            } else if (data.phase === "champions") {
                updateStatus.textContent = data.status;
                if (data.total && data.total > 0) {
                    const pct = Math.round((data.current / data.total) * 80) + 10;
                    progressBar.style.width = pct + "%";
                }
                if (data.champion) {
                    updateDetail.textContent = data.current + " / " + data.total + " champions";
                }
            } else if (data.phase === "items") {
                updateStatus.textContent = data.status;
                progressBar.style.width = "92%";
                updateDetail.textContent = "";
            } else if (data.phase === "done") {
                updateStatus.textContent = data.status;
                progressBar.style.width = "100%";
                progressBar.classList.add("progress-done");
                updateDetail.textContent = data.champions_count + " champions updated";
                updateCloseBtn.classList.remove("hidden");
                source.close();
            } else if (data.phase === "error") {
                updateStatus.textContent = data.status;
                progressBar.classList.add("progress-error");
                updateCloseBtn.classList.remove("hidden");
                source.close();
            }
        };

        source.onerror = () => {
            updateStatus.textContent = "Connection lost. Update may have failed.";
            progressBar.classList.add("progress-error");
            updateCloseBtn.classList.remove("hidden");
            source.close();
        };
    });

    updateCloseBtn.addEventListener("click", () => {
        updateModal.classList.add("hidden");
        updateBtn.disabled = false;
        progressBar.classList.remove("progress-done", "progress-error");
        location.reload();
    });

    // === Display functions ===

    function showError(msg) {
        errorMessage.textContent = msg;
        errorDisplay.classList.remove("hidden");
    }

    function hideError() {
        errorDisplay.classList.add("hidden");
    }

    function displayResults(data) {
        // Show results, hide placeholder
        resultsPlaceholder.classList.add("hidden");
        resultsContent.classList.remove("hidden");

        const stats = data.champion_stats;

        // Champion stats
        document.getElementById("stat-hp").textContent = Math.round(stats.health);
        document.getElementById("stat-ad").textContent = Math.round(stats.attack_damage);
        document.getElementById("stat-ap").textContent = Math.round(stats.ability_power);
        document.getElementById("stat-as").textContent = stats.attack_speed.toFixed(3);
        document.getElementById("stat-armor").textContent = Math.round(stats.armor);
        document.getElementById("stat-mr").textContent = Math.round(stats.magic_resistance);
        document.getElementById("stat-crit").textContent =
            Math.round(stats.critical_strike_chance) + "%";
        document.getElementById("stat-mana").textContent = Math.round(stats.max_mana);
        document.getElementById("stat-ah").textContent = Math.round(stats.ability_haste);
        document.getElementById("stat-lethality").textContent = Math.round(stats.lethality);
        document.getElementById("stat-mpen").textContent = Math.round(stats.magic_penetration_flat);
        document.getElementById("stat-armor-pen").textContent =
            Math.round(stats.armor_penetration_percent) + "%";
        document.getElementById("stat-mpen-pct").textContent =
            Math.round(stats.magic_penetration_percent) + "%";

        // Damage summary
        animateValue("total-damage-value", Math.round(data.total_damage));
        document.getElementById("ability-damage-value").textContent =
            Math.round(data.ability_damage);
        document.getElementById("auto-damage-value").textContent =
            Math.round(data.auto_attack_damage);

        // Effective resistances
        document.getElementById("eff-armor").textContent = data.effective_armor;
        document.getElementById("eff-mr").textContent = data.effective_mr;

        // Breakdown table
        const tbody = document.getElementById("breakdown-body");
        tbody.innerHTML = "";

        const breakdown = data.breakdown;
        for (const [key, entry] of Object.entries(breakdown)) {
            const tr = document.createElement("tr");

            const tdName = document.createElement("td");
            tdName.textContent = entry.name;

            const tdDetail = document.createElement("td");
            if (entry.execution_threshold_hp != null) {
                // Collector: show execution threshold instead of damage
                tdDetail.textContent = "Execute below " + Math.round(entry.execution_threshold_hp) + " HP";
            } else if (entry.sundered_sky_note != null) {
                tdDetail.textContent = entry.sundered_sky_note;
            } else if (entry.note != null && entry.total_damage === 0) {
                tdDetail.textContent = entry.note;
            } else if (entry.casts != null) {
                tdDetail.textContent = entry.casts + (entry.casts === 1 ? " cast" : " casts");
            } else if (entry.count != null) {
                let detail = "";
                if (entry.num_crits != null && entry.num_crits > 0 && entry.num_non_crits > 0) {
                    let parts = [];
                    parts.push(entry.num_crits + " crit" + (entry.num_crits !== 1 ? "s" : "")
                        + " @ " + Math.round(entry.crit_damage_per_hit) + " each");
                    parts.push(entry.num_non_crits + " non-crit" + (entry.num_non_crits !== 1 ? "s" : "")
                        + " @ " + Math.round(entry.non_crit_damage_per_hit) + " each");
                    detail = parts.join(", ");
                } else if (entry.num_crits != null && entry.num_crits > 0) {
                    detail = entry.count + " crit" + (entry.count !== 1 ? "s" : "")
                        + " @ " + Math.round(entry.crit_damage_per_hit) + " each";
                } else {
                    detail = entry.count + " hits";
                    if (entry.damage_per_hit != null) {
                        detail += " @ " + Math.round(entry.damage_per_hit) + " each";
                    }
                }
                tdDetail.textContent = detail;
            } else {
                tdDetail.textContent = "";
            }

            const tdDmg = document.createElement("td");
            tdDmg.className = "col-right";
            if (entry.execution_threshold_hp != null) {
                tdDmg.textContent = Math.round(entry.execution_threshold_hp) + " HP";
            } else {
                tdDmg.textContent = Math.round(entry.total_damage);
            }

            tr.appendChild(tdName);
            tr.appendChild(tdDetail);
            tr.appendChild(tdDmg);
            tbody.appendChild(tr);
        }

        // Champion assumptions
        const assumptionsPanel = document.getElementById("champion-assumptions");
        const assumptionsList = document.getElementById("champion-assumptions-list");
        const champion = championSelect.value;
        const optDef = championOptionsDefs[champion];
        if (optDef && optDef.assumptions && optDef.assumptions.length > 0) {
            assumptionsList.innerHTML = "";
            optDef.assumptions.forEach((text) => {
                const li = document.createElement("li");
                li.textContent = text;
                assumptionsList.appendChild(li);
            });
            assumptionsPanel.classList.remove("hidden");
        } else {
            assumptionsPanel.classList.add("hidden");
        }
    }

    // Simple animated counter for total damage
    function animateValue(elementId, targetValue) {
        const el = document.getElementById(elementId);
        const currentValue = parseInt(el.textContent) || 0;
        const diff = targetValue - currentValue;

        // Skip animation for small changes or first render
        if (Math.abs(diff) < 5 || currentValue === 0) {
            el.textContent = targetValue;
            return;
        }

        const duration = 300;
        const startTime = performance.now();

        function update(now) {
            const elapsed = now - startTime;
            const progress = Math.min(elapsed / duration, 1);
            // Ease out
            const eased = 1 - Math.pow(1 - progress, 3);
            el.textContent = Math.round(currentValue + diff * eased);
            if (progress < 1) {
                requestAnimationFrame(update);
            }
        }

        requestAnimationFrame(update);
    }
});
