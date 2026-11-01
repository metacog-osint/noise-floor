# SMOS browse brightness temperatures: known-answer test against long-range radars (pre-registration, 31 Oct 2026)

**Tool:** `tools/smos_rfi.py` (ESA's SMOS Level 1C browse product `MIR_BWLF1C`, from the Copernicus Data Space Ecosystem
with the CDSE keys already held). **Plan:** `docs/space-sensors-plan.md`, developed on Tom's 30 Oct request for every
satellite option.

Sections 1–3 were written and committed before any data from either test week was fetched.

## 1. What was looked at first

- **One half-orbit, used to build the reader.** It started at 00:27 UTC on 29 Oct 2026, outside both test weeks.
- **Flag shares.** The product's RFI flags are set on about 63% of its points, so they can't place emitters.
- **The 25 hottest 5° boxes in that half-orbit.** I printed them, ranked by share of looks above 320 K. None lies in
  the test box below. They were around Novaya Zemlya and the Kara Sea, the Kola Peninsula, Pakistan and western India.
- **SMAP's result for the same sites is known.** SMAP heard 10 of 14 of them (`docs/validation/smap-rfi.md` §5.1). The
  question here is whether SMOS, a second instrument in the same band, also hears them.

## 2. Measure (frozen)

**Why it isn't the product's own flags.** In the browse product the RFI flags are set over most of the globe. They also
draw on ESA's list of known sources (AUX_RFILST), so a test built on them could pass just because ESA had already listed
these radars.

**What it uses instead.**
- The browse product gives one brightness temperature per grid point and overpass, at 42.5° incidence, in the antenna's
  X and Y polarisations.
- A **look** is an overpass with both X and Y present.
- A look is **hot** if X or Y is above **320 K**. At L-band, natural surfaces stay below about 300 K, and the Arctic in
  October reads well below that.
- **`share_hot320`** for a grid point and week: hot looks divided by looks. Points with fewer than 8 looks in the week
  are dropped.
- The grid is ESA's fixed SMOS grid (about 15 km between points; SMOS's own resolution is about 30–50 km).

**Premise (unverified).** The AN/FPS-117 transmits in 1215–1400 MHz, below SMOS's 1400–1427 MHz. The premise is that its
out-of-band emission reaches SMOS's band strongly enough to push looks above 320 K. SMAP's result supports the first
part, but a weak contamination of a few kelvin wouldn't count here.

## 3. Sites, data and checks (frozen)

**Sites and groups.** As in SMAP's check (`docs/validation/smap-rfi.md` §5), so the two instruments can be compared
directly:
- **Sites:** the 14 active North Warning System long-range radars, with the same coordinates.
- **Excluded:** Lady Franklin Point (PIN-3). Points within 150 km of it count in neither group.
- **"Near":** every grid point within 40 km of a site.
- **"Far":** every grid point farther than 150 km from all 14 sites, inside the sites' box widened by 2° (about
  51.5–73.3°N, 168.2–54.8°W).
- Near and far point-weeks from the two weeks are pooled.

**Data.** SMOS OPER browse half-orbits whose start falls on each UTC day of two weeks, each week scored on its own:
- 1–7 Oct 2026;
- 20–26 Oct 2026.

These are the weeks SMAP's check used. A half-orbit that can't be read is skipped and reported, not replaced.

| # | Check | Holds if | Fails if |
|---|---|---|---|
| M1 | AUC of `share_hot320`, near vs far (pooled) | ≥ 0.80 | < 0.65 |
| M2 | Sites "heard" (nearest grid point within 40 km has `share_hot320` ≥ 0.25) in both weeks, out of 14 | ≥ 8 | ≤ 4 |
| M3 | Far points with `share_hot320` ≥ 0.25 (pooled) | ≤ 5% | > 15% |

Between the marks the result is "weakened". Reported without marks:
- AUCs at 300 K and 350 K;
- AUC of the share of looks carrying the product's RFI_POINT_SOURCE flag (X polarisation);
- per-site shares, and the highest share within 40 km of each site.

If M1–M3 hold, a SMOS layer would follow the SMAP pattern: a weekly map of grid points with a raised hot share.

## 4. Result (run 31 Oct 2026): fails

**Data.**
- 294 half-orbits over the 14 days, all read; none failed.
- The archive is thin for 1–4 Oct, with 3, 1, 9 and 5 half-orbits; 5–7 Oct and 20–26 Oct hold 23–30 a day.
- Two notes on the downloads:
  - one half-orbit on 3 Oct broke off mid-download and was fetched again whole, with the chunked reader the other
    Copernicus tools use;
  - this PC lost its internet connection during 22 Oct, so that day was fetched again (and 23–26 Oct after it).

  Each re-fetch read the same half-orbits; nothing was replaced.
- Pooled: 613 near point-weeks and 74,782 far ones.
- Because of the early-October gap, three southern sites (Brevoort Island, Saglek, Cartwright) had no point within
  40 km with 8 or more looks in the first week. By the frozen rule they can't count as heard in both weeks.

| # | Check | Result | Verdict |
|---|---|---|---|
| M1 | AUC of `share_hot320`, near vs far | **0.535** (median 0.00 near, 0.00 far) | **fails** (< 0.65) |
| M2 | Sites heard in both weeks | **2 of 14** (Cape Parry, Cape Dyer) | **fails** (≤ 4) |
| M3 | Far points with `share_hot320` ≥ 0.25 | **0.19%** | **holds** (≤ 5%) |

**Reported without marks.**
- AUC at 300 K: 0.546; at 350 K: 0.524.
- AUC of the share of looks with the product's RFI_POINT_SOURCE flag: **0.705** (median 0.30 near, 0.09 far). That flag
  draws on ESA's list of known sources, so it isn't an independent detection.

**Per site** (share of hot looks at the nearest point; week of 1–7 Oct / week of 20–26 Oct):

| Heard | Sites |
|---|---|
| Both weeks | Cape Dyer 0.90 / 0.87; Cape Parry 0.50 / 0.29 |
| Second week only | Cartwright – / 0.30; Brevoort Island – / 0.25 (no point with 8 looks in the first week) |
| Neither | Point Barrow, Oliktok, Barter Island, Cape Lisburne, Shingle Point, Cambridge Bay, Shepherd Bay, Hall Beach, Dewar Lakes, Saglek: 0.00 in both weeks (Shingle Point's highest point within 40 km reached 0.11) |

**What this shows.**
- Looks hotter than any natural surface mark a few of the radars clearly. Cape Dyer reads hot on nearly every look,
  and the background stays quiet (M3).
- Most sites never push SMOS above 320 K, while SMAP flags 10 of the same 14 (`docs/validation/smap-rfi.md` §5.1).
  This test can't tell which of these is the reason:
  - the radars' out-of-band energy adds only a few kelvin in SMOS's band, which the 320 K ceiling ignores;
  - SMOS's coarser reconstruction spreads a point source out;
  - ESA's processing reduces it before the browse product.
- The product's own flag separates sites from background better (AUC 0.705), but it leans on ESA's list of known
  sources and is set over most of the globe.

**Next, if SMOS is taken further.** A measure sensitive to a few kelvin would need a new pre-registered test on new
weeks: a point's brightness against its own surroundings, or the full L1C product with all incidence angles. Until
then SMOS stays a probe, not a source for the map.
