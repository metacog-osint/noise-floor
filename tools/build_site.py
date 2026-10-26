#!/usr/bin/env python3
"""Build the public site (site/, served by Cloudflare Pages) from site_src/ and the licence registry.

  python tools/build_site.py           # writes site/*.html, site/style.css, robots.txt, _headers

Sources:
  site_src/*.html     page bodies; first line is a JSON comment with title, description, nav
  site_src/lanes.json every lane: status, what, how, data, notes, links (Home grid + Lanes page)
  registry/sources.csv the licence registry (Sources page)
Nothing private may go into site_src/: the public-repo check runs on these files like any other.
"""
import hashlib
import csv
import html
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "site_src")
OUT = os.path.join(ROOT, "site")
REPO = "https://github.com/metacog-osint/noise-floor"
e = html.escape

STATUS = {  # key: (label, css class, one-line meaning)
    "validated": ("Validated", "st-validated", "built and tested against known events"),
    "partial": ("Partly validated", "st-partial", "built; first controls passed, more tests open"),
    "running": ("Running", "st-running", "collecting or operating now"),
    "built": ("Built", "st-built", "a working tool"),
    "prototype": ("Prototype", "st-prototype", "a first result, not yet a product"),
    "planned": ("Planned", "st-planned", "designed, not built"),
    "parked": ("Parked", "st-parked", "set aside with its final state written down; revisited on a named trigger"),
}
NAV = [("home", "Home", ""), ("map", "Map", "map"), ("sea", "Sea", "sea"), ("sun", "Sun", "sun"), ("charts", "Charts", "charts"),
       ("lanes", "Lanes", "lanes"), ("methods", "Methods", "methods"), ("validation", "Validation", "validation"), ("data", "Data", "data"), ("sources", "Sources", "sources")]
USE = {  # registry `use` values in plain words
    "ingest": "Feeds a layer", "ingest-after-ok": "After permission", "visual-only": "Visual comparison only",
    "cite-only": "Cited, not ingested", "later": "Later phase", "exclude": "Excluded", "private-watch": "Private watch only",
}
LANE = {"gnss-observed": "GNSS observed", "emitters": "Emitters", "maritime": "Maritime", "declared": "Declared",
        "context": "Context", "satcom": "SATCOM", "lf-hf": "LF/HF", "community": "Community", "attribution": "Attribution"}

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta name="color-scheme" content="light dark">
<link rel="stylesheet" href="/style.css">
<link rel="alternate" type="application/atom+xml" title="Noise Floor: daily GNSS summary" href="/feed.xml">
{head}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="site"><div class="in">
<a class="brand" href="/">Noise Floor</a>
<nav aria-label="Main">{nav}</nav>
</div></header>
<main id="main"{main_class}>
{body}
</main>
<footer class="site"><div class="in">
<p>A project of The Intelligence Company. Updated {updated}. <a href="{repo}">Source code</a> (MIT). <a href="/terms">Terms of use</a>.</p>
<p>ADS-B data: <a href="https://www.adsb.lol/">adsb.lol</a> (ODbL 1.0); derived data is published under ODbL. NISAR data: NASA/JPL-ISRO via ASF DAAC. Every source and its licence: <a href="/sources">Sources</a>.</p>
</div></footer>
</body>
</html>
"""


def chip(status):
    label, cls, _ = STATUS[status]
    return f'<span class="chip {cls}">{e(label)}</span>'


def nav_html(active):
    return "".join(f'<a href="/{href}"' + (' aria-current="page"' if key == active else "") + f">{e(label)}</a>"
                   for key, label, href in NAV)


def read_page(name):
    raw = open(os.path.join(SRC, name), encoding="utf-8").read()
    m = re.match(r"<!--(\{.*?\})-->\s*", raw, re.S)
    if not m:
        sys.exit(f"{name}: first line must be a JSON comment with title/description/nav")
    return json.loads(m.group(1)), raw[m.end():]


ASSETS = ("style.css", "map.js", "sea.js", "charts.js", "home.js", "data.js", "imagery.js", "sunoutage.js", "sun.js", "dash.js")
ASSET_V = {}            # file -> short content hash; pages ask for /file?v=hash, so browsers can cache assets for a year


def asset_bytes(f):
    """An asset's bytes with line endings normalised, so a Windows checkout (core.autocrlf) and CI build the same site."""
    return open(os.path.join(SRC, f), "rb").read().replace(b"\r\n", b"\n")


