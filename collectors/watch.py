#!/usr/bin/env python3
"""watch.py — daily trigger pollers: official warnings, planned GPS tests, user reports, space weather, GEO channel
listings, Chayka status and sun transit. Ported from Tom's emso-watch trigger board (14 Oct 2026 live fixes) to run
once a day on this PC from collectors/run_daily.cmd, writing a private digest. No phone pushes.

Each trigger is a lead for triage, not a finding, and carries a grade:
  WARNING  an official body issued a notice (navigational warning, planned GPS test, maritime advisory)
  EFFECT   something was reported or measurably changed (GPS user report, GEO channel removal)
  NATURAL  space-weather alert: rule it out before calling anything deliberate

Sources (licence and use: registry/sources.csv, verified 22 Oct 2026)
  NOAA SWPC alerts            noaa-swpc          ingest         ALERT/WARNING messages since the last run
  NGA MSI broadcast warnings  nga-msi            ingest         in-force warnings mentioning GNSS, jamming, AIS, radar...
  USCG NAVCEN GPS tests       navcen-gps-tests   ingest         planned GPS test schedule (PDF): new or revised tests
  USCG NAVCEN user reports    navcen-reports     ingest         GPS problem reports (GUIDE table): new and updated
  UKMTO warnings/advisories   ukmto              ingest (OGL)   new products; JMIC notes are cite-only (link, no copy)
  KingOfSat                   kingofsat          private-watch  removals at watched GEO slots; hourly at most; never
                                                                the robots-disallowed paths
  Chayka (DF6NM DL0AO)        df6nm-dl0ao        private-watch  status only (collectors/chayka.py); 15 min at most
  Sun transit                 (computed)                        windows for watched receiver/GEO pairs, next 48 h,
                                                                using tools/sun_transit.py geometry
Not ported: IODA (ask first), Cloudflare Radar and GPSJam (visual comparison only), ntfy pushes (need Tom's OK).

Config (private, gitignored): private/watch/pollers.json holds the watch lists (KingOfSat slots and watched channels,
sun-transit pairs, watch countries). A source whose list is missing reports SKIP; the others still run.

First run: UKMTO and KingOfSat list their back catalogue, so that run is recorded silently as a baseline; NAVCEN user
reports older than --since-days are baselined too. Every trigger fires once (ids kept in state.json for 400 days).

Outputs (all gitignored)
  data/raw/watch/YYYY-MM-DD/   raw responses (+ index.jsonl: url, fetched_at, sha256; unchanged bodies aren't re-stored)
  data/watch/alerts.jsonl      every new trigger, append-only
  data/watch/state.json        seen ids, source health, throttles, NAVCEN report revisions
  data/watch/navcen_gps_tests.json   the current NAVCEN test schedule, parsed
  data/watch/chayka/           Chayka rows and status (see collectors/chayka.py)
  data/watch/digest_YYYY-MM-DDTHHMMZ.md

Usage
  python collectors/watch.py                     # all sources
  python collectors/watch.py --only nga,ukmto    # some sources (keys: see SOURCES)
"""
import argparse, hashlib, html, io, json, os, re, sys, traceback, urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG = os.path.join(ROOT, "private", "watch", "pollers.json")
OUT = os.path.join(ROOT, "data", "watch")
RAW = os.path.join(ROOT, "data", "raw", "watch")
UA = "noise-floor watch pollers (research; daily)"
CENTRAL = ZoneInfo("America/Chicago")
SEEN_DAYS = 400

for _s in (sys.stdout, sys.stderr):   # Windows consoles default to a legacy code page
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class Skip(Exception):
    """Source not run (no config, optional dependency missing)."""


class Stale(Exception):
    """Source ran but its data is old or its receiver is faulty."""


class Throttled(Exception):
    """Polled too recently for the source's courtesy limit; keep the last status."""


def http_get(url, headers, timeout):
    """GET; any status other than 200 is an error (urllib raises on 4xx/5xx and follows redirects)."""
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status} from {url}")
        return r.read()


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%MZ")


def text_of(h):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", h or "")).split())


