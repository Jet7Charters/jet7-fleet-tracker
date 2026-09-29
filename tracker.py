"""Jet7 fleet tracker (OpenSky Network) — run once per hour.

For each tail:
  * In the air     -> live ADS-B position and the track actually flown.
  * On the ground  -> live position, labelled with the nearest airport.
  * Not heard now  -> last place we saw it (remembered between runs), or the
                      last arrival airport OpenSky recorded.
OpenSky has no flight plans, so no destination is shown while flying.
Then rebuilds docs/index.html and sends the hourly email and text.
"""

import csv
import io
import json
import math
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from nnumber import n_to_icao24

# ---------------------------------------------------------------- config
TAILS = ["N936AM", "N511AB", "N577XW", "N560PA", "N560WV", "N50XY", "N156RE"]
LOCAL_TZ = ZoneInfo(os.environ.get("LOCAL_TZ") or "America/New_York")

ROOT = Path(__file__).parent
DATA, DOCS = ROOT / "data", ROOT / "docs"
TEMPLATE = ROOT / "map_template.html"
OPENSKY = "https://opensky-network.org/api"
TOKEN_URL = ("https://auth.opensky-network.org/auth/realms/opensky-network/"
             "protocol/openid-connect/token")
AIRPORTS_CSV = "https://davidmegginson.github.io/ourairports-data/airports.csv"
STALE = 15 * 60          # no ADS-B for 15 min => not currently heard
M_TO_FT, MS_TO_KT = 3.28084, 1.94384

env = os.environ.get


# ---------------------------------------------------------------- helpers
def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj, indent=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=indent))


def local(ts, fmt="%a %-I:%M %p"):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(LOCAL_TZ).strftime(fmt)


