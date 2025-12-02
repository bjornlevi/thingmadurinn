const photo = document.getElementById("member-photo");
const optionsEl = document.getElementById("options");
const statusEl = document.getElementById("status");
const nextButton = document.getElementById("next-round");
const streakEl = document.getElementById("streak");
const timerEl = document.getElementById("timer");
const highScoreEl = document.getElementById("high-score");
const basePath = document.body.dataset.base || "";

let currentToken = null;
let locked = false;
let streak = 0;
let countdownId = null;
let timeLeft = 30;
const HIGH_SCORE_KEY = "thingmadurinn_high_score";
let highScore = loadHighScore();

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
    timerEl.textContent = `Tími: ${timeLeft}s`;
}

function renderHighScore() {
    highScoreEl.textContent = `Metskor: ${highScore.score} — ${highScore.name}`;
}

function clearTimer() {
    if (countdownId) {
        clearInterval(countdownId);
        countdownId = null;
    }
}

function startTimer() {
    clearTimer();
    timeLeft = 30;
    renderTimer();
    countdownId = setInterval(() => {
        timeLeft -= 1;
        if (timeLeft <= 0) {
            handleTimeout();
        } else {
            renderTimer();
        }
    }, 1000);
}

function handleTimeout() {
    clearTimer();
    if (locked) return;
    locked = true;
    timeLeft = 0;
    streak = 0;
    renderTimer();
    renderStatus("Tíminn rann út. Röðin endurstillt.", false, true);
    renderStreak();
    disableOptions();
    nextButton.disabled = false;
}

function disableOptions() {
    const buttons = Array.from(optionsEl.querySelectorAll("button.option"));
    buttons.forEach((btn) => {
        btn.disabled = true;
    });
}

function loadHighScore() {
    const stored = localStorage.getItem(HIGH_SCORE_KEY);
    if (!stored) {
        return { score: 0, name: "---" };
    }
    try {
        const parsed = JSON.parse(stored);
        return {
            score: Number(parsed.score) || 0,
            name: typeof parsed.name === "string" && parsed.name.trim() ? parsed.name : "---",
        };
    } catch (e) {
        return { score: 0, name: "---" };
    }
}

function saveHighScore() {
    localStorage.setItem(HIGH_SCORE_KEY, JSON.stringify(highScore));
}

function requestInitials() {
    const input = prompt("Nýr metárangur! Settu inn þrjá stafi (má vera UTF-8):", highScore.name);
    if (input === null) {
        return highScore.name;
    }
    const cleaned = Array.from(input.trim()).slice(0, 3).join("");
    return cleaned || "---";
}

function maybeUpdateHighScore() {
    if (streak > highScore.score) {
        const initials = requestInitials();
        highScore = { score: streak, name: initials };
        saveHighScore();
        renderHighScore();
    }
}

function resetState() {
    locked = false;
    currentToken = null;
    clearTimer();
    timeLeft = 30;
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
            streak = 0;
            renderStatus("Ekki alveg. Reyndu næst!", false, true);
        } else {
            button.classList.add("correct");
            streak += 1;
            renderStatus("Rétt svar! Vel gert.", true, false);
            maybeUpdateHighScore();
        }
        renderStreak();
    } catch (err) {
        renderStatus(err.message || "Villa kom upp við að senda ágiskun.", false, true);
    } finally {
        nextButton.disabled = false;
    }
}

nextButton.addEventListener("click", loadQuestion);
renderStreak();
renderTimer();
renderHighScore();
loadQuestion();
