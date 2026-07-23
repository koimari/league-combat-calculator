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
    // Server-provided config (see /api/config) — single source of truth
    // shared with the Python backend, populated by the fetch below.
    let itemToGroups = {};   // item name -> list of exclusivity group names
    let defaultTarget = {};  // default target stats for empty inputs
    // Champion option/assumption metadata, declared as OPTIONS/ASSUMPTIONS
    // beside each champion module's SLOTS (src/calculator/champions/).
    // Shape: { "<champion>": { options: [{key, type, default, label,
    // min?, max?, step?}], assumptions: ["..."] } } — champions absent
    // from the map have no special options (the generic path).
    let championOptionsMeta = {};
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

    // Config shared with the backend: item exclusivity groups (from
    // optimizer.py), fight/target defaults (from pipeline.py), and champion
    // option/assumption metadata (from the champion modules).
    fetch("/api/config")
        .then((res) => res.json())
        .then((data) => {
            defaultTarget = data.default_target;
            championOptionsMeta = data.champion_options || {};
            // Update Data is a local dev workflow (LOL_CALC_DEV=1); the
            // deployed site 404s the endpoint, so hide its button.
            if (!data.dev_mode) {
                document.getElementById("update-btn").classList.add("hidden");
            }
            // Reverse lookup: item name -> list of group names it belongs to
            for (const [group, members] of Object.entries(data.exclusivity_groups)) {
                for (const name of members) {
                    if (!itemToGroups[name]) itemToGroups[name] = [];
                    itemToGroups[name].push(group);
                }
            }
        });

    // === Champion selection ===

    // Champion options UI, rendered generically from championOptionsMeta.
    // Adding an option to a champion is a Python-side change: declare it
    // in the module's OPTIONS list — no frontend edit needed.

    const OPTION_NUMBER_STYLE =
        "width:56px; margin-left:8px; background:var(--bg-dark); " +
        "color:var(--text-light); border:1px solid var(--border-subtle); " +
        "border-radius:4px; padding:2px 6px; font-size:0.85rem;";

    function championOptionInputId(key) {
        return "champ-opt-" + key;
    }

    // Build the option controls: bool -> checkbox (recalc on change),
    // int/float -> number input with min/max/step (recalc on input).
    function renderChampionOptions(container, options) {
        container.innerHTML = "";
        options.forEach((opt, index) => {
            const label = document.createElement("label");
            label.className = "toggle-label compact";
            if (index > 0) label.style.marginTop = "6px";

            const text = document.createElement("span");
            text.className = "toggle-text";
            text.textContent = opt.label;

            const input = document.createElement("input");
            input.id = championOptionInputId(opt.key);
            if (opt.type === "bool") {
                input.type = "checkbox";
                input.checked = !!opt.default;
                input.addEventListener("change", scheduleRecalc);
                label.appendChild(input);
                label.appendChild(text);
            } else {
                input.type = "number";
                input.value = opt.default;
                if (opt.min !== undefined) input.min = opt.min;
                if (opt.max !== undefined) input.max = opt.max;
                if (opt.step !== undefined) input.step = opt.step;
                input.style.cssText = OPTION_NUMBER_STYLE;
                input.addEventListener("input", scheduleRecalc);
                label.appendChild(text);
                label.appendChild(input);
            }
            container.appendChild(label);
        });
    }

    // Read the current option values for the champion_options payload.
    // Returns null for champions without metadata; a cleared/invalid
    // number input falls back to the option's default.
    function collectChampionOptions(champion) {
        const meta = championOptionsMeta[champion];
        if (!meta) return null;
        const values = {};
        meta.options.forEach((opt) => {
            const el = document.getElementById(championOptionInputId(opt.key));
            if (opt.type === "bool") {
                values[opt.key] = el ? el.checked : !!opt.default;
            } else {
                const parsed =
                    opt.type === "int"
                        ? parseInt(el?.value, 10)
                        : parseFloat(el?.value);
                values[opt.key] = Number.isNaN(parsed) ? opt.default : parsed;
            }
        });
        return values;
    }

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
            if (championOptionsMeta[name]) {
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
        const meta = championOptionsMeta[championName];
        if (meta && meta.options.length > 0) {
            renderChampionOptions(championOptionsContent, meta.options);
        } else if (meta) {
            // Registered champion with assumptions but no knobs (Alistar).
            championOptionsContent.innerHTML = "";
            const p = document.createElement("p");
            p.style.cssText = "color:var(--text-muted); font-size:0.85rem;";
            p.textContent = "No configurable options for " + championName + ".";
            championOptionsContent.appendChild(p);
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
            // Unverified = no champion module yet (server-decided; see
            // /api/champions): greyed out, tooltip explains, no click.
            el.className = champ.verified ? "picker-item" : "picker-item unverified";
            const tooltip = champ.verified ? champ.name : `${champ.name} — not yet verified`;
            el.innerHTML = `<img src="${champ.icon}" alt="${champ.name}" loading="lazy"><div class="picker-tooltip">${tooltip}</div>`;
            if (champ.verified) {
                el.addEventListener("click", () => {
                    selectChampion(champ.name, champ.icon);
                    closeChampionPicker();
                });
            }
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

    // Item exclusivity groups — only one item per group allowed in a build.
    // The groups themselves come from the backend (/api/config -> itemToGroups),
    // so the manual builder and the optimizer enforce the same table.

    // Returns the exclusivity reason if an item is blocked, or null if allowed.
    // currentSlot is the slot being picked for (its current item is allowed).
    function getExclusivityBlock(itemName, currentSlot) {
        const groups = itemToGroups[itemName];
        if (!groups) return null;

        for (const [slotKey, slotItem] of Object.entries(selectedItems)) {
            if (!slotItem || slotKey === currentSlot) continue;
            if (slotItem === itemName) continue; // duplicate check handled elsewhere
            const slotGroups = itemToGroups[slotItem];
            if (!slotGroups) continue;
            for (const g of groups) {
                if (slotGroups.includes(g)) {
                    return `${g} group (have ${slotItem})`;
                }
            }
        }
        return null;
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
            const exclusivityBlock = !isUsed ? getExclusivityBlock(item.name, activePickerSlot) : null;
            const isBlocked = isUsed || exclusivityBlock;
            el.className = "picker-item" + (isBlocked ? " picker-item-used" : "");
            let tooltip = item.name;
            if (isUsed) tooltip += " (already selected)";
            else if (exclusivityBlock) tooltip += ` (${exclusivityBlock})`;
            el.innerHTML = `<img src="${item.icon}" alt="${item.name}" loading="lazy"><div class="picker-tooltip">${tooltip}</div>`;
            if (!isBlocked) {
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

    // === Level slider + fight settings ===

    // Derive every JS-driven display (value badges, tab highlight, panel
    // visibility, total-HP readout) from the inputs' current values.
    // Handlers mutate input state and then call this; it also runs once on
    // load because browsers (notably Firefox) restore form values across
    // reload WITHOUT firing events — without the load-time sync the UI
    // shows defaults while Calculate reads the restored inputs.
    function syncControlsFromInputs() {
        levelDisplay.textContent = levelSlider.value;
        durationDisplay.textContent = fightDuration.value;
        uptimeDisplay.textContent = autoUptime.value;
        let timeBased = false;
        fightTabs.forEach((tab) => {
            const radio = tab.querySelector('input[type="radio"]');
            tab.classList.toggle("active", radio.checked);
            if (radio.checked && radio.value === "time_based") timeBased = true;
        });
        timeBasedOptions.classList.toggle("hidden", !timeBased);
        uptimeOptions.classList.toggle("hidden", !includeAutos.checked);
        updateTotalHealth();
    }

    levelSlider.addEventListener("input", () => {
        syncControlsFromInputs();
        scheduleRecalc();
    });

    fightDuration.addEventListener("input", () => {
        syncControlsFromInputs();
        scheduleRecalc();
    });

    autoUptime.addEventListener("input", () => {
        syncControlsFromInputs();
        scheduleRecalc();
    });

    // Fight mode tabs
    fightTabs.forEach((tab) => {
        tab.addEventListener("click", () => {
            tab.querySelector('input[type="radio"]').checked = true;
            syncControlsFromInputs();
            scheduleRecalc();
        });
    });

    includeAutos.addEventListener("change", () => {
        // Uncheck "Auto Attacks Only" if autos are disabled
        if (!includeAutos.checked) autoAttacksOnly.checked = false;
        syncControlsFromInputs();
        scheduleRecalc();
    });

    autoAttacksOnly.addEventListener("change", () => {
        // "Auto Attacks Only" implies "Include Auto Attacks"
        if (autoAttacksOnly.checked) includeAutos.checked = true;
        syncControlsFromInputs();
        scheduleRecalc();
    });

    // Absorb browser-restored form state (see syncControlsFromInputs).
    syncControlsFromInputs();

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

    // Target stat payload fields. Empty inputs fall back to the
    // server-provided defaults (defaultTarget, fetched from /api/config).
    function buildTargetPayload() {
        const bonusHealth = parseFloat(targetBonusHealth.value) || defaultTarget.bonus_health;
        return {
            target_health: (parseFloat(targetBaseHealth.value) || defaultTarget.health) + bonusHealth,
            target_bonus_health: bonusHealth,
            target_armor: targetArmor.value !== "" ? parseFloat(targetArmor.value) : defaultTarget.armor,
            target_mr: targetMr.value !== "" ? parseFloat(targetMr.value) : defaultTarget.mr,
        };
    }

    // Payload fields shared by /api/calculate and /api/optimize: champion,
    // level, target stats, fight parameters, and the optional ability-rank /
    // cast-order / champion-option blocks.
    function buildFightPayload(champion) {
        const fightMode = document.querySelector('input[name="fight-mode"]:checked').value;

        const payload = {
            champion: champion,
            level: parseInt(levelSlider.value, 10),
            ...buildTargetPayload(),
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
        const championOptions = collectChampionOptions(champion);
        if (championOptions) {
            payload.champion_options = championOptions;
        }

        return payload;
    }

    function doCalculate() {
        const champion = championSelect.value;
        if (!champion) {
            showError("Please select a champion.");
            return;
        }

        if (isCalculating) return;
        isCalculating = true;

        // Collect items from slots
        const items = [];
        for (let i = 1; i <= 6; i++) {
            if (selectedItems[i]) items.push(selectedItems[i]);
        }

        const payload = buildFightPayload(champion);
        payload.boots = selectedItems.boots;
        payload.items = items;

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
            if (entry.detail != null) {
                // Engine-minted display text (execute threshold, Sundered
                // Sky diff, amp summaries) — always wins over derived text.
                tdDetail.textContent = entry.detail;
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
                    const unit = entry.unit || "hits";
                    detail = entry.count + " " + unit;
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
            if (entry.damage_display != null) {
                tdDmg.textContent = entry.damage_display;
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
        const meta = championOptionsMeta[champion];
        if (meta && meta.assumptions && meta.assumptions.length > 0) {
            assumptionsList.innerHTML = "";
            meta.assumptions.forEach((text) => {
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

    // =============== BUILD OPTIMIZER ===============
    const optimizeBtn = document.getElementById("optimize-btn");
    const optimizeBtnText = optimizeBtn.querySelector(".btn-text");
    const optimizeBtnLoading = optimizeBtn.querySelector(".btn-loading");
    const optimizeStatus = document.getElementById("optimize-status");
    const optimizeObjective = document.getElementById("optimize-objective");
    const optimizeSlots = document.getElementById("optimize-slots");

    let isOptimizing = false;

    optimizeBtn.addEventListener("click", () => {
        const champion = championSelect.value;
        if (!champion) {
            showError("Please select a champion first.");
            return;
        }
        if (isOptimizing) return;
        isOptimizing = true;

        const maxSlots = parseInt(optimizeSlots.value, 10);

        // Collect locked items (non-empty slots)
        const lockedItems = [];
        for (let i = 1; i <= 6; i++) {
            if (selectedItems[i]) lockedItems.push(selectedItems[i]);
        }
        const lockedBoots = selectedItems.boots || "";

        const payload = buildFightPayload(champion);
        payload.objective = optimizeObjective.value;
        payload.locked_items = lockedItems;
        payload.locked_boots = lockedBoots;
        payload.max_legendary_slots = maxSlots;

        // Show loading
        optimizeBtnText.textContent = "Optimizing...";
        optimizeBtnLoading.classList.remove("hidden");
        optimizeBtn.disabled = true;
        optimizeStatus.classList.add("hidden");

        fetch("/api/optimize", {
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

                // Fill empty legendary slots with optimized items
                const optimizedItems = data.items || [];
                // Figure out which items are new (not already locked)
                const lockedSet = new Set(lockedItems);
                const newItems = optimizedItems.filter((n) => !lockedSet.has(n));

                let newIdx = 0;
                for (let i = 1; i <= 6 && newIdx < newItems.length; i++) {
                    if (!selectedItems[i]) {
                        const name = newItems[newIdx];
                        const icon = itemIconMap[name] || "";
                        selectItem(String(i), name, icon);
                        newIdx++;
                    }
                }

                // Fill boots if it was empty
                if (!selectedItems.boots && data.boots) {
                    const icon = itemIconMap[data.boots] || "";
                    selectItem("boots", data.boots, icon);
                }

                // Show status
                optimizeStatus.textContent =
                    `Found in ${data.optimization_time_ms}ms (${data.evaluations} builds evaluated)`;
                optimizeStatus.classList.remove("hidden");

                // Trigger a full calculate to show the damage breakdown
                doCalculate();
            })
            .catch((err) => {
                showError("Optimization failed: " + err.message);
            })
            .finally(() => {
                isOptimizing = false;
                optimizeBtn.disabled = false;
                optimizeBtnText.textContent = "Optimize Build";
                optimizeBtnLoading.classList.add("hidden");
            });
    });
});
