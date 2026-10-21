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
