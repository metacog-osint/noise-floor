#!/usr/bin/env python3
"""site_layers.py: the map page's spoofing and CYGNSS layers, at deploy.

  python3 tools/site_layers.py RELEASE_DIR [SITE]

Copies RELEASE_DIR/<day>.spoof.json -> SITE/data/spoof/<day>.json and RELEASE_DIR/<day>.cygnss.json ->
SITE/data/cygnss/<day>.json (only files that carry map cells), and writes an index.json of the days in each folder.
Standard library only. Spoofing: tools/spoof_day.py through pipeline/daily_job.py --spoofing (ODbL, from adsb.lol);
CYGNSS: tools/cygnss_daily.py (derived from NASA CYGNSS L1, NASA open data).
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KINDS = {"spoof": ("spoof", "ODbL 1.0; derived from adsb.lol"), "cygnss": ("cygnss", "Derived from NASA CYGNSS L1 V3.2 (NASA open data)")}


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    release = sys.argv[1]
    site = sys.argv[2] if len(sys.argv) == 3 else os.path.join(ROOT, "site")
    for kind, (folder, licence) in KINDS.items():
        out = os.path.join(site, "data", folder)
        os.makedirs(out, exist_ok=True)
        days = []
        for f in sorted(glob.glob(os.path.join(release, f"*.{kind}.json"))):
            day = os.path.basename(f)[:10]
            try:
                d = json.load(open(f, encoding="utf-8"))
            except ValueError:
                continue
            if not d.get("cells"):
                continue                       # summaries made before the map layer have no cells
            d.setdefault("licence", licence)
            with open(os.path.join(out, f"{day}.json"), "w", encoding="utf-8", newline="\n") as g:
                json.dump(d, g, separators=(",", ":"))
            days.append(day)
        with open(os.path.join(out, "index.json"), "w", encoding="utf-8", newline="\n") as g:
            json.dump({"days": days, "licence": licence}, g, separators=(",", ":"))
        print(f"{kind}: {len(days)} days with map cells -> {os.path.relpath(out, site)}")


if __name__ == "__main__":
    main()