def asset_versions():
    for f in ASSETS:
        ASSET_V[f] = hashlib.sha256(asset_bytes(f)).hexdigest()[:10]


def data_version(folder):
    """Short hash of the files in site/data/<folder> (line endings normalised, so Windows and CI agree). Pages ask for
    /data/<folder>/<file>?v=<hash>, so new page code never meets an older cached data file."""
    h, d = hashlib.sha256(), os.path.join(OUT, "data", folder)
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        h.update(f.encode()); h.update(open(os.path.join(d, f), "rb").read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:10]


def render(meta, body, updated, narrow=False):
    layout = meta.get("layout")
    cls = ' class="wide"' if layout == "wide" else (' class="narrow"' if narrow else "")
    html = PAGE.format(title=e(meta["title"]), description=e(meta["description"]), nav=nav_html(meta.get("nav", "")),
                       body=body, updated=e(updated), repo=REPO, main_class=cls, head=meta.get("head", ""))
    for f, v in ASSET_V.items():
        html = html.replace(f'"/{f}"', f'"/{f}?v={v}"')
    return html


def status_counts(lanes):
    c = Counter(l["status"] for l in lanes)
    items = "".join(f'<div class="count"><b>{c[k]}</b><span>{chip(k)}</span></div>' for k in STATUS if c[k])
    return f'<div class="counts">{items}</div>'


def lane_grid(data):
    out = []
    for g in data["groups"]:
        lanes = [l for l in data["lanes"] if l["group"] == g["id"]]
        if not lanes:
            continue
        cards = "".join(
            f'<div class="card">{chip(l["status"])}<h3><a href="/lanes#{e(l["id"])}">{e(l["name"])}</a></h3>'
            f'<p>{e(l["summary"])}</p></div>' for l in lanes)
        out.append(f'<h3>{e(g["name"])}</h3><div class="grid">{cards}</div>')
    return "".join(out)


