#!/usr/bin/env python3
"""ZAYS MOTION PLAYS - NFL weather layer.

Pulls a FRESH forecast (never cached weather) for every upcoming NFL game's
stadium and kickoff window, tags it, compares the market total, and writes
reports/nfl_weather.json. Runs in GitHub Actions (see .github/workflows/weather.yml).

Usage: python weather/build_weather.py [--force] [--now ISO]
Stdlib only.
"""
import json, math, os, re, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(ROOT, "weather")
OUT = os.path.join(ROOT, "reports", "nfl_weather.json")
STADIUMS = os.path.join(W, "stadiums.json")
ROOFS = os.path.join(W, "roof_status.json")
POINTS = os.path.join(W, "nws_points.json")
ALERTS = os.path.join(W, "alerts.json")
PT = ZoneInfo("America/Los_Angeles")
UA = "ZMP-weather/1.0 (github.com/matthewleon66-ai/zmp-injury-reports)"
KMH_TO_MPH = 0.621
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


# ---------------------------------------------------------------- helpers
def get_json(url, accept="application/geo+json", tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa
            last = e
            time.sleep(2 + 3 * i)
    raise RuntimeError(f"{url}: {last}")


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def pt_str(dt):
    d = dt.astimezone(PT)
    return d.strftime("%a %-m/%-d %-I:%M %p PT")


def c_to_f(c):
    return None if c is None else c * 9 / 5 + 32


def r0(x):
    return None if x is None else int(round(x))


def r2(x):
    return None if x is None else round(x, 2)


def compass_mode(dirs):
    dirs = [d for d in dirs if d]
    return max(set(dirs), key=dirs.count) if dirs else None


def deg_to_compass(deg):
    if deg is None:
        return None
    pts = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return pts[int((deg % 360) / 22.5 + 0.5) % 16]


def parse_duration(s):
    m = re.match(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", s)
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    return timedelta(days=d, hours=h, minutes=mi)


def grid_series(prop):
    """NWS grid property -> list of (start, end, value)."""
    out = []
    for v in (prop or {}).get("values", []):
        t, dur = v["validTime"].split("/")
        s = parse_dt(t)
        out.append((s, s + parse_duration(dur), v["value"]))
    return out


def grid_at(series, hour):
    for s, e, v in series:
        if s <= hour < e:
            return v
    return None


def grid_sum(series, start, end):
    """Prorated sum of an accumulation series over [start, end)."""
    tot, seen = 0.0, False
    for s, e, v in series:
        ov = (min(e, end) - max(s, start)).total_seconds()
        if ov > 0 and v is not None:
            seen = True
            tot += v * ov / (e - s).total_seconds()
    return tot if seen else None


def uom_to_mph(val, uom):
    if val is None:
        return None
    u = (uom or "").lower()
    if "km_h" in u:
        return val * KMH_TO_MPH
    if "m_s" in u:
        return val * 2.23694
    if "kn" in u:
        return val * 1.15078
    return val


def mph_from_text(s):
    nums = [int(n) for n in re.findall(r"\d+", s or "")]
    return sum(nums) / len(nums) if nums else None


# ---------------------------------------------------------------- schedule & odds
def espn_games(now):
    start = now.astimezone(PT).date()
    end = start + timedelta(days=7)
    base = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?limit=100&dates="
    events, seen, data = [], set(), {}
    for i in range(8):  # one call per day: ESPN rejects some multi-day ranges
        day = start + timedelta(days=i)
        try:
            data = get_json(f"{base}{day:%Y%m%d}", accept="application/json")
        except Exception as e:
            log(f"  ESPN {day} failed: {e}")
            continue
        for ev in data.get("events", []):
            if ev["id"] not in seen:
                seen.add(ev["id"]); events.append(ev)
    if not seen and not data:
        raise RuntimeError("ESPN scoreboard unreachable")
    games = []
    for ev in events:
        comp = ev["competitions"][0]
        state = comp.get("status", {}).get("type", {}).get("state") or ev.get("status", {}).get("type", {}).get("state")
        if state != "pre":
            continue
        if os.environ.get("WX_DEBUG") and not games:
            log("  DEBUG odds:", json.dumps(comp.get("odds"))[:3000])
        teams = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
        venue = comp.get("venue", {}) or {}
        week = (ev.get("week") or data.get("week") or {}).get("number")
        games.append({
            "id": str(ev["id"]), "away": teams.get("away"), "home": teams.get("home"),
            "kickoff": parse_dt(ev["date"]), "week": week,
            "neutral": bool(comp.get("neutralSite")),
            "venue": {"name": venue.get("fullName"), "city": (venue.get("address") or {}).get("city"),
                      "state": (venue.get("address") or {}).get("state"),
                      "country": (venue.get("address") or {}).get("country"), "indoor": venue.get("indoor")},
            "odds": parse_odds((comp.get("odds") or [None])[0]),
        })
    return games


def _num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"-?\d+(?:\.\d+)?", str(x))
    return float(m.group()) if m else None


def _total_from(block):
    if not isinstance(block, dict):
        return None
    for path in (("total", "alternateDisplayValue"), ("total", "american"), ("total", "value"),
                 ("over", "line"), ("over", "alternateDisplayValue")):
        v = block
        for k in path:
            v = v.get(k) if isinstance(v, dict) else None
        n = _num(v)
        if n is not None and n > 20:
            return n
    return None


def _open_total(o):
    """ESPN: odds.total.over.open.line like 'o45.5' (fallback: odds.open.total)."""
    t = o.get("total") if isinstance(o.get("total"), dict) else {}
    for side in ("over", "under"):
        n = _num(((t.get(side) or {}).get("open") or {}).get("line"))
        if n is not None and n > 20:
            return n
    return _total_from(o.get("open"))


def parse_odds(o):
    if not o:
        return {"provider": None, "total": None, "total_open": None, "spread": None}
    return {
        "provider": (o.get("provider") or {}).get("name"),
        "total": _num(o.get("overUnder")) or _total_from(o.get("current")),
        "total_open": _open_total(o),
        "spread": o.get("details"),
    }


def espn_open_total(event_id):
    """Fallback: opening total from the ESPN game summary pickcenter."""
    try:
        d = get_json(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}",
                     accept="application/json")
    except Exception as e:
        log("  summary odds failed:", e)
        return None
    if os.environ.get("WX_DEBUG"):
        log("  DEBUG pickcenter:", json.dumps(d.get("pickcenter"))[:3000])
    for pc in d.get("pickcenter", []) or []:
        t = _open_total(pc)
        if t:
            return t
    return None


