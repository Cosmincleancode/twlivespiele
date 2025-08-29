from flask import Flask, send_from_directory, jsonify, request
import subprocess, os, time, sys, json
import scraper.scraper as scraper  # Import the scraper
from datetime import date

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
        try:
            # Validate the date format
            date.fromisoformat(query_date)
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

        start = time.time()
        # Call the scraper function directly
        try:
            result = scraper.main(query_date)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        elapsed = round(time.time() - start, 2)

        if "error" in result:
            # Handle errors from the scraper
            data = {
                "date": query_date,
                "generated_at": result.get("generated_at"),
                "error": result.get("error"),
                "games": []
            }
            data["_meta"] = {
                "elapsed": elapsed,
                "status": "error",
                "stderr": result.get("error")  # Or any relevant error info
            }
            return jsonify(data), 500
        else:
            # Successful scrape
            data = result
            data["_meta"] = {
                "elapsed": elapsed,
                "status": "ok",
                "stderr": ""
            }
            return jsonify(data), 200
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

    if query_date:
        try:
            # Validate the date format
            date_object = date.fromisoformat(query_date)
            log(f"Date {date_object} is valid")
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

        start = time.time()
        # Call the scraper function directly
        try:
            result = scraper.main(query_date)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        elapsed = round(time.time() - start, 2)

        if "error" in result:
            # Handle errors from the scraper
            status = "error"
            stdout = ""
            stderr = result.get("error")  # Or any relevant error info
            return jsonify({
                "status": status,
                "elapsed": elapsed,
                "stdout": stdout,
                "stderr": stderr,
            }), 500
        else:
            # Successful scrape
            status = "ok"
            stdout = ""
            stderr = ""
            return jsonify({
                "status": status,
                "elapsed": elapsed,
                "stdout": stdout,
                "stderr": stderr,
            }), 200
    else:
        return jsonify({"error": "Date parameter is missing."}), 400
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