def lanes_page(data):
    legend = "".join(f'<span title="{e(STATUS[k][2])}">{chip(k)} <span class="small">{e(STATUS[k][2])}</span></span>'
                     for k in STATUS)
    toc = " · ".join(f'<a href="#g-{e(g["id"])}">{e(g["name"])}</a>' for g in data["groups"])
    parts = [
        '<p class="kicker">Lanes</p><h1>Every lane, built and planned</h1>',
        '<p class="lede">Each lane answers one question with its own data and method. Statuses say how far each has got; '
        'planned lanes are designs, not results.</p>',
        f'<div class="legend">{legend}</div>', status_counts(data["lanes"]), f'<p class="small">Jump to: {toc} · <a href="#build-order">Build order</a></p>',
    ]
    for g in data["groups"]:
        parts.append(f'<h2 id="g-{e(g["id"])}">{e(g["name"])}</h2><p>{e(g["intro"])}</p>')
        for l in (x for x in data["lanes"] if x["group"] == g["id"]):
            links = " · ".join(f'<a href="{e(u)}">{e(t)}</a>' for t, u in l.get("links", []))
            data_list = "".join(f"<li>{e(d)}</li>" for d in l.get("data", []))
            parts.append(
                f'<article class="lane" id="{e(l["id"])}"><header>{chip(l["status"])}<h3>{e(l["name"])}</h3>'
                f'<span class="phase">{e(l["phase"])}</span></header>'
                f'<p><strong>{e(l["summary"])}</strong></p><dl>'
                f'<dt>What</dt><dd><p>{e(l["what"])}</p></dd>'
                f'<dt>How</dt><dd><p>{e(l["how"])}</p></dd>'
                f'<dt>Data</dt><dd><ul>{data_list}</ul></dd>'
                f'<dt>Notes</dt><dd><p>{e(l["notes"])}</p></dd>'
                + (f"<dt>More</dt><dd><p>{links}</p></dd>" if links else "") + "</dl></article>")
    parts.append("""<h2 id="build-order">Build order</h2>
<p>Each phase is finished, validated and committed before the next starts.</p>
<div class="tw"><table><thead><tr><th>Phase</th><th>Scope</th><th>Status</th></tr></thead><tbody>
<tr><td>1. Foundation</td><td>Licence registry, GNSS processor, method card, validation against known events</td><td>""" + chip("validated") + """</td></tr>
<tr><td>2. Daily and public</td><td>Daily pipeline and backfill, public map, declared-interference lane, home status board</td><td>""" + chip("running") + """</td></tr>
<tr><td>3. SATCOM v1</td><td>Sun outages with alerts (running; the interference register folded in), GEO threat board (next), satellite-internet health (parked until permissions); the L-band risk overlay was dropped</td><td>""" + chip("running") + """ sun outages</td></tr>
<tr><td>4. Spoofing and maritime</td><td>ADS-B spoofing (validated), AIS spoofing at sea and dark ships (prototypes, held-out tests next), declared-warning layers</td><td>""" + chip("validated") + """ ADS-B spoofing</td></tr>
<tr><td>5. Emitters</td><td>Sentinel-1 RFI board, weather-radar spokes</td><td>""" + chip("parked") + """</td></tr>
<tr><td>6. Assessment</td><td>Event model and grading (v0.2; exclusions folded in), community lane, the home status board as the daily status; weekly assessment later</td><td>""" + chip("prototype") + """ events; community collection running</td></tr>
<tr><td>7. Extensions</td><td>Spaceborne and network GNSS; NISAR L-band emitters (pulled forward)</td><td>""" + chip("partial") + """ NISAR</td></tr>
</tbody></table></div>""")
    return "\n".join(parts)


