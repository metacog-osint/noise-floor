#!/usr/bin/env python3
"""chayka.py — Loran-C / Chayka on-air status from the DF6NM DL0AO monitor image (private watch).

Ported from Tom's emso-watch Chayka logger (chayka_lib.py + chayka_log.py, 14 Oct 2026 live fixes). Called by
collectors/watch.py once a day; it can also run on its own.

The image (DL0AO grabber, Amberg DE, 88-112 kHz, updated every 15 min by DF6NM):
  * 1344 px wide = 42 tracks x 32 px, in the order of TRACKS below.
  * Time runs bottom-to-top: row 0 (top) is the newest sample, nominally 5 min per row; it spans ~5 days.
  * Brightness = field strength; the left strip carries a day-of-month label about once per 24 h of rows.

Each run downloads the image, scores every track, appends the 5-minute rows newer than the last logged one to
chayka_rows.csv (one 0/1 column per track), keeps one raw image per UTC day in archive/, and writes latest.json:
the watch chains' (8000 Western, 5990 Southern) state, 24-h ON%, same-UTC-hour baseline and departure flags.
Because the image holds ~5 days, a daily run loses nothing; rows far from the top drift with receiver gaps (±5 min
at the top, anchored to Last-Modified), so read older rows at hourly resolution or coarser.

What it measures: reception at Amberg, not transmitter status. Distant stations fade with day/night skywave, so flags
compare against the same UTC hour. Anthorn (two tracks, ~1,200 km groundwave, continuously on air) is the receiver
control: if it and most watched Chayka tracks are dark together, flags are suppressed. Chayka is a STATUS line, not a
trigger, until the Chayka-vs-GNSS study passes (|rho| >= 0.3, n >= 60, de-trended).

Source: df6nm-dl0ao in registry/sources.csv (private-watch: personal site, terms unverified; 15 min at most).
Outputs (gitignored): data/watch/chayka/{chayka_rows.csv, latest.json, calibration.csv, archive/lorvw_*.jpg}

Usage
  python collectors/chayka.py                                       # live
  python collectors/chayka.py --image FILE --at 2026-10-07T15:00Z   # score a saved image
"""
import argparse, csv, json, os, shutil, ssl, sys, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "watch", "chayka")
URL = os.environ.get("CHAYKA_IMAGE_URL", "https://vlf.u01.de/LF/LFgrabber/lorvw.jpg")
UA = {"User-Agent": "noise-floor watch pollers (research; daily)"}
ROW = timedelta(minutes=5)
# vlf.u01.de sends its leaf certificate without the Let's Encrypt chain (seen after its 14 Oct 2026 renewal; still so
# on 22 Oct). ca_extra.pem holds YR2 and Root YR cross-signed by ISRG Root X1 (from yr2.i.lencr.org / yr.i.lencr.org).
# When Let's Encrypt rotates intermediates this goes stale: re-fetch the issuer named in the leaf's AIA URL.
CA_EXTRA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ca_extra.pem")

