"""Turn an 'Add trip' issue into a row in data/trips.json.

Reads the issue body from the ISSUE_BODY env var (GitHub issue-form markdown),
prints the new trip id to GITHUB_OUTPUT so the next step can check it.
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIPS = ROOT / "data" / "trips.json"


def fields(body):
    out, label = {}, None
    for line in body.splitlines():
        m = re.match(r"^###\s+(.*)", line)
        if m:
            label = m.group(1).strip().lower()
            out[label] = ""
        elif label is not None and line.strip():
            out[label] = (out[label] + " " + line.strip()).strip()
    return {k: ("" if v == "_No response_" else v) for k, v in out.items()}


def fail(msg):
    print(f"::error::{msg}")
    Path(os.environ.get("GITHUB_OUTPUT", "/dev/null")).open("a").write(f"error={msg}\n")
    sys.exit(1)


def date(v, name, required=True):
    if not v:
        if required:
            fail(f"{name} is required.")
        return None
    try:
        return dt.date.fromisoformat(v.strip()).isoformat()
    except ValueError:
        fail(f"{name} must look like 2026-11-25 (got '{v}').")


def main():
    f = fields(os.environ.get("ISSUE_BODY", ""))
    code = lambda v, n: v.strip().upper() if re.fullmatch(r"[A-Za-z]{3}", v.strip() or "") \
        else fail(f"{n} must be a 3-letter airport code (got '{v}').")
    trip = {
        "name": f.get("trip name") or "Trip",
        "from": code(f.get("from", ""), "From"),
        "to": code(f.get("to", ""), "To"),
        "depart": date(f.get("depart date", ""), "Depart date"),
        "return": date(f.get("return date", ""), "Return date", required=False),
        "nonstop": f.get("nonstop only", "Yes").lower().startswith("y"),
        "companion": f.get("using a companion fare?", "No").lower().startswith("y"),
        "book_by": date(f.get("book by", ""), "Book by", required=False),
        "active": True,
    }
    if trip["return"] and trip["return"] < trip["depart"]:
        fail("Return date is before the depart date.")
    if trip["depart"] < dt.date.today().isoformat():
        fail("Depart date is in the past.")

    data = json.loads(TRIPS.read_text()) if TRIPS.exists() else {"trips": []}
    base = f"{trip['from']}-{trip['to']}-{trip['depart']}".lower()
    tid, n = base, 2
    while any(t["id"] == tid for t in data["trips"]):
        tid, n = f"{base}-{n}", n + 1
    trip = {"id": tid, **trip}
    data["trips"].append(trip)
    TRIPS.write_text(json.dumps(data, indent=1) + "\n")
    Path(os.environ.get("GITHUB_OUTPUT", "/dev/null")).open("a").write(f"id={tid}\n")
    print(f"::notice::Added {trip['name']} ({tid})")


if __name__ == "__main__":
    main()