def sources_page(rows):
    lanes = Counter(r["lane"] for r in rows)
    uses = Counter(r["use"] for r in rows)
    counts = "".join(f'<div class="count"><b>{n}</b><span>{e(USE.get(u, u))}</span></div>' for u, n in uses.most_common())
    lane_opts = "".join(f'<option value="{e(k)}">{e(LANE.get(k, k))} ({n})</option>' for k, n in sorted(lanes.items()))
    use_opts = "".join(f'<option value="{e(k)}">{e(USE.get(k, k))} ({n})</option>' for k, n in uses.most_common())
    body_rows = []
    for r in sorted(rows, key=lambda r: (LANE.get(r["lane"], r["lane"]), r["name"].lower())):
        comm = {"yes": "Yes", "no": "No", "ask": "Ask", "unverified": "Unverified"}.get(r["commercial"], r["commercial"])
        body_rows.append(
            f'<tr data-lane="{e(r["lane"])}" data-use="{e(r["use"])}"><td>{e(r["name"])}</td><td>{e(LANE.get(r["lane"], r["lane"]))}</td>'
            f'<td>{e(r["gives"])}</td><td>{e(r["licence"])}</td><td>{e(comm)}</td><td>{e(USE.get(r["use"], r["use"]))}</td>'
            f'<td class="num">{e(r["phase"] or "–")}</td></tr>')
    return f"""<p class="kicker">Sources</p>
<h1>Licence registry</h1>
<p class="lede">Every source Noise Floor uses, considered or rejected, with its licence and how it may be used. A source can't feed a public layer until its licence is recorded. "Unverified" means the terms haven't been confirmed yet.</p>
<div class="counts"><div class="count"><b>{len(rows)}</b><span>sources assessed</span></div>{counts}</div>
<div class="filters" role="search">
<label class="small" for="q">Search</label><input id="q" type="search" placeholder="Name, licence, what it gives…">
<select id="lane" aria-label="Lane"><option value="">All lanes</option>{lane_opts}</select>
<select id="use" aria-label="Use"><option value="">Any use</option>{use_opts}</select>
</div>
<p class="small" id="shown"></p>
<div class="tw"><table id="reg"><thead><tr><th>Source</th><th>Lane</th><th>What it gives</th><th>Licence</th><th>Commercial use</th><th>How we use it</th><th>Phase</th></tr></thead>
<tbody>{''.join(body_rows)}</tbody></table></div>
<p class="small">The registry is <a href="{REPO}/blob/main/registry/sources.csv">registry/sources.csv</a> in the repository, checked on every commit.</p>
<script>
(function(){{
  var q=document.getElementById('q'), l=document.getElementById('lane'), u=document.getElementById('use'), s=document.getElementById('shown');
  var rows=[].slice.call(document.querySelectorAll('#reg tbody tr'));
  function f(){{
    var t=q.value.toLowerCase(), n=0;
    rows.forEach(function(r){{
      var ok=(!l.value||r.dataset.lane===l.value)&&(!u.value||r.dataset.use===u.value)&&(!t||r.textContent.toLowerCase().indexOf(t)>=0);
      r.hidden=!ok; if(ok)n++;
    }});
    s.textContent=n+' of '+rows.length+' sources shown';
  }}
  [q,l,u].forEach(function(x){{x.addEventListener('input',f);}}); f();
}})();
</script>"""


def _table(head, rows):
    th = "".join(f"<th>{e(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f'<td{" class=\"num\"" if i else ""}>{e("–" if v is None else str(v))}</td>'
                                    for i, v in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def chart_fills():
    path = os.path.join(OUT, "data", "charts.json")
    if not os.path.exists(path):
        sys.exit("site/data/charts.json missing: run tools/export_site_data.py first")
    c = json.load(open(path, encoding="utf-8"))
    hs = c["hotspots"]
    names = list(hs)
    return {
        "{{TABLE:egnos}}": _table(["Hour (UTC)", "EGNOS area %", "Baseline %", "State", "Capable aircraft"],
                                  [[r["t"], r["share"], r["base"], r["state"], r["capable"]] for r in c["egnos"]]),
        "{{TABLE:storm}}": _table(["Hour (UTC)", "Below 10 m %", "Quiet days %", "Worse than 93 m %", "Quiet days %"],
                                  [[r["t"], r["acc10"], r["acc10_base"], r["gross"], r["gross_base"]] for r in c["storm"]]),
        "{{TABLE:bay}}": _table(["Minute (UTC)", "Aircraft-hexes"], [[r["t"], r["aircraft"]] for r in c["bay"] if r["aircraft"]]),
        "{{TABLE:hotspots}}": _table(["Day"] + names, [[hs[names[0]][i]["day"]] + [hs[n][i]["share"] for n in names]
                                                         for i in range(len(hs[names[0]]))]),
        "{{TABLE:types}}": _table(["Type", "Post-exposure aircraft-days", "Share %", "Share of all aircraft-days %", "Ratio"],
                                  [[r["type"], r["post_exposure"], r["pe_share"], r["all_share"], f'{r["ratio"]}×'] for r in c["types"]["rows"]]),
        "{{TYPES_TOTAL}}": f'{c["types"]["post_exposure_total"]:,}',
    }