# ---------------------------------------------------------------- venue
def resolve_venue(g, stadiums):
    if not g["neutral"] and g["home"] in stadiums:
        s = dict(stadiums[g["home"]])
        s["neutral"] = False
        s["country"] = "USA"
        return s
    v = g["venue"]
    for s in stadiums.values():  # neutral game at another NFL stadium
        if v.get("name") and s["stadium"].lower() == v["name"].lower():
            s = dict(s); s["neutral"] = True; s["country"] = "USA"
            return s
    q = v.get("city") or v.get("name")
    geo = get_json("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(q),
                   accept="application/json")
    r = (geo.get("results") or [{}])[0]
    country = v.get("country") or r.get("country") or ""
    return {"stadium": v.get("name") or "TBD", "city": ", ".join(x for x in (v.get("city"), v.get("state") or country) if x),
            "lat": r.get("latitude"), "lon": r.get("longitude"),
            "roof": "indoor" if v.get("indoor") else "open", "station": None, "neutral": True,
            "country": "USA" if country in ("USA", "United States") else country,
            "verify": "Neutral/international venue: coordinates geocoded from city, roof from ESPN venue.indoor. Verify."}


def nws_points(lat, lon, cache, expected_city):
    key = f"{lat:.4f},{lon:.4f}"
    if key in cache:
        return cache[key]
    p = get_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")["properties"]
    rl = p.get("relativeLocation", {}).get("properties", {})
    coords = p.get("relativeLocation", {}).get("geometry", {}).get("coordinates") or [lon, lat]
    dist_km = haversine(lat, lon, coords[1], coords[0])
    exp_state = (expected_city or "").split(",")[-1].strip()
    ok = dist_km <= 30 and (not exp_state or rl.get("state") == exp_state)
    cache[key] = {"forecastHourly": p["forecastHourly"], "forecastGridData": p["forecastGridData"],
                  "nws_city": f'{rl.get("city")}, {rl.get("state")}', "km_from_nws_ref": round(dist_km, 1),
                  "verified": ok, "checked": iso(datetime.now(timezone.utc))}
    log(f"  points {key} -> {cache[key]['nws_city']} ({dist_km:.1f} km) verified={ok}")
    return cache[key]


