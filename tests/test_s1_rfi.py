"""Offline tests for tools/s1_rfi.py: the RFI annotation parser (synthetic XML in the real schema, see Sentinel-1
Product Specification S1-RS-MDA-52-7441 Tables 6-112 to 6-119), geolocation from an annotation tail, burst
flagging, and site clustering on synthetic passes. No network.

Run:  python tests/test_s1_rfi.py
"""
import os
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import s1_rfi as S  # noqa: E402

RFI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rfi>
  <adsHeader>
    <missionId>S1C</missionId>
    <productType>GRD</productType>
    <polarisation>VV</polarisation>
    <mode>IW</mode>
    <swath>IW</swath>
    <startTime>2026-01-02T03:04:05.000000</startTime>
    <stopTime>2026-01-02T03:04:30.000000</stopTime>
    <absoluteOrbitNumber>1234</absoluteOrbitNumber>
    <missionDataTakeId>4321</missionDataTakeId>
    <imageNumber>001</imageNumber>
  </adsHeader>
  <rfiMitigationApplied>TimeFrequency</rfiMitigationApplied>
  <rfiDetectionFromNoiseReportList count="2">
    <rfiDetectionFromNoiseReport>
      <swath>IW1</swath>
      <noiseSensingTime>2026-01-02T03:04:04.500000</noiseSensingTime>
      <rfiDetected>true</rfiDetected>
      <maxKLDivergence>0.000000e+00</maxKLDivergence>
      <maxFisherZ>4.396501e+01</maxFisherZ>
      <maxRfiPsd>3.802615e+01</maxRfiPsd>
    </rfiDetectionFromNoiseReport>
    <rfiDetectionFromNoiseReport>
      <swath>IW2</swath>
      <noiseSensingTime>2026-01-02T03:04:20.000000</noiseSensingTime>
      <rfiDetected>false</rfiDetected>
      <maxKLDivergence>2.5e+00</maxKLDivergence>
      <maxFisherZ>3.1e+00</maxFisherZ>
      <maxRfiPsd>0.000000e+00</maxRfiPsd>
    </rfiDetectionFromNoiseReport>
  </rfiDetectionFromNoiseReportList>
  <rfiBurstReportList count="3">
    <rfiBurstReport>
      <swath>IW1</swath>
      <azimuthTime>2026-01-02T03:04:05.000000</azimuthTime>
      <inBandOutBandPowerRatio>2.104192e+00</inBandOutBandPowerRatio>
      <timeDomainRfiReport>
        <percentageAffectedLines>3.562811e+01</percentageAffectedLines>
        <avgPercentageAffectedSamples>4.353452e-02</avgPercentageAffectedSamples>
        <maxPercentageAffectedSamples>7.036417e+00</maxPercentageAffectedSamples>
      </timeDomainRfiReport>
      <frequencyDomainRfiBurstReport>
        <numSubBlocks>3</numSubBlocks>
        <subBlockSize>537</subBlockSize>
        <isolatedRfiReport>
          <percentageAffectedLines>4.536452e+00</percentageAffectedLines>
          <maxPercentageAffectedBW>7.117372e+00</maxPercentageAffectedBW>
        </isolatedRfiReport>
        <percentageBlocksPersistentRfi>0.000000e+00</percentageBlocksPersistentRfi>
        <maxPercentageBWAffectedPersistentRfi>0.000000e+00</maxPercentageBWAffectedPersistentRfi>
      </frequencyDomainRfiBurstReport>
    </rfiBurstReport>
    <rfiBurstReport>
      <swath>IW1</swath>
      <azimuthTime>2026-01-02T03:04:07.758000</azimuthTime>
      <inBandOutBandPowerRatio>3.7e+00</inBandOutBandPowerRatio>
      <timeDomainRfiReport>
        <percentageAffectedLines>2.0e+00</percentageAffectedLines>
        <avgPercentageAffectedSamples>1.0e-02</avgPercentageAffectedSamples>
        <maxPercentageAffectedSamples>1.0e+00</maxPercentageAffectedSamples>
      </timeDomainRfiReport>
      <frequencyDomainRfiBurstReport>
        <numSubBlocks>3</numSubBlocks>
        <subBlockSize>537</subBlockSize>
        <isolatedRfiReport>
          <percentageAffectedLines>1.0e+00</percentageAffectedLines>
          <maxPercentageAffectedBW>2.0e+00</maxPercentageAffectedBW>
        </isolatedRfiReport>
        <percentageBlocksPersistentRfi>3.3e+01</percentageBlocksPersistentRfi>
        <maxPercentageBWAffectedPersistentRfi>1.2e+01</maxPercentageBWAffectedPersistentRfi>
      </frequencyDomainRfiBurstReport>
    </rfiBurstReport>
    <rfiBurstReport>
      <swath>IW2</swath>
      <azimuthTime>2026-01-02T03:04:06.000000</azimuthTime>
      <inBandOutBandPowerRatio>3.8e+00</inBandOutBandPowerRatio>
    </rfiBurstReport>
  </rfiBurstReportList>
