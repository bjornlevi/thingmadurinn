const photo = document.getElementById("member-photo");
const optionsEl = document.getElementById("options");
const promptEl = document.querySelector(".prompt");
const statusEl = document.getElementById("status");
const nextButton = document.getElementById("next-round");
const streakEl = document.getElementById("streak");
const timerEl = document.getElementById("timer");
const timerFill = document.getElementById("timer-fill");
const highScoreEl = document.getElementById("high-score");
const leaderboardGrid = document.getElementById("leaderboard-grid");
const attemptsList = document.getElementById("attempts-list");
const clearAttemptsBtn = document.getElementById("clear-attempts");
const gameLinks = document.querySelectorAll(".game-link");
const difficultySlider = document.getElementById("difficulty-slider");
const difficultyValueEl = document.getElementById("difficulty-value");
const titleEl = document.getElementById("game-title");
const ledeEl = document.getElementById("game-lede");
const basePath = document.body.dataset.base || "";

const TIMER_LIMIT = 30;
const DIFFICULTIES = [2, 3, 4, 5, 6];
const GAME_COPY = {
    "who-is": {
        title: "Hver er þingmaðurinn?",
        lede: "Við sýnum mynd af þingmanni og þú velur nafnið sem passar.",
        prompt: "Veldu nafnið sem passar við myndina.",
    },
    party: {
        title: "Í hvaða þingflokki var þingmaðurinn?",
        lede: "Veldu réttan þingflokk út frá myndinni.",
        prompt: "Í hvaða þingflokki var þingmaðurinn?",
    },
    mixed: {
        title: "Þekkir þú þingmennina?",
        lede: "Við skiptum á milli þess að giska á þingmann eða þingflokk.",
        prompt: "Hvaða spurning kemur núna?",
    },
};

let currentToken = null;
let locked = false;
let streak = 0;
let countdownId = null;
let timeLeft = TIMER_LIMIT;
let highScores = [];
let highScoresByDifficulty = {};
let currentGame = "who-is";
let currentDifficulty = 4;
let currentQuestionType = "who-is";
let currentOptions = [];
let attempts = [];
const initialLink = Array.from(gameLinks).find((link) => link.classList.contains("active")) || gameLinks[0];
if (initialLink && initialLink.dataset.game) {
    currentGame = initialLink.dataset.game;
}
if (difficultySlider && difficultySlider.value) {
    currentDifficulty = Number(difficultySlider.value);
    if (difficultyValueEl) difficultyValueEl.textContent = String(currentDifficulty);
}

async function fetchJSON(url, options) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`Villa: ${resp.status} ${text}`);
    }
    return resp.json();
}

function updateGameCopy(mode) {
    const copy = GAME_COPY[mode] || GAME_COPY["who-is"];
    if (titleEl) titleEl.textContent = copy.title;
    if (ledeEl) ledeEl.textContent = copy.lede;
    if (promptEl) promptEl.textContent = copy.prompt;
}

function renderStatus(text, positive = false, negative = false) {
    statusEl.textContent = text;
    statusEl.classList.toggle("positive", positive);
    statusEl.classList.toggle("negative", negative);
}

function renderStreak() {
    const copy = GAME_COPY[currentGame] || GAME_COPY["who-is"];
    streakEl.textContent = `Röð rétt svarað: ${streak} — ${copy.title} (${currentDifficulty} valk.)`;
}

function renderTimer() {
    const safeTime = Math.max(0, timeLeft);
    timerEl.textContent = `${safeTime}s`;
    if (timerFill) {
        const pct = Math.max(0, Math.min(100, (safeTime / TIMER_LIMIT) * 100));
        timerFill.style.width = `${pct}%`;
    }
}

function renderHighScore() {
    const best = highScores[0];
    if (!highScoreEl) return;
    const copy = GAME_COPY[currentGame] || GAME_COPY["who-is"];
    const label = `${currentDifficulty} valk. — ${copy.title}`;
    highScoreEl.textContent = best
        ? `Flest rétt (${label}): ${best.score} — ${best.initials}`
        : `Lengsta röð (${label}): 0 — ---`;
}

