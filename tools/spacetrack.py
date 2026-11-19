#!/usr/bin/env python3
"""spacetrack.py: the Space-Track client Sentinel uses for gp_history element sets (tools/sentinel_gnss.py).

Moved from tools/geo_region.py on 18 Nov 2026, when the GEO page moved to Orbit (orbit.theintelligence.company/geo).
Noisefloor makes no gp (current catalogue) query any more; Orbit makes the one gp query on the shared account.

Data: Space-Track, USSPACECOM basic SSA data (blanket approval to redistribute and to publish analysis, with citation:
"Orbital data: USSPACECOM (space-track.org)"). Account: SPACETRACK_USER and SPACETRACK_PASSWORD from the environment
or, on Windows, the user variables; never printed. API rules (space-track.org/documentation, read 27 Oct 2026): under
30 requests a minute and 300 an hour; gp_history once per object over its lifetime, stored and never downloaded again.
"""
import http.cookiejar
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = "https://www.space-track.org"
CITE = "Orbital data: USSPACECOM (space-track.org)"
UA = "noise-floor (github.com/metacog-osint/noise-floor)"
ELSET = ["NORAD_CAT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER",
         "MEAN_ANOMALY", "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT", "ELEMENT_SET_NO", "REV_AT_EPOCH"]


def num(x, kind=float):
    if x is None or x == "":
        return None
    try:
        return kind(x)
    except (TypeError, ValueError):
        return None


def elset_row(g):
    """A Space-Track GP/GP_history record (all strings) -> the stored element set."""
    return {"norad": num(g.get("NORAD_CAT_ID"), int), "epoch": g.get("EPOCH"), "n": num(g.get("MEAN_MOTION")),
            "e": num(g.get("ECCENTRICITY")), "i": num(g.get("INCLINATION")), "raan": num(g.get("RA_OF_ASC_NODE")),
            "argp": num(g.get("ARG_OF_PERICENTER")), "M": num(g.get("MEAN_ANOMALY")), "bstar": num(g.get("BSTAR")),
            "ndot": num(g.get("MEAN_MOTION_DOT")), "nddot": num(g.get("MEAN_MOTION_DDOT")),
            "elset": num(g.get("ELEMENT_SET_NO"), int), "rev": num(g.get("REV_AT_EPOCH"), int)}


def history_path(ids, since, until):
    return (f"class/gp_history/NORAD_CAT_ID/{','.join(str(i) for i in ids)}/EPOCH/{since}--{until}"
            f"/orderby/NORAD_CAT_ID%20asc,EPOCH%20asc/predicates/{','.join(ELSET)}/format/json")


def credentials():
    user, pw = os.environ.get("SPACETRACK_USER"), os.environ.get("SPACETRACK_PASSWORD")
    if (not user or not pw) and sys.platform == "win32":
        import winreg                               # user variables set after this process started

        def get(k, name):
            try:
                return winreg.QueryValueEx(k, name)[0]
            except FileNotFoundError:
                return None
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            user, pw = user or get(k, "SPACETRACK_USER"), pw or get(k, "SPACETRACK_PASSWORD")
    if not user or not pw:
        raise SystemExit("SPACETRACK_USER / SPACETRACK_PASSWORD not set")
    return user, pw


class SpaceTrack:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.op.addheaders = [("User-Agent", UA)]
        self.requests = 0

    def __enter__(self):
        user, pw = credentials()
        body = urllib.parse.urlencode({"identity": user, "password": pw}).encode()
        with self.op.open(BASE + "/ajaxauth/login", body, timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
        if r.status != 200 or "Failed" in text:
            raise SystemExit("Space-Track login failed (check the account; the password is not shown)")
        return self

    def __exit__(self, *exc):
        try:
            self.op.open(BASE + "/ajaxauth/logout", timeout=30).read()
        except OSError:
            pass

    def query(self, path):
        """GET /basicspacedata/query/<path>; stop on anything but a JSON list (the rules say to stop, not retry)."""
        self.requests += 1
        with self.op.open(BASE + "/basicspacedata/query/" + path, timeout=600) as r:
            if r.status != 200:
                raise SystemExit(f"Space-Track returned {r.status}; stopping")
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, list):
            raise SystemExit(f"Space-Track error: {str(data)[:300]}")
        return data
