"""Feed contract v2: check one item and report problems against ICD 203's nine
tradecraft standards.

An item is a GeoJSON Feature (contract fields in "properties") or a plain object
holding the same fields with an optional "geometry". Problems are tuples of
(standard_id, severity, message) where severity is "error" or "warning".
"""

import re

from . import CONTRACT, likelihood, vocab

UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
JUDGED_KINDS = {"assessment", "forecast"}

# Standard 0 holds contract-level problems that no ICD 203 standard covers.
GENERAL = "general"


def split(item: dict) -> tuple[dict, object]:
    """(properties, geometry) for a Feature or a flat item."""
    if item.get("type") == "Feature":
        return item.get("properties") or {}, item.get("geometry")
    return item, item.get("geometry")


def is_judgment(p: dict) -> bool:
    return p.get("tier") == "warning" or p.get("kind") in JUDGED_KINDS


def check(item: dict, registers: dict | None = None) -> list[tuple[str, str, str]]:
    """All problems with one item. registers (optional) holds the program's
    requirement, warning-problem and indicator ids for link checks."""
    p, geom = split(item)
    out = []

    def err(std, msg):
        out.append((std, "error", msg))

    def warn(std, msg):
        out.append((std, "warning", msg))

    def one_of(std, key, allowed, required=True):
        v = p.get(key)
        if v is None:
            if required:
                err(std, f"{key} missing")
            return
        if v not in allowed:
            err(std, f"{key}={v!r} not in {sorted(allowed)}")

    def utc(std, key, required=True):
        v = p.get(key)
        if v is None:
            if required:
                err(std, f"{key} missing")
        elif not isinstance(v, str) or not UTC_RE.match(v):
            err(std, f"{key}={v!r} is not ISO 8601 UTC ending in Z")

    judged = is_judgment(p)

    # General contract fields.
    if p.get("contract") != CONTRACT:
        err(GENERAL, f"contract must be {CONTRACT!r}")
    for key in ("id", "program", "title"):
        if not p.get(key):
            err(GENERAL if key != "title" else "argumentation", f"{key} missing")
    one_of(GENERAL, "status", vocab.enum("status"))
    one_of(GENERAL, "msg_type", vocab.enum("msg_type"))
    one_of(GENERAL, "human_review", vocab.enum("human_review"))
    if p.get("us_person_data") != "none":
        err(GENERAL, "us_person_data must be 'none'")
    utc("sources", "data_as_of")
    utc("sources", "published_at")
    utc(GENERAL, "valid_until", required=False)
    countries = p.get("countries")
    if countries is None:
        err(GENERAL, "countries missing (use [] for none)")
    elif not isinstance(countries, list) or any(not isinstance(c, str) or not COUNTRY_RE.match(c) for c in countries):
        err(GENERAL, "countries must be ISO 3166-1 alpha-2 codes (XK allowed)")
    if p.get("evidence_hash") is not None and not HASH_RE.match(str(p["evidence_hash"])):
        err(GENERAL, "evidence_hash must be 'sha256:' plus 64 hex digits")

    # Tags.
    for key, fw in (("ie_aspect", "ie_aspect"), ("pmesii_pt", "pmesii_pt"), ("ascope", "ascope")):
        v = p.get(key)
        if v is not None:
            allowed = set(vocab.framework(fw)["values"])
            bad = [x for x in (v if isinstance(v, list) else [v]) if x not in allowed]
            if bad:
                err(GENERAL, f"{key} has unknown values {bad}")
    if p.get("continuum") is not None and p["continuum"] not in vocab.framework("continuum")["values"]:
        err(GENERAL, f"continuum={p['continuum']!r} unknown")
    one_of(GENERAL, "product_category", vocab.enum("product_category"), required=False)
    one_of(GENERAL, "precision_class", vocab.enum("precision_class"), required=False)
    ncf_ids = p.get("ncf")
    if ncf_ids is not None:
        bad = [f for f in ncf_ids if f not in vocab.ncf()]
        if bad:
            err(GENERAL, f"ncf has unknown functions {bad}")
        elif p.get("sector") is not None and sorted(p["sector"]) != vocab.derive_sectors(ncf_ids):
            err(GENERAL, "sector does not match the sectors derived from ncf")
    for entry in p.get("lifeline") or []:
        if not isinstance(entry, dict) or entry.get("id") not in vocab.lifelines()["values"] \
                or entry.get("status") not in vocab.lifelines()["status"]:
            err(GENERAL, f"lifeline entry {entry!r} needs a known id and status")
    rs = p.get("response_stage")
    if rs is not None:
        ladder, _, value = str(rs).partition(":")
        if ladder not in vocab.ladders() or value not in vocab.ladders()[ladder]["values"]:
            err(GENERAL, f"response_stage={rs!r} is not 'ladder:value' from grading.json")

    # 1. Sources, data and method.
    sources = p.get("sources")
    if not sources:
        err("sources", "sources[] missing or empty")
    else:
        for i, s in enumerate(sources):
            for key in ("publisher", "licence"):
                if not s.get(key):
                    err("sources", f"sources[{i}].{key} missing")
            if not s.get("accessed_at") and not s.get("published_at"):
                warn("sources", f"sources[{i}] needs accessed_at or published_at (ICS 206-01)")
            if not (s.get("url") or s.get("id")):
                err("sources", f"sources[{i}] needs a url or a register id")
            if not s.get("descriptor"):
                warn("sources", f"sources[{i}].descriptor missing (ICS 206-01 source descriptor)")
            g = s.get("grade")
            if g is not None and not (isinstance(g, str) and len(g) == 2
                                      and g[0] in vocab.admiralty()["reliability"]
                                      and g[1] in vocab.admiralty()["credibility"]):
                err("sources", f"sources[{i}].grade={g!r} is not an Admiralty grade like 'B2'")
    if not p.get("method_version"):
        err("sources", "method_version missing")
    cov = p.get("coverage_fraction")
    if cov is None:
        if p.get("indicator_state") != "no_data":
            warn("sources", "coverage_fraction missing")
    elif not isinstance(cov, (int, float)) or not 0 <= cov <= 1:
        err("sources", "coverage_fraction must be 0 to 1")

    # 2. Uncertainty.
    if judged:
        prob = p.get("probability")
        if prob is None:
            err("uncertainty", "a judgment needs probability (stored as a number)")
        else:
            try:
                expected = likelihood.term_for(prob)["id"]
                if p.get("likelihood_term") != expected:
                    err("uncertainty", f"likelihood_term should be {expected!r} for probability {prob}")
            except ValueError as e:
                err("uncertainty", str(e))
        one_of("uncertainty", "confidence", {"low", "moderate", "high"})
        if not p.get("confidence_basis"):
            err("uncertainty", "confidence_basis missing")
    if p.get("tier") == "anomaly" and not p.get("baseline_ref"):
        err("uncertainty", "an anomaly needs baseline_ref (baseline id, window, fixed or rolling)")

    # 3. Information versus judgment.
    one_of("distinguish", "kind", vocab.enum("kind"))
    one_of("distinguish", "tier", vocab.enum("tier"))
    one_of("distinguish", "status_class", vocab.enum("status_class"))
    if p.get("kind") == "observation" and p.get("tier") == "warning":
        err("distinguish", "an observation cannot be a warning: a warning is a judgment")
    if p.get("kind") in JUDGED_KINDS and p.get("tier") == "anomaly":
        err("distinguish", "an anomaly is a measurement: use kind=observation")

    # 4. Alternatives.
    if judged:
        alts = p.get("alternatives") or []
        if not alts:
            err("alternatives", "a judgment needs alternatives[]")
        for i, a in enumerate(alts):
            if not a.get("hypothesis") or not a.get("tell_apart"):
                err("alternatives", f"alternatives[{i}] needs hypothesis and tell_apart (the indicator that separates it)")

    # 5. Relevance to a written requirement.
    linked = p.get("requirement_ids") or ([p["warning_problem_id"]] if p.get("warning_problem_id") else [])
    if not linked:
        (err if judged else warn)("relevance", "no requirement_ids or warning_problem_id")
    if registers:
        known = registers.get("requirements", set()) | registers.get("warning_problems", set())
        for r in linked:
            if r not in known:
                err("relevance", f"{r!r} is not in the program's requirements or warning problems")

    # 6. Argumentation.
    if judged and not p.get("summary"):
        err("argumentation", "a judgment needs a summary (bottom line up front)")
    if p.get("indicator_id"):
        if not p.get("hypothesis_id"):
            err("argumentation", "indicator_id without hypothesis_id")
        one_of("argumentation", "direction", vocab.enum("direction"))
        one_of("argumentation", "indicator_state", vocab.enum("indicator_state"))
        if registers and p["indicator_id"] not in registers.get("indicators", {p["indicator_id"]}):
            err("argumentation", f"indicator {p['indicator_id']!r} is not in indicators.json")

    # 7. Change.
    if judged:
        one_of("change", "change_from_prior", vocab.enum("change_from_prior"))
        if p.get("change_from_prior") not in (None, "new", "unchanged") and not p.get("change_reason"):
            err("change", "change_reason missing for a changed judgment")
    if p.get("msg_type") in ("update", "cancel", "error") and not p.get("supersedes"):
        err("change", f"msg_type={p['msg_type']} needs supersedes")

    # 8. Accuracy: scoreable forecasts.
    if p.get("kind") == "forecast":
        res = p.get("resolution") or {}
        for key in ("rule", "source", "resolve_by"):
            if not res.get(key):
                err("accuracy", f"forecast needs resolution.{key}")
        if not p.get("valid_until"):
            err("accuracy", "forecast needs valid_until")

    # 9. Visual first.
    vis = p.get("visual")
    if geom is None and not (isinstance(vis, dict) and vis.get("type") and vis.get("url")):
        err("visual", "no geometry and no visual {type, url}: a finding without a visual is not finished")
    if geom is None and p.get("precision_class") not in (None, "none", "country", "admin1"):
        err("visual", f"precision_class={p.get('precision_class')!r} but geometry is null")

    return out
