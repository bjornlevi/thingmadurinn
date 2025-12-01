import os
import random
import sqlite3
from pathlib import Path
from typing import List

from flask import Flask, abort, jsonify, render_template, request
from itsdangerous import BadSignature, URLSafeSerializer


BASE_DIR = Path(__file__).parent
DEFAULT_DB = BASE_DIR / "data" / "thingmenn.db"


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


app = Flask(__name__, template_folder="templates", static_folder="static")
serializer = URLSafeSerializer(get_secret(), salt="thingmadurinn")
app.config["SECRET_KEY"] = get_secret()


def fetch_random_member(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, name, birthdate, image_url FROM members WHERE image_url IS NOT NULL ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    if not row:
        abort(503, description="No member data available. Run load_data.py to populate the database.")
    return row


def guess_gender(name: str) -> str:
    lower = name.lower()
    if lower.endswith("dóttir"):
        return "female"
    if lower.endswith("son"):
        return "male"
    return ""


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
    return render_template("index.html")


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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
