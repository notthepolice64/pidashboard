from flask import Flask, render_template, jsonify, request, redirect, url_for, send_file
import requests
import json
import os
import uuid
from datetime import datetime, date
from pathlib import Path

app = Flask(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
LATITUDE          = os.environ.get("LATITUDE",  "41.6")
LONGITUDE         = os.environ.get("LONGITUDE", "-89.5")
REMINDERS_FILE    = os.path.join(os.path.dirname(__file__), "reminders.json")
PICTURES_DIR      = os.path.expanduser(os.environ.get("PICTURES_DIR", "~/Pictures"))
IMAGE_EXTS        = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

STOCKS_FILE = os.path.join(os.path.dirname(__file__), "stocks.json")

DEFAULT_STOCKS = [
    {"symbol": "^DJI",    "label": "DOW"},
    {"symbol": "^GSPC",   "label": "S&P"},
    {"symbol": "^IXIC",   "label": "NSDQ"},
    {"symbol": "CAT",     "label": "CAT"},
    {"symbol": "BTC-USD", "label": "BTC"},
    {"symbol": "AAPL",    "label": "AAPL"},
    {"symbol": "GOOGL",   "label": "GOOG"},
    {"symbol": "META",    "label": "META"},
    {"symbol": "MSFT",    "label": "MSFT"},
    {"symbol": "NVDA",    "label": "NVDA"},
    {"symbol": "AMD",     "label": "AMD"},
]
# ─────────────────────────────────────────────────────────────────────────────

def load_stocks():
    if not os.path.exists(STOCKS_FILE):
        # First run — seed the file with defaults so it persists
        save_stocks(DEFAULT_STOCKS)
        return DEFAULT_STOCKS
    with open(STOCKS_FILE, "r") as f:
        try:
            data = json.load(f)
            # Fall back to defaults if file is empty list
            return data if data else DEFAULT_STOCKS
        except Exception:
            return DEFAULT_STOCKS

def save_stocks(items):
    with open(STOCKS_FILE, "w") as f:
        json.dump(items, f, indent=2)

def load_reminders():
    if not os.path.exists(REMINDERS_FILE):
        # Create the file so permissions can be set
        save_reminders([])
        return []
    with open(REMINDERS_FILE, "r") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_reminders(items):
    with open(REMINDERS_FILE, "w") as f:
        json.dump(items, f, indent=2)

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/admin")
def admin():
    reminders = load_reminders()
    today_str = date.today().isoformat()
    stocks = load_stocks()
    return render_template("admin.html", reminders=reminders, now=today_str, stocks=stocks)

@app.route("/admin/add", methods=["POST"])
def add_reminder():
    title = request.form.get("title", "").strip()
    due   = request.form.get("due", "").strip()
    if title:
        reminders = load_reminders()
        reminders.append({"id": str(uuid.uuid4()), "title": title, "due": due or None, "done": False})
        save_reminders(reminders)
    return redirect(url_for("admin"))

@app.route("/admin/done/<rid>", methods=["POST"])
def done_reminder(rid):
    reminders = load_reminders()
    for r in reminders:
        if r["id"] == rid:
            r["done"] = True
            break
    save_reminders(reminders)
    return redirect(url_for("admin"))

@app.route("/admin/delete/<rid>", methods=["POST"])
def delete_reminder(rid):
    reminders = load_reminders()
    reminders = [r for r in reminders if r["id"] != rid]
    save_reminders(reminders)
    return redirect(url_for("admin"))

@app.route("/admin/edit/<rid>", methods=["POST"])
def edit_reminder(rid):
    title = request.form.get("title", "").strip()
    due   = request.form.get("due", "").strip()
    reminders = load_reminders()
    for r in reminders:
        if r["id"] == rid:
            if title:
                r["title"] = title
            r["due"] = due or None
            break
    save_reminders(reminders)
    return redirect(url_for("admin"))

@app.route("/api/reminders")
def api_reminders():
    all_items = load_reminders()
    active = [r for r in all_items if not r.get("done")]
    today = date.today().isoformat()
    for r in active:
        r["overdue"] = bool(r.get("due") and r["due"] < today)
    active.sort(key=lambda r: (r.get("due") or "9999-99-99"))
    return jsonify({"items": active})

@app.route("/api/weather")
def api_weather():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        "&current=temperature_2m,relative_humidity_2m,weather_code,apparent_temperature"
        ",wind_speed_10m,wind_direction_10m,precipitation_probability,uv_index"
        "&hourly=temperature_2m,weather_code,precipitation_probability"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min"
        ",sunrise,sunset,uv_index_max,precipitation_probability_max"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph"
        "&precipitation_unit=inch&timezone=auto&forecast_days=7"
    )
    try:
        r = requests.get(url, timeout=5)
        data = r.json()
        current = data["current"]
        daily   = data.get("daily", {})
        hourly  = data.get("hourly", {})
        codes   = daily.get("weather_code", [])
        highs   = daily.get("temperature_2m_max", [])
        lows    = daily.get("temperature_2m_min", [])
        precip_prob_daily = daily.get("precipitation_probability_max", [])
        forecast = [
            {
                "code": codes[i],
                "hi":   round(highs[i]),
                "lo":   round(lows[i]),
                "precip": precip_prob_daily[i] if i < len(precip_prob_daily) else None,
            }
            for i in range(len(codes))
        ]
        # 2-hour intervals for next 12 hours (7 slots: now + 6 future)
        h_times  = hourly.get("time", [])
        h_temps  = hourly.get("temperature_2m", [])
        h_codes  = hourly.get("weather_code", [])
        h_precip = hourly.get("precipitation_probability", [])
        now_str  = current.get("time", "")[:13]
        hourly_out = []
        start_i = None
        for i, t in enumerate(h_times):
            if t[:13] == now_str:
                start_i = i
                break
        if start_i is None:
            start_i = 0
        slot = 0
        for i in range(start_i, min(start_i + 15, len(h_times))):
            if (i - start_i) % 2 == 0:
                hourly_out.append({
                    "time":   h_times[i][11:16],
                    "temp":   round(h_temps[i]) if i < len(h_temps) else None,
                    "code":   h_codes[i]  if i < len(h_codes)  else 0,
                    "precip": h_precip[i] if i < len(h_precip) else 0,
                    "now":    i == start_i,
                })
                slot += 1
                if slot >= 7:
                    break
        def fmt_time(iso):
            try: return iso[11:16]
            except Exception: return "--:--"
        sunrises = daily.get("sunrise", [])
        sunsets  = daily.get("sunset",  [])
        return jsonify({
            "temp":        round(current["temperature_2m"]),
            "feels":       round(current["apparent_temperature"]),
            "humidity":    current["relative_humidity_2m"],
            "condition":   weather_description(current["weather_code"]),
            "code":        current["weather_code"],
            "wind":        round(current.get("wind_speed_10m", 0)),
            "wind_dir":    wind_direction(current.get("wind_direction_10m", 0)),
            "precip_prob": current.get("precipitation_probability", 0),
            "uv_index":    current.get("uv_index", 0),
            "sunrise":     fmt_time(sunrises[0]) if sunrises else "--:--",
            "sunset":      fmt_time(sunsets[0])  if sunsets  else "--:--",
            "forecast":    forecast,
            "hourly":      hourly_out,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stocks")
def api_stocks():
    try:
        import yfinance as yf
        stock_list = load_stocks()
        results = []
        tickers = yf.Tickers(" ".join(s["symbol"] for s in stock_list))
        for s in stock_list:
            try:
                info = tickers.tickers[s["symbol"]].fast_info
                price = info.last_price
                prev  = info.previous_close
                chg_pct = ((price - prev) / prev) * 100 if prev else 0
                results.append({"sym": s["label"], "price": round(price, 2), "chg": round(chg_pct, 2)})
            except Exception:
                results.append({"sym": s["label"], "price": None, "chg": 0})
        return jsonify({"stocks": results})
    except ImportError:
        return jsonify({"error": "yfinance not installed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/stocks/add", methods=["POST"])
def add_stock():
    symbol = request.form.get("symbol", "").strip().upper()
    label  = request.form.get("label",  "").strip().upper()
    if symbol and label:
        stocks = load_stocks()
        if not any(s["symbol"] == symbol for s in stocks):
            stocks.append({"symbol": symbol, "label": label})
            save_stocks(stocks)
    return redirect(url_for("admin"))

def decode_sym(s):
    return s.replace("__hat__", "^").replace("__dash__", "-")

@app.route("/admin/stocks/remove/<symbol>", methods=["POST"])
def remove_stock(symbol):
    symbol = decode_sym(symbol)
    stocks = load_stocks()
    stocks = [s for s in stocks if s["symbol"] != symbol]
    save_stocks(stocks)
    return redirect(url_for("admin"))

@app.route("/admin/stocks/move/<symbol>/<direction>", methods=["POST"])
def move_stock(symbol, direction):
    symbol = decode_sym(symbol)
    stocks = load_stocks()
    idx = next((i for i, s in enumerate(stocks) if s["symbol"] == symbol), None)
    if idx is not None:
        if direction == "up" and idx > 0:
            stocks[idx-1], stocks[idx] = stocks[idx], stocks[idx-1]
        elif direction == "down" and idx < len(stocks)-1:
            stocks[idx+1], stocks[idx] = stocks[idx], stocks[idx+1]
        save_stocks(stocks)
    return redirect(url_for("admin"))

@app.route("/api/photos")
def api_photos():
    pics_path = Path(PICTURES_DIR)
    if not pics_path.exists():
        return jsonify({"photos": []})
    files = sorted([
        f for f in pics_path.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    ], key=lambda f: f.stat().st_mtime, reverse=True)
    return jsonify({"photos": [f"/photos/{f.name}" for f in files]})

@app.route("/photos/<filename>")
def serve_photo(filename):
    pics_path = Path(PICTURES_DIR)
    file_path = pics_path / filename
    if not file_path.resolve().parent == pics_path.resolve():
        return "Forbidden", 403
    if not file_path.exists():
        return "Not found", 404
    return send_file(str(file_path))

@app.route("/api/flashcard")
def api_flashcard():
    import random
    from vocab import DECK
    card = random.choice(DECK)
    return jsonify(card)

def wind_direction(degrees):
    dirs = ['N','NE','E','SE','S','SW','W','NW']
    return dirs[round(degrees / 45) % 8]

def weather_description(code):
    codes = {
        0:"Clear Sky",1:"Mainly Clear",2:"Partly Cloudy",3:"Overcast",
        45:"Foggy",48:"Icy Fog",51:"Light Drizzle",53:"Drizzle",55:"Heavy Drizzle",
        61:"Light Rain",63:"Rain",65:"Heavy Rain",71:"Light Snow",73:"Snow",75:"Heavy Snow",
        80:"Rain Showers",81:"Showers",82:"Heavy Showers",
        95:"Thunderstorm",96:"Thunderstorm + Hail",99:"Heavy Thunderstorm",
    }
    return codes.get(code, "Unknown")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
