"""NISAR L-band sub-bands and the GNSS / radar allocations they overlap.

NISAR splits its 1215-1300 MHz allocation into a main band (Frequency A) and a
5 MHz split-spectrum band (Frequency B). Which slices are used depends on the
acquisition mode (RANGE_BANDWIDTH_CONCAT in CMR, e.g. "20+5" over the Baltic).
Centre frequencies: NISAR Data User Guide, "Frequencies" table.
"""

# mode -> {freq: (centre MHz, bandwidth MHz)}
MODES = {
    "77":    {"A": (1257.5, 77.0)},
    "40+5":  {"A": (1239.0, 40.0), "B": (1293.5, 5.0)},
    "20+5":  {"A": (1229.0, 20.0), "B": (1293.5, 5.0)},
    "20+20": {"A": (1229.0, 20.0), "B": (1286.0, 20.0)},
    "5+5":   {"A": (1221.5, 5.0),  "B": (1236.5, 5.0)},
    # 5 MHz only, VV (polar and sea-ice coverage: Novaya Zemlya, Kola). The products label the slice B.
    "5":     {"B": (1221.5, 5.0)},
}

# What each mode's RFI tables actually span: the processor's own frequency axis, read from products on 29 Oct 2026
# (20+5: a Gulf pass, 28 Sep; 5: a Novaya Zemlya pass, 19 Oct). The tables span more than the image band.
# (low MHz, high MHz, dual-pol). Modes not listed aren't checked yet: their passes count as able to hear anything.
TABLE_SPAN = {
    "20+5": [(1215.0, 1263.0, True), (1290.5, 1296.5, True)],     # A 1215.00-1262.95 and B 1290.50-1296.49, HH+HV
    "5":    [(1218.5, 1224.5, False)],                            # B 1218.50-1224.49, VV only: no L2 centre, no cross-pol
}

# GNSS signals in 1215-1300 MHz: (name, low MHz, high MHz), main-lobe extents.
GNSS = [
    ("GPS L2",       1227.60 - 10.23, 1227.60 + 10.23),
    ("GLONASS G2",   1242.94 - 0.51,  1248.63 + 0.51),
    ("BeiDou B3",    1268.52 - 10.23, 1268.52 + 10.23),
    ("Galileo E6",   1278.75 - 20.46, 1278.75 + 20.46),
    ("QZSS L6",      1278.75 - 21.0,  1278.75 + 21.0),
]
RADAR_NOTE = "1215-1400 MHz is also the L-band air-surveillance / long-range radar allocation"


def band_edges(mode, freq, centre_mhz=None, bw_mhz=None):
    """(low, high) MHz for a sub-band. Product values win over the mode table."""
    if centre_mhz and bw_mhz:
        return centre_mhz - bw_mhz / 2, centre_mhz + bw_mhz / 2
    table = MODES.get(str(mode).replace(" ", ""), MODES["20+5"])
    if freq not in table:
        return None
    c, bw = table[freq]
    return c - bw / 2, c + bw / 2


def signal_needs(d):
    """What a pass must receive to detect this detection's signal again: [("tone", lo, hi) | ("broad", lo, hi)].

    A tone needs a slice containing its frequencies; broadband power needs a dual-polarization slice over the same
    frequencies (the cross-pol test). Band edges come from the detection's own mode."""
    mode, out = d.get("mode") or "20+5", []

    def add(part, band):
        runs = part.get("freq_runs_mhz") or []
        out.extend(("tone", r[0], r[1]) for r in runs)
        e = band_edges(mode, band) if band else None
        if e and (part.get("method") == "broadband" or part.get("broadband")):
            out.append(("broad", e[0], e[1]))
        elif e and not runs:
            out.append(("any", e[0], e[1]))       # no frequency detail: the slice itself
    add(d, d.get("band"))
    if isinstance(d.get("band_b"), dict):
        add(d["band_b"], "B")
    return out


def hears(modes, needs):
    """True if a pass in any of `modes` could detect at least one of `needs`. Unknown modes or needs: True."""
    modes = [m for m in (modes or []) if m]
    if not modes or not needs:
        return True
    for m in modes:
        span = TABLE_SPAN.get(str(m).replace(" ", ""))
        if span is None:
            return True
        for lo, hi, dual in span:
            for kind, a, b in needs:
                if a <= hi and b >= lo and (kind != "broad" or dual):
                    return True
    return False


def gnss_in(low, high):
    """GNSS signals whose main lobe overlaps [low, high] MHz."""
    return [n for n, lo, hi in GNSS if lo < high and hi > low]


def describe(bands, mode):
    """Human label for a detection seen in `bands` (e.g. ["A"], ["B"], ["A", "B"])."""
    parts, sig = [], []
    for b in bands:
        e = band_edges(mode, b)
        if not e:
            continue
        parts.append(f"{b} {e[0]:.0f}-{e[1]:.0f} MHz")
        sig += [s for s in gnss_in(*e) if s not in sig]
    return {
        "bands": bands,
        "band_text": " + ".join(parts),
        "gnss_overlap": sig,
        "freq_low_mhz": min(band_edges(mode, b)[0] for b in bands if band_edges(mode, b)),
        "freq_high_mhz": max(band_edges(mode, b)[1] for b in bands if band_edges(mode, b)),
    }


def interpretation(bands, mode):
    """One line on what the band pattern is consistent with. A hint, not an attribution."""
    d = describe(bands, mode)
    a_only = bands == ["A"]
    b_only = bands == ["B"]
    if a_only and d["gnss_overlap"]:
        return (f"Emission inside {d['band_text']} only, which contains {', '.join(d['gnss_overlap'])}. "
                "Consistent with a GNSS jammer covering that signal; an L-band radar is also possible.")
    if b_only:
        g = d["gnss_overlap"]
        return (f"Emission inside {d['band_text']} only"
                + (f" (overlaps {', '.join(g)})" if g else " (no GPS signal in this slice)")
                + f". More consistent with a radar or other L-band emitter than a GPS L2 jammer. {RADAR_NOTE}.")
    return (f"Emission across {d['band_text']}: wideband. Consistent with a broadband jammer or a strong L-band radar.")
