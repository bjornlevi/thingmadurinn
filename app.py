import os
import random
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import List, Sequence, Tuple

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, render_template, request
from itsdangerous import BadSignature, URLSafeSerializer


BASE_DIR = Path(__file__).parent
DEFAULT_DB = BASE_DIR / "data" / "thingmenn.db"

# Load .env if present (helps when systemd EnvironmentFile is not picked up)
load_dotenv(BASE_DIR / ".env", override=False)


def get_database_path() -> Path:
    custom = os.environ.get("THINGMADURINN_DB")
    return Path(custom) if custom else DEFAULT_DB


def get_connection() -> sqlite3.Connection:
    db_path = get_database_path()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}. Run load_data.py first.")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_secret() -> str:
    return os.environ.get("FLASK_SECRET_KEY", "change-me")


app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)
serializer = URLSafeSerializer(get_secret(), salt="thingmadurinn")
app.config["SECRET_KEY"] = get_secret()


def get_asset_version() -> str:
    """Use mtime of static files to bust caches (helps when behind nginx)."""
    candidates = [BASE_DIR / "static" / "app.js", BASE_DIR / "static" / "style.css"]
    try:
        return str(int(max(path.stat().st_mtime for path in candidates if path.exists())))
    except ValueError:
        return str(int(time.time()))


