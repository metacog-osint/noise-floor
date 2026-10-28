"""Community reports: link public posts (the private Bluesky collection) to NISAR emitter sites.

A post links to a site when:
- it is about interference or the sites (TOPIC);
- it names a place from a private gazetteer (private/watch/community_places.json: name, aliases, lat, lon, radius_km)
  that lies within the place's radius of the site;
- it was posted within WINDOW_DAYS of the site's detections.

Links are leads for an analyst, not corroboration by themselves. A post built on NISAR imagery is the same sensor as
ours, so it is flagged "same_sensor". Post text stays private (data/ and private/ are gitignored). The public export
carries only posts listed in private/watch/community_public.txt (one post URL per line, Tom's approval), and then
only the link, author and date.
"""
import json
import os
import re
from datetime import datetime, timedelta

TOPIC = re.compile(r"nisar|\bsar\b|\brfi\b|interference|jamm|spoof|gnss|\bgps\b|l-band|emitter|radar|notam|"
                   r"burevestnik|test site|missile", re.I)
SAME_SENSOR = re.compile(r"nisar", re.I)
WINDOW_DAYS = 14


def _km(lat1, lon1, lat2, lon2):
    from .public import _km as km
    return km(lat1, lon1, lat2, lon2)


def load_places(path):
    if not os.path.exists(path):
        return []
    places = json.load(open(path, encoding="utf-8"))
    for p in places:
        names = [p["name"]] + list(p.get("aliases", []))
        p["_re"] = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w-])", re.I)
    return places


def load_posts(path):
    if not os.path.exists(path):
        return []
    seen, out = set(), []
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if r.get("uri") in seen:
            continue
        seen.add(r.get("uri"))
        out.append(r)
    return out


def post_text(r):
    alt = r.get("alt") or ""
    if isinstance(alt, list):
        alt = " ".join(str(a) for a in alt)
    quote = r.get("quote") or ""
    if isinstance(quote, dict):
        quote = quote.get("text", "")
    return " ".join(str(x) for x in (r.get("text") or "", alt, quote) if x)


def _when(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


BROAD_KM = 150      # a place with a larger radius names a region: the post becomes an area-level report


def find_links(sites, posts, places, areas=None):
    """sites: list of (area name, site dict); areas: {area name: bbox}. One entry per post, oldest first.

    The post's most specific place decides: a specific place (radius <= BROAD_KM) links the post to the single nearest
    site within that radius that was active within WINDOW_DAYS of the post; a broad place (a region) makes it an
    area-level report for every area whose box contains the place.
    """
    links = []
    for r in posts:
        text = post_text(r)
        if not TOPIC.search(text):
            continue
        named = sorted((p for p in places if p["_re"].search(text)), key=lambda p: p.get("radius_km", 60))
        t = _when(r.get("created_at"))
        if not named or t is None:
            continue
        base = {"uri": r.get("uri"), "url": r.get("url"),
                "author": r.get("author") if isinstance(r.get("author"), str) else r.get("account"),
                "date": r["created_at"][:10], "same_sensor": bool(SAME_SENSOR.search(text)),
                "snippet": re.sub(r"\s+", " ", r.get("text") or "")[:200]}
        place = named[0]
        if place.get("radius_km", 60) > BROAD_KM:
            for name, bb in (areas or {}).items():
                if bb and bb[0] <= place["lon"] <= bb[2] and bb[1] <= place["lat"] <= bb[3]:
                    links.append({**base, "site": None, "area": name, "place": place["name"]})
            continue
        best = None
        for area, s in sites:
            lo = _when(s["first_seen"]) - timedelta(days=WINDOW_DAYS)
            hi = _when(s["last_seen"]) + timedelta(days=WINDOW_DAYS)
            k = _km(place["lat"], place["lon"], s["lat"], s["lon"])
            if lo <= t <= hi and k <= place.get("radius_km", 60) and (best is None or k < best[0]):
                best = (k, area, s)
        if best:
            links.append({**base, "site": best[2]["id"], "area": best[1], "place": place["name"], "km": round(best[0], 1)})
    links.sort(key=lambda x: (x["date"], x["site"] or ""))
    return links


def build_links(cfgs, repo):
    """Links for every site in every area state (all sites, not only public ones: the private view shows them all)."""
    sites, areas = [], {}
    for cfg in cfgs:
        spath = os.path.join(cfg["state_dir"], "state.json")
        if os.path.exists(spath):
            name = cfg.get("aoi", {}).get("public_name") or cfg.get("aoi", {}).get("name", "")
            areas[name] = cfg.get("aoi", {}).get("bbox")
            sites += [(name, s) for s in json.load(open(spath, encoding="utf-8")).get("sites", {}).values()]
    posts = load_posts(os.path.join(repo, "data", "community", "bluesky", "posts.jsonl"))
    places = load_places(os.path.join(repo, "private", "watch", "community_places.json"))
    return find_links(sites, posts, places, areas)


def approved(path):
    """Post URLs Tom approved for the public map (one per line, '#' comments)."""
    if not os.path.exists(path):
        return set()
    return {l.strip() for l in open(path, encoding="utf-8") if l.strip() and not l.startswith("#")}


def public_view(links, ok):
    """Approved links only, and only link, author and date: {site id: [...]}."""
    out = {}
    for x in links:
        if x["url"] in ok and x["site"]:
            out.setdefault(x["site"], []).append({"url": x["url"], "author": x["author"], "date": x["date"],
                                                  "same_sensor": x["same_sensor"]})
    return out
