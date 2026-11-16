#!/usr/bin/env python3
"""site_layers.py: the map page's spoofing, CYGNSS, NISAR, Sentinel-6, SMAP, COSMIC-2, Sentinel-1, limb S4 and ROTI layers, at deploy.

  python3 tools/site_layers.py RELEASE_DIR [SITE]

Copies RELEASE_DIR/<day>.<kind>.json -> SITE/data/<folder>/<day>.json and writes an index.json of the days in each folder:
- spoof -> data/spoof (only files that carry map cells). tools/spoof_day.py through pipeline/daily_job.py --spoofing
  (ODbL, from adsb.lol).
- cygnss -> data/cygnss (only files that carry map cells). tools/cygnss_daily.py (derived from NASA CYGNSS L1,
  NASA open data).
- nisar -> data/nisar (files with a "sites" list, even an empty one). nisar_rfi export, from the nisar-data release
  (derived from NASA-ISRO NISAR, NASA open data, CC0). Each file is a snapshot of every public repeat site so far;
  the map filters it to its own window.
- s6 -> data/s6 (only files that carry map cells). tools/s6_daily.py, from the s6-data release (derived from
  Copernicus Sentinel-6A receiver data via PO.DAAC; region-scale scores, docs/validation/space-receivers.md).
- smap -> data/smap (files with a "sources" list, even an empty one). tools/smap_daily.py, from the smap-data release
  (derived from NASA SMAP L1C, NSIDC DAAC, NASA open data; docs/validation/smap-rfi.md).
- cosmic2 -> data/cosmic2 (only files that carry map cells). tools/cosmic2_daily.py, from the cosmic2-data release
  (derived from UCAR CDAAC COSMIC-2, CC BY 4.0; region-scale scores, docs/validation/space-receivers.md).
- s1 -> data/s1 (files with a "cells" list, even an empty one). tools/s1_daily.py, from the s1-data release (derived
  from Copernicus Sentinel-1 RFI annotations; C-band radar activity by region, docs/validation/s1-rfi.md).
- cosmic2-limb-s4 -> data/limbs4 and ground-roti -> data/roti (files with "hours"), slimmed for the map by
  tools/swx_site.py (limb_map, roti_map), from the swx-data releases (Tom approved 16 Nov 2026). Limb S4 is measured
  along radio-occultation paths and reads higher than a ground receiver's S4; ROTI is a measured TEC fluctuation index
  at fixed stations, never an S4 value. Neither is read against S4 alert levels.
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
         "nisar": ("nisar", "Derived from NASA-ISRO NISAR (ASF DAAC), NASA open data, CC0", "sites", False),
         "s6": ("s6", "Derived from Copernicus Sentinel-6A data (PO.DAAC, doi:10.5067/S6AGN-1ROPD); contains modified "
                "Copernicus Sentinel data", "cells", True),
         "smap": ("smap", "Derived from NASA SMAP L1C (NSIDC DAAC, doi:10.5067/DV7IX2DQ681Y), NASA open data", "sources", False),
         "cosmic2": ("cosmic2", "Derived from UCAR CDAAC COSMIC-2 data (CC BY 4.0)", "cells", True),
         "s1": ("s1", "Derived from Copernicus Sentinel-1 Level-1 annotations; contains modified Copernicus Sentinel data",
                "cells", False),
         "cosmic2-limb-s4": ("limbs4", "CC BY 4.0. Derived from UCAR CDAAC COSMIC-2 data", "hours", False),
         "ground-roti": ("roti", "CC BY 4.0. Derived from IGS station data via BKG; credit the IGS and the station "
                         "operators", "hours", False)}
SLIM = {"cosmic2-limb-s4": "limb_map", "ground-roti": "roti_map"}    # swx_site.py: the map needs a day summary only


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
            if kind in SLIM:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import swx_site
                d = getattr(swx_site, SLIM[kind])(d)
            d.setdefault("licence", licence)
            with open(os.path.join(out, f"{day}.json"), "w", encoding="utf-8", newline="\n") as g:
                json.dump(d, g, ensure_ascii=False, separators=(",", ":"))
            days.append(day)
        with open(os.path.join(out, "index.json"), "w", encoding="utf-8", newline="\n") as g:
            json.dump({"days": days, "licence": licence}, g, separators=(",", ":"))
        print(f"{kind}: {len(days)} days with map {key} -> {os.path.relpath(out, site)}")


if __name__ == "__main__":
    main()
