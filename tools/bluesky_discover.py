#!/usr/bin/env python3
"""bluesky_discover.py — find Bluesky accounts that post about EMSO topics, ranked by what they actually post.

Candidates come from (1) account search on topic terms, (2) starter packs found by topic terms, (3) accounts that
several seed accounts follow (co-follow counts), and (4) optional handles to verify. Each candidate is scored on its
own last 50 posts: the share that match core EMSO terms (GNSS/EW/spectrum/radar/SATCOM/ADS-B/AIS/...) and adjacent
terms (satellites, drones, space), plus recency and volume. Public AppView API, no login.

Results reveal what is being watched, so they go to private/watch/ (gitignored).

Usage
  python tools/bluesky_discover.py --seed lemonodor.bsky.social --verify a.bsky.social b.bsky.social
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://public.api.bsky.app/xrpc"
UA = {"User-Agent": "emso-tracker account discovery (research)"}
OUT = os.path.join(ROOT, "private", "watch")
PAUSE_S = 0.35

TERMS = ["GNSS", "GPS jamming", "GNSS interference", "GPS spoofing", "electronic warfare", "spectrum", "SIGINT",
         "radar", "SATCOM", "space domain awareness", "satellite tracking", "ADS-B", "AIS ship tracking",
         "maritime OSINT", "aviation OSINT", "OSINT", "PNT", "eLoran", "SDR radio", "space weather", "ionosphere",
         "SAR imagery", "Sentinel-1", "counter-UAS", "EMSO", "military aviation", "flight tracking", "jamming"]
PACK_TERMS = ["OSINT", "GNSS", "electronic warfare", "space", "satellite", "aviation", "maritime", "defense"]
CORE = re.compile(r"\bGNSS\b|\bGPS\b|GLONASS|BeiDou|jamm|spoof|interferen|electronic warfare|\bEW\b|SIGINT|ELINT|"
                  r"spectrum|\bPNT\b|Loran|Chayka|radar|SATCOM|\bADS-?B\b|\bAIS\b|NOTAM|ionospher|geomagnetic|"
                  r"\bSDR\b|\bHF\b|over-the-horizon|\bRF\b|EMSO|Sentinel-1|\bSAR\b|counter-?UAS", re.I)
ADJ = re.compile(r"satellite|Starlink|\borbit|\bspace\b|drone|\bUAV\b|missile|air defen[cs]e|military aircraft|"
                 r"flight track|ship track|OSINT", re.I)


def get(method, **params):
    url = f"{API}/{method}?{urllib.parse.urlencode(params, doseq=True)}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                time.sleep(PAUSE_S)
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(2 + 3 * attempt)
        except Exception:
            time.sleep(2 + 3 * attempt)
    return None


def gather(seeds, verify, max_follows):
    src = defaultdict(set)       # did -> sources
    cofollow = Counter()
    handle_of = {}
    for t in TERMS:
        d = get("app.bsky.actor.searchActors", q=t, limit=25) or {}
        for a in d.get("actors", []):
            src[a["did"]].add(f"search:{t}"); handle_of[a["did"]] = a["handle"]
    for t in PACK_TERMS:
        d = get("app.bsky.graph.searchStarterPacks", q=t, limit=10) or {}
        for sp in d.get("starterPacks", []):
            lst = ((sp.get("record") or {}).get("list"))
            if not lst:
                continue
            members = get("app.bsky.graph.getList", list=lst, limit=100) or {}
            name = (sp.get("record") or {}).get("name", "")[:40]
            for it in members.get("items", []):
                s = it.get("subject") or {}
                if s.get("did"):
                    src[s["did"]].add(f"pack:{name}"); handle_of[s["did"]] = s.get("handle", "")
    for seed in seeds:
        cursor, n = None, 0
        while n < max_follows:
            d = get("app.bsky.graph.getFollows", actor=seed, limit=100, **({"cursor": cursor} if cursor else {})) or {}
            for a in d.get("follows", []):
                src[a["did"]].add(f"followed-by:{seed}"); cofollow[a["did"]] += 1; handle_of[a["did"]] = a["handle"]; n += 1
            cursor = d.get("cursor")
            if not cursor:
                break
    for h in verify:
        d = get("com.atproto.identity.resolveHandle", handle=h)
        if d and d.get("did"):
            src[d["did"]].add("verify"); handle_of[d["did"]] = h
    return src, cofollow, handle_of


def profiles(dids):
    out = {}
    dids = list(dids)
    for i in range(0, len(dids), 25):
        d = get("app.bsky.actor.getProfiles", actors=dids[i:i + 25]) or {}
        for p in d.get("profiles", []):
            out[p["did"]] = p
    return out


def score(did, prof, now):
    feed = get("app.bsky.feed.getAuthorFeed", actor=did, limit=50, filter="posts_no_replies") or {}
    posts = [it["post"] for it in feed.get("feed", []) if (it.get("post") or {}).get("author", {}).get("did") == did]
    if not posts:
        return None
    texts = []
    for po in posts:
        emb = po.get("embed") or {}
        alts = " ".join(i.get("alt", "") for i in (emb.get("images") or []) + ((emb.get("media") or {}).get("images") or []))
        ext = (emb.get("external") or {}).get("title", "")
        texts.append(((po.get("record") or {}).get("text", "") + " " + alts + " " + ext, po))
    core = [po for t, po in texts if CORE.search(t)]
    adj = [po for t, po in texts if not CORE.search(t) and ADJ.search(t)]
    last = max((po.get("indexedAt") or "") for po in posts)
    days = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).days if last else 9999
    bio = (prof.get("description") or "")
    s = (len(core) + 0.3 * len(adj)) / len(posts) + (0.25 if CORE.search(bio) else 0) + (0.1 if ADJ.search(bio) else 0)
    s *= 1.0 if days <= 14 else 0.7 if days <= 60 else 0.3
    ex = max(core, key=lambda po: (po.get("likeCount") or 0), default=None)
    return {"score": round(s, 3), "core_share": round(len(core) / len(posts), 2), "adj_share": round(len(adj) / len(posts), 2),
            "posts_checked": len(posts), "days_since_post": days,
            "example": (f"https://bsky.app/profile/{prof.get('handle')}/post/{ex['uri'].rsplit('/', 1)[-1]}" if ex else None),
            "example_text": " ".join(((ex or {}).get("record") or {}).get("text", "").split())[:160]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="append", default=[])
    ap.add_argument("--verify", nargs="*", default=[])
    ap.add_argument("--max-follows", type=int, default=2000)
    ap.add_argument("--top", type=int, default=60)
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    src, cofollow, handle_of = gather(a.seed, a.verify, a.max_follows)
    print(f"candidates: {len(src)}", file=sys.stderr)
    profs = profiles(src)
    # prefilter: topic words in bio, found by search/verify, or followed by a seed
    keep = [d for d, p in profs.items()
            if (CORE.search(p.get("description") or "") or ADJ.search(p.get("description") or "")
                or "verify" in src[d] or any(s.startswith("followed-by") for s in src[d]))
            and (p.get("postsCount") or 0) >= 20]
    print(f"scoring: {len(keep)}", file=sys.stderr)
    rows = []
    for d in keep:
        sc = score(d, profs[d], now)
        if not sc:
            continue
        p = profs[d]
        rows.append({"handle": p.get("handle"), "name": p.get("displayName") or "", "did": d,
                     "bio": " ".join((p.get("description") or "").split())[:200], "followers": p.get("followersCount"),
                     "posts": p.get("postsCount"), "cofollow": cofollow[d], "sources": sorted(src[d])[:4], **sc})
    rows.sort(key=lambda r: (-r["score"], -(r["followers"] or 0)))
    os.makedirs(OUT, exist_ok=True)
    json.dump(rows, open(os.path.join(OUT, "bluesky_candidates.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps({"candidates": len(src), "scored": len(rows), "file": "private/watch/bluesky_candidates.json"}))


if __name__ == "__main__":
    main()