def haversine(a1, o1, a2, o2):
    R = 6371
    p1, p2 = math.radians(a1), math.radians(a2)
    dp, dl = p2 - p1, math.radians(o2 - o1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- weather pulls
def window_hours(kick):
    k = kick.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [k + timedelta(hours=i) for i in range(4)]  # kickoff hour .. +3h


def pull_nws(pts, hours):
    fh = get_json(pts["forecastHourly"])["properties"]
    gd = get_json(pts["forecastGridData"])["properties"]
    per = {parse_dt(p["startTime"]).astimezone(timezone.utc): p for p in fh["periods"]}
    gust_s = grid_series(gd.get("windGust")); gust_u = (gd.get("windGust") or {}).get("uom")
    app_s = grid_series(gd.get("apparentTemperature"))
    qpf_s = grid_series(gd.get("quantitativePrecipitation")); qpf_u = (gd.get("quantitativePrecipitation") or {}).get("uom", "")
    snow_s = grid_series(gd.get("snowfallAmount")); snow_u = (gd.get("snowfallAmount") or {}).get("uom", "")
    rows = []
    for h in hours:
        p = per.get(h)
        if not p:
            continue
        rows.append({"hour": h, "wind": mph_from_text(p.get("windSpeed")), "dir": p.get("windDirection"),
                     "gust": uom_to_mph(grid_at(gust_s, h), gust_u),
                     "temp": p.get("temperature") if p.get("temperatureUnit", "F") == "F" else c_to_f(p.get("temperature")),
                     "feels": c_to_f(grid_at(app_s, h)),
                     "pop": (p.get("probabilityOfPrecipitation") or {}).get("value"),
                     "text": p.get("shortForecast", "")})
    if not rows:
        return None
    end = hours[-1] + timedelta(hours=1)
    mm_to_in = lambda v, u: None if v is None else (v / 25.4 if "mm" in u else v)
    return summarize(rows, mm_to_in(grid_sum(qpf_s, hours[0], end), qpf_u), mm_to_in(grid_sum(snow_s, hours[0], end), snow_u),
                     issued=fh.get("updateTime") or fh.get("generatedAt"), source="NWS")


def pull_open_meteo(lat, lon, hours):
    q = ("https://api.open-meteo.com/v1/forecast?latitude={:.4f}&longitude={:.4f}"
         "&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m,apparent_temperature,"
         "precipitation_probability,precipitation,snowfall,weather_code"
         "&wind_speed_unit=mph&temperature_unit=fahrenheit&precipitation_unit=inch&timezone=auto&forecast_days=10").format(lat, lon)
    d = get_json(q, accept="application/json")
    off = timedelta(seconds=d.get("utc_offset_seconds", 0))
    hr = d["hourly"]
    idx = {(datetime.fromisoformat(t) - off).replace(tzinfo=timezone.utc): i for i, t in enumerate(hr["time"])}
    rows, precip, snow = [], 0.0, 0.0
    for h in hours:
        i = idx.get(h)
        if i is None:
            continue
        g = lambda k: hr.get(k, [None] * (i + 1))[i]
        code = g("weather_code") or 0
        rows.append({"hour": h, "wind": g("wind_speed_10m"), "dir": deg_to_compass(g("wind_direction_10m")),
                     "gust": g("wind_gusts_10m"), "temp": g("temperature_2m"), "feels": g("apparent_temperature"),
                     "pop": g("precipitation_probability"),
                     "text": "Snow" if code in (71, 73, 75, 77, 85, 86) else ("Heavy Rain" if code in (65, 82) else ("Rain" if code in (51, 53, 55, 61, 63, 80, 81) else ""))})
        # precipitation at hour h is the total of the preceding hour -> use h+1 for hour h
        j = idx.get(h + timedelta(hours=1))
        if j is not None:
            precip += hr["precipitation"][j] or 0
            snow += hr["snowfall"][j] or 0
    if not rows:
        return None
    return summarize(rows, precip, snow, issued=None, source="Open-Meteo")


def summarize(rows, precip_in, snow_in, issued, source):
    winds = [r["wind"] for r in rows if r["wind"] is not None]
    gusts = [r["gust"] for r in rows if r["gust"] is not None]
    temps = [r["temp"] for r in rows if r["temp"] is not None]
    feels = [r["feels"] for r in rows if r["feels"] is not None]
    pops = [r["pop"] for r in rows if r["pop"] is not None]
    text = " ".join(r["text"] for r in rows).lower()
    if (snow_in or 0) > 0.05 or "snow" in text:
        ptype = "snow"
    elif any(w in text for w in ("sleet", "freezing")):
        ptype = "mix"
    elif any(w in text for w in ("rain", "shower", "drizzle", "thunder")) or (precip_in or 0) > 0.01:
        ptype = "rain"
    else:
        ptype = "none"
    return {
        "source": source, "issued": issued,
        "wind_avg": r0(sum(winds) / len(winds)) if winds else None,
        "wind_peak": r0(max(winds)) if winds else None,
        "gust": r0(max(gusts)) if gusts else None,
        "dir": compass_mode([r["dir"] for r in rows]),
        "dir_at_kick": rows[0]["dir"],
        "temp": r0(sum(temps) / len(temps)) if temps else None,
        "feels": r0(min(feels)) if feels else None,
        "precip_chance": r0(max(pops)) if pops else 0,
        "precip_in": r2(precip_in or 0),
        "snow_in": r2(snow_in or 0),
        "precip_type": ptype,
        "heavy_text": "heavy" in text,
        "hours": [{"t": iso(r["hour"]), "wind": r0(r["wind"]), "gust": r0(r["gust"]), "dir": r["dir"], "temp": r0(r["temp"]),
                   "feels": r0(r["feels"]), "pop": r["pop"], "wx": r["text"]} for r in rows],
    }


def observation(station):
    p = get_json(f"https://api.weather.gov/stations/{station}/observations/latest")["properties"]
    ws, wg = p.get("windSpeed", {}), p.get("windGust", {})
    return {"station": station, "time": p.get("timestamp"), "text": p.get("textDescription"),
            "wind": r0(uom_to_mph(ws.get("value"), ws.get("unitCode"))),
            "gust": r0(uom_to_mph(wg.get("value"), wg.get("unitCode"))),
            "dir": deg_to_compass((p.get("windDirection") or {}).get("value")),
            "temp": r0(c_to_f((p.get("temperature") or {}).get("value")))}


# ---------------------------------------------------------------- tags & logic
def wind_tag(w):
    if w is None:
        return None
    return "CALM" if w < 10 else "BREEZY" if w < 15 else "WINDY" if w < 20 else "HIGH WIND"


def make_tags(wx):
    tags = [wind_tag(wx["wind_avg"])]
    if (wx["gust"] or 0) >= 25:
        tags.append("GUSTY")
    if wx["precip_type"] == "rain" and wx["precip_chance"] >= 50 and (wx["precip_in"] >= 0.25 or wx["heavy_text"]):
        tags.append("WET")
    if wx["precip_type"] in ("snow", "mix") and wx["precip_chance"] >= 40 and (wx["snow_in"] >= 0.2 or wx["precip_in"] >= 0.05):
        tags.append("SNOW")
    if wx["feels"] is not None and wx["feels"] <= 20:
        tags.append("COLD")
    return [t for t in tags if t]


def confidence(now, kick):
    if now.astimezone(PT).date() == kick.astimezone(PT).date():
        return "FINAL"
    hrs = (kick - now).total_seconds() / 3600
    return "HIGH" if hrs <= 48 else "MEDIUM" if hrs < 120 else "LOW"


def refresh_interval(now, kick):
    if now.astimezone(PT).date() == kick.astimezone(PT).date():
        return timedelta(hours=1) if now >= kick - timedelta(hours=3) else timedelta(hours=6)
    wd = now.astimezone(PT).weekday()  # Mon=0
    return timedelta(hours=12) if wd <= 2 else timedelta(hours=6)


def is_due(now, kick, prev, roof_changed):
    if not prev or roof_changed or not prev.get("pulled_at_iso"):
        return True
    last = parse_dt(prev["pulled_at_iso"])
    final = kick - timedelta(minutes=90)
    if now >= final and last < final:
        return True
    return now - last >= refresh_interval(now, kick) - timedelta(minutes=10)


def roof_state(g, venue, roofs):
    if venue["roof"] == "indoor":
        return "INDOOR"
    if venue["roof"] == "open":
        return "OPEN-AIR"
    r = (roofs.get(g["id"]) or {}).get("status", "").lower()
    return {"open": "ROOF OPEN", "closed": "INDOOR (roof closed)"}.get(r, "ROOF TBD")


# ---------------------------------------------------------------- main
def main():
    force = "--force" in sys.argv
    now = datetime.now(timezone.utc)
    if "--now" in sys.argv:
        now = parse_dt(sys.argv[sys.argv.index("--now") + 1])
    stadiums = load(STADIUMS, {})["teams"]
    roofs = load(ROOFS, {})
    points = load(POINTS, {})
    prev_doc = load(OUT, {"games": []})
    prev = {g["espn_event_id"]: g for g in prev_doc.get("games", [])}
    alerts_doc = load(ALERTS, {"alerts": []})
    new_alerts, errors = [], []

    games = espn_games(now)
    log(f"{len(games)} upcoming games")
    out = []
    for g in sorted(games, key=lambda x: x["kickoff"]):
        label = f'{g["away"]}@{g["home"]}'
        p = prev.get(g["id"], {})
        try:
            venue = resolve_venue(g, stadiums)
        except Exception as e:
            errors.append(f"{label}: venue {e}"); log("  ERR", errors[-1])
            if p: out.append(p)
            continue
        roof = roof_state(g, venue, roofs)
        roof_changed = bool(p) and p.get("roof") != roof
        # ---- market (every run)
        odds = g["odds"]
        t_now = odds["total"]
        pt = p.get("total", {})
        t_open = odds["total_open"] or (pt.get("open") if pt.get("open_source") == "ESPN" else None)
        if t_open is None and t_now is not None and not pt:
            t_open = espn_open_total(g["id"])
        open_src = "ESPN" if t_open is not None else None
        if t_open is None:
            t_open = p.get("total", {}).get("first_seen") or t_now
            open_src = "first seen by this feed"
        t_prev = p.get("total", {}).get("now")
        hist = p.get("total", {}).get("history", [])
        if t_now is not None and (not hist or hist[-1]["total"] != t_now):
            hist = (hist + [{"t": iso(now), "total": t_now}])[-12:]
        total = {"open": t_open, "open_source": open_src, "first_seen": p.get("total", {}).get("first_seen") or t_now,
                 "prev": t_prev if t_prev != t_now else p.get("total", {}).get("prev"), "now": t_now,
                 "spread": odds["spread"], "book": odds["provider"], "history": hist}

        due = force or is_due(now, g["kickoff"], p, roof_changed)
        rec = dict(p) if (p and not due) else {}
        rec.update({"espn_event_id": g["id"], "away": g["away"], "home": g["home"], "week": g["week"],
                    "kickoff": iso(g["kickoff"]), "kickoff_pt": pt_str(g["kickoff"]),
                    "stadium": venue["stadium"], "city": venue["city"], "neutral_site": venue.get("neutral", False),
                    "roof": roof, "confidence": confidence(now, g["kickoff"]), "total": total})
        if venue.get("verify"):
            rec["venue_note"] = venue["verify"]
        if roof.startswith("INDOOR"):
            rec.update({"weather": None, "tags": ["INDOOR"], "display_weather": "INDOOR – weather N/A",
                        "pulled_at": pt_str(now), "pulled_at_iso": iso(now), "sources": [], "sources_disagree": False})
            if venue["roof"] == "retractable":
                rec["roof_source"] = roofs.get(g["id"], {}).get("source")
        elif due:
            log(f"{label} {venue['stadium']} roof={roof} -> pulling")
            hours = window_hours(g["kickoff"])
            nws = om = obs = None
            if venue["country"] == "USA" and venue["lat"] is not None:
                try:
                    pts = nws_points(venue["lat"], venue["lon"], points, venue["city"])
                    rec["stadium_check"] = {k: pts[k] for k in ("nws_city", "km_from_nws_ref", "verified")}
                    nws = pull_nws(pts, hours)
                except Exception as e:
                    errors.append(f"{label}: NWS {e}"); log("  ERR", errors[-1])
            try:
                om = pull_open_meteo(venue["lat"], venue["lon"], hours)
            except Exception as e:
                errors.append(f"{label}: Open-Meteo {e}"); log("  ERR", errors[-1])
            if venue.get("station") and now >= g["kickoff"] - timedelta(hours=6) and now.astimezone(PT).date() == g["kickoff"].astimezone(PT).date():
                try:
                    obs = observation(venue["station"])
                except Exception as e:
                    errors.append(f"{label}: obs {e}")
            primary = nws or om
            if not primary:
                rec.update(p or {})
                rec["error"] = "No forecast source reachable this run; showing previous pull" if p else "No forecast source reachable"
                out.append(rec); continue
            disagree = bool(nws and om and nws["wind_avg"] is not None and om["wind_avg"] is not None
                            and abs(nws["wind_avg"] - om["wind_avg"]) >= 5)
            tags = make_tags(primary)
            if roof == "ROOF TBD":
                tags.append("ROOF TBD")
            if disagree:
                tags.append("SOURCES DISAGREE")
            rec.update({"weather": primary, "weather_backup": om if nws else None, "observation": obs,
                        "tags": tags, "sources_disagree": disagree,
                        "sources": [s for s in ("NWS" if nws else None, "Open-Meteo" if om else None) if s],
                        "pulled_at": pt_str(now), "pulled_at_iso": iso(now), "error": None})
            if disagree:
                rec["disagree_detail"] = f'NWS {nws["wind_avg"]} mph vs Open-Meteo {om["wind_avg"]} mph sustained'
        # ---- market tags / edge flags (every run)
        tags = [t for t in rec.get("tags", []) if t != "PRICED IN"]
        weather_game = any(t in tags for t in ("WINDY", "HIGH WIND", "WET", "SNOW"))
        if weather_game and t_open is not None and t_now is not None and t_open - t_now >= 1.5:
            tags.append("PRICED IN")
        rec["tags"] = tags
        rec["weather_game"] = weather_game
        wx = rec.get("weather")
        # alerts vs previous pull
        a = diff_alerts(label, p, rec) if (p and due) else []
        if roof_changed and not a:
            a = [f"{label}: roof status {p.get('roof')} -> {roof}"]
        rec["edge_rerun_needed"] = bool(a) or (weather_game and t_prev is not None and t_now != t_prev)
        rec["odds_display"] = odds_display(total) if (weather_game or a) else None
        rec["card"] = card(rec)
        for txt in a:
            new_alerts.append({"id": f"{g['id']}-{iso(now)}-{len(new_alerts)}", "created": iso(now),
                               "game": label, "kickoff_pt": rec["kickoff_pt"], "text": txt, "card": rec["card"], "notified": False})
        out.append(rec)

    save(POINTS, points)
    doc = {"updated": iso(now), "updated_pt": pt_str(now),
           "note": "Weather layer for the ZAYS MOTION PLAYS Sports tab. Built by weather/build_weather.py (GitHub Action). Fresh NWS + Open-Meteo pulls; never cached weather.",
           "columns": "Kickoff (PT) | Stadium | Roof | Wind (sustained / gust / direction) | Temp / Feels | Precip | Tags | Confidence | Total (open → now) | Source | Updated",
           "errors": errors, "games": out}
    save(OUT, doc)
    if new_alerts:
        alerts_doc["alerts"] = (alerts_doc.get("alerts", []) + new_alerts)[-200:]
        save(ALERTS, alerts_doc)
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"alerts={len(new_alerts)}\n")
    with open(os.path.join(W, ".last_alerts.md"), "w") as f:
        f.write("\n\n".join(f"**{x['text']}**\n\n`{x['card']}`" for x in new_alerts))
    log(f"done: {len(out)} games, {len(new_alerts)} alerts, {len(errors)} errors")
    return 0 if out or not games else 1


