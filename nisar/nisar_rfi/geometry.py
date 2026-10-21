"""Orbit and map geometry helpers."""
import math
from functools import lru_cache

import numpy as np
from pyproj import Geod, Transformer

INCLINATION_DEG = 98.405          # NISAR sun-synchronous orbit
PERIOD_S = 5976.0                 # ~99.6 min at 747 km
EARTH_RATE = 7.2921159e-5
GEOD = Geod(ellps="WGS84")


def ground_track_heading(lat_deg, direction):
    """True heading (deg clockwise from north) of the sub-satellite track at a latitude,
    including Earth rotation. direction: 'A' ascending or 'D' descending."""
    ci = math.cos(math.radians(INCLINATION_DEG))
    cphi = math.cos(math.radians(lat_deg))
    ws = 2 * math.pi / PERIOD_S
    east = ci / cphi - (EARTH_RATE / ws) * cphi
    north = math.sqrt(max(0.0, 1 - (ci / cphi) ** 2))
    if direction == "D":
        north = -north
    return math.degrees(math.atan2(east, north)) % 360


def range_line_azimuth(lat_deg, direction):
    """Azimuth of the cross-track (range) direction, as a line orientation in [0, 180)."""
    return (ground_track_heading(lat_deg, direction) + 90) % 180


@lru_cache(maxsize=64)
def _to_grid(epsg):
    return Transformer.from_crs(4326, epsg, always_xy=True)


@lru_cache(maxsize=64)
def _to_ll(epsg):
    return Transformer.from_crs(epsg, 4326, always_xy=True)


def grid_angle(lat, lon, true_az, epsg):
    """Express a true azimuth as an angle from grid north in a projected CRS."""
    lon2, lat2, _ = GEOD.fwd(lon, lat, true_az, 2000.0)
    t = _to_grid(epsg)
    x1, y1 = t.transform(lon, lat)
    x2, y2 = t.transform(lon2, lat2)
    return math.degrees(math.atan2(x2 - x1, y2 - y1)) % 180


def cell_to_xy(grid, rows, cols):
    return grid["x0"] + np.asarray(cols) * grid["dx"], grid["y0"] + np.asarray(rows) * grid["dy"]


def xy_to_ll(epsg, x, y):
    lon, lat = _to_ll(epsg).transform(x, y)
    return lat, lon


def ll_to_xy(epsg, lat, lon):
    return _to_grid(epsg).transform(lon, lat)


def grid_center_ll(grid):
    ny, nx = grid["co_db"].shape
    x, y = cell_to_xy(grid, ny / 2, nx / 2)
    return xy_to_ll(grid["epsg"], float(x), float(y))


def km_between(lat1, lon1, lat2, lon2):
    return GEOD.inv(lon1, lat1, lon2, lat2)[2] / 1000.0


def line_intersection(lat1, lon1, az1, lat2, lon2, az2):
    """Intersect two lines (point + azimuth, treated as undirected) on a local plane
    around the first point. Returns (lat, lon, crossing_angle_deg) or None."""
    e2, n2 = _enu(lat1, lon1, lat2, lon2)
    d1 = np.array([math.sin(math.radians(az1)), math.cos(math.radians(az1))])
    d2 = np.array([math.sin(math.radians(az2)), math.cos(math.radians(az2))])
    A = np.column_stack([d1, -d2])
    if abs(np.linalg.det(A)) < 1e-6:
        return None
    t, _ = np.linalg.solve(A, np.array([e2, n2]))
    px, py = t * d1
    az = math.degrees(math.atan2(px, py))
    lon, lat, _ = GEOD.fwd(lon1, lat1, az, math.hypot(px, py))
    cross = abs((az1 - az2 + 90) % 180 - 90)
    return lat, lon, cross


def _enu(lat0, lon0, lat, lon):
    az, _, dist = GEOD.inv(lon0, lat0, lon, lat)
    return dist * math.sin(math.radians(az)), dist * math.cos(math.radians(az))
