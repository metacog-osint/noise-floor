#!/usr/bin/env python3
"""site_layers.py: the map page's spoofing, CYGNSS and NISAR layers, at deploy.

  python3 tools/site_layers.py RELEASE_DIR [SITE]

Copies RELEASE_DIR/<day>.<kind>.json -> SITE/data/<folder>/<day>.json and writes an index.json of the days in each folder:
- spoof -> data/spoof (only files that carry map cells). tools/spoof_day.py through pipeline/daily_job.py --spoofing
  (ODbL, from adsb.lol).
- cygnss -> data/cygnss (only files that carry map cells). tools/cygnss_daily.py (derived from NASA CYGNSS L1,
  NASA open data).
- nisar -> data/nisar (files with a "sites" list, even an empty one). nisar_rfi export, from the nisar-data release
  (derived from NASA-ISRO NISAR, NASA open data, CC0). Each file is a snapshot of every public repeat site so far;
  the map filters it to its own window.
Standard library only.
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# kind: (folder, licence, key the file must carry, whether that key must be non-empty)
KINDS = {"spoof": ("spoof", "ODbL 1.0; derived from adsb.lol", "cells", True),
         "cygnss": ("cygnss", "Derived from NASA CYGNSS L1 V3.2 (NASA open data)", "cells", True),
         "nisar": ("nisar", "Derived from NASA-ISRO NISAR (ASF DAAC), NASA open data, CC0", "sites", False)}


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    release = sys.argv[1]
    site = sys.argv[2] if len(sys.argv) == 3 else os.path.join(ROOT, "site")
    for kind, (folder, licence, key, nonempty) in KINDS.items():
        out = os.path.join(site, "data", folder)
        os.makedirs(out, exist_ok=True)
        days = []
        for f in sorted(glob.glob(os.path.join(release, f"*.{kind}.json"))):
            day = os.path.basename(f)[:10]
            try:
                d = json.load(open(f, encoding="utf-8"))
            except ValueError:
                continue
            if key not in d or (nonempty and not d[key]):
                continue                       # spoof/CYGNSS summaries made before the map layer have no cells
            d.setdefault("licence", licence)
            with open(os.path.join(out, f"{day}.json"), "w", encoding="utf-8", newline="\n") as g:
                json.dump(d, g, ensure_ascii=False, separators=(",", ":"))
            days.append(day)
        with open(os.path.join(out, "index.json"), "w", encoding="utf-8", newline="\n") as g:
            json.dump({"days": days, "licence": licence}, g, separators=(",", ":"))
        print(f"{kind}: {len(days)} days with map {key} -> {os.path.relpath(out, site)}")


if __name__ == "__main__":
    main()
