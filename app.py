from flask import Flask, send_from_directory, jsonify, request
import subprocess, os, time, sys, json

app = Flask(__name__, static_folder="web", static_url_path="")

DATA_DIR = os.path.join("web", "data")
MERGED = os.path.join(DATA_DIR, "merged.json")
RELOAD_LOG = os.path.join(DATA_DIR, "reload.log")

def ensure_data_files():
    """Creează web/data + fișierele implicite dacă lipsesc."""
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

@app.route("/")
def index():
    return send_from_directory("web", "index.html")

@app.route("/api/games", methods=["GET"])
def api_games():
    # dacă există ?date=YYYY-MM-DD, rulăm scraperul pentru acea dată
    query_date = request.args.get("date")
    if query_date:
        start = time.time()
        proc = subprocess.run(
            [sys.executable, os.path.join("scraper", "scraper.py"), query_date],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, shell=False, timeout=180
        )
        with open(MERGED, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_meta"] = {
            "elapsed": round(time.time()-start, 2),
            "status": "ok" if proc.returncode == 0 else "error",
            "stderr": (proc.stderr or "")[-1000:]
        }
        return jsonify(data), (200 if proc.returncode == 0 else 500)
    # altfel, doar servim fișierul curent
    return send_from_directory(DATA_DIR, "merged.json")

@app.route("/api/log")
def log_file():
    with open(RELOAD_LOG, "r", encoding="utf-8") as f:
        return jsonify({"log": f.read()[-10000:]})

@app.route("/api/reload", methods=["POST"])
def reload_data():
    payload = request.get_json(silent=True) or {}
    query_date = payload.get("date")
    args = [sys.executable, os.path.join("scraper", "scraper.py")]
    if query_date:
        args.append(query_date)
    start = time.time()
    proc = subprocess.run(
        args,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        capture_output=True, text=True, shell=False, timeout=180
    )
    return jsonify({
        "status": "ok" if proc.returncode == 0 else "error",
        "elapsed": round(time.time()-start, 2),
        "stdout": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-2000:],
    }), (200 if proc.returncode == 0 else 500)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
