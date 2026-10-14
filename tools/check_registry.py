#!/usr/bin/env python3
"""check_registry.py — validate registry/sources.csv and enforce the licence rule.

Rule (CLAUDE.md): a source feeds a public layer only with a recorded licence that allows commercial use.
  use=ingest            requires commercial=yes
  commercial=no         allows only use=visual-only or use=exclude
  every row             needs a licence statement and an assessment tag
Runs in the pre-commit hook and CI. Exit 1 lists every problem.
"""
import csv, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "registry", "sources.csv")
COLS = ["id", "name", "lane", "gives", "access", "licence", "commercial", "use", "phase", "assessed", "notes"]
LANES = {"gnss-observed", "maritime", "declared", "context", "satcom", "lf-hf", "emitters", "community", "attribution"}
COMMERCIAL = {"yes", "no", "ask", "unverified"}
USES = {"ingest", "ingest-after-ok", "private-watch", "cite-only", "visual-only", "later", "exclude"}


def problems(rows, header):
    out = []
    if header != COLS:
        out.append(f"header must be {','.join(COLS)}")
        return out
    seen = set()
    for n, r in enumerate(rows, 2):
        rid = r["id"]
        where = f"line {n} ({rid or 'no id'})"
        if not rid or rid in seen:
            out.append(f"{where}: id missing or duplicate")
        seen.add(rid)
        for c in ("name", "lane", "licence", "commercial", "use", "assessed"):
            if not r[c].strip():
                out.append(f"{where}: {c} is empty")
        if r["lane"] not in LANES:
            out.append(f"{where}: lane '{r['lane']}' not in {sorted(LANES)}")
        if r["commercial"] not in COMMERCIAL:
            out.append(f"{where}: commercial '{r['commercial']}' not in {sorted(COMMERCIAL)}")
        if r["use"] not in USES:
            out.append(f"{where}: use '{r['use']}' not in {sorted(USES)}")
        if r["use"] == "ingest" and r["commercial"] != "yes":
            out.append(f"{where}: use=ingest needs commercial=yes (got {r['commercial']})")
        if r["commercial"] == "no" and r["use"] not in ("visual-only", "exclude"):
            out.append(f"{where}: commercial=no allows only visual-only or exclude (got {r['use']})")
        if r["phase"] and r["phase"] not in {str(i) for i in range(1, 8)}:
            out.append(f"{where}: phase '{r['phase']}' not 1-7")
        if r["use"] in ("ingest", "ingest-after-ok", "private-watch") and not r["phase"]:
            out.append(f"{where}: use={r['use']} needs a phase")
    return out


def main():
    with open(PATH, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        rows = list(rd)
        header = rd.fieldnames
    errs = problems(rows, header)
    if errs:
        print("check_registry: " + str(len(errs)) + " problem(s)\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1
    by_use = {}
    for r in rows:
        by_use[r["use"]] = by_use.get(r["use"], 0) + 1
    print(f"check_registry: OK ({len(rows)} sources; " + ", ".join(f"{k} {v}" for k, v in sorted(by_use.items())) + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