</rfi>
"""

MANIFEST = """<xfdu:XFDU><metadataSection>
<safe:facility country="France" name="Copernicus S1 Core Ground Segment" organisation="ESA" site="x">
  <safe:software name="Sentinel-1 IPF" version="004.03"/>
</safe:facility>
<safe:platform><safe:nssdcIdentifier>x</safe:nssdcIdentifier><safe:familyName>SENTINEL-1</safe:familyName>
<safe:number>C</safe:number></safe:platform>
<safe:orbitNumber type="start">1234</safe:orbitNumber><safe:relativeOrbitNumber type="start">35</safe:relativeOrbitNumber>
<s1:pass>DESCENDING</s1:pass>
<s1sarl1:mode>IW</s1sarl1:mode><s1sarl1:productType>GRD</s1sarl1:productType>
<safe:footPrint><gml:coordinates>10.0,20.0 10.0,22.0 11.0,22.0 11.0,20.0</gml:coordinates></safe:footPrint>
</metadataSection></xfdu:XFDU>"""


def annotation_tail():
    """The end of a GRD main annotation as a range read returns it: starts mid-file, then swathTiming,
    geolocationGrid (3 lines x 3 pixels), coordinateConversion and swathMerging."""
    pts = []
    for li, (line, t) in enumerate(((0, "2026-01-02T03:04:05.000000"), (5000, "2026-01-02T03:04:15.000000"),
                                    (10000, "2026-01-02T03:04:25.000000"))):
        for pj, pix in enumerate((0, 12000, 24000)):
            lat = 10.0 + 0.5 * li          # +0.05 deg per second along track
            lon = 20.0 + 1.0 * pj          # +1 deg per 12000 pixels across track
            pts.append("<geolocationGridPoint><azimuthTime>%s</azimuthTime><slantRangeTime>5.3e-03</slantRangeTime>"
                       "<line>%d</line><pixel>%d</pixel><latitude>%.6f</latitude><longitude>%.6f</longitude>"
                       "<height>0</height><incidenceAngle>30</incidenceAngle><elevationAngle>27</elevationAngle>"
                       "</geolocationGridPoint>" % (t, line, pix, lat, lon))
    merge = "".join("<swathMerge><swath>IW%d</swath><swathBoundsList count=\"1\"><swathBounds>"
                    "<azimuthTime>2026-01-02T03:04:05.000000</azimuthTime><firstAzimuthLine>0</firstAzimuthLine>"
                    "<firstRangeSample>%d</firstRangeSample><lastAzimuthLine>10000</lastAzimuthLine>"
                    "<lastRangeSample>%d</lastRangeSample></swathBounds></swathBoundsList></swathMerge>"
                    % (k + 1, 8000 * k, 8000 * k + 7999) for k in range(3))
    return ("ttenuation>1.0</attenuation></x>\n  <swathTiming><linesPerBurst>0</linesPerBurst></swathTiming>\n"
            "  <geolocationGrid><geolocationGridPointList count=\"9\">" + "".join(pts) +
            "</geolocationGridPointList></geolocationGrid>\n  <coordinateConversion/>\n"
            "  <swathMerging><swathMergeList count=\"3\">" + merge + "</swathMergeList></swathMerging>\n</product>\n"
            "<numberOfSamples>24001</numberOfSamples>")


def near(a, b, tol):
    return abs(a - b) <= tol


def test_parse_rfi():
    r = S.parse_rfi(RFI_XML)
    assert r["mitigation"] == "TimeFrequency"
    assert r["header"]["missionId"] == "S1C" and r["header"]["polarisation"] == "VV"
    assert len(r["noise"]) == 2 and r["noise"][0]["detected"] is True and r["noise"][1]["detected"] is False
    assert near(r["noise"][0]["max_rfi_psd"], 38.02615, 1e-4)
    assert len(r["bursts"]) == 3
    b0, b1, b2 = r["bursts"]
    assert b0["swath"] == "IW1" and near(b0["td_lines_pct"], 35.62811, 1e-4)
    assert near(b0["iso_max_bw_pct"], 7.117372, 1e-5) and b0["pers_blocks_pct"] == 0.0
    assert b0["n_sub_blocks"] == 3 and b0["sub_block_size"] == 537
    assert near(b1["pers_blocks_pct"], 33.0, 1e-9) and near(b1["pers_max_bw_pct"], 12.0, 1e-9)
    assert b2["td_lines_pct"] is None and near(b2["in_out_ratio"], 3.8, 1e-9)   # burst without detection reports
    assert near(b1["t0"] - b0["t0"], 2.758, 1e-6)
    assert S.burst_duration(r["bursts"]) == b1["t0"] - b0["t0"]


def test_parse_manifest():
    m = S.parse_manifest(MANIFEST)
    assert m["ipf"] == "004.03" and m["mission"] == "C"
    assert m["abs_orbit"] == 1234 and m["rel_orbit"] == 35 and m["direction"] == "DESCENDING"
    assert m["product_type"] == "GRD" and m["mode"] == "IW"
    assert m["footprint"][0] == (10.0, 20.0) and len(m["footprint"]) == 4


def test_geo_and_bursts():
    tail = annotation_tail()
    assert S.geo_complete(tail) and not S.geo_complete(tail[tail.index("<geolocationGridPoint>"):])
    g = S.parse_geo(tail)
    assert g.swath_bounds["IW2"] == (8000.0, 15999.0)
    t0 = S.ts("2026-01-02T03:04:05.000000")
    la, lo = g.latlon(t0 + 10.0, 12000)
    assert near(la, 10.5, 1e-9) and near(lo, 21.0, 1e-9)
    la, lo = g.latlon(t0 - 2.0, 0)                 # before the first grid line: linear extrapolation
    assert near(la, 9.9, 1e-9) and near(lo, 20.0, 1e-9)
    rfi = S.parse_rfi(RFI_XML)
    meta = {"product": "S1C_IW_GRDH_1SDV_20260102T030405_x", "platform": "S1C", "pass": "S1C_1234",
            "rel_orbit": 35, "direction": "descending", "ipf": "004.03"}
    rows = S.burst_records(rfi, {"*": g}, meta)
    assert len(rows) == 3
    r0 = rows[0]
    assert r0["pol"] == "VV" and r0["noise_detected"] is True and near(r0["noise_max_psd"], 38.02615, 1e-4)
    # IW1 spans pixels 0..7999 -> lon 20.0..20.667; the burst lasts 2.758 s -> lat 10.0..10.1379
    lats = [p[0] for p in r0["poly"]]
    lons = [p[1] for p in r0["poly"]]
    assert near(min(lats), 10.0, 1e-4) and near(max(lats), 10.1379, 1e-3)
    assert near(min(lons), 20.0, 1e-4) and near(max(lons), 20.6666, 1e-3)
    assert near(r0["lat"], 10.069, 1e-3) and near(r0["lon"], 20.3333, 1e-3)
    # flags: td >= 10 -> yes; persistent blocks >= 1 -> yes; no reports -> no; pol filter
    assert S.flag(rows[0]) and S.flag(rows[1]) and not S.flag(rows[2])
    assert not S.flag(rows[0], {"pols": ["VH"]})
    assert not S.flag(rows[1], {"pers_blocks_pct": None})
    # adjacent slices repeat seam bursts: dedupe keeps one, the larger RFI
    dup = dict(rows[0], td_lines_pct=50.0, product="other")
    out = S.dedupe(rows + [dup])
    assert len(out) == 3 and max(r["td_lines_pct"] or 0 for r in out) == 50.0


# ------------------------------------------------------------------ clustering on synthetic passes
def box(lat0, lat1, lon0, lon1):
    return [[lat0, lon0], [lat0, lon1], [lat1, lon1], [lat1, lon0]]


def synth_pass(pid, track, direction, t, lat_off, lon_off, emitter, td_hit=40.0, td_bg=1.0, everywhere=False):
    """One pass: 3 swaths (0.8 deg wide) x 12 bursts (0.18 deg long), offset per geometry. The emitter lights the
    burst holding it and its along-track neighbours, in its own swath only (as seen in real passes)."""
    rows = []
    elat, elon = emitter
    for k in range(12):
        la0 = 46.0 + lat_off + 0.18 * k
        for sw in range(3):
            lo0 = 38.0 + lon_off + 0.8 * sw
            hit_sw = lo0 <= elon < lo0 + 0.8
            dk = (elat - la0) / 0.18
            if everywhere:
                td = td_hit
            elif hit_sw and 0 <= dk < 1:
                td = td_hit
            elif hit_sw and -1 <= dk < 2:
                td = td_hit * 0.5
            else:
                td = td_bg
            rows.append({"pass": pid, "pol": "VV", "swath": "IW%d" % (sw + 1), "t0": t + 2.758 * k,
                         "rel_orbit": track, "direction": direction, "platform": "S1C", "td_lines_pct": td,
                         "pers_blocks_pct": 0.0, "iso_max_bw_pct": 1.0, "pers_max_bw_pct": 0.0, "noise_max_psd": 0.0,
                         "poly": box(la0, la0 + 0.18, lo0, lo0 + 0.8)})
    return rows


GEOMS = [(43, "ascending", 0.00, 0.00), (145, "ascending", 0.07, 0.35), (21, "descending", 0.11, -0.25),
         (94, "descending", 0.03, 0.55)]
BBOX = [38.5, 46.5, 40.5, 47.8]


def passes(emitter, n_rep=3, **kw):
    rows = []
    for rep in range(n_rep):
        for i, (track, d, la, lo) in enumerate(GEOMS):
            pid = "S1C_%d" % (1000 + 10 * rep + i)
            rows += synth_pass(pid, track, d, 1.7e9 + 86400 * (6 * rep + i), la, lo, emitter, **kw)
    return rows


def test_sites_find_emitter():
    em = (47.13, 39.52)
    rows = passes(em)
    g = S.accumulate(rows, BBOX, 0.05)
    sites = S.find_sites(g)
    assert len(sites) >= 1, sites
    d, s = min((S.km(x["lat"], x["lon"], *em), x) for x in sites)
    assert d < 15.0, (d, s)
    assert s["n_tracks"] == 4 and s["n_passes"] == 12 and s["frac"] == 1.0
    assert s["pols"] == ["VV"] and s["first_seen"] < s["last_seen"]
    # the emitter cell ranks at the top of the area
    assert S.percentile_rank(g, "score", *em) > 0.95
    assert S.cell_value(g, "frac", *em) == 1.0 and S.cell_value(g, "frac", 0.0, 0.0) is None
    # Known limitation, kept visible: where the stripes of most (not all) geometries overlap, a ghost site can
    # appear (one subswath wide, ~60 km here). Only the true crossing is agreed by every covering geometry.
    ghosts = [x for x in sites if x is not s]
    assert all(x["n_tracks"] < x["n_cover_tracks"] for x in ghosts), ghosts
    assert all(S.km(x["lat"], x["lon"], *em) < 60 for x in ghosts), ghosts
    kml = S.kml_doc("test", {"sites": sites, "attribution": "Contains modified Copernicus Sentinel data 2026"})
    assert ET.fromstring(kml.encode("utf-8")).tag.endswith("kml")


def test_sites_quiet_and_saturated():
    quiet = passes((47.13, 39.52), td_hit=0.0, td_bg=0.0)
    g = S.accumulate(quiet, BBOX, 0.05)
    assert S.find_sites(g) == [] and g["hit"].max() == 0
    # RFI everywhere at the same level: no discrete site (fails the prominence rules)
    sat = passes((47.13, 39.52), td_hit=60.0, everywhere=True)
    g = S.accumulate(sat, BBOX, 0.05)
    assert g["frac"][g["cover"] >= 4].min() == 1.0
    assert S.find_sites(g) == [], S.find_sites(g)
    # two geometries are needed: a single geometry never makes a site
    one = [r for r in passes((47.13, 39.52)) if r["rel_orbit"] == 43]
    assert S.find_sites(S.accumulate(one, BBOX, 0.05)) == []


def test_scrub_and_platform():
    assert "sig" not in S.scrub("HTTP 403 https://x.blob.core.windows.net/a/b?sv=1&sig=abc")
    assert [S.norm_platform(x) for x in ("sentinel-1c", "SENTINEL-1A", "Sentinel-1D")] == ["S1C", "S1A", "S1D"]


def main():
    test_parse_rfi()
    test_parse_manifest()
    test_geo_and_bursts()
    test_sites_find_emitter()
    test_sites_quiet_and_saturated()
    test_scrub_and_platform()
    print("test_s1_rfi: ok")


if __name__ == "__main__":
    main()