function renderLeaderboard() {
    if (!leaderboardGrid) return;
    leaderboardGrid.innerHTML = "";
    const copy = GAME_COPY[currentGame] || GAME_COPY["who-is"];

    DIFFICULTIES.forEach((diff) => {
        const col = document.createElement("div");
        col.className = "leaderboard-col";
        const heading = document.createElement("p");
        heading.className = "leaderboard-col-title";
        heading.textContent = `${diff} valk. — ${copy.title}`;
        col.appendChild(heading);

        const list = document.createElement("ol");
        list.className = "leaderboard-list";
        const rows = highScoresByDifficulty[diff] || [];

        if (!rows.length) {
            const li = document.createElement("li");
            li.textContent = "Engin met enn.";
            list.appendChild(li);
        } else {
            rows.forEach((entry) => {
                const li = document.createElement("li");
                const nameSpan = document.createElement("span");
                nameSpan.textContent = entry.initials;
                const scoreSpan = document.createElement("span");
                scoreSpan.textContent = entry.score;
                li.appendChild(nameSpan);
                li.appendChild(scoreSpan);
                list.appendChild(li);
            });
        }

        col.appendChild(list);
        leaderboardGrid.appendChild(col);
    });
}

function renderAttempts() {
    if (!attemptsList) return;
    attemptsList.innerHTML = "";
    if (!attempts.length) {
        const li = document.createElement("li");
        li.textContent = "Engar tilraunir í þessari lotu enn.";
        attemptsList.appendChild(li);
        return;
    }

    attempts
        .slice(-15)
        .reverse()
        .forEach((item) => {
            const li = document.createElement("li");
            const left = document.createElement("span");
            left.textContent = item.label;
            const tag = document.createElement("span");
            tag.className = "tag";
            tag.textContent = item.question_type === "party" ? "Þingflokkur" : "Þingmaður";
            left.appendChild(document.createTextNode(" "));
            left.appendChild(tag);

            const res = document.createElement("span");
            res.className = `result ${item.correct ? "correct" : "wrong"}`;
            res.textContent = item.correct ? "Rétt" : "Rangt";

            li.appendChild(left);
            li.appendChild(res);
            attemptsList.appendChild(li);
        });
}

async function fetchHighScores() {
    highScores = [];
    highScoresByDifficulty = {};
    try {
        const requests = DIFFICULTIES.map(async (diff) => {
            const params = new URLSearchParams({
                game: currentGame,
                difficulty: String(diff),
            });
            const data = await fetchJSON(`${basePath}/api/high-scores?${params.toString()}`);
            highScoresByDifficulty[diff] = data.high_scores || [];
        });
        await Promise.all(requests);
        highScores = highScoresByDifficulty[currentDifficulty] || [];
    } catch (err) {
        renderStatus(err.message || "Gat ekki sótt lengstu röð.", false, true);
    } finally {
        renderHighScore();
        renderLeaderboard();
    }
}

async function submitHighScore(score, initials) {
    const data = await fetchJSON(`${basePath}/api/high-scores`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ score, initials, game: currentGame, difficulty: currentDifficulty }),
    });
    const updated = data.high_scores || highScores;
    highScoresByDifficulty[currentDifficulty] = updated;
    highScores = updated;
    renderHighScore();
    renderLeaderboard();
}

function requestInitials(defaultValue = "---") {
    const input = prompt("Nýtt met! Settu inn þrjá stafi (má vera UTF-8):", defaultValue);
    if (input === null) return null;
    const cleaned = Array.from(input.trim()).slice(0, 3).join("");
    return cleaned || null;
}

async function maybeSubmitHighScore(runScore) {
    if (runScore <= 0) return;
    const minScore = highScores.length < 10 ? 0 : highScores[highScores.length - 1].score;
    if (runScore < minScore) return;

    const initials = requestInitials(highScores[0]?.initials || "---");
    if (!initials) return;

    try {
        await submitHighScore(runScore, initials);
        renderStatus("Lengsta röð vistuð!", true, false);
    } catch (err) {
        renderStatus(err.message || "Tókst ekki að vista met.", false, true);
    }
}

function disableOptions() {
    const buttons = Array.from(optionsEl.querySelectorAll("button.option"));
    buttons.forEach((btn) => {
        btn.disabled = true;
    });
}

function clearTimer() {
    if (countdownId) {
        clearInterval(countdownId);
        countdownId = null;
    }
}

function startTimer() {
    clearTimer();
    timeLeft = TIMER_LIMIT;
    renderTimer();
    countdownId = setInterval(() => {
        timeLeft -= 1;
        if (timeLeft <= 0) {
            clearTimer();
            timeLeft = 0;
            renderTimer();
            handleTimeout().catch(() => {});
        } else {
            renderTimer();
        }
    }, 1000);
}