def km(a_lat, a_lon, b_lat, b_lon):
    p = math.pi / 180
    h = (math.sin((b_lat - a_lat) * p / 2) ** 2 + math.cos(a_lat * p) *
         math.cos(b_lat * p) * math.sin((b_lon - a_lon) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- airports
def load_airports():
    """[ident, short code, name, lat, lon] — downloaded once, then cached."""
    path = DATA / "airports.json"
    cached = load_json(path, None)
    if cached:
        return cached
    r = requests.get(AIRPORTS_CSV, timeout=60)
    r.raise_for_status()
    rows = []
    for a in csv.DictReader(io.StringIO(r.text)):
        if a["type"] in ("small_airport", "medium_airport", "large_airport"):
            short = a["iata_code"] or a["local_code"] or a["ident"]
            rows.append([a["ident"], short, a["name"],
                         round(float(a["latitude_deg"]), 4),
                         round(float(a["longitude_deg"]), 4)])
    save_json(path, rows, indent=None)
    return rows


def nearest(airports, lat, lon):
    best = min(airports, key=lambda a: (a[3] - lat) ** 2 +
               ((a[4] - lon) * math.cos(lat * math.pi / 180)) ** 2)
    return {"code": best[1], "name": best[2], "lat": best[3], "lon": best[4],
            "km": round(km(lat, lon, best[3], best[4]), 1)}


def by_ident(airports, ident):
    for a in airports:
        if a[0] == ident:
            return {"code": a[1], "name": a[2], "lat": a[3], "lon": a[4], "km": 0}
    return None


# ---------------------------------------------------------------- OpenSky
def session():
    s = requests.Session()
    cid, secret = env("OPENSKY_CLIENT_ID"), env("OPENSKY_CLIENT_SECRET")
    if cid and secret:
        r = requests.post(TOKEN_URL, timeout=30, data={
            "grant_type": "client_credentials",
            "client_id": cid, "client_secret": secret})
        r.raise_for_status()
        s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


def get_states(s, icaos):
    r = s.get(f"{OPENSKY}/states/all", params=[("icao24", i) for i in icaos], timeout=30)
    r.raise_for_status()
    out = {}
    for st in (r.json().get("states") or []):
        out[st[0]] = {
            "last_contact": st[4], "lon": st[5], "lat": st[6],
            "alt_ft": round(st[7] * M_TO_FT) if st[7] is not None else None,
            "on_ground": st[8],
            "speed_kt": round(st[9] * MS_TO_KT) if st[9] is not None else None,
            "heading": st[10]}
    return out


def get_track(s, icao):
    try:
        r = s.get(f"{OPENSKY}/tracks/all", params={"icao24": icao, "time": 0}, timeout=30)
        if r.status_code != 200:
            return None
        j = r.json()
        return {"start": j.get("startTime"),
                "path": [[p[1], p[2]] for p in (j.get("path") or []) if p[1] is not None]}
    except requests.RequestException:
        return None


def last_arrival(s, icao, now):
    """Most recent arrival airport OpenSky has recorded (updated in batches)."""
    try:
        r = s.get(f"{OPENSKY}/flights/aircraft", timeout=30,
                  params={"icao24": icao, "begin": now - 2 * 86400, "end": now})
        if r.status_code != 200:
            return None
        fl = [f for f in r.json() if f.get("estArrivalAirport")]
        if not fl:
            return None
        f = max(fl, key=lambda f: f["lastSeen"])
        return f["estArrivalAirport"], f["lastSeen"]
    except (requests.RequestException, ValueError):
        return None


# ---------------------------------------------------------------- notify
def fmt_line(a):
    if a["status"] == "airborne":
        dep = f" from {a['origin']['code']}" if a.get("origin") else ""
        alt = f"{a['alt_ft']:,}" if a.get("alt_ft") is not None else "?"
        return f"{a['tail']}: AIRBORNE{dep}, {alt} ft, {a.get('speed_kt') or '?'} kt"
    if a["status"] == "on_ground":
        return f"{a['tail']}: on ground at {a['airport']['code']}"
    if a["status"] == "last_seen":
        where = ("in the air near " if a.get("was_airborne") else "at ") + a["airport"]["code"]
        return f"{a['tail']}: not transmitting; last seen {where}, {a['seen']}"
    return f"{a['tail']}: no recent data"


def send_email(subject, body):
    host, to = env("SMTP_HOST"), env("EMAIL_TO")
    if not (host and to):
        return
    msg = MIMEText(body)
    msg["Subject"], msg["To"] = subject, to
    msg["From"] = env("EMAIL_FROM") or env("SMTP_USER", "")
    with smtplib.SMTP(host, int(env("SMTP_PORT") or 587), timeout=30) as smtp:
        smtp.starttls()
        smtp.login(env("SMTP_USER"), env("SMTP_PASS"))
        smtp.send_message(msg)


def send_sms(body):
    sid, token = env("TWILIO_SID"), env("TWILIO_TOKEN")
    if not (sid and token and env("SMS_TO")):
        return
    requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        auth=(sid, token), timeout=30,
        data={"From": env("TWILIO_FROM"), "To": env("SMS_TO"), "Body": body[:1500]})


# ---------------------------------------------------------------- main
def main():
    now = int(time.time())
    airports = load_airports()
    seen = load_json(DATA / "last_seen.json", {})
    s = session()
    icao_of = {t: n_to_icao24(t) for t in TAILS}
    states = get_states(s, list(icao_of.values()))

    aircraft = []
    for tail, icao in icao_of.items():
        rec = {"tail": tail, "icao24": icao, "status": "unknown", "track": []}
        st = states.get(icao)
        live = st and st["lat"] is not None and now - (st["last_contact"] or 0) < STALE

        if live:
            rec.update(st, lat=st["lat"], lon=st["lon"])
            seen[icao] = {"lat": st["lat"], "lon": st["lon"],
                          "t": st["last_contact"], "air": not st["on_ground"]}
            if st["on_ground"]:
                rec.update(status="on_ground", airport=nearest(airports, st["lat"], st["lon"]))
            else:
                rec["status"] = "airborne"
                tr = get_track(s, icao)
                if tr and len(tr["path"]) > 1:
                    rec["track"] = tr["path"]
                    rec["origin"] = nearest(airports, *tr["path"][0])
                    if tr["start"]:
                        rec["departed"] = local(tr["start"])
        elif icao in seen:
            p = seen[icao]
            rec.update(status="last_seen", lat=p["lat"], lon=p["lon"],
                       airport=nearest(airports, p["lat"], p["lon"]),
                       seen=local(p["t"]), was_airborne=p["air"])
        else:
            arr = last_arrival(s, icao, now)
            ap = by_ident(airports, arr[0]) if arr else None
            if ap:
                seen[icao] = {"lat": ap["lat"], "lon": ap["lon"], "t": arr[1], "air": False}
                rec.update(status="last_seen", lat=ap["lat"], lon=ap["lon"],
                           airport=ap, seen=local(arr[1]), was_airborne=False)
        aircraft.append(rec)

    stamp = datetime.fromtimestamp(now, timezone.utc).astimezone(LOCAL_TZ) \
        .strftime("%a %b %-d, %-I:%M %p %Z")
    payload = {"updated": stamp, "aircraft": aircraft}
    save_json(DATA / "last_seen.json", seen)
    save_json(DOCS / "data.json", payload)
    (DOCS / "index.html").write_text(
        TEMPLATE.read_text().replace("__FLEET_DATA__", json.dumps(payload)))

    up = sum(a["status"] == "airborne" for a in aircraft)
    link = env("PAGE_URL", "")
    body = (f"Jet7 fleet, {stamp}\n\n" + "\n".join(fmt_line(a) for a in aircraft)
            + (f"\n\nMap: {link}" if link else ""))
    send_email(f"Jet7 fleet: {up} airborne ({stamp})", body)
    send_sms(body)
    print(body)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        sys.exit(f"Data request failed: {e}")
