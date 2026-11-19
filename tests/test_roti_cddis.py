"""Ground ROTI: a file BKG can't deliver comes from NASA CDDIS when an Earthdata token is set (no network here)."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ground_roti as G  # noqa: E402

BKG = "https://igs.bkg.bund.de/root_ftp/IGS/obs/2026/321/NKLG00GAB_R_20263210000_01D_30S_MO.crx.gz"
CDDIS = "https://cddis.nasa.gov/archive/gnss/data/daily/2026/321/26d/NKLG00GAB_R_20263210000_01D_30S_MO.crx.gz"


def run(token):
    calls = []

    def fake_download(url, dest, tries=3, headers=None):
        calls.append((url, headers))
        if "bkg" in url:
            raise TimeoutError("timed out")
        return dest

    saved = G.download, G.SC.cddis_headers
    G.download = fake_download
    G.SC.cddis_headers = (lambda: {"Authorization": "Bearer x"}) if token else (lambda: None)
    try:
        return G.fetch(BKG, tempfile.gettempdir(), lambda: CDDIS, log=lambda *a: None), calls
    finally:
        G.download, G.SC.cddis_headers = saved


def test_fallback():
    (path, src), calls = run(token=True)
    assert src == "CDDIS" and path.endswith("NKLG00GAB_R_20263210000_01D_30S_MO.crx.gz"), (path, src)
    assert calls[0] == (BKG, None) and calls[1][0] == CDDIS and calls[1][1]["Authorization"].startswith("Bearer ")


def test_no_token_keeps_the_error():
    try:
        run(token=False)
    except TimeoutError:
        return
    raise AssertionError("without a token the BKG error must stand")


def test_credit_names_cddis():
    doc = G.build("2026-11-17", {}, [], {}, "BRDC00IGS_R_20263210000_01D_MN.rnx.gz", nav_from="CDDIS")
    assert G.CREDIT_CDDIS in doc["credit"] and doc["source"]["via_cddis"] == ["nav"], doc["source"]
    doc = G.build("2026-11-17", {}, [], {}, "BRDC00IGS_R_20263210000_01D_MN.rnx.gz")
    assert G.CREDIT_CDDIS not in doc["credit"] and "via_cddis" not in doc["source"]


if __name__ == "__main__":
    test_fallback()
    test_no_token_keeps_the_error()
    test_credit_names_cddis()
    print("test_roti_cddis: ok")
