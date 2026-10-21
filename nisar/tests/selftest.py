"""End-to-end self-test on synthetic NISAR GCOV files. No network needed.

Simulates four daily runs (one new pass each), then checks:
  - no detections on the clean passes (calm water and wind front included)
  - J1 found, band A only, alerted as NEW on its first pass
  - R1 found, band B only, alerted as NEW on its first pass
  - J1 cross-fixed from the ascending + descending passes
Writes out/map.html with the SYNTHETIC banner.

  python tests/selftest.py [workdir]
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from nisar_rfi import geometry as geo, pipeline  # noqa: E402
from make_fixtures import PASSES, TRUTH  # noqa: E402


def main():
    work = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "_selftest")
    fx, stage = os.path.join(work, "fixtures"), os.path.join(work, "stage")
    if not all(os.path.exists(os.path.join(fx, f'{p["name"]}.h5')) for p in PASSES):
        subprocess.check_call([sys.executable, os.path.join(HERE, "make_fixtures.py"), fx])
    for d in ("stage", "state", "out"):
        shutil.rmtree(os.path.join(work, d), ignore_errors=True)
    os.makedirs(stage)
    cfg = json.load(open(os.path.join(HERE, "..", "config.example.json")))
    cfg.update(state_dir=os.path.join(work, "state"), out_dir=os.path.join(work, "out"), demo=True,
               truth=[{k: t[k] for k in ("lat", "lon", "label")} for t in TRUTH])
    cfg["aoi"] = {"name": "Synthetic test", "bbox": [18.5, 53.8, 22.5, 55.6]}
    cfg["sites"]["site_prefix"] = "T"

    results, fails = [], []
    for i, p in enumerate(PASSES):
        shutil.copy(os.path.join(fx, f'{p["name"]}.h5'), stage)
        now = datetime.fromisoformat(p["start"]).replace(tzinfo=timezone.utc) + timedelta(hours=20)
        state, alerts = pipeline.run(cfg, local_dir=stage, now=now, log=lambda m: None)
        g = max(state["processed"].values(), key=lambda v: v["start"])
        dets = [d for d in state["detections"] if d["start"].startswith(p["start"][:10])]
        results.append((p, dets, alerts))
        print(f'{p["name"]} {p["start"][:10]} {p["dir"]}  emitters on: {",".join(p["on"]) or "none":6}  '
              f'-> {len(dets)} detection(s), {g.get("rejected", 0)} candidate(s) rejected, {len(alerts)} alert(s)')
        for d in dets:
            t = min(TRUTH, key=lambda t: geo.km_between(d["lat"], d["lon"], t["lat"], t["lon"]))
            off = geo.km_between(d["lat"], d["lon"], t["lat"], t["lon"])
            print(f'     {d["site"]}  band {"+".join(d["bands"]):3}  {d["confidence"]:6}  {off:4.1f} km from {t["id"]}  '
                  f'[{"; ".join(d["evidence"])}]')
        for a in alerts:
            print(f'     ALERT {a["title"]}')

    # checks
    def det(name):
        return next(r for r in results if r[0]["name"] == name)
    for name in ("P1", "P2"):
        if det(name)[1]:
            fails.append(f"{name}: expected no detections")
    for name, tid, band in (("P3", "J1", ["A"]), ("P4", "J1", ["A"]), ("P4", "R1", ["B"])):
        t = next(t for t in TRUTH if t["id"] == tid)
        hit = [d for d in det(name)[1] if geo.km_between(d["lat"], d["lon"], t["lat"], t["lon"]) < 12]
        if not hit:
            fails.append(f"{name}: {tid} not detected")
        elif hit[0]["bands"] != band:
            fails.append(f"{name}: {tid} bands {hit[0]['bands']} != {band}")
    titles = [a["title"] for r in results for a in r[2]]
    if sum("New" in t for t in titles) != 2:
        fails.append(f"expected 2 NEW alerts, got {titles}")
    st = json.load(open(os.path.join(work, "state", "state.json")))
    j1 = next(t for t in TRUTH if t["id"] == "J1")
    site = min(st["sites"].values(), key=lambda s: geo.km_between(s["lat"], s["lon"], j1["lat"], j1["lon"]))
    if site.get("fix"):
        err = geo.km_between(site["fix"]["lat"], site["fix"]["lon"], j1["lat"], j1["lon"])
        print(f'\nJ1 cross-fix: {site["fix"]["lat"]}, {site["fix"]["lon"]} (stated ±{site["fix"]["error_km"]} km, '
              f'crossing {site["fix"]["crossing_deg"]}°) — actual error {err:.1f} km')
        if err > 3 * max(site["fix"]["error_km"], 1):
            fails.append("J1 fix error exceeds stated uncertainty x3")
    else:
        fails.append("J1 has no cross-fix")
    print(f'map: {os.path.join(work, "out", "map.html")}')
    print("\nPASS" if not fails else "\nFAIL\n  " + "\n  ".join(fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
