const photo = document.getElementById("member-photo");
const optionsEl = document.getElementById("options");
const statusEl = document.getElementById("status");
const nextButton = document.getElementById("next-round");
const streakEl = document.getElementById("streak");
const basePath = document.body.dataset.base || "";

let currentToken = null;
let locked = false;
let streak = 0;

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

function resetState() {
    locked = false;
    currentToken = null;
    renderStatus("Veldu nafn til að byrja.");
    nextButton.disabled = true;
    optionsEl.innerHTML = "";
    photo.src = "";
    photo.alt = "";
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
    } catch (err) {
        renderStatus(err.message || "Gat ekki sótt gögn.", false, true);
    }
}

async function handleGuess(button, guessId) {
    if (locked || !currentToken) return;
    locked = true;

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
loadQuestion();