BAND = 32
# Track order used by DL0AO in 2026 (from the Loran-C-Chayka-Analyzer-Suite track list): (name, GRI, role, km from Amberg)
TRACKS = [
    ("GPS control", "-", "R", 0),
    ("Anthorn", "6731", "M", 1195), ("Anthorn", "6731", "Y", 1195),
    ("Bryansk", "8000", "M", 1657), ("Petrozavodsk", "8000", "W", 1929), ("Slonim", "8000", "X", 1032),
    ("Simferopol", "8000", "Y", 1742), ("Syzran", "8000", "Z", 2538),
    ("Afif", "8830", "M", 3923), ("Salwa", "8830", "W", 4319), ("Ash Shaykh H.", "8830", "Y", 3067),
    ("Al Muwassam", "8830", "Z", 4605),
    ("Kotelnikovo", "5990", "M", 2305), ("Poltavskaya", "5990", "X", 2029), ("Astrakhan", "5990", "Y", 2694),
    ("Balashov", "5990", "Z", 2223),
    ("Inta", "5960", "M", 3304), ("Tumanny Pen", "5960", "X", 2538), ("Norilsk", "5960", "Z", 4416),
    ("Yuzhno-Uralsk", "5970", "M", 3381), ("Yekaterinburg", "5970", "X", 3289), ("Orsk", "5970", "Z", 3281),
    ("Nagqu", "6250", "M", 6757), ("Pucheng", "6000", "M", 7660),
    ("Hexian", "6780", "M", 8700), ("Raoping", "6780", "X", 9061), ("Chongzuo", "6780", "Y", 8514),
    ("Xuancheng", "8390", "M", 8559), ("Raoping", "8390", "X", 9061), ("Rongcheng", "8390", "Y", 8248),
    ("Rongcheng", "7430", "M", 8248), ("Pucheng", "7430", "X", 8559), ("Helong", "7430", "Y", 8115),
    ("Pohang", "9930", "M", 8709), ("Kwang Ju", "9930", "W", 8660), ("Ussuriisk", "9930", "Z", 8076),
    ("Aleksandrovsk", "7950", "M", 7933), ("Petropavlovsk", "7950", "W", 8194), ("Ussuriisk", "7950", "X", 8076),
    ("George", "5990", "N", 8341), ("Fallon", "5990", "O", 9025), ("Havre", "5990", "P", 7785),
]
TRACK_IDS = [f"{n} {g}{r}" for n, g, r, _ in TRACKS]
WATCH_CHAINS = {"8000": "Western/European Chayka", "5990": "Southern Russian Chayka"}
WATCH_IDX = [i for i, (n, g, r, d) in enumerate(TRACKS) if g in WATCH_CHAINS and r in "MWXYZ"]
CONTROL = ["Anthorn 6731M", "Anthorn 6731Y"]
ON_CONTRAST = 35.0   # 0-255 brightness units above the row's floor; tuned on the 2026 DL0AO archive images
MAX_WANDER = 4.0     # px


