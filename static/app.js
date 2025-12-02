const photo = document.getElementById("member-photo");
const optionsEl = document.getElementById("options");
const statusEl = document.getElementById("status");
const nextButton = document.getElementById("next-round");
const streakEl = document.getElementById("streak");
const timerEl = document.getElementById("timer");
const timerFill = document.getElementById("timer-fill");
const highScoreEl = document.getElementById("high-score");
const leaderboardList = document.getElementById("leaderboard-list");
const basePath = document.body.dataset.base || "";

const TIMER_LIMIT = 30;

let currentToken = null;
let locked = false;
let streak = 0;
let countdownId = null;
let timeLeft = TIMER_LIMIT;
let highScores = [];

async function fetchJSON(url, options) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`Villa: ${resp.status} ${text}`);
    }
    return resp.json();
}

function renderStatus(text, positive = false, negative = false) {
    statusEl.textContent = text;
    statusEl.classList.toggle("positive", positive);
    statusEl.classList.toggle("negative", negative);
}

function renderStreak() {
    streakEl.textContent = `Röð rétt svarað: ${streak}`;
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
    highScoreEl.textContent = best ? `Metskor: ${best.score} — ${best.initials}` : "Metskor: 0 — ---";
}

function renderLeaderboard() {
    if (!leaderboardList) return;
    leaderboardList.innerHTML = "";
    if (!highScores.length) {
        const li = document.createElement("li");
        li.textContent = "Engin met enn. Gerðu tilraun!";
        leaderboardList.appendChild(li);
        return;
    }

    highScores.forEach((entry) => {
        const li = document.createElement("li");
        const nameSpan = document.createElement("span");
        nameSpan.textContent = entry.initials;
        const scoreSpan = document.createElement("span");
        scoreSpan.textContent = entry.score;
        li.appendChild(nameSpan);
        li.appendChild(scoreSpan);
        leaderboardList.appendChild(li);
    });
}

async function fetchHighScores() {
    try {
        const data = await fetchJSON(`${basePath}/api/high-scores`);
        highScores = data.high_scores || [];
    } catch (err) {
        renderStatus(err.message || "Gat ekki sótt metskor.", false, true);
    } finally {
        renderHighScore();
        renderLeaderboard();
    }
}

async function submitHighScore(score, initials) {
    const data = await fetchJSON(`${basePath}/api/high-scores`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ score, initials }),
    });
    highScores = data.high_scores || highScores;
    renderHighScore();
    renderLeaderboard();
}

function requestInitials(defaultValue = "---") {
    const input = prompt("Nýr metárangur! Settu inn þrjá stafi (má vera UTF-8):", defaultValue);
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
        renderStatus("Metskor vistaður!", true, false);
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
    renderStatus("Tíminn rann út. Röðin endurstillt.", false, true);
    disableOptions();
    nextButton.disabled = false;
    await maybeSubmitHighScore(finishedRun);
}

function resetState() {
    locked = false;
    currentToken = null;
    clearTimer();
    timeLeft = TIMER_LIMIT;
    renderStatus("Veldu nafn til að byrja.");
    nextButton.disabled = true;
    optionsEl.innerHTML = "";
    photo.src = "";
    photo.alt = "";
    renderTimer();
}

async function loadQuestion() {
    resetState();
    try {
        const data = await fetchJSON(`${basePath}/api/question`);
        currentToken = data.token;
        photo.src = data.image_url;
        photo.alt = "Mynd af þingmanni. Veldu nafnið.";

        data.options.forEach((option) => {
            const btn = document.createElement("button");
            btn.className = "option";
            btn.type = "button";
            btn.textContent = option.name;
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
            const id = Number(btn.dataset.id);
            if (id === result.answer_id) {
                btn.classList.add("correct");
            }
            btn.disabled = true;
        });

        if (!result.correct) {
            button.classList.add("wrong");
            const finishedRun = streak;
            streak = 0;
            renderStatus("Ekki alveg. Röðin endurstillt.", false, true);
            renderStreak();
            await maybeSubmitHighScore(finishedRun);
        } else {
            button.classList.add("correct");
            streak += 1;
            renderStatus("Rétt svar! Vel gert.", true, false);
            renderStreak();
        }
    } catch (err) {
        renderStatus(err.message || "Villa kom upp við að senda ágiskun.", false, true);
    } finally {
        nextButton.disabled = false;
    }
}

nextButton.addEventListener("click", loadQuestion);
renderStreak();
renderTimer();
fetchHighScores();
loadQuestion();
