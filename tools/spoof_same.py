#!/usr/bin/env python3
"""spoof_same.py: are two tools/spoof_day.py output folders the same, day by day?

  python tools/spoof_same.py DIR_A DIR_B [--days 2026-11-07 ...] [--json report.json] [--quiet]

For each day it compares
  events    <day>.events.json.gz, as sorted canonical JSON (order of episodes doesn't matter);
  tables    <day>.hex4 / hex2 / daily4 .parquet, as tables sorted on every column (pyarrow sort and Table.equals);
  summary   <day>.summary.json without the timing and provenance keys (seconds*, cpu_*, version, rerun, workers,
            method, cache_format); the *_top lists are classed:
              same        identical;
              tie-order   the same entries, in a different order among equal counts;
              tie-at-cut  the same entries above the cut and the same counts at it, but a different pick among the
                          entries tied at the cut count (the list is cut at 20 or 40 places);
              differs     anything else.
Only `differs` and a difference in events, tables or other summary values count as real. A day missing from one side
counts as real. Exit status: 0 if there is no real difference, 1 otherwise. tie-order and tie-at-cut are reported and
don't fail the run: spoof_day sorts records before aggregating, so they come only from runs made before that.

Every output folder of spoof_day (run, rerun) has this layout, so a rerun can be checked against the full run, a rerun
from one cache format against another, or a variant against a reference made earlier.
"""
import argparse
import gzip
import json
import os
import sys

import orjson
import pyarrow.compute as pc
import pyarrow.parquet as pq

TABLES = ("hex4", "hex2", "daily4")
SKIP = {"seconds", "seconds_read", "version", "rerun", "workers", "method", "cache_format"}
SKIP_PREFIX = ("seconds", "cpu_")


def skipped(key):
    return key in SKIP or key.startswith(SKIP_PREFIX)


def canon(x):
    return orjson.dumps(x, option=orjson.OPT_SORT_KEYS)


def load_events(path):
    with gzip.open(path, "rb") as f:
        d = orjson.loads(f.read())
    if isinstance(d, dict):
        for k in ("events", "episodes"):
            if k in d:
                return d[k]
    return d


def compare_events(pa_, pb_):
    ea, eb = sorted(canon(e) for e in load_events(pa_)), sorted(canon(e) for e in load_events(pb_))
    if ea == eb:
        return "same", len(ea)
    sa, sb = set(ea), set(eb)
    return f"DIFF a={len(ea)} b={len(eb)} only_a={len(sa - sb)} only_b={len(sb - sa)}", len(ea)


def sorted_table(path):
    t = pq.read_table(path)
    cols = sorted(t.column_names)
    t = t.select(cols)
    return t.take(pc.sort_indices(t, sort_keys=[(c, "ascending") for c in cols])) if t.num_rows else t


def _norm(rows):
    return sorted(canon([None if isinstance(v, float) and v != v else v for v in r.values()]) for r in rows)


def compare_table(pa_, pb_):
    ta, tb = sorted_table(pa_), sorted_table(pb_)
    if ta.schema.names != tb.schema.names:
        return f"DIFF columns a={ta.schema.names} b={tb.schema.names}"
    if [str(f.type) for f in ta.schema] != [str(f.type) for f in tb.schema]:
        return "DIFF column types"
    if ta.num_rows == tb.num_rows and ta.equals(tb):
        return "same"
    ra, rb = _norm(ta.to_pylist()), _norm(tb.to_pylist())       # NaN != NaN in Table.equals: look at the rows
    if ra == rb:
        return "same"
    sa, sb = set(ra), set(rb)
    return f"DIFF rows a={ta.num_rows} b={tb.num_rows} only_a={len(sa - sb)} only_b={len(sb - sa)}"


def top_key(x):
    if isinstance(x, dict):
        return x.get("n", x.get("count"))
    return x[-1] if isinstance(x, (list, tuple)) else x