# ---------------- image scoring ----------------
def load(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    if a.shape[1] != BAND * len(TRACKS):
        raise ValueError(f"expected width {BAND * len(TRACKS)}, got {a.shape[1]}: track layout may have changed")
    return a


def scores(a, chunk=4000):
    """Per row x track: (contrast, wander).

    Brightness = max RGB channel, smoothed over 3 rows so vertical traces beat speckle.
    contrast = mean of the 3 brightest pixel-columns in the track's band, minus the row's floor (25th percentile
               of that value across tracks).
    wander   = std-dev (px) of the brightest columns' position over a 7-row window. A real Loran pulse arrives at a
               fixed point in its band; the broadband noise strips on the right of the display wander."""
    H, n = a.shape[0], len(TRACKS)
    con = np.empty((H, n), dtype=np.float32)
    cen = np.empty((H, n), dtype=np.float32)
    k = np.ones(3) / 3
    for s in range(0, H, chunk):
        e = min(H, s + chunk)
        lo, hi = max(0, s - 1), min(H, e + 1)
        v = a[lo:hi].max(axis=2)
        sm = np.apply_along_axis(lambda c: np.convolve(c, k, mode="same"), 0, v)[s - lo: s - lo + (e - s)]
        bands = sm.reshape(e - s, n, BAND)
        cen[s:e] = np.argsort(bands, axis=2)[:, :, -3:].mean(axis=2)
        peak = np.sort(bands, axis=2)[:, :, -3:].mean(axis=2)
        peak[:, 0] = np.nan  # the GPS control band carries the label strip; not a station
        con[s:e] = peak - np.nanpercentile(peak, 25, axis=1, keepdims=True)
    win = np.lib.stride_tricks.sliding_window_view(np.pad(cen, ((3, 3), (0, 0)), mode="edge"), 7, axis=0)
    return con, win.std(axis=-1)


def on_off(con, wander, smooth=3, thr=None, max_wander=None):
    """Boolean ON matrix: contrast above threshold AND pulse position steady, then a running median over `smooth`
    rows to drop single-row flicker."""
    thr = ON_CONTRAST if thr is None else thr
    max_wander = MAX_WANDER if max_wander is None else max_wander
    on = ((con > thr) & (wander < max_wander)).astype(np.float32)
    if smooth > 1:
        pad = smooth // 2
        p = np.pad(on, ((pad, pad), (0, 0)), mode="edge")
        on = np.median(np.lib.stride_tricks.sliding_window_view(p, smooth, axis=0), axis=-1)
    return on > 0.5


def day_labels(a):
    """Centre rows of the day-of-month labels (white digits on black in the left strip), top to bottom."""
    px = a[:, 3:18, :]
    w = ((px[:, :, 0] > 170) & (px[:, :, 1] > 170) & (px[:, :, 2] > 170)).sum(axis=1)
    groups = []
    for r in np.where(w >= 3)[0]:
        if groups and r - groups[-1][-1] <= 8:
            groups[-1].append(r)
        else:
            groups.append([r])
    kept = []
    for c in (int(np.mean(g)) for g in groups if 2 <= len(g) <= 14):
        if not kept or c - kept[-1] >= 200:   # drop detections closer than 200 rows (speckle, split digits)
            kept.append(c)
    return kept


# ---------------- logging and summary ----------------
def _majority_on(rows, cols):
    return sum(int(r.get(c) or 0) for r in rows for c in cols) * 2 > len(rows) * len(cols)


def control_on(rows, recent=3):
    """Anthorn (the in-image control) ON in most of the newest rows."""
    return _majority_on(rows[-recent:], CONTROL) if rows else True


def receiver_ok(rows, recent=3):
    """False when the Anthorn control AND most watched Chayka tracks are dark in the newest rows: a fault at Amberg
    (receiver, antenna, display) silences everything, so a 'dropout' then says nothing about a transmitter.
    Anthorn alone dark while the Chayka tracks are on is Anthorn itself, not the receiver. (emso-watch used Anthorn
    alone; on the first live run, 22 Oct 2026, Anthorn's strong pulse wandered just past MAX_WANDER in the newest rows
    and that suppressed every flag.)"""
    last = rows[-recent:]
    if not last or control_on(rows, recent):
        return True
    return _majority_on(last, [TRACK_IDS[i] for i in WATCH_IDX])


def summarize(rows, now, recent=3):
    """Per watch station: ON now, 24-h ON%, same-UTC-hour baseline ON% (prior 30 days, >= 3 h of samples), flag."""
    if not rows:
        return {}
    ts = [datetime.fromisoformat(r["utc"].replace("Z", "+00:00")) for r in rows]
    rx_ok = receiver_ok(rows, recent)
    out = {}
    for i in WATCH_IDX:
        tid = TRACK_IDS[i]
        vals = [(t, int(r[tid])) for t, r in zip(ts, rows) if r.get(tid) not in (None, "")]
        if not vals:
            continue
        last = [v for _, v in vals[-recent:]]
        now_on = sum(last) * 2 > len(last)
        day = [v for t, v in vals if t > now - timedelta(hours=24)]
        base = [v for t, v in vals if now - timedelta(days=30) < t < now - timedelta(hours=12)
                and min((t.hour - now.hour) % 24, (now.hour - t.hour) % 24) <= 1]
        b = (100 * sum(base) / len(base)) if len(base) >= 36 else None
        flag = None
        if b is not None and rx_ok:
            if not now_on and b >= 80:
                flag = "DROPOUT: off now, normally on at this hour"
            elif now_on and b <= 20:
                flag = "UNUSUAL ON: on now, normally off at this hour"
        out[tid] = {"chain": TRACKS[i][1], "chain_name": WATCH_CHAINS[TRACKS[i][1]], "on_now": now_on,
                    "on_pct_24h": round(100 * sum(day) / len(day)) if day else None,
                    "same_hour_baseline_pct": None if b is None else round(b), "baseline_samples": len(base), "flag": flag}
    return out


def _open(req):
    try:
        return urllib.request.urlopen(req, timeout=60)
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLCertVerificationError) or not os.path.exists(CA_EXTRA):
            raise
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(CA_EXTRA)
        return urllib.request.urlopen(req, timeout=60, context=ctx)


def fetch(url, dest):
    """Download the image to dest; return (top-row time, anchored-by-Last-Modified)."""
    with _open(urllib.request.Request(url, headers=UA)) as r:
        data = r.read()
        lm = r.headers.get("Last-Modified")
    with open(dest, "wb") as f:
        f.write(data)
    t = parsedate_to_datetime(lm).astimezone(timezone.utc) if lm else datetime.now(timezone.utc)
    return t, bool(lm)


