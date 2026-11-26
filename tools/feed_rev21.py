#!/usr/bin/env python3
"""feed_rev21.py: feed contract revision 2.1 for Noisefloor (feed-contract migration step 4.4, Tom's yes 20 Nov 2026).

feed_v2.build() states each item's subject_id, signal and any change it knows itself. finish() adds what follows from
the item as built: event times, countries by overlap, sea areas, place basis, source lanes, and the header's health.

Decisions (Tom, 20 Nov 2026, "yes to defaults"):
- A jamming event's subject is the res-2 region at its centre, so an event recurring over one area is one subject.
  Since ideas#118, tools/event_subjects.py then lets an event that shares regions with an
  earlier one keep that subject while its centre moves; the centre key is for an event with no earlier ground.
- last_change comes from the kit's history log, kept on the release `feed-history` (tools/feed_history.py).
- Countries are the union of the kit's overlap helper and the sampled tags: islands the thinned outlines miss stay,
  and coasts that a box clips come in.

The run step (`python tools/feed_history.py run`) fills last_change after the build; a feed without it is still valid.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "doctrine", "kit", "python"))
from tic_doctrine import geo  # noqa: E402

FRESH_DAYS = 2      # the archives post the next morning: up to 2 days behind is fresh
LATE_DAYS = 4       # up to 4 is late, older is stale


def cell_at(lat, lon, res):
    """The H3 cell at a point, or None without one."""
    if lat is None or lon is None:
        return None
    import h3
    return h3.latlng_to_cell(lat, lon, res)


def subject(kind, key, fallback):
    """noisefloor:kind:key, or the item's own id when the key is unknown (an id is always a valid subject)."""
    return f"noisefloor:{kind}:{key}" if key else fallback


def signal(name, value, unit, expected=None, baseline_n=None):
    """The one number an anomaly's tier rests on, tail high. None when the value is missing."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    out = {"name": name, "value": value, "unit": unit, "tail": "high"}
    if isinstance(expected, (int, float)):
        out["expected"] = expected
    if isinstance(baseline_n, int) and baseline_n > 0:
        out["baseline_n"] = baseline_n
    return out


def _z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _t(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def event_times(p):
    """A measured window. Hour precision: each time is the start of its hour and covers it, so the end is the start of
    the last hour (a period ends on the hour after). Every other item covers its whole UTC day."""
    period = p.get("period")
    if period:
        last = _t(period["end"]) - timedelta(hours=1)
        p["event_start"], p["event_end"] = period["start"], _z(max(last, _t(period["start"])))
        p["event_time_precision"] = "hour"
    else:
        day = p["data_as_of"][:10] + "T00:00:00Z"
        p["event_start"], p["event_end"] = day, day
        p["event_time_precision"] = "day"


def lane_of(item_id):
    if item_id.startswith("noisefloor-spoof-"):
        return "spoofing"
    if item_id.startswith("noisefloor-milair-"):
        return "milair"
    return None


def lane_entry(day, now, label):
    """One lane of the header's health, from the newest day this build holds for it."""
    at = _z(now)
    if not day:
        return {"state": "failing", "checked_at": at, "last_ok": None, "last_error": "no file for this lane in this build",
                "failures": 1, "detail": f"{label}: nothing read"}
    behind = (now.date() - datetime.strptime(day, "%Y-%m-%d").date()).days
    state = "fresh" if behind <= FRESH_DAYS else "late" if behind <= LATE_DAYS else "stale"
    as_of = f"{day}T00:00:00Z"
    return {"state": state, "checked_at": at, "last_ok": at if state != "stale" else as_of, "last_error": None,
            "failures": 0, "data_as_of": as_of, "detail": f"{label}: newest day {day}, {behind} days behind"}


def health(board, milair, now):
    sp = board.get("spoofing") or {}
    spoof_days = [x.get("day") for x in (sp.get("new_places"), sp.get("place_levels"), sp.get("region_levels"))
                  if x and x.get("day")]
    sw = board.get("swx") or {}
    return {
        "adsblol-archive": lane_entry((board.get("freshness") or {}).get("aircraft_day"), now, "aircraft day"),
        "spoofing": lane_entry(max(spoof_days) if spoof_days else None, now, "spoofing day"),
        "cosmic2-ro": lane_entry((sw.get("limb") or {}).get("day"), now, "COSMIC-2 limb S4 day"),
        "cors-igs": lane_entry((sw.get("roti") or {}).get("day"), now, "ground ROTI day"),
        "milair": lane_entry((milair or {}).get("day"), now, "military air day"),
    }


def finish(feed, board, milair, now):
    """Add the 2.1 fields to every item and the header."""
    cache = {}
    for f in feed["features"]:
        p, g = f["properties"], f.get("geometry")
        p.setdefault("subject_id", p["id"])
        event_times(p)
        if p.get("last_change") and p["last_change"] != "none":
            p.setdefault("last_change_at", p["event_start"])
        name = lane_of(p["id"])
        if name:
            p["sources"] = [{**p["sources"][0], "lane": name}] + list(p["sources"][1:])
        if g:
            k = repr(g)
            if k not in cache:
                cache[k] = (geo.countries_overlapping(g), geo.sea_areas_for_geometry(g))
            over, seas = cache[k]
            p["countries"] = sorted(set(p.get("countries") or []) | set(over))
            p["sea_areas"] = list(seas)
        if p.get("countries"):
            p["place_basis"] = "location"
    feed["health"] = health(board, milair, now)
    return feed
