"""Offline tests for tools/sanctions.py and tools/vessels_build.py (the Sea map) on synthetic data: no network, no
collected AIS. Plain script, as CI runs it: needs numpy, pyarrow, pyproj and h3 (requirements.txt plus
nisar/requirements.txt, both installed in CI)."""
import io, math, os, shutil, sys, tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import sanctions as S  # noqa: E402
import vessels_build as V  # noqa: E402

T0 = 1_792_800_000
IMO_A, IMO_B = 9231509, 9603972            # both have valid check digits
OFAC_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<sanctionsData xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ENHANCED_XML">
 <publicationInfo><dataAsOf>2026-10-21T00:00:00-04:00</dataAsOf></publicationInfo>
 <entities>
  <entity id="4243">
   <generalInfo><identityId>1</identityId><entityType refId="602">Vessel</entityType></generalInfo>
   <sanctionsLists><sanctionsList refId="1550" id="1" datePublished="2024-12-16">SDN List</sanctionsList></sanctionsLists>
   <sanctionsPrograms><sanctionsProgram refId="1" id="2">RUSSIA-EO14024</sanctionsProgram></sanctionsPrograms>
   <names>
    <name id="1"><isPrimary>true</isPrimary><translations><translation id="1"><isPrimary>true</isPrimary>
      <formattedFullName>TEST TANKER</formattedFullName></translation></translations></name>
    <name id="2"><isPrimary>false</isPrimary><translations><translation id="2"><isPrimary>true</isPrimary>
      <formattedFullName>OLD NAME</formattedFullName></translation></translations></name>
   </names>
   <features>
    <feature id="1"><type featureTypeId="3">Vessel Flag</type><value>Gabon</value></feature>
    <feature id="2"><type featureTypeId="2">VESSEL TYPE</type><value>Crude Oil Tanker</value></feature>
    <feature id="3"><type featureTypeId="4">Vessel Call Sign</type><value>TRAA1</value></feature>
   </features>
   <identityDocuments>
    <identityDocument id="1"><type refId="1626">Vessel Registration Identification</type><documentNumber>IMO 9231509</documentNumber></identityDocument>
    <identityDocument id="2"><type refId="1627">MMSI</type><documentNumber>626123456</documentNumber></identityDocument>
   </identityDocuments>
  </entity>
  <entity id="77">
   <generalInfo><identityId>2</identityId><entityType refId="600">Individual</entityType></generalInfo>
   <names><name id="3"><isPrimary>true</isPrimary><translations><translation id="3"><formattedFullName>A PERSON</formattedFullName></translation></translations></name></names>
  </entity>
  <entity id="88">
   <generalInfo><identityId>3</identityId><entityType refId="602">Vessel</entityType></generalInfo>
   <sanctionsLists><sanctionsList refId="1550" id="4" datePublished="2019-03-25">SDN List</sanctionsList></sanctionsLists>
   <sanctionsPrograms><sanctionsProgram refId="2" id="5">DPRK3</sanctionsProgram><sanctionsProgram refId="3" id="6">DPRK4</sanctionsProgram></sanctionsPrograms>
   <names><name id="4"><isPrimary>true</isPrimary><translations><translation id="4"><formattedFullName>NO IMO SHIP</formattedFullName></translation></translations></name></names>
  </entity>
 </entities>
</sanctionsData>"""
UK_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<Designations xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <DateGenerated>16/10/2026</DateGenerated>
  <Designation>
    <DateDesignated>09/05/2025</DateDesignated><UniqueID>RUS9999</UniqueID>
    <Names><Name><Name6>Test Tanker</Name6><NameType>Primary name</NameType></Name>
           <Name><Name6>Alias One</Name6><NameType>Alias</NameType></Name></Names>
    <RegimeName>The Russia (Sanctions) (EU Exit) Regulations 2019</RegimeName>
    <IndividualEntityShip>Ship</IndividualEntityShip>
    <ShipDetails><Ship><IMONumbers><IMONumber>IMO9231509</IMONumber><IMONumber>9231509</IMONumber></IMONumbers>
      <CurrentBelievedFlagOfShips><CurrentBelievedFlagOfShip>Russia</CurrentBelievedFlagOfShip></CurrentBelievedFlagOfShips>
      <TypeOfShipDetails><TypeOfShip>Crude Oil Tanker</TypeOfShip></TypeOfShipDetails></Ship></ShipDetails>
  </Designation>
  <Designation>
    <DateDesignated>01/02/2023</DateDesignated><UniqueID>RUS0001</UniqueID>
    <Names><Name><Name6>A Person</Name6><NameType>Primary Name</NameType></Name></Names>
    <RegimeName>The Russia (Sanctions) (EU Exit) Regulations 2019</RegimeName>
    <IndividualEntityShip>Individual</IndividualEntityShip>
  </Designation>
  <Designation>
    <DateDesignated>03/10/2017</DateDesignated><UniqueID>DPR0075</UniqueID>
    <Names><Name><Name6>Petrel 8</Name6><NameType>Primary name</NameType></Name></Names>
    <RegimeName>The Democratic People's Republic of Korea (Sanctions) (EU Exit) Regulations 2019</RegimeName>
    <IndividualEntityShip>Ship</IndividualEntityShip>
    <ShipDetails><Ship><IMONumbers><IMONumber>9603972</IMONumber></IMONumbers></Ship></ShipDetails>
  </Designation>
</Designations>"""


