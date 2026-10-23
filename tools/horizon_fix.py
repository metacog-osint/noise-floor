#!/usr/bin/env python3
"""horizon_fix.py: locate a ground GNSS jammer from where aircraft lose and regain their positions (first version).

Principle (radio horizon; Schaefer et al., "Jammer on the Horizon", ION GNSS+ 2023, and the 2024 Baltic open-source
work in docs/research/2026-10-14-baltic-jammer-2024.md): an aircraft at height h first comes into a ground jammer's
line of sight at about r = 4.12 * (sqrt(h_rx) + sqrt(h_tx)) km (heights in metres, standard refraction). So the
jammer lies near a circle of radius r around the aircraft's last good position before it degrades or goes dark,
and ahead of it; and near the circle around its first good position after recovery, behind it. Each event votes for
the grid cells on its circle arc; where many arcs cross is the candidate.

  python tools/horizon_fix.py <day> [<day> ...] [--control <day>] [--grid lat0,lat1,lon0,lon1]
  python tools/horizon_fix.py <day> --fit --nacp-only [--hours 16-22] [--target name:lat,lon]   # reach fitted, scored

--fit (onsets only by default) fits the reach jointly with the location instead of assuming one; it is the mode
scored against the 2025 TDOA fixes in docs/validation/phase1.md (verdict 41: it finds the area, not the site).

Input: data/trace_box/<day>.jsonl.gz from tools/trace_box.py extract (ADS-B points with NACp). This is a first
version: a jammer whose power, not the horizon, limits its reach puts the arcs too far out, and coverage gaps add
false events (the control day shows that background).
"""
import argparse, gzip, json, math, os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACES = os.path.join(ROOT, "data", "trace_box")
R_EARTH = 6371.0
KNOWN = {"Kaliningrad city": (54.71, 20.51), "Baltiysk": (54.65, 19.91), "Sambia peninsula coast": (54.95, 20.2),
         "St Petersburg": (59.94, 30.31), "Bornholm": (55.1, 14.9)}


def parse_box(s):
    v = tuple(float(x) for x in s.split(","))
    assert len(v) == 4
    return v


def bearing(a, b):
    p1, p2, dl = math.radians(a[0]), math.radians(b[0]), math.radians(b[1] - a[1])
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360


