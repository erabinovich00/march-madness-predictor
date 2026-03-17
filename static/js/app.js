document.addEventListener("DOMContentLoaded", () => {
    // ============================
    // Toast notifications (replaces alert/prompt)
    // ============================
    function showToast(message, type = "info", duration = 3000) {
        const container = document.getElementById("toast-container");
        const toast = document.createElement("div");
        toast.className = `toast toast-${type}`;
        const icons = { success: "\u2705", error: "\u274C", warning: "\u26A0\uFE0F", info: "\u2139\uFE0F" };
        toast.innerHTML = `<span class="toast-icon">${icons[type] || icons.info}</span><span>${message}</span>`;
        container.appendChild(toast);
        setTimeout(() => {
            toast.classList.add("toast-out");
            toast.addEventListener("animationend", () => toast.remove());
        }, duration);
    }

    // ============================
    // State
    // ============================
    let currentUser = null;  // { user_id, username }
    let tournamentLocked = false;
    let lockTime = null;
    let editingBracketId = null;  // null = new, number = editing existing
    let viewingOnly = false;      // true = read-only view, no editing
    let currentGroupId = null;   // currently viewed group in Groups tab

    // picks structure:
    // { East: [ [8 R1 winners], [4 R2], [2 R3], [1 R4] ], ..., final_four: { semifinal_1, semifinal_2, champion } }
    let picks = {};

    const REGIONS = ["East", "South", "West", "Midwest"];
    const ROUND_NAMES = {1: "Round of 64", 2: "Round of 32", 3: "Sweet 16", 4: "Elite 8"};
    const FIRST_ROUND = [
        [1, 16], [8, 9], [5, 12], [4, 13],
        [6, 11], [3, 14], [7, 10], [2, 15]
    ];

    // ============================
    // Init
    // ============================
    checkAuth();
    checkStatus();
    checkModel();
    initTabs();
    initSeedDropdowns();
    initChaosSlider();
    initMatchupCalc();
    initInsights();

    // ============================
    // Tabs
    // ============================
    function initTabs() {
        document.querySelectorAll(".tab").forEach(btn => {
            btn.addEventListener("click", () => {
                document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
                document.querySelectorAll(".tab-content").forEach(c => c.classList.add("hidden"));
                btn.classList.add("active");
                const tabId = btn.dataset.tab;
                document.getElementById("tab-" + tabId).classList.remove("hidden");
                if (tabId === "my-bracket") btn.textContent = "My Bracket";
                if (tabId === "live-results") loadLiveResults();
                if (tabId === "groups") loadGroups();
                if (tabId === "insights") loadInsightsTab();
            });
        });
    }

    // ============================
    // Auth
    // ============================
    async function checkAuth() {
        try {
            const r = await fetch("/api/me");
            const data = await r.json();
            if (data.logged_in) {
                currentUser = { user_id: data.user_id, username: data.username };
            }
        } catch (e) { /* not logged in */ }
        renderAuthStatus();
        renderBracketTab();
    }

    function renderAuthStatus() {
        const el = document.getElementById("auth-status");
        if (currentUser) {
            el.innerHTML = `
                <span class="user-greeting">Hi, <strong>${esc(currentUser.username)}</strong></span>
                <button id="logout-btn" class="btn-secondary btn-sm">Logout</button>
            `;
            document.getElementById("logout-btn").addEventListener("click", async () => {
                await fetch("/api/logout", { method: "POST" });
                currentUser = null;
                renderAuthStatus();
                renderBracketTab();
            });
        } else {
            el.innerHTML = `
                <a href="/login" class="btn-primary btn-sm">Sign In</a>
                <a href="/register" class="btn-secondary btn-sm">Register</a>
            `;
        }
    }

    // ============================
    // Tournament Status
    // ============================
    async function checkStatus() {
        try {
            const r = await fetch("/api/status");
            const data = await r.json();
            tournamentLocked = data.locked;
            lockTime = data.lock_time;
        } catch (e) { /* ignore */ }
        renderLockBanner();
    }

    function renderLockBanner() {
        const banner = document.getElementById("lock-banner");
        const msg = document.getElementById("lock-message");
        if (tournamentLocked) {
            banner.classList.remove("hidden");
            msg.textContent = "Brackets are locked! The tournament has started.";
        } else if (lockTime) {
            const lt = new Date(lockTime);
            const now = new Date();
            const diff = lt - now;
            if (diff > 0 && diff < 3 * 24 * 60 * 60 * 1000) {
                banner.classList.remove("hidden");
                banner.classList.add("lock-warning");
                msg.textContent = `Brackets lock on ${lt.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })} at ${lt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })} ET. Submit yours before tip-off!`;
            } else {
                banner.classList.add("hidden");
            }
        }
    }

    let mlModelActive = false;

    async function checkModel() {
        try {
            const r = await fetch("/api/model/status");
            const data = await r.json();
            mlModelActive = !!data.ready;
            const badge = document.getElementById("model-badge");
            if (badge) {
                if (data.ready) {
                    badge.textContent = "ML Model Active";
                    badge.classList.add("model-active");
                } else {
                    badge.textContent = "Seed-Based";
                    badge.classList.add("model-fallback");
                }
            }
            // Update autofill button text
            const afBtn = document.getElementById("autofill-btn");
            if (afBtn && data.ready) {
                afBtn.textContent = "Auto-Fill (ML)";
            }
        } catch (e) { /* ignore */ }
    }

    // ============================
    // Bracket Tab
    // ============================
    function renderBracketTab() {
        const authPrompt = document.getElementById("bracket-auth-prompt");
        const builder = document.getElementById("bracket-builder");
        if (!currentUser) {
            authPrompt.classList.remove("hidden");
            builder.classList.add("hidden");
        } else {
            authPrompt.classList.add("hidden");
            builder.classList.remove("hidden");
            loadSavedBrackets();
        }
    }

    async function loadSavedBrackets() {
        const list = document.getElementById("saved-brackets-list");
        try {
            const r = await fetch("/api/brackets");
            if (!r.ok) { list.innerHTML = "<p>Could not load brackets.</p>"; return; }
            const brackets = await r.json();
            if (brackets.length === 0) {
                list.innerHTML = '<p class="text-light">No brackets yet. Click "+ New Bracket" to get started!</p>';
            } else {
                list.innerHTML = brackets.map(b => {
                    const champ = b.picks && b.picks.final_four && b.picks.final_four.champion;
                    return `
                    <div class="saved-bracket-row">
                        <span class="bracket-name-label">${esc(b.name)}</span>
                        ${champ ? `<span class="bracket-champ-label">\u{1F3C6} ${esc(champ)}</span>` : '<span class="bracket-champ-label text-light">No champion picked</span>'}
                        <span class="text-light">${new Date(b.created_at).toLocaleDateString()}</span>
                        <button class="btn-sm btn-secondary" onclick="window._viewBracket(${b.id})">View</button>
                        ${!tournamentLocked ? `<button class="btn-sm btn-accent" onclick="window._editBracket(${b.id})">Edit</button>` : ''}
                    </div>`;
                }).join("");
            }
        } catch (e) {
            list.innerHTML = "<p>Error loading brackets.</p>";
        }
    }

    // Expose for inline onclick
    window._viewBracket = async function(bracketId) {
        try {
            const r = await fetch(`/api/brackets/${bracketId}`);
            if (!r.ok) return;
            const b = await r.json();
            editingBracketId = b.id;
            viewingOnly = true;
            picks = b.picks || {};
            const isOwnBracket = currentUser && b.username === currentUser.username;
            const tabBtn = document.querySelector('[data-tab="my-bracket"]');
            if (!isOwnBracket && b.username) {
                tabBtn.textContent = b.username + "'s Bracket";
            } else {
                tabBtn.textContent = "My Bracket";
            }
            document.getElementById("editor-title").textContent = b.name;
            setEditorReadOnly(true);
            showEditor();
            buildPickUI();
            restorePicksToUI();
        } catch (e) { console.error(e); }
    };

    window._editBracket = async function(bracketId) {
        if (tournamentLocked) { showToast("Brackets are locked!", "warning"); return; }
        try {
            const r = await fetch(`/api/brackets/${bracketId}`);
            if (!r.ok) return;
            const b = await r.json();
            editingBracketId = b.id;
            viewingOnly = false;
            picks = b.picks || {};
            document.querySelector('[data-tab="my-bracket"]').textContent = "My Bracket";
            document.getElementById("bracket-name").value = b.name;
            document.getElementById("editor-title").textContent = "Edit: " + b.name;
            setEditorReadOnly(false);
            showEditor();
            buildPickUI();
            restorePicksToUI();
        } catch (e) { console.error(e); }
    };

    function setEditorReadOnly(readOnly) {
        const editorActions = document.querySelector(".editor-actions");
        const chaosControl = document.querySelector(".chaos-control");
        const ffBtns = document.querySelectorAll(".ff-slot .pick-btn");
        if (readOnly) {
            editorActions.classList.add("hidden");
            chaosControl.classList.add("hidden");
        } else {
            editorActions.classList.remove("hidden");
            chaosControl.classList.remove("hidden");
        }
    }

    // New bracket
    document.getElementById("new-bracket-btn").addEventListener("click", () => {
        if (tournamentLocked) { showToast("Brackets are locked!", "warning"); return; }
        editingBracketId = null;
        viewingOnly = false;
        picks = {};
        document.querySelector('[data-tab="my-bracket"]').textContent = "My Bracket";
        const defaultName = currentUser ? currentUser.username + "'s Bracket" : "My Bracket";
        document.getElementById("bracket-name").value = defaultName;
        document.getElementById("editor-title").textContent = "New Bracket";
        setEditorReadOnly(false);
        showEditor();
        buildPickUI();
    });

    document.getElementById("cancel-edit-btn").addEventListener("click", hideEditor);
    document.getElementById("back-to-list-btn").addEventListener("click", hideEditor);

    function showEditor() {
        document.getElementById("bracket-editor").classList.remove("hidden");
        document.getElementById("saved-brackets-section").classList.add("hidden");
    }

    function hideEditor() {
        document.getElementById("bracket-editor").classList.add("hidden");
        document.getElementById("saved-brackets-section").classList.remove("hidden");
        viewingOnly = false;
        loadSavedBrackets();
    }

    // ============================
    // Bracket Pick UI
    // ============================
    function buildPickUI() {
        REGIONS.forEach(region => {
            const container = document.querySelector(`#pick-region-${region.toLowerCase()} .pick-rounds`);
            container.innerHTML = "";

            const teams = TEAMS[region];
            if (!teams) return;

            // Initialize picks for this region if needed
            if (!picks[region] || !Array.isArray(picks[region])) {
                picks[region] = [[], [], [], []];
            }

            // Build R1 matchups
            const r1Div = document.createElement("div");
            r1Div.className = "pick-round";
            r1Div.innerHTML = '<div class="round-label">Round of 64</div>';

            FIRST_ROUND.forEach(([seedA, seedB], idx) => {
                const nameA = teams[String(seedA)] || teams[seedA] || `Seed ${seedA}`;
                const nameB = teams[String(seedB)] || teams[seedB] || `Seed ${seedB}`;
                const matchDiv = document.createElement("div");
                matchDiv.className = "pick-matchup";
                matchDiv.dataset.region = region;
                matchDiv.dataset.round = "0";
                matchDiv.dataset.game = idx;

                matchDiv.innerHTML = `
                    <button class="pick-team" data-team="${esc(nameA)}" data-seed="${seedA}">
                        <span class="seed-badge">${seedA}</span> ${esc(nameA)}
                    </button>
                    <button class="pick-team" data-team="${esc(nameB)}" data-seed="${seedB}">
                        <span class="seed-badge">${seedB}</span> ${esc(nameB)}
                    </button>
                `;
                r1Div.appendChild(matchDiv);
            });
            container.appendChild(r1Div);

            // Build subsequent round placeholders (R2: 4 games, R3: 2, R4: 1)
            const roundGames = [4, 2, 1];
            const roundLabels = ["Round of 32", "Sweet 16", "Elite 8"];
            for (let ri = 0; ri < 3; ri++) {
                const rDiv = document.createElement("div");
                rDiv.className = "pick-round";
                rDiv.innerHTML = `<div class="round-label">${roundLabels[ri]}</div>`;
                for (let gi = 0; gi < roundGames[ri]; gi++) {
                    const matchDiv = document.createElement("div");
                    matchDiv.className = "pick-matchup";
                    matchDiv.dataset.region = region;
                    matchDiv.dataset.round = String(ri + 1);
                    matchDiv.dataset.game = gi;
                    matchDiv.innerHTML = `
                        <button class="pick-team empty" data-team="" data-seed="">
                            <span class="seed-badge">?</span> ---
                        </button>
                        <button class="pick-team empty" data-team="" data-seed="">
                            <span class="seed-badge">?</span> ---
                        </button>
                    `;
                    rDiv.appendChild(matchDiv);
                }
                container.appendChild(rDiv);
            }
        });

        // Bind click handlers
        document.querySelectorAll(".pick-rounds").forEach(container => {
            container.addEventListener("click", handlePickClick);
        });

        // Reset Final Four display
        resetFinalFourDisplay();
    }

    function handlePickClick(e) {
        const btn = e.target.closest(".pick-team");
        if (!btn || btn.classList.contains("empty") || viewingOnly || tournamentLocked) return;

        const matchDiv = btn.closest(".pick-matchup");
        const region = matchDiv.dataset.region;
        const roundIdx = parseInt(matchDiv.dataset.round);
        const gameIdx = parseInt(matchDiv.dataset.game);
        const teamName = btn.dataset.team;
        const teamSeed = btn.dataset.seed;

        if (!teamName) return;

        // Set the pick
        if (!picks[region]) picks[region] = [[], [], [], []];
        picks[region][roundIdx][gameIdx] = teamName;

        // Highlight selected
        matchDiv.querySelectorAll(".pick-team").forEach(b => b.classList.remove("selected"));
        btn.classList.add("selected");

        // Advance winner to next round
        advanceWinner(region, roundIdx, gameIdx, teamName, teamSeed);
    }

    function advanceWinner(region, roundIdx, gameIdx, teamName, teamSeed) {
        const nextRound = roundIdx + 1;
        if (nextRound > 3) {
            // Region winner -> Final Four
            updateFinalFourSlot(region, teamName, teamSeed);
            return;
        }

        const nextGameIdx = Math.floor(gameIdx / 2);
        const isTop = gameIdx % 2 === 0;
        const container = document.querySelector(`#pick-region-${region.toLowerCase()} .pick-rounds`);
        const rounds = container.querySelectorAll(".pick-round");
        const nextRoundDiv = rounds[nextRound];
        if (!nextRoundDiv) return;

        const matchups = nextRoundDiv.querySelectorAll(".pick-matchup");
        const nextMatch = matchups[nextGameIdx];
        if (!nextMatch) return;

        const buttons = nextMatch.querySelectorAll(".pick-team");
        const targetBtn = isTop ? buttons[0] : buttons[1];
        if (!targetBtn) return;

        // Check if the team in this slot changed - if so, clear downstream
        const oldTeam = targetBtn.dataset.team;
        targetBtn.dataset.team = teamName;
        targetBtn.dataset.seed = teamSeed;
        targetBtn.innerHTML = `<span class="seed-badge">${teamSeed}</span> ${esc(teamName)}`;
        targetBtn.classList.remove("empty");

        if (oldTeam && oldTeam !== teamName && oldTeam !== "") {
            // Clear this pick and downstream if it was selected
            if (targetBtn.classList.contains("selected")) {
                targetBtn.classList.remove("selected");
                clearDownstream(region, nextRound, nextGameIdx);
            }
        }
    }

    function clearDownstream(region, roundIdx, gameIdx) {
        // Clear pick for this round/game
        if (picks[region] && picks[region][roundIdx]) {
            picks[region][roundIdx][gameIdx] = undefined;
        }

        const nextRound = roundIdx + 1;
        if (nextRound > 3) {
            // Clear FF slot
            updateFinalFourSlot(region, null, null);
            return;
        }

        const nextGameIdx = Math.floor(gameIdx / 2);
        const isTop = gameIdx % 2 === 0;
        const container = document.querySelector(`#pick-region-${region.toLowerCase()} .pick-rounds`);
        const rounds = container.querySelectorAll(".pick-round");
        const nextRoundDiv = rounds[nextRound];
        if (!nextRoundDiv) return;

        const matchups = nextRoundDiv.querySelectorAll(".pick-matchup");
        const nextMatch = matchups[nextGameIdx];
        if (!nextMatch) return;

        const buttons = nextMatch.querySelectorAll(".pick-team");
        const btn = isTop ? buttons[0] : buttons[1];

        if (btn) {
            const wasSel = btn.classList.contains("selected");
            btn.dataset.team = "";
            btn.dataset.seed = "";
            btn.innerHTML = '<span class="seed-badge">?</span> ---';
            btn.classList.add("empty");
            btn.classList.remove("selected");
            if (wasSel) clearDownstream(region, nextRound, nextGameIdx);
        }
    }

    function updateFinalFourSlot(region, teamName, teamSeed) {
        // East->semifinal_1 team A, South->semifinal_1 team B
        // West->semifinal_2 team A, Midwest->semifinal_2 team B
        const map = { East: ["semifinal_1", "a"], South: ["semifinal_1", "b"], West: ["semifinal_2", "a"], Midwest: ["semifinal_2", "b"] };
        const [ff, side] = map[region];
        const slot = document.querySelector(`.ff-slot[data-ff="${ff}"]`);
        if (!slot) return;

        const btn = slot.querySelector(`.ff-team-${side}`);
        if (!btn) return;

        if (teamName) {
            btn.dataset.team = teamName;
            btn.dataset.seed = teamSeed;
            btn.textContent = `(${teamSeed}) ${teamName}`;
            btn.classList.remove("empty");
        } else {
            btn.dataset.team = "";
            btn.dataset.seed = "";
            btn.textContent = "--";
            btn.classList.add("empty");
        }

        // Clear FF winner if it involved this team
        const winnerEl = document.querySelector(`[data-ff-winner="${ff}"] strong`);
        if (winnerEl) winnerEl.textContent = "--";
        if (picks.final_four) picks.final_four[ff] = undefined;

        // Also clear championship if semifinal changed
        clearChampionship();
    }

    function resetFinalFourDisplay() {
        document.querySelectorAll(".ff-slot .pick-btn").forEach(btn => {
            btn.textContent = "--";
            btn.dataset.team = "";
            btn.dataset.seed = "";
            btn.classList.add("empty");
            btn.classList.remove("selected");
        });
        document.querySelectorAll("[data-ff-winner] strong").forEach(el => el.textContent = "--");
    }

    function clearChampionship() {
        const champSlot = document.querySelector('.ff-slot[data-ff="champion"]');
        if (champSlot) {
            champSlot.querySelectorAll(".pick-btn").forEach(btn => {
                btn.textContent = "--";
                btn.dataset.team = "";
                btn.dataset.seed = "";
                btn.classList.add("empty");
                btn.classList.remove("selected");
            });
        }
        const winnerEl = document.querySelector('[data-ff-winner="champion"] strong');
        if (winnerEl) winnerEl.textContent = "--";
        if (picks.final_four) picks.final_four.champion = undefined;
    }

    // Final Four click handlers
    document.querySelectorAll(".ff-slot").forEach(slot => {
        slot.addEventListener("click", (e) => {
            const btn = e.target.closest(".pick-btn");
            if (!btn || btn.classList.contains("empty") || viewingOnly || tournamentLocked) return;

            const ffName = slot.dataset.ff;
            const team = btn.dataset.team;
            if (!team) return;

            if (!picks.final_four) picks.final_four = {};

            if (ffName === "semifinal_1" || ffName === "semifinal_2") {
                picks.final_four[ffName] = team;
                slot.querySelectorAll(".pick-btn").forEach(b => b.classList.remove("selected"));
                btn.classList.add("selected");
                const winnerEl = document.querySelector(`[data-ff-winner="${ffName}"] strong`);
                if (winnerEl) winnerEl.textContent = team;

                // Advance to championship
                const champSlot = document.querySelector('.ff-slot[data-ff="champion"]');
                const side = ffName === "semifinal_1" ? "a" : "b";
                const champBtn = champSlot.querySelector(`.ff-team-${side}`);
                if (champBtn) {
                    champBtn.dataset.team = team;
                    champBtn.dataset.seed = btn.dataset.seed;
                    champBtn.textContent = `(${btn.dataset.seed}) ${team}`;
                    champBtn.classList.remove("empty");
                }
                // Clear champion if changed
                const oldChamp = picks.final_four.champion;
                if (oldChamp) {
                    const champWinner = document.querySelector('[data-ff-winner="champion"] strong');
                    if (champWinner) champWinner.textContent = "--";
                    picks.final_four.champion = undefined;
                    champSlot.querySelectorAll(".pick-btn").forEach(b => b.classList.remove("selected"));
                }
            } else if (ffName === "champion") {
                picks.final_four.champion = team;
                slot.querySelectorAll(".pick-btn").forEach(b => b.classList.remove("selected"));
                btn.classList.add("selected");
                const winnerEl = document.querySelector('[data-ff-winner="champion"] strong');
                if (winnerEl) winnerEl.textContent = team;
            }
        });
    });

    // ============================
    // Restore picks to UI (when editing)
    // ============================
    function restorePicksToUI() {
        // Deep-copy final_four before region restore, because advanceWinner ->
        // updateFinalFourSlot clears picks.final_four entries as a side-effect
        const savedFF = picks.final_four ? Object.assign({}, picks.final_four) : null;

        REGIONS.forEach(region => {
            const regionPicks = picks[region];
            if (!Array.isArray(regionPicks)) return;

            const container = document.querySelector(`#pick-region-${region.toLowerCase()} .pick-rounds`);
            const rounds = container.querySelectorAll(".pick-round");

            regionPicks.forEach((roundPicks, roundIdx) => {
                if (!Array.isArray(roundPicks)) return;
                const roundDiv = rounds[roundIdx];
                if (!roundDiv) return;

                roundPicks.forEach((winner, gameIdx) => {
                    if (!winner) return;
                    const matchups = roundDiv.querySelectorAll(".pick-matchup");
                    const match = matchups[gameIdx];
                    if (!match) return;

                    // Find the button with this team name and click it
                    const btns = match.querySelectorAll(".pick-team");
                    btns.forEach(btn => {
                        if (btn.dataset.team === winner) {
                            btn.classList.add("selected");
                            // Also advance to next round
                            advanceWinner(region, roundIdx, gameIdx, winner, btn.dataset.seed);
                        }
                    });
                });
            });
        });

        // Restore FF picks (use saved copy because advanceWinner -> updateFinalFourSlot
        // clears picks.final_four entries as a side-effect during region restoration)
        const ff = savedFF;
        if (ff) {
            ["semifinal_1", "semifinal_2"].forEach(sfName => {
                if (!ff[sfName]) return;
                const slot = document.querySelector(`.ff-slot[data-ff="${sfName}"]`);
                if (!slot) return;
                slot.querySelectorAll(".pick-btn").forEach(btn => {
                    if (btn.dataset.team === ff[sfName]) {
                        btn.classList.add("selected");
                        const winnerEl = document.querySelector(`[data-ff-winner="${sfName}"] strong`);
                        if (winnerEl) winnerEl.textContent = ff[sfName];

                        // Advance to championship slot
                        const champSlot = document.querySelector('.ff-slot[data-ff="champion"]');
                        const side = sfName === "semifinal_1" ? "a" : "b";
                        const champBtn = champSlot.querySelector(`.ff-team-${side}`);
                        if (champBtn) {
                            champBtn.dataset.team = ff[sfName];
                            champBtn.dataset.seed = btn.dataset.seed;
                            champBtn.textContent = `(${btn.dataset.seed}) ${ff[sfName]}`;
                            champBtn.classList.remove("empty");
                        }
                    }
                });
            });
            if (ff.champion) {
                const champSlot = document.querySelector('.ff-slot[data-ff="champion"]');
                if (champSlot) {
                    champSlot.querySelectorAll(".pick-btn").forEach(btn => {
                        if (btn.dataset.team === ff.champion) {
                            btn.classList.add("selected");
                            const winnerEl = document.querySelector('[data-ff-winner="champion"] strong');
                            if (winnerEl) winnerEl.textContent = ff.champion;
                        }
                    });
                }
            }

            // Restore picks.final_four from saved copy
            picks.final_four = ff;
        }
    }

    // ============================
    // Save Bracket
    // ============================
    document.getElementById("save-bracket-btn").addEventListener("click", async () => {
        if (tournamentLocked) { showToast("Brackets are locked!", "warning"); return; }

        const fallbackName = currentUser ? currentUser.username + "'s Bracket" : "My Bracket";
        const name = document.getElementById("bracket-name").value.trim() || fallbackName;
        const payload = { picks, name };

        try {
            let r;
            if (editingBracketId) {
                r = await fetch(`/api/brackets/${editingBracketId}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
            } else {
                r = await fetch("/api/brackets", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
            }
            const data = await r.json();
            if (r.ok) {
                showToast("Bracket saved!", "success");
                hideEditor();
            } else {
                showToast(data.error || "Failed to save bracket.", "error");
            }
        } catch (e) {
            showToast("Network error saving bracket.", "error");
        }
    });

    // ============================
    // Auto-fill with AI
    // ============================
    document.getElementById("autofill-btn").addEventListener("click", async () => {
        const btn = document.getElementById("autofill-btn");
        btn.disabled = true;
        btn.textContent = "Generating...";
        try {
            const chaos = parseInt(document.getElementById("chaos-slider").value, 10) / 100;
            const r = await fetch("/api/predict", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ chaos_factor: chaos }),
            });
            if (!r.ok) throw new Error();
            const bracket = await r.json();

            // Convert prediction output to picks format
            picks = {};
            REGIONS.forEach(region => {
                const regionData = bracket.regions[region];
                if (!regionData) return;
                picks[region] = [];
                regionData.rounds.forEach(round => {
                    const roundPicks = round.matchups.map(m => m.winner.name);
                    picks[region].push(roundPicks);
                });
            });

            // Final four
            picks.final_four = {};
            if (bracket.final_four && bracket.final_four.length >= 2) {
                const sf1 = bracket.final_four[0].matchups[0];
                const sf2 = bracket.final_four[0].matchups[1];
                picks.final_four.semifinal_1 = sf1.winner.name;
                picks.final_four.semifinal_2 = sf2.winner.name;
                if (bracket.final_four[1] && bracket.final_four[1].matchups[0]) {
                    picks.final_four.champion = bracket.final_four[1].matchups[0].winner.name;
                }
            }

            // Re-render the pick UI with the new picks
            buildPickUI();
            restorePicksToUI();
        } catch (e) {
            showToast("Failed to auto-fill bracket.", "error");
        } finally {
            btn.disabled = false;
            btn.textContent = mlModelActive ? "Auto-Fill (ML)" : "Auto-Fill (AI)";
        }
    });

    // ============================
    // Live Results Tab
    // ============================
    async function loadLiveResults() {
        const grid = document.getElementById("live-results-grid");
        const ffSection = document.getElementById("live-ff-section");
        try {
            const r = await fetch("/api/results");
            const results = await r.json();

            // Group by region and round
            const byRegion = {};
            const ffResults = [];
            results.forEach(g => {
                if (g.region === "Final Four") {
                    ffResults.push(g);
                } else {
                    if (!byRegion[g.region]) byRegion[g.region] = {};
                    if (!byRegion[g.region][g.round]) byRegion[g.region][g.round] = [];
                    byRegion[g.region][g.round].push(g);
                }
            });

            grid.innerHTML = REGIONS.map(region => {
                const regionData = byRegion[region] || {};
                let html = `<div class="region-bracket"><h3>${region} Region</h3>`;
                for (let rd = 1; rd <= 4; rd++) {
                    const games = regionData[rd] || [];
                    if (games.length === 0) continue;
                    html += `<div class="round-group"><div class="round-label">${ROUND_NAMES[rd] || "Round " + rd}</div>`;
                    games.forEach(g => {
                        const aWin = g.winner === g.team_a;
                        const bWin = g.winner === g.team_b;
                        html += `
                            <div class="matchup ${g.winner ? 'decided' : ''}">
                                <div class="matchup-team ${aWin ? 'winner' : (bWin ? 'loser' : '')}">
                                    <span class="seed-badge">${g.seed_a}</span>
                                    <span class="team-name">${esc(g.team_a)}</span>
                                </div>
                                <div class="matchup-team ${bWin ? 'winner' : (aWin ? 'loser' : '')}">
                                    <span class="seed-badge">${g.seed_b}</span>
                                    <span class="team-name">${esc(g.team_b)}</span>
                                </div>
                            </div>`;
                    });
                    html += "</div>";
                }
                html += "</div>";
                return html;
            }).join("");

            // Final Four results
            if (ffResults.length > 0) {
                let ffHtml = "<h3>Final Four & Championship</h3>";
                ffResults.forEach(g => {
                    const label = g.round === 6 ? "Championship" : "Semifinal";
                    const aWin = g.winner === g.team_a;
                    const bWin = g.winner === g.team_b;
                    ffHtml += `
                        <div class="round-group">
                            <div class="round-label">${label}</div>
                            <div class="matchup ${g.winner ? 'decided' : ''}">
                                <div class="matchup-team ${aWin ? 'winner' : (bWin ? 'loser' : '')}">
                                    <span class="seed-badge">${g.seed_a}</span>
                                    <span class="team-name">${esc(g.team_a)}</span>
                                </div>
                                <div class="matchup-team ${bWin ? 'winner' : (aWin ? 'loser' : '')}">
                                    <span class="seed-badge">${g.seed_b}</span>
                                    <span class="team-name">${esc(g.team_b)}</span>
                                </div>
                            </div>
                        </div>`;
                });
                ffSection.innerHTML = ffHtml;
                ffSection.classList.remove("hidden");
            } else {
                ffSection.innerHTML = "";
            }
        } catch (e) {
            grid.innerHTML = "<p>Error loading results.</p>";
        }
    }

    // --- Sync & auto-refresh ---
    let autoRefreshInterval = null;

    document.getElementById("sync-btn").addEventListener("click", async () => {
        const btn = document.getElementById("sync-btn");
        btn.disabled = true;
        btn.textContent = "Syncing...";
        try {
            const r = await fetch("/api/sync", { method: "POST" });
            const stats = await r.json();
            btn.textContent = stats.updated > 0 ? `Updated ${stats.updated}!` : "Up to date";
            if (stats.updated > 0) loadLiveResults();
            updateLastSyncTime();
        } catch (e) {
            btn.textContent = "Sync failed";
        }
        setTimeout(() => { btn.disabled = false; btn.textContent = "Sync Now"; }, 2000);
    });

    document.getElementById("auto-refresh-toggle").addEventListener("change", (e) => {
        if (e.target.checked) {
            startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    });

    function startAutoRefresh() {
        stopAutoRefresh();
        autoRefreshInterval = setInterval(async () => {
            // Only refresh if live results tab is active
            if (!document.getElementById("tab-live-results").classList.contains("hidden")) {
                await loadLiveResults();
                updateLastSyncTime();
            }
        }, 30000); // Refresh display every 30 seconds
    }

    function stopAutoRefresh() {
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
            autoRefreshInterval = null;
        }
    }

    function updateLastSyncTime() {
        const el = document.getElementById("last-sync-time");
        if (el) el.textContent = `Last refreshed: ${new Date().toLocaleTimeString()}`;
    }

    // Start auto-refresh by default
    startAutoRefresh();

    // ============================
    // Groups Tab
    // ============================
    async function refreshBracketDropdown(preselectId) {
        const sel = document.getElementById("group-bracket-select");
        if (!sel) return;
        const prev = preselectId != null ? String(preselectId) : sel.value;
        try {
            const br = await fetch("/api/brackets");
            const brackets = await br.json();
            sel.innerHTML = '<option value="">-- Select a bracket --</option>' +
                brackets.map(b => `<option value="${b.id}">${esc(b.name)}</option>`).join("");
            if (prev) sel.value = prev;
        } catch (e) { /* ignore */ }
    }

    async function loadGroups() {
        if (!currentUser) {
            document.getElementById("groups-auth-prompt").classList.remove("hidden");
            document.getElementById("groups-content").classList.add("hidden");
            return;
        }
        document.getElementById("groups-auth-prompt").classList.add("hidden");
        document.getElementById("groups-content").classList.remove("hidden");

        try {
            const r = await fetch("/api/groups");
            const groups = await r.json();
            const list = document.getElementById("groups-list");
            if (groups.length === 0) {
                list.innerHTML = '<p class="text-light">No groups yet. Create or join one!</p>';
            } else {
                list.innerHTML = groups.map(g => `
                    <div class="group-row" onclick="window._viewGroup(${g.id}, '${esc(g.name)}', '${esc(g.invite_code)}')">
                        <span class="group-name-label">${esc(g.name)}</span>
                        <span class="group-bracket-tag">${g.bracket_name ? '\ud83c\udfc0 ' + esc(g.bracket_name) : '<em>No bracket set</em>'}</span>
                        <span class="text-light">Code: ${esc(g.invite_code)}</span>
                    </div>
                `).join("");
            }
        } catch (e) {
            document.getElementById("groups-list").innerHTML = "<p>Error loading groups.</p>";
        }

        // Refresh bracket dropdown if group detail is already visible
        if (!document.getElementById("group-detail").classList.contains("hidden") && currentGroupId) {
            let savedBracketId = null;
            try {
                const r = await fetch(`/api/groups/${currentGroupId}/bracket`);
                if (r.ok) {
                    const data = await r.json();
                    savedBracketId = data.bracket_id;
                }
            } catch (e) { /* ignore */ }
            await refreshBracketDropdown(savedBracketId);
        }
    }

    window._viewGroup = async function(groupId, name, inviteCode) {
        currentGroupId = groupId;
        const detail = document.getElementById("group-detail");
        detail.classList.remove("hidden");
        document.getElementById("group-detail-name").textContent = name;
        document.getElementById("group-invite-code").textContent = inviteCode;

        // Fetch the user's current bracket for this group, then build dropdown with it pre-selected
        let savedBracketId = null;
        try {
            const r = await fetch(`/api/groups/${groupId}/bracket`);
            if (r.ok) {
                const data = await r.json();
                savedBracketId = data.bracket_id;
            }
        } catch (e) { /* ignore */ }
        await refreshBracketDropdown(savedBracketId);

        // Disable bracket selection if tournament is locked
        const sel = document.getElementById("group-bracket-select");
        const setBtn = document.getElementById("set-group-bracket-btn");
        if (tournamentLocked) {
            sel.disabled = true;
            setBtn.disabled = true;
            setBtn.textContent = "Locked";
        } else {
            sel.disabled = false;
            setBtn.disabled = false;
            setBtn.textContent = "Set";
        }

        // Set bracket button
        document.getElementById("set-group-bracket-btn").onclick = async () => {
            const btn = document.getElementById("set-group-bracket-btn");
            const bracketId = document.getElementById("group-bracket-select").value;
            if (!bracketId) { showToast("Select a bracket first.", "warning"); btn.textContent = "Select one!"; setTimeout(() => btn.textContent = "Set", 1500); return; }
            btn.disabled = true;
            btn.textContent = "Setting…";
            try {
                const r = await fetch(`/api/groups/${groupId}/bracket`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ bracket_id: parseInt(bracketId) }),
                });
                if (r.ok) {
                    showToast("Bracket set for this group!", "success");
                    btn.textContent = "Set ✓";
                    loadGroups(); // refresh group list to show updated bracket tag
                } else {
                    const msg = (await r.json()).error || "Failed to set bracket.";
                    showToast(msg, "error");
                    btn.textContent = "Error";
                }
            } catch (e) {
                showToast("Network error.", "error");
                btn.textContent = "Error";
            }
            setTimeout(() => { btn.textContent = "Set"; btn.disabled = false; }, 1500);
            loadLeaderboard(groupId);
        };

        loadLeaderboard(groupId);
    };

    async function loadLeaderboard(groupId) {
        try {
            const r = await fetch(`/api/groups/${groupId}/leaderboard`);
            const lb = await r.json();
            const body = document.getElementById("leaderboard-body");
            if (lb.length === 0) {
                body.innerHTML = '<tr><td colspan="5">No members yet.</td></tr>';
            } else {
                body.innerHTML = lb.map((m, i) => `
                    <tr class="${m.username === (currentUser && currentUser.username) ? 'highlight-row' : ''}">
                        <td>${i + 1}</td>
                        <td>${m.bracket_id ? `<a href="#" class="lb-view-bracket" data-bracket-id="${m.bracket_id}">${esc(m.username)}</a>` : esc(m.username)}</td>
                        <td>${m.champion ? esc(m.champion) : '<span class="text-light">—</span>'}</td>
                        <td>${m.correct}</td>
                        <td><strong>${m.score}</strong></td>
                    </tr>
                `).join("");
                // Attach click handlers for viewing brackets
                body.querySelectorAll('.lb-view-bracket').forEach(link => {
                    link.addEventListener('click', (e) => {
                        e.preventDefault();
                        const bracketId = link.dataset.bracketId;
                        if (bracketId) {
                            document.querySelector('[data-tab="my-bracket"]').click();
                            window._viewBracket(parseInt(bracketId));
                        }
                    });
                });
            }
        } catch (e) {
            document.getElementById("leaderboard-body").innerHTML = '<tr><td colspan="5">Error loading leaderboard.</td></tr>';
        }
    }

    // Copy invite code
    document.getElementById("copy-invite-btn").addEventListener("click", () => {
        const code = document.getElementById("group-invite-code").textContent;
        navigator.clipboard.writeText(code).then(() => {
            const btn = document.getElementById("copy-invite-btn");
            btn.textContent = "Copied!";
            setTimeout(() => btn.textContent = "Copy", 1500);
        });
    });

    // Create group
    document.getElementById("create-group-btn").addEventListener("click", () => {
        document.getElementById("create-group-form").classList.remove("hidden");
        document.getElementById("join-group-form").classList.add("hidden");
        const input = document.getElementById("create-group-name");
        input.value = "";
        input.focus();
    });

    document.getElementById("create-group-cancel").addEventListener("click", () => {
        document.getElementById("create-group-form").classList.add("hidden");
    });

    document.getElementById("create-group-submit").addEventListener("click", async () => {
        const name = document.getElementById("create-group-name").value.trim();
        if (!name) return;
        try {
            const r = await fetch("/api/groups", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name }),
            });
            if (r.ok) {
                document.getElementById("create-group-form").classList.add("hidden");
                loadGroups();
            } else {
                showToast((await r.json()).error || "Failed to create group.", "error");
            }
        } catch (e) { showToast("Network error.", "error"); }
    });

    document.getElementById("create-group-name").addEventListener("keydown", (e) => {
        if (e.key === "Enter") document.getElementById("create-group-submit").click();
    });

    // Join group
    document.getElementById("join-group-btn").addEventListener("click", () => {
        document.getElementById("join-group-form").classList.remove("hidden");
        document.getElementById("create-group-form").classList.add("hidden");
        const input = document.getElementById("join-group-code");
        input.value = "";
        input.focus();
    });

    document.getElementById("join-group-cancel").addEventListener("click", () => {
        document.getElementById("join-group-form").classList.add("hidden");
    });

    document.getElementById("join-group-submit").addEventListener("click", async () => {
        const code = document.getElementById("join-group-code").value.trim();
        if (!code) return;
        try {
            const r = await fetch("/api/groups/join", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ invite_code: code }),
            });
            if (r.ok) {
                document.getElementById("join-group-form").classList.add("hidden");
                loadGroups();
            } else {
                showToast((await r.json()).error || "Failed to join group.", "error");
            }
        } catch (e) { showToast("Network error.", "error"); }
    });

    document.getElementById("join-group-code").addEventListener("keydown", (e) => {
        if (e.key === "Enter") document.getElementById("join-group-submit").click();
    });

    // ============================
    // Matchup Calculator (Tools tab)
    // ============================
    function initSeedDropdowns() {
        const teamA = document.getElementById("team-a");
        const teamB = document.getElementById("team-b");
        if (!teamA || !teamB) return;

        function populateTeams() {
            teamA.innerHTML = "";
            teamB.innerHTML = "";
            for (const region of ["East", "South", "West", "Midwest"]) {
                const teams = TEAMS[region] || {};
                const groupA = document.createElement("optgroup");
                groupA.label = region;
                const groupB = document.createElement("optgroup");
                groupB.label = region;
                for (let i = 1; i <= 16; i++) {
                    const name = teams[String(i)] || teams[i] || `Seed ${i}`;
                    const val = `${region}:${i}`;
                    groupA.appendChild(new Option(`#${i} ${name}`, val));
                    groupB.appendChild(new Option(`#${i} ${name}`, val));
                }
                teamA.appendChild(groupA);
                teamB.appendChild(groupB);
            }
            teamA.value = "East:1";
            teamB.value = "South:1";
        }

        populateTeams();
    }

    function initMatchupCalc() {
        const calcBtn = document.getElementById("calc-btn");
        if (!calcBtn) return;
        calcBtn.addEventListener("click", async () => {
            const teamAVal = document.getElementById("team-a").value;
            const teamBVal = document.getElementById("team-b").value;
            const [regionA, seedA] = teamAVal.split(":");
            const [regionB, seedB] = teamBVal.split(":");
            const round = document.getElementById("round-select").value;
            const params = new URLSearchParams({ seed_a: seedA, seed_b: seedB, round, region_a: regionA, region_b: regionB });
            const r = await fetch(`/api/matchup?${params}`);
            const data = await r.json();
            const result = document.getElementById("matchup-result");
            const teamsA = TEAMS[regionA] || {};
            const teamsB = TEAMS[regionB] || {};
            const nameA = data.team_a || teamsA[String(seedA)] || teamsA[seedA] || `#${seedA} Seed`;
            const nameB = data.team_b || teamsB[String(seedB)] || teamsB[seedB] || `#${seedB} Seed`;
            const modelLabel = data.model === "ml" ? "ML Model" : "Seed-Based";
            result.classList.remove("hidden");

            let analyticsHtml = "";
            if (data.rating_a && data.rating_b) {
                const ra = data.rating_a;
                const rb = data.rating_b;
                analyticsHtml = `
                <div class="analytics-comparison">
                    <table class="analytics-table">
                        <thead><tr><th>Stat</th><th>${esc(nameA)}</th><th>${esc(nameB)}</th></tr></thead>
                        <tbody>
                            <tr><td>Record</td><td>${esc(ra.record)}</td><td>${esc(rb.record)}</td></tr>
                            <tr><td>PPG</td><td>${ra.ppg}</td><td>${rb.ppg}</td></tr>
                            <tr><td>Opp PPG</td><td>${ra.opp_ppg}</td><td>${rb.opp_ppg}</td></tr>
                            <tr><td>Point Diff</td><td class="${ra.point_diff>rb.point_diff?'stat-better':''}">${ra.point_diff>0?'+':''}${ra.point_diff}</td><td class="${rb.point_diff>ra.point_diff?'stat-better':''}">${rb.point_diff>0?'+':''}${rb.point_diff}</td></tr>
                            <tr><td>FG%</td><td class="${ra.fg_pct>rb.fg_pct?'stat-better':''}">${ra.fg_pct}%</td><td class="${rb.fg_pct>ra.fg_pct?'stat-better':''}">${rb.fg_pct}%</td></tr>
                            <tr><td>3PT%</td><td class="${ra.three_pct>rb.three_pct?'stat-better':''}">${ra.three_pct}%</td><td class="${rb.three_pct>ra.three_pct?'stat-better':''}">${rb.three_pct}%</td></tr>
                            <tr><td>FT%</td><td>${ra.ft_pct}%</td><td>${rb.ft_pct}%</td></tr>
                            <tr><td>Rebounds</td><td class="${ra.rebounds>rb.rebounds?'stat-better':''}">${ra.rebounds}</td><td class="${rb.rebounds>ra.rebounds?'stat-better':''}">${rb.rebounds}</td></tr>
                            <tr><td>Assists</td><td class="${ra.assists>rb.assists?'stat-better':''}">${ra.assists}</td><td class="${rb.assists>ra.assists?'stat-better':''}">${rb.assists}</td></tr>
                            <tr><td>Turnovers</td><td class="${ra.turnovers<rb.turnovers?'stat-better':''}">${ra.turnovers}</td><td class="${rb.turnovers<ra.turnovers?'stat-better':''}">${rb.turnovers}</td></tr>
                            <tr><td>Steals</td><td class="${ra.steals>rb.steals?'stat-better':''}">${ra.steals}</td><td class="${rb.steals>ra.steals?'stat-better':''}">${rb.steals}</td></tr>
                            <tr><td>Blocks</td><td class="${ra.blocks>rb.blocks?'stat-better':''}">${ra.blocks}</td><td class="${rb.blocks>ra.blocks?'stat-better':''}">${rb.blocks}</td></tr>
                            <tr><td>SOS Rating</td><td>${ra.sos}</td><td>${rb.sos}</td></tr>
                        </tbody>
                    </table>
                </div>`;
            }

            result.innerHTML = `
                <div class="model-badge">${esc(modelLabel)} <span class="model-icon">${data.model === 'ml' ? '🤖' : '📊'}</span></div>
                <div style="display:flex;justify-content:space-between;margin-bottom:0.5rem">
                    <strong>#${data.seed_a} ${esc(nameA)}: ${data.probability_a}%</strong>
                    <strong>#${data.seed_b} ${esc(nameB)}: ${data.probability_b}%</strong>
                </div>
                <div class="prob-bar-container">
                    <div class="prob-bar team-a" style="width:${data.probability_a}%">${data.probability_a}%</div>
                    <div class="prob-bar team-b" style="width:${data.probability_b}%">${data.probability_b}%</div>
                </div>
                ${analyticsHtml}`;
        });
    }

    function initChaosSlider() {
        const slider = document.getElementById("chaos-slider");
        const display = document.getElementById("chaos-value");
        if (!slider || !display) return;
        slider.addEventListener("input", () => {
            display.textContent = `${slider.value}%`;
        });
    }

    // ============================
    // Utility
    // ============================
    function esc(str) {
        if (!str) return "";
        const d = document.createElement("div");
        d.textContent = str;
        return d.innerHTML;
    }

    // ============================
    // Insights Tab
    // ============================
    function initInsights() {
        const analyzeBtn = document.getElementById("analyze-btn");
        if (analyzeBtn) {
            analyzeBtn.addEventListener("click", runAnalysis);
        }
        const refreshHealthBtn = document.getElementById("refresh-health-btn");
        if (refreshHealthBtn) {
            refreshHealthBtn.addEventListener("click", runHealth);
        }
    }

    function loadInsightsTab() {
        const authPrompt = document.getElementById("insights-auth-prompt");
        const content = document.getElementById("insights-content");
        if (!currentUser) {
            authPrompt.classList.remove("hidden");
            content.classList.add("hidden");
            return;
        }
        authPrompt.classList.add("hidden");
        content.classList.remove("hidden");
        populateInsightsBracketDropdown();
    }

    async function populateInsightsBracketDropdown() {
        const sel = document.getElementById("insights-bracket-dropdown");
        if (!sel) return;
        try {
            const r = await fetch("/api/brackets");
            if (!r.ok) return;
            const brackets = await r.json();
            sel.innerHTML = brackets.length === 0
                ? '<option value="">No brackets saved</option>'
                : brackets.map(b => `<option value="${b.id}">${esc(b.name)}</option>`).join("");
        } catch (e) { sel.innerHTML = '<option value="">Error loading</option>'; }
    }

    async function runAnalysis() {
        const sel = document.getElementById("insights-bracket-dropdown");
        const bracketId = sel ? sel.value : null;
        if (!bracketId) { showToast("Select a bracket first", "warning"); return; }

        const btn = document.getElementById("analyze-btn");
        btn.disabled = true;
        btn.textContent = "Analyzing...";

        try {
            const r = await fetch(`/api/brackets/${bracketId}/analyze`);
            if (!r.ok) throw new Error();
            const data = await r.json();
            renderRiskReport(data);
            // Also load health
            runHealth();
        } catch (e) {
            showToast("Failed to analyze bracket", "error");
        } finally {
            btn.disabled = false;
            btn.textContent = "Analyze";
        }
    }

    function renderRiskReport(data) {
        // Risk card
        const riskCard = document.getElementById("risk-card");
        riskCard.classList.remove("hidden");
        document.getElementById("risk-score-num").textContent = data.risk_score;
        document.getElementById("risk-emoji").textContent = data.risk_emoji;
        document.getElementById("risk-label").textContent = data.risk_label;
        document.getElementById("risk-desc").textContent = data.risk_desc;
        document.getElementById("risk-percentile").textContent = data.percentile + "%";
        document.getElementById("risk-upsets").textContent = data.upset_count;
        document.getElementById("risk-expected").textContent = Math.round(data.expected_points);
        document.getElementById("risk-max").textContent = data.max_possible;

        // Color the score circle based on risk
        const circle = document.querySelector(".risk-score-circle");
        if (data.risk_score < 20) circle.className = "risk-score-circle risk-chalk";
        else if (data.risk_score < 40) circle.className = "risk-score-circle risk-calculated";
        else if (data.risk_score < 60) circle.className = "risk-score-circle risk-bold";
        else if (data.risk_score < 80) circle.className = "risk-score-circle risk-fearless";
        else circle.className = "risk-score-circle risk-reckless";

        // Champion
        const champCard = document.getElementById("champ-card");
        if (data.champion) {
            champCard.classList.remove("hidden");
            const c = data.champion;
            document.getElementById("champ-content").innerHTML = `
                <div class="champ-analysis">
                    <div class="champ-pick">
                        <span class="champ-seed-badge">${c.seed}</span>
                        <span class="champ-name">${esc(c.name)}</span>
                        <span class="champ-region">${esc(c.region)} Region</span>
                    </div>
                    <div class="champ-stats">
                        <div class="champ-stat">
                            <span class="stat-value">${c.historical_rate}%</span>
                            <span class="stat-label">Historical win rate for #${c.seed} seeds</span>
                        </div>
                        <div class="champ-stat">
                            <span class="stat-value">${c.rating}</span>
                            <span class="stat-label">Strength rating</span>
                        </div>
                    </div>
                </div>
            `;
        } else {
            champCard.classList.add("hidden");
        }

        // Region risk bars
        const regionCard = document.getElementById("region-risk-card");
        if (data.region_risk && Object.keys(data.region_risk).length > 0) {
            regionCard.classList.remove("hidden");
            document.getElementById("region-risk-bars").innerHTML = Object.entries(data.region_risk).map(([region, r]) => {
                const barColor = r.risk < 25 ? 'var(--win)' : r.risk < 50 ? 'var(--primary)' : r.risk < 75 ? 'var(--primary-light)' : 'var(--lose)';
                return `
                <div class="region-risk-row">
                    <span class="region-risk-name">${esc(region)}</span>
                    <div class="region-risk-bar-track">
                        <div class="region-risk-bar-fill" style="width:${Math.min(r.risk, 100)}%;background:${barColor}"></div>
                    </div>
                    <span class="region-risk-value">${r.risk}%</span>
                    <span class="region-risk-upsets">${r.upsets} upset${r.upsets !== 1 ? 's' : ''}</span>
                </div>`;
            }).join("");
        } else {
            regionCard.classList.add("hidden");
        }

        // All matchups grouped by round, sorted riskiest to safest
        const matchupsCard = document.getElementById("matchups-card");
        if (data.all_games && data.all_games.length > 0) {
            matchupsCard.classList.remove("hidden");
            const roundOrder = [1, 2, 3, 4, 5, 6];
            const roundNames = {1: "Round of 64", 2: "Round of 32", 3: "Sweet 16", 4: "Elite 8", 5: "Final Four", 6: "Championship"};
            const grouped = {};
            for (const g of data.all_games) {
                if (!grouped[g.round]) grouped[g.round] = [];
                grouped[g.round].push(g);
            }
            let html = "";
            for (const rd of roundOrder) {
                const games = grouped[rd];
                if (!games || games.length === 0) continue;
                games.sort((a, b) => a.win_prob - b.win_prob);
                html += `<div class="matchup-round-group">`;
                html += `<h4 class="matchup-round-title">${esc(roundNames[rd])}</h4>`;
                for (const g of games) {
                    const prob = Math.round(g.win_prob * 100);
                    const probClass = prob < 40 ? "prob-danger" : prob < 65 ? "prob-warn" : "prob-safe";
                    const loserName = g.loser || ("#" + g.loser_seed + " seed");
                    html += `
                    <div class="matchup-row">
                        <div class="matchup-teams">
                            <span class="matchup-winner"><span class="seed-badge">${g.winner_seed}</span> ${esc(g.winner)}</span>
                            <span class="matchup-vs">over</span>
                            <span class="matchup-loser"><span class="seed-badge">${g.loser_seed}</span> ${esc(loserName)}</span>
                        </div>
                        <span class="matchup-region">${esc(g.region)}</span>
                        <span class="matchup-prob ${probClass}">${prob}%</span>
                    </div>`;
                }
                html += `</div>`;
            }
            document.getElementById("matchups-content").innerHTML = html;
        } else {
            matchupsCard.classList.add("hidden");
        }
    }

    async function runHealth() {
        const sel = document.getElementById("insights-bracket-dropdown");
        const bracketId = sel ? sel.value : null;
        if (!bracketId) return;

        const healthCard = document.getElementById("health-card");
        healthCard.classList.remove("hidden");

        try {
            const r = await fetch(`/api/brackets/${bracketId}/health`);
            if (!r.ok) throw new Error();
            const h = await r.json();
            renderHealth(h);
        } catch (e) {
            document.getElementById("health-content").innerHTML = '<p class="text-light">Could not load health data.</p>';
        }
    }

    function renderHealth(h) {
        const total = h.correct + h.incorrect + h.pending;
        const correctPct = total > 0 ? Math.round((h.correct / total) * 100) : 0;

        let html = `
            <div class="health-overview">
                <div class="health-status">
                    <span class="health-emoji">${h.health_emoji}</span>
                    <span class="health-label">${esc(h.health_label)}</span>
                </div>
                <div class="health-stats">
                    <div class="health-stat">
                        <span class="stat-value">${h.current_points}</span>
                        <span class="stat-label">Current Pts</span>
                    </div>
                    <div class="health-stat">
                        <span class="stat-value">${h.ceiling}</span>
                        <span class="stat-label">Ceiling</span>
                    </div>
                    <div class="health-stat">
                        <span class="stat-value health-correct">${h.correct}</span>
                        <span class="stat-label">Correct</span>
                    </div>
                    <div class="health-stat">
                        <span class="stat-value health-incorrect">${h.incorrect}</span>
                        <span class="stat-label">Wrong</span>
                    </div>
                    <div class="health-stat">
                        <span class="stat-value">${h.pending}</span>
                        <span class="stat-label">Pending</span>
                    </div>
                </div>
            </div>

            <div class="health-bar-wrapper">
                <div class="health-bar">
                    <div class="health-bar-correct" style="width:${total > 0 ? (h.correct/total)*100 : 0}%"></div>
                    <div class="health-bar-incorrect" style="width:${total > 0 ? (h.incorrect/total)*100 : 0}%"></div>
                </div>
                <div class="health-bar-labels">
                    <span class="health-correct">${h.correct} correct</span>
                    <span class="health-incorrect">${h.incorrect} busted</span>
                    <span>${h.pending} remaining</span>
                </div>
            </div>
        `;

        // Critical games
        if (h.critical_games && h.critical_games.length > 0) {
            html += `<h4 class="health-section-title">Must-Win Games</h4><div class="critical-games">`;
            h.critical_games.forEach(g => {
                html += `
                    <div class="critical-game-row">
                        <span class="critical-team"><span class="seed-badge">${g.seed || '?'}</span> ${esc(g.team)}</span>
                        <span class="critical-round">${esc(g.round_name)}</span>
                        <span class="critical-region">${esc(g.region)}</span>
                        <span class="critical-points">+${g.points_at_stake} pts</span>
                    </div>`;
            });
            html += '</div>';
        }

        // Busted picks
        if (h.busted_picks && h.busted_picks.length > 0) {
            html += `<h4 class="health-section-title">Busted Picks</h4><div class="busted-picks">`;
            h.busted_picks.forEach(b => {
                html += `
                    <div class="busted-pick-row">
                        <span class="busted-picked">\u2716 ${esc(b.picked)}</span>
                        <span class="busted-actual">\u2192 ${esc(b.actual)}</span>
                        <span class="busted-round">${esc(b.round_name)}</span>
                        <span class="busted-points">-${b.points_lost} pts</span>
                    </div>`;
            });
            html += '</div>';
        }

        document.getElementById("health-content").innerHTML = html;
    }
});
