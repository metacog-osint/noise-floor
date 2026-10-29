"""Build nisar/nisar_rfi/assets/regions.json.gz: named physical regions and seas for place wording.

Where no town of 50,000+ is within 150 km, a site is described by the named region it lies in ("Novaya Zemlya",
"Danakil Desert", "Caspian Sea") instead of bare coordinates. Source: Natural Earth 10m geography regions and marine
polygons, v5.1.2 (public domain), downloaded once into data/natural_earth/ (gitignored).

Run: python tools/build_place_regions.py
"""
import gzip
import json
import os
import urllib.request

from shapely.geometry import mapping, shape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NE_DIR = os.path.join(ROOT, "data", "natural_earth")
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/{}.geojson"
OUT = os.path.join(ROOT, "nisar", "nisar_rfi", "assets", "regions.json.gz")
SKIP = {"Continent"}                    # too broad to say anything


def natural_earth(name):
    path = os.path.join(NE_DIR, f"{name}.geojson")
    if not os.path.exists(path):
        os.makedirs(NE_DIR, exist_ok=True)
        with urllib.request.urlopen(NE_URL.format(name), timeout=120) as r:
            open(path, "wb").write(r.read())
    return json.load(open(path, encoding="utf-8"))


def features(name, cls_key, name_keys):
    out = []
    for f in natural_earth(name)["features"]:
        p = f["properties"]
        cls = p.get(cls_key) or ""
        label = next((" ".join(str(p[k]).split()) for k in name_keys if p.get(k)), "")
        if not label or cls in SKIP:
            continue
        g = shape(f["geometry"]).simplify(0.02, preserve_topology=True)
        if g.is_empty:
            continue
        geom = mapping(g)
        geom["coordinates"] = json.loads(json.dumps(geom["coordinates"]), parse_float=lambda x: round(float(x), 3))
        out.append({"name": label, "class": cls, "geometry": geom})
    return out


def main():
    doc = {"_source": "Natural Earth 10m geography regions and marine polygons v5.1.2; public domain",
           "land": features("ne_10m_geography_regions_polys", "FEATURECLA", ("NAME_EN", "NAME")),
           "sea": features("ne_10m_geography_marine_polys", "featurecla", ("name_en", "name"))}
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(doc['land'])} land regions, {len(doc['sea'])} seas -> {os.path.relpath(OUT, ROOT)} "
          f"({os.path.getsize(OUT) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