def diff_alerts(label, p, rec):
    a = []
    ow, nw = (p.get("weather") or {}), (rec.get("weather") or {})
    if not ow or not nw:
        return a
    o, n = ow.get("wind_avg"), nw.get("wind_avg")
    if o is not None and n is not None:
        if abs(n - o) >= 5 or wind_tag(o) != wind_tag(n):
            a.append(f"{label}: sustained wind {o} -> {n} mph ({wind_tag(o)} -> {wind_tag(n)})")
    og, ng = ow.get("gust") or 0, nw.get("gust") or 0
    if (og < 25) != (ng < 25):
        a.append(f"{label}: gusts {og} -> {ng} mph (crossed 25)")
    op, np_ = ow.get("precip_chance") or 0, nw.get("precip_chance") or 0
    if np_ - op >= 30:
        a.append(f"{label}: precip chance jumped {op}% -> {np_}% ({nw.get('precip_type')})")
    if p.get("roof") != rec.get("roof"):
        a.append(f"{label}: roof status {p.get('roof')} -> {rec.get('roof')}")
    return a


def fmt_total(x):
    return "—" if x is None else (f"{x:g}")


def odds_display(t):
    """New number on top, previous number below (struck through on the card)."""
    prev = t.get("prev") if t.get("prev") is not None else t.get("open")
    return {"now": f"O/U {fmt_total(t.get('now'))}", "before": f"O/U {fmt_total(prev)}",
            "changed": prev is not None and t.get("now") is not None and prev != t.get("now")}


