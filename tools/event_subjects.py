#!/usr/bin/env python3
"""event_subjects.py: a jamming event keeps one subject while its centre moves (ideas#118, Tom's yes 24 Nov 2026).

feed_v2.build() keys each event on the H3 res-2 region at its centre. An event is about 300 km across, so its centre
moves from region to region over days of one activity, and the history logged one activity as an "ended" subject and a
"new" one beside it. Measured over four daily rolls (21-24 Nov 2026): 27 of 67 new event subjects sat one region from
an event that ended in the same roll, and only 6 kept their subject.

The rule, applied after the build and before the history run (feed_history.apply):
- A new event takes the subject of an earlier event whose regions it shares, most shared regions first. Earlier
  events are those open in the history state, and those that ended within GAP_HOURS (about two daily rolls), so an
  activity that skips one day keeps its subject too.
- Each subject goes to one item of a feed: the kit's history keeps a second item of a subject under its own dated id,
  which would log it new and ended every day. Of two events that both overlap one earlier subject, the one sharing
  more regions takes it, the other takes its next best match.
- An event that overlaps nothing keeps its centre key, noisefloor:event:<res-2 region>. When that key belongs to an
  open subject the event does not overlap (a subject that has moved away from the region it is named for), or to
  another item of this feed, it takes the first free <region>-2, <region>-3, ...

Only event subjects (noisefloor:event:...) are touched. Spoofing, region, area and space weather keys stay as built.
"""
from datetime import timedelta

PREFIX = "noisefloor:event:"
GAP_HOURS = 50          # two daily rolls (builds run 04:40-06:40 UTC, and a retry can land later the same day)


def is_event(subject_id):
    return isinstance(subject_id, str) and subject_id.startswith(PREFIX)


def regions(geometry):
    """The res-2 regions of an event as published: each polygon of its MultiPolygon is one region's boundary
    (feed_v2.h3_area), so the region is the one at the polygon's mean vertex. A Point (an older event without
    regions) gives its own region."""
    import h3
    if not geometry:
        return set()
    if geometry.get("type") == "Point":
        lon, lat = geometry["coordinates"][:2]
        return {h3.latlng_to_cell(lat, lon, 2)}
    polys = geometry["coordinates"] if geometry.get("type") == "MultiPolygon" else [geometry["coordinates"]]
    out = set()
    for poly in polys:
        ring = poly[0][:-1] if poly[0][0] == poly[0][-1] else poly[0]
        out.add(h3.latlng_to_cell(sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring), 2))
    return out


def earlier_events(state, ended_lines, now):
    """{subject: (regions, open)} for the events a new one may continue: open now, or ended within GAP_HOURS."""
    out = {}
    for k, e in ((state or {}).get("open") or {}).items():
        item = e.get("item") or {}
        sid = (item.get("properties") or {}).get("subject_id") or k
        if is_event(sid) and sid == k:          # an extra item kept under its own id is not a subject to continue
            out[sid] = (regions(item.get("geometry")), True)
    cut = (now - timedelta(hours=GAP_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for x in ended_lines or []:
        sid = x.get("subject_id")
        if x.get("change") != "ended" or not is_event(sid) or sid in out or (x.get("ended_at") or x.get("at") or "") < cut:
            continue
        out[sid] = (regions((x.get("item") or {}).get("geometry")), False)
    return out


def assign(feed, earlier):
    """Set each event item's subject_id in place by the rule above. Returns {item id: (built key, key now)} for the
    items whose key moved."""
    items = [f for f in feed.get("features") or [] if is_event((f.get("properties") or {}).get("subject_id"))]
    own = {id(f): regions(f.get("geometry")) for f in items}
    order = {id(f): i for i, f in enumerate(items)}
    pairs = []
    for f in items:
        for sid, (cells, live) in earlier.items():
            n = len(own[id(f)] & cells)
            if n:
                major = (f["properties"].get("tier") == "anomaly")
                pairs.append((-n, not live, not major, order[id(f)], sid, f))
    pairs.sort(key=lambda t: t[:5])
    chosen, used = {}, set()
    for *_, sid, f in pairs:
        if id(f) in chosen or sid in used:
            continue
        chosen[id(f)] = sid
        used.add(sid)
    taken = set(used) | {sid for sid, (_, live) in earlier.items() if live}
    moved = {}
    for f in items:
        p = f["properties"]
        built = p["subject_id"]
        sid = chosen.get(id(f))
        if sid is None:
            sid, n = built, 1
            while sid in taken:
                n += 1
                sid = f"{built}-{n}"
            taken.add(sid)
        if sid != built:
            moved[p["id"]] = (built, sid)
        p["subject_id"] = sid
    return moved


def apply(feed, state, ended_lines, now):
    return assign(feed, earlier_events(state, ended_lines, now))