def main():
    asset_versions()
    data = json.load(open(os.path.join(SRC, "lanes.json"), encoding="utf-8"))
    rows = list(csv.DictReader(open(os.path.join(ROOT, "registry", "sources.csv"), encoding="utf-8")))
    updated = data["updated"]
    for l in data["lanes"]:
        if l["status"] not in STATUS:
            sys.exit(f"lane {l['id']}: unknown status {l['status']}")
    os.makedirs(OUT, exist_ok=True)
    fills = {"{{UPDATED}}": e(updated), "{{LANE_COUNT}}": str(len(data["lanes"])),
             "{{STATUS_COUNTS}}": status_counts(data["lanes"]), "{{LANE_GRID}}": lane_grid(data),
             "{{SOURCE_COUNT}}": str(len(rows)), "{{VESSELS_V}}": data_version("vessels")}
    fills.update(chart_fills())
    written = []
    for name in ("index.html", "map.html", "sea.html", "sun.html", "charts.html", "methods.html", "validation.html", "data.html", "terms.html", "404.html"):
        meta, body = read_page(name)
        for k, v in fills.items():
            body = body.replace(k, v)
        if "{{" in body:
            sys.exit(f"{name}: unfilled placeholder")
        open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n").write(
            render(meta, body, updated, narrow=name in ("methods.html", "terms.html", "404.html")))
        written.append(name)
    open(os.path.join(OUT, "lanes.html"), "w", encoding="utf-8", newline="\n").write(render(
        {"title": "Lanes · Noise Floor", "description": "Every Noise Floor lane, built and planned: what it measures, how, which sources, and its limits.",
         "nav": "lanes"}, lanes_page(data), updated))
    open(os.path.join(OUT, "sources.html"), "w", encoding="utf-8", newline="\n").write(render(
        {"title": "Sources · Noise Floor", "description": "Noise Floor's licence registry: every source, its licence and how it may be used.",
         "nav": "sources"}, sources_page(rows), updated))
    written += ["lanes.html", "sources.html"]
    for f in ASSETS:
        open(os.path.join(OUT, f), "wb").write(asset_bytes(f))
    open(os.path.join(OUT, "robots.txt"), "w", newline="\n").write("User-agent: *\nAllow: /\n")
    year, day, hour, short = ("public, max-age=31536000, immutable", "public, max-age=86400, stale-while-revalidate=604800",
                              "public, max-age=3600, stale-while-revalidate=86400", "public, max-age=300, stale-while-revalidate=3600")
    rules = [("/*", "X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n  X-Frame-Options: DENY")]
    rules += [(f"/{f}", f"Cache-Control: {year}") for f in ASSETS]              # always requested as /file?v=<content hash>
    rules += [(f"/data/{f}", f"Cache-Control: {day}") for f in ("land.json", "borders.json", "places.json")]
    rules += [(p, f"Cache-Control: {hour}") for p in ("/data/gnss/2*", "/data/events/*", "/data/history/*")]   # day files
    rules += [("/data/vessels/*", f"Cache-Control: {hour}")]                  # Sea map data, refreshed by hand
    rules += [(f"/data/{f}", f"Cache-Control: {short}") for f in ("gnss/days.json", "trend.json", "charts.json")]
    rules += [("/feed.xml", f"Cache-Control: {short}")]
    open(os.path.join(OUT, "_headers"), "w", newline="\n").write("".join(f"{p}\n  {h}\n" for p, h in rules))
    for name in written:                      # a duplicate id once broke the charts page (two elements, one anchor)
        ids = re.findall(r'\sid="([^"]+)"', open(os.path.join(OUT, name), encoding="utf-8").read())
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            sys.exit(f"{name}: duplicate ids {dup}")
    expected = set(written) | set(ASSETS) | {"robots.txt", "_headers", "data", "feed.xml"}   # feed.xml: written at deploy (site_days.py)
    stray = sorted(set(os.listdir(OUT)) - expected)
    if stray:
        sys.exit(f"unexpected files in site/: {stray} (remove them, or add them to the build)")
    print("built:", ", ".join(sorted(expected)))


if __name__ == "__main__":
    main()
