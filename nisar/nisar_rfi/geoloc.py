"""Radar coordinates (azimuth time, slant range) to latitude/longitude, from the product's orbit.

Zero-Doppler geometry on the WGS84 ellipsoid at a given height: the ground point P satisfies
|P - S(t)| = r and (P - S(t)) . V(t) = 0, on the radar's look side. NISAR steers to zero
Doppler, so the beam centre at time t points into that plane. Good to a few hundred metres
on flat ground; terrain height h shifts the point across track by about h / tan(incidence).
"""
import numpy as np
from scipy.interpolate import CubicHermiteSpline

A = 6378137.0
F = 1 / 298.257223563
B = A * (1 - F)
E2 = F * (2 - F)
EP2 = (A * A - B * B) / (B * B)


def ecef_to_llh(x, y, z):
    """Geodetic latitude, longitude (degrees) and height (m) from ECEF (Bowring, two passes)."""
    x, y, z = np.asarray(x, float), np.asarray(y, float), np.asarray(z, float)
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    th = np.arctan2(z * A, p * B)
    lat = np.arctan2(z + EP2 * B * np.sin(th) ** 3, p - E2 * A * np.cos(th) ** 3)
    for _ in range(2):
        n = A / np.sqrt(1 - E2 * np.sin(lat) ** 2)
        h = p / np.cos(lat) - n
        lat = np.arctan2(z, p * (1 - E2 * n / (n + h)))
    n = A / np.sqrt(1 - E2 * np.sin(lat) ** 2)
    h = p / np.cos(lat) - n
    return np.degrees(lat), np.degrees(lon), h


def llh_to_ecef(lat, lon, h=0.0):
    lat, lon = np.radians(lat), np.radians(lon)
    n = A / np.sqrt(1 - E2 * np.sin(lat) ** 2)
    return np.array([(n + h) * np.cos(lat) * np.cos(lon), (n + h) * np.cos(lat) * np.sin(lon),
                     (n * (1 - E2) + h) * np.sin(lat)])


class Orbit:
    def __init__(self, t, pos, vel):
        o = np.argsort(t)
        self.t, self.pos, self.vel = np.asarray(t, float)[o], np.asarray(pos, float)[o], np.asarray(vel, float)[o]
        self._p = CubicHermiteSpline(self.t, self.pos, self.vel, axis=0)

    def state(self, t):
        t = np.asarray(t, float)
        return self._p(t), self._p.derivative()(t)


def rdr2geo(orbit, t, r, h=0.0, look="Left", iters=60):
    """lat, lon (degrees) for arrays of azimuth time t (s, orbit epoch) and slant range r (m)."""
    t, r = np.broadcast_arrays(np.asarray(t, float), np.asarray(r, float))
    s, v = orbit.state(t.ravel())
    r = r.ravel()
    vh = v / np.linalg.norm(v, axis=1, keepdims=True)
    down = -s - (np.sum(-s * vh, axis=1, keepdims=True)) * vh          # toward Earth, normal to velocity
    down /= np.linalg.norm(down, axis=1, keepdims=True)
    side = np.cross(vh, down) if str(look).lower().startswith("l") else np.cross(down, vh)
    lo, hi = np.zeros(len(r)), np.full(len(r), np.pi / 2)
    for _ in range(iters):                                             # height rises with look angle here
        mid = (lo + hi) / 2
        p = s + r[:, None] * (np.cos(mid)[:, None] * down + np.sin(mid)[:, None] * side)
        _, _, hh = ecef_to_llh(p[:, 0], p[:, 1], p[:, 2])
        below = hh < h
        lo = np.where(below, mid, lo)
        hi = np.where(below, hi, mid)
    mid = (lo + hi) / 2
    p = s + r[:, None] * (np.cos(mid)[:, None] * down + np.sin(mid)[:, None] * side)
    lat, lon, _ = ecef_to_llh(p[:, 0], p[:, 1], p[:, 2])
    return lat.reshape(t.shape), lon.reshape(t.shape)


def geo2rdr(orbit, lat, lon, h=0.0, iters=30):
    """Zero-Doppler time and slant range of a ground point (for checks and site predictions)."""
    p = llh_to_ecef(lat, lon, h)
    t = float(orbit.t.mean())
    for _ in range(iters):
        s, v = orbit.state(t)
        dt = np.dot(p - s, v) / np.dot(v, v)
        t += dt
        if abs(dt) < 1e-6:
            break
    s, _ = orbit.state(t)
    return t, float(np.linalg.norm(p - s))
