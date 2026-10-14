"""Offline test for pipeline/pnt_analysis.py on synthetic hourly/minute files (no network)."""
import os, shutil, sys, tempfile

import h3
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import pnt_analysis as A  # noqa: E402

EUROPE = h3.latlng_to_cell(50.0, 10.0, 4)      # inside the EGNOS box
US = h3.latlng_to_cell(40.0, -100.0, 4)        # inside WAAS (CONUS)


def write_day(folder, day, cap_bad_eu=20, gross_us=0, burst=False):
    rows = []
    for hour in range(24):
        rows.append({"h3": EUROPE, "hour": hour, "aircraft": 300, "bad_nacp": 0, "bad_nic": 0, "bad_acc10": 120,
                     "capable": 250, "cap_bad_acc10": cap_bad_eu})
        rows.append({"h3": US, "hour": hour, "aircraft": 300, "bad_nacp": gross_us if hour == 20 else 0, "bad_nic": 0,
                     "bad_acc10": 50, "capable": 250, "cap_bad_acc10": 8})
    pq.write_table(pa.Table.from_pylist(rows), os.path.join(folder, f"{day}.hourly.parquet"))
    mins = [{"h3": US, "minute": m, "bad_nacp": 1} for m in range(0, 1440, 7)]          # background noise
    if burst:
        mins += [{"h3": US, "minute": m, "bad_nacp": 30} for m in range(18 * 60, 18 * 60 + 5)]
    pq.write_table(pa.Table.from_pylist(mins, schema=pa.schema([("h3", pa.string()), ("minute", pa.int16()), ("bad_nacp", pa.int32())])),
                   os.path.join(folder, f"{day}.minute.parquet"))


def test_analysis():
    tmp = tempfile.mkdtemp()
    old = A.DAILY, A.OUT
    try:
        A.DAILY = tmp; A.OUT = os.path.join(tmp, "analysis"); os.makedirs(A.OUT)
        for d in range(1, 8):
            write_day(tmp, f"2025-10-0{d}")
        write_day(tmp, "2025-10-08", cap_bad_eu=240, gross_us=60, burst=True)   # EGNOS-like outage + US event
        sb = A.sbas("2025-10-08", use_kp=False)
        eg = sb["areas"]["EGNOS (Europe)"]
        assert eg["flagged_hours"] == 24 and eg["hours"][0]["state"] == "outage", eg["hours"][0]
        assert sb["areas"]["WAAS (CONUS)"]["flagged_hours"] == 0
        cache = {}
        an = A.anomalies("2025-10-08", lambda d: cache.setdefault(d, A.sbas(d, use_kp=False)))
        assert len(an["baseline_days"]) == 7, an["baseline_days"]
        kinds = {(f["measure"], f["hour"]) for f in an["anomalies"]}
        assert ("gross", 20) in kinds, an["anomalies"]
        assert not any(f["measure"] == "capable_10m" for f in an["anomalies"]), "SBAS-flagged hours are excluded, not anomalies"
        bu = A.bursts("2025-10-08")["bursts"]
        assert len(bu) == 1 and bu[0]["start"] == "18:00Z" and bu[0]["end"] == "18:04Z" and bu[0]["peak_aircraft"] == 30, bu
        assert A.bursts("2025-10-07")["bursts"] == []
    finally:
        A.DAILY, A.OUT = old
        shutil.rmtree(tmp)


if __name__ == "__main__":
    test_analysis()
    print("PASS test_analysis")
