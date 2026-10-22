#!/usr/bin/env python3
"""faa_gps_tests.py: announced US GPS interference tests, from the FAA's public flight advisories (SPANS).

The FAA posts a notice for each planned GPS interference test ("GPS Interference Testing <place> <dates>") with a
PDF flight advisory: the test centre, the daily windows in UTC, and the radius by altitude within which GPS
(including WAAS and ADS-B) may not be available. US government work, public domain (registry:
faa-spans-gps-advisories). These are declared events: they let the map label degradation as an announced test
instead of reading it as hostile interference. Validated on WSMRNM GPS 25-16 (docs/validation/phase1.md).

  python pipeline/faa_gps_tests.py --rss                    # new advisories from the notices feed (daily)
  python pipeline/faa_gps_tests.py --crawl 14600 15300      # one-off history by notice id (polite, ~2 s/request)
  python pipeline/faa_gps_tests.py --parse FILE.pdf         # print what the parser reads from one advisory
  python pipeline/faa_gps_tests.py --reparse                # re-read every stored advisory (after parser changes)
  python pipeline/faa_gps_tests.py --nids 14715 14774       # specific notice ids

Store: data/declared/faa_gps_tests.json, one record per test, keyed by its base id (a revision replaces the
earlier one). Needs pypdf.
"""
import argparse, io, json, math, os, re, sys, time, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "data", "declared", "faa_gps_tests.json")
SITE = "https://www.faasafety.gov"
RSS = SITE + "/RSS/NoticesRSS.aspx"
UA = {"User-Agent": "noise-floor (research; github.com/metacog-osint/noise-floor)"}
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
DASH = "-–—"

ID_RE = re.compile(r"N\s?A\s?V\s+GPS\s*\(([A-Z0-9_]+ GPS[ _]\d{2}-\d+(?: REV \d+)?)\)")     # text extraction sometimes splits "NA V"
CENTRE_RE = re.compile(r"(\d{2})(\d{2})(\d{2})([NS])\s*(\d{2,3})(\d{2})(\d{2})([EW])")    # some write 86 deg as '86', not '086'
DATE_RE = re.compile(r"^\s*(\d{1,2})(?:\s+([A-Z]{3}))?(?:\s+(\d{2}))?(?:\s*[" + DASH + r"]\s*(\d{1,2})\s+([A-Z]{3}))?\s+(\d{2})(?=\s)")
TIMES_RE = re.compile(r"(\d{4})Z\s*[" + DASH + r"]\s*(\d{4})Z")
AREA_RE = re.compile(r"AREA\s+DEFINED\s+AS:?\s*((?:\d{6}[NS]\s*\d{6,7}[EW]\s*(?:TO\s+)?)+)")
RADIUS_RE = re.compile(r"(\d+)\s*NM\s+RADIUS\s+(?:CENTERED\s+AT\s+\S+\s+\(\S+\)\s+)?(?:AT\s+)?(FL\d+(?:-UNL)?|\d+\s*FT(?:\s*AGL)?)")
NOTICE_TITLE_RE = re.compile(r"GPS\s+Interference\s+Testing", re.I)