def fetch_random_member(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, name, birthdate, image_url FROM members WHERE image_url IS NOT NULL ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    if not row:
        abort(503, description="No member data available. Run load_data.py to populate the database.")
    return row


def fetch_random_member_with_party(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT id, name, birthdate, image_url
        FROM members
        WHERE image_url IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM memberships WHERE member_id = members.id AND flokkur IS NOT NULL AND flokkur != ''
          )
        ORDER BY RANDOM() LIMIT 1
        """
    ).fetchone()
    if not row:
        abort(503, description="Engin þingsetu-gögn fundust. Keyrðu load_data.py aftur.")
    return row


def guess_gender(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    if normalized.endswith("dottir"):
        return "female"
    if normalized.endswith("son"):
        return "male"
    return ""


def clamp_difficulty(raw: str | int, default: int = 4) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(2, min(6, value))


def pick_party_key(flokkur_id: int | None, flokkur_name: str) -> str:
    name_part = (flokkur_name or "").strip()
    return f"{flokkur_id}:{name_part}" if flokkur_id is not None else f"none:{name_part}"


def fetch_member_parties(conn: sqlite3.Connection, member_id: int) -> List[Tuple[int | None, str]]:
    rows = conn.execute(
        """
        SELECT DISTINCT flokkur_id, flokkur
        FROM memberships
        WHERE member_id = ? AND (flokkur IS NOT NULL AND flokkur != '')
        """,
        (member_id,),
    ).fetchall()
    return [(row["flokkur_id"], row["flokkur"]) for row in rows]


def fetch_random_party_choices(
    conn: sqlite3.Connection, exclude_keys: set[str], limit: int
) -> List[Tuple[int | None, str]]:
    rows = conn.execute(
        """
        SELECT DISTINCT flokkur_id, flokkur
        FROM memberships
        WHERE flokkur IS NOT NULL AND flokkur != ''
        ORDER BY RANDOM()
        LIMIT ?
        """,
        (limit * 3,),
    ).fetchall()

    choices: List[Tuple[int | None, str]] = []
    for row in rows:
        key = pick_party_key(row["flokkur_id"], row["flokkur"])
        if key in exclude_keys:
            continue
        choices.append((row["flokkur_id"], row["flokkur"]))
        if len(choices) >= limit:
            break
    return choices


def ensure_high_scores_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS high_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            initials TEXT NOT NULL,
            score INTEGER NOT NULL,
            game_mode TEXT NOT NULL DEFAULT 'who-is',
            difficulty INTEGER NOT NULL DEFAULT 4,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Add missing columns for existing deployments.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(high_scores)")}
    if "game_mode" not in columns:
        conn.execute("ALTER TABLE high_scores ADD COLUMN game_mode TEXT NOT NULL DEFAULT 'who-is'")
    if "difficulty" not in columns:
        conn.execute("ALTER TABLE high_scores ADD COLUMN difficulty INTEGER NOT NULL DEFAULT 4")
    conn.commit()


def prune_high_scores(conn: sqlite3.Connection, mode: str, difficulty: int, limit: int = 10) -> None:
    # Keep historical rows; selection queries already limit to top N.
    return


def get_high_scores(conn: sqlite3.Connection, mode: str, difficulty: int, limit: int = 10) -> Sequence[sqlite3.Row]:
    ensure_high_scores_table(conn)
    rows = conn.execute(
        """
        SELECT initials, score, created_at
        FROM high_scores
        WHERE game_mode = ? AND difficulty = ?
        ORDER BY score DESC, created_at ASC
        LIMIT ?
        """,
        (mode, difficulty, limit),
    ).fetchall()
    return rows


def add_high_score(conn: sqlite3.Connection, initials: str, score: int, mode: str, difficulty: int) -> None:
    ensure_high_scores_table(conn)
    conn.execute(
        "INSERT INTO high_scores (initials, score, game_mode, difficulty) VALUES (?, ?, ?, ?)",
        (initials, score, mode, difficulty),
    )
    conn.commit()


def fetch_options(conn: sqlite3.Connection, correct_id: int, limit: int = 3, gender: str = "") -> List[sqlite3.Row]:
    params: List = [correct_id]
    sql = "SELECT id, name FROM members WHERE id != ? AND image_url IS NOT NULL"

    if gender == "male":
        sql += " AND lower(name) LIKE '%son'"
    elif gender == "female":
        sql += " AND lower(name) LIKE '%dóttir'"

    sql += " ORDER BY RANDOM() LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return rows


def build_name_question(conn: sqlite3.Connection, difficulty: int) -> dict:
    correct = fetch_random_member(conn)
    gender = guess_gender(correct["name"])
    needed = max(1, difficulty - 1)
    distractors = fetch_options(conn, correct["id"], limit=needed, gender=gender)

    # If too few same-gender options, fall back to mixed list to fill.
    while len(distractors) < needed:
        extra = fetch_options(conn, correct["id"], limit=needed - len(distractors), gender="")
        # Deduplicate by id
        seen_ids = {row["id"] for row in distractors}
        for row in extra:
            if row["id"] in seen_ids or row["id"] == correct["id"]:
                continue
            distractors.append(row)
            seen_ids.add(row["id"])
            if len(distractors) >= needed:
                break

    options = [{"id": correct["id"], "label": correct["name"]}]
    options.extend({"id": row["id"], "label": row["name"]} for row in distractors)
    random.shuffle(options)

    token = serializer.dumps({"answer_key": correct["id"], "question_type": "who-is"})

    return {
        "question_type": "who-is",
        "prompt": "Veldu nafnið sem passar við myndina.",
        "token": token,
        "image_url": correct["image_url"],
        "options": options,
    }


def build_party_question(conn: sqlite3.Connection, difficulty: int) -> dict:
    member = fetch_random_member_with_party(conn)
    parties = fetch_member_parties(conn, member["id"])
    if not parties:
        abort(503, description="Engar þingflokkskrár fundust fyrir valdan þingmann.")

    correct_party = random.choice(parties)
    correct_key = pick_party_key(*correct_party)

    needed_wrong = max(0, difficulty - 1)
    wrong_choices = fetch_random_party_choices(conn, exclude_keys={correct_key}, limit=needed_wrong)

    # If too few options were fetched, pad with remaining parties from the same member.
    if len(wrong_choices) < needed_wrong:
        existing_keys = {correct_key}
        existing_keys.update(pick_party_key(pid, name) for pid, name in wrong_choices)
        for party in parties:
            key = pick_party_key(*party)
            if key in existing_keys:
                continue
            wrong_choices.append(party)
            existing_keys.add(key)
            if len(wrong_choices) >= needed_wrong:
                break

    options = [{"id": correct_key, "label": correct_party[1]}]
    options.extend({"id": pick_party_key(pid, name), "label": name} for pid, name in wrong_choices)
    random.shuffle(options)

    token = serializer.dumps({"answer_key": correct_key, "question_type": "party"})

    return {
        "question_type": "party",
        "prompt": "Í hvaða þingflokki var þingmaðurinn?",
        "token": token,
        "image_url": member["image_url"],
        "options": options,
    }


@app.route("/")
def index():
    return render_template("index.html", asset_version=get_asset_version())


@app.route("/api/question")
def question():
    try:
        conn = get_connection()
    except FileNotFoundError as exc:
        abort(503, description=str(exc))

    game_mode = request.args.get("game", "who-is")
    if game_mode not in {"who-is", "party", "mixed"}:
        game_mode = "who-is"
    difficulty = clamp_difficulty(request.args.get("difficulty", 4))
    actual_mode = game_mode

    try:
        if game_mode == "mixed":
            actual_mode = random.choice(["who-is", "party"])

        if actual_mode == "party":
            question_payload = build_party_question(conn, difficulty)
        else:
            question_payload = build_name_question(conn, difficulty)
    except sqlite3.DatabaseError:
        abort(500, description="Database error.")
    finally:
        conn.close()

    question_payload["game_mode"] = actual_mode
    question_payload["difficulty"] = difficulty
    return jsonify(question_payload)


@app.route("/api/guess", methods=["POST"])
def guess():
    data = request.get_json(force=True, silent=True)
    if not data or "token" not in data or "answer" not in data:
        abort(400, description="Missing guess payload.")

    guess_id = data.get("answer")
    token = data.get("token")

    try:
        payload = serializer.loads(token)
    except BadSignature:
        abort(400, description="Invalid token.")

    answer_key = str(payload.get("answer_key"))
    question_type = payload.get("question_type", "who-is")
    is_correct = str(guess_id) == answer_key

    return jsonify({"correct": is_correct, "answer_id": answer_key, "question_type": question_type})


@app.route("/api/high-scores", methods=["GET", "POST"])
def high_scores():
    try:
        conn = get_connection()
    except FileNotFoundError as exc:
        abort(503, description=str(exc))

    try:
        if request.method == "GET":
            mode = request.args.get("game", "who-is")
            if mode not in {"who-is", "party", "mixed"}:
                mode = "who-is"
            difficulty = clamp_difficulty(request.args.get("difficulty", 4))

            rows = get_high_scores(conn, mode=mode, difficulty=difficulty)
            scores = [{"initials": row["initials"], "score": row["score"]} for row in rows]
            return jsonify({"high_scores": scores})

        payload = request.get_json(force=True, silent=True)
        if not payload or "initials" not in payload or "score" not in payload:
            abort(400, description="Missing high score payload.")

        try:
            score_val = int(payload.get("score", 0))
        except (TypeError, ValueError):
            abort(400, description="Invalid score value.")

        mode = str(payload.get("game", "who-is"))
        if mode not in {"who-is", "party", "mixed"}:
            mode = "who-is"
        difficulty = clamp_difficulty(payload.get("difficulty", 4))

        initials_raw = str(payload.get("initials", "")).strip()
        initials = "".join(list(initials_raw)[:3]) or "---"

        if score_val <= 0:
            abort(400, description="Score must be positive.")

        add_high_score(conn, initials, score_val, mode=mode, difficulty=difficulty)
        rows = get_high_scores(conn, mode=mode, difficulty=difficulty)
        scores = [{"initials": row["initials"], "score": row["score"]} for row in rows]
        return jsonify({"high_scores": scores})
    except sqlite3.DatabaseError:
        abort(500, description="Database error.")
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
