#!/usr/bin/env python3
"""daily_job.py — Phase 2 daily run: process new adsb.lol days and publish the outputs.

For each day (default: the last LOOKBACK UTC days that adsb.lol has published and this repo hasn't):
  1. download the day's archive release (adsblol/globe_history_<YYYY>, tag v<YYYY.MM.DD>-planes-readsb-prod-0)
  2. pnt_daily: per-hex outputs in data/pnt/daily
  3. fetch earlier days' outputs (up to 30 days back) from this repo's releases, for the baselines
  4. pnt_analysis: SBAS flags, anomalies and bursts in data/pnt/analysis
  5. the site's map file for the day, data/pnt/site/<day>.map.json
  6. upload all of it to this repo's release pnt-data-<YYYY-MM> (ODbL 1.0). <day>.map.json goes last and marks
     the day done; the site deploy collects those files.

adsb.lol publishes day D at about 03:30 UTC on D+1. Needs the GitHub CLI signed in, or GH_TOKEN set
(the workflow uses its own token). Days run oldest first, so each day's baselines include the day before.

Usage
  python pipeline/daily_job.py                          # latest missing days (what the schedule runs)
  python pipeline/daily_job.py 2026-10-07:2026-10-20    # a range
  python pipeline/daily_job.py 2026-09-22 --raw-dir data/raw/adsblol --no-upload   # local test: no download, no upload
  python pipeline/daily_job.py 2026-10-07:2026-10-21 --reanalyse    # rerun only the analyses on published days
  python pipeline/daily_job.py 2025-10-09:2025-10-25 --upload-local # publish days already processed on this PC
"""
import argparse, json, os, shutil, subprocess, sys, time, traceback
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pnt_analysis as A  # noqa: E402
import pnt_daily as P  # noqa: E402
from run_days import expand  # noqa: E402

REPO = os.environ.get("GITHUB_REPOSITORY", "metacog-osint/noise-floor")
DAILY, ANALYSIS = A.DAILY, A.OUT
SITE = os.path.join(ROOT, "data", "pnt", "site")
WORK = os.path.join(ROOT, "data", "raw", "daily_job")
NOTES = """GNSS degradation outputs for {month}, one set per UTC day, made automatically by the daily workflow
(`.github/workflows/daily.yml`) from the [adsb.lol](https://www.adsb.lol/) globe_history archive. Not reviewed by a person.

**Licence: ODbL 1.0**, derived from adsb.lol. Aggregates per H3 hex and region only: no aircraft identifiers.

Per day: `<day>.parquet` (per hex), `.hourly.parquet`, `.minute.parquet`, `.summary.json` (run details and method
parameters), `.sbas.json`, `.anomalies.json`, `.bursts.json`, `.hotspots.json` (shares in the named areas) and
`.map.json` (the site's map file).
Method: [method card](https://github.com/metacog-osint/noise-floor/blob/main/docs/method-card.md)."""


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout


def upstream(day):
    return f"adsblol/globe_history_{day[:4]}", f"v{day.replace('-', '.')}-planes-readsb-prod-0"


def data_tag(day):
    return f"pnt-data-{day[:7]}"


_ASSETS = {}