def top_compare(a, b):
    """'same', 'tie-order', 'tie-at-cut' or 'differs' for two top-N lists (count last in each entry)."""
    if a == b:
        return "same"
    ca, cb = sorted(canon(x) for x in a), sorted(canon(x) for x in b)
    ka, kb = [top_key(x) for x in a], [top_key(x) for x in b]
    if ca == cb:
        return "tie-order" if ka == kb else "differs"
    try:
        cut = min(ka)
        if ka == kb and sorted(canon(x) for x in a if top_key(x) != cut) == sorted(canon(x) for x in b if top_key(x) != cut):
            return "tie-at-cut"
    except TypeError:
        pass
    return "differs"


def compare_summary(pa_, pb_):
    with open(pa_, encoding="utf-8") as f:
        sa = json.load(f)
    with open(pb_, encoding="utf-8") as f:
        sb = json.load(f)
    diffs, ties = {}, {}
    for k in sorted(set(sa) | set(sb)):
        if skipped(k):
            continue
        va, vb = sa.get(k), sb.get(k)
        if k.endswith("_top") and isinstance(va, list) and isinstance(vb, list):
            c = top_compare(va, vb)
            if c == "differs":
                diffs[k] = c
            elif c != "same":
                ties[k] = c
        elif canon(va) != canon(vb):
            diffs[k] = {"a": va, "b": vb} if len(canon(va)) + len(canon(vb)) < 400 else "differs (long)"
    return diffs, ties, sa, sb


def compare_day(a_dir, b_dir, day):
    r = {"real_difference": False}
    need = [f"{day}.events.json.gz", f"{day}.summary.json"] + [f"{day}.{t}.parquet" for t in TABLES]
    missing = {s: [n for n in need if not os.path.exists(os.path.join(d, n))] for s, d in (("a", a_dir), ("b", b_dir))}
    if missing["a"] or missing["b"]:
        r["missing"] = {k: v for k, v in missing.items() if v}
        r["real_difference"] = True
        return r
    r["events"], r["n_events"] = compare_events(*(os.path.join(d, f"{day}.events.json.gz") for d in (a_dir, b_dir)))
    for t in TABLES:
        r[t] = compare_table(*(os.path.join(d, f"{day}.{t}.parquet") for d in (a_dir, b_dir)))
    diffs, ties, sa, sb = compare_summary(*(os.path.join(d, f"{day}.summary.json") for d in (a_dir, b_dir)))
    r["summary"] = diffs or "same"
    if ties:
        r["ties"] = ties
    for key in ("seconds", "seconds_read", "cpu_seconds"):
        r[f"{key}_a"], r[f"{key}_b"] = sa.get(key), sb.get(key)
    r["real_difference"] = bool(diffs) or r["events"] != "same" or any(r[t] != "same" for t in TABLES)
    return r


def days_in(d):
    return sorted({f[:10] for f in os.listdir(d) if f[:2] == "20" and f.endswith(".summary.json")})


def compare(a_dir, b_dir, days=None):
    """Report dict: per day, plus 'real_differences' (days with one) and 'tie_days' (days with only benign ties)."""
    days = days or days_in(a_dir)
    per = {day: compare_day(a_dir, b_dir, day) for day in days}
    return {"a": a_dir, "b": b_dir, "days": per,
            "n_days": len(per),
            "real_differences": [d for d, r in per.items() if r["real_difference"]],
            "tie_days": [d for d, r in per.items() if r.get("ties") and not r["real_difference"]],
            "same": not any(r["real_difference"] for r in per.values()) and bool(per)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--days", nargs="+", help="default: every day with a summary in A")
    ap.add_argument("--json", help="write the full report here")
    ap.add_argument("--quiet", action="store_true", help="print only the verdict and the days that differ")
    a = ap.parse_args()
    rep = compare(a.a, a.b, a.days)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, default=str)
    if not a.quiet:
        print(json.dumps(rep["days"], indent=1, default=str))
    bad = rep["real_differences"]
    print(f"{rep['n_days']} days: " + ("no real difference" if rep["same"] else f"REAL DIFFERENCE on {len(bad)}: {bad}")
          + (f"; tie-order or tie-at-cut only on {rep['tie_days']}" if rep["tie_days"] else ""))
    for d in bad:
        print(d, {k: v for k, v in rep["days"][d].items() if k not in ("real_difference",) and v != "same"
                  and not k.startswith(("seconds", "cpu_"))})
    sys.exit(0 if rep["same"] else 1)


if __name__ == "__main__":
    main()