def test_sanctions(tmp):
    assert S.imo_check_ok(IMO_A) and S.imo_check_ok(IMO_B) and not S.imo_check_ok(9231508) and not S.imo_check_ok(123)
    assert S.imo_of("IMO 9187629") == 9187629 and S.imo_of("IMO9187629") == 9187629 and S.imo_of("12345678") is None
    of = S.parse_ofac_enhanced(io.BytesIO(OFAC_XML))
    assert len(of) == 2, of                                   # the individual is skipped
    a = of[0]
    assert (a["imo"], a["mmsi"], a["name"], a["aliases"], a["flag"], a["callsign"]) == (IMO_A, [626123456], "TEST TANKER", ["OLD NAME"], "Gabon", "TRAA1"), a
    assert a["programme"] == "RUSSIA-EO14024" and a["date"] == "2024-12-16" and a["list"] == "OFAC SDN", a
    assert a["url"] == "https://sanctionssearch.ofac.treas.gov/Details.aspx?id=4243", a["url"]
    assert of[1]["imo"] is None and of[1]["programme"] == "DPRK3; DPRK4", of[1]
    uk = S.parse_uk_xml(io.BytesIO(UK_XML))
    assert len(uk) == 2, uk                                   # ships only
    u = uk[0]
    assert (u["imo"], u["imos"], u["name"], u["flag"], u["date"]) == (IMO_A, [IMO_A], "Test Tanker", "Russia", "2025-05-09"), u
    assert u["programme"] == "Russia (Sanctions) (EU Exit) Regulations 2019, ref RUS9999", u["programme"]
    assert uk[1]["imo"] == IMO_B and uk[1]["date"] == "2017-10-03"
    by_imo, no_imo, by_mmsi = S.merge(of + uk)
    assert sorted(by_imo) == [str(IMO_A), str(IMO_B)], by_imo.keys()
    va = by_imo[str(IMO_A)]
    assert [l["list"] for l in va["listings"]] == ["OFAC SDN", "UK Sanctions List"], va["listings"]
    assert va["names"] == ["TEST TANKER", "OLD NAME", "Test Tanker", "Alias One"] and va["mmsi"] == [626123456], va
    assert by_mmsi == {"626123456": [IMO_A]} and len(no_imo) == 1 and no_imo[0]["name"] == "NO IMO SHIP"
    for name, body, key, want in (("o.xml", OFAC_XML, "ofac", "2026-10-21"), ("u.xml", UK_XML, "uk", "2026-10-16")):
        p = os.path.join(tmp, name)
        open(p, "wb").write(body)
        assert S.published(key, p) == want