def events(day, min_alt, gap_s, h_tx, nacp_only=False, scale=1.0):
    """[(lat, lon, radius_km, heading_deg, kind, t)] where kind is 'onset' (jammer ahead) or 'recovery' (behind).
    nacp_only: only NACp drops and recoveries between consecutive positions, not gaps (coverage gaps look like gaps)."""
    if nacp_only:
        gap_s = float("inf")
    out = []
    with gzip.open(os.path.join(TRACES, f"{day}.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            a = json.loads(line)
            pts = sorted((p for p in a["pts"] if p[4] == "a" and p[5] is not None and isinstance(p[3], (int, float))
                          and p[3] >= min_alt), key=lambda p: p[0])
            for i in range(1, len(pts) - 1):
                p, q = pts[i], pts[i + 1]
                good_p, good_q = p[5] >= 8, q[5] >= 8
                lost = good_p and (q[0] - p[0] > gap_s or not good_q)
                back = good_q and (q[0] - p[0] > gap_s or not good_p)
                if lost and pts[i - 1][5] >= 8:
                    hdg = bearing(pts[i - 1][1:3], p[1:3])
                    out.append((p[1], p[2], scale * 4.12 * (math.sqrt(p[3] * 0.3048) + math.sqrt(h_tx)), hdg, "onset", p[0]))
                if back and i + 2 < len(pts) and pts[i + 2][5] >= 8:
                    hdg = bearing(q[1:3], pts[i + 2][1:3])
                    out.append((q[1], q[2], scale * 4.12 * (math.sqrt(q[3] * 0.3048) + math.sqrt(h_tx)), hdg, "recovery", q[0]))
    return out


def vote(evs, grid, step, tol_km, cone):
    lat = np.arange(grid[0], grid[1] + 1e-9, step)
    lon = np.arange(grid[2], grid[3] + 1e-9, step * 1.6)          # roughly square cells at 55-60N
    LA, LO = np.meshgrid(np.radians(lat), np.radians(lon), indexing="ij")
    votes = np.zeros(LA.shape)
    for la, lo, r, hdg, kind, *_ in evs:
        p1, l1 = math.radians(la), math.radians(lo)
        dl = LO - l1
        d = 2 * R_EARTH * np.arcsin(np.sqrt(np.clip(np.sin((LA - p1) / 2) ** 2 + math.cos(p1) * np.cos(LA) * np.sin(dl / 2) ** 2, 0, 1)))
        brg = np.degrees(np.arctan2(np.sin(dl) * np.cos(LA), math.cos(p1) * np.sin(LA) - math.sin(p1) * np.cos(LA) * np.cos(dl))) % 360
        want = hdg if kind == "onset" else (hdg + 180) % 360
        off = np.abs((brg - want + 180) % 360 - 180)
        votes += (np.abs(d - r) <= tol_km) & (off <= cone)
    return lat, lon, votes


def fit(evs, grid, step, cone, kmin=0.3, kmax=1.3, dk=0.02, win=0.05, both=False):
    """Reach estimated from the data. For each candidate cell, take the events whose heading points at it (onsets
    ahead, recoveries behind, +-cone) and the ratio q = distance / radio horizon of each; the reach fraction k is the
    value most of them agree on (the fullest window of +-win in q). The cell's score is how many agree. No reach is
    assumed: a horizon-limited jammer gives k near 1, a power-limited one less.
    both: score on the smaller of the onset and recovery counts at one k. Off by default: receivers take time to
    recover after leaving jamming, so recoveries sit farther out than onsets and the two don't share a k."""
    lat = np.arange(grid[0], grid[1] + 1e-9, step)
    lon = np.arange(grid[2], grid[3] + 1e-9, step * 1.6)
    E = np.array([(math.radians(e[0]), math.radians(e[1]), e[2], (e[3] if e[4] == "onset" else e[3] + 180) % 360,
                   e[4] == "onset") for e in evs]) if evs else np.zeros((0, 5))
    p1, l1, r, want, ons = (E[:, k] for k in range(5))
    ons = ons.astype(bool)
    bins = np.arange(kmin, kmax + dk / 2, dk)
    w = int(round(2 * win / dk)) + 1
    score, kbest = np.zeros((len(lat), len(lon))), np.zeros((len(lat), len(lon)))
    for i, la in enumerate(np.radians(lat)):
        for j, lo in enumerate(np.radians(lon)):
            dl = lo - l1
            d = 2 * R_EARTH * np.arcsin(np.sqrt(np.clip(np.sin((la - p1) / 2) ** 2 + np.cos(p1) * math.cos(la) * np.sin(dl / 2) ** 2, 0, 1)))
            brg = np.degrees(np.arctan2(np.sin(dl) * math.cos(la), np.cos(p1) * math.sin(la) - np.sin(p1) * math.cos(la) * np.cos(dl))) % 360
            m = (np.abs((brg - want + 180) % 360 - 180) <= cone) & (d <= kmax * r)
            if not m.any():
                continue
            q = d / r
            if both:
                ho = np.convolve(np.histogram(q[m & ons], bins=bins)[0], np.ones(w), mode="same")
                hr = np.convolve(np.histogram(q[m & ~ons], bins=bins)[0], np.ones(w), mode="same")
                h = 2 * np.minimum(ho, hr)
            else:
                h = np.convolve(np.histogram(q[m], bins=bins)[0], np.ones(w), mode="same")
            b = int(h.argmax())
            score[i, j], kbest[i, j] = h[b], (bins[b] + bins[b + 1]) / 2
    return lat, lon, score, kbest


def cell_of(lat, lon, la, lo):
    return int(np.abs(lat - la).argmin()), int(np.abs(lon - lo).argmin())


def peaks(lat, lon, v, n=5, sep_km=100):
    out, flat = [], np.argsort(v, axis=None)[::-1]
    for k in flat:
        i, j = np.unravel_index(k, v.shape)
        la, lo = lat[i], lon[j]
        if v[i, j] <= 0:
            break
        if all(km(la, lo, a, b) >= sep_km for a, b, _ in out):
            out.append((la, lo, v[i, j]))
        if len(out) == n:
            break
    return out


def km(a, b, c, d):
    p1, p2 = math.radians(a), math.radians(c)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2
    return 2 * R_EARTH * math.asin(min(1, math.sqrt(h)))


def nearest(la, lo):
    name, (a, b) = min(KNOWN.items(), key=lambda kv: km(la, lo, *kv[1]))
    return f"{km(la, lo, a, b):.0f} km from {name}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("days", nargs="+")
    ap.add_argument("--control", help="a quiet day: its votes on the same grid show the background")
    ap.add_argument("--grid", type=parse_box, default=(50.0, 62.0, 5.0, 35.0))
    ap.add_argument("--step", type=float, default=0.05, help="grid step in degrees of latitude")
    ap.add_argument("--min-alt", type=int, default=20000)
    ap.add_argument("--gap", type=float, default=4.0, help="minutes without a position that count as lost")
    ap.add_argument("--tol", type=float, default=20.0, help="km either side of the horizon circle")
    ap.add_argument("--cone", type=float, default=60.0, help="degrees either side of the heading (or its reverse)")
    ap.add_argument("--h-tx", type=float, default=30.0, help="assumed jammer height, metres")
    ap.add_argument("--nacp-only", action="store_true", help="use NACp drops and recoveries only, not position gaps")
    ap.add_argument("--stack", action="store_true", help="add all the days into one vote map (with a bootstrap spread)")
    ap.add_argument("--fit", action="store_true", help="estimate the reach from the data, jointly with the location")
    ap.add_argument("--hours", help="UTC hours to keep, e.g. 16-22 (events outside are dropped)")
    ap.add_argument("--kinds", choices=["all", "onset", "recovery"], default="onset",
                    help="--fit: which events to use (default onsets: recoveries lag while receivers re-acquire)")
    ap.add_argument("--target", action="append", default=[], help="name:lat,lon to score against (repeatable)")
    ap.add_argument("--boot", type=int, default=20, help="bootstrap resamples for --stack")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="fraction of the radio horizon used as the jammer's reach (below 1 when power, not the horizon, limits it)")
    a = ap.parse_args()
    ctrl = None
    if a.control:
        ce = events(a.control, a.min_alt, a.gap * 60, a.h_tx, a.nacp_only, a.scale)
        _, _, ctrl = vote(ce, a.grid, a.step, a.tol, a.cone)
        print(f"control {a.control}: {len(ce)} events")
    if a.fit:
        h0, h1 = (int(x) for x in a.hours.split("-")) if a.hours else (0, 23)
        targets = [(t.split(":")[0], *(float(x) for x in t.split(":")[1].split(","))) for t in a.target]
        for day in a.days:
            evs = [e for e in events(day, a.min_alt, a.gap * 60, a.h_tx, a.nacp_only) if h0 <= int(e[5] % 86400 // 3600) <= h1
                   and a.kinds in ("all", e[4])]
            lat, lon, s, k = fit(evs, a.grid, a.step, a.cone)
            print(f"{day} ({h0:02d}-{h1:02d}Z): {len(evs)} events")
            top = peaks(lat, lon, s)
            for la, lo, n in top:
                i, j = cell_of(lat, lon, la, lo)
                print(f"  {la:.2f}N {lo:.2f}E: {n:.0f} agreeing, reach {k[i, j]:.2f} of the horizon ({nearest(la, lo)})")
            for name, tla, tlo in targets:
                i, j = cell_of(lat, lon, tla, tlo)
                rank = int((s > s[i, j]).sum()) + 1
                print(f"  target {name}: {km(top[0][0], top[0][1], tla, tlo):.0f} km from the top peak; "
                      f"its own cell scores {s[i, j]:.0f} (rank {rank} of {s.size}, top {100 * rank / s.size:.1f}%), reach {k[i, j]:.2f}")
            if a.boot and top:
                rng = np.random.default_rng(1)
                ds = []
                for _ in range(a.boot):
                    pick = [evs[q] for q in rng.integers(0, len(evs), len(evs))]
                    bl, bo, _ = peaks(*fit(pick, a.grid, a.step, a.cone)[:3], n=1)[0]
                    ds.append(km(top[0][0], top[0][1], bl, bo))
                ds.sort()
                print(f"  bootstrap ({a.boot}): top peak moves a median {ds[len(ds) // 2]:.0f} km, 90% within {ds[int(0.9 * (len(ds) - 1))]:.0f} km")
        return
    if a.stack:                                       # one vote map over all the days, and a bootstrap spread
        allev = [e for day in a.days for e in events(day, a.min_alt, a.gap * 60, a.h_tx, a.nacp_only, a.scale)]
        lat, lon, v = vote(allev, a.grid, a.step, a.tol, a.cone)
        top = peaks(lat, lon, v)
        print(f"stacked {', '.join(a.days)}: {len(allev)} events")
        for la, lo, n in top:
            print(f"  {la:.2f}N {lo:.2f}E: {n:.0f} votes ({nearest(la, lo)})")
        rng = np.random.default_rng(1)
        fixes = []
        for _ in range(a.boot):
            pick = [allev[k] for k in rng.integers(0, len(allev), len(allev))]
            la, lo, n = peaks(*vote(pick, a.grid, a.step, a.tol, a.cone), n=1)[0]
            fixes.append((la, lo))
        if fixes:
            d = sorted(km(top[0][0], top[0][1], la, lo) for la, lo in fixes)
            print(f"  bootstrap ({a.boot} resamples): median {d[len(d) // 2]:.0f} km, 90% within {d[int(0.9 * (len(d) - 1))]:.0f} km of the top peak")
        return
    for day in a.days:
        evs = events(day, a.min_alt, a.gap * 60, a.h_tx, a.nacp_only, a.scale)
        lat, lon, v = vote(evs, a.grid, a.step, a.tol, a.cone)
        kinds = {k: sum(1 for e in evs if e[4] == k) for k in ("onset", "recovery")}
        print(f"{day}: {len(evs)} events ({kinds['onset']} onsets, {kinds['recovery']} recoveries)")
        for la, lo, n in peaks(lat, lon, v):
            c = ""
            if ctrl is not None:
                i, j = int(round((la - lat[0]) / a.step)), int(round((lo - lon[0]) / (a.step * 1.6)))
                c = f"; control {ctrl[i, j]:.0f}"
            print(f"  {la:.2f}N {lo:.2f}E: {n:.0f} votes{c} ({nearest(la, lo)})")
        if ctrl is not None:                              # excess over the control, scaled by event counts
            scale = len(evs) / max(1, len(ce))
            ex = v - scale * ctrl
            print("  excess over control:")
            for la, lo, n in peaks(lat, lon, ex):
                print(f"    {la:.2f}N {lo:.2f}E: {n:.0f} ({nearest(la, lo)})")


if __name__ == "__main__":
    main()