class Ctx:
    """Per-run context: clock, state, private config, raw archive and fetching."""

    def __init__(self, now, state, cfg, raw_dir, out_dir, opener=http_get, chayka_fetcher=None):
        self.now, self.state, self.cfg, self.raw_dir, self.out_dir = now, state, cfg, raw_dir, out_dir
        self.opener, self.chayka_fetcher = opener, chayka_fetcher
        self.panels, self.notes = {}, {}

    def get(self, url, source, ext, accept="*/*", timeout=45):
        body = self.opener(url, {"User-Agent": UA, "Accept": accept}, timeout)
        sha = hashlib.sha256(body).hexdigest()
        d = os.path.join(self.raw_dir, self.now.strftime("%Y-%m-%d")); os.makedirs(d, exist_ok=True)
        last = self.state.setdefault("raw", {}).get(url) or {}
        rec = {"url": url, "fetched_at": self.now.isoformat(), "sha256": sha, "bytes": len(body), "source": source}
        if last.get("sha256") == sha:
            rec.update(unchanged=True, file=last["file"])   # same bytes as last time: index only
        else:
            name = f"{self.now:%H%M%S}_{source}_{sha[:12]}.{ext}"
            open(os.path.join(d, name), "wb").write(body)
            rec["file"] = f"{self.now:%Y-%m-%d}/{name}"
            self.state["raw"][url] = {"sha256": sha, "file": rec["file"]}
        with open(os.path.join(d, "index.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        return body

    def json(self, url, source, timeout=45):
        return json.loads(self.get(url, source, "json", "application/json", timeout).decode("utf-8"))

    def html(self, url, source, timeout=45):
        return self.get(url, source, "html", "text/html", timeout).decode("utf-8", "replace")

    def due(self, name, minutes):
        """Courtesy throttle: raise Throttled if `name` was fetched within `minutes`; else record this attempt."""
        lf = self.state.setdefault("last_fetch", {})
        if lf.get(name) and self.now - datetime.fromisoformat(lf[name]) < timedelta(minutes=minutes):
            raise Throttled(f"polled within the last {minutes} min")
        lf[name] = self.now.isoformat()

    def first(self, label):
        return not self.state["health"].get(label, {}).get("last_ok")

    def trig(self, source, grade, title, detail="", url="", when=None, key=None, **extra):
        tid = hashlib.sha1(f"{source}|{key or title}".encode()).hexdigest()[:16]
        return {"id": tid, "source": source, "grade": grade, "title": title, "detail": (detail or "")[:600], "url": url,
                "event_time": when or iso(self.now), "first_seen": iso(self.now), **extra}


# ---------------- NOAA SWPC ----------------
def src_swpc(ctx):
    msgs = ctx.json("https://services.swpc.noaa.gov/products/alerts.json", "swpc")
    if not isinstance(msgs, list):
        raise ValueError(f"SWPC: unexpected shape {type(msgs).__name__}")
    last = ctx.state["health"].get("NOAA SWPC", {}).get("last_ok_iso")
    gap = (ctx.now - datetime.fromisoformat(last) + timedelta(hours=2)) if last else timedelta(0)
    since = ctx.now - min(timedelta(days=7), max(timedelta(hours=36), gap))
    out = []
    for m in msgs:
        t = datetime.strptime(m["issue_datetime"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if t < since:
            continue
        msg = m.get("message", "")
        head = next((l.strip() for l in msg.splitlines() if l.strip().startswith(("ALERT", "WARNING", "WATCH", "EXTENDED WARNING"))), "")
        if not head.startswith(("ALERT", "WARNING")):
            continue   # alerts and warnings only; watches, extensions and summaries are skipped
        out.append(ctx.trig("NOAA SWPC", "NATURAL", head[:140], " ".join(msg.split())[:500],
                            "https://www.swpc.noaa.gov/products/alerts-watches-and-warnings", iso(t),
                            key=f'{m.get("product_id")}|{m["issue_datetime"]}'))
    return out


# ---------------- NGA MSI ----------------
# RADAR alone matched "radar reflectors" on buoys and barriers in the first live run (14 Oct 2026)
MSI_KEYWORDS = re.compile(r"\b(GPS|GNSS|GLONASS|JAMM\w*|SPOOF\w*|INTERFERENCE|AIS|LORAN|CHAYKA|RADAR(?! REFLECTOR)|"
                          r"SATELLITE|INMARSAT|IRIDIUM)\b", re.I)


def dtg_iso(s):
    """NGA issueDate is a date-time group, e.g. '101133Z MAY 2024' -> '2024-05-10T11:33Z'."""
    try:
        return datetime.strptime(s.strip(), "%d%H%MZ %b %Y").strftime("%Y-%m-%dT%H:%MZ")
    except (ValueError, AttributeError):
        return (s or "")[:16]


NGA_AREAS = {"4": "NAVAREA IV", "12": "NAVAREA XII", "A": "HYDROLANT", "P": "HYDROPAC", "C": "HYDROARC"}
# NAVAREA IV and XII issue warnings every day. On 26 Oct 2026 the API's newest in-force warning dated from 10 May 2024
# (its own latest-warning endpoint agreed), so a feed with nothing newer than this is reported as an error, not OK.
NGA_STALE_DAYS = 30


def src_nga(ctx):
    d = ctx.json("https://msi.nga.mil/api/publications/broadcast-warn?output=json&status=A", "nga", timeout=60)
    items = d.get("broadcast-warn") if isinstance(d, dict) else d
    if not isinstance(items, list):
        raise ValueError(f"NGA MSI: unexpected shape {list(d)[:6] if isinstance(d, dict) else type(d)}")
    issued = [t for t in (dtg_iso(w.get("issueDate")) for w in items) if re.match(r"\d{4}-\d\d-\d\dT", t)]
    if issued and max(issued) < (ctx.now - timedelta(days=NGA_STALE_DAYS)).strftime("%Y-%m-%dT%H:%MZ"):
        raise ValueError(f"NGA MSI: feed looks frozen: the newest of {len(items)} in-force warnings was issued "
                         f"{max(issued)}")
    out = []
    for w in items:
        text = w.get("text") or w.get("msgText") or ""
        if not MSI_KEYWORDS.search(text):
            continue
        area = str(w.get("navArea", ""))
        ident = f'{area} {w.get("msgNumber", "")}/{w.get("msgYear", "")}'.strip()
        name = f'{NGA_AREAS.get(area, "NAVAREA " + area)} {w.get("msgNumber", "")}/{w.get("msgYear", "")}'
        sub = w.get("subregion")
        flat = " ".join(text.split())
        out.append(ctx.trig("NGA MSI", "WARNING", f"{name}{f' (subregion {sub})' if sub else ''}: {flat[:120]}", flat,
                            "https://msi.nga.mil/NavWarnings", dtg_iso(w.get("issueDate")), key=ident))
    return out


# ---------------- USCG NAVCEN: planned GPS tests (PDF) ----------------
NAVCEN_TESTS = "https://navcen.uscg.gov/sites/default/files/pdf/gps/gpsnotices/GPS_Interference.pdf"
# pypdf reads each table row right to left: coordinates, range @50 ft, range @10,000 ft, end, start, location, GPS#, name
# e.g. "32-06-58N 106-08-55W92NM120NM01 Oct14 SepNewman, TX GPS 26-02MCGRNM" (layout of 28 Sep 2026)
TEST_RE = re.compile(r"(?P<lat>\d{1,2}-\d\d-\d\d(?:\.\d+)?)\s*(?P<ns>[NS])\s*(?P<lon>\d{1,3}-\d\d-\d\d(?:\.\d+)?)\s*(?P<ew>[EW])\s*"
                     r"(?P<r50>\d+(?:\.\d+)?)\s*NM\s*(?P<r10k>\d+(?:\.\d+)?)\s*NM\s*"
                     r"(?P<end>\d{1,2}\s*[A-Za-z]{3})\s*(?P<start>\d{1,2}\s*[A-Za-z]{3})\s*"
                     r"(?P<loc>[^\n]+?)\s*GPS\s*#?\s*(?P<gps>\d\d-\d{2,3})\s*(?P<name>[A-Za-z0-9_-]+)")
UPDATE_RE = re.compile(r"LAST\s+UPDATE\s*:?\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", re.I)


def dms(s, hemi):
    parts = [float(x) for x in s.split("-")]
    v = parts[0] + parts[1] / 60 + parts[2] / 3600
    return round(-v if hemi in "SW" else v, 5)


def navcen_tests_parse(text):
    """Schedule text -> (last_update date, [test dicts]). Dates carry no year: years come from the update date."""
    m = UPDATE_RE.search(text)
    if not m:
        raise ValueError("NAVCEN tests: no 'LAST UPDATE' date found; layout may have changed")
    y = int(m.group(3)); y += 2000 if y < 100 else 0
    upd = date(y, int(m.group(1)), int(m.group(2)))

    def day(s):
        d = datetime.strptime(" ".join(s.split()) + f" {upd.year}", "%d %b %Y").date()
        return d.replace(year=d.year + 1) if d < upd - timedelta(days=120) else d

    tests = []
    for t in TEST_RE.finditer(text):
        start, end = day(t["start"]), day(t["end"])
        if end < start:
            end = end.replace(year=end.year + 1)
        tests.append({"name": t["name"], "gps": f"GPS {t['gps']}", "location": " ".join(t["loc"].split()),
                      "start": start.isoformat(), "end": end.isoformat(),
                      "lat": dms(t["lat"], t["ns"]), "lon": dms(t["lon"], t["ew"]),
                      "coords": f"{t['lat']}{t['ns']} {t['lon']}{t['ew']}",
                      "range_nm_50ft": float(t["r50"]), "range_nm_10000ft": float(t["r10k"])})
    return upd, tests


def pdf_text(body):
    try:
        import pypdf
    except ImportError as e:
        raise Skip(f"{e} (pip install -r requirements.txt)")
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(body)).pages)


def src_navcen_tests(ctx):
    upd, tests = navcen_tests_parse(pdf_text(ctx.get(NAVCEN_TESTS, "navcen_tests", "pdf", "application/pdf", 60)))
    if not tests:
        raise ValueError("NAVCEN tests: schedule parsed to 0 rows; layout may have changed")
    json.dump({"source": NAVCEN_TESTS, "last_update": upd.isoformat(), "fetched_at": ctx.now.isoformat(), "tests": tests},
              open(os.path.join(ctx.out_dir, "navcen_gps_tests.json"), "w", encoding="utf-8"), indent=1)
    today = ctx.now.date().isoformat()
    soon = (ctx.now.date() + timedelta(days=14)).isoformat()
    ctx.panels["navcen_tests"] = {"last_update": upd.isoformat(),
                                  "rows": [t for t in tests if t["end"] >= today and t["start"] <= soon]}
    known = ctx.state.setdefault("navcen_tests_known", {})   # GPS numbers repeat across ranges: key by name + number
    out = []
    for t in tests:
        key = "|".join(str(t[k]) for k in ("name", "gps", "start", "end", "coords", "range_nm_50ft", "range_nm_10000ft"))
        revised = known.get(f"{t['name']}|{t['gps']}") not in (None, key)
        known[f"{t['name']}|{t['gps']}"] = key
        tr = ctx.trig("USCG NAVCEN", "WARNING",
                      f"{'Revised: ' if revised else ''}planned GPS test {t['name']} ({t['gps']}), {t['location']}: "
                      f"{t['start']} to {t['end']}",
                      f"Centre {t['coords']}; range {t['range_nm_50ft']:g} NM at 50 ft, {t['range_nm_10000ft']:g} NM at "
                      f"10,000 ft (NAVCEN schedule, last update {upd}). Daily times are in the FAA flight advisory "
                      "or NOTAM.", NAVCEN_TESTS, t["start"], key=key)
        if t["end"] < today:
            tr["baseline"] = True   # already over when first seen: remembered, not listed
        out.append(tr)
    return out


# ---------------- USCG NAVCEN: GPS user problem reports (GUIDE table) ----------------
NAVCEN_REPORTS = "https://navcen.uscg.gov/guide-tool"   # /gps-problem-report-status redirects here (22 Oct 2026)
ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.S | re.I)


def navcen_reports_parse(page):
    """GUIDE table -> [{index, date, location, type, user, navcen, cause, closed}]. Commented-out cells are dropped:
    only what NAVCEN shows is used."""
    i = page.find('id="gps_pr_table"')
    if i < 0:
        raise ValueError("NAVCEN reports: table gps_pr_table not found; layout may have changed")
    body = re.sub(r"<!--.*?-->", "", page[i: page.find("</table>", i)], flags=re.S)
    out = []
    for row in ROW_RE.findall(body):
        c = [text_of(x) for x in CELL_RE.findall(row)]
        if len(c) < 7 or not c[0].isdigit():
            continue
        try:
            d = datetime.strptime(c[1], "%m/%d/%Y").date().isoformat()
        except ValueError:
            d = c[1]
        user, _, nav = c[4].partition("NAVCEN:")
        out.append({"index": int(c[0]), "date": d, "location": c[2], "type": c[3],
                    "user": user.replace("USER:", "", 1).strip(), "navcen": nav.strip(), "cause": c[5], "closed": c[6]})
    return out


def src_navcen_reports(ctx, since_days=14):
    reps = navcen_reports_parse(ctx.html(NAVCEN_REPORTS, "navcen_reports", timeout=60))
    if not reps:
        raise ValueError("NAVCEN reports: table parsed to 0 rows")
    ctx.notes["USCG NAVCEN reports"] = len(reps)
    first = ctx.first("USCG NAVCEN reports")
    floor = (ctx.now.date() - timedelta(days=since_days)).isoformat()
    rev = ctx.state.setdefault("navcen_reports_rev", {})
    out = []
    for r in reps:
        sig = hashlib.sha1(f"{r['cause']}|{r['closed']}|{r['navcen']}".encode()).hexdigest()[:12]
        prev = rev.get(str(r["index"]))
        rev[str(r["index"])] = sig
        what = f"{r['user'] or 'GPS problem'} ({r['type']})"
        detail = (f"Cause: {r['cause'] or 'open'}" + (f", closed {r['closed']}" if r["closed"] else "")
                  + f". User: {r['user']}. NAVCEN: {r['navcen'] or 'no assessment yet'} (User reports are unverified.)")
        if prev is None:
            t = ctx.trig("USCG NAVCEN reports", "EFFECT", f"Report {r['index']}, {r['location']}: {what}", detail,
                         NAVCEN_REPORTS, r["date"], key=str(r["index"]))
            if first and r["date"] < floor:
                t["baseline"] = True   # back catalogue: remembered, not listed
            out.append(t)
        elif prev != sig:
            out.append(ctx.trig("USCG NAVCEN reports", "EFFECT",
                                f"Report {r['index']} updated, {r['location']}: cause {r['cause'] or 'open'}", detail,
                                NAVCEN_REPORTS, r["date"], key=f"{r['index']}|{sig}"))
    return out


# ---------------- UKMTO ----------------
# ukmto.org renders its product lists client-side from this JSON API (found 14 Oct 2026). Type ids are productType.id in
# the page's __NEXT_DATA__ on /ukmto-products/warnings and /advisories. Licence: OGL (credit in the digest).
UKMTO_API = "https://sccd.royalnavy.mod.uk/api/ukmto"
UKMTO_TYPES = {"Warning": "19089a80-069d-4974-8899-2a9802bb7cdf", "Advisory": "30ec4eba-f133-4df6-b7bb-9a2328b64ec6"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def src_ukmto(ctx):
    ctx.due("ukmto", 30)
    # this month, plus last month during the first week so items near the boundary aren't missed
    periods = sorted({(t.year, MONTHS[t.month - 1]) for t in (ctx.now, ctx.now - timedelta(days=7))})
    out = []
    for kind, type_id in UKMTO_TYPES.items():
        counts = {}
        for year, month in periods:
            if year not in counts:
                counts[year] = ctx.json(f"{UKMTO_API}/products-count/{type_id}/{year}", "ukmto")
                if not isinstance(counts[year], list):
                    raise ValueError(f"UKMTO {kind} counts: unexpected shape {type(counts[year]).__name__}")
            m = next((x for x in counts[year] if x.get("name") == month), None)
            if not m or not m.get("productItemCount"):
                continue
            for p in ctx.json(f"{UKMTO_API}/products/{m['id']}", "ukmto") or []:
                ref, loc, pdf = p.get("reference") or p.get("name") or "", p.get("location") or "", p.get("pdfUrl") or ""
                jmic = "jmic" in (ref + pdf).lower()
                out.append(ctx.trig("UKMTO", "WARNING", f"UKMTO {kind}: {ref}" + (f", {loc}" if loc else ""),
                                    ("JMIC advisory notes carry the multinational GNSS/AIS interference picture for the Red Sea, "
                                     "Gulf of Aden, Arabian Gulf and Hormuz; cite with date and link, don't republish. "
                                     if jmic else "") + "Open the product for the area and times.",
                                    pdf or "https://www.ukmto.org/recent-incidents",
                                    (p.get("issueDate") or "")[:16] + "Z" if p.get("issueDate") else None,
                                    key=p.get("id") or pdf))
    return out


# ---------------- KingOfSat (private watch) ----------------
POS_RE = re.compile(r"^(\d{1,3}(?:\.\d)?)\s*°\s*([EW])\b")
FREQ_RE = re.compile(r"\b(\d{4,5}\.\d{1,2})\b(?:\s*MHz)?\s*([HVLR])?\b")
DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)")
KOS = "https://en.kingofsat.net"
KOS_DISALLOWED = ("channelhistory.php", "tp.php", "find", "detail")   # robots.txt, checked 22 Oct 2026


def kos_get(ctx, path):
    if any(x in path for x in KOS_DISALLOWED):
        raise ValueError(f"KingOfSat: {path} is disallowed by robots.txt")
    return ctx.html(KOS + path, "kingofsat")


def kos_parse(page):
    """KingOfSat 'removed'/'new' listing -> [{pos, sat, freq, name, date}]. Transponder rows carry the position
    (e.g. '13.0°E'); channel rows follow until the next one."""
    out, cur = [], None
    for row in ROW_RE.findall(page):
        cells = [text_of(c) for c in CELL_RE.findall(row)]
        if not cells:
            continue
        pi = next((i for i, c in enumerate(cells) if POS_RE.match(c)), None)
        if pi is not None:
            m = POS_RE.match(cells[pi])
            fm = next((FREQ_RE.search(c) for c in cells[pi + 1:pi + 5] if FREQ_RE.search(c)), None)
            cur = {"pos": f"{float(m.group(1)):.1f}{m.group(2)}", "sat": cells[pi + 1] if pi + 1 < len(cells) else "",
                   "freq": (fm.group(1) + (" " + fm.group(2) if fm.group(2) else "")) if fm else ""}
            continue
        if cur and len(cells) >= 5:
            name = next((c for c in cells if c and not re.fullmatch(r"[\d\s.,/:%-]+", c)), "")
            dm = DATE_RE.findall(" ".join(cells))
            if name:
                out.append({**cur, "name": name, "date": dm[-1] if dm else ""})
    return out


def src_kingofsat(ctx):
    kc = (ctx.cfg or {}).get("kingofsat") or {}
    if not kc.get("slots"):
        raise Skip("no kingofsat.slots in private/watch/pollers.json")
    slots = set(kc["slots"])
    watch = re.compile("|".join(kc.get("watch") or []) or r"(?!)", re.I)
    ctx.due("kingofsat", 60)   # courtesy: hourly at most
    removed = kos_parse(kos_get(ctx, "/removed"))
    if not removed:
        raise ValueError("KingOfSat 'removed' page parsed to 0 rows; markup may have changed")
    try:
        added = kos_parse(kos_get(ctx, "/new"))
    except Exception:
        added = []
    recent = {(ctx.now.date() - timedelta(days=k)).isoformat() for k in range(3)}
    groups = {}
    for r in removed:
        if r["pos"] not in slots or (r["date"] and r["date"] not in recent):
            continue
        groups.setdefault((r["pos"], r["sat"], r["freq"], r["date"]), []).append(r["name"])
    out = []
    for (pos, sat, freq, d), names in groups.items():
        moved = sorted({f'{x["name"]} -> {x["pos"]}' for x in added if x["name"] in names and x["pos"] != pos})
        watched = [n for n in names if watch.search(n)]
        out.append(ctx.trig("KingOfSat", "EFFECT",
                            f"{'WATCHED · ' if watched else ''}{pos} {sat}: {len(names)} channel(s) removed from {freq or 'n/k'}",
                            f"Removed {d or 'recently'}: {', '.join(names[:12])}{' …' if len(names) > 12 else ''}. "
                            + (f"Re-listed elsewhere: {'; '.join(moved[:6])}. " if moved else "")
                            + "A listing change, not a reception report: operator action, contract end, or a move to "
                            "escape jamming. Check for operator action before anything else.",
                            f"{KOS}/pos-{pos.replace('.0', '')}", d or None, key=f"{pos}|{freq}|{d}|{len(names)}"))
    return out


# ---------------- Chayka (private watch; status only) ----------------
def src_chayka(ctx):
    try:
        import chayka
    except ImportError as e:
        raise Skip(f"{e} (numpy and pillow are needed)")
    ctx.due("chayka", 15)   # courtesy: DF6NM's server, 15 min at most
    kw = {"fetcher": ctx.chayka_fetcher} if ctx.chayka_fetcher else {}
    st = chayka.run(os.path.join(ctx.out_dir, "chayka"), now=ctx.now, **kw)
    ctx.panels["chayka"] = st
    ctx.notes["Chayka (DL0AO)"] = st["new_rows"]
    age = ctx.now - datetime.fromisoformat(st["image_top_row_utc"].replace("Z", "+00:00"))
    if age > timedelta(hours=2):
        raise Stale(f"newest image row is {age.total_seconds() / 3600:.1f} h old (grabber not updating?)")
    if st.get("receiver_ok") is False:
        raise Stale("Anthorn and most Chayka tracks dark at DL0AO: receiver or display fault likely; flags suppressed")
    return []


# ---------------- Sun transit (computed) ----------------
def sun_windows(pairs, now, dish_m=0.9, freq_ghz=11.7, hours=48):
    """Windows ending after now and starting within `hours`, from tools/sun_transit.py geometry. Outage threshold =
    half the dish's 3 dB beamwidth (70 lambda / D) plus the sun's radius, as in the emso-watch planner."""
    if os.path.join(ROOT, "tools") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
    import sun_transit as ST
    thresh = 70 * (299792458.0 / (freq_ghz * 1e9)) / dish_m / 2 + 0.267
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for p in pairs:
        enu, el = ST.sat_direction(p["lat"], p["lon"], p["slot"])
        if el <= 0:
            continue
        for k in range(-1, hours // 24 + 2):
            w = ST.day_outage(p["lat"], p["lon"], enu, day0 + timedelta(days=k), thresh)
            if w and w["end"] >= now and w["start"] <= now + timedelta(hours=hours):
                out.append({**{x: p[x] for x in ("receiver", "country", "satellite", "slot")}, "elev": round(el, 1),
                            "start": w["start"], "end": w["end"], "peak": w["peak"], "minutes": round(w["minutes"]),
                            "active_now": w["start"] <= now <= w["end"]})
    return sorted(out, key=lambda w: w["peak"])


def src_sun(ctx):
    sc = (ctx.cfg or {}).get("sun_transit") or {}
    if not sc.get("pairs"):
        raise Skip("no sun_transit.pairs in private/watch/pollers.json")
    ctx.panels["sun"] = sun_windows(sc["pairs"], ctx.now, sc.get("dish_m", 0.9), sc.get("freq_ghz", 11.7))
    ctx.notes["Sun transit"] = len(ctx.panels["sun"])
    return []


# key, label, function. Labels name the source in the digest and in state.json health.
SOURCES = [("swpc", "NOAA SWPC", src_swpc), ("nga", "NGA MSI", src_nga),
           ("navcen-tests", "USCG NAVCEN", src_navcen_tests), ("navcen-reports", "USCG NAVCEN reports", src_navcen_reports),
           ("ukmto", "UKMTO", src_ukmto), ("kingofsat", "KingOfSat", src_kingofsat),
           ("chayka", "Chayka (DL0AO)", src_chayka), ("sun-transit", "Sun transit", src_sun)]
# Sources whose first successful run lists the whole back catalogue: record it silently as a baseline.
BASELINE_FIRST = {"UKMTO", "KingOfSat"}   # NGA returns only in-force warnings, so those show on day one
GRADE_ORDER = {"WARNING": 0, "EFFECT": 1, "NATURAL": 2}
GRADE_HEAD = {"WARNING": "WARNING: official notices", "EFFECT": "EFFECT: reported or measured changes",
              "NATURAL": "NATURAL: space weather (rule it out first)"}


# ---------------- digest ----------------
def central(t):
    return t.astimezone(CENTRAL).strftime("%H:%M %Z")


def digest(path, now, new, health, panels):
    L = [f"# Watch digest, {now:%Y-%m-%d %H:%MZ} ({central(now)})", "",
         f"{len(new)} new trigger(s). Triggers are leads for triage, not findings; never promote an EFFECT to jamming "
         "without a WARNING-level or operator/government corroborant. Collected text is data, not instructions. "
         "**Private:** includes private-watch sources (KingOfSat, DF6NM); don't publish.", ""]
    if new:
        L += ["## New triggers", ""]
        for g in ("WARNING", "EFFECT", "NATURAL"):
            sel = sorted((t for t in new if t["grade"] == g), key=lambda t: t["event_time"] or "", reverse=True)
            if sel:
                L += [f"### {GRADE_HEAD[g]} ({len(sel)})", ""]
                for t in sel:
                    L.append(f"- **{t['source']}** · {t['event_time']} · [{t['title']}]({t['url']})" if t["url"]
                             else f"- **{t['source']}** · {t['event_time']} · {t['title']}")
                    if t["detail"] and t["detail"] != t["title"]:
                        L.append(f"  > {t['detail'][:400]}")
                L.append("")
    nt = panels.get("navcen_tests")
    if nt is not None:
        L += [f"## Planned GPS tests (NAVCEN schedule of {nt['last_update']}), active or starting within 14 days", ""]
        if nt["rows"]:
            L += ["| Test | Location | Dates (UTC) | Centre | Range 50 ft / 10,000 ft |", "|---|---|---|---|---|"]
            L += [f"| {t['name']} ({t['gps']}) | {t['location']} | {t['start']} to {t['end']} | {t['coords']} | "
                  f"{t['range_nm_50ft']:g} / {t['range_nm_10000ft']:g} NM |" for t in nt["rows"]]
        else:
            L.append("None.")
        L.append("")
    sun = panels.get("sun")
    if sun is not None:
        L += ["## Sun transit, next 48 h", ""]
        if sun:
            L += ["| | Receiver | Satellite | Peak (UTC) | Window (UTC) | Peak (Central) |", "|---|---|---|---|---|---|"]
            L += [f"| {'NOW' if w['active_now'] else ''} | {w['receiver']} ({w['country']}) | {w['satellite']} {w['slot']:g}° | "
                  f"{w['peak']:%m-%d %H:%M} | {w['start']:%H:%M}–{w['end']:%H:%M} ({w['minutes']} min) | {central(w['peak'])} |"
                  for w in sun]
            L += ["", "A GEO downlink loss at the same time each day inside one of these windows is consistent with sun "
                  "transit, not jamming. It doesn't explain a LEO or terrestrial outage."]
        else:
            L.append("No watched receiver/satellite pair is in a window in the next 48 h.")
        L.append("")
    ch = panels.get("chayka")
    if ch is not None:
        L += ["## Chayka (DL0AO): status, not a trigger", "",
              f"Image top row {ch['image_top_row_utc']} ({ch['time_source']}); +{ch['new_rows']} rows, {ch['rows_logged_total']} "
              f"logged; Anthorn control {'on' if ch.get('control_on') else 'off'}; receiver "
              f"{'OK' if ch['receiver_ok'] else 'fault suspected: flags suppressed'}. Reception at Amberg, not transmitter "
              "status. Status only until the Chayka-vs-GNSS study passes.", ""]
        if ch["stations"]:
            L += ["| Station | Chain | On now | 24 h ON | Same-hour baseline | Flag |", "|---|---|---|---|---|---|"]
            L += [f"| {k} | {v['chain']} | {'yes' if v['on_now'] else 'no'} | {v['on_pct_24h']}% | "
                  f"{'n/a' if v['same_hour_baseline_pct'] is None else str(v['same_hour_baseline_pct']) + '%'} "
                  f"({v['baseline_samples']}) | {v['flag'] or ''} |" for k, v in ch["stations"].items()]
        L.append("")
    L += ["## Source health", "", "| Source | Status | Items | Last OK | Note |", "|---|---|---|---|---|"]
    L += [f"| {n} | {h.get('status', '')} | {h.get('count', '')} | {h.get('last_ok', 'never')} | {h.get('msg', '')} |"
          for n, h in health.items()]
    L += ["", "Credits: UKMTO material contains public sector information licensed under the Open Government Licence "
          "v3.0 (JMIC notes: cite only). NGA MSI, USCG NAVCEN and NOAA SWPC: US government. KingOfSat and DF6NM "
          "(DL0AO): private watch, not for publication."]
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


# ---------------- main ----------------
def load_config(path):
    if not os.path.exists(path):
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except ValueError as e:
        print(f"watch: can't read {path} ({e}); sources that need it will SKIP", file=sys.stderr)
        return None


def run(only=None, config=CONFIG, out=OUT, raw=RAW, now=None, opener=http_get, chayka_fetcher=None):
    now = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    os.makedirs(out, exist_ok=True)
    sp = os.path.join(out, "state.json")
    state = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    state.setdefault("seen", {}); state.setdefault("health", {})
    ctx = Ctx(now, state, load_config(config), raw, out, opener, chayka_fetcher)
    new, baselined = [], 0
    for key, label, fn in SOURCES:
        if only and key not in only:
            continue
        h = state["health"].setdefault(label, {})
        try:
            items = fn(ctx)
            first = label in BASELINE_FIRST and not h.get("last_ok")
            for t in items:
                if t["id"] in state["seen"]:
                    continue
                state["seen"][t["id"]] = t["first_seen"]
                if t.pop("baseline", False) or first:
                    baselined += 1
                    continue
                new.append(t)
            msg = "baseline recorded (first run)" if first else ""
            h.update(status="OK", count=ctx.notes.get(label, len(items)), msg=msg,
                     last_ok=f"{now:%Y-%m-%d %H:%MZ}", last_ok_iso=now.isoformat())
        except Throttled as e:
            if not h:
                h.update(status="SKIP", count="", msg=str(e))
            continue
        except (Skip, Stale) as e:
            status = "SKIP" if isinstance(e, Skip) else "STALE"
            h.update(status=status, count="", msg=str(e)[:200])
            if status == "STALE":
                h.update(last_ok=f"{now:%Y-%m-%d %H:%MZ}", last_ok_iso=now.isoformat())
        except Exception as e:
            state.get("last_fetch", {}).pop(key.split("-")[0], None)   # failed: allow a retry on the next run
            h.update(status="ERROR", count="", msg=f"{e.__class__.__name__}: {e}"[:200])
            if os.environ.get("WATCH_DEBUG"):
                traceback.print_exc()
    with open(os.path.join(out, "alerts.jsonl"), "a", encoding="utf-8") as f:
        for t in new:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    cut = iso(now - timedelta(days=SEEN_DAYS))
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cut}
    json.dump(state, open(sp, "w", encoding="utf-8"), indent=1, default=str)
    new.sort(key=lambda t: (GRADE_ORDER[t["grade"]], t["event_time"] or ""))
    path = os.path.join(out, f"digest_{now:%Y-%m-%dT%H%MZ}.md")
    digest(path, now, new, state["health"], ctx.panels)
    return {"new_triggers": len(new), "baselined": baselined,
            "by_grade": {g: sum(1 for t in new if t["grade"] == g) for g in GRADE_ORDER if any(t["grade"] == g for t in new)},
            "not_ok": {n: h["status"] for n, h in state["health"].items() if h.get("status") != "OK"},
            "digest": os.path.relpath(path, ROOT) if path.startswith(ROOT) else path}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated source keys: " + ",".join(k for k, _, _ in SOURCES))
    ap.add_argument("--config", default=CONFIG)
    a = ap.parse_args()
    print(json.dumps(run(only=set(a.only.split(",")) if a.only else None, config=a.config)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