def test_flags_and_categories():
    assert V.flag_of(273123456) == "RU" and V.flag_of(412000001) == "CN" and V.flag_of(413000001) == "CN"
    assert V.flag_of(414000001) == "CN" and V.flag_of(422000001) == "IR" and V.flag_of(445000001) == "KP"
    assert V.flag_of(230123000) == "FI" and V.flag_of(636012345) == "LR" and V.flag_of(667001235) == "SL"
    assert V.flag_of(992301234) is None and V.flag_of(2300123) is None and V.flag_of(111230001) is None   # AtoN, coast, SAR aircraft
    c = V.categories_for
    assert c(273123456, 80, True, None) == ["state_flag_of_interest"]
    assert c(273123456, 52, False, None) == ["state_flag_of_interest"]                 # tug without IMO
    assert c(413000001, 70, True, None) == ["state_flag_of_interest"]
    assert c(273123456, 37, True, None) == [] and c(273123456, 36, False, None) == [] and c(273123456, 30, True, None) == []
    assert c(273123456, 37, True, "imo") == []                                          # a listed yacht is still a private craft
    assert c(273123456, None, False, None) == [] and c(273123456, None, True, None) == ["state_flag_of_interest"]
    assert c(230123000, 35, False, None) == ["military"] and c(265123000, 55, False, None) == ["law_enforcement"]
    assert c(230123000, 70, True, None) == []                                           # Finnish cargo: not of interest
    assert c(636012345, 80, True, "imo") == ["sanctioned"] and c(636012345, 80, False, "mmsi") == ["sanctioned"]
    assert c(636012345, 80, False, "name") == []                                       # a name alone never adds a ship
    assert c(273123456, 35, True, "imo") == ["sanctioned", "military", "state_flag_of_interest"]
    assert c(992731234, 35, False, None) == []                                          # not a ship MMSI
    assert V.type_label(80) == "Tanker" and V.type_label(81) == "Tanker (hazardous category A)" and V.type_label(None) == "not given"
    assert V.type_label(35) == "Military operations" and V.type_label(55) == "Law enforcement"
    assert V.pos_fix_label(1) == "GPS" and V.pos_fix_label(3) == "combined GPS/GLONASS" and V.pos_fix_label(8) == "Galileo"
    assert V.pos_fix_label(0) is None and V.pos_fix_label(None) is None and V.pos_fix_label(12) is None
    eta = (10 << 16) | (25 << 11) | (14 << 6) | 30
    assert V.decode_eta(eta) == "10-25 14:30 UTC" and V.decode_eta(0) is None and V.decode_eta((24 << 6) | 60) is None


def track(mmsi, t, lat, lon, sog, heading=90):
    n = len(t)
    return {"mmsi": np.full(n, mmsi, np.int64), "time": np.asarray(t, np.int64), "lat": np.asarray(lat, float),
            "lon": np.asarray(lon, float), "sog": np.broadcast_to(np.asarray(sog, float), (n,)).copy(),
            "cog": np.full(n, 90.0), "heading": np.full(n, heading, np.int16), "navStat": np.zeros(n, np.int8),
            "posAcc": np.ones(n, bool), "raim": np.zeros(n, bool), "rx_ms": np.asarray(t, np.int64) * 1000}


def join(*tracks):
    L = {k: np.concatenate([t[k] for t in tracks]) for k in tracks[0]}
    o = np.lexsort((L["time"], L["mmsi"]))
    return {k: v[o] for k, v in L.items()}


def straight(mmsi, n=400, dt=10, kn=10.0, lat0=60.0, lon0=25.0):
    t = T0 + np.arange(n) * dt
    deg = kn * 1.852 / 3600 / (111.32 * math.cos(math.radians(lat0)))
    return track(mmsi, t, np.full(n, lat0), lon0 + deg * dt * np.arange(n), kn)


