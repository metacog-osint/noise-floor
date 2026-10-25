"""Private web view: bundle the run's outputs into a small static site and deploy it to a
Cloudflare Pages project that sits behind Cloudflare Access.

Everything here is private watch output. The Pages project and the Access application that
protects it (production and every deployment hostname) are set up once by the owner; their
names live in the private config, never in this repo:

  "view": {"pages_project": "...", "account_id": "...",
           "extra_maps": [{"title": "...", "path": "private/.../map.html"}],
           "vessels": true}            # optional: add the private vessel page (vessels.py); or {"days": 2, ...}

Deploys use wrangler with CLOUDFLARE_API_TOKEN from the environment (or the Windows user
environment). The token is never printed.
"""
import html
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .pipeline import REPO

CENTRAL = ZoneInfo("America/Chicago")
WRANGLER = "wrangler@4.151.3"
HEADERS = """/*
  X-Robots-Tag: noindex, nofollow
  Cache-Control: no-store
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
"""


def _ct(ts):
    """'Oct 21, 9:48 PM CDT' from an ISO UTC timestamp."""
    if not ts:
        return "n/a"
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    t = t.astimezone(CENTRAL)
    return t.strftime("%b %d, %I:%M %p %Z").replace(" 0", " ")


def _token():
    tok = os.environ.get("CLOUDFLARE_API_TOKEN")
    if tok:
        return tok
    if os.name == "nt":
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Environment]::GetEnvironmentVariable('CLOUDFLARE_API_TOKEN','User')"],
                           capture_output=True, text=True)
        return r.stdout.strip() or None
    return None


def _rows(items, cols):
    out = []
    for it in items:
        out.append("<tr>" + "".join(f"<td>{c(it)}</td>" for _, c in cols) + "</tr>")
    head = "<tr>" + "".join(f"<th>{html.escape(h)}</th>" for h, _ in cols) + "</tr>"
    return f"<table><thead>{head}</thead><tbody>{''.join(out) or '<tr><td colspan=9>None</td></tr>'}</tbody></table>"


def index_html(state, cfg, now, maps, files):
    """Landing page: run health, recent new sites, strongest repeat sites, links."""
    e = html.escape
    h = state.get("health", {})
    tok = h.get("token") or {}
    dets = {d["id"]: d for d in state.get("detections", [])}
    week = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    passes7 = sum(1 for p in state.get("processed", {}).values() if p.get("start", "") >= week)
    sites = list(state.get("sites", {}).values())

    def best(s):
        ds = [dets[i] for i in s.get("detections", []) if i in dets]
        return max(ds, key=lambda d: ["LOW", "MEDIUM", "HIGH"].index(d["confidence"])) if ds else None

    strong = []
    for s in sites:
        b = best(s)
        if b is None or b["confidence"] == "LOW":
            continue
        active = sum(1 for c in s.get("coverage", []) if c.get("active"))
        strong.append((active, len(s.get("geometries", [])), s, b))
    strong.sort(key=lambda x: (-x[0], -x[1]))
    recent = sorted((s for s in sites if not s.get("baseline")), key=lambda s: s.get("first_seen", ""), reverse=True)[:25]

    def method(d):
        m = d.get("method", "image")
        return "tones + broadband" if m == "tables" and d.get("broadband") else m

    site_cols = [
        ("Site", lambda x: e(x[2]["id"])),
        ("Where", lambda x: e(x[2].get("where", ""))),
        ("Passes active", lambda x: f'{x[0]} / {len(x[2].get("coverage", []))}'),
        ("Geometries", lambda x: str(x[1])),
        ("Signal", lambda x: e(x[3].get("band_text", ""))[:90]),
        ("Method", lambda x: e(method(x[3]))),
        ("Last seen", lambda x: e(_ct(x[2].get("last_seen")))),
    ]
    new_cols = [
        ("Site", lambda s: e(s["id"])),
        ("Where", lambda s: e(s.get("where", ""))),
        ("First seen", lambda s: e(_ct(s.get("first_seen")))),
        ("Status", lambda s: e(s.get("status", ""))),
    ]
    tok_txt = (f'{tok.get("days_left")} days (expires {tok.get("expires")})' if tok else "unknown")
    warn = ' class="warn"' if tok and tok.get("days_left", 99) < 14 else ""
    links = "".join(f'<li><a href="{e(href)}">{e(title)}</a></li>' for title, href in maps)
    dl = "".join(f'<li><a href="{e(f)}" download>{e(f)}</a></li>' for f in files)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Noise Floor private view</title>
