"""Offline checks for community links (nisar_rfi/community.py). Run: python tests/test_community.py (from nisar/)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from nisar_rfi import community  # noqa: E402


def place(name, lat, lon, radius, aliases=()):
    return {"name": name, "aliases": list(aliases), "lat": lat, "lon": lon, "radius_km": radius}


def main():
    import re
    places = [place("Pankovo", 73.10, 53.70, 60, ["Панково"]), place("Novaya Zemlya", 73.5, 55.5, 350)]
    for p in places:
        p["_re"] = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in [p["name"]] + p["aliases"]) + r")(?![\w-])", re.I)
    sites = [("NZ", {"id": "NZ-0029", "lat": 73.06, "lon": 53.72, "first_seen": "2026-10-07T23:10:54Z", "last_seen": "2026-10-19T23:10:54Z"}),
             ("NZ", {"id": "NZ-0024", "lat": 73.21, "lon": 53.59, "first_seen": "2026-09-23T22:54:59Z", "last_seen": "2026-10-05T22:55:00Z"})]
    areas = {"NZ": [51.0, 70.8, 57.5, 74.2]}
    posts = [
        {"uri": "a", "url": "https://x/a", "author": "puca.bsky.social", "created_at": "2026-10-18T11:07:51Z",
         "text": "NISAR Frequency A vs Sentinel-1 RFI at Pankovo"},
        {"uri": "b", "url": "https://x/b", "author": "someone", "created_at": "2026-10-18T12:00:00Z",
         "text": "Lovely sunset at Pankovo"},                                   # no interference topic: skipped
        {"uri": "c", "url": "https://x/c", "author": "someone", "created_at": "2026-12-30T12:00:00Z",
         "text": "jamming near Pankovo"},                                       # outside every site's window
        {"uri": "d", "url": "https://x/d", "author": "puca.bsky.social", "created_at": "2026-10-23T10:00:00Z",
         "text": "Monitoring vessels in a test-like configuration around Novaya Zemlya; Burevestnik?"},   # region only
        {"uri": "e", "url": "https://x/e", "author": "ru", "created_at": "2026-10-10T10:00:00Z",
         "text": "Панково: GPS jamming reported"},                              # alias
    ]
    links = community.find_links(sites, posts, places, areas)
    got = [(x["uri"], x["site"], x.get("area")) for x in links]
    assert got == [("e", "NZ-0029", "NZ"), ("a", "NZ-0029", "NZ"), ("d", None, "NZ")], got
    assert links[1]["same_sensor"] and not links[0]["same_sensor"]
    pub = community.public_view(links, {"https://x/a", "https://x/d"})
    assert list(pub) == ["NZ-0029"] and pub["NZ-0029"] == [
        {"url": "https://x/a", "author": "puca.bsky.social", "date": "2026-10-18", "same_sensor": True}], pub
    assert "snippet" not in pub["NZ-0029"][0]
    print("community links: topic, place, window, region-level, approval OK")


if __name__ == "__main__":
    main()
