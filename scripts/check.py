"""Daily price check for every active trip.

For each trip: ask SerpApi (Google Flights) for today's prices, log them,
decide BUY or WAIT, text when a trip flips to BUY, and write docs/data.json.

Usage:
  python scripts/check.py                 # all active trips
  python scripts/check.py --only ID       # one trip (used right after adding it)
  python scripts/check.py --grid          # also refresh the +/-3 day grid now
  python scripts/check.py --offline FILE  # use a saved SerpApi response (testing)
"""
import argparse
import base64
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from config import (ALASKA_NAMES, BUY_NEAR_LOW, COMPANION_COST, DEADLINE_DAYS,
                    GRID_OFFSETS, GRID_WEEKDAY, LAST_MINUTE_DAYS, MIN_OBS_FOR_LOW)

ROOT = Path(__file__).resolve().parents[1]
TRIPS = ROOT / "data" / "trips.json"
PRICES = ROOT / "data" / "prices.json"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "docs" / "data.json"

SERPAPI = "https://serpapi.com/search.json"


def note(msg):
    print(f"::notice::{msg}")


def warn(msg):
    print(f"::warning::{msg}")


def error(msg):
    print(f"::error::{msg}")


def load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")


# ---------- SerpApi ----------

def search(trip, depart, ret, key):
    params = {
        "engine": "google_flights",
        "departure_id": trip["from"],
        "arrival_id": trip["to"],
        "outbound_date": depart,
        "currency": "USD",
        "hl": "en",
        "gl": "us",
        "adults": 1,  # per-person price; two-person math happens below
        "api_key": key,
    }
    if ret:
        params.update(type=1, return_date=ret)
    else:
        params.update(type=2)
    if trip.get("nonstop", True):
        params["stops"] = 1
    url = SERPAPI + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=90) as r:
        res = json.load(r)
    if res.get("error"):
        raise RuntimeError(res["error"])
    return res


def searches_left(key):
    try:
        with urllib.request.urlopen(
                "https://serpapi.com/account.json?" + urllib.parse.urlencode({"api_key": key}),
                timeout=30) as r:
            return json.load(r).get("total_searches_left")
    except Exception:
        return None


def is_alaska(option):
    legs = option.get("flights", [])
    return bool(legs) and all(
        any(leg.get("airline", "").startswith(n) for n in ALASKA_NAMES) for leg in legs)


def parse(res):
    """Pull what we use out of one SerpApi response."""
    options = [o for o in res.get("best_flights", []) + res.get("other_flights", [])
               if isinstance(o.get("price"), (int, float))]
    options.sort(key=lambda o: o["price"])
    alaska = [o for o in options if is_alaska(o)]
    ins = res.get("price_insights", {}) or {}

    def row(o):
        legs = o.get("flights", [])
        return {
            "price": o["price"],
            "airline": " / ".join(dict.fromkeys(l.get("airline", "?") for l in legs)),
            "flight": ", ".join(l.get("flight_number", "") for l in legs),
            "depart": legs[0].get("departure_airport", {}).get("time", "") if legs else "",
            "arrive": legs[-1].get("arrival_airport", {}).get("time", "") if legs else "",
            "stops": max(len(legs) - 1, 0),
            "minutes": o.get("total_duration"),
            "alaska": is_alaska(o),
        }

    typical = ins.get("typical_price_range")
    return {
        "low": options[0]["price"] if options else ins.get("lowest_price"),
        "alaska": alaska[0]["price"] if alaska else None,
        "level": ins.get("price_level"),
        "typical": typical if isinstance(typical, list) and len(typical) == 2 else None,
        "google_history": ins.get("price_history") or [],
        "options": [row(o) for o in options[:6]],
        "url": res.get("search_metadata", {}).get("google_flights_url"),
        "n_options": len(options),
    }


# ---------- verdict ----------