<style>
:root{{--bg:#f6f5f1;--fg:#1c1f23;--mut:#5d646d;--line:#dedbd2;--acc:#b4462b;--card:#fff;--warn:#a33}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111418;--fg:#e7e5e0;--mut:#9aa1a9;--line:#2a2f36;--acc:#e0805f;--card:#171b20;--warn:#f08080}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:72rem;margin:0 auto;padding:2rem 1rem 3rem}}h1{{font-size:1.6rem;margin:0}}h2{{font-size:1.05rem;margin:2rem 0 .6rem}}
.sub{{color:var(--mut);margin:.2rem 0 1.4rem}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:.8rem}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.8rem 1rem}}.k{{color:var(--mut);font-size:.8rem}}.v{{font-size:1.15rem;font-weight:600}}
.warn{{color:var(--warn)}}a{{color:var(--acc)}}ul{{margin:.3rem 0;padding-left:1.2rem}}
.tw{{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}}table{{border-collapse:collapse;width:100%;font-size:.88rem}}
th,td{{text-align:left;padding:.45rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--mut);font-weight:600;white-space:nowrap}}
.note{{color:var(--mut);font-size:.85rem;margin-top:2rem}}
</style></head><body><main>
<h1>Noise Floor · private view</h1>
<p class="sub">NISAR L-band emitter watch. Updated {e(_ct(now.strftime("%Y-%m-%dT%H:%M:%SZ")))}. Private: behind Cloudflare Access.</p>
<div class="grid">
<div class="card"><div class="k">Last run</div><div class="v">{e(_ct(state.get("last_run")))}</div></div>
<div class="card"><div class="k">Passes processed, last 7 days</div><div class="v">{passes7}</div></div>
<div class="card"><div class="k">Sites with a MEDIUM/HIGH detection</div><div class="v">{len(strong)}</div></div>
<div class="card"><div class="k">Catalogue search</div><div class="v">{e((h.get("search") or {}).get("status", "n/a"))}</div></div>
<div class="card"><div class="k">Earthdata token</div><div class="v"{warn}>{e(tok_txt)}</div></div>
</div>
<h2>Maps</h2><ul>{links}</ul>
<h2>New sites since the baseline</h2><div class="tw">{_rows(recent, new_cols)}</div>
<h2>Strongest repeat sites</h2><div class="tw">{_rows(strong[:40], site_cols)}</div>
<h2>Downloads</h2><ul>{dl}</ul>
<p class="note">Each detection is a lead from one radar snapshot, not a finding. Methods and limits: the lane's README and validation report in the public repo. Times are Central with the zone named.</p>
</main></body></html>"""


def build(cfg, out_dir=None, now=None):
    """Assemble the view in private/nisar/view/ (or out_dir). Returns the folder."""
    now = now or datetime.now(timezone.utc)
    vcfg = cfg.get("view") or {}
    root = os.path.dirname(cfg["out_dir"])
    dest = out_dir or os.path.join(root, "view")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    state = json.load(open(os.path.join(cfg["state_dir"], "state.json")))
    maps, files = [("Watch map (main view)", "map.html")], []
    shutil.copy(os.path.join(cfg["out_dir"], "map.html"), os.path.join(dest, "map.html"))
    for i, m in enumerate(vcfg.get("extra_maps", []), start=1):
        src = m["path"] if os.path.isabs(m["path"]) else os.path.join(REPO, m["path"])
        if os.path.exists(src):
            name = f"map-{i}.html"
            shutil.copy(src, os.path.join(dest, name))
            maps.append((m.get("title", name), name))
    for f in ("detections.geojson", "sites.geojson", "alerts.jsonl", "observations.jsonl", "latest.json"):
        p = os.path.join(cfg["out_dir"], f)
        if os.path.exists(p):
            shutil.copy(p, os.path.join(dest, f))
            files.append(f)
    if vcfg.get("vessels"):                       # opt-in: the private vessel page (AIS; never published publicly)
        try:
            from . import vessels
            info = vessels.build_for_view(cfg, dest, vcfg["vessels"])
            maps.append((f"Vessel watch (AIS, private): {info['vessels']} vessels of interest", "vessels.html"))
            files.append("vessels.json")
        except Exception as ex:                   # the NISAR view still builds and deploys
            print(f"view: vessel page skipped ({type(ex).__name__}: {ex})")
    open(os.path.join(dest, "index.html"), "w", encoding="utf-8").write(index_html(state, cfg, now, maps, files))
    open(os.path.join(dest, "_headers"), "w", encoding="utf-8").write(HEADERS)
    return dest


def deploy(cfg, folder, log=print):
    """wrangler pages deploy to the configured project. Returns True on success."""
    vcfg = cfg.get("view") or {}
    proj, acct = vcfg.get("pages_project"), vcfg.get("account_id")
    tok = _token()
    if not (proj and acct and tok):
        log("view: not configured (pages_project, account_id, CLOUDFLARE_API_TOKEN); skipped")
        return False
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        log("view: npx not found; install Node.js")
        return False
    env = {**os.environ, "CLOUDFLARE_API_TOKEN": tok, "CLOUDFLARE_ACCOUNT_ID": acct}
    cmd = [npx, "--yes", WRANGLER, "pages", "deploy", folder, "--project-name", proj, "--branch", "main",
           "--commit-dirty=true"]
    if os.name == "nt":
        cmd = ["cmd", "/c"] + cmd
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [l.encode("ascii", "replace").decode().strip() for l in (r.stdout + r.stderr).splitlines() if l.strip()][-3:]
    log("view: " + (" | ".join(tail) if tail else f"wrangler exit {r.returncode}"))
    return r.returncode == 0


def publish(cfg, log=print):
    return deploy(cfg, build(cfg), log=log)
