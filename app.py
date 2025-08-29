# app.py
from flask import Flask, send_from_directory, jsonify, request
import subprocess, os, time, sys, json
import scraper.scraper as scraper  # your scraper
from datetime import datetime, date
import pytz

app = Flask(__name__, static_folder="web", static_url_path="")

# ---- Paths ----
DATA_DIR   = os.path.join("web", "data")
MERGED     = os.path.join(DATA_DIR, "merged.json")
RELOAD_LOG = os.path.join(DATA_DIR, "reload.log")

# ---- Timezone ----
VIENNA = pytz.timezone("Europe/Vienna")

def now_vienna_str():
    return datetime.now(VIENNA).strftime("%Y-%m-%d %H:%M:%S")

def log(msg: str):
    """Append to reload.log and stdout with Vienna timestamp."""
    line = f"[{now_vienna_str()}] {msg}\n"
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(RELOAD_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # don't crash logging
        pass
    print(line, end="", file=sys.stdout, flush=True)

def ensure_data_files():
    """Create web/data + default files if missing."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(RELOAD_LOG):
        open(RELOAD_LOG, "w", encoding="utf-8").write("")
    if not os.path.exists(MERGED):
        seed = {
            "date": "",
            "generated_at": "",
            "counters": {"LiveOnSat": 0, "SportEventz": 0, "Total": 0},
            "timezone": "Europe/Vienna (GMT+2)",
            "games": []
        }
        with open(MERGED, "w", encoding="utf-8") as f:
            json.dump(seed, f, ensure_ascii=False, indent=2)

@app.before_request
def _prepare():
    ensure_data_files()

@app.after_request
def _no_store(resp):
    # Avoid stale cache in browsers/proxies
    resp.headers["Cache-Control"] = "no-store"
    return resp

# ---------- Static ----------
@app.route("/")
def index():
    return send_from_directory("web", "index.html")

# ---------- Logs ----------
@app.route("/api/log")
def log_file():
    with open(RELOAD_LOG, "r", encoding="utf-8") as f:
        return jsonify({"log": f.read()[-10000:]})

# ---------- Games ----------
@app.route("/api/games", methods=["GET"])
def api_games():
    """
    If ?date=YYYY-MM-DD is provided -> run scraper for that date and return its JSON.
    Else -> return the current merged.json from disk.
    """
    query_date = request.args.get("date")

    if query_date:
        # Validate the date
        try:
            date.fromisoformat(query_date)
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

        start = time.time()
        try:
            log(f"Scrape requested via /api/games for {query_date}")
            result = scraper.main(query_date)  # your scraper should accept the date
        except Exception as e:
            log(f"Scraper exception: {e}")
            return jsonify({"error": str(e)}), 500

        elapsed = round(time.time() - start, 2)

        # Expecting dict from scraper; if it signals error, return 500
        if isinstance(result, dict) and "error" in result:
            data = {
                "date": query_date,
                "generated_at": result.get("generated_at"),
                "error": result.get("error"),
                "games": [],
                "_meta": {"elapsed": elapsed, "status": "error", "stderr": result.get("error", "")}
            }
            return jsonify(data), 500

        # Success path
        data = result if isinstance(result, dict) else {"date": query_date, "games": result}
        data["_meta"] = {"elapsed": elapsed, "status": "ok", "stderr": ""}
        return jsonify(data), 200

    # no ?date -> serve latest merged.json
    return send_from_directory(DATA_DIR, "merged.json")

# ---------- Reload (GET or POST) ----------
@app.route("/api/reload", methods=["GET", "POST"])
def reload_data():
    """
    Accepts:
      - GET /api/reload?date=YYYY-MM-DD
      - POST /api/reload  with JSON {"date": "YYYY-MM-DD"}
    If date missing -> fallback to 'today' in Vienna.
    """
    # prefer query param, else JSON body
    query_date = request.args.get("date")
    if not query_date:
        payload = request.get_json(silent=True) or {}
        query_date = payload.get("date")

    if not query_date:
        query_date = datetime.now(VIENNA).strftime("%Y-%m-%d")

    # Validate
    try:
        date_obj = date.fromisoformat(query_date)
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

    log(f"Reload requested for {date_obj}")

    start = time.time()
    try:
        result = scraper.main(query_date)
    except Exception as e:
        log(f"Scraper exception in /api/reload: {e}")
        return jsonify({"status": "error", "elapsed": round(time.time() - start, 2), "stderr": str(e)}), 500

    elapsed = round(time.time() - start, 2)

    # If scraper returns an error field, propagate 500
    if isinstance(result, dict) and "error" in result:
        stderr = result.get("error", "")
        log(f"Reload error for {query_date}: {stderr}")
        return jsonify({"status": "error", "elapsed": elapsed, "stderr": stderr}), 500

    log(f"Reload OK for {query_date} in {elapsed}s")
    return jsonify({"status": "ok", "elapsed": elapse
