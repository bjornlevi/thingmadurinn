import os
import random
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import List, Sequence

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


def guess_gender(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    if normalized.endswith("dottir"):
        return "female"
    if normalized.endswith("son"):
        return "male"
    return ""


def ensure_high_scores_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS high_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            initials TEXT NOT NULL,
            score INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def prune_high_scores(conn: sqlite3.Connection, limit: int = 10) -> None:
    conn.execute(
        """
        DELETE FROM high_scores
        WHERE id NOT IN (
            SELECT id FROM high_scores
            ORDER BY score DESC, created_at ASC
            LIMIT ?
        )
        """,
        (limit,),
    )
    conn.commit()


def get_high_scores(conn: sqlite3.Connection, limit: int = 10) -> Sequence[sqlite3.Row]:
    ensure_high_scores_table(conn)
    rows = conn.execute(
        """
        SELECT initials, score, created_at
        FROM high_scores
        ORDER BY score DESC, created_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return rows


def add_high_score(conn: sqlite3.Connection, initials: str, score: int) -> None:
    ensure_high_scores_table(conn)
    conn.execute(
        "INSERT INTO high_scores (initials, score) VALUES (?, ?)",
        (initials, score),
    )
    conn.commit()
    prune_high_scores(conn)


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


@app.route("/")
def index():
    return render_template("index.html", asset_version=get_asset_version())


@app.route("/api/question")
def question():
    try:
        conn = get_connection()
    except FileNotFoundError as exc:
        abort(503, description=str(exc))

    try:
        correct = fetch_random_member(conn)
        gender = guess_gender(correct["name"])
        distractors = fetch_options(conn, correct["id"], limit=3, gender=gender)
        if len(distractors) < 3:
            # If too few same-gender options, fall back to mixed list.
            extra = fetch_options(conn, correct["id"], limit=3, gender="")
            distractors = extra
    except sqlite3.DatabaseError:
        abort(500, description="Database error.")
    finally:
        conn.close()

    options = [{"id": correct["id"], "name": correct["name"]}]
    options.extend({"id": row["id"], "name": row["name"]} for row in distractors)
    random.shuffle(options)

    token = serializer.dumps({"answer_id": correct["id"]})

    return jsonify(
        {
            "token": token,
            "image_url": correct["image_url"],
            "birthdate": correct["birthdate"],
            "options": options,
        }
    )


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

    correct_id = int(payload.get("answer_id"))
    is_correct = str(guess_id) == str(correct_id)

    return jsonify({"correct": is_correct, "answer_id": correct_id})


@app.route("/api/high-scores", methods=["GET", "POST"])
def high_scores():
    try:
        conn = get_connection()
    except FileNotFoundError as exc:
        abort(503, description=str(exc))

    try:
        if request.method == "GET":
            rows = get_high_scores(conn)
            scores = [{"initials": row["initials"], "score": row["score"]} for row in rows]
            return jsonify({"high_scores": scores})

        payload = request.get_json(force=True, silent=True)
        if not payload or "initials" not in payload or "score" not in payload:
            abort(400, description="Missing high score payload.")

        try:
            score_val = int(payload.get("score", 0))
        except (TypeError, ValueError):
            abort(400, description="Invalid score value.")

        initials_raw = str(payload.get("initials", "")).strip()
        initials = "".join(list(initials_raw)[:3]) or "---"

        if score_val <= 0:
            abort(400, description="Score must be positive.")

        add_high_score(conn, initials, score_val)
        rows = get_high_scores(conn)
        scores = [{"initials": row["initials"], "score": row["score"]} for row in rows]
        return jsonify({"high_scores": scores})
    except sqlite3.DatabaseError:
        abort(500, description="Database error.")
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