async function handleTimeout() {
    if (locked) return;
    locked = true;
    const finishedRun = streak;
    streak = 0;
    renderStreak();
    renderStatus("Tíminn rann út. Reyndu aftur.", false, true);
    disableOptions();
    nextButton.disabled = false;
    await maybeSubmitHighScore(finishedRun);
}

function resetState() {
    locked = false;
    currentToken = null;
    currentQuestionType = currentGame;
    currentOptions = [];
    clearTimer();
    timeLeft = TIMER_LIMIT;
    renderStatus("Veldu svar til að byrja.");
    nextButton.disabled = true;
    optionsEl.innerHTML = "";
    photo.alt = "";
    renderTimer();
}

async function loadQuestion() {
    resetState();
    try {
        const params = new URLSearchParams({
            game: currentGame,
            difficulty: String(currentDifficulty),
        });
        const data = await fetchJSON(`${basePath}/api/question?${params.toString()}`);
        currentToken = data.token;
        currentQuestionType = data.question_type;
        if (promptEl && data.prompt) {
            promptEl.textContent = data.prompt;
        }

        photo.src = data.image_url;
        photo.alt = "Mynd af þingmanni. Veldu rétt svar.";

        currentOptions = data.options || [];
        currentOptions.forEach((option) => {
            const btn = document.createElement("button");
            btn.className = "option";
            btn.type = "button";
            btn.textContent = option.label;
            btn.dataset.id = option.id;
            btn.addEventListener("click", () => handleGuess(btn, option.id));
            optionsEl.appendChild(btn);
        });
        startTimer();
    } catch (err) {
        renderStatus(err.message || "Gat ekki sótt gögn.", false, true);
    }
}

async function handleGuess(button, guessId) {
    if (locked || !currentToken) return;
    locked = true;
    clearTimer();

    try {
        const result = await fetchJSON(`${basePath}/api/guess`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token: currentToken, answer: guessId }),
        });

        const buttons = Array.from(optionsEl.querySelectorAll("button.option"));
        buttons.forEach((btn) => {
            const id = String(btn.dataset.id);
            if (id === String(result.answer_id)) {
                btn.classList.add("correct");
            }
            btn.disabled = true;
        });

        if (!result.correct) {
            button.classList.add("wrong");
            const finishedRun = streak;
            streak = 0;
            renderStatus("Ekki alveg. Byrjað upp á nýtt.", false, true);
            renderStreak();
            await maybeSubmitHighScore(finishedRun);
        } else {
            button.classList.add("correct");
            streak += 1;
            renderStatus("Rétt svar! Vel gert.", true, false);
            renderStreak();
        }
        const correctLabel = (currentOptions.find((opt) => String(opt.id) === String(result.answer_id)) || {}).label;
        attempts.push({
            correct: !!result.correct,
            question_type: currentQuestionType,
            label: correctLabel || button.textContent || "Óþekkt",
        });
        renderAttempts();
    } catch (err) {
        renderStatus(err.message || "Villa kom upp við að senda ágiskun.", false, true);
    } finally {
        nextButton.disabled = false;
    }
}

function setActiveGame(game) {
    currentGame = game;
    gameLinks.forEach((link) => {
        const isActive = link.dataset.game === game;
        link.classList.toggle("active", isActive);
    });
    updateGameCopy(currentGame);
    streak = 0;
    renderStreak();
    fetchHighScores();
    loadQuestion();
}

function onDifficultyChange(value) {
    currentDifficulty = Number(value || 4);
    if (difficultyValueEl) difficultyValueEl.textContent = String(currentDifficulty);
    streak = 0;
    renderStreak();
    fetchHighScores();
    loadQuestion();
}

updateGameCopy(currentGame);
if (gameLinks.length) {
    gameLinks.forEach((link) => {
        link.addEventListener("click", (event) => {
            event.preventDefault();
            const game = link.dataset.game || "who-is";
            setActiveGame(game);
        });
    });
}
if (difficultySlider) {
    difficultySlider.addEventListener("input", (event) => {
        onDifficultyChange(event.target.value);
    });
}
if (clearAttemptsBtn) {
    clearAttemptsBtn.addEventListener("click", () => {
        attempts = [];
        renderAttempts();
    });
}
nextButton.addEventListener("click", loadQuestion);
renderStreak();
renderTimer();
fetchHighScores();
renderAttempts();
loadQuestion();