def test_build():
    spoofed = straight(273000001, lat0=60.0, lon0=27.5)
    i = np.arange(150, 156)                                   # 6 reports shown inland in Russia at 75 kn, then back
    spoofed["lat"][i], spoofed["lon"][i], spoofed["sog"][i] = 57.7, 32.5, 75.0
    L = join(spoofed,
             straight(273000002, lat0=59.8, lon0=24.0),       # Russian pleasure craft: never output
             straight(273000003, lat0=59.7, lon0=24.0),       # Russian fishing boat: never output
             straight(273000004, lat0=59.6, lon0=23.0),       # Russian pleasure craft with a listed IMO: never output
             straight(636000005, lat0=59.5, lon0=22.0),       # Liberian tanker with a listed IMO: sanctioned
             straight(230000006, lat0=60.1, lon0=22.0),       # Finnish law enforcement
             straight(230000007, lat0=60.2, lon0=22.0))       # Finnish cargo: not output
    meta = {273000001: {"type": 80, "imo": IMO_B, "name": "SPOOFED TANKER", "callSign": "UAAA1", "destination": "RULED",
                        "draught": 95, "refA": 150, "refB": 30, "refC": 15, "refD": 17, "posType": 2},
            273000002: {"type": 37, "name": "YACHT"}, 273000003: {"type": 30, "name": "TRAWLER"},
            273000004: {"type": 37, "imo": IMO_A, "name": "LISTED YACHT"},
            636000005: {"type": 80, "imo": IMO_A, "name": "LISTED TANKER"},
            230000006: {"type": 55, "name": "PATROL"}, 230000007: {"type": 70, "imo": IMO_B, "name": "CARGO"}}
    san = {"by_imo": {str(IMO_A): {"imo": IMO_A, "names": ["LISTED TANKER"], "listings": [
        {"list": "UK Sanctions List", "programme": "Russia (Sanctions) (EU Exit) Regulations 2019, ref RUS9999",
         "date": "2025-05-09", "url": "https://www.gov.uk/government/publications/the-uk-sanctions-list", "id": "RUS9999",
         "name": "LISTED TANKER", "flag": "Russia"}]}}, "by_mmsi": {}, "sources": []}
    baltic, gnss = V.build(L, meta, san, use_land=False)
    vs = {v["mmsi"]: v for v in baltic["vessels"]}
    assert sorted(vs) == [230000006, 273000001, 636000005], sorted(vs)
    assert all(v["ais_type"] not in (30, 36, 37) for v in baltic["vessels"])
    assert set(baltic) == {"generated", "coverage", "sources", "vessels"} and baltic["sources"][0].startswith("Source: Fintraffic")
    keys = {"mmsi", "imo", "name", "callsign", "flag", "ais_type", "ais_type_label", "ais_class", "categories", "listings",
            "last", "track", "reporting", "signals"}
    assert all(set(v) == keys for v in vs.values()), [set(v) ^ keys for v in vs.values()]
    s = vs[273000001]
    assert s["categories"] == ["state_flag_of_interest"] and s["flag"] == "RU" and s["ais_class"] == "A"
    assert s["reporting"]["spoofed_positions"] >= 6 and s["reporting"]["positions"] == 400, s["reporting"]
    assert all(p[1] > 59.9 and p[2] < 28 for p in s["track"]), [p for p in s["track"] if p[1] < 59.9]
    assert s["last"]["lat"] > 59.9 and s["last"]["sog"] == 10.0, s["last"]
    bins = [p[0] // V.THIN_S for p in s["track"]]
    assert len(bins) == len(set(bins)) and len(bins) >= 12, "track thinned to one point per 5-minute bin"
    assert s["signals"]["dimensions"] == {"length_m": 180, "beam_m": 32} and s["signals"]["draught"] == 9.5
    assert s["signals"]["imo_check_digit_ok"] is True and s["listings"] == []
    assert s["signals"]["pos_fix_device"] == "GLONASS" and vs[636000005]["signals"]["pos_fix_device"] is None
    t = vs[636000005]
    assert t["categories"] == ["sanctioned"] and t["flag"] == "LR"
    assert t["listings"] == [{"list": "UK Sanctions List", "programme": "Russia (Sanctions) (EU Exit) Regulations 2019, ref RUS9999",
                              "date": "2025-05-09", "url": "https://www.gov.uk/government/publications/the-uk-sanctions-list",
                              "match": "imo"}], t["listings"]
    assert t["reporting"]["spoofed_positions"] == 0 and t["reporting"]["median_interval_s"] == 10.0
    assert vs[230000006]["categories"] == ["law_enforcement"] and vs[230000006]["signals"]["ais_class"] is None
    assert gnss["affected_vessels"] == 1 and gnss["spoofed_to"] == [{"lat": 57.7, "lon": 32.5, "vessels": 1}], gnss["spoofed_to"]
    assert gnss["by_area"][0]["area"] == "Gulf of Finland east of 27E" and gnss["by_area"][0]["vessels"] == 1, gnss["by_area"]
    assert "mmsi" not in str(gnss).lower() and "SPOOFED TANKER" not in str(gnss), "no identities in the GNSS aggregate"


def test_gaps():
    outs = V.outages(np.array([0, 100, 200, 4000, 4100, 20000]))       # nobody heard 200-4000 and 4100-20000
    assert outs == [(200, 4000), (4100, 20000)], outs
    g = V.gap_hours(np.array([0, 9000, 12000]), [(200, 4000)])          # 2.5 h gap, 1.06 h of it the collector's
    assert len(g) == 1 and abs(g[0] - (9000 - 3800) / 3600) < 1e-9, g
    tt = np.array([0, 10, 299, 300, 650, 700])
    assert [p[0] for p in V.thin_track(tt, np.zeros(6), np.zeros(6))] == [0, 300, 700]


def main():
    tmp = tempfile.mkdtemp()
    try:
        test_sanctions(tmp)
        test_flags_and_categories()
        test_build()
        test_gaps()
        print("test_vessels: ok")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
