from flask import Flask, render_template, jsonify, request, redirect, url_for, send_file
import requests
import json
import os
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path

app = Flask(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
DATA_DIR          = os.environ.get("DATA_DIR", os.path.dirname(__file__))
os.makedirs(DATA_DIR, exist_ok=True)
REMINDERS_FILE    = os.path.join(DATA_DIR, "reminders.json")
PICTURES_DIR      = os.path.expanduser(os.environ.get("PICTURES_DIR", "~/Pictures"))
IMAGE_EXTS        = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

STOCKS_FILE   = os.path.join(DATA_DIR, "stocks.json")
EVENTS_FILE   = os.path.join(DATA_DIR, "events.json")
SLEEP_FILE    = os.path.join(DATA_DIR, "sleep_schedule.json")
LOCATION_FILE = os.path.join(DATA_DIR, "location.json")

# Default location is intentionally unset — the user configures it via /admin
# the first time they open the dashboard. Env vars (LATITUDE / LONGITUDE /
# CITY / TIMEZONE) override the saved file if present.
DEFAULT_LOCATION = {"city": "", "lat": None, "lon": None, "timezone": "UTC"}

DEFAULT_SLEEP = {"sleep_hour": 23, "sleep_minute": 30, "wake_hour": 6, "wake_minute": 30}

def load_sleep_schedule():
    if not os.path.exists(SLEEP_FILE):
        save_sleep_schedule(DEFAULT_SLEEP)
        return DEFAULT_SLEEP.copy()
    with open(SLEEP_FILE, "r") as f:
        try:
            return json.load(f)
        except Exception:
            return DEFAULT_SLEEP.copy()

def save_sleep_schedule(data):
    with open(SLEEP_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ── Location helpers ─────────────────────────────────────────────────────────
def load_location():
    """Return the current location config.

    Resolution order:
      1. Environment variables (LATITUDE + LONGITUDE required together;
         CITY and TIMEZONE optional). Useful for Docker / one-shot deploys.
      2. location.json on disk (set via the admin UI).
      3. DEFAULT_LOCATION (unset, timezone=UTC) — weather is disabled
         until the user configures a location.
    """
    env_lat = os.environ.get("LATITUDE")
    env_lon = os.environ.get("LONGITUDE")
    if env_lat and env_lon:
        try:
            return {
                "city":     os.environ.get("CITY", "").strip(),
                "lat":      float(env_lat),
                "lon":      float(env_lon),
                "timezone": os.environ.get("TIMEZONE", "UTC").strip() or "UTC",
            }
        except ValueError:
            pass

    if not os.path.exists(LOCATION_FILE):
        save_location(DEFAULT_LOCATION)
        return DEFAULT_LOCATION.copy()
    with open(LOCATION_FILE, "r") as f:
        try:
            data = json.load(f)
            for k, v in DEFAULT_LOCATION.items():
                data.setdefault(k, v)
            return data
        except Exception:
            return DEFAULT_LOCATION.copy()

def save_location(data):
    with open(LOCATION_FILE, "w") as f:
        json.dump(data, f, indent=2)

import calendar as _cal

def _easter(year):
    a=year%19;b=year//100;c=year%100;d=b//4;e=b%4
    f=(b+8)//25;g=(b-f+1)//3;h=(19*a+b-d-g+15)%30
    i=c//4;k=c%4;l=(32+2*e+2*i-h-k)%7
    m=(a+11*h+22*l)//451
    mo=(h+l-7*m+114)//31;dy=((h+l-7*m+114)%31)+1
    return date(year, mo, dy)

def _nth(year, month, weekday, n):
    """nth weekday in month. n>0 from start, n=-1 = last."""
    if n > 0:
        first=date(year,month,1)
        diff=(weekday-first.weekday())%7
        return first+timedelta(days=diff+(n-1)*7)
    else:
        last=date(year,month,_cal.monthrange(year,month)[1])
        diff=(last.weekday()-weekday)%7
        return last-timedelta(days=diff)

def _get_holidays(year):
    """Return list of {id, name, month, day} for a given year, all calculated."""
    e=_easter(year)
    return [
        {"id":"h-newyear",     "name":"New Year's Day",    "month":1,        "day":1},
        {"id":"h-mlk",         "name":"MLK Day",           "month":_nth(year,1,0,3).month,   "day":_nth(year,1,0,3).day},
        {"id":"h-presidents",  "name":"Presidents Day",    "month":_nth(year,2,0,3).month,   "day":_nth(year,2,0,3).day},
        {"id":"h-valentine",   "name":"Valentine's Day",   "month":2,        "day":14},
        {"id":"h-stpatrick",   "name":"St. Patrick's Day", "month":3,        "day":17},
        {"id":"h-easter",      "name":"Easter",            "month":e.month,  "day":e.day},
        {"id":"h-mothers",     "name":"Mother's Day",      "month":_nth(year,5,6,2).month,   "day":_nth(year,5,6,2).day},
        {"id":"h-memorial",    "name":"Memorial Day",      "month":_nth(year,5,0,-1).month,  "day":_nth(year,5,0,-1).day},
        {"id":"h-fathers",     "name":"Father's Day",      "month":_nth(year,6,6,3).month,   "day":_nth(year,6,6,3).day},
        {"id":"h-july4",       "name":"Independence Day",  "month":7,        "day":4},
        {"id":"h-labor",       "name":"Labor Day",         "month":_nth(year,9,0,1).month,   "day":_nth(year,9,0,1).day},
        {"id":"h-columbus",    "name":"Columbus Day",      "month":_nth(year,10,0,2).month,  "day":_nth(year,10,0,2).day},
        {"id":"h-halloween",   "name":"Halloween",         "month":10,       "day":31},
        {"id":"h-veterans",    "name":"Veterans Day",      "month":11,       "day":11},
        {"id":"h-thanksgiving","name":"Thanksgiving",      "month":_nth(year,11,3,4).month,  "day":_nth(year,11,3,4).day},
        {"id":"h-christmas",   "name":"Christmas Day",     "month":12,       "day":25},
        {"id":"h-newyeareve",  "name":"New Year's Eve",    "month":12,       "day":31},
    ]

# Static list for admin display (current year)
US_HOLIDAYS = _get_holidays(date.today().year)

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

def _moon_phase(dt=None):
    """Jean Meeus algorithm - accurate to ~1 day."""
    import math
    if dt is None:
        from datetime import timezone
        dt = datetime.now(timezone.utc)
    y, m, d = dt.year, dt.month, dt.day
    if m <= 2: y -= 1; m += 12
    A = int(y/100); B = 2 - A + int(A/4)
    jd = int(365.25*(y+4716)) + int(30.6001*(m+1)) + d + B - 1524.5
    jd += (dt.hour + dt.minute/60 + dt.second/3600) / 24
    age = (jd - 2451550.259722) % 29.530588853
    if age < 0: age += 29.530588853
    illumination = (1 - math.cos(2 * math.pi * (age / 29.530588853))) / 2
    pct = illumination * 100
    if pct <= 5:                     name = "New Moon"
    elif pct <= 45 and age < 14.77:  name = "Waxing Crescent"
    elif pct <= 55 and age < 14.77:  name = "First Quarter"
    elif pct < 95 and age < 14.77:   name = "Waxing Gibbous"
    elif pct >= 95:                  name = "Full Moon"
    elif pct >= 55 and age >= 14.77: name = "Waning Gibbous"
    elif pct >= 45 and age >= 14.77: name = "Last Quarter"
    else:                            name = "Waning Crescent"
    return {"phase": name, "illumination": round(pct), "age_days": round(age, 1)}

def load_events():
    if not os.path.exists(EVENTS_FILE):
        save_events([])
        return []
    with open(EVENTS_FILE, "r") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_events(items):
    with open(EVENTS_FILE, "w") as f:
        json.dump(items, f, indent=2)

def get_upcoming(days_ahead=14):
    """Return holidays + custom events occurring within days_ahead days."""
    today = date.today()
    year  = today.year
    result = []
    all_events = _get_holidays(year) + load_events()
    for ev in all_events:
        # Try this year, then next year
        for y in (year, year + 1):
            try:
                ev_date = date(y, ev["month"], ev["day"])
            except ValueError:
                continue
            delta = (ev_date - today).days
            if 0 <= delta <= days_ahead:
                result.append({
                    "id":       ev["id"],
                    "name":     ev["name"],
                    "date":     ev_date.isoformat(),
                    "date_fmt": ev_date.strftime("%a, %b %-d"),
                    "days":     delta,
                    "holiday":  ev["id"].startswith("h-"),
                })
                break
    result.sort(key=lambda x: x["days"])
    return result

@app.route("/api/sleep_schedule")
def api_sleep_schedule():
    return jsonify(load_sleep_schedule())

@app.route("/admin/sleep", methods=["POST"])
def update_sleep():
    try:
        sh = int(request.form.get("sleep_hour", 23))
        sm = int(request.form.get("sleep_minute", 30))
        wh = int(request.form.get("wake_hour", 6))
        wm = int(request.form.get("wake_minute", 30))
        save_sleep_schedule({"sleep_hour": sh, "sleep_minute": sm, "wake_hour": wh, "wake_minute": wm})
    except Exception:
        pass
    return redirect(url_for("admin"))

@app.route("/sleep")
def sleep():
    return render_template("sleep.html")

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/admin")
def admin():
    reminders = load_reminders()
    today_str = date.today().isoformat()

    # Partition reminders: active (visible on dashboard), past_due (hidden
    # from dashboard but kept here for cleanup), and done.
    active   = []
    past_due = []
    done     = []
    for r in reminders:
        if r.get("done"):
            done.append(r)
        elif r.get("due") and r["due"] < today_str:
            past_due.append(r)
        else:
            active.append(r)
    active.sort(key=lambda r: (r.get("due") or "9999-99-99"))
    past_due.sort(key=lambda r: r.get("due") or "")

    stocks = load_stocks()
    events = load_events()
    holidays = US_HOLIDAYS
    sleep_schedule = load_sleep_schedule()
    location = load_location()
    location_error = request.args.get("location_error")
    return render_template(
        "admin.html",
        reminders=reminders,
        active=active,
        past_due=past_due,
        done_reminders=done,
        now=today_str,
        stocks=stocks,
        events=events,
        holidays=holidays,
        sleep=sleep_schedule,
        location=location,
        location_error=location_error,
    )

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

@app.route("/admin/clear_past", methods=["POST"])
def clear_past_reminders():
    """Delete all reminders whose due date is before today."""
    today = date.today().isoformat()
    reminders = load_reminders()
    reminders = [
        r for r in reminders
        if not r.get("due") or r["due"] >= today
    ]
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
    """Return active reminders that have NOT yet passed their due date.
    Reminders past their due date are hidden from the main dashboard
    automatically (they remain visible/editable in the admin page)."""
    all_items = load_reminders()
    today = date.today().isoformat()
    active = [
        r for r in all_items
        if not r.get("done")
        and (not r.get("due") or r["due"] >= today)
    ]
    # Items due today still show; mark them so the UI can highlight
    for r in active:
        r["overdue"] = False  # by definition, nothing past-due reaches here
    active.sort(key=lambda r: (r.get("due") or "9999-99-99"))
    return jsonify({"items": active})

@app.route("/api/location")
def api_location():
    return jsonify(load_location())

@app.route("/admin/location", methods=["POST"])
def update_location():
    """Save (or update) the location from manually-entered coordinates."""
    lat   = request.form.get("lat", "").strip()
    lon   = request.form.get("lon", "").strip()
    tz    = request.form.get("timezone", "").strip()
    label = request.form.get("label", "").strip()

    if not (lat and lon):
        return redirect(url_for("admin", location_error="empty"))

    try:
        save_location({
            "city":     label or f"{lat}, {lon}",
            "lat":      float(lat),
            "lon":      float(lon),
            "timezone": tz or "UTC",
        })
    except ValueError:
        return redirect(url_for("admin", location_error="invalid"))

    return redirect(url_for("admin"))

@app.route("/api/weather")
def api_weather():
    loc = load_location()
    lat, lon = loc.get("lat"), loc.get("lon")
    if lat is None or lon is None:
        return jsonify({"error": "Location not configured. Set it in /admin."}), 400
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
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
            "moon":        _moon_phase(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/events")
def api_events():
    return jsonify({"items": get_upcoming()})

@app.route("/admin/events/add", methods=["POST"])
def add_event():
    name  = request.form.get("name", "").strip()
    month = request.form.get("month", "").strip()
    day   = request.form.get("day", "").strip()
    if name and month and day:
        events = load_events()
        events.append({
            "id":    "e-" + str(uuid.uuid4())[:8],
            "name":  name,
            "month": int(month),
            "day":   int(day),
        })
        save_events(events)
    return redirect(url_for("admin"))

@app.route("/admin/events/remove/<eid>", methods=["POST"])
def remove_event(eid):
    events = load_events()
    events = [e for e in events if e["id"] != eid]
    save_events(events)
    return redirect(url_for("admin"))

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