def days_between(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def tracked_price(trip, p):
    """Companion trips care about the Alaska fare; everything else, the cheapest fare."""
    if trip.get("companion") and p.get("alaska") is not None:
        return p["alaska"], "Alaska"
    return p.get("low"), "cheapest"


def two_person_cost(trip, p):
    if trip.get("companion") and p.get("alaska") is not None:
        return p["alaska"] + COMPANION_COST, f"Alaska ${p['alaska']:,} + ${COMPANION_COST} companion"
    if p.get("low") is None:
        return None, ""
    return p["low"] * 2, f"2 × ${p['low']:,}"


def decide(trip, p, obs, today):
    price, basis = tracked_price(trip, p)
    if price is None:
        return "NO DATA", "No matching flights came back today."
    to_depart = days_between(today, trip["depart"])
    if to_depart <= LAST_MINUTE_DAYS:
        return "BUY", f"{to_depart} days out; fares rarely drop from here."
    if trip.get("book_by"):
        to_deadline = days_between(today, trip["book_by"])
        if to_deadline <= DEADLINE_DAYS:
            return "BUY", (f"Book-by deadline in {max(to_deadline, 0)} days. "
                           "Take the best price available now.")
    lo, hi = p["typical"] if p.get("typical") else (None, None)
    if p.get("level") == "low" or (lo is not None and price <= lo):
        rng = f" (${lo:,}–${hi:,})" if lo is not None else ""
        return "BUY", f"${price:,} is below Google's typical range{rng}."
    seen = [o["tracked"] for o in obs if o.get("tracked") is not None]
    if basis == "cheapest":
        seen += [h[1] for h in p.get("google_history", []) if len(h) == 2]
    if len(seen) >= MIN_OBS_FOR_LOW:
        floor = min(seen)
        if price <= floor * (1 + BUY_NEAR_LOW):
            return "BUY", f"${price:,} matches the lowest price seen (${floor:,})."
        gap = price - floor
        rng = f"; typical ${lo:,}–${hi:,}" if lo is not None else ""
        return "WAIT", f"${gap:,} above the lowest seen (${floor:,}){rng}."
    rng = f" in the typical ${lo:,}–${hi:,} range" if lo is not None else ""
    return "WAIT", f"${price:,}{rng}; still building history."


# ---------- alerts ----------

def send_alert(text):
    sid, token = os.environ.get("TWILIO_SID"), os.environ.get("TWILIO_TOKEN")
    sender, to = os.environ.get("TWILIO_FROM"), os.environ.get("ALERT_TO")
    sent = False
    if sid and token and sender and to:
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        for number in [n.strip() for n in to.split(",") if n.strip()]:
            data = urllib.parse.urlencode({"From": sender, "To": number, "Body": text}).encode()
            req = urllib.request.Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                data=data, headers={"Authorization": f"Basic {auth}"})
            try:
                urllib.request.urlopen(req, timeout=30)
                sent = True
            except Exception as e:
                warn(f"Text to one number failed: {e}")
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=text.encode(),
                                     headers={"Title": "Flight Watch", "Priority": "high"})
        try:
            urllib.request.urlopen(req, timeout=30)
            sent = True
        except Exception as e:
            warn(f"Push alert failed: {e}")
    if not sent:
        note(f"Alert (no channel configured): {text}")


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--offline")
    args = ap.parse_args()

    key = os.environ.get("SERPAPI_KEY")
    if not key and not args.offline:
        error("SERPAPI_KEY secret is missing. Add it under Settings → Secrets and variables → Actions.")
        sys.exit(1)

    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-8))).date().isoformat()
    trips = load(TRIPS, {"trips": []})["trips"]
    prices = load(PRICES, {})
    offline = json.loads(Path(args.offline).read_text()) if args.offline else None

    todo = [t for t in trips if t.get("active", True)
            and t["depart"] >= today and (not args.only or t["id"] == args.only)]
    if not todo:
        note("No active trips to check.")

    failures = 0
    for trip in todo:
        tid = trip["id"]
        rec = prices.setdefault(tid, {"obs": [], "grid": None, "last_verdict": None})
        try:
            res = offline or search(trip, trip["depart"], trip.get("return"), key)
        except Exception as e:
            failures += 1
            error(f"{trip['name']}: search failed ({e}). Keeping yesterday's data.")
            continue
        save(RAW / f"{tid}.json", res)
        p = parse(res)
        if p["n_options"] == 0:
            warn(f"{trip['name']}: no flights matched (nonstop filter?).")

        price, basis = tracked_price(trip, p)
        obs = [o for o in rec["obs"] if o["date"] != today]
        verdict, reason = decide(trip, p, obs, today)
        cost, cost_note = two_person_cost(trip, p)
        obs.append({"date": today, "low": p["low"], "alaska": p["alaska"],
                    "tracked": price, "level": p["level"]})
        rec.update(obs=obs, basis=basis, latest=p, verdict=verdict, reason=reason,
                   cost_two=cost, cost_note=cost_note, checked=today)

        # +/-3 day grid: weekly, or on demand, to save quota
        grid_due = args.grid or rec.get("grid") is None or \
            dt.date.fromisoformat(today).weekday() == GRID_WEEKDAY
        if grid_due and not offline and days_between(today, trip["depart"]) > max(GRID_OFFSETS):
            rows = []
            for off in GRID_OFFSETS:
                d = (dt.date.fromisoformat(trip["depart"]) + dt.timedelta(days=off)).isoformat()
                r = (dt.date.fromisoformat(trip["return"]) + dt.timedelta(days=off)).isoformat() \
                    if trip.get("return") else None
                if d <= today:
                    continue
                try:
                    gp = parse(search(trip, d, r, key))
                    gprice, gbasis = tracked_price(trip, gp)
                    rows.append({"offset": off, "depart": d, "return": r, "price": gprice,
                                 "basis": gbasis})
                except Exception as e:
                    warn(f"{trip['name']}: grid {d} failed ({e})")
            rows.append({"offset": 0, "depart": trip["depart"], "return": trip.get("return"),
                         "price": price, "basis": basis})
            rec["grid"] = {"checked": today, "rows": sorted(rows, key=lambda x: x["offset"])}

        if verdict == "BUY" and rec.get("last_verdict") != "BUY":
            cost_txt = f"${cost:,} for two ({cost_note})" if cost else ""
            send_alert(f"BUY: {trip['name']} {trip['from']}→{trip['to']} "
                       f"{trip['depart']}{' to ' + trip['return'] if trip.get('return') else ''}. "
                       f"{cost_txt}. {reason} {p.get('url') or ''}".strip())
        rec["last_verdict"] = verdict
        note(f"{trip['name']}: {verdict} at ${price} ({basis}). {reason}")

    if todo and failures == len(todo):
        error("Every search failed. Nothing published; last good data stays live.")
        sys.exit(1)

    save(PRICES, prices)

    # page data
    out = {"meta": {"built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                    "today": today, "companion_cost": COMPANION_COST,
                    "searches_left": None if offline else searches_left(key)},
           "trips": []}
    for t in sorted(trips, key=lambda t: t["depart"]):
        rec = prices.get(t["id"], {})
        p = rec.get("latest", {})
        out["trips"].append({
            **t,
            "past": t["depart"] < today,
            "checked": rec.get("checked"),
            "verdict": rec.get("verdict", "PENDING"),
            "reason": rec.get("reason", "First check hasn't run yet."),
            "basis": rec.get("basis"),
            "cost_two": rec.get("cost_two"),
            "cost_note": rec.get("cost_note"),
            "low": p.get("low"), "alaska": p.get("alaska"),
            "level": p.get("level"), "typical": p.get("typical"),
            "url": p.get("url"), "options": p.get("options", []),
            "google_history": [[dt.datetime.fromtimestamp(h[0], dt.timezone.utc).date().isoformat(), h[1]]
                               for h in p.get("google_history", []) if len(h) == 2],
            "history": [[o["date"], o["tracked"]] for o in rec.get("obs", [])],
            "grid": rec.get("grid"),
            "days_to_depart": days_between(today, t["depart"]),
            "days_to_deadline": days_between(today, t["book_by"]) if t.get("book_by") else None,
        })
    save(OUT, out)


if __name__ == "__main__":
    main()