def card(r):
    wx = r.get("weather")
    if r["roof"].startswith("INDOOR"):
        wind = temp = precip = "—"
    elif wx:
        wind = f'{wx["wind_avg"]} mph (peak {wx["wind_peak"]}) / gust {wx["gust"] if wx["gust"] is not None else "—"} / {wx["dir"] or "—"}'
        temp = f'{wx["temp"]}°F / {wx["feels"] if wx["feels"] is not None else "—"}°F'
        precip = f'{wx["precip_chance"]}% {wx["precip_type"]}' + (f' {wx["precip_in"]}"' if wx["precip_in"] else "") + (f' (snow {wx["snow_in"]}")' if wx["snow_in"] else "")
        if r.get("sources_disagree"):
            b = r.get("weather_backup") or {}
            wind += f' [Open-Meteo {b.get("wind_avg")}]'
    else:
        wind = temp = precip = "pending"
    t = r["total"]
    tot = f'{fmt_total(t.get("open"))} → {fmt_total(t.get("now"))}'
    roof = "INDOOR – weather N/A" if r["roof"] == "INDOOR" else r["roof"]
    src = " + ".join(r.get("sources") or []) or "—"
    return " | ".join([r["kickoff_pt"], r["stadium"], roof, wind, temp, precip, " ".join(r.get("tags") or []) or "—",
                       r["confidence"], tot, src, r.get("pulled_at", "—")])


if __name__ == "__main__":
    sys.exit(main())