def floor5(t):
    return t.replace(second=0, microsecond=0) - timedelta(minutes=t.minute % 5)


def read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run(data=DATA, url=URL, image=None, at=None, now=None, fetcher=fetch):
    """One logging pass. Returns the latest.json dict."""
    now = now or datetime.now(timezone.utc)
    arch = os.path.join(data, "archive")
    os.makedirs(arch, exist_ok=True)
    if image:
        img = image
        t0 = datetime.fromisoformat(at.replace("Z", "+00:00")) if at else now
        anchored = "--at argument" if at else "local clock"
    else:
        img = os.path.join(data, "lorvw_latest.jpg")
        t0, has_lm = fetcher(url, img)
        anchored = "Last-Modified header" if has_lm else "local clock (no Last-Modified)"
    t0 = floor5(t0)
    arr = load(img)
    rows_path = os.path.join(data, "chayka_rows.csv")
    existing = read_rows(rows_path)
    last_t = datetime.fromisoformat(existing[-1]["utc"].replace("Z", "+00:00")) if existing else None
    # Log every row newer than the last logged one (the whole image on the first run; it seeds the same-hour
    # baseline at once). A daily run therefore leaves no gaps while the image still covers the interval.
    n = arr.shape[0] if last_t is None else max(0, min(arr.shape[0], int((t0 - last_t) / ROW) + 1))
    labels = day_labels(arr)
    new = []
    if n:
        con, wander = scores(arr[: min(arr.shape[0], max(n + 10, 400))])
        on = on_off(con, wander)
        for r in range(n - 1, -1, -1):   # oldest first
            t = t0 - r * ROW
            if last_t and t <= last_t:
                continue
            rec = {"utc": t.strftime("%Y-%m-%dT%H:%MZ")}
            rec.update({tid: int(on[r, i]) for i, tid in enumerate(TRACK_IDS) if i > 0})
            new.append(rec)
    if not image and not any(f.startswith(f"lorvw_{t0:%Y%m%d}") for f in os.listdir(arch)):
        shutil.copyfile(img, os.path.join(arch, f"lorvw_{t0:%Y%m%dT%H%MZ}.jpg"))   # one raw image per UTC day
    if new:
        write_hdr = not os.path.exists(rows_path)
        with open(rows_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["utc"] + TRACK_IDS[1:])
            if write_hdr:
                w.writeheader()
            w.writerows(new)
    # time-anchor check: where do the day labels sit relative to the top row?
    with open(os.path.join(data, "calibration.csv"), "a", encoding="utf-8") as f:
        implied = [(t0 - r * ROW).strftime("%H:%MZ") for r in labels[:2]]
        f.write(f"{t0:%Y-%m-%dT%H:%MZ},{anchored},{';'.join(map(str, labels[:3]))},{';'.join(implied)}\n")
    allrows = existing + new
    state = {"generated": now.strftime("%Y-%m-%dT%H:%MZ"), "image_top_row_utc": t0.strftime("%Y-%m-%dT%H:%MZ"),
             "time_source": anchored, "rows_logged_total": len(allrows), "new_rows": len(new),
             "label_rows_from_top": labels[:3],
             "note": "Reception at Amberg DE, not transmitter status. Flags need >=3 h of same-hour history.",
             "control_on": control_on(allrows), "receiver_ok": receiver_ok(allrows), "stations": summarize(allrows, t0)}
    with open(os.path.join(data, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--url", default=URL)
    ap.add_argument("--image", help="score a saved image instead of downloading")
    ap.add_argument("--at", help="UTC time of the image's top row (with --image), e.g. 2026-10-07T15:00Z")
    a = ap.parse_args()
    st = run(a.data, a.url, a.image, a.at)
    flags = {k: v["flag"] for k, v in st["stations"].items() if v["flag"]}
    print(f"{st['image_top_row_utc']}: +{st['new_rows']} rows, {st['rows_logged_total']} total; "
          + (f"FLAGS: {flags}" if flags else "no flags"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