def get(url, binary=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def dms(d, m, s, h):
    v = int(d) + int(m) / 60 + int(s) / 3600
    return round(-v if h in "SW" else v, 4)


def parse_text(t):
    """Fields from an advisory's text, or None if it isn't a parseable GPS test advisory."""
    t = t.replace("’", "'")
    m = ID_RE.search(t)
    c = CENTRE_RE.search(t)
    if not m or not c:
        return None
    centre = [dms(*c.group(1, 2, 3, 4)), dms(*c.group(5, 6, 7, 8))]
    b0, b1 = t.find("B. Dates"), t.find("C. Duration")
    windows = []
    for line in (t[b0:b1] if 0 <= b0 < b1 else t).splitlines():
        g = DATE_RE.match(line)
        times = TIMES_RE.findall(line[g.end():]) if g else []
        if not times:
            continue
        d1, m1, y1, d2, m2, yy = g.groups()
        y = 2000 + int(yy)
        if d2 is None:                                  # single day: "06 OCT 26 0600Z - 1200Z"
            first = last = date(y, MONTHS[m1], int(d1))
        else:   # "13 - 16 OCT 26", "26 OCT - 04 NOV 26", "22 SEP 25 - 4 OCT 25" (a range without DLY is read as daily too)
            last = date(y, MONTHS[m2], int(d2))
            y0 = 2000 + int(y1) if y1 else (y - 1 if m1 == "DEC" and m2 == "JAN" else y)
            first = date(y0, MONTHS[m1 or m2], int(d1))
        for t0, t1 in times:                            # one or more windows on the line, each every day of the range
            h0, h1 = (int(x[:2]) * 60 + int(x[2:]) for x in (t0, t1))
            d = first
            while d <= last:
                s = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(minutes=h0)
                e = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(minutes=h1 + (1440 if h1 < h0 else 0))
                windows.append([s.strftime("%Y-%m-%dT%H:%MZ"), e.strftime("%Y-%m-%dT%H:%MZ")])
                d += timedelta(days=1)
    radii = {}
    for r in RADIUS_RE.finditer(t):
        alt = re.sub(r"\s+", " ", r.group(2)).replace("-UNL", "").replace(" FT", "FT")
        radii.setdefault(alt, int(r.group(1)))
    area = None
    a = AREA_RE.search(t)
    if a:                                               # a polygon instead of radii: keep it, and its reach from the centre
        area = [[dms(*q[:4]), dms(*q[4:])] for q in CENTRE_RE.findall(a.group(1))]
        if area:
            reach = max(_nm(centre, q) for q in area)
            radii.setdefault("AREA", round(reach))
    if not windows:
        return None
    full = m.group(1).replace("GPS_", "GPS ")
    rec = {"id": full, "base": re.sub(r" REV \d+$", "", full), "centre": centre, "radii_nm": radii, "windows": sorted(set(map(tuple, windows)))}
    rec["windows"] = [list(w) for w in rec["windows"]]
    if area:
        rec["area"] = area
    return rec


def _nm(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h))) / 1.852


def pdf_text(data):
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def notice(nid):
    """(subject, pdf url, notice date) from a SPANS notice page; None if missing or not a GPS test."""
    html = get(f"{SITE}/SPANS/noticeView.aspx?nid={nid}")
    sm = re.search(r'id="ctl00_ContentPlaceHolder1_lblSubject"[^>]*>([^<]*)<', html)
    subject = re.sub(r"\s+", " ", sm.group(1)).strip() if sm else ""
    if not (NOTICE_TITLE_RE.search(subject) or re.search(r"\b[A-Z0-9]{4,8} GPS \d{2}-\d+", subject)
            or re.search(r"GPS\s+INTERFERENCE\s+TESTING", html)):
        return None
    pdf = re.search(r"/files/notices/[^\"'<>]+?\.pdf", html, re.I)
    dm = re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\w+ \d{1,2}, \d{4})", html)
    when = datetime.strptime(dm.group(2), "%B %d, %Y").date().isoformat() if dm else None
    return (subject, SITE + pdf.group(0) if pdf else None, when)


def pdf_place(t):
    """The place line under the date line at the top of an advisory ("WHITE SANDS MISSILE RANGE, NM")."""
    m = re.search(r"\n\s*\d{1,2}\s*(?:[A-Za-z]+\s*)?[" + DASH + r"?]\s*\d{1,2}\s+[A-Za-z]+\s*\n\s*([^\n]+?)\s*\n", t)
    return re.sub(r",\s*([A-Za-z]{2})$", lambda g: ", " + g.group(1).upper(), m.group(1).title()) if m else None


