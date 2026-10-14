"""Spike: process one day of adsb.lol readsb traces into per-hex GNSS-degradation rates.

Measures throughput on this PC and sanity-checks the method against known hotspots.
Per aircraft per hex: a report is 'bad' if NACp < 8 (also tracked: NIC < 7).
An aircraft is bad in a hex if >= 50% of its reports there are bad.
Hex score follows gpsjam's published formula: 100 * (bad - 1) / (good + bad).
"""
import gzip, os, sys, time, csv
from collections import defaultdict
from multiprocessing import Pool

import h3, orjson

TRACES = os.environ["TRACES_DIR"]  # folder of unpacked adsb.lol traces (00..ff)
RES = 4
GOOD_TYPES = {"adsb_icao"}
SAMPLE_S = float(os.environ.get("SAMPLE_S", "0"))


def process_folder(folder):
    hexes = defaultdict(lambda: [0, 0, 0])  # hex -> [aircraft, bad_nacp, bad_nic]
    stats = [0, 0, 0]  # files, reports seen, reports used
    path = os.path.join(TRACES, folder)
    for name in os.listdir(path):
        stats[0] += 1
        with open(os.path.join(path, name), "rb") as f:
            raw = f.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        d = orjson.loads(raw)
        if d.get("icao", "~").startswith("~"):
            continue
        nacp = nic = ver = None
        last_t = -1e9
        per_hex = defaultdict(lambda: [0, 0, 0])  # hex -> [reports, bad_nacp, bad_nic]
        for p in d.get("trace", []):
            stats[1] += 1
            det = p[8]
            if det:
                nacp = det.get("nac_p", nacp)
                nic = det.get("nic", nic)
                ver = det.get("version", ver)
            if p[0] - last_t < SAMPLE_S:
                continue
            if p[9] not in GOOD_TYPES or ver != 2 or nacp is None or nic is None:
                continue
            last_t = p[0]
            alt = p[3]
            if alt == "ground" or alt is None or alt < 1000:
                continue
            stats[2] += 1
            c = per_hex[h3.latlng_to_cell(p[1], p[2], RES)]
            c[0] += 1
            c[1] += nacp < 8
            c[2] += nic < 7
        for hx, (n, bn, bi) in per_hex.items():
            agg = hexes[hx]
            agg[0] += 1
            agg[1] += bn * 2 >= n
            agg[2] += bi * 2 >= n
    return dict(hexes), stats


def main():
    folders = sorted(os.listdir(TRACES))
    if len(sys.argv) > 1:
        folders = folders[: int(sys.argv[1])]
    t0 = time.time()
    total = defaultdict(lambda: [0, 0, 0])
    st = [0, 0, 0]
    with Pool(8) as pool:
        for hexes, s in pool.imap_unordered(process_folder, folders):
            for hx, v in hexes.items():
                a = total[hx]
                a[0] += v[0]; a[1] += v[1]; a[2] += v[2]
            st = [x + y for x, y in zip(st, s)]
    dt = time.time() - t0
    print(f"folders={len(folders)} files={st[0]} reports={st[1]:,} used={st[2]:,} hexes={len(total)} seconds={dt:.0f}")
    out = os.path.join(os.path.dirname(__file__), "spike_2025-10-16_res4.csv")
    rows = []
    for hx, (n, bn, bi) in total.items():
        lat, lon = h3.cell_to_latlng(hx)
        pct = 100 * max(bn - 1, 0) / n
        rows.append((hx, round(lat, 2), round(lon, 2), n, bn, bi, round(pct, 1)))
    rows.sort(key=lambda r: -r[6])
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["h3", "lat", "lon", "aircraft", "bad_nacp", "bad_nic", "pct_bad_nacp"])
        w.writerows(rows)
    print("top hexes with >= 10 aircraft:")
    for r in [r for r in rows if r[3] >= 10][:30]:
        print(r)


if __name__ == "__main__":
    main()