def assets(repo, tag):
    """{name: size} of a release's assets, or None if there is no such release."""
    if (repo, tag) not in _ASSETS:
        r = subprocess.run(["gh", "release", "view", tag, "-R", repo, "--json", "assets"],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            if "not found" not in (r.stderr or "").lower():
                raise RuntimeError(f"gh release view {tag} -R {repo}: {r.stderr.strip()[:400]}")
            _ASSETS[(repo, tag)] = None
        else:
            _ASSETS[(repo, tag)] = {a["name"]: a["size"] for a in json.loads(r.stdout)["assets"]}
    return _ASSETS[(repo, tag)]


def download_raw(day):
    repo, tag = upstream(day)
    up = assets(repo, tag) or {}
    parts = {n: s for n, s in up.items() if n.startswith(tag + ".tar")}
    if not parts:
        return None
    raw = os.path.join(WORK, day)
    os.makedirs(raw, exist_ok=True)
    gh("release", "download", tag, "-R", repo, "-p", f"{tag}.tar*", "-D", raw, "--clobber")
    for n, size in parts.items():
        got = os.path.getsize(os.path.join(raw, n))
        if got != size:
            raise RuntimeError(f"{n}: downloaded {got} bytes, release says {size}")
    return raw


def fetch_history(day):
    """Earlier days' hourly and minute tables and SBAS flags, from this repo's releases, where not already local."""
    d0, got = date.fromisoformat(day), 0
    for k in range(1, A.BASE_WINDOW + 1):
        d = (d0 - timedelta(days=k)).isoformat()
        for folder, name in ((DAILY, f"{d}.hourly.parquet"), (DAILY, f"{d}.minute.parquet"), (ANALYSIS, f"{d}.sbas.json")):
            if not os.path.exists(os.path.join(folder, name)) and name in (assets(REPO, data_tag(d)) or {}):
                os.makedirs(folder, exist_ok=True)
                gh("release", "download", data_tag(d), "-R", REPO, "-p", name, "-D", folder, "--clobber")
                got += 1
    return got


def outputs(day):
    return ([os.path.join(DAILY, f"{day}.{k}") for k in ("parquet", "hourly.parquet", "minute.parquet", "summary.json")]
            + [os.path.join(ANALYSIS, f"{day}.{k}") for k in ("sbas.json", "anomalies.json", "bursts.json")])


def upload(day):
    tag = data_tag(day)
    if assets(REPO, tag) is None:
        gh("release", "create", tag, "-R", REPO, "--title", f"GNSS degradation data, {day[:7]}",
           "--notes", NOTES.format(month=day[:7]), "--latest=false")
        _ASSETS[(REPO, tag)] = {}
    gh("release", "upload", tag, "-R", REPO, "--clobber", *outputs(day), os.path.join(SITE, f"{day}.hotspots.json"))
    gh("release", "upload", tag, "-R", REPO, "--clobber", os.path.join(SITE, f"{day}.map.json"))   # last: marks done
    _ASSETS.pop((REPO, tag), None)


def analyse(day):
    """pnt_analysis for one day, with earlier days fetched for the baselines. Returns (files fetched, its summary)."""
    hist = fetch_history(day)
    for p in outputs(day)[4:]:            # a rerun must not reuse the day's old SBAS flags
        if os.path.exists(p):
            os.remove(p)
    cmd = [sys.executable, os.path.join(HERE, "pnt_analysis.py"), day]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(f"pnt_analysis {day}: {r.stderr.strip()[-600:]}")
    return hist, json.loads(r.stdout.strip().splitlines()[-1])


def reanalyse(day, a):
    """Rerun only the analyses on a published day (after the analysis code changes): no adsb.lol download."""
    t0, tag = time.time(), data_tag(day)
    have = assets(REPO, tag) or {}
    if f"{day}.map.json" not in have:
        return {"day": day, "status": "not published; nothing to reanalyse"}
    for name in (f"{day}.parquet", f"{day}.hourly.parquet", f"{day}.minute.parquet"):
        if not os.path.exists(os.path.join(DAILY, name)):
            os.makedirs(DAILY, exist_ok=True)
            gh("release", "download", tag, "-R", REPO, "-p", name, "-D", DAILY, "--clobber")
    hist, an = analyse(day)
    import export_site_data as E
    E.hotspot_day(day, os.path.join(SITE, f"{day}.hotspots.json"))
    if not a.no_upload:
        gh("release", "upload", tag, "-R", REPO, "--clobber", *outputs(day)[4:], os.path.join(SITE, f"{day}.hotspots.json"))
        _ASSETS.pop((REPO, tag), None)
    return {"day": day, "status": "reanalysed" if not a.no_upload else "reanalysed (not uploaded)", "history_files": hist,
            "baseline_days": an.get("baseline_days"), "anomaly_region_hours": an.get("anomaly_region_hours"),
            "burst_events": an.get("burst_events"), "total_s": round(time.time() - t0)}


def upload_local(day, a):
    """Publish a day already processed and analysed here (data/pnt): site files, then the release upload."""
    missing = [p for p in outputs(day) if not os.path.exists(p)]
    if missing:
        return {"day": day, "status": f"missing local outputs: {', '.join(os.path.basename(p) for p in missing)}"}
    import export_site_data as E
    E.map_day(day, os.path.join(SITE, f"{day}.map.json"))
    E.hotspot_day(day, os.path.join(SITE, f"{day}.hotspots.json"))
    if a.no_upload:
        return {"day": day, "status": "done (not uploaded)"}
    upload(day)
    return {"day": day, "status": "published"}


def process(day, a):
    t0 = time.time()
    raw = a.raw_dir or download_raw(day)
    if raw is None:
        return {"day": day, "status": "not published yet"}
    t_dl = time.time() - t0
    try:
        s = P.run(day, raw, DAILY, a.workers)
    finally:
        if not a.raw_dir and not a.keep_raw:
            shutil.rmtree(raw, ignore_errors=True)
    hist, an = analyse(day)
    import export_site_data as E
    size, hexes, jam = E.map_day(day, os.path.join(SITE, f"{day}.map.json"))
    E.hotspot_day(day, os.path.join(SITE, f"{day}.hotspots.json"))
    if not a.no_upload:
        upload(day)
    return {"day": day, "status": "published" if not a.no_upload else "done (not uploaded)",
            "aircraft": s["aircraft"], "hexes_5plus": hexes, "jam_hexes": jam, "history_files": hist,
            "baseline_days": an.get("baseline_days"), "anomaly_region_hours": an.get("anomaly_region_hours"),
            "burst_events": an.get("burst_events"), "download_s": round(t_dl), "process_s": s["seconds"],
            "total_s": round(time.time() - t0)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("days", nargs="*", help="YYYY-MM-DD or START:END (default: the last --lookback days)")
    ap.add_argument("--lookback", type=int, default=7)
    ap.add_argument("--force", action="store_true", help="redo days that are already published")
    ap.add_argument("--reanalyse", action="store_true", help="rerun only the analyses on published days")
    ap.add_argument("--upload-local", action="store_true", help="publish days already processed on this machine")
    ap.add_argument("--raw-dir", help="use local adsb.lol files instead of downloading")
    ap.add_argument("--keep-raw", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    today = datetime.now(timezone.utc).date()
    days = sorted(set(expand(a.days))) if a.days else [(today - timedelta(days=k)).isoformat() for k in range(a.lookback, 0, -1)]
    results, failed = [], False
    for day in days:
        if not a.force and not a.reanalyse and not a.no_upload and f"{day}.map.json" in (assets(REPO, data_tag(day)) or {}):
            continue
        try:
            r = reanalyse(day, a) if a.reanalyse else upload_local(day, a) if a.upload_local else process(day, a)
        except Exception as e:
            traceback.print_exc()
            r, failed = {"day": day, "status": f"ERROR {e.__class__.__name__}: {e}"[:300]}, True
        print(json.dumps(r), flush=True)
        results.append(r)
    done = [r["day"] for r in results if r["status"] in ("published", "reanalysed")]
    print(json.dumps({"published": done, "checked": len(days)}))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"changed={'true' if done else 'false'}\npublished={' '.join(done)}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("| Day | Status | Aircraft | Hexes (5+) | Jamming-scale hexes | Baseline days | Minutes |\n|---|---|---|---|---|---|---|\n")
            for r in results:
                f.write(f"| {r['day']} | {r['status']} | {r.get('aircraft', '')} | {r.get('hexes_5plus', '')} | "
                        f"{r.get('jam_hexes', '')} | {r.get('baseline_days', '')} | {round(r['total_s'] / 60, 1) if 'total_s' in r else ''} |\n")
            if not results:
                f.write(f"| (none) | nothing new in the last {len(days)} days | | | | | |\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