def place(title):
    m = re.search(r"GPS\s+Interference\s+Testing\s+(?:at\s+)?(.+?)\s+\d{1,2}\s*(?:[A-Z]{3}\s*)?[" + DASH + r"]", title, re.I)
    pl = (m.group(1) if m else re.sub(r"(?i)GPS\s+Interference\s+Testing\s*", "", title)).strip(" ,").lstrip("-–:").strip()
    pl = pl.title() if pl.isupper() else pl
    return re.sub(r",\s*([A-Za-z]{2})$", lambda g: ", " + g.group(1).upper(), pl)


def load():
    if os.path.exists(STORE):
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    return {"source": "FAA SPANS flight advisories (US government, public domain)", "tests": {}}


def save(store):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    store["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    with open(STORE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(store, f, indent=1, ensure_ascii=False, sort_keys=True)


def add(store, nid, sleep=2.0):
    """Fetch one notice and its advisory; returns a status word."""
    if any(t.get("nid") == nid for t in store["tests"].values()):
        return "known"
    n = notice(nid)
    time.sleep(sleep)
    if not n:
        return "not a GPS test"
    title, pdf, when = n
    if not pdf:
        return "no PDF"
    text = pdf_text(get(pdf, binary=True))
    rec = parse_text(text)
    time.sleep(sleep)
    if not rec:
        return f"unparsed: {pdf}"
    where = place(title) if NOTICE_TITLE_RE.search(title) else (pdf_place(text) or title)
    rec.update({"nid": nid, "title": title, "place": where, "notice_url": f"{SITE}/SPANS/noticeView.aspx?nid={nid}",
                "pdf_url": pdf, "published": when})
    old = store["tests"].get(rec["base"])
    if old and old.get("nid", 0) > nid:
        return "older revision"
    store["tests"][rec["base"]] = rec
    return f"added {rec['id']} ({len(rec['windows'])} windows)"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rss", action="store_true")
    ap.add_argument("--crawl", nargs=2, type=int, metavar=("FIRST_NID", "LAST_NID"))
    ap.add_argument("--parse")
    ap.add_argument("--reparse", action="store_true")
    ap.add_argument("--nids", nargs="+", type=int)
    a = ap.parse_args()
    if a.parse:
        with open(a.parse, "rb") as f:
            print(json.dumps(parse_text(pdf_text(f.read())), indent=1))
        return
    store = load()
    nids = []
    if a.rss:
        root = ET.fromstring(get(RSS))
        for it in root.iter("item"):
            m = re.search(r"nid=(\d+)", it.findtext("link") or "")
            if m and NOTICE_TITLE_RE.search(it.findtext("title") or ""):
                nids.append(int(m.group(1)))
    if a.crawl:
        nids += list(range(a.crawl[0], a.crawl[1] + 1))
    if a.nids:
        nids += a.nids
    if a.reparse:
        changed = 0
        for base, old in list(store["tests"].items()):
            try:
                rec = parse_text(pdf_text(get(old["pdf_url"], binary=True)))
            except Exception as e:
                print(old["id"], f"error {e.__class__.__name__}: {e}"[:160])
                continue
            time.sleep(1.5)
            if rec:
                new = {**old, **{k: rec[k] for k in ("id", "centre", "radii_nm", "windows")}}
                if rec.get("area"):
                    new["area"] = rec["area"]
                changed += new != old
                store["tests"][base] = new
        print(json.dumps({"reparsed": len(store["tests"]), "changed": changed}))
    added = 0
    for nid in sorted(set(nids)):
        try:
            st = add(store, nid, sleep=0.5 if a.rss else 2.0)
        except Exception as e:
            st = f"error {e.__class__.__name__}: {e}"[:200]
        if st.startswith("added") or st.startswith("unparsed") or st.startswith("error"):
            print(nid, st, flush=True)
        added += st.startswith("added")
        if a.crawl and nid % 50 == 0:
            save(store)
    save(store)
    print(json.dumps({"checked": len(set(nids)), "added": added, "tests": len(store["tests"])}))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"tests_changed={'true' if added else 'false'}\n")


if __name__ == "__main__":
    main()
